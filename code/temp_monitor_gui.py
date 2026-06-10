"""ICE Transducer Temperature Monitor.

Acquires temperatures from two thermocouple probes (T2, T3) connected to
channels 2 and 3 of a Keithley DMM6500 (rear-panel scanner card, USB/VISA)
and evaluates them against IEC 60601-2-37:2024 clause 201.11 limits for an
INVASIVE TRANSDUCER ASSEMBLY (intracardiac echo catheter).

Test modes (see doc/IEC_60601-2-37_Requirements_Summary.md):
  - Simulated use a) peak temperature:  surface temperature <= 43 C
  - Simulated use b) temperature rise:  rise + thermal offset <= 6 C
  - Still air:                          rise + thermal offset <= 27 C

Thermal steady state: rate of change < 0.12 C/min for 3 consecutive minutes.
Test duration: 30 min or until thermal steady state (201.11.1.3.103).

Run:  python temp_monitor_gui.py
Demo mode (no instrument needed) is available from the GUI.
"""

import csv
import math
import os
import queue
import random
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHANNELS = (2, 3)                 # DMM6500 scanner-card channels for T2, T3
PROBE_CH = 2                      # T2: transducer surface (device under test)
AMBIENT_CH = 3                    # T3: ambient reference (test condition record)
CHANNEL_LABELS = {PROBE_CH: "T2 probe", AMBIENT_CH: "T3 ambient"}
AMBIENT_MIN_C = 20.0              # 201.11.1.3.101: ambient 23 +/- 3 C
AMBIENT_MAX_C = 26.0
AMBIENT_STABLE_BAND_C = 0.5       # still-air test: ambient stable within 0.5 C
DEFAULT_TC_TYPE = "T"
DEFAULT_INTERVAL_S = 1.0
DEFAULT_DURATION_MIN = 30.0       # 201.11.1.3.103
WARNING_TEMP_C = 41.0             # 201.12.4.2 j) conservative warning
STEADY_RATE_C_PER_MIN = 0.12      # 201.11.1.3.101
STEADY_HOLD_S = 180.0             # three consecutive minutes
STEADY_RATE_WINDOW_S = 60.0       # window used for the rate estimate

OUTPUT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temp")
)

TEST_MODES = {
    "peak": {
        "name": "Simulated use a) Peak temperature (invasive)",
        "clause": "201.11.1.3.101.1 a)",
        "limit": 43.0,
        "kind": "absolute",
        "criterion": "Maximum surface temperature <= 43.0 C",
    },
    "rise6": {
        "name": "Simulated use b) Temperature rise (invasive)",
        "clause": "201.11.1.3.101.1 b)",
        "limit": 6.0,
        "kind": "rise",
        "criterion": "Temperature rise + thermal offset <= 6.0 C",
    },
    "rise27": {
        "name": "Still air (no coupling gel)",
        "clause": "201.11.1.3.101.2",
        "limit": 27.0,
        "kind": "rise",
        "criterion": "Temperature rise + thermal offset <= 27.0 C",
    },
}


# ---------------------------------------------------------------------------
# Pass/fail evaluation (pure logic, unit-testable)
# ---------------------------------------------------------------------------

def evaluate_channel(mode_key, max_temp, baseline, thermal_offset):
    """Return (measured_value, limit, passed) for one channel.

    mode 'peak'  : value = max_temp,                       limit 43 C
    mode 'rise6' : value = max_temp - baseline + offset,   limit 6 C
    mode 'rise27': value = max_temp - baseline + offset,   limit 27 C
    """
    mode = TEST_MODES[mode_key]
    if mode["kind"] == "absolute":
        value = max_temp
    else:
        value = (max_temp - baseline) + thermal_offset
    return value, mode["limit"], value <= mode["limit"]


class SteadyStateDetector:
    """Detects thermal steady state per 201.11.1.3.101.

    Steady state is reached when the temperature rate of change (linear fit
    over the trailing `window_s` seconds) stays below `rate_limit` C/min for
    `hold_s` consecutive seconds.
    """

    def __init__(self, rate_limit=STEADY_RATE_C_PER_MIN,
                 window_s=STEADY_RATE_WINDOW_S, hold_s=STEADY_HOLD_S):
        self.rate_limit = rate_limit
        self.window_s = window_s
        self.hold_s = hold_s
        self.samples = deque()
        self.below_since = None
        self.steady = False
        self.steady_at = None
        self.last_rate = None

    def add(self, t, temp):
        self.samples.append((t, temp))
        while self.samples and self.samples[0][0] < t - self.window_s - 1.0:
            self.samples.popleft()
        rate = self._rate_per_min()
        self.last_rate = rate
        if rate is None:
            return
        if abs(rate) < self.rate_limit:
            if self.below_since is None:
                self.below_since = t
            elif not self.steady and (t - self.below_since) >= self.hold_s:
                self.steady = True
                self.steady_at = t
        else:
            self.below_since = None
            if not self.steady:
                self.steady_at = None

    def _rate_per_min(self):
        pts = list(self.samples)
        if len(pts) < 3 or (pts[-1][0] - pts[0][0]) < self.window_s * 0.5:
            return None
        n = len(pts)
        mean_t = sum(p[0] for p in pts) / n
        mean_y = sum(p[1] for p in pts) / n
        sxx = sum((p[0] - mean_t) ** 2 for p in pts)
        if sxx == 0:
            return None
        sxy = sum((p[0] - mean_t) * (p[1] - mean_y) for p in pts)
        return (sxy / sxx) * 60.0  # C/s -> C/min


# ---------------------------------------------------------------------------
# Instrument layer
# ---------------------------------------------------------------------------

class Dmm6500:
    """Keithley DMM6500 with scanner card, thermocouples on channels 2 and 3."""

    def __init__(self, resource_name, tc_type=DEFAULT_TC_TYPE, channels=CHANNELS):
        self.resource_name = resource_name
        self.tc_type = tc_type
        self.channels = channels
        self.inst = None
        self.idn = ""

    MODEL_KEYWORD = "DMM6500"

    def connect(self):
        import pyvisa
        rm = pyvisa.ResourceManager()
        self.inst = rm.open_resource(self.resource_name)
        self.inst.timeout = 10000
        self.inst.write_termination = "\n"
        self.inst.read_termination = "\n"
        self.idn = self.inst.query("*IDN?").strip()
        # Refuse to configure (and *RST) anything that is not the meter, e.g.
        # an oscilloscope or signal generator on the same USB bus.
        if self.MODEL_KEYWORD not in self.idn.upper():
            idn = self.idn
            self.inst.close()
            self.inst = None
            raise IOError(
                f"The instrument at {self.resource_name} reports:\n  {idn}\n"
                f"This is not a {self.MODEL_KEYWORD}. Click Refresh to "
                "auto-detect the meter.")
        self._configure()
        return self.idn

    def _configure(self):
        ch = ",".join(str(c) for c in self.channels)
        self._write_checked("*RST")
        self.inst.query("*OPC?")
        # Cold-junction compensation: the 2000-SCAN card has no built-in
        # reference junction sensor (the instrument rejects INTernal with
        # "channel does not support internal reference"), so a SIMulated
        # reference junction is used. Its temperature is updated to the
        # operator-entered ambient value at test start.
        for cmd in (
            f":SENS:FUNC 'TEMP', (@{ch})",
            f":SENS:TEMP:TRAN TC, (@{ch})",
            f":SENS:TEMP:TC:TYPE {self.tc_type}, (@{ch})",
            f":SENS:TEMP:UNIT CELS, (@{ch})",
            f":SENS:TEMP:NPLC 1, (@{ch})",
            f":SENS:TEMP:TC:RJUN:RSEL SIM, (@{ch})",
            f":SENS:TEMP:TC:RJUN:SIM 23, (@{ch})",
        ):
            self._write_checked(cmd)
        self.inst.query("*OPC?")

    def set_sim_ref_junction(self, temp_c):
        """Set the simulated reference-junction (cold-junction) temperature."""
        ch = ",".join(str(c) for c in self.channels)
        self._write_checked(f":SENS:TEMP:TC:RJUN:SIM {temp_c:.2f}, (@{ch})")

    def _write_checked(self, cmd):
        """Send a SCPI command and raise IOError listing any instrument errors."""
        self.inst.write(cmd)
        errors = []
        for _ in range(20):
            err = self.inst.query(":SYST:ERR?").strip()
            if err.split(",")[0].lstrip("+") == "0":
                break
            errors.append(err)
        if errors:
            raise IOError(f"SCPI command failed: {cmd!r} -> {'; '.join(errors)}")

    def read_temps(self):
        """Read all channels once; returns {channel: temperature_C}."""
        out = {}
        for c in self.channels:
            self.inst.write(f":ROUT:CLOS (@{c})")
            value = float(self.inst.query(":READ?"))
            if abs(value) > 1e30:  # +9.9e37 = overflow / open thermocouple
                raise IOError(f"Channel {c} reads overflow - thermocouple "
                              "open or not connected?")
            out[c] = value
        return out

    def close(self):
        if self.inst is not None:
            try:
                self.inst.write(":ROUT:OPEN:ALL")
                self.inst.close()
            except Exception:
                pass
            self.inst = None

    @staticmethod
    def identify_resources():
        """Query *IDN? on every VISA resource (USB first).

        Returns a list of (resource, idn) tuples; idn is a placeholder string
        for instruments that do not answer (busy, non-SCPI, ...). *IDN? is a
        mandatory IEEE-488.2 query and is safe to send to scopes, signal
        generators, etc.
        """
        import pyvisa
        try:
            rm = pyvisa.ResourceManager()
            resources = list(rm.list_resources())
        except Exception:
            return []
        resources.sort(key=lambda r: 0 if r.upper().startswith("USB") else 1)
        out = []
        for res in resources:
            try:
                inst = rm.open_resource(res)
                inst.timeout = 1500
                try:
                    idn = inst.query("*IDN?").strip()
                finally:
                    inst.close()
            except Exception as exc:
                idn = f"(no response: {exc.__class__.__name__})"
            out.append((res, idn))
        return out


class SimulatedDmm:
    """Demo instrument producing exponential self-heating curves.

    The time_scale factor accelerates simulated time so a 30 min test can be
    previewed in a couple of minutes.
    """

    IDN = "DEMO,SimulatedDMM6500,0,1.0"

    def __init__(self, tc_type=DEFAULT_TC_TYPE, channels=CHANNELS, time_scale=1.0):
        self.tc_type = tc_type
        self.channels = channels
        self.time_scale = time_scale
        self.t0 = None
        # baseline C, total rise C, time constant s  (per channel)
        self.params = {
            PROBE_CH: (37.0, 4.6, 300.0),    # heating transducer surface
            AMBIENT_CH: (23.2, 0.15, 600.0),  # nearly-stable room ambient
        }

    def connect(self):
        self.t0 = time.monotonic()
        return self.IDN

    def read_temps(self):
        elapsed = (time.monotonic() - self.t0) * self.time_scale
        out = {}
        for c in self.channels:
            base, rise, tau = self.params.get(c, (37.0, 5.0, 300.0))
            temp = base + rise * (1.0 - math.exp(-elapsed / tau))
            out[c] = temp + random.gauss(0.0, 0.01)
        return out

    def close(self):
        self.t0 = None


# ---------------------------------------------------------------------------
# GUI application
# ---------------------------------------------------------------------------

class App(tk.Tk):
    POLL_MS = 250

    def __init__(self):
        super().__init__()
        self.title("ICE Transducer Temperature Monitor - DMM6500 - IEC 60601-2-37:2024")
        self.geometry("1280x800")
        self.minsize(1100, 700)

        self.dmm = None
        self.acq_thread = None
        self.acq_stop = threading.Event()
        self.data_queue = queue.Queue()

        self.running = False
        self.test_start_wall = None
        self.test_start_mono = None
        self.baseline = {}
        self.max_temp = {}
        self.current = {}
        self.detectors = {}
        self.times = []                       # elapsed seconds
        self.temps = {c: [] for c in CHANNELS}
        self.csv_file = None
        self.csv_writer = None
        self.csv_path = None
        self.stop_reason = ""
        self.fail_latched = False
        self.last_plot_update = 0.0

        self._build_ui()
        self.after(self.POLL_MS, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)

        self._build_connection_panel(root)

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, pady=(6, 0))
        left = ttk.Frame(body, width=380)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)

        self._build_config_panel(left)
        self._build_control_panel(left)
        self._build_verdict_panel(left)
        self._build_readout_panel(right)
        self._build_plot(right)

    def _build_connection_panel(self, parent):
        frm = ttk.LabelFrame(parent, text="Instrument connection", padding=6)
        frm.pack(fill="x")

        self.demo_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Demo mode (no instrument)",
                        variable=self.demo_var,
                        command=self._on_demo_toggle).pack(side="left")

        ttk.Label(frm, text="  Demo speed x").pack(side="left")
        self.demo_speed_var = tk.StringVar(value="1")
        ttk.Spinbox(frm, from_=1, to=120, width=5,
                    textvariable=self.demo_speed_var).pack(side="left")

        ttk.Label(frm, text="   VISA resource:").pack(side="left")
        self.resource_var = tk.StringVar()
        self.resource_combo = ttk.Combobox(frm, textvariable=self.resource_var,
                                           width=42)
        self.resource_combo.pack(side="left", padx=4)
        ttk.Button(frm, text="Refresh", command=self._refresh_resources).pack(side="left")
        self.connect_btn = ttk.Button(frm, text="Connect", command=self._connect)
        self.connect_btn.pack(side="left", padx=4)

        self.conn_status = ttk.Label(frm, text="Not connected", foreground="gray")
        self.conn_status.pack(side="left", padx=8)

    def _build_config_panel(self, parent):
        frm = ttk.LabelFrame(parent, text="Test configuration (IEC 60601-2-37:2024)",
                             padding=6)
        frm.pack(fill="x", pady=(0, 6))

        self.mode_var = tk.StringVar(value="peak")
        for key in ("peak", "rise6", "rise27"):
            m = TEST_MODES[key]
            ttk.Radiobutton(
                frm, value=key, variable=self.mode_var,
                text=f"{m['name']}\n    {m['clause']}: {m['criterion']}",
                command=self._on_mode_change,
            ).pack(anchor="w", pady=2)

        grid = ttk.Frame(frm)
        grid.pack(fill="x", pady=(6, 0))

        def row(r, label, var, width=8, unit=""):
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky="w")
            e = ttk.Entry(grid, textvariable=var, width=width)
            e.grid(row=r, column=1, sticky="w", padx=4)
            if unit:
                ttk.Label(grid, text=unit).grid(row=r, column=2, sticky="w")
            return e

        self.offset_var = tk.StringVar(value="0.0")
        row(0, "Thermal offset", self.offset_var, unit="C  (201.3.228)")
        self.ambient_var = tk.StringVar(value="23.0")
        row(1, "Ambient temperature", self.ambient_var, unit="C  (23 +/- 3 C)")
        self.interval_var = tk.StringVar(value=str(DEFAULT_INTERVAL_S))
        row(2, "Sample interval", self.interval_var, unit="s")
        self.duration_var = tk.StringVar(value=str(DEFAULT_DURATION_MIN))
        row(3, "Max test duration", self.duration_var, unit="min  (201.11.1.3.103)")

        ttk.Label(grid, text="Thermocouple type").grid(row=4, column=0, sticky="w")
        self.tc_var = tk.StringVar(value=DEFAULT_TC_TYPE)
        ttk.Combobox(grid, textvariable=self.tc_var, values=("T", "K", "J"),
                     width=6, state="readonly").grid(row=4, column=1, sticky="w", padx=4)

        self.autostop_steady_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Auto-stop when both channels reach thermal "
                                  "steady state\n(< 0.12 C/min for 3 min)",
                        variable=self.autostop_steady_var).pack(anchor="w", pady=(6, 0))

        meta = ttk.Frame(frm)
        meta.pack(fill="x", pady=(6, 0))
        ttk.Label(meta, text="Operator").grid(row=0, column=0, sticky="w")
        self.operator_var = tk.StringVar()
        ttk.Entry(meta, textvariable=self.operator_var, width=18).grid(
            row=0, column=1, sticky="w", padx=4)
        ttk.Label(meta, text="Probe / DUT ID").grid(row=1, column=0, sticky="w")
        self.dut_var = tk.StringVar()
        ttk.Entry(meta, textvariable=self.dut_var, width=18).grid(
            row=1, column=1, sticky="w", padx=4)

    def _build_control_panel(self, parent):
        frm = ttk.LabelFrame(parent, text="Run control", padding=6)
        frm.pack(fill="x", pady=(0, 6))

        btns = ttk.Frame(frm)
        btns.pack(fill="x")
        self.start_btn = ttk.Button(btns, text="Start test", command=self.start_test,
                                    state="disabled")
        self.start_btn.pack(side="left", padx=2)
        self.stop_btn = ttk.Button(btns, text="Stop test", command=self.stop_test,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=2)

        self.elapsed_label = ttk.Label(frm, text="Elapsed: 00:00",
                                       font=("Segoe UI", 12, "bold"))
        self.elapsed_label.pack(anchor="w", pady=(6, 0))
        self.status_label = ttk.Label(frm, text="Idle", foreground="gray",
                                      wraplength=340)
        self.status_label.pack(anchor="w")

    def _build_verdict_panel(self, parent):
        frm = ttk.LabelFrame(parent, text="Compliance verdict", padding=6)
        frm.pack(fill="both", expand=True)

        self.verdict_label = tk.Label(frm, text="--", font=("Segoe UI", 28, "bold"),
                                      fg="gray")
        self.verdict_label.pack(pady=(4, 8))

        self.verdict_detail = ttk.Label(frm, text="", justify="left", wraplength=340,
                                        font=("Consolas", 10))
        self.verdict_detail.pack(anchor="w")

    def _build_readout_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill="x")
        self.readouts = {}
        for c in CHANNELS:
            box = ttk.LabelFrame(frm, text=f"{CHANNEL_LABELS[c]}  (channel {c})",
                                 padding=6)
            box.pack(side="left", fill="x", expand=True, padx=(0, 6))
            cur = tk.Label(box, text="--.- C", font=("Segoe UI", 26, "bold"))
            cur.pack()
            sub = ttk.Label(box, text="max --.-   rise --.-   rate --.-",
                            font=("Consolas", 10))
            sub.pack()
            steady = tk.Label(box, text="steady state: --", font=("Segoe UI", 9))
            steady.pack()
            self.readouts[c] = {"cur": cur, "sub": sub, "steady": steady}

    def _build_plot(self, parent):
        self.fig = Figure(figsize=(7, 4.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Elapsed time (min)")
        self.ax.set_ylabel("Temperature (C)")
        self.ax.grid(True, alpha=0.3)
        self.lines = {}
        colors = {PROBE_CH: "tab:red", AMBIENT_CH: "tab:green"}
        for c in CHANNELS:
            (line,) = self.ax.plot([], [], label=CHANNEL_LABELS[c], color=colors[c])
            self.lines[c] = line
        self.limit_line = self.ax.axhline(43.0, color="red", linestyle="--",
                                          alpha=0.7, label="Limit")
        self.warn_line = self.ax.axhline(WARNING_TEMP_C, color="orange",
                                         linestyle=":", alpha=0.7,
                                         label=f"Warning {WARNING_TEMP_C:.0f} C")
        self.ax.legend(loc="lower right")
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, pady=(6, 0))

    # ------------------------------------------------------ connection

    def _on_demo_toggle(self):
        if self.demo_var.get():
            self.resource_combo.configure(state="disabled")
        else:
            self.resource_combo.configure(state="normal")

    def _refresh_resources(self):
        self.conn_status.configure(text="Scanning instruments (*IDN?)...",
                                   foreground="gray")
        self.update_idletasks()
        found = Dmm6500.identify_resources()
        self.resource_map = {}
        labels = []
        meter_label = None
        for res, idn in found:
            parts = [p.strip() for p in idn.split(",")]
            model = parts[1] if len(parts) >= 2 else idn[:32]
            label = f"{model}  |  {res}"
            self.resource_map[label] = res
            labels.append(label)
            if meter_label is None and Dmm6500.MODEL_KEYWORD in idn.upper():
                meter_label = label
        self.resource_combo["values"] = labels
        if meter_label:
            self.resource_var.set(meter_label)
            self.conn_status.configure(
                text=f"{Dmm6500.MODEL_KEYWORD} detected automatically",
                foreground="green")
        elif labels:
            self.resource_var.set(labels[0])
            self.conn_status.configure(
                text=f"{len(labels)} instrument(s) found, "
                     f"no {Dmm6500.MODEL_KEYWORD}", foreground="orange")
        else:
            self.conn_status.configure(text="No VISA instruments found",
                                       foreground="gray")

    def _connect(self):
        if self.dmm is not None:
            self._disconnect()
            return
        try:
            if self.demo_var.get():
                speed = max(1.0, float(self.demo_speed_var.get() or 1))
                dmm = SimulatedDmm(tc_type=self.tc_var.get(), time_scale=speed)
            else:
                sel = self.resource_var.get().strip()
                if not sel:
                    messagebox.showwarning("No resource",
                                           "Select a VISA resource or enable Demo mode.")
                    return
                # Map the friendly "model | resource" label back to the VISA
                # address; raw addresses typed by the user pass through as-is.
                res = getattr(self, "resource_map", {}).get(sel, sel)
                dmm = Dmm6500(res, tc_type=self.tc_var.get())
            idn = dmm.connect()
        except Exception as exc:
            messagebox.showerror("Connection failed", str(exc))
            return
        self.dmm = dmm
        self.conn_status.configure(text=idn[:60], foreground="green")
        self.connect_btn.configure(text="Disconnect")
        self.start_btn.configure(state="normal")
        self.status_label.configure(text="Connected. Configure the test and press "
                                         "Start.", foreground="black")

    def _disconnect(self):
        if self.running:
            self.stop_test()
        if self.dmm is not None:
            self.dmm.close()
            self.dmm = None
        self.conn_status.configure(text="Not connected", foreground="gray")
        self.connect_btn.configure(text="Connect")
        self.start_btn.configure(state="disabled")

    # ------------------------------------------------------ test control

    def _read_config(self):
        try:
            offset = float(self.offset_var.get())
            interval = float(self.interval_var.get())
            duration = float(self.duration_var.get())
            ambient = float(self.ambient_var.get())
        except ValueError:
            raise ValueError("Thermal offset, ambient, interval and duration "
                             "must be numeric.")
        if interval < 0.2:
            raise ValueError("Sample interval must be >= 0.2 s.")
        if duration <= 0:
            raise ValueError("Duration must be positive.")
        if not (20.0 <= ambient <= 26.0):
            messagebox.showwarning(
                "Ambient temperature",
                "201.11.1.3.101 requires an ambient temperature of 23 +/- 3 C.\n"
                f"Entered value: {ambient:.1f} C. The test will continue, but the "
                "condition is recorded in the report.")
        return offset, interval, duration, ambient

    def start_test(self):
        if self.dmm is None or self.running:
            return
        try:
            self.cfg_offset, self.cfg_interval, self.cfg_duration, self.cfg_ambient = \
                self._read_config()
        except ValueError as exc:
            messagebox.showerror("Invalid configuration", str(exc))
            return

        try:
            # Use the operator-entered ambient temperature as the simulated
            # cold-junction temperature (2000-SCAN card has no CJC sensor).
            if isinstance(self.dmm, Dmm6500):
                self.dmm.set_sim_ref_junction(self.cfg_ambient)
            first = self.dmm.read_temps()
        except Exception as exc:
            messagebox.showerror("Read failed", f"Could not read instrument:\n{exc}")
            return

        # In demo mode the elapsed-time clock is accelerated together with the
        # simulated heating so a 30 min test can be previewed in seconds.
        self.time_scale = getattr(self.dmm, "time_scale", 1.0)
        self.baseline = dict(first)
        self.max_temp = dict(first)
        self.min_temp = dict(first)
        self.current = dict(first)
        self.detectors = {c: SteadyStateDetector() for c in CHANNELS}
        self.times = [0.0]
        self.temps = {c: [first[c]] for c in CHANNELS}
        self.fail_latched = False
        self.stop_reason = ""
        self.test_start_wall = datetime.now()
        self.test_start_mono = time.monotonic()
        for c in CHANNELS:
            self.detectors[c].add(0.0, first[c])

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        stamp = self.test_start_wall.strftime("%Y%m%d_%H%M%S")
        self.csv_path = os.path.join(OUTPUT_DIR, f"templog_{stamp}.csv")
        self.csv_file = open(self.csv_path, "w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(["timestamp", "elapsed_s",
                                  "T2_probe_C (ch2)", "T3_ambient_C (ch3)"])
        self.csv_writer.writerow([self.test_start_wall.isoformat(timespec="seconds"),
                                  "0.0", f"{first[2]:.3f}", f"{first[3]:.3f}"])

        self.acq_stop.clear()
        self.acq_thread = threading.Thread(target=self._acquire_loop, daemon=True)
        self.acq_thread.start()

        self.running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        mode = TEST_MODES[self.mode_var.get()]
        self.status_label.configure(
            text=f"Running: {mode['name']} ({mode['clause']}). Baseline "
                 f"T2={first[2]:.2f} C, T3={first[3]:.2f} C.",
            foreground="black")
        self._update_limit_lines()
        self._set_verdict("IN PROGRESS", "gray")

    def _update_limit_lines(self):
        mode = TEST_MODES[self.mode_var.get()]
        if mode["kind"] == "absolute":
            limit_y = mode["limit"]
            self.warn_line.set_visible(True)
        else:
            base = self.baseline.get(PROBE_CH, 37.0)
            limit_y = base + mode["limit"] - getattr(self, "cfg_offset", 0.0)
            self.warn_line.set_visible(False)
        self.limit_line.set_ydata([limit_y, limit_y])
        self.limit_line.set_label(f"Limit ({mode['clause']})")
        visible = [ln for ln in (*self.lines.values(), self.limit_line,
                                 self.warn_line) if ln.get_visible()]
        self.ax.legend(visible, [ln.get_label() for ln in visible],
                       loc="lower right")
        self.canvas.draw_idle()

    def _on_mode_change(self):
        if not self.running:
            self._update_limit_lines()

    def stop_test(self, reason=None):
        if not self.running:
            return
        self.running = False
        self.acq_stop.set()
        self.stop_reason = reason or "Stopped by operator"
        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
        self.start_btn.configure(state="normal" if self.dmm else "disabled")
        self.stop_btn.configure(state="disabled")
        self._finalize_test()

    # ------------------------------------------------------ acquisition

    def _acquire_loop(self):
        interval = self.cfg_interval
        next_t = time.monotonic()
        while not self.acq_stop.is_set():
            try:
                temps = self.dmm.read_temps()
                self.data_queue.put(("data", time.monotonic(), temps))
            except Exception as exc:
                self.data_queue.put(("error", time.monotonic(), str(exc)))
                return
            next_t += interval
            delay = next_t - time.monotonic()
            if delay > 0:
                if self.acq_stop.wait(delay):
                    return
            else:
                next_t = time.monotonic()

    def _poll_queue(self):
        try:
            while True:
                kind, t_mono, payload = self.data_queue.get_nowait()
                if kind == "error":
                    if self.running:
                        self.stop_test(reason=f"Instrument error: {payload}")
                        messagebox.showerror("Instrument error", payload)
                elif kind == "data" and self.running:
                    self._handle_sample(t_mono, payload)
        except queue.Empty:
            pass
        self.after(self.POLL_MS, self._poll_queue)

    def _handle_sample(self, t_mono, temps):
        elapsed = (t_mono - self.test_start_mono) * self.time_scale
        self.times.append(elapsed)
        for c in CHANNELS:
            v = temps[c]
            self.current[c] = v
            self.temps[c].append(v)
            if v > self.max_temp[c]:
                self.max_temp[c] = v
            if v < self.min_temp[c]:
                self.min_temp[c] = v
            self.detectors[c].add(elapsed, v)
        if self.csv_writer:
            self.csv_writer.writerow([datetime.now().isoformat(timespec="seconds"),
                                      f"{elapsed:.1f}",
                                      f"{temps[2]:.3f}", f"{temps[3]:.3f}"])
        self._update_readouts(elapsed)
        self._update_verdict_live()

        now = time.monotonic()
        if now - self.last_plot_update > 0.8:
            self.last_plot_update = now
            self._update_plot()

        # Auto-stop per 201.11.1.3.103: 30 min or thermal steady state.
        if elapsed >= self.cfg_duration * 60.0:
            self.stop_test(reason=f"Maximum duration reached "
                                  f"({self.cfg_duration:g} min, 201.11.1.3.103)")
        elif (self.autostop_steady_var.get()
              and self.detectors[PROBE_CH].steady):
            self.stop_test(reason="Thermal steady state reached on T2 probe "
                                  "(< 0.12 C/min for 3 min, 201.11.1.3.101)")

    # ------------------------------------------------------ display

    def _update_readouts(self, elapsed):
        mins, secs = divmod(int(elapsed), 60)
        self.elapsed_label.configure(text=f"Elapsed: {mins:02d}:{secs:02d}")
        for c in CHANNELS:
            r = self.readouts[c]
            cur = self.current[c]
            rise = self.max_temp[c] - self.baseline[c]
            drift = self.max_temp[c] - self.min_temp[c]
            det = self.detectors[c]
            rate = det.last_rate
            rate_txt = f"{rate:+.3f}" if rate is not None else "--"
            r["cur"].configure(text=f"{cur:.2f} C")
            r["sub"].configure(text=f"max {self.max_temp[c]:.2f} C   "
                                    f"rise {rise:.2f} C   drift {drift:.2f} C   "
                                    f"rate {rate_txt} C/min")
            if c == PROBE_CH:
                if det.steady:
                    r["steady"].configure(text="steady state: YES", fg="green")
                else:
                    r["steady"].configure(text="steady state: not yet", fg="gray")
                if self.mode_var.get() == "peak":
                    if cur > TEST_MODES["peak"]["limit"]:
                        r["cur"].configure(fg="red")
                    elif cur >= WARNING_TEMP_C:
                        r["cur"].configure(fg="orange")
                    else:
                        r["cur"].configure(fg="black")
                else:
                    _, _, ok = evaluate_channel(
                        self.mode_var.get(), self.max_temp[c], self.baseline[c],
                        self.cfg_offset)
                    r["cur"].configure(fg="black" if ok else "red")
            else:
                # Ambient reference channel: show 23 +/- 3 C condition and
                # drift (still-air test requires stability within 0.5 C).
                drift = self.max_temp[c] - self.min_temp[c]
                in_range = AMBIENT_MIN_C <= cur <= AMBIENT_MAX_C
                r["cur"].configure(fg="black" if in_range else "orange")
                r["steady"].configure(
                    text=f"23 +/- 3 C: {'OK' if in_range else 'OUT OF RANGE'}   "
                         f"drift {drift:.2f} C",
                    fg="green" if in_range and drift <= AMBIENT_STABLE_BAND_C
                    else "orange")

    def _update_verdict_live(self):
        mode_key = self.mode_var.get()
        value, limit, ok = evaluate_channel(
            mode_key, self.max_temp[PROBE_CH], self.baseline[PROBE_CH],
            self.cfg_offset)
        kind = TEST_MODES[mode_key]["kind"]
        what = "max temp" if kind == "absolute" else "rise+offset"
        amb = self.current[AMBIENT_CH]
        amb_drift = self.max_temp[AMBIENT_CH] - self.min_temp[AMBIENT_CH]
        amb_ok = AMBIENT_MIN_C <= amb <= AMBIENT_MAX_C
        probe_drift = self.max_temp[PROBE_CH] - self.min_temp[PROBE_CH]
        lines = [
            f"T2 probe: {what} = {value:6.2f} C "
            f"(limit {limit:.1f} C)  {'OK' if ok else 'EXCEEDED'}, "
            f"drift {probe_drift:.2f} C",
            f"T3 ambient: {amb:.2f} C "
            f"({'within' if amb_ok else 'OUTSIDE'} 23 +/- 3 C), "
            f"drift {amb_drift:.2f} C",
        ]
        self.verdict_detail.configure(text="\n".join(lines))
        if not ok:
            self.fail_latched = True
        if self.fail_latched:
            self._set_verdict("FAIL", "red")
        elif self.current[PROBE_CH] >= WARNING_TEMP_C and mode_key == "peak":
            self._set_verdict("WARNING >= 41 C", "orange")
        else:
            self._set_verdict("IN PROGRESS", "gray")

    def _set_verdict(self, text, color):
        self.verdict_label.configure(text=text, fg=color)

    def _update_plot(self):
        tmin = [t / 60.0 for t in self.times]
        for c in CHANNELS:
            self.lines[c].set_data(tmin, self.temps[c])
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    # ------------------------------------------------------ finalize

    def _finalize_test(self):
        mode_key = self.mode_var.get()
        mode = TEST_MODES[mode_key]
        value, limit, ok = evaluate_channel(
            mode_key, self.max_temp[PROBE_CH], self.baseline[PROBE_CH],
            self.cfg_offset)
        result = (value, limit, ok)
        verdict = "PASS" if ok else "FAIL"
        steady = self.detectors[PROBE_CH].steady
        completed = steady or (self.times and
                               self.times[-1] >= self.cfg_duration * 60.0 - 1)
        if ok and not completed:
            verdict = "PASS (incomplete test)"
        self._set_verdict(verdict, "green" if ok else "red")
        self.status_label.configure(text=f"Test ended: {self.stop_reason}",
                                    foreground="black")

        self._update_plot()
        stamp = self.test_start_wall.strftime("%Y%m%d_%H%M%S")
        png_path = os.path.join(OUTPUT_DIR, f"tempplot_{stamp}.png")
        try:
            self.fig.savefig(png_path, dpi=150, bbox_inches="tight")
        except Exception:
            png_path = "(plot save failed)"

        report_path = os.path.join(OUTPUT_DIR, f"report_{stamp}.txt")
        self._write_report(report_path, mode, result, verdict, png_path)
        messagebox.showinfo(
            "Test finished",
            f"Verdict: {verdict}\nReason: {self.stop_reason}\n\n"
            f"Data:   {self.csv_path}\nReport: {report_path}\nPlot:   {png_path}")

    def _write_report(self, path, mode, result, verdict, png_path):
        end_wall = datetime.now()
        elapsed = self.times[-1] if self.times else 0.0
        idn = getattr(self.dmm, "idn", None) or getattr(self.dmm, "IDN", "n/a")
        value, limit, ok = result
        p, a = PROBE_CH, AMBIENT_CH
        det = self.detectors[p]
        steady_txt = (f"yes, at {det.steady_at/60.0:.1f} min"
                      if det.steady else "no")
        amb_min, amb_max = self.min_temp[a], self.max_temp[a]
        amb_in_range = (AMBIENT_MIN_C <= amb_min and amb_max <= AMBIENT_MAX_C)
        amb_drift = amb_max - amb_min
        lines = [
            "=" * 72,
            "ICE TRANSDUCER SURFACE TEMPERATURE TEST REPORT",
            "Standard: IEC 60601-2-37:2024, clause 201.11",
            "=" * 72,
            f"Test mode        : {mode['name']}",
            f"Clause           : {mode['clause']}",
            f"Criterion        : {mode['criterion']}",
            f"Verdict          : {verdict}",
            "-" * 72,
            f"Operator         : {self.operator_var.get() or '(not entered)'}",
            f"Probe / DUT ID   : {self.dut_var.get() or '(not entered)'}",
            f"Instrument       : {idn}",
            f"Thermocouple     : type {self.tc_var.get()}; "
            "T2 probe = ch 2 (DUT surface), T3 ambient = ch 3 (reference)",
            f"Start            : {self.test_start_wall.isoformat(timespec='seconds')}",
            f"End              : {end_wall.isoformat(timespec='seconds')}",
            f"Elapsed          : {elapsed/60.0:.1f} min",
            f"Stop reason      : {self.stop_reason}",
            f"Ambient (entered): {self.cfg_ambient:.1f} C "
            f"(required 23 +/- 3 C, 201.11.1.3.101)",
            f"Thermal offset   : {self.cfg_offset:.2f} C (201.3.228)",
            f"Sample interval  : {self.cfg_interval:g} s",
            "-" * 72,
            "T2 probe (channel 2, device under test):",
            f"    Baseline             : {self.baseline[p]:.2f} C",
            f"    Min / Max            : {self.min_temp[p]:.2f} C / "
            f"{self.max_temp[p]:.2f} C",
            f"    Drift (max-min)      : {self.max_temp[p]-self.min_temp[p]:.2f} C",
            f"    Rise (max-baseline)  : {self.max_temp[p]-self.baseline[p]:.2f} C",
            f"    Evaluated value      : {value:.2f} C  (limit {limit:.1f} C)",
            f"    Result               : {'PASS' if ok else 'FAIL'}",
            f"    Thermal steady state : {steady_txt} "
            "(rate < 0.12 C/min for 3 consecutive minutes)",
            "T3 ambient (channel 3, test condition record):",
            f"    Baseline             : {self.baseline[a]:.2f} C",
            f"    Min / Max            : {amb_min:.2f} C / {amb_max:.2f} C",
            f"    Drift (max-min)      : {amb_drift:.2f} C "
            f"(still-air test requires <= {AMBIENT_STABLE_BAND_C:.1f} C)",
            f"    Within 23 +/- 3 C    : {'yes' if amb_in_range else 'NO'}",
            "-" * 72,
            "TO BE COMPLETED BY OPERATOR (required by the standard):",
            "  Transmit parameters / operating settings (201.11.1.3.102): ________",
            "  Measurement uncertainty (201.11.1.3.104):                  ________",
            "  Test object temperature before contact (>= 37 C, method a): _______",
            "-" * 72,
            f"Data file : {self.csv_path}",
            f"Plot file : {png_path}",
            "=" * 72,
        ]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # ------------------------------------------------------ shutdown

    def _on_close(self):
        if self.running:
            if not messagebox.askokcancel("Quit", "A test is running. Stop and quit?"):
                return
            self.stop_test(reason="Application closed")
        if self.dmm is not None:
            self.dmm.close()
        self.destroy()


def main():
    app = App()
    app._refresh_resources()
    app.mainloop()


if __name__ == "__main__":
    main()
