# vpc.py
"""
Host -> Virtual mapping and Windows visibility helpers.
Designed for low-end VM simulation:
 - map_host_to_virtual: proportional CPU mapping (so total <= VIRTUAL_CPU_UNITS)
 - get_visible_windows, get_active_window_info
"""

import ctypes
from ctypes import wintypes
import psutil
import win32gui
import win32process
import logging

logger = logging.getLogger(__name__)

def get_visible_windows(min_area=3000):
    visible_windows = []

    def enum_window_callback(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            rect = win32gui.GetWindowRect(hwnd)
            x, y, right, bottom = rect
            width, height = right - x, bottom - y
            area = max(0, width * height)
            if area < min_area:
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
                    "pid": int(pid),
                    "process_name": name,
                    "title": title,
                    "area": area
                })
        except Exception as e:
            logger.debug("enum_window_callback error: %s", e)

    try:
        win32gui.EnumWindows(enum_window_callback, None)
    except Exception as e:
        logger.exception("EnumWindows failed: %s", e)
        return []
    return visible_windows


def get_active_window_info():
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pid = pid.value
        title = win32gui.GetWindowText(hwnd)
        name = "Unknown"
        try:
            proc = psutil.Process(pid)
            name = proc.name()
        except Exception:
            pass
        return {"pid": pid or -1, "process_name": name, "title": title}
    except Exception:
        return {"pid": -1, "process_name": "Unknown", "title": ""}


def map_host_to_virtual(df_host, VIRTUAL_RAM_MB=512, VIRTUAL_CPU_UNITS=50):
    """
    Map host process metrics to virtual allocations (for low-end simulation).
    - CPU: proportional mapping so sum(v_cpu_alloc) ~= VIRTUAL_CPU_UNITS
    - RAM: scale relative to host memory but clamped to virtual size
    Returns pandas.DataFrame with columns: pid, name, v_cpu_alloc, v_ram_alloc
    """
    import pandas as pd
    rows = []
    try:
        system_ram_mb = psutil.virtual_memory().total / (1024 * 1024)
    except Exception:
        system_ram_mb = max(1024, VIRTUAL_RAM_MB)

    if df_host is None or df_host.empty:
        return pd.DataFrame(rows)

    # filter tiny processes
    if "memory_percent" in df_host.columns:
        df_host = df_host[df_host["memory_percent"] > 0.02]

    # defensive guard
    if df_host.empty:
        return pd.DataFrame(rows)

    # Total CPU across filtered processes (avoid per-process CPU% summation overflow)
    total_cpu = float(df_host["cpu_percent"].sum() or 1.0)

    # scaling factor to avoid extremely large per-process RAM mapping
    host_reference = max(system_ram_mb * 0.5, VIRTUAL_RAM_MB)
    scaling_factor = min(1.0, VIRTUAL_RAM_MB / host_reference) if host_reference > 0 else 1.0

    for _, r in df_host.iterrows():
        try:
            pid = int(r.get('pid', -1) or -1)
            name = str(r.get('name', f"proc_{pid}")).strip() or f"proc_{pid}"
            cpu = float(r.get('cpu_percent', 0.0) or 0.0)
            mem_pct = float(r.get('memory_percent', 0.0) or 0.0)

            # CPU: proportional so total approx VIRTUAL_CPU_UNITS
            v_cpu = (cpu / total_cpu) * VIRTUAL_CPU_UNITS if total_cpu > 0 else 0.0
            # clamp single process to reasonable share (40% of units)
            v_cpu = max(0.0, min(v_cpu, VIRTUAL_CPU_UNITS * 0.4))

            # RAM:
            host_proc_ram_mb = (mem_pct / 100.0) * system_ram_mb
            v_ram = host_proc_ram_mb * scaling_factor
            v_ram = max(0.0, min(v_ram, VIRTUAL_RAM_MB * 0.9))

            rows.append({
                "pid": pid,
                "name": name,
                "v_cpu_alloc": round(v_cpu, 2),
                "v_ram_alloc": round(v_ram, 2)
            })
        except Exception as e:
            logger.debug("map_host_to_virtual: skip row due to %s", e)
            continue

    return pd.DataFrame(rows)
