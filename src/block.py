class Block:
    def __init__(self, block_size, current_step, dirty, address, coherence_state="I"):
        self.size = block_size
        self.dirty_bit = dirty
        self.last_accessed = current_step
        self.insertion_time = current_step
        self.address = address
        self.access_count = 0
        self.coherence_state = coherence_state  # MSI state: 'M', 'S', or 'I'

    def is_dirty(self):
        return self.dirty_bit

    def write(self, current_step):
        self.dirty_bit = True
        self.last_accessed = current_step
        self.access_count += 1

    def clean(self):
        self.dirty_bit = False

    def read(self, current_step):
        self.last_accessed = current_step
        self.access_count += 1

    def set_coherence_state(self, state):
        """Set MSI coherence state ('M', 'S', or 'I')"""
        self.coherence_state = state
        # Modified state implies dirty
        if state == "M":
            self.dirty_bit = True

    def get_coherence_state(self):
        """Get current MSI coherence state"""
        return self.coherence_state
