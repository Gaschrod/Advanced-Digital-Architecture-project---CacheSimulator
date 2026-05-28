import math, block, response, random
import pprint


class Cache:
    def __init__(
        self,
        name,
        word_size,
        block_size,
        n_blocks,
        associativity,
        hit_time,
        write_time,
        write_back,
        logger,
        next_level=None,
        policy="LRU",
        core_id=None,
        is_shared=False,
    ):
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
        self.flush_hit_time = (
            self.hit_time + self.write_time
        )  # This is an oversimplification but for the purpose of academic learning, we assume that when there's data to write back,
        # we pay both the hit time to check tags and the write time to flush dirty block
        # In reality the time of execution would depend on the specific implementation and hardware architecture
        self.flush_miss_time = self.hit_time

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
                if index == "":
                    index = "0"
                self.data[index] = {}

    def eviction(self, index):
        """Dispatch to the configured eviction policy and select a tag to evict.

        Args:
            index (str): Binary string representing the set index.

        Returns:
            str: Tag selected for eviction.

        Raises:
            ValueError: If self.policy does not match a known policy.
        """
        match self.policy:
            case "lru":
                return self.LRU_policy(index)
            case "mru":
                return self.MRU_policy(index)
            case "lfu":
                return self.LFU_policy(index)
            case "nru":
                return self.NRU_policy(index)
            case "fifo":
                return self.FIFO_policy(index)
            case "lifo":
                return self.LIFO_policy(index)
            case "random":
                return self.random_policy(index)
            case _:
                raise ValueError(f"Unknown eviction policy: {self.policy}")

    def LRU_policy(self, index):
        """Least-Recently-Used (LRU) policy.

        Selects the tag whose block has the smallest last_accessed timestamp
        (i.e. the block that was used the longest time ago).

        Args:
            index (str): Set index whose blocks are considered.

        Returns:
            str: Tag selected for eviction.
        """
        return min(
            self.data[index], key=lambda tag: self.data[index][tag].last_accessed
        )

    def MRU_policy(self, index):
        """Most-Recently-Used (MRU) policy.

        Selects the tag whose block has the largest last_accessed timestamp
        (i.e. the block that was used most recently). Typically used less
        frequently than LRU.

        Args:
            index (str): Set index whose blocks are considered.

        Returns:
            str: Tag selected for eviction.
        """
        return max(
            self.data[index], key=lambda tag: self.data[index][tag].last_accessed
        )

    def LFU_policy(self, index):
        """Least-Frequently-Used (LFU) policy.

        Selects the tag whose block has the smallest access_count (fewest
        accesses). Ties are resolved by the min() function which choses the first minimum it encounters.

        Args:
            index (str): Set index whose blocks are considered.

        Returns:
            str: Tag selected for eviction.
        """
        return min(self.data[index], key=lambda tag: self.data[index][tag].access_count)

    def NRU_policy(self, index):
        """Not-Recently-Used (NRU) policy (simple reference-bit variant).

        NRU prefers blocks whose per-block 'referenced' bit is False. If at
        least one block is unreferenced, choose among those. If all blocks are
        referenced, clear the referenced bits for the entire set and then
        choose using insertion_time as a deterministic tie-breaker (oldest
        insertion wins).

        Notes:
            - This is a simplified NRU implementation (single reference bit per
              block) and does not implement the full 4-class NRU classification.

        Args:
            index (str): Set index whose blocks are considered.

        Returns:
            str: Tag selected for eviction.
        """
        candidates = [
            tag
            for tag, blk in self.data[index].items()
            if not getattr(blk, "referenced", False)
        ]
        if not candidates:
            for blk in self.data[index].values():
                blk.referenced = False
            candidates = list(self.data[index].keys())

        return min(candidates, key=lambda tag: self.data[index][tag].insertion_time)

    def FIFO_policy(self, index):
        """First-In-First-Out (FIFO) policy.

        Evicts the block with the smallest insertion_time (the oldest inserted
        block in the set).

        Args:
            index (str): Set index whose blocks are considered.

        Returns:
            str: Tag selected for eviction.
        """
        return min(
            self.data[index], key=lambda tag: self.data[index][tag].insertion_time
        )

    def LIFO_policy(self, index):
        """Last-In-First-Out (LIFO) policy.

        Evicts the most recently inserted block (largest insertion_time).

        Args:
            index (str): Set index whose blocks are considered.

        Returns:
            str: Tag selected for eviction.
        """
        return max(
            self.data[index], key=lambda tag: self.data[index][tag].insertion_time
        )

    def random_policy(self, index):
        """Random eviction policy.

        Chooses a tag uniformly at random from the set. Useful for testing or
        policy comparison.

        Args:
            index (str): Set index whose blocks are considered.

        Returns:
            str: Tag selected for eviction.
        """
        return random.choice(list(self.data[index].keys()))

    def mark_referenced(self, index, tag):
        """Mark the referenced flag for a block to True

        This is used by replacement policies to track recent usage.
        """
        self.data[index][tag].referenced = True

    def read(self, address, current_step):
        """Execute a read access for the given hexadecimal address.

        Behavior summary:
        - If this cache has no next level, return a hit response with this
          cache's hit_time (terminal level).
        - Otherwise parse the address into (block_offset, index, tag) and:
          * On hit: update the block metadata (access time), mark it as
            referenced and return a hit response.
          * On miss with free space in the set: fetch the block from the next
            level, insert it as a clean block, and return the aggregated
            response time (including this cache's write_time for allocation).
          * On miss and set full: select a victim via the configured eviction
            policy. If write-back is enabled and the victim is dirty, write it
            back to the next level before fetching the requested block. Insert
            the fetched block and return the aggregated response including any
            write-back time.

        Args:
            address (str): Hexadecimal address string (without 0x prefix).
            current_step (int): Current simulation step for timestamping.

        Returns:
            response.Response: Response object containing hit_list and the
            accumulated access time for this operation.
        """
        r = None
        if not self.next_level:
            r = response.Response({self.name: True}, self.hit_time)
        else:
            block_offset, index, tag = self.parse_address(address)
            in_cache = list(self.data[index].keys())

            if tag in in_cache:
                self.data[index][tag].read(current_step)
                self.mark_referenced(index, tag)
                r = response.Response({self.name: True}, self.hit_time)
            else:
                if len(in_cache) < self.associativity:
                    # No eviction needed, just fetch
                    r = self.next_level.read(address, current_step)
                    r.deepen(self.write_time, self.name)
                    self.data[index][tag] = block.Block(
                        self.block_size, current_step, False, address
                    )
                    self.mark_referenced(index, tag)
                else:
                    # Step 1: Find block to evict based on policy
                    oldest_tag = self.eviction(index)

                    # Step 2: Write back dirty block FIRST before fetching new one
                    writeback_time = 0
                    if self.write_back:
                        if self.data[index][oldest_tag].is_dirty():
                            self.logger.info(
                                "\tWriting back block "
                                + self.data[index][oldest_tag].address
                                + " to "
                                + self.next_level.name
                            )
                            temp = self.next_level.write(
                                self.data[index][oldest_tag].address, True, current_step
                            )
                            writeback_time = temp.time

                    # Step 3: Delete evicted block
                    del self.data[index][oldest_tag]

                    # Step 4: Fetch new block AFTER write-back
                    r = self.next_level.read(address, current_step)
                    r.deepen(self.write_time, self.name)
                    r.time += writeback_time

                    # Step 5: Insert new block
                    self.data[index][tag] = block.Block(
                        self.block_size, current_step, False, address
                    )
                    self.mark_referenced(index, tag)

        return r

    def compute_flush_time(self):
        """Compute the flush time from this level down to memory (base case when there are no data to evict).

        The base flush time equals the sum of `hit_time` for every cache
        level from this cache down to (but not including) the terminal
        level, plus the terminal level's `write_time` (main memory).
        """
        time = 0
        cur = self
        # Sum hit_time for every cache that has a next_level
        while cur and cur.next_level:
            time += cur.hit_time
            cur = cur.next_level
        # cur is now the terminal level (no next_level)
        if cur:
            time += getattr(cur, "write_time", cur.hit_time)
        return time

    def scan_for_presence(self, address):
        """Scan this cache and lower levels for the presence of data in line.

        Returns a list of tuples (level_obj, level_name, present_bool, is_dirty_bool)
        ordered from this level down to the terminal level.
        """
        res = []
        cur = self
        while cur:
            _, index, tag = cur.parse_address(address)
        
            present = False
            dirty = False
            if index in cur.data and tag in cur.data[index]:
                present = True
                dirty = cur.data[index][tag].is_dirty()

            res.append((cur, cur.name, present, dirty))
            if not cur.next_level:
                break
            cur = cur.next_level

        return res

    def write(self, address, from_cpu, current_step):
        """Execute a write access for the given hexadecimal address.

        Behavior summary:
        - If this cache has no next level, return a hit response with this
          cache's write_time (terminal level).
        - Otherwise parse the address into (block_offset, index, tag) and:
          * On hit: update the block metadata, mark referenced. If write-back
            is enabled the write is completed locally and a local write-time
            response is returned; otherwise the write is propagated to the
            next level (write-through).
          * On miss with free space in the set:
            - write-back (write-allocate): fetch the block from the next
              level, insert it as dirty and return the aggregated time.
            - write-through (no-write-allocate): forward the write to the
              next level and account for tag-check timing.
          * On miss when the set is full: select a victim via the eviction
            policy. If write-back is enabled and the victim is dirty, write
            it back prior to any allocation. Allocation semantics follow the
            write-back / write-through policies described above.

        Args:
            address (str): Hexadecimal address string (without 0x prefix).
            from_cpu (bool): True when the write originates from the CPU; the
                flag is forwarded to lower levels when propagating writes.
            current_step (int): Current simulation step for timestamping.

        Returns:
            response.Response: Response object containing hit_list and the
            accumulated access time for this operation.
        """
        r = None
        if not self.next_level:
            r = response.Response({self.name: True}, self.write_time)
        else:
            block_offset, index, tag = self.parse_address(address)
            in_cache = list(self.data[index].keys())

            if tag in in_cache:
                self.data[index][tag].write(current_step)
                self.mark_referenced(index, tag)
                if self.write_back:
                    r = response.Response({self.name: True}, self.write_time)
                else:
                    self.logger.info(
                        "\tWriting through block "
                        + address
                        + " to "
                        + self.next_level.name
                    )
                    r = self.next_level.write(address, from_cpu, current_step)
                    r.deepen(self.write_time, self.name)

            elif len(in_cache) < self.associativity:
                if self.write_back:
                    # Write-allocate: fetch block from lower level first, then write locally
                    r = self.next_level.read(address, current_step)
                    r.deepen(self.write_time, self.name)
                    self.data[index][tag] = block.Block(
                        self.block_size, current_step, True, address
                    )
                    self.mark_referenced(index, tag)
                else:
                    # Write-No-Allocate for write-through policy misses
                    self.logger.info(
                        "\tWriting through block "
                        + address
                        + " to "
                        + self.next_level.name
                    )
                    r = self.next_level.write(address, from_cpu, current_step)
                    r.deepen(self.hit_time, self.name)  # Miss penalty to check tags

            elif len(in_cache) == self.associativity:
                # Step 1: Find block to evict based on policy
                oldest_tag = self.eviction(index)

                if self.write_back:
                    # Step 2a: Write back dirty evicted block FIRST
                    writeback_time = 0
                    if self.data[index][oldest_tag].is_dirty():
                        self.logger.info(
                            "\tWriting back block "
                            + self.data[index][oldest_tag].address
                            + " to "
                            + self.next_level.name
                        )
                        temp = self.next_level.write(
                            self.data[index][oldest_tag].address, from_cpu, current_step
                        )
                        writeback_time = temp.time

                    # Step 3a: Delete evicted block
                    del self.data[index][oldest_tag]

                    # Step 4a: Write-allocate fetch AFTER write-back
                    r = self.next_level.read(address, current_step)
                    r.deepen(self.write_time, self.name)
                    r.time += writeback_time

                    # Step 5a: Insert new dirty block
                    self.data[index][tag] = block.Block(
                        self.block_size, current_step, True, address
                    )
                    self.mark_referenced(index, tag)

                else:
                    # Step 2b: Write-through — propagate write downward
                    # No write-allocate for write-through policy
                    self.logger.info(
                        "\tWriting through block "
                        + address
                        + " to "
                        + self.next_level.name
                    )
                    r = self.next_level.write(address, from_cpu, current_step)
                    r.deepen(self.write_time, self.name)

        return r

    def flush(self, address, current_step):
        """Flush a single block corresponding to address from this cache.

        Timing model:
        - Normal case (miss): tag-check cost at each level + write_time in main memory (terminal level).
        - Hit: the accumulated flush time is doubled to account for the write-back or eviction cost. 
        This is a simplification for the purpose of this project; in a real system the flush time would depend 
        on the specific implementation and hardware architecture.        

        Args:
            address (str): Hexadecimal address string (without 0x prefix).
            current_step (int): Current simulation step for timestamping.

        Returns:
            response.Response: Response object representing the flush timing
            and hit information.
        """
        # Compute baseline flush time (no-data path)
        base_time = self.compute_flush_time()

        # Scan hierarchy for presence of the block
        presence = self.scan_for_presence(address)

        # Determine whether any cache level (excluding terminal memory) contained data
        mem_name = presence[-1][1] if presence else None
        data_present = any(p for (_lvl, name, p, _d) in presence if name != mem_name)

        # Perform state changes: write back dirty blocks and remove the block
        # from any cache level where it is present.
        for (lvl, name, present, dirty) in presence:
            if not present:
                continue
            if dirty and lvl.next_level:
                # Write back dirty block to the next level to update state.                
                lvl.next_level.write(address, True, current_step)
            # Remove the block from this cache level
            _, idx, tg = lvl.parse_address(address)
            if idx in lvl.data and tg in lvl.data[idx]:
                del lvl.data[idx][tg]

        # Build hit_list mapping (True if present at that level before eviction)
        hit_list = {name: present for (_lvl, name, present, _d) in presence}

        # Final time: doubled if any data was present (clean or dirty) in caches
        final_time = base_time * (2 if data_present else 1)

        return response.Response(hit_list, final_time)

    def flush_all(self, current_step):
        """Flush all dirty blocks from this cache to lower levels and reset.

        Iterates over all sets in this cache and for each dirty block invokes
        next_level.flush to propagate data to lower levels. The cumulative time
        spent flushing (including per-block tag/write-back costs) is returned
        in the response. After flushing, this cache's sets are reinitialized
        (cache emptied). If there are further lower levels, the flush_all
        operation is recursively invoked on them.

        Args:
            current_step (int): Current simulation step for timestamping.

        Returns:
            response.Response: Response object containing the total time
            consumed by the flush_all operation for this cache.
        """
        if not self.next_level:
            # Terminal level: no intrinsic flush_all cost
            return response.Response({self.name: True}, self.write_time)

        # Collect all addresses currently cached here
        addresses = []
        for index in list(self.data.keys()):
            for tag in list(self.data[index].keys()):
                addresses.append(self.data[index][tag].address)

        total_time = 0
        for addr in addresses:
            # flush() will evict the block from all levels and return the
            # appropriate time (doubled if any cache contained the block).
            temp = self.flush(addr, current_step)
            total_time += temp.time

        # Reinitialize all sets locally (should already be empty after flushes)
        self.data = {}
        for i in range(self.n_sets):
            index = str(bin(i))[2:].zfill(self.index_size)
            if index == "":
                index = "0"
            self.data[index] = {}

        # Recursively flush lower levels
        if self.next_level and self.next_level.next_level:
            self.next_level.flush_all(current_step)

        return response.Response({self.name: True}, total_time)

    def parse_address(self, address):
        """Parse a hexadecimal address string into (block_offset, index, tag).

        The address parameter is expected to be a hexadecimal string (without
        a leading "0x"). The method computes the binary representation of the
        address using the configured block_offset_size and index_size and
        returns each component as a binary string.

        Args:
            address (str): Hexadecimal address string.

        Returns:
            tuple[str, str, str]: (block_offset, index, tag) each represented
            as a binary string (index may be "0" when index_size is zero).
        """
        address_size = len(address) * 4
        binary_address = bin(int(address, 16))[2:].zfill(address_size)

        block_offset = binary_address[-self.block_offset_size :]
        index = binary_address[
            -(self.block_offset_size + self.index_size) : -self.block_offset_size
        ]
        if index == "":
            index = "0"
        tag = binary_address[: -(self.block_offset_size + self.index_size)]
        return (block_offset, index, tag)

    # ==================== Coherence Methods for Multi-Core ====================
    # Processor events : PrRd, PrWr
    # Request types    : GetS (read miss), GetM (write miss), Upgrade (write hit on S), Flush (eviction/writeback)
    # States           : M (Modified, exclusive dirty), S (Shared, clean), I (Invalid)

    def get_coherence_state(self, address):
        """Get coherence state of a block ('M', 'S', or 'I')"""
        block_offset, index, tag = self.parse_address(address)

        if index not in self.data or tag not in self.data[index]:
            return "I"  # Not present = Invalid

        return self.data[index][tag].get_coherence_state()

    def invalidate_block(self, address):
        """Invalidate a block on a directory-triggered coherence message.

        - GetM (via Inv)     : S → I
        - GetM (via FetchInv): M → I
        - Upgrade (via Inv)  : S → I
        """

        block_offset, index, tag = self.parse_address(address)

        if index in self.data and tag in self.data[index]:
            state = self.data[index][tag].get_coherence_state()
            self.logger.info(
                f"\t[Core {self.core_id} L1] Invalidating {address} (was in state {state})"
            )
            # Remove the block
            del self.data[index][tag]

    def downgrade_to_shared(self, address):
        """Downgrade block from Modified to Shared on GetS intervention (M → S, Flush)."""
        block_offset, index, tag = self.parse_address(address)

        if index in self.data and tag in self.data[index]:
            self.logger.info(
                f"\t[Core {self.core_id} L1] Downgrading {address} from M to S"
            )
            self.data[index][tag].set_coherence_state("S")
            self.data[index][tag].clean()  # No longer dirty

    def upgrade_to_modified(self, address):
        """Upgrade block from Shared to Modified on Upgrade request (S → M, no data fetch)."""
        block_offset, index, tag = self.parse_address(address)

        if index in self.data and tag in self.data[index]:
            self.logger.info(
                f"\t[Core {self.core_id} L1] Upgrading {address} from S to M"
            )
            self.data[index][tag].set_coherence_state("M")

    def install_block(self, address, coherence_state, current_step):
        """Install a new block with given coherence state.

        Returns (evicted_address, evicted_state, evicted_is_dirty, writeback_time)
        if a block was evicted, otherwise None.
        """
        block_offset, index, tag = self.parse_address(address)

        eviction_result = None
        if len(self.data[index]) >= self.associativity:
            oldest_tag = self.eviction(index)
            evicted = self.data[index][oldest_tag]
            evicted_address = evicted.address
            evicted_state = evicted.get_coherence_state()
            evicted_dirty = evicted.is_dirty()

            writeback_time = 0
            if self.write_back and evicted_dirty:
                self.logger.info(
                    f"\t[Core {self.core_id} L1] Evicting dirty block {evicted_address} (write-back to L2)"
                )
                wb = self.next_level.write(evicted_address, True, current_step)
                writeback_time = wb.time

            del self.data[index][oldest_tag]
            eviction_result = (
                evicted_address,
                evicted_state,
                evicted_dirty,
                writeback_time,
            )

        # Install new block
        dirty = coherence_state == "M"
        self.data[index][tag] = block.Block(
            self.block_size, current_step, dirty, address, coherence_state
        )
        self.mark_referenced(index, tag)
        self.logger.info(
            f"\t[Core {self.core_id} L1] Installed {address} in state {coherence_state}"
        )
        return eviction_result

    def supply_data(self, address):
        """Supply data during Flush intervention (GetS M→S or GetM M→I)."""
        block_offset, index, tag = self.parse_address(address)

        if index in self.data and tag in self.data[index]:
            self.logger.info(f"\t[Core {self.core_id} L1] Supplying data for {address}")
            # Return a copy of the block (simulated)
            return self.data[index][tag]
        return None

    def local_read(self, address, current_step):
        """Perform a local read after coherence is satisfied (PrRd hit: M→M or S→S)."""
        block_offset, index, tag = self.parse_address(address)

        if index in self.data and tag in self.data[index]:
            self.data[index][tag].read(current_step)
            self.mark_referenced(index, tag)
            return response.Response({self.name: True}, self.hit_time)
        else:
            # Should not happen if coherence protocol is correct
            self.logger.error(
                f"\t[Core {self.core_id} L1] local_read() called but block {address} not present!"
            )
            return response.Response({self.name: False}, 0)

    def local_write(self, address, current_step):
        """Perform a local write after coherence is satisfied (PrWr hit: M→M, or after GetM/Upgrade installs M)."""
        block_offset, index, tag = self.parse_address(address)

        if index in self.data and tag in self.data[index]:
            self.data[index][tag].write(current_step)
            self.mark_referenced(index, tag)
            # Ensure Modified state
            self.data[index][tag].set_coherence_state("M")
            return response.Response({self.name: True}, self.write_time)
        else:
            # Should not happen if coherence protocol is correct
            self.logger.error(
                f"\t[Core {self.core_id} L1] local_write() called but block {address} not present!"
            )
            return response.Response({self.name: False}, 0)


class InvalidOpError(Exception):
    pass
