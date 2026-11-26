"""Experimental sparse storage for the same fixed-resolution fire equations.

Untouched terrain is supplied on demand; it is not a real Channel fuel dataset.
Uniform rain on untouched fuel is integrated as one background wetness value.
Changed cells are retained. Retirement/coarse fronts/streamed fuel maps are future
work, so this scales with the area ever visited, not just the current flame front.
"""
from __future__ import annotations

from dataclasses import asdict
import math

from .core import Cell, FireSim


class SparseCells:
    """Index-addressable cells; deliberately refuses a whole-theatre scan."""
    def __init__(self, count, factory):
        self.count, self.factory = count, factory
        self.allocated: dict[int, Cell] = {}

    def __len__(self):
        return self.count

    def _check(self, index):
        if not isinstance(index, int) or not 0 <= index < self.count:
            raise IndexError(index)

    def __getitem__(self, index):
        self._check(index)
        if index not in self.allocated:
            self.allocated[index] = self.factory(index)
        return self.allocated[index]

    def __setitem__(self, index, cell):
        self._check(index)
        self.allocated[index] = cell

    def __iter__(self):
        raise TypeError("Whole-theatre iteration is disabled; use cells.allocated.items()")


class SparseFireSim(FireSim):
    """Large coordinate envelope, detailed cells only where read or changed.

    fuel_at(x, y) returns keyword arguments for make_cell, including `kind`.
    It must be deterministic and side-effect free. provider_id identifies the
    dataset, resolution and coordinate mapping; restore requires the same ID.
    Base GUI/IL-2 exporters enumerate dense cells and must not be used here.
    EffectProjector works through the active set and needs no whole-map scan.
    """
    sparse_schema = 1

    def __init__(self, width, height, cell_size=10.0, seed=7,
                 fuel_at=None, provider_id="synthetic-uniform-grass-v1"):
        if any(type(v) is not int or not 1 <= v <= 1_000_000 for v in (width, height)):
            raise ValueError("Sparse dimensions must be positive integers <= 1,000,000")
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("A fuel provider identity is required")
        if fuel_at is not None and not callable(fuel_at):
            raise ValueError("fuel_at must be callable")
        if (fuel_at is None) != (provider_id == "synthetic-uniform-grass-v1"):
            raise ValueError("Custom fuel providers require their own ID and callback")
        super().__init__(1, 1, cell_size, seed)
        self.width, self.height = width, height
        self.fuel_at = fuel_at or (lambda x, y: {"kind": "grass"})
        self.provider_id = provider_id
        self.background_wetness = 0.0
        self.cells = SparseCells(width * height, self._new_cell)

    def _new_cell(self, index):
        values = self.fuel_at(index % self.width, index // self.width)
        c = self.make_cell(**values)
        if c.initial_fuel > 0:
            c.wetness = self.background_wetness
        return c

    def _weather_indices(self):
        # This hook runs after neighbour/ember reads may have populated new cells.
        # Cold cells already in memory must also follow background drying.
        if self.rain_mm_h or self.background_wetness > 0:
            return self.cells.allocated.keys()
        return ()

    def _tick(self, dt):
        super()._tick(dt)
        self.background_wetness = max(
            0.0, self.background_wetness + (self.rain_mm_h / 3600 - self._surface_drying_rate()) * dt)

    def stats(self):
        states = {k: 0 for k in ("unburned", "heating", "flaming", "smoldering", "burned")}
        allocated = self.cells.allocated
        states["unburned"] = len(self.cells) - len(allocated)
        for c in allocated.values():
            states[c.state] += 1
        return {"time": self.time, **states, "ignitions": self.ignitions,
                "consumed_kg": self.consumed_kg,
                "remaining_kg": sum(c.fuel for c in allocated.values()),
                "remaining_scope": "allocated_cells_only",
                "smoke_kg_s": sum(c.smoke_rate for c in allocated.values()),
                "potential_cells": len(self.cells), "allocated_cells": len(allocated),
                "active_cells": len(self.active)}

    def snapshot(self):
        return {"kind": "sparse", "schema": self.sparse_schema,
                "width": self.width, "height": self.height, "cell_size": self.cell_size,
                "seed": self.seed, "provider_id": self.provider_id,
                "background_wetness": self.background_wetness,
                "cells": [[i, asdict(c)] for i, c in sorted(self.cells.allocated.items())],
                "active": sorted(self.active), "wind_east": self.wind_east,
                "wind_north": self.wind_north, "rain_mm_h": self.rain_mm_h,
                "ambient_c": self.ambient_c,
                "embers_enabled": self.embers_enabled, "spot_rate": self.spot_rate, "spotting_model": self.spotting_model,
                "tick": self.tick, "accumulator_ns": self.accumulator_ns,
                "ignitions": self.ignitions, "consumed_kg": self.consumed_kg,
                "event_ids": sorted(self.event_ids), "rng_state": self.rng.getstate()}

    @classmethod
    def restore(cls, data, *, fuel_at=None, provider_id="synthetic-uniform-grass-v1"):
        if data.get("kind") != "sparse" or data.get("schema") != cls.sparse_schema:
            raise ValueError("Unsupported sparse snapshot")
        if data.get("provider_id") != provider_id:
            raise ValueError("Fuel dataset/coordinate identity mismatch")
        obj = cls(data["width"], data["height"], data["cell_size"], data["seed"],
                  fuel_at=fuel_at, provider_id=provider_id)
        obj.background_wetness = data["background_wetness"]
        if not math.isfinite(obj.background_wetness) or obj.background_wetness < 0:
            raise ValueError("Invalid background wetness")
        for index, values in data["cells"]:
            obj.cells._check(index)
            if index in obj.cells.allocated:
                raise ValueError("Duplicate sparse cell")
            c = Cell(**values)
            if not math.isfinite(c.fuel) or c.fuel < 0:
                raise ValueError("Invalid sparse fuel")
            obj.cells[index] = c
        obj.active = set(data["active"])
        if not obj.active.issubset(obj.cells.allocated):
            raise ValueError("Active cell missing from snapshot")
        for key in ("wind_east", "wind_north", "rain_mm_h", "embers_enabled", "spot_rate",
                    "tick", "accumulator_ns", "ignitions", "consumed_kg"):
            setattr(obj, key, data[key])
        obj.event_ids = set(data["event_ids"])
        obj._restore_environment(data)
        return obj
