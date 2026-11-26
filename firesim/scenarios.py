from .core import FireSim


def village(seed=7, ignite=True):
    sim = FireSim(48, 32, 10, seed)
    for y in range(sim.height):
        for x in range(sim.width):
            kind = "woodland" if x < 27 else "grass"
            if x in (23, 24):
                kind = "water"
            if y in (15, 16) or x == 35:
                kind = "road"
            if 28 <= x <= 44 and y in (7, 8, 11, 12, 20, 21, 24, 25) and x % 4 in (0, 1):
                kind = "timber" if x < 38 else "masonry"
            sim.paint(x, y, kind, elevation=y * 0.25,
                      object_id=f"building_{x}_{y}" if kind in ("timber", "masonry") else None)
    if ignite:
        sim.ignite(105, 100, 16, 850, "demo-bomb-1")
    return sim
