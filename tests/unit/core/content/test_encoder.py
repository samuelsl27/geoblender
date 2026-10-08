# SPDX-License-Identifier: GPL-3.0-or-later
"""Normalizador ``gbch/1``, primera parte: secciones ``HEAD``, ``DECL`` y ``DATA``,
``ContentDigest`` y rejillas, documentos y compuestos (spec 008, T05; RF-008-08; ADR-0024
§1, §2, §4 y §6; plan 008 §5.4.1).

RF-008-08: el hash de contenido da el mismo valor para el mismo dato aunque cambie su
contenedor (teselas, bloques de lectura, orden de bytes, float32 o float64, NaN con otra carga,
−0,0) y otro si cambia cualquier celda, el valor de sin dato, el tipo de celda, el CRS que trae
el fichero o lo declarado al importar (CRS horizontal y vertical, convenios), sin tolerancia
(D-8). ADR-0024 §1: el hash de datos no cambia con las declaraciones (RF-008-54 lo usa para «el
mismo contenido con otros ajustes»); §6: los vectores de referencia fijan la salida de
``gbch/1``.
"""

import hashlib
import struct
import tracemalloc
import unittest
from unittest import mock

import numpy as np

from tests.support import content_golden, provenance_data
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


class GoldenTest(unittest.TestCase):
    """RF-008-08; ADR-0024 §6: los vectores de referencia de ``gbch/1``
    (``tests/data/core/content/golden_gbch1.json``: rejillas float32 y float64 con NaN de
    otras cargas, −0,0, infinitos, enteros, booleanos, CRS del fichero o ``null``, sin dato NaN;
    documentos; compuestos) dan exactamente su hash: un cambio del normalizador los rompe."""

    def test_vectors(self) -> None:
        document = content_golden.load()
        self.assertEqual(document["normalizer"], content.NORMALIZER)
        by_id = content_golden.index(document)
        methods = set()
        for case in document["cases"]:
            with self.subTest(case=case["id"]):
                digest = content_golden.build(case, by_id)
                self.assertEqual(digest.data_sha256, case["data_sha256"])
                self.assertEqual(digest.content_sha256, case["content_sha256"])
                self.assertEqual(digest.reader, case["reader"])
                methods.add(content_golden.method_of(case))
        self.assertLessEqual({"grid", "document", "composite"}, methods)


if __name__ == "__main__":
    unittest.main()
