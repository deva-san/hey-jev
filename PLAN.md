# Hey Jev: Hermes, in voice. The researched plan

7 October 2026. Branch `fix/reality-check` (commit 6fc3a9b). Hermes Agent at commit 3569fba6 (7 Oct 2026).

Behind this plan are eight research studies: Hermes' code, Jev's code, voice ID, speed, the decision maker, papers,
and Reddit/GitHub (Reddit itself was blocked, so it used Hacker News, forums and GitHub issues instead). Every size
below was checked on the download page, and nothing was downloaded or installed. The full notes and sources are listed
at the end.

## Status, 7 October 2026 (evening): phases 0–6 built

All seven phases are built, each committed on its own branch, the branches stacked:
`phase0/fresh-start` → `phase1/voice-id` → `phase2/faster` → `phase3/decider` → `phase4/hermes-learning` →
`phase5/telegram` → `phase6/agent-jobs`. Nothing is pushed. Jev is running from `phase6/agent-jobs`, and 312 tests
pass.

| Phase | Built | Waiting on you | Changed from the plan, and why |
|---|---|---|---|
| 0 Fresh start | `backup.py`, the first-run greeting | – | – |
| 1 Your voice | CAM++ voice ID, enrolment by voice, learning mode that switches itself on | Say **"Hey Jev, learn my voice"** and read the 10 sentences | Turns under 1 s aren't checked: on this PC, Windows' voices saying "Hey Jev" matched yours. A short command said without her name is let go once it's on |
| 2 Faster | Streaming plain answers, the filler, Pocket voice ("Jev on this PC"), Kilo warm-up, 3 history turns | Try "Jev on this PC" in Settings > Voice. Fish stays until 30 Nov, then switches by itself | Ling's thinking stays "low": "none" was tested on 34 requests and was no faster, with more mistakes. Skill notes went into phase 4 |
| 3 Decider | MiniLM decider, trained on your 487 labelled turns, in shadow mode | Nothing. Switch it on later with Settings `"decider": "on"` | Held-out result: it would stop 11 of 44 wrong answers to room talk and miss 3 of 63 requests, so it stays shadow-only until real-use logs say otherwise |
| 4 Hermes learning | Hermes code synced at 3569fba6; curator; review rules; instant corrections; undo; better search; skills that fit written out | – | With full memory and 40 skills the prompt is about **3,700 tokens** (fixed part 2,300), and a test holds it within ≤ 4,000. The step list is trimmed; the 34-request test is still to re-run |
| 5 Telegram | Bot, pairing, buttons, voice notes, owner-only, "send me a screenshot" | Paired (done) | Listens whenever a token is saved, so `/start` always gets an answer. Before this, it stayed off until Pair was pressed, and a `/start` sent first got nothing. It keeps trying when Telegram can't be reached, and says so on the PC if the token stops working |
| 6 Coding jobs | OpenCode over ACP, confined, git snapshot; Hermes' cron rules | Ask for one in a git project folder | Questions mid-job are asked only on the phone (buttons). For a job asked by voice, a command needing your OK is refused and listed in her report rather than interrupting you. Edits in the folder go ahead once you've said yes to the job, since the snapshot makes them undoable |

Still to do: WhatsApp (later, as planned), interrupting her ("stop"), trimming the prompt, and switching the
decider on once its shadow log looks good.

## In short

Jev stays the body: the always-listening ears, the 0.7 s commands on the PC, Windows control and the safety rules.
Hermes' better parts come in as **Hermes' own code**, copied at a pinned commit: memory, skills, the curator,
the learning review, past-chat search, the Telegram button and pairing logic, and its cron rules.

What the research changed in the draft:

| Draft said | Research found | Now |
|---|---|---|
| Laya as the decision maker | Laya needs PyTorch and a 0.6–0.8 GB model. On this CPU it takes 0.3–0.75 s **per question**. Without training it is near chance (0.36), and it has a known "do NOT cancel" means cancel bug | A 23 MB local model (MiniLM, int8 ONNX) with small heads trained on Jev's own 487 hand-labelled turns. **3–10 ms**, no new packages. TypeSafe's own Jev is free on OpenCode "for a limited time" (`jev-1.13-free`, docs updated 6 Oct). It's optional, for coding-job decisions only, never on voice turns |
| Bring in Hermes' code | `pip install hermes-agent` needs Python < 3.14, and Jev runs 3.14.0. Importing Hermes modules pulls in 60–130 of its files and creates a whole Hermes home folder on disk | **Copy** the needed Hermes files at commit 3569fba6, with a pinned-commit record (`UPSTREAM.json`) and a small sync script for later updates |
| Hermes' Telegram adapter | It is 7,320 lines and drags in 158 Hermes files (~96k lines). It also lets every DM through when no allowlist is set | The library Hermes uses (python-telegram-bot 22.8, a 769 KB download, its only dependency already installed) plus ~250 lines of Hermes' own logic: buttons, owner check, pairing, message splitting |
| Faster answers (≤ 2 s) | Today she waits for the model's **whole** JSON reply before speaking. Ling most likely also "thinks" ~150 hidden tokens first (inferred from its token counts). Fish waits for 0.6 s of audio. The most common look-up (`skill_view`) costs a full extra model call | Stream the reply and speak the first sentence at once. Use the local voice, add a short filler, and drop the `skill_view` round trip. She stays on today's free models (your choice), so expect **~3 s** (from 4.6). Groq's free model would make it ~1.6 s, as an option for later |
| Fish voice | **Fish's free model ends 30 Nov 2026**, 54 days from now | Decision needed: Kyutai Pocket TTS on the PC (98.3 MB, runs in the sherpa-onnx already installed, first audio ~0.2–0.4 s). Windows' voices stay the last fallback |
| Skills she writes herself | Papers (SkillsBench 2602.12670) and Hermes users (152 skills, 22 unused duplicates): self-written skills only help when checked and tidied | Curator and new-skill checks are **required** in phase 4 |
| Voice ID | The model's published accuracy isn't on your voice | It first runs **2–3 days in shadow mode**: it scores turns but blocks nothing, to set the threshold from your real voice |

What gets left out, measured as too heavy: the Hermes desktop app (Electron 40, 3,521 TypeScript files),
Hermes' full agent loop on voice turns (11–14k tokens a call, 2+ calls a turn, needs 64k context), its cron engine
(18.5k lines), `delegate_task` sub-agents, PyTorch in any form, and new always-on background programs.

## Budgets: today (measured) and the target

Today's numbers come from her own log, 1–7 Oct 2026: 566 turns, 422 of them with a model call.

| | Today | Target | Gate |
|---|---|---|---|
| Simple commands, end of speech to first sound | 0.63 s median | ≤ 0.7 s | Every phase re-checks it |
| Questions to the model, end of speech to the **first word of the answer** (a filler doesn't count) | 4.6 s median, 8.9 s p90 | **≤ 3 s** median on today's free models (≤ 2 s needs a faster provider, optional). On top of that, a filler by 1.3 s on slow turns | Phase 2 |
| Prompt per model call | ~4,000–4,600 tokens (16k chars, of which ~60% is the step list) | ≤ 3,000 tokens for the fixed part, ≤ 4,000 in total with full memory. A test fails if it grows | Phase 2 and 4 |
| Model calls per question | 1, or 2 with a look-up (`skill_view` is the most common look-up) | 1 for nearly all; look-ups announced with a filler | Phase 2 |
| Memory (RAM), running | 797 MB working set | **+120–205 MB** without Pocket: voice ID 40–70, decider 60–100, Telegram 20–35. **Pocket adds ~350 MB loaded and ~600 MB at its peak**, so about 1.3 GB in all. It could load only when needed and unload when idle, but loading costs its fast start; measured in phase 2 | Every phase |
| Startup (`import siri`) | 0.65 s | No slower. New models load in the background | Every phase |
| New pip packages | – | **One:** python-telegram-bot (phase 5). No PyTorch, no Electron, no new program. Telegram is a thread inside Jev that checks for messages, off until you pair it | – |
| Tests | 216 pass in 9.5 s | All pass, plus each phase's new ones | Every phase |

## How it fits together

```
mic ─► Silero + Smart Turn ─► speech-to-text ─┬─► voice ID (new, phase 1, runs alongside speech-to-text)
                                              ▼
                                  decider (new, phase 3, 3–10 ms):  for me?  which route?  follow-up?
                                              ▼
              routines and quick commands (as today, ~0.6 s) ──► Windows actions (as today)
                                              ▼
              one model call, streamed (phase 2) ──► first sentence spoken while the rest arrives
                                              ▼
              Hermes memory, skills, curator, review, session search (phase 4, copied Hermes code)
Telegram thread (phase 5) ─► the same handle(), replies go to the chat, risky steps get Yes/No buttons
Background jobs (phase 6) ─► tasks.py queue ─► OpenCode CLI for coding, reports back by voice and Telegram
```

## Can she do what Hermes does?

| Capability | Hermes | Jev today | After this plan |
|---|---|---|---|
| Memory and your profile (MEMORY.md / USER.md) | Yes | Yes, Hermes' code, 4 fixes behind | Current Hermes code, re-copied |
| Skills she writes from experience | Yes | Yes, light version | Hermes format, plus checks before a new skill is kept |
| Curator (tidies unused skills) | Yes | No | Yes, Hermes' rules: stale after 14 days, archived after 30, never deleted |
| Learning review in the background | Yes, ~30k tokens a run | Yes, ~3–4.5k tokens | Hermes' prompts and triggers in Jev's single call; corrections reviewed **at once** |
| Past-chat search | FTS5, windows, scroll | FTS5, single hits | Hermes' query cleaner, plus context around each hit, dates and trigram matching |
| Scheduled jobs | Cron | Timers, reminders, task queue | Plus Hermes' rules: late jobs, weekdays, and replies go back to wherever you asked from |
| Background agents | `delegate_task` | Research tasks | Durable coding jobs through the OpenCode CLI, with Yes/No for each risky step |
| Tools | Terminal, browser, files, MCP | Windows actions, web, vision, guarded PowerShell | Same, plus coding jobs. MCP left out (prompt size) |
| Telegram | Yes | No | Yes, owner only, with Yes/No buttons |
| WhatsApp | Yes, a Node bridge | No | Later, Hermes' bridge started only while switched on |
| Voice | Wake word and push-to-talk. In its desktop app, voice works for the first turn only (Hermes issue #75329) | Always listening, 0.7 s commands | Plus your voice only and streamed answers. Interrupting her comes later |
| Fast typed decisions | No | No | Yes, a local decider |

## The phases

Each phase is small, ships on its own branch and commit, has its own tests in `tests/` (using
`tests/support.py`), and must pass its gate before the next one starts. Phase 1's shadow days run while phase 2 is
built.

All together it's about 20–25 working days. The one fixed date is **her new voice in by 20 November**, ten days
before Fish's free model ends. Phases 0–2 come first for that reason.

### Phase 0: backup and fresh start (about half a day): **done 7 Oct**

Branch `phase0/fresh-start`, commit b412a4f. The backup is
`%LOCALAPPDATA%\Hey Jev\Backups\heyjev-2026-10-07_21-16-40.zip`: 417 turns, 13 USER.md entries, 7 skills. She
greeted you after the wipe. 222 tests pass.

**Goal:** your old data is zipped and restorable with one command. Memory starts empty, and on first start she says
"Hey, I'm Jev, what can I do for you?"

- **Before anything:** copy the 487 hand labels from the earlier session's temporary folder to
  `%LOCALAPPDATA%\Hey Jev\decider\` (your decision 11). They're phase 3's training data, and a temporary folder can
  be cleaned up at any time. They're never put in the repo, because the repo has a GitHub remote and they contain
  room and family talk.
- **Backup:** `python backup.py` stops if Hey Jev is running, because she holds the databases open. It then zips
  `%APPDATA%\Hey Jev` and the repo's `vocabulary.json` and `apps.json` into
  `%LOCALAPPDATA%\Hey Jev\Backups\heyjev-<date>.zip`. It also takes `%LOCALAPPDATA%\Hey Jev\voice\` and
  `decider\`, once they exist.
  - SQLite files are copied with Hermes' safe copy helper (`backup_sqlite.py:31-82`, copied in).
  - `python backup.py --restore <zip>` puts everything back.
  - Phase 3 reads the old `history.db` from this zip.
- **Fresh start**, suggested (your decision 1):
  - **Wipe:** `memories\USER.md` (13 entries), `MEMORY.md` (1 entry), the day files (4), `skills\` (7 skills, all
    notes, no routine has ever run), and `history.db` (415 turns).
  - **Keep:** settings, contacts, the app list, the Dictionary (7 words), the keys in Credential Manager, the models
    (1.3 GB), `SOUL.md` (identical to the default), `tasks.db`, the log (the Home tab's stats and the latency
    baseline come from it), and the 10 clips in `Logs\missed` (real voice samples for testing phase 1).
- **First run:** a `first_run` flag in settings. On the first start after the wipe she says the new greeting, then
  never again. It's a new line in `REPLIES` (siri.py:299), said where the start-up hello is called
  (siri.py:4459-4463).
- **Your name:** `skills.py:227` writes "Hari says:" into the prompt. It should use the name in Settings.
- **Tests:** backup then restore gives the same files; wipe leaves the kept files untouched; the greeting comes once.
- **Gate:** restore checked on a copy; all tests pass.

### Phase 1: only your voice (about 2 days of work + 2–3 days of shadow mode)

**Goal:** other people, the TV and videos are ignored silently. You read 10 sentences once. A switch turns it off.

- **Reuses:** sherpa-onnx's `SpeakerEmbeddingExtractor` and `SpeakerEmbeddingManager`, already installed and
  checked working on Python 3.14. It also reuses `load_speaker_embedding_model` and `compute_speaker_embedding` from
  sherpa-onnx's official `speaker-identification.py` example. The design copies jxlarrea/wyoming-voice-match (MIT),
  which checks each piece of speech so TV voices are stripped out.
- **Model (download, your decision 2):** 3D-Speaker CAM++ English, `3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx`,
  **29.6 MB**, Apache-2.0, from sherpa-onnx's GitHub releases. Published error rate is 0.73% on full-length speech.
  It is the fastest accurate model, about 2.5× faster than ResNet34. Backup: WeSpeaker ResNet34 (26.5 MB). If your
  accent is the problem: NeMo TitaNet small (40 MB). Avoid the Chinese-trained models and the `_LM` versions.
- **Where it goes:**
  - A `VoiceId` class in speech.py next to `Turn`, using the existing `MODELS`, `SHA256` and `model_path`.
  - The score is worked out in `Listener._end` **alongside** speech-to-text and carried on the text as `.owner`,
    the way `.sure` is.
  - In `act_on` (siri.py:4059), a turn that fails becomes "nothing for her", which lands in the existing silent path.
  - A turned-away turn is also **not added to `ROOM`** (siri.py:4070). Otherwise it would still reach the model later,
    as "said just before" on her next unnamed turn.
- **How strict:**
  - **Her name said:** a relaxed level, scored on the name plus the command together.
  - **No name** ("Answer without her name", the follow-up window, a yes to her question): a strict level.
  - **A bare "yes"** (about 0.4 s) is too short to check. If she's waiting for a yes to something risky, a short yes
    waits; "yes, send it" or right Alt works.
  - **Hold right Alt and dictation:** not checked. The key press proves it's you.
- **Enrolment:** 10 sentences, most starting with "Hey Jev", through the same speech-mode mic. They are stored in
  `%LOCALAPPDATA%\Hey Jev\voice\`, never sent anywhere. After that her picture of your voice slowly grows from turns
  she's very sure were you, up to about 40, with a guard against drift (Apple's "Hey Siri" approach).
- **Threshold:** set from your own clips (each sentence cut to 1–2 s and scored against the other nine), not
  sherpa's demo 0.6. The decision has three zones: accept, unsure, reject. Then **2–3 days of shadow mode**: every
  turn's score is logged and nothing is blocked. The real threshold is set from that log.
- **Cold or tired voice:** a relaxed level when her name is said. A second try with her name within 20 s is
  accepted. Right Alt always works. "Re-learn my voice" re-enrols.
- **Expected (estimate, to measure):** 15–60 ms per turn, run in parallel, so commands stay at 0.7 s. +40–70 MB.
  About 2–5% of your turns turned away and 1–2% of other voices let through, before tuning.
- **Limits, said plainly:**
  - A recording of **your own** voice on a phone or TV will usually pass. Replay detection isn't worth it
    (published detectors fail outside their test conditions).
  - Family members of the same sex and accent are the realistic slips.
  - Telugu talk to family passes voice ID; the existing "is it for her?" logic still decides it.
- **Tests:**
  - **Unit tests in `test_listening`, with made-up scores:** accept and reject at each level, right Alt never
    checked, the switch off lets everything through, and a rejected turn stays out of `ROOM`.
  - **A separate manual script with the real model:** your clips pass, and Windows' Heera and Ravi are turned away.
- **Gate:** in the shadow-mode log, turns with her name (taken as yours) are accepted ≥ 95% at the chosen
  threshold. Command latency unchanged.

### Phase 2: faster answers (about 3–4 days)

**Goal:** the first word of the answer ≤ 2 s after you stop (median). A filler doesn't count towards this.

- **Stream the model reply.** Today `opencode.chat` sends one request and waits for the whole reply
  (opencode.py:82).
  - Add `"stream": true`, and change the reply to **one JSON line with `to` and `steps`, then the spoken text as
    plain lines**. The reviewer found `parse_plan` already accepts this shape, and it's simpler to stream than a JSON
    string with escapes.
  - Every safety gate sees the steps before she says a word.
  - The whole plan is still awaited, as today, for anything that needs a yes, power, messages, installs and
    **tasks**. Tasks are included because the task-claim guard (siri.py:2342-2344) can rewrite her spoken line
    afterwards.
  - Plans that end in a yes-question, and room talk she lets go, never stream.
  - The spoken lines go to the voice a sentence at a time, split by Hermes' `SentenceChunker`. Only the class is
    copied (`tools/tts_streaming.py:66-117`, MIT), not the module, which pulls in Hermes' TTS tool.
  - A plain answer has no steps, so speech starts after about 10 words.
- **The model: keep today's two free models, Ling (Kilo) and space-bunny (OpenCode).** You decided on 7 Oct: no new
  accounts.
  - The time is saved in other ways instead:
    - streaming the reply;
    - the local voice (−0.7 s);
    - no `skill_view` round trip (−~3 s on those turns);
    - warming Ling's host (a cold connection costs ~0.8 s);
    - a shorter prompt.
  - Expected: about **3 s** to the first word of the answer, down from 4.6 s, with a filler at 1.2 s.
  - The rest of the gap is the free models' own wait. Ling's hidden "thinking" comes before its first word, and
    space-bunny takes ~3 s even for 35 words.
  - Try Ling with reasoning switched off, if Kilo allows it.
- **Optional, only if you ever want the full 2 s** (researched, not part of the plan now). No card is needed for any of
  these (checked 7 Oct 2026).
  - **First choice: Groq's free plan, `gpt-oss-20b`, reasoning low.**
    - About 0.21 s to the first word at 1k tokens and 0.77 s at 10k; 910 words a second. These are Artificial
      Analysis figures, measured from the US.
    - Nothing is kept by default, and there's a zero-retention switch.
    - Limit: 8k tokens a minute and 200k a day, but "cached tokens do not count towards your rate limits". With the
      unchanging part of the prompt cached, that's about 10 calls a minute and ~250 a day, against her 120–240 a day
      today. About half of those were room talk, which phases 1 and 3 stop sending.
    - Never send two requests to Groq at once, because a pair can break the per-minute limit. Bursts (up to 11 a
      minute in the log) and the first call after 2 h (the cache expires) can go over it; those go to Mistral.
  - **Backup and hedge: Mistral's free mode, `mistral-small-4`.** About 0.48–0.71 s to the first word. It trains on
    your data by default; turn off "Anonymous improvement data" in its Admin panel.
  - **Ruled out:**
    - Cerebras and SambaNova need a card.
    - OpenRouter gives 50 requests a day unless you buy $10 of credit.
    - GitHub Models was retired on 30 Jul 2026.
    - Gemini's free tier trains on your text and has human reviewers.
    - NVIDIA's terms are trial-only.
  - **First step of the phase:** add per-turn timings to the log (prompt build, first word, first sentence, first
    audio). Keep the line beginnings the Home tab's stats read. Then measure time-to-first-word **from this PC**,
    20 runs each, with the real prompt (Ling and space-bunny, streamed).
  - Groq can't stream with a strict JSON schema, so keep today's prompt-instructed JSON and its tolerant parser.
  - **Expected, from the evidence (end of speech to first sound, median):**

    | | Today | **Plan: Ling + Pocket** | Optional: Groq + Pocket |
    |---|---|---|---|
    | End of turn + speech-to-text | 0.52 s | 0.52 | 0.52 |
    | Prompt + network | in model | in model | 0.23 |
    | Model to first sentence | 2.5–3.3 s | ~2.0–2.3 (estimate: thinking, then the first words) | 0.53 |
    | Voice to first audio | 1.0 s | 0.30 | 0.30 |
    | **Total** | **~4.8 s** | **~2.8–3.1 s** | **~1.6 s** |

    The slow 10% stays higher in every setup, which is why the filler is part of the design.
- **Hedge on the first word, not the whole answer:** if no first word has come by ~1 s, send the same request to
  the backup and keep whichever streams first. Today the backup goes out at 2.5 s and ~half the turns send two.
  The log had 19 "too many requests" errors, so background work (day summaries, reviews, research) goes to a
  different model than voice turns.
- **Filler:**
  - If no sentence is ready 1.2 s after you stop, she plays a cached "On it." / "One moment." / "Let me check." at
    0 ms. The 1.2 s is a design choice. The paper (2507.22352) showed natural spoken fillers help at 4 s and 6.5 s
    waits, while beeps didn't help at all.
  - Always when a web look-up starts. Never for quick commands, never twice, never before an unnamed turn is known
    to be for her.
- **Cheaper turns:**
  - Put the skill notes in the prompt instead of a `skill_view` round trip, which is the most common look-up. Cap
    them for now, because the decider that picks the 1–3 relevant skills only arrives in phase 3.
  - Warm the Kilo host too (today `warm()` misses `api.kilo.ai`), on speech start and on right Alt.
  - Shorten the step list (one line per step), keep 3 turns of history instead of 6, and move the clock and the
    front app to the end so the rest stays the same between calls.
- **The voice after 30 November (your decision 3).** This is its own step, **finished by 20 November**. When the new
  voice goes in, her cached lines (`cache\tts`) are made again in it.
  - Recommended: **Kyutai Pocket TTS int8** through the sherpa-onnx already installed. It's
    `sherpa-onnx-pocket-tts-int8-2026-01-26`, a **98.3 MB** download (~190 MB on disk), code MIT, weights CC-BY-4.0.
  - It's local and free for good, so not even the reply text leaves the PC.
  - First audio in ~0.2–0.4 s instead of Fish's ~1.0 s, which also helps the 2 s target.
  - It uses 2 cores, ~350 MB once loaded and ~600 MB while speaking.
  - The sherpa-onnx version takes its voice from a short reference clip. Use one from Kyutai's CC0 or CC-BY voice
    sets (some of their sets are non-commercial), or from someone who agrees. **Never a copy of Fish's Miku.**
  - Windows' Heera/Ravi stay as the last fallback.
  - Before switching, one benchmark on this laptop with speech-to-text loaded.
  - Kokoro stays out, as you decided.
- **Tests:** `test_planner` and the `Voice` tests in `test_actions`, plus new ones:
  - the streamed reader on pieces split at awkward places;
  - gated and task plans never speak early;
  - a filler at most once;
  - a prompt-size test: ≤ 3,000 tokens for the fixed part, ≤ 4,000 in total.
- **Gate:**
  - Over a day of real use, the median time to the **first word of the answer** is ≤ 3 s, fillers not counted
    (≤ 2 s only with the optional faster provider).
  - Quick commands still ≤ 0.7 s, and no rise in wrong actions.
  - The new voice is in.

### Phase 3: decision maker (about 3 days + shadow mode)

**Goal:** quick decisions in milliseconds; the model only writes.

The research found the biggest real mistake isn't picking the wrong action. It's "is this for her?":

- On 6–7 Oct she let go 21 of 145 requests meant for her.
- She answered 33 of 118 phrases that weren't meant for her.

That is 54 errors, against 22 wrong actions or replies (13 + 9).

- **Model (download, your decision 2):** `sentence-transformers/all-MiniLM-L6-v2`, file
  `onnx/model_quint8_avx2.onnx`, **23.0 MB** + tokenizer 0.5 MB, Apache-2.0.
  - Runs on onnxruntime, tokenizers and numpy, all already installed.
  - 3–10 ms a decision, 60–100 MB, 2 threads so it doesn't slow speech-to-text.
  - Lighter option: `minishlab/potion-base-8M` (30.2 MB, MIT, under 1 ms), but it's weaker on "don't" and word order.
- **Heads:** small logistic regressions in numpy (about 30 lines). The input is the sentence plus what Jev already
  tracks: the kind of turn, time since her last reply, whether she just asked something, media playing,
  speech-to-text confidence, name found, and recent room talk.
- **Answers in the same shape as Jev/Laya's `/v1/systemone`.** The parser is reused from this repo's own first
  version, which called TypeSafe's Jev just as the Mac Hey Jev does (`git show 5d9bbc0:siri.py`, `jev()` at line
  73). It's a few lines. Laya, Julia-1 or the hosted Jev can then be swapped in later without changing callers.
- **What it decides:**
  1. `for_me` (open mic and the follow-up window). A confident "not for her" saves the model call. A confident "for
     her" only means the model is called.
  2. `route`: answer only / look-up / screen / act / write / task / unclear. A look-up then starts at once, saving a
     model round trip of about 3 s. A screen request goes straight to vision, saving about 2 s.
  3. `follow_up` vs new request.
  4. Which skill applies, by similarity to its trigger phrases.
- **What stays rules, always:** her name, a yes to her question, numbers, apps and durations, formulaic commands
  (`QUICK`, `fast_intent`), and **every safety rule**: `needs_asking` (including "Should I look at your screen?",
  since the screenshot goes to a cloud model), power, `tasks.command_policy`, and negation ("don't", "cancel").
  **The decider never drops a question and never clears the unnamed-turn checks (`gate`).**
- **What stays with the model:** writing answers, plans with free text, fixing misheard words, vision.
- **Training data, already there:**
  - the 487 hand-labelled turns from the 4–7 Oct log review (saved in phase 0);
  - the 1,411 room phrases she let go;
  - the 143 turns with plan steps in the old `history.db`, read from the phase 0 backup;
  - the `fast_intent` patterns.

  Tests are kept apart, for checking only.
- **How it goes live** (stuntd's pattern):
  1. Collect.
  2. Train.
  3. Shadow: log only.
  4. Live, only above a level set for ≥ 95% precision on held-out turns.
  5. Back to shadow on its own if agreement drops.
- **Where:** a new `decider.py` (~200 lines). It's called from `route()` (siri.py:224), `could_be_request()` (266),
  `handle()` between `quick()` and `think()` (3712–3733), and `let_go()` (3602). `history.add()` logs its answers.
- **Expected (estimate, checked offline before going live):** model path right 46% → ~55%; requests for her that are
  let go or answered wrongly fall; room talk answered 28% → ~15%. Look-up turns save ~3 s.
- **Tests:** `test_routing`, `YesOrNo`, `test_safety` and `test_open_mic.py`, plus:
  - no decider answer can remove a question or clear `gate`;
  - negations never flip a safety ask;
  - low confidence falls back to today's behaviour.
- **Gate:** offline accuracy on held-out labels beats today's rules; a day of shadow mode agrees ≥ 95% where it
  would act.

### Phase 4: Hermes memory and learning (about 4–5 days)

**Goal:** she learns from you like Hermes, fixes mistakes as soon as you correct her, tidies unused skills, and
finds the right moment in past chats.

- **How Hermes code comes in:** `hermes_memory/UPSTREAM.json` holds commit 3569fba6 and the file list.
  - A dev-only `sync_hermes.py` copies the file bodies unchanged and rewrites a fixed set of imports.
  - It prints what changed upstream since the last pin, so updates are a reviewed step, not a surprise.
  - A ~60-line `_compat.py` supplies the few helpers the copied code expects.
  - Total ~1.4–1.9k lines of plain Python (Jev has ~1,040 today), with no new packages and an import cost of tens
    of ms.
- **Memory:**
  - Re-copy `memory_store.py`, which is 4 upstream commits behind (5–6 Oct). The fixes: matching that copes with
    curly quotes and dashes, a fix so a hand-edited USER.md no longer blocks every remove or replace (the Memory
    tab needs this), and clearer errors.
  - `threat_patterns.py` is already current.
  - Memory is capped at Hermes' limits (2,200 + 1,375 characters), about 970–1,410 tokens when full.
- **Skills:** keep Jev's lighter `skills.py`, adding Hermes' rules:
  - the 60-character description limit (`skill_utils.py:822`);
  - YAML-safe frontmatter (a bare "on" becomes a yes/no in Hermes' reader);
  - `platforms: [windows]`;
  - archive instead of delete.

  Your routines stay Hermes-compatible: Hermes ignores the extra `triggers` key. Only the 1–3 skills the decider
  picks go into the prompt in full; the rest appear as names only. Hermes users found hidden skills are "not
  reliably rediscovered" (Hermes #2045), so the names stay listed.
- **New-skill checks:** a skill is kept only after the task succeeded, and only if it isn't a near-duplicate of an
  existing one. Self-written skills drift into uselessness without this (SkillsBench; Ratchet 2605.22148).
- **Curator:** Hermes' rules, copied:
  - usage tracked in `.usage.json`;
  - stale after 14 days, archived after 30, never deleted;
  - runs weekly after 2 h idle;
  - no model calls;
  - routines you taught her are never archived automatically.

  Hermes' optional model-based merging (50–100 calls) stays off.
- **Learning review:** Hermes' review prompts and "what not to keep" rules, inside Jev's single review call
  (~3–4.5k tokens a run, against Hermes' ~30k). Hermes' trigger counts apply: every 10 turns, reset whenever she
  saves something herself.
- **Corrections at once:**
  - When you correct her, the review runs right after her reply. Today it waits 20 s plus a 90 s gap.
  - The correction is passed in as the focus.
  - Simple ones ("no, I said Zostel", "forget that") are handled in code straight away (Mem0's
    add/update/delete/no-op).
- **No "ask before keeping":** you declined it. Hermes forces a staging step for background removals, so instead
  every background change goes into an **undo journal** (your decision 7), so "undo that" works.
- **Past-chat search:** in `history.py`:
  - Hermes' query cleaner and its fallback to looser matching (~70 lines, copied as-is).
  - A trigram fallback (the SQLite here supports it).
  - A few turns of context around each hit, with scrolling.
  - Before/after dates, and skipping hits already seen.
  - Conversations split by gaps, so "what did we talk about at lunch" finds one sitting.
  - Plain keyword ranking (BM25) beat dense retrieval on agent memory (60.5 against 33.9, MemoryAgentBench
    2507.05257), so no embeddings are needed.
- **Tests:** `test_planner` `Learning`, plus: a correction changes memory before the next turn; the curator archives
  only her own unused skills; search finds a turn by a near-miss word; the prompt stays under budget with full
  memory.
- **Gate:** with full memory and 40 skills, the fixed prompt is ≤ 3,000 tokens and the total ≤ 4,000. No extra
  model call per voice turn.

### Phase 5: Telegram (about 3–4 days)

**Goal:** chat with Jev from your phone; only your account; risky steps get Yes/No buttons.

- **Reuses:**
  - **python-telegram-bot 22.8**, the version Hermes pins (769 KB, LGPL-3.0, supports Python 3.14). Its one
    dependency, httpx, is already installed (+190 ms, +15.6 MB on import). This is the plan's only new package.
  - ~250 lines of Hermes' own logic, copied into `telegram_bot.py`:
    - message splitting that keeps emoji and code intact: `truncate_message` (base.py:4875-4933) with `utf16_len`
      (225-231), `_custom_unit_to_cp` (234-245) and `fence_state_after` (helpers.py:538-545);
    - the button flow (adapter.py:4179-4181, 4233-4249, 4667-4762), with taps refused unless allowed (830-865).
      Your account is checked on every tap, the first tap wins, it's settled before the card is edited, and after a
      timeout it says "expired, not run";
    - token redaction;
    - Hermes' pairing rules (pairing.py:29-37): 8-character codes, 1-hour expiry, lockout after 5 tries, stored
      hashed.

    The question on the card is Jev's own `confirm_question`, plus Hermes' line that nothing happens if you don't
    answer.
- **How it works:**
  - It runs on its own thread inside Jev, because python-telegram-bot needs its own asyncio loop. It's imported
    only when switched on, so startup isn't slower, and it stays **off until you pair your phone**. It only works
    while the PC is on.
  - The thread starts inside `run_voice_assistant`, where the `busy` lock lives.
  - Text goes into the same `handle()` as voice. Replies go back to the chat instead of `say()`.
  - Long polling only, so nothing on the PC is open to the internet.
- **Owner only, failing closed:**
  - Private chats only, and only your numeric Telegram ID. It refuses to poll at all until that ID is set. A bare
    Hermes adapter lets everyone in without an allowlist (adapter.py:987-990).
  - Only plain messages and button taps are accepted.
  - Strangers are ignored, and you get one notice per stranger.
  - **Messages waiting from while the PC was off are dropped at start, as are any older than 2 min**
    (adapter.py:690-695). Otherwise a "shut down" sent while the PC was off would run at the next start.
  - **Pairing once (your decision 6, recommended):**
    1. You open a 10-minute pairing window at the PC.
    2. You send `/start` to your bot, and it replies with a code.
    3. Jev's window shows which Telegram account asked.
    4. You type the code into Jev's window.

    That proves you have both the phone and the PC.
  - The bot token lives in Windows Credential Manager, where Hermes keeps it in a plain `.env`.
  - Turn off "join groups" in BotFather.
  - `watch.py` ignores the bot's own messages, so her heads-ups don't announce her own replies.
- **Yes/No buttons** sit on Jev's own rules, which are stricter than Hermes': Jev asks for anything not on a
  read-only list, approvals survive a restart, and an interrupted command asks again.
  - A tap resolves a waiting plan or a task (`TASK_STORE.approve/cancel`).
  - Today there is one global waiting plan (`PENDING`, siri.py:3640). It becomes **one per place it was asked from**,
    so a "yes" said at the PC can't approve something asked on the phone, and the other way round.
  - Risky steps asked from the phone need the button.
  - Hermes' "approve for the session" and its model-judged auto-approve are **not** taken. No PIN, as you decided.
- **Voice notes:** decoded on the PC (soundfile / PyAV, already installed), then written by the speech-to-text engine
  already loaded (`Ears.transcribe()`), so no second model is loaded. **Never** Hermes' cloud fallback.
  - The note itself travels through Telegram's servers, as every Telegram voice note does (your decision 6).
  - Replies can come back as text, or as a voice note: Bot API 10.3 takes MP3, so no conversion is needed.
- **Safety after reading:** after she reads a web page or a message, risky steps need your Yes (button or voice),
  checked in code, not by the model (CaMeL 2503.18813, AgentDojo 2406.13352).
- **Tests:**
  - a stranger's message is ignored;
  - a tap from another account does nothing;
  - an expired card can't run;
  - a message older than 2 min is dropped;
  - the bot won't poll before pairing;
  - a voice "yes" can't approve a phone request;
  - long replies split correctly;
  - a voice note is transcribed without network.
- **Gate:** voice latency unchanged with the bot running; idle CPU unchanged.

### Phase 6: coding and agent jobs in the background (about 4–5 days)

**Goal:** longer jobs run in the background and report back when done.

- **Reuses:**
  - Jev's durable task queue (`tasks.py`), which already survives restarts.
  - The **OpenCode CLI already installed** (1.18.31, `~/.bun/bin/opencode`).
  - The stdio ACP client from Hermes' GitHub Copilot integration, about 120 lines (`copilot_acp_client.py:137-143,
    227-276, 380-506`). Hermes answers every permission request with "cancelled"; **Jev turns each one into a Yes/No**
    on the phone or by voice.
  - It was written for Copilot, so **day one is a short test that `opencode acp` on 1.18.31 talks to it**.
- **Confined, because OpenCode allows edits and commands by default** (checked on opencode.ai/docs/permissions,
  7 Oct):
  - Start `opencode acp` with
    `OPENCODE_CONFIG_CONTENT={"permission":{"edit":"ask","bash":"ask","webfetch":"deny","external_directory":"deny"}}`.
    That setting outranks the project's own `opencode.json`, which the agent could otherwise edit.
  - Every edit and command then becomes a permission request. Commands go through Jev's `tasks.command_policy`:
    blocked ones are refused, read-only ones allowed, everything else a Yes/No.
  - A git snapshot of the folder is taken before the job starts.
  - `code` jobs join `CHANGES_PC`, so they never re-run by themselves after a restart.
- **How:**
  - A new `code` job kind (tasks.py:25, `task_worker` 2573). It waits for your Yes, then runs OpenCode on a free
    model in one project folder only (your decision 8), with a long timeout.
  - It reports through `ANNOUNCE` and Telegram when done.
  - "Is it done" comes from exit codes and output first. The decider only shapes her spoken summary.
- **Optional (your decision 9):** with one test call to OpenCode's free `jev-1.13-free`, coding jobs can ask the
  hosted Jev quick typed questions ("is this step done?", "which file next?").
  - Speed: TypeSafe says 70–500 ms (vendor figures, in the eesel and TrueFoundry write-ups). This repo's first
    Windows version measured 755 ms median and 1.49 s p90 from here.
  - It's never used on voice turns, and it's dropped when the free offer ends.
- **Cron rules from Hermes,** added to `tasks.py` instead of copying its 18.5k-line cron:
  - a one-off reminder more than 2 min late is said as late, or dropped (your decision 10);
  - **a one-off command, install or code job more than 2 min late never runs by itself**: she tells you it was
    missed and asks again. Today `claim_due` (tasks.py:161-181) runs anything already due;
  - repeating ones catch up within half their period;
  - "weekdays at 9";
  - results go back to wherever you asked from (voice or phone);
  - checks that stay quiet when nothing changed.
- **Tests:** `test_timers` `Worker`, plus:
  - a code job never starts without a Yes;
  - each permission request becomes a Yes/No or follows `command_policy`;
  - the confining setting is always passed;
  - an edit outside the folder is refused;
  - a job doesn't re-run by itself after a restart;
  - a late command asks again.

  A command could still write anywhere once you say yes to it. That's why commands go through `command_policy` and
  your Yes, and not through settings alone.
- **Gate:** voice turns unaffected while a job runs.

### Later: WhatsApp

Reuse Hermes' Baileys bridge unchanged (Node 24.15 is already installed), started only while switched on, with a
~150-line Python client. Use a **spare number**, because ban risk falls on the account used. Meta's own Cloud API
needs a business account, and its terms from 15 Jan 2026 bar general-purpose AI assistants. Start after Telegram has
been stable for a while.

### Later: interrupting her ("stop")

Today `say()` mutes the mic for her whole reply.

- **Reuses:** Hermes' barge-in rules: wait 500 ms after she starts, trip on 80% of 300 ms, keep 1.2 s from before.
  The constants are at voice_mode.py:1308-1310, `_BargeDetector` at 1335-1408 and `full_duplex_listen` at 1410-1458.
- **Only on "stop" and the like, from your voice:** a study found only 11% of barge-ins set off by any recognised
  speech were real; the rest were backchannels, noise and echo (Duplex Conversation, KDD 2022).
- **The catch is CPU:** keeping Nemotron listening while she speaks costs ~2.3 cores, on top of Pocket's 2. The light
  way is sherpa-onnx's keyword spotter: the library is installed, but its small model would be another download
  (size to check).
- **Windows 11's "Voice Clarity" echo cancelling** works only on Communications-mode capture, and Windows may lower
  other sounds during "communications". Test it before moving off today's Speech mode.

## Your decisions (recommended default first)

1. **What the fresh start wipes:** memory, the day files, skills and old chats (`history.db`). **Keep:** settings,
   contacts, app list, Dictionary, keys, models, `tasks.db`, the log and the 10 voice clips.
2. **Downloads,** each from the official source:

   | File | Size | Licence | Phase |
   |---|---|---|---|
   | CAM++ voice ID | 29.6 MB | Apache-2.0 | 1 |
   | MiniLM int8 | 23.0 MB + 0.5 MB | Apache-2.0 | 3 |
   | Pocket TTS int8, only if chosen in 3 | 98.3 MB | MIT / CC-BY-4.0 | 2 |
   | python-telegram-bot 22.8 | 769 KB | LGPL-3.0 | 5 |

3. **Her voice after 30 Nov:** Pocket TTS on the PC (recommended), or Windows' Heera/Ravi only, or edge-tts. edge-tts
   is free, but the reply text goes to Microsoft, it's unofficial, and it broke repeatedly in 2026.
4. **Model provider: decided 7 Oct.** No new accounts; she stays on Ling and space-bunny. That's about 3 s instead
   of 2. Groq and Mistral stay written up in phase 2 as an option for later.
5. **Voice ID details:**
   - Dictation not checked (recommended).
   - A turned-away named turn shows a small "didn't sound like you" in the popup only, no sound (recommended).
   - Keep the enrolment recordings on the PC so the model can be swapped without re-reading (recommended).
6. **Telegram:**
   - Pairing in a 10-minute window opened at the PC, typing the bot's code into Jev's window (recommended).
   - Phone voice notes travel through Telegram's servers before being transcribed on the PC: OK?
7. **Background memory changes:** an undo journal (recommended), or never remove anything.
8. **Coding jobs:** which folder OpenCode may work in (recommended: one projects folder), and each edit or command
   approved by Yes/No.
9. **Hosted Jev test:** one test call to `jev-1.13-free` with your existing OpenCode key (recommended yes, for phase
   6 only).
10. **Late reminders:** said late (recommended) or dropped. Late commands, installs and code jobs never run by
    themselves either way.
11. **Decider training data:** copy the 487 hand labels from the earlier session's temporary folder to
    `%LOCALAPPDATA%\Hey Jev\decider\`, never into the repo (recommended yes, **soon**, before that folder is
    cleaned up).

## Risks

- **Free services end or slow down:** Ling, space-bunny, Fish (30 Nov) and `jev-1.13-free` are all "for now".
  Mitigations:
  - Everything quick stays on the PC.
  - Two model providers with failover.
  - A local voice.
  - Settings > Refresh to re-check.
- **Rate limits:** 19 "too many requests" errors in a week. Mitigations: background work goes to another model, the
  backup is sent only when no first word has come, and shorter prompts.
- **Voice ID turning you away:** shadow mode first, the relaxed level with her name, right Alt always works, and
  re-enrolment.
- **Decider mistakes:** it only goes live where it measured ≥ 95% precision, it can never remove a safety question,
  and it falls back to shadow mode by itself.
- **CPU:** Nemotron streaming uses ~2.3 cores while anyone talks; Pocket uses 2 while she speaks. Today they don't
  overlap, because the mic pauses while she talks. Interrupting her (later) would change that. To be measured in
  phase 2.
- **Telegram while the PC is off:** messages sent then are dropped, not run later. She can't be reached when the PC
  is off or asleep.
- **Hermes moves fast:** v0.21.4 alone rolled up ~1,800 PRs. Hence the pinned commit and the reviewed sync, never
  live imports.
- **Prompt injection from web pages and messages:** structural rules in code, never prompt wording alone. Adaptive
  attacks get past more than 90% of prompt-level defences (2510.09023).

## Research notes and main sources

The notes are in this session's scratchpad `research\` folder:
`jev-code-map.md`, `hermes-learning.md`, `hermes-reach.md`, `voice-id.md`, `speed.md`, `providers.md`, `tts.md`,
`decider.md`, `papers.md` and `community-github.md`.

- Hermes Agent, MIT: github.com/NousResearch/hermes-agent at 3569fba6. PyPI `hermes-agent` 0.19.0 requires Python <3.14.
- Laya: github.com/NandhaKishorM/laya (0.4.0, 7 Oct 2026). TypeSafe Jev on OpenCode Zen: opencode.ai/docs/zen
  (updated 6 Oct 2026).
- sherpa-onnx speaker models: github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models.
- jxlarrea/wyoming-voice-match (MIT).
- Fish free model end date: fish.audio/blog/s2-1-pro-free-api and docs.fish.audio/changelog.
- Kyutai Pocket TTS: github.com/kyutai-labs/pocket-tts; the sherpa-onnx port in its tts-models releases.
- Groq free limits and caching: console.groq.com/docs/rate-limits and /docs/prompt-caching. Speeds:
  artificialanalysis.ai/models/gpt-oss-20b/providers. Mistral free mode: docs.mistral.ai (all fetched 7 Oct 2026).
- Papers:
  - Short-utterance speaker verification: 2406.07103, Sub-3Sec (Interspeech 2025).
  - Fillers and latency: 2507.22352.
  - Tool retrieval: RAG-MCP 2505.03275.
  - Memory: LongMemEval 2410.10813, MemoryAgentBench 2507.05257, Mem0 2504.19413.
  - Skills: SkillsBench 2602.12670.
  - Injection: CaMeL 2503.18813, AgentDojo 2406.13352.
- Hermes users: issues #4379 (73% of each call is fixed overhead), #2045, #66180, #67582, #75329, #83683.
