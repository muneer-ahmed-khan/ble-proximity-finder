import asyncio
import math
import shutil
import struct
import sys
import tempfile
import wave
from pathlib import Path

from .model import FinderError


class Audio:
    def __init__(self):
        self.process = None
        self.directory = None
        self.next_beep = 0
        self.last_beep = None
        self.command = None
        self.windows = False
        self.active_key = None

    async def __aenter__(self):
        if sys.platform == "win32":
            self.windows = True
            return self
        player = shutil.which("afplay" if sys.platform == "darwin" else "aplay")
        if not player:
            raise FinderError("Audio unavailable. Install aplay on Linux or run without --sound.")
        self.directory = tempfile.TemporaryDirectory(prefix="ble-finder-")
        path = Path(self.directory.name) / "click.wav"
        rate = 22050
        frames = b"".join(
            struct.pack("<h", int(9000 * math.sin(2 * math.pi * 1100 * i / rate) * (1 - i / 1102)))
            for i in range(1102)
        )
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(frames)
        self.command = (
            [player, str(path)] if sys.platform == "darwin" else [player, "-q", str(path)]
        )
        return self

    async def stop(self):
        self.next_beep = 0
        self.last_beep = None
        self.active_key = None
        if self.windows:
            import winsound

            winsound.PlaySound(None, 0)
        if self.process is not None:
            if self.process.returncode is None:
                self.process.terminate()
            await self.process.wait()
            self.process = None

    async def update(self, device, now, timeout, reference):
        if device is None or not device.alive(now, timeout):
            await self.stop()
            return
        key = (device.identifier, device.generation)
        if self.active_key != key:
            self.active_key = key
            self.next_beep = now
            self.last_beep = None
        if self.last_beep is not None:
            self.next_beep = self.last_beep + reference.interval(device.smoothed)
        if self.process is not None:
            if self.process.returncode is None:
                return
            if self.process.returncode != 0:
                raise FinderError("Audio playback failed; check the sound output or omit --sound.")
            self.process = None
        if now < self.next_beep:
            return
        if self.windows:
            import winsound

            winsound.PlaySound("SystemDefault", winsound.SND_ALIAS | winsound.SND_ASYNC)
        else:
            try:
                self.process = await asyncio.create_subprocess_exec(
                    *self.command,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except OSError as exc:
                raise FinderError(
                    "Cannot start audio playback; check the player or omit --sound."
                ) from exc
        self.last_beep = now
        self.next_beep = now + reference.interval(device.smoothed)

    async def __aexit__(self, *args):
        await self.stop()
        if self.windows:
            import winsound

            winsound.PlaySound(None, 0)
        if self.directory:
            self.directory.cleanup()
