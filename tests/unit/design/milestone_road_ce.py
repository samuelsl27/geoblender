# SPDX-License-Identifier: GPL-3.0-or-later
"""Hito H2 de las pistas y rampas, sin Blender: E1 a E5 y CE-017-05 a CE-017-09 con proyecto (spec 017, T25; HU-017-1 a HU-017-3; RF-017-02, RF-017-03, RF-017-05, RF-017-17, RF-017-20, RF-017-22,
RF-017-23, RF-017-24, RF-017-25; RF-012-21, RF-012-22 y RF-012-24 con el DIFF-017; RF-015-01 a RF-015-18; plan 017 §7.1, §7.2 y §7.5; decisión de la sesión principal T19-b), como prueba de **hito**:
``check.py --completo`` la ejecuta (P-12: rejilla de 2 m con proyecto). Lo que ya prueban las tareas D y E **no se repite**: la matriz de abajo (:data:`MATRIX`, comprobada por
:class:`MatrixTest`) dice qué prueba cubre cada punto del marco de la 015 con la pista; aquí van las **composiciones** que ninguna tenía —la cadena entera de un escenario con sus cifras
contrastadas con el cálculo a mano o con otro código (la cubicación de la 011, la verificación de la 012)—. E3 (la «opción A15» con su confirmación y su motivo) y E5 (el ramal, la plataforma de destino
cambiada, la pista principal descartada, el relleno posterior y traer a otra versión) los recorren ``milestone_road_modes`` y ``milestone_road_chain``, ``milestone_road_bring`` y
``milestone_road_recompute`` (la matriz las cita) y, con lo que registra la extensión, ``tests/blender/milestone_road_ce.py``.

- **El tajo** (:class:`PitTest`, E1, E2, CE-017-05 y CE-017-09; en orden): la cantera de la 014 sintética (explotación hasta 125 m y la final restaurada con el fondo relleno hasta 140 m,
  ``road_data.pit_*``) con **el «solo relleno» posterior** —una plataforma de la 015 «en corte y relleno» a 130 m sobre el fondo, que es también «la plataforma del fondo» de E1— y la pista
  desde el final del corredor hasta ella **partiendo de la superficie que deja el relleno**: ruta, eje, rasante, sección y grabado, su resumen, la cadena cantera → plataforma → pista, la
  cubicación de la 011 entre la partida y la pista (el corte y el relleno del resumen a ≤ 10⁻⁹ relativo) y la verificación de la 012 de su superficie (la última de la cadena: «cumple», con 0 m³ en
  los intocables y fuera del perímetro); **sin avisar de la cantera de la que parte** (hallazgo H2-1); cambiado el relleno, la pista **sigue su cota** (T24b); sobre **la final restaurada** avisa de
  que no llega al fondo (las dos cotas mínimas); y la accesibilidad da **125 m sobre la explotación y 140 m sobre la final** y, con la superficie que propone el diálogo (la última de la
  cadena), también los 140 m sobre la final de su cantera (T43, C-2).
- **Antes del relleno** (:class:`BeforeTheFillTest`, CE-017-05): la pista sobre una superficie **anterior al relleno** avisa del área, la diferencia máxima y el lugar de lo que no tiene en cuenta
  (a mano sobre los ficheros) y, al cambiar el relleno, **queda obsoleta con su causa** (el hallazgo H2-2 impide aquí repetirla: véase la *Verificación* de la T25).
- **La cantera con bancos** (:class:`BankTest`, E4, CE-017-07 y CE-017-09; en orden): la rampa a una cota por los bancos (con la confirmación de la calzada fuera de su rasante), la accesibilidad de la
  cantera (tres bermas comunicadas y una no, la plataforma, las dos zonas «requiere acceso»: a mano), la accesibilidad de la superficie que deja la rampa (a mano: la inundación sobre ella) y la
  verificación de la 012 con las **tres respuestas** de RF-012-22.
- **La sección con proyecto** (:class:`SectionProjectTest`, CE-017-06, error 20): la huella guardada de la pista de 200 m es la sección a mano en las mismas celdas, de 200 m ± 1 celda, con el arcén
  en el lado de mayor cota y el caballón a la derecha si las cotas son iguales.
- **La plataforma de un acopio retirado «como plataforma»** (:class:`StockpilePlatformRoadTest`, E1, RF-017-03): la pista hasta ella, que se apoya en ella.
"""

from __future__ import annotations

import ast
import json
import math
import re
import unittest
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import constraints_project as cproject
from tests.support import res_fixtures
from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design import milestone_stockpile_supports as stock_ops
from tests.unit.design import test_removal_operation as rem
from tests.unit.design.milestone_road_recompute import RecomputeCase, finish_steps, recompute_function
from tests.unit.design.test_access_operation import request as access_request
from tests.unit.design.test_platform_operation import finish
from tests.unit.design.test_road_prepare import BY, GRID, drive, request

access = import_geoblender("gis.masks.access")
access_store = import_geoblender("design.access_store")
core_params = import_geoblender("core.params")
cparams = import_geoblender("core.constraints.params")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
entities = import_geoblender("design.entities")
entity_layer = import_geoblender("design.entity_layer")
entity_store = import_geoblender("design.entity_store")
gis = import_geoblender("gis")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
res_store = import_geoblender("reserves.store")
road_profiles = import_geoblender("design.road_profiles")
road_store = import_geoblender("design.road_store")
steps = import_geoblender("design.steps")
surfaces = import_geoblender("design.surfaces")
store = import_geoblender("design.store")
compliance = import_geoblender("reserves.compliance")
cstore = import_geoblender("reserves.compliance_store")
res_surfaces = import_geoblender("reserves.surfaces")
volumes = import_geoblender("reserves.volumes")

TOL = 1e-9
PROBE = "des.probe_road_h2"
"""El tipo de operación de prueba de V01 que escribe las dos superficies de una cantera (solo desde esta prueba)."""
MIN_THICKNESS_M = 0.02
"""El espesor mínimo de la 012 (``res.verify.min_thickness_m``, D-6): lo que separa «difiere» de «no difiere»."""
QUARRY = "Tajo"
EXPLOITATION, FINAL = "des_exp_tajo", "des_fin_tajo"
FILL, FILL_CODE = "Relleno del fondo", "PLT-001"
ROAD, ON_TERRAIN, ON_FINAL = "Pista al fondo", "Pista sobre el terreno", "Pista de la final"
TERRAIN = rd.dataset_of("tajo")
FILL_LAYER, PIT_POINTS, PIT_ENTRY_LAYER = "gis_fea_h2_relleno", "gis_fea_h2_puntos", "gis_fea_h2_entrada"
FILL_LEVEL_M = 130.0
"""La cota del «solo relleno» posterior (``road_data.PIT_FILL_LEVEL_M``): 5 m sobre el fondo."""
FILL_BOX = rd.PIT_FILL_BOX
VERIFY = "Verificación de la pista del tajo"
BANK_PROBE = "des.probe_road_h2_bank"
BANK_EXPLOITATION, BANK_ENTRY_LAYER = "des_exp_cantera", "gis_fea_h2_banco_entrada"
RAMP_NAME, PLATFORM_BANK = "Rampa a la berma de 115", "Plataforma de la berma 125"
ACCESS_NAME, ROAD_ACCESS_NAME, BANK_BERMS = "Accesibilidad de la cantera", "Accesibilidad de la rampa", "des_brm_cantera"
WITH, WITHOUT = "zona_con_acceso", "zona_sin_acceso"
RAMP_PROFILE, RAMP_GRADIENT_PCT = "rampa_15", 15.0
"""El perfil de las rampas de la cantera con bancos: el de referencia con pd y pm del 15 % (las rampas grabadas de la cantera son del 12,5 %: la pista las sigue sin moverlas)."""
SECTION_PROFILE, SHOULDER_M = "seccion", 3.0
"""El perfil de la prueba de la sección: el de referencia con un arcén de 3 m (el de la referencia no tiene), para ver en celdas de 2 m de qué lado va cada cosa."""
STOCK_PLATFORM, STOCK_POINTS = "Acopio 1 como plataforma", "gis_fea_h2_acopio_puntos"
STOCK_ORIGIN, STOCK_DESTINATION = (30.0, 100.0), (100.0, 100.0)
"""El origen de la pista (local, 70 m al oeste del Acopio 1) y su destino, el centro de la plataforma que deja su retirada."""
BOXES = {WITH: "Zona con acceso", WITHOUT: "Zona sin acceso"}
"""El código de cada zona «requiere acceso» y el nombre de su caja a mano de ``road_data``."""


def never(request_: Any) -> Any:
    raise AssertionError("las pruebas del hito no recalculan ni reproducen lo que no registran")


def surface_of(name: str) -> str:
    """El nombre del dato de la superficie entera (``des_psf_``) de la entidad ``name``."""
    return provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, name)


class H2Case(RecomputeCase):
    """Lo de ``RecomputeCase`` (la copia del proyecto de las pistas en 2 m, sus máscaras, el perfil de referencia y los tipos con sus funciones **reales**) más la accesibilidad y la
    verificación de la 012 registradas con las suyas (las de ``bl``) y las ayudas que usan todos los mundos del hito."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.ACCESS_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        cls.enterClassContext(registered(provenance.operation_def(provenance.ROAD_ACCESS, access_recompute, design_reproduce.reproduce_road_access), *provenance.ACCESS_FIGURES))
        cls.enterClassContext(registered(cstore.operation_def(verify_recompute, cstore.REPRODUCE[cstore.VERIFY]), *cstore.FIGURES))

    @classmethod
    def write_quarry(cls, probe: str, name: str, grids: dict[str, np.ndarray]) -> str:
        """Escribe en V01 las superficies ``grids`` (familia → valores) de la cantera ``name`` con la operación de prueba ``probe``: su uid."""
        begun = store._start(cls.project, probe, name, cls.v1, None, {"name": name}, (), (), None)
        cls.clock.advance(minutes=1)
        with store.design_writer(cls.project, probe, name, version=cls.v1.uid) as writer:
            for family, values in grids.items():
                drive(writer.grid_steps(family, gis.Raster(GRID, values, rd.CRS, rd.VERTICAL)))
            stored = writer.commit(begun, message="Superficies de la cantera del hito H2 de las pistas")
        cls.clock.advance(minutes=1)
        return str(stored.handle.uid)

    @classmethod
    def register_probe(cls, probe: str, outputs: tuple[str, ...]) -> None:
        """Registra el tipo de operación de prueba ``probe`` que escribe las superficies ``outputs`` (solo desde esta prueba)."""
        found = provenance.OperationType(probe, "Surfaces of a quarry of the H2 of the roads", outputs, ())
        cls.enterClassContext(mock.patch.object(provenance, "OPERATION_TYPES_BY_NAME", MappingProxyType({**provenance.OPERATION_TYPES_BY_NAME, probe: found})))
        cls.enterClassContext(registered(found.definition(never)))

    def uid(self, which: Any) -> str:
        return str(which.handle.uid)

    def road_figure(self, entity: str, key: str) -> float:
        """La cifra ``key`` de la pista ``entity`` (la de su operación vigente)."""
        code = entities.registry(self.project, self.v1.uid).get(entity).record.code
        return float({name: value for name, value, _scope in self.figures_of(self.current(code))}[key])

    def surface(self, name: str) -> np.ndarray:
        """La rejilla del dato ``name`` tal como está en su fichero."""
        return np.asarray(self.grid_of(name), dtype=np.float64)

    def footprint_mask(self, name: str) -> np.ndarray:
        """La huella de la entidad ``name`` (la tabla ``des_epr_``) como máscara de la rejilla."""
        (row,) = self.table(name, provenance.ENTITY_TABLE)
        return np.asarray(entity_store.runs_mask(json.loads(row["footprint"]), GRID.shape))

    def verify(self, start: str, *finals: str, name: str = VERIFY) -> Any:
        """La verificación de la 012 de V01 de ``finals`` contra ``start`` (nombres de dato): lo guardado (``StoredCheck``)."""
        self.clock.advance(minutes=1)
        found = None
        for step in cstore.verify_project_steps(self.project, version=self.v1.uid, name=name, start=res_surfaces.SurfaceRef(dataset=start),
                                                finals=tuple(res_surfaces.SurfaceRef(dataset=item) for item in finals)):
            found = step.result if step.result is not None else found
        return found


class PitCase(H2Case):
    """Lo de ``H2Case`` más **el tajo de la 014** de V01 (``des_exp_tajo`` y ``des_fin_tajo``, que escribe una operación de prueba), la capa del relleno, la de los puntos de la pista y la
    de la entrada de la accesibilidad."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.register_probe(PROBE, (provenance.EXPLOITATION_GRID, provenance.FINAL_GRID))
        cls.write_quarry(PROBE, QUARRY, {provenance.EXPLOITATION_GRID: rd.pit_exploitation(GRID), provenance.FINAL_GRID: rd.pit_final(GRID)})
        layer = sdata.FieldsLayer(FILL_LAYER, "line", (((rd.absolute([(FILL_BOX[0], 160.0), (FILL_BOX[2], 160.0)], GRID),),),), (FILL,),
                                  {"ancho": (FILL_BOX[3] - FILL_BOX[1],), "cota_inicial": (FILL_LEVEL_M,), "pendiente": (0.0,)})
        sdata.write_layer(cls.project, cls.clock, layer)
        points = (("Origen del tajo", rd.PIT_ORIGIN), ("En el relleno", (100.0, 160.0)))
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(PIT_POINTS, "point", tuple(((rd.absolute([point], GRID),),) for _name, point in points),
                                                                   tuple(name for name, _point in points), {}))
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(PIT_ENTRY_LAYER, "point", (((rd.absolute([rd.PIT_ENTRY], GRID),),),), ("Entrada del tajo",), {}))
        cls.clock.advance(minutes=1)

    @classmethod
    def make_fill(cls) -> Any:
        """El «solo relleno» posterior: la plataforma «Relleno del fondo» (``PLT-001``, «en corte y relleno» a 130 m) sobre la explotación del tajo, creada en V01: lo guardado."""
        asked = model.PlatformRequest(FILL, model.PlatformFields(layer=FILL_LAYER, start_level_field="cota_inicial", gradient_field="pendiente", width_field="ancho"), FILL, EXPLOITATION,
                                      mode="cut_fill", edge_angle_deg=35.0, reach_m=20.0)
        cls.clock.advance(minutes=1)
        stored = finish(steps.platform_run(cls.project, asked, masks=cls.masks_v1, version=cls.v1.uid)).create()
        cls.clock.advance(minutes=1)
        return stored

    @staticmethod
    def asked_road(name: str, **changes: Any) -> Any:
        """La pista de «Origen del tajo» (el terreno al final del corredor, 141 m) al centro del fondo, «En el relleno»: por defecto, **a la plataforma** (el punto de la capa que cae en su
        huella, 130 m) y partiendo de la superficie que deja el relleno; con otra partida, al punto (a la cota de esa superficie)."""
        base = {"destination": f"entity:{FILL_CODE}", "surface": f"entity:{FILL_CODE}"}
        return request(name, layer=PIT_POINTS, origin="Origen del tajo", **{**base, **changes})


def access_recompute(request_: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de ``des.road_access``: lleva los pasos hasta el final."""
    handle, work = store.recompute_run(request_)
    finish_steps(work)
    return handle


def verify_recompute(request_: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de ``res.verify_constraints``: lleva los pasos hasta el final."""
    handle, work = cstore.recompute_run(request_)
    finish_steps(work)
    return handle


class PitTest(PitCase):
    """E1, E2, CE-017-05 y CE-017-09 en el tajo, **en orden** (``test_a`` a ``test_g``): cada una parte de lo que dejó la anterior."""

    fill: ClassVar[Any]
    road: ClassVar[Any]
    road_stored: ClassVar[Any]

    def test_a_the_fill_after_the_pit_is_the_platform_at_the_bottom_of_the_chain(self) -> None:
        """E1, E2, RF-015-04, RF-015-15: el «solo relleno» posterior es una plataforma «en corte y relleno» de la 015 que sube el fondo del tajo de 125 a 130 m en su huella de 40 × 40 m: **8.000
        m³ a mano** (400 celdas de 4 m² por 5 m) entre la superficie de explotación y la suya; la partida por defecto de una pista sigue siendo la explotación, pero **la ocupa ya la plataforma** y la
        pista parte de la superficie que deja el relleno."""
        type(self).fill = self.make_fill()
        footprint = self.footprint_mask(FILL)
        raised = (self.surface(surface_of(FILL)) - self.surface(EXPLOITATION))[footprint]
        self.assertEqual(int(footprint.sum()), 400)
        self.assertLessEqual(abs(math.fsum(raised.tolist()) * GRID.cell_area - 8000.0), TOL * 8000.0)
        found = entities.registry(self.project, self.v1.uid).get(FILL_CODE)
        self.assertEqual((found.record.name, found.record.state, found.record.start), (FILL, entities.EntityState.CURRENT, EXPLOITATION))
        proposed = road_store.default_start(self.project, self.v1)
        self.assertEqual((proposed.ref, proposed.kind, proposed.conflict), (EXPLOITATION, "exploitation", FILL))

    def test_b_e1_the_road_to_the_platform_is_calculated_without_writing_and_created_in_one_transaction(self) -> None:
        """E1, RF-017-02, RF-017-03, RF-017-23, RF-015-03, D-22: la pista «trazar» del final del corredor (141 m) a la plataforma (130 m), **partiendo de la superficie que deja el relleno**: «Calcular»
        no escribe nada; el resumen da la longitud (no pasa de la recta en más de un 2,8 %), las cotas de inicio y de fin (141 y 130 m: la de la superficie de partida en cada punto), la pendiente
        máxima (≤ pd) y el radio mínimo (≥ Rmín), el corte y el relleno; **se apoya en la plataforma** y no avisa de la cantera ni del relleno de los que parte (hallazgo H2-1: ni la explotación ni
        la final de su propia cantera son «otro diseño»); «Crear» la deja al día."""
        before = self.state()
        calculation = self.calculate_in(self.asked_road(ROAD))
        self.assertEqual(self.state(), before, "calcular no escribe")
        summary = calculation.summary
        straight = math.dist(rd.PIT_ORIGIN, (100.0, 160.0))
        self.assertGreaterEqual(summary.length_m, straight)
        self.assertLessEqual(summary.length_m, straight * 1.028 + 1e-9)
        self.assertEqual((summary.start_level_m, summary.end_level_m), (rd.PIT_GROUND_M, FILL_LEVEL_M))
        self.assertLessEqual(summary.gradient_max_pct, rd.PROFILE.max_gradient_pct + 1e-9)
        self.assertTrue(summary.radius_min_m is None or summary.radius_min_m >= rd.PROFILE.min_radius_m - 1e-9)
        self.assertGreater(summary.cut_m3, 0.0)
        self.assertEqual(calculation.entity.supports, (FILL_CODE,))
        codes = [notice.code for notice in summary.notices]
        self.assertNotIn("des.road_other_design_differs", codes, "H2-1: la cantera de la que parte la partida no es otro diseño")
        self.assertNotIn("des.road_start_is_final", codes)
        self.assertEqual(calculation.outcome.other_designs, ())
        counters = self.state()["counter"]
        stored = calculation.create(decided_by=BY)
        self.clock.advance(minutes=1)
        self.assertEqual(self.state()["counter"] - counters, 1, "«Crear» es una transacción")
        type(self).road, type(self).road_stored = calculation, stored
        found = entities.registry(self.project, self.v1.uid).get("RDW-001")
        self.assertEqual((found.record.name, found.record.kind, found.record.state, found.record.start), (ROAD, entities.EntityKind.ROAD, entities.EntityState.CURRENT, f"entity:{FILL_CODE}"))

    def test_c_e1_the_axis_the_gradient_and_the_chain_are_the_hand_calculation(self) -> None:
        """E1, RF-017-23, RF-017-13, RF-017-15, RF-015-01, RF-015-04: del eje por estaciones **que guardó** (``des_rdx_``) salen, a mano, la rasante (de 141 a 130 m, sus extremos son el origen y el destino
        exactos), la pendiente media (``Σ|Δcota| / S``) y la máxima, que son las cifras registradas a ≤ 10⁻⁹ relativo y no pasan de pd; la anchura de la calzada y de la sección son las del perfil
        (10,5 y 11,5 m); y la cadena es **cantera → plataforma → pista**: la plataforma parte de la explotación y la pista, de la plataforma, que es la que apoya, con su volumen."""
        axis = self.table(ROAD, provenance.ROAD_AXIS_TABLE)
        s = np.array([row["station_m"] for row in axis])
        z = np.array([row["level_m"] for row in axis])
        figures = {key: value for key, value, _scope in self.figures_of(self.uid(self.road_stored))}
        steps_pct = np.abs(np.diff(z)) / np.diff(s) * 100.0
        for key, wanted in (("des.road_gradient_mean_pct", float(np.abs(np.diff(z)).sum() / (s[-1] - s[0]) * 100.0)), ("des.road_gradient_max_pct", float(steps_pct.max())),
                            ("des.road_length_m", float(s[-1] - s[0])), ("des.road_z_start_m", float(z[0])), ("des.road_z_end_m", float(z[-1]))):
            self.assertLessEqual(abs(figures[key] - wanted), TOL * max(1.0, abs(wanted)), key)
        self.assertEqual((float(z[0]), float(z[-1])), (rd.PIT_GROUND_M, FILL_LEVEL_M))
        self.assertLessEqual(float(steps_pct.max()), rd.PROFILE.max_gradient_pct + 1e-9)
        origin, destination = rd.absolute([rd.PIT_ORIGIN, (100.0, 160.0)], GRID)
        self.assertLessEqual(math.dist((axis[0]["x"], axis[0]["y"]), tuple(origin)), 1e-6)
        self.assertLessEqual(math.dist((axis[-1]["x"], axis[-1]["y"]), tuple(destination)), 1e-6)
        self.assertEqual((figures["des.road_width_m"], figures["des.road_section_m"]), (rd.PROFILE.vehicle_width_m * rd.PROFILE.lane_factor, 11.5))
        for _step in entity_store.entity_layer_steps(self.project, self.v1):
            pass
        with self.project.read() as conn:
            rows = {row.code: row for row in entity_layer.read_entity_layer(conn, entity_layer.entity_layer_table(self.v1.code))}
        self.assertEqual((rows[FILL_CODE].start, rows["RDW-001"].start), (EXPLOITATION, FILL))
        self.assertIn(f"{FILL} → {ROAD}", rows["RDW-001"].chain)
        (item,) = [found for found in entities.dependents(self.project, self.v1.code, FILL_CODE) if found.entity == "RDW-001"]
        self.assertIn("supported_on", item.roles)

    def test_d_ce_017_09_the_011_cubication_between_the_start_and_the_road_is_the_cut_and_fill_of_the_summary(self) -> None:
        """CE-017-09, RF-017-23, RF-011-02: la cubicación **de la 011** (``reserves.volumes``, otro código, sobre las dos rejillas del proyecto) entre la superficie de partida y la de la pista da
        el corte y el relleno **del resumen** (la sección y el borde juntos) a ≤ 10⁻⁹ relativo."""
        request_ = volumes.VolumeRequest("Cubicación de la pista del tajo", res_surfaces.SurfaceRef(dataset=surface_of(FILL)), res_surfaces.SurfaceRef(dataset=surface_of(ROAD)))
        found = None
        for step in volumes.volume_steps(request_, res_store.project_sources(self.project, request_, version_uid=self.v1.uid)):
            found = step.result if step.result is not None else found
        kernel = found.kernel
        summary = self.road.summary
        for what, got, wanted in (("corte", float(kernel.cut_m3[0]), summary.cut_m3), ("relleno", float(kernel.fill_m3[0]), summary.fill_m3)):
            self.assertGreater(wanted, 0.0, what)
            self.assertLessEqual(abs(got - wanted) / wanted, TOL, f"{what}: {got!r} frente a {wanted!r}")

    def test_e_ce_017_09_the_012_verification_of_the_last_surface_of_the_chain_complies_and_moves_nothing_in_the_untouchables(self) -> None:
        """CE-017-09, RF-012-21, RF-012-22, RF-015-06: la verificación de la 012 de la superficie de la pista (la última de su cadena: cantera → plataforma → pista) contra la explotación da
        **«cumple»**: ningún recinto falla, y los intocables y lo que queda fuera del perímetro tienen **0 m³** de corte y de relleno; la pista (como la plataforma) mueve cosas (la comparación no
        es vacía)."""
        found = self.verify(EXPLOITATION, surface_of(ROAD))
        (check,) = found.result.finals
        self.assertFalse(check.fails, [(item.code, item.verdict) for item in check.totals if item.verdict is compliance.Verdict.FAILS])
        by_code = {item.code: item for item in check.totals}
        guarded = [item for item in check.totals if item.counts is compliance.Counts.ANY]
        self.assertTrue(guarded and compliance.OUTSIDE_PERIMETER in by_code, "los intocables y el perímetro se miran")
        for item in guarded:
            self.assertEqual((item.cut_m3, item.fill_m3, item.moved_m2), (0.0, 0.0, 0.0), item.code)
        self.assertTrue(all(item.verdict in (compliance.Verdict.COMPLIES, compliance.Verdict.NOT_JUDGED) for item in check.totals))
        self.assertGreater(max(item.moved_m2 for item in check.totals), 0.0)

    def test_f_changing_the_fill_makes_the_road_stale_with_its_cause_and_recomputing_repeats_it_in_order_and_it_follows_the_new_level(self) -> None:
        """E2, E5, RF-015-16, RF-017-03, RF-008-26, D-13 (T24b): al **cambiar el relleno** (su cota, de 130 a 131 m) queda obsoleta con su causa la pista que parte de él (y la capa de entidades y la
        verificación, que miraban lo que cambió); «Recalcular lo obsoleto» repite **en orden** la plataforma y la pista; **la cota de fin de la pista, que salió de la plataforma, la sigue** (131 m)
        y nada queda obsoleto."""
        key = design_params.entity_key(FILL_CODE, "start_level_m")
        self.change(key, FILL_LEVEL_M + 1.0)
        self.assertIn(("parameter_changed", key), self.stale_causes(self.current(FILL_CODE)))
        self.assertTrue(self.stale_causes(self.current("RDW-001")), "la pista que parte del relleno queda obsoleta en cascada")
        plan = [unit[0] for unit in self.recompute_plan()]
        self.assertEqual([op for op in plan if op in (provenance.PLATFORM, provenance.ROAD)], [provenance.PLATFORM, provenance.ROAD])
        self.assertLessEqual(set(plan) - {provenance.PLATFORM, provenance.ROAD}, {provenance.ENTITY_LAYER, cstore.VERIFY})
        self.clock.advance(minutes=1)
        made = self.recompute_all()
        self.assertEqual([op for op in map(self.type_of, made) if op in (provenance.PLATFORM, provenance.ROAD)], [provenance.PLATFORM, provenance.ROAD])
        self.assertEqual(self.table(ROAD, provenance.ROAD_AXIS_TABLE)[-1]["level_m"], FILL_LEVEL_M + 1.0)
        self.assertEqual(self.road_figure(ROAD, "des.road_z_end_m"), FILL_LEVEL_M + 1.0)
        for uid in made:
            self.assertEqual(self.stale_causes(uid), set())
        self.assertEqual(self.recompute_plan(), [])

    def test_g_ce_017_05_on_the_restored_final_the_road_warns_that_it_does_not_reach_the_bottom_and_the_accessibility_gives_125_and_140(self) -> None:
        """CE-017-05, RF-017-05 (a), RF-017-24, E2, error 23: la pista sobre **la final restaurada** avisa, la primera, de que no llega al fondo con la cota mínima alcanzable sobre ella (140 m) y sobre
        la de explotación (125 m) sin impedir crearla, y la que parte del relleno no lo avisa; la accesibilidad da **125 m sobre la explotación y 140 m sobre la final** (a mano: el fondo del tajo
        por el corredor y el fondo relleno), la de la explotación con el aviso de la final, y la plataforma del fondo, comunicada. **C-2:** con la superficie que **propone el diálogo** (la última de la
        cadena: la de la pista, que parte del relleno que parte de la explotación) da además **140 m sobre la final de su cantera**, junto a su cota mínima (la menor de las celdas alcanzables de su
        rejilla), con el aviso de la final; sobre la final misma, o sobre la de una cadena que parte de ella, no se repite (su cota mínima ya es esa cifra)."""
        default = access_store.default_surface(self.project, self.v1)  # antes de crear la pista de la final (otra cadena): la cola es una sola
        self.assertEqual(default, surface_of(ROAD))
        calculation = self.calculate_in(self.asked_road(ON_FINAL, destination="En el relleno", surface=FINAL))
        first = calculation.summary.notices[0]
        self.assertEqual((first.code, first.values["surface"], first.values["z_final"], first.values["z_pit"]), ("des.road_start_is_final", FINAL, rd.PIT_Z_MIN_FINAL_M, rd.PIT_Z_MIN_EXPLOITATION_M))
        self.assertNotIn("des.road_start_is_final", [notice.code for notice in self.road.summary.notices])
        stored = calculation.create(decided_by=BY)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", self.uid(stored)), [("done",)])
        self.clock.advance(minutes=1)
        results: dict[str, Any] = {}
        from_the_final = surface_of(ON_FINAL)  # la de la pista que parte de la final: su cadena no sale de la explotación
        for surface in (EXPLOITATION, FINAL, default, from_the_final):
            asked = access_request(f"Accesibilidad sobre {surface}", layer=PIT_ENTRY_LAYER, surface=surface)
            made = finish_steps(steps.access_run(self.project, asked, version=self.v1.uid, masks=self.masks_v1))
            results[surface] = (made, made.create(decided_by=BY))
            self.clock.advance(minutes=1)
        pit_figures = {key: value for key, value, _scope in self.figures_of(self.uid(results[EXPLOITATION][1]))}
        final_figures = {key: value for key, value, _scope in self.figures_of(self.uid(results[FINAL][1]))}
        chain_figures = {key: value for key, value, _scope in self.figures_of(self.uid(results[default][1]))}
        self.assertEqual((pit_figures["des.acc_z_min_m"], pit_figures["des.acc_z_min_final_m"]), (rd.PIT_Z_MIN_EXPLOITATION_M, rd.PIT_Z_MIN_FINAL_M))
        self.assertEqual(final_figures["des.acc_z_min_m"], rd.PIT_Z_MIN_FINAL_M)
        self.assertNotIn("des.acc_z_min_final_m", final_figures, "sobre la final misma no se repite: su cota mínima ya es esa cifra")
        self.assertIn("des.access_final", [notice.code for notice in results[EXPLOITATION][0].notices])
        self.assertEqual((pit_figures["des.acc_platforms_reached"], final_figures["des.acc_platforms_reached"]), (1.0, 1.0))
        # C-2: con la superficie por defecto (la última de la cadena) la cota sobre la final también sale, sobre la de su cantera (140 m), y la propia es la menor de las celdas alcanzables
        reachable = np.asarray(results[default][0].outcome.reachable)
        self.assertEqual(chain_figures["des.acc_z_min_final_m"], rd.PIT_Z_MIN_FINAL_M)
        self.assertEqual(results[default][0].outcome.z_min_final_m, rd.PIT_Z_MIN_FINAL_M)
        self.assertEqual(chain_figures["des.acc_z_min_m"], float(self.surface(default)[reachable].min()))
        self.assertLess(chain_figures["des.acc_z_min_m"], rd.PIT_Z_MIN_FINAL_M, "sobre la última de la cadena se llega más abajo que sobre la final restaurada")
        self.assertIn("des.access_final", [notice.code for notice in results[default][0].notices])
        self.assertNotIn("des.access_final_none", [notice.code for notice in results[default][0].notices])
        self.assertEqual(results[default][0].summary.final, FINAL)
        # una cadena que parte de la final restaurada no sale de la explotación: sin cota sobre la final (no se repite) ni aviso de que falte
        self.assertNotIn("des.acc_z_min_final_m", {key for key, _value, _scope in self.figures_of(self.uid(results[from_the_final][1]))})
        self.assertIsNone(results[from_the_final][0].summary.final)
        self.assertNotIn("des.access_final_none", [notice.code for notice in results[from_the_final][0].notices])


class BeforeTheFillTest(PitCase):
    """CE-017-05, RF-017-05 (b), RF-015-16: una pista sobre una superficie **anterior al relleno**, en su propio mundo (el relleno, y la pista que parte de él, creados antes), **en orden**."""

    main: ClassVar[Any]
    other: ClassVar[Any]
    other_stored: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.make_fill()
        cls.main = cls.made(cls.asked_road(ROAD))[0]

    def test_a_a_road_before_the_fill_warns_of_the_area_the_difference_and_the_place(self) -> None:
        """CE-017-05, RF-017-05 (b): la pista sobre **el terreno anterior al relleno** (``gis_dtm_tajo``, la explotación sin el relleno) avisa, de lo que no tiene en cuenta —la superficie con el
        relleno y la pista (la última de su cadena) y la final restaurada—, del **área**, la **diferencia máxima** y el **lugar**, que son los de la cuenta a mano sobre sus rejillas en la huella de
        la pista (sección y borde); lo de lo que parte (la explotación), no; y lo que no tiene en cuenta queda como **entrada** con su hash."""
        calculation = self.calculate_in(self.asked_road(ON_TERRAIN, destination="En el relleno", surface=TERRAIN))
        others = {notice.values["other"]: notice.values for notice in calculation.summary.notices if notice.code == "des.road_other_design_differs"}
        self.assertEqual(sorted(others), [FINAL, surface_of(ROAD)])
        self.assertEqual(calculation.outcome.other_designs, (FINAL, surface_of(ROAD)))
        engraved = calculation.outcome.engraved
        inside = np.zeros(GRID.shape, dtype=bool)
        inside[calculation.outcome.window] = np.asarray(engraved.footprint) | np.asarray(engraved.in_reach)  # la huella de la pista: la sección y lo que su borde alcanza
        start = self.surface(TERRAIN)
        for name, values in others.items():
            with self.subTest(other=name):
                difference = np.abs(self.surface(name) - start)
                counted = inside & (difference > MIN_THICKNESS_M)
                self.assertEqual(values["area"], float(counted.sum()) * GRID.cell_area)
                self.assertLessEqual(abs(values["difference"] - float(difference[counted].max())), TOL)
                rows, cols = np.nonzero(counted & (difference >= float(difference[counted].max()) - 1e-12))
                self.assertTrue(any(abs(values["x"] - (GRID.west + (col + 0.5) * GRID.dx)) < 1e-6 and abs(values["y"] - (GRID.north - (row + 0.5) * GRID.dy)) < 1e-6
                                    for row, col in zip(rows.tolist(), cols.tolist(), strict=True)), "el lugar es el de una celda de la diferencia máxima")
        self.assertEqual(round(others[FINAL]["difference"], 9), 15.0)
        type(self).other = calculation
        type(self).other_stored = calculation.create(decided_by=BY)
        self.clock.advance(minutes=1)
        recorded = {name: sha for name, role, sha in self.query(
            "SELECT d.name, io.role, io.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
            "AND io.item_kind = 'dataset'", self.uid(self.other_stored)) if role == provenance.ROAD_OTHER_DESIGN_ROLE}
        self.assertEqual(sorted(recorded), [FINAL, surface_of(ROAD)])
        self.assertEqual(recorded, {name: self.hashes(name)[name][0] for name in recorded})

    def test_b_changing_the_fill_makes_it_stale_with_its_cause(self) -> None:
        """CE-017-05, RF-015-16, RF-008-26: al **cambiar el relleno** (su cota, de 130 a 131 m) la pista que no lo tenía en cuenta **queda obsoleta con su causa** y «Recalcular lo obsoleto» la
        tiene en su plan, después de la plataforma y de la pista que parte de ella (lee la superficie que esa deja). (**No se repite aquí**: hallazgo H2-2, véase la *Verificación* de la T25.)"""
        key = design_params.entity_key(FILL_CODE, "start_level_m")
        self.change(key, FILL_LEVEL_M + 1.0)
        causes = self.stale_causes(self.uid(self.other_stored))
        self.assertTrue(causes, "la pista sobre el terreno anterior queda obsoleta")
        self.assertIn(("parameter_changed", design_params.entity_key(FILL_CODE, "start_level_m")), causes)
        self.assertIn(("parameter_changed", key), self.stale_causes(self.current(FILL_CODE)))
        self.assertTrue(self.stale_causes(self.current("RDW-001")))
        plan = [unit[0] for unit in self.recompute_plan()]
        self.assertEqual([op for op in plan if op in (provenance.PLATFORM, provenance.ROAD)], [provenance.PLATFORM, provenance.ROAD, provenance.ROAD])


class BankCase(H2Case):
    """Lo de ``H2Case`` más **la cantera con bancos y rampas** de V01 (``des_exp_cantera``, su final 20 m más arriba y sus bermas de la 013; los escribe una operación de prueba), las dos
    restricciones «requiere acceso» **de verdad** (declaradas y compiladas en las máscaras de V01: ``zona_con_acceso`` y ``zona_sin_acceso``) y la capa con la entrada."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.register_probe(BANK_PROBE, (provenance.BERMS_GRID, provenance.EXPLOITATION_GRID, provenance.FINAL_GRID))
        exploitation = rd.bank_surface(GRID)
        cls.write_quarry(BANK_PROBE, "Cantera", {provenance.BERMS_GRID: rd.bank_berms(GRID), provenance.EXPLOITATION_GRID: exploitation, provenance.FINAL_GRID: exploitation + 20.0})
        rows = rd.bank_zone_constraints()
        cls.clock.advance(minutes=1)
        cproject.edit_constraints(cls.project, rows)
        cproject.declare(cls.project, cls.clock, {**{cparams.active_key(row.code): True for row in rows}, **{cparams.buffer_out_key(row.code): 0.0 for row in rows}})
        cls.clock.advance(minutes=1)
        for _step in access.ensure_masks_steps(cls.project, cls.v1.uid):
            pass
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        declared = road_profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", BY, "Perfil de las rampas de la cantera con bancos del H2", version=cls.v1.code)
        profile = rd.profile_with(max_gradient_pct=RAMP_GRADIENT_PCT, max_mean_gradient_pct=RAMP_GRADIENT_PCT)
        values = {param: getattr(profile, "class_name" if param.value == "class" else param.value) for param in design_params.RoadProfileParam}
        cls.clock.advance(minutes=1)
        road_profiles.edit_road_profiles(cls.project, (road_profiles.ProfileEdit(name=RAMP_PROFILE.upper(), values=values),), declared)
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(BANK_ENTRY_LAYER, "point", (((rd.absolute([rd.BANK_ENTRY], GRID),),),), ("Entrada de la cantera de bancos",), {}))
        cls.clock.advance(minutes=1)


class BankTest(BankCase):
    """E4, CE-017-07 y CE-017-09 en la cantera con bancos, **en orden** (``test_a`` a ``test_d``): la rampa a una cota, la accesibilidad de la superficie que deja y la verificación de la 012."""

    ramp: ClassVar[Any]
    ramp_stored: ClassVar[Any]

    def access_on(self, name: str, surface: str) -> Any:
        """«Calcula» y «crea» la accesibilidad ``name`` de la entrada de la cantera sobre ``surface``: lo guardado."""
        asked = access_request(name, layer=BANK_ENTRY_LAYER, surface=surface)
        found = finish_steps(steps.access_run(self.project, asked, version=self.v1.uid, masks=self.masks_v1))
        stored = found.create(decided_by=BY)
        self.clock.advance(minutes=1)
        return stored

    def reachable_by_hand(self, surface: np.ndarray) -> np.ndarray:
        """Lo alcanzable **a mano** de ``surface`` desde la entrada con los umbrales de la referencia (16 % y 4 m): la pendiente local de ``road_data.oracle_slope_pct``, lo intocable fuera, la
        apertura con el disco exacto de ``road_data.oracle_disc_opening`` y la inundación 4-conexa de ``road_data.oracle_reachable``."""
        untouchable = (self.masks_v1.classes & np.uint16(64)) != 0
        walkable = (rd.oracle_slope_pct(surface, GRID.dx) <= rd.ACCESS.walk_slope_pct) & ~untouchable
        return rd.oracle_reachable(rd.oracle_disc_opening(walkable, rd.ACCESS.walk_width_m / 2.0, GRID.dx), [rd.cell_of(rd.BANK_ENTRY, GRID)])

    def check_zones(self, name: str, reachable: np.ndarray, surface: np.ndarray) -> None:
        """Las dos zonas «requiere acceso» de la accesibilidad ``name`` frente al cálculo a mano sobre ``reachable`` y ``surface``: la comunicada, sin lugar; la que no, con su celda más
        próxima a lo alcanzable (por fuerza bruta), la distancia y la diferencia de cota."""
        zones = {row["code"]: row for row in self.table(name, provenance.ACCESS_ZONES_TABLE)}
        by_hand = {code: bool((rd.bank_zone_mask(box, GRID) & reachable).any()) for code, box in BOXES.items()}
        self.assertEqual(by_hand, {WITH: True, WITHOUT: False})
        self.assertEqual({code: bool(row["connected"]) for code, row in zones.items()}, by_hand)
        squared, index, level = rd.oracle_nearest_reachable(np.flatnonzero(rd.bank_zone_mask(BOXES[WITHOUT], GRID)), reachable, surface)
        row, column = divmod(index, GRID.ncols)
        missing = zones[WITHOUT]
        self.assertLessEqual(abs(missing["distance_m"] - math.sqrt(squared) * GRID.dx), TOL * max(1.0, missing["distance_m"]))
        self.assertLessEqual(abs(missing["level_difference_m"] - (level - float(surface[row, column]))), TOL * 10.0)
        self.assertLessEqual(abs(missing["x"] - (GRID.west + (column + 0.5) * GRID.dx)) + abs(missing["y"] - (GRID.north - (row + 0.5) * GRID.dy)), 1e-6)
        self.assertEqual((zones[WITH]["x"], zones[WITH]["distance_m"], zones[WITH]["level_difference_m"]), (None, None, None))

    def test_a_e4_the_ramp_to_a_level_goes_down_the_benches_and_ends_in_the_zone_at_that_level(self) -> None:
        """E4, RF-017-02, RF-017-10, RF-017-23, D-4: la rampa de la entrada de la cantera (140 m) a **una cota** (115 m, la de la berma) con la zona donde ha de alcanzarse y su tolerancia: termina
        **dentro de la zona**, a la cota pedida dentro de la tolerancia, sin pasar de pd en ningún tramo, con la longitud que pide el desnivel (≥ 25 m / pd); «Calcular» no escribe nada; por las
        caras de los bancos la altura máxima deja calzada **fuera de su rasante** (RF-017-22) y pide la confirmación expresa, con la que «Crear» la deja al día partiendo de la explotación de la
        cantera."""
        asked = request(RAMP_NAME, layer=rd.ENTRIES_LAYER, profile=RAMP_PROFILE, origin="Entrada de la cantera de bancos", destination=None, dest_level_m=rd.BANK_Z_MIN_M, dest_tol_m=0.5,
                        dest_zone=f"{rd.ZONES_LAYER}:Zona de la berma 115", surface=BANK_EXPLOITATION)
        before = self.state()
        calculation = self.calculate_in(asked)
        self.assertEqual(self.state(), before, "calcular no escribe")
        summary = calculation.summary
        self.assertEqual(summary.start_level_m, rd.BANK_ENTRANCE_M)
        self.assertLessEqual(abs(summary.end_level_m - rd.BANK_Z_MIN_M), 0.5)
        self.assertLessEqual(summary.gradient_max_pct, RAMP_GRADIENT_PCT + 1e-9)
        self.assertGreaterEqual(summary.length_m, (rd.BANK_ENTRANCE_M - rd.BANK_Z_MIN_M) / (RAMP_GRADIENT_PCT / 100.0) - 1e-9)
        self.assertTrue(calculation.needs_carriageway_confirmation, "por las caras de los bancos, la altura máxima deja calzada fuera de su rasante (RF-017-22)")
        self.assertEqual(summary.carriageway_area_m2, sum(group.area_m2 for group in calculation.outcome.off_level))
        calculation.confirm_road(carriageway=True)
        stored = calculation.create(decided_by=BY)
        self.clock.advance(minutes=1)
        type(self).ramp, type(self).ramp_stored = calculation, stored
        axis = self.table(RAMP_NAME, provenance.ROAD_AXIS_TABLE)
        west, south = rd.origin_of(GRID)
        x, y = axis[-1]["x"] - west, axis[-1]["y"] - south
        left, bottom, right, top = rd.ZONES[1][1]
        self.assertTrue(left <= x <= right and bottom <= y <= top, f"el eje acaba en la zona: ({x}, {y})")
        found = entities.registry(self.project, self.v1.uid).get("RDW-001")
        self.assertEqual((found.record.state, found.record.start), (entities.EntityState.CURRENT, BANK_EXPLOITATION))

    def test_b_ce_017_07_the_accessibility_of_the_bank_surface_lists_the_berms_the_platform_and_the_zones(self) -> None:
        """CE-017-07, RF-017-24, RF-017-25: la accesibilidad de la cantera con bancos (sus rampas grabadas) desde la entrada —con la plataforma de la berma de 125 m creada— da **tres bermas
        comunicadas (135, 125 y 115 m) y una no (105 m)**, cada una con su cota, su área (8.000 m²: 400 × 20 m) y su lugar (su centro), la cota mínima alcanzable (115 m) y la máxima (140 m), la
        plataforma **comunicada a 125 m** y las dos zonas «requiere acceso» —la de la berma de 135 m, comunicada; la de la de 105 m, **no**, con su lugar, la distancia y la diferencia de cota a lo
        alcanzable—, todo igual al cálculo a mano sobre la rejilla de lo alcanzable que guardó (que es la inundación a mano de ``road_data``)."""
        fields = model.PlatformFields(layer=rd.PLATFORMS_LAYER, start_level_field="cota_inicial", gradient_field="pendiente", width_field="ancho")
        self.clock.advance(minutes=1)
        asked = model.PlatformRequest(PLATFORM_BANK, fields, PLATFORM_BANK, rd.dataset_of("banco"), mode="cut_fill", edge_angle_deg=35.0, reach_m=20.0)
        finish(steps.platform_run(self.project, asked, masks=self.masks_v1, version=self.v1.uid)).create()
        self.clock.advance(minutes=1)
        stored = self.access_on(ACCESS_NAME, BANK_EXPLOITATION)
        surface = self.surface(BANK_EXPLOITATION)
        reachable = self.surface(provenance.dataset_name(provenance.ACCESS_GRID, ACCESS_NAME)) > 0.0
        np.testing.assert_array_equal(reachable, self.reachable_by_hand(surface))
        berms = self.table(ACCESS_NAME, provenance.ACCESS_BERMS_TABLE)
        self.assertEqual({row["level_m"]: bool(row["connected"]) for row in berms}, {135.0: True, 125.0: True, 115.0: True, 105.0: False})
        for row, (low, high) in zip(sorted(berms, key=lambda item: -item["level_m"]), rd.BANK_BERM_RANGES, strict=True):
            where = rd.absolute([(200.0, (low + high) / 2.0)], GRID)[0]
            self.assertEqual((row["area_m2"], row["x"], row["y"]), (rd.BANK_BERM_AREA_M2, float(where[0]), float(where[1])), row["level_m"])
        figures = {key: value for key, value, _scope in self.figures_of(self.uid(stored))}
        self.assertEqual((figures["des.acc_z_min_m"], figures["des.acc_z_max_m"]), (rd.BANK_Z_MIN_M, rd.BANK_Z_MAX_M))
        self.assertEqual((figures["des.acc_berms_reached"], figures["des.acc_berms_total"], figures["des.acc_platforms_reached"]), (3.0, 4.0, 1.0))
        (platform,) = self.table(ACCESS_NAME, provenance.ACCESS_PLATFORMS_TABLE)
        self.assertEqual((platform["code"], bool(platform["connected"]), platform["level_m"]), ("PLT-001", True, rd.BANK_PLATFORM_Z_M))
        self.check_zones(ACCESS_NAME, reachable, surface)

    def test_c_e4_the_accessibility_of_the_surface_the_ramp_leaves_says_what_it_communicates(self) -> None:
        """E4, RF-017-24, RF-017-25: la accesibilidad de la superficie que deja la rampa (la última de su cadena) dice **qué queda comunicado y a qué cota se llega** con lo que la rampa grabó: lo
        alcanzable que guardó es la inundación a mano sobre **esa** superficie (pendiente ≤ 16 %, ancho ≥ 4 m), la cota mínima alcanzable, la mínima de esas celdas, y cada berma está comunicada si
        alguna de sus celdas es alcanzable. Con la calzada que las máscaras de la cantera de la 015 dejan fuera de su rasante (la confirmación de RF-017-22), **la rampa no comunica la berma de
        115 m**, que sí comunicaban las rampas de la cantera: la lista lo dice con su lugar."""
        stored = self.access_on(ROAD_ACCESS_NAME, surface_of(RAMP_NAME))
        surface = self.surface(surface_of(RAMP_NAME))
        reachable = self.surface(provenance.dataset_name(provenance.ACCESS_GRID, ROAD_ACCESS_NAME)) > 0.0
        np.testing.assert_array_equal(reachable, self.reachable_by_hand(surface))
        levels = self.surface(BANK_BERMS)
        berms = self.table(ROAD_ACCESS_NAME, provenance.ACCESS_BERMS_TABLE)
        for row in berms:
            on_berm = levels == row["level_m"]
            self.assertEqual(bool(row["connected"]), bool((on_berm & reachable).any()), f"la berma de {row['level_m']} m")
        self.assertEqual({row["level_m"]: bool(row["connected"]) for row in berms}, {135.0: True, 125.0: True, 115.0: False, 105.0: False})
        figures = {key: value for key, value, _scope in self.figures_of(self.uid(stored))}
        self.assertEqual(figures["des.acc_z_min_m"], float(surface[reachable].min()))
        self.assertGreater(figures["des.acc_z_min_m"], rd.BANK_Z_MIN_M - 1e-9, "no se llega más abajo que la berma de 115 m")
        self.assertEqual(figures["des.acc_berms_reached"], 2.0)
        self.check_zones(ROAD_ACCESS_NAME, reachable, surface)

    def test_d_ce_017_09_the_012_verification_of_the_ramp_surface_gives_the_three_answers_of_the_zones(self) -> None:
        """CE-017-09, RF-012-22, RF-017-25, DIFF-017: la verificación de la 012 de la superficie de la rampa (la última de su cadena) contra la explotación, **con la accesibilidad al día** que se
        hizo sobre ella, da a la zona «requiere acceso» **comunicada «cumple»** y a la que no lo está **«no cumple»**; y una final **sin accesibilidad al día** (aquí, el terreno del proyecto) las deja
        **«sin comprobar»**: las tres respuestas; los intocables y lo que queda fuera del perímetro tienen 0 m³ y solo incumple la zona que no se comunica."""
        stored = self.verify(BANK_EXPLOITATION, surface_of(RAMP_NAME), rd.dataset_of("banco"))
        first, second = stored.result.finals
        self.assertEqual({code: first.zone(code).verdict for code in (WITH, WITHOUT)}, {WITH: compliance.Verdict.COMPLIES, WITHOUT: compliance.Verdict.FAILS})
        self.assertEqual({code: second.zone(code).verdict for code in (WITH, WITHOUT)}, {WITH: compliance.Verdict.UNCHECKED, WITHOUT: compliance.Verdict.UNCHECKED})
        (made,) = cstore.select_access(self.project, self.v1.uid, (res_surfaces.SurfaceRef(dataset=surface_of(RAMP_NAME)),)).uses
        self.assertEqual((made.code, made.name), ("ACC-002", ROAD_ACCESS_NAME))
        for check in (first, second):
            for item in check.totals:
                if item.counts is compliance.Counts.ANY:
                    self.assertEqual((item.cut_m3, item.fill_m3), (0.0, 0.0), item.code)
        self.assertEqual({item.code for item in first.totals if item.verdict is compliance.Verdict.FAILS}, {WITHOUT}, "solo incumple la zona que no se comunica")
        self.assertTrue(first.fails and not second.fails)
        start, final = self.surface(BANK_EXPLOITATION), self.surface(surface_of(RAMP_NAME))
        self.assertTrue((np.abs(final - start) > MIN_THICKNESS_M).any(), "la rampa mueve tierra: la comparación no es vacía")


class SectionCase(H2Case):
    """Lo de ``H2Case`` más el perfil ``SECCION`` (el de referencia con **un arcén de 3 m**, para que en las celdas de 2 m se vea de qué lado va cada cosa) y la rampa con la pendiente transversal
    **contraria** (``gis_dtm_rampa_lateral_sur``: el terreno sube hacia el sur)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        declared = road_profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", BY, "Perfil de la sección de la prueba del hito H2", version=cls.v1.code)
        profile = rd.profile_with(shoulder_m=SHOULDER_M, reach_m=12.5)
        values = {param: getattr(profile, "class_name" if param.value == "class" else param.value) for param in design_params.RoadProfileParam}
        cls.clock.advance(minutes=1)
        road_profiles.edit_road_profiles(cls.project, (road_profiles.ProfileEdit(name=SECTION_PROFILE.upper(), values=values),), declared)
        cls.clock.advance(minutes=1)
        res_fixtures.write_grids(cls.project, [("rampa_lateral_sur", gis.Raster(GRID, rd.ramp_terrain(GRID, cross_pct=-rd.RAMP_CROSS_PCT), rd.CRS, rd.VERTICAL))],
                                 message="Rampa con la pendiente transversal contraria del hito H2")
        cls.clock.advance(minutes=1)


class SectionProjectTest(SectionCase):
    """CE-017-06, RF-017-20, RF-017-21, RF-017-23, error 20 **con proyecto**: la pista «sobre un eje» de 200 m con la sección del perfil, creada, en las tres rampas (cotas iguales a los dos lados,
    pendiente transversal hacia el norte y hacia el sur)."""

    def section_of(self, label: str, cross_pct: float) -> tuple[Any, np.ndarray, Any]:
        """Crea la pista del eje de 200 m sobre la rampa ``label`` y da lo guardado, su huella (la tabla ``des_epr_``) y la sección a mano en las mismas celdas."""
        name = f"Sección sobre {label}"
        _calculation, stored = self.made(request(name, mode="on_axis", layer=rd.AXES_LAYER, surface=rd.dataset_of(label), feature="Eje de 200 m", profile=SECTION_PROFILE))
        footprint = self.footprint_mask(name)
        by_hand = rd.straight_section_by_hand(GRID, lambda x, y: rd.RAMP_Z0_M + rd.RAMP_SLOPE_PCT / 100.0 * x + cross_pct / 100.0 * (y - rd.RAMP_AXIS_Y_M), rd.PROFILE.vehicle_width_m * rd.PROFILE.lane_factor,
                                              SHOULDER_M, rd.PROFILE.berm_m)
        return stored, footprint, by_hand

    def check(self, stored: Any, footprint: np.ndarray, by_hand: Any, *, shoulder_row: float) -> None:
        """La huella guardada es la sección a mano en las mismas celdas; mide 200 m ± 1 celda a lo largo del eje (error 20: no 211,5 m) y la fila de más es la del lado del arcén."""
        np.testing.assert_array_equal(footprint, by_hand.cells)
        rows, cols = np.nonzero(footprint)
        self.assertLessEqual(abs((cols.max() - cols.min() + 1) * GRID.dx - 200.0), GRID.dx, "200 m ± 1 celda a lo largo del eje")
        self.assertEqual(int(footprint.sum()), 7 * 100, "seis filas de calzada y la del arcén; el caballón de 1 m no llega a un centro de celda de 2 m")
        _x, y = rd.local_centers(GRID)
        extra = sorted({float(y[row, col]) for row, col in zip(rows.tolist(), cols.tolist(), strict=True) if abs(float(y[row, col]) - rd.RAMP_AXIS_Y_M) > rd.PROFILE.vehicle_width_m * rd.PROFILE.lane_factor / 2.0})
        self.assertEqual(extra, [shoulder_row])
        figures = {key: value for key, value, _scope in self.figures_of(self.uid(stored))}
        self.assertEqual((figures["des.road_width_m"], figures["des.road_section_m"]), (10.5, 10.5 + SHOULDER_M + rd.PROFILE.berm_m))
        self.assertEqual(figures["des.road_area_m2"], float(footprint.sum()) * GRID.cell_area)

    def test_a_equal_heights_on_both_sides_the_berm_goes_on_the_right(self) -> None:
        """CE-017-06, RF-017-20, error 20: con **cotas iguales a ambos lados** (la rampa del 4 % sin pendiente transversal) la sección guardada es la de a mano a ≤ 10⁻⁹ m: el arcén a la
        izquierda (al norte) y **el caballón a la derecha** (al sur; el de 1 m no llega a un centro de celda de 2 m, la fila de más es la del arcén), 200 m ± 1 celda de largo."""
        stored, footprint, by_hand = self.section_of("rampa", 0.0)
        self.check(stored, footprint, by_hand, shoulder_row=rd.RAMP_AXIS_Y_M + 7.0)

    def test_b_with_a_cross_slope_the_shoulder_goes_on_the_higher_side(self) -> None:
        """CE-017-06, RF-017-20: con **pendiente transversal del 20 %** el arcén va **en el lado de mayor cota**: con el terreno subiendo hacia el norte, a la izquierda; con él subiendo hacia el sur,
        a la derecha (la huella guardada es la de a mano en las mismas celdas en los dos casos)."""
        stored, footprint, by_hand = self.section_of("rampa_lateral", rd.RAMP_CROSS_PCT)
        self.check(stored, footprint, by_hand, shoulder_row=rd.RAMP_AXIS_Y_M + 7.0)
        stored, footprint, by_hand = self.section_of("rampa_lateral_sur", -rd.RAMP_CROSS_PCT)
        self.check(stored, footprint, by_hand, shoulder_row=rd.RAMP_AXIS_Y_M - 7.0)


class StockpilePlatformRoadTest(rem.RemovalCase):
    """E1 (la otra plataforma de destino), RF-017-03, RF-015-15 y RF-015-04: la pista hasta **la plataforma que deja un acopio retirado «como plataforma»** (016, A9), en el proyecto de los acopios
    (la detección ``Acopios`` de V01 sobre el levantamiento y el Acopio 1 retirado como plataforma, ``PLT-001``)."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return (*super().definitions(), *road_profiles.OPERATIONS, provenance.operation_def(provenance.ROAD, recompute_function, design_reproduce.reproduce_road), *provenance.ROAD_FIGURES)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.ROAD_PROFILE_FAMILIES)
        core_params.register_families(design_params.ROAD_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        declared = road_profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", BY, "Perfil de la prueba de la pista a la plataforma de un acopio", version=cls.v1.code)
        values = {param: getattr(rd.profile_with(reach_m=12.5), "class_name" if param.value == "class" else param.value) for param in design_params.RoadProfileParam}
        cls.clock.advance(minutes=1)
        road_profiles.edit_road_profiles(cls.project, (road_profiles.ProfileEdit(name="PISTA_PRINCIPAL", values=values),), declared)
        cls.detect()
        cls.clock.advance(minutes=1)
        asked = model.PlatformRequest.of_stockpile(STOCK_PLATFORM, "STK-001#Acopio 1", stock_ops.SURVEY, edge_angle_deg=35.0, reach_m=12.0)
        platform = finish(steps.platform_run(cls.project, asked, masks=cls.masks_v1, version=cls.v1.uid))
        if platform.needs_confirmation:
            platform.confirm_counterslope()
        platform.create(decided_by=BY)
        cls.clock.advance(minutes=1)
        points = (("Origen del acopio", STOCK_ORIGIN), ("En la plataforma", STOCK_DESTINATION))
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(STOCK_POINTS, "point", tuple(((rd.absolute([point], GRID),),) for _name, point in points),
                                                                   tuple(name for name, _point in points), {}))
        cls.clock.advance(minutes=1)

    def test_a_the_road_to_the_platform_of_a_removed_stockpile_rests_on_it_and_reaches_the_plane_of_its_base(self) -> None:
        """E1, RF-017-03, RF-015-15, RF-015-04: la pista «trazar» de un punto a 70 m al oeste del Acopio 1 hasta **la plataforma que deja su retirada** (el punto de la capa que cae en su huella):
        **se apoya en ella** y parte de su superficie (la cadena levantamiento → plataforma → pista); la cota de fin es la del plano de la base del acopio en el punto (la del fichero de su base, a ≤ 10⁻⁹ m; no la del plano
        del levantamiento: la corona del Acopio 1 toca la del 2), la pendiente máxima no pasa de la de diseño y la longitud no baja de la recta (rodea lo que tiene delante: el levantamiento tiene montículos); «Calcular» no escribe nada y «Crear» la deja al día."""
        asked = request("Pista a la plataforma del acopio", layer=STOCK_POINTS, origin="Origen del acopio", destination="entity:PLT-001", surface="entity:PLT-001")
        before = self.state()
        calculation = finish(steps.road_run(self.project, asked, version=self.v1.uid, masks=self.masks_v1))
        self.assertEqual(self.state(), before, "calcular no escribe")
        summary = calculation.summary
        self.assertEqual(calculation.entity.supports, ("PLT-001",))
        cell = rd.cell_of(STOCK_DESTINATION, GRID)
        base = np.asarray(drive(surfaces.read_surface_steps(self.project, provenance.dataset_name("stb", "Acopios mineral"), version_uid=self.v1.uid)).values)
        platform = np.asarray(drive(surfaces.read_surface_steps(self.project, surface_of(STOCK_PLATFORM), version_uid=self.v1.uid)).values)
        self.assertLessEqual(abs(float(platform[cell]) - float(base[cell])), TOL, "la huella de la plataforma está en el plano de su base")
        self.assertEqual(summary.end_level_m, float(platform[cell]))
        straight = math.dist(STOCK_ORIGIN, STOCK_DESTINATION)
        self.assertGreaterEqual(summary.length_m, straight - 1e-9)
        self.assertLessEqual(summary.gradient_max_pct, rd.PROFILE.max_gradient_pct + 1e-9)
        self.assertNotIn("des.road_other_design_differs", [notice.code for notice in summary.notices])
        if calculation.needs_carriageway_confirmation:  # 100 m² de calzada a 0,16 m de su rasante por una restricción de la cantera de la 015 (RF-017-22)
            calculation.confirm_road(carriageway=True)
        stored = calculation.create(decided_by=BY)
        registry = entities.registry(self.project, self.v1.uid)
        self.assertEqual((registry.get("PLT-001").record.start, registry.get("RDW-001").record.start, str(registry.get("RDW-001").record.state)), (stock_ops.SURVEY, "entity:PLT-001", "current"))
        (item,) = [found for found in entities.dependents(self.project, self.v1.code, "PLT-001") if found.entity == "RDW-001"]
        self.assertIn("supported_on", item.roles)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", str(stored.handle.uid)), [("done",)])


MATRIX: dict[str, tuple[tuple[str, str], ...]] = {
    "RF-015-01": (("milestone_road_create.py", "RoadChainTest"), ("milestone_road_ce.py", "PitTest")),
    "RF-015-02": (("milestone_road_create.py", "RoadChainTest"), ("milestone_road_recompute.py", "RoadReproduceTest")),
    "RF-015-03": (("milestone_road_calculate.py", "CalculateTest"), ("milestone_road_ce.py", "PitTest")),
    "RF-015-04": (("milestone_road_chain.py", "BranchTest"), ("milestone_road_ce.py", "PitTest")),
    "RF-015-05": (("blender/milestone_road_menu.py", "RoadEntityMenuTest"), ("blender/test_road_menu.py", "RoadMenuTest")),
    "RF-015-06": (("milestone_road_create.py", "RoadChainTest"), ("test_road_prepare.py", "RoadPrepareTest")),
    "RF-015-07": (("milestone_road_prepare.py", "PendingSectorTest"),),
    "RF-015-08": (("test_road_prepare.py", "RoadPrepareTest"), ("milestone_road_calculate.py", "CalculateTest")),
    "RF-015-09": (("test_road_prepare.py", "RoadPrepareTest"), ("test_road_operation.py", "RejectionsTest")),
    "RF-015-10": (("milestone_road_create.py", "RoadChainTest"),),
    "RF-015-12": (("milestone_road_create.py", "RoadChainTest"),),
    "RF-015-13": (("milestone_road_calculate.py", "ConfirmationsOnTheCalculationTest"), ("test_road_operation.py", "SummaryTest")),
    "RF-015-14": (("test_road_engrave.py", "NoticesTest"), ("milestone_road_calculate.py", "QuarryCalculateTest")),
    "RF-015-15": (("milestone_road_chain.py", "BranchTest"), ("test_road_chain.py", "FillOnTheRoadTest"), ("milestone_road_ce.py", "PitTest")),
    "RF-015-16": (("milestone_road_chain.py", "TargetPlatformTest"), ("milestone_road_recompute.py", "RoadStaleTest"), ("milestone_road_ce.py", "BeforeTheFillTest")),
    "RF-015-17": (("milestone_road_chain.py", "DiscardMainRoadTest"),),
    "RF-015-18": (("milestone_road_bring.py", "BroughtChainTest"), ("test_road_bring.py", "BroughtRoadsTest")),
}
"""**La matriz del marco de la 015 con la pista** (T25): para cada punto de RF-015-01 a 18, la prueba (fichero de ``tests/unit/design`` y clase) que lo comprueba **con la pista** y lo cita en su
docstring, sin repetirlo aquí: los ficheros ``milestone_road_*`` (con proyecto; las ejecuta el paso «hito») y ``test_road_*`` (sin proyecto, en el «verde»). Las clases de este fichero son las
composiciones de E1 a E5 (el marco **junto con** lo demás: la cantera, la accesibilidad, la cubicación de la 011 y la verificación de la 012). Un fichero con el prefijo ``blender/`` es de
``tests/blender`` (con Blender y las órdenes reales: lo ejecuta ``tools/run_blender_tests.py``, desde ``check.py``); RF-015-05, insertar antes o después, se prueba así (T43, C-6)."""
LIMITS: dict[str, str] = {
    "RF-015-05": "**una pista no se inserta**: el punto aplica a la pista **junto a** otra entidad (se inserta una plataforma antes o después de una pista y la sucesora pasa a partir de ella, con el ramal "
                 "obsoleto con su causa: ``milestone_road_menu.test_fa``), pero «Pista…» no tiene ``insert_before`` y «Insertar antes o después de…» abre siempre «Plataforma…» (hallazgo H2-4, véase la "
                 "*Verificación* de la T25; ``test_road_menu.RoadMenuTest``)",
}
"""Lo de la matriz que aplica **con un límite escrito** (lo que la pista no hace en ese punto), con el porqué: cada clave está en :data:`MATRIX`."""
NOT_APPLICABLE: dict[str, str] = {
    "RF-015-11":"restricción declarada que se edita en QGIS: la pista **no declara ninguna restricción** (RF-017-01, D-15); lo prueba ``milestone_road_create.RoadChainTest.test_g`` (ni operación ni tabla de declaradas)",
}
"""Lo del marco que no se aplica a la pista, con el porqué."""


class MatrixTest(unittest.TestCase):
    """La matriz de :data:`MATRIX` es verdad: cada prueba que cita existe y **cita el requisito** en su docstring o en el de alguno de sus métodos, y los 18 puntos del marco están, o en la matriz
    (con su límite escrito en :data:`LIMITS`, si lo tiene) o en :data:`NOT_APPLICABLE` con su porqué."""

    def test_every_point_of_the_frame_of_the_015_has_a_road_test_that_says_so(self) -> None:
        """RF-015-01 a RF-015-18, RF-017-01 (§4: el marco de la 015 se prueba con la pista): los 18 puntos están repartidos; cada (fichero, clase) existe y cita el requisito. **RF-015-05 aplica**
        (T43, C-6: se inserta una plataforma detrás de una pista) y su límite es «una pista no se inserta», no un «no aplica»."""
        wanted = {f"RF-015-{number:02d}" for number in range(1, 19)}
        self.assertEqual(set(MATRIX) | set(NOT_APPLICABLE), wanted)
        self.assertFalse(set(MATRIX) & set(NOT_APPLICABLE))
        self.assertIn("RF-015-05", MATRIX)
        self.assertTrue(set(LIMITS) <= set(MATRIX) and all(LIMITS.values()))
        self.assertIn("RF-015-05", LIMITS)
        here = Path(__file__).resolve().parent
        trees: dict[str, ast.Module] = {}
        for requirement, tests in MATRIX.items():
            self.assertTrue(tests, requirement)
            for name, cls in tests:
                with self.subTest(requirement=requirement, test=f"{name}::{cls}"):
                    if name not in trees:
                        source = here.parents[1] / name if name.startswith("blender/") else here / name  # ``blender/…``: ``tests/blender/…``
                        trees[name] = ast.parse(source.read_text(encoding="utf-8"))
                    (node,) = [item for item in trees[name].body if isinstance(item, ast.ClassDef) and item.name == cls]
                    docstrings = [ast.get_docstring(node) or "", *(ast.get_docstring(item) or "" for item in node.body if isinstance(item, ast.FunctionDef))]
                    self.assertTrue(any(re.search(re.escape(requirement) + r"(?!\d)", text) for text in docstrings), f"{cls} no cita {requirement}")
        self.assertTrue(all(reason for reason in NOT_APPLICABLE.values()))


if __name__ == "__main__":
    import unittest

    unittest.main()
