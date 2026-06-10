# Changelog

ICE Transducer Temperature Monitor — DMM6500, IEC 60601-2-37:2024.
Version is bumped on every update; the same version is set in
`code/temp_monitor_gui.py` (`APP_VERSION`), shown in the window title and the
test report, carried in the file's header comment block (`Notes` field holds
the latest update description), and tagged in git (`vX.Y.Z`).

## V1.3.2 — 2026-06-09

- **Plot legend**: the limit-line label now shows the actual limit value in
  parentheses (e.g. `Limit (43.0 C)` — for rise modes the plotted absolute
  level baseline + limit − offset) with the cited standard
  (`IEC 60601-2-37 <clause>`) on a second line below it.

## V1.3.1 — 2026-06-09

- **"Save report" button** (Run control): enabled when a run ends. The
  operator can amend the UI fields after the test — operator name, DUT ID,
  transmit params, thermal offset, … — and save the outputs again. The
  verdict is re-evaluated with the amended values; filenames keep the run's
  start timestamp, and a changed test label writes new files alongside the
  old ones (the recorded CSV data is never modified).
- **PDF report** (`report_YYYYMMDD_HHMMSS_<label>.pdf`): generated next to
  the `.txt` report on every save — page 1 the full report text, page 2 the
  temperature plot. Uses matplotlib `PdfPages`, no new dependency.
- `temp/selftest.py`: checks for the PDF output, the Save-button state and
  a re-save with an amended operator name.

## V1.3.0 — 2026-06-09

- **Simulated-test demo re-added**: the instrument list now offers
  *Simulated DMM6500 (demo, no hardware)*, auto-selected when no VISA
  instrument is found. The demo heats the selected probe channel along an
  exponential curve (37 °C → ~41.6 °C, τ 300 s), keeps the ambient channel
  near 23 °C and runs on a ×60 accelerated clock, so a 30-min test reaches
  thermal steady state and finishes in ~30 s, exercising the full
  acquisition/CSV/report/plot pipeline.
- Demo runs are unambiguous in the records: `*IDN?` reports
  `SIMULATED,DMM6500-DEMO,…` (shown in the report's Instrument line) and the
  connection status turns orange.
- `temp/selftest.py` now drives the application's own `SimulatedDmm` (its
  private stub removed) and adds checks for the V1.2.0 auto-fill logic.

## V1.2.0 — 2026-06-09

- **Transmit-params tab reworked for console SW V1.0.0.105919** (presets from
  sheet `Acoustic Test V1.0.0.105919` of
  `doc/Acoustic Safety Test Parameters.xlsx`); presets of older console
  versions removed.
- **Modes**: B, C, B+C, B+CW, B+PW, B+C+PW, B+C+CW. Modes containing B show a
  *B Opt* selector (PEN/GEN/GRES/RES/HPEN/HRES — HGEN/HGRES1/HGRES2 no longer
  exist); modes containing C additionally show a *C Opt* selector (PEN/GEN
  only), e.g. B+C records `PEN(C)+GEN(B)`.
- **Fixed parameters auto-fill**: transmit frequency follows the Opt (B: PEN
  4.5 / GEN 6.5 / GRES 6.5 / RES 8 / HPEN 8 / HRES 9 MHz; C: PEN 4.5 /
  GEN 4.8 MHz); Pulses# is 2 for non-harmonic B, 1 for harmonic (H*) Opts,
  4 for modes with C. Both fields are read-only.
- **Image depth** is now a 3–15 cm spinbox, validated when the test starts.
  **FOV** choices are 90/100/115/120.
- **Focus number** 1–4; one focus-position entry box appears per focus, and
  the positions are recorded as the focus area (e.g. `1,2,3cm`).
- **Frame rate / PRF auto-fill** from the parameter table (15 cm depth) when
  the selected combination is tabulated; otherwise the fields stay empty and
  editable.

## V1.1.0 — 2026-06-09

- **Removed demo mode** (`SimulatedDmm`) from the application; an equivalent
  stub now lives only in `temp/selftest.py` for automated testing.
- **Ambient-channel selector**: new dropdown chooses whether channel 2 or
  channel 3 is the ambient reference TC; the other channel becomes the probe
  (DUT) evaluated against the IEC limits. Labels, plot colors, CSV columns and
  report sections follow the selection.
- **Transmit parameters tab** (201.11.1.3.102): records console SW version,
  Mode (B/C/C+B/PW/CW), Opt (PEN/GEN/GRES/RES/HPEN/HGEN/HGRES1/HGRES2/HRES for
  B; PEN/GEN and combined presets for C), image depth, FOV, focus number,
  focus area, line density, F (MHz), pulses #, frame rate, PRF — presets from
  `doc/Acoustic Safety Test Parameters.xlsx`, all fields editable.
- The settings build a test label (e.g. `B-PEN-D15-FOV90-FN1-1cm`) appended to
  CSV/report/PNG filenames so each console mode's run is identifiable; the
  full settings are written as `#` metadata lines at the top of the CSV and as
  an "Operating settings" block in the report (the blank transmit-parameters
  fill-in line is gone).
- Left configuration column reorganized into "Test setup" / "Transmit params"
  notebook tabs.

## V1.0.1 — 2026-06-09

- Rework the `temp_monitor_gui.py` file header into the standard comment-block
  format (`Project / Version / Modified / Notes`); the Notes field carries the
  latest update description and is rewritten on every version bump.
- No functional changes.

## V1.0.0 — 2026-06-09

Initial release.

- Tkinter GUI with live dual-channel plot, readouts, compliance verdict panel.
- Keithley DMM6500 over USB/VISA: instrument auto-detection (*IDN? scan of all
  VISA resources, refuses non-DMM6500), TERMINALS=REAR check, per-command SCPI
  error checking, simulated reference junction tied to the entered ambient
  temperature (2000-SCAN card has no CJC sensor), open-thermocouple detection.
- Channel roles: T2 (ch 2) = transducer surface under test, evaluated against
  the limits; T3 (ch 3) = ambient reference, recorded for the 23 ± 3 °C
  condition; drift (max−min) tracked on both channels.
- IEC 60601-2-37:2024 clause 201.11 pass/fail logic (invasive transducer):
  peak ≤ 43 °C; rise + thermal offset ≤ 6 °C (simulated use) / ≤ 27 °C
  (still air); 41 °C warning; steady-state detection < 0.12 °C/min for 3 min;
  auto-stop at 30 min or steady state.
- Outputs to `temp\`: CSV log, test report with operator fill-in fields,
  plot PNG. Demo mode with accelerated time for training/verification.
- Diagnostics: `temp\probe_check.py` scans all 10 scanner-card channels.
- Automated self-test: `temp\selftest.py` (verdict formulas, steady-state
  detector, accelerated end-to-end demo run).
