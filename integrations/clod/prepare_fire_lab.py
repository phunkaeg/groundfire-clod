"""Compile and optionally stage the offline Hawkinge Fire Lab mission variants."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from fire_lab import PLOTS
from hawkinge import CORE, CSC, HERE, OUT, PROTOTYPE, single_missions_folder
from prepare_bomb_range import ASSEMBLIES, NAME as RANGE, keys, run_checked, section, verify_loadouts

NAME = "GroundFire Hawkinge Fire Lab"
BUILD = OUT / "fire-lab"
LIGHTS = {"": 10, " - Dawn": 4.75, " - Dusk": 20.75, " - Night": 1}


def mission_variants():
    template = (HERE / (RANGE + ".mis")).read_text(encoding="utf-8")
    briefing = (HERE / (RANGE + ".briefing")).read_text(encoding="utf-8")
    profiles = verify_loadouts(template, briefing)
    wind = keys(section(template, "GlobalWind_0"), "Power")[0].split()
    climate = json.loads((PROTOTYPE.parent / "clod-map/output/seasonal-configurations.json").read_text())
    temperature = climate["summer"]["WORLDPOS"]["temperature"]
    climate_data = "\\t".join((temperature, *wind[:2]))
    centers = ", ".join("{ %d, %d }" % (x, y) for x, y in PLOTS.values())
    source = (HERE / "HawkingeFireLab.cs").read_text(encoding="utf-8")
    source = source.replace("__ENVIRONMENT__", climate_data).replace("__CENTERS__", centers)
    if "__ENVIRONMENT__" in source or "__CENTERS__" in source:
        raise ValueError("Unresolved mission settings")

    # Both single-seat flights use the same forest approach, with 350 m lateral separation.
    route = re.sub(r"NORMFLY [0-9.]+ (232745|232980|232695)\.00",
                   lambda m: {"232745": m[0].replace("232745", "232385"),
                              "232980": m[0].replace("232980", "232735"),
                              "232695": m[0].replace("232695", "232735")}[m[1]], template)
    stationary = ["[Stationary]"]
    cameras = ["[StaticCamera]"]
    for i, (x, y) in enumerate(PLOTS.values(), 1):
        stationary.append(f"  Static72{i:02} Stationary.Environment.TentBell_UK1 gb {x:.2f} {y:.2f} 90.00")
        cameras.append(f"  StaticCamera_{i - 1} {x - 80} {y - 70} 65")
    # A contrasting airfield-side aim point marks the tested forest clearing.
    stationary += ["  Static7291 Stationary.Environment.TentBell_UK1 gb 235437.00 232385.00 90.00",
                   "  Static7292 Stationary.Environment.TentBell_UK1 gb 235473.00 232385.00 90.00"]
    route = route.split("[Stationary]", 1)[0] + "\n".join(stationary + cameras) + "\n"

    files = {}
    for label, hour in LIGHTS.items():
        name = NAME + label
        mission = re.sub(r"(?m)^  TIME .+$", f"  TIME {hour}", route)
        descriptions = f"""[Info]
<Name>
Hawkinge Fire Lab{label}
<Description>
Offline ground-fire test. Open the Hawkinge Fire Lab bridge before starting the mission and leave it running. Once airborne, open Tab, then 4 Mission. If the game does not show Mission orders, use the bridge console. Type help there for commands.

Start one to three fires in forest, field or town fuel. Compare two hedgerows, a row of houses and a factory bay. Use wind, weather and fire clock to repeat a test. The fire multiplier follows mission time. The test wind, temperature and rain controls affect the fire model. This mission's start time sets the game lighting.

Forest tents east of Hawkinge are near map grid coordinates 235455, 232385. The other plots are at 234503, 232745 (field), 235450, 232700 (hedge) and 236864, 230456 (built-up). Use Custom to choose a bomb rack. Restart or clear the plot for like-for-like comparisons. Fire visuals use stock smoke, which fades after the source is stopped.
[1]
<Name>
SC 50 | four light bombs
<Description>
Stock Bf 109 E-4/B fit. A recognised ground detonation near the forest tents adds heat to the fire model.
[2]
<Name>
SC 250 | one heavy bomb
<Description>
Stock Bf 109 E-4/B fit. Use the same forest plot to compare with the SC 50.
"""
        for suffix, value in (("mis", mission), ("briefing", descriptions), ("cs", source)):
            files[f"{name}.{suffix}"] = value.encode("ascii")
        assert float(keys(section(mission, "MAIN"), "TIME")[0]) == hour
        assert section(mission, "GlobalWind_0") == section(template, "GlobalWind_0")
        for group in profiles:
            assert section(mission, group) == section(template, group)
    return files, profiles


def write_files(folder, files, *, stage=False):
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        target = folder / name
        if stage and target.exists() and target.read_bytes() != data:
            raise FileExistsError(f"Different file already exists at {target}")
    for name, data in files.items():
        target = folder / name
        if not stage or not target.exists():
            with target.open("xb" if stage else "wb") as stream:
                stream.write(data)
        if target.read_bytes() != data:
            raise OSError(f"File did not verify at {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", action="store_true")
    options = parser.parse_args()
    files, profiles = mission_variants()
    launch = "Launch Hawkinge Fire Lab Bridge.cmd"
    launcher = (f'@echo off\r\n"{Path(sys.executable)}" -B "{HERE / "fire_lab.py"}"\r\n'
                'if errorlevel 1 pause\r\n').encode("ascii")
    write_files(BUILD, {**files, launch: launcher})
    run_checked([CSC, "/nologo", "/platform:x64", "/target:library",
                 "/out:" + str(BUILD / "HawkingeFireLab.dll"),
                 *("/reference:" + str(CORE / assembly) for assembly in ASSEMBLIES),
                 BUILD / (NAME + ".cs")])
    destination = single_missions_folder() if options.stage else None
    if destination:
        write_files(destination, files, stage=True)
    report = {
        "mission_compiled": True, "game_launched": False,
        "staged_directory": str(destination) if destination else None,
        "start_hours": {NAME + label: hour for label, hour in LIGHTS.items()},
        "stock_loadouts": profiles,
        "sha256": {key: hashlib.sha256(data).hexdigest() for key, data in files.items()},
    }
    (BUILD / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "sha256"}, indent=2))


if __name__ == "__main__":
    main()
