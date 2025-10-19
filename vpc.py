# vpc.py
"""
Host -> Virtual mapping and Windows visibility helpers.
Contains:
 - map_host_to_virtual(df_host)
 - get_visible_windows()
 - get_active_window_info()
"""

import ctypes
from ctypes import wintypes
import psutil
import win32gui
import win32process

# If you want to reuse VIRTUAL_ constants from decision_tree, import them in the caller (app.py).
# This module focuses only on mapping and window helpers.

def get_visible_windows():
    visible_windows = []

    def enum_window_callback(hwnd, _):
        try:
            if win32gui.IsWindowVisible(hwnd):
                rect = win32gui.GetWindowRect(hwnd)
                x, y, right, bottom = rect
                width, height = right - x, bottom - y
                area = max(0, width * height)
                # ignore tiny windows
                if area < 5000:
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    proc = psutil.Process(pid)
                    name = proc.name()
                except Exception:
                    name = "Unknown"
                title = win32gui.GetWindowText(hwnd)
                if title and title.strip():
                    visible_windows.append({
                        "pid": pid,
                        "process_name": name,
                        "title": title,
                        "area": area
                    })
        except Exception:
            pass

    try:
        win32gui.EnumWindows(enum_window_callback, None)
    except Exception:
        return []
    return visible_windows


def get_active_window_info():
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pid = pid.value
        title = win32gui.GetWindowText(hwnd)
        name = None
        try:
            proc = psutil.Process(pid)
            name = proc.name()
        except Exception:
            name = "Unknown"
        return {"pid": pid, "process_name": name, "title": title}
    except Exception:
        return {"pid": -1, "process_name": "Unknown", "title": ""}


def map_host_to_virtual(df_host, VIRTUAL_RAM_MB=1024, VIRTUAL_CPU_UNITS=100):
    """
    Map host process metrics to virtual allocations.
    Returns a pandas.DataFrame with columns: pid, name, v_cpu_alloc, v_ram_alloc
    """
    import pandas as pd

    rows = []
    # total physical RAM in MB
    system_ram_mb = psutil.virtual_memory().total / (1024 * 1024)

    # Filter tiny memory processes to reduce noise
    if "memory_percent" in df_host.columns:
        df_host = df_host[df_host["memory_percent"] > 0.05]
    else:
        # nothing to map
        return pd.DataFrame(rows)

    # scaling heuristic:
    host_reference = max(system_ram_mb * 0.5, VIRTUAL_RAM_MB)
    scaling_factor = min(1.0, VIRTUAL_RAM_MB / host_reference)

    for _, r in df_host.iterrows():
        pid = int(r.get('pid', -1) or -1)
        name = str(r.get('name', 'unknown')).strip() or f"proc_{pid}"
        # CPU percent for the process (0..100)
        cpu = float(r.get('cpu_percent', 0.0) or 0.0)
        mem_pct = float(r.get('memory_percent', 0.0) or 0.0)

        # Map CPU to virtual CPU units (0..VIRTUAL_CPU_UNITS)
        v_cpu = min((cpu / 100.0) * VIRTUAL_CPU_UNITS, VIRTUAL_CPU_UNITS)

        # Host process RAM in MB
        host_proc_ram_mb = (mem_pct / 100.0) * system_ram_mb

        # Apply scaling factor so processes don't blow up virtual capacity
        v_ram = host_proc_ram_mb * scaling_factor

        # Clamp per-process virtual RAM so no single process exceeds a safe share
        v_ram = min(v_ram, VIRTUAL_RAM_MB * 0.8)

        rows.append({
            "pid": pid,
            "name": name,
            "v_cpu_alloc": round(v_cpu, 2),
            "v_ram_alloc": round(v_ram, 2)
        })

    return pd.DataFrame(rows)
