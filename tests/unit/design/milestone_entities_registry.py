# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_entities_registry» (spec 016, T02; plan 016 §8, primer riesgo; P-13): lo que pesa más
de 1 s. El «verde» deja en ``test_entities_registry`` el registro por tipo; esto lo ejecuta el paso «hito» de
``tools/check.py --completo`` (la publicación lo pide siempre).

La generalización del registro de la 015 a más de un tipo **no cambia un resultado** (RF-015-01, RF-015-02,
RF-015-04, RF-009-11): con los dos tipos de prueba registrados (``types_registered``), las plataformas de la 015
se crean, se recalculan, se congelan y se reproducen igual, y reproducir la revisión congelada da el **mismo
hash** que registró cada operación y las mismas cifras, sin escribir nada en el proyecto. La comparación con los
hash de **antes** de la T02 (los valores concretos) es de la *Verificación* de la tarea.

**Spec 017, T03** (la pista y la accesibilidad pasan a ser dos tipos más del programa, junto a los cuatro de la 016, sin cambiar un
resultado de la 015 ni de la 016): se amplía con la detección de acopios de la 016 (la de ``milestone_stockpile_recompute``, con sus
candidatos y sus decisiones, recalculada y congelada), que con los tipos de prueba registrados **y los dos de la 017** se reproduce
igual: los mismos hash y las mismas cifras, y lo vivo que cambia al recalcular no cambia lo congelado. Los valores concretos antes y
después de la T03 (los de las tres plataformas y la detección) son de su *Verificación*.
"""

from __future__ import annotations

from typing import Any, ClassVar

from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import milestone_stockpile_recompute as stockpile_recompute
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design.test_entities_registry import types_registered
from tests.unit.design.test_platform_operation import (
    WORKSHOP,
    RecomputeCase,
    design_params,
    entities_module,
    finish,
    freeze,
    recompute_mod,
    reproduce_mod,
)


class FrozenPlatformsWithMoreTypesRegisteredTest(RecomputeCase):
    """RF-016-02, RF-015-02, RF-009-11: P1 (del terreno) y P2 (de la superficie de P1) creadas en V01, la cota
    inicial de P1 cambiada en la versión (249 m) y las dos recalculadas, congeladas en V01.r1, **con los tipos de
    prueba registrados**: el registro de las entidades las lee como de la 015 y su revisión se reproduce igual."""

    revision: ClassVar[str]
    uids: ClassVar[tuple[str, ...]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(types_registered())
        cls.made(prep.request())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001"))
        cls.change(design_params.entity_key("PLT-001", "start_level_m"), 249.0)
        cls.clock.advance(minutes=1)
        again = finish(recompute_mod.recompute_steps(cls.project))
        assert [result.status for result in again.results] == [recompute_mod.UnitStatus.DONE] * 2
        registry = entities_module.registry(cls.project, cls.v1.uid)
        cls.uids = tuple(str(registry.get(code).operation_uid) for code in ("PLT-001", "PLT-002"))
        cls.clock.advance(minutes=1)
        frozen = finish(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba de la T02"))
        cls.revision = str(frozen.frozen.uid)
        cls.clock.advance(minutes=1)

    def reproduce(self) -> Any:
        """La reproducción de V01.r1, comprobando que **no escribió** nada en el proyecto."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before,
                         "reproducir no escribe en el proyecto")
        return report

    def test_the_registry_reads_the_platforms_as_the_015_did(self) -> None:
        """RF-016-02, RF-015-01, RF-015-25: con los tipos de prueba registrados, el registro de la versión da
        las dos plataformas como tipo ``platform``, al día, con las operaciones vigentes y sin ninguna entidad de
        los tipos de prueba, y la última de la cadena es P2 (la de su superficie, la que congelar verifica)."""
        found = entities_module.registry(self.project, self.v1.uid)
        self.assertEqual([item.code for item in found.records], ["PLT-001", "PLT-002"])
        self.assertEqual({item.kind.value for item in found.records}, {"platform"})
        self.assertEqual([entry.operation_uid for entry in found], list(self.uids))
        self.assertEqual([item.code for item in entities_module.chain_tails(found.records)], ["PLT-002"])

    def test_reproducing_the_frozen_revision_gives_the_same_hash_without_writing(self) -> None:
        """RF-016-02, RF-015-02, RF-009-11 (la 015, sin cambios): reproducir V01.r1 —sin proyecto, desde la capa,
        la partida, las máscaras y los parámetros congelados— da, de cada plataforma, la superficie, la tabla y
        el informe con el **mismo hash** que registró su operación y las mismas cifras, aunque haya tipos de
        entidad registrados que la 015 no tenía."""
        report = self.reproduce()
        mine = [check for check in report.outputs if check.operation_uid in self.uids]
        self.assertEqual(sorted((check.operation_uid, check.role) for check in mine),
                         sorted((uid, role) for uid in self.uids
                                for role in ("entity", "entity_report", "entity_surface")))
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        for uid in self.uids:
            found = [check for check in report.figures if check.operation_uid == uid]
            self.assertGreaterEqual(len(found), 9)
            self.assertTrue(all(check.same for check in found), [check for check in found if not check.same])
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)


class FrozenStockpileDetectionWithMoreTypesRegisteredTest(stockpile_recompute.ReproduceTest):
    """RF-017-01, RF-016-10, RF-016-02, RF-015-02, RF-009-11 (spec 017, T03): la detección de acopios de la 016 con sus candidatos y sus
    decisiones, recalculada con otro umbral y congelada en ``V01.r1``, **con los tipos de prueba registrados** (además de la pista y la
    accesibilidad, que ya son del programa): el registro de las entidades la lee como de la 016, su revisión se reproduce con el **mismo
    hash** que registró cada dato y las mismas cifras sin escribir, y lo vivo que cambia al recalcular no cambia lo congelado. Hereda las
    dos pruebas de ``milestone_stockpile_recompute.ReproduceTest``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.enterClassContext(types_registered())
        super().setUpClass()

    def test_the_registry_reads_the_detection_as_the_016_did(self) -> None:
        """RF-017-01, RF-016-02, RF-015-25: con los tipos de prueba registrados, el registro de la versión da la detección como tipo
        ``stockpile``, al día, con la operación vigente, **fuera de toda cadena** (sin partida) y sin ninguna pista ni accesibilidad."""
        found = entities_module.registry(self.project, self.v1.uid)
        self.assertEqual([item.code for item in found.records], ["STK-001"])
        self.assertEqual({item.kind.value for item in found.records}, {"stockpile"})
        (entry,) = list(found)  # la operación vigente: la de ``setUpClass`` o, si la otra prueba ya recalculó, la que la sustituyó
        self.assertEqual(self.query("SELECT op_type FROM gb_operation WHERE uid = ?", str(entry.operation_uid)),
                         [("des.stockpile_detect",)])
        self.assertEqual(entities_module.chain_tails(found.records), ())
