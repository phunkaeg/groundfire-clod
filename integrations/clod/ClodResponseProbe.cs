// Single-player dispatch fixture for GroundFire Hawkinge.mis. Compile separately
// from other root mission scripts. The fixture dispatches at t=8 s.
using System;
using System.Globalization;
using System.IO;
using maddox.GP;
using maddox.game;
using maddox.game.world;

public class Mission : AMission
{
    private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
    private const string Group = "0_Chief";
    private string session;
    private double start;
    private double nextPoll;
    private int submission = -1;
    private bool loaded;
    private string trace;

    public override void OnBattleStarted()
    {
        base.OnBattleStarted();
        if (!GamePlay.gpIsServerSingle())
            return;
        session = Guid.NewGuid().ToString("N");
        start = Time.TicksToSecs(Time.tickCounter());
        nextPoll = 8.0;
        submission = -1;
        loaded = false;
        MissionNumberListener = -1;
        string directory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                        "GroundFireHawkinge", "response");
        Directory.CreateDirectory(directory);
        trace = Path.Combine(directory, session + ".events.tsv");
    }

    public override void OnMissionLoaded(int missionNumber)
    {
        base.OnMissionLoaded(missionNumber);
        if (session != null && missionNumber == submission)
            loaded = true;
    }

    public override void OnTickGame()
    {
        base.OnTickGame();
        if (session == null)
            return;
        double seconds = Time.TicksToSecs(Time.tickCounter()) - start;
        if (seconds < nextPoll)
            return;
        nextPoll = seconds + 1;

        if (submission < 0)
        {
            Dispatch(seconds);
            return;
        }
        if (!loaded)
            return;

        string name = submission.ToString(Invariant) + ":" + Group;
        AiGroundGroup group = GamePlay.gpActorByName(name) as AiGroundGroup;
        if (group == null)
        {
            AiGroundGroup[] groups = GamePlay.gpGroundGroups(1);
            if (groups != null)
            {
                foreach (AiGroundGroup candidate in groups)
                {
                    if (candidate != null && candidate.IsValid() && candidate.Name() == name)
                    {
                        group = candidate;
                        break;
                    }
                }
            }
        }
        if (group == null || !group.IsValid())
        {
            Log(seconds, "group_missing", name);
            return;
        }

        AiActor[] items = group.GetItems();
        if (items == null)
            return;
        foreach (AiActor item in items)
        {
            AiGroundActor vehicle = item as AiGroundActor;
            if (vehicle == null || !vehicle.IsValid() || !vehicle.IsAlive())
                continue;
            Point3d p = vehicle.Pos();
            Log(seconds, "vehicle", String.Format(Invariant, "{0}\t{1}\t{2:F3}\t{3:F3}\t{4:F3}\t{5}",
                vehicle.Name(), vehicle.InternalTypeName(), p.x, p.y, p.z, vehicle.IsTaskComplete()));
        }
    }

    private void Dispatch(double seconds)
    {
        ISectionFile section = GamePlay.gpCreateSectionFile();
        section.add("MAIN", "MAP", "Land$English_Channel_1940");
        section.add("Chiefs", Group, "Vehicle.GB_Emrg_Column gb");
        // The geometry is from the shipped Hawkinge attack mission's 3_Chief_Road.
        string road = Group + "_Road";
        section.add(road, "234673.92", "232407.78 38.40 0 4 6.11");
        section.add(road, "234656.00", "232544.00 20.00");
        section.add(road, "234592.00", "232608.00 20.00");
        section.add(road, "234460.75", "232726.98 38.40");
        submission = GamePlay.gpNextMissionNumber();
        GamePlay.gpPostMissionLoad(section);
        Log(seconds, "dispatch", submission.ToString(Invariant));
    }

    private void Log(double seconds, string action, string detail)
    {
        string line = String.Format(Invariant, "GROUNDFIRE_RESPONSE {0}\t{1:F3}\t{2}\t{3}",
                                    session, seconds, action, detail);
        File.AppendAllText(trace, line + Environment.NewLine);
    }
}
