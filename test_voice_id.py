"""Checks only-your-voice with the real model, by hand: python test_voice_id.py

Scores your voice (the sentences you read for "learn my voice", in %LOCALAPPDATA%\\Hey Jev\\voice\\clips) against
Windows' own voices saying commands, and times each voice print. Your clips are scored against the others, one left
out at a time. Nothing leaves the PC; Windows' voices are made into WAV files in a temp folder and deleted."""
import glob
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
import soundfile as sf
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))
import speech  # noqa: E402
import voiceid  # noqa: E402

LINES = ("Hey Jev, open Chrome and play some music.", "What is the weather like today?",
         "Set a timer for five minutes.", "Turn the volume down a little.", "Pause the video, please.")


def windows_voices(folder):
    """WAV files of Windows' desktop voices saying LINES, 16 kHz mono."""
    script = ("Add-Type -AssemblyName System.Speech; $f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo("
              "16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
              "[System.Speech.AudioFormat.AudioChannel]::Mono); $s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              " $i = 0; foreach ($v in $s.GetInstalledVoices()) { foreach ($l in @(" +
              ",".join(f"'{line}'" for line in LINES) + ")) { $t = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              f" $t.SelectVoice($v.VoiceInfo.Name); $t.SetOutputToWaveFile('{folder}\\voice-' + $i + '.wav', $f);"
              " $t.Speak($l); $t.Dispose(); $i++ } }")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, capture_output=True)
    return sorted(glob.glob(os.path.join(folder, "voice-*.wav")))


def main():
    clips = sorted(glob.glob(os.path.join(voiceid.folder(), "clips", "*.wav")))
    if len(clips) < 3:
        sys.exit("Say “Hey Jev, learn my voice” first: your sentences are what this checks against.")
    speaker = speech.Speaker()
    yours, ms = [], []
    for path in clips:
        audio, _ = sf.read(path, dtype="float32")
        t = time.perf_counter()
        v, secs = speaker.print(audio)
        ms.append((secs, (time.perf_counter() - t) * 1000))
        if v is not None:
            yours.append(v)
    print(f"voice print: {np.median([m for _, m in ms]):.0f} ms median for {np.median([s for s, _ in ms]):.1f} s "
          f"of speech")
    centre = lambda vs: (lambda c: c / np.linalg.norm(c))(np.mean(vs, axis=0))
    mine = [float(v @ centre(yours[:i] + yours[i + 1:])) for i, v in enumerate(yours)]
    print("you:     " + " ".join(f"{s:.2f}" for s in mine))
    with tempfile.TemporaryDirectory() as folder:
        theirs = []
        for path in windows_voices(folder):
            audio, _ = sf.read(path, dtype="float32")
            v, secs = speaker.print(audio)
            if v is not None and secs >= voiceid.MIN_SPEECH:
                theirs.append(float(v @ centre(yours)))
    print("Windows: " + " ".join(f"{s:.2f}" for s in theirs))
    p = voiceid.Profile()
    print(f"levels now: {p.named:.2f} with her name, {p.strict:.2f} without"
          + (" (set from your turns)" if p.calibrated else " (the starting ones)"))
    caught = sum(s < p.strict for s in theirs)
    print(f"{sum(s >= p.named for s in mine)} of {len(mine)} of yours pass with her name; "
          f"{caught} of {len(theirs)} of Windows' turned away without it")


if __name__ == "__main__":
    main()
