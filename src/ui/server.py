"""
Web UI Server: Professional Real-Time Visual Dashboard for Workload-Adaptive LFS.
Designed following UI/UX Pro Max intelligence (Glassmorphism, High Contrast, Fira Code/Sans, Micro-interactions).
"""

from __future__ import annotations
import os
import time
import random
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.filesystem.lfs_core import LFSCore
from src.storage.segment import SegmentState
from src.workload.monitor import WorkloadMonitor
from src.workload.drift import DriftDetector
from src.gc.collector import GarbageCollector, GCEvent
from src.gc.fifo import FIFOPolicy
from src.gc.greedy import GreedyPolicy
from src.gc.adaptive import AdaptiveGCPolicy
from src.gc.trigger import GCTrigger
from src.config.config_loader import load_config


app = FastAPI(title="LFS Adaptive GC Visual Dashboard")


class UIStateManager:
    """Manages the in-memory state of the interactive LFS demonstration."""

    def __init__(self):
        self.config = load_config()
        self.reset()

    def reset(self):
        self.total_segments = 20
        self.blocks_per_segment = 20
        self.block_size = 4096

        self.lfs = LFSCore(
            total_segments=self.total_segments,
            blocks_per_segment=self.blocks_per_segment,
            block_size=self.block_size,
        )
        self.monitor = WorkloadMonitor(window_size=80)
        self.drift_detector = DriftDetector(threshold=0.25)
        self.trigger = GCTrigger(free_space_threshold=0.25, hard_free_space_threshold=0.08)

        # Policies
        self.adaptive_policy = AdaptiveGCPolicy(
            segment_manager=self.lfs.segment_manager,
            workload_monitor=self.monitor,
            drift_detector=self.drift_detector,
        )
        self.fifo_policy = FIFOPolicy()
        self.greedy_policy = GreedyPolicy()

        self.active_policy_name = "adaptive"  # "adaptive", "greedy", "fifo"

        self.gc = GarbageCollector(
            lfs=self.lfs,
            trigger=self.trigger,
            on_gc_complete_callback=self.adaptive_policy.on_gc_completed,
        )

        # Connect emergency GC callback
        def emergency_gc():
            self.run_gc_cycle(trigger_reason="EMERGENCY_SPACE_PRESSURE")

        self.lfs.segment_manager.gc_callback = emergency_gc

        self.current_phase_name = "SEQUENTIAL"
        self.op_counter = 0
        self.rng = random.Random(42)
        self.last_explanation = None

        # Live history for charts
        self.history_snapshots: List[Dict[str, Any]] = []
        self._record_snapshot()

    def _record_snapshot(self):
        bm = self.lfs.segment_manager.block_manager
        self.history_snapshots.append({
            "timestamp": time.time(),
            "ops": self.op_counter,
            "wa": round(bm.write_amplification, 2),
            "free_ratio": round(self.lfs.segment_manager.free_space_ratio * 100, 1),
            "dirty_ratio": round(self.lfs.segment_manager.dirty_space_ratio * 100, 1),
            "gc_count": self.gc.gc_count,
            "reclaimed_kb": round(self.gc.total_reclaimed_bytes / 1024.0, 1),
            "copied_kb": round(self.gc.total_copied_bytes / 1024.0, 1),
        })
        if len(self.history_snapshots) > 60:
            self.history_snapshots.pop(0)

    def run_workload_batch(self, workload_type: str, count: int = 15) -> Dict[str, Any]:
        """Executes a batch of operations according to workload pattern."""
        self.current_phase_name = workload_type.upper()

        for _ in range(count):
            self.op_counter += 1

            if workload_type == "sequential":
                f_idx = self.op_counter // 4
                path = f"/seq_file_{f_idx}.dat"
                off = (self.op_counter % 4) * self.block_size
                data = self.rng.randbytes(self.block_size)
                self.lfs.write(path, off, data)
                self.monitor.record_op("WRITE", path, off, len(data), 0)

            elif workload_type == "random":
                f_idx = self.rng.randint(0, 10)
                path = f"/rand_file_{f_idx}.dat"
                off = self.rng.randint(0, 6) * self.block_size
                data = self.rng.randbytes(self.block_size)
                self.lfs.write(path, off, data)
                self.monitor.record_op("WRITE", path, off, len(data), 0)

            elif workload_type == "update":
                f_idx = self.rng.randint(0, 3)
                path = f"/hot_file_{f_idx}.dat"
                off = self.rng.randint(0, 3) * self.block_size
                data = self.rng.randbytes(self.block_size)
                self.lfs.write(path, off, data)
                self.monitor.record_op("UPDATE", path, off, len(data), 1)

            elif workload_type == "delete":
                path = f"/temp_file_{self.rng.randint(0, 15)}.dat"
                if self.rng.random() < 0.5:
                    data = self.rng.randbytes(self.block_size)
                    self.lfs.write(path, 0, data)
                    self.monitor.record_op("WRITE", path, 0, len(data), 0)
                else:
                    try:
                        self.lfs.unlink(path)
                        self.monitor.record_op("DELETE", path, 0, 0, 1)
                    except FileNotFoundError:
                        pass

            elif workload_type == "mixed":
                r = self.rng.random()
                path = f"/mix_{self.rng.randint(0, 8)}.dat"
                off = self.rng.randint(0, 4) * self.block_size
                if r < 0.35:
                    try:
                        self.lfs.read(path, off, self.block_size)
                        self.monitor.record_op("READ", path, off, self.block_size, 0)
                    except FileNotFoundError:
                        pass
                elif r < 0.70:
                    data = self.rng.randbytes(self.block_size)
                    self.lfs.write(path, off, data)
                    self.monitor.record_op("WRITE", path, off, len(data), 0)
                elif r < 0.90:
                    data = self.rng.randbytes(self.block_size)
                    self.lfs.write(path, off, data)
                    self.monitor.record_op("UPDATE", path, off, len(data), 1)
                else:
                    try:
                        self.lfs.unlink(path)
                        self.monitor.record_op("DELETE", path, 0, 0, 1)
                    except FileNotFoundError:
                        pass

            # Auto GC trigger check
            should_gc, reason = self.trigger.should_trigger(self.lfs.segment_manager)
            if should_gc:
                self.run_gc_cycle(trigger_reason=reason)

        self._record_snapshot()
        return self.get_state()

    def run_gc_cycle(self, trigger_reason: str = "MANUAL_TRIGGER") -> Optional[Dict[str, Any]]:
        """Runs a single segment cleaning cycle under the selected policy."""
        candidates = self.lfs.segment_manager.get_eligible_candidates()
        if not candidates:
            return None

        victim = None
        event = None

        if self.active_policy_name == "adaptive":
            v, expl, pred_util, is_exp, fb, fb_reason = self.adaptive_policy.select_victim(
                eligible_candidates=candidates,
                current_op_count=self.op_counter,
            )
            victim = v
            self.last_explanation = expl
            event = self.gc.clean_segment(
                victim=victim,
                policy_name="Adaptive-GC",
                trigger_reason=trigger_reason,
                predicted_utility=pred_util,
                confidence=expl.confidence,
                is_exploration=is_exp,
                fallback_used=fb,
                fallback_reason=fb_reason,
                workload_phase=self.current_phase_name,
            )
        elif self.active_policy_name == "greedy":
            victim = self.greedy_policy.select_victim(candidates)
            if victim:
                event = self.gc.clean_segment(
                    victim=victim,
                    policy_name="Greedy",
                    trigger_reason=trigger_reason,
                    workload_phase=self.current_phase_name,
                )
        elif self.active_policy_name == "fifo":
            victim = self.fifo_policy.select_victim(candidates)
            if victim:
                event = self.gc.clean_segment(
                    victim=victim,
                    policy_name="FIFO",
                    trigger_reason=trigger_reason,
                    workload_phase=self.current_phase_name,
                )

        self._record_snapshot()
        return event.to_dict() if event else None

    def get_state(self) -> Dict[str, Any]:
        sm = self.lfs.segment_manager
        bm = sm.block_manager

        segments_data = []
        for sid in range(sm.total_segments):
            seg = sm.segments[sid]
            block_states = []
            for b_idx in range(sm.blocks_per_segment):
                if b_idx in seg.valid_offsets:
                    block_states.append(1)  # valid (emerald)
                elif b_idx in seg.invalid_offsets:
                    block_states.append(2)  # invalid (red)
                else:
                    block_states.append(0)  # free (slate)

            segments_data.append({
                "id": sid,
                "state": seg.state.value,
                "valid": seg.valid_blocks,
                "invalid": seg.invalid_blocks,
                "free": seg.free_blocks,
                "valid_ratio": round(seg.valid_ratio * 100, 1),
                "invalid_ratio": round(seg.invalid_ratio * 100, 1),
                "cleaning_count": seg.cleaning_count,
                "block_states": block_states,
            })

        explanation_data = None
        if self.last_explanation:
            explanation_data = {
                "gc_id": self.last_explanation.gc_id,
                "phase_id": self.last_explanation.phase_id,
                "victim_id": self.last_explanation.selected_segment_id,
                "predicted_utility": round(self.last_explanation.predicted_utility, 3),
                "confidence": round(self.last_explanation.confidence * 100, 1),
                "is_exploration": self.last_explanation.is_exploration,
                "fallback_used": self.last_explanation.fallback_used,
                "fallback_reason": self.last_explanation.fallback_reason,
                "top_factors": self.last_explanation.top_factors,
            }

        return {
            "summary": {
                "total_ops": self.op_counter,
                "current_phase": self.current_phase_name,
                "active_policy": self.active_policy_name.upper(),
                "write_amplification": round(bm.write_amplification, 2),
                "gc_count": self.gc.gc_count,
                "total_reclaimed_kb": round(self.gc.total_reclaimed_bytes / 1024.0, 1),
                "total_copied_kb": round(self.gc.total_copied_bytes / 1024.0, 1),
                "free_space_percent": round(sm.free_space_ratio * 100, 1),
                "dirty_space_percent": round(sm.dirty_space_ratio * 100, 1),
                "free_segments_count": sm.free_segments_count,
            },
            "segments": segments_data,
            "explanation": explanation_data,
            "history": self.history_snapshots,
        }


state_manager = UIStateManager()


class WorkloadRequest(BaseModel):
    workload_type: str
    count: int = 15


class PolicyRequest(BaseModel):
    policy: str


@app.get("/api/state")
def get_state():
    return state_manager.get_state()


@app.post("/api/workload")
def run_workload(req: WorkloadRequest):
    return state_manager.run_workload_batch(req.workload_type, req.count)


@app.post("/api/policy")
def set_policy(req: PolicyRequest):
    p = req.policy.lower()
    if p not in ("adaptive", "greedy", "fifo"):
        raise HTTPException(status_code=400, detail="Invalid policy name")
    state_manager.active_policy_name = p
    return {"status": "ok", "active_policy": p}


@app.post("/api/gc")
def trigger_gc():
    event = state_manager.run_gc_cycle(trigger_reason="MANUAL_UI_TRIGGER")
    return {"status": "ok", "event": event, "state": state_manager.get_state()}


@app.post("/api/reset")
def reset_system():
    state_manager.reset()
    return {"status": "ok", "state": state_manager.get_state()}


@app.get("/", response_class=HTMLResponse)
def index_page():
    return HTML_CONTENT


HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Workload-Adaptive LFS GC — Intelligent Visual Ops Console</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <!-- Google Fonts: Fira Code + Fira Sans according to UI/UX Pro Max guidelines -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --color-background: #0F172A;
      --color-card: #1B2336;
      --color-primary: #1E293B;
      --color-accent: #22C55E;
      --color-destructive: #EF4444;
    }
    body {
      font-family: 'Fira Sans', sans-serif;
      background-color: var(--color-background);
    }
    .font-mono-num {
      font-family: 'Fira Code', monospace;
    }
    .glass-card {
      background: rgba(27, 35, 54, 0.78);
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      border: 1px solid rgba(255, 255, 255, 0.08);
      box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    }
    .block-valid { background-color: #22C55E; }
    .block-invalid { background-color: #EF4444; }
    .block-free { background-color: #334155; }
    .victim-pulse {
      animation: pulseBorder 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite;
      border-color: #EF4444 !important;
    }
    @keyframes pulseBorder {
      0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
      50% { box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }
    }
    .transition-fast {
      transition: all 180ms cubic-bezier(0.4, 0, 0.2, 1);
    }
  </style>
</head>
<body class="text-slate-100 min-h-screen antialiased selection:bg-emerald-500 selection:text-slate-900">
  
  <!-- Top Navigation & System Status -->
  <header class="glass-card sticky top-0 z-50 border-b border-slate-800 px-6 py-3.5 flex flex-wrap justify-between items-center">
    <div class="flex items-center space-x-3.5">
      <div class="h-10 w-10 rounded-xl bg-gradient-to-br from-indigo-500 to-emerald-500 p-0.5 flex items-center justify-center shadow-lg shadow-indigo-500/20">
        <div class="h-full w-full bg-slate-900 rounded-[10px] flex items-center justify-center">
          <svg class="w-5 h-5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2 1.5 3 3.5 3h9c2 0 3.5-1 3.5-3V7M4 7c0-2 1.5-3 3.5-3h9c2 0 3.5 1 3.5 3M4 7h16m-5 4h.01M9 11h.01M9 15h.01m6 0h.01" />
          </svg>
        </div>
      </div>
      <div>
        <div class="flex items-center space-x-2">
          <h1 class="text-base font-bold tracking-tight text-white">LFS Workload-Adaptive GC</h1>
          <span class="px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wide uppercase bg-emerald-950/80 text-emerald-400 border border-emerald-500/40">ONLINE SGD READY</span>
        </div>
        <p class="text-xs text-slate-400 font-normal">Self-Adaptive Online Decision Making & Deterministic Safety Guarantees</p>
      </div>
    </div>

    <!-- Live Telemetry Badges -->
    <div class="flex items-center space-x-3 mt-3 sm:mt-0">
      <div class="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700/80">
        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping" aria-hidden="true"></span>
        <span class="text-xs text-slate-400">Phase:</span>
        <span id="hdr-phase" class="text-xs font-mono-num font-bold text-cyan-400">SEQUENTIAL</span>
      </div>
      <div class="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-indigo-950/60 border border-indigo-500/40">
        <span class="text-xs text-slate-300">Active Policy:</span>
        <span id="hdr-policy" class="text-xs font-mono-num font-bold text-indigo-400">ADAPTIVE</span>
      </div>
      <button onclick="resetSystem()" class="cursor-pointer transition-fast px-3.5 py-1.5 bg-rose-600/90 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold flex items-center space-x-1.5 shadow-md shadow-rose-900/20 focus-visible:ring-2 focus-visible:ring-rose-400">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
        <span>Reset LFS</span>
      </button>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-6 py-6 space-y-6">

    <!-- KPI Metric Cards (UI/UX Pro Max 8dp Grid) -->
    <section class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3.5">
      <div class="glass-card rounded-xl p-3.5 text-center">
        <span class="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Write Amplification</span>
        <p id="stat-wa" class="font-mono-num text-2xl font-bold text-emerald-400 mt-1">1.00x</p>
        <span class="text-[10px] text-slate-500 font-mono-num">Physical / Logical</span>
      </div>
      <div class="glass-card rounded-xl p-3.5 text-center">
        <span class="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Total Operations</span>
        <p id="stat-ops" class="font-mono-num text-2xl font-bold text-slate-100 mt-1">0</p>
        <span class="text-[10px] text-slate-500 font-mono-num">Live Stream Count</span>
      </div>
      <div class="glass-card rounded-xl p-3.5 text-center">
        <span class="text-[11px] font-medium text-slate-400 uppercase tracking-wider">GC Cycles Fired</span>
        <p id="stat-gcs" class="font-mono-num text-2xl font-bold text-amber-400 mt-1">0</p>
        <span class="text-[10px] text-slate-500 font-mono-num">Cleaned Segments</span>
      </div>
      <div class="glass-card rounded-xl p-3.5 text-center">
        <span class="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Free Space</span>
        <p id="stat-free" class="font-mono-num text-2xl font-bold text-cyan-400 mt-1">100%</p>
        <span class="text-[10px] text-slate-500 font-mono-num">Immediately Writable</span>
      </div>
      <div class="glass-card rounded-xl p-3.5 text-center">
        <span class="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Dirty / Invalid</span>
        <p id="stat-dirty" class="font-mono-num text-2xl font-bold text-rose-400 mt-1">0%</p>
        <span class="text-[10px] text-slate-500 font-mono-num">Awaiting GC Reclaim</span>
      </div>
      <div class="glass-card rounded-xl p-3.5 text-center">
        <span class="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Total Reclaimed</span>
        <p id="stat-reclaimed" class="font-mono-num text-2xl font-bold text-indigo-400 mt-1">0.0 KB</p>
        <span class="text-[10px] text-slate-500 font-mono-num">Net Freed Storage</span>
      </div>
    </section>

    <!-- Operational Controls & AI Explainability -->
    <section class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      
      <!-- Workload Generators & GC Actions -->
      <div class="lg:col-span-2 glass-card rounded-2xl p-5 space-y-4">
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <svg class="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            <h2 class="text-xs font-bold uppercase tracking-wider text-slate-300">Simulate Real Storage Workloads</h2>
          </div>
          <span class="text-[11px] text-slate-400">Click to inject operations into the log</span>
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
          <button onclick="triggerWorkload('sequential')" class="cursor-pointer transition-fast p-3 bg-slate-800/90 hover:bg-slate-700/80 rounded-xl border border-slate-700 text-left flex items-start space-x-3 group">
            <div class="p-2 rounded-lg bg-emerald-950/80 text-emerald-400 border border-emerald-500/30 group-hover:scale-105 transition-fast">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 14l-7 7m0 0l-7-7m7 7V3" /></svg>
            </div>
            <div>
              <p class="text-xs font-bold text-slate-200">Sequential Writes</p>
              <p class="text-[10px] text-slate-400 mt-0.5">+15 Sequential Blocks</p>
            </div>
          </button>

          <button onclick="triggerWorkload('random')" class="cursor-pointer transition-fast p-3 bg-slate-800/90 hover:bg-slate-700/80 rounded-xl border border-slate-700 text-left flex items-start space-x-3 group">
            <div class="p-2 rounded-lg bg-cyan-950/80 text-cyan-400 border border-cyan-500/30 group-hover:scale-105 transition-fast">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" /></svg>
            </div>
            <div>
              <p class="text-xs font-bold text-slate-200">Random Writes</p>
              <p class="text-[10px] text-slate-400 mt-0.5">+15 Dispersed Blocks</p>
            </div>
          </button>

          <button onclick="triggerWorkload('update')" class="cursor-pointer transition-fast p-3 bg-slate-800/90 hover:bg-slate-700/80 rounded-xl border border-slate-700 text-left flex items-start space-x-3 group">
            <div class="p-2 rounded-lg bg-amber-950/80 text-amber-400 border border-amber-500/30 group-hover:scale-105 transition-fast">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
            </div>
            <div>
              <p class="text-xs font-bold text-slate-200">Hot Overwrites</p>
              <p class="text-[10px] text-slate-400 mt-0.5">High Invalidation</p>
            </div>
          </button>

          <button onclick="triggerWorkload('delete')" class="cursor-pointer transition-fast p-3 bg-slate-800/90 hover:bg-slate-700/80 rounded-xl border border-slate-700 text-left flex items-start space-x-3 group">
            <div class="p-2 rounded-lg bg-rose-950/80 text-rose-400 border border-rose-500/30 group-hover:scale-105 transition-fast">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
            </div>
            <div>
              <p class="text-xs font-bold text-slate-200">Delete Batch</p>
              <p class="text-[10px] text-slate-400 mt-0.5">Unlink Files & Invalidate</p>
            </div>
          </button>

          <button onclick="triggerWorkload('mixed')" class="cursor-pointer transition-fast p-3 bg-slate-800/90 hover:bg-slate-700/80 rounded-xl border border-slate-700 text-left flex items-start space-x-3 group">
            <div class="p-2 rounded-lg bg-purple-950/80 text-purple-400 border border-purple-500/30 group-hover:scale-105 transition-fast">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>
            </div>
            <div>
              <p class="text-xs font-bold text-slate-200">Mixed Enterprise</p>
              <p class="text-[10px] text-slate-400 mt-0.5">Read/Write/Update Mix</p>
            </div>
          </button>

          <button onclick="triggerGC()" class="cursor-pointer transition-fast p-3 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-500 hover:to-indigo-600 text-white rounded-xl text-left flex items-start space-x-3 shadow-lg shadow-indigo-500/20 group">
            <div class="p-2 rounded-lg bg-white/10 group-hover:scale-105 transition-fast">
              <svg class="w-4 h-4 text-amber-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
            </div>
            <div>
              <p class="text-xs font-bold text-white">Trigger GC Cycle</p>
              <p class="text-[10px] text-indigo-200 mt-0.5">Clean Victim Now</p>
            </div>
          </button>
        </div>

        <!-- Policy Selector Tabs -->
        <div class="pt-3 border-t border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <span class="text-xs font-medium text-slate-400">Garbage Collection Policy:</span>
          <div class="inline-flex rounded-xl p-1 bg-slate-900 border border-slate-700/80" role="group">
            <button id="btn-pol-adaptive" onclick="setPolicy('adaptive')" class="cursor-pointer transition-fast px-4 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 text-white shadow-md">
              Adaptive-GC (Online SGD)
            </button>
            <button id="btn-pol-greedy" onclick="setPolicy('greedy')" class="cursor-pointer transition-fast px-4 py-1.5 text-xs font-semibold rounded-lg text-slate-400 hover:text-slate-200">
              Greedy Baseline
            </button>
            <button id="btn-pol-fifo" onclick="setPolicy('fifo')" class="cursor-pointer transition-fast px-4 py-1.5 text-xs font-semibold rounded-lg text-slate-400 hover:text-slate-200">
              FIFO Baseline
            </button>
          </div>
        </div>
      </div>

      <!-- AI Explainability Console -->
      <div class="glass-card rounded-2xl p-5 flex flex-col justify-between space-y-4">
        <div>
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center space-x-2">
              <svg class="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
              <h2 class="text-xs font-bold uppercase tracking-wider text-slate-300">Online AI Explainability</h2>
            </div>
            <span id="expl-mode" class="px-2 py-0.5 rounded text-[10px] font-bold tracking-wide uppercase bg-emerald-950 text-emerald-400 border border-emerald-600/40">EXPLOIT</span>
          </div>

          <div class="space-y-3">
            <div>
              <div class="flex justify-between items-center text-xs mb-1">
                <span class="text-slate-400">Model Confidence:</span>
                <span id="expl-conf" class="font-mono-num font-bold text-emerald-400">40.0%</span>
              </div>
              <div class="w-full bg-slate-800 h-2 rounded-full overflow-hidden p-0.5 border border-slate-700">
                <div id="expl-conf-bar" class="bg-gradient-to-r from-emerald-500 to-cyan-400 h-full rounded-full transition-fast w-2/5"></div>
              </div>
            </div>

            <div class="grid grid-cols-2 gap-2 text-xs pt-1">
              <div class="bg-slate-900/60 p-2.5 rounded-lg border border-slate-800">
                <span class="text-[11px] text-slate-400 block">Predicted Utility:</span>
                <span id="expl-util" class="font-mono-num font-bold text-indigo-400 text-sm">0.000</span>
              </div>
              <div class="bg-slate-900/60 p-2.5 rounded-lg border border-slate-800">
                <span class="text-[11px] text-slate-400 block">Safety Guard:</span>
                <span id="expl-fallback" class="font-mono-num font-bold text-slate-300 text-xs truncate">None (Safe)</span>
              </div>
            </div>

            <div class="pt-2 border-t border-slate-800/80">
              <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Decision Factors</span>
              <ul id="expl-factors" class="space-y-1 text-xs font-mono-num text-slate-300">
                <li class="flex items-center space-x-2 text-slate-500">
                  <span class="w-1.5 h-1.5 rounded-full bg-slate-600"></span>
                  <span>Awaiting initial GC decision...</span>
                </li>
              </ul>
            </div>
          </div>
        </div>

        <div class="bg-slate-900/80 p-2.5 rounded-xl border border-slate-800 text-[11px] text-slate-400 flex items-center space-x-2">
          <svg class="w-4 h-4 text-emerald-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
          <span>Safety Invariant: Hard free space threshold overrides AI if free &lt; 8%.</span>
        </div>
      </div>
    </section>

    <!-- Visual Disk Map (20 Segments Matrix) -->
    <section class="glass-card rounded-2xl p-5 space-y-4">
      <div class="flex flex-wrap justify-between items-center gap-3">
        <div>
          <div class="flex items-center space-x-2">
            <svg class="w-4 h-4 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" /></svg>
            <h2 class="text-xs font-bold uppercase tracking-wider text-slate-200">Physical Storage Map (20 Segments × 20 Blocks)</h2>
          </div>
          <p class="text-xs text-slate-400 mt-0.5">High-resolution block validity view. Green = Live Data, Red = Dead / Invalid, Dark Gray = Free.</p>
        </div>

        <!-- Legend -->
        <div class="flex items-center space-x-4 text-xs font-medium">
          <span class="flex items-center space-x-1.5"><span class="w-2.5 h-2.5 rounded-sm block-valid inline-block shadow-sm"></span><span class="text-slate-300">Live / Valid</span></span>
          <span class="flex items-center space-x-1.5"><span class="w-2.5 h-2.5 rounded-sm block-invalid inline-block shadow-sm"></span><span class="text-slate-300">Dead / Invalid</span></span>
          <span class="flex items-center space-x-1.5"><span class="w-2.5 h-2.5 rounded-sm block-free inline-block shadow-sm"></span><span class="text-slate-300">Free / Unwritten</span></span>
        </div>
      </div>

      <!-- Segment Grid Matrix -->
      <div id="segments-grid" class="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-5 gap-3 pt-2">
        <!-- Rendered dynamically -->
      </div>
    </section>

    <!-- Real-Time Chart.js Visualizations -->
    <section class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div class="glass-card rounded-2xl p-5 space-y-2">
        <div class="flex justify-between items-center mb-1">
          <h3 class="text-xs font-bold text-slate-300 uppercase tracking-wider">Write Amplification Trend</h3>
          <span class="text-[10px] text-slate-500 font-mono-num">Target: 1.00x</span>
        </div>
        <div class="h-60"><canvas id="waChart"></canvas></div>
      </div>

      <div class="glass-card rounded-2xl p-5 space-y-2">
        <div class="flex justify-between items-center mb-1">
          <h3 class="text-xs font-bold text-slate-300 uppercase tracking-wider">Reclaimed vs. Copied Bytes</h3>
          <span class="text-[10px] text-slate-500 font-mono-num">Units: Kilobytes (KB)</span>
        </div>
        <div class="h-60"><canvas id="reclaimChart"></canvas></div>
      </div>
    </section>

  </main>

  <script>
    let waChartInstance = null;
    let reclaimChartInstance = null;
    let activePolicy = "adaptive";

    async function fetchState() {
      try {
        const res = await fetch("/api/state");
        const data = await res.json();
        updateUI(data);
      } catch (err) {
        console.error("Failed to fetch state:", err);
      }
    }

    function updateUI(data) {
      const s = data.summary;
      document.getElementById("hdr-phase").innerText = s.current_phase;
      document.getElementById("hdr-policy").innerText = s.active_policy;
      document.getElementById("stat-wa").innerText = s.write_amplification + "x";
      document.getElementById("stat-ops").innerText = s.total_ops;
      document.getElementById("stat-gcs").innerText = s.gc_count;
      document.getElementById("stat-free").innerText = s.free_space_percent + "%";
      document.getElementById("stat-dirty").innerText = s.dirty_space_percent + "%";
      document.getElementById("stat-reclaimed").innerText = s.total_reclaimed_kb + " KB";

      // Render Segments Grid
      const grid = document.getElementById("segments-grid");
      grid.innerHTML = "";
      data.segments.forEach(seg => {
        const stateColor = seg.state === "ACTIVE" ? "border-amber-500/80 bg-amber-950/20" :
                           seg.state === "FREE" ? "border-slate-700/60 bg-slate-900/40" :
                           seg.state === "CLEANING" ? "border-rose-500 bg-rose-950/40 victim-pulse" :
                           "border-slate-700/80 bg-slate-800/60";

        let blocksHtml = "";
        seg.block_states.forEach(b => {
          const cls = b === 1 ? "block-valid" : b === 2 ? "block-invalid" : "block-free";
          blocksHtml += `<div class="h-2 w-full rounded-xs ${cls}"></div>`;
        });

        const card = `
          <div class="border ${stateColor} rounded-xl p-3 transition-fast hover:border-slate-500">
            <div class="flex justify-between items-center mb-2">
              <span class="text-xs font-mono-num font-bold text-white">Segment #${seg.id}</span>
              <span class="text-[10px] font-mono-num font-semibold px-2 py-0.5 rounded-full ${seg.state === 'ACTIVE' ? 'bg-amber-900/60 text-amber-300 border border-amber-600/30' : seg.state === 'FREE' ? 'bg-slate-800 text-slate-400' : 'bg-indigo-900/40 text-indigo-300 border border-indigo-600/30'}">${seg.state}</span>
            </div>
            <!-- Block Grid: 20 blocks in 4x5 -->
            <div class="grid grid-cols-5 gap-1 mb-2.5 bg-slate-950/80 p-1.5 rounded-lg border border-slate-800/80">
              ${blocksHtml}
            </div>
            <div class="flex justify-between text-[11px] font-mono-num text-slate-400">
              <span class="text-emerald-400">Live: ${seg.valid}</span>
              <span class="text-rose-400">Dead: ${seg.invalid}</span>
              <span class="text-slate-500">GC: ${seg.cleaning_count}x</span>
            </div>
          </div>
        `;
        grid.innerHTML += card;
      });

      // Update Explanation
      if (data.explanation) {
        const ex = data.explanation;
        document.getElementById("expl-conf").innerText = ex.confidence + "%";
        document.getElementById("expl-conf-bar").style.width = ex.confidence + "%";
        document.getElementById("expl-util").innerText = ex.predicted_utility;
        document.getElementById("expl-mode").innerText = ex.is_exploration ? "EXPLORE (ε)" : "EXPLOIT";
        document.getElementById("expl-mode").className = ex.is_exploration ?
          "px-2 py-0.5 rounded text-[10px] font-bold tracking-wide uppercase bg-amber-950 text-amber-300 border border-amber-600" :
          "px-2 py-0.5 rounded text-[10px] font-bold tracking-wide uppercase bg-emerald-950 text-emerald-400 border border-emerald-600";
        document.getElementById("expl-fallback").innerText = ex.fallback_used ? ex.fallback_reason : "None (Safe)";

        const factorsList = document.getElementById("expl-factors");
        factorsList.innerHTML = "";
        ex.top_factors.forEach(f => {
          factorsList.innerHTML += `
            <li class="flex items-center space-x-2">
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
              <span>${f}</span>
            </li>
          `;
        });
      }

      // Update Charts
      updateCharts(data.history);
    }

    function initCharts() {
      const ctxWA = document.getElementById('waChart').getContext('2d');
      waChartInstance = new Chart(ctxWA, {
        type: 'line',
        data: {
          labels: [],
          datasets: [{
            label: 'Write Amplification',
            data: [],
            borderColor: '#22C55E',
            backgroundColor: 'rgba(34, 197, 94, 0.1)',
            fill: true,
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#64748B', font: { family: 'Fira Code', size: 10 } } },
            y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#64748B', font: { family: 'Fira Code', size: 10 } }, beginAtZero: false, suggestedMin: 1.0 }
          }
        }
      });

      const ctxRec = document.getElementById('reclaimChart').getContext('2d');
      reclaimChartInstance = new Chart(ctxRec, {
        type: 'bar',
        data: {
          labels: [],
          datasets: [
            { label: 'Reclaimed (KB)', data: [], backgroundColor: '#6366F1', borderRadius: 6 },
            { label: 'Copied (KB)', data: [], backgroundColor: '#F59E0B', borderRadius: 6 }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              labels: { color: '#94A3B8', font: { family: 'Fira Sans', size: 11 }, boxWidth: 12 }
            }
          },
          scales: {
            x: { grid: { display: false }, ticks: { color: '#64748B', font: { family: 'Fira Code', size: 10 } } },
            y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#64748B', font: { family: 'Fira Code', size: 10 } }, beginAtZero: true }
          }
        }
      });
    }

    function updateCharts(history) {
      if (!history || history.length === 0) return;
      const labels = history.map(h => 'Op ' + h.ops);
      waChartInstance.data.labels = labels;
      waChartInstance.data.datasets[0].data = history.map(h => h.wa);
      waChartInstance.update();

      reclaimChartInstance.data.labels = labels;
      reclaimChartInstance.data.datasets[0].data = history.map(h => h.reclaimed_kb);
      reclaimChartInstance.data.datasets[1].data = history.map(h => h.copied_kb);
      reclaimChartInstance.update();
    }

    async function triggerWorkload(type) {
      await fetch('/api/workload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workload_type: type, count: 15 })
      });
      fetchState();
    }

    async function triggerGC() {
      await fetch('/api/gc', { method: 'POST' });
      fetchState();
    }

    async function setPolicy(pol) {
      activePolicy = pol;
      await fetch('/api/policy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ policy: pol })
      });

      ['adaptive', 'greedy', 'fifo'].forEach(p => {
        const btn = document.getElementById('btn-pol-' + p);
        if (p === pol) {
          btn.className = "cursor-pointer transition-fast px-4 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 text-white shadow-md";
        } else {
          btn.className = "cursor-pointer transition-fast px-4 py-1.5 text-xs font-semibold rounded-lg text-slate-400 hover:text-slate-200";
        }
      });
      fetchState();
    }

    async function resetSystem() {
      await fetch('/api/reset', { method: 'POST' });
      fetchState();
    }

    window.onload = () => {
      initCharts();
      fetchState();
      setInterval(fetchState, 2000);
    };
  </script>
</body>
</html>
"""
