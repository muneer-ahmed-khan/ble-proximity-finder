# Implementation notes

The tool uses Bleak advertisement callbacks and an asyncio loop. It reads broadcasts without pairing or opening a GATT connection.

## Modules

| Module | Responsibility |
| --- | --- |
| `cli.py` | Arguments, scan lifecycle, target selection, calibration workflow, error reporting |
| `model.py` | Device state, smoothing, proximity bands, distance and cadence calculations |
| `calibration.py` | Validated reference records, override precedence, atomic JSON writes |
| `output.py` | Survey/hunt rendering and terminal-safe device text |
| `audio.py` | Nonblocking platform playback, cadence scheduling, cleanup |

## Advertisement processing

A device record stores its identifier, best available advertised name, latest raw RSSI, last-seen time, counters, and a five-sample window. Timing uses a monotonic clock.

Consecutive identical RSSI values received less than 200 ms apart are excluded from the sample window. They still refresh last-seen. Values outside the accepted RSSI range are ignored. The average is calculated over the available accepted samples, up to five.

Survey sorts live records by average RSSI. Strongest signal is a useful proximity heuristic; devices with different transmit powers cannot be ranked by physical distance reliably.

## Hunt lifecycle

Selection uses an exact identifier or exact advertised name. Ambiguous names produce an error asking for an identifier. After selection, the target identifier stays fixed. Hunt updates on accepted target readings and reports loss independently of new callbacks.

The target record is retained during loss; other stale records are removed. Reacquisition after the unseen timeout resets the target’s smoothing window. A startup timeout bounds the wait for an initial match.

## Audio scheduling

The audio timer uses the most recent smoothed RSSI and time of the last beep. A changed signal can advance or postpone the pending beep. Advertisement arrival rate does not determine playback cadence. Loss and interruption stop playback and release temporary audio resources during normal cleanup.

## Calibration and failure handling

Calibration stores a single validated reference locally. It is written to a temporary file, flushed, and atomically replaced. Saved values apply only to their matching target; explicit flags override them.

The scanner is managed through an asynchronous context and cleanup stack. On macOS, a parent process detects native termination that cannot be handled as a Python exception. Operational errors are translated into readable guidance and nonzero exit codes.

Tests inject fake advertisements, a clock, and playback processes. They verify calculations and lifecycle behavior without a radio; physical validation is recorded separately in [TESTING.md](../TESTING.md).
