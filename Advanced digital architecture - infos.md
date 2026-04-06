# Requirements
 You will reuse the cache simulator you used during the labs of ELEC-H473 and adapt it. The objectives are multiple:

1. You will need to implement some kind of flush instruction in the simulator to use in the trace workload
2. You will need to implement new replacements policies i.e. NRU, random & FIFO
3. The attack that you will implement for the labs will be:
	A. Flush & Flush
    B . Flush & Reload
    C. Prime & Probe
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
 - [ ] Last in first out (LIFO)
 - [ ] First in last out (FILO)
 - [ ] Not recently used (NRU)

As of now, the simulator uses **LRU**
### 3. Attack to implement
- A. Flush & Flush
- B. Flush & Reload
- C. Prime & Probe
#### Prime & Probe
How it works:
- Priming phase: The attacker occupies all cache sets with attacker data.
- Probe phase: The attacker measures access time to figure out which set of data was accessed by the victim.
##### Flush & Reload
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

Only relies on the **execution time of the flush instruction**, that depends on whether the data is cached or not
- If no data cached, flush is fast → abort early in case of miss
- If there’s data, slight delay (*in theory, needs to be 2x tested on Cache Simulator*) → in case of a hit, must trigger eviction on all local caches

Doesn’t have a reload step → no cache misse (compared to other 2 techniques) thus lower impact and evades detection mechanisms

Infos gained: 
- Temporal/spatial awareness of the victim’s execution
- Can be enough to steal keys/track user input/bypass security features

Consist of only 1 phase that goes in an infinite loop

Measures the execution time of the `clflush` instruction → depending on the execution time, the attacker decides whether the memory line has been cached or not

The memory line isn’t loaded into the cache → reveals whether some other processes loaded it

At the same time, clflush evicts the memory line from the cache for the next loop round
of the attack. 