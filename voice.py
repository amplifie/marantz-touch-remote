#!/usr/bin/env python3
"""Sprachsteuerung (offline) mit Vosk – Hilfsprogramm für die Marantz-App.

Aufnahme über PulseAudio/PipeWire (parec), Erkennung lokal mit dem kleinen
deutschen Vosk-Modell. Nichts geht ins Internet.

  python3 voice.py test      → Mikrofon- und Erkennungstest im Terminal
  python3 voice.py serve     → wartet auf Zeilen von der App (JSON), antwortet mit JSON
"""
import json
import os
import subprocess
import sys
import time
from array import array

BASE = os.path.expanduser("~/.local/share/marantz-voice")
sys.path.insert(0, os.path.join(BASE, "lib"))
import vosk  # noqa: E402

RATE = 16000
vosk.SetLogLevel(-1)
_model = None


def _rms(data: bytes) -> int:
    a = array("h")
    a.frombytes(data[: len(data) // 2 * 2])
    return int((sum(x * x for x in a) / max(1, len(a))) ** 0.5)


def _mic_fix():
    """Mikrofon-Verschaltung sicherstellen (falls das System sie zurückgesetzt hat)."""
    fix = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mic-fix.sh")
    if os.path.exists(fix):
        subprocess.run([fix], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)


def model():
    global _model
    if _model is None:
        _model = vosk.Model(os.path.join(BASE, "model"))
    return _model


def listen(grammar=None, max_sec=6.0, on_level=None):
    """Hört zu, bis ein Satz zu Ende ist (Pause) oder max_sec erreicht ist.
    grammar: Liste erlaubter Wörter/Sätze (macht die Erkennung schneller und genauer)."""
    _mic_fix()
    if grammar:
        rec = vosk.KaldiRecognizer(model(), RATE, json.dumps(grammar + ["[unk]"], ensure_ascii=False))
    else:
        rec = vosk.KaldiRecognizer(model(), RATE)
    proc = subprocess.Popen(["parec", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
                             "--latency-msec=100"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    text, peak, start, heard = "", 0, time.time(), False
    try:
        while time.time() - start < max_sec:
            data = proc.stdout.read(3200)          # 0,1 s Audio
            if not data:
                break
            lvl = _rms(data)
            peak = max(peak, lvl)
            if on_level:
                on_level(lvl)
            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result()).get("text", "")
                if text and text != "[unk]":
                    heard = True
                    break
        if not heard:
            text = json.loads(rec.FinalResult()).get("text", "")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
    return {"text": text.replace("[unk]", "").strip(), "peak": peak}


def test():
    print("Lade Sprachmodell …", flush=True)
    t = time.time()
    model()
    print(f"Modell geladen in {time.time() - t:.1f} s.\n")
    tries = ["Sag z. B.: „lauter“", "Sag z. B.: „Filmabend“", "Sag z. B.: „Spiele Musik von Adele“"]
    for i, hint in enumerate(tries, 1):
        input(f"[{i}/3] {hint} – Enter drücken, dann sprechen …")
        print("   🎤 Ich höre zu …", flush=True)
        t = time.time()
        r = listen(max_sec=6)
        lvl = "gut" if r["peak"] > 3000 else "ok" if r["peak"] > 800 else "SEHR LEISE"
        print(f"   Erkannt: „{r['text'] or '(nichts)'}“   (Mikrofon-Pegel: {r['peak']} = {lvl}, "
              f"{time.time() - t:.1f} s)\n")
    print("Test fertig. Bitte die drei Ergebnisse an Claude zurückmelden.")


def serve():
    """Einfaches Zeilen-Protokoll für die App: {"grammar":[...]} → {"text":..,"peak":..}"""
    model()
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            req = json.loads(line)
            r = listen(req.get("grammar"), float(req.get("max_sec", 6)))
        except Exception as e:  # noqa: BLE001
            r = {"error": str(e)}
        print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    {"test": test, "serve": serve}.get(sys.argv[1] if len(sys.argv) > 1 else "test", test)()
