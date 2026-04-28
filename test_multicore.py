#!/usr/bin/env python3
"""
Multi-core cache simulator test suite.
Run from the repository root: python test_multicore.py
"""
import subprocess
import re
import sys
import os

SRC = os.path.join(os.path.dirname(__file__), "CacheSimulator", "src")
CFG = os.path.join(os.path.dirname(__file__), "CacheSimulator", "configs", "multilevel.config")
TRC = os.path.join(os.path.dirname(__file__), "CacheSimulator", "traces")

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"
INFO = "\033[36mINFO\033[0m"

# ---------------------------------------------------------------------------
# Test definitions
# Each entry: name, trace file, num_cores, list of expected cycle times
# (one entry per R/W instruction, in order; F/FA produce no time entry).
# A None value means "skip this step" (don't assert timing).
# A tuple (expected, note) adds an annotation to the result line.
# ---------------------------------------------------------------------------
TESTS = [
    {
        "name": "T01 — Single core: all MSI transitions",
        "trace": "T01_single_core.txt",
        "num_cores": 2,
        "expected_times": [
            (1021, "cold miss I→S, bus+L2-miss+mem"),
            (1,    "local read hit in S"),
            (5,    "bus upgrade S→M"),
            (1,    "local write hit in M"),
            (1,    "local read hit in M"),
        ],
        "expected_total": 1029,
        "notes": [],
    },
    {
        "name": "T02 — Two cores: read sharing (S state)",
        "trace": "T02_read_sharing.txt",
        "num_cores": 2,
        "expected_times": [
            (1021, "Core 0 cold miss I→S"),
            (21,   "Core 1 miss, L2 hit (5+16)"),
            (1,    "Core 0 local hit in S"),
            (1,    "Core 1 local hit in S"),
        ],
        "expected_total": 1044,
        "notes": [],
    },
    {
        "name": "T03 — Write invalidation (S→M, remote I)",
        "trace": "T03_write_invalidation.txt",
        "num_cores": 2,
        "expected_times": [
            (1021, "Core 0 cold miss I→S"),
            (21,   "Core 1 miss, L2 hit"),
            (5,    "Core 0 upgrade S→M, Core 1 invalidated"),
            (15,   "Core 1 miss, Core 0 intervention M→S (5+10)"),
            (1,    "Core 0 local hit in S"),
            (1,    "Core 1 local hit in S"),
        ],
        "expected_total": 1064,
        "notes": [],
    },
    {
        "name": "T04 — Modified→Shared intervention on read",
        "trace": "T04_modified_read_intervention.txt",
        "num_cores": 2,
        "expected_times": [
            (1021, "Core 0 cold write miss I→M"),
            (15,   "Core 1 read, Core 0 intervenes M→S (5+10)"),
            (1,    "Core 0 local hit in S"),
            (1,    "Core 1 local hit in S"),
        ],
        "expected_total": 1038,
        "notes": [],
    },
    {
        "name": "T05 — Ownership transfer (M→M)",
        "trace": "T05_ownership_transfer.txt",
        "num_cores": 2,
        "expected_times": [
            (1021, "Core 0 cold write miss I→M"),
            (15,   "Core 1 write, Core 0 supplies and is invalidated (5+10)"),
            (1,    "Core 1 local write hit in M"),
            (15,   "Core 0 write, Core 1 supplies and is invalidated (5+10)"),
            (1,    "Core 0 local read hit in M"),
        ],
        "expected_total": 1053,
        "notes": [],
    },
    {
        "name": "T06 — Ping-pong: repeated ownership transfers",
        "trace": "T06_ping_pong.txt",
        "num_cores": 2,
        "expected_times": [
            (1021, "Core 0 cold miss I→M"),
            (15,   "Core 1 write: c2c transfer"),
            (15,   "Core 0 write: c2c transfer"),
            (15,   "Core 1 write: c2c transfer"),
            (15,   "Core 0 write: c2c transfer"),
            (15,   "Core 1 write: c2c transfer"),
        ],
        "expected_total": 1096,
        "notes": ["Every write after first costs 15 cycles (bus overhead + c2c), never a local hit."],
    },
    {
        "name": "T07 — Three cores: multiple sharers and mass invalidation",
        "trace": "T07_three_cores.txt",
        "num_cores": 3,
        "expected_times": [
            (1021, "Core 0 cold miss I→S"),
            (21,   "Core 1 miss, L2 hit"),
            (21,   "Core 2 miss, L2 hit"),
            (5,    "Core 0 upgrade S→M, invalidates Cores 1 and 2"),
            (15,   "Core 1 miss, Core 0 intervenes M→S (5+10)"),
            (21,   "Core 2 miss, dir S, L2 hit (5+16)"),
            (5,    "Core 1 upgrade S→M, invalidates Cores 0 and 2"),
        ],
        "expected_total": 1109,
        "notes": [],
    },
    {
        "name": "T08 — Eviction aliasing (same L1 set, stale directory)",
        "trace": "T08_eviction_aliasing.txt",
        "num_cores": 2,
        "expected_times": [
            (1021, "Core 0 R 00000000, cold miss"),
            (1021, "Core 0 R 00000080, cold miss (same L1 set 0, way 2)"),
            (21,   "Core 1 R 00000000, L2 hit"),
            (1021, "Core 0 R 00000100, cold miss; evicts 00000000 from L1 (LRU)"),
            (21,   "Core 0 R 00000000, miss in L1 but dir/L2 still have it — L2 hit"),
        ],
        "expected_total": 3105,
        "notes": [
            "FIX: install_block now returns eviction info; bus calls process_eviction.",
            "After step 3, directory correctly removes Core 0 from sharers for 00000000.",
            "Step 4 still hits L2 (21 cycles) — timing unchanged but directory state is now correct.",
        ],
    },
    {
        "name": "T09 — Flush in multi-core (directory notified after flush)",
        "trace": "T09_flush_multicore.txt",
        "num_cores": 2,
        # F op at step 1 produces no time entry
        "expected_times": [
            (1021, "Core 0 write miss I→M"),
            (1021, "Core 1 read: directory correctly shows I → full memory fetch (5+1016)"),
            (1,    "Core 1 local hit in S"),
        ],
        "expected_total": 2043,
        "notes": [
            "FIX: core.flush() now calls directory.process_eviction() → M→I transition.",
            "Core 1 no longer gets a bogus 15-cycle cache-to-cache; it pays the real 1021-cycle cost.",
        ],
    },
    {
        "name": "T10 — Independent cores: zero coherence traffic",
        "trace": "T10_independent_cores.txt",
        "num_cores": 2,
        "expected_times": [
            (1021, "Core 0 R 00000000, cold miss"),
            (1021, "Core 1 R 00000010, cold miss (independent address)"),
            (5,    "Core 0 upgrade S→M"),
            (5,    "Core 1 upgrade S→M"),
            (1,    "Core 0 write hit M"),
            (1,    "Core 1 write hit M"),
            (1,    "Core 0 read hit M"),
            (1,    "Core 1 read hit M"),
        ],
        "expected_total": 2056,
        "notes": ["No interventions, no invalidations — completely independent address spaces."],
    },
    {
        "name": "T11 — Producer-consumer read-modify-write pattern",
        "trace": "T11_read_then_write_cycle.txt",
        "num_cores": 2,
        "expected_times": [
            (1021, "Core 0 R, cold miss I→S"),
            (5,    "Core 0 upgrade S→M"),
            (1,    "Core 0 write hit M"),
            (15,   "Core 1 R, Core 0 intervenes M→S (5+10)"),
            (5,    "Core 1 upgrade S→M, Core 0 invalidated"),
            (1,    "Core 1 write hit M"),
            (15,   "Core 0 R, Core 1 intervenes M→S (5+10)"),
            (1,    "Core 0 read hit S"),
        ],
        "expected_total": 1064,
        "notes": [],
    },
    {
        "name": "T12 — Four-core broadcast: one writer, many readers",
        "trace": "T12_four_cores_broadcast.txt",
        "num_cores": 4,
        "expected_times": [
            (1021, "Core 0 cold write miss I→M"),
            (15,   "Core 1 R, Core 0 intervenes M→S (5+10)"),
            (21,   "Core 2 R, dir S, L2 hit (5+16)"),
            (21,   "Core 3 R, dir S, L2 hit (5+16)"),
            (5,    "Core 0 upgrade S→M, invalidates Cores 1,2,3"),
            (1,    "Core 0 write hit M"),
            (15,   "Core 1 R, Core 0 intervenes M→S again (5+10)"),
        ],
        "expected_total": 1099,
        "notes": [],
    },
]


def run_simulator(trace_file, num_cores):
    cmd = [
        sys.executable,
        os.path.join(SRC, "cache_simulator.py"),
        "-c", CFG,
        "-t", os.path.join(TRC, trace_file),
        "-p", "lru",
        "-m",
        "-n", str(num_cores),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=SRC)
    return result.returncode, result.stdout + result.stderr


def parse_times(output):
    """Extract per-step cycle counts from simulator output (R/W ops only)."""
    return [int(m) for m in re.findall(r"time:\s+(\d+)", output)]


def parse_total(output):
    m = re.search(r"Total cycles taken:\s+(\d+)", output)
    return int(m.group(1)) if m else None


def run_tests():
    print("=" * 72)
    print("Multi-Core Cache Simulator — Test Suite")
    print("=" * 72)

    passed = failed = 0

    for test in TESTS:
        name = test["name"]
        print(f"\n{'─' * 72}")
        print(f"  {name}")
        print(f"{'─' * 72}")

        rc, output = run_simulator(test["trace"], test["num_cores"])

        # Check process exit code
        if rc != 0:
            print(f"  [{FAIL}] Simulator exited with code {rc}")
            print(output[-2000:])
            failed += 1
            continue

        actual_times = parse_times(output)
        expected_times = [e[0] if isinstance(e, tuple) else e for e in test["expected_times"]]
        step_notes = [e[1] if isinstance(e, tuple) else "" for e in test["expected_times"]]

        actual_total = parse_total(output)
        expected_total = test.get("expected_total")

        # Check instruction count
        if len(actual_times) != len(expected_times):
            print(f"  [{FAIL}] Step count mismatch: got {len(actual_times)}, "
                  f"expected {len(expected_times)}")
            print(f"         Actual times: {actual_times}")
            failed += 1
            continue

        step_ok = True
        for i, (actual, expected, note) in enumerate(zip(actual_times, expected_times, step_notes)):
            status = PASS if actual == expected else FAIL
            flag = "" if actual == expected else f"  ← got {actual}"
            print(f"  step {i}: [{status}] expected {expected:5d}  {note}{flag}")
            if actual != expected:
                step_ok = False

        # Total cycles check
        total_ok = True
        if expected_total is not None and actual_total is not None:
            total_ok = actual_total == expected_total
            status = PASS if total_ok else FAIL
            flag = f"  ← got {actual_total}" if not total_ok else ""
            print(f"  total:  [{status}] expected {expected_total}{flag}")
        elif actual_total is not None:
            print(f"  total:  [{INFO}] {actual_total} cycles")

        # Annotations
        for note in test.get("notes", []):
            print(f"  [{INFO}] {note}")

        if step_ok and total_ok:
            passed += 1
        else:
            failed += 1

    print(f"\n{'=' * 72}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed} tests")
    print("=" * 72)

    # Extra: per-core statistics note
    print(f"""
[{INFO}] Statistics note:
  Per-core hit/miss counts only include BUS operations (R/W misses that go
  through the bus). Local hits in M or S state (response key='cache_1') are
  NOT counted, so reported accesses will be lower than actual.
""")

    return failed


if __name__ == "__main__":
    sys.exit(run_tests())
