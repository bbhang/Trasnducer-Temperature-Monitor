"""Automated self-test for temp_monitor_gui.py (logic + demo-mode smoke test)."""
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

# ---- SteadyStateDetector ---------------------------------------------------
# Rising at 1 C/min for 5 min -> never steady.
d = m.SteadyStateDetector()
for i in range(0, 301):
    d.add(float(i), 37.0 + i / 60.0)
check("detector: 1 C/min ramp is NOT steady", not d.steady)

# Flat for 5 min -> steady after window + 3 min hold.
d = m.SteadyStateDetector()
for i in range(0, 301):
    d.add(float(i), 40.0)
check("detector: flat 5 min IS steady", d.steady)

# Exponential approach: steady only once rate drops below 0.12 C/min.
d = m.SteadyStateDetector()
tau, rise = 200.0, 5.0
steady_t = None
for i in range(0, 1801):
    d.add(float(i), 37.0 + rise * (1 - math.exp(-i / tau)))
    if d.steady and steady_t is None:
        steady_t = i
# rate(t) = rise/tau*exp(-t/tau)*60 C/min = 1.5*exp(-t/200); <0.12 at t≈505 s,
# plus 180 s hold -> expect steady around 700 s.
check("detector: exponential becomes steady", d.steady)
check("detector: steady time plausible (600-900 s)",
      steady_t is not None and 600 <= steady_t <= 900)

# ---- Demo-mode end-to-end smoke test ---------------------------------------
# Intercept all popups so the run is non-interactive.
popups = []
for fn in ("showinfo", "showerror", "showwarning"):
    setattr(m.messagebox, fn, lambda title, msg, _f=fn, **k: popups.append((_f, title, str(msg))))
m.messagebox.askokcancel = lambda *a, **k: True

app = m.App()
app.withdraw()
app.demo_var.set(True)
app.demo_speed_var.set("60")          # 60x: 30 simulated min in 30 real s
app.interval_var.set("0.25")
app.duration_var.set("30")
app.mode_var.set("rise6")
app.offset_var.set("0.0")
app.operator_var.set("selftest")
app.dut_var.set("DEMO-ICE-001")
app._connect()
check("demo connect", app.dmm is not None)

app.start_test()
check("test started", app.running)

t_end = time.time() + 60
while app.running and time.time() < t_end:
    app.update()
    time.sleep(0.02)

check("test auto-stopped", not app.running)
print("stop reason:", app.stop_reason)
check("auto-stop was steady-state or duration",
      "steady state" in app.stop_reason or "duration" in app.stop_reason)
check("samples collected (>40)", len(app.times) > 40)

csv_ok = app.csv_path and os.path.isfile(app.csv_path) and os.path.getsize(app.csv_path) > 1000
check("CSV written", bool(csv_ok))
out_dir = m.OUTPUT_DIR
stamp_files = sorted(os.listdir(out_dir))
report = [f for f in stamp_files if f.startswith("report_")]
png = [f for f in stamp_files if f.startswith("tempplot_")]
check("report written", bool(report))
check("plot PNG written", bool(png))
check("finish popup shown", any(p[0] == "showinfo" for p in popups))

if report:
    with open(os.path.join(out_dir, report[-1]), encoding="utf-8") as f:
        rep = f.read()
    print("\n----- report excerpt -----")
    print("\n".join(rep.splitlines()[:14]))
    check("report contains verdict", "Verdict" in rep)
    check("report contains clause", "201.11.1.3.101.1 b)" in rep)
    # Demo rises are 4.6/5.4 C -> rise6 should PASS
    check("demo rise6 verdict PASS", "Verdict          : PASS" in rep)

app._on_close()

print("\n%d check(s) failed" % len(fails))
sys.exit(1 if fails else 0)
