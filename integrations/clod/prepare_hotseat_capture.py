"""Prepare a separate, build-pinned Hawkinge capture mission for HOTSEAT."""
import argparse
import json
import math
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

from hawkinge import HERE, OUT, PROTOTYPE
from fire_lab import (FRONT_BUDGET, LONDON_ATTACK_CENTER, LONDON_CITY_RAID_CENTER, LONDON_RAID_CENTERS,
                      LONDON_CENTER, LONDON_TEMP_C, LONDON_WIND, PLOTS,
                      DENSE_FLAME_BUDGET, DISTRICT_LIGHT_BUDGET, SPLIT_FLAME_BUDGET, SPLIT_SMOKE_BUDGET,
                      WOOD_EDGE_CENTER, WOOD_EDGE_ROAD, WoodlandTerrain, london_ignitions)
from prepare_fire_lab import NAME as LAB_NAME, mission_variants, write_files

NAME = "GroundFire Hawkinge Wind Capture"
DESTINATION = OUT / "hotseat-capture"
WINDS = {"east": (12.0, 0.0), "north": (0.0, 12.0)}
ATTACK_POINTS = {"east": (235247, 232407), "north": (235408, 232360)}
TOWN_NAME = "GroundFire Hawkinge Town Capture"
LONDON_START_HOUR = 20.5
LONDON_DUSK_HOUR = 20.25
LONDON_MORNING_HOUR = 6.083333
LONDON_DAYLIGHT_HOUR = 10.5
LONDON_ATTACK_NIGHT_HOUR = 22.333334
LONDON_FIXED_CAMERA = "147550 273605 485 0 24 0 0"
# Frame both impact bands measured during the stock raid scouting run.
LONDON_ATTACK_CAMERA = "153560 273825 710 0 19 0 0"
LONDON_CITY_ATTACK_POINT = "149400.00 274180.00"
LONDON_CITY_SCOUT_CAMERA = (147000, 273950, 660, 0, 19)

BETA_WIND_PROBE = """
    private bool windSampled;

    private void SampleMissionWind()
    {
        double? ground = GroundHeight(0);
        if (windSampled || Now < 5 || !ground.HasValue)
            return;
        windSampled = true;
        try
        {
            foreach (Assembly engine in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (engine.GetName().Name != "maddox" ||
                    engine.ManifestModule.ModuleVersionId != new Guid("794e174f-8a18-4e18-b6f3-50136f58801d") ||
                    typeof(WWeather).Module.ModuleVersionId != new Guid("969786f0-e360-4528-a2fe-18ea0aefd6b9"))
                    continue;
                Type owner = engine.GetType("IN9ja8czYVm8g9Yda3jVhIdZoiD0Iurfl52UO1fGq$WF", true);
                MethodInfo getter = owner.GetMethod("9N8E$o$ey_2hz00$ZCHe4ck", BindingFlags.Public | BindingFlags.Static,
                    null, Type.EmptyTypes, null);
                if (getter == null || getter.ReturnType != typeof(WWeather))
                    throw new MissingMethodException("Unexpected mission weather getter");
                WWeather weather = (WWeather)getter.Invoke(null, null);
                foreach (int height in new[] { 1, 20, 100 })
                {
                    var point = new Point3d(Centers[0, 0], Centers[0, 1], ground.Value + height);
                    Vector3d wind;
                    if (weather.windGetWindInPointLODMAX(ref point, out wind))
                        Note(String.Format(Invariant, "game_wind agl={0} east={1:F3} north={2:F3} up={3:F3}",
                            height, wind.x, wind.y, wind.z));
                    else
                        Note("game_wind unavailable at agl=" + height);
                }
                return;
            }
            Note("game_wind unavailable on this build");
        }
        catch (Exception error)
        {
            Note("game_wind unavailable: " + error.GetType().Name);
        }
    }
"""


BETA_TERRAIN_PROBE = """
    private MethodInfo terrainHeight;

    private double? CaptureTerrainHeight(double x, double y)
    {
        if (terrainHeight == null)
        {
            foreach (Assembly engine in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (engine.GetName().Name != "maddox" ||
                    engine.ManifestModule.ModuleVersionId != new Guid("794e174f-8a18-4e18-b6f3-50136f58801d") ||
                    typeof(WWeather).Module.ModuleVersionId != new Guid("969786f0-e360-4528-a2fe-18ea0aefd6b9"))
                    continue;
                Type owner = engine.GetType("ZeG4vkM887XOVZ75iw9bLVuv7z4YcugySD2GAUW46rTd", true);
                MethodInfo getter = owner.GetMethod("9GGXBaHRV8C8OxZIPN_yH$8",
                    BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static,
                    null, new[] { typeof(double), typeof(double) }, null);
                if (getter == null || getter.ReturnType != typeof(double))
                    throw new MissingMethodException("Unexpected mission terrain height getter");
                terrainHeight = getter;
                break;
            }
            if (terrainHeight == null)
                return null;
        }
        double z = (double)terrainHeight.Invoke(null, new object[] { x, y });
        return Finite(z) ? (double?)z : null;
    }
"""


def town_series(mission, center):
    group = "BoB_LW_JG54_III.34"
    groups = (group, "BoB_LW_JG54_III.33", "BoB_LW_JG54_III.32")
    pattern = rf"(?m)^\[{re.escape(group)}\]\n([^\[]+)\[{re.escape(group)}_Way\]\n[^\[]+"
    match = re.search(pattern, mission)
    if not match or mission.count(f"  {group}\n") != 1:
        raise ValueError("The SC250 aircraft template was not found")
    raids = []
    if center == WOOD_EDGE_CENTER:
        aim_points = ((235918, 233784), (235730, 234010), (235570, 234170))
    else:
        aim_points = [(center[0] + east - 94, center[1] + north - 2)
                      for east, north in ((-65, -110), (30, 20), (75, 150))]
    for index, (name, (x, y)) in enumerate(zip(groups, aim_points)):
        start = x + 4092 + index * 1250
        raids.append(f"[{name}]\n{match[1]}[{name}_Way]\n"
                     f"  NORMFLY {start:.2f} {y + 25:.2f} 1050.00 315.00\n"
                     f"  GATTACK_POINT {x:.2f} {y:.2f} 1050.00 315.00\n"
                     f"  NORMFLY {x - 1800:.2f} {y + 15:.2f} 1050.00 315.00\n"
                     f"  NORMFLY {x - 1800:.2f} {y - 1080:.2f} 1050.00 315.00\n")
    mission = mission[:match.start()] + "".join(raids) + mission[match.end():]
    return mission.replace(f"  {group}\n", "".join(f"  {name}\n" for name in groups), 1)


def town_script(source, center, half):
    old_center = "{ %d, %d }" % PLOTS["town"]
    new_center = "{ %d, %d }" % center
    changes = (
        (old_center, new_center),
        ("    private string session;", BETA_TERRAIN_PROBE + "\n    private string session;"),
        ("double x = pos.x - Centers[0, 0], y = pos.y - Centers[0, 1];\n"
         "            double? height = GroundHeight(0);",
         "double x = pos.x - Centers[3, 0], y = pos.y - Centers[3, 1];\n"
         f"            bool inPlot = x >= -{half} && x < {half} && y >= -{half} && y < {half};\n"
         "            double? height = inPlot ? CaptureTerrainHeight(pos.x, pos.y) : null;"),
        ("x * x + y * y <= 62 * 62", "inPlot"),
        ("outside the marked forest plot", "outside the town test plot"),
        ("if (plot < 0 || Math.Abs(x - Centers[plot, 0]) > 80 || Math.Abs(y - Centers[plot, 1]) > 80)",
         f"double half = plot == 3 ? {half} : 80;\n"
         "            if (plot < 0 || Math.Abs(x - Centers[plot, 0]) > half || Math.Abs(y - Centers[plot, 1]) > half)"),
        ("double? z = GroundHeight(item.Value.Item1);",
         "double? z = item.Value.Item1 == 3 ? CaptureTerrainHeight(item.Value.Item2, item.Value.Item3)\n"
         "                                              : GroundHeight(item.Value.Item1);"),
    )
    for before, after in changes:
        if source.count(before) != 1:
            raise ValueError(f"The Fire Lab template changed near {before.splitlines()[0]}")
        source = source.replace(before, after)
    return source


def city_crew_script(source, terrain, route_path, crew_camera=None):
    routes = json.loads(route_path.read_text(encoding="ascii"))["routes"]
    if not 1 <= len(routes) <= 4:
        raise ValueError("Use one to four central London pump routes")
    if crew_camera is not None and not 1 <= crew_camera <= len(routes):
        raise ValueError("The camera must follow a pump with a route")
    west, south = (coord - terrain.half for coord in terrain.center)
    span = 2 * terrain.half
    arrays = []
    for route in routes:
        if not 2 <= len(route) <= 16 or any(len(point) != 2 for point in route):
            raise ValueError("Each pump route requires two to sixteen XY waypoints")
        for east, north in route:
            if not (west <= east < west + span and south <= north < south + span):
                raise ValueError("Pump waypoints must remain on the central London plot")
        for a, b in zip(route, route[1:]):
            length = math.dist(a, b)
            if length < 10:
                raise ValueError("Pump waypoints must be at least ten metres apart")
            segments = math.ceil(length / 5)
            for step in range(segments + 1):
                east = a[0] + (b[0] - a[0]) * step / segments
                north = a[1] + (b[1] - a[1]) * step / segments
                if terrain.kind(int((east - west) / terrain.cell_size),
                                int((north - south) / terrain.cell_size)) == "water":
                    raise ValueError("A pump route crosses chart-mapped water")
        points = ", ".join(f"new Point2d({east:.2f}, {north:.2f})" for east, north in route)
        arrays.append("        new[] { " + points + " },")
    crew = (HERE / "LondonCityCrews.cs").read_text(encoding="ascii")
    if crew_camera is not None:
        source = "#define LONDON_CREW_CAMERA\n" + source
        crew = crew.replace("__CREW_CAMERA_NUMBER__", str(crew_camera))
    if source.count("            ReadFrame(now);") != 1:
        raise ValueError("The London city crew tick hook changed")
    source = source.replace("            ReadFrame(now);", "            ReadFrame(now);\n            ObserveCityCrews(now);")
    return source + "\n" + crew.replace("__CITY_ROUTES__", "\n".join(arrays))


def village_crew_script(source):
    road = []
    for index, (x, y) in enumerate(WOOD_EDGE_ROAD):
        params = f"{y:.2f} 38.40 0 {len(WOOD_EDGE_ROAD)} 6.11" if index == 0 else f"{y:.2f} 20.00"
        road.append(f'        section.add(road, "{x:.2f}", "{params}");')
    crew = (HERE / "WoodlandVillageCrew.cs").read_text(encoding="ascii")
    crew = crew.replace("__CREW_WAYPOINTS__", "\n".join(road))
    crew = crew.replace("__CREW_STAND_X__", str(WOOD_EDGE_ROAD[-1][0]))
    crew = crew.replace("__CREW_STAND_Y__", str(WOOD_EDGE_ROAD[-1][1]))
    source = source.replace("public class Mission : AMission", "public partial class Mission : AMission")
    start = 'Record(String.Format(Invariant, "bomb\\t{0}\\t{1:R}\\t{2:R}", type, pos.x, pos.y));'
    if source.count(start) != 1:
        raise ValueError("The Fire Lab impact hook changed")
    source = source.replace(start, "{\n                " + start + "\n                crewPending = true;\n            }")
    source = source.replace("            ReadFrame(now);", "            ReadFrame(now);\n            ObserveCrew(now);")
    return source.rstrip() + "\n\n" + crew


def london_script(source, terrain):
    # The city fixture is driven by scheduled ground-ignition inputs.
    begin = source.index("    public override void OnBombExplosion(")
    end = source.index("    public override void OnTickGame()", begin)
    schedule = ",\n".join(f"        {{ {t}, {x}, {y} }}" for t, x, y in london_ignitions(terrain))
    fixture = """
    private int nextIgnition;
    private static readonly int[,] LondonStarts = {
__STARTS__
    };

    private void RunLondonIgnitions(double now)
    {
        while (nextIgnition < LondonStarts.GetLength(0) && now >= LondonStarts[nextIgnition, 0])
        {
            int i = nextIgnition++;
            Record(String.Format(Invariant, "ignition\\t{0}\\t{1}", LondonStarts[i, 1], LondonStarts[i, 2]));
        }
    }

""".replace("__STARTS__", schedule)
    source = source[:begin] + fixture + source[end:]
    return source.replace("            ReadFrame(now);", "            RunLondonIgnitions(now);\n            ReadFrame(now);")


def london_mission(east, north):
    x, y = LONDON_CENTER
    return f"""[PARTS]
  core.100
  bob.100
[MAIN]
  MAP Land$English_Channel_1940
  YEAR 1940
  MONTH 12
  DAY 29
  TIME {LONDON_START_HOUR:g}
  WeatherIndex 5
  CloudsHeight 1000
  Cloudiness 40
  CloudsThickness 500
  Haze 3
  GroundFog 0
  BreezeActivity 0
  ThermalActivity 0
  player BoB_RAF_F_609Sqn_Early.210
[GlobalWind_0]
  Power {east} {north} 0.000
  BottomBound 0.00
  TopBound 1500.00
  GustPower 0
  GustAngle 45
[AirGroups]
  BoB_RAF_F_609Sqn_Early.22
[BoB_RAF_F_609Sqn_Early.22]
  Flight1 P
  Class Aircraft.SpitfireMkIa_100oct
  Formation VIC3
  CallSign 14
  Fuel 100
  Weapons 1
  Skill 1 0.90 1 1 0.20 1 1 0.93
  Briefing 1
[BoB_RAF_F_609Sqn_Early.22_Way]
  NORMFLY {x - 2200:.2f} {y:.2f} 1000.00 315.00
  NORMFLY {x + 2200:.2f} {y:.2f} 1000.00 315.00
  NORMFLY {x + 2200:.2f} {y - 2800:.2f} 1000.00 315.00
[StaticCamera]
  StaticCamera_0 {x - 1460} {y + 100} 420
"""


def sightseeing_night_mission(path, hour=LONDON_START_HOUR):
    mission = path.read_bytes().decode("utf-8")
    main = re.search(r"(?m)^\[MAIN\]\r?\n([^\[]+)", mission)
    wind = re.search(r"(?m)^\[GlobalWind_0\]\r?\n[ \t]*Power[ \t]+(\S+)[ \t]+(\S+)[ \t]+\S+", mission)
    if main is None or "MAP Land$English_Channel_1940" not in main[1] or wind is None:
        raise ValueError("Expected the English Channel London Sightseeing mission and its wind layer")
    if hour is None:
        return mission, tuple(map(float, wind.groups()))
    updated, count = re.subn(r"(?m)^([ \t]*TIME[ \t]+)[^\r\n]+",
                             lambda match: f"{match[1]}{hour}", main[1])
    if count != 1:
        raise ValueError("Expected one TIME entry in the stock mission")
    return mission[:main.start(1)] + updated + mission[main.end(1):], tuple(map(float, wind.groups()))


def prepare(terrain=None, steam=False, large_fire=False, wind="east", front_fx=False,
            effect_size=1.0, object_fire=False, london_sightseeing=None, warm_lights=False, dusk=False,
            london_camera=False, london_attack=None, night_raid=False, city_raid=False,
            city_camera=None, city_routes=None, split_fx=False, dense_fx=False,
            morning=False, district_budget=DISTRICT_LIGHT_BUDGET, light_benchmark=False, warm_smoke=False,
            smoke_atlas=None, isolated_fires=False, crew_camera=None, daylight=False):
    daylight = daylight or crew_camera is not None
    town = terrain is not None and terrain.plot == "town"
    village = town and terrain.center == WOOD_EDGE_CENTER
    raid = london_attack is not None
    london = town and terrain.center in (LONDON_CENTER, *LONDON_RAID_CENTERS)
    wide = town and terrain.wide
    if london_sightseeing is not None and not london:
        raise ValueError("The Sightseeing variant requires the London terrain grid")
    raid_center = LONDON_CITY_RAID_CENTER if city_raid else LONDON_ATTACK_CENTER
    if raid and (not steam or not town or terrain.center != raid_center or london_sightseeing or (dusk and not city_raid)):
        raise ValueError("London Attack requires Steam and its own terrain grid")
    if night_raid and not (raid and warm_lights and front_fx):
        raise ValueError("The night raid requires London Attack, warm lights and front effects")
    if split_fx and not (city_raid and night_raid and large_fire):
        raise ValueError("Split effects require the city raid with stock BuildingFireBig")
    if dense_fx and not split_fx:
        raise ValueError("Dense effects require separate flame and smoke")
    if morning and (dusk or not city_raid):
        raise ValueError("Morning requires the central London raid and replaces dusk")
    if district_budget != DISTRICT_LIGHT_BUDGET and not dense_fx:
        raise ValueError("A custom district light budget requires dense effects")
    if light_benchmark and district_budget != 24:
        raise ValueError("The 12/24 light benchmark requires a 24-light mission")
    if warm_smoke and (not dense_fx or dusk or morning):
        raise ValueError("The firelit smoke comparison requires the dense night mission")
    if warm_smoke and (smoke_atlas is None or not smoke_atlas.is_file()):
        raise ValueError("--warm-smoke requires --smoke-atlas with the installed Smoke_Sprites_Air_W.dds")
    if isolated_fires and not warm_smoke:
        raise ValueError("--isolated-fires requires the firelit smoke night mission")
    if (city_raid and not night_raid) or ((city_camera or city_routes) and not city_raid):
        raise ValueError("City raid scenery options require the central London night mission")
    if daylight and (not city_raid or warm_smoke or dusk or morning):
        raise ValueError("Daylight uses the central London raid at 10:30")
    if crew_camera is not None and not city_routes:
        raise ValueError("--crew-camera requires pump routes")
    if town and terrain.center in LONDON_RAID_CENTERS and not raid:
        raise ValueError("The London raid grid requires the London Attack mission")
    if warm_lights and london_sightseeing is None and not raid:
        raise ValueError("Warm lights require a London mission")
    if dusk and not warm_lights:
        raise ValueError("The dusk comparison requires warm lights")
    if london_camera and (not steam or (london_sightseeing is None and not raid)):
        raise ValueError("The fixed London camera requires a Steam London mission")
    london_hour = None if raid else LONDON_DUSK_HOUR if dusk else LONDON_START_HOUR
    if night_raid:
        london_hour = LONDON_MORNING_HOUR if morning else LONDON_DUSK_HOUR if dusk else LONDON_ATTACK_NIGHT_HOUR
    if daylight:
        london_hour = LONDON_DAYLIGHT_HOUR
    london_path = london_attack if raid else london_sightseeing
    sightseeing_mission, london_wind = (sightseeing_night_mission(london_path, london_hour)
                                        if london_path is not None else (None, LONDON_WIND))
    if raid and ("[BoB_LW_KG76_II.17_Way]" not in sightseeing_mission or
                "GATTACK_TARG 155676.43 274164.17" not in sightseeing_mission):
        raise ValueError("Expected the installed London Attack mission")
    if city_raid:
        sightseeing_mission = sightseeing_mission.replace("GATTACK_TARG 155676.43 274164.17",
                                                          "GATTACK_POINT " + LONDON_CITY_ATTACK_POINT, 1)
    if town and steam and sightseeing_mission is None:
        raise ValueError("The Steam town variant requires the London Sightseeing approach")
    if front_fx and not town:
        raise ValueError("Front effects require a town terrain grid")
    if large_fire and object_fire:
        raise ValueError("Select one stock fire asset")
    if not math.isfinite(effect_size) or effect_size <= 0:
        raise ValueError("Effect size must be positive and finite")
    size_label = f"{effect_size:g}x"
    variants, _ = mission_variants()
    source = variants[LAB_NAME + ".cs"].decode("ascii")
    mission = variants[LAB_NAME + ".mis"].decode("ascii")
    # The known BETA416 assemblies are accepted in this experiment only.
    if not steam:
        source = source.replace("8e7a2ac5-43e4-45fc-8ef5-f4e3d36baff3", "794e174f-8a18-4e18-b6f3-50136f58801d")
        source = source.replace("7cabe1d9-b513-4d66-82fb-8d66589e5f09", "969786f0-e360-4528-a2fe-18ea0aefd6b9")
    east, north = (f"{component:.3f}" for component in (london_wind if london else WINDS[wind]))
    environment = r"\t".join((f"{LONDON_TEMP_C:g}" if london and not raid else "15", east, north))
    if terrain:
        environment += r"\t" + terrain.identity
        state = terrain.state_folder + ("-front" if front_fx else "")
        if night_raid:
            state += "-pulse"
        if split_fx:
            state += "-split"
        if dense_fx:
            state += "-dense"
        if district_budget != DISTRICT_LIGHT_BUDGET:
            state += f"-l{district_budget}"
        if warm_smoke:
            state += "-warm-smoke"
        source = source.replace('"GroundFireHawkinge", "lab"', f'"GroundFireHawkinge", "{state}"')
    source = source.replace(r"15\t2.000\t0.000", environment)
    if large_fire:
        source = source.replace("/BuildingFireSmall.eff", "/BuildingFireBig.eff")
    elif object_fire:
        source = source.replace("$core/3do/sfx/fire/BuildingFireSmall.eff",
                                "$core/3do/SFX/Fire/FireObject_0.eff")
    if effect_size != 1:
        spawn = "new object[] { loc, 1f, Asset, -1.0, true }"
        if source.count(spawn) != 1:
            raise ValueError("The Fire Lab effect spawn template changed")
        source = source.replace(spawn, f"new object[] {{ loc, {effect_size:g}f, Asset, -1.0, true }}")
        source = source.replace('Record("init\\t" + MissionEnvironment);',
                                'Record("init\\t" + MissionEnvironment);\n'
                                f'            Note("fx_size {effect_size:g} asset=" + Asset);')
    source = source.replace(
        'GamePlay.gpTimeofDay().ToString("R", Invariant));',
        'GamePlay.gpTimeofDay().ToString("R", Invariant) + "\\t" + '
        '(DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc))'
        '.TotalSeconds.ToString("F6", Invariant));',
    )
    # Log the first owned plume creation and later clear-down on the same mission clock.
    source = source.replace("effects.Add(item.Key, effect);",
                            'effects.Add(item.Key, effect);\n            Note("plume_created " + item.Key);')
    source = source.replace("fading.Add(actor);",
                            'fading.Add(actor);\n                Note("plume_finished " + id);')
    if front_fx:
        budget = SPLIT_FLAME_BUDGET + SPLIT_SMOKE_BUDGET if split_fx else FRONT_BUDGET
        if dense_fx:
            budget = DENSE_FLAME_BUDGET + SPLIT_SMOKE_BUDGET + district_budget
        source = source.replace("const int PlumeBudget = 4;", f"const int PlumeBudget = {budget};")
        total_budget = "192" if dense_fx else "PlumeBudget * 2" if split_fx else "PlumeBudget * 3"
        source = source.replace("const int TotalEffectBudget = 8;", f"const int TotalEffectBudget = {total_budget};")
        source = source.replace('Record("init\\t" + MissionEnvironment);',
                                'Record("init\\t" + MissionEnvironment);\n'
                                '            Note("fx_budget active=" + PlumeBudget + " total=" + TotalEffectBudget);')
    source = source.replace(
        'Note("plume_created " + item.Key);',
        'Note(String.Format(Invariant, "plume_created {0} {1:F6} {2:F3} {3:F3}",\n'
        '                               item.Key, Now, item.Value.Item2, item.Value.Item3));')
    source = source.replace('Note("plume_finished " + id);',
                            'Note(String.Format(Invariant, "plume_finished {0} {1:F6}", id, Now));')
    # A direct hit can destroy the stationary used to sample the terrain height.
    source = source.replace("    private string session;",
                            "    private readonly double?[] cachedGround = new double?[Plots.Length];\n"
                            "    private string session;")
    wind_sample = ""
    if london or (wind == "north" and not steam):
        probe = BETA_WIND_PROBE
        if town:
            probe = probe.replace("GroundHeight(0)", "CaptureTerrainHeight(Centers[3, 0], Centers[3, 1])")
            probe = probe.replace("Centers[0,", "Centers[3,")
        source = source.replace("    private string session;", probe + "\n    private string session;")
        wind_sample = "            SampleMissionWind();\n"
    source = source.replace('            Record("clock',
                            '            GroundHeight(0);\n' + wind_sample + '            Record("clock')
    source = source.replace("private double? GroundHeight(int plot)\n    {",
                            "private double? GroundHeight(int plot)\n    {\n"
                            "        if (cachedGround[plot].HasValue)\n"
                            "            return cachedGround[plot];")
    source = source.replace("return pos.z;", "return cachedGround[plot] = pos.z;")
    if town:
        source = town_script(source, terrain.center, int(terrain.half))
    if village:
        source = village_crew_script(source)
    if london and not raid:
        source = london_script(source, terrain)
    if raid:
        start = source.index("            string type =")
        end = source.index("            bool accepted =", start)
        source = source[:start] + (
            '            Match weapon = Regex.Match(id, "SC(?:1000|500|250|50)(?![0-9])");\n'
            '            string type = weapon.Success ? weapon.Value : "";\n'
            '            string fit = "";\n'
        ) + source[end:]
    if london and steam:
        # This revision retains the inspected terrain and weather methods.
        source = source.replace("794e174f-8a18-4e18-b6f3-50136f58801d", "8e7a2ac5-43e4-45fc-8ef5-f4e3d36baff3")
        source = source.replace("969786f0-e360-4528-a2fe-18ea0aefd6b9", "7cabe1d9-b513-4d66-82fb-8d66589e5f09")
    if warm_lights:
        hooks = (
            ("public class Mission : AMission", "public partial class Mission : AMission"),
            ("            ReadFrame(now);", "            ReadFrame(now);\n            ObserveCityLights();"),
            ("                finishEffect.Invoke(null, new[] { actor });",
             "                EndCityLight(id);\n                finishEffect.Invoke(null, new[] { actor });"),
            ("            effects.Add(item.Key, effect);",
             "            effects.Add(item.Key, effect);\n"
             "            TryLightCityFire(item.Key, item.Value.Item1, effect,\n"
             "                new Point3d(item.Value.Item2, item.Value.Item3, z.Value));"),
        )
        for before, after in hooks:
            if source.count(before) != 1:
                raise ValueError("The city light mission template changed")
            source = source.replace(before, after)
        source += "\n" + (HERE / "LondonFireLights.cs").read_text(encoding="ascii")
    if split_fx:
        flame_size = 7.0 if dense_fx else effect_size * 0.75
        hooks = (
            (f"new object[] {{ loc, {effect_size:g}f, Asset, -1.0, true }}",
             f"new object[] {{ loc, smokeOnly ? {effect_size:g}f : {flame_size:g}f, Asset, -1.0, true }}"),
            ("            object effect = createEffect.Invoke(",
             '            bool smokeOnly = item.Key.Contains("_P2_");\n'
             "            object effect = createEffect.Invoke("),
            ("            effects.Add(item.Key, effect);",
             "            SeparateCityEffect(effect, smokeOnly);\n"
             "            effects.Add(item.Key, effect);"),
            ("            TryLightCityFire(item.Key, item.Value.Item1, effect,\n"
             "                new Point3d(item.Value.Item2, item.Value.Item3, z.Value));\n",
             "" if dense_fx else
             "            if (!smokeOnly)\n"
             "                TryLightCityFire(item.Key, item.Value.Item1, effect,\n"
             "                    new Point3d(item.Value.Item2, item.Value.Item3, z.Value));\n"),
        )
        for before, after in hooks:
            if source.count(before) != 1:
                raise ValueError("The split city effect mission template changed")
            source = source.replace(before, after)
        source += "\n" + (HERE / "LondonSplitEffects.cs").read_text(encoding="ascii")
    if dense_fx:
        hooks = (
            ("if (desired.Count == 0 && effects.Count == 0)",
             "if (desired.Count == 0 && effects.Count == 0 && cityLights.Count == 0)"),
            ("if (now - receivedAt > 15 && effects.Count != 0)",
             "if (now - receivedAt > 15 && (effects.Count != 0 || cityLights.Count != 0))"),
            ("            BindEffects();\n", "            BindEffects();\n        ReconcileDistrictLights(desired);\n"),
            ("            var loc = new Loc(item.Value.Item2, item.Value.Item3, z.Value, 0, 0, 0);",
             '            double height = z.Value + (item.Key.Contains("_P4_") ? 5.5 : 0);\n'
             "            var loc = new Loc(item.Value.Item2, item.Value.Item3, height, 0, 0, 0);"),
        )
        for before, after in hooks:
            if source.count(before) != 1:
                raise ValueError("The dense city effect mission template changed")
            source = source.replace(before, after)
        source = source.replace("__DISTRICT_LIGHT_BUDGET__", str(district_budget))
        source += "\n" + (HERE / "LondonDistrictLights.cs").read_text(encoding="ascii")
    if raid:
        source = source.replace("public class Mission : AMission", "public partial class Mission : AMission")
        source = source.replace("            ReadFrame(now);", "            SelectRaidCamera(now);\n            ReadFrame(now);")
        source += "\n" + (HERE / "LondonAttackCamera.cs").read_text(encoding="ascii")
    if city_raid:
        source = source.replace("type={5} fit={6} accepted={7}",
                                "type={5} fit={6} t={8:F6} ground_z={9} agl={10} accepted={7}")
        source = source.replace("title, mass, pos.x, pos.y, pos.z, type, fit, accepted));",
                                "title, mass, pos.x, pos.y, pos.z, type, fit, accepted, Now,\n"
                                "                               height.HasValue ? height.Value.ToString(\"F3\", Invariant) : \"unknown\",\n"
                                "                               height.HasValue ? (pos.z - height.Value).ToString(\"F3\", Invariant) : \"unknown\"));")
    if night_raid:
        hooks = (
            ("        base.OnTickGame();", "        base.OnTickGame();\n        PulseCityLights();"),
            ("        var desired = new Dictionary<string, Tuple<int, double, double>>();",
             "        var strengths = new Dictionary<string, double>();\n"
             "        var desired = new Dictionary<string, Tuple<int, double, double>>();"),
            ("            double x, y;\n            if (row.Length != 4",
             "            double x, y, strength;\n            if (row.Length != 5 ||\n"
             "                !Parse(row[4], out strength) || strength < 0 || strength > 1"),
            ("            desired.Add(row[0], Tuple.Create(plot, x, y));",
             "            desired.Add(row[0], Tuple.Create(plot, x, y));\n"
             "            strengths.Add(row[0], strength);"),
            ("        receivedAt = now;", "        cityLightStrength = strengths;\n        receivedAt = now;"),
        )
        for before, after in hooks:
            if source.count(before) != 1:
                raise ValueError("The night lighting mission template changed")
            source = source.replace(before, after)
        source = "#define LONDON_PULSING_LIGHTS\n" + source
        if dense_fx:
            source = "#define LONDON_DISTRICT_LIGHTS\n" + source
    if light_benchmark:
        hooks = (
            ("            ReadFrame(now);", "            CheckLightBenchmark(now);\n            ReadFrame(now);"),
            ("    private void ReadFrame(double now)\n    {",
             "    private void ReadFrame(double now)\n    {\n"
             "        if (lightBenchFrozen)\n        {\n            receivedAt = now;\n            return;\n        }"),
        )
        for before, after in hooks:
            if source.count(before) != 1:
                raise ValueError("The light benchmark mission template changed")
            source = source.replace(before, after)
        source = "#define LONDON_LIGHT_BENCHMARK\n" + source
        source += "\n" + (HERE / "LondonLightBenchmark.cs").read_text(encoding="ascii")
    if warm_smoke:
        hooks = (
            ("            ReadFrame(now);", "            CheckWarmSmoke(now);\n            ReadFrame(now);"),
            ("    private void ReadFrame(double now)\n    {",
             "    private void ReadFrame(double now)\n    {\n"
             "        if (warmSmokeHeld)\n        {\n            receivedAt = now;\n            return;\n        }"),
            ("        }\n    }\n\n    private void BindEffects()",
             f"        }}\n        ReconcileWarmSmoke(desired, {effect_size:g}f);\n    }}\n\n    private void BindEffects()"),
        )
        for before, after in hooks:
            if source.count(before) != 1:
                raise ValueError("The warm smoke mission template changed")
            source = source.replace(before, after)
        source = "#define LONDON_WARM_SMOKE\n" + source
        source += "\n" + (HERE / "LondonWarmSmoke.cs").read_text(encoding="ascii")
    if isolated_fires:
        hooks = (
            ('            if (accepted)\n                Record(String.Format(Invariant, "bomb',
             '            if (accepted && SampleRaidImpact(pos))\n                Record(String.Format(Invariant, "bomb'),
            ('            else if (type != "")\n                GamePlay.gpHUDLogCenter',
             '            else if (!accepted && type != "")\n                GamePlay.gpHUDLogCenter'),
            ("                effects.Remove(id);", "                effects.Remove(id);\n                flameBands.Remove(id);"),
            ("            if (effects.ContainsKey(item.Key) || effects.Count + fading.Count >= TotalEffectBudget)",
             '            bool smokeOnly = item.Key.Contains("_P2_");\n'
             "            double strength = 0;\n"
             "            int band = smokeOnly ? -1 : FlameBand(item.Key, out strength);\n"
             "            object previous;\n"
             "            bool exists = effects.TryGetValue(item.Key, out previous);\n"
             "            if ((exists && (smokeOnly || flameBands[item.Key] == band)) ||\n"
             "                effects.Count + fading.Count >= TotalEffectBudget)"),
            ('            bool smokeOnly = item.Key.Contains("_P2_");\n'
             f"            object effect = createEffect.Invoke(null, new object[] {{ loc, smokeOnly ? {effect_size:g}f : 7f, Asset, -1.0, true }});",
             f"            object effect = createEffect.Invoke(null, new object[] {{ loc, smokeOnly ? {effect_size:g}f : FlameScales[band], Asset, -1.0, true }});"),
            ("            effects.Add(item.Key, effect);",
             "            if (exists)\n"
             "            {\n"
             "                finishEffect.Invoke(null, new[] { previous });\n"
             "                fading.Add(previous);\n"
             "            }\n"
             "            effects[item.Key] = effect;\n"
             "            if (!smokeOnly)\n"
             "            {\n"
             "                flameBands[item.Key] = band;\n"
             '                Note(String.Format(Invariant, "flame_scale {0} {1:F6} {2:F2} {3:F3}",\n'
             "                                   item.Key, Now, FlameScales[band], strength));\n"
             "            }\n"
             "            if (exists)\n"
             "                continue;"),
        )
        for before, after in hooks:
            if source.count(before) != 1:
                raise ValueError("The isolated city fire mission template changed")
            source = source.replace(before, after)
        source += "\n" + (HERE / "LondonIsolatedFires.cs").read_text(encoding="ascii")
    if city_routes:
        source = city_crew_script(source, terrain, city_routes, crew_camera)
    if environment not in source or "DateTime.UtcNow" not in source:
        raise ValueError("The Fire Lab template changed")

    mission, count = re.subn(r"(?m)^(\[GlobalWind_0\]\n[ \t]*Power )[^\r\n]+",
                             lambda match: f"{match[1]}{east} {north} 0.000", mission)
    if count != 1:
        raise ValueError("The mission wind layer was not found")
    # Each aim point is calibrated against a logged bomb impact on HOTSEAT.
    attack_x, attack_y = ATTACK_POINTS[wind]
    route = ("[BoB_LW_JG54_III.34_Way]\n"
             "  NORMFLY 239500.00 232385.00 1050.00 315.00\n"
             f"  GATTACK_POINT {attack_x:.2f} {attack_y:.2f} 1050.00 315.00\n"
             "  NORMFLY 233400.00 232385.00 1050.00 315.00\n"
             "  NORMFLY 233400.00 231300.00 1050.00 315.00\n")
    mission, count = re.subn(r"(?m)^\[BoB_LW_JG54_III\.34_Way\]\n[^\[]+", route, mission)
    if count != 1:
        raise ValueError("The SC250 route was not found")
    # Steam reads yaw and pitch after the AGL height. BETA416 uses only XYZ.
    camera = "235235 232380 145 0 34 0 0" if steam else "235105 232380 115"
    if town:
        mission = town_series(mission, terrain.center)
        x, y = terrain.center
        camera = f"{x - 480} {y - 38 if village else y} {185 if village else 165}"
        if wide:
            camera = f"{x - 760} {y + 212} 245"
    mission = mission.split("[StaticCamera]", 1)[0] + f"[StaticCamera]\n  StaticCamera_0 {camera}\n"
    if london:
        mission = sightseeing_mission if sightseeing_mission is not None else london_mission(east, north)
    if warm_lights and not raid:
        # Keep the stock aircraft and mission settings for the close lighting comparison.
        mission = mission.removeprefix("\ufeff")
        approach = (
            ("152300.17 273409.41 2000.00 400.00", "150700.00 273785.00 300.00 280.00"),
            ("131564.22 268030.59 2000.00 400.00", "145000.00 273700.00 300.00 280.00"),
        )
        for before, after in approach:
            if mission.count(before) != 1:
                raise ValueError("Expected the stock London Sightseeing approach")
            mission = mission.replace(before, after)
    if raid or london_camera:
        if "[StaticCamera]" in mission:
            raise ValueError("The source mission already contains a fixed camera")
        fixed_view = LONDON_ATTACK_CAMERA if raid else LONDON_FIXED_CAMERA
        if city_raid:
            view = city_camera or LONDON_CITY_SCOUT_CAMERA
            if len(view) != 5 or not all(math.isfinite(value) for value in view) or view[2] <= 0:
                raise ValueError("Invalid central London camera")
            fixed_view = " ".join(f"{value:g}" for value in (*view, 0, 0))
        mission = mission.rstrip() + f"\n[StaticCamera]\n  StaticCamera_0 {fixed_view}\n"
    name = NAME
    if terrain:
        name += " - Scenery Fuel" if terrain.chart.get("native_scenery") else " - Chart Fuel"
    if large_fire:
        name += " - Large FX"
    if wind != "east":
        name += f" - {wind.title()} Wind"
    if steam:
        name += " - Steam"
    if town:
        name = f"{TOWN_NAME} - {terrain.cell_size}m"
        if front_fx:
            name += " Front"
    if village:
        name = "GroundFire Woodland Village Crew"
    if wide:
        name += " Wide"
    grass = ""
    if terrain is not None and terrain.grass_moisture is not None:
        grass = f" Grass fuel uses a test moisture ratio of {terrain.grass_moisture:g}."
        if not village:
            name += f" Grass {terrain.grass_moisture:g}"
    if object_fire and not village:
        name += " Object Fire"
    if effect_size != 1:
        name += f" {size_label} FX"
    if london:
        name = "GroundFire London Sightseeing Night" if sightseeing_mission is not None else "GroundFire London Winter Night"
    if warm_lights:
        name = "GroundFire London Warm Lights"
        if dusk:
            name += " Dusk"
    if london and steam:
        name = name.replace("GroundFire ", "GroundFire Steam VR Beta ", 1)
    if london_camera:
        name += " Fixed View"
    if raid:
        name = "GroundFire Steam VR Beta London Attack"
        if night_raid:
            name += " Daylight" if daylight else " Morning" if morning else " Dusk" if dusk else " Night"
        if city_raid:
            name += " City" if city_routes else " City Scout"
        if split_fx:
            name += " Split FX"
        if dense_fx:
            name += " Dense"
        if district_budget != DISTRICT_LIGHT_BUDGET:
            name += f" L{district_budget}"
        if warm_smoke:
            name += " Warm Smoke"
        if crew_camera is not None:
            name += f" Crew {crew_camera}"
    build = "Steam vrbeta 25283265" if steam else "HOTSEAT BETA416"
    if terrain and terrain.chart.get("native_scenery"):
        survey = " Uses chart-derived woodland, the native road mesh and placed building bounds."
    else:
        survey = " Uses chart-derived woodland fuel." if terrain else " Uses the authored woodland test plot."
    effect = "FireObject_0" if object_fire else "BuildingFireBig" if large_fire else "BuildingFireSmall"
    effect += f" at {size_label} size"
    instructions = ("Use Ctrl+F2 for the elevated, angled forest camera." if steam else
                    "Use Ctrl+F2 for the elevated forest camera. This build stores the camera position and height.")
    brief = f"""[Info]
<Name>
{name.removeprefix('GroundFire ')}
<Description>
Single-player recording test for the inspected {build} build. Start the bundled GroundFire bridge before loading. The AI SC250 flight has an attack waypoint at the forest east of Hawkinge. Wait for the impact at normal mission speed, then use the game time-speed control. The forest centre is 235455, 232385 in game coordinates. The HUD reports when an impact is accepted. Mission and fire-model wind are set toward the {wind} at 12 m/s.{survey}{grass} The mission uses the stock {effect} effect. {instructions}
[1]
<Name>
Observer aircraft
<Description>
Watch the forest from an external view or use the mission camera.
[2]
<Name>
SC 250 test flight
<Description>
This air group has the scripted attack waypoint.
"""
    if town:
        brief = f"""[Info]
<Name>
{name.removeprefix('GroundFire ')}
<Description>
Single-player test for HOTSEAT BETA416. Start the bundled GroundFire bridge before loading. Three AI aircraft each drop one SC 250 on separate aim points in Hawkinge. Keep normal time until the third impact. The HUD reports accepted impacts. Use Ctrl+F2 to switch to the elevated town camera. Wind blows toward the {wind} at 12 m/s. The {terrain.half * 2:g} m plot uses a {terrain.cell_size} m grid, chart-mapped built-up cover and native road geometry.{grass} The mission uses the stock {effect} effect.
[1]
<Name>
Observer aircraft
<Description>
Watch the town from the mission camera.
"""
        if village:
            brief = brief.replace(
                "Watch the town from the mission camera.",
                "Watch the wooded village from the mission camera. The first impact dispatches an emergency column "
                "from the south. A live Austin pump vehicle must stop at the road end before the hose can apply water.")
        if london:
            brief = f"""[Info]
<Name>
London Winter Night
<Description>
Single-player city fire exercise for HOTSEAT BETA416. Start the bundled bridge before loading. Nine scripted ground fires start over three batches in chart-mapped built-up cover. Use Ctrl+F2 for the elevated observer camera. The scene starts on a December evening with cloud cover and a {math.hypot(*LONDON_WIND):g} m/s wind toward the northeast. The fire model uses {LONDON_TEMP_C:g} C air and damp grass. These are scenario settings. The city fuel map covers {terrain.half * 2:g} m using {terrain.cell_size} m cells. The mission uses the stock {effect} effect.
[1]
<Name>
Observer aircraft
<Description>
Watch the ground fires using the mission camera.
"""
        if sightseeing_mission is not None:
            brief = f"""[Info]
<Name>
{name.removeprefix('GroundFire ')}
<Description>
Single-player ground fire test for {build}. Start the Fire Lab Bridge first. The stock London Sightseeing flight starts at 20:30. Nine ground fires start automatically at 15, 25 and 35 seconds. Look toward London from the Spitfire or use its external view. The fire model covers {terrain.half * 2:g} m in {terrain.cell_size} m cells, with damp open ground and {LONDON_TEMP_C:g} C air. The mission uses the stock {effect} effect.
[2]
<Name>
Observer aircraft
<Description>
Follow the stock London sightseeing route in the Spitfire.
"""
            if warm_lights:
                start_time = "20:15" if dusk else "20:30"
                brief = brief.replace(
                    "The stock London Sightseeing flight starts at 20:30.",
                    f"The 300 m London flyover starts at {start_time}. "
                    "Press A for autopilot and F2 for the external view.")
                brief = brief.replace(
                    f"The mission uses the stock {effect} effect.",
                    f"The mission uses the stock {effect} effect and up to three warm ground lights "
                    "that turn off as the fire effects retire.")
                brief = brief.replace("Follow the stock London sightseeing route in the Spitfire.",
                                      "Watch the buildings on the left as the fires start.")
            if london_camera:
                brief = brief.replace(
                    "Start the Fire Lab Bridge first.",
                    "Start the Fire Lab Bridge first. Press Ctrl+F2 for the 485 m fixed view over the Thames.")
    if raid:
        brief = """[Info]
<Name>
London Attack Ground Fire Test
<Description>
Start the matching Fire Lab Bridge. Use A for autopilot. The raised harbour camera is selected shortly after the mission starts. This mission retains the London Attack bomber formation, loadouts and route. The spread model starts from compatible ground impacts recorded by the game.
"""
        if night_raid:
            start_time = "10:30" if daylight else "06:05" if morning else "20:15" if dusk else "22:20"
            brief += f"The mission starts at {start_time}. Active dock fires light nearby scenery with independently pulsing red and orange light.\n"
        if city_raid:
            brief = brief.replace("the raised harbour camera", "the raised city camera").replace("dock fires", "city fires")
        if city_routes:
            brief += "City pump crews dispatch after a fire starts. They set up and apply water once stopped within hose reach.\n"
        if crew_camera is not None:
            brief += f"The external view follows Pump {crew_camera} once it dispatches.\n"
        if split_fx:
            brief += "Flame effects follow burning cells, while separate smoke plumes follow areas producing the most smoke.\n"
        if dense_fx:
            brief += "Larger flames share the scene with steady, softly flickering district lights.\n"
        if warm_smoke:
            brief += "Smoke glow builds gradually, reaching higher as the fire intensifies.\n"
        if isolated_fires:
            brief += "Up to eight separated ground impacts seed fires. Flame scale follows the local burn intensity.\n"
    files = {f"{name}.{suffix}": value.encode("utf-8")
             for suffix, value in (("cs", source), ("mis", mission), ("briefing", brief))}
    destination = DESTINATION
    if town:
        plot = "london-night" if london else "woodland-village" if village else "town"
        if sightseeing_mission is not None:
            plot = ("london-city-response" if city_routes else "london-city-scout" if city_raid else
                    "london-attack-night" if night_raid else "london-attack" if raid else
                    "london-sightseeing-warm-lights" if warm_lights else "london-sightseeing-night")
            if dusk:
                plot += "-dusk"
            if morning:
                plot += "-morning"
            if daylight:
                plot += "-daylight"
            if crew_camera is not None:
                plot += f"-crew{crew_camera}"
            if steam:
                plot += "-steam-vrbeta"
            if london_camera:
                plot += "-fixed"
        if wide:
            plot += f"-{terrain.half * 2:g}m"
        destination /= f"{plot}-{terrain.cell_size}m" + ("-front" if front_fx else "") + terrain.grass_suffix
        if object_fire:
            destination = destination.with_name(destination.name + "-object")
        if effect_size != 1:
            destination = destination.with_name(destination.name + "-fx-" + size_label.replace(".", "p"))
        if split_fx:
            destination = destination.with_name(destination.name + "-split")
        if dense_fx:
            destination = destination.with_name(destination.name + "-dense")
        if district_budget != DISTRICT_LIGHT_BUDGET:
            destination = destination.with_name(destination.name + f"-l{district_budget}")
        if warm_smoke:
            destination = destination.with_name(destination.name + "-warm-smoke")
        if isolated_fires:
            destination = destination.with_name(destination.name + "-isolated")
    elif name != NAME:
        destination /= name.removeprefix(NAME + " - ").lower().replace(" - ", "-").replace(" ", "-")
    write_files(destination, files)
    with ZipFile(destination / "hotseat-capture.zip", "w", ZIP_DEFLATED) as bundle:
        for filename in files:
            bundle.write(destination / filename, f"mission/{filename}")
        command = '@echo off\r\npy -3 -B "%~dp0integrations\\clod\\fire_lab.py"'
        if terrain:
            bundle.write(terrain.path, "bridge/terrain/hawkinge-woodland.json")
            bundle.write(terrain.path.parent / terrain.chart["filename"], "bridge/terrain/" + terrain.chart["filename"])
            command += ' --terrain "%~dp0terrain\\hawkinge-woodland.json"'
        if front_fx:
            command += " --front-fx"
        if night_raid:
            command += " --light-data"
        if split_fx:
            command += " --split-fx"
        if dense_fx:
            command += " --dense-fx"
        if district_budget != DISTRICT_LIGHT_BUDGET:
            command += f" --district-lights {district_budget}"
        if warm_smoke:
            command += " --warm-smoke"
            profile = "profile/GroundFireEffects/"
            template = (HERE / "WarmSmoke.eff").read_text(encoding="ascii")
            common = re.search(r"(?ms)^\[SmokeUpper\]\n(.*?)(?=^\[|\Z)", template).group(1).strip()
            for layer in ("Lower", "Middle", "Upper"):
                ages = re.search(rf"(?ms)^\[Smoke{layer}\]\n(.*?)(?=^\[|\Z)", template).group(1)
                colors = "\n".join(line for line in ages.splitlines() if line.startswith("Colors"))
                emitter = re.sub(r"(?m)^Colors0[^\n]+(?:\nColors\d[^\n]+){5}", colors, common)
                asset = f"[ClassInfo]\nClassName TParticleSystemParams\n\n[General]\nSmoke0\n\n[Smoke0]\n{emitter}\n"
                bundle.writestr(profile + f"WarmSmokePlume{layer}.eff", asset)
            bundle.write(HERE / "WarmSmoke.mma", profile + "WarmSmokePlume.mma")
            bundle.write(smoke_atlas, profile + "Smoke_Sprites_Air_W.dds")
        bundle.writestr("bridge/Launch Fire Lab Bridge.cmd", command + "\r\n")
        bundle.write(PROTOTYPE / "integrations/clod/fire_lab.py", "bridge/integrations/clod/fire_lab.py")
        for module in (PROTOTYPE / "firesim").glob("*.py"):
            bundle.write(module, "bridge/firesim/" + module.name)
    print(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terrain", type=Path, help="Use the matching chart-derived woodland grid")
    parser.add_argument("--steam", action="store_true", help="Target the inspected Steam build with camera pitch support")
    assets = parser.add_mutually_exclusive_group()
    assets.add_argument("--large-fire", action="store_true", help="Use the stock BuildingFireBig effect")
    assets.add_argument("--object-fire", action="store_true", help="Use the stock FireObject_0 effect")
    parser.add_argument("--wind", choices=WINDS, default="east", help="Direction the wind blows toward")
    parser.add_argument("--front-fx", action="store_true", help="Use fixed fire emitters across the town")
    parser.add_argument("--effect-size", type=float, default=1.0, help="Initial size multiplier for each stock effect")
    parser.add_argument("--london-sightseeing", type=Path, help="Use a local copy of the shipped London Sightseeing mission")
    parser.add_argument("--warm-lights", action="store_true", help="Add warm lights and a low London flyover")
    parser.add_argument("--dusk", action="store_true", help="Start the warm-light London flyover at 20:15")
    parser.add_argument("--london-camera", action="store_true", help="Add the raised London camera on Steam vrbeta")
    parser.add_argument("--london-attack", type=Path, help="Instrument the installed London Attack mission on Steam vrbeta")
    parser.add_argument("--night-raid", action="store_true", help="Start London Attack at 22:20 with pulsing fire lights")
    parser.add_argument("--city-raid", action="store_true", help="Use the central London night raid test site")
    parser.add_argument("--city-camera", type=float, nargs=5, help="Set the camera position, height, yaw and pitch")
    parser.add_argument("--city-routes", type=Path, help="Add tested road routes for the central London fire crews")
    parser.add_argument("--crew-camera", type=int, choices=(1, 2, 3, 4), help="Fly the daylight raid and follow this pump")
    parser.add_argument("--split-fx", action="store_true", help="Use separate flame and smoke emitters in the city raid")
    parser.add_argument("--dense-fx", action="store_true", help="Use dense flames and separate district lights")
    parser.add_argument("--morning", action="store_true", help="Set the London city raid to 06:05")
    parser.add_argument("--daylight", action="store_true", help="Set the London city raid to 10:30")
    parser.add_argument("--district-lights", type=int, choices=(12, 24), default=DISTRICT_LIGHT_BUDGET)
    parser.add_argument("--light-benchmark", action="store_true", help="Enable 12/24-light comparisons after the flight")
    parser.add_argument("--warm-smoke", action="store_true", help="Light the lower smoke particles in the night test")
    parser.add_argument("--smoke-atlas", type=Path, help="Use Smoke_Sprites_Air_W.dds extracted from the installed game")
    parser.add_argument("--isolated-fires", action="store_true", help="Use spaced impact ignitions and variable flame sizes")
    args = parser.parse_args()
    prepare(WoodlandTerrain.load(args.terrain) if args.terrain else None, args.steam, args.large_fire,
            args.wind, args.front_fx, args.effect_size, args.object_fire, args.london_sightseeing,
            args.warm_lights, args.dusk, args.london_camera, args.london_attack, args.night_raid,
            args.city_raid, args.city_camera, args.city_routes, args.split_fx, args.dense_fx,
            args.morning, args.district_lights, args.light_benchmark, args.warm_smoke, args.smoke_atlas,
            args.isolated_fires, args.crew_camera, args.daylight)
