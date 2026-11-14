# SPDX-License-Identifier: GPL-3.0-or-later
"""La comprobación de las superficies de la 014 contra un límite nuevo (spec 014, T31; HU-014-7;
RF-014-26; plan 014 A13, §5.3.1; error 46 del análisis).

- ``design.refit.outside_volume``: de una superficie ``S`` y su partida ``z``, el volumen y el área
  de lo que mueve (``|S − z|`` mayor que el espesor mínimo, con dato en las dos) **fuera del límite
  vigente** de las máscaras (``design.refit.limit_cells``): un corte fuera del perímetro de
  actuación ∩ el límite legal sin su resguardo hacia dentro, o un relleno fuera del perímetro (la
  franja de solo relleno es del límite); y su aviso ``des.refit_outside`` con la superficie, el
  volumen, el área y la versión.
- ``design.store.limit_checks``: al recompilar las máscaras de una versión, eso mismo de cada
  superficie de esta spec que tiene (``limit_surfaces``: las dos de una cantera, no sus envolventes
  ni su clasificación), frente a su superficie de partida y con el espesor mínimo de la 012; sin
  máscaras al día, nada (no hay límite vigente contra el que comprobar). Solo lee.

Sin proyecto, en una rejilla hecha a mano; con proyecto, en una copia de la cantera sintética
(``quarry_fixtures``, T01) con una cantera de dos superficies creada en V01 y el límite legal
redibujado **30 m más corto por el este**; y su caché en memoria (``design.store.LimitCheckMemo``,
spec 014, T35; RNF-014-02), con la clave barata de ``limit_check_keys``.
"""

from __future__ import annotations

import dataclasses
import unittest
from collections.abc import Iterator
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

refit = import_geoblender("design.refit")
store = import_geoblender("design.store")
steps = import_geoblender("design.steps")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
design_params = import_geoblender("design.params")
core_params = import_geoblender("core.params")
res_provenance = import_geoblender("reserves.provenance")
access = import_geoblender("gis.masks.access")
combine = import_geoblender("gis.masks.combine")
gis = import_geoblender("gis")

THICKNESS_M = 0.02
"""El espesor mínimo de las pruebas (el de la 012 por defecto; un dato de entrada)."""
START = qfx.START_DATASET
EXPL, REST = qfx.EXPLOITATION_PROFILE, qfx.FINAL_PROFILE
BY_HAND = {"source": "Perfil de prueba", "source_kind": "person", "decided_by": "Samuel (IMGA)"}
QUARRY_NAME = "Corta E6"
EXPLOITATION = provenance.dataset_name("exp", QUARRY_NAME)
FINAL = provenance.dataset_name("fin", QUARRY_NAME)
CUT_BACK_M = 30.0
"""Lo que el límite nuevo recorta por el este (m): de x = 360 a x = 330 (local)."""
NEW_LEGAL_LOCAL = (qfx.LEGAL_LOCAL[0], qfx.LEGAL_LOCAL[1], qfx.LEGAL_LOCAL[2] - CUT_BACK_M,
                   qfx.LEGAL_LOCAL[3])
"""El límite legal redibujado (local): 290 × 320 m."""
NO_LONGER_CUT_LOCAL = (qfx.LEGAL_LOCAL[2] - CUT_BACK_M - qfx.LEGAL_INWARD_M, 0.0, 400.0, 400.0)
"""Donde el corte deja de estar admitido (local), a mano: al este de x = 330 − 5 (el resguardo
hacia dentro del límite nuevo)."""

# --- Una rejilla a mano: 6 filas × 12 columnas de 2 m (4 m² por celda) --------------------------
HAND_GRID = gis.Grid(700_000.0, 4_400_012.0, 2.0, 2.0, 12, 6)
P, L, B = (int(combine.ClassBit.PERIMETER), int(combine.ClassBit.LEGAL),
           int(combine.ClassBit.INNER_BAND))
COLUMN_BITS = (0, P, P, P | L | B, *([P | L] * 6), P | L | B, L)
"""Los bits de cada columna, a mano: la 0 fuera de todo; la 1 y la 2, la franja de solo relleno
(perímetro sin límite); la 3 y la 10, el resguardo hacia dentro del límite; de la 4 a la 9, dentro;
la 11, en el límite legal pero fuera del perímetro."""


def drive(work: Iterator[Any]) -> Any:
    """Lleva unos pasos hasta el final y devuelve el último ``Progress``."""
    found = None
    for found in work:
        pass
    return found


def drive_value(work: Iterator[Any]) -> Any:
    """Lleva unas unidades hasta el final y devuelve lo que devuelven."""
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value


def hand_masks() -> Any:
    """Las máscaras de :data:`HAND_GRID` con los bits de :data:`COLUMN_BITS`."""
    classes = np.tile(np.array(COLUMN_BITS, dtype=np.uint16), (HAND_GRID.nrows, 1))
    return access.MaskSet(HAND_GRID, "v-mano", "op-mano", access.MaskState.CURRENT, (), classes)


def hand_case() -> tuple[np.ndarray, np.ndarray]:
    """La partida (100 m, sin dato en la celda (0, 0)) y la superficie, a mano: un corte de 2 m en
    las filas 0 y 1, un relleno de 3 m en las 2 y 3 (sin dato en la celda (3, 0)), 0,01 m en la 4
    (menos que el espesor mínimo) y la partida en la 5."""
    start = np.full(HAND_GRID.shape, 100.0)
    start[0, 0] = np.nan
    surface = start.copy()
    surface[0:2] -= 2.0
    surface[2:4] += 3.0
    surface[3, 0] = np.nan
    surface[4] += 0.01
    return start, surface


class OutsideVolumeTest(unittest.TestCase):
    """RF-014-26 sin proyecto: lo que mueve una superficie fuera del límite, a mano."""

    def test_the_limit_cells_by_hand(self) -> None:
        """RF-014-26 (plan A13): dentro del límite para cortar, el perímetro ∩ el límite legal sin
        su resguardo hacia dentro (columnas 4 a 9); para rellenar, todo el perímetro, también la
        franja de solo relleno y el resguardo (columnas 1 a 10)."""
        cut, fill = refit.limit_cells(hand_masks())
        expected_cut = np.zeros(HAND_GRID.shape, dtype=bool)
        expected_cut[:, 4:10] = True
        expected_fill = np.zeros(HAND_GRID.shape, dtype=bool)
        expected_fill[:, 1:11] = True
        np.testing.assert_array_equal(cut, expected_cut)
        np.testing.assert_array_equal(fill, expected_fill)

    def test_volume_and_area_outside_by_hand(self) -> None:
        """RF-014-26: el corte de 2 m sale del límite en las columnas 0 a 3, 10 y 11 de dos filas
        (12 celdas menos la que no tiene partida: 11, 88 m³); el relleno de 3 m, solo en las
        columnas 0 y 11 (4 celdas menos la que no tiene superficie: 3, 36 m³); lo que mueve menos
        que el espesor mínimo no cuenta. 14 celdas, 56 m² y 124 m³; las entradas no cambian."""
        start, surface = hand_case()
        masks = hand_masks()
        kept = (start.copy(), surface.copy(), masks.classes.copy())
        found = refit.outside_volume(surface, start, masks, THICKNESS_M, name="des_exp_mano_v01",
                                     version="V01")
        self.assertEqual((found.surface, found.version, found.cells), ("des_exp_mano_v01", "V01",
                                                                       14))
        self.assertEqual((found.area_m2, found.volume_m3), (56.0, 124.0))
        self.assertEqual(found.min_thickness_m, THICKNESS_M)
        self.assertTrue(found.outside)
        for before, after in zip(kept, (start, surface, masks.classes), strict=True):
            np.testing.assert_array_equal(before, after)

    def test_the_warning_in_both_languages(self) -> None:
        """RF-014-26 (error 46): el aviso ``des.refit_outside`` nombra la superficie, el volumen,
        el área y la versión, y lleva a «Ajustar el diseño a un límite nuevo…», sin un punto
        detrás del «…» (T61, lo que vio el H3 en la ficha)."""
        start, surface = hand_case()
        found = refit.outside_volume(surface, start, hand_masks(), THICKNESS_M,
                                     name="des_exp_mano_v01", version="V01")
        notice = found.notice
        self.assertEqual((notice.code, notice.severity), ("des.refit_outside", "warning"))
        self.assertEqual(notice.text("es"),
                         "«des_exp_mano_v01» deja 124,0 m³ en 56 m² fuera del límite vigente de "
                         "la versión V01: use Diseño ▸ Cantera ▸ Ajustar el diseño a un límite "
                         "nuevo…")
        self.assertEqual(notice.text("en"),
                         "«des_exp_mano_v01» leaves 124.0 m³ in 56 m² outside the current limit "
                         "of version V01: use Design ▸ Quarry ▸ Refit the design to a new "
                         "limit…")

    def test_inside_the_limit_there_is_no_warning(self) -> None:
        """RF-014-26: lo que solo se mueve dentro del límite (un corte en las columnas 4 a 9 y un
        relleno en la franja) da 0 celdas, 0 m³ y ningún aviso; sin versión, la de las
        máscaras."""
        start = np.full(HAND_GRID.shape, 100.0)
        surface = start.copy()
        surface[:, 4:10] -= 5.0
        surface[:, 1:3] += 1.0
        found = refit.outside_volume(surface, start, hand_masks(), THICKNESS_M, name="x")
        self.assertEqual((found.cells, found.area_m2, found.volume_m3), (0, 0.0, 0.0))
        self.assertFalse(found.outside)
        self.assertIsNone(found.notice)
        self.assertEqual(found.version, "v-mano")

    def test_refusals(self) -> None:
        """Una superficie o una partida de otra forma que la rejilla de las máscaras y un espesor
        negativo son errores del programa (``ValueError``)."""
        start, surface = hand_case()
        with self.assertRaises(ValueError):
            refit.outside_volume(surface[:, :5], start, hand_masks(), THICKNESS_M, name="x")
        with self.assertRaises(ValueError):
            refit.outside_volume(surface, start[:3], hand_masks(), THICKNESS_M, name="x")
        with self.assertRaises(ValueError):
            refit.outside_volume(surface, start, hand_masks(), -1.0, name="x")


def declare(project: Any, clock: Any, key: str, value: object) -> None:
    """Declara el parámetro ``key`` en el proyecto."""
    clock.advance(minutes=1)
    with project.write_transaction() as conn:
        core_params.ParameterStore(project).create(
            conn, key, value, kind="ADOPTADO", reason="Prueba de la 014", **BY_HAND)


def never(request: Any) -> Any:  # nunca se llama: solo declara que se repite sola
    raise AssertionError("esta historia no recalcula ni reproduce")


def definitions() -> tuple[Any, ...]:
    """Los tipos de la 013 y de la 014 con sus cifras, como los registra ``bl`` (sin recalcular
    ni reproducir nada)."""
    return (*provenance.operation_defs({t: never for t in provenance.REPRODUCIBLE},
                                       {t: never for t in provenance.REPRODUCIBLE}),
            *(provenance.operation_def(op_type, never)
              for op_type in provenance.QUARRY_VERSION_TYPES),
            *provenance.FIGURES, *provenance.QUARRY_FIGURES)


class LimitChecksTest(qfx.QuarryProjectCase):
    """RF-014-26 con proyecto (véase el módulo), en el orden de las pruebas: la cantera «Corta E6»
    creada en V01 con el límite de la cantera; después, el límite legal 30 m más corto por el este
    y las máscaras de V01 recompiladas."""

    surfaces: ClassVar[dict[str, np.ndarray]]

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
        cls.clock.advance(minutes=1)
        request = model.QuarryRequest(name=QUARRY_NAME, start=START,
                                      final=model.QuarrySide(REST.code),
                                      exploitation=model.QuarrySide(EXPL.code))
        outcome = drive(steps.quarry_run(cls.project, request, version=cls.v1.uid,
                                         masks=cls.masks_of(cls.v1))).result
        outcome.create()
        cls.surfaces = {EXPLOITATION: outcome.outcome.exploitation_grid,
                        FINAL: outcome.outcome.final_grid}

    @classmethod
    def masks_of(cls, version: Any) -> Any:
        return access.load_masks(cls.project, version.uid)

    def written(self) -> list[tuple[Any, ...]]:
        """Lo que hay registrado en el proyecto: operaciones, datos y cifras."""
        return [*self.query("SELECT uid, op_type, status FROM gb_operation ORDER BY fid"),
                *self.query("SELECT name, status, content_sha256 FROM gb_dataset ORDER BY name"),
                *self.query("SELECT count(*) FROM gb_figure")]

    def expected(self, name: str) -> tuple[int, float]:
        """Las celdas y el volumen fuera del límite nuevo de la superficie ``name``, a mano: lo que
        mueve (más que el espesor mínimo frente a la ladera) al este de x = 325 (local)."""
        start, surface = qfx.terrain(), self.surfaces[name]
        moved = np.abs(surface - start) > THICKNESS_M
        moved &= np.isfinite(surface)
        outside = moved & qfx.in_box(NO_LONGER_CUT_LOCAL)
        self.assertFalse((surface[outside] > start[outside]).any())  # la cantera solo corta
        return int(np.count_nonzero(outside)), float(np.abs(surface - start)[outside].sum())

    def test_a_with_the_limit_it_was_designed_for_nothing_is_outside(self) -> None:
        """RF-014-26: las superficies de la 014 de V01 son las dos de la cantera (no sus
        envolventes, su clasificación ni la ladera); con el límite con que se diseñó, ninguna deja
        nada fuera y no hay aviso; comprobar no escribe nada. V02 no tiene ninguna."""
        with self.project.read() as conn:
            listed = store.limit_surfaces(conn, self.v1.uid)
            self.assertEqual(store.limit_surfaces(conn, self.v2.uid), ())
        self.assertEqual([origin.record.name for origin in listed], sorted([EXPLOITATION, FINAL]))
        self.assertEqual({origin.op_type for origin in listed}, {provenance.QUARRY})
        before = self.written()
        found = store.limit_checks(self.project, self.v1.uid)
        self.assertEqual(self.written(), before)
        self.assertEqual([check.surface for check in found], sorted([EXPLOITATION, FINAL]))
        for check in found:
            with self.subTest(superficie=check.surface):
                self.assertEqual((check.version, check.cells, check.volume_m3), ("V01", 0, 0.0))
                self.assertEqual(check.min_thickness_m, THICKNESS_M)
                self.assertIsNone(check.notice)
        self.assertEqual(store.limit_checks(self.project, self.v2.uid), ())

    def test_b_a_limit_cut_back_30_m_leaves_both_surfaces_outside(self) -> None:
        """RF-014-26 (error 46): con el límite legal 30 m más corto por el este, mientras las
        máscaras de V01 no se recompilan no hay límite vigente y no se comprueba nada; al
        recompilarlas, cada superficie de la cantera deja fuera, a mano, lo que corta al este de x =
        325 (local; el resguardo de 5 m hacia dentro del límite nuevo), con su aviso; solo la pedida
        si se nombra; y no se escribe nada."""
        (legal,) = [item for item in self.stored_constraints() if item.code == "concesion"]
        self.clock.advance(minutes=1)
        cp.edit_constraints(self.project, [dataclasses.replace(
            legal, parts=((cfx.rectangle(*NEW_LEGAL_LOCAL),),))])
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.STALE)
        self.assertEqual(store.limit_checks(self.project, self.v1.uid), ())
        self.clock.advance(minutes=1)
        drive(access.ensure_masks_steps(self.project, self.v1.uid))

        before = self.written()
        found = {check.surface: check for check in store.limit_checks(self.project,
                                                                      self.v1.uid)}
        self.assertEqual(self.written(), before)
        self.assertEqual(sorted(found), sorted([EXPLOITATION, FINAL]))
        for name, check in found.items():
            with self.subTest(superficie=name):
                cells, volume = self.expected(name)
                self.assertGreater(cells, 0)
                self.assertEqual((check.cells, check.area_m2), (cells, float(cells)))
                self.assertAlmostEqual(check.volume_m3, volume, delta=1e-9 * volume)
                self.assertEqual(check.notice.code, "des.refit_outside")
                self.assertIn(f"«{name}» deja ", check.notice.text("es"))
                self.assertIn("de la versión V01", check.notice.text("es"))
        (only,) = store.limit_checks(self.project, self.v1.uid, names=(FINAL,))
        self.assertEqual((only.surface, only.cells), (FINAL, found[FINAL].cells))
        self.assertEqual(store.limit_checks(self.project, self.v1.uid, names=(START,)), ())

    def set_hash(self, name: str, digest: str) -> None:
        """Cambia el hash de contenido registrado del dato ``name`` de V01 (lo que cambia al
        reescribir una superficie)."""
        with self.project.write_transaction() as conn:
            conn.execute("UPDATE gb_dataset SET content_sha256 = ? WHERE name = ? AND version_uid "
                         "= ? AND status = 'current'", (digest, name, self.v1.uid))

    def test_c_the_memo_hits_misses_and_follows_its_keys(self) -> None:
        """RNF-014-02 (spec 014, T35; RF-014-26): la caché de la comprobación
        (``design.store.LimitCheckMemo``). Vacía, no acierta; llenada por pasos
        (:meth:`~LimitCheckMemo.fill_steps`, en unidades), da lo mismo que ``limit_checks`` (todas,
        solo una por su nombre o su uid, ninguna de otra) **sin leer ninguna rejilla**, con el tipo
        de cada una; cerrada a mitad, o si una clave cambia mientras se llena, no guarda nada. Se
        invalida sola: con otro hash de una superficie (como al reescribirla) esa no acierta y,
        repuesto, vuelve a acertar; con las máscaras obsoletas (otra restricción) o recompiladas,
        nada acierta hasta llenarla otra vez. La clave no lee rejillas y es la misma para una
        superficie pida quien la pida (``types``)."""
        memo = store.LimitCheckMemo()
        self.assertIsNone(memo.lookup(self.project, self.v1.uid))
        expected = store.limit_checks(self.project, self.v1.uid)
        self.assertEqual(len(expected), 2)
        ((final_uid, original),) = self.query(
            "SELECT uid, content_sha256 FROM gb_dataset WHERE name = ? AND version_uid = ? AND "
            "status = 'current'", FINAL, self.v1.uid)

        work = memo.fill_steps(self.project, self.v1.uid)
        next(work)
        next(work)
        work.close()  # cerrada a mitad: nada guardado
        self.assertEqual(len(memo), 0)
        work = memo.fill_steps(self.project, self.v1.uid)
        next(work)
        self.set_hash(FINAL, "0" * 64)  # cambia una clave mientras se llena: nada guardado
        drive_value(work)
        self.assertEqual(len(memo), 0)
        self.set_hash(FINAL, original)

        units = 0
        work = memo.fill_steps(self.project, self.v1.uid)
        while True:
            try:
                self.assertIsNone(next(work))
            except StopIteration as stop:
                found = stop.value
                break
            units += 1
        self.assertGreater(units, 3)
        self.assertEqual([check for _op_type, check in found], list(expected))
        self.assertEqual({op_type for op_type, _check in found}, {provenance.QUARRY})
        surfaces = import_geoblender("design.surfaces")
        with mock.patch.object(store, "read_surface", side_effect=AssertionError("lee")), \
                mock.patch.object(surfaces, "read_surface", side_effect=AssertionError("lee")):
            self.assertEqual(memo.lookup(self.project, self.v1.uid), expected)
            by_name = {check.surface: check for check in expected}
            self.assertEqual(memo.lookup(self.project, self.v1.uid, names=(FINAL,)),
                             (by_name[FINAL],))
            self.assertEqual(memo.lookup(self.project, self.v1.uid, names=(final_uid,)),
                             (by_name[FINAL],))
            self.assertEqual(memo.lookup(self.project, self.v1.uid, names=(START,)), ())
            self.assertEqual(memo.lookup(self.project, self.v1.uid,
                                         types=store.REFIT_SOURCES), expected)
        keys = store.limit_check_keys(self.project, self.v1.uid)
        self.assertEqual(keys, store.limit_check_keys(self.project, self.v1.code))
        self.assertEqual(keys.surfaces, store.limit_check_keys(
            self.project, self.v1.uid, types=store.REFIT_SOURCES).surfaces)

        self.set_hash(FINAL, "f" * 64)  # otra superficie: esa no acierta; la otra, sí
        self.assertIsNone(memo.lookup(self.project, self.v1.uid))
        self.assertIsNone(memo.lookup(self.project, self.v1.uid, names=(FINAL,)))
        self.assertEqual(memo.lookup(self.project, self.v1.uid, names=(EXPLOITATION,)),
                         (by_name[EXPLOITATION],))
        self.set_hash(FINAL, original)
        self.assertEqual(memo.lookup(self.project, self.v1.uid), expected)

        (legal,) = [item for item in self.stored_constraints() if item.code == "concesion"]
        self.clock.advance(minutes=1)
        cp.edit_constraints(self.project, [dataclasses.replace(
            legal, parts=((cfx.rectangle(*qfx.LEGAL_LOCAL),),))])  # el límite de antes
        self.assertIsNone(memo.lookup(self.project, self.v1.uid))  # máscaras obsoletas
        self.clock.advance(minutes=1)
        drive(access.ensure_masks_steps(self.project, self.v1.uid))
        self.assertIsNone(memo.lookup(self.project, self.v1.uid))  # recompiladas: otras
        found = drive_value(memo.fill_steps(self.project, self.v1.uid))
        self.assertEqual([check.cells for _op_type, check in found], [0, 0])
        self.assertEqual(memo.lookup(self.project, self.v1.uid),
                         tuple(check for _op_type, check in found))
        memo.clear()
        self.assertEqual(len(memo), 0)
        self.assertIsNone(memo.lookup(self.project, self.v1.uid))
        self.assertEqual(drive_value(memo.fill_steps(self.project, self.v2.uid)), ())
        self.assertEqual(memo.lookup(self.project, self.v2.uid), ())


if __name__ == "__main__":
    unittest.main()
