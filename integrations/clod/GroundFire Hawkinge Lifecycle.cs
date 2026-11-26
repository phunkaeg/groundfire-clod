using System;
using System.Globalization;
using System.IO;
using System.Reflection;
using maddox.core;
using maddox.GP;
using maddox.game;
using maddox.game.world;

public class Mission : AMission
{
    private const double X = 235455;
    private const double PrimaryY = 232385;
    private const double ControlY = 232475;
    private const string Asset = "$core/3do/sfx/fire/BuildingFireSmall.eff";
    private static readonly string DirectoryPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GroundFireHawkinge", "lifecycle");
    private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;

    private string session;
    private double startTime;
    private double nextPoll;
    private int sequence;
    private bool started;
    private bool finished;
    private bool retired;
    private bool controlFinished;
    private bool controlRetired;
    private bool failed;
    private MethodInfo createEffect;
    private MethodInfo finishEffect;
    private FieldInfo particleField;
    private object primary;
    private object control;
    private double finishAt;

    public override void OnBattleStarted()
    {
        base.OnBattleStarted();
        if (!GamePlay.gpIsServerSingle())
            return;
        startTime = Time.TicksToSecs(Time.tickCounter());
        session = Guid.NewGuid().ToString("N");
        try
        {
            Directory.CreateDirectory(DirectoryPath);
            Record(0, "mission_started", "Hawkinge owned-emitter test");
            BindEffectMethods();
            Record(0, "effect_methods_bound", Asset);
            WriteClock(0);
        }
        catch (Exception error)
        {
            Fail(0, error);
        }
    }

    private void BindEffectMethods()
    {
        // This is the effect actor and its stock create/finish pair on the inspected build.
        Assembly engine = null;
        foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            if (assembly.GetName().Name == "maddox")
            {
                engine = assembly;
                break;
            }
        }
        if (engine == null || engine.ManifestModule.ModuleVersionId != new Guid("8e7a2ac5-43e4-45fc-8ef5-f4e3d36baff3") ||
            typeof(WEff3D).Module.ModuleVersionId != new Guid("7cabe1d9-b513-4d66-82fb-8d66589e5f09"))
            throw new InvalidOperationException("The installed effect assemblies differ from the inspected build.");

        Type actor = engine.GetType("yfF_qZl67WlmNS9coEvP0_bSaSCDSqkcGRjRO0s$kmQH", true);
        const BindingFlags methods = BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly;
        createEffect = actor.GetMethod("ZNpynOtOqVuCJyfuWKwJwy0", methods, null,
            new[] { typeof(Loc).MakeByRefType(), typeof(float), typeof(string), typeof(double), typeof(bool) }, null);
        finishEffect = actor.GetMethod("F6mh8rjUa2GGR$0BBCl7kQA", methods, null, new[] { actor }, null);
        particleField = actor.GetField("JfGsspZfCQ8TatQl98$8kEs",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
        if (createEffect == null || createEffect.ReturnType != actor ||
            finishEffect == null || finishEffect.ReturnType != typeof(void) ||
            particleField == null || particleField.FieldType != typeof(WEff3D))
            throw new MissingMemberException("Unexpected effect actor signature.");
    }

    public override void OnTickGame()
    {
        base.OnTickGame();
        if (session == null || failed)
            return;
        double seconds = Time.TicksToSecs(Time.tickCounter()) - startTime;
        if (seconds < nextPoll)
            return;
        nextPoll = seconds + 0.5;
        try
        {
            WriteClock(seconds);
            string desired = ReadDesired(seconds);
            if (!started && (desired == "small" || desired == "large"))
                StartEmitters(seconds);
            if (started && !finished && desired == "off")
                FinishPrimary(seconds);

            if (finished && !retired && Particle(primary) == null)
            {
                retired = true;
                Record(seconds, "primary_disposed", "control_present=" + (Particle(control) != null));
                GamePlay.gpHUDLogCenter("Hawkinge test plume cleared. The north control is still burning.");
            }
            if (retired && !controlFinished && seconds >= finishAt + 30)
            {
                finishEffect.Invoke(null, new[] { control });
                controlFinished = true;
                Record(seconds, "control_finish_called", Status(control));
            }
            if (controlFinished && !controlRetired && Particle(control) == null)
            {
                controlRetired = true;
                Record(seconds, "control_disposed", "both effect actors released their emitters");
                GamePlay.gpHUDLogCenter("Hawkinge control plume cleared.");
            }
        }
        catch (IOException)
        {
            // The sidecar can replace its command file during a read.
        }
        catch (Exception error)
        {
            Fail(seconds, error);
        }
    }

    private void StartEmitters(double seconds)
    {
        double primaryZ = MarkerHeight(PrimaryY, "Static7102");
        double controlZ = MarkerHeight(ControlY, "Static7103");
        primary = Spawn(PrimaryY, primaryZ);
        control = Spawn(ControlY, controlZ);
        started = true;
        Record(seconds, "emitters_created", String.Format(Invariant,
            "primary_z={0:F2} {1} control_z={2:F2} {3}", primaryZ, Status(primary), controlZ, Status(control)));
        GamePlay.gpHUDLogCenter("Hawkinge test and control plumes started. Test plume is south.");
    }

    private double MarkerHeight(double y, string name)
    {
        GroundStationary[] markers = GamePlay.gpGroundStationarys(X, y, 5);
        if (markers != null)
        {
            foreach (GroundStationary marker in markers)
            {
                Point3d pos = marker.pos;
                if (marker.IsAlive && marker.Name != null &&
                    (marker.Name == name || marker.Name.EndsWith(":" + name, StringComparison.Ordinal)) &&
                    Math.Abs(pos.x - X) < 2 && Math.Abs(pos.y - y) < 2)
                    return pos.z;
            }
        }
        throw new InvalidOperationException("Missing terrain height marker " + name);
    }

    private object Spawn(double y, double z)
    {
        object actor = createEffect.Invoke(null, new object[] { new Loc(X, y, z, 0, 0, 0), 1f, Asset, -1.0, true });
        if (Particle(actor) == null)
            throw new InvalidOperationException("Ground fire factory returned no emitter.");
        return actor;
    }

    private void FinishPrimary(double seconds)
    {
        if (Particle(primary) == null || Particle(control) == null)
            throw new InvalidOperationException("One of the emitters ended before the suppression command.");
        Record(seconds, "suppress_received", "primary " + Status(primary) + " control " + Status(control));
        finishEffect.Invoke(null, new[] { primary });
        finished = true;
        finishAt = seconds;
        Record(seconds, "primary_finish_called", "primary " + Status(primary) + " control " + Status(control));
        GamePlay.gpHUDLogCenter("Fire simulation stopped the south plume. Residual smoke can fade.");
    }

    private WEff3D Particle(object actor)
    {
        return actor == null ? null : (WEff3D)particleField.GetValue(actor);
    }

    private string Status(object actor)
    {
        WEff3D emitter = Particle(actor);
        if (emitter == null)
            return "disposed";
        return String.Format(Invariant, "intensity={0:F2} life={1:F2} fade={2:F2}",
            emitter.getIntesity(), emitter.timeLife(), emitter.timeFinish());
    }

    private string ReadDesired(double seconds)
    {
        string path = Path.Combine(DirectoryPath, "desired.tsv");
        if (!File.Exists(path))
            return "";
        string[] fields = File.ReadAllText(path).Trim().Split('\t');
        int number;
        double issuedAt;
        if (fields.Length != 4 || fields[0] != session ||
            !Int32.TryParse(fields[1], NumberStyles.Integer, Invariant, out number) ||
            !Double.TryParse(fields[2], NumberStyles.Float, Invariant, out issuedAt) ||
            Double.IsNaN(issuedAt) || Double.IsInfinity(issuedAt) ||
            issuedAt > seconds || seconds - issuedAt > 5 || number <= sequence)
            return "";
        sequence = number;
        return fields[3];
    }

    private void WriteClock(double seconds)
    {
        string clock = Path.Combine(DirectoryPath, "clock.tsv");
        string temp = Path.Combine(DirectoryPath, session + ".clock.tmp");
        File.WriteAllText(temp, String.Format(Invariant, "{0}\t{1:R}\r\n", session, seconds));
        if (File.Exists(clock))
            File.Replace(temp, clock, null);
        else
            File.Move(temp, clock);
    }

    private void Record(double seconds, string action, string detail)
    {
        string line = String.Format(Invariant, "{0}\t{1:F3}\t{2}\t{3}\r\n",
            session, seconds, action, detail.Replace("\r", " ").Replace("\n", " "));
        File.AppendAllText(Path.Combine(DirectoryPath, session + ".events.tsv"), line);
    }

    private void Fail(double seconds, Exception error)
    {
        failed = true;
        Exception cause = error.GetBaseException();
        try
        {
            Record(seconds, "probe_error", cause.GetType().Name + " " + cause.Message);
        }
        catch (IOException)
        {
        }
        GamePlay.gpHUDLogCenter("Hawkinge lifecycle test stopped. See the bridge log.");
    }
}
