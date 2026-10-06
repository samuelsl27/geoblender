# SPDX-License-Identifier: GPL-3.0-or-later
"""Catálogo de CRS de Geoblender (spec 002, T02; RF-002-03, RF-002-23; D-8, ADR-0019).

El catálogo es un extracto del EPSG Dataset (IOGP) generado una vez con PROJ
(``tools/gen_crs_catalog.py``) y guardado en ``thirdparty/epsg/``: Geoblender no depende
de la configuración de PROJ o GDAL del equipo (en el de IMGA, ``PROJ_LIB`` apuntaba al
``proj.db`` de PostGIS: Silvestre TOP-05).

La spec §11 dice «26 CRS» pero enumera 25 códigos (13 horizontales y 12 verticales): la
prueba exige exactamente los enumerados.
"""

import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support.package import import_geoblender
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

from gbtools import layout  # noqa: E402

crs = import_geoblender("core.georef.crs")
georef = import_geoblender("core.georef")
errors = import_geoblender("core.errors")

# Spec 002 §11 (D-1): horizontales 25828–25831, 4082, 4083, 32628–32631 y 23029–23031;
# verticales 5782 (Alicante), 9392–9394 (Baleares), 9395–9401 (Canarias) y 9402 (Ceuta).
SPEC_HORIZONTAL = (
    25828, 25829, 25830, 25831, 4082, 4083,
    32628, 32629, 32630, 32631, 23029, 23030, 23031,
)
SPEC_VERTICAL = (5782, 9392, 9393, 9394, 9395, 9396, 9397, 9398, 9399, 9400, 9401, 9402)
REJECTED = (4326, 9403, 99999)  # geográfico, geográfico (PN68) e inexistente
EPSG_FOLDER = ROOT / layout.THIRDPARTY_RELPATH / "epsg"


def _snapshot(catalog: object) -> list[object]:
    """Todo lo que expone el catálogo, comparable."""
    return [
        catalog.horizontals(),
        catalog.verticals(),
        catalog.source,
    ]


class CrsCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = crs.load_catalog()

    def test_defaults_have_name_and_wkt(self) -> None:
        """RF-002-23: EPSG:25830 y EPSG:5782 (los CRS propuestos) devuelven nombre,
        WKT2 con su ``ID["EPSG",n]`` y WKT1 con su ``AUTHORITY``."""
        horizontal = self.catalog.horizontal(25830)
        self.assertIsInstance(horizontal, georef.CrsRef)
        self.assertEqual(horizontal.epsg, 25830)
        self.assertEqual(horizontal.name, "ETRS89 / UTM zone 30N")
        self.assertTrue(horizontal.wkt2.startswith("PROJCRS["))
        self.assertTrue(horizontal.wkt2.endswith('ID["EPSG",25830]]'))
        self.assertTrue(horizontal.wkt1.startswith("PROJCS["))
        self.assertTrue(horizontal.wkt1.endswith('AUTHORITY["EPSG","25830"]]'))
        vertical = self.catalog.vertical(5782)
        self.assertIsInstance(vertical, georef.VerticalRef)
        self.assertEqual(
            (vertical.kind, vertical.epsg, vertical.name, vertical.note),
            ("epsg", 5782, "Alicante height", None),
        )
        self.assertTrue(vertical.wkt2.startswith("VERTCRS["))
        self.assertTrue(vertical.wkt2.endswith('ID["EPSG",5782]]'))
        self.assertEqual(crs.DEFAULT_HORIZONTAL_EPSG, 25830)
        self.assertEqual(crs.DEFAULT_VERTICAL_EPSG, 5782)

    def test_rejected_codes(self) -> None:
        """RF-002-03: 4326, 9403 y 99999 no están en el catálogo: se rechazan con el
        código EPSG y el motivo, como horizontal y como vertical."""
        for code in REJECTED:
            for lookup, field in (
                (self.catalog.horizontal, "CRS horizontal"),
                (self.catalog.vertical, "CRS vertical"),
            ):
                with self.subTest(code=code, field=field):
                    with self.assertRaises(errors.ValidationError) as caught:
                        lookup(code)
                    error = caught.exception
                    self.assertEqual(error.code, "core.crs_not_in_catalog")
                    self.assertEqual(error.field, field)
                    self.assertEqual(error.value, code)
                    self.assertIn(f"EPSG:{code}", str(error))
                    self.assertIn("no está en el catálogo", str(error))

    def test_wrong_kind_rejected(self) -> None:
        """RF-002-03: un CRS del catálogo del tipo equivocado se rechaza con el motivo
        (5782 no es horizontal; 25830 no es vertical); un código que no es entero,
        también."""
        with self.assertRaises(errors.ValidationError) as caught:
            self.catalog.horizontal(5782)
        self.assertEqual(caught.exception.code, "core.crs_not_horizontal")
        self.assertIn("vertical", str(caught.exception))
        with self.assertRaises(errors.ValidationError) as caught:
            self.catalog.vertical(25830)
        self.assertEqual(caught.exception.code, "core.crs_not_vertical")
        self.assertIn("horizontal", str(caught.exception))
        for bad in ("25830", 25830.0, True, None):
            with self.subTest(bad=bad):
                with self.assertRaises(errors.ValidationError) as caught:
                    self.catalog.horizontal(bad)
                self.assertEqual(caught.exception.code, "core.crs_code_invalid")

    def test_spec_entries(self) -> None:
        """RF-002-23: están exactamente los CRS de la spec §11, en su orden; cada WKT2
        termina con su ``ID["EPSG",n]`` y cada WKT1 con su ``AUTHORITY``; los
        horizontales son proyectados en metros y los verticales, en metros."""
        horizontals = self.catalog.horizontals()
        verticals = self.catalog.verticals()
        self.assertEqual(tuple(ref.epsg for ref in horizontals), SPEC_HORIZONTAL)
        self.assertEqual(tuple(ref.epsg for ref in verticals), SPEC_VERTICAL)
        data = json.loads(crs.CATALOG_PATH.read_text(encoding="utf-8"))
        entries = data["horizontal"] + data["vertical"]
        self.assertEqual(len(entries), len(SPEC_HORIZONTAL) + len(SPEC_VERTICAL))
        for entry in entries:
            code = entry["epsg"]
            with self.subTest(code=code):
                self.assertTrue(entry["wkt2"].endswith(f'ID["EPSG",{code}]]'))
                self.assertTrue(entry["wkt1"].endswith(f'AUTHORITY["EPSG","{code}"]]'))
                self.assertEqual(entry["unit"], "metre")
                self.assertTrue(entry["name"])
                self.assertTrue(entry["area"])
        for entry in data["horizontal"]:
            self.assertEqual(entry["type"], "projected")
            self.assertEqual(entry["axes"], ["E", "N"])
        for entry in data["vertical"]:
            self.assertEqual(entry["type"], "vertical")

    def test_projected_bounds(self) -> None:
        """RF-002-03: el ámbito proyectado de EPSG:25830 contiene (700 000; 4 400 000) y
        no (4 400 000; 700 000), la ventana con los ejes intercambiados."""
        ref = self.catalog.horizontal(25830)
        xmin, ymin, xmax, ymax = ref.bounds
        self.assertTrue(xmin < 700_000 < xmax and ymin < 4_400_000 < ymax)
        self.assertFalse(xmin < 4_400_000 < xmax)
        self.assertTrue(ref.contains(699_000.0, 4_399_000.0, 701_000.0, 4_401_000.0))
        self.assertFalse(ref.contains(4_399_000.0, 699_000.0, 4_401_000.0, 701_000.0))
        for horizontal in self.catalog.horizontals():
            with self.subTest(code=horizontal.epsg):
                left, bottom, right, top = horizontal.bounds
                self.assertLess(left, right)
                self.assertLess(bottom, top)

    def test_local_vertical(self) -> None:
        """RF-002-23: «referencia local» con descripción obligatoria; sin ella, error con
        el campo."""
        local = self.catalog.local_vertical("  Cota de obra: NP-0 del plano 3  ")
        self.assertEqual(
            (local.kind, local.epsg, local.wkt2, local.note),
            ("local", None, None, "Cota de obra: NP-0 del plano 3"),
        )
        self.assertTrue(local.name)
        for note in ("", "   ", None):
            with self.subTest(note=note):
                with self.assertRaises(errors.ValidationError) as caught:
                    self.catalog.local_vertical(note)
                self.assertEqual(caught.exception.code, "core.vcrs_note_required")

    def test_vertical_ref_invariants(self) -> None:
        """RF-002-23: un ``VerticalRef`` «epsg» lleva código y WKT y no nota; uno «local»,
        nota y ni código ni WKT; otro tipo se rechaza."""
        ref = georef.VerticalRef
        with self.assertRaises(ValueError):
            ref(kind="epsg", epsg=None, name="x", wkt2="VERTCRS[]", note=None)
        with self.assertRaises(ValueError):
            ref(kind="local", epsg=5782, name="x", wkt2=None, note="n")
        with self.assertRaises(ValueError):
            ref(kind="local", epsg=None, name="x", wkt2=None, note=" ")
        with self.assertRaises(ValueError):
            ref(kind="otro", epsg=None, name="x", wkt2=None, note=None)

    def test_independent_of_proj_environment(self) -> None:
        """RF-002-23: el resultado no cambia con ``PROJ_LIB``, ``PROJ_DATA`` y
        ``GDAL_DATA`` apuntando a carpetas falsas."""
        before = _snapshot(crs.read_catalog(crs.CATALOG_PATH))
        with tempfile.TemporaryDirectory(prefix="geoblender-proj-falso-") as fake:
            names = ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA")
            fake_env = {name: str(Path(fake) / name) for name in names}
            with mock.patch.dict(os.environ, fake_env):
                after = _snapshot(crs.read_catalog(crs.CATALOG_PATH))
        self.assertEqual(before, after)

    def test_json_cites_epsg_and_proj(self) -> None:
        """RF-002-23; ADR-0019: el JSON reconoce la propiedad de IOGP y lleva las
        versiones de EPSG y de PROJ con las que se generó."""
        source = self.catalog.source
        self.assertIn("IOGP", source["owner"])
        self.assertIn("IOGP", source["attribution"])
        self.assertIn("EPSG", source["dataset"])
        self.assertRegex(source["epsg_version"], r"^v\d+\.\d+$")
        self.assertRegex(source["epsg_date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(source["proj_version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(source["terms_of_use"], "https://epsg.org/terms-of-use.html")

    def test_folder_license_and_readme(self) -> None:
        """ADR-0019 (D-8): la carpeta tiene su ``LICENSE`` (los términos de EPSG, igual que
        ``LICENSES/LicenseRef-EPSG-terms-of-use.txt``) y un ``README.md`` que lista el
        catálogo con su sha256 y la atribución a IOGP."""
        license_text = (EPSG_FOLDER / "LICENSE").read_bytes()
        self.assertEqual(
            license_text,
            (ROOT / "LICENSES" / "LicenseRef-EPSG-terms-of-use.txt").read_bytes(),
        )
        readme = (EPSG_FOLDER / "README.md").read_text(encoding="utf-8")
        digest = hashlib.sha256(crs.CATALOG_PATH.read_bytes()).hexdigest()
        self.assertRegex(readme, rf"`crs_catalog\.json`\s*\|\s*`{digest}`")
        self.assertIn("IOGP", readme)
        listed = set(re.findall(r"^\| `([^`]+)` \|", readme, re.MULTILINE))
        present = {p.name for p in EPSG_FOLDER.iterdir()} - {"LICENSE", "README.md"}
        self.assertEqual(listed, present)

    def test_load_catalog_is_cached(self) -> None:
        """RF-002-23: ``load_catalog`` lee el fichero una vez y devuelve el mismo
        catálogo."""
        self.assertIs(crs.load_catalog(), crs.load_catalog())


if __name__ == "__main__":
    unittest.main()
