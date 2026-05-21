class DirectoryEntry:
    """Directory entry for tracking a single cache block's coherence state"""

    def __init__(self):
        self.state = "I"  # MSI state: 'M', 'S', or 'I'
        self.sharers = set()  # Set of core IDs that have the block
        self.owner = None  # Core ID if state == 'M'


class Directory:
    """Centralized directory-based coherence controller implementing MSI protocol"""

    def __init__(self, logger):
        self.entries = {}  # address -> DirectoryEntry
        self.logger = logger

    def _get_entry(self, address):
        """Get or create directory entry for address"""
        if address not in self.entries:
            self.entries[address] = DirectoryEntry()
        return self.entries[address]

    def process_read(self, core_id, address):
        """Process read request from a core

        Returns: action dict describing what to do
        """
        entry = self._get_entry(address)

        self.logger.info(
            f"\t[Directory] Read request for {address} from Core {core_id}"
        )
        self.logger.info(
            f"\t[Directory] Current state: {entry.state}, Sharers: {entry.sharers}, Owner: {entry.owner}"
        )

        if entry.state == "I":
            # No cache has it, fetch from memory
            entry.state = "S"
            entry.sharers.add(core_id)
            self.logger.info(
                f"\t[Directory] State I → S, Core {core_id} added to sharers"
            )
            return {"type": "fetch_from_memory"}

        elif entry.state == "S":
            # Others have it in Shared, add this core as sharer
            entry.sharers.add(core_id)
            self.logger.info(
                f"\t[Directory] State S → S, Core {core_id} added to sharers"
            )
            return {"type": "fetch_from_shared", "sharers": entry.sharers.copy()}

        elif entry.state == "M":
            # Owner has it Modified, need intervention
            owner = entry.owner
            entry.state = "S"
            entry.sharers = {owner, core_id}
            entry.owner = None
            self.logger.info(
                f"\t[Directory] State M → S, intervention from Core {owner}, both cores now share"
            )
            return {"type": "fetch_from_owner", "owner": owner}

    def process_write(self, core_id, address):
        """Process write request from a core (miss case)

        Returns: action dict describing what to do
        """
        entry = self._get_entry(address)

        self.logger.info(
            f"\t[Directory] Write request for {address} from Core {core_id}"
        )
        self.logger.info(
            f"\t[Directory] Current state: {entry.state}, Sharers: {entry.sharers}, Owner: {entry.owner}"
        )

        action = {"invalidate": True, "sharers": entry.sharers.copy()}

        if entry.state == "I":
            # No cache has it
            action["type"] = "fetch_from_memory"
            self.logger.info(f"\t[Directory] State I → M, Core {core_id} becomes owner")

        elif entry.state == "S":
            # Others have it shared, need to invalidate
            action["type"] = "fetch_from_memory"
            self.logger.info(
                f"\t[Directory] State S → M, invalidating {entry.sharers}, Core {core_id} becomes owner"
            )

        elif entry.state == "M":
            # Owner has it modified
            action["type"] = "fetch_from_owner"
            action["owner"] = entry.owner
            self.logger.info(
                f"\t[Directory] State M → M, intervention from Core {entry.owner}, Core {core_id} becomes new owner"
            )

        # Update directory: core becomes exclusive owner
        entry.state = "M"
        entry.sharers = set()
        entry.owner = core_id

        return action

    def process_upgrade(self, core_id, address):
        """Process upgrade request from Shared to Modified

        Returns: action dict with sharers to invalidate
        """
        entry = self._get_entry(address)

        self.logger.info(
            f"\t[Directory] Upgrade request for {address} from Core {core_id}"
        )

        # Core must be in sharers
        if core_id not in entry.sharers:
            self.logger.error(
                f"\t[Directory] ERROR: Core {core_id} not in sharers for {address}!"
            )
            return {"sharers": set()}

        if entry.state != "S":
            self.logger.error(
                f"\t[Directory] ERROR: Upgrade request but state is {entry.state}, not S!"
            )
            return {"sharers": set()}

        # Invalidate all other sharers
        other_sharers = entry.sharers - {core_id}

        # Transition to Modified
        entry.state = "M"
        entry.sharers = set()
        entry.owner = core_id

        self.logger.info(
            f"\t[Directory] State S → M, invalidating cores {other_sharers}, Core {core_id} becomes owner"
        )

        return {"sharers": other_sharers}

    def process_eviction(self, core_id, address, is_dirty):
        """Process eviction notification from a core's cache

        Args:
            core_id: Which core is evicting
            address: Block address being evicted
            is_dirty: Whether the evicted block was dirty
        """
        entry = self._get_entry(address)

        self.logger.info(
            f"\t[Directory] Eviction of {address} from Core {core_id} (dirty={is_dirty})"
        )

        if entry.state == "M" and entry.owner == core_id:
            # Evicting modified data
            if is_dirty:
                self.logger.info(
                    f"\t[Directory] Core {core_id} writing back modified {address}"
                )
            entry.state = "I"
            entry.owner = None
            self.logger.info(f"\t[Directory] State M → I")

        elif entry.state == "S":
            # Remove from sharers
            entry.sharers.discard(core_id)
            if len(entry.sharers) == 0:
                entry.state = "I"
                self.logger.info(f"\t[Directory] State S → I (no more sharers)")
            else:
                self.logger.info(
                    f"\t[Directory] State S → S (Core {core_id} removed, remaining: {entry.sharers})"
                )
