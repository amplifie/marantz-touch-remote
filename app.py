#!/usr/bin/env python3
"""Marantz-Fernbedienung als Programm für das Surface (Python + GTK3).

Aufbau für die Bedienung mit beiden Händen (Querformat):
  links  (linker Daumen):  Ein/Aus, Seitenwahl, Szenen
  mitte:                   Lautstärke-Ring, Eingänge, Klangmodi / Klang & Pegel
  rechts (rechter Daumen): Lautstärke + / −  (gedrückt halten = weiter), Stumm

Spricht direkt mit dem Receiver (über marantz.py), braucht keinen Server.
F11 = Vollbild an/aus, Esc oder ✕ = beenden.
"""
import math
import json
import os
import queue
import subprocess
import sys
import urllib.parse
import urllib.request
import threading
import time
from pathlib import Path

import cairo
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import marantz as m  # noqa: E402
import sprachbefehle  # noqa: E402
import i18n  # noqa: E402
from i18n import _  # noqa: E402

# Alle Beschriftungen laufen durch die Übersetzung (Deutsch → Englisch, falls nötig)
_orig_label_set_text = Gtk.Label.set_text
_orig_button_set_label = Gtk.Button.set_label
Gtk.Label.set_text = lambda self, text: _orig_label_set_text(self, _(text))
Gtk.Button.set_label = lambda self, text: _orig_button_set_label(self, _(text))

VOICE_DIR = os.path.expanduser("~/.local/share/marantz-voice")

GOLD = (0.851, 0.725, 0.494)       # #d9b97e
GOLD_DEEP = (0.690, 0.549, 0.318)  # #b08c51

CSS = b"""
* { font-family: "Ubuntu Sans", "Ubuntu", "Noto Sans", sans-serif; }
window {
  background-color: #0b0c0e;
  background-image: radial-gradient(ellipse at 50% 35%, #1b1d22 0%, #0e0f12 55%, #08090a 100%);
  color: #ecebe8;
}
.rail { background-color: rgba(255,255,255,0.025); border-radius: 34px;
        border: 1px solid rgba(255,255,255,0.05); padding: 22px 18px; }
.cap { color: #7d8088; font-size: 9pt; font-weight: 600; letter-spacing: 3px; }
.brand { color: #7d8088; font-size: 10pt; font-weight: 300; letter-spacing: 6px; }
.status-main { font-size: 17pt; font-weight: 500; color: #ecebe8; }
.status-sub { font-size: 13pt; font-weight: 300; color: #9a9da4; }
.hint { color: #6a6d74; font-size: 9pt; font-weight: 300; }
.err { color: #e0776d; font-size: 11pt; }

button {
  background-color: #1d1f24;
  background-image: linear-gradient(to bottom, #262930, #1b1d22);
  color: #ecebe8; border: 1px solid rgba(255,255,255,0.07); border-radius: 22px;
  box-shadow: inset 0 1px rgba(255,255,255,0.06), 0 3px 10px rgba(0,0,0,0.35);
  text-shadow: none; -gtk-icon-shadow: none; outline: none;
  font-size: 13pt; font-weight: 500; padding: 8px 12px; min-height: 60px;
  transition: all 120ms ease-out;
}
button:hover { background-image: linear-gradient(to bottom, #2b2e36, #1f2127); }
button:active, button.pressed {
  background-image: linear-gradient(to bottom, #141519, #191b1f);
  box-shadow: inset 0 3px 8px rgba(0,0,0,0.7), 0 1px 2px rgba(0,0,0,0.3);
  border-color: rgba(255,255,255,0.03);
}
button.sel {
  background-image: linear-gradient(to bottom, #e2c48c, #b9965a);
  color: #1c160b; border-color: rgba(255,230,180,0.45);
  box-shadow: inset 0 1px rgba(255,255,255,0.35), 0 4px 16px rgba(217,185,126,0.25);
}
button.sel:active { background-image: linear-gradient(to bottom, #b9965a, #a7864f); }

button.power { min-width: 96px; min-height: 96px; border-radius: 48px; font-size: 24pt; padding: 0;
               color: #7d8088; }
button.power.on { color: #9fe0bd; border-color: rgba(120,220,170,0.35);
                  box-shadow: inset 0 1px rgba(255,255,255,0.06), 0 0 22px rgba(80,200,140,0.25); }

button.nav { min-height: 78px; font-size: 13pt; border-radius: 20px; }
button.scene { min-height: 118px; border-radius: 26px; }
.scene-title { font-size: 15pt; font-weight: 500; }
.scene-sub { font-size: 9pt; font-weight: 300; color: #9a9da4; }

button.vol { min-height: 230px; font-size: 44pt; font-weight: 200; border-radius: 30px; }
button.mute { min-height: 96px; font-size: 12pt; border-radius: 26px; }
button.mute.muted { background-image: linear-gradient(to bottom, #a8463e, #7f312b); color: #fff;
                    border-color: rgba(255,150,140,0.3); }
button.close { min-width: 54px; min-height: 54px; border-radius: 27px; padding: 0; font-size: 13pt;
               color: #7d8088; background-image: none; background-color: transparent;
               box-shadow: none; border-color: rgba(255,255,255,0.08); }

.seg { background-color: rgba(0,0,0,0.35); border-radius: 24px; padding: 6px;
       border: 1px solid rgba(255,255,255,0.05); }
.seg button { min-height: 66px; border-radius: 19px; background-image: none; background-color: transparent;
              border-color: transparent; box-shadow: none; color: #b9bcc2; font-size: 12pt; }
.seg button:active { background-color: rgba(255,255,255,0.06); }
.seg button.sel { background-image: linear-gradient(to bottom, #e2c48c, #b9965a); color: #1c160b;
                  box-shadow: 0 3px 12px rgba(217,185,126,0.25); }

.card { background-color: rgba(255,255,255,0.03); border-radius: 28px; padding: 22px;
        border: 1px solid rgba(255,255,255,0.05); }
.lv-name { font-size: 12pt; font-weight: 400; color: #d6d5d2; }
.lv-val { font-size: 14pt; font-weight: 500; min-width: 96px; color: #ecebe8; }
.lv-val.changed { color: #d9b97e; }
button.step { min-height: 62px; min-width: 62px; font-size: 11pt; border-radius: 18px; padding: 0 6px; }
button.step.big { color: #d9b97e; }
button.toggle-sm { min-height: 62px; min-width: 90px; border-radius: 18px; font-size: 11pt; }

.volnum { font-size: 62pt; font-weight: 200; color: #f2f1ee; }
.volcap { font-size: 9pt; font-weight: 600; letter-spacing: 4px; color: #7d8088; }
.volnum.muted { color: #8a8d94; }
button.topbtn { min-width: 76px; min-height: 76px; border-radius: 38px; padding: 0; font-size: 20pt;
                color: #b9bcc2; }
button.edit { min-width: 46px; min-height: 40px; border-radius: 14px; padding: 0 8px; font-size: 13pt;
              background-image: none; background-color: transparent; border-color: rgba(255,255,255,0.10);
              box-shadow: none; color: #b9a27a; }
button.chip { min-height: 58px; border-radius: 16px; font-size: 12pt; padding: 4px 8px; }
button.chip.tall { min-height: 86px; font-size: 14pt; }
.compact button { min-height: 62px; font-size: 11pt; }
entry { background-color: #15171b; color: #ecebe8; border: 1px solid rgba(255,255,255,0.12);
        border-radius: 16px; min-height: 58px; font-size: 15pt; padding: 0 18px; box-shadow: none; }
scale.geq trough { min-width: 12px; border-radius: 6px; background-color: rgba(255,255,255,0.08);
                   border: none; }
scale.geq highlight { background-image: linear-gradient(to top, #8a6c3c, #e2c48c); border-radius: 6px;
                      border: none; }
scale.geq slider { min-width: 46px; min-height: 46px; margin: -17px; border-radius: 23px; border: none;
                   background-image: linear-gradient(to bottom, #f6ead2, #d9b97e);
                   box-shadow: 0 3px 12px rgba(0,0,0,0.55); }
scale.geq mark indicator { min-width: 14px; min-height: 2px; color: rgba(255,255,255,0.35); }
.geq-val { font-size: 13pt; font-weight: 500; color: #ecebe8; }
.geq-val.changed { color: #d9b97e; }
.geq-freq { font-size: 10pt; color: #8a8d94; }
button.tone-btn { min-height: 110px; font-size: 30pt; font-weight: 200; border-radius: 28px; }
.tone-val { font-size: 30pt; font-weight: 300; color: #ecebe8; }
.tone-val.changed { color: #d9b97e; }
.volnum.glowing { color: #fff6e6; text-shadow: 0 0 18px rgba(217,185,126,0.95), 0 0 42px rgba(217,185,126,0.6); }
button.row { min-height: 0; border-radius: 20px; padding: 0 26px; font-size: 15pt; font-weight: 400;
             background-image: linear-gradient(to bottom, #202228, #1a1c21); }
button.row.cursor { border-color: rgba(217,185,126,0.55);
                    box-shadow: inset 4px 0 #d9b97e, 0 3px 10px rgba(0,0,0,0.35); }
button.row.empty { background-image: none; background-color: transparent; border-color: transparent;
                   box-shadow: none; }
button.ctl { min-height: 84px; min-width: 96px; font-size: 13pt; border-radius: 22px; }
button.ctl.icon { font-size: 20pt; }
.media-title { font-size: 19pt; font-weight: 500; color: #ecebe8; }
.media-pos { font-size: 12pt; font-weight: 300; color: #9a9da4; }
.media-off { font-size: 15pt; font-weight: 300; color: #9a9da4; }
list { background-color: transparent; }
list row { background-image: linear-gradient(to bottom, #202228, #1a1c21); border-radius: 20px;
           margin: 5px 6px; padding: 0 26px; min-height: 90px;
           border: 1px solid rgba(255,255,255,0.06); transition: all 120ms ease-out; }
list row:hover { background-image: linear-gradient(to bottom, #25282f, #1d1f24); }
list row:active { background-image: linear-gradient(to bottom, #141519, #191b1f);
                  box-shadow: inset 0 3px 8px rgba(0,0,0,0.7); }
list row.playing { border-color: rgba(217,185,126,0.55); box-shadow: inset 4px 0 #d9b97e; }
list row.playing .row-title { color: #d9b97e; }
list row.disabled { opacity: 0.4; }
.row-title { font-size: 15pt; font-weight: 400; color: #ecebe8; }
.row-sub { font-size: 11pt; font-weight: 300; color: #9a9da4; }
.row-chev { font-size: 22pt; font-weight: 200; color: #7d8088; }
.row-dur { font-size: 12pt; font-weight: 300; color: #9a9da4; }
.mini { background-color: rgba(255,255,255,0.035); border-radius: 26px; padding: 12px 14px;
        border: 1px solid rgba(217,185,126,0.25); }
.mini-title { font-size: 14pt; font-weight: 500; color: #ecebe8; }
.mini-sub { font-size: 11pt; font-weight: 300; color: #b9a27a; }
.np-title { font-size: 26pt; font-weight: 500; color: #f2f1ee; }
.np-artist { font-size: 17pt; font-weight: 300; color: #d9b97e; }
.np-album { font-size: 13pt; font-weight: 300; color: #9a9da4; }
.np-time { font-size: 13pt; font-weight: 400; color: #b9bcc2; }
.np-chip { font-size: 9pt; font-weight: 600; letter-spacing: 2px; color: #7d8088;
           border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 4px 12px; }
button.big-ctl { min-height: 120px; min-width: 150px; font-size: 30pt; border-radius: 30px; }
button.play { min-width: 190px; }
.toast { background-color: rgba(26,28,33,0.97); color: #f2f1ee; font-size: 15pt; font-weight: 500;
         border: 1px solid rgba(217,185,126,0.55); border-radius: 22px; padding: 20px 34px;
         box-shadow: 0 10px 40px rgba(0,0,0,0.6); }
.toast.warn { background-color: rgba(60,22,18,0.96); color: #ffe3dc;
              border-color: rgba(240,120,100,0.6); }
button.pad { min-width: 190px; min-height: 160px; font-size: 30pt; border-radius: 32px; }
popover { background-color: #1a1c21; border: 1px solid rgba(217,185,126,0.3); border-radius: 22px;
          box-shadow: 0 12px 40px rgba(0,0,0,0.6); }
button.popbtn { min-width: 250px; min-height: 76px; font-size: 14pt; }
button.mic { min-height: 110px; font-size: 30pt; border-radius: 30px; }
button.mic.listening { background-image: linear-gradient(to bottom, #e2c48c, #b9965a);
                       border-color: rgba(255,230,180,0.6);
                       box-shadow: 0 0 34px rgba(217,185,126,0.55); }
.wordmark { font-size: 20pt; font-weight: 300; letter-spacing: 12px; color: #d9b97e; }
.wordline { min-height: 1px; background-image: linear-gradient(to right, rgba(217,185,126,0), rgba(217,185,126,0.7)); }
scrollbar slider { min-width: 6px; background-color: rgba(255,255,255,0.15); border-radius: 3px; }
scrollbar { background-color: transparent; border: none; }
"""


# ---------- kleine Helfer ----------
def add_cls(w, *classes):
    ctx = w.get_style_context()
    for c in classes:
        ctx.add_class(c)
    return w


def set_cls(w, cls, on):
    ctx = w.get_style_context()
    (ctx.add_class if on else ctx.remove_class)(cls)


def label(text, *classes, xalign=0.5, markup=False):
    lb = Gtk.Label(xalign=xalign)
    lb.set_markup(text) if markup else lb.set_text(text)
    return add_cls(lb, *classes)


def button(text, cb, *classes):
    b = Gtk.Button(label=_(text))
    if cb:
        b.connect("clicked", lambda _b: cb())
    b.set_can_focus(False)
    return add_cls(b, *classes)


def segmented(items, cb, vertical=False):
    """Edle Segment-Leiste; items = [(wert, text)]. Gibt (box, {wert: button}) zurück."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                  spacing=4, homogeneous=True)
    add_cls(box, "seg")
    btns = {}
    for value, text in items:
        b = button(text, lambda v=value: cb(v))
        btns[value] = b
        box.pack_start(b, True, True, 0)
    return box, btns


def mark(btns, active):
    for v, b in btns.items():
        set_cls(b, "sel", v == active)


class HoldButton(Gtk.Button):
    """Knopf, der beim Gedrückthalten wiederholt auslöst (wie eine echte Fernbedienung)."""

    def __init__(self, text, cb, *classes):
        super().__init__(label=text)
        self.cb = cb
        self.timer = None
        self.set_can_focus(False)
        add_cls(self, *classes)
        self.connect("button-press-event", self.on_press)
        self.connect("button-release-event", self.on_release)
        self.connect("leave-notify-event", self.on_release)

    def on_press(self, *_):
        self.cb(True)        # True = neuer Druck
        self.stop()
        self.timer = GLib.timeout_add(450, self.start_repeat)
        set_cls(self, "pressed", True)
        return False

    def start_repeat(self):
        self.timer = GLib.timeout_add(170, self.repeat)
        return False

    def repeat(self):
        self.cb(False)       # False = Wiederholung beim Halten
        return True

    def stop(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None

    def on_release(self, *_):
        self.stop()
        set_cls(self, "pressed", False)
        return False


class Worker:
    """Schickt Befehle der Reihe nach an den Receiver (nichts geht verloren, nichts überholt sich)."""

    def __init__(self, on_error, on_idle):
        self.q = queue.Queue()
        self.on_error, self.on_idle = on_error, on_idle
        self.vol_pending = False
        threading.Thread(target=self.loop, daemon=True).start()

    def put(self, fn):
        self.q.put(fn)

    def loop(self):
        while True:
            fn = self.q.get()
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self.on_error, e)
            if self.q.empty():
                GLib.idle_add(self.on_idle)


SERVER = "http://127.0.0.1:8080"   # Hintergrunddienst (Bibliothek + Wiedergabe)


def api(path):
    r = json.loads(urllib.request.urlopen(SERVER + path, timeout=60).read())
    if isinstance(r, dict) and r.get("error"):
        raise RuntimeError(r["error"])
    return r


def in_bg(fn, done=None, err=None):
    def work():
        try:
            r = fn()
            if done:
                GLib.idle_add(done, r)
        except Exception as e:  # noqa: BLE001
            if err:
                GLib.idle_add(err, e)
    threading.Thread(target=work, daemon=True).start()


# ---------- Hauptfenster ----------
class App(Gtk.Window):
    def __init__(self):
        super().__init__(title="Marantz")
        here = Path(__file__).resolve().parent
        self.set_icon_from_file(str(here / "icon.svg"))
        self.set_default_size(1500, 1000)
        self.st, self.cfg = {}, {}
        self.vol_shown = None        # angezeigte Lautstärke
        self.vol_target = None       # Ziel beim schnellen Tippen/Halten
        self.vol_local_until = 0.0   # bis dahin Status-Lautstärke ignorieren
        self.reload_settings = False
        self.worker = Worker(self.show_err, self.after_commands)

        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        outer = Gtk.Box(spacing=26)
        outer.set_border_width(26)
        top_ov = Gtk.Overlay()
        top_ov.add(outer)
        self.toast_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE,
                                      transition_duration=250)
        self.toast_rev.set_halign(Gtk.Align.CENTER)
        self.toast_rev.set_valign(Gtk.Align.START)
        self.toast_rev.set_margin_top(40)
        self.toast_lbl = label("", "toast")
        self.toast_lbl.set_justify(Gtk.Justification.CENTER)
        self.toast_rev.add(self.toast_lbl)
        top_ov.add_overlay(self.toast_rev)
        top_ov.set_overlay_pass_through(self.toast_rev, True)
        self.toast_timer = None
        self.add(top_ov)
        outer.pack_start(self.build_left(), False, False, 0)
        outer.pack_start(self.build_center(), True, True, 0)
        outer.pack_start(self.build_right(), False, False, 0)

        self.voice_proc, self.voice_busy, self.voice_last = None, False, time.time()
        GLib.timeout_add_seconds(60, self.voice_idle_check)
        self.connect("destroy", self.on_destroy)
        self.connect("key-press-event", self.on_key)
        # Mauszeiger: bei Touch unsichtbar, bei Touchpad/Maus kurz sichtbar
        self.cursor_timer = None
        self.connect("realize", lambda *_: self.hide_cursor())
        Gdk.event_handler_set(self.on_any_event, None)
        self.fullscreen()
        self.is_full = True
        self.show_page("main")
        self.refresh()
        in_bg(m.model_name, lambda n: self.model_lbl.set_text(n.upper()), lambda e: None)
        GLib.timeout_add_seconds(3, self.tick)
        GLib.timeout_add(1000, self.media_tick)

    # ----- linke Leiste -----
    def build_left(self):
        rail = add_cls(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14), "rail")
        rail.set_size_request(260, -1)

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        top.set_halign(Gtk.Align.CENTER)
        self.model_lbl = label("MARANTZ", "brand")          # wird durch das echte Modell ersetzt
        top.pack_start(self.model_lbl, False, False, 0)
        self.power_btn = button("⏻", self.toggle_power, "power")
        self.power_btn.set_halign(Gtk.Align.CENTER)
        top.pack_start(self.power_btn, False, False, 0)
        self.power_lbl = label("–", "status-sub")
        top.pack_start(self.power_lbl, False, False, 0)
        rail.pack_start(top, False, False, 0)

        rail.pack_start(Gtk.Box(), True, True, 0)  # Abstand: Bedienung liegt im Daumenbereich

        nav, self.nav_btns = segmented([("main", "Bedienung"), ("sound", "Klang & Pegel"),
                                        ("eq", "EQ"), ("media", "Mediathek")],
                                       self.show_page, vertical=True)
        for b in self.nav_btns.values():
            add_cls(b, "nav")
        rail.pack_start(nav, False, False, 0)

        cap = Gtk.Box()
        cap.pack_start(label("SZENEN", "cap", xalign=0), True, True, 0)
        cap.pack_start(button("✎", self.open_scene_editor, "edit"), False, False, 0)
        rail.pack_start(cap, False, False, 10)
        self.scene_btns = []
        for idx in range(3):
            b = Gtk.Button()
            b.set_can_focus(False)
            add_cls(b, "scene")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            inner.set_valign(Gtk.Align.CENTER)
            inner.set_halign(Gtk.Align.CENTER)
            t = label("", "scene-title")
            t.set_ellipsize(3)
            t.set_max_width_chars(14)
            sub = label("", "scene-sub")
            inner.pack_start(t, False, False, 0)
            inner.pack_start(sub, False, False, 0)
            b.add(inner)
            b.connect("clicked", lambda _b, k=idx: self.run_profile(k))
            self.scene_btns.append((t, sub))
            rail.pack_start(b, False, False, 0)
        rail.pack_start(Gtk.Box(), False, False, 24)
        self.refresh_scenes()
        return rail

    # ----- rechte Leiste -----
    def build_right(self):
        rail = add_cls(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14), "rail")
        rail.set_size_request(230, -1)
        top = Gtk.Box(spacing=22, homogeneous=True)
        top.set_halign(Gtk.Align.CENTER)
        top.pack_start(button("⚙", self.open_setup, "topbtn"), False, False, 0)
        top.pack_start(button("✕", Gtk.main_quit, "topbtn"), False, False, 0)
        rail.pack_start(top, False, False, 0)
        rail.pack_start(Gtk.Box(), True, True, 0)
        self.mic_btn = None
        if i18n.LANG == "de" and os.path.isdir(os.path.join(VOICE_DIR, "model")):
            self.mic_btn = button("🎤", self.voice_press, "mic")
            rail.pack_start(self.mic_btn, False, False, 0)
            rail.pack_start(label("SPRECHEN", "cap"), False, False, 0)
            rail.pack_start(Gtk.Box(), False, False, 14)
        rail.pack_start(label("LAUTSTÄRKE", "cap"), False, False, 6)
        rail.pack_start(HoldButton("+", lambda first: self.vol_step(+1, first), "vol"), False, False, 0)
        rail.pack_start(HoldButton("−", lambda first: self.vol_step(-1, first), "vol"), False, False, 0)
        self.mute_btn = button("Stumm", self.toggle_mute, "mute")
        rail.pack_start(self.mute_btn, False, False, 6)
        rail.pack_start(Gtk.Box(), False, False, 30)
        return rail

    # ----- Mitte -----
    def build_center(self):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.status_main = label("verbinde …", "status-main", xalign=0)
        self.status_sub = label("", "status-sub", xalign=0)
        head.pack_start(self.status_main, False, False, 0)
        head.pack_start(self.status_sub, False, False, 0)
        top = Gtk.Box(spacing=20)
        head_ev = Gtk.EventBox()
        head_ev.add(head)
        head_ev.connect("button-release-event", lambda *_: self.open_input_pop())
        self.input_pop = Gtk.Popover(relative_to=self.status_main, position=Gtk.PositionType.BOTTOM)
        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        pop_box.set_border_width(14)
        pop_box.pack_start(label("EINGANG WÄHLEN", "cap", xalign=0), False, False, 4)
        self.pop_grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        pop_box.pack_start(self.pop_grid, False, False, 0)
        pop_box.show_all()
        self.input_pop.add(pop_box)
        self.all_sources = [("SI" + c, m.SOURCE_NAMES[c]) for c in m.SOURCE_ORDER]
        top.pack_start(head_ev, False, False, 0)
        top.pack_start(Gtk.Box(), True, True, 0)
        mark_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        mark_box.set_valign(Gtk.Align.CENTER)
        mark_box.pack_start(label("MARANTZ", "wordmark", xalign=1), False, False, 0)
        mark_box.pack_start(add_cls(Gtk.Box(), "wordline"), False, False, 0)
        top.pack_start(mark_box, False, False, 6)
        col.pack_start(top, False, False, 4)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=180)
        self.stack.add_named(self.build_main(), "main")
        self.stack.add_named(self.build_sound(), "sound")
        self.stack.add_named(self.build_eq(), "eq")
        self.stack.add_named(self.build_media(), "media")
        self.stack.add_named(self.build_setup(), "setup")
        self.stack.add_named(self.build_scene_editor(), "edit_scenes")
        self.stack.add_named(self.build_input_editor(), "edit_inputs")
        col.pack_start(self.stack, True, True, 0)

        self.err_lbl = label("", "err")
        col.pack_start(self.err_lbl, False, False, 0)
        return col

    def build_main(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        ov = Gtk.Overlay()
        self.ring = Gtk.DrawingArea()
        self.ring.set_size_request(-1, 380)
        self.ring.connect("draw", self.draw_ring)
        # Ring als Drehregler: Finger auflegen und im Kreis bewegen
        self.ring_drag = None
        self.ring.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.BUTTON1_MOTION_MASK)
        self.ring.connect("button-press-event", self.on_ring_press)
        self.ring.connect("motion-notify-event", self.on_ring_motion)
        self.ring.connect("button-release-event", self.on_ring_release)
        ov.add(self.ring)
        mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        mid.set_halign(Gtk.Align.CENTER)
        self.ring_mid = mid
        mid.set_valign(Gtk.Align.START)
        # Zahl genau in die (tiefer liegende) Ringmitte: Abstand nach dem Verteilen der Größen setzen
        self.ring.connect("size-allocate", lambda w, a: GLib.idle_add(self.place_ring_mid))
        self.vol_lbl = label("–", "volnum")
        self.vol_cap = label("LAUTSTÄRKE", "volcap")
        mid.pack_start(self.vol_lbl, False, False, 0)
        mid.pack_start(self.vol_cap, False, False, 0)
        ov.add_overlay(mid)
        page.pack_start(ov, True, True, 0)

        cap = Gtk.Box()
        ph = Gtk.Box()
        ph.set_size_request(46, -1)                      # Platzhalter = Breite von ✎ → echte Mitte
        cap.pack_start(ph, False, False, 0)
        cap.pack_start(label("EINGANG", "cap"), True, True, 0)
        cap.pack_start(button("✎", self.open_input_editor, "edit"), False, False, 0)
        page.pack_start(cap, False, False, 0)
        self.in_holder = Gtk.Box()
        page.pack_start(self.in_holder, False, False, 0)
        self.in_btns = {}
        self.refresh_inputs()
        page.pack_start(label("SOUND MODE", "cap"), False, False, 6)
        seg, self.group_btns = segmented(m.MODE_GROUPS, self.group_press)
        add_cls(seg, "compact")
        page.pack_start(seg, False, False, 0)
        page.pack_start(label("KLANGMODUS", "cap"), False, False, 6)
        seg, self.mode_btns = segmented([(c, t) for c, t, _ in m.MODES], self.cmd)
        add_cls(seg, "compact")
        page.pack_start(seg, False, False, 0)
        return page

    def build_sound(self):
        page = Gtk.Box(spacing=20)

        au = add_cls(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        au.pack_start(label("AUDYSSEY", "cap", xalign=0), False, False, 0)

        def section(title, items, prefix_fn):
            au.pack_start(label(title, "status-sub", xalign=0), False, False, 6)
            seg, btns = segmented(items, lambda v: self.set_cmd(prefix_fn(v)))
            au.pack_start(seg, False, False, 0)
            return btns

        self.multeq_btns = section("MultEQ", [("AUDYSSEY", "Audyssey"), ("BYP.LR", "Byp. L/R"),
                                              ("FLAT", "Flat"), ("OFF", "Aus")],
                                   lambda v: "PSMULTEQ:" + v)
        self.dyneq_btns = section("Dynamic EQ", [(True, "Ein"), (False, "Aus")],
                                  lambda v: "PSDYNEQ " + ("ON" if v else "OFF"))
        self.reflev_btns = section("Referenzpegel-Offset", [("0", "0 dB"), ("5", "5 dB"),
                                                            ("10", "10 dB"), ("15", "15 dB")],
                                   lambda v: "PSREFLEV " + v)
        self.dynvol_btns = section("Dynamic Volume", [("OFF", "Aus"), ("LIT", "Leicht"),
                                                      ("MED", "Mittel"), ("HEV", "Stark")],
                                   lambda v: "PSDYNVOL " + v)
        self.cinema_btns = section("Cinema EQ", [(True, "Ein"), (False, "Aus")],
                                   lambda v: "PSCINEMA EQ." + ("ON" if v else "OFF"))
        h = label("In Direct und Pure Direct schaltet der Receiver Audyssey und Cinema EQ ab.",
                  "hint", xalign=0)
        h.set_line_wrap(True)
        au.pack_start(h, False, False, 10)

        page.pack_start(au, True, True, 0)

        lv = add_cls(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        lv.pack_start(label("PEGEL", "cap", xalign=0), False, False, 0)
        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        r = Gtk.Box(spacing=8)
        name = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        name.set_valign(Gtk.Align.CENTER)
        name.pack_start(label("Subwoofer-Pegel", "lv-name", xalign=0), False, False, 0)
        name.pack_start(label("Schnellanpassung", "hint", xalign=0), False, False, 0)
        r.pack_start(name, True, True, 0)
        self.swl_onoff = button("Ein", lambda: self.set_cmd(
            "PSSWL " + ("OFF" if self.cfg.get("swl_on") else "ON")), "toggle-sm")
        r.pack_start(self.swl_onoff, False, False, 0)
        rows.pack_start(r, False, False, 0)
        r = Gtk.Box(spacing=8)
        r.pack_start(Gtk.Box(), True, True, 0)
        self.swl_val = self.steppers(r, lambda d: self.step_level("PSSWL ", None, d))
        rows.pack_start(r, False, False, 0)
        rows.pack_start(add_cls(Gtk.Separator(), "hint"), False, False, 4)

        self.ch_vals = {}
        for code, cname in m.CHANNELS:
            r = Gtk.Box(spacing=8)
            r.pack_start(label(cname, "lv-name", xalign=0), True, True, 0)
            self.ch_vals[code] = self.steppers(
                r, lambda d, c=code: self.step_level(f"CV{c} ", c, d))
            rows.pack_start(r, False, False, 0)

        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sc.set_kinetic_scrolling(True)
        sc.add(rows)
        lv.pack_start(sc, True, True, 0)
        page.pack_start(lv, False, False, 0)
        return page

    # ----- Musik-Seite: Plex-Bibliothek + Wiedergabe (über den Hintergrunddienst) -----
    def build_media(self):
        self.lib_path = [("0", "Bibliothek")]
        self.lib_items, self.lib_total, self.lib_loading = [], 0, False
        self.pl = {}
        self.art_cache = {}
        self.art_pb = None
        self.art_url = None

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.media_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                                     transition_duration=150)

        lib = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        head = Gtk.Box(spacing=16)
        self.lib_back = button("‹  Zurück", self.lib_up, "ctl")
        head.pack_start(self.lib_back, False, False, 0)
        self.media_title = label("Bibliothek", "media-title", xalign=0)
        self.media_title.set_ellipsize(3)
        head.pack_start(self.media_title, True, True, 0)
        self.media_pos = label("", "media-pos", xalign=1)
        head.pack_start(self.media_pos, False, False, 0)
        lib.pack_start(head, False, False, 0)

        self.lib_list = Gtk.ListBox()
        self.lib_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.lib_list.set_activate_on_single_click(True)
        self.lib_list.connect("row-activated", self.on_row)
        self.lib_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.lib_scroll.set_kinetic_scrolling(True)
        self.lib_scroll.add(self.lib_list)
        self.lib_scroll.get_vadjustment().connect("value-changed", self.on_lib_scroll)
        lib.pack_start(self.lib_scroll, True, True, 0)
        self.media_stack.add_named(lib, "list")
        self.media_stack.add_named(self.build_now(), "now")
        outer.pack_start(self.media_stack, True, True, 0)
        outer.pack_start(self.build_mini(), False, False, 0)
        self.media_stack.connect("notify::visible-child", lambda *_: self.pl_render())
        return outer

    def build_mini(self):
        """Mini-Player unten: immer sichtbar, solange etwas in der Warteschlange ist."""
        self.mini = add_cls(Gtk.Box(spacing=18), "mini")
        tap = Gtk.EventBox()
        tap.connect("button-release-event", lambda *_: self.media_stack.set_visible_child_name("now"))
        inner = Gtk.Box(spacing=18)
        self.mini_cover = Gtk.DrawingArea()
        self.mini_cover.set_size_request(84, 84)
        self.mini_cover.connect("draw", lambda w, cr: self.draw_art(w, cr, 14))
        inner.pack_start(self.mini_cover, False, False, 0)
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        txt.set_valign(Gtk.Align.CENTER)
        self.mini_title = label("", "mini-title", xalign=0)
        self.mini_title.set_ellipsize(3)
        self.mini_sub = label("", "mini-sub", xalign=0)
        self.mini_sub.set_ellipsize(3)
        txt.pack_start(self.mini_title, False, False, 0)
        txt.pack_start(self.mini_sub, False, False, 0)
        inner.pack_start(txt, True, True, 0)
        tap.add(inner)
        self.mini.pack_start(tap, True, True, 0)
        self.mini_play = button("⏸", lambda: self.ctl("toggle"), "ctl", "icon")
        for txt_, act in (("⏮", "prev"), (None, "toggle"), ("⏹", "stop"), ("⏭", "next")):
            b = self.mini_play if txt_ is None else button(txt_, lambda a=act: self.ctl(a), "ctl", "icon")
            self.mini.pack_start(b, False, False, 0)
        self.mini_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
                                     transition_duration=220)
        self.mini_rev.add(self.mini)
        return self.mini_rev

    def build_now(self):
        """Große Ansicht „Jetzt läuft“."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        head = Gtk.Box(spacing=16)
        head.pack_start(button("‹  Bibliothek", lambda: self.media_stack.set_visible_child_name("list"),
                               "ctl"), False, False, 0)
        head.pack_start(label("Jetzt läuft", "media-title", xalign=0), True, True, 0)
        self.np_track = label("", "media-pos", xalign=1)
        head.pack_start(self.np_track, False, False, 0)
        page.pack_start(head, False, False, 0)

        body = Gtk.Box(spacing=40)
        self.np_cover = Gtk.DrawingArea()
        self.np_cover.set_size_request(440, 440)
        self.np_cover.connect("draw", lambda w, cr: self.draw_art(w, cr, 26))
        body.pack_start(self.np_cover, False, False, 0)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        info.set_valign(Gtk.Align.CENTER)
        self.np_title = label("–", "np-title", xalign=0)
        self.np_title.set_line_wrap(True)
        self.np_title.set_lines(3)
        self.np_title.set_ellipsize(3)
        self.np_artist = label("", "np-artist", xalign=0)
        self.np_artist.set_ellipsize(3)
        self.np_album = label("", "np-album", xalign=0)
        self.np_album.set_ellipsize(3)
        for w in (self.np_title, self.np_artist, self.np_album):
            info.pack_start(w, False, False, 0)
        body.pack_start(info, True, True, 0)
        page.pack_start(body, True, True, 0)

        bar_box = Gtk.EventBox()
        bar_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        bar_box.connect("button-press-event", self.on_bar_press)
        self.np_bar = Gtk.DrawingArea()
        self.np_bar.set_size_request(-1, 44)
        self.np_bar.connect("draw", self.draw_progress)
        bar_box.add(self.np_bar)
        page.pack_start(bar_box, False, False, 0)
        times = Gtk.Box()
        self.np_elapsed = label("0:00", "np-time", xalign=0)
        self.np_total = label("", "np-time", xalign=1)
        times.pack_start(self.np_elapsed, True, True, 0)
        times.pack_start(label("Zum Spulen auf den Balken tippen", "hint"), True, True, 0)
        times.pack_start(self.np_total, True, True, 0)
        page.pack_start(times, False, False, 0)

        ctl = Gtk.Box(spacing=22)
        ctl.set_halign(Gtk.Align.CENTER)
        ctl.pack_start(button("⏮", lambda: self.ctl("prev"), "big-ctl"), False, False, 0)
        self.np_play = button("⏸", lambda: self.ctl("toggle"), "big-ctl", "play", "sel")
        ctl.pack_start(self.np_play, False, False, 0)
        ctl.pack_start(button("⏹", lambda: self.ctl("stop"), "big-ctl"), False, False, 0)
        ctl.pack_start(button("⏭", lambda: self.ctl("next"), "big-ctl"), False, False, 0)
        page.pack_start(ctl, False, False, 8)
        return page

    # ----- Bibliothek -----
    def lib_open(self, oid, title, push=True):
        if push:
            self.lib_path.append((oid, title))
        self.lib_items, self.lib_total = [], 0
        for r in self.lib_list.get_children():
            self.lib_list.remove(r)
        self.media_title.set_text(tr(title))
        self.media_pos.set_text("lädt …")
        self.lib_back.set_sensitive(len(self.lib_path) > 1)
        self.lib_scroll.get_vadjustment().set_value(0)
        self.lib_more()

    def lib_more(self):
        if self.lib_loading:
            return
        oid = self.lib_path[-1][0]
        start = len(self.lib_items)
        self.lib_loading = True

        def done(r):
            self.lib_loading = False
            if self.lib_path[-1][0] != oid:
                return
            self.lib_total = r["total"]
            for it in r["items"]:
                self.lib_items.append(it)
                self.lib_list.add(self.lib_row(it))
            self.lib_list.show_all()
            n = self.lib_total
            self.media_pos.set_text("leer" if not n else _("{} Einträge").format(n) if n != 1 else "1 Eintrag")
            self.mark_playing()

        def fail(e):
            self.lib_loading = False
            self.media_pos.set_text("")
            self.show_err(e)
        in_bg(lambda: api(f"/api/lib?id={urllib.parse.quote(oid)}&start={start}&count=150"),
              done, fail)

    def lib_row(self, it):
        row = Gtk.ListBoxRow()
        row.item = it
        box = Gtk.Box(spacing=16)
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        txt.set_valign(Gtk.Align.CENTER)
        t = label(tr(it["title"]), "row-title", xalign=0)
        t.set_ellipsize(3)
        txt.pack_start(t, False, False, 0)
        sub = it.get("artist") if it["kind"] == "track" else ""
        if it["kind"] == "other":
            sub = "nicht abspielbar"
        if sub:
            s_ = label(sub, "row-sub", xalign=0)
            s_.set_ellipsize(3)
            txt.pack_start(s_, False, False, 0)
        box.pack_start(txt, True, True, 0)
        if it["kind"] == "folder":
            box.pack_start(label("›", "row-chev"), False, False, 0)
        elif it["kind"] == "track":
            box.pack_start(label(self.fmt_time(it.get("duration")), "row-dur"), False, False, 0)
        else:
            add_cls(row, "disabled")
        row.add(box)
        return row

    def on_lib_scroll(self, adj):
        if adj.get_value() + adj.get_page_size() > adj.get_upper() - 600 and \
                len(self.lib_items) < self.lib_total:
            self.lib_more()

    def lib_up(self):
        if len(self.lib_path) > 1:
            self.lib_path.pop()
            oid, title = self.lib_path[-1]
            self.lib_open(oid, title, push=False)

    def on_row(self, _lb, row):
        it = row.item
        if it["kind"] == "folder":
            self.lib_open(it["id"], it["title"])
        elif it["kind"] == "track":
            parent = self.lib_path[-1][0]
            self.pl.update(id=it["id"], title=it["title"], artist=it.get("artist"),
                           album=it.get("album"), art=it.get("art"), state="PLAYING",
                           elapsed=0, duration=it.get("duration"), active=True,
                           index=None, count=None)
            # Ein paar Sekunden lang alte Statusmeldungen ignorieren, bis der Titel wirklich läuft
            self.pl_hold_until = time.time() + 6
            self.media_stack.set_visible_child_name("now")   # sofort Cover, Zeit, Spulen zeigen
            self.pl_render()
            self.worker.put(lambda: api(f"/api/play?parent={urllib.parse.quote(parent)}"
                                        f"&item={urllib.parse.quote(it['id'])}"))

    def mark_playing(self):
        pid = self.pl.get("id") if self.pl.get("active") else None
        for row in self.lib_list.get_children():
            set_cls(row, "playing", row.item.get("id") == pid)

    # ----- Wiedergabe -----
    def ctl(self, action, t=None):
        if action == "toggle":
            self.pl["state"] = "PAUSED_PLAYBACK" if self.pl.get("state") == "PLAYING" else "PLAYING"
        elif action == "stop":
            self.pl.update(state="STOPPED", active=False)
        self.pl_render()
        q = f"/api/ctl?a={action}" + (f"&t={int(t)}" if t is not None else "")
        self.worker.put(lambda: api(q))

    def on_bar_press(self, w, ev):
        d = self.pl.get("duration")
        if not d or not self.pl.get("active"):
            return False
        W = w.get_allocated_width()
        frac = max(0.0, min(1.0, (ev.x - 12) / max(1, W - 24)))
        self.pl["elapsed"] = int(d * frac)
        self.pl_render()
        self.ctl("seek", d * frac)
        return True

    def media_tick(self):
        if self.stack.get_visible_child_name() == "media" and not self.is_minimized():
            in_bg(lambda: api("/api/player"), self.on_player, lambda e: None)
        return True

    def media_refresh(self):
        if not self.lib_items and not self.lib_loading:
            self.lib_open(*self.lib_path[-1], push=False)
        self.media_tick()

    def on_player(self, pl):
        hold = getattr(self, "pl_hold_until", 0)
        if time.time() < hold and pl.get("id") != self.pl.get("id"):
            return   # Dienst meldet noch den alten Titel – gleich nochmal fragen
        if time.time() < hold and pl.get("state") != "PLAYING":
            pl = dict(pl, state="PLAYING")
        self.pl = pl
        self.pl_render()

    def pl_render(self):
        pl = self.pl
        has = bool(pl.get("title")) and pl.get("count", 1) and (pl.get("active") or pl.get("title"))
        self.mini_rev.set_reveal_child(bool(has) and self.media_stack.get_visible_child_name() == "list")
        playing = pl.get("state") == "PLAYING"
        for b in (self.mini_play, self.np_play):
            b.set_label("⏸" if playing else "▶")
            set_cls(b, "sel", playing)
        title = pl.get("title") or "–"
        self.mini_title.set_text(title)
        tm = f"{self.fmt_time(pl.get('elapsed') or 0)} / {self.fmt_time(pl.get('duration'))}"
        state = _({"PLAYING": "", "PAUSED_PLAYBACK": "Pause · ", "STOPPED": "Gestoppt · ",
                   "TRANSITIONING": "lädt … · "}.get(pl.get("state", ""), ""))
        self.mini_sub.set_text(f"{state}{pl.get('artist') or ''}  ·  {tm}")
        self.np_title.set_text(title)
        self.np_artist.set_text(pl.get("artist") or "")
        self.np_album.set_text(tr(pl.get("album") or ""))
        self.np_track.set_text(_("Titel {} von {}").format(pl["index"], pl["count"]) if pl.get("count") else "")
        self.np_elapsed.set_text(self.fmt_time(pl.get("elapsed") or 0))
        self.np_total.set_text(self.fmt_time(pl.get("duration")))
        self.np_bar.queue_draw()
        self.load_art(pl.get("art"))
        self.mark_playing()

    def load_art(self, url):
        if url and not url.lower().startswith(("http://", "https://")):
            url = None            # Sicherheit: nur echte Webadressen laden
        if url == self.art_url:
            return
        self.art_url = url
        if not url:
            self.art_pb = None
            self.mini_cover.queue_draw()
            self.np_cover.queue_draw()
            return
        if url in self.art_cache:
            self.art_pb = self.art_cache[url]
            self.mini_cover.queue_draw()
            self.np_cover.queue_draw()
            return

        def fetch():
            data = urllib.request.urlopen(url, timeout=6).read()
            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            pb = loader.get_pixbuf()
            s = 480 / max(pb.get_width(), pb.get_height())
            return pb.scale_simple(int(pb.get_width() * s), int(pb.get_height() * s),
                                   GdkPixbuf.InterpType.BILINEAR)

        def done(pb):
            if len(self.art_cache) > 30:
                self.art_cache.clear()
            self.art_cache[url] = pb
            if self.art_url == url:
                self.art_pb = pb
                self.mini_cover.queue_draw()
                self.np_cover.queue_draw()
        in_bg(fetch, done, lambda e: None)

    @staticmethod
    def fmt_time(sec):
        if sec is None:
            return "–:––"
        h, rest = divmod(int(sec), 3600)
        mi, se = divmod(rest, 60)
        return f"{h}:{mi:02d}:{se:02d}" if h else f"{mi}:{se:02d}"

    def draw_art(self, w, cr, r):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        size = min(W, H)
        x, y = (W - size) / 2, (H - size) / 2
        cr.new_sub_path()
        cr.arc(x + size - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + size - r, y + size - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + size - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.clip()
        pb = self.art_pb
        if pb:
            sc = pb.scale_simple(int(size), int(size), GdkPixbuf.InterpType.BILINEAR)
            Gdk.cairo_set_source_pixbuf(cr, sc, x, y)
            cr.paint()
        else:
            g = cairo.LinearGradient(x, y, x + size, y + size)
            g.add_color_stop_rgb(0, 0.15, 0.16, 0.19)
            g.add_color_stop_rgb(1, 0.08, 0.09, 0.10)
            cr.set_source(g)
            cr.paint()
            cr.set_source_rgba(*GOLD, 0.5)
            cr.select_font_face("Ubuntu Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(size * 0.3)
            ext = cr.text_extents("♪")
            cr.move_to(x + size / 2 - ext.width / 2 - ext.x_bearing,
                       y + size / 2 - ext.height / 2 - ext.y_bearing)
            cr.show_text("♪")
        return False

    def draw_progress(self, w, cr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        cy, pad = H / 2, 12
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(8)
        cr.set_source_rgba(1, 1, 1, 0.08)
        cr.move_to(pad, cy)
        cr.line_to(W - pad, cy)
        cr.stroke()
        e, d = self.pl.get("elapsed"), self.pl.get("duration")
        if e is None or not d:
            return False
        x1 = pad + (W - 2 * pad) * max(0.0, min(1.0, e / d))
        g = cairo.LinearGradient(pad, 0, W - pad, 0)
        g.add_color_stop_rgb(0, *GOLD_DEEP)
        g.add_color_stop_rgb(1, *GOLD)
        cr.set_source(g)
        cr.move_to(pad, cy)
        cr.line_to(x1, cy)
        cr.stroke()
        cr.set_source_rgb(0.96, 0.92, 0.84)
        cr.arc(x1, cy, 12, 0, 2 * math.pi)
        cr.fill()
        return False

    def open_input_pop(self):
        self.fill_input_pop()
        self.input_pop.popup()
        # Namen/Auswahl frisch vom Receiver holen (eigene Namen, nur benutzte Quellen)
        in_bg(m.sources, lambda lst: (setattr(self, "all_sources", lst), self.fill_input_pop()),
              lambda e: None)

    def fill_input_pop(self):
        for c in self.pop_grid.get_children():
            self.pop_grid.remove(c)
        cur = self.st.get("input", "").lower().replace(" ", "")
        for i, (code, name) in enumerate(self.all_sources):
            b = button(name, lambda c=code: (self.input_pop.popdown(), self.select_input(c)), "popbtn")
            set_cls(b, "sel", name.lower().replace(" ", "") == cur)
            self.pop_grid.attach(b, i % 3, i // 3, 1, 1)
        self.pop_grid.show_all()
        return False

    def select_input(self, code):
        self.cmd(code)
        if code == "SISERVER":
            self.show_page("media")

    # ----- Sound-Mode-Gruppe (Film/Musik/Spiel/Pure) -----
    def group_press(self, code):
        mark(self.group_btns, code)            # sofort leuchten lassen
        self.cmd(code)
        GLib.timeout_add(1500, self.group_refresh)

    def group_refresh(self):
        surround = self.st.get("surround", "")
        in_bg(lambda: m.sound_group(surround), lambda g: mark(self.group_btns, g) or False,
              lambda e: None)
        return False

    # ----- Frei belegbare Szenen -----
    def refresh_scenes(self):
        self.config = m.load_config()
        for (t, sub), p in zip(self.scene_btns, self.config["profiles"]):
            t.set_text(p.get("name") or "Szene")
            sub.set_text(m.profile_subtitle(p))

    def run_profile(self, idx):
        p = self.config["profiles"][idx]
        self.status_sub.set_text(_("Szene „{}“ wird eingestellt …").format(_(p.get("name", ""))))
        self.worker.put(lambda: m.run_profile(p))

    def chip_grid(self, items, cols, cb):
        """Raster aus Auswahl-Knöpfen; items = [(wert, text)] → (grid, {wert: button})"""
        g = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        btns = {}
        for n, (v, t) in enumerate(items):
            b = button(t, lambda v=v: cb(v), "chip")
            btns[v] = b
            g.attach(b, n % cols, n // cols, 1, 1)
        return g, btns

    def build_scene_editor(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        head = Gtk.Box(spacing=16)
        head.pack_start(label("Szenen bearbeiten", "media-title", xalign=0), False, False, 0)
        tabs, self.pe_tabs = segmented([(0, "1"), (1, "2"), (2, "3")], self.pe_select)
        tabs.set_size_request(330, -1)
        head.pack_end(tabs, False, False, 0)
        page.pack_start(head, False, False, 0)

        row = Gtk.Box(spacing=12)
        self.pe_name = Gtk.Entry(placeholder_text=_("Name der Szene"))
        self.pe_name.set_max_length(24)
        self.pe_name.connect("changed", lambda e: self.pe_set("name", e.get_text().strip()))
        row.pack_start(self.pe_name, True, True, 0)
        row.pack_start(button("Aktuellen Zustand übernehmen", self.pe_capture, "chip", "sel"),
                       False, False, 0)
        page.pack_start(row, False, False, 0)

        page.pack_start(label("Was soll passieren?", "status-sub", xalign=0), False, False, 0)
        seg, self.pe_power = segmented([("on", "Einschalten & einstellen"),
                                        ("off", "Ausschalten (Standby)")],
                                       lambda v: (self.pe_set("power", v), self.pe_render()))
        add_cls(seg, "compact")
        page.pack_start(seg, False, False, 0)

        self.pe_detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.pe_detail.pack_start(label("Eingang", "status-sub", xalign=0), False, False, 0)
        srcs = [(None, "unverändert")] + [("SI" + c, m.SOURCE_NAMES[c]) for c in m.SOURCE_ORDER]
        g, self.pe_in = self.chip_grid(srcs, 6, lambda v: (self.pe_set("input", v), self.pe_render()))
        self.pe_detail.pack_start(g, False, False, 0)
        self.pe_detail.pack_start(label("Klangmodus", "status-sub", xalign=0), False, False, 0)
        modes = [(None, "unverändert")] + [(c, t) for c, t, _ in m.MODES]
        g, self.pe_mode = self.chip_grid(modes, 5, lambda v: (self.pe_set("mode", v), self.pe_render()))
        self.pe_detail.pack_start(g, False, False, 0)
        self.pe_detail.pack_start(label("Lautstärke", "status-sub", xalign=0), False, False, 0)
        vr = Gtk.Box(spacing=8)
        self.pe_vol_keep = button("unverändert", lambda: (self.pe_set("volume", None), self.pe_render()),
                                  "chip")
        vr.pack_start(self.pe_vol_keep, True, True, 0)
        for d in (-5, -1):
            vr.pack_start(button(("%+d" % d).replace("-", "−"), lambda d=d: self.pe_vol(d), "chip"),
                          True, True, 0)
        self.pe_vol_lbl = label("–", "tone-val")
        vr.pack_start(self.pe_vol_lbl, True, True, 0)
        for d in (1, 5):
            vr.pack_start(button("%+d" % d, lambda d=d: self.pe_vol(d), "chip"), True, True, 0)
        self.pe_detail.pack_start(vr, False, False, 0)
        page.pack_start(self.pe_detail, False, False, 0)

        page.pack_start(Gtk.Box(), True, True, 0)
        foot = Gtk.Box(spacing=14, homogeneous=True)
        foot.pack_start(button("Abbrechen", lambda: self.show_page("main"), "chip"), True, True, 0)
        foot.pack_start(button("Speichern", self.pe_save, "chip", "sel"), True, True, 0)
        page.pack_start(foot, False, False, 0)
        self.pe = {"idx": 0, "profiles": [], "loading": False}
        return page

    def open_scene_editor(self):
        import copy
        self.pe["profiles"] = copy.deepcopy(m.load_config()["profiles"])
        self.show_page("edit_scenes")
        self.pe_select(0)

    def pe_select(self, idx):
        self.pe["idx"] = idx
        self.pe["loading"] = True
        self.pe_name.set_text(self.pe["profiles"][idx].get("name", ""))
        self.pe["loading"] = False
        self.pe_render()

    def pe_set(self, key, value):
        if self.pe.get("loading"):
            return
        p = self.pe["profiles"][self.pe["idx"]]
        if value is None:
            p.pop(key, None)
        else:
            p[key] = value

    def pe_vol(self, d):
        p = self.pe["profiles"][self.pe["idx"]]
        base = p.get("volume")
        if base is None:
            base = int(round(self.st.get("volume") or 40))
        p["volume"] = max(0, min(m.LOUD, int(base) + d))   # Szenen höchstens 80
        self.pe_render()

    def pe_capture(self):
        """Eingang, Klangmodus und Lautstärke so übernehmen, wie sie gerade am Receiver sind."""
        st = self.st
        if not st.get("power"):
            return self.toast("Der Receiver ist aus – bitte erst einschalten und einstellen.")
        p = self.pe["profiles"][self.pe["idx"]]
        p["power"] = "on"
        cur = st.get("input", "").lower().replace(" ", "")
        p["input"] = next((code for code, name in self.all_sources
                           if name.lower().replace(" ", "") == cur), p.get("input"))
        key = m.mode_key(st.get("surround", ""))
        p["mode"] = next((c for c, _, k in m.MODES if k == key), p.get("mode"))
        if st.get("volume") is not None:
            p["volume"] = max(0, min(m.LOUD, int(round(st["volume"]))))
        self.pe_render()
        self.toast("Aktueller Zustand übernommen")

    def pe_render(self):
        p = self.pe["profiles"][self.pe["idx"]]
        for i, b in self.pe_tabs.items():
            b.set_label(self.pe["profiles"][i].get("name") or _("Szene {}").format(i + 1))
        mark(self.pe_tabs, self.pe["idx"])
        mark(self.pe_power, p.get("power", "on"))
        self.pe_detail.set_sensitive(p.get("power", "on") != "off")
        mark(self.pe_in, p.get("input"))
        mark(self.pe_mode, p.get("mode"))
        v = p.get("volume")
        self.pe_vol_lbl.set_text("–" if v is None else str(v))
        set_cls(self.pe_vol_keep, "sel", v is None)

    def pe_save(self):
        for i, p in enumerate(self.pe["profiles"]):
            p["name"] = (p.get("name") or _("Szene {}").format(i + 1))[:24]
        cfg = m.load_config()
        cfg["profiles"] = self.pe["profiles"]
        m.save_config(cfg)
        self.refresh_scenes()
        self.show_page("main")
        self.toast("Szenen gespeichert")

    # ----- Frei wählbare Eingangsleiste -----
    def refresh_inputs(self):
        self.config = m.load_config()
        for c in self.in_holder.get_children():
            self.in_holder.remove(c)
        items = [(c, m.source_name(c)) for c in self.config["inputs"]]
        seg, self.in_btns = segmented(items, self.select_input)
        self.in_holder.pack_start(seg, True, True, 0)
        self.in_holder.show_all()
        if self.st:
            self._last_status = None
            self.on_status(self.st)

    def build_input_editor(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.pack_start(label("Eingänge in der Leiste", "media-title", xalign=0), False, False, 0)
        page.pack_start(label(_("Bis zu {} Eingänge antippen – in der Reihenfolge, in der "
                                "sie erscheinen sollen. Nochmal tippen entfernt.").format(m.MAX_INPUTS),
                              "status-sub", xalign=0), False, False, 0)
        self.ie_holder = Gtk.Box()
        page.pack_start(self.ie_holder, False, False, 8)
        page.pack_start(Gtk.Box(), True, True, 0)
        foot = Gtk.Box(spacing=14, homogeneous=True)
        foot.pack_start(button("Abbrechen", lambda: self.show_page("main"), "chip"), True, True, 0)
        foot.pack_start(button("Speichern", self.ie_save, "chip", "sel"), True, True, 0)
        page.pack_start(foot, False, False, 0)
        self.ie_sel = []
        return page

    def open_input_editor(self):
        self.ie_sel = list(m.load_config()["inputs"])
        self.ie_fill()
        self.show_page("edit_inputs")
        in_bg(m.sources, lambda lst: (setattr(self, "all_sources", lst), self.ie_fill()), lambda e: None)

    def ie_fill(self):
        for c in self.ie_holder.get_children():
            self.ie_holder.remove(c)
        g, self.ie_btns = self.chip_grid(self.all_sources, 4, self.ie_toggle)
        for b in self.ie_btns.values():
            add_cls(b, "tall")
        self.ie_holder.pack_start(g, True, True, 0)
        self.ie_holder.show_all()
        self.ie_render()
        return False

    def ie_toggle(self, code):
        if code in self.ie_sel:
            self.ie_sel.remove(code)
        elif len(self.ie_sel) < m.MAX_INPUTS:
            self.ie_sel.append(code)
        else:
            self.toast(_("Höchstens {} Eingänge – erst einen anderen abwählen.").format(m.MAX_INPUTS))
        self.ie_render()

    def ie_render(self):
        names = dict(self.all_sources)
        for code, b in self.ie_btns.items():
            on = code in self.ie_sel
            b.set_label(f"{self.ie_sel.index(code) + 1}.  {_(names[code])}" if on else names[code])
            set_cls(b, "sel", on)

    def ie_save(self):
        if not self.ie_sel:
            return self.toast("Bitte mindestens einen Eingang wählen.")
        cfg = m.load_config()
        cfg["inputs"] = self.ie_sel[:m.MAX_INPUTS]
        m.save_config(cfg)
        self.refresh_inputs()
        self.show_page("main")
        self.toast("Eingangsleiste gespeichert")

    # ----- Setup-Menü des Receivers (auf dem Fernseher) -----
    def build_setup(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        head = Gtk.Box(spacing=16)
        head.pack_start(label("Einstellungsmenü am Fernseher", "media-title", xalign=0), True, True, 0)
        head.pack_start(button("Web-Oberfläche", self.open_config, "ctl"), False, False, 0)
        page.pack_start(head, False, False, 0)
        hint = label("Das Menü des Receivers erscheint auf dem Fernseher. "
                     "Mit den Pfeilen bewegen, mit OK auswählen. Pfeile gedrückt halten = weiter.",
                     "status-sub", xalign=0)
        hint.set_line_wrap(True)
        page.pack_start(hint, False, False, 0)

        pad = Gtk.Grid(row_spacing=16, column_spacing=16)
        pad.set_halign(Gtk.Align.CENTER)
        pad.set_valign(Gtk.Align.CENTER)

        def arrow(txt, c):
            b = HoldButton(txt, lambda _first, c=c: self.cmd(c), "pad")
            return b
        pad.attach(arrow("▲", "MNCUP"), 1, 0, 1, 1)
        pad.attach(arrow("◀", "MNCLT"), 0, 1, 1, 1)
        pad.attach(button("OK", lambda: self.cmd("MNENT"), "pad", "sel"), 1, 1, 1, 1)
        pad.attach(arrow("▶", "MNCRT"), 2, 1, 1, 1)
        pad.attach(arrow("▼", "MNCDN"), 1, 2, 1, 1)
        page.pack_start(pad, True, True, 0)

        foot = Gtk.Box(spacing=16, homogeneous=True)
        foot.pack_start(button("‹  Zurück", lambda: self.cmd("MNRTN"), "ctl"), True, True, 0)
        foot.pack_start(button("Option", lambda: self.cmd("MNOPT"), "ctl"), True, True, 0)
        self.setup_close_btn = button("Menü schließen", self.close_setup, "ctl", "sel")
        foot.pack_start(self.setup_close_btn, True, True, 0)
        page.pack_start(foot, False, False, 0)
        return page

    def open_setup(self):
        if self.stack.get_visible_child_name() == "setup":
            return self.close_setup()
        self.page_before_setup = self.stack.get_visible_child_name()
        cur = self.st.get("input", "").lower().replace(" ", "")
        self.input_before_setup = next((c for c, n in self.all_sources
                                        if n.lower().replace(" ", "") == cur), None)
        name = m.source_name(self.input_before_setup) if self.input_before_setup else None
        self.setup_close_btn.set_label(_("Schließen & zurück zu {}").format(_(name)) if name else "Menü schließen")
        self.cmd("MNMEN ON")
        self.stack.set_visible_child_name("setup")
        mark(self.nav_btns, None)

    def close_setup(self):
        self.show_page(getattr(self, "page_before_setup", "main") or "main")

    def open_config(self):
        """Konfigurationsseite des Receivers im Browser öffnen."""
        subprocess.Popen(["xdg-open", f"http://{m.RECEIVER}/index.asp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        self.iconify()  # App kurz weglegen, damit der Browser vorne ist

    def build_eq(self):
        page = Gtk.Box(spacing=20, homogeneous=True)

        def card(title):
            c = add_cls(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
            c.pack_start(label(title, "cap", xalign=0), False, False, 0)
            return c

        def section(box, title, items, prefix_fn):
            box.pack_start(label(title, "status-sub", xalign=0), False, False, 6)
            seg, btns = segmented(items, lambda v: self.set_cmd(prefix_fn(v)))
            box.pack_start(seg, False, False, 0)
            return btns

        tc = card("KLANGREGELUNG")
        self.tone_btns = section(tc, "Bass / Höhen", [(True, "Ein"), (False, "Aus")],
                                 lambda v: "PSTONE CTRL " + ("ON" if v else "OFF"))
        self.tone_vals = {}
        for key, name, prefix in (("bass", "Bass", "PSBAS "), ("treble", "Höhen", "PSTRE ")):
            tc.pack_start(label(name, "status-sub", xalign=0), False, False, 10)
            r = Gtk.Box(spacing=12)
            r.pack_start(button("−", lambda k=key, p=prefix: self.step_tone(p, k, -1), "tone-btn"),
                         True, True, 0)
            val = label("–", "tone-val")
            r.pack_start(val, True, True, 0)
            r.pack_start(button("+", lambda k=key, p=prefix: self.step_tone(p, k, +1), "tone-btn"),
                         True, True, 0)
            self.tone_vals[key] = val
            tc.pack_start(r, False, False, 0)
        h = label("Wirkt nur, wenn Dynamic EQ aus ist und nicht in Direct / Pure Direct.",
                  "hint", xalign=0)
        h.set_line_wrap(True)
        tc.pack_start(h, False, False, 12)
        page.pack_start(tc, True, True, 0)

        gc = card("GRAFIK-EQ")
        self.geq_btns = section(gc, "Grafik-EQ", [(True, "Ein"), (False, "Aus")],
                                lambda v: "PSGEQ " + ("ON" if v else "OFF"))
        self.geq_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        gc.pack_start(self.geq_box, True, True, 0)
        self.geq = {"group": "FRO", "timer": None, "updating": False, "confirm0": False}
        self.geq_box.pack_start(label("Lautsprecher", "status-sub", xalign=0), False, False, 6)
        seg, self.geq_group_btns = segmented(
            [("FRO", "Front"), ("CEN", "Center"), ("SUR", "Surround"), ("FRH", "Höhe v."),
             ("RHE", "Höhe h.")], self.geq_switch)
        self.geq_box.pack_start(seg, False, False, 0)
        bands = Gtk.Box(spacing=4, homogeneous=True)
        self.geq_scales, self.geq_vals = {}, {}
        for b in m.GEQ_BANDS:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            val = label("–", "geq-val")
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, m.GEQ_MIN, m.GEQ_MAX, 0.5)
            sc.set_inverted(True)
            sc.set_draw_value(False)
            sc.set_vexpand(True)
            sc.set_can_focus(False)
            sc.add_mark(0, Gtk.PositionType.LEFT, None)
            add_cls(sc, "geq")
            sc.connect("value-changed", lambda w, b=b: self.geq_changed(b, w))
            col.pack_start(val, False, False, 0)
            col.pack_start(sc, True, True, 0)
            col.pack_start(label(b.replace("k", " k") + ("Hz" if "k" in b else " Hz"), "geq-freq"),
                           False, False, 0)
            self.geq_scales[b], self.geq_vals[b] = sc, val
            bands.pack_start(col, True, True, 0)
        self.geq_box.pack_start(bands, True, True, 10)
        foot = Gtk.Box(spacing=12)
        self.geq_status = label("", "status-sub", xalign=0)
        foot.pack_start(self.geq_status, True, True, 0)
        self.geq_zero_btn = button("Alle auf 0", self.geq_zero, "toggle-sm")
        foot.pack_start(self.geq_zero_btn, False, False, 0)
        self.geq_box.pack_start(foot, False, False, 0)
        h2 = label("Wirkt nur bei MultEQ „Aus“ (Seite Klang & Pegel). Änderungen werden nach "
                   "kurzem Loslassen automatisch im Receiver gespeichert.", "hint", xalign=0)
        h2.set_line_wrap(True)
        gc.pack_start(h2, False, False, 12)
        page.pack_start(gc, True, True, 0)
        return page

    # ----- Grafik-EQ -----
    def geq_load(self, group=None):
        group = group or self.geq["group"]
        self.geq_status.set_text("lädt …")
        in_bg(lambda: m.geq_read(group), self.geq_show,
              lambda e: self.geq_status.set_text(_("Nicht erreichbar: {}").format(_(str(e)))))

    def geq_show(self, st):
        self.geq["group"] = st["group"]
        mark(self.geq_group_btns, st["group"])
        self.geq["updating"] = True
        for b, v in st["vals"].items():
            self.geq_scales[b].set_value(v)
            self.geq_vals[b].set_text(self.geq_fmt(v))
        self.geq["updating"] = False
        self.geq_status.set_text("")
        return False

    @staticmethod
    def geq_fmt(v):
        return "0" if v == 0 else ("%+.1f" % v).replace(".0", "").replace(".", i18n.DEC).replace("-", "−")

    def geq_changed(self, band, scale):
        v = round(scale.get_value() * 2) / 2
        self.geq_vals[band].set_text(self.geq_fmt(v))
        set_cls(self.geq_vals[band], "changed", v != 0)
        if self.geq["updating"]:
            return
        self.geq_status.set_text("…")
        if self.geq["timer"]:
            GLib.source_remove(self.geq["timer"])
        self.geq["timer"] = GLib.timeout_add(700, self.geq_send)

    def geq_send(self):
        self.geq["timer"] = None
        group = self.geq["group"]
        vals = {b: round(sc.get_value() * 2) / 2 for b, sc in self.geq_scales.items()}
        self.geq_status.set_text("speichere …")

        def job():
            try:
                st = m.geq_set(group, vals)
                GLib.idle_add(self.geq_saved, st, vals)
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self.geq_status.set_text, _("Fehler: {}").format(_(str(e))))
        self.worker.put(job)
        return False

    def geq_saved(self, st, sent):
        ok = all(abs(st["vals"][b] - sent[b]) < 0.01 for b in sent)
        self.geq_status.set_text("Gespeichert ✓" if ok else "Receiver hat andere Werte gemeldet")
        if not ok and not self.geq["timer"]:
            self.geq_show(st)
        return False

    def geq_switch(self, group):
        if self.geq["timer"]:            # offene Änderung zuerst speichern
            GLib.source_remove(self.geq["timer"])
            self.geq_send()
        mark(self.geq_group_btns, group)
        self.geq_load(group)

    def geq_zero(self):
        if not self.geq["confirm0"]:
            self.geq["confirm0"] = True
            self.geq_zero_btn.set_label("Sicher? Nochmal")
            GLib.timeout_add(3000, lambda: (self.geq.update(confirm0=False),
                                            self.geq_zero_btn.set_label("Alle auf 0")) and False)
            return
        self.geq["confirm0"] = False
        self.geq_zero_btn.set_label("Alle auf 0")
        for sc in self.geq_scales.values():
            sc.set_value(0)

    def steppers(self, row, cb):
        """−3  −0,5  [Wert]  +0,5  +3"""
        row.pack_start(button("−3", lambda: cb(-3), "step", "big"), False, False, 0)
        row.pack_start(button("−0" + i18n.DEC + "5", lambda: cb(-0.5), "step"), False, False, 0)
        val = label("–", "lv-val")
        row.pack_start(val, False, False, 0)
        row.pack_start(button("+0" + i18n.DEC + "5", lambda: cb(+0.5), "step"), False, False, 0)
        row.pack_start(button("+3", lambda: cb(+3), "step", "big"), False, False, 0)
        return val

    # ----- Lautstärke-Ring -----
    @staticmethod
    def ring_layout(W, H):
        """Mittelpunkt und Radius: Der Ring ist unten offen (270°), deshalb sitzt der
        Mittelpunkt tiefer – so nutzt der Ring die Fläche voll aus."""
        pad = 54                                   # Platz fürs Glühen
        r = min(W / 2 - pad, (H - pad - 34) / (1 + math.sin(math.pi / 4)))
        return W / 2, pad + r, max(r, 50)

    def place_ring_mid(self):
        a = self.ring.get_allocation()
        cx, cy, r = self.ring_layout(a.width, a.height)
        mid = self.ring_mid
        h = mid.get_preferred_height()[1] - mid.get_margin_top() - mid.get_margin_bottom()
        top = max(0, int(cy - h / 2))
        if self.ring_mid.get_margin_top() != top:
            self.ring_mid.set_margin_top(top)
        return False

    def draw_ring(self, w, cr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        cx, cy, r = self.ring_layout(W, H)
        a0, sweep = math.pi * 0.75, math.pi * 1.5
        v = self.vol_shown
        frac = 0 if v is None else max(0.0, min(1.0, v / m.MAX_VOL))
        muted = self.st.get("mute") or not self.st.get("power", True)

        glow = 0.0 if muted else getattr(self, "glow", 0.0)
        a_fill = a0 + sweep * frac
        # Grundbild (Skalenstriche + Spur) nur einmal zeichnen und zwischenspeichern
        if getattr(self, "_ring_key", None) != (W, H):
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
            c2 = cairo.Context(surf)
            c2.set_line_cap(cairo.LINE_CAP_ROUND)
            c2.set_line_width(2)
            for i in range(41):
                a = a0 + sweep * i / 40
                r1, r2 = r + 14, r + (22 if i % 5 == 0 else 18)
                c2.set_source_rgba(1, 1, 1, 0.16 if i % 5 == 0 else 0.07)
                c2.move_to(cx + r1 * math.cos(a), cy + r1 * math.sin(a))
                c2.line_to(cx + r2 * math.cos(a), cy + r2 * math.sin(a))
                c2.stroke()
            c2.set_line_width(14)
            c2.set_source_rgba(1, 1, 1, 0.06)
            c2.arc(cx, cy, r, a0, a0 + sweep)
            c2.stroke()
            self._ring_base, self._ring_key = surf, (W, H)
        cr.set_source_surface(self._ring_base, 0, 0)
        cr.paint()
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        # beim Glühen: Striche im gefüllten Bereich golden (nur dann, kostet sonst nichts)
        if glow > 0.01:
            cr.set_line_width(2)
            for i in range(41):
                a = a0 + sweep * i / 40
                if a > a_fill:
                    break
                r1, r2 = r + 14, r + (22 if i % 5 == 0 else 18)
                cr.set_source_rgba(*GOLD, 0.75 * glow)
                cr.move_to(cx + r1 * math.cos(a), cy + r1 * math.sin(a))
                cr.line_to(cx + r2 * math.cos(a), cy + r2 * math.sin(a))
                cr.stroke()
        if frac <= 0:
            return False

        a1 = a0 + sweep * frac
        a_loud = a0 + sweep * m.LOUD / m.MAX_VOL
        RED = (0.95, 0.42, 0.30)
        if muted:
            cr.set_source_rgba(0.55, 0.56, 0.60, 0.6)
        else:
            # weicher Schein – beim Glühen mehrere breite, transparente Schichten (wie Licht)
            layers = [(30, 0.10)] + ([(72, 0.05), (52, 0.09), (36, 0.15), (24, 0.22)]
                                     if glow > 0.01 else [])
            for width, alpha in layers:
                k = alpha if width == 30 and len(layers) == 1 else alpha * (glow if width != 30 else 1)
                cr.set_line_width(width)
                cr.set_source_rgba(*GOLD, k)
                cr.arc(cx, cy, r, a0, min(a1, a_loud))
                cr.stroke()
                if a1 > a_loud:
                    cr.set_source_rgba(*RED, k)
                    cr.arc(cx, cy, r, a_loud, a1)
                    cr.stroke()
            # Bogen selbst: beim Glühen heller (Richtung Champagner-Weiß)
            hi = tuple(c + (1.0 - c) * 0.55 * glow for c in GOLD)
            g = cairo.LinearGradient(cx - r, cy + r, cx + r, cy - r)
            g.add_color_stop_rgb(0, *GOLD_DEEP)
            g.add_color_stop_rgb(1, *hi)
            cr.set_source(g)
        cr.set_line_width(14 + 4 * glow)
        cr.arc(cx, cy, r, a0, min(a1, a_loud))
        cr.stroke()
        if a1 > a_loud:
            cr.set_source_rgba(0.88, 0.40, 0.32, 0.65 if muted else 1.0)
            cr.arc(cx, cy, r, a_loud, a1)
            cr.stroke()
        # Markierung bei 80
        cr.set_source_rgba(0.88, 0.40, 0.32, 0.8)
        cr.set_line_width(3)
        cr.move_to(cx + (r - 20) * math.cos(a_loud), cy + (r - 20) * math.sin(a_loud))
        cr.line_to(cx + (r + 24) * math.cos(a_loud), cy + (r + 24) * math.sin(a_loud))
        cr.stroke()
        # Punkt am Ende (beim Drehen größer und leuchtend)
        px, py = cx + r * math.cos(a1), cy + r * math.sin(a1)
        if glow > 0.01:
            col = RED if a1 > a_loud else GOLD
            halo = cairo.RadialGradient(px, py, 0, px, py, 26 + 26 * glow)
            halo.add_color_stop_rgba(0, *col, 0.65 * glow)
            halo.add_color_stop_rgba(1, *col, 0)
            cr.set_source(halo)
            cr.arc(px, py, 26 + 26 * glow, 0, 2 * math.pi)
            cr.fill()
        if self.ring_drag:
            cr.set_source_rgba(*GOLD, 0.25)
            cr.arc(px, py, 30, 0, 2 * math.pi)
            cr.fill()
        cr.set_source_rgb(0.96, 0.92, 0.84) if not muted else cr.set_source_rgb(0.7, 0.7, 0.72)
        cr.arc(px, py, 16 if self.ring_drag else 9, 0, 2 * math.pi)
        cr.fill()
        return False

    # ----- Aktionen -----
    def show_page(self, key):
        if self.stack.get_visible_child_name() == "setup" and key != "setup":
            self.cmd("MNMEN OFF")   # Menü am Fernseher schließen, wenn man die Seite verlässt
            prev = getattr(self, "input_before_setup", None)
            if prev:
                # Eingang erneut wählen → Fernseher schaltet (per HDMI-CEC) zurück
                GLib.timeout_add(800, lambda: self.cmd(prev) or False)
                self.input_before_setup = None
        self.stack.set_visible_child_name(key)
        mark(self.nav_btns, key)
        if key in ("sound", "eq"):
            self.load_settings()
        if key == "eq":
            self.geq_load()
        elif key == "media":
            self.media_refresh()

    def toast(self, text, secs=4, warn=False):
        """Kurze Meldung oben in der Mitte (secs=None: bleibt stehen, warn=True: rot)."""
        self.toast_lbl.set_text(text)
        set_cls(self.toast_lbl, "warn", warn)
        self.toast_rev.set_reveal_child(True)
        if self.toast_timer:
            GLib.source_remove(self.toast_timer)
            self.toast_timer = None
        if secs:
            self.toast_timer = GLib.timeout_add(int(secs * 1000), self.toast_hide)
        return False

    def on_destroy(self, *_):
        if self.voice_proc and self.voice_proc.poll() is None:
            self.voice_proc.terminate()
        Gtk.main_quit()

    # ----- Sprachsteuerung (offline, voice.py als Hilfsprozess) -----
    def voice_press(self):
        if self.voice_busy:
            return
        self.voice_busy = True
        set_cls(self.mic_btn, "listening", True)
        starting = self.voice_proc is None or self.voice_proc.poll() is not None
        self.toast("Sprachsteuerung wird geladen …" if starting else "🎤  Ich höre zu …", None)
        threading.Thread(target=self.voice_run, daemon=True).start()

    def voice_run(self):
        try:
            p = self.voice_proc
            if p is None or p.poll() is not None:
                p = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / "voice.py"),
                                      "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
                self.voice_proc = p
                if not p.stdout.readline():
                    raise RuntimeError("startet nicht")
                GLib.idle_add(self.toast, "🎤  Ich höre zu …", None)
            p.stdin.write(json.dumps({"max_sec": 6}) + "\n")
            p.stdin.flush()
            res = json.loads(p.stdout.readline() or '{"error": "keine Antwort"}')
        except Exception as e:  # noqa: BLE001
            res = {"error": str(e)}
        GLib.idle_add(self.voice_done, res)

    def voice_idle_check(self):
        p = self.voice_proc
        if p and p.poll() is None and not self.voice_busy and time.time() - self.voice_last > 300:
            p.terminate()                  # Sprachmodell aus dem Speicher nehmen
            self.voice_proc = None
        return True

    def voice_done(self, res):
        self.voice_busy = False
        self.voice_last = time.time()
        set_cls(self.mic_btn, "listening", False)
        if res.get("error"):
            self.toast(_("Sprachsteuerung: {}").format(res["error"]))
        elif not res.get("text"):
            self.toast("Nichts verstanden – bitte noch einmal.")
        else:
            self.voice_exec(res["text"], sprachbefehle.verstehe(res["text"]))
        return False

    def voice_exec(self, text, c):
        said, a = f"„{text}“", c.get("aktion")
        # Szenen auch über ihren selbst gewählten Namen aufrufen („Kino“, „Party“ …)
        norm = lambda x: "".join(ch for ch in x.lower() if ch.isalnum())
        for i, p in enumerate(self.config["profiles"]):
            n = norm(p.get("name", ""))
            if len(n) >= 3 and n in norm(text) and a not in ("kuenstler",):
                self.run_profile(i)
                return self.toast(f"{said}\n→ {p.get('name')}")
        msg = None
        if a is None:
            return self.toast(_("{}\nDas habe ich leider nicht verstanden.").format(said), 5)
        if a in ("schritt", "lautstaerke"):
            base = self.vol_base()
            if base is None:
                return self.toast("Lautstärke gerade unbekannt.")
            self.gesture_start = base
            self.set_vol(int(round(base)) + c["wert"] if a == "schritt" else c["wert"])
            if self.vol_target >= m.LOUD:
                return            # Warnung „sehr laut“ steht schon da
            msg = _("Lautstärke {}").format(self.vol_target)
        elif a == "cmd":
            if c["wert"] in ("SITV", "SIGAME", "SISERVER"):
                self.select_input(c["wert"])
            else:
                self.cmd(c["wert"])
            msg = c["text"]
        elif a == "szene":
            profs = self.config["profiles"]
            idx = {"film": 0, "musik": 1}.get(c["wert"])
            if c["wert"] == "aus":
                idx = next((i for i, p in enumerate(profs) if p.get("power") == "off"), None)
                if idx is None:
                    self.cmd("ZMOFF")
                    return self.toast(_("{}\n→ Ausschalten").format(said))
            self.run_profile(idx)
            msg = profs[idx].get("name")
        elif a == "ctl":
            self.ctl(c["wert"])
            msg = {"pause": "Pause", "play": "Weiter", "stop": "Stopp", "next": "Nächster Titel",
                   "prev": "Vorheriger Titel"}[c["wert"]]
        elif a == "kuenstler":
            self.toast(_("{}\nSuche in der Mediathek …").format(said), None)
            in_bg(lambda: api("/api/artists"),
                  lambda lst: self.voice_play_artist(text, c, lst),
                  lambda e: self.toast(_("Mediathek nicht erreichbar:\n{}").format(_(str(e))), 6))
            return
        self.toast("{}\n→ {}".format(said, _(msg)))

    def voice_play_artist(self, text, c, lst):
        k = sprachbefehle.finde_kuenstler(c["name"], lst)
        if not k:
            return self.toast(_("„{}“\nKünstler „{}“ nicht gefunden.").format(text, c["name"]), 5)
        self.toast(_("„{}“\n→ Spiele {}").format(text, k["title"]) + (_(" (zufällig)") if c["zufall"] else ""), 5)
        self.show_page("media")
        self.media_stack.set_visible_child_name("now")
        q = "/api/play_artist?id=" + urllib.parse.quote(k["id"]) + ("&shuffle=1" if c["zufall"] else "")
        self.worker.put(lambda: api(q))
        return False

    def toast_hide(self):
        self.toast_rev.set_reveal_child(False)
        self.toast_timer = None
        return False

    def hide_cursor(self):
        gw = self.get_window()
        if gw:
            gw.set_cursor(Gdk.Cursor.new_for_display(gw.get_display(), Gdk.CursorType.BLANK_CURSOR))
        self.cursor_timer = None
        return False

    def on_any_event(self, ev, _data):
        t = ev.get_event_type()
        if t in (Gdk.EventType.MOTION_NOTIFY, Gdk.EventType.BUTTON_PRESS,
                 Gdk.EventType.TOUCH_BEGIN, Gdk.EventType.TOUCH_UPDATE):
            dev = ev.get_source_device()
            touch = (t in (Gdk.EventType.TOUCH_BEGIN, Gdk.EventType.TOUCH_UPDATE) or
                     (dev is not None and dev.get_source() == Gdk.InputSource.TOUCHSCREEN))
            if self.cursor_timer:
                GLib.source_remove(self.cursor_timer)
                self.cursor_timer = None
            gw = self.get_window()
            if touch:
                self.hide_cursor()
            elif gw:
                gw.set_cursor(None)   # normaler Zeiger
                self.cursor_timer = GLib.timeout_add(3000, self.hide_cursor)
        Gtk.main_do_event(ev)

    def on_key(self, _w, ev):
        if ev.keyval == Gdk.KEY_F11:
            (self.unfullscreen if self.is_full else self.fullscreen)()
            self.is_full = not self.is_full
        elif ev.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()
        elif ev.keyval in (Gdk.KEY_plus, Gdk.KEY_KP_Add, Gdk.KEY_Up,
                           Gdk.KEY_minus, Gdk.KEY_KP_Subtract, Gdk.KEY_Down):
            # gehaltene Taste (Wiederholung) zählt nicht als neuer Druck
            first = time.time() - getattr(self, "last_key", 0) > 0.6
            self.last_key = time.time()
            up = ev.keyval in (Gdk.KEY_plus, Gdk.KEY_KP_Add, Gdk.KEY_Up)
            self.vol_step(+1 if up else -1, first)

    def show_err(self, e=None):
        self.err_lbl.set_text(_("Receiver nicht erreichbar: {}").format(_(str(e))) if e else "")

    def after_commands(self):
        GLib.timeout_add(400, self.refresh_once)
        if self.reload_settings:
            self.reload_settings = False
            GLib.timeout_add(600, self.load_settings_once)

    def cmd(self, c):
        self.worker.put(lambda: m.send(c))

    def set_cmd(self, c):
        self.reload_settings = True
        self.worker.put(lambda: m.send(c))

    def toggle_power(self):
        self.cmd("ZMOFF" if self.st.get("power") else "ZMON")

    def toggle_mute(self):
        self.st["mute"] = not self.st.get("mute")
        self.render_volume()
        self.cmd("MUON" if self.st["mute"] else "MUOFF")

    def scene(self, key, title):
        self.status_sub.set_text(_("Szene „{}“ wird eingestellt …").format(_(title)))
        self.worker.put(lambda: m.run_scene(key))

    def vol_base(self):
        return self.vol_target if time.time() < self.vol_local_until else self.st.get("volume")

    def vol_step(self, d, first=True):
        base = self.vol_base()
        if base is None:
            return
        if first:
            self.gesture_start = base    # neuer Druck: von hier aus zählt der sanfte Stopp
        self.set_vol(int(round(base)) + d)

    # ----- Drehregler am Ring -----
    def ring_geom(self, ev):
        W, H = self.ring.get_allocated_width(), self.ring.get_allocated_height()
        cx, cy, r = self.ring_layout(W, H)
        dx, dy = ev.x - cx, ev.y - cy
        return math.atan2(dy, dx), math.hypot(dx, dy), r

    def on_ring_press(self, _w, ev):
        base = self.vol_base()
        if base is None:
            return False
        ang, dist, r = self.ring_geom(ev)
        if dist < r * 0.35 or dist > r + 90:   # Mitte (Zahl) und weit außerhalb ignorieren
            return False
        self.ring_drag = {"a": ang, "v": float(base)}
        self.gesture_start = base
        self.ring.queue_draw()
        return True

    def on_ring_motion(self, _w, ev):
        if not self.ring_drag:
            return False
        ang, _dist, _r = self.ring_geom(ev)
        d = ang - self.ring_drag["a"]
        d = (d + math.pi) % (2 * math.pi) - math.pi   # Sprung bei ±180° ausgleichen
        self.ring_drag["a"] = ang
        # ganzer Bogen (270°) = ganzer erlaubter Bereich 0…MAX_VOL
        self.ring_drag["v"] = max(0.0, min(float(m.MAX_VOL),
                                           self.ring_drag["v"] + d / (math.pi * 1.5) * m.MAX_VOL))
        new = int(round(self.ring_drag["v"]))
        if new != int(round(self.vol_base() or 0)):
            self.set_vol(new)
        return True

    def on_ring_release(self, _w, _ev):
        if self.ring_drag:
            self.ring_drag = None
            self.ring.queue_draw()
        return False

    def set_vol(self, v):
        v = max(0, min(m.MAX_VOL, int(v)))
        start = getattr(self, "gesture_start", None)
        start = 0 if start is None else start
        if v > m.LOUD and start < m.LOUD:
            # sanfter Stopp: über 80 nur mit neuem Druck / neuem Ansetzen
            v = m.LOUD
            self.toast("Achtung: Ab 80 wird es sehr laut.\n"
                       "Für mehr einfach noch einmal drücken oder neu am Ring ansetzen.", warn=True)
        elif v > m.LOUD and v > (self.vol_shown or 0):
            self.toast(_("Sehr laut ({}) – bitte Ohren und Lautsprecher schonen.").format(v), warn=True)
        self.vol_target = v
        self.vol_local_until = time.time() + 2.5
        self.vol_shown = self.vol_target
        self.render_volume()
        if not self.worker.vol_pending:   # schnelle Klicks bündeln, immer den neuesten Wert senden
            self.worker.vol_pending = True

            def send_latest():
                self.worker.vol_pending = False
                m.send("MV%02d" % self.vol_target)
            self.worker.put(send_latest)

    def step_tone(self, prefix, key, delta):
        cur = self.cfg.get(key)
        if cur is None:
            return
        new = max(44, min(56, cur + delta))   # 50 = 0 dB, ±6 dB
        self.cfg[key] = new
        self.render_settings()
        self.worker.put(lambda: m.send(prefix + "%02d" % new))

    def step_level(self, prefix, ch, delta):
        cur = self.cfg.get("swl") if ch is None else self.cfg.get("levels", {}).get(ch)
        if cur is None:
            return
        new = max(m.LEVEL_MIN, min(m.LEVEL_MAX, cur + delta))
        if ch is None:
            self.cfg["swl"] = new
        else:
            self.cfg["levels"][ch] = new
        self.render_settings()
        self.worker.put(lambda: m.send(prefix + m.fmt_level(new)))

    # ----- Aktualisieren -----
    def is_minimized(self):
        gw = self.get_window()
        return bool(gw and gw.get_state() & Gdk.WindowState.ICONIFIED)

    def tick(self):
        if not self.is_minimized():        # minimiert: nichts abfragen (spart Strom)
            self.refresh()
        return True

    def refresh_once(self):
        self.refresh()
        return False

    def refresh(self):
        in_bg(m.status, self.on_status, self.on_status_err)

    def on_status(self, st):
        if st == getattr(self, "_last_status", None) and time.time() >= self.vol_local_until:
            return              # nichts geändert → nichts neu zeichnen (spart viel Rechenzeit)
        self._last_status = dict(st)
        self.st = st
        self.show_err()
        on = st["power"]
        set_cls(self.power_btn, "on", on)
        self.power_lbl.set_text("Eingeschaltet" if on else "Standby")
        if time.time() >= self.vol_local_until:
            self.vol_shown = st["volume"]
        self.render_volume()
        cur_in = st["input"].lower().replace(" ", "")
        for code, b in self.in_btns.items():
            n = m.source_name(code)
            names = {n.lower().replace(" ", ""), i18n.tr_lang(n, "en").lower().replace(" ", "")}
            set_cls(b, "sel", on and cur_in in names)
        prev = getattr(self, "_group_key", None)
        gkey = (st.get("surround"), st.get("input"), st.get("power"))
        if gkey != prev:
            self._group_key = gkey
            if on:
                self.group_refresh()
            else:
                mark(self.group_btns, None)
        key = m.mode_key(st["surround"])
        for code, b in self.mode_btns.items():
            set_cls(b, "sel", on and MODE_KEYS[code] == key)
        if on:
            self.status_main.set_text(_(st["input"]) + "  ▾")
            self.status_sub.set_text(st["surround"])
        else:
            self.status_main.set_text("Standby")
            self.status_sub.set_text("Receiver ist ausgeschaltet")

    # ----- Glühen des Rings -----
    def pulse_glow(self):
        self.glow = 1.0
        set_cls(self.vol_lbl, "glowing", True)
        if not getattr(self, "glow_timer", None):
            self.glow_timer = GLib.timeout_add(40, self.glow_step)   # 25 Bilder/s

    def glow_step(self):
        if self.ring_drag:
            self.glow = max(self.glow, 0.85)       # beim Drehen glüht er weiter
        else:
            self.glow *= 0.90                     # sanft abklingen
        if self.glow < 0.5:
            set_cls(self.vol_lbl, "glowing", False)
        self.ring.queue_draw()
        if self.glow < 0.03:
            self.glow, self.glow_timer = 0.0, None
            self.ring.queue_draw()
            return False
        return True

    def render_volume(self):
        v = self.vol_shown
        if v is not None and getattr(self, "last_drawn_vol", None) not in (None, v):
            self.pulse_glow()                     # Lautstärke hat sich geändert → aufglühen
        self.last_drawn_vol = v
        self.vol_lbl.set_text("–" if v is None else ("%g" % v).replace(".", i18n.DEC))
        muted = bool(self.st.get("mute"))
        set_cls(self.vol_lbl, "muted", muted)
        self.vol_cap.set_text("STUMM" if muted else "LAUTSTÄRKE")
        set_cls(self.mute_btn, "muted", muted)
        self.mute_btn.set_label("Ton an" if muted else "Stumm")
        key = (v, muted, bool(self.st.get("power", True)))
        if key != getattr(self, "_ring_state", None) or getattr(self, "glow", 0) > 0:
            self._ring_state = key
            self.ring.queue_draw()

    def on_status_err(self, e):
        self.show_err(e)
        self.status_main.set_text("Keine Verbindung")
        self.status_sub.set_text(_("Receiver unter %s nicht erreichbar") % m.RECEIVER)

    def load_settings(self):
        in_bg(m.settings, self.on_settings, self.show_err)

    def load_settings_once(self):
        self.load_settings()
        return False

    def on_settings(self, cfg):
        self.cfg = cfg
        self.render_settings()

    def render_settings(self):
        c = self.cfg
        mark(self.multeq_btns, c.get("multeq"))
        mark(self.dyneq_btns, c.get("dyneq"))
        mark(self.reflev_btns, c.get("reflev"))
        mark(self.dynvol_btns, c.get("dynvol"))
        mark(self.cinema_btns, c.get("cinemaeq"))
        mark(self.tone_btns, c.get("tone"))
        mark(self.geq_btns, c.get("geq"))
        for key, lbl in self.tone_vals.items():
            v = c.get(key)
            lbl.set_text("–" if v is None else ("0 dB" if v == 50 else ("%+d dB" % (v - 50)).replace("-", "−")))
            set_cls(lbl, "changed", v is not None and v != 50)
        on = c.get("swl_on")
        self.swl_onoff.set_label("Ein" if on else "Aus")
        set_cls(self.swl_onoff, "sel", bool(on))
        if c.get("swl") is not None:
            self.swl_val.set_text(m.level_db(c["swl"]))
            set_cls(self.swl_val, "changed", c["swl"] != 50)
        for code, lbl in self.ch_vals.items():
            v = c.get("levels", {}).get(code)
            lbl.set_text("–" if v is None else m.level_db(v))
            set_cls(lbl, "changed", v is not None and v != 50)


# Englische Menüpunkte des Receivers / Plex auf Deutsch (Namen von Künstlern usw. bleiben)
DE = {
    "Media Server": "Mediaserver", "Now Playing": "Jetzt läuft", "Online Music": "Online-Musik",
    "Favorites": "Favoriten", "Internet Radio": "Internetradio", "Music": "Musik",
    "Video": "Video", "Video (not play)": "Video (nicht abspielbar)", "Photos": "Fotos",
    "Music Channels": "Musikkanäle", "Shared Music": "Geteilte Musik",
    "Remote Music": "Musik von anderen Servern", "Music Queue": "Warteschlange",
    "Music Recommendations": "Empfehlungen", "Preferences": "Einstellungen",
    "All Artists": "Alle Künstler", "Album Artists": "Album-Künstler", "Artists": "Künstler",
    "All Albums": "Alle Alben", "Albums": "Alben", "All Tracks": "Alle Titel", "Tracks": "Titel",
    "By Album": "Nach Album", "By Artist": "Nach Künstler", "By Genre": "Nach Genre",
    "By Decade": "Nach Jahrzehnt", "By Year": "Nach Jahr", "By Collection": "Nach Sammlung",
    "By Folder": "Nach Ordner", "By Rating": "Nach Bewertung", "Recently Added": "Kürzlich hinzugefügt",
    "Recently Played": "Zuletzt gespielt", "Most Played": "Am häufigsten gespielt",
    "Playlists": "Wiedergabelisten", "Genres": "Genres", "Folders": "Ordner", "Search": "Suche",
    "Shuffle": "Zufallswiedergabe", "Play All": "Alle abspielen", "[Unknown Album]": "[Unbekanntes Album]",
    "[Unknown Artist]": "[Unbekannter Künstler]", "Unknown Album": "Unbekanntes Album",
    "Unknown Artist": "Unbekannter Künstler", "Channels": "Kanäle", "Settings": "Einstellungen",
}


def tr(text):
    if i18n.LANG != "de":
        return text          # Englisch: Plex-Menüs bleiben im Original
    return DE.get(text.strip(), text) if text else text


INPUT_ITEMS = [("SITV", "TV Audio"), ("SIGAME", "Game"), ("SISERVER", "Mediaserver")]
INPUT_MATCH = {"SITV": "tvaudio", "SIGAME": "game", "SISERVER": "server"}
MODE_KEYS = {c: k for c, _, k in m.MODES}

if __name__ == "__main__":
    App().show_all()
    Gtk.main()
