"""Check the listening loop with no mic, keys or network: Windows' own voice says a short script, and the real
end-of-speech detector, speech-to-text and Smart Turn decide where each turn ends and what it's for, and the quick
path what to do about it.

    .venv\\Scripts\\python test_listen.py            # with the speech-to-text picked in Settings
    .venv\\Scripts\\python test_listen.py parakeet   # or name one: nemotron, parakeet or whisper

Prints what was heard and how long it took, and exits with 1 if anything is routed wrong.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
import soundfile as sf

import settings
import siri
import speech

# "[400]" in a line is a pause of 400 ms in the middle of it, said as one sentence, the way people pause to think
SAY = r"""param($folder)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $s.SelectVoice('Microsoft David Desktop') } catch {}
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$i = 0
foreach ($line in Get-Content (Join-Path $folder 'say.txt') -Encoding UTF8) {
    $s.SetOutputToWaveFile((Join-Path $folder "$i.wav"), $format)
    if ($line -match '\[\d+\]') {
        $body = [regex]::Replace([System.Security.SecurityElement]::Escape($line), '\[(\d+)\]', '<break time="$1ms"/>')
        $s.SpeakSsml('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">' + $body + '</speak>')
    } else {
        $s.Speak($line)
    }
    $i++
}
$s.SetOutputToNull()
$s.Dispose()
"""
# (seconds of quiet before it, what's said, what it should be taken as: None for not hers, "wake" for just her name,
#  or (gate, a word in the request, what the quick path does first: a step, "say" for a reply, None for the model))
SCRIPT = [
    (1.0, "Hey Jev, open Notepad.", (False, "notepad", "open")),
    (1.0, "Turn the volume up.", (True, "volume", "volume")),  # in the follow-up window, so no name needed
    (13.0, "Turn the volume down.", None),  # the window has closed
    (1.0, "I told Jeff about the meeting yesterday.", None),  # a name, but nobody called her
    (1.0, "Hey Jev.", "wake"),
    (1.0, "Play some lo-fi music and open Notepad.", (False, "notepad", None)),  # after a bare "Hey Jev": the model
    (1.0, "Hello Jev.", (False, "hello", "say")),  # a greeting gets a greeting back
    (1.0, "Hello[700] Jev.", (False, "hello", "say")),  # a breath after "Hello": that cut her name off
    (1.0, "Hey Jev, open[800] Notepad.", (False, "notepad", "open")),  # "open" and a pause: wait for what
    (1.0, "Hey Jev, check the space of the C drive.", (False, "drive", "say")),  # answered on the PC, no model
    (1.0, "Hey Jev[400] open YouTube.", (False, "youtube", "website")),  # a short pause after her name: one turn
    # a pause to think mid-sentence: she waits for the rest, not "Sorry?" after "and"
    (1.0, "Hey Jev, open Gmail in my Work profile and[900] set the volume to thirty.", (False, "volume", None)),
]


def voice(lines):
    """Windows' built-in voice saying each line, as 16 kHz audio."""
    folder = tempfile.mkdtemp(prefix="heyjev-test-")
    try:
        with open(os.path.join(folder, "say.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        with open(os.path.join(folder, "say.ps1"), "w", encoding="utf-8") as f:
            f.write(SAY)
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        os.path.join(folder, "say.ps1"), folder], check=True, capture_output=True)
        return [sf.read(os.path.join(folder, f"{i}.wav"), dtype="float32")[0] for i in range(len(lines))]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def taken_as(text, kind):
    """What the app would make of a phrase: None, "wake", or (gate, request, first quick step / "say" / None). With
    "Hey Jev" needed, whatever Settings say: Answer without her name sends more to the model, see test_open_mic.py."""
    what = siri.route(text, kind, open_mic=False)
    if not isinstance(what, tuple):
        return what
    plan = siri.quick(what[1])
    return what[2], what[1], (plan["steps"][0]["do"] if plan["steps"] else "say") if plan else None


def ok(want, got):
    if want is None or want == "wake":
        return got == want
    return isinstance(got, tuple) and got[0] == want[0] and want[1] in got[1].lower() and got[2] == want[2]


def pair(phrases, lines):
    """Which heard phrases go with which line of the script: the line each overlaps most in the audio fed in, so
    one line split in two is one line wrong, not every line after it. phrases and lines are (start, end) in
    samples. Returns the phrases' indexes for each line."""
    mine = [[] for _ in lines]
    for i, (a, b) in enumerate(phrases):
        mine[int(np.argmax([min(b, end) - max(a, start) for start, end in lines]))].append(i)
    return mine


def main():
    # This checks speech/turn routing, not whatever call happens to be using the real PC mic while the test runs.
    # Call-aware routing has its own local check.
    siri.win.call_apps = lambda: ()
    engine = sys.argv[1] if len(sys.argv) > 1 else settings.get("stt_engine")
    clips = voice([line for _, line, _ in SCRIPT])
    t = time.time()
    ears, turn = speech.Ears(engine, print), speech.Turn(print)
    print(f"{engine} and Smart Turn loaded in {time.time() - t:.1f}s")
    heard, follow_up, fed, held, words = [], [None], [0], [None], {}

    def on_phrase(audio, kind, text, ms):
        start = fed[0] - len(audio)  # where it began in the audio fed in, to tell which line it was
        if held[0]:  # the rest of a phrase that a pause cut off, as the app joins them
            first, first_kind, first_ms, start = held[0]
            held[0] = None
            text = speech.heard(f"{first} {text}".strip(), min(first.sure, text.sure))
            kind, ms = kind if first_kind == "other" else first_kind, first_ms + ms
        elif siri.unfinished(text) and isinstance(siri.route(text, kind, open_mic=False), tuple):
            print(f"  (cut off at {text!r}, the app waits for the rest)")
            held[0] = (text, kind, ms, start)
            return
        what = taken_as(text, kind)
        heard.append((kind, text, what, ms, fed[0], words.pop("seen", None), start))
        if what == "wake":
            listener.arm(siri.WAKE_WINDOW)
        elif what:
            follow_up[0] = siri.FOLLOW_UP  # she answered: the app opens the window once she's done talking

    def on_words(text, kind):  # when her name first shows up in the words as they come
        if "seen" not in words and siri.find_name(text):
            words["seen"] = fed[0]

    listener = speech.Listener(speech.end_of_speech(), ears, on_phrase, turn=turn, on_words=on_words,
                               hold_for=siri.wait_for_rest)
    speech_ends, starts = [], []  # where each line's voice starts and stops, in samples from the start
    for (gap, _, _), clip in zip(SCRIPT, clips):
        audio = np.concatenate([np.zeros(int(gap * speech.RATE), "float32"), clip])
        voiced = np.flatnonzero(np.abs(audio) > 0.01)
        starts.append(fed[0] + voiced[0])
        speech_ends.append(fed[0] + voiced[-1])
        for i in range(0, len(audio), siri.Recorder.BLOCK):
            fed[0] += len(audio[i:i + siri.Recorder.BLOCK])
            listener.feed(audio[i:i + siri.Recorder.BLOCK])
            if follow_up[0] is not None:
                listener.reset(follow_up[0])
                follow_up[0] = None
    for _ in range(80):  # quiet at the end, so the last phrase finishes
        fed[0] += siri.Recorder.BLOCK
        listener.feed(np.zeros(siri.Recorder.BLOCK, "float32"))

    wrong = 0
    mine = pair([(h[6], h[4]) for h in heard], list(zip(starts, speech_ends)))
    waits, early = [], []
    for (_, line, want), got, start, end in zip(SCRIPT, mine, starts, speech_ends):
        if len(got) != 1:  # split in two, or not heard at all
            wrong += 1
            print(f"  BAD {line!r:52} heard as {len(got)} phrases: {[str(heard[i][1]) for i in got]}")
            continue
        kind, text, what, ms, at, seen, _ = heard[got[0]]
        wait = (at - end) / speech.RATE + ms / 1000  # from the end of the voice to the words being ready
        waits.append(wait)
        if seen is not None:
            early.append((seen - start) / speech.RATE)
        good = ok(want, what)
        wrong += not good
        print(f"  {'ok ' if good else 'BAD'} {line!r:52} heard as {kind:9} {text!r:46} {wait:.2f}s -> {what}")
    print(f"{len(SCRIPT) - wrong} of {len(SCRIPT)} right. From the end of a phrase to its words: "
          f"{np.mean(waits or [0]):.2f}s on average, {np.median(waits or [0]):.2f}s median (speech-to-text and Smart "
          f"Turn {np.mean([h[3] for h in heard] or [0]):.0f} ms of it)")
    if early:
        print(f"Her name showed up in the words {np.median(early):.2f}s after the speech started (median)")
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    main()
