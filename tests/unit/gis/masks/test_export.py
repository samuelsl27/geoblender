# SPDX-License-Identifier: GPL-3.0-or-later
"""Exportar la rejilla de clases de las restricciones (spec 012, T20; HU-012-2; RF-012-20; plan
012 §5.3.4, D-25 y D-32; D-29 de la 011: exportar no es una operación).

``gis.masks.export`` escribe la rejilla de clases **registrada** de una versión como GeoTIFF
entregable (Float32, sin dato −9999, el CRS del proyecto: RF-006-24) con su leyenda en español, de
dos maneras: en los metadatos del propio GeoTIFF (``GDAL_METADATA``: ``CLASE_<código>`` por cada
código presente, ``VERSION`` y ``LEYENDA``) y en un ``.qml`` paletado junto al fichero, que QGIS
aplica solo. Los códigos son la suma de los bits de D-25 (una celda puede ser a la vez «corte
admitido» y «dentro del perímetro»), así que la leyenda lleva solo los códigos que hay y el
nombre de cada uno junta los de sus bits.

- **La leyenda**: el nombre de un código son los de sus bits, de menor a mayor, unidos con « + »
  (3 = «Corte admitido + Relleno admitido»); 0 es «Sin clase»; también en inglés. Los códigos que
  hay son los valores distintos de la rejilla. El ``.qml`` es un renderizador paletado de la
  banda 1 con una entrada por código (valor, etiqueta en español, color ``#rrggbb`` y opacidad;
  el 0, transparente) y se escribe de forma determinista.
- **El GeoTIFF**: se lee de vuelta con la misma rejilla, el CRS del proyecto (EPSG:25830) y los
  mismos códigos que las máscaras al día (``load_masks``); sus metadatos llevan el nombre en
  español de cada código y la versión. Se escribe desde lo registrado, sin escribir en el proyecto
  (ni operaciones ni datos nuevos).
- **El destino** (como en la exportación de la 011): con su extensión, fuera del proyecto o en su
  ``exports/``, con el proyecto escribible si es dentro, con la guarda de las escrituras de la 008
  y sobre un fichero que existe (o su ``.qml``) solo con ``overwrite``; sin escribir nada si se
  rechaza. Las máscaras que no están al día (sin compilar u obsoletas), también se rechazan
  (``core.constraint_masks_missing``, ``core.constraint_masks_stale``).
- **Por pasos**: el primero lee la rejilla, los siguientes escriben una tesela cada uno (≤ 0,05 s)
  y el último pone el GeoTIFF y el ``.qml`` en su sitio; cerrarlos antes (Esc) no deja nada.
"""

from __future__ import annotations

import sys
import time
import unittest
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support import constraints_project as cp
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

export = import_geoblender("gis.masks.export")
access = import_geoblender("gis.masks.access")
combine = import_geoblender("gis.masks.combine")
reader = import_geoblender("gis.geotiff.reader")
tiff = import_geoblender("gis.geotiff.tiff")
geokeys = import_geoblender("gis.geotiff.geokeys")
messages = import_geoblender("gis.messages")
paths = import_geoblender("core.paths")
cparams = import_geoblender("core.constraints.params")
cmessages = import_geoblender("core.constraints.messages")
params = import_geoblender("core.params")
versions_model = import_geoblender("core.versions.model")

Bit = combine.ClassBit
NO_READ_ONLY = paths.ReadOnlyDirs.from_sources(None, [])
BUDGET_S = 0.05
TOWER_V01_CELLS = fx.TOWER_ZONE_CELLS
"""Las celdas de la zona de la torre con 8 m en V01 (CE-012-01): las del bit «intocable»."""
V01_CELLS = {0: 13_900, 12: 1_700, 16: 1_450, 25: 750, 26: 136, 27: 5_718, 48: 1_650, 58: 236,
             88: 46, 120: 14}
"""Los códigos de la rejilla de clases de V01 con las celdas de cada uno (de ``combine``, T09):
10 códigos en las 25.600 celdas del sitio; los 12 son la franja (1.700 celdas, CE-012-03) y los
88 y 120, la torre (46 + 14 = 60 celdas, CE-012-01)."""
V01_LABELS = {
    12: "Franja de solo relleno + Dentro del perímetro de actuación",
    27: "Corte admitido + Relleno admitido + Dentro del perímetro de actuación + "
        "Dentro del límite legal",
    88: "Dentro del perímetro de actuación + Dentro del límite legal + Intocable o excluido",
}
"""El nombre en español de tres de ellos, escrito a mano."""


def _last(steps: Iterator[Any]) -> Any:
    result = None
    for step in steps:
        if step.result is not None:
            result = step.result
    return result


class LegendTest(unittest.TestCase):
    """La leyenda de los códigos (sin proyecto)."""

    def test_labels_join_the_bits_in_spanish_and_english(self) -> None:
        """RF-012-20: el nombre de un código junta los de sus bits, de menor a mayor, con « + »;
        el 0 es «Sin clase»; cada uno de los once bits tiene el suyo, en los dos idiomas."""
        names = {
            Bit.CUT_ALLOWED: "Corte admitido",
            Bit.FILL_ALLOWED: "Relleno admitido",
            Bit.FILL_STRIP: "Franja de solo relleno",
            Bit.PERIMETER: "Dentro del perímetro de actuación",
            Bit.LEGAL: "Dentro del límite legal",
            Bit.INNER_BAND: "Banda de resguardo hacia dentro del límite legal",
            Bit.UNTOUCHABLE: "Intocable o excluido",
            Bit.AVOID: "Preferible no afectar",
            Bit.RESTORATION: "Solo restauración",
            Bit.ACCESS: "Requiere acceso",
            Bit.CONFLICT: "Sin movimiento posible",
        }
        self.assertEqual(len(names), 11)
        for bit, text in names.items():
            with self.subTest(bit.name):
                self.assertEqual(export.class_label(int(bit)), text)
        self.assertEqual(export.class_label(0), "Sin clase")
        self.assertEqual(export.class_label(0, "en"), "No class")
        self.assertEqual(export.class_label(3), "Corte admitido + Relleno admitido")
        self.assertEqual(export.class_label(3, "en"), "Cut allowed + Fill allowed")
        self.assertEqual(
            export.class_label(1 + 8 + 16),
            "Corte admitido + Dentro del perímetro de actuación + Dentro del límite legal")
        everything = export.class_label(2047)
        self.assertEqual(everything.count(" + "), 10)
        self.assertEqual(len({export.class_label(code) for code in range(2048)}), 2048)

    def test_codes_out_of_range_are_refused(self) -> None:
        """RF-012-20: un código negativo, de más de once bits o que no es un entero es un error
        del programa."""
        for bad in (-1, 2048, 1.5, True, "3"):
            with self.subTest(bad), self.assertRaises((ValueError, TypeError)):
                export.class_label(bad)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            export.class_label(3, "fr")

    def test_present_codes(self) -> None:
        """RF-012-20: los códigos que hay son los valores distintos de la rejilla, de menor a
        mayor, como enteros."""
        classes = np.array([[3, 0, 3], [11, 0, 1024]], dtype=np.uint16)
        self.assertEqual(export.present_codes(classes), (0, 3, 11, 1024))
        self.assertTrue(all(type(code) is int for code in export.present_codes(classes)))
        with self.assertRaises(ValueError):
            export.present_codes(np.array([2048], dtype=np.uint16))

    def test_colors(self) -> None:
        """RF-012-20: cada código tiene un color determinista (``r, g, b, a``): el 0, transparente;
        los demás, opacos; un conflicto, un intocable y lo admitido se distinguen."""
        self.assertEqual(export.class_color(0)[3], 0)
        for code in (1, 3, 8, 9, 25, 64, 1024, 2047):
            with self.subTest(code):
                color = export.class_color(code)
                self.assertEqual(len(color), 4)
                self.assertTrue(all(isinstance(part, int) and 0 <= part <= 255 for part in color))
                self.assertEqual(color[3], 255)
                self.assertEqual(color, export.class_color(code))
        self.assertEqual(len({export.class_color(code) for code in (3, 64, 1024, 1 + 8 + 16)}), 4)

    def test_metadata_items(self) -> None:
        """RF-012-20: los metadatos llevan ``LEYENDA``, ``VERSION`` y ``CLASE_<código>`` por
        cada código presente, en ese orden, sin «&» (GDAL 3.13 lo lee mal)."""
        items = export.legend_items((0, 3, 1024), "V01")
        self.assertEqual(list(items), ["LEYENDA", "VERSION", "CLASE_0", "CLASE_3", "CLASE_1024"])
        self.assertEqual(items["VERSION"], "V01")
        self.assertEqual(items["CLASE_0"], "Sin clase")
        self.assertEqual(items["CLASE_3"], "Corte admitido + Relleno admitido")
        self.assertEqual(items["CLASE_1024"], "Sin movimiento posible")
        self.assertIn("suma", items["LEYENDA"])
        self.assertTrue(all("&" not in text for text in items.values()))
        geokeys.format_gdal_metadata(items)  # el escritor del GeoTIFF las admite

    def test_paletted_qml(self) -> None:
        """RF-012-20: el ``.qml`` es un renderizador paletado de la banda 1 con una entrada por
        código (valor, etiqueta en español, color y opacidad), igual cada vez."""
        codes = (0, 3, 24, 1024)
        text = export.classes_qml(codes)
        self.assertTrue(text.startswith("<!DOCTYPE qgis"))
        self.assertEqual(text, export.classes_qml(codes))
        root = ET.fromstring(text.split("\n", 1)[1])
        self.assertEqual(root.tag, "qgis")
        self.assertEqual(root.get("styleCategories"), "Symbology")
        (renderer,) = root.iter("rasterrenderer")
        self.assertEqual((renderer.get("type"), renderer.get("band")), ("paletted", "1"))
        entries = list(renderer.iter("paletteEntry"))
        self.assertEqual([entry.get("value") for entry in entries], [str(code) for code in codes])
        for entry, code in zip(entries, codes, strict=True):
            with self.subTest(code):
                self.assertEqual(entry.get("label"), export.class_label(code))
                red, green, blue, alpha = export.class_color(code)
                self.assertEqual(entry.get("color"), f"#{red:02x}{green:02x}{blue:02x}")
                self.assertEqual(entry.get("alpha"), str(alpha))
        self.assertEqual(entries[0].get("alpha"), "0")
        self.assertEqual(entries[2].get("label"),
                         "Dentro del perímetro de actuación + Dentro del límite legal")

    def test_no_codes_no_qml(self) -> None:
        """RF-012-20: una leyenda sin códigos es un error del programa."""
        with self.assertRaises(ValueError):
            export.classes_qml(())


class _ExportBase(cp.ConstraintsProjectCase):
    """El proyecto de las restricciones con las máscaras de V01 compiladas y una carpeta de
    destino fuera del proyecto."""

    masks: Any
    out: Path

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.out = cls.enterClassContext(project_tmp("gb-ex-"))
        cls.masks = _last(access.ensure_masks_steps(cls.project, cls.v1.uid, budget_s=BUDGET_S))

    def export(self, name: str = "clases.tif", **options: Any) -> Path:
        options.setdefault("read_only", NO_READ_ONLY)
        return export.export_classes(self.project, self.v1.uid, self.out / name, **options)

    def counts(self) -> tuple[int, int, int]:
        """Las operaciones, los datos y los eventos del proyecto (para ver que nada se escribe)."""
        return tuple(self.query(f"SELECT count(*) FROM {table}")[0][0]
                     for table in ("gb_operation", "gb_dataset", "gb_event"))  # type: ignore[return-value]

    def listing(self) -> list[str]:
        return sorted(path.name for path in self.out.iterdir())


class ExportTest(_ExportBase):
    """Exportar las clases de V01, rechazos y pasos, en orden sobre el mismo proyecto."""

    def test_a_the_grid_reads_back_georeferenced_with_its_legend(self) -> None:
        """RF-012-20 (RF-006-24): el GeoTIFF se lee de vuelta con la rejilla de las máscaras, el
        CRS del proyecto (EPSG:25830) y exactamente sus códigos; sus metadatos nombran en
        español cada código y la versión; el ``.qml`` es el de esos códigos; no queda ningún
        temporal ni se escribe nada en el proyecto."""
        before = self.counts()
        path = self.export()
        self.assertEqual(path, self.out / "clases.tif")
        self.assertEqual(self.listing(), ["clases.qml", "clases.tif"])
        self.assertEqual(self.counts(), before)

        found = reader.read_geotiff(path, max_cells=sys.maxsize)
        self.assertEqual(found.grid, self.masks.grid)
        self.assertEqual(found.grid, fx.SITE_GRID)
        self.assertEqual(found.declared_crs.epsg, 25830)
        self.assertEqual(found.source_dtype, "float32")
        self.assertEqual(found.nodata_value, -9999.0)
        values = np.asarray(found.values)
        self.assertTrue(np.isfinite(values).all())
        np.testing.assert_array_equal(values, self.masks.classes.astype(np.float64))
        self.assertEqual(int(((self.masks.classes & int(Bit.UNTOUCHABLE)) != 0).sum()),
                         TOWER_V01_CELLS)

        codes = export.present_codes(self.masks.classes)
        self.assertEqual(codes, tuple(V01_CELLS))
        self.assertEqual({code: int((values == code).sum()) for code in codes}, V01_CELLS)
        self.assertEqual(sum(V01_CELLS.values()), fx.SITE_GRID.nrows * fx.SITE_GRID.ncols)
        self.assertEqual(V01_CELLS[12] * fx.SITE_GRID.cell_area, fx.limits().strip_m2)
        self.assertEqual(V01_CELLS[88] + V01_CELLS[120], TOWER_V01_CELLS)
        with path.open("rb") as stream:
            ifd = tiff.read_first_ifd(stream, path.stat().st_size)
        items = geokeys.parse_gdal_items(ifd.text(tiff.GDAL_METADATA) or "")
        self.assertEqual(items, export.legend_items(codes, self.v1.code))
        self.assertEqual(items["VERSION"], self.v1.code)
        self.assertEqual([key for key in items if key.startswith("CLASE_")],
                         [f"CLASE_{code}" for code in codes])
        for code in codes:
            self.assertEqual(items[f"CLASE_{code}"], export.class_label(code))
        for code, text in V01_LABELS.items():
            self.assertEqual(items[f"CLASE_{code}"], text)
        self.assertEqual(items["CLASE_0"], "Sin clase")
        self.assertEqual((self.out / "clases.qml").read_text(encoding="utf-8"),
                         export.classes_qml(codes))

    def test_b_refusals_write_nothing(self) -> None:
        """RF-012-20 (RF-008-15): una extensión que no es de GeoTIFF, un destino que ya existe
        (o cuyo ``.qml`` ya existe) sin ``overwrite``, uno dentro del proyecto pero fuera de
        ``exports/``, una carpeta de solo lectura, un proyecto de solo lectura (con el destino en
        ``exports/``), máscaras sin compilar y una versión que no existe se rechazan con su
        código, sin escribir nada."""
        before, listing = self.counts(), self.listing()
        with self.assertRaises(messages.GisError) as caught:
            self.export("clases.png")
        self.assertEqual(caught.exception.code, "gis.export_extension_invalid")
        with self.assertRaises(messages.GisError) as caught:
            self.export("clases.tif")
        self.assertEqual(caught.exception.code, "gis.export_target_exists")
        (self.out / "otras.qml").write_text("x", encoding="utf-8")
        with self.assertRaises(messages.GisError) as caught:
            self.export("otras.tif")
        self.assertEqual(caught.exception.code, "gis.export_target_exists")
        self.assertIn("otras.qml", str(caught.exception))
        (self.out / "otras.qml").unlink()
        with self.assertRaises(messages.GisError) as caught:
            export.export_classes(self.project, self.v1.uid, Path(self.project.root) / "clases.tif",
                                  read_only=NO_READ_ONLY)
        self.assertEqual(caught.exception.code, "gis.export_inside_project")
        locked = paths.ReadOnlyDirs.from_sources(str(self.out), [])
        with self.assertRaises(Exception) as caught:
            self.export("nuevo.tif", read_only=locked)
        self.assertEqual(caught.exception.code, "core.write_target_read_only")  # type: ignore[attr-defined]
        with self.assertRaises(cmessages.ConstraintError) as caught:
            export.export_classes(_ReadOnlyProject(self.project), self.v1.uid,
                                  Path(self.project.root) / "exports" / "clases.tif",
                                  read_only=NO_READ_ONLY)
        self.assertEqual(caught.exception.code, "core.constraint_export_read_only")
        with self.assertRaises(access.MaskError) as caught:
            export.export_classes(self.project, self.v2.uid, self.out / "v2.tif",
                                  read_only=NO_READ_ONLY)
        self.assertEqual(caught.exception.code, "core.constraint_masks_missing")
        with self.assertRaises(versions_model.VersionError) as caught:
            export.export_classes(self.project, "V99", self.out / "v99.tif",
                                  read_only=NO_READ_ONLY)
        self.assertEqual(caught.exception.code, "core.version_unknown")
        self.assertEqual((self.counts(), self.listing()), (before, listing))

    def test_c_overwrite_replaces_both_files(self) -> None:
        """RF-012-20: con ``overwrite`` se sustituyen el GeoTIFF y el ``.qml``, con los mismos
        bytes (determinista), y no queda ningún temporal."""
        first = {name: (self.out / name).read_bytes() for name in ("clases.tif", "clases.qml")}
        for name in first:
            (self.out / name).write_bytes(b"viejo")
        self.export(overwrite=True)
        self.assertEqual({name: (self.out / name).read_bytes() for name in first}, first)
        self.assertEqual(self.listing(), ["clases.qml", "clases.tif"])

    def test_d_steps_are_short_and_closing_them_leaves_nothing(self) -> None:
        """RF-012-20 (RNF-012-06): el primer paso lee, los demás escriben una tesela, ninguno pasa
        de 0,05 s y el avance crece hasta 1; cerrar los pasos a mitad no deja ni el GeoTIFF, ni el
        ``.qml``, ni temporales; los rechazos salen al llamar, antes del primer paso."""
        before = self.listing()
        steps = export.export_classes_steps(self.project, self.v1.uid, self.out / "pasos.tif",
                                            read_only=NO_READ_ONLY)
        first = next(steps)
        self.assertEqual(first, 0.0)
        steps.close()
        self.assertEqual(self.listing(), before)

        steps = export.export_classes_steps(self.project, self.v1.uid, self.out / "pasos.tif",
                                            read_only=NO_READ_ONLY)
        fractions: list[float] = []
        longest = 0.0
        while True:
            started = time.perf_counter()
            try:
                fractions.append(next(steps))
            except StopIteration as stop:
                longest = max(longest, time.perf_counter() - started)
                self.assertEqual(stop.value, self.out / "pasos.tif")
                break
            longest = max(longest, time.perf_counter() - started)
        self.assertEqual(fractions[0], 0.0)
        self.assertEqual(fractions[-1], 1.0)
        self.assertEqual(fractions, sorted(fractions))
        self.assertLessEqual(longest, BUDGET_S)
        self.assertEqual(self.listing(), sorted([*before, "pasos.qml", "pasos.tif"]))
        with self.assertRaises(messages.GisError):  # al llamar, no al primer paso
            export.export_classes_steps(self.project, self.v1.uid, self.out / "pasos.tif",
                                        read_only=NO_READ_ONLY)

    def test_e_inside_exports_folder_of_the_project(self) -> None:
        """RF-012-20 (D-29 de la 011): dentro de ``exports/`` del proyecto también se exporta,
        sin registrar el entregable como dato."""
        folder = Path(self.project.root) / "exports"
        folder.mkdir(exist_ok=True)
        target = folder / "clases.tif"
        self.addCleanup(lambda: [path.unlink(missing_ok=True) for path in (
            target, target.with_suffix(".qml"))])
        before = self.counts()
        export.export_classes(self.project, self.v1.uid, target, read_only=NO_READ_ONLY)
        self.assertTrue(target.is_file() and target.with_suffix(".qml").is_file())
        self.assertEqual(self.counts(), before)

    def test_f_stale_masks_are_not_exported(self) -> None:
        """RF-012-20 (RF-012-17): con las máscaras obsoletas (cambió el resguardo de la torre en
        V01) no se exporta nada: ``core.constraint_masks_stale`` con la orden de compilar."""
        self.clock.advance(minutes=1)
        store = params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            store.change(conn, cparams.buffer_out_key("torre"), value=10.0,
                         reason="Prueba de la exportación", version=self.v1.code)
        before, listing = self.counts(), self.listing()
        with self.assertRaises(access.MaskError) as caught:
            self.export("obsoletas.tif")
        self.assertEqual(caught.exception.code, "core.constraint_masks_stale")
        self.assertIn("geoblender.gis_compile_constraints", str(caught.exception))
        self.assertEqual((self.counts(), self.listing()), (before, listing))


class _ReadOnlyProject:
    """El proyecto como si estuviera abierto en solo lectura (lo demás, el mismo)."""

    writable = False

    def __init__(self, project: Any) -> None:
        self._project = project

    def __getattr__(self, name: str) -> Any:
        return getattr(self._project, name)


if __name__ == "__main__":
    unittest.main()
