using System;
using System.Globalization;

internal static class HawkingeRangeChecks
{
    private static void Require(bool condition, string detail)
    {
        if (!condition)
            throw new InvalidOperationException(detail);
    }

    private static double Run(string bomb, double expectedLitres)
    {
        double x = HawkingeRangeResponse.StagingX;
        double y = HawkingeRangeResponse.StagingY;
        var fire = new HawkingeRangeResponse(bomb, HawkingeRangeResponse.TargetX,
                                             HawkingeRangeResponse.TargetY);
        for (int i = 0; i < 10; i++)
            fire.Advance(1, x - 90 + i * 9, y);
        Require(fire.Stage == "en_route" && fire.Pumped == 0, "A moving vehicle applied water.");
        fire.Advance(1, x, y);
        for (int i = 0; i < 5; i++)
            fire.Advance(1, x, y);
        fire.Advance(4, x, y);
        Require(fire.Stage == "en_route" && fire.Pumped == 0, "Stale telemetry retained readiness.");
        for (int i = 0; i < 12; i++)
            fire.Advance(1, x, y);
        Require(fire.Stage == "setting_up" && fire.Pumped == 0, "Water started before setup completed.");

        int seconds = 0;
        while (fire.Stage != "knocked_down" && seconds < 60)
        {
            fire.Advance(1, x, y);
            seconds++;
        }
        Require(fire.Stage == "knocked_down", "Fire failed to reach knockdown.");
        Require(Math.Abs(fire.Pumped - expectedLitres) < 0.0001, "Incorrect water volume.");
        double pumped = fire.Pumped;
        fire.Advance(10, x, y);
        Require(fire.Pumped == pumped, "Knocked-down fire continued to use water.");
        Console.WriteLine(String.Format(CultureInfo.InvariantCulture, "{0} {1} {2:F3}", bomb, seconds, pumped));
        return pumped;
    }

    public static void Main()
    {
        Require(HawkingeRangeResponse.BombFromTitle("Bomb.SC-50_GradeII_J") == "SC50", "SC 50 alias failed.");
        Require(HawkingeRangeResponse.BombFromTitle("Bomb.SC-250_Type1_J") == "SC250", "SC 250 alias failed.");
        Require(HawkingeRangeResponse.BombFromTitle("Bomb.SC-500") == "", "Unexpected bomb accepted.");
        double light = Run("SC50", 45 / 0.65);
        double heavy = Run("SC250", 105 / 0.65);
        Require(heavy > light, "The two loadouts produced the same water requirement.");

        double x = HawkingeRangeResponse.StagingX, y = HawkingeRangeResponse.StagingY;
        var outOfReach = new HawkingeRangeResponse("SC50", x + 180, y);
        for (int i = 0; i < 40; i++)
            outOfReach.Advance(1, x, y);
        Require(outOfReach.Stage == "out_of_reach" && outOfReach.Pumped == 0, "Water reached a distant fire.");
    }
}
