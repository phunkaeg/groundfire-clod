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

public class Mission : AMission
{
    private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
    private static readonly string Folder = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GroundFireHawkinge", "lab");
    private const string Asset = "$core/3do/sfx/fire/BuildingFireSmall.eff";
    private const int PlumeBudget = 4;
    private const int TotalEffectBudget = 8;
    private const string MissionEnvironment = "__ENVIRONMENT__";
    private static readonly string[] Plots = { "forest", "field", "hedge", "town" };
    private static readonly double[,] Centers = { __CENTERS__ };
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
            double x = pos.x - Centers[0, 0], y = pos.y - Centers[0, 1];
            double? height = GroundHeight(0);
            string id = (title ?? "").ToUpperInvariant().Replace("-", "").Replace(" ", "").Replace("_", "");
            string type = Regex.IsMatch(id, "SC250(?![0-9])") ? "SC250" :
                          Regex.IsMatch(id, "SC50(?![0-9])") ? "SC50" : "";
            string fit = AircraftFit(initiator == null ? null : initiator.Actor);
            if (fit == "" && initiator != null && initiator.Player != null)
                fit = AircraftFit(initiator.Player.Place());
            if (type == "" && (id.Length == 0 || !Regex.IsMatch(id, "SC[0-9]")))
                type = fit;
            bool accepted = type != "" && (fit == "" || fit == type) &&
                            Finite(x) && Finite(y) && Finite(pos.z) && height.HasValue &&
                            x * x + y * y <= 62 * 62 && Math.Abs(pos.z - height.Value) <= 20;
            Note(String.Format(Invariant, "bomb title={0} mass_raw={1:R} x={2:R} y={3:R} z={4:R} type={5} fit={6} accepted={7}",
                               title, mass, pos.x, pos.y, pos.z, type, fit, accepted));
            if (accepted)
                Record(String.Format(Invariant, "bomb\t{0}\t{1:R}\t{2:R}", type, pos.x, pos.y));
            else if (type != "")
                GamePlay.gpHUDLogCenter("Fire Lab impact outside the marked forest plot or type mismatch.");
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
        if (session == null || stopped || Now < pollAt)
            return;
        double now = Now;
        pollAt = now + 0.5;
        try
        {
            Player player = GamePlay.gpPlayer();
            if (menuPlayer == null)
                InstallMenu(player);
            Record("clock\t" + GamePlay.gpTimeofDay().ToString("R", Invariant));
            ReadFrame(now);
            if (now - receivedAt > 15 && effects.Count != 0)
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
        var desired = new Dictionary<string, Tuple<int, double, double>>();
        for (int i = 1; i < lines.Length; ++i)
        {
            string[] row = lines[i].Split('\t');
            double x, y;
            if (row.Length != 4 || !Regex.IsMatch(row[0], @"^\d+_P\d+_\d+_\d+$") ||
                desired.ContainsKey(row[0]) || !Parse(row[2], out x) || !Parse(row[3], out y))
                return;
            int plot = Array.IndexOf(Plots, row[1]);
            if (plot < 0 || Math.Abs(x - Centers[plot, 0]) > 80 || Math.Abs(y - Centers[plot, 1]) > 80)
                return;
            desired.Add(row[0], Tuple.Create(plot, x, y));
        }
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
        if (desired.Count == 0 && effects.Count == 0)
            return;
        if (createEffect == null)
            BindEffects();
        fading.RemoveAll(delegate(object actor) { return particle.GetValue(actor) == null; });
        foreach (string id in new List<string>(effects.Keys))
        {
            if (!desired.ContainsKey(id))
            {
                object actor = effects[id];
                finishEffect.Invoke(null, new[] { actor });
                fading.Add(actor);
                effects.Remove(id);
            }
        }
        foreach (var item in desired)
        {
            if (effects.ContainsKey(item.Key) || effects.Count + fading.Count >= TotalEffectBudget)
                continue;
            double? z = GroundHeight(item.Value.Item1);
            if (!z.HasValue)
                continue;
            var loc = new Loc(item.Value.Item2, item.Value.Item3, z.Value, 0, 0, 0);
            object effect = createEffect.Invoke(null, new object[] { loc, 1f, Asset, -1.0, true });
            if (effect == null || particle.GetValue(effect) == null)
                throw new InvalidOperationException("Ground fire factory returned no emitter.");
            effects.Add(item.Key, effect);
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
                    return pos.z;
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
