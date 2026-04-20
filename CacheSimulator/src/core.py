class Core:
    """Represents a single CPU core with private L1 cache"""

    def __init__(self, core_id, l1_cache, bus, logger):
        self.core_id = core_id
        self.l1_cache = l1_cache
        self.bus = bus
        self.logger = logger

        # Register this core with the bus
        self.bus.register_core(self)

    def read(self, address, current_step):
        """Process a read request from this core

        Implements MSI protocol read logic:
        - If block in M or S state: local read (hit)
        - If block in I state: coherent read via bus (miss)

        Returns: Response object with timing and hit/miss info
        """
        # Check L1 coherence state
        state = self.l1_cache.get_coherence_state(address)

        self.logger.info(f'\t[Core {self.core_id}] Read {address}, L1 state: {state}')

        if state in ['M', 'S']:
            # Valid state - can read locally
            self.logger.info(f'\t[Core {self.core_id}] L1 hit in state {state}')
            return self.l1_cache.local_read(address, current_step)
        else:
            # Invalid state - need to fetch via bus
            self.logger.info(f'\t[Core {self.core_id}] L1 miss, requesting via bus')
            return self.bus.coherent_read(self.core_id, address, current_step)

    def write(self, address, current_step):
        """Process a write request from this core

        Implements MSI protocol write logic:
        - If block in M state: local write (hit)
        - If block in S state: upgrade to M (invalidate others)
        - If block in I state: coherent write via bus (miss)

        Returns: Response object with timing and hit/miss info
        """
        # Check L1 coherence state
        state = self.l1_cache.get_coherence_state(address)

        self.logger.info(f'\t[Core {self.core_id}] Write {address}, L1 state: {state}')

        if state == 'M':
            # Already have exclusive ownership - can write locally
            self.logger.info(f'\t[Core {self.core_id}] L1 hit in state M')
            return self.l1_cache.local_write(address, current_step)

        elif state == 'S':
            # Shared state - need to upgrade (invalidate other copies)
            self.logger.info(f'\t[Core {self.core_id}] L1 hit in state S, upgrading to M')
            return self.bus.coherent_upgrade(self.core_id, address, current_step)

        else:
            # Invalid state - need to fetch with exclusive access
            self.logger.info(f'\t[Core {self.core_id}] L1 miss, requesting exclusive via bus')
            return self.bus.coherent_write(self.core_id, address, current_step)

    def handle_bus_read(self, address, requesting_core_id):
        """Handle BusRd request from another core (coherence callback)

        Called when another core wants to read a block.

        MSI transitions:
        - M → S: Supply data, write back to memory, downgrade to Shared
        - S → S: Do nothing (memory supplies data)
        - I → I: Do nothing (we don't have it)

        Returns: Data if we supplied it, None otherwise
        """
        state = self.l1_cache.get_coherence_state(address)

        self.logger.info(f'\t[Core {self.core_id}] Received BusRd for {address} from Core {requesting_core_id}, state: {state}')

        if state == 'M':
            # We have modified data - must supply and downgrade
            self.logger.info(f'\t[Core {self.core_id}] Supplying data and downgrading M → S')
            data = self.l1_cache.supply_data(address)
            self.l1_cache.downgrade_to_shared(address)
            # Note: In real implementation, would write back to memory here
            return data

        elif state == 'S':
            # We have shared data - memory can supply
            self.logger.info(f'\t[Core {self.core_id}] We have shared copy, memory will supply')
            return None

        else:
            # We don't have it
            self.logger.info(f'\t[Core {self.core_id}] We don\'t have {address}')
            return None

    def handle_bus_read_exclusive(self, address, requesting_core_id):
        """Handle BusRdX request from another core (coherence callback)

        Called when another core wants exclusive access (for write).

        MSI transitions:
        - M → I: Supply data, write back to memory, invalidate
        - S → I: Just invalidate
        - I → I: Do nothing (we don't have it)

        Returns: Data if we supplied it, None otherwise
        """
        state = self.l1_cache.get_coherence_state(address)

        self.logger.info(f'\t[Core {self.core_id}] Received BusRdX for {address} from Core {requesting_core_id}, state: {state}')

        if state == 'M':
            # We have modified data - must supply, write back, and invalidate
            self.logger.info(f'\t[Core {self.core_id}] Supplying data and invalidating (M → I)')
            data = self.l1_cache.supply_data(address)
            self.l1_cache.invalidate_block(address)
            # Note: In real implementation, would write back to memory here
            return data

        elif state == 'S':
            # We have shared data - just invalidate
            self.logger.info(f'\t[Core {self.core_id}] Invalidating shared copy (S → I)')
            self.l1_cache.invalidate_block(address)
            return None

        else:
            # We don't have it
            self.logger.info(f'\t[Core {self.core_id}] We don\'t have {address}')
            return None
