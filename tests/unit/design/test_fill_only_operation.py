# SPDX-License-Identifier: GPL-3.0-or-later
"""La operación ``des.fill_only`` de «Solo relleno…» (spec 014, T30; HU-014-6; RF-014-22 a
RF-014-25, RF-014-29; CE-014-07; plan 014 A12, §5.2.3, §5.3.2, §5.3.3).

- ``design.model.FillOnlyRequest``: lo que pide «Solo relleno…», como el escalonado en relleno de la
  013 (una envolvente de la versión, la superficie de partida, el perfil base y el de cada sector y
  el ancla) más la capa de láminas de agua con su campo de cota; ``design.provenance`` guarda y lee
  sus ajustes (``fill_only_settings``, ``fill_only_request``) y dice lo que consume
  (``fill_only_inputs``: la capa de láminas, con el papel ``water_layer``).
- ``design.steps.fill_only_run``: «Calcular» deja la superficie en un temporal y **nada
  registrado**; «Crear» registra ``des.fill_only`` con ``des_srf_`` (``design_surface``) y
  ``des_rpt_`` (``report``), sus ajustes, sus entradas, sus parámetros y sus cifras (las del
  escalonado de la 013 y ``des.fill_only_cut_m3``); lo escrito es el diseño de
  ``design.fronts.fill_only_steps`` con las mismas entradas, bit a bit; un diseño que movería un
  intocable se rechaza nombrándolo, sin escribir nada (RF-014-25); se recalcula y se reproduce como
  las demás de la 014.

La historia con proyecto, sobre una copia de la cantera sintética (``quarry_fixtures``, T01): en V01,
una envolvente descendente de 30° desde 274 m en la lámina de agua (datos de la prueba) y el diseño
«solo relleno» «Balsa» que la escalona en relleno con ``REST_5_35_6`` y la lámina a 270 m.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, files

fronts = import_geoblender("design.fronts")
messages = import_geoblender("design.messages")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
model = import_geoblender("design.model")
pipeline = import_geoblender("design.pipeline")
seeds_mod = import_geoblender("design.seeds")
provenance = import_geoblender("design.provenance")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
core_params = import_geoblender("core.params")
res_provenance = import_geoblender("reserves.provenance")
freeze = import_geoblender("core.versions.freeze")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
figures_mod = import_geoblender("core.provenance.figures")
project_model = import_geoblender("core.project.model")
access = import_geoblender("gis.masks.access")
geotiff_reader = import_geoblender("gis.geotiff.reader")

START = qfx.START_DATASET
REST = qfx.FINAL_PROFILE
BY_HAND = {"source": "Perfil de prueba", "source_kind": "person", "decided_by": "Samuel (IMGA)"}
ENVELOPE = "Plataforma de la balsa"
ENVELOPE_LEVEL_M, ENVELOPE_SLOPE_DEG = 274.0, 30.0
"""La envolvente que se escalona (datos de la prueba): descendente, de 30°, desde 274 m en las
celdas de la lámina de agua."""
NAME = "Balsa"
WATER = model.LayerField(qfx.WATER_LAYER, "cota")
REQUEST = model.FillOnlyRequest(NAME, ENVELOPE, START, REST.code, water=WATER)
DATASET = provenance.dataset_name("srf", NAME)
REPORT = provenance.dataset_name("rpt", NAME)
RAISED_CELLS = 420
"""Las celdas de la lámina por debajo de su cota (T29: ``Σ 15 − ⌊i/4⌋`` a mano)."""


def finish(found: Iterator[Any]) -> Any:
    """El resultado del último ``Progress`` de unos pasos."""
    last = None
    for last in found:
        pass
    return last.result


def drive(work: Iterator[Any]) -> Any:
    """Lleva unos pasos hasta el final y devuelve el último ``Progress``."""
    found = None
    for found in work:
        pass
    return found


class FillOnlyRequestTest(unittest.TestCase):
    """RF-014-22, RF-014-24, RF-014-29 sin proyecto: la petición, sus ajustes y lo que consume."""

    def test_the_request_is_a_fill_benching_with_its_water_sheets(self) -> None:
        """RF-014-22: «Solo relleno…» escalona **en relleno** (su ``DesignRequest`` de la 013 lleva
        el sentido relleno, la envolvente, el perfil base, el de cada sector y el ancla); las
        láminas son su capa con el campo de cota (RF-014-24)."""
        request = model.FillOnlyRequest(NAME, ENVELOPE, START, REST.code, {"sector_2": "p2"},
                                        "gis_dtm_anclas", WATER)
        self.assertEqual(request.design, model.DesignRequest(
            NAME, ENVELOPE, "fill", REST.code, {"sector_2": "p2"}, "gis_dtm_anclas"))
        self.assertEqual(request.sector_profiles, (("sector_2", "p2"),))
        self.assertIsNone(model.FillOnlyRequest(NAME, ENVELOPE, START, REST.code).water)

    def test_the_settings_go_and_come_back(self) -> None:
        """RF-014-29, RF-014-31: los ajustes guardan lo que vuelve a pedir el mismo diseño (sin el
        sentido, que siempre es relleno: ``FILL_ONLY_SETTINGS``) y se leen igual, con y sin
        láminas; la superficie de partida es la de un escalonado (``design_start``); unos ajustes
        sin nombre o con la capa de láminas sin campo se rechazan."""
        request = model.FillOnlyRequest(NAME, ENVELOPE, START, REST.code, {"sector_2": "p2"},
                                        "gis_dtm_anclas", WATER)
        for wanted in (request, REQUEST, model.FillOnlyRequest(NAME, ENVELOPE, START, "p1")):
            with self.subTest(request=wanted):
                settings = provenance.fill_only_settings(wanted, ["sector_1"], ["sector_2"])
                found = json.loads(json.dumps(settings))
                self.assertEqual(provenance.fill_only_request(found), wanted)
                self.assertEqual(provenance.design_start(found), START)
                self.assertNotIn("sense", found)
                self.assertEqual(provenance.settings_pending(found), ("sector_1",))
                self.assertEqual(provenance.settings_touched(found), ("sector_2",))
        self.assertEqual(provenance.fill_only_settings(REQUEST)["water"],
                         {"layer": qfx.WATER_LAYER, "field": "cota"})
        declared = {setting.key for setting in provenance.FILL_ONLY_SETTINGS}
        self.assertEqual(declared, {"base_profile", "anchor.source"})
        settings = provenance.fill_only_settings(REQUEST)
        for broken in ({**settings, "name": ""}, {**settings, "water": {"layer": "x"}},
                       {**settings, "anchor": {"source": "grid", "grid": None}}):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                provenance.fill_only_request(broken)

    def test_what_it_consumes(self) -> None:
        """RF-014-29, RF-014-31: lo que consume, en su orden: la envolvente (``envelope``), la
        superficie de partida (``surface``), la rejilla de anclas (``anchors``), la capa de
        láminas (``water_layer``), las máscaras y los sectores y las búsquedas."""
        masks = (provenance.Use("gis_msk_x", "masks_classes"),)
        request = model.FillOnlyRequest(NAME, ENVELOPE, START, REST.code,
                                        anchor_grid="gis_dtm_anclas", water=WATER)
        found = provenance.fill_only_inputs(request, masks, ("core_sector",))
        self.assertEqual([(use.item, use.role) for use in found], [
            (provenance.dataset_name("env", ENVELOPE), "envelope"), (START, "surface"),
            ("gis_dtm_anclas", "anchors"), (qfx.WATER_LAYER, provenance.WATER_LAYER_ROLE),
            ("gis_msk_x", "masks_classes"), ("core_sector", "sectors")])
        self.assertEqual(provenance.WATER_LAYER_ROLE, "water_layer")
        plain = provenance.fill_only_inputs(model.FillOnlyRequest(NAME, ENVELOPE, START, "p1"))
        self.assertEqual([use.role for use in plain], ["envelope", "surface"])


# --- La operación (con proyecto) ------------------------------------------------------------------


def recompute_function(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo: lleva los pasos hasta el final."""
    handle, work = store.recompute_run(request)
    drive(work)
    return handle


def never(request: Any) -> Any:  # nunca se llama: solo declara que se repite sola
    raise AssertionError("esta historia no recalcula ni reproduce ese tipo")


def definitions() -> tuple[Any, ...]:
    """Los tipos de la 013 y de la 014 con sus cifras, como los registra ``bl``: «solo relleno»
    con sus funciones **reales** de recálculo y de reproducción; los demás, sin reproducción (al
    reproducir se toma lo congelado: así se reproduce solo «solo relleno»)."""
    found = [provenance.operation_def(op_type, never) for op_type in provenance.REPRODUCIBLE]
    for op_type in provenance.QUARRY_VERSION_TYPES:
        if op_type == provenance.FILL_ONLY:
            found.append(provenance.operation_def(op_type, recompute_function,
                                                  design_reproduce.reproduce_fill_only))
        else:
            found.append(provenance.operation_def(op_type, never))
    return (*found, *provenance.FIGURES, *provenance.QUARRY_FIGURES)


def declare(project: Any, clock: Any, key: str, value: object) -> None:
    """Declara el parámetro ``key`` en el proyecto."""
    clock.advance(minutes=1)
    with project.write_transaction() as conn:
        core_params.ParameterStore(project).create(
            conn, key, value, kind="ADOPTADO", reason="Prueba de la 014", **BY_HAND)


def composed(design: np.ndarray) -> Any:
    """Un ``design_compute_steps`` que da como compuesta ``design`` (sustituido en la prueba)."""

    def compute(job: Any, *, budget_s: float = 0.05) -> Any:
        outcome = pipeline.DesignOutcome(design, SimpleNamespace(count=0),
                                         SimpleNamespace(fill_m3=0.0, cut_m3=0.0), (), 0.0, "")
        yield project_model.Progress("benching", 1, 1, "escalonado", result=outcome)

    return compute


class FillOnlyOperationTest(qfx.QuarryProjectCase):
    """RF-014-22 a RF-014-25 y RF-014-29 con proyecto (véase el módulo): la envolvente de la balsa
    creada en V01 una vez y el diseño «solo relleno» «Balsa» calculado, creado, recalculado y
    reproducido."""

    calculation: ClassVar[Any]
    stored: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions(design_params.DEFINITIONS)
        core_params.register_definitions(design_params.QUARRY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        cls.enterClassContext(registered(*definitions()))
        for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
            declare(cls.project, cls.clock, design_params.bench_key(REST.code, param),
                    getattr(REST, param))
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        record = cls.record_of(START)
        cls.terrain_file = Path(cls.project.root, *record.locator.split("/"))
        cls.terrain_sha = hashlib.sha256(cls.terrain_file.read_bytes()).hexdigest()
        cls.clock.advance(minutes=1)
        envelope = model.EnvelopeRequest(
            ENVELOPE, "down", model.SeedSource("fixed", zone=model.Zone("layer", qfx.WATER_LAYER),
                                               elevation_m=ENVELOPE_LEVEL_M),
            slope_deg=ENVELOPE_SLOPE_DEG)
        drive(steps.envelope_run(cls.project, envelope, version=cls.v1.uid,
                                 masks=cls.masks_v1)).result.create()
        cls.before = cls.des_state()
        cls.clock.advance(minutes=1)
        cls.calculation = drive(cls.fill_steps()).result
        cls.calculated = cls.des_state()
        cls.stored = cls.calculation.create()

    @classmethod
    def record_of(cls, name: str) -> Any:
        registry = import_geoblender("core.datasets.registry")
        with cls.project.read() as conn:
            return registry.get(conn, name, version_uid="")

    @classmethod
    def fill_steps(cls, request: Any = REQUEST, **options: Any) -> Iterator[Any]:
        options.setdefault("masks", cls.masks_v1)
        return steps.fill_only_run(cls.project, request, version=cls.v1.uid, **options)

    @classmethod
    def query_of(cls, sql: str, *values: Any) -> list[Any]:
        with cls.project.read() as conn:
            return conn.execute(sql, values).fetchall()

    @classmethod
    def des_state(cls) -> dict[str, Any]:
        """Lo que ``des`` ha dejado en el proyecto: operaciones, datos, tablas, cifras, ficheros."""
        return {
            "operations": cls.query_of("SELECT uid, op_type, status FROM gb_operation WHERE "
                                       "op_type LIKE 'des.%' ORDER BY fid"),
            "datasets": cls.query_of("SELECT name, status FROM gb_dataset WHERE name LIKE "
                                     "'des!_%' ESCAPE '!' ORDER BY name"),
            "tables": cls.query_of("SELECT name FROM sqlite_master WHERE name LIKE 'des!_%' "
                                   "ESCAPE '!' ORDER BY name"),
            "figures": cls.query_of("SELECT count(*) FROM gb_figure WHERE key LIKE 'des.%'"),
            "files": sorted(path.name for path in (cls.root / "rasters").iterdir())}

    def grid_of(self, name: str) -> np.ndarray:
        record = self.record(name, self.v1)
        return geotiff_reader.read_geotiff(self.root / record.locator).values

    def figures_of(self, uid: str) -> dict[tuple[str, str], float]:
        return {(key, scope): value for key, scope, value in self.query_of(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def default(self, key: str) -> float:
        return float(core_params.definition(key).default)

    def expected(self) -> Any:
        """El diseño de ``design.fronts.fill_only_steps`` con las mismas entradas, armado aquí: la
        envolvente de la versión, la ladera registrada, las máscaras de V01, los sectores, el perfil
        y la lámina de la capa, con los intocables por su nombre."""
        envelope = self.grid_of(provenance.dataset_name("env", ENVELOPE))
        refs, labels = seeds_mod.sector_layout(self.project, self.masks_v1)
        values = {design_params.bench_key(REST.code, param): getattr(REST, param)
                  for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor")}
        job = pipeline.DesignJob(
            model.DesignRequest(NAME, ENVELOPE, "fill", REST.code), qfx.GRID, qfx.terrain(),
            envelope, self.masks_v1, refs, labels, {},
            pipeline.bench_profiles(values, [REST.code]), None,
            self.default(design_params.VERIFY_MIN_THICKNESS),
            self.default(design_params.TOLERANCE_FACE), self.default(design_params.WARNING_RATIO))
        sheets = fronts.water_sheets(self.read_layer(qfx.WATER_LAYER), WATER, qfx.GRID)
        untouchables = fronts.untouchable_zones(self.masks_v1, {"torre": "Torre"})
        return finish(fronts.fill_only_steps(fronts.FillOnlyJob(job, sheets, untouchables)))

    # --- Calcular y crear --------------------------------------------------------------------

    def test_a_calculating_writes_nothing_and_creating_registers(self) -> None:
        """RF-014-22 a RF-014-24, RF-014-29: «Calcular» deja la superficie en su temporal y no
        registra nada; «Crear» registra ``des.fill_only`` de V01 hecha con ``des_srf_`` (papel
        ``design_surface``) y ``des_rpt_`` (``report``); lo escrito es el diseño «solo relleno»
        de ``design.fronts`` con las mismas entradas, bit a bit: no corta (CE-014-07), rellena,
        solo mueve el relleno admitido de la 012 (la torre, como el terreno), la lámina es su
        partida y el terreno registrado no cambia."""
        for key in ("operations", "datasets", "tables", "figures"):
            self.assertEqual(self.calculated[key], self.before[key], key)
        (temporary,) = sorted(set(self.calculated["files"]) - set(self.before["files"]))
        self.assertRegex(temporary, rf"^{DATASET}_v01\.tif\.tmp-[0-9a-f]+$")
        calculation = self.calculation
        self.assertEqual((calculation.op_type, calculation.name, calculation.version),
                         (provenance.FILL_ONLY, NAME, "V01"))
        self.assertEqual([spec.name for spec in calculation.specs], [DATASET, REPORT])
        uid = self.stored.handle.uid
        self.assertEqual(self.query_of("SELECT op_type, status FROM gb_operation WHERE uid = ?",
                                       uid), [(provenance.FILL_ONLY, "done")])
        roles = dict(self.query_of(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out'", uid))
        self.assertEqual(roles, {DATASET: "design_surface", REPORT: "report"})
        written, terrain = self.grid_of(DATASET), qfx.terrain()
        expected = self.expected()
        np.testing.assert_array_equal(written, expected.surface)
        np.testing.assert_array_equal(written, calculation.outcome.surface)
        self.assertEqual(float(np.maximum(terrain - written, 0.0).sum()), 0.0)
        self.assertGreater(calculation.outcome.design.report.fill_m3, 1_000.0)
        start = calculation.outcome.start
        np.testing.assert_array_equal(written[~self.masks_v1.fill_allowed()],
                                      start[~self.masks_v1.fill_allowed()])
        tower = fronts.untouchable_zones(self.masks_v1)[0].mask
        np.testing.assert_array_equal(written[tower], terrain[tower])
        self.assertEqual(calculation.outcome.water_cells, RAISED_CELLS)
        self.assertEqual(hashlib.sha256(self.terrain_file.read_bytes()).hexdigest(),
                         self.terrain_sha)

    def test_a_its_figures_are_those_of_the_013_and_its_cut(self) -> None:
        """RF-014-22, RF-014-29 (plan §5.2.3): las cifras CALCULADO son las del escalonado de la
        013 (desmonte, terraplén, área con movimiento…, con el ámbito de su nombre) y
        ``des.fill_only_cut_m3`` = 0 m³."""
        uid = self.stored.handle.uid
        scope = figures_mod.scope_json(provenance.quarry_figure_scope(NAME))
        found = self.figures_of(uid)
        expected = {(figure.key, figures_mod.scope_json(figure.scope)): figure.value
                    for figure in self.calculation.outcome.figures}
        self.assertEqual(found, expected)
        self.assertEqual(found[("des.fill_only_cut_m3", scope)], 0.0)
        self.assertEqual(found[("des.cut_m3", scope)], 0.0)
        self.assertEqual(found[("des.fill_m3", scope)],
                         self.calculation.outcome.design.report.fill_m3)
        self.assertIn(NAME, self.calculation.message)

    def test_a_what_is_registered_repeats_the_request(self) -> None:
        """RF-014-29, RF-014-31: los ajustes repiten la petición (con la capa de láminas y su campo);
        las entradas, la envolvente, la superficie de partida, la capa de láminas
        (``water_layer``), las máscaras y los sectores; los parámetros, los del escalonado de la
        013 (los cinco del perfil, las tolerancias y el espesor mínimo), ninguno de la cantera;
        la ficha de la superficie dice su superficie de partida."""
        uid = self.stored.handle.uid
        settings = json.loads(self.query_of("SELECT settings FROM gb_operation WHERE uid = ?",
                                            uid)[0][0])
        self.assertEqual(provenance.fill_only_request(settings), REQUEST)
        self.assertEqual(settings["water"], {"layer": qfx.WATER_LAYER, "field": "cota"})
        inputs = {(name, role) for name, role in self.query_of(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'", uid)}
        for item in ((provenance.dataset_name("env", ENVELOPE), "envelope"), (START, "surface"),
                     (qfx.WATER_LAYER, "water_layer")):
            self.assertIn(item, inputs)
        self.assertTrue(any(role.startswith("masks_") for _name, role in inputs), inputs)
        params = {key for (key,) in self.query_of(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", uid)}
        wanted = {design_params.bench_key(REST.code, param) for param in (
            "height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor")}
        wanted |= {design_params.TOLERANCE_FACE, design_params.WARNING_RATIO,
                   design_params.VERIFY_MIN_THICKNESS}
        self.assertTrue(wanted <= params, params)
        self.assertFalse(any(key.startswith(("des.quarry.", "des.edge.")) for key in params))
        with self.project.read() as conn:
            origin = store.design_surface_of(conn, DATASET, self.v1.uid)
            record = self.record(DATASET, self.v1)
            self.assertEqual(store.design_surface_start(conn, record.uid), START)
        self.assertEqual((origin.op_type, origin.start), (provenance.FILL_ONLY, START))

    def test_a_the_report_table(self) -> None:
        """RF-014-22, RF-014-24 (plan §5.2.3): ``des_rpt_`` lleva las filas del informe de la 013
        (frente al terreno de partida con la lámina) y, además, el corte frente al terreno
        registrado y las celdas en que la lámina es la partida."""
        report = self.calculation.outcome.design.report
        rows = {quantity: (value, unit) for quantity, value, unit, _note in self.query_of(
            f'SELECT quantity, value, unit_code, note FROM "{REPORT}_v01" ORDER BY fid')}
        self.assertEqual(rows["cut_m3"], (report.cut_m3, "m3"))
        self.assertEqual(rows["fill_m3"], (report.fill_m3, "m3"))
        self.assertEqual(rows["fill_only_cut_m3"], (0.0, "m3"))
        self.assertEqual(rows["water_cells"], (float(RAISED_CELLS), "-"))

    def test_b_a_moved_untouchable_or_a_layer_without_its_field_writes_nothing(self) -> None:
        """RF-014-25, RF-014-24: si el escalonado moviera el intocable (aquí, sustituido en la
        prueba para subir 1 m las 224 celdas de la torre: 224 m³) «Calcular» se rechaza al avanzar
        nombrándolo por su nombre de la 012, «Torre», con el volumen
        (``des.fill_only_untouchable``); una capa de láminas sin el campo de la cota, con sus
        campos (``des.quarry_layer_field``). En los dos casos no queda nada: ni operación, ni
        dato, ni temporal."""
        before = self.des_state()
        tower = fronts.untouchable_zones(self.masks_v1)[0].mask
        lifted = qfx.terrain()
        lifted[tower] += 1.0
        with mock.patch.object(fronts, "design_compute_steps", composed(lifted)):
            with self.assertRaises(messages.DesignError) as caught:
                drive(self.fill_steps(model.FillOnlyRequest("Torre", ENVELOPE, START, REST.code)))
        self.assertEqual(caught.exception.code, "des.fill_only_untouchable")
        self.assertEqual(caught.exception.values["constraint"], "Torre")
        self.assertEqual(caught.exception.values["value"], float(qfx.TOWER_ZONE_CELLS))
        self.assertEqual(self.des_state(), before)
        wrong = model.FillOnlyRequest("Sin campo", ENVELOPE, START, REST.code,
                                      water=model.LayerField(qfx.WATER_LAYER, "nivel"))
        with self.assertRaises(messages.DesignError) as caught:
            drive(self.fill_steps(wrong))
        self.assertEqual(caught.exception.code, "des.quarry_layer_field")
        self.assertEqual(self.des_state(), before)

    # --- Recalcular y reproducir -------------------------------------------------------------

    def test_c_recomputing_repeats_the_design(self) -> None:
        """RF-014-31, RF-008-26: el recálculo de ``des.fill_only`` repite el diseño con sus ajustes
        (sustituye al anterior) y da la misma superficie y las mismas cifras: nada de lo que lee ha
        cambiado."""
        old = self.stored.handle.uid
        settings = json.loads(self.query_of("SELECT settings FROM gb_operation WHERE uid = ?",
                                            old)[0][0])
        sha = self.record(DATASET, self.v1).content_sha256
        figures = self.figures_of(old)
        request = recompute_mod.RecomputeRequest(self.project, old, provenance.FILL_ONLY,
                                                 settings, (), (), version=self.v1.uid)
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(request)
        stored = drive(work).result
        self.assertEqual(stored.handle.uid, handle.uid)
        self.assertEqual(self.query_of("SELECT op_type, status, supersedes_uid FROM gb_operation "
                                       "WHERE uid = ?", handle.uid),
                         [(provenance.FILL_ONLY, "done", old)])
        self.assertEqual(self.record(DATASET, self.v1).content_sha256, sha)
        self.assertEqual(self.figures_of(handle.uid), figures)
        type(self).stored = stored

    def test_d_reproducing_the_frozen_revision_gives_the_same(self) -> None:
        """RF-009-11, RF-014-29: congelar V01 y reproducir su revisión da la superficie y el
        informe con el mismo hash y las mismas cifras, sin escribir nada en el proyecto (la
        envolvente, la ladera, la capa de láminas y las máscaras se leen de lo congelado)."""
        self.clock.advance(minutes=1)
        outcome = drive(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega")).result
        revision = str(outcome.frozen.uid)
        self.clock.advance(minutes=1)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = drive(reproduce_mod.reproduce_steps(self.project, revision)).result
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before)
        uid = self.stored.handle.uid
        mine = [check for check in report.outputs if check.operation_uid == uid]
        self.assertEqual(sorted(check.role for check in mine), ["design_surface", "report"])
        self.assertTrue(all(check.same for check in mine), mine)
        reproduced = {check.key for check in report.figures if check.operation_uid == uid}
        self.assertIn("des.fill_only_cut_m3", reproduced)
        self.assertIn("des.fill_m3", reproduced)
        self.assertTrue(all(check.same for check in report.figures if check.operation_uid == uid))
        self.assertTrue(report.matches)


if __name__ == "__main__":
    unittest.main()
