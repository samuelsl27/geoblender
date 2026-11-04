# SPDX-License-Identifier: GPL-3.0-or-later
"""Exportar a GeoTIFF una rejilla del diseño (spec 013, T19; HU-013-6; RF-013-34; RF-006-24;
plan 013 §5.1 y §5.3.3; D-29 de la 011: exportar no es una operación).

``design.export`` escribe la envolvente (``des_env_``), la superficie de diseño (``des_srf_``) o la
rejilla de cotas de berma (``des_brm_``) **registradas** de una versión como GeoTIFF entregable del
perfil ``deliverable`` de la 006 (Float32, sin dato −9999, el CRS y la referencia vertical del
proyecto) y no escribe nada en el proyecto. Sobre el proyecto del diseño (una copia por clase) con
una envolvente y un escalonado en V01 calculados con ``design`` de verdad, en el orden de las
pruebas:

- **a**: cada una de las tres rejillas se lee de nuevo con ``gis`` con la misma rejilla, el CRS y la
  referencia vertical del proyecto, el «sin dato» −9999 declarado y cada cota **igual a la
  registrada redondeada a float32 (0 m de diferencia)**; las celdas sin dato siguen sin dato.
- **b**: los metadatos del fichero dicen la unidad (m), de qué es y de qué versión.
- **c**: no se escribe nada en el proyecto (ni operaciones, ni datos, ni eventos) y no queda ningún
  temporal.
- **d**: los rechazos (extensión, destino que existe, dentro del proyecto fuera de ``exports/``,
  carpeta de solo lectura, proyecto de solo lectura, versión o rejilla que no existen, una familia
  que no es una rejilla) no escriben nada.
- **e**: con ``overwrite`` se sustituye, con los mismos bytes.
- **f**: los pasos son cortos, el avance crece hasta 1 y cerrarlos a mitad no deja nada; con el
  destino abierto por otro programa, ``gis.raster_target_locked`` y el anterior intacto.
- **g**: dentro de ``exports/`` del proyecto también se exporta, sin registrar el entregable.
"""

from __future__ import annotations

import sys
import time
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as dfx
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

export = import_geoblender("design.export")
store = import_geoblender("design.store")
provenance = import_geoblender("design.provenance")
model = import_geoblender("design.model")
design_params = import_geoblender("design.params")
design_messages = import_geoblender("design.messages")
core_params = import_geoblender("core.params")
paths = import_geoblender("core.paths")
versions_model = import_geoblender("core.versions.model")
gis_provenance = import_geoblender("gis.provenance")
reader = import_geoblender("gis.geotiff.reader")
writer = import_geoblender("gis.geotiff.writer")
tiff = import_geoblender("gis.geotiff.tiff")
geokeys = import_geoblender("gis.geotiff.geokeys")
gis_messages = import_geoblender("gis.messages")
res_provenance = import_geoblender("reserves.provenance")

NO_READ_ONLY = paths.ReadOnlyDirs.from_sources(None, [])
BUDGET_S = 0.05
PROFILE = "expl_10_60_6"
PROFILE_VALUES = {"height_m": 10.0, "face_deg": 60.0, "berm_m": 6.0, "anchor_m": 125.0,
                  "mesh_factor": 1.0}
BY_HAND = {"source": "Perfil de prueba", "source_kind": "person", "decided_by": "Samuel (IMGA)"}
ENVELOPE_NAME = "Hueco inicial"
BOTTOM_M = 630.0
"""El fondo del hoyo: la cota fija de las semillas del sector 1 (más baja que el terreno)."""
DESIGN_NAME = "Diseño inicial"
NAMES = {provenance.ENVELOPE_GRID: ENVELOPE_NAME, provenance.DESIGN_GRID: DESIGN_NAME,
         provenance.BERMS_GRID: DESIGN_NAME}
"""El nombre de la operación de cada rejilla exportable (la rejilla de bermas es del escalonado)."""
GRIDS = tuple(NAMES)
LABELS = {provenance.ENVELOPE_GRID: "Envolvente",
          provenance.DESIGN_GRID: "Superficie de diseño",
          provenance.BERMS_GRID: "Cota real de las bermas"}
NODATA = -9999.0
WITH_NODATA = (provenance.ENVELOPE_GRID, provenance.BERMS_GRID)


def _never(request: Any) -> Any:
    raise AssertionError("las pruebas de exportar no recalculan ni reproducen")


def definitions() -> tuple[Any, ...]:
    """Lo que declara ``des`` a la procedencia, como lo registrará ``bl``."""
    return (*provenance.operation_defs({t: _never for t in provenance.REPRODUCIBLE},
                                       {t: _never for t in provenance.REPRODUCIBLE}),
            *provenance.FIGURES)


def last(steps: Iterator[Any]) -> Any:
    """El último ``Progress`` de unos pasos."""
    found = None
    for found in steps:
        pass
    return found


class _ReadOnlyProject:
    """Un proyecto abierto en solo lectura (lo demás, el de siempre)."""

    writable = False

    def __init__(self, project: Any) -> None:
        self._project = project

    def __getattr__(self, name: str) -> Any:
        return getattr(self._project, name)


class ExportTest(dfx.DesignProjectCase):
    """RF-013-34: exportar las tres rejillas de V01, en el orden de las pruebas (el proyecto, la
    carpeta de destino y lo exportado son de la clase)."""

    out: Path

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions(design_params.DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        cls.enterClassContext(registered(*definitions()))
        cls.out = cls.enterClassContext(project_tmp("gb-dx-"))
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for param, value in PROFILE_VALUES.items():
                core_params.ParameterStore(cls.project).create(
                    conn, design_params.bench_key(PROFILE, param), value,
                    kind="ADOPTADO" if param == "mesh_factor" else "HIPÓTESIS",
                    reason="Perfil de prueba", **BY_HAND)
        request = model.EnvelopeRequest(
            name=ENVELOPE_NAME, direction="up",
            seeds=model.SeedSource("fixed", elevation_m=BOTTOM_M,
                                   zone=model.Zone("sector", "sector_1")),
            slope_mode="constant", slope_deg=35.0, metric="chamfer5", mesh_factor=1.0,
            reach_m=None, domain=model.WorkDomain())
        cls.clock.advance(minutes=1)
        _handle, steps = store.run_envelope(cls.project, request, version=cls.v1.uid)
        last(steps)
        design = model.DesignRequest(name=DESIGN_NAME, envelope=ENVELOPE_NAME, sense="cut",
                                     base_profile=PROFILE, sector_profiles={}, anchor_grid=None)
        cls.clock.advance(minutes=1)
        _handle, steps = store.run_design(cls.project, design, dfx.START_DATASET,
                                          version=cls.v1.uid)
        last(steps)

    # --- Ayudas -------------------------------------------------------------------------------

    def registered(self, family: str) -> Any:
        """La rejilla registrada de ``family`` en V01, leída con ``gis`` (float64, NaN sin dato)."""
        record = self.record(provenance.dataset_name(family, NAMES[family]), self.v1)
        self.assertIsNotNone(record, family)
        return reader.read_geotiff(self.root.joinpath(*record.locator.split("/")),
                                   max_cells=sys.maxsize)

    def export(self, family: str, name: str | None = None, **options: Any) -> Path:
        """Exporta la rejilla ``family`` de V01 a ``out/<nombre>`` (por defecto, ``<familia>.tif``)."""
        options.setdefault("read_only", NO_READ_ONLY)
        options.setdefault("version", self.v1.uid)
        return export.export_grid(self.project, family, NAMES[family],
                                  self.out / (name or f"{family}.tif"), **options)

    def steps(self, family: str, name: str, **options: Any) -> Iterator[float]:
        options.setdefault("read_only", NO_READ_ONLY)
        options.setdefault("version", self.v1.uid)
        return export.export_grid_steps(self.project, family, NAMES[family], self.out / name,
                                        **options)

    def counts(self) -> tuple[int, int, int]:
        """Las operaciones, los datos y los eventos del proyecto (para ver que nada se escribe)."""
        return tuple(self.query(f"SELECT count(*) FROM {table}")[0][0]  # type: ignore[return-value]
                     for table in ("gb_operation", "gb_dataset", "gb_event"))

    def listing(self) -> list[str]:
        return sorted(path.name for path in self.out.iterdir())

    # --- La historia --------------------------------------------------------------------------

    def test_a_each_grid_reads_back_equal_to_the_registered_one_rounded_to_float32(self) -> None:
        """RF-013-34 (RF-006-24): las tres rejillas se leen de nuevo con ``gis`` con la rejilla de
        la registrada, el CRS del proyecto (EPSG:25830) y su referencia vertical, el «sin dato»
        −9999 declarado y cada cota igual a la registrada pasada a float32 (0 m de diferencia, y a
        media unidad de float32 de la de float64); las celdas sin dato (las que tiene la
        envolvente y la de bermas) siguen sin dato y ninguna cota es el «sin dato»."""
        for family in GRIDS:
            with self.subTest(family=family):
                stored = self.registered(family)
                path = self.export(family)
                found = reader.read_geotiff(path, max_cells=sys.maxsize)
                self.assertEqual(found.grid, stored.grid)
                self.assertEqual(found.grid, cfx.SITE_GRID)
                self.assertEqual((found.declared_crs.epsg, found.declared_vertical.epsg),
                                 (25830, self.project.record.vcrs_epsg))
                self.assertEqual((found.source_dtype, found.nodata_value), ("float32", NODATA))
                finite = np.isfinite(stored.values)
                self.assertTrue(finite.any())
                self.assertEqual(not finite.all(), family in WITH_NODATA,
                                 "la envolvente y la de bermas tienen celdas sin dato; la "
                                 "superficie de diseño (la de partida con el hoyo) no")
                expected = np.where(finite, stored.values.astype(np.float32).astype(np.float64),
                                    np.nan)
                np.testing.assert_array_equal(found.values, expected)  # 0 m (y NaN con NaN)
                self.assertEqual(int(np.isfinite(found.values).sum()), int(finite.sum()))
                self.assertFalse((found.values == NODATA).any())
                half_unit = np.spacing(np.abs(stored.values[finite]).astype(np.float32)) / 2
                self.assertTrue((np.abs(found.values[finite] - stored.values[finite])
                                 <= half_unit).all())
                # Las cotas son metros: las de la rejilla registrada, sin escala ni desplazamiento.
                self.assertEqual(float(found.values[finite].min()),
                                 float(np.float32(stored.values[finite].min())))
                self.assertEqual(float(found.values[finite].max()),
                                 float(np.float32(stored.values[finite].max())))

    def test_b_the_metadata_say_the_unit_what_it_is_and_the_version(self) -> None:
        """RF-013-34: los metadatos del GeoTIFF declaran que la cota va en metros, qué es (en
        español), el dato del proyecto del que sale y su versión."""
        for family in GRIDS:
            with self.subTest(family=family):
                path = self.out / f"{family}.tif"
                with path.open("rb") as stream:
                    ifd = tiff.read_first_ifd(stream, path.stat().st_size)
                items = geokeys.parse_gdal_items(ifd.text(tiff.GDAL_METADATA) or "")
                self.assertEqual(items, {
                    "UNIDAD": "m", "TIPO": LABELS[family],
                    "DATO": provenance.dataset_name(family, NAMES[family]),
                    "VERSION": self.v1.code})
                self.assertEqual(items, export.metadata_items(family, NAMES[family],
                                                              self.v1.code))

    def test_c_nothing_is_written_in_the_project_and_no_temporary_is_left(self) -> None:
        """RF-013-34 (D-29 de la 011): exportar no es una operación: ni operaciones, ni datos, ni
        eventos nuevos, y en la carpeta de destino solo están los GeoTIFF (ni temporales ni
        ``.qml``)."""
        before = self.counts()
        self.export(provenance.DESIGN_GRID, "otra.tif")
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.listing(), sorted([f"{family}.tif" for family in GRIDS]
                                                + ["otra.tif"]))
        (self.out / "otra.tif").unlink()

    def test_d_refusals_write_nothing(self) -> None:
        """RF-013-34 (RF-008-15): una extensión que no es de GeoTIFF, un destino que ya existe, uno
        dentro del proyecto pero fuera de ``exports/``, una carpeta de solo lectura, un proyecto de
        solo lectura (con el destino en ``exports/``), una ruta demasiado larga, una versión que
        no existe, una rejilla que la versión no tiene (V02 no calculó nada) o cuyo fichero falta,
        una familia que no es una rejilla y un nombre vacío se rechazan con su código, sin
        escribir nada."""
        design = provenance.DESIGN_GRID
        before, listing = self.counts(), self.listing()
        with self.assertRaises(gis_messages.GisError) as caught:
            self.export(design, "diseno.png")
        self.assertEqual(caught.exception.code, "gis.export_extension_invalid")
        with self.assertRaises(gis_messages.GisError) as caught:
            self.export(design)
        self.assertEqual(caught.exception.code, "gis.export_target_exists")
        with self.assertRaises(gis_messages.GisError) as caught:
            export.export_grid(self.project, design, DESIGN_NAME, self.root / "diseno.tif",
                               version=self.v1.uid, read_only=NO_READ_ONLY)
        self.assertEqual(caught.exception.code, "gis.export_inside_project")
        locked = paths.ReadOnlyDirs.from_sources(str(self.out), [])
        with self.assertRaises(Exception) as caught:
            self.export(design, "nuevo.tif", read_only=locked)
        self.assertEqual(caught.exception.code, "core.write_target_read_only")  # type: ignore[attr-defined]
        with self.assertRaises(design_messages.DesignError) as caught:
            export.export_grid(_ReadOnlyProject(self.project), design, DESIGN_NAME,
                               self.root / "exports" / "diseno.tif", version=self.v1.uid,
                               read_only=NO_READ_ONLY)
        self.assertEqual(caught.exception.code, "des.export_read_only_project")
        with self.assertRaises(versions_model.VersionError) as caught:
            self.export(design, "v99.tif", version="V99")
        self.assertEqual(caught.exception.code, "core.version_unknown")
        with self.assertRaises(design_messages.DesignError) as caught:
            self.export(design, "v02.tif", version=self.v2.uid)
        self.assertEqual(caught.exception.code, "des.export_unknown")
        self.assertIn("V02", str(caught.exception))
        self.assertEqual((caught.exception.field, caught.exception.value),
                         ("rejilla", DESIGN_NAME))
        with self.assertRaises(design_messages.DesignError) as caught:
            export.export_grid(self.project, design, "Otro diseño", self.out / "otro.tif",
                               version=self.v1.uid, read_only=NO_READ_ONLY)
        self.assertEqual(caught.exception.code, "des.export_unknown")
        for table in (provenance.BERM_TABLE, provenance.REPORT_TABLE, "xyz"):
            with self.assertRaises(ValueError):
                export.export_grid(self.project, table, DESIGN_NAME, self.out / "tabla.tif",
                                   version=self.v1.uid, read_only=NO_READ_ONLY)
        with self.assertRaises(TypeError):
            export.export_grid(self.project, design, " ", self.out / "vacio.tif",
                               version=self.v1.uid, read_only=NO_READ_ONLY)
        with self.assertRaises(TypeError):
            self.export(design, "otra.tif", overwrite="sí")
        # El destino cabe justo en el límite de Windows, pero su temporal (``.tmp``) no.
        fits = "n" * (paths.MAX_FILE_PATH_CHARS - len(str(self.out)) - 1 - len(".tif")) + ".tif"
        self.assertEqual(len(str(self.out / fits)), paths.MAX_FILE_PATH_CHARS)
        with self.assertRaises(Exception) as caught:  # al llamar, antes del primer paso
            self.steps(design, fits)
        self.assertEqual(caught.exception.code, "core.path_too_long")  # type: ignore[attr-defined]
        self.assertIn(".tmp", str(caught.exception))
        record = self.record(provenance.dataset_name(design, DESIGN_NAME), self.v1)
        kept = self.root.joinpath(*record.locator.split("/"))
        hidden = kept.with_name(kept.name + ".oculto")
        kept.rename(hidden)  # el dato está registrado, pero su fichero falta
        try:
            with self.assertRaises(gis_messages.GisError) as caught:
                self.export(design, "falta.tif")
        finally:
            hidden.rename(kept)
        self.assertEqual(caught.exception.code, "gis.dataset_file_missing")
        self.assertEqual((self.counts(), self.listing()), (before, listing))

    def test_e_overwrite_replaces_with_the_same_bytes(self) -> None:
        """RF-013-34: con ``overwrite`` se sustituye el fichero, con los mismos bytes (el mismo
        ráster da el mismo fichero), y no queda ningún temporal."""
        design = provenance.DESIGN_GRID
        first = (self.out / f"{design}.tif").read_bytes()
        (self.out / f"{design}.tif").write_bytes(b"viejo")
        self.export(design, overwrite=True)
        self.assertEqual((self.out / f"{design}.tif").read_bytes(), first)
        self.assertEqual(self.listing(), sorted(f"{family}.tif" for family in GRIDS))

    def test_f_steps_are_short_closing_them_leaves_nothing_and_a_locked_target_is_refused(
            self) -> None:
        """RF-013-34 (RNF-013-07): el primer paso lee, los demás escriben una tesela, ninguno pasa
        de 0,05 s y el avance crece hasta 1; cerrar los pasos a mitad no deja ni el GeoTIFF ni
        temporales; los rechazos salen al llamar, antes del primer paso; y con el destino abierto
        por otro programa (``PermissionError`` al sustituirlo), ``gis.raster_target_locked`` con el
        fichero anterior intacto y sin temporales."""
        design = provenance.DESIGN_GRID
        before = self.listing()
        with mock.patch.object(writer, "TILE_SIZE", 64):  # 160 × 160: 9 teselas
            steps = self.steps(design, "pasos.tif")
            self.assertEqual(next(steps), 0.0)
            self.assertLess(next(steps), 1.0)
            steps.close()
            self.assertEqual(self.listing(), before)

            fractions: list[float] = []
            longest = 0.0
            steps = self.steps(design, "pasos.tif")
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
        self.assertEqual(len(fractions), 1 + 9)
        self.assertEqual(fractions, sorted(fractions))
        self.assertLessEqual(longest, BUDGET_S)
        self.assertEqual(self.listing(), sorted([*before, "pasos.tif"]))
        stored = self.registered(design)
        found = reader.read_geotiff(self.out / "pasos.tif", max_cells=sys.maxsize)
        np.testing.assert_array_equal(found.values, np.where(
            np.isfinite(stored.values), stored.values.astype(np.float32), np.nan))
        with self.assertRaises(gis_messages.GisError):  # al llamar, no al primer paso
            self.steps(design, "pasos.tif")

        kept = (self.out / "pasos.tif").read_bytes()
        with mock.patch.object(writer.os, "replace", side_effect=PermissionError("abierto")):
            with self.assertRaises(gis_messages.GisError) as caught:
                last(self.steps(design, "pasos.tif", overwrite=True))
        self.assertEqual(caught.exception.code, "gis.raster_target_locked")
        self.assertEqual((self.out / "pasos.tif").read_bytes(), kept)
        self.assertEqual(self.listing(), sorted([*before, "pasos.tif"]))
        (self.out / "pasos.tif").unlink()

    def test_g_inside_the_exports_folder_of_the_project_it_exports_without_registering(
            self) -> None:
        """RF-013-34 (D-29 de la 011): dentro de ``exports/`` del proyecto también se exporta,
        sin registrar el entregable como dato."""
        folder = self.root / "exports"
        folder.mkdir(exist_ok=True)
        target = folder / "diseno.tif"
        self.addCleanup(target.unlink, missing_ok=True)
        before = self.counts()
        export.export_grid(self.project, provenance.DESIGN_GRID, DESIGN_NAME, target,
                           version=self.v1.uid, read_only=NO_READ_ONLY)
        self.assertTrue(target.is_file())
        self.assertEqual(self.counts(), before)
        self.assertEqual(target.read_bytes(), (self.out / f"{provenance.DESIGN_GRID}.tif"
                                               ).read_bytes())

    def test_h_a_dataset_is_found_as_an_exportable_grid_only_if_it_is_a_live_design_grid(
            self) -> None:
        """RF-013-34 (T28; D-29 de la 011): ``stored_grid`` da, de un dato por su uid o por su nombre
        en una versión, su familia, el nombre de su operación (el de su dato) y su versión, que es
        justo lo que pide ``export_grid_steps``; solo lo hace de una rejilla viva del diseño: una
        tabla, un dato de otro módulo, uno que no existe, uno por su nombre sin la versión y uno
        sustituido se rechazan con ``des.export_not_grid`` y un valor que no es un texto, con
        ``TypeError``; ni lo uno ni lo otro escribe nada."""
        before = self.counts()
        slugs = {family: gis_provenance.dataset_slug(NAMES[family]) for family in GRIDS}
        for family in GRIDS:
            with self.subTest(family=family):
                record = self.record(provenance.dataset_name(family, NAMES[family]), self.v1)
                by_uid = export.stored_grid(self.project, record.uid)
                self.assertEqual((by_uid.record.uid, by_uid.family, by_uid.name,
                                  by_uid.version_uid, by_uid.version_code),
                                 (record.uid, family, slugs[family], self.v1.uid, self.v1.code))
                by_name = export.stored_grid(self.project, record.name, version=self.v1.uid)
                self.assertEqual(by_name, by_uid)
                # Lo que da es lo que exporta: el nombre sirve tal cual para ``export_grid``.
                path = export.export_grid(
                    self.project, by_uid.family, by_uid.name, self.out / f"h_{family}.tif",
                    version=by_uid.version_uid, read_only=NO_READ_ONLY)
                self.assertEqual(path.read_bytes(), (self.out / f"{family}.tif").read_bytes())
                path.unlink()
        table = self.record(provenance.dataset_name(provenance.REPORT_TABLE, DESIGN_NAME),
                            self.v1)
        start = self.record(dfx.START_DATASET, None)
        for ref, version in ((table.uid, ""), (table.name, self.v1.uid), (start.uid, ""),
                             (start.name, ""),
                             (provenance.dataset_name(provenance.DESIGN_GRID, DESIGN_NAME), ""),
                             (provenance.dataset_name(provenance.DESIGN_GRID, DESIGN_NAME),
                              self.v2.uid), ("zzz", self.v1.uid), ("0" * 32, "")):
            with self.subTest(ref=ref, version=version):
                with self.assertRaises(design_messages.DesignError) as caught:
                    export.stored_grid(self.project, ref, version=version)
                self.assertEqual(caught.exception.code, "des.export_not_grid")
                self.assertEqual((caught.exception.field, caught.exception.value),
                                 ("rejilla", ref))
        for bad in ("", None, 7):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                export.stored_grid(self.project, bad)  # type: ignore[arg-type]
        design = self.record(provenance.dataset_name(provenance.DESIGN_GRID, DESIGN_NAME), self.v1)
        with self.project.write_transaction() as conn:  # un dato sustituido ya no se exporta
            conn.execute("UPDATE gb_dataset SET status = 'superseded' WHERE uid = ?", (design.uid,))
        try:
            with self.assertRaises(design_messages.DesignError) as caught:
                export.stored_grid(self.project, design.uid)
            self.assertEqual(caught.exception.code, "des.export_not_grid")
        finally:
            with self.project.write_transaction() as conn:
                conn.execute("UPDATE gb_dataset SET status = 'current' WHERE uid = ?",
                             (design.uid,))
        self.assertEqual(export.stored_grid(self.project, design.uid).record.uid, design.uid)
        self.assertEqual(self.counts()[0:2], before[0:2])  # ni operaciones ni datos nuevos


if __name__ == "__main__":
    unittest.main()
