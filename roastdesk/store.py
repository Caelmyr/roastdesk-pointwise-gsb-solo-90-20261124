"""Keep source pixels immutable and archive inspection results by revision."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from werkzeug.exceptions import Conflict, NotFound

from .frame import encode


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write(path, payload):
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_record(path, data):
    write(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode())


def read_record(path):
    if not path.is_file():
        raise NotFound("This roast sample or saved inspection could not be found.")
    return json.loads(path.read_text())


def identifier(value):
    if not isinstance(value, str) or len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
        raise NotFound("This roast sample or saved inspection could not be found.")
    return value


class Library:
    def __init__(self, root):
        self.samples = Path(root) / "samples"
        self.images = Path(root) / "images"
        self.reports = Path(root) / "reports"
        for directory in (self.samples, self.images, self.reports):
            directory.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def sample_path(self, sample_id):
        return self.samples / f"{identifier(sample_id)}.json"

    def sample(self, sample_id):
        return read_record(self.sample_path(sample_id))

    def source(self, record):
        return self.images / f"{record['source']['sha256']}.png"

    def list(self):
        rows = (read_record(path) for path in self.samples.glob("*.json"))
        return sorted(rows, key=lambda row: (row["created"], row["id"]), reverse=True)

    def create(self, title, image, filename, settings, synthetic=False, prepared=None):
        encoded = encode(image)
        fingerprint = sha256(encoded).hexdigest()
        record = {
            "id": uuid4().hex, "title": title, "created": stamp(), "synthetic": synthetic,
            "width": image.width, "height": image.height, "revision": 1, "settings": settings,
            "source": {"name": filename, "sha256": fingerprint}, "reports": [],
        }
        if prepared:
            record["source"]["prepared"] = prepared
        with self.lock:
            pixels = self.source(record)
            if not pixels.exists():
                write(pixels, encoded)
            write_record(self.sample_path(record["id"]), record)
        return record

    @staticmethod
    def require_revision(record, revision):
        if type(revision) is not int or revision != record["revision"]:
            raise Conflict("The tray changed. Reopen it before saving.")

    def revise(self, sample_id, revision, settings):
        with self.lock:
            record = self.sample(sample_id)
            self.require_revision(record, revision)
            record.update(revision=revision + 1, settings=settings)
            write_record(self.sample_path(sample_id), record)
            return record

    def retain(self, sample_id, revision, result):
        with self.lock:
            record = self.sample(sample_id)
            self.require_revision(record, revision)
            report = {
                **result, "id": uuid4().hex, "sample_id": sample_id, "created": stamp(),
                "source_revision": revision, "title": record["title"], "source": record["source"],
                "width": record["width"], "height": record["height"], "synthetic": record["synthetic"],
            }
            write_record(self.reports / f"{report['id']}.json", report)
            record["reports"].insert(0, {"id": report["id"], "created": report["created"],
                                        "count": report["summary"]["count"]})
            record["revision"] += 1
            write_record(self.sample_path(sample_id), record)
            return record, report

    def report(self, sample_id, report_id):
        record = self.sample(sample_id)
        report_id = identifier(report_id)
        if not any(item["id"] == report_id for item in record["reports"]):
            raise NotFound("This saved inspection could not be found.")
        return read_record(self.reports / f"{report_id}.json")
