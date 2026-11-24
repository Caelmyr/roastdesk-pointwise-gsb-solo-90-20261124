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
