# decision_tree.py
"""
Final decision tree / scoring module.
Works on virtual allocations (v_cpu_alloc in 0..100 units, v_ram_alloc in MB).
Keeps session-store support for wait-times and usage-history (optional).
"""

from collections import Counter

# Virtual PC configuration (same values used across app)
VIRTUAL_RAM_MB = 1024    # 1 GB virtual RAM
VIRTUAL_CPU_UNITS = 100  # virtual CPU units (percent-like scale)

# Weight coefficients (balanced for CPU+RAM)
ALPHA_CPU = 0.35    # CPU impact
BETA_RAM = 0.35     # RAM impact
GAMMA_WAIT = 0.15   # Wait-time impact
DELTA_VIS = 0.10    # Visibility on-screen impact
EPS_HISTORY = 0.05  # User history impact

# Ignore list for noisy/system processes (safe to skip)
IGNORE_LIST = {
    "System Idle Process", "TextInputHost.exe", "svchost.exe",
    "RuntimeBroker.exe", "winlogon.exe", "SearchIndexer.exe",
    "System", "Idle"
}

def safe_name(value, pid):
    """Return a safe string name for a process."""
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
    Compute per-process scores and actions based on virtual allocations.

    Args:
      virtual_df: pandas.DataFrame (or similar) with columns:
                  ['pid','name','v_cpu_alloc','v_ram_alloc']
      visible_windows: optional list of dicts {pid, process_name, title, area}
      session_store: optional dict-like to persist 'wait_times' and 'usage_history' and 'refresh_interval'

    Returns:
      list of dicts sorted by score desc. Each dict contains:
        pid, name, v_cpu_alloc, v_ram_alloc, w_cpu, w_ram, w_wait, w_vis, w_hist,
        score, action, reason, wait_time_sec
    """
    # defensive defaults
    if visible_windows is None:
        visible_windows = []
    if session_store is None:
        session_store = {}

    # prepare visible maps
    vis_by_pid = {v['pid']: v for v in visible_windows if isinstance(v.get('pid', None), int)}
    vis_by_name = {}
    total_screen_area = sum((v.get('area', 0) for v in visible_windows)) if visible_windows else 1
    for v in visible_windows:
        pname = v.get('process_name') or v.get('name') or ""
        vis_by_name.setdefault(pname, []).append(v)

    # ensure session store fields
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
    # iterate rows defensively (works with pandas.DataFrame)
    for _, row in virtual_df.iterrows():
        pid = int(row.get('pid', -1) or -1)
        raw_name = row.get('name', 'unknown')
        name = safe_name(raw_name, pid)
        # skip system noise
        if name in IGNORE_LIST:
            continue

        # read virtual allocations
        try:
            v_cpu = float(row.get('v_cpu_alloc', 0.0) or 0.0)
        except Exception:
            v_cpu = 0.0
        try:
            v_ram = float(row.get('v_ram_alloc', 0.0) or 0.0)
        except Exception:
            v_ram = 0.0

        # normalized CPU/RAM weights (0..1)
        w_cpu = max(0.0, min(1.0, v_cpu / VIRTUAL_CPU_UNITS))
        w_ram = max(0.0, min(1.0, v_ram / VIRTUAL_RAM_MB))

        # visibility weight (if provided)
        vis_area = 0
        if pid in vis_by_pid:
            vis_area = vis_by_pid[pid].get('area', 0)
        elif name in vis_by_name:
            try:
                vis_area = max(v.get('area', 0) for v in vis_by_name[name])
            except Exception:
                vis_area = 0
        w_vis = (vis_area / total_screen_area) if total_screen_area > 0 else 0.0

        # usage history: increment if visible or CPU allocated > threshold
        try:
            if vis_area > 0 or v_cpu > 1.0:
                usage_history[name] += 1
        except Exception:
            usage_history[str(name)] = usage_history.get(str(name), 0) + 1

        w_hist = min(usage_history.get(name, 0) / 50.0, 1.0)

        # wait-time handling (simulate: if v_cpu small -> waiting)
        prev_wait = wait_times.get(pid, 0.0)
        if v_cpu < 5.0:
            prev_wait += refresh_interval
        else:
            prev_wait = max(0.0, prev_wait - refresh_interval)
        wait_times[pid] = prev_wait
        w_wait = min(prev_wait / 120.0, 1.0)

        # combined score
        score = (
            ALPHA_CPU * w_cpu +
            BETA_RAM * w_ram +
            GAMMA_WAIT * w_wait +
            DELTA_VIS * w_vis +
            EPS_HISTORY * w_hist
        )
        score = max(0.0, min(1.0, score))  # clamp

        # decision thresholds
        if score >= 0.75:
            action = "kill"
            reason = "High combined virtual CPU+RAM load / visible / frequent"
        elif score >= 0.45:
            action = "preempt"
            reason = "Moderate virtual load — consider preemption"
        else:
            action = "wait"
            reason = "Low load — keep waiting"

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
            "action": action,
            "reason": reason,
            "wait_time_sec": round(wait_times.get(pid, 0.0), 1)
        })

    # persist session updates back
    session_store['wait_times'] = wait_times
    session_store['usage_history'] = usage_history
    session_store['refresh_interval'] = refresh_interval

    # sort by score descending
    results.sort(key=lambda x: x['score'], reverse=True)
    return results
