// Offline compile-checked input probe; runtime delivery/clock/coordinates untested.
// Merge these callbacks into ONE root mission script; do not load duplicate probes.
// Output goes through CloD's log API. This source starts no external process,
// opens no socket, places no effect, and applies no damage.
using System;
using System.Globalization;
using System.Text;
using maddox.GP;
using maddox.game;
using maddox.game.world;

public class Mission : AMission
{
    private string session = Guid.NewGuid().ToString("N");
    private long sequence = 0;
    private double lastClock = Double.NegativeInfinity;

    private static string Number(double value)
    {
        return Double.IsNaN(value) || Double.IsInfinity(value) ? "null" :
            value.ToString("R", CultureInfo.InvariantCulture);
    }

    private static string Quote(string value)
    {
        StringBuilder b = new StringBuilder("\"");
        foreach (char c in value ?? "")
        {
            if (c == '"') b.Append("\\\"");
            else if (c == '\\') b.Append("\\\\");
            else if (c < 32) b.Append("\\u" + ((int)c).ToString("x4"));
            else b.Append(c);
        }
        return b.Append('"').ToString();
    }

    private string Prefix(string kind)
    {
        return "{\"schema\":1,\"source\":\"clod-probe\",\"session\":" + Quote(session) +
            ",\"kind\":" + Quote(kind) + ",\"sequence\":" + (++sequence).ToString(CultureInfo.InvariantCulture) +
            ",\"mission_number\":" + MissionNumber.ToString(CultureInfo.InvariantCulture) +
            ",\"tick\":" + Time.tickCounter().ToString(CultureInfo.InvariantCulture) +
            ",\"clock_seconds_api\":" + Number(Time.TicksToSecs(Time.tickCounter()));
    }

    private void Emit(string json)
    {
        GamePlay.gpLogServer("GROUNDFIRE " + json);
    }

    private static string Position(Point3d pos)
    {
        return "{\"x\":" + Number(pos.x) + ",\"y\":" + Number(pos.y) + ",\"z\":" + Number(pos.z) + "}";
    }

    public override void OnBattleStarted()
    {
        base.OnBattleStarted();
        session = Guid.NewGuid().ToString("N");
        sequence = 0;
        lastClock = Double.NegativeInfinity;
        MissionNumberListener = -1;
        Emit(Prefix("battle_started") + ",\"coordinates\":\"raw-game-xyz-unregistered\"}");
    }

    public override void OnTickGame()
    {
        base.OnTickGame();
        double now = Time.TicksToSecs(Time.tickCounter());
        if (now < lastClock || now - lastClock >= 2.0)
        {
            lastClock = now;
            Emit(Prefix("clock") + "}");
        }
    }

    public override void OnBombExplosion(string title, double mass, Point3d pos,
                                         AiDamageInitiator initiator, int eventArgInt)
    {
        base.OnBombExplosion(title, mass, pos, initiator, eventArgInt);
        Emit(Prefix("bomb_explosion") + ",\"title\":" + Quote(title) +
             ",\"mass_raw\":" + Number(mass) + ",\"position_raw\":" + Position(pos) + ",\"event_arg\":" +
             eventArgInt.ToString(CultureInfo.InvariantCulture) + "}");
    }

    public override void OnStationaryKilled(int missionNumber, GroundStationary stationary,
                                            AiDamageInitiator initiator, int eventArgInt)
    {
        base.OnStationaryKilled(missionNumber, stationary, initiator, eventArgInt);
        if (stationary == null)
            return;
        Emit(Prefix("stationary_killed") + ",\"name\":" + Quote(stationary.Name) +
             ",\"title\":" + Quote(stationary.Title) + ",\"category\":" + Quote(stationary.Category) +
             ",\"target_mission_number\":" + missionNumber.ToString(CultureInfo.InvariantCulture) +
             ",\"position_raw\":" + Position(stationary.pos) +
             ",\"event_arg\":" + eventArgInt.ToString(CultureInfo.InvariantCulture) + "}");
    }

    public override void OnBuildingKilled(string title, Point3d pos,
                                          AiDamageInitiator initiator, int eventArgInt)
    {
        base.OnBuildingKilled(title, pos, initiator, eventArgInt);
        Emit(Prefix("building_killed") + ",\"title\":" + Quote(title) +
             ",\"position_raw\":" + Position(pos) +
             ",\"event_arg\":" + eventArgInt.ToString(CultureInfo.InvariantCulture) + "}");
    }
}
