public partial class Mission
{
    private const string LightCarrier = "$core/3do/sfx/smoke/ChimneyBlack.eff";

    private void RemoveDistrictLight(string id)
    {
        object owner = cityLights[id].Owner;
        EndCityLight(id);
        if (particle.GetValue(owner) != null)
            finishEffect.Invoke(null, new[] { owner });
    }

    private void ReconcileDistrictLights(Dictionary<string, Tuple<int, double, double>> desired)
    {
        bool clear = stopped || Now - receivedAt > 15;
        foreach (string id in new List<string>(cityLights.Keys))
        {
            CityLight light = cityLights[id];
            if (!clear && (desired.ContainsKey(id) || light.Strength > 0.025)
                && particle.GetValue(light.Owner) != null)
                continue;
            RemoveDistrictLight(id);
        }

        foreach (string id in new List<string>(desired.Keys))
        {
            if (!id.Contains("_P3_"))
                continue;
            var position = desired[id];
            desired.Remove(id);
            if (clear || cityLightFailed || cityLights.ContainsKey(id) || cityLights.Count >= CityLightBudget)
                continue;
            double? z = CaptureTerrainHeight(position.Item2, position.Item3);
            if (!z.HasValue)
                continue;
            var loc = new Loc(position.Item2, position.Item3, z.Value, 0, 0, 0);
            object owner = createEffect.Invoke(null, new object[] { loc, 1f, LightCarrier, -1.0, true });
            if (owner == null)
                throw new InvalidOperationException("District light carrier could not be created.");
            try
            {
                var emitter = (WEff3D)particle.GetValue(owner);
                if (emitter == null)
                    throw new InvalidOperationException("District light carrier has no draw effect.");
                emitter.changeParam("Smoke0", EffectParameterName.ParticlesPerSec, NoEmission);
                emitter.changeParam("Smoke1", EffectParameterName.ParticlesPerSec, NoEmission);
                TryLightCityFire(id, position.Item1, owner, new Point3d(position.Item2, position.Item3, z.Value));
            }
            finally
            {
                if (!cityLights.ContainsKey(id))
                    finishEffect.Invoke(null, new[] { owner });
            }
        }
    }
}
