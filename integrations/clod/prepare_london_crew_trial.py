"""Build a controlled CloD crew trial using the accepted impacts of a recorded raid."""
import argparse
import csv
from decimal import Decimal
from pathlib import Path
import re

from fire_lab import WoodlandTerrain
from prepare_hotseat_capture import city_crew_script


def replace_one(source, before, after):
    if source.count(before) != 1:
        raise ValueError(f"Expected one source anchor: {before}")
    return source.replace(before, after)


def build(source, log, routes, terrain, destination, name, follow_pump=None):
    events = []
    with log.open(encoding="ascii") as stream:
        for _, stamp, action, *fields in csv.reader(stream, delimiter="\t"):
            if action == "bomb":
                kind, east, north = fields
                if kind not in {"SC50", "SC250"}:
                    raise ValueError(f"Unsupported impact profile: {kind}")
                events.append((Decimal(stamp), kind, Decimal(east), Decimal(north)))
    if not events or any(a[0] > b[0] for a, b in zip(events, events[1:])):
        raise ValueError("Impact times must be ordered")
    offset = events[0][0] - Decimal("20.01")
    fixture = []
    for stamp, kind, east, north in events:
        if not all(value.is_finite() for value in (stamp, east, north)):
            raise ValueError("Non-finite impact event")
        fixture.append(f'        new Impact({stamp-offset:f}, "{kind}", {east:f}, {north:f}),')

    script = source.with_suffix(".cs").read_text(encoding="utf-8-sig")
    plan = city_crew_script("            ReadFrame(now);", terrain, routes, follow_pump)
    anchor = r"    private static readonly Point2d\[\]\[\] CityRoutes = \{.*?    \};"
    match = re.search(anchor, plan, flags=re.S)
    script, edits = re.subn(anchor, lambda _: match[0], script, flags=re.S)
    if edits != 1:
        raise ValueError("Missing crew routes in the trial template")

    # Game ignition events are excluded. The fixture drives only the fire bridge.
    before = script.index("    public override void OnBombExplosion(")
    after = script.index("    public override void OnTickGame()", before)
    script = script[:before] + script[after:]
    script = replace_one(script, '            Record("clock\\t"', '            ApplyImpactFixture(now);\n            Record("clock\\t"')
    script = replace_one(script, "if (cityAlarmAt < 0 && effects.Count > 0)\n            cityAlarmAt = now;",
                         "if (cityAlarmAt < 0 && nextFixtureImpact != 0)\n            cityAlarmAt = FixedImpacts[0].Time;")
    script = replace_one(script, "private void Record(string command)\n    {",
                         "private void Record(string command) { RecordAt(Now, command); }\n\n"
                         "    private void RecordAt(double stamp, string command)\n    {")
    script = replace_one(script, "sequence + 1, Now, command", "sequence + 1, stamp, command")
    script = replace_one(script, "            bool stopped = vehicle.IsTaskComplete() || pump.StillSamples >= 3;",
                         "            ObserveTrialPose(i + 1, vehicle, p, now);\n"
                         "            bool stopped = vehicle.IsTaskComplete() || pump.StillSamples >= 3;")
    extension = Path(__file__).with_name("LondonCrewTrial.cs").read_text(encoding="ascii")
    script += "\n" + extension.replace("__IMPACTS__", "\n".join(fixture))
    if follow_pump is not None:
        script = "#define LONDON_CREW_CAMERA\n" + replace_one(
            script, "__CREW_CAMERA_NUMBER__", str(follow_pump))

    mission = source.with_suffix(".mis").read_text(encoding="utf-8-sig")
    # Keep the proven player slot and aircraft configuration, with a fly-through waypoint.
    mission, count = re.subn(r"(?m)^  GATTACK_POINT (.*?) /GAttackType LEVEL$",
                             r"  NORMFLY \1", mission)
    if count != 1 or re.search(r"(?m)^\s*GATTACK", mission):
        raise ValueError("Expected exactly one London ground attack waypoint")

    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"{name}.cs").write_text(script, encoding="ascii")
    (destination / f"{name}.mis").write_text(mission, encoding="ascii")
    (destination / f"{name}.briefing").write_text(
        "[Info]\n<Name>\n" + name + "\n<Description>\n"
        "The fire simulation receives the same recorded impacts on every run. "
        "CloD drives the trucks live. The impact replay does not apply native blast damage.\n",
        encoding="ascii")
    (destination / "impact-fixture.tsv").write_text(
        "".join(f"{stamp-offset:f}\t{kind}\t{east:f}\t{north:f}\n" for stamp, kind, east, north in events),
        encoding="ascii")
    print(f"{len(events)} impacts, first at {events[0][0] - offset}s, last at {events[-1][0] - offset}s")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path, help="Base London crew mission stem")
    parser.add_argument("recording", type=Path, help="Recorded fire events")
    parser.add_argument("routes", type=Path)
    parser.add_argument("terrain", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("name")
    parser.add_argument("--follow-pump", type=int, choices=range(1, 5))
    args = parser.parse_args()
    build(args.template, args.recording, args.routes, WoodlandTerrain.load(args.terrain),
          args.destination, args.name, args.follow_pump)


if __name__ == "__main__":
    main()
