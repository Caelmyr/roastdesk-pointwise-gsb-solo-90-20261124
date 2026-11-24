"""Draw a deterministic synthetic tray of roasted beans for practice."""

import numpy as np
from PIL import Image

from .model import defaults

WIDTH, HEIGHT = 1050, 730


def sample():
    y, x = np.indices((HEIGHT, WIDTH), dtype=float)
    rng = np.random.default_rng(103)
    light = 1.0 - 0.035 * ((x - 480) / 540) ** 2 - 0.028 * ((y - 310) / 400) ** 2
    colors = light[..., None] * np.array([235., 225., 205.])
    definitions = [
        (133, 143, 43, 60, -.5, [100, 58, 37]), (323, 124, 66, 44, .2, [166, 99, 64]),
        (522, 152, 53, 70, .4, [129, 76, 53]), (726, 132, 50, 37, -.6, [114, 70, 43]),
        (910, 149, 53, 59, .25, [183, 115, 77]), (158, 307, 72, 44, -.55, [147, 87, 52]),
        (367, 350, 48, 62, .35, [98, 59, 41]), (555, 323, 56, 44, .8, [126, 72, 45]),
        (640, 343, 55, 42, .5, [159, 94, 58]), (862, 346, 48, 66, -.4, [154, 90, 54]),
        (148, 559, 64, 53, .7, [118, 76, 52]), (328, 554, 45, 61, -.7, [162, 101, 57]),
        (516, 557, 59, 52, -.18, [130, 87, 60]), (703, 545, 55, 64, .75, [94, 53, 41]),
        (900, 550, 61, 49, -.3, [153, 89, 61]), (937, 654, 18, 9, -.4, [92, 54, 32]),
    ]
    for cx, cy, rx, ry, angle, base in definitions:
        u = (x - cx) * np.cos(angle) + (y - cy) * np.sin(angle)
        v = (y - cy) * np.cos(angle) - (x - cx) * np.sin(angle)
        z = (u / rx) ** 2 + (v / ry) ** 2
        shade = (z > 1) & (z < 1.31) & (x > cx + 5) & (y > cy - 10)
        colors[shade] -= 11 * np.clip(1.31 - z[shade], 0, .3)[:, None]
        face = z <= 1 + .04 * np.sin(6 * np.arctan2(v, u))
        crease = np.exp(-((u - 6 * np.sin(v / 17)) / 3.5) ** 2) * (np.abs(v) < ry * .87)
        texture = 1.02 + .16 * (1 - z[face]) - .42 * crease[face] + .048 * np.cos(v[face] / 4 + u[face] / 7)
        colors[face] = np.array(base) * texture[:, None]
    colors += rng.normal(0, 1.65, (HEIGHT, WIDTH, 1))
    return Image.fromarray(np.clip(colors, 0, 255).astype(np.uint8))


def glare():
    """Add one specular patch so the highlight-sampling workflow can be practiced."""
    image = np.asarray(sample()).astype(np.float32)
    y, x = np.indices((HEIGHT, WIDTH), dtype=float)
    distance = np.hypot(x - 522, y - 152)
    image[distance < 11] = [148, 147, 143]
    rim = (distance >= 11) & (distance < 15)
    image[rim] = image[rim] * .35 + np.array([155, 154, 150]) * .65
    return Image.fromarray(np.clip(image, 0, 255).astype(np.uint8))


def create(library):
    return library.create("House roast • synthetic tray", glare(), "synthetic-tray.png",
                          defaults(WIDTH, HEIGHT), synthetic=True)
