# Multi-Core Cache Simulator with MSI Coherence

This document describes the multi-core extension to the cache simulator, which implements directory-based MSI (Modified-Shared-Invalid) cache coherence protocol.

## Overview

The multi-core simulator extends the single-core cache simulator with:
- **Private L1 caches** per core
- **Shared L2 cache** accessed by all cores
- **Directory-based MSI coherence protocol** to maintain cache consistency
- **Centralized directory controller** tracking block ownership
- **System bus** for inter-core communication

## Architecture

```
Core 0 → L1_0 (private) ─┐
Core 1 → L1_1 (private) ─┼→ System Bus ←→ Directory Controller
                         │                      ↓
                         └──────→ Shared L2 → Memory
```

## MSI Coherence Protocol

### States

- **Modified (M)**: Single cache has exclusive, modified copy (dirty)
  - Can read/write without bus transactions
  - Must supply data on coherence requests

- **Shared (S)**: One or more caches have clean copy
  - Can read locally
  - Write requires upgrade (invalidate other sharers)

- **Invalid (I)**: Block not present or has been invalidated
  - Any access requires bus transaction

### State Transitions

#### Processor Operations

| Current State | Operation | Action | Next State |
|---------------|-----------|--------|------------|
| I | Read | Fetch from memory/other cache | S |
| S | Read | Hit | S |
| M | Read | Hit | M |
| I | Write | Fetch exclusive, invalidate sharers | M |
| S | Write | Upgrade, invalidate other sharers | M |
| M | Write | Hit | M |

#### Bus Operations (from other cores)

| Current State | Bus Operation | Action | Next State |
|---------------|---------------|--------|------------|
| M | BusRd | Supply data, write back, downgrade | S |
| S | BusRd | No action (memory supplies) | S |
| I | BusRd | No action | I |
| M | BusRdX | Supply data, write back, invalidate | I |
| S | BusRdX | Invalidate | I |
| I | BusRdX | No action | I |

## Usage

### Command-Line Arguments

```bash
python cache_simulator.py -c <config> -t <trace> -p <policy> -m -n <cores>
```

**Multi-core specific arguments:**
- `-m, --multi-core`: Enable multi-core simulation with MSI coherence
- `-n, --num-cores`: Number of CPU cores (default: 2)

**Example:**
```bash
python src/cache_simulator.py -c configs/multilevel.config -t traces/multicore_test.txt -p lru -m -n 2
```

### Configuration Requirements

Multi-core mode **requires** a configuration file with at least:
- `cache_1`: L1 cache specification (will be replicated per core)
- `cache_2`: Shared L2 cache specification
- `mem`: Main memory specification

**Example config (multilevel.config):**
```yaml
architecture:
  word_size: 4
  block_size: 16
  write_back: true

cache_1:  # Private L1 per core
  blocks: 16
  associativity: 2
  hit_time: 1

cache_2:  # Shared L2
  blocks: 64
  associativity: 4
  hit_time: 16

mem:
  hit_time: 1000
```

### Trace Format

Multi-core traces use the format: `<core_id> <address> <operation> [ATTACKER|VICTIM]`

**Fields:**
- `core_id`: Integer core ID (0-indexed)
- `address`: Hexadecimal memory address
- `operation`: R (read), W (write), F (flush), FA (flush all)
- `actor`: Optional ATTACKER/VICTIM tag for security analysis

**Example trace:**
```
# Core 0 reads address 0x00000000
0 00000000 R

# Core 1 reads same address (will share)
1 00000000 R

# Core 0 writes (upgrades to M, invalidates Core 1)
0 00000000 W

# Core 1 reads (Core 0 intervenes, both share)
1 00000000 R
```

## Coherence Scenarios

### Scenario 1: Read Sharing

```
0 00000000 R  # Core 0: miss → fetch from memory → state S
1 00000000 R  # Core 1: miss → fetch from memory → state S (both share)
0 00000000 R  # Core 0: hit in state S
```

**Result:** Both cores have the block in Shared state

### Scenario 2: Write Invalidation

```
0 00000000 R  # Core 0: miss → state S
1 00000000 R  # Core 1: miss → state S (both share)
0 00000000 W  # Core 0: upgrade S→M, invalidate Core 1
```

**Result:** Core 0 has M, Core 1 has I (invalidated)

### Scenario 3: Modified Intervention

```
0 00000000 W  # Core 0: miss → state M (exclusive, dirty)
1 00000000 R  # Core 1: miss → Core 0 supplies data, both → state S
```

**Result:** Core 0 downgrades M→S, Core 1 gets S, data written back

### Scenario 4: Write-Write Conflict

```
0 00000000 W  # Core 0: miss → state M
1 00000000 W  # Core 1: miss → Core 0 supplies & invalidates, Core 1 → state M
```

**Result:** Core 0 invalidated (I), Core 1 has M

## Implementation Details

### New Components

**1. Directory Controller (`directory.py`)**
- `DirectoryEntry`: Tracks state, sharers, owner per block
- `Directory`: Centralized controller managing coherence
  - `process_read()`: Handle read requests
  - `process_write()`: Handle write requests
  - `process_upgrade()`: Handle S→M upgrades
  - `process_eviction()`: Handle cache evictions

**2. System Bus (`bus.py`)**
- `Bus`: Interconnect for coherence messages
  - `coherent_read()`: Handle read miss (BusRd)
  - `coherent_write()`: Handle write miss (BusRdX)
  - `coherent_upgrade()`: Handle S→M upgrade
  - `register_core()`: Register cores on the bus

**3. Core Abstraction (`core.py`)**
- `Core`: Encapsulates CPU + private L1
  - `read()`: Check state, route to local or bus
  - `write()`: Check state, route to local or bus
  - `handle_bus_read()`: Callback for BusRd from other cores
  - `handle_bus_read_exclusive()`: Callback for BusRdX from other cores

### Modified Components

**1. Block Class (`block.py`)**
- Added `coherence_state` field ('M', 'S', or 'I')
- Added `set_coherence_state()` and `get_coherence_state()` methods

**2. Cache Class (`cache.py`)**
- Added `core_id` and `is_shared` parameters
- Added coherence methods:
  - `get_coherence_state()`: Query block state
  - `invalidate_block()`: Remove block (coherence callback)
  - `downgrade_to_shared()`: M→S transition
  - `upgrade_to_modified()`: S→M transition
  - `install_block()`: Install with specific coherence state
  - `supply_data()`: Provide data to other caches
  - `local_read()` / `local_write()`: Operations after coherence check

**3. Main Simulator (`cache_simulator.py`)**
- Added `build_multicore_hierarchy()`: Build multi-core system
- Added `simulate_multicore()`: Execute multi-core traces
- Added `analyze_multicore_results()`: Per-core statistics

## Performance Metrics

### Timing Model

- **Bus transaction overhead**: 5 cycles
- **Cache-to-cache transfer**: 10 cycles (faster than memory)
- **L1 hit**: 1 cycle (from config)
- **L2 hit**: 16 cycles (from config)
- **Memory access**: 1000 cycles (from config)

### Statistics Reported

- Total instructions executed
- Total cycles consumed
- Per-core L1 statistics:
  - Number of accesses
  - Hits and misses
  - Hit rate percentage

## Backward Compatibility

The simulator maintains full backward compatibility with single-core mode:
- Default behavior (without `-m` flag) runs original single-core simulator
- Original trace format (`<address> <operation>`) still works
- All existing configs and tests continue to function

## Examples

### Example 1: Basic Multi-Core Test

**Command:**
```bash
python src/cache_simulator.py -c configs/multilevel.config -t traces/multicore_test.txt -p lru -m -n 2
```

**Output excerpt:**
```
0:  [Core 0] [UNKNOWN] Reading 00000000
    [Directory] State I → S, Core 0 added to sharers
    [Core 0 L1] Installed 00000000 in state S

1:  [Core 1] [UNKNOWN] Reading 00000000
    [Directory] State S → S, Core 1 added to sharers
    [Core 1 L1] Installed 00000000 in state S

Core 0 L1: 5 accesses, 1 hit, 4 misses (20% hit rate)
Core 1 L1: 5 accesses, 0 hits, 5 misses (0% hit rate)
```

### Example 2: 4-Core Simulation

```bash
python src/cache_simulator.py -c configs/multilevel.config -t traces/multicore_4cores.txt -p lru -m -n 4
```

## Limitations and Future Work

### Current Limitations

1. **Sequential simulation**: Instructions execute sequentially, not in parallel
2. **Simple directory**: Centralized directory (not distributed)
3. **MSI only**: Does not implement MESI or MOESI extensions
4. **No network model**: Bus has fixed latencies

### Future Enhancements

1. **MESI protocol**: Add Exclusive state for optimization
2. **MOESI protocol**: Add Owned state for shared dirty data
3. **Snooping protocol**: Compare with directory-based approach
4. **Multi-level coherence**: Coherence at L2/L3 levels
5. **Non-uniform latencies**: Model realistic interconnect delays
6. **Multi-core attacks**: Extend Prime & Probe for cross-core attacks

## Testing

### Test Traces Included

- `multicore_test.txt`: Basic MSI coherence scenarios
  - Read sharing
  - Write invalidation
  - Modified intervention
  - Write-write conflicts

### Creating Custom Traces

Format: `<core_id> <address> <operation> [ATTACKER|VICTIM]`

**Tips:**
- Use sequential core IDs (0, 1, 2, ...)
- Test each MSI transition explicitly
- Vary addresses to test different cache sets
- Use comments (`#`) to document expected behavior

## Debugging

Enable detailed logging to see coherence protocol decisions:
- Directory state transitions
- Bus transactions (BusRd, BusRdX, upgrades)
- Cache state changes (I→S, S→M, M→S, etc.)
- Interventions and invalidations

Check the log file (`cache_simulator.log`) for full coherence trace.

## References

- MSI Protocol: [Cache Coherence Protocols](https://en.wikipedia.org/wiki/MSI_protocol)
- Directory-Based Coherence: Computer Architecture textbooks (Hennessy & Patterson)
- Cache Coherence: [Primer on Memory Consistency and Cache Coherence](https://www.morganclaypool.com/doi/abs/10.2200/S00346ED1V01Y201104CAC016)
