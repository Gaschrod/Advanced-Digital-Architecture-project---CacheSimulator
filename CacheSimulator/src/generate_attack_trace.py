#!/usr/bin/env python3
"""
Generates a trace template to use with corresponding attack (Prime & Probe, Flush+Reload, Flush+Flush) for the cache simulator.

Usage:
    python3 generate_attack_trace.py -c <config_file> [-o <output_file>] [-s <target_set>]

Arguments:
    -c / --config-file   : YAML config file (required)
    -o / --output-file   : Output trace file (default: prime_probe_trace.txt)
    -s / --target-set    : Target a specific set index only (default: all sets)

Output format:
    A ready-to-use trace template with:
    - Setup phase: Attacker accesses to prime or flush cache lines
    - Victim phase: Placeholder lines for victim accesses (to be replaced by user)
    - Probe phase: Attacker accesses to probe the cache state

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

import yaml, math, argparse, sys

def compute_cache_geometry(configs):
    block_size   = configs['architecture']['block_size']
    n_blocks     = configs['cache_1']['blocks']
    associativity = configs['cache_1']['associativity']
    n_sets       = n_blocks // associativity
    offset_bits  = int(math.log2(block_size))
    index_bits   = int(math.log2(n_sets)) if n_sets > 1 else 0

    return {
        'block_size': block_size, 'n_blocks': n_blocks,
        'associativity': associativity, 'n_sets': n_sets,
        'offset_bits': offset_bits, 'index_bits': index_bits,
    }

def make_address(set_index, way_index, offset_bits, index_bits):
    address = (way_index << (index_bits + offset_bits)) | (set_index << offset_bits)
    return f"{address:08X}"

def generate_trace(geometry, target_set, attack_type):
    n_sets = geometry['n_sets']
    associativity = geometry['associativity']
    offset_bits = geometry['offset_bits']
    index_bits = geometry['index_bits']

    sets_to_target = [target_set] if target_set is not None else list(range(n_sets))
    
    setup_lines, victim_lines, probe_lines = [], [], []

    if attack_type == 'prime_probe':
        for s in sets_to_target:
            setup_lines.append(f"# --- Set {s} ---")
            probe_lines.append(f"# --- Set {s} ---")
            for w in range(associativity):
                addr = make_address(s, w, offset_bits, index_bits)
                setup_lines.append(f"{addr} R ATTACKER")
                probe_lines.append(f"{addr} R ATTACKER")
    else:
        # Architecture trace Flush+Reload et Flush+Flush
        for s in sets_to_target:
            setup_lines.append(f"# --- Set {s} ---")
            probe_lines.append(f"# --- Set {s} ---")
            addr = make_address(s, 0, offset_bits, index_bits) 
            
            # Phase 1: Vider la ligne du cache (Flush)
            setup_lines.append(f"{addr} F ATTACKER")
            
            # Phase 3: Probe
            if attack_type == 'flush_reload':
                probe_lines.append(f"{addr} R ATTACKER") # Recharger (Read)
            elif attack_type == 'flush_flush':
                probe_lines.append(f"{addr} F ATTACKER") # Re-flusher (Flush)

    victim_lines.append("# --- VICTIM PHASE ---")
    victim_lines.append("# Replace these lines with your actual victim accesses.")
    for s in sets_to_target[:min(2, len(sets_to_target))]:
        if attack_type == 'prime_probe':
            example_addr = make_address(s, associativity, offset_bits, index_bits)
        else:
            example_addr = make_address(s, 0, offset_bits, index_bits)
            
        victim_lines.append(f"# {example_addr} R VICTIM")
        
    return setup_lines, victim_lines, probe_lines

def write_trace_file(geometry, setup_lines, victim_lines, probe_lines, output_file, attack_type):
    with open(output_file, 'w') as f:
        f.write(f"# Auto-generated trace for {attack_type.upper()}\n")
        f.write("#\n# === PHASE 1: SETUP ===\n")
        for line in setup_lines: f.write(line + "\n")
        
        f.write("\n# === PHASE 2: VICTIM ===\n")
        for line in victim_lines: f.write(line + "\n")
        
        f.write("\n# === PHASE 3: PROBE ===\n")
        for line in probe_lines: f.write(line + "\n")

def main():
    parser = argparse.ArgumentParser(description='Generate traces for cache attacks.')
    parser.add_argument('-c', '--config-file', required=True)
    parser.add_argument('-a', '--attack-type', choices=['prime_probe', 'flush_reload', 'flush_flush'], required=True)
    parser.add_argument('-o', '--output-file', default='attack_trace.txt')
    parser.add_argument('-s', '--target-set', type=int, default=None)
    args = parser.parse_args()

    with open(args.config_file) as f:
        configs = yaml.safe_load(f)

    geometry = compute_cache_geometry(configs)
    setup_lines, victim_lines, probe_lines = generate_trace(geometry, args.target_set, args.attack_type)
    write_trace_file(geometry, setup_lines, victim_lines, probe_lines, args.output_file, args.attack_type)
    print(f"Trace template ({args.attack_type}) written to: {args.output_file}")

if __name__ == '__main__':
    main()