# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que ``des`` pone al día tras cambiar un parámetro de **cualquier tipo de entidad** y al terminar «Recalcular lo obsoleto»
(spec 016, T47; hallazgos D-1 y D-2 de la verificación única; RF-015-10, RF-015-12, RF-015-27, RF-015-29, RF-016-24): los
ganchos de ``bl.ops.core_provenance`` que registra ``bl.ops.des``, sin proyecto y con lo registrado cambiado por un doble.

- **D-1** (``_layers_after_recompute``): la capa de entidades se pone al día al terminar «Recalcular lo obsoleto» si la
  versión tiene **alguna entidad viva de cualquier tipo** (la plataforma, la detección de acopios, la retirada, el contrafuerte o
  el cuerpo apoyado: ``design.provenance.ENTITY_OP_NAMES``), no solo plataformas: en una versión **sin plataformas** (un
  contrafuerte solo) la capa se quedaba diciendo «obsoleta» sobre una entidad al día hasta la siguiente orden de entidades.
- **D-2** («Cambiar parámetro…»): la comprobación de las reglas entre entidades de crear
  (``design.entity_store.check_parameter_change``) y lo que sigue al cambio (declarar, recompilar las máscaras y poner al día la
  capa, ``des_entity_refresh``) están registrados para los **siete** principios de clave (``des.platform.``, ``des.stockpile.``,
  ``des.removal.``, ``des.buttress.`` y ``des.body.``), no solo para el de la plataforma; desregistrar los quita todos.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import sqlite3
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType
from typing import Any
from unittest import mock

from tests.support import blender_ext

PREFIXES = ("des.platform.", "des.stockpile.", "des.removal.", "des.buttress.", "des.body.", "des.road.", "des.access.", "des.pit.")
ENTITY_TYPES = ("des.platform", "des.stockpile_detect", "des.stockpile_removal", "des.buttress", "des.body", "des.road",
                "des.road_access", "des.pit")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{blender_ext.module_name()}.{name}")


class FakeProject:
    """Un proyecto de mentira: solo ``read()``, con las operaciones de la prueba en una base en memoria."""

    def __init__(self, *operations: tuple[str, str, str | None]) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE gb_operation (uid TEXT, op_type TEXT, status TEXT, superseded_by TEXT)")
        for number, (op_type, status, superseded) in enumerate(operations):
            self.conn.execute("INSERT INTO gb_operation VALUES (?, ?, ?, ?)", (f"op-{number}", op_type, status, superseded))

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        yield self.conn


class SupportedAftersTest(unittest.TestCase):
    """Con la extensión habilitada."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.des_ops = _module("bl.ops.des")
        cls.cp = _module("bl.ops.core_provenance")
        cls.entity_store = _module("design.entity_store")
        cls.entities = _module("design.entities")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    # --- D-1: la capa tras «Recalcular lo obsoleto» -----------------------------------------------

    def after_recompute(self, *operations: tuple[str, str, str | None]) -> tuple[Any, mock.Mock]:
        """Lo que da ``_layers_after_recompute`` en un proyecto con esas operaciones y las veces que pidió los pasos."""
        sentinel = iter(())
        with mock.patch.object(self.entity_store, "layers_sync_steps", return_value=sentinel) as steps:
            found = self.des_ops._layers_after_recompute(FakeProject(*operations))  # noqa: SLF001
        if steps.called:
            self.assertIs(found, sentinel)
        return found, steps

    def test_a_any_live_entity_of_any_type_puts_the_layer_up_to_date_after_recomputing(self) -> None:
        """RF-015-27, RF-016-24 (D-1): con **una sola** operación viva de cada tipo (la plataforma, la detección de acopios, la
        retirada, el contrafuerte, el cuerpo, la pista o la accesibilidad), el gancho pide los pasos de poner al día la capa (hasta la T47, solo con una
        plataforma: un contrafuerte solo dejaba la capa «obsoleta» sobre una entidad al día)."""
        self.assertEqual(set(self.des_ops.provenance.ENTITY_OP_NAMES), set(ENTITY_TYPES))
        for op_type in ENTITY_TYPES:
            with self.subTest(op_type=op_type):
                _found, steps = self.after_recompute((op_type, "done", None))
                steps.assert_called_once()

    def test_b_without_a_live_entity_it_is_a_query_and_nothing_is_loaded(self) -> None:
        """RF-015-27 (D-1): sin ninguna entidad viva (ninguna operación, las sustituidas, las que no terminaron y las que no son
        de una entidad, entre ellas la declaración y la capa mismas), devuelve ``None`` y no pide los pasos."""
        cases = {"sin operaciones": (), "sustituida": (("des.buttress", "done", "op-9"),),
                 "fallida": (("des.body", "failed", None),), "en curso": (("des.stockpile_removal", "running", None),),
                 "de otro tipo": (("des.envelope", "done", None), ("des.declare_constraints", "done", None),
                                  ("des.entity_layer", "done", None))}
        for label, operations in cases.items():
            with self.subTest(label):
                found, steps = self.after_recompute(*operations)
                self.assertIsNone(found)
                steps.assert_not_called()

    # --- D-2: «Cambiar parámetro…» de cualquier tipo --------------------------------------------

    def test_c_the_check_and_what_follows_are_registered_for_the_seven_prefixes_and_unregistered_with_them(self) -> None:
        """RF-015-08, RF-015-10, RF-015-12 (D-2): la comprobación y lo que sigue a «Cambiar parámetro…» están registrados para
        los siete principios de clave de los tipos del programa (los de ``design.entities``), con las mismas funciones y el de la
        plataforma, el de siempre; desregistrar ``des`` los quita **todos** y registrarlo otra vez los pone otra vez (idempotente)."""
        registered = tuple(f"{spec.key_prefix}." for spec in self.entities.registered_types())
        self.assertEqual(registered, PREFIXES)
        self.assertEqual(set(self.des_ops.PARAMETER_PREFIXES), set(PREFIXES))
        self.assertEqual(self.des_ops.PARAMETER_PREFIX, "des.platform.")
        checks, afters = self.cp._PARAMETER_CHECKS, self.cp._PARAMETER_AFTERS  # noqa: SLF001
        self.addCleanup(self.des_ops.register)
        for prefix in PREFIXES:
            self.assertIs(checks.get(prefix), self.des_ops._check_entity_parameter, prefix)  # noqa: SLF001
            self.assertIs(afters.get(prefix), self.des_ops._after_entity_parameter, prefix)  # noqa: SLF001
        for _ in range(2):
            self.des_ops.unregister()
            for prefix in PREFIXES:
                self.assertNotIn(prefix, checks, prefix)
                self.assertNotIn(prefix, afters, prefix)
        for _ in range(2):
            self.des_ops.register()
            for prefix in PREFIXES:
                self.assertIs(checks.get(prefix), self.des_ops._check_entity_parameter, prefix)  # noqa: SLF001
                self.assertIs(afters.get(prefix), self.des_ops._after_entity_parameter, prefix)  # noqa: SLF001

    def test_d_changing_a_parameter_of_any_type_is_checked_and_refreshes_what_follows(self) -> None:
        """RF-015-10, RF-015-12, RF-015-29 (D-2): una clave de **cada** tipo (y solo de las entidades) llega a la comprobación de
        ``design.entity_store`` con la versión, antes de escribir, y, escrita, lanza lo que sigue (``des_entity_refresh`` por
        pasos) si la versión es la activa; una clave de otro módulo, un cambio del proyecto (sin versión) y el de una versión que no es
        la activa no lanzan nada."""
        with mock.patch.object(self.entity_store, "check_parameter_change") as check:
            for prefix in PREFIXES:
                with self.subTest(prefix=prefix, what="comprobar"):
                    check.reset_mock()
                    self.cp.check_parameter_change("proyecto", f"{prefix}x_001.guard_m", 12.0, "uid-v01")
                    check.assert_called_once_with("proyecto", f"{prefix}x_001.guard_m", 12.0, version="uid-v01")
            check.reset_mock()
            self.cp.check_parameter_change("proyecto", "des.quarry.crown_ring_cells", 2, "uid-v01")
            self.cp.check_parameter_change("proyecto", "des.buttress.btr_001.guard_m", 12.0, None)
            check.assert_not_called()
        with mock.patch.object(self.des_ops.scene_versions, "active_version", return_value="uid-v01"), \
                mock.patch.object(self.des_ops, "bpy") as fake:
            refresh = fake.ops.geoblender.des_entity_refresh
            for prefix in PREFIXES:
                with self.subTest(prefix=prefix, what="lo que sigue"):
                    refresh.reset_mock()
                    self.cp.parameter_changed("proyecto", f"{prefix}x_001.guard_m", "uid-v01")
                    refresh.assert_called_once_with("EXEC_DEFAULT", in_steps=True)
            refresh.reset_mock()
            self.cp.parameter_changed("proyecto", "des.quarry.crown_ring_cells", "uid-v01")
            self.cp.parameter_changed("proyecto", "des.buttress.btr_001.guard_m", None)
            self.cp.parameter_changed("proyecto", "des.buttress.btr_001.guard_m", "uid-v02")
            refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
