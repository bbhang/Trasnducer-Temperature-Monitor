"""Automated self-test for temp_monitor_gui.py (logic + end-to-end run).

Drives the application's own SimulatedDmm demo instrument (x60 accelerated
clock) to exercise the full acquisition, steady-state, verdict and report
pipeline (TXT + PDF + re-save + live monitor + per-run output folder,
V1.3.1-V1.3.7) without hardware.
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "code"))

import temp_monitor_gui as m

fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        fails.append(name)


# ---- evaluate_channel ------------------------------------------------------
v, lim, ok = m.evaluate_channel("peak", 42.9, 37.0, 0.0)
check("peak 42.9 <= 43 passes", ok and lim == 43.0 and v == 42.9)
v, lim, ok = m.evaluate_channel("peak", 43.1, 37.0, 0.0)
check("peak 43.1 > 43 fails", not ok)
v, lim, ok = m.evaluate_channel("rise6", 42.5, 37.0, 0.4)
check("rise6 5.5+0.4=5.9 <= 6 passes", ok and abs(v - 5.9) < 1e-9)
v, lim, ok = m.evaluate_channel("rise6", 42.8, 37.0, 0.4)
check("rise6 5.8+0.4=6.2 > 6 fails", not ok)
v, lim, ok = m.evaluate_channel("rise27", 49.0, 23.0, 1.0)
check("rise27 26+1=27 <= 27 passes", ok and abs(v - 27.0) < 1e-9)
v, lim, ok = m.evaluate_channel("rise27", 49.5, 23.0, 1.0)
check("rise27 26.5+1=27.5 > 27 fails", not ok)

# ---- build_test_label ------------------------------------------------------
label = m.build_test_label({"mode": "B", "opt": "PEN", "depth": "15",
                            "fov": "90", "focus_num": "1", "focus_area": "1cm"})
check("label B-PEN-D15-FOV90-FN1-1cm", label == "B-PEN-D15-FOV90-FN1-1cm")
label = m.build_test_label({"mode": "B+C", "opt": "PEN(C)+GEN(B)",
                            "depth": "15", "fov": "90", "focus_num": "1",
                            "focus_area": "0-1cm"})
check("label sanitizes parentheses", "(" not in label and ")" not in label)
label = m.build_test_label({"mode": "B+C", "opt": "PEN(C)+GEN(B)",
                            "c_roi": "0-1", "depth": "15", "fov": "90",
                            "focus_num": "1", "focus_area": "1cm"})
check("label carries C ROI", "CROI0-1" in label)
check("label empty when no params", m.build_test_label({}) == "")

# ---- auto_tx_params (console SW V1.0.0.105919 table) -----------------------
a = m.auto_tx_params("B", "PEN", "PEN", "90", "1", "15")
check("auto B/PEN/90: F 4.5, 2 pulses, FR 35.14, PRF 4182",
      a == {"f_mhz": "4.5", "pulses": "2",
            "frame_rate": "35.14", "prf": "4182"})
a = m.auto_tx_params("B", "HRES", "PEN", "120", "1", "15")
check("auto B/HRES/120: F 9, 1 pulse (harmonic), FR 11.62",
      a == {"f_mhz": "9", "pulses": "1",
            "frame_rate": "11.62", "prf": "4182"})
a = m.auto_tx_params("B", "PEN", "PEN", "90", "3", "15")
check("auto B/PEN/90 3-focus: FR 11.71",
      a["frame_rate"] == "11.71" and a["prf"] == "4182")
a = m.auto_tx_params("B+C", "GEN", "PEN", "100", "1", "15", c_roi="0-1")
check("auto B+C PEN(C): F 4.5, 4 pulses, FR 14.6, PRF 10000",
      a == {"f_mhz": "4.5", "pulses": "4",
            "frame_rate": "14.6", "prf": "10000"})
a = m.auto_tx_params("B+C", "GEN", "GEN", "120", "1", "15", c_roi="0-1")
check("auto B+C FOV120: FR/PRF not tabulated -> empty",
      a["f_mhz"] == "4.8" and a["frame_rate"] == "" and a["prf"] == "")
a = m.auto_tx_params("B+C", "PEN", "PEN", "90", "1", "15", c_roi="0-1")
check("auto B+C with B Opt != GEN: FR/PRF empty (not measured)",
      a["frame_rate"] == "" and a["prf"] == "")
a = m.auto_tx_params("B+C", "GEN", "PEN", "90", "1", "15", c_roi="0-15")
check("auto B+C with C ROI 0-15: FR/PRF empty (not measured)",
      a["frame_rate"] == "" and a["prf"] == "")
a = m.auto_tx_params("B", "GEN", "PEN", "90", "2", "15")
check("auto B/GEN/90 2-focus: FR/PRF empty (only PEN measured)",
      a["frame_rate"] == "" and a["prf"] == "")
a = m.auto_tx_params("B", "PEN", "PEN", "90", "1", "10")
check("auto depth != 15: FR/PRF empty",
      a["frame_rate"] == "" and a["prf"] == "")

# ---- SteadyStateDetector ---------------------------------------------------
d = m.SteadyStateDetector()
for i in range(0, 301):
    d.add(float(i), 37.0 + i / 60.0)
check("detector: 1 C/min ramp is NOT steady", not d.steady)

d = m.SteadyStateDetector()
for i in range(0, 301):
    d.add(float(i), 40.0)
check("detector: flat 5 min IS steady", d.steady)

d = m.SteadyStateDetector()
tau, rise = 200.0, 5.0
steady_t = None
for i in range(0, 1801):
    d.add(float(i), 37.0 + rise * (1 - math.exp(-i / tau)))
    if d.steady and steady_t is None:
        steady_t = i
check("detector: exponential becomes steady", d.steady)
check("detector: steady time plausible (600-900 s)",
      steady_t is not None and 600 <= steady_t <= 900)

# ---- SimulatedDmm demo instrument ------------------------------------------
demo = m.SimulatedDmm()
idn = demo.connect()
check("demo IDN marks run as SIMULATED", idn.startswith("SIMULATED,"))
temps = demo.read_temps()
check("demo reads both channels", sorted(temps) == sorted(m.CHANNELS))
demo.start_heating(probe_ch=3)
t = demo.read_temps()
check("demo probe ch3 hot, ch2 ambient", t[3] > 30.0 and t[2] < 26.0)
check("demo clock accelerated x60", demo.time_scale == 60.0)
demo.close()

# ---- End-to-end demo run with swapped channel roles ------------------------
# Ambient = channel 2, probe = channel 3 (channel 3 heats up).
popups = []
for fn in ("showinfo", "showerror", "showwarning"):
    setattr(m.messagebox, fn,
            lambda title, msg, _f=fn, **k: popups.append((_f, title, str(msg))))
m.messagebox.askokcancel = lambda *a, **k: True

app = m.App()
app.withdraw()
check("default test mode is rise6 (method b, no closed-loop monitoring)",
      app.mode_var.get() == "rise6")
app.ambient_combo.set("Channel 2 (T2)")
app._on_ambient_change()
check("roles: probe=ch3 ambient=ch2",
      app.probe_ch == 3 and app.ambient_ch == 2)

app.dmm = m.SimulatedDmm()
app.dmm.connect()
app.interval_var.set("0.25")
app.duration_var.set("30")
app.mode_var.set("rise6")
app.offset_var.set("0.0")
app.operator_var.set("selftest")
app.dut_var.set("DEMO-ICE-001")
app.tx_vars["mode"].set("B")
app._on_console_mode_change()
app.tx_vars["b_opt"].set("PEN")
app.tx_vars["depth"].set("15")
app.tx_vars["fov"].set("90")
app.tx_vars["focus_num"].set("1")
app._on_focus_num_change()

# ---- Live monitor: reads but records nothing --------------------------------
app.start_monitor()
check("monitor running", app.monitoring)
t_end = time.time() + 5
while app.last_monitor_temps is None and time.time() < t_end:
    app.update()
    time.sleep(0.02)
check("monitor got a sample", app.last_monitor_temps is not None)
check("monitor readout shows probe temperature",
      app.readouts[3]["cur"]["text"] not in ("--.- C", "")
      and app.readouts[3]["cur"]["text"].endswith("C"))
app._capture_precontact()
pre = app.precontact_var.get()
check("pre-contact temp captured from probe (~37 C)",
      pre != "" and 36.0 <= float(pre) <= 39.5)
check("monitor recorded nothing", app.csv_path is None and not app.times)
app.stop_monitor()
check("monitor stopped", not app.monitoring)
check("start while monitoring stops monitor cleanly",
      str(app.monitor_btn["text"]) == "Monitor (no record)")
app.precontact_var.set("")    # run the test with the field empty again

app.start_test()
check("test started", app.running)
check("test label built", app.test_label == "B-PEN-D15-FOV90-FN1-1cm")
check("F/pulses auto-filled into params",
      app.tx_params["f_mhz"] == "4.5" and app.tx_params["pulses"] == "2")
check("FR/PRF auto-filled into params",
      app.tx_params["frame_rate"] == "35.14"
      and app.tx_params["prf"] == "4182")

t_end = time.time() + 60
while app.running and time.time() < t_end:
    app.update()
    time.sleep(0.02)

check("test auto-stopped", not app.running)
print("stop reason:", app.stop_reason)
check("auto-stop on T3 probe steady state",
      "T3" in app.stop_reason and "steady state" in app.stop_reason)
check("samples collected (>40)", len(app.times) > 40)

# ---- Per-run output folder ---------------------------------------------------
out_dir = app.run_dir
check("run folder created", bool(out_dir) and os.path.isdir(out_dir))
check("run folder under default output folder",
      os.path.dirname(out_dir) == m.OUTPUT_DIR)
check("run folder name carries label",
      os.path.basename(out_dir).startswith("run_")
      and "B-PEN-D15-FOV90-FN1-1cm" in os.path.basename(out_dir))
check("CSV inside run folder", os.path.dirname(app.csv_path) == out_dir)

check("CSV filename carries label",
      app.csv_path and "B-PEN-D15-FOV90-FN1-1cm" in os.path.basename(app.csv_path))
csv_ok = app.csv_path and os.path.isfile(app.csv_path)
check("CSV written", bool(csv_ok))
if csv_ok:
    with open(app.csv_path, encoding="utf-8") as f:
        csv_text = f.read()
    check("CSV has # metadata", csv_text.startswith("# program:"))
    check("CSV metadata has console mode", "# console_mode: B" in csv_text)
    check("CSV metadata: C ROI blank in B mode", "# c_roi_cm: \n" in csv_text)
    check("CSV header swapped roles",
          "T3_probe_C (ch3)" in csv_text and "T2_ambient_C (ch2)" in csv_text)

reports = sorted(f for f in os.listdir(out_dir)
                 if f.startswith("report_") and f.endswith(".txt"))
pdfs = sorted(f for f in os.listdir(out_dir)
              if f.startswith("report_") and f.endswith(".pdf"))
pngs = sorted(f for f in os.listdir(out_dir) if f.startswith("tempplot_"))
check("report written", bool(reports))
check("report PDF written", bool(pdfs))
if pdfs:
    with open(os.path.join(out_dir, pdfs[-1]), "rb") as f:
        check("PDF magic number", f.read(5) == b"%PDF-")
check("plot PNG written", bool(pngs))
check("report filename carries label",
      reports and "B-PEN-D15-FOV90-FN1-1cm" in reports[-1])
check("finish popup shown", any(p[0] == "showinfo" for p in popups))

if reports:
    with open(os.path.join(out_dir, reports[-1]), encoding="utf-8") as f:
        rep = f.read()
    print("\n----- report excerpt -----")
    print("\n".join(rep.splitlines()[:30]))
    check("report verdict PASS", "Verdict          : PASS" in rep)
    check("report names SIMULATED instrument", "SIMULATED,DMM6500-DEMO" in rep)
    check("report swapped probe section", "T3 probe (channel 3" in rep)
    check("report swapped ambient section", "T2 ambient (channel 2" in rep)
    check("report has operating settings block",
          "Operating settings of the ultrasound console (201.11.1.3.102)" in rep)
    check("report lists F MHz", "4.5 MHz" in rep)
    check("report references PDF file", "PDF file" in rep)
    check("report has blank operator fields before fill",
          "fill in the GUI" in rep)

# ---- Save report again with amended UI fields -------------------------------
# The Save button opens a folder picker; stub it to a fresh subfolder so the
# re-save also proves saving into a different, not-yet-existing directory.
resave_dir = os.path.join(out_dir, "resaved")
m.filedialog.askdirectory = lambda **k: resave_dir
check("save button enabled after run", str(app.save_btn["state"]) == "normal")
app.operator_var.set("selftest-amended")
app.uncert_var.set("+/- 0.3")
app.precontact_var.set("37.2")
app.save_report()
check("re-save popup shown", any(p[1] == "Report saved" for p in popups))
check("re-save created chosen folder", os.path.isdir(resave_dir))
reports2 = sorted(f for f in os.listdir(resave_dir)
                  if f.startswith("report_") and f.endswith(".txt"))
check("re-saved report in chosen folder", bool(reports2))
check("re-saved PDF in chosen folder",
      any(f.endswith(".pdf") for f in os.listdir(resave_dir)))
out_dir = resave_dir
reports = reports2
if reports:
    with open(os.path.join(out_dir, reports[-1]), encoding="utf-8") as f:
        rep2 = f.read()
    check("re-saved report has amended operator", "selftest-amended" in rep2)
    check("re-saved report keeps verdict PASS", "Verdict          : PASS" in rep2)
    check("re-saved report has measurement uncertainty", "+/- 0.3 C" in rep2)
    check("re-saved report has pre-contact temperature", "37.2 C" in rep2)
    check("re-saved report has no blank operator fields",
          "fill in the GUI" not in rep2)

app._on_close()

print("\n%d check(s) failed" % len(fails))
sys.exit(1 if fails else 0)
