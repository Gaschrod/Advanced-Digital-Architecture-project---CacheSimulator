import response


class Bus:
    """System bus/interconnect for cache coherence messages"""

    def __init__(self, directory, shared_cache, logger):
        self.directory = directory
        self.shared_cache = shared_cache  # Shared L2 cache
        self.cores = {}  # core_id -> Core object
        self.logger = logger
        self.transaction_time = 5  # Bus transaction overhead in cycles
        self.cache_to_cache_time = 10  # Cache-to-cache transfer time

    def register_core(self, core):
        """Register a core on the bus"""
        self.cores[core.core_id] = core
        self.logger.info(f"[Bus] Registered Core {core.core_id}")

    def coherent_read(self, core_id, address, current_step):
        """Handle coherent read request (BusRd)

        Called when a core has a read miss and needs to fetch the block.

        Returns: Response object with timing information
        """
        self.logger.info(f"\t[Bus] Core {core_id} requests BusRd for {address}")

        # Consult directory
        action = self.directory.process_read(core_id, address)

        total_time = self.transaction_time
        data = None

        if action["type"] == "fetch_from_memory":
            # No other cache has it, get from shared L2/memory
            self.logger.info(f"\t[Bus] Fetching from shared cache/memory")
            r = self.shared_cache.read(address, current_step)
            total_time += r.time
            data = r

        elif action["type"] == "fetch_from_owner":
            # Another cache has it in Modified state, need intervention
            owner_id = action["owner"]
            self.logger.info(f"\t[Bus] Intervention: Core {owner_id} must supply data")
            data = self.cores[owner_id].handle_bus_read(address, core_id)
            total_time += self.cache_to_cache_time

        elif action["type"] == "fetch_from_shared":
            # Shared by others, get from shared cache/memory (clean copy)
            self.logger.info(
                f"\t[Bus] Fetching from shared cache (others have clean copies)"
            )
            r = self.shared_cache.read(address, current_step)
            total_time += r.time
            data = r

        # Install block in requesting core's cache in Shared state
        requesting_core = self.cores[core_id]
        eviction = requesting_core.l1_cache.install_block(address, "S", current_step)
        if eviction is not None:
            evicted_addr, evicted_state, evicted_dirty, wb_time = eviction
            total_time += wb_time
            self.directory.process_eviction(core_id, evicted_addr, evicted_dirty)

        # Return response (miss at L1, but fetched successfully)
        return response.Response({f"core_{core_id}_L1": False}, total_time)

    def coherent_write(self, core_id, address, current_step):
        """Handle coherent write request for a miss (BusRdX)

        Called when a core has a write miss and needs exclusive access.

        Returns: Response object with timing information
        """
        self.logger.info(
            f"\t[Bus] Core {core_id} requests BusRdX (write miss) for {address}"
        )

        # Consult directory
        action = self.directory.process_write(core_id, address)

        total_time = self.transaction_time

        # Invalidate all sharers
        if action["invalidate"] and action["sharers"]:
            for sharer_id in action["sharers"]:
                if sharer_id != core_id:
                    self.logger.info(
                        f"\t[Bus] Sending invalidation to Core {sharer_id}"
                    )
                    self.cores[sharer_id].handle_bus_read_exclusive(address, core_id)

        # Get data if needed
        if action["type"] == "fetch_from_memory":
            self.logger.info(f"\t[Bus] Fetching from shared cache/memory")
            r = self.shared_cache.read(address, current_step)
            total_time += r.time

        elif action["type"] == "fetch_from_owner":
            owner_id = action["owner"]
            self.logger.info(f"\t[Bus] Intervention: Core {owner_id} must supply data")
            data = self.cores[owner_id].handle_bus_read_exclusive(address, core_id)
            total_time += self.cache_to_cache_time

        # Install block in Modified state
        requesting_core = self.cores[core_id]
        eviction = requesting_core.l1_cache.install_block(address, "M", current_step)
        if eviction is not None:
            evicted_addr, evicted_state, evicted_dirty, wb_time = eviction
            total_time += wb_time
            self.directory.process_eviction(core_id, evicted_addr, evicted_dirty)

        # Return response (miss at L1)
        return response.Response({f"core_{core_id}_L1": False}, total_time)

    def coherent_upgrade(self, core_id, address, current_step):
        """Handle upgrade request from Shared to Modified

        Called when a core has a write hit to a Shared block.

        Returns: Response object with timing information
        """
        self.logger.info(f"\t[Bus] Core {core_id} requests upgrade (S→M) for {address}")

        # Consult directory to get other sharers
        action = self.directory.process_upgrade(core_id, address)

        # Invalidate other sharers
        for sharer_id in action["sharers"]:
            if sharer_id != core_id:
                self.logger.info(f"\t[Bus] Sending invalidation to Core {sharer_id}")
                self.cores[sharer_id].l1_cache.invalidate_block(address)

        # Upgrade local block to Modified
        self.cores[core_id].l1_cache.upgrade_to_modified(address)

        # Return response (hit at L1, but needed bus transaction for upgrade)
        return response.Response({f"core_{core_id}_L1": True}, self.transaction_time)
