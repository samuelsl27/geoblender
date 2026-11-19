# SPDX-License-Identifier: GPL-3.0-or-later
"""CE-016-03 completo y los diseños de la 013, 014 y 015 «iguales con y sin base» (spec 016, T31; HU-016-2; RF-012-21,
RF-012-22, RF-012-24, RF-012-30, RF-012-31; RF-016-09, RF-016-11, RF-016-13, RF-016-15; plan 016 §5.4 A12, §7.1; DIFF-012 §4
(c) y (e); P-13: con proyecto en la rejilla de 2 m, al paso «hito» de ``tools/check.py --completo``; el «verde» lleva los casos
de ``tests/referencia/res/test_ref_compliance_stockpile.py``).

:class:`TallVerificationTest` es **la verificación de la 012 de la revisión que contiene la retirada** del acopio de 12 m junto a
un relleno de la 015 de CE-016-03 (el mundo del hito H2, ``milestone_stockpile_ce.TallWorld``: el levantamiento alto de V01, la
detección ``STK-001``, el relleno ``PLT-001`` que lo cubre y la retirada ``RMV-001`` desde ese relleno con lo apoyado confirmado),
con cuatro recintos más de las zonas de la 012 sobre su huella en bandas de 12 a 18 m —**sin corte**, **solo relleno**, **solo
restauración** y **banda de resguardo**— y el límite legal «Concesión» ajustado al acopio con 50 m hacia dentro (su **banda hacia
dentro**, ``concesion:inner``, cubre casi toda la huella): las cinco zonas del dominio por defecto de RF-012-30. La partida es el
dato sobre el que se hizo la detección (el levantamiento) y la final, la superficie de la retirada (CE-016-03, T30: la base es la
de la detección **sobre esa partida**). Las cuentas, a mano con bucles sobre las rejillas leídas de los ficheros (el cálculo
independiente de la T31, no el código que se prueba):

- **(a)** terreno 0 m³ y «cumple» en las cinco zonas, con el corte de acopios aparte (el de la huella, > 0), terreno + acopios =
  el corte de RF-012-21 a ≤ 10⁻⁹ relativo; la cifra CALCULADO del corte de acopios por zona (RF-012-24).
- **(b)** una celda de cada banda **por debajo de la base** (0,5 m): «no cumple» con 2 m³ de corte de terreno en cada zona (los de
  sus celdas; la banda hacia dentro, con las suyas) y un grupo por celda.
- **(c)** sin acopios (la selección vacía) da lo mismo que antes, **bit a bit** frente a ``compliance.check`` sin base sobre las
  mismas rejillas: todo el corte cuenta y la retirada «no cumple»; ni una entrada, ni una fila, ni una cifra de acopios.
- **(c)** el relleno ``PLT-001`` (un diseño de la 015) verifica lo mismo con y sin base.
- **(e)** una detección **obsoleta** (cambiar el umbral de la 011) no se usa y se avisa con su causa: todo el corte cuenta.

:class:`DesignsWithBaseTest` y :class:`QuarryMasksWithBaseTest` repiten CE-013-06 (100 diseños sintéticos de la 013 en el sitio de
la 012, que verifican 0 m³ en todos los recintos) y los mismos diseños sobre las máscaras de la cantera de la 014 con **una
base de acopios** en lo que dejan sin tocar: las mismas cifras que sin ella (las cinco zonas cuentan el corte de terreno, y los
diseños solo cortan en el corte admitido: DIFF-012 §3).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from typing import Any, ClassVar

import numpy as np

from tests.referencia.des import test_ref_design_masks as dm
from tests.referencia.res import test_ref_compliance_stockpile as ref
from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cproject
from tests.support import design_fixtures as dfx
from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.res_fixtures import write_grids
from tests.unit.design import milestone_stockpile_ce as ce
from tests.unit.design import milestone_stockpile_supports as sup
from tests.unit.design import test_removal_operation as rem
from tests.unit.design import test_stockpile_prepare as tp

access = import_geoblender("gis.masks.access")
cmodel = import_geoblender("core.constraints.model")
core_params = import_geoblender("core.params")
cparams = import_geoblender("core.constraints.params")
cstore_constraints = import_geoblender("core.constraints.store")
compliance = import_geoblender("reserves.compliance")
cstore = import_geoblender("reserves.compliance_store")
figures_mod = import_geoblender("core.provenance.figures")
gis = import_geoblender("gis")
provenance = import_geoblender("design.provenance")
stockpile_store = import_geoblender("design.stockpile_store")
surfaces = import_geoblender("reserves.surfaces")

T = cmodel.ConstraintType
C = compliance.Counts
V = compliance.Verdict
CELL_M2 = ce.CELL_M2
MIN_M = 0.02
"""El espesor mínimo de verificación (D-6, ADOPTADO)."""
LEGAL_BOX_M = (90.0, 100.0, 210.0, 220.0)
"""El límite legal «Concesión» (local): 120 × 120 m que rodean el pie del acopio de 12 m (de 120 a 180 m en x y de 130 a 190
en y) con 30 m de sobra (el relleno de la 015 y la marca con su margen quedan dentro del dominio)."""
INWARD_M = 50.0
"""Su resguardo hacia dentro: la banda de 50 m cubre todo lo que no es el núcleo de (140, 150) a (160, 170) m."""
STRIPS = {
    "z_sin_corte": ("Sin corte del acopio", T.NO_CUT, (120.0, 130.0, 138.0, 190.0)),
    "z_solo_relleno": ("Solo relleno del acopio", T.FILL_ONLY, (138.0, 130.0, 150.0, 190.0)),
    "z_solo_restauracion": ("Solo restauración del acopio", T.RESTORATION_ONLY, (150.0, 130.0, 162.0, 190.0)),
    "z_resguardo": ("Resguardo del acopio", T.SETBACK, (162.0, 130.0, 180.0, 190.0)),
}
"""Las cuatro zonas en bandas verticales sobre la huella (local; los lados, en múltiplos de 2 m: ninguna celda de 2 m queda a
caballo): código → (nombre, tipo, caja)."""
INNER = "concesion:inner"
FIVE = (*STRIPS, INNER)
PITS = {"z_sin_corte": (128.0, 136.0, 130.0, 138.0), "z_solo_relleno": (142.0, 136.0, 144.0, 138.0),
        "z_solo_restauracion": (156.0, 136.0, 158.0, 138.0), "z_resguardo": (170.0, 136.0, 172.0, 138.0)}
"""Las celdas (cajas de una celda de 2 m, local) que se bajan 0,5 m por debajo de la base: una en cada banda, en el sur de la
huella (a 6 m de su pie: ya tiene 3 m de acopio)."""
PIT_M = 0.5
NAME = "Revisión con la retirada"
REMOVAL_SURFACE = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, ce.REMOVAL)
OVER_SURFACE = ce.OVER_SURFACE
USER = sup.USER


def _no_recompute(request: Any) -> Any:
    raise AssertionError("las pruebas de la verificación no recalculan con la función de bl")


def _last(steps: Any) -> Any:
    found = None
    for step in steps:
        if step.result is not None:
            found = step.result
    return found


def zone_row(code: str, name: str, ctype: Any, box: tuple[float, float, float, float]) -> Any:
    kinds = cmodel.GeometryKind
    return cmodel.Constraint(
        uid=f"{code:0<32}"[:32], code=code, name=name, ctype=ctype, kind=kinds.POLYGON, parts=((cfx.rectangle(*box),),),
        priority=0, reason="Prueba de CE-016-03 con la verificación de la 012", decided_by="Samuel (IMGA)",
        decided_on=date(2026, 11, 19), decision_uid=None, intention_uid=None, source_input=None, source_fid=None,
        layer=cstore_constraints.layer_of(kinds.POLYGON), fid=0)


class TallVerificationTest(ce.TallWorld):
    """CE-016-03 (la verificación de la 012 de la revisión con la retirada) en las cinco zonas, y el resto de (c) y (e) con el
    mundo del acopio de 12 m. **En orden** (``test_a`` a ``test_e``): cada prueba parte de lo que dejó la anterior; la última
    deja obsoleta la detección."""

    survey: ClassVar[np.ndarray]
    final: ClassVar[np.ndarray]
    base: ClassVar[np.ndarray]
    footprint: ClassVar[np.ndarray]
    masks: ClassVar[Any]

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return (*super().definitions(), cstore.operation_def(_no_recompute, cstore.REPRODUCE[cstore.VERIFY]),
                *cstore.FIGURES)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        with cls.project.read() as conn:
            (legal,) = [row for row in cstore_constraints.read_constraints(conn) if row.code == "concesion"]
        rows = [dataclasses.replace(legal, parts=((cfx.rectangle(*LEGAL_BOX_M),),)),
                *(zone_row(code, name, ctype, box) for code, (name, ctype, box) in STRIPS.items())]
        cls.clock.advance(minutes=1)
        cproject.edit_constraints(cls.project, rows)
        cproject.declare(cls.project, cls.clock, {key: value for code in STRIPS for key, value in (
            (cparams.active_key(code), True), (cparams.buffer_out_key(code), 0.0))})
        cls.change(cparams.buffer_in_key("concesion"), INWARD_M)
        cls.clock.advance(minutes=1)
        for _step in access.ensure_masks_steps(cls.project, cls.v1.uid):
            pass
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        cls.build_world()
        cls.made(ce.over(ce.OVER))
        cls.make(rem.asked(ce.REMOVAL, ce.KEY, start="entity:PLT-001", transition_deg=ce.ANGLE_DEG),
                 confirm={"resting": True})
        probe = cls("test_a_the_removal_complies_in_the_five_zones_with_the_stockpile_cut_apart")
        cls.survey, cls.final = probe.grid_of(ce.SURVEY), probe.grid_of(REMOVAL_SURFACE)
        cls.base, cls.footprint = probe.grid_of(ce.BASE), probe.footprint_mask()
        cls.masks = cls.masks_v1
        cls.write_finals(("retirada", cls.final))

    @classmethod
    def write_finals(cls, *grids: tuple[str, np.ndarray]) -> None:
        """Escribe ``grids`` (etiqueta, cotas) como rejillas del proyecto (``gis_dtm_<etiqueta>``)."""
        cls.clock.advance(minutes=1)
        write_grids(cls.project, [(label, gis.Raster(ce.GRID, values, sdata.CRS, sdata.VERTICAL)) for label, values in grids],
                    message="Finales de la verificación con la base (T31)")

    # --- Ayudas -------------------------------------------------------------------------------

    def start_ref(self) -> Any:
        """La partida: el dato sobre el que se hizo la detección (el levantamiento alto de V01)."""
        return surfaces.SurfaceRef(dataset=ce.SURVEY, label="Levantamiento alto")

    def verify(self, finals: tuple[str, ...], *, name: str = NAME, **options: Any) -> Any:
        """Verifica ``finals`` (datasets de V01 o del proyecto) frente al levantamiento en V01: lo guardado (``StoredCheck``)."""
        self.clock.advance(minutes=1)
        return _last(cstore.verify_project_steps(
            self.project, version=self.v1.uid, name=name, start=self.start_ref(),
            finals=tuple(surfaces.SurfaceRef(dataset=dataset) for dataset in finals), **options))

    def zone_mask(self, code: str) -> np.ndarray:
        """Las celdas del recinto ``code`` de las máscaras de V01 (compiladas), como máscara de la rejilla."""
        return np.asarray(self.masks.zones[code].mask(ce.GRID.shape))

    def hand(self, mask: np.ndarray, start: np.ndarray, base: np.ndarray, final: np.ndarray) -> tuple[float, float]:
        """A mano, en las celdas de ``mask``: el corte de RF-012-21 y el corte de terreno de RF-012-30 (``R = mín(partida, base)``
        donde hay base), en m³ (celdas de 4 m²), de las diferencias que pasan del espesor mínimo."""
        s, b, f = start[mask], base[mask], final[mask]
        with np.errstate(invalid="ignore"):
            cut = s - f
            terrain = np.fmin(s, b) - f
            return float(cut[cut > MIN_M].sum()) * CELL_M2, float(terrain[terrain > MIN_M].sum()) * CELL_M2

    def operation(self, name: str = NAME) -> str:
        """La verificación vigente llamada ``name``."""
        for uid, text in self.query("SELECT uid, settings FROM gb_operation WHERE op_type = ? AND status = 'done' AND "
                                    "superseded_by IS NULL ORDER BY rowid DESC", cstore.VERIFY):
            if json.loads(text)["name"] == name:
                return str(uid)
        raise AssertionError(f"no hay una verificación «{name}»")

    def stale(self, uid: str) -> bool:
        return bool(self.query("SELECT 1 FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?", uid))

    # --- Las pruebas ----------------------------------------------------------------------------

    def test_a_the_removal_complies_in_the_five_zones_with_the_stockpile_cut_apart(self) -> None:
        """CE-016-03, RF-012-30, RF-012-22, RF-012-21, RF-012-24, RF-016-09: la verificación de la revisión que contiene la
        retirada (el relleno de la 015 y la retirada desde él), frente al levantamiento sobre el que se hizo la detección, da en
        **cada una de las cinco zonas** (sin corte, solo relleno, solo restauración, banda de resguardo y banda hacia dentro de
        un límite legal) **corte de terreno 0 m³ y «cumple»**, con el corte de acopios aparte (el de la huella, a mano, > 0) y
        terreno + acopios = el corte de RF-012-21 a ≤ 10⁻⁹ relativo; nada incumple; la base es la de la detección (una por
        material) y la cifra CALCULADO del corte de acopios sale en cada zona."""
        for code, (_name, _ctype, box) in STRIPS.items():  # las cuatro zonas: lo compilado, lo que cuenta la regla de la celda a mano
            np.testing.assert_array_equal(np.flatnonzero(self.zone_mask(code)), tp.hand_cells(box), code)
        band = self.zone_mask(INNER)
        inside = np.zeros(ce.GRID.shape, dtype=bool)
        inside.ravel()[tp.hand_cells(LEGAL_BOX_M)] = True
        self.assertTrue(np.all(inside[band]), "la banda es del límite")
        self.assertFalse(band.ravel()[tp.hand_cells((140.0, 150.0, 160.0, 170.0))].any(), "el núcleo (50 m de resguardo) no es banda")
        self.assertGreater(int(np.count_nonzero(band & self.footprint)), 500, "la banda cubre casi toda la huella")
        stored = self.verify((REMOVAL_SURFACE,))
        result = stored.result
        self.assertEqual(result.fails, (False,), "nada incumple")
        (used,) = result.selection.bases
        self.assertEqual((used.detection, used.scope, used.material), ("STK-001", "version", "mineral"))
        self.assertEqual(result.selection.skipped, ())
        check = result.finals[0]
        uid = self.operation()
        figures = {(key, scope): value for key, scope, value in self.query(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", uid)}
        for code in FIVE:
            mask = self.zone_mask(code)
            cut, terrain = self.hand(mask, self.survey, self.base, self.final)
            zone = check.zone(code)
            with self.subTest(zona=code):
                self.assertEqual(terrain, 0.0, "a mano, el corte de terreno es 0: la retirada no baja de la base")
                self.assertGreater(cut, 100.0, "y hay corte de acopios en la zona")
                self.assertEqual((zone.counts, zone.verdict), (C.CUT_TERRAIN, V.COMPLIES))
                self.assertEqual(zone.counted_m3, 0.0)
                ref.close(self, zone.cut_m3, cut, "el corte de RF-012-21")
                ref.close(self, zone.stockpile_cut_m3, cut, "el corte de acopios")
                ref.close(self, zone.counted_m3 + zone.stockpile_cut_m3, zone.cut_m3, "terreno + acopios")
                scope = figures_mod.scope_json({"check": NAME, "final": 1, "zone": code})
                ref.close(self, figures[("res.check_stockpile_cut_m3", scope)], cut, "la cifra del corte de acopios")
        self.assertEqual(check.groups, ())
        self.assertIsNone(check.violations)
        for other in check.totals:  # lo que no es de las cinco no cambia: el relleno, fuera del límite legal, no cuenta
            if other.code not in FIVE:
                self.assertEqual(other.stockpile_cut_m3, 0.0, other.code)
                self.assertNotEqual(other.verdict, V.FAILS, other.code)

    def test_b_a_cell_below_the_base_does_not_comply_with_the_cut_under_the_base(self) -> None:
        """CE-016-03, RF-012-30, RF-012-22: bajando **una celda de cada banda por debajo de la base** (0,5 m), la verificación
        «no cumple» en esa zona y solo en ella (y en la banda hacia dentro, que las contiene) con **el corte bajo la base** (2 m³
        por celda: 0,5 m · 4 m²), a mano sobre las celdas de cada zona, y un grupo por celda; el corte de acopios de la zona
        sigue siendo el resto (terreno + acopios = el corte de RF-012-21)."""
        dug = self.final.copy()
        cells = {}
        for code, box in PITS.items():
            (cell,) = tp.hand_cells(box)
            cells[code] = int(cell)
            self.assertTrue(self.footprint.ravel()[cell], f"{code}: la celda es de la huella")
            self.assertFalse(np.isnan(self.base.ravel()[cell]))
            dug.ravel()[cell] = self.base.ravel()[cell] - PIT_M
        self.write_finals(("pozo", dug))
        result = self.verify(("gis_dtm_pozo",), name="Con celdas bajo la base").result
        self.assertEqual(result.fails, (True,))
        check = result.finals[0]
        for code in FIVE:
            mask = self.zone_mask(code)
            cut, terrain = self.hand(mask, self.survey, self.base, dug)
            pits = [cell for cell in cells.values() if mask.ravel()[cell]]
            zone = check.zone(code)
            with self.subTest(zona=code):
                ref.close(self, terrain, len(pits) * PIT_M * CELL_M2, "a mano, el corte bajo la base")
                self.assertGreater(len(pits), 0)
                self.assertEqual((zone.counts, zone.verdict), (C.CUT_TERRAIN, V.FAILS))
                ref.close(self, zone.counted_m3, terrain, "el corte de terreno")
                ref.close(self, zone.cut_m3, cut, "el corte de RF-012-21")
                ref.close(self, zone.counted_m3 + zone.stockpile_cut_m3, zone.cut_m3, "terreno + acopios")
                self.assertGreater(zone.stockpile_cut_m3, 100.0)
                groups = check.groups_of(code)
                self.assertEqual(len(groups), len(pits))
                for group in groups:
                    self.assertEqual((group.cells, group.area_m2), (1, CELL_M2))
                    ref.close(self, group.volume_m3, PIT_M * CELL_M2, "el volumen de su grupo")
                    ref.close(self, group.max_m, PIT_M, "su espesor")
        failing = {total.code for total in check.totals if total.verdict is V.FAILS}
        self.assertEqual(failing, set(FIVE), "no cumplen las cinco (cada una por su celda) y ninguna más")

    def test_c_without_detected_stockpiles_it_is_the_old_result_bit_for_bit(self) -> None:
        """CE-016-03, RF-012-30, RF-012-24: sin acopios detectados (la selección vacía), la verificación de la misma retirada da
        lo mismo que antes: todo el corte cuenta (el de la huella: la retirada «no cumple» en las cinco zonas), **bit a bit**
        lo que da ``compliance.check`` sin base sobre las mismas rejillas y los mismos recintos (totales, grupos y rejilla de
        incumplimientos); ni una entrada, ni una fila, ni una cifra de acopios."""
        stored = self.verify(("gis_dtm_retirada",), name="Sin acopios", bases=cstore.BaseSelection())
        check = stored.result.finals[0]
        masks = self.masks
        zones = compliance.check_zones(masks.classes, masks.zones, masks.ctypes, masks.weights)
        direct = compliance.check(masks.grid, zones, self.survey, self.final, MIN_M)
        self.assertEqual(ref.totals_of(check), ref.totals_of(direct))
        self.assertEqual([dataclasses.astuple(item) for item in check.totals], [dataclasses.astuple(item) for item in direct.totals],
                         "bit a bit, también lo que cuenta cada recinto")
        self.assertEqual(ref.groups_of(check), ref.groups_of(direct))
        self.assertTrue(np.array_equal(check.violations, direct.violations, equal_nan=True))
        for code in FIVE:
            cut, _terrain = self.hand(self.zone_mask(code), self.survey, np.full(ce.GRID.shape, np.nan), self.final)
            zone = check.zone(code)
            with self.subTest(zona=code):
                self.assertEqual((zone.counts, zone.verdict, zone.stockpile_cut_m3), (C.CUT, V.FAILS, 0.0))
                ref.close(self, zone.counted_m3, cut, "todo el corte cuenta")
                ref.close(self, zone.cut_m3, cut, "el corte de RF-012-21")
        self.assertEqual(stored.result.fails, (True,))
        uid = self.operation("Sin acopios")
        roles = {row[0] for row in self.query("SELECT role FROM gb_operation_io WHERE operation_uid = ?", uid)}
        self.assertFalse({role for role in roles if "base" in role})
        self.assertEqual({key for (key, _scope) in (
            (row[0], row[1]) for row in self.query("SELECT key, scope FROM gb_figure WHERE operation_uid = ?", uid))},
            {"res.check_cut_m3", "res.check_fill_m3", "res.check_moved_area_m2", "res.check_nodata_area_m2"})
        self.assertNotIn("bases", json.loads(self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)[0][0]))
        with self.project.read() as conn:
            read = cstore.read_verification(conn, self.v1.uid, "Sin acopios")
        self.assertEqual((read.bases, read.skipped), ((), ()))
        self.assertTrue(all(item.stockpile_cut_m3 is None for item in read.zones))

    def test_d_the_fill_of_the_015_verifies_the_same_with_and_without_the_base(self) -> None:
        """RF-012-30, DIFF-012 §3 (c): el relleno ``PLT-001`` (un diseño de la 015: solo rellena sobre el levantamiento y sobre el
        acopio) verifica lo mismo con la base de la detección que sin ella: nada incumple, corte 0 en todos los recintos y los
        mismos totales y grupos (solo cambia lo que cuenta en las cinco zonas)."""
        with_base = self.verify((OVER_SURFACE,), name="Relleno con base").result
        without = self.verify((OVER_SURFACE,), name="Relleno sin base", bases=cstore.BaseSelection()).result
        self.assertEqual((with_base.fails, without.fails), ((False,), (False,)))
        self.assertEqual(len(with_base.selection.bases), 1)
        self.assertEqual(without.selection.bases, ())
        a, b = with_base.finals[0], without.finals[0]
        self.assertEqual(ref.totals_of(a), ref.totals_of(b))
        self.assertEqual(ref.groups_of(a), ref.groups_of(b))
        for code in FIVE:
            zone = a.zone(code)
            self.assertEqual((zone.cut_m3, zone.counted_m3, zone.stockpile_cut_m3), (0.0, 0.0, 0.0), code)
            self.assertEqual(zone.counts, C.CUT_TERRAIN)
            self.assertEqual(b.zone(code).counts, C.CUT)
        self.assertGreater(a.zone("z_solo_relleno").fill_m3, 0.0, "y rellena de verdad")

    def test_e_an_obsolete_detection_is_not_used_and_all_the_cut_counts(self) -> None:
        """RF-012-31, RF-012-24, CE-016-03: cambiar el umbral de la huella (la 011) deja obsoleta la detección y, con ella, la
        verificación de la revisión (la base era una de sus entradas); la selección **ya no la usa** y lo dice con su causa;
        una verificación nueva cuenta todo el corte, como sin base (la retirada «no cumple» en las cinco zonas), nombrando la
        detección y la causa en lo que guarda."""
        before = self.operation()
        self.assertFalse(self.stale(before))
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(
                conn, "res.anthropic_presence_m", value=0.6, source="prueba de la T31", source_kind="person",
                decided_by=USER, reason="Se cambia el umbral de la huella", version=None)
        self.assertTrue(self.stale(self.current()), "la detección")
        self.assertTrue(self.stale(before), "la verificación, por su base")
        found = cstore.select_bases(self.project, self.v1.uid, self.start_ref())
        self.assertEqual(found.bases, ())
        (skipped,) = found.skipped
        self.assertEqual((skipped.detection, skipped.reason), ("STK-001", stockpile_store.EXCLUDED_STALE))
        self.assertTrue(skipped.cause)
        text = skipped.text("Levantamiento alto")
        self.assertIn("«Acopios»", text)
        self.assertIn(skipped.cause, text)
        stored = self.verify(("gis_dtm_retirada",), name="Con la detección obsoleta")
        check = stored.result.finals[0]
        for code in FIVE:
            zone = check.zone(code)
            with self.subTest(zona=code):
                self.assertEqual((zone.counts, zone.verdict, zone.stockpile_cut_m3), (C.CUT, V.FAILS, 0.0))
                self.assertEqual(zone.counted_m3, zone.cut_m3)
                self.assertGreater(zone.cut_m3, 100.0)
        with self.project.read() as conn:
            read = cstore.read_verification(conn, self.v1.uid, "Con la detección obsoleta")
        self.assertEqual(read.bases, ())
        self.assertTrue(any("«Acopios»" in item and "obsoleta" in item and skipped.cause in item for item in read.skipped),
                        read.skipped)


class _WithBase(dm.Verification):
    """Los recintos de las máscaras con el modo de contar de la verificación con base (``check_zones(with_base=True)``) y su
    verificador, para comparar con el de siempre."""

    def __init__(self, masks: Any) -> None:
        super().__init__(masks)
        found = list(compliance.check_zones(masks.classes, masks.zones, masks.ctypes, masks.weights, with_base=True))
        found.append(dataclasses.replace(self.zones[-1]))  # «todo», que no es de ninguno de los cinco
        self.zones_base = tuple(found)
        self.index_base = compliance.zone_index(masks.grid, self.zones_base)

    def check_with_base(self, start: np.ndarray, final: np.ndarray, base: np.ndarray) -> Any:
        checker = compliance.Checker(self.masks.grid, self.zones_base, dm.MIN_THICKNESS_M, index=self.index_base)
        checker.add(0, start, final, base)
        return checker.result()


def assert_same_with_base(test: Any, plain: Any, based: Any) -> None:
    """Los mismos totales (sin lo que cuenta cada recinto), grupos y rejilla de incumplimientos con y sin base, y 0 m³ de
    corte de acopios."""
    ref.assert_identical(test, based, plain)
    test.assertTrue(all(item.stockpile_cut_m3 == 0.0 for item in based.totals))


class DesignsWithBaseTest(dfx.DesignProjectCase):
    """CE-013-06 con una base de acopios (DIFF-012 §3 y §4 (c); RF-012-30): los 100 diseños sintéticos de la 013 (los de
    ``test_ref_design_masks``: envolventes y escalonados con y sin recorte, compuestos con las máscaras de V01 de la 012) dan lo
    mismo —0 m³ en los recintos que juzgan, mismos totales y grupos— verificados con una base de acopios (a 3 m por debajo del
    terreno en el 40 % de las celdas) que sin ella."""

    def test_one_hundred_designs_verify_the_same_with_a_base(self) -> None:
        """RF-012-30, RF-012-21, RF-012-22 (DIFF-012 §3 y §4 (c)): los 100 diseños de CE-013-06, cada uno con una base distinta,
        no incumplen ningún recinto, cuentan 0 m³ en los que juzgan y dan los mismos totales, grupos y rejilla de incumplimientos
        que sin base (y 0 m³ de corte de acopios); la gran mayoría mueve tierra."""
        masks = access.load_masks(self.project, self.v1.uid)
        verification = _WithBase(masks)
        start = dm.terrain_of(masks.grid.shape)
        generator = dm.RandomDesigns(masks, start)
        rng, base_rng = np.random.default_rng(20261102), np.random.default_rng(20261119)
        moving = 0
        for number in range(dm.DESIGNS):
            _stairs, design, sense = generator.make(rng)
            base = np.where(base_rng.random(start.shape) < 0.4, start - 3.0, np.nan)
            plain = verification.check(start, design)
            based = verification.check_with_base(start, design, base)
            with self.subTest(diseno=number, sentido=sense):
                self.assertFalse(based.fails)
                assert_same_with_base(self, plain, based)
                for total in based.totals:
                    if total.counts in (C.CUT_TERRAIN, C.CUT, C.FILL, C.ANY):
                        self.assertEqual(total.counted_m3, 0.0, total.code)
            moving += int(bool(np.any(np.abs(design - start) > dm.MIN_THICKNESS_M)))
        self.assertGreaterEqual(moving, 80, "la gran mayoría mueve tierra: la prueba no es vacía")

    def test_a_cell_in_the_base_changes_only_the_five_zones(self) -> None:
        """RF-012-30: con dientes, un diseño que deja **una** celda 1 m por debajo de la partida en la cuneta («sin corte», de
        la 012) no cumple sin base y con una base que no la cubre, y cumple —con 4 m³ de corte de acopios— con una base 2 m por
        debajo de la partida en esa celda; en la torre (intocable), no cumple con base tampoco."""
        masks = access.load_masks(self.project, self.v1.uid)
        verification = _WithBase(masks)
        start = dm.terrain_of(masks.grid.shape)
        for code, exempt in (("cuneta", True), ("torre", False)):
            cells = np.argwhere(verification.exclusive(code, "cut"))
            row, col = (int(value) for value in cells[len(cells) // 2])
            dug = start.copy()
            dug[row, col] -= 1.0
            covering = np.full(start.shape, np.nan)
            covering[row, col] = start[row, col] - 2.0
            area = masks.grid.cell_area
            with self.subTest(zona=code):
                self.assertEqual([t.code for t in verification.check(start, dug).totals if t.verdict is V.FAILS], [code])
                other = np.full(start.shape, np.nan)
                other[0, 0] = start[0, 0] - 2.0
                self.assertEqual([t.code for t in verification.check_with_base(start, dug, other).totals
                                  if t.verdict is V.FAILS], [code])
                fails = [t.code for t in verification.check_with_base(start, dug, covering).totals if t.verdict is V.FAILS]
                self.assertEqual(fails, [] if exempt else [code])
                if exempt:
                    zone = verification.check_with_base(start, dug, covering).zone(code)
                    self.assertEqual((zone.counted_m3, zone.stockpile_cut_m3), (0.0, area))


class QuarryMasksWithBaseTest(qfx.QuarryProjectCase):
    """RF-012-30: los diseños sintéticos de la 013 (los que usa la 014 para sus superficies) sobre las máscaras de V01 de la
    cantera de la 014 (límite legal con 5 m hacia dentro, perímetro, torre y «sin corte»; rejilla de 2 m) dan lo mismo con una
    base de acopios que sin ella."""

    STEP_M = qfx.COARSE_STEP_M
    DESIGNS = 24

    def test_the_designs_of_the_quarry_verify_the_same_with_a_base(self) -> None:
        """RF-012-30, RF-012-22 (DIFF-012 §3 y §4 (c)): 24 diseños sobre las máscaras de V01 de la cantera de la 014 no
        incumplen ningún recinto y dan los mismos totales, grupos y rejilla de incumplimientos con una base de acopios que
        sin ella."""
        masks = self.masks()
        verification = _WithBase(masks)
        start = qfx.terrain(self.grid)
        generator = dm.RandomDesigns(masks, start)
        rng, base_rng = np.random.default_rng(20261120), np.random.default_rng(20261121)
        moving = 0
        for number in range(self.DESIGNS):
            _stairs, design, sense = generator.make(rng)
            base = np.where(base_rng.random(start.shape) < 0.4, start - 3.0, np.nan)
            plain = verification.check(start, design)
            based = verification.check_with_base(start, design, base)
            with self.subTest(diseno=number, sentido=sense):
                self.assertFalse(based.fails)
                assert_same_with_base(self, plain, based)
            moving += int(bool(np.any(np.abs(design - start) > dm.MIN_THICKNESS_M)))
        self.assertGreaterEqual(moving, self.DESIGNS // 2)
