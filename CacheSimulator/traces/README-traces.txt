# Basic usage
Trace files have very little formatting.

Each address must be followed by a space and either an 'R' (read), a 'W' (write) or a 'F' (flush from cache into memory).
To flush all addresses into memory, use 'FA' with address XXX.

Trace files support commenting. Lines that start with '#' will be ignored.
In-line comments are NOT supported.

# Attack mode

## Prime & Probe
Need to specify "ATTACKER" or "VICTIM" after the operation, e.g. "R ATTACKER" or "W VICTIM". 
It's also important to only put "ATTACKER" accesses first, then "VICTIM" accesses and finally the same "ATTACKER" accesses again.

This respect the format of the attack:
1. Fill the cache with the attacker's addresses.
2. Let the victim execute.
3. Check which of the attacker's addresses have been evicted by the victim's accesses.