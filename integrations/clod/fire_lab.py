"""Local single-player Hawkinge lab bridge. Launch before starting the mission."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
from queue import SimpleQueue
import re
import sys
from threading import Thread
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from firesim.adapters import TheatrePlumeProjector
from firesim.core import FireSim
from firesim.response import HosePlan, HoseResponse
from firesim.sparse import SparseFireSim

SIZE, CELL = 32, 5
HALF = SIZE * CELL / 2
PLOTS = {
    "forest": (235455, 232385),
    "field": (234503, 232745),
    "hedge": (235450, 232700),
    "town": (236864, 230456),
}
SEEDS = ((16, 16), (9, 16), (24, 16))
BOMBS = {"SC50": (8, 375), "SC250": (19, 650), "SC500": (24, 750), "SC1000": (30, 850)}
RATES = (0, 1, 4, 16)
WIND_SPEEDS = (0, 2, 6, 12)
WIND_HEADINGS = {"N": 0, "NE": 45, "E": 90, "SE": 135,
                 "S": 180, "SW": 225, "W": 270, "NW": 315}
TEMPERATURES = {"summer": 23, "winter": 5}
TOWN_CENTER, TOWN_WIDTH = (235360, 233320), 640
WOOD_EDGE_CENTER = (235776, 234048)
LONDON_CENTER = (149120, 273280)
LONDON_ATTACK_CENTER = (155680, 274176)
LONDON_CITY_RAID_CENTER = (149120, 274144)
LONDON_RAID_CENTERS = (LONDON_ATTACK_CENTER, LONDON_CITY_RAID_CENTER)
LONDON_TEMP_C = 4.0
LONDON_WIND = (3.5, 3.5)
WOOD_EDGE_ROAD = ((236155.12, 233480.00), (236098.44, 233560.00), (236044.62, 233640.00),
                 (236007.29, 233700.00), (235983.18, 233743.00))
TERRAIN_KINDS = {"W": "woodland", "G": "grass", "R": "road", "M": "masonry", "U": "masonry", "S": "water"}
FRONT_BUDGET = 16
FRONT_SPACING_M = 20.0
SPLIT_FLAME_BUDGET = 36
SPLIT_SMOKE_BUDGET = 8
DENSE_FLAME_BUDGET = 144
DISTRICT_LIGHT_BUDGET = 12


@dataclass(frozen=True)
class WoodlandTerrain:
    path: Path
    identity: str
    rows: tuple[str, ...]
    chart: dict
    plot: str
    center: tuple[float, float]
    cell_size: int
    grass_moisture: float | None = None

    @classmethod
    def load(cls, path):
        payload = path.read_bytes()
        data = json.loads(payload)
        rows = tuple(data["rows_south_to_north"])
        center = tuple(data["center_game_xy"])
        cell_size = data["cell_size_m"]
        plot = data.get("plot", "forest")
        grass_moisture = data.get("grass_moisture")
        if data["schema"] == 1:
            expected = plot == "forest" and (center, cell_size, len(rows)) == (PLOTS["forest"], CELL, SIZE)
        else:
            width = data.get("span_m", TOWN_WIDTH)
            valid_center = center in (LONDON_CENTER, *LONDON_RAID_CENTERS) or (len(center) == 2 and
                            all(type(coord) is int and 229376 <= coord < 237568 for coord in center))
            expected = (data["schema"] == 2 and plot == "town" and valid_center
                        and cell_size in (10, 20) and len(rows) % 2 == 0
                        and type(width) is int and TOWN_WIDTH <= width <= 3200 and len(rows) * cell_size == width)
        if not expected or any(len(row) != len(rows) or set(row) - TERRAIN_KINDS.keys() for row in rows):
            raise ValueError("Hawkinge terrain grid does not match the capture plot")
        if grass_moisture is not None and (
                type(grass_moisture) not in (int, float) or not 0 <= grass_moisture <= 2):
            raise ValueError("Grass moisture must be a dry-mass ratio in [0, 2]")
        return cls(path, hashlib.sha256(payload).hexdigest(), rows, data["chart"], plot, center, cell_size,
                   grass_moisture)

    def kind(self, x, y):
        return TERRAIN_KINDS[self.rows[y][x]]

    @property
    def half(self):
        return len(self.rows) * self.cell_size / 2

    @property
    def wide(self):
        return self.plot == "town" and self.half * 2 > TOWN_WIDTH

    @property
    def grass_suffix(self):
        return "" if self.grass_moisture is None else f"-grass-{self.grass_moisture:g}".replace(".", "p")

    @property
    def state_folder(self):
        if self.plot == "town":
            site = "" if self.center == TOWN_CENTER else f"-{self.center[0]}-{self.center[1]}"
            width = f"-{self.half * 2:g}m" if self.wide else ""
            return f"lab-town-{self.cell_size}m{site}{width}{self.grass_suffix}"
        base = "lab-scenery" if self.chart.get("native_scenery") else "lab-chart"
        return base + self.grass_suffix


class FireFrontProjector:
    """Place fixed effects on flaming cells with bounded, spatially spread coverage."""

    def __init__(self, budget=FRONT_BUDGET, spacing=FRONT_SPACING_M):
        self.budget = budget
        self.spacing = spacing
        self.anchors = []
        self.last_move = -math.inf

    def clear(self):
        self.anchors.clear()
        self.last_move = -math.inf

    def desired(self, sim):
        positions = {i: sim.center(i) for i in sorted(sim.active) if sim.cells[i].state == "flaming"}
        anchors = [i for i in self.anchors if i in positions]

        def separation(a, b):
            ax, ay = positions[a]
            bx, by = positions[b]
            return (ax - bx) ** 2 + (ay - by) ** 2

        distance = {i: min((separation(i, a) for a in anchors), default=math.inf)
                    for i in positions}
        while distance:
            best = max(distance, key=lambda i: (distance[i], sim.cells[i].intensity, -i))
            gap = distance[best]
            if gap < self.spacing ** 2:
                break
            if len(anchors) == self.budget:
                # Keep hot emitters fixed unless a distant fire needs a slot.
                if gap < (3 * self.spacing) ** 2 or sim.time < self.last_move + 8:
                    break
                old = min(anchors, key=lambda i: (
                    min(separation(i, a) for a in anchors if a != i), sim.cells[i].intensity, i))
                if min(separation(old, a) for a in anchors if a != old) > (1.5 * self.spacing) ** 2:
                    break
                anchors.remove(old)
                anchors.append(best)
                self.last_move = sim.time
                break
            anchors.append(best)
            del distance[best]
            for i in distance:
                distance[i] = min(distance[i], separation(i, best))
        self.anchors = anchors
        return [(f"P1_{i % sim.width}_{i // sim.width}", *positions[i]) for i in anchors]


class SmokeProjector:
    """Keep a few smoke origins near the centers of the strongest smoke-producing areas."""

    def __init__(self):
        self.anchors = {}

    def desired(self, sim):
        sectors = {}
        for i in sorted(sim.active):
            rate = sim.cells[i].smoke_rate
            if rate <= 0:
                continue
            east, north = sim.center(i)
            sector = (int(east / 280), int(north / 280))
            sectors.setdefault(sector, []).append((i, east, north, rate))
        strengths = {key: sum(row[3] for row in cells) for key, cells in sectors.items()}
        # Give existing plumes preference when two areas generate similar amounts of smoke.
        order = sorted(sectors, key=lambda key: (
            -strengths[key] * (1.25 if key in self.anchors else 1), key))
        selected = {}
        for key in order[:SPLIT_SMOKE_BUDGET]:
            cells = sectors[key]
            mass = strengths[key]
            center_x = sum(x * rate for _, x, _, rate in cells) / mass
            center_y = sum(y * rate for _, _, y, rate in cells) / mass
            anchor = self.anchors.get(key)
            if anchor is not None:
                east, north = sim.center(anchor)
                if math.hypot(east - center_x, north - center_y) < 65:
                    selected[key] = anchor
                    continue
            # Use an actual smoke-producing cell so a shoreline plume starts on land.
            selected[key] = min(cells, key=lambda row: (
                (row[1] - center_x) ** 2 + (row[2] - center_y) ** 2, -row[3], row[0]))[0]
        self.anchors = selected
        return [(f"P2_{i % sim.width}_{i // sim.width}", *sim.center(i)) for i in selected.values()]


class DenseFlameProjector:
    """Fill burning blocks with flame origins and distribute the budget across the plot."""

    def __init__(self):
        self.anchors = set()

    def clear(self):
        self.anchors.clear()

    def desired(self, sim):
        best_by_block = {}
        for i in sorted(sim.active):
            cell = sim.cells[i]
            if cell.state != "flaming":
                continue
            x, y = sim.center(i)
            block = int(x / 40), int(y / 40)
            rank = (i in self.anchors, cell.intensity, -i)
            if block not in best_by_block or rank > best_by_block[block][0]:
                best_by_block[block] = rank, i, x, y
        districts = {}
        for (x, y), row in best_by_block.items():
            districts.setdefault((x // 5, y // 5), []).append(row)
        ordered = []
        for district in sorted(districts):
            for priority, (rank, i, x, y) in enumerate(sorted(districts[district], reverse=True)):
                ordered.append((priority, -rank[0], -rank[1], district, i, x, y))
        chosen = sorted(ordered)[:DENSE_FLAME_BUDGET]
        self.anchors = {i for _, _, _, _, i, _, _ in chosen}
        return [(f"P1_{i % sim.width}_{i // sim.width}", x, y) for _, _, _, _, i, x, y in chosen]


class DistrictLightProjector:
    """Keep a fixed light in each selected burning district and track its combined intensity."""

    def __init__(self, budget=DISTRICT_LIGHT_BUDGET):
        self.budget = budget
        self.district_size = 160 if budget > DISTRICT_LIGHT_BUDGET else 220
        self.anchors = {}

    def desired(self, sim):
        districts = {}
        for i in sorted(sim.active):
            cell = sim.cells[i]
            if cell.state != "flaming" or cell.intensity <= 0:
                continue
            east, north = sim.center(i)
            key = int(east / self.district_size), int(north / self.district_size)
            districts.setdefault(key, []).append((i, east, north, cell.intensity))
        heat = {key: sum(row[3] for row in cells) for key, cells in districts.items()}
        chosen = {key: self.anchors[key] for key in self.anchors if key in districts}
        for key in sorted(heat, key=lambda key: (-heat[key], key)):
            if len(chosen) >= self.budget:
                break
            if key in chosen or heat[key] < 0.8:
                continue
            cells = districts[key]
            center_x = sum(x * strength for _, x, _, strength in cells) / heat[key]
            center_y = sum(y * strength for _, _, y, strength in cells) / heat[key]
            anchor, x, y, _ = min(cells, key=lambda row: (
                (row[1] - center_x) ** 2 + (row[2] - center_y) ** 2, row[0]))
            if all(math.dist((x, y), sim.center(other)) >= 105 for other in chosen.values()):
                chosen[key] = anchor
        self.anchors = chosen
        return [(f"P3_{i % sim.width}_{i // sim.width}", *sim.center(i), -math.expm1(-heat[key] / 5))
                for key, i in chosen.items()]


def london_ignitions(terrain):
    """Return repeatable visual test starts on chart-classified urban cells."""
    if terrain.center != LONDON_CENTER or terrain.cell_size != 10 or terrain.half != 1600:
        raise ValueError("The London fixture requires its wide 10 m terrain")
    offset = len(terrain.rows) // 2
    used = set()
    for index, (east, north) in enumerate(((-480, 470), (590, 900), (320, -420))):
        for dx, dy in ((-55, -35), (0, 30), (65, -15)):
            x, y = offset + (east + dx) // 10, offset + (north + dy) // 10
            candidates = ((a, b) for b in range(y - 5, y + 6) for a in range(x - 5, x + 6)
                          if terrain.rows[b][a] == "U" and (a, b) not in used)
            i, j = min(candidates, key=lambda v: ((v[0] - x) ** 2 + (v[1] - y) ** 2, v))
            used.add((i, j))
            yield (15 + 10 * index, LONDON_CENTER[0] + (i - offset) * 10 + 5,
                   LONDON_CENTER[1] + (j - offset) * 10 + 5)


def make_plot(plot, gap=False, terrain=None):
    if terrain is not None and terrain.plot == plot:
        dim = len(terrain.rows)

        def fuel_at(x, y):
            kind = terrain.kind(x, y)
            return {"kind": kind, "moisture": terrain.grass_moisture if kind == "grass" else None}

        if terrain.wide:
            return SparseFireSim(dim, dim, terrain.cell_size, fuel_at=fuel_at, provider_id=terrain.identity)
        sim = FireSim(dim, dim, terrain.cell_size)
        for y in range(dim):
            for x in range(dim):
                sim.paint(x, y, **fuel_at(x, y))
        return sim
    sim = FireSim(SIZE, SIZE, CELL)
    for y in range(SIZE):
        for x in range(SIZE):
            kind = "road"
            if 2 <= x < 30 and 2 <= y < 30:
                if plot in ("forest", "field"):
                    kind = "woodland" if plot == "forest" else "grass"
                elif plot == "hedge" and y == 16 and not (gap and 19 <= x <= 20):
                    kind = "hedgerow"
                elif plot == "town" and (x - 2) % 7 < 5 and (y - 2) % 7 < 5:
                    kind = "masonry"
                elif plot == "houses" and 15 <= y < 19 and any(
                    left <= x < left + 4 for left in (9, 15, 21)
                ):
                    kind = "masonry"
                elif plot == "factory" and 9 <= x < 25 and 14 <= y < 21:
                    kind = "factory"
            sim.paint(x, y, kind)
    return sim


@dataclass
class CityCrew:
    response: HoseResponse
    clock: float
    position: tuple[float, float] | None = None
    parked: bool = False
    target: int | None = None


class Lab:
    def __init__(self, terrain=None, front_fx=False, split_fx=False, dense_fx=False,
                 district_budget=DISTRICT_LIGHT_BUDGET):
        self.available_terrain = terrain
        self.terrain = None
        self.sim = None
        self.anchor = None
        self.plot = None
        self.generation = 0
        self.rate = 1
        self.clock = 0.0
        self.tod = 0.0
        self.mission_weather = None
        self.wind = (0.0, 0.0)
        self.heading = math.pi / 2
        self.ambient = 20.0
        self.rain = 0
        self.embers = True
        self.projector = TheatrePlumeProjector(plume_budget=4, light_budget=0)
        self.front = (DenseFlameProjector() if dense_fx else
                      FireFrontProjector(SPLIT_FLAME_BUDGET, 40.0) if split_fx else
                      FireFrontProjector() if front_fx else None)
        self.smoke = SmokeProjector() if split_fx else None
        self.district_lights = DistrictLightProjector(district_budget) if dense_fx else None
        self.crew = None
        self.crew_position = None
        self.crew_clock = None
        self.crew_parked = False
        self.city_crews = {}

    def city_crew_sample(self, seconds, args):
        number, east, north, stopped = args
        crew = self.city_crews.get(number)
        if crew is None or self.sim is None:
            return
        position = float(east), float(north)
        FireSim._finite(*position)
        crew.position = position
        pump = tuple(coord - origin + self.terrain.half for coord, origin in zip(position, self.terrain.center))
        dt = min(2, seconds - crew.clock) if crew.parked else 0
        crew.clock = seconds
        response = crew.response
        plan = response.plan
        crew.parked = stopped == "1" and math.dist(pump, plan.staging) <= plan.arrival_radius_m
        if not crew.parked or response.water_left_l <= 0:
            response.advance(self.sim, dt, pump, stopped=crew.parked)
            return

        def reachable(i):
            fire = self.sim.center(i)
            distance = math.dist(pump, fire)
            if distance > plan.hose_m or self.sim.cells[i].state != "flaming":
                return False
            # A straight hose scenario must stay on the same side of the river.
            steps = max(1, math.ceil(distance / (self.sim.cell_size / 2)))
            for step in range(steps + 1):
                x, y = (math.floor((a + (b - a) * step / steps) / self.sim.cell_size)
                        for a, b in zip(pump, fire))
                if not (0 <= x < self.sim.width and 0 <= y < self.sim.height):
                    return False
                if self.sim.cells[self.sim.index(x, y)].kind == "water":
                    return False
            return True

        if crew.target is None or not reachable(crew.target):
            crew.target = min((i for i in self.sim.active if reachable(i)),
                              key=lambda i: (math.dist(pump, self.sim.center(i)), i), default=None)
        if crew.target is None:
            response.state = "out_of_reach"
            response.setup_remaining_s = plan.setup_s
            return
        response.plan = replace(plan, fire=self.sim.center(crew.target), intake=pump)
        response.advance(self.sim, dt, pump, stopped=True)

    def crew_sample(self, seconds, args):
        if self.crew is None:
            return None
        east, north, stopped = args
        east, north = float(east), float(north)
        FireSim._finite(east, north)
        old = self.crew.state
        dt = min(2.0, seconds - self.crew_clock) if self.crew_parked else 0.0
        self.crew_clock = seconds
        self.crew_position = east, north
        offset = tuple(v - self.terrain.half for v in self.terrain.center)
        pump = east - offset[0], north - offset[1]
        plan = self.crew.plan
        self.crew_parked = stopped == "1" and math.dist(pump, plan.staging) <= plan.arrival_radius_m
        if not self.crew_parked:
            self.crew.advance(self.sim, dt, pump, stopped=False)
        elif self.crew.water_left_l > 0:
            targets = (self.sim.center(i) for i in self.sim.active if self.sim.cells[i].state == "flaming")
            nearest = min(targets, key=lambda p: (math.dist(pump, p), p), default=None)
            if nearest is None or math.dist(pump, nearest) > plan.hose_m:
                self.crew.state = "out_of_reach"
            else:
                self.crew.plan = replace(plan, fire=nearest, intake=pump)
                self.crew.advance(self.sim, dt, pump, stopped=True)
        if self.crew.state != old and self.crew.state == "pumping":
            return "Fire crew pumping water on the reachable fire."
        if self.crew.state != old and self.crew.state == "water_exhausted":
            return "Emergency pump tank exhausted."
        if self.crew.state != old and self.crew.state == "setting_up":
            return "Fire crew has arrived and is setting up the hose."
        return None

    def environment(self):
        if self.sim:
            self.sim.wind_east, self.sim.wind_north = self.wind
            self.sim.ambient_c = self.ambient
            self.sim.rain_mm_h = self.rain
            self.sim.embers_enabled = self.embers

    def advance(self, clock):
        delta = clock - self.clock
        if not math.isfinite(clock) or delta < 0:
            raise ValueError("Mission clock regressed")
        self.clock = clock
        if self.sim and delta and self.rate:
            remaining = delta * self.rate
            while remaining > 0:
                step = min(remaining, 3600)
                self.sim.step(step)
                remaining -= step

    def new_plot(self, kind, gap=False):
        self.sim = make_plot(kind, gap, self.terrain)
        self.crew = self.crew_position = self.crew_clock = None
        self.crew_parked = False
        self.city_crews.clear()
        self.plot = kind
        self.anchor = kind if kind in PLOTS else "town"
        self.generation += 1
        if self.front:
            self.front.clear()
        if self.smoke:
            self.smoke.anchors.clear()
        if self.district_lights:
            self.district_lights.anchors.clear()
        self.environment()

    def handle(self, seconds, action, args):
        if self.mission_weather is None and action != "init":
            raise ValueError("Missing mission environment")
        self.advance(seconds)
        message = None
        if action == "init":
            if self.mission_weather is not None:
                raise ValueError("Duplicate mission initialization")
            temp, east, north = map(float, args[:3])
            if len(args) > 3:
                dataset_id, = args[3:]
                if self.available_terrain is None or self.available_terrain.identity != dataset_id:
                    raise ValueError("Mission requires its matching Hawkinge terrain grid")
                self.terrain = self.available_terrain
            FireSim._finite(temp, east, north)
            self.mission_weather = temp, (east, north)
            self.ambient, self.wind = self.mission_weather
            if math.hypot(*self.wind):
                self.heading = math.atan2(*self.wind)
            message = "Lab bridge connected. Open Mission orders or use the bridge console."
        elif action == "clock":
            tod = float(args[0])
            if math.isfinite(tod):
                self.tod = tod
        elif action == "crew_dispatch":
            if not self.terrain or self.terrain.center != WOOD_EDGE_CENTER or self.sim is None:
                raise ValueError("No woodland village fire for the crew")
            stage = tuple(road - origin + self.terrain.half
                          for road, origin in zip(WOOD_EDGE_ROAD[-1], self.terrain.center))
            self.crew = HoseResponse(HosePlan(stage, stage, stage, hose_m=150, setup_s=12,
                                              pump_l_s=6, charged_line_l_s=6, water_l=300,
                                              application_radius_m=12, delivery_fraction=0.65,
                                              arrival_radius_m=30))
            self.crew_clock = seconds
            self.crew_parked = False
            message = "Fire detected. Emergency column dispatched."
        elif action == "crew_position":
            message = self.crew_sample(seconds, args)
        elif action == "city_crew_dispatch":
            if not self.terrain or self.terrain.center != LONDON_CITY_RAID_CENTER or self.sim is None:
                raise ValueError("No central London fire for the crew")
            number, east, north = args
            if number not in ("1", "2", "3", "4") or number in self.city_crews:
                raise ValueError("Invalid central London crew dispatch")
            stage = tuple(float(coord) - origin + self.terrain.half
                          for coord, origin in zip((east, north), self.terrain.center))
            plan = HosePlan(stage, stage, stage, hose_m=170, setup_s=18, pump_l_s=8,
                            charged_line_l_s=6, water_l=1200, application_radius_m=17,
                            delivery_fraction=0.65, arrival_radius_m=32)
            self.city_crews[number] = CityCrew(HoseResponse(plan), seconds)
        elif action == "city_crew_position":
            self.city_crew_sample(seconds, args)
        elif action == "city_crew_lost":
            crew = self.city_crews.get(args[0])
            if crew is not None:
                crew.position = None
                crew.parked = False
                crew.target = None
                crew.response.advance(self.sim, 0, None, stopped=False)
                crew.response.state = "unavailable"
        elif action == "seed":
            plot, quantity = args
            if plot not in (*PLOTS, "houses", "factory", "hedge_gap"):
                raise ValueError("Unknown plot")
            count = int(quantity)
            if count not in (1, 2, 3) or (plot in ("hedge", "hedge_gap", "houses", "factory") and count != 1):
                raise ValueError("Unsupported seed count")
            self.new_plot("hedge" if plot == "hedge_gap" else plot, gap=plot == "hedge_gap")
            cell = self.sim.cell_size
            offset = (self.sim.width - SIZE) // 2
            for x, y in SEEDS[:count]:
                self.sim.ignite((x + offset + 0.5) * cell, (y + offset + 0.5) * cell, cell * 0.48, 360)
            # Set the queued seeds visibly alight after the first normal fixed step.
            message = f"{plot.replace('_', ' ')}: {count} ignition point(s)."
        elif action == "ignition":
            if not self.terrain or self.terrain.center not in (LONDON_CENTER, LONDON_CITY_RAID_CENTER):
                raise ValueError("Scripted city ignition requires the London terrain")
            wx, wy = map(float, args)
            FireSim._finite(wx, wy)
            x, y = (coord - center + self.terrain.half
                    for coord, center in zip((wx, wy), self.terrain.center))
            span = self.terrain.half * 2
            if not (0 <= x < span and 0 <= y < span):
                raise ValueError("Scripted fire is outside the London plot")
            if self.plot != "town":
                self.new_plot("town")
            count = self.sim.ignite(x, y, radius=9, exposure=500)
            message = f"Scripted city fire started. {count} fuel cell(s) heated."
        elif action == "bomb":
            bomb, wx, wy = args[:3]
            wx, wy = float(wx), float(wy)
            FireSim._finite(wx, wy)
            plot = self.terrain.plot if self.terrain else "forest"
            x, y = self.terrain.center if self.terrain else PLOTS["forest"]
            half = self.terrain.half if self.terrain else HALF
            if plot == "town":
                inside = -half <= wx - x < half and -half <= wy - y < half
            else:
                inside = math.hypot(wx - x, wy - y) <= 62
            if not inside:
                return f"{bomb} missed the {plot} test area."
            radius, exposure = BOMBS[bomb]
            if self.plot != plot:
                self.new_plot(plot)
            # A 20 m plot can contain an SC 50 impact even when no cell centre is inside its footprint.
            coarse_city = self.terrain is not None and self.terrain.center == LONDON_CITY_RAID_CENTER and self.sim.cell_size == 20
            count = self.sim.ignite(half + wx - x, half + wy - y, radius, exposure, seed_impact_cell=coarse_city)
            message = f"{bomb} ground impact: {count} fuel cells heated."
        elif action == "rate":
            rate = int(args[0])
            if rate not in RATES:
                raise ValueError("Unsupported fire clock multiplier")
            self.rate = rate
            message = "Fire clock held." if not rate else f"Fire clock {rate}x mission time."
        elif action == "wind":
            axis, value = args
            current_speed = math.hypot(*self.wind)
            east, north = self.wind
            if axis == "toward":
                heading = math.radians(WIND_HEADINGS[value])
                # Remember a selected heading even while calm.
                self.heading = heading
                speed = current_speed
            elif axis == "speed":
                speed = int(value)
                if speed not in WIND_SPEEDS:
                    raise ValueError("Unsupported wind speed")
                heading = math.atan2(east, north) if current_speed else self.heading
            else:
                raise ValueError("Unknown wind command")
            self.heading = heading
            self.wind = speed * math.sin(heading), speed * math.cos(heading)
            message = f"Fire wind {speed:g} m/s toward {math.degrees(heading) % 360:.0f} degrees."
        elif action == "weather":
            value, = args
            if value == "mission":
                self.ambient, self.wind = self.mission_weather
                self.rain, self.embers = 0, True
                self.heading = math.atan2(*self.wind)
            elif value in TEMPERATURES:
                self.ambient = TEMPERATURES[value]
            elif value == "rain":
                self.rain = 12 if not self.rain else 0
            elif value == "embers":
                self.embers = not self.embers
            else:
                raise ValueError("Unknown weather command")
            message = self.status()
        elif action == "water":
            applied = 0
            if self.sim:
                for i in tuple(sorted(self.sim.active)):
                    cell = self.sim.cells[i]
                    if cell.state in ("flaming", "smoldering") and cell.wetness < 0.4:
                        applied += self.sim.suppress(*self.sim.center(i), radius=5, water_kg=75)
            message = (f"Applied {applied:g} L of test water. Residual smoke can linger."
                       if applied else "No active fire needed test water.")
        elif action in ("reset", "stop"):
            self.sim = self.anchor = self.plot = None
            self.crew = self.crew_position = self.crew_clock = None
            self.crew_parked = False
            self.city_crews.clear()
            message = "Plot cleared. Lab weather and fire speed retained."
        elif action == "status":
            message = self.status()
        else:
            raise ValueError(f"Unknown action {action!r}")
        self.environment()
        return message

    def status(self):
        wind = math.hypot(*self.wind)
        heading = round(math.degrees(self.heading)) % 360
        minute_of_day = round(self.tod * 60) % (24 * 60)
        status = (f"{minute_of_day // 60:02}:{minute_of_day % 60:02} | {self.ambient:g} C | "
                  f"wind {wind:.1f} m/s to {heading:.0f} deg | {self.rain} mm/h | "
                  f"embers {'on' if self.embers else 'off'} | fire {self.rate}x")
        if self.sim:
            stats = self.sim.stats()
            status += f" | {self.plot} {self.sim.time:.0f}s | {stats['ignitions']} cells ignited"
            if self.plot == "hedge":
                ignited = [i % SIZE for i, cell in enumerate(self.sim.cells) if cell.fuel < cell.initial_fuel]
                if ignited:
                    status += f" | {(max(ignited) - min(ignited) + 1) * CELL}m hedge involved"
        return status

    def frame(self, session, version, message_id, message, light_data=False):
        lines = [f"{session}\t{version}\t{self.clock:.6f}\t{message_id}\t{message}"]
        if self.sim:
            terrain = self.terrain if self.terrain and self.terrain.plot == self.plot else None
            wx, wy = terrain.center if terrain else PLOTS[self.anchor]
            half = terrain.half if terrain else HALF
            if terrain and terrain.plot == "town" and self.front:
                anchors = self.front.desired(self.sim)
                if self.smoke:
                    anchors += self.smoke.desired(self.sim)
            else:
                anchors = ((p.sector, p.east, p.north) for p in self.projector.desired(self.sim, half, half))
            for sector, east, north in anchors:
                ix, iy = int(east / self.sim.cell_size), int(north / self.sim.cell_size)
                if self.district_lights and terrain and sector.startswith("P1_") and terrain.rows[iy][ix] in "UM":
                    sector = sector.replace("P1_", "P4_", 1)
                row = f"{self.generation}_{sector}\t{self.anchor}\t{wx - half + east:.3f}\t{wy - half + north:.3f}"
                if light_data:
                    intensity = 0 if sector.startswith("P2_") else self.sim.cells[self.sim.index(ix, iy)].intensity
                    row += f"\t{intensity:.5f}"
                lines.append(row)
            if self.district_lights and terrain and self.plot == "town":
                for sector, east, north, strength in self.district_lights.desired(self.sim):
                    lines.append(f"{self.generation}_{sector}\t{self.anchor}\t{wx - half + east:.3f}\t"
                                 f"{wy - half + north:.3f}\t{strength:.5f}")
        return "\n".join(lines) + "\n"


def publish(folder, session, frame):
    temp = folder / (session + ".bridge.tmp")
    temp.write_text(frame, encoding="ascii")
    temp.replace(folder / (session + ".plumes.tsv"))


def console(queue):
    print("Console fallback: seed forest 3 | seed hedge 1 | rate 4 | status | help", flush=True)
    for line in sys.stdin:
        words = line.strip().split()
        if words == ["help"]:
            print("seed forest/field/town 1/2/3 | seed hedge/hedge_gap/houses/factory 1\n"
                  "wind toward N/NE/E/SE/S/SW/W/NW | wind speed 0/2/6/12\n"
                  "rate 0/1/4/16 | weather mission/summer/winter/rain/embers | water | reset | status", flush=True)
        elif words and words[0] in {"seed", "wind", "rate", "weather", "water", "reset", "status"}:
            queue.put(words)
        elif words:
            print("Unknown command. Type help.", flush=True)


def bridge(folder, terrain=None, front_fx=False, light_data=False, split_fx=False, dense_fx=False,
           district_budget=DISTRICT_LIGHT_BUDGET):
    folder.mkdir(parents=True, exist_ok=True)
    # Ignore a stale session selector until the game actually appends a new event.
    started_at = time.time_ns()
    session, lab, offset, event_number = "", None, 0, 0
    message, message_id, version = "", 0, 0
    pending = stopped = False
    inputs = SimpleQueue()
    print("Waiting for Hawkinge Fire Lab. Leave this window open while flying.", flush=True)
    if sys.stdin is not None and sys.stdin.isatty():
        Thread(target=console, args=(inputs,), daemon=True).start()
    while True:
        time.sleep(0.10)
        try:
            active = (folder / "active.txt").read_text(encoding="ascii").strip()
            if not re.fullmatch("[0-9a-f]{32}", active):
                continue
            path = folder / (active + ".events.tsv")
            if active != session:
                if path.stat().st_mtime_ns < started_at:
                    continue
                lab = Lab(terrain, front_fx, split_fx, dense_fx, district_budget)
                session, offset, event_number = active, 0, 0
                message, message_id, version = "", 0, 0
                pending = stopped = False
            changed = False
            with path.open("rb") as stream:
                stream.seek(offset)
                for row in stream:
                    if not row.endswith(b"\n"):
                        break
                    seq, seconds, action, *args = row.decode("ascii").rstrip("\r\n").split("\t")
                    if int(seq) != event_number + 1:
                        raise ValueError("Out-of-order mission event")
                    result = lab.handle(float(seconds), action, args)
                    if result is not None:
                        message, message_id = result, time.monotonic_ns()
                        print(result, flush=True)
                    if action == "stop":
                        print("Mission ended. Waiting for another Fire Lab flight.", flush=True)
                        stopped = True
                    offset = stream.tell()
                    event_number = int(seq)
                    changed = True
            while not inputs.empty():
                action, *args = inputs.get()
                if stopped:
                    print("Start a Hawkinge Fire Lab mission first.", flush=True)
                    continue
                try:
                    result = lab.handle(lab.clock, action, args)
                except (IndexError, KeyError, ValueError) as error:
                    print(f"Command rejected: {error}. Type help.", flush=True)
                    continue
                message, message_id = result, time.monotonic_ns()
                print(result, flush=True)
                changed = True
            if changed:
                version = time.monotonic_ns()
                pending = True
            if pending:
                # Republish after a Windows sharing race on the atomic rename.
                publish(folder, session, lab.frame(session, version, message_id, message, light_data))
                pending = False
        except FileNotFoundError:
            continue
        except PermissionError:
            continue


if __name__ == "__main__":
    import msvcrt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terrain", type=Path, help="Enable the matching Hawkinge woodland grid")
    parser.add_argument("--front-fx", action="store_true", help="Use fixed fire emitters across the town")
    parser.add_argument("--light-data", action="store_true", help="Send per-emitter fire intensity to the night raid")
    parser.add_argument("--split-fx", action="store_true", help="Send separate flame and smoke origins")
    parser.add_argument("--dense-fx", action="store_true", help="Use dense flames and separate district lights")
    parser.add_argument("--district-lights", type=int, choices=(12, 24), default=DISTRICT_LIGHT_BUDGET)
    parser.add_argument("--warm-smoke", action="store_true", help="Use the isolated night smoke test folder")
    args = parser.parse_args()
    terrain = WoodlandTerrain.load(args.terrain) if args.terrain else None
    if args.front_fx and (terrain is None or terrain.plot != "town"):
        parser.error("--front-fx requires a town terrain grid")
    if args.light_data and (not args.front_fx or terrain.center not in LONDON_RAID_CENTERS):
        parser.error("--light-data requires the London Attack terrain and --front-fx")
    if args.split_fx and (not args.light_data or terrain.center != LONDON_CITY_RAID_CENTER):
        parser.error("--split-fx requires the central London terrain and --light-data")
    if args.dense_fx and not args.split_fx:
        parser.error("--dense-fx requires --split-fx")
    if args.district_lights != DISTRICT_LIGHT_BUDGET and not args.dense_fx:
        parser.error("--district-lights requires --dense-fx")
    if args.warm_smoke and not args.dense_fx:
        parser.error("--warm-smoke requires --dense-fx")
    state = terrain.state_folder if terrain else "lab"
    if args.front_fx:
        state += "-front"
    if args.light_data:
        state += "-pulse"
    if args.split_fx:
        state += "-split"
    if args.dense_fx:
        state += "-dense"
    if args.district_lights != DISTRICT_LIGHT_BUDGET:
        state += f"-l{args.district_lights}"
    if args.warm_smoke:
        state += "-warm-smoke"
    folder = Path(os.environ["LOCALAPPDATA"]) / "GroundFireHawkinge" / state
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "bridge.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise SystemExit("A Hawkinge Fire Lab bridge is already running.") from error
        try:
            bridge(folder, terrain, args.front_fx, args.light_data, args.split_fx, args.dense_fx, args.district_lights)
        except KeyboardInterrupt:
            pass
