# Multi-Core Cache Simulator — Usage & Testing Guide

---

## Setup

All commands must be run from the `CacheSimulator/src/` directory:

```bash
cd CacheSimulator/src
```

Multi-core mode requires a config file that defines `cache_2` (shared L2). The provided `configs/multilevel.config` satisfies this requirement.

---

## Command Syntax

```bash
python cache_simulator.py \
  -c <config_file> \
  -t <trace_file> \
  -p <eviction_policy> \
  -m \
  -n <num_cores>
```

### All flags

| Flag | Long form | Description | Default |
|------|-----------|-------------|---------|
| `-c` | `--config-file` | YAML config file | required |
| `-t` | `--trace-file` | Trace file | required |
| `-p` | `--policy` | `lru`, `mru`, `nru`, `lfu`, `fifo`, `lifo`, `random` | `lru` |
| `-m` | `--multi-core` | Enable multi-core MSI mode | off |
| `-n` | `--num-cores` | Number of cores | 2 |
| `-l` | `--log-file` | Output log file name | `cache_simulator.log` |
| `-b` | `--beautify` | Colored terminal output | off |
| `-d` | `--draw-cache` | Print cache layout tables after simulation | off |

---

## Trace File Format

```
<core_id> <address> <operation> [ATTACKER|VICTIM]
```

| Field | Description |
|-------|-------------|
| `core_id` | Integer, 0-indexed |
| `address` | 8-digit hex address (e.g. `00000000`) |
| `operation` | `R` read · `W` write · `F` flush address · `FA` flush all |
| `actor` | Optional: `ATTACKER` or `VICTIM` |

Lines starting with `#` are comments.

**Example:**
```
# Core 0 fetches from memory -> state S
0 00000000 R
# Core 1 fetches same line -> both share it in S
1 00000000 R
# Core 0 writes -> upgrades to M, Core 1 invalidated to I
0 00000000 W
# Core 1 reads -> Core 0 supplies data, both downgrade to S
1 00000000 R
```

---

## Provided Test Traces

### `traces/multicore_test.txt` — Basic MSI scenarios

```bash
python cache_simulator.py \
  -c ../configs/multilevel.config \
  -t ../traces/multicore_test.txt \
  -p lru -m -n 2
```

| Test | Scenario |
|------|----------|
| 1 | Read sharing — two cores share a block in state S |
| 2 | Write invalidation — S -> M upgrade invalidates the other sharer |
| 3 | Modified intervention — M owner supplies data when another core reads |
| 4 | Independent addresses — no coherence traffic between cores |
| 5 | Write-write conflict — ownership transfers between cores |

---

### `traces/multicore_comprehensive.txt` — Full MSI coverage

```bash
python cache_simulator.py \
  -c ../configs/multilevel.config \
  -t ../traces/multicore_comprehensive.txt \
  -p lru -m -n 2
```

Covers 11 scenarios including ping-pong writes, multiple sharers, sequential read-write patterns, and eviction of modified blocks.

---

## Step-by-Step Test Procedures

### Test 1 — Read Sharing (I -> S)

**Trace:**
```
0 00000000 R
1 00000000 R
0 00000000 R
```

**Expected behavior:**
1. Core 0 misses -> fetches from memory -> state I->S. Directory: sharers = `{0}`.
2. Core 1 misses -> fetches from memory -> state I->S. Directory: sharers = `{0, 1}`.
3. Core 0 hits in state S. No bus transaction.

**What to check:** Step 2 is a miss; step 3 shows `time: 1` (L1 hit).

---

### Test 2 — Write Invalidation (S -> M)

**Trace:**
```
0 00000000 R
1 00000000 R
0 00000000 W
```

**Expected behavior:**
1. Steps 0–1: both cores in state S.
2. Step 2: Core 0 sends upgrade request. Core 1 invalidated (S->I). Core 0 transitions to M.

**What to check:** Step 2 incurs bus overhead (5 cycles) and Core 1 no longer holds the line.

---

### Test 3 — Modified Intervention (M -> S)

**Trace:**
```
0 00000010 W
1 00000010 R
```

**Expected behavior:**
1. Core 0 misses -> BusRdX -> state M. Directory: owner = 0.
2. Core 1 misses -> BusRd -> Core 0 supplies data (cache-to-cache: 10 cycles), both -> state S. Directory: sharers = `{0, 1}`.

**What to check:** Step 1's time reflects a cache-to-cache transfer (10 cycles) rather than a memory fetch (1000 cycles).

---

### Test 4 — Write-Write Conflict (ownership transfer)

**Trace:**
```
0 00000040 W
1 00000040 W
```

**Expected behavior:**
1. Core 0 misses -> BusRdX -> state M. Directory: owner = 0.
2. Core 1 misses -> BusRdX -> Core 0 supplies data and is invalidated (M->I). Core 1 -> M. Directory: owner = 1.

**What to check:** Both steps are misses; step 1 triggers Core 0 invalidation.

---

### Test 5 — Ping-Pong Writes

**Trace:**
```
0 00000060 W
1 00000060 W
0 00000060 W
1 00000060 W
```

**Expected behavior:** Ownership transfers on every step after the first. Every write after the first is a miss with full coherence overhead.

**What to check:** Total cycle count is high — this demonstrates the performance cost of repeated invalidations (false sharing worst case).

---

## Reading the Output

### Per-instruction log

```
0:  [Core 0] [UNKNOWN] Reading 00000000
    hit_list: {'core_0_L1': False, 'cache_2': False, 'mem': True}   time: 1017

1:  [Core 1] [UNKNOWN] Reading 00000000
    hit_list: {'core_1_L1': False, 'cache_2': True}                 time: 32

2:  [Core 0] [UNKNOWN] Reading 00000000
    hit_list: {'core_0_L1': True}                                    time: 1
```

- `hit_list`: which cache level was hit (`True`) or missed (`False`).
- `time`: cycle count for that instruction.

### Statistics summary (end of run)

```
Number of instructions: 10
Total cycles taken: 3241

Core 0 L1:
    Number of accesses: 5
    Number of hits: 1
    Number of misses: 4
    Hit rate: 20.00%
```

The full coherence trace (directory transitions, bus transactions, cache state changes) is written to `cache_simulator.log`.

---

## Timing Reference

| Event | Latency |
|-------|---------|
| L1 hit | 1 cycle (from config `hit_time`) |
| L2 hit | 16 cycles (from config `hit_time`) |
| Memory access | 1000 cycles (from config `hit_time`) |
| Bus transaction overhead | 5 cycles |
| Cache-to-cache transfer | 10 cycles |

---

## Writing Custom Traces

Use any text editor. Addresses must be 8 hex digits. Use comments to document expected states:

```
# Two cores compete for the same line
0 00001000 R       # Core 0 fetches -> S
1 00001000 R       # Core 1 fetches -> S (both share)
0 00001000 W       # Core 0 upgrades -> M, Core 1 -> I
1 00001000 W       # Core 1 takes ownership -> M, Core 0 -> I
```

Tips:
- Vary addresses to avoid unintended cache set conflicts.
- The `ATTACKER` / `VICTIM` labels appear in the log but multi-core Prime & Probe analysis is not yet implemented.
- `core_id` must be in range `[0, num_cores - 1]`; the simulator will error otherwise.

---

## Single-Core Mode (backward compatible)

Without `-m`, the simulator runs the original single-core flow with the original trace format:

```bash
python cache_simulator.py \
  -c ../configs/L1.config \
  -t ../traces/simple_trace.txt \
  -p lru
```

Single-core trace format: `<address> <operation> [ATTACKER|VICTIM]`
