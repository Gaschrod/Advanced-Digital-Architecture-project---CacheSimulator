class DirectoryEntry:
    """Directory entry for tracking a single cache block's coherence state"""

    def __init__(self):
        self.state = "I"  # MSI state: 'M', 'S', or 'I'
        self.sharers = set()  # Set of core IDs that have the block
        self.owner = None  # Core ID if state == 'M'


class Directory:
    """Centralized coherence controller implementing MSI protocol.

    The directory tracks per-block state and sends targeted point-to-point
    messages directly to the relevant caches:
    - Fetch    : sent to M-state owner on BusRd   → owner transitions M → S, supplies data
    - FetchInv : sent to M-state owner on BusRdX  → owner transitions M → I, supplies data
    - Inv      : sent to each S-state sharer on BusRdX or BusUpgr → sharer transitions S → I
    """

    def __init__(self, logger):
        self.entries = {}  # address -> DirectoryEntry
        self.cores = {}  # core_id -> Core, populated via register_core
        self.logger = logger

    def register_core(self, core):
        """Register a core so the directory can send it messages."""
        self.cores[core.core_id] = core
        self.logger.info(f"[Directory] Registered Core {core.core_id}")

    def _get_entry(self, address):
        """Get or create directory entry for address"""
        if address not in self.entries:
            self.entries[address] = DirectoryEntry()
        return self.entries[address]

    def process_read(self, requesting_core_id, address):
        """Process BusRd from requesting_core_id (I --PrRd--> S).

        Directory transitions and messages sent:
        - Dir I → Dir S : no copies, fetch from memory, add requester as sharer
        - Dir S → Dir S : add requester as sharer, fetch from memory
        - Dir M → Dir S : send Fetch to owner (owner: M → S), add both as sharers

        Returns: dict with 'source' key ('memory' or 'cache') for bus timing.
        """
        entry = self._get_entry(address)

        self.logger.info(
            f"\t[Directory] Received BusRd for {address} from Core {requesting_core_id}"
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
            return {"source": "memory"}

        elif entry.state == "S":
            # Dir S → Dir S : add requester as sharer, fetch from memory
            entry.sharers.add(requesting_core_id)
            self.logger.info(
                f"\t[Directory] S → S, Core {requesting_core_id} added to sharers"
            )
            return {"source": "memory"}

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
            return {"source": "cache"}

    def process_write(self, requesting_core_id, address):
        """Process BusRdX from requesting_core_id (I --PrWr--> M).

        Directory transitions and messages sent:
        - Dir I → Dir M : no copies, fetch from memory, requester becomes owner
        - Dir S → Dir M : send Inv to all sharers (S → I), fetch from memory, requester becomes owner
        - Dir M → Dir M : send FetchInv to owner (M → I), requester becomes new owner

        Returns: dict with 'source' key ('memory' or 'cache') for bus timing.
        """
        entry = self._get_entry(address)

        self.logger.info(
            f"\t[Directory] Received BusRdX for {address} from Core {requesting_core_id}"
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
            return {"source": "memory"}

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
            return {"source": "memory"}

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
            return {"source": "cache"}

    def process_upgrade(self, requesting_core_id, address):
        """Process BusUpgr from requesting_core_id (S --PrWr--> M).

        Directory transition and messages sent:
        - Dir S → Dir M : send Inv to all other sharers (S → I), requester becomes owner
          (no data fetch — requester already holds a valid S copy)
        """
        entry = self._get_entry(address)

        self.logger.info(
            f"\t[Directory] Received BusUpgr for {address} from Core {requesting_core_id}"
        )

        if requesting_core_id not in entry.sharers:
            self.logger.error(
                f"\t[Directory] ERROR: Core {requesting_core_id} not in sharers for {address}!"
            )
            return

        if entry.state != "S":
            self.logger.error(
                f"\t[Directory] ERROR: BusUpgr but state is {entry.state}, not S!"
            )
            return

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
