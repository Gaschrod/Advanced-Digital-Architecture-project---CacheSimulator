import math, block, response
import pprint

class Cache:
    def __init__(self, name, word_size, block_size, n_blocks, associativity, hit_time, write_time, write_back, logger, next_level=None):
        self.name = name
        self.word_size = word_size
        self.block_size = block_size
        self.n_blocks = n_blocks
        self.associativity = associativity
        self.hit_time = hit_time
        self.write_time = write_time
        self.write_back = write_back
        self.logger = logger
        
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


    def read(self, address, current_step):
        r = None
        if not self.next_level:
            r = response.Response({self.name:True}, self.hit_time)
        else:
            block_offset, index, tag = self.parse_address(address)
            in_cache = list(self.data[index].keys())

            if tag in in_cache:
                self.data[index][tag].read(current_step)
                r = response.Response({self.name:True}, self.hit_time)
            else:
                if len(in_cache) < self.associativity:
                    # No eviction needed, just fetch
                    r = self.next_level.read(address, current_step)
                    r.deepen(self.write_time, self.name)
                    self.data[index][tag] = block.Block(self.block_size, current_step, False, address)
                else:
                    # Step 1: Find LRU block
                    oldest_tag = in_cache[0]
                    for b in in_cache:
                        if self.data[index][b].last_accessed < self.data[index][oldest_tag].last_accessed:
                            oldest_tag = b

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
                else:
                    self.logger.info('\tWriting through block ' + address + ' to ' + self.next_level.name)
                    self.data[index][tag] = block.Block(self.block_size, current_step, from_cpu, address)
                    r = self.next_level.write(address, from_cpu, current_step)
                    r.deepen(self.write_time, self.name)
            
            elif len(in_cache) == self.associativity:
                # Step 1: Find LRU block
                oldest_tag = in_cache[0]
                for b in in_cache:
                    if self.data[index][b].last_accessed < self.data[index][oldest_tag].last_accessed:
                        oldest_tag = b

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

                else:
                    # Step 2b: Write-through — propagate write downward
                    # No write-allocate for write-through policy
                    self.logger.info('\tWriting through block ' + address + ' to ' + self.next_level.name)
                    r = self.next_level.write(address, from_cpu, current_step)
                    r.deepen(self.write_time, self.name)

                    # Step 3b: Delete and replace evicted block
                    del self.data[index][oldest_tag]
                    self.data[index][tag] = block.Block(self.block_size, current_step, from_cpu, address)

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


class InvalidOpError(Exception):
    pass