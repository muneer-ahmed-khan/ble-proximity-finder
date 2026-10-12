import argparse
import asyncio
import math
import os
import subprocess
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path
from statistics import mean

from . import calibration, output
from .audio import Audio
from .model import FinderError, Tracker


def positive(text):
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return value


def parser():
    result = argparse.ArgumentParser(
        description="Find an advertising BLE device by signal strength.",
        epilog=(
            "RSSI distance is noisy and approximate: walls, bodies and interference matter. "
            "A single radio estimates distance, not bearing. Bluetooth on alone does not "
            "guarantee a phone advertises BLE. Uncalibrated defaults assume -45 dBm at 0.7 m."
        ),
    )
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--hunt", metavar="NAME_OR_ID", help="track one exact name or identifier")
    modes.add_argument("--calibrate", metavar="NAME_OR_ID", help="measure a near reference")
    result.add_argument("--sound", action="store_true", help="audible hunt feedback")
    result.add_argument("--verbose", action="store_true", help="show raw/accepted/changed counts")
    result.add_argument("--near", type=float, help="near reference dBm (default -45)")
    result.add_argument("--far", type=float, help="far reference dBm (default -72)")
    result.add_argument(
        "--reference-distance", type=positive, help="near-reference metres (default 0.7)"
    )
    result.add_argument(
        "--path-loss", type=positive, default=2, help="path-loss exponent (default 2)"
    )
    result.add_argument(
        "--refresh", type=positive, default=1, help="survey refresh seconds (default 1)"
    )
    result.add_argument(
        "--timeout", type=positive, default=10, help="unseen timeout seconds (default 10)"
    )
    result.add_argument(
        "--startup-timeout",
        type=positive,
        default=30,
        help="target/startup wait seconds (default 30)",
    )
    result.add_argument(
        "--calibration-file",
        type=Path,
        default=calibration.default_path(),
        help="calibration JSON path (default ~/.ble-finder/calibration.json)",
    )
    return result


def validate(args, argument_parser):
    if args.sound and not args.hunt:
        argument_parser.error("--sound requires --hunt")
    if args.calibrate and args.near is not None:
        argument_parser.error("--near cannot be supplied with --calibrate; it is measured")
    if args.hunt == "" or args.calibrate == "":
        argument_parser.error("target cannot be empty")
    for value in (args.near, args.far):
        if value is not None and (not math.isfinite(value) or not -127 <= value <= 20):
            argument_parser.error("RSSI references must be finite and between -127 and 20 dBm")
    if args.near is not None and args.far is not None and args.near <= args.far:
        argument_parser.error("near must be stronger than far")


def bluetooth_error(exc):
    reason = str(getattr(exc, "reason", "")).lower()
    detail = (reason + " " + str(exc)).lower()
    if any(word in detail for word in ("denied", "unauthorized", "not authorized", "permission")):
        return (
            "Bluetooth permission denied. On macOS enable your terminal/application in "
            "System Settings → Privacy & Security → Bluetooth; restart it and try again."
        )
    if any(word in detail for word in ("powered_off", "powered off", "turned off", "not powered")):
        return "Bluetooth is off. Enable Bluetooth in system settings and try again."
    if any(
        word in detail
        for word in (
            "no_bluetooth",
            "no bluetooth",
            "no adapter",
            "not supported",
            "no_ble_central_role",
        )
    ):
        return "No BLE-capable adapter found. Attach or enable a supported Bluetooth adapter."
    return (
        "Bluetooth scan failed. Check the adapter is enabled and BLE-capable, grant Bluetooth "
        "permission, and retry. On Linux ensure BlueZ is running and accessible."
    )


async def run(
    args, scanner_factory=None, clock=time.monotonic, sleeper=asyncio.sleep, audio_factory=Audio
):
    saved = None if args.calibrate else calibration.load(args.calibration_file)
    target = args.hunt or args.calibrate
    if saved is None or saved.identifier == target or target is None:
        calibration.resolve(args, saved, target)
    tracker = Tracker(args.timeout, target)
    callback_error = None
    samples = []
    sample_start = None

    def reference(identifier):
        return calibration.resolve(args, saved, identifier)

    def receive(device, advertisement):
        nonlocal callback_error, sample_start
        try:
            now = clock()
            previous_revision = tracker.revision
            tracker.receive(device.address, advertisement.local_name, advertisement.rssi, now)
            if args.calibrate and tracker.revision != previous_revision:
                if sample_start is None:
                    sample_start = now
                samples.append(tracker.target_device().raw_rssi)
        except (FinderError, ValueError) as exc:
            callback_error = FinderError(str(exc))

    if args.calibrate:
        distance = args.reference_distance or 0.7
        try:
            input(
                f"Hold the target at arm's length, {distance:g} m from the adapter. "
                "Use --reference-distance if different. Press Enter to sample for 5 seconds: "
            )
        except EOFError as exc:
            raise FinderError(
                "Calibration requires interactive input; run it in a terminal."
            ) from exc
    if scanner_factory is None:
        from bleak import BleakScanner

        scanner_factory = BleakScanner
    print(output.DISCLAIMER, flush=True)
    print(
        "Uncalibrated readings assume -45/-72 dBm at 0.7 m; flags override saved values.",
        flush=True,
    )
    if target:
        print(f"Waiting for {output.safe(target)} (Ctrl+C to stop)...", flush=True)
    async with AsyncExitStack() as stack:
        sound = await stack.enter_async_context(audio_factory()) if args.sound else None
        scanner = scanner_factory(detection_callback=receive)
        try:
            await asyncio.wait_for(stack.enter_async_context(scanner), timeout=args.startup_timeout)
        except TimeoutError as exc:
            raise FinderError(
                "Bluetooth scanner startup timed out. Check adapter power and permission."
            ) from exc
        started = clock()
        next_refresh = started
        displayed_revision = -1
        was_alive = False
        found = False
        while True:
            now = clock()
            if callback_error:
                raise callback_error
            tracker.live(now)
            device = tracker.target_device()
            if target:
                if device is None and now - started >= args.startup_timeout:
                    raise FinderError(
                        f"Target {output.safe(target)} was not seen within "
                        f"{args.startup_timeout:g} seconds. "
                        "Check BLE advertising or use an identifier."
                    )
                alive = device is not None and device.alive(now, args.timeout)
                if alive:
                    ref = reference(device.identifier)
                    if not found and not args.calibrate:
                        print(
                            f"Using reference: near={ref.near:.1f}, far={ref.far:g} dBm "
                            f"at {ref.distance:g} m; path-loss exponent={ref.exponent:g}.",
                            flush=True,
                        )
                    if args.calibrate:
                        if sample_start is not None and now - sample_start >= 5:
                            if len(samples) < 3:
                                raise FinderError(
                                    "Too few calibration samples; ensure the target "
                                    "advertises regularly and retry."
                                )
                            measured = mean(samples)
                            far = args.far if args.far is not None else -72
                            distance = args.reference_distance or 0.7
                            try:
                                record = calibration.Calibration(
                                    device.identifier, measured, far, distance
                                )
                            except ValueError as exc:
                                raise FinderError(
                                    "Measured near reference is not stronger than far. "
                                    "Move closer or adjust --far."
                                ) from exc
                            calibration.save(args.calibration_file, record)
                            print(
                                f"Saved near={measured:.1f}, far={far:g} dBm at {distance:g} m "
                                f"from {len(samples)} accepted samples to {args.calibration_file}."
                            )
                            return 0
                    elif tracker.revision != displayed_revision:
                        status = "Reacquired" if found and not was_alive else "Tracking"
                        output.hunt(device, ref, args.verbose, status, sound=args.sound)
                        displayed_revision = tracker.revision
                    found = True
                elif was_alive:
                    print("Target lost — no recent advertisements; sound stopped.", flush=True)
                    if args.calibrate:
                        raise FinderError("Target lost during calibration; move closer and retry.")
                was_alive = alive
                if args.calibrate and sample_start is not None and now - sample_start >= 5:
                    raise FinderError("Not enough recent calibration data; move closer and retry.")
                if sound:
                    await sound.update(
                        device, now, args.timeout, reference(device.identifier) if device else None
                    )
            elif now >= next_refresh:
                output.survey(tracker.live(now), reference, args.verbose)
                next_refresh = now + args.refresh
            await sleeper(0.05)


def guarded_macos(argv):
    environment = os.environ.copy()
    environment["BLE_FINDER_WORKER"] = "1"
    process = subprocess.Popen([sys.executable, "-m", "ble_finder", *argv], env=environment)
    try:
        code = process.wait()
    except KeyboardInterrupt:
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        return 130
    if code < 0:
        print(
            "Error: the native Bluetooth process was terminated by macOS. "
            "Check Bluetooth permission for your terminal/application in "
            "System Settings → Privacy & Security → Bluetooth, restart it, and retry. "
            "If Python is not listed or still aborts, use a Python distribution "
            "with a macOS Bluetooth usage description.",
            file=sys.stderr,
        )
        return 1
    return code


def main(argv=None):
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    validate(args, argument_parser)
    if sys.platform == "darwin" and os.environ.get("BLE_FINDER_WORKER") != "1":
        return guarded_macos(list(sys.argv[1:] if argv is None else argv))
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except FinderError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: invalid calibration/overrides: {exc}", file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as exc:
        print(f"Error: {bluetooth_error(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:
        from bleak.exc import BleakError

        if isinstance(exc, BleakError):
            print(f"Error: {bluetooth_error(exc)}", file=sys.stderr)
            return 1
        raise
