public partial class Mission
{
    private static readonly DateTime FireLightingDate = new DateTime(__FIRE_DATE__);
    private const double FireLightingStart = __FIRE_START__;
    private const double FireLightingLatitude = 51.5, FireLightingLongitude = 0, FireLightingUtcOffset = 0;
    private double fireNightFactor;

    private void RefreshFireLighting(double now)
    {
        int days = (int)Math.Floor((FireLightingStart + Math.Max(0, now) / 3600) / 24);
        double previous = fireNightFactor;
        fireNightFactor = FireSunlight.NightFactor(FireLightingDate.AddDays(days), GamePlay.gpTimeofDay(),
            FireLightingLatitude, FireLightingLongitude, FireLightingUtcOffset);
        if ((previous > 0) != (fireNightFactor > 0))
            Note(String.Format(Invariant, "fire_night_visuals {0} {1:F6}", fireNightFactor > 0 ? "on" : "off", now));
        if (fireNightFactor > 0)
            return;

#if LONDON_DISTRICT_LIGHTS
        foreach (string id in new List<string>(cityLights.Keys))
            RemoveDistrictLight(id);
#else
        if (previous > 0)
            foreach (CityLight light in cityLights.Values)
                if (particle.GetValue(light.Owner) != null)
                    setOwnedEmission.Invoke(light.Light, new object[] { 0f, 0f });
#endif
#if LONDON_WARM_SMOKE
        foreach (string id in new List<string>(warmSmoke.Keys))
            FinishWarmPlume(id);
#endif
    }
}
