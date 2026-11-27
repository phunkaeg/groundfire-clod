"""Audit a recorded Channel trial and draw its actual captured fire spread."""
import argparse
from bisect import bisect_right
import csv
from functools import lru_cache
import json
import math
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFont

from channel_bridge import ChannelRun, events, FuelMap


FONT_ROOT = Path("C:/Windows/Fonts")
LAND = {"woodland": "#355c42", "grass": "#6d8053", "masonry": "#896e56", "water": "#2c526b"}
STATE = {"heating": "#ac994e", "flaming": "#fb863d", "smoldering": "#ae775f", "burned": "#594644"}
WIDTH, HEIGHT = 2240, 670
FPS = 15


def read_log(path):
    with path.open("rb") as stream:
        data = [(seq, clock, kind, args) for seq, clock, kind, args, _ in events(stream)]
    if not data or any(seq != i for i, (seq, *_) in enumerate(data, 1)):
        raise ValueError("Incomplete or out-of-order mission log")
    return data


def replay(data, fuel, session):
    run = ChannelRun(fuel, session)
    for row in data:
        run.handle(*row)
    return run


def site_for(impact, sites):
    point = (impact["east"], impact["north"])
    site = min(sites, key=lambda s: math.dist(point, s["aim_xy"]))
    return site["name"] if math.dist(point, site["aim_xy"]) <= 3600 else "outside site views"


def report(run, sites):
    counts = {s["name"]: dict(impacts=0, heated_impacts=0, weapons={}) for s in sites}
    for impact in run.impacts:
        name = site_for(impact, sites)
        if name not in counts:
            continue
        row = counts[name]
        row["impacts"] += 1
        row["heated_impacts"] += impact["heated"] > 0
        weapon = impact["weapon"]
        row["weapons"][weapon] = row["weapons"].get(weapon, 0) + 1
    hawkinge = sites[0]
    seam = hawkinge["seam_east_m"]
    crossings = [ex for ex in run.sim.crossings
                 if ex["source_xy"][0] < seam <= ex["receiver_xy"][0] and
                 math.dist(ex["receiver_xy"], hawkinge["aim_xy"]) <= 1800]
    return dict(session=run.session, duration=run.clock, sites=counts,
                hawkinge_crossing=crossings[0] if crossings else None,
                allocated_cells=run.sim.stats()["allocated_cells"])


def plotted_sites(sites, impacts):
    views = []
    for site in sites:
        hits = [i for i in impacts if site_for(i, sites) == site["name"]]
        if not hits:
            views.append(dict(site, map_xy=site["camera"][:2], span=900))
            continue
        xs, ys = [i["east"] for i in hits], [i["north"] for i in hits]
        east = site.get("seam_east_m", (min(xs) + max(xs)) / 2)
        north = (min(ys) + max(ys)) / 2
        span = max(900, max(2 * abs(x-east) for x in xs) + 320, max(ys)-min(ys) + 320)
        views.append(dict(site, map_xy=[east, north], span=math.ceil(span/20)*20))
    return views


@lru_cache(maxsize=6)
def backdrop(fuel, x0, y0, span):
    side = span // 10
    land = Image.new("RGB", (side, side))
    for y in range(side):
        for x in range(side):
            kind = fuel.sample(x0 + x*10 + 5, y0 + y*10 + 5)["kind"]
            land.putpixel((x, side-1-y), tuple(bytes.fromhex(LAND.get(kind, "#263136")[1:])))
    return land.resize((480, 480), Image.Resampling.NEAREST)


def render_frame(run, frame_path, site, clock):
    frame = Image.new("RGB", (WIDTH, HEIGHT), "#142025")
    if frame_path:
        with Image.open(frame_path) as captured:
            frame.paste(captured.convert("RGB").resize((1600, HEIGHT), Image.Resampling.BILINEAR), (0, 0))
    ink = ImageDraw.Draw(frame)
    small = ImageFont.truetype(FONT_ROOT / "segoeui.ttf", 20)
    label = ImageFont.truetype(FONT_ROOT / "seguisb.ttf", 24)
    large = ImageFont.truetype(FONT_ROOT / "seguisb.ttf", 35)
    fx, fy, span, pixels = 1628, 110, site["span"], 480
    scale = pixels / span
    ax, ay = site["map_xy"]
    x0, y0 = 10 * math.floor((ax - span/2)/10), 10 * math.floor((ay - span/2)/10)

    def point(x, y):
        return fx + (x - x0)*scale, fy + (y0 + span - y)*scale

    def visible(x, y):
        return x0 <= x < x0+span and y0 <= y < y0+span

    ink.text((fx, 17), site["name"], fill="#f0f5f2", font=large)
    ink.text((fx, 64), "Recorded impacts and simulated spread", fill="#b5d1c7", font=small)
    frame.paste(backdrop(run.fuel,x0,y0,span), (fx,fy))
    for index,cell in run.sim.cells.allocated.items():
        if cell.state not in STATE:
            continue
        x,y = run.sim.center(index)
        if visible(x,y):
            ink.rectangle((*point(x-5,y+5),*point(x+5,y-5)), fill=STATE[cell.state])
    for impact in run.impacts:
        x,y = impact["east"],impact["north"]
        if visible(x,y):
            px,py=point(x,y)
            ink.ellipse((px-2,py-2,px+2,py+2),fill="#efe8d2")
    seam = site.get("seam_east_m")
    if seam is not None and visible(seam, ay):
        x, _ = point(seam, ay)
        ink.line((x, fy, x, fy+pixels), fill="#ecf4f0", width=2)
        ink.text((x+6, fy+8), "Fuel tile seam", fill="#ffffff", font=small, stroke_width=1,
                 stroke_fill="#142025")
        for cross in run.sim.crossings:
            x, y = cross["receiver_xy"]
            if cross["source_xy"][0] < seam <= x and visible(x, y) and clock >= cross["mission_s"]:
                px, py = point(x, y)
                ink.ellipse((px-6, py-6, px+6, py+6), outline="white", width=2)
                ink.text((fx, 626), f"Spread across seam at {cross['mission_s']:.1f} s", fill="#b6e7cd", font=label)
                break
    site_hits = sum(site_for(impact, [site]) == site["name"] for impact in run.impacts)
    year = f"{int(clock)//60:02}:{int(clock)%60:02}"
    ink.text((fx, 598), f"Mission {year}  |  {site_hits} impacts  |  North up", fill="#e4f0eb", font=small)
    return frame


def video(data, fuel, session, shots, sites, target, start, duration, segments=None):
    clocks = [row for row in data if row[2] == "clock"]
    times = [float(row[3][-1]) for row in clocks]
    with (shots / "frames.tsv").open() as stream:
        frames = [(float(stamp), shots / name) for name, stamp in csv.reader(stream, delimiter="\t")]
    stamps = [stamp for stamp, _ in frames]
    if segments:
        by_clock = [row[1] for row in clocks]
        timeline = [(times[max(0,bisect_right(by_clock,a)-1)], times[min(len(times)-1,bisect_right(by_clock,b)-1)])
                    for a,b in segments]
    else:
        first = next(wall for row,wall in zip(clocks, times) if row[1] >= start)
        timeline = [(first, min(first+duration, times[-1]))]
    samples = (begin + i/FPS for begin,end in timeline
               for i in range(max(0,int((min(end,stamps[-1])-begin)*FPS))))
    keyframes = {s["name"]:s for s in sites}
    run = ChannelRun(fuel, session)
    cursor = 0

    # A frame's wall clock is matched to the game clock that was actually observed.
    args = ["ffmpeg","-hide_banner","-loglevel","error","-y","-f","rawvideo","-pixel_format","rgb24",
            "-video_size",f"{WIDTH}x{HEIGHT}","-framerate",str(FPS),"-i","pipe:0","-c:v","libx264",
            "-preset","fast","-crf","20","-pix_fmt","yuv420p","-movflags","+faststart",str(target)]
    with subprocess.Popen(args, stdin=subprocess.PIPE) as encoder:
        for wall in samples:
            position = max(0, min(len(times)-1,bisect_right(times,wall)-1))
            clock, region = clocks[position][1], clocks[position][3][2]
            while cursor < len(data) and data[cursor][1] <= clock:
                run.handle(*data[cursor])
                cursor += 1
            i_shot = max(0,min(len(stamps)-1,bisect_right(stamps,wall)-1))
            encoder.stdin.write(render_frame(run,frames[i_shot][1],keyframes[region],clock).tobytes())
        encoder.stdin.close()
        if encoder.wait():
            raise RuntimeError("FFmpeg could not write Channel replay")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("fuel_map", type=Path)
    parser.add_argument("trial_plan", type=Path)
    parser.add_argument("--frames", type=Path)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--start", type=float, default=20)
    parser.add_argument("--duration", type=float, default=180)
    parser.add_argument("--segments", help="Comma-separated mission-time ranges, for example 40:95,133:150")
    args = parser.parse_args()
    sites = json.loads(args.trial_plan.read_text())["sites"]
    data = read_log(args.events)
    session = args.events.name.split(".")[0]
    fuel = FuelMap(args.fuel_map)
    try:
        result = replay(data, fuel, session)
        print(json.dumps(report(result, sites), indent=2), flush=True)
        if args.frames and args.video:
            segments = [tuple(map(float,s.split(":"))) for s in args.segments.split(",")] if args.segments else None
            video(data, fuel, session, args.frames, plotted_sites(sites,result.impacts),
                  args.video, args.start, args.duration, segments)
    finally:
        fuel.close()


if __name__ == "__main__":
    main()
