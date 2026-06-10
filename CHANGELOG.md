# Changelog

ICE Transducer Temperature Monitor — DMM6500, IEC 60601-2-37:2024.
Version is bumped on every update; the same version is set in
`code/temp_monitor_gui.py` (`APP_VERSION`), shown in the window title and the
test report, mirrored in the module docstring "Latest update notes", and tagged
in git (`vX.Y.Z`).

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
