#!/usr/bin/env python

import yaml, cache, argparse, logging, pprint
from terminaltables.other_tables import UnixTable

def main():
    #Set up our arguments
    parser = argparse.ArgumentParser(description='Simulate a cache')
    parser.add_argument('-c','--config-file', help='Configuration file for the memory heirarchy', required=True)
    parser.add_argument('-t', '--trace-file', help='Tracefile containing instructions', required=True)
    parser.add_argument('-p', '--policy', choices=['lru', 'mru', 'nru', 'lfu', 'fifo', 'lifo', 'filo', 'random'], help='Eviction policy to use (lru, mru, nru, lfu, fifo, lifo, filo, random)', type=str.lower, required=False, default='lru')
    parser.add_argument('-a', '--attack-type', choices=['prime_probe', 'flush_reload', 'flush_flush'], help='Type of attack to analyze (prime_probe or flush_reload)', type=str.lower, required=False)
    parser.add_argument('-l', '--log-file', help='Log file name', required=False)
    parser.add_argument('-b', '--beautify', help='Use colors', required=False, action='store_true')
    parser.add_argument('-d', '--draw-cache', help='Draw cache layouts', required=False, action='store_true')
    arguments = vars(parser.parse_args())
    
    policy = arguments['policy']
    attack_type = arguments['attack_type']
    
    if arguments['beautify']:
        import colorer

    log_filename = 'cache_simulator.log'
    if arguments['log_file']:
        log_filename = arguments['log_file']

    #Clear the log file if it exists
    with open(log_filename, 'w'):
        pass

    logger = logging.getLogger()
    fh = logging.FileHandler(log_filename)
    sh = logging.StreamHandler()
    logger.addHandler(fh)
    logger.addHandler(sh)

    fh_format = logging.Formatter('%(message)s')
    fh.setFormatter(fh_format)
    sh.setFormatter(fh_format)
    logger.setLevel(logging.INFO)
    
    logger.info('Loading config...')
    config_file = open(arguments['config_file'])
    configs = yaml.safe_load(config_file)
    hierarchy = build_hierarchy(configs, logger, policy)
    logger.info('Memory hierarchy built.')

    logger.info('Loading tracefile...')
    trace_file = open(arguments['trace_file'])
    trace = trace_file.read().splitlines()
    trace = [item for item in trace if item.strip() and not item.startswith('#')]
    logger.info('Loaded tracefile ' + arguments['trace_file'])
    logger.info('Begin simulation!')
    simulate(hierarchy, trace, logger)
    if arguments['draw_cache']:
        for cache in hierarchy:
            if hierarchy[cache].next_level:
                print_cache(hierarchy[cache])

#Print the contents of a cache as a table
#If the table is too long, it will print the first few sets,
#break, and then print the last set
def print_cache(cache):
    table_size = 5
    ways = [""]
    sets = []
    set_indexes = sorted(cache.data.keys())
    if len(cache.data.keys()) > 0:
        first_key = list(cache.data.keys())[0]
        way_no = 0
        
        #Label the columns
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
                temp_way = ['.']
                for w in range(cache.associativity):
                    temp_way.append('')
                sets.append(temp_way)
            
            set_ways = cache.data[set_indexes[len(set_indexes) - 1]].keys()
            temp_way = ['Set ' + str(len(set_indexes) - 1)]
            for w in set_ways:
                temp_way.append(cache.data[set_indexes[len(set_indexes) - 1]][w].address)
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
        print ("\n")
        print (table.table)

# Loop through the instructions in the tracefile and use the given memory hierarchy to find AMAT (Average Memory Access Time)
def simulate(hierarchy, trace, logger):
    responses = []
    # We only interface directly with L1. Reads and writes will automatically interact with lower levels of the hierarchy
    l1 = hierarchy['cache_1']
    for current_step in range(len(trace)):
        instruction = trace[current_step]

        parts = instruction.split()
        if len(parts) == 3:
            address, op, actor = parts # Actor = ATTACKER or VICTIM
            if actor not in ['ATTACKER', 'VICTIM']:
                raise cache.InvalidOpError
        elif len(parts) == 2: # Possible to use cache simulator without attacker/victim roles (base case)
            address, op = parts
            actor = 'UNKNOWN'
        else:
            raise cache.InvalidOpError


        #Call read for this address on our memory hierarchy
        if op == 'R':
            logger.info(str(current_step) + ':\t[' + actor + '] Reading ' + address)
            r = l1.read(address, current_step)
            r.actor = actor
            r.address = address
            logger.warning('\thit_list: ' + pprint.pformat(r.hit_list) + '\ttime: ' + str(r.time) + '\n')
            responses.append(r)
        elif op == 'W':
            logger.info(str(current_step) + ':\t[' + actor + '] Writing ' + address)
            r = l1.write(address, True, current_step)
            r.actor = actor
            r.address = address
            logger.warning('\thit_list: ' + pprint.pformat(r.hit_list) + '\ttime: ' + str(r.time) + '\n')
            responses.append(r)
        elif op == 'F':
            logger.info(str(current_step) + ':\t[' + actor + '] Flushing ' + address)
            r = l1.flush(address, current_step)
            r.actor = actor
            r.address = address
            logger.warning('\thit_list: ' + pprint.pformat(r.hit_list) + '\ttime: ' + str(r.time) + '\tflush_hit: ' + str(r.flush_hit) + '\n')
            responses.append(r)
        elif op == 'FA': # Doesn't care about the address which is a placeholder anyway
            logger.info(str(current_step) + ':\t[' + actor + '] Flushing all')
            r = l1.flush_all(current_step)
            logger.info('\n')
        else:
            raise cache.InvalidOpError
    logger.info('Simulation complete')
    analyze_results(hierarchy, responses, logger, attack_type=attack_type)

def get_llc_name(hierarchy):
    """Trouve dynamiquement le Last Level Cache (LLC) basé sur la config."""
    if 'cache_3' in hierarchy: return 'cache_3'
    if 'cache_2' in hierarchy: return 'cache_2'
    return 'cache_1'

def analyze_results(hierarchy, responses, logger, attack_type=None):
    n_instructions = len(responses)
    total_time = sum(r.time for r in responses)

    logger.info('\nNumber of instructions: ' + str(n_instructions))
    logger.info('\nTotal cycles taken: ' + str(total_time) + '\n')

    # Split by actor
    attacker_responses = [r for r in responses if r.actor == 'ATTACKER']
    victim_responses   = [r for r in responses if r.actor == 'VICTIM']

    # Standard AMAT on all responses
    amat = compute_amat(hierarchy['cache_1'], responses, logger)
    logger.info('\nAMATs:\n' + pprint.pformat(amat))

    # Prime & Probe report — only if both actors are present
    if attacker_responses and victim_responses:
        if attack_type == 'prime_probe':
            logger.info('\n=== Prime & Probe Analysis ===')
            analyze_prime_probe(hierarchy['cache_1'], attacker_responses, logger)
        elif attack_type == 'flush_reload':
            logger.info('\n=== Flush+Reload Analysis ===')
            analyze_flush_reload(hierarchy, responses, logger)
        elif attack_type == 'flush_flush':
            logger.info('\n=== Flush+Flush Analysis ===')
            analyze_flush_reload(hierarchy, responses, logger)
        else:
            logger.info('\nNo attack type specified, skipping attack analysis. Use -a or --attack-type to specify an attack type for analysis.')

def compute_amat(level, responses, logger, results={}):
    #Check if this is main memory
    #Main memory has a non-variable hit time
    if not level.next_level:
        results[level.name] = level.hit_time
    else:
        #Find out how many times this level of cache was accessed
        #And how many of those accesses were misses
        n_miss = 0
        n_access = 0
        for r in responses:
            if level.name in r.hit_list.keys():
                n_access += 1
                if r.hit_list[level.name] == False:
                    n_miss += 1

        if n_access > 0:
            miss_rate = float(n_miss)/n_access
            #Recursively compute the AMAT of this level of cache by computing
            #the AMAT of lower levels
            results[level.name] = round(level.hit_time + miss_rate * compute_amat(level.next_level, responses, logger)[level.next_level.name],2)
        else:
            results[level.name] = round(0 * compute_amat(level.next_level, responses, logger)[level.next_level.name],2)

        logger.info(level.name)
        logger.info('\tNumber of accesses: ' + str(n_access))
        logger.info('\tNumber of hits: ' + str(n_access - n_miss))
        logger.info('\tNumber of misses: ' + str(n_miss))
    return results

def analyze_prime_probe(l1, attacker_responses, logger):
    # The trace template guarantees: first N are prime, last N are probe
    # (N = total attacker accesses / 2)
    mid = len(attacker_responses) // 2
    prime_responses = attacker_responses[:mid]
    probe_responses = attacker_responses[mid:]

    logger.info('Probe results (miss = victim accessed that set):')
    compromised_sets = []

    for prime_r, probe_r in zip(prime_responses, probe_responses):
        # Get the address from the probe response's hit_list context
        # A miss on probe means the victim evicted the attacker's line
        hit_in_l1 = probe_r.hit_list.get('cache_1', False)
        status = 'HIT  (set untouched)' if hit_in_l1 else 'MISS (victim accessed this set!)'
        logger.info('\tProbe address: ' + str(probe_r.address) + ' -> ' + status)
        if not hit_in_l1:
            compromised_sets.append(probe_r)

    logger.info('\nSets likely accessed by victim: ' + str(len(compromised_sets)))

def analyze_flush_reload(hierarchy, responses, logger):
    # Flush+Reload is only meaningful if the attacker and victim share a cache line, so we look for flushes that hit in the victim's accesses
    logger.info('\n=== Flush+Reload Analysis ===')
    
    flush_addresses = {r.address for r in responses if r.actor == 'ATTACKER' and getattr(r, 'flush_hit', None) is not None}
    attacker_reads = [r for r in responses if r.actor == 'ATTACKER' and r.address in flush_addresses and getattr(r, 'flush_hit', None) is not None and r.address in flush_addresses]

    for r in attacker_reads:
        hit_in_llc = llc_name in r.hit_list
        hit_in_any_cache = any(c in r.hit_list for c in hierarchy if c != 'mem')

        if hit_in_llc:
            status = "HIT in LLC -> line shared with victim)"
        elif hit_in_any_cache:
            status = "HIT in upper cache"
        else:
            status = "MISS, likely no access by victim or the victim accessed but the line was evicted before the attacker's read"

        logger.info('\tFlush address: ' + str(r.address) + ' -> ' + status) # If short time: memory has been accessed and thus data is still in cache
        # If not: as the line has been evicted, the data is not in cache anymore and thus we have a miss

def analyze_flush_flush(hierarchy, responses, logger):
    # Flush+Flush is only meaningful if the attacker and victim share a cache line, so we look for flushes that hit in the victim's accesses
    logger.info('\n=== Flush+Flush Analysis ===')
    
    attacker_flushes = [r for r in responses if r.actor == 'ATTACKER' and r.address in flush_addresses and getattr(r, 'flush_hit', None) is not None and r.address in flush_addresses]

    seen = set()
    probe_flushes = []
    for r in attacker_flushes:
        if r.address in seen:
            probe_flushes.append(r)
        else:
            seen.add(r.address)
    
    for r in probe_flushes:
        status = "HIT -> victim accessed the memory line"
        logger.info('\tFlush address: ' + str(r.address) + ' -> ' + status) # If short time: memory has been accessed and thus data is still in cache

def build_hierarchy(configs, logger, policy):
    #Build the cache hierarchy with the given configuration
    hierarchy = {}
    #Main memory is required
    main_memory = build_cache(configs, 'mem', None, logger, policy)
    prev_level = main_memory
    hierarchy['mem'] = main_memory
    if 'cache_3' in configs.keys():
        cache_3 = build_cache(configs, 'cache_3', prev_level, logger, policy)
        prev_level = cache_3
        hierarchy['cache_3'] = cache_3
    if 'cache_2' in configs.keys():
        cache_2 = build_cache(configs, 'cache_2', prev_level, logger, policy)
        prev_level = cache_2
        hierarchy['cache_2'] = cache_2
    #Cache_1 is required
    cache_1 = build_cache(configs, 'cache_1', prev_level, logger, policy)
    hierarchy['cache_1'] = cache_1
    return hierarchy

def build_cache(configs, name, next_level_cache, logger, policy):

    return cache.Cache(name,
                configs['architecture']['word_size'],
                configs['architecture']['block_size'],
                configs[name]['blocks'] if (name != 'mem') else -1,
                configs[name]['associativity'] if (name != 'mem') else -1,
                configs[name]['hit_time'],
                configs[name]['hit_time'],
                configs['architecture']['write_back'],
                logger,
                next_level_cache,
                policy)


if __name__ == '__main__':
    main()
