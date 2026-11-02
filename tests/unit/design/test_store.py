# SPDX-License-Identifier: GPL-3.0-or-later
"""Escribir el resultado de las envolventes y el escalonado, todo o nada (spec 013, T14; HU-013-2,
HU-013-3; RF-013-04, RF-013-17, RF-013-19, RF-013-31; plan 013 §5.3.2, D-14, D-27, R4; RF-008-17,
RF-008-18, RF-008-23, RF-008-24, RF-009-05) y recalcular y reproducir (T15; HU-013-2, HU-013-6;
RF-013-06, RF-013-17, RF-013-31; CE-013-08; RF-008-26, RF-009-11).

Calcular deja las rejillas en temporales con su hash por bandas, junto a su destino, y **no**
registra nada: ni operación, ni dato, ni cifra. Solo «Crear» (``DesignWriter.commit``) abre la
operación, reclama las rutas, pone las rejillas en su sitio, escribe las tablas y las cifras y
completa, todo en **una** transacción de escritura; cancelar o fallar en cualquier punto no deja
nada, ni operación ni dato ni temporal.

- **RF-013-04**: las máscaras de la versión se piden por el contrato de la 012 (se compilan antes
  si no están al día), se registran como entradas (la operación queda obsoleta si cambian) y no se
  usan obsoletas, ni al empezar ni al confirmar.
- **RF-013-17**: una operación de versión con un nombre único en la versión, con sus ajustes, sus
  entradas, los parámetros que lee y sus cifras CALCULADO; ni sin versión activa ni en una no
  editable.
- **RF-013-19**: un perfil sin valor o fuera de rango se rechaza antes de abrir la operación (que
  crearía una fila vacía en el proyecto).
- **RF-013-31**: la superficie de diseño lleva su papel, y se registra solo cuando la persona lo
  confirma (D-14); lo que cambió entre calcular y confirmar no se registra.
- **T15** (``VersionsStoryTest``, al final): lo obsoleto se repite con sus ajustes sin pedir
  confirmación; cambiar el ancla de un perfil solo en V01 deja obsoleta la superficie y no la
  envolvente (CE-013-08); reproducir V01.r1 da lo mismo; los sectores que tocó el dominio se
  guardan para la marca de la búsqueda pendiente (RF-013-06).
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import math
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, files

store = import_geoblender("design.store")
pipeline = import_geoblender("design.pipeline")
design_reproduce = import_geoblender("design.reproduce")
freeze = import_geoblender("core.versions.freeze")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
versions_check = import_geoblender("core.versions.check")
graph = import_geoblender("core.provenance.graph")
provenance = import_geoblender("design.provenance")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
design_params = import_geoblender("design.params")
design_report = import_geoblender("design.report")
design_berms = import_geoblender("design.berms")
design_sectors = import_geoblender("design.sectors")
operations = import_geoblender("core.provenance.operations")
registry = import_geoblender("core.datasets.registry")
core_params = import_geoblender("core.params")
stale = import_geoblender("core.provenance.stale")
versions_model = import_geoblender("core.versions.model")
versions_read = import_geoblender("core.versions.read")
access = import_geoblender("gis.masks.access")
masks_store = import_geoblender("gis.masks.store")
georef = import_geoblender("core.georef")
geotiff_reader = import_geoblender("gis.geotiff.reader")
geotiff_writer = import_geoblender("gis.geotiff.writer")
raster_mod = import_geoblender("gis.raster")
res_provenance = import_geoblender("reserves.provenance")

SURFACE = dfx.START_DATASET
PROFILE = "expl_10_60_6"
OTHER = "rest_5_35_6"
THICKNESS = "res.verify.min_thickness_m"
ENVELOPE_NAME = "Hueco inicial"
ENVELOPE_DATASET = "des_env_hueco_inicial"
DESIGN_NAME = "Diseño inicial"
PROFILE_VALUES = {"height_m": 10.0, "face_deg": 60.0, "berm_m": 6.0, "anchor_m": 125.0,
                  "mesh_factor": 1.0}
BY_HAND = {"source": "Perfil de prueba", "source_kind": "person", "decided_by": "Samuel (IMGA)"}
LATE = "2026-10-28T10:00:00Z"


def recompute(request: Any) -> Any:  # nunca se llama: solo declara que se repite sola
    raise AssertionError("las pruebas del almacén no recalculan con la función de bl")


def reproduce(request: Any) -> Iterator[Any]:  # idem
    raise AssertionError("las pruebas del almacén no reproducen")


def definitions() -> tuple[Any, ...]:
    """Los dos tipos con sus funciones y las cifras, como las registrará ``bl``."""
    return (*provenance.operation_defs(
        {t: recompute for t in provenance.REPRODUCIBLE},
        {t: reproduce for t in provenance.REPRODUCIBLE}), *provenance.FIGURES)


def drive(steps: Any) -> Any:
    """Lleva un generador hasta el final y devuelve lo que devuelve (``StopIteration.value``)."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def last(steps: Any) -> Any:
    """El último ``Progress`` de unos pasos."""
    found = None
    for found in steps:
        pass
    return found


def envelope_request(name: str = ENVELOPE_NAME, **changes: Any) -> Any:
    base: dict[str, Any] = {
        "direction": "down", "seeds": model.SeedSource("surface", surface=SURFACE,
                                                       zone=model.Zone("domain")),
        "slope_mode": "constant", "slope_deg": 35.0, "metric": "chamfer5", "mesh_factor": 1.0,
        "reach_m": None, "domain": model.WorkDomain()}
    return model.EnvelopeRequest(name=name, **{**base, **changes})


def design_request(name: str = DESIGN_NAME, **changes: Any) -> Any:
    base: dict[str, Any] = {"envelope": ENVELOPE_NAME, "sense": "cut", "base_profile": PROFILE,
                            "sector_profiles": {}, "anchor_grid": None}
    return model.DesignRequest(name=name, **{**base, **changes})


def declare_profile(project: Any, clock: Any, code: str, *, version: Any = None,
                    skip: tuple[str, ...] = (), **changes: float) -> None:
    """Declara los valores de un perfil en el proyecto o, con ``version``, en esa versión (como
    lo hará «Perfiles de banco…», T16)."""
    parameters = core_params.ParameterStore(project)
    values = {**PROFILE_VALUES, **changes}
    clock.advance(minutes=1)
    with project.write_transaction() as conn:
        for param, value in values.items():
            if param in skip:
                continue
            kind = "ADOPTADO" if param == "mesh_factor" else "HIPÓTESIS"
            parameters.create(conn, design_params.bench_key(code, param), value, kind=kind,
                              reason="Perfil de prueba", version=version, **BY_HAND)


def lowered(depth: float, *, blank_rows: int = 20) -> Any:
    """La superficie de partida del sitio bajada ``depth`` m, sin dato en las primeras filas: una
    envolvente de prueba (float64, con NaN, que se ha de guardar bit a bit)."""
    start = cfx.site_start()
    values = np.array(start.values, dtype=np.float64) - depth
    values[:blank_rows, :] = np.nan
    return raster_mod.Raster(start.grid, values, start.crs, start.vertical)


def envelope_figures(raster: Any) -> Any:
    """Las cifras de una envolvente de prueba, sacadas de su rejilla."""
    start = cfx.site_start()
    finite = np.isfinite(raster.values)
    cells = int(np.count_nonzero(finite))
    low, high = float(raster.values[finite].min()), float(raster.values[finite].max())
    cut = float(np.sum((start.values[finite] - raster.values[finite]).clip(min=0.0))
                * raster.grid.cell_area)
    return provenance.envelope_figures(cells=cells, area_m2=cells * raster.grid.cell_area,
                                       min_m=low, max_m=high, cut_m3=cut, fill_m3=0.0)


def design_pieces(pending: tuple[str, ...] = ()) -> dict[str, Any]:
    """Las cuatro salidas de un escalonado de prueba: la superficie de diseño (un corte de 2 m en
    una franja), la rejilla de bermas, la tabla de bermas y el informe real de ``report_steps``."""
    start = cfx.site_start()
    values = np.array(start.values, dtype=np.float64)
    design = values.copy()
    design[40:80, 40:100] -= 2.0
    berm_grid = np.full(values.shape, np.nan)
    berm_grid[60, 40:100] = values[60, 40:100] - 2.0
    geometry = start.grid
    allowed = np.ones(values.shape, dtype=np.bool_)
    report = last(design_report.report_steps(
        values, design, geometry, allowed, min_thickness_m=0.02, face_deg=60.0,
        face_tolerance_deg=1.0, warning_ratio=2.0, operation=DESIGN_NAME, pending=pending)
    ).result
    table = (design_berms.BermRow("sector_1", PROFILE, 648.0, 36, 144.0, 648.0, 0.0),
             design_berms.BermRow("sector_2", PROFILE, 648.0, 24, 96.0, 648.0, 1e-9))
    berms = design_berms.Berms(berm_grid, table, 60, 240.0)
    return {"srf": raster_mod.Raster(geometry, design, start.crs, start.vertical),
            "brm": raster_mod.Raster(geometry, berm_grid, start.crs, start.vertical),
            "berms": berms, "report": report}


class _StoreCase(dfx.DesignProjectCase):
    """El proyecto del diseño (una copia **por prueba**: estas pruebas escriben y marcan
    obsoleto), con lo que declara ``des`` registrado (lo hará ``bl``)."""

    @classmethod
    def setUpClass(cls) -> None:
        dfx.project_template()  # la plantilla, antes de registrar lo de la 012 (T05)
        cls.enterClassContext(cp.constraints_registered())
        core_params.register_definitions(design_params.DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        cls.enterClassContext(registered(*definitions()))

    def setUp(self) -> None:
        self.project, self.clock = self.enterContext(dfx.open_design_project("gb-st-"))
        self.root = Path(self.project.root)
        with self.project.read() as conn:
            self.v1, self.v2 = (versions_read.version(conn, uid)
                                for uid in dfx.project_template()["versions"])
        self.cached: Any = None

    # --- Lo que hay en el proyecto -----------------------------------------------------------

    def des_state(self) -> dict[str, Any]:
        """Lo que ``des`` ha dejado en el proyecto: operaciones, datos, tablas, cifras y los
        ficheros de ``rasters/`` (con sus temporales)."""
        names = sorted(path.name for path in (self.root / "rasters").iterdir())
        with self.project.read() as conn:
            return {
                "operations": conn.execute(
                    "SELECT op_type, status FROM gb_operation WHERE op_type LIKE 'des.%' "
                    "ORDER BY fid").fetchall(),
                "datasets": conn.execute("SELECT name FROM gb_dataset WHERE name LIKE 'des\\_%' "
                                         "ESCAPE '\\' ORDER BY name").fetchall(),
                "tables": conn.execute("SELECT name FROM sqlite_master WHERE name LIKE "
                                       "'des\\_%' ESCAPE '\\' ORDER BY name").fetchall(),
                "figures": conn.execute("SELECT key FROM gb_figure WHERE key LIKE 'des.%' "
                                        "ORDER BY fid").fetchall(),
                "files": names}

    def assertNothing(self, before: dict[str, Any]) -> None:  # noqa: N802
        """Que ``des`` no ha dejado nada desde ``before``: ni operación, ni dato, ni tabla, ni
        cifra, ni fichero (tampoco un temporal ni una copia apartada)."""
        self.assertEqual(self.des_state(), before)

    def declare_profile(self, code: str, *, version: Any = None, skip: tuple[str, ...] = (),
                        **changes: float) -> None:
        """Declara los valores de un perfil en el proyecto o, con ``version``, en esa versión
        (como lo hará «Perfiles de banco…», T16)."""
        declare_profile(self.project, self.clock, code, version=version, skip=skip, **changes)

    def stale_masks(self, masks: Any) -> None:
        """Deja obsoletas las máscaras ``masks`` (una causa en la caché de la 008)."""
        with self.project.write_transaction() as conn:
            conn.execute("INSERT INTO gb_stale (item_kind, item_uid, cause_kind, subject_uid, "
                         "since) VALUES ('operation', ?, 'dataset_changed', ?, ?)",
                         (masks.operation_uid, "x" * 32, LATE))

    def cached_masks(self) -> Any:
        """Las máscaras de V01, cargadas una vez por prueba (cargarlas cuesta lo que el resto de
        preparar un cálculo); quien las deja obsoletas pasa masks=None y self.cached = None."""
        if self.cached is None:
            self.cached = self.masks()
        return self.cached

    def prepare_envelope(self, request: Any | None = None, **kw: Any) -> Any:
        version = kw.pop("version", self.v1.uid)
        if "masks" not in kw and version == self.v1.uid:
            kw["masks"] = self.cached_masks()
        return store.prepare_envelope(self.project, request or envelope_request(),
                                      version=version, **kw)

    def prepare_design(self, request: Any | None = None, **kw: Any) -> Any:
        kw.setdefault("masks", self.cached_masks())
        return store.prepare_design(self.project, request or design_request(), SURFACE,
                                    version=self.v1.uid, **kw)

    def write_envelope(self, request: Any | None = None, raster: Any | None = None,
                       **kw: Any) -> Any:
        """Calcula (a temporales) y confirma una envolvente; devuelve lo guardado."""
        request = request or envelope_request()
        raster = raster or lowered(10.0)
        start = self.prepare_envelope(request, **kw)
        with store.DesignWriter(self.project, provenance.ENVELOPE, request.name,
                                version=self.v1.uid) as writer:
            drive(writer.grid_steps(provenance.ENVELOPE_GRID, raster))
            self.clock.advance(minutes=1)
            return writer.commit(start, figures=envelope_figures(raster),
                                 message="Envolvente de prueba")

    def abandon_at_the_end(self, handle: Any) -> None:
        """Deja «fallida» al terminar la prueba una operación que siga «en curso»."""
        def close() -> None:
            state = operations.operation_statuses(self.project, [handle.uid]).get(handle.uid)
            if state == operations.OperationStatus.RUNNING:
                handle.fail("Prueba")

        self.addCleanup(close)

    def record_of(self, name: str, version: Any = None) -> Any:
        return self.record(name, self.v1 if version is None else version)


class EnvelopeCommitTest(_StoreCase):
    """RF-013-17, RF-013-31, D-14, D-27: calcular no registra nada; confirmar lo registra todo."""

    def test_calculating_registers_nothing_and_confirming_registers_everything(self) -> None:
        """RF-013-17, RF-013-31, D-14, R4: tras calcular (la rejilla en su temporal, con su hash)
        no hay operación, dato, cifra ni tabla (y no se compila nada con las máscaras al día); al
        confirmar, en **una** transacción de escritura, una operación ``des.envelope`` hecha en la
        revisión abierta de V01 con sus ajustes, las entradas con sus papeles y los parámetros que
        lee, su rejilla como dato de la versión con su papel y su hash (el que da el lector de la
        008), sus seis cifras CALCULADO y ni rastro de temporal."""
        request = envelope_request()
        raster = lowered(10.0)
        before = self.des_state()
        operations_before = self.query("SELECT count(*) FROM gb_operation")
        masks = self.masks()
        start = self.prepare_envelope(request, masks=masks)
        self.assertEqual(self.des_state(), before, "preparar no escribe")
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), operations_before,
                         "con las máscaras al día no se compila nada")
        entered: list[str] = []
        original = self.project.write_transaction

        def spy() -> Any:
            entered.append("write")
            return original()

        with store.DesignWriter(self.project, provenance.ENVELOPE, request.name,
                                version=self.v1.uid) as writer:
            spec = drive(writer.grid_steps(provenance.ENVELOPE_GRID, raster))
            self.assertEqual(spec.name, ENVELOPE_DATASET)
            self.assertEqual(spec.locator, "rasters/des_env_hueco_inicial_v01.tif")
            after = self.des_state()
            self.assertEqual({key: after[key] for key in after if key != "files"},
                             {key: before[key] for key in before if key != "files"},
                             "calcular no registra operación, dato, tabla ni cifra")
            (temporary,) = set(after["files"]) - set(before["files"])
            self.assertRegex(temporary, r"^des_env_hueco_inicial_v01\.tif\.tmp-[0-9a-f]+$")
            self.clock.advance(minutes=1)
            with mock.patch.object(self.project, "write_transaction", spy):
                stored = writer.commit(start, figures=envelope_figures(raster),
                                       message="Envolvente de prueba")
        self.assertEqual(entered, ["write"], "abrir, mover, escribir y completar: una sola")
        final = self.des_state()
        self.assertEqual(final["operations"], [("des.envelope", "done")])
        self.assertEqual(final["datasets"], [(ENVELOPE_DATASET,)])
        self.assertEqual(sorted(set(final["files"]) - set(before["files"])),
                         ["des_env_hueco_inicial_v01.tif"], "sin temporal ni copia apartada")
        self.assertEqual([item.name for item in stored.records], [ENVELOPE_DATASET])
        handle = stored.handle
        self.assertIn(self.root / "rasters" / "des_env_hueco_inicial_v01.tif", handle.claims)
        self.assertEqual((handle.op_type, handle.version_uid), ("des.envelope", self.v1.uid))
        ((status, revision, settings_text),) = self.query(
            "SELECT status, revision_uid, settings FROM gb_operation WHERE uid = ?", handle.uid)
        self.assertEqual((status, revision), ("done", handle.revision_uid))
        self.assertTrue(revision)
        self.assertEqual(provenance.envelope_request(json.loads(settings_text)), request)
        self.assertEqual(json.loads(settings_text), provenance.envelope_settings(request))
        wanted = provenance.envelope_inputs(request, masks.uses(),
                                            masks_store.available_tables(self.project))
        roles = [role for (role,) in self.query(
            "SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in'",
            handle.uid)]
        self.assertEqual(sorted(roles), sorted(use.role for use in wanted))
        self.assertTrue({"surface", "sectors", "searches"} <= set(roles))
        self.assertEqual(sum(role.startswith("masks_") for role in roles), 3)
        self.assertEqual([(item.key, item.scope) for item in handle.params],
                         [(THICKNESS, "project")])
        record = self.record_of(ENVELOPE_DATASET)
        self.assertEqual((record.module, record.kind, record.reader, record.operation_uid),
                         ("des", "raster", "gis.geotiff@1", handle.uid))
        self.assertEqual(record.locator, "rasters/des_env_hueco_inicial_v01.tif")
        ((role,),) = self.query("SELECT role FROM gb_operation_io WHERE operation_uid = ? "
                                "AND direction = 'out'", handle.uid)
        self.assertEqual(role, "envelope")
        with self.project.read() as conn:
            self.assertEqual(
                registry.content_digest(conn, self.project, record).content_sha256,
                record.content_sha256, "el hash es el que da el lector de la 008")
            self.assertEqual(stale.item_causes(conn, "operation", handle.uid), frozenset())
        figures = self.query("SELECT key, unit, kind FROM gb_figure WHERE operation_uid = ? "
                             "ORDER BY fid", handle.uid)
        self.assertEqual([key for key, _unit, _kind in figures],
                         [spec.key for spec in envelope_figures(raster)])
        self.assertEqual({kind for _key, _unit, kind in figures}, {"CALCULADO"})
        written = geotiff_reader.read_geotiff(self.root / record.locator)
        self.assertTrue(np.array_equal(written.values.view(np.uint64),
                                       raster.values.view(np.uint64)),
                        "la rejilla se guarda bit a bit, también los NaN")

    def test_cancelling_midway_leaves_nothing(self) -> None:
        """Hecho cuando, RF-013-31, D-14: cerrar los pasos a mitad del hash o de la escritura
        (Esc) y cerrar la ventana sin crear no dejan nada: ni operación, ni dato, ni temporal."""
        before = self.des_state()
        raster = lowered(10.0)
        with mock.patch.object(geotiff_writer, "TILE_SIZE", 32), \
                mock.patch.object(store, "_HASH_BLOCK_CELLS", 4096):
            probe = store.DesignWriter(self.project, provenance.ENVELOPE, ENVELOPE_NAME,
                                       version=self.v1.uid)
            total = sum(1 for _ in probe.grid_steps(provenance.ENVELOPE_GRID, raster))
            probe.close()
            self.assertGreaterEqual(total, 30)
            self.assertNothing(before)
            for steps_done in (0, 1, 3, 12, total - 1):
                with self.subTest(steps=steps_done):
                    writer = store.DesignWriter(self.project, provenance.ENVELOPE, ENVELOPE_NAME,
                                                version=self.v1.uid)
                    steps = writer.grid_steps(provenance.ENVELOPE_GRID, raster)
                    for _ in range(steps_done):
                        next(steps)
                    if steps_done >= 12:
                        self.assertNotEqual(self.des_state()["files"], before["files"],
                                            "a mitad de la escritura el temporal existe")
                    steps.close()
                    writer.close(GeneratorExit())
                    self.assertNothing(before)
        writer = store.DesignWriter(self.project, provenance.ENVELOPE, ENVELOPE_NAME,
                                    version=self.v1.uid)
        drive(writer.grid_steps(provenance.ENVELOPE_GRID, raster))
        self.assertNotEqual(self.des_state()["files"], before["files"], "el temporal existe")
        self.assertEqual(self.des_state()["operations"], [])
        writer.close()
        self.assertNothing(before)
        writer.close()  # cerrar dos veces no hace nada
        with self.assertRaises(RuntimeError):
            writer.commit(self.prepare_envelope(), figures=())
        self.assertNothing(before)

    def test_a_failure_while_confirming_leaves_nothing(self) -> None:
        """RF-013-17, RF-013-31, R4: si algo falla dentro de la transacción —``complete`` (tras
        abrir la operación, mover la rejilla y escribir las tablas) o una cifra NaN, que
        ``design.provenance`` nunca arma pero la 008 rechaza—, todo se deshace: no queda
        operación, dato, tabla, cifra, rejilla en su sitio ni temporal; el proyecto sigue
        escribiendo."""
        before = self.des_state()
        raster = lowered(10.0)
        start = self.prepare_envelope()
        nan = (*envelope_figures(raster)[:-1],
               provenance.FigureSpec("des.env_fill_m3", math.nan, "m3"))
        failures = (
            ("complete", mock.patch.object(operations.OperationHandle, "complete",
                                           side_effect=RuntimeError("fallo de prueba")),
             envelope_figures(raster), RuntimeError, None),
            ("nan", contextlib.nullcontext(), nan, Exception, "core.figure_nan"))
        for label, patch, figures, expected, code in failures:
            with self.subTest(failure=label):
                with patch, self.assertRaises(expected) as caught:
                    with store.DesignWriter(self.project, provenance.ENVELOPE, ENVELOPE_NAME,
                                            version=self.v1.uid) as writer:
                        drive(writer.grid_steps(provenance.ENVELOPE_GRID, raster))
                        writer.commit(start, figures=figures)
                if code is not None:
                    self.assertEqual(getattr(caught.exception, "code", ""), code)
                self.assertNothing(before)
        again = self.write_envelope()
        self.assertEqual(again.handle.op_type, "des.envelope", "el proyecto sigue escribiendo")

    def test_a_repeated_name_is_refused_before_calculating_and_when_confirming(self) -> None:
        """RF-013-17: el nombre es único en la versión (el dato ``des_env_<nombre>`` vigente lo
        ocupa, aunque la ortografía difiera: mismo nombre en ASCII); se rechaza al empezar, sin
        escribir nada, y otra vez al confirmar si, entre calcular y crear, otra operación lo
        ocupó. Otra versión puede repetirlo, y la envolvente y el escalonado pueden llamarse
        igual (son datos de familias distintas); un nombre sin letras ni cifras no vale."""
        self.write_envelope()
        before = self.des_state()
        for name in (ENVELOPE_NAME, "HUECO  inicial", "hueco-inicial"):
            with self.subTest(name=name):
                with self.assertRaises(messages.DesignError) as caught:
                    store.DesignWriter(self.project, provenance.ENVELOPE, name,
                                       version=self.v1.uid)
                self.assertEqual(caught.exception.code, "des.operation_name_repeated")
                self.assertIn(ENVELOPE_DATASET, str(caught.exception))
                self.assertIn(name, str(caught.exception))
                with self.assertRaises(messages.DesignError) as caught:
                    self.prepare_envelope(envelope_request(name))
                self.assertEqual(caught.exception.code, "des.operation_name_repeated")
        self.assertNothing(before)
        other = self.write_envelope(envelope_request("Hueco 2"))
        self.assertEqual(other.records[0].name, "des_env_hueco_2")
        store.DesignWriter(self.project, provenance.STEPPED, ENVELOPE_NAME,
                           version=self.v1.uid).close()
        store.DesignWriter(self.project, provenance.ENVELOPE, ENVELOPE_NAME,
                           version=self.v2.uid).close()
        with self.assertRaises(Exception) as caught:
            store.DesignWriter(self.project, provenance.ENVELOPE, "¿¡!?", version=self.v1.uid)
        self.assertEqual(getattr(caught.exception, "code", ""), "gis.dataset_name_invalid")
        request = envelope_request("Hueco repetido")
        raster = lowered(10.0)
        start = self.prepare_envelope(request)
        with store.DesignWriter(self.project, provenance.ENVELOPE, request.name,
                                version=self.v1.uid) as writer:
            drive(writer.grid_steps(provenance.ENVELOPE_GRID, raster))
            self.write_envelope(request)
            before = self.des_state()
            with self.assertRaises(messages.DesignError) as caught:
                writer.commit(start, figures=envelope_figures(raster))
        self.assertEqual(caught.exception.code, "des.operation_name_repeated")
        self.assertEqual(self.des_state(), {**before, "files": [
            name for name in before["files"] if ".tmp-" not in name]})

    def test_needs_an_editable_version(self) -> None:
        """RF-013-17, RF-009-21: sin versión activa, ``core.version_required``; en una SUPERADO,
        ``core.version_not_editable``; en una que no existe, ``core.version_unknown``. Ninguna
        escribe nada."""
        before = self.des_state()
        for version, code in ((None, "core.version_required"), ("", "core.version_required"),
                              ("V99", "core.version_unknown")):
            with self.subTest(version=version):
                with self.assertRaises(versions_model.VersionError) as caught:
                    store.prepare_envelope(self.project, envelope_request(), version=version)
                self.assertEqual(caught.exception.code, code)
                with self.assertRaises(versions_model.VersionError) as caught:
                    store.DesignWriter(self.project, provenance.ENVELOPE, ENVELOPE_NAME,
                                       version=version)
                self.assertEqual(caught.exception.code, code)
        with self.project.write_transaction() as conn:
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?",
                         (self.v2.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", ("Prueba de la 013", self.v2.uid))
        for call in (lambda: store.prepare_envelope(self.project, envelope_request(),
                                                    version=self.v2.uid),
                     lambda: store.DesignWriter(self.project, provenance.ENVELOPE, ENVELOPE_NAME,
                                                version=self.v2.uid)):
            with self.assertRaises(versions_model.VersionError) as caught:
                call()
            self.assertEqual(caught.exception.code, "core.version_not_editable")
        self.assertNothing(before)

    def test_what_changed_since_calculating_is_not_recorded(self) -> None:
        """RF-013-04, RF-013-17: si la superficie de partida cambió entre calcular y crear, la
        envolvente ya no le corresponde: se rechaza (``des.input_changed``) sin registrar nada;
        calculada de nuevo, se registra."""
        request = envelope_request("Hueco cambiado")
        raster = lowered(10.0)
        start = self.prepare_envelope(request)
        shifted = cfx.site_start()
        self.write_surfaces((dfx.START_LABEL, raster_mod.Raster(
            shifted.grid, np.array(shifted.values) + 1.0, shifted.crs, shifted.vertical)))
        before = self.des_state()
        with self.assertRaises(messages.DesignError) as caught:
            with store.DesignWriter(self.project, provenance.ENVELOPE, request.name,
                                    version=self.v1.uid) as writer:
                drive(writer.grid_steps(provenance.ENVELOPE_GRID, raster))
                writer.commit(start, figures=envelope_figures(raster))
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn(SURFACE, str(caught.exception))
        self.assertNothing(before)
        with self.assertRaises(messages.DesignError) as caught:  # sin la transacción de «Crear»
            start.begin(self.project)
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertEqual(self.des_state()["operations"], [("des.envelope", "failed")])
        stored = self.write_envelope(request)
        self.assertEqual(stored.handle.op_type, "des.envelope")



class MasksTest(_StoreCase):
    """RF-013-04: las máscaras, por el contrato de la 012."""

    def test_masks_not_compiled_are_compiled_first(self) -> None:
        """RF-013-04: en V02 (sin compilar) preparar una envolvente compila las máscaras como
        operación propia (``gis.compile_constraints``) y las registra como entradas de la
        envolvente."""
        self.assertIs(access.mask_state(self.project, self.v2.uid)[0], access.MaskState.MISSING)
        self.clock.advance(minutes=1)
        start = store.prepare_envelope(self.project, envelope_request(), version=self.v2.uid)
        self.assertIs(access.mask_state(self.project, self.v2.uid)[0], access.MaskState.CURRENT)
        compiled = self.query("SELECT count(*) FROM gb_operation WHERE op_type = "
                              "'gis.compile_constraints' AND status = 'done'")[0][0]
        self.assertGreaterEqual(compiled, 2)
        used = {use.role for use in start.inputs if use.role.startswith("masks_")}
        self.assertEqual(len(used), 3)
        with store.DesignWriter(self.project, provenance.ENVELOPE, ENVELOPE_NAME,
                                version=self.v2.uid) as writer:
            raster = lowered(10.0)
            drive(writer.grid_steps(provenance.ENVELOPE_GRID, raster))
            self.clock.advance(minutes=1)
            stored = writer.commit(start, figures=envelope_figures(raster))
        inputs = {uid for (uid,) in self.query(
            "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in' "
            "AND role LIKE 'masks_%'", stored.handle.uid)}
        self.assertEqual(inputs, {use.item for use in start.inputs
                                  if use.role.startswith("masks_")})
        self.assertEqual(stored.handle.version_uid, self.v2.uid)

    def test_stale_masks_are_not_used_and_the_operation_goes_stale(self) -> None:
        """RF-013-04, RF-013-17: las máscaras son entradas de la envolvente: al cambiar una
        restricción, las máscaras quedan obsoletas y la envolvente que las usó, también; y unas
        máscaras obsoletas no se usan —ni al preparar o empezar una operación ni al confirmar un
        cálculo hecho antes (``core.constraint_masks_stale``)—, sin dejar nada (ni el temporal);
        sin pasarlas, se compilan de nuevo antes."""
        first = self.write_envelope(envelope_request("Primero"))
        with self.project.read() as conn:
            self.assertEqual(stale.item_causes(conn, "operation", first.handle.uid), frozenset())
        masks = self.masks()
        request = envelope_request("Segundo")
        start = self.prepare_envelope(request, masks=masks)
        raster = lowered(10.0)
        before = self.des_state()
        with self.assertRaises(access.MaskError) as caught:
            with store.DesignWriter(self.project, provenance.ENVELOPE, request.name,
                                    version=self.v1.uid) as writer:
                drive(writer.grid_steps(provenance.ENVELOPE_GRID, raster))
                rows = self.stored_constraints()
                self.clock.advance(minutes=1)
                cp.edit_constraints(self.project, [
                    dataclasses.replace(rows[0], name=rows[0].name + " (editada)")])
                self.assertIs(access.mask_state(self.project, self.v1.uid)[0],
                              access.MaskState.STALE)
                writer.commit(start, figures=envelope_figures(raster))
        self.assertEqual(caught.exception.code, "core.constraint_masks_stale")
        self.assertNothing(before)
        with self.project.read() as conn:
            self.assertTrue(stale.item_causes(conn, "operation", first.handle.uid),
                            "la envolvente queda obsoleta al cambiar lo que usó")
        for call in (lambda: store.begin_envelope(self.project, request, version=self.v1.uid,
                                                  masks=masks),
                     lambda: self.prepare_envelope(request, masks=masks),
                     lambda: start.begin(self.project)):
            with self.assertRaises(access.MaskError) as caught:
                call()
            self.assertEqual(caught.exception.code, "core.constraint_masks_stale")
        self.assertNothing(before)
        self.clock.advance(minutes=1)
        again = self.prepare_envelope(request, masks=None)
        self.assertIs(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.CURRENT)
        self.assertEqual(again.masks.version_uid, self.v1.uid)



class OperationStartTest(_StoreCase):
    """Lo que anota la operación al empezar: ajustes, entradas, parámetros y perfiles."""

    def test_a_started_operation_keeps_its_settings_inputs_and_parameters(self) -> None:
        """RF-013-06, RF-013-09, RF-013-13, RF-013-17: los sectores que se pasan se guardan en los
        ajustes (la marca de «búsqueda de intocables pendiente»; de ahí los lee
        ``settings_pending``); ``begin_envelope`` registra «en curso» la operación en la versión,
        con las mismas entradas y sin escribir datos; con pendiente por sectores la envolvente lee
        el talud general de los perfiles que usa (no su ancla, que puede faltar) y los taludes
        impuestos de los sectores que tienen fila, y anota de cada uno su ámbito."""
        start = self.prepare_envelope(pending_sectors=("sector_2",))
        self.assertEqual(provenance.settings_pending(start.settings), ("sector_2",))
        self.assertEqual(start.settings, provenance.envelope_settings(
            envelope_request(), ("sector_2",)))
        self.assertEqual(provenance.settings_pending(self.prepare_envelope().settings), ())
        before = self.des_state()
        handle = store.begin_envelope(self.project, envelope_request(), version=self.v1.uid)
        self.abandon_at_the_end(handle)
        self.assertEqual((handle.op_type, handle.version_uid), ("des.envelope", self.v1.uid))
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", handle.uid),
                         [("running",)])
        self.assertEqual(self.des_state()["datasets"], before["datasets"])
        self.assertEqual(len(handle.inputs), 6)
        self.declare_profile(PROFILE, skip=("anchor_m",))
        parameters = core_params.ParameterStore(self.project)
        key = design_sectors.slope_key("sector_2")
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            parameters.create(conn, key, 10.6, kind="ADOPTADO", reason="La propiedad",
                              version=self.v1.code, source="Escritura", source_kind="document",
                              decided_by="Samuel (IMGA)")
        request = envelope_request("Por sectores", slope_mode="sectors", slope_deg=None)
        start = self.prepare_envelope(request, profiles=(PROFILE,))
        self.assertEqual(start.params, (
            *(design_params.bench_key(PROFILE, param) for param in (
                "height_m", "face_deg", "berm_m", "mesh_factor")), key, THICKNESS))
        by_sectors = store.begin_envelope(self.project, request, version=self.v1.uid,
                                          profiles=(PROFILE,))
        self.abandon_at_the_end(by_sectors)
        scopes = {item.key: item.scope for item in by_sectors.params}
        self.assertEqual(scopes[key], "version")
        self.assertEqual(scopes[design_params.bench_key(PROFILE, "height_m")], "project")
        self.assertEqual(scopes[THICKNESS], "project")
        values = {item.key: json.loads(item.value_json) for item in by_sectors.params}
        self.assertEqual(values[key], 10.6)
        self.assertEqual(values[design_params.bench_key(PROFILE, "face_deg")], 60.0)

    def test_a_profile_without_values_is_refused_and_creates_nothing(self) -> None:
        """RF-013-19, RF-013-18: un perfil que no tiene un valor, o lo tiene fuera de rango (el
        90° de la cara, que ``ParamDef`` admite), se rechaza al preparar y al empezar nombrando
        el perfil, la clave y el valor, sin crear la fila vacía «sin confirmar» que abrir la
        operación habría dejado en el proyecto; el factor de malla, con su 1,0 por defecto, no
        hace falta declararlo."""
        keys = "SELECT key FROM gb_parameter WHERE key LIKE 'des.bench.%' ORDER BY key"
        self.declare_profile(PROFILE)
        before = (self.query(keys), self.des_state())
        for call in (
                lambda: store.prepare_design(self.project, design_request(base_profile="vacio"),
                                             SURFACE, version=self.v1.uid),
                lambda: store.begin_design(self.project, design_request(base_profile="vacio"),
                                           SURFACE, version=self.v1.uid),
                lambda: store.prepare_design(
                    self.project, design_request(sector_profiles={"sector_2": "vacio"}),
                    SURFACE, version=self.v1.uid),
                lambda: self.prepare_envelope(envelope_request(slope_mode="sectors",
                                                               slope_deg=None),
                                              profiles=("vacio",))):
            with self.assertRaises(messages.DesignError) as caught:
                call()
            self.assertEqual(caught.exception.code, "des.profile_value_missing")
            self.assertEqual(caught.exception.field, "des.bench.vacio.height_m")
            self.assertIn("vacio", str(caught.exception))
        by_sectors = envelope_request("Por sectores", slope_mode="sectors", slope_deg=None)
        self.declare_profile("fuerte", face_deg=90.0, skip=("anchor_m",))
        with self.assertRaises(messages.DesignError) as caught:
            self.prepare_envelope(by_sectors, profiles=("fuerte",))
        self.assertEqual(caught.exception.code, "des.profile_value_range")
        self.assertEqual(caught.exception.field, "des.bench.fuerte.face_deg")
        self.assertEqual(caught.exception.value, 90.0)
        with self.assertRaises(messages.DesignError) as caught:  # sin ancla, el escalonado no vale
            store.prepare_design(self.project, design_request(base_profile="fuerte"), SURFACE,
                                 version=self.v1.uid)
        self.assertEqual(caught.exception.code, "des.profile_value_range")
        self.declare_profile("sin_ancla", skip=("anchor_m", "mesh_factor"))
        with self.assertRaises(messages.DesignError) as caught:
            store.prepare_design(self.project, design_request(base_profile="sin_ancla"),
                                 SURFACE, version=self.v1.uid)
        self.assertEqual(caught.exception.field, "des.bench.sin_ancla.anchor_m")
        self.prepare_envelope(by_sectors, profiles=("sin_ancla",))  # la envolvente no lee el ancla
        after = (self.query(keys), self.des_state())
        self.assertEqual(after[1], before[1], "ninguna operación, dato ni fichero")
        self.assertEqual([key for (key,) in after[0] if "vacio" in key], [],
                         "ninguna fila vacía creada")
        self.assertEqual(len(after[0]) - len(before[0]), 4 + 3, "solo las que se declararon")


class DesignCommitTest(_StoreCase):
    """RF-013-31: el escalonado, con sus cuatro salidas."""

    def setUp(self) -> None:
        super().setUp()
        self.declare_profile(PROFILE)
        self.write_envelope()

    def write_design(self, pending: tuple[str, ...] = (), request: Any | None = None,
                     **kw: Any) -> tuple[Any, dict[str, Any]]:
        request = request or design_request()
        pieces = design_pieces(pending)
        start = self.prepare_design(request, pending_sectors=pending, **kw)
        with store.DesignWriter(self.project, provenance.STEPPED, request.name,
                                version=self.v1.uid) as writer:
            drive(writer.grid_steps(provenance.DESIGN_GRID, pieces["srf"]))
            drive(writer.grid_steps(provenance.BERMS_GRID, pieces["brm"]))
            drive(writer.table_steps(provenance.BERM_TABLE, store.berm_rows(pieces["berms"])))
            drive(writer.table_steps(provenance.REPORT_TABLE, store.report_rows(pieces["report"])))
            self.assertEqual([spec.name for spec in writer.specs], [
                "des_srf_diseno_inicial", "des_brm_diseno_inicial", "des_bmt_diseno_inicial",
                "des_rpt_diseno_inicial"])
            self.clock.advance(minutes=1)
            stored = writer.commit(start, figures=provenance.design_figures(
                pieces["report"], berm_count=pieces["berms"].count), message="Diseño de prueba")
        return stored, pieces

    def test_the_design_registers_its_four_outputs_with_their_roles(self) -> None:
        """RF-013-31, RF-013-17, RF-013-28, RF-013-30, RF-009-24: una operación
        ``des.stepped_design`` hecha que consume la envolvente y la superficie de partida, y
        escribe la superficie de diseño (con el papel ``design_surface`` que reconoce la
        comprobación de congelar), la rejilla de bermas, su tabla y el informe, cada uno con su
        hash verificado por el lector de la 008, y sus cifras CALCULADO (``des.cut_m3`` y
        ``des.fill_m3`` las que lee T15). Las tablas se guardan con las filas que se dieron, sin
        NaN, con los avisos en JSON. Los cinco valores del perfil base se anotan con su ámbito:
        el de la versión si la versión lo cambió (la altura), el del proyecto si no."""
        self.clock.advance(minutes=1)
        parameters = core_params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            parameters.create(conn, design_params.bench_key(PROFILE, "height_m"), 8.0,
                              kind="ADOPTADO", reason="V01 más baja", version=self.v1.code,
                              **BY_HAND)
        stored, pieces = self.write_design(pending=("Sector 2",))
        handle = stored.handle
        self.assertEqual(handle.op_type, "des.stepped_design")
        self.assertEqual(self.des_state()["operations"],
                         [("des.envelope", "done"), ("des.stepped_design", "done")])
        outputs = self.query(
            "SELECT d.name, o.role FROM gb_operation_io AS o JOIN gb_dataset AS d ON d.uid = "
            "o.item_uid WHERE o.operation_uid = ? AND o.direction = 'out' ORDER BY o.fid",
            handle.uid)
        self.assertEqual(outputs, [("des_srf_diseno_inicial", "design_surface"),
                                   ("des_brm_diseno_inicial", "berms"),
                                   ("des_bmt_diseno_inicial", "berm_table"),
                                   ("des_rpt_diseno_inicial", "report")])
        self.assertEqual(provenance.DESIGN_SURFACE_ROLE, "design_surface")
        envelope = self.record_of(ENVELOPE_DATASET)
        used = dict(self.query("SELECT role, item_uid FROM gb_operation_io WHERE "
                               "operation_uid = ? AND direction = 'in'", handle.uid))
        self.assertTrue({"envelope", "surface", "sectors", "searches"} <= set(used))
        self.assertEqual(used["envelope"], envelope.uid)
        self.assertEqual(used["surface"], self.record(SURFACE).uid)
        with self.project.read() as conn:
            for record in stored.records:
                self.assertEqual(
                    registry.content_digest(conn, self.project, record).content_sha256,
                    record.content_sha256, record.name)
                self.assertEqual(self.record_of(record.name).uid, record.uid)
            self.assertEqual(stale.item_causes(conn, "operation", handle.uid), frozenset())
        surface = geotiff_reader.read_geotiff(self.root / stored.records[0].locator)
        self.assertTrue(np.array_equal(surface.values.view(np.uint64),
                                       pieces["srf"].values.view(np.uint64)))
        figures = dict(self.query("SELECT key, value FROM gb_figure WHERE operation_uid = ?",
                                  handle.uid))
        self.assertEqual(figures["des.cut_m3"], pieces["report"].cut_m3)
        self.assertEqual(figures["des.fill_m3"], 0.0)
        self.assertEqual(figures["des.berm_count"], 2.0)
        self.assertTrue(all(math.isfinite(value) for value in figures.values()))
        self.assertEqual(self.query("SELECT DISTINCT kind FROM gb_figure WHERE "
                                    "operation_uid = ?", handle.uid), [("CALCULADO",)])
        ((text,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", handle.uid)
        self.assertEqual(provenance.design_request(json.loads(text)), design_request())
        self.assertEqual(provenance.design_start(json.loads(text)), SURFACE)
        self.assertEqual(provenance.settings_pending(json.loads(text)), ("Sector 2",))
        rows = self.query('SELECT sector, profile, level_m, cells, area_m2, anchor_m, '
                          f'anchor_diff_m FROM "{stored.records[2].locator}" ORDER BY fid')
        self.assertEqual(rows, [row.values() for row in pieces["berms"].table])
        report = self.query('SELECT quantity, value, unit_code, note FROM '
                            f'"{stored.records[3].locator}" ORDER BY fid')
        self.assertEqual(report, store.report_rows(pieces["report"]))
        quantities = [quantity for quantity, *_ in report]
        self.assertEqual(quantities[:3], ["cut_m3", "fill_m3", "cut_cells"])
        self.assertIn("slope_max_at", quantities)
        warning = next(note for quantity, _v, _u, note in report if quantity == "warning")
        self.assertEqual(json.loads(warning)["code"], "des.sector_pending_mark")
        self.assertEqual(json.loads(warning)["values"], {"sector": "Sector 2"})
        scopes = {item.key: item.scope for item in handle.params}
        self.assertEqual(scopes[design_params.bench_key(PROFILE, "height_m")], "version")
        for param in ("face_deg", "berm_m", "anchor_m", "mesh_factor"):
            self.assertEqual(scopes[design_params.bench_key(PROFILE, param)], "project")
        for key in ("des.tolerance.face_deg", "des.warning.magnitude_ratio", THICKNESS):
            self.assertEqual(scopes[key], "project")
        values = {item.key: json.loads(item.value_json) for item in handle.params}
        self.assertEqual(values[design_params.bench_key(PROFILE, "height_m")], 8.0)

    def test_nothing_is_left_by_cancelling_failing_or_missing_an_output(self) -> None:
        """Hecho cuando, RF-013-31, R4: cancelar a mitad de las cuatro salidas, cerrar la ventana
        con todo listo, fallar al confirmar (con las cuatro listas) o confirmar sin alguna de
        ellas no deja nada del escalonado: ni operación, ni dato, ni tabla, ni temporal; la
        envolvente sigue intacta. Una salida que no es de su tipo, una tabla donde va una rejilla
        y la misma salida dos veces se rechazan al pedirlas."""
        before = self.des_state()
        envelope = self.record_of(ENVELOPE_DATASET)
        pieces = design_pieces()
        start = self.prepare_design()

        def prepare(writer: Any) -> None:
            drive(writer.grid_steps(provenance.DESIGN_GRID, pieces["srf"]))
            drive(writer.grid_steps(provenance.BERMS_GRID, pieces["brm"]))
            drive(writer.table_steps(provenance.BERM_TABLE, store.berm_rows(pieces["berms"])))
            drive(writer.table_steps(provenance.REPORT_TABLE, store.report_rows(pieces["report"])))

        writer = store.DesignWriter(self.project, provenance.STEPPED, DESIGN_NAME,
                                    version=self.v1.uid)
        drive(writer.grid_steps(provenance.DESIGN_GRID, pieces["srf"]))
        drive(writer.table_steps(provenance.BERM_TABLE, store.berm_rows(pieces["berms"])))
        steps = writer.grid_steps(provenance.BERMS_GRID, pieces["brm"])
        next(steps)
        steps.close()
        writer.close(GeneratorExit())
        self.assertNothing(before)
        writer = store.DesignWriter(self.project, provenance.STEPPED, DESIGN_NAME,
                                    version=self.v1.uid)
        prepare(writer)
        self.assertNotEqual(self.des_state()["files"], before["files"])
        writer.close()
        self.assertNothing(before)
        with mock.patch.object(operations.OperationHandle, "complete",
                               side_effect=RuntimeError("fallo de prueba")):
            with self.assertRaises(RuntimeError):
                with store.DesignWriter(self.project, provenance.STEPPED, DESIGN_NAME,
                                        version=self.v1.uid) as writer:
                    prepare(writer)
                    writer.commit(start, figures=())
        self.assertNothing(before)
        self.assertEqual(self.record_of(ENVELOPE_DATASET).content_sha256,
                         envelope.content_sha256)
        with self.assertRaises(ValueError):
            with store.DesignWriter(self.project, provenance.STEPPED, DESIGN_NAME,
                                    version=self.v1.uid) as writer:
                drive(writer.grid_steps(provenance.DESIGN_GRID, pieces["srf"]))
                writer.commit(start, figures=())
        self.assertNothing(before)
        with store.DesignWriter(self.project, provenance.STEPPED, DESIGN_NAME,
                                version=self.v1.uid) as writer:
            with self.assertRaises(ValueError):
                writer.grid_steps(provenance.ENVELOPE_GRID, pieces["srf"])  # no es del escalonado
            other_crs = georef.load_catalog().horizontal(25831)
            with self.assertRaises(ValueError):  # una rejilla en otro CRS no se escribe
                writer.grid_steps(provenance.DESIGN_GRID, raster_mod.Raster(
                    pieces["srf"].grid, pieces["srf"].values, other_crs, pieces["srf"].vertical))
            with self.assertRaises(TypeError):
                writer.grid_steps(provenance.DESIGN_GRID, pieces["srf"].values)  # no es un Raster
            with self.assertRaises(ValueError):
                writer.table_steps(provenance.DESIGN_GRID, [])  # una rejilla no es una tabla
            with self.assertRaises(ValueError):
                writer.grid_steps(provenance.BERM_TABLE, pieces["brm"])  # una tabla no es rejilla
            drive(writer.table_steps(provenance.BERM_TABLE, []))
            with self.assertRaises(ValueError):
                writer.table_steps(provenance.BERM_TABLE, [])  # dos veces la misma
            with self.assertRaises(ValueError):
                writer.table_steps(provenance.REPORT_TABLE, [("solo", "tres", "columnas")])
        self.assertNothing(before)



class StartedOperationTest(_StoreCase):
    """Una operación que ya está «en curso» (el recálculo, T15): el escritor la completa o la
    deja cancelada o fallida, sin nada de lo escrito."""

    def begin(self, name: str = ENVELOPE_NAME, **kw: Any) -> Any:
        handle = store.begin_envelope(self.project, envelope_request(name), version=self.v1.uid,
                                      **kw)
        self.abandon_at_the_end(handle)
        return handle

    def test_the_writer_completes_a_started_operation_or_leaves_it_cancelled(self) -> None:
        """RF-013-17, RF-008-19: con la operación ya empezada, el escritor reclama sus rutas, pone
        la rejilla y completa en una transacción, sin abrir otra; cerrar los pasos (Esc) la deja
        «cancelada» y un fallo, «fallida», sin dato, cifra ni temporal. Errores del programa:
        confirmar con una ``OperationStart`` cuando ya hay operación (o sin ella cuando no la
        hay, o de otro nombre) y reanudar con algo que no es una operación."""
        before = self.des_state()["files"]
        handle = self.begin("Primera")
        raster = lowered(10.0)
        with store.DesignWriter.resume(self.project, handle) as writer:
            drive(writer.grid_steps(provenance.ENVELOPE_GRID, raster))
            self.assertTrue(any(".tmp-" in str(path) for path in handle.claims))
            with self.assertRaises(ValueError):
                writer.commit(self.prepare_envelope(envelope_request("Otra")), figures=())
            self.clock.advance(minutes=1)
            stored = writer.commit(figures=envelope_figures(raster))
        self.assertIs(stored.handle, handle)
        self.assertEqual(self.des_state()["operations"], [("des.envelope", "done")])
        self.assertEqual([item.name for item in stored.records], ["des_env_primera"])
        after = self.des_state()
        cancelled = self.begin("Segunda")
        writer = store.DesignWriter.resume(self.project, cancelled)
        steps = writer.grid_steps(provenance.ENVELOPE_GRID, lowered(10.0))
        next(steps)
        steps.close()
        writer.close(GeneratorExit())
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?",
                                    cancelled.uid), [("cancelled",)])
        failing = self.begin("Tercera")
        with mock.patch.object(operations.OperationHandle, "complete",
                               side_effect=RuntimeError("fallo de prueba")):
            with self.assertRaises(RuntimeError):
                with store.DesignWriter.resume(self.project, failing) as writer:
                    drive(writer.grid_steps(provenance.ENVELOPE_GRID, lowered(10.0)))
                    writer.commit(figures=())
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", failing.uid),
                         [("failed",)])
        state = self.des_state()
        self.assertEqual((state["files"], state["datasets"], state["figures"], state["tables"]),
                         (after["files"], after["datasets"], after["figures"], after["tables"]))
        self.assertEqual(sorted(set(after["files"]) - set(before)),
                         ["des_env_primera_v01.tif"])
        with store.DesignWriter(self.project, provenance.ENVELOPE, "Otro",
                                version=self.v1.uid) as other:
            drive(other.grid_steps(provenance.ENVELOPE_GRID, lowered(10.0)))
            with self.assertRaises(ValueError):
                other.commit(figures=())
            with self.assertRaises(ValueError):
                other.commit(self.prepare_envelope(envelope_request("Uno distinto")),
                             figures=())  # otro nombre
        with self.assertRaises(TypeError):
            store.DesignWriter.resume(self.project, object())  # type: ignore[arg-type]

    def test_recalculating_replaces_the_data_and_a_failure_restores_it(self) -> None:
        """RF-008-26, RF-013-17: la operación que sustituye a otra reescribe su dato vivo con el
        mismo nombre (no es un nombre repetido); si falla al confirmar, la rejilla anterior vuelve
        a su sitio, bit a bit, y la operación anterior sigue hecha y vigente."""
        first = self.write_envelope()
        record = self.record_of(ENVELOPE_DATASET)
        path = self.root / record.locator
        original = path.read_bytes()
        with self.assertRaises(messages.DesignError):
            self.begin()  # sin decir que sustituye, el nombre está ocupado
        handle = self.begin(supersedes=first.handle.uid)
        with mock.patch.object(operations.OperationHandle, "complete",
                               side_effect=RuntimeError("fallo de prueba")):
            with self.assertRaises(RuntimeError):
                with store.DesignWriter.resume(self.project, handle) as writer:
                    drive(writer.grid_steps(provenance.ENVELOPE_GRID, lowered(5.0)))
                    writer.commit(figures=())
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(sorted(p.name for p in path.parent.iterdir() if ".tmp-" in p.name), [])
        self.assertEqual(self.record_of(ENVELOPE_DATASET).content_sha256, record.content_sha256)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?",
                                    first.handle.uid), [("done",)])
        again = self.begin(supersedes=first.handle.uid)
        with store.DesignWriter.resume(self.project, again) as writer:
            drive(writer.grid_steps(provenance.ENVELOPE_GRID, lowered(5.0)))
            self.clock.advance(minutes=1)
            writer.commit(figures=envelope_figures(lowered(5.0)))
        replaced = self.record_of(ENVELOPE_DATASET)
        self.assertEqual(replaced.uid, record.uid)
        self.assertNotEqual(replaced.content_sha256, record.content_sha256)
        self.assertEqual(replaced.operation_uid, again.uid)
        with self.project.read() as conn:
            self.assertEqual(registry.content_digest(conn, self.project, replaced).content_sha256,
                             replaced.content_sha256)


class RowsTest(unittest.TestCase):
    """Las filas de las dos tablas (formato, sin NaN, avisos con su código)."""

    def test_the_berm_table_has_the_columns_of_the_berms(self) -> None:
        """RF-013-28: las columnas de ``des_bmt_`` son las de ``design.berms``, en su orden; las
        filas son las de la medición, sin cambiar nada, y una cota de anclaje que no es finita
        se guarda sin valor."""
        self.assertEqual(tuple(column.name for column in store.BERM_COLUMNS),
                         design_berms.COLUMNS)
        berms = design_pieces()["berms"]
        self.assertEqual(store.berm_rows(berms),
                         [("sector_1", PROFILE, 648.0, 36, 144.0, 648.0, 0.0),
                          ("sector_2", PROFILE, 648.0, 24, 96.0, 648.0, 1e-9)])
        self.assertEqual(store.berm_rows(design_berms.Berms(np.empty((0, 0)), (), 0, 0.0)), [])
        odd = design_berms.Berms(np.empty((0, 0)), (design_berms.BermRow(
            "", PROFILE, 1.0, 1, 4.0, math.nan, math.nan),), 1, 4.0)
        self.assertEqual(store.berm_rows(odd), [("", PROFILE, 1.0, 1, 4.0, None, None)])

    def test_the_report_rows_give_every_figure_or_a_note(self) -> None:
        """RF-013-17, RF-013-30: una fila por cifra del informe con su unidad; lo que no existe
        (sin movimiento no hay inclinación) es una fila sin valor con la nota ``no_movement``, y
        ninguna fila lleva NaN ni infinito; el lugar del máximo va en la nota, en float64 en
        texto; los avisos, con su código y sus valores."""
        report = design_pieces()["report"]
        rows = store.report_rows(report, unassigned_area_m2=1234.5)
        by_quantity = {quantity: (value, unit, note) for quantity, value, unit, note in rows
                       if quantity not in ("warning", "note")}
        self.assertEqual(by_quantity["cut_m3"][:2], (report.cut_m3, "m3"))
        self.assertEqual(by_quantity["moved_area_m2"][:2], (report.moved_area_m2, "m2"))
        self.assertEqual(by_quantity["min_thickness_m"][:2], (0.02, "m"))
        self.assertEqual(by_quantity["unassigned_area_m2"][:2], (1234.5, "m2"))
        self.assertEqual(by_quantity["slope_max_deg"][:2], (report.slope_max_deg, "deg"))
        for _quantity, value, _unit, _note in rows:
            self.assertTrue(value is None or math.isfinite(value))
        place = by_quantity["slope_max_at"]
        self.assertIsNone(place[0])
        x, y = (float(part) for part in place[2].split(";"))
        self.assertEqual((x, y), (report.slope_max_at.x, report.slope_max_at.y))
        fine = dataclasses.replace(report, slope_max_at=design_report.CellPlace(
            3, 4, 699_812.123456789, 4_399_700.987654321))
        (place,) = [note for quantity, _v, _u, note in store.report_rows(fine)
                    if quantity == "slope_max_at"]
        self.assertEqual(tuple(float(part) for part in place.split(";")),
                         (699_812.123456789, 4_399_700.987654321), "float64 en texto, sin perder")
        notes = [json.loads(note) for quantity, _v, _u, note in rows if quantity == "note"]
        self.assertEqual([item["code"] for item in notes], ["des.magnitude_no_reference"])
        self.assertEqual(notes[0]["values"], {"operation": DESIGN_NAME})
        still = dataclasses.replace(report, cut_cells=0, fill_cells=0, slope_p90_deg=None,
                                    slope_p99_deg=None, slope_max_deg=None, slope_max_at=None)
        rows = store.report_rows(still)
        by_quantity = {quantity: (value, unit, note) for quantity, value, unit, note in rows}
        for name in ("slope_p90_deg", "slope_p99_deg", "slope_max_deg"):
            self.assertEqual(by_quantity[name], (None, "deg", "no_movement"))
        self.assertNotIn("slope_max_at", by_quantity)
        self.assertNotIn("unassigned_area_m2", by_quantity)

    def test_the_report_rows_refuse_a_figure_that_is_not_finite(self) -> None:
        """RF-013-17: un valor NaN o infinito es un error del programa (``ValueError``): no se
        escribe en el informe."""
        report = design_pieces()["report"]
        for field, value in (("cut_m3", math.nan), ("moved_area_m2", math.inf),
                             ("slope_max_deg", -math.inf)):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    store.report_rows(dataclasses.replace(report, **{field: value}))


# --- Recalcular lo obsoleto y reproducir lo congelado (T15) ---------------------------------------

POOL = "Hoyo del sector 1"
POOL_DATASET = "des_env_hoyo_del_sector_1"
STEPPED = "Bancos del hoyo"
BOTTOM_M = 630.0
OTHER_PROFILE = "otro_8_50_5"
OTHER_VALUES = {"height_m": 8.0, "face_deg": 50.0, "berm_m": 5.0, "anchor_m": 125.0,
                "mesh_factor": 1.0}
SECTOR_SLOPE = "des.sector.sector_2.max_general_slope_deg"
ANCHOR_KEY = design_params.bench_key(PROFILE, "anchor_m")
NEW_ANCHOR_M = 127.0


def finish(made: Any) -> Any:
    """Lleva los pasos de un cálculo (``run_envelope``, ``run_design``) hasta el final y devuelve lo
    guardado."""
    handle, steps = made
    stored = last(steps).result
    assert stored.handle.uid == handle.uid
    return stored


def recompute_function(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo: lleva los pasos hasta el final."""
    handle, steps = store.recompute_run(request)
    drive(steps)
    return handle


def real_definitions() -> tuple[Any, ...]:
    """Los dos tipos con sus funciones **reales** de recálculo y de reproducción, y las cifras."""
    return (*provenance.operation_defs(
        {t: recompute_function for t in provenance.REPRODUCIBLE},
        dict(design_reproduce.REPRODUCE)), *provenance.FIGURES)


def pool_request(**changes: Any) -> Any:
    """Una envolvente ascendente desde una cota fija en el sector 1, con la pendiente de cada
    sector (el sector 2 impone 20°) y el perfil base y el del sector 2."""
    base: dict[str, Any] = {
        "direction": "up", "slope_mode": "sectors", "slope_deg": None,
        "seeds": model.SeedSource("fixed", elevation_m=BOTTOM_M,
                                  zone=model.Zone("sector", "sector_1")),
        "base_profile": PROFILE, "sector_profiles": {"sector_2": OTHER_PROFILE}}
    return envelope_request(POOL, **{**base, **changes})


def stepped_request(**changes: Any) -> Any:
    """El escalonado en corte del hoyo, con el otro perfil en el sector 2."""
    base: dict[str, Any] = {"envelope": POOL, "sector_profiles": {"sector_2": OTHER_PROFILE}}
    return design_request(STEPPED, **{**base, **changes})


MOUND = "Montera"
MOUND_SURFACE = "gis_dtm_montera"
MOUND_LAYER = "gis_fea_montera"
BOUND_LAYER = "gis_fea_ambito"
ANCHORS = "gis_dtm_anclas"
FILL_PROFILE = "rest_5_35_6"
FILL_VALUES = {"height_m": 5.0, "face_deg": 35.0, "berm_m": 6.0, "anchor_m": 125.0,
               "mesh_factor": 1.0}
MOUND_TOP_M = 665.0
ANCHOR_M = 127.0
FILLED = "Terraplén de la montera"


def mound_request() -> Any:
    """Una envolvente descendente exacta de 35° con alcance de 80 m desde las celdas de una capa de
    polígonos de una superficie a 665 m, con el dominio acotado a otra capa."""
    return envelope_request(
        MOUND, direction="down", slope_deg=35.0, metric="exact", reach_m=80.0,
        seeds=model.SeedSource("surface", surface=MOUND_SURFACE,
                               zone=model.Zone("layer", MOUND_LAYER)),
        domain=model.WorkDomain(layer=BOUND_LAYER))


def filled_request() -> Any:
    """El relleno de berma primero de la montera, anclado a una rejilla de anclas."""
    return design_request(FILLED, envelope=MOUND, sense="fill", base_profile=FILL_PROFILE,
                          anchor_grid=ANCHORS)


class VersionsStoryTest(dfx.DesignProjectCase):
    """CE-013-08, RF-013-06, RF-013-17, RF-013-31: una sola historia, en el orden de las pruebas,
    sobre el proyecto del diseño (una copia por clase) con lo que declara ``des`` registrado con
    sus funciones reales de recálculo y de reproducción.

    En V01 se declaran dos perfiles (``expl_10_60_6`` y ``otro_8_50_5``) y 20° de talud impuesto en
    el sector 2; se calcula un hoyo (envolvente ascendente desde 630 m en el sector 1, con la
    pendiente de cada sector) y se escalona en corte; se congela V01.r1.

    - **a**: lo registrado es lo que da el cálculo (RF-013-17, RF-013-31, RF-013-06).
    - **b**: cambiar el ancla de un perfil solo en V01 deja obsoleta la superficie de la revisión
      abierta y no la envolvente, que lee su talud pero no su ancla (CE-013-08).
    - **c**: recalcular lo obsoleto repite solo el escalonado, sin confirmar, con la nueva ancla:
      cambia; lo congelado en V01.r1 no cambia (CE-013-08).
    - **d**: reproducir V01.r1 da las mismas salidas y cifras que lo congelado, aunque lo vivo ya
      sea otro, sin escribir en el proyecto (CE-013-08, RF-009-11).
    - **e**: con la búsqueda de un sector pendiente, el resultado lleva la marca (RF-013-06) y no
      se recalcula nada, ni se registra una operación (RF-013-05)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions(design_params.DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        cls.enterClassContext(registered(*real_definitions()))
        declare_profile(cls.project, cls.clock, PROFILE)
        declare_profile(cls.project, cls.clock, OTHER_PROFILE, **OTHER_VALUES)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).create(
                conn, SECTOR_SLOPE, 20.0, kind="HIPÓTESIS", reason="Talud del sector 2",
                version=cls.v1.code, **BY_HAND)
        cls.clock.advance(minutes=1)
        cls.pool = finish(store.run_envelope(cls.project, pool_request(),
                                                 version=cls.v1.uid))
        cls.clock.advance(minutes=1)
        cls.stepped = finish(store.run_design(cls.project, stepped_request(), SURFACE,
                                                  version=cls.v1.uid))
        declare_profile(cls.project, cls.clock, FILL_PROFILE, **FILL_VALUES)
        helper = cls("test_a_what_is_registered_is_what_is_calculated")
        start = cfx.site_start()

        def flat(value: float) -> Any:
            return raster_mod.Raster(start.grid, np.full(start.values.shape, value), start.crs,
                                     start.vertical)

        helper.write_surfaces(("montera", flat(MOUND_TOP_M)), ("anclas", flat(ANCHOR_M)))
        helper.write_layer(MOUND_LAYER, [[[cfx.rectangle(40.0, 40.0, 60.0, 60.0)]]])
        helper.write_layer(BOUND_LAYER, [[[cfx.rectangle(30.0, 30.0, 100.0, 100.0)]]])
        cls.clock.advance(minutes=1)
        cls.mound = finish(store.run_envelope(cls.project, mound_request(), version=cls.v1.uid))
        cls.clock.advance(minutes=1)
        cls.filled = finish(store.run_design(cls.project, filled_request(), SURFACE,
                                             version=cls.v1.uid))
        cls.outputs_before = cls.outputs_of()
        cls.figures_before = {uid: cls.figures_of(uid) for uid in (
            cls.pool.handle.uid, cls.stepped.handle.uid, cls.mound.handle.uid,
            cls.filled.handle.uid)}
        cls.clock.advance(minutes=1)
        outcome = last(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega")).result
        cls.r1, cls.r2 = str(outcome.frozen.uid), str(outcome.opened.uid)
        cls.frozen_before = cls.frozen(cls.r1)

    # --- Ayudas -------------------------------------------------------------------------------

    @classmethod
    def query_of(cls, sql: str, *values: Any) -> list[Any]:
        with cls.project.read() as conn:
            return conn.execute(sql, values).fetchall()

    @classmethod
    def outputs_of(cls) -> dict[str, str]:
        """El hash de contenido de cada dato vivo de ``des`` de V01."""
        return {name: sha for name, sha in cls.query_of(
            "SELECT name, content_sha256 FROM gb_dataset WHERE name LIKE 'des\\_%' ESCAPE '\\' "
            "AND status IN ('current', 'stale') ORDER BY name")}

    @classmethod
    def figures_of(cls, uid: str) -> dict[str, float]:
        return {key: value for key, value in cls.query_of(
            "SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid)}

    @classmethod
    def frozen(cls, revision_uid: str) -> dict[str, Any]:
        """Lo congelado por ``revision_uid``: la fila de la revisión y cada elemento."""
        return {
            "revision": cls.query_of("SELECT state, snapshot_dir, snapshot_sha256, altered_at "
                                     "FROM gb_revision WHERE uid = ?", revision_uid),
            "items": cls.query_of("SELECT item_kind, item_uid, part, item_rev, content_sha256, "
                                  "copied, snapshot_path, snapshot_layer, file_sha256, "
                                  "file_size, state FROM gb_revision_item WHERE revision_uid = ? "
                                  "ORDER BY item_kind, item_uid", revision_uid)}

    def causes(self) -> dict[tuple[str, str], set[tuple[str, str]]]:
        """Las causas de obsolescencia de cada elemento obsoleto."""
        found: dict[tuple[str, str], set[tuple[str, str]]] = {}
        for kind, uid, cause, subject in self.query(
                "SELECT item_kind, item_uid, cause_kind, subject_uid FROM gb_stale"):
            found.setdefault((kind, uid), set()).add((cause, subject))
        return found

    def report_notes(self, name: str) -> list[str]:
        """Los códigos de los avisos y notas del informe ``des_rpt_<name>_v01``."""
        rows = self.query(f'SELECT quantity, note FROM "des_rpt_{name}_v01" ORDER BY fid')
        return [json.loads(note)["code"] for quantity, note in rows
                if quantity in ("warning", "note")]

    def settings_of(self, uid: str) -> dict[str, Any]:
        return dict(json.loads(self.query("SELECT settings FROM gb_operation WHERE uid = ?",
                                          uid)[0][0]))

    # --- La historia --------------------------------------------------------------------------

    def test_a_what_is_registered_is_what_is_calculated(self) -> None:
        """RF-013-17, RF-013-31, RF-013-06, RF-013-21: la envolvente y el escalonado de V01 son
        dos operaciones de versión hechas, con sus ajustes (los perfiles asignados y los
        sectores que tocó el dominio), sus cifras CALCULADO y la superficie de diseño con su
        papel; el hoyo baja hasta 630 m y mueve tierra; los bancos tienen bermas."""
        env_uid, des_uid = self.pool.handle.uid, self.stepped.handle.uid
        settings = self.settings_of(env_uid)
        request = provenance.envelope_request(settings)
        self.assertEqual(request, pool_request())
        self.assertEqual(request.base_profile, PROFILE)
        self.assertEqual(dict(request.sector_profiles), {"sector_2": OTHER_PROFILE})
        self.assertEqual(provenance.settings_touched(settings), ("sector_1", "sector_2"))
        self.assertEqual(provenance.settings_pending(settings), ())
        design = self.settings_of(des_uid)
        self.assertEqual(provenance.design_request(design), stepped_request())
        self.assertEqual(provenance.settings_touched(design), ("sector_1", "sector_2"))
        self.assertIsNone(provenance.settings_previous(design), "sin revisión anterior")
        figures = self.figures_before[env_uid]
        self.assertEqual(sorted(figures), sorted(
            spec.key for spec in provenance.envelope_figures(
                cells=1, area_m2=1.0, min_m=1.0, max_m=1.0, cut_m3=None, fill_m3=None)),
            "sin superficie de partida no hay desmonte ni terraplén de la envolvente")
        self.assertEqual(figures["des.env_min_m"], BOTTOM_M)
        self.assertGreater(figures["des.env_cells"], 2800, "el hoyo y sus taludes")
        figures = self.figures_before[des_uid]
        self.assertGreater(figures["des.cut_m3"], 0.0)
        self.assertEqual(figures["des.fill_m3"], 0.0)
        self.assertGreater(figures["des.berm_count"], 0)
        record = self.record(provenance.dataset_name("srf", STEPPED), self.v1)
        self.assertEqual(record.operation_uid, des_uid)
        self.assertEqual(self.query("SELECT role FROM gb_operation_io WHERE operation_uid = ? AND "
                                    "direction = 'out' AND item_uid = ?", des_uid, record.uid),
                         [("design_surface",)])
        self.assertIn("des.magnitude_no_reference", self.report_notes("bancos_del_hoyo"))
        env = geotiff_reader.read_geotiff(self.root / self.record(POOL_DATASET, self.v1).locator)
        self.assertEqual(float(np.nanmin(env.values)), BOTTOM_M)
        surface = geotiff_reader.read_geotiff(self.root / record.locator).values
        start = cfx.site_start().values
        self.assertLess(float(np.nanmin(surface)), float(start.min()))
        self.assertLessEqual(float(np.nanmax(surface)), float(start.max()))
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE status <> 'done' "
                                    "AND op_type LIKE 'des.%'"), [(0,)])

    def test_b_a_profile_changed_in_v01_stales_only_the_surface(self) -> None:
        """CE-013-08, RF-013-17: cambiar el ancla de un perfil solo en V01 deja obsoleta la
        superficie de la revisión abierta, con la causa ``parameter_changed``, y no la envolvente,
        que lee el talud general del perfil pero no su ancla; lo congelado en V01.r1 no cambia."""
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).create(
                conn, ANCHOR_KEY, NEW_ANCHOR_M, kind="HIPÓTESIS", reason="Prueba de la 013",
                version=self.v1.code, **BY_HAND)
        causes = self.causes()
        stepped = ("operation", self.stepped.handle.uid)
        self.assertEqual({cause for cause, _subject in causes[stepped]}, {"parameter_changed"})
        surface = self.record(provenance.dataset_name("srf", STEPPED), self.v1)
        self.assertIn(("dataset", surface.uid), causes)
        self.assertFalse([key for key in causes if key[1] == self.pool.handle.uid],
                         "la envolvente no usa el ancla: no queda obsoleta")
        self.assertFalse([key for key in causes if key[0] == "dataset"
                          and key[1] == self.record(POOL_DATASET, self.v1).uid])
        self.assertEqual(self.frozen(self.r1), self.frozen_before)

    def test_a_the_mound_is_filled_in_benches_anchored_to_the_grid(self) -> None:
        """CE-013-08, RF-013-01, RF-013-02, RF-013-14, RF-013-23, RF-013-24: las semillas son las
        celdas de la capa a 665 m; la envolvente descendente exacta no sale de la otra capa y se
        compara con la superficie de las semillas; el relleno de berma primero queda anclado a
        127 + 5·n (la rejilla de anclas), no a los 125 m del perfil."""
        figures = self.figures_before[self.mound.handle.uid]
        self.assertEqual(figures["des.env_max_m"], MOUND_TOP_M)
        self.assertGreater(figures["des.env_cut_m3"], 0.0, "con superficie de partida hay volumen")
        self.assertEqual(figures["des.env_fill_m3"], 0.0)
        env = geotiff_reader.read_geotiff(
            self.root / self.record("des_env_montera", self.v1).locator).values
        inside = int(np.isfinite(env).sum())
        self.assertEqual(inside, figures["des.env_cells"])
        self.assertGreater(inside, 100)
        self.assertLessEqual(inside, 35 * 35, "acotada a la capa de 70 × 70 m")
        design = geotiff_reader.read_geotiff(
            self.root / self.record("des_srf_terraplen_de_la_montera", self.v1).locator).values
        self.assertTrue((design > cfx.site_start().values).any(), "hay relleno")
        berms = self.query('SELECT level_m, anchor_m, anchor_diff_m FROM '
                           '"des_bmt_terraplen_de_la_montera_v01"')
        self.assertTrue(berms)
        for level, anchor, diff in berms:
            self.assertAlmostEqual((level - ANCHOR_M) / 5.0, round((level - ANCHOR_M) / 5.0),
                                   places=6, msg=f"berma a {level} m")
            self.assertLess(abs(diff), 1e-6)
            self.assertAlmostEqual(anchor, level - diff, places=6)

    def test_c_recomputing_repeats_only_the_surface_and_the_frozen_does_not_change(self) -> None:
        """CE-013-08, RF-013-17, RF-008-26: «Recalcular lo obsoleto» repite solo el escalonado,
        sin pedir confirmación y en la revisión abierta (r2), con los mismos ajustes y la nueva
        ancla; la envolvente, que no estaba obsoleta, no se toca; la superficie cambia; el
        desmonte se compara con el de V01.r1 (D-25); lo congelado en V01.r1 no cambia."""
        before = self.outputs_of()
        old = self.stepped.handle.uid
        with self.project.read() as conn:
            plan = recompute_mod.plan_recompute(graph.load_graph(conn))
        self.assertEqual([unit.operations for unit in plan.units], [(old,)])
        self.clock.advance(minutes=1)
        outcome = last(recompute_mod.recompute_steps(self.project)).result
        self.assertEqual([item.status for item in outcome.results], [recompute_mod.UnitStatus.DONE])
        (new,) = outcome.results[0].operations
        self.assertNotEqual(new, old)
        self.assertEqual(self.query("SELECT op_type, status, revision_uid, supersedes_uid FROM "
                                    "gb_operation WHERE uid = ?", new),
                         [(provenance.STEPPED, "done", self.r2, old)])
        now = self.outputs_of()
        surface = provenance.dataset_name("srf", STEPPED)
        self.assertEqual(now[POOL_DATASET], before[POOL_DATASET], "la envolvente no se tocó")
        self.assertNotEqual(now[surface], before[surface], "la nueva ancla mueve los bancos")
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE op_type = ? AND "
                                    "supersedes_uid IS NOT NULL", provenance.ENVELOPE), [(0,)])
        settings = self.settings_of(new)
        self.assertEqual(provenance.design_request(settings), stepped_request())
        self.assertEqual(provenance.settings_touched(settings), ("sector_1", "sector_2"))
        old_figures = self.figures_before[old]
        self.assertEqual(provenance.settings_previous(settings), {
            "operation": STEPPED, "revision": "V01.r1", "cut_m3": old_figures["des.cut_m3"],
            "fill_m3": old_figures["des.fill_m3"]})
        self.assertNotIn("des.magnitude_no_reference", self.report_notes("bancos_del_hoyo"))
        figures = self.figures_of(new)
        self.assertNotEqual(figures["des.cut_m3"], old_figures["des.cut_m3"])
        with self.project.read() as conn:
            resolved = core_params.ParameterStore(self.project).resolve(
                conn, ANCHOR_KEY, ("version", "project"), version=self.v1.code)
        self.assertEqual((resolved.scope, resolved.value), ("version", NEW_ANCHOR_M))
        self.assertEqual(self.causes(), {("operation", old): self.causes()[("operation", old)]},
                         "solo queda marcada la operación que se sustituyó")
        self.assertEqual(self.frozen(self.r1), self.frozen_before)
        findings = graph.drain(versions_check.check_steps(self.project, [self.r1], full=True))
        self.assertEqual([item.altered for item in findings], [False])

    def test_d_recomputing_an_envelope_repeats_it_and_then_what_depends_on_it(self) -> None:
        """RF-013-17, RF-013-13, RF-008-25: cambiar el talud que impone el sector 2 solo en V01
        deja obsoletas la envolvente por sectores, que lo lee, y los dos escalonados, que también
        lo leen (el de la montera no usa esa envolvente, pero sí el talud de los sectores);
        recalcular repite la envolvente (sustituye a la suya, con sus ajustes y los sectores
        que tocó), y los escalonados, el del hoyo ya sobre la envolvente nueva, que cambia."""
        old_pool = self.query("SELECT uid FROM gb_operation WHERE op_type = ? AND superseded_by "
                              "IS NULL AND settings LIKE ?", provenance.ENVELOPE,
                              f'%"name":"{POOL}"%')[0][0]
        old_hash = self.outputs_of()[POOL_DATASET]
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(
                conn, SECTOR_SLOPE, value=15.0, reason="Prueba de la 013", version=self.v1.code)
        outcome = last(recompute_mod.recompute_steps(self.project)).result
        done = [item for item in outcome.results if item.status is recompute_mod.UnitStatus.DONE]
        self.assertEqual(len(done), 3, outcome.results)
        (new_pool,) = [uid for item in done for uid in item.operations
                       if self.query("SELECT op_type FROM gb_operation WHERE uid = ?",
                                     uid)[0][0] == provenance.ENVELOPE]
        self.assertEqual(self.query("SELECT supersedes_uid, status FROM gb_operation WHERE "
                                    "uid = ?", new_pool), [(old_pool, "done")])
        settings = self.settings_of(new_pool)
        self.assertEqual(provenance.envelope_request(settings), pool_request())
        self.assertEqual(provenance.settings_touched(settings), ("sector_1", "sector_2"))
        self.assertNotEqual(self.outputs_of()[POOL_DATASET], old_hash,
                            "el sector 2 pasa de 20° a 15°: la envolvente cambia")
        new_figures = self.figures_of(new_pool)
        self.assertEqual(new_figures["des.env_min_m"], BOTTOM_M)
        self.assertNotEqual(new_figures["des.env_max_m"], self.figures_before[
            self.pool.handle.uid]["des.env_max_m"])
        self.assertEqual(self.query("SELECT count(*) FROM gb_stale WHERE item_kind = 'operation' "
                                    "AND item_uid NOT IN (SELECT uid FROM gb_operation WHERE "
                                    "superseded_by IS NOT NULL)"), [(0,)], "lo vivo está al día")

    def test_d_reproducing_a_later_revision_repeats_what_it_was_compared_with(self) -> None:
        """RF-013-30, RF-013-31, D-25 (RF-009-11): el escalonado recalculado se comparó con el de
        V01.r1 (lo anterior está en sus ajustes); reproducir la revisión que lo congela da su
        informe con ese mismo aviso de magnitud, es decir, las mismas salidas con el mismo hash y
        las mismas cifras, sin tener ya las revisiones de entonces a mano."""
        new = self.query("SELECT uid FROM gb_operation WHERE op_type = ? AND superseded_by IS NULL "
                         "AND supersedes_uid IS NOT NULL", provenance.STEPPED)[-1][0]
        self.clock.advance(minutes=1)
        outcome = last(freeze.freeze_steps(self.project, self.v1.uid,
                                           reason="Segunda entrega")).result
        report = last(reproduce_mod.reproduce_steps(self.project, str(outcome.frozen.uid))).result
        self.assertEqual(report.not_reproducible, ())
        mine = [check for check in report.outputs if check.operation_uid == new]
        self.assertEqual(sorted(check.role for check in mine),
                         ["berm_table", "berms", "design_surface", "report"])
        self.assertTrue(all(check.same for check in mine), mine)
        reproduced = {check.key: check.reproduced for check in report.figures
                      if check.operation_uid == new}
        self.assertEqual(reproduced, self.figures_of(new))
        self.assertTrue(report.matches)

    def test_d_reproducing_v01_r1_gives_the_same(self) -> None:
        """CE-013-08, RF-013-17, RF-013-31 (RF-009-11): reproducir V01.r1, ya con otra ancla viva,
        da las salidas de las dos envolventes y de los dos escalonados con el mismo hash y sus
        cifras iguales, sin escribir nada en el proyecto; el segundo par recorre los caminos que el
        primero no (semillas de una superficie en una capa de polígonos, dominio acotado a otra
        capa, alcance y distancia euclídea exacta, relleno de berma primero y rejilla de anclas):
        lo que se lee de lo congelado es lo que leyó el cálculo del proyecto."""
        self.clock.advance(minutes=1)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = last(reproduce_mod.reproduce_steps(self.project, self.r1)).result
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before)
        self.assertEqual(report.not_reproducible, ())
        pairs = ((self.pool, self.stepped), (self.mound, self.filled))
        for envelope, design in pairs:
            mine = [check for check in report.outputs
                    if check.operation_uid in (envelope.handle.uid, design.handle.uid)]
            self.assertEqual(sorted(check.role for check in mine),
                             ["berm_table", "berms", "design_surface", "envelope", "report"])
            self.assertTrue(all(check.same for check in mine), mine)
            self.assertTrue(all(check.reproduced_sha256 == check.frozen_sha256 for check in mine))
        for uid in (self.mound.handle.uid, self.filled.handle.uid):  # las cifras vigentes
            reproduced = {check.key: check.reproduced for check in report.figures
                          if check.operation_uid == uid}
            self.assertEqual(reproduced, self.figures_before[uid], uid)
        self.assertTrue(report.matches)

    def test_e_a_pending_search_marks_the_result_and_refuses_recalculating(self) -> None:
        """RF-013-06, RF-013-05: con la búsqueda de un sector que tocó el dominio pendiente, el
        resultado lleva la marca «búsqueda de intocables pendiente» con ese sector (los que tocó
        están en los ajustes); y repetir la operación se niega, nombrando el sector, sin empezar
        ni dejar nada."""
        stepped = self.query("SELECT uid FROM gb_operation WHERE op_type = ? AND "
                             "superseded_by IS NULL", provenance.STEPPED)[-1][0]
        touched = provenance.settings_touched(self.settings_of(stepped))
        sectors = design_sectors.design_sectors(self.project, self.v1.uid)
        self.assertEqual(design_sectors.pending_marks(touched, sectors), ())
        with self.project.write_transaction() as conn:
            conn.execute("DELETE FROM core_untouchable_search WHERE sector_code = 'sector_1'")
        sectors = design_sectors.design_sectors(self.project, self.v1.uid)
        marks = design_sectors.pending_marks(touched, sectors)
        self.assertEqual([mark.code for mark in marks], ["sector_1"])
        self.assertEqual(marks[0].text("es"), "Búsqueda de intocables pendiente en «Sector 1».")
        before = self.query("SELECT count(*) FROM gb_operation")
        for op_type, name in ((provenance.ENVELOPE, POOL), (provenance.STEPPED, STEPPED)):
            uid = self.query("SELECT uid FROM gb_operation WHERE op_type = ? AND superseded_by "
                             "IS NULL", op_type)[-1][0]
            request = recompute_mod.RecomputeRequest(
                self.project, uid, op_type, self.settings_of(uid), (), (), version=self.v1.uid)
            with self.subTest(name=name):
                with self.assertRaises(messages.DesignError) as caught:
                    store.recompute_run(request)
                self.assertEqual(caught.exception.code, "des.sector_pending")
                self.assertIn("Sector 1", str(caught.exception))
                self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), before)

    def snapshot(self) -> dict[str, Any]:
        """Lo que ``des`` ha dejado en el proyecto, sin las operaciones: datos, tablas, cifras y
        los ficheros de ``rasters/`` (con sus temporales)."""
        return {
            "datasets": self.query("SELECT name FROM gb_dataset WHERE name LIKE 'des!_%' "
                                   "ESCAPE '!' ORDER BY name"),
            "tables": self.query("SELECT name FROM sqlite_master WHERE name LIKE 'des!_%' "
                                 "ESCAPE '!' ORDER BY name"),
            "figures": self.query("SELECT count(*) FROM gb_figure WHERE key LIKE 'des.%'"),
            "files": sorted(path.name for path in (self.root / "rasters").iterdir())}

    def test_b_closing_the_steps_midway_or_failing_leaves_nothing(self) -> None:
        """RF-013-33, RF-008-19, R4: cerrar los pasos de una operación que ya empezó (Esc) a mitad
        de calcular o de escribir —con la rejilla ya en su temporal— o un fallo del cálculo la dejan
        «cancelada» o «fallida» y no dejan ni datos, ni tablas, ni cifras, ni ficheros (tampoco un
        temporal)."""
        before = self.snapshot()
        request = dataclasses.replace(mound_request(), name="Otra montera")
        handle, steps = store.run_envelope(self.project, request, version=self.v1.uid)
        next(steps)
        steps.close()  # a mitad de calcular
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", handle.uid),
                         [("cancelled",)])
        self.assertEqual(self.snapshot(), before)
        handle, steps = store.run_envelope(self.project, request, version=self.v1.uid,
                                           budget_s=1e-9)
        for step in steps:  # pasos de una unidad: hasta que la rejilla esté en su temporal
            if step.phase == "store" and (len(list((self.root / "rasters").iterdir()))
                                          != len(before["files"])):
                break
        self.assertNotEqual(self.snapshot()["files"], before["files"], "el temporal existe")
        steps.close()
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", handle.uid),
                         [("cancelled",)])
        self.assertEqual(self.snapshot(), before)
        handle, steps = store.run_envelope(self.project, request, version=self.v1.uid)
        with mock.patch.object(pipeline, "envelope_compute_steps",
                               side_effect=RuntimeError("fallo de prueba")):
            with self.assertRaises(RuntimeError):
                drive(steps)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", handle.uid),
                         [("failed",)])
        self.assertEqual(self.snapshot(), before)

    def test_c_recomputing_refuses_what_is_not_its_own(self) -> None:
        """RF-008-26: ``recompute_run`` repite solo operaciones de ``des``: lo que no es una
        petición de recálculo es ``TypeError``, y una operación de otro módulo o unos ajustes que
        no son los suyos, ``ValueError``, antes de empezar nada."""
        before = self.query("SELECT count(*) FROM gb_operation")
        with self.assertRaises(TypeError):
            store.recompute_run("res.volume")  # type: ignore[arg-type]
        other = recompute_mod.RecomputeRequest(self.project, "u" * 32, "res.volume", {}, (), (),
                                               version=self.v1.uid)
        with self.assertRaises(ValueError):
            store.recompute_run(other)
        broken = recompute_mod.RecomputeRequest(self.project, "u" * 32, provenance.ENVELOPE,
                                                {"name": "Sin más"}, (), (), version=self.v1.uid)
        with self.assertRaises(ValueError):
            store.recompute_run(broken)
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), before)


if __name__ == "__main__":
    unittest.main()
