# MacroRecorder

> **WARNING:** This tool records and replays mouse/keyboard input. Using
> macros or auto-clickers in games (e.g. Roblox) can violate the game's
> Terms of Service and get your account banned. Use it responsibly and only
> where allowed. Run in a VM if you want to be safe.

## What it does

A mouse & keyboard macro recorder with a themeable GUI.

- Records mouse clicks, mouse movement, and keyboard input.
- Plays the macro back on a **loop** until you stop it.
- Captures where the mouse was when recording started, and returns the cursor
  there at the start of every loop.
- Dark-themed GUI with themes: dark, light, galaxy, miku, and a fully custom
  theme editor (HSV color wheel + per-role colors).

## Controls / hotkeys

| Key | Action |
|-----|--------|
| `F8` | Toggle recording |
| `F9` | Toggle looping playback |
| `ESC` | Quit |

The hotkeys are **editable** — open **Settings → HOTKEYS**, click a key button,
then press the new key. Changes are saved to `macro_config.json`.
Hotkeys are not recorded into the macro itself.

## Run it (Windows)

Just download and double-click:

```
MacroRecorder.exe
```

No install needed — it's a standalone Windows program.

> The full source code is included in this repo as **`MacroRecorder.txt`**
> if you want to read (or rebuild from) it. It needs `img_MIKU_us.png` and
> `noFilter.png` (also included) for the miku theme. The exe is the
> ready-to-run version.

## Requirements (to run the exe)

- Windows (any modern version)

## Disclaimer

Provided as-is. Only use in environments where automation is permitted.
The author is not responsible for bans or damage caused by its use.
