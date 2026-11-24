"""Regression checks for joined-bean splitting on RoastDesk (stdlib unittest)."""
import io
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def tray():
    width, height = 760, 520
    yy, xx = np.mgrid[0:height, 0:width].astype(float)
    image = np.full((height, width, 3), 232.0) * (
        1 - 0.04 * ((xx - width / 2) / width) ** 2
        - 0.03 * ((yy - height / 2) / height) ** 2)[..., None]
    rng = np.random.default_rng(11)

    def bean(cx, cy, rx, ry, angle, base):
        u = (xx - cx) * math.cos(angle) + (yy - cy) * math.sin(angle)
        v = (yy - cy) * math.cos(angle) - (xx - cx) * math.sin(angle)
        z = (u / rx) ** 2 + (v / ry) ** 2
        selected = z <= 1
        image[selected] = np.array(base) * (1.02 + 0.15 * (1 - np.clip(z, 0, 1)))[selected][:, None]
        return selected

    bean(150, 120, 58, 40, 0.2, (120, 74, 50))
    bean(320, 150, 60, 42, -0.4, (150, 92, 58))
    bean(500, 120, 55, 38, 0.5, (95, 58, 40))
    bean(150, 300, 62, 44, 0.1, (160, 100, 62))
    first = bean(400, 370, 60, 40, 0.1, (130, 80, 52))
    second = bean(500, 378, 58, 40, -0.2, (105, 66, 44))
    crease = (xx - 450) * 0.98 - (yy - 374) * 0.15
    image[(first | second) & (np.abs(crease) < 2.4)] = [62, 40, 26]
    soft = (first | second) & (np.abs(crease) >= 2.4) & (np.abs(crease) < 5)
    image[soft] = image[soft] * 0.55 + np.array([62, 40, 26]) * 0.45
    bean(650, 330, 55, 40, -0.2, (140, 88, 55))
    bean(300, 460, 54, 38, 0.3, (115, 72, 47))
    bean(650, 450, 50, 36, 0.1, (170, 110, 70))
    image += rng.normal(0, 1.6, image.shape)
    raw = io.BytesIO()
    Image.fromarray(np.clip(image, 0, 255).astype(np.uint8)).save(raw, format="PNG")
    return raw.getvalue()


class RoastDeskSplitTests(unittest.TestCase):
    def setUp(self):
        from roastdesk.__main__ import application
        self.directory = tempfile.TemporaryDirectory()
        self.client = application(self.directory.name).test_client()
        response = self.client.post(
            "/roast/samples",
            data={"photo": (io.BytesIO(tray()), "tray.png"), "title": "Joined"},
            content_type="multipart/form-data")
        self.assertEqual(response.status_code, 201)
        self.sample = response.get_json()["id"]

    def tearDown(self):
        self.directory.cleanup()

    def inspect(self, settings=None):
        body = {} if settings is None else {"settings": settings}
        return self.client.post(f"/roast/samples/{self.sample}/inspect",
                                json=body).get_json()

    def hint(self, bean, settings):
        return self.client.post(f"/roast/samples/{self.sample}/seam",
                                json={"bean": bean, "settings": settings}).get_json()

    @staticmethod
    def joined(result):
        return max(result["rows"], key=lambda row: row["area"])

    def test_suggestion_tiles_the_joined_shape(self):
        result = self.inspect()
        joined = self.joined(result)
        hint = self.hint(joined["id"], result["settings"])
        self.assertTrue(hint["possible"])
        self.assertTrue(hint["points"])
        self.assertEqual(hint["bean"], joined["id"])
        self.assertEqual(sum(piece["area"] for piece in hint["pieces"]), joined["area"])
        self.assertTrue(all(piece["area"] >= result["settings"]["minimum_area"]
                            for piece in hint["pieces"]))

    def test_adopting_replaces_the_joined_record(self):
        result = self.inspect()
        before = {row["id"] for row in result["rows"]}
        joined = self.joined(result)
        hint = self.hint(joined["id"], result["settings"])
        settings = {**result["settings"],
                    "splits": [{"bean": joined["id"], "points": hint["points"]}]}
        after = self.inspect(settings)
        rows = {row["id"]: row for row in after["rows"]}
        self.assertNotIn(joined["id"], rows)
        children = [row for row in after["rows"] if row["id"] not in before]
        self.assertEqual(len(children), 2)
        self.assertEqual(sum(row["area"] for row in children), joined["area"])
        self.assertEqual(sorted(row["area"] for row in children),
                         sorted(piece["area"] for piece in hint["pieces"]))
        self.assertTrue(all(row["rgb"] != joined["rgb"] for row in children))

    def test_preexisting_exclusions_survive_the_split(self):
        result = self.inspect()
        joined = self.joined(result)
        others = [row for row in result["rows"] if row["id"] != joined["id"]]
        excluded = sorted((others[0]["id"], others[1]["id"]))
        settings = {**result["settings"], "exclude": excluded}
        result = self.inspect(settings)
        before_count, before_area = result["summary"]["count"], result["summary"]["area"]
        joined = self.joined(result)
        hint = self.hint(joined["id"], settings)
        settings = {**settings, "splits": [{"bean": joined["id"], "points": hint["points"]}]}
        after = self.inspect(settings)
        self.assertEqual(sorted(row["id"] for row in after["rows"] if row["excluded"]), excluded)
        self.assertEqual(after["summary"]["count"], before_count + 1)
        self.assertEqual(after["summary"]["area"], before_area)

    def test_saved_inspection_keeps_split_measurements(self):
        result = self.inspect()
        joined = self.joined(result)
        hint = self.hint(joined["id"], result["settings"])
        settings = {**result["settings"],
                    "splits": [{"bean": joined["id"], "points": hint["points"]}]}
        record = self.client.get(f"/roast/samples/{self.sample}").get_json()
        revised = self.client.put(f"/roast/samples/{self.sample}/settings",
                                  json={"settings": settings, "revision": record["revision"]}).get_json()
        saved = self.client.post(f"/roast/samples/{self.sample}/reports",
                                 json={"settings": settings, "revision": revised["revision"]})
        self.assertEqual(saved.status_code, 201)
        archive = saved.get_json()["report"]
        self.assertNotIn(joined["id"], {row["id"] for row in archive["rows"]})
        self.assertEqual(len(archive["rows"]), len(result["rows"]) + 1)
        self.assertEqual(archive["settings"]["splits"], settings["splits"])
        table = self.client.get(
            f"/roast/samples/{self.sample}/reports/{archive['id']}/beans.csv").data.decode()
        self.assertEqual(len(table.strip().splitlines()), len(archive["rows"]) + 1)
        self.assertEqual(self.client.get(
            f"/roast/samples/{self.sample}/reports/{archive['id']}/overlay.png").status_code, 200)

    def test_single_bean_is_left_alone(self):
        result = self.inspect()
        joined = self.joined(result)
        lone = min((row for row in result["rows"] if row["id"] != joined["id"]),
                   key=lambda row: abs(row["area"] - 6500))
        hint = self.hint(lone["id"], result["settings"])
        self.assertFalse(hint["possible"])
        self.assertTrue(hint["reason"])

    def test_minimum_area_blocks_impossible_split(self):
        result = self.inspect()
        joined = self.joined(result)
        settings = {**result["settings"], "minimum_area": joined["area"]}
        hint = self.hint(joined["id"], settings)
        self.assertFalse(hint["possible"])
        self.assertTrue(hint["reason"])

    def test_probe_names_a_half_after_the_split(self):
        result = self.inspect()
        joined = self.joined(result)
        hint = self.hint(joined["id"], result["settings"])
        settings = {**result["settings"],
                    "splits": [{"bean": joined["id"], "points": hint["points"]}]}
        after = self.inspect(settings)
        for row in after["rows"]:
            found = self.client.post(f"/roast/samples/{self.sample}/point",
                                     json={"point": row["seed"], "settings": settings}).get_json()
            self.assertEqual(found["bean"], row["id"])

    def test_archive_exposes_split_to_the_live_lookup(self):
        result = self.inspect()
        joined = self.joined(result)
        hint = self.hint(joined["id"], result["settings"])
        settings = {**result["settings"],
                    "splits": [{"bean": joined["id"], "points": hint["points"]}]}
        record = self.client.get(f"/roast/samples/{self.sample}").get_json()
        revised = self.client.put(f"/roast/samples/{self.sample}/settings",
                                  json={"settings": settings, "revision": record["revision"]}).get_json()
        archive = self.client.post(f"/roast/samples/{self.sample}/reports",
                                   json={"settings": settings,
                                         "revision": revised["revision"]}).get_json()["report"]
        child = next(row for row in archive["rows"] if row["id"] not in
                     {r["id"] for r in result["rows"]})
        found = self.client.post(f"/roast/samples/{self.sample}/point",
                                 json={"point": child["seed"], "report": archive["id"]}).get_json()
        self.assertEqual(found["bean"], child["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
