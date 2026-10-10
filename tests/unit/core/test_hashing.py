# SPDX-License-Identifier: GPL-3.0-or-later
"""JSON canónico, flotante canónico y huellas sha256 (spec 008, T04; RF-008-07, RF-008-08;
ADR-0024 §2; plan 008 §5.3.1).

El hash de contenido de una entrada (RF-008-08) y lo que se registra de ella (RF-008-07:
ajustes de importación en JSON canónico y la huella de los bytes de cada fichero) se apoyan
en tres piezas que no pueden cambiar con el proceso, el equipo ni el orden en que se
construyó un valor: el **JSON canónico** (UTF-8 sin BOM, claves ordenadas, sin espacios,
enteros como enteros, flotantes con ``repr``, −0,0 → 0,0, NaN e infinitos con su marca), el
**flotante canónico** (un float32 se amplía sin pérdida, NaN canónico, −0,0 = 0,0) y la
**huella sha256** de unos bytes o de un fichero leído por trozos, con progreso y
cancelación entre trozos.
"""

import copy
import datetime as dt
import hashlib
import json
import math
import random
import struct
import subprocess
import sys
import unittest
from collections import OrderedDict, namedtuple
from decimal import Decimal
from fractions import Fraction
from http import HTTPStatus
from types import MappingProxyType

import numpy as np

from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.repo import ROOT
from tests.support.trees import age_folders, child_env, child_temp

hashing = import_geoblender("core.hashing")

MIB = 1 << 20
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
CANONICAL_NAN_BITS = 0x7FF8000000000000
BACKSLASH = chr(92)


def _bits(value: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def _from_bits(bits: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def _float32_from_bits(bits: int) -> np.float32:
    return np.frombuffer(struct.pack("<I", bits), dtype="<f4")[0]


# NaN con otras cargas y signos: el silencioso de siempre, uno con carga, el negativo, uno
# señalizador y todo unos.
NAN_PATTERNS = (
    0x7FF8000000000000,
    0x7FF8000000000001,
    0xFFF8000000000000,
    0x7FF0000000000001,
    0xFFFFFFFFFFFFFFFF,
)


def sample_names() -> list[str]:
    """Nombres de campo en el orden en que los recorre un conjunto: depende de
    ``PYTHONHASHSEED``, así que cambia de un proceso a otro."""
    names = {f"campo_{index:02d}" for index in range(48)}
    names |= {"año", "Z", "a", "é", "_", "B"}
    return list(names)


def sample_value() -> dict[str, object]:
    """Un valor con objetos construidos en el orden de :func:`sample_names` (otro en cada
    proceso) y todos los casos especiales del JSON canónico."""
    names = sample_names()
    return {
        "campos": {name: len(name) * 0.1 for name in names},
        "listas": [[name, index % 3 == 0] for index, name in enumerate(sorted(names))],
        "especiales": [-0.0, math.nan, math.inf, -math.inf, 2**70, None, 1.0, 1e16, 5e-324],
        "texto": "Peñón de 12,000 0 ha €",
        "bytes": b"\x00\xff",
        "fecha": dt.datetime(2026, 10, 8, 10, 0, 0, 125000, tzinfo=dt.UTC),
    }


CHILD = r"""
import hashlib, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from tests.unit.core import test_hashing as module
print(module.hashing.canonical_json(module.sample_value()).hex())
print(hashlib.sha256("|".join(module.sample_names()).encode("utf-8")).hexdigest())
"""


class CanonicalFloatTest(unittest.TestCase):
    def test_negative_zero_is_zero(self) -> None:
        """RF-008-08 (ADR-0024 §2 y §4): −0,0 y 0,0 son el mismo valor: el flotante
        canónico de −0,0 es 0,0 con el signo positivo, también desde float32."""
        for value in (-0.0, 0.0, np.float32(-0.0), np.float64(-0.0)):
            with self.subTest(value=value):
                result = hashing.canonical_float(value)
                self.assertIs(type(result), float)
                self.assertEqual(_bits(result), 0)

    def test_any_nan_is_the_canonical_nan(self) -> None:
        """RF-008-08 (ADR-0024 §4): todo NaN, con cualquier carga o signo, en float64 o en
        float32, es el NaN canónico ``0x7FF8000000000000``."""
        values = [_from_bits(bits) for bits in NAN_PATTERNS]
        values += [_float32_from_bits(bits) for bits in (0x7FC00000, 0x7FC00001, 0xFFC00000)]
        values.append(np.float64(math.nan))
        for value in values:
            with self.subTest(value=repr(value)):
                result = hashing.canonical_float(value)
                self.assertIs(type(result), float)
                self.assertEqual(_bits(result), CANONICAL_NAN_BITS)
        self.assertEqual(_bits(hashing.CANONICAL_NAN), CANONICAL_NAN_BITS)

    def test_float32_widens_exactly(self) -> None:
        """RF-008-08 (D-8): el mismo valor en float32 y en float64 es el mismo flotante
        canónico: un float32 se amplía a float64 sin pérdida (0,1 en float32 es
        0,100000001490116…, no 0,1)."""
        rng = random.Random(4)
        samples = [np.float32(0.1), np.float32(12000.0), np.float32(-4400000.5)]
        samples += [_float32_from_bits(rng.getrandbits(32) & 0x7F7FFFFF) for _ in range(500)]
        for value in samples:
            with self.subTest(value=repr(value)):
                result = hashing.canonical_float(value)
                self.assertIs(type(result), float)
                self.assertEqual(result, float(value))
                self.assertEqual(np.float32(result), value)
        self.assertEqual(hashing.canonical_float(np.float32(0.1)), 0.10000000149011612)

    def test_other_values_are_unchanged(self) -> None:
        """RF-008-08: fuera de NaN y −0,0 el valor no cambia en ningún bit (sin tolerancia,
        D-8); los infinitos siguen siendo infinitos y un entero pasa a float."""
        rng = random.Random(8)
        for _ in range(2000):
            bits = rng.getrandbits(64)
            value = _from_bits(bits)
            if math.isnan(value) or value == 0.0:
                continue
            self.assertEqual(_bits(hashing.canonical_float(value)), bits)
        self.assertEqual(hashing.canonical_float(math.inf), math.inf)
        self.assertEqual(hashing.canonical_float(-math.inf), -math.inf)
        self.assertEqual(_bits(hashing.canonical_float(5e-324)), 1)
        self.assertEqual(hashing.canonical_float(3), 3.0)
        self.assertIs(type(hashing.canonical_float(3)), float)

    def test_rejects_what_is_not_a_number(self) -> None:
        """RF-008-08: un booleano, un texto, ``None`` o unos bytes no son un flotante: se
        rechazan con ``TypeError`` en lugar de convertirlos a escondidas."""
        for value in (True, False, "1.0", None, b"1", [1.0]):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    hashing.canonical_float(value)


class CanonicalJsonTest(unittest.TestCase):
    def test_sorted_keys_without_spaces(self) -> None:
        """RF-008-07, RF-008-08 (ADR-0024 §2): claves ordenadas (por punto de código, también
        en los objetos anidados), sin espacios ni saltos de línea."""
        value = {"b": 1, "a": [1, 2.5, "x"], "c": {"z": None, "y": True}, "á": 0, "B": 0, "_": 0}
        self.assertEqual(
            hashing.canonical_json(value),
            '{"B":0,"_":0,"a":[1,2.5,"x"],"b":1,"c":{"y":true,"z":null},"á":0}'.encode(),
        )

    def test_key_order_does_not_matter(self) -> None:
        """RF-008-08: el mismo objeto construido en otro orden, o como otro tipo de
        diccionario, da los mismos bytes."""
        items = [(f"k{index}", {"v": index * 0.5, "w": [index, None]}) for index in range(40)]
        forward = dict(items)
        backward = dict(reversed(items))
        shuffled = list(items)
        random.Random(15).shuffle(shuffled)
        expected = hashing.canonical_json(forward)
        self.assertEqual(hashing.canonical_json(backward), expected)
        self.assertEqual(hashing.canonical_json(OrderedDict(shuffled)), expected)
        self.assertEqual(hashing.canonical_json(MappingProxyType(dict(shuffled))), expected)

    def test_floats_with_repr(self) -> None:
        """RF-008-08 (ADR-0024 §2): un flotante se escribe con ``repr``, el texto más corto
        que vuelve al mismo binario: 2 000 valores al azar vuelven bit a bit."""
        pinned = {
            0.1: b"0.1",
            1.0: b"1.0",
            1e16: b"1e+16",
            1e-7: b"1e-07",
            5e-324: b"5e-324",
            0.30000000000000004: b"0.30000000000000004",
            1.7976931348623157e308: b"1.7976931348623157e+308",
            -4400000.456: b"-4400000.456",
            12.0: b"12.0",
        }
        for value, text in pinned.items():
            with self.subTest(value=value):
                self.assertEqual(hashing.canonical_json(value), text)
        rng = random.Random(16)
        for _ in range(2000):
            value = _from_bits(rng.getrandbits(64))
            if not math.isfinite(value):
                continue
            encoded = hashing.canonical_json(value)
            canonical = hashing.canonical_float(value)
            self.assertEqual(encoded, repr(canonical).encode("ascii"))
            self.assertEqual(_bits(json.loads(encoded)), _bits(canonical))

    def test_integers_as_integers(self) -> None:
        """RF-008-08 (ADR-0024 §2): los enteros se escriben como enteros (sin «.0» ni
        límite de tamaño) y un flotante entero, con su «.0»: 1 y 1,0 son valores distintos.
        Los booleanos son ``true`` y ``false``, nunca 1 y 0."""
        cases = (  # pares, no un diccionario: en él 1 y True serían la misma clave
            (1, b"1"),
            (-5, b"-5"),
            (0, b"0"),
            (2**70, b"1180591620717411303424"),
            (np.int64(7), b"7"),
            (np.int32(-3), b"-3"),
            (True, b"true"),
            (False, b"false"),
            (None, b"null"),
        )
        for value, text in cases:
            with self.subTest(value=value):
                self.assertEqual(hashing.canonical_json(value), text)
        self.assertEqual(hashing.canonical_json([1, 1.0, True]), b"[1,1.0,true]")

    def test_float32_and_float64_give_the_same_bytes(self) -> None:
        """RF-008-08 (D-8): el mismo valor en float32 y en float64 da los mismos bytes; un
        flotante de numpy se escribe como el de Python."""
        for value in (0.5, 0.1, -4400000.5, 12000.0):
            single = np.float32(value)
            with self.subTest(value=value):
                self.assertEqual(
                    hashing.canonical_json([single, {"z": single}]),
                    hashing.canonical_json([float(single), {"z": float(single)}]),
                )
        self.assertEqual(hashing.canonical_json(np.float32(0.5)), hashing.canonical_json(0.5))
        self.assertEqual(hashing.canonical_json(np.float64(0.1)), b"0.1")
        self.assertEqual(hashing.canonical_json(np.float32(0.1)), b"0.10000000149011612")

    def test_marks_for_negative_zero_nan_and_infinities(self) -> None:
        """RF-008-08 (ADR-0024 §2): −0,0 → ``0.0``; todo NaN → ``{"nan":true}``; los
        infinitos → ``{"inf":1}`` y ``{"inf":-1}``; también anidados y desde float32."""
        self.assertEqual(hashing.canonical_json(-0.0), b"0.0")
        self.assertEqual(hashing.canonical_json(np.float32(-0.0)), b"0.0")
        for bits in NAN_PATTERNS:
            with self.subTest(bits=hex(bits)):
                self.assertEqual(hashing.canonical_json(_from_bits(bits)), b'{"nan":true}')
        self.assertEqual(hashing.canonical_json(_float32_from_bits(0xFFC00001)), b'{"nan":true}')
        self.assertEqual(hashing.canonical_json(math.inf), b'{"inf":1}')
        self.assertEqual(hashing.canonical_json(-math.inf), b'{"inf":-1}')
        self.assertEqual(
            hashing.canonical_json({"v": [math.nan, -math.inf, -0.0, np.float32(math.inf)]}),
            b'{"v":[{"nan":true},{"inf":-1},0.0,{"inf":1}]}',
        )

    def test_utf8_without_bom_and_exact_text(self) -> None:
        """RF-008-07, RF-008-08 (ADR-0024 §2): UTF-8 sin BOM, sin escapar lo que no es ASCII;
        el texto va tal cual: ni se normaliza Unicode (é compuesta ≠ e + acento) ni se
        tocan los espacios. Las comillas, la barra y los de control van escapados."""
        encoded = hashing.canonical_json({"año": "Peñón  €  ", "𝔸": "x"})
        self.assertEqual(encoded, '{"año":"Peñón  €  ","𝔸":"x"}'.encode("utf-8"))
        self.assertFalse(encoded.startswith(b"\xef\xbb\xbf"))
        composed = hashing.canonical_json("é")
        decomposed = hashing.canonical_json("e" + chr(0x301))
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(decomposed, b'"e\xcc\x81"')
        self.assertNotEqual(hashing.canonical_json("a b"), hashing.canonical_json("a  b"))
        escaped = hashing.canonical_json('"' + chr(10) + chr(9) + BACKSLASH + chr(1) + chr(0x2028))
        expected = (
            b'"' + b"\\\"" + b"\\n" + b"\\t" + b"\\\\" + b"\\" + b"u0001"
            + chr(0x2028).encode("utf-8") + b'"'
        )
        self.assertEqual(escaped, expected)

    def test_bytes_dates_and_tuples(self) -> None:
        """RF-008-07 (ADR-0024 §2): los binarios van como ``{"b64": …}``; las fechas, en ISO
        8601 UTC con «Z» (milisegundos, o microsegundos si los hay) y los días como
        ``AAAA-MM-DD``; una tupla es una lista. Una fecha sin zona se rechaza: no se
        supone."""
        self.assertEqual(hashing.canonical_json(b"\x00\xff"), b'{"b64":"AP8="}')
        self.assertEqual(hashing.canonical_json(bytearray(b"abc")), b'{"b64":"YWJj"}')
        self.assertEqual(hashing.canonical_json(memoryview(b"")), b'{"b64":""}')
        madrid = dt.timezone(dt.timedelta(hours=2))
        dates = (
            (dt.datetime(2026, 10, 8, 10, 0, tzinfo=dt.UTC), b'"2026-10-08T10:00:00.000Z"'),
            (
                dt.datetime(2026, 10, 8, 12, 0, 0, 125000, tzinfo=madrid),
                b'"2026-10-08T10:00:00.125Z"',
            ),
            (
                dt.datetime(2026, 10, 8, 10, 0, 0, 123456, tzinfo=dt.UTC),
                b'"2026-10-08T10:00:00.123456Z"',
            ),
            (dt.date(2026, 10, 8), b'"2026-10-08"'),
        )
        for value, text in dates:
            with self.subTest(value=value):
                self.assertEqual(hashing.canonical_json(value), text)
        with self.assertRaises(ValueError):
            hashing.canonical_json({"fecha": dt.datetime(2026, 10, 8, 10, 0)})
        self.assertEqual(
            hashing.canonical_json((1, (2.0, "x"))), hashing.canonical_json([1, [2.0, "x"]])
        )

    def test_subclasses_are_written_as_their_base(self) -> None:
        """RF-008-07: una enumeración de texto (``ParamKind.HIPOTESIS``) se escribe como su
        texto, una de enteros como su entero y una tupla con nombre como una lista."""
        kind = import_geoblender("core.params").ParamKind
        point = namedtuple("Point", "x y")
        self.assertEqual(
            hashing.canonical_json({kind.HIPOTESIS: kind.ADOPTADO, "n": HTTPStatus.OK}),
            '{"HIPÓTESIS":"ADOPTADO","n":200}'.encode("utf-8"),
        )
        self.assertEqual(hashing.canonical_json(point(1.5, -0.0)), b"[1.5,0.0]")

    def test_rejects_values_without_a_canonical_form(self) -> None:
        """RF-008-08: lo que no tiene una forma canónica única se rechaza en lugar de
        escribirse de cualquier modo: conjuntos (sin orden), claves que no son texto,
        fracciones y decimales (no son un flotante exacto), complejos, matrices de numpy y
        objetos; un texto con un sustituto suelto no es UTF-8."""
        rejected = (
            {1, 2},
            frozenset({"a"}),
            {1: "a"},
            {("a",): 1},
            Fraction(1, 3),
            Decimal("1.5"),
            1 + 2j,
            np.array([1.0, 2.0]),
            object(),
            [dt.time(10, 0)],
        )
        for value in rejected:
            with self.subTest(value=repr(value)):
                with self.assertRaises(TypeError):
                    hashing.canonical_json(value)
        with self.assertRaises(ValueError):
            hashing.canonical_json({"a": "x" + chr(0xD800)})

    def test_input_is_not_modified(self) -> None:
        """RF-008-07: calcular la forma canónica no cambia el valor que se le da (ni −0,0,
        ni NaN, ni el orden de sus claves)."""
        value = sample_value()
        before = copy.deepcopy(value)
        order = list(value["campos"])
        hashing.canonical_json(value)
        self.assertEqual(list(value["campos"]), order)
        self.assertEqual(repr(value), repr(before))
        self.assertEqual(math.copysign(1.0, value["especiales"][0]), -1.0)

    def test_same_bytes_in_two_processes(self) -> None:
        """RF-008-08 (ADR-0024 §6: un hash de hoy se comprueba con otro proceso y otro
        día): el mismo valor da los mismos bytes en este proceso y en dos procesos hijos con
        otra semilla de ``hash`` (que recorren el conjunto de nombres en otro orden, y así
        construyen sus objetos en otro orden)."""
        expected = hashing.canonical_json(sample_value())
        self.assertEqual(
            hashlib.sha256(expected).hexdigest(),
            hashing.sha256_bytes(expected),
        )
        # Los hijos, con el mismo intérprete y sin el site-packages si este no lo tiene (el
        # paso «motor» de check.py usa -S y el numpy del motor en PYTHONPATH).
        flags = ["-B", "-s", *(["-S"] if sys.flags.no_site else [])]
        with child_temp() as temp:
            children = []
            for seed in ("1", "2"):
                env = child_env(None, temp)
                env["PYTHONHASHSEED"] = seed
                children.append(
                    subprocess.Popen(
                        [sys.executable, *flags, "-c", CHILD, str(ROOT)],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=env,
                        text=True,
                    )
                )
            outputs = []
            for child in children:
                out, err = child.communicate(timeout=60)
                self.assertEqual(child.returncode, 0, err)
                outputs.append(out.split())
        (first_bytes, first_order), (second_bytes, second_order) = outputs
        self.assertNotEqual(first_order, second_order, "las dos semillas dieron el mismo orden")
        self.assertEqual(bytes.fromhex(first_bytes), expected)
        self.assertEqual(bytes.fromhex(second_bytes), expected)


class Sha256BytesTest(unittest.TestCase):
    def test_known_vectors(self) -> None:
        """RF-008-07: la huella de unos bytes es su sha256 en hexadecimal en minúsculas (los
        vectores de FIPS 180-2 para «» y «abc»), igual desde ``bytes``, ``bytearray`` y
        ``memoryview``; un texto sin codificar se rechaza."""
        self.assertEqual(hashing.sha256_bytes(b""), EMPTY_SHA256)
        self.assertEqual(hashing.sha256_bytes(b"abc"), ABC_SHA256)
        self.assertEqual(hashing.sha256_bytes(bytearray(b"abc")), ABC_SHA256)
        self.assertEqual(hashing.sha256_bytes(memoryview(b"xabcx")[1:4]), ABC_SHA256)
        with self.assertRaises(TypeError):
            hashing.sha256_bytes("abc")


class Sha256FileTest(unittest.TestCase):
    """Un fichero de 20 MiB (no múltiplo del trozo de 8 MiB) con bytes deterministas. Cada
    prueba lo lee como mucho una vez (sha256 va a unos 180 MB/s en el PC de referencia)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = cls.enterClassContext(project_tmp("gb-hash-"))
        cls.data = random.Random(20261008).randbytes(20 * MIB)
        cls.path = cls.folder / "fuente.bin"
        cls.path.write_bytes(cls.data)
        cls.expected = hashlib.sha256(cls.data).hexdigest()

    def _stat(self) -> tuple[int, int]:
        status = self.path.stat()
        return status.st_size, status.st_mtime_ns

    def test_20_mib_equals_hashlib_with_progress(self) -> None:
        """RF-008-07: la huella de un fichero de 20 MiB leído por trozos de 8 MiB es la de
        ``hashlib``; el progreso llega tras cada trozo (bytes hechos, total) y acaba en el
        total. El fichero queda con el mismo tamaño y la misma fecha."""
        calls: list[tuple[int, int]] = []
        before = self._stat()
        digest = hashing.sha256_file(
            self.path, progress=lambda done, total: calls.append((done, total))
        )
        self.assertEqual(digest, self.expected)
        self.assertEqual(calls, [(8 * MIB, 20 * MIB), (16 * MIB, 20 * MIB), (20 * MIB, 20 * MIB)])
        self.assertEqual(self._stat(), before)
        self.assertEqual(hashing.DEFAULT_CHUNK, 8 * MIB)

    def test_other_chunk_sizes_and_empty_file(self) -> None:
        """RF-008-07: con trozos de cualquier tamaño (1 byte, 7 bytes, más que el fichero) y
        con la ruta como texto, la huella es la misma y la carpeta de la fuente no cambia
        (tampoco auxiliares); la de un fichero vacío es la del vacío, con un aviso de
        progreso (0, 0)."""
        folder = self.folder / "pequeños"
        folder.mkdir()
        small = folder / "pequeño.bin"
        small.write_bytes(self.data[:1000])
        empty = folder / "vacío.bin"
        empty.write_bytes(b"")
        expected = hashlib.sha256(self.data[:1000]).hexdigest()
        age_folders(folder)
        with assert_source_untouched(folder):
            for chunk in (1, 7, 999, 1000, 1001, 8 * MIB):
                with self.subTest(chunk=chunk):
                    calls: list[tuple[int, int]] = []
                    digest = hashing.sha256_file(
                        str(small),
                        chunk=chunk,
                        progress=lambda done, total: calls.append((done, total)),
                    )
                    self.assertEqual(digest, expected)
                    self.assertEqual(len(calls), -(-1000 // chunk))
                    self.assertEqual(calls[-1], (1000, 1000))
            calls = []
            self.assertEqual(
                hashing.sha256_file(
                    empty, progress=lambda done, total: calls.append((done, total))
                ),
                EMPTY_SHA256,
            )
        self.assertEqual(calls, [(0, 0)])

    def test_cancel_between_chunks(self) -> None:
        """RF-008-07 (ADR-0024 §7: por bloques, con progreso y cancelación): si se pide parar
        tras el primer trozo, para antes de leer el segundo con ``HashCancelled`` (lo leído y
        el total) y deja el fichero cerrado (se puede renombrar en Windows) y sin cambios."""
        answers = iter([False, True])
        calls: list[tuple[int, int]] = []
        before = self._stat()
        with self.assertRaises(hashing.HashCancelled) as caught:
            hashing.sha256_file(
                self.path,
                progress=lambda done, total: calls.append((done, total)),
                cancelled=lambda: next(answers),
            )
        self.assertEqual(self._stat(), before)
        self.assertEqual(calls, [(8 * MIB, 20 * MIB)])
        self.assertEqual((caught.exception.done, caught.exception.total), (8 * MIB, 20 * MIB))
        self.assertIn("fuente.bin", str(caught.exception))
        moved = self.path.with_name("movido.bin")
        self.path.replace(moved)
        moved.replace(self.path)

    def test_cancel_before_the_first_chunk(self) -> None:
        """RF-008-07: si ya se pidió parar, no se lee nada: ``HashCancelled`` con 0 bytes y
        ningún aviso de progreso."""
        calls: list[tuple[int, int]] = []
        with self.assertRaises(hashing.HashCancelled) as caught:
            hashing.sha256_file(
                self.path,
                progress=lambda done, total: calls.append((done, total)),
                cancelled=lambda: True,
            )
        self.assertEqual(calls, [])
        self.assertEqual((caught.exception.done, caught.exception.total), (0, 20 * MIB))

    def test_invalid_chunk_and_missing_file(self) -> None:
        """RF-008-07: un trozo que no es un entero positivo se rechaza antes de abrir nada;
        un fichero que no existe da ``FileNotFoundError``."""
        for chunk in (0, -1):
            with self.subTest(chunk=chunk):
                with self.assertRaises(ValueError):
                    hashing.sha256_file(self.path, chunk=chunk)
        for chunk in (True, 1.5, "8"):
            with self.subTest(chunk=chunk):
                with self.assertRaises(TypeError):
                    hashing.sha256_file(self.path, chunk=chunk)
        with self.assertRaises(FileNotFoundError):
            hashing.sha256_file(self.folder / "no-existe.bin")


if __name__ == "__main__":
    unittest.main()
