# Changelog

ICE Transducer Temperature Monitor — DMM6500, IEC 60601-2-37:2024.
Version is bumped on every update; the same version is set in
`code/temp_monitor_gui.py` (`APP_VERSION`), shown in the window title and the
test report, carried in the file's header comment block (`Notes` field holds
the latest update description), and tagged in git (`vX.Y.Z`).

## V1.3.10 — 2026-06-10

- **Frame rate / PRF auto-fill requires all measured table conditions**:
  in addition to the V1.3.9 gating, the auto-fill now also requires
  *Line density* = UH and *Console SW version* = V1.0.0.105919 — the
  conditions every row of the parameter table was measured under.
  Editing either field to anything else blanks *Frame rate* / *PRF* for
  manual entry, and both fields now re-trigger the auto-fill evaluation.
- **Depth compared numerically**: a manually typed depth of `15.0` now
  counts as the tabulated 15 cm instead of failing the exact string
  match and blanking the auto-fill.
- `temp/selftest.py`: checks for depth `15.0`, non-UH line density and
  non-table console SW version.

## V1.3.9 — 2026-06-10

- **Frame rate / PRF auto-fill only under measured table conditions**: the
  parameter table measured B+C only with B Opt = GEN and C ROI = 0–1 cm
  (rows `PEN(C)+GEN(B)` / `GEN(C)+GEN(B)`), but the auto-fill keyed only on
  C Opt and FOV, so B+C with any other B Opt (PEN, GRES, RES, HPEN, HRES)
  or with C ROI 0–15 cm wrongly auto-filled 14.6 Hz / 10000 Hz. These
  unmeasured combinations now leave *Frame rate* and *PRF* empty for
  manual entry, like every other condition not in the table.
- `auto_tx_params()` takes the C ROI as a new argument; changing the
  *C ROI* selector now re-evaluates the auto-filled fields.
- `temp/selftest.py`: checks that B+C with B Opt ≠ GEN, B+C with C ROI
  0–15, and B multifocus with a non-PEN Opt all leave FR/PRF empty.

## V1.3.8 — 2026-06-10

- **Default test mode is now *Simulated use b) Temperature rise***: the
  system has no closed-loop temperature monitoring, so IEC 60601-2-37
  201.11.1.3.101.1 allows selecting method a) or b) ("Test method a) or b)
  specified below shall be selected"; a) is mandatory only for equipment
  with closed-loop temperature monitoring). Method b) is the method chosen
  for this test program; method a) remains selectable in the GUI.
- `temp/selftest.py`: checks that the default test mode is `rise6`.

## V1.3.7 — 2026-06-10

- **Per-run output folder**: every test creates `run_YYYYMMDD_HHMMSS_<label>`
  under the output folder and writes all its files there (CSV, report TXT,
  report PDF, plot PNG) instead of loose files in `temp\`.
- **Output folder field** (*Test setup* tab, with *Browse…*): the default
  base folder for the run folders; preset to `temp\`.
- **Save report folder dialog**: the *Save report* button now opens a
  folder picker (starting at the default output folder) and writes the
  re-saved report TXT/PDF and plot PNG into the chosen folder; cancelling
  the dialog aborts the save.
- `temp/selftest.py`: checks the run folder (location, name, CSV inside)
  and a re-save into a different, newly created folder via a stubbed dialog.
- `.gitignore`: ignore `temp/run_*/`.

## V1.3.6 — 2026-06-09

- **C ROI selector** (modes containing C): 0–1 or 0–15 cm. Recorded in the
  test label (`CROI0-1`), the CSV `#` metadata (`c_roi_cm`) and the report's
  operating-settings block (omitted for modes without C).
- `temp/selftest.py`: checks for the C ROI label part and the blank
  `c_roi_cm` metadata in B mode.

## V1.3.5 — 2026-06-09

- **Mode list corrected**: standalone C removed — the console offers C only
  combined with B. Modes are now B, B+C, B+CW, B+PW, B+C+PW, B+C+CW.

## V1.3.4 — 2026-06-09

- **Live monitor (no recording)**: new *Monitor (no record)* button starts a
  live readout — no CSV, no statistics, no report — for the pre-run condition
  checks: test-object temperature before contact (≥ 37 °C, method a) and the
  23 ± 3 °C ambient. The probe readout shows a `pre-contact >= 37 C` hint,
  the ambient readout the 23 ± 3 °C check. *→ DUT temp before contact*
  copies the probe's live reading into the Test-setup field. Starting a test
  stops the monitor automatically; each acquisition thread now owns its stop
  event, so a finishing monitor read can never leak into a test run.
- User Guide: new procedure step for the pre-contact check and a new section
  *How to determine the measurement uncertainty (201.11.1.3.104)* —
  end-to-end bath calibration vs. GUM budget, typical component values, and
  the *measured value + uncertainty* decision rule.
- `temp/selftest.py`: live-monitor checks (sample received, readout updated,
  pre-contact capture, nothing recorded, clean stop).

## V1.3.3 — 2026-06-09

- **Operator fields in the GUI** (*Test setup* tab): *Meas. uncertainty*
  (201.11.1.3.104) and *DUT temp before contact* (≥ 37 °C, method a) — the
  report's former blank fill-in lines. Entered values are written into the
  report and the CSV `#` metadata; left empty, the report keeps a blank line
  pointing at the GUI + *Save report*. Typical flow: fill them after the run
  and press *Save report*.
- `temp/selftest.py`: re-save fills both fields and verifies them in the
  report.

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
