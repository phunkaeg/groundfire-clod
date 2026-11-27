# Implementation notes

## Mission and bridge

CloD's C# script appends typed, sequenced events to the active mission log. The Python bridge uses the mission clock, publishes the desired effects, and calculates suppression from position and fuel state. Day and night bridges use different local state folders under **%LOCALAPPDATA%\GroundFireHawkinge**.

The release carries a derived 20 m terrain classification. Its bridge excludes water from fuel and rejects hose lines crossing water. The replay renderer draws a fuel overview when the optional stock navigation chart is unavailable.

## Smoke material

The authored [material](../effects/WarmSmokePlume.mma) selects the existing **ParticleAdd_Emmisive** painter. The lower, middle and upper [particle definitions](../effects/) share their particle motion and size curves and use different color and opacity ramps. Emission fades with particle age as the plume rises. The mission blends the three profiles according to smoothed fire intensity. Separate dark smoke carries the plume above the glow. Warm district point lights illuminate nearby scenery.

The installer reads **Smoke_Sprites_Air_W.dds** from the local game's core archive for the optional night setup. It copies this atlas to the user profile.

## Sunset and sunrise

The lighting-enabled London missions use CloD's mission clock, the mission date, and the Channel map's configured latitude, longitude and time zone. Added point lights and warm smoke start at calculated sunset, ramp up as the sun drops, and fade out by calculated sunrise. Base smoke and flame effects render independently. The clock follows mission acceleration and advances the date at midnight. The gate uses estimated solar elevation, so the native renderer's apparent horizon may differ slightly. [NOAA solar position method](https://gml.noaa.gov/grad/solcalc/solareqns.PDF)

## Street planning

The [survey tool](../tools/road-survey/) samples **gpLandType** at 5 m intervals and also probes the game's ground pathfinder. Its road flags exposed local streets that were missing from the extracted road mesh. Direct **gpFindPath** results led through city blocks on the original approaches.

The [routing tool](../integrations/clod/plan_london_crew_routes.py) grows the sampled road corridors, excludes water, favors clearance and uses A* to produce waypoints. The [revised profile](../integrations/clod/london_city_matched_routes.json) was refined by comparing prior truck positions with the survey and moving staging within hose reach. It uses short runs along clear streets without sharp final turns. The mission loads routes with **gpPostMissionLoad**, then checks that each native truck is stopped near its staging point before pumping.

The previous close-ups drove model transforms from interpolated positions. Live capture uses CloD's own heading, steering and suspension. The [matched-trial builder](../integrations/clod/prepare_london_crew_trial.py) accepts **--follow-pump** with a pump number from 1 to 4 for repeatable native vehicle views. At roughly one-second sample intervals, the measured travel of all four revised trucks aligned within 20 degrees of their native body heading.

The prior and revised trials received matching impact types, world coordinates and times relative to the first impact. The fixture reproduces ignition and runs native truck movement. It omits blast and structural damage. Automatic obstacle detours and other city maps require their own validation.
