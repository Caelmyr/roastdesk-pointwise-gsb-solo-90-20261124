"""Validate the original-pixel crop, foreground and sampling settings."""

from image_lab.validation import Invalid

MAX_UPLOAD = 14 * 1024 * 1024
MAX_PIXELS = 4_000_000
MAX_COMPONENTS = 320
MAX_RUNS = 12000


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
            "target_low": 60, "target_high": 112, "exclude": [],
            "minimum_retained": .6, "sampling": {}}


def point(value, width, height):
    if not isinstance(value, list) or len(value) != 2:
        raise Invalid("Choose a point on the photo.")
    return [integer(value[0], "X", 0, width - 1), integer(value[1], "Y", 0, height - 1)]


def ratio(value, label="Minimum retained share"):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 1:
        raise Invalid(f"{label} must be more than 0 and at most 100 percent.")
    return float(value)


def bean_key(value, width, height):
    if not isinstance(value, str):
        raise Invalid("Choose a measured bean.")
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise Invalid("Choose a measured bean.")
    x = integer(int(parts[0]), "Bean X", 0, width - 1)
    y = integer(int(parts[1]), "Bean Y", 0, height - 1)
    return f"{x}:{y}"


def runs(value, width, height):
    if not isinstance(value, list) or len(value) > MAX_RUNS:
        raise Invalid("The retained-pixel outline is invalid.")
    rows = []
    for run in value:
        if not isinstance(run, list) or len(run) != 3:
            raise Invalid("The retained-pixel outline is invalid.")
        row = integer(run[0], "Outline Y", 0, height - 1)
        start = integer(run[1], "Outline X", 0, width)
        end = integer(run[2], "Outline X", start + 1, width)
        rows.append([row, start, end])
    return rows


def sample_plan(value, width, height):
    if not isinstance(value, dict) or value.get("version") != 1:
        raise Invalid("The sampling plan version is not supported.")
    return {"version": 1, "avoid": runs(value.get("avoid"), width, height)}


def sampling_map(value, width, height):
    if not isinstance(value, dict) or len(value) > MAX_COMPONENTS:
        raise Invalid("The per-bean sampling plans are invalid.")
    return {bean_key(key, width, height): sample_plan(plan, width, height)
            for key, plan in value.items()}


def stored(record, saved):
    """Fill defaults for settings written by an earlier version of the desk."""
    return {**defaults(record["width"], record["height"]), **saved}


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
    threshold = integer(result["threshold"], "Tray separator", 1, 254)
    minimum_area = integer(result["minimum_area"], "Minimum bean area", 1, MAX_PIXELS)
    # Bean identities come from the crop and silhouette; a change there makes any
    # retained-pixel plan refer to a different shape, so those plans are dropped.
    reshaped = [left, top, right, bottom] != original["box"]
    reshaped = reshaped or threshold != original["threshold"]
    reshaped = reshaped or minimum_area != original["minimum_area"]
    plans = {} if reshaped else sampling_map(result.get("sampling", {}), width, height)
    return {
        "box": [left, top, right, bottom], "threshold": threshold,
        "minimum_area": minimum_area, "target_low": low, "target_high": high,
        "exclude": sorted(set(exclusions)),
        "minimum_retained": ratio(result.get("minimum_retained", .6)),
        "sampling": plans,
    }
