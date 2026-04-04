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


### 1. New replacement policies
 Examples: 
 - NRU
 - Random
 - FIFO

As of now, the simulator uses **LRU**