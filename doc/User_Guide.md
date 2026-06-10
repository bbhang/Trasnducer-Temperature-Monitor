# ICE Transducer Temperature Monitor — User Guide

GUI application for measuring ICE transducer self-heating with a Keithley DMM6500
and judging compliance against IEC 60601-2-37:2024 clause 201.11
(see `IEC_60601-2-37_Requirements_Summary.md` for the full requirement extraction).

## 1. Hardware setup

- **Instrument:** Keithley DMM6500 with the 2000-SCAN scanner card installed in the
  **rear panel** card slot.
- **Probes:** two type-T thermocouples (default; K/J selectable in the GUI) on
  scanner-card channels 2 (T2) and 3 (T3). One channel is the **probe** on the
  transducer surface (DUT) — evaluated against the IEC limits and used for
  steady-state auto-stop; the other is the **ambient reference** — recorded to
  document the 23 ± 3 °C test condition (and ≤ 0.5 °C stability for the
  still-air test), not part of the pass/fail verdict. Which channel is the
  ambient reference is selected in the GUI (*Ambient ref. channel*, default
  channel 3).
- Set the front-panel **TERMINALS** switch to **REAR**.
- **Connection:** USB cable from the DMM6500 rear USB-B port to the PC.
  A VISA runtime must be installed (NI-VISA or Keysight IO Libraries; alternatively
  `pip install pyvisa-py pyusb`).
- Attach the thermocouple junctions to the transducer surface points expected to
  reach the highest temperature, in good thermal contact, secured so that they have
  negligible effect on the local temperature rise (201.11.1.3.104 — thin film or
  fine wire recommended).

## 2. Software setup

```
pip install -r code\requirements.txt
python code\temp_monitor_gui.py
```

Python 3.10+ with tkinter (included in the standard Windows installer).

## 3. Operating procedure

1. **Connect** — click *Refresh*: the program queries `*IDN?` on every VISA
   instrument (safe for scopes, signal generators, etc.) and **auto-selects the
   DMM6500** from the list, which shows each instrument as `model | address`.
   Click *Connect*; the `*IDN?` string appears in green. Connecting to anything
   that is not a DMM6500 is refused (so a scope is never accidentally `*RST`).
   - **Demo without hardware:** the list always ends with *Simulated DMM6500
     (demo, no hardware)* — auto-selected when no VISA instrument is found.
     It simulates the probe heating from 37 °C to ~41.6 °C (ambient ~23 °C)
     on a ×60 clock, so a 30-min test finishes in ~30 s, for training and
     for verifying the CSV/report/plot pipeline. The connection status turns
     orange and the report's Instrument line reads `SIMULATED,DMM6500-DEMO,…`
     so a demo run can never be mistaken for a real measurement.
2. **Configure the test** (*Test setup* tab):
   - Test mode — choose per your test plan:
     - *Simulated use a) Peak temperature* — tissue-mimicking phantom preheated to
       ≥ 37 °C; limit: surface temperature ≤ **43 °C**.
     - *Simulated use b) Temperature rise* (**default**) — invasive limit: rise +
       thermal offset ≤ **6 °C**. The standard requires selecting either a) or b)
       (201.11.1.3.101.1); method a) is mandatory only for equipment with a
       closed-loop temperature monitoring system, which this system does not
       have, so b) is the chosen method for this test program.
     - *Still air* — no coupling gel; limit: rise + thermal offset ≤ **27 °C**.
   - *Thermal offset* — known stable offset at thermal steady state (201.3.228);
     0.0 if none.
   - *Ambient temperature* — record the room temperature; the standard requires
     23 ± 3 °C and the GUI warns if the entered value is outside that range.
   - *Ambient ref. channel* — choose which TC channel (2 or 3, default 3) is
     the ambient reference; the **other channel becomes the probe** evaluated
     against the IEC limits. All labels, plot colors, CSV columns and report
     sections follow the selection.
   - *Sample interval* (default 1 s), *Max test duration* (default 30 min),
     thermocouple type, operator and catheter/DUT ID (stored in the report).
   - *Meas. uncertainty* (201.11.1.3.104) and *DUT temp before contact*
     (≥ 37 °C, method a) — operator fields required by the standard, written
     into the report and the CSV metadata. They are usually known only after
     the run: fill them in and press *Save report* (step 8).
   - *Output folder* (with *Browse…*) — base folder for the outputs, preset
     to `temp\`. Every run creates its own subfolder
     `run_YYYYMMDD_HHMMSS_<label>` in it.
3. **Enter the console operating settings** (*Transmit params* tab,
   201.11.1.3.102) — set the ultrasound system to the operating mode that
   produces the **highest surface temperature** and record it here. Every
   console mode must be tested in its own run:
   - *Mode*: B, B+C, B+CW, B+PW, B+C+PW, B+C+CW (console SW V1.0.0.105919;
     C exists only combined with B, not standalone). Modes containing B show
     a *B Opt* selector (PEN, GEN, GRES, RES, HPEN, HRES); modes containing
     C also show a *C Opt* selector (PEN, GEN) and a *C ROI* selector
     (0–1 or 0–15 cm). A B+C run is recorded as e.g. `PEN(C)+GEN(B)` with
     the ROI in the test label (`CROI0-1`), the CSV metadata and the report.
   - *F (MHz)* and *Pulses #* are fixed and fill automatically: frequency
     follows the Opt (B: PEN 4.5 / GEN 6.5 / GRES 6.5 / RES 8 / HPEN 8 /
     HRES 9 MHz; C: PEN 4.5 / GEN 4.8 MHz); pulses are 2 for non-harmonic B,
     1 for harmonic (H*) Opts, 4 for modes with C.
   - *Image depth* (3–15 cm), *FOV* (90/100/115/120 deg), *Focus number*
     (1–4) with **one focus-position box per focus** (recorded as the focus
     area, e.g. `1,2,3cm`), *Line density*, *Console SW version*.
   - *Frame rate* and *PRF* fill automatically only when the exact
     combination was measured in `doc/Acoustic Safety Test Parameters.xlsx`
     (15 cm depth; B+C additionally requires B Opt GEN and C ROI 0–1 cm);
     any other combination leaves them empty — enter the values read from
     the console/oscilloscope manually.
   - The tab shows the resulting **test label** (e.g.
     `B-PEN-D15-FOV90-FN1-1cm`); it is appended to all output filenames so
     each mode's run is identifiable.
4. **Pre-contact check (optional)** — *Monitor (no record)* starts a live
   readout **without recording anything** (no CSV, no statistics, no report):
   use it to verify the test conditions before the run, in particular that
   the test object is preheated to **≥ 37 °C** (simulated-use method a,
   201.11.1.3.101.1) and that the ambient is within 23 ± 3 °C. The button
   *→ DUT temp before contact* copies the probe's live reading into the
   corresponding *Test setup* field, so the pre-contact temperature is
   documented in the report. Press *Stop monitor* when done — or simply press
   *Start test*, which stops the monitor automatically.
5. **Start test** — press *Start test* **just before activating acoustic output**.
   The first reading is stored as the per-channel **baseline** used for the
   temperature-rise calculation.
6. **During the test** — live readouts show current/max/rise/drift/rate per channel, a
   live plot with the limit line, a steady-state indicator, and the live verdict:
   - **IN PROGRESS** (gray) — no limit exceeded yet.
   - **WARNING ≥ 41 C** (orange) — peak mode only (201.12.4.2 j).
   - **FAIL** (red) — a limit was exceeded (latched for the rest of the run).
   - If the ultrasound system auto-freezes, re-activate it immediately
     (201.11.1.3.103).
7. **End of test** — the run stops automatically after the configured duration
   (default 30 min) or when the **probe** channel reaches thermal steady state
   (rate < 0.12 °C/min held for 3 min, 201.11.1.3.101), whichever comes first;
   *Stop test* ends it manually (the report then notes an incomplete test).
   The CSV, the report (TXT + PDF) and the plot PNG are saved automatically
   into the run's own folder (see section 4).
8. **Save report again (optional)** — after the run the *Save report* button
   becomes active. If information was missing or wrong during the run
   (operator name, DUT ID, transmit params, thermal offset, …), amend the
   fields in the GUI and click *Save report*: a folder-picker dialog
   (starting at the default output folder) chooses where the files go, the
   verdict is re-evaluated and the report/PDF/plot are written there.
   Filenames keep the run's start timestamp; changing the transmit params
   changes the test label, producing new files alongside the old ones. The
   recorded CSV data is never modified.

## 4. Output files

Each run creates its own folder `run_YYYYMMDD_HHMMSS_<label>` under the
*Output folder* configured in the GUI (default `temp\`) and writes all its
files there. `<label>` below is the transmit-parameter test label, e.g.
`B-PEN-D15-FOV90-FN1-1cm`.

| File | Content |
|---|---|
| `templog_YYYYMMDD_HHMMSS_<label>.csv` | `#` metadata lines (program version, mode, opt, depth, FOV, focus, operator, ...) then timestamp, elapsed s, probe °C, ambient °C — every sample |
| `report_YYYYMMDD_HHMMSS_<label>.txt` | test conditions, operating-settings block (201.11.1.3.102), baseline/min/max/drift/rise per channel, steady-state time, PASS/FAIL verdict, operator fill-in fields |
| `report_YYYYMMDD_HHMMSS_<label>.pdf` | PDF version of the report: page 1 the report text, page 2 the temperature plot |
| `tempplot_YYYYMMDD_HHMMSS_<label>.png` | temperature curves with limit lines |

The operator fields required by the standard — measurement uncertainty
(201.11.1.3.104) and, for method a), the test-object temperature before
contact (≥ 37 °C for invasive use) — are entered in the *Test setup* tab and
written into the report; if they were empty during the run, fill them in and
press *Save report*. An empty field leaves a blank fill-in line in the report.
The pre-contact temperature can be captured directly from the live monitor
(procedure step 4).

### How to determine the measurement uncertainty (201.11.1.3.104)

Enter the **expanded uncertainty of the complete measuring chain**
(thermocouple → 2000-SCAN card → DMM6500), e.g. `+/- 0.5 (k=2)` — the GUI
appends the °C unit. The standard requires the uncertainty to be *stated*;
it does not set a numeric limit.

**Preferred — end-to-end calibration (traceable):** compare the complete
chain (thermocouples connected through the scanner card to the DMM6500)
against a calibrated reference thermometer in a stirred liquid bath at
37–43 °C, and use the uncertainty stated in the calibration certificate.
This is the most defensible value in an audit.

**Alternative — uncertainty budget (GUM):** combine the main components by
root-sum-square. Typical values for this setup:

| Component | Typical contribution |
|---|---|
| Type-T thermocouple wire tolerance (IEC 60584-1, class 1) | ± 0.5 °C |
| DMM6500 thermocouple measurement accuracy (instrument spec) | ≈ ± 0.2 °C |
| Simulated cold-junction compensation — accuracy of the *Ambient temperature* entered in the GUI | ≈ ± 0.5 °C |
| Scanner-card relay thermal EMF, noise | ≈ ± 0.1 °C |

Root-sum-square ≈ ± 0.7 °C; **± 1.0 °C (k = 2)** is a conservative,
defensible declaration without a bath calibration.

Notes:

- The **temperature-rise modes** (rise + offset ≤ 6 / 27 °C) are far less
  sensitive: cold-junction and thermocouple systematic errors largely cancel
  in *max − baseline*, leaving mainly noise and drift (± 0.1–0.2 °C typical).
  The **peak mode (43 °C absolute)** carries the full absolute uncertainty
  including the cold-junction error — this is the mode for which a bath
  calibration matters most.
- A conservative compliance decision compares *measured value + uncertainty*
  against the limit: e.g. a 42.5 °C peak with ± 1.0 °C uncertainty gives
  43.5 °C > 43 °C, which does **not** demonstrate compliance — reduce the
  uncertainty (calibrate the chain) or state the decision rule used in the
  report.

## 5. Pass/fail logic

The verdict is evaluated on the **probe channel only** (the channel not chosen
as ambient reference); the ambient channel is recorded as a test condition
(23 ± 3 °C range and drift):

| Mode | Evaluated value (probe) | Limit |
|---|---|---|
| Simulated use a) | maximum temperature | ≤ 43.0 °C |
| Simulated use b) | (max − baseline) + thermal offset | ≤ 6.0 °C |
| Still air | (max − baseline) + thermal offset | ≤ 27.0 °C |

Note: the single-fault +5 °C allowance of 201.13.1.2 applies only to external-use
(skin) transducers and is **not** applied here.

## 6. Troubleshooting

- **No VISA resources found** — install NI-VISA (or `pip install pyvisa-py pyusb`),
  check the USB cable, and confirm the DMM6500 appears in Windows Device Manager.
- **"Undefined header" (-113) SCPI errors** — every configuration command is now
  checked against `:SYST:ERR?`; the connection error dialog names the exact
  offending command. The DMM6500 does not accept legacy 2000-series headers
  (e.g. `:UNIT:TEMP`); temperature units are set via `:SENS:TEMP:UNIT CELS, (@ch)`.
- **Reference junction** — the 2000-SCAN card has no cold-junction sensor (the
  instrument rejects `INTernal` with "channel does not support internal
  reference"), so the program uses a **SIMulated reference junction** set to the
  *Ambient temperature* entered in the GUI at test start. Keep the card
  terminals at room temperature, away from drafts. Absolute readings carry the
  cold-junction error; the temperature-rise test modes cancel it.
- **Relay clicking during acquisition** — normal. The 2000-SCAN card uses
  electromechanical relays and a single measurement path, so every sample the
  card must switch channel 2 → channel 3 and back; each switch is one audible
  click. At a 1 s interval a 30 min test produces ~3600 operations, negligible
  against the relay rated life (>10^8 operations). To reduce clicking, increase
  the sample interval (2–5 s is still far finer than the 0.12 °C/min
  steady-state criterion requires).
- **"thermocouple open or not connected" although probes are wired** — in order
  of likelihood:
  1. The front-panel **TERMINALS switch is on FRONT** — the scanner card is not
     in the measurement path (relays still click, but every channel reads
     overflow). The GUI now checks `:ROUT:TERM?` at connect and refuses with a
     clear message; flip the switch to REAR.
  2. The probes are wired to **different card channels** than 2/3 — run
     `python temp\probe_check.py`: it scans all 10 channels in TC mode and
     prints which ones return a valid temperature.
  3. **Loose screw terminals** — the clamp may be biting the insulation instead
     of bare wire; re-strip and re-tighten H and L of the channel.
- **Noisy rate / steady state never reached** — increase the sample interval or
  shield the thermocouples from airflow; the still-air test requires an environment
  without air movement, ambient stable within 0.5 °C.
- **Instrument busy after a crash** — power-cycle the DMM6500 or send `*RST` from
  another VISA session.

## 7. Verification status

`temp\selftest.py` exercises the verdict formulas, the test-label builder, the
steady-state detector and a full accelerated end-to-end run using the
application's own simulated instrument (swapped channel roles, live monitor
with pre-contact capture and no recording, CSV metadata, operating-settings
block in the report, auto-stop on steady state, PDF report, re-save with
amended fields, per-run output folder and re-save into a chosen folder).
All checks pass as of 2026-06-10 (V1.3.9).
Real-instrument validation (USB VISA address, channel configuration) is to be
performed on the bench.
