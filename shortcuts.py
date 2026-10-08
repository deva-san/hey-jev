"""Keyboard shortcuts she presses straight away, without asking the answer model: Windows 11's own, and those of the
apps people use most (Chrome and Edge, File Explorer, YouTube, Word, VS Code, Notepad, and text anywhere).

Each is (keys, where it works, kind, how people say it). She picks the one for the app in front: "new tab" is Ctrl+T
in Chrome, "zoom in" is Ctrl+Plus there but Windows' Magnifier on the desktop. Only the whole phrase counts (after
fast_intent.clean_text has taken "can you", "please" and the like off); anything else goes to the model as before.

How it's said is written plainly: words, [optional words], (one | or another), and ~ for "the", "this", "that",
"it", "my", "a" or nothing.

kind: "safe" only shows, moves or opens things, fine whoever asked; "edit" changes what's in the app (paste, undo,
bold), so heard without her name the model decides it was for her first. Nothing that deletes for good, signs out or
runs things is here (Shift+Delete, Ctrl+Alt+Delete, Win+R, Win+X's letters): the Windows key is only ever pressed
for one of these, never for a plan the model made (siri.press_keys).
"""
import re

SOURCES = (
    "https://support.microsoft.com/en-us/windows/keyboard-shortcuts-in-windows-dcc61a57-8ff0-cffe-9796-cb9706c75eec",
    "https://support.microsoft.com/en-us/windows/windows-keyboard-shortcuts-for-accessibility-021bcb62-45c8-e4ef-1e4f-41b8c1fc87fd",
    "https://support.google.com/chrome/answer/157179",
    "https://support.microsoft.com/en-us/microsoft-edge/keyboard-shortcuts-in-microsoft-edge-50d3edab-30d9-c7e4-21ce-37fe2713cfad",
    "https://support.google.com/youtube/answer/7631406",
    "https://support.microsoft.com/en-us/office/keyboard-shortcuts-in-word-95ef89dd-7142-4b50-afb2-f762f663ceb2",
    "https://code.visualstudio.com/shortcuts/keyboard-shortcuts-windows.pdf",
)

# where a shortcut works, by the program in front
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe"}
PROGRAMS = {"explorer": {"explorer.exe"}, "word": {"winword.exe"}, "vscode": {"code.exe"}, "notepad": {"notepad.exe"}}

# (keys, scope, kind, [how it's said])
TABLE = [
    # ------------------------------------------------------------------ Windows, anywhere
    ("win+d", "windows", "safe", ["(show | go to | take me to) ~ desktop", "(minimise | minimize) (all | everything) [windows]",
                                  "hide (all | everything) [windows]", "show desktop"]),
    ("win+shift+m", "windows", "safe", ["(restore | bring back | (unminimise | unminimize)) (all | everything) [windows]",
                                        "bring back (all | everything) [windows]"]),
    ("win+home", "windows", "safe", ["(minimise | minimize) [all] [the] other windows",
                                     "(minimise | minimize) everything (else | but this) [one | window]"]),
    ("win+e", "windows", "safe", ["open [a] [new] [file] explorer [window]", "open my (files | computer)",
                                  "open this pc"]),
    ("win+i", "windows", "safe", ["open ~ [windows] settings", "[windows] settings"]),
    ("win+a", "windows", "safe", ["(open | show) ~ quick settings", "quick settings", "action (center | centre)"]),
    ("win+n", "windows", "safe", ["(open | show) ~ notifications [center | centre | panel]",
                                  "(open | show) ~ notification (center | centre | panel)", "(open | show) ~ calendar"]),
    ("win+v", "windows", "safe", ["(open | show) ~ clipboard [history]", "clipboard history"]),
    ("win+.", "windows", "safe", ["(open | show) ~ (emoji | emojis) [panel | picker | keyboard]",
                                  "emoji (panel | picker)", "insert [an] emoji"]),
    ("win+shift+s", "windows", "safe", ["[take | grab] [a] (screenshot | screen shot | snip) of [a] [part of] ~ "
                                        "(screen | region | area | part)", "snip [a | the] (region | area | part)",
                                        "select [an | a] (area | region) to (capture | screenshot)"]),
    ("win+print_screen", "windows", "safe", ["[take | save] [a] full (screenshot | screen shot | screen capture)",
                                             "save [a] (screenshot | screen shot) [to [my] pictures]",
                                             "(screenshot | screen shot) [the] (whole | full | entire) screen"]),
    ("win+tab", "windows", "safe", ["(open | show) ~ task view", "show [all] [my] [open] windows", "task view"]),
    ("alt+tab", "windows", "safe", ["switch (window | windows | app | apps)",
                                    "switch to [the] (last | previous | other) (window | app)",
                                    "[go] back to [the] (last | previous | other) (window | app)", "next window"]),
    ("win+ctrl+d", "windows", "safe", ["(add | create | make | open) [a] [new] virtual desktop", "new virtual desktop"]),
    ("win+ctrl+right", "windows", "safe", ["[switch to | go to | move to] [the] (next | right) [virtual] desktop"]),
    ("win+ctrl+left", "windows", "safe", ["[switch to | go to | move to] [the] (previous | left) [virtual] desktop"]),
    ("win+ctrl+f4", "windows", "safe", ["close ~ [current] virtual desktop"]),
    ("win+left", "windows", "safe", ["snap ~ [window | app] [to the] left", "(move | put) ~ [window | app] "
                                     "(to | on) the left [side | half]"]),
    ("win+right", "windows", "safe", ["snap ~ [window | app] [to the] right", "(move | put) ~ [window | app] "
                                      "(to | on) the right [side | half]"]),
    ("win+up", "windows", "safe", ["make ~ [window | app] (full | bigger | fill the screen)"]),
    ("win+down", "windows", "safe", ["make ~ [window | app] smaller"]),
    ("win+shift+left", "windows", "safe", ["move ~ [window | app] to [the] (other | left | previous) (monitor | screen | display)"]),
    ("win+shift+right", "windows", "safe", ["move ~ [window | app] to [the] (next | right) (monitor | screen | display)"]),
    ("win+z", "windows", "safe", ["(open | show) ~ snap (layout | layouts)", "snap (layout | layouts)"]),
    ("win+w", "windows", "safe", ["(open | show) ~ (widget | widgets) [board | panel]", "widgets"]),
    ("win+s", "windows", "safe", ["(open | show) ~ [windows] search", "search windows", "search (the | my) pc"]),
    ("win", "windows", "safe", ["(open | show) ~ start [menu]", "start menu"]),
    ("win+b", "windows", "safe", ["(open | show | go to) ~ [system] tray", "show hidden icons"]),
    ("win+t", "windows", "safe", ["(go to | focus) ~ taskbar"]),
    ("win+k", "windows", "safe", ["[open] (cast | casting) [panel | menu]", "connect to [a] [wireless] display",
                                  "cast [my | the] screen"]),
    ("win+p", "windows", "safe", ["(open | show) ~ (project | projection) [settings | menu | options]",
                                  "(project | duplicate | extend) [my | the] (screen | display)"]),
    ("win+h", "windows", "safe", ["[start | open] [windows] voice typing"]),
    ("win+g", "windows", "safe", ["(open | show) ~ [xbox] game bar", "game bar"]),
    ("win+alt+r", "windows", "safe", ["(start | stop) [screen | game] recording [the screen | the game]",
                                      "record [the | my] (screen | game | gameplay)"]),
    ("win+=", "windows", "safe", ["[open | turn on | start] ~ magnifier", "magnify [the screen]"]),
    ("win+esc", "windows", "safe", ["(close | turn off | stop | exit) [the] magnifier"]),
    ("win+ctrl+enter", "windows", "safe", ["(turn on | turn off | start | stop | toggle) [the] narrator", "narrator"]),
    ("win+ctrl+o", "windows", "safe", ["(open | show) ~ (on screen | onscreen) keyboard", "(on screen | onscreen) keyboard"]),
    ("win+u", "windows", "safe", ["[open] ~ accessibility settings", "[open] ease of access"]),
    ("win+ctrl+c", "windows", "safe", ["(turn on | turn off | toggle) [the] (color | colour) (filter | filters)"]),
    ("win+pause", "windows", "safe", ["(open | show) ~ (about | system info | system information | pc info) [page]",
                                      "about (this | my) pc"]),
    ("win+alt+d", "windows", "safe", ["(show | open) ~ (date and time | clock) [panel]"]),
    ("win+ctrl+shift+b", "windows", "edit", ["(reset | restart) [the] (graphics | display | video) driver",
                                             "fix [the] black screen"]),
    ("ctrl+shift+esc", "windows", "safe", ["[open] ~ task manager"]),
    # ------------------------------------------------------------------ text, in most apps
    ("ctrl+a", "text", "safe", ["select (all | everything) [the text]"]),
    ("ctrl+c", "text", "safe", ["copy [~ (selected text | text | that | this | it | selection)]"]),
    ("ctrl+x", "text", "edit", ["cut [~ (selected text | text | that | this | it | selection)]"]),
    ("ctrl+v", "text", "edit", ["paste [~ (text | that | this | it)] [here]"]),
    ("ctrl+shift+v", "text", "edit", ["paste [as] (plain | unformatted) text", "paste without [the] formatting"]),
    ("ctrl+z", "text", "edit", ["undo [that | it | the last (thing | change)]"]),
    ("ctrl+y", "text", "edit", ["redo [that | it]"]),
    ("ctrl+s", "text", "edit", ["save [~ (file | document | doc | changes | work) | this | it]"]),
    ("ctrl+f", "text", "safe", ["[open] find [on ~ page | in ~ (page | file | document)]",
                                "search (this | the) (page | file | document)"]),
    ("ctrl+p", "text", "safe", ["print [~ (page | document | file) | this | it]", "open [the] print (dialog | menu)"]),
    ("ctrl+b", "text", "edit", ["make ~ [text | selection] bold", "bold [~ (text | selection) | that | this | it]"]),
    ("ctrl+i", "text", "edit", ["make ~ [text | selection] italic", "(italic | italicise | italicize) [~ text | that | this | it]"]),
    ("ctrl+u", "text", "edit", ["underline [~ text | that | this | it]"]),
    ("ctrl+backspace", "text", "edit", ["delete [the] (last | previous) word", "delete (a | one) word"]),
    ("ctrl+home", "text", "safe", ["go to [the] (top | start | beginning) [of [the] (page | document | file)]"]),
    ("ctrl+end", "text", "safe", ["go to [the] (bottom | end) [of [the] (page | document | file)]"]),
    # ------------------------------------------------------------------ Chrome, Edge and the like
    ("ctrl+t", "browser", "safe", ["[open] [a] [another] new tab"]),
    ("ctrl+n", "browser", "safe", ["[open] [a] new [browser] window"]),
    ("ctrl+shift+n", "browser", "safe", ["[open] [a | an] [new] (incognito | private | inprivate | in private) "
                                         "[window | tab | mode]", "go incognito"]),
    ("ctrl+w", "browser", "safe", ["close ~ [current] tab"]),
    ("ctrl+shift+t", "browser", "safe", ["(reopen | restore | bring back) ~ [last] [closed] tab",
                                         "open [the] [last] closed tab", "undo close tab"]),
    ("ctrl+tab", "browser", "safe", ["(next | switch) tab", "(go to | switch to) [the] next tab"]),
    ("ctrl+shift+tab", "browser", "safe", ["previous tab", "(go to | switch to) [the] previous tab"]),
    ("ctrl+1", "browser", "safe", ["(go to | switch to) [the] first tab", "first tab"]),
    ("ctrl+9", "browser", "safe", ["(go to | switch to) [the] [very] last tab"]),
    ("alt+left", "browser", "safe", ["go back [a page]", "(previous | last) page", "back"]),
    ("alt+right", "browser", "safe", ["go forward [a page]", "next page", "forward"]),
    ("f5", "browser", "safe", ["(refresh | reload) [~ (page | tab | site | website)]"]),
    ("ctrl+shift+r", "browser", "safe", ["hard (refresh | reload) [~ (page | tab)]",
                                         "(refresh | reload) without [the] cache"]),
    ("ctrl+d", "browser", "safe", ["bookmark [~ (page | tab | site) | this | it]",
                                   "add (this | the) [page] to [my] (bookmarks | favorites | favourites)",
                                   "(save | add) ~ [page] [as a] bookmark"]),
    ("ctrl+shift+b", "browser", "safe", ["(show | hide | toggle) ~ (bookmark | bookmarks) bar"]),
    ("ctrl+h", "browser", "safe", ["(open | show) ~ [browser | browsing] history", "[browser | browsing] history"]),
    ("ctrl+j", "browser", "safe", ["(open | show) ~ downloads [page]", "[my] downloads page"]),
    ("ctrl+l", "browser", "safe", ["(go to | focus | select) ~ (address | url | search) bar"]),
    ("ctrl+=", "browser", "safe", ["zoom in [on ~ page]", "make ~ [page | text] bigger"]),
    ("ctrl+-", "browser", "safe", ["zoom out [of ~ page]", "make ~ [page | text] smaller"]),
    ("ctrl+0", "browser", "safe", ["(reset | normal | default) zoom", "zoom [to] (100 | a hundred | normal) [percent]",
                                   "reset [the] zoom"]),
    ("f11", "browser", "safe", ["[go | make it | enter | exit | leave] (full screen | fullscreen) [mode]"]),
    ("ctrl+u", "browser", "safe", ["(view | show) ~ [page] source [code]"]),
    ("f12", "browser", "safe", ["(open | show | close) ~ (dev tools | developer tools | devtools | inspector)"]),
    ("shift+esc", "browser", "safe", ["[open] ~ (browser | chrome | edge) task manager"]),
    ("ctrl+shift+delete", "browser", "safe", ["(open | show) ~ clear (browsing data | data | history) [page | dialog | settings]",
                                              "clear browsing data"]),
    ("ctrl+shift+a", "browser", "safe", ["search [my] [open] tabs", "(open | show) tab search"]),
    ("ctrl+shift+o", "browser", "safe", ["(open | show) ~ (bookmark | bookmarks) [manager]"]),
    ("alt+home", "browser", "safe", ["(go to | open) [the] (home page | homepage)"]),
    ("esc", "browser", "safe", ["stop loading [~ page]"]),
    # ------------------------------------------------------------------ YouTube, in the browser
    ("k", "youtube", "safe", ["(pause | play | resume) [~ video | it]"]),
    ("f", "youtube", "safe", ["[go | make it | enter | exit | leave] (full screen | fullscreen) [mode]"]),
    ("m", "youtube", "safe", ["(mute | unmute) [~ video]"]),
    ("j", "youtube", "safe", ["[go | skip] back (10 | ten) seconds", "rewind [(10 | ten) seconds]"]),
    ("l", "youtube", "safe", ["[go | skip] (forward | ahead) (10 | ten) seconds", "fast forward [(10 | ten) seconds]"]),
    ("left", "youtube", "safe", ["[go | skip] back (5 | five) seconds"]),
    ("right", "youtube", "safe", ["[go | skip] (forward | ahead) (5 | five) seconds"]),
    ("shift+n", "youtube", "safe", ["[play] [the] next video", "skip [this | the] video"]),
    ("shift+p", "youtube", "safe", ["[play] [the] previous video"]),
    ("c", "youtube", "safe", ["(turn on | turn off | show | hide | toggle) ~ (captions | subtitles | cc)",
                              "captions", "subtitles"]),
    ("t", "youtube", "safe", ["(theater | theatre | cinema) mode"]),
    ("i", "youtube", "safe", ["[open | turn on | start] (mini player | miniplayer | picture in picture)"]),
    ("shift+.", "youtube", "safe", ["(speed up | faster) [the video]", "increase [the] [playback] speed"]),
    ("shift+,", "youtube", "safe", ["(slow down | slower) [the video]", "decrease [the] [playback] speed"]),
    ("0", "youtube", "safe", ["[go | skip] [back] to the (start | beginning) [of the video]", "restart [the] video",
                              "start [the video] (over | again)"]),
    ("end", "youtube", "safe", ["[go | skip] to the end [of the video]"]),
    # ------------------------------------------------------------------ File Explorer
    ("ctrl+shift+n", "explorer", "edit", ["(make | create) [a] new folder", "new folder"]),
    ("alt+up", "explorer", "safe", ["[go] up [a | one] (level | folder)", "[open] [the] parent folder"]),
    ("alt+left", "explorer", "safe", ["go back", "back", "previous folder"]),
    ("alt+right", "explorer", "safe", ["go forward", "forward"]),
    ("alt+enter", "explorer", "safe", ["(show | open) ~ properties", "properties"]),
    ("alt+p", "explorer", "safe", ["(show | hide | toggle) ~ preview [pane]"]),
    ("alt+shift+p", "explorer", "safe", ["(show | hide | toggle) ~ details [pane]"]),
    ("ctrl+e", "explorer", "safe", ["search [in] (this | the) folder", "(go to | focus) ~ search [box | bar]"]),
    ("ctrl+l", "explorer", "safe", ["(go to | focus | select) ~ (address | path | location) bar"]),
    ("f2", "explorer", "edit", ["rename [~ (file | folder) | this | it]"]),
    ("ctrl+t", "explorer", "safe", ["[open] [a] [another] new tab"]),
    ("ctrl+w", "explorer", "safe", ["close ~ [current] tab"]),
    ("ctrl+n", "explorer", "safe", ["[open] [a] new [explorer] window"]),
    ("f5", "explorer", "safe", ["(refresh | reload) [~ (folder | window)]"]),
    ("ctrl+shift+6", "explorer", "safe", ["[show | switch to | change to] [the] details [view]"]),
    ("ctrl+shift+2", "explorer", "safe", ["[show | switch to | change to] [the] large icons [view]"]),
    # ------------------------------------------------------------------ Word
    ("ctrl+e", "word", "edit", ["(center | centre) [~ (text | line | paragraph)]", "align ~ [text] [to the] (center | centre)"]),
    ("ctrl+l", "word", "edit", ["align ~ [text] [to the] left", "left align"]),
    ("ctrl+r", "word", "edit", ["align ~ [text] [to the] right", "right align"]),
    ("ctrl+j", "word", "edit", ["justify [the] [text | paragraph]"]),
    ("ctrl+enter", "word", "edit", ["[insert | add] [a] page break", "new page"]),
    ("ctrl+n", "word", "safe", ["(new | create a new | open a new) [blank] document"]),
    ("ctrl+o", "word", "safe", ["open [a] (document | file)"]),
    ("ctrl+shift+.", "word", "edit", ["[make] [the] (text | font) bigger", "increase [the] font [size]"]),
    ("ctrl+shift+,", "word", "edit", ["[make] [the] (text | font) smaller", "decrease [the] font [size]"]),
    ("ctrl+shift+l", "word", "edit", ["(make | start) [a] (bullet | bulleted) list", "add (bullet | bullets)"]),
    ("ctrl+h", "word", "safe", ["[open] [find and] replace"]),
    ("ctrl+k", "word", "edit", ["(insert | add) [a] (link | hyperlink)"]),
    ("f7", "word", "safe", ["(check | run) [the] spelling [and grammar]", "(spellcheck | spell check)"]),
    # ------------------------------------------------------------------ VS Code
    ("ctrl+shift+p", "vscode", "safe", ["(open | show) ~ command palette", "command palette"]),
    ("ctrl+p", "vscode", "safe", ["[quick] open [a] file", "go to [a] file"]),
    ("ctrl+b", "vscode", "safe", ["(show | hide | toggle) ~ (sidebar | side bar)"]),
    ("ctrl+`", "vscode", "safe", ["(open | show | hide | toggle) ~ terminal"]),
    ("ctrl+shift+e", "vscode", "safe", ["(show | open | focus) ~ [file] explorer"]),
    ("ctrl+shift+f", "vscode", "safe", ["search [in | across] [all] [the] files", "find in files"]),
    ("ctrl+shift+x", "vscode", "safe", ["(show | open) ~ extensions"]),
    ("ctrl+g", "vscode", "safe", ["go to [a] line"]),
    ("ctrl+/", "vscode", "edit", ["(comment | uncomment) [~ (line | lines | selection) | this | it]", "toggle comment"]),
    ("shift+alt+f", "vscode", "edit", ["format ~ (document | file | code)", "format (it | this)"]),
    ("ctrl+\\", "vscode", "safe", ["split ~ (editor | screen)"]),
    ("ctrl+shift+`", "vscode", "safe", ["[open] [a] new terminal"]),
    ("f5", "vscode", "safe", ["[start | run] (debug | debugging)", "run [the] (code | program)"]),
    ("ctrl+=", "vscode", "safe", ["zoom in", "make ~ [text | font] bigger"]),
    ("ctrl+-", "vscode", "safe", ["zoom out", "make ~ [text | font] smaller"]),
    # ------------------------------------------------------------------ Notepad
    ("ctrl+t", "notepad", "safe", ["[open] [a] [another] new tab"]),
    ("ctrl+w", "notepad", "safe", ["close ~ [current] tab"]),
    ("ctrl+h", "notepad", "safe", ["[open] [find and] replace"]),
    ("ctrl+g", "notepad", "safe", ["go to [a] line"]),
    ("f5", "notepad", "edit", ["(insert | add | type) [the] (time and date | date and time | date | time)"]),
    ("ctrl+=", "notepad", "safe", ["zoom in", "make ~ [text] bigger"]),
    ("ctrl+-", "notepad", "safe", ["zoom out", "make ~ [text] smaller"]),
    # ------------------------------------------------------------------ by number: taskbar apps, tabs, YouTube
    ("win+1", "windows", "safe", ["(open | switch to) [the] first (app | pinned app | taskbar app) [on the taskbar]", "first taskbar app"]),
    ("win+2", "windows", "safe", ["(open | switch to) [the] second (app | pinned app | taskbar app) [on the taskbar]", "second taskbar app"]),
    ("win+3", "windows", "safe", ["(open | switch to) [the] third (app | pinned app | taskbar app) [on the taskbar]", "third taskbar app"]),
    ("win+4", "windows", "safe", ["(open | switch to) [the] fourth (app | pinned app | taskbar app) [on the taskbar]", "fourth taskbar app"]),
    ("win+5", "windows", "safe", ["(open | switch to) [the] fifth (app | pinned app | taskbar app) [on the taskbar]", "fifth taskbar app"]),
    ("win+6", "windows", "safe", ["(open | switch to) [the] sixth (app | pinned app | taskbar app) [on the taskbar]", "sixth taskbar app"]),
    ("win+7", "windows", "safe", ["(open | switch to) [the] seventh (app | pinned app | taskbar app) [on the taskbar]", "seventh taskbar app"]),
    ("win+8", "windows", "safe", ["(open | switch to) [the] eighth (app | pinned app | taskbar app) [on the taskbar]", "eighth taskbar app"]),
    ("win+9", "windows", "safe", ["(open | switch to) [the] ninth (app | pinned app | taskbar app) [on the taskbar]", "ninth taskbar app"]),
    ("ctrl+2", "browser", "safe", ["(go to | switch to) [the] second tab", "tab (2 | second)"]),
    ("ctrl+3", "browser", "safe", ["(go to | switch to) [the] third tab", "tab (3 | third)"]),
    ("ctrl+4", "browser", "safe", ["(go to | switch to) [the] fourth tab", "tab (4 | fourth)"]),
    ("ctrl+5", "browser", "safe", ["(go to | switch to) [the] fifth tab", "tab (5 | fifth)"]),
    ("ctrl+6", "browser", "safe", ["(go to | switch to) [the] sixth tab", "tab (6 | sixth)"]),
    ("ctrl+7", "browser", "safe", ["(go to | switch to) [the] seventh tab", "tab (7 | seventh)"]),
    ("ctrl+8", "browser", "safe", ["(go to | switch to) [the] eighth tab", "tab (8 | eighth)"]),
    ("1", "youtube", "safe", ["(go | skip | jump) to 10 (percent | %) [of the video]"]),
    ("2", "youtube", "safe", ["(go | skip | jump) to 20 (percent | %) [of the video]"]),
    ("3", "youtube", "safe", ["(go | skip | jump) to 30 (percent | %) [of the video]"]),
    ("4", "youtube", "safe", ["(go | skip | jump) to 40 (percent | %) [of the video]"]),
    ("5", "youtube", "safe", ["(go | skip | jump) to 50 (percent | %) [of the video]"]),
    ("6", "youtube", "safe", ["(go | skip | jump) to 60 (percent | %) [of the video]"]),
    ("7", "youtube", "safe", ["(go | skip | jump) to 70 (percent | %) [of the video]"]),
    ("8", "youtube", "safe", ["(go | skip | jump) to 80 (percent | %) [of the video]"]),
    ("9", "youtube", "safe", ["(go | skip | jump) to 90 (percent | %) [of the video]"]),
    # ------------------------------------------------------------------ more of Windows (the research's list)
    ("win+alt+up", "windows", "safe", ["snap ~ [window | app] to the top [half]"]),
    ("win+alt+down", "windows", "safe", ["snap ~ [window | app] to the bottom [half]"]),
    ("win+shift+up", "windows", "safe", ["stretch ~ [window | app] [to the full height | top to bottom]"]),
    ("alt+print_screen", "windows", "safe", ["(screenshot | screen shot) (of this | this) window",
                                             "copy [a] screenshot of (this | the) window"]),
    ("win+shift+r", "windows", "safe", ["record [a | an] (part | area | region) of the screen", "record a screen region"]),
    ("win+alt+g", "windows", "safe", ["clip that", "save the last (30 seconds | few moments | thirty seconds)"]),
    ("win+ctrl+l", "windows", "safe", ["(turn on | turn off | start | stop | toggle) [the] live captions", "live captions"]),
    ("win+ctrl+v", "windows", "safe", ["(open | show) ~ sound output [settings]", "(choose | pick | change) [the] "
                                       "(speaker | speakers | audio output | sound output) [device]"]),
    ("win+alt+k", "windows", "safe", ["(mute | unmute) [my] (mic | microphone) in [the] call", "(mute | unmute) [the] call"]),
    ("win+alt+b", "windows", "safe", ["(turn on | turn off | toggle) [the] hdr"]),
    ("win+space", "windows", "safe", ["(switch | change) [the] (keyboard | input) (language | layout)"]),
    ("win+-", "windows", "safe", ["zoom out [the] magnifier", "magnifier zoom out"]),
    ("win+ctrl+n", "windows", "safe", ["(open | show) ~ narrator settings"]),
    ("win+ctrl+m", "windows", "safe", ["(open | show) ~ magnifier settings"]),
    ("shift+f10", "windows", "safe", ["(open | show) ~ (context | right click) menu", "right click (this | it)"]),
    # ------------------------------------------------------------------ moving about in text
    ("ctrl+left", "text", "safe", ["(go | move) back (a | one) word", "previous word"]),
    ("ctrl+right", "text", "safe", ["(go | move) (forward | on) (a | one) word", "next word"]),
    ("home", "text", "safe", ["go to [the] (start | beginning) of [the] line"]),
    ("end", "text", "safe", ["go to [the] end of [the] line"]),
    ("ctrl+delete", "text", "edit", ["delete [the] next word"]),
    ("shift+home", "text", "safe", ["select to [the] (start | beginning) of [the] line"]),
    ("shift+end", "text", "safe", ["select to [the] end of [the] line"]),
    ("ctrl+shift+left", "text", "safe", ["select [the] (previous | last) word"]),
    ("ctrl+shift+right", "text", "safe", ["select [the] next word"]),
    ("ctrl+shift+home", "text", "safe", ["select [everything] to the (top | start | beginning)"]),
    ("ctrl+shift+end", "text", "safe", ["select [everything] to the (bottom | end)"]),
    # ------------------------------------------------------------------ more of File Explorer
    ("ctrl+shift+1", "explorer", "safe", ["[show | switch to | change to] [the] extra large icons [view]"]),
    ("ctrl+shift+3", "explorer", "safe", ["[show | switch to | change to] [the] medium icons [view]"]),
    ("ctrl+shift+4", "explorer", "safe", ["[show | switch to | change to] [the] small icons [view]"]),
    ("ctrl+shift+5", "explorer", "safe", ["[show | switch to | change to] [the] list [view]", "show as [a] list"]),
    ("ctrl+shift+7", "explorer", "safe", ["[show | switch to | change to] [the] tiles [view]"]),
    ("ctrl+shift+8", "explorer", "safe", ["[show | switch to | change to] [the] content [view]"]),
    ("ctrl+shift+e", "explorer", "safe", ["expand all [the] folders"]),
    ("ctrl+tab", "explorer", "safe", ["(next | switch) tab", "(go to | switch to) [the] next tab"]),
    ("ctrl+shift+tab", "explorer", "safe", ["previous tab", "(go to | switch to) [the] previous tab"]),
    ("f11", "explorer", "safe", ["[go | make it] (full screen | fullscreen)"]),
    # ------------------------------------------------------------------ more of the browser
    ("ctrl+shift+page_up", "browser", "safe", ["move ~ tab [to the] left"]),
    ("ctrl+shift+page_down", "browser", "safe", ["move ~ tab [to the] right"]),
    # ------------------------------------------------------------------ more of YouTube
    ("esc", "youtube", "safe", ["(exit | leave) (full screen | fullscreen | the mini player | the miniplayer)",
                                "close the (mini player | miniplayer)"]),
    ("ctrl+right", "youtube", "safe", ["[go to | skip to | play] [the] next chapter"]),
    ("ctrl+left", "youtube", "safe", ["[go to | skip to | play] [the] previous chapter"]),
    ("shift+=", "youtube", "safe", ["(make | turn) [the] (captions | subtitles) bigger", "bigger (captions | subtitles)"]),
    ("-", "youtube", "safe", ["(make | turn) [the] (captions | subtitles) smaller", "smaller (captions | subtitles)"]),
    (".", "youtube", "safe", ["(next | forward one | step forward [a | one]) frame"]),
    (",", "youtube", "safe", ["(previous | back one | step back [a | one]) frame"]),
    ("shift+/", "youtube", "safe", ["(show | open) [youtube] keyboard shortcuts"]),
    # ------------------------------------------------------------------ more of Word
    ("ctrl+alt+1", "word", "edit", ["(make ~ [a] | turn ~ into [a]) heading [1 | one]", "heading (1 | one)"]),
    ("ctrl+alt+2", "word", "edit", ["(make ~ [a] | turn ~ into [a]) heading (2 | two)", "heading (2 | two)"]),
    ("ctrl+alt+3", "word", "edit", ["(make ~ [a] | turn ~ into [a]) heading (3 | three)", "heading (3 | three)"]),
    ("ctrl+shift+n", "word", "edit", ["(make ~ | back to) normal [text | style]", "normal style"]),
    ("ctrl+1", "word", "edit", ["single (line spacing | spacing | space)", "single space ~ [text | lines]"]),
    ("ctrl+2", "word", "edit", ["double (line spacing | spacing | space)", "double space ~ [text | lines]"]),
    ("ctrl+5", "word", "edit", ["(1.5 | one and a half) [line] spacing"]),
    ("shift+f3", "word", "edit", ["change [the] case [of ~ (text | selection)]"]),
    ("ctrl+shift+a", "word", "edit", ["(make ~ [text] | put ~ in) (all caps | all capitals | capitals | uppercase)",
                                      "all caps"]),
    ("ctrl+]", "word", "edit", ["(make ~ [text] | font) (a bit | a little) bigger"]),
    ("ctrl+[", "word", "edit", ["(make ~ [text] | font) (a bit | a little) smaller"]),
    ("ctrl+m", "word", "edit", ["indent [~ (paragraph | text | this)]"]),
    ("ctrl+shift+e", "word", "safe", ["(turn on | turn off | toggle) [the] track changes", "track changes"]),
    ("ctrl+alt+m", "word", "safe", ["(insert | add) [a] comment"]),
    ("shift+f7", "word", "safe", ["(open | show) [the] thesaurus", "thesaurus"]),
    ("ctrl+f2", "word", "safe", ["print preview", "(show | open) [the] print preview"]),
    ("f12", "word", "safe", ["save as", "save ~ (file | document) as"]),
    ("ctrl+g", "word", "safe", ["go to [a] (page | line)"]),
    ("ctrl+f1", "word", "safe", ["(show | hide | toggle | collapse | expand) [the] ribbon"]),
    ("ctrl+=", "word", "safe", ["zoom in"]),
    ("ctrl+-", "word", "safe", ["zoom out"]),
    ("ctrl+0", "word", "safe", ["(reset | normal | default) zoom", "reset [the] zoom"]),
    # ------------------------------------------------------------------ more of VS Code
    ("ctrl+,", "vscode", "safe", ["(open | show) [the] settings", "settings"]),
    ("ctrl+n", "vscode", "safe", ["[open | create] [a] new file"]),
    ("ctrl+shift+n", "vscode", "safe", ["[open] [a] new (window | vs code window)"]),
    ("ctrl+w", "vscode", "safe", ["close ~ [current] (tab | editor | file)"]),
    ("ctrl+shift+t", "vscode", "safe", ["(reopen | restore) ~ [last] [closed] (tab | editor | file)"]),
    ("ctrl+tab", "vscode", "safe", ["(next | switch) (tab | editor | file)"]),
    ("ctrl+shift+tab", "vscode", "safe", ["previous (tab | editor | file)"]),
    ("f12", "vscode", "safe", ["go to [the] definition"]),
    ("shift+f12", "vscode", "safe", ["(show | find) [all] [the] references"]),
    ("f2", "vscode", "edit", ["rename [~ (symbol | variable | function)]"]),
    ("ctrl+.", "vscode", "safe", ["quick fix", "(show | open) [the] quick fix [menu]"]),
    ("alt+z", "vscode", "safe", ["(turn on | turn off | toggle) [the] word wrap", "word wrap"]),
    ("alt+up", "vscode", "edit", ["move ~ line up"]),
    ("alt+down", "vscode", "edit", ["move ~ line down"]),
    ("ctrl+shift+k", "vscode", "edit", ["delete ~ line"]),
    ("ctrl+l", "vscode", "safe", ["select ~ line"]),
    ("ctrl+shift+g", "vscode", "safe", ["(show | open) [the] source control", "source control"]),
    ("ctrl+shift+d", "vscode", "safe", ["(show | open) [the] run and debug [panel | view]"]),
    ("ctrl+shift+m", "vscode", "safe", ["(show | open) [the] problems [panel]", "problems"]),
    ("shift+f5", "vscode", "safe", ["stop (debugging | the debugger | running)"]),
    ("f9", "vscode", "safe", ["(add | set | remove | toggle) [a] breakpoint", "breakpoint"]),
    ("f10", "vscode", "safe", ["step over"]),
    ("f11", "vscode", "safe", ["step into"]),
    ("shift+f11", "vscode", "safe", ["step out"]),
    # ------------------------------------------------------------------ more of Notepad
    ("ctrl+shift+n", "notepad", "safe", ["[open] [a] new [notepad] window"]),
    ("ctrl+shift+s", "notepad", "edit", ["save as", "save ~ (file | note) as"]),
]

ARTICLE = "(?:the |this |that |it |my |a |an )?"


def _compile(said):
    """How it's said, as a regex for the words with a space after each: "show [the] desktop" ->
    "show (?:the )?desktop ". Brackets nest."""
    tokens = re.findall(r"\[|\]|\(|\)|\||~|[^\s\[\]()|~]+", said)
    pos = [0]

    def seq(end):
        alts, parts = [], []
        while pos[0] < len(tokens) and tokens[pos[0]] not in end:
            tok = tokens[pos[0]]
            pos[0] += 1
            if tok == "|":
                alts.append("".join(parts))
                parts = []
            elif tok in "[(":
                inner = seq("])")
                pos[0] += 1  # the closing bracket
                parts.append(f"(?:{inner})" + ("?" if tok == "[" else ""))
            elif tok == "~":
                parts.append(ARTICLE)
            else:
                parts.append(tok + " ")
        alts.append("".join(parts))
        return "|".join(alts) if len(alts) > 1 else alts[0]
    out = seq(())
    if pos[0] != len(tokens):
        raise ValueError(f"unbalanced brackets in {said!r}")
    return out


class Shortcut:
    def __init__(self, keys, scope, kind, said):
        self.keys, self.scope, self.kind, self.said = keys, scope, kind, said
        self.rx = re.compile("(?:" + "|".join(f"(?:{_compile(s)})" for s in said) + ")")
        self.id = f"{scope}:{keys}"

    def __repr__(self):
        return f"Shortcut({self.id!r}, {self.kind})"


ALL = [Shortcut(*row) for row in TABLE]
BY_ID = {s.id: s for s in ALL}


def scopes(exe="", youtube=False):
    """Where the program in front (its .exe, and whether YouTube is playing in it) takes shortcuts, most particular
    first."""
    exe = str(exe or "").lower().replace("/", "\\").rsplit("\\", 1)[-1]
    out = ["youtube"] if youtube else []
    if exe in BROWSERS:
        out.append("browser")
    out += [name for name, exes in PROGRAMS.items() if exe in exes]
    return out + ["text", "windows"]


def find(text, where):
    """The shortcut these words ask for, in the program in front (where: scopes()), or None. Only the whole phrase
    counts. Said for another app (YouTube's "captions" with Word in front), None: the model works out what they
    meant."""
    t = " ".join(re.sub(r"[^\w\s'`/\\.,=-]", " ", str(text or "").lower()).split())
    if not t:
        return None
    for scope in where:
        for s in ALL:
            if s.scope == scope and s.rx.fullmatch(t + " "):
                return s
    return None
