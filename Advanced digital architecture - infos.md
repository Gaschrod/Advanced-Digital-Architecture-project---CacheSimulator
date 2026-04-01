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
- Forme des labs
- 