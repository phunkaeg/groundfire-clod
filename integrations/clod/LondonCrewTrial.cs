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
__IMPACTS__
    };
    private int nextFixtureImpact;
    private readonly object[] trialLocators = new object[CityRoutes.Length];
    private readonly MethodInfo[] trialGetCurrent = new MethodInfo[CityRoutes.Length];
    private readonly bool[] trialPoseUnavailable = new bool[CityRoutes.Length];

    private void ApplyImpactFixture(double now)
    {
        while (nextFixtureImpact < FixedImpacts.Length && FixedImpacts[nextFixtureImpact].Time <= now)
        {
            Impact impact = FixedImpacts[nextFixtureImpact];
            RecordAt(impact.Time, String.Format(Invariant, "bomb\t{0}\t{1:R}\t{2:R}",
                impact.Type, impact.East, impact.North));
            nextFixtureImpact++;
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
