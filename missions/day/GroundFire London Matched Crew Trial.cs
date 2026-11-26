#define LONDON_CREW_CAMERA
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
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GroundFireHawkinge", "lab-town-20m-149120-274144-3200m-grass-0p5-front-pulse-split-dense-l24");
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
            Player player = GamePlay.gpPlayer();
            if (menuPlayer == null)
                InstallMenu(player);
            GroundHeight(0);
            SampleMissionWind();
            ApplyImpactFixture(now);
            Record("clock\t" + GamePlay.gpTimeofDay().ToString("R", Invariant) + "\t" + (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds.ToString("F6", Invariant));
            SelectRaidCamera(now);
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
            }
        }
        foreach (var item in desired)
        {
            if (effects.ContainsKey(item.Key) || effects.Count + fading.Count >= TotalEffectBudget)
                continue;
            double? z = item.Value.Item1 == 3 ? CaptureTerrainHeight(item.Value.Item2, item.Value.Item3)
                                              : GroundHeight(item.Value.Item1);
            if (!z.HasValue)
                continue;
            double height = z.Value + (item.Key.Contains("_P4_") ? 5.5 : 0);
            var loc = new Loc(item.Value.Item2, item.Value.Item3, height, 0, 0, 0);
            bool smokeOnly = item.Key.Contains("_P2_");
            object effect = createEffect.Invoke(null, new object[] { loc, smokeOnly ? 4f : 7f, Asset, -1.0, true });
            if (effect == null || particle.GetValue(effect) == null)
                throw new InvalidOperationException("Ground fire factory returned no emitter.");
            SeparateCityEffect(effect, smokeOnly);
            effects.Add(item.Key, effect);
            Note(String.Format(Invariant, "plume_created {0} {1:F6} {2:F3} {3:F3}",
                               item.Key, Now, item.Value.Item2, item.Value.Item3));
        }
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

    private void Record(string command) { RecordAt(Now, command); }

    private void RecordAt(double stamp, string command)
    {
        string line = String.Format(Invariant, "{0}\t{1:F6}\t{2}\n", sequence + 1, stamp, command);
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
        green = (float)(0.18 + 0.36 * colorHeat);
        var color = new Tuple3f(1f, green, (float)(0.045 + 0.18 * colorHeat));
        light.setColor(ref color);
        setOwnedEmission.Invoke(light, new object[] { intensity, CityLightRadius });
    }

    private void PulseCityLights()
    {
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
        if (cityLightFailed || Plots[plot] != "town" || cityLights.Count >= CityLightBudget)
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
            setOwnedEmission.Invoke(light, new object[] { CityLightIntensity, CityLightRadius });
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
        bool clear = stopped || Now - receivedAt > 15;
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

    private static MethodInfo BindRaidView(out Type actorType)
    {
        Assembly engine = Assembly.Load("maddox");
        if (engine.ManifestModule.ModuleVersionId != new Guid("8e7a2ac5-43e4-45fc-8ef5-f4e3d36baff3"))
            throw new InvalidOperationException("London camera requires the inspected Steam build.");

        actorType = engine.GetType("B3ik9i8vEcErjO61EnV5pr8xSg_fKyjgLBB2LLZAsCag", true);
        Type view = engine.GetType("fJOaaT0jQJ73cJ6fixjcwm1WB3rBeWFDeVuRzOZRBA2w", true);
        MethodInfo select = view.GetMethod("l0fU4X9NAqoCahbXbk$LwbE", BindingFlags.Public | BindingFlags.Static,
            null, new[] { actorType }, null);
        if (select == null || select.ReturnType != typeof(void))
            throw new MissingMethodException("Unexpected external view selector.");
        return select;
    }

    private static MethodInfo BindRaidActors(Assembly engine, out object namedActors)
    {
        const BindingFlags members = BindingFlags.Public | BindingFlags.NonPublic;
        Type registry = engine.GetType("IN9ja8czYVm8g9Yda3jVhIdZoiD0Iurfl52UO1fGq$WF", true);
        MethodInfo getWorld = registry.GetMethod("ogBa7X8tof8PQ7kD5doXYAg", members | BindingFlags.Static,
            null, Type.EmptyTypes, null);
        FieldInfo byName = getWorld.ReturnType.GetField("HNE0cqGJqxveych4msrLm1E", members | BindingFlags.Instance);
        MethodInfo find = byName.FieldType.GetMethod("QnL8ABDdA9vjIiTAX7$v3Z8", members | BindingFlags.Instance,
            null, new[] { typeof(object) }, null);
        if (find == null || find.ReturnType != typeof(object))
            throw new MissingMethodException("Unexpected actor lookup.");
        namedActors = byName.GetValue(getWorld.Invoke(null, null));
        return find;
    }

    private void SelectRaidCamera(double now)
    {
        if (raidCameraAttempted || now < 12 || GamePlay.gpPlayer() == null)
            return;
        raidCameraAttempted = true;
        try
        {
            Type actorType;
            MethodInfo select = BindRaidView(out actorType);
            Assembly engine = actorType.Assembly;
            Type cameraType = engine.GetType("4UhbWdQ2FZoEglRk6kTMTcM6ThpsX7qpD8e3a$W1QrhN", true);
            if (!actorType.IsAssignableFrom(cameraType))
                throw new MissingMemberException("Unexpected London camera selector.");

            object namedActors;
            MethodInfo find = BindRaidActors(engine, out namedActors);
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

#if LONDON_CREW_CAMERA
    private bool crewCameraAttempted;

    private void FollowCityCrew(int number, AiGroundActor vehicle)
    {
        if (number != 1 || crewCameraAttempted || GamePlay.gpPlayer() == null)
            return;

        crewCameraAttempted = true;
        try
        {
            Type actorType;
            MethodInfo select = BindRaidView(out actorType);
            string name = vehicle.Name();
            object namedActors;
            MethodInfo find = BindRaidActors(actorType.Assembly, out namedActors);
            object actor = find.Invoke(namedActors, new object[] { name });
            if (!actorType.IsInstanceOfType(actor))
                throw new InvalidOperationException("No external-view actor for " + name + " (" + vehicle.GetType().FullName + ").");
            select.Invoke(null, new[] { actor });
            Note(String.Format(Invariant, "city_crew_camera {0} {1:F6} {2}", number, Now, name));
        }
        catch (Exception error)
        {
            Note("city_crew_camera_error " + error.GetBaseException().Message);
        }
    }
#endif

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
        if (cityAlarmAt < 0 && nextFixtureImpact != 0)
            cityAlarmAt = FixedImpacts[0].Time;
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
#if LONDON_CREW_CAMERA
            FollowCityCrew(i + 1, vehicle);
#endif
            pump.Missing = false;
            Point3d p = vehicle.Pos();
            pump.StillSamples = pump.LastPosition.HasValue &&
                Math.Abs(p.x - pump.LastPosition.Value.x) <= 0.5 &&
                Math.Abs(p.y - pump.LastPosition.Value.y) <= 0.5 ? pump.StillSamples + 1 : 0;
            pump.LastPosition = p;
            ObserveTrialPose(i + 1, vehicle, p, now);
            bool stopped = vehicle.IsTaskComplete() || pump.StillSamples >= 3;
            Record(String.Format(Invariant, "city_crew_position\t{0}\t{1:R}\t{2:R}\t{3}",
                i + 1, p.x, p.y, stopped ? 1 : 0));
        }
    }
}

public partial class Mission
{
    private sealed class Impact
    {
        public readonly double Time, East, North;
        public readonly string Type;
        public Impact(double time, string type, double east, double north)
        {
            Time = time;
            Type = type;
            East = east;
            North = north;
        }
    }

    private static readonly Impact[] FixedImpacts = {
        new Impact(20.010000, "SC50", 149430.16709626088, 274115.16207752132),
        new Impact(20.520000, "SC50", 149384.29667539516, 272699.30826603674),
        new Impact(20.670000, "SC50", 149415.77538199583, 273781.49305774324),
        new Impact(20.730000, "SC50", 149623.02247258264, 273843.18598429865),
        new Impact(20.760000, "SC50", 149423.02201975376, 274144.08106170333),
        new Impact(20.820000, "SC50", 149492.655000578, 273899.08142172487),
        new Impact(21.000000, "SC50", 149861.01006814468, 274051.10399831628),
        new Impact(21.120000, "SC50", 149604.70648079662, 273923.11155964277),
        new Impact(21.210000, "SC50", 149420.78419497062, 274162.94002001674),
        new Impact(21.270000, "SC50", 149897.86564081456, 273902.55943710462),
        new Impact(21.330000, "SC50", 149367.91654210625, 272786.91509510914),
        new Impact(21.450000, "SC50", 149788.69276025271, 273876.64666922926),
        new Impact(21.540000, "SC50", 149385.51190035435, 273908.077809078),
        new Impact(21.660000, "SC50", 149855.46733831009, 273603.84918239166),
        new Impact(21.720000, "SC50", 149604.28261726905, 273941.77863448655),
        new Impact(21.840000, "SC50", 149945.34704151453, 273727.70227025752),
        new Impact(21.900000, "SC50", 149365.01846212006, 272826.1145234257),
        new Impact(21.930000, "SC50", 149412.99714932483, 274204.3250858775),
        new Impact(21.960000, "SC50", 149434.09609221155, 273734.39253206615),
        new Impact(21.960000, "SC50", 149842.3483485443, 273664.01116132911),
        new Impact(22.140000, "SC50", 149416.6066568066, 272617.00112468994),
        new Impact(22.140000, "SC50", 149855.72016233735, 274129.05536201049),
        new Impact(22.230000, "SC50", 149350.10097162321, 274029.69719566678),
        new Impact(22.500000, "SC50", 149573.26064770814, 274076.53446191334),
        new Impact(22.620000, "SC50", 149780.04882652126, 273946.54911701934),
        new Impact(22.770000, "SC50", 149519.49940782308, 274264.84723739029),
        new Impact(22.890000, "SC50", 149378.45593810681, 272807.83115371165),
        new Impact(22.890000, "SC50", 149333.04377332376, 273003.39522180706),
        new Impact(22.950000, "SC50", 149408.21175354565, 273827.63114698528),
        new Impact(22.950000, "SC50", 149860.84650081806, 274118.87288070034),
        new Impact(22.950000, "SC50", 149763.30940755008, 274018.95653415564),
        new Impact(23.130000, "SC50", 149830.21957992596, 273757.67637487844),
        new Impact(23.160000, "SC50", 149623.65020087731, 273886.06684203079),
        new Impact(23.160000, "SC50", 149915.06004119245, 273894.28641974251),
        new Impact(23.370000, "SC50", 149373.03299672171, 272855.413173658),
        new Impact(23.400000, "SC50", 149819.31347285814, 274309.08466696349),
        new Impact(23.460000, "SC50", 149330.61938490259, 274090.946532423),
        new Impact(23.520000, "SC50", 149582.22667742535, 274056.9411794449),
        new Impact(23.790000, "SC50", 149373.28070695506, 273952.70344320778),
        new Impact(23.790000, "SC50", 149265.82320767868, 274289.20714941871),
        new Impact(23.820000, "SC50", 149342.53974713545, 273004.043577784),
        new Impact(23.820000, "SC50", 149805.96640302474, 274373.95384820661),
        new Impact(24.030000, "SC50", 149538.03858880629, 274201.52262182749),
        new Impact(24.210000, "SC50", 149791.13646560218, 274434.36516641313),
        new Impact(24.270000, "SC50", 149467.46626838078, 274042.20170701592),
        new Impact(24.300000, "SC50", 149437.01692359039, 274147.08876475284),
        new Impact(24.300000, "SC50", 149334.9318183428, 273051.789541011),
        new Impact(24.420000, "SC50", 149881.23375385336, 274077.30228951888),
        new Impact(24.450000, "SC50", 149219.34296861623, 274437.6805576898),
        new Impact(24.540000, "SC50", 149296.87035771168, 273246.22954247193),
        new Impact(24.660000, "SC50", 149801.83236872204, 273916.97712936491),
        new Impact(24.810000, "SC50", 149425.87640208317, 274186.33404161345),
        new Impact(24.840000, "SC50", 149341.4698425883, 274051.98661339947),
        new Impact(25.140000, "SC50", 149404.561022312, 274266.06391051767),
        new Impact(25.140000, "SC50", 149284.53333450702, 274231.97122288769),
        new Impact(25.200000, "SC50", 149794.6145035997, 273962.88482188457),
        new Impact(25.200000, "SC50", 149766.44981271619, 274072.20060721732),
        new Impact(25.290000, "SC50", 149545.90993879872, 274175.45974309294),
        new Impact(25.620000, "SC50", 149754.17183477883, 274120.83022347424),
        new Impact(25.650000, "SC50", 149327.67852570856, 274551.02453999216),
        new Impact(25.740000, "SC50", 149783.52622019316, 274474.71340540878),
        new Impact(25.830000, "SC50", 149359.09222211357, 272992.49532948784),
        new Impact(25.890000, "SC50", 149542.66272723227, 274194.88698106218),
        new Impact(25.890000, "SC50", 149507.68432149047, 274317.45359592972),
        new Impact(25.920000, "SC50", 149818.43196538315, 274336.24707856058),
        new Impact(25.950000, "SC50", 149403.176489462, 274274.01019556826),
        new Impact(25.950000, "SC50", 149318.04772146081, 273193.89555658115),
        new Impact(26.010000, "SC50", 149244.498523787, 274368.39006163867),
        new Impact(26.130000, "SC50", 149483.64733047644, 274387.81299728667),
        new Impact(26.190000, "SC50", 149690.9074730647, 274360.88724739075),
        new Impact(26.430000, "SC50", 149670.58531562638, 274450.13958163367),
        new Impact(26.460000, "SC50", 149392.14605576542, 274318.63175052329),
        new Impact(26.490000, "SC50", 149760.462458851, 274113.37684982189),
        new Impact(26.550000, "SC50", 149744.94184805287, 274603.26035339211),
        new Impact(26.640000, "SC50", 149321.14682260333, 273217.84947565413),
        new Impact(26.670000, "SC50", 149270.77553459763, 274766.81943523529),
        new Impact(26.700000, "SC250", 149106.83163186911, 273680.25717585726),
        new Impact(26.730000, "SC50", 149307.47856891819, 274636.41219110572),
        new Impact(26.820000, "SC50", 149736.51758118704, 274208.49326923362),
        new Impact(26.910000, "SC50", 149256.50965614649, 274340.00477511494),
        new Impact(26.970000, "SC50", 149484.01482263277, 274397.3157916487),
        new Impact(26.970000, "SC50", 149190.92266805368, 274584.87544433889),
        new Impact(27.210000, "SC50", 149663.96382775498, 274468.70027917437),
        new Impact(27.270000, "SC50", 149361.9088148748, 274451.95662823028),
        new Impact(27.330000, "SC50", 149361.25871636582, 274815.89407830971),
        new Impact(27.330000, "SC250", 149119.33080406309, 273655.192551711),
        new Impact(27.480000, "SC50", 149812.92697713646, 274368.45435619669),
        new Impact(27.540000, "SC50", 149404.24391163021, 274681.39100054267),
        new Impact(27.600000, "SC50", 149328.01196508994, 273217.691030213),
        new Impact(27.600000, "SC250", 149101.89907963891, 274987.08088637289),
        new Impact(27.690000, "SC50", 149250.42090859788, 274376.14431758522),
        new Impact(27.720000, "SC50", 149474.76967108721, 274426.35848693358),
        new Impact(27.720000, "SC50", 149752.77078166508, 274573.44657316688),
        new Impact(27.720000, "SC50", 149148.78856721, 273546.50388636586),
        new Impact(27.750000, "SC50", 149616.19544713086, 274627.61684422725),
        new Impact(28.170000, "SC50", 149463.03457094857, 274469.0775637895),
        new Impact(28.170000, "SC50", 149142.85981361222, 273481.368275091),
        new Impact(28.170000, "SC50", 149154.25692391212, 274776.44150688779),
        new Impact(28.170000, "SC250", 149321.39303091675, 274945.3230941887),
        new Impact(28.290000, "SC50", 149269.83843873951, 273291.65580304444),
        new Impact(28.290000, "SC50", 149600.76852887811, 274695.88886304572),
        new Impact(28.290000, "SC250", 149103.05608842484, 275008.05034520559),
        new Impact(28.320000, "SC50", 149239.50215993702, 274884.94454927376),
        new Impact(28.410000, "SC250", 149618.85707863877, 274951.71927474439),
        new Impact(28.410000, "SC250", 149293.16194707606, 275037.558933023),
        new Impact(28.470000, "SC50", 149675.53995719893, 274423.188193876),
        new Impact(28.560000, "SC50", 149199.31698026115, 274607.24982831161),
        new Impact(28.560000, "SC250", 149181.52603569182, 275094.25660671853),
        new Impact(28.590000, "SC50", 149672.61203408119, 274807.87625044171),
        new Impact(28.680000, "SC50", 149233.40654164823, 274476.92393452174),
        new Impact(28.680000, "SC250", 149218.03923938805, 274959.13000099733),
        new Impact(28.680000, "SC250", 149549.56519402016, 274891.99432829564),
        new Impact(28.770000, "SC50", 149289.97741460626, 274703.79868419672),
        new Impact(28.860000, "SC50", 149756.15827724186, 274544.33279001218),
        new Impact(28.980000, "SC50", 149328.64787855232, 274572.21869568824),
        new Impact(28.980000, "SC250", 149589.38107091805, 274726.42241824511),
        new Impact(29.190000, "SC50", 149392.85196467084, 274710.02008961566),
        new Impact(29.520000, "SC250", 149634.48154241, 274912.84130395652),
        new Impact(29.880000, "SC50", 149760.23029731042, 274527.1420778454),
    };
    private int nextFixtureImpact;
    private readonly object[] trialLocators = new object[CityRoutes.Length];
    private readonly MethodInfo[] trialGetCurrent = new MethodInfo[CityRoutes.Length];
    private readonly bool[] trialPoseUnavailable = new bool[CityRoutes.Length];

    private void ApplyImpactFixture(double now)
    {
        while (nextFixtureImpact < FixedImpacts.Length && FixedImpacts[nextFixtureImpact].Time <= now)
        {
            Impact impact = FixedImpacts[nextFixtureImpact++];
            RecordAt(impact.Time, String.Format(Invariant, "bomb\t{0}\t{1:R}\t{2:R}",
                impact.Type, impact.East, impact.North));
        }
    }

    private void ObserveTrialPose(int number, AiGroundActor vehicle, Point3d position, double time)
    {
        int index = number - 1;
        if (trialPoseUnavailable[index])
            return;
        try
        {
            if (trialGetCurrent[index] == null)
            {
                Type actorType;
                BindRaidView(out actorType);
                object registry;
                MethodInfo find = BindRaidActors(actorType.Assembly, out registry);
                object actor = find.Invoke(registry, new object[] { vehicle.Name() });
                if (!actorType.IsInstanceOfType(actor))
                    throw new InvalidOperationException("Unresolved truck actor " + vehicle.Name());
                FieldInfo locator = actorType.GetField("sI8j0EB3mzvoEVN7_fBGXoM", BindingFlags.Instance | BindingFlags.Public);
                object transform = locator.GetValue(actor);
                MethodInfo get = transform.GetType().GetMethod("E$xjBqywRtc_fs7sz4ukMRI",
                    BindingFlags.Public | BindingFlags.Instance, null, Type.EmptyTypes, null);
                if (get == null || get.ReturnType != typeof(Loc) || get.DeclaringType == locator.FieldType ||
                    get.GetBaseDefinition().DeclaringType != locator.FieldType)
                    throw new MissingMethodException("Truck current pose getter unavailable");
                trialLocators[index] = transform;
                trialGetCurrent[index] = get;
            }

            Loc pose = (Loc)trialGetCurrent[index].Invoke(trialLocators[index], null);
            double x = pose.getX() - position.x, y = pose.getY() - position.y;
            if (x * x + y * y > 4)
                throw new InvalidOperationException("Truck pose and mission API disagree");
            Note(String.Format(Invariant, "truck_pose {0} {1:F6} {2:R} {3:R} {4:R} {5:R} {6:R} {7:R}",
                number, time, pose.getX(), pose.getY(), pose.getZ(), pose.yaw(), pose.pitch(), pose.roll()));
        }
        catch (Exception error)
        {
            trialPoseUnavailable[index] = true;
            Note("truck_pose_unavailable " + number + " " + error.GetBaseException().Message);
        }
    }
}
