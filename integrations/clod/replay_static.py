"""Exercise CloD event, firefighting and plume paths from synthetic inputs."""
import json
from pathlib import Path
import sys
import time

PROTOTYPE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROTOTYPE))

from firesim.adapters import TheatrePlumeProjector
from firesim.clod import ClodEventIngestor, ClodPumpTracker, IgnitionProfile, StorageSite
from firesim.response import HosePlan, HoseResponse
from firesim.scars import burn_tiles
from firesim.sparse import SparseFireSim


def record(sequence, kind, **fields):
    return {"schema": 1, "source": "clod-probe", "session": "offline-fixture",
            "sequence": sequence, "kind": kind, **fields}


def response_replay():
    sim = SparseFireSim(24, 18)
    sim.paint(10, 7, "woodland")
    sim.wind_east = sim.wind_north = 0
    sim.embers_enabled = False
    pos = {"x": 105, "y": 75, "z": 157}
    events = ClodEventIngestor({"Fixture.Small": IgnitionProfile(4, 400)}, {}, lambda x, y: 157)
    result = events.feed(record(1, "bomb_explosion", title="Fixture.Small", position_raw=pos), sim)
    assert result == "bomb-ignition"
    control = SparseFireSim.restore(sim.snapshot())

    # 120 imperial gal/min rounded to 9.09 L/s, with a lower scenario hose rate.
    plan = HosePlan(staging=(85, 95), fire=(105, 75), intake=(85, 105),
                    hose_m=60, setup_s=12, pump_l_s=9.09, charged_line_l_s=6,
                    water_l=180, application_radius_m=8, delivery_fraction=0.65)
    response = HoseResponse(plan)
    tracker = ClodPumpTracker("offline-fixture", "2:fixture-pump", "Fixture.Pump")
    timeline = []
    previous = None
    target = sim.index(10, 7)
    for second in range(56):
        # Synthetic drive ending after 10 s. The same tracker can read raw game log records.
        x = min(85, 25 + 6 * second)
        line = f"GROUNDFIRE_RESPONSE offline-fixture\t{second}\tvehicle\t2:fixture-pump\tFixture.Pump\t{x}\t95\t157\tFalse"
        elapsed, pump, stopped = tracker.feed(line)
        response.advance(sim, elapsed, pump, stopped=stopped)
        sim.step(elapsed)
        control.step(elapsed)
        state = response.state, sim.cells[target].state
        if state != previous:
            timeline.append({"seconds": second, "response": state[0], "fire": state[1],
                             "pumped_l": round(response.pumped_l, 3)})
            previous = state
    assert response.pumped_l == plan.water_l and response.water_left_l == 0
    assert abs(response.applied_kg - 117) < 1e-9
    assert sim.cells[target].state != "flaming" and control.cells[target].state == "flaming"
    return {"timeline": timeline, "pumped_l": response.pumped_l,
            "applied_kg": round(response.applied_kg, 3), "remaining_l": response.water_left_l,
            "target_remaining_fuel_kg": round(sim.cells[target].fuel, 3),
            "untreated_control_state": control.cells[target].state,
            "nonempty_burn_mask_tiles": len(burn_tiles(sim))}


def storage_replay():
    sim = SparseFireSim(50, 50)
    site = StorageSite(205, 205, "fuel_store", IgnitionProfile(18, 500),
                       stationary_name="0:FixtureStore", building_title="Fixture.Store")
    site.prepare(sim)
    events = ClodEventIngestor({}, {"fixture-store": site}, lambda x, y: 157)
    pos = {"x": site.east, "y": site.north, "z": 157}
    accepted = events.feed(record(1, "stationary_killed", name=site.stationary_name, position_raw=pos), sim)
    duplicate = events.feed(record(2, "building_killed", title=site.building_title, position_raw=pos), sim)
    sim.step(10)
    assert accepted == "storage-ignition" and duplicate == "duplicate"
    return {"first_event": accepted, "second_alias": duplicate, "ignited_cells": sim.ignitions,
            "default_store_fuel_kg": sim.cells[sim.index(20, 20)].initial_fuel}


def plume_replay():
    sim = SparseFireSim(10000, 10000)
    sim.embers_enabled = False
    events = ClodEventIngestor({"Fixture.Load": IgnitionProfile(4, 400)}, {}, lambda x, y: 0)
    started = time.perf_counter()
    for index in range(348):
        pos = {"x": 50005 + 130 * (index % 19), "y": 50005 + 130 * (index // 19), "z": 0}
        events.feed(record(index + 1, "bomb_explosion", title="Fixture.Load", position_raw=pos), sim)
    sim.step(10)
    elapsed = time.perf_counter() - started
    projector = TheatrePlumeProjector()
    started = time.perf_counter()
    near = projector.desired(sim, 51000, 51000)
    far = projector.desired(sim, 38000, 51000)
    projection_ms = 1000 * (time.perf_counter() - started)
    assert len(near) <= 24 and sum(p.use_light for p in near) <= 4
    assert near and far and max(p.ground_span_m for p in far) > max(p.ground_span_m for p in near)
    return {"synthetic_events": 348, "simulated_seconds": sim.time,
            "flaming_cells": sim.stats()["flaming"], "event_and_sim_cpu_seconds": round(elapsed, 4),
            "two_projection_ms": round(projection_ms, 4),
            "near": {"plumes": len(near), "lights": sum(p.use_light for p in near)},
            "far": {"plumes": len(far), "lights": sum(p.use_light for p in far)}}


def main():
    report = {"game_connected": False, "inputs": "synthetic, no historical loadout or game performance claim",
              "response": response_replay(), "storage": storage_replay(), "plumes": plume_replay()}
    path = PROTOTYPE / "output/clod/static-replay.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
