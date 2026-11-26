public partial class Mission
{
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
