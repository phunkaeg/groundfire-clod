import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations/clod"))
from fire_lab import (FRONT_BUDGET, FRONT_SPACING_M, LONDON_ATTACK_CENTER, LONDON_CITY_RAID_CENTER,
                      LONDON_CENTER, LONDON_TEMP_C, LONDON_WIND,
                      DistrictLightProjector, FireFrontProjector, Lab, PLOTS, SIZE, WOOD_EDGE_CENTER, WOOD_EDGE_ROAD,
                      WoodlandTerrain, london_ignitions)
from firesim.core import FUELS, FireSim
from firesim.sparse import SparseFireSim
from render_capture_map import read_raid_impacts


def new_lab():
    lab = Lab()
    lab.handle(0, "init", ["15", "2", "0"])
    return lab


class FireLabTests(unittest.TestCase):
    def test_raid_impact_overlay_reads_real_in_plot_explosions(self):
        with TemporaryDirectory() as directory:
            log = Path(directory) / "raid.flight.log"
            log.write_text(
                "bomb title=SC 50 mass_raw=50 x=149004.4 y=273785.7 z=15 type=SC50 fit= "
                "t=249.15 ground_z=15 agl=0 accepted=True\n"
                "bomb title=SC 50 mass_raw=50 x=149113.2 y=273883.1 z=15 type=SC50 fit= "
                "t=247.26 ground_z=15 agl=0 accepted=True\n"
                "bomb title=SC 50 mass_raw=50 x=147000 y=271000 z=15 type=SC50 fit= "
                "t=248.31 ground_z=unknown agl=unknown accepted=False\n",
                encoding="ascii",
            )
            self.assertEqual(read_raid_impacts(log), [
                (247.26, 149113.2, 273883.1),
                (249.15, 149004.4, 273785.7),
            ])

    def test_warm_smoke_particles_darken_as_they_expand(self):
        effect = (Path(__file__).resolve().parents[1] / "integrations/clod/WarmSmoke.eff").read_text()
        fade_ages = []
        for profile in ("SmokeLower", "SmokeMiddle", "SmokeUpper"):
            body = re.search(rf"(?m)^\[{profile}\]\n([^\[]+)", effect)[1]
            colors = [tuple(map(float, line.split()[1:])) for line in body.splitlines() if line.startswith("Colors")]
            ages, brightness = zip(*((age, red * opacity) for age, red, _, _, opacity in colors))
            self.assertTrue(all(red > green > blue for _, red, green, blue, _ in colors))
            self.assertTrue(all(a < b for a, b in zip(ages, ages[1:])))
            self.assertEqual(brightness[0], 0)
            self.assertEqual(brightness[-1], 0)
            self.assertTrue(all(a >= b for a, b in zip(brightness[1:], brightness[2:])))
            fade_ages.append(next(age for age, level in zip(ages[1:], brightness[1:]) if level == 0))
        self.assertEqual(fade_ages, [0.45, 0.70, 1.0])
        size_table = re.search(r"(?m)^SizeTable\s+(.+)$", effect)
        sizes = list(map(float, size_table[1].split()[1::2]))
        self.assertTrue(all(a < b for a, b in zip(sizes, sizes[1:])))

    def test_coarse_city_impact_reaches_the_cell_off_center(self):
        terrain = WoodlandTerrain(Path("."), "city20", ("U" * 160,) * 160, {},
                                  "town", LONDON_CITY_RAID_CENTER, 20)
        lab = Lab(terrain)
        lab.handle(0, "init", [15, 0, 0, terrain.identity])
        x, y = LONDON_CITY_RAID_CENTER
        self.assertIn("1 fuel cells heated", lab.handle(1, "bomb", ["SC50", x + 0.2, y + 0.2]))
        self.assertGreater(lab.sim.cells[lab.sim.index(80, 80)].heat, 0)
        self.assertEqual(lab.sim.cells[lab.sim.index(79, 79)].heat, 0)

    def test_city_crew_waits_for_a_parked_pump_and_hose_setup(self):
        terrain = WoodlandTerrain(Path("."), "city", ("U" * 320,) * 320, {},
                                  "town", LONDON_CITY_RAID_CENTER, 10)
        lab = Lab(terrain, front_fx=True)
        lab.handle(0, "init", [15, 0, 0, terrain.identity])
        x, y = LONDON_CITY_RAID_CENTER
        lab.handle(1, "bomb", ["SC250", x + 5, y + 5])
        lab.handle(8, "city_crew_dispatch", ["1", x + 55, y + 5])
        lab.handle(10, "city_crew_position", ["1", x + 100, y + 5, "1"])
        crew = lab.city_crews["1"].response
        self.assertEqual(crew.state, "en_route")
        for second in range(11, 32):
            lab.handle(second, "city_crew_position", ["1", x + 55, y + 5, "1"])
        self.assertEqual(crew.state, "pumping")
        self.assertEqual(crew.pumped_l, 12)
        self.assertGreater(crew.applied_kg, 0)
        lab.handle(32, "city_crew_lost", ["1"])
        self.assertEqual(crew.state, "unavailable")

    def test_optional_light_field_keeps_the_legacy_emitter_coordinates(self):
        terrain = WoodlandTerrain(Path("."), "raid", ("U" * 320,) * 320, {},
                                  "town", LONDON_ATTACK_CENTER, 10, 0.5)
        lab = Lab(terrain, front_fx=True)
        lab.handle(0, "init", [15, 3, 0, terrain.identity])
        x, y = LONDON_ATTACK_CENTER
        lab.handle(1, "bomb", ["SC250", x + 5, y + 5])
        lab.advance(14)

        normal = lab.frame("session", 1, 1, "ok").splitlines()
        lighting = lab.frame("session", 1, 1, "ok", light_data=True).splitlines()
        self.assertGreater(len(lighting), 1)
        self.assertEqual(normal[0], lighting[0])
        self.assertEqual(len(normal), len(lighting))
        for original, colored in zip(normal[1:], lighting[1:]):
            fields, intensity = colored.rsplit("\t", 1)
            self.assertEqual(original, fields)
            cell_x, cell_y = map(int, fields.split("\t")[0].split("_")[-2:])
            self.assertAlmostEqual(float(intensity), lab.sim.cells[lab.sim.index(cell_x, cell_y)].intensity,
                                   places=5)

    def test_split_frame_lights_only_flames_and_keeps_smoldering_smoke(self):
        terrain = WoodlandTerrain(Path("."), "city20", ("U" * 160,) * 160, {},
                                  "town", LONDON_CITY_RAID_CENTER, 20)
        lab = Lab(terrain, front_fx=True, split_fx=True)
        lab.handle(0, "init", [15, 0, 0, terrain.identity])
        east, north = terrain.center
        lab.handle(1, "bomb", ["SC50", east + 10, north + 10])
        flame = lab.sim.index(80, 80)
        smoke = lab.sim.index(92, 92)
        lab.sim.active = {flame, smoke}
        lab.sim.cells[flame].state = "flaming"
        lab.sim.cells[flame].intensity = 0.75
        lab.sim.cells[smoke].state = "smoldering"
        lab.sim.cells[smoke].smoke_rate = 1.0

        rows = lab.frame("session", 1, 1, "ok", light_data=True).splitlines()[1:]
        self.assertEqual(rows, [
            f"1_P1_80_80\ttown\t{east + 10:.3f}\t{north + 10:.3f}\t0.75000",
            f"1_P2_92_92\ttown\t{east + 250:.3f}\t{north + 250:.3f}\t0.00000",
        ])

    def test_district_light_keeps_its_location_when_flames_move_within_the_district(self):
        sim = FireSim(12, 12, cell_size=20)
        projector = DistrictLightProjector()
        start, next_cell = sim.index(2, 3), sim.index(6, 5)
        for i in (start, next_cell):
            sim.cells[i].state = "flaming"
            sim.cells[i].intensity = 0.9

        sim.active = {start}
        first, = projector.desired(sim)
        sim.active = {next_cell}
        second, = projector.desired(sim)
        self.assertEqual(first, second)
        sim.active = set()
        self.assertEqual(projector.desired(sim), [])

    def test_london_scripted_starts_use_the_city_grid(self):
        rows = ("S" * 320,) + ("U" * 320,) * 319
        terrain = WoodlandTerrain(Path("."), "london", rows, {}, "town", LONDON_CENTER, 10, 0.5)
        lab = Lab(terrain)
        starts = list(london_ignitions(terrain))
        self.assertEqual(len(set(starts)), 9)
        lab.handle(0, "init", [LONDON_TEMP_C, *LONDON_WIND, terrain.identity])
        for stamp, east, north in starts:
            self.assertIn("1 fuel cell", lab.handle(stamp, "ignition", [east, north]))
        lab.advance(36)
        self.assertGreaterEqual(lab.sim.stats()["ignitions"], 9)
        self.assertEqual(lab.sim.cells[0].fuel, 0)
        self.assertEqual(lab.wind, LONDON_WIND)

    def test_wide_town_spreads_across_the_old_edge_without_embers(self):
        terrain = WoodlandTerrain(Path("."), "wide", ("W" * 128,) * 128, {},
                                  "town", WOOD_EDGE_CENTER, 10)
        lab = Lab(terrain)
        lab.handle(0, "init", [15, 0, 12, terrain.identity])
        lab.embers = False
        lab.new_plot("town")
        self.assertIsInstance(lab.sim, SparseFireSim)
        self.assertEqual(len(lab.sim.cells.allocated), 0)
        edge = terrain.half + 320
        lab.sim.ignite(terrain.half + 5, edge - 15, 4, 630)
        lab.advance(150)
        self.assertTrue(any(lab.sim.center(i)[1] > edge and cell.initial_fuel > cell.fuel
                            for i, cell in lab.sim.cells.allocated.items()))
        self.assertLess(len(lab.sim.cells.allocated), len(lab.sim.cells) // 8)

    def test_woodland_village_water_requires_arrival_and_setup(self):
        terrain = WoodlandTerrain(Path("."), "village", ("W" * 24 + "G" * 16 + "U" * 24,) * 64, {},
                                  "town", WOOD_EDGE_CENTER, 10, 0.45)
        lab = Lab(terrain)
        lab.handle(0, "init", [15, 0, 12, terrain.identity])
        lab.handle(0, "bomb", ["SC250", 235955, 233765])
        self.assertEqual(lab.sim.cells[0].moisture, FUELS["woodland"].moisture)
        self.assertEqual(lab.sim.cells[30].moisture, 0.45)
        self.assertEqual(lab.sim.cells[63].moisture, FUELS["masonry"].moisture)
        lab.handle(0, "crew_dispatch", [])
        sx, sy = WOOD_EDGE_ROAD[-1]
        for tick in range(1, 6):
            lab.handle(tick, "crew_position", [str(sx + 60), str(sy), "1"])
        self.assertEqual(lab.crew.pumped_l, 0)
        for tick in range(6, 17):
            lab.handle(tick, "crew_position", [str(sx), str(sy), "1"])
        self.assertEqual(lab.crew.pumped_l, 0)
        for tick in range(17, 25):
            lab.handle(tick, "crew_position", [str(sx), str(sy), "1"])
        self.assertGreater(lab.crew.pumped_l, 0)
        self.assertAlmostEqual(lab.crew.applied_kg, lab.crew.pumped_l * 0.65)

    def test_town_emitter_coverage_uses_fixed_flaming_cells(self):
        sim = FireSim(32, 32, 10)
        for y in range(5, 15):
            for x in range(5, 15):
                i = sim.index(x, y)
                sim.cells[i].state = "flaming"
                sim.active.add(i)
        projector = FireFrontProjector()
        initial = projector.desired(sim)
        self.assertEqual(len(initial), FRONT_BUDGET)
        remote = sim.index(26, 27)
        sim.cells[remote].state = "flaming"
        sim.active.add(remote)
        effects = projector.desired(sim)
        anchors = {(east, north) for _, east, north in effects}
        self.assertEqual(len(anchors), FRONT_BUDGET)
        self.assertEqual(len(set(effects) & set(initial)), FRONT_BUDGET - 1)
        self.assertIn(sim.center(remote), anchors)
        self.assertLessEqual(anchors, {sim.center(i) for i in sim.active})
        for a in anchors:
            self.assertTrue(all((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 >= FRONT_SPACING_M ** 2
                                for b in anchors - {a}))
        self.assertEqual(projector.desired(sim), effects)
        sim.cells[remote].state = "smoldering"
        self.assertNotIn(sim.center(remote), {(east, north) for _, east, north in projector.desired(sim)})

    def test_every_menu_leaf_and_distinct_seed_counts(self):
        source = Path(__file__).resolve().parents[1] / "integrations/clod/HawkingeFireLab.cs"
        actions = source.read_text().split("string[][] Actions = {", 1)[1].split("};", 1)[0]
        for arg in re.findall(r'"([^"]+)"', actions):
            action, *args = arg.split(r"\t")
            with self.subTest(action=arg):
                lab = new_lab()
                self.assertTrue(lab.handle(0, action, args))
                if action == "seed":
                    lab.handle(0.5, "clock", ["10"])
                    self.assertEqual(lab.sim.stats()["ignitions"], int(args[1]))
                    self.assertEqual(len(lab.frame("session", 1, 1, "ok").splitlines()) - 1, int(args[1]))

    def test_time_multiplier_advances_only_with_game_clock(self):
        lab = new_lab()
        lab.handle(10, "seed", ["forest", "1"])
        lab.handle(11, "rate", ["4"])
        lab.handle(15, "clock", ["10"])
        self.assertEqual(lab.sim.time, 17)
        lab.handle(15, "clock", ["10"])
        self.assertEqual(lab.sim.time, 17)
        lab.handle(15, "rate", ["0"])
        lab.handle(100, "clock", ["10"])
        self.assertEqual(lab.sim.time, 17)
        lab.handle(100, "rate", ["1"])
        lab.handle(101, "clock", ["10"])
        self.assertEqual(lab.sim.time, 18)

    def test_gap_blocks_local_spread_and_bomb_presets_differ(self):
        fronts = {}
        for scenario in ("hedge", "hedge_gap"):
            lab = new_lab()
            lab.handle(0, "weather", ["embers"])
            lab.handle(0, "seed", [scenario, "1"])
            lab.handle(300, "clock", ["10"])
            involved = [i for i, cell in enumerate(lab.sim.cells) if cell.fuel < cell.initial_fuel]
            self.assertEqual({i // SIZE for i in involved}, {16})
            fronts[scenario] = set(i % SIZE for i in involved)
        self.assertGreater(max(fronts["hedge"]), 20)
        self.assertLess(max(fronts["hedge_gap"]), 19)
        groups = {}
        x, y = map(str, PLOTS["forest"])
        for bomb in ("SC50", "SC250"):
            lab = new_lab()
            lab.handle(0, "bomb", [bomb, x, y])
            lab.handle(0.5, "clock", ["10"])
            groups[bomb] = lab.sim.stats()["ignitions"]
        self.assertGreater(groups["SC50"], 0)
        self.assertGreater(groups["SC250"], groups["SC50"])

    def test_ambient_drying_dense_sparse_and_legacy(self):
        for model in (FireSim, SparseFireSim):
            wetness = []
            for temperature in (23, 5):
                sim = model(2, 2)
                sim.ambient_c, sim.rain_mm_h = temperature, 12
                sim.step(120)
                self.assertEqual(model.restore(sim.snapshot()).ambient_c, temperature)
                wetness.append(sim.cells[0].wetness)
            self.assertLess(*wetness)
            data = sim.snapshot()
            del data["ambient_c"]
            self.assertEqual(model.restore(data).ambient_c, 20)

    @unittest.skipUnless(sys.platform == "win32", "Windows bridge")
    def test_game_event_file_to_plume_file(self):
        script = Path(__file__).resolve().parents[1] / "integrations/clod/fire_lab.py"
        session = "a" * 32
        with TemporaryDirectory() as work:
            folder = Path(work) / "GroundFireHawkinge/lab"
            folder.mkdir(parents=True)
            with subprocess.Popen([sys.executable, "-B", str(script)],
                                  env={**os.environ, "LOCALAPPDATA": work},
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True) as process:
                try:
                    self.assertIn("Waiting for Hawkinge", process.stdout.readline())
                    events = folder / (session + ".events.tsv")
                    events.write_text("1\t0\tinit\t15\t2\t0\n2\t0\tseed\tforest\t3\n"
                                      "3\t0.5\tclock\t10\n4\t1\tres", encoding="ascii")
                    (folder / "active.txt").write_text(session, encoding="ascii")
                    output = folder / (session + ".plumes.tsv")

                    def frame_for(version):
                        until = time.monotonic() + 5
                        while time.monotonic() < until:
                            if output.exists():
                                rows = output.read_text().splitlines()
                                if int(rows[0].split("\t")[1]) > version:
                                    return rows
                            time.sleep(0.02)
                        self.fail("No updated plume frame")

                    burning = frame_for(0)
                    self.assertEqual(len(burning), 4)
                    self.assertTrue(all(row.split("\t")[1] == "forest" for row in burning[1:]))
                    with events.open("a", encoding="ascii") as stream:
                        stream.write("et\n")
                    cleared = frame_for(int(burning[0].split("\t")[1]))
                    self.assertEqual(len(cleared), 1)
                    self.assertIn("Plot cleared", cleared[0])
                finally:
                    process.terminate()
