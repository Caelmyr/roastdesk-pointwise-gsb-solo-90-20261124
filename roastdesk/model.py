"""Validate the original-pixel crop, foreground and sampling settings."""

from image_lab.validation import Invalid

MAX_UPLOAD = 14 * 1024 * 1024
MAX_PIXELS = 4_000_000
MAX_COMPONENTS = 320
MAX_SEAM_POINTS = 400


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
            "target_low": 60, "target_high": 112, "exclude": [], "splits": []}


def point(value, width, height):
    if not isinstance(value, list) or len(value) != 2:
        raise Invalid("Choose a point on the photo.")
    return [integer(value[0], "X", 0, width - 1), integer(value[1], "Y", 0, height - 1)]


def bean_key(value):
    """A shape key: ``x:y`` for a joined silhouette, ``x:y#n`` for one of its halves."""
    if not isinstance(value, str) or len(value) > 24:
        raise Invalid("The bean position is invalid.")
    position, _, half = value.partition("#")
    parts = position.split(":")
    if len(parts) != 2:
        raise Invalid("The bean position is invalid.")
    for part in parts:
        if not part.isdigit() or int(part) > MAX_PIXELS:
            raise Invalid("The bean position is invalid.")
    if half and (not half.isdigit() or int(half) < 1):
        raise Invalid("The bean position is invalid.")
    return value


def exclusion_key(value):
    """Exclusions may name a joined shape or one of the halves it was split into."""
    return bean_key(value)



def splits(value, width, height):
    if not isinstance(value, list) or len(value) > MAX_COMPONENTS:
        raise Invalid("The list of adopted bean seams is invalid.")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise Invalid("An adopted bean seam is invalid.")
        bean = bean_key(item.get("bean"))
        points = item.get("points")
        if not isinstance(points, list) or not 2 <= len(points) <= MAX_SEAM_POINTS:
            raise Invalid("An adopted bean seam needs at least two points.")
        cleaned = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise Invalid("An adopted bean seam needs pixel points.")
            x = number(point[0], "Seam X", 0, width)
            y = number(point[1], "Seam Y", 0, height)
            cleaned.append([round(x, 2), round(y, 2)])
        if bean in seen:
            raise Invalid("The same joined bean has more than one adopted seam.")
        seen.add(bean)
        result.append({"bean": bean, "points": cleaned})
    return result


def number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Invalid(f"{label} must be a number from {low} to {high}.")
    if not low <= value <= high:
        raise Invalid(f"{label} must be a number from {low} to {high}.")
    return float(value)


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
    if not isinstance(exclusions, list) or len(exclusions) > MAX_COMPONENTS:
        raise Invalid("The list of excluded bean positions is invalid.")
    exclusions = {exclusion_key(key) for key in exclusions}
    return {
        "box": [left, top, right, bottom],
        "threshold": integer(result["threshold"], "Tray separator", 1, 254),
        "minimum_area": integer(result["minimum_area"], "Minimum bean area", 1, MAX_PIXELS),
        "target_low": low, "target_high": high, "exclude": sorted(exclusions),
        "splits": splits(result.get("splits", []), width, height),
    }
