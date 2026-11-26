"""Timed sidecar water delivery gated by measured pump position and supply."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class HosePlan:
    staging: tuple[float, float]
    fire: tuple[float, float]
    intake: tuple[float, float]
    hose_m: float
    setup_s: float
    pump_l_s: float
    charged_line_l_s: float
    water_l: float
    application_radius_m: float
    delivery_fraction: float
    arrival_radius_m: float = 6.0

    def __post_init__(self):
        for point in (self.staging, self.fire, self.intake):
            if len(point) != 2 or not all(math.isfinite(v) for v in point):
                raise ValueError("Response points must have two finite coordinates")
        positive = (self.hose_m, self.pump_l_s, self.charged_line_l_s,
                    self.application_radius_m, self.arrival_radius_m)
        if any(not math.isfinite(v) or v <= 0 for v in positive):
            raise ValueError("Hose lengths, rates and radii must be positive and finite")
        if not (math.isfinite(self.water_l) and self.water_l >= 0 and
                math.isfinite(self.setup_s) and self.setup_s >= 0 and 0 < self.delivery_fraction <= 1):
            raise ValueError("Invalid supply, setup time or delivery fraction")


class HoseResponse:
    """One pump. Each interval needs a fresh observation of its position and stop state."""

    def __init__(self, plan: HosePlan):
        self.plan = plan
        self.water_left_l = plan.water_l
        self.setup_remaining_s = plan.setup_s
        self.pumped_l = 0.0
        self.applied_kg = 0.0
        self.state = "dispatched"

    def advance(self, sim, seconds, pump_pos, *, stopped):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Response duration must be finite and non-negative")
        if pump_pos is not None and (len(pump_pos) != 2 or not all(math.isfinite(v) for v in pump_pos)):
            raise ValueError("Pump position must have two finite coordinates")
        plan = self.plan
        if pump_pos is None or not stopped or math.dist(pump_pos, plan.staging) > plan.arrival_radius_m:
            self.setup_remaining_s = plan.setup_s
            self.state = "en_route"
            return 0.0

        # These are lower bounds. A mission can provide staging/intake points
        # chosen around obstacles until the adapter has actual hose routes.
        if math.dist(pump_pos, plan.intake) + math.dist(pump_pos, plan.fire) > plan.hose_m:
            self.state = "out_of_reach"
            self.setup_remaining_s = plan.setup_s
            return 0.0
        if self.water_left_l <= 0:
            self.state = "water_exhausted"
            return 0.0

        setup = min(self.setup_remaining_s, seconds)
        self.setup_remaining_s -= setup
        pumping_seconds = seconds - setup
        if pumping_seconds <= 0:
            self.state = "setting_up"
            return 0.0

        # Density is approximated as 1 kg/L. The charged line rate caps a
        # pump whose nameplate output may be much higher than nozzle delivery.
        pumped = min(self.water_left_l, pumping_seconds * min(plan.pump_l_s, plan.charged_line_l_s))
        self.water_left_l -= pumped
        self.pumped_l += pumped
        applied = sim.suppress(*plan.fire, plan.application_radius_m, pumped * plan.delivery_fraction)
        self.applied_kg += applied
        self.state = "pumping" if self.water_left_l > 0 else "water_exhausted"
        return applied
