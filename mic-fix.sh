#!/bin/bash
# Surface 3: eingebautes Mikrofon aktivieren.
# Der Audio-Chip (rt5645) nimmt ab Werk vom leeren analogen Eingang auf.
# Das echte Mikrofon ist digital (DMIC1) und läuft über den Aufnahmeweg ADC2.
# Ermittelt am 2026-11-26 per Piepton-Test (Lautsprecher abspielen + aufnehmen).
CARD=$(aplay -l 2>/dev/null | grep -m1 rt5645 | sed -E 's/^[^0-9]*([0-9]+).*/\1/')
CARD=${CARD:-1}
A="amixer -c $CARD -q sset"
$A 'Stereo1 DMIC Mux' DMIC1
$A 'Stereo1 ADC2 Mux' DMIC
$A 'Sto1 ADC MIXL ADC1' off
$A 'Sto1 ADC MIXR ADC1' off
$A 'Sto1 ADC MIXL ADC2' on
$A 'Sto1 ADC MIXR ADC2' on
$A 'ADC Boost' 1
