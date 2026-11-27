using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using maddox.core;
using maddox.GP;
using maddox.game;
using maddox.game.world;

public partial class Mission : AMission
{
    private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
    private static readonly string Folder = Path.Combine(Environment.GetFolderPath(
        Environment.SpecialFolder.LocalApplicationData), "GroundFireHawkinge", "channel-fire");
    private const string Dataset = "__DATASET__";
    private const double EastMax = __EAST_MAX__, NorthMax = __NORTH_MAX__;
    private const int PlumeBudget = 24, TotalEffectBudget = 64;
    private const string Asset = "$core/3do/sfx/fire/BuildingFireBig.eff";
    private static readonly string[] Sites = { __SITE_NAMES__ };
    private static readonly Point2d[] CameraPositions = { __CAMERA_XY__ };

    private readonly Dictionary<string, object> effects = new Dictionary<string, object>();
    private readonly List<object> fading = new List<object>();
    private MethodInfo createEffect;
    private MethodInfo finishEffect;
    private FieldInfo particle;
    private string session;
    private int sequence;
    private long version;
    private double start, pollAt, lastFrameAt;
    private bool stopped, visualFault, cameraFault;
    private Player menuPlayer;
    private int camera = -1;
    private int requestedCamera;
    private double Now { get { return Time.TicksToSecs(Time.tickCounter()) - start; } }

    public override void OnBattleStarted()
    {
        base.OnBattleStarted();
        if (!GamePlay.gpIsServerSingle())
            return;
        start = Time.TicksToSecs(Time.tickCounter());
        Directory.CreateDirectory(Folder);
        session = Guid.NewGuid().ToString("N");
        Record("init\t" + Dataset + "\t15\t__WIND_EAST__\t__WIND_NORTH__");
        string pointer = Path.Combine(Folder, "active.txt");
        string temporary = Path.Combine(Folder, session + ".ready");
        File.WriteAllText(temporary, session);
        if (File.Exists(pointer))
            File.Replace(temporary, pointer, null);
        else
            File.Move(temporary, pointer);
    }

    public override void OnBombExplosion(string title, double mass, Point3d pos,
                                         AiDamageInitiator initiator, int eventArgInt)
    {
        base.OnBombExplosion(title, mass, pos, initiator, eventArgInt);
        if (session == null || stopped)
            return;
        try
        {
            string id = (title ?? "").ToUpperInvariant().Replace("_", "").Replace("-", "").Replace(" ", "");
            Match weapon = Regex.Match(id, "SC(?:1000|500|250|50)(?![0-9])");
            double? ground = Inside(pos.x, pos.y) && Finite(pos.z) ? CaptureTerrainHeight(pos.x, pos.y) : null;
            AiActor actor = initiator == null ? null : initiator.Actor;
            AiGroup group = actor == null ? null : actor.Group();
            string name = group == null ? (actor == null ? "" : actor.Name()) : group.Name();
            name = Clean(name);
            bool accepted = weapon.Success && ground.HasValue && Math.Abs(pos.z - ground.Value) <= 20;
            Note(String.Format(Invariant, "bomb t={0:F6} title={1} type={2} mass={3:R} x={4:R} y={5:R} z={6:R} ground={7} group={8} accepted={9}",
                Now, Clean(title), weapon.Value, mass, pos.x, pos.y, pos.z, ground.HasValue ? ground.Value.ToString("R", Invariant) : "unknown",
                name, accepted));
            if (accepted)
                Record(String.Format(Invariant, "bomb\t{0}\t{1:R}\t{2:R}\t{3:R}\t{4:R}\t{5}",
                    weapon.Value, pos.x, pos.y, pos.z, ground.Value, name));
        }
        catch (Exception error)
        {
            Note("bomb_read_error " + error.GetBaseException().Message);
        }
    }

    public override void OnOrderMissionMenuSelected(Player player, int id, int item)
    {
        base.OnOrderMissionMenuSelected(player, id, item);
        if (session != null && !stopped && player == menuPlayer && id == 0 && item >= 1 && item <= Sites.Length)
            requestedCamera = item - 1;
    }

    public override void OnTickGame()
    {
        base.OnTickGame();
        if (session == null || stopped || Now < pollAt)
            return;
        double now = Now;
        pollAt = now + 0.5;
        try
        {
            Player player = GamePlay.gpPlayer();
            if (player != null && player != menuPlayer)
            {
                menuPlayer = player;
                try { GamePlay.gpSetOrderMissionMenu(player, false, 0, Sites, new bool[Sites.Length]); }
                catch (Exception error) { Note("mission_menu_unavailable " + error.GetBaseException().Message); }
            }
            SelectCamera(now, player);
            // The report and projector share the observer used for the captured view.
            Point2d observer = CameraPositions[requestedCamera];
            double utc = (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
            Record(String.Format(Invariant, "clock\t{0:R}\t{1:R}\t{2}\t{3:F6}",
                observer.x, observer.y, Sites[requestedCamera], utc));
            if (!visualFault)
                Render(now);
        }
        catch (IOException)
        {
            // A bridge frame may be between writes.
        }
        catch (Exception error)
        {
            visualFault = true;
            Note("channel_visual_error " + error.GetBaseException().Message);
        }
    }

    private void SelectCamera(double now, Player player)
    {
        if (cameraFault || now < 12 || player == null)
            return;
        string path = Path.Combine(Folder, session + ".view.txt");
        if (File.Exists(path))
        {
            int selected;
            if (Int32.TryParse(File.ReadAllText(path).Trim(), out selected) && selected >= 0 && selected < Sites.Length)
                requestedCamera = selected;
        }
        if (camera == requestedCamera)
            return;
        try
        {
            Type actorType;
            MethodInfo select = BindRaidView(out actorType);
            Type cameraType = actorType.Assembly.GetType("4UhbWdQ2FZoEglRk6kTMTcM6ThpsX7qpD8e3a$W1QrhN", true);
            if (!actorType.IsAssignableFrom(cameraType))
                throw new MissingMemberException("Unexpected static camera type");
            object registry;
            MethodInfo find = BindRaidActors(actorType.Assembly, out registry);
            string name = "StaticCamera_" + requestedCamera.ToString(Invariant);
            foreach (string prefix in new[] { "0:", "1:", "" })
            {
                object actor = find.Invoke(registry, new object[] { prefix + name });
                if (!cameraType.IsInstanceOfType(actor))
                    continue;
                select.Invoke(null, new[] { actor });
                camera = requestedCamera;
                Note(String.Format(Invariant, "camera_selected {0} {1:F6} {2}", Sites[camera], Now, prefix + name));
                return;
            }
        }
        catch (Exception error)
        {
            cameraFault = true;
            Note("channel_camera_error " + error.GetBaseException().Message);
        }
    }

    private void Render(double now)
    {
        if (effects.Count > 0 && now - lastFrameAt > 15)
            Apply(new Dictionary<string, Point2d>());
        string path = Path.Combine(Folder, session + ".plumes.tsv");
        if (!File.Exists(path))
            return;
        string[] lines = File.ReadAllLines(path);
        if (lines.Length == 0 || lines.Length > PlumeBudget + 1)
            return;
        string[] header = lines[0].Split('\t');
        long next;
        double stamp;
        if (header.Length != 3 || header[0] != session || !Int64.TryParse(header[1], out next)
            || next <= version || !Parse(header[2], out stamp) || stamp > now + 0.01 || now - stamp > 15)
            return;
        var desired = new Dictionary<string, Point2d>();
        for (int i = 1; i < lines.Length; ++i)
        {
            string[] row = lines[i].Split('\t');
            double x, y;
            if (row.Length != 4 || !Regex.IsMatch(row[0], @"^[FS]\d+_\d+_\d+$") ||
                row[1].Length != 1 || row[0][0] != row[1][0] || desired.ContainsKey(row[0]) ||
                !Parse(row[2], out x) || !Parse(row[3], out y) || !Inside(x, y))
                return;
            desired.Add(row[0], new Point2d(x, y));
        }
        Apply(desired);
        version = next;
        lastFrameAt = now;
    }

    private void Apply(Dictionary<string, Point2d> desired)
    {
        if (desired.Count == 0 && effects.Count == 0)
            return;
        if (createEffect == null)
            BindEffects();
        fading.RemoveAll(actor => particle.GetValue(actor) == null);
        foreach (string key in new List<string>(effects.Keys))
        {
            if (desired.ContainsKey(key))
                continue;
            object actor = effects[key];
            finishEffect.Invoke(null, new[] { actor });
            fading.Add(actor);
            effects.Remove(key);
        }
        foreach (var item in desired)
        {
            if (effects.ContainsKey(item.Key) || effects.Count + fading.Count >= TotalEffectBudget)
                continue;
            Point2d p = item.Value;
            double? z = CaptureTerrainHeight(p.x, p.y);
            if (!z.HasValue)
                continue;
            bool smoke = item.Key[0] == 'S';
            var location = new Loc(p.x, p.y, z.Value, 0, 0, 0);
            object actor = createEffect.Invoke(null, new object[] { location, smoke ? 4f : 3f, Asset, -1.0, true });
            if (actor == null || particle.GetValue(actor) == null)
                throw new InvalidOperationException("Ground fire factory returned no emitter");
            SeparateCityEffect(actor, smoke);
            effects.Add(item.Key, actor);
            Note(String.Format(Invariant, "effect_created {0} {1:F6} {2:F3} {3:F3}", item.Key, Now, p.x, p.y));
        }
    }

    public override void OnBattleStoped()
    {
        if (session != null && !stopped)
        {
            stopped = true;
            try { Record("stop"); }
            finally
            {
                try { Apply(new Dictionary<string, Point2d>()); }
                catch (Exception error) { Note("effect_cleanup_error " + error.GetBaseException().Message); }
            }
        }
        base.OnBattleStoped();
    }

    private void Record(string data)
    {
        File.AppendAllText(Path.Combine(Folder, session + ".events.tsv"),
            String.Format(Invariant, "{0}\t{1:F6}\t{2}\n", sequence + 1, Now, data));
        sequence++;
    }

    private void Note(string line)
    {
        try { File.AppendAllText(Path.Combine(Folder, session + ".flight.log"), Clean(line) + "\n"); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    private static string Clean(string text)
    {
        return (text ?? "").Replace('\t', ' ').Replace('\r', ' ').Replace('\n', ' ');
    }

    private static bool Inside(double east, double north)
    {
        return east >= 0 && east < EastMax && north >= 0 && north < NorthMax;
    }

    private static bool Parse(string text, out double value)
    {
        return Double.TryParse(text, NumberStyles.Float, Invariant, out value) && Finite(value);
    }

    private static bool Finite(double value) { return !Double.IsNaN(value) && !Double.IsInfinity(value); }

__HEIGHT_BINDING__
__EFFECT_BINDING__
__EMITTER_FILTER__
__CAMERA_BINDINGS__
}
