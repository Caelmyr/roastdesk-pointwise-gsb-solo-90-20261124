"""Recommend clean color-sampling pixels for one bean under specular highlights."""

import cv2
import numpy as np

from .frame import luma

VERSION = 1
DEFAULT_RATIO = .6

# Specular patches are neutral (white or grey) and brighter than the bean surface.
# Keep the limits conservative: a clearly light-brown face is chromatic and stays,
# while a low-saturation glare and the uncertain rim around it are removed.
SATURATION_SHARE = .45
MIN_SATURATION_LIMIT = .05
MAX_SATURATION_LIMIT = .18


def _band(lightness, settings):
    if lightness < settings["target_low"]:
        return "dark"
    if lightness > settings["target_high"]:
        return "light"
    return "target"


def _reading(pixels, settings):
    rgb_mean = np.round(pixels.mean(axis=0), 1)
    brightness = luma(pixels)
    tone = round(float(brightness.mean()), 2)
    return {
        "rgb": rgb_mean.tolist(), "lightness": tone,
        "spread": round(float(brightness.std()), 2), "band": _band(tone, settings),
    }


def runs(mask, offset=(0, 0)):
    """Encode a boolean tile mask as source-coordinate runs ``[y, x0, x1)``."""
    left, top = offset
    rows = []
    for row in range(mask.shape[0]):
        columns = np.flatnonzero(mask[row])
        if not len(columns):
            continue
        breaks = np.flatnonzero(np.diff(columns) > 1)
        starts = np.r_[columns[0], columns[breaks + 1]]
        ends = np.r_[columns[breaks] + 1, columns[-1] + 1]
        rows.extend([int(top + row), int(left + start), int(left + end)]
                    for start, end in zip(starts, ends))
    return rows


def runs_mask(shape, offset, encoded):
    """Rebuild a tile mask from source-coordinate runs."""
    left, top = offset
    mask = np.zeros(shape, dtype=bool)
    for y, start, end in encoded:
        row = y - top
        if 0 <= row < shape[0]:
            mask[row, max(0, start - left):max(0, end - left)] = True
    return mask


def polygons(mask, offset=(0, 0)):
    """Outline a tile mask as source-coordinate polygons for drawing."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    shapes = []
    for contour in contours:
        if cv2.contourArea(contour) >= 1:
            points = cv2.approxPolyDP(contour, .8, True)[:, 0]
            if len(points) >= 3:
                shapes.append((points + np.asarray(offset, dtype=np.int32)).tolist())
    return shapes


def enclosed_holes(mask):
    """Empty regions fully enclosed by the silhouette, which are still bean face."""
    flooded = np.pad((~mask).astype(np.uint8), 1, constant_values=1)
    cv2.floodFill(flooded, None, (0, 0), 2)
    return (~mask) & (flooded[1:-1, 1:-1] != 2)


def _highlight_mask(pixels):
    brightest = pixels.max(axis=1)
    chroma = brightest - pixels.min(axis=1)
    saturation = chroma / np.maximum(brightest, 1.)
    lightness = luma(pixels)
    deviation = float(lightness.std())
    median_lightness = float(np.median(lightness))
    limit = float(np.clip(SATURATION_SHARE * float(np.median(saturation)),
                          MIN_SATURATION_LIMIT, MAX_SATURATION_LIMIT))
    floor = max(median_lightness - .5 * deviation, .9 * median_lightness, 40.)
    return (saturation <= limit) & (lightness >= floor)


def recommend(photo, mask, bean, settings, offset=(0, 0), plan=None):
    """Leave out glare and its uncertain rim; keep the rest of the bean face.

    ``photo`` is the bean's bounding tile and ``mask`` its silhouette. ``offset`` is
    the tile's source position so the returned runs line up with the photograph.
    Empty regions enclosed by the silhouette are bean face too: a very bright glare
    can reach the tray's brightness and drop the connected shape. ``plan`` replays a
    previously adopted choice so an archive always marks the same pixels.
    """
    photo = np.asarray(photo)
    mask = np.asarray(mask, dtype=bool)
    face = mask | enclosed_holes(mask)
    area = int(mask.sum())
    face_area = int(face.sum())
    if not area:
        return None
    pixels = photo[face].astype(np.float32)
    whole = _reading(pixels, settings)

    if plan is not None:
        avoided = runs_mask(face.shape, offset, plan["avoid"]) & face
    else:
        glare = np.zeros(face.shape, dtype=bool)
        glare[face] = _highlight_mask(pixels)
        glare &= face
        if glare.any():
            size = max(face.shape)
            radius = int(np.clip(round(size * .045), 1, 5))
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
            avoided = cv2.dilate(glare.astype(np.uint8), kernel).astype(bool) & face
        else:
            avoided = glare
    retained = face & ~avoided

    retained_area = int(retained.sum())
    ratio = retained_area / face_area
    minimum = float(settings.get("minimum_retained", DEFAULT_RATIO))
    ready = retained_area > 0 and ratio + 1e-9 >= minimum
    reading = (_reading(photo[retained].astype(np.float32), settings) if retained_area
               else {"rgb": None, "lightness": None, "spread": None, "band": None})
    return {
        "bean": bean, "version": VERSION, "area": face_area,
        "retained_area": retained_area, "retained_ratio": round(ratio, 4),
        "minimum_ratio": round(float(minimum), 4),
        "status": "ready" if ready else "retake",
        "retained": runs(retained, offset), "avoided": runs(avoided, offset),
        "retained_outline": polygons(retained, offset),
        "avoided_outline": polygons(avoided, offset),
        "whole": whole, **reading,
    }


def plan(recommendation):
    """The persisted part of a recommendation; exact avoided source pixels."""
    return {
        "version": recommendation["version"], "avoid": recommendation["avoided"],
        "retained_area": recommendation["retained_area"],
        "retained_ratio": recommendation["retained_ratio"],
        "minimum_ratio": recommendation["minimum_ratio"],
    }
