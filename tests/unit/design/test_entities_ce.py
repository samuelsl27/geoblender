# SPDX-License-Identifier: GPL-3.0-or-later
"""Hito H2 de las entidades de diseño (spec 015, T27; HU-015-1, HU-015-2; CE-015-01, CE-015-04 y CE-015-05; E3 de
§2 y §10.1 sin pantalla; RF-015-01 a RF-015-18; plan 015 §7.1, §7.5 y §8; ADR-0030): el marco **de punta a punta, con
proyecto**, antes de ponerle la vista, la capa y el menú. Los dos errores que dieron origen a la spec, el 59 (un
relleno que seguía apoyado en lo que otro retiraba) y el 51 (la programación lineal rellenó una balsa que ningún
operador sabía que no se rellenaba), con la cantera sintética de la 014 y las capas de plataformas (rejilla gruesa de 2
m), **sin tocar las funciones del código**: solo la API pública de ``design``, ``core`` y ``gis``, y las cuentas **a
mano** (la huella de una plataforma de 30 m de eje y 6 m de ancho sobre celdas de 2 m, con los centros de celda sobre
los extremos del eje, son 16 × 3 = 48 celdas de 4 m²).

- **CE-015-01** (:class:`DependenciesTest`, el marco del error 59): P2 «en corte y relleno», de la superficie de P1,
  rellena 2 m sobre la huella de P1 y **se apoya en ella** con 48 · 2 · 4 = **384 m³** a mano, a ≤ 10⁻⁹ relativo; otra
  entidad que **declara** apoyarse en P1 se registra igual (con 0 m³); cambiar P1 deja obsoleta a P2 en cascada con la
  causa y, tras rehacerlo todo, el volumen apoyado es el de la rasante nueva (369,6 m³ a mano); **traídas P1 y P2 a otra
  versión**, quedan sin calcular y, al calcularlas allí, la dependencia **se detecta de nuevo**; al descartar P1, **una
  sola lista** da lo que se le apoya antes (con su volumen), lo apoyado queda en «apoyo retirado» y «Recalcular lo
  obsoleto» **no lo recalcula** hasta que la persona lo rehace sobre otra superficie (P2), lo descarta (P5) o lo da por
  bueno con un motivo que queda registrado (P4: su salida no cambia y lo que dependía de ella no se recalcula); y una
  versión hija recibe **descartada** la que se descartó con datos (hallazgo (a) de la T26).
- **CE-015-04** (:class:`ProtectedPlatformTest`, el marco del error 51): una plataforma «en corte» que declara «sin
  relleno» (D-4); un «solo relleno» de la 014 y una plataforma «en corte y relleno» que la solapa rellenan **0 m³** en
  su huella, el resumen de la segunda da el área que no rellena con la plataforma protegida y **la verificación de la
  012 da «cumple»** (por recinto, con una celda movida de más que sí incumple); al cambiar su propia restricción queda
  obsoleta y, recalculada, la marca se quita sin que cambie su salida (RF-008-26, D-21; lo que da cada pasada, en la
  prueba); descartada, su restricción sale de las máscaras; y una «en corte y relleno» que la declare se rechaza.
- **CE-015-05** (:class:`FrozenVersionTest`): congelar V01.r1 y cambiar la pendiente de P1 en la revisión abierta deja
  obsoletas, con su causa, a la plataforma y a lo que se le apoya y, recalculadas, cambian; V01.r1 **no cambia** (ni sus
  elementos ni los ficheros de su instantánea, por su huella) y se reproduce bit a bit.
- **E3 sin pantalla** (§2, §10.1): lo que enseña «Ver restricciones y límites» (``listed_constraints``, con su
  entidad), el «solo relleno» que no entra en la plataforma protegida, cambiar una entidad y ver la cascada en
  «Recalcular lo obsoleto» y descartar una plataforma en la que se apoya otra (la lista antes; «apoyo retirado»
  después y no recalculada por «Recalcular lo obsoleto»), repartidos entre las tres clases.
"""

from __future__ import annotations

import hashlib
import json
import math
import unittest
from typing import Any, ClassVar

import numpy as np

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import create_version
from tests.unit.design import test_after_entity_change as chain_test
from tests.unit.design import test_declare_operation as decl
from tests.unit.design import test_entity_dependents as dep
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_fill_only_operation as fill_test
from tests.unit.design import test_platform_operation as ops_test
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
core_params = import_geoblender("core.params")
cstore = import_geoblender("reserves.compliance_store")
compliance = import_geoblender("reserves.compliance")
design_params = import_geoblender("design.params")
design_store = import_geoblender("design.store")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
events = import_geoblender("core.project.events")
freeze = import_geoblender("core.versions.freeze")
gis = import_geoblender("gis")
masks_store = import_geoblender("gis.masks.store")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
steps = import_geoblender("design.steps")
surfaces = import_geoblender("reserves.surfaces")
geotiff_reader = import_geoblender("gis.geotiff.reader")

DesignError = messages.DesignError
EntityState = entities.EntityState
BALSA, ON_TOP, DRAG, TWIN = dep.BALSA, dep.ON_TOP, dep.DRAG, dep.TWIN
WORKSHOP, WITH_AXIS = prep.WORKSHOP, prep.WITH_AXIS
START = fill_test.START
BY = "Samuel (IMGA)"
WHY = "Se retira la balsa: la propiedad cambia el plan"
UNIT = "m³"

CELL_M2 = 4.0
"""El área de una celda de la rejilla gruesa (2 m)."""
FOOTPRINT_CELLS = 16 * 3
"""La huella de «Plataforma de la balsa», a mano: el eje de (135, 305) a (165, 305) tiene los centros de celda de
x = 135, 137… 165 (16, con los dos extremos: centros de celda de 2 m, impares) y el ancho de 6 m, tres filas (y de
303, 305 y 307): 48 celdas, 192 m²."""
FILL_M = 2.0
"""P2 («Sobre la balsa», 257 m) sube 2 m sobre la rasante de P1 (255 m)."""
FILL_BY_HAND_M3 = FOOTPRINT_CELLS * FILL_M * CELL_M2
"""384 m³: lo que P2 rellena sobre la huella de P1 a mano."""
SLOPE_PCT = 0.5
"""La pendiente de P1 tras cambiarla en las pruebas (la de la capa es 0 %)."""
ABSCISSAE = [2.0 * column for column in range(16)]
"""La abscisa del centro de cada columna de la huella: 0, 2… 30 m desde el primer vértice del eje."""
FILL_AFTER_BY_HAND_M3 = 3 * math.fsum(FILL_M - SLOPE_PCT / 100.0 * sigma for sigma in ABSCISSAE) * CELL_M2
"""Lo que rellena P2 sobre la rasante de P1 con la pendiente de 0,5 %: la columna de abscisa σ queda
``2 − 0,005·σ`` m sobre ella, en tres filas: 369,6 m³."""
THICKNESS_M = sup.THICKNESS_M
GRADIENT = dep.GRADIENT
HOLE = prep.HOLE_DATASET
EDGE_HOLE = ops_test.EDGE_HOLE_DATASET
CHECK_P4 = "Revisión del taller"
GUARD_LABEL = "Resguardo de la zona protegida"
"""La etiqueta (en español) del parámetro ``guard_m`` de una plataforma."""


def sha256(path: Any) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(found: float, expected: float, *, relative: float = 1e-9) -> bool:
    """Si ``found`` es ``expected`` a ≤ ``relative`` relativo (y exacto si ``expected`` es cero)."""
    return found == expected if expected == 0.0 else abs(found - expected) / abs(expected) <= relative


class HandCase:
    """Las cuentas a mano de las tres clases: la huella de «Plataforma de la balsa» **por su geometría** (no por la
    tabla que escribe la entidad) y lo apoyado por una superficie con la fórmula de RF-015-15
    (``a = r − máx(partida, entidad)`` sobre las celdas con ``a`` mayor que el espesor mínimo)."""

    def footprint_by_hand(self) -> np.ndarray:
        """Las celdas del eje de 30 m con 6 m de ancho (véase :data:`FOOTPRINT_CELLS`), de la rejilla gruesa."""
        x, y = qfx.local_centers(self.grid)  # type: ignore[attr-defined]
        return (x >= 135.0) & (x <= 165.0) & (y > 302.0) & (y < 308.0)

    @staticmethod
    def supported(result: np.ndarray, start: np.ndarray, entity: np.ndarray, where: np.ndarray) -> float:
        """Los m³ que ``result`` apoya sobre ``entity`` en las celdas ``where``, **celda a celda** y sumados exactos."""
        with np.errstate(invalid="ignore"):
            thick = result[where] - np.maximum(start[where], entity[where])
        return math.fsum(float(value) for value in thick if value > THICKNESS_M) * CELL_M2

    def read(self, name: str, version: Any = None) -> np.ndarray:
        """La rejilla del dato ``name`` de ``version`` (por defecto V01) tal como está en su fichero."""
        record = self.record(name, self.v1 if version is None else version)  # type: ignore[attr-defined]
        return geotiff_reader.read_geotiff(self.root / record.locator).values  # type: ignore[attr-defined]


def world_definitions() -> tuple[Any, ...]:
    """Los tipos de la 013, la 014, la 015 y la 012 con las funciones **reales** de recálculo y reproducción
    (las que registrará ``bl``): lo necesario para «Recalcular lo obsoleto» de punta a punta."""
    design = [provenance.operation_def(op_type, fill_test.recompute_function)
              for op_type in (*provenance.REPRODUCIBLE, *provenance.QUARRY_VERSION_TYPES)]
    verification = cstore.operation_def(dep.recompute_verification, cstore.REPRODUCE[cstore.VERIFY])
    return (*decl.declare_definitions(), *design, *provenance.FIGURES, *provenance.QUARRY_FIGURES, verification,
            *cstore.FIGURES)


# ---------------------------------------------------------------------------------------------
# CE-015-01 y E3: las dependencias entre plataformas
# ---------------------------------------------------------------------------------------------


class DependenciesTest(chain_test.ChainCase, dep.DependentsCase, HandCase):
    """CE-015-01 y E3, en el orden de las pruebas (cada una parte de lo que dejó la anterior), sobre V01: P1 («Plataforma
    de la balsa», del terreno), P2 («Sobre la balsa», «en corte y relleno» **de la superficie de P1**), P3 («Arrastra el
    terreno», de la de P2), P4 («Plataforma de taller», de otro terreno, que **declara** apoyarse en P1) con su
    verificación, P5 («Explanada con eje», de otro terreno, que también lo declara), el «solo relleno» «Balsa 2» y la
    verificación de P2. (a) detectada y declarada, (b) la cascada, (c) recalcular, (d) traerlas a otra versión, (e) la
    lista antes, (f) descartar P1, (g) la versión hija y las tres salidas: (h) rehacer, (i) descartar y (j) dar por
    buena, y (k) lo que queda para «Recalcular lo obsoleto»."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return world_definitions()

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()  # P1, P2, P3, «Balsa 2» y la verificación de P2 (T24)
        cls.made(prep.request(WORKSHOP, start=HOLE))  # PLT-004
        cls.made(prep.polygon_request(WITH_AXIS, start=EDGE_HOLE))  # PLT-005
        for code in ("PLT-004", "PLT-005"):  # lo declara la persona: se registra al recalcular
            cls.declare_support(code, "PLT-001")
            cls.remake(code)
        cls.clock.advance(minutes=1)
        sup.finish(cstore.verify_project_steps(
            cls.project, version=cls.v1.uid, name=CHECK_P4,
            start=surfaces.SurfaceRef(dataset=HOLE, label="Partida"),
            finals=(surfaces.SurfaceRef(dataset=provenance.dataset_name("psf", WORKSHOP), label=WORKSHOP),)))

    # --- Ayudas -------------------------------------------------------------------------------

    @classmethod
    def declare_support(cls, code: str, text: str) -> None:
        """La persona declara que la entidad ``code`` se apoya en ``text`` (parámetro de versión, ADOPTADO)."""
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).create(
                conn, design_params.entity_key(code, "supports"), text, kind="ADOPTADO", source="Criterio de la prueba",
                source_kind="person", decided_by=BY, reason="Dependencia declarada", version=cls.v1.uid)

    @classmethod
    def remake(cls, code: str) -> None:
        """«Recalcular» la entidad ``code`` con sus parámetros de ahora (su función de recálculo de ``des``)."""
        cls.clock.advance(minutes=1)
        entry = entities.registry(cls.project, cls.v1.uid).get(code)
        ((settings,),) = cls.query_of("SELECT settings FROM gb_operation WHERE uid = ?", entry.operation_uid)
        request = recompute_mod.RecomputeRequest(cls.project, str(entry.operation_uid), provenance.PLATFORM,
                                                 json.loads(settings), (), (), version=cls.v1.uid)
        _handle, work = design_store.recompute_run(request)
        sup.finish(work)

    def name_of(self, uid: str) -> str:
        """El nombre de la operación ``uid`` (el de sus ajustes o, sin él, su tipo)."""
        ((op_type, settings),) = self.query("SELECT op_type, settings FROM gb_operation WHERE uid = ?", uid)
        return str(json.loads(settings).get("name", op_type))

    def plan_names(self) -> list[list[str]]:
        """Los nombres de las operaciones de cada unidad del plan de «Recalcular lo obsoleto», en su orden."""
        return [[self.name_of(uid) for uid in unit] for unit in self.plan_units()]

    def states(self) -> dict[str, EntityState]:
        return {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}

    def recompute_all(self) -> list[list[tuple[str, str]]]:
        """«Recalcular lo obsoleto» **tantas veces como haga falta** (una pasada = una llamada de la orden): lo hecho por
        pasada, como ``(estado, nombre)``; se para al no quedar nada o al no hacerse nada más."""
        passes: list[list[tuple[str, str]]] = []
        for _ in range(8):
            if not self.recompute_plan():
                break
            self.clock.advance(minutes=1)
            outcome = ops_test.finish(recompute_mod.recompute_steps(self.project))
            passes.append([(str(result.status), self.name_of(result.unit.operations[0])) for result in outcome.results])
        return passes

    def supported_of(self, code: str) -> dict[str, float | None]:
        """Lo que se apoya en la entidad ``code`` ahora (la lista de la T24), por nombre, con su volumen."""
        return {row.name: row.volume_m3 for row in entities.dependents(self.project, self.v1.uid, code)}

    # --- (a) Detectada y declarada ------------------------------------------------------------

    def test_a1_the_platform_that_fills_on_another_rests_on_it_with_the_volume_by_hand(self) -> None:
        """CE-015-01, RF-015-15 (D-11, D-9): P2 («en corte y relleno», de la superficie de P1) rellena 2 m sobre la huella
        de P1, que son 48 celdas de 4 m² (**por su geometría**, no por la tabla de la entidad): **384 m³ a mano**; la
        operación de P2 anota la superficie de P1 como ``supported_on`` y la tabla de su huella, y la cifra
        ``des.supported_m3`` con el ámbito de P1 —CALCULADO, en m³— y la lista de lo que se apoya en P1 dan lo mismo,
        a ≤ 10⁻⁹ relativo, que el cálculo celda a celda sobre los ficheros."""
        foot = self.footprint_by_hand()
        self.assertEqual(int(foot.sum()), FOOTPRINT_CELLS)
        self.assertEqual(int(self.cells_of(dep.EPR1)), FOOTPRINT_CELLS, "la tabla de P1 tiene las mismas celdas")
        by_files = self.supported(self.read(dep.PSF2), self.read(dep.PSF1), self.read(dep.PSF1), foot)
        self.assertTrue(close(by_files, FILL_BY_HAND_M3), by_files)
        uid = self.current("PLT-002")
        self.assertEqual(self.supports_of(uid), [(dep.PSF1, "supported_on"), (dep.EPR1, "support_footprint")])
        registered = self.volumes_of(uid)
        self.assertEqual(list(registered), ["PLT-001"])
        self.assertTrue(close(registered["PLT-001"], FILL_BY_HAND_M3), registered)
        self.assertEqual(self.query("SELECT unit, kind FROM gb_figure WHERE operation_uid = ? AND key = "
                                    "'des.supported_m3'", uid), [("m3", "CALCULADO")])
        listed = self.supported_of("PLT-001")
        self.assertTrue(close(listed[ON_TOP], FILL_BY_HAND_M3), listed)
        oracle = self.supported(self.read(dep.TWIN_SURFACE), qfx.terrain(self.grid), self.read(dep.PSF1), foot)
        self.assertGreater(oracle, 100.0)
        self.assertTrue(close(listed[TWIN], oracle), (listed[TWIN], oracle))

    def test_a2_a_dependency_declared_by_the_person_is_registered_the_same(self) -> None:
        """CE-015-01, RF-015-15 (D-11): P4 y P5 **declaran** apoyarse en P1 y no comparten con ella ni una celda: se
        registran **igual** que la detectada —la superficie de P1 como ``supported_on``, la tabla de su huella y la cifra
        ``des.supported_m3`` con el ámbito de P1—, con **0 m³**, y salen en lo que se apoya en P1 y en «en qué se apoya» la
        suya."""
        for code, name in (("PLT-004", WORKSHOP), ("PLT-005", WITH_AXIS)):
            with self.subTest(entity=code):
                uid = self.current(code)
                self.assertEqual(self.supports_of(uid), [(dep.PSF1, "supported_on"), (dep.EPR1, "support_footprint")])
                self.assertEqual(self.volumes_of(uid), {"PLT-001": 0.0})
                self.assertEqual(self.supported_of("PLT-001")[name], 0.0)
                rests = [(row.entity, row.roles, row.volume_m3)
                         for row in entities.dependencies_of(self.project, self.v1.uid, code)]
                self.assertEqual(rests[0], ("PLT-001", ("supported_on",), 0.0))
        self.assertEqual(entity_store.declared_supports(self.project, self.v1, "PLT-004"), ("PLT-001",))

    def test_a3_one_list_gives_every_one_with_its_volume(self) -> None:
        """CE-015-01, RF-015-15, RF-015-17: lo que se apoya en P1 es **una sola lista**, por orden de registro, con el
        nombre, el tipo y el volumen de cada uno: P2 (los 384 m³), «Balsa 2» (el suyo), P4 y P5 (los declarados, 0 m³)."""
        found = entities.dependents(self.project, self.v1.uid, "PLT-001")
        self.assertEqual([(row.name, row.op_type) for row in found],
                         [(ON_TOP, "des.platform"), (TWIN, "des.fill_only"), (WORKSHOP, "des.platform"),
                          (WITH_AXIS, "des.platform")])
        self.assertTrue(all(row.volume_m3 is not None for row in found))
        self.assertEqual([row.volume_m3 for row in found[2:]], [0.0, 0.0])
        shown = [row.text("es") for row in found]
        self.assertTrue(shown[0].startswith(f"{ON_TOP} (Plataforma): 384 m³"), shown[0])
        self.assertEqual(shown[2], f"{WORKSHOP} (Plataforma): 0 m³ apoyados")

    # --- (b) Cambiar P1: la cascada, con su causa (E3) ----------------------------------------

    def test_b_changing_the_first_platform_makes_everything_that_rests_on_it_obsolete_with_the_cause(self) -> None:
        """CE-015-01, RF-015-16, E3 (cambiar una entidad y ver la cascada): la pendiente de P1 pasa de 0 a 0,5 %: quedan
        obsoletas **con la misma causa raíz** (el cambio de la pendiente de P1) P1, P2 (que parte de su superficie), P3, «Balsa 2»,
        P4, P5 y las dos verificaciones; el motivo legible dice qué entidad y qué cambió (su nombre, no su código) y
        «Recalcular lo obsoleto» las pone **en orden de dependencia** (P1 antes que P2, que parte de ella)."""
        for code in ("PLT-001", "PLT-002", "PLT-003", "PLT-004", "PLT-005"):
            self.assertEqual(self.stale_causes(self.current(code)), set(), "antes de cambiar nada, todo al día")
        self.assertEqual(self.recompute_plan(), [])
        self.change(GRADIENT, SLOPE_PCT)
        every = {code: self.current(code) for code in ("PLT-001", "PLT-002", "PLT-003", "PLT-004", "PLT-005")}
        every |= {"twin": self.fill_uid(), "check": self.check_uid()}
        for name, uid in every.items():
            self.assertEqual(self.stale_causes(uid), {("parameter_changed", GRADIENT)}, name)
        wanted = f"Obsoleto: cambió {dep.LABEL} · {BALSA}"
        for code in ("PLT-002", "PLT-003", "PLT-004", "PLT-005"):
            self.assertEqual(entities.stale_reason(self.project, self.v1.uid, code), wanted, code)
        self.assertEqual(entities.operation_reason(self.project, self.v1.uid, every["twin"]), wanted)
        self.assertTrue(set(self.states().values()) == {EntityState.STALE})
        order = [unit[0] for unit in self.plan_names()]
        self.assertLess(order.index(BALSA), order.index(ON_TOP), "P1 antes que P2, que parte de su superficie")
        self.assertLess(order.index(ON_TOP), order.index(DRAG))
        self.assertEqual(len(order), 8)

    def test_c_recomputing_in_order_leaves_nothing_obsolete_and_measures_what_rests_on_it_again(self) -> None:
        """CE-015-01, RF-015-16, RF-008-26, CE-015-05 (D-9): «Recalcular lo obsoleto» rehace lo obsoleto en orden y no
        queda nada; P2 sigue apoyada en P1, ahora con el volumen de la rasante nueva (0,5 %): **369,6 m³ a mano** (la
        columna de abscisa σ rellena ``2 − 0,005·σ`` m en tres filas), medido otra vez sobre las superficies nuevas, y
        P4 y P5, con 0 m³ (siguen declaradas)."""
        before = self.hashes_of(self.current("PLT-001"))
        check = self.check_op_of(CHECK_P4)
        passes = self.recompute_all()
        self.assertEqual(self.recompute_plan(), [])
        self.assertTrue(all(status == str(recompute_mod.UnitStatus.DONE) for units in passes for status, _ in units))
        redone = sorted(name for units in passes for _status, name in units)
        self.assertEqual(redone, sorted([BALSA, ON_TOP, DRAG, TWIN, dep.CHECK, WORKSHOP, WITH_AXIS]),
                         "se rehace lo obsoleto, cada una una vez")
        self.assertEqual(self.check_op_of(CHECK_P4), check, "la verificación de P4 pierde la marca sin recalcularse: la "
                                                            "salida de P4 (que solo declara) salió igual (RF-008-26)")
        self.assertEqual(self.stale_causes(check), set())
        self.assertEqual(set(self.states().values()), {EntityState.CURRENT})
        self.assertNotEqual(self.hashes_of(self.current("PLT-001"))[dep.PSF1], before[dep.PSF1], "la rasante cambió")
        listed = self.supported_of("PLT-001")
        self.assertTrue(close(listed[ON_TOP], FILL_AFTER_BY_HAND_M3), (listed[ON_TOP], FILL_AFTER_BY_HAND_M3))
        self.assertAlmostEqual(FILL_AFTER_BY_HAND_M3, 369.6, places=9)
        by_files = self.supported(self.read(dep.PSF2), self.read(dep.PSF1), self.read(dep.PSF1),
                                  self.footprint_by_hand())
        self.assertTrue(close(by_files, FILL_AFTER_BY_HAND_M3), by_files)
        self.assertEqual((listed[WORKSHOP], listed[WITH_AXIS]), (0.0, 0.0))
        self.assertTrue(close(self.volumes_of(self.current("PLT-002"))["PLT-001"], FILL_AFTER_BY_HAND_M3))

    # --- (d) Traerlas a otra versión: sin calcular y la dependencia se detecta de nuevo -------------

    def test_d_brought_to_another_version_they_are_not_calculated_and_the_dependency_is_detected_again(self) -> None:
        """CE-015-01, RF-015-18, RF-009-01, D-18: traer P1 y P2 de V01 a V02 deja **sus definiciones sin calcular** (sin
        ninguna superficie, operación ni cifra en V02; V01 no cambia: los mismos datos, operaciones y cifras); al
        calcularlas allí (P1 y después P2, con su código y sus campos de la capa) **la dependencia se detecta de nuevo**:
        la operación de P2 anota la superficie de P1 de V02 como ``supported_on`` y la cifra vale lo mismo que en V01
        (369,6 m³ a mano, ya con la pendiente de P1 de V01, que se trae)."""
        before = self.written()
        found = entity_store.bring_entities(self.project, "V01", "V02", codes=["PLT-001", "PLT-002"])
        self.assertEqual([(item.source_code, item.code) for item in found.entities],
                         [("PLT-001", "PLT-001"), ("PLT-002", "PLT-002")])
        results = {"datasets": self.query("SELECT name FROM gb_dataset WHERE version_uid = ?", self.v2.uid),
                   "operations": self.query("SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON "
                                            "r.uid = o.revision_uid WHERE r.version_uid = ?", self.v2.uid)}
        self.assertEqual(results, {"datasets": [], "operations": []})
        v2 = {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v2.uid)}
        self.assertEqual(v2, {"PLT-001": EntityState.UNCALCULATED, "PLT-002": EntityState.UNCALCULATED})
        self.assertEqual(entities.registry(self.project, self.v2.uid).get("PLT-002").record.start, "entity:PLT-001")
        for key in ("operations", "datasets", "io", "figures", "files"):
            self.assertEqual(self.written()[key], before[key], f"V01: {key}")
        self.clock.advance(minutes=1)
        for _step in access.ensure_masks_steps(self.project, self.v2.uid):
            pass
        masks = access.load_masks(self.project, self.v2.uid)
        self.clock.advance(minutes=1)
        first = self.calculate_in(sup.asked(BALSA), version=self.v2.uid, masks=masks, code="PLT-001").create()
        self.clock.advance(minutes=1)
        second = self.calculate_in(dep.on_top(), version=self.v2.uid, masks=masks, code="PLT-002").create()
        self.assertEqual(self.supports_of(first.handle.uid), [])
        self.assertEqual(self.supports_of(second.handle.uid), [(dep.PSF1, "supported_on"), (dep.EPR1, "support_footprint")])
        again = self.volumes_of(second.handle.uid)
        self.assertEqual(list(again), ["PLT-001"])
        self.assertTrue(close(again["PLT-001"], FILL_AFTER_BY_HAND_M3), again)
        by_files = self.supported(self.read(dep.PSF2, self.v2), self.read(dep.PSF1, self.v2),
                                  self.read(dep.PSF1, self.v2), self.footprint_by_hand())
        self.assertTrue(close(by_files, FILL_AFTER_BY_HAND_M3), by_files)
        self.assertTrue(close(again["PLT-001"], self.volumes_of(self.current("PLT-002"))["PLT-001"]))
        self.assertEqual({entry.record.code: entry.record.state
                          for entry in entities.registry(self.project, self.v2.uid)},
                         {"PLT-001": EntityState.CURRENT, "PLT-002": EntityState.CURRENT})

    # --- (e) La lista de antes de descartar y (f) descartar P1 -----------------------------------

    def test_e_before_discarding_one_list_gives_what_rests_on_it_with_its_volume(self) -> None:
        """CE-015-01, RF-015-17, E3 (la lista antes): antes de descartar P1, **una sola lista** da lo que se le apoya y lo
        que parte de ella —nombre, tipo y volumen apoyado en m³—: P2 (369,6 m³ a mano), «Balsa 2», P4 y P5 (0 m³); no
        escribe nada, y es la misma lista de ``entities.dependents``."""
        before = self.written()
        plan = entity_store.discard_plan(self.project, self.v1.uid, "PLT-001")
        self.assertEqual(self.written(), before, "la lista no escribe nada")
        self.assertEqual((plan.code, plan.name, plan.state, plan.calculated), ("PLT-001", BALSA, EntityState.CURRENT, True))
        self.assertEqual(plan.dependents, entities.dependents(self.project, self.v1.uid, "PLT-001"))
        self.assertEqual([(row.name, row.op_type) for row in plan.dependents],
                         [(ON_TOP, "des.platform"), (TWIN, "des.fill_only"), (WORKSHOP, "des.platform"),
                          (WITH_AXIS, "des.platform")])
        self.assertTrue(close(plan.dependents[0].volume_m3, FILL_AFTER_BY_HAND_M3))
        lines = plan.lines("es")
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith(f"{ON_TOP} (Plataforma): "), lines[0])
        self.assertIn(UNIT, lines[0])

    def test_f_discarding_the_first_platform_leaves_what_rested_on_it_as_support_removed_and_not_recomputed(self) -> None:
        """CE-015-01, RF-015-17, RF-009-12, E3, error 59: descartar P1 (con el motivo y quién; lo que sigue con
        ``discard_entity_steps``) pone sus tres datos «descartados» **sin borrar nada** y un evento con la lista de lo que se
        le apoyaba; P2, P4, P5 y «Balsa 2», que se apoyaban en ella, quedan en **«apoyo retirado»**, con la causa
        («Apoyo retirado: se descartó la plataforma …»); P3, que parte de P2, obsoleta; y «Recalcular lo obsoleto»
        **no recalcula** nada de eso: la primera unidad se rehúsa («se descartó y no tiene sucesor»,
        ``core.recompute_no_successor_release``) y no se crea ninguna operación."""
        listed = entity_store.discard_plan(self.project, self.v1.uid, "PLT-001")
        before = self.written()
        files = sorted(path.name for path in (self.root / "rasters").iterdir())
        self.clock.advance(minutes=1)
        result = ops_test.finish(entity_store.discard_entity_steps(self.project, self.v1.uid, "PLT-001", reason=WHY,
                                                                   decided_by=BY))
        self.assertEqual(result.discarded.dependents, listed.dependents, "la lista que se enseñó es la que se registra")
        self.assertIsNone(result.chain.failure)
        self.assertEqual(set(result.discarded.datasets), {dep.PSF1, dep.EPR1, provenance.dataset_name("prp", BALSA)})
        after = self.written()
        for key in ("operations", "io", "figures", "tables"):  # nada se borra (RF-009-12): lo de antes sigue
            self.assertTrue(all(row in after[key] for row in before[key]), f"{key}: algo desapareció")
        self.assertGreaterEqual(len(after["datasets"]), len(before["datasets"]), "ningún dato desaparece")
        self.assertEqual(sorted(path.name for path in (self.root / "rasters").iterdir()), files, "ningún fichero se borra")
        self.assertEqual(self.states(), {
            "PLT-001": EntityState.DISCARDED, "PLT-002": EntityState.SUPPORT_REMOVED, "PLT-003": EntityState.STALE,
            "PLT-004": EntityState.SUPPORT_REMOVED, "PLT-005": EntityState.SUPPORT_REMOVED})
        wanted = f"Apoyo retirado: se descartó la plataforma {BALSA}"
        for code in ("PLT-002", "PLT-004", "PLT-005"):
            self.assertEqual(entities.stale_reason(self.project, self.v1.uid, code), wanted, code)
        self.assertEqual(entities.operation_reason(self.project, self.v1.uid, self.fill_uid()), wanted)
        retired = {row.name for row in entities.retired_supports(self.project, self.v1.uid)}
        self.assertEqual(retired, {ON_TOP, TWIN, WORKSHOP, WITH_AXIS})
        (event,) = [item for item in self._events(events.EventKind.ENTITY_DISCARDED)]
        self.assertEqual((event.data["entity"], event.data["reason"], event.data["decided_by"]), ("PLT-001", WHY, BY))
        self.assertEqual({item["name"] for item in event.data["dependents"]}, {ON_TOP, TWIN, WORKSHOP, WITH_AXIS})
        # «Recalcular lo obsoleto» no recalcula lo apoyado
        operations = self.query("SELECT uid, status FROM gb_operation ORDER BY fid")
        self.clock.advance(minutes=1)
        outcome = ops_test.finish(recompute_mod.recompute_steps(self.project))
        self.assertTrue(outcome.results)
        refused = [result for result in outcome.results if result.status is recompute_mod.UnitStatus.REFUSED]
        self.assertEqual({result.code for result in refused}, {"core.recompute_no_successor_release"})
        self.assertIn("se descartó y no tiene sucesor", refused[0].reason)
        self.assertEqual([result.status for result in outcome.results].count(recompute_mod.UnitStatus.DONE), 0)
        self.assertEqual(self.query("SELECT uid, status FROM gb_operation ORDER BY fid"), operations,
                         "no se crea ninguna operación")
        self.assertEqual(self.states()["PLT-002"], EntityState.SUPPORT_REMOVED)
        self.assertIn(ON_TOP, [unit[0] for unit in self.plan_names()], "sigue en el plan: se rehúsa, no se recalcula")

    def _events(self, kind: Any) -> list[Any]:
        with self.project.read() as conn:
            return events.read_events(conn, kind)

    # --- (g) La versión hija recibe descartada la que se descartó con datos ----------------------

    def test_g_a_version_that_starts_from_this_one_gets_the_discarded_one_discarded_and_it_is_not_brought(self) -> None:
        """CE-015-01, RF-015-17, RF-015-18, RF-009-01, D-12 (hallazgo (a) de la T26): V03 parte de V01 y hereda los
        parámetros, no los resultados: P1, descartada con datos, llega **descartada** (no «viva y sin calcular»: no ocupa
        su partida ni su nombre) y los demás, sin calcular; «Traer las entidades de V01…» a otra versión no la trae y
        pedirla es ``des.entity_bring_discarded``."""
        self.clock.advance(minutes=1)
        child = create_version(self.project, feature="Hija", title="Hija de V01", parent="V01")
        mine = {entry.record.code: entry.record.state for entry in entities.registry(self.project, child.uid)}
        self.assertEqual(mine["PLT-001"], EntityState.DISCARDED)
        self.assertEqual({code for code, state in mine.items() if state is EntityState.UNCALCULATED},
                         {"PLT-002", "PLT-003", "PLT-004", "PLT-005"})
        with self.assertRaises(DesignError) as asked:
            entity_store.bring_entities(self.project, "V01", child.code, codes=["PLT-001"])
        self.assertEqual(asked.exception.code, "des.entity_bring_discarded")
        target = create_version(self.project, feature="Destino", title="Destino")
        brought = entity_store.bring_entities(self.project, "V01", target.code)
        self.assertNotIn("PLT-001", [item.source_code for item in brought.entities])
        self.assertEqual(len(brought.entities), 4)

    # --- (h) a (j) Las tres salidas -----------------------------------------------------------

    def test_h_remaking_it_on_another_surface_takes_it_out_of_support_removed(self) -> None:
        """CE-015-01, RF-015-17 (salida 1, «rehacerla sobre otra superficie»), error 59: P2 parte de la superficie de P1
        (descartada): su partida pasa al terreno (que P1, descartada, ya no ocupa) y se recalcula con
        ``platform_run(code=, supersedes=)``; la operación nueva sustituye a la anterior (queda como historia), P2 **sale de
        «apoyo retirado»** (al día, sin ninguna dependencia de P1) y de lo que se apoya en P1; P3, que parte de su
        superficie, queda obsoleta y **ahora sí** se puede recalcular."""
        old = self.current("PLT-002")
        self.change(design_params.entity_key("PLT-002", "start"), START)
        self.clock.advance(minutes=1)
        asked = prep.request(ON_TOP, fields=prep.line_fields(dep.ON_TOP_LAYER), start=START, mode=model.PlatformMode.CUT_FILL)
        made = self.calculate_in(asked, masks=None, code="PLT-002", supersedes=old).create()
        self.assertNotEqual(made.handle.uid, old)
        self.assertEqual(self.current("PLT-002"), made.handle.uid)
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old), [(made.handle.uid,)])
        self.assertEqual(self.states()["PLT-002"], EntityState.CURRENT)
        self.assertEqual(self.supports_of(made.handle.uid), [])
        self.assertIsNone(entities.stale_reason(self.project, self.v1.uid, "PLT-002"))
        self.assertNotIn(ON_TOP, self.supported_of("PLT-001"))
        (rests,) = entities.dependencies_of(self.project, self.v1.uid, "PLT-002")
        self.assertEqual((rests.name, rests.entity), (START, None), "parte del terreno")
        self.assertEqual(self.states()["PLT-003"], EntityState.STALE)

    def test_i_discarding_it_leaves_it_as_a_record_with_its_own_event(self) -> None:
        """CE-015-01, RF-015-17, RF-009-12 (salida 2, «descartarla»), error 59: P5, que se apoyaba en P1 (declarada), se
        descarta con su motivo: **nada se borra** (sus tres datos pasan a «descartados»), su lista de lo que se le apoya
        está vacía y deja su evento; sigue siendo un registro (descartada) y su código no se reutiliza."""
        plan = entity_store.discard_plan(self.project, self.v1.uid, "PLT-005")
        self.assertEqual(plan.dependents, ())
        self.clock.advance(minutes=1)
        found = entity_store.discard_entity(self.project, self.v1.uid, "PLT-005", reason=WHY, decided_by=BY)
        self.assertEqual(set(found.datasets), {provenance.dataset_name(family, WITH_AXIS) for family in ("psf", "epr", "prp")})
        self.assertEqual(self.states()["PLT-005"], EntityState.DISCARDED)
        self.assertEqual([item.data["entity"] for item in self._events(events.EventKind.ENTITY_DISCARDED)],
                         ["PLT-001", "PLT-005"])
        self.assertNotIn(WITH_AXIS, [row.name for row in entities.retired_supports(self.project, self.v1.uid)])
        self.assertEqual(entities.next_code(entities.EntityKind.PLATFORM, self.states()), "PLT-006")

    def test_j_giving_it_as_good_with_a_reason_does_not_change_its_output_nor_recompute_what_depends_on_it(self) -> None:
        """CE-015-01, RF-015-17, RF-008-26, RF-008-27 (salida 3, «darla por buena con un motivo»), error 59: P4 (declaró
        apoyarse en P1, sin partir de su superficie) se repite **sin ese apoyo** con el motivo y el decisor en sus ajustes
        (``supports_released``) y un evento ``support_released``; su salida **no cambia** (los mismos hash), sale de «apoyo
        retirado» y la verificación que consumió su superficie **no se recalcula** (sigue siendo la misma operación) y deja
        de estar obsoleta."""
        old, check = self.current("PLT-004"), self.check_op_of(CHECK_P4)
        hashes = self.hashes_of(old)
        self.assertNotEqual(self.stale_causes(check), set(), "antes, la verificación de P4 está obsoleta en cascada")
        self.clock.advance(minutes=1)
        handle, work = entity_store.release_support(self.project, self.v1.uid, "PLT-004", "PLT-001", reason=WHY,
                                                    decided_by=BY)
        sup.finish(work)
        new = handle.uid
        self.assertEqual(self.current("PLT-004"), new)
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old), [(new,)])
        self.assertEqual(self.hashes_of(new), hashes, "su salida no cambia")
        self.assertEqual(self.supports_of(new), [])
        self.assertEqual(self.states()["PLT-004"], EntityState.CURRENT)
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", new)
        (released,) = json.loads(settings)["supports_released"]
        self.assertEqual({key: released[key] for key in ("entity", "reason", "by")},
                         {"entity": "PLT-001", "reason": WHY, "by": BY})
        (event,) = self._events(events.EventKind.SUPPORT_RELEASED)
        self.assertEqual((event.data["name"], event.data["reason"], event.data["decided_by"], event.data["entities"]),
                         (WORKSHOP, WHY, BY, ["PLT-001"]))
        self.assertEqual(self.check_op_of(CHECK_P4), check, "lo que dependía de ella no se recalcula")
        self.assertEqual(self.stale_causes(check), set(), "y deja de estar obsoleto: su entrada es la misma")
        self.assertNotIn(WORKSHOP, self.supported_of("PLT-001"))
        key = design_params.entity_key("PLT-004", "supports")
        self.assertEqual(core_params.ParameterStore(self.project).get(key, version=self.v1.uid).value, "PLT-001",
                         "lo que la persona declaró sigue como lo puso")

    def check_op_of(self, name: str) -> str:
        """El uid de la verificación vigente llamada ``name``."""
        rows = self.query("SELECT uid, settings FROM gb_operation WHERE op_type = ? AND status = 'done' AND "
                          "superseded_by IS NULL", cstore.VERIFY)
        (found,) = [uid for uid, settings in rows if json.loads(settings).get("name") == name]
        return str(found)

    # --- (k) Lo que queda para «Recalcular lo obsoleto» --------------------------------------------

    def test_k_what_is_left_to_recompute_is_what_can_be_and_the_rest_waits_for_its_decision(self) -> None:
        """CE-015-01, RF-015-17, E3: con P2 rehecha, P4 dada por buena y P5 descartada, «Recalcular lo obsoleto» rehace
        **lo que se puede** (P3, que parte de la superficie nueva de P2, la verificación de P2 y la capa de entidades) y **sigue sin recalcular**
        «Balsa 2», que se apoya en P1 descartada y aún espera su decisión (``core.recompute_no_successor_release``); no se
        inventa ninguna decisión y P1 sigue siendo un registro."""
        self.assertIn(TWIN, {row.name for row in entities.retired_supports(self.project, self.v1.uid)})
        twin = self.fill_uid()
        self.clock.advance(minutes=1)
        outcome = ops_test.finish(recompute_mod.recompute_steps(self.project))
        done = {self.name_of(result.unit.operations[0]) for result in outcome.results
                if result.status is recompute_mod.UnitStatus.DONE}
        refused = {self.name_of(result.unit.operations[0]) for result in outcome.results
                   if result.status is recompute_mod.UnitStatus.REFUSED}
        self.assertEqual(done, {DRAG, dep.CHECK, "des.entity_layer"},
                         "y la capa de entidades: P5, descartada, ya no la retiene (T40, C-4 y E-3)")
        self.assertIn(TWIN, refused)
        self.assertEqual(refused, {TWIN}, "P5, descartada, ya no vuelve al plan ni se rehúsa (T40, hallazgos C-4 y E-3)")
        self.assertEqual({result.status for result in outcome.results} - {recompute_mod.UnitStatus.DONE,
                                                                          recompute_mod.UnitStatus.REFUSED}, set(),
                         "ninguna unidad falla")
        self.assertEqual(self.fill_uid(), twin, "«Balsa 2» sigue siendo la de antes: espera su decisión")
        self.assertEqual(self.states(), {
            "PLT-001": EntityState.DISCARDED, "PLT-002": EntityState.CURRENT, "PLT-003": EntityState.CURRENT,
            "PLT-004": EntityState.CURRENT, "PLT-005": EntityState.DISCARDED})
        self.assertEqual([row.name for row in entities.retired_supports(self.project, self.v1.uid)], [TWIN])


# ---------------------------------------------------------------------------------------------
# CE-015-04 y E3: la plataforma que protege
# ---------------------------------------------------------------------------------------------


class ProtectedPlatformTest(chain_test.ChainCase, sup.SupportsCase, HandCase):
    """CE-015-04 y E3, en el orden de las pruebas, sobre V01 con la envolvente de la lámina de agua de la 014: (a) lo que
    rellenaría «Balsa 2» sin proteger, (b) P1 («Plataforma de la balsa», «en corte», 255 m) que protege con 4 m, (c) el
    «solo relleno» con la restricción, (d) la plataforma «en corte y relleno» que la solapa, (e) la verificación de la 012,
    (f) cambiar su propia restricción, (g) lo que no se admite («en corte y relleno» que protege) y (h) descartarla."""

    GUARD_M = 4.0
    CODE = "dec__plt_001"
    ZONE_CELLS = (16 + 4) * (3 + 4)
    """La zona de la restricción, a mano: la huella (16 × 3) ensanchada 4 m = dos celdas de 2 m por cada lado."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return world_definitions()

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
            fill_test.declare(cls.project, cls.clock, design_params.bench_key(fill_test.REST.code, param),
                              getattr(fill_test.REST, param))
        envelope = model.EnvelopeRequest(
            fill_test.ENVELOPE, "down",
            model.SeedSource("fixed", zone=model.Zone("layer", qfx.WATER_LAYER),
                             elevation_m=fill_test.ENVELOPE_LEVEL_M),
            slope_deg=fill_test.ENVELOPE_SLOPE_DEG)
        cls.clock.advance(minutes=1)
        fill_test.drive(steps.envelope_run(cls.project, envelope, version=cls.v1.uid,
                                           masks=cls.masks_v1)).result.create()
        qfx.write_feature_layer(cls.project, cls.clock, dep.on_top_layer())

    # --- Ayudas -------------------------------------------------------------------------------

    def fill_calculation(self, name: str = TWIN) -> Any:
        """«Calcular» el «solo relleno» ``name`` con las máscaras de ahora (sin crearlo)."""
        self.clock.advance(minutes=1)
        masks = access.load_masks(self.project, self.v1.uid)
        return fill_test.drive(steps.fill_only_run(
            self.project, model.FillOnlyRequest(name, fill_test.ENVELOPE, START, fill_test.REST.code,
                                                water=fill_test.WATER),
            version=self.v1.uid, masks=masks)).result

    def fill_in(self, surface: np.ndarray, where: np.ndarray) -> float:
        """Los m³ que ``surface`` sube sobre el terreno en las celdas ``where``."""
        gained = surface[where] - qfx.terrain(self.grid)[where]
        return math.fsum(float(value) for value in gained if value > 0.0) * CELL_M2

    def zone(self) -> np.ndarray:
        """La zona de la restricción declarada por P1 en las máscaras vigentes."""
        masks = access.load_masks(self.project, self.v1.uid)
        return np.asarray(masks.zone(self.CODE).mask(self.grid.shape))

    def name_of(self, uid: str) -> str:
        """El nombre de la operación ``uid`` (el de sus ajustes o, sin él, su tipo)."""
        ((op_type, settings),) = self.query("SELECT op_type, settings FROM gb_operation WHERE uid = ?", uid)
        return str(json.loads(settings).get("name", op_type))

    def plan_names(self) -> list[list[str]]:
        """Los nombres de las operaciones de cada unidad del plan de «Recalcular lo obsoleto», en su orden."""
        return [[self.name_of(uid) for uid in unit] for unit in self.plan_units()]

    def passes(self) -> list[list[tuple[str, str]]]:
        """«Recalcular lo obsoleto» tantas veces como haga falta: lo hecho en cada pasada, como ``(estado, tipo)``."""
        found: list[list[tuple[str, str]]] = []
        for _ in range(8):
            if not self.recompute_plan():
                break
            self.clock.advance(minutes=1)
            outcome = ops_test.finish(recompute_mod.recompute_steps(self.project))
            found.append([(str(result.status), self.query("SELECT op_type FROM gb_operation WHERE uid = ?",
                                                           result.unit.operations[0])[0][0])
                          for result in outcome.results])
        return found

    def listed(self) -> tuple[Any, ...]:
        return masks_store.listed_constraints(self.project, version=self.v1.uid)

    def figure_value(self, uid: str, key: str) -> float:
        return float(next(value for (name, _scope), value in self.figures_of(uid).items() if name == key))

    def fill_uid(self) -> str:
        """El uid de la operación vigente de «Balsa 2»."""
        ((uid,),) = self.query("SELECT uid FROM gb_operation WHERE op_type = 'des.fill_only' AND status = 'done' "
                               "AND superseded_by IS NULL")
        return str(uid)

    def set_param(self, key: str, value: object, who: str = decl.USER) -> None:
        """El parámetro de versión ``key`` de V01 con ``value``: se da de alta si no tiene fila y, si la tiene, se cambia."""
        if core_params.ParameterStore(self.project).get(key, version=self.v1.uid) is None:
            self.create_param(key, value, who=who)
        else:
            self.change_as(key, value, who)

    # --- (a) Sin proteger ---------------------------------------------------------------------

    def test_a_without_the_protection_the_fill_only_would_fill_on_the_footprint(self) -> None:
        """CE-015-04 (los dientes de la prueba), error 51: sin ninguna restricción que lo impida, «Balsa 2», el «solo
        relleno» de la 014 sobre la lámina de agua, **rellena** sobre la huella de la plataforma (centenares de m³): lo
        que, protegida, tendrá que quedar en 0."""
        foot = self.footprint_by_hand()
        control = self.fill_calculation("Sin proteger")
        self.addCleanup(control.discard)
        self.assertGreater(self.fill_in(control.outcome.surface, foot), 100.0)

    # --- (b) La plataforma «en corte» que protege --------------------------------------------

    def test_b_a_cut_platform_that_protects_declares_its_restriction_and_the_masks_carry_it(self) -> None:
        """CE-015-04, RF-015-10, RF-015-12 (D-4, D-21), E3: P1 («en corte», que protege con 4 m) declara «sin relleno»
        sobre su huella (``dec__plt_001``, con la huella ensanchada dos celdas: **140 celdas a mano**) y las máscaras de la
        versión la llevan, sin relleno admitido en ella; **«Ver restricciones y límites»** (``listed_constraints`` y
        ``shown_constraints_steps``) la lista con **su entidad**, su resguardo y su estado «activa». Tras la cadena
        («Recalcular lo obsoleto», **una pasada**: P1, que consumió las máscaras anteriores, y la envolvente, que las
        usó) no queda nada obsoleto."""
        self.made(sup.asked(BALSA, protect=True, guard_m=self.GUARD_M))
        chain = self.chain()
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled), (1, True, True))
        self.assertIsNone(chain.failure)
        zone = self.zone()
        self.assertEqual(int(zone.sum()), self.ZONE_CELLS)
        foot = self.footprint_by_hand()
        self.assertTrue(zone[foot].all(), "la zona contiene su huella")
        masks = access.load_masks(self.project, self.v1.uid)
        self.assertEqual(masks.ctypes[self.CODE], "no_fill")
        self.assertFalse(masks.fill_allowed()[zone].any(), "sin relleno admitido en su zona")
        (declared,) = [item for item in self.listed() if item.declared]
        self.assertEqual((declared.entity_code, declared.entity_name, declared.constraint.code, declared.state,
                          declared.buffer_out_m), ("PLT-001", BALSA, self.CODE, "active", self.GUARD_M))
        self.assertEqual(declared.constraint.entity_name, BALSA)
        shown = [item for item in prep.drive(masks_store.shown_constraints_steps(self.project, version=self.v1.uid))
                 if item.declared]
        self.assertEqual([(item.entity_name, item.state) for item in shown], [(BALSA, "active")])
        self.assertEqual(len([item for item in self.listed() if not item.declared]), 4, "las del proyecto, aparte")
        self.assertEqual(self.passes(), [[(str(recompute_mod.UnitStatus.DONE), "des.platform"),
                                          (str(recompute_mod.UnitStatus.DONE), "des.envelope")]])
        self.assertEqual(self.recompute_plan(), [])

    # --- (c) El «solo relleno» de la 014 -------------------------------------------------------

    def test_c_the_fill_only_fills_zero_cubic_metres_in_the_footprint_and_in_the_zone(self) -> None:
        """CE-015-04, RF-015-06, RF-015-10 (error 51), E3 (el «solo relleno» que no entra en la plataforma protegida): con las
        máscaras que llevan la restricción, «Balsa 2» rellena **0 m³ en la huella** y en toda su zona (la superficie es el
        terreno, bit a bit), pero sí en el resto de la lámina (miles de m³: no es un cálculo vacío) y **no se apoya en P1**
        (nada que registrar: no rellena sobre ella)."""
        foot, zone = self.footprint_by_hand(), self.zone()
        calculation = self.fill_calculation()
        surface = calculation.outcome.surface
        self.assertEqual(self.fill_in(surface, foot), 0.0)
        self.assertEqual(self.fill_in(surface, zone), 0.0)
        np.testing.assert_array_equal(surface[zone], qfx.terrain(self.grid)[zone])
        self.assertGreater(self.fill_in(surface, np.ones(self.grid.shape, dtype=bool)), 1_000.0)
        stored = calculation.create()
        self.assertEqual(self.supports_of(stored.handle.uid), [])
        self.assertEqual(self.volumes_of(stored.handle.uid), {})
        self.assertEqual(entities.dependents(self.project, self.v1.uid, "PLT-001"), ())

    # --- (d) La plataforma «en corte y relleno» que la solapa ----------------------------------

    def test_d_a_cut_and_fill_platform_over_it_fills_zero_and_the_summary_gives_the_area_with_the_entity(self) -> None:
        """CE-015-04, RF-015-13, RF-015-06 (error 51): P2 («Sobre la balsa», «en corte y relleno» a 257 m, de la superficie
        de P1, con **la misma huella**) rellena **0 m³** en ella: su superficie es la de P1 en esas celdas (bit a bit); el
        resumen dice el área que no rellena —**192 m² a mano** (48 celdas de 4 m²)— con la restricción y **la entidad que la
        declara** (la plataforma protegida), y la figura de lo que queda por debajo de la rasante; como no rellena, no se
        apoya en P1 (ni entradas ni cifra)."""
        foot = self.footprint_by_hand()
        self.clock.advance(minutes=1)
        calculation = self.calculate_in(dep.on_top(), masks=None)
        held = next(item for item in calculation.summary.notices if item.code == "des.entity_held")
        self.assertEqual((held.values["entity"], held.values["constraint"], held.values["other"], held.values["area"]),
                         (ON_TOP, self.CODE, BALSA, FOOTPRINT_CELLS * CELL_M2))
        self.assertEqual(calculation.outcome.held_area_m2, 192.0)
        self.assertIn(f"«{BALSA}»", calculation.summary.lines("es")[[item.code for item in
                                                                      calculation.summary.notices].index("des.entity_held")])
        stored = calculation.create()
        mine, theirs = self.read(dep.PSF2), self.read(dep.PSF1)
        np.testing.assert_array_equal(mine[foot], theirs[foot])
        self.assertEqual(self.fill_in(mine, foot) - self.fill_in(theirs, foot), 0.0)
        self.assertEqual(self.figure_value(stored.handle.uid, "des.plat_fill_m3"), 0.0)
        self.assertEqual(self.figure_value(stored.handle.uid, "des.plat_below_m2"), 192.0)
        self.assertEqual(self.supports_of(stored.handle.uid), [])
        self.assertEqual(self.volumes_of(stored.handle.uid), {})
        self.assertEqual(self.states(), {"PLT-001": EntityState.CURRENT, "PLT-002": EntityState.CURRENT})

    def states(self) -> dict[str, EntityState]:
        return {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}

    # --- (e) La verificación de la 012 --------------------------------------------------------

    def verify(self, name: str, finals: tuple[str, ...]) -> Any:
        """«Verificar un diseño por recinto…» de la 012 de ``finals`` frente al terreno: su ``VerifyResult``."""
        self.clock.advance(minutes=1)
        stored = sup.finish(cstore.verify_project_steps(
            self.project, version=self.v1.uid, name=name, start=surfaces.SurfaceRef(dataset=START, label="Partida"),
            finals=tuple(surfaces.SurfaceRef(dataset=final, label=final) for final in finals)))
        return stored.result

    def test_e_the_verification_of_the_012_complies_in_the_zone_of_the_protected_platform(self) -> None:
        """CE-015-04, RF-012-21, RF-012-22 (ADR-0028, CE-012-05), error 51: la verificación por recinto de la 012 de P1, P2 y
        «Balsa 2» frente al terreno **da «cumple»** en todos los recintos y cuenta exactamente **0 m³** en el de la
        restricción declarada (``dec__plt_001``, de «sin relleno»: cuenta el relleno); con los dientes: el terreno con
        **una** celda de su huella rellenada 1 m **incumple ese recinto y solo él**, con el área de esa celda (4 m²)."""
        finals = (provenance.dataset_name("psf", BALSA), provenance.dataset_name("psf", ON_TOP), dep.TWIN_SURFACE)
        result = self.verify("Revisión de la balsa", finals)
        self.assertEqual(result.fails, (False, False, False))
        for check in result.finals:
            declared = check.zone(self.CODE)
            self.assertEqual((declared.counts, declared.counted_m3, declared.verdict),
                             (compliance.Counts.FILL, 0.0, compliance.Verdict.COMPLIES))
            for total in check.totals:
                if total.counts in (compliance.Counts.CUT, compliance.Counts.FILL, compliance.Counts.ANY):
                    self.assertEqual((total.counted_m3, total.verdict), (0.0, compliance.Verdict.COMPLIES), total.code)
        raised = qfx.terrain(self.grid).copy()  # el terreno con UNA celda de la huella 1 m más alta: un relleno de 1 m
        row, column = (int(value) for value in np.argwhere(self.footprint_by_hand())[20])
        raised[row, column] += 1.0
        self.clock.advance(minutes=1)
        res_fixtures.write_grids(self.project, [("balsa_tocada", gis.Raster(self.grid, raised, efx.CRS, efx.VERTICAL))],
                                 message="Una celda de la plataforma protegida rellenada 1 m")
        touched = self.verify("Revisión de la celda", ("gis_dtm_balsa_tocada",))
        self.assertEqual(touched.fails, (True,))
        (check,) = touched.finals
        self.assertEqual([total.code for total in check.totals if total.verdict is compliance.Verdict.FAILS], [self.CODE])
        self.assertEqual(check.zone(self.CODE).counted_m3, CELL_M2)

    # --- (f) Cambiar su propia restricción (el ciclo de D-21) ---------------------------------

    def test_f_changing_its_own_restriction_makes_it_obsolete_and_recomputing_it_does_not_change_its_output(self) -> None:
        """CE-015-04, RF-008-26, RF-015-12, D-21 (el ciclo entidad → declarada → máscaras → entidad), lo que da el código: P1
        pasa de 4 a 6 m de resguardo y **queda obsoleta** (causa: ese parámetro; también lo que depende de ella: la
        declaración, las máscaras, la envolvente, «Balsa 2», P2 y la verificación); las máscaras **se siguen entregando**
        (``mask_state`` «al día»: la excepción de ``_only_through_declared``, pendiente de la aprobación de Samuel, que es la
        que deja recalcular); la cadena declara otra vez y recompila las máscaras (la zona crece una corona de una celda);
        y **una sola pasada** de «Recalcular lo obsoleto» rehace P1, la envolvente, «Balsa 2», P2 y la verificación, **sin
        recalcular la declaración ni las máscaras** (pierden su marca: la salida de P1 **no cambia**, mismo hash, RF-008-26)
        y deja todo al día. La salida de P2 tampoco cambia (no puede rellenar su huella); la de «Balsa 2» sí (la zona crece)."""
        key = decl.guard_key("PLT-001")
        first, second, twin = self.current("PLT-001"), self.current("PLT-002"), self.fill_uid()
        hashes = {name: self.hashes_of(uid) for name, uid in (("P1", first), ("P2", second), ("twin", twin))}
        declaration, masks_op = self.current_declaration(), self.compile_op()
        zone = self.zone()
        self.change_as(key, 6.0, decl.EDITOR)
        for name, uid in (("P1", first), ("P2", second), ("twin", twin), ("declaración", declaration),
                          ("máscaras", masks_op)):
            self.assertEqual(self.stale_causes(uid), {("parameter_changed", key)}, name)
        self.assertEqual(entities.stale_reason(self.project, self.v1.uid, "PLT-001"),
                         f"Obsoleto: cambió {GUARD_LABEL} · {BALSA}")
        self.assertIs(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.CURRENT,
                      "se entregan: sin ello nada podría recalcularse")
        chain = self.chain()
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled), (1, True, True))
        (change,) = chain.changes
        self.assertEqual((change.code, change.polygon_gained_m2, change.polygon_lost_m2, change.zone_lost_m2),
                         (self.CODE, 0.0, 0.0, 0.0))
        self.assertGreater(change.zone_gained_m2, 0.0)
        self.assertGreater(int(self.zone().sum()), int(zone.sum()))
        self.assertEqual(self.zone().sum(), (16 + 6) * (3 + 6), "6 m de resguardo: tres celdas por cada lado, a mano")
        declaration, masks_op = self.current_declaration(), self.compile_op()
        plan = [unit[0] for unit in self.plan_names()]
        self.assertEqual(plan[:2], [BALSA, "des.declare_constraints"], "P1 es lo primero que se rehace")
        self.assertEqual(len(plan), 9, "el plan: P1, la declaración, las máscaras, la capa de entidades (T30, que consume los "
                                       "datos de P1), la envolvente, «Balsa 2», P2 y dos verificaciones")
        self.assertIn("des.entity_layer", plan)
        passes = self.passes()
        self.assertEqual(len(passes), 1, "una sola pasada")
        done = str(recompute_mod.UnitStatus.DONE)
        self.assertEqual(sorted(passes[0]), sorted([(done, "des.platform"), (done, "des.envelope"),
                                                    (done, "des.fill_only"), (done, "des.platform"),
                                                    (done, "res.verify_constraints"),
                                                    (done, "res.verify_constraints")]))
        self.assertEqual(self.hashes_of(self.current("PLT-001")), hashes["P1"], "la salida de P1 no cambia")
        self.assertEqual(self.hashes_of(self.current("PLT-002")), hashes["P2"], "la de P2 tampoco")
        self.assertNotEqual(self.hashes_of(self.fill_uid()), hashes["twin"], "la de «Balsa 2», sí: la zona crece")
        self.assertEqual((self.current_declaration(), self.compile_op()), (declaration, masks_op),
                         "la declaración y las máscaras no se recalcularon: perdieron su marca")
        self.assertEqual(self.recompute_plan(), [])
        self.assertIs(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.CURRENT)
        self.assertEqual(self.fill_in(self.read(dep.TWIN_SURFACE), self.zone()), 0.0, "sigue sin rellenar su zona")

    # --- (g) Lo que no se admite: la «en corte y relleno» que protege -----------------------------

    def test_g_a_cut_and_fill_platform_cannot_declare_the_restriction_that_forbids_its_own_movement(self) -> None:
        """CE-015-04, RF-015-12 (D-4, D-21), error 51: una plataforma «en corte y relleno» que protege se rechaza al
        prepararla (``des.platform_protect_cut_fill``, con la capa, la entidad y el campo del modo) y, si su parámetro
        ``protect`` se pusiera después a verdadero, la declaración también la rechaza; en los dos, sin escribir nada y
        con «en corte», que sí puede."""
        before = self.written()
        asked = dep.on_top(protect=True, guard_m=4.0)
        with self.assertRaises(DesignError) as prepared:
            ops_test.finish(steps.platform_run(self.project, asked, version=self.v1.uid, masks=None,
                                               code="PLT-002", supersedes=self.current("PLT-002")))
        self.assertEqual(prepared.exception.code, "des.platform_protect_cut_fill")
        self.assertEqual(prepared.exception.field, "des.platform.plt_002.mode")
        self.assertIn(ON_TOP, prepared.exception.text)
        self.assertEqual(self.written(), before)
        self.set_param(decl.guard_key("PLT-002"), 4.0)
        self.set_param(decl.protect_key("PLT-002"), True)
        before = self.written()
        with self.assertRaises(DesignError) as declared:
            ops_test.finish(entity_store.declare_constraints_steps(self.project, self.v1))
        self.assertEqual(declared.exception.code, "des.platform_protect_cut_fill")
        self.assertEqual(self.written(), before, "la declaración rechazada no escribe nada")
        self.change_as(decl.protect_key("PLT-002"), False, decl.USER)
        self.assertEqual([row.entity_code for row in self.listed() if row.declared], ["PLT-001"])

    # --- (h) Descartarla ----------------------------------------------------------------------

    def test_h_discarding_it_takes_its_restriction_out_of_the_masks(self) -> None:
        """CE-015-04, RF-015-10, RF-015-17, RF-012-06, E3: descartar P1 (``discard_entity_steps``) **quita su restricción de
        las máscaras**: la declaración queda sin ella, las máscaras se compilan otra vez sin su zona (``KeyError``), el relleno
        se admite otra vez donde protegía (las 140 celdas), la lista de «Ver restricciones y límites» ya no la trae y
        el informe da lo perdido; P2, que parte de su superficie, queda en «apoyo retirado»; nada se borra (su tabla
        sigue)."""
        zone = self.zone()
        table = self.record(provenance.dataset_name("epr", BALSA), self.v1).locator
        self.clock.advance(minutes=1)
        result = sup.finish(entity_store.discard_entity_steps(self.project, self.v1.uid, "PLT-001", reason=WHY,
                                                              decided_by=BY))
        chain = result.chain
        self.assertIsNone(chain.failure)
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled), (0, True, True))
        self.assertEqual(self.declared(), ())
        masks = access.load_masks(self.project, self.v1.uid)
        with self.assertRaises(KeyError):
            masks.zone(self.CODE)
        self.assertTrue(masks.fill_allowed()[zone].all(), "el relleno se admite otra vez en toda su zona")
        self.assertEqual(int(masks.fill_allowed()[zone].sum()), int(zone.sum()))
        self.assertEqual([row.entity_code for row in self.listed() if row.declared], [])
        (lost,) = [item for item in chain.changes if item.code == self.CODE]
        self.assertGreater(lost.zone_lost_m2, 0.0)
        self.assertEqual(lost.polygon_lost_m2, FOOTPRINT_CELLS * CELL_M2)
        self.assertEqual(self.query(f'SELECT count(*) FROM "{table}"'), [(1,)], "nada se borra: su tabla sigue")
        self.assertEqual(self.states()["PLT-001"], EntityState.DISCARDED)
        self.assertEqual(self.states()["PLT-002"], EntityState.SUPPORT_REMOVED)


# ---------------------------------------------------------------------------------------------
# CE-015-05: congelar y cambiar
# ---------------------------------------------------------------------------------------------


class FrozenVersionTest(dep.DependentsCase, HandCase):
    """CE-015-05, en el orden de las pruebas, sobre V01 con P1, P2 (de su superficie, que se le apoya), P3, «Balsa 2» y la
    verificación de P2: (a) congelar V01.r1, (b) cambiar la pendiente de P1 en la revisión abierta, (c) recalcular y (d)
    V01.r1 no cambia y se reproduce bit a bit."""

    revision: ClassVar[str]
    items: ClassVar[list[tuple[Any, ...]]]
    frozen: ClassVar[dict[str, dict[str, str]]]
    files: ClassVar[dict[str, str]]
    ops: ClassVar[dict[str, str]]

    def snapshot_files(self) -> dict[str, str]:
        """La huella (SHA-256 **recalculada ahora**) de cada fichero de la instantánea de V01.r1."""
        found = {}
        for (path,) in self.query("SELECT DISTINCT snapshot_path FROM gb_revision_item WHERE revision_uid = ? AND "
                                  "snapshot_path IS NOT NULL ORDER BY snapshot_path", type(self).revision):
            found[str(path)] = sha256(self.root / str(path))
        return found

    def live(self) -> dict[str, str]:
        return {"P1": self.current("PLT-001"), "P2": self.current("PLT-002"), "P3": self.current("PLT-003"),
                "twin": self.fill_uid(), "check": self.check_uid()}

    def test_a_freezing_gives_v01_r1_with_the_files_of_its_snapshot(self) -> None:
        """CE-015-05, RF-009-06, RF-009-11: congelar V01 (con P1, P2, P3, «Balsa 2» y la verificación) da V01.r1 con su
        instantánea (los ficheros de lo producido y de lo de aguas arriba, cada uno con su huella: la que anotó
        la congelación es la que tiene el fichero ahora) y abre la revisión siguiente; lo vigente es lo mismo."""
        cls = type(self)
        self.clock.advance(minutes=1)
        frozen = sup.finish(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega de la prueba"))
        cls.revision = str(frozen.frozen.uid)
        cls.items = self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", cls.revision)
        self.assertTrue(cls.items)
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?", cls.revision), [("frozen",)])
        cls.files = self.snapshot_files()
        self.assertTrue(cls.files)
        recorded = {str(path): str(sha) for path, sha in self.query(
            "SELECT DISTINCT snapshot_path, file_sha256 FROM gb_revision_item WHERE revision_uid = ? AND "
            "snapshot_path IS NOT NULL AND copied = 1", cls.revision)}
        self.assertTrue(recorded)
        for path, sha in recorded.items():
            self.assertEqual(cls.files[path], sha, f"{path}: la huella anotada es la del fichero")
        cls.ops = self.live()
        cls.frozen = {name: self.hashes_of(uid) for name, uid in cls.ops.items()}
        self.assertEqual(self.recompute_plan(), [])
        (opened,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = 'open'", self.v1.uid)[0]
        self.assertNotEqual(opened, cls.revision)

    def test_b_changing_the_slope_of_the_first_platform_in_the_open_revision_makes_it_and_what_rests_on_it_obsolete(self) -> None:
        """CE-015-05, RF-015-16, RF-009-19, E3: congelada V01.r1, cambiar la pendiente de P1 (de 0 a 0,5 %) en la revisión
        abierta deja obsoletas, **cada una con su causa** (el cambio de ese parámetro), a la plataforma, a P2 y a «Balsa 2»,
        que se le apoyan, a P3 (que parte de P2) y a la verificación (que usa la superficie de P2); el motivo dice qué
        entidad cambió y qué; V01.r1 sigue congelada."""
        for name, uid in type(self).ops.items():
            self.assertEqual(self.stale_causes(uid), set(), name)
        self.change(GRADIENT, SLOPE_PCT)
        for name, uid in type(self).ops.items():
            self.assertEqual(self.stale_causes(uid), {("parameter_changed", GRADIENT)}, name)
        wanted = f"Obsoleto: cambió {dep.LABEL} · {BALSA}"
        for code in ("PLT-001", "PLT-002", "PLT-003"):
            self.assertEqual(entities.stale_reason(self.project, self.v1.uid, code), wanted, code)
        self.assertEqual(entities.operation_reason(self.project, self.v1.uid, self.fill_uid()), wanted)
        self.assertEqual([row.state for row in entities.dependents(self.project, self.v1.uid, "PLT-001")],
                         [EntityState.STALE] * 2)
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?", type(self).revision), [("frozen",)])

    def test_c_recomputing_changes_what_was_recomputed_in_the_open_revision(self) -> None:
        """CE-015-05, RF-015-16, RF-008-26, RF-009-19: «Recalcular lo obsoleto» rehace las cinco **en la revisión abierta**
        (cada operación nueva sustituye a la de la congelada, que queda como historia) y lo recalculado **cambia**: la
        superficie de P1 (la rasante sube 0,5 %), la de P2 y la de «Balsa 2» tienen otro hash que el congelado, y lo
        apoyado en P1 es el de la rasante nueva: **369,6 m³ a mano**; no queda nada obsoleto."""
        cls = type(self)
        self.clock.advance(minutes=1)
        outcome = sup.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE] * 5)
        (opened,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = 'open'", self.v1.uid)[0]
        made = [result.operations[0] for result in outcome.results]
        self.assertEqual(self.query("SELECT revision_uid FROM gb_operation WHERE uid IN (?, ?, ?, ?, ?)", *made),
                         [(opened,)] * 5)
        self.assertEqual(sorted(old for (old,) in self.query(
            "SELECT supersedes_uid FROM gb_operation WHERE uid IN (?, ?, ?, ?, ?)", *made)), sorted(cls.ops.values()))
        self.assertEqual(self.recompute_plan(), [])
        now = self.live()
        for name, family in (("P1", dep.PSF1), ("P2", dep.PSF2), ("P3", provenance.dataset_name("psf", DRAG))):
            self.assertNotEqual(self.hashes_of(now[name])[family], cls.frozen[name][family], f"{name}: cambió")
        self.assertNotEqual(self.hashes_of(now["check"]), cls.frozen["check"], "la verificación de P2: otro resultado")
        self.assertEqual(self.hashes_of(now["twin"])[dep.TWIN_SURFACE], cls.frozen["twin"][dep.TWIN_SURFACE],
                         "«Balsa 2» se recalcula y su superficie sale igual: el terreno queda por encima de la rasante de "
                         "P1, que no la toca (solo se le apoya)")
        listed = {row.name: row.volume_m3 for row in entities.dependents(self.project, self.v1.uid, "PLT-001")}
        self.assertTrue(close(listed[ON_TOP], FILL_AFTER_BY_HAND_M3), listed)
        by_files = self.supported(self.read(dep.PSF2), self.read(dep.PSF1), self.read(dep.PSF1), self.footprint_by_hand())
        self.assertTrue(close(by_files, FILL_AFTER_BY_HAND_M3), by_files)

    def test_d_the_frozen_revision_does_not_change_and_is_reproduced_bit_by_bit(self) -> None:
        """CE-015-05, RF-009-11, RF-009-19: V01.r1 **no cambió**: sigue congelada, con los mismos elementos y los mismos
        ficheros de su instantánea (la huella de cada uno, recalculada ahora, es la de antes), y las operaciones congeladas
        conservan sus hash; **se reproduce bit a bit** —sin escribir nada en el proyecto— con las salidas y las cifras
        iguales a las congeladas, aunque lo vivo ya sea otro."""
        cls = type(self)
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?", cls.revision), [("frozen",)])
        self.assertEqual(self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", cls.revision),
                         cls.items)
        self.assertEqual(self.snapshot_files(), cls.files, "los ficheros congelados no cambian")
        self.assertEqual({name: self.hashes_of(uid) for name, uid in cls.ops.items()}, cls.frozen)
        before = self.written()
        report = sup.finish(reproduce_mod.reproduce_steps(self.project, cls.revision))
        self.assertEqual(self.written(), before, "reproducir no escribe nada")
        self.assertTrue(report.outputs)
        self.assertTrue(all(check.same for check in report.outputs), [c for c in report.outputs if not c.same])
        self.assertTrue(all(check.same for check in report.figures))
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)
        mine = {check.operation_uid: check for check in report.outputs if check.role == "entity_surface"}
        for name in ("P1", "P2"):
            self.assertEqual(mine[cls.ops[name]].reproduced_sha256, cls.frozen[name][dep.PSF1 if name == "P1" else dep.PSF2],
                             f"{name}: la superficie reproducida es la congelada")
            self.assertNotEqual(mine[cls.ops[name]].reproduced_sha256, self.hashes_of(self.live()[name])[
                dep.PSF1 if name == "P1" else dep.PSF2], "y no la viva")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
