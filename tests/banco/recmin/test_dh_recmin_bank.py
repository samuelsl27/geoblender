# SPDX-License-Identifier: GPL-3.0-or-later
"""Banco de RecMin: la importación de una base real de RecMin frente a una lectura directa con
el motor de Access (spec 005, T34; CE-005-05; RF-005-03, RF-005-13; D-3 y DP-65; plan 005 §7,
«Banco RecMin», y §5.6).

CE-005-05: la base real se importa en solo lectura con los mismos sondeos y muestras que en
RecMin, y su carpeta no cambia.

Lo ejecuta el arnés de los bancos de la 001 (``tools/bench_silvestre.py``, fila ``recmin`` de
``BANKS``) solo con ``tools/check.py --banco`` y con ``GEOBLENDER_RECMIN_BANK_DIR`` apuntando a
la carpeta del banco; sin la variable (o si no es una carpeta), se omite. Necesita el motor de
Access de 64 bits (ACE 16 o 12): sin él no se puede contrastar, y la comparación falla con lo
que hay que instalar (un banco sin contrastar nunca da verde). **Solo lectura**: del banco solo
se leen sus ficheros (el motor abre siempre una copia en ``%TEMP%``: junto a la base que abre
crea su ``.laccdb``), y el arnés y estas comparaciones comprueban que la carpeta queda igual.
Lo que se escribe (las copias, el proyecto temporal y sus trabajos) va a una carpeta temporal
de ``%TEMP%`` que se borra. Ni la ruta ni el nombre de ningún fichero del banco se escriben aquí
ni en la salida, ni ningún dato suyo: solo los nombres de las tablas de RecMin, los recuentos y
las diferencias de la comparación.

1. **Las bases**: cada ``.mdb`` o ``.accdb`` del banco (y de sus subcarpetas, sin seguir
   enlaces) de formato Jet 4 o ACE por su cabecera (``interop.ports.read_format``, sin motor)
   que tiene la tabla ``SONDEOS``; las copias iguales (mismo sha256) cuentan como una. Si no hay
   ninguna, la comparación falla con el motivo.
2. **La lectura directa** con el motor (``count_mdb.ps1``, en un ``powershell.exe`` de 64 bits,
   sobre una copia): el ``COUNT(*)`` de cada tabla y, de cada columna ``ELEMENTO n``, sus
   valores (sin nulos ni blancos) y su suma y la de sus valores absolutos, que suma el motor en
   doble precisión (``SUM(CDbl(…))``); y la tabla ``ELEMENTOS``. No usa nada de Geoblender.
3. **La importación**, como la hace Blender (``tests.support.recmin_import``: la lectura
   ``dh_import_recmin`` en proceso aparte con la base por su ruta y su copia verificada, la
   aplicación ``dh_import_apply`` y lo importado escrito por pasos con el original de la base),
   en un proyecto temporal nuevo. Lo declarado: el CRS y el datum del propio proyecto temporal
   (EPSG:25830 y EPSG:5782), así que nada se transforma, y ninguna coordenada se compara ni se
   usa: no es una suposición sobre la base, que no declara el suyo; el azimut, de cuadrícula
   (no se convierte); los negativos, tal cual (la copia literal de DP-41: así se suman como en
   RecMin); y leída aunque su versión de esquema no sea 11 ni 12 (como «Leer igualmente»: se
   dice en la línea de la comparación).
4. **El hash de contenido** de la base por el trabajo ``core_content_hash``
   (``jobs.content_hash.run``, con la base por su ruta y su copia verificada) con lo que guardó
   su importación en ``gb_input`` (su lector, su tipo, sus declaraciones y sus ajustes), como
   lo pide «Comprobar las entradas» (008).
5. **La foto** de la carpeta del banco (listado, tamaños, fechas y sha256 de cada fichero:
   ``tests.support.provenance_checks.source_state``) antes y después de todo.

Las cifras se imprimen en una línea ``CE-005-05: …`` por base, para anotarlas en la
verificación de la T34.
"""

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.support import recmin, recmin_import
from tests.support.core_fixtures import make_session, make_settings
from tests.support.package import import_geoblender
from tests.support.provenance_checks import source_changes, source_state
from tests.support.repo import EXTENSION_DIR, ROOT
from tests.support.trees import remove_tree

ports = import_geoblender("interop.ports")
recmin_schema = import_geoblender("interop.recmin.schema")
recmin_drillholes = import_geoblender("interop.recmin.drillholes")
model = import_geoblender("drillholes.model")
schema = import_geoblender("drillholes.schema")
store = import_geoblender("drillholes.store")
create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
inputs_mod = import_geoblender("core.inputs")
checks = import_geoblender("core.provenance.checks")
encoder = import_geoblender("core.content.encoder")
gis_store = import_geoblender("gis.store")
content_hash = import_geoblender("jobs.content_hash")
job_paths = import_geoblender("jobs.paths")
worker_api = import_geoblender("jobs.worker_api")

ENV = "GEOBLENDER_RECMIN_BANK_DIR"
SCRIPT = Path(__file__).with_name("count_mdb.ps1")
BASE_SUFFIXES = (".mdb", ".accdb")
ACCESS_SUFFIXES = (".mdb", ".accdb", ".ldb", ".laccdb")  # ninguno, en el repositorio
READ_FORMATS = ("jet4", "ace")  # los de RecMin (RF-005-13)
COLLARS = "SONDEOS"  # la tabla sin la que no es una base de sondeos de RecMin
REPOSITORY_FOLDERS = (EXTENSION_DIR, ROOT / "tools", ROOT / "tests")  # sin datos del banco
COUNT_TIMEOUT_S = 1800.0  # la lectura directa de una base grande
DECIMAL = recmin_import.DECIMAL
# Diferencia de cada valor importado frente al del motor: un Single, por su decimal más corto
# (RF-005-02), dista de su valor en doble precisión menos de medio ulp de precisión simple
# (2⁻²⁴ de su valor); y cada suma en doble precisión del motor añade como mucho 2⁻⁵³ de la suma
# de los absolutos.
SINGLE_ERROR = 2.0 ** -24
DOUBLE_ERROR = 2.0 ** -53
NOT_COUNTED = ("version", "rotations")  # ACTUALIZACION y GIROS: no van al informe por tabla
NOT_RECORDED = ("formulas",)  # FORMULAS: un elemento por nombre, no un registro por fila
SAMPLES = "samples"


def _report(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _count(value: int) -> str:
    """Un entero con punto de millares."""
    return f"{value:,}".replace(",", ".")


# --- La lectura directa con el motor -------------------------------------------------------


@dataclass(frozen=True)
class _EngineElement:
    """Una columna ``ELEMENTO n`` según el motor: su tipo (``DATA_TYPE`` de OLE DB), sus
    valores y, si es numérica, su suma y la de sus valores absolutos."""

    column: str
    type: int
    count: int
    sum: float | None
    abs_sum: float | None


@dataclass(frozen=True)
class _EngineTable:
    name: str
    rows: int
    columns: tuple[str, ...]
    elements: tuple[_EngineElement, ...]


@dataclass(frozen=True)
class _Direct:
    """Lo que cuenta el motor en una base: el proveedor, sus tablas por su nombre y los
    elementos de ``ELEMENTOS`` (número → nombre y unidad)."""

    provider: str
    tables: dict[str, _EngineTable]
    elements: dict[int, tuple[str | None, str | None]]

    def table(self, name: str) -> _EngineTable | None:
        for table in self.tables.values():
            if table.name.strip().upper() == name:
                return table
        return None


def _number(text: object) -> float | None:
    return None if text is None else float(str(text))


def _decoded(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("oem" if os.name == "nt" else "latin-1", errors="replace")


def _direct_read(copy: Path) -> _Direct:
    """La lectura directa de la copia ``copy`` con el motor (``count_mdb.ps1``)."""
    process = subprocess.run(
        [str(recmin.powershell(64)), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
         "Bypass", "-File", str(SCRIPT), "-Source", str(copy),
         "-Providers", ";".join(recmin.ACE_PROVIDERS)],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=COUNT_TIMEOUT_S,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    if process.returncode != 0:
        raise AssertionError(f"el motor no leyó la copia de la base (código "
                             f"{process.returncode}): {_decoded(process.stderr).strip()}")
    lines = [line for line in _decoded(process.stdout).splitlines() if line.strip()]
    data = json.loads(lines[-1])
    tables = {}
    for item in data["tables"]:
        elements = tuple(_EngineElement(e["column"], int(e["type"]), int(e["count"]),
                                        _number(e["sum"]), _number(e["abs_sum"]))
                         for e in item["elements"] or ())
        tables[item["name"]] = _EngineTable(item["name"], int(item["rows"]),
                                            tuple(c["name"] for c in item["columns"] or ()),
                                            elements)
    elements: dict[int, tuple[str | None, str | None]] = {}
    for item in data["elements"] or ():
        number = _number(item["number"])
        if number is not None and number.is_integer():
            elements[int(number)] = (item["name"], item["unit"])
    return _Direct(data["provider"], tables, elements)


# --- La importación y lo que dejó en el proyecto ---------------------------------------------


@dataclass
class _Imported:
    """Lo que dejó la importación en el proyecto: su informe por tabla de RecMin (leídos,
    importados y rechazados), sus rechazos por tabla y campo, los registros de lo importado
    por tabla de RecMin (sus ``external_id`` distintos, sin las muestras), los valores de lo
    importado por tabla de muestras y elemento, la entrada (``gb_input``) y su versión de
    esquema y sus avisos."""

    log: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    rejected: Counter[tuple[str, str]] = field(default_factory=Counter)
    records: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    values: dict[tuple[str, str], list[float | None]] = field(
        default_factory=lambda: defaultdict(list))
    record: Any = None
    schema_version: int | None = None
    warnings: int = 0
    seconds: float = 0.0


def _declaration(project: Any) -> Any:
    """Lo declarado al importar la base del banco (véase el módulo, paso 3)."""
    crs, vertical = gis_store.project_references(project)
    return model.SourceDeclaration(
        crs=crs, vertical=vertical, azimuth_ref=model.AzimuthRef.GRID, declination_deg=None,
        inclination_convention=model.InclinationConvention.NEGATIVE_DOWN, units={},
        value_rules=model.ValueRules(decimal_mark=DECIMAL, negative_is_below_dl=False))


def _imported(project: Any, importer: Any) -> _Imported:
    """Lo importado, el informe y la entrada de ``project`` tras la importación."""
    found = _Imported()
    found.schema_version = importer.report.get("schema_version")
    found.warnings = len(importer.report.get("warnings") or ())
    with project.read() as conn:
        names = [name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name GLOB 'dh_src_*' "
            "ORDER BY name")]
        for name in names:
            role = schema.layout_of(name).role
            if role == "assay":
                for external, element, value in conn.execute(
                        f'SELECT external_id, element, value FROM "{name}"'):
                    table = recmin_drillholes.external_table(external) or ""
                    found.values[(table.upper(), model.name_key(element))].append(value)
                continue
            for (external,) in conn.execute(f'SELECT external_id FROM "{name}"'):
                table = recmin_drillholes.external_table(external)
                if table is not None:
                    found.records[table.upper()].add(external)
        for table, kind, read, imported, rejected, item_field in conn.execute(
                f'SELECT table_role, kind, n_read, n_imported, n_rejected, field '
                f'FROM "{store.IMPORT_LOG}"'):
            if kind == "summary":
                found.log[str(table).upper()] = (int(read), int(imported), int(rejected))
            elif kind == "rejected":
                found.rejected[(str(table).upper(), str(item_field))] += 1
        (found.record,) = inputs_mod.list_inputs(conn)
    return found


def _new_project(folder: Path) -> Any:
    """Un proyecto temporal nuevo en ``folder`` (los ajustes sintéticos de las pruebas)."""
    (folder / "proyectos").mkdir(parents=True)
    return create.create_project(folder / "proyectos", make_settings(), make_session(),
                                 userdata_mod.UserData(folder / "u")).project


def _import(path: Path, folder: Path, number: int) -> _Imported:
    """La importación de la base ``path`` en un proyecto temporal nuevo en ``folder``."""
    with ExitStack() as stack:
        project = _new_project(folder)
        stack.callback(project.close)
        runner = recmin_import.new_runner(folder, project)
        stack.callback(runner.shutdown)
        importer = recmin_import.RecminImport(
            project, runner, path, _declaration(project), decimal=DECIMAL,
            accept_schema=True, name=f"banco_{number}", job_label="Banco de RecMin")
        started = time.perf_counter()
        importer.import_source()
        found = _imported(project, importer)
        found.seconds = time.perf_counter() - started
        return found


# --- El hash de contenido por core_content_hash ----------------------------------------------


class _QuietSink:
    """Los eventos del trabajo de hash, que no se miran."""

    def send(self, event: Any) -> None:
        return None


def _content_digest(record: Any, path: Path, folder: Path) -> Any:
    """El hash de contenido de la base ``path`` por el camino del trabajo
    ``core_content_hash`` con lo que guardó su importación (``record``, la entrada)."""
    request = checks.HashRequest(record.uid, record.name, record.reader, record.kind,
                                 record.declarations, record.settings, {"main": path},
                                 record.normalizer, path.stat().st_size)
    job = content_hash.new_job(request)
    job_dir = job_paths.job_dir(folder, job.job_uid).create()
    ctx = worker_api.WorkerContext(job, job_dir, _QuietSink(), cancel_event=threading.Event(),
                                   paths=content_hash.job_paths(request))
    summary = content_hash.run(ctx)
    return encoder.ContentDigest(summary["data_sha256"], summary["content_sha256"],
                                 summary["normalizer"], summary["reader"])


# --- Las bases del banco y su comparación ---------------------------------------------------


@dataclass
class _Base:
    """Una base de RecMin del banco: su ruta relativa (nunca se imprime), su formato, cuántas
    copias iguales hay, lo que cuenta el motor, lo que dejó su importación y su hash de
    contenido por ``core_content_hash``."""

    label: str
    rel: str
    format: str
    copies: int
    sha256: str
    direct: _Direct
    imported: _Imported | None = None
    digest: Any = None


def _access_files(folder: Path, digests: dict[str, str]) -> list[tuple[str, str, int]]:
    """Las bases de Access Jet 4 o ACE del banco, una por contenido: su ruta relativa, su
    formato y sus copias iguales, en un orden fijo."""
    seen: dict[str, list] = {}
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for name in sorted(files):
            path = Path(root, name)
            if path.suffix.lower() not in BASE_SUFFIXES:
                continue
            try:
                fmt, _version = ports.read_format(path)
            except ports.MdbError:
                continue
            if str(fmt) not in READ_FORMATS:
                continue
            rel = path.relative_to(folder).as_posix()
            digest = digests.get(rel)
            if digest is None:  # tras un enlace o un punto de reparación: fuera de la foto
                continue
            entry = seen.setdefault(digest, [rel, str(fmt), 0])
            entry[2] += 1
    return [tuple(entry) for entry in seen.values()]


def _counted_tables(base: _Base) -> list[Any]:
    """Las tablas de la base que lee el importador y cuenta su informe
    (``interop.recmin.schema.layout`` con las columnas que da el motor)."""
    columns = {table.name: list(table.columns) for table in base.direct.tables.values()}
    return [use for use in recmin_schema.layout(columns).tables
            if str(use.kind) not in NOT_COUNTED]


def _element_key(base: _Base, column: str) -> tuple[str | None, bool]:
    """El nombre (sin mayúsculas) del elemento de una columna ``ELEMENTO n`` y si es de texto
    («txt»), por la tabla ``ELEMENTOS`` que da el motor; sin elemento, ``None``."""
    number = recmin_schema.element_number(column)
    name, unit = base.direct.elements.get(number, (None, None))
    if name is None:
        return None, False
    text = recmin_drillholes.element_unit(unit) == recmin_drillholes.TEXT_UNIT
    return model.name_key(name), text


def _table_problems(base: _Base) -> list[str]:
    """Lo que no cuadra entre el motor y la importación, tabla a tabla."""
    problems: list[str] = []
    imported = base.imported
    for use in _counted_tables(base):
        table = base.direct.tables[use.name]
        key = use.name.strip().upper()
        logged = imported.log.get(key)
        if logged is None:
            problems.append(f"{use.name}: el informe de la importación no la cuenta")
            continue
        read, done, rejected = logged
        if read != table.rows:
            problems.append(f"{use.name}: el motor cuenta {_count(table.rows)} filas y la "
                            f"importación leyó {_count(read)}")
        if rejected:
            fields = ", ".join(f"{name} {_count(count)}" for (where, name), count
                               in sorted(imported.rejected.items()) if where == key)
            problems.append(f"{use.name}: {_count(rejected)} valores o registros rechazados "
                            f"(por campo: {fields or 'sin detalle'})")
        if str(use.kind) == SAMPLES:
            values = sum(element.count for element in table.elements)
            if done != values:
                problems.append(f"{use.name}: el motor cuenta {_count(values)} valores de sus "
                                f"elementos y la importación importó {_count(done)}")
            continue
        records = len(imported.records.get(key, ()))
        if str(use.kind) in NOT_RECORDED:
            if records != done:
                problems.append(f"{use.name}: la importación dice {_count(done)} y lo "
                                f"importado tiene {_count(records)}")
            continue
        if done != table.rows:
            problems.append(f"{use.name}: el motor cuenta {_count(table.rows)} filas y la "
                            f"importación importó {_count(done)}")
        if records != table.rows:
            problems.append(f"{use.name}: el motor cuenta {_count(table.rows)} filas y lo "
                            f"importado tiene {_count(records)} registros con su identificador "
                            f"de RecMin")
    return problems


@dataclass(frozen=True)
class _Sum:
    """Un elemento de una tabla de muestras: sus valores según el motor y en lo importado, y
    sus sumas (``None`` si no se suman: de texto o de una columna no numérica)."""

    table: str
    column: str
    element: str | None
    engine_count: int
    imported_count: int
    engine_sum: float | None
    imported_sum: float | None
    tolerance: float | None

    @property
    def difference(self) -> float | None:
        if self.engine_sum is None or self.imported_sum is None:
            return None
        return abs(self.imported_sum - self.engine_sum)


def _sums(base: _Base) -> list[_Sum]:
    """Cada elemento de cada tabla de muestras: lo que cuenta y suma el motor y lo que hay en
    lo importado."""
    found: list[_Sum] = []
    for use in _counted_tables(base):
        if str(use.kind) != SAMPLES:
            continue
        table = base.direct.tables[use.name]
        key = use.name.strip().upper()
        for element in table.elements:
            name, text = _element_key(base, element.column)
            values = base.imported.values.get((key, name), []) if name is not None else []
            summed = element.sum is not None and not text
            numbers = [value for value in values if value is not None]
            imported_sum = math.fsum(numbers) if summed and len(numbers) == len(values) else None
            tolerance = None
            if summed:
                tolerance = (element.abs_sum or 0.0) * (
                    SINGLE_ERROR + (element.count + 2) * DOUBLE_ERROR)
            found.append(_Sum(use.name, element.column, name, element.count, len(values),
                              element.sum if summed else None, imported_sum, tolerance))
    return found


def _sum_problems(base: _Base) -> list[str]:
    problems: list[str] = []
    for item in _sums(base):
        where = f"{item.table}, {item.column} ({item.element or 'sin elemento'})"
        if item.engine_count != item.imported_count:
            problems.append(f"{where}: el motor cuenta {_count(item.engine_count)} valores y lo "
                            f"importado tiene {_count(item.imported_count)}")
        if item.engine_sum is None:
            continue
        if item.imported_sum is None:
            problems.append(f"{where}: lo importado tiene valores sin número")
        elif item.difference > item.tolerance:
            problems.append(f"{where}: la suma de lo importado difiere de la del motor en "
                            f"{item.difference:.3g} (tolerancia {item.tolerance:.3g})")
    return problems


def _tables(kinds: dict[str, list[Any]], kind: str) -> str:
    count = len(kinds.get(kind, ()))
    return f"{count} tabla" if count == 1 else f"{count} tablas"


def _line(base: _Base) -> str:
    """La línea ``CE-005-05: …`` de una base."""
    imported = base.imported
    kinds: dict[str, list[Any]] = defaultdict(list)
    for use in _counted_tables(base):
        kinds[str(use.kind)].append(use)

    def rows(kind: str) -> int:
        return sum(base.direct.tables[use.name].rows for use in kinds.get(kind, ()))

    sums = _sums(base)
    by_element: Counter[str] = Counter()
    for item in sums:
        by_element[item.element or "?"] += item.imported_count
    worst = max((item.difference / max(abs(item.engine_sum), 1e-300) for item in sums
                 if item.difference is not None), default=0.0)
    schema_text = (f"esquema {imported.schema_version}"
                   if imported.schema_version is not None else "sin versión de esquema")
    copies = "" if base.copies == 1 else f", {base.copies} copias iguales"
    problems = len(_table_problems(base)) + len(_sum_problems(base))
    return (
        f"CE-005-05 (banco de RecMin, {base.label}: {base.format.upper()}{copies}, "
        f"{schema_text}, motor {base.direct.provider}): {len(_counted_tables(base))} tablas "
        f"leídas; {_count(rows('collars'))} sondeos, {_count(rows('surveys'))} estaciones, "
        f"{_count(rows('lithology'))} tramos de litología ({_tables(kinds, 'lithology')}), "
        f"{_count(rows('samples'))} muestras ({_tables(kinds, 'samples')}) "
        f"con {_count(sum(by_element.values()))} valores de {len(by_element)} elementos ("
        + ", ".join(f"{name} {_count(count)}" for name, count in sorted(by_element.items()))
        + f"); diferencias con el motor: {problems}; mayor diferencia relativa de una suma "
        + f"{worst:.1e}".replace(".", ",")
        + f"; hash de contenido por core_content_hash "
        f"{'igual' if base.digest == imported.record.digest else 'DISTINTO'} que el de su "
        f"importación; avisos de la lectura: {imported.warnings}; importada en "
        + f"{imported.seconds:.1f} s".replace(".", ",")
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_copies(bank: Any) -> list[str]:
    """Los ficheros de ``geoblender/``, ``tools/`` y ``tests/`` iguales (tamaño y sha256) a
    uno del banco, y las bases de Access que haya en ellos (rutas del repositorio)."""
    sizes: dict[int, set[str]] = defaultdict(set)
    for rel, (size, _mtime) in bank.entries.items():
        if not rel.endswith("/") and size > 0:
            sizes[size].add(bank.digests[rel])
    found: list[str] = []
    for top in REPOSITORY_FOLDERS:
        for root, dirs, files in os.walk(top):
            dirs.sort()
            for name in sorted(files):
                path = Path(root, name)
                rel = path.relative_to(ROOT).as_posix()
                if path.suffix.lower() in ACCESS_SUFFIXES:
                    found.append(f"{rel}: una base de Access en el repositorio")
                    continue
                digests = sizes.get(path.stat().st_size)
                if digests and _sha256(path) in digests:
                    found.append(f"{rel}: igual que un fichero del banco")
    return found


class RecminBankTest(unittest.TestCase):
    """CE-005-05 con la base de RecMin del banco (RF-005-03, RF-005-13)."""

    bases: list[_Base] = []
    before: Any = None
    after: Any = None
    copies: list[str] = []

    @classmethod
    def setUpClass(cls) -> None:
        text = os.environ.get(ENV, "").strip()
        if not text:
            raise unittest.SkipTest(
                f"OMITIDO: recmin: la variable {ENV} no está definida; defínala con la carpeta "
                "del banco (solo lectura) y ejecute tools/check.py --banco")
        folder = Path(text)
        if not folder.is_dir():
            raise unittest.SkipTest(f"OMITIDO: recmin: {ENV} no apunta a una carpeta legible")
        cls.before = source_state(folder)
        found = _access_files(folder, cls.before.digests)
        if not found:
            raise AssertionError(
                "no se encontró en el banco ninguna base de RecMin: ningún .mdb ni .accdb de "
                "Access en formato Jet 4 o ACE")
        if not recmin.ace_available():
            raise AssertionError(f"sin el motor de Access no se puede contrastar el banco: "
                                 f"{recmin.ACE_HINT}")
        temp = Path(tempfile.mkdtemp(prefix="gb-bdh-"))
        try:
            bases: list[_Base] = []
            for number, (rel, fmt, copies) in enumerate(found, start=1):
                copy = temp / f"d{number}" / f"base{Path(rel).suffix.lower()}"
                copy.parent.mkdir()
                shutil.copyfile(folder / rel, copy)
                direct = _direct_read(copy)
                remove_tree(copy.parent)
                if direct.table(COLLARS) is None:
                    continue  # una base de Access que no es de sondeos de RecMin
                bases.append(_Base("", rel, fmt, copies, cls.before.digests[rel], direct))
            if not bases:
                raise AssertionError(
                    "no se encontró en el banco ninguna base de RecMin: ninguna base de Access "
                    f"tiene la tabla {COLLARS}")
            with ExitStack() as registered:
                recmin_import.registrations(registered)
                for number, base in enumerate(bases, start=1):
                    base.label = f"base {number} de {len(bases)}"
                    base.imported = _import(folder / base.rel, temp / f"p{number}", number)
                    base.digest = _content_digest(base.imported.record, folder / base.rel,
                                                  temp / f"h{number}")
                    _report(_line(base))
        finally:
            remove_tree(temp)
        cls.bases = bases
        cls.after = source_state(folder)
        cls.copies = _repository_copies(cls.before)

    def test_tables_counted_like_the_engine(self) -> None:
        """CE-005-05, RF-005-13: cada tabla que lee el importador tiene en el informe de la
        importación las filas que cuenta el motor, sin ningún rechazo; lo importado tiene un
        registro con su identificador de RecMin por cada fila (las bocas, las desviaciones, la
        litología, las intersecciones, los cortes y los catálogos) y, de las tablas de
        muestras, tantos valores como cuenta el motor en sus elementos."""
        for base in self.bases:
            with self.subTest(base=base.label):
                problems = _table_problems(base)
                self.assertEqual(problems, [], "\n".join(problems))

    def test_elements_summed_like_the_engine(self) -> None:
        """CE-005-05, RF-005-13, RF-005-02: de cada elemento de cada tabla de muestras, lo
        importado tiene los valores que cuenta el motor y su suma es la del motor, con la
        diferencia de precisión simple de cada valor (su decimal más corto) como tolerancia;
        los de texto se cuentan."""
        for base in self.bases:
            with self.subTest(base=base.label):
                self.assertTrue(_sums(base) or not any(
                    str(use.kind) == SAMPLES for use in _counted_tables(base)))
                problems = _sum_problems(base)
                self.assertEqual(problems, [], "\n".join(problems))

    def test_content_hash_is_that_of_its_import(self) -> None:
        """RF-005-13, RF-005-03: el hash de contenido de la base por ``core_content_hash`` es
        el que guardó su importación, que leyó los bytes del banco (la huella de su fichero
        y la de su original guardado son el sha256 de la base del banco)."""
        for base in self.bases:
            with self.subTest(base=base.label):
                record = base.imported.record
                self.assertEqual(base.digest, record.digest)
                (main,) = record.files
                self.assertEqual(main.sha256, base.sha256)
                self.assertEqual(main.original_sha256, base.sha256)

    def test_bank_folder_untouched(self) -> None:
        """RF-005-03: la carpeta del banco queda igual: los mismos ficheros y carpetas, con
        los mismos tamaños, fechas y sha256, sin ningún ``.laccdb`` ni ``.ldb``."""
        changes = source_changes(self.before, self.after)
        self.assertEqual(changes, [], "\n".join(changes))

    def test_no_bank_data_in_the_repository(self) -> None:
        """RF-005-03, CE-005-05 (D-3): ningún fichero del banco está copiado en
        ``geoblender/``, ``tools/`` ni ``tests/`` (ninguno con su tamaño y su sha256), y no
        hay en ellos ninguna base de Access."""
        self.assertEqual(self.copies, [], "\n".join(self.copies))


if __name__ == "__main__":
    unittest.main()
