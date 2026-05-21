# Requirements
 You will reuse the cache simulator you used during the labs of ELEC-H473 and adapt it. The objectives are multiple:

1. You will need to implement some kind of flush instruction in the simulator to use in the trace workload
2. You will need to implement new replacements policies i.e. NRU, random & FIFO
3. The attack that you will implement for the labs will be:
	A. Prime & Probe
    B . Flush & Reload
    C. Flush & Flush
4. Implement a multi-core version of the cache simulator (private L1 cache per core) which requires cache coherence and consistency 
	A. We recommend you to use directory-based cache coherence protocol with Modified Shared Invalid (MSI) states
5. Finally, some kind of graphical user interface to help the students handle the simulator easily

To help you with some documentations, here are some papers that you may find interesting:
- Daniel Gruss – Microarchitectural Incontinence - You would leak too if you were so fast! https://www.youtube.com/watch?v=cAWmNp3Ukqk 
- Flush+Reload (Yarom) - https://www.youtube.com/watch?v=JwSHvPvmBOw 
- Last-Level Cache Side-Channel Attacks are Practical https://www.youtube.com/watch?v=vpGI1ggKzC4 
- Cache Replacement - Georgia Tech HPCA Part 3 https://www.youtube.com/watch?v=NFp0U8jGTn0 
# Preliminary research/infos
[Github project for cache simulator](https://github.com/auxiliary/CacheSimulator) → the version on UV has been adapted to Python 3.X

Commands to do before anything:
```bash
python3 -m venv .h473_venv
source .h473_venv/bin/activate
pip install pyyaml
pip install terminaltables
```
#### Cache Replacement - Georgia Tech HPCA Part 3 - NOTES
LRU = really good policy (Least-Recently-Used)
NMRU: Not MRU

## Questions to asks/clarification needed
- Forme des labs/du rendu final (en dehors du code → on doit faire de la doc pour suivre des labs ?)
## Steps research
### 0. How does the simulator works/what does it do?
Cf. file “docs/cache_simulator_report” for whole docs but basically:
1. Takes a configuration file + trace file
2. Generates a memory hierarchy based on the configurations and runs the instructions from the trace file

The cache hierarchy is configurable using YAML (L2 and L3 are optional)
##### Diagrams
1.Read diagram
![[Pasted image 20260401143129.png|250]]  
2.Write diagram
![[Pasted image 20260401143539.png|300]]
### 1. Flush instruction in the simulator
Need to add new operation letter (`F`) in traces maybe also another variant for full flush of the cache (`FA`)

Flush needs to:
- Find the block in cache
- Write it back to memory (even if lower levels are clean, the goal is always to push into memory)
- Remote from the level in the cache

**NB: will need to comment/document code and functions and cleanup useless comments**

>[!QUESTION] Forced flush or only for dirty blocks?
>As of now, the flush instruction flush everything from cache onto memory
>
>Is this OK or should only dirty bits be flushed to lower level? From read litterature, the better option seems to flush everything (as it isn’t a case of writing over an already occupied block)
>
>1. Write-back: a flush must:
>	- Write dirty blocks all the way down to memory
>	- Invalidate the block from **all levels** (dirty or clean)
>2. Write-through: a flush only needs to:
>	- Invalidate the block from cache levels
>	- No write-back needed ever

Example of scenario to:
1. Populate levels of cache
2. Dirty higher level (L1)
3. Flush to L2 (now L2 dirty)
4. Flush L2 so that the ‘new’ data sits in L3
5. Try a read which will have to look into L3
```
# Step 1: Load X into all levels
000000A0 R       # miss in L1, L2, L3 → data pulled from memory
                 # result: X in L1, L2, L3

# Step 2: Dirty it in L1
000000A0 W       # write-back mode → marks X dirty in L1 only
                 # result: X dirty in L1, clean in L2, L3

# Step 3: Flush X from L1
000000A0 F       # dirty → writes down to L2 (L2 now has updated data)
                 # invalidates X from L1
                 # result: X gone from L1, dirty in L2, stale in L3

# Step 4: Flush X from L2
000000A0 F       # dirty → writes down to L3 (L3 now has updated data)
                 # invalidates X from L2
                 # result: X gone from L1, gone from L2, updated in L3

# Step 5: Read X again → should miss L1 and L2, hit L3
000000A0 R       # verifies data survived in L3!
```
### 2. New replacement policies
“Best” config to test (smaller thus less ‘space’ to test):
```
architecture:
  word_size: 4
  block_size: 16    # 4-bit offset → addresses 0x40 apart = different blocks, same set
  write_back: true

cache_1:
  blocks: 4
  associativity: 2  # 2-way → 2 sets, easy to reason about
  hit_time: 1

mem:
  hit_time: 1000    # large gap makes hits/misses obvious in timing
```

Example of ways to check correct implementation of LRU:
```
00000000 R    # load A  last=0
00000040 R    # load B  last=1  (full)
00000000 R    # hit  A  last=2, B is LRU
00000080 R    # miss C, evict B(LRU)  → set: {A(last=2), C(last=3)}
00000000 R    # hit  A  last=4, C is LRU  ← re-access A to make it MRU again
00000040 R    # miss B, evict C(LRU)  → set: {A(last=4), B(last=5)}
00000080 R    # miss C (evicted at step 3)  ← confirms correct eviction order
00000000 R    # hit  A  ← confirms A survived throughout
```

With reads:
```
00000000 R    # load A
00000040 R    # load B  (set full)
00000000 W    # write A → A becomes MRU, B becomes LRU
00000080 R    # should evict B not A
00000000 R    # A still in cache → hit
00000040 R    # B was evicted → miss
```

With trashing (trying to read 3 blocks one after the other with only 2 sets):
```
# With 2-way cache, cycling 3 blocks in same set → 100% miss rate
00000000 R    # miss
00000040 R    # miss
00000080 R    # miss, evicts A
00000000 R    # miss, evicts B  ← LRU would always evict the needed block
00000040 R    # miss, evicts C
00000080 R    # miss, evicts A
00000000 R    # miss → 100% miss rate confirms LRU thrashing behavior
```

 Examples: 
 - [x] Random replacement (RR) 
	- Tested and validated
 - [x] First in first out (FIFO)
	- Tested and validated
 - [x] LRU
	 - OK
 - [x] Most Recently Used (MRU)
	- Remove most recently used block (inverse of LRU)
 - [x] Least frequently used (LFU)

<u>Optional:</u>
 - [x] Last in first out (LIFO)
 - [x] First in last out (FILO) -> removed because same thing as LIFO
 - [x] Not recently used (NRU)

As of now, the simulator uses **LRU**
### 3. Attack to implement
- A. Prime & Probe
- B. Flush & Reload
- C. Flush & Flush
#### Prime & Probe
How it works:
- Priming phase: The attacker occupies all cache sets with attacker data.
- Probe phase: The attacker measures access time to figure out which set of data was accessed by the victim.

To better understand the attack: https://security.stackexchange.com/questions/213212/cache-side-channels-prime-probe-attack

<u>Important for the documentation: a VICTIM operation on the exact same block wouldn’t be detected, only an operation on another block of the same set</u>
Reason: even with a write, the block is only marked as “dirty” but this isn’t taken into account by the attacker thus he won’t see a difference if the data is different but the block is the same

**Important note regarding attack limitations:** when a config a more than an associativity of 1 (e.g. associativity of 2), depending on the policy used (e.g. LRU), false positive can happen

Exemple of traces where this can happen:
```
0:      [ATTACKER] Reading 00000000
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

1:      [ATTACKER] Reading 00000080
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

2:      [ATTACKER] Reading 00000010
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

3:      [ATTACKER] Reading 00000090
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

4:      [ATTACKER] Reading 00000020
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

5:      [ATTACKER] Reading 000000A0
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

6:      [ATTACKER] Reading 00000030
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

7:      [ATTACKER] Reading 000000B0
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

8:      [ATTACKER] Reading 00000040
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

9:      [ATTACKER] Reading 000000C0
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

10:     [ATTACKER] Reading 00000050
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

11:     [ATTACKER] Reading 000000D0
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

12:     [ATTACKER] Reading 00000060
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

13:     [ATTACKER] Reading 000000E0
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

14:     [ATTACKER] Reading 00000070
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

15:     [ATTACKER] Reading 000000F0
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

16:     [VICTIM] Reading 00000100
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

17:     [VICTIM] Reading 00000110
        hit_list: {'cache_1': False, 'cache_2': False, 'cache_3': False, 'mem': True}   time: 1117

18:     [VICTIM] Reading 00000111
        hit_list: {'cache_1': True}     time: 1

19:     [VICTIM] Reading 00000110
        hit_list: {'cache_1': True}     time: 1

20:     [VICTIM] Reading 00000111
        hit_list: {'cache_1': True}     time: 1

21:     [ATTACKER] Reading 00000000
        hit_list: {'cache_1': False, 'cache_2': True}   time: 17 
        // Here the probe reads 0x00 which misses because the victim evicted it ✔️
		// But then it fetches from L2 and evicts 0x80 which was the least 
		// recently used
		
22:     [ATTACKER] Reading 00000080
        hit_list: {'cache_1': False, 'cache_2': True}   time: 17 
		// Also a miss because the precedent probe evicted it but **the victim 
		// didn't touch it**
		
23:     [ATTACKER] Reading 00000010
        hit_list: {'cache_1': False, 'cache_2': True}   time: 17

24:     [ATTACKER] Reading 00000090
        hit_list: {'cache_1': False, 'cache_2': True}   time: 17
		// Same thing happens here, the cause being the L1 cache which is 2-ways 
		// associative thus:
		
		┌cache_1┬──────────┬──────────┐
		│       │ Way 0    │ Way 1    │
		├───────┼──────────┼──────────┤
		│ Set 0 │ 00000000 │ 00000080 │
		├───────┼──────────┼──────────┤
		│ Set 1 │ 00000010 │ 00000090 │
		├───────┼──────────┼──────────┤
		
25:     [ATTACKER] Reading 00000020
        hit_list: {'cache_1': True}     time: 1

26:     [ATTACKER] Reading 000000A0
        hit_list: {'cache_1': True}     time: 1

27:     [ATTACKER] Reading 00000030
        hit_list: {'cache_1': True}     time: 1

28:     [ATTACKER] Reading 000000B0
        hit_list: {'cache_1': True}     time: 1

29:     [ATTACKER] Reading 00000040
        hit_list: {'cache_1': True}     time: 1

30:     [ATTACKER] Reading 000000C0
        hit_list: {'cache_1': True}     time: 1

31:     [ATTACKER] Reading 00000050
        hit_list: {'cache_1': True}     time: 1

32:     [ATTACKER] Reading 000000D0
        hit_list: {'cache_1': True}     time: 1

33:     [ATTACKER] Reading 00000060
        hit_list: {'cache_1': True}     time: 1

34:     [ATTACKER] Reading 000000E0
        hit_list: {'cache_1': True}     time: 1

35:     [ATTACKER] Reading 00000070
        hit_list: {'cache_1': True}     time: 1

36:     [ATTACKER] Reading 000000F0
        hit_list: {'cache_1': True}     time: 1

Simulation complete

Number of instructions: 37

Total cycles taken: 20189

cache_3
        Number of accesses: 18
        Number of hits: 0
        Number of misses: 18
cache_2
        Number of accesses: 22
        Number of hits: 4
        Number of misses: 18
cache_1
        Number of accesses: 37
        Number of hits: 15
        Number of misses: 22

AMATs:
{'cache_1': 545.65, 'cache_2': 916.0, 'cache_3': 1100.0, 'mem': 1000}

=== Prime & Probe Analysis ===
Probe results (miss = victim accessed that set):
Probe address: 00000000 -> MISS (victim accessed this set!)
Probe address: 00000080 -> MISS (victim accessed this set!)
Probe address: 00000010 -> MISS (victim accessed this set!)
Probe address: 00000090 -> MISS (victim accessed this set!)
Probe address: 00000020 -> HIT  (set untouched)
Probe address: 000000A0 -> HIT  (set untouched)
Probe address: 00000030 -> HIT  (set untouched)
Probe address: 000000B0 -> HIT  (set untouched)
Probe address: 00000040 -> HIT  (set untouched)
Probe address: 000000C0 -> HIT  (set untouched)
Probe address: 00000050 -> HIT  (set untouched)
Probe address: 000000D0 -> HIT  (set untouched)
Probe address: 00000060 -> HIT  (set untouched)
Probe address: 000000E0 -> HIT  (set untouched)
Probe address: 00000070 -> HIT  (set untouched)
Probe address: 000000F0 -> HIT  (set untouched)

Sets likely accessed by victim: 4
```
#### Flush & Reload
Targets the Last-Level Cache (would be L3 with the “most advanced config” of the simulator). 
Thus, the attacker and the victim don’t need to share the execution core

It’s a cross-core attack → the spy and the victim can execute in parallel on different execution cores

- The attack identifies access to **specific memory lines** 
- It has a high fidelity
- No false positives
- No additional processing for detecting access

Important: it’s a variant of Prime & Probe

A round of attack consists of three phases:
1. The monitored memory line is flushed from the cache hierarchy. 
2. The spy waits to allow the victim time to access the memory line before the third phase. 
3. The spy reloads the memory line, measuring the time to load it. If during the wait phase the victim accesses the memory line, the line will be available in the cache and the reload operation will take a short time. If, on the other hand, the victim has not accessed the memory line, the line will need to be brought from memory and the reload will take significantly longer. 
#### Flush & Flush
Interesting reads:
- [Flush+Flush: A Stealthier Last-Level Cache Attack](https://arxiv.org/pdf/1511.04594v1)

/!\ Is it specific to last level of the cache or not? /!\

Important: as of now, the instruction “Flush” in the simulator **doesn’t have a measured time** (would need to be implemented and take into consideration different timing whether there is data to flush or not → already in memory)

Only relies on the **execution time of the flush instruction**, that depends on whether the data is cached or not
- If no data cached, flush is fast → abort early in case of miss
- If there’s data, slight delay (*in theory, needs to be 2x tested on Cache Simulator*) → in case of a hit, must trigger eviction on all local caches

**For the purpose of the project: flush time is determined to be 2x when there’s data to flush**

Doesn’t have a reload step → no cache misse (compared to other 2 techniques) thus lower impact and evades detection mechanisms

Infos gained: 
- Temporal/spatial awareness of the victim’s execution
- Can be enough to steal keys/track user input/bypass security features

Consist of only 1 phase that goes in an infinite loop

Measures the execution time of the `clflush` instruction → depending on the execution time, the attacker decides whether the memory line has been cached or not

The memory line isn’t loaded into the cache → reveals whether some other processes loaded it

At the same time, clflush evicts the memory line from the cache for the next loop round
of the attack. 