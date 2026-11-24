"""Decode immutable, displayed-orientation tray photographs."""

from io import BytesIO
import warnings

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from image_lab.validation import Invalid

from .model import MAX_PIXELS, MAX_UPLOAD


def encode(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def decode(raw):
    if len(raw) > MAX_UPLOAD:
        raise Invalid("A single photo can be at most 14 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=("PNG", "JPEG")) as source:
                width, height = source.size
                if min(width, height) < 8 or max(width, height) > 4096 or width * height > MAX_PIXELS:
                    raise Invalid("Photos must be 8–4096 pixels per side and no more than 4 million pixels.")
                if getattr(source, "n_frames", 1) != 1:
                    raise Invalid("Use a single-frame PNG or JPEG.")
                prepared = ImageOps.exif_transpose(source)
                if "A" in prepared.getbands() or "transparency" in prepared.info:
                    if prepared.convert("RGBA").getchannel("A").getextrema()[0] != 255:
                        raise Invalid("Flatten any transparent pixels before importing.")
                image = prepared.convert("RGB")
    except Invalid:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Invalid("The photo exceeds the supported dimensions.") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise Invalid("Could not open that image as PNG or JPEG.") from None
    return image


def pixels(library, record):
    with Image.open(library.source(record)) as sample:
        return np.array(sample.convert("RGB"))


def luma(rgb):
    colors = rgb.astype(np.float32)
    return colors[..., 0] * 0.2126 + colors[..., 1] * 0.7152 + colors[..., 2] * 0.0722
