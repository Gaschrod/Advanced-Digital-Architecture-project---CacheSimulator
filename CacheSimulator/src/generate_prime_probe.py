#!/usr/bin/env python3
"""
generate_prime_probe.py
-----------------------
Generates a Prime & Probe trace template for the cache simulator.

Usage:
    python3 generate_prime_probe.py -c <config_file> [-o <output_file>] [-s <target_set>]

Arguments:
    -c / --config-file   : YAML config file (required)
    -o / --output-file   : Output trace file (default: prime_probe_trace.txt)
    -s / --target-set    : Target a specific set index only (default: all sets)

Output format:
    A ready-to-use trace template with:
      - PRIME phase   : attacker fills every way of every target set
      - VICTIM phase  : placeholder lines for student to fill in
      - PROBE phase   : same addresses as prime, in same order

It's only needed to replace the VICTIM section with actual victim accesses.
ATTACKER lines should not be modified!

Address construction:
    address = (way_index << (index_bits + offset_bits)) | (set_index << offset_bits)
    - offset bits  = log2(block_size)   → selects byte within block
    - index bits   = log2(n_sets)       → selects the cache set
    - tag bits     = everything above   → different tags = different ways
    
    For fully associative caches (n_sets=1, index_bits=0):
    - All addresses map to the same single set
    - Way separation is achieved purely through different tag values
"""

import yaml
import math
import argparse
import sys


def compute_cache_geometry(configs):
    """
    Derive the cache geometry from a config file.
    Returns a dict with all relevant parameters.
    """
    block_size   = configs['architecture']['block_size']
    n_blocks     = configs['cache_1']['blocks']
    associativity = configs['cache_1']['associativity']

    n_sets           = n_blocks // associativity
    offset_bits      = int(math.log2(block_size))
    # Edge case: fully associative → n_sets=1 → log2(1)=0 index bits
    index_bits       = int(math.log2(n_sets)) if n_sets > 1 else 0

    return {
        'block_size'   : block_size,
        'n_blocks'     : n_blocks,
        'associativity': associativity,
        'n_sets'       : n_sets,
        'offset_bits'  : offset_bits,
        'index_bits'   : index_bits,
    }


def make_address(set_index, way_index, offset_bits, index_bits):
    """
    Build a hex address that maps to a specific (set, way) pair.

    For fully associative (index_bits=0):
        [ tag | offset ]   (no index field)
        tag = way_index → guarantees each address maps to a different block
    """
    address = (way_index << (index_bits + offset_bits)) | (set_index << offset_bits)
    # Format as 8 hex digits, zero-padded, uppercase
    return f"{address:08X}"


def generate_trace(geometry, target_set=None):
    """
    Generate the full list of trace lines for prime, victim placeholder, and probe.
    Returns (prime_lines, victim_lines, probe_lines) as lists of strings.
    """
    n_sets        = geometry['n_sets']
    associativity = geometry['associativity']
    offset_bits   = geometry['offset_bits']
    index_bits    = geometry['index_bits']

    # Determine which sets to target
    if target_set is not None:
        if target_set >= n_sets:
            print(f"Error: target set {target_set} does not exist "
                  f"(cache has {n_sets} sets, indices 0–{n_sets-1})")
            sys.exit(1)
        sets_to_target = [target_set]
    else:
        sets_to_target = list(range(n_sets))

    prime_lines  = []
    probe_lines  = []
    victim_lines = []

    for s in sets_to_target:
        prime_lines.append(f"# --- Set {s} ---")
        probe_lines.append(f"# --- Set {s} ---")
        for w in range(associativity):
            addr = make_address(s, w, offset_bits, index_bits)
            prime_lines.append(f"{addr} R ATTACKER")
            probe_lines.append(f"{addr} R ATTACKER")

    # Victim placeholder — one line per target set as a guide
    victim_lines.append("# Replace these lines with your actual victim accesses.")
    victim_lines.append("# Use addresses that map to the sets you want to monitor.")
    victim_lines.append("# Format: <address> <R|W> VICTIM")
    victim_lines.append("# Example:")
    for s in sets_to_target[:min(2, len(sets_to_target))]:  # show 1-2 examples
        example_addr = make_address(s, associativity, offset_bits, index_bits)
        victim_lines.append(f"# {example_addr} R VICTIM  # would evict something in set {s}")

    return prime_lines, victim_lines, probe_lines


def write_trace_file(geometry, prime_lines, victim_lines, probe_lines,
                     output_file, config_file, target_set):
    """
    Write the full annotated trace template to disk.
    """
    n_sets        = geometry['n_sets']
    associativity = geometry['associativity']
    block_size    = geometry['block_size']
    offset_bits   = geometry['offset_bits']
    index_bits    = geometry['index_bits']

    target_desc = f"set {target_set}" if target_set is not None else "all sets"

    with open(output_file, 'w') as f:
        # Header
        f.write("# ============================================================\n")
        f.write("# Prime & Probe Trace Template\n")
        f.write("# Auto-generated by generate_prime_probe.py\n")
        f.write(f"# Config file  : {config_file}\n")
        f.write(f"# Target       : {target_desc}\n")
        f.write("# ============================================================\n")
        f.write("#\n")
        f.write("# Cache geometry (cache_1):\n")
        f.write(f"#   Block size    : {block_size} bytes\n")
        f.write(f"#   Sets          : {n_sets}\n")
        f.write(f"#   Associativity : {associativity}-way\n")
        f.write(f"#   Offset bits   : {offset_bits}\n")
        f.write(f"#   Index bits    : {index_bits}\n")
        if index_bits == 0:
            f.write("#   NOTE: Fully associative cache — no index field in address.\n")
            f.write("#         All addresses map to the single set. Tags distinguish ways.\n")
        f.write("#\n")
        f.write("# Address layout: [ tag | index | offset ]\n")
        f.write(f"#                         {index_bits} bits  {offset_bits} bits\n")
        f.write("#\n")
        f.write("# HOW TO USE:\n")
        f.write("#   1. Do NOT modify the ATTACKER lines.\n")
        f.write("#   2. Replace the VICTIM section with your victim's memory accesses.\n")
        f.write("#   3. Run: python3 cache_simulator.py -c <config> -t <this_file>\n")
        f.write("#   4. Check the Prime & Probe Analysis in the output:\n")
        f.write("#        MISS on probe → victim accessed that set\n")
        f.write("#        HIT  on probe → victim did not access that set\n")
        f.write("# ============================================================\n")
        f.write("\n")

        # Prime phase
        f.write("# ============================================================\n")
        f.write("# PRIME PHASE — attacker fills all target sets\n")
        f.write("# ============================================================\n")
        for line in prime_lines:
            f.write(line + "\n")
        f.write("\n")

        # Victim phase
        f.write("# ============================================================\n")
        f.write("# VICTIM PHASE — replace with actual victim accesses\n")
        f.write("# ============================================================\n")
        for line in victim_lines:
            f.write(line + "\n")
        f.write("\n")

        # Probe phase
        f.write("# ============================================================\n")
        f.write("# PROBE PHASE — attacker re-reads primed addresses\n")
        f.write("# ============================================================\n")
        for line in probe_lines:
            f.write(line + "\n")


def print_summary(geometry, config_file, output_file, target_set):
    """Print a human-readable summary to stdout."""
    n_sets        = geometry['n_sets']
    associativity = geometry['associativity']
    offset_bits   = geometry['offset_bits']
    index_bits    = geometry['index_bits']
    n_prime_lines = (len([target_set]) if target_set is not None else n_sets) * associativity

    print("\n=== Prime & Probe Address Generator ===")
    print(f"  Config        : {config_file}")
    print(f"  Sets          : {n_sets}")
    print(f"  Associativity : {associativity}-way")
    print(f"  Offset bits   : {offset_bits}")
    print(f"  Index bits    : {index_bits}")
    if index_bits == 0:
        print("  NOTE          : Fully associative — single set, tag-only addressing")
    print(f"  Target        : {'set ' + str(target_set) if target_set is not None else 'all sets'}")
    print(f"  Prime lines   : {n_prime_lines}  (= {n_sets if target_set is None else 1} set(s) × {associativity} way(s))")
    print(f"  Output file   : {output_file}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description='Generate a Prime & Probe trace template for the cache simulator.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('-c', '--config-file',
                        help='YAML cache configuration file', required=True)
    parser.add_argument('-o', '--output-file',
                        help='Output trace file (default: prime_probe_trace.txt)',
                        default='prime_probe_trace.txt')
    parser.add_argument('-s', '--target-set',
                        help='Target a specific set index only (default: all sets)',
                        type=int, default=None)
    args = parser.parse_args()

    # Load config
    try:
        with open(args.config_file) as f:
            configs = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: config file '{args.config_file}' not found.")
        sys.exit(1)

    # Validate required sections
    for section in ('architecture', 'cache_1', 'mem'):
        if section not in configs:
            print(f"Error: config file missing required section '{section}'.")
            sys.exit(1)

    geometry = compute_cache_geometry(configs)
    prime_lines, victim_lines, probe_lines = generate_trace(geometry, args.target_set)
    write_trace_file(geometry, prime_lines, victim_lines, probe_lines,
                     args.output_file, args.config_file, args.target_set)
    print_summary(geometry, args.config_file, args.output_file, args.target_set)
    print(f"Trace template written to: {args.output_file}")


if __name__ == '__main__':
    main()
