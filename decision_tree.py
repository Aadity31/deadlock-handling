# decision_tree.py
"""
Decision tree scoring for low-end VM simulation.
- VIRTUAL_RAM_MB and VIRTUAL_CPU_UNITS match app defaults (512MB, 50 units)
- explicit deadlock detection + clearer weights
"""

from collections import Counter
import logging

logger = logging.getLogger(__name__)

# Virtual PC configuration for low-end demo
VIRTUAL_RAM_MB = 512    # simulated 512 MB
VIRTUAL_CPU_UNITS = 50  # simulated 50 CPU units

# Weight coefficients tuned to show visible differences on low-end
ALPHA_CPU = 0.50    # emphasize CPU (so high CPU shows up)
BETA_RAM = 0.25
GAMMA_WAIT = 0.15
DELTA_VIS = 0.06
EPS_HISTORY = 0.04

# Ignore list
IGNORE_LIST = {
    "System Idle Process", "TextInputHost.exe", "svchost.exe",
    "RuntimeBroker.exe", "winlogon.exe", "SearchIndexer.exe",
    "System", "Idle"
}

def safe_name(value, pid):
    try:
        if not isinstance(value, str):
            value = str(value)
        name = value.strip()
        if not name:
            name = f"proc_{pid}"
        return name
    except Exception:
        return f"proc_{pid}"

def compute_scores(virtual_df, visible_windows=None, session_store=None):
    """
    Compute per-process scores and actions.
    Returns list sorted by score desc.
    """
    if visible_windows is None:
        visible_windows = []
    if session_store is None:
        session_store = {}

    vis_by_pid = {v['pid']: v for v in visible_windows if isinstance(v.get('pid', None), int)}
    vis_by_name = {}
    total_screen_area = sum((v.get('area', 0) for v in visible_windows)) if visible_windows else 1
    for v in visible_windows:
        pname = v.get('process_name') or v.get('name') or ""
        vis_by_name.setdefault(pname, []).append(v)

    if 'wait_times' not in session_store:
        session_store['wait_times'] = {}
    if 'usage_history' not in session_store:
        session_store['usage_history'] = Counter()
    if 'refresh_interval' not in session_store:
        session_store['refresh_interval'] = 2

    wait_times = session_store['wait_times']
    usage_history = session_store['usage_history']
    refresh_interval = session_store.get('refresh_interval', 2)

    results = []
    for _, row in virtual_df.iterrows():
        try:
            pid = int(row.get('pid', -1) or -1)
        except Exception:
            pid = -1
        raw_name = row.get('name', 'unknown')
        name = safe_name(raw_name, pid)
        if name in IGNORE_LIST:
            continue

        try:
            v_cpu = float(row.get('v_cpu_alloc', 0.0) or 0.0)
        except Exception:
            v_cpu = 0.0
        try:
            v_ram = float(row.get('v_ram_alloc', 0.0) or 0.0)
        except Exception:
            v_ram = 0.0

        w_cpu = max(0.0, min(1.0, v_cpu / VIRTUAL_CPU_UNITS))

        # RAM normalized vs 40% of virtual RAM so it shows visibly on low-end
        ram_normalizer = max(1.0, VIRTUAL_RAM_MB * 0.4)
        w_ram = max(0.0, min(1.0, v_ram / ram_normalizer))

        vis_area = 0
        if pid in vis_by_pid:
            vis_area = vis_by_pid[pid].get('area', 0)
        elif name in vis_by_name:
            try:
                vis_area = max(v.get('area', 0) for v in vis_by_name[name])
            except Exception:
                vis_area = 0
        w_vis = (vis_area / total_screen_area) if total_screen_area > 0 else 0.0

        try:
            if vis_area > 0 or v_cpu > 1.0:
                usage_history[name] += 1
        except Exception:
            usage_history[name] = usage_history.get(name, 0) + 1

        w_hist = min(usage_history.get(name, 0) / 30.0, 1.0)

        prev_wait = wait_times.get(pid, 0.0)
        if v_cpu < (VIRTUAL_CPU_UNITS * 0.06):  # if allocated very small CPU, it's likely waiting
            prev_wait += refresh_interval
        else:
            prev_wait = max(0.0, prev_wait - refresh_interval)
        wait_times[pid] = prev_wait
        w_wait = min(prev_wait / 90.0, 1.0)

        score_raw = (
            ALPHA_CPU * w_cpu +
            BETA_RAM * w_ram +
            GAMMA_WAIT * w_wait +
            DELTA_VIS * w_vis +
            EPS_HISTORY * w_hist
        )
        score = max(0.0, min(1.0, score_raw))

        # Deadlock heuristic (explicit) + tuned thresholds for low-end demo
        action = "wait"
        reason = "Low load — keep waiting"
        if w_wait > 0.75 and w_cpu < 0.02:
            action = "deadlocked"
            reason = "Likely deadlock: waiting long without CPU progress"
        elif score >= 0.60:
            action = "kill"
            reason = "High combined load — terminate to recover"
        elif score >= 0.30:
            action = "preempt"
            reason = "Moderate load — preempt to rebalance"

        results.append({
            "pid": pid,
            "name": name,
            "v_cpu_alloc": round(v_cpu, 2),
            "v_ram_alloc": round(v_ram, 2),
            "w_cpu": round(w_cpu, 3),
            "w_ram": round(w_ram, 3),
            "w_wait": round(w_wait, 3),
            "w_vis": round(w_vis, 3),
            "w_hist": round(w_hist, 3),
            "score": round(score, 3),
            "raw_score": round(score_raw, 4),
            "action": action,
            "reason": reason,
            "wait_time_sec": round(wait_times.get(pid, 0.0), 1)
        })

    session_store['wait_times'] = wait_times
    session_store['usage_history'] = usage_history
    session_store['refresh_interval'] = refresh_interval

    results.sort(key=lambda x: x['score'], reverse=True)
    return results
