import asyncio
import json
from types import SimpleNamespace

import pytest

from ble_finder import calibration, cli, output
from ble_finder.audio import Audio
from ble_finder.model import Device, FinderError, Reference, Tracker


def options(tmp_path, *flags):
    return cli.parser().parse_args(
        ["--calibration-file", str(tmp_path / "calibration.json"), *flags]
    )


@pytest.mark.parametrize(
    "rssi,band",
    [
        (-44, "very close"),
        (-45, "very close"),
        (-46, "same room"),
        (-72, "same room"),
        (-73, "far"),
    ],
)
def test_band_boundaries(rssi, band):
    assert Reference().band(rssi) == band


def test_distance_and_audio_mapping():
    ref = Reference(distance=1)
    assert ref.metres(-45) == 1
    assert ref.metres(-65) == pytest.approx(10)
    assert ref.interval(-90) == 2
    assert ref.interval(-25) == pytest.approx(0.2)
    assert 0.2 < ref.interval(-60) < 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"near": -80},
        {"distance": 0},
        {"exponent": -1},
        {"near": float("nan")},
        {"far": float("-inf")},
    ],
)
def test_reference_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        Reference(**kwargs)


def test_moving_window_duplicate_and_liveness():
    d = Device("id")
    assert d.receive(-50, 0, 10)
    assert not d.receive(-50, 0.1, 10)
    assert d.last_seen == 0.1
    assert d.alive(10.05, 10)
    assert not d.alive(10.1, 10)
    for t, rssi in enumerate([-60, -70, -80, -90, -100], 1):
        d.receive(rssi, t, 10)
    assert d.smoothed == -80
    assert (d.raw_count, d.accepted_count, d.changed_count) == (7, 6, 6)
    assert d.receive(-100, 5.2, 10)
    assert d.accepted_count == 7
    d.receive(-40, 16, 10)
    assert list(d.samples) == [-40]
    assert d.generation == 2


def test_survey_sorted_expired_and_unnamed():
    t = Tracker(timeout=10)
    t.receive("weak", None, -80, 0)
    t.receive("strong", "Phone", -40, 1)
    assert [d.identifier for d in t.live(2)] == ["strong", "weak"]
    assert [d.identifier for d in t.live(10)] == ["strong"]
    assert "weak" not in t.devices


def test_hunt_lost_reacquired_and_ignored():
    t = Tracker(timeout=1, target="Phone")
    t.receive("id", None, -40, 0)
    assert t.selected is None
    t.receive("id", "Phone", -42, 0.5)
    t.receive("other", "Other", -10, 0.6)
    assert t.selected == "id"
    assert t.revision == 1
    assert not t.target_device().alive(1.5, 1)
    t.live(1.5)
    assert "id" in t.devices
    t.receive("id", "Phone", -80, 2)
    assert t.target_device().smoothed == -80
    assert t.revision == 2


def test_ambiguous_names_and_identifier_selection():
    t = Tracker(target="Same")
    t.receive("a", "Same", -40, 0)
    with pytest.raises(FinderError, match="Several"):
        t.receive("b", "Same", -50, 0)
    t = Tracker(target="a")
    t.receive("a", "Same", -40, 0)
    t.receive("b", "Same", -50, 0)
    assert t.selected == "a"


def test_bad_rssi_is_ignored():
    t = Tracker()
    for value in [127, -128, None]:
        t.receive("id", None, value, 0)
    assert not t.devices


def test_calibration_atomic_roundtrip_and_precedence(tmp_path):
    path = tmp_path / "nested" / "calibration.json"
    record = calibration.Calibration("id", -40, -80, 1)
    calibration.save(path, record)
    assert calibration.load(path) == record
    assert len(list(path.parent.iterdir())) == 1
    args = options(tmp_path, "--near", "-42")
    ref = calibration.resolve(args, record, "id")
    assert (ref.near, ref.far, ref.distance) == (-42, -80, 1)
    ref = calibration.resolve(args, record, "other")
    assert (ref.near, ref.far, ref.distance) == (-42, -72, 0.7)
    assert calibration.load(tmp_path / "missing") is None


@pytest.mark.parametrize(
    "content",
    [
        "{",
        '{"identifier":"id"}',
        json.dumps({"identifier": "id", "near": -90, "far": -72, "distance": 1}),
    ],
)
def test_bad_calibration_is_actionable(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content)
    with pytest.raises(FinderError, match="repair or remove"):
        calibration.load(path)


@pytest.mark.parametrize(
    "flags",
    [
        ["--sound"],
        ["--timeout", "nan"],
        ["--refresh", "0"],
        ["--near", "-80", "--far", "-72"],
        ["--near", "inf"],
        ["--calibrate", "id", "--near", "-40"],
        ["--hunt", ""],
    ],
)
def test_bad_cli(flags):
    with pytest.raises(SystemExit) as exc:
        cli.main(flags)
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "message,fragment",
    [
        ("powered_off", "Bluetooth is off"),
        ("permission denied", "permission denied"),
        ("no adapter", "No BLE-capable"),
        ("unknown", "scan failed"),
    ],
)
def test_adapter_errors(message, fragment):
    assert fragment in cli.bluetooth_error(RuntimeError(message))


def test_terminal_control_characters_are_sanitized():
    assert "\x1b" not in output.safe("name\x1b[2J\n")


class Clock:
    def __init__(self):
        self.now = 0
        self.on_sleep = lambda: None

    def __call__(self):
        return self.now

    async def sleep(self, amount):
        self.now += amount
        self.on_sleep()


class Scanner:
    def __init__(self, callback, fail=False):
        self.callback = callback
        self.closed = False
        self.fail = fail

    async def __aenter__(self):
        if self.fail:
            raise RuntimeError("powered off")
        return self

    async def __aexit__(self, *args):
        self.closed = True

    def emit(self, identifier="id", name="Phone", rssi=-40):
        self.callback(
            SimpleNamespace(address=identifier), SimpleNamespace(local_name=name, rssi=rssi)
        )


def test_missing_target_exits_and_scanner_closes(tmp_path):
    clock = Clock()
    scanner = Scanner(None)

    def factory(detection_callback):
        scanner.callback = detection_callback
        return scanner

    with pytest.raises(FinderError, match="not seen"):
        asyncio.run(
            cli.run(
                options(tmp_path, "--hunt", "missing", "--startup-timeout", "0.1"),
                factory,
                clock,
                clock.sleep,
            )
        )
    assert scanner.closed


def test_hunt_updates_loss_reacquisition_and_cleanup(tmp_path, capsys):
    clock = Clock()
    scanner = Scanner(None)

    def factory(detection_callback):
        scanner.callback = detection_callback
        scanner.emit()
        return scanner

    def tick():
        if 0.2 < clock.now < 0.3:
            scanner.emit(rssi=-70)
        if clock.now > 0.4:
            raise KeyboardInterrupt

    clock.on_sleep = tick
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(
            cli.run(
                options(tmp_path, "--hunt", "id", "--timeout", "0.1"), factory, clock, clock.sleep
            )
        )
    result = capsys.readouterr().out
    assert "Tracking" in result and "Target lost" in result and "Reacquired" in result
    assert scanner.closed


def test_calibration_samples_and_saves(tmp_path, monkeypatch):
    clock = Clock()
    scanner = Scanner(None)
    monkeypatch.setattr("builtins.input", lambda _: "")

    def factory(detection_callback):
        scanner.callback = detection_callback
        return scanner

    last_sample = [-1.0]

    def tick():
        if clock.now - last_sample[0] >= 0.3:
            scanner.emit(rssi=-40 if clock.now < 2 else -50)
            last_sample[0] = clock.now

    clock.on_sleep = tick
    args = options(tmp_path, "--calibrate", "id", "--reference-distance", "1")
    assert asyncio.run(cli.run(args, factory, clock, clock.sleep)) == 0
    record = calibration.load(args.calibration_file)
    assert record.identifier == "id"
    assert -50 < record.near < -40
    assert record.distance == 1
    assert scanner.closed


def test_callback_ambiguity_reaches_cli_and_cleans_up(tmp_path):
    clock = Clock()
    scanner = Scanner(None)

    def factory(detection_callback):
        scanner.callback = detection_callback
        scanner.emit("one")
        scanner.emit("two")
        return scanner

    with pytest.raises(FinderError, match="Several"):
        asyncio.run(cli.run(options(tmp_path, "--hunt", "Phone"), factory, clock, clock.sleep))
    assert scanner.closed


def test_audio_cadence_and_stop(monkeypatch):
    emitted = []

    class Process:
        returncode = 0

        async def wait(self):
            return self.returncode

    async def spawn(*args, **kwargs):
        emitted.append(args)
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def scenario():
        sound = Audio()
        sound.command = ["test-player"]
        d = Device("id")
        d.receive(-72, 0, 10)
        await sound.update(d, 0, 10, Reference())
        await sound.update(d, 1, 10, Reference())
        assert len(emitted) == 1
        await sound.update(d, 2, 10, Reference())
        assert len(emitted) == 2
        await sound.update(d, 10, 10, Reference())
        assert sound.active_key is None
        assert sound.process is None
        assert len(emitted) == 2

    asyncio.run(scenario())


def test_macos_native_abort_is_actionable(monkeypatch, capsys):
    class Process:
        def wait(self):
            return -6

    calls = []

    def launch(command, env):
        calls.append((command, env))
        return Process()

    monkeypatch.setattr(cli.subprocess, "Popen", launch)
    assert cli.guarded_macos(["--hunt", "id"]) == 1
    assert "Privacy & Security" in capsys.readouterr().err
    assert calls[0][1]["BLE_FINDER_WORKER"] == "1"
    assert calls[0][0][-2:] == ["--hunt", "id"]


def test_macos_guard_preserves_normal_exit(monkeypatch):
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: SimpleNamespace(wait=lambda: 2))
    assert cli.guarded_macos([]) == 2


def test_macos_guard_interrupt_stops_worker(monkeypatch):
    class Process:
        stopped = False
        calls = 0

        def wait(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            if self.calls == 2:
                raise cli.subprocess.TimeoutExpired("worker", timeout)
            return 0

        def terminate(self):
            self.stopped = True

    process = Process()
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: process)
    assert cli.guarded_macos([]) == 130
    assert process.stopped


def test_audio_failure_and_missing_player(monkeypatch):
    async def fail(*args, **kwargs):
        raise OSError("missing")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail)

    async def scenario():
        d = Device("id")
        d.receive(-45, 0, 10)
        sound = Audio()
        sound.command = ["missing-player"]
        with pytest.raises(FinderError, match="Cannot start audio"):
            await sound.update(d, 0, 10, Reference())

    asyncio.run(scenario())
    monkeypatch.setattr("ble_finder.audio.shutil.which", lambda _: None)
    monkeypatch.setattr("ble_finder.audio.sys.platform", "linux")
    with pytest.raises(FinderError, match="Audio unavailable"):
        asyncio.run(Audio().__aenter__())


def test_calibration_lost_and_insufficient_data(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    for timeout, message in [("0.1", "lost during calibration"), ("10", "Too few")]:
        clock = Clock()
        scanner = Scanner(None)

        def factory(detection_callback, scanner=scanner):
            scanner.callback = detection_callback
            scanner.emit()
            return scanner

        with pytest.raises(FinderError, match=message):
            asyncio.run(
                cli.run(
                    options(tmp_path, "--calibrate", "id", "--timeout", timeout),
                    factory,
                    clock,
                    clock.sleep,
                )
            )
        assert scanner.closed
        assert not (tmp_path / "calibration.json").exists()


def test_windows_audio_stops_on_loss(monkeypatch):
    import sys

    calls = []
    monkeypatch.setitem(
        sys.modules, "winsound", SimpleNamespace(PlaySound=lambda *args: calls.append(args))
    )

    async def scenario():
        sound = Audio()
        sound.windows = True
        await sound.update(None, 1, 10, None)

    asyncio.run(scenario())
    assert calls == [(None, 0)]


def test_survey_refresh_and_cleanup(tmp_path, capsys):
    clock = Clock()
    scanner = Scanner(None)

    def factory(detection_callback):
        scanner.callback = detection_callback
        scanner.emit(name="Visible")
        return scanner

    def tick():
        if clock.now > 0.2:
            raise KeyboardInterrupt

    clock.on_sleep = tick
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(
            cli.run(
                options(tmp_path, "--refresh", "0.1", "--timeout", "0.1"),
                factory,
                clock,
                clock.sleep,
            )
        )
    text = capsys.readouterr().out
    assert "Visible" in text
    assert "No advertisements received recently" in text
    assert scanner.closed


def test_saved_references_allow_partial_flag_override(tmp_path):
    args = options(tmp_path, "--hunt", "id", "--near", "-80")
    cli.validate(args, cli.parser())
    ref = calibration.resolve(args, calibration.Calibration("id", -70, -90, 1), "id")
    assert ref.near == -80 and ref.far == -90


def test_main_translates_backend_errors(monkeypatch, tmp_path, capsys):
    from bleak.exc import BleakBluetoothNotAvailableError, BleakBluetoothNotAvailableReason

    monkeypatch.setenv("BLE_FINDER_WORKER", "1")

    async def fail(*args):
        raise BleakBluetoothNotAvailableError(BleakBluetoothNotAvailableReason.POWERED_OFF, "off")

    monkeypatch.setattr(cli, "run", fail)
    assert cli.main(["--calibration-file", str(tmp_path / "missing")]) == 1
    assert "Bluetooth is off" in capsys.readouterr().err


def test_audio_cleanup_terminates_live_player():
    class Process:
        returncode = None

        def terminate(self):
            self.returncode = -15

        async def wait(self):
            return self.returncode

    async def scenario():
        sound = Audio()
        process = Process()
        sound.process = process
        await sound.stop()
        assert process.returncode == -15
        assert sound.process is None

    asyncio.run(scenario())


def test_calibrated_sound_distinguishes_near_positions():
    ref = Reference(near=-58.1, far=-72, distance=1)
    assert ref.interval(-80) == 2
    assert ref.interval(-58.1) == pytest.approx(0.8)
    assert ref.interval(-50) == pytest.approx(0.557)
    assert ref.interval(-40) == pytest.approx(0.257)
    assert ref.interval(-30) == pytest.approx(0.2)
    values = [ref.interval(rssi) for rssi in range(-90, -20)]
    assert values == sorted(values, reverse=True)


def test_verbose_hunt_shows_cadence_and_small_distance(capsys):
    d = Device("test-id")
    d.receive(-30, 0, 10)
    output.hunt(d, Reference(near=-58.1, distance=1), verbose=True, sound=True)
    text = capsys.readouterr().out
    assert "beep every 0.20s (5.0/s)" in text
    assert "<0.1 m" in text and "~0.0 m" not in text


def test_audio_adapts_pending_beep_to_signal_changes(monkeypatch):
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def scenario():
        sound = Audio()
        sound.command = ["test-player"]
        d = Device("id")
        ref = Reference(near=-58.1)
        d.receive(-80, 0, 10)
        await sound.update(d, 0, 10, ref)
        d.samples.clear()
        d.samples.append(-30)
        d.receive(-30, 0.1, 10)
        await sound.update(d, 0.25, 10, ref)
        assert len(calls) == 2
        d.samples.clear()
        d.samples.append(-80)
        d.receive(-80, 0.3, 10)
        await sound.update(d, 0.5, 10, ref)
        assert len(calls) == 2
        await sound.update(d, 2.3, 10, ref)
        assert len(calls) == 3

    asyncio.run(scenario())
