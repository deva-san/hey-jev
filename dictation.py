"""Dictation from Tatoscription: "Hey Jev, transcribe" records until "stop transcribing", then pastes the text at your cursor.

The audio never leaves the PC: the same local speech model that listens for "stop transcribing" writes the text.
"""
import os, re, json, time

from winplatform import log_path

MAX_SECS = 15 * 60  # stops by itself after this, in case the stop phrase gets missed
HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY = log_path("Hey Jev dictation.jsonl")
START = re.compile(r"^\W*(?:(?:please|can you|could you)\s+)?(?:start\s+)?(?:transcrib\w*|dictat\w*|take notes)"
                   r"(?:\s+(?:this|this meeting|this call|notes|mode|now|please|for me))?\W*$", re.I)

USER_VOCAB = os.path.join(HERE, "vocabulary.json")  # your own words, gitignored
VOCAB = []


def read_vocab():
    path = USER_VOCAB if os.path.exists(USER_VOCAB) else os.path.join(HERE, "vocabulary.example.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_vocab():
    global VOCAB
    VOCAB = [(re.compile(r"\b" + re.escape(alt) + r"\b", re.I), word) for word, alts in read_vocab().items() for alt in alts]


def save_vocab(words):
    """words is {"Word": ["heard as", ...]}, saved to vocabulary.json and used straight away."""
    with open(USER_VOCAB, "w", encoding="utf-8") as f:
        json.dump(words, f, indent=2, ensure_ascii=False)
        f.write("\n")
    load_vocab()


load_vocab()


def fix_vocab(text):
    for rx, word in VOCAB:
        text = rx.sub(word, text)
    return text


# --------------------------------------------------------------------------- tidying what you said, as Nixi does
# "Anyone up for a game tonight? Um, I'm free after seven, actually eight." is pasted as "Anyone up for a game
# tonight? I'm free after eight.": fillers go, and so do words you put right yourself, with the word that said so.
# The popup shows them struck through as you talk (segments). All on this PC, by rule: no model sees your dictation.
FILLERS = {"um", "umm", "ummm", "uh", "uhh", "uhm", "erm", "er", "err", "ah", "ahh", "hmm", "hmmm", "hm", "mm", "mmm"}
# what says the words just before it were wrong, after a comma: "seven, actually eight", "at 5, no, 6 pm"
CUES = (("no", "wait"), ("sorry", "i", "mean"), ("i", "mean"), ("i", "meant"), ("or", "rather"), ("make", "that"),
        ("no", "sorry"), ("actually",), ("no",), ("sorry",), ("rather",), ("wait",), ("oops",))
LEADS = (("make", "it"), ("make", "that"), ("let's", "say"), ("say",))  # "actually, make it seven": part of the cue
SCRATCH = (("scratch", "that"), ("delete", "that"), ("strike", "that"))  # the sentence before it goes
STUTTER = {"i", "the", "a", "an", "to", "and", "we", "so", "it", "is", "my", "you", "in", "on", "of"}
NUMBERS = set("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
              "sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred "
              "thousand half quarter noon midnight".split())


def _bare(token):
    return re.sub(r"^[^\w']+|[^\w']+$", "", token.lower().replace("\u2019", "'"))


def _ends(token, marks):
    return token.rstrip("\"')\u201d\u2019").endswith(tuple(marks))


def _kind(token, first=False):
    """What sort of word, to line a correction up with what it puts right: a number, a name, or any other word.
    first: it starts a sentence, so a capital doesn't make it a name ("Call Ravi")."""
    bare = _bare(token)
    if re.fullmatch(r"\d+(?:[:.]\d+)?(?:am|pm|st|nd|rd|th|%)?", bare) or bare in NUMBERS or \
            (bare.count("-") == 1 and set(bare.split("-")) <= NUMBERS):  # "twenty-five"
        return "number"
    word = re.sub(r"^[^\w]+", "", token)
    if word[:1].isupper() and not first and not re.fullmatch(r"i(?:'[a-z]+)?", bare):
        return "name"
    return "word"


def _phrase_at(bare, i, phrases):
    """How many words of one of phrases start at i, longest first, else 0."""
    for words in sorted(phrases, key=len, reverse=True):
        if tuple(bare[i:i + len(words)]) == words:
            return len(words)
    return 0


def segments(text):
    """What was said, word by word, as [(word, kept)]: fillers ("um"), a stutter ("I I") and what you put right
    yourself ("seven, actually") aren't kept. The words are as said, so the popup can strike out what goes."""
    toks = str(text or "").split()
    bare = [_bare(t) for t in toks]
    keep = [True] * len(toks)
    kind = lambda j: _kind(toks[j], j == 0 or _ends(toks[j - 1], ".?!"))  # noqa: E731
    for i, b in enumerate(bare):
        if b in FILLERS:
            keep[i] = False
    for i in range(len(toks) - 1):
        if keep[i] and bare[i] in STUTTER and bare[i] == bare[i + 1] and not _ends(toks[i], ".?!"):
            keep[i] = False

    def before(i, most=8):
        """The kept words before i in the same sentence, nearest last."""
        out = []
        j = i - 1
        while j >= 0 and len(out) < most:
            if keep[j]:
                if _ends(toks[j], ".?!"):
                    break
                out.insert(0, j)
            j -= 1
        return out

    i = 0
    while i < len(toks):
        n = _phrase_at(bare, i, SCRATCH)
        if n:
            back = before(i, 40)
            if not back:  # "scratch that" after a full stop: the sentence before that one
                j = i - 1
                while j >= 0 and not keep[j]:
                    j -= 1
                if j >= 0:
                    back = before(j, 40) + [j]
            for j in back + list(range(i, i + n)):
                keep[j] = False
            i += n
            continue
        n = _phrase_at(bare, i, CUES)
        prev = before(i)
        if not n or not keep[i] or not prev:
            i += 1
            continue
        paused = _ends(toks[prev[-1]], (",", "-", "\u2014", "\u2013"))
        if not paused:  # no comma, as Nemotron often writes it: only a number or a name put right by another
            nxt = next((j for j in range(i + n, len(toks)) if keep[j]), None)
            if nxt is None or kind(prev[-1]) not in ("number", "name") or kind(nxt) != kind(prev[-1]):
                i += 1
                continue
        lead = _phrase_at(bare, i + n, LEADS)
        start = i + n + lead
        fix = []  # the words that put it right: to the end of the clause
        for j in range(start, len(toks)):
            fix.append(j)
            if _ends(toks[j], ".?!;,"):
                break
        fix = [j for j in fix if keep[j]]
        if not fix or _phrase_at(bare, fix[0], CUES):
            i += 1
            continue
        wrong = None
        anchor = next((k for k in range(len(prev) - 1, -1, -1) if bare[prev[k]] == bare[fix[0]]), None)
        if anchor is not None:  # "tell John, actually tell Mary": from the word it starts with again
            wrong = prev[anchor:]
        else:  # the most words that line up with it word for word by sort: "at 5, no, 6 pm" puts right 5,
            # "Ravi Kumar, sorry, Priya Shah" both names, "Call Ravi actually Priya tomorrow" only Ravi
            for k in range(min(len(fix), 4, len(prev)), 0, -1):
                if all(kind(x) == kind(y) for x, y in zip(prev[-k:], fix[:k])):
                    wrong = prev[-k:]
                    break
        if not wrong:
            i += 1
            continue
        for j in wrong + list(range(i, start)):
            keep[j] = False
        i = start
    return list(zip(toks, keep))


def clean(text):
    """What you meant, as it's pasted: fillers and the words you put right left out (see segments), a capital
    where a sentence now starts, and no comma left hanging."""
    out = []
    for word, kept in segments(text):
        if not kept:
            mark = re.search(r"[.?!]+[\"')\u201d\u2019]*$", word)
            if mark and out and not _ends(out[-1], ".?!"):  # "I'm free, um." keeps its full stop
                out[-1] = re.sub(r"[,;:\-\u2013\u2014]+$", "", out[-1]) + mark.group(0)
            continue
        if (not out or _ends(out[-1], ".?!")) and word[:1].islower() and not re.search(r"[A-Z]", word[1:]):
            word = word[:1].upper() + word[1:]  # not "iPhone"
        out.append(word)
    return re.sub(r"[,;:\-\u2013\u2014]+$", "", " ".join(out)).strip()


class Dictation:
    def __init__(self, names):
        # her name goes with the stop phrase however it was written: "Hey Jev" came out as "Hello" or "Heijev", and
        # that was pasted at the end of the text
        self.stop_rx = re.compile(rf"(?:\b(?:hey|hi|hay|hello|hallo|hullo|okay|ok)\W+)?"
                                  rf"(?:\b(?:hey|hei|he|hi|ha|h|a)?(?:{names})\W+)?\b(?:stop|end|finish)\W+(?:the\W+)?"
                                  r"(?:transcri|dictat)\w*\W*$", re.I)
        self.active = False

    def start(self):
        self.active, self.started, self.heard = True, time.time(), []

    def timed_out(self):
        return self.active and time.time() - self.started > MAX_SECS

    def add(self, heard):
        """Keep what was heard in this phrase, returns True if it was the stop command."""
        if heard:
            self.heard.append(heard)
        return bool(self.stop_rx.search(heard)) or self.timed_out()

    def preview(self, partial=""):
        """Everything said so far and the phrase still being said, for the popup: it strikes out what clean drops."""
        if not self.active:
            return str(partial or "")
        return fix_vocab(" ".join([*self.heard, str(partial or "")]).strip())

    def finish(self):
        """The whole dictation as one text, minus the stop phrase and tidied (clean), also saved to the history."""
        self.active = False
        said = self.stop_rx.sub("", " ".join(self.heard)).strip(" ,")
        said = fix_vocab(said) if said else ""
        text = clean(said) if said else ""
        if text:
            entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "text": text}
            if said != text:
                entry["said"] = said  # as said, before the fillers and corrections came out
            with open(HISTORY, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        return text
