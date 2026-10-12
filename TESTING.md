# Testing

## Automated checks

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m pip check
```

The suite covers band boundaries, distance calculations, cadence mapping, smoothing, debounce, last-seen updates, sorting/expiry, name ambiguity, calibration persistence/precedence, invalid input, survey/hunt/calibration workflows, target loss/reacquisition, audio scheduling/cleanup, and native-process error reporting.

Latest local verification: **50 tests passed**, lint/format checks passed, and dependencies were consistent. Environment: Python 3.11.13, Bleak 3.0.2, pytest 9.1.1, Ruff 0.17.0 on macOS 26.1.

## Hardware validation

A named iPhone virtual peripheral was discovered from macOS. Calibration completed at a measured one-metre reference using 12 accepted readings. Hunt displayed changing raw/smoothed RSSI, bands, and estimates. Audio was heard; the revised cadence was reported as working, but a controlled interval comparison has not been recorded.

These observations do not prove accurate distance measurement. Windows and Linux hardware behavior is untested.

| Check | Current evidence |
| --- | --- |
| Live discovery and named target | Observed on macOS with an iPhone test advertiser |
| Calibration at a measured reference | Completed at 1 m |
| Hunt display and verbose counters | Observed with changing signal readings |
| Directional signal trends while moving | Signal variation observed; positions/times not recorded |
| Revised audible cadence | Informally reported working; controlled comparison pending |
| Real target loss/reacquisition and silence on loss | Pending physical check; automated coverage passes |
| Never-seen target startup timeout | Automated coverage passes; successful-radio physical check pending |
| Distance at several measured positions | Pending |
| Adapter off, absent adapter, permission refusal and recovery | Automated error mapping/native termination checked; full physical matrix pending |

## Manual checklist

1. Inspect Bluetooth settings and confirm a known target is advertising.
2. Run survey with two advertisers. Move one farther away, then stop it and verify expiry after the timeout.
3. Calibrate at a measured reference distance. Change near/far flags and confirm band thresholds shift.
4. Hunt by name and identifier. Stop/start advertising and verify lost/reacquired status. Try a nonexistent name with a short startup timeout.
5. Observe raw, accepted, and changed counters with the target stationary and moving. Do not expect a fixed counter ratio.
6. Compare beep spacing at steady strong, intermediate, and weak signals. Stop advertising and confirm silence after loss.
7. Compare estimated metres at several measured positions, including through an obstacle. Record the error rather than assuming precision.
8. Verify adapter-off and permission errors where the OS permits, restore access, and confirm cleanup with Ctrl+C.

Use fictional labels in shared screenshots or logs. Exclude actual device identifiers, calibration files, and private host paths from reports.
