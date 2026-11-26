"""Compile, stage and run the single-player Hawkinge fire test."""
import argparse
from contextlib import closing
import ctypes
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

HERE = Path(__file__).resolve().parent
PROTOTYPE = HERE.parents[1]
sys.path.insert(0, str(PROTOTYPE))

from firesim.fuelmap import FuelMap
from firesim.sparse import SparseFireSim

CORE = Path("G:/SteamLibrary/steamapps/common/IL-2 Sturmovik Cliffs of Dover Blitz/parts/core")
DATABASE = PROTOTYPE.parent / "clod-map/output/channel-fuel.sqlite"
CSC = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
OUT = PROTOTYPE / "output/clod/hawkinge"
MISSION = "GroundFire Hawkinge"
OWNED_MISSION = "GroundFire Hawkinge Lifecycle"
X, Y = 235455, 232385
IGNITE_AT = 8
SUPPRESS_AT = 38
STEP = 0.5


class FireTest:
    def __init__(self, fuel):
        meta = fuel.metadata
        self.sim = SparseFireSim(
            math.ceil(meta["width"] * meta["pixel_size_m"] / 10),
            math.ceil(meta["height"] * meta["pixel_size_m"] / 10),
            fuel_at=fuel.provider(),
            provider_id=fuel.provider_identity(),
        )
        self.last_tick = 0
        self.stage = "off"

    def advance(self, seconds):
        target = int(min(seconds, 90) / STEP)
        while self.last_tick < target:
            self.last_tick += 1
            elapsed = self.last_tick * STEP
            if elapsed == IGNITE_AT:
                self.sim.ignite(X, Y, 12, 600, event_id="hawkinge-timed-test")
            if elapsed == SUPPRESS_AT:
                self.sim.suppress(X, Y, 160, 65000)
            self.sim.step(STEP)
        flames = [
            self.sim.cells[index].intensity for index in self.sim.active
            if self.sim.cells[index].state == "flaming"
        ]
        if not flames:
            self.stage = "off"
        elif max(flames) >= 0.60 or self.stage == "large":
            self.stage = "large"
        else:
            self.stage = "small"
        return self.stage


def publish(directory, session, sequence, seconds, mode):
    temp = directory / "desired.tmp"
    target = directory / "desired.tsv"
    temp.write_text(f"{session}\t{sequence}\t{seconds:.6f}\t{mode}\n", encoding="ascii")
    for attempt in range(10):
        try:
            temp.replace(target)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.02)


def compile_mission(name):
    OUT.mkdir(parents=True, exist_ok=True)
    stem = name.replace(" ", "")
    command = [str(CSC), "/nologo", "/target:library", "/platform:x64",
               "/out:" + str(OUT / f"{stem}.dll")]
    command.extend("/reference:" + str(CORE / name) for name in ("gameWorld.dll", "core.dll", "part.dll"))
    command.append(str(HERE / f"{name}.cs"))
    result = subprocess.run(command, capture_output=True, timeout=40)
    log = OUT / ("compile-lifecycle.log" if name == OWNED_MISSION else "compile.log")
    log.write_bytes(result.stdout + result.stderr)
    result.check_returncode()


def single_missions_folder():
    documents = ctypes.create_unicode_buffer(260)
    result = ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, documents)
    if result != 0:
        raise OSError(f"Unable to locate Documents: 0x{result & 0xffffffff:08x}")
    profile = Path(documents.value) / "1C SoftClub/il-2 sturmovik cliffs of dover"
    if not profile.is_dir():
        raise FileNotFoundError(profile)
    return profile / "missions/Single"


def stage_mission(name):
    destination = single_missions_folder()
    mission = (HERE / f"{MISSION}.mis").read_bytes()
    if name == OWNED_MISSION:
        mission += (
            b"\n[Stationary]\n"
            b"  Static7102 Stationary.Environment.TentBell_UK1 gb 235455 232385 0.00\n"
            b"  Static7103 Stationary.Environment.TentBell_UK1 gb 235455 232475 0.00\n"
        )
    files = {
        destination / f"{name}.mis": mission,
        destination / f"{name}.cs": (HERE / f"{name}.cs").read_bytes(),
    }
    for target, content in files.items():
        if target.exists() and target.read_bytes() != content:
            raise FileExistsError(f"Existing mission differs: {target}")
    destination.mkdir(parents=True, exist_ok=True)
    for target, content in files.items():
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(content)
    print(f"Staged {name} in {destination}", flush=True)


def replay(fuel):
    test = FireTest(fuel)
    transitions = []
    previous = None
    with TemporaryDirectory(prefix="groundfire-hawkinge-") as temporary:
        directory = Path(temporary)
        for seconds in range(91):
            stage = test.advance(seconds)
            if stage != previous:
                sequence = seconds + 1
                publish(directory, "0" * 32, sequence, seconds, stage)
                data = (directory / "desired.tsv").read_text().strip().split("\t")
                assert data == ["0" * 32, str(sequence), f"{seconds:.6f}", stage]
                transitions.append({"seconds": seconds, "mode": stage, "ignited": test.sim.ignitions})
                previous = stage
    assert [item["mode"] for item in transitions] == ["off", "small", "large", "off"], transitions
    report = {"transitions": transitions, "stats": test.sim.stats(), "game_connected": False}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "offline-replay.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


def live(fuel, directory, wait_seconds):
    directory.mkdir(parents=True, exist_ok=True)
    clock = directory / "clock.tsv"
    started = time.time()
    deadline = time.monotonic() + wait_seconds
    test = None
    current_session = None
    last_seconds = -1
    sequence = 0
    last_mode = None
    print(f"Waiting for the Hawkinge mission clock in {directory}", flush=True)
    while time.monotonic() < deadline:
        try:
            stat = clock.stat()
            if stat.st_mtime + 2 >= started:
                incoming_session, seconds_text = clock.read_text(encoding="utf-8-sig").strip().split("\t")
                seconds = float(seconds_text)
                if re.fullmatch("[0-9a-f]{32}", incoming_session) and math.isfinite(seconds) and seconds >= 0:
                    if incoming_session != current_session:
                        test = FireTest(fuel)
                        current_session = incoming_session
                        last_seconds = -1
                        sequence = 0
                        last_mode = None
                    if seconds > last_seconds:
                        sequence += 1
                        mode = test.advance(seconds)
                        publish(directory, current_session, sequence, seconds, mode)
                        last_seconds = seconds
                        if mode != last_mode:
                            print(f"{seconds:5.1f}s {mode} ({test.sim.ignitions} ignitions)", flush=True)
                            last_mode = mode
                        if seconds >= 75:
                            return
        except (OSError, ValueError):
            # Missing/locked files and incomplete clock observations are retried.
            pass
        time.sleep(0.2)
    raise TimeoutError(f"Mission did not reach 75 seconds before timeout. Last clock: {last_seconds}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "replay", "watch"))
    parser.add_argument("--lifecycle", action="store_true", help="Use the owned-emitter test mission")
    parser.add_argument("--wait", type=float, default=420)
    args = parser.parse_args()
    if args.action == "prepare":
        name = OWNED_MISSION if args.lifecycle else MISSION
        compile_mission(name)
        stage_mission(name)
        return
    with closing(FuelMap(DATABASE)) as fuel:
        if args.action == "replay":
            replay(fuel)
        else:
            local_appdata = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
            directory = Path(local_appdata) / "GroundFireHawkinge"
            if args.lifecycle:
                directory /= "lifecycle"
            live(fuel, directory, args.wait)


if __name__ == "__main__":
    main()
