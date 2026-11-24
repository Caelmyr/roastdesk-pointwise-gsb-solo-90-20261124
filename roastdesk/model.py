"""Validate the original-pixel crop, foreground and sampling settings."""

from image_lab.validation import Invalid

MAX_UPLOAD = 14 * 1024 * 1024
MAX_PIXELS = 4_000_000
MAX_COMPONENTS = 320


def document(value):
    if not isinstance(value, dict):
        raise Invalid("Expected a settings object.")
    return value


def integer(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Invalid(f"{label} must be a whole number from {low} to {high}.")
    return value


def text(value, default="Tray sample"):
    return str(value or "").strip()[:120] or default


def defaults(width, height):
    return {"box": [0, 0, width, height], "threshold": 158, "minimum_area": 80,
            "target_low": 60, "target_high": 112, "exclude": []}


def point(value, width, height):
    if not isinstance(value, list) or len(value) != 2:
        raise Invalid("Choose a point on the photo.")
    return [integer(value[0], "X", 0, width - 1), integer(value[1], "Y", 0, height - 1)]


def settings(record, overrides):
    original = record["settings"]
    result = {**original, **document(overrides)}
    width, height = record["width"], record["height"]
    box = result["box"]
    if not isinstance(box, list) or len(box) != 4:
        raise Invalid("Choose a rectangular crop.")
    left = integer(box[0], "Left", 0, width - 1)
    top = integer(box[1], "Top", 0, height - 1)
    right = integer(box[2], "Right", left + 1, width)
    bottom = integer(box[3], "Bottom", top + 1, height)
    low = integer(result["target_low"], "Dark boundary", 0, 254)
    high = integer(result["target_high"], "Light boundary", low + 1, 255)
    exclusions = result["exclude"]
    if (not isinstance(exclusions, list) or len(exclusions) > MAX_COMPONENTS
            or any(not isinstance(key, str) or len(key) > 24 for key in exclusions)):
        raise Invalid("The list of excluded bean positions is invalid.")
    return {
        "box": [left, top, right, bottom],
        "threshold": integer(result["threshold"], "Tray separator", 1, 254),
        "minimum_area": integer(result["minimum_area"], "Minimum bean area", 1, MAX_PIXELS),
        "target_low": low, "target_high": high, "exclude": sorted(set(exclusions)),
    }
