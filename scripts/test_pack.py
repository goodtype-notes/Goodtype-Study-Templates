"""Regression checks for strict validation and deterministic packaging."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from zipfile import ZipFile

from package import package
from validate import shape_object, validate


class ValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        manifest, files = validate(report=False)
        self.manifest = copy.deepcopy(manifest)
        for name, path in files.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)

    def save(self, path, data):
        (self.root / path).write_text(json.dumps(data), encoding="utf-8")

    def test_manifest_rejects_privileges_and_locale_mismatch(self):
        mutations = [
            {"commands": [{"id": "run"}]},
            {"entrypoint": "program.exe"},
            {"strings": {"en": {"name": "Name", "extra": "Extra"}, "de": {"name": "Name"}}},
            {"contents": {"shapes": ["content/shapes/../example.json"]}},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.save("goodtype-addon.json", self.manifest | mutation)
                with self.assertRaises(ValueError):
                    validate(self.root, report=False)

    def test_duplicate_keys(self):
        with (self.root / "goodtype-addon.json").open(encoding="utf-8") as stream:
            source = stream.read()
        (self.root / "goodtype-addon.json").write_text('{"id": "other",' + source[1:], encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
            validate(self.root, report=False)

    def test_geometry_or_spacing_bounds(self):
        contents = self.manifest["contents"]
        if "shapes" in contents:
            path = contents["shapes"][0]
            data = json.loads((self.root / path).read_text(encoding="utf-8"))
            data["items"][0]["objects"][0]["geometry"]["end"]["x"] = 1000
        else:
            path = contents["templates"][0]
            data = json.loads((self.root / path).read_text(encoding="utf-8"))
            data["templates"][0]["template"]["elements"][0]["spacingPt"] = 72 / 25.4
        self.save(path, data)
        with self.assertRaisesRegex(ValueError, "Invalid number"):
            validate(self.root, report=False)

    def test_relative_handles_determine_curve_bounds(self):
        g = dict(kind="spline", closed=False, nodes=[
            {"point": {"x": 10, "y": 4}, "handleOut": {"x": 4, "y": -8}},
            {"point": {"x": 22, "y": 4}, "handleIn": {"x": -4, "y": -8}},
        ])
        obj = dict(type="shape", x=0, y=2, geometry=g, style={})
        # The controls extend above the item, while the curve is tangent to its edge.
        shape_object(obj, 24, 12)
        obj["y"] = 1
        with self.assertRaisesRegex(ValueError, "Invalid number"):
            shape_object(obj, 24, 12)


    def test_package_is_reproducible_and_extracted_content_validates(self):
        archive = package()
        expected = hashlib.sha256(archive.read_bytes()).hexdigest()
        package()
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), expected)
        self.assertEqual((archive.parent / "SHA256SUMS").read_text().split()[0], expected)
        with tempfile.TemporaryDirectory() as destination:
            with ZipFile(archive) as zipped:
                self.assertIsNone(zipped.testzip())
                self.assertTrue(all(name.startswith(archive.stem + "/") for name in zipped.namelist()))
                zipped.extractall(destination)
            validate(Path(destination) / archive.stem, report=False)
