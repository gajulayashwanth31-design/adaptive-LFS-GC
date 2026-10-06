# PRD — Workload-Adaptive Online Decision Making for Garbage Collection in a Log-Structured File System

## 1. Document Information

- **Project type:** Operating Systems / Storage Systems research prototype
- **Base project:** Adaptive Segment Cleaning — An Online Learning Approach to Garbage Collection in Log-Structured File Systems
- **Proposed upgraded direction:** Workload-Adaptive Online Decision Making for LFS Garbage Collection
- **Implementation target:** User-space Log-Structured File System using FUSE/fusepy
- **Primary learning approach:** Lightweight online learning / contextual decision-making
- **Baseline policies:** FIFO and Greedy
- **Primary objective:** Learn workload-dependent garbage-collection decisions while preserving deterministic filesystem safety

---

## 2. Executive Summary

This project develops a self-adaptive garbage-collection policy for a Log-Structured File System (LFS).

The original prototype uses an online Logistic Regression model to rank candidate segments for cleaning. The upgraded system extends this idea beyond simple victim prediction. It observes workload behavior, detects workload changes, estimates the expected utility of possible cleaning actions, balances exploitation with controlled exploration, and falls back to deterministic policies when the learning component is uncertain or unsafe.

The project does **not** claim that machine-learning-based garbage collection is itself new. Adaptive and learning-based garbage collection already have prior art. The intended contribution is the design and experimental study of a lightweight, online, workload-adaptive decision-making pipeline for an educational/user-space LFS, with explicit attention to workload phase changes, adaptation speed, exploration, overhead, explainability, and safety.

The central research question is:

> **Can a lightweight online decision-making policy learn which garbage-collection actions are beneficial under changing workloads, while adapting quickly and maintaining deterministic safety guarantees?**

---

# 3. Background

## 3.1 Log-Structured File System

An LFS writes new and updated data sequentially into a log rather than repeatedly overwriting blocks in place.

When data is updated:

1. The new version is appended.
2. The old version becomes invalid.
3. Over time, segments contain a mixture of valid and invalid blocks.
4. Garbage collection identifies segments containing reclaimable space.
5. Live blocks are copied elsewhere.
6. The cleaned segment is reclaimed and reused.

The efficiency of this process depends heavily on victim-segment selection.

## 3.2 Problem in Conventional Garbage Collection

Two simple policies are used as baselines:

### FIFO

Select the oldest eligible segment.

Advantages:
- Extremely simple.
- Very low decision overhead.
- Deterministic.

Disadvantages:
- Does not directly consider how much space can be reclaimed.
- Does not learn from previous cleaning outcomes.
- May perform poorly under workload changes.

### Greedy

Select the segment with the lowest valid-data ratio.

Advantages:
- Naturally favors segments with more invalid data.
- Usually has good reclaim potential.

Disadvantages:
- Does not explicitly account for segment age, future invalidation, cleaning cost, or workload phase.
- Does not learn from historical outcomes.

## 3.3 Existing Base Prototype

The original project proposes:

- A user-space LFS.
- FUSE/fusepy integration.
- Segment metadata tracking.
- Workload generation.
- Online Logistic Regression using River.
- Segment feature extraction.
- Comparison against FIFO and Greedy.
- Evaluation using write amplification, reclaimed space, GC overhead, latency, throughput, and prediction quality.

The upgraded PRD retains these foundations and adds a self-adaptive decision layer.

---

# 4. Problem Statement

Traditional LFS garbage collection policies rely primarily on fixed heuristics.

A workload may, however, transition between:

- Sequential writes.
- Random writes.
- Update-heavy behavior.
- Delete-heavy behavior.
- Mixed access.
- Different workload phases over time.

A segment that is an attractive victim under one workload phase may be a poor victim under another.

Therefore, the system should continuously observe workload behavior and use historical cleaning outcomes to adapt its decisions.

The key challenge is not merely predicting whether a segment is "good" or "bad." It is deciding:

1. **Whether garbage collection should happen now.**
2. **Which candidate segment should be cleaned.**
3. **What the expected benefit and cost are.**
4. **How much confidence the model has.**
5. **Whether the workload has changed enough to justify adaptation.**
6. **When to explore an uncertain decision rather than always selecting the current best candidate.**

---

# 5. Project Goals

## 5.1 Primary Goals

1. Build a functioning user-space LFS.
2. Track segment-level validity and access metadata.
3. Monitor workload behavior online.
4. Detect meaningful workload phase changes.
5. Estimate the expected utility of GC actions.
6. Select victim segments adaptively.
7. Optionally learn whether triggering GC now is beneficial.
8. Introduce controlled exploration/exploitation.
9. Provide deterministic safety fallbacks.
10. Compare the adaptive system against FIFO and Greedy.
11. Measure adaptation speed and decision overhead.
12. Evaluate performance under stationary and changing workloads.
13. Produce reproducible experiments and logs.

## 5.2 Secondary Goals

- Explain why a segment was selected.
- Visualize workload phases.
- Visualize model confidence.
- Track cumulative utility.
- Measure regret or decision quality.
- Study cold-start behavior.
- Study model behavior after workload transitions.

---

# 6. Non-Goals

The following are explicitly outside the primary scope:

1. Building a production-grade kernel-space LFS.
2. Claiming a new fundamental garbage-collection algorithm.
3. Claiming that ML-based GC itself is novel.
4. Replacing filesystem correctness mechanisms with ML.
5. Training a large neural network.
6. Requiring GPU hardware.
7. Supporting every production filesystem feature.
8. Proving patentability.
9. Guaranteeing that the learned policy beats every possible heuristic.
10. Building a commercial storage system.

---

# 7. Intended Contribution

The contribution should be framed as a **system combination and experimental study**, not as the invention of ML-based GC.

### Established components

- LFS garbage collection.
- FIFO/Greedy-style victim selection.
- Workload-aware/adaptive GC.
- Learning-based storage optimization.
- Online learning.
- Workload/phase detection.
- Exploration/exploitation.

### Intended project contribution

The project combines these ideas into a lightweight user-space LFS pipeline in which:

```text
Workload
   ↓
Workload Monitor
   ↓
Phase / Drift Detection
   ↓
Online Utility Model
   ↓
GC Trigger Decision
   ↓
Candidate Victim Ranking
   ↓
Exploration / Exploitation
   ↓
Safety Filter
   ↓
Garbage Collection
   ↓
Observed Outcome
   ↓
Online Model Update
```

The experimental focus is on:

- adaptation speed,
- workload phase changes,
- lightweight online learning,
- exploration,
- safety fallback,
- decision overhead,
- and cost-benefit-aware victim selection.

---

# 8. Users and Stakeholders

## 8.1 Primary User

The primary user is the researcher/student operating the LFS prototype and running workloads.

## 8.2 Stakeholders

- OS course instructor.
- Project evaluator.
- Storage-systems researchers.
- Students studying operating systems.
- Students studying online ML.
- Future developers extending the prototype.

---

# 9. High-Level System Architecture

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
                    │ Model               │
                    └──────────┬──────────┘
                               │
                 ┌─────────────┴─────────────┐
                 │                           │
                 ▼                           ▼
       ┌──────────────────┐        ┌──────────────────┐
       │ GC Trigger       │        │ Victim Ranking   │
       │ Decision         │        │ / Utility Model  │
       └────────┬─────────┘        └────────┬─────────┘
                │                           │
                └────────────┬──────────────┘
                             ▼
                  ┌────────────────────────┐
                  │ Exploration /          │
                  │ Exploitation           │
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
                    └─────────┬──────────┘
                              │
                              ▼
                    ┌────────────────────┐
                    │ Online Model       │
                    │ Update             │
                    └────────────────────┘
```

---

# 10. Core Components

## 10.1 FUSE Layer

### Responsibility

Expose the user-space filesystem through standard filesystem operations.

### Example operations

- `create`
- `open`
- `read`
- `write`
- `truncate`
- `unlink`
- `mkdir`
- `readdir`
- `rename`

### Requirement

The ML component must not directly control filesystem correctness.

---

# 11. LFS Core

The LFS core manages:

- Logical files.
- File metadata.
- Physical blocks.
- Segment allocation.
- Append-only writes.
- Valid/invalid block state.
- Segment lifecycle.

### Segment state

Each segment should maintain metadata such as:

```text
segment_id
total_blocks
valid_blocks
invalid_blocks
valid_ratio
invalid_ratio
creation_time
age
last_update_time
update_count
access_count
time_since_last_update
reclaimable_bytes
last_cleaned_time
cleaning_count
historical_cleaning_cost
historical_reclaimed_bytes
```

---

# 12. Segment Manager

## Responsibilities

1. Allocate segments.
2. Track valid blocks.
3. Track invalid blocks.
4. Identify eligible GC candidates.
5. Provide candidate features.
6. Execute segment cleaning.
7. Update metadata after cleaning.

## Candidate Eligibility

A segment may be eligible if:

- It is not currently active.
- It contains valid data that can be relocated.
- It is not reserved for another operation.
- Cleaning it will not violate filesystem correctness.

The eligibility filter must be deterministic.

---

# 13. Workload Monitor

The workload monitor continuously collects short-window statistics.

## Features

Possible workload-level features:

- Reads per second.
- Writes per second.
- Updates per second.
- Deletes per second.
- Sequentiality ratio.
- Random-access ratio.
- Average request size.
- Unique-file ratio.
- Repeated-update ratio.
- Write burstiness.
- Segment invalidation rate.
- GC frequency.
- Recent write amplification.

## Sliding Window

Use a configurable window:

```text
W = recent N operations
```

Example:

```text
Window size = 500 operations
```

The exact value should be configurable for experimentation.

---

# 14. Workload Phase / Drift Detector

## Objective

Detect when the current workload behavior differs materially from recent historical behavior.

The detector should not react to every small fluctuation.

## Possible approaches

### Option A — Statistical Feature Drift

Compare:

```text
Current window statistics
        vs
Reference window statistics
```

Possible distance:

- Euclidean distance after normalization.
- KL divergence for distributions.
- Population Stability Index.
- Mean/variance change.
- Threshold-based feature difference.

### Option B — Simple Change Detector

For the initial implementation, use a lightweight threshold mechanism.

Example:

```text
drift_score =
    weighted_difference(current_features, baseline_features)
```

If:

```text
drift_score > threshold
```

then:

```text
phase_change = TRUE
```

## Requirements

The detector should expose:

```text
phase_id
drift_score
drift_detected
timestamp
```

---

# 15. Online Utility Model

Instead of predicting only:

> "Is this segment useful?"

the upgraded system should estimate:

> "How beneficial is cleaning this segment under the current workload?"

## Candidate Utility

A practical utility formulation is:

```text
Utility =
    ReclaimedBytes
    - λ1 × CopiedBytes
    - λ2 × CleaningLatency
    - λ3 × WriteAmplificationCost
```

For normalized features, another formulation is:

```text
Utility =
    α × ReclaimBenefit
    - β × CopyCost
    - γ × LatencyCost
```

The weights should be configurable.

## Ratio-Based Alternative

A simple cost-benefit formulation:

```text
Utility =
    ReclaimedBytes /
    (CopiedBytes + λ × CleaningLatency)
```

The implementation should choose one primary formulation and keep the alternative for ablation experiments.

---

# 16. Online Learning Model

The original project uses River Online Logistic Regression.

The upgraded system may retain Logistic Regression for the first implementation because it is:

- lightweight,
- interpretable,
- online,
- CPU-friendly,
- easy to update after every decision.

The model should consume:

```text
Segment features
+
Workload features
+
Phase information
```

Example input:

```text
[
  valid_ratio,
  invalid_ratio,
  age,
  update_count,
  access_count,
  time_since_update,
  reclaimable_bytes,
  historical_cleaning_cost,
  workload_write_rate,
  workload_update_rate,
  sequentiality,
  phase_id
]
```

---

# 17. GC Trigger Decision

The upgraded design can allow the learning layer to estimate whether GC should be triggered.

## Inputs

- Free-space percentage.
- Active segment count.
- Number of eligible segments.
- Recent invalidation rate.
- Current workload.
- Recent GC cost.
- Current predicted benefit.

## Trigger score

Conceptually:

```text
TriggerScore =
    ExpectedGCBenefit
    - ExpectedGCCost
```

GC should be triggered if:

```text
TriggerScore > threshold
```

subject to hard safety/resource constraints.

## Important Safety Rule

The model must never be allowed to prevent GC indefinitely if the filesystem requires space reclamation.

Therefore:

```text
if free_space < HARD_LIMIT:
    trigger GC using deterministic policy
```

---

# 18. Victim Ranking

When GC is required:

1. Generate eligible candidates.
2. Extract features.
3. Compute utility/prediction score.
4. Rank candidates.
5. Apply exploration policy.
6. Apply safety constraints.
7. Select victim.

Example:

```text
Candidate A → score 0.81
Candidate B → score 0.73
Candidate C → score 0.58
Candidate D → score 0.46
```

The system normally chooses A during exploitation.

---

# 19. Exploration vs Exploitation

Always selecting the highest-scoring segment can prevent the model from discovering that another candidate is better under a new workload phase.

The system should therefore support controlled exploration.

## Exploration Strategy

A simple initial strategy:

```text
with probability ε:
    explore
else:
    exploit
```

Example:

```text
ε = 0.10
```

During exploration, select a candidate among high-uncertainty or competitive candidates.

## Better Strategy

Use uncertainty-aware exploration:

```text
ExplorationScore =
    PredictedUtility + κ × Uncertainty
```

This encourages the system to test decisions about which it has insufficient knowledge.

## Exploration Constraints

Exploration must never violate:

- filesystem correctness,
- candidate eligibility,
- hard resource limits,
- minimum free-space requirements.

---

# 20. Safety Filter and Fallback

The safety layer separates ML decisions from filesystem correctness.

## Safety checks

Before executing a learned decision:

1. Is the segment eligible?
2. Is the segment currently locked?
3. Is sufficient temporary space available?
4. Is the predicted score valid?
5. Is model confidence above the minimum threshold?
6. Has the segment exceeded a safety constraint?
7. Would cleaning cause an unacceptable immediate resource condition?

## Fallback

If confidence is too low:

```text
Adaptive Policy
      ↓
Low confidence
      ↓
Greedy / FIFO fallback
```

Possible fallback hierarchy:

```text
Adaptive
   ↓ if uncertain
Greedy
   ↓ if unavailable
FIFO
```

The exact hierarchy should be configurable.

---

# 21. Feedback Loop

After every GC action, record the actual outcome.

Example:

```text
Before:
valid_blocks = 20
invalid_blocks = 80

After:
copied_bytes = X
reclaimed_bytes = Y
latency = Z
write_amplification = A
```

Calculate:

```text
observed_utility
```

Then update the online learner.

This produces:

```text
Decision
   ↓
Action
   ↓
Outcome
   ↓
Reward/utility
   ↓
Model update
   ↓
Better future decision
```

---

# 22. Explainability

Every adaptive GC decision should generate a structured explanation.

Example:

```text
GC Decision
------------
Phase: UPDATE_HEAVY
Victim: Segment 17

Predicted utility: 0.82
Confidence: 0.91

Important factors:
- Invalid ratio: high
- Reclaimable bytes: high
- Historical cleaning benefit: high
- Age: moderate

Policy:
EXPLOIT

Fallback:
NOT USED
```

This makes the project easier to demonstrate and evaluate.

---

# 23. Data Model

## Segment Table

```text
segment_id
total_blocks
valid_blocks
invalid_blocks
valid_ratio
age
creation_time
last_update_time
update_count
access_count
reclaimable_bytes
cleaning_count
last_cleaned_time
historical_copy_cost
historical_reclaim
```

## Workload Window

```text
window_id
start_time
end_time
read_rate
write_rate
update_rate
delete_rate
sequentiality
randomness
average_request_size
invalidation_rate
phase_id
drift_score
```

## GC Event

```text
gc_id
timestamp
trigger_reason
victim_segment
policy
prediction_score
confidence
exploration_flag
copied_bytes
reclaimed_bytes
latency
write_amplification
observed_utility
fallback_used
```

## Model Event

```text
timestamp
model_version
phase_id
feature_vector
prediction
target
update_result
```

---

# 24. Functional Requirements

## FR-01: Filesystem Operation

The system shall support basic LFS file operations through FUSE.

## FR-02: Segment Tracking

The system shall track valid and invalid blocks for each segment.

## FR-03: Workload Monitoring

The system shall collect workload statistics online.

## FR-04: Candidate Generation

The system shall generate eligible GC candidates.

## FR-05: Feature Extraction

The system shall calculate segment and workload features.

## FR-06: Online Learning

The system shall update the learning model incrementally.

## FR-07: Workload Drift Detection

The system shall detect significant changes in workload characteristics.

## FR-08: Adaptive Triggering

The system shall estimate whether GC should be triggered, subject to hard safety limits.

## FR-09: Victim Selection

The system shall rank candidate segments.

## FR-10: Exploration

The system shall support configurable exploration.

## FR-11: Safety Filter

The system shall validate learned decisions before execution.

## FR-12: Fallback

The system shall fall back to deterministic policies when required.

## FR-13: Feedback

The system shall record GC outcomes.

## FR-14: Explainability

The system shall expose decision scores and reasons.

## FR-15: Experiment Logging

The system shall save machine-readable experiment results.

---

# 25. Non-Functional Requirements

## Performance

- Model inference should be lightweight.
- GC decision overhead should be measurable.
- Logging should not dominate filesystem execution.

## Reliability

- ML errors must not corrupt filesystem state.
- Deterministic fallback must always be available.

## Reproducibility

- Workloads must support fixed random seeds.
- Configuration must be saved.
- Model parameters must be logged.
- Experiments must be repeatable.

## Interpretability

- Segment decisions should be explainable.
- Feature values should be recorded.

## Modularity

Each subsystem should be independently replaceable.

---

# 26. Workload Generator

The project should include deterministic workload generators.

## Workload A — Sequential

```text
write file1
write file2
write file3
...
```

Expected behavior:

- High sequentiality.
- Relatively predictable invalidation.

## Workload B — Random

Random files/blocks are updated.

## Workload C — Update-Heavy

Frequently modify existing files.

Expected:

- High invalidation rate.
- Many stale blocks.

## Workload D — Delete-Heavy

Create and delete files repeatedly.

## Workload E — Mixed

Combine reads, writes, updates, and deletes.

## Workload F — Phase-Changing

Example:

```text
Phase 1 → Sequential
Phase 2 → Random
Phase 3 → Update-heavy
Phase 4 → Delete-heavy
Phase 5 → Mixed
```

This is the most important workload for demonstrating adaptation.

---

# 27. Evaluation Baselines

At minimum compare:

### Baseline 1 — FIFO

Oldest eligible segment.

### Baseline 2 — Greedy

Lowest valid-data ratio.

### Baseline 3 — Original Online Logistic Regression

The original project's adaptive victim-selection approach.

### Proposed 1 — Drift-Aware Online Model

Online learning + workload monitoring + phase detection.

### Proposed 2 — Drift-Aware + Exploration

Adds controlled exploration.

### Proposed 3 — Full Adaptive System

Includes:

- workload monitoring,
- drift detection,
- adaptive trigger,
- utility-based victim selection,
- exploration,
- safety fallback,
- feedback learning.

---

# 28. Evaluation Metrics

## 28.1 Write Amplification

A central metric.

Conceptually:

```text
Write Amplification =
Total physical bytes written /
Total logical bytes written
```

Lower is generally better.

## 28.2 Reclaimed Space per GC

```text
Reclaimed Space =
space made available after cleaning
```

## 28.3 Cleaning Cost

Measure:

- bytes copied,
- number of valid blocks relocated,
- CPU time,
- elapsed latency.

## 28.4 GC Frequency

Number of GC operations per workload unit.

## 28.5 Cleaning Latency

Measure per-GC latency and distribution.

Report:

- mean,
- median,
- p95,
- p99 where practical.

## 28.6 Throughput

Measure filesystem operations or logical bytes processed per second.

## 28.7 CPU Overhead

Measure additional CPU cost attributable to:

- feature extraction,
- model inference,
- model updates,
- drift detection.

## 28.8 Prediction Quality

If a classification target is retained:

- accuracy,
- precision,
- recall,
- F1,
- calibration where useful.

For utility prediction:

- MAE,
- RMSE,
- correlation between predicted and observed utility.

## 28.9 Adaptation Time

Measure how many operations or GC cycles are required after a workload transition before the adaptive policy stabilizes.

## 28.10 Regret

For a decision-making evaluation:

```text
Regret =
Utility of best available decision
-
Utility achieved by selected decision
```

Track cumulative regret over time.

## 28.11 Fallback Rate

Percentage of decisions that use deterministic fallback.

## 28.12 Exploration Rate

Percentage of decisions selected through exploration.

---

# 29. Key Research Experiment

## Phase-Change Experiment

Run:

```text
0–20k operations    → sequential
20k–40k             → random
40k–60k             → update-heavy
60k–80k             → delete-heavy
80k–100k            → mixed
```

Compare:

```text
FIFO
Greedy
Online LR
Drift-aware LR
Drift-aware + Exploration
```

Measure:

- adaptation time,
- write amplification,
- reclaimed space,
- cleaning latency,
- throughput,
- model overhead,
- regret.

The main question:

> Does the adaptive policy recover faster after workload changes than a policy without explicit phase detection?

---

# 30. Ablation Studies

Ablation is essential for demonstrating which component actually matters.

## Ablation A — No Drift Detector

Compare:

```text
Online model
vs
Drift-aware model
```

Question:

> Does explicit phase detection improve adaptation?

## Ablation B — No Exploration

Compare:

```text
Exploit-only
vs
Explore + exploit
```

Question:

> Does controlled exploration improve long-term decisions?

## Ablation C — No Safety Fallback

Compare:

```text
Adaptive
vs
Adaptive + fallback
```

Measure whether fallback affects robustness.

## Ablation D — No Workload Features

Use only segment features.

Compare with:

```text
Segment + workload features
```

Question:

> Does workload context improve victim selection?

## Ablation E — No Historical Features

Remove:

- previous cleaning benefit,
- historical cost,
- cleaning count.

Question:

> Does historical experience improve decisions?

---

# 31. Cold-Start Experiment

At startup, the model has little or no knowledge.

Evaluate:

```text
First 10% workload
Middle 40%
Final 50%
```

Measure whether performance improves as the model receives feedback.

Expected observation:

```text
Cold start
   ↓
Exploration / learning
   ↓
Improved predictions
   ↓
More stable decisions
```

---

# 32. Model Reset / Concept Drift Experiment

Evaluate whether retaining old knowledge hurts performance after a workload transition.

Compare:

### Strategy A

Never reset model.

### Strategy B

Partial adaptation.

### Strategy C

Reset/reinitialize model after strong drift.

Measure recovery time.

---

# 33. Configuration Parameters

All major parameters should be configurable.

Example:

```yaml
filesystem:
  segment_size: 4096
  blocks_per_segment: 64

workload:
  window_size: 500

gc:
  free_space_threshold: 0.20
  hard_free_space_threshold: 0.05

learning:
  learning_rate: 0.01
  exploration_rate: 0.10
  confidence_threshold: 0.60

drift:
  threshold: 0.30

utility:
  reclaim_weight: 1.0
  copy_cost_weight: 0.5
  latency_weight: 0.2

fallback:
  policy: greedy
```

Values should be treated as experimental configuration rather than fixed truths.

---

# 34. Proposed Software Structure

```text
project/
│
├── src/
│   ├── filesystem/
│   │   ├── fuse_fs.py
│   │   ├── lfs_core.py
│   │   └── metadata.py
│   │
│   ├── storage/
│   │   ├── segment.py
│   │   ├── segment_manager.py
│   │   └── block_manager.py
│   │
│   ├── gc/
│   │   ├── collector.py
│   │   ├── fifo.py
│   │   ├── greedy.py
│   │   ├── adaptive.py
│   │   ├── trigger.py
│   │   └── safety.py
│   │
│   ├── learning/
│   │   ├── online_model.py
│   │   ├── utility.py
│   │   ├── exploration.py
│   │   └── feedback.py
│   │
│   ├── workload/
│   │   ├── monitor.py
│   │   ├── drift.py
│   │   └── generator.py
│   │
│   ├── experiments/
│   │   ├── runner.py
│   │   ├── metrics.py
│   │   └── logger.py
│   │
│   └── config/
│       └── config.yaml
│
├── workloads/
├── results/
├── plots/
├── tests/
├── docs/
└── README.md
```

---

# 35. Decision Algorithm

## High-Level Algorithm

```text
START

Initialize LFS
Initialize segment metadata
Initialize workload monitor
Initialize drift detector
Initialize online model

FOR every filesystem operation:

    Execute filesystem operation

    Update segment metadata

    Update workload statistics

    IF workload window is complete:
        calculate workload features
        calculate drift score

        IF drift detected:
            increment phase ID
            adapt model / exploration parameters if configured

    IF GC is required:

        Generate eligible segments

        Calculate features for every candidate

        Estimate utility for each candidate

        IF adaptive trigger is enabled:
            estimate whether GC should execute

        Rank candidates

        IF exploration condition is satisfied:
            choose exploration candidate
        ELSE:
            choose highest-utility candidate

        Apply safety checks

        IF decision is unsafe OR confidence is low:
            use deterministic fallback

        Execute GC

        Measure:
            copied bytes
            reclaimed bytes
            latency
            write amplification

        Calculate observed utility

        Update online model

        Log decision and outcome

END
```

---

# 36. Safety Invariants

The following rules must never be violated by the ML system:

1. Only eligible segments may be cleaned.
2. Valid blocks must never be lost.
3. File metadata must remain consistent.
4. A segment must not be simultaneously modified by conflicting operations.
5. Hard free-space constraints must override learned trigger decisions.
6. Invalid model output must never directly modify filesystem state.
7. Deterministic fallback must remain available.
8. Every GC action must be logged.

---

# 37. Testing Strategy

## Unit Tests

Test independently:

- Segment validity tracking.
- Invalid-block calculation.
- Candidate generation.
- Utility calculation.
- Drift score.
- Model update.
- Exploration policy.
- Safety filter.
- FIFO.
- Greedy.

## Integration Tests

Test:

```text
write → update → invalidate → GC → reclaim
```

Verify that:

- live data remains readable,
- reclaimed space becomes reusable,
- metadata remains correct.

## Stress Tests

Run:

- many small files,
- large files,
- repeated updates,
- delete-heavy workloads,
- mixed workloads,
- rapid phase transitions.

## Fault Tests

Test:

- invalid model output,
- missing feature,
- model unavailable,
- low confidence,
- insufficient free space,
- corrupted/invalid candidate metadata.

Expected result:

```text
Fallback to safe deterministic behavior.
```

---

# 38. Logging Requirements

Every GC event should log at least:

```text
timestamp
workload_phase
drift_score
trigger_reason
candidate_count
selected_segment
policy
prediction
confidence
exploration
fallback
valid_blocks_before
invalid_blocks_before
copied_bytes
reclaimed_bytes
latency
write_amplification
observed_utility
```

Store results in CSV/JSON for analysis.

---

# 39. Visualization Dashboard

Recommended plots:

## Plot 1

Write amplification vs workload phase.

## Plot 2

Reclaimed space per GC.

## Plot 3

GC latency distribution.

## Plot 4

Throughput over time.

## Plot 5

Drift score over time.

Mark detected phase transitions.

## Plot 6

Predicted utility vs observed utility.

## Plot 7

Exploration vs exploitation decisions.

## Plot 8

Cumulative regret.

## Plot 9

Fallback rate.

## Plot 10

Model performance before and after workload transitions.

---

# 40. Success Criteria

The project is successful if it demonstrates all of the following:

### System

- A functioning user-space LFS exists.
- GC works correctly.
- FIFO and Greedy baselines work.
- Adaptive policy works.

### Learning

- The model updates online.
- Model decisions use current workload context.
- Workload changes can be detected.
- The policy responds to changes.

### Safety

- Filesystem correctness is maintained.
- Unsafe learned decisions trigger fallback.

### Evaluation

- At least five workload classes are tested.
- Phase-changing workload is tested.
- Multiple baselines are compared.
- Ablation experiments are completed.

### Research

The project should answer:

> Does explicit workload adaptation improve GC decision quality under changing workloads, and what overhead does that adaptation introduce?

---

# 41. Expected Results

The project should **not** assume in advance that the adaptive system will always outperform FIFO or Greedy.

Expected hypotheses:

### H1

Adaptive policies will perform better on workloads whose behavior changes over time.

### H2

Workload features will improve decision quality compared with segment-only features.

### H3

Drift detection will reduce adaptation time after workload transitions.

### H4

Controlled exploration can improve long-term utility compared with purely greedy exploitation.

### H5

Safety fallback will reduce the risk of poor decisions during cold-start or high-uncertainty periods.

### H6

The adaptive policy will introduce additional CPU/model overhead compared with FIFO and Greedy.

The experiments must determine whether these hypotheses are actually supported.

---

# 42. Risks and Mitigations

## Risk 1 — ML Does Not Beat Greedy

### Mitigation

Treat this as a valid research result.

Analyze:

- workloads,
- phases,
- model limitations,
- overhead.

The objective is not to force an improvement.

## Risk 2 — Model Learns Too Slowly

### Mitigation

- Tune learning rate.
- Reduce feature dimensionality.
- Increase exploration carefully.
- Use drift-triggered adaptation.

## Risk 3 — Drift Detector Has False Positives

### Mitigation

Use thresholds and minimum persistence before declaring a phase change.

## Risk 4 — Exploration Hurts Performance

### Mitigation

Use a small exploration probability and restrict exploration to safe candidate choices.

## Risk 5 — FUSE Overhead Dominates

### Mitigation

Measure ML overhead separately from total filesystem overhead.

## Risk 6 — Synthetic Workloads Are Unrealistic

### Mitigation

Use multiple workload patterns and clearly report the limitation.

---

# 43. Implementation Phases

## Phase 1 — Base LFS

Deliver:

- FUSE filesystem.
- Append-only log.
- Segment manager.
- Valid/invalid tracking.

## Phase 2 — Baseline GC

Implement:

- FIFO.
- Greedy.

## Phase 3 — Workload Generator

Implement:

- Sequential.
- Random.
- Update-heavy.
- Delete-heavy.
- Mixed.
- Phase-changing.

## Phase 4 — Original Online Model

Implement:

- River online Logistic Regression.
- Segment features.
- Online updates.
- Baseline comparison.

## Phase 5 — Workload Monitor

Implement:

- sliding-window features,
- workload statistics,
- logging.

## Phase 6 — Drift Detector

Implement:

- drift score,
- threshold,
- phase IDs,
- transition logging.

## Phase 7 — Utility-Based Decision Layer

Implement:

- utility function,
- workload-aware features,
- victim ranking.

## Phase 8 — Exploration

Implement:

- epsilon exploration,
- uncertainty-aware option if feasible.

## Phase 9 — Safety Layer

Implement:

- hard constraints,
- confidence threshold,
- fallback policy.

## Phase 10 — Evaluation

Run:

- baseline comparison,
- phase-change tests,
- ablations,
- cold-start tests,
- overhead measurements.

## Phase 11 — Documentation

Produce:

- architecture diagram,
- algorithms,
- result plots,
- limitations,
- prior-art framing,
- reproducibility instructions.

---

# 44. Minimum Viable Product

If implementation time becomes limited, the MVP should include:

1. User-space LFS.
2. Segment metadata.
3. FIFO.
4. Greedy.
5. Online Logistic Regression.
6. Workload monitor.
7. Phase-change workload.
8. Simple drift detector.
9. Utility-based ranking.
10. Safety fallback.
11. Metrics.
12. Comparison plots.

Exploration and learned GC triggering can then be added as extensions.

---

# 45. Recommended Final Version

For the strongest project presentation, the final system should contain:

```text
                SELF-ADAPTIVE LFS GC
                         │
       ┌─────────────────┼─────────────────┐
       │                 │                 │
       ▼                 ▼                 ▼
 Workload Monitor   Segment State     Historical Outcomes
       │                 │                 │
       └─────────────────┼─────────────────┘
                         ▼
                  Drift Detection
                         │
                         ▼
                 Online Utility Model
                         │
               ┌─────────┴─────────┐
               ▼                   ▼
          GC Trigger          Victim Ranking
               │                   │
               └─────────┬─────────┘
                         ▼
                  Explore / Exploit
                         │
                         ▼
                    Safety Filter
                         │
                         ▼
                         GC
                         │
                         ▼
                     Feedback
                         │
                         └──────────→ Model Update
```

---

# 46. Prior-Art Positioning

The project should use careful wording.

## Do Not Say

> "Nobody has used machine learning for garbage collection before."

This is not defensible.

## Say

> "Machine-learning-based and adaptive garbage collection already have prior art. Our project focuses on a lightweight online decision-making framework for a user-space LFS, with explicit workload phase detection, utility-based victim selection, controlled exploration, safety fallback, and evaluation of adaptation speed and overhead."

## If Asked About Novelty

Use:

> "The novelty is not the use of ML for garbage collection itself. The project contribution is the combination and experimental evaluation of workload-aware online decision making, phase-change adaptation, exploration, and safety-constrained victim selection in our lightweight LFS prototype."

---

# 47. Research Questions

### RQ1

Can an online learner improve segment-cleaning decisions compared with FIFO and Greedy?

### RQ2

Does workload context improve victim selection?

### RQ3

Does explicit workload-drift detection improve adaptation after phase changes?

### RQ4

Does exploration improve cumulative cleaning utility?

### RQ5

What is the computational overhead of the adaptive policy?

### RQ6

How does the adaptive policy behave during cold start?

### RQ7

Does a safety fallback improve robustness without significantly reducing performance?

---

# 48. Final Project Statement

> **We propose a workload-adaptive garbage-collection framework for a user-space Log-Structured File System. The system continuously observes segment state and workload behavior, detects workload phase changes, estimates the cost-benefit of candidate cleaning actions using lightweight online learning, balances exploration with exploitation, and applies deterministic safety constraints before executing a learned decision. The system learns from actual GC outcomes and is evaluated against FIFO, Greedy, and simpler online-learning baselines across stationary and phase-changing workloads.**

---

# 49. Future Scope

Possible extensions include:

- Contextual bandits.
- Thompson Sampling.
- Upper Confidence Bound (UCB).
- More advanced online classifiers/regressors.
- Reinforcement learning.
- Learned GC thresholds.
- Multi-objective optimization.
- Workload prediction.
- Model aging.
- Transfer learning between workload classes.
- Real storage traces.
- Kernel-space implementation.
- SSD/ZNS-specific evaluation.
- Multi-tenant storage environments.

These are future extensions rather than requirements for the first implementation.

---

# 50. Final Deliverables

The completed project should produce:

1. Source code.
2. User-space LFS.
3. FIFO GC implementation.
4. Greedy GC implementation.
5. Online learning implementation.
6. Workload monitor.
7. Drift detector.
8. Utility model.
9. Exploration policy.
10. Safety/fallback layer.
11. Workload generator.
12. Experiment runner.
13. CSV/JSON experiment logs.
14. Evaluation plots.
15. Architecture diagram.
16. Technical report.
17. Reproducibility guide.
18. Prior-art discussion.
19. Final presentation/demo.

---

# 51. Definition of Done

The project is considered complete when:

- [ ] LFS mounts and performs basic file operations.
- [ ] Segments and block validity are tracked correctly.
- [ ] FIFO GC works.
- [ ] Greedy GC works.
- [ ] Original online-learning baseline works.
- [ ] Workload features are collected online.
- [ ] Phase changes are detectable.
- [ ] Utility can be calculated.
- [ ] Adaptive victim ranking works.
- [ ] Exploration can be enabled/disabled.
- [ ] Safety fallback works.
- [ ] Every GC action produces a log entry.
- [ ] Phase-changing experiments are reproducible.
- [ ] Baselines and adaptive variants are compared.
- [ ] Ablation studies are completed.
- [ ] Adaptation time is measured.
- [ ] ML/decision overhead is measured.
- [ ] Filesystem correctness is verified.
- [ ] Final results are presented without overstating novelty.

