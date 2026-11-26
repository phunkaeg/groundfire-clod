"""Render a Hawkinge fire map from a clocked mission log or an offline example."""
import argparse
from bisect import bisect_right
from functools import lru_cache
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageColor, ImageDraw, ImageFont

from fire_lab import (CELL, HALF, LONDON_CITY_RAID_CENTER, LONDON_RAID_CENTERS, LONDON_CENTER,
                      LONDON_TEMP_C, LONDON_WIND, PLOTS, SIZE, TERRAIN_KINDS,
                      TOWN_WIDTH, WOOD_EDGE_CENTER, Lab, WoodlandTerrain, london_ignitions)
from hawkinge import OUT

WIDTH, HEIGHT, FPS = 960, 640, 20
MAP_X, MAP_Y, PIXELS = 32, 104, 15
COLORS = dict(woodland="#3f6543", grass="#758354", road="#544d46", masonry="#c45736", town_cover="#996950", burned="#39302f",
              heating="#a69c42", flaming="#f77b28", smoldering="#a17b67", water="#2a5372")
RAID_IMPACT_COLOR = "#e6d4c4"
RAID_IMPACT_PATTERN = re.compile(r"^bomb .*? x=(\S+) y=(\S+) z=\S+ .*? t=(\S+) .* accepted=True$")


def terrain_inset(folder):
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    resolution = float(metadata["pixel_size_m"])
    if resolution <= 0 or metadata["raster_origin"] != "top_left; game Y increases upward":
        raise ValueError("Unsupported Channel overview registration")
    east, north = PLOTS["forest"]
    columns, rows, zoom = 16, 7, 22
    with Image.open(folder / "channel-overview.png") as source:
        if source.size != (metadata["width"], metadata["height"]):
            raise ValueError("Channel overview dimensions do not match the registration metadata")
        x = (east - metadata["origin_x_m"]) / resolution
        y = source.height - (north - metadata["origin_y_m"]) / resolution
        left, top = int(x) - columns // 2, int(y) - rows // 2
        if left < 0 or top < 0 or left + columns > source.width or top + rows > source.height:
            raise ValueError("Hawkinge plot is outside the registered Channel overview")
        inset = source.crop((left, top, left + columns, top + rows)).convert("RGB")
        inset = inset.resize((columns * zoom, rows * zoom), Image.Resampling.NEAREST)
    # The white box registers the authored plot on the coarse native raster.
    cx, cy, radius = (x - left) * zoom, (y - top) * zoom, HALF * zoom / resolution
    ImageDraw.Draw(inset).rectangle((cx - radius, cy - radius, cx + radius, cy + radius),
                                     outline="white", width=2)
    return inset, resolution, "Cliffs of Dover overview"


def chart_inset(terrain):
    chart = terrain.chart
    filename = chart["filename"]
    if Path(filename).name != filename:
        raise ValueError("Expected the chart image beside the terrain file")
    source_path = terrain.path.parent / filename
    if not source_path.is_file():
        size = (154, 154) if terrain.wide else (352, 154)
        inset = fuel_raster(terrain.rows).resize(size, Image.Resampling.NEAREST)
        ImageDraw.Draw(inset).rectangle((0, 0, size[0] - 1, size[1] - 1), outline="white")
        return inset, terrain.cell_size, "Fuel grid overview"
    payload = source_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != chart["sha256"]:
        raise ValueError("The chart image does not match the woodland grid")
    resolution = chart["metres_per_pixel"]
    width, height = round(2560 / resolution), round(1120 / resolution)
    if terrain.wide:
        width = height = round(min(3200, terrain.half * 2 + 160) / resolution)
    east, north = terrain.center
    origin_east, origin_north = chart["origin_game_xy"]
    with Image.open(BytesIO(payload)) as source:
        cx = (east - origin_east) / resolution
        cy = source.height - (north - origin_north) / resolution
        left, top = int(cx) - width // 2, int(cy) - height // 2
        if not (0 <= left <= source.width - width and 0 <= top <= source.height - height):
            raise ValueError("Hawkinge chart crop does not cover the test plot")
        resample = Image.Resampling.LANCZOS if width > 352 else Image.Resampling.NEAREST
        size = (154, 154) if terrain.wide else (352, 154)
        inset = source.crop((left, top, left + width, top + height)).resize(size, resample)
    zoom = size[0] / width
    x, y, r = (cx - left) * zoom, (cy - top) * zoom, terrain.half * zoom / resolution
    ImageDraw.Draw(inset).rectangle((x - r, y - r, x + r, y + r), outline="white", width=2)
    title = "CloD chart and scenery geometry" if chart.get("native_scenery") else "Cliffs of Dover navigation chart"
    return inset, chart.get("woodland_metres_per_pixel", resolution), title


@lru_cache(maxsize=4)
def fuel_raster(rows):
    size = len(rows)
    colors = {symbol: ImageColor.getrgb(COLORS["town_cover" if symbol == "U" else kind])
              for symbol, kind in TERRAIN_KINDS.items()}
    layer = Image.new("RGB", (size, size))
    layer.putdata([colors[symbol] for row in reversed(rows) for symbol in row])
    return layer


def wide_fire_raster(lab, grid):
    layer = fuel_raster(grid.rows).copy()
    if lab.sim:
        size = len(grid.rows)
        for i, cell in lab.sim.cells.allocated.items():
            color = COLORS.get(cell.state)
            if color:
                layer.putpixel((i % size, size - 1 - i // size),
                               ImageColor.getrgb("#534535" if cell.state == "burned" and cell.kind == "grass" else color))
    return layer


def render(lab, impacts, elapsed, heading, acceleration, terrain=None, emitters=None, split_fx=False,
           scripted_ignitions=False, raid_impacts=None):
    frame = Image.new("RGB", (WIDTH, HEIGHT), "#142025")
    canvas = ImageDraw.Draw(frame)
    font_dir = Path("C:/Windows/Fonts")
    fonts = {size: ImageFont.truetype(font_dir / ("seguisb.ttf" if size >= 26 else "segoeui.ttf"), size)
             for size in (16, 19, 26, 36)}

    def text(x, y, content, size, color="#ecf2ed"):
        canvas.text((x, y), content, fill=color, font=fonts[size])

    grid = lab.terrain if lab.terrain and (lab.plot is None or lab.plot == lab.terrain.plot) else None
    town = grid is not None and grid.plot == "town"
    village = town and grid.center == WOOD_EDGE_CENTER
    raid = town and grid.center in LONDON_RAID_CENTERS
    city_raid = raid and grid.center == LONDON_CITY_RAID_CENTER
    london = town and (raid or grid.center == LONDON_CENTER)
    wide = grid is not None and grid.wide
    size = lab.sim.width if lab.sim else len(grid.rows) if grid else SIZE
    cell = lab.sim.cell_size if lab.sim else grid.cell_size if grid else CELL
    span = size * cell
    map_side = PIXELS * SIZE
    title = "Woodland village fire" if village else "Hawkinge town fire" if town else "Hawkinge woodland fire"
    if city_raid:
        title = ("Central London in the morning" if 5 <= lab.tod < 10 else
                 "Central London by day" if 10 <= lab.tod < 19 else
                 "Central London at dusk" if 19 <= lab.tod < 22 else "Central London at night")
    elif raid:
        title = "London Attack at night" if lab.tod >= 22 else "London Attack"
    elif london:
        title = "London night fire"
    elif wide:
        title += " · wider test"
    text(32, 20, title, 36)
    text(34, 68, heading, 19, "#a9c6ba")
    if wide:
        layer = wide_fire_raster(lab, grid).resize((map_side, map_side), Image.Resampling.NEAREST)
        frame.paste(layer, (MAP_X, MAP_Y))
        if not london:
            half_box = map_side * TOWN_WIDTH / (2 * span)
            mx, my = MAP_X + map_side // 2, MAP_Y + map_side // 2
            for delta in range(-round(half_box), round(half_box), 10):
                for edge in (-half_box, half_box):
                    canvas.line((mx + delta, my + edge, mx + delta + 6, my + edge), fill="#f8edcd", width=2)
                    canvas.line((mx + edge, my + delta, mx + edge, my + delta + 6), fill="#f8edcd", width=2)
    for iy in range(0 if wide else size):
        for ix in range(size):
            x0 = MAP_X + ix * map_side // size
            x1 = MAP_X + (ix + 1) * map_side // size - 1
            y0 = MAP_Y + (size - 1 - iy) * map_side // size
            y1 = MAP_Y + (size - iy) * map_side // size - 1
            base = COLORS["town_cover"] if town and grid.rows[iy][ix] == "U" else None
            if lab.sim:
                fuel = lab.sim.cells[iy * size + ix]
                color = COLORS.get(fuel.state, base or COLORS.get(fuel.kind, COLORS["road"]))
                if grid and fuel.state == "burned" and fuel.kind == "grass":
                    color = "#534535"
            elif grid:
                color = base or COLORS[grid.kind(ix, iy)]
            else:
                color = COLORS["woodland"] if 2 <= ix < 30 and 2 <= iy < 30 else COLORS["road"]
            canvas.rectangle((x0, y0, x1, y1), fill=color, outline="#253936")

    map_east, map_north = grid.center if grid else PLOTS["forest"]
    def map_point(east, north):
        return (MAP_X + (0.5 + (east - map_east) / span) * map_side,
                MAP_Y + (0.5 - (north - map_north) / span) * map_side)

    if lab.crew_position is not None:
        x, y = map_point(*lab.crew_position)
        margin = 25
        if MAP_X - margin <= x <= MAP_X + map_side + margin and MAP_Y - margin <= y <= MAP_Y + map_side + margin:
            x = max(MAP_X + 5, min(x, MAP_X + map_side - 5))
            y = max(MAP_Y + 5, min(y, MAP_Y + map_side - 5))
            canvas.rectangle((x - 5, y - 5, x + 5, y + 5), fill="#579cff", outline="white")
    radius = 4 if london else 7 if town else 10
    if raid_impacts is not None:
        for _, east, north in raid_impacts:
            x, y = map_point(east, north)
            if MAP_X <= x < MAP_X + map_side and MAP_Y <= y < MAP_Y + map_side:
                canvas.ellipse((x - 1.5, y - 1.5, x + 1.5, y + 1.5), fill=RAID_IMPACT_COLOR)
    for i, (east, north) in enumerate(impacts or (), 1):
        x, y = map_point(east, north)
        if raid:
            if raid_impacts is None:
                canvas.ellipse((x - 2, y - 2, x + 2, y + 2), fill="#f2ede0")
            continue
        canvas.ellipse((x - radius, y - radius, x + radius, y + radius), outline="white", width=2)
        canvas.line((x - radius - 4, y, x + radius + 4, y), fill="white", width=2)
        canvas.line((x, y - radius - 4, x, y + radius + 4), fill="white", width=2)
        if town and not london:
            text(x + 12, y - 25, str(i), 16)
    for key, (east, north) in (emitters or {}).items():
        x, y = map_point(east, north)
        color = "#ffe479" if split_fx and ("_P1_" in key or "_P4_" in key) else "#75e4ee"
        canvas.ellipse((x - 3, y - 3, x + 3, y + 3), fill=color, outline="#172628")
    if raid_impacts is not None:
        for east, north in impacts:
            x, y = map_point(east, north)
            canvas.ellipse((x - 5, y - 5, x + 5, y + 5), outline="#ffffff", width=2)
    for number, crew in lab.city_crews.items():
        if crew.position is None:
            continue
        x, y = map_point(*crew.position)
        if not (MAP_X <= x < MAP_X + map_side and MAP_Y <= y < MAP_Y + map_side):
            continue
        if crew.target is not None and crew.response.state == "pumping":
            tx, ty = lab.sim.center(crew.target)
            target = map_point(tx + map_east - span / 2, ty + map_north - span / 2)
            canvas.line((x, y, *target), fill="#82b3ff", width=2)
        canvas.rectangle((x - 4, y - 4, x + 4, y + 4), fill="#377ee8", outline="white")
        text(x + 7, y - 12, number, 16, "#b9d8ff")

    grid_label = f"{span:g} m plot · {cell:g} m cells" if grid else "Authored fuel grid · 5 m cells"
    if grid and grid.grass_moisture is not None:
        grid_label += f" · grass moisture {grid.grass_moisture:g}"
    text(32, 596, grid_label, 16, "#a9c6ba")
    text(410, 596, "North up", 16, "#a9c6ba")
    if village and lab.crew is not None:
        status = lab.crew.state.replace("_", " ")
        text(32, 618, f"Fire crew {status}  ·  {lab.crew.pumped_l:.0f} L pumped", 16, "#9fcaff")
    x = 550
    first_fire = scripted_ignitions or (london and not raid)
    text(x, 109, "Elapsed since first fire" if first_fire else "Elapsed since impact", 19, "#a9c6ba")
    awaiting = "Awaiting ignition" if first_fire else "Awaiting impact"
    text(x, 139, awaiting if elapsed is None else f"{int(elapsed) // 60:02}:{int(elapsed) % 60:02}", 36)
    text(x, 187, acceleration, 19, "#a9c6ba")
    east, north = lab.wind
    speed = math.hypot(east, north)
    if speed:
        directions = ("north", "NE", "east", "SE", "south", "SW", "west", "NW")
        bearing = math.atan2(east, north)
        direction = directions[round(bearing / (math.pi / 4)) % len(directions)]
        text(x, 219, f"Wind  {speed:.3g} m/s toward {direction}", 19)
        dx, dy = east / speed, -north / speed
        cx, cy = x + 300, 232
        tip_x, tip_y = cx + 23 * dx, cy + 23 * dy
        base_x, base_y = tip_x - 10 * dx, tip_y - 10 * dy
        color = "#86d6b2"
        canvas.line((cx - 23 * dx, cy - 23 * dy, tip_x, tip_y), fill=color, width=3)
        canvas.polygon([(tip_x, tip_y), (base_x - 6 * dy, base_y + 6 * dx),
                        (base_x + 6 * dy, base_y - 6 * dx)], fill=color)
    else:
        text(x, 219, "Wind calm", 19)
    stats = lab.sim.stats() if lab.sim else {"ignitions": 0, "flaming": 0}
    text(x, 254, f"{stats['ignitions']:3d}  cells ignited", 26)
    text(x, 289, f"{stats['flaming']:3d}  cells flaming", 26)
    if terrain:
        inset, resolution, title = terrain
        if london:
            text(x, 331, title, 19)
            text(x + 174, 363, f"Air temperature  {lab.ambient:g} C", 19)
            if raid_impacts is not None:
                text(x + 174, 392, f"{len(raid_impacts)} impacts · {len(impacts)} selected", 16, "#a9c6ba")
            elif raid:
                label = "scripted ignitions" if scripted_ignitions else "mapped impacts"
                text(x + 174, 392, f"{len(impacts or ())} {label}", 16, "#a9c6ba")
            else:
                text(x + 174, 392, "Damp open ground", 16, "#a9c6ba")
            if city_raid:
                crew_count = 4 if "4" in lab.city_crews else 3
                for number in map(str, range(1, crew_count + 1)):
                    crew = lab.city_crews.get(number)
                    label = "Waiting for dispatch"
                    if crew is not None:
                        response = crew.response
                        label = response.state.replace("_", " ").capitalize()
                        if response.pumped_l > 0:
                            label += f" · {response.pumped_l:.0f} L"
                    text(x + 174, 426 + (int(number) - 1) * 22, f"Pump {number}  {label}", 16, "#b9d8ff")
            elif lab.sim:
                text(x + 174, 439, f"{stats['allocated_cells']:,} cells loaded", 16)
                text(x + 174, 463, f"{stats['potential_cells']:,} potential", 16, "#a9c6ba")
        elif wide:
            outside = 0
            if lab.sim:
                low = (size - round(TOWN_WIDTH / cell)) // 2
                high = size - low
                outside = sum(burning.initial_fuel > burning.fuel and
                              not (low <= i % size < high and low <= i // size < high)
                              for i, burning in lab.sim.cells.allocated.items())
            text(x, 331, f"{outside} cells ignited beyond old grid", 19)
            text(x + 174, 363, "Dashed square", 19)
            text(x + 174, 392, "Former 640 m plot", 16, "#a9c6ba")
            if lab.sim:
                text(x + 174, 439, f"{stats['allocated_cells']:,} cells loaded", 16)
                text(x + 174, 463, f"{stats['potential_cells']:,} potential", 16, "#a9c6ba")
        else:
            text(x, 331, title, 19)
        frame.paste(inset, (x, 357))
        detail = f"Land-cover source {resolution:g} m" if town else f"Woodland source {resolution:g} m" if grid else f"{resolution:g} m per pixel"
        text(x, 517, f"{detail} · white box = {span:g} m plot", 16, "#a9c6ba")
    legend_y = (541 if split_fx else 546) if terrain else 385
    legend_step = 16 if split_fx else 18 if town else 24
    legend = [("Woodland", "woodland"), ("Heating", "heating"), ("Flaming", "flaming"),
              ("Smoldering", "smoldering"), ("Burned", "burned")]
    if grid:
        legend.append(("Open land", "grass"))
        if grid.chart.get("native_scenery"):
            legend.extend((("Road mesh", "road"), ("Building bounds", "masonry")))
        if town:
            legend.append(("Built-up cover", "town_cover"))
            if split_fx:
                legend.extend((("Flame origin", "flame_origin"), ("Smoke origin", "fx_origin")))
            elif emitters is not None:
                legend.append(("FX origin", "fx_origin"))
        if london:
            legend.append(("Water", "water"))
        if raid:
            legend.append(("Scripted ignition" if scripted_ignitions else "Bomb impact", "impact"))
            if raid_impacts is not None:
                legend.append(("Selected for fire", "ignition_impact"))
    for index, (label, color) in enumerate(legend):
        lx, ly = x + index % 2 * 185, legend_y + index // 2 * legend_step
        swatch = 15 if town else 18
        if color in ("fx_origin", "flame_origin"):
            fill = "#ffe479" if color == "flame_origin" else "#75e4ee"
            canvas.ellipse((lx + 4, ly + 4, lx + 11, ly + 11), fill=fill)
        elif color == "impact":
            canvas.ellipse((lx + 5, ly + 5, lx + 10, ly + 10),
                           fill=RAID_IMPACT_COLOR if raid_impacts is not None else "#f2ede0")
        elif color == "ignition_impact":
            canvas.ellipse((lx + 3, ly + 3, lx + 12, ly + 12), outline="#ffffff", width=2)
        else:
            canvas.rounded_rectangle((lx, ly, lx + swatch, ly + swatch), radius=3, fill=COLORS[color])
        text(lx + 28, ly - 3, label, 16 if town else 19)
    return frame


def read_event_log(path):
    events, clocks = [], []
    for line in path.read_text(encoding="ascii").splitlines():
        sequence, seconds, action, *args = line.split("\t")
        stamp = float(seconds)
        if int(sequence) != len(events) + 1:
            raise ValueError("Mission log sequence is incomplete")
        events.append((stamp, action, args))
        if action == "clock" and len(args) == 2:
            clocks.append((float(args[1]), stamp))
    if len(clocks) < 2 or any(a >= b for (a, _), (b, _) in zip(clocks, clocks[1:])):
        raise ValueError("Mission log needs ordered UTC clock samples")
    if not any(action in ("bomb", "ignition") for _, action, _ in events):
        raise ValueError("No accepted ground fire input in this mission log")
    return events, clocks


def read_effect_changes(path):
    changes = []
    for line in path.read_text(encoding="ascii").splitlines():
        fields = line.split()
        if len(fields) == 5 and fields[0] == "plume_created":
            _, key, seconds, east, north = fields
            changes.append((float(seconds), key, (float(east), float(north))))
        elif len(fields) == 3 and fields[0] == "plume_finished":
            _, key, seconds = fields
            changes.append((float(seconds), key, None))
    if not changes:
        raise ValueError("No timestamped CloD effects in flight log")
    return iter(sorted(changes, key=lambda change: change[0]))


def read_raid_impacts(path):
    impacts = []
    for line in path.read_text(encoding="ascii").splitlines():
        match = RAID_IMPACT_PATTERN.match(line)
        if match:
            east, north, seconds = map(float, match.groups())
            impacts.append((seconds, east, north))
    if not impacts:
        raise ValueError("No timestamped in-plot bomb impacts in flight log")
    return sorted(impacts)


def frames(events, clocks, video_start, duration, preview, terrain=None, woodland=None, effects=None, fps=FPS,
           split_fx=False, raid_impacts=None):
    lab = Lab(woodland)
    impacts = []
    impact_at = None
    cursor = 0
    emitters = {} if effects is not None else None
    change = next(effects, None) if effects is not None else None
    effect_version = 0
    rendered_key = None
    rendered_frame = None
    scripted_ignitions = (raid_impacts is None and
                          next((kind for _, kind, _ in events if kind in ("bomb", "ignition")), None) == "ignition")
    utc = [row[0] for row in clocks]
    raid_times = [row[0] for row in raid_impacts] if raid_impacts is not None else None
    for number in range(round(duration * fps)):
        wall = number / fps
        if preview:
            seconds = max(0, (wall - 2) * 12)
            if wall < 2:
                event_limit = -0.5
            else:
                event_limit = seconds
            label = "12x playback"
        else:
            after = min(len(clocks) - 1, max(1, bisect_right(utc, video_start + wall)))
            t0, s0 = clocks[after - 1]
            t1, s1 = clocks[after]
            phase = max(0, min(1, (video_start + wall - t0) / (t1 - t0)))
            seconds = event_limit = s0 + (s1 - s0) * phase
            label = f"{(s1 - s0) / (t1 - t0):.1f}x mission clock observed"
        while cursor < len(events) and events[cursor][0] <= event_limit:
            stamp, action, args = events[cursor]
            lab.handle(max(stamp, lab.clock), action, args)
            if action == "bomb" or (raid_impacts is None and action == "ignition"):
                impacts.append(tuple(map(float, args[-2:])))
                if impact_at is None:
                    impact_at = stamp
            cursor += 1
        if lab.mission_weather is None and preview:
            weather = (list(map(str, (LONDON_TEMP_C, *LONDON_WIND)))
                       if woodland and woodland.center == LONDON_CENTER else ["15", "12", "0"])
            if woodland:
                weather.append(woodland.identity)
            lab.handle(0, "init", weather)
        # Recorded frames use the last completed game sample, matching the sidecar's inputs.
        if preview:
            lab.advance(seconds)
        while change is not None and change[0] <= event_limit:
            _, key, position = change
            if position is None:
                emitters.pop(key, None)
            else:
                emitters[key] = position
            effect_version += 1
            change = next(effects, None)
        visible_count = bisect_right(raid_times, event_limit) if raid_times is not None else 0
        first_impact = (raid_times[0] if visible_count else None) if raid_times is not None else impact_at
        elapsed = None if first_impact is None else max(0, lab.clock - first_impact)
        heading = "Replay from the recorded mission log"
        if preview:
            heading = ("Offline model run · scripted city ignitions" if woodland and woodland.center == LONDON_CENTER else
                       "Offline model preview · simulated SC 250 ignition")
        # The recorded map changes only when a mission or effect sample arrives.
        key = cursor, effect_version, visible_count, label
        if preview or key != rendered_key:
            rendered_frame = render(lab, impacts, elapsed, heading, label, terrain, emitters,
                                    split_fx, scripted_ignitions,
                                    raid_impacts[:visible_count] if raid_impacts is not None else None)
            rendered_key = key
        yield rendered_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--effects-log", type=Path, help="Show live effect origins from the matching flight log")
    parser.add_argument("--show-bomb-impacts", action="store_true",
                        help="Distinguish all logged ground impacts from fire-simulation inputs")
    parser.add_argument("--split-fx", action="store_true", help="Mark flame and smoke origins separately")
    parser.add_argument("--capture-start-utc", type=float)
    parser.add_argument("--game-video", type=Path, help="Put gameplay alongside the recorded fire map")
    parser.add_argument("--terrain-context", type=Path,
                        help="Directory containing the extracted Channel overview and its registration metadata")
    parser.add_argument("--terrain", type=Path, help="Matching chart-derived Hawkinge woodland grid")
    parser.add_argument("--duration", type=float, default=20)
    parser.add_argument("--fps", type=int, choices=(20, 24, 30), default=FPS)
    parser.add_argument("--output", type=Path, default=OUT / "hotseat-capture/hawkinge-map-preview.mp4")
    args = parser.parse_args()
    if args.game_video and not args.events:
        parser.error("--game-video requires the mission log for the same capture")
    if args.effects_log and (not args.events or
                             args.effects_log.stem.removesuffix(".flight") != args.events.stem.removesuffix(".events")):
        parser.error("--effects-log requires the matching mission event log")
    if args.duration <= 0:
        parser.error("--duration must be positive")
    woodland = WoodlandTerrain.load(args.terrain) if args.terrain else None
    if args.show_bomb_impacts and (not args.effects_log or not woodland or woodland.center not in LONDON_RAID_CENTERS):
        parser.error("--show-bomb-impacts requires a London raid grid and its flight log")
    if args.events:
        if args.capture_start_utc is None:
            parser.error("--capture-start-utc is required with --events")
        events, clocks = read_event_log(args.events)
        init = next((values for _, action, values in events if action == "init"), [])
        if woodland and init[3:] != [woodland.identity]:
            parser.error("the provided woodland grid was not used in the recorded mission")
    else:
        x, y = woodland.center if woodland else PLOTS["forest"]
        events = [(0, "bomb", ["SC250", str(x - 20), str(y)])]
        if woodland and woodland.center == LONDON_CENTER:
            events = [(t, "ignition", [str(x), str(y)]) for t, x, y in london_ignitions(woodland)]
        elif woodland and woodland.plot == "town":
            events.extend([(15, "bomb", ["SC250", str(x + 70), str(y + 55)]),
                           (30, "bomb", ["SC250", str(x + 35), str(y + 180)])])
        clocks = []
    terrain = chart_inset(woodland) if woodland else (
        terrain_inset(args.terrain_context) if args.terrain_context else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
               "-pixel_format", "rgb24", "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", str(args.fps),
               "-i", "pipe:0"]
    if args.game_video:
        duration = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(args.game_video)],
            text=True,
        )
        args.duration = min(args.duration, float(duration))
        command += ["-i", str(args.game_video), "-filter_complex",
                    f"[1:v]scale=-2:{HEIGHT},setsar=1,fps={args.fps}[game];"
                    "[game][0:v]hstack=inputs=2:shortest=1[combined]",
                    "-map", "[combined]", "-map", "1:a?", "-c:a", "aac", "-shortest"]
    command += ["-c:v", "libx264", "-preset", "fast", "-crf", "19",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(args.output)]
    with subprocess.Popen(command, stdin=subprocess.PIPE) as encoder:
        for frame in frames(events, clocks, args.capture_start_utc, args.duration, not args.events,
                            terrain, woodland, read_effect_changes(args.effects_log) if args.effects_log else None,
                            fps=args.fps, split_fx=args.split_fx,
                            raid_impacts=read_raid_impacts(args.effects_log) if args.show_bomb_impacts else None):
            encoder.stdin.write(frame.tobytes())
        encoder.stdin.close()
        if encoder.wait():
            raise RuntimeError("FFmpeg did not encode the map")
    print(args.output)


if __name__ == "__main__":
    main()
