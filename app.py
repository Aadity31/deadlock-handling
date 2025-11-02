# app.py
"""
Streamlit app — AI Virtual Deadlock Simulator (low-end VM)
Usage: streamlit run app.py
- Low-end VM defaults: 512 MB, 50 CPU units
- Visual deadlock flash for examiner when 'deadlocked' detected
- CPU mapping normalized so total CPU units do not exceed VIRTUAL_CPU_UNITS
- Live update without full reload
"""

import time
import psutil
import pandas as pd
import streamlit as st
import json
import os
import matplotlib.pyplot as plt

from decision_tree import compute_scores, VIRTUAL_RAM_MB, VIRTUAL_CPU_UNITS
from vpc import map_host_to_virtual, get_visible_windows, get_active_window_info

SESSION_FILE = ".session_store.json"

def load_session_store():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data
        except Exception:
            return {}
    return {}

def save_session_store(store):
    try:
        dumpable = dict(store)
        if 'usage_history' in dumpable:
            dumpable['usage_history'] = dict(dumpable['usage_history'])
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(dumpable, f, indent=2)
    except Exception:
        pass


st.set_page_config(page_title="AI Virtual Deadlock Simulator (Low-end Demo)", layout="wide")
st.title("AI Deadlock Handling — Low-end Virtual PC (512MB / 50 CPU units)")

# session defaults
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


# load persisted
persisted = load_session_store()
if persisted.get('wait_times') and not st.session_state.get('wait_times'):
    st.session_state['wait_times'] = persisted.get('wait_times')
if persisted.get('usage_history') and not st.session_state.get('usage_history'):
    st.session_state['usage_history'] = persisted.get('usage_history')

# sidebar
st.sidebar.header("Simulation Controls")
refresh_interval = st.sidebar.slider("Refresh interval (seconds)", 2, 6, st.session_state['refresh_interval'])
st.session_state['refresh_interval'] = refresh_interval
live_mode = st.sidebar.toggle("🔄 Live Update Mode", value=True)

placeholder = st.empty()

# ================== MAIN LIVE UPDATE LOOP ==================
run_loop = True
if live_mode:
    while run_loop:
        with placeholder.container():

            # 1) gather host snapshot (safer cpu sampling)
            processes = []
            for proc in psutil.process_iter(['pid','name']):
                try:
                    proc.cpu_percent(interval=None)
                except Exception:
                    pass

            time.sleep(0.2)  # small stable sampling

            for proc in psutil.process_iter(['pid','name','cpu_percent','memory_percent']):
                try:
                    info = {}
                    try:
                        info = proc.as_dict(attrs=['pid','name','cpu_percent','memory_percent'])
                    except Exception:
                        info = proc.info
                    info["cpu_percent"] = float(info.get("cpu_percent", 0.0) or 0.0)
                    info["memory_percent"] = float(info.get("memory_percent", 0.0) or 0.0)
                    processes.append(info)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                except Exception:
                    continue

            df_host = pd.DataFrame(processes)
            if df_host.empty:
                st.warning("No host process data available.")
                break

            visible_windows = get_visible_windows()
            active_info = get_active_window_info()

            # 2) map host -> virtual (low-end)
            df_virtual = map_host_to_virtual(df_host, VIRTUAL_RAM_MB, VIRTUAL_CPU_UNITS)

            # inject stable demo tasks (keeps behavior consistent)
            extra_tasks = [
                {"pid": 9901, "name": "AI_Optimizer", "v_cpu_alloc": 5, "v_ram_alloc": 40},
                {"pid": 9902, "name": "MemoryBalancer", "v_cpu_alloc": 4, "v_ram_alloc": 30},
                {"pid": 9903, "name": "DeadlockResolver", "v_cpu_alloc": 3, "v_ram_alloc": 25},
            ]
            if df_virtual is None or df_virtual.empty:
                df_virtual = pd.DataFrame(extra_tasks)
            else:
                df_virtual = pd.concat([df_virtual, pd.DataFrame(extra_tasks)], ignore_index=True)

            # 3) scoring
            session_store = {
                'wait_times': st.session_state.get('wait_times', {}),
                'usage_history': st.session_state.get('usage_history', {}),
                'refresh_interval': refresh_interval
            }
            decisions = compute_scores(df_virtual, visible_windows=visible_windows, session_store=session_store)

            # persist session store
            st.session_state['wait_times'] = session_store.get('wait_times', st.session_state.get('wait_times', {}))
            st.session_state['usage_history'] = session_store.get('usage_history', st.session_state.get('usage_history', {}))
            save_session_store({'wait_times': st.session_state['wait_times'], 'usage_history': st.session_state['usage_history']})

            # 4) apply actions
            adjusted = []
            killed_this_cycle = []
            pending_list = []
            deadlock_detected = False
            deadlocked_items = []

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
                elif proc["action"] == "deadlocked":
                    deadlock_detected = True
                    deadlocked_items.append(proc)
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

            # 5) auto recovery/compression
            total_vram = float(df_virtual_adj["v_ram_alloc"].sum()) if not df_virtual_adj.empty else 0.0
            total_vcpu = float(df_virtual_adj["v_cpu_alloc"].sum()) if not df_virtual_adj.empty else 0.0

            if total_vram > 0 and total_vram > VIRTUAL_RAM_MB:
                compression_ratio = min(1.0, VIRTUAL_RAM_MB / total_vram)
                df_virtual_adj["v_ram_alloc"] = (df_virtual_adj["v_ram_alloc"] * compression_ratio).round(2)
                total_vram = float(df_virtual_adj["v_ram_alloc"].sum())

            if total_vram > VIRTUAL_RAM_MB:
                score_map = {d['pid']: d['score'] for d in decisions}
                while total_vram > VIRTUAL_RAM_MB and not df_virtual_adj.empty and score_map:
                    worst_pid = min(score_map.keys(), key=lambda p: score_map.get(p, 1.0))
                    df_virtual_adj = df_virtual_adj[df_virtual_adj["pid"] != worst_pid]
                    score_map.pop(worst_pid, None)
                    total_vram = float(df_virtual_adj["v_ram_alloc"].sum())

            total_vcpu = float(df_virtual_adj["v_cpu_alloc"].sum()) if not df_virtual_adj.empty else 0.0

            # 6) host metrics
            host_cpu_percent = psutil.cpu_percent(interval=0.5)
            host_ram_percent = psutil.virtual_memory().percent

            if total_vram < VIRTUAL_RAM_MB * 0.8:
                status = "Stable"
            elif total_vram < VIRTUAL_RAM_MB:
                status = "Near Limit"
            else:
                status = "Overload"

            log_entry = f"{time.strftime('%H:%M:%S')} | Status: {status} | Virtual RAM {round(total_vram,2)}MB / {VIRTUAL_RAM_MB}MB | Virtual CPU {round(total_vcpu,2)} / {VIRTUAL_CPU_UNITS}"
            st.session_state['log'].append(log_entry)
            if len(st.session_state['log']) > 500:
                st.session_state['log'] = st.session_state['log'][-500:]

            # 7) UI Rendering
            st.subheader("Host Snapshot")
            hc1, hc2, hc3 = st.columns(3)
            hc1.metric("Host CPU %", f"{host_cpu_percent}%")
            hc2.metric("Host RAM %", f"{host_ram_percent}%")
            hc3.write(f"Active: {active_info.get('process_name')} — {active_info.get('title')}")

            st.markdown("---")
            st.subheader("Virtual PC Summary (Low-end)")
            vc1, vc2, vc3 = st.columns(3)
            vc1.metric("Virtual CPU Used", f"{round(total_vcpu,2)} / {VIRTUAL_CPU_UNITS}")
            vc2.metric("Virtual RAM Used", f"{round(total_vram,2)} MB / {VIRTUAL_RAM_MB} MB")
            vc3.write(f"Status: {status}")

            st.markdown("**Resource balance (visual)**")
            fig1, ax1 = plt.subplots()
            used = max(0.0, total_vcpu)
            free = max(0.0, VIRTUAL_CPU_UNITS - used)
            ax1.pie([used, free], labels=["Used CPU", "Free CPU"], autopct='%1.1f%%')
            st.pyplot(fig1)

            st.markdown("---")
            st.subheader("Virtual Task Table (Adjusted)")
            if not df_virtual_adj.empty:
                st.dataframe(df_virtual_adj[['pid','name','v_cpu_alloc','v_ram_alloc','action','reason']].reset_index(drop=True), use_container_width=True)
            else:
                st.write("No virtual tasks after adjustments.")

            st.markdown("---")
            st.subheader("AI Decision Tree (Weights & Actions)")
            if decisions:
                try:
                    df_dec = pd.DataFrame(decisions)[
                        ['pid','name','v_cpu_alloc','v_ram_alloc','w_cpu','w_ram','w_wait','w_vis','w_hist','score','action','reason','wait_time_sec']
                    ]
                    st.dataframe(df_dec.reset_index(drop=True), use_container_width=True)
                    viz_df = df_dec[['name','w_cpu','w_ram','w_wait','w_vis','w_hist','score']].set_index('name')
                    st.bar_chart(viz_df)
                except Exception:
                    st.write("Decision data present but cannot render table.")
            else:
                st.info("No AI decisions available.")

            st.markdown("---")
            st.subheader("Virtual Scheduling Order (Priority)")
            if decisions:
                for idx, d in enumerate(decisions[:20], start=1):
                    st.write(f"{idx}. {d['name']} (PID {d['pid']}) → {d['action'].upper()} | score={d['score']} | CPU={d['v_cpu_alloc']} | RAM={d['v_ram_alloc']}  — {d.get('reason','')}")
            else:
                st.write("No scheduled tasks.")

            st.markdown("---")
            st.subheader("Monitor Panels")
            kc, pc, hc = st.columns([1,1,1])
            with kc:
                st.markdown("Killed / Resolved (recent 20)")
                killed_df = pd.DataFrame(st.session_state['killed_history'][-20:])
                if not killed_df.empty:
                    st.dataframe(killed_df[['time','pid','name','v_cpu_alloc','v_ram_alloc','score','reason']].reset_index(drop=True), use_container_width=True)
                else:
                    st.write("No entries yet.")

            with pc:
                st.markdown("Pending (wait)")
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

            if deadlock_detected:
                st.error("⚠️ DEADLOCK(S) DETECTED — Deadlock handler triggered.")
                for d in deadlocked_items:
                    st.warning(f"Deadlocked: {d['name']} (PID {d['pid']}) — reason: {d.get('reason','')}, wait_time={d.get('wait_time_sec')}")
                st.markdown("<h3 style='color:darkred'>DEADLOCK RESOLVER RUN — see Killed/Resolved panel</h3>", unsafe_allow_html=True)

        # Sleep for live refresh (no reload)
        time.sleep(refresh_interval)
else:
    st.info("Live update mode paused. Enable it from sidebar.")
