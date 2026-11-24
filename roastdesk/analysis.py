"""Segment visible bean silhouettes and measure their original source pixels."""

import cv2
import numpy as np

from image_lab.validation import Invalid

from .frame import luma
from .model import MAX_COMPONENTS


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


def bean_rows(crop, labels, visible, settings):
    left, top, right, bottom = settings["box"]
    excluded = set(settings["exclude"])
    rows = []
    for label, stats, center in visible:
        x, y, width, height, _ = map(int, stats)
        label_tile = labels[y:y + height, x:x + width]
        mask = label_tile == label
        photo_tile = crop[y:y + height, x:x + width]
        area_color = area_and_color(photo_tile[mask])
        seed_column = int(np.flatnonzero(mask[0])[0])
        bean_id = f"{left + x + seed_column}:{top + y}"
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        outer = max(contours, key=cv2.contourArea)
        geometry = cv2.approxPolyDP(outer, 0.85, True)[:, 0] + [left + x, top + y]
        tone = area_color["lightness"]
        if tone < settings["target_low"]:
            band = "dark"
        elif tone > settings["target_high"]:
            band = "light"
        else:
            band = "target"
        edge = x == 0 or y == 0 or left + x + width == right or top + y + height == bottom
        rows.append({
            **area_color, "id": bean_id, "seed": [left + x + seed_column, top + y],
            "center": [round(float(center[0] + left), 2), round(float(center[1] + top), 2)],
            "box": [left + x, top + y, left + x + width, top + y + height],
            "outline": geometry.tolist(), "band": band, "touches_crop": edge,
            "excluded": bean_id in excluded,
        })
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


def recommend_window(rows, settings, size):
    """Place one fixed-size review window inside the current crop.

    Only beans whose full bounding box lands inside the window are counted and
    excluded beans never count. A placement is valid only when no measured bean
    straddles its edge, so adopting the window as the new crop can never split a
    bean, and when it holds at least one light and two target-band beans for
    color reference. Valid placements prefer the most light beans, then the
    fewest crowding beans of other bands, then the topmost-leftmost spot.
    """
    left, top, right, bottom = settings["box"]
    crop_width, crop_height = right - left, bottom - top
    if (not isinstance(size, list) or len(size) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in size)):
        raise Invalid("Give the review window size as a whole-pixel width and height.")
    width, height = size
    if not 1 <= width <= crop_width or not 1 <= height <= crop_height:
        raise Invalid(f"Review window size must fit inside the crop: 1–{crop_width} × 1–{crop_height} px.")
    columns, lanes = crop_width - width + 1, crop_height - height + 1
    cut = np.zeros((lanes + 1, columns + 1), dtype=np.int32)
    bands = {band: np.zeros((lanes + 1, columns + 1), dtype=np.int32)
             for band in ("dark", "target", "light")}

    def stamp(grid, x_from, x_to, y_from, y_to, delta):
        col_from = max(x_from, left) - left
        row_from = max(y_from, top) - top
        col_to = min(x_to, right - width) - left
        row_to = min(y_to, bottom - height) - top
        if col_from > col_to or row_from > row_to:
            return
        grid[row_from, col_from] += delta
        grid[row_from, col_to + 1] -= delta
        grid[row_to + 1, col_from] -= delta
        grid[row_to + 1, col_to + 1] += delta

    for bean in rows:
        x1, y1, x2, y2 = bean["box"]
        stamp(cut, x1 - width + 1, x2 - 1, y1 - height + 1, y2 - 1, 1)
        stamp(cut, x2 - width, x1, y2 - height, y1, -1)
        if not bean["excluded"]:
            stamp(bands[bean["band"]], x2 - width, x1, y2 - height, y1, 1)
    for grid in (cut, *bands.values()):
        np.cumsum(grid, axis=0, dtype=np.int32, out=grid)
        np.cumsum(grid, axis=1, dtype=np.int32, out=grid)
    cut = cut[:lanes, :columns]
    light, target, dark = (bands[band][:lanes, :columns] for band in ("light", "target", "dark"))
    valid = (cut == 0) & (light >= 1) & (target >= 2)
    if not valid.any():
        raise Invalid(f"No {width} × {height} px review window fits inside the crop without cutting "
                      "a bean while holding at least one light and two target-band beans. "
                      "Try another window size.")
    placements = int(valid.sum())
    best_light = int(light[valid].max())
    valid &= light == best_light
    crowd = target + dark
    best_crowd = int(crowd[valid].min())
    chosen = int(np.flatnonzero((valid & (crowd == best_crowd)).ravel())[0])
    row, col = divmod(chosen, columns)
    window_left, window_top = left + col, top + row
    return {
        "box": [window_left, window_top, window_left + width, window_top + height],
        "size": [width, height],
        "counts": {"light": best_light, "target": int(target[row, col]), "dark": int(dark[row, col])},
        "placements": placements,
    }


def recommend(rgb, settings, size):
    crop, labels, visible = silhouettes(rgb, settings)
    return recommend_window(bean_rows(crop, labels, visible, settings), settings, size)


def locate(rgb, settings, point):
    x, y = point
    left, top, right, bottom = settings["box"]
    local_id = None
    if left <= x < right and top <= y < bottom:
        _, labels, visible = silhouettes(rgb, settings)
        label = labels[y - top, x - left]
        for candidate, stats, _ in visible:
            if candidate == label:
                sx, sy, _, _, _ = map(int, stats)
                seed = int(np.flatnonzero(labels[sy] == label)[0])
                local_id = f"{left + seed}:{top + sy}"
                break
    color = rgb[y, x]
    return {"point": point, "rgb": color.tolist(), "lightness": round(float(luma(color)), 2),
            "bean": local_id}
