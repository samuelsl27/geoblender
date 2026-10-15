# SPDX-License-Identifier: GPL-3.0-or-later
"""Los hashes de contenido de los sondeos no cambian al calcularlos más deprisa (spec 005, T52;
RF-005-01, RF-005-02, RNF-005-01; ADR-0024 §5 y §6; RF-008-08).

La T52 acelera los hashes de una importación de V-ref: ``core.content.RowEncoder`` codifica
las filas por columnas (``update_columns``) y ``drillholes.schema.table_digest`` hashea las
filas de una tabla sin la ida y vuelta por un GeoPackage en memoria, emulando lo que SQLite
guarda de cada valor según el tipo de su columna (un NaN en una columna de números es
``NULL``…); lo que no sabe emular lo hashea como antes (``schema.stored_digest``). Una versión
publicada del normalizador no cambia (ADR-0024 §6): estas pruebas comparan, bit a bit, los
hashes de ahora con los que daba el código de partida de la T52 (anotados aquí, calculados con
él) en

- **V-ref** a escala 1/100 (``tests/data/dh/sintetico.py``, semilla fija): el hash de
  contenido de cada uno de sus 6 CSV (``io.dh_csv@1``, el de la fuente), el de lo importado de
  cada uno (``dh_src_<rol>``) y el de las 11 tablas de su base (``dh.build_base``);
- una **muestra con todos los tipos** de columna de las 21 tablas de los sondeos: reales
  (también −0,0, NaN —que se guarda como ``NULL``—, ±infinito, subnormales y el Single 0,1 por
  su decimal más corto), enteros de 64 bits, sí/no, fechas, textos (vacíos, con comillas,
  barras, tabuladores, saltos de línea, el carácter nulo, tildes y emojis) y nulos, y una
  **muestra mezclada** con valores que SQLite convierte al guardarlos (un entero en una
  columna de reales, un real entero en una de enteros, un «1» en una de sí/no, un ``float`` de
  numpy, una enumeración): esa la hashea ``stored_digest``.

Los vectores de referencia de la 008 (``tests/data/core/content/golden_gbch1.json``) los
comprueba ``tests/unit/core/content/test_golden_gbch1.py``, ahora por el camino por columnas.
"""

from __future__ import annotations

import enum
import math
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.data.dh import sintetico
from tests.support import dh_sets
from tests.support.package import import_geoblender

csv_tables = import_geoblender("interop.csv_tables")
tabular = import_geoblender("interop.drillholes_tabular")
dh_content = import_geoblender("interop.dh_content")
model = import_geoblender("drillholes.model")
values = import_geoblender("drillholes.values")
schema = import_geoblender("drillholes.schema")
store = import_geoblender("drillholes.store")
build = import_geoblender("drillholes.build_base")
provenance = import_geoblender("drillholes.provenance")
readers = import_geoblender("core.content.readers")
wkb = import_geoblender("core.gpkg.wkb")

CRS = dh_sets.H25830
VERTICAL = dh_sets.V5782
VREF_SCALE = 0.01
PROJECT_UID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
FILES = {
    tabular.TableRole.COLLAR: "bocas.csv",
    tabular.TableRole.SURVEY: "desviaciones.csv",
    tabular.TableRole.LITHOLOGY: "litologia.csv",
    tabular.TableRole.ASSAY_WIDE: "analisis_columnas.csv",
    tabular.TableRole.LITHOLOGY_CATALOG: "litologias.csv",
    tabular.TableRole.ELEMENT_CATALOG: "elementos.csv",
}
READING = {"encoding": "utf-8", "separator": ";"}
DECIMAL = ","
DATE_FORMAT = "%d/%m/%Y"
SAMPLE_ROWS = 14
SINGLE = values.from_single(np.float32(0.1))

# Los valores de cada tipo de columna de la muestra (los que SQLite guarda tal cual, salvo
# NaN, que es NULL, y −0,0, que se lee 0,0): la fila k toma, en la columna j, el valor
# (7·k + j) módulo su número.
REALS = (SINGLE, 700_010.5, -60.25, -0.0, math.nan, math.inf, -math.inf, 5e-324,
         1.7976931348623157e308, 4_400_020.25, None, 1e-7, 12.0, -3.5e15)
INTEGERS = (1, 0, -7, 2**62, -(2**63), 2**63 - 1, None, 123_456_789)
BOOLEANS = (True, False, 1, 0, None)
DATES = ("2026-10-14", "2024-02-29", "1999-12-31", None)
TEXTS = ("S-12 «Ñandú»", "", " espacios ", 'comillas "dobles" y \\barra',
         "tab\tnueva\nlínea\r", "\x00nul\x1f", "emoji 🙂 y 𝄞", "á", "1,5", "123",
         '{"OBS":"señal"}', None)


class _Kind(enum.StrEnum):
    MEASURED = "measured"


# Lo que SQLite convierte al guardarlo (la muestra mezclada): por tipo de columna.
MIXED = {
    "DOUBLE": (7, np.float64(2.5), True),
    "INTEGER": (3.0, True),
    "BOOLEAN": ("1", 1.0),
    "TEXT": (_Kind.MEASURED,),
}


def _declaration(units: Mapping[str, str]) -> Any:
    return model.SourceDeclaration(
        crs=CRS, vertical=VERTICAL, azimuth_ref=model.AzimuthRef.GRID, declination_deg=None,
        inclination_convention=model.InclinationConvention.NEGATIVE_DOWN, units=dict(units),
        value_rules=model.ValueRules(decimal_mark=DECIMAL), date_format=DATE_FORMAT)


def _uid(number: int) -> str:
    return f"{number:08x}-0000-4000-8000-{number:012x}"


def vref_digests(folder: Path) -> dict[str, str]:
    """El hash de contenido de V-ref a escala 1/100 escrito en ``folder``: ``fuente <fichero>``
    (``io.dh_csv@1``), ``<dh_src_rol> <fichero>`` (lo importado de cada fichero) y
    ``base <tabla>`` (las 11 tablas de su base)."""
    sintetico.write_vref(folder, scale=VREF_SCALE)
    tables = {role: csv_tables.read_table(folder / name, **READING)
              for role, name in FILES.items()}
    units = {row[0]: row[2] for row in tables[tabular.TableRole.ELEMENT_CATALOG].rows}
    decl = _declaration(units)
    found: dict[str, str] = {}
    entries = []
    for number, (role, name) in enumerate(FILES.items(), start=1):
        table = tables[role]
        mapping = dict(tabular.suggest_mapping(role, table.columns))
        request = dh_content.DH_CSV.request(
            provenance.input_kind(provenance.DH_CSV, str(role)),
            provenance.source_declarations(provenance.DH_CSV, decl, role=str(role),
                                           mapping=mapping),
            {"main": folder / name},
            {**READING, "header_row": 0, "decimal": DECIMAL, "date_format": DATE_FORMAT})
        found[f"fuente {name}"] = readers.read_content(dh_content.DH_CSV,
                                                       request).content_sha256
        rows = tabular.read_role(role, table, mapping, decl)
        parts = store.source_tables(collars=rows.collars, surveys=rows.surveys,
                                    lithology=rows.lithology, assays=rows.assays,
                                    catalogs=rows.catalogs)
        for part, part_rows in parts.items():
            layout = schema.source_layout(part)
            found[f"{layout.name} {name}"] = schema.table_digest(layout, part_rows,
                                                                 CRS).content_sha256
        entries.append(build.SourceEntry(
            _uid(number), decl, collars=rows.collars, surveys=rows.surveys,
            lithology=rows.lithology, assays=rows.assays, catalogs=rows.catalogs,
            label=str(role)))
    base = build.build_base(entries, None, CRS, VERTICAL, project_uid=PROJECT_UID)
    for name in schema.BASE_TABLES:
        found[f"base {name}"] = schema.table_digest(schema.LAYOUTS[name], base.rows(name),
                                                    CRS).content_sha256
    return found


def _choices(column: Any) -> Sequence[Any]:
    """Los valores de la muestra para una columna (sin nulos ni NaN si es ``NOT NULL``)."""
    found: Sequence[Any] = {"DOUBLE": REALS, "INTEGER": INTEGERS, "BOOLEAN": BOOLEANS,
                            "DATE": DATES}.get(column.sql_type, TEXTS)
    if column.not_null:
        found = [value for value in found
                 if value is not None and not (isinstance(value, float) and math.isnan(value))]
    return found


def _geometry(layout: Any, k: int) -> bytes | None:
    """La geometría de la fila ``k`` de una capa (una de cada cinco bocas, sin coordenadas)."""
    if layout.geometry_type == "POINT":
        if k % 5 == 1:
            return None
        return wkb.encode_geometry("POINT", np.array([700_010.5 + k, 4_400_020.25 - k / 8,
                                                      812.125 + k]), CRS.epsg, True)
    xyz = np.array([[700_010.5, 4_400_020.25, 812.125],
                    [700_030.0 + k, 4_400_040.5, 740.0 - k],
                    [700_060.25, 4_400_070.0 - k, 690.5]])
    return wkb.encode_geometry("LINESTRING", xyz, CRS.epsg, True)


def sample_rows(layout: Any, *, mixed: bool = False) -> list[tuple[Any, ...]]:
    """:data:`SAMPLE_ROWS` filas de la tabla de ``layout`` con todos los valores de su tipo;
    con ``mixed``, la última fila con lo que SQLite convierte al guardarlo (:data:`MIXED`)."""
    rows = []
    for k in range(SAMPLE_ROWS):
        row = []
        for j, column in enumerate(layout.columns):
            choices = _choices(column)
            value = choices[(7 * k + j) % len(choices)]
            if mixed and k == SAMPLE_ROWS - 1 and column.sql_type in MIXED:
                options = MIXED[column.sql_type]
                value = options[j % len(options)]
            row.append(value)
        if layout.geometry_type is not None:
            row.insert(0, _geometry(layout, k))
        rows.append(tuple(row))
    return rows


def sample_digests(*, mixed: bool = False) -> dict[str, str]:
    """El hash de contenido de la muestra de cada una de las 21 tablas de los sondeos."""
    return {name: schema.table_digest(layout, sample_rows(layout, mixed=mixed),
                                      CRS).content_sha256
            for name, layout in schema.LAYOUTS.items()}


# --- Los hashes del código de partida de la T52 (commit acb34cd) -----------------------------

BEFORE_VREF: dict[str, str] = {
    "fuente bocas.csv": "2eae4b76dcddafb6d9a754c367d9c1ce8a7189e50505581c0ed578856b87eaf0",
    "dh_src_collar bocas.csv": "ddcc275b583347a29f3940cf4decafdc465de0c0a517855fbe2703a1b1e2bba3",
    "fuente desviaciones.csv":
        "8e3262b398910abb9d88b138eb33196c9359f63e906d3f3d131df5bdb307580d",
    "dh_src_survey desviaciones.csv":
        "0589fc87178d5a01f53458168371ef4f6fddf2293508efb39f325fe34c8283a7",
    "fuente litologia.csv": "b48e373c3d53f9ef0fcafb04916f9e13a3d7c1904e7ded76c3340b42a01057d0",
    "dh_src_lithology litologia.csv":
        "1ab87591642172c8f4badb56e18e173152102e3cce8a51e0ec2f37148c8599fd",
    "fuente analisis_columnas.csv":
        "a5e9e287fb86110a9329a17714fdc017171e65f59a8dc0ebeaff216a735599a2",
    "dh_src_assay analisis_columnas.csv":
        "21d8e21e4863b32ef4a79e8b80bd0aa28c4f4284acd09ab78190e9b524598135",
    "fuente litologias.csv": "007716c82836ea5307d1a5df7179022142cbea5a237bf7fab396a6cfe0997b01",
    "dh_src_catalog litologias.csv":
        "c7dde382b77f562fbc6fac130a898c16ab550157b9c61df50aaeb40ea12c1d65",
    "fuente elementos.csv": "1f451c43315bf957ce5eda89478c79bbbb13608bc46e36e384f0da9c444a8651",
    "dh_src_catalog elementos.csv":
        "bd39df31dd29bdae1c7e0f69e051632a30883b1ab1c4bcc9c31097420e2b20eb",
    "base dh_collar": "599cd9dc480a5fc0d18fc11e0ef5d39ead83080ed4f3d8289d6e3c839b4f057d",
    "base dh_survey": "4863191a95c415e3cab3b17b44025aef75a251f635848154ec9074228612bc7e",
    "base dh_lithology": "efd97bd48d1d2fe2bfb9ed3e5cdf21c6fe14f6b70a3aaad0d5f5502bdf0d9089",
    "base dh_assay": "d869217feab1ae563515e668d4c8775acf9cfd2b6ba2a4c0f96b7962ddbe0730",
    "base dh_zone_interval": "d66b033b945536b0bbfcd87e170ca37e74112884e492e5795d9f4ed690da3b89",
    "base dh_structure": "80b9c380beac47e9fe9e7a526f7ee6b7cd450d54f28fd106b9e9f4092afad540",
    "base dh_lithology_code": "9a6853e37322a139bfd919641d6340f5d38b5687f733c865dd2b0746f2374549",
    "base dh_element": "b6ea12fbc662ebd903e74849136c13ce16c14395bf8879c715e34694b5e7be35",
    "base dh_sector": "722c809d735684bc0ca709c3b974e4179dd912f4dfcfd0d6cf1d3697fb1296f1",
    "base dh_group": "722c809d735684bc0ca709c3b974e4179dd912f4dfcfd0d6cf1d3697fb1296f1",
    "base dh_zone": "0a3b335aa78abecf8f7ee24799dd1910d7968d9095acdca6f63ccd47ce61b984",
}
BEFORE_SAMPLE: dict[str, str] = {
    "dh_collar": "88b2d245d156e497b0f4bbc59c4a3cad9b01e8e5287800e36eacf78327c53d19",
    "dh_survey": "456ec42aaad362dc088c604dbb0a317535d55dbac25ed0553706466f4972e67c",
    "dh_lithology": "6430d03cb34902de7074c6d5b775738b900c9c5555bb4932b17397c363e6d9b5",
    "dh_assay": "46a3d2128c48197e7005ea8380f34c2638c6f7852a9a9f9c71e48a433a61023b",
    "dh_zone_interval": "c99085bc60c08e51b8bc6a3d9b7c340713fbcd5b458cd7c550768408e1996ffa",
    "dh_structure": "a884b755d7d3bb3b859e4e506dea4695a3d32a61081d626d0f46027c83677543",
    "dh_lithology_code": "b61e85ec4088fc625c6628b1c23d7363389f5a485224b887a7b5a67a9cbd51a0",
    "dh_element": "4777e3b72821ee288e61812851640ce6d1eeb9bb3a709db23653101495a9c002",
    "dh_sector": "a16cf5fa05f6cb7d5c5bbd2b81a00dfb92a1effe09fe50e9b0268c8a199f7c7a",
    "dh_group": "a16cf5fa05f6cb7d5c5bbd2b81a00dfb92a1effe09fe50e9b0268c8a199f7c7a",
    "dh_zone": "8c8d66dbd1b715813e96c15d95c077b8d43cc096713ad6263d3ccd6c6e10b17d",
    "dh_trace": "c691e4d8c9956b8ce470bc1f869c376a3a86ed6a788b100a4d3dc6101dc6b827",
    "dh_validation_issue": "e634fc68f6a3c8a0666c83f7723cdca97d984d39d37c1549696bb7b5c3930738",
    "dh_import_log": "6020af3ee8bec902b1293873499d8df3273e05e0de9a243f33e49d7f6caab0ed",
    "dh_src_collar": "5dd996511a49f83a3a3d4d987df2d089a930a36690d3560d65be3cc55de56a0f",
    "dh_src_survey": "6f88a86d4b13e414174c12230ae4f342bcdcb858074af5e5a7a1bbff03e3a5ea",
    "dh_src_lithology": "cb1aa5c0643cb758b976c4633a5b060d4228616b61338e632b687fea6af195c5",
    "dh_src_assay": "cd50da8edbd2b5efd5c8857478c25e83b39b5af6052d91f5f74bc0bc90144537",
    "dh_src_catalog": "c8561956a3614b0faf8c30635b500bf09ca205985a32bfcaa24cae9b9dd348c9",
    "dh_src_zone_interval": "ff361f2556b15effcb07590bec38791ef4c0f7b589fdb41c4293a24ef6d5c045",
    "dh_src_structure": "23f35c0fe76e6367832c5cd4d0b74ec489515d63083f1b9e10f44c80e9e792c1",
}
BEFORE_MIXED: dict[str, str] = {
    "dh_collar": "5c7de2cb7d6de4b07ef0c62ba4165be4c21c818af1acebbb968e0efc267bb4f9",
    "dh_survey": "0b51c4b18128f6228ddc6c92609daf1bedab59ec0917236480c8131a4b143164",
    "dh_lithology": "37cf81df9c3cd18ab9a64b41b3f4f99a0bd631533053f5663833916f3af3a182",
    "dh_assay": "5a6f8ce5f83158ad40b82ec0955cc58e7127e94e0e1156039b32da260366581c",
    "dh_zone_interval": "f016b91286db9eecb930676b2cc7cbd21040e7a74716beb75730d544f238c38b",
    "dh_structure": "efc487019b8526b4ec997c892d7e2587a1134d8c81e386bc9b25fff2fd65a226",
    "dh_lithology_code": "d15d96faebdc06a926655455318b7dd7a4953388d34c623e85a5f50cd259079b",
    "dh_element": "946dcc3711989740bd82cba599c29ffddbd79fc5207de0cd20109608b131d047",
    "dh_sector": "5463c997a564db97bf8dcaaccc699ca475b2bece79850ceb0df79cde23f74f41",
    "dh_group": "5463c997a564db97bf8dcaaccc699ca475b2bece79850ceb0df79cde23f74f41",
    "dh_zone": "7c29f30d4180ac34dec770651f6684fafb40cb8773e359127b1468283d4636c2",
    "dh_trace": "9529e00316bd82c96ed9230800d66a5666ae8cf92292b1c1ef983545c2cc1211",
    "dh_validation_issue": "04761282a1da590396c12b8759eb12e5d81cacdb6e20e78768cd86cb742b2bc1",
    "dh_import_log": "7fda0e47754679ff131714f70e5cc5eb8ff1d184868326c71e4afc37160f61bd",
    "dh_src_collar": "78f2fe76106744e722084d64d52841c1299544d6f54defd77f81e28e192bace1",
    "dh_src_survey": "8d394f29105752471f06f1094079464904861d433c31a4e7a82f66b791a15daa",
    "dh_src_lithology": "6c8b48ffc2d1bd22168772c9d1a01c45c67d8133ffb4e7008f0fd6f07c634d9f",
    "dh_src_assay": "c286a9bdcecc64d5b655c55bce6bb0560c661b129124a330898ebaed4db8375a",
    "dh_src_catalog": "a1f2998e3074350fc8b36a829fd092d855cb74e5e03e052e7c7d2f1452d3aebf",
    "dh_src_zone_interval": "ad069424d849a0d9dc2028bdae3b7c05c7657388dc3318008af6bfb466434e00",
    "dh_src_structure": "26f9b449c16e5c2943ee77fa7c677c11834795ab9a9ac2e30257de517d21441f",
}


class DigestsUnchangedTest(unittest.TestCase):
    """RF-005-01, RF-005-02, RNF-005-01 (ADR-0024 §6): los hashes de ahora son, bit a bit, los
    del código de partida."""

    def test_vref_sources_imported_and_base(self) -> None:
        """RF-005-01, RF-005-02, RNF-005-01: V-ref a escala 1/100: el hash de sus 6 CSV, el de
        lo importado de cada uno y el de las 11 tablas de su base, los de antes."""
        with tempfile.TemporaryDirectory(prefix="gb-t52-") as tmp:
            found = vref_digests(Path(tmp))
        self.assertEqual(len([key for key in found if key.startswith("base ")]), 11)
        self.assertEqual(found, BEFORE_VREF)

    def test_sample_with_every_type(self) -> None:
        """RF-005-01, RF-005-02: la muestra con todos los tipos de las 21 tablas (reales con
        −0,0, NaN e infinitos, enteros de 64 bits, sí/no, fechas, textos y nulos), sus hashes
        de antes, sin pasar por SQLite en las tablas sin geometría."""
        with mock.patch.object(schema, "stored_digest", wraps=schema.stored_digest) as stored:
            found = sample_digests()
        self.assertEqual(found, BEFORE_SAMPLE)
        self.assertEqual(sorted(call.args[0].name for call in stored.call_args_list),
                         ["dh_collar", "dh_trace"])

    def test_mixed_sample(self) -> None:
        """RF-005-01, RF-005-02: la muestra con lo que SQLite convierte al guardarlo, sus
        hashes de antes (las tablas con esos valores, por ``stored_digest``)."""
        self.assertEqual(sample_digests(mixed=True), BEFORE_MIXED)


class StoredDigestTest(unittest.TestCase):
    """RF-005-01, RF-005-02 (ADR-0024 §5): ``table_digest`` sin SQLite da lo mismo que
    ``stored_digest`` (las filas guardadas en un GeoPackage en memoria y leídas con
    ``core.gpkg_layer@1``), también los errores."""

    def test_random_rows(self) -> None:
        """RF-005-01, RF-005-02: 300 filas al azar (semilla fija) de los valores de la muestra
        en cada tabla sin geometría: el mismo hash por los dos caminos."""
        rng = np.random.default_rng(20_261_015)
        for name, layout in schema.LAYOUTS.items():
            if layout.geometry_type is not None:
                continue
            choices = [_choices(column) for column in layout.columns]
            rows = [tuple(options[int(rng.integers(len(options)))] for options in choices)
                    for _ in range(300)]
            with self.subTest(tabla=name):
                self.assertEqual(schema.table_digest(layout, rows, CRS),
                                 schema.stored_digest(layout, rows, CRS))

    def test_same_errors(self) -> None:
        """RF-005-01: una fila que no vale da el mismo error por los dos caminos: una fila
        corta, un nulo o un NaN en una columna ``NOT NULL``, un texto con un sustituto suelto,
        un 2 en una de sí/no, una fecha que no existe, un texto o un entero de 65 bits en una
        de enteros."""
        layout = schema.LAYOUTS["dh_assay"]
        good = sample_rows(layout)
        names = layout.insert_columns
        cases = {
            "fila corta": None,
            "nulo en NOT NULL": ("element_id", None),
            "sustituto suelto": ("unit", "g/t\ud800"),
            "2 en un sí/no": ("is_primary", 2),
            "entero en texto": ("hole_id", "abc"),
            "entero de 65 bits": ("hole_id", 2**64),
        }
        dates = schema.LAYOUTS["dh_src_collar"]
        for name, change in cases.items():
            rows = [list(row) for row in good]
            if change is None:
                rows[4] = rows[4][:-1]
            else:
                rows[4][names.index(change[0])] = change[1]
            with self.subTest(name):
                self.assert_same_error(layout, rows)
        rows = [list(row) for row in sample_rows(dates)]
        rows[2][dates.insert_columns.index("start_date")] = "2024-02-30"
        with self.subTest("fecha que no existe"):
            self.assert_same_error(dates, rows)
        rows = [list(row) for row in sample_rows(schema.LAYOUTS["dh_trace"])]
        rows[1][schema.LAYOUTS["dh_trace"].insert_columns.index("length_m")] = math.nan
        with self.subTest("NaN en un real NOT NULL"):
            self.assert_same_error(schema.LAYOUTS["dh_trace"], rows)
        survey = schema.LAYOUTS["dh_survey"]
        rows = [list(row) for row in sample_rows(survey)]
        rows[3][survey.insert_columns.index("depth")] = math.nan  # NULL: admite nulos
        self.assertEqual(schema.table_digest(survey, rows, CRS),
                         schema.stored_digest(survey, rows, CRS))

    def assert_same_error(self, layout: Any, rows: list[list[Any]]) -> None:
        with self.assertRaises(Exception) as expected:
            schema.stored_digest(layout, rows, CRS)
        with self.assertRaises(type(expected.exception)) as raised:
            schema.table_digest(layout, rows, CRS)
        self.assertEqual(str(raised.exception), str(expected.exception))


if __name__ == "__main__":
    unittest.main()
