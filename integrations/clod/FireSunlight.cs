// Solar approximation from NOAA's General Solar Position Calculations.
internal static class FireSunlight
{
    private const double Radians = Math.PI / 180;
    private const double SunsetElevation = -0.833;
    private const double FullGlowElevation = -4.0;

    public static double NightFactor(DateTime date, double hour, double latitude,
                                     double longitude, double utcOffset)
    {
        if (Double.IsNaN(hour) || Double.IsInfinity(hour) || hour < 0 || hour >= 24)
            return 0;

        double year = 2 * Math.PI / (DateTime.IsLeapYear(date.Year) ? 366 : 365)
            * (date.DayOfYear - 1 + (hour - 12) / 24);
        double sin = Math.Sin(year), cos = Math.Cos(year);
        double sin2 = Math.Sin(2 * year), cos2 = Math.Cos(2 * year);
        double equation = 229.18 * (0.000075 + 0.001868 * cos - 0.032077 * sin
            - 0.014615 * cos2 - 0.040849 * sin2);
        double declination = 0.006918 - 0.399912 * cos + 0.070257 * sin
            - 0.006758 * cos2 + 0.000907 * sin2
            - 0.002697 * Math.Cos(3 * year) + 0.00148 * Math.Sin(3 * year);
        double angle = (15 * (hour - utcOffset) + longitude + equation / 4 - 180) * Radians;
        double lat = latitude * Radians;
        double sinElevation = Math.Sin(lat) * Math.Sin(declination)
            + Math.Cos(lat) * Math.Cos(declination) * Math.Cos(angle);
        double elevation = Math.Asin(Math.Max(-1, Math.Min(1, sinElevation))) / Radians;
        double fade = (SunsetElevation - elevation) / (SunsetElevation - FullGlowElevation);
        return Math.Max(0, Math.Min(1, fade));
    }
}
