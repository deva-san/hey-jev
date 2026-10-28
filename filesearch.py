"""Finding your files, the way Nixi (heynixi.com) does: "find my resume", "where's the invoice PDF?", "open the
CareerID offer letter". Asks Windows Search's own index, the one the Start menu searches, so it answers in under a
second and reads nothing new off the disk. Only file names are matched, never what's inside them.

What it finds stays on this PC; the model is only told names, folders and dates when it was the one that asked.
Your phone's files that Phone Link shows in File Explorer (the CrossDevice folder) are only searched when you say
"on my phone": opening one fetches it from the phone.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import threading
import time

import winplatform as win

HOME = os.path.expanduser("~")
PHONE = os.path.join(HOME, "CrossDevice")
MAX_FOUND = 8
ROWS = 1000  # asked of the index at most, newest first: a name like "readme" is in thousands of code packages
# folders that are full of files nobody means: apps' own data, code's packages, caches and the bin
SKIP = re.compile(r"\\(?:AppData|node_modules|\.git|\.venv|venv|site-packages|__pycache__|\.next|\.cache|\.bun|"
                  r"\.cargo|\.rustup|\.m2|\.gradle|\.nuget|\.idea|\.vscode|\$Recycle\.Bin|Temp|tmp|target|dist|obj|"
                  r"npm-cache|pipx)(?:\\|$)", re.I)  # target, dist, obj: what building code leaves, copies of its folders
# folders in your user folder that aren't yours to search: Windows' own, and the phone's unless you say so
NOT_YOURS = {"appdata", "crossdevice", "contacts", "favorites", "links", "searches", "saved games", "3d objects"}
# folders inside a program's code: a resume in a website's uploads folder is someone else's, not yours
MADE = re.compile(r"\\(?:src|uploads?|public|static|assets|resources|build|out|bin|vendor|packages|lib|tests?|"
                  r"fixtures|backend|frontend|www)\\", re.I)
# names a program gave a file: a GUID or a long run of hex in front of it
MACHINE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{16,}", re.I)
# Words that say what kind of file, and the extensions they mean
KINDS = {
    "picture": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp"), "photo": None, "image": None,
    "screenshot": None, "video": (".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv"), "movie": None,
    "song": (".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg"), "music": None, "audio": None,
    "pdf": (".pdf",), "word": (".docx", ".doc"), "doc": None, "docx": None,
    "document": (".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".odt"),
    "excel": (".xlsx", ".xls", ".csv"), "spreadsheet": None, "sheet": None, "csv": (".csv",),
    "presentation": (".pptx", ".ppt"), "powerpoint": None, "ppt": None, "slides": None, "deck": None,
    "zip": (".zip", ".rar", ".7z"), "text": (".txt", ".md"),
}
for _alias, _of in (("photo", "picture"), ("image", "picture"), ("screenshot", "picture"), ("movie", "video"),
                    ("music", "song"), ("audio", "song"), ("doc", "word"), ("docx", "word"), ("spreadsheet", "excel"),
                    ("sheet", "excel"), ("powerpoint", "presentation"), ("ppt", "presentation"),
                    ("slides", "presentation"), ("deck", "presentation")):
    KINDS[_alias] = KINDS[_of]
NAMED_KINDS = {"screenshot"}  # a kind that's in the name too: Windows calls them "Screenshot 2026-10-12 101010.png"
FOLDER_WORDS = {"folder", "folders", "directory", "directories"}
YOURS = {e for k in ("picture", "video", "song", "document", "excel", "presentation", "zip") for e in KINDS[k]}
CODE = {".java", ".class", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".py", ".pyc", ".css", ".scss", ".html", ".json",
        ".xml", ".yml", ".yaml", ".go", ".rs", ".kt", ".c", ".cpp", ".h", ".cs", ".rb", ".php", ".sql", ".map", ".lock"}
STOP = {"my", "the", "a", "an", "file", "files", "called", "named", "that", "this", "those", "these", "which", "is",
        "are", "of", "for", "about", "from", "in", "on", "with", "and", "or", "some", "any", "all", "last", "latest",
        "recent", "newest", "new", "old", "i", "me", "please", "pc", "computer", "laptop", "phone", "mobile",
        "downloaded", "saved", "made", "got", "it", "one", "where", "find", "search", "look", "locate", "open", "show",
        "dot", "did", "put", "keep", "kept", "save", "download", "get", "up"}
# She opens documents, pictures, videos, songs and archives straight away. Anything else found this way, a program, a
# script, a shortcut, code, only gets its folder opened with it picked out: a name heard wrong must never run something.
OPENS = YOURS | {".ods", ".odp", ".epub", ".tif", ".tiff"}
SAID_KIND = {".pdf": "a PDF", ".docx": "a Word file", ".doc": "a Word file", ".xlsx": "a spreadsheet",
             ".xls": "a spreadsheet", ".csv": "a spreadsheet", ".pptx": "a presentation", ".ppt": "a presentation",
             ".txt": "a text file", ".md": "a text file", ".rtf": "a document", ".odt": "a document",
             ".zip": "a zip file", ".rar": "a zip file", ".7z": "a zip file", ".exe": "a program", ".msi": "an installer",
             **{e: "a picture" for e in KINDS["picture"]}, **{e: "a video" for e in KINDS["video"]},
             **{e: "a song" for e in KINDS["song"]}}
# Windows' own names for where your folders are, wherever they've been moved to (Downloads may be on D:)
SHELL_FOLDERS = {"Desktop": "Desktop", "Personal": "Documents", "{374DE290-123F-4565-9164-39C4925E467B}": "Downloads",
                 "My Pictures": "Pictures", "My Video": "Videos", "My Music": "Music"}
FOUND = {"items": [], "at": 0.0}  # what she found last, for "open the first one"
FOUND_FOR = 600.0  # seconds that list counts
_lock = threading.Lock()
_known = {}


def known_folders():
    """{path: "Downloads"} for your Desktop, Documents, Downloads, Pictures, Videos, Music and OneDrive."""
    if not _known:
        found = {}
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
                for value, name in SHELL_FOLDERS.items():
                    try:
                        found[os.path.normpath(winreg.QueryValueEx(key, value)[0])] = name
                    except OSError:
                        pass
        except (ImportError, OSError):
            pass
        for name in SHELL_FOLDERS.values():  # where they are when Windows didn't say
            if name not in found.values():
                found[os.path.join(HOME, name)] = name
        if os.environ.get("OneDrive"):
            found.setdefault(os.path.normpath(os.environ["OneDrive"]), "OneDrive")
        _known.update(found)
    return dict(_known)


def scopes(phone=False):
    """Where to look: your own folders in your user folder (not AppData, Windows' own or the phone's), your known
    folders wherever they are, and D:. With phone, only the phone's."""
    if phone:
        return [PHONE]
    out = []
    try:
        names = sorted(os.listdir(HOME))
    except OSError:
        names = []
    for name in names:
        path = os.path.join(HOME, name)
        try:
            st = os.stat(path, follow_symlinks=False)
        except OSError:
            continue
        attrs = getattr(st, "st_file_attributes", 0)
        hidden = attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM | stat.FILE_ATTRIBUTE_REPARSE_POINT)
        if stat.S_ISDIR(st.st_mode) and not hidden and not name.startswith(".") and \
                name.lower() not in NOT_YOURS and not SKIP.search("\\" + name):
            out.append(path)
    if os.path.isdir("D:\\"):
        out.append("D:\\")
    for path in known_folders():
        inside = any(os.path.normcase(path).startswith(os.path.normcase(s.rstrip("\\")) + "\\") for s in out)
        if os.path.isdir(path) and not inside and os.path.normcase(path) not in map(os.path.normcase, out):
            out.append(path)
    return out


def terms(said):
    """(name words, extensions, folders only, phone) from what was said: "my latest resume pdf" -> (["resume"],
    (".pdf",), False, False)."""
    words = re.findall(r"[\w'.+-]+", str(said or "").lower())
    phone = bool({"phone", "mobile"} & set(words))
    exts, folder, keep = [], False, []
    for w in words:
        w = w.strip(".'")
        if w not in KINDS and w.endswith("s") and w[:-1] in KINDS:  # "pdfs", "photos", "screenshots"
            w = w[:-1]
        if w in FOLDER_WORDS:
            folder = True
        elif w in KINDS:
            exts += [e for e in KINDS[w] if e not in exts]
            if w in NAMED_KINDS:
                keep.append(w)
        elif w.startswith(".") and w in {e for v in KINDS.values() for e in v}:
            exts.append(w)
        elif w and w not in STOP and re.search(r"\w", w):
            keep.append(w)
    return keep[:5], tuple(exts), folder, phone


def _like(word):
    """A word for Windows Search's LIKE: only letters, digits and a few marks, its wildcards escaped."""
    word = re.sub(r"[^\w .+-]", "", word)
    return word.replace("[", "[[]").replace("_", "[_]").replace("%", "[%]")


def _query(words, exts, folder, phone, top):
    """The index is asked for the longest word in the file's name; the rest may be in its folders too, which search
    checks: "hey jev readme" is README.md in hey-jev. Only your own folders are looked in (scopes): leaving the
    others out in the query itself takes the index seconds."""
    def text(s):  # a value inside '...', as SQL has it: a quote in a folder name (O'Brien) doubled
        return str(s).replace("'", "''")
    where = ["(" + " OR ".join(f"SCOPE='file:{text(p.replace(os.sep, '/'))}'" for p in scopes(phone)) + ")"]
    where += [f"System.FileName LIKE '%{_like(w)}%'" for w in sorted(words, key=len)[-1:] if _like(w)]
    if exts:
        where.append("(" + " OR ".join(f"System.FileExtension = '{text(e)}'" for e in exts) + ")")
    if folder:
        where.append("System.Kind = 'folder'")
    return (f"SELECT TOP {int(top)} System.ItemPathDisplay, System.DateModified, System.Size FROM SystemIndex "
            f"WHERE {' AND '.join(where)} ORDER BY System.DateModified DESC")


def _ask_index(sql):
    """Rows from Windows Search's index: [(path, modified as seconds since 1970, size)]."""
    win._com()
    import comtypes.client
    con = comtypes.client.CreateObject("ADODB.Connection")
    con.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
    try:
        rs = comtypes.client.CreateObject("ADODB.Recordset")
        rs.Open(sql, con)
        try:
            if rs.EOF:
                return []
            paths, modified, sizes = rs.GetRows()  # all at once, a column each: one call, not three a row
        finally:
            rs.Close()
        return [(str(p), m.timestamp() if hasattr(m, "timestamp") else 0.0, int(s or 0))
                for p, m, s in zip(paths, modified, sizes)]
    finally:
        con.Close()


def _flat(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split())


def _score(path, words):
    """(how well a file matches the words, every word is in its name, its name is just them), or None if one of them
    is nowhere in its name or folders. Every word in the name beats some in its folders, and a name that's just them
    beats one with more; search puts the newest first among equally good ones."""
    base = os.path.splitext(os.path.basename(path))[0]
    name = _flat(base).replace(" ", "")
    rel = os.path.relpath(path, HOME) if path.lower().startswith(HOME.lower()) else path
    whole = _flat(rel).replace(" ", "")
    flat = [_flat(w).replace(" ", "") for w in words]
    if not all(w in whole for w in flat):
        return None
    named = all(w in name for w in flat)
    exact = name == "".join(flat)
    return (2 if named else 1) + (0.5 if exact else 0), named, exact


# where each kind of file of yours lives, so "my photos" are the ones in Pictures, not a program's icons
OWN_PLACE = {**{e: "Pictures" for e in KINDS["picture"]}, **{e: "Videos" for e in KINDS["video"]},
             **{e: "Music" for e in KINDS["song"]}}


def _inside(folder, root):
    f, r = os.path.normcase(os.path.normpath(folder)), os.path.normcase(os.path.normpath(root))
    return f == r or f.startswith(r.rstrip(os.sep) + os.sep)


def _depth(folder):
    """How many folders down it is from your user folder, or from where a known folder of yours was moved to:
    Desktop\\Harish Doc is 2."""
    roots = sorted({HOME, *(os.path.dirname(p) for p in known_folders())}, key=len, reverse=True)
    root = next((r for r in roots if _inside(folder, r)), os.path.splitdrive(folder)[0] + os.sep)
    rel = os.path.relpath(folder, root) if _inside(folder, root) else folder
    return 0 if rel in (".", "") else rel.count(os.sep) + 1


def _yours(path, is_dir=False, want_folder=False):
    """More for what people mean by "my resume", a document or a photo, near the top of their folders; less for a
    programmer's Resume.java, a file deep in a program's folders or its uploads, a name a program gave it, or a folder
    when a file was asked for."""
    ext = "" if is_dir else os.path.splitext(path)[1].lower()
    kind = 0.5 if ext in YOURS else -1.5 if ext in CODE else 0.0
    if is_dir and not want_folder:
        kind -= 0.5
    if MADE.search(path):
        kind -= 0.7
    if MACHINE.search(os.path.basename(path)):
        kind -= 1.0
    kind -= min(0.8, 0.1 * max(0, _depth(os.path.dirname(path)) - 3))
    place = OWN_PLACE.get(ext)
    if place and any(name == place and _inside(os.path.dirname(path), p) for p, name in known_folders().items()):
        kind += 0.5
    return kind


def search(said, limit=MAX_FOUND, remember=True):
    """The files that match what was said, best first: [{"path", "name", "folder", "modified", "size", "is_dir",
    "named", "exact"}] (see _score). Remembered for "open the first one", unless not remember: then keep_found does
    it, once she's said what she found. RuntimeError if Windows Search can't be asked."""
    words, exts, folder, phone = terms(said)
    if not words and not exts:
        raise ValueError("I didn't catch what file to look for")
    sql = _query(words, exts, folder, phone, ROWS)
    for attempt in (1, 2):  # its first connection in a while now and then fails, and the next one works
        try:
            rows = _ask_index(sql)
            break
        except Exception as exc:
            if attempt == 2:
                raise RuntimeError("Windows Search isn't answering, so I can't look through your files") from exc
            time.sleep(0.3)
    found = []
    for path, when, size in rows:
        if SKIP.search(path) or (not phone and path.lower().startswith(PHONE.lower())):
            continue
        hit = _score(path, words) if words else (1.0, False, False)  # "my pdfs": any of that kind
        if hit is None:
            continue
        is_dir = os.path.isdir(path)
        found.append({"path": path, "name": os.path.basename(path), "folder": os.path.dirname(path),
                      "modified": when, "size": size, "is_dir": is_dir,
                      "score": round(hit[0] + _yours(path, is_dir, folder), 2), "named": hit[1], "exact": hit[2]})
    found.sort(key=lambda f: (-f["score"], -f["modified"]))  # newest first among equally good matches
    found = found[:limit]
    if remember:
        keep_found(found)
    return found


def keep_found(found):
    """What she found and said, for "open the first one" in the next few minutes."""
    with _lock:
        FOUND.update(items=list(found), at=time.time())


def recent():
    """What she found last, if it was in the last few minutes."""
    with _lock:
        return list(FOUND["items"]) if time.time() - FOUND["at"] < FOUND_FOR else []


def where(folder):
    """Where a folder is, as she'd say it: "on your Desktop", "in Harish Doc, on your Desktop", "in your Downloads",
    "on your phone", "on the D drive", or in the folder's own name."""
    f = os.path.normcase(os.path.normpath(folder))
    phone = os.path.normcase(PHONE)
    if f == phone or f.startswith(phone + os.sep):
        return "on your phone"
    for path, name in sorted(known_folders().items(), key=lambda kv: -len(kv[0])):  # OneDrive\Documents is Documents
        p = os.path.normcase(path)
        if f == p or f.startswith(p + os.sep):
            top = "on your Desktop" if name == "Desktop" else f"in your {name}"
            return top if f == p else f"in {os.path.basename(os.path.normpath(folder))}, {top}"
    if f == os.path.normcase(HOME):
        return "in your user folder"
    drive, rest = os.path.splitdrive(os.path.normpath(folder))
    if rest in ("", os.sep):
        return f"on the {drive.rstrip(':')} drive" if drive else "on this PC"
    return f"in {os.path.basename(os.path.normpath(folder))}"


def ago(when):
    if not when:
        return ""
    days = int((time.time() - when) // 86400)
    return "today" if days < 1 else "yesterday" if days < 2 else f"{days} days ago" if days < 14 else \
        time.strftime("on %d %B %Y", time.localtime(when)).replace(" 0", " ")


def spoken(item, kind=True):
    """A file's name as she says it: "CareerID Offer Letter, a PDF" for CareerID_Offer_Letter.pdf, without the GUID
    a program put in front. kind: with what kind of file it is."""
    if item.get("is_dir"):
        base, ext = item["name"], ""
    else:
        base, ext = os.path.splitext(item["name"])
    words = " ".join(MACHINE.sub(" ", base).replace("_", " ").split()).strip(" -.") or item["name"]
    if not kind:
        return words
    if item.get("is_dir"):
        return f"the {words} folder"
    said = SAID_KIND.get(ext.lower()) or (f"a {ext[1:].upper()} file" if ext else "")
    return f"{words}, {said}" if said else words


def said(found, said_for):
    """What she says about what she found: the best one and where it is, and two more, without saying the same
    folder again ("I found 8 in Screenshots, in your Pictures. The best match is ...")."""
    if not found:
        return f"I couldn't find a file called \u201c{' '.join(str(said_for).split())}\u201d on this PC."
    top = found[0]
    when = f", changed {ago(top['modified'])}" if top["modified"] else ""
    if len(found) == 1:
        return f"I found {spoken(top)} {where(top['folder'])}{when}. Want me to open it?"
    if all(f["folder"] == top["folder"] for f in found[1:]):
        return (f"I found {len(found)} {where(top['folder'])}. The best match is {spoken(top)}{when}. Want me to "
                "open it?")
    others = " and ".join(spoken(f) + ("" if f["folder"] == top["folder"] else f" {where(f['folder'])}")
                          for f in found[1:3])
    return (f"I found {len(found)}. The best match is {spoken(top)} {where(top['folder'])}{when}. Also {others}. "
            "Want me to open the first one?")


def for_model(found):
    """What she found, for the model: names, folders and dates, numbered as she'd say them."""
    return [{"n": n, "name": f["name"], "where": where(f["folder"]), "changed": ago(f["modified"]),
             "folder": f["is_dir"]} for n, f in enumerate(found, 1)]


def pick(n=1, path=None):
    """One of what she found last: by its place in the list, or by its path. LookupError if there's nothing."""
    found = recent()
    if path:
        hit = next((f for f in found if os.path.normcase(f["path"]) == os.path.normcase(str(path))), None)
        if hit is None:
            raise LookupError("I can only open a file I've just found for you")
        return hit
    if not found:
        raise LookupError("I haven't looked for any files just now")
    if not 0 < n <= len(found):
        raise LookupError(f"I only found {len(found)}")
    return found[n - 1]


def open_found(item, folder=False):
    """Open what she found: a document or folder as you'd double-click it, a program only as its folder with it
    picked out (see OPENS). folder: show where it is instead."""
    path = item["path"]
    if not os.path.exists(path):
        raise RuntimeError(f"{item['name']} isn't there any more")
    if folder or (not item.get("is_dir") and os.path.splitext(path)[1].lower() not in OPENS):
        subprocess.Popen(["explorer.exe", f"/select,{path}"], creationflags=win.CREATE_NO_WINDOW)
        return "folder"
    if item.get("is_dir"):
        win.open_folder(path)
        return "folder"
    os.startfile(path)
    return "file"
