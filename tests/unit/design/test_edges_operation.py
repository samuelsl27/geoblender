# SPDX-License-Identifier: GPL-3.0-or-later
"""La operación ``des.edge_transition``: la transición del borde de una superficie de diseño con el
terreno no afectado y el salto creado que deja (spec 014, T28; HU-014-5; RF-014-19 a RF-014-21,
RF-014-29; CE-014-06; plan 014 A10, A11, §5.2.3, §5.3.2).

- ``design.edges.transition_domain``: el dominio de la transición son las celdas que **mueve el
  diseño** (con dato en las dos superficies y ``|S − z|`` mayor que el espesor mínimo de la 012)
  donde las máscaras admiten mover el terreno; su anillo exterior es el terreno no afectado del
  borde del diseño, el mismo borde en que A11 mide el salto creado.
- ``design.edges.edge_transition_steps``: la transición (A10, ``transition_steps``) en ese dominio
  y el salto creado de la superficie con la transición (A11, ``created_steps``), con sus tres
  cifras (``des.transition_m3``, ``des.created_step_max_m``, ``des.created_step_share_pct``) y el
  aviso de RF-014-21 si queda dentro menos del porcentaje admitido. **CE-014-06**, segunda mitad:
  con la transición, el salto creado del borde queda ≤ 1 m.
- ``design.steps.edge_transition_run``: «Calcular» la transición de una superficie de diseño de la
  versión deja su rejilla en un temporal y **nada registrado**; «Crear» registra
  ``des.edge_transition`` con ``des_trn_`` (``design_surface``) y ``des_erp_``, sus ajustes, sus
  entradas, sus parámetros y sus cifras; una superficie que no es de diseño se rechaza
  (``des.edge_not_design_surface``) y el ángulo sin valor también (D-9), sin escribir nada; se
  recalcula y se reproduce como las demás de la 014.

La historia con proyecto, sobre una copia de la cantera sintética (``quarry_fixtures``, T01) con
una cantera de dos superficies creada en V01: la transición de su superficie final.
"""

from __future__ import annotations

import json
import math
import unittest
from collections.abc import Iterator
from typing import Any, ClassVar

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, files

edges = import_geoblender("design.edges")
messages = import_geoblender("design.messages")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
core_params = import_geoblender("core.params")
res_provenance = import_geoblender("reserves.provenance")
freeze = import_geoblender("core.versions.freeze")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
figures_mod = import_geoblender("core.provenance.figures")
access = import_geoblender("gis.masks.access")
geotiff_reader = import_geoblender("gis.geotiff.reader")

THICKNESS_M = 0.02
"""El espesor mínimo de las pruebas sin proyecto (el de la 012 es un dato de entrada)."""
ANGLE_DEG = 35.0
"""El ángulo de transición de las pruebas (D-9: lo declara una persona; el del análisis)."""
THRESHOLD_M, SHARE_PCT = 1.0, 99.0
"""El salto y el porcentaje admitidos por defecto (D-6)."""
TAN = math.tan(math.radians(ANGLE_DEG))

A_BOX = (100.0, 260.0, 200.0, 300.0)
"""La corta de 4 m al pie del escarpe previo (local: izquierda, abajo, derecha, arriba; T27)."""
B_BOX = (200.0, 296.0, 300.0, 300.0)
"""La regularización de 0,5 m a lo largo del escarpe previo (T27)."""
C_BOX = (250.0, 150.0, 260.0, 160.0)
"""El relleno de 2 m, lejos del escarpe (T27)."""


def finish(found: Iterator[Any]) -> Any:
    """El resultado del último ``Progress`` de unos pasos."""
    last = None
    for last in found:
        pass
    return last.result


def scarp_design() -> tuple[np.ndarray, np.ndarray]:
    """La ladera de la cantera y el diseño de CE-014-06 de la T27: la corta de 4 m al pie del
    escarpe previo de 3 m, la regularización de 0,5 m a lo largo de él y el relleno de 2 m."""
    start = qfx.terrain()
    surface = start.copy()
    for box, change in ((A_BOX, -4.0), (B_BOX, -0.5), (C_BOX, 2.0)):
        surface[qfx.in_box(box)] += change
    return start, surface


def border_pairs(domain: np.ndarray, valid: np.ndarray) -> list[tuple[tuple[int, int],
                                                                      tuple[int, int]]]:
    """Las parejas de vecinas (4 vecinos) con una celda en ``domain`` y la otra fuera, con dato
    en las dos: el borde del dominio con su anillo."""
    found = []
    for d_row, d_col in ((0, 1), (1, 0)):
        one = domain[:domain.shape[0] - d_row, :domain.shape[1] - d_col]
        two = domain[d_row:, d_col:]
        good = valid[:valid.shape[0] - d_row, :valid.shape[1] - d_col] & valid[d_row:, d_col:]
        rows, cols = np.nonzero((one != two) & good)
        found += [((int(r), int(c)), (int(r) + d_row, int(c) + d_col))
                  for r, c in zip(rows, cols, strict=True)]
    return found


class EdgeTransitionDomainTest(unittest.TestCase):
    """RF-014-19 a RF-014-21 y CE-014-06 sin proyecto, en la ladera de la cantera."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.start, cls.surface = scarp_design()
        cls.allowed = qfx.in_box(qfx.LEGAL_LOCAL)
        cls.before = (cls.start.copy(), cls.surface.copy(), cls.allowed.copy())
        cls.outcome = finish(edges.edge_transition_steps(
            cls.surface, cls.start, qfx.GRID, angle_deg=ANGLE_DEG, min_thickness_m=THICKNESS_M,
            threshold_m=THRESHOLD_M, share_pct=SHARE_PCT, allowed=cls.allowed, name="Borde"))

    def test_the_domain_is_what_the_design_moves(self) -> None:
        """RF-014-19, A10, A11: el dominio de la transición son las celdas que mueve el diseño
        (más que el espesor mínimo, con dato en las dos superficies) donde las máscaras admiten
        mover el terreno: aquí, las de la corta, la regularización y el relleno, ni una más; una
        celda movida fuera de lo admitido, o sin dato, no es del dominio."""
        expected = qfx.in_box(A_BOX) | qfx.in_box(B_BOX) | qfx.in_box(C_BOX)
        found = edges.transition_domain(self.surface, self.start, THICKNESS_M, self.allowed)
        self.assertEqual(found.dtype, np.bool_)
        np.testing.assert_array_equal(found, expected)
        np.testing.assert_array_equal(self.outcome.domain, expected)
        allowed = self.allowed & ~qfx.in_box(C_BOX)
        np.testing.assert_array_equal(
            edges.transition_domain(self.surface, self.start, THICKNESS_M, allowed),
            expected & ~qfx.in_box(C_BOX))
        hollow = self.surface.copy()
        hollow[qfx.in_box(C_BOX)] = np.nan
        np.testing.assert_array_equal(
            edges.transition_domain(hollow, self.start, THICKNESS_M, self.allowed),
            expected & ~qfx.in_box(C_BOX))
        thick = edges.transition_domain(self.surface, self.start, 0.5, None)
        np.testing.assert_array_equal(thick, qfx.in_box(A_BOX) | qfx.in_box(C_BOX))

    def test_the_transition_is_a10_on_that_domain(self) -> None:
        """RF-014-19, A10: la superficie con la transición es la de ``transition_steps`` en ese
        dominio, con su volumen; fuera de él, la superficie de diseño bit a bit; ninguna entrada
        se modifica."""
        domain = self.outcome.domain
        expected = finish(edges.transition_steps(self.surface, self.start, domain, qfx.GRID,
                                                 ANGLE_DEG))
        np.testing.assert_array_equal(self.outcome.grid, expected.grid)
        self.assertEqual(self.outcome.transition.volume_m3, expected.volume_m3)
        self.assertGreater(self.outcome.transition.volume_m3, 0.0)
        np.testing.assert_array_equal(self.outcome.grid[~domain], self.surface[~domain])
        for current, before in zip((self.start, self.surface, self.allowed), self.before,
                                   strict=True):
            np.testing.assert_array_equal(current, before)

    def test_ce_014_06_with_the_transition_the_created_step_is_within(self) -> None:
        """CE-014-06 (errores 42 y 48), RF-014-20, RF-014-21: sin la transición, el escalón creado
        de 4 m pasa del salto admitido en 316 de las 520 parejas del borde (T27); con la
        transición a 35°, el salto creado de la superficie nueva es ≤ 1 m en todas las parejas del
        borde, no se avisa y su porcentaje dentro es el 100 %. En cada pareja del borde del
        dominio con su anillo (el terreno no afectado), el salto creado no pasa del de la
        transición (``tan θ`` por el paso más el espesor mínimo), también en la esquina del
        escarpe previo, donde la pendiente del propio terreno pasa de 35°."""
        before = finish(edges.created_steps(self.surface, self.start, self.outcome.domain,
                                            qfx.GRID, THICKNESS_M, THRESHOLD_M, SHARE_PCT))
        self.assertEqual((before.pairs, before.over, before.maximum_m), (520, 316, 4.0))
        report = self.outcome.report
        self.assertGreater(report.pairs, 0)
        self.assertEqual(report.over, 0)
        self.assertLessEqual(report.maximum_m, 1.0)
        self.assertFalse(report.warned)
        self.assertEqual(self.outcome.notices, ())
        self.assertEqual(report.within_pct, 100.0)
        expected = finish(edges.created_steps(self.outcome.grid, self.start, self.outcome.domain,
                                              qfx.GRID, THICKNESS_M, THRESHOLD_M, SHARE_PCT))
        self.assertEqual((report.pairs, report.over, report.maximum_m),
                         (expected.pairs, expected.over, expected.maximum_m))
        grid, start = self.outcome.grid, self.start
        valid = np.isfinite(grid) & np.isfinite(start)
        pairs = border_pairs(self.outcome.domain, valid)
        self.assertEqual(len(pairs), 520)
        for one, two in pairs:
            created = abs(grid[one] - grid[two]) - abs(start[one] - start[two])
            self.assertLessEqual(created, TAN * qfx.STEP_M + THICKNESS_M + 1e-9, (one, two))

    def test_the_three_figures_and_the_message(self) -> None:
        """RF-014-19 a RF-014-21 (plan §5.2.3): las cifras CALCULADO de la transición, con el
        ámbito de su nombre: su volumen (m³), el mayor salto creado (m) y el porcentaje de las
        parejas dentro del salto admitido (%); el mensaje dice el nombre y el volumen."""
        found = {figure.key: figure for figure in self.outcome.figures}
        self.assertEqual(list(found), ["des.transition_m3", "des.created_step_max_m",
                                       "des.created_step_share_pct"])
        self.assertEqual([found[key].unit for key in found], ["m3", "m", "%"])
        for figure in found.values():
            self.assertEqual(dict(figure.scope), {"name": "borde"})
        self.assertEqual(found["des.transition_m3"].value, self.outcome.transition.volume_m3)
        self.assertEqual(found["des.created_step_max_m"].value,
                         max(0.0, self.outcome.report.maximum_m))
        self.assertEqual(found["des.created_step_share_pct"].value, 100.0)
        self.assertIn("Borde", self.outcome.message)

    def test_a_negative_created_step_is_recorded_as_zero(self) -> None:
        """RF-014-20 (la cifra no admite negativos): si el diseño solo reduce los saltos que ya
        tenía el terreno, el mayor salto creado es negativo y la cifra lo registra como 0 m (el
        informe lleva el valor con su signo); sin parejas, 0 m y el 100 % dentro."""
        transition = edges.Transition(np.zeros((2, 2)), 12.5, 3, ANGLE_DEG, 1.0)
        report = edges.EdgeReport(4, 0, -0.75, 1.0, 2.0, (), 1.0, 99.0, THICKNESS_M)
        found = {figure.key: figure.value
                 for figure in edges.edge_transition_figures("Borde", transition, report)}
        self.assertEqual(found, {"des.transition_m3": 12.5, "des.created_step_max_m": 0.0,
                                 "des.created_step_share_pct": 100.0})
        empty = edges.EdgeReport(0, 0, 0.0, None, None, (), 1.0, 99.0, THICKNESS_M)
        found = {figure.key: figure.value
                 for figure in edges.edge_transition_figures("Borde", transition, empty)}
        self.assertEqual((found["des.created_step_max_m"], found["des.created_step_share_pct"]),
                         (0.0, 100.0))

    def test_a_steep_angle_leaves_the_step_and_warns(self) -> None:
        """RF-014-21 (D-6), RF-014-19: con un ángulo de transición de 89° la transición casi no
        cambia nada y el escalón creado de 4 m sigue: se avisa con el porcentaje, el máximo, su
        lugar y una nota por tramo (los dos de la T27), en los dos idiomas."""
        outcome = finish(edges.edge_transition_steps(
            self.surface, self.start, qfx.GRID, angle_deg=89.0, min_thickness_m=THICKNESS_M,
            threshold_m=THRESHOLD_M, share_pct=SHARE_PCT, allowed=self.allowed, name="Borde"))
        report = outcome.report
        self.assertEqual((report.pairs, report.over, report.maximum_m), (520, 316, 4.0))
        self.assertTrue(report.warned)
        codes = [notice.code for notice in outcome.notices]
        self.assertEqual(codes, ["des.edge_created_step", "des.edge_stretch", "des.edge_stretch"])
        self.assertEqual([notice.severity for notice in outcome.notices],
                         ["warning", "note", "note"])
        first = outcome.notices[0]
        self.assertEqual(first.values["pairs"], 520)
        self.assertEqual(first.values["stretches"], 2)
        self.assertEqual(first.values["maximum"], 4.0)
        self.assertIn("parejas del borde", first.text("es"))
        self.assertIn("pairs of the edge", first.text("en"))
        self.assertIn("Tramo 1", outcome.notices[1].text("es"))

    def test_the_steps_and_their_refusals(self) -> None:
        """RF-014-19, RF-014-21, D-9: por pasos, con la transición y el salto creado; cerrar a
        mitad no deja nada; el ángulo de transición sin valor se rechaza al llamar
        (``des.quarry_param_missing``), y el ángulo, el salto y el porcentaje fuera de su rango
        (``des.quarry_param_range``)."""
        def run(**options: Any) -> Iterator[Any]:
            values = {"angle_deg": ANGLE_DEG, "min_thickness_m": THICKNESS_M,
                      "threshold_m": THRESHOLD_M, "share_pct": SHARE_PCT, "name": "Borde",
                      **options}
            return edges.edge_transition_steps(self.surface, self.start, qfx.GRID,
                                               allowed=self.allowed, **values)

        found = list(run(budget_s=0.0))
        phases = {step.phase for step in found}
        self.assertTrue({"transition", "created_step"} <= phases, phases)
        self.assertIsInstance(found[-1].result, edges.EdgeTransition)
        running = run(budget_s=0.0)
        next(running)
        running.close()
        for options, code in (({"angle_deg": None}, "des.quarry_param_missing"),
                              ({"angle_deg": 90.0}, "des.quarry_param_range"),
                              ({"threshold_m": 0.0}, "des.quarry_param_range"),
                              ({"share_pct": 101.0}, "des.quarry_param_range")):
            with self.subTest(options=options):
                with self.assertRaises(messages.DesignError) as caught:
                    run(**options)
                self.assertEqual(caught.exception.code, code)
        with self.assertRaises(ValueError):
            edges.edge_transition_steps(self.surface, np.zeros((3, 3)), qfx.GRID,
                                        angle_deg=ANGLE_DEG, min_thickness_m=THICKNESS_M,
                                        threshold_m=THRESHOLD_M, share_pct=SHARE_PCT,
                                        name="Borde")


# --- La operación (con proyecto) ------------------------------------------------------------------

START = qfx.START_DATASET
EXPL, REST = qfx.EXPLOITATION_PROFILE, qfx.FINAL_PROFILE
BY_HAND = {"source": "Perfil de prueba", "source_kind": "person", "decided_by": "Samuel (IMGA)"}
QUARRY_NAME = "Cantera E7"
NAME = "Transición E7"
SURFACE = provenance.dataset_name("fin", QUARRY_NAME)
DATASET = provenance.dataset_name("trn", NAME)
REPORT = provenance.dataset_name("erp", NAME)


def drive(work: Iterator[Any]) -> Any:
    """Lleva unos pasos hasta el final y devuelve el último ``Progress``."""
    found = None
    for found in work:
        pass
    return found


def recompute_function(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo: lleva los pasos hasta el final."""
    handle, work = store.recompute_run(request)
    drive(work)
    return handle


def never(request: Any) -> Any:  # nunca se llama: solo declara que se repite sola
    raise AssertionError("esta historia no recalcula ni reproduce ese tipo")


def definitions() -> tuple[Any, ...]:
    """Los tipos de la 013 y de la 014 con sus cifras, como los registra ``bl``: la transición con
    sus funciones **reales** de recálculo y de reproducción; la cantera, sin reproducción (al
    reproducir se toma lo congelado: así se reproduce solo la transición)."""
    found = [*provenance.operation_defs({t: never for t in provenance.REPRODUCIBLE},
                                        {t: never for t in provenance.REPRODUCIBLE})]
    for op_type in provenance.QUARRY_VERSION_TYPES:
        if op_type == provenance.EDGE_TRANSITION:
            found.append(provenance.operation_def(op_type, recompute_function,
                                                  design_reproduce.reproduce_edge_transition))
        else:
            found.append(provenance.operation_def(op_type, never))
    return (*found, *provenance.FIGURES, *provenance.QUARRY_FIGURES)


def declare(project: Any, clock: Any, key: str, value: object) -> None:
    """Declara el parámetro ``key`` en el proyecto."""
    clock.advance(minutes=1)
    with project.write_transaction() as conn:
        core_params.ParameterStore(project).create(
            conn, key, value, kind="ADOPTADO", reason="Prueba de la 014", **BY_HAND)


class EdgeTransitionOperationTest(qfx.QuarryProjectCase):
    """RF-014-19 a RF-014-21 y RF-014-29 con proyecto (véase el módulo): la cantera «Cantera E7» de
    V01 creada una vez; antes de declarar el ángulo de transición, su rechazo; después, la
    transición de su superficie final calculada, creada, recalculada y reproducida."""

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
        for profile in (EXPL, REST):
            for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
                declare(cls.project, cls.clock, design_params.bench_key(profile.code, param),
                        getattr(profile, param))
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        cls.clock.advance(minutes=1)
        request = model.QuarryRequest(name=QUARRY_NAME, start=START,
                                      final=model.QuarrySide(REST.code),
                                      exploitation=model.QuarrySide(EXPL.code))
        drive(steps.quarry_run(cls.project, request, version=cls.v1.uid,
                               masks=cls.masks_v1)).result.create()
        cls.before = cls.des_state()
        try:
            drive(cls.transition_steps())
        except messages.DesignError as error:
            cls.missing = error
        cls.missing_state = cls.des_state()
        declare(cls.project, cls.clock, design_params.EDGE_TRANSITION, ANGLE_DEG)
        cls.clock.advance(minutes=1)
        cls.calculation = drive(cls.transition_steps()).result
        cls.calculated = cls.des_state()
        cls.stored = cls.calculation.create()

    @classmethod
    def transition_steps(cls, name: str = NAME, surface: str = SURFACE, **options: Any
                         ) -> Iterator[Any]:
        options.setdefault("masks", cls.masks_v1)
        return steps.edge_transition_run(cls.project, name, surface, START, version=cls.v1.uid,
                                         **options)

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

    def thickness(self) -> float:
        return float(core_params.definition(design_params.VERIFY_MIN_THICKNESS).default)

    # --- Calcular y crear --------------------------------------------------------------------

    def test_a_the_angle_without_value_is_refused_before_writing(self) -> None:
        """RF-014-19, D-9: sin el ángulo de transición declarado (no tiene valor por defecto), la
        transición se rechaza al avanzar con ``des.quarry_param_missing`` y no se escribe nada."""
        self.assertEqual(self.missing.code, "des.quarry_param_missing")
        self.assertIn(design_params.EDGE_TRANSITION, self.missing.text)
        self.assertEqual(self.missing_state, self.before)

    def test_a_calculating_writes_nothing_and_creating_registers(self) -> None:
        """RF-014-19, RF-014-29: «Calcular» deja la rejilla de la transición en su temporal y no
        registra nada; «Crear» registra ``des.edge_transition`` de V01 hecha con ``des_trn_``
        (papel ``design_surface``) y ``des_erp_`` (``edge_report``) y sus tres cifras CALCULADO;
        lo escrito es la transición de A10 en las celdas que mueve la superficie final donde las
        máscaras admiten mover el terreno, y fuera de ellas, la superficie final bit a bit."""
        for key in ("operations", "datasets", "tables", "figures"):
            self.assertEqual(self.calculated[key], self.before[key], key)
        (temporary,) = sorted(set(self.calculated["files"]) - set(self.before["files"]))
        self.assertRegex(temporary, rf"^{DATASET}_v01\.tif\.tmp-[0-9a-f]+$")
        calculation = self.calculation
        self.assertEqual((calculation.op_type, calculation.name, calculation.version),
                         (provenance.EDGE_TRANSITION, NAME, "V01"))
        self.assertEqual([spec.name for spec in calculation.specs], [DATASET, REPORT])
        uid = self.stored.handle.uid
        self.assertEqual(self.query_of("SELECT op_type, status FROM gb_operation WHERE uid = ?",
                                       uid), [(provenance.EDGE_TRANSITION, "done")])
        roles = dict(self.query_of(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out'", uid))
        self.assertEqual(roles, {DATASET: "design_surface", REPORT: "edge_report"})
        final, start = self.grid_of(SURFACE), qfx.terrain()
        allowed = self.masks_v1.cut_allowed() | self.masks_v1.fill_allowed()
        with np.errstate(invalid="ignore"):
            domain = (allowed & np.isfinite(final) & np.isfinite(start)
                      & (np.abs(final - start) > self.thickness()))
        self.assertTrue(domain.any(), "la cantera excava")
        expected = finish(edges.transition_steps(final, start, domain, qfx.GRID, ANGLE_DEG))
        written = self.grid_of(DATASET)
        np.testing.assert_array_equal(written, expected.grid)
        np.testing.assert_array_equal(written, calculation.outcome.grid)
        np.testing.assert_array_equal(written[~domain], final[~domain])
        report = finish(edges.created_steps(written, start, domain, qfx.GRID, self.thickness(),
                                            THRESHOLD_M, SHARE_PCT))
        scope = figures_mod.scope_json(provenance.quarry_figure_scope(NAME))
        self.assertEqual(self.figures_of(uid), {
            ("des.transition_m3", scope): expected.volume_m3,
            ("des.created_step_max_m", scope): max(0.0, report.maximum_m),
            ("des.created_step_share_pct", scope): report.within_pct})
        self.assertGreater(expected.volume_m3, 0.0)
        self.assertIn(NAME, calculation.message)

    def test_a_what_is_registered_repeats_the_request(self) -> None:
        """RF-014-29, RF-014-31: los ajustes son el nombre, la superficie de diseño y la de
        partida; las entradas, la superficie de diseño (``design_surface``), la de partida
        (``surface``) y las máscaras; los parámetros, el ángulo de transición, el salto y el
        porcentaje admitidos y el espesor mínimo."""
        uid = self.stored.handle.uid
        settings = json.loads(self.query_of("SELECT settings FROM gb_operation WHERE uid = ?",
                                            uid)[0][0])
        self.assertEqual(settings, provenance.transition_settings(NAME, SURFACE, START))
        self.assertEqual(provenance.transition_start(settings), (NAME, SURFACE, START))
        inputs = {(name, role) for name, role in self.query_of(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'", uid)}
        self.assertIn((SURFACE, "design_surface"), inputs)
        self.assertIn((START, "surface"), inputs)
        self.assertTrue(any(role.startswith("masks_") for _name, role in inputs), inputs)
        params = {key for (key,) in self.query_of(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", uid)}
        self.assertEqual(params, {design_params.EDGE_TRANSITION, design_params.EDGE_MAX_STEP,
                                  design_params.EDGE_MIN_SHARE,
                                  design_params.VERIFY_MIN_THICKNESS})

    def test_a_the_edge_report_table(self) -> None:
        """RF-014-20, RF-014-21 (plan §5.2.3): ``des_erp_`` lleva, en formato largo, el volumen y
        las celdas de la transición, el ángulo, las parejas del borde, las que pasan, los
        porcentajes, el mayor salto creado (con su lugar), el salto y el porcentaje admitidos y el
        espesor mínimo, iguales a los del informe calculado."""
        outcome = self.calculation.outcome
        rows = {quantity: (value, unit, note) for quantity, value, unit, note in self.query_of(
            f'SELECT quantity, value, unit_code, note FROM "{REPORT}_v01" ORDER BY fid')}
        report = outcome.report
        self.assertEqual(rows["transition_m3"][:2], (outcome.transition.volume_m3, "m3"))
        self.assertEqual(rows["transition_cells"][:2], (float(outcome.transition.cells), "-"))
        self.assertEqual(rows["angle_deg"][:2], (ANGLE_DEG, "deg"))
        self.assertEqual(rows["edge_pairs"][:2], (float(report.pairs), "-"))
        self.assertEqual(rows["over_pairs"][:2], (float(report.over), "-"))
        self.assertEqual(rows["within_pct"][:2], (report.within_pct, "%"))
        self.assertEqual(rows["created_step_max_m"][:2], (report.maximum_m, "m"))
        self.assertEqual(rows["threshold_m"][:2], (THRESHOLD_M, "m"))
        self.assertEqual(rows["min_share_pct"][:2], (SHARE_PCT, "%"))
        self.assertEqual(rows["min_thickness_m"][:2], (self.thickness(), "m"))

    def test_b_a_surface_that_is_not_of_a_design_is_refused(self) -> None:
        """RF-014-19 (plan §5.2.3: una superficie ``design_surface``): la superficie de partida,
        la envolvente de la cantera o un nombre que la versión no tiene se rechazan al avanzar con
        ``des.edge_not_design_surface`` nombrándolos, sin escribir nada."""
        before = self.des_state()
        envelope = provenance.dataset_name("fen", QUARRY_NAME)
        for surface in (START, envelope, "des_fin_no_existe"):
            with self.subTest(surface=surface):
                with self.assertRaises(messages.DesignError) as caught:
                    drive(self.transition_steps("Otra", surface))
                self.assertEqual(caught.exception.code, "des.edge_not_design_surface")
                self.assertIn(surface, caught.exception.text)
        self.assertEqual(self.des_state(), before)

    def test_b_closing_the_steps_midway_leaves_nothing(self) -> None:
        """RF-014-29 (RF-013-33): cerrar «Calcular» con la rejilla ya en su temporal no deja
        nada."""
        before = self.des_state()
        work = self.transition_steps("Transición C", budget_s=1e-9)
        for step in work:
            if step.phase == "store" and len(list((self.root / "rasters").iterdir())) > len(
                    before["files"]):
                break
        self.assertNotEqual(self.des_state()["files"], before["files"], "el temporal existe")
        work.close()
        self.assertEqual(self.des_state(), before)

    # --- Recalcular y reproducir -------------------------------------------------------------

    def test_c_recomputing_repeats_the_transition(self) -> None:
        """RF-014-31, RF-008-26: el recálculo de ``des.edge_transition`` repite la transición con
        sus ajustes (sustituye a la anterior) y da la misma rejilla y las mismas cifras: nada de lo
        que lee ha cambiado."""
        old = self.stored.handle.uid
        settings = json.loads(self.query_of("SELECT settings FROM gb_operation WHERE uid = ?",
                                            old)[0][0])
        sha = self.record(DATASET, self.v1).content_sha256
        figures = self.figures_of(old)
        request = recompute_mod.RecomputeRequest(self.project, old, provenance.EDGE_TRANSITION,
                                                 settings, (), (), version=self.v1.uid)
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(request)
        stored = drive(work).result
        self.assertEqual(stored.handle.uid, handle.uid)
        self.assertEqual(self.query_of("SELECT op_type, status, supersedes_uid FROM gb_operation "
                                       "WHERE uid = ?", handle.uid),
                         [(provenance.EDGE_TRANSITION, "done", old)])
        self.assertEqual(self.record(DATASET, self.v1).content_sha256, sha)
        self.assertEqual(self.figures_of(handle.uid), figures)
        type(self).stored = stored

    def test_d_reproducing_the_frozen_revision_gives_the_same(self) -> None:
        """RF-009-11, RF-014-29: congelar V01 y reproducir su revisión da la superficie con la
        transición y el informe del salto creado con el mismo hash y las mismas cifras, sin
        escribir nada en el proyecto (la superficie de diseño, la de partida y las máscaras se
        leen de lo congelado)."""
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
        self.assertEqual(sorted(check.role for check in mine), ["design_surface", "edge_report"])
        self.assertTrue(all(check.same for check in mine), mine)
        reproduced = {check.key for check in report.figures if check.operation_uid == uid}
        self.assertEqual(reproduced, {"des.transition_m3", "des.created_step_max_m",
                                      "des.created_step_share_pct"})
        self.assertTrue(all(check.same for check in report.figures if check.operation_uid == uid))
        self.assertTrue(report.matches)
