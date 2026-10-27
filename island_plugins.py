"""The island's plugins, the way MaterialYou Dynamic Island (github.com/Angel-Studio/MaterialYou-Dynamic-Island)
has them: a popup when a notification comes in, from the apps you pick; what's playing, with its controls; the
battery when you plug in or it runs low; and a running timer counting down. Each can be turned on and off, and has
its own options, in the Island tab.

A plugin looks at what Windows already keeps, on one background thread, and tells the island what to show. Nothing
here sends anything anywhere. To add one, subclass Plugin and put it in PLUGINS.
"""
import asyncio
import ctypes
import os
import queue
import re
import sys
import threading
import time
import winreg

import settings
import watch
import winplatform as win

FULL_SCREEN = {2, 3, 4, 7}  # SHQueryUserNotificationState: busy, a game, presenting, a full-screen Store app


class Activity:
    """What a plugin wants the island to show. kind: notification, media, battery or timer. live: it stays while
    it lasts (music playing, a timer running), else it's a popup that shows for a few seconds. mood: how her eyes
    react when it comes up (island_face.MOODS)."""
    __slots__ = ("plugin", "kind", "data", "live", "mood", "at", "until", "seconds")

    def __init__(self, plugin, kind, data, live=False, mood=None, seconds=None):
        self.plugin, self.kind, self.data, self.live, self.mood = plugin, kind, data, live, mood
        self.at, self.until, self.seconds = time.time(), None, seconds


def get_options(plugin_id):
    return dict((settings.get("island_plugin_options") or {}).get(plugin_id) or {})


class Plugin:
    """One thing the island can show. poll(now) runs on the plugins' thread every `every` seconds while it's on,
    and calls self.show(Activity) for a popup, self.live(Activity or None) for what stays while it lasts."""
    id = name = description = ""
    every = 2.0
    options = ()  # (key, label, default) for the Island tab
    default_on = True

    def __init__(self, host):
        self.host = host

    def enabled(self):
        on = (settings.get("island_plugins") or {}).get(self.id)
        return self.default_on if on is None else bool(on)

    def option(self, key):
        opts = get_options(self.id)
        if key in opts:
            return opts[key]
        return next((d for k, _, d in self.options if k == key), None)

    def show(self, activity):
        self.host.post(("show", activity))

    def live(self, activity):
        self.host.post(("live", self.id, activity))

    def start(self):
        """When it's turned on, or the app starts: note what's there already, so it isn't news."""

    def stop(self):
        """When it's turned off: anything it shows goes."""
        self.live(None)

    def poll(self, now):
        raise NotImplementedError

    def command(self, what, data=None):
        """A click on what it shows, run on the plugins' thread."""


# --------------------------------------------------------------------------- notifications
# Your phone's apps by their Android package: Phone Link's copies of their notifications carry only that
PHONE_APPS = {
    "com.google.android.apps.nbu.paisa.user": "Google Pay", "com.phonepe.app": "PhonePe", "net.one97.paytm": "Paytm",
    "com.bt.bms": "BookMyShow", "com.jpl.jiomart": "JioMart", "com.jio.myjio": "MyJio", "in.swiggy.android": "Swiggy",
    "com.application.zomato": "Zomato", "in.amazon.mshop.android.shopping": "Amazon",
    "com.flipkart.android": "Flipkart", "com.ubercab": "Uber", "com.olacabs.customer": "Ola",
    "com.rapido.passenger": "Rapido", "com.olx.southasia": "OLX", "com.android.deskclock": "Clock",
    "com.google.android.deskclock": "Clock", "com.google.android.gm": "Gmail", "com.google.android.youtube": "YouTube",
    "com.google.android.googlequicksearchbox": "Google", "com.google.android.gms": "Google Play services",
    "com.android.vending": "Play Store", "com.google.android.apps.maps": "Google Maps",
    "com.google.android.apps.photos": "Google Photos", "com.instagram.android": "Instagram",
    "com.facebook.katana": "Facebook", "com.facebook.orca": "Messenger", "com.snapchat.android": "Snapchat",
    "com.twitter.android": "X", "com.linkedin.android": "LinkedIn", "com.openai.chatgpt": "ChatGPT",
    "com.shazam.android": "Shazam", "com.spotify.music": "Spotify", "com.netflix.mediaclient": "Netflix",
    "com.truecaller": "Truecaller", "com.sbi.lotusintouch": "SBI YONO", "com.zoho.accounts.oneauth": "Zoho OneAuth",
    "com.xiaomi.mipicks": "GetApps", "com.miui.msa.global": "MIUI",
}
GENERIC = {"com", "org", "net", "ai", "io", "in", "co", "app", "apps", "android", "desktop", "client", "stable", "beta",
           "electron", "microsoft", "google", "windows", "mobile"}  # parts of an app's ID that aren't its name


def app_label(app_id, fallback=""):
    """What an app is called, from its Windows ID: the Start menu's name, WhatsApp for Phone Link's copy of it, a
    phone app by its package, or a tidy name from the ID ("Microsoft.VisualStudioCode", Visual Studio Code). "" for
    Windows' own notices (low disk, AutoPlay) and IDs with no name in them."""
    aid = str(app_id or "")
    low = aid.lower()
    if low.startswith("windows."):  # Windows' own: low disk, AutoPlay, Settings, security
        return ""
    for name, start_id in win.loaded_start_apps():
        if start_id.lower() == low:
            return name
    name, messaging = watch._app(aid)
    if messaging or not aid:
        return name if aid else fallback
    if is_phone(aid):
        if "yourphonecalling" in low:
            return "Phone calls"
        package = aid.split("YourPhoneNotifications_", 1)[1] if "YourPhoneNotifications_" in aid else ""
        if not package:
            return fallback or name
        parts = [p for p in package.split(".") if p and p.lower() not in GENERIC]
        return PHONE_APPS.get(package.lower()) or (_tidy(parts[-1]) if parts else fallback or name)
    if "!" in aid:
        family, tail = aid.split("!", 1)
        if tail.lower().startswith(("http://", "https://")):  # a site put in the Start menu by Edge or Chrome
            host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", tail, flags=re.I).split("/")[0].lower())
            return host.split(".")[0].capitalize() if host else ""
        if "://" in tail:
            return ""  # a browser extension
        aid = family
    parts = [p for p in aid.split("_", 1)[0].split(".")  # a Store app's package, before its publisher's code
             if p and p.lower() not in GENERIC and not re.fullmatch(r"[0-9A-F]{6,}", p)]
    if not parts or (re.fullmatch(r"[A-Za-z0-9]{16,}", parts[-1]) and re.search(r"\d", parts[-1])):
        return ""  # a code, not a name
    return _tidy(parts[-1])


def _tidy(word):
    """An ID's word as a name: "VisualStudioCode" is Visual Studio Code, "opencode" Opencode."""
    word = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", word)
    return word[:1].upper() + word[1:]


def is_phone(app_id):
    return "yourphone" in str(app_id).lower()


def notification_apps(days=180):
    """[{"name", "messaging", "phone", "when", "id"}] for the apps that have notified on this PC lately, newest
    first, one row a name (WhatsApp on the PC and through Phone Link are one). From Windows' own note of it."""
    found = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, watch.SETTINGS_KEY) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                app_id = winreg.EnumKey(root, i)
                try:
                    with winreg.OpenKey(root, app_id) as key:
                        added = winreg.QueryValueEx(key, "LastNotificationAddedTime")[0]
                except OSError:
                    continue
                when = (int(added) - watch.FILETIME_1970) / 1e7
                if when < time.time() - days * 86400:
                    continue
                messaging = watch._app(app_id)[1]
                name = app_label(app_id)
                if not name or re.fullmatch(r"\d+|\{?[0-9a-f]{8}-[0-9a-f-]{20,}\}?", name, re.I) or \
                        "notifyicongeneratedaumid" in app_id.lower():
                    continue  # Windows' own, or a tray icon's balloon, with no name to show
                row = found.get(name)
                if row is None or when > row["when"]:
                    found[name] = {"name": name, "messaging": messaging, "phone": is_phone(app_id), "when": when,
                                   "id": app_id}
    except OSError:
        pass
    for name in ("WhatsApp", "Telegram", "Messages"):  # the ones people message you in, even before they notify
        found.setdefault(name, {"name": name, "messaging": True, "phone": False, "when": 0.0, "id": ""})
    # the ones people message you in, then the PC's, then your phone's, the latest first in each
    return sorted(found.values(), key=lambda r: (not r["messaging"], r["phone"], -r["when"]))


def app_on(name, messaging):
    """Whether notifications from this app show in the island: as picked in the Island tab, else the apps people
    message you in."""
    picked = settings.get("island_apps") or {}
    return bool(picked[name]) if name in picked else bool(messaging)


class Notifications(Plugin):
    id, name = "notifications", "Notifications"
    description = "A popup when a notification comes in, from the apps you pick below. Click it to open the app."
    every = 1.5
    options = (("text", "Show what the message says", True),)

    def start(self):
        self.seen = time.time()
        self.added = watch.last_added()
        self.waiting, self.covered = {}, {}

    def poll(self, now):
        found = watch.notifications(self.seen, messages_only=False, limit=10)
        if found:
            self.seen = found[-1]["when"] + 1e-6
        front = (win.front_app_name() or "").lower()
        for n in found:
            self.covered[n["app"]] = max(self.covered.get(n["app"], 0.0), n["when"])
            label = app_label(n.get("app_id", ""), n["app"])
            messaging = watch._app(n.get("app_id", ""))[1]
            if not app_on(label, messaging) or (label.lower() in front and not is_phone(n.get("app_id"))):
                continue  # not picked, or you're looking at that app already
            self.show(Activity(self.id, "notification", {
                "app": label, "app_id": n.get("app_id", ""), "title": watch.spoken_sender(n["from"]) if
                re.fullmatch(r"[\d\s()+.-]+", n["from"].strip()) else n["from"],
                "text": n["text"] if self.option("text") else "", "phone": is_phone(n.get("app_id"))},
                mood="surprised"))
        # WhatsApp Desktop takes its own notification away before it can be read: Windows' note that it notified
        for app_id, when in watch.last_added().items():
            if when > self.added.get(app_id, 0.0) + 1e-6:
                self.added[app_id] = when
                self.waiting[app_id] = (when, now)
        for app_id, (when, noticed) in list(self.waiting.items()):
            name = watch._app(app_id)[0]
            if self.covered.get(name, 0.0) >= when - 15:
                del self.waiting[app_id]
            elif now - noticed > 1.6:
                del self.waiting[app_id]
                label = app_label(app_id, name)
                if app_on(label, True) and not watch.own_reply(name, when):
                    self.show(Activity(self.id, "notification", {"app": label, "app_id": app_id,
                                                                 "title": "New message", "text": "",
                                                                 "phone": is_phone(app_id)}, mood="surprised"))

    def command(self, what, data=None):
        if what == "open" and data:
            open_app(data.get("app_id", ""), data.get("app", ""))


def open_app(app_id, name=""):
    """The app a notification came from, brought up as the Start menu would: Phone Link for your phone's. Only an
    app that's in the Start menu is ever started."""
    if is_phone(app_id):
        app_id = "Microsoft.YourPhone_8wekyb3d8bbwe!App"
    known = {aid for _, aid in win.loaded_start_apps()}
    if app_id in known:
        import subprocess
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"], creationflags=win.CREATE_NO_WINDOW)
    elif name:
        try:
            win.launch(name)
        except Exception:
            pass


# --------------------------------------------------------------------------- media
PLAYERS = {"spotify": "Spotify", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "vlc": "VLC",
           "brave": "Brave", "zunemusic": "Media Player", "microsoft.media": "Media Player", "applemusic": "Apple Music",
           "youtube": "YouTube", "amazon": "Amazon Music", "wynk": "Wynk", "gaana": "Gaana"}


def player_name(app_id):
    a = str(app_id or "").lower()
    return next((name for key, name in PLAYERS.items() if key in a), (re.split(r"[!._]", a)[0] or "Media").title())


class Media(Plugin):
    id, name = "media", "Media"
    description = "What's playing, with its cover, and play, pause, next and back when you point at it."
    every = 1.0
    options = (("art", "Show the cover", True), ("paused", "Stay a while after it's paused", True))
    PAUSED_FOR = 25.0  # seconds it stays after a pause, so it can be played again from the island

    def start(self):
        self.loop, self.manager, self.session, self.key, self.art, self.art_key = None, None, None, None, None, None
        self.props, self.props_at, self.paused_at, self.meter, self.level = None, 0.0, None, None, 0.0
        self.last = None

    def _run(self, coro):
        if self.loop is None:
            win._com()
            self.loop = asyncio.new_event_loop()
        return self.loop.run_until_complete(coro)

    def _manager(self):
        if self.manager is None:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
            self.manager = self._run(M.request_async())
        return self.manager

    def poll(self, now):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status
        try:
            session = self._manager().get_current_session()
        except Exception:
            self.manager = None
            session = None
        if session is None:
            self.session = None
            if self.last is not None:
                self.last = None
                self.live(None)
            return
        self.session = session
        status = session.get_playback_info().playback_status
        playing = status == Status.PLAYING
        if playing:
            self.paused_at = None
        elif self.paused_at is None:
            self.paused_at = now
        if not playing and self.last is None:
            return  # paused before it was seen playing (Amazon Music left paused hours ago): nothing to show
        if not playing and (not self.option("paused") or now - self.paused_at > self.PAUSED_FOR):
            if self.last is not None:
                self.last = None
                self.live(None)
            return
        if self.props is None or now - self.props_at > 3.0 or (self.last and self.last.data.get("playing") != playing):
            try:
                self.props = self._run(session.try_get_media_properties_async())
            except Exception:
                self.props = None
            self.props_at = now
        p = self.props
        title = (p.title or "").strip() if p else ""
        artist = (p.artist or p.album_artist or "").strip() if p else ""
        app = player_name(session.source_app_user_model_id)
        if not title:
            title = app
        tl = session.get_timeline_properties()
        try:
            position, end = tl.position.total_seconds(), (tl.end_time - tl.start_time).total_seconds()
            from datetime import datetime, timezone
            if playing and tl.last_updated_time:
                position += (datetime.now(timezone.utc) - tl.last_updated_time).total_seconds()
        except Exception:
            position, end = 0.0, 0.0
        key = (title, artist, app)
        if self.option("art") and p and key != self.art_key:
            self.art_key, self.art = key, self._cover(p)
        data = {"title": title, "artist": artist, "app": app, "app_id": session.source_app_user_model_id or "",
                "playing": playing, "position": max(0.0, position), "duration": max(0.0, end), "at": now,
                "art": self.art if self.option("art") else None}
        same = ("title", "artist", "app", "playing", "duration")
        changed = self.last is None or any(self.last.data[k] != data[k] for k in same) or \
            self.last.data["art"] is not data["art"]
        if not changed:  # where it would be by now: a jump means it was moved along, or back
            old = self.last.data
            expected = old["position"] + (now - old["at"] if old["playing"] else 0.0)
            changed = abs(data["position"] - expected) > 2.5
        if changed:
            self.last = Activity(self.id, "media", data, live=True,
                                 mood=None if self.last is not None else "happy")
            self.live(self.last)
        if playing:
            self.level = self._level()

    def _cover(self, props):
        try:
            if not props.thumbnail:
                return None
            from winrt.windows.storage.streams import Buffer, InputStreamOptions
            stream = self._run(props.thumbnail.open_read_async())
            size = int(stream.size)
            if not 0 < size < 8_000_000:
                return None
            buf = Buffer(size)
            got = self._run(stream.read_async(buf, size, InputStreamOptions.READ_AHEAD))
            data = bytes(got)
            import island_art
            return island_art.decode(data, 96)
        except Exception as exc:
            print(f"  island: no cover art ({exc!r})")
            return None

    def _level(self):
        """How loud the speakers are playing, 0 to 1, for the bars."""
        try:
            if self.meter is None:
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
                device = AudioUtilities.GetSpeakers()
                device = getattr(device, "_dev", device)
                self.meter = ctypes.cast(device.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None),
                                         ctypes.POINTER(IAudioMeterInformation))
            return float(self.meter.GetPeakValue())
        except Exception:
            self.meter = None
            return 0.0

    def command(self, what, data=None):
        if self.session is None:
            return
        calls = {"toggle": self.session.try_toggle_play_pause_async, "next": self.session.try_skip_next_async,
                 "previous": self.session.try_skip_previous_async}
        if what in calls:
            try:
                self._run(calls[what]())
            except Exception as exc:
                print(f"  island: {what} didn't work ({exc!r})")
            self.props_at = 0.0  # look again straight away
            self.host.poll_soon(self)
        elif what == "open":
            app = player_name(self.session.source_app_user_model_id)
            try:
                win.focus_app(win.App(app, [self.session.source_app_user_model_id.lower()]))
            except Exception:
                pass


# --------------------------------------------------------------------------- battery
class Battery(Plugin):
    id, name = "battery", "Battery"
    description = "The battery and its percentage when you plug in or unplug, when it's full, and when it runs low."
    every = 2.0
    options = (("percent", "Show the percentage", True), ("while_charging", "Keep showing while it charges", False))

    def start(self):
        b = win_battery()
        self.plugged = b[1] if b else None
        self.percent = b[0] if b else None
        self.warned = set()
        self.kept = None  # what the charging one shows, so it's only sent when it changes

    def poll(self, now):
        b = win_battery()
        if b is None:
            return
        percent, plugged = b
        if self.plugged is not None and plugged != self.plugged:
            self.show(Activity(self.id, "battery", {"percent": percent, "charging": plugged,
                                                    "event": "plugged" if plugged else "unplugged"},
                               mood="happy" if plugged else None, seconds=4.0 if plugged else 2.5))
            self.warned.clear()
        elif plugged and percent >= 100 and (self.percent or 0) < 100:
            self.show(Activity(self.id, "battery", {"percent": percent, "charging": True, "event": "full"},
                               mood="happy", seconds=4.0))
        elif not plugged:
            for level in (10, 20):
                if percent <= level and level not in self.warned:
                    self.warned.update(x for x in (10, 20) if x >= level)
                    self.show(Activity(self.id, "battery", {"percent": percent, "charging": False, "event": "low"},
                                       mood="sad", seconds=6.0))
                    break
        self.plugged, self.percent = plugged, percent
        keep = percent if plugged and percent < 100 and self.option("while_charging") else None
        if keep != self.kept:
            self.kept = keep
            self.live(Activity(self.id, "battery", {"percent": percent, "charging": True, "event": "charging"},
                               live=True) if keep is not None else None)

    def stop(self):
        self.kept = None
        self.live(None)


def win_battery():
    """(percent, plugged in) from Windows, or None on a PC with no battery."""
    try:
        import psutil
        b = psutil.sensors_battery()
    except Exception:
        return None
    return None if b is None else (int(round(b.percent)), bool(b.power_plugged))


# --------------------------------------------------------------------------- timers
class Timers(Plugin):
    id, name = "timers", "Timers"
    description = "A running timer counting down, with a ring for how much is left."
    every = 1.0

    def start(self):
        self.shown = None

    def poll(self, now):
        siri = sys.modules.get("siri")
        found = []
        if siri is not None and hasattr(siri, "TIMERS"):
            with siri.TIMERS_LOCK:
                found = [((t.get("label") or "").capitalize(), t["end"], t["secs"]) for t in siri.TIMERS]
        found = [f for f in found if f[1] > now]
        if not found:
            if self.shown is not None:
                self.shown = None
                self.live(None)
            return
        label, end, total = min(found, key=lambda f: f[1])
        key = (label, end)
        if key != self.shown:
            self.shown = key
            self.live(Activity(self.id, "timer", {"label": label, "end": end, "total": max(1.0, float(total))},
                               live=True))


PLUGINS = (Notifications, Media, Battery, Timers)


class Runner:
    """The plugins' thread: each on plugin polled when it's due, what they say kept for the island to take
    (take), clicks run here (do), and the island told when a full-screen app is up or the screen in front changed."""

    def __init__(self):
        self.events = queue.Queue()
        self.jobs = queue.Queue()
        self.plugins = [cls(self) for cls in PLUGINS]
        self.due = {p.id: 0.0 for p in self.plugins}
        self.on = {}
        self.busy, self.area, self.light = None, None, None
        self.thread = threading.Thread(target=self._loop, name="island-plugins", daemon=True)
        self.stopped = False

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped = True

    def post(self, event):
        self.events.put(event)

    def take(self):
        out = []
        try:
            while True:
                out.append(self.events.get_nowait())
        except queue.Empty:
            return out

    def do(self, plugin_id, what, data=None):
        self.jobs.put((plugin_id, what, data))

    def poll_soon(self, plugin):
        self.due[plugin.id] = time.time() + 0.3

    def plugin(self, plugin_id):
        return next((p for p in self.plugins if p.id == plugin_id), None)

    def _loop(self):
        win._com()
        last_screen = 0.0
        while not self.stopped:
            now = time.time()
            try:
                while True:
                    pid, what, data = self.jobs.get_nowait()
                    p = self.plugin(pid)
                    if p is not None:
                        p.command(what, data)
            except queue.Empty:
                pass
            except Exception as exc:
                print(f"  island: a click failed ({exc!r})")
            shown = bool(settings.get("popup"))  # with the popup off in Settings they all rest
            for p in self.plugins:
                try:
                    on = shown and p.enabled()
                    if on != self.on.get(p.id):
                        self.on[p.id] = on
                        p.start() if on else p.stop()
                    if on and now >= self.due[p.id]:
                        self.due[p.id] = now + p.every
                        p.poll(now)
                    elif on and p.id == "media" and getattr(p, "last", None) is not None and \
                            p.last.data.get("playing"):
                        p.level = p._level()  # the bars move with the music between looks
                except Exception as exc:
                    self.due[p.id] = now + 10  # a plugin that fails waits, and never stops the others
                    print(f"  island: {p.name} failed ({exc!r})")
            if now - last_screen > 2.0:
                last_screen = now
                self._screen()
            time.sleep(0.1)

    def _screen(self):
        state = ctypes.c_int()
        try:
            ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
            busy = state.value in FULL_SCREEN
        except Exception:
            busy = False
        if busy != self.busy:
            self.busy = busy
            self.post(("busy", busy))
        try:
            area = win.work_area()
        except Exception:
            area = None
        if area != self.area:
            self.area = area
            self.post(("place", area))
        try:
            light = not win.dark_mode()
        except Exception:
            light = False
        if light != self.light:
            self.light = light
            self.post(("light", light))
