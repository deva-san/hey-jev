"""Installing and updating apps, through winget, the package manager built into Windows 11.

She looks the app up in winget's own catalogue (never a website she found by searching, so never a fake download
page), picks the real one rather than a nightly or a plugin, checks whether it's already on this PC and how much
room is left, and reads it back: name, version, publisher. Nothing is installed until you say yes, and then it runs
as a background task, so she's free while it downloads.

The installer winget picks is the one that fits this PC (64-bit or Arm, and the newest stable version), and winget
checks its SHA-256 against the catalogue before it runs anything.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading

import winplatform as win

WINGET = shutil.which("winget") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps",
                                                "winget.exe")
COMMON = ["--accept-source-agreements", "--disable-interactivity"]
LOOK_TIMEOUT = 60  # search, show and list take a second or so
INSTALL_TIMEOUT = 30 * 60  # a big app on a slow line
MIN_FREE_GB = 1.0  # below this she won't start an install
LOW_FREE_GB = 3.0  # below this she mentions it
NAME = re.compile(r"[\w .+&'#-]{1,60}")
PACKAGE_ID = re.compile(r"[\w.+-]{2,120}")
# not what someone means by "install VLC", unless they said so
SIDE = re.compile(r"\b(?:nightly|beta|preview|insiders?|canary|dev|alpha|rc|test|portable|bridge|plugin|extension|"
                  r"addon|add-on|sdk|cli|server|helper|theme)\b", re.I)
ARCH = {"AMD64": "64-bit", "ARM64": "Arm 64-bit", "X86": "32-bit"}
SOURCES = ("winget", "msstore")
# what people say, and what the catalogue calls it
ALIASES = {"vs code": "Visual Studio Code", "vscode": "Visual Studio Code", "visual studio code": "Visual Studio Code",
           "java": "Temurin JDK", "jdk": "Temurin JDK", "node": "Node.js", "nodejs": "Node.js",
           "chrome": "Google Chrome", "edge": "Microsoft Edge", "teams": "Microsoft Teams", "office": "Microsoft 365",
           "word": "Microsoft Word", "excel": "Microsoft Excel", "obs": "OBS Studio", "vlc player": "VLC",
           "zip": "7-Zip", "7 zip": "7-Zip", "notepad plus plus": "Notepad++", "whats app": "WhatsApp"}
NO_PACKAGE = 0x8A150014  # winget: nothing matches
ALREADY = 0x8A15002B  # winget: already installed and nothing newer
REBOOT = (0x8A150109, 3010, 1641)  # winget or the installer: done, but Windows must restart to finish
LOCK = threading.Lock()  # winget installs one thing at a time anyway


class NotFound(RuntimeError):
    pass


def available():
    return bool(WINGET) and os.path.exists(WINGET)


def _run(args, timeout=LOOK_TIMEOUT, cancelled=None):
    """(exit code as an unsigned number, output). Arguments go straight to winget, never through a shell."""
    if not available():
        raise RuntimeError("winget isn't on this PC, so I can't install apps")
    p = subprocess.Popen([WINGET, *args, *COMMON], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=win.CREATE_NO_WINDOW)
    try:
        if cancelled is None:
            out, _ = p.communicate(timeout=timeout)
        else:  # an install: check now and then whether you cancelled it in the Tasks tab
            waited, out = 0, b""
            while True:
                try:
                    out, _ = p.communicate(timeout=2)
                    break
                except subprocess.TimeoutExpired:
                    waited += 2
                    if cancelled() or waited >= timeout:
                        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True,
                                       creationflags=win.CREATE_NO_WINDOW)
                        p.communicate()
                        raise RuntimeError("cancelled" if cancelled() else "it took too long, so I stopped it")
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        raise RuntimeError("winget didn't answer in time")
    text = out.decode("utf-8", "replace")
    text = "\n".join(line.rsplit("\r", 1)[-1] for line in text.splitlines())  # progress bars redraw with \r
    return p.returncode & 0xFFFFFFFF, text


def _table(text):
    """winget's table as dicts, by its own column headings: Name, Id, Version, and Available or Source if shown."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^-{10,}\s*$", line.strip()) and i > 0:
            head = lines[i - 1]
            names = re.findall(r"\S+", head)
            starts = [head.index(n) for n in names] if names else []
            rows = []
            for row in lines[i + 1:]:
                if not row.strip():
                    continue
                cells = [row[s:(starts[k + 1] if k + 1 < len(starts) else None)].strip() for k, s in enumerate(starts)]
                rows.append(dict(zip(names, cells)))
            return rows
    return []


def clean_name(name):
    name = " ".join(str(name or "").split()).strip(" .")
    if not NAME.fullmatch(name):
        raise ValueError("that isn't an app name I can look up")
    return name


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _score(want, row):
    """Higher is a better match for what you said. None: not what you meant."""
    name, pid = _norm(row.get("Name", "")), row.get("Id", "")
    tail = _norm(pid.split(".")[-1])
    w = _norm(want)
    maker = _norm(pid.split(".")[0]) if "." in pid else ""
    if maker and name.startswith(maker + " ") and not w.startswith(maker) and name[len(maker) + 1:] == w:
        # "Microsoft Visual Studio Code" is what you mean by "Visual Studio Code", but a shade under a name that's
        # exactly it, or "Stackless Python" would beat Python itself
        name, exact_after_maker = w, True
    else:
        exact_after_maker = False
    if not w or not pid or not PACKAGE_ID.fullmatch(pid):
        return None
    if SIDE.search(f"{row.get('Name', '')} {pid}") and not SIDE.search(want):
        return None
    if name == w or tail == w.replace(" ", ""):
        score = 95 if exact_after_maker else 100
    elif name.startswith(w + " ") or name.startswith(w):
        score = 80
    elif w in name.split() or all(part in name.split() for part in w.split()):
        score = 60
    elif w.replace(" ", "") in name.replace(" ", "") or w.replace(" ", "") in _norm(pid).replace(" ", ""):
        score = 40
    else:
        return None
    if _norm(pid.split(".")[0]).replace(" ", "") == w.replace(" ", ""):
        score += 15  # published by who you named: Telegram.TelegramDesktop over someone's telegram-owl
    if re.search(r"\s+v?\d+(?:\.\d+)*$", str(row.get("Name", "")).strip()):
        # "Python 2", "Python 3.14", "Temurin JDK 8", "... 25": the same app in versions, so the newest one
        parts = (_version_key(row.get("Version")) + [0, 0, 0])[:3]
        return score + 1 + sum(p / 1000 ** i for i, p in enumerate(parts)) / 100
    return score - len(name) / 100  # "VLC media player" over a longer name with VLC in it


def _version_key(text):
    return [int(p) for p in re.findall(r"\d+", str(text))[:4]]


def _search(name, source):
    try:
        code, text = _run(["search", "--query", name, "--source", source])
    except RuntimeError:
        return []
    return [{**r, "source": source} for r in (_table(text) if code != NO_PACKAGE else [])]


def find(name):
    """The package you most likely mean, then up to two others: [{"id", "name", "version", "source"}].

    winget's own catalogue and the Microsoft Store are searched at once: some apps, like WhatsApp, are only in the
    Store. On a tie winget's wins, since it checks the download's SHA-256. NotFound if neither has it."""
    name = clean_name(name)
    query = ALIASES.get(" ".join(name.lower().split()), name)

    def ranked(rows):
        out = [(s + (5 if r["source"] == "winget" else 0), r) for r in rows if (s := _score(query, r)) is not None]
        return sorted(out, key=lambda x: -x[0])

    # one after the other: two winget searches at once trip over each other and one comes back empty
    scored = ranked(_search(query, "winget"))
    if not scored or scored[0][0] < 100:  # nothing that plainly is it, so the Store too (WhatsApp is only there)
        scored = ranked([r for _, r in scored] + _search(query, "msstore"))
    if not scored:
        raise NotFound(f"I couldn't find {name} in winget or the Microsoft Store")
    return [{"id": r["Id"], "name": r.get("Name") or r["Id"], "version": r.get("Version", ""), "source": r["source"]}
            for _, r in scored[:3]]


def label(name, version):
    """"Python 3.14" and 3.14.0 read as Python 3.14.0, not Python 3.14 3.14.0."""
    name, version = str(name or "").strip(), str(version or "").strip()
    m = re.search(r"\s+v?(\d+(?:\.\d+)*)$", name)
    if m and version.startswith(m.group(1)):
        name = name[:m.start()]
    return f"{name} {version}".strip() if version and version.lower() != "unknown" else name


def fits(info):
    """Which build winget picked for this PC, from its download link where that says, else just that it fits."""
    url = str(info.get("installer_url", "")).lower()
    if re.search(r"arm64|aarch64", url):
        return "the Arm 64-bit version for this PC"
    if re.search(r"x64|win64|amd64|x86_64|64-?bit", url):
        return "the 64-bit version for this PC"
    if re.search(r"x86|win32|ia32|32-?bit", url):
        return "a 32-bit version, the one there is for this PC"
    return "the version winget picks for this PC"


def details(package_id, source="winget"):
    """What winget knows about it: version, publisher, installer type, and its homepage."""
    if not PACKAGE_ID.fullmatch(str(package_id or "")) or source not in SOURCES:
        raise ValueError("not a package id")
    code, text = _run(["show", "--id", package_id, "--exact", "--source", source])
    if code:
        raise RuntimeError(f"winget couldn't show {package_id}")
    info = {"id": package_id}
    first = re.search(r"^Found (.+?) \[" + re.escape(package_id) + r"\]", text, re.M)
    info["name"] = first.group(1).strip() if first else package_id
    for key in ("Version", "Publisher", "Homepage", "License", "Installer Type", "Installer Url"):
        m = re.search(rf"^\s*{re.escape(key)}:\s*(.+)$", text, re.M)
        if m:
            info[key.lower().replace(" ", "_")] = m.group(1).strip()
    return info


def installed(package_id):
    """{"version", "available"} if it's on this PC (available: a newer version, or ""), else None."""
    code, text = _run(["list", "--id", package_id, "--exact"])
    if code == NO_PACKAGE or code:
        return None
    rows = _table(text)
    if not rows:
        return None
    row = rows[0]
    return {"version": row.get("Version", ""), "available": row.get("Available", "")}


def free_gb():
    try:
        return shutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").free / 1024 ** 3
    except OSError:
        return None


def this_pc():
    """How she describes the installer that fits this PC."""
    arch = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE", "")
    return ARCH.get(arch.upper(), "")


def prepare(name):
    """Everything she needs to ask "Install VLC media player 3.0.24 from VideoLAN?": a dict, or an exception whose
    message is what to say. Nothing is downloaded or changed here."""
    picks = find(name)
    best = picks[0]
    info = details(best["id"], best["source"])
    have = installed(best["id"])
    free = free_gb()
    action = "install"
    if have:
        if not have["available"]:
            return {"action": "none", "id": best["id"], "name": info["name"], "have": have["version"],
                    "say": f"{label(info['name'], have['version'])} is already installed, and that's the latest."}
        action = "upgrade"
    if free is not None and free < MIN_FREE_GB:
        raise RuntimeError(f"your C drive only has {free:.1f} gigabytes free, which isn't enough to install it safely")
    others = [p["name"] for p in picks[1:] if p["name"] != info["name"]]
    version = info.get("version", best["version"])
    return {"action": action, "id": best["id"], "source": best["source"], "name": info["name"],
            "version": "" if version.lower() == "unknown" else version, "publisher": info.get("publisher", ""),
            "have": have["version"] if have else "", "available": have["available"] if have else "",
            "type": info.get("installer_type", ""), "free": free, "others": others,
            "fits": "from the Microsoft Store" if best["source"] == "msstore" else fits(info)}


def question(ready):
    """What she reads back before installing, so you can say yes, no, or "the other one"."""
    who = f" from {ready['publisher']}" if ready.get("publisher") else ""
    if ready["action"] == "upgrade":
        line = (f"{label(ready['name'], ready['have'])} is installed, and "
                f"{ready.get('available') or ready['version']} is out{who}. Update it?")
    else:
        line = f"{label(ready['name'], ready['version'])}{who}, {ready.get('fits') or 'for this PC'}. Install it?"
    if ready.get("free") is not None and ready["free"] < LOW_FREE_GB:
        line += f" Your C drive is down to {ready['free']:.1f} gigabytes."
    return line


def install(ready, cancelled=None):
    """Install or update it. (done, what to say). Only ever called after a yes, from the background worker."""
    pid = ready["id"]
    if not PACKAGE_ID.fullmatch(str(pid or "")):
        raise ValueError("not a package id")
    verb = "upgrade" if ready.get("action") == "upgrade" else "install"
    source = ready.get("source") or "winget"
    if source not in SOURCES:
        raise ValueError("not a source I know")
    args = [verb, "--id", pid, "--exact", "--source", source, "--silent", "--accept-package-agreements"]
    if verb == "install" and ready.get("version") and source == "winget":
        args += ["--version", ready["version"]]  # exactly what she read back, not whatever is newest by then
    with LOCK:
        code, text = _run(args, INSTALL_TIMEOUT, cancelled or (lambda: False))
    tail = [l.strip() for l in text.splitlines() if l.strip()][-3:]
    if code == 0:
        try:
            win.start_apps(refresh=True)  # so "open VLC" finds it straight away
        except Exception:
            pass
        new = ready.get("available") if verb == "upgrade" else ready.get("version")
        if verb == "upgrade":
            return True, f"{ready['name']} is updated" + (f" to {new}." if new else "."), text
        return True, f"{label(ready['name'], new)} is installed.", text
    if code in REBOOT:
        return True, f"{ready['name']} is installed, but Windows needs a restart to finish it.", text
    if code == ALREADY:
        return True, f"{ready['name']} was already up to date.", text
    why = tail[-1] if tail else f"winget stopped with code {code:#x}"
    if re.search(r"cancel|denied|1602|0x80070005", why, re.I):
        why = "the install was cancelled, maybe at Windows' permission prompt"
    return False, f"{ready['name']} didn't install: {why}", text
