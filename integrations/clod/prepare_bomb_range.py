"""Build, check and optionally copy the self-contained Hawkinge range into Single."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from hawkinge import CORE, CSC, HERE, OUT, PROTOTYPE, single_missions_folder

sys.path.insert(0, str(PROTOTYPE.parent / "clod-map/tools"))
from sfs import SFS

NAME = "GroundFire Hawkinge Bomb Range"
BUILD = OUT / "bomb-range"
RESPONSE = HERE / "HawkingeRangeResponse.cs"
CHECKS = HERE / "HawkingeRangeChecks.cs"
ASSEMBLIES = ("gameWorld.dll", "core.dll", "part.dll")


def run_checked(command):
    result = subprocess.run([str(value) for value in command], capture_output=True, timeout=40)
    output = (result.stdout + result.stderr).decode(errors="replace")
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} exited {result.returncode}\n{output}")
    return output


def section(text, name):
    match = re.search(r"^\[" + re.escape(name) + r"\]\s*\n([^[]*)", text, re.M)
    if not match:
        raise ValueError(f"Missing mission or game-data section {name}")
    return match[1].splitlines()


def keys(lines, name):
    return [line.strip().split(maxsplit=1)[1] for line in lines
            if re.match(r"^\s*" + re.escape(name) + r"\s+", line)]


def verify_loadouts(mission, briefing):
    archive = CORE.parent / "bob/files.SFS"
    with SFS(archive) as sfs:
        loadout_source = sfs.read(sfs.entries[590]).decode("cp1252")
    aircraft_class = section(loadout_source, "Bf-109E-4B")
    rack = keys(section(loadout_source, "Bf-109E-4B_BombRack"), "loadout")
    player = keys(section(mission, "MAIN"), "player")[0]
    groups = [line.strip() for line in section(mission, "AirGroups") if line.strip()]
    if len(groups) != 2:
        raise ValueError("Expected exactly two selectable air groups")
    variants = (("4xSC50", "Bomb.SC-50_GradeII_J"), ("SC250", "Bomb.SC-250_Type1_J"))
    profiles = {}
    for number, (group, (rack_name, bomb)) in enumerate(zip(groups, variants), 1):
        fields = section(mission, group)
        assert keys(fields, "Class") == ["Aircraft.Bf-109E-4B"]
        index = list(map(int, keys(fields, "Weapons")[0].split()))[2]
        assert rack[index].split()[0] == rack_name and "Gun " + bomb in rack[index]
        assert any(row.rstrip().endswith("Bf-109E-4B_BombRack " + rack_name) for row in aircraft_class)
        assert keys(fields, "Detonator")[0].split()[0] == bomb
        assert keys(fields, "Briefing") == [str(number)] and section(briefing, str(number))
        assert len(keys(section(mission, group + "_Way"), "NORMFLY")) >= 2
        profiles[group] = {"rack_index": index, "munition_entry": bomb}
    assert player == groups[0].rsplit(".", 1)[0] + ".310"
    stationary = section(mission, "Stationary")
    assert sum("Stationary.Environment.TentBell_UK1" in line for line in stationary) == 5
    assert any("Static7101 " in line and "234503.00 232745.00" in line for line in stationary)
    return profiles


def build():
    BUILD.mkdir(parents=True, exist_ok=True)
    source = (HERE / f"{NAME}.cs").read_text(encoding="utf-8")
    response = RESPONSE.read_text(encoding="utf-8")
    files = {suffix: (HERE / f"{NAME}.{suffix}").read_bytes() for suffix in ("mis", "briefing")}
    profiles = verify_loadouts(files["mis"].decode(), files["briefing"].decode())
    files["cs"] = (source.rstrip() + "\n\n" + response.rstrip() + "\n").encode()
    for suffix, data in files.items():
        (BUILD / f"{NAME}.{suffix}").write_bytes(data)

    compiler = [CSC, "/nologo", "/platform:x64"]
    dll = BUILD / "HawkingeBombRange.dll"
    run_checked([*compiler, "/target:library", "/out:" + str(dll),
                 *("/reference:" + str(CORE / assembly) for assembly in ASSEMBLIES),
                 BUILD / f"{NAME}.cs"])
    check_exe = BUILD / "HawkingeRangeChecks.exe"
    run_checked([*compiler, "/target:exe", "/out:" + str(check_exe), RESPONSE, CHECKS])
    output = run_checked([check_exe])
    water = {}
    for line in output.splitlines():
        bomb, seconds, litres = line.split()
        water[bomb] = {"pumping_seconds_rounded_up": int(seconds), "pumped_litres": float(litres)}
    assert set(water) == {"SC50", "SC250"}
    return files, {"game_launched": False, "mission_compiled": True,
                   "loadouts": profiles, "synthetic_pump_replay": water}


def stage(files):
    destination = single_missions_folder()
    targets = {destination / f"{NAME}.{suffix}": data for suffix, data in files.items()}
    for target, data in targets.items():
        if target.exists() and target.read_bytes() != data:
            raise FileExistsError(f"Different file already exists: {target}")
    destination.mkdir(parents=True, exist_ok=True)
    for target, data in targets.items():
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(data)
        if target.read_bytes() != data:
            raise OSError(f"Staged file did not verify: {target}")
    return str(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", action="store_true", help="Copy the checked mission into Single")
    args = parser.parse_args()
    files, report = build()
    report["sha256"] = {suffix: hashlib.sha256(data).hexdigest() for suffix, data in files.items()}
    report["staged_directory"] = stage(files) if args.stage else None
    (BUILD / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
