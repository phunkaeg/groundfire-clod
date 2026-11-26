// Shared by the self-contained mission script and its offline test executable.
internal sealed class HawkingeRangeResponse
{
    internal const double TargetX = 234503;
    internal const double TargetY = 232745;
    internal const double TargetRadius = 65;
    internal const double StagingX = 234460.75;
    internal const double StagingY = 232726.98;
    private const double SetupSeconds = 12;
    private const double WaterSupplyLitres = 300;
    private const double LineLitresPerSecond = 6;
    private const double DeliveryFraction = 0.65;
    private const double AttackHoseMetres = 110;
    private const double StagingRadius = 65;
    private const double MaximumSampleGap = 2.5;

    private double? lastX;
    private double lastY;
    private double setup;
    private readonly double requiredWater;
    private readonly double fireX;
    private readonly double fireY;
    internal string Stage { get; private set; }
    internal double Pumped { get; private set; }
    internal double EffectiveWater { get { return Pumped * DeliveryFraction; } }

    internal HawkingeRangeResponse(string bomb, double x, double y)
    {
        if (bomb != "SC50" && bomb != "SC250")
            throw new System.ArgumentException("Unsupported range munition.");
        requiredWater = bomb == "SC50" ? 45 : 105;
        fireX = x;
        fireY = y;
        Stage = "en_route";
    }

    internal static double Distance(double x, double y, double otherX, double otherY)
    {
        double dx = x - otherX;
        double dy = y - otherY;
        return System.Math.Sqrt(dx * dx + dy * dy);
    }

    internal static string BombFromTitle(string title)
    {
        string id = (title ?? "").ToUpperInvariant().Replace("-", "").Replace(" ", "").Replace("_", "");
        if (id.Contains("SC250"))
            return "SC250";
        return id.Contains("SC50") && !id.Contains("SC500") ? "SC50" : "";
    }

    internal void Advance(double seconds, double? x, double y)
    {
        if (Stage == "knocked_down" || Stage == "water_exhausted")
            return;
        bool stopped = x.HasValue && lastX.HasValue && seconds > 0 && seconds <= MaximumSampleGap &&
                       Distance(x.Value, y, lastX.Value, lastY) / seconds <= 0.50;
        lastX = x;
        lastY = y;
        if (!stopped || Distance(x.Value, y, StagingX, StagingY) > StagingRadius)
        {
            setup = 0;
            Stage = "en_route";
            return;
        }
        if (Distance(x.Value, y, fireX, fireY) > AttackHoseMetres)
        {
            setup = 0;
            Stage = "out_of_reach";
            return;
        }
        // A portable test supply is staged with the crew. No replenishment.
        double preparing = System.Math.Min(seconds, SetupSeconds - setup);
        setup += preparing;
        double pumping = seconds - preparing;
        if (pumping <= 0)
        {
            Stage = "setting_up";
            return;
        }
        double needed = (requiredWater - EffectiveWater) / DeliveryFraction;
        Pumped += System.Math.Min(needed, System.Math.Min(WaterSupplyLitres - Pumped, LineLitresPerSecond * pumping));
        if (EffectiveWater >= requiredWater - 0.00001)
            Stage = "knocked_down";
        else
            Stage = Pumped >= WaterSupplyLitres ? "water_exhausted" : "pumping";
    }
}
