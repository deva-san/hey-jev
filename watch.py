"""What JARVIS would mention without being asked: a message in one of the apps people message you in, a low battery,
a nearly full drive, memory or the CPU maxed out for a while, the internet dropping or coming back. Light: a look
every 20 seconds at things Windows already keeps, nothing that runs in the meantime.

Messages come from Windows' own list of notifications, the ones that pop up in the corner, Phone Link's from your
phone included (wpndatabase.db, opened read only). A heads-up says who a message is from, all on this PC. What it
says goes to the answer model only when you ask her to read it.
"""
import os
import re
import socket
import sqlite3
import time
import winreg
import xml.etree.ElementTree as ET

import psutil

DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Notifications", "wpndatabase.db")
FILETIME_1970 = 116444736000000000  # Windows counts time in 100 ns steps from 1601
# Windows notes when each app last added a notification, and keeps the note after the notification itself is gone.
# WhatsApp Desktop takes its own away again (9 added on this PC, none ever left in the list), and one read on the
# phone takes Phone Link's copy away too, so this is how she still knows a message came in.
SETTINGS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
MESSAGE_LOOK = 4.0  # seconds between looks for messages: one look reads a small file, about a millisecond
SAME_MESSAGE = 60.0  # one heads-up per person per app in this time: Phone Link and WhatsApp Desktop both get each one
# The apps people message you in, by a piece of the app's ID in Windows, and what she calls them
MESSAGING = [(r"YourPhoneNotifications_com\.whatsapp|whatsapp", "WhatsApp"), (r"YourPhoneMessages|android\.apps\.messaging",
             "Messages"), (r"teams", "Teams"), (r"outlook|com\.microsoft\.office\.outlook", "Outlook"),
             (r"android\.gm\b|gmail", "Gmail"), (r"telegram", "Telegram"), (r"slack", "Slack"), (r"discord", "Discord"),
             (r"signal", "Signal"), (r"instagram", "Instagram"), (r"facebook\.orca|messenger", "Messenger")]
QUIET = (23, 7)  # no heads-ups from 11 at night to 7 in the morning, but for a nearly flat battery


def _app(primary_id):
    """(what she calls the app, whether people message you in it) from a Windows app ID."""
    for pattern, name in MESSAGING:
        if re.search(pattern, primary_id, re.I):
            return name, True
    tail = re.split(r"[!_.]", primary_id.replace("YourPhoneNotifications_", ""))
    words = [w for w in tail if w and not re.fullmatch(r"com|org|net|android|app|windows|microsoft|[0-9a-z]{13}", w, re.I)]
    return (words[-1].capitalize() if words else primary_id), False


def _texts(payload):
    """The lines of a notification: who it's from, then what it says."""
    try:
        root = ET.fromstring(payload if isinstance(payload, (bytes, str)) else bytes(payload))
    except ET.ParseError:
        return []
    return [" ".join((t.text or "").split()) for t in root.iter("text") if (t.text or "").strip()]


def notifications(since=0.0, messages_only=True, limit=30):
    """Notifications that arrived after since (seconds since 1970), newest last:
    [{"app", "from", "text", "when"}]. [] if Windows' list can't be read."""
    if not os.path.exists(DB):
        return []
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=2)
        try:
            rows = con.execute("SELECT h.PrimaryId, n.Payload, n.ArrivalTime FROM Notification n JOIN NotificationHandler "
                               "h ON n.HandlerId = h.RecordId WHERE n.Type = 'toast' AND n.ArrivalTime > ? "
                               "ORDER BY n.ArrivalTime DESC LIMIT 200",
                               (int(since * 1e7) + FILETIME_1970,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    out = []
    for primary_id, payload, arrived in rows:
        app, messaging = _app(primary_id or "")
        if messages_only and not messaging:
            continue
        texts = _texts(payload)
        if not texts:
            continue
        out.append({"app": app, "from": texts[0][:60], "text": " ".join(texts[1:])[:300],
                    "when": (arrived - FILETIME_1970) / 1e7})
        if len(out) >= limit:
            break
    return out[::-1]


def last_added():
    """{Windows app ID: when it last added a notification, in seconds since 1970} for the apps people message you in.

    Windows keeps this note after the notification itself has gone, so it still counts one that was taken away
    before she looked. Badges don't move it. {} if it can't be read."""
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                app_id = winreg.EnumKey(root, i)
                if not _app(app_id)[1]:
                    continue
                try:
                    with winreg.OpenKey(root, app_id) as key:
                        added = winreg.QueryValueEx(key, "LastNotificationAddedTime")[0]
                    out[app_id] = (int(added) - FILETIME_1970) / 1e7
                except (OSError, ValueError, TypeError):
                    continue
    except OSError:
        return {}
    return out


def vanished(since, found):
    """Message apps that notified after since but have nothing left in the list for it, like WhatsApp Desktop."""
    have = {n["app"] for n in found}
    return list(dict.fromkeys(_app(a)[0] for a, when in last_added().items()
                              if when > since and _app(a)[0] not in have))


def ago(when):
    mins = int((time.time() - when) // 60)
    return "just now" if mins < 1 else f"{mins} min ago" if mins < 60 else f"{mins // 60} h ago"


def recent(hours=12, messages_only=True):
    """For "any new messages?": what came in lately, with how long ago, for the model."""
    since = time.time() - hours * 3600
    found = notifications(since, messages_only, 15)
    out = [{**n, "when": ago(n["when"])} for n in found]
    added = last_added()
    for name in vanished(since, found):  # it came in, but its notification was taken away, so who from is unknown
        when = max(t for a, t in added.items() if _app(a)[0] == name)
        out.append({"app": name, "from": "unknown, the notification was cleared", "text": "", "when": ago(when)})
    return out


def spoken_sender(name):
    """A sender as she'd say it: a number not in your contacts, like 914035072560, is "a number ending in 2 5 6 0"
    (she read one out as a twelve-digit number once)."""
    digits = re.sub(r"\D", "", str(name or ""))
    if len(digits) >= 6 and re.fullmatch(r"[\d\s()+.-]+", str(name).strip()):
        return "a number ending in " + " ".join(digits[-4:])
    return str(name or "someone")


def say_messages(found):
    """"Mum sent you a WhatsApp message." or "3 new messages on WhatsApp, from Mum and Ravi."."""
    by_app = {}
    for n in found:
        by_app.setdefault(n["app"], []).append(n["from"])
    parts = []
    for app, senders in by_app.items():
        names = list(dict.fromkeys(spoken_sender(s) for s in senders))
        if len(senders) == 1:
            parts.append(f"{names[0]} sent you a message on {app}")
        else:
            who = names[0] if len(names) == 1 else ", ".join(names[:-1][:2]) + " and " + names[-1]
            parts.append(f"{len(senders)} new messages on {app}, from {who}")
    return " ".join(p[:1].upper() + p[1:] + "." for p in parts)


def online():
    try:
        socket.create_connection(("opencode.ai", 443), timeout=3).close()
        return True
    except OSError:
        return False


class Watcher:
    """Call check() every 20 seconds or so: it returns what's worth saying now, each thing once."""

    def __init__(self):
        self.seen = time.time()  # messages before she started don't count
        self.added = last_added()  # when each message app last notified, so ones from before she started don't count
        self.waiting = {}  # app ID: (when it notified, when she noticed) for ones with nothing left in the list yet
        self.covered = {}  # app name: the newest notification of its she found in the list
        self.told = {}  # (app, sender) and app names: when she last said so, so two copies make one heads-up
        self.said = {}  # what was said, and when
        self.battery_warned = set()  # levels warned about since it was last plugged in
        self.busy = {"cpu": 0, "memory": 0}  # checks in a row it's been maxed out
        self.offline = 0  # checks in a row without the internet
        self.told_offline = False
        psutil.cpu_percent(None)

    def _once(self, key, every):
        if time.time() - self.said.get(key, 0) < every:
            return False
        self.said[key] = time.time()
        return True

    def _fresh(self, key, now):
        """True the first time something is said within SAME_MESSAGE, and notes it."""
        if now - self.told.get(key, 0) < SAME_MESSAGE:
            return False
        self.told[key] = now
        return True

    def messages(self, front=""):
        """A heads-up for messages that came in since the last look, or "". Light enough to call every few seconds.

        front is the app in front (or something that says which): you're already looking at that one's messages.
        From the list, she says who it's from. If the list lost it before she looked, she still says which app."""
        hour = time.localtime().tm_hour
        if hour >= QUIET[0] or hour < QUIET[1]:
            return ""
        now = time.time()
        found = notifications(self.seen)
        if found:
            # a microsecond past the newest one, because Windows' arrival time is in 100ns ticks and loses a couple
            # of them coming back through a float: without this she says the same message again
            self.seen = found[-1]["when"] + 1e-6
        for n in found:
            self.covered[n["app"]] = max(self.covered.get(n["app"], 0.0), n["when"])
        for app_id, when in last_added().items():  # what Windows noted, whatever happened to it afterwards
            if when > self.added.get(app_id, 0.0) + 1e-6:
                self.added[app_id] = when
                self.waiting[app_id] = (when, now)
        gone = []  # apps that notified, with nothing in the list for it a look later
        for app_id, (when, noticed) in list(self.waiting.items()):
            name = _app(app_id)[0]
            if self.covered.get(name, 0.0) >= when - 15:  # the list had it, or WhatsApp's other copy of it
                del self.waiting[app_id]
            elif noticed < now - 1.0:  # give the list one look to catch up before saying it without a name
                del self.waiting[app_id]
                gone.append(name)
        if not (found or gone):
            return ""
        front = (front() if callable(front) else front or "").lower()
        new = [n for n in found if n["app"].lower() not in front
               and self._fresh((n["app"], spoken_sender(n["from"])), now)]
        for n in new:
            self.told[n["app"]] = now  # so a WhatsApp copy that vanished doesn't make a second heads-up
        nameless = [a for a in dict.fromkeys(gone) if a.lower() not in front and self._fresh(a, now)]
        self.told = {k: t for k, t in self.told.items() if now - t < 2 * SAME_MESSAGE}
        parts = [say_messages(new)] if new else []
        if nameless:
            parts.append(f"You've got a new message on {' and '.join(nameless)}.")
        return " ".join(parts)

    def check(self, read_messages=True, front=""):
        lines, hour = [], time.localtime().tm_hour
        quiet = hour >= QUIET[0] or hour < QUIET[1]
        b = psutil.sensors_battery()
        if b and b.power_plugged:
            self.battery_warned.clear()
        elif b:
            for level in (10, 20):
                if b.percent <= level and level not in self.battery_warned:
                    self.battery_warned.update(l for l in (10, 20) if l >= level)
                    if level == 10 or not quiet:
                        lines.append(f"Battery's at {round(b.percent)} percent. " +
                                     ("Time to plug in." if level == 10 else "You might want to plug in soon."))
                    break
        if quiet:
            return lines
        if read_messages:
            line = self.messages(front)
            if line:
                lines.append(line)
        try:
            free = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").free / 1024 ** 3
            if free < 5 and self._once("disk", 12 * 3600):
                lines.append(f"Your C drive is nearly full, only {free:.1f} gigabytes left.")
        except OSError:
            pass
        cpu, ram = psutil.cpu_percent(None), psutil.virtual_memory().percent
        for kind, value, limit, line in (("cpu", cpu, 90, "Something's working the CPU flat out."),
                                         ("memory", ram, 92, "Memory's almost full.")):
            self.busy[kind] = self.busy[kind] + 1 if value >= limit else 0
            if self.busy[kind] >= 4 and self._once(kind, 1800):
                try:
                    import sysinfo
                    top = sysinfo.top_apps("cpu" if kind == "cpu" else "memory", 1)
                    line += f" {top[0]['app']} is using the most." if top else ""
                except Exception:
                    pass
                lines.append(line)
        if self._once("net", 60):  # the internet, once a minute
            if online():
                if self.told_offline:
                    lines.append("We're back online.")
                self.offline, self.told_offline = 0, False
            else:
                self.offline += 1
                if self.offline >= 2 and not self.told_offline:
                    self.told_offline = True
                    lines.append("We've lost the internet.")
        return lines
