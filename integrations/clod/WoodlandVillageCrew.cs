public partial class Mission
{
    private const string CrewGroup = "0_Chief";
    private const double CrewStandX = __CREW_STAND_X__;
    private const double CrewStandY = __CREW_STAND_Y__;
    private int crewMission = -1;
    private bool crewPending;
    private double crewPollAt;
    private Point3d? lastPump;
    private int stillSamples;
    private string pumpName;

    private void DispatchCrew()
    {
        if (crewMission >= 0)
            return;
        ISectionFile section = GamePlay.gpCreateSectionFile();
        section.add("MAIN", "MAP", "Land$English_Channel_1940");
        section.add("Chiefs", CrewGroup, "Vehicle.GB_Emrg_Column gb");
        string road = CrewGroup + "_Road";
__CREW_WAYPOINTS__
        crewMission = GamePlay.gpNextMissionNumber();
        GamePlay.gpPostMissionLoad(section);
        Record("crew_dispatch");
        Note("crew_dispatched " + crewMission.ToString(Invariant));
    }

    private void ObserveCrew(double now)
    {
        if (crewPending)
        {
            crewPending = false;
            DispatchCrew();
        }
        if (crewMission < 0 || now < crewPollAt)
            return;
        crewPollAt = now + 1;
        string name = crewMission.ToString(Invariant) + ":" + CrewGroup;
        AiGroundGroup group = GamePlay.gpActorByName(name) as AiGroundGroup;
        if (group == null)
        {
            AiGroundGroup[] groups = GamePlay.gpGroundGroups(1);
            if (groups != null)
                foreach (AiGroundGroup candidate in groups)
                    if (candidate != null && candidate.IsValid() &&
                        (candidate.Name() == name || (groups.Length == 1 && candidate.ID() == CrewGroup)))
                    {
                        group = candidate;
                        break;
                    }
        }
        AiActor[] vehicles = group == null || !group.IsValid() ? null : group.GetItems();
        if (vehicles == null)
            return;
        AiGroundActor pump = null;
        double nearest = Double.PositiveInfinity;
        foreach (AiActor item in vehicles)
        {
            AiGroundActor vehicle = item as AiGroundActor;
            if (vehicle == null || !vehicle.IsValid() || !vehicle.IsAlive())
                continue;
            string type = vehicle.InternalTypeName() ?? "";
            if (type.IndexOf("Austin_K2_ATV", StringComparison.OrdinalIgnoreCase) < 0)
                continue;
            Point3d candidate = vehicle.Pos();
            double distance = CrewDistance(candidate.x, candidate.y, CrewStandX, CrewStandY);
            if (distance < nearest)
            {
                nearest = distance;
                pump = vehicle;
            }
        }
        if (pump == null)
        {
            stillSamples = 0;
            lastPump = null;
            return;
        }
        Point3d p = pump.Pos();
        string current = pump.Name();
        if (current != pumpName)
        {
            Note("crew_pump " + current + " " + pump.InternalTypeName());
            stillSamples = 0;
            pumpName = current;
            lastPump = null;
        }
        stillSamples = lastPump.HasValue &&
            CrewDistance(p.x, p.y, lastPump.Value.x, lastPump.Value.y) <= 0.7 ? stillSamples + 1 : 0;
        lastPump = p;
        bool stopped = pump.IsTaskComplete() || stillSamples >= 2;
        Record(String.Format(Invariant, "crew_position\t{0:R}\t{1:R}\t{2}", p.x, p.y, stopped ? 1 : 0));
    }

    private static double CrewDistance(double x, double y, double otherX, double otherY)
    {
        double dx = x - otherX, dy = y - otherY;
        return Math.Sqrt(dx * dx + dy * dy);
    }
}
