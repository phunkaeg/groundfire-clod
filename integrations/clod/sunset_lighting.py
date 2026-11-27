"""Embed the Channel mission date and solar gate into a lighting-enabled mission."""
from datetime import date
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
CHANNEL_DEFAULTS = dict(summer=(1940, 7, 15), autumn=(1940, 10, 7), winter=(1940, 12, 7))


def mission_solar_inputs(mission):
    section = re.search(r"(?mi)^\[MAIN\][ \t]*\r?\n([^\[]+)", mission)
    if section is None:
        raise ValueError("No mission MAIN section for sunset lighting")
    entries = dict(re.findall(r"(?mi)^[ \t]*([A-Z]+)[ \t]+([^\r\n]+)", section[1].strip()))
    main = {key.upper(): value.strip() for key, value in entries.items()}
    map_name = main.get("MAP", "").lower()
    if not map_name.startswith("land$english_channel_1940"):
        raise ValueError("Sunset lighting uses the Channel map solar settings")
    season = ("winter" if "winter" in map_name else
              "autumn" if "autumn" in map_name else "summer")
    d = date(*(int(main.get(key, fallback))
               for key, fallback in zip(("YEAR", "MONTH", "DAY"), CHANNEL_DEFAULTS[season])))
    hour = float(main["TIME"])
    if not math.isfinite(hour) or not 0 <= hour < 24:
        raise ValueError("Mission TIME must be within 24 hours")
    return d, hour


def append_fire_sunlight(source, mission):
    d, hour = mission_solar_inputs(mission)
    binding = (HERE / "FireSunlightMission.cs").read_text(encoding="ascii")
    binding = binding.replace("__FIRE_DATE__", f"{d.year}, {d.month}, {d.day}")
    binding = binding.replace("__FIRE_START__", format(hour, ".12g"))
    solar = (HERE / "FireSunlight.cs").read_text(encoding="ascii")
    return source.rstrip() + "\n\n" + binding.rstrip() + "\n\n" + solar
