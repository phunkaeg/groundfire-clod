from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations/clod"))
from sunset_lighting import append_fire_sunlight, mission_solar_inputs


class SunsetLightingTests(unittest.TestCase):
    def test_summer_date_uses_map_default(self):
        mission = "[MAIN]\r\n  MAP Land$English_Channel_1940\r\n  TIME 10.5\r\n[AirGroups]\r\n"
        self.assertEqual(mission_solar_inputs(mission), (date(1940, 7, 15), 10.5))

    def test_authored_mission_date_overrides_map_default(self):
        mission = ("[MAIN]\n  MAP Land$English_Channel_1940\n  TIME 20.25\n"
                   "  YEAR 1941\n  MONTH 12\n  DAY 25\n")
        self.assertEqual(mission_solar_inputs(mission), (date(1941, 12, 25), 20.25))
        source = append_fire_sunlight("existing script", mission)
        self.assertIn("new DateTime(1941, 12, 25)", source)
        self.assertIn("FireLightingStart = 20.25", source)
        self.assertIn("GamePlay.gpTimeofDay()", source)
        self.assertNotIn("__FIRE_", source)

    def test_winter_map_default(self):
        mission = "[main]\n map Land$English_Channel_1940_Winter\n time 18\n"
        self.assertEqual(mission_solar_inputs(mission), (date(1940, 12, 7), 18))

    def test_invalid_clock_is_rejected(self):
        mission = "[MAIN]\n  MAP Land$English_Channel_1940\n  TIME nan\n"
        with self.assertRaisesRegex(ValueError, "within 24 hours"):
            mission_solar_inputs(mission)
