#!/usr/bin/env python

import yaml, cache, argparse, logging, pprint
from terminaltables.other_tables import UnixTable
import core, bus, directory


def main():
    # Set up our arguments
    parser = argparse.ArgumentParser(description="Simulate a cache")
    parser.add_argument(
        "-c",
        "--config-file",
        help="Configuration file for the memory heirarchy",
        required=True,
    )
    parser.add_argument(
        "-t", "--trace-file", help="Tracefile containing instructions", required=True
    )
    parser.add_argument(
            "-m",
            "--multi-core",
            help="Enable multi-core simulation with MSI coherence",
            required=False,
            action="store_true",
            )
    parser.add_argument(
            "-n",
            "--num-cores",
            help="Number of cores for multi-core simulation (default: 2)",
            type=int,
            required=False,
            default=2,
            )
    parser.add_argument(
        "-p",
        "--policy",
        choices=["lru", "mru", "nru", "lfu", "fifo", "lifo", "filo", "random"],
        help="Eviction policy to use (lru, mru, nru, lfu, fifo, lifo, filo, random)",
        type=str.lower,
        required=False,
        default="lru",
    )
    parser.add_argument(
        "-a",
        "--attack-type",
        choices=["prime_probe", "flush_reload", "flush_flush"],
        help="Type of attack to analyze (prime_probe or flush_reload)",
        type=str.lower,
        required=False,
    )
    parser.add_argument("-l", "--log-file", help="Log file name", required=False)
    parser.add_argument(
        "-b", "--beautify", help="Use colors", required=False, action="store_true"
    )
    parser.add_argument(
        "-d",
        "--draw-cache",
        help="Draw cache layouts",
        required=False,
        action="store_true",
    )
    arguments = vars(parser.parse_args())

    policy = arguments["policy"]
    attack_type = arguments["attack_type"]

    if arguments["beautify"]:
        import colorer

    log_filename = "cache_simulator.log"
    if arguments["log_file"]:
        log_filename = arguments["log_file"]

    # Clear the log file if it exists
    with open(log_filename, "w"):
        pass

    logger = logging.getLogger()
    fh = logging.FileHandler(log_filename)
    sh = logging.StreamHandler()
    logger.addHandler(fh)
    logger.addHandler(sh)

    fh_format = logging.Formatter("%(message)s")
    fh.setFormatter(fh_format)
    sh.setFormatter(fh_format)
    logger.setLevel(logging.INFO)

    logger.info("Loading config...")
    config_file = open(arguments["config_file"])
    configs = yaml.safe_load(config_file)

    # Multi-core or single-core mode
    if arguments["multi_core"]:
        logger.info(
            f'Building multi-core hierarchy with {arguments["num_cores"]} cores...'
        )
        hierarchy = build_multicore_hierarchy(
            configs, logger, policy, arguments["num_cores"]
        )
        logger.info("Multi-core memory hierarchy built.")
    else:
        hierarchy = build_hierarchy(configs, logger, policy)
        logger.info("Memory hierarchy built.")

    logger.info("Loading tracefile...")
    trace_file = open(arguments["trace_file"])
    trace = trace_file.read().splitlines()
    trace = [item for item in trace if item.strip() and not item.startswith("#")]
    logger.info("Loaded tracefile " + arguments["trace_file"])
    logger.info("Begin simulation!")

    # Run appropriate simulation
    # WARNING: check for attack_type in multicore
    if arguments["multi_core"]:
        simulate_multicore(hierarchy, trace, logger, attack_type)
    else:
        simulate(hierarchy, trace, logger, attack_type)

    if arguments["draw_cache"]:
        if arguments["multi_core"]:
            # Draw L1 caches for each core
            for i in range(arguments["num_cores"]):
                cache_name = f"cache_1_core_{i}"
                if cache_name in hierarchy and hierarchy[cache_name].next_level:
                    print_cache(hierarchy[cache_name])
        else:
            for cache_item in hierarchy:
                if hierarchy[cache_item].next_level:
                    print_cache(hierarchy[cache_item])


# Print the contents of a cache as a table
# If the table is too long, it will print the first few sets,
# break, and then print the last set
def print_cache(cache):
    table_size = 5
    ways = [""]
    sets = []
    set_indexes = sorted(cache.data.keys())
    if len(cache.data.keys()) > 0:
        first_key = list(cache.data.keys())[0]
        way_no = 0

        # Label the columns
        for way in range(cache.associativity):
            ways.append("Way " + str(way_no))
            way_no += 1

        # Print either all the sets if the cache is small, or just a few
        # sets and then the last set
        sets.append(ways)
        if len(set_indexes) > table_size + 4 - 1:
            for s in range(min(table_size, len(set_indexes) - 4)):
                set_ways = cache.data[set_indexes[s]].keys()
                temp_way = ["Set " + str(s)]
                for w in set_ways:
                    temp_way.append(cache.data[set_indexes[s]][w].address)
                sets.append(temp_way)

            for i in range(3):
                temp_way = ["."]
                for w in range(cache.associativity):
                    temp_way.append("")
                sets.append(temp_way)

            set_ways = cache.data[set_indexes[len(set_indexes) - 1]].keys()
            temp_way = ["Set " + str(len(set_indexes) - 1)]
            for w in set_ways:
                temp_way.append(
                    cache.data[set_indexes[len(set_indexes) - 1]][w].address
                )
            sets.append(temp_way)
        else:
            for s in range(len(set_indexes)):
                set_ways = cache.data[set_indexes[s]].keys()
                temp_way = ["Set " + str(s)]
                for w in set_ways:
                    temp_way.append(cache.data[set_indexes[s]][w].address)
                sets.append(temp_way)

        table = UnixTable(sets)
        table.title = cache.name
        table.inner_row_border = True
        print("\n")
        print(table.table)


# Loop through the instructions in the tracefile and use the given memory hierarchy to find AMAT (Average Memory Access Time)
def simulate(hierarchy, trace, logger, attack_type):
    responses = []
    # We only interface directly with L1. Reads and writes will automatically interact with lower levels of the hierarchy
    l1 = hierarchy["cache_1"]
    for current_step in range(len(trace)):
        instruction = trace[current_step]

        parts = instruction.split()
        if len(parts) == 3:
            address, op, actor = parts  # Actor = ATTACKER or VICTIM
            if actor not in ["ATTACKER", "VICTIM"]:
                raise cache.InvalidOpError
        elif (
            len(parts) == 2
        ):  # Possible to use cache simulator without attacker/victim roles (base case)
            address, op = parts
            actor = "UNKNOWN"
        else:
            raise cache.InvalidOpError

        # Call read for this address on our memory hierarchy
        if op == "R":
            logger.info(str(current_step) + ":\t[" + actor + "] Reading " + address)
            r = l1.read(address, current_step)
            r.actor = actor
            r.address = address
            logger.warning(
                "\thit_list: "
                + pprint.pformat(r.hit_list)
                + "\ttime: "
                + str(r.time)
                + "\n"
            )
            responses.append(r)
        elif op == "W":
            logger.info(str(current_step) + ":\t[" + actor + "] Writing " + address)
            r = l1.write(address, True, current_step)
            r.actor = actor
            r.address = address
            logger.warning(
                "\thit_list: "
                + pprint.pformat(r.hit_list)
                + "\ttime: "
                + str(r.time)
                + "\n"
            )
            responses.append(r)
        elif op == "F":
            logger.info(str(current_step) + ":\t[" + actor + "] Flushing " + address)
            r = l1.flush(address, current_step)
            r.actor = actor
            r.address = address
            r.flush_hit = any(
                hit for level, hit in r.hit_list.items() if level != "mem"
            )
            logger.warning(
                "\thit_list: "
                + pprint.pformat(r.hit_list)
                + "\ttime: "
                + str(r.time)
                + "\tflush_hit: "
                + str(r.flush_hit)
                + "\n"
            )
            responses.append(r)
        elif op == "FA":  # Doesn't care about the address which is a placeholder anyway
            logger.info(str(current_step) + ":\t[" + actor + "] Flushing all")
            r = l1.flush_all(current_step)
            logger.info("\n")
        else:
            raise cache.InvalidOpError
    logger.info("Simulation complete")
    analyze_results(hierarchy, responses, logger, attack_type)


def get_llc_name(hierarchy):
    # Dynamically find the Last Level Cache (LLC) based on the configuration
    if "cache_3" in hierarchy:
        return "cache_3"
    if "cache_2" in hierarchy:
        return "cache_2"
    return "cache_1"


def analyze_results(hierarchy, responses, logger, attack_type):
    n_instructions = len(responses)
    total_time = sum(r.time for r in responses)

    logger.info("\nNumber of instructions: " + str(n_instructions))
    logger.info("\nTotal cycles taken: " + str(total_time) + "\n")

    # Split by actor
    attacker_responses = [r for r in responses if r.actor == "ATTACKER"]
    victim_responses = [r for r in responses if r.actor == "VICTIM"]

    # Standard AMAT on all responses
    amat = compute_amat(hierarchy["cache_1"], responses, logger)
    logger.info("\nAMATs:\n" + pprint.pformat(amat))

    # Prime & Probe report — only if both actors are present
    if attacker_responses and victim_responses:
        if attack_type == "prime_probe":
            logger.info("\n=== Prime & Probe Analysis ===")
            analyze_prime_probe(hierarchy["cache_1"], attacker_responses, logger)
        elif attack_type == "flush_reload":
            logger.info("\n=== Flush & Reload Analysis ===")
            analyze_flush_reload(hierarchy, responses, logger)
        elif attack_type == "flush_flush":
            logger.info("\n=== Flush & Flush Analysis ===")
            analyze_flush_flush(responses, logger)
        else:
            logger.info(
                "\nNo attack type specified, skipping attack analysis. Use -a or --attack-type to specify an attack type for analysis."
            )


def compute_amat(level, responses, logger, results={}):
    # Check if this is main memory
    # Main memory has a non-variable hit time
    if not level.next_level:
        results[level.name] = level.hit_time
    else:
        # Find out how many times this level of cache was accessed
        # And how many of those accesses were misses
        n_miss = 0
        n_access = 0
        for r in responses:
            if level.name in r.hit_list.keys():
                n_access += 1
                if r.hit_list[level.name] == False:
                    n_miss += 1

        if n_access > 0:
            miss_rate = float(n_miss) / n_access
            # Recursively compute the AMAT of this level of cache by computing
            # the AMAT of lower levels
            results[level.name] = round(
                level.hit_time
                + miss_rate
                * compute_amat(level.next_level, responses, logger)[
                    level.next_level.name
                ],
                2,
            )
        else:
            results[level.name] = round(
                0
                * compute_amat(level.next_level, responses, logger)[
                    level.next_level.name
                ],
                2,
            )

        logger.info(level.name)
        logger.info("\tNumber of accesses: " + str(n_access))
        logger.info("\tNumber of hits: " + str(n_access - n_miss))
        logger.info("\tNumber of misses: " + str(n_miss))
    return results


def analyze_prime_probe(l1, attacker_responses, logger):
    # The trace template guarantees: first N are prime, last N are probe
    # (N = total attacker accesses / 2)
    mid = len(attacker_responses) // 2
    prime_responses = attacker_responses[:mid]
    probe_responses = attacker_responses[mid:]

    logger.info("Probe results (miss = victim accessed that set):")
    compromised_sets = []

    for prime_r, probe_r in zip(prime_responses, probe_responses):
        # Get the address from the probe response's hit_list context
        # A miss on probe means the victim evicted the attacker's line
        hit_in_l1 = probe_r.hit_list.get("cache_1", False)
        status = (
            "HIT  (set untouched)" if hit_in_l1 else "MISS (victim accessed this set!)"
        )
        logger.info("Probe address: " + str(probe_r.address) + " -> " + status)
        if not hit_in_l1:
            compromised_sets.append(probe_r)

    logger.info("\nSets likely accessed by victim: " + str(len(compromised_sets)))


def analyze_flush_reload(hierarchy, responses, logger):
    llc_name = get_llc_name(hierarchy)
    llc = hierarchy[llc_name]
    mem = hierarchy["mem"]

    # Threshold: anything below memory latency means the line was found in LLC
    # (shared across cores) — the attacker can't observe the victim's private L1/L2
    threshold = (llc.hit_time + mem.hit_time) // 2

    flush_addresses = {
        r.address
        for r in responses
        if r.actor == "ATTACKER" and getattr(r, "flush_hit", None) is not None
    }

    attacker_reads = [
        r
        for r in responses
        if r.actor == "ATTACKER"
        and r.address in flush_addresses
        and getattr(r, "flush_hit", None) is None
    ]

    accessed = []
    for r in attacker_reads:
        # In a real cross-core scenario, a victim access leaves the line in the shared LLC.
        # The reload time reflects LLC latency (fast) vs memory latency (slow).
        if r.time <= threshold:
            status = f"FAST reload (time={r.time} ≤ threshold={threshold}) → victim accessed this line (found in LLC)"
            accessed.append(r.address)
        else:
            status = f"SLOW reload (time={r.time} > threshold={threshold}) → victim did not access (fetched from memory)"

        logger.info(f"Reload @ {r.address}: {status}")

    logger.info(
        f"\nThreshold used: {threshold} cycles (LLC={llc.hit_time}, mem={mem.hit_time})"
    )
    logger.info(f"Lines likely accessed by victim: {len(accessed)}")
    for addr in accessed:
        logger.info(f"\t{addr}")


def analyze_flush_flush(responses, logger):
    # Flush+Flush is only meaningful if the attacker and victim share a cache line, so we look for flushes that hit in the victim's accesses

    attacker_flushes = [
        r
        for r in responses
        if r.actor == "ATTACKER" and getattr(r, "flush_hit", None) is not None
    ]
    seen = set()
    probe_flushes = []
    for r in attacker_flushes:
        if r.address in seen:
            probe_flushes.append(r)
        else:
            seen.add(r.address)

    accessed = []
    for r in probe_flushes:
        if r.flush_hit:
            status = f"SLOW flush (hit) → victim accessed this line"
            accessed.append(r.address)
        else:
            status = f"FAST flush (miss) → victim did not access"

        logger.info(
            f"Probe flush @ {r.address}: {r.time} cycles → {status}"
        )  # If short time: memory has been accessed and thus data is still in cache

    logger.info(f"\nLines likely accessed by victim: {len(accessed)}")
    for addr in accessed:
        logger.info(f"\t{addr}")


def build_hierarchy(configs, logger, policy):
    # Build the cache hierarchy with the given configuration
    hierarchy = {}
    # Main memory is required
    main_memory = build_cache(configs, "mem", None, logger, policy)
    prev_level = main_memory
    hierarchy["mem"] = main_memory
    if "cache_3" in configs.keys():
        cache_3 = build_cache(configs, "cache_3", prev_level, logger, policy)
        prev_level = cache_3
        hierarchy["cache_3"] = cache_3
    if "cache_2" in configs.keys():
        cache_2 = build_cache(configs, "cache_2", prev_level, logger, policy)
        prev_level = cache_2
        hierarchy["cache_2"] = cache_2
    # Cache_1 is required
    cache_1 = build_cache(configs, "cache_1", prev_level, logger, policy)
    hierarchy["cache_1"] = cache_1
    return hierarchy


def build_cache(
    configs, name, next_level_cache, logger, policy, core_id=None, is_shared=False
):

    return cache.Cache(
        name,
        configs["architecture"]["word_size"],
        configs["architecture"]["block_size"],
        configs[name]["blocks"] if (name != "mem") else -1,
        configs[name]["associativity"] if (name != "mem") else -1,
        configs[name]["hit_time"],
        configs[name]["hit_time"],
        configs["architecture"]["write_back"],
        logger,
        next_level_cache,
        policy,
        core_id,
        is_shared,
    )


def build_multicore_hierarchy(configs, logger, policy, num_cores=2):
    """Build multi-core hierarchy with private L1 caches and shared L2

    Args:
        configs: Configuration dictionary from YAML
        logger: Logger instance
        policy: Eviction policy string
        num_cores: Number of CPU cores (default: 2)

    Returns:
        hierarchy dict containing cores, caches, directory, and bus
    """
    hierarchy = {}

    # Build memory (required)
    main_memory = build_cache(configs, "mem", None, logger, policy)
    hierarchy["mem"] = main_memory
    prev_level = main_memory

    # Build L2 (shared cache - required for multi-core)
    if "cache_2" not in configs.keys():
        raise ValueError("Multi-core mode requires cache_2 (shared L2) in config file")

    cache_2 = build_cache(
        configs, "cache_2", prev_level, logger, policy, core_id=None, is_shared=True
    )
    hierarchy["cache_2"] = cache_2
    prev_level = cache_2

    # Create directory controller
    dir_controller = directory.Directory(logger)
    hierarchy["directory"] = dir_controller

    # Create bus
    system_bus = bus.Bus(dir_controller, prev_level, logger)
    hierarchy["bus"] = system_bus

    # Build cores with private L1 caches
    cores = []
    for i in range(num_cores):
        # Create private L1 cache for this core
        l1_name = f"cache_1_core_{i}"
        l1_cache = build_cache(
            configs, "cache_1", prev_level, logger, policy, core_id=i, is_shared=False
        )

        # Create core
        cpu_core = core.Core(i, l1_cache, system_bus, logger)
        cores.append(cpu_core)

        hierarchy[f"core_{i}"] = cpu_core
        hierarchy[l1_name] = l1_cache

    hierarchy["cores"] = cores
    hierarchy["num_cores"] = num_cores

    return hierarchy


def simulate_multicore(hierarchy, trace, logger, attack_type=None):
    """Simulate multi-core execution with MSI coherence

    Trace format: <core_id> <address> <operation> [ATTACKER|VICTIM]
    Example: 0 00000000 R VICTIM

    Args:
        hierarchy: Multi-core hierarchy dict
        trace: List of trace instructions
        logger: Logger instance
        attack_type: Type of attack to analyze (optional)
    """
    responses = []
    cores = hierarchy["cores"]
    num_cores = hierarchy["num_cores"]

    for current_step in range(len(trace)):
        instruction = trace[current_step]
        parts = instruction.split()

        # Parse multi-core trace format: <core_id> <address> <operation> [ATTACKER|VICTIM]
        if len(parts) == 4:
            core_id_str, address, op, actor = parts
            if actor not in ["ATTACKER", "VICTIM"]:
                raise cache.InvalidOpError("Invalid actor (must be ATTACKER or VICTIM)")
        elif len(parts) == 3:
            core_id_str, address, op = parts
            actor = "UNKNOWN"
        else:
            raise cache.InvalidOpError(
                "Multi-core trace format: <core_id> <address> <operation> [ATTACKER|VICTIM]"
            )

        # Parse core ID
        try:
            core_id = int(core_id_str)
        except ValueError:
            raise cache.InvalidOpError(
                f"Invalid core_id: {core_id_str} (must be integer)"
            )

        if core_id >= num_cores or core_id < 0:
            raise ValueError(
                f"Invalid core_id {core_id}, only {num_cores} cores available (0-{num_cores-1})"
            )

        target_core = cores[core_id]

        # Execute operation on appropriate core
        if op == "R":
            logger.info(
                f"{current_step}:\t[Core {core_id}] [{actor}] Reading {address}"
            )
            r = target_core.read(address, current_step)
            r.actor = actor
            r.address = address
            logger.warning(f"\thit_list: {pprint.pformat(r.hit_list)} time: {r.time}\n")
            responses.append(r)

        elif op == "W":
            logger.info(
                f"{current_step}:\t[Core {core_id}] [{actor}] Writing {address}"
            )
            r = target_core.write(address, current_step)
            r.actor = actor
            r.address = address
            logger.warning(f"\thit_list: {pprint.pformat(r.hit_list)} time: {r.time}\n")
            responses.append(r)

        elif op == "F":
            logger.info(
                f"{current_step}:\t[Core {core_id}] [{actor}] Flushing {address}"
            )
            r = target_core.flush(address, current_step)
            r.actor = actor
            r.address = address
            r.flush_hit = any(
                hit for level, hit in r.hit_list.items() if level != "mem"
            )
            logger.warning(
                f"\thit_list: {pprint.pformat(r.hit_list)}\ttime: {r.time}\tflush_hit: {r.flush_hit}\n"
            )
            responses.append(r)

        elif op == "FA":
            logger.info(f"{current_step}:\t[Core {core_id}] [{actor}] Flushing all")
            r = target_core.flush_all(current_step)
            logger.info("\n")

        else:
            raise cache.InvalidOpError(f"Invalid operation: {op}")

    logger.info("Simulation complete")
    analyze_multicore_results(hierarchy, responses, logger, attack_type)


def analyze_multicore_results(hierarchy, responses, logger, attack_type=None):
    """Analyze multi-core simulation results

    Args:
        hierarchy: Multi-core hierarchy dict
        responses: List of Response objects
        logger: Logger instance
        attack_type: Type of attack to analyze (optional)
    """
    n_instructions = len(responses)
    total_time = sum(r.time for r in responses)

    logger.info(f"\nNumber of instructions: {n_instructions}")
    logger.info(f"\nTotal cycles taken: {total_time}\n")

    # Per-core statistics
    num_cores = hierarchy["num_cores"]
    for i in range(num_cores):
        cache_name = f"core_{i}_L1"
        core_responses = [r for r in responses if cache_name in r.hit_list]

        if core_responses:
            n_access = len(core_responses)
            n_hits = sum(1 for r in core_responses if r.hit_list.get(cache_name, False))
            n_miss = n_access - n_hits
            hit_rate = (n_hits / n_access * 100) if n_access > 0 else 0

            logger.info(f"Core {i} L1:")
            logger.info(f"\tNumber of accesses: {n_access}")
            logger.info(f"\tNumber of hits: {n_hits}")
            logger.info(f"\tNumber of misses: {n_miss}")
            logger.info(f"\tHit rate: {hit_rate:.2f}%\n")

    # Overall statistics (could add AMAT calculation for shared L2 here)
    logger.info("Note: Multi-core AMAT calculation not yet implemented")

    # Attack analysis — roughly mirrors analyze_results() single-core logic
    attacker_responses = [r for r in responses if r.actor == "ATTACKER"]
    victim_responses = [r for r in responses if r.actor == "VICTIM"]

    if attacker_responses and victim_responses:
        if attack_type == "prime_probe":
            logger.info("\n=== Prime & Probe Analysis (Multi-Core) ===")
            analyze_prime_probe(
                hierarchy.get("cache_1_core_0"), attacker_responses, logger
            )
        elif attack_type == "flush_reload":
            logger.info("\n=== Flush & Reload Analysis (Multi-Core) ===")
            analyze_flush_reload(hierarchy, responses, logger)
        elif attack_type == "flush_flush":
            logger.info("\n=== Flush & Flush Analysis (Multi-Core) ===")
            analyze_flush_flush(responses, logger)
        else:
            logger.info(
                "\nNo attack type specified, skipping attack analysis. Use -a or --attack-type to specify an attack type for analysis."
            )
    elif attack_type:
        logger.info(
            "\nAttack type specified but no VICTIM accesses found in trace — skipping analysis."
        )
        logger.info(
            "Add victim accesses to the VICTIM PHASE section of your trace file."
        )
    elif attacker_responses and not victim_responses and not attack_type:
        logger.info(
            "\nAttacker accesses detected but no VICTIM accesses found in trace."
        )


if __name__ == "__main__":
    main()
