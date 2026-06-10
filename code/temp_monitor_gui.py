#!/usr/bin/env python3
# =============================================================================
# Project : ICE Transducer Temperature Monitor
# Version : 1.3.7
# Modified: 2026-06-10
# Notes   : v1.3.7 - Per-run output folder: every test creates
#           run_<stamp>_<label> under the configurable "Output folder"
#           (new Test-setup field with Browse...) and writes CSV, report
#           TXT/PDF and plot PNG into it. "Save report" now opens a
#           folder-picker dialog (starting at the default output folder)
#           to choose where the re-saved files go.
#           (Older notes: see CHANGELOG.md; Notes holds only the latest.)
# =============================================================================
"""ICE Transducer Temperature Monitor.

Acquires temperatures from two thermocouple probes (T2, T3) connected to
channels 2 and 3 of a Keithley DMM6500 (rear-panel scanner card, USB/VISA)
and evaluates them against IEC 60601-2-37:2024 clause 201.11 limits for an
INVASIVE TRANSDUCER ASSEMBLY (intracardiac echo catheter). One channel is the
probe on the transducer surface (device under test), the other is an ambient
reference; the operator selects which is which in the GUI.

Test modes (see doc/IEC_60601-2-37_Requirements_Summary.md):
  - Simulated use a) peak temperature:  surface temperature <= 43 C
  - Simulated use b) temperature rise:  rise + thermal offset <= 6 C
  - Still air:                          rise + thermal offset <= 27 C

Thermal steady state: rate of change < 0.12 C/min for 3 consecutive minutes.
Test duration: 30 min or until thermal steady state (201.11.1.3.103).

Run:  python temp_monitor_gui.py
"""

import csv
import math
import os
import queue
import random
import re
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

APP_VERSION = "1.3.7"             # bumped on every update (see CHANGELOG.md)

CHANNELS = (2, 3)                 # DMM6500 scanner-card channels (T2, T3)
DEFAULT_AMBIENT_CH = 3            # default ambient-reference channel
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

# Demo mode: a simulated DMM6500 selectable from the instrument list.
DEMO_RESOURCE = "DEMO"
DEMO_LABEL = "Simulated DMM6500  |  demo, no hardware"
DEMO_TIME_SCALE = 60.0            # 1 real second = 60 simulated seconds

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

# Ultrasound console operating settings (201.11.1.3.102) for console SW
# V1.0.0.105919; presets from doc/Acoustic Safety Test Parameters.xlsx,
# sheet 'Acoustic Test V1.0.0.105919'.
CONSOLE_SW_DEFAULT = "V1.0.0.105919"
CONSOLE_MODES = ("B", "B+C", "B+CW", "B+PW", "B+C+PW", "B+C+CW")
B_OPTS = ("PEN", "GEN", "GRES", "RES", "HPEN", "HRES")
C_OPTS = ("PEN", "GEN")
# Transmit frequency is fixed per Opt (column F of the parameter table).
B_FREQ_MHZ = {"PEN": "4.5", "GEN": "6.5", "GRES": "6.5", "RES": "8",
              "HPEN": "8", "HRES": "9"}
C_FREQ_MHZ = {"PEN": "4.5", "GEN": "4.8"}
C_ROI_PRESETS_CM = ("0-1", "0-15")    # C-mode region of interest
DEPTH_MIN_CM = 3.0
DEPTH_MAX_CM = 15.0
FOV_PRESETS_DEG = ("90", "100", "115", "120")
MAX_FOCUS_NUM = 4

# Frame rate / PRF presets (image depth 15 cm). Combinations missing from the
# parameter table leave the fields empty for manual entry.
# B mode, single focus: (b_opt, fov) -> (frame_rate_Hz, prf_Hz)
B_FRAME_PRF = {
    ("PEN", "90"): ("35.14", "4182"),
    ("GEN", "90"): ("35.14", "4182"),
    ("GRES", "90"): ("35.14", "4182"),
    ("RES", "90"): ("31.21", "4182"),
    ("HPEN", "90"): ("15.15", "4182"),
    ("HRES", "90"): ("15.15", "4182"),
    ("PEN", "100"): ("31.68", "4182"),
    ("GEN", "100"): ("31.68", "4182"),
    ("GRES", "100"): ("31.68", "4182"),
    ("RES", "100"): ("28.26", "4182"),
    ("HPEN", "100"): ("13.76", "4182"),
    ("HRES", "100"): ("13.76", "4182"),
    ("PEN", "115"): ("27.7", "4182"),
    ("GEN", "115"): ("27.7", "4182"),
    ("GRES", "115"): ("27.7", "4182"),
    ("RES", "115"): ("24.6", "4182"),
    ("HPEN", "115"): ("12.02", "4182"),
    ("HRES", "115"): ("12.02", "4182"),
    ("PEN", "120"): ("26.64", "4182"),
    ("GEN", "120"): ("26.64", "4182"),
    ("GRES", "120"): ("26.64", "4182"),
    ("RES", "120"): ("23.76", "4182"),
    ("HPEN", "120"): ("11.62", "4182"),
    ("HRES", "120"): ("11.62", "4182"),
}
# B mode PEN @ FOV 90 with multiple foci: focus_num -> (frame_rate, prf)
B_MULTIFOCUS_FRAME_PRF = {
    ("PEN", "90", "2"): ("17.57", "4182"),
    ("PEN", "90", "3"): ("11.71", "4182"),
    ("PEN", "90", "4"): ("8.786", "4182"),
}
# B+C: (c_opt, fov) -> (frame_rate, prf); table only covers FOV 90 and 100.
BC_FRAME_PRF = {
    ("PEN", "90"): ("14.6", "10000"),
    ("GEN", "90"): ("14.6", "10000"),
    ("PEN", "100"): ("14.6", "10000"),
    ("GEN", "100"): ("14.6", "10000"),
}


def mode_tokens(mode):
    """'B+C+PW' -> ['B', 'C', 'PW']."""
    return [t for t in mode.split("+") if t]


def auto_tx_params(mode, b_opt, c_opt, fov, focus_num, depth):
    """Derive the fixed/auto transmit parameters for a mode selection.

    Returns {'f_mhz', 'pulses', 'frame_rate', 'prf'} as strings; empty when
    the combination is not covered by the parameter table.
      - F is fixed per Opt (C frequency when a C mode is active, as in the
        table's combined-mode rows).
      - Pulses#: B non-harmonic = 2, harmonic (H*) = 1; modes with C = 4.
      - Frame rate / PRF only auto-fill at 15 cm depth, where the table has
        measured values.
    """
    toks = mode_tokens(mode)
    out = {"f_mhz": "", "pulses": "", "frame_rate": "", "prf": ""}
    if "C" in toks:
        out["f_mhz"] = C_FREQ_MHZ.get(c_opt, "")
        out["pulses"] = "4"
    elif "B" in toks:
        out["f_mhz"] = B_FREQ_MHZ.get(b_opt, "")
        out["pulses"] = "1" if b_opt.startswith("H") else "2"
    fr_prf = None
    if depth == "15":
        if mode == "B":
            if focus_num == "1":
                fr_prf = B_FRAME_PRF.get((b_opt, fov))
            else:
                fr_prf = B_MULTIFOCUS_FRAME_PRF.get((b_opt, fov, focus_num))
        elif mode == "B+C":
            fr_prf = BC_FRAME_PRF.get((c_opt, fov))
    if fr_prf:
        out["frame_rate"], out["prf"] = fr_prf
    return out


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


def build_test_label(params):
    """Build a compact, filename-safe label from the operating settings.

    Example: {'mode': 'B', 'opt': 'PEN', 'depth': '15', 'fov': '90',
              'focus_num': '1', 'focus_area': '1cm'} -> 'B-PEN-D15-FOV90-FN1-1cm'
    """
    parts = []
    if params.get("mode"):
        parts.append(params["mode"])
    if params.get("opt"):
        parts.append(params["opt"].replace("(", "").replace(")", ""))
    if params.get("c_roi"):
        parts.append(f"CROI{params['c_roi']}")
    if params.get("depth"):
        parts.append(f"D{params['depth']}")
    if params.get("fov"):
        parts.append(f"FOV{params['fov']}")
    if params.get("focus_num"):
        parts.append(f"FN{params['focus_num']}")
    if params.get("focus_area"):
        parts.append(params["focus_area"])
    label = "-".join(parts)
    return re.sub(r"[^A-Za-z0-9.+-]+", "-", label).strip("-")


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

    MODEL_KEYWORD = "DMM6500"

    def __init__(self, resource_name, tc_type=DEFAULT_TC_TYPE, channels=CHANNELS):
        self.resource_name = resource_name
        self.tc_type = tc_type
        self.channels = channels
        self.inst = None
        self.idn = ""

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
    """Demo instrument: no hardware, accelerated clock (x60).

    The probe channel follows an exponential heating curve (37 C -> ~41.6 C,
    tau 300 s) and the ambient channel stays near 23 C, so a full simulated
    run reaches thermal steady state and PASSes every test mode. With the
    x60 clock a 30-minute test completes in about 30 s of wall time. The
    *IDN? string clearly marks the run as SIMULATED in the report.
    """

    def __init__(self, resource_name=DEMO_RESOURCE, tc_type=DEFAULT_TC_TYPE,
                 channels=CHANNELS):
        self.resource_name = resource_name
        self.tc_type = tc_type
        self.channels = channels
        self.time_scale = DEMO_TIME_SCALE
        self.idn = (f"SIMULATED,DMM6500-DEMO,0,"
                    f"x{DEMO_TIME_SCALE:g}-clock (no hardware)")
        self.t0 = None
        self.params = {}              # {channel: (base_C, rise_C, tau_s)}

    def connect(self):
        self.start_heating(probe_ch=min(self.channels))
        return self.idn

    def start_heating(self, probe_ch):
        """(Re)start the heating curves with `probe_ch` as the hot channel."""
        for c in self.channels:
            if c == probe_ch:
                self.params[c] = (37.0, 4.6, 300.0)    # DUT surface
            else:
                self.params[c] = (23.2, 0.2, 600.0)    # ambient reference
        self.t0 = time.monotonic()

    def read_temps(self):
        elapsed = (time.monotonic() - self.t0) * self.time_scale
        out = {}
        for c in self.channels:
            base, rise, tau = self.params[c]
            out[c] = (base + rise * (1.0 - math.exp(-elapsed / tau))
                      + random.gauss(0.0, 0.01))
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
        self.title(f"ICE Transducer Temperature Monitor V{APP_VERSION} "
                   "- DMM6500 - IEC 60601-2-37:2024")
        self.geometry("1280x840")
        self.minsize(1100, 720)

        self.dmm = None
        self.acq_thread = None
        self.acq_stop = threading.Event()
        self.data_queue = queue.Queue()

        self.running = False
        self.monitoring = False
        self.last_monitor_temps = None
        self.probe_ch = 2
        self.ambient_ch = DEFAULT_AMBIENT_CH
        self.test_start_wall = None
        self.test_start_mono = None
        self.baseline = {}
        self.max_temp = {}
        self.min_temp = {}
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
        self.test_label = ""

        self._build_ui()
        self._apply_channel_roles()
        self.after(self.POLL_MS, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------ channel roles

    def _ch_role(self, c):
        return "ambient" if c == self.ambient_ch else "probe"

    def _ch_label(self, c):
        return f"T{c} {self._ch_role(c)}"

    def _on_ambient_change(self, _event=None):
        if self.running:
            return
        sel = self.ambient_combo.get()
        self.ambient_ch = 2 if "2" in sel else 3
        self.probe_ch = 3 if self.ambient_ch == 2 else 2
        self._apply_channel_roles()

    def _apply_channel_roles(self):
        """Refresh labels and plot colors after the ambient selection changes."""
        colors = {self.probe_ch: "tab:red", self.ambient_ch: "tab:green"}
        for c in CHANNELS:
            self.readout_boxes[c].configure(
                text=f"{self._ch_label(c)}  (channel {c})")
            self.lines[c].set_color(colors[c])
            self.lines[c].set_label(self._ch_label(c))
        self._update_limit_lines()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)

        self._build_connection_panel(root)

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, pady=(6, 0))
        left = ttk.Frame(body, width=400)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)

        self.config_book = ttk.Notebook(left)
        self.config_book.pack(fill="x")
        setup_tab = ttk.Frame(self.config_book, padding=6)
        tx_tab = ttk.Frame(self.config_book, padding=6)
        self.config_book.add(setup_tab, text="Test setup")
        self.config_book.add(tx_tab, text="Transmit params")
        self._build_config_panel(setup_tab)
        self._build_transmit_panel(tx_tab)

        self._build_control_panel(left)
        self._build_verdict_panel(left)
        self._build_readout_panel(right)
        self._build_plot(right)

    def _build_connection_panel(self, parent):
        frm = ttk.LabelFrame(parent, text="Instrument connection", padding=6)
        frm.pack(fill="x")

        ttk.Label(frm, text="VISA resource:").pack(side="left")
        self.resource_var = tk.StringVar()
        self.resource_combo = ttk.Combobox(frm, textvariable=self.resource_var,
                                           width=48)
        self.resource_combo.pack(side="left", padx=4)
        ttk.Button(frm, text="Refresh", command=self._refresh_resources).pack(side="left")
        self.connect_btn = ttk.Button(frm, text="Connect", command=self._connect)
        self.connect_btn.pack(side="left", padx=4)

        self.conn_status = ttk.Label(frm, text="Not connected", foreground="gray")
        self.conn_status.pack(side="left", padx=8)

    def _build_config_panel(self, parent):
        self.mode_var = tk.StringVar(value="peak")
        for key in ("peak", "rise6", "rise27"):
            m = TEST_MODES[key]
            ttk.Radiobutton(
                parent, value=key, variable=self.mode_var,
                text=f"{m['name']}\n    {m['clause']}: {m['criterion']}",
                command=self._on_mode_change,
            ).pack(anchor="w", pady=2)

        grid = ttk.Frame(parent)
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
                     width=6, state="readonly").grid(row=4, column=1, sticky="w",
                                                     padx=4)

        ttk.Label(grid, text="Ambient ref. channel").grid(row=5, column=0,
                                                          sticky="w")
        self.ambient_combo = ttk.Combobox(
            grid, values=("Channel 3 (T3)", "Channel 2 (T2)"), width=14,
            state="readonly")
        self.ambient_combo.set("Channel 3 (T3)" if DEFAULT_AMBIENT_CH == 3
                               else "Channel 2 (T2)")
        self.ambient_combo.grid(row=5, column=1, columnspan=2, sticky="w", padx=4)
        self.ambient_combo.bind("<<ComboboxSelected>>", self._on_ambient_change)

        self.autostop_steady_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Auto-stop when the probe reaches thermal "
                                     "steady state\n(< 0.12 C/min for 3 min)",
                        variable=self.autostop_steady_var).pack(anchor="w",
                                                                pady=(6, 0))

        meta = ttk.Frame(parent)
        meta.pack(fill="x", pady=(6, 0))
        ttk.Label(meta, text="Operator").grid(row=0, column=0, sticky="w")
        self.operator_var = tk.StringVar()
        ttk.Entry(meta, textvariable=self.operator_var, width=20).grid(
            row=0, column=1, sticky="w", padx=4)
        ttk.Label(meta, text="Catheter / DUT ID").grid(row=1, column=0, sticky="w")
        self.dut_var = tk.StringVar()
        ttk.Entry(meta, textvariable=self.dut_var, width=20).grid(
            row=1, column=1, sticky="w", padx=4)
        # Operator fields required by the standard; may be filled after the
        # run and saved into the report with the "Save report" button.
        ttk.Label(meta, text="Meas. uncertainty").grid(row=2, column=0,
                                                       sticky="w")
        self.uncert_var = tk.StringVar()
        ttk.Entry(meta, textvariable=self.uncert_var, width=20).grid(
            row=2, column=1, sticky="w", padx=4)
        ttk.Label(meta, text="C  (201.11.1.3.104)").grid(row=2, column=2,
                                                         sticky="w")
        ttk.Label(meta, text="DUT temp before contact").grid(row=3, column=0,
                                                             sticky="w")
        self.precontact_var = tk.StringVar()
        ttk.Entry(meta, textvariable=self.precontact_var, width=20).grid(
            row=3, column=1, sticky="w", padx=4)
        ttk.Label(meta, text="C  (>= 37, method a)").grid(row=3, column=2,
                                                          sticky="w")
        # Default base folder for the outputs; every run creates its own
        # run_<stamp>_<label> subfolder in it.
        ttk.Label(meta, text="Output folder").grid(row=4, column=0, sticky="w")
        self.outdir_var = tk.StringVar(value=OUTPUT_DIR)
        ttk.Entry(meta, textvariable=self.outdir_var, width=20).grid(
            row=4, column=1, sticky="w", padx=4)
        ttk.Button(meta, text="Browse...", command=self._browse_outdir).grid(
            row=4, column=2, sticky="w")

    def _browse_outdir(self):
        d = filedialog.askdirectory(
            title="Default output folder",
            initialdir=self.outdir_var.get().strip() or OUTPUT_DIR)
        if d:
            self.outdir_var.set(os.path.normpath(d))

    def _build_transmit_panel(self, parent):
        ttk.Label(parent,
                  text="Ultrasound console operating settings "
                       "(201.11.1.3.102).\nPresets: Acoustic Test "
                       f"{CONSOLE_SW_DEFAULT}. Recorded in the report,\n"
                       "the CSV header and the output file names.",
                  foreground="gray").pack(anchor="w", pady=(0, 6))

        grid = ttk.Frame(parent)
        grid.pack(fill="x")
        self.tx_vars = {}
        self._tx_rows = {}            # key -> [widgets] for show/hide

        def combo_row(r, label, key, values, default="", width=16,
                      command=None):
            lab = ttk.Label(grid, text=label)
            lab.grid(row=r, column=0, sticky="w", pady=1)
            var = tk.StringVar(value=default)
            cb = ttk.Combobox(grid, textvariable=var, values=values,
                              width=width, state="readonly")
            cb.grid(row=r, column=1, sticky="w", padx=4, pady=1)
            if command:
                cb.bind("<<ComboboxSelected>>", command)
            self.tx_vars[key] = var
            self._tx_rows[key] = [lab, cb]
            return cb

        def entry_row(r, label, key, default="", width=18, unit="",
                      readonly=False):
            lab = ttk.Label(grid, text=label)
            lab.grid(row=r, column=0, sticky="w", pady=1)
            var = tk.StringVar(value=default)
            ent = ttk.Entry(grid, textvariable=var, width=width,
                            state="readonly" if readonly else "normal")
            ent.grid(row=r, column=1, sticky="w", padx=4, pady=1)
            widgets = [lab, ent]
            if unit:
                u = ttk.Label(grid, text=unit)
                u.grid(row=r, column=2, sticky="w")
                widgets.append(u)
            self.tx_vars[key] = var
            self._tx_rows[key] = widgets

        entry_row(0, "Console SW version", "console_sw",
                  default=CONSOLE_SW_DEFAULT, width=18)
        combo_row(1, "Mode", "mode", CONSOLE_MODES, default="B",
                  command=self._on_console_mode_change)
        combo_row(2, "B Opt (image preset)", "b_opt", B_OPTS, default="PEN")
        combo_row(3, "C Opt", "c_opt", C_OPTS, default="PEN")
        combo_row(4, "C ROI (cm)", "c_roi", C_ROI_PRESETS_CM, default="0-1",
                  width=8)

        lab = ttk.Label(grid, text="Image depth (cm)")
        lab.grid(row=5, column=0, sticky="w", pady=1)
        self.tx_vars["depth"] = tk.StringVar(value="15")
        depth_spin = ttk.Spinbox(grid, textvariable=self.tx_vars["depth"],
                                 from_=DEPTH_MIN_CM, to=DEPTH_MAX_CM,
                                 increment=1, width=7)
        depth_spin.grid(row=5, column=1, sticky="w", padx=4, pady=1)
        ttk.Label(grid, text=f"({DEPTH_MIN_CM:g}-{DEPTH_MAX_CM:g})").grid(
            row=5, column=2, sticky="w")
        self._tx_rows["depth"] = [lab, depth_spin]

        combo_row(6, "FOV (deg)", "fov", FOV_PRESETS_DEG, default="90",
                  width=8)
        combo_row(7, "Focus number", "focus_num",
                  tuple(str(n) for n in range(1, MAX_FOCUS_NUM + 1)),
                  default="1", width=8, command=self._on_focus_num_change)

        # One position entry per focus; entries beyond the selected focus
        # number are hidden.
        lab = ttk.Label(grid, text="Focus pos. (cm)")
        lab.grid(row=8, column=0, sticky="w", pady=1)
        focus_frm = ttk.Frame(grid)
        focus_frm.grid(row=8, column=1, columnspan=2, sticky="w", padx=4)
        self._focus_entries = []
        for i in range(MAX_FOCUS_NUM):
            var = tk.StringVar(value=str(i + 1))
            ent = ttk.Entry(focus_frm, textvariable=var, width=5)
            ent.grid(row=0, column=i, padx=(0, 3))
            self._focus_entries.append((ent, var))
            var.trace_add("write", lambda *_: self._update_label_preview())

        entry_row(9, "Line density", "line_density", default="UH", width=8)
        entry_row(10, "F (MHz)", "f_mhz", width=8, unit="(fixed per Opt)",
                  readonly=True)
        entry_row(11, "Pulses #", "pulses", width=8, unit="(fixed per mode)",
                  readonly=True)
        entry_row(12, "Frame rate (Hz)", "frame_rate", width=8,
                  unit="(auto if tabulated)")
        entry_row(13, "PRF (Hz)", "prf", width=8, unit="(auto if tabulated)")

        self.tx_label_preview = ttk.Label(parent, text="", foreground="gray")
        self.tx_label_preview.pack(anchor="w", pady=(6, 0))
        for var in self.tx_vars.values():
            var.trace_add("write", lambda *_: self._update_label_preview())
        for key in ("mode", "b_opt", "c_opt", "fov", "focus_num", "depth"):
            self.tx_vars[key].trace_add("write",
                                        lambda *_: self._update_tx_auto())
        self._on_console_mode_change()
        self._on_focus_num_change()

    def _set_tx_row_visible(self, key, visible):
        for w in self._tx_rows[key]:
            if visible:
                w.grid()
            else:
                w.grid_remove()

    def _on_console_mode_change(self, _event=None):
        toks = mode_tokens(self.tx_vars["mode"].get())
        self._set_tx_row_visible("b_opt", "B" in toks)
        self._set_tx_row_visible("c_opt", "C" in toks)
        self._set_tx_row_visible("c_roi", "C" in toks)
        self._update_tx_auto()

    def _on_focus_num_change(self, _event=None):
        try:
            n = int(self.tx_vars["focus_num"].get())
        except ValueError:
            n = 1
        for i, (ent, _var) in enumerate(self._focus_entries):
            if i < n:
                ent.grid()
            else:
                ent.grid_remove()
        self._update_label_preview()

    def _update_tx_auto(self):
        """Auto-fill F, pulses#, frame rate and PRF from the selection."""
        auto = auto_tx_params(
            self.tx_vars["mode"].get(), self.tx_vars["b_opt"].get(),
            self.tx_vars["c_opt"].get(), self.tx_vars["fov"].get(),
            self.tx_vars["focus_num"].get(),
            self.tx_vars["depth"].get().strip())
        for key in ("f_mhz", "pulses", "frame_rate", "prf"):
            if self.tx_vars[key].get() != auto[key]:
                self.tx_vars[key].set(auto[key])

    def _collect_tx_params(self):
        params = {k: v.get().strip() for k, v in self.tx_vars.items()}
        toks = mode_tokens(params["mode"])
        has_b, has_c = "B" in toks, "C" in toks
        if has_b and has_c:
            opt = f"{params['c_opt']}(C)+{params['b_opt']}(B)"
        elif has_c:
            opt = params["c_opt"]
        elif has_b:
            opt = params["b_opt"]
        else:
            opt = ""
        params["opt"] = opt
        if not has_c:
            params["c_roi"] = ""
        try:
            n = int(params["focus_num"])
        except ValueError:
            n = 1
        pos = [v.get().strip() for _e, v in self._focus_entries[:n]]
        pos = [p for p in pos if p]
        params["focus_area"] = ",".join(pos) + "cm" if pos else ""
        return params

    def _update_label_preview(self):
        label = build_test_label(self._collect_tx_params())
        self.tx_label_preview.configure(text=f"Test label: {label or '(none)'}")

    def _build_control_panel(self, parent):
        frm = ttk.LabelFrame(parent, text="Run control", padding=6)
        frm.pack(fill="x", pady=(6, 6))

        btns = ttk.Frame(frm)
        btns.pack(fill="x")
        self.start_btn = ttk.Button(btns, text="Start test", command=self.start_test,
                                    state="disabled")
        self.start_btn.pack(side="left", padx=2)
        self.stop_btn = ttk.Button(btns, text="Stop test", command=self.stop_test,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=2)
        self.save_btn = ttk.Button(btns, text="Save report",
                                   command=self.save_report, state="disabled")
        self.save_btn.pack(side="left", padx=2)

        # Live readout without recording, for the pre-run condition checks
        # (test-object temperature before contact, ambient 23 +/- 3 C).
        mon = ttk.Frame(frm)
        mon.pack(fill="x", pady=(4, 0))
        self.monitor_btn = ttk.Button(mon, text="Monitor (no record)",
                                      command=self.toggle_monitor,
                                      state="disabled")
        self.monitor_btn.pack(side="left", padx=2)
        self.capture_btn = ttk.Button(mon, text="-> DUT temp before contact",
                                      command=self._capture_precontact,
                                      state="disabled")
        self.capture_btn.pack(side="left", padx=2)

        self.elapsed_label = ttk.Label(frm, text="Elapsed: 00:00",
                                       font=("Segoe UI", 12, "bold"))
        self.elapsed_label.pack(anchor="w", pady=(6, 0))
        self.status_label = ttk.Label(frm, text="Idle", foreground="gray",
                                      wraplength=360)
        self.status_label.pack(anchor="w")

    def _build_verdict_panel(self, parent):
        frm = ttk.LabelFrame(parent, text="Compliance verdict", padding=6)
        frm.pack(fill="both", expand=True)

        self.verdict_label = tk.Label(frm, text="--", font=("Segoe UI", 28, "bold"),
                                      fg="gray")
        self.verdict_label.pack(pady=(4, 8))

        self.verdict_detail = ttk.Label(frm, text="", justify="left", wraplength=360,
                                        font=("Consolas", 10))
        self.verdict_detail.pack(anchor="w")

    def _build_readout_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill="x")
        self.readouts = {}
        self.readout_boxes = {}
        for c in CHANNELS:
            box = ttk.LabelFrame(frm, text=f"channel {c}", padding=6)
            box.pack(side="left", fill="x", expand=True, padx=(0, 6))
            cur = tk.Label(box, text="--.- C", font=("Segoe UI", 26, "bold"))
            cur.pack()
            sub = ttk.Label(box, text="max --.-   rise --.-   drift --.-",
                            font=("Consolas", 10))
            sub.pack()
            steady = tk.Label(box, text="steady state: --", font=("Segoe UI", 9))
            steady.pack()
            self.readouts[c] = {"cur": cur, "sub": sub, "steady": steady}
            self.readout_boxes[c] = box

    def _build_plot(self, parent):
        self.fig = Figure(figsize=(7, 4.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Elapsed time (min)")
        self.ax.set_ylabel("Temperature (C)")
        self.ax.grid(True, alpha=0.3)
        self.lines = {}
        for c in CHANNELS:
            (line,) = self.ax.plot([], [], label=f"T{c}")
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
        self.resource_map[DEMO_LABEL] = DEMO_RESOURCE
        self.resource_combo["values"] = labels + [DEMO_LABEL]
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
            self.resource_var.set(DEMO_LABEL)
            self.conn_status.configure(
                text="No VISA instruments found - simulated demo selected",
                foreground="gray")

    def _connect(self):
        if self.dmm is not None:
            self._disconnect()
            return
        sel = self.resource_var.get().strip()
        if not sel:
            messagebox.showwarning("No resource",
                                   "Click Refresh and select the DMM6500.")
            return
        # Map the friendly "model | resource" label back to the VISA address;
        # raw addresses typed by the user pass through as-is.
        res = getattr(self, "resource_map", {}).get(sel, sel)
        try:
            if res == DEMO_RESOURCE:
                dmm = SimulatedDmm(tc_type=self.tc_var.get())
            else:
                dmm = Dmm6500(res, tc_type=self.tc_var.get())
            idn = dmm.connect()
        except Exception as exc:
            messagebox.showerror("Connection failed", str(exc))
            return
        self.dmm = dmm
        self.conn_status.configure(
            text=idn[:60],
            foreground="orange" if res == DEMO_RESOURCE else "green")
        self.connect_btn.configure(text="Disconnect")
        self.start_btn.configure(state="normal")
        self.monitor_btn.configure(state="normal")
        self.status_label.configure(text="Connected. Configure the test and press "
                                         "Start.", foreground="black")

    def _disconnect(self):
        if self.running:
            self.stop_test()
        self.stop_monitor()
        if self.dmm is not None:
            self.dmm.close()
            self.dmm = None
        self.conn_status.configure(text="Not connected", foreground="gray")
        self.connect_btn.configure(text="Connect")
        self.start_btn.configure(state="disabled")
        self.monitor_btn.configure(state="disabled")

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
        self.stop_monitor()
        try:
            self.cfg_offset, self.cfg_interval, self.cfg_duration, self.cfg_ambient = \
                self._read_config()
        except ValueError as exc:
            messagebox.showerror("Invalid configuration", str(exc))
            return
        self._on_ambient_change()             # lock in the channel roles
        self.tx_params = self._collect_tx_params()
        depth_txt = self.tx_params.get("depth", "")
        try:
            depth_ok = DEPTH_MIN_CM <= float(depth_txt) <= DEPTH_MAX_CM
        except ValueError:
            depth_ok = False
        if not depth_ok:
            messagebox.showerror(
                "Invalid configuration",
                f"Image depth must be {DEPTH_MIN_CM:g}-{DEPTH_MAX_CM:g} cm "
                f"(entered: {depth_txt or '(empty)'}).")
            return
        self.test_label = build_test_label(self.tx_params)

        try:
            # Use the operator-entered ambient temperature as the simulated
            # cold-junction temperature (2000-SCAN card has no CJC sensor).
            if isinstance(self.dmm, Dmm6500):
                self.dmm.set_sim_ref_junction(self.cfg_ambient)
            elif isinstance(self.dmm, SimulatedDmm):
                self.dmm.start_heating(self.probe_ch)
            first = self.dmm.read_temps()
        except Exception as exc:
            messagebox.showerror("Read failed", f"Could not read instrument:\n{exc}")
            return

        # time_scale is 1.0 for the real instrument; the automated self-test
        # injects a stub with an accelerated clock.
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

        stamp = self.test_start_wall.strftime("%Y%m%d_%H%M%S")
        suffix = f"_{self.test_label}" if self.test_label else ""
        # One folder per run (under the GUI's output folder) holds the CSV,
        # the report TXT/PDF and the plot PNG.
        base = self.outdir_var.get().strip() or OUTPUT_DIR
        self.run_dir = os.path.join(base, f"run_{stamp}{suffix}")
        try:
            os.makedirs(self.run_dir, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(
                "Invalid output folder",
                f"Cannot create the run folder:\n{self.run_dir}\n\n{exc}")
            return
        self.csv_path = os.path.join(self.run_dir, f"templog_{stamp}{suffix}.csv")
        self.csv_file = open(self.csv_path, "w", newline="", encoding="utf-8")
        self.csv_file.write(self._csv_metadata())
        self.csv_writer = csv.writer(self.csv_file)
        p, a = self.probe_ch, self.ambient_ch
        self.csv_writer.writerow(
            ["timestamp", "elapsed_s",
             f"T{p}_probe_C (ch{p})", f"T{a}_ambient_C (ch{a})"])
        self.csv_writer.writerow([self.test_start_wall.isoformat(timespec="seconds"),
                                  "0.0", f"{first[p]:.3f}", f"{first[a]:.3f}"])

        # Fresh stop event per thread: a previous (monitor) thread that is
        # still finishing its last read keeps its own, already-set event.
        while not self.data_queue.empty():
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                break
        self.acq_stop = threading.Event()
        self.acq_thread = threading.Thread(
            target=self._acquire_loop, args=(self.acq_stop,), daemon=True)
        self.acq_thread.start()

        self.running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.save_btn.configure(state="disabled")
        self.monitor_btn.configure(state="disabled")
        self.ambient_combo.configure(state="disabled")
        mode = TEST_MODES[self.mode_var.get()]
        self.status_label.configure(
            text=f"Running: {mode['name']} ({mode['clause']}). "
                 f"Label {self.test_label or '(none)'}. Baseline "
                 f"T{p}={first[p]:.2f} C, T{a}={first[a]:.2f} C.",
            foreground="black")
        self._update_limit_lines()
        self._set_verdict("IN PROGRESS", "gray")

    def _csv_metadata(self):
        """'#'-prefixed metadata lines written before the CSV header row."""
        tx = getattr(self, "tx_params", {})
        items = [
            ("program", f"temp_monitor_gui.py V{APP_VERSION}"),
            ("test_mode", TEST_MODES[self.mode_var.get()]["name"]),
            ("test_label", self.test_label),
            ("operator", self.operator_var.get()),
            ("catheter_id", self.dut_var.get()),
            ("measurement_uncertainty_C", self.uncert_var.get().strip()),
            ("dut_temp_before_contact_C", self.precontact_var.get().strip()),
            ("probe_channel", str(self.probe_ch)),
            ("ambient_channel", str(self.ambient_ch)),
            ("thermal_offset_C", f"{self.cfg_offset:g}"),
            ("ambient_entered_C", f"{self.cfg_ambient:g}"),
            ("console_sw", tx.get("console_sw", "")),
            ("console_mode", tx.get("mode", "")),
            ("opt", tx.get("opt", "")),
            ("c_roi_cm", tx.get("c_roi", "")),
            ("image_depth_cm", tx.get("depth", "")),
            ("fov_deg", tx.get("fov", "")),
            ("focus_number", tx.get("focus_num", "")),
            ("focus_area", tx.get("focus_area", "")),
            ("line_density", tx.get("line_density", "")),
            ("f_mhz", tx.get("f_mhz", "")),
            ("pulses", tx.get("pulses", "")),
            ("frame_rate_hz", tx.get("frame_rate", "")),
            ("prf_hz", tx.get("prf", "")),
        ]
        return "".join(f"# {k}: {v}\n" for k, v in items)

    def _update_limit_lines(self):
        mode = TEST_MODES[self.mode_var.get()]
        if mode["kind"] == "absolute":
            limit_y = mode["limit"]
            self.warn_line.set_visible(True)
        else:
            base = self.baseline.get(self.probe_ch, 37.0)
            limit_y = base + mode["limit"] - getattr(self, "cfg_offset", 0.0)
            self.warn_line.set_visible(False)
        self.limit_line.set_ydata([limit_y, limit_y])
        self.limit_line.set_label(f"Limit ({limit_y:.1f} C)\n"
                                  f"IEC 60601-2-37 {mode['clause']}")
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
        self.monitor_btn.configure(state="normal" if self.dmm else "disabled")
        self.ambient_combo.configure(state="readonly")
        self._finalize_test()

    # ------------------------------------------------------ live monitor

    def toggle_monitor(self):
        if self.monitoring:
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        """Live readout without recording: no CSV, no statistics, no report.

        Pre-run condition check, in particular the test-object temperature
        before contact (>= 37 C for method a, 201.11.1.3.101.1) and the
        23 +/- 3 C ambient.
        """
        if self.dmm is None or self.running or self.monitoring:
            return
        try:
            self.cfg_interval = max(0.2, float(self.interval_var.get()))
        except ValueError:
            self.cfg_interval = DEFAULT_INTERVAL_S
        self._on_ambient_change()             # lock in the channel roles
        try:
            if isinstance(self.dmm, Dmm6500):
                try:
                    amb = float(self.ambient_var.get())
                except ValueError:
                    amb = 23.0
                self.dmm.set_sim_ref_junction(amb)
            elif isinstance(self.dmm, SimulatedDmm):
                self.dmm.start_heating(self.probe_ch)
        except Exception as exc:
            messagebox.showerror("Monitor failed", str(exc))
            return
        self.monitoring = True
        self.last_monitor_temps = None
        self.acq_stop = threading.Event()
        self.acq_thread = threading.Thread(
            target=self._acquire_loop, args=(self.acq_stop,), daemon=True)
        self.acq_thread.start()
        self.monitor_btn.configure(text="Stop monitor")
        self.capture_btn.configure(state="normal")
        self.status_label.configure(
            text="Monitoring - live readout only, nothing is recorded.",
            foreground="black")

    def stop_monitor(self):
        if not self.monitoring:
            return
        self.monitoring = False
        self.acq_stop.set()
        self.monitor_btn.configure(text="Monitor (no record)")
        self.capture_btn.configure(state="disabled")
        self.status_label.configure(text="Monitor stopped.", foreground="gray")

    def _capture_precontact(self):
        """Copy the probe's live reading into 'DUT temp before contact'."""
        if not self.monitoring or not self.last_monitor_temps:
            return
        v = self.last_monitor_temps[self.probe_ch]
        self.precontact_var.set(f"{v:.2f}")
        self.status_label.configure(
            text=f"DUT temp before contact set to {v:.2f} C "
                 f"(T{self.probe_ch} probe).", foreground="black")

    def _handle_monitor_sample(self, temps):
        self.last_monitor_temps = temps
        for c in CHANNELS:
            r = self.readouts[c]
            v = temps[c]
            r["sub"].configure(text="live monitor - not recorded")
            if c == self.probe_ch:
                ok37 = v >= 37.0
                r["cur"].configure(text=f"{v:.2f} C", fg="black")
                r["steady"].configure(
                    text=f"pre-contact >= 37 C: {'yes' if ok37 else 'not yet'}",
                    fg="green" if ok37 else "gray")
            else:
                in_range = AMBIENT_MIN_C <= v <= AMBIENT_MAX_C
                r["cur"].configure(text=f"{v:.2f} C",
                                   fg="black" if in_range else "orange")
                r["steady"].configure(
                    text=f"23 +/- 3 C: {'OK' if in_range else 'OUT OF RANGE'}",
                    fg="green" if in_range else "orange")

    # ------------------------------------------------------ acquisition

    def _acquire_loop(self, stop_evt):
        interval = self.cfg_interval
        next_t = time.monotonic()
        while not stop_evt.is_set():
            try:
                temps = self.dmm.read_temps()
                self.data_queue.put(("data", time.monotonic(), temps))
            except Exception as exc:
                self.data_queue.put(("error", time.monotonic(), str(exc)))
                return
            next_t += interval
            delay = next_t - time.monotonic()
            if delay > 0:
                if stop_evt.wait(delay):
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
                    elif self.monitoring:
                        self.stop_monitor()
                        messagebox.showerror("Instrument error", payload)
                elif kind == "data" and self.running:
                    self._handle_sample(t_mono, payload)
                elif kind == "data" and self.monitoring:
                    self._handle_monitor_sample(payload)
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
            self.csv_writer.writerow(
                [datetime.now().isoformat(timespec="seconds"), f"{elapsed:.1f}",
                 f"{temps[self.probe_ch]:.3f}", f"{temps[self.ambient_ch]:.3f}"])
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
              and self.detectors[self.probe_ch].steady):
            self.stop_test(reason=f"Thermal steady state reached on T{self.probe_ch} "
                                  "probe (< 0.12 C/min for 3 min, 201.11.1.3.101)")

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
            if c == self.probe_ch:
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
                in_range = AMBIENT_MIN_C <= cur <= AMBIENT_MAX_C
                r["cur"].configure(fg="black" if in_range else "orange")
                r["steady"].configure(
                    text=f"23 +/- 3 C: {'OK' if in_range else 'OUT OF RANGE'}   "
                         f"drift {drift:.2f} C",
                    fg="green" if in_range and drift <= AMBIENT_STABLE_BAND_C
                    else "orange")

    def _update_verdict_live(self):
        mode_key = self.mode_var.get()
        p, a = self.probe_ch, self.ambient_ch
        value, limit, ok = evaluate_channel(
            mode_key, self.max_temp[p], self.baseline[p], self.cfg_offset)
        kind = TEST_MODES[mode_key]["kind"]
        what = "max temp" if kind == "absolute" else "rise+offset"
        amb = self.current[a]
        amb_drift = self.max_temp[a] - self.min_temp[a]
        amb_ok = AMBIENT_MIN_C <= amb <= AMBIENT_MAX_C
        probe_drift = self.max_temp[p] - self.min_temp[p]
        lines = [
            f"T{p} probe: {what} = {value:6.2f} C "
            f"(limit {limit:.1f} C)  {'OK' if ok else 'EXCEEDED'}, "
            f"drift {probe_drift:.2f} C",
            f"T{a} ambient: {amb:.2f} C "
            f"({'within' if amb_ok else 'OUTSIDE'} 23 +/- 3 C), "
            f"drift {amb_drift:.2f} C",
        ]
        self.verdict_detail.configure(text="\n".join(lines))
        if not ok:
            self.fail_latched = True
        if self.fail_latched:
            self._set_verdict("FAIL", "red")
        elif self.current[p] >= WARNING_TEMP_C and mode_key == "peak":
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
        self._update_plot()
        verdict, paths = self._save_outputs()
        self.save_btn.configure(state="normal")
        self.status_label.configure(text=f"Test ended: {self.stop_reason}",
                                    foreground="black")
        messagebox.showinfo(
            "Test finished",
            f"Verdict: {verdict}\nReason: {self.stop_reason}\n\n"
            f"Data:   {self.csv_path}\nReport: {paths['txt']}\n"
            f"PDF:    {paths['pdf']}\nPlot:   {paths['png']}")

    def save_report(self):
        """Save the report again with the current UI fields (Save button).

        A folder-picker dialog (starting at the GUI's default output folder)
        chooses where the report TXT/PDF and plot PNG are written.
        """
        if self.running or not self.times or self.test_start_wall is None:
            return
        target = filedialog.askdirectory(
            title="Choose the folder for the report files",
            initialdir=self.outdir_var.get().strip() or OUTPUT_DIR)
        if not target:
            self.status_label.configure(text="Save cancelled.",
                                        foreground="gray")
            return
        verdict, paths = self._save_outputs(out_dir=os.path.normpath(target))
        self.status_label.configure(
            text=f"Report saved ({verdict}): {os.path.basename(paths['txt'])}",
            foreground="black")
        messagebox.showinfo(
            "Report saved",
            f"Verdict: {verdict}\n\nReport: {paths['txt']}\n"
            f"PDF:    {paths['pdf']}\nPlot:   {paths['png']}")

    def _save_outputs(self, out_dir=None):
        """Write the plot PNG, text report and PDF report for the recorded run.

        Files go into `out_dir` (default: the run's own folder, created at
        test start). Metadata that does not affect the recorded data
        (operator, DUT ID, transmit params, thermal offset, ambient) is
        re-read from the UI, so the operator can amend it after the run and
        press "Save report" to save again. Filenames keep the run's start
        timestamp; a changed test label produces new files alongside the
        old ones.
        """
        self.tx_params = self._collect_tx_params()
        self.test_label = build_test_label(self.tx_params)
        try:
            self.cfg_offset = float(self.offset_var.get())
        except ValueError:
            pass
        try:
            self.cfg_ambient = float(self.ambient_var.get())
        except ValueError:
            pass

        mode_key = self.mode_var.get()
        mode = TEST_MODES[mode_key]
        p = self.probe_ch
        value, limit, ok = evaluate_channel(
            mode_key, self.max_temp[p], self.baseline[p], self.cfg_offset)
        verdict = "PASS" if ok else "FAIL"
        completed = (self.detectors[p].steady
                     or (self.times
                         and self.times[-1] >= self.cfg_duration * 60.0 - 1))
        if ok and not completed:
            verdict = "PASS (incomplete test)"
        self._set_verdict(verdict, "green" if ok else "red")

        stamp = self.test_start_wall.strftime("%Y%m%d_%H%M%S")
        suffix = f"_{self.test_label}" if self.test_label else ""
        if out_dir is None:
            out_dir = getattr(self, "run_dir", None) or OUTPUT_DIR
        os.makedirs(out_dir, exist_ok=True)
        png_path = os.path.join(out_dir, f"tempplot_{stamp}{suffix}.png")
        try:
            self.fig.savefig(png_path, dpi=150, bbox_inches="tight")
        except Exception:
            png_path = "(plot save failed)"
        txt_path = os.path.join(out_dir, f"report_{stamp}{suffix}.txt")
        pdf_path = os.path.join(out_dir, f"report_{stamp}{suffix}.pdf")
        text = self._report_text(mode, (value, limit, ok), verdict,
                                 png_path, pdf_path)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        try:
            self._write_pdf_report(pdf_path, text)
        except Exception as exc:
            pdf_path = f"(PDF save failed: {exc})"
        return verdict, {"png": png_path, "txt": txt_path, "pdf": pdf_path}

    def _write_pdf_report(self, path, report_text):
        """Two-page PDF: page 1 the report text, page 2 the temperature plot."""
        with PdfPages(path) as pdf:
            page = Figure(figsize=(8.27, 11.69))      # A4 portrait
            page.text(0.07, 0.97, report_text, family="monospace",
                      fontsize=8, va="top")
            pdf.savefig(page)
            pdf.savefig(self.fig)
            info = pdf.infodict()
            info["Title"] = ("ICE Transducer Surface Temperature Test Report "
                             + (self.test_label or "")).strip()
            info["Author"] = self.operator_var.get() or "(not entered)"

    def _report_text(self, mode, result, verdict, png_path, pdf_path):
        end_wall = datetime.now()
        elapsed = self.times[-1] if self.times else 0.0
        idn = getattr(self.dmm, "idn", "n/a")
        value, limit, ok = result
        p, a = self.probe_ch, self.ambient_ch
        tx = getattr(self, "tx_params", {})
        det = self.detectors[p]
        steady_txt = (f"yes, at {det.steady_at/60.0:.1f} min"
                      if det.steady else "no")
        amb_min, amb_max = self.min_temp[a], self.max_temp[a]
        amb_in_range = (AMBIENT_MIN_C <= amb_min and amb_max <= AMBIENT_MAX_C)
        amb_drift = amb_max - amb_min

        def tx_line(label, key, unit=""):
            val = tx.get(key, "") or "(not entered)"
            return f"    {label:<21}: {val}{unit if tx.get(key) else ''}"

        unc = self.uncert_var.get().strip()
        pre = self.precontact_var.get().strip()
        blank = "________  (fill in the GUI, then press 'Save report')"

        lines = [
            "=" * 72,
            "ICE TRANSDUCER SURFACE TEMPERATURE TEST REPORT",
            "Standard: IEC 60601-2-37:2024, clause 201.11",
            f"Program: temp_monitor_gui.py V{APP_VERSION}",
            "=" * 72,
            f"Test mode        : {mode['name']}",
            f"Clause           : {mode['clause']}",
            f"Criterion        : {mode['criterion']}",
            f"Test label       : {self.test_label or '(none)'}",
            f"Verdict          : {verdict}",
            "-" * 72,
            f"Operator         : {self.operator_var.get() or '(not entered)'}",
            f"Catheter / DUT ID: {self.dut_var.get() or '(not entered)'}",
            f"Instrument       : {idn}",
            f"Thermocouple     : type {self.tc_var.get()}; "
            f"T{p} probe = ch {p} (DUT surface), "
            f"T{a} ambient = ch {a} (reference)",
            f"Start            : {self.test_start_wall.isoformat(timespec='seconds')}",
            f"End              : {end_wall.isoformat(timespec='seconds')}",
            f"Elapsed          : {elapsed/60.0:.1f} min",
            f"Stop reason      : {self.stop_reason}",
            f"Ambient (entered): {self.cfg_ambient:.1f} C "
            f"(required 23 +/- 3 C, 201.11.1.3.101)",
            f"Thermal offset   : {self.cfg_offset:.2f} C (201.3.228)",
            f"Sample interval  : {self.cfg_interval:g} s",
            "-" * 72,
            "Operating settings of the ultrasound console (201.11.1.3.102):",
            tx_line("Console SW version", "console_sw"),
            tx_line("Mode", "mode"),
            tx_line("Opt (image preset)", "opt"),
            # C ROI only exists in modes containing C; omit it elsewhere.
            *([tx_line("C ROI", "c_roi", " cm")] if tx.get("c_roi") else []),
            tx_line("Image depth", "depth", " cm"),
            tx_line("FOV", "fov", " deg"),
            tx_line("Focus number", "focus_num"),
            tx_line("Focus area", "focus_area"),
            tx_line("Line density", "line_density"),
            tx_line("F", "f_mhz", " MHz"),
            tx_line("Pulses #", "pulses"),
            tx_line("Frame rate", "frame_rate", " Hz"),
            tx_line("PRF", "prf", " Hz"),
            "-" * 72,
            f"T{p} probe (channel {p}, device under test):",
            f"    Baseline             : {self.baseline[p]:.2f} C",
            f"    Min / Max            : {self.min_temp[p]:.2f} C / "
            f"{self.max_temp[p]:.2f} C",
            f"    Drift (max-min)      : {self.max_temp[p]-self.min_temp[p]:.2f} C",
            f"    Rise (max-baseline)  : {self.max_temp[p]-self.baseline[p]:.2f} C",
            f"    Evaluated value      : {value:.2f} C  (limit {limit:.1f} C)",
            f"    Result               : {'PASS' if ok else 'FAIL'}",
            f"    Thermal steady state : {steady_txt} "
            "(rate < 0.12 C/min for 3 consecutive minutes)",
            f"T{a} ambient (channel {a}, test condition record):",
            f"    Baseline             : {self.baseline[a]:.2f} C",
            f"    Min / Max            : {amb_min:.2f} C / {amb_max:.2f} C",
            f"    Drift (max-min)      : {amb_drift:.2f} C "
            f"(still-air test requires <= {AMBIENT_STABLE_BAND_C:.1f} C)",
            f"    Within 23 +/- 3 C    : {'yes' if amb_in_range else 'NO'}",
            "-" * 72,
            "OPERATOR-ENTERED FIELDS (required by the standard):",
            f"  Measurement uncertainty (201.11.1.3.104):                   "
            f"{unc + ' C' if unc else blank}",
            f"  Test object temperature before contact (>= 37 C, method a): "
            f"{pre + ' C' if pre else blank}",
            "-" * 72,
            f"Data file : {self.csv_path}",
            f"Plot file : {png_path}",
            f"PDF file  : {pdf_path}",
            "=" * 72,
        ]
        return "\n".join(lines)

    # ------------------------------------------------------ shutdown

    def _on_close(self):
        if self.running:
            if not messagebox.askokcancel("Quit", "A test is running. Stop and quit?"):
                return
            self.stop_test(reason="Application closed")
        self.stop_monitor()
        if self.dmm is not None:
            self.dmm.close()
        self.destroy()


def main():
    app = App()
    app._refresh_resources()
    app.mainloop()


if __name__ == "__main__":
    main()
