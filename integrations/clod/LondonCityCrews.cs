public partial class Mission
{
    private const string CityPumpGroup = "0_Chief";
    private static readonly Point2d[][] CityRoutes = {
__CITY_ROUTES__
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
        if (number != __CREW_CAMERA_NUMBER__ || crewCameraAttempted || GamePlay.gpPlayer() == null)
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
                ? String.Format(Invariant, "{0:F2} 20.00 0 {1} 6.11", p.y, route.Length)
                : String.Format(Invariant, "{0:F2} 20.00", p.y);
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
#if LONDON_CREW_CAMERA
            FollowCityCrew(i + 1, vehicle);
#endif
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
