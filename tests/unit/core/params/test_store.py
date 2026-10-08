# SPDX-License-Identifier: GPL-3.0-or-later
"""Valores de los parámetros del proyecto y su historial (spec 008, T13; RF-008-01,
RF-008-02, RF-008-04, RF-008-05; CE-008-03; plan 008 §5.2.1, §5.3.1 y §2.3 S-1).

``core.params.store.ParameterStore`` guarda en ``gb_parameter`` el valor vigente de cada
parámetro del proyecto, con su unidad, su tipo (MEDIDO, CALCULADO, ADOPTADO o HIPÓTESIS),
su origen, quién lo decidió, cuándo y por qué, y en ``gb_parameter_history`` una fila por
cada alta, cambio o confirmación, que no se modifica nunca:

- un parámetro sin tipo, un CALCULADO tecleado (sin la cifra de la que sale) y un cambio sin
  motivo se rechazan con los textos de la spec §8, sin escribir nada y sin dejar el proyecto
  en solo lectura;
- el K de esponjamiento que pasa por seis valores y acaba ADOPTADO conserva sus siete filas,
  y las seis primeras siguen diciendo HIPÓTESIS (CE-008-03);
- un valor por defecto se registra «sin confirmar», con el origen «valor por defecto de
  Geoblender <versión>» y el decisor «Geoblender (valor por defecto)»; confirmarlo no pide
  motivo, quita la marca y añade una fila (RF-008-04, RF-008-02);
- adoptar como CALCULADO el valor de una cifra lo hace una persona, con la operación de la
  que sale la cifra (decisión S-1 de Samuel: ningún cálculo cambia un parámetro);
- ``resolve`` da a una operación la clave, el valor, la unidad, el tipo, el ámbito y la
  revisión que usa (RF-008-05);
- ``value_sha256`` (lo que compara la cascada, plan D10) no cambia con un cambio solo de
  tipo.

Cada prueba crea su proyecto sintético (esquema 2) con un reloj simulado y la sesión de
``tests.support.core_fixtures``; los rechazos se comprueban dentro de
``Project.write_transaction()``, como los hará la interfaz.
"""

import datetime as dt
import sqlite3
import unittest
from collections.abc import Callable, Mapping
from typing import Any

from tests.support.core_fixtures import (
    CLOCK_START,
    FakeClock,
    make_session,
    make_settings,
    project_tmp,
)
from tests.support.package import import_geoblender
from tests.unit.core.provenance.test_schema import (
    FIGURE_UID,
    OP_UID,
    UNKNOWN_UID,
    figure_row,
    operation_row,
)

create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
params = import_geoblender("core.params")
store_mod = import_geoblender("core.params.store")
core_defs = import_geoblender("core.params.core_defs")
hashing = import_geoblender("core.hashing")
timeutil = import_geoblender("core.timeutil")

SESSION = make_session()
USER_HOST = SESSION.user_host
KEY = "res.swell_factor"
DEFAULT_DECIDER = "Geoblender (valor por defecto)"
OTHER_FIGURE_UID = "00000000-0000-4000-8000-0000000000b2"

# Los textos de la spec §8 (sin el punto final, que añade el mensaje).
SPEC_NO_KIND = (
    "El parámetro «res.swell_factor» necesita un tipo: MEDIDO, CALCULADO, ADOPTADO o HIPÓTESIS"
)
SPEC_CALCULATED = (
    "Un parámetro CALCULADO lo escribe una operación; para fijarlo a mano, elija ADOPTADO o "
    "HIPÓTESIS"
)
SPEC_NO_REASON = "Indique el motivo del cambio de «res.swell_factor» (1,22 → 1,23)"

SWELL = params.ParamDef(
    KEY, "float", "-", 1.15, 1.0, 2.0, ("RF-008-04",),
    "Prueba: K de esponjamiento sin ensayo", kind="HIPÓTESIS", source_kind="document",
)
RECOVERY = params.ParamDef(
    "res.recovery", "float", "-", 0.9, 0.0, 1.0, ("RF-008-03",), "Prueba: recuperación minera",
)
LIMITS = params.ParamDef(
    "res.bench_limits", "json", "m", (5.0, 15.0), 0.0, 50.0, ("RF-008-05",),
    "Prueba: alturas mínima y máxima de banco", length=2,
)
RAMPS = params.ParamDef(
    "res.use_ramps", "bool", "-", True, requirements=("RF-008-05",), source="Prueba: rampas",
)
METHOD = params.ParamDef(
    "res.method", "text", "-", "lerchs", requirements=("RF-008-05",),
    source="Prueba: algoritmo de la corta", choices=("lerchs", "pseudoflow"),
)
DEFINITIONS = (SWELL, RECOVERY, LIMITS, RAMPS, METHOD)

# El K de CE-008-03: (valor, motivo, fecha de la decisión) de cada paso en HIPÓTESIS, y su
# adopción por la propiedad.
K_STEPS: tuple[tuple[float, str, dt.datetime], ...] = (
    (1.15, "Sin ensayo: valor bibliográfico de calizas", dt.datetime(2026, 9, 1, 8, tzinfo=dt.UTC)),
    (1.05, "Primer ensayo de laboratorio", dt.datetime(2026, 9, 5, 10, tzinfo=dt.UTC)),
    (1.11, "Segundo ensayo de laboratorio", dt.datetime(2026, 9, 8, 11, tzinfo=dt.UTC)),
    (1.24, "Ensayo en campo tras la voladura 3", dt.datetime(2026, 9, 12, 9, tzinfo=dt.UTC)),
    (1.22, "Media de los ensayos de campo", dt.datetime(2026, 9, 16, 12, tzinfo=dt.UTC)),
    (1.23, "Media corregida con la voladura 5", dt.datetime(2026, 9, 20, 8, tzinfo=dt.UTC)),
)
ADOPTION: dict[str, Any] = {
    "kind": "ADOPTADO",
    "source": "Ensayo de esponjamiento de la propiedad (24/09/2026)",
    "source_kind": "document",
    "decided_by": "La propiedad",
    "decided_at": dt.datetime(2026, 9, 24, 9, 31, tzinfo=dt.UTC),
    "reason": "La propiedad adopta el K de su ensayo",
}
BY_HAND: dict[str, Any] = {
    "source": "Bibliografía de esponjamiento de calizas",
    "source_kind": "document",
    "decided_by": "Samuel (IMGA)",
}


def _sha(value: object, unit: str) -> str:
    """``value_sha256`` según el plan (D10): sha256 del JSON canónico de ``{value, unit}``."""
    return hashing.sha256_bytes(hashing.canonical_json({"unit": unit, "value": value}))


def _at(minutes: int) -> str:
    return timeutil.format_utc(CLOCK_START + dt.timedelta(minutes=minutes))


def _insert(conn: sqlite3.Connection, table: str, row: Mapping[str, Any]) -> None:
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(row.values()))


class StoreCase(unittest.TestCase):
    """Un proyecto nuevo por prueba (``self.project``) con las definiciones de prueba de
    ``res`` registradas, su ``ParameterStore`` y un reloj que avanza con :meth:`tick`."""

    def setUp(self) -> None:
        params.register_definitions(DEFINITIONS)
        self.addCleanup(params.unregister_definitions, "res")
        tmp = self.enterContext(project_tmp("gb-t13-"))
        parent = tmp / "proyectos"
        parent.mkdir()
        self.clock = FakeClock()
        self.project = create.create_project(
            parent, make_settings(), SESSION, userdata_mod.UserData(tmp / "u"), clock=self.clock
        ).project
        self.addCleanup(self.project.close)
        self.store = store_mod.ParameterStore(self.project)

    def tick(self) -> None:
        self.clock.advance(minutes=1)

    def write(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        with self.project.write_transaction() as conn:
            return work(conn)

    def snapshot(self) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
        with self.project.read() as conn:
            return (
                conn.execute("SELECT * FROM gb_parameter ORDER BY fid").fetchall(),
                conn.execute("SELECT * FROM gb_parameter_history ORDER BY fid").fetchall(),
            )

    def assertRejected(self, code: str, work: Callable[[sqlite3.Connection], Any]) -> Any:
        """``work`` se rechaza con ``code`` sin escribir nada y el proyecto sigue en
        escritura (un rechazo no es un fallo de la base)."""
        before = self.snapshot()
        with self.assertRaises(params.ParamError) as caught:
            self.write(work)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertTrue(self.project.writable)
        self.assertEqual(self.snapshot(), before)
        return caught.exception

    def create_k(self, value: float = 1.22, **changes: Any) -> Any:
        fields: dict[str, Any] = {"kind": "HIPÓTESIS", **BY_HAND, "reason": "Valor de partida"}
        fields.update(changes)
        return self.write(lambda conn: self.store.create(conn, KEY, value, **fields))


class RejectionTest(StoreCase):
    """RF-008-01 y RF-008-02 (spec §8): lo que no se guarda, con su texto."""

    def test_create_without_kind(self) -> None:
        """RF-008-01, CE-008-03: un parámetro sin tipo se rechaza con el texto de la spec
        §8, y uno con un tipo que no es de los cuatro, nombrándolo; no se escribe nada."""
        for kind in (None, "", "  "):
            with self.subTest(kind=kind):
                error = self.assertRejected(
                    "core.param_kind_missing",
                    lambda conn, kind=kind: self.store.create(
                        conn, KEY, 1.15, kind=kind, **BY_HAND, reason="Sin ensayo"
                    ),
                )
                self.assertEqual(str(error), SPEC_NO_KIND + ".")
        error = self.assertRejected(
            "core.param_kind_unknown",
            lambda conn: self.store.create(
                conn, KEY, 1.15, kind="ESTIMADO", **BY_HAND, reason="Sin ensayo"
            ),
        )
        self.assertIn("«ESTIMADO»", str(error))
        self.assertIsNone(self.store.get(KEY))
        self.assertEqual(self.store.history(KEY), [])

    def test_calculated_typed_by_hand(self) -> None:
        """RF-008-01 y S-1: un CALCULADO tecleado (sin la cifra de origen) se rechaza al
        crearlo y al cambiarlo, también solo el tipo, con el texto de la spec §8 tras la
        clave."""
        expected = f"{KEY}: {SPEC_CALCULATED[0].lower()}{SPEC_CALCULATED[1:]}."
        error = self.assertRejected(
            "core.param_calculated_by_hand",
            lambda conn: self.store.create(
                conn, KEY, 1.11, kind="CALCULADO", **BY_HAND, reason="Balance"
            ),
        )
        self.assertEqual(str(error), expected)
        self.create_k()
        for changes in ({"kind": "CALCULADO", "value": 1.11}, {"kind": "CALCULADO"}):
            with self.subTest(changes=changes):
                error = self.assertRejected(
                    "core.param_calculated_by_hand",
                    lambda conn, changes=changes: self.store.change(
                        conn, KEY, reason="Resultado del balance", **changes
                    ),
                )
                self.assertEqual(str(error), expected)

    def test_change_without_reason(self) -> None:
        """RF-008-02 (spec §8): un cambio sin motivo se rechaza con el valor anterior y el
        nuevo; uno solo de tipo, con los dos tipos; un alta sin motivo, con su valor."""
        self.create_k(1.22)
        for reason in (None, "", "   "):
            with self.subTest(reason=reason):
                error = self.assertRejected(
                    "core.param_reason_missing",
                    lambda conn, reason=reason: self.store.change(
                        conn, KEY, value=1.23, reason=reason
                    ),
                )
                self.assertEqual(str(error), SPEC_NO_REASON + ".")
        error = self.assertRejected(
            "core.param_reason_missing",
            lambda conn: self.store.change(conn, KEY, kind="ADOPTADO", decided_by="La propiedad"),
        )
        self.assertEqual(
            str(error),
            "Indique el motivo del cambio de «res.swell_factor» (HIPÓTESIS → ADOPTADO, "
            "«Samuel (IMGA)» → «La propiedad»).",
        )
        error = self.assertRejected(
            "core.param_reason_missing_new",
            lambda conn: self.store.create(
                conn, "res.recovery", 0.85, kind="ADOPTADO", **BY_HAND, reason=" "
            ),
        )
        self.assertEqual(str(error), "Indique el motivo del valor de «res.recovery» (0,85).")

    def test_other_rejections(self) -> None:
        """RF-008-01: sin origen, con una clase de origen desconocida o sin decisor no se
        da de alta; un parámetro no se da de alta dos veces, ni sin una definición
        registrada que compruebe su valor; no se cambia ni se confirma uno que no está, ni
        se cambia sin cambiar nada; los valores que no valen (RF-008-03), con los códigos de
        ``ParamDef``."""
        cases: tuple[tuple[str, dict[str, Any]], ...] = (
            ("core.param_source_missing", {"source": "  "}),
            ("core.param_source_kind_unknown", {"source_kind": "rumor"}),
            ("core.param_decided_by_missing", {"decided_by": None}),
        )
        for code, changes in cases:
            with self.subTest(code=code):
                self.assertRejected(
                    code,
                    lambda conn, changes=changes: self.store.create(
                        conn, KEY, 1.15, kind="HIPÓTESIS",
                        **{**BY_HAND, **changes}, reason="Sin ensayo",
                    ),
                )
        self.assertRejected(
            "core.param_undefined",
            lambda conn: self.store.create(
                conn, "res.undeclared", 1.0, kind="ADOPTADO", **BY_HAND, reason="Prueba"
            ),
        )
        self.assertRejected(
            "core.param_not_registered",
            lambda conn: self.store.change(conn, KEY, value=1.3, reason="Ensayo"),
        )
        self.assertRejected(
            "core.param_not_registered", lambda conn: self.store.confirm(conn, KEY)
        )
        self.create_k(1.22)
        self.assertRejected("core.param_exists", lambda conn: self.store.create(
            conn, KEY, 1.3, kind="HIPÓTESIS", **BY_HAND, reason="Otra vez"
        ))
        self.assertRejected("core.param_unchanged", lambda conn: self.store.change(
            conn, KEY, value=1.22, kind="HIPÓTESIS", reason="Lo mismo"
        ))
        values = (
            ("core.param_out_of_range", {"value": 3.5}),
            ("core.param_not_number", {"value": float("nan")}),
            ("core.param_not_finite", {"value": float("inf"), "unit": "%"}),
            ("core.param_missing", {"value": None}),
            ("core.param_unit_not_convertible", {"value": 1.3, "unit": "m"}),
            ("core.param_unit_unknown", {"value": 1.3, "unit": "furlong"}),
        )
        for code, changes in values:
            with self.subTest(code=code):
                self.assertRejected(
                    code,
                    lambda conn, changes=changes: self.store.change(
                        conn, KEY, reason="Ensayo", **changes
                    ),
                )

    def test_unit_is_converted_to_the_declared_one(self) -> None:
        """RF-008-03 al guardar: 35 % en un parámetro declarado en fracción se guarda (y
        consta en el historial) como 0,35 en la unidad declarada."""
        record = self.write(lambda conn: self.store.create(
            conn, "res.recovery", 35, "%", kind="ADOPTADO", **BY_HAND, reason="Plan de labores"
        ))
        self.assertEqual((record.value, record.unit), (0.35, "-"))
        self.assertEqual(record.value_sha256, _sha(0.35, "-"))
        (entry,) = self.store.history("res.recovery")
        self.assertEqual((entry.value, entry.unit), (0.35, "-"))


class HistoryTest(StoreCase):
    """RF-008-02 y CE-008-03: el historial de solo inserción."""

    def test_k_keeps_seven_entries(self) -> None:
        """CE-008-03, RF-008-02: un K que pasa por 1,15 → 1,05 → 1,11 → 1,24 → 1,22 → 1,23
        y a ADOPTADO tiene siete filas con su tipo, la fecha de la decisión, quién, cuándo y
        el motivo; las seis primeras siguen diciendo HIPÓTESIS y no cambian; el cambio solo
        de tipo no cambia ``value_sha256`` (plan D10)."""
        (first, first_reason, first_at), *rest = K_STEPS
        self.write(lambda conn: self.store.create(
            conn, KEY, first, kind="HIPÓTESIS", **BY_HAND, decided_at=first_at,
            reason=first_reason,
        ))
        for value, reason, decided_at in rest:
            self.tick()
            record = self.write(lambda conn, v=value, r=reason, d=decided_at: self.store.change(
                conn, KEY, value=v, decided_at=d, reason=r
            ))
            self.assertEqual(record.value, value)
        rows_before = self.snapshot()[1]
        entries_before = self.store.history(KEY)
        self.tick()
        record = self.write(lambda conn: self.store.change(conn, KEY, **ADOPTION))

        entries = self.store.history(KEY)
        self.assertEqual(len(entries), 7)
        self.assertEqual(entries[:6], entries_before)
        self.assertEqual(self.snapshot()[1][:6], rows_before)
        self.assertEqual([entry.rev for entry in entries], list(range(1, 8)))
        self.assertEqual([entry.action for entry in entries], ["create"] + ["change"] * 6)
        self.assertEqual(
            [entry.value for entry in entries], [1.15, 1.05, 1.11, 1.24, 1.22, 1.23, 1.23]
        )
        self.assertEqual([entry.kind for entry in entries], ["HIPÓTESIS"] * 6 + ["ADOPTADO"])
        self.assertEqual(
            [entry.reason for entry in entries],
            [step[1] for step in K_STEPS] + [ADOPTION["reason"]],
        )
        self.assertEqual(
            [entry.decided_at for entry in entries],
            [timeutil.format_utc(step[2]) for step in K_STEPS]
            + [timeutil.format_utc(ADOPTION["decided_at"])],
        )
        self.assertEqual(
            [entry.decided_by for entry in entries], ["Samuel (IMGA)"] * 6 + ["La propiedad"]
        )
        self.assertEqual([entry.changed_at for entry in entries], [_at(i) for i in range(7)])
        self.assertEqual({entry.changed_by for entry in entries}, {USER_HOST})
        self.assertEqual({entry.session_uid for entry in entries}, {SESSION.session_uid})
        self.assertEqual({entry.unconfirmed for entry in entries}, {False})
        self.assertEqual({entry.operation_uid for entry in entries}, {None})
        self.assertEqual({entry.unit for entry in entries}, {"-"})

        hashes = [entry.value_sha256 for entry in entries]
        self.assertEqual(hashes, [_sha(entry.value, "-") for entry in entries])
        self.assertEqual(len(set(hashes[:6])), 6)
        self.assertEqual(hashes[6], hashes[5])
        self.assertEqual(record.value_sha256, hashes[5])
        self.assertEqual((record.kind, record.value, record.rev), ("ADOPTADO", 1.23, 7))
        self.assertEqual((record.decided_by, record.source), ("La propiedad", ADOPTION["source"]))
        self.assertEqual(record.reason, ADOPTION["reason"])
        self.assertEqual(record.modified_at, _at(6))
        self.assertEqual(record.created_at, _at(0))
        self.assertFalse(record.unconfirmed)
        self.assertEqual(self.store.get(KEY), record)


class DefaultTest(StoreCase):
    """RF-008-04: el valor por defecto de su módulo, «sin confirmar»."""

    def test_ensure_default_registers_it_unconfirmed(self) -> None:
        """RF-008-04: con el valor y el tipo por defecto de la definición (HIPÓTESIS para un
        K sin dato), origen «valor por defecto de Geoblender <versión>», decisor «Geoblender
        (valor por defecto)» y «sin confirmar»; una segunda llamada no añade nada."""
        record = self.write(
            lambda conn: self.store.ensure_default(conn, KEY, geoblender_version="0.3.0")
        )
        self.assertEqual(
            (record.key, record.scope, record.scope_uid, record.module, record.value_type),
            (KEY, "project", "", "res", "float"),
        )
        self.assertEqual((record.value, record.unit, record.kind), (1.15, "-", "HIPÓTESIS"))
        self.assertTrue(record.unconfirmed)
        self.assertEqual(record.source, "valor por defecto de Geoblender 0.3.0")
        self.assertEqual(record.source_kind, "document")
        self.assertEqual(record.decided_by, DEFAULT_DECIDER)
        self.assertEqual(record.decided_at, _at(0))
        self.assertEqual(record.rev, 1)
        self.assertIsNone(record.operation_uid)
        self.assertIsNone(record.review)
        self.assertEqual(record.value_sha256, _sha(1.15, "-"))
        self.assertEqual(record.def_sha256, store_mod.definition_sha256(SWELL))
        (entry,) = self.store.history(KEY)
        self.assertEqual(entry.action, "default")
        self.assertEqual((entry.value, entry.kind, entry.rev), (1.15, "HIPÓTESIS", 1))
        self.assertTrue(entry.unconfirmed)
        self.assertEqual(entry.changed_by, DEFAULT_DECIDER)
        self.assertEqual(entry.decided_by, DEFAULT_DECIDER)
        self.assertEqual(entry.source, "valor por defecto de Geoblender 0.3.0")
        self.assertTrue(entry.reason)

        self.tick()
        again = self.write(
            lambda conn: self.store.ensure_default(conn, KEY, geoblender_version="0.4.0")
        )
        self.assertEqual(again, record)
        self.assertEqual(len(self.store.history(KEY)), 1)

    def test_technical_default_is_adopted(self) -> None:
        """RF-008-04: un parámetro técnico (``core.original_copy_limit``) entra ADOPTADO,
        con su unidad y su clase de origen, también «sin confirmar»; uno que ningún módulo
        registrado declara no se inventa."""
        if "core.original_copy_limit" not in params.DEFINITIONS:
            params.register_definitions(core_defs.DEFINITIONS)
            self.addCleanup(params.unregister_definitions, "core")
        record = self.write(lambda conn: self.store.ensure_default(
            conn, "core.original_copy_limit", geoblender_version="0.3.0"
        ))
        self.assertEqual((record.value, record.unit, record.kind), (200.0, "MB", "ADOPTADO"))
        self.assertEqual((record.source_kind, record.module), ("algorithm", "core"))
        self.assertTrue(record.unconfirmed)
        self.assertRejected("core.param_undefined", lambda conn: self.store.ensure_default(
            conn, "res.undeclared", geoblender_version="0.3.0"
        ))

    def test_confirm_without_reason(self) -> None:
        """RF-008-02 y RF-008-04: confirmar no pide motivo, quita «sin confirmar» y añade
        una fila (quién confirma: una persona) con el mismo valor, tipo y decisor; la fila
        del valor por defecto sigue «sin confirmar»; confirmar otra vez no tiene nada que
        confirmar."""
        self.write(lambda conn: self.store.ensure_default(conn, KEY, geoblender_version="0.3.0"))
        self.tick()
        record = self.write(lambda conn: self.store.confirm(conn, KEY))
        self.assertFalse(record.unconfirmed)
        self.assertEqual((record.value, record.kind, record.rev), (1.15, "HIPÓTESIS", 2))
        self.assertEqual(record.decided_by, DEFAULT_DECIDER)
        self.assertEqual(record.value_sha256, _sha(1.15, "-"))
        first, second = self.store.history(KEY)
        self.assertTrue(first.unconfirmed)
        self.assertEqual(second.action, "confirm")
        self.assertIsNone(second.reason)
        self.assertFalse(second.unconfirmed)
        self.assertEqual((second.value, second.kind, second.rev), (1.15, "HIPÓTESIS", 2))
        self.assertEqual((second.changed_by, second.changed_at), (USER_HOST, _at(1)))
        self.assertEqual(second.value_sha256, first.value_sha256)
        self.assertRejected("core.param_nothing_to_confirm", lambda conn: self.store.confirm(
            conn, KEY
        ))

    def test_changing_a_default_value_confirms_it(self) -> None:
        """RF-008-02 y RF-008-04: cambiar el valor de un «sin confirmar» le quita la marca;
        la persona que lo cambia da su origen y su decisor (no se quedan los del valor por
        defecto)."""
        self.write(lambda conn: self.store.ensure_default(conn, KEY, geoblender_version="0.3.0"))
        self.assertRejected("core.param_source_missing", lambda conn: self.store.change(
            conn, KEY, value=1.2, decided_by="Samuel (IMGA)", reason="Ensayo"
        ))
        self.assertRejected("core.param_decided_by_missing", lambda conn: self.store.change(
            conn, KEY, value=1.2, source="Ensayo de laboratorio", reason="Ensayo"
        ))
        self.tick()
        record = self.write(lambda conn: self.store.change(
            conn, KEY, value=1.2, **BY_HAND, reason="Ensayo de laboratorio"
        ))
        self.assertFalse(record.unconfirmed)
        first, second = self.store.history(KEY)
        self.assertEqual((first.unconfirmed, second.unconfirmed), (True, False))
        self.assertEqual((second.value, second.changed_by), (1.2, USER_HOST))


class AdoptFigureTest(StoreCase):
    """Decisión S-1 de Samuel y RF-008-01: solo una persona adopta como CALCULADO el valor
    de una cifra, con la operación que la calculó."""

    def setUp(self) -> None:
        super().setUp()
        self.create_k(1.23, kind="ADOPTADO", decided_by="La propiedad")
        self.record = self.store.get(KEY)

        def add(conn: sqlite3.Connection) -> None:
            _insert(conn, "gb_operation", operation_row(op_type="res.balance", module="res"))
            _insert(conn, "gb_figure", figure_row(
                key="res.balance_k", label="K del balance", value=1.11, unit="-",
                parameter_uid=self.record.uid, parameter_rev=self.record.rev,
            ))
            _insert(conn, "gb_figure", figure_row(uid=OTHER_FIGURE_UID))

        self.write(add)

    def test_a_person_adopts_the_figure(self) -> None:
        """S-1: con la cifra de origen, el parámetro pasa a CALCULADO con su valor (1,11) y
        la operación que la calculó; la fila del historial la escribe la persona de la
        sesión; volver a ADOPTADO a mano quita la operación."""
        self.tick()
        record = self.write(lambda conn: self.store.change(
            conn, KEY, from_figure=FIGURE_UID, decided_by="Samuel (IMGA)",
            reason="Se adopta el K del balance",
        ))
        self.assertEqual((record.kind, record.value, record.unit), ("CALCULADO", 1.11, "-"))
        self.assertEqual(record.operation_uid, OP_UID)
        self.assertEqual(record.source, "cifra «res.balance_k» de la operación «res.balance»")
        self.assertEqual(record.source_kind, "operation")
        entry = self.store.history(KEY)[-1]
        self.assertEqual((entry.action, entry.kind, entry.value), ("change", "CALCULADO", 1.11))
        self.assertEqual((entry.operation_uid, entry.changed_by), (OP_UID, USER_HOST))
        self.assertEqual(entry.decided_by, "Samuel (IMGA)")

        self.assertRejected("core.param_calculated_by_hand", lambda conn: self.store.change(
            conn, KEY, value=1.2, reason="Otro K"
        ))
        self.tick()
        record = self.write(lambda conn: self.store.change(conn, KEY, value=1.23, **ADOPTION))
        self.assertEqual((record.kind, record.operation_uid), ("ADOPTADO", None))
        self.assertIsNone(self.store.history(KEY)[-1].operation_uid)

    def test_figure_rejections(self) -> None:
        """S-1: no se adopta una cifra que no está, ni la de otro parámetro, ni sin motivo;
        con la cifra no se teclea el valor ni otro tipo."""
        self.assertRejected("core.param_figure_unknown", lambda conn: self.store.change(
            conn, KEY, from_figure=UNKNOWN_UID, decided_by="Samuel (IMGA)", reason="K"
        ))
        self.assertRejected("core.param_figure_other", lambda conn: self.store.change(
            conn, KEY, from_figure=OTHER_FIGURE_UID, decided_by="Samuel (IMGA)", reason="K"
        ))
        self.assertRejected("core.param_reason_missing", lambda conn: self.store.change(
            conn, KEY, from_figure=FIGURE_UID, decided_by="Samuel (IMGA)"
        ))
        for changes in ({"value": 1.2}, {"kind": "ADOPTADO"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.write(lambda conn, changes=changes: self.store.change(
                    conn, KEY, from_figure=FIGURE_UID, decided_by="Samuel (IMGA)", reason="K",
                    **changes,
                ))
        self.assertEqual(self.store.get(KEY), self.record)


class ResolveTest(StoreCase):
    """RF-008-05: lo que una operación anota del parámetro que lee."""

    def test_resolve_gives_what_the_operation_records(self) -> None:
        """RF-008-05: clave, valor, unidad, tipo, ámbito (el proyecto) y la revisión del
        historial, con la marca y ``value_sha256``; también con una conexión de lectura."""
        self.create_k(1.22)
        self.tick()
        self.write(lambda conn: self.store.change(conn, KEY, value=1.23, reason="Ensayo"))
        record = self.store.get(KEY)
        with self.project.read() as conn:
            resolved = self.store.resolve(conn, KEY)
        self.assertEqual(resolved, store_mod.ResolvedParam(
            parameter_uid=record.uid, key=KEY, scope="project", scope_uid="", rev=2,
            value=1.23, value_json="1.23", unit="-", kind="HIPÓTESIS", unconfirmed=False,
            value_sha256=_sha(1.23, "-"),
        ))
        self.assertEqual(self.write(lambda conn: self.store.resolve(conn, KEY)), resolved)

    def test_resolve_other_value_types(self) -> None:
        """RF-008-05: una lista, un sí/no y un texto vuelven con su tipo (la lista, como
        tupla) y su JSON canónico."""
        expected = {
            "res.bench_limits": ((5.0, 15.0), "[5.0,15.0]", "m"),
            "res.use_ramps": (True, "true", "-"),
            "res.method": ("lerchs", '"lerchs"', "-"),
        }
        for key in expected:
            self.write(lambda conn, key=key: self.store.ensure_default(
                conn, key, geoblender_version="0.3.0"
            ))
        with self.project.read() as conn:
            for key, (value, text, unit) in expected.items():
                with self.subTest(key=key):
                    resolved = self.store.resolve(conn, key)
                    self.assertEqual(resolved.value, value)
                    self.assertIs(type(resolved.value), type(value))
                    self.assertEqual((resolved.value_json, resolved.unit), (text, unit))
                    self.assertEqual(resolved.kind, "ADOPTADO")
                    self.assertTrue(resolved.unconfirmed)
                    self.assertEqual(resolved.value_sha256, _sha(value, unit))

    def test_resolve_rejections(self) -> None:
        """RF-008-05: un parámetro que el proyecto no tiene no se resuelve (antes,
        ``ensure_default``); en esta spec solo hay ámbito de proyecto (la versión, con la
        009)."""
        with self.project.read() as conn:
            with self.assertRaises(params.ParamError) as caught:
                self.store.resolve(conn, KEY)
            self.assertEqual(caught.exception.code, "core.param_not_registered")
            for chain in ((), ("version",), ("project", "sector")):
                with self.subTest(chain=chain), self.assertRaises(ValueError):
                    self.store.resolve(conn, KEY, scope_chain=chain)


if __name__ == "__main__":
    unittest.main()
