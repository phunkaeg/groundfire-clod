"""Typed JSON boundary, usable from stdin/stdout or an eventual game transport."""
from .adapters import EffectProjector, IL2Adapter, MemorySink, make_manifest
from .il2 import GroundLogIngestor


class Controller:
    def __init__(self, sim, policy=None):
        self.sim = sim
        self.sink = MemorySink()
        self.adapter = IL2Adapter(self.sink, make_manifest(sim))
        self.log = GroundLogIngestor(**policy) if policy else None

    def handle(self, event):
        if not isinstance(event, dict):
            raise ValueError("Protocol event must be a JSON object")
        kind = event.get("kind")
        if kind == "advance":
            self.sim.step(float(event["seconds"]))
        elif kind == "ignition":
            self.sim.ignite(float(event["east"]), float(event["north"]), float(event["radius_m"]),
                            float(event["exposure_kj_m2"]), event.get("event_id"))
        elif kind == "suppression":
            self.sim.suppress(float(event["east"]), float(event["north"]), float(event["radius_m"]), float(event["water_kg"]))
        elif kind == "weather":
            east = float(event.get("wind_east_m_s", self.sim.wind_east))
            north = float(event.get("wind_north_m_s", self.sim.wind_north))
            rain = float(event.get("rain_mm_h", self.sim.rain_mm_h))
            self.sim._finite(east, north, rain)
            if rain < 0:
                raise ValueError("Negative rain")
            self.sim.wind_east, self.sim.wind_north, self.sim.rain_mm_h = east, north, rain
        elif kind == "il2_log":
            if self.log is None:
                raise ValueError("IL-2 ground-target/ammunition policy required")
            result = self.log.feed(event["line"], self.sim)
        elif kind not in ("state", "snapshot"):
            raise ValueError("Unsupported event kind")
        count = len(self.sink.commands)
        effects = self.adapter.synchronize(self.sim)
        response = {"schema": 1, "kind": "state", "stats": self.sim.stats(),
                    "effects": [{"id": e.sector, "mode": e.mode, "east": e.east, "north": e.north} for e in effects.values()],
                    "il2_commands_preview": self.sink.commands[count:], "game_connected": False}
        if kind == "il2_log":
            response["log_result"] = result
        if kind == "snapshot":
            response["snapshot"] = self.sim.snapshot()
        return response


def dcs_effect_script(effects, origin_x=0, origin_z=0):
    """Generate a mission-script effect update. Does not install or execute it.

    Prototype frame maps local east to DCS x, local north to DCS z; the user must
    supply/verify map orientation. No heat damage or terrain charring is implied.
    """
    import json
    lines = ["-- Generated GroundFire desired-state update; game acceptance pending.",
             "-- Prototype alignment: local east->DCS x, north->DCS z; verify per map.",
             "GroundFireFX = GroundFireFX or {}", "local wanted = {}"]
    for e in effects:
        preset = {"small": 1, "large": 3, "smoke": 5}[e["mode"]]
        x, z = origin_x + e["east"], origin_z + e["north"]
        name = json.dumps("GroundFire_" + e["id"])
        lines.append(f"wanted[{name}] = {{x={x:.3f}, z={z:.3f}, preset={preset}}}")
    lines += [
        "for name, old in pairs(GroundFireFX) do",
        "  local new = wanted[name]",
        "  if not new or new.preset ~= old.preset or new.x ~= old.x or new.z ~= old.z then",
        "    trigger.action.effectSmokeStop(name)",
        "    GroundFireFX[name] = nil",
        "  end",
        "end",
        "for name, new in pairs(wanted) do",
        "  if not GroundFireFX[name] then",
        "    local p = {x=new.x, y=land.getHeight({x=new.x, y=new.z}), z=new.z}",
        "    trigger.action.effectSmokeBig(p, new.preset, 0.5, name)",
        "    GroundFireFX[name] = new",
        "  end",
        "end",
    ]
    return "\n".join(lines) + "\n"
