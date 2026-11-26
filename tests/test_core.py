import json
import math
import unittest

from firesim.core import FireSim
from firesim.scenarios import village
from firesim.adapters import EffectProjector, IL2Adapter, MemorySink, make_manifest


def uniform(w=15, h=9, kind="grass", moisture=0.05):
    s = FireSim(w, h)
    for y in range(h):
        for x in range(w):
            s.paint(x, y, kind, moisture=moisture)
    s.embers_enabled = False
    return s


class CoreTests(unittest.TestCase):
    def test_no_spontaneous_ignition(self):
        s = uniform()
        s.step(300)
        self.assertEqual(s.stats()["ignitions"], 0)
        self.assertEqual(s.consumed_kg, 0)

    def test_fire_spreads_beyond_ignition_footprint(self):
        s = uniform()
        s.ignite(75, 45, 4, 600)
        s.step(100)
        self.assertGreater(s.ignitions, 1)
        self.assertGreater(s.consumed_kg, 1)

    def test_finite_fuel_burnout_mass_balance(self):
        s = uniform(1, 1)
        initial = s.cells[0].fuel
        s.ignite(5, 5, 4, 600)
        s.step(900)
        self.assertEqual(s.cells[0].state, "burned")
        self.assertEqual(s.cells[0].fuel, 0)
        self.assertAlmostEqual(s.consumed_kg, initial, places=7)

    def test_water_and_road_do_not_burn(self):
        for kind in ("water", "road"):
            s = uniform(1, 1, kind)
            s.ignite(5, 5, 10, 100000)
            s.step(50)
            self.assertEqual(s.ignitions, 0)

    def test_no_fuel_barrier_without_embers(self):
        s = uniform(15, 7)
        for y in range(s.height):
            s.paint(7, y, "water")
        s.wind_east = 8
        s.ignite(55, 35, 4, 600)
        s.step(180)
        self.assertGreater(s.ignitions, 1)
        self.assertTrue(all(c.fuel == c.initial_fuel for i, c in enumerate(s.cells) if i % s.width > 7))

    def test_embers_can_cross_a_nonfuel_barrier(self):
        s = uniform(30, 9)
        for x in (13, 14, 15):
            for y in range(s.height):
                s.paint(x, y, "water")
        s.embers_enabled = True
        s.spot_rate = 0.4
        s.wind_east = 8
        s.ignite(115, 45, 4, 650)
        s.step(100)
        self.assertTrue(any(c.fuel < c.initial_fuel for i, c in enumerate(s.cells) if i % s.width > 15))

    def test_same_burning_area_samples_same_ember_distances_across_resolutions(self):
        samples = []
        for resolution in (10, 5, 2.5):
            side = int(220 / resolution)
            s = FireSim(side, side, cell_size=resolution, seed=7)
            s.spot_rate = 8
            for y in range(int(100 / resolution), int(110 / resolution)):
                for x in range(int(100 / resolution), int(110 / resolution)):
                    i = s.index(x, y)
                    s.cells[i].state = "flaming"
                    s.cells[i].intensity = 1
                    s.active.add(i)
            s.step(0.5)
            samples.append([
                (round(e.landing_east - e.source_east, 9), round(e.landing_north - e.source_north, 9))
                for e in s.ember_landings
            ])
        self.assertGreater(len(samples[0]), 1)
        self.assertEqual(samples[0], samples[1])
        self.assertEqual(samples[0], samples[2])

    def test_rain_reduces_fuel_consumption(self):
        dry, wet = uniform(), uniform()
        wet.rain_mm_h = 40
        for s in (dry, wet):
            s.ignite(75, 45, 4, 600)
            s.step(110)
        self.assertLess(wet.consumed_kg, dry.consumed_kg)

    def test_wet_fuel_resists_identical_heat(self):
        dry, wet = uniform(1, 1, moisture=0.05), uniform(1, 1, moisture=0.8)
        for s in (dry, wet):
            s.ignite(5, 5, 4, 150)
            s.step(20)
        self.assertGreater(dry.consumed_kg, wet.consumed_kg)
        self.assertEqual(wet.ignitions, 0)

    def test_water_extinguishes_without_consuming_fuel(self):
        s = uniform(1, 1)
        s.ignite(5, 5, 4, 600)
        s.step(12)
        before = s.cells[0].fuel
        s.suppress(5, 5, 4, 100)
        self.assertEqual(s.cells[0].fuel, before)
        s.step(10)
        self.assertNotEqual(s.cells[0].state, "flaming")
        self.assertAlmostEqual(s.cells[0].fuel, before)

    def test_wind_changes_direction(self):
        s = uniform(21, 11)
        s.wind_east = 7
        s.ignite(105, 55, 4, 600)
        s.step(75)
        east = sum(c.initial_fuel - c.fuel for i, c in enumerate(s.cells) if i % s.width > 10)
        west = sum(c.initial_fuel - c.fuel for i, c in enumerate(s.cells) if i % s.width < 10)
        self.assertGreater(east, west * 1.2)

    def test_snapshot_continuation_including_rng(self):
        s = village(20)
        s.spot_rate = 0.05
        s.step(42.25)
        restored = FireSim.restore(json.loads(json.dumps(s.snapshot())))
        for _ in range(80):
            s.step(0.75)
            restored.step(0.75)
        self.assertEqual(s.snapshot(), restored.snapshot())

    def test_snapshot_without_spotting_model_continues_in_legacy_mode(self):
        original = FireSim(25, 18)
        original.spotting_model = "legacy_cell"
        original.spot_rate = 2
        original.ignite(105, 85, 4, 600)
        original.step(3.5)
        snapshot = json.loads(json.dumps(original.snapshot()))
        del snapshot["spotting_model"]
        restored = FireSim.restore(snapshot)
        self.assertEqual(restored.spotting_model, "legacy_cell")
        for sim in (restored, original):
            sim.step(5)
        self.assertEqual(restored.snapshot(), original.snapshot())

    def test_external_step_chunking_invariant(self):
        a, b = village(2), village(2)
        a.step(20)
        for _ in range(200):
            b.step(0.1)
        self.assertEqual(a.snapshot(), b.snapshot())

    def test_masonry_contents_can_burn_without_total_collapse(self):
        s = uniform(1, 1, "masonry")
        s.ignite(5, 5, 4, 1200)
        s.step(3600)
        self.assertEqual(s.cells[0].fuel, 0)
        self.assertAlmostEqual(s.cells[0].integrity, 0.6)

    def test_duplicate_input_event_is_idempotent(self):
        s = uniform(1, 1)
        s.ignite(5, 5, 4, 100, "a")
        heat = s.cells[0].heat
        self.assertEqual(s.ignite(5, 5, 4, 100, "a"), 0)
        self.assertEqual(s.cells[0].heat, heat)

    def test_nonfinite_input_rejected(self):
        s = uniform(1, 1)
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                s.step(value)
            with self.assertRaises(ValueError):
                s.ignite(value, 0)


class ProjectionTests(unittest.TestCase):
    def test_budget_and_delta_only_output(self):
        s = village()
        s.step(75)
        p = EffectProjector(2, 3)
        sink = MemorySink()
        a = IL2Adapter(sink, make_manifest(s, 2), p)
        desired = a.synchronize(s)
        self.assertLessEqual(len(desired), 3)
        count = len(sink.commands)
        self.assertGreater(count, 0)
        a.synchronize(s)
        self.assertEqual(len(sink.commands), count)
        a.stop_all()
        self.assertFalse(a.current)

    def test_damage_milestone_fires_once(self):
        s = uniform(1, 1, "timber")
        s.cells[0].object_id = "house"
        manifest = make_manifest(s)
        manifest["damage"] = {"house": {"25": "GF_house_DAMAGE25"}}
        sink = MemorySink()
        a = IL2Adapter(sink, manifest)
        s.ignite(5, 5, 4, 900)
        s.step(100)
        a.synchronize(s)
        a.synchronize(s)
        self.assertEqual(sink.commands.count("serverinput GF_house_DAMAGE25"), 1)

    def test_rejected_request_is_not_marked_applied(self):
        class Reject:
            def trigger(self, name):
                raise ConnectionError("mock rejection")
        s = uniform(1, 1)
        s.ignite(5, 5, 4, 600)
        s.step(1)
        a = IL2Adapter(Reject(), make_manifest(s))
        with self.assertRaises(ConnectionError):
            a.synchronize(s)
        self.assertFalse(a.current)


if __name__ == "__main__":
    unittest.main()
