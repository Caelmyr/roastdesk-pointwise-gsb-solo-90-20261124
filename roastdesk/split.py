"""Suggest and apply a seam that separates two touching beans."""

import math

import cv2
import numpy as np
from scipy import ndimage as ndi

from .frame import luma

MAX_POINTS = 400
SAMPLE_LIMIT = 30000
PROFILE_LIMIT = 120000
DETECT_SIZE = 640
BRIDGE_COST = 0.72
BRIGHTNESS_OFFSET = 0.02
CURVATURE_COST = 0.08


def _peaks(distance, size):
    """Interior points where the distance to the edge is locally largest."""
    footprint = np.ones((size, size), bool)
    ridges = (distance == ndi.maximum_filter(distance, footprint=footprint, mode="constant"))
    ridges &= distance > 0.5
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ridges.astype(np.uint8),
                                                               connectivity=8)
    found = []
    for label in range(1, count):
        ys, xs = np.nonzero(labels == label)
        if not xs.size:
            continue
        index = int(np.argmax(distance[ys, xs]))
        found.append((float(distance[ys[index], xs[index]]),
                      float(xs[index]), float(ys[index])))
    found.sort(reverse=True)
    return found


def _bottleneck(distance, first, second):
    """Widest interior passage between two peaks (highest distance level)."""
    low, high = 0.0, min(first[0], second[0])
    for _ in range(18):
        middle = (low + high) / 2
        count, labels = cv2.connectedComponents(
            (distance >= middle).astype(np.uint8), connectivity=8)
        same = (labels[int(round(first[2])), int(round(first[1]))]
                == labels[int(round(second[2])), int(round(second[1]))])
        if same:
            low = middle
        else:
            high = middle
    return low


def _pair(mask, minimum_area):
    """Return the two centers of a joined pair, or ``None``.

    Two touching beans leave two separate distance crests, and every interior
    route between them must cross a shallower neck. A single bean keeps one
    crest; a curved bean may show several crests but any route between them
    stays deep, so it is not mistaken for a pair. Very large shapes are judged
    on a reduced copy and the centers are mapped back.
    """
    height, width = mask.shape
    scale = min(1.0, DETECT_SIZE / max(height, width))
    if scale < 1:
        small = cv2.resize(mask.astype(np.float32), (max(1, round(width * scale)),
                                                     max(1, round(height * scale))),
                           interpolation=cv2.INTER_AREA) > 0.5
    else:
        small = mask
    distance = cv2.distanceTransform(small.astype(np.uint8), cv2.DIST_L2, 5)
    if float(distance.max()) < 2:
        return None
    radius = math.sqrt(max(minimum_area, 1) / math.pi) * scale
    size = max(3, int(round(radius * 0.9)) * 2 + 1)
    peaks = _peaks(distance, size)
    if len(peaks) < 2:
        return None
    peaks = [peak for peak in peaks if peak[0] >= 0.2 * peaks[0][0]][:8]
    best = None
    for first in range(len(peaks)):
        for second in range(first + 1, len(peaks)):
            gap = math.hypot(peaks[first][1] - peaks[second][1],
                             peaks[first][2] - peaks[second][2])
            if gap < 1.2 * radius:
                continue
            neck = _bottleneck(distance, peaks[first], peaks[second])
            low, high = sorted((peaks[first][0], peaks[second][0]))
            waist = neck / high
            if waist > 0.90:
                continue
            score = waist + 0.25 * (low / high)
            if best is None or score < best[0]:
                best = (score, peaks[first], peaks[second])
    if best is None:
        return None
    centers = []
    ys, xs = np.nonzero(mask)
    for peak in best[1:]:
        column = peak[1] / scale
        row = peak[2] / scale
        if scale < 1:
            index = int(np.argmin((xs - column) ** 2 + (ys - row) ** 2))
            column, row = float(xs[index]), float(ys[index])
        centers.append((peak[0] / scale, column, row))
    return {"first": centers[0], "second": centers[1]}


def _profile(points, first, second):
    """Locate the narrowest crossing between the two centers."""
    axis = np.asarray(second, np.float64) - np.asarray(first, np.float64)
    length = float(np.linalg.norm(axis))
    if length < 2:
        return None
    axis /= length
    across = np.array([-axis[1], axis[0]])
    relative = points - np.asarray(first, np.float64)
    along = relative @ axis
    width = relative @ across
    positions = np.linspace(0.24, 0.76, 53)
    spans = np.asarray([float(np.ptp(width[band])) if band.sum() > 1 else 0.0
                        for band in (np.abs(along - position * length) <= 1.5
                                     for position in positions)], np.float64)
    spans = ndi.uniform_filter1d(spans, 5)
    index = int(np.argmin(spans))
    return {"axis": axis, "across": across, "length": length,
            "waist": float(positions[index]), "first": np.asarray(first, np.float64)}


def _rotated(vector, angle):
    cosine, sine = math.cos(angle), math.sin(angle)
    return np.array([vector[0] * cosine - vector[1] * sine,
                     vector[0] * sine + vector[1] * cosine])


def _endpoints(reference, direction, points):
    """Extend a straight crossing past both silhouette edges."""
    along = points @ direction
    low = float((along - reference @ direction).min()) - 3
    high = float((along - reference @ direction).max()) + 3
    return np.array([reference + direction * low, reference + direction * high])


def _straight(points, ys, xs, brightness, profile, minimum_area):
    """Score short straight seams that stay clear of the silhouette tips.

    Large shapes are scored on a fixed subsample so the candidate sweep stays
    quick; the winning cut is always checked exactly before it is offered.
    """
    stride = max(1, math.ceil(len(points) / SAMPLE_LIMIT))
    required = minimum_area / stride
    if stride > 1:
        points = points[::stride]
        ys, xs = ys[::stride], xs[::stride]
    across = profile["across"]
    length = profile["length"]
    first = profile["first"]
    waist = profile["waist"]
    choices = []
    for position in np.linspace(max(0.2, waist - 0.12), min(0.8, waist + 0.12), 13):
        for angle in np.deg2rad(np.arange(-24, 24.1, 3)):
            normal = _rotated(across, float(angle))
            reference = first + profile["axis"] * (position * length)
            side = (points - reference) @ normal
            left, right = int((side >= 0).sum()), int((side < 0).sum())
            if left < required or right < required:
                continue
            near = np.abs(side) <= 2.5
            if near.sum() < 4:
                continue
            darkness = float(brightness[ys[near], xs[near]].mean()) if brightness is not None else 0.0
            score = darkness + 0.12 * abs(position - waist) + 0.002 * abs(angle)
            choices.append((score, reference, normal))
    choices.sort(key=lambda item: item[0])
    return choices


def _normalized(gray, mask):
    values = gray[mask]
    if not values.size:
        return None
    low = float(np.percentile(values, 5))
    high = float(np.percentile(values, 95))
    if high - low < 10:
        return None
    return np.clip((gray - low) / (high - low), 0, 1).astype(np.float32)


def _trace(mask, brightness, profile, candidate):
    """Follow the darkest gently curving crossing inside a corridor."""
    _, reference, normal = candidate
    along = np.array([-normal[1], normal[0]])
    if along @ profile["axis"] < 0:
        along = -along
    ys, xs = np.nonzero(mask)
    points = np.column_stack([xs, ys]).astype(np.float64)
    relative = points - reference
    across = relative @ normal
    depth = relative @ along
    low, high = float(across.min()) - 2, float(across.max()) + 2
    span = float(np.percentile(depth, 99) - np.percentile(depth, 1))
    half = int(np.clip(round(span * 0.12), 2, 12))
    rows = np.arange(math.floor(low), math.ceil(high) + 1, dtype=np.float64)
    offsets = np.arange(-half, half + 1, dtype=np.float64)
    x = reference[0] + normal[0] * rows[:, None] + along[0] * offsets[None, :]
    y = reference[1] + normal[1] * rows[:, None] + along[1] * offsets[None, :]
    xi = np.clip(np.rint(x).astype(np.int32), 0, mask.shape[1] - 1)
    yi = np.clip(np.rint(y).astype(np.int32), 0, mask.shape[0] - 1)
    inside = mask[yi, xi]
    cost = np.where(inside, brightness[yi, xi], BRIDGE_COST).astype(np.float64)
    cost += BRIGHTNESS_OFFSET * np.abs(offsets)[None, :] / max(half, 1)
    accumulated = cost[0].copy()
    backtrack = np.zeros((len(rows), len(offsets)), np.int16)
    index = np.arange(len(offsets))
    transition = CURVATURE_COST * np.abs(index[:, None] - index[None, :])
    for row in range(1, len(rows)):
        total = accumulated[:, None] + transition
        choice = total.argmin(axis=0)
        accumulated = cost[row] + total[choice, index]
        backtrack[row] = choice
    offset = int(accumulated.argmin())
    path = []
    for row in range(len(rows) - 1, -1, -1):
        path.append((reference[0] + normal[0] * rows[row] + along[0] * offsets[offset],
                     reference[1] + normal[1] * rows[row] + along[1] * offsets[offset]))
        offset = int(backtrack[row, offset])
    path.reverse()
    return np.rint(_trim(path, mask)).astype(np.int32)


def _walk_to_edge(points, mask):
    """Continue both ends along the cut until they leave the silhouette."""
    points = np.asarray(points, np.float64)
    height, width = mask.shape

    def beyond(end, neighbor):
        direction = points[end] - points[neighbor]
        length = float(np.linalg.norm(direction))
        if length < 1e-6:
            return np.empty((0, 2))
        direction /= length
        walk = []
        for step in range(1, 65):
            candidate = points[end] + direction * step
            column, row = int(round(candidate[0])), int(round(candidate[1]))
            walk.append(candidate)
            if not (0 <= row < height and 0 <= column < width and mask[row, column]):
                walk.append(candidate + direction)
                break
        return np.asarray(walk)

    start = beyond(0, 1)
    finish = beyond(-1, -2)
    return np.vstack([start[::-1], points, finish]) if len(start) else np.vstack([points, finish])


def _trim(points, mask):
    """Keep the on-shape stretch of a cut, for showing it on the photo."""
    points = np.asarray(points, np.float64)
    height, width = mask.shape
    columns = np.clip(np.rint(points[:, 0]).astype(np.int32), 0, width - 1)
    rows = np.clip(np.rint(points[:, 1]).astype(np.int32), 0, height - 1)
    inside = mask[rows, columns]
    if not inside.any():
        return points
    first = int(np.argmax(inside))
    last = len(inside) - int(np.argmax(inside[::-1])) - 1
    return points[first:last + 1]


def _path_cost(mask, brightness, points):
    """Mean darkness of a cut, sampled along its in-shape stretch."""
    points = np.asarray(points, np.float64)
    if brightness is None or len(points) < 2:
        return None
    steps = np.linspace(0, len(points) - 1, max(len(points), 240))
    x = np.interp(steps, np.arange(len(points)), points[:, 0])
    y = np.interp(steps, np.arange(len(points)), points[:, 1])
    xi = np.clip(np.rint(x).astype(np.int32), 0, mask.shape[1] - 1)
    yi = np.clip(np.rint(y).astype(np.int32), 0, mask.shape[0] - 1)
    inside = mask[yi, xi]
    if inside.sum() < 4:
        return None
    return float(brightness[yi[inside], xi[inside]].mean())


def _length(points):
    points = np.asarray(points, np.float64)
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _separate(mask, points):
    """Split a mask along a polyline; the two pieces tile the original exactly.

    Both ends are extended along the cut until they leave the silhouette, so a
    stored seam that stops at the outline still separates the whole shape.
    """
    points = np.asarray(points, np.float64)
    if len(points) < 2:
        return None
    points = _walk_to_edge(points, mask)
    height, width = mask.shape
    pad = 4
    padded = np.zeros((height + pad * 2, width + pad * 2), np.uint8)
    padded[pad:pad + height, pad:pad + width] = mask.astype(np.uint8)
    coordinates = np.rint(points + pad).astype(np.int32).reshape(-1, 1, 2)
    for thickness in (2, 1):
        barrier = np.zeros_like(padded)
        cv2.polylines(barrier, [coordinates], False, 1, thickness=thickness,
                      lineType=cv2.LINE_8)
        barrier = (barrier > 0) & (padded > 0)
        remaining = ((padded > 0) & ~barrier).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(remaining, connectivity=4)
        regions = [label for label in range(1, count)
                   if stats[label, cv2.CC_STAT_AREA] >= max(3, 0.002 * int(mask.sum()))]
        if len(regions) != 2:
            continue
        split = np.zeros_like(labels, np.uint8)
        for index, label in enumerate(regions, 1):
            split[labels == label] = index
        first = cv2.distanceTransform((split != 1).astype(np.uint8), cv2.DIST_L2, 5)
        second = cv2.distanceTransform((split != 2).astype(np.uint8), cv2.DIST_L2, 5)
        first = np.where(split == 1, 0, first)
        second = np.where(split == 2, 0, second)
        pending = (padded > 0) & (split == 0)
        split[pending & (first <= second)] = 1
        split[pending & (first > second)] = 2
        parts = []
        for index in (1, 2):
            part = (split == index)[pad:pad + height, pad:pad + width]
            inner, _ = cv2.connectedComponents(part.astype(np.uint8), connectivity=4)
            if inner != 2:
                break
            parts.append(part)
        else:
            if sum(int(part.sum()) for part in parts) == int(mask.sum()):
                return parts
    return None


def _contains(parts, centers):
    """Each center must land in its own piece."""
    found = [0, 0]
    for part in parts:
        for index, center in enumerate(centers[:2]):
            column, row = int(round(center[1])), int(round(center[2]))
            if 0 <= row < part.shape[0] and 0 <= column < part.shape[1] and part[row, column]:
                found[index] += 1
    return found == [1, 1]


def _usable(parts, centers, minimum_area):
    return (parts is not None
            and all(int(part.sum()) >= minimum_area for part in parts)
            and _contains(parts, centers))


def _simplify(points):
    array = np.rint(np.asarray(points)).astype(np.int32).reshape(-1, 1, 2)
    simplified = cv2.approxPolyDP(array, 0.85, False).reshape(-1, 2)
    if len(simplified) > MAX_POINTS:
        simplified = simplified[::math.ceil(len(simplified) / MAX_POINTS)]
    return simplified.tolist()


def _candidate(points, mask, centers, minimum_area):
    """A stored form of the cut that splits exactly as proposed.

    The simplified polyline is preferred; a dense cut is kept only when
    simplifying would move the seam enough to change the two pieces.
    """
    simplified = _simplify(points)
    parts = _separate(mask, simplified)
    if _usable(parts, centers, minimum_area):
        return {"points": simplified, "parts": parts}
    dense = np.rint(np.asarray(points, np.float64)).astype(np.int32).tolist()
    if len(dense) > MAX_POINTS:
        return None
    parts = _separate(mask, dense)
    if _usable(parts, centers, minimum_area):
        return {"points": dense, "parts": parts}
    return None


def _response(candidate, mode):
    return {"possible": True, "points": candidate["points"], "mode": mode,
            "pieces": [{"area": int(part.sum())} for part in candidate["parts"]]}


def _rejection(area, minimum_area, reason, candidate=False):
    return {"possible": False, "candidate": candidate, "area": area,
            "minimum_area": minimum_area, "reason": reason}


def suggest(mask, photo, minimum_area):
    """Measure one component and propose a two-bean seam when that is defensible."""
    mask = np.ascontiguousarray(mask.astype(bool))
    area = int(mask.sum())
    if area < 2 * minimum_area:
        return _rejection(area, minimum_area,
                          f"This shape has {area} px²; two measurable beans need at least "
                          f"{2 * minimum_area} px² together. Keep it as one shape.")
    pair = _pair(mask, minimum_area)
    if pair is None:
        return _rejection(area, minimum_area,
                          "This shape has no two-bean waist. Keep it as one bean.")
    centers = [pair["first"], pair["second"]]
    ys, xs = np.nonzero(mask)
    stride = max(1, math.ceil(len(xs) / PROFILE_LIMIT))
    points = np.column_stack([xs[::stride], ys[::stride]]).astype(np.float64)
    profile = _profile(points, (pair["second"][1], pair["second"][2]),
                       (pair["first"][1], pair["first"][2]))
    if profile is None:
        return _rejection(area, minimum_area,
                          "This shape has no two-bean waist. Keep it as one bean.",
                          candidate=True)
    brightness = _normalized(luma(photo), mask)
    choices = _straight(points, ys[::stride], xs[::stride], brightness, profile, minimum_area)
    if not choices:
        return _rejection(area, minimum_area,
                          f"No dividing line leaves two pieces of at least {minimum_area} px². "
                          "Keep this shape as one bean.", candidate=True)
    for candidate in choices[:3]:
        straight = _endpoints(candidate[1], candidate[2], points)
        straight_parts = _separate(mask, straight)
        straight_ok = _usable(straight_parts, centers, minimum_area)
        if brightness is not None:
            traced = _trace(mask, brightness, profile, candidate)
            traced_parts = _separate(mask, traced)
            if _usable(traced_parts, centers, minimum_area):
                if not straight_ok:
                    answer = _candidate(traced, mask, centers, minimum_area)
                    if answer is not None:
                        return _response(answer, "seam")
                straight_cost = _path_cost(mask, brightness, straight)
                traced_cost = _path_cost(mask, brightness, traced)
                if (straight_cost is not None and traced_cost is not None
                        and traced_cost + 0.03 <= straight_cost
                        and _length(traced) <= 1.3 * _length(straight)):
                    answer = _candidate(traced, mask, centers, minimum_area)
                    if answer is not None:
                        return _response(answer, "seam")
        if straight_ok:
            answer = _candidate(straight, mask, centers, minimum_area)
            if answer is not None:
                return _response(answer, "straight")
    return _rejection(area, minimum_area,
                      "A clean two-bean split is not possible without cutting a fragment. "
                      "Keep this shape as one bean.", candidate=True)


def _array(points):
    if not isinstance(points, (list, tuple, np.ndarray)) or len(points) < 2:
        return None
    try:
        array = np.asarray(points, np.float64)
    except (TypeError, ValueError):
        return None
    if array.ndim != 2 or array.shape[1] != 2 or not np.isfinite(array).all():
        return None
    return array


def apply(mask, points, minimum_area):
    """Separate one component using stored seam points, or return ``None``."""
    mask = np.ascontiguousarray(mask.astype(bool))
    array = _array(points)
    if array is None:
        return None
    parts = _separate(mask, array)
    if parts is None or any(int(part.sum()) < minimum_area for part in parts):
        return None
    return parts
