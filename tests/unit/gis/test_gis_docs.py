# SPDX-License-Identifier: GPL-3.0-or-later
"""La topografía frente a su documentación (spec 006, T37; plan 006 §5.6, D20 y D22).

Como el esquema de la procedencia frente a ``formato-proyecto.md`` (spec 008, T62), el código
manda y la documentación lo describe; estas pruebas avisan de que se separan:

- ``docs/arquitectura/modulos/gis.md``: lo que nombra de ``gis`` en su API existe en el código y
  la API nombra cada módulo del paquete; nombra cada lector de contenido de ``gis.content`` con
  su versión, cada tipo de operación de ``gis.provenance`` y cada parámetro de ``gis.params``;
- ``docs/arquitectura/datos/formato-proyecto.md`` §4.2: sin el ``<nombre>__<hash8>.tif`` de un
  fichero bloqueado (D20: la operación falla sin escribir) y con lo importado de una entrada
  con su uid corto (D22); §4.3: el npz de un TIN con el *deflate* del nivel con que lo escribe
  ``gis.tin`` (T35).

Sin la carpeta de la documentación, se omiten (recurso ``docs``).
"""

from __future__ import annotations

import pkgutil
import re
import unittest

from tests.support import docs
from tests.support.bs_tables import backticked, section
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
gis_content = import_geoblender("gis.content")
gis_params = import_geoblender("gis.params")
provenance = import_geoblender("gis.provenance")
tin = import_geoblender("gis.tin")

GIS_RELPATH = "docs/arquitectura/modulos/gis.md"
FORMAT_RELPATH = "docs/arquitectura/datos/formato-proyecto.md"
GIS_NAME = re.compile(r"^gis(?:\.[A-Za-z_]\w*)+$")
UID = "3f2b9c1d-8e7a-4b6c-9d0e-1a2b3c4d5e6f"  # el uid de una entrada (un UUID en texto)


def resolves(dotted: str) -> bool:
    """``gis.<módulo>[.<nombre>…]`` existe en el código."""
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            obj = import_geoblender(".".join(parts[:cut]))
        except ModuleNotFoundError:
            continue
        for name in parts[cut:]:
            if not hasattr(obj, name):
                return False
            obj = getattr(obj, name)
        return True
    return False


@docs.requires_docs
class GisModuleDocTest(unittest.TestCase):
    """``modulos/gis.md`` nombra la API, los lectores, las operaciones y los parámetros que
    existen."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(GIS_RELPATH)

    def test_named_api_exists(self) -> None:
        """RF-006-01, RF-006-08, RF-006-13, RF-006-18, RF-006-19, RF-006-26 (plan 006 §5.3):
        todo lo que la API de la ficha nombra de ``gis`` existe, y la nombra cada módulo del
        paquete."""
        api = section(self.text, "## API pública")
        named = {token for token in backticked(api) if GIS_NAME.match(token)}
        self.assertGreater(len(named), 40)
        self.assertEqual(sorted(name for name in named if not resolves(name)), [])
        for info in pkgutil.iter_modules(gis.__path__):
            with self.subTest(module=info.name):
                self.assertTrue(any(name == f"gis.{info.name}"
                                    or name.startswith(f"gis.{info.name}.")
                                    for name in named))

    def test_readers_operations_and_parameters(self) -> None:
        """RF-006-26 (plan 006 §5.6.1 a §5.6.3; D17): la ficha nombra cada lector de contenido
        de la topografía con su versión, cada tipo de operación y cada parámetro, con los de
        control en su párrafo."""
        readers = set(backticked(section(self.text, "## Lectores de contenido")))
        for reader in gis_content.CONTENT_READERS:
            with self.subTest(reader=reader.id):
                self.assertIn(reader.id, readers)
        operations = section(self.text, "## Operaciones, datos y parámetros")
        named = set(backticked(operations))
        for declared in provenance.OPERATION_TYPES:
            with self.subTest(operation=declared.op_type):
                self.assertIn(declared.op_type, named)
        for definition in gis_params.DEFINITIONS:
            with self.subTest(parameter=definition.key):
                self.assertIn(definition.key, named)
        control = next(paragraph for paragraph in operations.split("\n\n")
                       if paragraph.startswith("**De control**"))
        self.assertEqual(
            sorted(token for token in backticked(control) if token in gis_params.PARAMS),
            sorted(("gis.tin.blender_cdt_max_s", "gis.import.max_cells",
                    "gis.vertical.ellipsoidal_band_m", "gis.validate.z_range_m",
                    "gis.view.lod_steps_m")))


@docs.requires_docs
class ProjectFormatDocTest(unittest.TestCase):
    """``formato-proyecto.md`` describe los rásteres y el TIN que escribe la topografía."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(FORMAT_RELPATH)

    def test_rasters_without_a_hashed_name(self) -> None:
        """RF-006-08, RF-006-24 (plan 006 §5.6.5, D20 y D22): §4.2 no dice que un fichero
        bloqueado se escriba como ``<nombre>__<hash8>.tif`` (la operación falla sin escribir,
        con el anterior intacto) y nombra lo importado con el uid corto de su entrada."""
        rasters = section(self.text, "### 4.2 `rasters/` — GeoTIFF")
        self.assertNotIn("__<hash8>", rasters)
        self.assertEqual(provenance.dataset_locator("src", "mdt", input_uid=UID),
                         "rasters/gis_src_mdt_3f2b9c1d.tif")
        self.assertEqual(provenance.dataset_locator("dtm", "mdt"), "rasters/gis_dtm_mdt.tif")
        named = backticked(rasters)
        self.assertIn("gis_src_<slug>_<entrada8>.tif", named)
        self.assertIn("gis_dtm_<slug>.tif", named)
        self.assertIn("gis.raster_target_locked", named)

    def test_tin_npz_with_its_deflate_level(self) -> None:
        """RF-006-13 (T35; plan 006 §5.2.2): §4.3 dice con qué *deflate* se escribe el npz de
        un TIN, el nivel que usa ``gis.tin``, y no que se escriba con
        ``numpy.savez_compressed``."""
        meshes = section(self.text, "### 4.3 `meshes/` — npz")
        self.assertIn(f"*deflate* de nivel {tin._NPZ_LEVEL}", meshes)
        self.assertNotIn("Se escribe con `numpy.savez_compressed`", meshes)


if __name__ == "__main__":
    unittest.main()
