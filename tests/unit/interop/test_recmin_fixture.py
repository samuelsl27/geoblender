# SPDX-License-Identifier: GPL-3.0-or-later
"""Bases RecMin sintéticas (spec 005, T02; plan 005 §2.1 y §7): ``tests/data/dh/recmin/``.

- **RF-005-13** (importar una base de RecMin, MDB o ACCDB, Jet 4 o ACE, esquema 11 o 12,
  con todas sus tablas de litología y de muestras, catálogos, intersecciones y cortes):
  ``recmin_v12.sql`` tiene el esquema de ``default.mdb`` de RecMin Pro (plan 005 §2.1:
  tablas en minúsculas, ``ACTUALIZACION.ULTIMA = 12``, coordenadas y ángulos en Double,
  tramos, leyes, densidades y ``CL *`` en Single, ``COLOR`` en Int32, «au» en ppb y «cu» en
  %) y ``recmin_v11.sql``, el de la investigación 01 §6.1 (tablas en mayúsculas,
  ``ULTIMA = 11``, sin ``GRUPOS`` ni ``FORMULAS``, ``DISTANCIA`` en Single). Los dos tienen
  tablas adicionales de litología y de muestras (con otro nombre: se reconocen por su
  forma), un elemento de texto (unidad «txt», columna de texto), colores BGR asimétricos
  y referencias que se resuelven.
- **RF-005-02** (precisión simple): los dos guardan 0,1 y 4,35 en columnas Single, que
  leídas en doble precisión no son 0,1 ni 4,35.
- ``build_mdb.ps1`` crea con cada guion una base Jet 4 (``Microsoft.Jet.OLEDB.4.0``, en el
  ``powershell.exe`` de 32 bits) y otra ACE (ACE 16 o 12, en el de 64 bits; con extensión
  ``.mdb``, como ``default.mdb``), en una carpeta temporal y sin tocar la de los guiones;
  cada base tiene las tablas, el número de filas de cada una (:data:`EXPECTED_ROWS`) y los
  tipos de columna del guion, y la cabecera de su formato (byte 0x14: 1 en Jet 4, 2 en ACE;
  plan 005 §5.3.4). Ninguna base se versiona.

Sin el motor ACE de 64 bits, las pruebas de la base ACE se omiten con ``[ENTORNO] ace``.
"""

import hashlib
import os
import shutil
import struct
import tempfile
import unittest
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

from tests.support import recmin
from tests.support.resources import WINDOWS, WINDOWS_HINT, is_available, requires, skip_reason

V11, V12 = "recmin_v11.sql", "recmin_v12.sql"
SPDX = "SPDX-License-Identifier: GPL-3.0-or-later"

# Filas de cada tabla de cada guion, con el nombre de la tabla tal como lo escribe RecMin
# (minúsculas en el esquema 12, mayúsculas en el 11).
EXPECTED_ROWS: dict[str, dict[str, int]] = {
    V12: {
        "sondeos": 4,
        "angulos": 11,
        "litologia": 9,
        "idlitologia": 7,
        "muestras": 7,
        "elementos": 3,
        "sectores": 2,
        "grupos": 2,
        "zonas": 2,
        "intersecciones": 2,
        "cortes": 1,
        "formulas": 2,
        "actualizacion": 1,
        "giros": 0,
        "secciones": 2,
        "alteracion": 3,
        "duplicados": 2,
    },
    V11: {
        "SONDEOS": 3,
        "ANGULOS": 7,
        "LITOLOGIA": 8,
        "IDLITOLOGIA": 5,
        "MUESTRAS": 5,
        "ELEMENTOS": 3,
        "SECTORES": 2,
        "ZONAS": 1,
        "INTERSECCIONES": 1,
        "CORTES": 1,
        "ACTUALIZACION": 1,
        "GIROS": 0,
        "LITOLOGIA2": 2,
        "MUESTRAS2": 1,
    },
}
SCHEMA_VERSION = {V11: 11, V12: 12}
# Tipo de Jet SQL del guion → tipo OLE DB que da el motor (``DATA_TYPE`` del esquema de
# columnas): LONG y COUNTER, Integer (3); SHORT, SmallInt (2); SINGLE, Single (4); DOUBLE,
# Double (5); BIT, Boolean (11); DATETIME, Date (7); TEXT y MEMO, WChar (130).
OLEDB_TYPES = {
    "LONG": 3,
    "COUNTER": 3,
    "SHORT": 2,
    "SINGLE": 4,
    "DOUBLE": 5,
    "BIT": 11,
    "DATETIME": 7,
    "TEXT": 130,
    "MEMO": 130,
}
LITHOLOGY_SHAPE = ("IDSONDEO", "DESDE", "HASTA", "IDLITO")
SAMPLE_SHAPE = ("IDSONDEO", "DESDE", "HASTA")
# Cabecera de una base de Access: «Standard Jet DB» o «Standard ACE DB» en el byte 4 y la
# versión del formato en el 0x14 (plan 005 §2.1 y §5.3.4).
HEADERS = {"jet4": (b"Standard Jet DB", 1), "ace": (b"Standard ACE DB", 2)}

_build: recmin.Build | None = None
_tmp: Path | None = None
_sources_before: dict[str, str] = {}


def _fingerprint(folder: Path) -> dict[str, str]:
    """Nombre → sha256 de cada fichero de ``folder``."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.iterdir())
        if p.is_file()
    }


def setUpModule() -> None:
    """Crea las bases de los dos guiones una sola vez, Jet 4 y ACE a la vez (si hay ACE)."""
    global _build, _tmp
    if os.name != "nt":
        raise unittest.SkipTest(skip_reason(WINDOWS, WINDOWS_HINT))
    _sources_before.update(_fingerprint(recmin.RECMIN_DIR))
    _tmp = Path(tempfile.mkdtemp(prefix="gbrm"))
    engines = ("jet4", "ace") if is_available(recmin.ACE) else ("jet4",)
    _build = recmin.build_bases(_tmp, engines)


def tearDownModule() -> None:
    if _tmp is not None:
        shutil.rmtree(_tmp, ignore_errors=True)


def _scripts() -> dict[str, dict[str, recmin.SqlTable]]:
    return {name: recmin.parse_sql(recmin.RECMIN_DIR / name) for name in (V11, V12)}


def _shaped(tables: dict[str, recmin.SqlTable], names: Iterable[str]) -> list[str]:
    """Las tablas cuyas columnas incluyen ``names`` (sin distinguir mayúsculas)."""
    wanted = {n.upper() for n in names}
    return [
        t.name for t in tables.values() if wanted <= {c.name.upper() for c in t.columns}
    ]


def _element_columns(table: recmin.SqlTable) -> dict[int, recmin.SqlColumn]:
    """Las columnas «ELEMENTO n» de una tabla de muestras, por su número."""
    return {
        int(c.name.split()[1]): c for c in table.columns if c.name.upper().startswith("ELEMENTO ")
    }


def _table(tables: dict[str, recmin.SqlTable], name: str) -> recmin.SqlTable:
    """La tabla ``name`` sin distinguir mayúsculas (como la busca la importación)."""
    found = [t for t in tables.values() if t.name.upper() == name.upper()]
    assert len(found) == 1, f"{name}: {found}"
    return found[0]


def _f32(value: Decimal) -> float:
    """El float64 del float32 más cercano a ``value``, como lo lee quien no lo redondea."""
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


class AceResourceTest(unittest.TestCase):
    """El recurso ``ace`` de ``tests.support.resources`` (la 005 lo declara en T02)."""

    def test_ace_is_declared_and_registered(self) -> None:
        """RF-005-13, RF-001-06: ``ace`` está en la lista cerrada de recursos, tiene
        comprobación registrada y su motivo dice qué instalar."""
        from tests.support import resources

        self.assertIn(recmin.ACE, resources.RESOURCES)
        self.assertIsInstance(resources.is_available(recmin.ACE), bool)
        self.assertIn("Access", recmin.ACE_HINT)
        self.assertIn("64 bits", recmin.ACE_HINT)


class SqlScriptsTest(unittest.TestCase):
    """Lo que prometen los dos guiones, leídos sin motor (``recmin.parse_sql``)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.scripts = _scripts()

    def test_rows_per_table(self) -> None:
        """RF-005-13: cada guion crea sus tablas con las filas de :data:`EXPECTED_ROWS`."""
        for name, tables in self.scripts.items():
            with self.subTest(guion=name):
                got = {t.name: len(t.rows) for t in tables.values()}
                self.assertEqual(got, EXPECTED_ROWS[name])

    def test_schema_version_and_table_name_case(self) -> None:
        """RF-005-13, RF-005-15: ``ACTUALIZACION.ULTIMA`` es 11 o 12; el esquema 12 escribe
        las tablas en minúsculas (``default.mdb``) y el 11, en mayúsculas."""
        for name, tables in self.scripts.items():
            with self.subTest(guion=name):
                version = _table(tables, "ACTUALIZACION").rows
                self.assertEqual([row["ULTIMA"] for row in version], [SCHEMA_VERSION[name]])
                lower = name == V12
                for table in tables:
                    self.assertEqual(table, table.lower() if lower else table.upper())

    def test_v12_types_of_default_mdb(self) -> None:
        """RF-005-13, RF-005-02 (plan 005 §2.1): en el esquema 12, coordenadas y ángulos
        en Double; tramos, leyes, densidades y ``CL *`` en Single; ``COLOR`` en Int32;
        elementos «au» en ppb y «cu» en %, y ``GRUPOS``, ``IDGRUPO`` y ``FORMULAS``."""
        tables = self.scripts[V12]
        expected = {
            ("sondeos", "ESTE"): "DOUBLE",
            ("sondeos", "NORTE"): "DOUBLE",
            ("sondeos", "ELEVACION"): "DOUBLE",
            ("sondeos", "IDGRUPO"): "SHORT",
            ("sondeos", "CL NORTE"): "SINGLE",
            ("sondeos", "CL ESTE"): "SINGLE",
            ("sondeos", "CL Z"): "SINGLE",
            ("angulos", "DISTANCIA"): "DOUBLE",
            ("angulos", "INCLINACION"): "DOUBLE",
            ("angulos", "DIRECCION"): "DOUBLE",
            ("litologia", "DESDE"): "SINGLE",
            ("litologia", "HASTA"): "SINGLE",
            ("muestras", "DESDE"): "SINGLE",
            ("muestras", "HASTA"): "SINGLE",
            ("muestras", "ELEMENTO 1"): "SINGLE",
            ("muestras", "ELEMENTO 2"): "SINGLE",
            ("idlitologia", "DENSIDAD"): "SINGLE",
            ("idlitologia", "COLOR"): "LONG",
            ("zonas", "DENSIDAD"): "SINGLE",
        }
        for (table, column), kind in expected.items():
            with self.subTest(tabla=table, columna=column):
                self.assertEqual(tables[table].column(column).type, kind)
        elements = {(r["NOMBRE"], r["UNIDAD"]) for r in tables["elementos"].rows}
        self.assertLessEqual({("au", "ppb"), ("cu", "%")}, elements)
        self.assertIn("formulas", tables)
        self.assertIn("grupos", tables)

    def test_v11_types_of_investigation_01(self) -> None:
        """RF-005-13 (investigación 01 §6.1): el esquema 11 no tiene ``GRUPOS``,
        ``IDGRUPO`` ni ``FORMULAS`` y guarda ``ANGULOS.DISTANCIA`` en Single (bases
        antiguas)."""
        tables = self.scripts[V11]
        self.assertNotIn("GRUPOS", tables)
        self.assertNotIn("FORMULAS", tables)
        self.assertNotIn("IDGRUPO", {c.name for c in tables["SONDEOS"].columns})
        self.assertEqual(tables["ANGULOS"].column("DISTANCIA").type, "SINGLE")
        self.assertEqual(tables["SONDEOS"].column("ESTE").type, "DOUBLE")

    def test_additional_lithology_and_sample_tables_by_shape(self) -> None:
        """RF-005-13 (plan 005 §5.4): además de ``LITOLOGIA`` y ``MUESTRAS``, cada guion
        tiene otra tabla de litología (``IDSONDEO, DESDE, HASTA, IDLITO``) y otra de
        muestras (``ELEMENTO n``) con otro nombre; las de muestras tienen las mismas
        columnas de elementos, y todas, tramos con desde < hasta."""
        for name, tables in self.scripts.items():
            with self.subTest(guion=name):
                lithology = _shaped(tables, LITHOLOGY_SHAPE)
                samples = [
                    t for t in _shaped(tables, SAMPLE_SHAPE) if _element_columns(tables[t])
                ]
                main_lithology = _table(tables, "LITOLOGIA").name
                main_samples = _table(tables, "MUESTRAS").name
                self.assertEqual(len(lithology), 2, lithology)
                self.assertEqual(len(samples), 2, samples)
                self.assertIn(main_lithology, lithology)
                self.assertIn(main_samples, samples)
                columns = {t: sorted(_element_columns(tables[t])) for t in samples}
                self.assertEqual(columns[samples[0]], columns[samples[1]])
                for table in (*lithology, *samples):
                    for row in tables[table].rows:
                        self.assertLess(row["DESDE"], row["HASTA"], (table, row))

    def test_text_element(self) -> None:
        """RF-005-13 (plan 005 §5.2: unidad «txt» → ``unit = 'text'``): cada guion tiene un
        elemento de unidad «txt» cuya columna es de texto en todas las tablas de muestras,
        con valores de texto y algún nulo; los demás elementos son Single."""
        for name, tables in self.scripts.items():
            with self.subTest(guion=name):
                catalog = _table(tables, "ELEMENTOS").rows
                text = {r["ELEMENTO"] for r in catalog if r["UNIDAD"] == "txt"}
                self.assertEqual(len(text), 1, catalog)
                samples = [t for t in _shaped(tables, SAMPLE_SHAPE) if _element_columns(tables[t])]
                self.assertEqual(len(samples), 2, samples)
                for table in samples:
                    columns = _element_columns(tables[table])
                    self.assertEqual(sorted(columns), sorted(r["ELEMENTO"] for r in catalog))
                    for number, column in columns.items():
                        kind = "TEXT" if number in text else "SINGLE"
                        self.assertEqual(column.type, kind, (table, column))
                (number,) = text
                values = [r[f"ELEMENTO {number}"] for r in _table(tables, "MUESTRAS").rows]
                self.assertTrue(any(isinstance(v, str) for v in values), values)
                self.assertIn(None, values)

    def test_single_precision_values(self) -> None:
        """RF-005-02: cada guion guarda 0,1 y 4,35 en columnas Single, que en doble
        precisión serían 0,100000001490116 y 4,349999904632568 (plan 005 §5.4)."""
        for name, tables in self.scripts.items():
            with self.subTest(guion=name):
                singles = {
                    row[column.name]
                    for table in tables.values()
                    for column in table.columns
                    if column.type == "SINGLE"
                    for row in table.rows
                }
                for value in (Decimal("0.1"), Decimal("4.35")):
                    self.assertIn(value, singles)
                    self.assertNotEqual(_f32(value), float(value))

    def test_bgr_colors(self) -> None:
        """RF-005-13 (``COLOR`` en BGR de Windows → ``#RRGGBB``): los colores de
        ``IDLITOLOGIA`` son enteros de 24 bits y alguno tiene rojo y azul distintos, para que
        leerlos como RGB dé otro color."""
        for name, tables in self.scripts.items():
            with self.subTest(guion=name):
                colors = [r["COLOR"] for r in _table(tables, "IDLITOLOGIA").rows]
                self.assertTrue(all(0 <= c <= 0xFFFFFF for c in colors), colors)
                asymmetric = [c for c in colors if c & 0xFF != (c >> 16) & 0xFF]
                self.assertGreaterEqual(len(asymmetric), 2, colors)

    def test_references_resolve(self) -> None:
        """RF-005-13: los sondeos, litologías, zonas, sectores y grupos a los que se
        refieren las tablas existen, y cada tramo de un sondeo queda dentro de su
        profundidad deducida (máximo de la última ``DISTANCIA`` y del último ``HASTA``)."""
        for name, tables in self.scripts.items():
            with self.subTest(guion=name):
                holes = {r["IDSONDEO"] for r in _table(tables, "SONDEOS").rows}
                codes = {r["IDLITO"] for r in _table(tables, "IDLITOLOGIA").rows}
                zones = {r["IDZONA"] for r in _table(tables, "ZONAS").rows}
                sectors = {r["IDSECTOR"] for r in _table(tables, "SECTORES").rows}
                for table in tables.values():
                    columns = {c.name for c in table.columns}
                    for row in table.rows:
                        if "IDSONDEO" in columns and table.name.upper() != "SONDEOS":
                            self.assertIn(row["IDSONDEO"], holes, (table.name, row))
                        if "IDLITO" in columns and table.name.upper() != "IDLITOLOGIA":
                            self.assertIn(row["IDLITO"], codes, (table.name, row))
                        if "IDZONA" in columns and table.name.upper() != "ZONAS":
                            self.assertIn(row["IDZONA"], zones, (table.name, row))
                        if "IDSECTOR" in columns and table.name.upper() != "SECTORES":
                            self.assertIn(row["IDSECTOR"], sectors, (table.name, row))
                if name == V12:
                    groups = {r["IDGRUPO"] for r in tables["grupos"].rows}
                    for row in tables["sondeos"].rows:
                        self.assertIn(row["IDGRUPO"], groups)

    def test_files_and_no_database_versioned(self) -> None:
        """RF-005-13 (plan 005 §2: el guion ``.ps1`` lleva su línea SPDX como comentario):
        en la carpeta solo están los dos guiones SQL (UTF-8 sin BOM, LF, con su línea SPDX)
        y ``build_mdb.ps1`` (CRLF, con la suya); ninguna base ni fichero de bloqueo."""
        names = sorted(p.name for p in recmin.RECMIN_DIR.iterdir())
        self.assertEqual(names, ["build_mdb.ps1", V11, V12])
        for name in (V11, V12):
            data = (recmin.RECMIN_DIR / name).read_bytes()
            with self.subTest(fichero=name):
                self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
                self.assertNotIn(b"\r", data)
                self.assertEqual(data.decode("utf-8").splitlines()[0], f"-- {SPDX}")
        script = recmin.BUILD_SCRIPT.read_bytes()
        self.assertFalse(script.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(script.count(b"\n"), script.count(b"\r\n"))
        self.assertEqual(script.decode("utf-8").splitlines()[0], f"# {SPDX}")


class _BuiltBasesChecks:
    """Comprobaciones de las bases que crea ``build_mdb.ps1`` con un motor (``ENGINE``)."""

    ENGINE = ""

    def _bases(self) -> dict[str, recmin.BuiltBase]:
        assert _build is not None
        case: unittest.TestCase = self  # type: ignore[assignment]
        case.assertNotIn(self.ENGINE, _build.missing, "el motor no creó la base")
        return {sql: _build.bases[(sql, self.ENGINE)] for sql in (V11, V12)}

    def test_format_header(self) -> None:
        """RF-005-13, RF-005-14 (plan 005 §5.3.4): cada base tiene la cabecera de su
        formato y su byte de versión (0x14), y la extensión ``.mdb``; está en la carpeta
        temporal, no en la de los guiones."""
        case: unittest.TestCase = self  # type: ignore[assignment]
        header, version = HEADERS[self.ENGINE]
        for sql, base in self._bases().items():
            with case.subTest(guion=sql):
                data = base.path.read_bytes()[:0x15]
                case.assertEqual(data[4:4 + len(header)], header)
                case.assertEqual(data[0x14], version)
                case.assertEqual(base.path.suffix, ".mdb")
                case.assertEqual(base.path.parent, _tmp)

    def test_rows_per_table(self) -> None:
        """RF-005-13: el motor cuenta en cada base las tablas y las filas de
        :data:`EXPECTED_ROWS` (las del guion), con los nombres de RecMin."""
        case: unittest.TestCase = self  # type: ignore[assignment]
        for sql, base in self._bases().items():
            with case.subTest(guion=sql):
                got = {t.name: t.rows for t in base.tables.values()}
                case.assertEqual(got, EXPECTED_ROWS[sql])

    def test_column_types(self) -> None:
        """RF-005-13, RF-005-02: cada columna tiene el nombre, el orden y el tipo OLE DB
        del guion (Single en precisión simple, Double, Int32…), y los textos, su tamaño."""
        case: unittest.TestCase = self  # type: ignore[assignment]
        for sql, base in self._bases().items():
            script = recmin.parse_sql(recmin.RECMIN_DIR / sql)
            for name, table in script.items():
                with case.subTest(guion=sql, tabla=name):
                    built = base.tables[name].columns
                    case.assertEqual([c.name for c in built], [c.name for c in table.columns])
                    case.assertEqual(
                        [c.type for c in built], [OLEDB_TYPES[c.type] for c in table.columns]
                    )
                    texts = [c.size for c in built if c.type == OLEDB_TYPES["TEXT"]]
                    sizes = [c.size or 0 for c in table.columns if c.type in ("TEXT", "MEMO")]
                    case.assertEqual(texts, sizes)

    def test_sources_untouched(self) -> None:
        """RF-005-03 (las fuentes no cambian): crear las bases no cambia ni añade nada en
        la carpeta de los guiones."""
        case: unittest.TestCase = self  # type: ignore[assignment]
        case.assertEqual(_fingerprint(recmin.RECMIN_DIR), _sources_before)


@unittest.skipUnless(os.name == "nt", skip_reason(WINDOWS, WINDOWS_HINT))
class Jet4BasesTest(_BuiltBasesChecks, unittest.TestCase):
    """Las bases Jet 4 (``Microsoft.Jet.OLEDB.4.0``, ``powershell.exe`` de 32 bits)."""

    ENGINE = "jet4"


@requires(recmin.ACE, recmin.ACE_HINT)
class AceBasesTest(_BuiltBasesChecks, unittest.TestCase):
    """Las bases ACE (ACE 16 o 12, ``powershell.exe`` de 64 bits), como ``default.mdb``."""

    ENGINE = "ace"


if __name__ == "__main__":
    unittest.main()
