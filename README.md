# Bluetooth Proximity Finder

Find a nearby Bluetooth Low Energy device from the terminal. Scan for advertisements, pick a target, and follow its signal strength as you move. Optional beeps get faster as the signal gets stronger.

Built for John Crickett’s **Coding Challenge #140: Bluetooth Proximity Finder**.

## What it does

- Lists nearby BLE advertisers, sorted by smoothed signal strength.
- Tracks one device by its advertised name or platform identifier.
- Calibrates a reference signal at a measured distance.
- Shows raw RSSI, a five-reading average, proximity bands, and approximate metres.
- Provides audio feedback and reports when the target is lost or reacquired.
- Handles unavailable Bluetooth adapters and permission failures with readable errors.

This is a signal meter. It cannot tell you which direction to walk, and it can only track devices that advertise BLE.

## Install

You need Python 3.11 or newer, a BLE-capable Bluetooth adapter, and a nearby advertising device.

From the repository directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
ble-finder --help
```

On Windows, activate the environment with `.venv\Scripts\Activate.ps1` in PowerShell.

macOS is the hardware-tested platform. The implementation uses Bleak’s cross-platform backends; Windows and Linux hardware behavior has not been verified. See [platform setup and troubleshooting](docs/usage.md#platform-setup).

## Try it

### 1. Find a target

```sh
ble-finder
```

Survey refreshes once a second and removes devices unseen for ten seconds. A signal closer to zero is stronger: −45 dBm is stronger than −75 dBm. Unnamed devices appear by identifier.

Phones do not necessarily advertise a recognizable name just because Bluetooth is enabled. For an iPhone test, create a named virtual peripheral in [LightBlue](https://punchthrough.com/lightblue/) and keep the app open while advertising. [Detailed instructions](docs/usage.md#testing-with-an-iphone)

### 2. Calibrate

Place the target at a measured distance with a clear path to the laptop. For a one-metre reference:

```sh
ble-finder --calibrate "Test-Phone" --reference-distance 1
```

Replace `Test-Phone` with the name or identifier from your survey. Press Enter when positioned and hold still for the five-second sample. Calibration stores the average RSSI and reference distance locally.

### 3. Hunt

```sh
ble-finder --hunt "Test-Phone" --sound --verbose
```

Walk toward and away from the target. Listen for shorter or longer gaps between beeps; the pitch stays the same. Verbose output shows reading counts and the intended beep interval.

Example output, using fictional data:

```text
Using reference: near=-58.0, far=-72 dBm at 1 m; path-loss exponent=2.
Tracking: Test-Phone  example-device-id  raw -64  avg -63.0 dBm  same room  ~1.8 m  raw=20 accepted=15 changed=13  beep every 1.23s (0.8/s)
Target lost — no recent advertisements; sound stopped.
```

Hunt waits for the same target to return after a loss. Press Ctrl+C to stop.

## Reading the display

`raw` is the latest signal reading; `avg` is the average of the last five accepted readings. Proximity bands use the calibrated or configured near/far references. The metre estimate uses a log-distance model and is **approximate**: walls, bodies, orientation, transmit power, and interference affect it.

Before calibration, the defaults assume −45 dBm at 0.7 metres. Do not treat those estimates as measurements. A calibration taken at one metre makes that position the “very close” reference; the label describes a signal threshold, not a precise room boundary.

Sound ranges from one beep every two seconds at the far reference to one every 0.8 seconds at the near reference. It reaches one every 0.2 seconds at a signal 20 dB stronger than near, so closer-than-calibration positions remain distinguishable.

## Options

Run `ble-finder --help` for every flag. Common overrides:

```sh
ble-finder --hunt "Test-Phone" --near -58 --far -75 --path-loss 2
ble-finder --hunt "Test-Phone" --startup-timeout 15 --timeout 5
ble-finder --refresh 2 --verbose
```

Names match exactly. If several devices share a name, use the identifier from survey. macOS uses UUID identifiers rather than MAC addresses.

Calibration is saved at `~/.ble-finder/calibration.json` and applies only to its matching identifier. Explicit flags override saved values, then defaults. A new calibration replaces the previous record. Use `--calibration-file` to choose another path.

## Development

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m pip check
```

The automated suite tests signal calculations, device state, calibration, CLI behavior, audio scheduling, and error handling without needing Bluetooth hardware. Physical testing remains necessary for radio and sound behavior.

- [Usage, defaults, and troubleshooting](docs/usage.md)
- [Implementation notes](docs/architecture.md)
- [Test coverage and manual checklist](TESTING.md)

## References

- [Coding Challenges](https://codingchallenges.fyi/) — John Crickett’s challenge series.
- [Bleak scanner API](https://bleak.readthedocs.io/en/latest/api/scanner.html).
- [Bleak macOS backend](https://bleak.readthedocs.io/en/latest/backends/macos.html).
