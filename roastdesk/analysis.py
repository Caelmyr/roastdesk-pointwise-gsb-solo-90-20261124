"""Segment visible bean silhouettes and measure their original source pixels."""

import cv2
import numpy as np

from image_lab.validation import Invalid

from . import split
from .frame import luma
from .model import MAX_COMPONENTS


def seeds(settings):
    """Return the applied seams keyed by the joined bean they replace."""
    return {item["bean"]: item["points"] for item in settings.get("splits", [])}


def silhouettes(rgb, settings):
    left, top, right, bottom = settings["box"]
    crop = rgb[top:bottom, left:right]
    foreground = (luma(crop) <= settings["threshold"]).astype(np.uint8)
    count, labels, stats, centers = cv2.connectedComponentsWithStats(foreground, connectivity=8)
    visible = [(label, stats[label], centers[label]) for label in range(1, count)
               if stats[label, cv2.CC_STAT_AREA] >= settings["minimum_area"]]
    if len(visible) > MAX_COMPONENTS:
        raise Invalid(f"More than {MAX_COMPONENTS} measurable shapes. Reduce the crop or raise minimum area.")
    return crop, labels, visible


def area_and_color(rgb_pixels):
    rgb_mean = rgb_pixels.mean(axis=0)
    brightness = luma(rgb_pixels)
    return {
        "area": len(rgb_pixels), "rgb": np.round(rgb_mean, 1).tolist(),
        "lightness": round(float(brightness.mean()), 2),
        "spread": round(float(brightness.std()), 2),
    }


def component_id(mask, x, y, left, top):
    """The position of the leftmost top pixel, stable while the shape is whole."""
    seed_column = int(np.flatnonzero(mask[0])[0])
    return f"{left + x + seed_column}:{top + y}"


def measure(mask, photo, offset, settings, bean_id, center, excluded):
    """Build one table row for a silhouette in local image coordinates."""
    area_color = area_and_color(photo[mask])
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outer = max(contours, key=cv2.contourArea)
    geometry = cv2.approxPolyDP(outer, 0.85, True)[:, 0] + offset
    tone = area_color["lightness"]
    if tone < settings["target_low"]:
        band = "dark"
    elif tone > settings["target_high"]:
        band = "light"
    else:
        band = "target"
    ys, xs = np.nonzero(mask)
    box = [int(offset[0] + xs.min()), int(offset[1] + ys.min()),
           int(offset[0] + xs.max() + 1), int(offset[1] + ys.max() + 1)]
    edge = (xs.min() == 0 or ys.min() == 0
            or box[2] == settings["box"][2] or box[3] == settings["box"][3])
    return {
        **area_color, "id": bean_id,
        "seed": [int(offset[0] + xs[0]), int(offset[1] + ys[0])],
        "center": [round(float(center[0] + offset[0]), 2), round(float(center[1] + offset[1]), 2)],
        "box": box, "outline": geometry.tolist(), "band": band,
        "touches_crop": bool(edge), "excluded": bean_id in excluded,
    }


def separate(mask, offset, settings, points):
    """Apply one stored seam to a shape, expressed in source coordinates."""
    local = [[point[0] - offset[0], point[1] - offset[1]] for point in points]
    return split.apply(mask, local, settings["minimum_area"])


def piece_ids(parts, offset, parent):
    """Stable keys for the two halves, never reusing the joined record's key."""
    labels = []
    for index, part in enumerate(parts):
        ys, xs = np.nonzero(part)
        key = f"{int(offset[0] + xs[0])}:{int(offset[1] + ys[0])}"
        if key == parent or key in labels:
            key = f"{key}#{index + 1}"
        labels.append(key)
    return labels


def leaves(mask, offset, settings, planned, bean_id, ancestors=()):
    """Resolve the stored seams for one shape down to its measured pieces.

    A shape is split only when its own seam still produces two measurable
    pieces; the halves are then checked for further adopted seams, so a clump
    of three can be taken apart in two steps without losing area.
    """
    points = planned.get(bean_id)
    if points is None or bean_id in ancestors:
        return [(bean_id, mask)]
    parts = separate(mask, offset, settings, points)
    if parts is None:
        return [(bean_id, mask)]
    result = []
    for part, child in zip(parts, piece_ids(parts, offset, bean_id)):
        result.extend(leaves(part, offset, settings, planned, child,
                             ancestors + (bean_id,)))
    return result


def bean_rows(crop, labels, visible, settings):
    left, top, right, bottom = settings["box"]
    excluded = set(settings["exclude"])
    planned = seeds(settings)
    rows = []
    for label, stats, center in visible:
        x, y, width, height, _ = map(int, stats)
        label_tile = labels[y:y + height, x:x + width]
        mask = label_tile == label
        photo_tile = crop[y:y + height, x:x + width]
        offset = [left + x, top + y]
        bean_id = component_id(mask, x, y, left, top)
        pieces = leaves(mask, offset, settings, planned, bean_id)
        if len(pieces) == 1:
            rows.append(measure(mask, photo_tile, offset, settings, bean_id, center, excluded))
            continue
        for child, part in pieces:
            ys, xs = np.nonzero(part)
            rows.append(measure(part, photo_tile, offset, settings, child,
                                (float(xs.mean()), float(ys.mean())), excluded))
    return sorted(rows, key=lambda bean: (bean["seed"][1], bean["seed"][0]))


def tray_summary(rows):
    included = [row for row in rows if not row["excluded"]]
    tones = np.array([row["lightness"] for row in included], dtype=np.float64)
    counts = {band: sum(row["band"] == band for row in included)
              for band in ("dark", "target", "light")}
    histogram, edges = np.histogram(tones, bins=16, range=(0, 256))
    return {
        "count": len(included), "excluded": len(rows) - len(included),
        "mean": round(float(tones.mean()), 2) if len(tones) else None,
        "median": round(float(np.median(tones)), 2) if len(tones) else None,
        "spread": round(float(tones.std()), 2) if len(tones) else None,
        "area": sum(row["area"] for row in included), "bands": counts,
        "histogram": [{"edge": int(edge), "count": int(count)}
                      for edge, count in zip(edges[:-1], histogram)],
    }


def inspect(rgb, settings):
    crop, labels, visible = silhouettes(rgb, settings)
    rows = bean_rows(crop, labels, visible, settings)
    return {"rows": rows, "settings": settings, "summary": tray_summary(rows)}


def branch(mask, offset, settings, planned, bean_id):
    """Find one shape in the applied seam tree, or ``None``."""
    points = planned.get(bean_id)
    parts = separate(mask, offset, settings, points) if points is not None else None
    if parts is None:
        return {"bean": bean_id, "mask": mask, "parts": None, "children": []}
    children = []
    for part, child in zip(parts, piece_ids(parts, offset, bean_id)):
        children.append(branch(part, offset, settings, planned, child))
    return {"bean": bean_id, "mask": mask, "parts": parts, "children": children}


def find(node, bean_id):
    if node["bean"] == bean_id:
        return node
    for child in node["children"]:
        found = find(child, bean_id)
        if found is not None:
            return found
    return None


def hint(rgb, settings, bean_id):
    """Propose a seam for one joined shape, or explain why it stays whole."""
    crop, labels, visible = silhouettes(rgb, settings)
    left, top = settings["box"][:2]
    planned = seeds(settings)
    for label, stats, _ in visible:
        x, y, width, height, _ = map(int, stats)
        mask = (labels[y:y + height, x:x + width] == label)
        original = component_id(mask, x, y, left, top)
        offset = [left + x, top + y]
        node = find(branch(mask, offset, settings, planned, original), bean_id)
        if node is None:
            continue
        local_ys, local_xs = np.nonzero(node["mask"])
        result = {"bean": bean_id, "minimum_area": settings["minimum_area"],
                  "box": [offset[0] + int(local_xs.min()), offset[1] + int(local_ys.min()),
                          offset[0] + int(local_xs.max()) + 1, offset[1] + int(local_ys.max()) + 1]}
        if node["parts"] is not None:
            result.update(possible=True, adopted=True, points=planned[bean_id],
                          pieces=[{"area": int(part.sum())} for part in node["parts"]])
            return result
        photo = crop[y:y + height, x:x + width]
        suggestion = split.suggest(node["mask"], photo, settings["minimum_area"])
        result.update(suggestion)
        result["adopted"] = False
        if suggestion["possible"]:
            result["points"] = [[round(point[0] + offset[0], 2),
                                 round(point[1] + offset[1], 2)]
                                for point in suggestion["points"]]
        elif suggestion.get("candidate"):
            result["reason"] = ("Two bean centers are visible, but no clean seam keeps both "
                                "pieces at the minimum area. Keep this shape as one bean.")
        return result
    raise Invalid("That bean is not measurable in the current crop.")


def locate(rgb, settings, point):
    x, y = point
    left, top, right, bottom = settings["box"]
    local_id = None
    if left <= x < right and top <= y < bottom:
        _, labels, visible = silhouettes(rgb, settings)
        label = labels[y - top, x - left]
        planned = seeds(settings)
        for candidate, stats, _ in visible:
            if candidate != label:
                continue
            sx, sy, width, height = map(int, stats[:4])
            mask = labels[sy:sy + height, sx:sx + width] == label
            offset = [left + sx, top + sy]
            node = branch(mask, offset, settings, planned,
                          component_id(mask, sx, sy, left, top))
            row, column = y - top - sy, x - left - sx
            while node["parts"] is not None:
                children = [child for child in node["children"] if child["mask"][row, column]]
                if not children:
                    break
                node = children[0]
            local_id = node["bean"]
            break
    color = rgb[y, x]
    return {"point": point, "rgb": color.tolist(), "lightness": round(float(luma(color)), 2),
            "bean": local_id}
