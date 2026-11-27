public partial class Mission
{
#if LONDON_DISTRICT_LIGHTS
    private const int CityLightBudget = __DISTRICT_LIGHT_BUDGET__;
    private const double CityLightSpacing = 105.0;
    private const float CityLightRadius = 165f;
#elif LONDON_PULSING_LIGHTS
    private const int CityLightBudget = 6;
    private const double CityLightSpacing = 125.0;
    private const float CityLightRadius = 140f;
#else
    private const int CityLightBudget = 3;
    private const float CityLightIntensity = 2f;
    private const double CityLightSpacing = 160.0;
    private const float CityLightRadius = 140f;
#endif
    private const double CityLightHeight = 12.0;

    private sealed class CityLight
    {
        public WLightPoint Light;
        public object Owner;
        public Point3d Anchor;
        public bool RenderPositionLogged;
#if LONDON_PULSING_LIGHTS
        public double Phase;
#endif
#if LONDON_DISTRICT_LIGHTS
        public double Strength;
        public double UpdatedAt;
#endif
    }

    private readonly Dictionary<string, CityLight> cityLights = new Dictionary<string, CityLight>();
    private FieldInfo effectDraw;
    private ConstructorInfo ownedPointLight;
    private FieldInfo lightOffset;
    private MethodInfo attachLight;
    private MethodInfo setOwnedEmission;
    private bool cityLightFailed;

#if LONDON_PULSING_LIGHTS
    private Dictionary<string, double> cityLightStrength = new Dictionary<string, double>();
    private readonly System.Diagnostics.Stopwatch cityLightClock = System.Diagnostics.Stopwatch.StartNew();
    private double nextCityLightUpdate;
    private double nextCityLightSample;

    private void ApplyCityLight(WLightPoint light, double phase, double strength, double seconds,
        out float green, out float intensity)
    {
        // Using wall time keeps the flicker readable at accelerated mission time.
#if LONDON_DISTRICT_LIGHTS
        double pulse = 1.0 + 0.06 * Math.Sin(seconds * 2.8 + phase)
                           + 0.035 * Math.Sin(seconds * 6.2 + phase * 1.61);
        double colorHeat = 0.75 * Math.Sqrt(strength);
        intensity = (float)(3.8 * strength * pulse);
#else
        double pulse = 0.83 + 0.13 * Math.Sin(seconds * 5.3 + phase)
                            + 0.08 * Math.Sin(seconds * 11.9 + phase * 1.61);
        double colorHeat = Math.Sqrt(strength) * (0.72 + 0.28 * Math.Sin(seconds * 2.4 + phase));
        intensity = (float)((0.35 + 4.10 * strength) * pulse);
#endif
        intensity *= (float)fireNightFactor;
        green = (float)(0.18 + 0.36 * colorHeat);
        var color = new Tuple3f(1f, green, (float)(0.045 + 0.18 * colorHeat));
        light.setColor(ref color);
        setOwnedEmission.Invoke(light, new object[] { intensity, CityLightRadius });
    }

    private void PulseCityLights()
    {
        if (fireNightFactor <= 0)
            return;
#if LONDON_WARM_SMOKE
        if (warmSmokeHeld)
            return;
#endif
#if LONDON_LIGHT_BENCHMARK
        if (lightBenchFrozen)
            return;
#endif
        double seconds = cityLightClock.Elapsed.TotalSeconds;
        if (cityLightFailed || cityLights.Count == 0 || seconds < nextCityLightUpdate)
            return;
        nextCityLightUpdate = seconds + 1.0 / 12.0;
        bool sample = seconds >= nextCityLightSample;
        if (sample)
            nextCityLightSample = seconds + 4.0;
        try
        {
            foreach (var item in cityLights)
            {
                CityLight city = item.Value;
                double strength;
                if (particle.GetValue(city.Owner) == null)
                    continue;
#if LONDON_DISTRICT_LIGHTS
                cityLightStrength.TryGetValue(item.Key, out strength);
                double dt = Math.Min(0.25, seconds - city.UpdatedAt);
                double fadeSeconds = strength >= city.Strength ? 2.1 : 5;
                city.Strength += (strength - city.Strength) * (1 - Math.Exp(-dt / fadeSeconds));
                city.UpdatedAt = seconds;
                strength = city.Strength;
#else
                if (!cityLightStrength.TryGetValue(item.Key, out strength))
                    continue;
#endif
                float green, intensity;
                ApplyCityLight(city.Light, city.Phase, strength, seconds, out green, out intensity);
                if (sample)
                    Note(String.Format(Invariant, "city_light_pulse {0} {1:F6} {2:F3} {3:F3} {4:F3}",
                        item.Key, Now, strength, green, intensity));
            }
        }
        catch (Exception error)
        {
            cityLightFailed = true;
            Note("city_light_error " + error.GetBaseException().Message);
        }
    }
#endif

    private void BindCityLights(Type effect)
    {
        // BindEffects has already verified the exact engine assemblies.
        const BindingFlags fields = BindingFlags.Instance | BindingFlags.Public |
            BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
        Type owner = effect.BaseType;
        Type light = effect.Assembly.GetType("iAGyqzCT7GrCImqReh9aGOE0UYDNoV6Lh8AHseKFcifx", true);
        if (!typeof(WLightPoint).IsAssignableFrom(light))
            throw new InvalidOperationException("Unexpected city light type.");
        effectDraw = owner.GetField("KJnEE1bYssohV97HSzi8Wdo", fields);
        ownedPointLight = light.GetConstructor(new[] { owner });
        lightOffset = light.GetField("H$9tex8fHhAXegggcDlXQxY", fields);
        setOwnedEmission = light.GetMethod("2TSXkZX9YWjHrJEckGyXMFI", new[] { typeof(float), typeof(float) });
        if (effectDraw == null || ownedPointLight == null || lightOffset == null ||
            lightOffset.FieldType != typeof(Point3d) || setOwnedEmission == null ||
            setOwnedEmission.ReturnType != typeof(void))
            throw new MissingMemberException("Unexpected point light binding.");
        attachLight = effectDraw.FieldType.GetMethod("MW_GUZt3_kbiRW8Vr6GtNf8",
            new[] { typeof(string), light });
        if (attachLight == null || attachLight.ReturnType != typeof(void))
            throw new MissingMemberException("Unexpected effect draw light binding.");
    }

    private void TryLightCityFire(string id, int plot, object effect, Point3d anchor)
    {
        if (fireNightFactor <= 0 || cityLightFailed || Plots[plot] != "town" || cityLights.Count >= CityLightBudget)
            return;

        foreach (CityLight other in cityLights.Values)
        {
            double dx = anchor.x - other.Anchor.x, dy = anchor.y - other.Anchor.y;
            if (dx * dx + dy * dy < CityLightSpacing * CityLightSpacing)
                return;
        }

        WLightPoint light = null;
        bool owned = false;
        try
        {
            if (attachLight == null)
                BindCityLights(effect.GetType());
            object draw = effectDraw.GetValue(effect);
            if (draw == null)
                throw new InvalidOperationException("Fire effect has no draw owner.");
            light = (WLightPoint)ownedPointLight.Invoke(new[] { effect });
            lightOffset.SetValue(light, new Point3d(0, 0, CityLightHeight));
            var city = new CityLight { Light = light, Owner = effect, Anchor = anchor };
#if LONDON_PULSING_LIGHTS
            city.Phase = (anchor.x * 0.713 + anchor.y * 0.419) % (2 * Math.PI);
            double strength;
#if LONDON_DISTRICT_LIGHTS
            strength = 0;
            city.UpdatedAt = cityLightClock.Elapsed.TotalSeconds;
#else
            cityLightStrength.TryGetValue(id, out strength);
#endif
            float green, intensity;
            ApplyCityLight(light, city.Phase, strength, cityLightClock.Elapsed.TotalSeconds, out green, out intensity);
#else
            var color = new Tuple3f(1f, 0.48f, 0.20f);
            light.setColor(ref color);
            setOwnedEmission.Invoke(light, new object[] { (float)(CityLightIntensity * fireNightFactor), CityLightRadius });
#endif
            // The effect submits the light each frame and disposes it with the draw owner.
            attachLight.Invoke(draw, new object[] { "GroundFireCity", light });
            owned = true;
            cityLights.Add(id, city);
            Note(String.Format(Invariant, "city_light_on {0} {1:F6} {2:F1} {3:F1} {4:F1}",
                id, Now, anchor.x, anchor.y, anchor.z + CityLightHeight));
        }
        catch (Exception error)
        {
            cityLightFailed = true;
            if (light != null && !owned)
                ((IDisposable)light).Dispose();
            Note("city_light_error " + error.GetBaseException().Message);
        }
    }

#if !LONDON_DISTRICT_LIGHTS
    private void ReconcileAttachedCityLights(Dictionary<string, Tuple<int, double, double>> desired)
    {
        if (fireNightFactor <= 0 || cityLightFailed)
            return;
#if !LONDON_PULSING_LIGHTS
        foreach (CityLight light in cityLights.Values)
            if (particle.GetValue(light.Owner) != null)
                setOwnedEmission.Invoke(light.Light, new object[] {
                    (float)(CityLightIntensity * fireNightFactor), CityLightRadius });
#endif
        foreach (var point in desired)
        {
            object effect;
            if (cityLights.Count >= CityLightBudget)
                break;
            if (point.Key.Contains("_P2_") || cityLights.ContainsKey(point.Key) ||
                !effects.TryGetValue(point.Key, out effect))
                continue;
            var p = point.Value;
            double? ground = CaptureTerrainHeight(p.Item2, p.Item3);
            if (ground.HasValue)
                TryLightCityFire(point.Key, p.Item1, effect, new Point3d(p.Item2, p.Item3, ground.Value));
        }
    }
#endif

    private void ObserveCityLights()
    {
        foreach (var item in cityLights)
        {
            CityLight city = item.Value;
            if (city.RenderPositionLogged || particle.GetValue(city.Owner) == null)
                continue;
            var rendered = new Point3d();
            city.Light.getPos(ref rendered);
            double dx = rendered.x - city.Anchor.x, dy = rendered.y - city.Anchor.y;
            if (dx * dx + dy * dy > 4)
                continue;
            city.RenderPositionLogged = true;
            Note(String.Format(Invariant, "city_light_render_pos {0} {1:F6} {2:F1} {3:F1} {4:F1}",
                item.Key, Now, rendered.x, rendered.y, rendered.z));
        }
    }

    private void EndCityLight(string id)
    {
        CityLight city;
        if (!cityLights.TryGetValue(id, out city))
            return;
        // Smoke may still fade after the flame has gone out.
        if (particle.GetValue(city.Owner) != null)
            setOwnedEmission.Invoke(city.Light, new object[] { 0f, 0f });
        cityLights.Remove(id);
        Note(String.Format(Invariant, "city_light_off {0} {1:F6}", id, Now));
    }
}
