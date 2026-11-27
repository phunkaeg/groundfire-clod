"""Prepare the single-mission Channel fuel and tile-seam trial for CloD Steam beta."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from shutil import copy2

from channel_bridge import MAP_FILE, PROTOTYPE, SeamFire
from firesim.fuelmap import FuelMap


HERE = Path(__file__).resolve().parent
MISSION = "GroundFire Channel Three-Site Trial"
TEMPLATE = PROTOTYPE / "missions/day/GroundFire London Live Raid"


def section(text, first, last):
    start = text.index(first)
    return text[start:text.index(last, start + len(first))].rstrip()


def mission_script(fuel, plan):
    prior = TEMPLATE.with_suffix(".cs").read_text(encoding="utf-8-sig")
    template = (HERE / "ChannelFireMission.cs").read_text(encoding="ascii")
    sites = plan["sites"]
    sim = SeamFire(fuel)
    replacements = {
        "DATASET": fuel.metadata["dataset_id"],
        "EAST_MAX": f"{sim.east_max:g}",
        "NORTH_MAX": f"{sim.north_max:g}",
        "WIND_EAST": f"{plan['wind_m_s'][0]:g}",
        "WIND_NORTH": f"{plan['wind_m_s'][1]:g}",
        "SITE_NAMES": ", ".join('"' + s["name"] + '"' for s in sites),
        "CAMERA_XY": ", ".join(f"new Point2d({s['camera'][0]}, {s['camera'][1]})" for s in sites),
        "HEIGHT_BINDING": section(prior, "    private MethodInfo terrainHeight;", "    private string session;"),
        "EFFECT_BINDING": section(prior, "    private void BindEffects()", "    private double? GroundHeight("),
        "EMITTER_FILTER": section(prior, "    // These are the named emitters", "\n}\n"),
        "CAMERA_BINDINGS": section((HERE / "LondonAttackCamera.cs").read_text(encoding="ascii"),
                                   "    private static MethodInfo BindRaidView(", "    private void SelectRaidCamera("),
    }
    for field, body in replacements.items():
        token = f"__{field}__"
        if template.count(token) != 1:
            raise ValueError(f"Invalid Channel mission token {token}")
        template = template.replace(token, body)
    return template


def mission_map(fuel, plan):
    sites = plan["sites"]
    if len(sites) != 3 or any(not re.fullmatch("[A-Za-z]+", s["name"]) for s in sites):
        raise ValueError("The trial requires three named Channel sites")

    observer = "BoB_LW_KG76_II.17"
    formations = [f"BoB_LW_KG76_II.{i}7" for i in range(2, 5)]
    prior = TEMPLATE.with_suffix(".mis").read_text(encoding="utf-8-sig")
    player = section(prior, f"[{observer}]", f"[{observer}_Way]")
    east, north = plan["wind_m_s"]
    lines = [
        "[PARTS]", "  core.100", "  bob.100", "[MAIN]", "  MAP Land$English_Channel_1940",
        "  TIME 10.5", "  WeatherIndex 0", "  CloudsHeight 1600",
        "  BattleArea 0 0 368640 319488 50000", "  player BoB_LW_KG76_II.100",
        "[GlobalWind_0]", f"  Power {east:.3f} {north:.3f} 0.000",
        "  BottomBound 0", "  TopBound 1800", "  GustPower 0", "  GustAngle 0",
        "[AirGroups]", f"  {observer}",
        *[f"  {formation}" for formation in formations], player,
        f"[{observer}_Way]", "  NORMFLY 229500 232000 2000 360",
        "  NORMFLY 234000 240000 2000 360", "  NORMFLY 244000 249000 2000 360",
    ]
    sim = SeamFire(fuel)
    for index, (site, group) in enumerate(zip(sites, formations)):
        x, y = site["aim_xy"]
        if not sim.contains(x, y) or fuel.sample(x, y)["kind"] not in ("woodland", "grass", "masonry"):
            raise ValueError(f"{site['name']} is not on usable fuel")
        seam = site.get("seam_east_m")
        if seam is not None and (seam % (sim.pixel_m * sim.tile_pixels) != 0 or not 20 <= seam - x <= 150):
            raise ValueError("Hawkinge aim must lie west of an actual vertical fuel tile seam")
        lines.extend([
            f"[{group}]", "  Flight0  B", "  Class Aircraft.Ju-88A-1", f"  CallSign {21 + index}",
            "  BombSpacing 20", "  Fuel 55", "  Weapons 1 1 1 3 1 1",
            "  Skill 0.95 0.95 0.95 0.95 0.95 0.95 0.95 0.95",
            f"[{group}_Way]",
            f"  NORMFLY {x:.2f} {y-site['approach_m']:.2f} 1200.00 360.00",
            f"  GATTACK_POINT {x:.2f} {y:.2f} 1200.00 360.00 /GAttackType LEVEL",
            f"  NORMFLY {x:.2f} {y+5000:.2f} 1200.00 360.00",
            f"  NORMFLY {x-2600:.2f} {y+12000:.2f} 1800.00 360.00",
        ])
    lines += ["[CustomChiefs]", "[Stationary]", "[Buildings]", "[BuildingsLinks]", "[StaticCamera]"]
    for i, site in enumerate(sites):
        lines.append(f"  StaticCamera_{i} " + " ".join(map(str, site["camera"])) + " 0 0")
    return "\n".join(lines) + "\n"


def write_trial(db, destination, plan_path):
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    mission = destination / "mission"
    bridge = destination / "bridge"
    mission.mkdir(parents=True, exist_ok=True)
    (bridge / "terrain").mkdir(parents=True, exist_ok=True)
    fuel = FuelMap(db)
    try:
        (mission / f"{MISSION}.mis").write_text(mission_map(fuel, plan), encoding="ascii")
        (mission / f"{MISSION}.cs").write_text(mission_script(fuel, plan), encoding="ascii")
        info = dict(plan, fuel_dataset=fuel.metadata["dataset_id"],
                    fuel_db_sha256=hashlib.sha256(db.read_bytes()).hexdigest(),
                    build="Steam vrbeta build 25283265", mission=MISSION)
    finally:
        fuel.close()
    (mission / f"{MISSION}.briefing").write_text(
        f"[Info]\n<Name>\n{MISSION}\n<Description>\n"
        "Start Launch Channel Bridge.cmd before entering flight. Three AI Ju 88s make live "
        "bombing runs near Hawkinge, Tangmere and Calais. The first camera watches the Hawkinge "
        "fuel tile seam. Use the Mission orders menu to change camera. The bridge records impacts "
        "and adjacent-cell spread across the seam.\n", encoding="ascii")
    (destination / "trial-plan.json").write_text(json.dumps(info, indent=2) + "\n", encoding="ascii")
    copy2(db, bridge / "terrain" / MAP_FILE)
    (bridge / "integrations/clod").mkdir(parents=True, exist_ok=True)
    (bridge / "firesim").mkdir(exist_ok=True)
    for filename in ("channel_bridge.py", "fire_lab.py", "hawkinge.py"):
        copy2(HERE / filename, bridge / "integrations/clod" / filename)
    for source in (PROTOTYPE / "firesim").glob("*.py"):
        copy2(source, bridge / "firesim" / source.name)
    (bridge / "Launch Channel Bridge.cmd").write_bytes(
        b'@echo off\r\npy -3 -B "%~dp0integrations\\clod\\channel_bridge.py"\r\nif errorlevel 1 pause\r\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fuel_map", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--plan", type=Path, default=HERE / "channel_trial_plan.json")
    args = parser.parse_args()
    write_trial(args.fuel_map, args.destination, args.plan)


if __name__ == "__main__":
    main()
