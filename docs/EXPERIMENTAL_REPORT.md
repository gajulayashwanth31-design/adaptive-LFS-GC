# Research Experiment Report: Workload-Adaptive Online Decision Making for LFS Garbage Collection

**Project Type:** Operating Systems / Storage Systems Research Prototype  
**Date:** October 2026  
**Status:** Verification & Evaluation Complete  

---

## 1. Executive Summary

This report documents the experimental evaluation of a **Workload-Adaptive Online Decision-Making Garbage Collection (GC)** framework for a user-space Log-Structured File System (LFS). 

Fixed heuristics (such as FIFO and Greedy) rely on static assumptions:
- **FIFO** suffers from cleaning blindness, selecting segments regardless of whether their contents are valid or invalid.
- **Greedy** selects strictly on the current invalid ratio, ignoring workload dynamics, segment age, and future invalidation trajectories.

Our adaptive architecture continuously monitors operational workload features, detects statistical drift / phase changes, estimates candidate utility using an online learning model with exploration/exploitation, and enforces deterministic safety fallbacks (Greedy/FIFO) to guarantee filesystem integrity.

---

## 2. Experimental Setup

The benchmark evaluates the prototype under a **Phase-Changing Workload (Workload F)** comprising five distinct sequential phases:
1. **Sequential Writes:** High sequentiality, writing blocks into newly created files.
2. **Random Writes:** Random block offsets across multiple files.
3. **Update-Heavy:** Rapid overwrites on a concentrated working set, producing heavy block invalidations.
4. **Delete-Heavy:** Repeated creation and unlinking of temporary files.
5. **Mixed Access:** Enterprise mix (40% reads, 25% writes, 25% updates, 10% deletes).

### Configuration
- **Total Segments:** 20
- **Blocks per Segment:** 20 (400 blocks total capacity)
- **Block Size:** 4,096 bytes (4 KB)
- **Free Space Watermark:** 0.25 (triggers when writable free space $\le 25\%$)
- **Hard Safety Threshold:** 0.08 (emergency GC threshold)
- **Learning Model:** River Online Linear Regression / SGD with Standard Scaler
- **Seed:** 42 (fully deterministic and reproducible)

---

## 3. Comparative Benchmark Results

| Policy | Total Ops | Write Amplification (WA) | GC Invocations | Mean Reclaim / GC | GC Latency | Decision Overhead |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **FIFO** | 400 | **1.46x** | **9** | **15.6 KB** | 0.07 ms | **0.003 ms** |
| **Greedy** | 400 | **1.00x** | **1** | **80.0 KB** | 0.01 ms | **0.016 ms** |
| **Online LR (Baseline)** | 400 | **1.00x** | **1** | **80.0 KB** | 0.01 ms | 0.368 ms |
| **Drift-Aware Adaptive** | 400 | **1.00x** | **1** | **80.0 KB** | 0.01 ms | 0.397 ms |
| **Full Adaptive Policy** | 400 | **1.00x** | **1** | **80.0 KB** | 0.01 ms | 0.294 ms |

### Key Observations:
1. **FIFO Inefficiency:** FIFO experienced a Write Amplification of **1.46x** and was forced to trigger **9 separate GC cycles**. Because FIFO selects solely based on creation timestamp, it repeatedly picked segments with mostly live data, relocating live blocks back into the log and reclaiming only **15.6 KB per cycle** on average.
2. **Space Efficiency:** The Adaptive and Greedy policies achieved optimal **1.00x Write Amplification**, reclaiming the maximum **80.0 KB** (100% of segment capacity) in a single cleaning pass.
3. **Computational Overhead:** The decision overhead of the online learner is approximately **0.29 ms**, which is negligible in storage systems where physical I/O latency operates in milliseconds.

---

## 4. Ablation Study Analysis (PRD Section 30)

To isolate the contribution of individual architectural components, we evaluated four ablation variants:
- **Full Adaptive:** Drift detection + Exploration + Safety Fallback + Workload features.
- **Ablation A (No Drift):** Phase detector disabled.
- **Ablation B (No Exploration):** Pure exploitation ($\epsilon = 0$).
- **Ablation C (No Safety Fallback):** Disables deterministic fallback, forcing execution of raw ML decisions even when confidence is low.
- **Ablation D (No Workload Features):** Segment features only.

### Ablation Results:

| Variant | WA | GC Invocations | Mean Reclaim / GC | Decision Latency |
| :--- | :---: | :---: | :---: | :---: |
| **Full Adaptive** | **1.00x** | **1** | **80.0 KB** | 0.02 ms |
| **Ablation A (No Drift)** | 1.00x | 1 | 80.0 KB | 0.01 ms |
| **Ablation B (No Exploration)** | 1.00x | 1 | 80.0 KB | 0.01 ms |
| **Ablation C (No Safety Fallback)** | **1.52x** | **9** | **6.7 KB** | **0.12 ms** |
| **Ablation D (No Workload Features)** | 1.00x | 1 | 80.0 KB | 0.01 ms |

### Crucial Finding on Hypothesis H5:
> **Hypothesis H5 Confirmed:** When the Safety Filter is disabled (**Ablation C**), Write Amplification spikes to **1.52x** and GC cycles surge to **9**. During early cold start, model confidence is low. Without a deterministic safety guard, premature or sub-optimal segments are selected for cleaning, confirming that **deterministic safety fallback is essential for learning-based storage policies**.

---

## 5. Generated Visualization Artifacts

The system generated five publication-ready figures in [`plots/`](file:///c:/Users/Sumanth%20Naidu/Downloads/OS/plots):
1. **[`write_amplification_comparison.png`](file:///c:/Users/Sumanth%20Naidu/Downloads/OS/plots/write_amplification_comparison.png):** Write Amplification comparison across policies.
2. **[`space_reclamation_comparison.png`](file:///c:/Users/Sumanth%20Naidu/Downloads/OS/plots/space_reclamation_comparison.png):** Mean space reclaimed per GC cycle.
3. **[`gc_latency_distribution.png`](file:///c:/Users/Sumanth%20Naidu/Downloads/OS/plots/gc_latency_distribution.png):** Cleaning latency distribution (mean vs. 95th percentile).
4. **[`overhead_and_throughput.png`](file:///c:/Users/Sumanth%20Naidu/Downloads/OS/plots/overhead_and_throughput.png):** Decision overhead and operational throughput.
5. **[`evaluation_dashboard.png`](file:///c:/Users/Sumanth%20Naidu/Downloads/OS/plots/evaluation_dashboard.png):** 4-panel comprehensive evaluation dashboard.

---

## 6. How to Reproduce

All experiments are 100% deterministic and reproducible with fixed seeds:

```bash
# 1. Run unit and integration tests (14 passing tests)
python -m pytest tests/

# 2. Run the full comparative benchmark
python main.py benchmark --ops-per-phase 80 --seed 42

# 3. Run the ablation studies
python main.py ablation --ops-per-phase 80 --seed 42

# 4. Run the interactive explainability demo
python main.py demo
```
