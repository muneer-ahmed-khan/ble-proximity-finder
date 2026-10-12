import sys

from .model import Reference

DISCLAIMER = "Distance is approximate: walls, bodies and interference affect RSSI. No bearing."


def safe(value):
    return "".join(c if c.isprintable() else "?" for c in str(value))[:100]


def row(device, reference, verbose=False):
    metres = reference.metres(device.smoothed)
    distance = "<0.1 m" if metres < 0.1 else f"~{metres:.1f} m"
    text = (
        f"{safe(device.name or device.identifier):<30} {safe(device.identifier):<38} "
        f"raw {device.raw_rssi:4}  avg {device.smoothed:6.1f} dBm  "
        f"{reference.band(device.smoothed):<10}  {distance}"
    )
    if verbose:
        text += (
            f"  raw={device.raw_count} accepted={device.accepted_count}"
            f" changed={device.changed_count}"
        )
    return text


def survey(devices, reference_for, verbose=False):
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")
    print("BLE survey — strongest smoothed signal first (Ctrl+C to stop)")
    print(DISCLAIMER)
    print("Uncalibrated devices use assumed -45/-72 dBm at 0.7 m unless flags override them.")
    for device in devices:
        print(row(device, reference_for(device.identifier), verbose))
    if not devices:
        print("No advertisements received recently; check that your target advertises BLE.")
    sys.stdout.flush()


def hunt(device, reference: Reference, verbose=False, status="Tracking", sound=False):
    text = f"{status}: {row(device, reference, verbose)}"
    if verbose and sound:
        interval = reference.interval(device.smoothed)
        text += f"  beep every {interval:.2f}s ({1 / interval:.1f}/s)"
    print(text, flush=True)
