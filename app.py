# app.py
import time
import psutil
import pandas as pd
import streamlit as st

from decision_tree import compute_scores, VIRTUAL_RAM_MB, VIRTUAL_CPU_UNITS
from vpc import map_host_to_virtual, get_visible_windows, get_active_window_info

# Try to import st_autorefresh (optional). If not available, fallback to manual refresh button.
try:
    import importlib
    module = importlib.import_module("streamlit_autorefresh")
    st_autorefresh = getattr(module, "st_autorefresh", None)
    AUTorefresh_AVAILABLE = st_autorefresh is not None
except Exception:
    st_autorefresh = None
    AUTorefresh_AVAILABLE = False

# ------------------ CONFIG ------------------
st.set_page_config(page_title="AI Virtual Deadlock Simulator (Final)", layout="wide")
st.title("AI Deadlock Handling — Virtual PC Simulation (1 GB / 100 CPU Units)")

# ------------------ SESSION DEFAULTS ------------------
if 'refresh_interval' not in st.session_state:
    st.session_state['refresh_interval'] = 3
if 'wait_times' not in st.session_state:
    st.session_state['wait_times'] = {}
if 'usage_history' not in st.session_state:
    st.session_state['usage_history'] = {}
if 'log' not in st.session_state:
    st.session_state['log'] = []
if 'killed_history' not in st.session_state:
    st.session_state['killed_history'] = []
if 'last_run' not in st.session_state:
    st.session_state['last_run'] = time.time()

# Sidebar controls
st.sidebar.header("Simulation Controls")
refresh_interval = st.sidebar.slider("Refresh interval (seconds)", 1, 10, st.session_state['refresh_interval'])
st.session_state['refresh_interval'] = refresh_interval

# Manual refresh fallback button
if not AUTorefresh_AVAILABLE:
    if st.sidebar.button("Refresh now"):
        st.session_state['last_run'] = time.time()
        st.experimental_rerun()

# If autorefresh is available, call it so the page refreshes automatically.
if AUTorefresh_AVAILABLE:
    st_autorefresh(interval=refresh_interval * 1000, key="auto_refresh_counter")

# ------------------ MAIN SINGLE-PASS RUN ------------------

# 1) Gather host process snapshot
processes = []
# Seed cpu_percent
for proc in psutil.process_iter(['pid', 'name']):
    try:
        proc.cpu_percent(interval=None)
    except Exception:
        pass

time.sleep(0.01)

for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
    try:
        info = proc.info
        try:
            info["cpu_percent"] = proc.cpu_percent(interval=None)
        except Exception:
            info["cpu_percent"] = info.get("cpu_percent", 0.0) or 0.0
        info["memory_percent"] = round(info.get("memory_percent", 0.0) or 0.0, 3)
        processes.append(info)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        continue

df_host = pd.DataFrame(processes)
if df_host.empty:
    st.warning("No host process data available.")
    st.stop()

visible_windows = get_visible_windows()
active_info = get_active_window_info()

# 2) Map host -> virtual
df_virtual = map_host_to_virtual(df_host, VIRTUAL_RAM_MB, VIRTUAL_CPU_UNITS)

# 3) Inject virtual AI daemon tasks (so simulation has stable tasks to manage)
extra_tasks = [
    {"pid": 9001, "name": "AI_Optimizer", "v_cpu_alloc": 12, "v_ram_alloc": 80},
    {"pid": 9002, "name": "MemoryBalancer", "v_cpu_alloc": 8, "v_ram_alloc": 60},
    {"pid": 9003, "name": "DeadlockResolver", "v_cpu_alloc": 5, "v_ram_alloc": 50},
    {"pid": 9004, "name": "SystemLogger", "v_cpu_alloc": 3, "v_ram_alloc": 40},
    {"pid": 9005, "name": "PredictiveScheduler", "v_cpu_alloc": 10, "v_ram_alloc": 70},
]
if df_virtual is None or df_virtual.empty:
    df_virtual = pd.DataFrame(extra_tasks)
else:
    df_virtual = pd.concat([df_virtual, pd.DataFrame(extra_tasks)], ignore_index=True)

# 4) AI Decision Tree scoring
session_store = {
    'wait_times': st.session_state.get('wait_times', {}),
    'usage_history': st.session_state.get('usage_history', {}),
    'refresh_interval': refresh_interval
}
decisions = compute_scores(df_virtual, visible_windows=visible_windows, session_store=session_store)

# 5) Apply simulated actions and build adjusted virtual allocations
adjusted = []
killed_this_cycle = []
pending_list = []
for proc in decisions:
    v_cpu = proc["v_cpu_alloc"]
    v_ram = proc["v_ram_alloc"]

    if proc["action"] == "preempt":
        v_cpu = round(v_cpu * 0.6, 2)
        v_ram = round(v_ram * 0.6, 2)
        adjusted.append({
            "pid": proc["pid"],
            "name": proc["name"],
            "v_cpu_alloc": v_cpu,
            "v_ram_alloc": v_ram,
            "action": "preempt",
            "reason": proc.get("reason", "")
        })
    elif proc["action"] == "kill":
        killed_this_cycle.append({
            "pid": proc["pid"],
            "name": proc["name"],
            "v_cpu_alloc": proc["v_cpu_alloc"],
            "v_ram_alloc": proc["v_ram_alloc"],
            "score": proc["score"],
            "reason": proc.get("reason", "")
        })
        st.session_state['killed_history'].append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pid": proc["pid"],
            "name": proc["name"],
            "v_cpu_alloc": proc["v_cpu_alloc"],
            "v_ram_alloc": proc["v_ram_alloc"],
            "score": proc["score"],
            "reason": proc.get("reason", "")
        })
    else:
        adjusted.append({
            "pid": proc["pid"],
            "name": proc["name"],
            "v_cpu_alloc": proc["v_cpu_alloc"],
            "v_ram_alloc": proc["v_ram_alloc"],
            "action": "wait",
            "reason": proc.get("reason", "")
        })
        pending_list.append({
            "pid": proc["pid"],
            "name": proc["name"],
            "v_cpu_alloc": proc["v_cpu_alloc"],
            "v_ram_alloc": proc["v_ram_alloc"],
            "score": proc["score"]
        })

df_virtual_adj = pd.DataFrame(adjusted)

# 6) Auto Recovery: compression + drop worst if needed
total_vram = float(df_virtual_adj["v_ram_alloc"].sum()) if not df_virtual_adj.empty else 0.0
total_vcpu = float(df_virtual_adj["v_cpu_alloc"].sum()) if not df_virtual_adj.empty else 0.0

if total_vram > VIRTUAL_RAM_MB and total_vram > 0:
    compression_ratio = VIRTUAL_RAM_MB / total_vram
    df_virtual_adj["v_ram_alloc"] = (df_virtual_adj["v_ram_alloc"] * compression_ratio).round(2)
    total_vram = float(df_virtual_adj["v_ram_alloc"].sum())

if total_vram > VIRTUAL_RAM_MB:
    score_map = {d['pid']: d['score'] for d in decisions}
    while total_vram > VIRTUAL_RAM_MB and not df_virtual_adj.empty and score_map:
        worst_pid = max(score_map.keys(), key=lambda p: score_map.get(p, 0.0))
        df_virtual_adj = df_virtual_adj[df_virtual_adj["pid"] != worst_pid]
        score_map.pop(worst_pid, None)
        total_vram = float(df_virtual_adj["v_ram_alloc"].sum())

total_vcpu = float(df_virtual_adj["v_cpu_alloc"].sum()) if not df_virtual_adj.empty else 0.0

# 7) Host summary metrics
host_cpu_percent = psutil.cpu_percent(interval=0.5)
host_ram_percent = psutil.virtual_memory().percent

if total_vram < VIRTUAL_RAM_MB * 0.8:
    status = "Stable"
elif total_vram < VIRTUAL_RAM_MB:
    status = "Near Limit"
else:
    status = "Overload"

# Persist session stores
st.session_state['wait_times'] = session_store.get('wait_times', st.session_state.get('wait_times', {}))
st.session_state['usage_history'] = session_store.get('usage_history', st.session_state.get('usage_history', {}))

# 8) Logging
log_entry = f"{time.strftime('%H:%M:%S')} | Status: {status} | Virtual RAM {round(total_vram,2)}MB / {VIRTUAL_RAM_MB}MB | Virtual CPU {round(total_vcpu,2)} / {VIRTUAL_CPU_UNITS}"
st.session_state['log'].append(log_entry)
if len(st.session_state['log']) > 500:
    st.session_state['log'] = st.session_state['log'][-500:]

# 9) UI Layout
placeholder = st.empty()
with placeholder.container():
    st.subheader("Host Resource Snapshot")
    hc1, hc2, hc3 = st.columns(3)
    hc1.metric("Host CPU %", f"{host_cpu_percent}%")
    hc2.metric("Host RAM %", f"{host_ram_percent}%")
    hc3.write(f"Active: {active_info.get('process_name')} — {active_info.get('title')}")

    st.markdown("---")
    st.subheader("Virtual PC Resource Allocation Summary")
    vc1, vc2, vc3 = st.columns(3)
    vc1.metric("Virtual CPU Used", f"{round(total_vcpu,2)} / {VIRTUAL_CPU_UNITS}")
    vc2.metric("Virtual RAM Used", f"{round(total_vram,2)} MB / {VIRTUAL_RAM_MB} MB")
    vc3.write(f"Status: {status}")

    st.markdown("---")
    st.subheader("Virtual Task Table (Adjusted)")
    if not df_virtual_adj.empty:
        st.dataframe(df_virtual_adj[['pid','name','v_cpu_alloc','v_ram_alloc','action','reason']].reset_index(drop=True), use_container_width=True)
    else:
        st.write("No virtual tasks after adjustments.")

    st.markdown("---")
    st.subheader("AI Decision Tree (Process Weights & Actions)")
    if decisions:
        try:
            df_dec = pd.DataFrame(decisions)[
                ['pid','name','v_cpu_alloc','v_ram_alloc','w_cpu','w_ram','w_wait','w_vis','w_hist','score','action','reason','wait_time_sec']
            ]
            st.dataframe(df_dec.reset_index(drop=True), use_container_width=True)
        except Exception:
            st.write("Decision data is available but could not be shown as table due to format.")
    else:
        st.info("No AI decisions available.")

    st.markdown("---")
    st.subheader("Virtual Scheduling Order (Descending Priority)")
    if decisions:
        for idx, d in enumerate(decisions[:20], start=1):
            st.write(f"{idx}. {d['name']} (PID {d['pid']}) → {d['action'].upper()} | score={d['score']} | CPU={d['v_cpu_alloc']} | RAM={d['v_ram_alloc']}")
    else:
        st.write("No scheduled virtual tasks.")

    st.markdown("---")
    st.subheader("Monitor Panels")

    kc, pc, hc = st.columns([1,1,1])
    with kc:
        st.markdown("Killed Processes (history recent 20)")
        killed_df = pd.DataFrame(st.session_state['killed_history'][-20:])
        if not killed_df.empty:
            st.dataframe(killed_df[['time','pid','name','v_cpu_alloc','v_ram_alloc','score','reason']].reset_index(drop=True), use_container_width=True)
        else:
            st.write("No processes killed yet.")

    with pc:
        st.markdown("Pending Processes (action = wait)")
        if pending_list:
            df_pending = pd.DataFrame(pending_list).sort_values(by='score', ascending=False).reset_index(drop=True)
            st.dataframe(df_pending[['pid','name','v_cpu_alloc','v_ram_alloc','score']].head(50), use_container_width=True)
        else:
            st.write("No pending processes.")

    with hc:
        st.markdown("High-CPU Virtual Tasks")
        if not df_virtual_adj.empty:
            df_cpu_sorted = df_virtual_adj.sort_values(by='v_cpu_alloc', ascending=False).reset_index(drop=True)
            st.dataframe(df_cpu_sorted[['pid','name','v_cpu_alloc','v_ram_alloc']].head(20), use_container_width=True)
        else:
            st.write("No virtual tasks to show.")

    st.markdown("---")
    st.subheader("AI Event Log (recent)")
    st.text_area("System Log", "\n".join(st.session_state['log'][-50:]), height=220)

# End of single-pass run. Streamlit will re-run on refresh/autorefresh or manual refresh.
