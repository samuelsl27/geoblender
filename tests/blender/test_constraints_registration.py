# SPDX-License-Identifier: GPL-3.0-or-later
"""El registro de los límites y las restricciones en Blender (spec 012, T21; HU-012-4; RF-012-16,
RF-012-28; plan 012 §5.3.3, D-31, D-38; ADR-0025 §2, ADR-0027; principio 8).

- ADR-0025 §2, ADR-0027 (RF-012-16): habilitar registra en ``core`` lo que declara la 012: sus
  cuatro familias de parámetros de una restricción (resguardo hacia fuera y hacia dentro, peso y
  «activa»), la distancia de búsqueda de intocables y el espesor mínimo de la verificación, sus
  seis tipos de operación (cuatro de ``core``, ``gis.compile_constraints`` y
  ``res.verify_constraints``), sus dieciséis cifras (la última, la del corte de acopios, de la 016, T30) y la
  comprobación de congelar de ``res``;
  ``bl/ops/core_constraints.py`` lo quita y lo vuelve a poner con los mismos objetos y deja lo
  que otro registró antes con las mismas claves.
- El contrato de registro de la 008 (RF-008-26, RF-009-05, RF-009-11; RF-012-16): cada tipo con
  su versión 1.0, su ámbito (la compilación y la verificación, de la versión: la versión no
  editable desactiva sus órdenes; las otras cuatro, del proyecto), sus órdenes en el catálogo y,
  los dos que se repiten, su recálculo, su reproducción y la tolerancia de sus cifras; sus
  textos, en español. La entrada «012» del catálogo (D-38) y las dos órdenes de D-31 (provisionales
  hasta T23 y T28).
- D-19 (RF-012-16, RF-008-26): «Recalcular lo obsoleto» de unas máscaras obsoletas por un
  parámetro empieza la compilación nueva y deja sus pasos en la cola de ``gis`` (``masks_tick``, a
  mano: en ``blender -b`` no corren los temporizadores) mientras ``recompute_steps`` espera; la
  cola dice su avance en la barra de estado, deja «fallida» la operación de unos pasos que fallan,
  lleva sus avisos al registro de Blender y, al desregistrar, cierra lo que espera (como Esc:
  nada a medias). La verificación hace lo mismo con la cola de ``res``.
- Principio 8: deshabilitar no deja clases, propiedades, temporizadores, familias, definiciones,
  operaciones, cifras ni comprobaciones de congelar de la 012, y la huella entera de Blender
  vuelve a la del principio de la sesión.
- RNF-001-03 (spec 001; T38): habilitar la extensión de cero no importa las máscaras, su búsqueda,
  el motor de la verificación ni la cadena de versiones y procedencia que arrastran
  (``LazyRegistrationTest``; las importa la primera llamada que las usa) y deja el recolector de
  basura como estaba. Lo mide ``tests/rendimiento/blender/perf_registration.py`` y lo fija sin
  Blender ``tests/unit/architecture/test_lazy_registration.py``.

Un proyecto mínimo (24 × 24 celdas de 1 m) y uno solo por prueba que lo necesita (RNF-001-01). Se
ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import gc
import importlib
import json
import sqlite3
import unittest
import uuid
from collections.abc import Callable, Iterator
from datetime import date
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.trees import temp_folder

ENTRY = "012"
ENTRY_TITLE = ("Legal limits and constraints", "Límites legales y restricciones")
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 24.0
STEP_M = 1.0
REASON = "Prueba del registro de las restricciones"
INWARD_M = 2.0
CHANGED_INWARD_M = 4.0
COUNTS = {"parámetros": 2, "familias": 4, "operaciones": 6, "grupos": 0, "cifras": 16,
          "comprobaciones": 1}
CORE_TYPES = ("core.declare_sectors", "core.find_untouchables", "core.edit_constraints",
              "core.edit_intentions")
VERSION_TYPES = ("gis.compile_constraints", "res.verify_constraints")
WM_PROPERTY = "geoblender_constraints"
GROUP = "GEOBLENDER_PG_core_constraints"
STATUS_MSGID = "Recomputing «{name}»… {percent} %"
STATUS = "Recalculando «{name}»… {percent} %"
DROPPED = "cancelada durante la operación: se desactivó Geoblender antes de empezar"
COMMANDS = {
    "core.declare_sectors": "geoblender.core_find_untouchables",
    "core.find_untouchables": "geoblender.core_find_untouchables",
    "core.edit_constraints": "geoblender.core_edit_constraints",
    "core.edit_intentions": "geoblender.core_edit_client_marks",
    "gis.compile_constraints": "geoblender.gis_compile_constraints",
    "res.verify_constraints": "geoblender.res_verify_constraints",
}
DELIVERED: frozenset[str] = frozenset({"geoblender.core_edit_limits",
                                       "geoblender.core_edit_constraints",
                                       "geoblender.gis_compile_constraints",
                                       "geoblender.core_find_untouchables",
                                       "geoblender.core_edit_client_marks",
                                       "geoblender.res_verify_constraints"})
SEARCH_TYPES = ("core.declare_sectors", "core.find_untouchables")
"""Los dos tipos que lanza la misma orden del catálogo: la ventana de la búsqueda
(``core.find_untouchables``); declarar los sectores tiene su orden interna."""
"""Las órdenes de la 012 que ya tienen su clase real (de la entrada «012») y lanzan alguna de
las operaciones de :data:`COMMANDS`: cada una pasa del R-32 a la 012 con la suya (T22 a T28; la
de los límites, ``core_edit_limits``, no es la orden de su tipo, que es la de las restricciones:
su prueba es ``test_constraints_limits``; las de las restricciones y la compilación, la T23:
``test_constraints_ops``)."""


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def check_key(module: str, check: Callable[..., Any]) -> str:
    """La clave de una comprobación de congelar en la huella de los registros: su módulo y su
    función (con su módulo, que distingue la de «otro» con el mismo nombre)."""
    return f"{module}:{check.__module__}.{check.__qualname__}"


class _Modules:
    """Los módulos de la extensión que mira la prueba (los de la habilitación en curso)."""

    def __init__(self) -> None:
        self.core_ops = _module("bl.ops.core_constraints")
        self.gis_ops = _module("bl.ops.gis")
        self.res_ops = _module("bl.ops.res")
        self.queue = _module("bl.ops.incorporation")
        self.params = _module("core.params")
        self.contract = _module("core.provenance.contract")
        self.freeze = _module("core.versions.freeze")
        self.cparams = _module("core.constraints.params")
        self.cprov = _module("core.constraints.provenance")
        self.cmodel = _module("core.constraints.model")
        self.cstore = _module("core.constraints.store")
        self.cmessages = _module("core.constraints.messages")
        self.masks_provenance = _module("gis.masks.provenance")
        self.masks_store = _module("gis.masks.store")
        self.verify = _module("reserves.compliance_store")
        self.commands = _module("bl.ui.commands")
        self.i18n = _module("core.i18n")

    def keys(self) -> dict[str, set[str]]:
        """Las claves de la 012 en cada registro de ``core``."""
        return {
            "parámetros": {defn.key for defn in (*self.cparams.DEFINITIONS,
                                                 *self.verify.DEFINITIONS)},
            "familias": {family.pattern for family in self.cparams.FAMILIES},
            "operaciones": {defn.op_type for defn in self.cprov.OPERATIONS}
            | set(VERSION_TYPES),
            "grupos": set(),
            "cifras": {figure.key for figure in (*self.masks_provenance.FIGURES,
                                                 *self.verify.FIGURES)},
            "comprobaciones": {check_key(self.verify.MODULE, self.core_ops.freeze_findings)},
        }

    def registries(self) -> dict[str, dict[str, Any]]:
        """Los registros de ``core`` que amplía la 012, por nombre (copias)."""
        return {
            "parámetros": dict(self.params.DEFINITIONS),
            "familias": dict(self.params.FAMILIES),
            "operaciones": dict(self.contract.OPERATIONS),
            "grupos": dict(self.contract.GROUPS),
            "cifras": dict(self.contract.FIGURES),
            "comprobaciones": {check_key(module, check): check
                               for module, check in self.freeze.freeze_checks()},
        }

    def ours(self) -> dict[str, list[str]]:
        keys = self.keys()
        return {name: sorted(key for key in found if key in keys[name])
                for name, found in self.registries().items()}


class ConstraintsRegisteredTest(unittest.TestCase):
    """Con la extensión habilitada (sin importarla otra vez: ``blender_ext.release``)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.m = _Modules()
        cls.cat = cls.m.commands.catalog()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.m.i18n.set_language, self.m.i18n.language())
        self.m.i18n.set_language("es")

    # --- Ayudas -------------------------------------------------------------------------------

    def assertSameRegistries(self, got: dict[str, dict[str, Any]],  # noqa: N802 - unittest
                             expected: dict[str, dict[str, Any]]) -> None:
        """Las mismas claves en cada registro y, en cada una, el mismo objeto."""
        self.assertEqual({name: sorted(found) for name, found in got.items()},
                         {name: sorted(found) for name, found in expected.items()})
        for name, found in got.items():
            for key, item in found.items():
                self.assertIs(item, expected[name][key], f"{name}: {key}")

    def register_others(self) -> list[tuple[str, str, Any]]:
        """Lo que «otro» registra con claves de la 012 antes de registrarla: objetos distintos
        de los suyos. Devuelve (registro, clave, objeto)."""
        m = self.m
        definition = dataclasses.replace(m.cparams.SEARCH_DISTANCE)
        family = dataclasses.replace(m.cparams.FAMILIES[0])
        operation = dataclasses.replace(m.cprov.OPERATIONS[0])
        m.params.register_definitions([definition])
        m.params.register_families([family])
        m.contract.register_operation(operation)

        def other_check(conn: Any, version_uid: str) -> tuple[()]:
            return ()

        m.freeze.register_freeze_check(m.verify.MODULE, other_check)
        return [("parámetros", definition.key, definition),
                ("familias", family.pattern, family),
                ("operaciones", operation.op_type, operation),
                ("comprobaciones", check_key(m.verify.MODULE, other_check), other_check)]

    def forget_others(self, others: list[tuple[str, str, Any]]) -> Callable[[], None]:
        """Con la 012 quitada, quita lo de «otro» (y deja lo demás de ``core`` como estaba) y la
        vuelve a registrar."""
        m = self.m
        core_defs = _module("core.params.core_defs")

        def forget() -> None:
            m.core_ops.unregister()
            if any(name == "parámetros" for name, _key, _item in others):
                m.params.unregister_definitions("core")  # solo se quitan por módulo:
                m.params.register_definitions(core_defs.DEFINITIONS)  # lo de core, otra vez
            m.params.unregister_families("core")
            m.contract.unregister_operation(m.cprov.OPERATIONS[0].op_type)
            m.freeze.unregister_freeze_checks(m.verify.MODULE)
            m.core_ops.register()

        return forget

    def project(self) -> tuple[Any, Any]:
        """Un proyecto nuevo en escritura (fuera de la sesión) de :data:`SIZE_M` m de lado con
        celdas de :data:`STEP_M` m y V01; el proyecto y V01."""
        folder = temp_folder(self, "gb-r21-")
        (folder / "proyectos").mkdir()
        session = _module("bl.scene.project_session")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + SIZE_M, SOUTH + SIZE_M), grid_step_m=STEP_M))
        project = core_project.create_project(folder / "proyectos", settings, session.session(),
                                              session.userdata()).project
        self.addCleanup(project.close)
        with project.write_transaction() as conn:
            version, _revision = _module("core.versions.store").create_version(
                conn, project, feature="mascaras", title="Máscaras", reason=REASON)
        project.refresh_header()
        return project, version

    def declare_limit(self, project: Any) -> str:
        """El límite legal del proyecto (un cuadrado de 20 m dentro de la ventana) con
        :data:`INWARD_M` m hacia dentro, creado como lo hará la orden (``core.edit_constraints``
        con sus parámetros); el código de la restricción."""
        m = self.m
        x0, y0, x1, y1 = WEST + 2.0, SOUTH + 2.0, WEST + 22.0, SOUTH + 22.0
        ring = np.asarray([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], dtype=np.float64)
        kind = m.cmodel.GeometryKind.POLYGON
        row = m.cmodel.Constraint(
            uid=uuid.uuid4().hex, code="", name="Concesión",
            ctype=m.cmodel.ConstraintType.LEGAL_LIMIT, kind=kind, parts=((ring,),), priority=0,
            reason=REASON, decided_by="la prueba", decided_on=date(2026, 10, 31),
            decision_uid=None, intention_uid=None, source_input=None, source_fid=None,
            layer=m.cstore.layer_of(kind), fid=0)
        declaration = m.cprov.ParamDeclaration(
            values={m.cmodel.ConstraintParam.BUFFER_IN: INWARD_M,
                    m.cmodel.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by="la prueba", reason=REASON)
        edited = m.cprov.edit_constraints(project, [row], params=declaration,
                                          srs_id=project.record.crs_epsg)
        return str(edited.constraints[0].code)

    def compile_masks(self, project: Any, version: Any) -> str:
        """La compilación de V01 como la lanzará la orden (``begin_compile`` y sus pasos hasta
        el final); el uid de su operación."""
        store = self.m.masks_store
        handle = store.begin_compile(project, version=version.uid)
        for _step in store.compile_run(project, handle):
            pass
        return handle.uid

    def change_inward(self, project: Any, code: str) -> None:
        """El resguardo hacia dentro del proyecto a :data:`CHANGED_INWARD_M` (HIPÓTESIS), con
        su motivo: las máscaras que lo leyeron quedan obsoletas."""
        store = self.m.params.ParameterStore(project)
        with project.write_transaction() as conn:
            store.change(conn, self.m.cparams.buffer_in_key(code), value=CHANGED_INWARD_M,
                         kind="HIPÓTESIS", source="Criterio de la prueba", source_kind="person",
                         decided_by="la prueba", reason=REASON)

    @staticmethod
    def rows(project: Any, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with project.read() as conn:
            return conn.execute(sql, args).fetchall()

    # --- Pruebas ------------------------------------------------------------------------------

    def test_register_and_unregister_leave_core_as_it_was(self) -> None:
        """ADR-0025 §2, ADR-0027, principio 8 (RF-012-16): habilitada, la 012 tiene en ``core``
        sus 2 definiciones de parámetros, sus 4 familias, sus 6 tipos de operación, sus 15
        cifras y la comprobación de congelar de ``res`` (ningún grupo acoplado).
        ``bl/ops/core_constraints.py`` lo suyo (familias, la distancia de búsqueda, las cuatro
        operaciones de ``core`` y la comprobación) lo quita todo (dos veces: nada más cambia) y lo
        vuelve a poner (dos veces) con los mismos objetos. Con lo que «otro» registró antes con
        las mismas claves, registrar pone solo lo que falta (lo de otro se queda) y desregistrar
        deja los registros exactamente como estaban."""
        m = self.m
        enabled = m.registries()
        ours = m.ours()
        self.assertEqual({name: len(keys) for name, keys in ours.items()}, COUNTS)
        mine = {  # lo que registra core_constraints (lo demás, gis y res)
            "parámetros": {m.cparams.SEARCH_DISTANCE.key},
            "familias": set(m.keys()["familias"]),
            "operaciones": set(CORE_TYPES),
            "comprobaciones": set(m.keys()["comprobaciones"]),
        }
        bare = {name: {key: item for key, item in found.items() if key not in mine.get(name, ())}
                for name, found in enabled.items()}
        others: list[tuple[str, str, Any]] = []
        self.addCleanup(lambda: self.forget_others(others)())
        for _ in range(2):
            m.core_ops.unregister()
            self.assertSameRegistries(m.registries(), bare)
        for _ in range(2):
            m.core_ops.register()
            self.assertSameRegistries(m.registries(), enabled)

        m.core_ops.unregister()
        others.extend(self.register_others())
        before = m.registries()
        m.core_ops.register()
        after = m.registries()
        self.assertEqual(m.ours(), ours)
        for name, key, item in others:
            with self.subTest(de_otro=f"{name}: {key}"):
                self.assertIs(after[name][key], item)
        self.assertIn(m.core_ops.freeze_findings, [check for _m, check
                                                   in m.freeze.freeze_checks()])
        m.core_ops.unregister()
        self.assertSameRegistries(m.registries(), before)

    def test_operation_types_follow_the_contract_of_008(self) -> None:
        """RF-012-16, RF-008-26, RF-009-05, RF-009-11 (contrato de ADR-0025; plan §5.2.3, D-31,
        D-38): los seis tipos de la 012, versión 1.0, sin grupo; la compilación y la
        verificación, de la versión (la orden pide una versión editable) y repetibles, con el
        recálculo de ``bl/ops/gis.py`` y de ``bl/ops/res.py``, su reproducción y la tolerancia de
        sus cifras (10⁻⁹); las otras cuatro, del proyecto y sin repetirse; cada orden que los
        lanza está en el catálogo; sus cifras, las de ``gis.masks.provenance`` y
        ``reserves.compliance_store``; los textos de todo ello, en español. La entrada «012» está
        en el catálogo y las órdenes que ya tienen su clase real (ninguna aún) están en ella; las
        demás siguen siendo las provisionales de R-32."""
        m = self.m
        session = _module("bl.ops.core_provenance")
        found = {op_type: defn for op_type, defn in m.contract.OPERATIONS.items()
                 if op_type in m.keys()["operaciones"]}
        self.assertEqual(sorted(found), sorted((*CORE_TYPES, *VERSION_TYPES)))
        self.assertIs(found["gis.compile_constraints"], m.gis_ops.MASKS_OPERATION_DEF)
        self.assertIs(found["res.verify_constraints"], m.res_ops.VERIFY_OPERATION_DEF)
        for op_type, defn in sorted(found.items()):
            with self.subTest(operación=op_type):
                repeats = op_type in VERSION_TYPES
                # La compilación sube a 1.1 en la T44 (varios límites legales: F-1); las demás, 1.0.
                self.assertEqual((defn.version, defn.group, defn.repeatable),
                                 ("1.1" if op_type == "gis.compile_constraints" else "1.0",
                                  None, repeats))
                self.assertEqual(defn.scope, "version" if repeats else "project")
                self.assertEqual(session.requires_version(op_type), repeats)
                self.assertEqual(defn.commands, (COMMANDS[op_type],))
                for idname in defn.commands:
                    self.assertIn(idname, self.cat.commands)
                self.assertEqual(callable(defn.recompute), repeats)
                self.assertEqual(callable(defn.reproduce), repeats)
                self.assertEqual(defn.figure_tolerance,
                                 m.masks_provenance.FIGURE_TOLERANCE if repeats else None)
        self.assertIs(found["gis.compile_constraints"].recompute, m.gis_ops.recompute_compile)
        self.assertIs(found["res.verify_constraints"].recompute, m.res_ops.recompute_verify)
        # Las reproducciones que se registran son las de ``bl`` (importan el cálculo al usarse,
        # RNF-001-03, T38) y llaman a las de ``gis.masks.store`` y ``reserves.compliance_store``.
        self.assertIs(found["gis.compile_constraints"].reproduce, m.gis_ops.reproduce_compile)
        self.assertIs(found["res.verify_constraints"].reproduce, m.res_ops.reproduce_verify)
        for defn, store, name in ((found["gis.compile_constraints"], m.masks_store,
                                   "reproduce_compile"),
                                  (found["res.verify_constraints"], m.verify, "reproduce_verify")):
            request, outcome = object(), iter(())
            with mock.patch.object(store, name, return_value=outcome) as real:
                self.assertIs(defn.reproduce(request), outcome)
            real.assert_called_once_with(request)
            self.assertEqual(store.REPRODUCE[defn.op_type].__name__, name)
        for figure in (*m.masks_provenance.FIGURES, *m.verify.FIGURES):
            self.assertIs(m.contract.FIGURES[figure.key], figure)
        for defn in (*m.cparams.DEFINITIONS, *m.verify.DEFINITIONS):
            self.assertIs(m.params.DEFINITIONS[defn.key], defn)
        for family in m.cparams.FAMILIES:
            self.assertIs(m.params.FAMILIES[family.pattern], family)
        msgids = {defn.label_msgid for defn in found.values()}
        msgids |= {setting.label_msgid for defn in found.values() for setting in defn.settings}
        msgids |= {figure.label_msgid for figure in (*m.masks_provenance.FIGURES,
                                                     *m.verify.FIGURES)}
        msgids |= {defn.label_msgid for defn in (*m.cparams.DEFINITIONS, *m.verify.DEFINITIONS)}
        msgids |= {family.template.label_msgid for family in m.cparams.FAMILIES}
        msgids |= {message.msgid for message in m.cmessages.CATALOG}
        self.assertNotIn(None, msgids)
        self.assertEqual(m.i18n.untranslated(msgids), [])
        self.assertEqual(m.i18n.untranslated([STATUS_MSGID]), [])

        entry = self.cat.entries[ENTRY]
        self.assertEqual((entry.title, entry.title_es, entry.delivered), (*ENTRY_TITLE, True))
        aware = session.ProvenanceAwareOperator
        for op_type, idname in sorted(COMMANDS.items()):
            with self.subTest(orden=idname):
                cls = m.commands.registered_class(idname)
                if idname in DELIVERED:
                    self.assertEqual(self.cat.commands[idname].entry, ENTRY)
                    self.assertTrue(issubclass(cls, aware))
                    if op_type in SEARCH_TYPES:  # la ventana lanza uno; el otro, su interna
                        self.assertEqual(cls.provenance_op_type, "core.find_untouchables")
                        continue
                    self.assertEqual(cls.provenance_op_type, op_type)
                    continue
                # T22 a T28 las pasan a la 012 con su clase real
                self.assertEqual(self.cat.commands[idname].entry, "R-32")
                self.assertTrue(m.commands.is_provisional(cls))

    def test_the_two_commands_of_d31_are_in_the_catalog(self) -> None:
        """RF-012-28, D-31, D-38: «Compilar las máscaras» (acción) y «Verificar un diseño por
        recinto…» (diálogo) están en Diseño ▸ Límites y restricciones, tras «Ver restricciones y
        límites», con sus textos en los dos idiomas; la segunda, también como acceso cruzado en
        Cubicación; «Cuadrículas mineras…» sigue en R-32 (D-2)."""
        cat = self.cat
        compile_command = cat.commands["geoblender.gis_compile_constraints"]
        verify_command = cat.commands["geoblender.res_verify_constraints"]
        self.assertEqual((compile_command.label, compile_command.label_es, compile_command.action),
                         ("Compile the masks", "Compilar las máscaras", "A"))
        self.assertEqual((verify_command.label, verify_command.label_es, verify_command.action),
                         ("Verify a design by zone…", "Verificar un diseño por recinto…", "D"))
        design = cat.menus["GEOBLENDER_MT_ui_design"]
        keys = [item.key for item in design.groups[0].items]
        self.assertEqual(keys[-3:], ["geoblender.core_toggle_constraints_overlay",
                                     "geoblender.gis_compile_constraints",
                                     "geoblender.res_verify_constraints"])
        volumetrics = cat.menus["GEOBLENDER_MT_ui_volumetrics"]
        crossed = [item.key for group in volumetrics.groups for item in group.items
                   if item.cross]
        self.assertIn("geoblender.res_verify_constraints", crossed)
        self.assertEqual(cat.commands["geoblender.core_edit_mining_grid"].entry, "R-32")

    def test_recompute_stale_masks_by_the_queue(self) -> None:
        """D-19, RF-012-16, RF-008-24, RF-008-26 (plan A12): las máscaras de V01 (un límite
        legal con 2 m hacia dentro) quedan obsoletas al cambiar su resguardo; «Recalcular lo
        obsoleto» llama al recálculo de ``gis``, que empieza la compilación nueva «en curso» con
        el resguardo de hoy y deja sus pasos en la cola de ``gis``; ``recompute_steps`` espera
        («Esperando a «gis.compile_constraints»…») mientras el temporizador de la cola
        (``masks_tick``) los avanza, con el avance en la barra de estado; al terminar, la
        compilación nueva sustituye a la anterior en la revisión abierta de V01, las máscaras
        están al día y no queda nada obsoleto ni en la cola."""
        m = self.m
        gis_ops = m.gis_ops
        recompute = _module("core.provenance.recompute")
        graph = _module("core.provenance.graph")
        access = _module("gis.masks.access")
        project, version = self.project()
        code = self.declare_limit(project)
        first = self.compile_masks(project, version)
        self.assertEqual(access.mask_state(project, version.uid)[0], access.MaskState.CURRENT)
        self.change_inward(project, code)
        self.assertEqual(access.mask_state(project, version.uid)[0], access.MaskState.STALE)
        with project.read() as conn:
            self.assertEqual(recompute.plan_recompute(graph.load_graph(conn)).operations,
                             (first,))

        messages: list[str] = []
        waiting: list[list[str]] = []
        last = None
        with mock.patch.object(m.queue, "status_text") as status:
            for step in recompute.recompute_steps(project):
                messages.append(step.message)
                if gis_ops.pending_mask_runs():
                    waiting.append(gis_ops.pending_mask_runs())
                    gis_ops.masks_tick()  # el temporizador de la cola entre dos del modal
                last = step
        outcome = last.result
        self.assertEqual([(result.unit.op_types, str(result.status))
                          for result in outcome.results],
                         [(("gis.compile_constraints",), "done")])
        (second,) = outcome.results[0].operations
        self.assertIn("Esperando a «gis.compile_constraints»…", messages)
        self.assertTrue(waiting)
        self.assertEqual({tuple(uids) for uids in waiting}, {(second,)})
        shown = [call.args[0] for call in status.call_args_list]
        self.assertTrue(any(text and text.startswith("Recalculando «") and text.endswith(" %")
                            for text in shown), shown)
        self.assertIsNone(shown[-1])
        self.assertEqual(gis_ops.pending_mask_runs(), [])
        self.assertIsNone(gis_ops.masks_tick())

        (old,) = self.rows(project, "SELECT revision_uid, superseded_by FROM gb_operation "
                           "WHERE uid = ?", first)
        (new,) = self.rows(project, "SELECT status, revision_uid, supersedes_uid FROM "
                           "gb_operation WHERE uid = ?", second)
        self.assertEqual(new, ("done", old[0], first))
        self.assertEqual(old[1], second)
        (value,) = self.rows(project, "SELECT value FROM gb_operation_param WHERE "
                             "operation_uid = ? AND key = ?", second,
                             m.cparams.buffer_in_key(code))[0]
        self.assertEqual(json.loads(value), CHANGED_INWARD_M)
        self.assertEqual(access.mask_state(project, version.uid)[0], access.MaskState.CURRENT)
        with project.read() as conn:
            self.assertEqual(recompute.plan_recompute(graph.load_graph(conn)).operations, ())

    def test_the_queues_fail_report_and_close(self) -> None:
        """D-19, RF-012-28 (plan §2.1): la cola de ``gis`` avanza un paso por llamada de su
        temporizador, uno detrás de otro; unos pasos que fallan dejan «fallida» su operación
        (con el motivo) y sigue la siguiente; los avisos del resultado (los de la compilación)
        van al registro de Blender (``bl.ops.jobs.report_later``); desregistrar cierra lo que
        espera sin dar ni un paso más (como Esc: la operación queda cancelada y nada a medias) y
        quita el temporizador. La verificación hace lo mismo con la cola de ``res``: su recálculo
        (``res.verify_constraints``) deja los pasos de ``compliance_store.recompute_run`` en ella
        y los avisos de sus finales van al registro."""
        m = self.m
        gis_ops, res_ops = m.gis_ops, m.res_ops
        jobs_ops = _module("bl.ops.jobs")
        progress = _module("core.project.model").Progress
        masks_notice = SimpleNamespace(text=lambda language: f"aviso de las máscaras ({language})")
        check_notice = SimpleNamespace(text=lambda language: f"aviso de la verificación "
                                                           f"({language})")
        log: list[str] = []
        failed: list[tuple[str, str]] = []

        def handle(uid: str, op_type: str) -> Any:
            return SimpleNamespace(uid=uid, op_type=op_type, settings={},
                                   fail=lambda reason: failed.append((uid, reason)),
                                   cancel=lambda reason: failed.append((uid, reason)))

        def steps(name: str, result: Any = None, *, fail: bool = False) -> Iterator[Any]:
            try:
                log.append(f"{name} 1")
                yield progress("compile", 1, 2, "…")
                if fail:
                    raise RuntimeError("fallo inyectado")
                log.append(f"{name} 2")
                yield progress("save", 2, 2, "…", result)
            finally:
                log.append(f"{name} cerrado")

        stored_masks = SimpleNamespace(result=SimpleNamespace(notices=(masks_notice,)))
        stored_check = SimpleNamespace(result=SimpleNamespace(
            finals=(SimpleNamespace(notices=(check_notice,)),)))
        self.addCleanup(res_ops.RUNS.drop)
        self.addCleanup(gis_ops.register)  # al final de la prueba, desregistrada y vuelta a poner
        self.addCleanup(gis_ops.unregister)
        with mock.patch.object(m.queue, "status_text") as status:
            gis_ops.queue_mask_steps(handle("op-1", "gis.compile_constraints"),
                                     steps("a", fail=True))
            gis_ops.queue_mask_steps(handle("op-2", "gis.compile_constraints"),
                                     steps("b", stored_masks))
            self.assertTrue(bpy.app.timers.is_registered(gis_ops.masks_tick))
            self.assertEqual(gis_ops.pending_mask_runs(), ["op-1", "op-2"])
            with self.assertLogs("geoblender.bl.ops", "ERROR"):
                while gis_ops.masks_tick() is not None:
                    pass
            self.assertEqual(log, ["a 1", "a cerrado", "b 1", "b 2", "b cerrado"])
            self.assertEqual([uid for uid, _reason in failed], ["op-1"])
            self.assertIn("RuntimeError: fallo inyectado", failed[0][1])
            self.assertIn(("WARNING", masks_notice.text("es")), jobs_ops.sent_reports())
            shown = [call.args[0] for call in status.call_args_list]
            self.assertIn("Recalculando «Compilación de las restricciones»… 50 %", shown)
            self.assertIsNone(shown[-1])
            log.clear()
            gis_ops.queue_mask_steps(handle("op-3", "gis.compile_constraints"), steps("c"))
            gis_ops.masks_tick()
            gis_ops.unregister()
        self.assertEqual(log, ["c 1", "c cerrado"])  # la empezada la cancelan sus pasos
        self.assertEqual([uid for uid, _reason in failed], ["op-1"])
        self.assertEqual(gis_ops.pending_mask_runs(), [])
        self.assertFalse(bpy.app.timers.is_registered(gis_ops.masks_tick))

        log.clear()
        verification = handle("op-4", "res.verify_constraints")
        request = SimpleNamespace(project=None, op_type="res.verify_constraints")
        with mock.patch.object(m.verify, "recompute_run",
                               return_value=(verification, steps("d", stored_check))) as run:
            self.assertIs(res_ops.recompute_verify(request), verification)
        run.assert_called_once_with(request)
        self.assertEqual(res_ops.pending_runs(), ["op-4"])
        with mock.patch.object(m.queue, "status_text"):
            while res_ops.res_tick() is not None:
                pass
        self.assertEqual(log, ["d 1", "d 2", "d cerrado"])
        self.assertIn(("WARNING", check_notice.text("es")), jobs_ops.sent_reports())
        self.assertEqual(res_ops.pending_runs(), [])

    def test_disable_leaves_nothing_of_the_constraints(self) -> None:
        """Principio 8, RF-012-28 (``geoblender/AGENTS.md``, Registro; plan §2.1): habilitada, la
        012 tiene sus declaraciones en ``core``, ``WindowManager.geoblender_constraints`` y su
        grupo; deshabilitarla, con unos pasos esperando en la cola de ``gis`` sin haber empezado,
        deja su operación cancelada (no «en curso») sin dar ningún paso y no deja ninguna clase,
        propiedad, temporizador, parámetro, familia, operación, cifra ni comprobación de congelar
        de la 012, y la huella entera de Blender (clases, propiedades, manejadores, temporizadores,
        traducciones…) vuelve a la del principio de la sesión."""
        m = self.m
        props = _module("bl.props.core_constraints")
        self.assertTrue(all(cls.is_registered for cls in props.classes))
        rna = bpy.types.WindowManager.bl_rna.properties[WM_PROPERTY]
        self.assertEqual((rna.type, rna.fixed_type.identifier), ("POINTER", GROUP))
        self.assertIsInstance(getattr(bpy.context.window_manager, WM_PROPERTY),
                              props.GEOBLENDER_PG_core_constraints)
        self.assertEqual({name: len(keys) for name, keys in m.ours().items()}, COUNTS)
        closed: list[str] = []
        cancelled: list[str] = []

        def steps() -> Iterator[Any]:
            try:
                yield _module("core.project.model").Progress("compile", 1, 2, "…")
            finally:
                closed.append("cerrado")

        waiting = SimpleNamespace(uid="op-9", op_type="gis.compile_constraints", settings={},
                                  fail=lambda reason: None, cancel=cancelled.append)
        m.gis_ops.queue_mask_steps(waiting, steps())
        self.assertTrue(bpy.app.timers.is_registered(m.gis_ops.masks_tick))

        self.addCleanup(blender_ext.enable)  # las demás pruebas de la clase, habilitada
        blender_ext.disable()
        self.assertEqual([cls.__name__ for cls in props.classes if cls.is_registered], [])
        self.assertEqual([name for name in dir(bpy.types)
                          if name.startswith("GEOBLENDER_") and "_core_constraints" in name], [])
        self.assertFalse(hasattr(bpy.types.WindowManager, WM_PROPERTY))
        self.assertEqual(m.ours(), {name: [] for name in COUNTS})
        self.assertEqual(m.gis_ops.pending_mask_runs(), [])
        self.assertEqual(closed, [])  # nunca empezó: cerrarlo no da ningún paso
        self.assertEqual(cancelled, [DROPPED])
        self.assertFalse(bpy.app.timers.is_registered(m.gis_ops.masks_tick))
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(),
                                                      blender_ext.state_fingerprint()), [])


HEAVY: tuple[str, ...] = (
    "gis.masks.access", "gis.masks.combine", "gis.masks.compile", "gis.masks.export",
    "gis.masks.overlay", "gis.masks.sectors", "gis.masks.sources", "gis.masks.store",
    "gis.masks.zones", "gis.search", "reserves.compliance", "reserves.compliance_store",
    "core.versions.freeze", "core.versions.reproduce", "core.versions.copy",
    "core.versions.check", "core.provenance.lineage", "core.provenance.recompute",
    # El cálculo de la 016 (spec 016, T51; RNF-001-03): ninguno se importa al habilitar, tampoco por un
    # nombre que ``design.model`` ofrece al pedirlo (``__getattr__``), que el árbol sintáctico no ve.
    "design.stockpiles", "design.stockpile_store", "design.removal", "design.supported_store",
    "design.thickness", "design.buttress", "design.supported_edge", "design.morphology",
    "design.supported_requests",
    # El perfil de pista de la 017 (spec 017, T04): se importa al usarlo; ``provenance`` declara su operación.
    "design.road_profiles",
    # Los datos de la pista y de la accesibilidad de la 017 (spec 017, T05): se importan al usarlos.
    "design.road_model",
    # La malla, los 16 rumbos y la red 2D de la ruta de la 017 (spec 017, T06): los pide quien traza una pista.
    "design.road_net",
    # La ruta 3D de mínimo coste de la ruta de la 017 (spec 017, T07): la pide quien traza una pista.
    "design.road_route",
    # El eje con curvas circulares de la 017 (spec 017, T10): lo pide quien forma el eje de una pista.
    "design.road_axis",
    # La rasante acotada de la 017 (spec 017, T11): la pide quien da la rasante a un eje.
    "design.road_gradient",
    # La sección tipo de la 017 (spec 017, T12): la pide quien calcula una pista.
    "design.road_section",
    # El grabado de la sección y su borde con dos ángulos de la 017 (spec 017, T13): lo pide quien calcula una pista.
    "design.road_engrave",
    # Lo alcanzable y las cotas de la accesibilidad de la 017 (spec 017, T15): lo pide quien calcula la accesibilidad.
    "design.road_access",
    # La operación de accesibilidad de la 017 (spec 017, T17): preparar, calcular por pasos y el resumen.
    "design.access_store",
    # Preparar la pista de la 017 (spec 017, T19): la piden las órdenes al usarla.
    "design.road_store",
    # La capa de ejes de pistas de la 017 (spec 017, T26): se importa al usarla, solo si la versión tiene pistas.
    "design.road_layer",
    # Lo que la barra N lee de una pista y de una accesibilidad (spec 017, T31b): se importa al usarla, al seleccionar una.
    "design.road_card")
"""Lo que habilitar no importa (los de la 012 que fija ``tests/unit/architecture/test_lazy_registration``,
y los de la 016 y la 017, que esa prueba mira por sus importaciones de nivel de módulo)."""
LIGHT: tuple[str, ...] = ("core.constraints.provenance", "gis.masks.provenance",
                          "reserves.provenance", "core.versions.freezing")
"""Lo que sí: las declaraciones que registra ``bl``."""


class LazyRegistrationTest(unittest.TestCase):
    """La extensión de cero (``blender_ext.fresh``), sin importar nada antes de habilitarla."""

    def loaded(self) -> set[str]:
        """Los módulos de la extensión importados ahora, sin el prefijo de la copia de pruebas."""
        prefix = module_name() + "."
        return {name.removeprefix(prefix) for name in blender_ext.loaded_modules()}

    def test_enabling_does_not_load_the_heavy_modules(self) -> None:
        """RNF-001-03, plan 012 §7.4: habilitar de cero registra la 012 (sus declaraciones ligeras)
        sin importar ningún módulo de :data:`HEAVY`, y deja el recolector de basura activo."""
        self.assertTrue(gc.isenabled())
        with blender_ext.fresh():
            blender_ext.enable()
            loaded = self.loaded()
            self.assertEqual(sorted(set(HEAVY) & loaded), [])
            self.assertEqual(sorted(set(LIGHT) - loaded), [])
            self.assertTrue(gc.isenabled())

    def test_the_first_use_loads_what_it_needs(self) -> None:
        """RNF-001-03: con la extensión habilitada de cero, lo que se registró importa el cálculo en
        su primera llamada: la reproducción de la compilación carga ``gis.masks.store`` (y la
        cadena de versiones que arrastra) y no el almacén de la verificación; la comprobación de
        congelar de ``res`` carga ``reserves.compliance_store``; la reproducción de la verificación
        llega a su función (su guarda rechaza lo que no es una petición de reproducir)."""
        with blender_ext.fresh():
            blender_ext.enable()
            gis_ops = _module("bl.ops.gis")
            res_ops = _module("bl.ops.res")
            core_ops = _module("bl.ops.core_constraints")
            freezing = _module("core.versions.freezing")
            checks = [check for module, check in freezing.freeze_checks() if module == "res"]
            self.assertEqual(checks, [core_ops.freeze_findings])
            self.assertEqual(sorted({"gis.masks.store", "reserves.compliance_store"}
                                    & self.loaded()), [])
            with self.assertRaises(ValueError):  # la guarda de la reproducción, ya importada
                gis_ops.reproduce_compile(object())
            self.assertIn("gis.masks.store", self.loaded())
            self.assertNotIn("reserves.compliance_store", self.loaded())
            with self.assertRaises(sqlite3.OperationalError):  # la base no es un proyecto
                checks[0](sqlite3.connect(":memory:"), "V01")
            self.assertIn("reserves.compliance_store", self.loaded())
            with self.assertRaises(ValueError):
                res_ops.reproduce_verify(object())


if __name__ == "__main__":
    unittest.main()
