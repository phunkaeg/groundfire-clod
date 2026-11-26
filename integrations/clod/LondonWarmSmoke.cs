public partial class Mission
{
    private const string WarmSmokeFolder = "$user/GroundFireEffects/";
    private static readonly string[] WarmSmokeAssets = {
        WarmSmokeFolder + "WarmSmokePlumeLower.eff",
        WarmSmokeFolder + "WarmSmokePlumeMiddle.eff",
        WarmSmokeFolder + "WarmSmokePlumeUpper.eff"
    };
    private static readonly float[] StockLowerSmokeRate = { 2f };
    private readonly Dictionary<string, WarmPlume> warmSmoke = new Dictionary<string, WarmPlume>();
    private bool warmSmokeFailed;
    private bool warmSmokeAssetsChecked;
    private bool warmSmokeHeld;
    private bool warmSmokeFixtureStarted;
    private string lastWarmSmokeCommand;

    private sealed class WarmPlume
    {
        public readonly object[] Owners = new object[WarmSmokeAssets.Length];
        public Loc Origin;
        public double Glow;
        public double UpdatedAt;
        public double LastLoggedAt;
    }

    private void ReconcileWarmSmoke(Dictionary<string, Tuple<int, double, double>> desired, float smokeScale)
    {
        if (warmSmokeFailed)
            return;
        try
        {
            var flames = new List<KeyValuePair<string, Tuple<int, double, double>>>();
            foreach (var point in desired)
                if (point.Key.Contains("_P1_") || point.Key.Contains("_P4_"))
                    flames.Add(point);

            var plumeHeat = new Dictionary<string, double>();
            foreach (var point in desired)
            {
                if (!point.Key.Contains("_P2_") || !effects.ContainsKey(point.Key))
                    continue;
                double heat = 0;
                foreach (var flame in flames)
                {
                    double dx = point.Value.Item2 - flame.Value.Item2;
                    double dy = point.Value.Item3 - flame.Value.Item3;
                    double strength;
                    if (cityLightStrength.TryGetValue(flame.Key, out strength))
                        heat = Math.Max(heat, strength * (1 - (dx * dx + dy * dy) / (145 * 145)));
                }
                plumeHeat.Add(point.Key, Math.Max(0, (heat - 0.08) / 0.92));
            }

            foreach (string id in new List<string>(warmSmoke.Keys))
            {
                if (plumeHeat.ContainsKey(id))
                    continue;
                FinishWarmPlume(id);
            }

            double now = Now;
            foreach (var source in plumeHeat)
            {
                WarmPlume plume;
                if (!warmSmoke.TryGetValue(source.Key, out plume))
                {
                    if (source.Value == 0)
                        continue;
                    var point = desired[source.Key];
                    double? ground = CaptureTerrainHeight(point.Item2, point.Item3);
                    if (!ground.HasValue)
                        continue;
                    if (!warmSmokeAssetsChecked)
                    {
                        foreach (string asset in WarmSmokeAssets)
                            CheckSmokeAsset(asset);
                        CheckSmokeAsset(WarmSmokeFolder + "WarmSmokePlume.mma");
                        CheckSmokeAsset(WarmSmokeFolder + "Smoke_Sprites_Air_W.dds");
                        warmSmokeAssetsChecked = true;
                    }
                    // Start just above the low London roofs so the smoke reads from street fires.
                    plume = new WarmPlume {
                        Origin = new Loc(point.Item2, point.Item3, ground.Value + 12, 0, 0, 0),
                        UpdatedAt = now, LastLoggedAt = now - 5
                    };
                    warmSmoke.Add(source.Key, plume);
                    Note(String.Format(Invariant, "warm_smoke_on {0} {1:F6} {2:F3} {3:F3}",
                        source.Key, now, point.Item2, point.Item3));
                }

                double elapsed = Math.Max(0, now - plume.UpdatedAt);
                double responseTime = source.Value > plume.Glow ? 8 : 11;
                plume.Glow += (source.Value - plume.Glow) * (1 - Math.Exp(-elapsed / responseTime));
                plume.UpdatedAt = now;
                if (source.Value == 0 && plume.Glow < 0.01)
                {
                    FinishWarmPlume(source.Key);
                    continue;
                }

                double brightness = Math.Pow(plume.Glow, 1.35);
                BlendWarmSmoke(plume, smokeScale, brightness);
                SetLowerSmokeRate(source.Key, new[] { (float)(StockLowerSmokeRate[0] * (1 - brightness)) });
                if (now - plume.LastLoggedAt >= 4)
                {
                    Note(String.Format(Invariant, "warm_smoke_ramp {0} {1:F2} {2:F3} {3:F3} {4:F3}",
                        source.Key, now, source.Value, plume.Glow, brightness));
                    plume.LastLoggedAt = now;
                }
            }
        }
        catch (Exception error)
        {
            warmSmokeFailed = true;
            Note("warm_smoke_error " + error.GetBaseException().Message);
        }
    }

    private void FinishWarmPlume(string id)
    {
        foreach (object owner in warmSmoke[id].Owners)
            if (owner != null && particle.GetValue(owner) != null)
                finishEffect.Invoke(null, new[] { owner });
        warmSmoke.Remove(id);
        SetLowerSmokeRate(id, StockLowerSmokeRate);
        Note("warm_smoke_off " + id);
    }

    private static void CheckSmokeAsset(string asset)
    {
        long handle = maddox.rts.WSFS.open(asset, 0);
        if (handle < 0)
            throw new FileNotFoundException("Missing firelit smoke dependency " + asset);
        maddox.rts.WSFS.close(handle);
    }

    private void BlendWarmSmoke(WarmPlume plume, float smokeScale, double brightness)
    {
        // At most two profiles emit at once. Higher profiles keep their colour later into the same ascent.
        double reach = plume.Glow * (WarmSmokeAssets.Length - 1);
        for (int i = 0; i < WarmSmokeAssets.Length; i++)
        {
            float amount = (float)(brightness * Math.Max(0, 1 - Math.Abs(reach - i)));
            object owner = plume.Owners[i];
            var emitter = owner == null ? null : (WEff3D)particle.GetValue(owner);
            if (emitter == null)
            {
                if (amount < 0.005f)
                    continue;
                string asset = WarmSmokeAssets[i];
                owner = createEffect.Invoke(null, new object[] { plume.Origin, smokeScale, asset, -1.0, true });
                emitter = owner == null ? null : (WEff3D)particle.GetValue(owner);
                if (emitter == null)
                    throw new InvalidOperationException("The profile smoke effect did not create a particle system.");
                plume.Owners[i] = owner;
                Note("warm_smoke_asset " + asset);
            }
            emitter.setIntesity(amount);
        }
    }

    private void SetLowerSmokeRate(string id, float[] rate)
    {
        object owner;
        if (effects.TryGetValue(id, out owner))
        {
            var emitter = (WEff3D)particle.GetValue(owner);
            if (emitter != null)
                emitter.changeParam("Smoke0", EffectParameterName.ParticlesPerSec, rate);
        }
    }

    private readonly Dictionary<WEff3D, float> warmSmokeProbeStrength = new Dictionary<WEff3D, float>();
    private readonly List<WEff3D> pausedProbeEffects = new List<WEff3D>();

    private void CheckWarmSmoke(double now)
    {
        string path = Path.Combine(Folder, session + ".smoke.txt");
        if (!File.Exists(path) || warmSmokeFailed)
            return;
        string line = File.ReadAllText(path).Trim();
        if (line.Length > 64 || line == lastWarmSmokeCommand)
            return;
        string[] request = line.Split(' ');
        long serial;
        if (request.Length != 2 || !Int64.TryParse(request[0], out serial))
            return;
        string command = request[1];
        if (command == "seed")
        {
            lastWarmSmokeCommand = line;
            if (!warmSmokeFixtureStarted)
            {
                warmSmokeFixtureStarted = true;
                foreach (var point in new[] {
                    Tuple.Create(149530, 274674), Tuple.Create(149550, 274674), Tuple.Create(149550, 274654),
                    Tuple.Create(149110, 274274), Tuple.Create(149130, 274274), Tuple.Create(149130, 274254),
                    Tuple.Create(149750, 274194), Tuple.Create(149770, 274194), Tuple.Create(149770, 274174)
                })
                    Record(String.Format(Invariant, "ignition\t{0}\t{1}", point.Item1, point.Item2));
                Note("warm_smoke_fixture_started");
            }
            return;
        }
        if (command != "hold-on" && command != "hold-off" && command != "resume")
            return;
        lastWarmSmokeCommand = line;
        if (command == "resume")
        {
            foreach (var emitter in pausedProbeEffects)
                emitter.pause(false);
            pausedProbeEffects.Clear();
            warmSmokeHeld = false;
            warmSmokeProbeStrength.Clear();
        }
        else if (warmSmokeHeld || warmSmoke.Count != 0)
        {
            if (!warmSmokeHeld)
            {
                // Hold the stock flames and dark smoke at the same instant for the image comparison.
                foreach (object owner in effects.Values)
                {
                    var emitter = (WEff3D)particle.GetValue(owner);
                    if (emitter != null && !emitter.isPaused())
                    {
                        emitter.pause(true);
                        pausedProbeEffects.Add(emitter);
                    }
                }
                foreach (var plume in warmSmoke.Values)
                {
                    foreach (object owner in plume.Owners)
                    {
                        var emitter = owner == null ? null : (WEff3D)particle.GetValue(owner);
                        if (emitter != null)
                            warmSmokeProbeStrength.Add(emitter, emitter.getIntesity());
                    }
                }
                warmSmokeHeld = true;
            }
            foreach (var point in warmSmokeProbeStrength)
                point.Key.setIntesity(command == "hold-on" ? point.Value : 0f);
        }
        double utc = (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        Note(String.Format(Invariant, "warm_smoke_probe {0} {1} {2:F6} {3:F6}",
            command, warmSmoke.Count, now, utc));
    }
}
