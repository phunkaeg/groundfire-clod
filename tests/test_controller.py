import json
import subprocess
import sys
import unittest

from firesim.controller import Controller, dcs_effect_script
from firesim.core import FireSim


class ControllerTests(unittest.TestCase):
    def test_protocol_can_drive_fire_and_suppression(self):
        c = Controller(FireSim(3, 3))
        c.handle({"kind": "ignition", "east": 15, "north": 15, "radius_m": 4, "exposure_kj_m2": 700})
        result = c.handle({"kind": "advance", "seconds": 15})
        self.assertGreater(result["stats"]["flaming"], 0)
        self.assertFalse(result["game_connected"])
        self.assertTrue(result["effects"])
        c.handle({"kind": "suppression", "east": 15, "north": 15, "radius_m": 4, "water_kg": 500})
        result = c.handle({"kind": "advance", "seconds": 1})
        self.assertEqual(result["stats"]["flaming"], 0)

    def test_bad_weather_does_not_partially_mutate_state(self):
        c = Controller(FireSim(1, 1))
        old = c.sim.wind_east
        with self.assertRaises(ValueError):
            c.handle({"kind": "weather", "wind_east_m_s": 9, "rain_mm_h": -1})
        self.assertEqual(c.sim.wind_east, old)

    def test_nonobject_protocol_message_rejected(self):
        with self.assertRaises(ValueError):
            Controller(FireSim(1, 1)).handle([])

    def test_stdio_protocol_and_error_recovery(self):
        events = [{"kind": "weather", "wind_east_m_s": 1}, {"kind": "bogus"}, {"kind": "advance", "seconds": 3}]
        result = subprocess.run([sys.executable, "-m", "firesim", "stream"],
                                input="\n".join(json.dumps(v) for v in events) + "\n",
                                text=True, capture_output=True, timeout=10, check=True)
        output = [json.loads(v) for v in result.stdout.splitlines()]
        self.assertEqual(len(output), 3)
        self.assertEqual(output[1]["kind"], "error")
        self.assertEqual(output[2]["stats"]["time"], 3)

    def test_dcs_preview_uses_named_lifecycle_and_terrain_height(self):
        script = dcs_effect_script([{"id": "S000_000", "mode": "large", "east": 10, "north": 20}])
        self.assertIn('wanted["GroundFire_S000_000"]', script)
        self.assertIn("preset=3", script)
        self.assertIn("land.getHeight", script)
        self.assertIn("effectSmokeStop(name)", script)
        self.assertIn("if not GroundFireFX[name]", script)


if __name__ == "__main__":
    unittest.main()
