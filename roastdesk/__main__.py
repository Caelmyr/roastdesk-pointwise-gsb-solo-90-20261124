"""Serve the RoastDesk proof desk and photo preparation workspace."""

import os
from pathlib import Path

from waitress import serve

from image_lab import create_app

from .web import install


def application(data=None):
    storage = Path(data or os.environ.get("ROASTDESK_DATA", "runtime-data"))
    app = create_app(storage / "preparation")
    install(app, storage / "roast-photos")
    return app


if __name__ == "__main__":
    serve(application(), host=os.environ.get("HOST", "127.0.0.1"),
          port=int(os.environ.get("PORT", "8000")), threads=4)
