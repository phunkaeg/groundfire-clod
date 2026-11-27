from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import zlib

HERE = Path(__file__).resolve().parents[1] / "integrations/clod"
sys.path.insert(0, str(HERE))
from channel_bridge import ChannelRun, EFFECT_BUDGET, FuelMap


class ChannelBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "tile-fixture.sqlite"
        metadata = dict(schema=1, dataset_id="tile-fixture", width=24, height=16,
                        origin_x_m=0, origin_y_m=0, pixel_size_m=10, tile_size=8, classes=[
                            dict(id=1, name="forest", kind="woodland", moisture=.18),
                            dict(id=2, name="water", kind="water", moisture=1.0),
                        ])
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("CREATE TABLE tiles (tx INT, ty INT, width INT, height INT, classes BLOB)")
            db.executemany("INSERT INTO metadata VALUES (?, ?)",
                           [(k, json.dumps(v)) for k, v in metadata.items()])
            for tx in range(3):
                for ty in range(2):
                    db.execute("INSERT INTO tiles VALUES (?, ?, 8, 8, ?)",
                               (tx, ty, zlib.compress(bytes([2 if tx == 2 else 1] * 64))))
            db.commit()
        self.fuel = FuelMap(path)
        self.addCleanup(self.fuel.close)
        self.run = ChannelRun(self.fuel, "0" * 32)

    def test_adjacent_spread_crosses_real_tile_without_direct_heat(self):
        run = self.run
        run.handle(1, 0, "init", ["tile-fixture", "15", "8", "0"])
        run.handle(2, 10, "bomb", ["SC50", "55", "125", "0", "0", "air group"])
        run.handle(3, 110, "clock", ["60", "120", "fixture", "0"])
        crossing = next(row for row in run.evidence
                        if row.get("source_tile") == (0, 0) and row.get("receiver_tile") == (1, 0))
        self.assertFalse(crossing["receiver_directly_heated"])
        self.assertEqual(crossing["same_tile_flaming_neighbors"], 0)
        self.assertGreaterEqual(crossing["receiver_xy"][0], 80)
        self.assertLessEqual(len(run.frame(3).splitlines()), EFFECT_BUDGET + 1)

    def test_water_impact_stays_inert(self):
        run = self.run
        run.handle(1, 0, "init", ["tile-fixture", "15", "8", "0"])
        run.handle(2, 10, "bomb", ["SC50", "215", "125", "0", "0", "air group"])
        run.handle(3, 100, "clock", ["210", "120", "fixture", "0"])
        self.assertEqual(run.impacts[0]["heated"], 0)
        self.assertFalse(run.sim.crossings)
        self.assertEqual(run.sim.ignitions, 0)

    def test_rejects_an_unmatched_database(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.run.handle(1, 0, "init", ["different-database", "15", "8", "0"])
