"""Trains the decider's heads (decider.py) on her own past turns: python train_decider.py

for_me, "was this said to her?", from the hand labels of 4 to 7 October 2026 (487 turns: U for her, N not, B a
filler like "mm-hmm") and the 1,411 room phrases she let go, all kept in %LOCALAPPDATA%\\Hey Jev\\decider\\labels-*.
A request said with her name counts too, with the name taken off, since that's how it would sound without it.
Later turns logged in shadow mode (shadow.jsonl) are added once you've labelled them there ("label": "U" or "N").

It checks itself on turns it hasn't seen (5 folds), sets the levels where it was right 95% of the time each way,
prints what that would have changed on those days, and saves heads.npz next to the labels. Nothing leaves the PC.
"""
import glob
import json
import os
import re
import sys

import numpy as np
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))
import decider  # noqa: E402
import siri  # noqa: E402

PRECISION = 0.95


def labelled_turns():
    """(words, kind, label, outcome, source) from the hand-labelled logs."""
    out = []
    for folder in sorted(glob.glob(os.path.join(decider.folder(), "labels-*"))):
        raw = open(os.path.join(folder, "labels.py"), encoding="utf-8").read().split('RAW = """')[1].split('"""')[0]
        labels = {}
        for item in re.split(r"[|\n]", raw):
            p = item.split()
            if len(p) >= 2:
                labels[int(p[0])] = (p[1], p[2] if len(p) > 2 else "")
        parsed = json.load(open(os.path.join(folder, "parsed.json"), encoding="utf-8"))
        for t in parsed["turns"]:
            intent, outcome = labels.get(t["line"], ("?", ""))
            if intent == "?" or not t.get("text"):
                continue
            found = siri.find_name(t["text"])
            words = found[1] if found else t["text"]
            if words and words.strip(" .,!?"):
                kind = "follow_up" if t.get("kind") == "follow_up" and not found else "cold"
                out.append((words, kind, 1 if intent == "U" else 0, outcome, "hand", bool(found)))
        seen = {w.lower() for w, *_ in out}
        for r in parsed.get("room", []):
            w = (r.get("text") or "").strip()
            if w and w.lower() not in seen and not siri.find_name(w):
                seen.add(w.lower())
                out.append((w, "cold", 0, "", "room", False))
    shadow = os.path.join(decider.folder(), "shadow.jsonl")
    if os.path.exists(shadow):
        for line in open(shadow, encoding="utf-8"):
            e = json.loads(line)
            if e.get("label") in ("U", "N"):
                # older rows have "True" for a follow-up (str of the gate), which features() saw as no kind
                kind = {"True": "follow_up"}.get(e.get("kind"), e.get("kind", "cold"))
                out.append((e["said"], kind, 1 if e["label"] == "U" else 0, "", "shadow", False))
    return out


def levels(p, y):
    """(hi, lo): from hi up it's for her 95% of the time, from lo down it isn't. Beyond 0..1 if never."""
    order = np.argsort(-p)
    hi = 1.01
    for k in range(1, len(order) + 1):
        top = order[:k]
        if y[top].mean() >= PRECISION and k >= 10:
            hi = float(p[top].min())
    order = np.argsort(p)
    lo = -0.01
    for k in range(1, len(order) + 1):
        low = order[:k]
        if (1 - y[low]).mean() >= PRECISION and k >= 10:
            lo = float(p[low].max())
    return hi, lo


def main():
    if not decider.available():
        sys.exit("The decider's model isn't in the models folder: see decider.ENCODER.")
    rows = labelled_turns()
    if not rows:
        sys.exit("No labels found in " + decider.folder())
    enc = decider.Encoder()
    x = np.stack([decider.features(enc(w), k) for w, k, *_ in rows])
    y = np.array([r[2] for r in rows], np.float32)
    hand = np.array([r[4] in ("hand", "shadow") for r in rows])
    # judged only on what would reach the decider: turns without her name that she'd otherwise ask the model about
    judged = hand & np.array([not r[5] and (r[1] == "follow_up" or siri.could_be_request(r[0])) for r in rows])
    print(f"{len(rows)} turns: {int(y.sum())} for her, {int((1 - y).sum())} not; {int(judged.sum())} judged")
    rng = np.random.default_rng(7)
    fold = rng.integers(0, 5, len(rows))
    p = np.zeros(len(rows), np.float32)
    for f in range(5):
        test = fold == f
        w, b = decider.train_head(x[~test], y[~test])
        p[test] = decider.predict({"w": w, "b": b}, x[test])
    pj, yj = p[judged], y[judged]
    hi, lo = levels(pj, yj)
    auc = np.mean([(a > b_) + 0.5 * (a == b_) for a in pj[yj == 1] for b_ in pj[yj == 0]]) if 0 < yj.sum() < len(yj) \
        else float("nan")
    print(f"held out: AUC {auc:.3f}; for her from {hi:.2f} up, not from {lo:.2f} down")
    sure_no = pj <= lo
    print(f"  it would let go {int(sure_no.sum())} of {len(pj)} without a model call, "
          f"{int((sure_no & (yj == 1)).sum())} of them meant for her")
    outcome = np.array([r[3] for r in rows])[judged]
    answered = (yj == 0) & np.isin(outcome, ["spoke", "acted"])
    print(f"  of the {int(answered.sum())} not for her that she answered or acted on, it would have stopped "
          f"{int((answered & sure_no).sum())}")
    w, b = decider.train_head(x, y)
    os.makedirs(decider.folder(), exist_ok=True)
    path = os.path.join(decider.folder(), "heads.npz")
    np.savez(path, for_me__w=w, for_me__b=b, for_me__hi=hi, for_me__lo=lo)
    print(f"saved {path}")


if __name__ == "__main__":
    main()
