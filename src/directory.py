import response


class DirectoryEntry:
    """Directory entry for tracking a single cache block's coherence state"""

    def __init__(self):
        self.state = "I"  # MSI state: 'M', 'S', or 'I'
        self.sharers = set()  # Set of core IDs that have the block
        self.owner = None  # Core ID if state == 'M'


class Directory:
    """Centralized coherence controller implementing MSI protocol.

    The directory is the full transaction coordinator: cores send their requests
    (GetS, GetM, Upgrade) directly to it. It tracks per-block state, sends
    targeted point-to-point messages to the relevant caches, fetches data from
    the shared cache / memory when needed, installs the block in the requesting
    core's L1, and returns timing information.

    Coherence messages sent directly to caches:
    - Fetch    : sent to M-state owner on a GetS request     → owner transitions M → S, supplies data
    - FetchInv : sent to M-state owner on a GetM request     → owner transitions M → I, supplies data
    - Inv      : sent to each S-state sharer on a GetM or Upgrade request → sharer transitions S → I
    """

    def __init__(self, shared_cache, logger):
        self.entries = {}  # address -> DirectoryEntry
        self.cores = {}  # core_id -> Core, populated via register_core
        self.shared_cache = shared_cache  # Shared L2 cache / memory
        self.logger = logger
        self.transaction_time = 5  # Transaction overhead in cycles
        self.cache_to_cache_time = (
            10  # Extra latency when data comes from another cache
        )

    def register_core(self, core):
        """Register a core so the directory can send it messages."""
        self.cores[core.core_id] = core
        self.logger.info(f"[Directory] Registered Core {core.core_id}")

    def _get_entry(self, address):
        """Get or create directory entry for address"""
        if address not in self.entries:
            self.entries[address] = DirectoryEntry()
        return self.entries[address]

    def process_read(self, requesting_core_id, address, current_step):
        """Process GetS from requesting_core_id (I --PrRd--> S).

        Directory transitions and messages sent:
        - Dir I → Dir S : no copies, fetch from memory, add requester as sharer
        - Dir S → Dir S : add requester as sharer, fetch from memory
        - Dir M → Dir S : send Fetch to owner (owner: M → S), add both as sharers

        Fetches data, installs the block in the requester's L1 in Shared state.

        Returns: Response object with timing information.
        """
        entry = self._get_entry(address)

        self.logger.info(
            f"\t[Directory] Received GetS for {address} from Core {requesting_core_id}"
        )
        self.logger.info(
            f"\t[Directory] State: {entry.state}, Sharers: {entry.sharers}, Owner: {entry.owner}"
        )

        if entry.state == "I":
            # Dir I → Dir S : no copies, requester fetches from memory
            entry.state = "S"
            entry.sharers.add(requesting_core_id)
            self.logger.info(
                f"\t[Directory] I → S, Core {requesting_core_id} added to sharers"
            )
            source = "memory"

        elif entry.state == "S":
            # Dir S → Dir S : add requester as sharer, fetch from memory
            entry.sharers.add(requesting_core_id)
            self.logger.info(
                f"\t[Directory] S → S, Core {requesting_core_id} added to sharers"
            )
            source = "memory"

        elif entry.state == "M":
            # Dir M → Dir S : send Fetch to owner
            owner_id = entry.owner
            self.logger.info(f"\t[Directory] Sending Fetch to Core {owner_id} (M → S)")
            self.cores[owner_id].receive_fetch(address, requesting_core_id)
            entry.state = "S"
            entry.sharers = {owner_id, requesting_core_id}
            entry.owner = None
            self.logger.info(
                f"\t[Directory] M → S, Core {requesting_core_id} added as sharer"
            )
            source = "cache"

        return self._complete_transaction(
            requesting_core_id, address, "S", source, current_step
        )

    def process_write(self, requesting_core_id, address, current_step):
        """Process GetM from requesting_core_id (I --PrWr--> M).

        Directory transitions and messages sent:
        - Dir I → Dir M : no copies, fetch from memory, requester becomes owner
        - Dir S → Dir M : send Inv to all sharers (S → I), fetch from memory, requester becomes owner
        - Dir M → Dir M : send FetchInv to owner (M → I), requester becomes new owner

        Fetches data, installs the block in the requester's L1 in Modified state.

        Returns: Response object with timing information.
        """
        entry = self._get_entry(address)

        self.logger.info(
            f"\t[Directory] Received GetM for {address} from Core {requesting_core_id}"
        )
        self.logger.info(
            f"\t[Directory] State: {entry.state}, Sharers: {entry.sharers}, Owner: {entry.owner}"
        )

        if entry.state == "I":
            # Dir I → Dir M : no copies to invalidate, fetch from memory
            entry.state = "M"
            entry.owner = requesting_core_id
            self.logger.info(
                f"\t[Directory] I → M, Core {requesting_core_id} becomes owner"
            )
            source = "memory"

        elif entry.state == "S":
            # Dir S → Dir M : send Inv to all sharers (S → I), fetch from memory
            for sharer_id in list(entry.sharers):
                if sharer_id != requesting_core_id:
                    self.logger.info(
                        f"\t[Directory] Sending Inv to Core {sharer_id} (S → I)"
                    )
                    self.cores[sharer_id].receive_inv(address, requesting_core_id)
            entry.state = "M"
            entry.sharers = set()
            entry.owner = requesting_core_id
            self.logger.info(
                f"\t[Directory] S → M, Core {requesting_core_id} becomes owner"
            )
            source = "memory"

        elif entry.state == "M":
            # Dir M → Dir M : send FetchInv to current owner (M → I), requester becomes new owner
            owner_id = entry.owner
            self.logger.info(
                f"\t[Directory] Sending FetchInv to Core {owner_id} (M → I)"
            )
            self.cores[owner_id].receive_fetch_inv(address, requesting_core_id)
            entry.state = "M"
            entry.sharers = set()
            entry.owner = requesting_core_id
            self.logger.info(
                f"\t[Directory] M → M, Core {requesting_core_id} becomes new owner"
            )
            source = "cache"

        return self._complete_transaction(
            requesting_core_id, address, "M", source, current_step
        )

    def process_upgrade(self, requesting_core_id, address, current_step):
        """Process Upgrade from requesting_core_id (S --PrWr--> M).

        Directory transition and messages sent:
        - Dir S → Dir M : send Inv to all other sharers (S → I), requester becomes owner
          (no data fetch — requester already holds a valid S copy)

        Upgrades the requester's local block to Modified (no data fetch needed).

        Returns: Response object with timing information.
        """
        entry = self._get_entry(address)

        self.logger.info(
            f"\t[Directory] Received Upgrade for {address} from Core {requesting_core_id}"
        )

        if requesting_core_id not in entry.sharers:
            self.logger.error(
                f"\t[Directory] ERROR: Core {requesting_core_id} not in sharers for {address}!"
            )
            # Preserve legacy behavior: still upgrade the local block.
            self.cores[requesting_core_id].l1_cache.upgrade_to_modified(address)
            return response.Response(
                {f"core_{requesting_core_id}_L1": True}, self.transaction_time
            )

        if entry.state != "S":
            self.logger.error(
                f"\t[Directory] ERROR: Upgrade but state is {entry.state}, not S!"
            )
            # Preserve legacy behavior: still upgrade the local block.
            self.cores[requesting_core_id].l1_cache.upgrade_to_modified(address)
            return response.Response(
                {f"core_{requesting_core_id}_L1": True}, self.transaction_time
            )

        # Send Inv to all other sharers (S → I)
        for sharer_id in list(entry.sharers):
            if sharer_id != requesting_core_id:
                self.logger.info(
                    f"\t[Directory] Sending Inv to Core {sharer_id} (S → I)"
                )
                self.cores[sharer_id].receive_inv(address, requesting_core_id)

        entry.state = "M"
        entry.sharers = set()
        entry.owner = requesting_core_id
        self.logger.info(
            f"\t[Directory] S → M, Core {requesting_core_id} becomes owner"
        )

        # S → M : upgrade local block (no data fetch needed)
        self.cores[requesting_core_id].l1_cache.upgrade_to_modified(address)

        return response.Response(
            {f"core_{requesting_core_id}_L1": True}, self.transaction_time
        )

    def _complete_transaction(
        self, requesting_core_id, address, install_state, source, current_step
    ):
        """Fetch data, install the block in the requester's L1, and tally timing.

        Shared tail for GetS / GetM once coherence has been resolved:
        - account for the transaction overhead;
        - read from the shared cache / memory when the data comes from memory,
          or charge the cache-to-cache transfer latency otherwise;
        - install the block in the requesting core's L1 in `install_state`,
          forwarding any eviction back to the directory.

        Returns: Response object with timing information.
        """
        total_time = self.transaction_time

        if source == "memory":
            # Data comes from shared cache / memory
            r = self.shared_cache.read(address, current_step)
            total_time += r.time
        else:
            # Data comes from the former owner (cache-to-cache transfer)
            total_time += self.cache_to_cache_time

        # Install block in the requesting core's L1
        requesting_core = self.cores[requesting_core_id]
        eviction = requesting_core.l1_cache.install_block(
            address, install_state, current_step
        )
        if eviction is not None:
            evicted_addr, evicted_state, evicted_dirty, wb_time = eviction
            total_time += wb_time
            self.process_eviction(requesting_core_id, evicted_addr, evicted_dirty)

        return response.Response(
            {f"core_{requesting_core_id}_L1": False}, total_time
        )

    def process_eviction(self, core_id, address, is_dirty):
        """Process a Flush (eviction) notification from a core's cache.

        MSI transitions on Flush:
        - Dir M, owner evicts : M --Flush--> I, write back to memory if dirty
        - Dir S, sharer evicts: sharer's copy invalidated; dir stays S until last sharer leaves
        """
        entry = self._get_entry(address)

        self.logger.info(
            f"\t[Directory] Flush of {address} from Core {core_id} (dirty={is_dirty})"
        )

        if entry.state == "M" and entry.owner == core_id:
            # M --Flush--> I : owner evicts modified block
            if is_dirty:
                self.logger.info(
                    f"\t[Directory] Core {core_id} writes back modified {address}"
                )
            entry.state = "I"
            entry.owner = None
            self.logger.info(f"\t[Directory] M → I")

        elif entry.state == "S":
            # S --Flush--> S/I : sharer evicts clean copy
            entry.sharers.discard(core_id)
            if len(entry.sharers) == 0:
                entry.state = "I"
                self.logger.info(f"\t[Directory] S → I (no more sharers)")
            else:
                self.logger.info(
                    f"\t[Directory] S → S (Core {core_id} removed, remaining: {entry.sharers})"
                )
