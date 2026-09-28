"""Survey-unit partitioning over the catchment road graph (docs/DESIGN.md §7 Unit generation).
Pure functions (no DB) so the service, the tests and the benchmark share one implementation.

Graph: nodes = OSM junctions, edges = catchment segments. EVERY catchment segment is walkable, but
only `to_survey` segments are assigned to units — a unit can walk along a reused lane to reach
its next gap.

Workload of a unit (minutes) = Σ (segment length / walk speed + capture minutes per segment)
                               + walking to reach each segment from the rest of the unit.

Algorithm ("balanced region growing"):
  1. k = ceil(total survey minutes / target unit minutes).
  2. Seeds: farthest-point sampling by network distance, so units start spread out.
  3. Grow: repeatedly take the least-loaded unit and give it the unassigned survey segment
     nearest to it along the road graph (Dijkstra from the unit's junctions); the walk to reach it
     is added to that unit's load. Least-loaded-first balances; nearest-first keeps units compact.
Segments unreachable over the catchment graph fall back to straight-line distance × 1.4.
"""
import heapq
import math
from collections import defaultdict

DETOUR = 1.4   # straight line → street distance, for pieces not connected inside the catchment


def _graph(segs: list[dict]) -> dict:
    adj = defaultdict(list)
    for s in segs:
        adj[s["from_node"]].append((s["to_node"], s["length_m"]))
        adj[s["to_node"]].append((s["from_node"], s["length_m"]))
    return adj


def _dijkstra(adj: dict, sources: set) -> dict:
    dist = {n: 0.0 for n in sources}
    heap = [(0.0, n) for n in sources]
    while heap:
        d, n = heapq.heappop(heap)
        if d > dist.get(n, math.inf):
            continue
        for m, w in adj[n]:
            nd = d + w
            if nd < dist.get(m, math.inf):
                dist[m] = nd
                heapq.heappush(heap, (nd, m))
    return dist


def _seg_dist(dist: dict, s: dict, members: list[dict]) -> float:
    d = min(dist.get(s["from_node"], math.inf), dist.get(s["to_node"], math.inf))
    if d < math.inf:
        return d
    return DETOUR * min(math.hypot(s["x"] - m["x"], s["y"] - m["y"]) for m in members)


def cost(s: dict, cfg: dict) -> float:
    return s["length_m"] / cfg["walk_speed_m_per_min"] + cfg["capture_minutes_per_segment"]


def partition(segs: list[dict], survey_ids: set[str], cfg: dict) -> list[dict]:
    """segs: every catchment segment {segment_id, from_node, to_node, length_m, x, y (metres)}.
    Returns [{segment_ids, minutes, walk_minutes}] covering each survey segment exactly once."""
    survey = [s for s in segs if s["segment_id"] in survey_ids]
    if not survey:
        return []
    adj = _graph(segs)
    total = sum(cost(s, cfg) for s in survey)
    k = max(1, min(len(survey), math.ceil(total / cfg["target_unit_minutes"])))

    # 1. seeds: start from the segment farthest from the centroid, then farthest-point by network.
    cx = sum(s["x"] for s in survey) / len(survey)
    cy = sum(s["y"] for s in survey) / len(survey)
    seeds = [max(survey, key=lambda s: math.hypot(s["x"] - cx, s["y"] - cy))]
    while len(seeds) < k:
        dist = _dijkstra(adj, {n for s in seeds for n in (s["from_node"], s["to_node"])})
        chosen = {s["segment_id"] for s in seeds}
        seeds.append(max((s for s in survey if s["segment_id"] not in chosen),
                         key=lambda s: _seg_dist(dist, s, seeds)))

    # 2. balanced growth
    units = [{"members": [s], "minutes": cost(s, cfg), "walk_minutes": 0.0} for s in seeds]
    left = {s["segment_id"]: s for s in survey}
    for s in seeds:
        del left[s["segment_id"]]
    while left:
        u = min(units, key=lambda u: u["minutes"])
        dist = _dijkstra(adj, {n for m in u["members"] for n in (m["from_node"], m["to_node"])})
        d, nxt = min(((_seg_dist(dist, s, u["members"]), s) for s in left.values()), key=lambda t: t[0])
        walk = d / cfg["walk_speed_m_per_min"]
        u["members"].append(nxt)
        u["minutes"] += cost(nxt, cfg) + walk
        u["walk_minutes"] += walk
        del left[nxt["segment_id"]]
    if cfg.get("smooth", True):
        _smooth(units, cfg, segs, adj)
    return [{"segment_ids": [m["segment_id"] for m in u["members"]], **estimate(segs, u["members"], cfg, adj)}
            for u in units]


def estimate(segs: list[dict], members: list[dict], cfg: dict, adj: dict | None = None) -> dict:
    """Workload of one unit: survey time + a nearest-neighbour walk between its segments. Used for
    generated units and again after every manual edit, so the numbers are always comparable."""
    adj = adj or _graph(segs)
    if not members:
        return {"minutes": 0.0, "walk_minutes": 0.0, "length_m": 0.0, "pieces": 0}
    left, cur, walk = list(members[1:]), members[0], 0.0
    while left:
        dist = _dijkstra(adj, {cur["from_node"], cur["to_node"]})
        d, cur = min(((_seg_dist(dist, s, [cur]), s) for s in left), key=lambda t: t[0])
        walk += d
        left.remove(cur)
    w = walk / cfg["walk_speed_m_per_min"]
    return {"minutes": round(sum(cost(m, cfg) for m in members) + w, 1), "walk_minutes": round(w, 1),
            "length_m": round(sum(m["length_m"] for m in members), 1), "pieces": pieces(members)}


def _components(members: list[dict]) -> list[list[dict]]:
    by_node = defaultdict(list)
    for m in members:
        by_node[m["from_node"]].append(m)
        by_node[m["to_node"]].append(m)
    seen, out = set(), []
    for m in members:
        if m["segment_id"] in seen:
            continue
        comp, stack = [], [m]
        seen.add(m["segment_id"])
        while stack:
            s = stack.pop()
            comp.append(s)
            for n in (s["from_node"], s["to_node"]):
                for t in by_node[n]:
                    if t["segment_id"] not in seen:
                        seen.add(t["segment_id"])
                        stack.append(t)
        out.append(comp)
    return out


def _smooth(units: list[dict], cfg: dict, segs: list[dict], adj: dict, rounds: int = 3) -> None:
    """Give each unit's stray pieces (not its largest) to a unit they touch, if both units stay
    within [min_unit_minutes, max_unit_minutes] by the same estimate() the UI shows — fewer
    disconnected pieces without losing balance."""
    cap = cfg.get("max_unit_minutes", cfg["target_unit_minutes"] * 1.2)
    floor = cfg.get("min_unit_minutes", cfg["target_unit_minutes"] * 0.8)
    for u in units:
        u["minutes"] = estimate(segs, u["members"], cfg, adj)["minutes"]
    for _ in range(rounds):
        moved = False
        for i, u in enumerate(units):
            comps = sorted(_components(u["members"]), key=len, reverse=True)
            for piece in comps[1:]:
                piece_nodes = {n for s in piece for n in (s["from_node"], s["to_node"])}
                ids = {s["segment_id"] for s in piece}
                rest = [m for m in u["members"] if m["segment_id"] not in ids]
                donor = estimate(segs, rest, cfg, adj)["minutes"]
                if donor < floor:
                    continue
                best = None
                for j, v in enumerate(units):
                    if j == i or not piece_nodes & {n for m in v["members"] for n in (m["from_node"], m["to_node"])}:
                        continue
                    after = estimate(segs, v["members"] + piece, cfg, adj)["minutes"]
                    if after <= cap and (best is None or after < best[1]):
                        best = (j, after)
                if best is None:
                    continue
                j, after = best
                u["members"], u["minutes"] = rest, donor
                units[j]["members"] = units[j]["members"] + piece
                units[j]["minutes"] = after
                moved = True
        if not moved:
            break


def pieces(segs: list[dict]) -> int:
    """Connected pieces within one unit (segments sharing a junction are connected)."""
    return len(_components(segs))
