# SPDX-License-Identifier: GPL-3.0-or-later
"""Las filas de una tabla, codificadas por columnas (spec 005, T52; RNF-005-01; spec 008,
RF-008-08; ADR-0024 §2, §4 y §6).

``core.content.RowEncoder`` hashea cada fila con el JSON canónico de sus valores convertidos al
tipo de su columna. Con lotes grandes (las 500.000 filas de los análisis de V-ref) lo hace por
columnas (``update`` con filas en listas o tuplas, y ``update_columns`` con las columnas): el
texto de cada valor de una columna de un tipo exacto (``float``, ``int``, ``str``, ``bool`` o
nulo) sin pasar por ``canonical_json`` valor a valor, y lo demás valor a valor como antes. El
hash es el mismo, bit a bit: estas pruebas lo comparan con el que daba el código de partida de
la T52 (anotado aquí) con todos los tipos de campo (textos con comillas, barras, caracteres de
control y emojis; reales con −0,0, NaN, infinitos, subnormales, float32 y enteros; enteros
grandes y de numpy; sí/no; fechas y fechas y horas en objeto y en texto; binarios; nulos), en
orden y sin él, de una vez, por lotes y fila a fila. Un lote con un valor que no vale da el
mismo error que fila a fila y deja el codificador como estaba.
"""

from __future__ import annotations

import datetime as dt
import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

content = import_geoblender("core.content")
encoder = import_geoblender("core.content.encoder")


class _Text(str):
    """Un texto que no es exactamente ``str`` (como una enumeración)."""


COLUMNS = [["t", "text"], ["f", "float"], ["i", "int"], ["b", "bool"], ["d", "date"],
           ["dt", "datetime"], ["x", "blob"]]
EXACT = [["hole", "text"], ["z", "float"], ["n", "int"], ["ok", "bool"]]
ROWS = 23
TZ = dt.timezone(dt.timedelta(hours=2))
CHOICES = {
    "text": ("S-01", "", 'a"b\\c', "\x00\x1f\n\t", "🙂 𝄞", "Ñandú «á»", _Text("sub"), "1,5",
             None),
    "float": (0.1, -0.0, math.nan, math.inf, -math.inf, 5e-324, 1e308, 3, np.float32(0.1),
              np.float64(2.5), None, 12.0, np.int32(4), -3.5e15, 4_400_020.25),
    "int": (1, -(2**70), 0, np.int64(5), 3.0, None, 2**63 - 1),
    "bool": (True, False, 0, 1, np.bool_(True), None),
    "date": ("2026-10-14", dt.date(2024, 2, 29), None),
    "datetime": (dt.datetime(2026, 10, 8, 10, 0, tzinfo=dt.UTC), "2026-10-08T10:00:00+02:00",
                 dt.datetime(2025, 1, 2, 3, 4, 5, 678_901, tzinfo=TZ), None),
    "blob": (b"\x00\x01", bytearray(b"abc"), memoryview(b"xyz"), b"", None),
}
EXACT_CHOICES = {
    "text": ("S-01", "", 'a"b\\c', "\x00\x1f\n", "🙂", None),
    "float": (0.1, -0.0, math.nan, math.inf, -math.inf, 612.5, None, 1e-300),
    "int": (1, -(2**63), 0, 2**63 - 1, None, 42),
    "bool": (True, False, None),
}


def rows_of(columns: list[list[str]], choices: dict[str, tuple[object, ...]],
            count: int = ROWS) -> list[list[object]]:
    """``count`` filas con todos los valores de cada tipo: la fila k toma, en la columna j,
    el valor (5·k + j) módulo su número."""
    return [[choices[kind][(5 * k + j) % len(choices[kind])]
             for j, (_name, kind) in enumerate(columns)] for k in range(count)]


def data_sha256(columns: list[list[str]], rows: list[list[object]], ordered: bool) -> str:
    """El hash de datos de la tabla con ``rows`` de una vez (``ContentHasher.rows``)."""
    hasher = content.ContentHasher("table", declarations={}, reader="test.table@1")
    return hasher.rows(columns, ordered, rows).digest().data_sha256


def before_cases() -> dict[str, str]:
    """El hash de datos de cada caso, por su nombre."""
    found = {}
    for name, columns, choices in (("todos", COLUMNS, CHOICES), ("exactos", EXACT,
                                                                   EXACT_CHOICES)):
        rows = rows_of(columns, choices)
        for ordered in (False, True):
            found[f"{name} {'en orden' if ordered else 'sin orden'}"] = data_sha256(
                columns, rows, ordered)
    return found


# --- Los hashes del código de partida de la T52 (commit acb34cd) -----------------------------

BEFORE: dict[str, str] = {
    "todos sin orden": "c8b4ed7ec87835feea444c09a7f165d37314c4f663b9d160ac63f9cd6d42b168",
    "todos en orden": "1d781dd1f2678785ae92d627704a71781438582a3b2ef3ca96c5f8e5387da033",
    "exactos sin orden": "414ec8f93695729d9dea5d206517d1ff663b7032ed7167abedf8d7307d9d5e6e",
    "exactos en orden": "a60039741c572751349f7a451a36cdc0b7fabfc761b2fb617c4acd9ad0b4b9f4",
}


class ColumnsTest(unittest.TestCase):
    """RNF-005-01, RF-008-08 (ADR-0024 §6): el mismo hash por columnas que fila a fila."""

    def test_same_hashes_as_before(self) -> None:
        """RF-008-08: todos los tipos de campo, en orden y sin él, los hashes de antes."""
        self.assertEqual(before_cases(), BEFORE)

    def test_batches_columns_and_rows_give_the_same_hash(self) -> None:
        """RNF-005-01, RF-008-08: de una vez, por lotes de 5, fila a fila, por columnas y con
        filas en diccionarios, el mismo hash."""
        for name, columns, choices in (("todos", COLUMNS, CHOICES), ("exactos", EXACT,
                                                                       EXACT_CHOICES)):
            rows = rows_of(columns, choices)
            for ordered in (False, True):
                key = f"{name} {'en orden' if ordered else 'sin orden'}"
                with self.subTest(key):
                    by_rows = encoder.RowEncoder(columns, ordered)
                    for row in rows:
                        by_rows.add(row)
                    in_batches = encoder.RowEncoder(columns, ordered)
                    for first in range(0, len(rows), 5):
                        in_batches.update(rows[first:first + 5])
                    by_columns = encoder.RowEncoder(columns, ordered)
                    by_columns.update_columns([list(column) for column in zip(*rows)])
                    as_dicts = encoder.RowEncoder(columns, ordered)
                    as_dicts.update([dict(zip([n for n, _ in columns], row, strict=True))
                                     for row in rows])
                    expected = BEFORE[key]
                    for feed in (by_rows, in_batches, by_columns, as_dicts):
                        self.assertEqual(feed.count, ROWS)
                        self.assertEqual(feed.finish(), expected)

    def test_many_rows_by_columns(self) -> None:
        """RNF-005-01: 20.000 filas de tipos exactos por columnas, como las da una tabla de la
        base: el hash de las mismas filas una a una con ``canonical_json``."""
        rows = rows_of(EXACT, EXACT_CHOICES, 20_000)
        feed = encoder.RowEncoder(EXACT, False)
        feed.update_columns([tuple(column) for column in zip(*rows)])
        reference = encoder.RowEncoder(EXACT, False)
        for row in rows:
            reference.add(dict(zip([n for n, _ in EXACT], row, strict=True)))
        self.assertEqual(feed.finish(), reference.finish())

    def test_a_bad_value_fails_as_row_by_row(self) -> None:
        """RF-008-08: un lote (por filas o por columnas) con un valor que no vale da el error
        de la primera fila que no vale, el mismo que fila a fila, y no añade nada."""
        good = rows_of(COLUMNS, CHOICES, 6)
        cases = {
            "texto en un real": (1, "1,5"),
            "1,5 en un entero": (2, 1.5),
            "2 en un sí/no": (3, 2),
            "fecha que no existe": (4, "2024-02-30"),
            "fecha y hora sin zona": (5, dt.datetime(2026, 10, 8, 10)),
            "sustituto suelto": (0, "a\ud800b"),
            "booleano en un real": (1, True),
            "texto en un binario": (6, "AAE="),
        }
        for name, (column, value) in cases.items():
            with self.subTest(name):
                rows = [list(row) for row in good]
                rows[3][column] = value
                rows[5][column] = value
                reference = encoder.RowEncoder(COLUMNS, False)
                with self.assertRaises(Exception) as expected:
                    for row in rows:
                        reference._item(row)
                for feed_rows in (True, False):
                    feed = encoder.RowEncoder(COLUMNS, False)
                    feed.update(good[:2])
                    with self.assertRaises(type(expected.exception)) as raised:
                        if feed_rows:
                            feed.update(rows)
                        else:
                            feed.update_columns([list(column) for column in zip(*rows)])
                    self.assertEqual(str(raised.exception), str(expected.exception))
                    self.assertEqual(feed.count, 2)
                    feed.update(good[2:])
                    self.assertEqual(feed.finish(), data_sha256(COLUMNS, good, False))

    def test_columns_that_do_not_fit(self) -> None:
        """RF-008-08: ``update_columns`` con otro número de columnas que la tabla, columnas de
        distinto largo o un texto en lugar de una columna: ``ValueError`` o ``TypeError``, sin
        añadir nada; sin filas, nada."""
        feed = encoder.RowEncoder(EXACT, True)
        cases = (
            ([["S-01"], [1.0], [1]], ValueError),
            ([["S-01"], [1.0], [1], [True, False]], ValueError),
            ([["S-01"], [1.0], [1], "x"], TypeError),
            ("abcd", TypeError),
        )
        for columns, error in cases:
            with self.subTest(columns=columns), self.assertRaises(error):
                feed.update_columns(columns)
        feed.update_columns([[], [], [], []])
        self.assertEqual(feed.count, 0)
        self.assertEqual(feed.finish(), data_sha256(EXACT, [], True))


if __name__ == "__main__":
    unittest.main()
