"""Plan the London demonstration pump routes from CloD's sampled street flags."""
import argparse
import heapq
import json
import math
from pathlib import Path

from PIL import Image, ImageFilter

ORIGIN = (148420, 273220)
SIZE = (321, 356)
STEP_M = 5
ROAD = 0x20
WATER = 0x1C
APPROACHES = (
    ((148870, 274072), (149060, 274235)),
    ((149945, 274713), (149822, 274605)),
    ((149555, 273514), (149591, 273723)),
    ((149911, 273621), (149950, 273765)),
)
NEIGHBORS = tuple((dx, dy, math.hypot(dx, dy)) for dy in (-1, 0, 1)
                  for dx in (-1, 0, 1) if dx or dy)


def to_world(point):
    return tuple(origin + pixel * STEP_M for origin, pixel in zip(ORIGIN, point))


def to_grid(point):
    return tuple(round((coord - origin) / STEP_M) for origin, coord in zip(ORIGIN, point))


def road_grid(survey_path):
    road = Image.new("L", SIZE)
    water = Image.new("L", SIZE)
    surveyed = set()
    with survey_path.open(encoding="ascii") as survey:
        for line in survey:
            fields = line.split()
            if not fields or fields[0] != "land":
                continue
            east, north, flags = map(int, fields[1:])
            point = to_grid((east, north))
            if to_world(point) != (east, north) or not all(0 <= p < n for p, n in zip(point, SIZE)):
                raise ValueError("Street sample is outside the 5 m London survey")
            surveyed.add(point)
            if flags & WATER == WATER:
                water.putpixel(point, 255)
            elif flags & ROAD:
                road.putpixel(point, 255)
    if len(surveyed) != math.prod(SIZE):
        raise ValueError("The London street survey is incomplete")

    # Close gaps between samples and give steering room on wider parts of the road.
    road_band = road.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(3))
    wide_band = road_band.filter(ImageFilter.MinFilter(3))
    return {(x, y): 1 if wide_band.getpixel((x, y)) else 2.5
            for x, y in surveyed if road_band.getpixel((x, y)) and not water.getpixel((x, y))}


def shortest_route(start, goal, street):
    queue = [(math.dist(start, goal), 0.0, start)]
    previous = {start: None}
    distance = {start: 0.0}
    while queue:
        _, cost, point = heapq.heappop(queue)
        if distance[point] != cost:
            continue
        if point == goal:
            route = []
            while point is not None:
                route.append(point)
                point = previous[point]
            return route[::-1]
        for dx, dy, step in NEIGHBORS:
            next_point = point[0] + dx, point[1] + dy
            if next_point not in street:
                continue
            if dx and dy and ((next_point[0], point[1]) not in street
                              or (point[0], next_point[1]) not in street):
                continue
            length = cost + step * street[next_point]
            if length < distance.get(next_point, math.inf):
                previous[next_point] = point
                distance[next_point] = length
                heapq.heappush(queue, (length + math.dist(next_point, goal), length, next_point))
    raise ValueError(f"No connected streets between {to_world(start)} and {to_world(goal)}")


def cut_points(first, last):
    count = max(1, math.ceil(2 * math.dist(first, last)))
    for step in range(count + 1):
        yield tuple(round(a + (b - a) * step / count) for a, b in zip(first, last))


def waypoints(route, street):
    points = [route[0]]
    start = 0
    while start < len(route) - 1:
        for end in range(len(route) - 1, start, -1):
            if math.dist(route[start], route[end]) < 3 and end < len(route) - 1:
                continue
            shortcut = tuple(cut_points(route[start], route[end]))
            if not all(point in street for point in shortcut):
                continue
            full = route[start:end + 1]
            if (sum(street[point] for point in shortcut) / len(shortcut)
                    <= sum(street[point] for point in full) / len(full) + 0.45):
                break
        points.append(route[end])
        start = end
    world_points = [to_world(point) for point in points]
    if not 2 <= len(world_points) <= 16 or any(
            math.dist(a, b) < 10 for a, b in zip(world_points, world_points[1:])):
        raise ValueError("The road route exceeds CloD mission waypoint limits")
    return world_points


def plan(survey_path):
    street = road_grid(survey_path)
    routes = []
    for depot, staging in APPROACHES:
        candidates = to_grid(depot), to_grid(staging)
        goal = candidates[1]
        nearby = {point: weight for point, weight in street.items()
                  if all(abs(p - q) < 70 for p, q in zip(point, goal))}
        start, end = (min(nearby, key=lambda point: (math.dist(point, target) + nearby[point] - 1, point))
                      for target in candidates)
        if math.dist(start, candidates[0]) > 6 or math.dist(end, candidates[1]) > 6:
            raise ValueError("No street within 30 m of the planned depot or hose stop")
        routes.append(waypoints(shortest_route(start, end, nearby), nearby))
    return routes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("survey", type=Path, help="TSV of the verified 5 m CloD terrain survey")
    parser.add_argument("output", type=Path, help="Route profile for the capture generator")
    args = parser.parse_args()
    args.output.write_text(json.dumps({"routes": plan(args.survey)}, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
