# SPDX-License-Identifier: GPL-3.0-or-later
"""Hito H2 de los acopios con proyecto (spec 016, T22; HU-016-2; CE-016-03 sin su última frase, CE-016-04 con un relleno de la 015 como lo
apoyado, E2 y E3 sin pantalla; RF-016-11, RF-016-13 a RF-016-16, RF-015-15, RF-015-17; plan 016 §5.4 A6 a A9, §5.7 P-9, §7.1 y §7.5). Va al paso
«hito» de ``check.py --completo`` (P-13: la rejilla de 2 m con proyecto); lo del dominio, con sus cuentas a mano, está en ``test_removal_*.py``.

**El acopio de 12 m** de ``tests.support.stockpile_data`` (:data:`~tests.support.stockpile_data.TALL`: pie de 30 m de semilado, cima de 6 m y
12 m de altura, 17.864 m³ por encima de su plano; trasladado al centro (150, 160) m de la cantera, dentro del dominio por defecto de las
máscaras) sobre **un plano de 3,76 %** (el del acopio 7 de la V10), como superficie de V01, con una marca que lo rodea y la detección ``Acopios``
(``STK-001``, **de la versión**; con la detección **del proyecto**, que es la normal, :class:`TallProjectButtressTest`, T45); y un **relleno de la 015** (la plataforma «en corte y relleno» ``PLT-001``, 70 × 70 m a 1 m por encima de la cima) que lo cubre y
sale por todos lados: lo apoyado (RF-016-14) y el relleno que queda **junto** al acopio (CE-016-03: la pared del error 47).

Las cuentas son **a mano**, hechas aparte con bucles de Python sobre los ficheros que escribió la operación (``design_oracles``: la
retirada de A6 celda a celda, con la envolvente de fuerza bruta, y la pared de A8 pareja a pareja) y con el montón calculado con su fórmula
(``Mound.heights``), no con el código que se prueba.

- :class:`TallRemovalTest` (CE-016-03 y CE-016-04, **en orden**): la detección a mano, el relleno, la lista única antes de calcular, la
  negativa a crear sin confirmarla, la retirada (la superficie celda a celda, sin bajar de la base ni pared de más del ángulo de
  transición, y retirado + apoyado + transición + no retirado = lo que había sobre la base), «apoyo retirado» fuera de «Recalcular lo
  obsoleto» (cómo se lee), el relleno **después** de la retirada solo obsoleto y la partida de otra versión.
- :class:`TallAsPlatformTest` (CE-016-03, E3): retirado «como plataforma»: la huella entera en el plano de su base, el eje de borde a
  borde y las cifras iguales al cálculo a mano.
- :class:`TallButtressTest` (CE-016-04 con **el contrafuerte real**, E2; T27): la cadena detección (**de la versión**) → contrafuerte →
  retirada con **el contrafuerte de la T26** (coronación a 135 m sobre la cima del acopio de 12 m, el perfil ``EXPL_10_60_6`` escrito en el
  proyecto) en lugar del relleno de la 015: se apoya en el acopio, **una sola lista** antes de retirarlo, «apoyo retirado» tras crear la
  retirada, «Recalcular lo obsoleto» sin recalcularlo, el contrafuerte **después** de la retirada solo obsoleto y lo que sigue a la
  orden sin fallar.
- :class:`TallProjectButtressTest` (CE-016-04 con **la detección del proyecto** y el contrafuerte real, E2; T45, hallazgos S-1 y B-1): lo mismo con el
  levantamiento alto **en el proyecto** y la detección **del proyecto** (la normal: detectar sobre el terreno): el contrafuerte se apoya en el acopio
  del proyecto, y creada la retirada **queda en «apoyo retirado»** (con su causa y sin recalcularse); el contrafuerte después de la retirada, solo obsoleto.
- :class:`TallProjectChainTest` (CE-016-04, E2; T45): la detección del proyecto, **un relleno de la 015 y el contrafuerte real encima**: lo que se apoyaba en
  el acopio son los dos, en una sola lista, y creada la retirada **los dos** quedan en «apoyo retirado», sin recalcularse.
"""

from __future__ import annotations

import json
import math
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_oracles as oracles
from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import milestone_buttress_operation as btr
from tests.unit.design import milestone_removal_platform as aspl
from tests.unit.design import milestone_stockpile_detection as ops
from tests.unit.design import milestone_stockpile_prepare as tp
from tests.unit.design import milestone_stockpile_supports as sup
from tests.unit.design import test_platform_operation as platform_ops
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design import test_removal_operation as rem

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
removal = import_geoblender("design.removal")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
supported_store = import_geoblender("design.supported_store")

State = entities.EntityState
GRID = sup.GRID
STEP_M = GRID.dx
CELL_M2 = STEP_M * STEP_M
USER = sup.USER
OFFSET_M = (100.0, 100.0)
"""Lo que se traslada el acopio de 12 m del banco de pruebas (centro en (50, 60)) a la cantera: su centro queda en (150, 160) m, con el pie
de 120 a 180 m y 190 de norte: dentro del dominio por defecto de las máscaras de V01 (las filas 31 a 168 y las columnas 21 a 178)."""
TALL = sdata.TALL.moved(*OFFSET_M)
GRADIENT = 0.0376
"""La pendiente del plano de la base: el 3,76 % del acopio 7 de la V10."""
PLANE = sdata.plane(math.degrees(math.atan(GRADIENT)), pivot=(150.0, 160.0), z_pivot=115.0)
THRESHOLD_M = 0.3
"""El umbral de la huella de la 011 (``res.anthropic_presence_m``, D-17), con el que se cuenta a mano."""
ANGLE_DEG = 35.0
"""El ángulo de transición de referencia de D-2 (35°, un dato de ENTRADA de la prueba)."""
MARK_BOX_M = (115.0, 125.0, 185.0, 195.0)
"""La marca del acopio (local): 70 × 70 m, que **rodea** el pie de 60 m (una marca orientativa dentro del pie, de 50 m, no converge en las 6 vueltas de D-3
con una cara de 26,6°: la corona queda en la ladera y el plano sale torcido; ``des.stockpile_not_converged``)."""
MARGIN_M = 5.0
PAD = 3
"""Las celdas que se toman a cada lado de la huella para comparar con el cálculo a mano (el anillo de semillas y las parejas del borde)."""
SURVEY_NAME = "Levantamiento alto"
SURVEY = provenance.dataset_name(provenance.STOCKPILE_SURFACE_GRID, SURVEY_NAME)
MARKS_LAYER = "gis_fea_marca_alta"
AXES_LAYER = "gis_fea_relleno_alto"
KEY = "Acopio alto"
OVER = "Sobre el acopio alto"
REMOVAL = "Retirada del acopio alto"
AFTER = "Después de la retirada"
OVER_SURFACE = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, OVER)
BASE = provenance.dataset_name("stb", "Acopios mineral")
DETECTED = provenance.dataset_name(provenance.STOCKPILE_SURFACE_GRID, "Acopios")
AFTER_UP_M = 2.0
"""Lo que se sube el relleno que se hace **después** de la retirada, sobre el mismo sitio que ``PLT-001``."""
CROWNS_LAYER = "gis_fea_coronacion_alta"
CROWN_ZONE = "Cima del acopio alto"
CROWN_BOX_M = (138.0, 148.0, 162.0, 172.0)
"""La zona de coronación (local): 24 × 24 m sobre la cima del acopio de 12 m (el centro, (150, 160), y la cima de 12 m de lado)."""
CROWN_M = 135.0
"""La cota de coronación: el ancla de ``EXPL_10_60_6`` (125 m) más un banco (10 m), por encima de la cima del acopio (≈ 127 m)."""
GUARD_M = 10.0
BUTTRESS = "Contrafuerte del acopio alto"
BUTTRESS_AFTER = "Contrafuerte después de la retirada"
BUTTRESS_SURFACE = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, BUTTRESS)


def tall_survey() -> np.ndarray:
    """La superficie de V01: el plano de 3,76 % más el acopio de 12 m (su altura es sobre el plano), calculada con su fórmula."""
    return PLANE.values(GRID) + sdata.mound_heights(GRID.shape, GRID.dx, (TALL,))


def cell_centre(row: int, col: int) -> tuple[float, float]:
    """El centro (local, desde el suroeste) de la celda ``(row, col)`` de la rejilla."""
    return (col + 0.5) * STEP_M, (GRID.nrows - row - 0.5) * STEP_M


def hand_footprint() -> set[tuple[int, int]]:
    """A mano: las celdas con el centro dentro del pie del acopio y más de 0,3 m sobre el plano (un bucle, no el código)."""
    left, bottom, right, top = TALL.foot_box
    found = set()
    for row in range(GRID.nrows):
        for col in range(GRID.ncols):
            x, y = cell_centre(row, col)
            if left < x < right and bottom < y < top and float(TALL.heights(x, y)) > THRESHOLD_M:
                found.add((row, col))
    return found


def level_over_the_top() -> float:
    """La rasante del relleno: la cota más alta de la cima redondeada hacia arriba al metro, más uno (como la de la T15)."""
    return float(math.ceil(float(tall_survey()[sdata.in_box(TALL.foot_box, GRID)].max()))) + 1.0


def axes_layer(level: float) -> Any:
    """Los ejes de los dos rellenos (arrays nuevos): el que cubre el acopio (70 m de eje y 70 de ancho, sobre el pie de 60 m) y el que se hace
    **después** de la retirada sobre el mismo sitio y 2 m más alto."""
    path = ((115.0, 160.0), (185.0, 160.0))
    return qfx.LayerData(
        AXES_LAYER, "line", tuple(((cfx.absolute(path),),) for _ in range(2)), (OVER, AFTER),
        {"ancho": (70.0, 70.0), "cota_inicial": (level, level + AFTER_UP_M), "pendiente": (0.0, 0.0)})


def over(name: str, **changes: Any) -> Any:
    """El relleno ``name`` de la capa de ejes, «en corte y relleno», del levantamiento alto (de V01)."""
    base: dict[str, Any] = {"fields": prep.line_fields(AXES_LAYER), "start": SURVEY, "mode": model.PlatformMode.CUT_FILL}
    return prep.request(name, **{**base, **changes})


def overlap(low: float, high: float, floor: float, ceiling: float) -> float:
    """La longitud de ``[low, high]`` que cae en ``[floor, ceiling]``."""
    return max(min(high, ceiling) - max(low, floor), 0.0)


class TallWorld(rem.RemovalCase):
    """El proyecto de la cantera con el levantamiento alto como superficie de V01, su capa de marcas, la detección ``Acopios`` (``STK-001``)
    y la capa de ejes del relleno; las ayudas para comparar con el cálculo a mano sobre los ficheros."""

    level: ClassVar[float]

    @classmethod
    def write_survey(cls) -> None:
        """Escribe el levantamiento alto como dato de V01 (:data:`SURVEY`) con el escritor de versión."""
        raster = gis.Raster(cls.grid, tall_survey(), sdata.CRS, sdata.VERTICAL)
        begun = store._start(cls.project, tp.PROBE, SURVEY_NAME, cls.v1, None, {"name": SURVEY_NAME}, (), (), None)
        cls.clock.advance(minutes=1)
        with store.design_writer(cls.project, tp.PROBE, SURVEY_NAME, version=cls.v1.uid) as writer:
            tp.drive(writer.grid_steps(provenance.STOCKPILE_SURFACE_GRID, raster))
            writer.commit(begun, message="Superficie de V01 del hito H2")
        cls.clock.advance(minutes=1)

    @classmethod
    def build_world(cls) -> None:
        """El levantamiento, la marca (de 70 × 70 m, que rodea el pie de 60 m), la detección y la capa de ejes."""
        cls.level = level_over_the_top()
        cls.write_survey()
        mark = sdata.FieldsLayer(MARKS_LAYER, "polygon", (((cfx.rectangle(*MARK_BOX_M),),),), (KEY,),
                                 {"margen": (MARGIN_M,), "material": ("mineral",)})
        sdata.write_layer(cls.project, cls.clock, mark)
        cls.create(tp.request("Acopios", layer=MARKS_LAYER, surface=SURVEY))
        qfx.write_feature_layer(cls.project, cls.clock, axes_layer(cls.level))
        cls.clock.advance(minutes=1)

    def window(self) -> tuple[slice, slice]:
        """La ventana de la comparación: la huella del acopio con ``PAD`` celdas a cada lado."""
        rows, cols = self.cells_of(KEY)
        return (slice(int(rows.min()) - PAD, int(rows.max()) + PAD + 1), slice(int(cols.min()) - PAD, int(cols.max()) + PAD + 1))

    def footprint_mask(self) -> np.ndarray:
        """La huella del acopio como máscara de la rejilla entera."""
        mask = np.zeros(GRID.shape, dtype=bool)
        rows, cols = self.cells_of(KEY)
        mask[rows, cols] = True
        return mask

    def hand_retirement(self, start_name: str, *, angle_deg: float = ANGLE_DEG) -> tuple[Any, tuple[slice, slice]]:
        """La retirada del acopio desde ``start_name`` **a mano** (:func:`~tests.support.design_oracles.hand_removal`), sobre su ventana: la
        superficie de partida, la base y la superficie con que se detectó **leídas de los ficheros** y el dominio de las máscaras."""
        window = self.window()
        domain = self.masks_v1.default_domain()[window]
        footprint = self.footprint_mask()[window]
        base, detected = self.grid_of(BASE)[window], self.grid_of(DETECTED)[window]
        found = oracles.hand_removal(self.grid_of(start_name)[window].tolist(), base.tolist(), detected.tolist(), footprint.tolist(),
                                     domain.tolist(), step=STEP_M, tan=math.tan(math.radians(angle_deg)), metric="exact")
        return found, window


class TallRemovalTest(TallWorld):
    """CE-016-03 (con proyecto) y CE-016-04 (con un relleno de la 015), **en orden** (``test_a`` a ``test_h``): cada prueba parte de lo que
    dejó la anterior; la detección ``STK-001`` (V01), el relleno ``PLT-001`` y la retirada ``RMV-001`` del acopio de 12 m."""

    over_m3: ClassVar[float]
    listed: ClassVar[tuple[Any, ...]]
    calculation: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build_world()

    def test_a_the_detection_is_the_footprint_the_volume_and_the_plane_done_by_hand(self) -> None:
        """RF-016-02, RF-016-09 (la base del hito): la detección real del acopio de 12 m sobre el plano de 3,76 % da **la huella** del cálculo
        a mano (las celdas con más de 0,3 m sobre el plano), su **volumen** (``Σ altura · 4 m²``, con la altura de la fórmula del montón) a ≤
        10⁻⁹ relativo y un **plano de base** igual al sintético a ≤ 10⁻⁶ m en toda la huella (D-11)."""
        rows, cols = self.cells_of(KEY)
        found = {(int(row), int(col)) for row, col in zip(rows, cols, strict=True)}
        wanted = hand_footprint()
        self.assertEqual(found, wanted)
        volume = math.fsum(float(TALL.heights(*cell_centre(row, col))) * CELL_M2 for row, col in sorted(wanted))
        self.assertGreater(volume, 17_000.0, "el acopio de 12 m (17.864 m³ en celdas de 1 m)")
        (row,) = self.table("stk")
        self.assertEqual(row["key"], KEY)
        (found_volume,) = [value for key, scope, value in self.figures_of(self.uid_of("STK-001"))
                           if key == "des.stk_volume_m3" and json.loads(scope).get("stockpile") == KEY]
        self.assertRelative(found_volume, volume, "volumen a mano")
        base = self.grid_of(BASE)[rows, cols]
        wanted_base = np.array([PLANE.at(*cell_centre(int(r), int(c))) for r, c in zip(rows, cols, strict=True)])
        self.assertLessEqual(float(np.max(np.abs(base - wanted_base))), 1e-6, "el plano de base, a ≤ 10⁻⁶ m")
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("STK-001").record.state, State.CURRENT)

    def test_b_a_fill_of_the_015_over_the_stockpile_rests_on_it_with_its_volume_by_hand(self) -> None:
        """RF-016-14, RF-015-15 (A13), CE-016-04: el relleno ``PLT-001`` (la plataforma «en corte y relleno» de la 015, a 1 m sobre la cima, que
        cubre el pie y sale por todos lados) se apoya **en el acopio** por su clave, con un volumen igual al cálculo a mano
        (``Σ (relleno − máx(partida, acopio))·4 m²`` sobre las celdas de su huella que pasan del espesor mínimo, **de los ficheros**) a ≤ 10⁻⁹
        relativo."""
        self.made(over(OVER))
        uid = self.uid_of("PLT-001")
        found = self.supported_of(uid)
        self.assertEqual(list(found), [("STK-001", KEY)], "una sola cifra, la del acopio")
        rows, cols = self.cells_of(KEY)
        top = self.grid_of(OVER_SURFACE)[rows, cols]
        start, ground = self.grid_of(SURVEY)[rows, cols], self.grid_of(DETECTED)[rows, cols]
        thick = top - np.maximum(start, ground)
        volume = math.fsum(float(value) for value in thick[thick > sup.THICKNESS_M]) * CELL_M2
        type(self).over_m3 = found[("STK-001", KEY)]
        self.assertRelative(self.over_m3, volume, "lo apoyado, de los ficheros")
        hand = math.fsum(self.level - float(PLANE.at(*cell_centre(int(r), int(c)))) - float(TALL.heights(*cell_centre(int(r), int(c))))
                         for r, c in zip(rows, cols, strict=True)) * CELL_M2
        self.assertRelative(self.over_m3, hand, "lo apoyado, a mano (la rasante menos el acopio, plano incluido)")

    def test_c_what_rests_on_the_stockpile_is_one_list_before_calculating_and_is_not_removed_without_confirming_it(self) -> None:
        """RF-016-14, RF-015-17 (error 59; CE-016-04): retirar el acopio desde la superficie del relleno da **una sola lista** antes de calcular
        (el relleno, con su tipo y su volumen a mano), la misma que la del diálogo y que la que luego calcula la orden; el aviso de lo apoyado
        es el primero del resumen; calcular **no escribe nada**; «Crear» sin confirmarla se rechaza (``des.removal_resting_unconfirmed``)
        **sin escribir nada y sin cerrar el cálculo**."""
        asked = rem.asked(REMOVAL, KEY, start="entity:PLT-001", transition_deg=ANGLE_DEG)
        before = self.state()
        listed = supported_store.resting_preview(self.project, self.v1.uid, f"STK-001#{KEY}", "entity:PLT-001")
        self.assertEqual(self.state(), before, "la lista del diálogo solo lee")
        (row,) = listed
        self.assertEqual((row.name, row.op_type, row.entity, row.surface), (OVER, "des.platform", "PLT-001", OVER_SURFACE))
        self.assertRelative(row.volume_m3, self.over_m3, "el volumen de la lista, el de su cifra")
        type(self).listed = listed
        calculation = self.calculate(asked)
        type(self).calculation = calculation
        self.assertEqual(listed, calculation.entity.resting, "la lista del diálogo es la que calcula la orden")
        self.assertEqual([notice.code for notice in calculation.notices][:1], ["des.removal_resting"], "el aviso, el primero")
        self.assertTrue(calculation.needs_resting_confirmation)
        self.assertEqual({key: value for key, value in self.state().items() if key != "files"},
                         {key: value for key, value in before.items() if key != "files"}, "calcular no escribe")
        self.assertEqual(len(self.temporaries()), 1, "solo el temporal de la superficie")
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=USER)
        self.assertEqual(caught.exception.code, "des.removal_resting_unconfirmed")
        self.assertTrue(calculation.open, "sin cerrar el cálculo")
        self.assertEqual({key: value for key, value in self.state().items() if key != "files"},
                         {key: value for key, value in before.items() if key != "files"}, "el rechazo no escribe")

    def test_d_the_removal_leaves_no_wall_over_the_angle_never_goes_under_the_base_and_adds_up_to_what_there_was(self) -> None:
        """CE-016-03, RF-016-11, RF-016-13, RF-016-15 (error 47; con proyecto): con lo apoyado confirmado, la retirada del acopio de 12 m
        junto al relleno deja una superficie **igual celda a celda** (≤ 10⁻⁹ m) a la de la implementación independiente (la envolvente de
        fuerza bruta desde las celdas de fuera de la huella con 35° y la superficie ``mín(z, máx(base, envolvente))``); **ninguna celda
        de la huella baja de su base**; **ninguna pareja creada** pasa de 35° (ni siquiera con la tolerancia de cara: la comprobación va sin
        ella), y retirado + apoyado + transición + no retirado es lo que había sobre la base a ≤ 10⁻⁹ relativo; las cifras de la operación,
        iguales a las de a mano."""
        calculation, stored = self.make(rem.asked(REMOVAL, KEY, start="entity:PLT-001", transition_deg=ANGLE_DEG),
                                        confirm={"resting": True})
        uid = str(stored.handle.uid)
        hand, window = self.hand_retirement(OVER_SURFACE)
        surface = self.grid_of(provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, REMOVAL))
        start, base = self.grid_of(OVER_SURFACE), self.grid_of(BASE)
        self.assertLessEqual(float(np.max(np.abs(surface[window] - hand.surface))), 1e-9, "la superficie, celda a celda")
        outside = np.ones(GRID.shape, dtype=bool)
        outside[window] = False
        np.testing.assert_array_equal(surface[outside], start[outside], "fuera de la ventana, la superficie de partida bit a bit")
        mask = self.footprint_mask()
        self.assertTrue(np.all(surface[mask] >= np.minimum(start, base)[mask]), "ninguna celda baja de la base")
        self.assertGreater(float(np.min(surface[mask] - base[mask])), -1e-9)
        figures = self.figures_by_key(uid)
        for key, wanted in (("des.rmv_removed_m3", hand.removed), ("des.rmv_resting_m3", hand.resting),
                            ("des.rmv_transition_m3", hand.transition), ("des.rmv_kept_m3", hand.kept)):
            if wanted:
                self.assertRelative(figures[key], wanted, key)
            else:
                self.assertEqual(figures[key], 0.0, key)
        self.assertRelative(figures["des.rmv_transition_m2"], hand.transition_cells * CELL_M2, "área de la transición")
        total = math.fsum((figures["des.rmv_removed_m3"], figures["des.rmv_resting_m3"], figures["des.rmv_transition_m3"],
                           figures["des.rmv_kept_m3"]))
        self.assertRelative(total, hand.above, "retirado + apoyado + transición + no retirado = lo que había sobre la base")
        self.assertGreater(figures["des.rmv_resting_m3"], 0.0)
        self.assertGreater(figures["des.rmv_transition_m3"], 0.0, "el relleno que rodea el acopio deja una transición")
        self.assertLess(figures["des.rmv_resting_m3"], self.over_m3, "la transición se queda con parte del relleno que cubría el acopio")
        admitted = np.zeros(surface[window].shape, dtype=bool)
        for row, col in hand.admitted:
            admitted[row, col] = True
        wall = oracles.hand_wall(start[window].tolist(), surface[window].tolist(), admitted.tolist(), dx=STEP_M, dy=STEP_M,
                                 west=GRID.west + window[1].start * STEP_M, north=GRID.north - window[0].start * STEP_M,
                                 thickness=0.01, threshold=0.0, limit_deg=ANGLE_DEG + 1e-6)
        self.assertEqual(wall.stretches, (), "ninguna pared pasa del ángulo de transición")
        self.assertGreater(wall.pairs, 100, "se miró el borde entero")
        self.assertEqual(calculation.outcome.wall.stretches, (), "la pared que mide la orden, ninguna")
        self.assertFalse(calculation.needs_wall_confirmation)
        settings = json.loads(self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)[0][0])
        self.assertEqual(set(settings["removal_confirmed"]), {"resting"}, "solo lo apoyado se confirmó: no hay pared que confirmar")
        self.assertRelative(settings["removal_confirmed"]["resting"]["volume_m3"], self.over_m3, "los m³ confirmados")

    def test_e_the_fill_that_rested_on_the_stockpile_is_left_with_its_support_removed(self) -> None:
        """RF-015-17, RF-016-14, P-9 (CE-016-04): tras crear la retirada, ``PLT-001`` queda en **«apoyo retirado»** —con su causa, que nombra el
        acopio y la retirada— sin descartar nada; la detección y la retirada, al día."""
        states = {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}
        self.assertEqual(states, {"STK-001": State.CURRENT, "PLT-001": State.SUPPORT_REMOVED, "RMV-001": State.CURRENT})
        why = entities.stale_reason(self.project, self.v1.uid, "PLT-001")
        assert why is not None
        self.assertTrue(why.startswith("Apoyo retirado: "), why)
        for wanted in (KEY, REMOVAL):
            self.assertIn(wanted, why)
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)], "nada se descartó")
        (lost,) = entities.retired_supports(self.project, self.v1.uid)
        self.assertEqual((lost.entity, lost.name), ("PLT-001", OVER))
        self.assertTrue(lost.releasable)

    def entities_state(self, code: str) -> Any:
        return entities.registry(self.project, self.v1.uid).get(code).record.state

    def test_f_a_fill_made_after_the_removal_is_only_stale(self) -> None:
        """RF-015-17, CE-016-04: un relleno **después** de la retirada en la cadena (parte de su superficie), sobre el mismo sitio, aunque se apoye
        en el mismo acopio, **no pierde su apoyo** —la retirada no le quita nada— y, si cambia, **solo queda obsoleto** (con la causa de la
        008, no «apoyo retirado»)."""
        self.made(over(AFTER, start="entity:RMV-001"))
        self.assertEqual(self.entities_state("PLT-002"), State.CURRENT)
        self.change(design_params.entity_key("PLT-002", "start_level_m"), self.level + AFTER_UP_M + 1.0)
        self.assertEqual(self.entities_state("PLT-002"), State.STALE)
        self.assertEqual(self.entities_state("PLT-001"), State.SUPPORT_REMOVED)
        reason = entities.stale_reason(self.project, self.v1.uid, "PLT-002")
        assert reason is not None
        self.assertTrue(reason.startswith("Obsoleto"), reason)
        self.assertEqual([row.entity for row in entities.retired_supports(self.project, self.v1.uid)], ["PLT-001"])

    def test_g_recompute_stale_does_not_remake_it_and_this_is_how_it_reads(self) -> None:
        """RF-016-14, RF-015-17 (error 59; CE-016-04; la nota de la T39): con ``PLT-001`` obsoleta además de sin apoyo, «Recalcular lo obsoleto»
        **no la recalcula**: no escribe una operación ni un dato, y la unidad **sale ``FAILED``** (no ``REFUSED``: ``core`` solo rehúsa lo
        descartado) con el código ``core.recompute_failed`` y el motivo «espera una decisión» que nombra el acopio y la retirada; **lo que se lee**:
        una sola unidad fallida (la de ``PLT-001``) y ninguna hecha."""
        self.change(design_params.entity_key("PLT-001", "start_level_m"), self.level + 1.0)
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("PLT-001").record.state, State.SUPPORT_REMOVED)
        uid = self.uid_of("PLT-001")
        operations = self.query("SELECT COUNT(*) FROM gb_operation")
        datasets = self.query("SELECT COUNT(*) FROM gb_dataset")
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual(self.uid_of("PLT-001"), uid)
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_operation"), operations)
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_dataset"), datasets)
        mine = [result for result in outcome.results if uid in result.unit.operations]
        (result,) = mine
        self.assertIs(result.status, recompute_mod.UnitStatus.FAILED, "falla, no se rehúsa")
        self.assertEqual(result.code, "core.recompute_failed")
        text = result.text(language="es")
        assert text is not None
        for wanted in (KEY, REMOVAL, "decisión"):
            self.assertIn(wanted, text)
        self.assertEqual([item.status for item in outcome.results], [recompute_mod.UnitStatus.FAILED],
                         [(item.status, item.text()) for item in outcome.results])
        self.assertEqual(self.entities_state("PLT-001"), State.SUPPORT_REMOVED)

    def test_h_with_the_start_of_another_version_the_notice_names_that_surface(self) -> None:
        """RF-016-14, CE-016-04: con la superficie de partida **de otra versión** (el resultado del relleno de V01 visto desde V02), todo lo que
        tiene por encima de la superficie del acopio va a esa superficie **por su nombre**: una fila sin operación, con su volumen a mano, y el
        aviso nombra esa superficie."""
        rows, cols = self.cells_of(KEY)
        surface = self.grid_of(DETECTED)[rows, cols]
        item = removal.RemovedStockpile(KEY, KEY, rows.astype(np.int64) * GRID.ncols + cols, self.grid_of(BASE)[rows, cols], surface)
        found = removal.resting_on(self.project, self.v2.uid, item, OVER_SURFACE, detected_on=SURVEY)
        (row,) = found
        self.assertEqual((row.name, row.op_type, row.entity, row.operation_uid, row.surface), (OVER_SURFACE, None, None, None, OVER_SURFACE))
        self.assertRelative(row.volume_m3, self.over_m3, "a mano")
        (notice,) = removal.resting_notices(KEY, found)
        self.assertIn(OVER_SURFACE, notice.text("es"))
        self.assertIn("superficie de partida", row.text("es"))


class TallAsPlatformTest(TallWorld):
    """CE-016-03, RF-016-16, E3, **en orden** (``test_a`` a ``test_c``): el acopio de 12 m retirado «como plataforma» desde el relleno que lo cubre."""

    calculation: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build_world()
        cls.made(over(OVER))

    @classmethod
    def request(cls) -> Any:
        return aspl.of_stockpile("El acopio alto como plataforma", KEY, start="entity:PLT-001")

    def hand_axis(self) -> tuple[float, float, float, float, float, float]:
        """A mano: el centro de la huella (la media de los centros de sus celdas, locales), la dirección de máxima pendiente del plano y la menor y la
        mayor proyección **de las esquinas de todas sus celdas** sobre ella (m desde el centro)."""
        norm = math.hypot(PLANE.east_slope, PLANE.north_slope)
        ux, uy = PLANE.east_slope / norm, PLANE.north_slope / norm
        cells = sorted(hand_footprint())
        xs = [cell_centre(row, col)[0] for row, col in cells]
        ys = [cell_centre(row, col)[1] for row, col in cells]
        xc, yc = math.fsum(xs) / len(cells), math.fsum(ys) / len(cells)
        projections = [(corner_x - xc) * ux + (corner_y - yc) * uy
                       for row, col in cells for corner_x in (col * STEP_M, (col + 1) * STEP_M)
                       for corner_y in ((GRID.nrows - row - 1) * STEP_M, (GRID.nrows - row) * STEP_M)]
        return xc, yc, ux, uy, min(projections), max(projections)

    def test_a_the_whole_footprint_is_in_the_plane_of_its_base_and_the_axis_runs_from_edge_to_edge(self) -> None:
        """CE-016-03, RF-016-16, A9, E3: retirado «como plataforma» (calcular no escribe nada), **la huella entera queda en el plano de su base**
        (el sintético de 3,76 %) a ≤ 10⁻⁹ m, la rasante es la de ese plano (su pendiente, 3,76 %, y su cota en el origen del eje) y **el eje va de
        borde a borde** de la huella —de la menor a la mayor proyección de las esquinas de sus celdas— por su centro, en la dirección de máxima
        pendiente, a ≤ 10⁻⁹ relativo del cálculo a mano."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        calculation = platform_ops.finish(steps.platform_run(self.project, self.request(), masks=self.masks_v1, version=self.v1.uid))
        type(self).calculation = calculation
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))[1], before[1], "calcular no escribe")
        outcome = calculation.outcome
        window = outcome.footprint.window
        rows, cols = np.nonzero(outcome.footprint.cells)
        found = {(int(row + window[0].start), int(col + window[1].start)) for row, col in zip(rows, cols, strict=True)}
        self.assertEqual(found, hand_footprint(), "la huella de la plataforma son las celdas del acopio")
        wanted = np.array([PLANE.at(*cell_centre(row, col)) for row, col in sorted(found)])
        got = np.array([outcome.result[row - window[0].start, col - window[1].start] for row, col in sorted(found)])
        self.assertLessEqual(float(np.max(np.abs(got - wanted))), 1e-9, "la huella entera, en el plano de su base")
        self.assertLessEqual(abs(outcome.footprint.gradient_pct - 100.0 * GRADIENT) / (100.0 * GRADIENT), 1e-9, "3,76 %")
        xc, yc, ux, uy, t_min, t_max = self.hand_axis()
        (start, end) = outcome.footprint.axis.vertices
        for (x, y), t in ((start, t_min), (end, t_max)):
            self.assertLessEqual(abs((x - GRID.west) - (xc + t * ux)), 1e-6)
            self.assertLessEqual(abs((y - (GRID.north - GRID.nrows * GRID.dy)) - (yc + t * uy)), 1e-6)
        self.assertLessEqual(abs(math.hypot(end[0] - start[0], end[1] - start[1]) - (t_max - t_min)) / (t_max - t_min), 1e-9,
                             "de borde a borde")
        self.assertLessEqual(abs(outcome.footprint.start_level_m - float(PLANE.at(xc + t_min * ux, yc + t_min * uy))), 1e-9,
                             "la cota inicial, la del plano en el origen del eje")

    def test_b_the_figures_of_the_platform_and_of_the_removal_are_the_ones_done_by_hand(self) -> None:
        """CE-016-03, RF-016-13, RF-016-16, A9: las cifras de la retirada —retirado, apoyado, transición (0: toda la huella queda en su plano) y no
        retirado (0)— son iguales al cálculo a mano (``Σ`` de la longitud de la columna ``[plano, partida]`` a cada lado de la superficie con que
        se detectó) a ≤ 10⁻⁹ relativo y suman lo que había sobre la base; lo apoyado es el relleno y pide su confirmación."""
        calculation = self.calculation
        found = calculation.outcome.removal
        rows, cols = np.nonzero(calculation.outcome.footprint.cells)
        window = calculation.outcome.footprint.window
        removed, resting, above = [], [], []
        start, ground = self.grid_of(OVER_SURFACE), self.grid_of(DETECTED)
        for row, col in zip(rows + window[0].start, cols + window[1].start, strict=True):
            plane = float(PLANE.at(*cell_centre(int(row), int(col))))
            level, detected = float(start[row, col]), float(ground[row, col])
            removed.append(overlap(plane, level, -math.inf, detected))
            resting.append(overlap(plane, level, detected, math.inf))
            above.append(max(level - plane, 0.0))
        self.assertRelative(found.removed_m3, math.fsum(removed) * CELL_M2, "retirado")
        self.assertRelative(found.resting_m3, math.fsum(resting) * CELL_M2, "apoyado")
        self.assertRelative(found.above_base_m3, math.fsum(above) * CELL_M2, "lo que había sobre la base")
        self.assertEqual((found.transition_m3, found.transition_m2, found.kept_m3), (0.0, 0.0, 0.0))
        self.assertRelative(math.fsum((found.removed_m3, found.resting_m3)), found.above_base_m3, "suman lo que había sobre la base")
        self.assertTrue(calculation.needs_resting_confirmation)
        self.assertEqual([(row.name, row.entity) for row in calculation.entity.resting], [(OVER, "PLT-001")])

    def test_c_creating_it_registers_one_platform_and_leaves_the_fill_with_its_support_removed(self) -> None:
        """RF-016-16, RF-016-14, RF-015-02, P-9, E3: confirmado lo apoyado, «Crear» registra **una** operación ``des.platform`` (la plataforma con la
        huella como geometría, sin ninguna capa) que consume el acopio, con las cifras de la plataforma y de la retirada con el ámbito de la
        entidad; el relleno que se apoyaba queda en «apoyo retirado» y lo que sigue a la orden no falla."""
        calculation = self.calculation
        calculation.confirm_removal(resting=True)
        if calculation.needs_confirmation:
            calculation.confirm_counterslope()
        self.clock.advance(minutes=1)
        stored = calculation.create(decided_by=USER)
        uid = str(stored.handle.uid)
        self.assertEqual(self.query("SELECT op_type, scope, status FROM gb_operation WHERE uid = ?", uid), [("des.platform", "version", "done")])
        self.assertEqual([item for item in self.inputs_of(uid) if item[0] == "removed_stockpile"],
                         [("removed_stockpile", sup.TABLE), ("removed_stockpile", BASE), ("removed_stockpile", DETECTED)])
        self.assertFalse([role for role, _name in self.inputs_of(uid) if role in ("entity_layer", "entity_axis_layer")], "ninguna capa")
        figures = self.figures_by_key(uid)
        self.assertEqual(figures["des.rmv_removed_m3"], calculation.outcome.removal.removed_m3)
        self.assertEqual(figures["des.rmv_transition_m3"], 0.0)
        states = {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}
        self.assertEqual(states["PLT-001"], State.SUPPORT_REMOVED)
        self.assertEqual(states["PLT-002"], State.CURRENT)
        chain = ops.last(import_geoblender("design.entity_store").after_entity_change(self.project, self.v1.uid))
        self.assertIsNone(chain.failure, None if chain.failure is None else chain.failure.reason)
        self.assertEqual(self.temporaries(), [])


def crown(name: str = BUTTRESS, **changes: Any) -> Any:
    """La petición de un contrafuerte con la zona de coronación de la capa :data:`CROWNS_LAYER` (sobre la cima del acopio alto), el perfil
    ``EXPL_10_60_6``, la coronación a 135 m y, porque protege por defecto (D-1), su resguardo, desde el levantamiento de V01."""
    base: dict[str, Any] = {"fields": model.ButtressFields(layer=CROWNS_LAYER, crown_field="cota"), "feature": CROWN_ZONE, "start": SURVEY,
                            "profile": btr.PROFILE, "crown_m": CROWN_M, "guard_m": GUARD_M}
    return model.ButtressRequest(name=name, **{**base, **changes})


class TallButtressTest(TallWorld):
    """CE-016-04 con **el contrafuerte real** y E2 (``test_a`` a ``test_g``, **en orden**; T27): la detección ``STK-001`` (V01), el
    contrafuerte ``BTR-001`` de la zona de coronación sobre la cima del acopio de 12 m y la retirada ``RMV-001`` del acopio desde la
    superficie del contrafuerte. Lo de la retirada en sí (la superficie celda a celda, la pared, la transición) es de
    :class:`TallRemovalTest`; aquí, **la cadena** con el tipo nuevo."""

    over_m3: ClassVar[float]
    listed: ClassVar[tuple[Any, ...]]

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return (*super().definitions(), *btr.buttress_definitions())

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        btr.write_profile(cls)
        cls.build_world()
        zone = sdata.FieldsLayer(CROWNS_LAYER, "polygon", (((cfx.rectangle(*CROWN_BOX_M),),),), (CROWN_ZONE,), {"cota": (CROWN_M,)})
        sdata.write_layer(cls.project, cls.clock, zone)
        cls.clock.advance(minutes=1)

    @classmethod
    def make_buttress(cls, asked: Any) -> tuple[Any, Any]:
        """«Calcula» y «crea» el contrafuerte ``asked`` en V01 (un minuto después de lo anterior): la ``Calculation`` y lo guardado."""
        cls.clock.advance(minutes=1)
        calculation = ops.last(steps.buttress_run(cls.project, asked, masks=cls.masks_v1, version=cls.v1.uid))
        stored = calculation.create(decided_by=USER)
        cls.clock.advance(minutes=1)
        return calculation, stored

    def entity_state(self, code: str) -> Any:
        return entities.registry(self.project, self.v1.uid).get(code).record.state

    def test_a_a_buttress_over_the_stockpile_rests_on_it_with_its_volume_by_hand(self) -> None:
        """RF-016-14, RF-016-17, RF-015-15 (A13), CE-016-04: el contrafuerte de la T26 —la zona de coronación de 24 × 24 m sobre la cima del
        acopio de 12 m, coronación a 135 m— se apoya **en el acopio** por su clave, con **una sola cifra** (``("STK-001", clave)``) cuyo valor
        es el cálculo a mano (``Σ (contrafuerte − máx(partida, acopio))·4 m²`` sobre las celdas de su huella que pasan del espesor mínimo,
        **de los ficheros**) a ≤ 10⁻⁹ relativo; sube solo sobre parte de su huella (en las caras bajas del acopio, de 26,6°, el levantamiento
        queda por encima del talud del perfil)."""
        calculation, stored = self.make_buttress(crown())
        self.assertEqual(calculation.entity.code, "BTR-001")
        uid = self.uid_of("BTR-001")
        self.assertEqual(uid, str(stored.handle.uid))
        found = self.supported_of(uid)
        self.assertEqual(list(found), [("STK-001", KEY)], "una sola cifra, la del acopio")
        rows, cols = self.cells_of(KEY)
        top = self.grid_of(BUTTRESS_SURFACE)[rows, cols]
        start, ground = self.grid_of(SURVEY)[rows, cols], self.grid_of(DETECTED)[rows, cols]
        thick = top - np.maximum(start, ground)
        self.assertTrue(np.all(top >= start), "un contrafuerte no corta ninguna celda")
        volume = math.fsum(float(value) for value in thick[thick > sup.THICKNESS_M]) * CELL_M2
        type(self).over_m3 = found[("STK-001", KEY)]
        self.assertRelative(self.over_m3, volume, "lo apoyado, de los ficheros")
        self.assertGreater(int(np.count_nonzero(thick > sup.THICKNESS_M)), 0, "sube sobre parte de la huella del acopio")
        self.assertEqual(self.entity_state("BTR-001"), State.CURRENT)

    def test_b_what_rests_on_the_stockpile_is_one_list_before_calculating_and_is_not_removed_without_confirming_it(self) -> None:
        """RF-016-14, RF-015-17 (error 59; CE-016-04): retirar el acopio desde la superficie del contrafuerte da **una sola lista** antes de
        calcular (el contrafuerte, con su tipo ``des.buttress`` y su volumen a mano), la misma que la del diálogo y que la que luego calcula la
        orden; el aviso de lo apoyado es el primero del resumen y sale **una vez**; calcular **no escribe nada**; «Crear» sin confirmarla se
        rechaza (``des.removal_resting_unconfirmed``) **sin escribir nada y sin cerrar el cálculo**."""
        asked = rem.asked(REMOVAL, KEY, start="entity:BTR-001", transition_deg=ANGLE_DEG)
        before = self.state()
        listed = supported_store.resting_preview(self.project, self.v1.uid, f"STK-001#{KEY}", "entity:BTR-001")
        self.assertEqual(self.state(), before, "la lista del diálogo solo lee")
        (row,) = listed
        self.assertEqual((row.name, row.op_type, row.entity, row.surface), (BUTTRESS, "des.buttress", "BTR-001", BUTTRESS_SURFACE))
        self.assertRelative(row.volume_m3, self.over_m3, "el volumen de la lista, el de su cifra")
        type(self).listed = listed
        calculation = self.calculate(asked)
        self.assertEqual(listed, calculation.entity.resting, "la lista del diálogo es la que calcula la orden")
        codes = [notice.code for notice in calculation.notices]
        self.assertEqual(codes.count("des.removal_resting"), 1, "una sola vez")
        self.assertEqual(codes[:1], ["des.removal_resting"], "el aviso, el primero")
        self.assertTrue(calculation.needs_resting_confirmation)
        self.assertEqual({key: value for key, value in self.state().items() if key != "files"},
                         {key: value for key, value in before.items() if key != "files"}, "calcular no escribe")
        self.assertEqual(len(self.temporaries()), 1, "solo el temporal de la superficie")
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=USER)
        self.assertEqual(caught.exception.code, "des.removal_resting_unconfirmed")
        self.assertTrue(calculation.open, "sin cerrar el cálculo")
        self.assertEqual({key: value for key, value in self.state().items() if key != "files"},
                         {key: value for key, value in before.items() if key != "files"}, "el rechazo no escribe")
        calculation.discard()
        self.assertEqual(self.temporaries(), [])

    def test_c_the_removal_is_created_once_what_rests_on_it_is_confirmed(self) -> None:
        """RF-016-11, RF-016-14, RF-015-02 (CE-016-04): con lo apoyado confirmado la retirada del acopio desde la superficie del contrafuerte
        se crea; la confirmación queda en los ajustes de la operación (los m³ de la lista, de quién y cuándo) y la retirada deja lo retirado
        y lo apoyado (el contrafuerte que cubría el acopio: más de 0 m³)."""
        calculation, stored = self.make(rem.asked(REMOVAL, KEY, start="entity:BTR-001", transition_deg=ANGLE_DEG), confirm={"resting": True})
        uid = str(stored.handle.uid)
        figures = self.figures_by_key(uid)
        self.assertGreater(figures["des.rmv_resting_m3"], 0.0)
        self.assertGreater(figures["des.rmv_removed_m3"], 0.0)
        settings = json.loads(self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)[0][0])
        self.assertEqual(set(settings["removal_confirmed"]), {"resting"})
        self.assertRelative(settings["removal_confirmed"]["resting"]["volume_m3"], self.over_m3, "los m³ confirmados")
        self.assertIn("RMV-001", [entry.record.code for entry in entities.registry(self.project, self.v1.uid)])
        self.assertFalse(calculation.open)

    def test_d_the_buttress_is_left_with_its_support_removed_and_nothing_is_discarded(self) -> None:
        """RF-015-17, RF-016-14, P-9 (CE-016-04): tras crear la retirada, ``BTR-001`` queda en **«apoyo retirado»** —con su causa, que nombra el
        acopio y la retirada— sin descartar nada; la detección y la retirada, al día."""
        states = {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}
        self.assertEqual(states, {"STK-001": State.CURRENT, "BTR-001": State.SUPPORT_REMOVED, "RMV-001": State.CURRENT})
        why = entities.stale_reason(self.project, self.v1.uid, "BTR-001")
        assert why is not None
        self.assertTrue(why.startswith("Apoyo retirado: "), why)
        for wanted in (KEY, REMOVAL):
            self.assertIn(wanted, why)
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)], "nada se descartó")
        (lost,) = entities.retired_supports(self.project, self.v1.uid)
        self.assertEqual((lost.entity, lost.name), ("BTR-001", BUTTRESS))
        self.assertTrue(lost.releasable)

    def test_e_a_buttress_made_after_the_removal_is_only_stale(self) -> None:
        """RF-015-17, CE-016-04: un contrafuerte **después** de la retirada en la cadena (parte de su superficie), sobre el mismo sitio, aunque
        se apoye en el mismo acopio, **no pierde su apoyo** —la retirada no le quita nada— y, si cambia (otra coronación del ancla), **solo
        queda obsoleto** (con la causa de la 008, no «apoyo retirado»)."""
        self.make_buttress(crown(BUTTRESS_AFTER, start="entity:RMV-001"))
        self.assertEqual(self.entity_state("BTR-002"), State.CURRENT)
        self.change(design_params.entity_key("BTR-002", "crown_m"), CROWN_M + 10.0)
        self.assertEqual(self.entity_state("BTR-002"), State.STALE)
        self.assertEqual(self.entity_state("BTR-001"), State.SUPPORT_REMOVED)
        reason = entities.stale_reason(self.project, self.v1.uid, "BTR-002")
        assert reason is not None
        self.assertTrue(reason.startswith("Obsoleto"), reason)
        self.assertEqual([row.entity for row in entities.retired_supports(self.project, self.v1.uid)], ["BTR-001"])

    def test_f_recompute_stale_does_not_remake_it_and_this_is_how_it_reads(self) -> None:
        """RF-016-14, RF-015-17 (error 59; CE-016-04; la nota de la T39): con ``BTR-001`` obsoleta además de sin apoyo, «Recalcular lo
        obsoleto» **no la recalcula**: no escribe una operación ni un dato, y la unidad **sale ``FAILED``** (no ``REFUSED``: ``core`` solo
        rehúsa lo descartado) con el código ``core.recompute_failed`` y el motivo «espera una decisión» que nombra el acopio y la retirada;
        **lo que se lee**: una sola unidad fallida (la de ``BTR-001``), ninguna hecha, y **ni siquiera la del contrafuerte que la sigue** (la
        retirada y el contrafuerte de después dependen de su superficie, así que esperan a que se resuelva)."""
        self.change(design_params.entity_key("BTR-001", "crown_m"), CROWN_M + 10.0)
        self.assertEqual(self.entity_state("BTR-001"), State.SUPPORT_REMOVED)
        uid = self.uid_of("BTR-001")
        operations = self.query("SELECT COUNT(*) FROM gb_operation")
        datasets = self.query("SELECT COUNT(*) FROM gb_dataset")
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual(self.uid_of("BTR-001"), uid)
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_operation"), operations)
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_dataset"), datasets)
        (result,) = [result for result in outcome.results if uid in result.unit.operations]
        self.assertIs(result.status, recompute_mod.UnitStatus.FAILED, "falla, no se rehúsa")
        self.assertEqual(result.code, "core.recompute_failed")
        text = result.text(language="es")
        assert text is not None
        for wanted in (KEY, REMOVAL, "decisión"):
            self.assertIn(wanted, text)
        self.assertEqual([item.status for item in outcome.results], [recompute_mod.UnitStatus.FAILED],
                         [(item.status, item.text()) for item in outcome.results])
        self.assertEqual(self.entity_state("BTR-001"), State.SUPPORT_REMOVED)

    def test_g_the_buttress_declares_no_cut_on_its_crown_zone_and_what_follows_the_order_does_not_fail(self) -> None:
        """RF-015-10, RF-015-12, P-8, H-6, CE-016-04 (E2): lo que sigue a las órdenes (``after_entity_change``: declarar y recompilar las
        máscaras) no falla en una versión con la detección, el contrafuerte **sin apoyo** (que protegía y sigue declarando), la retirada y el
        contrafuerte de después: declara «sin corte» **sobre la zona de coronación** de cada uno (el polígono de la capa, no el de su
        huella) con su resguardo."""
        chain = ops.last(import_geoblender("design.entity_store").after_entity_change(self.project, self.v1.uid))
        self.assertIsNone(chain.failure, None if chain.failure is None else chain.failure.reason)
        declared = import_geoblender("core.constraints.declared")
        with self.project.read() as conn:
            found = {item.entity_code: item for item in declared.read_in_version(conn, self.v1.uid)}
        self.assertEqual(sorted(found), ["BTR-001", "BTR-002"])
        zone = np.array(cfx.rectangle(*CROWN_BOX_M))
        wanted = (float(zone[:, 0].min()), float(zone[:, 1].min()), float(zone[:, 0].max()), float(zone[:, 1].max()))
        for code, item in found.items():
            with self.subTest(entity=code):
                (ring,) = item.parts[0]
                self.assertEqual((float(ring[:, 0].min()), float(ring[:, 1].min()), float(ring[:, 0].max()), float(ring[:, 1].max())), wanted)
                self.assertEqual(item.buffer_out_m, GUARD_M)
        self.assertEqual(self.entity_state("BTR-001"), State.SUPPORT_REMOVED, "declarar no le devuelve el apoyo")
        self.assertEqual(self.temporaries(), [])


# =================================================================================================================
# T45 (hallazgos S-1 y B-1): la cadena de E2 con la detección **del proyecto** (la normal: detectar sobre el terreno, D-15) y el contrafuerte real
# =================================================================================================================

PROJECT_SURVEY = "gis_dtm_levantamiento_alto"
"""El levantamiento alto como superficie **del proyecto** (el terreno): sobre ella se detecta (la detección es del proyecto) y de ella parte el contrafuerte."""


class TallProjectWorld(TallWorld):
    """Lo de :class:`TallWorld` con el levantamiento alto **en el proyecto** y la detección ``Acopios`` (``STK-001``) **del proyecto**: la retirada la
    ata a lo que se le apoyaba por lo que anotó al crearse, no por las cifras del relleno (la detección no es de la versión)."""

    @classmethod
    def write_survey(cls) -> None:
        """Escribe el levantamiento alto como superficie del proyecto (:data:`PROJECT_SURVEY`)."""
        from tests.support.res_fixtures import write_grids

        cls.clock.advance(minutes=1)
        write_grids(cls.project, [("levantamiento_alto", gis.Raster(cls.grid, tall_survey(), sdata.CRS, sdata.VERTICAL))],
                    message="Levantamiento alto del proyecto (T45)")
        cls.clock.advance(minutes=1)

    @classmethod
    def build_world(cls) -> None:
        """El levantamiento del proyecto, la marca, la detección **del proyecto** y la capa de ejes."""
        cls.level = level_over_the_top()
        cls.write_survey()
        mark = sdata.FieldsLayer(MARKS_LAYER, "polygon", (((cfx.rectangle(*MARK_BOX_M),),),), (KEY,),
                                 {"margen": (MARGIN_M,), "material": ("mineral",)})
        sdata.write_layer(cls.project, cls.clock, mark)
        cls.create(tp.request("Acopios", layer=MARKS_LAYER, surface=PROJECT_SURVEY), version=None, masks=None)
        qfx.write_feature_layer(cls.project, cls.clock, axes_layer(cls.level))
        cls.clock.advance(minutes=1)

    def project_grid(self, name: str) -> np.ndarray:
        """La rejilla del dato **del proyecto** ``name`` tal como está en su fichero."""
        found = self.record(name)
        assert found is not None, name
        return np.asarray(sup.geotiff_reader.read_geotiff(self.root / found.locator).values)

    def cells_of(self, key: str) -> tuple[np.ndarray, np.ndarray]:
        """Las celdas de la huella del acopio ``key`` de la detección del proyecto, de su fila de ``des_stk_``."""
        found = sup.stockpile_store.read_detection_table(self.project, provenance.STOCKPILES_TABLE, "Acopios", version_uid="")
        (row,) = [item for item in found if item["key"] == key]
        return entities.runs_cells(tuple(tuple(run) for run in json.loads(row["footprint"])))


class TallProjectButtressTest(TallProjectWorld):
    """CE-016-04 con **el contrafuerte real y la detección del proyecto**, E2 (T45; S-1; ``test_a`` a ``test_g``, **en orden**): la detección ``STK-001``
    (del proyecto), el contrafuerte ``BTR-001`` de la zona de coronación sobre la cima del acopio de 12 m (parte del levantamiento del proyecto) y la
    retirada ``RMV-001`` del acopio desde su superficie, **creada con la orden real**. Lo que sigue a las órdenes de «Contrafuerte…» —declarar su zona y
    recompilar las máscaras, que deja obsoleto al contrafuerte y obliga a «Recalcular lo obsoleto» antes de retirar el acopio, RF-016-12— es de la
    prueba de Blender (``tests/blender/milestone_stockpile_ce.py``, con las órdenes reales): aquí, el dominio."""

    over_m3: ClassVar[float]

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return (*super().definitions(), *btr.buttress_definitions())

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        btr.write_profile(cls)
        cls.build_world()
        zone = sdata.FieldsLayer(CROWNS_LAYER, "polygon", (((cfx.rectangle(*CROWN_BOX_M),),),), (CROWN_ZONE,), {"cota": (CROWN_M,)})
        sdata.write_layer(cls.project, cls.clock, zone)
        cls.clock.advance(minutes=1)

    @classmethod
    def calculate(cls, request: Any, **options: Any) -> Any:
        """«Calcula» ``request`` con las máscaras de V01 **de ahora**: ``after_entity_change`` las recompila y las cargadas de antes ya no valen."""
        cls.masks_v1 = tp.access.load_masks(cls.project, cls.v1.uid)
        return super().calculate(request, **options)

    @classmethod
    def make_buttress(cls, asked: Any) -> tuple[Any, Any]:
        """«Calcula» y «crea» el contrafuerte ``asked`` en V01 (un minuto después de lo anterior): la ``Calculation`` y lo guardado."""
        cls.clock.advance(minutes=1)
        cls.masks_v1 = tp.access.load_masks(cls.project, cls.v1.uid)
        calculation = ops.last(steps.buttress_run(cls.project, asked, masks=cls.masks_v1, version=cls.v1.uid))
        stored = calculation.create(decided_by=USER)
        cls.clock.advance(minutes=1)
        return calculation, stored

    def entity_state(self, code: str) -> Any:
        return entities.registry(self.project, self.v1.uid).get(code).record.state

    @staticmethod
    def project_crown(name: str = BUTTRESS, **changes: Any) -> Any:
        """:func:`crown` desde el levantamiento del **proyecto**."""
        return crown(name, **{"start": PROJECT_SURVEY, **changes})

    def test_a_a_buttress_over_a_stockpile_of_a_project_detection_rests_on_it_with_its_volume_by_hand(self) -> None:
        """RF-016-14, RF-016-17, RF-015-15 (A13), CE-016-04 (S-1): el contrafuerte sobre la cima del acopio de 12 m se apoya **en el acopio de la
        detección del proyecto** por su clave, con **una sola cifra** cuyo valor es el cálculo a mano de los ficheros (``Σ (contrafuerte − máx(partida,
        acopio))·4 m²`` en las celdas de su huella que pasan del espesor mínimo) a ≤ 10⁻⁹ relativo; sus entradas son los datos **del proyecto**."""
        calculation, stored = self.make_buttress(self.project_crown())
        self.assertEqual(calculation.entity.code, "BTR-001")
        uid = self.uid_of("BTR-001")
        self.assertEqual(uid, str(stored.handle.uid))
        found = self.supported_of(uid)
        self.assertEqual(list(found), [("STK-001", KEY)], "una sola cifra, la del acopio")
        rows, cols = self.cells_of(KEY)
        top = self.grid_of(BUTTRESS_SURFACE)[rows, cols]
        start, ground = self.project_grid(PROJECT_SURVEY)[rows, cols], self.project_grid(DETECTED)[rows, cols]
        thick = top - np.maximum(start, ground)
        volume = math.fsum(float(value) for value in thick[thick > sup.THICKNESS_M]) * CELL_M2
        type(self).over_m3 = found[("STK-001", KEY)]
        self.assertRelative(self.over_m3, volume, "lo apoyado, de los ficheros")
        self.assertEqual(self.supports_of(uid), [(DETECTED, "supported_on"), (sup.TABLE, "support_footprint")])
        (row,) = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile=KEY)
        self.assertEqual((row.entity, row.state, row.volume_m3), ("BTR-001", State.CURRENT, self.over_m3))

    def test_b_what_rests_on_the_stockpile_is_one_list_before_calculating_and_is_not_removed_without_confirming_it(self) -> None:
        """RF-016-14, RF-015-17 (error 59; CE-016-04): retirar el acopio desde la superficie del contrafuerte da **una sola lista** antes de calcular
        (el contrafuerte, con su tipo y su volumen), la misma que la del diálogo y la que calcula la orden; no se crea sin confirmarla ni escribe nada."""
        asked = rem.asked(REMOVAL, KEY, start="entity:BTR-001", transition_deg=ANGLE_DEG)
        before = self.state()
        listed = supported_store.resting_preview(self.project, self.v1.uid, f"STK-001#{KEY}", "entity:BTR-001")
        self.assertEqual(self.state(), before, "la lista del diálogo solo lee")
        (row,) = listed
        self.assertEqual((row.name, row.op_type, row.entity, row.surface), (BUTTRESS, "des.buttress", "BTR-001", BUTTRESS_SURFACE))
        self.assertRelative(row.volume_m3, self.over_m3, "el volumen de la lista, el de su cifra")
        calculation = self.calculate(asked)
        self.assertEqual(listed, calculation.entity.resting)
        self.assertTrue(calculation.needs_resting_confirmation)
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=USER)
        self.assertEqual(caught.exception.code, "des.removal_resting_unconfirmed")
        self.assertTrue(calculation.open, "sin cerrar el cálculo")
        calculation.discard()
        self.assertEqual(self.temporaries(), [])

    def test_c_the_buttress_is_left_with_its_support_removed_and_nothing_is_discarded(self) -> None:
        """RF-015-17, RF-016-14, P-9 (CE-016-04; S-1, el centro de la hoja): creada la retirada **con la orden real** y lo apoyado confirmado,
        ``BTR-001`` queda en **«apoyo retirado»** con su causa (el acopio y la retirada) sin descartar nada; la retirada, al día; ``dependents`` del
        acopio lo da en «apoyo retirado» con su volumen y la retirada anota lo que se le apoyaba."""
        calculation, stored = self.make(rem.asked(REMOVAL, KEY, start="entity:BTR-001", transition_deg=ANGLE_DEG), confirm={"resting": True})
        self.assertFalse(calculation.open)
        self.assertEqual({entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)},
                         {"BTR-001": State.SUPPORT_REMOVED, "RMV-001": State.CURRENT})
        why = entities.stale_reason(self.project, self.v1.uid, "BTR-001")
        assert why is not None
        self.assertTrue(why.startswith("Apoyo retirado: "), why)
        for wanted in (KEY, REMOVAL):
            self.assertIn(wanted, why)
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)], "nada se descartó")
        (lost,) = entities.retired_supports(self.project, self.v1.uid)
        self.assertEqual((lost.entity, lost.name, lost.releasable), ("BTR-001", BUTTRESS, True))
        (row,) = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile=KEY)
        self.assertEqual((row.entity, row.state, row.volume_m3), ("BTR-001", State.SUPPORT_REMOVED, self.over_m3))
        ((text,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", str(stored.handle.uid))
        (recorded,) = json.loads(text)[provenance.REMOVAL_RESTING]
        self.assertEqual((recorded["entity"], recorded["name"]), ("BTR-001", BUTTRESS))
        self.assertRelative(recorded["volume_m3"], self.over_m3, "lo anotado")

    def test_d_a_buttress_made_after_the_removal_is_only_stale(self) -> None:
        """RF-015-17, CE-016-04: un contrafuerte **después** de la retirada en la cadena (parte de su superficie), sobre el mismo sitio, aunque se apoye
        en el mismo acopio del proyecto, **no pierde su apoyo** y, si cambia, **solo queda obsoleto** (con la causa de la 008)."""
        self.make_buttress(crown(BUTTRESS_AFTER, start="entity:RMV-001"))
        self.assertEqual(self.entity_state("BTR-002"), State.CURRENT)
        self.assertIn(("STK-001", KEY), self.supported_of(self.uid_of("BTR-002")), "se apoya en el acopio del proyecto")
        self.change(design_params.entity_key("BTR-002", "crown_m"), CROWN_M + 10.0)
        self.assertEqual(self.entity_state("BTR-002"), State.STALE)
        self.assertEqual(self.entity_state("BTR-001"), State.SUPPORT_REMOVED)
        reason = entities.stale_reason(self.project, self.v1.uid, "BTR-002")
        assert reason is not None
        self.assertTrue(reason.startswith("Obsoleto"), reason)
        self.assertEqual([row.entity for row in entities.retired_supports(self.project, self.v1.uid)], ["BTR-001"])

    def test_e_recompute_stale_does_not_remake_it_and_this_is_how_it_reads(self) -> None:
        """RF-016-14, RF-015-17 (error 59; CE-016-04): con ``BTR-001`` obsoleto además de sin apoyo, «Recalcular lo obsoleto» **no lo recalcula** —ni
        una operación ni un dato— y su unidad **sale ``FAILED``** con el motivo «espera una decisión» que nombra el acopio y la retirada; lo que sigue
        (la retirada y el contrafuerte de después) espera."""
        self.change(design_params.entity_key("BTR-001", "crown_m"), CROWN_M + 10.0)
        self.assertEqual(self.entity_state("BTR-001"), State.SUPPORT_REMOVED)
        uid = self.uid_of("BTR-001")
        operations, datasets = self.query("SELECT COUNT(*) FROM gb_operation"), self.query("SELECT COUNT(*) FROM gb_dataset")
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual(self.uid_of("BTR-001"), uid)
        self.assertEqual((self.query("SELECT COUNT(*) FROM gb_operation"), self.query("SELECT COUNT(*) FROM gb_dataset")), (operations, datasets))
        (result,) = [item for item in outcome.results if uid in item.unit.operations]
        self.assertIs(result.status, recompute_mod.UnitStatus.FAILED, "falla, no se rehúsa")
        self.assertEqual(result.code, "core.recompute_failed")
        text = result.text(language="es")
        assert text is not None
        for wanted in (KEY, REMOVAL, "decisión"):
            self.assertIn(wanted, text)
        self.assertEqual([item.status for item in outcome.results], [recompute_mod.UnitStatus.FAILED])

    def test_f_giving_it_as_good_brings_the_buttress_back(self) -> None:
        """RF-015-17, P-9 (CE-016-04): «darlo por bueno» sin ese apoyo (con motivo y decisor) saca a ``BTR-001`` de «apoyo retirado»: su operación
        nueva no lleva la entrada del acopio ni su cifra, y no queda nada que soltar (el contrafuerte de después de la retirada no perdió nada: está
        aguas abajo de ella)."""
        entity_store = import_geoblender("design.entity_store")
        self.clock.advance(minutes=1)
        _handle, work = entity_store.release_support(self.project, self.v1.uid, "BTR-001", reason="Se rehace sobre el relleno nuevo", decided_by=USER)
        ops.finish(work)
        self.assertNotEqual(self.entity_state("BTR-001"), State.SUPPORT_REMOVED)
        self.assertEqual(entities.retired_supports(self.project, self.v1.uid), ())
        self.assertNotIn(("STK-001", KEY), self.supported_of(self.uid_of("BTR-001")))

class TallProjectChainTest(TallProjectWorld):
    """CE-016-04 y E2 con **la detección del proyecto, un relleno de la 015 y el contrafuerte real encima** (T45; S-1; ``test_a`` a ``test_c``, **en orden**):
    el relleno ``PLT-001`` cubre el acopio de 12 m (parte del levantamiento del proyecto), el contrafuerte ``BTR-001`` parte de su superficie y sube por encima
    de él, y la retirada ``RMV-001`` parte de la del contrafuerte: lo que se le apoyaba al acopio son **los dos**, en **una sola lista**, y creada la
    retirada **los dos** quedan en «apoyo retirado»."""

    over_m3: ClassVar[float]
    listed: ClassVar[tuple[Any, ...]]

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return (*super().definitions(), *btr.buttress_definitions())

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        btr.write_profile(cls)
        cls.build_world()
        zone = sdata.FieldsLayer(CROWNS_LAYER, "polygon", (((cfx.rectangle(*CROWN_BOX_M),),),), (CROWN_ZONE,), {"cota": (CROWN_M,)})
        sdata.write_layer(cls.project, cls.clock, zone)
        cls.clock.advance(minutes=1)
        cls.made(over(OVER, start=PROJECT_SURVEY))
        cls.clock.advance(minutes=1)
        ops.last(steps.buttress_run(cls.project, crown(start="entity:PLT-001"), masks=cls.masks_v1, version=cls.v1.uid)).create(decided_by=USER)
        cls.clock.advance(minutes=1)

    def test_a_what_rests_on_the_stockpile_is_one_list_with_the_fill_and_the_buttress(self) -> None:
        """RF-016-14, RF-015-17 (error 59; CE-016-04; S-1): retirar el acopio **del proyecto** desde la superficie del contrafuerte da **una sola lista**
        antes de calcular con **los dos** —el relleno de la 015 y el contrafuerte, cada uno con su tipo y lo que puso sobre el acopio—, la misma que la que
        calcula la orden; sus volúmenes son los de sus cifras y se confirma de una vez."""
        by_name = {row.name: row for row in supported_store.resting_preview(self.project, self.v1.uid, f"STK-001#{KEY}", "entity:BTR-001")}
        self.assertEqual(sorted(by_name), sorted((OVER, BUTTRESS)))
        self.assertEqual((by_name[OVER].op_type, by_name[BUTTRESS].op_type), ("des.platform", "des.buttress"))
        listed = supported_store.resting_preview(self.project, self.v1.uid, f"STK-001#{KEY}", "entity:BTR-001")
        self.assertEqual([row.entity for row in listed], ["PLT-001", "BTR-001"], "de la más antigua a la de partida")
        for code, row in (("PLT-001", by_name[OVER]), ("BTR-001", by_name[BUTTRESS])):
            with self.subTest(entity=code):
                self.assertRelative(self.supported_of(self.uid_of(code))[("STK-001", KEY)], row.volume_m3,
                                    "lo que cada uno puso sobre el acopio es lo que midió al crearse")
        calculation = self.calculate(rem.asked(REMOVAL, KEY, start="entity:BTR-001", transition_deg=ANGLE_DEG))
        self.assertEqual(listed, calculation.entity.resting)
        self.assertTrue(calculation.needs_resting_confirmation)
        calculation.discard()

    def test_b_creating_the_removal_leaves_both_with_their_support_removed(self) -> None:
        """RF-015-17, RF-016-14, P-9 (CE-016-04; S-1: «en los dos»): creada la retirada con lo apoyado confirmado, **el relleno y el contrafuerte** quedan
        en «apoyo retirado» con su causa (el acopio y la retirada) sin descartar nada; la retirada, al día; la retirada anota **las dos** operaciones y
        ``dependents`` del acopio las da las dos."""
        _calculation, stored = self.make(rem.asked(REMOVAL, KEY, start="entity:BTR-001", transition_deg=ANGLE_DEG), confirm={"resting": True})
        states = {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}
        self.assertEqual(states, {"PLT-001": State.SUPPORT_REMOVED, "BTR-001": State.SUPPORT_REMOVED, "RMV-001": State.CURRENT})
        for code in ("PLT-001", "BTR-001"):
            with self.subTest(entity=code):
                why = entities.stale_reason(self.project, self.v1.uid, code)
                assert why is not None
                self.assertTrue(why.startswith("Apoyo retirado: "), why)
                for wanted in (KEY, REMOVAL):
                    self.assertIn(wanted, why)
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)], "nada se descartó")
        ((text,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", str(stored.handle.uid))
        self.assertEqual([row["entity"] for row in json.loads(text)[provenance.REMOVAL_RESTING]], ["PLT-001", "BTR-001"])
        self.assertEqual({row.entity: row.state for row in entities.dependents(self.project, self.v1.uid, "STK-001", stockpile=KEY)},
                         {"PLT-001": State.SUPPORT_REMOVED, "BTR-001": State.SUPPORT_REMOVED})
        self.assertEqual(sorted(row.entity for row in entities.retired_supports(self.project, self.v1.uid)), ["BTR-001", "PLT-001"])

    def test_c_recompute_stale_does_not_remake_either_of_them(self) -> None:
        """RF-016-14, RF-015-17 (error 59; CE-016-04): con el relleno obsoleto además de sin apoyo, «Recalcular lo obsoleto» **no lo recalcula** (ni lo
        que parte de su superficie: el contrafuerte y la retirada esperan), la unidad sale ``FAILED`` con «espera una decisión» y nombra el acopio y la
        retirada."""
        self.change(design_params.entity_key("PLT-001", "start_level_m"), self.level + 1.0)
        uid = self.uid_of("PLT-001")
        operations = self.query("SELECT COUNT(*) FROM gb_operation")
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual((self.uid_of("PLT-001"), self.query("SELECT COUNT(*) FROM gb_operation")), (uid, operations))
        (result,) = [item for item in outcome.results if uid in item.unit.operations]
        self.assertIs(result.status, recompute_mod.UnitStatus.FAILED)
        for wanted in (KEY, REMOVAL, "decisión"):
            self.assertIn(wanted, str(result.text(language="es")))
        self.assertEqual([item.status for item in outcome.results], [recompute_mod.UnitStatus.FAILED], "nada se recalculó")


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
