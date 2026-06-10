"""Automated self-test for temp_monitor_gui.py (logic + end-to-end run).

The application itself has no demo mode (V1.1.0); this script injects a stub
instrument with an accelerated clock to exercise the full acquisition,
steady-state, verdict and report pipeline without hardware.
"""
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "code"))

import temp_monitor_gui as m

fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        fails.append(name)


class StubDmm:
    """Test-only instrument stub: exponential heating curves, fast clock."""

    def __init__(self, params, time_scale=60.0):
        self.params = params              # {channel: (base_C, rise_C, tau_s)}
        self.time_scale = time_scale
        self.idn = "STUB,FakeDMM6500,0,selftest"
        self.t0 = time.monotonic()

    def read_temps(self):
        elapsed = (time.monotonic() - self.t0) * self.time_scale
        out = {}
        for c, (base, rise, tau) in self.params.items():
            temp = base + rise * (1.0 - math.exp(-elapsed / tau))
            out[c] = temp + random.gauss(0.0, 0.01)
        return out

    def close(self):
        pass


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
label = m.build_test_label({"mode": "C+B", "opt": "PEN(C)+GEN(B)",
                            "depth": "15", "fov": "90", "focus_num": "X",
                            "focus_area": "0-1cm"})
check("label sanitizes parentheses", "(" not in label and ")" not in label)
check("label empty when no params", m.build_test_label({}) == "")

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

# ---- End-to-end run with swapped channel roles -----------------------------
# Ambient = channel 2, probe = channel 3 (channel 3 heats up).
popups = []
for fn in ("showinfo", "showerror", "showwarning"):
    setattr(m.messagebox, fn,
            lambda title, msg, _f=fn, **k: popups.append((_f, title, str(msg))))
m.messagebox.askokcancel = lambda *a, **k: True

app = m.App()
app.withdraw()
app.ambient_combo.set("Channel 2 (T2)")
app._on_ambient_change()
check("roles: probe=ch3 ambient=ch2",
      app.probe_ch == 3 and app.ambient_ch == 2)

app.dmm = StubDmm({3: (37.0, 4.6, 300.0),   # probe: heats up, rise < 6 C
                   2: (23.2, 0.15, 600.0)},  # ambient: nearly stable
                  time_scale=60.0)
app.interval_var.set("0.25")
app.duration_var.set("30")
app.mode_var.set("rise6")
app.offset_var.set("0.0")
app.operator_var.set("selftest")
app.dut_var.set("DEMO-ICE-001")
app.tx_vars["console_sw"].set("V1.0.0.105919")
app.tx_vars["mode"].set("B")
app.tx_vars["opt"].set("PEN")
app.tx_vars["depth"].set("15")
app.tx_vars["fov"].set("90")
app.tx_vars["focus_num"].set("1")
app.tx_vars["focus_area"].set("1cm")
app.tx_vars["f_mhz"].set("4.5")

app.start_test()
check("test started", app.running)
check("test label built", app.test_label == "B-PEN-D15-FOV90-FN1-1cm")

t_end = time.time() + 60
while app.running and time.time() < t_end:
    app.update()
    time.sleep(0.02)

check("test auto-stopped", not app.running)
print("stop reason:", app.stop_reason)
check("auto-stop on T3 probe steady state",
      "T3" in app.stop_reason and "steady state" in app.stop_reason)
check("samples collected (>40)", len(app.times) > 40)

check("CSV filename carries label",
      app.csv_path and "B-PEN-D15-FOV90-FN1-1cm" in os.path.basename(app.csv_path))
csv_ok = app.csv_path and os.path.isfile(app.csv_path)
check("CSV written", bool(csv_ok))
if csv_ok:
    with open(app.csv_path, encoding="utf-8") as f:
        csv_text = f.read()
    check("CSV has # metadata", csv_text.startswith("# program:"))
    check("CSV metadata has console mode", "# console_mode: B" in csv_text)
    check("CSV header swapped roles",
          "T3_probe_C (ch3)" in csv_text and "T2_ambient_C (ch2)" in csv_text)

out_dir = m.OUTPUT_DIR
reports = sorted(f for f in os.listdir(out_dir) if f.startswith("report_"))
pngs = sorted(f for f in os.listdir(out_dir) if f.startswith("tempplot_"))
check("report written", bool(reports))
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
    check("report swapped probe section", "T3 probe (channel 3" in rep)
    check("report swapped ambient section", "T2 ambient (channel 2" in rep)
    check("report has operating settings block",
          "Operating settings of the ultrasound console (201.11.1.3.102)" in rep)
    check("report lists console SW", "V1.0.0.105919" in rep)
    check("report lists F MHz", "4.5 MHz" in rep)

check("no SimulatedDmm in app module", not hasattr(m, "SimulatedDmm"))

app._on_close()

print("\n%d check(s) failed" % len(fails))
sys.exit(1 if fails else 0)
