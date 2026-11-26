"""Bounded effect projection and acknowledged, manifest-only game commands."""
from dataclasses import dataclass
import math
import re


@dataclass(frozen=True)
class Effect:
    sector: str
    mode: str  # small, large, smoke
    east: float
    north: float
    score: float


class EffectProjector:
    def __init__(self, sector_cells=4, budget=24):
        if sector_cells < 1 or budget < 1:
            raise ValueError("Invalid projection limits")
        self.sector_cells, self.budget = sector_cells, budget

    def desired(self, sim):
        buckets = {}
        for i in sorted(sim.active):
            c = sim.cells[i]
            if c.state not in ("flaming", "smoldering"):
                continue
            x, y = i % sim.width, i // sim.width
            sx, sy = x // self.sector_cells, y // self.sector_cells
            key = f"S{sx:03d}_{sy:03d}"
            b = buckets.setdefault(key, [sx, sy, 0.0, 0.0])
            b[2] = max(b[2], c.intensity if c.state == "flaming" else 0)
            b[3] += c.smoke_rate
        result = []
        for key, (sx, sy, fire, smoke) in buckets.items():
            mode = "large" if fire > 0.60 else "small" if fire > 0 else "smoke"
            e = min((sx + 0.5) * self.sector_cells, sim.width - 0.5) * sim.cell_size
            n = min((sy + 0.5) * self.sector_cells, sim.height - 0.5) * sim.cell_size
            result.append(Effect(key, mode, e, n, fire * 100 + smoke))
        result.sort(key=lambda v: (-v.score, v.sector))
        return {v.sector: v for v in result[:self.budget]}


@dataclass(frozen=True)
class Plume:
    sector: str
    east: float
    north: float
    ground_span_m: float
    flame_cells: int
    peak_intensity: float
    smoke_kg_s: float
    distance_m: float
    use_light: bool


class TheatrePlumeProjector:
    """Standalone visual slots for a moving observer. Physics stays at cell resolution."""

    def __init__(self, plume_budget=24, light_budget=4):
        if type(plume_budget) is not int or type(light_budget) is not int or not 0 <= light_budget <= plume_budget:
            raise ValueError("Invalid plume or light budget")
        self.plume_budget, self.light_budget = plume_budget, light_budget

    def desired(self, sim, observer_east, observer_north):
        if not all(math.isfinite(v) for v in (observer_east, observer_north)):
            raise ValueError("Invalid observer position")
        sectors = {}
        for index in sorted(sim.active):
            cell = sim.cells[index]
            if cell.state not in ("flaming", "smoldering"):
                continue
            east, north = sim.center(index)
            distance = math.hypot(east - observer_east, north - observer_north)
            side_cells = 8 if distance < 1500 else 32 if distance < 6000 else 128
            span = side_cells * sim.cell_size
            key = (side_cells, int(east // span), int(north // span))
            if key not in sectors:
                sectors[key] = []
            sectors[key].append((east, north, cell.intensity, cell.smoke_rate))

        ranked = []
        for (side_cells, x, y), cells in sectors.items():
            weights = [0.01 + intensity + smoke for _, _, intensity, smoke in cells]
            total = sum(weights)
            east = sum(cell[0] * weight for cell, weight in zip(cells, weights)) / total
            north = sum(cell[1] * weight for cell, weight in zip(cells, weights)) / total
            smoke = sum(cell[3] for cell in cells)
            flames = sum(cell[2] > 0 for cell in cells)
            peak = max(cell[2] for cell in cells)
            distance = math.hypot(east - observer_east, north - observer_north)
            priority = (peak + math.log1p(flames + smoke)) / (1 + distance / 2000)
            sector = f"P{side_cells}_{x}_{y}"
            ranked.append((priority, sector, east, north, side_cells * sim.cell_size,
                           flames, peak, smoke, distance))

        lights = self.light_budget
        result = []
        for _, sector, east, north, span, flames, peak, smoke, distance in sorted(
                ranked, key=lambda row: (-row[0], row[1]))[:self.plume_budget]:
            use_light = lights > 0 and distance < 1500 and peak >= 0.60
            lights -= use_light
            result.append(Plume(sector, east, north, span, flames, peak, smoke, distance, use_light))
        return result


class MemorySink:
    """Offline command recorder. Its acknowledgements are mock acknowledgements."""
    def __init__(self):
        self.commands = []

    def trigger(self, name):
        self.commands.append(f"serverinput {name}")


class IL2Adapter:
    def __init__(self, sink, manifest, projector=None):
        self.sink = sink
        self.manifest = manifest
        self.projector = projector or EffectProjector()
        self.current = {}
        self.damage_done = set()
        self.unmapped = set()

    def synchronize(self, sim):
        desired = self.projector.desired(sim)
        for sector in sorted(set(self.current) | set(desired)):
            new = desired[sector].mode if sector in desired else None
            old = self.current.get(sector)
            if new == old:
                continue
            mapping = self.manifest.get("sectors", {}).get(sector)
            if mapping is None:
                self.unmapped.add(sector)
                continue
            if old is not None:
                self.sink.trigger(mapping[f"stop_{old}"])
                # Commit each acknowledged action; a later failure must not pretend old FX remain.
                self.current.pop(sector, None)
            if new is not None:
                self.sink.trigger(mapping[f"start_{new}"])
                self.current[sector] = new
        for c in sim.cells:
            if c.object_id is None:
                continue
            mapping = self.manifest.get("damage", {}).get(c.object_id, {})
            for percent, name in sorted(mapping.items(), key=lambda v: int(v[0])):
                key = (c.object_id, int(percent))
                if key not in self.damage_done and (1 - c.integrity) * 100 >= int(percent):
                    self.sink.trigger(name)
                    self.damage_done.add(key)
        return desired

    def stop_all(self):
        for sector in sorted(list(self.current)):
            mode = self.current[sector]
            self.sink.trigger(self.manifest["sectors"][sector][f"stop_{mode}"])
            del self.current[sector]


def make_manifest(sim, sector_cells=4, prefix="GF"):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,15}", prefix):
        raise ValueError("Prefix must be a short mission-safe identifier")
    sectors = {}
    for sy in range(math.ceil(sim.height / sector_cells)):
        for sx in range(math.ceil(sim.width / sector_cells)):
            key = f"S{sx:03d}_{sy:03d}"
            sectors[key] = {f"{a}_{m}": f"{prefix}_{key}_{a}_{m}" for a in ("start", "stop") for m in ("small", "large", "smoke")}
    return {"schema": 1, "status": "prepared effects; no live-game acceptance yet", "prefix": prefix,
            "sector_cells": sector_cells, "sectors": sectors, "damage": {},
            "input_policy": "explicit ground-target and ammunition allowlists; damage reports are ignition proxies"}
