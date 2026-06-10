# IEC 60601-2-37:2024 — Transducer Surface Temperature Requirements Summary

Source: `Standard\IEC 60601-2-37_2024.pdf`, clause 201.11 (pages 24–28 of the standard).
Scope of this test program: ICE (intracardiac echo) catheter transducer = **INVASIVE TRANSDUCER ASSEMBLY**.

## 1. Top-level requirement (201.11.1.2.2)

> TRANSDUCER ASSEMBLIES applied to the PATIENT shall have a PATIENT contact surface
> temperature **not exceeding 43 °C** in NORMAL CONDITIONS when measured under test
> conditions 201.11.1.3.101.1 (simulated use).
>
> TRANSDUCER ASSEMBLIES applied to the PATIENT shall have a PATIENT contact surface
> temperature **not exceeding 50 °C** when measured under test conditions
> 201.11.1.3.101.2 (still air).

The PATIENT contact surface includes any part of the APPLIED PART, not just the radiating
surface, but excluding the cable.

## 2. Tests and limits (Table 201.104, invasive-use column)

| Test | Clause | Conditions | Limit |
|---|---|---|---|
| Simulated use — method a) peak temperature | 201.11.1.3.101.1 a) | Ambient 23 ± 3 °C. Point of contact of the test object ≥ 37 °C and stable before contacting the applied part. | Surface temperature **≤ 43 °C** |
| Simulated use — method b) temperature rise | 201.11.1.3.101.1 b) | Ambient 23 ± 3 °C. Initial temperature at the object–transducer interface between 20 °C and 37 °C, in thermal steady state. | Temperature rise + THERMAL OFFSET **≤ 6 °C**  (ΔTtx + ΔToffset + 37 °C ≤ 43 °C, Eq. 3) |
| Still air (no coupling gel) | 201.11.1.3.101.2 | Ambient 23 ± 3 °C, stable within 0.5 °C, no airflow. Initial applied-part temperature = ambient (or known stable offset). | Temperature rise + THERMAL OFFSET **≤ 27 °C**  (ΔTtx + ΔToffset + 23 °C ≤ 50 °C, Eq. 4) |

Notes:
- Temperature rise (method b) is defined as the difference between the transducer
  temperature just before acoustic activation and the maximum temperature measured
  during the test (Note 1 to 201.11.1.3.101.1).
- Method a) shall be used where the equipment uses a closed-loop temperature
  monitoring system.
- THERMAL OFFSET (201.3.228) must be a known, stable value at thermal steady state.

## 3. Thermal steady state (201.11.1.3.101 / 201.11.1.3.103)

> Thermal steady state is considered reached when the rate of change of temperature is
> **< 0.12 °C per minute for three consecutive minutes**.

## 4. Test duration (201.11.1.3.103)

- The equipment is continually operated for the duration of the test.
- Simulated-use test: **30 min** or until thermal steady state is reached.
- Still-air test: **30 min**; or twice the time period limited by an automatic output
  hold/"freeze" the operator cannot disable; or until thermal steady state.
- If the equipment automatically freezes or halts output earlier, it shall be switched
  on again immediately.

## 5. Operating settings (201.11.1.3.102)

Operate the ultrasonic diagnostic equipment at the setting that gives the **highest
surface temperature** of the applied part. The transmit parameters shall be recorded in
the test report.

## 6. Temperature measurement (201.11.1.3.104)

- Thermocouple or infra-red radiometry may be used.
- A thermocouple junction and adjacent lead wire shall be held in good thermal contact
  with the surface being measured, positioned so that it has a negligible effect on the
  temperature rise of the measured area (thin film or fine wire recommended).
- Measure at the areas of the applied part giving the **highest** surface temperature.
- The **measurement uncertainty shall be recorded in the test report**
  (ISO/IEC Guide 98-1 recommended).

## 7. Test object properties (simulated use, 201.11.1.3.101.1)

Soft-tissue-mimicking material:
- Specific heat capacity: (3500 ± 500) J/(kg·K)
- Thermal conductivity: (0.5 ± 0.1) W/(m·K)
- Attenuation at 5 MHz: (2.5 ± 1.0) dB/cm
- Designed (e.g. with absorbers) to minimize ultrasound reflections back to the
  transducer surface.

## 8. Related display requirement (201.12.4.2 j)

> If an ULTRASONIC TRANSDUCER intended for trans-oesophageal use is capable of exceeding
> a surface temperature of 41 °C, then the surface temperature shall be displayed or an
> indication provided to the OPERATOR when the surface temperature equals or exceeds 41 °C.

Although stated for trans-oesophageal transducers, the monitoring GUI adopts **41 °C as a
conservative warning threshold** for the ICE catheter.

## 9. Single fault condition note (201.13.1.2)

The +5 °C single-fault allowance applies **only** to transducer assemblies intended for
application to the skin surface (external use). It does **not** apply to invasive
(ICE) transducers.

## 10. How the GUI applies these requirements

| GUI test mode | Pass criterion (per channel T2, T3) | Auto-stop |
|---|---|---|
| Simulated use a) Peak temperature | max temperature ≤ 43.0 °C | 30 min or steady state |
| Simulated use b) Temperature rise (invasive) | (max T − baseline T) + thermal offset ≤ 6.0 °C | 30 min or steady state |
| Still air | (max T − baseline T) + thermal offset ≤ 27.0 °C | 30 min or steady state |

- Baseline = reading captured at test start (just before acoustic activation).
- Steady state detection: linear-fit rate over a 60 s window < 0.12 °C/min held for
  180 consecutive seconds, evaluated independently for each channel.
- Warning (yellow) when any channel ≥ 41 °C in peak mode; alarm (red) and FAIL when a
  limit is exceeded.
- The report includes operator-filled fields for transmit parameters (201.11.1.3.102)
  and measurement uncertainty (201.11.1.3.104).
