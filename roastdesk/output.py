"""Export archived bean data and mark its exact source framing."""

import csv
from io import StringIO

from PIL import Image, ImageDraw

from .frame import encode

COLORS = {"dark": "#859DFF", "target": "#8DE4AE", "light": "#FFB358"}
EXCLUDED = "#FF8281"
SAMPLING_RETAINED = "#3ED6C0"
SAMPLING_AVOIDED = "#F2C14E"


def table(report):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["bean", "seed_x", "seed_y", "area_px", "sampled_area_px", "red", "green",
                     "blue", "mean_lightness", "lightness_stddev", "band", "excluded",
                     "touches_crop", "sampling"])
    for row in report["rows"]:
        writer.writerow([row["id"], *row["seed"], row["area"], row.get("sampled_area", row["area"]),
                         *row["rgb"], row["lightness"], row["spread"], row["band"], row["excluded"],
                         row["touches_crop"], row.get("sampling", False)])
    return buffer.getvalue()


def overlay(source, report, proposed=None):
    with Image.open(source) as image:
        photo = image.convert("RGB")
    draw = ImageDraw.Draw(photo)
    box = report["settings"]["box"] if "settings" in report else report["box"]
    left, top, right, bottom = box
    draw.rectangle((left, top, right - 1, bottom - 1), outline="#FFFAE0", width=2)
    if proposed:
        for points in proposed["retained"]:
            draw.line([*[tuple(point) for point in points], tuple(points[0])],
                      fill=SAMPLING_RETAINED, width=2)
        for points in proposed["avoided"]:
            draw.line([*[tuple(point) for point in points], tuple(points[0])],
                      fill=SAMPLING_AVOIDED, width=2)
        return encode(photo)
    for row in report["rows"]:
        color = EXCLUDED if row["excluded"] else COLORS[row["band"]]
        contour = [tuple(point) for point in row["outline"]]
        if len(contour) > 1:
            draw.line([*contour, contour[0]], fill=color, width=2)
        else:
            draw.point(tuple(row["seed"]), fill=color)
        if row.get("sampling"):
            for points in row.get("retained", []):
                draw.line([*[tuple(point) for point in points], tuple(points[0])],
                          fill=SAMPLING_RETAINED, width=1)
            for points in row.get("avoided", []):
                draw.line([*[tuple(point) for point in points], tuple(points[0])],
                          fill=SAMPLING_AVOIDED, width=1)
        x, y = map(round, row["center"])
        if row.get("sampling"):
            draw.text((x, y + 14), f"{row.get('sampled_area', row['area'])}/{row['area']} px",
                      fill=color, stroke_width=1, stroke_fill="#1D1815")
        draw.text((x, y), row["id"], fill=color, stroke_width=1, stroke_fill="#1D1815")
    return encode(photo)
