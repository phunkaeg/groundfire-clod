import json
import unittest
from dataclasses import asdict

from firesim.core import FireSim
from firesim.sparse import SparseFireSim
from firesim.adapters import EffectProjector


class SparseTests(unittest.TestCase):
    def assert_cells_equal(self, dense, sparse):
        for i in range(dense.width * dense.height):
            a, b = asdict(dense.cells[i]), asdict(sparse.cells[i])
            for key in a:
                if isinstance(a[key], float):
                    self.assertAlmostEqual(a[key], b[key], places=9, msg=(i, key))
                else:
                    self.assertEqual(a[key], b[key], (i, key))
        self.assertEqual(dense.ignitions, sparse.ignitions)
        self.assertAlmostEqual(dense.consumed_kg, sparse.consumed_kg, places=8)

    def test_dry_spread_and_embers_match_dense(self):
        dense, sparse = FireSim(41, 31), SparseFireSim(41, 31)
        for s in (dense, sparse):
            s.wind_east, s.wind_north, s.spot_rate = 5, 1, 0.08
            for y in range(31):
                s.paint(22, y, "road")
            s.ignite(155, 155, 12, 600)
            s.step(120)
        self.assertLess(len(sparse.cells.allocated), 41 * 31)
        self.assert_cells_equal(dense, sparse)
        self.assertEqual(dense.rng.getstate(), sparse.rng.getstate())

    def test_background_rain_drying_and_late_ignition_match_dense(self):
        dense, sparse = FireSim(25, 19), SparseFireSim(25, 19)
        for s in (dense, sparse):
            s.rain_mm_h = 25
            s.step(90)
            s.rain_mm_h = 0
            s.step(40)
            s.ignite(125, 95, 12, 600)
            s.step(90)
            s.suppress(125, 95, 20, 100)
            s.step(20)
        self.assert_cells_equal(dense, sparse)

    def test_distant_fires_do_not_allocate_intervening_map(self):
        s = SparseFireSim(35_000, 35_000)
        self.assertEqual(len(s.cells.allocated), 0)
        for east, north in ((1005, 1005), (300005, 270005)):
            s.ignite(east, north, 4, 600)
        s.step(100)
        self.assertGreater(s.ignitions, 2)
        self.assertLess(len(s.cells.allocated), 2000)
        self.assertEqual(s.stats()["potential_cells"], 1_225_000_000)
        self.assertLessEqual(len(EffectProjector(budget=6).desired(s)), 6)

    def test_json_snapshot_replay_with_weather_and_fractional_step(self):
        a = SparseFireSim(35_000, 35_000)
        a.rain_mm_h = 3
        a.ignite(1005, 1005, 12, 600, "test")
        a.step(20.3)
        b = SparseFireSim.restore(json.loads(json.dumps(a.snapshot())))
        for s in (a, b):
            s.step(55.7)
            s.ignite(300005, 270005, 12, 600)
            s.step(20)
        self.assertEqual(a.snapshot(), b.snapshot())

    def test_fuel_provider_and_identity(self):
        provider = lambda x, y: {"kind": "water" if x == 10 else "woodland"}
        a = SparseFireSim(5000, 5000, fuel_at=provider, provider_id="fixture-v1")
        a.embers_enabled = False
        a.ignite(105, 105, 4, 600)
        a.step(20)
        self.assertEqual(a.ignitions, 0)
        self.assertEqual(a.cells[a.index(9, 10)].kind, "woodland")
        with self.assertRaises(ValueError):
            SparseFireSim.restore(a.snapshot())
        with self.assertRaises(ValueError):
            SparseFireSim.restore(a.snapshot(), provider_id="fixture-v1")
        b = SparseFireSim.restore(a.snapshot(), fuel_at=provider, provider_id="fixture-v1")
        self.assertEqual(a.snapshot(), b.snapshot())
        with self.assertRaises(TypeError):
            list(a.cells)


if __name__ == "__main__":
    unittest.main()
