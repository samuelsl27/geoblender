# SPDX-License-Identifier: GPL-3.0-or-later
"""Bases RecMin sintéticas para las pruebas de la spec 005 (T02; plan 005 §2.1 y §7).

Los guiones de ``tests/data/dh/recmin/`` (``recmin_v11.sql`` y ``recmin_v12.sql``, Jet
SQL en UTF-8) describen dos bases RecMin inventadas; ``build_mdb.ps1`` crea con cada uno
una base Jet 4 (``Microsoft.Jet.OLEDB.4.0``, que solo existe en el ``powershell.exe`` de
32 bits) y otra ACE (ACE 16 o 12, en el de 64 bits), siempre en la carpeta que se le da
(una temporal: ninguna base se versiona). Aquí:

- :func:`parse_sql` lee un guion sin motor: sus tablas, con sus columnas (nombre, tipo de
  Jet SQL y tamaño) y sus filas (columna → valor: ``None``, ``bool``, ``int``,
  ``Decimal`` con el texto exacto del número, ``str`` o ``datetime``). Es la referencia con
  la que las pruebas comparan lo que lee el motor (T02) o el extractor (T16).
- :func:`build_bases` crea las bases de los dos guiones con los motores pedidos, los dos a
  la vez (un ``powershell.exe`` por motor, sin ventana), y devuelve lo que el motor contó en
  cada una (tablas, filas y tipos OLE DB de las columnas).
- :func:`shared_bases` da lo mismo, con las bases copiadas de un almacén de la carpeta
  temporal del sistema (:func:`default_store`) donde :func:`build_bases` las crea una sola
  vez por guion y motor (spec 005, T44; RNF-001-01): crear una base lanza un
  ``powershell.exe`` (≈ 2 s de procesador) y varias pruebas, en cada comprobación y en dos
  pasos («unitarias» y «motor»), necesitan las mismas. Cada entrada (:func:`store_key`)
  depende del motor, del nombre y del texto de cada guion y de ``build_mdb.ps1``; guarda la
  huella de cada base, que se comprueba antes de copiarla (una que ya no es la que se guardó
  se crea otra vez), y se borra si nadie la usa en :data:`STORE_KEEP_DAYS` días. Un motor
  que falta no se guarda. Las pruebas del propio guion (``test_recmin_fixture``) siguen
  creándolas con :func:`build_bases`.
- El recurso ``ace`` (:data:`ACE`, ``tests.support.resources``) está disponible si el
  registro de 64 bits tiene un proveedor OLE DB ACE (16.0 o 12.0); sin él, las pruebas de la
  base ACE se omiten con ``[ENTORNO] ace``. Jet 4.0 de 32 bits viene con Windows.
- :func:`raw_tables` da las tablas de un guion como las dará el extractor de la base (T16):
  ``interop.ports.RawTable`` en memoria, con el tipo OLE DB de cada columna (:data:`OLEDB_TYPES`)
  y sus valores con el tipo de Python del motor (Single como ``numpy.float32``, Double como
  ``float``). Las usan las pruebas del lector de RecMin (T15), sin motor.
- :func:`vref_script` escribe V-ref (``tests/data/dh/sintetico.py``; spec 005 §5) como el guion
  de una base de RecMin con el esquema de ``recmin_v12.sql`` y :func:`vref_base` crea con él la
  base ACE (``build_mdb.ps1``, por :func:`shared_bases`) de la prueba de rendimiento de la
  importación de RecMin (T33). Ni el guion ni la base se versionan.
"""

from __future__ import annotations

import datetime
import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import numpy as np

from tests.data.dh import sintetico
from tests.support import resources
from tests.support.package import import_geoblender
from tests.support.repo import ROOT

ACE = "ace"  # el recurso de tests.support.resources
ACE_HINT = (
    "instale el motor de bases de datos de Access de Microsoft de 64 bits (gratuito; "
    "proveedor OLE DB Microsoft.ACE.OLEDB.16.0 o 12.0), u Office de 64 bits"
)
ACE_PROVIDERS: tuple[str, ...] = ("Microsoft.ACE.OLEDB.16.0", "Microsoft.ACE.OLEDB.12.0")
JET_PROVIDER = "Microsoft.Jet.OLEDB.4.0"

RECMIN_DIR = ROOT / "tests" / "data" / "dh" / "recmin"
BUILD_SCRIPT = RECMIN_DIR / "build_mdb.ps1"
SQL_NAMES: tuple[str, ...] = ("recmin_v11.sql", "recmin_v12.sql")

# Motor → argumento -Engine de build_mdb.ps1 y bits de su powershell.exe.
ENGINES: dict[str, tuple[str, int]] = {"jet4": ("Jet4", 32), "ace": ("Ace", 64)}
BUILD_TIMEOUT_S = 120.0
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ace_available() -> bool:
    """Si el registro de 64 bits tiene un proveedor OLE DB ACE (lo que necesita el
    ``powershell.exe`` de 64 bits de :func:`build_bases`)."""
    if os.name != "nt":
        return False
    import winreg

    for provider in ACE_PROVIDERS:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT,
                f"{provider}\\CLSID",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ):
                return True
        except OSError:
            continue
    return False


resources.register_resource(ACE, ace_available)


def powershell(bits: int) -> Path:
    """El ``powershell.exe`` de Windows de 64 o 32 bits (visto desde un proceso de 64)."""
    folder = {64: "System32", 32: "SysWOW64"}[bits]
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return root / folder / "WindowsPowerShell" / "v1.0" / "powershell.exe"


# ---------------------------------------------------------------------------------------
# Lectura de los guiones (sin motor)
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SqlColumn:
    """Una columna de un ``CREATE TABLE``: nombre, tipo de Jet SQL (``LONG``, ``SINGLE``,
    ``TEXT``…) y tamaño (``TEXT(n)``; ``None`` en los demás)."""

    name: str
    type: str
    size: int | None


@dataclass(frozen=True)
class SqlTable:
    """Una tabla de un guion, con sus columnas en orden y sus filas (columna → valor)."""

    name: str
    columns: tuple[SqlColumn, ...]
    rows: tuple[dict[str, object], ...]

    def column(self, name: str) -> SqlColumn:
        """La columna ``name`` (``KeyError`` si no está)."""
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(f"{self.name}: no tiene la columna {name!r}")


_CREATE = re.compile(r"^CREATE TABLE \[(?P<name>[^\]]+)\]\s*\((?P<body>.*)\)$", re.DOTALL)
_INSERT = re.compile(
    r"^INSERT INTO \[(?P<name>[^\]]+)\]\s*\((?P<columns>[^)]*)\)\s*VALUES\s*\((?P<values>.*)\)$",
    re.DOTALL,
)
_COLUMN = re.compile(r"^\[(?P<name>[^\]]+)\]\s+(?P<type>[A-Z]+)(?:\((?P<size>\d+)\))?(?:\s.*)?$")
_TOKEN = re.compile(
    r"\s*(?:"
    r"'(?P<text>(?:[^']|'')*)'"
    r"|#(?P<date>[^#]+)#"
    r"|(?P<number>-?\d+(?:\.\d+)?)"
    r"|(?P<word>NULL|TRUE|FALSE)"
    r")\s*(?:,|$)"
)


def _statements(text: str, where: str) -> list[str]:
    """Las sentencias de un guion, como las parte ``build_mdb.ps1``: sin las líneas de
    comentario («--») ni las vacías, cada una hasta el «;» que acaba una línea."""
    statements: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(current).strip()
            statements.append(statement[:-1])
            current = []
    if current:
        raise ValueError(f"{where}: la última sentencia no acaba en «;»")
    return statements


def _columns(body: str, where: str) -> tuple[SqlColumn, ...]:
    columns: list[SqlColumn] = []
    for part in body.split(","):
        match = _COLUMN.match(part.strip())
        if match is None:
            raise ValueError(f"{where}: columna que no se entiende: {part.strip()!r}")
        size = match["size"]
        columns.append(SqlColumn(match["name"], match["type"], int(size) if size else None))
    return tuple(columns)


def _values(text: str, where: str) -> list[object]:
    values: list[object] = []
    position = 0
    text = text.strip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None or match.end() == position:
            raise ValueError(f"{where}: valor que no se entiende en {text[position:]!r}")
        if match["text"] is not None:
            values.append(match["text"].replace("''", "'"))
        elif match["date"] is not None:
            values.append(datetime.datetime.fromisoformat(match["date"]))
        elif match["number"] is not None:
            number = match["number"]
            values.append(Decimal(number) if "." in number else int(number))
        else:
            values.append({"NULL": None, "TRUE": True, "FALSE": False}[match["word"]])
        position = match.end()
    return values


def parse_sql(path: Path) -> dict[str, SqlTable]:
    """Las tablas de un guion de ``tests/data/dh/recmin/`` en el orden en que las crea,
    con sus filas; ``ValueError`` si una sentencia no es ``CREATE TABLE`` ni ``INSERT
    INTO`` o se refiere a una tabla o una columna que no existe."""
    columns: dict[str, tuple[SqlColumn, ...]] = {}
    rows: dict[str, list[dict[str, object]]] = {}
    for number, statement in enumerate(
        _statements(Path(path).read_text(encoding="utf-8"), str(path)), start=1
    ):
        where = f"{path}: sentencia {number}"
        if (create := _CREATE.match(statement)) is not None:
            name = create["name"]
            if name in columns:
                raise ValueError(f"{where}: la tabla {name} ya existe")
            columns[name] = _columns(create["body"], where)
            rows[name] = []
        elif (insert := _INSERT.match(statement)) is not None:
            name = insert["name"]
            if name not in columns:
                raise ValueError(f"{where}: la tabla {name} no existe")
            names = [c.strip().strip("[]") for c in insert["columns"].split(",")]
            unknown = set(names) - {c.name for c in columns[name]}
            values = _values(insert["values"], where)
            if unknown or len(values) != len(names):
                raise ValueError(f"{where}: columnas {names} y valores {values}")
            rows[name].append(dict(zip(names, values, strict=True)))
        else:
            raise ValueError(f"{where}: no es CREATE TABLE ni INSERT INTO: {statement[:60]!r}")
    return {
        name: SqlTable(name, columns[name], tuple(rows[name])) for name in columns
    }


# ---------------------------------------------------------------------------------------
# Las tablas crudas en memoria (las que dará el extractor, T16)
# ---------------------------------------------------------------------------------------

# DATA_TYPE de OLE DB de cada tipo de Jet SQL de los guiones (lo que cuenta el motor).
OLEDB_TYPES: dict[str, int] = {
    "SHORT": 2, "LONG": 3, "COUNTER": 3, "SINGLE": 4, "DOUBLE": 5, "DATETIME": 7, "BIT": 11,
    "TEXT": 130, "MEMO": 130,
}


def _raw_value(value: object, kind: str, singles_as_float: bool) -> object:
    """Un valor del guion con el tipo de Python que da el motor para su columna."""
    if value is None:
        return None
    if kind == "SINGLE":
        single = np.float32(float(value))  # el Single de ese decimal
        return float(single) if singles_as_float else single
    if kind == "DOUBLE":
        return float(value)  # el Double más próximo al decimal escrito
    if kind == "BIT":
        return bool(value)
    if kind in ("SHORT", "LONG", "COUNTER"):
        return int(value)
    return value


def raw_tables(path: Path, *, singles_as_float: bool = False,
               ports: ModuleType | None = None) -> dict[str, object]:
    """Las tablas del guion ``path`` como ``interop.ports.RawTable`` (nombre tal como lo
    escribe el guion → tabla): columnas con su tipo OLE DB y tamaño (``TEXT(n)``: n; ``MEMO``:
    0) y filas con el valor de cada columna (``None`` si el guion no lo da). Con
    ``singles_as_float``, los Single llegan como el ``float`` exacto de su ``float32``.
    ``ports``: el módulo ``interop.ports`` que las crea (en Blender, el de la extensión
    habilitada); por defecto, el del paquete de las pruebas sin Blender."""
    if ports is None:
        ports = import_geoblender("interop.ports")
    found: dict[str, object] = {}
    for name, table in parse_sql(path).items():
        columns = tuple(
            ports.RawColumn(c.name, OLEDB_TYPES[c.type],
                            c.size if c.type == "TEXT" else (0 if c.type == "MEMO" else None))
            for c in table.columns
        )
        rows = tuple(
            tuple(_raw_value(row.get(c.name), c.type, singles_as_float) for c in table.columns)
            for row in table.rows
        )
        found[name] = ports.RawTable(name, columns, rows)
    return found


# ---------------------------------------------------------------------------------------
# Creación de las bases (con el motor)
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BuiltColumn:
    """Una columna como la describe el motor: ``DATA_TYPE`` de OLE DB y
    ``CHARACTER_MAXIMUM_LENGTH`` (``None`` en las que no son de texto)."""

    name: str
    type: int
    size: int | None


@dataclass(frozen=True)
class BuiltTable:
    """Una tabla de una base creada: filas que contó el motor y columnas en orden."""

    name: str
    rows: int
    columns: tuple[BuiltColumn, ...]


@dataclass(frozen=True)
class BuiltBase:
    """Una base creada por ``build_mdb.ps1``: motor (``jet4`` o ``ace``), guion, ruta,
    proveedor OLE DB que la creó y sus tablas por nombre."""

    engine: str
    sql: str
    path: Path
    provider: str
    tables: dict[str, BuiltTable]


@dataclass(frozen=True)
class Build:
    """Lo que creó :func:`build_bases`: las bases por (guion, motor) y los motores que
    faltaban (``ace`` sin ACE)."""

    bases: dict[tuple[str, str], BuiltBase]
    missing: frozenset[str]


def _base(record: dict) -> BuiltBase:
    tables = {
        t["name"]: BuiltTable(
            t["name"],
            int(t["rows"]),
            tuple(BuiltColumn(c["name"], int(c["type"]), c["size"]) for c in t["columns"]),
        )
        for t in record["tables"]
    }
    return BuiltBase(record["engine"], record["sql"], Path(record["path"]), record["provider"],
                     tables)


def build_bases(out_dir: Path, engines: tuple[str, ...] = tuple(ENGINES), *,
                sql: Path | None = None, timeout_s: float = BUILD_TIMEOUT_S) -> Build:
    """Crea en ``out_dir`` (que no debe tener ya esas bases) las bases de los dos guiones
    (con ``sql``, solo las de ese guion, que puede estar en otra carpeta: una variante escrita
    por la prueba) con cada motor de ``engines`` (``jet4``, ``ace``), un ``powershell.exe`` por
    motor y todos a la vez; ``RuntimeError`` con la salida de errores si alguno falla o tarda
    más de ``timeout_s`` segundos."""
    processes: dict[str, subprocess.Popen[bytes]] = {}
    chosen = [] if sql is None else ["-Sql", str(sql)]
    for engine in engines:
        argument, bits = ENGINES[engine]
        processes[engine] = subprocess.Popen(
            [
                str(powershell(bits)), "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(BUILD_SCRIPT),
                "-OutDir", str(out_dir), "-Engine", argument, *chosen,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATE_NO_WINDOW,
        )
    bases: dict[tuple[str, str], BuiltBase] = {}
    missing: set[str] = set()
    failures: list[str] = []
    for engine, process in processes.items():
        try:
            out, err = process.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            out, err = process.communicate()
            failures.append(f"{engine}: más de {timeout_s:.0f} s")
            continue
        if process.returncode != 0:
            failures.append(
                f"{engine}: código {process.returncode}: {err.decode('utf-8', 'replace')}"
            )
            continue
        for line in out.decode("utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("missing"):
                missing.add(record["engine"])
            else:
                base = _base(record)
                bases[(base.sql, base.engine)] = base
    if failures:
        raise RuntimeError("build_mdb.ps1 no creó las bases: " + " | ".join(failures))
    return Build(bases, frozenset(missing))


# ---------------------------------------------------------------------------------------
# Bases compartidas entre pruebas (spec 005, T44)
# ---------------------------------------------------------------------------------------

STORE_FOLDER = "geoblender-datos"  # el almacén, en la carpeta temporal del sistema
STORE_SCHEMA = "geoblender.recmin_bases/1"
STORE_ENTRY_PREFIX = "recmin-"  # una entrada por guiones y motor: recmin-<clave>
STORE_TEMP_PREFIX = ".a-medias-"  # lo que se está creando (o quedó a medias)
STORE_INDEX = "bases.json"  # en cada entrada: sus bases, con su huella y lo que contó el motor
STORE_KEEP_DAYS = 30  # una entrada que nadie usa en estos días se borra
_TEMP_KEEP_S = 86400.0  # un resto a medias de más de un día se borra
# La carpeta temporal del sistema al importar este módulo: la de una prueba que cambia la de
# su proceso (``tempfile.tempdir``, como test_dh_workers) no se lleva el almacén.
_SYSTEM_TEMP = Path(tempfile.gettempdir())


def default_store() -> Path:
    """El almacén de :func:`shared_bases`: en la carpeta temporal del sistema, fuera del
    repositorio (RF-001-09), compartido por todas las raíces (las bases solo dependen de los
    guiones), aunque una prueba cambie la carpeta temporal de su proceso."""
    return _SYSTEM_TEMP / STORE_FOLDER


def _scripts(sql: Path | None) -> list[Path]:
    """Los guiones que crea ``build_mdb.ps1``: el dado o, sin él, los ``*.sql`` de su
    carpeta, por su nombre."""
    return [Path(sql)] if sql is not None else sorted(RECMIN_DIR.glob("*.sql"))


def store_key(engine: str, sql: Path | None = None) -> str:
    """La clave de la entrada de las bases de ``engine`` con el guion ``sql`` (o los de la
    carpeta): el motor, el nombre y el texto de cada guion y ``build_mdb.ps1``."""
    digest = hashlib.sha256()
    for part in (STORE_SCHEMA.encode(), engine.encode(), BUILD_SCRIPT.read_bytes()):
        digest.update(part + b"\0")
    for script in _scripts(sql):
        digest.update(script.name.encode("utf-8") + b"\0" + script.read_bytes() + b"\0")
    return digest.hexdigest()[:16]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(base: BuiltBase, path: Path) -> dict:
    return {
        "sql": base.sql,
        "file": path.name,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "provider": base.provider,
        "tables": [
            {"name": table.name, "rows": table.rows,
             "columns": [[c.name, c.type, c.size] for c in table.columns]}
            for table in base.tables.values()
        ],
    }


def _built(record: dict, engine: str, path: Path) -> BuiltBase:
    tables = {
        t["name"]: BuiltTable(t["name"], int(t["rows"]),
                              tuple(BuiltColumn(n, int(k), s) for n, k, s in t["columns"]))
        for t in record["tables"]
    }
    return BuiltBase(engine, record["sql"], path, record["provider"], tables)


def _discard(folder: Path, store: Path) -> None:
    """Quita una carpeta del almacén: primero la aparta (nadie la toma ya por buena) y
    después la borra."""
    aside = store / f"{STORE_TEMP_PREFIX}{uuid.uuid4().hex}"
    try:
        os.rename(folder, aside)
    except OSError:
        return
    shutil.rmtree(aside, ignore_errors=True)


def _entry(store: Path, key: str) -> list[dict] | None:
    """Las bases de la entrada ``key`` si existe y cada una es la que se guardó (tamaño y
    sha256); si no vale, se quita y ``None``. Al usarla, cuenta como usada hoy."""
    folder = store / f"{STORE_ENTRY_PREFIX}{key}"
    index = folder / STORE_INDEX
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
        records = data["bases"] if data.get("schema") == STORE_SCHEMA else None
        if not records or not all(
            (folder / r["file"]).stat().st_size == r["size"]
            and _sha256(folder / r["file"]) == r["sha256"]
            for r in records
        ):
            records = None
    except (OSError, ValueError, KeyError, TypeError):
        records = None
    if records is None:
        if folder.exists():
            _discard(folder, store)
        return None
    os.utime(index)
    return records


def _keep(store: Path, key: str, engine: str, bases: list[BuiltBase]) -> list[dict] | None:
    """Guarda como entrada ``key`` las bases recién creadas de ``engine`` (se mueven a una
    carpeta a medias que, completa, toma su nombre de golpe). Si otra prueba la guardó antes,
    se usa la suya."""
    folder = store / f"{STORE_TEMP_PREFIX}{engine}-{uuid.uuid4().hex}"
    folder.mkdir()
    records = []
    for base in bases:
        target = folder / base.path.name
        os.replace(base.path, target)
        records.append(_record(base, target))
    index = {"schema": STORE_SCHEMA, "engine": engine, "bases": records}
    (folder / STORE_INDEX).write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    try:
        os.rename(folder, store / f"{STORE_ENTRY_PREFIX}{key}")
    except OSError:  # ya existe: la guardó otra prueba a la vez
        shutil.rmtree(folder, ignore_errors=True)
        return _entry(store, key)
    return records


def _prune(store: Path) -> None:
    """Borra las entradas que nadie usa desde hace :data:`STORE_KEEP_DAYS` días y los restos
    a medias de más de un día."""
    now = time.time()
    for folder in store.iterdir():
        try:
            if folder.name.startswith(STORE_ENTRY_PREFIX):
                index = folder / STORE_INDEX
                used = (index if index.exists() else folder).stat().st_mtime
                if now - used > STORE_KEEP_DAYS * 86400:
                    _discard(folder, store)
            elif folder.name.startswith(STORE_TEMP_PREFIX):
                if now - folder.stat().st_mtime > _TEMP_KEEP_S:
                    shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


def shared_bases(
    out_dir: Path,
    engines: tuple[str, ...] = tuple(ENGINES),
    *,
    sql: Path | None = None,
    store: Path | None = None,
    build: Callable[..., Build] | None = None,
) -> Build:
    """Lo mismo que :func:`build_bases` en ``out_dir`` (que no debe tener ya esas bases),
    con cada base copiada del almacén ``store`` (:func:`default_store`); las que no están,
    o ya no son las que se guardaron, las crea ``build`` (:func:`build_bases`), todos esos
    motores a la vez, y se guardan. Un motor que falta (sin ACE) no se guarda."""
    store = default_store() if store is None else Path(store)
    build = build_bases if build is None else build
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    store.mkdir(parents=True, exist_ok=True)
    keys = {engine: store_key(engine, sql) for engine in engines}
    entries = {engine: _entry(store, keys[engine]) for engine in engines}
    absent = tuple(engine for engine in engines if entries[engine] is None)
    missing: set[str] = set()
    if absent:
        with tempfile.TemporaryDirectory(prefix=STORE_TEMP_PREFIX, dir=store) as work:
            made = build(Path(work), absent, sql=sql)
            for engine in absent:
                if engine in made.missing:
                    missing.add(engine)
                    continue
                bases = [base for (_sql, made_engine), base in sorted(made.bases.items())
                         if made_engine == engine]
                entries[engine] = _keep(store, keys[engine], engine, bases)
    found: dict[tuple[str, str], BuiltBase] = {}
    for engine in engines:
        records = entries[engine]
        if records is None:
            continue
        folder = store / f"{STORE_ENTRY_PREFIX}{keys[engine]}"
        for record in records:
            target = out_dir / record["file"]
            if target.exists():
                raise FileExistsError(f"{target}: ya existe; no se sustituye")
            shutil.copyfile(folder / record["file"], target)
            base = _built(record, engine, target)
            found[(base.sql, engine)] = base
    _prune(store)
    return Build(found, frozenset(missing))


# ---------------------------------------------------------------------------------------
# V-ref como base de RecMin (spec 005, T33)
# ---------------------------------------------------------------------------------------

VREF_SQL = "recmin_vref.sql"
"""El nombre del guion de V-ref (:func:`vref_script`); su base ACE es ``recmin_vref_ace.mdb``."""
VREF_SCHEMA = RECMIN_DIR / "recmin_v12.sql"
"""El guion del que toma su esquema: el 12, el de ``default.mdb`` de RecMin Pro."""
VREF_EXTRA_TABLES = frozenset({"alteracion", "duplicados"})
"""Las tablas adicionales de ese guion, que V-ref no tiene."""
VREF_SAMPLES = "muestras"
"""La tabla de las muestras, que en V-ref tiene un ``ELEMENTO n`` Single por cada elemento."""
VREF_BUILD_TIMEOUT_S = 900.0
"""Lo que puede tardar ``build_mdb.ps1`` con V-ref (unas 97.000 sentencias: alrededor de un
minuto en el PC de referencia, lo que tarda el motor en cada una)."""
_VREF_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _vref_number(text: str) -> str:
    """Un número de V-ref (coma decimal; «<x» bajo el límite de detección) en Jet SQL, con
    punto: «<x» es el valor negativo −x (como lo guarda RecMin, «−x = <x»)."""
    number = text.replace(",", ".")
    if number.startswith("<"):
        number = "-" + number[1:]
    if _VREF_NUMBER.fullmatch(number) is None:
        raise ValueError(f"V-ref: {text!r} no es un número")
    return number


def _vref_date(text: str) -> str:
    """Una fecha de V-ref (dd/mm/aaaa) como literal de Jet SQL (#aaaa-mm-dd#)."""
    day = datetime.datetime.strptime(text, "%d/%m/%Y").date()
    return f"#{day.isoformat()}#"


def _vref_text(text: str) -> str:
    """Un texto como literal de Jet SQL, entre comillas simples."""
    quote = "'"
    return quote + text.replace(quote, quote * 2) + quote


def _vref_bgr(color: str) -> int:
    """El ``COLOR`` de RecMin (BGR de Windows) de un color «#RRGGBB»."""
    red, green, blue = (int(color[k:k + 2], 16) for k in (1, 3, 5))
    return blue * 65536 + green * 256 + red


def _vref_insert(table: str, columns: tuple[str, ...], values: list[object]) -> str:
    names = ", ".join(f"[{name}]" for name in columns)
    return f"INSERT INTO [{table}] ({names}) VALUES ({', '.join(map(str, values))});"


def _vref_schema(elements: int) -> list[str]:
    """Los ``CREATE TABLE`` de :data:`VREF_SCHEMA` sin :data:`VREF_EXTRA_TABLES` y con
    ``muestras`` de ``elements`` columnas ``ELEMENTO n`` Single."""
    text = VREF_SCHEMA.read_text(encoding="utf-8")
    found: list[str] = []
    for statement in _statements(text, str(VREF_SCHEMA)):
        create = _CREATE.match(statement)
        if create is None or create["name"] in VREF_EXTRA_TABLES:
            continue
        name = create["name"]
        if name == VREF_SAMPLES:
            fields = [f"[ID] COUNTER CONSTRAINT [pk_{name}] PRIMARY KEY", "[DESDE] SINGLE",
                      "[HASTA] SINGLE", "[IDSONDEO] LONG",
                      *(f"[ELEMENTO {n}] SINGLE" for n in range(1, elements + 1))]
            statement = f"CREATE TABLE [{name}] (\n  " + ",\n  ".join(fields) + "\n)"
        found.append(statement + ";")
    return found


def vref_script(tables: Mapping[str, sintetico.Table] | None = None) -> str:
    """V-ref (``tables``: las seis tablas de ``sintetico.vref_tables``, en el formato de
    ``csv_basico``; por defecto, las de su semilla) como guion de una base de RecMin con el
    esquema de :data:`VREF_SCHEMA` (``build_mdb.ps1`` lo convierte en una base): los mismos
    sondeos, estaciones, tramos y valores, con las coordenadas y los ángulos en Double, los
    tramos y las leyes en Single (``DESDE``, ``HASTA`` y un ``ELEMENTO n`` por cada elemento, en
    el orden de su catálogo), «<x» como el valor negativo −x, los colores en BGR y la versión
    de esquema 12. RecMin no guarda la profundidad ni el tipo de los sondeos (la profundidad se
    deduce de sus estaciones y sus tramos) ni el nombre de cada muestra."""
    tables = sintetico.vref_tables() if tables is None else tables
    elements = tables["elementos.csv"].rows
    codes = [row[0] for row in elements]
    assays = tables["analisis_columnas.csv"]
    if list(assays.header[4:]) != codes:
        raise ValueError(f"V-ref: las leyes {assays.header[4:]} no son las de su catálogo "
                         f"{codes}")
    lines = [
        "-- V-ref (spec 005 §5) como base de RecMin con el esquema 12; lo escribe",
        "-- tests.support.recmin.vref_script y no se versiona.",
        *_vref_schema(len(codes)),
    ]
    holes: dict[str, int] = {}
    planned = {"sí": "TRUE", "no": "FALSE"}
    for number, row in enumerate(tables["bocas.csv"].rows, start=1):
        name, east, north, elevation = row[:4]
        holes[name] = number
        lines.append(_vref_insert(
            "sondeos", ("IDSONDEO", "SONDEO", "ESTE", "NORTE", "ELEVACION", "PLAN",
                        "FECHA INI", "FECHA FIN", "CONTROL"),
            [number, _vref_text(name), _vref_number(east), _vref_number(north),
             _vref_number(elevation), planned[row[11]], _vref_date(row[9]),
             _vref_date(row[10]), "FALSE"]))
    for number, (name, depth, azimuth, inclination) in enumerate(
            tables["desviaciones.csv"].rows, start=1):
        lines.append(_vref_insert(
            "angulos", ("ID", "IDSONDEO", "DISTANCIA", "INCLINACION", "DIRECCION"),
            [number, holes[name], _vref_number(depth), _vref_number(inclination),
             _vref_number(azimuth)]))
    lithology_codes = tables["litologias.csv"].rows
    catalog = {row[0]: number for number, row in enumerate(lithology_codes, start=1)}
    for number, (name, start, end, code) in enumerate(tables["litologia.csv"].rows, start=1):
        lines.append(_vref_insert("litologia", ("ID", "DESDE", "HASTA", "IDSONDEO", "IDLITO"),
                                  [number, _vref_number(start), _vref_number(end),
                                   holes[name], catalog[code]]))
    for number, (code, description, color, density, order) in enumerate(lithology_codes,
                                                                         start=1):
        bgr = _vref_bgr(color)
        lines.append(_vref_insert(
            "idlitologia", ("IDLITO", "NOMBRE CORTO", "COLOR", "ESTILO", "DESCRIPCION",
                            "COLORPRINT", "ESTILOPRINT", "VER", "DENSIDAD", "ORDEN"),
            [number, _vref_text(code), bgr, 0, _vref_text(description), bgr, 0, "TRUE",
             _vref_number(density), int(order)]))
    value_columns = tuple(f"ELEMENTO {n}" for n in range(1, len(codes) + 1))
    for number, (name, start, end, _sample, *values) in enumerate(assays.rows, start=1):
        lines.append(_vref_insert(
            VREF_SAMPLES, ("ID", "DESDE", "HASTA", "IDSONDEO", *value_columns),
            [number, _vref_number(start), _vref_number(end), holes[name],
             *(_vref_number(value) for value in values)]))
    for number, (code, _name, unit, decimals, _limit) in enumerate(elements, start=1):
        lines.append(_vref_insert(
            "elementos", ("ELEMENTO", "NOMBRE", "UNIDAD", "TABLA", "CALCULO", "ORDEN",
                          "DECIMALES", "CONTADOR"),
            [number, _vref_text(code), _vref_text(unit), "TRUE", "TRUE", number,
             int(decimals), number]))
    lines.append(_vref_insert("actualizacion", ("ULTIMA",), [12]))
    return "\n".join(lines) + "\n"


def vref_base(out_dir: Path, tables: Mapping[str, sintetico.Table] | None = None, *,
              store: Path | None = None) -> BuiltBase:
    """V-ref (``tables``, como en :func:`vref_script`) como base de RecMin en formato ACE en
    ``out_dir`` (que no debe tenerla ya): su guion (:data:`VREF_SQL`, escrito en ``out_dir`` y
    borrado después) y su base, que crea ``build_mdb.ps1`` con el motor por
    :func:`shared_bases` (del almacén ``store``, :func:`default_store`, si ya se creó con el
    mismo guion; plazo :data:`VREF_BUILD_TIMEOUT_S`). ``RuntimeError`` sin ACE."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    script = out_dir / VREF_SQL
    script.write_text(vref_script(tables), encoding="utf-8", newline="\n")
    try:
        made = shared_bases(out_dir, (ACE,), sql=script, store=store,
                            build=functools.partial(build_bases,
                                                    timeout_s=VREF_BUILD_TIMEOUT_S))
    finally:
        script.unlink(missing_ok=True)
    if ACE in made.missing:
        raise RuntimeError(f"sin el motor ACE no se crea la base de V-ref: {ACE_HINT}")
    return made.bases[(VREF_SQL, ACE)]
