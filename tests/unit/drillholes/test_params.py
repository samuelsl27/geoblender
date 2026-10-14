# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros de los sondeos (spec 005, T20; HU-005-1; RF-005-16, RF-005-26; plan 005 §5.2.4
y §5.6.3, D-17 y D-18; RF-008-01 a RF-008-06).

``drillholes.params`` declara con el ``ParamDef`` de ``core.params`` (spec 008) las ocho
definiciones del plan §5.6.3, todas ADOPTADO de origen ``algorithm``, cada una con su
etiqueta (``label_msgid``, con su español en ``core/i18n/messages.toml``); no registra nada:
las registra ``bl/ops/dh.py`` y quedan «sin confirmar» en el proyecto hasta que una persona
las confirma:

- los cinco umbrales de la validación (spec §11: 0,01 m, 0,01 m, 0,05 m, 3 °/30 m y 2 m), los
  que lee ``dh.validate`` y los campos de ``drillholes.validate.ValidationParams``;
- el paso de las trazas (2 m), que lee ``dh.desurvey`` con la tolerancia de profundidad;
- la regla de los valores bajo el límite de detección (RF-005-26, D-4: la mitad del límite),
  partida en ``dh.below_dl.method`` (``factor``, ``limit``, ``zero`` o ``absent``) y
  ``dh.below_dl.factor`` (0,5 en [0; 1]) porque un ``ParamDef`` no guarda un objeto (D-17).
  Ninguna operación de la 005 la lee (la consumen R-14 y R-15): cambiarla añade historial con
  su motivo y no deja obsoleto ningún dato ``dh_`` ni cambia el hash de ``dh_assay`` (los
  valores guardados no cambian).

Fuera de rango, ``core.param_out_of_range`` con la clave (o ``core.param_not_choice`` en la
regla). Las pruebas del proyecto escriben en uno real de esquema 2 una base, una validación y
unas trazas con las operaciones de la T40 y cambian los parámetros con el ``ParameterStore``
de la 008 (lo que hace ``geoblender.core_set_parameter``, D-22). Cada prueba deja los
registros de ``core`` (operaciones, lectores y parámetros) como los encontró.
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.dh_sets import params as csv_errores_params
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered, snapshot
from tests.unit.drillholes.test_schema import _rows

params = import_geoblender("drillholes.params")
provenance = import_geoblender("drillholes.provenance")
schema = import_geoblender("drillholes.schema")
validate = import_geoblender("drillholes.validate")
core_params = import_geoblender("core.params")
units = import_geoblender("core.units")
operations = import_geoblender("core.provenance.operations")
stale = import_geoblender("core.provenance.stale")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
i18n = import_geoblender("core.i18n")

ParamError = core_params.ParamError
SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
DEPTH = "dh.validation.depth_tolerance_m"
GAP = "dh.validation.gap_tolerance_m"
MIN_INTERVAL = "dh.validation.min_interval_m"
DOGLEG = "dh.validation.dogleg_max_deg_30m"
COLLAR_DEM = "dh.validation.collar_dem_tolerance_m"
TRACE_STEP = "dh.desurvey.trace_step_m"
METHOD = "dh.below_dl.method"
FACTOR = "dh.below_dl.factor"
METHODS = ("factor", "limit", "zero", "absent")

# Plan 005 §5.6.3, en su orden: clave → (tipo de valor, unidad, valor por defecto, mínimo,
# máximo, mínimo excluido). Los valores por defecto son los de la spec §11 y D-4; los rangos
# no los fija el plan: son los de drillholes/params.py (decisión de T20, revisable). El
# paso de las trazas excluye el 0 (una polilínea necesita un paso positivo).
EXPECTED: dict[str, tuple[str, str, object, float | None, float | None, bool]] = {
    DEPTH: ("float", "m", 0.01, 0.0, 1.0, False),
    GAP: ("float", "m", 0.01, 0.0, 1.0, False),
    MIN_INTERVAL: ("float", "m", 0.05, 0.0, 10.0, False),
    DOGLEG: ("float", "deg/30m", 3.0, 0.0, 180.0, False),
    COLLAR_DEM: ("float", "m", 2.0, 0.0, 100.0, False),
    TRACE_STEP: ("float", "m", 2.0, 0.0, 100.0, True),
    METHOD: ("text", "-", "factor", None, None, False),
    FACTOR: ("float", "-", 0.5, 0.0, 1.0, False),
}
# Los requisitos que usa cada clave.
EXPECTED_RF: dict[str, tuple[str, ...]] = {
    DEPTH: ("RF-005-16", "RF-005-17"),
    GAP: ("RF-005-16",),
    MIN_INTERVAL: ("RF-005-16",),
    DOGLEG: ("RF-005-16",),
    COLLAR_DEM: ("RF-005-16", "RF-005-18"),
    TRACE_STEP: ("RF-005-20", "RF-005-23"),
    METHOD: ("RF-005-26",),
    FACTOR: ("RF-005-26",),
}
# Plan §5.6.3: quién consume cada clave (columna «La consume»).
VALIDATION_KEYS = (DEPTH, GAP, MIN_INTERVAL, DOGLEG, COLLAR_DEM)
DESURVEY_KEYS = (DEPTH, TRACE_STEP)
PERSON = dict(source="Informe de reservas 2026, criterio de leyes", source_kind="document",
              decided_by="Responsable de geología de IMGA")


def _recompute(request: Any) -> Any:  # nunca se llama aquí
    raise AssertionError("las pruebas de los parámetros no recalculan")


@contextmanager
def _reader_registered(reader: Any) -> Iterator[None]:
    """Registra ``reader`` si aún no está y lo quita al salir."""
    added = reader.id not in readers.READERS
    if added:
        readers.register_reader(reader)
    try:
        yield
    finally:
        if added:
            readers.unregister_reader(reader.id)


class _RegistriesUntouched(unittest.TestCase):
    """Comprueba al terminar cada prueba que los registros de ``core`` (operaciones, lectores
    y parámetros) están como al empezarla."""

    def setUp(self) -> None:
        before = self._registries()
        self.addCleanup(lambda: self.assertEqual(self._registries(), before,
                                                 "la prueba dejó algo registrado"))

    @staticmethod
    def _registries() -> tuple[Any, ...]:
        return snapshot(), dict(readers.READERS), dict(core_params.DEFINITIONS)


class DefinitionsTest(unittest.TestCase):
    def test_the_eight_definitions_of_the_plan(self) -> None:
        """RF-005-16, RF-005-26, RF-008-01 (plan §5.6.3, D-17): las ocho claves del plan, en
        su orden y sin repetir, con el ``ParamDef`` de ``core.params`` (del módulo ``dh``),
        por clave en ``PARAMS``."""
        keys = [definition.key for definition in params.DEFINITIONS]
        self.assertEqual(keys, list(EXPECTED))
        self.assertEqual(list(params.PARAMS), list(EXPECTED))
        self.assertIs(params.ParamDef, core_params.ParamDef)
        for definition in params.DEFINITIONS:
            with self.subTest(key=definition.key):
                self.assertIsInstance(definition, core_params.ParamDef)
                self.assertEqual(definition.module, "dh")
                self.assertIs(params.param(definition.key), definition)
                self.assertIs(params.PARAMS[definition.key], definition)
        self.assertEqual(params.VALIDATION_KEYS, VALIDATION_KEYS)
        self.assertEqual(params.DESURVEY_KEYS, DESURVEY_KEYS)
        self.assertEqual(params.BELOW_DL_KEYS, (METHOD, FACTOR))
        self.assertEqual(params.BELOW_DL_METHODS, METHODS)

    def test_defaults_units_ranges_type_and_source(self) -> None:
        """RF-005-16, RF-005-26, RF-008-01, RF-008-04 (spec §11, D-4, D-6; plan §5.6.3,
        D-18): el tipo de valor, la unidad del catálogo (``deg/30m`` para el cambio de
        dirección), el valor por defecto con su tipo, el rango, ADOPTADO de origen
        ``algorithm``, su procedencia y los RF que lo usan; la regla, un texto entre sus
        cuatro opciones, por defecto ``factor`` con 0,5: la mitad del límite."""
        for key, (value_type, unit, default, low, high, low_excluded) in EXPECTED.items():
            with self.subTest(key=key):
                definition = params.param(key)
                self.assertEqual(definition.value_type, value_type)
                self.assertEqual(definition.unit, unit)
                self.assertIn(unit, units.UNITS)
                self.assertEqual(definition.default, default)
                self.assertIs(type(definition.default), type(default))
                self.assertEqual((definition.minimum, definition.maximum), (low, high))
                self.assertIs(definition.min_exclusive, low_excluded)
                self.assertEqual(definition.kind, "ADOPTADO")
                self.assertEqual(definition.source_kind, "algorithm")
                self.assertEqual(definition.scope, "project")
                self.assertFalse(definition.allow_empty)
                self.assertTrue(definition.source.strip(), "sin procedencia")
                self.assertEqual(definition.requirements, EXPECTED_RF[key])
                self.assertEqual(params.default(key), default)
        self.assertEqual(params.param(METHOD).choices, METHODS)
        self.assertEqual(units.symbol("deg/30m"), "°/30 m")
        self.assertEqual(params.param(DOGLEG).range_text(), "[0; 180] °/30 m")
        self.assertEqual(params.param(TRACE_STEP).range_text(), "(0; 100] m")
        self.assertEqual(params.param(FACTOR).range_text(), "[0; 1]")
        self.assertEqual(params.param(METHOD).range_text(), "")

    def test_validation_thresholds_are_those_of_validate(self) -> None:
        """RF-005-16 (spec §11): las cinco claves de la validación son, en su orden, los
        campos de ``ValidationParams``, y sus valores por defecto dan los umbrales de
        ``csv_errores/esperado.json`` (los de CE-005-01)."""
        fields = tuple(item.name for item in dataclasses.fields(validate.ValidationParams))
        self.assertEqual(tuple(key.rpartition(".")[2] for key in VALIDATION_KEYS), fields)
        defaults = validate.ValidationParams(**{
            key.rpartition(".")[2]: params.default(key) for key in VALIDATION_KEYS})
        self.assertEqual(defaults, csv_errores_params())

    def test_parameters_read_by_each_operation(self) -> None:
        """RF-005-16, RF-005-26 (plan §5.6.3 y §5.6.4): ``dh.validate`` lee los cinco
        umbrales y ``dh.desurvey`` la tolerancia de profundidad y el paso; cada parámetro que
        lee una operación de la 005 está declarado aquí, y la regla bajo el límite no la lee
        ninguna (R-14 y R-15)."""
        by_type = {declared.op_type: declared.params for declared in provenance.OPERATION_TYPES}
        self.assertEqual(by_type[provenance.VALIDATE], VALIDATION_KEYS)
        self.assertEqual(by_type[provenance.DESURVEY], DESURVEY_KEYS)
        read = {key for keys in by_type.values() for key in keys}
        self.assertLessEqual(read, set(params.PARAMS))
        self.assertEqual(set(params.PARAMS) - read, {METHOD, FACTOR})

    def test_bounds_accepted_and_outside_rejected(self) -> None:
        """RF-005-16, RF-005-26, RF-008-03: ``check`` acepta el valor por defecto y los
        extremos incluidos del rango y rechaza lo de fuera con ``ParamError``
        ``core.param_out_of_range``, con la clave como campo y en el mensaje."""
        for key, (value_type, _unit, default, low, high, low_excluded) in EXPECTED.items():
            if value_type != "float":
                continue
            definition = params.param(key)
            with self.subTest(key=key):
                self.assertEqual(definition.check(default), default)
                if not low_excluded:
                    self.assertEqual(definition.check(low), low)
                self.assertEqual(definition.check(high), high)
                self.assertIs(type(definition.check(1)), float)
                for outside in (high + 1e-9, low if low_excluded else low - 1e-9):
                    with self.assertRaises(ParamError) as caught:
                        definition.check(outside)
                    self.assertEqual(caught.exception.code, "core.param_out_of_range")
                    self.assertEqual(caught.exception.field, key)
                    self.assertIn(f"«{key}»", str(caught.exception))
        with self.assertRaises(ParamError) as caught:
            params.param(FACTOR).check(1.5)
        self.assertEqual(str(caught.exception),
                         "Parámetro «dh.below_dl.factor»: 1,5 está fuera de su rango [0; 1].")

    def test_rule_options_and_wrong_types(self) -> None:
        """RF-005-26, RF-008-03 (D-17): la regla admite sus cuatro opciones y nada más
        (``core.param_not_choice``, con la clave), ni vacía (``core.param_missing``); un
        umbral no admite un booleano, un texto ni un NaN."""
        rule = params.param(METHOD)
        for option in METHODS:
            self.assertEqual(rule.check(option), option)
        cases = (
            (METHOD, "median", "core.param_not_choice"),
            (METHOD, "Factor", "core.param_not_choice"),
            (METHOD, "", "core.param_missing"),
            (METHOD, None, "core.param_missing"),
            (METHOD, 0.5, "core.param_not_text"),
            (GAP, True, "core.param_not_number"),
            (GAP, "0,01", "core.param_not_number"),
            (DOGLEG, math.nan, "core.param_not_number"),
            (FACTOR, None, "core.param_missing"),
        )
        for key, value, code in cases:
            with self.subTest(key=key, value=value):
                with self.assertRaises(ParamError) as caught:
                    params.param(key).check(value)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.field, key)
        self.assertEqual(core_params.parse_value(params.param(DOGLEG), "3,5 °/30 m"), 3.5)
        self.assertEqual(core_params.parse_value(params.param(GAP), "0,02 m"), 0.02)
        self.assertEqual(core_params.parse_value(params.param(METHOD), " limit "), "limit")

    def test_labels_with_their_spanish(self) -> None:
        """RF-008-06 (principio 10): cada definición lleva su etiqueta para el panel de
        parámetros, un ``msgid`` en inglés, distinto en cada una y sin marcadores, con su
        español en ``core/i18n/messages.toml``."""
        table = i18n.load_messages()
        labels = [definition.label_msgid for definition in params.DEFINITIONS]
        self.assertEqual(len(set(labels)), len(EXPECTED), "etiquetas repetidas o sin etiqueta")
        for definition in params.DEFINITIONS:
            label = definition.label_msgid
            with self.subTest(key=definition.key, label=label):
                self.assertIsInstance(label, str)
                self.assertTrue(label.strip())
                self.assertEqual(set(label) & SPANISH_LETTERS, set(), "msgid en inglés")
                self.assertEqual(i18n.placeholders(label), set())
                self.assertIn(label, table)
                self.assertNotEqual(table[label], label)
                self.assertEqual(i18n.translate("es", label), table[label])

    def test_unknown_key_and_repeated_key(self) -> None:
        """Una clave que no es de los sondeos es un error del programa (``KeyError``); un
        índice con una clave repetida, también (``ValueError``: no se pierde en silencio)."""
        with self.assertRaisesRegex(KeyError, "dh.no_such"):
            params.param("dh.no_such")
        first = params.DEFINITIONS[0]
        with self.assertRaisesRegex(ValueError, first.key):
            params.index_definitions((first, first))


class RegistrationTest(_RegistriesUntouched):
    def test_registered_and_removed_without_trace(self) -> None:
        """RF-008-01 (plan §5.6.3): ``bl`` registra las ocho en ``core.params`` y las quita con
        ``unregister_definitions("dh")`` sin dejar rastro; registrarlas dos veces es un
        error del programa y no cambia lo registrado."""
        before = dict(core_params.DEFINITIONS)
        self.addCleanup(core_params.unregister_definitions, "dh")
        core_params.register_definitions(params.DEFINITIONS)
        for definition in params.DEFINITIONS:
            self.assertIs(core_params.DEFINITIONS[definition.key], definition)
        with self.assertRaises(ValueError):
            core_params.register_definitions(params.DEFINITIONS)
        self.assertEqual(core_params.unregister_definitions("dh"), len(EXPECTED))
        self.assertEqual(dict(core_params.DEFINITIONS), before)
        self.assertEqual(core_params.unregister_definitions("dh"), 0)


class ProjectRuleTest(_RegistriesUntouched):
    """Un proyecto real de esquema 2 con los parámetros y las operaciones de la 005
    registrados, una base (bocas, desviaciones y análisis con filas), una validación y unas
    trazas hechas."""

    def setUp(self) -> None:
        super().setUp()
        functions = {op_type: _recompute for op_type in provenance.REPEATABLE}
        self.enterContext(registered(*provenance.operation_defs(functions)))
        self.enterContext(_reader_registered(builtin.GPKG_LAYER))
        core_params.register_definitions(params.DEFINITIONS)
        self.addCleanup(core_params.unregister_definitions, "dh")
        tmp = self.enterContext(project_tmp("gb-t20-"))
        (tmp / "proyectos").mkdir()
        self.project = create.create_project(
            tmp / "proyectos", make_settings(), make_session(), userdata_mod.UserData(tmp / "u"),
            clock=FakeClock()).project
        self.addCleanup(self.project.close)
        self.store = core_params.ParameterStore(self.project)
        self._run(provenance.BUILD_BASE, ("dh_collar", "dh_survey", "dh_assay"), rows=True)
        self._run(provenance.VALIDATE, ("dh_validation_issue",), keys=VALIDATION_KEYS,
                  uses=(("dh_collar", "collar"), ("dh_survey", "survey"),
                        ("dh_assay", "assay")))
        self._run(provenance.DESURVEY, ("dh_trace",), keys=DESURVEY_KEYS,
                  uses=(("dh_collar", "collar"), ("dh_survey", "survey")))

    def _run(self, op_type: str, tables: tuple[str, ...], *, keys: tuple[str, ...] = (),
             uses: tuple[tuple[str, str], ...] = (), rows: bool = False) -> None:
        """La operación ``op_type`` hecha: lee ``keys`` y ``uses`` y escribe ``tables``."""
        handle = operations.begin_operation(
            self.project, op_type, settings={}, params=keys, executor="blender",
            inputs=[operations.Use(item, role) for item, role in uses])
        with self.project.write_transaction() as conn:
            outputs = []
            for table in tables:
                layout = schema.LAYOUTS[table]
                schema.create_table(conn, layout, table, 25830)
                if rows:
                    schema.insert_rows(conn, layout, table, _rows(layout))
                epsg = 25830 if layout.geometry_type is not None else None
                outputs.append(provenance.dataset_spec(table, crs_epsg=epsg))
            software = {"pyproj": "3.7.2"} if op_type == provenance.BUILD_BASE else None
            handle.complete(conn, outputs=outputs, software=software)

    def _state(self) -> tuple[Any, ...]:
        """Las filas de ``dh_assay`` y el hash de contenido y el estado de cada dato."""
        with self.project.read() as conn:
            assays = conn.execute("SELECT * FROM dh_assay ORDER BY fid").fetchall()
            datasets = conn.execute("SELECT name, content_sha256, status FROM gb_dataset "
                                    "ORDER BY name").fetchall()
        return assays, datasets

    def _stale(self) -> set[str]:
        return {item.name for item in stale.stale_items(self.project).items}

    def _ensure_rule(self) -> None:
        """Lo que hará la primera importación (plan §5.6.3): registrar la regla con su valor
        por defecto, «sin confirmar»."""
        with self.project.write_transaction() as conn:
            for key in params.BELOW_DL_KEYS:
                self.store.ensure_default(
                    conn, key, geoblender_version=self.project.session.geoblender_version)

    def test_changing_the_rule_adds_history_and_leaves_dh_data_current(self) -> None:
        """RF-005-26, RF-008-02, RF-008-04 (plan §5.6.3, D-17, D-22): la regla se registra con
        su valor por defecto (la mitad del límite, ADOPTADO, «sin confirmar»); cambiarla con su
        motivo añade una fila al historial con el valor anterior intacto, y no deja obsoleto
        ningún dato ``dh_`` ni cambia las filas ni el hash de contenido de ``dh_assay``."""
        self.assertEqual(self._stale(), set())
        before = self._state()
        self.assertIn("dh_assay", [name for name, _sha, _status in before[1]])
        self.assertEqual(len(before[0]), 3)
        self._ensure_rule()
        for key, value in ((METHOD, "factor"), (FACTOR, 0.5)):
            record = self.store.get(key)
            self.assertEqual((record.value, record.kind, record.source_kind, record.unconfirmed),
                             (value, "ADOPTADO", "algorithm", True))
        with self.project.write_transaction() as conn:
            self.store.change(conn, FACTOR, value=0.25, reason="Criterio del informe", **PERSON)
            self.store.change(conn, METHOD, value="zero", reason="Leyes conservadoras",
                              **PERSON)
        for key, old, new, reason in ((METHOD, "factor", "zero", "Leyes conservadoras"),
                                      (FACTOR, 0.5, 0.25, "Criterio del informe")):
            with self.subTest(key=key):
                history = self.store.history(key)
                self.assertEqual([entry.action for entry in history], ["default", "change"])
                self.assertEqual([entry.value for entry in history], [old, new])
                self.assertEqual(history[1].reason, reason)
                self.assertTrue(history[0].reason.strip())
                record = self.store.get(key)
                self.assertEqual((record.value, record.unconfirmed), (new, False))
        self.assertEqual(self._stale(), set())
        self.assertEqual(stale.stale_items(self.project).counts.obsolete, 0)
        self.assertEqual(self._state(), before)

    def test_rule_out_of_range_is_rejected_without_writing(self) -> None:
        """RF-005-26, RF-008-03: una regla fuera de rango o que no es una de sus opciones se
        rechaza con su código y la clave (``core.param_out_of_range``,
        ``core.param_not_choice``), sin escribir nada y con el proyecto en escritura."""
        self._ensure_rule()
        history = {key: self.store.history(key) for key in params.BELOW_DL_KEYS}
        for key, value, code in ((FACTOR, 1.5, "core.param_out_of_range"),
                                 (FACTOR, -0.1, "core.param_out_of_range"),
                                 (METHOD, "median", "core.param_not_choice")):
            with self.subTest(key=key, value=value):
                with self.assertRaises(ParamError) as caught:
                    with self.project.write_transaction() as conn:
                        self.store.change(conn, key, value=value, reason="Prueba", **PERSON)
                self.assertEqual((caught.exception.code, caught.exception.field), (code, key))
                self.assertTrue(self.project.writable)
        self.assertEqual({key: self.store.history(key) for key in params.BELOW_DL_KEYS},
                         history)

    def test_thresholds_leave_stale_what_reads_them(self) -> None:
        """RF-005-16, RF-005-22, RF-008-02 (control positivo de la anterior): cambiar un umbral
        de la validación deja obsoletas las incidencias, y no las trazas; cambiar el paso de
        las trazas, las trazas; la base, nunca."""
        with self.project.write_transaction() as conn:
            self.store.change(conn, GAP, value=0.02, reason="Tramos de RC", **PERSON)
        self.assertEqual(self._stale(), {"dh_validation_issue"})
        with self.project.write_transaction() as conn:
            self.store.change(conn, TRACE_STEP, value=1.0, reason="Vista más fina", **PERSON)
        self.assertEqual(self._stale(), {"dh_validation_issue", "dh_trace"})


if __name__ == "__main__":
    unittest.main()
