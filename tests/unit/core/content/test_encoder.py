# SPDX-License-Identifier: GPL-3.0-or-later
"""Normalizador ``gbch/1``: secciones ``HEAD``, ``DECL`` y ``DATA``, ``ContentDigest`` y
rejillas, documentos y compuestos (spec 008, T05); entidades, filas, mallas y nubes de puntos
(T06). RF-008-08; ADR-0024 §1, §2, §4 y §6; plan 008 §5.4.1. Los vectores de referencia, en
``test_golden_gbch1.py``.

RF-008-08: el hash de contenido da el mismo valor para el mismo dato aunque cambie su
contenedor (teselas, bloques de lectura, orden de bytes, float32 o float64, NaN con otra carga,
−0,0) y otro si cambia cualquier celda, el valor de sin dato, el tipo de celda, el CRS que trae
el fichero o lo declarado al importar (CRS horizontal y vertical, convenios), sin tolerancia
(D-8). ADR-0024 §1: el hash de datos no cambia con las declaraciones (RF-008-54 lo usa para «el
mismo contenido con otros ajustes»); §6: los vectores de referencia fijan la salida de
``gbch/1``.
"""

import datetime as dt
import hashlib
import struct
import tracemalloc
import unittest
from unittest import mock

import numpy as np

from tests.support import provenance_data, wkb_build
from tests.support.package import import_geoblender

content = import_geoblender("core.content")
encoder = import_geoblender("core.content.encoder")
hashing = import_geoblender("core.hashing")

MIB = 1 << 20
CANONICAL_NAN_BITS = 0x7FF8000000000000
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
DECLARATIONS = {
    "conventions": {"decimal": ","},
    "crs_h": {"epsg": 25830},
    "crs_v": {"epsg": 5782},
}
# NaN de float64 con otras cargas y signos (el canónico, con carga, negativo, señalizador,
# todo unos) y de float32 (el de siempre, con carga, negativo, señalizador).
NAN64 = (0x7FF8000000000000, 0x7FF8000000000001, 0xFFF8000000000000, 0x7FF0000000000001,
         0xFFFFFFFFFFFFFFFF)
NAN32 = (0x7FC00000, 0x7FC00001, 0xFFC00000, 0x7F800001)
# 50 M celdas (5 000 × 10 000) en bandas de 100 filas de float32: el hash de datos se calculó
# aparte, con una implementación independiente (struct, json y hashlib, bandas de 500 filas).
BIG_ROWS, BIG_COLUMNS, BIG_BAND = 5_000, 10_000, 100
BIG_DATA_SHA256 = "a7d2126b9efdeacb9b97b97bcff5bf39b3cdca9f60e414753a8d1ee08dc85d35"
BIG_PEAK_LIMIT = 32 * MIB


def _section(label: bytes, payload: bytes) -> bytes:
    """Una sección de ADR-0024 §2 escrita a mano: etiqueta, longitud uint64 LE y contenido."""
    return label + struct.pack("<Q", len(payload)) + payload


def _f64(bits: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def _bits(values: np.ndarray) -> bytes:
    return np.ascontiguousarray(values).tobytes()


def header(**changes: object) -> dict[str, object]:
    """La cabecera de la rejilla de :func:`sample` con ``changes``."""
    found: dict[str, object] = {
        "rows": 4,
        "columns": 5,
        "x0": 715000.0,
        "y0": 4378000.0,
        "dx": 2.0,
        "dy": 2.0,
        "cell": "area",
        "class": "float",
        "nodata": -9999.0,
        "crs": {"epsg": 25830},
    }
    found.update(changes)
    return found


def sample(dtype: str = "<f4") -> np.ndarray:
    """Rejilla de 4 × 5 cotas con un NaN, un −0,0 y una celda sin dato."""
    values = np.array(
        [
            [612.5, 613.25, 614.0, 614.5, 615.0],
            [611.75, np.nan, 612.0, -9999.0, 613.5],
            [610.5, 611.0, -0.0, 612.125, 612.25],
            [609.0, 609.5, 610.25, 610.75, 611.0],
        ],
        dtype="<f8",
    )
    return values.astype(dtype)


def grid_digest(
    values: object = None,
    *,
    head: dict[str, object] | None = None,
    declarations: dict[str, object] | None = None,
    blocks: object = None,
    kind: str = "raster",
) -> object:
    """El ``ContentDigest`` de una rejilla (``blocks``: los bloques de filas tal cual)."""
    hasher = content.ContentHasher(
        kind,
        declarations=DECLARATIONS if declarations is None else declarations,
        reader="test.grid@1",
    )
    if blocks is None:
        blocks = [sample() if values is None else values]
    return hasher.grid(header() if head is None else head, blocks).digest()


def tiled_rows(values: np.ndarray, tile_rows: int, tile_columns: int):
    """Las filas como las da un lector de teselas: cada tesela, rellena con basura más allá
    del borde de la rejilla (como en un GeoTIFF), se recorta y se juntan las de una banda."""
    rows, columns = values.shape
    padded_rows = -(-rows // tile_rows) * tile_rows
    padded_columns = -(-columns // tile_columns) * tile_columns
    padded = np.full((padded_rows, padded_columns), 777.0, dtype=values.dtype)
    padded[:rows, :columns] = values
    for top in range(0, padded_rows, tile_rows):
        tiles = [
            padded[top:top + tile_rows, left:left + tile_columns].copy()
            for left in range(0, padded_columns, tile_columns)
        ]
        band = np.concatenate(tiles, axis=1)
        yield band[: max(0, min(tile_rows, rows - top)), :columns]


class SectionLayoutTest(unittest.TestCase):
    """RF-008-08; ADR-0024 §1, §2 y §4: la forma canónica son secciones (etiqueta ASCII de 4
    bytes, longitud uint64 *little-endian* y contenido); ``HEAD`` = ``{"kind",
    "normalizer"}``, ``DECL`` = las declaraciones y ``DATA`` = el hash de datos, todo en JSON
    canónico; la rejilla, su cabecera y sus valores float64 o int64 *little-endian* por filas
    de norte a sur. Escrita aquí a mano, sin el normalizador, da los mismos hashes."""

    def test_grid_stream(self) -> None:
        values = np.array(
            [[1.5, -0.0, _f64(0x7FF8000000000001)], [2.0, 3.25, -7.0]], dtype="<f8"
        )
        head = header(rows=2, columns=3, x0=715000, dx=2)
        digest = grid_digest(values, head=head)
        canonical = np.array([[1.5, 0.0, _f64(CANONICAL_NAN_BITS)], [2.0, 3.25, -7.0]])
        grid_header = (
            b'{"cell":"area","class":"float","columns":3,"crs":{"epsg":25830},"dx":2.0,'
            b'"dy":2.0,"nodata":-9999.0,"rows":2,"x0":715000.0,"y0":4378000.0}'
        )
        data = hashlib.sha256(
            _section(b"GRID", grid_header) + _section(b"VALS", _bits(canonical.astype("<f8")))
        ).hexdigest()
        self.assertEqual(digest.data_sha256, data)
        decl = b'{"conventions":{"decimal":","},"crs_h":{"epsg":25830},"crs_v":{"epsg":5782}}'
        self.assertEqual(hashing.canonical_json(DECLARATIONS), decl)
        whole = hashlib.sha256(
            _section(b"HEAD", b'{"kind":"raster","normalizer":"gbch/1"}')
            + _section(b"DECL", decl)
            + _section(b"DATA", bytes.fromhex(data))
        ).hexdigest()
        self.assertEqual(digest.content_sha256, whole)
        self.assertEqual(
            content.content_sha256("raster", DECLARATIONS, data), digest.content_sha256
        )

    def test_int_grid_stream(self) -> None:
        values = np.array([[-32768, 0], [7, 32767]], dtype=">i2")
        head = header(rows=2, columns=2, **{"class": "int", "nodata": -32768.0})
        digest = grid_digest(values, head=head)
        grid_header = (
            b'{"cell":"area","class":"int","columns":2,"crs":{"epsg":25830},"dx":2.0,'
            b'"dy":2.0,"nodata":-32768,"rows":2,"x0":715000.0,"y0":4378000.0}'
        )
        stream = _section(b"GRID", grid_header) + _section(
            b"VALS", struct.pack("<4q", -32768, 0, 7, 32767)
        )
        self.assertEqual(digest.data_sha256, hashlib.sha256(stream).hexdigest())

    def test_document_is_its_print(self) -> None:
        source = provenance_data.DATA_DIR / provenance_data.REPORT
        data = source.read_bytes()
        chunks = [data[:7], b"", data[7:100], data[100:]]
        digest = content.ContentHasher("document", declarations={}).document(chunks).digest()
        self.assertEqual(digest.data_sha256, hashing.sha256_file(source))
        whole = hashlib.sha256(
            _section(b"HEAD", b'{"kind":"document","normalizer":"gbch/1"}')
            + _section(b"DECL", b"{}")
            + _section(b"DATA", bytes.fromhex(digest.data_sha256))
        ).hexdigest()
        self.assertEqual(digest.content_sha256, whole)
        empty = content.ContentHasher("document", declarations={}).document([]).digest()
        self.assertEqual(empty.data_sha256, EMPTY_SHA256)

    def test_composite_stream(self) -> None:
        parts = {
            "survey": ("table", hashlib.sha256(b"s").hexdigest()),
            "collar": ("table", hashlib.sha256(b"c").hexdigest()),
            "Assay": ("table", hashlib.sha256(b"a").hexdigest()),
        }
        digest = (
            content.ContentHasher("drillholes", declarations=DECLARATIONS)
            .composite(parts)
            .digest()
        )
        names = sorted(parts)
        self.assertEqual(names, ["Assay", "collar", "survey"])
        part_header = b'{"parts":[["Assay","table"],["collar","table"],["survey","table"]]}'
        values = b"".join(bytes.fromhex(parts[name][1]) for name in names)
        stream = _section(b"PART", part_header) + _section(b"VALS", values)
        self.assertEqual(digest.data_sha256, hashlib.sha256(stream).hexdigest())

    def test_digest_fields(self) -> None:
        digest = grid_digest()
        self.assertIsInstance(digest, content.ContentDigest)
        self.assertEqual(digest.normalizer, "gbch/1")
        self.assertEqual(content.NORMALIZER, "gbch/1")
        self.assertEqual(digest.reader, "test.grid@1")
        for value in (digest.data_sha256, digest.content_sha256):
            self.assertRegex(value, r"\A[0-9a-f]{64}\Z")
        with self.assertRaises(AttributeError):
            digest.data_sha256 = EMPTY_SHA256  # type: ignore[misc]
        hasher = content.ContentHasher("raster", declarations=DECLARATIONS)
        hasher.grid(header(), [sample()])
        self.assertEqual(hasher.digest(), hasher.digest())
        self.assertEqual(hasher.digest().reader, "")


class FloatRulesTest(unittest.TestCase):
    """RF-008-08 y D-8: los mismos valores en float32 y en float64 dan el mismo hash; todo NaN
    es el NaN canónico; −0,0 = 0,0; el orden de bytes no cuenta; y no hay tolerancia: una
    celda o una coordenada que cambia en un bit cambia los dos hashes."""

    def test_float32_equals_float64(self) -> None:
        reference = grid_digest(sample("<f4"))
        for dtype in ("<f8", ">f4", ">f8"):
            with self.subTest(dtype=dtype):
                self.assertEqual(grid_digest(sample("<f4").astype(dtype)), reference)
        half = sample("<f4").astype("<f2")
        self.assertEqual(grid_digest(half), grid_digest(half.astype("<f8")))

    def test_nan_is_canonical(self) -> None:
        reference = grid_digest(sample("<f8"))
        for bits in NAN64:
            values = sample("<f8")
            values.view("<u8")[1, 1] = bits
            with self.subTest(bits=f"{bits:016x}"):
                self.assertEqual(grid_digest(values), reference)
        for bits in NAN32:
            values = sample("<f4")
            values.view("<u4")[1, 1] = bits
            with self.subTest(bits=f"{bits:08x}"):
                self.assertEqual(grid_digest(values), reference)

    def test_negative_zero(self) -> None:
        values = sample("<f8")
        self.assertEqual(struct.pack("<d", values[2, 2]), struct.pack("<d", -0.0))
        positive = values.copy()
        positive[2, 2] = 0.0
        self.assertEqual(grid_digest(values), grid_digest(positive))
        self.assertEqual(grid_digest(values.astype("<f4")), grid_digest(positive))

    def test_no_tolerance(self) -> None:
        reference = grid_digest()
        moved = sample("<f8")
        moved[3, 4] = np.nextafter(moved[3, 4], np.inf)
        smallest = sample("<f8")
        smallest[2, 2] = 5e-324
        corner = header(x0=np.nextafter(715000.0, np.inf))
        for name, digest in (
            ("cota +1 ulp", grid_digest(moved)),
            ("0 → subnormal", grid_digest(smallest)),
            ("x0 +1 ulp", grid_digest(head=corner)),
            ("NaN → sin dato", grid_digest(np.nan_to_num(sample(), nan=-9999.0))),
        ):
            with self.subTest(name):
                self.assertNotEqual(digest.data_sha256, reference.data_sha256)
                self.assertNotEqual(digest.content_sha256, reference.content_sha256)

    def test_input_is_not_modified(self) -> None:
        values = sample("<f8")
        values.view("<u8")[1, 1] = 0xFFF8000000000001
        before = values.tobytes()
        head = header()
        frozen = dict(head)
        grid_digest(values, head=head)
        self.assertEqual(values.tobytes(), before)
        self.assertEqual(head, frozen)
        small = sample("<f4")
        before = small.tobytes()
        grid_digest(small)
        self.assertEqual(small.tobytes(), before)


class GridContentTest(unittest.TestCase):
    """RF-008-08, RF-008-54; ADR-0024 §1, §3 y §4: el sin dato, el tipo de celda y el CRS que
    trae el fichero (``{"epsg": n}`` o ``null``) son datos (cambian los dos hashes); lo
    declarado al importar —CRS horizontal y vertical y convenios— es contenido pero no dato
    (cambia solo el de contenido); una cota cambia los dos; enteros y flotantes iguales en la
    cabecera, o en un sin dato de una rejilla de flotantes, son el mismo valor."""

    def test_data_changes(self) -> None:
        reference = grid_digest()
        changed = sample()
        changed[0, 0] = 612.75
        cases = (
            ("sin dato −9998", grid_digest(head=header(nodata=-9998.0))),
            ("sin dato vacío", grid_digest(head=header(nodata=None))),
            ("sin dato NaN", grid_digest(head=header(nodata=float("nan")))),
            ("celda de punto", grid_digest(head=header(cell="point"))),
            ("CRS del fichero 25829", grid_digest(head=header(crs={"epsg": 25829}))),
            ("CRS del fichero null", grid_digest(head=header(crs=None))),
            ("una cota", grid_digest(changed)),
            ("dy", grid_digest(head=header(dy=2.5))),
        )
        for name, digest in cases:
            with self.subTest(name):
                self.assertNotEqual(digest.data_sha256, reference.data_sha256)
                self.assertNotEqual(digest.content_sha256, reference.content_sha256)

    def test_declarations_change_only_the_content(self) -> None:
        reference = grid_digest()
        cases = (
            ("CRS horizontal declarado", {**DECLARATIONS, "crs_h": {"epsg": 25829}}),
            ("CRS vertical", {**DECLARATIONS, "crs_v": {"local": "cota de obra"}}),
            ("convenio", {**DECLARATIONS, "conventions": {"decimal": "."}}),
            ("convenio nuevo", {**DECLARATIONS, "conventions": {"decimal": ",", "z": "up"}}),
        )
        for name, declarations in cases:
            with self.subTest(name):
                digest = grid_digest(declarations=declarations)
                self.assertEqual(digest.data_sha256, reference.data_sha256)
                self.assertNotEqual(digest.content_sha256, reference.content_sha256)
        other_kind = grid_digest(kind="block_field")
        self.assertEqual(other_kind.data_sha256, reference.data_sha256)
        self.assertNotEqual(other_kind.content_sha256, reference.content_sha256)

    def test_same_values_written_otherwise(self) -> None:
        reference = grid_digest()
        reordered = dict(reversed(list(header().items())))
        decl = dict(reversed(list(DECLARATIONS.items())))
        numpy_head = header(x0=np.float32(715000.0), rows=np.int64(4), crs={"epsg": np.int32(25830)})
        for name, digest in (
            ("enteros en la cabecera", grid_digest(head=header(x0=715000, y0=4378000, dx=2))),
            ("sin dato entero", grid_digest(head=header(nodata=-9999))),
            ("claves en otro orden", grid_digest(head=reordered, declarations=decl)),
            ("numpy en la cabecera", grid_digest(head=numpy_head)),
        ):
            with self.subTest(name):
                self.assertEqual(digest, reference)
        ints = np.array([[1, -2, 3], [4, 5, -32768]], dtype="<i2")
        head = header(rows=2, columns=3, nodata=-32768, **{"class": "int"})
        same = grid_digest(ints, head=head)
        for dtype in ("<i4", "<i8", ">i2"):
            with self.subTest(dtype=dtype):
                self.assertEqual(grid_digest(ints.astype(dtype), head=head), same)
        self.assertEqual(grid_digest(ints, head={**head, "nodata": -32768.0}), same)
        mask = np.array([[True, False], [False, True]])
        bool_head = header(rows=2, columns=2, nodata=None, **{"class": "bool"})
        as_bool = grid_digest(mask, head=bool_head)
        self.assertEqual(grid_digest(mask.astype("<u1"), head=bool_head), as_bool)
        int_head = {**bool_head, "class": "int"}
        self.assertNotEqual(grid_digest(mask.astype("<i8"), head=int_head).data_sha256,
                            as_bool.data_sha256)


class BlocksTest(unittest.TestCase):
    """RF-008-08; ADR-0024 §4 y §7: teselas, bloques de filas, el orden de la memoria y los
    trozos internos del normalizador no cuentan; 50 M celdas se hashean por bloques con
    memoria acotada."""

    def setUp(self) -> None:
        rng = np.random.default_rng(8)
        self.values = (rng.integers(-40000, 40000, size=(37, 53)) / 4).astype("<f4")
        self.values[5, 7] = np.nan
        self.values[36, 52] = -0.0
        self.head = header(rows=37, columns=53)
        self.reference = grid_digest(self.values, head=self.head)

    def test_row_blocks(self) -> None:
        values = self.values
        cases = {
            "fila a fila": list(values),
            "bloques 5, 0, 1, 13 y 18": [values[:5], values[5:5], values[5:6], values[6:19],
                                        values[19:]],
            "orden Fortran": [np.asfortranarray(values)],
            "vista con paso": [np.repeat(values, 2, axis=1)[:, ::2]],
            "generador": (values[top:top + 4] for top in range(0, 37, 4)),
        }
        for name, blocks in cases.items():
            with self.subTest(name):
                self.assertEqual(grid_digest(head=self.head, blocks=blocks), self.reference)

    def test_tiles(self) -> None:
        for tile_rows, tile_columns in ((16, 16), (8, 32), (37, 53), (1, 64), (64, 1)):
            with self.subTest(tile=(tile_rows, tile_columns)):
                blocks = tiled_rows(self.values, tile_rows, tile_columns)
                self.assertEqual(grid_digest(head=self.head, blocks=blocks), self.reference)

    def test_internal_chunks(self) -> None:
        for cells in (1, 7, 53, 54, 1000):
            with self.subTest(cells=cells), mock.patch.object(encoder, "GRID_CHUNK_CELLS", cells):
                self.assertEqual(grid_digest(self.values, head=self.head), self.reference)

    def test_push_form(self) -> None:
        hasher = content.ContentHasher("raster", declarations=DECLARATIONS, reader="test.grid@1")
        feed = hasher.begin_grid(self.head)
        for top in range(0, 37, 10):
            feed.update(self.values[top:top + 10])
            self.assertEqual(feed.rows_done, min(37, top + 10))
        self.assertEqual(feed.finish(), self.reference.data_sha256)
        self.assertEqual(hasher.digest(), self.reference)
        alone = encoder.GridEncoder(self.head)
        alone.update(self.values)
        self.assertEqual(alone.finish(), self.reference.data_sha256)

    def test_50m_cells_bounded_memory(self) -> None:
        base = np.arange(BIG_BAND * BIG_COLUMNS, dtype="<f4").reshape(BIG_BAND, BIG_COLUMNS)
        base *= np.float32(0.25)
        base[3, 7] = np.nan

        def bands():
            for index in range(BIG_ROWS // BIG_BAND):
                yield base + np.float32(index)

        head = header(rows=BIG_ROWS, columns=BIG_COLUMNS, x0=500000.0, y0=4400000.0, dx=1.0,
                      dy=1.0)
        hasher = content.ContentHasher("raster", declarations=DECLARATIONS)
        started = not tracemalloc.is_tracing()
        if started:
            tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            before = tracemalloc.get_traced_memory()[0]
            digest = hasher.grid(head, bands()).digest()
            peak = tracemalloc.get_traced_memory()[1] - before
        finally:
            if started:
                tracemalloc.stop()
        self.assertEqual(digest.data_sha256, BIG_DATA_SHA256)
        self.assertLess(peak, BIG_PEAK_LIMIT, f"pico de memoria: {peak / MIB:.1f} MiB")


class CompositeTest(unittest.TestCase):
    """RF-008-08; ADR-0024 §4: un compuesto (sondeos, una rejilla con su ``.prj``) es el hash
    de datos de cada parte, ordenadas por su nombre: el orden en que llegan no cuenta; el
    nombre, el tipo o los datos de una parte, sí."""

    def setUp(self) -> None:
        self.parts = {
            "collar": ("table", hashlib.sha256(b"c").hexdigest()),
            "survey": ("table", hashlib.sha256(b"s").hexdigest()),
            "assay": ("table", hashlib.sha256(b"a").hexdigest()),
        }

    def digest(self, parts: dict[str, tuple[str, str]]) -> object:
        hasher = content.ContentHasher("drillholes", declarations=DECLARATIONS)
        return hasher.composite(parts).digest()

    def test_order_does_not_count(self) -> None:
        reference = self.digest(self.parts)
        self.assertEqual(self.digest(dict(reversed(list(self.parts.items())))), reference)

    def test_changes(self) -> None:
        reference = self.digest(self.parts)
        renamed = {("collars" if k == "collar" else k): v for k, v in self.parts.items()}
        cases = (
            ("nombre", renamed),
            ("tipo", {**self.parts, "assay": ("document", self.parts["assay"][1])}),
            ("datos", {**self.parts, "assay": ("table", hashlib.sha256(b"b").hexdigest())}),
            ("una parte menos", {k: v for k, v in self.parts.items() if k != "assay"}),
        )
        for name, parts in cases:
            with self.subTest(name):
                self.assertNotEqual(self.digest(parts).data_sha256, reference.data_sha256)

    def test_parts_from_encoders(self) -> None:
        grid = encoder.GridEncoder(header())
        grid.update(sample())
        prj = encoder.DocumentEncoder()
        prj.update(b'PROJCS["ETRS89 / UTM zone 30N"]')
        parts = {"grid": ("raster", grid.finish()), "prj": ("document", prj.finish())}
        digest = content.ContentHasher("raster", declarations=DECLARATIONS).composite(parts)
        self.assertEqual(parts["grid"][1], grid_digest().data_sha256)
        self.assertNotEqual(digest.digest().data_sha256, grid_digest().data_sha256)


class ValidationTest(unittest.TestCase):
    """RF-008-08: un lector que da algo que no tiene forma canónica única (una cabecera
    incompleta o con claves de más, filas que faltan o sobran, valores de otra clase) o que
    usa mal el normalizador se rechaza con un error claro, sin dar un hash."""

    def test_header(self) -> None:
        missing = header()
        del missing["crs"]
        cases = (
            ("falta crs", missing, ValueError),
            ("clave de más", header(rotation=0.0), ValueError),
            ("filas 0", header(rows=0), ValueError),
            ("filas booleano", header(rows=True), TypeError),
            ("columnas 2,5", header(columns=2.5), TypeError),
            ("dx 0", header(dx=0.0), ValueError),
            ("dy negativo", header(dy=-2.0), ValueError),
            ("x0 infinito", header(x0=float("inf")), ValueError),
            ("x0 NaN", header(x0=float("nan")), ValueError),
            ("x0 texto", header(x0="715000"), TypeError),
            ("celda pixel", header(cell="pixel"), ValueError),
            ("clase double", header(**{"class": "double"}), ValueError),
            ("CRS texto", header(crs="EPSG:25830"), TypeError),
            ("CRS wkt", header(crs={"wkt": "PROJCS[…]"}), ValueError),
            ("CRS 0", header(crs={"epsg": 0}), ValueError),
            ("CRS texto en epsg", header(crs={"epsg": "25830"}), TypeError),
            ("sin dato texto", header(nodata="-9999"), TypeError),
            ("sin dato booleano", header(nodata=False), TypeError),
            ("sin dato 1,5 entero", header(nodata=1.5, **{"class": "int"}), ValueError),
            ("cabecera lista", [("rows", 4)], TypeError),
        )
        for name, head, error in cases:
            with self.subTest(name), self.assertRaises(error):
                encoder.GridEncoder(head)

    def test_blocks(self) -> None:
        ints = header(**{"class": "int", "nodata": None})
        bools = header(**{"class": "bool", "nodata": None})
        too_big = np.full((4, 5), 2**63, dtype="<u8")
        cases = (
            ("columnas de menos", header(), [sample()[:, :4]], ValueError),
            ("filas de más", header(), [sample(), sample()[:1]], ValueError),
            ("filas de menos", header(), [sample()[:3]], ValueError),
            ("tres dimensiones", header(), [sample()[None]], ValueError),
            ("flotantes en enteros", ints, [sample()], TypeError),
            ("int64 en flotantes", header(), [np.nan_to_num(sample()).astype("<i8")], TypeError),
            ("objetos", header(), [sample().astype(object)], TypeError),
            ("textos", header(), [np.full((4, 5), "1")], TypeError),
            ("uint64 enorme", ints, [too_big], ValueError),
            ("2 en booleanos", bools, [np.full((4, 5), 2, dtype="<i2")], ValueError),
        )
        for name, head, blocks, error in cases:
            with self.subTest(name), self.assertRaises(error):
                content.ContentHasher("raster", declarations={}).grid(head, blocks)

    def test_hasher(self) -> None:
        cases = (
            ("tipo desconocido", ("rastre",), {"declarations": {}}, ValueError),
            ("declaraciones lista", ("raster",), {"declarations": [("crs_h", 1)]}, TypeError),
            ("declaraciones con conjunto", ("raster",), {"declarations": {"a": {1}}}, TypeError),
            ("lector sin versión", ("raster",), {"declarations": {}, "reader": "gis.geotiff"},
             ValueError),
            ("normalizador gbch/2", ("raster",), {"declarations": {}, "normalizer": "gbch/2"},
             ValueError),
        )
        for name, args, kwargs, error in cases:
            with self.subTest(name), self.assertRaises(error):
                content.ContentHasher(*args, **kwargs)

    def test_states(self) -> None:
        hasher = content.ContentHasher("raster", declarations={})
        with self.assertRaises(RuntimeError):
            hasher.digest()
        feed = hasher.begin_grid(header())
        with self.assertRaises(RuntimeError):
            hasher.digest()
        with self.assertRaises(RuntimeError):
            hasher.document([b"x"])
        feed.update(sample())
        feed.finish()
        with self.assertRaises(RuntimeError):
            feed.update(sample())
        with self.assertRaises(RuntimeError):
            hasher.grid(header(), [sample()])
        with self.assertRaises(RuntimeError):
            hasher.composite({"a": ("table", EMPTY_SHA256)})
        self.assertEqual(hasher.digest().normalizer, "gbch/1")
        failed = content.ContentHasher("raster", declarations={})
        with self.assertRaises(ValueError):
            failed.grid(header(), [sample()[:2]])
        with self.assertRaises(RuntimeError):
            failed.digest()

    def test_failed_block(self) -> None:
        ints = header(**{"class": "int", "nodata": None})
        zeros = np.zeros((4, 5), dtype="<u8")
        expected = encoder.GridEncoder(ints)
        expected.update(zeros)
        rejected = zeros.copy()
        rejected[3, 4] = 2**63
        feed = encoder.GridEncoder(ints)
        with mock.patch.object(encoder, "GRID_CHUNK_CELLS", 5), self.assertRaises(ValueError):
            feed.update(rejected)
        self.assertEqual(feed.rows_done, 0)
        feed.update(zeros)
        self.assertEqual(feed.finish(), expected.finish())

        real = encoder._float_cells
        calls: list[int] = []

        def failing(block: np.ndarray) -> np.ndarray:
            calls.append(len(block))
            if len(calls) == 2:
                raise MemoryError("simulado")
            return real(block)

        broken = encoder.GridEncoder(header())
        with (
            mock.patch.object(encoder, "GRID_CHUNK_CELLS", 5),
            mock.patch.object(encoder, "_float_cells", failing),
            self.assertRaises(MemoryError),
        ):
            broken.update(sample())
        for action in (lambda: broken.update(sample()), broken.finish):
            with self.assertRaises(RuntimeError):
                action()

    def test_document_and_composite(self) -> None:
        with self.assertRaises(TypeError):
            content.ContentHasher("document", declarations={}).document(["texto"])
        bad = (
            ("vacío", {}, ValueError),
            ("hash corto", {"a": ("table", "abc")}, ValueError),
            ("hash en mayúsculas", {"a": ("table", EMPTY_SHA256.upper())}, ValueError),
            ("tipo desconocido", {"a": ("tabla", EMPTY_SHA256)}, ValueError),
            ("nombre vacío", {"": ("table", EMPTY_SHA256)}, ValueError),
            ("lista", [("a", "table", EMPTY_SHA256)], TypeError),
        )
        for name, parts, error in bad:
            with self.subTest(name), self.assertRaises(error):
                content.ContentHasher("drillholes", declarations={}).composite(parts)

    def test_digest_values(self) -> None:
        with self.assertRaises(ValueError):
            content.ContentDigest("abc", EMPTY_SHA256, "gbch/1", "")
        with self.assertRaises(ValueError):
            content.ContentDigest(EMPTY_SHA256, EMPTY_SHA256, "", "")


# --- Entidades, filas, mallas y puntos (T06) -------------------------------------------------

content_wkb = import_geoblender("core.content.wkb")
core_numbers = import_geoblender("core.numbers")

FIELDS = {"code": "text", "area": "float", "parts": "int"}
LAYER_CRS = {"epsg": 25830}
ATTRIBUTES = {"code": "A", "area": 1.0, "parts": 1}
COLUMNS = [["hole", "text"], ["x", "float"], ["y", "float"], ["z", "float"], ["depth", "float"]]
ROWS = [
    ["S-01", 715010.0, 4378020.0, 612.5, 120.0],
    ["S-02", 715030.5, 4378041.25, 613.0, None],
    ["S-03", 715050.0, 4378060.0, 611.75, 95.5],
]
MESH_META = {
    "schema": 1,
    "kind": "solid",
    "crs_epsg": 25830,
    "closed": True,
    "oriented": True,
    "volume_m3": 166.66666666666666,
    "operation_uid": "op-0001",
}
POINT_COLUMNS = [["x", "float"], ["y", "float"], ["z", "float"], ["class", "int"]]


def polygon(x0: float, y0: float, side: float = 10.0) -> tuple[str, object]:
    return ("Polygon", [wkb_build.square(x0, y0, side)])


def sample_features() -> list[tuple[bytes | None, dict[str, object]]]:
    """Tres parcelas: dos cuadrados (uno con un atributo nulo) y una sin geometría."""
    return [
        (wkb_build.iso_le(polygon(715000.0, 4378000.0)),
         {"code": "P-01", "area": 100.0, "parts": 1}),
        (wkb_build.iso_le(polygon(715020.0, 4378000.0)),
         {"code": "P-02", "area": 100.0, "parts": None}),
        (None, {"code": "P-03", "area": None, "parts": 0}),
    ]


def feature_digest(
    features: object = None,
    *,
    fields: object = FIELDS,
    dims: str = "XY",
    crs: object = LAYER_CRS,
    declarations: dict[str, object] | None = None,
) -> object:
    """El ``ContentDigest`` de una capa (por defecto, :func:`sample_features`)."""
    hasher = content.ContentHasher(
        "vector",
        declarations=DECLARATIONS if declarations is None else declarations,
        reader="test.layer@1",
    )
    items = sample_features() if features is None else features
    return hasher.features(fields, dims, crs, items).digest()


def row_digest(
    rows: object = None, *, ordered: bool = False, columns: object = COLUMNS
) -> object:
    hasher = content.ContentHasher("table", declarations=DECLARATIONS, reader="test.table@1")
    return hasher.rows(columns, ordered, ROWS if rows is None else rows).digest()


def tetrahedron() -> dict[str, np.ndarray]:
    """Un sólido de 4 vértices (float64 absolutos) y 4 caras (int32), con ``vertex_source``."""
    return {
        "vertices": np.array(
            [
                [715000.0, 4378000.0, 600.0],
                [715010.0, 4378000.0, 600.0],
                [715000.0, 4378010.0, 600.0],
                [715000.0, 4378000.0, 610.0],
            ]
        ),
        "faces": np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]], dtype="<i4"),
        "vertex_source": np.array([0, 0, 1, 3], dtype="u1"),
    }


def mesh_digest(arrays: object = None, meta: object = None) -> object:
    hasher = content.ContentHasher("mesh", declarations=DECLARATIONS, reader="test.mesh@1")
    return hasher.mesh(
        tetrahedron() if arrays is None else arrays, MESH_META if meta is None else meta
    ).digest()


def cloud(count: int = 12) -> dict[str, np.ndarray]:
    """Una nube de ``count`` puntos: x e y en float64, z en float32 y la clase en uint8."""
    rng = np.random.default_rng(6)
    return {
        "x": 715000.0 + rng.integers(0, 4000, count) / 4,
        "y": 4378000.0 + rng.integers(0, 4000, count) / 4,
        "z": (600 + rng.integers(0, 400, count) / 8).astype("<f4"),
        "class": rng.integers(1, 7, count).astype("<u1"),
    }


def point_digest(
    blocks: object, *, ordered: bool = True, columns: object = POINT_COLUMNS
) -> object:
    hasher = content.ContentHasher("point_cloud", declarations=DECLARATIONS)
    return hasher.points(columns, ordered, blocks).digest()


def pick(columns: dict[str, np.ndarray], index: object) -> dict[str, np.ndarray]:
    """Los puntos ``index`` (un corte o una permutación) de cada columna."""
    return {name: values[index] for name, values in columns.items()}


class StreamLayoutTest(unittest.TestCase):
    """RF-008-08; ADR-0024 §2 y §4: entidades, filas, mallas y nubes de puntos escritas a mano
    (``struct`` y ``hashlib``, sin el normalizador) dan los mismos hashes. Cada tipo es su
    cabecera en JSON canónico con su etiqueta (``FEAT``, ``TABL``, ``MESH``, ``PNTS``) y una
    sección ``VALS``: los sha256 de las entidades ordenados; los de las filas, en orden o
    ordenados; los arrays de la malla en float64 o int64 por nombre; el sha256 de los
    registros de los puntos (float64 o int64 *little-endian*, punto a punto)."""

    def test_features_stream(self) -> None:
        ring = [715000.0, 4378000.0, 715010.0, 4378000.0, 715010.0, 4378010.0,
                715000.0, 4378000.0]
        polygon_wkb = struct.pack("<BIII8d", 1, 3, 1, 4, *ring)
        empty_point = struct.pack("<BI2Q", 1, 1, CANONICAL_NAN_BITS, CANONICAL_NAN_BITS)
        features = [
            (polygon_wkb, {"code": "A", "area": 50.0, "parts": 1}),
            (None, {"code": "B", "area": None, "parts": 2}),
            (empty_point, {"code": "C", "area": float("nan"), "parts": None}),
        ]
        digest = feature_digest(features)
        entities = sorted(
            [
                hashlib.sha256(polygon_wkb + b'{"area":50.0,"code":"A","parts":1}').digest(),
                hashlib.sha256(b"\x00" + b'{"area":null,"code":"B","parts":2}').digest(),
                hashlib.sha256(
                    empty_point + b'{"area":{"nan":true},"code":"C","parts":null}'
                ).digest(),
            ]
        )
        head = (
            b'{"count":3,"crs":{"epsg":25830},"dims":"XY","fields":[["area","float"],'
            b'["code","text"],["parts","int"]]}'
        )
        data = hashlib.sha256(
            _section(b"FEAT", head) + _section(b"VALS", b"".join(entities))
        ).hexdigest()
        self.assertEqual(digest.data_sha256, data)
        self.assertEqual(
            digest.content_sha256, content.content_sha256("vector", DECLARATIONS, data)
        )

    def test_rows_stream(self) -> None:
        columns = [["hole", "text"], ["z", "float"], ["n", "int"]]
        rows = [["S-02", None, 4], ["S-01", 612.5, 3]]
        each = [
            hashlib.sha256(b'["S-02",null,4]').digest(),
            hashlib.sha256(b'["S-01",612.5,3]').digest(),
        ]
        for ordered, flag, values in ((True, b"true", each), (False, b"false", sorted(each))):
            with self.subTest(ordered=ordered):
                hasher = content.ContentHasher("table", declarations={})
                digest = hasher.rows(columns, ordered, rows).digest()
                head = (
                    b'{"columns":[["hole","text"],["z","float"],["n","int"]],"count":2,'
                    b'"ordered":' + flag + b"}"
                )
                stream = _section(b"TABL", head) + _section(b"VALS", b"".join(values))
                self.assertEqual(digest.data_sha256, hashlib.sha256(stream).hexdigest())

    def test_mesh_stream(self) -> None:
        arrays = tetrahedron()
        digest = mesh_digest(arrays)
        head = (
            b'{"arrays":[["faces","int",[4,3]],["vertex_source","int",[4]],'
            b'["vertices","float",[4,3]]],"meta":{"closed":true,"crs_epsg":25830,'
            b'"kind":"solid"}}'
        )
        values = (
            arrays["faces"].astype("<i8").tobytes()
            + arrays["vertex_source"].astype("<i8").tobytes()
            + arrays["vertices"].astype("<f8").tobytes()
        )
        stream = _section(b"MESH", head) + _section(b"VALS", values)
        self.assertEqual(digest.data_sha256, hashlib.sha256(stream).hexdigest())

    def test_points_stream(self) -> None:
        points = [
            (715000.5, 4378000.25, 612.0, 2),
            (715001.0, 4378000.0, -0.0, 6),
            (715000.0, 4378002.0, 611.5, 2),
        ]
        block = {
            "x": np.array([p[0] for p in points]),
            "y": np.array([p[1] for p in points]),
            "z": np.array([p[2] for p in points], dtype="<f4"),
            "class": np.array([p[3] for p in points], dtype="<u1"),
        }
        records = [struct.pack("<dddq", x, y, z + 0.0, c) for x, y, z, c in points]
        for ordered, flag, chosen in (
            (True, b"true", records),
            (False, b"false", sorted(records)),
        ):
            with self.subTest(ordered=ordered):
                digest = point_digest([block], ordered=ordered)
                head = (
                    b'{"columns":[["x","float"],["y","float"],["z","float"],["class","int"]],'
                    b'"count":3,"ordered":' + flag + b"}"
                )
                inner = hashlib.sha256(b"".join(chosen)).digest()
                stream = _section(b"PNTS", head) + _section(b"VALS", inner)
                self.assertEqual(digest.data_sha256, hashlib.sha256(stream).hexdigest())


class FeatureRulesTest(unittest.TestCase):
    """RF-008-08; ADR-0024 §4 (fila «Vectorial»): las entidades son un multiconjunto (ni su
    orden ni su número interno cuentan; dos iguales cuentan dos veces); un vértice movido
    1 mm, un atributo, el CRS de la capa, las dimensiones o los campos y sus tipos cambian el
    hash; el WKB *big endian* y el extendido dan lo mismo que el ISO; la geometría nula (byte
    ``0x00``), la vacía (su WKB ISO vacío; un punto vacío con NaN canónicos) y el atributo nulo
    (``null``) son distintos entre sí y de cualquier valor."""

    def test_order_does_not_count(self) -> None:
        reference = feature_digest()
        features = sample_features()
        for name, items in (
            ("al revés", features[::-1]),
            ("rotadas", features[1:] + features[:1]),
        ):
            with self.subTest(name):
                self.assertEqual(feature_digest(items), reference)

    def test_duplicates_count_twice(self) -> None:
        features = sample_features()
        first, second = features[0], features[1]
        self.assertNotEqual(
            feature_digest(features + [first]).data_sha256, feature_digest().data_sha256
        )
        self.assertNotEqual(
            feature_digest([first, first, second]).data_sha256,
            feature_digest([first, second, second]).data_sha256,
        )
        self.assertNotEqual(
            feature_digest([first, first]).data_sha256, feature_digest([first]).data_sha256
        )

    def test_vertex_moved_1_mm(self) -> None:
        reference = feature_digest()
        ring = wkb_build.square(715000.0, 4378000.0, 10.0)
        for index, axis in ((2, 0), (2, 1), (0, 1)):
            moved = [list(point) for point in ring]
            moved[index][axis] += 0.001
            if index == 0:
                moved[-1][axis] += 0.001  # el anillo sigue cerrado
            features = sample_features()
            features[0] = (wkb_build.iso_le(("Polygon", [moved])), features[0][1])
            with self.subTest(vertex=index, axis=axis):
                digest = feature_digest(features)
                self.assertNotEqual(digest.data_sha256, reference.data_sha256)
                self.assertNotEqual(digest.content_sha256, reference.content_sha256)

    def test_wkb_variants(self) -> None:
        hole = [[715052.0, 4378002.0], [715052.0, 4378003.0], [715053.0, 4378003.0],
                [715052.0, 4378002.0]]
        line_zm = [[0.0, 0.0, 1.0, 2.0], [1.0, 1.0, 1.0, 3.0], [2.0, 0.0, 1.0, 4.0]]
        cases = (
            ("XY", ("MultiPolygon", [
                polygon(715000.0, 4378000.0),
                ("Polygon", [wkb_build.square(715050.0, 4378000.0, 5.0), hole]),
            ])),
            ("XYZ", ("LineString", [[715000.0, 4378000.0, 612.5], [715003.0, 4378004.0, 613.0]])),
            ("XYM", ("Point", [715000.0, 4378000.0, 7.5])),
            ("XYZM", ("GeometryCollection", [
                ("Point", [1.0, 2.0, 3.0, 4.0]),
                ("LineString", line_zm),
                ("MultiPoint", [("Point", [5.0, 6.0, 7.0, 8.0]), ("Point", None)]),
            ])),
            ("XY", ("CompoundCurve", [
                ("CircularString", [[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]]),
                ("LineString", [[2.0, 0.0], [0.0, 0.0]]),
            ])),
            ("XYZ", ("MultiSurface", [
                ("CurvePolygon", [("LineString", [p + [9.0] for p in wkb_build.square(0, 0, 1)])]),
                ("PolyhedralSurface", [("Polygon", [wkb_build.square(0, 0, 1, z=1.0)])]),
                ("TIN", [("Triangle", [[[0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0],
                                        [0.0, 0.0, 1.0]]])]),
            ])),
            ("XY", ("MultiCurve", [("LineString", [[0.0, 0.0], [1.0, 1.0]])])),
        )
        for dims, geometry in cases:
            iso = wkb_build.iso_le(geometry, dims)
            reference = feature_digest([(iso, ATTRIBUTES)], dims=dims)
            variants = {
                "ISO big endian": wkb_build.encode(geometry, dims, order=">"),
                "extendido": wkb_build.encode(geometry, dims, flavor="ewkb"),
                "extendido big endian con SRID": wkb_build.encode(
                    geometry, dims, order=">", flavor="ewkb", srid=25830
                ),
                "partes en otro orden de bytes": wkb_build.encode(geometry, dims, parts_order=">"),
                "bytearray": bytearray(iso),
                "memoryview": memoryview(iso),
            }
            self.assertEqual(content_wkb.canonical_wkb(iso, dims), iso)
            for name, wkb in variants.items():
                with self.subTest(geometry=geometry[0], dims=dims, variant=name):
                    self.assertEqual(content_wkb.canonical_wkb(wkb, dims), iso)
                    self.assertEqual(feature_digest([(wkb, ATTRIBUTES)], dims=dims), reference)

    def test_canonical_coordinates(self) -> None:
        zero = wkb_build.iso_le(("Point", [0.0, 4378000.0]))
        negative = wkb_build.encode(("Point", [-0.0, 4378000.0]), order=">")
        self.assertEqual(content_wkb.canonical_wkb(negative, "XY"), zero)
        canonical = struct.pack("<BI2Q", 1, 1, CANONICAL_NAN_BITS, CANONICAL_NAN_BITS)
        self.assertEqual(content_wkb.canonical_wkb(wkb_build.iso_le(("Point", None)), "XY"),
                         canonical)
        for bits in NAN64:
            nan = _f64(bits)
            for order, flag in (("<", 1), (">", 0)):
                with self.subTest(bits=f"{bits:016x}", order=order):
                    raw = struct.pack(f"{order}BI2d", flag, 1, nan, nan)
                    self.assertEqual(content_wkb.canonical_wkb(raw, "XY"), canonical)

    def test_null_empty_and_null_attribute(self) -> None:
        geometries = {
            "nula": None,
            "punto vacío": wkb_build.iso_le(("Point", None)),
            "polígono vacío": wkb_build.iso_le(("Polygon", [])),
            "multipolígono vacío": wkb_build.iso_le(("MultiPolygon", [])),
            "línea vacía": wkb_build.iso_le(("LineString", [])),
            "colección vacía": wkb_build.iso_le(("GeometryCollection", [])),
            "polígono con un anillo vacío": wkb_build.iso_le(("Polygon", [[]])),
            "punto (0, 0)": wkb_build.iso_le(("Point", [0.0, 0.0])),
        }
        found = {
            name: feature_digest([(wkb, ATTRIBUTES)]).data_sha256
            for name, wkb in geometries.items()
        }
        self.assertEqual(len(set(found.values())), len(geometries), found)
        empty_be = wkb_build.encode(("Polygon", []), order=">", flavor="ewkb", srid=25830)
        self.assertEqual(
            feature_digest([(empty_be, ATTRIBUTES)]).data_sha256, found["polígono vacío"]
        )
        values = {"nulo": None, "cero": 0.0, "NaN": float("nan"), "−0,0": -0.0}
        attribute = {
            name: feature_digest([(None, {**ATTRIBUTES, "area": value})]).data_sha256
            for name, value in values.items()
        }
        self.assertEqual(attribute["cero"], attribute["−0,0"])
        self.assertEqual(len({attribute[name] for name in ("nulo", "cero", "NaN")}), 3)

    def test_layer_fields_and_dims(self) -> None:
        reference = feature_digest()
        features = sample_features()
        renamed = [
            (geometry, {("codigo" if key == "code" else key): value
                        for key, value in attributes.items()})
            for geometry, attributes in features
        ]
        changed = [features[0], (features[1][0], {**features[1][1], "code": "P-2"}), features[2]]
        cases = (
            ("CRS de la capa null", feature_digest(crs=None)),
            ("CRS de la capa 25829", feature_digest(crs={"epsg": 25829})),
            ("dimensiones XYZ", feature_digest(dims="XYZ")),
            ("campo renombrado", feature_digest(
                renamed, fields={"codigo": "text", "area": "float", "parts": "int"})),
            ("tipo de un campo", feature_digest(fields={**FIELDS, "parts": "float"})),
            ("un atributo", feature_digest(changed)),
            ("una entidad menos", feature_digest(features[:2])),
            ("capa vacía", feature_digest([])),
        )
        for name, digest in cases:
            with self.subTest(name):
                self.assertNotEqual(digest.data_sha256, reference.data_sha256)
                self.assertNotEqual(digest.content_sha256, reference.content_sha256)
        for name, fields in (
            ("campos en otro orden", dict(reversed(list(FIELDS.items())))),
            ("campos en pares", [[key, value] for key, value in FIELDS.items()]),
            ("campos en tuplas", tuple((key, value) for key, value in FIELDS.items())),
        ):
            with self.subTest(name):
                self.assertEqual(feature_digest(fields=fields), reference)
        self.assertEqual(feature_digest(crs={"epsg": np.int32(25830)}), reference)

    def test_attribute_values(self) -> None:
        fields = {"f": "float", "i": "int", "b": "bool", "t": "text", "d": "date",
                  "dt": "datetime", "blob": "blob"}
        base = {"f": 100.0, "i": 3, "b": True, "t": "Límite", "d": dt.date(2026, 10, 8),
                "dt": dt.datetime(2026, 10, 8, 10, 0, tzinfo=dt.UTC), "blob": b"\x00\x01"}

        def digest(**changes: object) -> object:
            return feature_digest([(None, {**base, **changes})], fields=fields)

        reference = digest()
        same = {
            "flotante entero": {"f": 100},
            "flotante float32": {"f": np.float32(100.0)},
            "flotante entero de numpy": {"f": np.int64(100)},
            "entero 3,0": {"i": 3.0},
            "entero de numpy": {"i": np.int16(3)},
            "booleano 1": {"b": 1},
            "booleano de numpy": {"b": np.bool_(True)},
            "fecha en texto": {"d": "2026-10-08"},
            "fecha y hora en texto": {"dt": "2026-10-08T10:00:00Z"},
            "fecha y hora en otra zona": {"dt": "2026-10-08T12:00:00+02:00"},
            "fecha y hora con milisegundos": {"dt": "2026-10-08T10:00:00.000Z"},
            "binario bytearray": {"blob": bytearray(b"\x00\x01")},
            "binario memoryview": {"blob": memoryview(b"\x00\x01")},
        }
        for name, changes in same.items():
            with self.subTest(name):
                self.assertEqual(digest(**changes), reference)
        different = {
            "texto descompuesto": {"t": "Li" + chr(0x301) + "mite"},
            "texto con espacio": {"t": "Límite "},
            "flotante +1 ulp": {"f": float(np.nextafter(100.0, np.inf))},
            "booleano falso": {"b": False},
            "fecha": {"d": dt.date(2026, 10, 9)},
            "fecha y hora +1 ms": {"dt": "2026-10-08T10:00:00.001Z"},
            "binario": {"blob": b"\x00\x02"},
            "entero 4": {"i": 4},
        }
        for name, changes in different.items():
            with self.subTest(name):
                self.assertNotEqual(digest(**changes).data_sha256, reference.data_sha256)

    def test_dims_kept(self) -> None:
        xy = [[715000.0, 4378000.0], [715003.0, 4378004.0]]
        xyz = [point + [612.5] for point in xy]
        xym = [point + [7.0] for point in xy]
        xyzm = [point + [7.0] for point in xyz]
        line = ("LineString",)
        cases = (
            ("Z de más en una capa XY", ("XYZ", xyz), "XY", ("XY", xy)),
            ("M de más en una capa XYZ", ("XYZM", xyzm), "XYZ", ("XYZ", xyz)),
            ("Z de más en una capa XYM", ("XYZM", xyzm), "XYM", ("XYM", xym)),
            ("sin Z en una capa XYZ", ("XY", xy), "XYZ", ("XY", xy)),
            ("sin M en una capa XYZM", ("XYZ", xyz), "XYZM", ("XYZ", xyz)),
        )
        for name, (source_dims, points), dims, (kept_dims, kept) in cases:
            with self.subTest(name):
                source = wkb_build.encode(line + (points,), source_dims, order=">")
                expected = wkb_build.iso_le(line + (kept,), kept_dims)
                self.assertEqual(content_wkb.canonical_wkb(source, dims), expected)
        nested = ("GeometryCollection", [("Point", [1.0, 2.0, 3.0, 4.0]), ("Point", None)])
        flat = ("GeometryCollection", [("Point", [1.0, 2.0]), ("Point", None)])
        self.assertEqual(
            content_wkb.canonical_wkb(wkb_build.encode(nested, "XYZM", flavor="ewkb"), "XY"),
            wkb_build.iso_le(flat),
        )

    def test_declarations_change_only_the_content(self) -> None:
        reference = feature_digest()
        other = feature_digest(declarations={**DECLARATIONS, "crs_h": {"epsg": 25829}})
        self.assertEqual(other.data_sha256, reference.data_sha256)
        self.assertNotEqual(other.content_sha256, reference.content_sha256)

    def test_push_form(self) -> None:
        reference = feature_digest()
        features = sample_features()
        hasher = content.ContentHasher("vector", declarations=DECLARATIONS, reader="test.layer@1")
        feed = hasher.begin_features(FIELDS, "XY", LAYER_CRS)
        feed.add(*features[0])
        feed.update(iter(features[1:]))
        self.assertEqual(feed.count, 3)
        self.assertEqual(feed.finish(), reference.data_sha256)
        self.assertEqual(hasher.digest(), reference)
        alone = encoder.FeatureEncoder(FIELDS, "XY", LAYER_CRS)
        alone.update(features)
        self.assertEqual(alone.finish(), reference.data_sha256)

    def test_input_is_not_modified(self) -> None:
        features = sample_features()
        raw = bytearray(features[0][0])
        attributes = {**features[0][1], "area": np.float32(100.0)}
        frozen = (bytes(raw), dict(attributes))
        fields = dict(FIELDS)
        feature_digest([(raw, attributes)], fields=fields)
        self.assertEqual((bytes(raw), attributes), frozen)
        self.assertEqual(fields, FIELDS)


class RowRulesTest(unittest.TestCase):
    """RF-008-08; ADR-0024 §4 (fila «Tabla»): el orden de las filas solo cuenta con
    ``ordered = True``; dos filas iguales cuentan dos veces; los valores llegan ya
    interpretados («1,5» y «1.50» de un CSV son el mismo número) y se convierten al tipo
    declarado de su columna; un valor, un nulo, el nombre, el tipo o el orden de una columna
    cambian el hash."""

    def test_order_only_with_ordered(self) -> None:
        unordered = row_digest(ordered=False)
        self.assertEqual(row_digest(ROWS[::-1], ordered=False), unordered)
        ordered = row_digest(ordered=True)
        self.assertNotEqual(row_digest(ROWS[::-1], ordered=True).data_sha256,
                            ordered.data_sha256)
        self.assertEqual(row_digest([tuple(row) for row in ROWS], ordered=True), ordered)
        self.assertNotEqual(ordered.data_sha256, unordered.data_sha256)

    def test_duplicates_count_twice(self) -> None:
        for ordered in (False, True):
            with self.subTest(ordered=ordered):
                self.assertNotEqual(
                    row_digest(ROWS + ROWS[:1], ordered=ordered).data_sha256,
                    row_digest(ordered=ordered).data_sha256,
                )

    def test_interpreted_values(self) -> None:
        columns = [["hole", "text"], ["grade", "float"], ["count", "int"]]
        texts = ("1,5", "1.50", "1,500", " 1.5 ")
        digests = {
            text: row_digest(
                [["S-01", core_numbers.parse_decimal(text, obj="CSV", field="ley"), 2]],
                columns=columns,
            )
            for text in texts
        }
        self.assertEqual(len(set(digests.values())), 1, digests)
        reference = row_digest(ordered=True)
        names = [name for name, _ in COLUMNS]
        same = {
            "entero en una columna de flotantes": [[*ROWS[0][:4], 120], *ROWS[1:]],
            "float32": [[*ROWS[0][:3], np.float32(612.5), ROWS[0][4]], *ROWS[1:]],
            "filas como diccionarios": [dict(zip(names, row, strict=True)) for row in ROWS],
            "diccionarios en otro orden": [
                dict(reversed(list(zip(names, row, strict=True)))) for row in ROWS
            ],
        }
        for name, rows in same.items():
            with self.subTest(name):
                self.assertEqual(row_digest(rows, ordered=True), reference)

    def test_changes(self) -> None:
        reference = row_digest()
        swapped = [["hole", "text"], ["y", "float"], ["x", "float"], ["z", "float"],
                   ["depth", "float"]]
        cases = (
            ("una cota", [ROWS[0], [*ROWS[1][:3], 613.01, None], ROWS[2]], COLUMNS),
            ("un nulo", [[*ROWS[0][:4], None], *ROWS[1:]], COLUMNS),
            ("columna renombrada", ROWS, [["sondeo", "text"], *COLUMNS[1:]]),
            ("columnas en otro orden", [[r[0], r[2], r[1], r[3], r[4]] for r in ROWS], swapped),
            ("tabla vacía", [], COLUMNS),
        )
        for name, rows, columns in cases:
            with self.subTest(name):
                self.assertNotEqual(row_digest(rows, columns=columns).data_sha256,
                                    reference.data_sha256)
        as_float = row_digest([[*row[:4], 100.0] for row in ROWS])
        as_int = row_digest([[*row[:4], 100] for row in ROWS],
                            columns=[*COLUMNS[:4], ["depth", "int"]])
        self.assertNotEqual(as_int.data_sha256, as_float.data_sha256)

    def test_push_form(self) -> None:
        reference = row_digest(ordered=True)
        hasher = content.ContentHasher("table", declarations=DECLARATIONS, reader="test.table@1")
        feed = hasher.begin_rows(COLUMNS, True)
        feed.add(ROWS[0])
        feed.update(ROWS[1:])
        self.assertEqual(feed.count, 3)
        feed.finish()
        self.assertEqual(hasher.digest(), reference)


class MeshRulesTest(unittest.TestCase):
    """RF-008-08; ADR-0024 §4 (fila «Malla»): los arrays van por su nombre, con su clase y su
    forma, ``vertices`` en float64 canónico y las caras y demás enteros en int64; el orden de
    los vértices y de las caras cuenta; de ``meta`` solo son contenido ``kind``, ``crs_epsg`` y
    ``closed`` (una clave que falta es ``null``): las demás no cuentan."""

    def test_meta_keys_that_are_not_content(self) -> None:
        reference = mesh_digest()
        cases = {
            "solo las de contenido": {
                key: MESH_META[key] for key in ("kind", "crs_epsg", "closed")
            },
            "volumen": {**MESH_META, "volume_m3": 1.0},
            "operación": {**MESH_META, "operation_uid": "op-0002"},
            "esquema": {**MESH_META, "schema": 2},
            "orientación": {**MESH_META, "oriented": False},
            "tipo de superficie": {**MESH_META, "surface_type": "tin"},
            "triangulador": {**MESH_META, "triangulator": "delaunay@1"},
        }
        for name, meta in cases.items():
            with self.subTest(name):
                self.assertEqual(mesh_digest(meta=meta), reference)

    def test_meta_keys_that_are_content(self) -> None:
        reference = mesh_digest()
        cases = {
            "kind": {**MESH_META, "kind": "surface"},
            "crs_epsg": {**MESH_META, "crs_epsg": 25829},
            "closed": {**MESH_META, "closed": False},
            "sin closed": {key: value for key, value in MESH_META.items() if key != "closed"},
            "sin meta": {},
        }
        for name, meta in cases.items():
            with self.subTest(name):
                self.assertNotEqual(mesh_digest(meta=meta).data_sha256, reference.data_sha256)
        self.assertEqual(mesh_digest(meta={"kind": "solid"}),
                         mesh_digest(meta={"kind": "solid", "crs_epsg": None, "closed": None}))
        self.assertEqual(mesh_digest(meta={**MESH_META, "crs_epsg": np.int64(25830),
                                           "closed": np.bool_(True)}), reference)

    def test_order_and_values_count(self) -> None:
        reference = mesh_digest()
        arrays = tetrahedron()
        order = [3, 2, 1, 0]
        renumbered = {
            "vertices": arrays["vertices"][order],
            "faces": np.array([[order.index(i) for i in face] for face in arrays["faces"]],
                              dtype="<i4"),
            "vertex_source": arrays["vertex_source"][order],
        }
        moved = tetrahedron()
        moved["vertices"][3, 2] += 0.001
        cases = {
            "vértices renumerados": renumbered,
            "caras en otro orden": {**arrays, "faces": arrays["faces"][::-1].copy()},
            "un vértice 1 mm": moved,
            "caras en una fila": {**arrays, "faces": arrays["faces"].reshape(-1)},
            "array renombrado": {**{k: v for k, v in arrays.items() if k != "vertex_source"},
                                 "vertex_kind": arrays["vertex_source"]},
            "sin vertex_source": {k: v for k, v in arrays.items() if k != "vertex_source"},
            "vértices enteros": {**arrays, "vertices": arrays["vertices"].astype("<i8")},
        }
        for name, changed in cases.items():
            with self.subTest(name):
                self.assertNotEqual(mesh_digest(changed).data_sha256, reference.data_sha256)

    def test_same_values_written_otherwise(self) -> None:
        reference = mesh_digest()
        arrays = tetrahedron()
        cases = {
            "vértices en float32": {**arrays, "vertices": arrays["vertices"].astype("<f4")},
            "vértices big endian": {**arrays, "vertices": arrays["vertices"].astype(">f8")},
            "vértices en orden Fortran": {**arrays,
                                          "vertices": np.asfortranarray(arrays["vertices"])},
            "caras en int64": {**arrays, "faces": arrays["faces"].astype("<i8")},
            "caras en uint16": {**arrays, "faces": arrays["faces"].astype("<u2")},
            "arrays en otro orden": dict(reversed(list(arrays.items()))),
        }
        for name, changed in cases.items():
            with self.subTest(name):
                self.assertEqual(mesh_digest(changed), reference)
        odd = {"vertices": np.array([[-0.0, 1.0, _f64(0xFFF8000000000001)]])}
        canonical = {"vertices": np.array([[0.0, 1.0, np.nan]])}
        self.assertEqual(mesh_digest(odd, {}), mesh_digest(canonical, {}))
        with mock.patch.object(encoder, "GRID_CHUNK_CELLS", 2):
            self.assertEqual(mesh_digest(), reference)


class PointRulesTest(unittest.TestCase):
    """RF-008-08; ADR-0024 §4 (fila «Nube de puntos»): las columnas en float64 o int64, por
    bloques; los bloques, su forma (columnas o array estructurado) y los trozos internos no
    cuentan; float32 = float64, NaN canónico y −0,0 = 0,0; con ``ordered = True`` (por
    defecto) el orden de los puntos cuenta, y sin él, no; dos puntos iguales cuentan dos
    veces; el orden de las columnas declaradas, sí."""

    def setUp(self) -> None:
        self.points = cloud()
        self.reference = point_digest([self.points])

    def test_blocks_do_not_count(self) -> None:
        points = self.points
        structured = np.zeros(12, dtype=[("class", "u1"), ("x", "<f8"), ("y", "<f8"), ("z", "<f4")])
        for name in points:
            structured[name] = points[name]
        cases = {
            "en tres bloques": [pick(points, slice(0, 5)), pick(points, slice(5, 5)),
                                pick(points, slice(5, 12))],
            "punto a punto": (pick(points, slice(i, i + 1)) for i in range(12)),
            "array estructurado": [structured],
            "columnas en otro orden": [dict(reversed(list(points.items())))],
            "listas": [{name: values.tolist() for name, values in points.items()}],
        }
        for name, blocks in cases.items():
            with self.subTest(name):
                self.assertEqual(point_digest(blocks), self.reference)
        unordered = point_digest([points], ordered=False)
        for cells in (1, 4, 5, 1000):
            with self.subTest(cells=cells), mock.patch.object(encoder, "GRID_CHUNK_CELLS", cells):
                self.assertEqual(point_digest([points]), self.reference)
                self.assertEqual(point_digest([points], ordered=False), unordered)

    def test_order(self) -> None:
        permutation = np.random.default_rng(1).permutation(12)
        shuffled = pick(self.points, permutation)
        self.assertNotEqual(point_digest([shuffled]).data_sha256, self.reference.data_sha256)
        unordered = point_digest([self.points], ordered=False)
        self.assertEqual(point_digest([shuffled], ordered=False), unordered)
        self.assertEqual(
            point_digest([pick(shuffled, slice(0, 7)), pick(shuffled, slice(7, 12))],
                         ordered=False),
            unordered,
        )
        self.assertNotEqual(unordered.data_sha256, self.reference.data_sha256)
        doubled = pick(self.points, np.r_[np.arange(12), 0])
        self.assertNotEqual(point_digest([doubled], ordered=False).data_sha256,
                            unordered.data_sha256)

    def test_values(self) -> None:
        points = self.points
        same = {
            "z en float64": {**points, "z": points["z"].astype("<f8")},
            "clase en int64": {**points, "class": points["class"].astype("<i8")},
            "x big endian": {**points, "x": points["x"].astype(">f8")},
        }
        for name, block in same.items():
            with self.subTest(name):
                self.assertEqual(point_digest([block]), self.reference)
        odd = {"x": np.array([-0.0, 1.0]), "y": np.array([_f64(0x7FF0000000000001), 2.0]),
               "z": np.array([1.0, 2.0], dtype="<f4"), "class": np.array([1, 2], dtype="u1")}
        canonical = {**odd, "x": np.array([0.0, 1.0]), "y": np.array([np.nan, 2.0])}
        self.assertEqual(point_digest([odd]), point_digest([canonical]))
        moved = {**points, "z": points["z"].copy()}
        moved["z"][4] = np.nextafter(moved["z"][4], np.float32(np.inf))
        swapped = [["y", "float"], ["x", "float"], ["z", "float"], ["class", "int"]]
        changed = {
            "una cota +1 ulp": point_digest([moved]),
            "columnas declaradas en otro orden": point_digest([points], columns=swapped),
            "clase como flotante": point_digest(
                [points], columns=[*POINT_COLUMNS[:3], ["class", "float"]]),
            "un punto menos": point_digest([pick(points, slice(0, 11))]),
        }
        for name, digest in changed.items():
            with self.subTest(name):
                self.assertNotEqual(digest.data_sha256, self.reference.data_sha256)

    def test_push_form(self) -> None:
        hasher = content.ContentHasher("point_cloud", declarations=DECLARATIONS)
        feed = hasher.begin_points(POINT_COLUMNS)
        feed.update(pick(self.points, slice(0, 8)))
        feed.update(pick(self.points, slice(8, 12)))
        self.assertEqual(feed.count, 12)
        feed.finish()
        self.assertEqual(hasher.digest(), self.reference)


class NewTypesValidationTest(unittest.TestCase):
    """RF-008-08: lo que no tiene forma canónica única —un WKB truncado, con bytes de más o de
    un tipo desconocido, un atributo que no es de su tipo declarado o que falta, una fila de
    otra longitud, columnas o arrays de otra clase, un ``meta`` mal formado— se rechaza con un
    error claro, sin dar un hash; un fallo a medias deja el codificador inservible."""

    def features_error(self, items: object, fields: object = FIELDS) -> None:
        content.ContentHasher("vector", declarations={}).features(fields, "XY", None, items)

    def test_layer(self) -> None:
        cases = (
            ("dimensiones XYZMM", (FIELDS, "XYZMM", None), ValueError),
            ("dimensiones en minúsculas", (FIELDS, "xy", None), ValueError),
            ("campo repetido", ([["a", "text"], ["a", "int"]], "XY", None), ValueError),
            ("tipo de campo desconocido", ({"a": "double"}, "XY", None), ValueError),
            ("nombre vacío", ({"": "text"}, "XY", None), ValueError),
            ("campos en un texto", ("abc", "XY", None), TypeError),
            ("par de tres", ([["a", "text", 1]], "XY", None), ValueError),
            ("CRS en texto", (FIELDS, "XY", "EPSG:25830"), TypeError),
            ("CRS 0", (FIELDS, "XY", {"epsg": 0}), ValueError),
        )
        for name, args, error in cases:
            with self.subTest(name), self.assertRaises(error):
                encoder.FeatureEncoder(*args)

    def test_features(self) -> None:
        wkb = sample_features()[0][0]
        attributes = sample_features()[0][1]
        point = struct.pack("<BI2d", 1, 1, 1.0, 2.0)
        cases = (
            ("geometría en texto", ("POINT (1 2)", attributes), TypeError),
            ("falta un atributo", (wkb, {"code": "A", "area": 1.0}), ValueError),
            ("atributo de más", (wkb, {**attributes, "x": 1}), ValueError),
            ("atributos en lista", (wkb, ["A", 1.0, 1]), TypeError),
            ("entidad sin atributos", (wkb,), ValueError),
            ("texto en un flotante", (None, {**attributes, "area": "100"}), TypeError),
            ("1,5 en un entero", (None, {**attributes, "parts": 1.5}), ValueError),
            ("NaN en un entero", (None, {**attributes, "parts": float("nan")}), ValueError),
            ("booleano en un entero", (None, {**attributes, "parts": True}), TypeError),
            ("booleano en un flotante", (None, {**attributes, "area": False}), TypeError),
            ("número en un texto", (None, {**attributes, "code": 5}), TypeError),
            ("WKB vacío", (b"", attributes), ValueError),
            ("WKB truncado", (wkb[:-1], attributes), ValueError),
            ("bytes de más", (wkb + b"\x00", attributes), ValueError),
            ("orden de bytes 2", (b"\x02" + wkb[1:], attributes), ValueError),
            ("tipo 13", (struct.pack("<BI", 1, 13), attributes), ValueError),
            ("tipo 0", (struct.pack("<BI2d", 1, 0, 1.0, 2.0), attributes), ValueError),
            ("tipo 4001", (struct.pack("<BI2d", 1, 4001, 1.0, 2.0), attributes), ValueError),
            ("ISO y extendido a la vez",
             (struct.pack("<BI3d", 1, 1001 | 0x80000000, 1.0, 2.0, 3.0), attributes), ValueError),
            ("número de puntos enorme", (struct.pack("<BII", 1, 2, 0xFFFFFFFF), attributes),
             ValueError),
            ("número de partes enorme", (struct.pack("<BII", 1, 7, 0xFFFFFFFF) + point,
                                         attributes), ValueError),
        )
        for name, feature, error in cases:
            with self.subTest(name), self.assertRaises(error):
                self.features_error([feature])
        deep = point
        for _ in range(100):
            deep = struct.pack("<BII", 1, 7, 1) + deep
        with self.assertRaises(ValueError):
            self.features_error([(deep, attributes)])

    def test_attribute_types(self) -> None:
        cases = (
            ("2 en un booleano", "bool", 2, ValueError),
            ("texto en un booleano", "bool", "sí", TypeError),
            ("fecha y hora en una fecha", "date",
             dt.datetime(2026, 10, 8, tzinfo=dt.UTC), TypeError),
            ("fecha con barras", "date", "08/10/2026", ValueError),
            ("fecha sin ceros", "date", "2026-10-8", ValueError),
            ("fecha y hora sin zona", "datetime", dt.datetime(2026, 10, 8, 10), ValueError),
            ("texto sin zona", "datetime", "2026-10-08T10:00:00", ValueError),
            ("fecha en una fecha y hora", "datetime", dt.date(2026, 10, 8), TypeError),
            ("texto en un binario", "blob", "AAE=", TypeError),
            ("número en una fecha", "date", 20261008, TypeError),
        )
        for name, kind, value, error in cases:
            with self.subTest(name), self.assertRaises(error):
                self.features_error([(None, {"a": value})], fields={"a": kind})

    def test_failed_update_leaves_the_encoder_as_it_was(self) -> None:
        features = sample_features()
        feed = encoder.FeatureEncoder(FIELDS, "XY", LAYER_CRS)
        feed.update(features[:1])
        with self.assertRaises(TypeError):
            feed.update([features[1], (None, {**features[2][1], "area": "1"})])
        self.assertEqual(feed.count, 1)
        feed.update(features[1:])
        self.assertEqual(feed.finish(), feature_digest().data_sha256)
        rows = encoder.RowEncoder(COLUMNS, True)
        with self.assertRaises(ValueError):
            rows.update([ROWS[0], ROWS[1][:2]])
        self.assertEqual(rows.count, 0)
        rows.update(ROWS)
        self.assertEqual(rows.finish(), row_digest(ordered=True).data_sha256)
        points = encoder.PointEncoder(POINT_COLUMNS)
        with self.assertRaises(ValueError):
            points.update({**cloud(), "z": np.zeros(3)})
        self.assertEqual(points.count, 0)
        points.update(cloud())
        self.assertEqual(points.finish(), point_digest([cloud()]).data_sha256)

    def test_failure_while_hashing_breaks_the_points(self) -> None:
        real = encoder._float_cells
        calls: list[int] = []

        def failing(block: np.ndarray) -> np.ndarray:
            calls.append(len(block))
            if len(calls) == 2:
                raise MemoryError("simulado")
            return real(block)

        broken = encoder.PointEncoder(POINT_COLUMNS)
        with (
            mock.patch.object(encoder, "GRID_CHUNK_CELLS", 8),
            mock.patch.object(encoder, "_float_cells", failing),
            self.assertRaises(MemoryError),
        ):
            broken.update(cloud())
        for action in (lambda: broken.update(cloud()), broken.finish):
            with self.assertRaises(RuntimeError):
                action()

    def test_rows(self) -> None:
        cases = (
            ("ordered en texto", (COLUMNS, "yes", [ROWS[0]]), TypeError),
            ("fila corta", (COLUMNS, True, [ROWS[0][:4]]), ValueError),
            ("fila larga", (COLUMNS, True, [[*ROWS[0], 1.0]]), ValueError),
            ("fila en texto", (COLUMNS, True, ["S-01"]), TypeError),
            ("diccionario sin una columna", (COLUMNS, True, [{"hole": "S-01"}]), ValueError),
            ("sin columnas", ([], True, []), ValueError),
            ("columna repetida", ([["a", "int"], ["a", "int"]], True, []), ValueError),
            ("texto en un flotante", (COLUMNS, False, [[*ROWS[0][:4], "120"]]), TypeError),
        )
        for name, args, error in cases:
            with self.subTest(name), self.assertRaises(error):
                content.ContentHasher("table", declarations={}).rows(*args)

    def test_mesh(self) -> None:
        arrays = tetrahedron()
        cases = (
            ("sin arrays", ({}, MESH_META), ValueError),
            ("arrays en lista", ([arrays["vertices"]], MESH_META), TypeError),
            ("nombre vacío", ({"": arrays["vertices"]}, MESH_META), ValueError),
            ("objetos", ({"vertices": arrays["vertices"].astype(object)}, MESH_META), TypeError),
            ("textos", ({"meta": np.array('{"kind": "solid"}')}, MESH_META), TypeError),
            ("uint64 enorme", ({"faces": np.array([2**63], dtype="<u8")}, MESH_META), ValueError),
            ("meta en lista", (arrays, [("kind", "solid")]), TypeError),
            ("crs_epsg en texto", (arrays, {**MESH_META, "crs_epsg": "25830"}), TypeError),
            ("crs_epsg booleano", (arrays, {**MESH_META, "crs_epsg": True}), TypeError),
            ("crs_epsg 0", (arrays, {**MESH_META, "crs_epsg": 0}), ValueError),
            ("closed en texto", (arrays, {**MESH_META, "closed": "yes"}), TypeError),
            ("kind numérico", (arrays, {**MESH_META, "kind": 3}), TypeError),
        )
        for name, args, error in cases:
            with self.subTest(name), self.assertRaises(error):
                content.ContentHasher("mesh", declarations={}).mesh(*args)

    def test_points(self) -> None:
        points = cloud()
        cases = (
            ("clase desconocida", ([["x", "double"]], True, [{"x": points["x"]}]), ValueError),
            ("ordered en número", (POINT_COLUMNS, 1, [points]), TypeError),
            ("falta una columna", (POINT_COLUMNS, True,
                                   [{k: v for k, v in points.items() if k != "z"}]), ValueError),
            ("columna de más", (POINT_COLUMNS, True, [{**points, "t": points["z"]}]), ValueError),
            ("longitudes distintas", (POINT_COLUMNS, True, [{**points, "z": points["z"][:5]}]),
             ValueError),
            ("columna 2-D", (POINT_COLUMNS, True,
                             [{**points, "z": points["z"].reshape(3, 4)}]), ValueError),
            ("flotantes en una columna entera", (POINT_COLUMNS, True,
                                                 [{**points, "class": points["z"]}]), TypeError),
            ("bloque en lista", (POINT_COLUMNS, True, [[points["x"]]]), TypeError),
            ("sin columnas", ([], True, []), ValueError),
        )
        for name, args, error in cases:
            with self.subTest(name), self.assertRaises(error):
                content.ContentHasher("point_cloud", declarations={}).points(*args)

    def test_states(self) -> None:
        hasher = content.ContentHasher("vector", declarations={})
        feed = hasher.begin_features(FIELDS, "XY", None)
        with self.assertRaises(RuntimeError):
            hasher.digest()
        for action in (
            lambda: hasher.rows(COLUMNS, True, []),
            lambda: hasher.mesh(tetrahedron(), {}),
            lambda: hasher.begin_points(POINT_COLUMNS),
        ):
            with self.assertRaises(RuntimeError):
                action()
        feed.finish()
        with self.assertRaises(RuntimeError):
            feed.add(None, {"code": "A", "area": 1.0, "parts": 1})
        with self.assertRaises(RuntimeError):
            hasher.features(FIELDS, "XY", None, [])


def _steps_and_value(steps: object) -> tuple[list[float], object]:
    """Los avances de un generador de pasos y lo que devuelve al acabar."""
    seen: list[float] = []
    while True:
        try:
            seen.append(next(steps))  # type: ignore[call-overload]
        except StopIteration as stop:
            return seen, stop.value


class FinishStepsTest(unittest.TestCase):
    """RNF-008-11 y RF-008-08 (spec 008, T67; ADR-0024 §2 y §4: ningún hash cambia): una capa
    o una tabla grande cierra su hash por pasos (``finish_steps``): los sha256 de sus
    elementos van a la sección ``VALS`` por trozos de ``step`` elementos como poco (sin orden,
    ordenados por grupos de su primer byte: el mismo orden que ``sorted`` sobre todos), con el
    avance (0–1) tras cada trozo que no es el último. El hash es el de ``finish()`` y el de la
    forma escrita a mano (``struct`` y ``hashlib``, todos los sha256 ordenados de una vez)."""

    COUNT = 3_000
    STEP = 100
    COLUMNS = [["hole", "text"], ["z", "float"], ["n", "int"]]

    def rows(self) -> list[list[object]]:
        """Filas con repetidas (dos filas iguales cuentan dos veces)."""
        return [[f"S-{index % 997:04d}", float(index % 7), index % 11]
                for index in range(self.COUNT)]

    def features(self) -> list[tuple[None, dict[str, object]]]:
        return [(None, {"code": f"P-{index % 499:04d}", "area": float(index % 13),
                        "parts": index % 3}) for index in range(self.COUNT)]

    def expected_rows(self, ordered: bool) -> str:
        each = [hashlib.sha256(hashing.canonical_json(row)).digest() for row in self.rows()]
        head = hashing.canonical_json(
            {"columns": self.COLUMNS, "count": self.COUNT, "ordered": ordered}
        )
        values = b"".join(each if ordered else sorted(each))
        return hashlib.sha256(_section(b"TABL", head) + _section(b"VALS", values)).hexdigest()

    def expected_features(self) -> str:
        each = sorted(
            hashlib.sha256(b"\x00" + hashing.canonical_json(attributes)).digest()
            for _shape, attributes in self.features()
        )
        head = hashing.canonical_json({
            "count": self.COUNT, "crs": LAYER_CRS, "dims": "XY",
            "fields": [["area", "float"], ["code", "text"], ["parts", "int"]],
        })
        return hashlib.sha256(
            _section(b"FEAT", head) + _section(b"VALS", b"".join(each))
        ).hexdigest()

    def assert_steps(self, seen: list[float]) -> None:
        """Avances crecientes dentro de (0, 1), uno por trozo de ``STEP`` elementos o poco
        más (los grupos por el primer byte no se parten)."""
        self.assertEqual(seen, sorted(set(seen)))
        self.assertGreater(seen[0], 0.0)
        self.assertLess(seen[-1], 1.0)
        self.assertGreaterEqual(len(seen), self.COUNT // (2 * self.STEP))
        self.assertLessEqual(len(seen), self.COUNT // self.STEP)

    def test_rows_by_steps(self) -> None:
        for ordered in (False, True):
            with self.subTest(ordered=ordered):
                feed = encoder.RowEncoder(self.COLUMNS, ordered)
                feed.update(self.rows())
                seen, value = _steps_and_value(feed.finish_steps(self.STEP))
                self.assertEqual(value, self.expected_rows(ordered))
                self.assert_steps(seen)
                alone = encoder.RowEncoder(self.COLUMNS, ordered)
                alone.update(self.rows())
                self.assertEqual(alone.finish(), value)

    def test_features_by_steps(self) -> None:
        hasher = content.ContentHasher("vector", declarations=DECLARATIONS)
        feed = hasher.begin_features(FIELDS, "XY", LAYER_CRS)
        feed.update(self.features())
        seen, value = _steps_and_value(feed.finish_steps(self.STEP))
        self.assertEqual(value, self.expected_features())
        self.assertEqual(hasher.digest().data_sha256, value)  # entregado al acabar
        self.assert_steps(seen)
        alone = encoder.FeatureEncoder(FIELDS, "XY", LAYER_CRS)
        alone.update(self.features())
        self.assertEqual(alone.finish(), value)

    def test_few_elements_in_one_step(self) -> None:
        """Con menos elementos que ``step`` (o ninguno), un solo paso: sin avances."""
        feed = encoder.RowEncoder(COLUMNS, False)
        feed.update(ROWS)
        seen, value = _steps_and_value(feed.finish_steps(len(ROWS) + 1))
        self.assertEqual(seen, [])
        self.assertEqual(value, row_digest().data_sha256)
        empty = encoder.FeatureEncoder(FIELDS, "XY", None)
        self.assertEqual(_steps_and_value(empty.finish_steps(1)),
                         ([], encoder.FeatureEncoder(FIELDS, "XY", None).finish()))

    def test_abandoned_steps_deliver_nothing(self) -> None:
        """Pedir los pasos cierra el codificador (aunque no se recorran); dejarlos a medias
        (cancelar) no entrega el hash: el hasher sigue sin datos."""
        hasher = content.ContentHasher("vector", declarations=DECLARATIONS)
        feed = hasher.begin_features(FIELDS, "XY", LAYER_CRS)
        feed.update(self.features())
        steps = feed.finish_steps(self.STEP)
        with self.assertRaises(RuntimeError):
            feed.add(None, ATTRIBUTES)
        next(steps)
        steps.close()
        with self.assertRaises(RuntimeError):
            hasher.digest()
        with self.assertRaises(RuntimeError):
            feed.finish()
        rows = encoder.RowEncoder(COLUMNS, True)
        rows.finish_steps()
        with self.assertRaises(RuntimeError):
            rows.add(ROWS[0])

    def test_bad_step(self) -> None:
        """Un ``step`` que no es un entero positivo se rechaza y el codificador sigue abierto."""
        feed = encoder.RowEncoder(COLUMNS, False)
        feed.update(ROWS)
        for step, error in ((0, ValueError), (-3, ValueError), (2.5, TypeError),
                            (True, TypeError)):
            with self.subTest(step=step), self.assertRaises(error):
                feed.finish_steps(step)
        self.assertEqual(feed.finish(), row_digest().data_sha256)


if __name__ == "__main__":
    unittest.main()
