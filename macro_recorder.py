"""Feather Macro - records mouse (clicks + movement) and keyboard, then plays
them back in a loop. Ships as a small desktop app with a UI.

Hotkeys (also clickable, editable in Settings -> HOTKEYS):
  F8 / Record      start / stop recording
  F9 / Play        start / stop looping playback
  F6 / Auto Click  start / stop the auto clicker
  ESC / Quit       exit

Settings (UI theme + hotkeys) are saved to/loaded from "macro_config.json" in
this folder. The macro itself is saved to "macro.json".
The configured hotkeys are not recorded so playback can't re-trigger the
recorder.
"""
import colorsys
import json
import math
import os
import queue
import sys
import time
import threading
import tkinter as tk

from pynput import mouse, keyboard

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

MACRO_FILE = os.path.join(APP_DIR, "macro.json")
CONFIG_FILE = os.path.join(APP_DIR, "macro_config.json")


def resource_path(name):
    base = getattr(sys, "_MEIPASS", None) or APP_DIR
    return os.path.join(base, name)

HOTKEYS = {"f8", "f9", "esc"}

DEFAULT_HOTKEYS = {"record": "f8", "play": "f9", "quit": "esc", "autoclick": "f6"}

MAX_CPS = 50  # hard cap: faster than this floods Windows and freezes everything


def hotkey_display(name):
    name = str(name)
    if name.startswith("char:"):
        return name[len("char:"):].upper()
    if name.startswith("vk:"):
        return name[len("vk:"):].upper()
    return name.upper()

MOVE_THRESHOLD = 4      # min pixels of movement to record
MOVE_MIN_TIME = 0.1     # min seconds between recorded movement samples

# -- theme ---------------------------------------------------------------------
ACCENT = "#4f8cff"
RED = "#ff5c5c"
GREEN = "#3ecf6e"
YELLOW = "#f5b942"

THEMES = {
    "dark": {
        "bg": "#1b1e23", "panel": "#23272e", "btn": "#2b313b",
        "fg": "#e8eaed", "muted": "#9aa3ad", "border": "#14171b",
    },
    "light": {
        "bg": "#f2f3f5", "panel": "#ffffff", "btn": "#e4e7eb",
        "fg": "#1c1e21", "muted": "#6b7280", "border": "#d5d9de",
    },
    "galaxy": {
        "bg": "#0f0a1e", "panel": "#1b1233", "btn": "#241a40",
        "fg": "#e8e4ff", "muted": "#9a8fc7", "border": "#0a0618",
    },
    "miku": {
        "bg": "#0d1b1a", "panel": "#14302d", "btn": "#1c3b38",
        "fg": "#eafbf9", "muted": "#7fbdb4", "border": "#06201d",
    },
}

DEFAULT_THEME = "dark"

THEME_IMAGES = {"miku": "img_MIKU_us.png"}
THEME_BADGES = {"miku": "noFilter.png"}

ROLE_NAMES = [
    ("bg", "Background"),
    ("panel", "Panels"),
    ("btn", "Buttons"),
    ("border", "Borders"),
    ("fg", "Text"),
    ("muted", "Muted text"),
]

DEFAULT_CUSTOM = {
    "bg": "#1b1e23", "panel": "#23272e", "btn": "#2b313b",
    "fg": "#e8eaed", "muted": "#9aa3ad", "border": "#14171b",
}


def hsv_to_hex(h, s, v):
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, max(0.0, min(1.0, s)),
                                  max(0.0, min(1.0, v)))
    return "#%02x%02x%02x" % (int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


def hex_to_hsv(hex_color):
    hex_color = (hex_color or "").strip().lstrip("#")
    if len(hex_color) != 6:
        return 0.0, 0.0, 1.0
    try:
        r, g, b = [int(hex_color[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError:
        return 0.0, 0.0, 1.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360.0, s, v


class ColorWheel(tk.Canvas):
    R = 78

    def __init__(self, master, on_color):
        self.SIZE = self.R * 2
        super().__init__(master, width=self.SIZE, height=self.SIZE,
                         highlightthickness=0, bd=0)
        self.outside = "#23272e"
        self.on_color = on_color
        self.h, self.s, self.v = 0.0, 0.0, 1.0
        self._img = None
        self._img_id = None
        self.ring = None
        self.redraw()
        self.bind("<Button-1>", self._picked)
        self.bind("<B1-Motion>", self._picked)

    def set_outside(self, color):
        if color == self.outside:
            return
        self.outside = color
        self.redraw()

    def set_hsv(self, h, s, v):
        self.h, self.s, self.v = h % 360, max(0.0, min(1.0, s)), max(0.0, min(1.0, v))
        self.redraw()

    def redraw(self):
        if self._img_id is not None:
            self.delete(self._img_id)
        img = tk.PhotoImage(width=self.SIZE, height=self.SIZE)
        for y in range(self.SIZE):
            row = []
            for x in range(self.SIZE):
                dx = x - self.R
                dy = y - self.R
                dist = (dx * dx + dy * dy) ** 0.5
                if dist > self.R:
                    row.append(self.outside)
                else:
                    row.append(hsv_to_hex(math.degrees(math.atan2(dy, dx)) % 360,
                                          dist / self.R, self.v))
            img.put(row, to=(0, y))
        self._img = img
        self._img_id = self.create_image(self.R, self.R, image=img)
        self._draw_ring()

    def _draw_ring(self):
        if self.ring is not None:
            self.delete(self.ring)
        rad = math.radians(self.h)
        px = self.R + self.s * self.R * math.cos(rad)
        py = self.R + self.s * self.R * math.sin(rad)
        self.ring = self.create_oval(px - 5, py - 5, px + 5, py + 5,
                                     outline="#ffffff", width=2)

    def _picked(self, ev):
        dx = ev.x - self.R
        dy = ev.y - self.R
        dist = (dx * dx + dy * dy) ** 0.5
        if dist > self.R:
            return
        self.h = math.degrees(math.atan2(dy, dx)) % 360
        self.s = dist / self.R
        self._draw_ring()
        self.on_color(hsv_to_hex(self.h, self.s, self.v))


class ValueBar(tk.Canvas):
    def __init__(self, master, height, on_value):
        self.height = height
        super().__init__(master, width=24, height=height,
                         highlightthickness=0, bd=0)
        self.h, self.s, self.v = 0.0, 0.0, 1.0
        self.on_value = on_value
        self._img = None
        self._img_id = None
        self.mark = None
        self.redraw()
        self.bind("<Button-1>", self._set)
        self.bind("<B1-Motion>", self._set)

    def set_hsv(self, h, s, v):
        self.h, self.s, self.v = h % 360, max(0.0, min(1.0, s)), max(0.0, min(1.0, v))
        self.redraw()

    def redraw(self):
        if self._img_id is not None:
            self.delete(self._img_id)
        img = tk.PhotoImage(width=1, height=self.height)
        for y in range(self.height):
            img.put(hsv_to_hex(self.h, self.s, 1 - y / max(1, self.height - 1)), to=(0, y))
        self._img = img
        self._img_id = self.create_image(0, 0, anchor="nw", image=img)
        self._draw_mark()

    def _draw_mark(self):
        if self.mark is not None:
            self.delete(self.mark)
        y = int((1 - self.v) * (self.height - 1))
        self.mark = self.create_rectangle(0, y - 2, 24, y + 2,
                                          outline="#ffffff", width=2)

    def _set(self, ev):
        self.v = 1 - max(0, min(self.height - 1, ev.y)) / max(1, self.height - 1)
        self._draw_mark()
        self.on_value(self.v)


def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f)
    except Exception:
        pass


def button_name(b):
    return str(b).replace("Button.", "")


def button_from_name(name):
    return getattr(mouse.Button, name, mouse.Button.left)


def key_name(k):
    if isinstance(k, keyboard.KeyCode):
        return ("char:" if k.char is not None else "vk:") + (k.char if k.char is not None else str(k.vk))
    return str(k).replace("Key.", "")


def key_from_name(name):
    if name.startswith("char:"):
        return keyboard.KeyCode.from_char(name[len("char:"):])
    if name.startswith("vk:"):
        return keyboard.KeyCode.from_vk(int(name[len("vk:"):]))
    return getattr(keyboard.Key, name, keyboard.Key.space)


class Recorder:
    def __init__(self, hotkeys=None):
        self.recording = False
        self.playing = False
        self.events = []          # list of dicts: t, type, action, ...
        self.start_t = 0.0
        self.held_keys = set()    # keys currently held down (avoid auto-repeat)
        self.stop_play = threading.Event()
        self.lock = threading.Lock()
        self.last_mouse_pos = None  # last recorded mouse position
        self.last_move_t = 0.0
        self.start_pos = None       # mouse position when recording started
        self.loops = 0              # completed playback loops
        self.message = "Ready. Click Record or press %s." % hotkey_display(DEFAULT_HOTKEYS["record"])
        self.quit_requested = False
        cfg = load_config()
        self.hotkeys = dict(DEFAULT_HOTKEYS)
        self.hotkeys.update(cfg.get("hotkeys", {}) or {})
        self.capture_target = None   # hotkey role currently awaiting a key press
        self.on_capture = None       # callback(role, name) for UI updates
        self.speed = float(cfg.get("speed", 1.0))   # playback speed multiplier
        # auto clicker state
        self.clicking = False
        self.click_stop = threading.Event()
        self.cps = 10
        self.click_button = "left"
        self.click_hold = False

    # -- recording --------------------------------------------------------------
    def _record(self, ev):
        with self.lock:
            if not self.recording:
                return
            ev = dict(ev)
            ev["t"] = round(time.time() - self.start_t, 3)
            self.events.append(ev)

    def on_click(self, x, y, button, pressed):
        try:
            self._record({"type": "mouse", "x": x, "y": y,
                          "button": button_name(button),
                          "action": "down" if pressed else "up"})
        except Exception:
            pass

    def on_move(self, x, y):
        try:
            with self.lock:
                if not self.recording:
                    self.last_mouse_pos = None
                    return
                now = time.time() - self.start_t
                if self.last_mouse_pos is not None:
                    dx = x - self.last_mouse_pos[0]
                    dy = y - self.last_mouse_pos[1]
                    if dx * dx + dy * dy < MOVE_THRESHOLD ** 2 and now - self.last_move_t < MOVE_MIN_TIME:
                        return
                self.last_mouse_pos = (x, y)
                self.last_move_t = now
                self.events.append({"t": round(now, 3), "type": "move", "x": x, "y": y})
        except Exception:
            pass

    def _key_name(self, key):
        try:
            return key.name if hasattr(key, "name") else key.char
        except AttributeError:
            return str(key)

    # -- hotkeys ----------------------------------------------------------------
    def _capture_hotkey(self, name):
        target = self.capture_target
        self.capture_target = None
        if not name:
            if self.on_capture:
                self.on_capture(target, self.hotkeys.get(target))
            return
        for other, val in self.hotkeys.items():
            if other != target and val == name:
                self.message = "%s is already assigned to %s. Pick another key." % (
                    hotkey_display(name), other.capitalize())
                if self.on_capture:
                    self.on_capture(target, self.hotkeys.get(target))
                return
        self.hotkeys[target] = name
        self.message = "%s set as the %s hotkey." % (
            hotkey_display(name), target.capitalize())
        if self.on_capture:
            self.on_capture(target, name)

    def on_press(self, key):
        try:
            return self._on_press_impl(key)
        except Exception:
            pass

    def _on_press_impl(self, key):
        name = self._key_name(key)
        if self.capture_target is not None:
            self._capture_hotkey(name)
            return
        if name == self.hotkeys.get("quit"):
            self.quit_requested = True
            self.message = "Quitting..."
            self.stop_play.set()
            self.click_stop.set()
            return False  # stop listeners
        if name == self.hotkeys.get("record"):
            self.toggle_record()
            return
        if name == self.hotkeys.get("play"):
            self.toggle_play()
            return
        if name == self.hotkeys.get("autoclick"):
            self.toggle_autoclick()
            return
        # everything else gets recorded
        if name in self.hotkeys.values():
            return
        if key in self.held_keys:
            return
        self.held_keys.add(key)
        self._record({"type": "key", "key": key_name(key), "action": "down"})

    def on_release(self, key):
        try:
            self._on_release_impl(key)
        except Exception:
            pass

    def _on_release_impl(self, key):
        name = self._key_name(key)
        if self.capture_target is not None:
            return
        if name in self.hotkeys.values():
            return
        if key not in self.held_keys:
            return
        self.held_keys.discard(key)
        self._record({"type": "key", "key": key_name(key), "action": "up"})

    # -- actions (used by UI and hotkeys) ---------------------------------------
    def toggle_record(self):
        with self.lock:
            if self.playing:
                self.message = "Press %s (Play) to stop playback first." % hotkey_display(self.hotkeys["play"])
                return
            if self.recording:
                self.recording = False
                self.save()
                self.message = "Stopped recording: %d events saved." % len(self.events)
            else:
                self.events = []
                self.held_keys.clear()
                self.last_mouse_pos = None
                self.last_move_t = 0.0
                self.start_pos = list(mouse.Controller().position)
                self.start_t = time.time()
                self.recording = True
                self.message = "Recording... press %s / Stop when done." % hotkey_display(self.hotkeys["record"])

    def toggle_play(self):
        with self.lock:
            if self.recording:
                self.message = "Stop recording before playing."
                return
            if self.playing:
                self.stop_play.set()
                self.message = "Stopping playback..."
                return
            self.load()
            if not self.events:
                self.message = "Nothing recorded yet."
                return
            self.stop_play = threading.Event()
            self.loops = 0
            self.playing = True
            self.message = "Playing %d events (looping)... %s to stop." % (
                len(self.events), hotkey_display(self.hotkeys["play"]))
        threading.Thread(target=self._play, daemon=True).start()

    def request_quit(self):
        self.quit_requested = True
        self.message = "Quitting..."
        self.stop_play.set()
        self.click_stop.set()

    # -- auto clicker -----------------------------------------------------------
    def set_cps(self, cps):
        self.cps = max(1, min(MAX_CPS, int(cps)))

    def set_speed(self, speed):
        self.speed = max(0.1, min(5.0, float(speed)))

    def toggle_autoclick(self):
        with self.lock:
            if self.clicking:
                self.click_stop.set()
                self.message = "Stopping auto clicker..."
                return
            if self.recording or self.playing:
                self.message = "Stop recording / playback before auto clicking."
                return
            self.click_stop = threading.Event()
            self.clicking = True
            self.message = "Auto clicking %s at %d CPS... %s to stop." % (
                self.click_button, self.cps,
                hotkey_display(self.hotkeys["autoclick"]))
        threading.Thread(target=self._click_loop, daemon=True).start()

    def _click_loop(self):
        mctl = mouse.Controller()
        btn = self.decode_button({"button": self.click_button})
        interval = 1.0 / max(1, self.cps)
        try:
            if self.click_hold:
                mctl.press(btn)
                while not self.click_stop.is_set():
                    time.sleep(0.02)
            else:
                while not self.click_stop.is_set():
                    mctl.click(btn)
                    remaining = interval
                    while remaining > 0 and not self.click_stop.is_set():
                        step = min(0.02, remaining)
                        time.sleep(step)
                        remaining -= step
        except Exception as e:
            self.message = "Auto click error: %s" % e
        finally:
            try:
                mctl.release(btn)
            except Exception:
                pass
            with self.lock:
                self.clicking = False
            self.message = "Auto clicker stopped."

    # -- save / load ------------------------------------------------------------
    def save(self):
        try:
            with open(MACRO_FILE, "w") as f:
                json.dump({"start": self.start_pos, "events": self.events}, f)
        except Exception:
            self.message = "Could not save the macro (%s)." % os.path.basename(MACRO_FILE)

    def load(self):
        if not os.path.exists(MACRO_FILE):
            return
        try:
            with open(MACRO_FILE) as f:
                data = json.load(f)
        except Exception:
            self.events = []
            self.start_pos = None
            self.message = "Macro file was unreadable; starting empty."
            return
        self.events = data.get("events", []) or []
        self.start_pos = data.get("start")

    @staticmethod
    def decode_button(ev):
        try:
            return mouse.Button[ev["button"]]
        except (KeyError, TypeError):
            return mouse.Button.left

    # -- playback ---------------------------------------------------------------
    def _sleep(self, secs):
        end = time.time() + secs
        while not self.stop_play.is_set():
            remaining = end - time.time()
            if remaining <= 0:
                break
            time.sleep(min(0.05, remaining))

    def _play(self):
        mctl = mouse.Controller()
        kctl = keyboard.Controller()
        start = time.time()
        try:
            while not self.stop_play.is_set():
                self.loops += 1
                if self.start_pos is not None:
                    mctl.position = tuple(self.start_pos)
                prev = 0.0
                for ev in self.events:
                    if self.stop_play.is_set():
                        break
                    wait = (ev["t"] - prev) / max(0.1, self.speed)
                    prev = ev["t"]
                    if wait > 0:
                        self._sleep(wait)
                    if self.stop_play.is_set():
                        break
                    if ev["type"] == "mouse":
                        if ev["action"] == "down":
                            mctl.position = (ev["x"], ev["y"])
                            mctl.press(self.decode_button(ev))
                        else:
                            mctl.release(self.decode_button(ev))
                    elif ev["type"] == "move":
                        mctl.position = (ev["x"], ev["y"])
                    else:
                        k = key_from_name(ev["key"])
                        if ev["action"] == "down":
                            kctl.press(k)
                        else:
                            kctl.release(k)
                # release everything between loops so nothing stays held
                for b in (mouse.Button.left, mouse.Button.right, mouse.Button.middle):
                    mctl.release(b)
                for k in list(self.held_keys):
                    kctl.release(k)
                self.held_keys.clear()
        except Exception as e:
            self.message = "Playback error: %s" % e
        finally:
            for b in (mouse.Button.left, mouse.Button.right, mouse.Button.middle):
                mctl.release(b)
            for k in list(self.held_keys):
                kctl.release(k)
            self.held_keys.clear()
            with self.lock:
                self.playing = False
            self.message = "Stopped after %d loops in %.1fs." % (self.loops, time.time() - start)


class App:
    def __init__(self, root, rec):
        self.root = root
        self.rec = rec
        self.settings = None
        self.editor = None
        self.wheel = None
        self.valbar = None
        self.header_img = None
        self.header_badge = None
        self.capture_queue = queue.Queue()

        cfg = load_config()
        self.theme = cfg.get("theme", DEFAULT_THEME)
        if self.theme not in THEMES and self.theme != "custom":
            self.theme = DEFAULT_THEME
        self.custom = dict(DEFAULT_CUSTOM)
        self.custom.update(cfg.get("custom", {}))

        root.title("Feather Macro")
        root.resizable(False, False)

        self.status_var = tk.StringVar()
        self.events_var = tk.StringVar()
        self.loops_var = tk.StringVar()
        self.pos_var = tk.StringVar()

        self._build()
        self.apply_theme()

        root.after(100, self.poll)

    # -- widget helpers ---------------------------------------------------------
    def _label(self, parent, text, font, role):
        w = tk.Label(parent, text=text, font=font)
        w._role = role
        return w

    def _button(self, parent, text, command, role):
        w = tk.Button(parent, text=text, command=command,
                      relief="flat", bd=0, padx=12, pady=10,
                      font=("Segoe UI", 11, "bold"), cursor="hand2")
        w._role = role
        return w

    def _build(self):
        r = self.root
        r.grid_columnconfigure(0, weight=1)
        r.grid_rowconfigure(1, weight=1)

        # tab bar
        tabbar = tk.Frame(r)
        tabbar._role = "bg"
        tabbar.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        self.tab_macro = self._button(tabbar, "Macro", lambda: self.show_tab("macro"), "tab_sel")
        self.tab_macro.pack(side="left", padx=(0, 6))
        self.tab_auto = self._button(tabbar, "Auto Clicker", lambda: self.show_tab("auto"), "tab")
        self.tab_auto.pack(side="left")

        # tab content frames
        self.macro_tab = tk.Frame(r)
        self.macro_tab._role = "bg"
        self.macro_tab.grid(row=1, column=0, sticky="nsew")
        self.auto_tab = tk.Frame(r)
        self.auto_tab._role = "bg"
        self.auto_tab.grid(row=1, column=0, sticky="nsew")

        self._build_macro_tab(self.macro_tab)
        self._build_auto_tab(self.auto_tab)
        self.show_tab("macro")

    def _build_macro_tab(self, tab):
        # header
        header = tk.Frame(tab, padx=16, pady=12)
        header._role = "panel"
        header.grid(row=0, column=0, sticky="ew")
        self.header_frame = header
        texts = tk.Frame(header)
        texts._role = "panel"
        texts.pack(side="left")
        self._label(texts, "FEATHER MACRO", ("Segoe UI", 15, "bold"), "panel_fg").pack(anchor="w")
        self._label(texts, "mouse + keyboard automation", ("Segoe UI", 9), "panel_muted").pack(anchor="w")

        # status
        status = tk.Frame(tab, padx=16, pady=12)
        status._role = "bg"
        status.grid(row=1, column=0, sticky="ew")
        self.status_label = self._label(status, "", ("Segoe UI", 20, "bold"), "status")
        self.status_label.pack(anchor="w")
        self.message_label = self._label(status, "", ("Segoe UI", 10), "bg_muted")
        self.message_label.pack(anchor="w", pady=(6, 0))

        # record / play
        btns = tk.Frame(tab, padx=16)
        btns._role = "bg"
        btns.grid(row=2, column=0, sticky="ew")
        self.record_btn = self._button(btns, "Record  (%s)" % hotkey_display(self.rec.hotkeys["record"]), self.rec.toggle_record, "btn_accent")
        self.record_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.play_btn = self._button(btns, "Play  (%s)" % hotkey_display(self.rec.hotkeys["play"]), self.rec.toggle_play, "btn_green")
        self.play_btn.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=1)

        # playback speed
        speed_row = tk.Frame(tab)
        speed_row._role = "panel"
        speed_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))
        self._label(speed_row, "Playback speed", ("Segoe UI", 10), "panel_fg").pack(side="left", padx=(0, 12))
        self.speed_var = tk.DoubleVar(value=self.rec.speed)
        speed_scale = tk.Scale(speed_row, from_=0.1, to=5.0, resolution=0.1,
                               orient="horizontal", variable=self.speed_var,
                               showvalue=False, command=self._speed_changed)
        speed_scale._role = "scale"
        speed_scale.pack(side="left", fill="x", expand=True)
        self.speed_label = self._label(speed_row, "%.1fx" % self.rec.speed,
                                       ("Segoe UI", 10, "bold"), "panel_fg")
        self.speed_label.pack(side="left", padx=(12, 0))

        # stats
        stats = tk.Frame(tab, padx=16, pady=12)
        stats._role = "panel"
        stats.grid(row=4, column=0, sticky="ew", padx=16, pady=12)
        self._stat(stats, 0, "EVENTS", self.events_var)
        self._stat(stats, 1, "LOOPS", self.loops_var)
        self._stat(stats, 2, "MOUSE START", self.pos_var)
        for c in range(3):
            stats.grid_columnconfigure(c, weight=1)

        # settings / quit
        bottom = tk.Frame(tab, padx=16)
        bottom._role = "bg"
        bottom.grid(row=5, column=0, sticky="ew")
        self._button(bottom, "Settings", self.open_settings, "btn").grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.quit_btn = self._button(bottom, "Quit  (%s)" % hotkey_display(self.rec.hotkeys["quit"]), self.rec.request_quit, "btn_red")
        self.quit_btn.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)

        # footer
        self._label(tab, "Macro: %s    Config: %s" % (os.path.basename(MACRO_FILE), os.path.basename(CONFIG_FILE)),
                    ("Segoe UI", 8), "bg_muted").grid(row=6, column=0, pady=(8, 10))

    def _build_auto_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)

        # status
        status = tk.Frame(tab, padx=16, pady=12)
        status._role = "bg"
        status.grid(row=0, column=0, sticky="ew")
        self.auto_status_label = self._label(status, "", ("Segoe UI", 20, "bold"), "status")
        self.auto_status_label.pack(anchor="w")
        self._label(status, "auto clicker", ("Segoe UI", 10), "bg_muted").pack(anchor="w", pady=(6, 0))

        # start / stop
        btns = tk.Frame(tab, padx=16)
        btns._role = "bg"
        btns.grid(row=1, column=0, sticky="ew")
        self.click_btn = self._button(btns, "Start Clicking  (%s)" % hotkey_display(self.rec.hotkeys["autoclick"]), self.rec.toggle_autoclick, "btn_green")
        self.click_btn.grid(row=0, column=0, sticky="ew")
        btns.grid_columnconfigure(0, weight=1)

        # controls
        panel = tk.Frame(tab, padx=16, pady=12)
        panel._role = "panel"
        panel.grid(row=2, column=0, sticky="ew", padx=16, pady=12)

        row1 = tk.Frame(panel)
        row1._role = "panel"
        row1.pack(fill="x", pady=4)
        self._label(row1, "Clicks per second", ("Segoe UI", 10), "panel_fg").pack(side="left", padx=(0, 12))
        self.cps_var = tk.IntVar(value=self.rec.cps)
        scale = tk.Scale(row1, from_=1, to=MAX_CPS, orient="horizontal",
                         variable=self.cps_var, showvalue=True,
                         command=lambda v: self.rec.set_cps(v))
        scale._role = "scale"
        scale.pack(side="left", fill="x", expand=True)

        row2 = tk.Frame(panel)
        row2._role = "panel"
        row2.pack(fill="x", pady=4)
        self._label(row2, "Mouse button", ("Segoe UI", 10), "panel_fg").pack(side="left", padx=(0, 12))
        self.click_btn_var = tk.StringVar(value=self.rec.click_button)
        menu = tk.OptionMenu(row2, self.click_btn_var, "left", "middle", "right",
                             command=self._click_button_changed)
        menu._role = "menu"
        menu.pack(side="left")
        self._label(row2, "left", ("Segoe UI", 8), "panel_muted").pack(side="left", padx=8)

        row3 = tk.Frame(panel)
        row3._role = "panel"
        row3.pack(fill="x", pady=4)
        self._label(row3, "Mode", ("Segoe UI", 10), "panel_fg").pack(side="left", padx=(0, 12))
        self.click_mode_var = tk.StringVar(value="click")
        self._label(row3, "Click (press+release)  /  ", ("Segoe UI", 9), "panel_muted").pack(side="left")
        rb = tk.Radiobutton(row3, text="Hold (press until stopped)", value="hold",
                            variable=self.click_mode_var,
                            command=self._click_mode_changed)
        rb._role = "radio"
        rb.pack(side="left")

        hint = self._label(tab, "Toggle with %s, or click Start. Hotkeys are editable in Settings.\n"
                           "Keep CPS under ~30 or the system will freeze."
                           % hotkey_display(self.rec.hotkeys["autoclick"]),
                           ("Segoe UI", 8), "bg_muted")
        hint.grid(row=3, column=0, pady=(0, 10))
        self.auto_hint = hint
        self.auto_message_label = self._label(tab, "", ("Segoe UI", 10), "bg_muted")
        self.auto_message_label.grid(row=4, column=0, pady=(0, 6))

    def show_tab(self, name):
        if name == "auto":
            self.macro_tab.grid_remove()
            self.auto_tab.grid()
        else:
            self.auto_tab.grid_remove()
            self.macro_tab.grid()
        if getattr(self, "tab_macro", None) is not None:
            self.tab_macro._role = "tab_sel" if name == "macro" else "tab"
            self.tab_auto._role = "tab_sel" if name == "auto" else "tab"
            self.apply_theme()

    def _click_button_changed(self, value):
        self.rec.click_button = value

    def _speed_changed(self, value):
        self.rec.set_speed(float(value))
        self.speed_label.config(text="%.1fx" % self.rec.speed)

    def _click_mode_changed(self):
        self.rec.click_hold = (self.click_mode_var.get() == "hold")

    def _stat(self, parent, col, title, var):
        box = tk.Frame(parent, padx=10, pady=8)
        box._role = "bg"
        box.grid(row=0, column=col, sticky="ew", padx=4)
        self._label(box, title, ("Segoe UI", 8), "bg_muted").pack(anchor="w")
        val = tk.Label(box, textvariable=var, font=("Segoe UI", 12, "bold"))
        val._role = "bg_fg"
        val.pack(anchor="w")

    # -- theme ------------------------------------------------------------------
    def _load_theme_image(self, path, max_w=120):
        try:
            img = tk.PhotoImage(file=path)
        except Exception:
            return None
        scale = max(1, img.width() // max_w)
        if scale > 1:
            img = img.subsample(scale, scale)
        return img

    def _make_theme_image(self, parent, filename, max_w):
        if not filename:
            return None
        img = self._load_theme_image(resource_path(filename), max_w)
        if img is None:
            return None
        lbl = tk.Label(parent, image=img)
        lbl.image = img
        lbl._role = "panel"
        return lbl

    def current_theme_colors(self):
        if self.theme == "custom":
            base = dict(DEFAULT_CUSTOM)
            base.update(self.custom)
            return base
        return THEMES[self.theme]

    def _alive(self, w):
        try:
            return w is not None and w.winfo_exists()
        except tk.TclError:
            return False

    def apply_theme(self, save=False):
        t = self.current_theme_colors()

        self._set_theme_images()

        def apply(w):
            role = getattr(w, "_role", None)
            if role in ("bg", None):
                w.configure(bg=t["bg"])
            elif role == "panel":
                w.configure(bg=t["panel"])
            elif role == "panel_fg":
                w.configure(bg=t["panel"], fg=t["fg"])
            elif role == "panel_muted":
                w.configure(bg=t["panel"], fg=t["muted"])
            elif role == "bg_muted":
                w.configure(bg=t["bg"], fg=t["muted"])
            elif role == "bg_fg":
                w.configure(bg=t["bg"], fg=t["fg"])
            elif role == "status":
                w.configure(bg=t["bg"])
            elif role == "btn":
                w.configure(bg=t["btn"], fg=t["fg"],
                            activebackground=t["btn"], activeforeground=t["fg"],
                            highlightbackground=t["border"], highlightthickness=1)
            elif role == "btn_accent":
                w.configure(bg=t["btn"], fg=t["fg"],
                            activebackground=ACCENT, activeforeground=t["fg"],
                            highlightbackground=ACCENT, highlightthickness=1)
            elif role == "btn_green":
                w.configure(bg=t["btn"], fg=t["fg"],
                            activebackground=GREEN, activeforeground=t["fg"],
                            highlightbackground=GREEN, highlightthickness=1)
            elif role == "btn_red":
                w.configure(bg=t["btn"], fg=t["fg"],
                            activebackground=RED, activeforeground=t["fg"],
                            highlightbackground=RED, highlightthickness=1)
            elif role == "radio":
                w.configure(bg=t["panel"], fg=t["fg"], selectcolor=t["btn"],
                            activebackground=t["panel"], activeforeground=t["fg"],
                            highlightthickness=0)
            elif role == "tab":
                w.configure(bg=t["btn"], fg=t["fg"],
                            activebackground=t["btn"], activeforeground=t["fg"],
                            highlightthickness=1, highlightbackground=t["border"])
            elif role == "tab_sel":
                w.configure(bg=t["panel"], fg=t["fg"],
                            activebackground=t["panel"], activeforeground=t["fg"],
                            highlightthickness=1, highlightbackground=ACCENT)
            elif role == "scale":
                w.configure(bg=t["panel"], fg=t["fg"], troughcolor=t["bg"],
                            activebackground=t["fg"],
                            highlightthickness=1, highlightbackground=t["border"])
            elif role == "menu":
                w.configure(bg=t["btn"], fg=t["fg"],
                            activebackground=t["btn"], activeforeground=t["fg"],
                            highlightthickness=1, highlightbackground=t["border"])
            elif role == "entry":
                w.configure(bg=t["panel"], fg=t["fg"], insertbackground=t["fg"],
                            highlightthickness=1, highlightbackground=t["border"])
            elif role == "swatch":
                w.configure(bg=self.swatch_color.get())
            for c in w.winfo_children():
                apply(c)

        windows = [self.root]
        if self.settings is not None:
            try:
                if self.settings.winfo_exists():
                    windows.append(self.settings)
            except tk.TclError:
                self.settings = None
        for w in windows:
            apply(w)
        if self._alive(self.wheel):
            self.wheel.set_outside(t["panel"])
        if self._alive(self.valbar):
            self.valbar.configure(bg=t["panel"])
        if save:
            self.save_config()

    def _set_theme_images(self):
        for attr in ("header_img", "header_badge"):
            w = getattr(self, attr, None)
            if self._alive(w):
                try:
                    w.destroy()
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        if not self._alive(self.header_frame):
            return
        img_name = THEME_IMAGES.get(self.theme)
        if img_name:
            self.header_img = self._make_theme_image(self.header_frame, img_name, 120)
            if self._alive(self.header_img):
                self.header_img.pack(side="right", padx=(16, 0))
        badge_name = THEME_BADGES.get(self.theme)
        if badge_name:
            self.header_badge = self._make_theme_image(self.header_frame, badge_name, 44)
            if self._alive(self.header_badge):
                self.header_badge.pack(side="left", padx=(0, 12))

    def save_config(self):
        save_config({"theme": self.theme, "custom": self.custom,
                     "hotkeys": self.rec.hotkeys, "speed": self.rec.speed})

    def refresh_hotkey_labels(self):
        self.record_btn.config(text="Record  (%s)" % hotkey_display(self.rec.hotkeys["record"]))
        self.play_btn.config(text="Play  (%s)" % hotkey_display(self.rec.hotkeys["play"]))
        self.quit_btn.config(text="Quit  (%s)" % hotkey_display(self.rec.hotkeys["quit"]))
        if not self.rec.clicking:
            self.click_btn.config(text="Start Clicking  (%s)" % hotkey_display(self.rec.hotkeys["autoclick"]))
        if getattr(self, "auto_hint", None) is not None:
            self.auto_hint.config(text="Toggle with %s, or click Start. Hotkeys are editable in Settings."
                                  % hotkey_display(self.rec.hotkeys["autoclick"]))

    def choose_theme(self, name):
        self.theme = name
        if getattr(self, "theme_var", None) is not None:
            self.theme_var.set(name)
        self.save_config()
        self.apply_theme()
        if getattr(self, "editor", None) is not None:
            if name == "custom":
                self.editor.pack(fill="x", padx=14, pady=(4, 0))
            else:
                self.editor.pack_forget()

    # -- custom color editing ---------------------------------------------------
    def set_custom_color(self, role, hex_color):
        self.custom[role] = hex_color
        self.save_config()
        if self.theme == "custom":
            self.apply_theme()
        self.refresh_editor()

    def refresh_editor(self):
        if getattr(self, "role_var", None) is None:
            return
        role = self.role_var.get()
        hex_color = self.custom.get(role, "#000000")
        if getattr(self, "hex_var", None) is not None:
            self.hex_var.set(hex_color)
        if getattr(self, "swatch_color", None) is not None:
            self.swatch_color.set(hex_color)
        h, s, v = hex_to_hsv(hex_color)
        if self.wheel is not None:
            self.wheel.set_hsv(h, s, v)
        if self.valbar is not None:
            self.valbar.set_hsv(h, s, v)

    def reset_custom(self):
        self.custom = dict(DEFAULT_CUSTOM)
        self.save_config()
        if self.theme == "custom":
            self.apply_theme()
        self.refresh_editor()

    def _wheel_picked(self, hex_color):
        self.set_custom_color(self.role_var.get(), hex_color)

    def _value_picked(self, v):
        h, s, _ = hex_to_hsv(self.custom.get(self.role_var.get(), "#000000"))
        self.set_custom_color(self.role_var.get(), hsv_to_hex(h, s, v))

    def _hex_entered(self, event):
        text = self.hex_var.get().strip()
        if text and not text.startswith("#"):
            text = "#" + text
        if len(text) == 7:
            self.set_custom_color(self.role_var.get(), text)

    def _role_changed(self, *_):
        self.refresh_editor()

    # -- settings ---------------------------------------------------------------
    def open_settings(self):
        if self.settings is not None:
            try:
                self.settings.lift()
                self.settings.focus_force()
                return
            except tk.TclError:
                self.settings = None
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.resizable(False, False)
        win._role = "bg"
        self.settings = win

        self._label(win, "UI THEME", ("Segoe UI", 12, "bold"), "panel_fg").pack(anchor="w", padx=14, pady=(12, 4))

        self.theme_var = tk.StringVar(value=self.theme)
        theme_row = tk.Frame(win)
        theme_row._role = "bg"
        theme_row.pack(anchor="w", padx=26)
        for name in list(THEMES) + ["custom"]:
            rb = tk.Radiobutton(theme_row, text=name.capitalize(), value=name,
                                variable=self.theme_var,
                                command=lambda n=name: self.choose_theme(n))
            rb._role = "radio"
            rb.pack(side="left", padx=(0, 12))

        # custom color editor (hidden unless Custom is selected)
        self.editor = tk.Frame(win)
        self.editor._role = "panel"
        self.role_var = tk.StringVar(value="bg")
        self.hex_var = tk.StringVar()
        self.swatch_color = tk.StringVar(value="#000000")

        top = tk.Frame(self.editor)
        top._role = "panel"
        top.pack(fill="x", padx=12, pady=(8, 2))
        self._label(top, "Edit color:", ("Segoe UI", 10), "panel_fg").pack(side="left", padx=(0, 8))
        role_menu = tk.OptionMenu(top, self.role_var, *[n for n, _ in ROLE_NAMES])
        role_menu._role = "menu"
        role_menu.pack(side="left")
        self._label(top, "", ("Segoe UI", 10), "panel_muted").pack(side="left", padx=8)

        body = tk.Frame(self.editor)
        body._role = "panel"
        body.pack(fill="x", padx=12, pady=4)
        self.wheel = ColorWheel(body, self._wheel_picked)
        self.wheel.pack(side="left")
        self.valbar = ValueBar(body, self.wheel.SIZE, self._value_picked)
        self.valbar.pack(side="left", padx=(8, 0))

        side = tk.Frame(body)
        side._role = "panel"
        side.pack(side="left", padx=14)
        swatch = tk.Label(side, width=6, height=3, bg="#000000")
        swatch._role = "swatch"
        self.swatch = swatch
        self._sync_swatch = lambda: swatch.configure(bg=self.swatch_color.get())
        self.swatch_color.trace_add("write", lambda *a: self._sync_swatch())
        swatch.pack(anchor="w")
        self._label(side, "Hex #RRGGBB", ("Segoe UI", 8), "panel_muted").pack(anchor="w", pady=(8, 2))
        entry = tk.Entry(side, textvariable=self.hex_var, width=10,
                         justify="center", relief="flat", bd=0)
        entry._role = "entry"
        entry.bind("<Return>", self._hex_entered)
        entry.pack(anchor="w")
        self._label(side, "press Enter to apply", ("Segoe UI", 8), "panel_muted").pack(anchor="w")
        self._button(side, "Reset", self.reset_custom, "btn").pack(anchor="w", pady=(10, 0))

        self._label(self.editor, "Saved to macro_config.json", ("Segoe UI", 8), "bg_muted").pack(anchor="w", padx=12, pady=(4, 8))

        self.role_var.trace_add("write", self._role_changed)

        # hotkey editor
        self._label(win, "HOTKEYS", ("Segoe UI", 12, "bold"), "panel_fg").pack(anchor="w", padx=14, pady=(12, 4))
        hk_frame = tk.Frame(win)
        hk_frame._role = "bg"
        hk_frame.pack(fill="x", padx=14)
        self.hk_buttons = {}
        for role, label in (("record", "Record"), ("play", "Play"),
                            ("quit", "Quit"), ("autoclick", "Auto Click")):
            row = tk.Frame(hk_frame)
            row._role = "bg"
            row.pack(fill="x", pady=2)
            self._label(row, label, ("Segoe UI", 10), "bg_fg").pack(side="left", padx=(0, 12))
            btn = tk.Button(row, text=hotkey_display(self.rec.hotkeys[role]),
                            command=lambda r=role: self.arm_hotkey(r),
                            relief="flat", bd=0, padx=10, pady=4,
                            font=("Segoe UI", 10, "bold"), cursor="hand2")
            btn._role = "btn"
            btn.pack(side="left")
            self.hk_buttons[role] = btn
        self.hk_hint = self._label(win, "Click a key button, then press the new key.",
                                   ("Segoe UI", 8), "bg_muted")
        self.hk_hint.pack(anchor="w", padx=14, pady=(4, 0))

        def close():
            self.rec.capture_target = None
            win.destroy()
            self.settings = None
            self.editor = None
            self.wheel = None
            self.valbar = None
            self.theme_var = None
            self.role_var = None
            self.hex_var = None
            self.hk_buttons = {}
            self.hk_hint = None

        self._button(win, "Close", close, "btn").pack(fill="x", padx=14, pady=(8, 12))
        win.protocol("WM_DELETE_WINDOW", close)
        self.apply_theme()
        if self.theme == "custom":
            self.editor.pack(fill="x", padx=14, pady=(4, 0))
        self.refresh_editor()

    # -- hotkey editing ---------------------------------------------------------
    def arm_hotkey(self, role):
        self.rec.capture_target = role
        self.rec.message = "Press the new %s hotkey..." % role
        for r, b in getattr(self, "hk_buttons", {}).items():
            b.config(text="Press a key..." if r == role
                     else hotkey_display(self.rec.hotkeys[r]))
        if getattr(self, "hk_hint", None) is not None:
            self.hk_hint.config(text="Press the key to use for %s..." % role)

    def _hotkey_captured(self, role, name):
        self.save_config()
        if getattr(self, "hk_buttons", None):
            for r, b in self.hk_buttons.items():
                b.config(text=hotkey_display(self.rec.hotkeys[r]))
        if getattr(self, "hk_hint", None) is not None:
            if self.rec.hotkeys.get(role) == name:
                self.hk_hint.config(text="%s set as the %s hotkey." % (
                    hotkey_display(name), role.capitalize()))
            else:
                self.hk_hint.config(text="%s is already used by another hotkey." % hotkey_display(name))
        self.refresh_hotkey_labels()

    # -- polling ----------------------------------------------------------------
    def poll(self):
        try:
            self._poll_once()
        except Exception:
            pass
        self.root.after(100, self.poll)

    def _poll_once(self):
        rec = self.rec
        try:
            while True:
                role, name = self.capture_queue.get_nowait()
                self._hotkey_captured(role, name)
        except queue.Empty:
            pass
        if rec.quit_requested:
            self.root.destroy()
            return
        # watchdog: pynput hooks can die on odd input; restart them so recording
        # never silently stops working.
        try:
            if not getattr(self, "m_listener", None) or not self.m_listener.is_alive():
                self.m_listener = mouse.Listener(on_click=rec.on_click, on_move=rec.on_move)
                self.m_listener.start()
            if not getattr(self, "k_listener", None) or not self.k_listener.is_alive():
                self.k_listener = keyboard.Listener(on_press=rec.on_press, on_release=rec.on_release)
                self.k_listener.start()
        except Exception:
            pass
        if rec.recording:
            self.status_label.config(text="RECORDING", fg=RED)
        elif rec.playing:
            self.status_label.config(text="PLAYING", fg=GREEN)
        else:
            self.status_label.config(text="IDLE", fg=YELLOW)
        self.message_label.config(text=rec.message)
        self.events_var.set(str(len(rec.events)))
        self.loops_var.set(str(rec.loops))
        pos = rec.start_pos
        self.pos_var.set("(%d, %d)" % tuple(pos) if pos else "-")
        if rec.clicking:
            self.auto_status_label.config(text="CLICKING", fg=GREEN)
            self.click_btn.config(text="Stop Clicking")
        else:
            self.auto_status_label.config(text="IDLE", fg=YELLOW)
            self.click_btn.config(text="Start Clicking  (%s)" % hotkey_display(rec.hotkeys["autoclick"]))
        if getattr(self, "auto_message_label", None) is not None:
            self.auto_message_label.config(text=rec.message)


def main():
    rec = Recorder()
    root = tk.Tk()
    app = App(root, rec)
    rec.on_capture = lambda role, name: app.capture_queue.put((role, name))

    m_listener = mouse.Listener(on_click=rec.on_click, on_move=rec.on_move)
    k_listener = keyboard.Listener(on_press=rec.on_press, on_release=rec.on_release)
    m_listener.start()
    k_listener.start()
    app.m_listener = m_listener
    app.k_listener = k_listener

    try:
        root.mainloop()
    finally:
        rec.request_quit()
        for lst in (getattr(app, "m_listener", None), getattr(app, "k_listener", None)):
            try:
                lst.stop()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import tkinter.messagebox as mb
        try:
            mb.showerror("Feather Macro", "Failed to start:\n%s" % e)
        except Exception:
            pass
