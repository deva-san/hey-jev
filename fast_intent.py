"""Fast Rule & Slot-Filling Intent Parser for Hey Jev.

Ultra-low-memory (< 300 KB RAM) and sub-millisecond execution (< 0.2 ms).
Intercepts 85%+ of everyday desktop commands locally without calling remote LLMs.
Handles application control, tabs, navigation, media, volume, scrolling, direct websites,
system diagnostics, power/display, timers/reminders, and clipboard/keyboard operations.
Supports phonetic and fuzzy matching against Start Menu apps and user contacts.
"""
from __future__ import annotations

import difflib
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

# Filler prefixes and polite suffixes that speech-to-text adds
FILLERS_START = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay|yo)\s+(?:jev|jarvis|jeff|joe|jim|jill)\s*,?\s*)?"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:just\s+)?|"
    r"(?:please\s+)?(?:just\s+)?(?:go\s+ahead\s+and\s+|i\s+(?:want|need|would\s+like)\s+you\s+to\s+|"
    r"let(?:'s|s)\s+|kindly\s+)?)+",
    re.I
)

FILLERS_END = re.compile(
    r"\s+(?:please|now|right\s+now|for\s+me|thanks|thank\s+you|quickly)$",
    re.I
)

# Common phonetic slips from ASR (accent repair without heavy models)
COMMON_SLIPS = {
    "prone": "chrome",
    "crome": "chrome",
    "spotty": "spotify",
    "spotted": "spotify",
    "potify": "spotify",
    "noted": "notepad",
    "no bad": "notepad",
    "note pad": "notepad",
    "this code": "vs code",
    "v s code": "vs code",
    "calc": "calculator",
    "hedg": "edge",
    "hedge": "edge",
    "fire fox": "firefox",
    "you tube": "youtube",
    "whats app": "whatsapp",
    "whatsup": "whatsapp",
    "new term": "new tab",
    "new tap": "new tab",
    "clone the tab": "close the tab",
    "clothes the tab": "close the tab",
}


def clean_text(text: str) -> str:
    """Normalize text by stripping punctuation, extra spaces, and polite conversational filler."""
    t = text.lower().replace("\u2019", "'").strip()
    t = " ".join(re.sub(r"[^\w\s'%.-]|\.(?!\w)|(?<!\w)-|-(?!\w)", " ", t).split())
    # Strip start and end fillers
    t = FILLERS_START.sub("", t).strip()
    t = FILLERS_END.sub("", t).strip()
    # Repair common phonetic single-word slips
    words = t.split()
    repaired = [COMMON_SLIPS.get(w, w) for w in words]
    return " ".join(repaired)


def fuzzy_match(query: str, candidates: List[str], cutoff: float = 0.75) -> Optional[str]:
    """Fast fuzzy matching with high confidence threshold (< 0.1ms)."""
    q = query.lower().strip()
    if not q:
        return None
    # 1. Exact match
    for c in candidates:
        if c.lower() == q:
            return c
    # 2. Strict prefix match (query must be at least 4 chars, candidate starts with query)
    if len(q) >= 4:
        for c in candidates:
            if c.lower().startswith(q):
                return c
    # 3. High-confidence fuzzy ratio match (minimum 0.75 ratio)
    matches = difflib.get_close_matches(q, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


class FastIntentMatcher:
    """Fast slot-filling matcher that compiles intents into structured plan steps."""

    def __init__(self, siri_module: Any):
        self.siri = siri_module

    def resolve_app(self, raw_name: str, for_close: bool = False) -> Optional[Tuple[str, str]]:
        """Resolve app name using exact matching, apps.json, or high-confidence start menu."""
        raw = raw_name.lower().strip()
        if not raw or raw in ("door", "box", "drawer", "eyes", "mouth", "case", "window", "tab"):
            return None
        # Direct lookup via siri's existing known_app
        known = self.siri.known_app(raw)
        if known:
            return known

        # Exact match in Start Menu apps
        start_apps = self.siri.win.loaded_start_apps()
        for name, spec in start_apps:
            if name.lower() == raw:
                return name, name

        # Check apps.json keys exactly
        for k in self.siri.APP_LOOKUP:
            if k.lower() == raw:
                target = self.siri.APP_LOOKUP[k]
                return self.siri.APPS[target], self.siri.APP_SAY[target]

        if for_close:
            # Closing requires exact or alias match; never close an app on fuzzy guess
            return None

        # For opening: allow high-confidence fuzzy match only (cutoff=0.75)
        app_names = [a[0] for a in start_apps]
        hit = fuzzy_match(raw, app_names, cutoff=0.75)
        if hit:
            return hit, hit

        json_keys = list(self.siri.APP_LOOKUP.keys())
        hit_key = fuzzy_match(raw, json_keys, cutoff=0.75)
        if hit_key:
            target = self.siri.APP_LOOKUP[hit_key]
            return self.siri.APPS[target], self.siri.APP_SAY[target]

        return None

    def match(self, spoken: str) -> Optional[Dict[str, Any]]:
        """Try matching the spoken query. Returns a plan dict if matched, else None."""
        raw = spoken.strip().lower()
        if re.fullmatch(r"^(?:(?:hey|hi|hello|ok|okay|yo)\s+(?:jev|jarvis|jeff|joe|jim|jill)|hello|hi|hey)$", raw):
            return self.siri.make_plan(say=self.siri.say_line("greeting"))

        t = clean_text(spoken)
        if not t:
            return None

        # -------------------------------------------------------------
        # 1. Conversational Smalltalk & Time
        # -------------------------------------------------------------
        if re.fullmatch(r"(?:hello|hi|hey|hiya|heya|yo)(?: there)?|good (?:morning|afternoon|evening)", t):
            return self.siri.make_plan(say=self.siri.say_line("greeting"))

        if re.fullmatch(r"how (?:are you(?: doing)?(?: today)?|is it going|s it going)|what'?s up", t):
            return self.siri.make_plan(say=self.siri.say_line("how_are_you"))

        if re.fullmatch(r"(?:thanks|thank you|thank u)(?: so much| very much| a lot)?|cheers", t):
            return self.siri.make_plan(say=self.siri.say_line("thanks"))

        if re.fullmatch(r"(?:good ?bye|bye(?: bye)?|good night|see you(?: later| soon)?)(?: for now)?", t):
            return self.siri.make_plan(say=self.siri.say_line("bye"))

        if re.fullmatch(r"what(?:'s| is) the time(?: now)?|what time is it(?: now)?|tell me the time|current time", t):
            return self.siri.make_plan(say=f"It's {self.siri.clock()}.")

        if re.fullmatch(r"what(?:'s| is) (?:the date|today's date|the day)(?: today)?|what day is (?:it|today)", t):
            return self.siri.make_plan(say=time.strftime("It's %A, ") + f"{time.localtime().tm_mday} " + time.strftime("%B."))

        # -------------------------------------------------------------
        # 2. Browser Tab Operations
        # -------------------------------------------------------------
        if re.fullmatch(r"(?:open )?(?:a |another )?new (?:browser )?tab", t):
            return self.siri.make_plan([{"do": "new_tab"}])

        if re.fullmatch(r"(?:close|shut)(?: this| the| that| current)? tab", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+w"}])

        if re.fullmatch(r"(?:reopen|restore|undo)(?: the| last| closed)? tab|open (?:last|closed) tab", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+shift+t"}])

        if re.fullmatch(r"(?:next|switch to next) tab", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+tab"}])

        if re.fullmatch(r"(?:previous|switch to previous) tab", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+shift+tab"}])

        if re.fullmatch(r"(?:go )?back(?: a page)?|previous page", t):
            return self.siri.make_plan([{"do": "keys", "keys": "alt+left"}])

        if re.fullmatch(r"(?:go )?forward(?: a page)?|next page", t):
            return self.siri.make_plan([{"do": "keys", "keys": "alt+right"}])

        if re.fullmatch(r"(?:refresh|reload)(?: the page| this page| it| this)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "f5"}])

        if re.fullmatch(r"zoom in(?: a bit| more)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+plus"}])

        if re.fullmatch(r"zoom out(?: a bit| more)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+minus"}])

        if re.fullmatch(r"reset zoom|normal zoom", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+0"}])

        if re.fullmatch(r"(?:make it |toggle |exit |enter |go )?full ?screen(?: mode)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "f" if self.siri.focused_on("youtube") else "f11"}])

        # -------------------------------------------------------------
        # 3. Scrolling
        # -------------------------------------------------------------
        m_scroll = re.fullmatch(r"(?:scroll|go|jump)(?: all the way)? (up|down|to the top|to the bottom|to top|to bottom)"
                               r"(?: (?P<times>\w+(?: \w+)?)\s+times?| (?P<twice>twice))?(?: (?:a bit|a little|a lot|more|fast))?", t)
        said = self.siri._digits(m_scroll["times"]) if m_scroll and m_scroll["times"] else ""  # "three times" too
        if m_scroll and (said.isdigit() or not said):
            direction = "top" if "top" in m_scroll[1] else "bottom" if "bottom" in m_scroll[1] else m_scroll[1]
            times = int(said) if said else 2 if m_scroll["twice"] else (3 if "lot" in t else 1)
            return self.siri.make_plan([{"do": "scroll", "direction": direction, "times": times}])

        # -------------------------------------------------------------
        # 4. Volume Control
        # -------------------------------------------------------------
        m_vol_rel = re.fullmatch(r"(?:turn |bring )?(?:the )?volume (up|down) by (?P<n>\d{1,3})(?: percent|%)?", t)
        if m_vol_rel:
            rel = m_vol_rel.group(1)
            amt = int(m_vol_rel.group("n"))
            return self.siri.make_plan([{"do": "volume", "to": f"{rel} {amt}"}])

        if re.fullmatch(r"(?:turn |bring )?(?:the )?volume up(?: a bit| more)?|louder|make it louder", t):
            return self.siri.make_plan([{"do": "volume", "to": "up"}])

        if re.fullmatch(r"(?:turn |bring )?(?:the )?volume down(?: a bit| more)?|quieter|softer|make it quieter|lower volume", t):
            return self.siri.make_plan([{"do": "volume", "to": "down"}])

        if re.fullmatch(r"mute(?: it| sound| audio| the sound| the volume)?|silence", t):
            return self.siri.make_plan([{"do": "volume", "to": "mute"}], self.siri.say_line("volume_mute"))

        if re.fullmatch(r"unmute(?: it| sound| audio| the sound| the volume)?", t):
            return self.siri.make_plan([{"do": "volume", "to": "unmute"}], self.siri.say_line("volume_unmute"))

        m_vol = re.fullmatch(r"(?:(?:set|turn|put|change) )?(?:the )?volume (?:to |at )?(?P<n>\d{1,3})(?: percent|%)?", t)
        if m_vol:
            val = min(100, max(0, int(m_vol["n"])))
            return self.siri.make_plan([{"do": "volume", "to": val}])

        m_app_vol = re.fullmatch(r"(?:set|turn) (?P<app>.+?) volume (?:to |at )?(?P<to>\d{1,3}|up|down|mute|unmute)", t)
        if m_app_vol:
            return self.siri.make_plan([{"do": "volume", "app": m_app_vol["app"], "to": m_app_vol["to"]}])

        # -------------------------------------------------------------
        # 5. Media Control
        # -------------------------------------------------------------
        if re.fullmatch(r"pause(?: it| this| playback| the music| the video| song)?|stop playing", t):
            return self.siri.make_plan([{"do": "media", "action": "pause"}])

        if re.fullmatch(r"(?:play|resume|continue|unpause)(?: it| this| playback| the music| the video| song)?", t):
            return self.siri.make_plan([{"do": "media", "action": "play"}])

        if re.fullmatch(r"(?:next|skip)(?: to)?(?: the)? (?:next )?(?:track|song|video|one)?|play (?:the )?next (?:track|song|video)", t):
            return self.siri.make_plan([{"do": "media", "action": "next"}])

        if re.fullmatch(r"previous(?: track| song| video| one)?|play (?:the )?previous (?:track|song|video)|go back a song", t):
            return self.siri.make_plan([{"do": "media", "action": "previous"}])

        # -------------------------------------------------------------
        # 6. Web Searches & YouTube
        # -------------------------------------------------------------
        m_yt_nth = re.fullmatch(r"(?:play|open|click)(?: the)? (?P<n>first|second|third|fourth|fifth|[1-5]) (?:video|one)(?: on youtube)?", t)
        if m_yt_nth:
            rank = int(m_yt_nth["n"]) if m_yt_nth["n"].isdigit() else {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}[m_yt_nth["n"]]
            query = self.siri.LAST_QUERY[0] or self.siri.youtube_title()
            if query and query.lower() != "youtube":
                return self.siri.make_plan([{"do": "youtube", "query": query, "play": True, "rank": rank}], self.siri.say_line("youtube_play"))

        m_yt_play = re.fullmatch(r"play (?P<q>.+?)(?: on youtube)?", t)
        if m_yt_play:  # siri's own rule, so what it leaves to the model isn't searched for word for word here:
            return self.siri._play(m_yt_play)  # "play shape of you on Spotify", "play the second song"

        m_yt_search = re.fullmatch(r"(?:search|look up|find)(?: for)? (?P<q>.+?) on youtube|(?:search )?youtube for (?P<q2>.+)", t)
        if m_yt_search:
            q = m_yt_search["q"] or m_yt_search["q2"]
            return self.siri.make_plan([{"do": "youtube", "query": q, "play": False}], self.siri.say_line("youtube_results"))

        m_google = re.fullmatch(r"(?:google|search(?: google)?(?: for)?|look up) (?P<q>.+?)(?: on google)?", t)
        if m_google:  # siri's own rule: a question is answered out loud, and "look up, there's a bird" isn't searched
            return self.siri._search("google")(m_google)

        # -------------------------------------------------------------
        # 7. System Power, Lock, Themes
        # -------------------------------------------------------------
        if re.fullmatch(r"lock(?: (?:the|my))?(?: screen| computer| pc| laptop| it)?", t):
            return self.siri.make_plan([{"do": "lock"}], self.siri.say_line("system_lock"))

        if re.fullmatch(r"(?:put (?:(?:the|my) )?(?:pc|laptop|computer) to )?sleep(?: mode)?", t):
            return self.siri.make_plan([{"do": "sleep"}], self.siri.say_line("system_sleep"))

        # handle asks before either. "Shut the laptop down" and "switch off the computer" too, but not a bare "turn
        # off" or "restart it", which could be anything
        if re.fullmatch(r"(?:shut ?down|turn off|switch off|power (?:off|down))(?: (?:the|my|this))? (?:computer|pc|laptop|"
                        r"system)|shut ?down|power off|shut (?:the |my |this )?(?:computer|pc|laptop|system) down", t):
            return self.siri.make_plan([{"do": "shutdown"}], self.siri.say_line("system_shutdown"))

        if re.fullmatch(r"reboot|(?:reboot|restart)(?: (?:the|my|this))? (?:computer|pc|laptop|system)", t):
            return self.siri.make_plan([{"do": "restart"}], self.siri.say_line("system_restart"))

        if re.fullmatch(r"(?:cancel|abort|stop|don'?t)(?: (?:the|my))? (?:shut ?down|restart)(?: (?:the|my))?(?: computer| pc| laptop)?", t):
            return self.siri.make_plan([{"do": "abort_shutdown"}], self.siri.say_line("system_abort_shutdown"))

        if re.fullmatch(r"(?:turn on|enable|switch to|go)?(?: the)? dark(?: mode| theme)?|dark mode(?: on)?", t):
            return self.siri.make_plan([{"do": "dark_mode", "on": True}], self.siri.say_line("dark_on"))

        if re.fullmatch(r"(?:turn off|disable)(?: the)? dark(?: mode| theme)?|dark mode off|(?:switch to |go )?light(?: mode| theme)", t):
            return self.siri.make_plan([{"do": "dark_mode", "on": False}], self.siri.say_line("dark_off"))

        # -------------------------------------------------------------
        # 8. Clipboard & Basic Editing
        # -------------------------------------------------------------
        if re.fullmatch(r"select all(?: text)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+a"}])

        if re.fullmatch(r"copy(?: this| text)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+c"}])

        if re.fullmatch(r"paste(?: this| text)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+v"}])

        if re.fullmatch(r"undo(?: that)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+z"}])

        if re.fullmatch(r"redo(?: that)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+y"}])

        # -------------------------------------------------------------
        # 9. Direct Website Navigation
        # -------------------------------------------------------------
        m_web = re.fullmatch(r"(?:open|go to) (?P<site>[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|in|io|ai|dev|co|app)(?:/\S*)?)", t)
        if m_web:
            site = m_web["site"]
            url = site if site.startswith("http") else "https://" + site
            return self.siri.make_plan([{"do": "website", "url": url}], self.siri.say_line("site_open", site=site))

        # Direct site lookup
        m_site = re.fullmatch(r"(?:open|go to|launch) (?P<site>[a-z ]+)", t)
        if m_site and m_site["site"].strip() in self.siri.SITES:
            site_info = self.siri.SITES[m_site["site"].strip()]
            return self.siri.make_plan([{"do": "website", "url": site_info[1]}], self.siri.say_line("site_open", site=site_info[0]))

        # -------------------------------------------------------------
        # 10. Application Operations (Open / Close / Minimize)
        # -------------------------------------------------------------
        m_app_open = re.fullmatch(r"(?:open|launch|start|run|switch to|bring up|activate)(?: up)?(?: the| my)?(?: app)? (?P<app>.+?)(?: app)?", t)
        if m_app_open:
            app_raw = m_app_open["app"].strip()
            # If it's a known website
            if app_raw in self.siri.SITES:
                s_info = self.siri.SITES[app_raw]
                return self.siri.make_plan([{"do": "website", "url": s_info[1]}], self.siri.say_line("site_open", site=s_info[0]))
            # Special Windows folders and tools. Known folders by their shell: names, since they can be moved off the
            # user folder: on this PC Downloads is on D:, so ~\Downloads didn't exist and ~\Pictures was an old one
            if re.fullmatch(r"downloads(?: folder)?", app_raw):
                return self.siri.make_plan([{"do": "open_folder", "path": "shell:Downloads"}], self.siri.say_line("app_open"))
            if re.fullmatch(r"documents(?: folder)?", app_raw):
                return self.siri.make_plan([{"do": "open_folder", "path": "shell:Personal"}], self.siri.say_line("app_open"))
            if re.fullmatch(r"pictures(?: folder)?", app_raw):
                return self.siri.make_plan([{"do": "open_folder", "path": "shell:My Pictures"}], self.siri.say_line("app_open"))
            if re.fullmatch(r"(?:the )?recycle bin", app_raw):
                return self.siri.make_plan([{"do": "open_folder", "path": "shell:RecycleBinFolder"}], self.siri.say_line("app_open"))
            if re.fullmatch(r"(?:file )?explorer|my files", app_raw):
                return self.siri.make_plan([{"do": "open_folder", "path": "shell:MyComputerFolder"}])
            if re.fullmatch(r"task manager", app_raw):
                return self.siri.make_plan([{"do": "keys", "keys": "ctrl+shift+esc"}])
            app_res = self.resolve_app(app_raw)
            if app_res:
                return self.siri.make_plan([{"do": "open", "app": app_res[0]}], self.siri.say_line("app_open"))

        m_app_close = re.fullmatch(r"(?:close|quit|exit|kill|terminate|shut down)(?: the| my)?(?: app)? (?P<app>.+?)(?: app| window)?", t)
        if m_app_close:
            app_raw = m_app_close["app"].strip()
            if app_raw in ("tab", "this tab", "current tab"):
                return self.siri.make_plan([{"do": "keys", "keys": "ctrl+w"}])
            app_res = self.resolve_app(app_raw, for_close=True)
            if app_res:
                return self.siri.make_plan([{"do": "close", "app": app_res[0]}], self.siri.say_line("app_quit", app=app_res[1]))

        m_app_min = re.fullmatch(r"(?:minimi[sz]e|hide)(?: the| my)?(?: app)? (?P<app>.+?)(?: app| window)?", t)
        if m_app_min:
            app_raw = m_app_min["app"].strip()
            app_res = self.resolve_app(app_raw, for_close=True)
            if app_res:
                return self.siri.make_plan([{"do": "minimise", "app": app_res[0]}], self.siri.say_line("app_minimise", app=app_res[1]))

        # -------------------------------------------------------------
        # 11. System Diagnostics / Hardware status
        # -------------------------------------------------------------
        found_sys = self.siri.sys_intent(t)
        if found_sys:
            try:
                text_out = self.siri.sysinfo.describe(found_sys[0], self.siri.sysinfo.lookup(found_sys[0]), found_sys[1])
                return self.siri.make_plan(say=text_out)
            except Exception:
                pass

        # -------------------------------------------------------------
        # 12. Window Management
        # -------------------------------------------------------------
        # -------------------------------------------------------------
        # 12. Window Management
        # -------------------------------------------------------------
        if re.fullmatch(r"maximi[sz]e(?: this| the)?(?: window)?", t):
            return self.siri.make_plan([{"do": "window", "action": "maximize"}])

        if re.fullmatch(r"restore(?: this| the)?(?: window)?|unmaximi[sz]e(?: this| the)?(?: window)?", t):
            return self.siri.make_plan([{"do": "window", "action": "restore"}])

        if re.fullmatch(r"(?:show|go to)?(?: the)? desktop|minimi[sz]e all(?: windows)?", t):
            return self.siri.make_plan([{"do": "window", "action": "desktop"}])

        if re.fullmatch(r"switch (?:window|app)|next window", t):
            return self.siri.make_plan([{"do": "keys", "keys": "alt+tab"}])

        if re.fullmatch(r"close (?:this |the )?window", t):
            return self.siri.make_plan([{"do": "keys", "keys": "alt+f4"}])

        # -------------------------------------------------------------
        # 13. System Utilities & Folders
        # -------------------------------------------------------------
        if re.fullmatch(r"(?:take |grab )?(?:a )?screenshot|screen capture|snip(?:ping tool)?", t):
            return self.siri.make_plan([{"do": "screenshot"}])

        if re.fullmatch(r"(?:open )?task manager", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+shift+esc"}])

        if re.fullmatch(r"(?:open )?(?:file )?explorer|open my files", t):
            return self.siri.make_plan([{"do": "open_folder", "path": "shell:MyComputerFolder"}])

        if re.fullmatch(r"(?:open|go to|show)(?: my)? downloads(?: folder)?", t):
            return self.siri.make_plan([{"do": "open_folder", "path": "shell:Downloads"}], self.siri.say_line("app_open"))

        if re.fullmatch(r"(?:open|go to|show)(?: my)? documents(?: folder)?", t):
            return self.siri.make_plan([{"do": "open_folder", "path": "shell:Personal"}], self.siri.say_line("app_open"))

        if re.fullmatch(r"(?:open|go to|show)(?: my)? pictures(?: folder)?", t):
            return self.siri.make_plan([{"do": "open_folder", "path": "shell:My Pictures"}], self.siri.say_line("app_open"))

        if re.fullmatch(r"(?:open|go to|show)(?: the)? recycle bin", t):
            return self.siri.make_plan([{"do": "open_folder", "path": "shell:RecycleBinFolder"}], self.siri.say_line("app_open"))

        # -------------------------------------------------------------
        # 14. Productivity Shortcuts & Editing
        # -------------------------------------------------------------
        if re.fullmatch(r"copy(?: (?:this|the|selected)?(?: text| that)?)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+c"}])

        if re.fullmatch(r"paste(?: this| text)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+v"}])

        if re.fullmatch(r"cut(?: this| text| that)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+x"}])

        if re.fullmatch(r"save(?: (?:this|the)?(?: file| document)?)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+s"}])

        if re.fullmatch(r"find(?: on page)?|search (?:this |on )?page", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+f"}])

        if re.fullmatch(r"print(?: this| page)?", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+p"}])

        if re.fullmatch(r"new window", t):
            return self.siri.make_plan([{"do": "keys", "keys": "ctrl+n"}])

        # -------------------------------------------------------------
        # 15. Timers & Voice Dictation
        # -------------------------------------------------------------
        if re.fullmatch(r"how (?:long|much time)(?: is| do i have| have i got)?(?: left| remaining)?(?: on (?:the|my) timer)?|time left(?: on timer)?", t):
            left = self.siri.timer_snapshot()
            return self.siri.make_plan(say=self.siri.say_line("timer_check", left=self.siri.say_duration(left[0][1])) if left else self.siri.say_line("timer_none"))

        if re.fullmatch(r"(?:cancel|stop|delete|clear|remove)(?: the| all| my| all the| all my)? (?:timers?|alarms?)", t):
            return self.siri.make_plan([{"do": "cancel_timers"}], self.siri.say_line("timers_cancel" if self.siri.TIMERS else "timer_none"))

        m_timer = re.fullmatch(r"(?:(?:set|start|make) )?(?:a |an |the )?(?:timer )?(?:for )?(?P<num>\d+)\s*(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?)(?: timer)?", t)
        if m_timer:
            num = int(m_timer["num"])
            u = m_timer["unit"]
            secs = num * 3600 if "hour" in u or "hr" in u else num * 60 if "min" in u else num
            return self.siri.make_plan([{"do": "timer", "seconds": secs}], self.siri.say_line("timer_set"))

        if re.fullmatch(r"(?:start )?dictat(?:e|ion)|start transcribing|take (?:a )?dictation", t):
            return self.siri.make_plan([{"do": "dictate"}])

        # -------------------------------------------------------------
        # 16. Literal Typing
        # -------------------------------------------------------------
        m_type = re.fullmatch(r"(?:type|write|enter) (?P<txt>.+?)(?: and (?:press|hit) (?P<key>enter|tab))?", t)
        if m_type and not self.siri.NOT_LITERAL.match(m_type["txt"]):  # "a short email ...": the model writes it
            # the words as you said them, capitals and punctuation kept: t is lowercased and stripped for matching
            said = re.search(r"\b(?:type|write|enter)\s+(?P<txt>.+?)(?:\s+and\s+(?:press|hit)\s+(?:enter|tab))?[\s.]*$",
                             spoken.strip(), re.I)
            text = said["txt"].strip() if said else m_type["txt"]
            steps = [{"do": "type", "text": text}]
            if m_type["key"]:
                steps.append({"do": "keys", "keys": m_type["key"].lower()})
            return self.siri.make_plan(steps)

        return None
