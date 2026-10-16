# SPDX-License-Identifier: GPL-3.0-or-later
"""Valores de las fuentes de sondeos: vía rápida vectorizada, analizador de especiales y
precisión simple (spec 005, T05; HU-005-1; plan 005 §5.3.2 y §5.4).

- **RF-005-09**: un valor vacío o un centinela declarado (−99, «ND») es ausente; «<x» es x con
  la marca «bajo el límite de detección» y «>x», x con «sobre el límite superior»; un negativo
  se guarda tal cual, salvo que se declare «−x = <x»; lo que no es un número se rechaza con su
  fila y su motivo. El texto original se conserva siempre. Coma y punto decimal: el que no es
  el declarado se rechaza (spec §8, «coma decimal mezclada con punto»).
- **RF-005-02**: los números de un CSV o un XLSX son, bit a bit, los de su decimal en doble
  precisión (``float(texto)``, un solo redondeo); los Single de RecMin, su decimal más corto
  (``float32(0.1)`` → 0,1 y no 0,10000000149011612).
"""

from __future__ import annotations

import json
import math
import random
import unittest
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

values = import_geoblender("drillholes.values")
model = import_geoblender("drillholes.model")
csv_tables = import_geoblender("interop.csv_tables")

DATA = ROOT / "tests" / "data" / "dh"
BASICO = DATA / "csv_basico"
CONVENIOS = DATA / "csv_convenios"
ERRORES = DATA / "csv_errores"

Flag = model.DetectionFlag
OK, BELOW, ABOVE = Flag.OK, Flag.BELOW_DL, Flag.ABOVE_UL
COMMA = model.ValueRules(",")
POINT = model.ValueRules(".")
NAN = math.nan
NOT_NUMBER = "number"  # el motivo de un rechazo: «no es un número»
MARK = "mark"  # el motivo de un rechazo: el separador decimal no es el declarado


def _bits(array: np.ndarray) -> list[int]:
    """Los bits de cada float64 (distingue −0,0 de 0,0); un NaN, el mismo NaN."""
    found = np.array(array, dtype=np.float64)
    found[np.isnan(found)] = math.nan
    return found.view(np.int64).tolist()


def _flags(parsed) -> list:
    """Las marcas de una columna leída, como ``DetectionFlag``."""
    return [values.FLAGS[code] for code in parsed.flags.tolist()]


def _read(path, separator: str):
    return csv_tables.read_table(path, encoding="utf-8", separator=separator)


def _column(table, name: str) -> list[str]:
    index = table.columns.index(name)
    return [row[index] for row in table.rows]


class SpecialValuesTest(unittest.TestCase):
    """RF-005-09: cada clase de valor da su valor, su marca, su texto y su rechazo."""

    def _check(self, rules, cases) -> None:
        """Cada caso (texto, valor esperado, marca, motivo del rechazo o None), solo y en una
        columna con todos los demás: la columna da lo mismo que cada texto suelto."""
        texts = [case[0] for case in cases]
        kept = list(texts)
        column = values.parse_column(texts, rules)
        self.assertEqual(texts, kept)  # la entrada no cambia
        self.assertEqual(column.values.dtype, np.float64)
        self.assertEqual(column.flags.dtype, np.int8)
        self.assertEqual(column.reported.dtype, object)
        self.assertEqual(column.rejected_rows.dtype, np.int64)
        self.assertEqual(len(column), len(cases))
        rejected = dict(zip(column.rejected_rows.tolist(), column.rejected_reasons, strict=True))
        for row, (text, value, flag, reason) in enumerate(cases):
            with self.subTest(texto=text, decimal=rules.decimal_mark):
                alone = values.parse_column([text], rules)
                for parsed, index in ((column, row), (alone, 0)):
                    self.assertEqual(_bits(parsed.values[index:index + 1]), _bits([value]))
                    self.assertIs(_flags(parsed)[index], flag)
                    original = text if text and text.strip() else None
                    self.assertEqual(parsed.reported[index], original)
                if reason is None:
                    self.assertNotIn(row, rejected)
                    self.assertEqual(alone.rejected_rows.tolist(), [])
                else:
                    self.assertEqual(alone.rejected_rows.tolist(), [0])
                    self.assertEqual(alone.rejected_reasons, (rejected[row],))
                    if reason == MARK:
                        self.assertIn("separador decimal", rejected[row])
                    else:
                        self.assertIn("no es un número", rejected[row])

    def test_comma_with_sentinels(self) -> None:
        """RF-005-09: con coma decimal y los centinelas «−99» y «ND», sin «−x = <x»: vacío y
        centinela (también «nd» y «−99,0», el mismo número), ausentes; «<0,01» y «>500», el
        número con su marca; −0,5, tal cual; «abc», «ND» sin declarar y el punto decimal,
        rechazados. Se admiten el signo, la coma al principio o al final, espacios de miles
        y el signo menos tipográfico; «−0» es 0 (sin −0,0). «nan», «inf», «1_000» o un
        número que no cabe en float64 no son números."""
        rules = model.ValueRules(",", frozenset({"-99", "ND"}))
        self._check(rules, [
            ("", NAN, OK, None),
            ("   ", NAN, OK, None),
            ("-99", NAN, OK, None),
            (" -99,0 ", NAN, OK, None),
            ("−99", NAN, OK, None),
            ("ND", NAN, OK, None),
            ("nd", NAN, OK, None),
            ("<0,01", 0.01, BELOW, None),
            ("< 0,01", 0.01, BELOW, None),
            (">500", 500.0, ABOVE, None),
            (">10,00", 10.0, ABOVE, None),
            ("-0,5", -0.5, OK, None),
            ("−0,5", -0.5, OK, None),
            ("0", 0.0, OK, None),
            ("-0", 0.0, OK, None),
            ("+5", 5.0, OK, None),
            (",5", 0.5, OK, None),
            ("5,", 5.0, OK, None),
            ("4,86", 4.86, OK, None),
            (" 2,9 ", 2.9, OK, None),
            ("1 234,5", 1234.5, OK, None),
            ("4 400 040,456", 4400040.456, OK, None),
            ("1,5E-03", 0.0015, OK, None),
            ("abc", NAN, OK, NOT_NUMBER),
            ("N/D", NAN, OK, NOT_NUMBER),
            ("0.5", NAN, OK, MARK),
            ("1.234,5", NAN, OK, MARK),
            ("<", NAN, OK, NOT_NUMBER),
            ("<abc", NAN, OK, NOT_NUMBER),
            ("<<5", NAN, OK, NOT_NUMBER),
            ("--5", NAN, OK, NOT_NUMBER),
            ("5-", NAN, OK, NOT_NUMBER),
            (",", NAN, OK, NOT_NUMBER),
            ("1,2,3", NAN, OK, NOT_NUMBER),
            ("nan", NAN, OK, NOT_NUMBER),
            ("inf", NAN, OK, NOT_NUMBER),
            ("1_000", NAN, OK, NOT_NUMBER),
            ("0x10", NAN, OK, NOT_NUMBER),
            ("1e999", NAN, OK, NOT_NUMBER),
            ("9" * 400, NAN, OK, NOT_NUMBER),
        ])

    def test_negative_is_below_detection_limit(self) -> None:
        """RF-005-09: con «−x = <x» declarado, −0,5 es 0,5 bajo el límite de detección; el
        centinela sigue siendo ausente (se mira antes); 0 y «<x» no cambian."""
        rules = model.ValueRules(",", frozenset({"-99"}), negative_is_below_dl=True)
        self._check(rules, [
            ("-0,5", 0.5, BELOW, None),
            ("−0,5", 0.5, BELOW, None),
            ("-5", 5.0, BELOW, None),
            ("-1,5E-03", 0.0015, BELOW, None),
            ("-99", NAN, OK, None),
            ("-99,00", NAN, OK, None),
            ("0", 0.0, OK, None),
            ("-0", 0.0, OK, None),
            ("0,5", 0.5, OK, None),
            ("<0,01", 0.01, BELOW, None),
            (">500", 500.0, ABOVE, None),
            ("", NAN, OK, None),
            ("abc", NAN, OK, NOT_NUMBER),
        ])

    def test_point(self) -> None:
        """RF-005-09: con punto decimal, la coma es la que se rechaza; sin centinelas, «ND» y
        «-99» no son ausentes («-99» es un número)."""
        self._check(POINT, [
            ("0.5", 0.5, OK, None),
            ("<0.5", 0.5, BELOW, None),
            ("<10", 10.0, BELOW, None),
            (">10000", 10000.0, ABOVE, None),
            ("-0.5", -0.5, OK, None),
            ("-99", -99.0, OK, None),
            (".5", 0.5, OK, None),
            ("1.5e-3", 0.0015, OK, None),
            ("0,5", NAN, OK, MARK),
            ("1,234.5", NAN, OK, MARK),
            ("ND", NAN, OK, NOT_NUMBER),
            ("", NAN, OK, None),
        ])

    def test_original_text_and_rows(self) -> None:
        """RF-005-09: el texto original se conserva tal cual (con sus espacios), también el
        de un centinela y el de un rechazo; las filas rechazadas van en orden, con un motivo
        cada una, y no tienen valor."""
        texts = [" <0,01 ", "x", "ND", "", "1,5", "0.5", " 7 "]
        column = values.parse_column(texts, model.ValueRules(",", frozenset({"ND"})))
        self.assertEqual(column.reported.tolist(),
                         [" <0,01 ", "x", "ND", None, "1,5", "0.5", " 7 "])
        self.assertEqual(column.rejected_rows.tolist(), [1, 5])
        self.assertEqual(len(column.rejected_reasons), 2)
        self.assertEqual(_bits(column.values), _bits([0.01, NAN, NAN, NAN, 1.5, NAN, 7.0]))

    def test_inputs(self) -> None:
        """RF-005-09: se leen listas, tuplas y arrays de textos (``None`` = vacío, como una
        celda vacía de un XLSX); un número que no es texto, un texto suelto o unas reglas que
        no son ``ValueRules`` son un error del programa. Una columna vacía da arrays vacíos."""
        expected = _bits([1.5, NAN, 0.25])
        for texts in (["1,5", None, "0,25"], ("1,5", "", "0,25"),
                      np.array(["1,5", "", "0,25"])):
            with self.subTest(tipo=type(texts).__name__):
                parsed = values.parse_column(texts, COMMA)
                self.assertEqual(_bits(parsed.values), expected)
                self.assertEqual(parsed.reported.tolist()[1], None)
        empty = values.parse_column([], COMMA)
        self.assertEqual((len(empty), empty.values.dtype, empty.flags.dtype), (0, np.float64,
                                                                               np.int8))
        for texts in (["1,5", 2.5], ["1,5", np.float32(2.5)], "1,5"):
            with self.subTest(textos=texts):
                with self.assertRaises(TypeError):
                    values.parse_column(texts, COMMA)
        with self.assertRaises(TypeError):
            values.parse_column(["1,5"], ",")

    def test_value_rules_is_the_model_one(self) -> None:
        """RF-005-09: ``drillholes.values`` da las ``ValueRules`` del modelo (las de la
        ``SourceDeclaration``), no otras; las marcas int8 son los códigos de la columna
        ``detection_flag`` de ``AssayColumns``."""
        self.assertIs(values.ValueRules, model.ValueRules)
        self.assertEqual(values.FLAGS, model.AssayColumns.code_values("detection_flag"))
        self.assertEqual({flag: values.FLAG_CODES[flag] for flag in Flag},
                         {flag: code for code, flag in enumerate(values.FLAGS)})


class FastPathTest(unittest.TestCase):
    """RF-005-02, RF-005-09: los números corrientes no pasan por el analizador de especiales y
    son, bit a bit, el float64 de su decimal."""

    def test_only_specials_are_analysed(self) -> None:
        """RF-005-09: en una columna de 5 000 números, vacíos, un «<0,01», un centinela y un
        «abc», el analizador de especiales solo ve esos tres; los vacíos y los números van
        por la vía rápida, sin un bucle de Python por valor."""
        rng = random.Random(5005)
        texts = [f"{rng.randrange(10**6)},{rng.randrange(1000):03d}" for _ in range(5000)]
        texts[10:20] = [""] * 10
        texts[100], texts[200], texts[300] = "<0,01", "ND", "abc"
        rules = model.ValueRules(",", frozenset({"ND"}))
        with mock.patch.object(values, "_special", wraps=values._special) as special:
            parsed = values.parse_column(texts, rules)
        self.assertEqual(sorted(call.args[0] for call in special.call_args_list),
                         ["<0,01", "ND", "abc"])
        self.assertEqual(parsed.rejected_rows.tolist(), [300])
        self.assertEqual(int(np.isnan(parsed.values).sum()), 12)

    def test_decimals_are_exact(self) -> None:
        """RF-005-02: 20 000 decimales al azar (de 1 a 17 cifras, con signo, coordenadas UTM
        de 4,4 Mm y valores pequeños), con coma y con punto, dan bit a bit ``float(texto)``:
        un solo redondeo, el del decimal."""
        rng = random.Random(502)
        texts = []
        for _ in range(20000):
            digits = str(rng.randrange(1, 10 ** rng.randrange(1, 18)))
            point = rng.randrange(len(digits) + 1)
            text = (digits[:point] or "0") + "." + (digits[point:] or "0")
            texts.append(("-" if rng.random() < 0.2 else "") + text)
        texts += ["4400040.456", "700010.5", "0.1", "0.3", "2.675", "1.0000000000000002",
                  "17976931348623157" + "0" * 292 + ".0", "0." + "0" * 320 + "5"]
        expected = _bits([float(text) for text in texts])
        self.assertEqual(_bits(values.parse_column(texts, POINT).values), expected)
        commas = [text.replace(".", ",") for text in texts]
        self.assertEqual(_bits(values.parse_column(commas, COMMA).values), expected)


class DataFilesTest(unittest.TestCase):
    """RF-005-09: los valores de laboratorio de ``tests/data/dh`` dan lo que dice su
    ``esperado.json`` y su README."""

    def test_basico_long_and_wide(self) -> None:
        """RF-005-09: la columna «Valor» de ``csv_basico/analisis_filas.csv`` (coma decimal,
        sin centinelas) da los 84 valores con 1 ausente, 2 bajo el límite y 1 sobre el
        límite superior (``esperado.json``), sin rechazos; las columnas Au, Ag y Cu de
        ``analisis_columnas.csv`` dan los mismos valores y marcas."""
        expected = json.loads((BASICO / "esperado.json").read_text(encoding="utf-8"))
        declared = expected["declaration"]
        rules = model.ValueRules(declared["decimal_mark"], frozenset(declared["sentinels"]),
                                 declared["negative_is_below_dl"])
        long = _read(BASICO / "analisis_filas.csv", ";")
        parsed = values.parse_column(_column(long, "Valor"), rules)
        counts = expected["values"]
        flags = _flags(parsed)
        self.assertEqual(len(parsed), counts["read"])
        self.assertEqual(int(np.isnan(parsed.values).sum()), counts["absent"])
        self.assertEqual(flags.count(BELOW), counts["below_dl"])
        self.assertEqual(flags.count(ABOVE), counts["above_ul"])
        self.assertEqual(parsed.rejected_rows.tolist(), [])
        by_key = {(sample, element): (bits, flag) for sample, element, bits, flag in zip(
            _column(long, "Muestra"), _column(long, "Elemento"), _bits(parsed.values), flags,
            strict=True)}
        wide = _read(BASICO / "analisis_columnas.csv", ";")
        found = {}
        for element in ("Au", "Ag", "Cu"):
            column = values.parse_column(_column(wide, element), rules)
            self.assertEqual(column.rejected_rows.tolist(), [])
            for sample, bits, flag in zip(_column(wide, "Muestra"), _bits(column.values),
                                          _flags(column), strict=True):
                found[(sample, element)] = (bits, flag)
        self.assertEqual(found, by_key)

    def test_convenios(self) -> None:
        """RF-005-09: con punto decimal, los análisis de ``csv_convenios`` dan «<10», «<0.5» y
        «>10000» con su marca y ningún rechazo."""
        table = _read(CONVENIOS / "assays.csv", ",")
        parsed = values.parse_column(_column(table, "Value"), POINT)
        self.assertEqual(parsed.rejected_rows.tolist(), [])
        marked = {text: (value, flag) for text, value, flag in zip(
            parsed.reported.tolist(), parsed.values.tolist(), _flags(parsed), strict=True)
            if flag is not OK}
        self.assertEqual(marked, {"<10": (10.0, BELOW), "<0.5": (0.5, BELOW),
                                  ">10000": (10000.0, ABOVE)})

    def test_negatives_of_w08(self) -> None:
        """RF-005-09: los valores de DH-W08 (Ag de M-0102 = 0 y de M-0302 = −0,5) se guardan
        tal cual sin declaración (los avisa la validación); con «−x = <x», −0,5 es 0,5 bajo el
        límite y 0 sigue siendo 0."""
        table = _read(ERRORES / "dh_w08_analisis_filas.csv", ";")
        texts = _column(table, "Valor")
        rows = [i for i, (sample, element) in enumerate(zip(
            _column(table, "Muestra"), _column(table, "Elemento"), strict=True))
            if (sample, element) in {("M-0102", "Ag"), ("M-0302", "Ag")}]
        plain = values.parse_column(texts, COMMA)
        self.assertEqual([plain.values[i] for i in rows], [0.0, -0.5])
        self.assertEqual([_flags(plain)[i] for i in rows], [OK, OK])
        declared = values.parse_column(texts, model.ValueRules(",", negative_is_below_dl=True))
        self.assertEqual([declared.values[i] for i in rows], [0.0, 0.5])
        self.assertEqual([_flags(declared)[i] for i in rows], [OK, BELOW])
        self.assertEqual([declared.reported[i] for i in rows], ["0", "-0,5"])


class SingleTest(unittest.TestCase):
    """RF-005-02: un Single de RecMin se guarda por su decimal más corto."""

    def test_scalar(self) -> None:
        """RF-005-02: ``float32(0.1)`` → 0,1 (no 0,10000000149011612), 4,35 → 4,35; también
        si llega ya en float64 (0.10000000149011612); NaN sigue ausente, −0 es 0. Un float64
        que no es un Single (0,1) es un error: se perdería su valor."""
        self.assertEqual(float(np.float32(0.1)), 0.10000000149011612)
        cases = [(np.float32(0.1), 0.1), (np.float32(4.35), 4.35),
                 (0.10000000149011612, 0.1), (np.float32(58.5), 58.5),
                 (np.float32(-0.0), 0.0), (np.float32(16777217.0), 16777216.0),
                 (np.float32(1e-5), 1e-05), (np.float32(3.4028235e38), 3.4028235e38)]
        for single, expected in cases:
            with self.subTest(single=single):
                found = values.from_single(single)
                self.assertIs(type(found), float)
                self.assertEqual(_bits([found]), _bits([expected]))
        self.assertTrue(math.isnan(values.from_single(np.float32("nan"))))
        for bad in (0.1, 1e300, "0,1", np.float64(0.1)):
            with self.subTest(malo=bad):
                with self.assertRaises((TypeError, ValueError)):
                    values.from_single(bad)

    def test_column(self) -> None:
        """RF-005-02: la columna da lo mismo que ``float(format_float_positional(float32(v),
        unique=True, trim='-'))`` valor a valor (20 000 Single al azar, por sus bits, y los
        repetidos de una base: 0,1 y 4,35), en float64 y sin cambiar la entrada."""
        rng = np.random.default_rng(502)
        singles = rng.integers(0, 2**32, 20000, dtype=np.uint64).astype(np.uint32)
        singles = singles.view(np.float32)
        singles = np.concatenate([singles[np.isfinite(singles)],
                                  np.array([0.1, 4.35, 0.1, -0.0, np.nan], np.float32)])
        kept = singles.copy()
        found = values.from_single_column(singles)
        self.assertEqual(found.dtype, np.float64)
        self.assertEqual(singles.tobytes(), kept.tobytes())
        expected = [float(np.format_float_positional(v, unique=True, trim="-")) + 0.0
                    for v in singles]
        self.assertEqual(_bits(found), _bits(expected))
        self.assertEqual(found[-5:-1].tolist(), [0.1, 4.35, 0.1, 0.0])
        widened = values.from_single_column(singles.astype(np.float64))
        self.assertEqual(_bits(widened), _bits(found))
        with self.assertRaises(ValueError):
            values.from_single_column(np.array([0.1, 0.5]))
        self.assertEqual(values.from_single_column(np.array([], np.float32)).dtype, np.float64)


if __name__ == "__main__":
    unittest.main()
