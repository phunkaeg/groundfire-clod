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
