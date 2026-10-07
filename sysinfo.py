"""What the PC is doing, read only: drives, battery, CPU, RAM, the apps using the most, network, uptime.
Nothing here changes anything, so it's safe to answer whoever asks."""
import ctypes
import os
import platform
import re
import socket
import time

import psutil

GB = 1024 ** 3
NAMES = {"msedge": "Edge", "code": "VS Code", "explorer": "File Explorer", "msmpeng": "Windows Defender",
         "svchost": "Windows services",
         "pythonw": "Hey Jev", "python": "Hey Jev", "dwm": "the Windows desktop", "searchhost": "Windows Search",
         "memory compression": "Windows memory compression", "system": "Windows", "vmmem": "WSL",
         "vmmemwsl": "WSL", "registry": "the Windows registry"}
KINDS = ("disk", "battery", "cpu", "memory", "apps", "network", "uptime", "system")


def _app_name(name):
    stem = re.sub(r"\.exe$", "", name or "", flags=re.I)
    return NAMES.get(stem.lower(), stem[:1].upper() + stem[1:])


def drives():
    out = []
    for p in psutil.disk_partitions(all=False):
        if "cdrom" in p.opts or not p.fstype:
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        out.append({"drive": p.device.rstrip("\\").rstrip(":"), "free_gb": round(u.free / GB, 1),
                    "total_gb": round(u.total / GB, 1), "used_percent": round(u.percent)})
    return out


def battery():
    b = psutil.sensors_battery()
    if b is None:
        return {"has_battery": False}
    left = b.secsleft
    minutes = None if b.power_plugged or left in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) or left < 0 \
        else int(left // 60)
    return {"has_battery": True, "percent": round(b.percent), "plugged_in": bool(b.power_plugged), "minutes_left": minutes}


class _Text(ctypes.Structure):  # UNICODE_STRING
    _fields_ = [("length", ctypes.c_ushort), ("max_length", ctypes.c_ushort), ("buffer", ctypes.c_void_p)]


class _Process(ctypes.Structure):  # the start of SYSTEM_PROCESS_INFORMATION, as Task Manager reads it
    _fields_ = [("next", ctypes.c_ulong), ("threads", ctypes.c_ulong), ("private_working_set", ctypes.c_longlong),
                ("hard_faults", ctypes.c_ulong), ("threads_high", ctypes.c_ulong), ("cycles", ctypes.c_ulonglong),
                ("created", ctypes.c_longlong), ("user_time", ctypes.c_longlong), ("kernel_time", ctypes.c_longlong),
                ("name", _Text), ("priority", ctypes.c_long), ("pid", ctypes.c_void_p), ("parent", ctypes.c_void_p),
                ("handles", ctypes.c_ulong), ("session", ctypes.c_ulong), ("key", ctypes.c_void_p),
                ("peak_virtual", ctypes.c_size_t), ("virtual", ctypes.c_size_t), ("page_faults", ctypes.c_ulong),
                ("peak_working_set", ctypes.c_size_t), ("working_set", ctypes.c_size_t)]


_ntdll = ctypes.WinDLL("ntdll")
_ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
                                            ctypes.POINTER(ctypes.c_ulong)]
_ntdll.NtQuerySystemInformation.restype = ctypes.c_long


def _snapshot():
    """{pid: (name, CPU time in 100 ns units, RAM in bytes)} for every process, in one call. psutil asks one process
    at a time, and for the 130 or so here it can't open itself it reads all of them again each time: a CPU check
    took 9 seconds that way."""
    size = ctypes.c_ulong(0)
    for _ in range(5):
        buf = ctypes.create_string_buffer(size.value + 128 * 1024)
        status = _ntdll.NtQuerySystemInformation(5, buf, len(buf), ctypes.byref(size)) & 0xFFFFFFFF
        if status == 0:
            break
        if status != 0xC0000004:  # STATUS_INFO_LENGTH_MISMATCH: more processes than room, try a bigger buffer
            raise OSError(f"Windows wouldn't list the processes ({status:#x})")
    else:
        raise OSError("Windows wouldn't list the processes")
    out, offset = {}, 0
    while True:
        p = _Process.from_buffer(buf, offset)
        name = ctypes.wstring_at(p.name.buffer, p.name.length // 2) if p.name.buffer else ""
        out[p.pid or 0] = (name, p.user_time + p.kernel_time, p.working_set)
        if not p.next:
            return out
        offset += p.next


def _sample_cpu(n=5, secs=0.5):
    """(whole CPU %, the apps using the most) from one half-second sample, added up by program. This process is left
    out, since measuring is all it's doing just then."""
    me = os.getpid()
    psutil.cpu_percent(None)
    before, t0 = _snapshot(), time.perf_counter()
    time.sleep(secs)
    after, t1 = _snapshot(), time.perf_counter()
    total = psutil.cpu_percent(None)
    whole = (t1 - t0) * 1e7 * (psutil.cpu_count() or 1)  # all the cores' time, in 100 ns units
    totals = {}
    for pid, (name, cpu, _) in after.items():
        if pid in (0, me) or not name or before.get(pid, ("",))[0] != name:
            continue
        totals[_app_name(name)] = totals.get(_app_name(name), 0) + (cpu - before[pid][1]) / whole * 100
    top = sorted(totals.items(), key=lambda kv: -kv[1])[:n]
    return total, [{"app": k, "cpu_percent": round(v, 1)} for k, v in top if v >= 0.05]


def top_apps(by="memory", n=5):
    """The apps using the most RAM or CPU, added up by program, since Chrome runs as dozens of processes."""
    if by == "cpu":
        return _sample_cpu(n)[1]
    totals = {}
    for pid, (name, _, ram) in _snapshot().items():
        if pid and name:
            totals[_app_name(name)] = totals.get(_app_name(name), 0) + ram
    top = sorted(totals.items(), key=lambda kv: -kv[1])[:n]
    return [{"app": k, "memory_gb": round(v / GB, 2)} for k, v in top]


def cpu():
    total, top = _sample_cpu(3)
    return {"percent": round(total), "cores": psutil.cpu_count(), "top": top}


def memory():
    vm = psutil.virtual_memory()
    return {"used_gb": round((vm.total - vm.available) / GB, 1), "total_gb": round(vm.total / GB, 1),
            "percent": round(vm.percent), "top": top_apps("memory", 3)}


def network():
    """Online or not, and the adapters with an address. Not netsh for the Wi-Fi name: it took 4 seconds here."""
    stats, links = psutil.net_if_stats(), []
    for name, entries in psutil.net_if_addrs().items():
        if not stats.get(name) or not stats[name].isup or re.search(r"loopback|vethernet|virtual|vmware|vbox|bluetooth",
                                                                     name, re.I):
            continue
        ips = [a.address for a in entries if a.family == socket.AF_INET and not a.address.startswith(("127.", "169.254."))]
        if ips:
            links.append({"adapter": name, "ip": ips[0]})
    try:
        socket.create_connection(("opencode.ai", 443), timeout=2).close()  # the server she already talks to
        online = True
    except OSError:
        online = False
    return {"online": online, "connections": links[:3]}


def uptime():
    secs = int(time.time() - psutil.boot_time())
    return {"hours": secs // 3600, "minutes": secs % 3600 // 60}


def system():
    vm = psutil.virtual_memory()
    return {"windows": platform.platform(terse=True), "pc_name": socket.gethostname(),
            "processor": platform.processor(), "cores": psutil.cpu_count(), "ram_gb": round(vm.total / GB, 1)}


def lookup(what):
    """The facts for one kind of question, as a small dict for the model."""
    what = (what or "").lower()
    if what in ("disk", "storage", "drive", "drives", "space"):
        return {"drives": drives()}
    if what == "battery":
        return battery()
    if what in ("cpu", "processor"):
        return cpu()
    if what in ("memory", "ram"):
        return memory()
    if what in ("apps", "processes"):
        return {"by_memory": top_apps("memory"), "by_cpu": top_apps("cpu")}
    if what in ("network", "wifi", "internet", "ip"):
        return network()
    if what == "uptime":
        return uptime()
    if what in ("system", "pc", "windows"):
        return system()
    raise RuntimeError(f"I can't look up {what or 'that'}")


def _gb(x):
    return f"{x:.0f} GB" if x >= 10 else f"{x:.1f} GB"


def describe(what, data, drive=None):
    """One or two sentences she can say about lookup(what)."""
    if what == "disk":
        ds = data["drives"]
        one = [d for d in ds if drive and d["drive"].lower() == drive.lower()]
        if one:
            d = one[0]
            return (f"Your {d['drive']} drive has {_gb(d['free_gb'])} free out of {_gb(d['total_gb'])}, "
                    f"so it's {d['used_percent']}% full.")
        missing = f"There's no {drive.upper()} drive here. " if drive else ""
        return missing + " ".join(f"{d['drive']} drive: {_gb(d['free_gb'])} free of {_gb(d['total_gb'])}." for d in ds)
    if what == "battery":
        if not data["has_battery"]:
            return "This PC doesn't have a battery."
        line = f"Battery is at {data['percent']}%"
        if data["plugged_in"]:
            return line + " and plugged in."
        mins = data["minutes_left"]
        if not mins:
            return line + ", not plugged in."
        h, m = divmod(mins, 60)
        left = " and ".join(f"{n} {unit}{'' if n == 1 else 's'}" for n, unit in ((h, "hour"), (m, "minute")) if n)
        return line + f", not plugged in, about {left} left."
    if what == "cpu":
        top = data["top"][0] if data["top"] else None
        return f"The CPU is at {data['percent']}%." + (f" {top['app']} is using the most." if top else "")
    if what == "memory":
        top = data["top"][0] if data["top"] else None
        return (f"You're using {data['used_gb']} of {data['total_gb']} GB of RAM, {data['percent']}%."
                + (f" {top['app']} uses the most, {_gb(top['memory_gb'])}." if top else ""))
    if what == "apps":
        names = ", ".join(f"{a['app']} {_gb(a['memory_gb'])}" for a in data["by_memory"][:3])
        return f"Using the most memory: {names}."
    if what == "network":
        if not data["online"]:
            return "You're not connected to the internet right now."
        c = data["connections"][0] if data["connections"] else None
        via = "" if not c else " on Wi-Fi" if re.search(r"wi-?fi|wlan|wireless", c["adapter"], re.I) else f" over {c['adapter']}"
        return f"You're online{via}" + (f", your IP is {c['ip']}." if c else ".")
    if what == "uptime":
        h, m = data["hours"], data["minutes"]
        return f"Your PC has been on for {h} hour{'s' if h != 1 else ''} and {m} minute{'s' if m != 1 else ''}." if h \
            else f"Your PC has been on for {m} minutes."
    if what == "system":
        return f"This is {data['pc_name']}, on {data['windows']}, with {data['cores']} cores and {data['ram_gb']} GB of RAM."
    return ""
