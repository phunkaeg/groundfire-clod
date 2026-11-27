#define LONDON_WARM_SMOKE
#define LONDON_DISTRICT_LIGHTS
#define LONDON_PULSING_LIGHTS
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using maddox.core;
using maddox.GP;
using maddox.game;
using maddox.game.world;

public partial class Mission : AMission
{
    private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
    private static readonly string Folder = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GroundFireHawkinge", "lab-town-20m-149120-274144-3200m-grass-0p5-front-pulse-split-dense-l24-warm-smoke");
    private const string Asset = "$core/3do/sfx/fire/BuildingFireBig.eff";
    private const int PlumeBudget = 176;
    private const int TotalEffectBudget = 192;
    private const string MissionEnvironment = "15\t3.000\t0.000\t55657956b3d3c864184c56d6dc98116d8bdfa92a96ed17f8a9343e17c6b8203b";
    private static readonly string[] Plots = { "forest", "field", "hedge", "town" };
    private static readonly double[,] Centers = { { 235455, 232385 }, { 234503, 232745 }, { 235450, 232700 }, { 149120, 274144 } };
    private static readonly string[] Roots = {
        "Forest", "Field", "Hedgerow", "Town and buildings", "Wind toward",
        "Wind speed", "Fire clock", "Weather", "Water, reset and status"
    };
    private static readonly string[][] Options = {
        new[] { "1 fire", "2 fires", "3 fires" },
        new[] { "1 fire", "2 fires", "3 fires" },
        new[] { "1 continuous hedge fire", "1 hedge fire with 10 m gap" },
        new[] { "1 town fire", "2 town fires", "3 town fires", "House row", "Factory bay" },
        new[] { "N", "NE", "E", "SE", "S", "SW", "W", "NW" },
        new[] { "Calm", "2 m/s", "6 m/s", "12 m/s" },
        new[] { "Hold fire clock", "1x mission time", "4x mission time", "16x mission time" },
        new[] { "Mission defaults", "Summer 23 C", "Winter 5 C", "Toggle rain", "Toggle embers" },
        new[] { "Apply test water", "Clear plot", "Status" }
    };
    private static readonly string[][] Actions = {
        new[] { "seed\tforest\t1", "seed\tforest\t2", "seed\tforest\t3" },
        new[] { "seed\tfield\t1", "seed\tfield\t2", "seed\tfield\t3" },
        new[] { "seed\thedge\t1", "seed\thedge_gap\t1" },
        new[] { "seed\ttown\t1", "seed\ttown\t2", "seed\ttown\t3", "seed\thouses\t1", "seed\tfactory\t1" },
        new[] { "wind\ttoward\tN", "wind\ttoward\tNE", "wind\ttoward\tE", "wind\ttoward\tSE",
                "wind\ttoward\tS", "wind\ttoward\tSW", "wind\ttoward\tW", "wind\ttoward\tNW" },
        new[] { "wind\tspeed\t0", "wind\tspeed\t2", "wind\tspeed\t6", "wind\tspeed\t12" },
        new[] { "rate\t0", "rate\t1", "rate\t4", "rate\t16" },
        new[] { "weather\tmission", "weather\tsummer", "weather\twinter", "weather\train", "weather\tembers" },
        new[] { "water", "reset", "status" }
    };

    private readonly Dictionary<string, object> effects = new Dictionary<string, object>();
    private readonly List<object> fading = new List<object>();
    private readonly double?[] cachedGround = new double?[Plots.Length];

    private bool windSampled;

    private void SampleMissionWind()
    {
        double? ground = CaptureTerrainHeight(Centers[3, 0], Centers[3, 1]);
        if (windSampled || Now < 5 || !ground.HasValue)
            return;
        windSampled = true;
        try
        {
            foreach (Assembly engine in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (engine.GetName().Name != "maddox" ||
                    engine.ManifestModule.ModuleVersionId != new Guid("8e7a2ac5-43e4-45fc-8ef5-f4e3d36baff3") ||
                    typeof(WWeather).Module.ModuleVersionId != new Guid("7cabe1d9-b513-4d66-82fb-8d66589e5f09"))
                    continue;
                Type owner = engine.GetType("IN9ja8czYVm8g9Yda3jVhIdZoiD0Iurfl52UO1fGq$WF", true);
                MethodInfo getter = owner.GetMethod("9N8E$o$ey_2hz00$ZCHe4ck", BindingFlags.Public | BindingFlags.Static,
                    null, Type.EmptyTypes, null);
                if (getter == null || getter.ReturnType != typeof(WWeather))
                    throw new MissingMethodException("Unexpected mission weather getter");
                WWeather weather = (WWeather)getter.Invoke(null, null);
                foreach (int height in new[] { 1, 20, 100 })
                {
                    var point = new Point3d(Centers[3, 0], Centers[3, 1], ground.Value + height);
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


    private MethodInfo terrainHeight;

    private double? CaptureTerrainHeight(double x, double y)
    {
        if (terrainHeight == null)
        {
            foreach (Assembly engine in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (engine.GetName().Name != "maddox" ||
                    engine.ManifestModule.ModuleVersionId != new Guid("8e7a2ac5-43e4-45fc-8ef5-f4e3d36baff3") ||
                    typeof(WWeather).Module.ModuleVersionId != new Guid("7cabe1d9-b513-4d66-82fb-8d66589e5f09"))
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

    private string session;
    private double start;
    private double pollAt;
    private double receivedAt;
    private int sequence;
    private long frame;
    private long hud;
    private bool stopped;
    private bool menuFailed;
    private bool effectFailed;
    private Player menuPlayer;
    private MethodInfo createEffect;
    private MethodInfo finishEffect;
    private FieldInfo particle;

    private double Now { get { return Time.TicksToSecs(Time.tickCounter()) - start; } }

    public override void OnBattleStarted()
    {
        base.OnBattleStarted();
        if (!GamePlay.gpIsServerSingle())
            return;
        try
        {
            start = Time.TicksToSecs(Time.tickCounter());
            session = Guid.NewGuid().ToString("N");
            Directory.CreateDirectory(Folder);
            Record("init\t" + MissionEnvironment);
            Note("fx_budget active=" + PlumeBudget + " total=" + TotalEffectBudget);
            Note("fx_size 4 asset=" + Asset);
            string ready = Path.Combine(Folder, "active.txt");
            string temporary = Path.Combine(Folder, session + ".ready");
            File.WriteAllText(temporary, session);
            if (File.Exists(ready))
                File.Replace(temporary, ready, null);
            else
                File.Move(temporary, ready);
            GamePlay.gpHUDLogCenter("Hawkinge Fire Lab. Open Mission orders with the bridge running.");
        }
        catch (Exception error)
        {
            Report(error);
            stopped = true;
        }
    }

    public override void OnPlaceEnter(Player player, AiActor actor, int placeIndex)
    {
        base.OnPlaceEnter(player, actor, placeIndex);
        if (session != null && !stopped && player != null && player == GamePlay.gpPlayer())
            InstallMenu(player);
    }

    private void InstallMenu(Player player)
    {
        if (player == null || menuFailed)
            return;
        try
        {
            GamePlay.gpSetOrderMissionMenu(player, false, 0, Roots,
                new[] { true, true, true, true, true, true, true, true, true });
            menuPlayer = player;
        }
        catch (Exception error)
        {
            menuFailed = true;
            Report(error);
            GamePlay.gpHUDLogCenter("Mission orders unavailable. Use the Fire Lab bridge console.");
        }
    }

    public override void OnOrderMissionMenuSelected(Player player, int id, int item)
    {
        base.OnOrderMissionMenuSelected(player, id, item);
        if (session == null || stopped || menuFailed || player == null || player != menuPlayer)
            return;
        try
        {
            if (id == 0 && item >= 1 && item <= Options.Length)
            {
                string[] options = Options[item - 1];
                GamePlay.gpSetOrderMissionMenu(player, true, item, options, new bool[options.Length]);
            }
            else if (id >= 1 && id <= Actions.Length)
            {
                if (item >= 1 && item <= Actions[id - 1].Length)
                    Record(Actions[id - 1][item - 1]);
                InstallMenu(player);
            }
        }
        catch (Exception error)
        {
            Report(error);
        }
    }

    public override void OnBombExplosion(string title, double mass, Point3d pos,
                                         AiDamageInitiator initiator, int eventArgInt)
    {
        base.OnBombExplosion(title, mass, pos, initiator, eventArgInt);
        if (session == null || stopped)
            return;
        try
        {
            double x = pos.x - Centers[3, 0], y = pos.y - Centers[3, 1];
            bool inPlot = x >= -1600 && x < 1600 && y >= -1600 && y < 1600;
            double? height = inPlot ? CaptureTerrainHeight(pos.x, pos.y) : null;
            string id = (title ?? "").ToUpperInvariant().Replace("-", "").Replace(" ", "").Replace("_", "");
            Match weapon = Regex.Match(id, "SC(?:1000|500|250|50)(?![0-9])");
            string type = weapon.Success ? weapon.Value : "";
            string fit = "";
            bool accepted = type != "" && (fit == "" || fit == type) &&
                            Finite(x) && Finite(y) && Finite(pos.z) && height.HasValue &&
                            inPlot && Math.Abs(pos.z - height.Value) <= 20;
            Note(String.Format(Invariant, "bomb title={0} mass_raw={1:R} x={2:R} y={3:R} z={4:R} type={5} fit={6} t={8:F6} ground_z={9} agl={10} accepted={7}",
                               title, mass, pos.x, pos.y, pos.z, type, fit, accepted, Now,
                               height.HasValue ? height.Value.ToString("F3", Invariant) : "unknown",
                               height.HasValue ? (pos.z - height.Value).ToString("F3", Invariant) : "unknown"));
            if (accepted && SampleRaidImpact(pos))
                Record(String.Format(Invariant, "bomb\t{0}\t{1:R}\t{2:R}", type, pos.x, pos.y));
            else if (!accepted && type != "")
                GamePlay.gpHUDLogCenter("Fire Lab impact outside the town test plot or type mismatch.");
        }
        catch (Exception error)
        {
            Report(error);
        }
    }

    private static string AircraftFit(AiActor actor)
    {
        if (actor == null)
            return "";
        string name = actor.Name() ?? "";
        if (actor.Group() != null)
            name += " " + actor.Group().Name();
        if (name.IndexOf("BoB_LW_ErprGr210F", StringComparison.OrdinalIgnoreCase) >= 0)
            return "SC50";
        return name.IndexOf("BoB_LW_JG54_III", StringComparison.OrdinalIgnoreCase) >= 0 ? "SC250" : "";
    }

    public override void OnTickGame()
    {
        base.OnTickGame();
        PulseCityLights();
        if (session == null || stopped || Now < pollAt)
            return;
        double now = Now;
        pollAt = now + 0.5;
        try
        {
            RefreshFireLighting(now);
            Player player = GamePlay.gpPlayer();
            if (menuPlayer == null)
                InstallMenu(player);
            GroundHeight(0);
            SampleMissionWind();
            Record("clock\t" + GamePlay.gpTimeofDay().ToString("R", Invariant) + "\t" + (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds.ToString("F6", Invariant));
            SelectRaidCamera(now);
            CheckWarmSmoke(now);
            ReadFrame(now);
            ObserveCityCrews(now);
            ObserveCityLights();
            if (now - receivedAt > 15 && (effects.Count != 0 || cityLights.Count != 0))
                Apply(new Dictionary<string, Tuple<int, double, double>>());
        }
        catch (IOException)
        {
            // The bridge can replace its output during a read.
        }
        catch (Exception error)
        {
            Report(error);
        }
    }

    public override void OnBattleStoped()
    {
        if (session != null && !stopped)
        {
            stopped = true;
            try
            {
                Apply(new Dictionary<string, Tuple<int, double, double>>());
                Record("stop");
            }
            catch (Exception error)
            {
                Report(error);
            }
        }
        base.OnBattleStoped();
    }

    private void ReadFrame(double now)
    {
        if (warmSmokeHeld)
        {
            receivedAt = now;
            return;
        }
        string path = Path.Combine(Folder, session + ".plumes.tsv");
        if (!File.Exists(path))
            return;
        string[] lines = File.ReadAllLines(path);
        if (lines.Length < 1 || lines.Length > PlumeBudget + 1)
            return;
        string[] header = lines[0].Split(new[] { '\t' }, 5);
        long version, message;
        double time;
        if (header.Length != 5 || header[0] != session ||
            !Int64.TryParse(header[1], out version) || version <= frame ||
            !Parse(header[2], out time) || time > now + 0.01 || now - time > 15 ||
            !Int64.TryParse(header[3], out message))
            return;
        var strengths = new Dictionary<string, double>();
        var desired = new Dictionary<string, Tuple<int, double, double>>();
        for (int i = 1; i < lines.Length; ++i)
        {
            string[] row = lines[i].Split('\t');
            double x, y, strength;
            if (row.Length != 5 ||
                !Parse(row[4], out strength) || strength < 0 || strength > 1 || !Regex.IsMatch(row[0], @"^\d+_P\d+_\d+_\d+$") ||
                desired.ContainsKey(row[0]) || !Parse(row[2], out x) || !Parse(row[3], out y))
                return;
            int plot = Array.IndexOf(Plots, row[1]);
            double half = plot == 3 ? 1600 : 80;
            if (plot < 0 || Math.Abs(x - Centers[plot, 0]) > half || Math.Abs(y - Centers[plot, 1]) > half)
                return;
            desired.Add(row[0], Tuple.Create(plot, x, y));
            strengths.Add(row[0], strength);
        }
        cityLightStrength = strengths;
        receivedAt = now;
        frame = version;
        if (message > hud && header[4].Length <= 250)
        {
            GamePlay.gpHUDLogCenter(header[4]);
            hud = message;
        }
        if (!effectFailed)
        {
            try
            {
                Apply(desired);
            }
            catch (Exception error)
            {
                effectFailed = true;
                Report(error);
                GamePlay.gpHUDLogCenter("Fire Lab visual binding failed. Simulation controls remain available.");
            }
        }
    }

    private void Apply(Dictionary<string, Tuple<int, double, double>> desired)
    {
        if (desired.Count == 0 && effects.Count == 0 && cityLights.Count == 0)
            return;
        if (createEffect == null)
            BindEffects();
        ReconcileDistrictLights(desired);
        fading.RemoveAll(delegate(object actor) { return particle.GetValue(actor) == null; });
        foreach (string id in new List<string>(effects.Keys))
        {
            if (!desired.ContainsKey(id))
            {
                object actor = effects[id];
                EndCityLight(id);
                finishEffect.Invoke(null, new[] { actor });
                fading.Add(actor);
                Note(String.Format(Invariant, "plume_finished {0} {1:F6}", id, Now));
                effects.Remove(id);
                flameBands.Remove(id);
            }
        }
        foreach (var item in desired)
        {
            bool smokeOnly = item.Key.Contains("_P2_");
            double strength = 0;
            int band = smokeOnly ? -1 : FlameBand(item.Key, out strength);
            object previous;
            bool exists = effects.TryGetValue(item.Key, out previous);
            if ((exists && (smokeOnly || flameBands[item.Key] == band)) ||
                effects.Count + fading.Count >= TotalEffectBudget)
                continue;
            double? z = item.Value.Item1 == 3 ? CaptureTerrainHeight(item.Value.Item2, item.Value.Item3)
                                              : GroundHeight(item.Value.Item1);
            if (!z.HasValue)
                continue;
            double height = z.Value + (item.Key.Contains("_P4_") ? 5.5 : 0);
            var loc = new Loc(item.Value.Item2, item.Value.Item3, height, 0, 0, 0);
            object effect = createEffect.Invoke(null, new object[] { loc, smokeOnly ? 4f : FlameScales[band], Asset, -1.0, true });
            if (effect == null || particle.GetValue(effect) == null)
                throw new InvalidOperationException("Ground fire factory returned no emitter.");
            SeparateCityEffect(effect, smokeOnly);
            if (exists)
            {
                finishEffect.Invoke(null, new[] { previous });
                fading.Add(previous);
            }
            effects[item.Key] = effect;
            if (!smokeOnly)
            {
                flameBands[item.Key] = band;
                Note(String.Format(Invariant, "flame_scale {0} {1:F6} {2:F2} {3:F3}",
                                   item.Key, Now, FlameScales[band], strength));
            }
            if (exists)
                continue;
            Note(String.Format(Invariant, "plume_created {0} {1:F6} {2:F3} {3:F3}",
                               item.Key, Now, item.Value.Item2, item.Value.Item3));
        }
        ReconcileWarmSmoke(desired, 4f);
    }

    private void BindEffects()
    {
        Assembly engine = null;
        foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
            if (assembly.GetName().Name == "maddox")
                engine = assembly;
        if (engine == null || engine.ManifestModule.ModuleVersionId != new Guid("8e7a2ac5-43e4-45fc-8ef5-f4e3d36baff3") ||
            typeof(WEff3D).Module.ModuleVersionId != new Guid("7cabe1d9-b513-4d66-82fb-8d66589e5f09"))
            throw new InvalidOperationException("The installed effect assemblies differ from the inspected build.");
        Type actor = engine.GetType("yfF_qZl67WlmNS9coEvP0_bSaSCDSqkcGRjRO0s$kmQH", true);
        const BindingFlags methods = BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly;
        MethodInfo create = actor.GetMethod("ZNpynOtOqVuCJyfuWKwJwy0", methods, null,
            new[] { typeof(Loc).MakeByRefType(), typeof(float), typeof(string), typeof(double), typeof(bool) }, null);
        MethodInfo finish = actor.GetMethod("F6mh8rjUa2GGR$0BBCl7kQA", methods, null, new[] { actor }, null);
        FieldInfo emitter = actor.GetField("JfGsspZfCQ8TatQl98$8kEs",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
        if (create == null || create.ReturnType != actor || finish == null || finish.ReturnType != typeof(void) ||
            emitter == null || emitter.FieldType != typeof(WEff3D))
            throw new MissingMemberException("Unexpected effect actor signature.");
        createEffect = create;
        finishEffect = finish;
        particle = emitter;
    }

    private double? GroundHeight(int plot)
    {
        if (cachedGround[plot].HasValue)
            return cachedGround[plot];
        double x = Centers[plot, 0], y = Centers[plot, 1];
        string name = "Static72" + (plot + 1).ToString("00", Invariant);
        var markers = GamePlay.gpGroundStationarys(x, y, 5);
        if (markers != null)
        {
            foreach (GroundStationary marker in markers)
            {
                Point3d pos = marker.pos;
                if (marker.Name != null &&
                    (marker.Name == name || marker.Name.EndsWith(":" + name, StringComparison.Ordinal)) &&
                    Math.Abs(pos.x - x) < 2 && Math.Abs(pos.y - y) < 2 && Finite(pos.z))
                    return cachedGround[plot] = pos.z;
            }
        }
        return null;
    }

    private static bool Parse(string value, out double parsed)
    {
        return Double.TryParse(value, NumberStyles.Float, Invariant, out parsed) && Finite(parsed);
    }

    private static bool Finite(double value)
    {
        return !Double.IsNaN(value) && !Double.IsInfinity(value);
    }

    private void Record(string command)
    {
        string line = String.Format(Invariant, "{0}\t{1:F6}\t{2}\n", sequence + 1, Now, command);
        File.AppendAllText(Path.Combine(Folder, session + ".events.tsv"), line);
        sequence++;
    }

    private void Note(string line)
    {
        File.AppendAllText(Path.Combine(Folder, session + ".flight.log"), line.Replace("\r", " ").Replace("\n", " ") + "\n");
    }

    private void Report(Exception error)
    {
        try
        {
            Note(error.GetBaseException().Message);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}

public partial class Mission
{
#if LONDON_DISTRICT_LIGHTS
    private const int CityLightBudget = 24;
    private const double CityLightSpacing = 105.0;
    private const float CityLightRadius = 165f;
#elif LONDON_PULSING_LIGHTS
    private const int CityLightBudget = 6;
    private const double CityLightSpacing = 125.0;
    private const float CityLightRadius = 140f;
#else
    private const int CityLightBudget = 3;
    private const float CityLightIntensity = 2f;
    private const double CityLightSpacing = 160.0;
    private const float CityLightRadius = 140f;
#endif
    private const double CityLightHeight = 12.0;

    private sealed class CityLight
    {
        public WLightPoint Light;
        public object Owner;
        public Point3d Anchor;
        public bool RenderPositionLogged;
#if LONDON_PULSING_LIGHTS
        public double Phase;
#endif
#if LONDON_DISTRICT_LIGHTS
        public double Strength;
        public double UpdatedAt;
#endif
    }

    private readonly Dictionary<string, CityLight> cityLights = new Dictionary<string, CityLight>();
    private FieldInfo effectDraw;
    private ConstructorInfo ownedPointLight;
    private FieldInfo lightOffset;
    private MethodInfo attachLight;
    private MethodInfo setOwnedEmission;
    private bool cityLightFailed;

#if LONDON_PULSING_LIGHTS
    private Dictionary<string, double> cityLightStrength = new Dictionary<string, double>();
    private readonly System.Diagnostics.Stopwatch cityLightClock = System.Diagnostics.Stopwatch.StartNew();
    private double nextCityLightUpdate;
    private double nextCityLightSample;

    private void ApplyCityLight(WLightPoint light, double phase, double strength, double seconds,
        out float green, out float intensity)
    {
        // Using wall time keeps the flicker readable at accelerated mission time.
#if LONDON_DISTRICT_LIGHTS
        double pulse = 1.0 + 0.06 * Math.Sin(seconds * 2.8 + phase)
                           + 0.035 * Math.Sin(seconds * 6.2 + phase * 1.61);
        double colorHeat = 0.75 * Math.Sqrt(strength);
        intensity = (float)(3.8 * strength * pulse);
#else
        double pulse = 0.83 + 0.13 * Math.Sin(seconds * 5.3 + phase)
                            + 0.08 * Math.Sin(seconds * 11.9 + phase * 1.61);
        double colorHeat = Math.Sqrt(strength) * (0.72 + 0.28 * Math.Sin(seconds * 2.4 + phase));
        intensity = (float)((0.35 + 4.10 * strength) * pulse);
#endif
        intensity *= (float)fireNightFactor;
        green = (float)(0.18 + 0.36 * colorHeat);
        var color = new Tuple3f(1f, green, (float)(0.045 + 0.18 * colorHeat));
        light.setColor(ref color);
        setOwnedEmission.Invoke(light, new object[] { intensity, CityLightRadius });
    }

    private void PulseCityLights()
    {
        if (fireNightFactor <= 0)
            return;
#if LONDON_WARM_SMOKE
        if (warmSmokeHeld)
            return;
#endif
#if LONDON_LIGHT_BENCHMARK
        if (lightBenchFrozen)
            return;
#endif
        double seconds = cityLightClock.Elapsed.TotalSeconds;
        if (cityLightFailed || cityLights.Count == 0 || seconds < nextCityLightUpdate)
            return;
        nextCityLightUpdate = seconds + 1.0 / 12.0;
        bool sample = seconds >= nextCityLightSample;
        if (sample)
            nextCityLightSample = seconds + 4.0;
        try
        {
            foreach (var item in cityLights)
            {
                CityLight city = item.Value;
                double strength;
                if (particle.GetValue(city.Owner) == null)
                    continue;
#if LONDON_DISTRICT_LIGHTS
                cityLightStrength.TryGetValue(item.Key, out strength);
                double dt = Math.Min(0.25, seconds - city.UpdatedAt);
                double fadeSeconds = strength >= city.Strength ? 2.1 : 5;
                city.Strength += (strength - city.Strength) * (1 - Math.Exp(-dt / fadeSeconds));
                city.UpdatedAt = seconds;
                strength = city.Strength;
#else
                if (!cityLightStrength.TryGetValue(item.Key, out strength))
                    continue;
#endif
                float green, intensity;
                ApplyCityLight(city.Light, city.Phase, strength, seconds, out green, out intensity);
                if (sample)
                    Note(String.Format(Invariant, "city_light_pulse {0} {1:F6} {2:F3} {3:F3} {4:F3}",
                        item.Key, Now, strength, green, intensity));
            }
        }
        catch (Exception error)
        {
            cityLightFailed = true;
            Note("city_light_error " + error.GetBaseException().Message);
        }
    }
#endif

    private void BindCityLights(Type effect)
    {
        // BindEffects has already verified the exact engine assemblies.
        const BindingFlags fields = BindingFlags.Instance | BindingFlags.Public |
            BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
        Type owner = effect.BaseType;
        Type light = effect.Assembly.GetType("iAGyqzCT7GrCImqReh9aGOE0UYDNoV6Lh8AHseKFcifx", true);
        if (!typeof(WLightPoint).IsAssignableFrom(light))
            throw new InvalidOperationException("Unexpected city light type.");
        effectDraw = owner.GetField("KJnEE1bYssohV97HSzi8Wdo", fields);
        ownedPointLight = light.GetConstructor(new[] { owner });
        lightOffset = light.GetField("H$9tex8fHhAXegggcDlXQxY", fields);
        setOwnedEmission = light.GetMethod("2TSXkZX9YWjHrJEckGyXMFI", new[] { typeof(float), typeof(float) });
        if (effectDraw == null || ownedPointLight == null || lightOffset == null ||
            lightOffset.FieldType != typeof(Point3d) || setOwnedEmission == null ||
            setOwnedEmission.ReturnType != typeof(void))
            throw new MissingMemberException("Unexpected point light binding.");
        attachLight = effectDraw.FieldType.GetMethod("MW_GUZt3_kbiRW8Vr6GtNf8",
            new[] { typeof(string), light });
        if (attachLight == null || attachLight.ReturnType != typeof(void))
            throw new MissingMemberException("Unexpected effect draw light binding.");
    }

    private void TryLightCityFire(string id, int plot, object effect, Point3d anchor)
    {
        if (fireNightFactor <= 0 || cityLightFailed || Plots[plot] != "town" || cityLights.Count >= CityLightBudget)
            return;

        foreach (CityLight other in cityLights.Values)
        {
            double dx = anchor.x - other.Anchor.x, dy = anchor.y - other.Anchor.y;
            if (dx * dx + dy * dy < CityLightSpacing * CityLightSpacing)
                return;
        }

        WLightPoint light = null;
        bool owned = false;
        try
        {
            if (attachLight == null)
                BindCityLights(effect.GetType());
            object draw = effectDraw.GetValue(effect);
            if (draw == null)
                throw new InvalidOperationException("Fire effect has no draw owner.");
            light = (WLightPoint)ownedPointLight.Invoke(new[] { effect });
            lightOffset.SetValue(light, new Point3d(0, 0, CityLightHeight));
            var city = new CityLight { Light = light, Owner = effect, Anchor = anchor };
#if LONDON_PULSING_LIGHTS
            city.Phase = (anchor.x * 0.713 + anchor.y * 0.419) % (2 * Math.PI);
            double strength;
#if LONDON_DISTRICT_LIGHTS
            strength = 0;
            city.UpdatedAt = cityLightClock.Elapsed.TotalSeconds;
#else
            cityLightStrength.TryGetValue(id, out strength);
#endif
            float green, intensity;
            ApplyCityLight(light, city.Phase, strength, cityLightClock.Elapsed.TotalSeconds, out green, out intensity);
#else
            var color = new Tuple3f(1f, 0.48f, 0.20f);
            light.setColor(ref color);
            setOwnedEmission.Invoke(light, new object[] { (float)(CityLightIntensity * fireNightFactor), CityLightRadius });
#endif
            // The effect submits the light each frame and disposes it with the draw owner.
            attachLight.Invoke(draw, new object[] { "GroundFireCity", light });
            owned = true;
            cityLights.Add(id, city);
            Note(String.Format(Invariant, "city_light_on {0} {1:F6} {2:F1} {3:F1} {4:F1}",
                id, Now, anchor.x, anchor.y, anchor.z + CityLightHeight));
        }
        catch (Exception error)
        {
            cityLightFailed = true;
            if (light != null && !owned)
                ((IDisposable)light).Dispose();
            Note("city_light_error " + error.GetBaseException().Message);
        }
    }

#if !LONDON_DISTRICT_LIGHTS
    private void ReconcileAttachedCityLights(Dictionary<string, Tuple<int, double, double>> desired)
    {
        if (fireNightFactor <= 0 || cityLightFailed)
            return;
#if !LONDON_PULSING_LIGHTS
        foreach (CityLight light in cityLights.Values)
            if (particle.GetValue(light.Owner) != null)
                setOwnedEmission.Invoke(light.Light, new object[] {
                    (float)(CityLightIntensity * fireNightFactor), CityLightRadius });
#endif
        foreach (var point in desired)
        {
            object effect;
            if (cityLights.Count >= CityLightBudget)
                break;
            if (point.Key.Contains("_P2_") || cityLights.ContainsKey(point.Key) ||
                !effects.TryGetValue(point.Key, out effect))
                continue;
            var p = point.Value;
            double? ground = CaptureTerrainHeight(p.Item2, p.Item3);
            if (ground.HasValue)
                TryLightCityFire(point.Key, p.Item1, effect, new Point3d(p.Item2, p.Item3, ground.Value));
        }
    }
#endif

    private void ObserveCityLights()
    {
        foreach (var item in cityLights)
        {
            CityLight city = item.Value;
            if (city.RenderPositionLogged || particle.GetValue(city.Owner) == null)
                continue;
            var rendered = new Point3d();
            city.Light.getPos(ref rendered);
            double dx = rendered.x - city.Anchor.x, dy = rendered.y - city.Anchor.y;
            if (dx * dx + dy * dy > 4)
                continue;
            city.RenderPositionLogged = true;
            Note(String.Format(Invariant, "city_light_render_pos {0} {1:F6} {2:F1} {3:F1} {4:F1}",
                item.Key, Now, rendered.x, rendered.y, rendered.z));
        }
    }

    private void EndCityLight(string id)
    {
        CityLight city;
        if (!cityLights.TryGetValue(id, out city))
            return;
        // Smoke may still fade after the flame has gone out.
        if (particle.GetValue(city.Owner) != null)
            setOwnedEmission.Invoke(city.Light, new object[] { 0f, 0f });
        cityLights.Remove(id);
        Note(String.Format(Invariant, "city_light_off {0} {1:F6}", id, Now));
    }
}

public partial class Mission
{
    // These are the named emitters in BuildingFireBig.eff on the inspected Steam build.
    private static readonly string[] SmokeSections = { "SmokeBalls", "Smoke0", "Smoke3", "Smoke4" };
    private static readonly string[] FlameSections = { "FireStat", "FireBallStat", "FireFar" };
    private static readonly float[] NoEmission = { 0f };

    private void SeparateCityEffect(object effect, bool smokeOnly)
    {
        try
        {
            var emitter = (WEff3D)particle.GetValue(effect);
            foreach (string section in smokeOnly ? FlameSections : SmokeSections)
                emitter.changeParam(section, EffectParameterName.ParticlesPerSec, NoEmission);
        }
        catch
        {
            finishEffect.Invoke(null, new[] { effect });
            throw;
        }
    }
}

public partial class Mission
{
    private const string LightCarrier = "$core/3do/sfx/smoke/ChimneyBlack.eff";

    private void RemoveDistrictLight(string id)
    {
        object owner = cityLights[id].Owner;
        EndCityLight(id);
        if (particle.GetValue(owner) != null)
            finishEffect.Invoke(null, new[] { owner });
    }

    private void ReconcileDistrictLights(Dictionary<string, Tuple<int, double, double>> desired)
    {
        bool clear = fireNightFactor <= 0 || stopped || Now - receivedAt > 15;
        foreach (string id in new List<string>(cityLights.Keys))
        {
            CityLight light = cityLights[id];
            if (!clear && (desired.ContainsKey(id) || light.Strength > 0.025)
                && particle.GetValue(light.Owner) != null)
                continue;
            RemoveDistrictLight(id);
        }

        foreach (string id in new List<string>(desired.Keys))
        {
            if (!id.Contains("_P3_"))
                continue;
            var position = desired[id];
            desired.Remove(id);
            if (clear || cityLightFailed || cityLights.ContainsKey(id) || cityLights.Count >= CityLightBudget)
                continue;
            double? z = CaptureTerrainHeight(position.Item2, position.Item3);
            if (!z.HasValue)
                continue;
            var loc = new Loc(position.Item2, position.Item3, z.Value, 0, 0, 0);
            object owner = createEffect.Invoke(null, new object[] { loc, 1f, LightCarrier, -1.0, true });
            if (owner == null)
                throw new InvalidOperationException("District light carrier could not be created.");
            try
            {
                var emitter = (WEff3D)particle.GetValue(owner);
                if (emitter == null)
                    throw new InvalidOperationException("District light carrier has no draw effect.");
                emitter.changeParam("Smoke0", EffectParameterName.ParticlesPerSec, NoEmission);
                emitter.changeParam("Smoke1", EffectParameterName.ParticlesPerSec, NoEmission);
                TryLightCityFire(id, position.Item1, owner, new Point3d(position.Item2, position.Item3, z.Value));
            }
            finally
            {
                if (!cityLights.ContainsKey(id))
                    finishEffect.Invoke(null, new[] { owner });
            }
        }
    }
}

public partial class Mission
{
    private bool raidCameraAttempted;

    private void SelectRaidCamera(double now)
    {
        if (raidCameraAttempted || now < 12 || GamePlay.gpPlayer() == null)
            return;
        raidCameraAttempted = true;
        try
        {
            Assembly engine = Assembly.Load("maddox");
            if (engine.ManifestModule.ModuleVersionId != new Guid("8e7a2ac5-43e4-45fc-8ef5-f4e3d36baff3"))
                throw new InvalidOperationException("London camera requires the inspected Steam build.");

            const BindingFlags members = BindingFlags.Public | BindingFlags.NonPublic;
            Type actorType = engine.GetType("B3ik9i8vEcErjO61EnV5pr8xSg_fKyjgLBB2LLZAsCag", true);
            Type cameraType = engine.GetType("4UhbWdQ2FZoEglRk6kTMTcM6ThpsX7qpD8e3a$W1QrhN", true);
            Type registry = engine.GetType("IN9ja8czYVm8g9Yda3jVhIdZoiD0Iurfl52UO1fGq$WF", true);
            Type view = engine.GetType("fJOaaT0jQJ73cJ6fixjcwm1WB3rBeWFDeVuRzOZRBA2w", true);
            MethodInfo getWorld = registry.GetMethod("ogBa7X8tof8PQ7kD5doXYAg", members | BindingFlags.Static,
                null, Type.EmptyTypes, null);
            FieldInfo byName = getWorld.ReturnType.GetField("HNE0cqGJqxveych4msrLm1E", members | BindingFlags.Instance);
            MethodInfo find = byName.FieldType.GetMethod("QnL8ABDdA9vjIiTAX7$v3Z8", members | BindingFlags.Instance,
                null, new[] { typeof(object) }, null);
            MethodInfo select = view.GetMethod("l0fU4X9NAqoCahbXbk$LwbE", members | BindingFlags.Static,
                null, new[] { actorType }, null);
            if (!actorType.IsAssignableFrom(cameraType) || find.ReturnType != typeof(object) || select.ReturnType != typeof(void))
                throw new MissingMemberException("Unexpected London camera selector.");

            object namedActors = byName.GetValue(getWorld.Invoke(null, null));
            foreach (string name in new[] { "0:StaticCamera_0", "1:StaticCamera_0", "StaticCamera_0" })
            {
                object actor = find.Invoke(namedActors, new object[] { name });
                if (!cameraType.IsInstanceOfType(actor))
                    continue;
                select.Invoke(null, new[] { actor });
                Note("raid_camera_selected " + name);
                return;
            }
            Note("raid_camera_missing");
        }
        catch (Exception error)
        {
            Note("raid_camera_error " + error.GetBaseException().Message);
        }
    }
}

public partial class Mission
{
    private const string WarmSmokeFolder = "$user/GroundFireEffects/";
    private static readonly string[] WarmSmokeAssets = {
        WarmSmokeFolder + "WarmSmokePlumeLower.eff",
        WarmSmokeFolder + "WarmSmokePlumeMiddle.eff",
        WarmSmokeFolder + "WarmSmokePlumeUpper.eff"
    };
    private static readonly float[] StockLowerSmokeRate = { 2f };
    private readonly Dictionary<string, WarmPlume> warmSmoke = new Dictionary<string, WarmPlume>();
    private bool warmSmokeFailed;
    private bool warmSmokeAssetsChecked;
    private bool warmSmokeHeld;
    private bool warmSmokeFixtureStarted;
    private string lastWarmSmokeCommand;

    private sealed class WarmPlume
    {
        public readonly object[] Owners = new object[WarmSmokeAssets.Length];
        public Loc Origin;
        public double Glow;
        public double UpdatedAt;
        public double LastLoggedAt;
    }

    private void ReconcileWarmSmoke(Dictionary<string, Tuple<int, double, double>> desired, float smokeScale)
    {
        if (warmSmokeFailed || fireNightFactor <= 0)
            return;
        try
        {
            var flames = new List<KeyValuePair<string, Tuple<int, double, double>>>();
            foreach (var point in desired)
                if (point.Key.Contains("_P1_") || point.Key.Contains("_P4_"))
                    flames.Add(point);

            var plumeHeat = new Dictionary<string, double>();
            foreach (var point in desired)
            {
                if (!point.Key.Contains("_P2_") || !effects.ContainsKey(point.Key))
                    continue;
                double heat = 0;
                foreach (var flame in flames)
                {
                    double dx = point.Value.Item2 - flame.Value.Item2;
                    double dy = point.Value.Item3 - flame.Value.Item3;
                    double strength;
                    if (cityLightStrength.TryGetValue(flame.Key, out strength))
                        heat = Math.Max(heat, strength * (1 - (dx * dx + dy * dy) / (145 * 145)));
                }
                plumeHeat.Add(point.Key, Math.Max(0, (heat - 0.08) / 0.92));
            }

            foreach (string id in new List<string>(warmSmoke.Keys))
            {
                if (plumeHeat.ContainsKey(id))
                    continue;
                FinishWarmPlume(id);
            }

            double now = Now;
            foreach (var source in plumeHeat)
            {
                WarmPlume plume;
                if (!warmSmoke.TryGetValue(source.Key, out plume))
                {
                    if (source.Value == 0)
                        continue;
                    var point = desired[source.Key];
                    double? ground = CaptureTerrainHeight(point.Item2, point.Item3);
                    if (!ground.HasValue)
                        continue;
                    if (!warmSmokeAssetsChecked)
                    {
                        foreach (string asset in WarmSmokeAssets)
                            CheckSmokeAsset(asset);
                        CheckSmokeAsset(WarmSmokeFolder + "WarmSmokePlume.mma");
                        CheckSmokeAsset(WarmSmokeFolder + "Smoke_Sprites_Air_W.dds");
                        warmSmokeAssetsChecked = true;
                    }
                    // Start just above the low London roofs so the smoke reads from street fires.
                    plume = new WarmPlume {
                        Origin = new Loc(point.Item2, point.Item3, ground.Value + 12, 0, 0, 0),
                        UpdatedAt = now, LastLoggedAt = now - 5
                    };
                    warmSmoke.Add(source.Key, plume);
                    Note(String.Format(Invariant, "warm_smoke_on {0} {1:F6} {2:F3} {3:F3}",
                        source.Key, now, point.Item2, point.Item3));
                }

                double elapsed = Math.Max(0, now - plume.UpdatedAt);
                double responseTime = source.Value > plume.Glow ? 8 : 11;
                plume.Glow += (source.Value - plume.Glow) * (1 - Math.Exp(-elapsed / responseTime));
                plume.UpdatedAt = now;
                if (source.Value == 0 && plume.Glow < 0.01)
                {
                    FinishWarmPlume(source.Key);
                    continue;
                }

                double brightness = fireNightFactor * Math.Pow(plume.Glow, 1.35);
                BlendWarmSmoke(plume, smokeScale, brightness);
                SetLowerSmokeRate(source.Key, new[] { (float)(StockLowerSmokeRate[0] * (1 - brightness)) });
                if (now - plume.LastLoggedAt >= 4)
                {
                    Note(String.Format(Invariant, "warm_smoke_ramp {0} {1:F2} {2:F3} {3:F3} {4:F3}",
                        source.Key, now, source.Value, plume.Glow, brightness));
                    plume.LastLoggedAt = now;
                }
            }
        }
        catch (Exception error)
        {
            warmSmokeFailed = true;
            Note("warm_smoke_error " + error.GetBaseException().Message);
        }
    }

    private void FinishWarmPlume(string id)
    {
        foreach (object owner in warmSmoke[id].Owners)
        {
            var emitter = owner == null ? null : (WEff3D)particle.GetValue(owner);
            if (emitter == null)
                continue;
            if (fireNightFactor <= 0)
            {
                emitter.setIntesity(0);
                if (emitter.isPaused())
                    emitter.pause(false);
            }
            finishEffect.Invoke(null, new[] { owner });
        }
        warmSmoke.Remove(id);
        SetLowerSmokeRate(id, StockLowerSmokeRate);
        Note("warm_smoke_off " + id);
    }

    private static void CheckSmokeAsset(string asset)
    {
        long handle = maddox.rts.WSFS.open(asset, 0);
        if (handle < 0)
            throw new FileNotFoundException("Missing firelit smoke dependency " + asset);
        maddox.rts.WSFS.close(handle);
    }

    private void BlendWarmSmoke(WarmPlume plume, float smokeScale, double brightness)
    {
        // At most two profiles emit at once. Higher profiles keep their colour later into the same ascent.
        double reach = plume.Glow * (WarmSmokeAssets.Length - 1);
        for (int i = 0; i < WarmSmokeAssets.Length; i++)
        {
            float amount = (float)(brightness * Math.Max(0, 1 - Math.Abs(reach - i)));
            object owner = plume.Owners[i];
            var emitter = owner == null ? null : (WEff3D)particle.GetValue(owner);
            if (emitter == null)
            {
                if (amount < 0.005f)
                    continue;
                string asset = WarmSmokeAssets[i];
                owner = createEffect.Invoke(null, new object[] { plume.Origin, smokeScale, asset, -1.0, true });
                emitter = owner == null ? null : (WEff3D)particle.GetValue(owner);
                if (emitter == null)
                    throw new InvalidOperationException("The profile smoke effect did not create a particle system.");
                plume.Owners[i] = owner;
                Note("warm_smoke_asset " + asset);
            }
            emitter.setIntesity(amount);
        }
    }

    private void SetLowerSmokeRate(string id, float[] rate)
    {
        object owner;
        if (effects.TryGetValue(id, out owner))
        {
            var emitter = (WEff3D)particle.GetValue(owner);
            if (emitter != null)
                emitter.changeParam("Smoke0", EffectParameterName.ParticlesPerSec, rate);
        }
    }

    private readonly Dictionary<WEff3D, float> warmSmokeProbeStrength = new Dictionary<WEff3D, float>();
    private readonly List<WEff3D> pausedProbeEffects = new List<WEff3D>();

    private void CheckWarmSmoke(double now)
    {
        string path = Path.Combine(Folder, session + ".smoke.txt");
        if (!File.Exists(path) || warmSmokeFailed)
            return;
        string line = File.ReadAllText(path).Trim();
        if (line.Length > 64 || line == lastWarmSmokeCommand)
            return;
        string[] request = line.Split(' ');
        long serial;
        if (request.Length != 2 || !Int64.TryParse(request[0], out serial))
            return;
        string command = request[1];
        if (command == "seed")
        {
            lastWarmSmokeCommand = line;
            if (!warmSmokeFixtureStarted)
            {
                warmSmokeFixtureStarted = true;
                foreach (var point in new[] {
                    Tuple.Create(149530, 274674), Tuple.Create(149550, 274674), Tuple.Create(149550, 274654),
                    Tuple.Create(149110, 274274), Tuple.Create(149130, 274274), Tuple.Create(149130, 274254),
                    Tuple.Create(149750, 274194), Tuple.Create(149770, 274194), Tuple.Create(149770, 274174)
                })
                    Record(String.Format(Invariant, "ignition\t{0}\t{1}", point.Item1, point.Item2));
                Note("warm_smoke_fixture_started");
            }
            return;
        }
        if (command != "hold-on" && command != "hold-off" && command != "resume")
            return;
        lastWarmSmokeCommand = line;
        if (command == "resume")
        {
            foreach (var emitter in pausedProbeEffects)
                emitter.pause(false);
            pausedProbeEffects.Clear();
            warmSmokeHeld = false;
            warmSmokeProbeStrength.Clear();
        }
        else if (warmSmokeHeld || warmSmoke.Count != 0)
        {
            if (!warmSmokeHeld)
            {
                // Hold the stock flames and dark smoke at the same instant for the image comparison.
                foreach (object owner in effects.Values)
                {
                    var emitter = (WEff3D)particle.GetValue(owner);
                    if (emitter != null && !emitter.isPaused())
                    {
                        emitter.pause(true);
                        pausedProbeEffects.Add(emitter);
                    }
                }
                foreach (var plume in warmSmoke.Values)
                {
                    foreach (object owner in plume.Owners)
                    {
                        var emitter = owner == null ? null : (WEff3D)particle.GetValue(owner);
                        if (emitter != null)
                            warmSmokeProbeStrength.Add(emitter, emitter.getIntesity());
                    }
                }
                warmSmokeHeld = true;
            }
            foreach (var point in warmSmokeProbeStrength)
                point.Key.setIntesity(command == "hold-on" ? point.Value : 0f);
        }
        double utc = (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        Note(String.Format(Invariant, "warm_smoke_probe {0} {1} {2:F6} {3:F6}",
            command, warmSmoke.Count, now, utc));
    }
}

public partial class Mission
{
    private const int IgnitionBudget = 8;
    private const double IgnitionSpacing = 250;
    private readonly List<Point3d> sampledImpacts = new List<Point3d>();
    private readonly Dictionary<string, int> flameBands = new Dictionary<string, int>();
    private static readonly float[] FlameScales = { 2.6f, 4.1f, 5.7f, 7f };
    private static readonly double[] FlameThresholds = { 0.30, 0.58, 0.82 };

    private bool SampleRaidImpact(Point3d impact)
    {
        if (sampledImpacts.Count >= IgnitionBudget)
            return false;

        foreach (Point3d previous in sampledImpacts)
        {
            double x = impact.x - previous.x;
            double y = impact.y - previous.y;
            if (x * x + y * y < IgnitionSpacing * IgnitionSpacing)
                return false;
        }
        sampledImpacts.Add(impact);
        return true;
    }

    private int FlameBand(string id, out double strength)
    {
        cityLightStrength.TryGetValue(id, out strength);
        int current;
        bool hasPrevious = flameBands.TryGetValue(id, out current);
        int band = 0;
        while (band < FlameThresholds.Length)
        {
            // Keep the current size through small fluctuations at a boundary.
            double margin = !hasPrevious ? 0 : band < current ? -0.035 : 0.035;
            if (strength < FlameThresholds[band] + margin)
                break;
            band++;
        }
        return band;
    }
}

public partial class Mission
{
    private const string CityPumpGroup = "0_Chief";
    private static readonly Point2d[][] CityRoutes = {
        new[] { new Point2d(149255.00, 274132.00), new Point2d(149331.00, 274156.00) },
        new[] { new Point2d(149945.00, 274715.00), new Point2d(149915.00, 274690.00) },
        new[] { new Point2d(149756.00, 273712.00), new Point2d(149799.00, 273786.00) },
        new[] { new Point2d(149910.00, 273640.00), new Point2d(149950.00, 273765.00) },
    };

    private sealed class CityPumpRun
    {
        public int Mission = -1;
        public Point3d? LastPosition;
        public int StillSamples;
        public bool Missing;
    }

    private readonly CityPumpRun[] cityPumps = Array.ConvertAll(CityRoutes, route => new CityPumpRun());
    private double cityAlarmAt = -1;
    private double cityCrewPollAt;

    private void DispatchCityPump(int index, Point2d[] route, CityPumpRun pump)
    {
        ISectionFile section = GamePlay.gpCreateSectionFile();
        section.add("MAIN", "MAP", "Land$English_Channel_1940");
        section.add("Chiefs", CityPumpGroup, "Vehicle.Austin_K2_ATV gb");
        string road = CityPumpGroup + "_Road";
        for (int i = 0; i < route.Length; ++i)
        {
            Point2d p = route[i];
            string parameters = i == 0
                ? String.Format(Invariant, "{0:F2} 7.00 0 {1} 6.11", p.y, route.Length)
                : String.Format(Invariant, "{0:F2} 7.00", p.y);
            section.add(road, p.x.ToString("F2", Invariant), parameters);
        }
        pump.Mission = GamePlay.gpNextMissionNumber();
        GamePlay.gpPostMissionLoad(section);
        Point2d staging = route[route.Length - 1];
        Record(String.Format(Invariant, "city_crew_dispatch\t{0}\t{1:R}\t{2:R}", index + 1, staging.x, staging.y));
        Note(String.Format(Invariant, "city_crew_dispatched {0} {1:F6} {2}", index + 1, Now, pump.Mission));
    }

    private void ObserveCityCrews(double now)
    {
        if (cityAlarmAt < 0 && effects.Count > 0)
            cityAlarmAt = now;
        if (cityAlarmAt < 0 || now < cityCrewPollAt)
            return;
        cityCrewPollAt = now + 1.0;
        for (int i = 0; i < cityPumps.Length; ++i)
        {
            CityPumpRun pump = cityPumps[i];
            if (pump.Mission < 0)
            {
                if (now >= cityAlarmAt + 20 + 12 * i)
                    DispatchCityPump(i, CityRoutes[i], pump);
                continue;
            }
            string groupName = pump.Mission.ToString(Invariant) + ":" + CityPumpGroup;
            AiGroundGroup group = GamePlay.gpActorByName(groupName) as AiGroundGroup;
            AiActor[] actors = group != null && group.IsValid() ? group.GetItems() : null;
            AiGroundActor vehicle = null;
            if (actors != null)
            {
                foreach (AiActor actor in actors)
                {
                    var candidate = actor as AiGroundActor;
                    if (candidate != null && candidate.IsValid() && candidate.IsAlive() &&
                        (candidate.InternalTypeName() ?? "").IndexOf("Austin_K2_ATV", StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        vehicle = candidate;
                        break;
                    }
                }
            }
            if (vehicle == null)
            {
                if (pump.LastPosition.HasValue && !pump.Missing)
                    Record(String.Format(Invariant, "city_crew_lost\t{0}", i + 1));
                pump.LastPosition = null;
                pump.StillSamples = 0;
                pump.Missing = true;
                continue;
            }
            if (!pump.LastPosition.HasValue)
                Note(String.Format(Invariant, "city_crew_pump {0} {1:F6} {2} {3}", i + 1, Now,
                    vehicle.Name(), vehicle.InternalTypeName()));
            pump.Missing = false;
            Point3d p = vehicle.Pos();
            pump.StillSamples = pump.LastPosition.HasValue &&
                Math.Abs(p.x - pump.LastPosition.Value.x) <= 0.5 &&
                Math.Abs(p.y - pump.LastPosition.Value.y) <= 0.5 ? pump.StillSamples + 1 : 0;
            pump.LastPosition = p;
            bool stopped = vehicle.IsTaskComplete() || pump.StillSamples >= 3;
            Record(String.Format(Invariant, "city_crew_position\t{0}\t{1:R}\t{2:R}\t{3}",
                i + 1, p.x, p.y, stopped ? 1 : 0));
        }
    }
}

public partial class Mission
{
    private static readonly DateTime FireLightingDate = new DateTime(1940, 7, 15);
    private const double FireLightingStart = 22.333334;
    private const double FireLightingLatitude = 51.5, FireLightingLongitude = 0, FireLightingUtcOffset = 0;
    private double fireNightFactor;

    private void RefreshFireLighting(double now)
    {
        int days = (int)Math.Floor((FireLightingStart + Math.Max(0, now) / 3600) / 24);
        double previous = fireNightFactor;
        fireNightFactor = FireSunlight.NightFactor(FireLightingDate.AddDays(days), GamePlay.gpTimeofDay(),
            FireLightingLatitude, FireLightingLongitude, FireLightingUtcOffset);
        if ((previous > 0) != (fireNightFactor > 0))
            Note(String.Format(Invariant, "fire_night_visuals {0} {1:F6}", fireNightFactor > 0 ? "on" : "off", now));
        if (fireNightFactor > 0)
            return;

#if LONDON_DISTRICT_LIGHTS
        foreach (string id in new List<string>(cityLights.Keys))
            RemoveDistrictLight(id);
#else
        if (previous > 0)
            foreach (CityLight light in cityLights.Values)
                if (particle.GetValue(light.Owner) != null)
                    setOwnedEmission.Invoke(light.Light, new object[] { 0f, 0f });
#endif
#if LONDON_WARM_SMOKE
        foreach (string id in new List<string>(warmSmoke.Keys))
            FinishWarmPlume(id);
#endif
    }
}

// Solar approximation from NOAA's General Solar Position Calculations.
internal static class FireSunlight
{
    private const double Radians = Math.PI / 180;
    private const double SunsetElevation = -0.833;
    private const double FullGlowElevation = -4.0;

    public static double NightFactor(DateTime date, double hour, double latitude,
                                     double longitude, double utcOffset)
    {
        if (Double.IsNaN(hour) || Double.IsInfinity(hour) || hour < 0 || hour >= 24)
            return 0;

        double year = 2 * Math.PI / (DateTime.IsLeapYear(date.Year) ? 366 : 365)
            * (date.DayOfYear - 1 + (hour - 12) / 24);
        double sin = Math.Sin(year), cos = Math.Cos(year);
        double sin2 = Math.Sin(2 * year), cos2 = Math.Cos(2 * year);
        double equation = 229.18 * (0.000075 + 0.001868 * cos - 0.032077 * sin
            - 0.014615 * cos2 - 0.040849 * sin2);
        double declination = 0.006918 - 0.399912 * cos + 0.070257 * sin
            - 0.006758 * cos2 + 0.000907 * sin2
            - 0.002697 * Math.Cos(3 * year) + 0.00148 * Math.Sin(3 * year);
        double angle = (15 * (hour - utcOffset) + longitude + equation / 4 - 180) * Radians;
        double lat = latitude * Radians;
        double sinElevation = Math.Sin(lat) * Math.Sin(declination)
            + Math.Cos(lat) * Math.Cos(declination) * Math.Cos(angle);
        double elevation = Math.Asin(Math.Max(-1, Math.Min(1, sinElevation))) / Radians;
        double fade = (SunsetElevation - elevation) / (SunsetElevation - FullGlowElevation);
        return Math.Max(0, Math.Min(1, fade));
    }
}
