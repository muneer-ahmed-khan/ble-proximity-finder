import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .model import FinderError, Reference


@dataclass(frozen=True)
class Calibration:
    identifier: str
    near: float
    far: float
    distance: float

    def __post_init__(self):
        if not isinstance(self.identifier, str) or not self.identifier:
            raise ValueError("Calibration identifier is missing.")
        Reference(self.near, self.far, self.distance)


def default_path():
    return Path.home() / ".ble-finder" / "calibration.json"


def load(path):
    try:
        return Calibration(**json.loads(path.read_text()))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        raise FinderError(f"Cannot read calibration at {path}; repair or remove the file.") from exc


def save(path, calibration):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(asdict(calibration), handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except OSError as exc:
        raise FinderError(
            f"Cannot save calibration at {path}; check directory permissions."
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def resolve(args, calibration=None, identifier=None):
    matched = calibration is not None and calibration.identifier == identifier

    def value(option, saved, fallback):
        explicit = getattr(args, option)
        if explicit is not None:
            return explicit
        return getattr(calibration, saved) if matched else fallback

    return Reference(
        value("near", "near", -45),
        value("far", "far", -72),
        value("reference_distance", "distance", 0.7),
        args.path_loss,
    )
