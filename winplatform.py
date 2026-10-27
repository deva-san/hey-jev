"""Windows versions of everything the Mac build did with AppleScript, afplay, pbcopy and pmset."""
import asyncio
import contextlib
import ctypes
import json
import os
import re
import struct
import subprocess
import sys
import threading
import time
import winreg
from ctypes import wintypes
from functools import lru_cache
from urllib.parse import quote


# --------------------------------------------------------------------------- the C++ runtime, first
def _system_cpp_runtime():
    """Windows' own C++ runtime, loaded before any package can load its older copy. winrt brings MSVCP140.dll
    14.29, and onnxruntime and sherpa-onnx, built with a newer one, crash in that one (a mutex, 0xc0000005) if it's
    loaded first: once a DLL of that name is in the process, every later load of the name gets it. On 22 October
    the island's media plugin imported winrt before the speech models loaded, and she crashed 4 seconds in. The
    runtime is backward compatible, so winrt runs on the newer one."""
    path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "msvcp140.dll")
    try:
        if os.path.exists(path):
            ctypes.WinDLL(path)
    except Exception:  # not Windows (the tests' stand-ins), or a runtime Windows won't load: as it was
        pass


_system_cpp_runtime()

# --------------------------------------------------------------------------- paths
# On 8 Oct `python -m unittest` from the repo root imported siri through the old hand checks (test_listen.py and co.)
# before tests/support.py had moved %APPDATA%, and the test run wrote 982 turns into her real history, 1,488 runs into
# the task log, 88 dictations, and an empty contacts book over three real people. So in a test run her real folders
# are refused outright: tests/support.py sets HEYJEV_TESTING to the real folders before it imports anything, and a
# test runner that started without it (python -m unittest, pytest, an editor's) is told apart by what it ran. A normal
# run of hers is neither, and for her this is one dict lookup.
RUNNERS = ("pytest", "_pytest", "unittestadapter", "teamcity")  # an editor's runner loads one of these first


def _test_run():
    main = sys.modules.get("__main__")
    started = (getattr(getattr(main, "__spec__", None), "name", None) or "").split(".")[0]
    return started in ("unittest", "pytest") or any(name in sys.modules for name in RUNNERS)


# Worked out once, here: a runner is always loaded before it imports her code. Asked again on every use, a library
# that imported pytest inside her running app would have made her voice and decider folders raise from then on.
TEST_RUN = _test_run()


def own_data(path):
    """path, unless this is a test run and path is in her real data, which raises instead."""
    real = os.environ.get("HEYJEV_TESTING")
    if real is None and not TEST_RUN:
        return path
    home = os.path.expanduser("~")
    bases = (real or os.pathsep.join((os.environ.get("APPDATA", ""), os.environ.get("LOCALAPPDATA", "")))).split(
        os.pathsep) + [os.path.join(home, "AppData", "Roaming"), os.path.join(home, "AppData", "Local"), home]
    target = os.path.normcase(os.path.abspath(path))
    for base in filter(None, bases):
        mine = os.path.normcase(os.path.abspath(os.path.join(base, "Hey Jev")))
        if target == mine or target.startswith(mine + os.sep):
            raise RuntimeError(f"a test run reached her real data ({path}): import tests.support first, and run the "
                               "suite as python -m unittest discover -s tests -t .")
    return path


APPDATA_DIR = own_data(os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Hey Jev"))
LOG_DIR = own_data(os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Hey Jev", "Logs"))
os.makedirs(APPDATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)


def log_path(name):
    """Where the Mac build used ~/Library/Logs/<name>."""
    return os.path.join(LOG_DIR, name)


CREATE_NO_WINDOW = 0x08000000  # no console flashing up when the app runs without one
_ps = os.path.join(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows",
                   "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
POWERSHELL = _ps if os.path.exists(_ps) else "powershell"  # full path, the shortcut's PATH can't always find it

# --------------------------------------------------------------------------- Win32
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32")
dwmapi = ctypes.WinDLL("dwmapi")
version = ctypes.WinDLL("version")
powrprof = ctypes.WinDLL("powrprof")
shell32 = ctypes.WinDLL("shell32")

HWND, DWORD, BOOL, UINT, LONG = wintypes.HWND, wintypes.DWORD, wintypes.BOOL, wintypes.UINT, wintypes.LONG
WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, wintypes.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", DWORD)]


def _sig(fn, args, res=BOOL):
    fn.argtypes, fn.restype = args, res


_sig(user32.EnumWindows, [WNDENUMPROC, wintypes.LPARAM])
_sig(user32.EnumChildWindows, [HWND, WNDENUMPROC, wintypes.LPARAM])
_sig(user32.GetWindowThreadProcessId, [HWND, ctypes.POINTER(DWORD)], DWORD)
_sig(user32.IsWindowVisible, [HWND])
_sig(user32.IsIconic, [HWND])
_sig(user32.IsWindow, [HWND])
_sig(user32.GetWindow, [HWND, UINT], HWND)
_sig(user32.GetAncestor, [HWND, UINT], HWND)
_sig(user32.GetWindowLongW, [HWND, ctypes.c_int], LONG)
_sig(user32.SetWindowLongW, [HWND, ctypes.c_int, LONG], LONG)
_sig(user32.GetWindowTextLengthW, [HWND], ctypes.c_int)
_sig(user32.GetWindowTextW, [HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int)
_sig(user32.GetClassNameW, [HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int)
_sig(user32.ShowWindow, [HWND, ctypes.c_int])
_sig(user32.SetWindowPos, [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, UINT])
_sig(user32.PostMessageW, [HWND, UINT, wintypes.WPARAM, wintypes.LPARAM])
_sig(user32.SendMessageTimeoutW, [HWND, UINT, wintypes.WPARAM, wintypes.LPCWSTR, UINT, UINT,
                                  ctypes.POINTER(ctypes.c_size_t)], wintypes.LPARAM)
_sig(user32.GetForegroundWindow, [], HWND)
_sig(user32.GetWindowRect, [HWND, ctypes.POINTER(RECT)])
_sig(user32.SetForegroundWindow, [HWND])
_sig(user32.BringWindowToTop, [HWND])
_sig(user32.AttachThreadInput, [DWORD, DWORD, BOOL])
_sig(user32.SwitchToThisWindow, [HWND, BOOL], None)
_sig(user32.FindWindowW, [wintypes.LPCWSTR, wintypes.LPCWSTR], HWND)
_sig(user32.LockWorkStation, [])
_sig(user32.MonitorFromWindow, [HWND, DWORD], wintypes.HANDLE)
_sig(user32.GetMonitorInfoW, [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)])
_sig(user32.OpenClipboard, [HWND])
_sig(user32.EmptyClipboard, [])
_sig(user32.CloseClipboard, [])
_sig(user32.SetClipboardData, [UINT, wintypes.HANDLE], wintypes.HANDLE)
_sig(kernel32.GlobalAlloc, [UINT, ctypes.c_size_t], ctypes.c_void_p)
_sig(kernel32.GlobalLock, [ctypes.c_void_p], ctypes.c_void_p)
_sig(kernel32.GlobalUnlock, [ctypes.c_void_p])
_sig(kernel32.GlobalFree, [ctypes.c_void_p], ctypes.c_void_p)
_sig(kernel32.OpenProcess, [DWORD, BOOL, DWORD], wintypes.HANDLE)
_sig(kernel32.QueryFullProcessImageNameW, [wintypes.HANDLE, DWORD, wintypes.LPWSTR, ctypes.POINTER(DWORD)])
_sig(kernel32.CloseHandle, [wintypes.HANDLE])
_sig(kernel32.GetCurrentThreadId, [], DWORD)
_sig(kernel32.CreateMutexW, [ctypes.c_void_p, BOOL, wintypes.LPCWSTR], wintypes.HANDLE)
_sig(dwmapi.DwmGetWindowAttribute, [HWND, DWORD, ctypes.c_void_p, DWORD], ctypes.c_long)
_sig(version.GetFileVersionInfoSizeW, [wintypes.LPCWSTR, ctypes.POINTER(DWORD)], DWORD)
_sig(version.GetFileVersionInfoW, [wintypes.LPCWSTR, DWORD, DWORD, ctypes.c_void_p])
_sig(version.VerQueryValueW, [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(UINT)])
_sig(powrprof.SetSuspendState, [wintypes.BOOLEAN, wintypes.BOOLEAN, wintypes.BOOLEAN], wintypes.BOOLEAN)
_sig(ole32.CoInitializeEx, [ctypes.c_void_p, DWORD], ctypes.c_long)

GW_OWNER, GA_ROOT, GA_ROOTOWNER, GWL_EXSTYLE = 4, 2, 3, -20
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x8, 0x20, 0x80
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x80000, 0x08000000
SW_HIDE, SW_MINIMIZE, SW_RESTORE = 0, 6, 9
SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x10, 0x40
HWND_TOPMOST = HWND(-1)
HWND_BROADCAST = HWND(0xFFFF)
WM_CLOSE, WM_SYSCOMMAND, WM_SETTINGCHANGE = 0x10, 0x112, 0x1A
SC_MONITORPOWER = 0xF170
SMTO_ABORTIFHUNG = 0x2
DWMWA_CLOAKED, DWMWA_EXTENDED_FRAME_BOUNDS = 14, 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MONITOR_DEFAULTTOPRIMARY = 1

# Windows parts that look like app windows but must never be closed or minimised as one
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow"}
# Never force-quit these: the taskbar, the frame UWP apps live in, and Jev herself
PROTECTED = {"explorer.exe", "applicationframehost.exe", "python.exe", "pythonw.exe", "py.exe", "pyw.exe",
             "dwm.exe", "csrss.exe", "winlogon.exe", "svchost.exe", "searchhost.exe",
             "startmenuexperiencehost.exe", "shellexperiencehost.exe", "textinputhost.exe"}

# --------------------------------------------------------------------------- COM, needed by pycaw (volume) and WinRT (media)
_tls = threading.local()
RPC_E_CHANGED_MODE = -2147417850


def _com():
    """Start COM on this thread. comtypes initialises COM again when first imported, so it must match this thread."""
    if getattr(_tls, "com", None) is None:
        _tls.com = "sta" if ole32.CoInitializeEx(None, 0) == RPC_E_CHANGED_MODE else "mta"
    if "comtypes" not in sys.modules:
        sys.coinit_flags = 2 if _tls.com == "sta" else 0


# --------------------------------------------------------------------------- sounds
MEDIA_DIR = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Media")
SOUNDS = {"wake": "Speech On.wav", "dictate_start": "Speech On.wav", "dictate_stop": "Speech Off.wav",
          "timer": "Windows Notify Calendar.wav"}  # stand-ins for the Mac's Tink, Pop and Glass


def play(path, write=None):
    """Play a sound file and wait until it's done, like afplay. write(out, data, rate): plays it instead of
    out.write, False if it stopped part way."""
    import sounddevice as sd
    import soundfile as sf
    try:
        data, rate = sf.read(path, dtype="float32", always_2d=True)
    except Exception:
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME)
        return
    with sd.OutputStream(samplerate=rate, channels=data.shape[1], dtype="float32") as out:
        if write is None:
            out.write(data)
        elif not write(out, data, rate):
            out.abort()  # what's buffered goes too


def chime(name):
    path = os.path.join(MEDIA_DIR, SOUNDS[name])
    if os.path.exists(path):
        try:
            play(path)
        except Exception as exc:
            print(f"  chime failed: {exc}")


# --------------------------------------------------------------------------- volume
def _endpoint():
    _com()
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    speakers = AudioUtilities.GetSpeakers()
    ep = getattr(speakers, "EndpointVolume", None)
    if ep is None:  # older pycaw hands back the raw device
        from comtypes import CLSCTX_ALL
        ep = ctypes.cast(speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None),
                         ctypes.POINTER(IAudioEndpointVolume))
    return ep


def volume():
    return round(_endpoint().GetMasterVolumeLevelScalar() * 100)


def set_volume(level, unmute=True):
    ep = _endpoint()
    ep.SetMasterVolumeLevelScalar(max(0, min(100, level)) / 100, None)
    if unmute and level > 0:
        ep.SetMute(0, None)


def set_muted(muted):
    _endpoint().SetMute(1 if muted else 0, None)


def _app_audio(app):
    """The app's sessions in the Windows volume mixer, which is how Spotify's own volume is set here."""
    _com()
    from pycaw.pycaw import AudioUtilities
    found = []
    for session in AudioUtilities.GetAllSessions():
        proc = session.Process
        if not proc:
            continue
        try:
            path = proc.exe()
        except Exception:
            path = proc.name()
        if app.matches(path):
            found.append(session)
    if not found:
        raise RuntimeError(f"{app.name} isn't in the volume mixer yet, play something first")
    return found


def app_volume(app):
    return round(_app_audio(app)[0].SimpleAudioVolume.GetMasterVolume() * 100)


def set_app_volume(app, level):
    for session in _app_audio(app):
        session.SimpleAudioVolume.SetMasterVolume(max(0, min(100, level)) / 100, None)


def app_sounding(app):
    """True if the app is playing sound now: its session in the volume mixer runs while it plays and stops when it's
    paused. VLC 3 isn't in Windows' media controls, so this is how to tell it's the one playing."""
    try:
        return any(s.State == 1 for s in _app_audio(app))  # AudioSessionStateActive
    except Exception:
        return False


# --------------------------------------------------------------------------- brightness, Wi-Fi, Bluetooth, mic, output
# From Tomte (github.com/xditya/tomte-windows, MIT, src/Tomte.Core/Device): the laptop screen's brightness through
# WMI, Wi-Fi and Bluetooth through Windows.Devices.Radios, the mic's mute and the sound's output device through Core
# Audio, each straight away. On 25 October "Increase brightness" went to a task in Settings, which pressed Win+A and
# stopped. Tomte says the radios need a packaged app; here, unpackaged, Windows allowed them (access 1, 26 October)
def _wmi():
    _com()
    import comtypes.client
    return comtypes.client.CoGetObject("winmgmts:{impersonationLevel=impersonate}!\\\\.\\root\\wmi", dynamic=True)


def brightness():
    """The built-in screen's brightness, 0 to 100, or None with none Windows can set (an external monitor needs
    DDC/CI, which this doesn't do)."""
    try:
        for m in _wmi().ExecQuery("SELECT CurrentBrightness FROM WmiMonitorBrightness"):
            return int(m.Properties_.Item("CurrentBrightness").Value)
    except Exception:
        return None
    return None


def set_brightness(percent):
    """The built-in screen at percent, 0 to 100. RuntimeError if there's none Windows can set."""
    percent, done = max(0, min(100, int(percent))), False
    try:
        for m in _wmi().ExecQuery("SELECT * FROM WmiMonitorBrightnessMethods"):
            args = m.Methods_.Item("WmiSetBrightness").InParameters.SpawnInstance_()
            args.Properties_.Item("Timeout").Value = 1
            args.Properties_.Item("Brightness").Value = percent
            m.ExecMethod_("WmiSetBrightness", args)
            done = True
    except Exception as exc:
        raise RuntimeError("This screen's brightness isn't one Windows lets me set") from exc
    if not done:
        raise RuntimeError("This screen's brightness isn't one Windows lets me set")


RADIO_PAGES = {"wifi": "ms-settings:network-wifi", "bluetooth": "ms-settings:bluetooth"}


def _radio_call(kind, on=None):
    """kind's radio ("wifi" or "bluetooth"): with on None, True or False for on or off; else set so, True if Windows
    did. None if Windows won't let her, or there's no such radio (an adapter turned off in Device Manager)."""
    _com()
    from winrt.windows.devices.radios import Radio, RadioAccessStatus, RadioKind, RadioState
    want = {"wifi": RadioKind.WI_FI, "bluetooth": RadioKind.BLUETOOTH}[kind]

    async def run():
        if await Radio.request_access_async() != RadioAccessStatus.ALLOWED:
            return None
        radio = next((r for r in await Radio.get_radios_async() if r.kind == want), None)
        if radio is None:
            return None
        if on is None:
            return radio.state == RadioState.ON
        return await radio.set_state_async(RadioState.ON if on else RadioState.OFF) == RadioAccessStatus.ALLOWED
    try:
        return asyncio.run(run())
    except OSError:  # a radio that went away mid-call (a dongle pulled out) raises rather than saying so
        return None


def radio_on(kind):
    """True if Wi-Fi or Bluetooth (kind) is on, False if off, None if she can't tell."""
    return _radio_call(kind)


def set_radio(kind, on):
    """Wi-Fi or Bluetooth (kind) on or off. When Windows won't let her, its Settings page opens instead, as Tomte
    does, and RuntimeError says so."""
    if _radio_call(kind, bool(on)) is not True:
        open_windows_page(RADIO_PAGES[kind])
        raise RuntimeError(f"Windows didn't let me switch {'Wi-Fi' if kind == 'wifi' else 'Bluetooth'}, so I've "
                           f"opened its settings")


def _mic_endpoint():
    _com()
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    mic = AudioUtilities.GetMicrophone()
    if mic is None:
        raise RuntimeError("There's no microphone")
    return ctypes.cast(mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), ctypes.POINTER(IAudioEndpointVolume))


def mic_muted():
    return bool(_mic_endpoint().GetMute())


def set_mic_muted(muted):
    """Mute the default mic for every app (calls too). Her own listening uses it as well, so muted she hears only
    right Alt's push-to-talk if that's on the same mic: say it before, not after."""
    _mic_endpoint().SetMute(1 if muted else 0, None)


def output_devices():
    """[(id, name, is_default)] for the sound outputs that are on: speakers, headphones, a Bluetooth speaker."""
    _com()
    from pycaw.constants import DEVICE_STATE, EDataFlow
    from pycaw.pycaw import AudioUtilities
    try:
        current = AudioUtilities.GetSpeakers().id
    except Exception:
        current = None
    return [(d.id, d.FriendlyName, d.id == current)
            for d in AudioUtilities.GetAllDevices(EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value)
            if d.FriendlyName]


# Windows names an output for what it is and what it's on: "Speakers (Realtek(R) Audio)" is the laptop's own,
# "Speakers (JBL Flip 5)" or "Headphones (Galaxy Buds2 Pro)" a Bluetooth one. These words only say what it is
OUTPUT_KINDS = {"speaker", "speakers", "headphone", "headphones", "headset", "earbud", "earbuds", "earphone",
                "earphones", "audio", "sound", "output", "bluetooth", "stereo", "hands", "free"}
SOUND_CHIP = re.compile(r"realtek|high definition|intel|amd|nvidia|conexant|cirrus|audio device|smart sound", re.I)


def output_name(name):
    """An output as she'd say it: "Speakers" for the laptop's own, "JBL Flip 5" for a Bluetooth speaker."""
    m = re.fullmatch(r"(.+?) \((.+)\)", name.strip())
    return (m[1] if SOUND_CHIP.search(m[2]) else m[2]) if m else name.strip()


def pick_output(devices, name):
    """The one of devices called name: the whole name, else the one that has most of its words, a word that names it
    ("jbl", "buds") over one that only says what it is ("speaker"). LookupError, as she'd say it, for none or for
    more than one as near."""
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower())
             if w not in ("the", "my", "a", "to", "device", "one", "please")]
    if not words:
        raise LookupError("Which speaker or headphones?")
    exact = [d for d in devices if d[1].lower() == name.lower().strip() or output_name(d[1]).lower() == name.lower()]
    if len(exact) == 1:
        return exact[0]

    def score(d):
        have = set(re.findall(r"[a-z0-9]+", d[1].lower()))
        return sum((1 if w in OUTPUT_KINDS else 2) for w in words
                   if w in have or w.rstrip("s") in have or w + "s" in have)
    scored = [(score(d), d) for d in devices]
    best = max((s for s, _ in scored), default=0)
    found = [d for s, d in scored if s == best and s > 0]
    if len(found) == 1:
        return found[0]
    names = " or ".join(output_name(d[1]) for d in (found or devices))
    raise LookupError(f"There's more than one like that: {names}." if found else
                      f"I can't find a sound output called {name}. There's {names}." if devices else
                      "There's no sound output on.")


def set_output(device_id):
    """Sound goes to this output from now on, in every app, as picking it in Quick Settings does."""
    _com()
    from pycaw.constants import ERole
    from pycaw.pycaw import AudioUtilities
    AudioUtilities.SetDefaultDevice(device_id, [ERole.eConsole, ERole.eMultimedia, ERole.eCommunications])


# --------------------------------------------------------------------------- media (Spotify), via Windows media controls
def media_session(app_hint=None):
    """The media session of the app whose id contains app_hint ("spotify"). With no hint, the one Windows shows in
    its media controls: whatever is playing, or played last (YouTube in Chrome, Spotify, VLC). None if there's none."""
    _com()
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager

    async def find():
        manager = await Manager.request_async()
        if app_hint is None:
            return manager.get_current_session()
        for session in manager.get_sessions():
            if app_hint in (session.source_app_user_model_id or "").lower():
                return session
        return None
    return asyncio.run(find())


def media_sessions():
    """Every media session Windows' media controls know of: each tab playing in a browser has its own."""
    _com()
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager

    async def find():
        manager = await Manager.request_async()
        return list(manager.get_sessions())
    return asyncio.run(find())


def media_command(session, command):
    calls = {"play": session.try_play_async, "pause": session.try_pause_async,
             "toggle": session.try_toggle_play_pause_async,
             "next": session.try_skip_next_async, "previous": session.try_skip_previous_async}

    async def run():
        return await calls[command]()
    return asyncio.run(run())


def media_props(session):
    """(title, artist) of what a media session is playing, "" for what it doesn't say. A YouTube video in Chrome is
    its title and its channel."""
    async def get():
        return await session.try_get_media_properties_async()
    try:
        props = asyncio.run(get())
    except Exception:
        return "", ""
    return (props.title or "").strip(), (props.artist or "").strip()


def media_title(session):
    """'Title - Artist' of what a media session is playing, or "" if it doesn't say."""
    title, artist = media_props(session)
    return f"{title} - {artist}" if title and artist else title


def media_playing(session):
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status
    return session.get_playback_info().playback_status == Status.PLAYING


def media_position(session):
    """Seconds into the current track, counting time since Windows last heard from the app."""
    from datetime import datetime, timezone
    timeline = session.get_timeline_properties()
    pos = timeline.position.total_seconds()
    try:
        if media_playing(session) and timeline.last_updated_time:
            pos += (datetime.now(timezone.utc) - timeline.last_updated_time).total_seconds()
    except Exception:
        pass
    return pos


MEDIA_STATUS = {0: "closed", 1: "opened", 2: "changing", 3: "stopped", 4: "playing", 5: "paused"}


def media_status(session):
    """What a media session is doing: "playing", "paused", "stopped", "changing", "opened" or "closed", "" if
    Windows won't say."""
    try:
        return MEDIA_STATUS.get(int(session.get_playback_info().playback_status), "")
    except Exception:
        return ""


def media_length(session):
    """How long what a media session plays is, in seconds, or 0 if it doesn't say."""
    try:
        timeline = session.get_timeline_properties()
        return max(0.0, timeline.end_time.total_seconds() - timeline.start_time.total_seconds())
    except Exception:
        return 0.0


# --------------------------------------------------------------------------- dark mode, lock, sleep
PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def dark_mode():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE) as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False  # never set means light


def light_mode():
    """True if apps and Windows itself (the taskbar, Start) are both in light mode: dark_mode reads only the apps."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE) as key:
            for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                try:
                    if winreg.QueryValueEx(key, name)[0] == 0:
                        return False
                except OSError:
                    pass  # never set means light
    except OSError:
        pass
    return True


def set_dark_mode(on):
    light = 0 if on else 1
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, PERSONALIZE, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, light)
        winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, light)
    # tell the taskbar and open apps to repaint in the new theme. A window that hasn't taken the message when the wait
    # runs out never hears of it and keeps its old colours, and Explorer, repainting many windows, can take more than
    # 2 s: Tomte (Display.cs) waits 5 s, as Microsoft's PowerToys Light Switch does. A hung window is skipped at once
    result = ctypes.c_size_t()
    user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "ImmersiveColorSet", SMTO_ABORTIFHUNG, 5000,
                               ctypes.byref(result))


# --------------------------------------------------------------------------- Night light
# Windows keeps whether Night light is on in the registry, as Bond CompactBinary v1 inside a CloudStore envelope, and
# explorer.exe applies a change there at once, so it's switched as quickly as dark mode, with no Settings window. It
# isn't documented: this is the layout kvnxiao/win-nightlight-cli worked out (docs/nightlight-registry-format.md,
# Windows 11 builds 26100 and 26300; 26200 here is the same). On or off writes only the state value, the way Settings
# and Quick Settings do it. A value laid out any other way is left alone: one Windows can't read could leave it stuck
NIGHT_STATE = "\\".join((r"Software\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount\Current",
                         "default$windows.data.bluelightreduction.bluelightreductionstate",
                         "windows.data.bluelightreduction.bluelightreductionstate"))
BOND = b"CB\x01\x00"  # a marshaled Bond CompactBinary v1 struct
ENVELOPE = BOND + b"\x0a\x02\x01\x00\x2a\x06"  # its metadata (field 0: true), then the payload's timestamp
BT_BOOL, BT_UINT8, BT_UINT64, BT_INT8, BT_INT32 = 2, 3, 6, 14, 16
VARINTS = {4, 5, 6, 15, 16, 17}  # Bond's unsigned and (zigzag) signed integers, 16 to 64 bits
FILETIME_1970 = 11644473600  # seconds from 1601, where a FILETIME counts from, to 1970


def _varint(n):
    out = bytearray()
    while n > 0x7F:
        out.append(n & 0x7F | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _read_varint(data, i):
    n = shift = 0
    while shift < 70:
        b = data[i]
        n, i, shift = n | (b & 0x7F) << shift, i + 1, shift + 7
        if b < 0x80:
            return n, i
    raise ValueError("a number too long")


def _night_split(data):
    """(timestamp, inner payload) out of the state value, or ValueError if it isn't laid out as Windows writes it."""
    data = bytes(data)
    try:
        if not data.startswith(ENVELOPE):
            raise ValueError("not a CloudStore envelope")
        stamp, i = _read_varint(data, len(ENVELOPE))
        if data[i:i + 3] != b"\x2a\x2b\x0e":  # field 1: the data wrapper, with field 1 a list of bytes
            raise ValueError("no payload where it should be")
        size, i = _read_varint(data, i + 3)
    except IndexError:
        raise ValueError("cut short") from None
    inner = data[i:i + size]
    if len(inner) != size or data[i + size:] != b"\x00\x00\x00":
        raise ValueError("more than the payload in it")
    return stamp, inner


def _night_fields(inner):
    """{field: (Bond type, its bytes)} of the inner state, or ValueError for a type it shouldn't have."""
    if not inner.startswith(BOND):
        raise ValueError("not a Bond struct")
    fields, i = {}, len(BOND)
    try:
        while True:
            head = inner[i]
            kind, field, i = head & 0x1F, head >> 5, i + 1
            if not kind:  # BT_STOP
                break
            if field == 6:
                field, i = inner[i], i + 1
            elif field == 7:
                field, i = inner[i] | inner[i + 1] << 8, i + 2
            start = i
            if kind in (BT_BOOL, BT_UINT8, BT_INT8):
                i += 1
            elif kind in VARINTS:
                _, i = _read_varint(inner, i)
            else:
                raise ValueError(f"field {field} is of type {kind}")
            fields[field] = (kind, inner[start:i])
    except IndexError:
        raise ValueError("cut short") from None
    if i != len(inner):
        raise ValueError("more after its end")
    return fields


def _bond_field(field, kind, value):
    head = bytes([field << 5 | kind]) if field <= 5 else bytes([0xC0 | kind, field]) if field <= 0xFF else \
        bytes([0xE0 | kind, field & 0xFF, field >> 8])
    return head + value


def night_light_value(data, on, now=None):
    """The state value data with Night light on or off, as Windows Settings writes it: field 0 there (0, running)
    only when it's on, field 10 = 1 (changed by hand), field 20 = now as a FILETIME, and the envelope's timestamp the
    later of now and 2 s after the one in it, as Windows won't apply one it has seen go by. Fields it doesn't know
    stay as they are, in order."""
    now = time.time() if now is None else now
    stamp, inner = _night_split(data)
    fields = _night_fields(inner)
    if fields.get(30, (BT_BOOL, b"\x01"))[1] == b"\x00":  # usable: false
        raise RuntimeError("Night light isn't available on this screen")
    fields.pop(0, None)
    if on:
        fields[0] = (BT_INT32, b"\x00")
    fields[10] = (BT_INT32, b"\x02")  # zigzag 1
    fields[20] = (BT_UINT64, _varint(int((now + FILETIME_1970) * 10_000_000)))
    inner = BOND + b"".join(_bond_field(f, *fields[f]) for f in sorted(fields)) + b"\x00"
    return ENVELOPE + _varint(max(int(now), stamp + 2)) + b"\x2a\x2b\x0e" + _varint(len(inner)) + inner + b"\x00" * 3


def night_light():
    """True if Night light is on now, False if it's off, None if that can't be told."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NIGHT_STATE) as key:
            return 0 in _night_fields(_night_split(winreg.QueryValueEx(key, "Data")[0])[1])
    except (OSError, ValueError):
        return None


def set_night_light(on):
    """Turns Night light on or off now, as its switch in Quick Settings does, the schedule as it was. False if it
    already was."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NIGHT_STATE, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
            data = winreg.QueryValueEx(key, "Data")[0]
            if (0 in _night_fields(_night_split(data)[1])) == bool(on):
                return False
            winreg.SetValueEx(key, "Data", 0, winreg.REG_BINARY, night_light_value(data, on))
    except FileNotFoundError:
        raise RuntimeError("Night light isn't set up yet: switch it on once in Settings") from None
    except ValueError as exc:
        raise RuntimeError("I can't switch Night light directly on this version of Windows") from exc
    return True


def lock():
    if not user32.LockWorkStation():
        raise RuntimeError("Windows wouldn't lock")


def sleep():
    if not powrprof.SetSuspendState(False, False, False):
        # Modern Standby laptops refuse SetSuspendState, turning the screen off puts those to sleep
        user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2)


def shutdown(delay=10):
    """Initiate a clean Windows shutdown with a grace period (default 10s)."""
    subprocess.Popen(["shutdown.exe", "/s", "/t", str(delay), "/c", "Hey Jev is shutting down the PC."])


def restart(delay=10):
    """Initiate a clean Windows restart with a grace period (default 10s)."""
    subprocess.Popen(["shutdown.exe", "/r", "/t", str(delay), "/c", "Hey Jev is restarting the PC."])


def abort_shutdown():
    """Cancel a pending Windows shutdown or restart."""
    subprocess.Popen(["shutdown.exe", "/a"])


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", DWORD), ("BatteryFullLifeTime", DWORD)]


_sig(kernel32.GetSystemPowerStatus, [ctypes.POINTER(SYSTEM_POWER_STATUS)])


def charging():
    """True while the battery is charging, False when it isn't (on battery, or plugged in and as full as it'll get:
    a Lenovo's conservation mode stops at about 60 percent), None with no battery or when Windows won't say."""
    s = SYSTEM_POWER_STATUS()
    if not kernel32.GetSystemPowerStatus(ctypes.byref(s)) or s.BatteryFlag in (128, 255):
        return None
    return bool(s.BatteryFlag & 8)


DOWNLOADS_ID = "{374DE290-123F-4565-9164-39C4925E467B}"  # the Downloads folder's ID in User Shell Folders


def downloads_folder():
    """Where browsers save what they download unless told otherwise: Windows' Downloads folder, which can be moved
    off C (on Hari's PC it's on D), else the one in the user folder."""
    for key in (r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                path = os.path.expandvars(str(winreg.QueryValueEx(k, DOWNLOADS_ID)[0]))
        except OSError:
            continue
        if os.path.isdir(path):
            return path
    return os.path.join(os.path.expanduser("~"), "Downloads")


# --------------------------------------------------------------------------- apps
def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


@lru_cache(maxsize=512)
def file_description(path):
    """The "File description" Windows shows for an .exe, like "Visual Studio Code" for Code.exe."""
    try:
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, buf):
            return ""
        ptr, length = ctypes.c_void_p(), UINT()
        if not version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)) \
                or length.value < 4:
            return ""
        lang, codepage = struct.unpack("<HH", ctypes.string_at(ptr.value, 4))
        if version.VerQueryValueW(buf, f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription",
                                  ctypes.byref(ptr), ctypes.byref(length)) and length.value:
            return ctypes.wstring_at(ptr.value, length.value).rstrip("\x00")
    except Exception:
        pass
    return ""


class App:
    """An app from apps.json: the name it has in the Start menu, and the .exe its windows belong to."""

    def __init__(self, name, exes=()):
        self.name = name
        self.exes = {e.lower() for e in ([exes] if isinstance(exes, str) else exes or ())}
        words = _norm(name).split()
        self.joined = "".join(words)
        self.words = {w for w in words if len(w) >= 3}

    def matches(self, exe_path):
        if not exe_path:
            return False
        base = os.path.basename(exe_path).lower()
        if base in self.exes:
            return True
        stem = re.sub(r"[^a-z0-9]", "", base[:-4] if base.endswith(".exe") else base)
        # Spotify.exe, chrome.exe for "Google Chrome", Code.exe for "VS Code", and Store apps' own names with
        # Windows or Microsoft in front: WindowsCamera.exe for "Camera" ("Close camera": "Camera isn't running")
        if stem == self.joined or stem in self.words:
            return True
        bare = re.sub(r"^(?:windows|microsoft)", "", stem)  # the whole name only: "Camera Hub" isn't WindowsCamera
        if bare and bare != stem and bare == self.joined:
            return True
        return _norm(file_description(exe_path)).replace(" ", "") == self.joined

    def __repr__(self):
        return f"App({self.name!r}, {sorted(self.exes)})"


_start_apps, _start_lock = None, threading.Lock()


def start_apps(refresh=False):
    """(name, AppID) for everything in the Start menu, which covers normal and Microsoft Store apps."""
    global _start_apps
    with _start_lock:
        if _start_apps is None or refresh:
            script = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
                      "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress")
            try:
                out = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
                                     capture_output=True, text=True, encoding="utf-8", errors="replace",
                                     creationflags=CREATE_NO_WINDOW, timeout=60).stdout
                data = json.loads(out) if out.strip() else []
            except Exception as exc:
                print(f"  couldn't read the Start menu: {exc}")
                data = []
            if isinstance(data, dict):
                data = [data]
            _start_apps = [(d["Name"], d["AppID"]) for d in data if d.get("Name") and d.get("AppID")]
        return _start_apps


def warm_start_apps():
    threading.Thread(target=start_apps, daemon=True).start()


def loaded_start_apps():
    """The Start menu as far as it's been read, without waiting while it's read the first time."""
    return _start_apps or []


def find_start_app(name, refresh=True):
    target, target_norm = name.lower(), _norm(name)
    for again in ((False, True) if refresh else (False,)):  # look again in case it was installed after Jev started
        apps = start_apps(refresh=again)
        for rule in (lambda n: n.lower() == target, lambda n: _norm(n) == target_norm,
                     lambda n: re.search(rf"\b{re.escape(target_norm)}\b", _norm(n))):
            hits = [a for a in apps if rule(a[0])]
            if hits:
                return min(hits, key=lambda a: len(a[0]))  # "Zoom" -> "Zoom Workplace", not something longer
    return None


def launch(name):
    hit = find_start_app(name)
    if hit:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{hit[1]}"], creationflags=CREATE_NO_WINDOW)
        return
    try:
        os.startfile(name)  # last try, anything Windows knows by name, like "notepad"
    except OSError:
        raise RuntimeError(f"Couldn't find {name} in the Start menu")


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _pid(hwnd):
    pid = DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _exe(pid):
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf, size = ctypes.create_unicode_buffer(32768), DWORD(32768)
        return buf.value if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else ""
    finally:
        kernel32.CloseHandle(handle)


def _children(hwnd):
    found = []
    cb = WNDENUMPROC(lambda h, _: found.append(h) or True)
    user32.EnumChildWindows(hwnd, cb, 0)
    return found


def window_exe(hwnd):
    """The .exe a window belongs to. Store apps like Calculator sit inside ApplicationFrameHost, so look one level in."""
    pid = _pid(hwnd)
    exe = _exe(pid)
    if os.path.basename(exe).lower() == "applicationframehost.exe":
        for child in _children(hwnd):
            child_pid = _pid(child)
            if child_pid != pid:
                return _exe(child_pid)
    return exe


def _is_app_window(hwnd):
    if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
        return False
    if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW or not user32.GetWindowTextLengthW(hwnd):
        return False
    cloaked = DWORD()  # suspended Store apps and other virtual desktops
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return not cloaked.value and _class_name(hwnd) not in SHELL_CLASSES


def app_windows(app):
    """The app's windows on screen (minimised ones too), front-most first."""
    found = []
    cb = WNDENUMPROC(lambda h, _: found.append(h) or True)
    user32.EnumWindows(cb, 0)
    return [h for h in found if _is_app_window(h) and app.matches(window_exe(h))]


def open_windows():
    """Every app window on screen, minimised ones too, front-most first: [(hwnd, exe path, title)]."""
    found = []
    cb = WNDENUMPROC(lambda h, _: found.append(h) or True)
    user32.EnumWindows(cb, 0)
    return [(h, window_exe(h), window_title(h)) for h in found if _is_app_window(h)]


def _app_processes(app):
    import psutil
    me = os.getpid()
    out = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        if proc.info["pid"] != me and app.matches(proc.info["exe"] or proc.info["name"] or ""):
            out.append(proc)
    return out


def bring_to_front(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    front = user32.GetForegroundWindow()
    if front == hwnd:
        return
    # Windows stops background apps stealing focus, borrowing the front window's input queue gets round that
    me = kernel32.GetCurrentThreadId()
    other = user32.GetWindowThreadProcessId(front, None) if front else 0
    attached = bool(other and other != me and user32.AttachThreadInput(me, other, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, other, False)
    if user32.GetForegroundWindow() != hwnd:
        user32.SwitchToThisWindow(hwnd, True)


def open_app(app, wait=8.0):
    """Like `open -a`: bring it to the front if it's open, else launch it and wait for its window."""
    windows = app_windows(app)
    if windows:
        bring_to_front(windows[0])
        return
    front = user32.GetForegroundWindow()
    launch(app.name)
    start = time.time()
    while time.time() - start < wait:
        time.sleep(0.2)
        if app_windows(app):
            return
        now = user32.GetForegroundWindow()  # web apps like YouTube run as chrome.exe, so their windows never match
        if now and now != front and _is_app_window(now):  # a new window came to the front, that's it
            return


def focus_app(app):
    windows = app_windows(app)
    if not windows:
        return open_app(app)  # AppleScript's activate launches it too
    bring_to_front(windows[0])


def minimise_app(app):
    windows = app_windows(app)
    if not windows:
        raise RuntimeError(f"{app.name} has no windows open")
    for hwnd in windows:
        user32.ShowWindow(hwnd, SW_MINIMIZE)


def quit_app(app):
    windows, procs = app_windows(app), _app_processes(app)
    if not windows and not procs:
        raise RuntimeError(f"{app.name} isn't running")
    refused = 0
    for hwnd in windows:  # same as clicking X, so apps still get to ask about unsaved work
        if not user32.PostMessageW(hwnd, WM_CLOSE, 0, 0) and ctypes.get_last_error() == 5:
            refused += 1  # access denied: Windows keeps apps that run as administrator, like Task Manager, out of reach
    if windows and refused == len(windows):
        raise RuntimeError(f"Windows won't let me close {app.name}, it runs as administrator")
    deadline = time.time() + 4
    while windows and time.time() < deadline:
        time.sleep(0.25)
        windows = app_windows(app)
    if windows:  # something's still open, maybe a "save changes?" prompt, so that's up to you
        raise RuntimeError(f"{app.name} is still open, it may be asking you to save something")
    import psutil
    procs = [p for p in _app_processes(app)
             if os.path.basename(p.info["exe"] or p.info["name"] or "").lower() not in PROTECTED]
    _, alive = psutil.wait_procs(procs, timeout=4)  # give it a moment to close by itself
    for proc in alive:  # Spotify, Slack, Discord and co only drop to the tray, quit means quit
        try:
            proc.kill()
        except psutil.Error:
            pass


def front_window():
    """The window in front, or None."""
    return user32.GetForegroundWindow() or None


def shown(hwnd):
    """True if hwnd is a window that's still there and showing."""
    return bool(hwnd) and bool(user32.IsWindow(hwnd)) and bool(user32.IsWindowVisible(hwnd))


def foreground_exe():
    hwnd = user32.GetForegroundWindow()
    return window_exe(hwnd) if hwnd else ""


def window_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def app_path(exe):
    """Full path of a program Windows has under App Paths, like chrome.exe or msedge.exe, or None."""
    sub = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, sub) as key:
                path = os.path.expandvars(str(winreg.QueryValueEx(key, "")[0]).strip('"'))
        except OSError:
            continue
        if os.path.isfile(path):
            return path
    return None


def front_title():
    """The title of the window in front, like "lofi music - YouTube - Google Chrome"."""
    hwnd = user32.GetForegroundWindow()
    return window_title(hwnd) if hwnd else ""


# --------------------------------------------------------------------------- calls
# Windows keeps which apps use the mic, for the mic icon on the taskbar: a key per app under ConsentStore\microphone,
# with LastUsedTimeStop 0 while it's in use. Only apps that mean a conversation count, never Voicemeeter, which can
# hold the mic all day, or Hey Jev itself, which is python. (in the key's name, in the running program's name, name)
CALL_APPS = (("whatsapp", "whatsapp", "WhatsApp"), ("msteams", "teams", "Teams"), ("teams", "teams", "Teams"),
             ("yourphone", "phoneexperiencehost", "Phone Link"), ("zoom", "zoom", "Zoom"),
             ("discord", "discord", "Discord"), ("skype", "skype", "Skype"), ("slack", "slack", "Slack"),
             ("telegram", "telegram", "Telegram"), ("signal", "signal", "Signal"), ("webex", "webex", "Webex"),
             ("chrome.exe", "chrome", "Chrome"), ("msedge.exe", "msedge", "Edge"), ("brave.exe", "brave", "Brave"),
             ("firefox.exe", "firefox", "Firefox"), ("comet.exe", "comet", "Comet"))
_MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
_calls = {"at": 0.0, "apps": ()}


def _mic_users():
    """The names of the mic keys of apps using the mic right now, lower case."""
    found = []
    for sub in (_MIC_KEY, _MIC_KEY + r"\NonPackaged"):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub)
        except OSError:
            continue
        with key:
            for i in range(1000):
                try:
                    name = winreg.EnumKey(key, i)
                except OSError:
                    break
                try:
                    with winreg.OpenKey(key, name) as app:
                        start = winreg.QueryValueEx(app, "LastUsedTimeStart")[0]
                        stop = winreg.QueryValueEx(app, "LastUsedTimeStop")[0]
                except OSError:
                    continue
                if start and not stop:
                    found.append(name.lower())
    return found


def call_apps(max_age=2.0):
    """The apps that mean a call, WhatsApp, Teams, Zoom or a browser for Meet, that have the mic open right now, read
    again at most every max_age seconds. Each one's program has to be running too: a crash can leave the key saying
    in use."""
    if time.time() - _calls["at"] < max_age:
        return _calls["apps"]
    apps = []
    try:
        users = _mic_users()
        hits = [(proc, label) for key, proc, label in CALL_APPS if any(key in u for u in users)]
        if hits:
            import psutil
            running = {(p.info["name"] or "").lower() for p in psutil.process_iter(["name"])}
            apps = [label for proc, label in hits if any(proc in r for r in running)]
    except Exception:
        apps = []
    _calls.update(at=time.time(), apps=tuple(dict.fromkeys(apps)))
    return _calls["apps"]


def front_app_name():
    """The app in front by name, like "Google Chrome", so "close it" or "scroll down" make sense to the planner."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd or _pid(hwnd) == os.getpid():
        return ""  # nothing, or Jev's own window
    exe = window_exe(hwnd)
    return (file_description(exe) or os.path.splitext(os.path.basename(exe))[0]) if exe else ""


def scroll(clicks):
    """Turn the mouse wheel over the window in front, then put the pointer back. clicks > 0 scrolls up.
    The wheel, not Page Down, since keys go to the YouTube player and Home there jumps to the start of the video."""
    from pynput.mouse import Controller
    hwnd, rect = user32.GetForegroundWindow(), RECT()
    if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("There's no window in front to scroll")
    mouse = Controller()
    back = mouse.position
    mouse.position = ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
    try:
        for _ in range(abs(clicks)):
            mouse.scroll(0, 1 if clicks > 0 else -1)
            time.sleep(0.01)
        time.sleep(0.05)
    finally:
        mouse.position = back


def default_browser_progid():
    base = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https"
    for sub in ("UserChoiceLatest", "UserChoice"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{base}\\{sub}") as key:
                return winreg.QueryValueEx(key, "ProgId")[0]
        except OSError:
            continue
    return ""


def open_url(url, app=None):
    """Open a website, in a given browser if there is one, otherwise in the default browser. Web addresses only, with
    quotes, spaces and control characters percent-encoded: a quote in a planned address ended the quoted argument
    below, and the rest went to the browser as switches (Electron's CVE-2018-1000006 trick)."""
    url = quote(str(url or "").strip(), safe=":/?#[]@!$&'()*+,;=%~")
    if not re.match(r"https?://", url, re.I):  # never a file or a program, which os.startfile would run
        raise RuntimeError("I only open web addresses")
    if app:
        windows = app_windows(app)
        exe = window_exe(windows[0]) if windows else ""
        if exe:
            subprocess.Popen([exe, url], creationflags=CREATE_NO_WINDOW)
            return
        for name in sorted(app.exes):  # chrome.exe, msedge.exe, brave.exe and firefox.exe are registered by name
            try:
                os.startfile(name, arguments=f'"{url}"')
                return
            except OSError:
                continue
    os.startfile(url)


# --------------------------------------------------------------------------- keyboard and clipboard
def press(*names):
    """press("ctrl", "t"), with every key but the last held down."""
    from pynput.keyboard import Controller, Key
    keyboard = Controller()
    keys = [getattr(Key, n) if len(n) > 1 else n for n in names]
    for key in keys[:-1]:
        keyboard.press(key)
    try:
        keyboard.press(keys[-1])
        keyboard.release(keys[-1])
    finally:
        for key in reversed(keys[:-1]):
            keyboard.release(key)


def type_text(text, chunk=24, gap=0.02):
    """Type it on the keyboard, in small runs, leaving the clipboard alone.

    Line breaks are dropped on purpose: in a chat box Enter is send, and nothing here may send anything."""
    from pynput.keyboard import Controller
    keyboard = Controller()
    typed = "".join(c for c in str(text or "") if c.isprintable())
    for i in range(0, len(typed), chunk):
        keyboard.type(typed[i:i + chunk])
        time.sleep(gap)
    return len(typed)


def set_clipboard(text):
    data = text.encode("utf-16-le") + b"\x00\x00"
    for _ in range(20):  # another app may have it open for a moment
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Couldn't open the clipboard")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(13, handle):  # CF_UNICODETEXT, Windows owns the memory from here
            kernel32.GlobalFree(handle)
            raise RuntimeError("Couldn't write to the clipboard")
    finally:
        user32.CloseClipboard()


_sig(user32.GetClipboardData, [UINT], wintypes.HANDLE)
_sig(user32.IsClipboardFormatAvailable, [UINT])


def clipboard_text():
    """The text on the clipboard, or None if there's none (or a picture or files instead)."""
    if not user32.IsClipboardFormatAvailable(13) or not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        ptr = kernel32.GlobalLock(handle) if handle else None
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


_sig(user32.EnumClipboardFormats, [UINT], UINT)
_sig(user32.GetClipboardSequenceNumber, [], DWORD)
_sig(kernel32.GlobalSize, [ctypes.c_void_p], ctypes.c_size_t)
_sig(user32.FindWindowExW, [HWND, HWND, wintypes.LPCWSTR, wintypes.LPCWSTR], HWND)
GDI_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}  # bitmaps, metafiles, palettes: handles, not memory to copy


def clipboard_snapshot():
    """Everything on the clipboard, format by format, to put back after borrowing it: text, a picture, files, and
    the marks a password manager adds so Windows keeps it out of clipboard history. [] if it's empty or busy."""
    for _ in range(20):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return []
    out = []
    try:
        fmt = user32.EnumClipboardFormats(0)
        while fmt:
            if fmt not in GDI_FORMATS:  # Windows makes CF_BITMAP again from the CF_DIB beside it
                handle = user32.GetClipboardData(fmt)
                size = kernel32.GlobalSize(handle) if handle else 0
                ptr = kernel32.GlobalLock(handle) if size else None
                if ptr:
                    try:
                        out.append((fmt, ctypes.string_at(ptr, size)))
                    finally:
                        kernel32.GlobalUnlock(handle)
            fmt = user32.EnumClipboardFormats(fmt)
    finally:
        user32.CloseClipboard()
    return out


def clipboard_restore(snapshot):
    """Puts back what clipboard_snapshot took, or empties the clipboard if it was empty."""
    for _ in range(20):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Couldn't open the clipboard")
    try:
        user32.EmptyClipboard()
        for fmt, data in snapshot:
            handle = kernel32.GlobalAlloc(0x0042, max(1, len(data)))
            ptr = kernel32.GlobalLock(handle)
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(fmt, handle):
                kernel32.GlobalFree(handle)
    finally:
        user32.CloseClipboard()


def clipboard_sequence():
    """A number Windows moves on at every change to the clipboard."""
    return user32.GetClipboardSequenceNumber()


def set_clipboard_files(paths):
    """Files on the clipboard, as File Explorer's Copy puts them (CF_HDROP), so Ctrl+V pastes them into a chat."""
    files = ("\0".join(str(p) for p in paths) + "\0\0").encode("utf-16-le")
    # DROPFILES: where the names start (20 bytes on), a point and a flag nobody reads, and wide names
    data = (20).to_bytes(4, "little") + bytes(12) + (1).to_bytes(4, "little") + files
    for _ in range(20):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Couldn't open the clipboard")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0042, len(data))  # GMEM_MOVEABLE | GMEM_ZEROINIT
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(15, handle):  # CF_HDROP
            kernel32.GlobalFree(handle)
            raise RuntimeError("Couldn't put the files on the clipboard")
    finally:
        user32.CloseClipboard()


def selected_files():
    """The files selected in the File Explorer window in front, as full paths: [] if none are, or another app is in
    front. Folders aren't files."""
    front = user32.GetForegroundWindow()
    if not front or _class_name(front) != "CabinetWClass":
        return []
    _com()
    import comtypes.client
    shell = comtypes.client.CreateObject("Shell.Application", dynamic=True)
    windows, tabs = shell.Windows(), []
    for i in range(windows.Count):
        try:
            window = windows.Item(i)
            if window is not None and int(window.HWND) == front:
                tabs.append(window)  # each tab of a Windows 11 File Explorer window is one, all with its handle
        except Exception:
            continue
    if len(tabs) > 1:  # the tab in front: the window's title is its name ("Downloads - File Explorer")
        title = window_title(front)
        tabs = [t for t in tabs if title.startswith(str(t.LocationName) + " - ") or title == str(t.LocationName)]
        if len(tabs) != 1:
            raise RuntimeError("I can't tell which File Explorer tab you mean. Select the file in a window with one tab")
    for window in tabs:
        try:
            items = window.Document.SelectedItems()
            paths = [items.Item(j).Path for j in range(items.Count)]
            return [p for p in paths if os.path.isfile(p)]
        except Exception:
            continue
    return []


def paste(text):
    set_clipboard(text)  # stays on the clipboard too, in case the paste misses
    time.sleep(0.2)
    press("ctrl", "v")


# --------------------------------------------------------------------------- push to talk on right Alt
VK_RMENU, LLKHF_INJECTED = 0xA5, 0x10
WM_KEYDOWN, WM_SYSKEYDOWN = 0x100, 0x104


def start_ptt_listener(on_press, on_release):
    """Hold right Alt to talk. The key is swallowed, so the app in front doesn't open its menu when you let go.
    Both callbacks run inside the keyboard hook, so they must return straight away."""
    from pynput import keyboard
    held = [False]

    def event_filter(msg, data):
        if data.vkCode != VK_RMENU or data.flags & LLKHF_INJECTED:
            return True
        down = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
        if down != held[0]:  # holding a key repeats key-down, only act on the change
            held[0] = down
            (on_press if down else on_release)()
        listener.suppress_event()

    listener = keyboard.Listener(win32_event_filter=event_filter)
    listener.daemon = True
    listener.start()
    return listener


# --------------------------------------------------------------------------- microphones
def _is_mapper(name):
    return name.startswith(("Microsoft Sound Mapper", "Primary Sound Capture"))


def input_devices():
    """Mics on the default audio API, so each one is listed once (Windows lists them under up to four APIs)."""
    import sounddevice as sd
    try:
        api = sd.query_hostapis(sd.default.hostapi)
    except Exception:
        return []
    names = []
    for index in api["devices"]:
        dev = sd.query_devices(index)
        if dev["max_input_channels"] > 0 and not _is_mapper(dev["name"]) and dev["name"] not in names:
            names.append(dev["name"])
    return names


LOOPBACK = re.compile(r"stereo mix|what u hear|wave out|loopback", re.I)  # records what the PC plays, not your voice


def auto_input():
    """(index, name) of the mic to use when none is picked: Windows' default, unless that's Stereo Mix."""
    default = default_input_name()
    if not LOOPBACK.search(default):
        return None, default
    for name in input_devices():
        if not LOOPBACK.search(name):
            return input_device(name), name
    return None, default


def input_device(name):
    """sounddevice index for a mic name from input_devices(), or None if it's gone."""
    import sounddevice as sd
    if not name:
        return None
    try:
        for index in sd.query_hostapis(sd.default.hostapi)["devices"]:
            dev = sd.query_devices(index)
            if dev["name"] == name and dev["max_input_channels"] > 0:
                return index
    except Exception:
        pass
    return None


def speech_input(name=""):
    """(index, full name) of a mic on WASAPI, the audio API where Windows can take what the PC is playing out of the
    mic. name is one from input_devices(), which cuts names at 31 characters, or "" for the automatic one."""
    import sounddevice as sd
    name = (name if input_device(name) is not None else auto_input()[1]).strip()
    try:
        api = next(i for i, a in enumerate(sd.query_hostapis()) if "WASAPI" in a["name"])
        for index in sd.query_hostapis(api)["devices"]:
            dev = sd.query_devices(index)
            if dev["max_input_channels"] > 0 and dev["name"].startswith(name) and not LOOPBACK.search(dev["name"]):
                return index, dev["name"]
    except Exception:
        pass
    return None


def default_input_name():
    import sounddevice as sd
    try:
        return sd.query_devices(kind="input")["name"]
    except Exception:
        return "none found"


# --------------------------------------------------------------------------- window helpers for the UI
def prepare_gui(app_id="HeyJev.App"):
    """Sharp text on high-DPI screens, and a taskbar button of our own instead of Python's."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
    except Exception:
        pass


_mutex = []


def single_instance(name="HeyJevSingleInstance"):
    """False if Jev is already running, the way a Mac app only ever opens once."""
    handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
    already = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    _mutex.append(handle)
    return not already


def show_existing(title):
    hwnd = user32.FindWindowW("TkTopLevel", title)
    if hwnd:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
    return bool(hwnd)


def root_hwnd(widget_id):
    return user32.GetAncestor(widget_id, GA_ROOT)


def make_overlay(hwnd):
    """Clicks go through, never takes focus, not in the taskbar or Alt+Tab."""
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
                          | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)


def show_no_activate(hwnd, x, y, w, h):
    user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)


def set_click_through(hwnd, on):
    """Clicks go through the overlay to what's under it (on), or it takes them, as the island does while you point
    at its buttons. It never takes the focus either way."""
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    new = (style | WS_EX_TRANSPARENT) if on else (style & ~WS_EX_TRANSPARENT)
    if new != style:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new)


_sig(user32.GetCursorPos, [ctypes.POINTER(wintypes.POINT)])


def cursor_pos():
    """Where the mouse is, in real pixels."""
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def hide_window(hwnd):
    user32.ShowWindow(hwnd, SW_HIDE)


# --------------------------------------------------------------------------- signing in and coming back
wtsapi32 = ctypes.WinDLL("wtsapi32")
_sig(wtsapi32.WTSQuerySessionInformationW, [wintypes.HANDLE, DWORD, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
                                             ctypes.POINTER(DWORD)])
_sig(wtsapi32.WTSFreeMemory, [ctypes.c_void_p], None)


class _Session(ctypes.Structure):  # WTSINFOEXW at level 1, as far as the lock flag
    _fields_ = [("level", DWORD), ("_pad", DWORD), ("id", ctypes.c_ulong), ("state", ctypes.c_int),
                ("flags", ctypes.c_long)]


def session_locked():
    """True while the lock screen is up, False when you're at the desktop, None if Windows won't say."""
    buf, size = ctypes.c_void_p(), DWORD()
    if not wtsapi32.WTSQuerySessionInformationW(None, 0xFFFFFFFF, 25, ctypes.byref(buf), ctypes.byref(size)):
        return None  # 25 is WTSSessionInfoEx, 0xFFFFFFFF this session
    try:
        return {0: True, 1: False}.get(_Session.from_address(buf.value).flags)
    finally:
        wtsapi32.WTSFreeMemory(buf)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # what starts when you sign in, also in Task Manager


def startup_command():
    """The venv's pythonw.exe running app.py, so no console flashes up, with --startup so it knows why it started."""
    here = os.path.dirname(os.path.abspath(__file__))
    exe = os.path.join(here, ".venv", "Scripts", "pythonw.exe")
    return f'"{exe if os.path.exists(exe) else sys.executable}" "{os.path.join(here, "app.py")}" --startup'


def starts_with_windows(name="Hey Jev"):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return bool(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return False


def set_start_with_windows(on, name="Hey Jev"):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if on:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


# --------------------------------------------------------------------------- the screen, for vision mode
gdi32 = ctypes.WinDLL("gdi32")
_sig(user32.GetDC, [HWND], wintypes.HDC)
_sig(user32.ReleaseDC, [HWND, wintypes.HDC], ctypes.c_int)
_sig(user32.SetWindowDisplayAffinity, [HWND, DWORD])
_sig(user32.WindowFromPoint, [wintypes.POINT], HWND)
_sig(dwmapi.DwmFlush, [], ctypes.c_long)
_sig(gdi32.CreateCompatibleDC, [wintypes.HDC], wintypes.HDC)
_sig(gdi32.CreateCompatibleBitmap, [wintypes.HDC, ctypes.c_int, ctypes.c_int], wintypes.HBITMAP)
_sig(gdi32.SelectObject, [wintypes.HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ)
_sig(gdi32.BitBlt, [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int,
                    ctypes.c_int, DWORD])
_sig(gdi32.GetDIBits, [wintypes.HDC, wintypes.HBITMAP, UINT, UINT, ctypes.c_void_p, ctypes.c_void_p, UINT], ctypes.c_int)
_sig(gdi32.DeleteObject, [wintypes.HGDIOBJ])
_sig(gdi32.DeleteDC, [wintypes.HDC])


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", DWORD), ("biWidth", LONG), ("biHeight", LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", DWORD), ("biSizeImage", DWORD),
                ("biXPelsPerMeter", LONG), ("biYPelsPerMeter", LONG), ("biClrUsed", DWORD), ("biClrImportant", DWORD)]


try:  # Windows 10 1607 and later
    _sig(user32.SetThreadDpiAwarenessContext, [ctypes.c_void_p], ctypes.c_void_p)
    _set_dpi_context = user32.SetThreadDpiAwarenessContext
except AttributeError:
    _set_dpi_context = None
NO_CAPTURE = []  # windows left out of screenshots, like the popup (bubble.py adds it)


@contextlib.contextmanager
def _real_pixels():
    """Positions in real pixels on this thread while inside, whatever the display scaling, so a screenshot and a
    click agree on where things are."""
    old = _set_dpi_context(ctypes.c_void_p(-4)) if _set_dpi_context else None  # per monitor, version 2
    try:
        yield
    finally:
        if old:
            _set_dpi_context(ctypes.c_void_p(old))


def screenshot():
    """The screen the window in front is on: (height, width, 3) RGB as a numpy array, and where that screen is,
    (left, top, right, bottom) in real pixels. Windows in NO_CAPTURE, like the popup, are left out."""
    import numpy as np
    hidden = [hw for hw in NO_CAPTURE if user32.SetWindowDisplayAffinity(hw, 0x11)]  # WDA_EXCLUDEFROMCAPTURE
    try:
        if hidden:  # a frame or two for Windows to draw the screen without them
            dwmapi.DwmFlush()
            dwmapi.DwmFlush()
        with _real_pixels():
            monitor = user32.MonitorFromWindow(user32.GetForegroundWindow(), MONITOR_DEFAULTTOPRIMARY)
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                raise RuntimeError("I couldn't find the screen")
            r = info.rcMonitor
            left, top, w, h = r.left, r.top, r.right - r.left, r.bottom - r.top
            screen = user32.GetDC(None)
            mem = gdi32.CreateCompatibleDC(screen)
            bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
            old = gdi32.SelectObject(mem, bmp)
            try:
                buf = ctypes.create_string_buffer(w * h * 4)
                bits = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h, biPlanes=1,
                                        biBitCount=32)  # top row first: blue, green, red and a spare byte a pixel
                if not gdi32.BitBlt(mem, 0, 0, w, h, screen, left, top, 0x00CC0020) or \
                        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bits), 0) != h:
                    raise RuntimeError("I couldn't take a screenshot")
            finally:
                gdi32.SelectObject(mem, old)
                gdi32.DeleteObject(bmp)
                gdi32.DeleteDC(mem)
                user32.ReleaseDC(None, screen)
    finally:
        for hw in hidden:
            user32.SetWindowDisplayAffinity(hw, 0)
    return np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, 2::-1].copy(), (left, top, left + w, top + h)


PW_RENDERFULLCONTENT = 2  # what a browser or an app drawn by DirectComposition shows too, not a black box
_sig(user32.PrintWindow, [HWND, wintypes.HDC, UINT])


def window_image(hwnd):
    """One window as it looks, even behind others, from the window itself (PrintWindow), not the screen: (height,
    width, 3) RGB. None if it's gone or minimised, or Windows wouldn't draw it. For a watch on a window you're not
    looking at (watchers.py), so nothing else on the screen is in it."""
    import numpy as np
    if not hwnd or not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        return None
    with _real_pixels():
        r = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        w, h = r.right - r.left, r.bottom - r.top
        if w < 8 or h < 8:
            return None
        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
        old = gdi32.SelectObject(mem, bmp)
        try:
            buf = ctypes.create_string_buffer(w * h * 4)
            bits = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h, biPlanes=1,
                                    biBitCount=32)
            if not user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT) or \
                    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bits), 0) != h:
                return None
        finally:
            gdi32.SelectObject(mem, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(None, screen)
    rgb = np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, 2::-1]
    return None if not rgb.any() else rgb.copy()  # all black: it wouldn't draw itself


def window_at(x, y):
    """The .exe of the window at a point on the screen, in real pixels, or ""."""
    hwnd = root_at(x, y)
    return window_exe(hwnd) if hwnd else ""


def root_at(x, y):
    """The top-level window at a point on the screen, in real pixels, or None."""
    with _real_pixels():
        hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    return user32.GetAncestor(hwnd, GA_ROOT) if hwnd else None


def owner_of(hwnd):
    """The app window a window is part of: itself, or for a dialog, a menu or a list that dropped down from it, the
    window that owns it. None for none."""
    return user32.GetAncestor(hwnd, GA_ROOTOWNER) if hwnd else None


def front_area():
    """Where the window in front is, (left, top, right, bottom) in real pixels, with what's open from it, which can
    reach outside it: its dialogs, and the menus and lists that dropped down from it (owner_of), and a menu (#32768).
    None if there's no window in front. vision.capture cuts the task's picture to it."""
    front = user32.GetForegroundWindow()
    if not front:
        return None
    root, boxes = owner_of(front), []

    def visit(hwnd, _):
        if hwnd == front or (user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd) and
                             (owner_of(hwnd) == root or _class_name(hwnd) == "#32768")):
            rect = RECT()  # without the invisible border Windows 10 and 11 put round a window to resize it by
            if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect),
                                            ctypes.sizeof(rect)) == 0 or user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                if rect.right > rect.left and rect.bottom > rect.top:
                    boxes.append((rect.left, rect.top, rect.right, rect.bottom))
        return True
    with _real_pixels():
        user32.EnumWindows(WNDENUMPROC(visit), 0)
    if not boxes:
        return None
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def window_exists(hwnd):
    """True if hwnd is still a window: Outlook's new mail closes once it's sent, a dialog in front of it doesn't."""
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def minimised(hwnd):
    """True if the window is minimised to the taskbar."""
    return bool(hwnd) and bool(user32.IsIconic(hwnd))


def click(x, y, button="left", double=False):
    """Click at a point on the screen, in real pixels. The pointer stays there, as if you'd clicked."""
    from pynput.mouse import Button, Controller
    mouse = Controller()
    with _real_pixels():
        mouse.position = (int(x), int(y))
        time.sleep(0.08)  # menus and buttons react to the pointer coming over them
        mouse.click(Button.right if button == "right" else Button.left, 2 if double else 1)


def work_area():
    """(left, top, right, bottom) of the screen you're working on, minus the taskbar."""
    monitor = user32.MonitorFromWindow(user32.GetForegroundWindow(), MONITOR_DEFAULTTOPRIMARY)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return 0, 0, 1920, 1040
    r = info.rcWork
    return r.left, r.top, r.right, r.bottom


# --------------------------------------------------------------------------- Native Windows Speech Synthesis (OneCore / SAPI5)
def native_voices():
    """Discover available Windows built-in voices (OneCore natural voices and SAPI5 desktop voices).
    Returns [(id, description, is_onecore)]. Costs 0 MB RAM."""
    voices = []
    # 1. OneCore voices (natural Windows 10/11 voices)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens") as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                sub = winreg.EnumKey(k, i)
                try:
                    with winreg.OpenKey(k, sub) as sk:
                        desc = winreg.QueryValueEx(sk, "")[0]
                        voices.append((f"onecore:{sub}", desc, True))
                except OSError:
                    pass
    except OSError:
        pass
    # 2. SAPI5 desktop voices
    try:
        _com()
        import comtypes.client
        v = comtypes.client.CreateObject("SAPI.SpVoice")
        count = v.GetVoices().Count
        for i in range(count):
            desc = v.GetVoices().Item(i).GetDescription()
            sid = v.GetVoices().Item(i).Id
            voices.append((f"sapi:{sid}", desc, False))
    except Exception:
        pass
    return voices


_native_voice_cache = {}


def get_native_spvoice(voice_id=None):
    """Reuse cached SAPI.SpVoice object per thread for sub-10ms speech start. Per thread, since a COM object made on
    one thread mustn't be used from another."""
    _com()
    import comtypes.client
    key = (threading.get_ident(), str(voice_id or ""))
    if key in _native_voice_cache:
        return _native_voice_cache[key]
    v = comtypes.client.CreateObject("SAPI.SpVoice")
    if voice_id and str(voice_id).startswith("onecore:"):
        token_name = voice_id[len("onecore:"):]
        try:
            tok = comtypes.client.CreateObject("SAPI.SpObjectToken")
            tok.SetId(rf"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\{token_name}")
            v.Voice = tok
        except Exception:
            pass
    elif voice_id and str(voice_id).startswith("sapi:"):
        token_id = voice_id[len("sapi:"):]
        try:
            tok = comtypes.client.CreateObject("SAPI.SpObjectToken")
            tok.SetId(token_id)
            v.Voice = tok
        except Exception:
            pass
    else:
        # Default to best natural OneCore voice available (Heera, Ravi, Mark, Zira, David)
        for cand in ("MSTTS_V110_enIN_HeeraM", "MSTTS_V110_enIN_RaviM", "MSTTS_V110_enUS_MarkM",
                     "MSTTS_V110_enUS_ZiraM", "MSTTS_V110_enUS_DavidM"):
            try:
                tok = comtypes.client.CreateObject("SAPI.SpObjectToken")
                tok.SetId(rf"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\{cand}")
                v.Voice = tok
                break
            except Exception:
                pass
    _native_voice_cache[key] = v
    return v


def speak_native(text, voice=None, voice_id=None, wait=True, stop=None):
    """Speak text using Windows native OneCore / SAPI5 voice. 0 MB added RAM, < 15ms latency. stop(): True to stop
    part way, checked every 50 ms (the voice is this thread's, so only this thread can stop it)."""
    v = get_native_spvoice(voice or voice_id)
    if stop is None or not wait:
        v.Speak(str(text or ""), 0 if wait else 1)
        return
    v.Speak(str(text or ""), 1)  # SVSFlagsAsync
    while not v.WaitUntilDone(50):
        if stop():
            v.Speak("", 3)  # SVSFPurgeBeforeSpeak | async: what it was saying stops
            return


def native_to_wav(text, wav_path, voice=None, voice_id=None):
    """Render speech to WAV file via native Windows TTS in ~20ms, 0 MB added RAM."""
    _com()
    import comtypes.client
    v = get_native_spvoice(voice or voice_id)
    fs = comtypes.client.CreateObject("SAPI.SpFileStream")
    fs.Open(wav_path, 3, False)
    v.AudioOutputStream = fs
    try:
        v.Speak(str(text or ""), 0)
    finally:
        fs.Close()
        v.AudioOutputStream = None


# --------------------------------------------------------------------------- Fast UI Automation Element Inspection
# Buttons the fast path never presses: the vision path, with its own rules, decides those
RISKY_CLICKS = re.compile(r"\b(?:send|delete|remove|erase|buy|pay|purchase|order|checkout|post|publish|submit|sign ?out|"
                          r"log ?out|uninstall|format|reset|discard|unsubscribe|transfer|confirm|allow|accept|install)\b")


def find_and_click_ui_element(target_name, hwnd=None):
    """Click a button, link, menu item, tab or list item in the window in front whose name is exactly target_name, in
    about 40 ms instead of a screenshot and the model. Only when exactly one visible, enabled element has that name;
    anything vaguer, or a risky button like Send or Delete, returns False so vision mode handles it."""
    clean = " ".join(str(target_name or "").lower().split())
    if not clean or RISKY_CLICKS.search(clean):
        return False
    _com()
    hwnd = hwnd or user32.GetForegroundWindow()
    if not hwnd:
        return False
    try:
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
        uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
        root = uia.ElementFromHandle(hwnd)
        if not root:
            return False
        hits = []
        for ctype in (50000, 50005, 50011, 50019, 50007):  # button, hyperlink, menu item, tab item, list item
            found = root.FindAll(4, uia.CreatePropertyCondition(30003, ctype))
            if not found:
                continue
            for i in range(min(200, found.Length)):
                el = found.GetElement(i)
                if " ".join((el.CurrentName or "").lower().split()) != clean:
                    continue
                if el.CurrentIsOffscreen or not el.CurrentIsEnabled:
                    continue
                rect = el.CurrentBoundingRectangle
                if rect.right > rect.left and rect.bottom > rect.top:
                    hits.append(rect)
        if len(hits) != 1:  # none, or more than one with that name: let vision work out which
            return False
        rect = hits[0]
        click((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        return True
    except Exception as exc:
        print(f"  uia element click failed: {exc!r}")
    return False


# --------------------------------------------------------------------------- UI Automation for her own procedures
# What agent.py reads and presses: controls found by their name and role, never by where they are on the screen, so a
# button that moved is still found and one that's gone is never pressed by mistake. Each call to UI Automation has a
# time limit, so a slow or hung app makes it give up instead of holding her up, and no extra threads are needed.
_ui = threading.local()  # this thread's UI Automation: a COM object made on one thread mustn't be used from another
ROLES = {"button": 50000, "checkbox": 50002, "combobox": 50003, "edit": 50004, "link": 50005, "listitem": 50007,
         "menuitem": 50011, "radio": 50013, "tab": 50019, "document": 50030}
ROLE_OF = {v: k for k, v in ROLES.items()}
UIA_LIMIT = 800  # ms one UI Automation call may take, then it raises
BROWSER_EXES = {"chrome.exe", "msedge.exe", "brave.exe"}
OMNIBOX = "Address and search bar"  # the address bar's name in Chrome, Edge and Brave
# Direction marks and a shortcut hint on the end of a name: Gmail's Send button is "Send \u202a(Ctrl-Enter)\u202c"
BIDI = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
SHORTCUT_HINT = re.compile(r"\s*\((?:ctrl|control|alt|shift|win|cmd)\s*[-+][^()]*\)$", re.I)
_sleep, _clock = time.sleep, time.monotonic  # swapped for a fake clock in the tests, so polling takes no time


def uia():
    """This thread's UI Automation (CUIAutomation8, made once a thread), every call limited to UIA_LIMIT."""
    got = getattr(_ui, "uia", None)
    if got is None:
        _com()
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen.UIAutomationClient import CUIAutomation8, IUIAutomation2
        got = comtypes.client.CreateObject(CUIAutomation8, interface=IUIAutomation2)
        got.TransactionTimeout = got.ConnectionTimeout = UIA_LIMIT
        _ui.uia = got
    return got


def clean_name(name):
    """A control's name as a person reads it: no invisible direction marks, single spaces, and no shortcut hint on
    the end, so "Send \u202a(Ctrl-Enter)\u202c" is "Send"."""
    return SHORTCUT_HINT.sub("", " ".join(BIDI.sub("", str(name or "")).split())).strip()


def _text(value):
    """What's typed in a control, without direction marks and with single spaces, the way typed text is compared."""
    return " ".join(BIDI.sub("", str(value or "")).split())


def ui_info(el):
    """What a control is: {"name", "role", "aid", "password", "el"}, role one of ROLES or ""."""
    return {"name": clean_name(el.CurrentName), "role": ROLE_OF.get(el.CurrentControlType, ""),
            "aid": str(el.CurrentAutomationId or ""), "password": bool(el.CurrentIsPassword), "el": el}


def _shown(el):
    """On the screen, enabled and with a size: one a person could use."""
    if el.CurrentIsOffscreen or not el.CurrentIsEnabled:
        return False
    rect = el.CurrentBoundingRectangle
    return rect.right > rect.left and rect.bottom > rect.top


def _find(want, role, aid, hwnd):
    """The shown controls of role (any of ROLES if None) in window hwnd, by AutomationId, else by clean name. Raises
    LookupError when it couldn't really look (no window in front, or more controls than it reads, the one wanted
    maybe among those left), rather than answer that it isn't there."""
    a = uia()
    hwnd = hwnd or user32.GetForegroundWindow()
    root = a.ElementFromHandle(hwnd) if hwnd else None
    if not root:
        raise LookupError("no window in front to read")
    types = [ROLES[role]] if role in ROLES else list(ROLES.values())
    kinds = a.CreatePropertyCondition(30003, types[0])  # ControlType: one FindAll by role, never a walk of the tree
    for t in types[1:]:
        kinds = a.CreateOrCondition(kinds, a.CreatePropertyCondition(30003, t))
    for by_id in ([True, False] if aid else [False]):  # an AutomationId can change with the app's version: then the name
        found = root.FindAll(4, a.CreateAndCondition(kinds, a.CreatePropertyCondition(30011, str(aid))) if by_id
                             else kinds)
        hits = []
        for i in range(min(500, found.Length if found else 0)):
            el = found.GetElement(i)
            if (by_id or (want and clean_name(el.CurrentName).lower() == want)) and _shown(el):
                hits.append(el)
        if hits or not want:
            return hits
        if not by_id and found and found.Length > 500:  # it may be one of those past the ones read
            raise LookupError("more controls than she reads")
    return []


def find_ui(name=None, role=None, aid=None, hwnd=None, wait=0.0, unique=True, strict=False):
    """The shown, enabled control of this role in the window in front (or hwnd): by its AutomationId, else exactly by
    name (clean_name, any case). unique: only if there's exactly one, else None, since two Send buttons mean two mails
    open and she can't tell which. Looks again every 0.3 s for up to wait seconds, for a page still loading.
    strict: a window that couldn't be read (too slow, none in front, more controls than she reads) raises, rather
    than passing for one without the control, since saying it's gone takes a clean read."""
    want = clean_name(name).lower()
    if not want and not aid:
        return None
    end = _clock() + wait
    while True:
        try:
            hits = _find(want, role, aid, hwnd)
        except Exception as exc:  # slow, gone or not answering: as good as not there, unless strict
            if strict:
                raise
            print(f"  ui automation: {exc!r}")
            hits = []
        if hits and (len(hits) == 1 or not unique):
            return hits[0]
        if len(hits) > 1 or _clock() >= end:
            return None
        _sleep(0.3)


def find_all_ui(name=None, role=None, aid=None, hwnd=None):
    """Every shown, enabled control find_ui would find, in the window's order, or [] if none or it couldn't read the
    window: a settings card is often named like the switch in it, and comes first."""
    want = clean_name(name).lower()
    if not want and not aid:
        return []
    try:
        return _find(want, role, aid, hwnd)
    except Exception as exc:  # slow, gone or not answering: as good as not there
        print(f"  ui automation: {exc!r}")
        return []


UIA_E_TIMEOUT = -2146233083  # 0x80131505 as comtypes gives it: the app didn't answer within UIA_LIMIT


def _pattern(el, pattern, interface):
    """el's UI Automation pattern (Invoke 10000, Value 10002, Toggle 10015) as its interface, or None."""
    try:
        got = el.GetCurrentPattern(pattern)
        if not got:
            return None
        _com()
        from comtypes.gen import UIAutomationClient
        return got.QueryInterface(getattr(UIAutomationClient, interface))
    except Exception:
        return None


def ui_act(el, text=None, state=None, caret=False):
    """Use a control as a person would, and say how: a switch turned "on" or "off" only if it isn't already
    ("already"); text put in by its Value pattern, else by focusing it and pasting, the clipboard put back after; else
    Invoked, the way its own keyboard shortcut would; else clicked in its middle. caret: the text is typed where the
    cursor is (a "type" step), never by the Value pattern, which puts it in place of everything in the box: a list in
    Notepad, a draft or its signature in Gmail, and in an Edit its undo too."""
    if state in ("on", "off"):
        toggle = _pattern(el, 10015, "IUIAutomationTogglePattern")
        if toggle is None:
            raise RuntimeError("That isn't something I can switch on or off")
        if ("on" if toggle.CurrentToggleState == 1 else "off") == state:
            return "already"
        toggle.Toggle()
        return "toggled"
    if text is not None:
        value = None if caret else _pattern(el, 10002, "IUIAutomationValuePattern")
        if value is not None and not value.CurrentIsReadOnly:
            value.SetValue(str(text))
            return "set"
        el.SetFocus()
        kept = clipboard_snapshot()
        try:
            paste(str(text))
            time.sleep(0.3)  # the app reads the clipboard after the keys: too soon and it pastes what was there
        finally:
            clipboard_restore(kept)
        return "pasted"
    invoke = _pattern(el, 10000, "IUIAutomationInvokePattern")
    if invoke is not None:
        try:
            invoke.Invoke()
        except Exception as exc:
            # A WinForms or Win32 button that opens a modal dialog (Are you sure?, Save As) doesn't return from Invoke
            # till the dialog closes, so UI Automation gives up at UIA_LIMIT though it was pressed. What's on the
            # screen next says if it worked: it's never pressed again to find out
            if getattr(exc, "hresult", None) != UIA_E_TIMEOUT:
                raise
            print("  ui automation: Invoke timed out, taken as pressed")
        return "invoked"
    with _real_pixels():  # in the real pixels click uses: read outside, a screen scaled unlike the main one is off
        rect = el.CurrentBoundingRectangle
    click((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
    return "clicked"


def ui_value(el):
    """What's typed in a control, or None: it has no Value pattern, it's a password box, or it couldn't be read."""
    try:
        if el.CurrentIsPassword:
            return None
        value = _pattern(el, 10002, "IUIAutomationValuePattern")
        return None if value is None else _text(value.CurrentValue)
    except Exception:
        return None


def ui_toggle(el):
    """"on" or "off" for a switch or a tick box, else None."""
    toggle = _pattern(el, 10015, "IUIAutomationTogglePattern")
    try:
        return None if toggle is None else "on" if toggle.CurrentToggleState == 1 else "off"
    except Exception:
        return None


def ui_at(x, y):
    """What's at a point on the screen, in real pixels: the control there, or the nearest one around it that can be
    pressed or switched, since a button's label is often a text inside it. Never the page around it: a picture, a
    canvas or a button a web page doesn't show UI Automation isn't the page, whose name is only its title, so the
    thing at the point is given as it is, often with no name, which the gate won't press after typing or hold for a
    yes. ui_info with "climbed": it's one around the thing at the point (a button around its label, or a mail's row
    around an icon in it that UI Automation doesn't show, which the gate won't hold for a yes: pressing the row opens
    the mail). None if UI Automation can't say."""
    try:
        a = uia()
        with _real_pixels():
            el = a.ElementFromPoint(wintypes.POINT(int(x), int(y)))
        first, walker = el, a.ControlViewWalker
        for depth in range(8):
            if not el or (depth and el.CurrentControlType == ROLES["document"]):
                break
            if el.CurrentControlType in ROLE_OF or el.GetCurrentPropertyValue(30031) or \
                    el.GetCurrentPropertyValue(30041):  # can be Invoked or Toggled
                return {**ui_info(el), "climbed": bool(depth)}
            el = walker.GetParentElement(el)
        return {**ui_info(first), "climbed": False} if first else None
    except Exception as exc:
        print(f"  ui automation: {exc!r}")
        return None


def ui_focused():
    """The control with the keyboard focus, as ui_info, or None."""
    try:
        el = uia().GetFocusedElement()
        return ui_info(el) if el else None
    except Exception as exc:
        print(f"  ui automation: {exc!r}")
        return None


def ui_dialog_text(el, most=300):
    """The words of the dialog a control is in, up to most characters: its title and the text in it, so an OK is
    judged by what it says yes to, like "Delete this conversation?". "" if it isn't in one."""
    try:
        a = uia()
        box, walker = el, a.ControlViewWalker
        for _ in range(12):
            if not box:
                return ""
            if box.CurrentControlType == 50032 or str(box.CurrentAriaRole or "").lower() in ("dialog", "alertdialog"):
                break  # a window, or a dialog in a web page
            box = walker.GetParentElement(box)
        else:
            return ""
        texts = box.FindAll(4, a.CreatePropertyCondition(30003, 50020))  # its texts
        words = [clean_name(box.CurrentName)] + [clean_name(texts.GetElement(i).CurrentName)
                                                 for i in range(min(20, texts.Length if texts else 0))]
        return " ".join(w for w in words if w)[:most]
    except Exception as exc:
        print(f"  ui automation: {exc!r}")
        return ""


def foreground():
    """(hwnd, exe, title) of the window in front, exe as a lower-case file name like "chrome.exe"."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, "", ""
    return hwnd, os.path.basename(window_exe(hwnd)).lower(), window_title(hwnd)


def site_of(url):
    """The domain of a web address, without "www.": "https://www.Example.com/a" and "mail.google.com/mail/u/0" (as
    the address bar shows it) give "example.com" and "mail.google.com". None if it isn't one."""
    m = re.match(r"(?:[a-z][\w+.-]*://)?(?:[^@/\s]*@)?([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})(?::\d+)?(?:[/?#]|$)",
                 str(url or "").strip(), re.I)
    return m[1].lower().removeprefix("www.") if m else None


def browser_site():
    """The site in front, from the address bar of Chrome, Edge or Brave, as site_of has it. None for anything else."""
    hwnd, exe, _ = foreground()
    if exe not in BROWSER_EXES:
        return None
    box = find_ui(OMNIBOX, "edit", hwnd=hwnd)
    return site_of(ui_value(box)) if box is not None else None


# A site is a tab, not an app: "Close the YouTube" on 22 October got "YouTube isn't running". Its tab is found by
# its title, the site's own name a part of it ("Akka Official Trailer | Keerthy Suresh - YouTube", "(3) Feed |
# LinkedIn", "Home / X"), never the name as a word in it: "download youtube videos - Google Search" isn't YouTube
TAB_BROWSERS = BROWSER_EXES | {"firefox.exe"}
TITLE_PARTS = re.compile(r"\s+[-|/\u00b7\u2013\u2014]\s+")
TITLE_COUNT = re.compile(r"^\(\d[\d,]*\+?\)\s*")  # "(3) YouTube": what's unread


def shows_site(title, names):
    """True if a window or tab title is one of the site's own: one of names ("YouTube", "Google Search") is a part of
    it, as a site puts its name in its pages' titles."""
    names = [names] if isinstance(names, str) else names
    parts = {" ".join(TITLE_COUNT.sub("", p).split()).lower() for p in TITLE_PARTS.split(BIDI.sub("", title or ""))}
    return any(" ".join(str(n).split()).lower() in parts for n in names if str(n).strip())


def browser_windows():
    """Browser windows on screen, minimised ones too, front-most first."""
    found = []
    cb = WNDENUMPROC(lambda h, _: found.append(h) or True)
    user32.EnumWindows(cb, 0)
    return [h for h in found if _is_app_window(h) and os.path.basename(window_exe(h)).lower() in TAB_BROWSERS]


def _tab_items(hwnd):
    """The tabs in a browser window's tab strip, as (UI Automation element, name)."""
    a = uia()
    root = a.ElementFromHandle(hwnd)
    found = root.FindAll(4, a.CreatePropertyCondition(30003, ROLES["tab"])) if root else None
    items = [found.GetElement(i) for i in range(min(100, found.Length if found else 0))]
    return [(el, clean_name(el.CurrentName)) for el in items]


def close_site_tab(names):
    """Closes the browser tab showing a site (names as shows_site has them): one in front of its window is brought
    forward and closed with Ctrl+W, else one behind another tab is picked in the tab strip first. The tab's title.
    LookupError if no tab shows it, RuntimeError if it couldn't be brought to the front, so the keys can't go to
    another window."""
    windows = browser_windows()
    target = next((h for h in windows if shows_site(window_title(h), names)), None)
    for hwnd in windows if target is None else ():
        try:
            tab = next((el for el, name in _tab_items(hwnd) if shows_site(name, names)), None)
        except Exception as exc:  # slow or not answering: the next window
            print(f"  ui automation: {exc!r}")
            continue
        if tab is None:
            continue
        bring_to_front(hwnd)
        _sleep(0.15)
        pick = _pattern(tab, 10010, "IUIAutomationSelectionItemPattern")  # SelectionItem: the tab to the front
        if pick is not None:
            pick.Select()
        else:
            ui_act(tab)
        _sleep(0.3)
        target = hwnd
        break
    if target is None:
        raise LookupError("no tab shows it")
    bring_to_front(target)
    _sleep(0.15)
    title = window_title(target)
    if user32.GetForegroundWindow() != target or not shows_site(title, names):
        raise RuntimeError("its browser window didn't come to the front")
    press("ctrl", "w")
    return title


# What a snapshot reads of each control, all in the one call: name, role, AutomationId, off screen, enabled,
# password, where it is, keyboard focus, what's typed in it, and whether it's a switch and how it's set
SNAP_PROPS = (30005, 30003, 30011, 30022, 30010, 30019, 30001, 30008, 30045, 30041, 30086)
SNAP_LISTS = 15  # list items in a snapshot: a mailbox has hundreds, and the first screenful is what she needs
SNAP_NAME = 60  # characters of a name
SLOW_FOR = 60.0  # seconds a window UI Automation timed out on is left to a screenshot
_slow = {}  # window -> until when it is


def _cached(value, kind):
    """A cached property's value if it's a kind (str, int, bool), else None: UI Automation's "not supported" comes
    back as an object, and a bool is an int too."""
    return value if type(value) is kind else None


def _focus_box(a, walk=True):
    """Where the dialog the keyboard focus is in sits, (left, top, right, bottom), or None if it isn't in one short of
    the window itself (or not walk: not looked for); and the control with the focus as (role, name, what's typed in
    it), or None. (None, None) if UI Automation can't say."""
    try:
        f = a.GetFocusedElement()
        if not f:
            return None, None
        focused = (ROLE_OF.get(f.CurrentControlType, ""), clean_name(f.CurrentName)[:SNAP_NAME],
                   None if f.CurrentIsPassword else _cached(f.GetCurrentPropertyValue(30045), str))
        e, walker = f if walk else None, a.ControlViewWalker
        for _ in range(12):  # as ui_dialog_text: a window, or a dialog in a web page (Gmail's new mail)
            if not e:
                break
            if e.CurrentControlType == 50032 or str(e.CurrentAriaRole or "").lower() in ("dialog", "alertdialog"):
                r = e.CurrentBoundingRectangle
                return (r.left, r.top, r.right, r.bottom), focused
            e = walker.GetParentElement(e)
        return None, focused
    except Exception:
        return None, None


def _inside(rect, box):
    return box is not None and box[0] <= rect[0] and box[1] <= rect[1] and rect[2] <= box[2] and rect[3] <= box[3]


def _snapshot(hwnd, most, browser=False, root=None, lists=SNAP_LISTS):
    """The shown controls of window hwnd (or under root), of ROLES, read in one FindAllBuildCache: (items, web, total,
    focused, cut), web being how many of them are inside the page of a browser (None if there's no page), total how
    many there were before the first most were kept, focused the control with the focus (_focus_box), and cut True
    if some were left out: past most, or list items past lists.
    With more than most, the order they're in the window doesn't decide alone which are kept: Chrome's own buttons
    and Gmail's inbox came first, and the new mail, last on the page, was never seen. So the address bar comes first
    (the site is read from it), then what's in the dialog the focus is in (the new mail: Gmail puts the cursor in its
    To), then the page, then the rest. In a browser, the tabs along its top are left out: every other tab's title,
    your bank's too, went to the model each round."""
    a = uia()
    root = root or a.ElementFromHandle(hwnd)
    if not root:
        return [], None, 0, None, False
    cache = a.CreateCacheRequest()
    for prop in SNAP_PROPS:
        cache.AddProperty(prop)
    kinds = None
    for t in ROLES.values():
        one = a.CreatePropertyCondition(30003, t)
        kinds = one if kinds is None else a.CreateOrCondition(kinds, one)
    found = root.FindAllBuildCache(4, a.CreateAndCondition(kinds, a.CreatePropertyCondition(30022, False)), cache)
    items, listed, page, cut = [], 0, None, False
    for i in range(found.Length if found else 0):
        el = found.GetElement(i)
        rect = el.CachedBoundingRectangle
        if el.CachedIsOffscreen or not el.CachedIsEnabled or rect.right <= rect.left or rect.bottom <= rect.top:
            continue
        role = ROLE_OF.get(el.CachedControlType, "")
        name = clean_name(el.CachedName)[:SNAP_NAME]
        value = None if el.CachedIsPassword else _cached(el.GetCachedPropertyValue(30045), str)
        state = _cached(el.GetCachedPropertyValue(30086), int) if _cached(el.GetCachedPropertyValue(30041), bool) \
            else None
        if role == "document" and page is None:
            page = (rect.left, rect.top, rect.right, rect.bottom)
        if role == "listitem":
            listed += 1
            if listed > lists:
                cut = True
                continue
        if not name and not value and role not in ("edit", "document", "combobox"):
            continue  # a button with no name: nothing she could tell anyone about it
        items.append({"id": len(items) + 1, "role": role, "name": name, "value": _text(value) if value else None,
                      "state": {0: "off", 1: "on"}.get(state), "password": bool(el.CachedIsPassword),
                      "focus": bool(el.CachedHasKeyboardFocus), "aid": str(el.CachedAutomationId or ""),
                      "rect": (rect.left, rect.top, rect.right, rect.bottom), "el": el})
    if browser and page is not None:  # the tab strip, above the page
        items = [it for it in items if not (it["role"] == "tab" and it["rect"][3] <= page[1])]
    web = None if page is None else sum(1 for it in items if it["role"] != "document" and _inside(it["rect"], page))
    total = len(items)
    box, focused = _focus_box(a, walk=total > most)
    if total > most:
        def rank(it):
            if it["role"] == "edit" and it["name"] == OMNIBOX:
                return 0
            return 1 if _inside(it["rect"], box) else 2 if _inside(it["rect"], page) else 3
        items, cut = sorted(items, key=rank)[:most], True  # sorted keeps the window's order within each
    for n, it in enumerate(items):
        it["id"] = n + 1
    return items, web, total, focused, cut


def ui_snapshot(hwnd=None, most=60):
    """What's in the window in front (or hwnd) for her to read and press, in one go: {"hwnd", "title", "exe", "site",
    "focus" (the id with the keyboard focus, or None), "total" (how many controls there were, most of them kept),
    "focused" (the control with the focus as (role, name, value), kept or not), "cut" (some were left out, so a
    name's only once in items maybe isn't in the window), "items": [{"id", "role", "name", "value", "state",
    "password", "focus", "aid", "rect", "el"}]}, up to most controls in the order they're on the page (with more,
    those that matter first: _snapshot), SNAP_LISTS list items of them, names cut to SNAP_NAME. A
    password's value is never read. None if UI Automation timed out on the window: it's left to a screenshot for
    SLOW_FOR seconds after, rather than held up each time.
    Chrome fills in a page's controls lazily, when something first asks: with fewer than 5 in the page, it reads
    once more after half a second. Only that read is timed for being slow: timed with the half second and the read
    before it, a page still loading shut UI Automation off for the whole of Chrome, all its tabs, for a minute."""
    hwnd = hwnd or user32.GetForegroundWindow()
    if not hwnd or _clock() < _slow.get(hwnd, 0.0):
        return None
    exe, began = os.path.basename(window_exe(hwnd)).lower(), _clock()
    browser = exe in BROWSER_EXES
    try:
        items, web, total, focused, cut = _snapshot(hwnd, most, browser)
        if browser and web is not None and web < 5:
            _sleep(0.5)
            began = _clock()  # the read the next look will do: not the half second, nor a page still filling in
            items, web, total, focused, cut = _snapshot(hwnd, most, browser)
    except Exception as exc:  # UI Automation's time limit, or the window went away: a screenshot will do
        print(f"  ui snapshot: {exc!r}")
        _slow[hwnd] = _clock() + SLOW_FOR
        return None
    if _clock() - began > 2 * UIA_LIMIT / 1000:  # it got there, but slowly: next time straight to a screenshot
        _slow[hwnd] = _clock() + SLOW_FOR
    box = next((it for it in items if it["role"] == "edit" and it["name"] == OMNIBOX), None)
    return {"hwnd": hwnd, "title": window_title(hwnd), "exe": exe,
            "site": site_of(box["value"]) if box is not None and browser else None,
            "focus": next((it["id"] for it in items if it["focus"]), None), "total": total, "focused": focused,
            "cut": cut, "items": items}


def ui_fields(el=None):
    """What a send would send, read in one go as [(role, name, value)]: every shown control in the dialog el is in
    (Gmail's new mail is one, in its page), else in the window in front, however many: a snapshot's caps could leave a
    recipient out. A password's value is never read. None if UI Automation couldn't read it, never [] for that: who a
    mail goes to that couldn't be read isn't a mail to nobody."""
    try:
        a = uia()
        hwnd = user32.GetForegroundWindow()
        box, walker, scope = el, a.ControlViewWalker, None
        for _ in range(12):  # as ui_dialog_text: a window, or a dialog in a web page
            if not box:
                break
            if box.CurrentControlType == 50032 or str(box.CurrentAriaRole or "").lower() in ("dialog", "alertdialog"):
                scope = box
                break
            box = walker.GetParentElement(box)
        scope = scope or (a.ElementFromHandle(hwnd) if hwnd else None)
        if not scope:
            return None
        browser = bool(hwnd) and os.path.basename(window_exe(hwnd)).lower() in BROWSER_EXES
        items = _snapshot(hwnd, 10 ** 5, browser, root=scope, lists=10 ** 5)[0]
    except Exception as exc:
        print(f"  ui automation: {exc!r}")
        return None
    return [(it["role"], it["name"], it["value"]) for it in items]


# --------------------------------------------------------------------------- Native Window Management & Shell
def maximize_foreground_window():
    """Maximize the active foreground window using Win32 ShowWindow (< 1ms)."""
    _com()
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE


def restore_foreground_window():
    """Restore/unmaximize the active foreground window (< 1ms)."""
    _com()
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE


def minimize_foreground_window():
    """Minimize the active foreground window (< 1ms)."""
    _com()
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE


def show_desktop():
    """Toggle or show desktop via Windows Shell COM (< 5ms, 0 RAM)."""
    _com()
    import comtypes.client
    shell = comtypes.client.CreateObject("Shell.Application")
    shell.ToggleDesktop()


SHELL_FOLDERS = {"shell:MyComputerFolder", "shell:RecycleBinFolder", "shell:Downloads", "shell:Personal",
                 "shell:My Pictures", "shell:My Music", "shell:My Video", "shell:Desktop"}
# What they're called, for an "open" step: a model planned "open recycle bin" as an app, which no Start menu has
SHELL_NAMES = {"recycle bin": "shell:RecycleBinFolder", "this pc": "shell:MyComputerFolder",
               "my computer": "shell:MyComputerFolder", "downloads": "shell:Downloads", "documents": "shell:Personal",
               "my documents": "shell:Personal", "pictures": "shell:My Pictures"}


def open_folder(path_or_uri):
    """Open a folder in File Explorer. Only an existing folder or one of SHELL_FOLDERS: os.startfile would run a
    program or script if handed one, so files are refused."""
    target = str(path_or_uri or "").strip()
    if target in SHELL_FOLDERS:
        os.startfile(target)
        return
    full = os.path.abspath(os.path.expandvars(os.path.expanduser(target)))
    if not target or not os.path.isdir(full):
        raise RuntimeError("I can only open folders that exist")
    os.startfile(full)


def open_snipping_tool():
    """Launch Windows Snipping Tool / screenclip protocol."""
    os.startfile("ms-screenclip:")


# Windows' own tools and Settings pages, by what people call them, for an "open" step (windows_page): on 25 October
# "Open device manager" searched Google, Device Manager not being in the Start menu, and a task in Settings went to
# https://display for ms-settings:display. Only these open by name: a Settings page can't run anything, and none of
# these tools starts a program by itself (Run, Task Scheduler, the registry and command windows are left out)
WINDOWS_PAGES = {
    "windows update": "ms-settings:windowsupdate", "windows updates": "ms-settings:windowsupdate",
    "updates": "ms-settings:windowsupdate", "update settings": "ms-settings:windowsupdate",
    "check for updates": "ms-settings:windowsupdate-action",
    "display": "ms-settings:display", "display settings": "ms-settings:display", "screen settings": "ms-settings:display",
    "sound settings": "ms-settings:sound", "sound": "ms-settings:sound", "audio settings": "ms-settings:sound",
    "bluetooth": "ms-settings:bluetooth", "bluetooth settings": "ms-settings:bluetooth",
    "bluetooth and devices": "ms-settings:bluetooth", "devices": "ms-settings:bluetooth",
    "wifi": "ms-settings:network-wifi", "wi fi": "ms-settings:network-wifi", "wifi settings": "ms-settings:network-wifi",
    "network settings": "ms-settings:network", "internet settings": "ms-settings:network",
    "network and internet": "ms-settings:network", "hotspot": "ms-settings:network-mobilehotspot",
    "mobile hotspot": "ms-settings:network-mobilehotspot", "vpn": "ms-settings:network-vpn",
    "airplane mode": "ms-settings:network-airplanemode", "flight mode": "ms-settings:network-airplanemode",
    "installed apps": "ms-settings:appsfeatures", "apps and features": "ms-settings:appsfeatures",
    "apps settings": "ms-settings:appsfeatures", "default apps": "ms-settings:defaultapps",
    "startup apps": "ms-settings:startupapps", "storage": "ms-settings:storagesense",
    "storage settings": "ms-settings:storagesense", "battery settings": "ms-settings:batterysaver",
    "battery saver": "ms-settings:batterysaver", "power settings": "ms-settings:powersleep",
    "power and battery": "ms-settings:powersleep", "night light settings": "ms-settings:nightlight",
    "personalization": "ms-settings:personalization", "personalisation": "ms-settings:personalization",
    "wallpaper": "ms-settings:personalization-background", "background": "ms-settings:personalization-background",
    "themes": "ms-settings:themes", "colors": "ms-settings:colors", "colours": "ms-settings:colors",
    "lock screen settings": "ms-settings:lockscreen", "taskbar settings": "ms-settings:taskbar",
    "notification settings": "ms-settings:notifications", "notifications settings": "ms-settings:notifications",
    "focus": "ms-settings:focus", "do not disturb": "ms-settings:notifications",
    "privacy": "ms-settings:privacy", "privacy settings": "ms-settings:privacy",
    "camera settings": "ms-settings:privacy-webcam", "camera privacy": "ms-settings:privacy-webcam",
    "camera permissions": "ms-settings:privacy-webcam", "microphone settings": "ms-settings:privacy-microphone",
    "microphone privacy": "ms-settings:privacy-microphone", "mic settings": "ms-settings:privacy-microphone",
    "location settings": "ms-settings:privacy-location", "date and time": "ms-settings:dateandtime",
    "time settings": "ms-settings:dateandtime", "language settings": "ms-settings:regionlanguage",
    "keyboard settings": "ms-settings:typing", "mouse settings": "ms-settings:mousetouchpad",
    "touchpad settings": "ms-settings:devices-touchpad", "printers": "ms-settings:printers",
    "printers and scanners": "ms-settings:printers", "accounts": "ms-settings:yourinfo",
    "sign in options": "ms-settings:signinoptions", "about": "ms-settings:about", "about this pc": "ms-settings:about",
    "system settings": "ms-settings:display", "accessibility": "ms-settings:easeofaccess",
    "windows security": "windowsdefender:", "virus protection": "windowsdefender:",
    "device manager": "devmgmt.msc", "disk management": "diskmgmt.msc", "event viewer": "eventvwr.msc",
    "task manager": "taskmgr.exe", "control panel": "control.exe", "system information": "msinfo32.exe",
    "resource monitor": "resmon.exe", "character map": "charmap.exe", "network connections": "ncpa.cpl",
    "programs and features": "appwiz.cpl", "sound control panel": "mmsys.cpl", "power options": "powercfg.cpl",
    "system properties": "sysdm.cpl", "mouse properties": "main.cpl"}
SETTINGS_PAGE = re.compile(r"ms-settings:[a-z0-9-]*", re.I)  # any Settings page, as a model may name one


def windows_page(name):
    """What opens one of Windows' tools or Settings pages called name ("Device Manager", "the Windows Update page",
    "camera settings"), else None."""
    key = " ".join(re.sub(r"[^a-z0-9]+", " ", str(name or "").lower().replace("wi-fi", "wifi")).split())
    key = re.sub(r"^(?:open |the |my )+", "", key)
    for k in (key, re.sub(r" (?:page|window|app|tool|settings? page)$", "", key), re.sub(r"^windows ", "", key)):
        if k in WINDOWS_PAGES:
            return WINDOWS_PAGES[k]
    return None


def open_windows_page(target):
    """Opens one of WINDOWS_PAGES' tools or pages, or a Settings page (ms-settings:...): nothing else, as
    os.startfile would run whatever it's handed."""
    target = str(target or "").strip()
    if target not in WINDOWS_PAGES.values() and not SETTINGS_PAGE.fullmatch(target):
        raise RuntimeError("I can only open Windows' own settings and tools that way")
    os.startfile(target)

