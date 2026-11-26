using System;
using System.Globalization;
using System.IO;
using System.Reflection;
using maddox.core;
using maddox.GP;
using maddox.game;
using maddox.game.world;

public class Mission : AMission
{
    private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
    private const string Group = "0_Chief";
    private const string Smoke = "$core/3do/sfx/fire/BuildingFireSmall.eff";
    private string trace;
    private double started;
    private double lastPoll;
    private double? markerZ;
    private double ignitionTime;
    private bool routeLoaded;
    private bool groupReported;
    private bool finishCalled;
    private bool faulted;
    private bool retired;
    private int submission;
    private string bomb;
    private Point3d impact;
    private object emitter;
    private MethodInfo createEffect;
    private MethodInfo finishEffect;
    private FieldInfo emitterField;
    private HawkingeRangeResponse response;

    private double Now { get { return Time.TicksToSecs(Time.tickCounter()) - started; } }

    public override void OnBattleStarted()
    {
        base.OnBattleStarted();
        if (!GamePlay.gpIsServerSingle())
            return;
        started = Time.TicksToSecs(Time.tickCounter());
        lastPoll = -1;
        submission = -1;
        markerZ = null;
        routeLoaded = groupReported = finishCalled = faulted = retired = false;
        bomb = null;
        response = null;
        emitter = null;
        MissionNumberListener = -1;
        try
        {
            string directory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                            "GroundFireHawkinge", "bomb-range");
            Directory.CreateDirectory(directory);
            trace = Path.Combine(directory, Guid.NewGuid().ToString("N") + ".events.tsv");
            BindEffects();
            Note("mission_started", "Hawkinge Bomb Range");
        }
        catch (Exception error)
        {
            Fail(error);
        }
    }

    public override void OnMissionLoaded(int missionNumber)
    {
        base.OnMissionLoaded(missionNumber);
        if (trace != null && missionNumber == submission)
            routeLoaded = true;
    }

    public override void OnBombExplosion(string title, double mass, Point3d pos,
                                         AiDamageInitiator initiator, int eventArgInt)
    {
        base.OnBombExplosion(title, mass, pos, initiator, eventArgInt);
        if (trace == null || faulted)
            return;
        string raw = String.Format(Invariant, "{0} mass_raw={1:R} x={2:F2} y={3:F2} z={4:F2} arg={5}",
                                   title, mass, pos.x, pos.y, pos.z, eventArgInt);
        Note("bomb_callback", raw);
        if (bomb != null)
            return;
        if (!markerZ.HasValue ||
            HawkingeRangeResponse.Distance(pos.x, pos.y, HawkingeRangeResponse.TargetX,
                                          HawkingeRangeResponse.TargetY) > HawkingeRangeResponse.TargetRadius ||
            Math.Abs(pos.z - markerZ.Value) > 20 ||
            Double.IsNaN(pos.x) || Double.IsNaN(pos.y) || Double.IsNaN(pos.z))
        {
            Note("bomb_outside_range", raw);
            Hud("Range miss. Aim at the tents northwest of Hawkinge.");
            return;
        }
        string type = HawkingeRangeResponse.BombFromTitle(title);
        string aircraft = AircraftBomb(initiator == null ? null : initiator.Actor);
        if (aircraft.Length == 0 && initiator != null && initiator.Player != null)
            aircraft = AircraftBomb(initiator.Player.Place());
        if (type.Length == 0)
            type = aircraft;
        if (type.Length == 0 || (aircraft.Length > 0 && aircraft != type))
        {
            Note("bomb_type_unresolved", raw + " aircraft_fit=" + aircraft);
            Hud("Range impact recorded. The bomb type could not be matched.");
            return;
        }
        bomb = type;
        impact = pos;
        Note("bomb_accepted", type + " " + raw);
    }

    public override void OnTickGame()
    {
        base.OnTickGame();
        if (trace == null || faulted || retired)
            return;
        double seconds = Now;
        if (seconds < lastPoll + 1)
            return;
        double dt = seconds - lastPoll;
        lastPoll = seconds;
        try
        {
            if (!markerZ.HasValue)
            {
                FindRangeMarker();
                return;
            }
            if (bomb == null)
                return;
            if (response == null)
            {
                StartFire(seconds);
                return;
            }
            if (finishCalled)
            {
                if (emitterField.GetValue(emitter) == null)
                {
                    retired = true;
                    emitter = null;
                    Note("emitter_retired", bomb);
                    Hud("Smoke cleared. Restart and select the other loadout to compare.");
                }
                return;
            }

            AiGroundActor pump = FindPump();
            string oldStage = response.Stage;
            if (pump == null)
                response.Advance(dt, null, 0);
            else
            {
                Point3d p = pump.Pos();
                response.Advance(dt, p.x, p.y);
                Note("pump", String.Format(Invariant, "{0} {1:F2} {2:F2} {3} litres={4:F1}",
                                           pump.Name(), p.x, p.y, response.Stage, response.Pumped));
            }
            if (oldStage != response.Stage)
                DescribeStage();
            if (seconds - ignitionTime >= 160 && seconds - ignitionTime < 161.5 &&
                (response.Stage == "en_route" || response.Stage == "out_of_reach"))
            {
                Note("crew_not_in_position", "submission_loaded=" + routeLoaded);
                Hud("Crew not in position. No water has been applied.");
            }
        }
        catch (Exception error)
        {
            Fail(error);
        }
    }

    private static string AircraftBomb(AiActor actor)
    {
        if (actor == null)
            return "";
        string name = actor.Name() ?? "";
        if (actor.Group() != null)
            name += " " + actor.Group().Name();
        if (name.IndexOf("BoB_LW_ErprGr210F", StringComparison.OrdinalIgnoreCase) >= 0)
            return "SC50";
        if (name.IndexOf("BoB_LW_JG54_III", StringComparison.OrdinalIgnoreCase) >= 0)
            return "SC250";
        return "";
    }

    private void FindRangeMarker()
    {
        double x = HawkingeRangeResponse.TargetX, y = HawkingeRangeResponse.TargetY;
        GroundStationary[] items = GamePlay.gpGroundStationarys(x, y, 5);
        if (items == null)
            return;
        foreach (GroundStationary item in items)
        {
            if (item == null || item.Name == null ||
                !(item.Name == "Static7101" || item.Name.EndsWith(":Static7101", StringComparison.Ordinal)))
                continue;
            Point3d p = item.pos;
            if (HawkingeRangeResponse.Distance(p.x, p.y, x, y) > 2 ||
                Double.IsNaN(p.z) || Double.IsInfinity(p.z))
                continue;
            markerZ = p.z;
            Note("range_armed", "height=" + p.z.ToString("F2", Invariant));
            Hud("Hawkinge range armed. Look for the tents northwest of the airfield.");
            return;
        }
    }

    private void StartFire(double seconds)
    {
        float size = bomb == "SC50" ? 1f : 1.35f;
        emitter = createEffect.Invoke(null, new object[] { new Loc(impact.x, impact.y, impact.z, 0, 0, 0),
                                                          size, Smoke, -1.0, true });
        if (emitter == null || emitterField.GetValue(emitter) == null)
            throw new InvalidOperationException("CloD did not return the range fire emitter.");
        response = new HawkingeRangeResponse(bomb, impact.x, impact.y);
        ignitionTime = seconds;
        Dispatch();
        Hud(bomb + " impact. Fire detected. Emergency column dispatched.");
    }

    private void Dispatch()
    {
        ISectionFile section = GamePlay.gpCreateSectionFile();
        section.add("MAIN", "MAP", "Land$English_Channel_1940");
        section.add("Chiefs", Group, "Vehicle.GB_Emrg_Column gb");
        // Shipped Hawkinge attack campaign, 3_Chief_Road.
        string road = Group + "_Road";
        section.add(road, "234673.92", "232407.78 38.40 0 4 6.11");
        section.add(road, "234656.00", "232544.00 20.00");
        section.add(road, "234592.00", "232608.00 20.00");
        section.add(road, "234460.75", "232726.98 38.40");
        submission = GamePlay.gpNextMissionNumber();
        GamePlay.gpPostMissionLoad(section);
        Note("dispatch", submission.ToString(Invariant));
    }

    private AiGroundActor FindPump()
    {
        if (!routeLoaded)
            return null;
        string name = submission.ToString(Invariant) + ":" + Group;
        AiGroundGroup group = GamePlay.gpActorByName(name) as AiGroundGroup;
        if (group == null)
        {
            AiGroundGroup[] groups = GamePlay.gpGroundGroups(1);
            if (groups == null)
                return null;
            foreach (AiGroundGroup candidate in groups)
            {
                // This range has no other ground groups.
                if (candidate != null && candidate.IsValid() &&
                    (candidate.Name() == name || (groups.Length == 1 && candidate.ID() == Group)))
                {
                    group = candidate;
                    break;
                }
            }
        }
        AiActor[] items = group == null || !group.IsValid() ? null : group.GetItems();
        if (items == null)
            return null;
        AiGroundActor nearest = null;
        double nearestDistance = Double.PositiveInfinity;
        foreach (AiActor item in items)
        {
            AiGroundActor vehicle = item as AiGroundActor;
            if (vehicle == null || !vehicle.IsValid() || !vehicle.IsAlive())
                continue;
            string type = vehicle.InternalTypeName() ?? "";
            if (!groupReported)
                Note("vehicle_identified", vehicle.Name() + " " + type);
            if (type.IndexOf("Austin_K2_ATV", StringComparison.OrdinalIgnoreCase) < 0)
                continue;
            Point3d p = vehicle.Pos();
            double distance = HawkingeRangeResponse.Distance(p.x, p.y, HawkingeRangeResponse.StagingX,
                                                              HawkingeRangeResponse.StagingY);
            if (distance < nearestDistance)
            {
                nearest = vehicle;
                nearestDistance = distance;
            }
        }
        groupReported = items.Length > 0;
        return nearest;
    }

    private void DescribeStage()
    {
        Note("response_" + response.Stage, "pumped_l=" + response.Pumped.ToString("F1", Invariant));
        switch (response.Stage)
        {
            case "setting_up":
                Hud("Fire crew has arrived and is setting up the pump.");
                break;
            case "pumping":
                Hud("Water on the fire.");
                break;
            case "knocked_down":
                finishEffect.Invoke(null, new[] { emitter });
                finishCalled = true;
                Note("emitter_finish", "pumped_l=" + response.Pumped.ToString("F1", Invariant));
                Hud("Fire knocked down. The remaining smoke will dissipate.");
                break;
            case "out_of_reach":
                Hud("Fire crew has stopped. The impact is outside hose reach.");
                break;
            case "water_exhausted":
                Hud("The crew has exhausted its water supply.");
                break;
        }
    }

    private void BindEffects()
    {
        Assembly engine = Array.Find(AppDomain.CurrentDomain.GetAssemblies(), a => a.GetName().Name == "maddox");
        if (engine == null || engine.ManifestModule.ModuleVersionId != new Guid("8e7a2ac5-43e4-45fc-8ef5-f4e3d36baff3") ||
            typeof(WEff3D).Module.ModuleVersionId != new Guid("7cabe1d9-b513-4d66-82fb-8d66589e5f09"))
            throw new InvalidOperationException("CloD effect assembly differs from the Hawkinge-tested build.");
        Type actor = engine.GetType("yfF_qZl67WlmNS9coEvP0_bSaSCDSqkcGRjRO0s$kmQH", true);
        const BindingFlags methods = BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly;
        createEffect = actor.GetMethod("ZNpynOtOqVuCJyfuWKwJwy0", methods, null,
            new[] { typeof(Loc).MakeByRefType(), typeof(float), typeof(string), typeof(double), typeof(bool) }, null);
        finishEffect = actor.GetMethod("F6mh8rjUa2GGR$0BBCl7kQA", methods, null, new[] { actor }, null);
        emitterField = actor.GetField("JfGsspZfCQ8TatQl98$8kEs",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
        if (createEffect == null || createEffect.ReturnType != actor ||
            finishEffect == null || finishEffect.ReturnType != typeof(void) ||
            emitterField == null || emitterField.FieldType != typeof(WEff3D))
            throw new MissingMemberException("Unexpected effect actor signature.");
    }

    private void Hud(string message)
    {
        GamePlay.gpHUDLogCenter(message);
    }

    private void Note(string action, string detail)
    {
        if (trace == null)
            return;
        string safe = detail.Replace("\r", " ").Replace("\n", " ").Replace("\t", " ");
        try
        {
            File.AppendAllText(trace, String.Format(Invariant, "{0:F3}\t{1}\t{2}\r\n", Now, action, safe));
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    private void Fail(Exception error)
    {
        faulted = true;
        Note("probe_error", error.GetBaseException().Message);
        Hud("Hawkinge range script stopped. See the range log.");
    }

    public override void OnBattleStoped()
    {
        Note("mission_stopped", bomb ?? "no bomb accepted");
        trace = null;
        base.OnBattleStoped();
    }
}
