public partial class Mission
{
    // These are the named emitters in BuildingFireBig.eff on the inspected Steam build.
    private static readonly string[] SmokeSections = { "SmokeBalls", "Smoke0", "Smoke3", "Smoke4" };
    private static readonly string[] FlameSections = { "FireStat", "FireBallStat", "FireFar" };
    private static readonly float[] NoEmission = { 0f };

    private void SeparateCityEffect(object effect, bool smokeOnly)
    {
        try
        {
            var emitter = (WEff3D)particle.GetValue(effect);
            foreach (string section in smokeOnly ? FlameSections : SmokeSections)
                emitter.changeParam(section, EffectParameterName.ParticlesPerSec, NoEmission);
        }
        catch
        {
            finishEffect.Invoke(null, new[] { effect });
            throw;
        }
    }
}
