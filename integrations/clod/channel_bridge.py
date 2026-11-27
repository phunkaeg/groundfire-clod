"""Mission-clock bridge for the installed Channel fuel database."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import time

from hawkinge import PROTOTYPE
from fire_lab import BOMBS, publish
from firesim.adapters import TheatrePlumeProjector
from firesim.fuelmap import FuelMap
from firesim.sparse import SparseFireSim


CELL_M = 10
MAP_FILE = "channel-fuel.sqlite"
BRIDGE_DIR = "channel-fire"
EFFECT_BUDGET = 24
NEIGHBORS = tuple((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy)


class SeamFire(SparseFireSim):
    """Track a direct neighbour spread across the persisted fuel tile grid."""

    def __init__(self, fuel):
        meta = fuel.metadata
        if (meta["origin_x_m"], meta["origin_y_m"]) != (0, 0):
            raise ValueError("The Channel mission expects zero-based game coordinates")
        self.east_max = meta["width"] * meta["pixel_size_m"]
        self.north_max = meta["height"] * meta["pixel_size_m"]
        self.pixel_m = meta["pixel_size_m"]
        self.fuel_height = meta["height"]
        self.tile_pixels = meta["tile_size"]
        super().__init__(math.ceil(self.east_max / CELL_M), math.ceil(self.north_max / CELL_M),
                         CELL_M, fuel_at=fuel.provider(CELL_M, unknown_policy="inert"),
                         provider_id=fuel.provider_identity(CELL_M, unknown_policy="inert"))
        self.directly_heated = set()
        self.reported = set()
        self.crossings = []
        self.embers_enabled = False  # Separate adjacent spread from spotting in this trial.

    def contains(self, east, north):
        return 0 <= east < self.east_max and 0 <= north < self.north_max

    def tile(self, index):
        east, north = self.center(index)
        px = math.floor(east / self.pixel_m)
        py = self.fuel_height - 1 - math.floor(north / self.pixel_m)
        return px // self.tile_pixels, py // self.tile_pixels

    def seed_bomb(self, kind, east, north, event_id):
        radius, exposure = BOMBS[kind]
        if not self.contains(east, north):
            return 0
        self.directly_heated.update(
            i for i, _ in self._footprint(east, north, radius, seed_impact_cell=True))
        return self.ignite(east, north, radius, exposure, event_id, seed_impact_cell=True)

    def _tick(self, dt):
        flaming = {i for i in self.active if self.cells[i].state == "flaming"
                   and self.cells[i].intensity > 0.005}
        super()._tick(dt)
        for i in sorted(self.active - flaming - self.directly_heated):
            if self.cells[i].state != "flaming":
                continue
            target = self.tile(i)
            x, y = i % self.width, i // self.width
            sources = []
            for dx, dy in NEIGHBORS:
                sx, sy = x + dx, y + dy
                if not (0 <= sx < self.width and 0 <= sy < self.height):
                    continue
                source = self.index(sx, sy)
                if source in flaming:
                    sources.append((self.tile(source), source))
            # With spotting off and no same-tile flame supplying heat on this
            # tick, the receiver's transition needs heat from across a seam.
            if any(tile == target for tile, _ in sources):
                continue
            for origin, source in sources:
                pair = origin, target
                if pair not in self.reported:
                    self.crossings.append(dict(event="tile_crossing", mission_s=self.time,
                                               source_xy=self.center(source), receiver_xy=self.center(i),
                                               source_tile=origin, receiver_tile=target,
                                               receiver_directly_heated=False,
                                               same_tile_flaming_neighbors=0))
                    self.reported.add(pair)


class ChannelRun:
    def __init__(self, fuel, session):
        self.fuel, self.session = fuel, session
        self.sim = SeamFire(fuel)
        self.projector = TheatrePlumeProjector(plume_budget=8, light_budget=0)
        self.clock = 0.0
        self.observer = None
        self.evidence = []
        self.next_crossing = 0
        self.impacts = []
        self.ready = False

    def handle(self, sequence, seconds, kind, args):
        if not math.isfinite(seconds) or seconds < self.clock:
            raise ValueError("Non-monotonic mission clock")
        if kind == "init":
            if self.ready or sequence != 1:
                raise ValueError("Unexpected Channel mission init")
            fingerprint, temperature, east, north = args
            if fingerprint != self.fuel.metadata["dataset_id"]:
                raise ValueError("Channel fuel database does not match the mission")
            values = [float(v) for v in (temperature, east, north)]
            if not all(map(math.isfinite, values)):
                raise ValueError("Invalid Channel weather")
            self.sim.ambient_c, self.sim.wind_east, self.sim.wind_north = values
            self.ready = True
        elif not self.ready:
            raise ValueError("Channel mission did not negotiate a fuel dataset")

        # Stop is sequenced like a clock sample so the replay includes the last span.
        self.sim.step(seconds - self.clock)
        self.clock = seconds
        self.evidence.extend(self.sim.crossings[self.next_crossing:])
        self.next_crossing = len(self.sim.crossings)
        if kind == "bomb":
            weapon, east, north, z, height, group = args
            east, north, z, height = map(float, (east, north, z, height))
            if weapon not in BOMBS or not all(map(math.isfinite, (east, north, z, height))):
                raise ValueError("Invalid bomb record")
            heated = self.sim.seed_bomb(weapon, east, north, f"{self.session}:{sequence}")
            impact = dict(event="impact", mission_s=seconds, weapon=weapon,
                          east=east, north=north, agl=z-height, group=group, heated=heated,
                          fuel=self.fuel.sample(east, north)["name"])
            self.impacts.append(impact)
            self.evidence.append(impact)
        elif kind == "clock":
            east, north, region, utc = args
            self.observer = float(east), float(north)
        elif kind not in ("init", "stop"):
            raise ValueError(f"Unknown Channel event {kind}")

    def frame(self, revision):
        lines = [f"{self.session}\t{revision}\t{self.clock:.6f}"]
        if self.observer is not None:
            ox, oy = self.observer
            for plume in self.projector.desired(self.sim, ox, oy):
                lines.append(f"S{plume.sector[1:]}\tS\t{plume.east:.3f}\t{plume.north:.3f}")
            groups = {}
            for index in sorted(self.sim.active):
                cell = self.sim.cells[index]
                if cell.state != "flaming":
                    continue
                east, north = self.sim.center(index)
                distance = math.hypot(east - ox, north - oy)
                if distance > 6000:
                    continue
                score = cell.intensity / (1 + distance / 1000)
                key = int(east // 30), int(north // 30)
                if key not in groups or score > groups[key][0]:
                    groups[key] = score, east, north
            ranked = sorted(groups.items(), key=lambda item: (-item[1][0], item[0]))
            for (gx, gy), (_, east, north) in ranked[:EFFECT_BUDGET - len(lines) + 1]:
                lines.append(f"F30_{gx}_{gy}\tF\t{east:.3f}\t{north:.3f}")
        return "\n".join(lines) + "\n"


def events(stream):
    for line in stream:
        if not line.endswith(b"\n"):
            break
        seq, stamp, kind, *args = line.decode("ascii").rstrip("\r\n").split("\t")
        yield int(seq), float(stamp), kind, args, len(line)


def serve(folder, fuel):
    print(f"Channel GroundFire bridge ready in {folder}", flush=True)
    started = time.time_ns()
    session, offset, sequence, run, pending, finished = None, 0, 0, None, False, False
    while True:
        time.sleep(0.1)
        try:
            active = (folder / "active.txt").read_text(encoding="ascii").strip()
            if not re.fullmatch(r"[0-9a-f]{32}", active):
                continue
            source = folder / f"{active}.events.tsv"
            if session != active:
                if source.stat().st_mtime_ns < started:
                    continue
                session, offset, sequence = active, 0, 0
                run, pending, finished = ChannelRun(fuel, session), False, False
            if not finished:
                with source.open("rb") as stream:
                    stream.seek(offset)
                    for number, stamp, kind, args, size in events(stream):
                        if number != sequence + 1:
                            raise ValueError("Missing Channel log row")
                        run.handle(number, stamp, kind, args)
                        offset, sequence, pending = offset + size, number, True
                        if kind == "stop":
                            finished = True
                            break
            if run.evidence:
                with (folder / f"{session}.evidence.jsonl").open("a", encoding="ascii") as report:
                    for row in run.evidence:
                        print(json.dumps(row), file=report)
                        print(json.dumps(row), flush=True)
                run.evidence.clear()
            if pending:
                frame = f"{session}\t{sequence}\t{run.clock:.6f}\n" if finished else run.frame(sequence)
                publish(folder, session, frame)
                pending = False
        except (FileNotFoundError, PermissionError):
            continue


def main():
    import msvcrt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fuel-map", type=Path, default=PROTOTYPE / "terrain" / MAP_FILE)
    parser.add_argument("--folder", type=Path, default=Path(os.environ["LOCALAPPDATA"]) /
                        "GroundFireHawkinge" / BRIDGE_DIR)
    args = parser.parse_args()
    fuel = FuelMap(args.fuel_map)
    try:
        args.folder.mkdir(parents=True, exist_ok=True)
        with (args.folder / "bridge.lock").open("a+b") as lock:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise SystemExit("The Channel bridge is already running.") from error
            serve(args.folder, fuel)
    except KeyboardInterrupt:
        pass
    finally:
        fuel.close()


if __name__ == "__main__":
    main()
