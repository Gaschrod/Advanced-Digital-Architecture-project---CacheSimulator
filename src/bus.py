import response


class Bus:
    """Interconnect between processor cores and the directory controller.

    In this directory-based MSI implementation the bus has two responsibilities:
    1. Forward processor requests (BusRd, BusRdX, BusUpgr) to the directory.
    2. Fetch data from the shared cache / memory when needed and install blocks
       in the requesting core's L1 cache.

    All coherence decisions — which caches to contact and what messages to send
    (Fetch, FetchInv, Inv) — are made by the directory, not the bus.
    """

    def __init__(self, directory, shared_cache, logger):
        self.directory = directory
        self.shared_cache = shared_cache  # Shared L2 cache / memory
        self.cores = {}  # core_id -> Core
        self.logger = logger
        self.transaction_time = 5  # Bus transaction overhead in cycles
        self.cache_to_cache_time = (
            10  # Extra latency when data comes from another cache
        )

    def register_core(self, core):
        """Register a core on the bus and with the directory."""
        self.cores[core.core_id] = core
        self.directory.register_core(core)
        self.logger.info(f"[Bus] Registered Core {core.core_id}")

    def coherent_read(self, core_id, address, current_step):
        """Forward BusRd to the directory (I --PrRd--> S).

        This method fetches data from the shared cache or accounts for cache-to-cache transfer time, then installs the block
        in the requesting core's L1 in Shared state.

        Returns: Response object with timing information
        """
        self.logger.info(f"\t[Bus] Forwarding BusRd from Core {core_id} for {address}")

        # Directory handles coherence (sends Fetch to owner if needed)
        result = self.directory.process_read(core_id, address)

        total_time = self.transaction_time

        if result["source"] == "memory":
            # Data comes from shared cache / memory
            r = self.shared_cache.read(address, current_step)
            total_time += r.time
        else:
            # Data comes from the former owner (cache-to-cache transfer)
            total_time += self.cache_to_cache_time

        # Install block in Shared state in the requesting core's L1
        requesting_core = self.cores[core_id]
        eviction = requesting_core.l1_cache.install_block(address, "S", current_step)
        if eviction is not None:
            evicted_addr, evicted_state, evicted_dirty, wb_time = eviction
            total_time += wb_time
            self.directory.process_eviction(core_id, evicted_addr, evicted_dirty)

        return response.Response({f"core_{core_id}_L1": False}, total_time)

    def coherent_write(self, core_id, address, current_step):
        """Forward BusRdX to the directory (I --PrWr--> M).

        This method fetches data from the shared cache or accounts for cache-to-cache transfer time, then installs the
        block in the requesting core's L1 in Modified state.

        Returns: Response object with timing information
        """
        self.logger.info(f"\t[Bus] Forwarding BusRdX from Core {core_id} for {address}")

        # Directory handles coherence (sends Inv or FetchInv as needed)
        result = self.directory.process_write(core_id, address)

        total_time = self.transaction_time

        if result["source"] == "memory":
            # Data comes from shared cache / memory
            r = self.shared_cache.read(address, current_step)
            total_time += r.time
        else:
            # Data comes from the former owner (cache-to-cache transfer)
            total_time += self.cache_to_cache_time

        # Install block in Modified state in the requesting core's L1
        requesting_core = self.cores[core_id]
        eviction = requesting_core.l1_cache.install_block(address, "M", current_step)
        if eviction is not None:
            evicted_addr, evicted_state, evicted_dirty, wb_time = eviction
            total_time += wb_time
            self.directory.process_eviction(core_id, evicted_addr, evicted_dirty)

        return response.Response({f"core_{core_id}_L1": False}, total_time)

    def coherent_upgrade(self, core_id, address, current_step):
        """Forward BusUpgr to the directory (S --PrWr--> M).

        The directory sends Inv to all other sharers. No data fetch is needed
        since the requesting core already holds a valid Shared copy. The block
        is then upgraded to Modified state locally.

        Returns: Response object with timing information
        """
        self.logger.info(
            f"\t[Bus] Forwarding BusUpgr from Core {core_id} for {address}"
        )

        # Directory handles coherence (sends Inv to other sharers)
        self.directory.process_upgrade(core_id, address)

        # S → M : upgrade local block (no data fetch needed)
        self.cores[core_id].l1_cache.upgrade_to_modified(address)

        return response.Response({f"core_{core_id}_L1": True}, self.transaction_time)
