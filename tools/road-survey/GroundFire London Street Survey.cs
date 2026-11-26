using System;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using maddox.GP;
using maddox.game;
using maddox.game.world;

public partial class Mission : AMission
{
    private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
    private static readonly string Output = Path.Combine(Environment.GetFolderPath(
        Environment.SpecialFolder.LocalApplicationData), "GroundFireHawkinge", "london-street-survey.tsv");
    private void Note(string text) { File.AppendAllText(Output, text + Environment.NewLine); }

    private int sample;
    private bool complete;
    private IRecalcPathParams[] paths;
    private static readonly Point2d[][] Requests = {
        new[] { new Point2d(148992, 274230), new Point2d(149112, 274225) },
        new[] { new Point2d(149878, 274600), new Point2d(149758, 274605) },
        new[] { new Point2d(149557, 273583), new Point2d(149551, 273710) },
        new[] { new Point2d(149566, 273489), new Point2d(149554, 273640) },
        new[] { new Point2d(148754, 273330), new Point2d(149554, 273490) },
        new[] { new Point2d(148580, 273465), new Point2d(149496, 273475) },
        new[] { new Point2d(149878, 274600), new Point2d(148992, 274230) },
    };

    public override void OnBattleStarted()
    {
        base.OnBattleStarted();
        File.WriteAllText(Output, "survey\n");
    }

    public override void OnTickGame()
    {
        base.OnTickGame();
        double now = GamePlay.gpTime().tickCounter() * GamePlay.gpTime().tickLen();
        SelectRaidCamera(now);
        if (complete || now < 18 || GamePlay.gpPlayer() == null)
            return;
        try
        {
            if (paths == null)
            {
                paths = new IRecalcPathParams[Requests.Length];
                for (int i = 0; i < Requests.Length; ++i)
                {
                    var pair = Requests[i];
                    paths[i] = GamePlay.gpFindPath(pair[0], 1, pair[1], 1, PathType.GROUND, 1);
                    Note(String.Format(Invariant, "request\t{0}\t{1}", i, paths[i] == null ? "null" : paths[i].State.ToString()));
                }
            }
            var lines = new StringBuilder();
            const int width = 321, height = 356;
            for (int end = Math.Min(width * height, sample + 350); sample < end; ++sample)
            {
                int x = 148420 + 5 * (sample % width), y = 273220 + 5 * (sample / width);
                lines.AppendFormat(Invariant, "land\t{0}\t{1}\t{2}\n", x, y, (int)GamePlay.gpLandType(x, y));
            }
            if (lines.Length > 0)
                File.AppendAllText(Output, lines.ToString());
            if (sample < width * height || now < 28)
                return;
            for (int i = 0; i < paths.Length; ++i)
            {
                var path = paths[i];
                if (path == null)
                    continue;
                Note(String.Format(Invariant, "result\t{0}\t{1}\t{2:R}", i, path.State, path.Length));
                if (path.State == RecalcPathState.SUCCESS && path.Path != null)
                    foreach (AiWayPoint point in path.Path)
                    {
                        var ground = point as AiGroundWayPoint;
                        Note(String.Format(Invariant, "point\t{0}\t{1:R}\t{2:R}\t{3:R}\t{4:R}",
                            i, point.P.x, point.P.y, point.P.z, ground == null ? 0 : ground.roadWidth));
                    }
            }
            Note("complete");
            complete = true;
        }
        catch (Exception error)
        {
            complete = true;
            Note("error " + error);
        }
    }

    private bool raidCameraAttempted;

    private static MethodInfo BindRaidView(out Type actorType)
    {
        Assembly engine = Assembly.Load("maddox");
        if (engine.ManifestModule.ModuleVersionId != new Guid("8e7a2ac5-43e4-45fc-8ef5-f4e3d36baff3"))
            throw new InvalidOperationException("London camera requires the inspected Steam build.");

        actorType = engine.GetType("B3ik9i8vEcErjO61EnV5pr8xSg_fKyjgLBB2LLZAsCag", true);
        Type view = engine.GetType("fJOaaT0jQJ73cJ6fixjcwm1WB3rBeWFDeVuRzOZRBA2w", true);
        MethodInfo select = view.GetMethod("l0fU4X9NAqoCahbXbk$LwbE", BindingFlags.Public | BindingFlags.Static,
            null, new[] { actorType }, null);
        if (select == null || select.ReturnType != typeof(void))
            throw new MissingMethodException("Unexpected external view selector.");
        return select;
    }

    private static MethodInfo BindRaidActors(Assembly engine, out object namedActors)
    {
        const BindingFlags members = BindingFlags.Public | BindingFlags.NonPublic;
        Type registry = engine.GetType("IN9ja8czYVm8g9Yda3jVhIdZoiD0Iurfl52UO1fGq$WF", true);
        MethodInfo getWorld = registry.GetMethod("ogBa7X8tof8PQ7kD5doXYAg", members | BindingFlags.Static,
            null, Type.EmptyTypes, null);
        FieldInfo byName = getWorld.ReturnType.GetField("HNE0cqGJqxveych4msrLm1E", members | BindingFlags.Instance);
        MethodInfo find = byName.FieldType.GetMethod("QnL8ABDdA9vjIiTAX7$v3Z8", members | BindingFlags.Instance,
            null, new[] { typeof(object) }, null);
        if (find == null || find.ReturnType != typeof(object))
            throw new MissingMethodException("Unexpected actor lookup.");
        namedActors = byName.GetValue(getWorld.Invoke(null, null));
        return find;
    }

    private void SelectRaidCamera(double now)
    {
        if (raidCameraAttempted || now < 12 || GamePlay.gpPlayer() == null)
            return;
        raidCameraAttempted = true;
        try
        {
            Type actorType;
            MethodInfo select = BindRaidView(out actorType);
            Assembly engine = actorType.Assembly;
            Type cameraType = engine.GetType("4UhbWdQ2FZoEglRk6kTMTcM6ThpsX7qpD8e3a$W1QrhN", true);
            if (!actorType.IsAssignableFrom(cameraType))
                throw new MissingMemberException("Unexpected London camera selector.");

            object namedActors;
            MethodInfo find = BindRaidActors(engine, out namedActors);
            foreach (string name in new[] { "0:StaticCamera_0", "1:StaticCamera_0", "StaticCamera_0" })
            {
                object actor = find.Invoke(namedActors, new object[] { name });
                if (!cameraType.IsInstanceOfType(actor))
                    continue;
                select.Invoke(null, new[] { actor });
                Note("raid_camera_selected " + name);
                return;
            }
            Note("raid_camera_missing");
        }
        catch (Exception error)
        {
            Note("raid_camera_error " + error.GetBaseException().Message);
        }
    }
}
