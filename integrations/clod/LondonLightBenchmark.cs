public partial class Mission
{
    private bool lightBenchFrozen;
    private string lastLightBenchCommand;
    private List<string> lightBenchIds;
    private Dictionary<string, Tuple<int, double, double>> lightBenchPositions;
    private Dictionary<string, double> lightBenchStrengths;

    private void CheckLightBenchmark(double now)
    {
        string path = Path.Combine(Folder, session + ".lights.txt");
        if (!File.Exists(path))
            return;
        string line = File.ReadAllText(path).Trim();
        if (line.Length > 64 || line == lastLightBenchCommand)
            return;
        string[] words = line.Split(' ');
        long request;
        if (words.Length < 2 || !Int64.TryParse(words[0], out request))
            return;
        lastLightBenchCommand = line;
        if (words[1] == "freeze")
        {
            if (lightBenchFrozen || cityLights.Count != CityLightBudget)
            {
                LogLightBenchmark("wait", cityLights.Count);
                return;
            }
            lightBenchPositions = new Dictionary<string, Tuple<int, double, double>>();
            lightBenchStrengths = new Dictionary<string, double>();
            lightBenchIds = new List<string>(cityLights.Keys);
            lightBenchIds.Sort(delegate(string a, string b)
            {
                int order = cityLights[b].Strength.CompareTo(cityLights[a].Strength);
                return order != 0 ? order : String.CompareOrdinal(a, b);
            });
            foreach (string id in lightBenchIds)
            {
                CityLight light = cityLights[id];
                lightBenchPositions.Add(id, Tuple.Create(3, light.Anchor.x, light.Anchor.y));
                lightBenchStrengths.Add(id, light.Strength);
            }
            lightBenchFrozen = true;
            SetBenchmarkEmission(-1);
            LogLightBenchmark("freeze", cityLights.Count);
            for (int i = 0; i < lightBenchIds.Count; ++i)
            {
                CityLight light = cityLights[lightBenchIds[i]];
                Note(String.Format(Invariant, "light_bench_anchor {0} {1} {2:F3} {3:F3} {4:F3} {5:F5}",
                    i, lightBenchIds[i], light.Anchor.x, light.Anchor.y, light.Anchor.z, light.Strength));
            }
            return;
        }
        if (!lightBenchFrozen)
            return;
        if (words[1] == "resume")
        {
            lightBenchFrozen = false;
            LogLightBenchmark("resume", cityLights.Count);
            return;
        }
        if (words[1] == "12" || words[1] == "24")
        {
            int budget = Int32.Parse(words[1], Invariant);
            var selected = new Dictionary<string, Tuple<int, double, double>>();
            foreach (string id in lightBenchIds.GetRange(0, budget))
                selected.Add(id, lightBenchPositions[id]);
            foreach (string id in new List<string>(cityLights.Keys))
                if (!selected.ContainsKey(id))
                    RemoveDistrictLight(id);
            receivedAt = now;
            ReconcileDistrictLights(selected);
            SetBenchmarkEmission(-1);
            LogLightBenchmark("cap", cityLights.Count);
            return;
        }
        int index;
        if (words[1] == "full" || (words.Length == 3 && words[1] == "probe" &&
            Int32.TryParse(words[2], out index) && index >= 0 && index < lightBenchIds.Count))
        {
            index = words[1] == "full" ? -1 : Int32.Parse(words[2], Invariant);
            SetBenchmarkEmission(index);
            LogLightBenchmark("probe", index);
        }
    }

    private void SetBenchmarkEmission(int hidden)
    {
        for (int i = 0; i < lightBenchIds.Count; ++i)
        {
            CityLight light;
            string id = lightBenchIds[i];
            if (!cityLights.TryGetValue(id, out light))
                continue;
            light.Strength = lightBenchStrengths[id];
            float green, intensity;
            ApplyCityLight(light.Light, light.Phase, i == hidden ? 0 : light.Strength, 0, out green, out intensity);
        }
    }

    private void LogLightBenchmark(string stage, int value)
    {
        double utc = (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        Note(String.Format(Invariant, "light_bench_{0} {1} {2:F6} {3:F6}", stage, value, Now, utc));
    }
}
