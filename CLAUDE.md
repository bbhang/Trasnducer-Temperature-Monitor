# Project conventions for Claude Code

ICE Transducer Temperature Monitor — Tkinter GUI for IEC 60601-2-37:2024
clause 201.11 transducer surface-temperature testing with a Keithley DMM6500
(see `doc/User_Guide.md`).

## Versioning (strict)

- **Every functional update gets its own patch version bump**
  (V1.3.6 → V1.3.7). Never batch several updates into one minor bump.
  One version = one update = one commit = one git tag.
- Bump `APP_VERSION` in `code/temp_monitor_gui.py` **and** the file's header
  comment block (`Version` / `Modified` / `Notes`). The `Notes` field holds
  **only the latest version's note**; older notes live in `CHANGELOG.md`.
- Add a `## VX.Y.Z — YYYY-MM-DD` section at the top of `CHANGELOG.md`.
- Update `doc/User_Guide.md` for user-visible changes, including the
  section-7 verification stamp: "All checks pass as of <date> (VX.Y.Z)".

## Testing

- Run `python temp/selftest.py` before every commit; it must end with
  `0 check(s) failed`. Extend it with checks for each new feature.
- Test outputs go to per-run folders `temp/run_*/` (gitignored).

## Git workflow

- Develop **directly on `main`** (no feature branches needed).
- Commit message style: `V1.3.7: short lowercase description`.
- Lightweight tag `vX.Y.Z` on every version commit.
- Push (with `--tags`) when the user asks.
