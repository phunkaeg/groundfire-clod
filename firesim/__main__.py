import argparse
import json
from pathlib import Path
import sys
import time

from .controller import Controller, dcs_effect_script
from .mission import export_group
from .scenarios import village


def main():
    parser = argparse.ArgumentParser(description="GroundFire offline simulation and adapter laboratory")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Run a reproducible offline demo and save evidence")
    demo.add_argument("--seconds", type=float, default=180)
    demo.add_argument("--output", type=Path, default=Path("output"))
    demo.add_argument("--seed", type=int, default=7)
    stream = sub.add_parser("stream", help="Accept typed NDJSON events on stdin; never connects to a game")
    stream.add_argument("--policy", type=Path)
    export = sub.add_parser("export-il2", help="Create prepared effects, with no game launch or installation")
    export.add_argument("--output", type=Path, default=Path("output/il2"))
    export.add_argument("--origin-x", type=float, default=0)
    export.add_argument("--origin-y", type=float, default=0)
    export.add_argument("--origin-z", type=float, default=0)
    export.add_argument("--sector-limit", type=int)
    args = parser.parse_args()
    if args.command == "stream":
        policy = json.loads(args.policy.read_text()) if args.policy else None
        c = Controller(village(ignite=False), policy)
        for line in sys.stdin:
            try:
                response = c.handle(json.loads(line))
            except (ValueError, KeyError, TypeError) as error:
                response = {"kind": "error", "message": str(error), "game_connected": False}
            print(json.dumps(response, allow_nan=False), flush=True)
    elif args.command == "export-il2":
        path, manifest = export_group(village(ignite=False), args.output,
                                      origin=(args.origin_x, args.origin_y, args.origin_z), sector_limit=args.sector_limit)
        print(f"Exported {len(manifest['sectors'])} prepared effect sectors: {path}")
        print("Placement, terrain elevation and live game behavior remain unvalidated.")
    else:
        if not 0 <= args.seconds <= 3600:
            parser.error("--seconds must be between 0 and 3600")
        args.output.mkdir(parents=True, exist_ok=True)
        controller = Controller(village(args.seed))
        started = time.perf_counter()
        timeline = []
        remaining = args.seconds
        while remaining > 0:
            chunk = min(5, remaining)
            response = controller.handle({"kind": "advance", "seconds": chunk})
            timeline.append(response)
            remaining -= chunk
        elapsed = time.perf_counter() - started
        report = {"model": "experimental lumped cell model; coefficients not calibrated", "game_connected": False,
                  "seconds_simulated": args.seconds, "wall_seconds": elapsed, "stats": controller.sim.stats(),
                  "il2_commands_preview": controller.sink.commands, "timeline": timeline}
        (args.output / "demo-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (args.output / "snapshot.json").write_text(json.dumps(controller.sim.snapshot()), encoding="utf-8")
        effects = controller.handle({"kind": "state"})["effects"]
        (args.output / "dcs-effects-preview.lua").write_text(dcs_effect_script(effects), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k not in ("timeline", "il2_commands_preview")}, indent=2))


if __name__ == "__main__":
    main()
