"""Export prepared IL-2 effect groups using locally observed mission syntax.

This creates data only. It neither installs nor starts a mission. Terrain height,
placement and runtime acceptance remain the mission author's responsibility.
"""
from pathlib import Path
import json
import math
import re

from .adapters import make_manifest

SCRIPTS = {"small": "city_firesmall_loop.txt", "large": "city_fire_loop.txt", "smoke": "villagesmoke_loop.txt"}


def export_group(sim, folder, sector_cells=4, origin=(0.0, 0.0, 0.0), prefix="GF", sector_limit=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = make_manifest(sim, sector_cells, prefix)
    manifest["placement"] = {"game_x_origin": origin[0], "game_y_height": origin[1], "game_z_origin": origin[2],
                             "mapping": "local east -> game X; local north -> game Z; configurable prototype alignment, not verified geographic axes"}
    if sector_limit is not None:
        manifest["sectors"] = dict(list(manifest["sectors"].items())[:sector_limit])
    next_id = 100001
    records = []
    def alloc():
        nonlocal next_id
        value = next_id
        next_id += 1
        return value
    def emit(kind, idx, name, x, z, fields):
        common = [f'Index = {idx};', f'Name = "{name}";', 'Desc = "";', f'XPos = {x:.3f};',
                  f'YPos = {origin[1]:.3f};', f'ZPos = {z:.3f};', 'XOri = 0;', 'YOri = 0;', 'ZOri = 0;']
        records.append(kind + "\n{\n  " + "\n  ".join(common + fields) + "\n}\n")
    for key, names in manifest["sectors"].items():
        sx, sy = map(int, re.fullmatch(r"S(\d+)_(\d+)", key).groups())
        x = origin[0] + min((sx + 0.5) * sector_cells, sim.width - 0.5) * sim.cell_size
        z = origin[2] + min((sy + 0.5) * sector_cells, sim.height - 0.5) * sim.cell_size
        for mode, script in SCRIPTS.items():
            effect, entity = alloc(), alloc()
            emit("Effect", effect, f"{prefix}_{key}_{mode}", x, z,
                 [f"LinkTrId = {entity};", f'Script = "luascripts\\worldobjects\\mapemitters\\{script}";', 'Model = "";'])
            emit("MCU_TR_Entity", entity, "Effect entity", x, z,
                 ["Targets = [];", "Objects = [];", "Enabled = 1;", f"MisObjID = {effect};"])
            for action, action_type in (("start", 0), ("stop", 1)):
                cmd, trigger = alloc(), alloc()
                emit("MCU_CMD_Effect", cmd, action, x, z,
                     ["Targets = [];", f"Objects = [{entity}];", f"ActionType = {action_type};"])
                emit("MCU_TR_ServerInput", trigger, names[f"{action}_{mode}"], x, z,
                     [f"Targets = [{cmd}];", "Objects = [];", "Enabled = 1;"])
    text = 'Group\n{\n  Name = "GroundFire prepared effect adapter";\n  Index = 100000;\n  Desc = "Runtime untested. Place at correct terrain altitude before use.";\n' + "\n".join(records) + "}\n\n# end of file\n"
    validate_group(text)
    path = folder / "GroundFire_effects.Group"
    path.write_text(text, encoding="utf-8")
    (folder / "il2_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path, manifest


def validate_group(text):
    if not text.rstrip().endswith("# end of file"):
        raise ValueError("IL-2 text files require the end-of-file marker")
    if text.count("{") != text.count("}"):
        raise ValueError("Unbalanced group braces")
    ids = list(map(int, re.findall(r"\bIndex\s*=\s*(\d+);", text)))
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate mission index")
    known = set(ids)
    refs = list(map(int, re.findall(r"(?:LinkTrId|MisObjID)\s*=\s*(\d+);", text)))
    for contents in re.findall(r"(?:Targets|Objects)\s*=\s*\[([^\]]*)\]", text):
        refs.extend(int(v) for v in contents.split(",") if v.strip())
    if not set(refs) <= known:
        raise ValueError("Unresolved mission object reference")
    names = re.findall(r'MCU_TR_ServerInput\s*\{[^}]*?Name = "([^"]+)";', text, re.S)
    if len(set(names)) != len(names):
        raise ValueError("Duplicate server input name")
    return {"objects": len(ids), "server_inputs": len(names)}
