"""Diagnostic: find which DMM6500 scanner-card channels have live thermocouples.

Scans channels 1-10 in thermocouple temperature mode and prints the reading of
each channel, so a probe wired to an unexpected terminal is found immediately.

Run:  python probe_check.py
"""
import sys

import pyvisa

TC_TYPE = "T"
CHANNELS = range(1, 11)

rm = pyvisa.ResourceManager()

# --- locate the DMM6500 -----------------------------------------------------
dmm = None
for res in rm.list_resources():
    try:
        inst = rm.open_resource(res)
        inst.timeout = 2000
        idn = inst.query("*IDN?").strip()
    except Exception:
        continue
    if "DMM6500" in idn.upper():
        dmm = inst
        print(f"Found: {idn}\n   at: {res}")
        break
    inst.close()

if dmm is None:
    print("No DMM6500 found on any VISA resource.")
    sys.exit(1)

dmm.timeout = 5000

# --- check the front/rear TERMINALS switch ----------------------------------
terminals = dmm.query(":ROUT:TERM?").strip().upper()
print(f"TERMINALS switch: {terminals}")
if terminals.startswith("FRON"):
    print("\n*** The TERMINALS switch is on FRONT - the scanner card is NOT in")
    print("*** the measurement path and every channel will read as open.")
    print("*** Flip the physical switch on the front panel to REAR, then rerun.")
    sys.exit(1)

# --- scan all channels in TC temperature mode -------------------------------
dmm.write("*RST")
dmm.query("*OPC?")
print(f"\nScanning channels 1-10 as type-{TC_TYPE} thermocouples "
      "(SIM reference junction 23 C)...\n")
print(f"{'channel':>8} | {'reading':>12} | status")
print("-" * 44)
for ch in CHANNELS:
    try:
        dmm.write(f":SENS:FUNC 'TEMP', (@{ch})")
        dmm.write(f":SENS:TEMP:TRAN TC, (@{ch})")
        dmm.write(f":SENS:TEMP:TC:TYPE {TC_TYPE}, (@{ch})")
        dmm.write(f":SENS:TEMP:TC:RJUN:RSEL SIM, (@{ch})")
        dmm.write(f":SENS:TEMP:TC:RJUN:SIM 23, (@{ch})")
        dmm.write(f":ROUT:CLOS (@{ch})")
        value = float(dmm.query(":READ?"))
        if abs(value) > 1e30:
            print(f"{ch:>8} | {'overflow':>12} | OPEN (no thermocouple)")
        else:
            print(f"{ch:>8} | {value:>10.2f} C | OK - probe detected")
    except Exception as exc:
        print(f"{ch:>8} | {'error':>12} | {exc}")
    # show any queued instrument errors for this channel
    while True:
        err = dmm.query(":SYST:ERR?").strip()
        if err.split(",")[0].lstrip("+") == "0":
            break
        print(f"{'':>8} | {'':>12} | instrument error: {err}")

dmm.write(":ROUT:OPEN:ALL")
dmm.close()
print("\nDone. The GUI expects: T2 probe on channel 2, T3 ambient on channel 3.")
print("If your probes show up on other channels, either move the wires or tell")
print("Claude the channel numbers so the program constants can be updated.")
