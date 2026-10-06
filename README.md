# Workload-Adaptive Online Decision Making for LFS Garbage Collection

> **Operating Systems / Storage Systems Research Prototype**  
> Complete PRD Specification: [`PRD.md`](file:///c:/Users/Sumanth%20Naidu/Downloads/OS/PRD.md)

---

## 1. Project Overview & Idea

Log-Structured File Systems (LFS) buffer and write all modifications (data blocks and metadata) sequentially into contiguous chunks called **segments**. When data is modified or deleted, existing blocks are invalidated in place, leaving segments fragmented with a mixture of live (valid) and dead (invalid) data over time.

### The Problem
Traditional garbage collection (GC / segment cleaning) relies on fixed heuristics:
- **FIFO**: Cleans the oldest eligible segment. Simple and low overhead, but blind to reclaimable space and future updates.
- **Greedy**: Cleans the segment with the highest invalid-data ratio. Effective in static workloads, but fails to consider segment age, cleaning latency, write amplification, or future workload invalidation patterns.

Real storage workloads undergo distinct phase changes:
$$\text{Sequential} \longrightarrow \text{Random} \longrightarrow \text{Update-Heavy} \longrightarrow \text{Delete-Heavy} \longrightarrow \text{Mixed}$$

A segment that is an optimal cleaning candidate during one phase might be a terrible choice during another (e.g., cleaning a segment right before its remaining blocks would have been invalidated by upcoming writes).

### The Solution: Workload-Adaptive Decision Making
This project builds an end-to-end user-space LFS with a **lightweight, online decision-making framework** that:
1. **Monitors Workload in Real Time:** Tracks read/write rates, update ratios, sequentiality, and request sizes across a sliding window.
2. **Detects Workload Drift / Phase Shifts:** Uses statistical change detection to flag when workload patterns shift.
3. **Estimates Candidate Utility:** Replaces binary classification with an online cost-benefit utility model:
   $$\text{Utility} = \text{ReclaimedBytes} - \lambda_1 \times \text{CopiedBytes} - \lambda_2 \times \text{CleaningLatency} - \lambda_3 \times \text{WriteAmplificationCost}$$
4. **Balances Exploration & Exploitation:** Applies controlled $\epsilon$-greedy exploration with uncertainty bonuses to discover new optimal segments during workload shifts.
5. **Enforces Deterministic Safety Invariants:** Machine learning **never** directly compromises filesystem integrity. If model confidence is low or free space reaches hard thresholds, the system falls back to deterministic policies (Greedy $\to$ FIFO).
6. **Closes the Feedback Loop:** Immediately records actual reclaimed space, copied bytes, and GC latency after every cleaning cycle to update the model online.

---

## 2. End-to-End System Architecture

```text
                     ┌─────────────────────────┐
                     │      User Workload      │
                     │ write / update / delete │
                     └────────────┬────────────┘
                                  │
                                  ▼
                     ┌─────────────────────────┐
                     │       FUSE Layer        │
                     └────────────┬────────────┘
                                  │
                                  ▼
               ┌─────────────────────────────────────┐
               │            LFS Core                  │
               │ file operations + metadata + log    │
               └───────────────┬─────────────────────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
                ▼                             ▼
       ┌─────────────────┐          ┌──────────────────┐
       │ Segment Manager │          │ Workload Monitor  │
       └────────┬────────┘          └────────┬─────────┘
                │                            │
                │                            ▼
                │                   ┌─────────────────┐
                │                   │ Drift Detector  │
                │                   └────────┬────────┘
                │                            │
                └──────────────┬─────────────┘
                               ▼
                     ┌─────────────────────┐
                     │ Online Decision     │
                     │ Model (Utility)     │
                     └──────────┬──────────┘
                                │
                  ┌─────────────┴─────────────┐
                  │                           │
                  ▼                           ▼
        ┌──────────────────┐        ┌──────────────────┐
        │ GC Trigger       │        │ Candidate Victim │
        │ Decision         │        │ Ranking          │
        └────────┬─────────┘        └────────┬─────────┘
                 │                           │
                 └────────────┬──────────────┘
                              ▼
                   ┌────────────────────────┐
                   │ Exploration /          │
                   │ Exploitation (ε-Greedy)│
                   └───────────┬────────────┘
                               ▼
                     ┌────────────────────┐
                     │ Safety Filter      │
                     │ + Fallback Policy  │
                     └─────────┬──────────┘
                               ▼
                     ┌────────────────────┐
                     │ Garbage Collector  │
                     └─────────┬──────────┘
                               │
                               ▼
                     ┌────────────────────┐
                     │ Outcome Recorder   │
                     │ & Feedback Loop    │
                     └─────────┬──────────┘
                               │
                               ▼
                     ┌────────────────────┐
                     │ Online Model       │
                     │ Update (SGD/River) │
                     └────────────────────┘
```

---

## 3. Evaluation & Research Questions

### Baselines for Comparison
1. **FIFO**: Oldest eligible segment.
2. **Greedy**: Lowest valid-data ratio.
3. **Static Online Logistic Regression**: Previous baseline (binary classifier without phase/utility modeling).
4. **Drift-Aware Online Model**: Incorporates phase detection and context.
5. **Full Adaptive Policy**: Drift awareness + online utility estimation + exploration + safety fallbacks.

### Primary Metrics
- **Write Amplification (WA):** $\frac{\text{Total Physical Bytes Written}}{\text{Total Logical Bytes Written}}$ (lower is better).
- **Space Reclaimed per GC:** Reclaimed bytes made reusable.
- **Cleaning Cost & Latency:** Valid bytes relocated, elapsed time per GC cycle.
- **Adaptation Time:** Number of operations / GC cycles required to recover efficiency after a workload phase transition.
- **Cumulative Regret:** Difference between optimal candidate utility and chosen candidate utility.
- **Decision Overhead:** Milliseconds spent on feature extraction and inference.
- **Fallback Rate:** Percentage of decisions falling back to deterministic safety mechanisms.

### Key Hypotheses
- **H1:** Adaptive policies outperform FIFO and Greedy under changing workload phases.
- **H2:** Workload context features improve victim selection over segment-only features.
- **H3:** Explicit drift detection significantly reduces adaptation time across phase boundaries.
- **H4:** Controlled exploration avoids local optima without unacceptable performance degradation.
- **H5:** Deterministic safety fallback eliminates catastrophic decisions during cold-start and uncertain states.

---

## 4. Planned Project Structure

```text
OS/
├── PRD.md                         # Full Product Requirement Document
├── README.md                      # Project Idea, Architecture, and Specification
├── docs/                          # Detailed design documents & architecture specs
│
├── src/
│   ├── filesystem/
│   │   ├── fuse_fs.py             # User-space FUSE interface / mount adapter
│   │   ├── lfs_core.py            # Logical inode/file mapping, append log, block index
│   │   └── metadata.py            # File metadata & directory hierarchies
│   │
│   ├── storage/
│   │   ├── segment.py             # Segment metadata, valid/invalid block tracking
│   │   ├── segment_manager.py     # Allocation, segment lifecycle, candidate filters
│   │   └── block_manager.py       # Block allocation, read/write/invalidation mechanics
│   │
│   ├── gc/
│   │   ├── collector.py           # GC coordinator (cleaning, relocating, freeing)
│   │   ├── fifo.py                # FIFO baseline cleaner
│   │   ├── greedy.py              # Greedy baseline cleaner
│   │   ├── adaptive.py            # Workload-adaptive cleaner
│   │   ├── trigger.py             # Space-threshold and learned GC triggering
│   │   └── safety.py              # Safety invariants & deterministic fallback
│   │
│   ├── learning/
│   │   ├── online_model.py        # Online learner (linear utility / SGD / River)
│   │   ├── utility.py             # Multi-factor utility formulation
│   │   ├── exploration.py         # ε-greedy and uncertainty-aware selection
│   │   └── feedback.py            # Feedback loop and reward calculation
│   │
│   ├── workload/
│   │   ├── monitor.py             # Sliding-window workload metrics
│   │   ├── drift.py               # Statistical drift detector & phase tracking
│   │   └── generator.py           # Workload generators (A: Seq, B: Rand, C: Update, D: Del, E: Mixed, F: Phase)
│   │
│   ├── experiments/
│   │   ├── runner.py              # Automated benchmark and experiment runner
│   │   ├── metrics.py             # Metrics aggregator (WA, latency, throughput, regret)
│   │   └── logger.py              # Structured JSON/CSV event logger
│   │
│   └── config/
│       └── config.yaml            # Hyperparameters, segment size, thresholds
│
├── workloads/                     # Workload traces and generator configurations
├── results/                       # Raw experiment logs and benchmarks
├── plots/                         # Graphs (WA, latency distributions, drift, regret)
└── tests/                         # Unit tests, integration tests, and safety invariant tests
```
