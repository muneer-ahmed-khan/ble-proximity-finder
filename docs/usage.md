# Usage guide

## Platform setup

Inspect your OS Bluetooth settings before scanning. Enable the adapter and confirm that your test device is advertising. Some settings screens do not show RSSI; survey supplies advertisement RSSI instead.

### macOS

Grant Bluetooth access to the terminal or application running Python in **System Settings → Privacy & Security → Bluetooth**. Restart that application after changing permission if scanning still fails.

macOS returns host-specific UUIDs for BLE devices, not Bluetooth MAC addresses. Use the identifier from the current Mac’s survey; a phone’s address from its Settings cannot be converted through this scanner.

Use macOS 12.3 or newer for unrestricted active scanning. Some Python runtimes require a Bluetooth usage description in their application metadata. If the native Bluetooth process terminates before an exception can be raised, the CLI reports it through a parent process. Check terminal permissions and use a Python distribution configured for macOS Bluetooth access. See [Bleak’s permission documentation](https://bleak.readthedocs.io/en/latest/backends/macos.html#permissions).

### Linux and Windows

Linux requires a BLE adapter and a running, accessible BlueZ service. Sound uses `aplay`; on Debian-based distributions it is provided by `alsa-utils`.

Windows requires an enabled BLE-capable adapter. Sound uses the Windows system sound. These platforms have not been hardware-tested.

## Testing with an iPhone

A controlled advertisement makes the phone identifiable without guessing from signal strength.

1. Install **LightBlue by Punch Through** on the iPhone and allow Bluetooth access.
2. Open **Virtual Devices**, add a **Blank** peripheral, and configure a short advertised name such as `Test-Phone` if the name field is available.
3. Save the device and enable advertising.
4. Keep the app open in the foreground with the screen unlocked.
5. Run survey on the laptop and find the advertised name.
6. Stop advertising and wait at least ten seconds; restart it and confirm the same test advertisement returns.

Use the name actually displayed by survey. Interface labels may vary by app version. If a blank profile does not start advertising, consult [LightBlue’s virtual-device guide](https://punchthrough.com/how-to-use-lightblue/).

iOS omits the advertised local name in the background. This test setup does not establish that the tool can reliably identify an ordinary locked iPhone without a controlled advertiser. See [Apple’s peripheral advertising documentation](https://developer.apple.com/documentation/corebluetooth/cbperipheralmanager/startadvertising(_:)).

## Calibration

Measure the distance from roughly the laptop’s base to the target. Keep orientation and placement consistent, avoid blocking the path with your body, and hold both devices still. Supply the measured distance with `--reference-distance`; arm’s length is not automatically one metre.

The CLI waits for the selected target, then collects accepted readings for five seconds. It requires at least three samples and saves their average as near RSSI. The far reference defaults to −72 dBm and can be overridden with `--far`. Near must be stronger than far.

A new calibration atomically replaces the previous local record. It applies only to the matching identifier. Corrupt or unreadable records produce an error; repair or remove the indicated file. Explicit flags take precedence over calibration, then defaults.

## Defaults

| Setting | Default |
| --- | --- |
| Survey refresh | 1 second |
| Unseen timeout | 10 seconds |
| Target startup timeout | 30 seconds |
| Near / far RSSI | −45 / −72 dBm |
| Reference distance | 0.7 m, assumed |
| Path-loss exponent | 2 |
| Moving average | Five accepted readings |
| Duplicate debounce | Same consecutive RSSI within 200 ms |
| Calibration sampling | 5 seconds |

Survey removes stale rows. Hunt retains its selected identifier, announces loss after the unseen timeout, stops audio, and waits for reacquisition. Startup timeout applies before the first target match; a never-seen target exits with an error.

## Signal, distance, and sound

RSSI at or above near is “very close”; readings between far and near are “same room”; readings below far are “far.” Noise can cause labels to cross boundaries while the device is stationary.

The distance model is:

```text
distance = reference_distance × 10^((reference_RSSI − smoothed_RSSI) / (10 × path_loss))
```

It estimates distance, not bearing. Environmental variation and unknown transmit power make metre values approximate. Values below 0.1 m display as `<0.1 m` rather than rounding to zero.

Audio uses the smoothed signal and a separate timer. Beep spacing is interpolated between two seconds at far, 0.8 seconds at near, and 0.2 seconds at near +20 dB, clamped at the endpoints. Verbose hunt shows the intended interval; playback overhead may affect the actual cadence. macOS uses a temporary WAV tone with `afplay`, Linux uses `aplay`, and Windows uses the system sound.

Verbose counters distinguish raw callbacks, accepted samples, and changes in raw RSSI. Repeated readings can be genuine; debounce is a heuristic. A stationary device can still produce many changed readings. Every valid advertisement updates last-seen, including readings excluded from smoothing.

## Troubleshooting

**No recognizable names:** Devices may advertise without a name. Use a known advertiser or the survey identifier. Strongest signal alone does not identify a device.

**Repeated rows or old output:** Survey redraws once a second. Terminal scrollback can retain previous snapshots; scan data is not loaded from old sessions. Within a scan, the last reading remains until the unseen timeout. Clear scrollback using your terminal’s controls if needed.

**No target found:** Check the exact advertised name, keep the advertiser active, and try its identifier. Bluetooth enabled alone does not guarantee BLE advertising.

**Sound seems unchanged:** Listen for gaps between beeps, not pitch. Hold positions long enough for the five-reading average to settle. Read the verbose beep interval and compare a strong signal with a weak one.

**Metres look implausible:** Calibrate at a measured distance and compare signal trends. Changing the path-loss exponent changes the model, but does not remove radio uncertainty.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Help or successful calibration |
| 1 | Operational failure, unavailable Bluetooth, or unseen target |
| 2 | Invalid arguments or reference overrides |
| 130 | Interrupted with Ctrl+C |
