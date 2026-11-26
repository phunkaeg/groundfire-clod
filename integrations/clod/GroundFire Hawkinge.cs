using System;
using System.Globalization;
using System.IO;
using maddox.GP;
using maddox.game;
using maddox.game.world;

public class Mission : AMission
{
    private const double FireX = 235455;
    private const double FireY = 232385;
    private const double ControlX = 235455;
    private const double ControlY = 232365;
    private const string ControlName = "Static7102";
    private const string EffectName = "Static7101";
    private static readonly string BridgeDirectory = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GroundFireHawkinge");
    private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;

    private string session;
    private double startTime;
    private double nextPoll;
    private double inspectAt;
    private int commandNumber;
    private int expectedMissionNumber;
    private bool submissionEvent;
    private bool controlSpawned;
    private bool quarantined;
    private string currentEffect = "off";
    private string pendingCheck = "";

    private double ClockSeconds()
    {
        return Time.TicksToSecs(Time.tickCounter()) - startTime;
    }

    private void Record(string action, string detail)
    {
        string line = String.Format(Invariant, "{0}\t{1:F3}\t{2}\t{3}\r\n",
                                    session, ClockSeconds(), action, detail.Replace("\r", " ").Replace("\n", " "));
        File.AppendAllText(Path.Combine(BridgeDirectory, session + ".events.tsv"), line);
    }

    private void WriteClock(double seconds)
    {
        string clock = Path.Combine(BridgeDirectory, "clock.tsv");
        string temp = Path.Combine(BridgeDirectory, session + ".clock.tmp");
        File.WriteAllText(temp, String.Format(Invariant, "{0}\t{1:R}\r\n", session, seconds));
        if (File.Exists(clock))
            File.Replace(temp, clock, null);
        else
            File.Move(temp, clock);
    }

    public override void OnBattleStarted()
    {
        base.OnBattleStarted();
        if (!GamePlay.gpIsServerSingle())
            return;
        startTime = Time.TicksToSecs(Time.tickCounter());
        session = Guid.NewGuid().ToString("N");
        nextPoll = 0;
        commandNumber = 0;
        currentEffect = "off";
        pendingCheck = "";
        quarantined = false;
        controlSpawned = false;
        MissionNumberListener = -1;
        try
        {
            Directory.CreateDirectory(BridgeDirectory);
            Record("mission_started", "Hawkinge single-player effect test");
            WriteClock(0);
        }
        catch (Exception error)
        {
            GamePlay.gpHUDLogCenter("GroundFire bridge unavailable: " + error.Message);
            session = null;
        }
    }

    public override void OnMissionLoaded(int missionNumber)
    {
        base.OnMissionLoaded(missionNumber);
        if (session != null && missionNumber == expectedMissionNumber)
            submissionEvent = true;
    }

    public override void OnTickGame()
    {
        base.OnTickGame();
        if (session == null)
            return;
        double seconds = ClockSeconds();
        if (seconds < nextPoll)
            return;
        nextPoll = seconds + 0.5;
        try
        {
            WriteClock(seconds);
            if (pendingCheck.Length != 0 && seconds >= inspectAt)
                Inspect();

            string command = Path.Combine(BridgeDirectory, "desired.tsv");
            if (pendingCheck.Length != 0 || !File.Exists(command))
                return;

            string[] fields = File.ReadAllText(command).Trim().Split('\t');
            int number;
            double issuedAt;
            if (fields.Length != 4 || fields[0] != session ||
                !Int32.TryParse(fields[1], NumberStyles.Integer, Invariant, out number) ||
                !Double.TryParse(fields[2], NumberStyles.Float, Invariant, out issuedAt) ||
                Double.IsNaN(issuedAt) || Double.IsInfinity(issuedAt) ||
                issuedAt > seconds || seconds - issuedAt > 5 || number <= commandNumber ||
                (fields[3] != "small" && fields[3] != "large" && fields[3] != "off"))
                return;
            commandNumber = number;
            Apply(fields[3], seconds);
        }
        catch (IOException)
        {
            // The sidecar may be replacing a file. Retry at the next poll.
        }
        catch (Exception error)
        {
            quarantined = true;
            Record("probe_error", error.GetType().Name + " " + error.Message);
            GamePlay.gpHUDLogCenter("GroundFire probe stopped. See the bridge log.");
        }
    }

    private GroundStationary FindAlive(double x, double y, string name)
    {
        GroundStationary[] nearby = GamePlay.gpGroundStationarys(x, y, 5);
        if (nearby == null)
            return null;
        foreach (GroundStationary item in nearby)
        {
            Point3d position = item.pos;
            if (item.IsAlive && item.Name != null &&
                (item.Name == name || item.Name.EndsWith(":" + name, StringComparison.Ordinal)) &&
                Math.Abs(position.x - x) < 2 && Math.Abs(position.y - y) < 2)
                return item;
        }
        return null;
    }

    private void Apply(string desired, double seconds)
    {
        if (quarantined || currentEffect == desired)
            return;

        if (currentEffect != "off")
        {
            GroundStationary handle = FindAlive(FireX, FireY, EffectName);
            if (handle == null)
            {
                quarantined = true;
                Record("effect_handle_missing", currentEffect + " -> " + desired);
                GamePlay.gpHUDLogCenter("GroundFire could not identify the effect for cleanup.");
                return;
            }
            handle.Destroy();
            pendingCheck = "remove";
            inspectAt = seconds + 1;
            Record("effect_destroy_called", currentEffect);
            return;
        }

        string asset = desired == "small" ? "BuildingFireSmall" : "BuildingFireBig";
        ISectionFile section = GamePlay.gpCreateSectionFile();
        section.add("MAIN", "MAP", "Land$English_Channel_1940");
        section.add("Stationary", EffectName, String.Format(Invariant,
            "Smoke.Environment.{0} nn {1:F2} {2:F2} 0.00 /height 0.00", asset, FireX, FireY));
        if (!controlSpawned)
            section.add("Stationary", ControlName, String.Format(Invariant,
                "Stationary.Environment.TentBell_UK1 gb {0:F2} {1:F2} 0.00", ControlX, ControlY));
        expectedMissionNumber = GamePlay.gpNextMissionNumber();
        submissionEvent = false;
        controlSpawned = true;
        currentEffect = desired;
        pendingCheck = "spawn";
        inspectAt = seconds + 3;
        GamePlay.gpPostMissionLoad(section);
        Record("effect_load_requested", asset);
        GamePlay.gpHUDLogCenter("GroundFire " + desired + " effect requested east of Hawkinge.");
    }

    private void Inspect()
    {
        string check = pendingCheck;
        pendingCheck = "";
        bool fireFound = FindAlive(FireX, FireY, EffectName) != null;
        bool controlFound = FindAlive(ControlX, ControlY, ControlName) != null;
        AiActor actor = GamePlay.gpActorByName(expectedMissionNumber.ToString(Invariant) + ":" + EffectName);
        Record("inspect_" + check, String.Format(Invariant,
            "mission_loaded={0} control_found={1} effect_stationary={2} effect_actor={3}",
            submissionEvent, controlFound, fireFound, actor != null && actor.IsValid()));
        if (check == "remove")
        {
            quarantined = fireFound;
            if (!fireFound)
            {
                currentEffect = "off";
                // Re-read the same desired state now that the removal has settled.
                commandNumber--;
            }
        }
    }

    public override void OnBattleStoped()
    {
        base.OnBattleStoped();
        if (session != null)
        {
            Record("mission_stopped", "Mission ended");
            session = null;
        }
    }
}
