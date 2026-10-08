# Hey Jev (Windows, free models only)

A voice assistant for your PC. Say "Hey Jev" (or "Hello Jev", or just "Jev") or hold right Alt, ask for something, and she does it and answers back. Everything runs on free models, with no billing anywhere.

- Simple commands ("open Notepad", "pause", "scroll down", "louder", "set a timer for 5 minutes") are worked out on your PC, so they happen about half a second after you stop talking
- Anything else goes to a free OpenCode Zen model (`space-bunny-free`) that plans the steps: "search career ID on YouTube and play the first video", "open Notepad and write a poem about rain", "who directed Iron Man 2?". That takes about 2.5 to 4 seconds more in real use, sometimes longer on the free models
- She listens in small pieces while you talk, all on your PC: Silero hears speech 32 ms at a time, and Smart Turn, a small AI turn-taking model, decides at each pause whether you've finished, from your tone as well as the quiet. Finished, she answers straight away. Mid-sentence, she waits for the rest. Parakeet (NVIDIA) turns it into text. See Listening below
- Fish Audio S2.1 Pro speaks every reply on its free model (`s2.1-pro-free`), in a voice you pick in Settings. New lines play while Fish is still making them
- Vision: she can look at the screen when you ask, "what's on my screen?", "click the second video", and act on it
- A personality in the spirit of JARVIS, and [Hermes Agent](https://github.com/NousResearch/hermes-agent)'s memory, skills and learning loop: teach her a routine once and she runs it from then on, and she learns from your corrections
- The internet, free and without keys: facts, the news, the weather, and research that carries on in the background while you work
- Heads-ups: new messages (your phone's too, through Phone Link), a low battery, a full drive, the internet going

This is a Windows port of [henryklunaris/hey-jev](https://github.com/henryklunaris/hey-jev), which is Mac only. AppleScript became Windows APIs, the Keychain became Credential Manager, the AppKit window became a Tk window, and the paid services (OpenRouter, TypeSafe, OpenAI) became free ones. The Mac version decides with Jev, TypeSafe's model, which only picks from a fixed list of commands, so here a free chat model plans the steps instead. She's still called Jev. Works on Windows 10 and 11.

## Free models only

Hey Jev refuses any model that isn't free before a request goes out, so nothing can be billed, even if billing is turned on at OpenCode later. Settings won't save a paid model either.

Free models are free for a limited time, and they can end without notice:

- If the free answer model ends, the simple commands still work, since they never need it. For everything else she says her brain isn't answering, and the window says why. Settings > Refresh lists the free models that work now.
- Fish's `s2.1-pro-free` is free until the end of November 2026. After that her voice stops unless Fish keeps a free model.

OpenCode keeps most of its free models for its own coding app. From Hey Jev, `space-bunny-free` works, and the rest return "OpenCode's free tier can only be used from within OpenCode" (checked October 2026).

With a Kilo key she also gets [Kilo Gateway](https://kilo.ai/docs/gateway/)'s free models (the ones ending in `:free`). On her own prompt, Ling 3.0 Flash Sante answered in about 2 s (median of 5 requests, worst 2.8 to 6.6 s), against 3.7 s for space-bunny. In real use, 1 to 7 October 2026, Ling's median was about 2.6 s a call (4 s at p90), and space-bunny's about 3 to 4 s. Cohere North Mini Code, Step 3.7 Flash and Nemotron 3 Super were slower or timed out, and Kilo's two auto routers didn't give her JSON. So Ling is her model, and when it's slow or busy (free models are rate limited) her second try goes to space-bunny on OpenCode, and the other way round. Screenshots always go to space-bunny, since Ling only reads text.

## What it can do

- Apps: open, close, minimise or switch to anything in the Start menu. Close works the way clicking X does, so apps can still ask about unsaved work. Apps that only drop to the tray (Spotify, Slack, Discord) are then ended.
- Websites and search: "open YouTube", "open github.com in Edge", "google the weather in Delhi", "search lofi music on YouTube".
- Music and video: "play Arijit Singh songs" plays YouTube's top video for it. Play, pause, next and previous work on whatever is playing, YouTube in the browser or Spotify. On Spotify, "previous" partway through a song goes back a song, not to its start. VLC 3 isn't in Windows' media controls, so when nothing there is playing and VLC is open, she brings it to the front and presses its own keys: pause, next and previous while VLC is playing, and play when nothing else is in the media controls. Before a new video starts, the last one is paused, so two don't play at once. The browser is brought to the front, since Chrome holds a video back while its window is hidden behind others. She hears you over the video, see Echo cancelling below.
- The app in front: "scroll down", "scroll to the top", "new tab", "close this tab", "go back", "refresh", "make it full screen" on YouTube, and other shortcuts.
- Keyboard shortcuts, pressed on the PC with no model: about 160 of Windows 11's own and those of Chrome and Edge, File Explorer, YouTube, Word, VS Code and Notepad (`shortcuts.py`, from Microsoft's, Google's and YouTube's own lists). "Show the desktop", "snap this window left", "open clipboard history", "emoji panel", "new virtual desktop", "reopen the closed tab", "turn on captions", "rename this file", "open the command palette". The app in front decides: "new tab" is Chrome's or File Explorer's, "full screen" is YouTube's own on YouTube. The Windows key is only ever pressed for one of these, never for a plan the model made. Heard without her name, only ones that show or move things, never paste, undo and the like. Nothing that deletes, signs out or runs things is in the list.
- Writing: "open Notepad and write today's date", "write a short email saying I'll be late". The text goes where your cursor is.
- Volume, mute, a volume level (in digits or words), an app's own volume, dark mode, lock or sleep the PC, or shut it down or restart it after a yes.
- Timers and reminders: "set a timer for 5 minutes", "remind me in 20 minutes to call Mum", "remind me every hour to drink water", "how long is left?", "cancel the 5 minute timer". Timers, and one-off reminders due within 12 hours, count down live in the window, and she tells you when each is done. "Cancel the timer" cancels only timers; "cancel my reminders" or "stop reminding me to drink water" names the reminders and cancels them after a yes.
- Questions and chat: "what's the capital of Japan?", "and Australia?", "hello", "thanks".
- Several things in one go: "open Chrome and search for career ID".
- Remembering: "remember that my website CareerID is careerid.in", then later "open CareerID". "What do you remember about me?", "forget that ...". See Memory below.
- Looking back: "what did we talk about yesterday?", "what was that video I played?".
- The PC: "check the storage of C drive", "is my laptop charging?", "how much RAM am I using?", "what's using the CPU?", "am I online?", "how long has the PC been on?". Simple ones are answered on the PC straight away.
- Browser profiles by name: "go to my Harish profile", "open Gmail in my Work profile". She reads Chrome's, Edge's and Brave's profile list, and when Chrome starts with nothing open she uses the last profile, so its profile picker doesn't get in the way.
- A hello when you sign in or come back to the laptop, see Starting with Windows below.
- The screen: "what's on my screen?", "read this page to me", "click the sign in button", "play the video about biryani", "search for lofi music in this box". See Vision below.
- The world: "who directed Iron Man 2?", "what's the latest news?", "will it rain tomorrow?", "what's the weather like in Delhi?". See The internet below.
- Research: "research the best budget phones in India under 20,000". She looks into it in the background, reads a few pages, tells you when she's done and saves a note. "Make a note: ...", "open my notes".
- Messages: "any new messages?" reads what came in on WhatsApp, Teams, Messages and so on. See Heads-ups below.
- Routines: "when I say work mode, open Gmail in my Work profile and set the volume to 30", then just "work mode". See Skills and learning below.

Hide works like minimise, since Windows has no hide.

### Vision, and tasks she learns by doing them

When you ask about the screen, or for a task in an app that none of her steps covers ("turn on night light", "send a mail to ..."), she says it back first ("Okay: turn on night light.") and then does it a few steps at a time (`agent.py`). She reads the window in front by Windows UI Automation: its buttons, boxes, switches and links, by name. That goes to the answer model, which says what to click, fill in or press next; she does it and looks again. Only when the controls aren't enough (a window that shows few or none, one too slow to read, a task about "this" or "the second one", the model asking to see, or a step that changed nothing) does a screenshot go too, shrunk to 1280 pixels wide, to `space-bunny-free`, which takes pictures, five at most a task. Plain "click ..." asks go straight to the button by name.

Once it's done, and code has checked on the screen that it is (the switch is on, the mail's gone), she keeps what she did as a procedure, written by code and never by a model: "Okay, night light's on, and I've learned how." Next time the same words do it with no model at all, if they asked for just that task: not words that asked for more ("night light and open Gmail"), point back at an earlier turn ("turn it on"), don't say the task itself ("switch on", "do what he asked"), or came after she read a page or a message; the planner can still start it by name. When a task has things that change, like who a mail is to and what it says, those become slots, kept without the values, and the planner fills them from your new words in its one call, put its own way if need be: the procedure then types them in itself. Switches are kept with the state they were set to, so a switch that's already on is left on, and typing goes in at the cursor, adding to what's in the box. A task about whichever one is newest ("the latest mail", "my new mail", "the one that just came in") or what's on the screen isn't learned, and a mail row, a file, a list item your words didn't name, or a control with a twin by the same name, is kept to be found by sight, never by what it said this time. If a step stops working (an app moved its button), she works that bit out again from where it stopped, with a screenshot, and keeps the mended version; after three failures in a row she puts it away and works it out afresh next time. "Forget what you just learned" takes a new one back.

Limits: screenshots go to the model only for these asks, never otherwise, and are never kept. Her popup is left out of them. A first look at a window the task doesn't name sends only its title, so your bank isn't read out to the model when you ask for night light. Without her name she asks "Should I look at your screen for that?" first, unless she looked in the last minute; a task heard less than 90% surely is asked about too, and she only learns from tasks you asked for by name. Send, delete, pay, post, comment, reply and the like wait for your yes to her own question, with what it would send read back in full (what she typed, what a web address fills in, like a Gmail compose link's to, subject and body, and for a send what's in the window itself, like a new mail a link opened already filled in) and every address it goes to spelled out. A mail goes only to an address you said, now or a turn or two before, or one she remembers, unless you asked her to reply, and a send whose window she can't read is left to you. One yes is for one press: OK, Enter or Y on a "Delete these items?" box asks again, and so does Enter after typing on any page, whether or not she can read which site it is. She leaves passwords, codes, card numbers, sign-in and payment pages to you, never types or opens an address, link or number you didn't say, opens a site you didn't name only after asking, doesn't drive chat apps or chat sites (WhatsApp and Telegram have their own messaging), including one installed from its site as an app, only clicks in the window she's working in, and never clicks or types in command windows, the Run box or Start. "Stop", her name or right Alt stops a task part way, and so does "stop" from your phone, and the rest of what you asked for with it. Untick Let her see the screen in Settings to turn it off.

### Voice

Settings > Voice picks her voice from six Fish voices that speak well on the free model: Hannah (the default, friendly and clear), Sarah, Laura, Miku (an Indian accent), Assistant and Ethan. Try it plays a line. To use any other voice, paste its link from fish.audio there.

To sound natural, her lines are plain, without the acted `[sighing]` and `[chuckling]` tags, and her usual replies are made once in Fish's steadiest mode and kept. New sentences stream in its quicker mode, which starts talking in about a second (1.0 to 1.1 s at the median here, about 1.7 s at p90), where the steady one took 4. If Fish hasn't started within about 5 seconds, she says the line in her voice on this PC, or Windows' own if that isn't there.

**Her voice on this PC.** Fish's free model is free only until 30 November 2026. "Jev on this PC" in Settings > Voice is Kyutai's Pocket TTS (code MIT, weights CC-BY 4.0), run by the sherpa-onnx she already uses for speech-to-text, in an Indian English voice from the VCTK recordings (speakers p248 and p251, CC-BY 4.0). Nothing leaves the PC, not even the words. Here it starts in about 0.5 to 0.8 s and makes speech three times faster than real time on 2 cores. It takes about 600 MB while loaded, so it loads when first needed (0.7 s) and is let go after 5 minutes unused (`pocket.py`). From 1 December a Fish voice turns into this one by itself. It's a 98 MB download (`sherpa-onnx-pocket-tts-int8-2026-01-26` from sherpa-onnx's releases) plus two short voice clips, in the models folder.

**Faster answers.** The answer model's reply now streams. A plain answer (nothing to do, only something to say) is said a sentence at a time while the rest is still coming, each sentence's voice made while the one before plays, so there are no gaps. Anything with steps, anything without her name, and a task still waits for the whole plan, so every check sees it first. If she's still thinking 0.9 s in, about 1.2 s after you stopped, she says a cached "On it." or "Let me check.": a natural spoken filler makes a wait feel shorter, where a beep doesn't (arXiv 2507.22352). A second request goes out only if the first hasn't started writing, which spends less of the free models' limits. In a test of 34 real requests on 7 October, "Tokyo." for "what's the capital of Japan?" started 1.7 s after the request. Turning Ling's thinking off was tried and left off: no quicker, and it made more mistakes.

### Listening

The mic hands over 32 ms at a time, and each piece is worked on as it comes:

1. Silero VAD hears where speech starts and where it pauses.
2. At each pause (0.2 s of quiet), Smart Turn listens to the whole of what you've said so far and gives the chance you've finished. It hears the sound itself: the pitch falling at the end of a sentence, or staying up mid-thought, the way a person does.
   - Over 50%: the turn ends there and then.
   - 15 to 50%: after 0.5 s of quiet.
   - Under 15%: she waits for more, up to 1.2 s.
   - Under a second of speech, like a bare "Hey Jev", always gets the 0.5 s, so a breath after her name doesn't split it.
- A turn that's only "Hello", "Hey" or "Hi" so far waits the full 1.2 s: ending at half a second cut "Hello [breath] Jev" off before her name, every time one evening. With Nemotron a bare "Hello Jev" is answered about 0.6 s later because of it. Parakeet and Whisper only write once you stop, so a short turn is written at that pause instead, and only a bare greeting waits.
- A phrase that stops on "open", "search", "type" and the like ("Open [pause] recycle bin") waits up to 1.8 s for the rest and joins it on, like one that stops on "and" (`DANGLING` in `siri.py`).
3. Parakeet writes the words, in about 0.2 s, and she acts on them. Her name at the start of a longer phrase brings the popup up while you're still talking.
4. Every 45 seconds a moment of quiet goes through Parakeet and Smart Turn, so Windows keeps them in memory. With little memory free, it had moved them out, and the first phrases of a test then took 3 to 9 seconds.

From the end of a command to its words took about 0.65 s in `checks/listen.py` on a quiet machine, against 0.88 s before, when half a second of quiet was the only sign you'd finished. With the PC busy it's more like 1 to 2 s. A pause to think, as in "open Gmail in my Work profile and... set the volume to thirty", stays one request. Smart Turn only runs at pauses, and took 64 to 367 ms a call on this PC under load. `checks/listen.py` passes 12 of 12 with both Nemotron and Parakeet.

Settings > Speech to text also has Nemotron ASR Streaming, which writes the words while you talk, about half a second at a time, and shows them in the popup. On 36 test lines in Windows' two voices it got fewer words wrong than Parakeet, 3.5% against 4.8%, but in Hari's own voice it kept losing her name: "Hey Jev" and "Hello Jev" came out as "Hello", 3 of 7 calls one evening. With Nemotron, a "Hello", "Hey" or "Hi" with nothing else now gets the chime, and for 8 seconds what you say next counts without her name, the way it does after she answers. Parakeet's bare greetings were nearly all room talk, so it only does that with Nemotron. The last 10 of those greetings are kept as clips in `%LOCALAPPDATA%\Hey Jev\Logs\missed`, to try fixes on a real voice (`MISSED_KEEP` in `siri.py`). Delete the folder any time. It's there to try, not the default.

Nemotron also costs more CPU while anyone in the room talks: about 2.3 cores at 2 threads (`STREAM_THREADS` in `speech.py`), 4.5 at 3, where the work itself is a third of a core. sherpa-onnx's onnxruntime keeps its helper threads spinning between pieces and has no setting to stop it. 1 thread uses 0.34 cores but takes 120 ms longer once you stop. Parakeet only works once you've finished.

Smart Turn v3.2 is Pipecat's (BSD 2-clause), 8 MB, run by onnxruntime, and downloads once. Nemotron ASR Streaming 0.6B is NVIDIA's (NVIDIA Open Model License), 460 MB, downloaded only if you pick it.

### Ideas from Alfred computer-use

Hey Jev borrows the best applicable ideas from [zisshh/computer-use](https://github.com/zisshh/computer-use) (MIT), reimplemented for Windows rather than copying its Mac actions:

- **Call-aware:** while WhatsApp, Teams, Zoom, Discord or a browser has the mic for a call, unnamed speech is held back. Say **Jev** or **Jarvis** and she still acts. Windows' microphone privacy registry is checked in about 1 ms and cached for 2 seconds (`winplatform.call_apps`).
- **The app owns the next sentence:** after opening YouTube, "search for Sam Sulek" searches YouTube, not Google. The app asked for wins for 10 seconds while its window comes forward (`FOCUS`).
- **Local page choices where reliable:** after a search she can play the first through fifth ordinary YouTube result from the result list she fetched herself, with no screenshot or answer-model call.
- **Local compounds:** "open Notepad and type hello", "new tab and open YouTube", and "type hello and press Enter" become fixed steps on the PC (in a chat app she won't press Enter, since that would send). A request to compose a mail, poem or message, or to fill something in like today's date, still goes to the answer model. Unnamed typing first goes through the is-it-for-her decision.
- **Accent slips:** the measured nonsense spellings of "type" from Alfred (`diap`, `dayeb`, and similar) are repaired only in a command-verb position. Real words and the text to type are never changed. This PC's own "prone" for Chrome, "clone the tab" and "new term" are fixed too.

Not adopted: Apple's echo canceller (Windows speech mode already removes this PC's playback); Ghostty/Apple Accessibility code; early execution while a sentence is still being spoken ("open Chrome—no, don't" must not open it); and page clicking by visible text. A read-only Windows UI Automation probe saw Chrome's tabs and toolbar in 69 ms but not the web document, so the existing screenshot vision remains the reliable Windows path. Messaging is deliberately a separate feature because sending to the wrong person needs confirmation and post-send checks.

### Is it for her?

Without her name, what she hears may be you talking to someone, a phone call, a video or the TV. A phone call in the log kept her talking for a minute, each bit of it answered with "Sorry, could you say that again?". Now, without her name:

- "Mm-hmm", "okay", "hello?", "thank you" and the like get nothing, unless it's a yes to her own question.
- Words speech-to-text isn't sure of are let go. It says how sure it is of each word. On 62 clips from this room with Parakeet, clear speech came out above 90%, and mumbling, Telugu and talk across the room at 40 to 60%. Below 55% she lets it go. Nemotron gives the same speech about 8 points less, so its scores are moved up by that. With Windows' voices made faint and noisy, as from across the room, Nemotron mostly wrote nothing at all, where Parakeet made up words.
- She never asks you to say it again or what you meant: she does what you most likely meant, or lets it go. While music or a video plays she only takes commands about it, like pause or louder, unless the mic is in speech mode (Echo cancelling), which takes what the PC plays out of it.
- Answering a chat doesn't keep the conversation open, so one stray answer doesn't lead to the next. The window for carrying on without her name is now 8 seconds. A heads-up only opens it if she asked something.

With her name and words she isn't sure of (under 70%), the model is told they may be wrong, so it asks what you'd like rather than guessing.

### Only your voice

Say "Hey Jev, learn my voice" (or Settings > Your voice > Learn) and read the 10 short sentences that come up in the popup. From then on each turn's speech gets a voice print, 512 numbers from 3D-Speaker's CAM++ model (30 MB, Apache 2.0, run by sherpa-onnx, 15 to 60 ms beside speech-to-text, so commands are no slower), and it's compared with yours. The recordings and prints stay in `%LOCALAPPDATA%\Hey Jev\voice`.

For the first days she only learns: every turn is scored and logged and nobody is turned away. After 30 of your turns with her name she sets the levels from them, so 95% of your named turns pass, and switches on by herself and tells you. Then a turn that isn't your voice is let go without a sound, and someone else's words aren't kept as room talk for the model either. Her picture of your voice grows from turns that were plainly you, up to 40.

- With her name, or straight after a bare "Hey Jev", a lower level; without it a higher one.
- Under a second of speech can't be told apart: on this PC, Windows' voices saying "Hey Jev" matched Hari's own. So a short turn counts with her name or just after she spoke, and a short one said cold, like "pause" across the room, is let go: say "Jev, pause".
- Right Alt and dictation aren't checked: the key press is you.
- A recording of your own voice on a phone or TV will usually pass. Family members of the same sex and accent are the likeliest to slip through.
- "Answer everyone" turns it off, "only answer me" back on. `python checks\voice_id.py` scores your recordings against Windows' voices with the real model.

### The decider

A small sentence model (all-MiniLM-L6-v2, int8, 23 MB, Apache 2.0, about 15 ms on this PC, `decider.py`) gives a chance that words said without her name were said to her, from heads trained on her own past turns (`train_decider.py`: the 487 hand-labelled turns of 4 to 7 October and 1,411 room phrases, in `%LOCALAPPDATA%\Hey Jev\decider`). It answers in the same shape as TypeSafe's Jev and Laya (`/v1/systemone`), so either can be swapped in. Laya itself was looked at first: it needs PyTorch and a 0.6 to 0.8 GB model and took 0.3 to 0.75 s a question on this CPU.

On turns it hadn't seen, below 0.07 it was right 95% of the time: it would have let 63 of 431 unnamed turns go without asking the model, 3 of them meant for her, and stopped 11 of the 44 times she answered room talk. So it starts in shadow mode, asked and logged, changing nothing. With Settings `"decider": "on"` it only lets go what it's sure isn't for her: it never drops a question she'd ask first and never clears the checks for words said without her name. It also picks which of her skills fit a request.

### Without her name

Settings > Without her name > Answer without her name: no "Hey Jev" needed at any time. She listens to everything, and works out whether you were talking to her or to someone else:

1. On the PC: a phrase only counts if it could be a request, with a word that asks for something ("open", "play", "search", "scroll", "volume"), a question ("what", "who", "how"), or the name of an app or site (`ASKING` in `siri.py`). "Are you coming for dinner?", "pass me the water" and "okay, so it's gonna rain later" stop there and never leave the PC. Words speech-to-text isn't sure of and small talk stop there too, as above.
2. Simple commands run straight away: "open Chrome", "volume down", "YouTube", "new tab".
3. The rest goes to the answer model, told it was overheard (`COLD_NOTE`), with up to three things said in the half minute before it that weren't for her, so it can tell a conversation. It answers `{"to": "others"}` for people talking to each other, a phone call, a video or garbled words, and she says nothing. If it says so out loud instead ("That sounded like someone else in the room"), she still says nothing. A question about what "you" did or ate ("why are you late?") is always to a person.

In `checks/open_mic.py`, all 20 phrases were taken right in each of three runs: 10 for her, like "open prone" (Chrome) and "who directed Iron Man", and 10 to someone else, like "I told him to open the door" and "did you watch the match yesterday". Only 3 of the 20 reach the model, though: the rest are settled on the PC, so it mostly tests those checks, not the model's judgement. Before the fixes it was 19, 19 and 18, and what it got wrong changed from run to run.

What could be a request goes to the answer model as text, with what was said just before it. Your voice never leaves the PC.

Speech-to-text gets words wrong, so the answer model is told to work out what you meant from the sound, your apps and what you just did: "open prone" is open Chrome, "clone the tab" is close the tab, "new term" a new tab, and just "YouTube" opens it. The ones heard here most often are fixed on the PC too (`QUICK` in `siri.py`), so they're instant.

The mic now stays on while she thinks and acts, and only pauses while she talks, so she doesn't hear herself. What you say while she's working is heard once she's done, instead of lost, up to 20 seconds of it.

### Memory

She uses [Hermes Agent](https://github.com/NousResearch/hermes-agent)'s own memory code (MIT, copied into `hermes_memory\`): two small files, `USER.md` for who you are and `MEMORY.md` for her own notes, in `%APPDATA%\Hey Jev\memories`. Both go into everything she's asked, so she knows them without looking. She adds to them when you say "remember ...", and Hermes' scanner turns away anything that looks like an attack on her instructions. When they're full she replaces or drops old entries. The Memory tab lists them, with Forget this.

Everything you say to her, and what she did, is kept as well: in `history.db`, which she searches when you ask about the past, and as one Markdown file a day in `memories\days`. Once a day she writes a short summary at the end of the day before's file and saves up to 3 lasting facts from it. Clear conversations in the Memory tab deletes them, her memory stays.

Searching the past works the way Hermes' session_search does, with its query cleaner copied in: every word first, then any of them, then pieces of words ("reerid" finds "careerid.in"), each of the best hits with the turns before and after it, and "after" for the last few days ("what did we decide last week").

Hermes' code is copied into `hermes_memory\` at a pinned commit, listed in `UPSTREAM.json`, with only its imports changed (`_compat.py`): the memory store, threat scanner, skill usage tracking and curator whole, and named pieces of the rest. `python sync_hermes.py <a hermes-agent checkout>` shows what changed upstream and copies it over; then run the tests.

**Fresh start and backups.** `python backup.py` zips her data to `%LOCALAPPDATA%\Hey Jev\Backups` (SQLite files copied with SQLite's own backup, Hermes' way). `--fresh` backs up first, then clears her memory, skills and old chats, keeping settings, contacts, the app list, the Dictionary, keys and models, and she says "Hey, I'm Jev, what can I do for you?" when she next starts. `--restore <zip>` puts a backup back. Quit her first: it won't touch anything while she runs. Her memory was started fresh this way on 7 October 2026.

### Personality

How she talks is in `%APPDATA%\Hey Jev\SOUL.md`, the way Hermes Agent keeps its personality: calm, quick, warm, a little dry, a step ahead, in the spirit of JARVIS in the Iron Man films, written in our own words. She's direct the way Hermes is: a one-line answer for a small ask, a short report when a job's done, and no "Great question". Memory tab > Edit personality opens it. Change it, save, and she talks that way from the next thing you ask. Delete it to go back to the default. Like Hermes, a file that tries to take over her instructions is set aside for the default.

### Skills and learning

Skills are [Hermes Agent](https://github.com/NousResearch/hermes-agent)'s: one `SKILL.md` each, in `%APPDATA%\Hey Jev\skills`, with a name, a description and what she knows about the task. Hermes' checks run on every one she saves, including its threat scanner, and the list of them goes into what she's asked, so she knows what she can do. Hey Jev adds one thing: a skill can carry the phrases that start it and its steps, so a routine you teach her runs straight away, on the PC, with no model in the way:

- "When I say work mode, open Gmail in my Work profile and set the volume to 30." She saves it as a skill.
- "Work mode." Gmail opens in the Work profile and the volume goes to 30, in about a second.

Her learning loop is a light version of Hermes'. After a turn worth learning from (you corrected her, something failed, a task took three steps or more, or every sixth turn), she looks back over the last few turns in the background and keeps what she learned. Room talk she overheard without her name and only answered doesn't count and isn't looked back over, and overheard words only go into her memory when they ask her to remember, forget or note something ("remember that ...", "keep in mind ..."), not when someone says "I remember ...". What she keeps is a fact about you, a skill for a task that took a few goes, or a word speech-to-text got wrong ("no, I said Zostel"), which goes into your Dictionary. A word only goes in if what was written sounds like it and you said the right one after: a look back once made "I'm interpreting" then "it was accept" into interpreting -> Accept, which would have changed every "interpreting" from then on. Most looks back find nothing. The Memory tab lists her skills with what you say for them, and Forget this deletes one. Untick Learn as she goes in Settings to stop it.

With Hermes' parts brought in:

- A correction ("no, I said ...", "that's wrong") is looked at straight away, with what you said as the focus, so she has it right next time. The look back carries Hermes' own rules: one fact in one place, a skill is the procedure and its pitfalls, and never keep "X doesn't work" or a one-off task.
- Skills are written in Hermes' format, the description cut to its 60 letters. The ones that fit a request are written out in full in what she's asked, so the model doesn't spend a round trip loading them.
- Hermes' curator runs once a week, after 2 quiet hours. A skill she wrote herself and hasn't used in 14 days is marked stale; after 30 it's archived to `skills\.archive`, never deleted. Skills you taught her are never touched.
- What a look back or a day's summary changed is kept as it was before. "Forget what you just learned" puts it back.

### The internet

She looks things up with free sources that don't need keys, all at once:

- Wikipedia, for people, films, places and facts
- DuckDuckGo's instant answers
- Google News, for the latest on anything, and the top stories where you are
- any web page, read as plain text, as a browser would fetch it
- Open-Meteo for the weather, for roughly where you are (ipinfo.io works that out from your internet address) or a place you name. "What's the weather like tomorrow?" is answered on the PC without the model, in about a second

There's no general search engine. In October 2026 DuckDuckGo, Yahoo, Mojeek and Startpage asked scripts for a captcha, and Bing answered "Iron Man 2 director" with pages about iron. For what these sources don't have, like a price or a live score, she opens a Google search in your browser and reads it off the screen with vision.

**A question gets an answer, not a page of results.** "When will Gemini 4 be on Antigravity?", "any new AI models launched?", even "Google when is the next India match", are looked up and answered out loud in a few sentences. She opens Google in the browser only when you want to see it: "show me pictures of the Taj Mahal", "google cheap flights to Delhi", "open Google". Turn it off with `"spoken_answers": false` in settings.

What pages say is information for her, never instructions: a page that tries to give her orders is left out, she only opens addresses on the internet, never this PC or your home network, and after reading the web or your messages, anything that changes things needs a yes first.

### Research and notes

An idea from CopilotKit's [OpenDots](https://github.com/CopilotKit/OpenDots), whose agents carry on working while you talk: say "research ..." or "look into ..." and she does it in the background. She starts from a search, reads the two or three best pages and news stories, then tells you in a few sentences once she's free, about 40 seconds later. A longer report with the sources goes into `%APPDATA%\Hey Jev\notes`, one Markdown file each. "Make a note: ..." saves one too, and "open my notes" opens the folder.

### Messaging, with a yes first

She can message on **WhatsApp**, **Telegram**, and other chat apps on this PC, and she never sends anything on her own:

1. "Message Mum on WhatsApp: hi."
2. The chat opens with **hi** typed into the message box. Nothing is sent.
3. She reads it back: *"'hi' to Mum on WhatsApp. Send it?"*
4. You say **yes**, and only then does she press Enter.
5. On WhatsApp she then checks the box emptied, so she says it sent only when it did. Telegram draws its own interface and Windows can read nothing inside it, so there she says she can't read it back and you check the window.

Other ways to say it: "Send hi to Mum on WhatsApp", "On Telegram to bittu send hi", "WhatsApp Mum: running late", "Message Bittu on Signal: hi", "Message Mum on WhatsApp saying I'm running late". With Answer without her name on, a message heard without her name is only typed in once the answer model decides it was for her. Asked to send one later, she says she can only send it now.

You have 90 seconds to say yes ("yes", "yes, send it", "go ahead"); after the first few seconds, start with her name: "Jev, send it". Saying nothing for 90 seconds leaves the message unsent; saying **no** ("not now", "forget it") drops it, and clears the box in the apps she typed into herself. After the first few seconds, asking for something else, like "Jev, stop the music", does that instead, and the message stays typed in, unsent.

**She learns who people are.** The first time you name someone she doesn't know on WhatsApp, she looks for them in your WhatsApp, the way you would:

1. "Message Bunty on WhatsApp: hi" → *"Let me look for Bunty in your WhatsApp."*
2. She types the name into WhatsApp's own search. For each chat it finds (up to three, groups left out), she opens it and reads the number off its contact panel.
3. *"I found Buntyyy in your WhatsApp, number plus 9 1, 9 5 7 3 3, 0 9 1 9 9. Is that them?"* On your phone she shows the number as WhatsApp does.
4. **Yes** saves them and types the message in, then she asks *"Send it?"* as usual; a second yes sends it. **No** moves on to the next one she found, and after the last she asks for the number.

She never presses a key in WhatsApp while looking: the search box is filled through Windows' accessibility interface, and a chat is opened with a click only when that spot is WhatsApp's own window. She reads only the name and number on the contact panel, never the messages, though opening a chat marks it read, as it would for you. Nothing is saved without your yes to her question.

If WhatsApp has nobody by that name, or on Telegram, she asks once:

- "Message Mum on WhatsApp: running late" → *"I couldn't find Mum in your WhatsApp. What's their phone number, with the country code?"*
- "+91 98765 43210" → she saves it, then carries on with the message that was waiting. The reply has to be just the number or username. A number without its country code, like 98765 43210, gets asked for again.
- From then on, "message Mum on WhatsApp: hi" is one step.

You can also teach her outright: "Mum's WhatsApp number is +91 98765 43210", "Save bittu on Telegram as @bittu_01". The **Contacts** tab lists everyone she knows, and you can fix or remove them there. They are kept in `%APPDATA%\Hey Jev\contacts.json`, on this PC only.

**Why a number or username, and not a name search.** On WhatsApp and Telegram she opens the chat with the app's own link (`whatsapp://send`, `tg://resolve`), which puts the text in the box without sending. Searching a chat list for a name she heard could land on the wrong person, and "Mum" and "Mom" are different chats; an explicit number cannot be mistaken. That's why WhatsApp's search only ever finds her a number, which you confirm, and never picks the chat she sends to. It also means she can message someone whose chat isn't open yet.

**Apps with no link of their own.** Signal, Slack, Discord, Teams and the rest get done the long way round, the way you would:

1. "Message Bittu on Signal: hi."
2. She brings Signal up, waits until it really is the window in front, presses its search shortcut, types **Bittu**, presses Enter to open the chat it found, then types **hi**. Nothing is sent.
3. *"'hi' to Bittu on Signal. Send it? I can't read Signal, so check that's the right chat before I do."*
4. Your **yes** is confirming the chat as well as the words, because nothing in those apps can be read back.

That yes is also what teaches her. The shortcut that worked and the name that found the person are saved, so the next one is a single sentence. Her first guess is `Ctrl+F`, or `Ctrl+K` for Slack and Discord; if it's wrong, put her right in one line: **"In Slack you search with control K"**, or "To search in Signal, press control shift F". What she's learned lives in `%APPDATA%\Hey Jev\recipes.json`, and the **Contacts** tab shows which apps she's worked out along with the name she types into each one.

If you say **no** to one of these, she selects the message she typed and deletes it, so nothing is left sitting in someone's chat.

She refuses rather than guesses: an app that isn't on this PC, someone not in the book (or confirmed by you from WhatsApp's own search), an empty message, WhatsApp Desktop not linked to your phone, the app not in front when the yes comes, the app losing focus part-way through typing (she stops there and sends nothing), or the text in the box no longer matching what she read back. A shortcut she doesn't recognise is ignored rather than pressed, including anything odd hand-edited into `recipes.json`.

**Files and photos on WhatsApp.** "Send this to Amma" sends the file or photo you just sent her from your phone, or the files selected in File Explorer in front of you. They wait in WhatsApp's preview, she reads their names back, and they go only after your yes. She never picks a file herself.

**When they reply.** Everyone she sends a message or a file to for you is watched for a reply, day and night, with no time limit:

1. Their reply shows up in Windows' notifications, as it would for you. She knows it's theirs by the chat's own name in WhatsApp, or their number, never a shorter name another chat might share. On Telegram and the apps she types her way into she can't read the chat's name, so there it's by the name you call them, and only if that's what the app shows.
2. On your phone's Telegram, straight away and at any hour: *"Buntyyy 🐼 replied on WhatsApp: 'ok see you at 5'. What should I reply?"* A few messages in a row come as one.
3. On the PC, the same out loud, when Heads-ups is on. From 11 at night to 7 in the morning she keeps quiet on the PC, and says at 7 any your phone didn't get. While she's waiting for your answer to another question, like "Send it?", she holds it back until that's answered, so your yes can't go to the wrong question.
4. "Tell him I'm on my way", "reply ok", "ask her what time": the reply is drafted to the person whose reply you last heard, there or on the phone, and asked about as ever. A yes sends it, and she keeps following that conversation. "Reply to Amma ..." is Amma's, never the last who replied.

After a message goes, she puts back the window you were in. WhatsApp shows no notification for a reply in the chat you're looking at, so with it left in front she'd never hear of one. What they wrote is said and sent to your phone, but her history keeps only that they replied, so it reaches the answer model only when you ask her to read it. Who she's following is kept in `%APPDATA%\Hey Jev\follow_ups.json`, on this PC only.

Not supported on purpose: groups, replying to the last message, voice notes, email, and anything scheduled or automatic. Messaging always needs you there to say yes. She never opens your chats to read them and never screenshots one: a reply's words come from its notification, as you'd see it pop up.

### Installing and updating apps, with a yes first

"Download and install VLC", "install Zoom on this PC", "update Git":

1. She looks it up in **winget**, the package manager built into Windows 11, and in the Microsoft Store if winget doesn't plainly have it (WhatsApp is only in the Store). She never downloads from a website she found by searching, so a fake download page can't fool her.
2. She picks the real app, not a nightly, a plugin or someone else's package with the same word in it: "Telegram" is Telegram Desktop, not telegram-owl; "Python" is the newest Python 3, not Python 2; "Java" is the newest Temurin JDK.
3. She checks whether it's already on this PC, and how much room C: has. She won't start with under 1 GB free, and mentions it under 3 GB.
4. She reads it back: *"VLC media player 3.0.24 from VideoLAN, the 64-bit version for this PC. Install it?"* If it's installed and something newer is out: *"Git 2.53.0.2 is installed, and 2.55.0.5 is out. Update it?"* If it's already the latest, she says so and asks nothing.
5. On **yes** it runs as a background task (in the Tasks tab), so she's free while it downloads. winget picks the installer that fits this PC and checks its SHA-256 before running it. If Windows asks whether to allow the install, say yes there. She tells you when it's done, or why it didn't work.

Only install, download and install, reinstall and update start a lookup straight away. "Get me Spotify" or "download VLC" go through the answer model first, then the same lookup and yes.

She installs exactly the version she read back. One goes at a time. Installs can't be scheduled, and one cut off by Jev closing or a restart waits for "approve task N" rather than running again by itself. Saying no, or nothing for 90 seconds, installs nothing.

### Durable tasks, schedules and commands

The **Tasks** tab is a small durable job queue in `%APPDATA%\Hey Jev\tasks.db`. One worker sleeps when there is nothing due and tells you when each task finishes. Commands, installs and research run one at a time on a thread of their own, so a reminder or PC check that falls due meanwhile isn't held up. Queued work, recurring schedules and reminders survive closing Jev, signing out and restarting Windows. Work that was due while the PC was off runs once when Jev starts; a repeating task then moves to its next future time rather than running every missed occurrence.

Examples:

- "Remind me in 10 minutes to call Mum." — reminders now use the durable queue; short timers remain in memory.
- "Remind me tomorrow at 6 PM to call Mum."
- "Every Monday at 9 AM check my C drive."
- "Every 30 minutes check my network."
- "Research budget laptops tomorrow at 9 AM."
- "Check git status in `C:\path\to\project`.", then "Do that at 6 PM." — the later task copies the already validated command; it is not reinterpreted later.
- "Run the tests in `C:\path\to\project`." Jev uses a project's declared `npm test`, pytest, `dotnet test`, `go test` or `cargo test`; if none is declared, she asks rather than guessing.
- "What tasks are running?", "What is scheduled?", "Cancel my reminders", "Stop reminding me to drink water", "Cancel task 3", "Approve task 3."

Commands run through hidden, non-interactive PowerShell with an existing working folder, at most 120 seconds and 64 KB of stored output. Read-only diagnostics, `git status/diff/log`, and declared test/build/lint/typecheck commands run automatically. Anything that can install, write, delete, move, commit, push, stop a process or change the system waits in **waiting approval**; approve it by voice or in the Tasks tab. Disk formatting, broad forced deletion, registry/security/Defender/firewall changes, restart/shutdown, encoded or nested PowerShell, downloads, credentials/private keys, `.env`, forced Git operations, elevation and similar commands are blocked even if asked. Output is redacted, kept locally and shown in Tasks; Jev only speaks success, exit code or that details are there.

Scheduled work is deliberately limited to reminders, PC lookups, research and guarded commands. It cannot send messages or email, type/click later, buy, pay, publish, delete, change accounts or security, because those need a person present to verify the target and result.

Hermes' cron rules: a command, install or coding job that comes due more than 2 minutes late, as after the PC was off or asleep, doesn't run late by itself, it asks again. A late reminder says when it was for. "Every weekday at 9" works. A repeating check that finds the same as last time stays quiet. And a task's result goes back where it was asked from, your phone included.

**Coding jobs.** "Add a dark mode toggle to the settings page in `C:\path\to\project`." She asks first, and on a yes the OpenCode CLI already on this PC does it in the background, driven over ACP the way Hermes drives a coding agent (`coder.py`), and she tells you when it's done. It's kept on a short leash, because OpenCode lets an agent edit and run commands without asking:

- A setting that outranks the project's own turns every edit and command into a request to her, and turns off web fetching and other folders.
- Only a git project folder, never a system or app-data one, snapshotted first so it can be undone (she says how).
- Edits in the folder go ahead. Commands follow the rules above: blocked ones refused, read-only ones run, anything else asked on your phone with buttons when the job came from there, else refused and listed in her report.
- Only a free model, or it doesn't start.

### Your phone (Telegram)

Talk to her from your phone. Make a bot with [@BotFather](https://core.telegram.org/bots/tutorial#obtain-your-bot-token), paste its token in Keys (it's kept in Credential Manager), press Settings > Phone > Pair, send `/start` to your bot, and type the code it sends back into that box on the PC. That proves you have both. It uses `python-telegram-bot` 22.8, the library Hermes Agent pins (`telegram_bot.py`), and Hermes' pairing rules: 8 letters, kept only hashed, good only while the pairing is open (10 minutes from pressing Pair), locked for an hour after 5 wrong codes. Pressing Pair again starts afresh, so codes strangers asked for can't keep yours out.

- Until you pair, all it answers is `/start`: with a code while pairing is open, else with how to open it. Nothing else runs. After, only your account counts, and you're told once about anyone else who tries.
- It asks Telegram for messages, so nothing on the PC is open to the internet. Only private chats, messages and button taps.
- Anything sent while the PC was off or asleep, or over 2 minutes ago, is dropped, never run late.
- A message goes through the same turn as voice, and her answer comes back to the chat.
- A risky step comes back as a question with Yes and No buttons. Only a tap answers it, within 5 minutes. A typed yes, or a yes said at the PC, doesn't, and a question asked at the PC can't be answered from the phone.
- Voice notes are written out by the speech-to-text on this PC. They do pass through Telegram's servers, as every Telegram voice note does.
- "Send me a screenshot" (or just "screenshot" on the phone) sends a picture of the PC's screen to your chat, 1920 pixels wide, her popup left out. It only ever goes to your own paired account.
- If Telegram can't be reached, it keeps trying. If the token stops working, even while it's listening, the PC says so next to Settings > Phone. A second tap on Yes or No does nothing.
- The token never reaches the log, even inside the library's own errors. Her heads-ups skip the bot's own messages.
- It only works while the PC is on.

### Heads-ups

She reads the Windows notification list on this PC (the same one the notification centre shows), read only. That's how she answers "any new messages?", and how welcome back tells you who messaged while you were away. Messaging apps count: WhatsApp, Messages, Teams, Outlook, Gmail, Telegram, Slack, Discord, Signal, Instagram and Messenger, and your phone's WhatsApp and texts through Phone Link.

Every 20 seconds she checks a few things and speaks up, once each, as soon as she isn't in the middle of something and you aren't mid-sentence (she waits up to 10 seconds). Anything that comes up during a dictation is told once it stops:

- a new message, who it's from and the app, never what it says
- the battery at 20 and 10 percent, when it's not charging
- the C drive under 5 GB
- the CPU or RAM flat out for over a minute
- the internet going, and coming back

From 11 at night to 7 in the morning she stays quiet, except for a nearly flat battery. Settings has Heads-ups and Read my notifications to turn them off.

### The popup

A black pill at the bottom of the screen, Siri style: the Siri wave while she listens and while she talks, moving with the voice, and glowing dots that merge and scatter while she thinks and works, with what she heard or what she's saying next to it. In the seconds after she answers, when you don't need "Hey Jev", the wave dims and a red line counts down. The two animations are the GLSL shaders of the SiriWave React component (`wave` and `fluid-dots`), done in numpy for a small image each frame, about a millisecond. Untick Show the popup in Settings to only see it while dictating.

### Starting with Windows

Settings > Start when I sign in (on here) adds Hey Jev to what Windows starts when you sign in, minimised to the taskbar. Then she welcomes you the way JARVIS welcomes Tony home in Iron Man 2, with the time and the weather: "Welcome home, Hari. It's 2:27 in the afternoon, 33 degrees and mostly clear outside. Anything you'd like me to do?" When you come back to the laptop after it was locked or asleep for a minute or more, it's "Welcome back, Hari.", with only what needs you: who messaged while you were away, the battery if it's under 30 percent and not charging, the C drive if it's nearly full. Just answer, no "Hey Jev" needed. The name and Say hello are in Settings too. It also shows in Task Manager > Startup apps.

### Adding apps

Any app in the Start menu works by its name. Add apps to `apps.json` (or the Apps tab of the window, then restart Jev) when she gets the name wrong, or can't close or switch to it. The app name is its name in the Start menu, for example `"notion": "Notion"`. For apps the transcriber gets wrong, or whose program has a different name, use the longer form:

    "vscode": {"app": "Visual Studio Code", "say": "VS Code", "exe": "Code.exe", "heard_as": ["this code", "v s code"]}

A heard_as spelling is only put right where an app is named: said on its own, or after open, close, switch to and the like, so a message, the text to type or a search keeps its words ("type I'm prone to typos" stays as said).

`exe` is only needed when close or switch to can't find the app's windows by its name.

### Dictation

Say "Hey Jev, transcribe" and the popup shows at the bottom of the screen. Talk as long as you like, then say "Hey Jev, stop transcribing" and the text is pasted where your cursor is (and left on the clipboard). With Answer without her name on, "transcribe this" said without her name first goes through the is-it-for-her decision, like any other request. It's written on your PC, so the audio never leaves it. Every dictation is saved to `%LOCALAPPDATA%\Hey Jev\Logs\Hey Jev dictation.jsonl`. To fix words it gets wrong, open the Dictionary tab: add a word and the ways it gets misheard. It saves to `vocabulary.json`, which is gitignored (`vocabulary.example.json` is the starter list).

## What you need

- Windows 10 or 11
- Python 3.10 or newer (tested on 3.14). If you don't have it: `winget install Python.Python.3.12`, or the installer from [python.org](https://www.python.org/downloads/)
- Two free API keys:
  - OpenCode Zen: [opencode.ai/zen](https://opencode.ai/zen). Sign in and create a key. It's the same key Hermes Agent calls `OPENCODE_ZEN_API_KEY`. No billing needed for the free models.
  - Fish Audio: [fish.audio](https://fish.audio/?fpr=henryk). Create a key on the API keys page. No credit needed for `s2.1-pro-free`.
  - Kilo (optional): [kilo.ai](https://kilo.ai/docs/gateway/authentication). Sign in and copy your API key. Only its `:free` models are used, so nothing is billed.

## Setup

In this folder:

    powershell -ExecutionPolicy Bypass -File setup.ps1

That makes a `.venv` with the packages and puts a "Hey Jev" shortcut in the Start menu and on the Desktop. The shortcut runs the code straight from this folder. Run `setup.ps1` again if you move the folder. (The upstream repo is still the Mac version, so cloning it fresh won't get you this one.)

First launch:

1. The window opens on the Keys tab. Paste your keys and hit Save keys, they're saved in Windows Credential Manager. Change them any time in the same tab.
2. The speech models download one time, about 470 MB (Nemotron is another 460 MB if you pick it), into `%LOCALAPPDATA%\Hey Jev\models`. Set `HEYJEV_MODELS` in `.env` to keep them on another drive (this PC uses `D:\HeyJev\models`).
3. If Windows blocks the mic, turn on Settings > Privacy & security > Microphone > Let desktop apps access your microphone. To use a different mic, pick it in the Settings tab. Automatic skips Stereo Mix, which only hears what the PC plays.

The dot at the top goes green when it's ready. The switch in the top right picks how you talk to it:

- Hold Right Alt: hold right Alt, talk, let go. Jev swallows the key, so the app in front doesn't open its menu.
- Hey Jev: always listening. Say what you want directly when Answer without her name is on, or say "Hey Jev", "Jev" or "Jarvis". A name on its own chimes and arms the next thing you say. "Hello Jev" or "Hi Jarvis" on their own get a hello back. For 8 seconds after she answers ("Still listening" in the window), the next thing you say doesn't need a name: "open YouTube", then "scroll down", then "close it", or "play lofi music", then "louder". With Answer without her name on in Settings, nothing needs it. During a call, Require her name on calls overrides that, so say Jev or Jarvis.

### Echo cancelling

The mic is opened in Windows' speech mode, the one made for voice assistants. Windows takes whatever the PC is playing out of the mic, so a YouTube video or music doesn't drown you out. On this laptop a talking video went from as loud as a voice in the mic to 62 dB below it, and Parakeet heard none of it. Without it, the mic heard the video word for word, which is why she stopped answering once a video played.

If she stops hearing you, untick Echo cancelling in Settings. Then, while something plays, say "Hey Jev" close to the mic, or hold right Alt. The log says which way the mic is open: `[mic: ..., speech mode, so she hears you over what the PC plays]`.

## Using the window

- Closing the window keeps her listening, it stays in the taskbar. Opening the shortcut again brings it back.
- Quit with Ctrl+Q or "Quit Hey Jev" at the bottom of the sidebar.
- Ctrl+T keeps it above other apps (also in Settings), Ctrl+M minimises.

## Models

The answer model in Settings works out what you asked and answers, on OpenCode Zen or Kilo, free only. The default is `space-bunny-free`, which keeps nothing and isn't trained on. This PC uses `kilo/inclusionai/ling-3.0-flash-sante:free`, which is quicker. Check Kilo's data policy for the free model you pick. Refresh checks which free models answer from Hey Jev right now and lists only those. Picking one checks it straight away.

Free models differ on privacy: some keep nothing, others may use what you send to improve the model. [opencode.ai/docs/zen](https://opencode.ai/docs/zen/) lists which is which.

## Running from the terminal

Useful for seeing what she heard, planned and did:

    .venv\Scripts\python.exe siri.py                                     # hold right Alt mode, the log prints here
    .venv\Scripts\python.exe siri.py --wake                              # Hey Jev mode, always listening
    .venv\Scripts\python.exe siri.py --text "open notepad and write hello"   # one turn, no mic
    .venv\Scripts\python.exe siri.py --ui                                # same as the shortcut
    .venv\Scripts\python.exe checks\listen.py                            # checks the listening, no mic or keys needed
    .venv\Scripts\python.exe checks\listen.py parakeet                   # the same with another speech-to-text
    .venv\Scripts\python.exe checks\open_mic.py                          # without her name: hers, or someone else's?

`checks/listen.py` has Windows' own voice say "Hey Jev, open Notepad", a follow-up, a bare "Hey Jev", "Hello Jev", a pause after her name, a pause to think mid-sentence and a few things that aren't for her. It runs them through the real voice detector, speech-to-text and Smart Turn, 32 ms at a time, and checks where each turn ended, what it was taken as and what the quick path would do.

Tests: the unit tests live in `tests\`. Run them with `.venv\Scripts\python.exe -m unittest discover -s tests -t .`, never a bare `python -m unittest` from the repo root. `tests\support.py` points her app data at a temp folder and blocks anything that would act on the PC or go online, and a test run that reaches her real `%APPDATA%\Hey Jev` or `%LOCALAPPDATA%\Hey Jev` stops with an error instead of writing there. The hand checks in `checks\` use the real models and are run by hand, not by unittest.

Keys can also go in a `.env` file in this folder (`OPENCODE_ZEN_API_KEY`, `FISH_AUDIO_API_KEY`). A key in `.env` takes priority over the one saved in Credential Manager. `.env` can also set `OPENCODE_MODEL`, free models only.

## How it works

1. The mic hands over 32 ms at a time. While you hold right Alt it goes straight into speech-to-text, so the words are ready a moment after you let go. In Hey Jev mode the mic stays open, and Silero VAD hears where speech starts and pauses. The mic runs in Windows' speech mode (WASAPI with the speech category), so what the PC plays is taken out first.
2. Smart Turn decides at each pause whether you've finished, and Parakeet writes the words (see Listening above). The words are ready about 0.65 seconds after you stop talking on a quiet machine, 1 to 2 seconds when the PC is busy.
3. A phrase is for her if her name is in it, written however speech-to-text heard it: Jev, Jarvis, Jeff, Jet, Jeth, Joe, Jim, Ju, or run together as "Heijev" or "HF" (`STRONG` and `WEAK` in `siri.py`). Real names like Jeff only count after "hey", "hello", "ok" and so on, or at the start the way you'd call someone ("Jeff, open Chrome", or "Jeff open Chrome", as Nemotron often writes it), so "I told Jeff about it" doesn't wake her. A phrase also counts if it comes right after a bare "Hey Jev", or in the follow-up window. With Answer without her name on, anything else that could be a request goes to the answer model to decide (see Without her name above).
4. Routines you taught her come first, then simple commands, which match a list of patterns (`QUICK` in `siri.py`). They run straight away, with a scripted reply that was made once and kept in `cache\tts`.
5. Everything else goes to the answer model with her personality, her memory, the list of her skills, the time, the app in front, what's playing, running timers, your browser profiles and the last half hour of turns, so "close it" and "and Australia?" make sense. It answers with JSON: the steps to take, from a fixed list (open, close, website, youtube, google, media, volume, scroll, keys, type, timer, memory, skill, research, note, screen and so on), and what to say. It can look things up first, on the PC, on the internet or in past conversations, and gets the results back before it answers, up to 4 times. It's told speech-to-text mishears words, so it searches for what you meant ("Avengers Doomshare Tyler" is the Doomsday trailer). The free model's queue makes the same question take anywhere from 2 to 16 seconds, so if it's slow the question goes out again after 2.5 and 5 seconds, and the first answer back is used. An empty answer is asked again once within that time, and after 12 seconds she says she's slow rather than going quiet.
6. The steps run while she says her line, through Windows: the Start menu to launch apps, window messages to close, minimise and focus them, the volume mixer, Windows' media controls for whatever is playing, YouTube's search page for the top video, the mouse wheel for scrolling, the keyboard for shortcuts, and the clipboard for typing. Closing or minimising an app, sending, installing and saving something are said once they're done, and only if they worked.
7. When she wasn't called by name first (a follow-up, or the name in the middle of a sentence), she lets small talk, words she isn't sure of and anything unclear go (see Is it for her? above), and the model may decide it wasn't for her, like a video saying "thanks for watching". Typing, shortcuts, closing, minimising, lock, sleep and looking at the screen then only go ahead when the words ask for them. Closing an app needs the words to start with "close" or name the app, since a model once planned closing Kiro for "Yeah, do you open close?". Otherwise she asks first, "Should I close Google Chrome?", and a yes or no in the next few seconds decides.
8. Smart Turn hears most pauses mid-sentence for what they are. If a turn still ends on a word like "to" or "and", as in "so at the end of the day we need to", she waits 1.8 seconds more for the rest.

## Safety

She does what she hears, and a video or someone in the room can say "Hey Jev" too. So there are limits whoever asks:

- Typing, key presses and clicks never go to command windows (Command Prompt, PowerShell, Windows Terminal), and never use the Windows key. Enter is never pressed in a chat app (WhatsApp, Telegram, Signal, Slack, Discord, Teams and the like), so a message only goes out after it's read back and you say yes. Shortcuts that send or delete (Ctrl+Enter, Alt+S, Shift+Delete) are never pressed from a plan unless you said the keys yourself ("press control enter"): "send it" with a mail open is a task on the screen, read back and asked about first. Terminal work instead goes through the durable hidden command runner, where code classifies the command as automatic, approval-required or blocked before it starts.
- Websites are web addresses only, never a file or a program. Apps are opened by their plain name only, never a path.
- What web pages and messages say is information, never instructions. Pages, messages, search results and headlines that try to give her orders are left out, she only reads addresses on the internet, and after reading the web or your messages anything that changes things needs a yes first: typing, shortcuts, closing apps, lock and sleep, and also saving or forgetting a contact (she reads the number back), her memory, skills, schedules, dark mode, cancelling timers and approving a task. Opening, playing and looking things up still go ahead. With a shutdown or restart in the plan, that is what she asks about.
- Messages are never sent without a spoken yes, never to someone she had to guess, and never to a group. The recipient comes from your contacts book as a number or username, so a misheard name can't reach the wrong person, and she won't send at all if the app isn't in front or the words in the box changed.
- Her memory and skills go through Hermes Agent's threat scanner before they're saved, and her personality before it's used. Routines can only hold steps that act, the same list the model plans from, never a command line.

## What it costs

$0. The answer model is a free Kilo or OpenCode Zen model, the voice is Fish's free model, the YouTube search is the public results page, the web sources (Wikipedia, DuckDuckGo, Google News, Open-Meteo, ipinfo.io) are free without keys, speech-to-text runs on your PC, and the task queue/scheduler/command runner use Python and Windows only.

## Troubleshooting

- Holding right Alt does nothing. Check the dot is green. Windows doesn't pass keys to Jev while an app running as administrator is in front.
- "401 Unauthorized" in the window. One of your keys is wrong or expired. Re-paste it in the Keys tab. If you also have a `.env`, check the key there, because it wins over Credential Manager.
- She hears nothing. Pick your mic in Settings, or Automatic. Stereo Mix only records what the PC plays, never you.
- She only chimes when you say "Hello Jev" with Nemotron picked. It heard "Hello" without her name, so she listens for what you want instead of answering. Say it, or pick Parakeet in Settings > Speech to text, which hears her name as Joe, Jim or Jill and counts those.
- She answers to room conversation during a WhatsApp, Teams, Zoom, Discord or browser call. Keep Require her name on calls ticked in Settings; say "Jev" or "Jarvis" during the call. The log prints `[call: ...]` when Windows says one starts.
- She doesn't answer an unnamed request. Check Settings > Without her name > Answer without her name. During a call, her name is still required.
- She answers late, or not at all for a while. The log line after each phrase ends with the time and, if she was behind the mic, `Xs behind`. More than 2 seconds behind, apart from what was said while she was working on a turn, or 20 seconds behind in all (`CATCH_UP`), and she skips to now, logged as `(listening was ... behind, skipped ...)`. That means the CPU was too busy.
- She answers before you've finished, or waits a beat too long. Smart Turn's lines are `FINISHED`, `MAYBE`, `SETTLE` and `LONGEST` in `speech.Listener`. The log's `stt` time after each phrase is how long the words took once you stopped.
- She misses "Hey Jev" while a video is playing. Check the log says `speech mode` on the `[mic: ...]` line, and that Echo cancelling is ticked in Settings. Sound from another device, like a TV or a phone, isn't taken out, since Windows only knows what this PC plays. Pause it, or hold right Alt.
- She stopped hearing you after an update. Untick Echo cancelling in Settings, that opens the mic the old way.
- A video opens but doesn't play. Chrome waits until its window is on screen. She brings it to the front, but if Chrome was still starting it can stay behind: click it.
- She misses "Hey Jev" in a quiet room. The log shows phrases that start with "hey" but didn't count, like `(not for me: 'Hey Jed, open Spotify')`. Add the word she heard to `WEAK` in `siri.py`. "Hey Jet" and "Hey Jeth", missed this way before, now count.
- She says her brain isn't answering. The free answer model stopped working from outside OpenCode. Open Settings, hit Refresh and pick another. Simple commands still work meanwhile.
- She types or scrolls in the wrong place. Steps go to the app in front, so click the window you mean first, or name it: "open Notepad and write...".
- The app won't open again. It's still running with the window closed, the shortcut brings it back, or quit it with Ctrl+Q.
- Checking what happened. Every phrase it heard, the plan and what she said is logged to `%LOCALAPPDATA%\Hey Jev\Logs\Hey Jev.log`.

## Files

- `siri.py` all the logic: her name, the quick commands, the planner, the steps, Fish, the turn loop and the welcome
- `speech.py` the ears: model downloads, Silero VAD, Smart Turn, where turns end, Parakeet (or Nemotron streaming, or Whisper), and the follow-up window. `checks/listen.py` checks them, `checks/open_mic.py` what she takes as hers without her name
- `winplatform.py` the Windows side: apps, windows, volume, media, scrolling, dark mode, clipboard, the right Alt hook, the lock screen and starting with Windows
- `opencode.py` OpenCode Zen and Kilo Gateway, free models only
- `tasks.py` the SQLite task queue, local schedule parser, command policy, hidden PowerShell runner, timeout, output cap and redaction
- `messaging.py` WhatsApp and Telegram: the contacts book, the app links that type without sending, and the checks before and after a yes
- `hermes_memory\` Hermes Agent's code (MIT) at the commit in `UPSTREAM.json`: its memory store, threat scanner, skill usage and curator whole, and pieces in `hermes_bits.py`, `gateway_bits.py` and `acp_bits.py`, with `_compat.py` standing in for the rest of Hermes; `skills.py`, its skills cut down to what Hey Jev needs, with routines added. `sync_hermes.py` brings them up to a newer Hermes. `history.py` the conversations and day files
- `voiceid.py` only your voice, `decider.py` and `train_decider.py` the decider, `pocket.py` her voice on this PC
- `telegram_bot.py` your phone, `coder.py` coding jobs through OpenCode, `backup.py` backups and a fresh start
- `web.py` the internet: Wikipedia, DuckDuckGo's instant answers, Google News, reading a page, the weather
- `watch.py` heads-ups: the Windows notification list, battery, drive, CPU, RAM and the internet
- `sysinfo.py` what the PC is doing, read only: drives, battery, CPU, RAM, network, uptime
- `apps.json` apps she should know by another name, or by their program
- `dictation.py` dictation, `vocabulary.example.json` its word fixes (copy to `vocabulary.json`), `bubble.py` the popup
- `agent.py` tasks in apps: the live loop, the gate every step passes, the yes for a send, and procedures she learned by doing them, replayed, mended and put away. `vision.py` the screenshots it sends, made small, with no image library
- `assistant_ui.py` the window: status, mode switch, and the Home, Tasks, Contacts, Dictionary, Apps, Dictation history, Memory, Privacy, Settings and Keys tabs
- `secrets_store.py` Credential Manager read / write, `settings.py` window and model settings in `%APPDATA%\Hey Jev`
- `app.py` and `setup.ps1` the shortcut's entry point and the setup script
- `assets\` the app icon

## Change the voice

Settings > Voice, see Voice above. For any voice on [fish.audio](https://fish.audio/?fpr=henryk), open it and paste its page link into the voice box. Her usual replies are made again in the new voice in the background.
