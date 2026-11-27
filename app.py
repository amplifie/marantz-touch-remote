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
import re
import select
import subprocess
import sys
import syslog
import urllib.parse
import urllib.request
import threading
import time
import weakref
from pathlib import Path

import cairo
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, Gio, GLib, GdkPixbuf, GObject, PangoCairo  # noqa: E402

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

CSS_BASE = """
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

.volstrip { font-size: 44pt; font-weight: 200; color: #ecebe8; border-radius: 30px;
            background-color: #1d1f24; background-image: linear-gradient(to bottom, #262930, #1b1d22);
            border: 1px solid rgba(255,255,255,0.07);
            box-shadow: inset 0 1px rgba(255,255,255,0.06), 0 3px 10px rgba(0,0,0,0.35); }
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
button.topbtn { min-width: 60px; min-height: 60px; border-radius: 30px; padding: 0; font-size: 17pt;
                color: #b9bcc2; }
button.edit { min-width: 38px; min-height: 38px; border-radius: 19px; padding: 0; font-size: 12pt;
              background-image: none; background-color: transparent;
              border: 1px solid rgba(217,185,126,0.40); box-shadow: none; color: #d9b97e; }
button.edit:active { background-color: rgba(217,185,126,0.18); }
button.power.menu { color: #d9b97e; font-size: 26pt; }
button.menuitem { min-height: 76px; min-width: 420px; border-radius: 20px; padding: 0 22px; }
.menu-icon { font-size: 20pt; color: #d9b97e; }
.menu-text { font-size: 15pt; font-weight: 500; }
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
.np-format { font-size: 13pt; font-weight: 600; color: #d9b97e;
             border: 1px solid rgba(217,185,126,0.45); border-radius: 14px; padding: 5px 14px; }
.np-time { font-size: 13pt; font-weight: 400; color: #b9bcc2; }
.np-chip { font-size: 9pt; font-weight: 600; letter-spacing: 2px; color: #7d8088;
           border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 4px 12px; }
button.big-ctl { min-height: 120px; min-width: 150px; font-size: 30pt; border-radius: 30px; }
button.play { min-width: 190px; }
.toast { background-color: rgba(26,28,33,0.97); color: #f2f1ee; font-size: 15pt; font-weight: 500;
         border: 1px solid rgba(217,185,126,0.55); border-radius: 22px; padding: 20px 34px;
         box-shadow: 0 10px 40px rgba(0,0,0,0.6); }
.help { background-color: rgba(22,24,29,0.98); border: 1px solid rgba(217,185,126,0.55);
        border-radius: 28px; padding: 32px 44px; box-shadow: 0 10px 40px rgba(0,0,0,0.6); }
.help-key { font-size: 13pt; font-weight: 600; color: #d9b97e; }
.help-text { font-size: 13pt; font-weight: 300; color: #ecebe8; }
.kbd.kbd.kbd { border: 1px solid #fff3d6;
               box-shadow: 0 0 0 3px #fff3d6, 0 0 22px 4px rgba(217,185,126,0.85); }
list row.kbd.kbd { background-image: linear-gradient(to bottom, #3a3428, #2c281f); }
scale.kbd slider { box-shadow: 0 0 0 4px #fff3d6, 0 0 22px 6px rgba(217,185,126,0.9); }
scale.kbd.kbd.kbd { box-shadow: none; border-color: transparent; }
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
.wordmark { font-size: 18pt; font-weight: 300; letter-spacing: 8px; color: #d9b97e; }
.wordsub { font-size: 9pt; font-weight: 300; letter-spacing: 3px; color: #9a9da4; }
.wordline { min-height: 1px; background-image: linear-gradient(to right, rgba(217,185,126,0), rgba(217,185,126,0.7)); }
scrollbar slider { min-width: 6px; background-color: rgba(255,255,255,0.15); border-radius: 3px; }
scrollbar { background-color: transparent; border: none; }
"""

# ---------- Anpassung an die Fenstergröße ----------
# Alle Maße oben und im Code gelten für die Referenzgröße 1920×1280 (Surface 3 im Vollbild).
# Bei anderer Fenstergröße wird alles mit einem Faktor umgerechnet – ohne Scrollen.
UI_REF_W, UI_REF_H = 1920, 1280
UI_MIN_PT = 7.0            # kleinste Schriftgröße, damit alles lesbar bleibt
RING_R0 = 320.0            # Ring-Radius bei der Referenzgröße (alle Ring-Maße sind Anteile davon)
_CSS_NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(px|pt)\b")


def scaled_css(f):
    """CSS mit Faktor f: px und pt werden umgerechnet, 1px-Linien bleiben scharf."""
    def one(mo):
        v, unit = float(mo.group(1)), mo.group(2)
        if unit == "px":
            return mo.group(0) if v <= 1 else f"{max(1, round(v * f))}px"
        return f"{max(UI_MIN_PT, round(v * f, 1)):g}pt"
    return _CSS_NUM.sub(one, CSS_BASE).encode()


def _px(v, f):
    return v if v <= 0 else max(1, int(round(v * f)))


class Shrinkable(Gtk.Bin):
    """Hülle um den ganzen Inhalt: Das Fenster darf kleiner werden, als der Inhalt
    gerade braucht (sonst ließe es sich nie verkleinern). Danach rechnet die App
    die Maße passend um, sodass wieder alles ohne Abschneiden hineinpasst."""

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.CONSTANT_SIZE

    def do_get_preferred_width(self):
        return 1, 1

    def do_get_preferred_height(self):
        return 1, 1

    def do_size_allocate(self, a):
        self.set_allocation(a)
        c = self.get_child()
        if c and c.get_visible():
            mw = c.get_preferred_width()[0]
            r = Gdk.Rectangle()
            r.x, r.y = a.x, a.y
            r.width = max(a.width, mw)
            r.height = max(a.height, c.get_preferred_height_for_width(r.width)[0])
            c.size_allocate(r)


class UiScale:
    """Merkt sich für jedes Widget die ursprünglichen Pixelwerte (Größe, Abstände, Ränder)
    und setzt sie bei einem neuen Faktor neu. Neue Widgets (z. B. Listenzeilen) werden
    automatisch erfasst, sobald sie in die Oberfläche eingehängt werden."""

    def __init__(self):
        self.f = 1.0
        self.known = weakref.WeakSet()
        self.pending = []
        self.idle = None
        GObject.add_emission_hook(Gtk.Widget, "parent-set", self._on_parent_set)

    def _on_parent_set(self, w, *_):
        self.pending.append(w)
        if self.idle is None:
            self.idle = GLib.idle_add(self.flush, priority=GLib.PRIORITY_HIGH_IDLE)
        return True

    def flush(self):
        """Neu eingehängte Widgets erfassen und mit dem aktuellen Faktor anpassen."""
        self.idle = None
        todo, self.pending = self.pending, []
        for w in todo:
            if w.get_parent() is None:
                continue
            b = getattr(w, "_ui_base", None)
            if b is None:
                b = self._record(w)
                w._ui_base = b
                self.known.add(w)
            else:
                b.pop("pad", None)          # neu eingepackt: Abstand frisch übernehmen
                self._record_pad(w, b)
            if self.f != 1.0:
                self._apply(w, b)
        return False

    @staticmethod
    def _record_pad(w, b):
        p = w.get_parent()
        if isinstance(p, Gtk.Box):
            pad = p.child_get_property(w, "padding")
            if pad:
                b["pad"] = pad

    def _record(self, w):
        b = {}
        rw, rh = w.get_size_request()
        if rw > 0 or rh > 0:
            b["req"] = (rw, rh)
        if isinstance(w, Gtk.Container) and w.get_border_width():
            b["border"] = w.get_border_width()
        if isinstance(w, Gtk.Box) and w.get_spacing():
            b["spacing"] = w.get_spacing()
        if isinstance(w, Gtk.Grid) and (w.get_row_spacing() or w.get_column_spacing()):
            b["grid"] = (w.get_row_spacing(), w.get_column_spacing())
        if not getattr(w, "_ui_keep_margin", False):
            mg = (w.get_margin_top(), w.get_margin_bottom(), w.get_margin_start(), w.get_margin_end())
            if any(mg):
                b["margin"] = mg
        self._record_pad(w, b)
        return b

    def _apply(self, w, b):
        f = self.f
        if "req" in b:
            w.set_size_request(*(_px(v, f) for v in b["req"]))
        if "border" in b:
            w.set_border_width(_px(b["border"], f))
        if "spacing" in b:
            w.set_spacing(_px(b["spacing"], f))
        if "grid" in b:
            w.set_row_spacing(_px(b["grid"][0], f))
            w.set_column_spacing(_px(b["grid"][1], f))
        if "margin" in b:
            t, bo, st, en = (_px(v, f) for v in b["margin"])
            w.set_margin_top(t)
            w.set_margin_bottom(bo)
            w.set_margin_start(st)
            w.set_margin_end(en)
        if "pad" in b:
            p = w.get_parent()
            if isinstance(p, Gtk.Box):
                exp, fill, _pad, pt = p.query_child_packing(w)
                p.set_child_packing(w, exp, fill, _px(b["pad"], f), pt)

    def set_factor(self, f):
        self.flush()
        self.f = f
        for w in list(self.known):
            self._apply(w, w._ui_base)


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


def update_text(lb, text):
    """Text nur setzen, wenn er sich ändert (sonst rechnet GTK das Layout neu)."""
    if lb.get_text() != _(text):
        lb.set_text(text)


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


class VolumeStrip(Gtk.DrawingArea):
    """Hoher Lautstärke-Streifen: oben „+“, unten „−“, dazwischen die Zahl; überall senkrecht ziehbar.

    Tippen/Halten auf + und − wirkt wie bei HoldButton (nur löst ein kurzer Tipp erst beim
    Loslassen aus, weil dort auch ein Ziehen beginnen darf). Gesendet wird nichts selbst:
    step(richtung, neuer_druck), base() = aktueller Wert, drag(wert), drag_end()."""

    ZONE = 214          # Höhe der +/−-Flächen bei der Referenzgröße (wie die früheren Kacheln)
    MIN_H = 442         # Mindesthöhe: zwei frühere Kacheln samt Abstand
    SLOP = 8            # ab so vielen Pixeln senkrechter Bewegung wird gezogen
    GAIN = 1.2          # ganze Streifenhöhe = 1,2 × Maximum
    DRAG_MAX = 60       # beim Ziehen hier Schluss, darüber nur schrittweise mit „+“

    def __init__(self, ui, step, base, drag, drag_end):
        super().__init__()
        self.ui, self.step, self.base = ui, step, base
        self.drag, self.drag_end = drag, drag_end
        self.value, self.muted = None, False
        self.press = None       # laufende Berührung
        self.timer = None
        self.set_size_request(-1, self.MIN_H)
        add_cls(self, "volstrip")
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.BUTTON1_MOTION_MASK)
        self.connect("button-press-event", self.on_press)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("button-release-event", self.on_release)
        self.connect("grab-broken-event", lambda *_: self.cancel())
        self.connect("unmap", lambda *_: self.cancel())

    def set_state(self, value, muted):
        if (value, muted) != (self.value, self.muted):
            self.value, self.muted = value, muted
            self.queue_draw()

    @property
    def dragging(self):
        return bool(self.press and self.press["drag"])

    def zone_height(self, H):
        return min(self.ZONE * self.ui.f, 0.4 * H)    # in der Mitte bleibt immer Platz für die Zahl

    def zone_at(self, x, y):
        W, H = self.get_allocated_width(), self.get_allocated_height()
        if not (0 <= x < W and 0 <= y < H):
            return 0
        z = self.zone_height(H)
        return 1 if y < z else -1 if y >= H - z else 0

    # ----- Bedienung -----
    def stop_timer(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None

    def on_press(self, _w, ev):
        if ev.type != Gdk.EventType.BUTTON_PRESS or ev.button != 1:
            return True         # Doppeltipp-Zusatzereignisse nicht doppelt zählen
        self.cancel()
        zone = self.zone_at(ev.x, ev.y)
        self.press = {"y": ev.y, "v": self.base(), "zone": zone, "drag": False,
                      "repeated": False, "lit": zone}
        if zone:
            self.timer = GLib.timeout_add(450, self.start_repeat)
        self.queue_draw()
        return True

    def start_repeat(self):
        self.press["repeated"] = True
        self.step(self.press["zone"], True)
        self.timer = GLib.timeout_add(170, self.repeat)
        return False

    def repeat(self):
        self.step(self.press["zone"], False)
        return True

    def on_motion(self, _w, ev):
        p = self.press
        if not p:
            return False
        if not p["drag"] and abs(ev.y - p["y"]) > self.SLOP:
            self.stop_timer()
            v = self.base()
            if v is not None:
                p.update(drag=True, v=float(v), limit=max(self.DRAG_MAX, v), lit=0)
                self.queue_draw()
        if p["drag"]:
            self.move_to(ev.y)
        elif p["lit"] and self.zone_at(ev.x, ev.y) != p["zone"]:
            self.stop_timer()               # Finger von der Fläche gerutscht → nichts mehr auslösen
            p.update(lit=0, zone=0)
            self.queue_draw()
        return True

    def move_to(self, y):
        p = self.press
        new = p["v"] + (p["y"] - y) / max(1, self.get_allocated_height()) * m.MAX_VOL * self.GAIN
        new = int(round(max(0, min(m.MAX_VOL, p["limit"], new))))
        # Wer von oberhalb der Grenze herunterzieht, kommt nur bis zur Grenze wieder hinauf
        p["limit"] = max(self.DRAG_MAX, min(p["limit"], new))
        self.drag(new, p["v"])

    def on_release(self, _w, ev):
        p = self.press
        if not p or ev.button != 1:
            return False
        if p["drag"]:
            self.move_to(ev.y)
        elif not p["repeated"] and p["zone"] and self.zone_at(ev.x, ev.y) == p["zone"]:
            self.step(p["zone"], True)      # kurzer Tipp
        self.cancel()
        return True

    def cancel(self):
        """Berührung beenden; nach dem Ziehen immer den Endwert senden."""
        self.stop_timer()
        p, self.press = self.press, None
        if p:
            if p["drag"]:
                self.drag_end()
            self.queue_draw()
        return False

    # ----- Zeichnen -----
    def do_draw(self, cr):
        W, H = self.get_allocated_width(), self.get_allocated_height()
        ctx, f = self.get_style_context(), self.ui.f
        Gtk.render_background(ctx, cr, 0, 0, W, H)
        rad = min(ctx.get_property("border-radius", ctx.get_state()), W / 2, H / 2)
        cr.save()                               # alles Weitere in der abgerundeten Form halten
        cr.new_sub_path()
        for cx, cy, a in ((W - rad, rad, -0.5), (W - rad, H - rad, 0),
                          (rad, H - rad, 0.5), (rad, rad, 1)):
            cr.arc(cx, cy, rad, a * math.pi, (a + 0.5) * math.pi)
        cr.close_path()
        cr.clip()
        v = self.value

        def make_text(txt, scale):
            layout = self.create_pango_layout(txt)
            font = ctx.get_property("font", ctx.get_state()).copy()
            font.set_size(int(font.get_size() * scale))
            layout.set_font_description(font)
            return layout, layout.get_pixel_size()

        number = make_text("–" if v is None else ("%g" % v).replace(".", i18n.DEC), 0.75)
        if v is not None and v > 0:
            top = H * (1 - min(1.0, v / m.MAX_VOL))
            grey = (0.55, 0.56, 0.60)
            col = grey if self.muted else GOLD
            cr.set_source_rgba(*col, 0.20)
            cr.rectangle(0, top, W, H - top)
            cr.fill()
            cr.set_source_rgb(*col)
            edge = max(1.0, 2 * f)
            nw, nh = number[1]
            if abs(top - H / 2) < 0.4 * nh:      # Kante nicht quer durch die Zahl: dort aussparen
                side = (W - nw) / 2 - 10 * f
                cr.rectangle(0, top, side, edge)
                cr.rectangle(W - side, top, side, edge)
            else:
                cr.rectangle(0, top, W, edge)
            cr.fill()
        z = self.zone_height(H)
        if self.press and self.press["lit"]:    # gedrückte Fläche abdunkeln
            cr.set_source_rgba(0, 0, 0, 0.35)
            cr.rectangle(0, 0 if self.press["lit"] > 0 else H - z, W, z)
            cr.fill()
        # feine Skala rechts: ein Strich je 10, bei 0/30/60/90 etwas länger
        cr.set_line_width(1)
        cr.set_source_rgba(1, 1, 1, 0.13)
        for n in range(10, m.MAX_VOL, 10):
            y = round(H * (1 - n / m.MAX_VOL)) + 0.5
            cr.move_to(W - W * (0.11 if n % 30 == 0 else 0.07), y)
            cr.line_to(W, y)
        cr.stroke()
        cr.restore()
        Gtk.render_frame(ctx, cr, 0, 0, W, H)

        def show(text, cy, color):
            layout, (tw, th) = text
            cr.set_source_rgb(*color)
            cr.move_to((W - tw) / 2, cy - th / 2)
            PangoCairo.show_layout(cr, layout)

        light = (0.925, 0.922, 0.910)           # Schriftfarbe der Knöpfe (#ecebe8)
        show(make_text("+", 1.0), z / 2, light)
        show(make_text("−", 1.0), H - z / 2, light)
        show(number, H / 2, (0.54, 0.55, 0.58) if self.muted else GOLD)
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
SERVERS = "@servers"  # Kennung der Server-Auswahl in der Mediathek
LIB_PAGE = 60       # Einträge je Nachladen in der Mediathek (mehr lässt die Oberfläche stocken)
COVER_BYTES = 8 * 1024 * 1024
COVER_PIXELS = 16_000_000          # größere Bilder gar nicht erst entpacken
COVER_RETRY = 30    # s bis zum neuen Versuch, wenn ein Cover nicht geladen werden konnte
VOICE_START_WAIT = 60   # s höchstens für das Laden des Sprachmodells
VOICE_WAIT = 20         # s höchstens auf eine Erkennung warten
SEEK_DELAY = 300    # ms Ruhe nach dem letzten Tipp auf den Balken, dann spulen
STATUS_FAILS = 3    # so viele Fehlabfragen in Folge, bis "Keine Verbindung" erscheint
STATUS_FRESH = 8    # s; mit älterem Stand wird die Lautstärke nicht relativ verstellt


class ServiceError(RuntimeError):
    """Fehler vom Hintergrunddienst; source: "receiver", "plex" oder "dienst"."""

    def __init__(self, text, source="dienst"):
        super().__init__(text)
        self.source = source


def api(path, timeout=60):
    try:
        req = urllib.request.Request(SERVER + path, headers={"X-Marantz": "1"})
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        try:                                    # echten Fehlertext aus der Antwort lesen
            r = json.loads(e.read())
            raise ServiceError(r["error"], r.get("source", "dienst")) from None
        except (ValueError, KeyError, TypeError):
            raise ServiceError(str(e)) from None
    except OSError:
        raise ServiceError(_("Hintergrunddienst antwortet nicht"), "app") from None


def err_text(e):
    """Fehlermeldung mit der Stelle, an der es wirklich hakt."""
    source = getattr(e, "source", "receiver" if isinstance(e, OSError) else "")
    head = {"receiver": "Receiver-Fehler: {}", "plex": "Medienserver-Fehler: {}",
            "dienst": "Fehler im Hintergrunddienst: {}"}.get(source, "Fehler: {}")
    return _(head).format(_(str(e)))


def load_pixbuf(url):
    """Bild aus dem Netz laden – mit Grenzen für Dateigröße und Bildfläche."""
    data = m.read_limited(urllib.request.urlopen(url, timeout=6), COVER_BYTES)
    loader = GdkPixbuf.PixbufLoader()

    def check(ld, w, h):
        if w * h > COVER_PIXELS:
            ld.set_size(0, 0)               # bricht das Entpacken mit einem Fehler ab
    loader.connect("size-prepared", check)
    try:
        loader.write(data)
    finally:
        try:
            loader.close()
        except GLib.Error:
            pass
    pb = loader.get_pixbuf()
    if pb is None:
        raise ValueError("Bild nicht lesbar oder zu groß")
    return pb


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
        super().__init__(title="Touch Remote for Marantz")
        here = Path(__file__).resolve().parent
        self.set_icon_from_file(str(here / "icon.svg"))
        self.set_default_size(1500, 1000)
        self.st, self.cfg = {}, {}
        self.vol_shown = None        # angezeigte Lautstärke
        self.vol_target = None       # Ziel beim schnellen Tippen/Halten
        self.vol_local_until = 0.0   # bis dahin Status-Lautstärke ignorieren
        self.reload_settings = False
        self.err_timer = None
        self.status_busy = self.status_again = False
        self.status_fails = 0
        # Abfragezeit des angezeigten Stands (Uhrzeit, zählt auch die Bereitschaft mit)
        self.status_time = self.status_asked = self.status_valid_from = 0.0
        # Drei getrennte Warteschlangen, damit Lautstärke und Stumm nie warten müssen:
        self.worker = Worker(self.show_err, self.after_commands)    # kurze Befehle an den Receiver
        self.service = Worker(self.show_err, self.after_slow)       # Hintergrunddienst/Mediathek
        self.slow = Worker(self.show_err, self.after_slow)          # Szenen und Grafik-EQ
        self.vol_user_gen = 0        # zählt Lautstärke-Eingriffe von Hand

        self.css_prov = Gtk.CssProvider()
        self.css_prov.load_from_data(scaled_css(1.0))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.css_prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.ui = UiScale()
        self.scale_target, self.scale_timer = None, None

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
        self.content = top_ov
        shell = Shrinkable()
        shell.add(top_ov)
        self.add(shell)
        outer.pack_start(self.build_left(), False, False, 0)
        outer.pack_start(self.build_center(), True, True, 0)
        outer.pack_start(self.build_right(), False, False, 0)
        self.help_box = self.build_help()
        top_ov.add_overlay(self.help_box)

        self.voice_proc, self.voice_busy, self.voice_last = None, False, time.time()
        GLib.timeout_add_seconds(60, self.voice_idle_check)
        self.connect("destroy", self.on_destroy)
        self.keys_held, self.power_asked = {}, 0.0
        self.kfocus = None          # per Tastatur ausgewähltes Element
        self.lib_row_at = 0         # Zeile der Mediathek, die zuletzt ausgewählt war
        self.lib_row_memory = {}    # je Ordnertiefe: Zeile, von der aus er geöffnet wurde
        self.lib_row_wanted = None  # nach dem Laden auswählen
        self.connect("key-press-event", self.on_key)
        self.connect("key-release-event", self.on_key_release)
        self.connect("focus-out-event", lambda *_: self.keys_held.clear())
        self.connect("window-state-event", self.on_window_state)
        # Mauszeiger: bei Touch unsichtbar, bei Touchpad/Maus kurz sichtbar
        self.cursor_timer = None
        self.connect("realize", lambda *_: self.hide_cursor())
        Gdk.event_handler_set(self.on_any_event, None)
        self.fullscreen()
        self.is_full = True
        # Startgröße = Bildschirm (Vollbild); spätere Größenänderungen kommen über configure-event
        mon = Gdk.Display.get_default().get_primary_monitor() or Gdk.Display.get_default().get_monitor(0)
        if mon:
            g = mon.get_geometry()
            self.request_scale(g.width, g.height, now=True)
        self.connect("configure-event", lambda _w, ev: self.request_scale(ev.width, ev.height))
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
        self.model_lbl = label("RECEIVER", "brand")          # wird durch das echte Modell ersetzt
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

        rail.pack_start(self.caption_with_edit("SZENEN", self.open_scene_editor), False, False, 10)
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
        rail.pack_start(self.build_menu(), False, False, 0)
        self.mic_btn = None
        if i18n.LANG == "de" and os.path.isdir(os.path.join(VOICE_DIR, "model")):
            self.mic_btn = button("🎤", self.voice_press, "mic")
            rail.pack_start(self.mic_btn, False, False, 14)
            rail.pack_start(label("SPRECHEN", "cap"), False, False, 0)
            rail.pack_start(Gtk.Box(), False, False, 14)
        rail.pack_start(label("LAUTSTÄRKE", "cap"), False, False, 6)
        self.vol_sent, self.vol_send_timer, self.vol_dragged = 0.0, None, False
        self.wheel_last = self.wheel_sent = self.last_key = 0      # Zeitstempel in ms
        self.strip = VolumeStrip(self.ui, self.vol_step, self.vol_base, self.drag_vol, self.drag_vol_end)
        self.strip.add_events(Gdk.EventMask.SCROLL_MASK)
        self.strip.connect("scroll-event", self.on_wheel)
        rail.pack_start(self.strip, True, True, 0)          # füllt den freien Platz
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
        self.pop_numbered = False
        top.pack_start(head_ev, False, False, 0)
        top.pack_start(Gtk.Box(), True, True, 0)
        mark_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        mark_box.set_valign(Gtk.Align.CENTER)
        mark_box.pack_start(label("TOUCH REMOTE", "wordmark", xalign=1), False, False, 0)
        mark_box.pack_start(add_cls(Gtk.Box(), "wordline"), False, False, 0)
        mark_box.pack_start(label("for Marantz", "wordsub", xalign=1), False, False, 0)
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
        self.err_lbl.set_line_wrap(True)
        self.err_lbl.set_max_width_chars(50)      # lange Meldungen umbrechen
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
        self.ring.add_events(Gdk.EventMask.SCROLL_MASK)
        self.ring.connect("scroll-event", self.on_wheel)
        ov.add(self.ring)
        mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        mid.set_halign(Gtk.Align.CENTER)
        self.ring_mid = mid
        mid._ui_keep_margin = True
        mid.set_valign(Gtk.Align.START)
        # Zahl genau in die (tiefer liegende) Ringmitte: Abstand nach dem Verteilen der Größen setzen
        self.ring.connect("size-allocate", lambda w, a: GLib.idle_add(self.place_ring_mid))
        mid.connect("size-allocate", lambda w, a: GLib.idle_add(self.place_ring_mid))  # neue Schriftgröße
        self.vol_lbl = label("–", "volnum")
        self.vol_font_prov, self.vol_font_pt = Gtk.CssProvider(), None
        self.vol_lbl.get_style_context().add_provider(self.vol_font_prov,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.vol_cap = label("LAUTSTÄRKE", "volcap")
        mid.pack_start(self.vol_lbl, False, False, 0)
        mid.pack_start(self.vol_cap, False, False, 0)
        ov.add_overlay(mid)
        page.pack_start(ov, True, True, 0)

        page.pack_start(self.caption_with_edit("EINGANG", self.open_input_editor), False, False, 0)
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

    # ----- Musik-Seite: Bibliothek des Medienservers + Wiedergabe (über den Hintergrunddienst) -----
    def build_media(self):
        self.lib_path = [("0", "Bibliothek")]
        self.lib_items, self.lib_total, self.lib_loading = [], 0, False
        self.lib_gen = 0            # zählt geöffnete Ordner (alte Antworten verwerfen)
        self.pl = {}
        self.pl_error_id = None
        self.player_busy = False
        self.seek_target, self.seek_timer, self.seek_gen = None, None, 0
        self.seek_queued, self.seek_until = False, 0
        self.art_cache = {}
        self.art_pb = None
        self.art_url = None
        self.shown_playing = self.shown_pid = self.shown_bar = None   # zuletzt Gezeichnetes

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
        head.pack_start(button("Server", self.lib_servers, "ctl"), False, False, 0)
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
        self.mini_cover.connect("draw", lambda w, cr: self.draw_art(w, cr, 14 / 84))
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
        self.np_cover.connect("draw", lambda w, cr: self.draw_art(w, cr, 26 / 440))
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
        self.np_format = label("", "np-format", xalign=0)      # z. B. FLAC · 1067 kbit/s · 44,1 kHz
        self.np_format.set_halign(Gtk.Align.START)
        self.np_format.set_ellipsize(3)
        self.np_format.set_opacity(0)                          # ohne Angaben unsichtbar
        info.pack_start(self.np_format, False, False, 6)
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
        self.lib_row_at = 0
        self.lib_gen += 1
        self.lib_loading = False        # eine noch laufende Abfrage gehört zum alten Stand
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
        gen = self.lib_gen

        def done(r):
            if gen != self.lib_gen:
                return
            self.lib_loading = False
            self.lib_total = r["total"]
            for it in r["items"]:
                self.lib_items.append(it)
                row = self.lib_row(it)
                self.lib_list.add(row)
                row.show_all()
            n = self.lib_total
            if r.get("open"):                    # Server nennt keine Gesamtzahl
                n = f"{len(self.lib_items)}+"
            self.media_pos.set_text("leer" if not n else _("{} Einträge").format(n) if n != 1 else "1 Eintrag")
            self.mark_playing()
            if self.lib_row_wanted is not None:
                GLib.idle_add(self.lib_select_wanted)   # erst nach dem Aufbau der Zeilen

        def fail(e):
            if gen != self.lib_gen:
                return
            self.lib_loading = False
            self.media_pos.set_text("")
            self.show_err(e)
            if str(e) == "Bitte Medienserver wählen" and oid != SERVERS:
                self.lib_servers()
        path = (f"/api/lib?id={urllib.parse.quote(oid)}&start={start}&count={LIB_PAGE}"
                if oid != SERVERS else "/api/servers")
        in_bg(lambda: api(path), done, fail)

    def lib_servers(self):
        """Auswahl des Medienservers – eine Liste wie ein Ordner (Zurück führt hinaus)."""
        if self.lib_path[-1][0] != SERVERS:
            self.lib_open(SERVERS, "Medienserver")

    def select_server(self, udn):
        def done(_r):
            self.lib_path = [("0", "Bibliothek")]
            self.lib_row_memory.clear()         # Zeilen gehörten zum alten Server
            self.lib_open("0", "Bibliothek", push=False)
        in_bg(lambda: api("/api/server?id=" + urllib.parse.quote(udn)), done, self.show_err)

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
        if it.get("current"):
            sub = "✓ " + _("aktuell")
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
        elif it["kind"] != "server":
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
        elif it["kind"] == "server":
            self.select_server(it["id"])
        elif it["kind"] == "track":
            parent, pos = self.lib_path[-1][0], row.get_index()
            self.seek_cancel()              # altes Spulziel gehört nicht zum neuen Titel
            self.pl.update(id=it["id"], title=it["title"], artist=it.get("artist"),
                           album=it.get("album"), art=it.get("art"), state="PLAYING",
                           format=it.get("format"), kbps=it.get("kbps"), rate=it.get("rate"),
                           bits=None, avg=None,
                           elapsed=0, duration=it.get("duration"), active=True,
                           index=None, count=None)
            # Ein paar Sekunden lang alte Statusmeldungen ignorieren, bis der Titel wirklich läuft
            self.pl_hold_until = time.time() + 6
            self.media_stack.set_visible_child_name("now")   # sofort Cover, Zeit, Spulen zeigen
            self.pl_render()
            self.service.put(lambda: api(f"/api/play?parent={urllib.parse.quote(parent)}"
                                         f"&item={urllib.parse.quote(it['id'])}&pos={pos}"))

    def playing_id(self):
        return self.pl.get("id") if self.pl.get("active") else None

    def mark_playing(self):
        pid = self.shown_pid = self.playing_id()
        for row in self.lib_list.get_children():
            set_cls(row, "playing", row.item.get("id") == pid)

    # ----- Wiedergabe -----
    def ctl(self, action, t=None):
        if action == "seek" and t is not None:
            return self.seek_to(t)
        if action in ("next", "prev", "stop"):
            self.seek_cancel()
        if action == "toggle":
            self.pl["state"] = "PAUSED_PLAYBACK" if self.pl.get("state") == "PLAYING" else "PLAYING"
        elif action == "stop":
            self.pl.update(state="STOPPED", active=False)
        self.pl_render()
        q = f"/api/ctl?a={action}"
        self.service.put(lambda: api(q))

    # ----- Spulen: bei schnellem Tippen nur das letzte Ziel senden -----
    def seek_to(self, t):
        d = self.pl.get("duration")
        t = max(0, int(min(t, d - 5) if d else t))      # nicht ganz ans Titelende
        self.seek_target = t
        self.seek_until = float("inf")                  # Anzeige am Ziel halten
        self.pl["elapsed"] = t
        self.pl_render()
        if self.seek_timer:
            GLib.source_remove(self.seek_timer)
        self.seek_timer = GLib.timeout_add(SEEK_DELAY, self.seek_send)

    def seek_send(self):
        self.seek_timer = None
        if not self.seek_queued:        # wartet schon ein Auftrag, nimmt er das neue Ziel mit
            self.seek_queued = True
            gen = self.seek_gen
            self.service.put(lambda: self.seek_job(gen))
        return False

    def seek_job(self, gen):            # läuft im Dienst-Thread
        if gen != self.seek_gen:        # inzwischen anderer Titel / abgebrochen
            return
        t, self.seek_queued = self.seek_target, False
        ok = False
        try:
            api(f"/api/ctl?a=seek&t={t}")
            ok = True
        finally:
            GLib.idle_add(self.seek_done, t, ok)

    def seek_done(self, t, ok):
        if self.seek_target == t and not self.seek_timer and not self.seek_queued:
            self.seek_until = time.time() + 2 if ok else 0
        return False

    def seek_cancel(self):
        if self.seek_timer:
            GLib.source_remove(self.seek_timer)
            self.seek_timer = None
        self.seek_gen += 1
        self.seek_target, self.seek_queued, self.seek_until = None, False, 0

    def on_bar_press(self, w, ev):
        if ev.type != Gdk.EventType.BUTTON_PRESS:       # Doppelklick-Zusatzereignisse
            return True
        d = self.pl.get("duration")
        if not d or not self.pl.get("id"):      # auch gestoppt: Titel startet dort
            return False
        W, pad = w.get_allocated_width(), self.bar_pad(w)
        frac = max(0.0, min(1.0, (ev.x - pad) / max(1, W - 2 * pad)))
        self.seek_to(d * frac)
        return True

    def media_tick(self):
        visible = self.stack.get_visible_child_name() == "media" or self.pl.get("active")
        if visible and not self.is_minimized() and not self.player_busy:
            self.player_busy = True         # nie zwei Abfragen gleichzeitig
            in_bg(lambda: api("/api/player", 10), self.player_done, self.player_failed)
        return True

    def player_done(self, pl):
        self.player_busy = False
        self.on_player(pl)

    def player_failed(self, _e):
        self.player_busy = False

    def media_refresh(self):
        if not self.lib_items and not self.lib_loading:
            self.lib_open(*self.lib_path[-1], push=False)
        self.media_tick()

    def on_player(self, pl):
        hold = getattr(self, "pl_hold_until", 0)
        if time.time() < hold and pl.get("id") != self.pl.get("id"):
            return   # Dienst meldet noch den alten Titel – gleich nochmal fragen
        if time.time() < hold and pl.get("state") not in ("PLAYING", "TRANSITIONING"):
            pl = dict(pl, state="PLAYING")
        if time.time() < self.seek_until and pl.get("id") == self.pl.get("id") and pl.get("active"):
            pl = dict(pl, elapsed=self.seek_target)
        self.pl = pl
        self.pl_render()
        eid = pl.get("error_id")                # neue Meldung aus der Wiedergabe?
        if eid != self.pl_error_id:
            if self.pl_error_id is not None and pl.get("error"):
                self.show_err(ServiceError(pl["error"], "receiver"))
            self.pl_error_id = eid

    def pl_render(self):
        pl = self.pl
        has = bool(pl.get("title")) and pl.get("count", 1) and (pl.get("active") or pl.get("title"))
        self.mini_rev.set_reveal_child(bool(has) and self.media_stack.get_visible_child_name() == "list")
        playing = pl.get("state") == "PLAYING"
        if playing != self.shown_playing:       # läuft jede Sekunde: nur Änderungen setzen
            self.shown_playing = playing
            for b in (self.mini_play, self.np_play):
                b.set_label("⏸" if playing else "▶")
                set_cls(b, "sel", playing)
        title = pl.get("title") or "–"
        update_text(self.mini_title, title)
        tm = f"{self.fmt_time(pl.get('elapsed') or 0)} / {self.fmt_time(pl.get('duration'))}"
        state = _({"PLAYING": "", "PAUSED_PLAYBACK": "Pause · ", "STOPPED": "Gestoppt · ",
                   "TRANSITIONING": "lädt … · "}.get(pl.get("state", ""), ""))
        short = self.fmt_audio(pl, rate=False)     # vorn, damit ein langer Name es nicht abschneidet
        update_text(self.mini_sub, (f"{short}  ·  " if short else "")
                    + f"{state}{pl.get('artist') or ''}  ·  {tm}")
        fmt = self.fmt_audio(pl)
        update_text(self.np_format, fmt)
        self.np_format.set_opacity(1 if fmt else 0)
        update_text(self.np_title, title)
        update_text(self.np_artist, pl.get("artist") or "")
        update_text(self.np_album, tr(pl.get("album") or ""))
        update_text(self.np_track, _("Titel {} von {}").format(pl["index"], pl["count"]) if pl.get("count") else "")
        update_text(self.np_elapsed, self.fmt_time(pl.get("elapsed") or 0))
        update_text(self.np_total, self.fmt_time(pl.get("duration")))
        bar = (pl.get("elapsed"), pl.get("duration"))
        if bar != self.shown_bar:
            self.shown_bar = bar
            self.np_bar.queue_draw()
        self.load_art(pl.get("art"))
        if self.playing_id() != self.shown_pid:     # neue Listenzeilen markiert lib_more selbst
            self.mark_playing()

    @staticmethod
    def fmt_audio(pl, rate=True):
        """„FLAC · Ø 2900 kbit/s · 24 Bit / 96 kHz“ – nur Bekanntes; Ø = Durchschnitt."""
        parts = [pl.get("format") or ""]
        if pl.get("kbps"):
            parts.append(("Ø " if pl.get("avg") else "") + f"{pl['kbps']} kbit/s")
        if rate and pl.get("rate"):
            khz = f"{pl['rate'] / 1000:g}".replace(".", i18n.DEC) + " kHz"
            parts.append(f"{pl['bits']} Bit / {khz}" if pl.get("bits") else khz)
        return " · ".join(p for p in parts if p)

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

        target = max(480, self.np_cover.get_allocated_width())   # nicht unscharf auf großen Schirmen

        def fetch():
            pb = load_pixbuf(url)
            s = target / max(pb.get_width(), pb.get_height())
            return pb.scale_simple(max(1, int(pb.get_width() * s)), max(1, int(pb.get_height() * s)),
                                   GdkPixbuf.InterpType.BILINEAR)

        def done(pb):
            if len(self.art_cache) > 30:
                self.art_cache.clear()
            self.art_cache[url] = pb
            if self.art_url == url:
                self.art_pb = pb
                self.mini_cover.queue_draw()
                self.np_cover.queue_draw()

        def retry():
            if self.art_url == url and self.art_pb is None:
                self.art_url = None             # die nächste Statusmeldung lädt neu
            return False

        def fail(_e):
            if self.art_url == url:             # nie das Cover des vorigen Titels stehen lassen
                self.art_pb = None
                self.mini_cover.queue_draw()
                self.np_cover.queue_draw()
                GLib.timeout_add_seconds(COVER_RETRY, retry)
        in_bg(fetch, done, fail)

    @staticmethod
    def fmt_time(sec):
        if sec is None:
            return "–:––"
        h, rest = divmod(int(sec), 3600)
        mi, se = divmod(rest, 60)
        return f"{h}:{mi:02d}:{se:02d}" if h else f"{mi}:{se:02d}"

    def draw_art(self, w, cr, rr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        size = min(W, H)
        r = size * rr                               # Eckradius als Anteil der Cover-Größe
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

    @staticmethod
    def bar_pad(w):
        return w.get_allocated_height() * 12 / 44     # Referenz: 12 px Rand bei 44 px Höhe

    def draw_progress(self, w, cr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        cy, pad = H / 2, self.bar_pad(w)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(H * 8 / 44)
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
        cr.arc(x1, cy, pad, 0, 2 * math.pi)
        cr.fill()
        return False

    def open_input_pop(self, numbered=False):
        self.pop_numbered = numbered        # über die Tastatur geöffnet: Ziffern anzeigen
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
            text = f"{(i + 1) % 10}  ·  {_(name)}" if self.pop_numbered and i < 10 else name
            b = button(text, lambda c=code: (self.input_pop.popdown(), self.select_input(c)), "popbtn")
            set_cls(b, "sel", name.lower().replace(" ", "") == cur)
            self.pop_grid.attach(b, i % 3, i // 3, 1, 1)
        self.pop_grid.show_all()
        return False

    def select_input(self, code):
        self.cmd(code)
        if code == "SISERVER":
            self.show_page("media")

    def caption_with_edit(self, text, cb):
        """Überschrift mittig, ✎ als kleiner runder Knopf direkt daneben."""
        cap = Gtk.Box(spacing=10)
        cap.set_halign(Gtk.Align.CENTER)
        ph = Gtk.Box()
        ph.set_size_request(38, -1)                  # gleich breiter Platzhalter → Text bleibt mittig
        cap.pack_start(ph, False, False, 0)
        lb = label(text, "cap")
        lb.set_valign(Gtk.Align.CENTER)
        cap.pack_start(lb, False, False, 0)
        cap.pack_start(button("✎", cb, "edit"), False, False, 0)
        return cap

    # ----- Sprache (🌐) -----
    LANG_NAMES = {"auto": "Auto", "de": "Deutsch", "en": "English"}

    def build_menu(self):
        """Rechts oben: Spiegelbild des Ein/Aus-Knopfs links – ein runder Menü-Knopf."""
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        top.set_halign(Gtk.Align.CENTER)
        top.pack_start(label("MENÜ", "brand"), False, False, 0)
        self.menu_btn = button("☰", self.open_menu, "power", "menu")
        self.menu_btn.set_halign(Gtk.Align.CENTER)
        top.pack_start(self.menu_btn, False, False, 0)
        lang = m.load_config().get("language", "auto")
        sub = Gtk.Box(spacing=8)
        sub.set_halign(Gtk.Align.CENTER)
        g = Gtk.DrawingArea()                      # gleicher Globus wie im Menü, passend zum Design
        g.set_size_request(18, 18)
        g.set_valign(Gtk.Align.CENTER)
        g.connect("draw", self.draw_globe)
        sub.pack_start(g, False, False, 0)
        self.menu_sub = label(self.LANG_NAMES.get(lang, "Auto"), "status-sub")
        sub.pack_start(self.menu_sub, False, False, 0)
        top.pack_start(sub, False, False, 0)

        self.menu_pop = Gtk.Popover(relative_to=self.menu_btn, position=Gtk.PositionType.LEFT)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(18)

        def item(icon, text, cb):
            b = Gtk.Button()
            b.set_can_focus(False)
            add_cls(b, "menuitem")
            row = Gtk.Box(spacing=18)
            ic = icon if isinstance(icon, Gtk.Widget) else label(icon, "menu-icon")
            ic.set_size_request(34, -1)
            row.pack_start(ic, False, False, 0)
            row.pack_start(label(text, "menu-text", xalign=0), True, True, 0)
            b.add(row)
            b.connect("clicked", lambda *_: (self.menu_pop.popdown(), cb()))
            return b

        box.pack_start(item("⚙", "Einstellungsmenü am Fernseher", self.open_setup), False, False, 0)
        lang_head = Gtk.Box(spacing=12)
        globe = Gtk.DrawingArea()
        globe.set_size_request(24, 24)
        globe.connect("draw", self.draw_globe)
        lang_head.pack_start(globe, False, False, 4)
        # absichtlich zweisprachig, damit jeder seine Sprache findet
        lang_head.pack_start(label("SPRACHE / LANGUAGE", "cap", xalign=0), False, False, 0)
        box.pack_start(lang_head, False, False, 10)
        row = Gtk.Box(spacing=8, homogeneous=True)
        self.lang_btns = {}
        for code, name in (("auto", "Auto"), ("de", "Deutsch"), ("en", "English")):
            btn = Gtk.Button(label=name)          # Sprachnamen NICHT übersetzen
            btn.set_can_focus(False)
            add_cls(btn, "chip")
            btn.connect("clicked", lambda _b, c=code: self.choose_lang(c))
            self.lang_btns[code] = btn
            row.pack_start(btn, True, True, 0)
        box.pack_start(row, False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 8)
        box.pack_start(item("⌨", "Tastaturkürzel", self.toggle_help), False, False, 0)
        box.pack_start(item("▁", "Minimieren", self.iconify), False, False, 0)
        box.pack_start(item("✕", "App beenden", Gtk.main_quit), False, False, 0)
        box.show_all()
        self.menu_pop.add(box)
        return top

    def open_menu(self):
        mark(self.lang_btns, m.load_config().get("language", "auto"))
        self.menu_pop.popup()

    @staticmethod
    def draw_globe(w, cr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        cx, cy, r = W / 2, H / 2, min(W, H) / 2 * 10 / 12   # Referenz: r = 10 bei 24 px
        cr.set_source_rgb(0.73, 0.74, 0.76)
        cr.set_line_width(max(1.0, r * 0.16))
        cr.arc(cx, cy, r, 0, 2 * math.pi)                  # Umriss
        cr.stroke()
        cr.save()                                          # Meridian (schmale Ellipse)
        cr.translate(cx, cy)
        cr.scale(0.45, 1)
        cr.arc(0, 0, r, 0, 2 * math.pi)
        cr.restore()
        cr.stroke()
        cr.move_to(cx, cy - r)                             # Mittel-Meridian
        cr.line_to(cx, cy + r)
        cr.move_to(cx - r, cy)                             # Äquator
        cr.line_to(cx + r, cy)
        for k in (-0.5, 0.5):                              # Breitenkreise
            y = cy + k * r
            dx = r * math.sqrt(1 - k * k) * 0.92
            cr.move_to(cx - dx, y)
            cr.line_to(cx + dx, y)
        cr.stroke()
        return False

    def choose_lang(self, code):
        self.menu_pop.popdown()
        cfg = m.load_config()
        if cfg.get("language", "auto") == code:
            return
        cfg["language"] = code
        m.save_config(cfg)
        self.toast({"de": "Sprache: Deutsch – App startet neu …",
                    "en": "Language: English – restarting …"}.get(code, "Auto – restarting …"), None)
        GLib.timeout_add(700, self.restart_app)

    def restart_app(self):
        """Neu starten, damit alle Texte in der neuen Sprache aufgebaut werden."""
        if self.voice_proc and self.voice_proc.poll() is None:
            self.voice_proc.terminate()
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:])

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
        gen = self.vol_user_gen
        self.slow.put(lambda: m.run_profile(p, lambda: gen != self.vol_user_gen))

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
        # loaded = Gruppe, deren echte Werte die Regler zeigen (None: gesperrt, nichts senden)
        self.geq = {"group": "FRO", "loaded": None, "seq": 0, "timer": None, "updating": False,
                    "confirm0": False}
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
        bands.set_sensitive(False)
        self.geq_bands = bands
        self.geq_box.pack_start(bands, True, True, 10)
        foot = Gtk.Box(spacing=12)
        self.geq_status = label("", "status-sub", xalign=0)
        foot.pack_start(self.geq_status, True, True, 0)
        self.geq_zero_btn = button("Alle auf 0", self.geq_zero, "toggle-sm")
        self.geq_zero_btn.set_sensitive(False)
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
        if self.geq["timer"]:            # offene Änderung zuerst speichern
            GLib.source_remove(self.geq["timer"])
            self.geq_send()
        self.geq_lock_ui(None)
        self.geq["seq"] += 1
        seq = self.geq["seq"]
        self.geq_status.set_text("lädt …")

        def done(st):
            if seq == self.geq["seq"]:
                self.geq_show(st)

        def fail(e):
            if seq == self.geq["seq"]:
                self.geq_status.set_text(_("Nicht erreichbar: {}").format(_(str(e))))
        # über dieselbe Warteschlange wie das Speichern: erst speichern, dann lesen
        self.slow.put(lambda: self.geq_job(lambda: m.geq_read(group), done, fail))

    @staticmethod
    def geq_job(fn, done, fail):         # läuft im Szenen/EQ-Thread
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001
            GLib.idle_add(fail, e)
        else:
            GLib.idle_add(done, r)

    def geq_lock_ui(self, loaded):
        self.geq["loaded"] = loaded
        self.geq_bands.set_sensitive(loaded is not None)
        self.geq_zero_btn.set_sensitive(loaded is not None)

    def geq_show(self, st):
        self.geq["group"] = st["group"]
        mark(self.geq_group_btns, st["group"])
        self.geq["updating"] = True
        for b, v in st["vals"].items():
            self.geq_scales[b].set_value(v)
            self.geq_vals[b].set_text(self.geq_fmt(v))
        self.geq["updating"] = False
        self.geq_status.set_text("")
        self.geq_lock_ui(st["group"])
        return False

    @staticmethod
    def geq_fmt(v):
        return "0" if v == 0 else ("%+.1f" % v).replace(".0", "").replace(".", i18n.DEC).replace("-", "−")

    def geq_changed(self, band, scale):
        v = round(scale.get_value() * 2) / 2
        self.geq_vals[band].set_text(self.geq_fmt(v))
        set_cls(self.geq_vals[band], "changed", v != 0)
        if self.geq["updating"] or self.geq["loaded"] is None:
            return
        self.geq_status.set_text("…")
        if self.geq["timer"]:
            GLib.source_remove(self.geq["timer"])
        self.geq["timer"] = GLib.timeout_add(700, self.geq_send)

    def geq_send(self):
        self.geq["timer"] = None
        group = self.geq["loaded"]
        if group is None:               # ohne geladene Werte niemals schreiben
            return False
        vals = {b: round(sc.get_value() * 2) / 2 for b, sc in self.geq_scales.items()}
        self.geq_status.set_text("speichere …")

        def job():
            try:
                st = m.geq_set(group, vals)
                GLib.idle_add(self.geq_saved, st, vals)
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self.geq_status.set_text, _("Fehler: {}").format(_(str(e))))
        self.slow.put(job)
        return False

    def geq_saved(self, st, sent):
        if st["group"] != self.geq["loaded"]:   # inzwischen andere Gruppe: Anzeige nicht anfassen
            return False
        ok = all(abs(st["vals"][b] - sent[b]) < 0.01 for b in sent)
        self.geq_status.set_text("Gespeichert ✓" if ok else "Receiver hat andere Werte gemeldet")
        if not ok and not self.geq["timer"]:
            self.geq_show(st)
        return False

    def geq_switch(self, group):
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
        Mittelpunkt tiefer – so nutzt der Ring die Fläche voll aus.
        Alle Abstände sind Anteile vom Radius (Referenz: 54 bzw. 34 px bei r = 320)."""
        p, q = 54 / RING_R0, 34 / RING_R0           # oben Platz fürs Glühen, unten für Beschriftung
        r = max(20.0, min(W / (2 + 2 * p), H / (1 + math.sin(math.pi / 4) + p + q)))
        return W / 2, p * r + r, r

    def place_ring_mid(self):
        a = self.ring.get_allocation()
        cx, cy, r = self.ring_layout(a.width, a.height)
        # Zahl wächst mit dem Ring (62 pt bei r = 320); nur bei spürbarer Änderung neu setzen
        pt = max(UI_MIN_PT * 2, round(62 * r / RING_R0 * 2) / 2)
        if pt != self.vol_font_pt:
            self.vol_font_pt = pt
            self.vol_font_prov.load_from_data(f"* {{ font-size: {pt:g}pt; }}".encode())
        mid = self.ring_mid
        h = mid.get_preferred_height()[1] - mid.get_margin_top() - mid.get_margin_bottom()
        top = max(0, int(cy - h / 2))
        if self.ring_mid.get_margin_top() != top:
            self.ring_mid.set_margin_top(top)
        return False

    @staticmethod
    def draw_knob(c, cx, cy, r):
        """Mattschwarzer Metall-Drehknopf in der Ringmitte (Licht von oben links).
        Alle Maße sind Anteile vom Radius r. Außen endet alles bei 0,81·r, damit Glühen,
        Punkt und Skala frei bleiben. Wird nur ins Grundbild gezeichnet (siehe draw_ring)."""
        R, R_face = 0.76 * r, 0.675 * r        # Außenkante bzw. glatte Deckfläche
        full = 2 * math.pi
        light = -0.75 * math.pi                # Richtung zur Lichtquelle (oben links)
        lx, ly = math.cos(light), math.sin(light)

        def disk(radius, source):
            c.set_source(source)
            c.arc(cx, cy, radius, 0, full)
            c.fill()

        def shade(radius, *stops):
            """Verlauf quer über den Knopf, von der Lichtseite zur Schattenseite."""
            g = cairo.LinearGradient(cx + lx * radius, cy + ly * radius,
                                     cx - lx * radius, cy - ly * radius)
            for pos, rgba in stops:
                g.add_color_stop_rgba(pos, *rgba)
            return g

        # weicher Schlagschatten, leicht nach unten versetzt
        sy = cy + 0.025 * r
        g = cairo.RadialGradient(cx, sy, 0.70 * r, cx, sy, 0.785 * r)
        g.add_color_stop_rgba(0, 0, 0, 0, 0.75)
        g.add_color_stop_rgba(1, 0, 0, 0, 0)
        c.set_source(g)
        c.arc(cx, sy, 0.785 * r, 0, full)
        c.fill()

        # Mantel mit feiner Riffelung: jede Rille hat eine helle und eine dunkle Flanke
        disk(R, shade(R, (0, (0.23, 0.24, 0.26, 1)), (0.5, (0.10, 0.105, 0.115, 1)),
                      (1, (0.045, 0.047, 0.052, 1))))
        teeth = 150
        step = full / teeth
        c.set_line_cap(cairo.LINE_CAP_BUTT)
        c.set_line_width(max(0.7, step * R * 0.36))
        for i in range(teeth):
            lit = 0.5 + 0.5 * math.cos(i * step - light)      # 1 = zum Licht, 0 = abgewandt
            for offset, rgba in ((0.0, (1, 1, 1, 0.03 + 0.17 * lit * lit)),
                                 (0.45, (0, 0, 0, 0.55))):
                a = (i + offset) * step
                ca, sa = math.cos(a), math.sin(a)
                c.set_source_rgba(*rgba)
                c.move_to(cx + R_face * ca, cy + R_face * sa)
                c.line_to(cx + 0.992 * R * ca, cy + 0.992 * R * sa)
                c.stroke()

        # Außenkante: schmaler Lichtreflex
        c.set_line_width(max(1.0, 0.005 * r))
        c.set_source(shade(R, (0, (1, 1, 1, 0.30)), (0.45, (1, 1, 1, 0.04)),
                           (1, (1, 1, 1, 0.10))))
        c.arc(cx, cy, R, 0, full)
        c.stroke()

        # Fase zwischen Riffelung und Deckfläche: dunkle Fuge, dann angeschrägte Kante
        disk(R_face + 0.008 * r, cairo.SolidPattern(0.02, 0.02, 0.025, 0.9))
        disk(R_face, shade(R_face, (0, (0.36, 0.37, 0.40, 1)), (0.5, (0.12, 0.125, 0.14, 1)),
                           (1, (0.20, 0.205, 0.225, 1))))

        # matte Deckfläche
        R_top = R_face - 0.018 * r
        disk(R_top, shade(R_top, (0, (0.150, 0.155, 0.170, 1)), (0.55, (0.085, 0.089, 0.100, 1)),
                          (1, (0.062, 0.065, 0.073, 1))))

        # feine Drehspuren: viele dünne Kreise, die nur zum Licht hin und gegenüber schimmern
        c.set_line_width(max(0.6, 0.0035 * r))
        rings, levels = 70, 4
        for level in range(levels):
            # ungleichmäßige, aber immer gleiche Stärke → wirkt wie echtes Metall.
            # Gleich starke Kreise gemeinsam zeichnen (4 Durchgänge statt 69, deutlich schneller)
            k = 0.022 + 0.008 * level
            c.set_source(shade(R_top, *[(pos, (1, 1, 1, k * s)) for pos, s in
                                        ((0, 1.0), (0.30, 0.25), (0.5, 0.05),
                                         (0.75, 0.20), (1, 0.55))]))
            for i in range(1, rings):
                if int(abs(math.sin(i * 12.9898)) * levels * 0.999) == level:
                    c.new_sub_path()
                    c.arc(cx, cy, R_top * i / rings, 0, full)
            c.stroke()

    def draw_ring(self, w, cr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        cx, cy, r = self.ring_layout(W, H)
        u = r / RING_R0                  # 1 Referenz-Pixel bei dieser Ringgröße
        a0, sweep = math.pi * 0.75, math.pi * 1.5
        v = self.vol_shown
        frac = 0 if v is None else max(0.0, min(1.0, v / m.MAX_VOL))
        muted = self.st.get("mute") or not self.st.get("power", True)

        glow = 0.0 if muted else getattr(self, "glow", 0.0)
        a_fill = a0 + sweep * frac
        # Grundbild (Knopf, Skalenstriche, Spur) nur bei neuer Größe zeichnen und zwischenspeichern
        sf = w.get_scale_factor()
        if getattr(self, "_ring_key", None) != (W, H, sf):
            img = cairo.ImageSurface(cairo.FORMAT_ARGB32, W * sf, H * sf)
            img.set_device_scale(sf, sf)
            c2 = cairo.Context(img)
            self.draw_knob(c2, cx, cy, r)
            c2.set_line_cap(cairo.LINE_CAP_ROUND)
            c2.set_line_width(max(1.0, 2 * u))
            for i in range(41):
                a = a0 + sweep * i / 40
                r1, r2 = r + 14 * u, r + (22 if i % 5 == 0 else 18) * u
                c2.set_source_rgba(1, 1, 1, 0.16 if i % 5 == 0 else 0.07)
                c2.move_to(cx + r1 * math.cos(a), cy + r1 * math.sin(a))
                c2.line_to(cx + r2 * math.cos(a), cy + r2 * math.sin(a))
                c2.stroke()
            c2.set_line_width(14 * u)
            c2.set_source_rgba(1, 1, 1, 0.06)
            c2.arc(cx, cy, r, a0, a0 + sweep)
            c2.stroke()
            # Kopie passend zum Bildschirm: lässt sich beim Glühen schneller auflegen
            surf = cr.get_target().create_similar(cairo.CONTENT_COLOR_ALPHA, W, H)
            c3 = cairo.Context(surf)
            c3.set_source_surface(img, 0, 0)
            c3.paint()
            self._ring_base, self._ring_key = surf, (W, H, sf)
        cr.set_source_surface(self._ring_base, 0, 0)
        cr.paint()
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        # beim Glühen: Striche im gefüllten Bereich golden (nur dann, kostet sonst nichts)
        if glow > 0.01:
            cr.set_line_width(max(1.0, 2 * u))
            for i in range(41):
                a = a0 + sweep * i / 40
                if a > a_fill:
                    break
                r1, r2 = r + 14 * u, r + (22 if i % 5 == 0 else 18) * u
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
                cr.set_line_width(width * u)
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
        cr.set_line_width((14 + 4 * glow) * u)
        cr.arc(cx, cy, r, a0, min(a1, a_loud))
        cr.stroke()
        if a1 > a_loud:
            cr.set_source_rgba(0.88, 0.40, 0.32, 0.65 if muted else 1.0)
            cr.arc(cx, cy, r, a_loud, a1)
            cr.stroke()
        # Markierung bei 80
        cr.set_source_rgba(0.88, 0.40, 0.32, 0.8)
        cr.set_line_width(max(1.0, 3 * u))
        r_in, r_out = r - 20 * u, r + 24 * u
        cr.move_to(cx + r_in * math.cos(a_loud), cy + r_in * math.sin(a_loud))
        cr.line_to(cx + r_out * math.cos(a_loud), cy + r_out * math.sin(a_loud))
        cr.stroke()
        # Punkt am Ende (beim Drehen größer und leuchtend)
        px, py = cx + r * math.cos(a1), cy + r * math.sin(a1)
        if glow > 0.01:
            col = RED if a1 > a_loud else GOLD
            halo = cairo.RadialGradient(px, py, 0, px, py, (26 + 26 * glow) * u)
            halo.add_color_stop_rgba(0, *col, 0.65 * glow)
            halo.add_color_stop_rgba(1, *col, 0)
            cr.set_source(halo)
            cr.arc(px, py, (26 + 26 * glow) * u, 0, 2 * math.pi)
            cr.fill()
        if self.ring_drag:
            cr.set_source_rgba(*GOLD, 0.25)
            cr.arc(px, py, 30 * u, 0, 2 * math.pi)
            cr.fill()
        cr.set_source_rgb(0.96, 0.92, 0.84) if not muted else cr.set_source_rgb(0.7, 0.7, 0.72)
        cr.arc(px, py, (16 if self.ring_drag else 9) * u, 0, 2 * math.pi)
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

    @staticmethod
    def voice_line(p, seconds):
        """Eine Antwortzeile vom Hilfsprozess; hängt er, wird er beendet."""
        if not select.select([p.stdout], [], [], seconds)[0]:
            p.kill()
            p.wait()
            raise RuntimeError(_("keine Antwort"))
        return p.stdout.readline()

    def voice_run(self):
        try:
            p = self.voice_proc
            if p is None or p.poll() is not None:
                p = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / "voice.py"),
                                      "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
                self.voice_proc = p
                if not self.voice_line(p, VOICE_START_WAIT):
                    raise RuntimeError("startet nicht")
                GLib.idle_add(self.toast, "🎤  Ich höre zu …", None)
            p.stdin.write(json.dumps({"max_sec": 6}) + "\n")
            p.stdin.flush()
            res = json.loads(self.voice_line(p, VOICE_WAIT) or '{"error": "keine Antwort"}')
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
        # Ein echter Befehl („stopp die Musik“) hat Vorrang; der Name zählt dann nur, wenn der
        # Satz praktisch nur aus ihm besteht.
        fill = ("bitte", "szene", "starte", "starten", "aktiviere", "mach", "mal")
        core = "".join(norm(w) for w in text.split() if norm(w) not in fill)
        loose = a is None or (a == "szene" and c.get("wert") != "aus")
        for i, p in enumerate(self.config["profiles"]):
            n = norm(p.get("name", ""))
            if len(n) >= 3 and (core == n or (loose and n in norm(text))):
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
        self.service.put(lambda: api(q))
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
            if t in (Gdk.EventType.BUTTON_PRESS, Gdk.EventType.TOUCH_BEGIN):
                self.set_kfocus(None)       # wer tippt oder klickt, braucht keine Markierung
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

    # ----- Größe anpassen (entprellt, damit beim Ziehen nichts ruckelt) -----
    def request_scale(self, W, H, now=False):
        if (W, H) == self.scale_target:
            return False
        self.scale_target = (W, H)
        if self.scale_timer:
            GLib.source_remove(self.scale_timer)
            self.scale_timer = None
        if now:
            self.apply_scale()
        else:
            self.scale_timer = GLib.timeout_add(250, self.apply_scale)   # erst wenn Ruhe ist
        return False

    def set_ui_factor(self, f):
        if abs(f - self.ui.f) < 0.005:
            return
        self.css_prov.load_from_data(scaled_css(f))
        self.ui.set_factor(f)

    def apply_scale(self):
        self.scale_timer = None
        W, H = self.scale_target
        self.fit_gen = getattr(self, "fit_gen", 0) + 1
        self.set_ui_factor(max(0.4, min(2.0, W / UI_REF_W, H / UI_REF_H)))
        # GTK misst neue Schriftgrößen erst nach dem nächsten Layout → dann prüfen
        GLib.idle_add(self.check_fit, self.fit_gen, 0, priority=GLib.PRIORITY_LOW)
        return False

    def check_fit(self, gen, tries):
        """Nachregeln, falls Schrift-Untergrenzen mehr Platz brauchen (höchstens 3×)."""
        if gen != self.fit_gen or tries >= 3 or self.ui.f <= 0.4:
            return False
        W, H = self.scale_target
        mn = self.content.get_preferred_size()[0]
        if mn.width > W or mn.height > H:
            self.set_ui_factor(max(0.4, self.ui.f * min(W / mn.width, H / mn.height) * 0.99))
            GLib.idle_add(self.check_fit, gen, tries + 1, priority=GLib.PRIORITY_LOW)
        return False

    # ----- Tastatur -----
    SEEK_KEY = 10           # s je Druck auf ← / →
    POWER_CONFIRM = 3       # s Zeit für den zweiten Druck auf P

    def key_repeat(self, ev):
        """True, wenn die Taste gehalten wird (automatische Wiederholung)."""
        last = self.keys_held.get(ev.hardware_keycode)
        self.keys_held[ev.hardware_keycode] = ev.time
        return last is not None and self.since(ev, last) < 1000

    def on_key_release(self, _w, ev):
        self.keys_held.pop(ev.hardware_keycode, None)
        return False

    def on_key(self, _w, ev):
        """True = Taste verarbeitet. Beim Tippen in Textfeldern wirken nur Esc, F11 und Strg."""
        key = Gdk.keyval_to_lower(ev.keyval)
        mods = ev.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK |
                           Gdk.ModifierType.SUPER_MASK)
        repeat = self.key_repeat(ev)
        digit = next((n for n in range(10) if key in (getattr(Gdk, f"KEY_{n}"),
                                                      getattr(Gdk, f"KEY_KP_{n}"))), None)
        if mods:                            # Alt/Super gehören dem System
            if mods != Gdk.ModifierType.CONTROL_MASK:
                return False
            if key == Gdk.KEY_q:
                Gtk.main_quit()
            elif key == Gdk.KEY_m:
                self.iconify()
            elif digit in (1, 2, 3):
                if not repeat:
                    self.run_profile(digit - 1)
            else:
                return False
            return True
        if ev.keyval in (Gdk.KEY_Tab, Gdk.KEY_KP_Tab, Gdk.KEY_ISO_Left_Tab):
            back = ev.keyval == Gdk.KEY_ISO_Left_Tab or ev.state & Gdk.ModifierType.SHIFT_MASK
            self.move_focus(-1 if back else 1)
            return True
        if key == Gdk.KEY_F11:
            (self.unfullscreen if self.is_full else self.fullscreen)()
            self.is_full = not self.is_full
            return True
        if key == Gdk.KEY_Escape:
            self.step_back()
            return True
        focus = self.get_focus()
        if isinstance(focus, Gtk.Entry) and focus.get_mapped():
            return False                    # beim Tippen steuert die Tastatur nur das Textfeld
        if key in (Gdk.KEY_F1, Gdk.KEY_question):
            if not repeat:
                self.toggle_help()
            return True
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            w = self.current_focus()
            if not repeat:
                if w is not None:
                    self.activate_focus(w)
                elif self.stack.get_visible_child_name() == "setup" and self.nav_root() is self.content:
                    self.cmd("MNENT")
            return True
        if key in (Gdk.KEY_plus, Gdk.KEY_KP_Add, Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            return self.volume_key(ev, key in (Gdk.KEY_plus, Gdk.KEY_KP_Add))
        arrows = {Gdk.KEY_Up: (0, -1), Gdk.KEY_Down: (0, 1),
                  Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0)}
        if key in arrows and self.nav_arrow(*arrows[key]):
            return True
        if key == Gdk.KEY_BackSpace and self.nav_root() is self.content:
            page = self.stack.get_visible_child_name()
            if page == "setup":
                self.cmd("MNRTN")
            elif page == "media" and not repeat:
                self.lib_back_key()
            return True
        if key in (Gdk.KEY_Up, Gdk.KEY_Down):
            return self.volume_key(ev, key == Gdk.KEY_Up)
        if key == Gdk.KEY_m:
            if not repeat:
                self.toggle_mute()
            return True
        if self.help_box.get_visible():     # bei offener Hilfe nichts weiter auslösen
            return True
        if self.input_pop.get_visible():
            if digit is not None and not repeat:
                n = (digit - 1) % 10        # 1–9, 0 = zehnter Eingang
                if n < len(self.all_sources):
                    self.input_pop.popdown()
                    self.select_input(self.all_sources[n][0])
            elif key == Gdk.KEY_i and not repeat:
                self.input_pop.popdown()
            return True
        if key in (Gdk.KEY_Left, Gdk.KEY_Right):
            self.seek_by(self.SEEK_KEY if key == Gdk.KEY_Right else -self.SEEK_KEY)
            return True
        action = {Gdk.KEY_space: "toggle", Gdk.KEY_n: "next", Gdk.KEY_b: "prev",
                  Gdk.KEY_s: "stop"}.get(key)
        if action:
            if not repeat and self.pl.get("title") and (action == "toggle" or self.pl.get("active")):
                self.ctl(action)
            return True
        pages = ("main", "sound", "eq", "media")
        if digit and digit <= len(pages):
            if not repeat:
                self.show_page(pages[digit - 1])
            return True
        if key == Gdk.KEY_i:
            if not repeat:
                self.open_input_pop(numbered=True)
            return True
        if key == Gdk.KEY_p:
            if not repeat:
                self.power_key()
            return True
        return False

    # ----- Auswahl mit Tab und Pfeilen -----
    def nav_root(self):
        """Bereich, in dem ausgewählt wird: Hilfe, offenes Popup oder die ganze Oberfläche."""
        if self.help_box.get_visible():
            return self.help_box
        for pop in (self.input_pop, self.menu_pop):
            if pop.get_visible():
                return pop
        return self.content

    def nav_targets(self):
        """Auswählbare Elemente in Lesereihenfolge. Die Titelliste zählt als eine Station."""
        out = []

        def walk(w):
            if not (w.get_mapped() and w.is_sensitive()):
                return
            if w is self.lib_list:
                row = self.lib_row_widget()
                if row:
                    out.append(row)
                return
            if isinstance(w, (Gtk.Button, Gtk.Scale, Gtk.Entry)):
                out.append(w)
                return
            if isinstance(w, Gtk.Container):
                kids = w.get_children()
                if isinstance(w, Gtk.Grid):
                    kids.sort(key=lambda c: (w.child_get_property(c, "top-attach"),
                                             w.child_get_property(c, "left-attach")))
                for c in kids:
                    walk(c)
        walk(self.nav_root())
        return out

    def current_focus(self):
        """Ausgewähltes Element, falls es noch sichtbar und bedienbar ist."""
        w = self.kfocus
        if w is None:
            return None
        root = self.nav_root()
        if w.get_mapped() and w.is_sensitive() and (w is root or w.is_ancestor(root)):
            return w
        self.set_kfocus(None)
        return None

    def set_kfocus(self, w):
        old, self.kfocus = self.kfocus, w
        if old is w:
            return
        if old is not None:
            set_cls(old, "kbd", False)
            if isinstance(old, Gtk.Entry):
                self.set_focus(None)
        if w is not None:
            set_cls(w, "kbd", True)
            if isinstance(w, Gtk.Entry):
                w.grab_focus()
            if isinstance(w, Gtk.ListBoxRow):
                self.lib_row_at = w.get_index()
            self.scroll_to(w)

    def move_focus(self, step):
        targets = self.nav_targets()
        if not targets:
            return
        cur = self.current_focus()
        if cur is None:
            focus = self.get_focus()        # z. B. ein Textfeld, das GTK selbst gewählt hat
            cur = focus if focus in targets else None
        if cur in targets:
            new = targets[(targets.index(cur) + step) % len(targets)]
        else:
            new = targets[0 if step > 0 else -1]
        if not isinstance(new, Gtk.Entry):
            self.set_focus(None)
        self.set_kfocus(new)

    @staticmethod
    def scroll_to(w):
        """Ausgewähltes Element in einem Rollbereich sichtbar machen."""
        sw = w.get_ancestor(Gtk.ScrolledWindow)
        if not sw or not sw.get_child():
            return
        inner = sw.get_child()
        if isinstance(inner, Gtk.Viewport):
            inner = inner.get_child()
        pos = w.translate_coordinates(inner, 0, 0)
        if pos:
            sw.get_vadjustment().clamp_page(pos[1] - 6, pos[1] + w.get_allocated_height() + 6)

    def activate_focus(self, w):
        if isinstance(w, Gtk.ListBoxRow):
            if w.item["kind"] in ("folder", "server"):
                self.lib_row_memory[len(self.lib_path)] = w.get_index()
                self.lib_row_wanted = 0
                self.set_kfocus(None)
            self.on_row(self.lib_list, w)
        elif isinstance(w, HoldButton):
            w.cb(True)
        elif isinstance(w, Gtk.Button):
            w.clicked()

    # ----- Titelliste -----
    def lib_visible(self):
        return (self.stack.get_visible_child_name() == "media" and
                self.media_stack.get_visible_child_name() == "list")

    def lib_row_widget(self):
        rows = self.lib_list.get_children()
        return rows[min(self.lib_row_at, len(rows) - 1)] if rows else None

    def lib_move(self, step):
        rows = self.lib_list.get_children()
        if not rows:
            return
        cur = self.current_focus()
        if cur in rows:
            i = max(0, min(len(rows) - 1, rows.index(cur) + step))
        else:
            i = min(self.lib_row_at, len(rows) - 1)
        self.set_focus(None)
        self.set_kfocus(rows[i])
        if i >= len(rows) - 5 and len(rows) < self.lib_total:
            self.lib_more()

    def lib_back_key(self):
        if self.media_stack.get_visible_child_name() == "now":
            self.media_stack.set_visible_child_name("list")
        elif len(self.lib_path) > 1:
            self.lib_row_wanted = self.lib_row_memory.pop(len(self.lib_path) - 1, 0)
            self.set_kfocus(None)
            self.lib_up()

    def lib_select_wanted(self):
        """Nach dem Öffnen eines Ordners per Tastatur gleich wieder eine Zeile auswählen."""
        want = self.lib_row_wanted
        rows = self.lib_list.get_children()
        if want is None or not rows:
            return False
        if want >= len(rows) and len(rows) < self.lib_total:
            self.lib_more()             # die gemerkte Zeile liegt auf einer späteren Seite
            return False
        self.lib_row_wanted = None
        if self.lib_visible():
            self.lib_row_at = min(want, len(rows) - 1)
            self.set_kfocus(rows[self.lib_row_at])
            GLib.idle_add(lambda: self.kfocus is not None and self.scroll_to(self.kfocus) and False)
        return False

    def volume_key(self, ev, up):
        # gehaltene Taste (Wiederholung) zählt nicht als neuer Druck
        first = self.since(ev, self.last_key) >= self.NEW_PRESS
        self.last_key = ev.time
        self.vol_step(+1 if up else -1, first)
        return True

    def nav_arrow(self, dx, dy):
        """Pfeiltaste dort verwenden, wo etwas auszuwählen ist. False = sonst (Lautstärke, Spulen)."""
        if self.help_box.get_visible():
            return True
        if self.input_pop.get_visible():            # Raster mit drei Spalten
            self.move_focus(dx + 3 * dy)
            return True
        if self.menu_pop.get_visible():
            self.move_focus(dx + dy)
            return True
        w = self.current_focus()
        if isinstance(w, Gtk.Scale) and dy:
            w.set_value(w.get_value() - 0.5 * dy)
            return True
        page = self.stack.get_visible_child_name()
        if page == "setup":                         # Menü am Fernseher
            self.cmd({(0, -1): "MNCUP", (0, 1): "MNCDN", (-1, 0): "MNCLT", (1, 0): "MNCRT"}[dx, dy])
            return True
        if dy and self.lib_visible():
            self.lib_move(dy)
            return True
        return False

    def step_back(self):
        """Esc: immer nur einen Schritt zurück, nie die App beenden."""
        page = self.stack.get_visible_child_name()
        if self.help_box.get_visible():
            self.help_box.hide()
        elif self.input_pop.get_visible():
            self.input_pop.popdown()
        elif self.menu_pop.get_visible():
            self.menu_pop.popdown()
        elif page in ("edit_scenes", "edit_inputs"):
            self.set_kfocus(None)
            self.show_page("main")      # wie „Abbrechen“
        elif self.current_focus() is not None and not isinstance(self.kfocus, Gtk.ListBoxRow):
            self.set_kfocus(None)       # erst die Markierung aufheben
        elif page == "setup":
            self.close_setup()
        elif page == "media":
            self.lib_back_key()

    def seek_by(self, seconds):
        pl = self.pl
        if not (pl.get("active") and pl.get("duration")):
            return                      # gestoppt: Spulen würde die Wiedergabe starten
        pending = self.seek_target if time.time() < self.seek_until else None
        base = pending if pending is not None else pl.get("elapsed") or 0
        self.seek_to(base + seconds)

    def power_key(self):
        """Ein/Aus erst beim zweiten Druck, damit nichts aus Versehen ausgeht."""
        if time.time() - self.power_asked < self.POWER_CONFIRM:
            self.power_asked = 0.0
            self.toast_hide()
            self.toggle_power()
        else:
            self.power_asked = time.time()
            self.toast("Zum Ein-/Ausschalten noch einmal P drücken", self.POWER_CONFIRM)

    # ----- Hilfe mit allen Tasten -----
    KEY_HELP = (("+  −  ↑  ↓", "Lautstärke"), ("M", "Stumm"),
                ("Leertaste", "Wiedergabe / Pause"), ("←  →", "10 Sekunden zurück / vor"),
                ("N  B  S", "Nächster / voriger Titel / Stopp"),
                ("1 – 4", "Bedienung, Klang & Pegel, EQ, Mediathek"),
                ("I", "Eingang wählen, dann Ziffer"), ("Strg + 1 – 3", "Szene starten"),
                ("Tab  ⇧ Tab", "Knopf oder Regler auswählen"), ("Enter", "Auswahl auslösen"),
                ("↑ ↓ ← →", "In Listen und Menüs: auswählen"),
                ("Rücktaste", "Zurück (Mediathek, Fernsehmenü)"),
                ("P  P", "Receiver ein / aus"), ("Esc", "Einen Schritt zurück"),
                ("Strg + M", "Minimieren"), ("Strg + Q", "App beenden"),
                ("F11", "Vollbild an / aus"), ("F1  ?", "Diese Hilfe"))

    def build_help(self):
        card = add_cls(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18), "help")
        card.pack_start(label("TASTATUR", "cap", xalign=0), False, False, 0)
        grid = Gtk.Grid(column_spacing=40, row_spacing=10)
        for row, (keys, text) in enumerate(self.KEY_HELP):
            grid.attach(label(keys, "help-key", xalign=0), 0, row, 1, 1)
            grid.attach(label(text, "help-text", xalign=0), 1, row, 1, 1)
        card.pack_start(grid, False, False, 0)
        card.pack_start(button("Schließen", lambda: self.help_box.hide(), "chip"), False, False, 0)
        card.show_all()
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.CENTER)
        card.set_no_show_all(True)
        card.hide()
        return card

    def toggle_help(self):
        self.menu_pop.popdown()
        self.input_pop.popdown()
        self.help_box.set_visible(not self.help_box.get_visible())

    def show_err(self, e=None):
        """Fehler unten anzeigen; verschwindet nach 3 s von selbst."""
        if self.err_timer:
            GLib.source_remove(self.err_timer)
            self.err_timer = None
        self.err_lbl.set_text(err_text(e) if e else "")
        if e:
            syslog.syslog(syslog.LOG_WARNING, err_text(e))
            self.err_timer = GLib.timeout_add(3000, self.hide_err)

    def hide_err(self):
        self.err_timer = None
        self.err_lbl.set_text("")
        return False

    def after_slow(self):
        GLib.timeout_add(400, self.refresh_once)

    def after_commands(self):
        GLib.timeout_add(400, self.refresh_once)
        if self.reload_settings:
            self.reload_settings = False
            GLib.timeout_add(600, self.load_settings_once)

    def cmd(self, c):
        if c.startswith("MU"):          # Stumm von Hand: Szene setzt danach keine Lautstärke mehr
            self.vol_user_gen += 1
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
        self.slow.put(lambda: m.run_scene(key))

    def vol_base(self):
        """Wert, von dem aus verstellt wird; None, solange er nicht sicher aktuell ist."""
        if time.time() < self.vol_local_until:
            return self.vol_target
        if time.time() - self.status_time > STATUS_FRESH:
            self.refresh()          # z. B. nach der Bereitschaft: erst neu lesen
            return None
        return self.st.get("volume")

    def vol_step(self, d, first=True):
        base = self.vol_base()
        if base is None:
            return
        if first:
            self.gesture_start = base    # neuer Druck: von hier aus zählt der sanfte Stopp
        self.set_vol(int(round(base)) + d)

    # ----- Mausrad über Ring oder Streifen -----
    WHEEL_STEP = 100        # ms; höchstens ein Schritt in dieser Zeit (Touchpads feuern sehr schnell)
    NEW_PRESS = 600         # ms Ruhe = neues Ansetzen (erst dann geht es über 80 weiter)

    @staticmethod
    def since(ev, last):
        """ms zwischen zwei Eingaben – laut Zeitstempel der Eingabe, nicht der Verarbeitung:
        hängt die Oberfläche kurz, darf das nicht wie eine Pause aussehen."""
        return (ev.time - last) % 2 ** 32

    def on_wheel(self, _w, ev):
        step = {Gdk.ScrollDirection.UP: 1, Gdk.ScrollDirection.DOWN: -1}.get(ev.direction)
        if not step:
            return False
        new = self.since(ev, self.wheel_last) >= self.NEW_PRESS
        self.wheel_last = ev.time
        if new or self.since(ev, self.wheel_sent) >= self.WHEEL_STEP:
            self.wheel_sent = ev.time
            self.vol_step(step, new)
        return True

    # ----- Ziehen am Lautstärke-Streifen -----
    DRAG_SEND_MS = 120          # beim Ziehen höchstens so oft ein Befehl

    def drag_vol(self, v, start):
        if v == int(round(self.vol_base() or 0)):
            return
        self.gesture_start = start
        self.vol_dragged = True
        self.set_vol(v, send=False)          # Anzeige sofort, Senden gedrosselt
        if self.vol_send_timer:
            return
        wait = self.DRAG_SEND_MS - int((time.monotonic() - self.vol_sent) * 1000)
        if wait <= 0:
            self.send_vol()
        else:
            self.vol_send_timer = GLib.timeout_add(wait, self.drag_send_later)

    def drag_send_later(self):
        self.vol_send_timer = None
        self.send_vol()
        return False

    def drag_vol_end(self):
        if self.vol_send_timer:
            GLib.source_remove(self.vol_send_timer)
            self.vol_send_timer = None
        if self.vol_dragged:                 # Endwert immer senden (nie einen alten Wert von früher)
            self.vol_dragged = False
            self.vol_local_until = time.time() + 2.5
            self.send_vol()

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
        if dist < r * 0.35 or dist > r * (1 + 90 / RING_R0):   # Mitte (Zahl) und weit außerhalb ignorieren
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

    def set_vol(self, v, send=True):
        v = max(0, min(m.MAX_VOL, int(v)))
        self.vol_user_gen += 1          # eine laufende Szene überschreibt das nicht mehr
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
        if send:
            self.send_vol()

    def send_vol(self):
        self.vol_sent = time.monotonic()
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

    def on_window_state(self, _w, ev):
        """Zurück aus dem Minimieren: Inzwischen kann am Receiver verstellt worden sein."""
        iconified = Gdk.WindowState.ICONIFIED
        if ev.changed_mask & iconified and not ev.new_window_state & iconified:
            self.status_time = self.vol_local_until = 0.0
            self.status_valid_from = time.time()    # ältere, noch laufende Abfragen zählen nicht
            self.refresh()
        return False

    def refresh_once(self):
        self.refresh()
        return False

    def refresh(self):
        if self.status_busy:            # nie zwei Statusabfragen gleichzeitig
            self.status_again = True
            return
        self.status_busy = True
        self.status_asked = time.time()
        in_bg(m.status, self.on_status_ok, self.on_status_err)

    def status_done(self):
        self.status_busy = False
        if self.status_again:
            self.status_again = False
            GLib.timeout_add(400, self.refresh_once)

    def on_status_ok(self, st):
        lost, self.status_fails = self.status_fails >= STATUS_FAILS, 0
        if lost:                        # wieder da → Meldung sicher entfernen
            self.show_err()
        if self.status_asked >= self.status_valid_from:
            self.status_time = self.status_asked
        else:
            self.status_again = True
        try:
            self.on_status(st)
        finally:
            self.status_done()

    def on_status(self, st):
        if (st == getattr(self, "_last_status", None) and time.time() >= self.vol_local_until
                and self.vol_shown == st["volume"]):
            return              # nichts geändert → nichts neu zeichnen (spart viel Rechenzeit)
        self._last_status = dict(st)
        self.st = st
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
        self.strip.set_state(v, muted)
        self.mute_btn.set_label("Ton an" if muted else "Stumm")
        key = (v, muted, bool(self.st.get("power", True)))
        if key != getattr(self, "_ring_state", None) or getattr(self, "glow", 0) > 0:
            self._ring_state = key
            self.ring.queue_draw()

    def on_status_err(self, e):
        self.status_done()
        self.status_fails += 1
        if self.status_fails < STATUS_FAILS:    # einzelne Aussetzer ignorieren
            return
        if self.status_fails == STATUS_FAILS:
            syslog.syslog(syslog.LOG_WARNING, "Status: %s" % e)
        self._last_status = None                # nächster Erfolg zeichnet alles neu
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

APP_ID = "io.github.amplifie.MarantzTouchRemote"


def main(make_window=App):
    """Nur eine App gleichzeitig: Ein zweiter Start holt das vorhandene Fenster nach vorn
    (wichtig, um die minimierte App per Touch zurückzubekommen)."""
    single = Gio.Application(application_id=APP_ID)
    try:
        single.register(None)
    except GLib.Error:                      # ohne Sitzungsbus: einfach normal starten
        single = None
    if single and single.get_is_remote():
        single.activate()
        single.get_dbus_connection().flush_sync(None)
        return
    win = make_window()
    if single:
        single.connect("activate", lambda *_: win.present())
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
