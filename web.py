"""Her way onto the internet, free and without keys: Wikipedia, DuckDuckGo's instant answers and Google News for
looking things up, any page read as plain text, Open-Meteo for the weather. Only requests and the standard library.

General search engines turn scripts away now (October 2026: DuckDuckGo, Yahoo, Mojeek and Startpage asked for a
captcha, Bing answered "Iron Man 2 director" with pages about iron). For what these sources don't cover, like
prices or live scores, she opens a search in your own browser and reads it off the screen (siri.py, screen).

What she reads on the web is information, never instructions: pages that try to give her orders are checked with
Hermes Agent's threat patterns and left out (see read).
"""
import html
import ipaddress
import json
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from hermes_memory.threat_patterns import first_threat_message

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/141.0 Safari/537.36", "Accept-Language": "en-IN,en;q=0.9"}
S = requests.Session()
MAX_PAGE = 1_500_000  # bytes of a page read at most, so a huge page can't hold her up
_cache = {}  # what was looked up lately: (kind, key) -> (when, result)


def _cached(kind, key, secs, make):
    hit = _cache.get((kind, key))
    if hit and time.time() - hit[0] < secs:
        return hit[1]
    result = make()
    _cache[(kind, key)] = (time.time(), result)
    return result


def _text(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment or "")).split())


# --------------------------------------------------------------------------- looking things up
def _wikipedia(query, n=3):
    j = S.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=8, params={
        "action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": n}).json()
    return [{"title": x["title"], "url": "https://en.wikipedia.org/wiki/" + x["title"].replace(" ", "_"),
             "snippet": _text(x.get("snippet"))} for x in j.get("query", {}).get("search", [])]


def _instant(query):
    """DuckDuckGo's instant answer: a short summary for people, places, films and the like, or "" if it has none."""
    j = S.get("https://api.duckduckgo.com/", params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
              headers=UA, timeout=8).json()
    text = j.get("Answer") or j.get("AbstractText") or ""
    return {"text": text[:800], "url": j.get("AbstractURL") or ""} if text else ""


def search(query, links=False):
    """What the free sources have on it, asked at once: {"answer", "wikipedia", "news"}, each left out if empty.
    links: the news stories come with their link too, for reading them (research does)."""
    query = " ".join(str(query or "").split())[:200]
    if not query:
        raise RuntimeError("I didn't catch what to look up")

    def make():
        jobs = {"answer": lambda: _instant(query), "wikipedia": lambda: _wikipedia(query),
                "news": lambda: news(query, 5, links)}
        out, failed, threads = {}, [], []
        for key, job in jobs.items():
            def run(key=key, job=job):
                try:
                    out[key] = job()
                except Exception:
                    failed.append(key)
            threads.append(threading.Thread(target=run, daemon=True))
            threads[-1].start()
        for t in threads:
            t.join(9)
        found = {k: out[k] for k in jobs if out.get(k)}
        if not found:
            raise RuntimeError("I couldn't look it up, the internet may be down" if len(failed) == len(jobs) else
                               "Nothing came up for that, try other words")
        return found
    return _cached("search", (query.lower(), links), 600, make)


# --------------------------------------------------------------------------- reading a page
class _Reader(HTMLParser):
    """The readable text of a page: title, description, headings, paragraphs and list items, without menus,
    scripts, footers and forms."""
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "button", "select",
            "template", "iframe", "head"}
    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "td", "th", "pre", "blockquote", "dd", "dt", "figcaption", "tr", "br",
             "div", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip, self.parts, self.title, self.description, self.in_title = 0, [], "", "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            a = dict(attrs)
            if (a.get("name") or a.get("property") or "").lower() in ("description", "og:description"):
                self.description = self.description or (a.get("content") or "")
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self.in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def _public(url):
    """Only web addresses on the internet, never this PC or the home network. A name counts by where it points, since
    names like 127.0.0.1.nip.io or localtest.me point straight back here; one that doesn't point anywhere doesn't."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or not host or host == "localhost" or host.endswith((".local", ".lan")):
        return False
    try:
        ips = [ipaddress.ip_address(str(a[4][0]).split("%")[0])
               for a in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)]
    except (OSError, UnicodeError, ValueError):
        return False
    return bool(ips) and all(ip.is_global and not ip.is_multicast for ip in ips)


def _get(url):
    """A page, its redirects followed only to addresses on the internet. Each is checked before it's asked for:
    requests would follow one to the router first, and only then could its address be checked."""
    for _ in range(6):
        r = S.get(url, headers=UA, timeout=10, stream=True, allow_redirects=False)
        if not r.is_redirect:
            return r
        r.close()
        url = urljoin(r.url, r.headers["location"])
        if not _public(url):  # it sent her somewhere on this PC or the home network
            raise RuntimeError("I only read pages on the internet")
    raise requests.TooManyRedirects(f"more than 5 redirects from {url}")


def _story(url):
    """Where a Google News link goes. It only gets you there with JavaScript: Google's page for the story carries a
    signature, near its end, and Google's own API swaps that for the address (as of October 2026). About 1 s."""
    def make():
        art = urlparse(url).path.rstrip("/").split("/")[-1]
        try:
            page = S.get(f"https://news.google.com/rss/articles/{art}", headers=UA, timeout=10).text
            sg, ts = (re.search(f'data-n-a-{k}="([^"]+)"', page) for k in ("sg", "ts"))
            req = ["Fbv4je", f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,'
                             f'0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{art}",{ts[1]},"{sg[1]}"]']
            r = S.post("https://news.google.com/_/DotsSplashUi/data/batchexecute", timeout=10,
                       headers={**UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
                       data={"f.req": json.dumps([[req]], separators=(",", ":"))})
            return json.loads(json.loads(r.text.split("\n\n")[1])[0][2])[1]
        except Exception as exc:  # no signature on the page, or the answer changed shape
            raise RuntimeError(f"I couldn't open that story ({type(exc).__name__})")
    return _cached("story", url, 86400, make)


def read(url, limit=5000):
    """A web page as {"url", "title", "text"}, the text cut to limit characters. A Google News link reads the
    story it points to."""
    url = str(url or "").strip()
    if not re.match(r"[a-z][a-z0-9+.-]*:", url, re.I):  # "example.com/page": a web address without its https
        url = "https://" + url
    if (urlparse(url).hostname or "").lower() == "news.google.com" and "/articles/" in urlparse(url).path:
        url = _story(url)
    if not _public(url):  # file:, this PC, the home network
        raise RuntimeError("I only read pages on the internet")

    def make():
        try:
            with _get(url) as r:
                r.raise_for_status()
                data = b""
                for chunk in r.iter_content(65536):
                    data += chunk
                    if len(data) > MAX_PAGE:
                        break
                kind = r.headers.get("content-type", "")
                text = data.decode(r.encoding or "utf-8", "replace")
                final = r.url
        except requests.RequestException as exc:
            raise RuntimeError(f"I couldn't open that page ({type(exc).__name__})")
        if "html" not in kind and "<html" not in text[:2000].lower():
            body, title = text, ""
        else:
            reader = _Reader()
            reader.feed(text)
            lines = [" ".join(l.split()) for l in "".join(reader.parts).split("\n")]
            body = "\n".join(l for l in lines if len(l) > 40 or (l and l[-1] in ".?!:"))
            body = (reader.description.strip() + "\n" if reader.description else "") + body
            title = " ".join(reader.title.split())
        if first_threat_message(body[:20000], scope="context"):  # a page giving her orders: information only
            body = "(This page has text that tries to give instructions, so it's left out.)"
        return {"url": final, "title": title, "text": body[:limit]}
    return _cached("read", url, 600, make)


# --------------------------------------------------------------------------- weather
WEATHER = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy", 45: "foggy", 48: "foggy", 51: "light drizzle",
           53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
           67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow", 80: "light showers",
           81: "showers", 82: "heavy showers", 85: "snow showers", 86: "snow showers", 95: "thunderstorms",
           96: "thunderstorms with hail", 99: "thunderstorms with hail"}


def here():
    """Roughly where this PC is, from its internet address: {"place", "lat", "lon", "country"}."""
    def make():
        j = S.get("https://ipinfo.io/json", headers=UA, timeout=6).json()
        lat, lon = (float(v) for v in j["loc"].split(","))
        return {"place": j.get("city") or j.get("region") or "here", "lat": lat, "lon": lon,
                "country": j.get("country") or ""}
    return _cached("here", "", 3600, make)


def place(name):
    """Where a town or city is, by name."""
    def make():
        j = S.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": name, "count": 1},
                  headers=UA, timeout=6).json()
        r = (j.get("results") or [None])[0]
        if not r:
            raise RuntimeError(f"I couldn't find a place called {name}")
        return {"place": f"{r['name']}, {r.get('country', '')}".strip(", "), "lat": r["latitude"],
                "lon": r["longitude"], "country": r.get("country_code") or ""}
    return _cached("place", name.lower(), 86400, make)


def weather(where=None):
    """Now, today and tomorrow, for a place by name or, with none, here."""
    loc = place(where) if where and str(where).strip() else here()

    def make():
        j = S.get("https://api.open-meteo.com/v1/forecast", headers=UA, timeout=8, params={
            "latitude": loc["lat"], "longitude": loc["lon"], "timezone": "auto", "forecast_days": 3,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset"}).json()
        c, d = j["current"], j["daily"]
        days = [{"day": ("today", "tomorrow", "day after")[i], "sky": WEATHER.get(d["weather_code"][i], "mixed"),
                 "high_c": round(d["temperature_2m_max"][i]), "low_c": round(d["temperature_2m_min"][i]),
                 "rain_chance": d["precipitation_probability_max"][i],
                 "sunrise": d["sunrise"][i][-5:], "sunset": d["sunset"][i][-5:]} for i in range(min(3, len(d["time"])))]
        return {"place": loc["place"], "now": {"temp_c": round(c["temperature_2m"]),
                                               "feels_like_c": round(c["apparent_temperature"]),
                                               "sky": WEATHER.get(c["weather_code"], "mixed"),
                                               "humidity": c["relative_humidity_2m"], "wind_kmh": round(c["wind_speed_10m"])},
                "days": days}
    return _cached("weather", (round(loc["lat"], 2), round(loc["lon"], 2)), 900, make)


# --------------------------------------------------------------------------- news
def news(topic=None, n=6, links=False):
    """Headlines from Google News, for a topic or the top stories where this PC is: [{"title", "source", "when"}].
    links: each story's own address too, as "url", worked out from Google's link at about 1 s and 600 KB a story,
    all at once. Only research asks for them."""
    topic = " ".join(str(topic or "").split())[:120]
    try:
        country = here().get("country") or "IN"
    except Exception:
        country = "IN"
    params = {"hl": f"en-{country}", "gl": country, "ceid": f"{country}:en"}

    def make():
        url = "https://news.google.com/rss" + ("/search" if topic else "")
        r = S.get(url, params={**params, **({"q": topic} if topic else {})}, headers=UA, timeout=8)
        r.raise_for_status()
        out = []
        for item in ET.fromstring(r.content).iter("item"):
            title = item.findtext("title") or ""
            source = item.findtext("source") or ""
            if source and title.endswith(" - " + source):
                title = title[:-len(source) - 3]
            out.append({"title": title, "source": source, "when": (item.findtext("pubDate") or "")[:22],
                        **({"url": item.findtext("link") or ""} if links else {})})
            if len(out) >= n:
                break

        def real(story):
            try:
                story["url"] = _story(story["url"])
            except RuntimeError:
                pass  # Google's link still opens it in a browser, and read tries it again
        threads = [threading.Thread(target=real, args=(s,), daemon=True) for s in out if links]
        for t in threads:
            t.start()
        for t in threads:
            t.join(12)
        return out
    return _cached("news", (topic.lower(), country, links), 600, make)
