import math
from collections import deque
from dataclasses import dataclass, field
from statistics import mean


class FinderError(Exception):
    pass


@dataclass(frozen=True)
class Reference:
    near: float = -45
    far: float = -72
    distance: float = 0.7
    exponent: float = 2

    def __post_init__(self):
        values = (self.near, self.far, self.distance, self.exponent)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Reference values must be finite.")
        if not -127 <= self.far < self.near <= 20:
            raise ValueError("RSSI references must satisfy -127 <= far < near <= 20 dBm.")
        if self.distance <= 0 or self.exponent <= 0:
            raise ValueError("Reference distance and path-loss exponent must be positive.")

    def band(self, rssi):
        if rssi >= self.near:
            return "very close"
        return "same room" if rssi >= self.far else "far"

    def metres(self, rssi):
        power = (self.near - rssi) / (10 * self.exponent)
        if power > 300:
            return math.inf
        return self.distance * 10**power

    def interval(self, rssi):
        if rssi <= self.near:
            fraction = max(0, (rssi - self.far) / (self.near - self.far))
            return 2 - 1.2 * fraction
        fraction = min(1, (rssi - self.near) / 20)
        return 0.8 - 0.6 * fraction


@dataclass
class Device:
    identifier: str
    name: str | None = None
    last_seen: float = 0
    raw_rssi: int = 0
    raw_count: int = 0
    accepted_count: int = 0
    changed_count: int = 0
    samples: deque = field(default_factory=lambda: deque(maxlen=5))
    generation: int = 0

    @property
    def smoothed(self):
        return mean(self.samples)

    def receive(self, rssi, now, timeout, name=None):
        old = self.raw_rssi
        gap = now - self.last_seen
        restarted = not self.samples or gap >= timeout
        duplicate = not restarted and old == rssi and gap < 0.2
        self.raw_count += 1
        if restarted or old != rssi:
            self.changed_count += 1
        if restarted:
            self.samples.clear()
            self.generation += 1
        self.last_seen = now
        self.raw_rssi = rssi
        if name:
            self.name = name
        if duplicate:
            return False
        self.samples.append(rssi)
        self.accepted_count += 1
        return True

    def alive(self, now, timeout):
        return bool(self.samples) and now - self.last_seen < timeout


class Tracker:
    def __init__(self, timeout=10, target=None):
        self.timeout = timeout
        self.target = target
        self.selected = None
        self.devices = {}
        self.revision = 0

    def receive(self, identifier, name, rssi, now):
        if not isinstance(rssi, int) or not -127 <= rssi <= 20:
            return
        device = self.devices.setdefault(identifier, Device(identifier))
        accepted = device.receive(rssi, now, self.timeout, name)
        if self.target:
            candidates = [d for d in self.devices.values() if d.identifier == self.target]
            if not candidates:
                candidates = [d for d in self.devices.values() if d.name == self.target]
                if len(candidates) > 1:
                    raise FinderError(
                        "Several devices share that name. Run survey and use an identifier."
                    )
            if candidates and self.selected is None:
                self.selected = candidates[0].identifier
            if accepted and identifier == self.selected:
                self.revision += 1

    def live(self, now):
        stale = [
            key
            for key, d in self.devices.items()
            if key != self.selected and not d.alive(now, self.timeout)
        ]
        for key in stale:
            del self.devices[key]
        return sorted(
            (d for d in self.devices.values() if d.alive(now, self.timeout)),
            key=lambda d: (-d.smoothed, d.identifier),
        )

    def target_device(self):
        return self.devices.get(self.selected)
