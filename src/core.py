class Core:
    """Represents a single CPU core with private L1 cache"""

    def __init__(self, core_id, l1_cache, interconnect, logger):
        self.core_id = core_id
        self.l1_cache = l1_cache
        self.interconnect = interconnect
        self.logger = logger

        # Register this core with the interconnect (which also registers it with the directory)
        self.interconnect.register_core(self)

    def read(self, address, current_step):
        """Process a read request (PrRd) from this core.

        MSI processor-side transitions on PrRd:
        - M --PrRd--> M : hit, read locally
        - S --PrRd--> S : hit, read locally
        - I --PrRd--> S : miss, send GetS to directory

        Returns: Response object with timing and hit/miss info
        """
        state = self.l1_cache.get_coherence_state(address)

        self.logger.info(f"\t[Core {self.core_id}] PrRd {address}, L1 state: {state}")

        if state in ["M", "S"]:
            # M --PrRd--> M  /  S --PrRd--> S : hit, no interconnect transaction needed
            self.logger.info(f"\t[Core {self.core_id}] L1 hit in state {state}")
            return self.l1_cache.local_read(address, current_step)
        else:
            # I --PrRd--> S : miss, send GetS to directory
            self.logger.info(f"\t[Core {self.core_id}] L1 miss, issuing GetS")
            return self.interconnect.coherent_read(self.core_id, address, current_step)

    def write(self, address, current_step):
        """Process a write request (PrWr) from this core.

        MSI processor-side transitions on PrWr:
        - M --PrWr--> M : hit, write locally
        - S --PrWr--> M : hit, send Upgrade to directory (no data fetch)
        - I --PrWr--> M : miss, send GetM to directory (fetch data + invalidate all)

        Returns: Response object with timing and hit/miss info
        """
        state = self.l1_cache.get_coherence_state(address)

        self.logger.info(f"\t[Core {self.core_id}] PrWr {address}, L1 state: {state}")

        if state == "M":
            # M --PrWr--> M : hit, already have exclusive ownership
            self.logger.info(f"\t[Core {self.core_id}] L1 hit in state M")
            return self.l1_cache.local_write(address, current_step)

        elif state == "S":
            # S --PrWr--> M : hit, send Upgrade to directory
            self.logger.info(f"\t[Core {self.core_id}] L1 hit in state S, issuing Upgrade")
            r = self.interconnect.coherent_upgrade(self.core_id, address, current_step)
            # Update block metadata (LRU/NRU timestamps, access count, dirty bit).
            # The interconnect transaction time already covers the write; the local_write
            # response is intentionally discarded.
            _ = self.l1_cache.local_write(address, current_step)
            return r

        else:
            # I --PrWr--> M : miss, send GetM to directory
            self.logger.info(f"\t[Core {self.core_id}] L1 miss, issuing GetM")
            r = self.interconnect.coherent_write(self.core_id, address, current_step)
            # Update block metadata (LRU/NRU timestamps, access count, dirty bit).
            # The interconnect transaction time already covers the write; the local_write
            # response is intentionally discarded.
            _ = self.l1_cache.local_write(address, current_step)
            return r

    def flush(self, address, current_step):
        """Evict a block from L1 and notify the directory (Flush).

        MSI processor-side transitions on Flush:
        - M --Flush--> I : write dirty block back to memory, invalidate
        - S --Flush--> I : drop clean copy, invalidate
        - I --Flush--> I : nothing to do
        """
        state = self.l1_cache.get_coherence_state(address)
        r = self.l1_cache.flush(address, current_step)
        if state != "I":
            self.interconnect.directory.process_eviction(self.core_id, address, state == "M")
        return r

    def flush_all(self, current_step):
        """Evict all blocks from L1 and notify the directory (Flush) for each.

        Applies M --Flush--> I and S --Flush--> I to every cached block.
        """
        blocks = [
            (blk.address, blk.get_coherence_state(), blk.is_dirty())
            for index in self.l1_cache.data
            for blk in self.l1_cache.data[index].values()
        ]
        r = self.l1_cache.flush_all(current_step)
        for addr, state, is_dirty in blocks:
            if state != "I":
                self.interconnect.directory.process_eviction(self.core_id, addr, is_dirty)
        return r

    # ── Messages received from the directory ──────────────────────────────────

    def receive_fetch(self, address, requesting_core_id):
        """Receive a Fetch message from the directory (M → S).

        Sent by the directory when another core issues a GetS and this cache
        holds the block in Modified state. This core must supply the data and
        downgrade to Shared.
        """
        state = self.l1_cache.get_coherence_state(address)
        self.logger.info(
            f"\t[Core {self.core_id}] Received Fetch from directory for {address}"
            f" (requested by Core {requesting_core_id}), state: {state}"
        )
        # M → S : supply data and downgrade
        data = self.l1_cache.supply_data(address)
        self.l1_cache.downgrade_to_shared(address)
        # Per MSI protocol, a dirty writeback to memory is required here.
        # Omitted in this simulation because data values are not tracked.
        return data

    def receive_fetch_inv(self, address, requesting_core_id):
        """Receive a FetchInv message from the directory (M → I).

        Sent by the directory when another core issues a GetM and this cache
        holds the block in Modified state. This core must supply the data and
        invalidate its copy.
        """
        state = self.l1_cache.get_coherence_state(address)
        self.logger.info(
            f"\t[Core {self.core_id}] Received FetchInv from directory for {address}"
            f" (requested by Core {requesting_core_id}), state: {state}"
        )
        # M → I : supply data and invalidate
        data = self.l1_cache.supply_data(address)
        self.l1_cache.invalidate_block(address)
        # Per MSI protocol, a dirty writeback to memory is required here.
        # Omitted in this simulation because data values are not tracked.
        return data

    def receive_inv(self, address, requesting_core_id):
        """Receive an Inv message from the directory (S → I).

        Sent by the directory when another core issues GetM or Upgrade and
        this cache holds a Shared copy. This core must invalidate its copy.
        """
        state = self.l1_cache.get_coherence_state(address)
        self.logger.info(
            f"\t[Core {self.core_id}] Received Inv from directory for {address}"
            f" (requested by Core {requesting_core_id}), state: {state}"
        )
        # S → I : invalidate
        self.l1_cache.invalidate_block(address)
