"""Deterministic, fixed-step, lumped fire model. Not a calibrated fire predictor.

Lengths: m; mass: kg; heat exposure: kJ/m²; incident flux: kW/m²;
wind: local east/north velocity in m/s. Visual/game adapters own no physics.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
import math
import random


@dataclass(frozen=True)
class Fuel:
    load: float  # dry kg/m²
    ignition: float  # nominal exposure threshold, kJ/m²
    burn_rate: float  # kg/m²/s
    moisture: float
    surviving_structure: float = 0.0
    smoke_yield: float = 0.08
    heat_yield: float = 18000.0  # kJ/kg in this prototype


FUELS = {
    "water": Fuel(0, 1, 0, 1),
    "road": Fuel(0, 1, 0, 0),
    "grass": Fuel(0.6, 32, 0.018, 0.10),
    "woodland": Fuel(2.8, 65, 0.035, 0.18),
    "hedgerow": Fuel(2.6, 50, 0.042, 0.14),
    "timber": Fuel(7.0, 110, 0.060, 0.12, 0.05, 0.12),
    "masonry": Fuel(4.0, 150, 0.040, 0.15, 0.60, 0.10),
    "factory": Fuel(8.5, 125, 0.045, 0.12, 0.45, 0.13),
    "fuel_store": Fuel(15.0, 75, 0.085, 0.03, 0.10, 0.18, 24000.0),
    "ammo_store": Fuel(9.0, 105, 0.070, 0.08, 0.15, 0.12, 20000.0),
}


@dataclass
class Cell:
    kind: str
    fuel: float  # remaining dry kg
    initial_fuel: float
    moisture: float
    heat: float = 0.0
    wetness: float = 0.0  # deposited water kg/m²
    intensity: float = 0.0  # normalized flaming fraction
    integrity: float = 1.0
    state: str = "unburned"
    elevation: float = 0.0
    object_id: str | None = None
    smoke_rate: float = 0.0  # kg/s proxy


@dataclass(frozen=True)
class EmberLanding:
    source_east: float
    source_north: float
    landing_east: float
    landing_north: float


class FireSim:
    schema = 1
    fixed_ns = 500_000_000
    ember_visual_limit = 32
    ember_event_limit = 128
    ember_reference_cell_m = 10.0

    def __init__(self, width: int, height: int, cell_size: float = 10.0, seed: int = 7):
        if not (1 <= width <= 512 and 1 <= height <= 512 and math.isfinite(cell_size) and cell_size > 0):
            raise ValueError("Invalid grid dimensions/cell size")
        self.width, self.height, self.cell_size = width, height, cell_size
        self.seed = seed
        self.rng = random.Random(seed)
        self.cells = [self.make_cell("grass") for _ in range(width * height)]
        self.active: set[int] = set()
        self.wind_east = 3.0
        self.wind_north = 0.0
        self.rain_mm_h = 0.0
        self.ambient_c = 20.0
        self.embers_enabled = True
        self.spot_rate = 0.006  # expected spotting events/s per 100 m² at full intensity
        self.spotting_model = "per_area"
        self.ember_landings: list[EmberLanding] = []
        self.tick = 0
        self.accumulator_ns = 0
        self.ignitions = 0
        self.consumed_kg = 0.0
        self.event_ids: set[str] = set()

    @property
    def time(self):
        return self.tick * self.fixed_ns / 1e9

    @property
    def area(self):
        return self.cell_size ** 2

    def make_cell(self, kind: str, moisture: float | None = None, fuel_load: float | None = None, **kwargs):
        f = FUELS[kind]
        load = f.load if fuel_load is None else fuel_load
        if not math.isfinite(load) or load < 0:
            raise ValueError("Fuel load must be finite dry kg/m² >= 0")
        mass = load * self.area
        m = f.moisture if moisture is None else moisture
        if not math.isfinite(m) or not 0 <= m <= 2:
            raise ValueError("Fuel moisture must be a dry-mass ratio in [0, 2]")
        return Cell(kind, mass, mass, m, **kwargs)

    def index(self, x: int, y: int):
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError((x, y))
        return y * self.width + x

    def paint(self, x: int, y: int, kind: str, **kwargs):
        i = self.index(x, y)
        self.cells[i] = self.make_cell(kind, **kwargs)
        self.active.discard(i)

    def center(self, i: int):
        return ((i % self.width + 0.5) * self.cell_size, (i // self.width + 0.5) * self.cell_size)

    def ignite(self, east: float, north: float, radius: float = 12, exposure: float = 500,
               event_id: str | None = None, *, seed_impact_cell: bool = False):
        """Seed an exposure pulse. An HE damage report is only an ignition proxy."""
        self._finite(east, north, radius, exposure)
        if radius <= 0 or exposure < 0:
            raise ValueError("Invalid ignition radius/exposure")
        if event_id is not None:
            if event_id in self.event_ids:
                return 0
            self.event_ids.add(event_id)
        count = 0
        for i, weight in self._footprint(east, north, radius, seed_impact_cell=seed_impact_cell):
            c = self.cells[i]
            if c.fuel <= 0:
                continue
            c.heat += exposure * weight
            self.active.add(i)
            count += 1
        return count

    def suppress(self, east: float, north: float, radius: float = 20, water_kg: float = 1500):
        """Distribute finite water. Suppression preserves unconsumed dry fuel."""
        self._finite(east, north, radius, water_kg)
        if radius <= 0 or water_kg < 0:
            raise ValueError("Invalid suppression radius/water mass")
        footprint = list(self._footprint(east, north, radius))
        total = sum(w for _, w in footprint)
        if not total:
            return 0
        for i, w in footprint:
            c = self.cells[i]
            water = water_kg * w / total / self.area
            c.wetness += water
            c.heat = max(0, c.heat - water * 2260)
            c.intensity *= math.exp(-water * 4)
            self.active.add(i)
        return water_kg

    @staticmethod
    def _finite(*values):
        if any(not math.isfinite(v) for v in values):
            raise ValueError("Non-finite input")

    def _footprint(self, east, north, radius, *, seed_impact_cell=False):
        impact = (math.floor(east / self.cell_size), math.floor(north / self.cell_size)) if seed_impact_cell else None
        lo_x = max(0, math.floor((east - radius) / self.cell_size))
        hi_x = min(self.width - 1, math.floor((east + radius) / self.cell_size))
        lo_y = max(0, math.floor((north - radius) / self.cell_size))
        hi_y = min(self.height - 1, math.floor((north + radius) / self.cell_size))
        for y in range(lo_y, hi_y + 1):
            for x in range(lo_x, hi_x + 1):
                i = self.index(x, y)
                if (x, y) == impact:
                    yield i, 1.0
                    continue
                e, n = self.center(i)
                d = math.hypot(e - east, n - north)
                if d <= radius:
                    yield i, max(0.1, 1 - d / radius)

    def step(self, seconds: float):
        self._finite(seconds)
        if not 0 <= seconds <= 3600:
            raise ValueError("step duration must be in [0, 3600] seconds")
        self._finite(self.wind_east, self.wind_north, self.rain_mm_h, self.spot_rate, self.ambient_c)
        if self.rain_mm_h < 0:
            raise ValueError("Rain cannot be negative")
        self.ember_landings.clear()
        self.accumulator_ns += round(seconds * 1e9)
        while self.accumulator_ns >= self.fixed_ns:
            self._tick(self.fixed_ns / 1e9)
            self.accumulator_ns -= self.fixed_ns

    def _tick(self, dt):
        # Freeze all source intensities before any target changes: no scan-order spread.
        drying = self._surface_drying_rate()
        flux: dict[int, float] = {}
        candidates = set(self.active)
        speed = math.hypot(self.wind_east, self.wind_north)
        sources = [(i, self.cells[i]) for i in sorted(self.active)]
        spotting = self.embers_enabled and speed > 0.25
        use_area = spotting and self.spotting_model == "per_area" and self.spot_rate > 0
        use_legacy = spotting and self.spotting_model == "legacy_cell"
        ember_sources: list[int] = []
        cumulative_intensity: list[float] = []
        total_intensity = 0.0
        for i, c in sources:
            intensity = c.intensity
            if c.state != "flaming" or intensity <= 0.005:
                continue
            f = FUELS[c.kind]
            emitted = f.burn_rate * f.heat_yield * 0.15 * intensity / (1 + 3 * c.moisture)
            x, y = i % self.width, i // self.width
            transfers = []
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if not (dx or dy) or not (0 <= x + dx < self.width and 0 <= y + dy < self.height):
                        continue
                    j = self.index(x + dx, y + dy)
                    neighbor = self.cells[j]
                    if neighbor.fuel <= 0:
                        continue
                    dist = math.hypot(dx, dy)
                    directional = (dx * self.wind_east + dy * self.wind_north) / dist
                    slope = (neighbor.elevation - c.elevation) / (dist * self.cell_size)
                    factor = math.exp(max(-1.5, min(1.5, 0.18 * directional + 2 * slope)))
                    transfers.append((j, 0.055 * factor / (dist * dist)))
            normalization = max(1.0, sum(w for _, w in transfers) / 0.6)
            for j, w in transfers:
                flux[j] = flux.get(j, 0) + emitted * w / normalization
                candidates.add(j)
            if use_area:
                total_intensity += intensity
                ember_sources.append(i)
                cumulative_intensity.append(total_intensity)
            elif use_legacy and self.rng.random() < -math.expm1(-self.spot_rate * intensity * dt):
                angle = math.atan2(self.wind_north, self.wind_east) + self.rng.gauss(0, 0.2)
                distance = self.cell_size * self.rng.uniform(2, 4 + min(speed, 12))
                tx = round(x + math.cos(angle) * distance / self.cell_size)
                ty = round(y + math.sin(angle) * distance / self.cell_size)
                if 0 <= tx < self.width and 0 <= ty < self.height:
                    j = self.index(tx, ty)
                    self._deposit_ember(i, j, self.center(j), dt, flux, candidates)

        if ember_sources:
            self._sample_embers(ember_sources, cumulative_intensity, speed, dt, flux, candidates)

        candidates.update(self._weather_indices())
        next_active = set()
        for i in sorted(candidates):
            c = self.cells[i]
            f = FUELS[c.kind]
            c.smoke_rate = 0.0
            if c.initial_fuel <= 0:
                c.heat = c.intensity = c.wetness = 0.0
                c.state = "unburned"
                continue
            if self.rain_mm_h:
                c.wetness += self.rain_mm_h / 3600 * dt
            c.wetness = max(0, c.wetness - (drying + 0.003 * c.intensity) * dt)
            c.heat = max(0, c.heat * math.exp(-0.012 * dt) + flux.get(i, 0) * dt)
            threshold = f.ignition * (1 + 5 * c.moisture + 2 * min(c.wetness, 5))
            if c.fuel <= 1e-7:
                c.fuel = c.intensity = 0.0
                c.state = "burned"
            else:
                can_flame = c.wetness < 0.35 and c.moisture < 0.65
                if c.state in ("unburned", "heating") and c.heat >= threshold and can_flame:
                    c.state = "flaming"
                    c.intensity = max(c.intensity, 0.12)
                    self.ignitions += 1
                if c.state == "flaming":
                    if not can_flame:
                        c.state = "heating" if c.heat > 1 else "unburned"
                        c.intensity = 0.0
                    else:
                        target = min(1, 4 * c.fuel / c.initial_fuel) / (1 + 2 * c.wetness)
                        c.intensity += (target - c.intensity) * -math.expm1(-dt / 7)
                        amount = min(c.fuel, f.burn_rate * self.area * c.intensity * dt / (1 + 3 * c.moisture))
                        self._consume(c, f, amount)
                        c.heat = max(c.heat, threshold * 1.1)
                        c.smoke_rate = amount / dt * f.smoke_yield
                        if c.fuel < 0.12 * c.initial_fuel:
                            c.state = "smoldering"
                            c.intensity = 0.0
                elif c.state == "smoldering":
                    amount = min(c.fuel, 0.0015 * self.area * dt / (1 + c.wetness * 10))
                    self._consume(c, f, amount)
                    c.smoke_rate = amount / dt * f.smoke_yield * 1.8
                    if c.wetness > 0.5:
                        c.state = "heating" if c.heat > 1 else "unburned"
                else:
                    c.state = "heating" if c.heat > 1 else "unburned"
                    c.intensity = 0.0
            if c.state in ("flaming", "smoldering") or c.heat > 0.01 or c.wetness > 0:
                next_active.add(i)
        self.active = next_active
        self.tick += 1

    def _sample_embers(self, sources, cumulative_intensity, speed, dt, flux, candidates):
        total = cumulative_intensity[-1]
        reference_m = self.ember_reference_cell_m
        mean = self.spot_rate * (self.area / reference_m**2) * dt * total
        heading = math.atan2(self.wind_north, self.wind_east)
        max_distance_m = reference_m * (4 + min(speed, 12))
        arrival = 0.0
        # Unit-rate exponential arrivals produce a Poisson event count on [0, mean].
        # Sampling a source by its share retains the relative rates of all burning cells.
        for _ in range(self.ember_event_limit):
            arrival += self.rng.expovariate(1.0)
            if arrival >= mean:
                break
            source_index = bisect_right(cumulative_intensity, self.rng.random() * total)
            i = sources[min(source_index, len(sources) - 1)]
            east, north = self.center(i)
            angle = heading + self.rng.gauss(0, 0.2)
            distance = self.rng.uniform(2 * reference_m, max_distance_m)
            landing = east + distance * math.cos(angle), north + distance * math.sin(angle)
            tx = math.floor(landing[0] / self.cell_size)
            ty = math.floor(landing[1] / self.cell_size)
            if 0 <= tx < self.width and 0 <= ty < self.height:
                self._deposit_ember(i, self.index(tx, ty), landing, dt, flux, candidates)

    def _deposit_ember(self, source, receiver, landing, dt, flux, candidates):
        if self.cells[receiver].fuel <= 0:
            return
        flux[receiver] = flux.get(receiver, 0) + 150 / dt
        candidates.add(receiver)
        if len(self.ember_landings) < self.ember_visual_limit:
            self.ember_landings.append(EmberLanding(*self.center(source), *landing))

    def _surface_drying_rate(self):
        # Prototype temperature sensitivity for surface water, independent of fuel moisture.
        return 0.0007 * 1.5 ** ((max(-30.0, min(60.0, self.ambient_c)) - 20) / 10)

    def _weather_indices(self):
        """Storage-specific coverage for background weather, before cell updates."""
        return range(len(self.cells)) if self.rain_mm_h else ()

    def _consume(self, c, f, amount):
        c.fuel = max(0.0, c.fuel - amount)
        self.consumed_kg += amount
        burned_fraction = 1 - c.fuel / c.initial_fuel
        c.integrity = max(f.surviving_structure, 1 - burned_fraction * (1 - f.surviving_structure))

    def stats(self):
        states = {k: 0 for k in ("unburned", "heating", "flaming", "smoldering", "burned")}
        for c in self.cells:
            states[c.state] += 1
        return {"time": self.time, **states, "ignitions": self.ignitions, "consumed_kg": self.consumed_kg,
                "remaining_kg": sum(c.fuel for c in self.cells), "smoke_kg_s": sum(c.smoke_rate for c in self.cells)}

    def snapshot(self):
        return {"schema": self.schema, "width": self.width, "height": self.height, "cell_size": self.cell_size,
                "seed": self.seed, "cells": [asdict(c) for c in self.cells], "active": sorted(self.active),
                "wind_east": self.wind_east, "wind_north": self.wind_north, "rain_mm_h": self.rain_mm_h,
                "ambient_c": self.ambient_c,
                "embers_enabled": self.embers_enabled, "spot_rate": self.spot_rate,
                "spotting_model": self.spotting_model, "tick": self.tick,
                "accumulator_ns": self.accumulator_ns, "ignitions": self.ignitions, "consumed_kg": self.consumed_kg,
                "event_ids": sorted(self.event_ids), "rng_state": self.rng.getstate()}

    @classmethod
    def restore(cls, data):
        if data.get("schema") != cls.schema:
            raise ValueError("Unsupported snapshot schema")
        obj = cls(data["width"], data["height"], data["cell_size"], data["seed"])
        if len(data["cells"]) != len(obj.cells):
            raise ValueError("Snapshot cell count mismatch")
        obj.cells = [Cell(**c) for c in data["cells"]]
        if any(c.kind not in FUELS or not math.isfinite(c.fuel) or c.fuel < 0 for c in obj.cells):
            raise ValueError("Invalid snapshot fuel")
        obj.active = set(data["active"])
        if any(not isinstance(i, int) or not 0 <= i < len(obj.cells) for i in obj.active):
            raise ValueError("Invalid active cell")
        for key in ("wind_east", "wind_north", "rain_mm_h", "embers_enabled", "spot_rate", "tick", "accumulator_ns", "ignitions", "consumed_kg"):
            setattr(obj, key, data[key])
        obj.event_ids = set(data["event_ids"])
        obj._restore_environment(data)
        return obj

    def _restore_environment(self, data):
        self.ambient_c = data.get("ambient_c", 20.0)
        self._finite(self.ambient_c)
        model = data.get("spotting_model", "legacy_cell")
        if model not in ("per_area", "legacy_cell"):
            raise ValueError("Unsupported spotting model")
        self.spotting_model = model

        def tuples(v):
            return tuple(map(tuples, v)) if isinstance(v, (list, tuple)) else v

        self.rng.setstate(tuples(data["rng_state"]))
