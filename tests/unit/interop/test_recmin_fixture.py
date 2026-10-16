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
- **RNF-001-01** (spec 005, T44): ``recmin.shared_bases`` da a cada prueba que las pide su
  copia de esas bases, creadas una vez por guion y motor en un almacén de la carpeta temporal
  del sistema (con la huella de cada base, que se comprueba antes de copiarla); este módulo
  sigue creándolas con ``build_bases`` cada vez.

Sin el motor ACE de 64 bits, las pruebas de la base ACE se omiten con ``[ENTORNO] ace``.
"""

import concurrent.futures
import hashlib
import os
import shutil
import struct
import tempfile
import threading
import time
import unittest
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from unittest import mock

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


class _FakeBuilder:
    """Un ``build_bases`` simulado, sin motor: escribe ``<guion>_<motor>.mdb`` con un texto
    propio y anota con qué motores se le llamó; con ``missing``, esos motores faltan."""

    def __init__(self, missing: Iterable[str] = (), delay_s: float = 0.0) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.missing = frozenset(missing)
        self.delay_s = delay_s
        self.lock = threading.Lock()

    def __call__(self, out_dir: Path, engines: tuple[str, ...] = tuple(recmin.ENGINES), *,
                 sql: Path | None = None) -> recmin.Build:
        with self.lock:
            self.calls.append(tuple(engines))
        time.sleep(self.delay_s)
        scripts = [Path(sql)] if sql is not None else sorted(recmin.RECMIN_DIR.glob("*.sql"))
        bases: dict[tuple[str, str], recmin.BuiltBase] = {}
        for engine in engines:
            if engine in self.missing:
                continue
            for script in scripts:
                path = out_dir / f"{script.stem}_{engine}.mdb"
                path.write_bytes(f"{engine}:{script.read_text(encoding='utf-8')}".encode())
                column = recmin.BuiltColumn("ID", 3, None)
                bases[(script.name, engine)] = recmin.BuiltBase(
                    engine, script.name, path, f"proveedor-{engine}",
                    {"t": recmin.BuiltTable("t", 2, (column,))})
        return recmin.Build(bases, self.missing & set(engines))


def _without_paths(build: recmin.Build) -> dict[tuple[str, str], tuple[object, ...]]:
    return {key: (b.engine, b.sql, b.path.name, b.provider, b.tables)
            for key, b in build.bases.items()}


def _entries(store: Path) -> list[str]:
    return sorted(p.name for p in store.iterdir()) if store.exists() else []


class SharedBasesTest(unittest.TestCase):
    """``recmin.shared_bases`` (spec 005, T44; RNF-001-01): las bases de :func:`build_bases`
    se crean una vez por guion y motor en un almacén de la carpeta temporal del sistema, y
    cada prueba recibe su copia, en su carpeta, como si las hubiera creado."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gbrs")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.store = self.tmp / "almacen"

    def _shared(self, name: str, builder: _FakeBuilder, engines: tuple[str, ...] = ("jet4", "ace"),
                sql: Path | None = None) -> recmin.Build:
        return recmin.shared_bases(self.tmp / name, engines, sql=sql, store=self.store,
                                   build=builder)

    def test_built_once_then_copied(self) -> None:
        """RNF-001-01, RF-005-13: la primera vez se crean (todos los motores a la vez, como
        ``build_bases``) y se guardan, una entrada por motor; las siguientes se copian de
        ahí sin crear nada: cada carpeta recibe los mismos ficheros y lo que el motor contó
        de cada base, con la ruta de su copia."""
        builder = _FakeBuilder()
        first = self._shared("a", builder)
        second = self._shared("b", builder)
        self.assertEqual(builder.calls, [("jet4", "ace")])
        self.assertEqual(_without_paths(first), _without_paths(second))
        self.assertEqual(len(first.bases), 4)
        for build, folder in ((first, self.tmp / "a"), (second, self.tmp / "b")):
            for base in build.bases.values():
                self.assertEqual(base.path.parent, folder)
                self.assertTrue(base.path.read_bytes().startswith(base.engine.encode() + b":"))
        self.assertEqual(len([n for n in _entries(self.store)
                              if n.startswith(recmin.STORE_ENTRY_PREFIX)]), 2)

    def test_damaged_or_missing_engine_is_built_again(self) -> None:
        """RNF-001-01: una base guardada que ya no es la que se guardó (otro tamaño u otro
        contenido) se crea otra vez, solo la de ese motor; un motor que faltaba (sin ACE) no
        se guarda y se vuelve a probar la vez siguiente."""
        builder = _FakeBuilder(missing=("ace",))
        found = self._shared("a", builder)
        self.assertEqual(found.missing, frozenset({"ace"}))
        self.assertEqual({key[1] for key in found.bases}, {"jet4"})
        (entry,) = [p for p in self.store.iterdir() if p.name.startswith(
            recmin.STORE_ENTRY_PREFIX)]
        stored = next(entry.glob("*.mdb"))
        stored.write_bytes(stored.read_bytes()[:-1] + b"X")
        builder.missing = frozenset()
        again = self._shared("b", builder)
        self.assertEqual(builder.calls, [("jet4", "ace"), ("jet4", "ace")])
        self.assertEqual(again.missing, frozenset())
        self.assertEqual(_without_paths(again)[(V12, "jet4")],
                         _without_paths(found)[(V12, "jet4")])
        third = self._shared("c", builder)
        self.assertEqual(len(builder.calls), 2)
        self.assertEqual(_without_paths(third), _without_paths(again))

    def test_the_key_is_the_script_and_the_builder(self) -> None:
        """RNF-001-01: la entrada depende del motor, del nombre y del texto de cada guion y de
        ``build_mdb.ps1``: el mismo guion en otra carpeta da la misma; otro texto, otra."""
        one = _write_script(self.tmp / "x", "v.sql", "-- uno\n")
        same = _write_script(self.tmp / "y", "v.sql", "-- uno\n")
        other = _write_script(self.tmp / "z", "v.sql", "-- dos\n")
        renamed = _write_script(self.tmp / "z", "w.sql", "-- uno\n")
        key = recmin.store_key("jet4", one)
        self.assertEqual(key, recmin.store_key("jet4", same))
        self.assertNotEqual(key, recmin.store_key("ace", one))
        self.assertNotEqual(key, recmin.store_key("jet4", other))
        self.assertNotEqual(key, recmin.store_key("jet4", renamed))
        self.assertNotEqual(key, recmin.store_key("jet4"))
        default = recmin.store_key("jet4")
        with mock.patch.object(recmin, "BUILD_SCRIPT", one):
            self.assertNotEqual(recmin.store_key("jet4"), default)
        builder = _FakeBuilder()
        self._shared("a", builder, ("jet4",), sql=one)
        self._shared("b", builder, ("jet4",), sql=same)
        self._shared("c", builder, ("jet4",), sql=other)
        self.assertEqual(builder.calls, [("jet4",), ("jet4",)])

    def test_at_the_same_time_one_entry(self) -> None:
        """RNF-001-01: varias pruebas que las piden a la vez (cada parte de la comprobación es
        un proceso) acaban con las mismas bases y una sola entrada por motor, sin restos."""
        builder = _FakeBuilder(delay_s=0.2)
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            builds = list(pool.map(lambda n: self._shared(f"p{n}", builder), range(4)))
        self.assertTrue(all(_without_paths(b) == _without_paths(builds[0]) for b in builds))
        self.assertEqual(len(_entries(self.store)), 2, _entries(self.store))

    def test_default_store_in_the_system_temp(self) -> None:
        """RF-001-09, RNF-001-01: el almacén está en la carpeta temporal del sistema, fuera
        del repositorio, también si una prueba cambia la de su proceso (``tempfile.tempdir``)."""
        system = Path(tempfile.gettempdir())
        self.assertEqual(recmin.default_store(), system / recmin.STORE_FOLDER)
        with mock.patch.object(tempfile, "tempdir", str(self.tmp)):
            self.assertEqual(recmin.default_store(), system / recmin.STORE_FOLDER)

    def test_old_entries_are_removed(self) -> None:
        """RF-001-09 (la carpeta temporal no crece sin fin): una entrada que nadie usa desde
        hace más de ``STORE_KEEP_DAYS`` días, y un resto a medias de más de un día, se
        borran; la que se usa, no."""
        builder = _FakeBuilder()
        self._shared("a", builder, ("jet4",))
        old = self.store / f"{recmin.STORE_ENTRY_PREFIX}0123456789abcdef"
        (old / "x.mdb").parent.mkdir(parents=True)
        (old / "x.mdb").write_bytes(b"x")
        leftover = self.store / f"{recmin.STORE_TEMP_PREFIX}resto"
        leftover.mkdir()
        long_ago = time.time() - (recmin.STORE_KEEP_DAYS + 1) * 86400
        for path in (old, old / "x.mdb", leftover):
            os.utime(path, (long_ago, long_ago))
        self._shared("b", builder, ("jet4",))
        self.assertFalse(old.exists())
        self.assertFalse(leftover.exists())
        self.assertEqual(len(_entries(self.store)), 1)
        self.assertEqual(builder.calls, [("jet4",)])


def _write_script(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


@unittest.skipUnless(os.name == "nt", skip_reason(WINDOWS, WINDOWS_HINT))
class SharedRealBasesTest(unittest.TestCase):
    """``recmin.shared_bases`` con ``build_mdb.ps1`` y su almacén de verdad."""

    def test_same_bases_as_build_bases(self) -> None:
        """RF-005-13, RNF-001-01: las bases compartidas (Jet 4 y, si hay, ACE) tienen la
        cabecera de su formato y las mismas tablas, filas y tipos que las que acaba de crear
        ``build_bases`` (:func:`setUpModule`), en la carpeta de la prueba."""
        assert _build is not None
        engines = ("jet4", "ace") if is_available(recmin.ACE) else ("jet4",)
        with tempfile.TemporaryDirectory(prefix="gbrsr") as tmp:
            shared = recmin.shared_bases(Path(tmp), engines)
            self.assertEqual(shared.missing, _build.missing)
            self.assertEqual(sorted(shared.bases), sorted(_build.bases))
            for key, base in shared.bases.items():
                with self.subTest(base=key):
                    fresh = _build.bases[key]
                    self.assertEqual(base.path.parent, Path(tmp))
                    self.assertEqual(base.path.name, fresh.path.name)
                    self.assertEqual(base.tables, fresh.tables)
                    header, version = HEADERS[base.engine]
                    data = base.path.read_bytes()[:0x15]
                    self.assertEqual((data[4:4 + len(header)], data[0x14]), (header, version))


if __name__ == "__main__":
    unittest.main()
