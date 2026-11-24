"""Export archived bean data and mark its exact source framing."""

import csv
from io import StringIO

from PIL import Image, ImageDraw

from .frame import encode

COLORS = {"dark": "#859DFF", "target": "#8DE4AE", "light": "#FFB358"}
EXCLUDED = "#FF8281"


def table(report):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["bean", "seed_x", "seed_y", "area_px", "red", "green", "blue", "mean_lightness",
                     "lightness_stddev", "band", "excluded", "touches_crop"])
    for row in report["rows"]:
        writer.writerow([row["id"], *row["seed"], row["area"], *row["rgb"], row["lightness"],
                         row["spread"], row["band"], row["excluded"], row["touches_crop"]])
    return buffer.getvalue()


def overlay(source, report):
    with Image.open(source) as image:
        photo = image.convert("RGB")
    draw = ImageDraw.Draw(photo)
    left, top, right, bottom = report["settings"]["box"]
    draw.rectangle((left, top, right - 1, bottom - 1), outline="#FFFAE0", width=2)
    for row in report["rows"]:
        color = EXCLUDED if row["excluded"] else COLORS[row["band"]]
        contour = [tuple(point) for point in row["outline"]]
        if len(contour) > 1:
            draw.line([*contour, contour[0]], fill=color, width=2)
        else:
            draw.point(tuple(row["seed"]), fill=color)
        x, y = map(round, row["center"])
        draw.text((x, y), row["id"], fill=color, stroke_width=1, stroke_fill="#1D1815")
    return encode(photo)
