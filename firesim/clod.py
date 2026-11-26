"""Turn observed CloD events into explicit mission-authored ignition pulses."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class IgnitionProfile:
    radius_m: float
    exposure_kj_m2: float

    def __post_init__(self):
        if not all(math.isfinite(v) and v > 0 for v in (self.radius_m, self.exposure_kj_m2)):
            raise ValueError("Ignition radius and exposure must be finite and positive")

    def apply(self, sim, east, north, event_id):
        return sim.ignite(east, north, self.radius_m, self.exposure_kj_m2, event_id)


@dataclass(frozen=True)
class StorageSite:
    east: float
    north: float
    kind: str
    secondary: IgnitionProfile
    stationary_name: str | None = None
    building_title: str | None = None

    def __post_init__(self):
        if self.kind not in ("fuel_store", "ammo_store"):
            raise ValueError("Invalid storage fuel type")
        if not all(math.isfinite(v) for v in (self.east, self.north)):
            raise ValueError("Invalid storage site position")
        if not self.stationary_name and not self.building_title:
            raise ValueError("Storage site needs an exact callback name or title")

    def prepare(self, sim):
        """Set up a new mission's authored fuel deposit before processing events."""
        sim.paint(math.floor(self.east / sim.cell_size), math.floor(self.north / sim.cell_size), self.kind)


class ClodEventIngestor:
    def __init__(self, bomb_profiles, storage_sites, ground_height, *, ground_tolerance_m=5.0):
        if not math.isfinite(ground_tolerance_m) or ground_tolerance_m < 0:
            raise ValueError("Ground tolerance must be finite and non-negative")
        self.bomb_profiles = bomb_profiles
        self.storage_sites = storage_sites
        self.ground_height = ground_height
        self.ground_tolerance_m = ground_tolerance_m

    def feed(self, record, sim):
        if record.get("schema") != 1 or record.get("source") != "clod-probe":
            return "ignored-source"
        kind = record.get("kind")
        if kind not in ("bomb_explosion", "stationary_killed", "building_killed"):
            return "ignored-event"
        session, sequence = record.get("session"), record.get("sequence")
        if not isinstance(session, str) or not session or type(sequence) is not int or sequence < 1:
            raise ValueError("Missing CloD event identity")
        profile = None
        if kind == "bomb_explosion":
            profile = self.bomb_profiles.get(record.get("title"))
            if profile is None:
                return "unmapped-munition"
            if f"clod:{session}:bomb:{sequence}" in sim.event_ids:
                return "duplicate"
        pos = record.get("position_raw", {})
        if not isinstance(pos, dict):
            raise ValueError("Missing CloD position")
        x, y, z = (pos.get(axis) for axis in ("x", "y", "z"))
        if not all(type(v) in (float, int) and math.isfinite(v) for v in (x, y, z)):
            raise ValueError("Missing or non-finite CloD position")
        if not (0 <= x < sim.width * sim.cell_size and 0 <= y < sim.height * sim.cell_size):
            return "outside-map"

        if profile is not None:
            ground = self.ground_height(x, y)
            if ground is None or not math.isfinite(ground):
                return "unknown-ground-height"
            if abs(z - ground) > self.ground_tolerance_m:
                return "outside-ground-tolerance"
            profile.apply(sim, x, y, f"clod:{session}:bomb:{sequence}")
            return "bomb-ignition"

        # Multiple objects may share a building title, and one object may
        # have two callback aliases. Use the uniquely located site's ID.
        selector = "stationary_name" if kind == "stationary_killed" else "building_title"
        observed = record.get("name" if kind == "stationary_killed" else "title")
        matches = [(key, site) for key, site in self.storage_sites.items()
                   if observed and observed == getattr(site, selector)
                   and math.hypot(site.east - x, site.north - y) <= 2]
        if len(matches) != 1:
            return "unmapped-storage"
        key, site = matches[0]
        event_id = f"clod:{session}:storage:{key}"
        if event_id in sim.event_ids:
            return "duplicate"
        index = sim.index(math.floor(site.east / sim.cell_size), math.floor(site.north / sim.cell_size))
        if sim.cells[index].kind != site.kind:
            return "storage-fuel-unprepared"
        site.secondary.apply(sim, site.east, site.north, event_id)
        return "storage-ignition"


class ClodPumpTracker:
    """Match one known towing vehicle from the probe's single-player telemetry."""

    def __init__(self, session, actor_name, actor_type, *, stop_m_s=0.5, max_gap_s=2.5):
        if not (math.isfinite(stop_m_s) and stop_m_s >= 0 and math.isfinite(max_gap_s) and max_gap_s > 0):
            raise ValueError("Invalid telemetry thresholds")
        self.session, self.actor_name, self.actor_type = session, actor_name, actor_type
        self.stop_m_s, self.max_gap_s = stop_m_s, max_gap_s
        self.last = None

    def feed(self, line):
        _, marker, payload = line.partition("GROUNDFIRE_RESPONSE ")
        if not marker:
            return None
        parts = payload.strip().split("\t")
        if len(parts) != 9 or (parts[0], parts[2], parts[3], parts[4]) != (
                self.session, "vehicle", self.actor_name, self.actor_type):
            return None
        seconds, east, north = map(float, (parts[1], parts[5], parts[6]))
        pos = (east, north)
        if not all(math.isfinite(v) for v in (seconds, east, north)) or seconds < 0:
            raise ValueError("Invalid ground vehicle telemetry")
        if self.last is None:
            self.last = (seconds, pos)
            return 0.0, pos, False
        previous_seconds, previous_pos = self.last
        elapsed = seconds - previous_seconds
        if elapsed <= 0:
            return None
        self.last = (seconds, pos)
        if elapsed > self.max_gap_s:
            return 0.0, pos, False
        return elapsed, pos, math.dist(pos, previous_pos) / elapsed <= self.stop_m_s
