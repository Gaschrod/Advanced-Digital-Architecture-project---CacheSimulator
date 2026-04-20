import math, block, response, random
import pprint

class Cache:
    def __init__(self, name, word_size, block_size, n_blocks, associativity, hit_time, write_time, write_back, logger, next_level=None, policy='LRU', core_id=None, is_shared=False):
        self.name = name
        self.word_size = word_size
        self.block_size = block_size
        self.n_blocks = n_blocks
        self.associativity = associativity
        self.hit_time = hit_time
        self.write_time = write_time
        self.write_back = write_back
        self.logger = logger
        self.policy = policy
        self.core_id = core_id  # Which core owns this cache (None for shared caches)
        self.is_shared = is_shared  # Is this a shared cache (L2/L3)?

        self.n_sets = int(n_blocks / associativity)
        self.data = {}
        self.next_level = next_level

        self.block_offset_size = int(math.log(self.block_size, 2))
        self.index_size = int(math.log(self.n_sets, 2))

        if next_level:
            for i in range(self.n_sets):
                index = str(bin(i))[2:].zfill(self.index_size)
                if index == '':
                    index = '0'
                self.data[index] = {}

    def eviction(self, index):        
        match self.policy:
            case 'lru':                
                return self.LRU_policy(index)
            case 'mru':
                return self.MRU_policy(index)
            case 'lfu':
                return self.LFU_policy(index)
            case 'nru':
                return self.NRU_policy(index)
            case 'fifo':               
                return self.FIFO_policy(index)
            case 'lifo':
                return self.LIFO_policy(index)
            case 'filo':
                return self.FILO_policy(index)
            case 'random':             
                return self.random_policy(index)
            case _:                    
                raise ValueError(f"Unknown eviction policy: {self.policy}")  

    def LRU_policy(self, index):
        return min(self.data[index], key=lambda tag: self.data[index][tag].last_accessed)
    
    def MRU_policy(self, index):
        return max(self.data[index], key=lambda tag: self.data[index][tag].last_accessed)
    
    def LFU_policy(self, index):
        return min(self.data[index], key=lambda tag: self.data[index][tag].access_count)
    
    def NRU_policy(self, index):
        # NRU uses a per-block reference bit: prefer blocks with bit=0.
        # If all are referenced, clear the set's bits and choose among all blocks.
        candidates = [
            tag for tag, blk in self.data[index].items()
            if not getattr(blk, 'referenced', False)
        ]
        if not candidates:
            for blk in self.data[index].values():
                blk.referenced = False
            candidates = list(self.data[index].keys())

        return min(candidates, key=lambda tag: self.data[index][tag].insertion_time)

    def FIFO_policy(self, index):
        return min(self.data[index], key=lambda tag: self.data[index][tag].insertion_time)
    
    def LIFO_policy(self, index):
        return max(self.data[index], key=lambda tag: self.data[index][tag].insertion_time)

    def FILO_policy(self, index):
        return max(self.data[index], key=lambda tag: self.data[index][tag].insertion_time)

    def random_policy(self, index):
        return random.choice(list(self.data[index].keys()))

    def mark_referenced(self, index, tag):
        self.data[index][tag].referenced = True


    def read(self, address, current_step):
        r = None
        if not self.next_level:
            r = response.Response({self.name:True}, self.hit_time)
        else:
            block_offset, index, tag = self.parse_address(address)
            in_cache = list(self.data[index].keys())

            if tag in in_cache:
                self.data[index][tag].read(current_step)
                self.mark_referenced(index, tag)
                r = response.Response({self.name:True}, self.hit_time)
            else:
                if len(in_cache) < self.associativity:
                    # No eviction needed, just fetch
                    r = self.next_level.read(address, current_step)
                    r.deepen(self.write_time, self.name)
                    self.data[index][tag] = block.Block(self.block_size, current_step, False, address)
                    self.mark_referenced(index, tag)
                else:
                    # Step 1: Find block to evict based on policy
                    oldest_tag = self.eviction(index)

                    # Step 2: Write back dirty block FIRST before fetching new one
                    writeback_time = 0
                    if self.write_back:
                        if self.data[index][oldest_tag].is_dirty():
                            self.logger.info('\tWriting back block ' + self.data[index][oldest_tag].address + ' to ' + self.next_level.name)
                            temp = self.next_level.write(self.data[index][oldest_tag].address, True, current_step)
                            writeback_time = temp.time

                    # Step 3: Delete evicted block
                    del self.data[index][oldest_tag]

                    # Step 4: Fetch new block AFTER write-back
                    r = self.next_level.read(address, current_step)
                    r.deepen(self.write_time, self.name)
                    r.time += writeback_time

                    # Step 5: Insert new block
                    self.data[index][tag] = block.Block(self.block_size, current_step, False, address)
                    self.mark_referenced(index, tag)

        return r


    def write(self, address, from_cpu, current_step):
        r = None
        if not self.next_level:
            r = response.Response({self.name:True}, self.write_time)
        else:
            block_offset, index, tag = self.parse_address(address)
            in_cache = list(self.data[index].keys())

            if tag in in_cache:
                self.data[index][tag].write(current_step)
                self.mark_referenced(index, tag)
                if self.write_back:
                    r = response.Response({self.name:True}, self.write_time)
                else:
                    self.logger.info('\tWriting through block ' + address + ' to ' + self.next_level.name)
                    r = self.next_level.write(address, from_cpu, current_step)
                    r.deepen(self.write_time, self.name)
            
            elif len(in_cache) < self.associativity:
                if self.write_back:
                    # Write-allocate: fetch block from lower level first, then write locally
                    r = self.next_level.read(address, current_step)
                    r.deepen(self.write_time, self.name)
                    self.data[index][tag] = block.Block(self.block_size, current_step, True, address)
                    self.mark_referenced(index, tag)
                else:
                    # Write-No-Allocate for write-through policy misses
                    self.logger.info('\tWriting through block ' + address + ' to ' + self.next_level.name)
                    r = self.next_level.write(address, from_cpu, current_step)
                    r.deepen(self.hit_time, self.name) # Miss penalty to check tags
            
            elif len(in_cache) == self.associativity:
                # Step 1: Find block to evict based on policy
                oldest_tag = self.eviction(index)

                if self.write_back:
                    # Step 2a: Write back dirty evicted block FIRST
                    writeback_time = 0
                    if self.data[index][oldest_tag].is_dirty():
                        self.logger.info('\tWriting back block ' + self.data[index][oldest_tag].address + ' to ' + self.next_level.name)
                        temp = self.next_level.write(self.data[index][oldest_tag].address, from_cpu, current_step)
                        writeback_time = temp.time

                    # Step 3a: Delete evicted block
                    del self.data[index][oldest_tag]

                    # Step 4a: Write-allocate fetch AFTER write-back
                    r = self.next_level.read(address, current_step)
                    r.deepen(self.write_time, self.name)
                    r.time += writeback_time

                    # Step 5a: Insert new dirty block
                    self.data[index][tag] = block.Block(self.block_size, current_step, True, address)
                    self.mark_referenced(index, tag)

                else:
                    # Step 2b: Write-through — propagate write downward
                    # No write-allocate for write-through policy
                    self.logger.info('\tWriting through block ' + address + ' to ' + self.next_level.name)
                    r = self.next_level.write(address, from_cpu, current_step)
                    r.deepen(self.write_time, self.name)

        return r


    def flush(self, address, current_step):
        r = None
        if not self.next_level:
            r = response.Response({self.name: True}, self.write_time)
        else:
            block_offset, index, tag = self.parse_address(address)
            in_cache = list(self.data[index].keys())
            if tag in in_cache:
                if self.data[index][tag].is_dirty():
                    # Dirty: pay write cost and propagate all the way to memory
                    r = self.next_level.flush(address, current_step)
                    r.deepen(self.write_time, self.name)
                else:
                    # Clean: still propagate to invalidate lower levels
                    # but no write cost at this level
                    r = self.next_level.flush(address, current_step)
                    r.deepen(0, self.name)
                del self.data[index][tag]  # always invalidate
            else:
                # Not found here, keep propagating down
                r = self.next_level.flush(address, current_step)
                r.deepen(self.hit_time, self.name)
        return r


    def flush_all(self, current_step):
        r = None
        if not self.next_level:
            r = response.Response({self.name:True}, self.write_time)
        else:
            r = response.Response({self.name:True}, 0)
            for index in self.data.keys():
                for tag in self.data[index].keys():
                    address = self.data[index][tag].address
                    if self.data[index][tag].is_dirty():
                        self.logger.info('\tFlushing block ' + address + ' to memory')
                        temp = self.next_level.flush(address, current_step)
                        temp.deepen(self.write_time, self.name)
                        r.time += temp.time
            # Reinitialize all sets
            self.data = {}
            for i in range(self.n_sets):
                index = str(bin(i))[2:].zfill(self.index_size)
                if index == '':
                    index = '0'
                self.data[index] = {}
            # Recursively flush all lower levels
            if self.next_level.next_level:
                self.next_level.flush_all(current_step)
        return r

    def parse_address(self, address):
        address_size = len(address) * 4
        binary_address = bin(int(address, 16))[2:].zfill(address_size)

        block_offset = binary_address[-self.block_offset_size:]
        index = binary_address[-(self.block_offset_size+self.index_size):-self.block_offset_size]
        if index == '':
            index = '0'
        tag = binary_address[:-(self.block_offset_size+self.index_size)]
        return (block_offset, index, tag)

    # ==================== Coherence Methods for Multi-Core ====================

    def get_coherence_state(self, address):
        """Get coherence state of a block ('M', 'S', or 'I')"""
        block_offset, index, tag = self.parse_address(address)

        if index not in self.data or tag not in self.data[index]:
            return 'I'  # Not present = Invalid

        return self.data[index][tag].get_coherence_state()

    def invalidate_block(self, address):
        """Invalidate a block (coherence callback from bus)"""
        block_offset, index, tag = self.parse_address(address)

        if index in self.data and tag in self.data[index]:
            state = self.data[index][tag].get_coherence_state()
            self.logger.info(f'\t[Core {self.core_id} L1] Invalidating {address} (was in state {state})')
            # Remove the block
            del self.data[index][tag]

    def downgrade_to_shared(self, address):
        """Downgrade block from Modified to Shared (bus intervention)"""
        block_offset, index, tag = self.parse_address(address)

        if index in self.data and tag in self.data[index]:
            self.logger.info(f'\t[Core {self.core_id} L1] Downgrading {address} from M to S')
            self.data[index][tag].set_coherence_state('S')
            self.data[index][tag].clean()  # No longer dirty

    def upgrade_to_modified(self, address):
        """Upgrade block from Shared to Modified"""
        block_offset, index, tag = self.parse_address(address)

        if index in self.data and tag in self.data[index]:
            self.logger.info(f'\t[Core {self.core_id} L1] Upgrading {address} from S to M')
            self.data[index][tag].set_coherence_state('M')

    def install_block(self, address, coherence_state, current_step):
        """Install a new block with given coherence state"""
        block_offset, index, tag = self.parse_address(address)

        # May need eviction if set is full
        if len(self.data[index]) >= self.associativity:
            oldest_tag = self.eviction(index)

            # Write back dirty block if needed
            if self.write_back and self.data[index][oldest_tag].is_dirty():
                self.logger.info(f'\t[Core {self.core_id} L1] Evicting dirty block {self.data[index][oldest_tag].address}')
                # In multi-core, eviction should notify directory (handled by core/bus layer)

            del self.data[index][oldest_tag]

        # Install new block
        dirty = (coherence_state == 'M')
        self.data[index][tag] = block.Block(self.block_size, current_step, dirty, address, coherence_state)
        self.mark_referenced(index, tag)
        self.logger.info(f'\t[Core {self.core_id} L1] Installed {address} in state {coherence_state}')

    def supply_data(self, address):
        """Supply data to another cache (coherence callback for intervention)"""
        block_offset, index, tag = self.parse_address(address)

        if index in self.data and tag in self.data[index]:
            self.logger.info(f'\t[Core {self.core_id} L1] Supplying data for {address}')
            # Return a copy of the block (simulated)
            return self.data[index][tag]
        return None

    def local_read(self, address, current_step):
        """Local read without coherence check (coherence already validated)"""
        block_offset, index, tag = self.parse_address(address)

        if index in self.data and tag in self.data[index]:
            self.data[index][tag].read(current_step)
            self.mark_referenced(index, tag)
            return response.Response({self.name: True}, self.hit_time)
        else:
            # Should not happen if coherence protocol is correct
            self.logger.error(f'\t[Core {self.core_id} L1] local_read() called but block {address} not present!')
            return response.Response({self.name: False}, 0)

    def local_write(self, address, current_step):
        """Local write without coherence check (coherence already validated)"""
        block_offset, index, tag = self.parse_address(address)

        if index in self.data and tag in self.data[index]:
            self.data[index][tag].write(current_step)
            self.mark_referenced(index, tag)
            # Ensure Modified state
            self.data[index][tag].set_coherence_state('M')
            return response.Response({self.name: True}, self.write_time)
        else:
            # Should not happen if coherence protocol is correct
            self.logger.error(f'\t[Core {self.core_id} L1] local_write() called but block {address} not present!')
            return response.Response({self.name: False}, 0)


class InvalidOpError(Exception):
    pass