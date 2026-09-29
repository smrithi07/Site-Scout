"""Survey-unit partitioning over the catchment road graph (docs/DESIGN.md §7 Unit generation).
Pure functions (no DB) so the service, the tests and the benchmark share one implementation.

Graph: nodes = OSM junctions, edges = catchment segments. EVERY catchment segment is walkable, but
only `to_survey` segments are assigned to units — a unit can walk along a reused lane to reach
its next gap.

Workload of a unit (minutes) = Σ (segment length / walk speed + capture minutes per segment)
                               + walking to reach each segment from the rest of the unit.

Algorithm (config `studies.units.method`):
  k = ceil(total survey minutes / target unit minutes); each unit aims at total / k.
  peel (default) — one unit at a time from the edge of the remaining lanes, growing only through
     lanes that touch it (nearest its start first), jumping only when its stretch runs out.
  grow — all k units at once from spread-out seeds; the least-loaded unit takes its nearest lane.
     Balanced, but units interleave along one long stretch → more pieces (benchmark: DECISIONS 9b).
  Then smoothing hands stray pieces to a touching unit when both stay within [min, max] minutes.
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

    units = (_peel if cfg.get("method", "peel") == "peel" else _grow)(survey, adj, cfg, k, total)
    if cfg.get("smooth", True):
        _smooth(units, cfg, segs, adj)
    return [{"segment_ids": [m["segment_id"] for m in u["members"]], **estimate(segs, u["members"], cfg, adj)}
            for u in units]


def _grow(survey: list[dict], adj: dict, cfg: dict, k: int, total: float) -> list[dict]:
    """All units at once: least-loaded unit takes its nearest lane. Balanced, but units interleave
    along a long stretch (kept for the benchmark in docs/DECISIONS.md)."""
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
    return units


def _peel(survey: list[dict], adj: dict, cfg: dict, k: int, total: float) -> list[dict]:
    """Stretch-first. The to-survey lanes form connected stretches; a unit should never cut one it
    doesn't have to. Short stretches (< min minutes) attach to the nearest long stretch by road, so a
    stub becomes one planned hop inside a neighbouring unit instead of a tiny unit of its own. Each
    group is then one unit if it fits (≤ max minutes), else peeled into ⌈minutes / target⌉
    contiguous, balanced units."""
    lo, hi = cfg.get("min_unit_minutes", 0), cfg.get("max_unit_minutes", math.inf)
    mins = lambda lanes: sum(cost(s, cfg) for s in lanes)  # noqa: E731
    stretches = sorted(_components(survey), key=mins, reverse=True)
    big = [list(c) for c in stretches if mins(c) >= lo]
    small = [c for c in stretches if mins(c) < lo]
    if not big:                                   # only short stretches: plan them as one group
        big, small = [[s for c in small for s in c]], []
    anchors = [{n for s in g for n in (s["from_node"], s["to_node"])} for g in big]
    centres = [(sum(s["x"] for s in g) / len(g), sum(s["y"] for s in g) / len(g)) for g in big]
    for c in small:
        dist = _dijkstra(adj, {n for s in c for n in (s["from_node"], s["to_node"])})
        road = [min((dist.get(n, math.inf) for n in a), default=math.inf) for a in anchors]
        if min(road) < math.inf:
            i = road.index(min(road))
        else:                                     # not connected inside the catchment: straight line
            cx, cy = sum(s["x"] for s in c) / len(c), sum(s["y"] for s in c) / len(c)
            i = min(range(len(big)), key=lambda j: math.hypot(centres[j][0] - cx, centres[j][1] - cy))
        big[i] += c
    units = []
    for group in big:
        est = estimate([], group, cfg, adj)       # includes walking to attached stubs
        m = est["minutes"]
        if m <= hi:
            units.append({"members": group, "minutes": m, "walk_minutes": est["walk_minutes"]})
        else:
            units += _peel_stretch(group, adj, cfg, math.ceil(m / cfg["target_unit_minutes"]))
    return units


def _peel_stretch(survey: list[dict], adj: dict, cfg: dict, k: int) -> list[dict]:
    """Split ONE connected stretch into k contiguous units, one at a time, peeled off the edge of what
    is left: start at the remaining lane farthest
    from the remaining lanes' centre, then repeatedly take the lane that TOUCHES the unit and is
    nearest its start (compact, contiguous growth), until the unit is closest to its share (what is
    left ÷ units left). Jump to
    the nearest lane by road only when the unit's stretch runs out. Peeling from the edge keeps
    what remains connected, so later units stay contiguous too."""
    by_node = defaultdict(list)
    for s in survey:
        by_node[s["from_node"]].append(s)
        by_node[s["to_node"]].append(s)
    left = {s["segment_id"]: s for s in survey}
    units = []
    while left:
        # Re-aim every unit at what is left ÷ units left, so earlier overshoot never starves the last.
        share = sum(cost(t, cfg) for t in left.values()) / max(1, k - len(units))
        last_unit = len(units) >= k - 1
        rest = list(left.values())
        cx = sum(s["x"] for s in rest) / len(rest)
        cy = sum(s["y"] for s in rest) / len(rest)
        seed = max(rest, key=lambda s: math.hypot(s["x"] - cx, s["y"] - cy))
        from_seed = _dijkstra(adj, {seed["from_node"], seed["to_node"]})
        del left[seed["segment_id"]]
        u = {"members": [seed], "minutes": cost(seed, cfg), "walk_minutes": 0.0}
        nodes = {seed["from_node"], seed["to_node"]}
        while left:
            touching = {t["segment_id"]: t for n in nodes for t in by_node[n] if t["segment_id"] in left}
            if touching:
                nxt, walk_m = min(touching.values(), key=lambda t: _seg_dist(from_seed, t, [seed])), 0.0
            else:
                dist = _dijkstra(adj, nodes)
                walk_m, nxt = min(((_seg_dist(dist, t, u["members"]), t) for t in left.values()), key=lambda x: x[0])
            add = cost(nxt, cfg) + walk_m / cfg["walk_speed_m_per_min"]
            # stop where the unit is closest to its share (the last unit takes everything left)
            if not last_unit and abs(u["minutes"] + add - share) >= abs(u["minutes"] - share):
                break
            del left[nxt["segment_id"]]
            u["members"].append(nxt)
            u["minutes"] += add
            u["walk_minutes"] += walk_m / cfg["walk_speed_m_per_min"]
            nodes |= {nxt["from_node"], nxt["to_node"]}
        units.append(u)
    return units


def walk(segs: list[dict], members: list[dict], adj: dict | None = None) -> tuple[list[dict], float]:
    """A nearest-neighbour route through a unit's lanes: (lanes in walking order, metres walked
    between them). Starts at the lane farthest from the unit's centre, so the walk sweeps across."""
    if not members:
        return [], 0.0
    adj = adj or _graph(segs)
    cx = sum(m["x"] for m in members) / len(members)
    cy = sum(m["y"] for m in members) / len(members)
    cur = max(members, key=lambda m: math.hypot(m["x"] - cx, m["y"] - cy))
    order, left, walked = [cur], [m for m in members if m is not cur], 0.0
    while left:
        dist = _dijkstra(adj, {cur["from_node"], cur["to_node"]})
        d, cur = min(((_seg_dist(dist, s, [cur]), s) for s in left), key=lambda t: t[0])
        walked += d
        order.append(cur)
        left.remove(cur)
    return order, walked


def estimate(segs: list[dict], members: list[dict], cfg: dict, adj: dict | None = None) -> dict:
    """Workload of one unit: survey time + walking between its lanes along `walk()`. Used for
    generated units and again after every manual edit, so the numbers are always comparable."""
    if not members:
        return {"minutes": 0.0, "walk_minutes": 0.0, "length_m": 0.0, "pieces": 0}
    _, walked = walk(segs, members, adj)
    w = walked / cfg["walk_speed_m_per_min"]
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
