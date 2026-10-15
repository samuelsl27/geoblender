# SPDX-License-Identifier: GPL-3.0-or-later
"""Los trabajos de los sondeos (spec 005, T23; HU-005-1, HU-005-2; RF-005-03, RF-005-04,
RF-005-05 a RF-005-10, RF-005-13 a RF-005-16, RF-005-20; plan 005 §5.3.3, §5.6.5 a §5.6.7;
ADR-0010).

Lo pesado de la 005 va a los trabajos de la 004: ``drillholes/jobs.py`` declara sus siete tipos
(``WorkerInfo``) y las funciones de los cinco que pueden ir en el hilo; las dos lecturas de una
fuente (``dh_import_tabular``, ``dh_import_recmin``), siempre en proceso aparte, están en
``interop/dh_jobs.py``; cada tipo tiene su envoltorio ``workers/dh_*.py``. Aquí:

- cada ``main(ctx)`` con el ``WorkerContext`` de la 004 (en el hilo, como el ejecutor en hilo)
  deja sus resultados en ``out/`` con su huella y, en el resumen, el ``ContentDigest`` de la
  fuente (el de su lector de la T39) o el de cada tabla que será un dato del proyecto (el de
  ``schema.table_digest``, que es el que calcula el registro de la 008 al escribirla);
- lo leído y las tablas viajan en npz sin *pickle* (``drillholes.arrays``), bit a bit;
- cancelar a mitad (también con todo escrito) deja ``out/`` vacía; un fallo explicado es un
  ``JobFailed`` con su código; una base de RecMin de esquema desconocido termina con
  ``needs_confirmation`` y sin resultados (RF-005-15);
- la petición nunca lleva una ruta (la fuente llega por ``--path`` y se copia, verificada, a
  ``in/``; lo del proyecto, a ``in/``), ningún trabajo abre ``project.gpkg`` ni escribe fuera de
  su carpeta, y la carpeta de la fuente no cambia (RF-005-03);
- con el ``JobRunner`` de la 004, una lectura va en proceso aparte, da lo mismo que en el hilo
  y se cancela en ≤ 2 s; el ``powershell.exe`` hijo de una base de RecMin termina al cancelar.

Datos sintéticos de ``tests/data/dh`` (``csv_basico``, ``csv_errores``, ``recmin_v12.sql``),
pequeños: cada trabajo en el hilo tarda centésimas. Lo que va en proceso aparte se lanza al
empezar el módulo y lo recoge ``SubprocessTest``.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.data.dh import build_xlsx
from tests.support import dh_sets, recmin
from tests.support import jobs_fixtures as _support
from tests.support.core_fixtures import FakeClock, make_session, make_settings
from tests.support.package import import_geoblender
from tests.support.provenance_checks import source_changes, source_state
from tests.support.repo import EXTENSION_DIR, ROOT

dh_jobs = import_geoblender("drillholes.jobs")
io_jobs = import_geoblender("interop.dh_jobs")
arrays = import_geoblender("drillholes.arrays")
model = import_geoblender("drillholes.model")
schema = import_geoblender("drillholes.schema")
provenance = import_geoblender("drillholes.provenance")
build = import_geoblender("drillholes.build_base")
store = import_geoblender("drillholes.store")
validate = import_geoblender("drillholes.validate")
desurvey = import_geoblender("drillholes.desurvey")
surface = import_geoblender("drillholes.surface")
view_data = import_geoblender("drillholes.view_data")
tabular = import_geoblender("interop.drillholes_tabular")
interop_base = import_geoblender("interop.base")
dh_content = import_geoblender("interop.dh_content")
recmin_reader = import_geoblender("interop.recmin.drillholes")
ports = import_geoblender("interop.ports")
mdb_reader = import_geoblender("adapters.mdb_reader")
gis = import_geoblender("gis")
gis_jobs = import_geoblender("gis.jobs")
geotiff_reader = import_geoblender("gis.geotiff.reader")
georef = import_geoblender("core.georef")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
encoder = import_geoblender("core.content.encoder")
wkb = import_geoblender("core.gpkg.wkb")
dataset_model = import_geoblender("core.datasets.model")
dataset_registry = import_geoblender("core.datasets.registry")
create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
catalog = import_geoblender("jobs.catalog")
protocol = import_geoblender("jobs.protocol")
job_paths = import_geoblender("jobs.paths")
policy = import_geoblender("jobs.policy")
runner_mod = import_geoblender("jobs.runner")
worker_api = import_geoblender("jobs.worker_api")
job_messages = import_geoblender("jobs.messages")
records = import_geoblender("jobs.records")

CRS, VERTICAL = dh_sets.H25830, dh_sets.V5782
CRS_JSON, VERTICAL_JSON = {"epsg": 25830}, {"epsg": 5782}
PROJECT_UID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
OPERATION_UID = "0f3c2a5e-7b1d-4c9e-8a6f-2d4b6c8e0a13"
FILES: dict[str, str] = dict(dh_sets.basico_expected()["files"])  # papel → fichero
ROLES = ("collar", "survey", "lithology", "assay_wide", "lithology_catalog", "element_catalog")
CSV_SETTINGS = {"encoding": "utf-8", "separator": ";", "header_row": 0, "decimal": ",",
                "date_format": "%d/%m/%Y"}
XLSX_SETTINGS = {"sheet": "bocas", "header_row": 0, "decimal": ",", "date_format": "%d/%m/%Y"}
DEM = ROOT / "tests" / "data" / "gis" / "geotiff" / "f64_strip.tif"  # cubre csv_basico
V12 = recmin.RECMIN_DIR / "recmin_v12.sql"
THRESHOLDS = {"depth_tolerance_m": 0.01, "gap_tolerance_m": 0.01, "min_interval_m": 0.05,
              "dogleg_max_deg_30m": 3.0, "collar_dem_tolerance_m": 2.0}
TRACE_STEP_M = 2.0
CANCEL_BUDGET_S = 2.0  # RF-004-09: cancelar para en ≤ 2 s
WAIT_S = 60.0  # plazo de seguridad: un trabajo colgado no cuelga la prueba
EXPECTED_WORKERS = ("dh_import_tabular", "dh_import_recmin", "dh_import_apply",
                    "dh_build_base", "dh_validate", "dh_desurvey", "dh_view_arrays")
BIG_COPIES = 1500  # análisis en columnas de csv_basico repetidos: unos 2 MB, segundos de hash

_STATE: dict[str, Any] = {}


# --- Datos ---------------------------------------------------------------------------------------


def _declaration(**changes: Any) -> Any:
    """La declaración de ``csv_basico/esperado.json`` con ``changes``."""
    found = dh_sets.basico_expected()["declaration"]
    values: dict[str, Any] = dict(
        crs=CRS, vertical=VERTICAL, azimuth_ref=found["azimuth_ref"],
        declination_deg=found["declination_deg"],
        inclination_convention=found["inclination_convention"], units=found["units"],
        value_rules=model.ValueRules(decimal_mark=found["decimal_mark"]),
        all_vertical=found["all_vertical"], density_kind=found["density_kind"],
        date_format=found["date_format"])
    values.update(changes)
    return model.SourceDeclaration(**values)


def _recmin_declaration(**changes: Any) -> Any:
    values: dict[str, Any] = dict(
        crs=CRS, vertical=VERTICAL, azimuth_ref=model.AzimuthRef.GRID, declination_deg=None,
        inclination_convention=model.InclinationConvention.NEGATIVE_DOWN, units={},
        value_rules=model.ValueRules(decimal_mark="."))
    values.update(changes)
    return model.SourceDeclaration(**values)


def _mapping(role: str) -> dict[str, str]:
    table = dh_sets.basico_tables()[role]
    return tabular.suggest_mapping(role, table.columns)


def _read_role(role: str, declaration: Any = None) -> Any:
    """Lo que lee el importador de la tabla ``role`` de ``csv_basico``."""
    table = dh_sets.basico_tables()[role]
    return tabular.read_role(role, table, _mapping(role), declaration or _declaration())


def _uid(number: int) -> str:
    return f"{number:08x}-0000-4000-8000-{number:012x}"


def _entries() -> list[Any]:
    """Las seis entradas de ``csv_basico`` (una por fichero) como las lee el importador."""
    found = []
    for number, role in enumerate(ROLES, start=1):
        rows = _read_role(role)
        found.append(build.SourceEntry(_uid(number), _declaration(), collars=rows.collars,
                                       surveys=rows.surveys, lithology=rows.lithology,
                                       assays=rows.assays, catalogs=rows.catalogs,
                                       label=role))
    return found


def _bits(values: Any) -> Any:
    """Una columna comparable bit a bit (sin −0,0 y con un solo NaN; ``extra``, diccionario);
    lo que no es un array, tal cual."""
    if not isinstance(values, np.ndarray):
        return values
    if values.dtype.kind == "f":
        found = values.astype(np.float64) + 0.0
        found[np.isnan(found)] = np.nan
        return found.view(np.int64).tolist()
    return [dict(value) if isinstance(value, Mapping) else value
            for value in values.reshape(-1).tolist()] + [values.shape, str(values.dtype)]


def _columns(columns: Any) -> dict[str, Any]:
    return {item.name: _bits(getattr(columns, item.name))
            for item in dataclasses.fields(columns)}


def _same_tables(test: unittest.TestCase, got: Mapping[str, Any],
                 expected: Mapping[str, Any]) -> None:
    for name, columns in expected.items():
        with test.subTest(tabla=name):
            test.assertEqual(_columns(got[name]), _columns(columns))


def _stored(rows: Any) -> list[tuple[Any, ...]]:
    """Unas filas como se guardan: un NaN es ``NULL`` (``None``)."""
    return [tuple(None if isinstance(v, float) and math.isnan(v) else v for v in row)
            for row in rows]


def _issue_row(issue: Any) -> tuple[Any, ...]:
    """La fila de ``dh_validation_issue`` de una incidencia (plan §5.6.1): el sondeo por su
    ``fid`` (posición + 1), la fila por su ``fid``, el nivel y el alcance por su texto, el
    valor en texto (sí/no; un número por su decimal más corto, con punto) y el mensaje en
    español."""
    value = issue.value
    if isinstance(value, bool):
        value = "sí" if value else "no"
    elif isinstance(value, float):
        value = np.format_float_positional(value + 0.0, unique=True, trim="-")  # −0 = 0
    elif value is not None:
        value = str(value)
    return (None if issue.hole < 0 else issue.hole + 1, issue.hole_name, issue.code,
            str(issue.level), None if issue.scope is None else str(issue.scope), issue.table,
            None if issue.row_ref is None else issue.row_ref + 1, issue.log_set, issue.element,
            issue.catalog_code, issue.depth_from, issue.depth_to, issue.field, value,
            issue.message("es"))


def _big_assays(path: Path) -> None:
    """Los análisis en columnas de ``csv_basico`` repetidos :data:`BIG_COPIES` veces con otros
    sondeos: una tabla de unos 2 MB que tarda segundos en hashearse."""
    lines = (dh_sets.BASICO / FILES["assay_wide"]).read_text("utf-8").splitlines()
    header, body = lines[0], lines[1:]
    out = [header]
    for copy in range(BIG_COPIES):
        out += [f"G{copy:05d}-{line}" for line in body]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _fake_base(path: Path) -> Path:
    """Un fichero con la cabecera de una base de Jet 4 (sin datos)."""
    data = bytearray(4096)
    data[0:4] = b"\x00\x01\x00\x00"
    data[4:19] = b"Standard Jet DB"
    data[0x14] = 1
    path.write_bytes(bytes(data))
    return path


def _v12(version: int | None = None) -> dict[str, Any]:
    """Las tablas de ``recmin_v12.sql`` como las da el extractor (con otra versión de esquema
    en ``ACTUALIZACION.ULTIMA``, si se da)."""
    tables = dict(recmin.raw_tables(V12))
    if version is not None:
        name = next(key for key in tables if key.casefold() == "actualizacion")
        table = tables[name]
        column = table.position("ULTIMA")
        rows = [tuple(version if i == column else v for i, v in enumerate(row))
                for row in table.rows]
        tables[name] = ports.RawTable(table.name, table.columns, tuple(rows))
    return tables


class _FakeExtractor:
    """Un ``MdbExtractor`` sin motor: da las tablas que se le dan, anota qué copia abrió y deja
    un crudo en ``out_dir``; con ``block``, espera a que le pidan cancelar; con ``error``, lo
    lanza."""

    def __init__(self, tables: Mapping[str, Any], *, block: bool = False,
                 error: Exception | None = None) -> None:
        self.tables = tables
        self.block = block
        self.error = error
        self.opened: list[Path] = []
        self.cancelled_seen = threading.Event()

    def probe(self, path: Path) -> Any:  # pragma: no cover - no lo usa el trabajo
        return ports.MdbInfo(ports.MdbFormat.JET4, 1)

    def extract(self, path: Path, out_dir: Path, on_progress: Any, cancelled: Any) -> list:
        self.opened.append(Path(path))
        out_dir.mkdir(parents=True)
        (out_dir / "schema.json").write_text("{}", encoding="utf-8")
        on_progress(0.5, "Leyendo")
        if self.error is not None:
            raise self.error
        while self.block:
            if cancelled():
                self.cancelled_seen.set()
                raise ports.MdbCancelled()
            time.sleep(0.005)
        on_progress(1.0, "Leída")
        return list(self.tables.values())


def setUpModule() -> None:  # noqa: N802 (nombre de unittest)
    tmp = _support.jobs_tmp(prefix="gb23-")
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    # Mientras dura el módulo, la carpeta temporal de este proceso es una suya: las carpetas
    # privadas del lector de RecMin que mira tearDownModule son solo las de sus pruebas, y no
    # las de otro módulo que lee una base a la vez en otra parte de la comprobación (spec 005,
    # T44: con las bases compartidas, test_dh_content lee las suyas en ese momento).
    private = base / "temp"
    private.mkdir()
    temp = mock.patch.object(tempfile, "tempdir", str(private))
    temp.start()
    unittest.addModuleCleanup(temp.stop)
    sources = base / "fuentes"
    sources.mkdir()
    for name in FILES.values():
        shutil.copyfile(dh_sets.BASICO / name, sources / name)
    build_xlsx.basico_book().write(sources / "csv_basico.xlsx")
    _big_assays(sources / "analisis_grande.csv")
    _fake_base(sources / "base.mdb")
    inputs = base / "entradas"
    inputs.mkdir()
    entries = _entries()
    built = build.build_base(entries, None, CRS, VERTICAL, project_uid=PROJECT_UID)
    arrays.save_npz(inputs / "base.npz", arrays.set_arrays(built.dset))
    hashes = built.columns["dh_collar"]["survey_sha256"]
    np.save(inputs / "hashes.npy", np.array(list(hashes), dtype=np.bytes_), allow_pickle=False)
    shutil.copyfile(DEM, inputs / "dem.tif")
    for role in ("collar", "lithology", "assay_wide"):
        rows = _read_role(role)
        arrays.save_npz(inputs / f"leido_{role}.npz", arrays.tables_arrays(
            {"collars": rows.collars, "surveys": rows.surveys, "lithology": rows.lithology,
             "assays": rows.assays}, rows.catalogs))
    cases = {case["code"]: case for case in dh_sets.errores_expected()["cases"]}
    errors = {code: dh_sets.error_case(cases[code]) for code in ("DH-E06", "DH-E10", "DH-W15")}
    for code, case in errors.items():
        arrays.save_npz(inputs / f"error_{code}.npz", arrays.set_arrays(case.dset))
    _STATE.update(base=base, sources=sources, inputs=inputs, entries=entries, built=built,
                  hashes=list(hashes), errors=errors, before=source_state(sources),
                  temp_before=_private_folders())
    _launch_subprocesses()
    if os.name == "nt":  # la base de Jet 4 de recmin_v12.sql, mientras corren las pruebas
        thread = threading.Thread(target=_build_jet4, args=(base / "bases",), daemon=True)
        thread.start()
        _STATE["jet4"] = thread


def _build_jet4(folder: Path) -> None:
    try:
        folder.mkdir()
        built = recmin.shared_bases(folder, ("jet4",), sql=V12)
        (_STATE["jet4_base"],) = [item.path for item in built.bases.values()]
    except Exception as error:  # noqa: BLE001 - lo dice la prueba que la usa
        _STATE["jet4_error"] = error


def _private_folders() -> set[str]:
    """Las carpetas privadas del lector de RecMin en la carpeta temporal del proceso (la del
    módulo, :func:`setUpModule`): no debe quedar ninguna."""
    return {path.name for path in Path(tempfile.gettempdir()).glob(
        f"{dh_content.PRIVATE_PREFIX}*")}


def tearDownModule() -> None:  # noqa: N802 - comprobación final de las fuentes
    changes = source_changes(_STATE["before"], source_state(_STATE["sources"]))
    if changes:
        raise AssertionError(f"la carpeta de las fuentes cambió (RF-005-03): {changes}")
    left = _private_folders() - _STATE["temp_before"]
    if left:
        raise AssertionError(f"quedaron carpetas fuera de las de los trabajos: {left}")


def _launch_subprocesses() -> None:
    """Lanza en proceso aparte, con el ``JobRunner`` de la 004, dos ``dh_import_tabular``:
    las bocas de ``csv_basico`` (termina) y unos análisis grandes, que ``SubprocessTest``
    cancela a mitad."""
    base = _STATE["base"] / "proceso"
    base.mkdir()
    registry = mock.patch.dict(catalog._REGISTRY)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    for info in dh_jobs.WORKER_INFOS:
        catalog.register_worker(info)
    project = base / "proyecto"
    project.mkdir()
    runner = runner_mod.JobRunner(jobs_root=base / "jobs", package_dir=EXTENSION_DIR,
                                  blender_python=Path(sys.executable), max_subprocess=2,
                                  forbidden_roots=[project])
    unittest.addModuleCleanup(runner.shutdown)
    sources = _STATE["sources"]
    handles = {}
    for key, role, file in (("bocas", "collar", FILES["collar"]),
                            ("grande", "assay_wide", "analisis_grande.csv")):
        request = protocol.new_request(
            dh_jobs.IMPORT_TABULAR, label=f"Lectura de {file}", owner="dh",
            params=_tabular_params(role), operation_uid=OPERATION_UID,
            grace_s=dh_jobs.CANCEL_GRACE_S)
        handles[key] = runner.submit(runner.prepare(request),
                                     paths={"source_main": sources / file})
    watched: dict[str, Any] = {"stop": threading.Event()}
    watcher = threading.Thread(target=_watch, args=(runner, handles, watched), daemon=True)
    watcher.start()

    def stop() -> None:
        watched["stop"].set()
        watcher.join(WAIT_S)

    unittest.addModuleCleanup(stop)  # antes de cerrar el lanzador (las limpiezas, al revés)
    _STATE["subprocess"] = {"runner": runner, "handles": handles, "base": base,
                            "watcher": watcher, "watched": watched}


def _watch(runner: Any, handles: Mapping[str, Any], watched: dict[str, Any]) -> None:
    """Sigue los trabajos en proceso aparte mientras corren las pruebas en el hilo (en otro
    hilo, como el monitor de Blender con su temporizador): anota sus eventos y cancela los
    análisis grandes en cuanto calculan el hash de la fuente (su avance pasa de la copia)."""
    events: dict[str, list[Any]] = {}
    asked: dict[str, float] = {}
    deadline = time.monotonic() + WAIT_S
    try:
        while any(handle.result() is None for handle in handles.values()):
            if watched["stop"].is_set() or time.monotonic() > deadline:
                raise AssertionError("los trabajos en proceso aparte no terminan")
            for update in runner.poll():
                events.setdefault(update.job_uid, []).extend(update.events)
            big = events.get(handles["grande"].job_uid, [])
            if "grande" not in asked and any(e.type == "progress" and e.frac > 0.12
                                             for e in big):
                asked["grande"] = time.time()
                runner.cancel(handles["grande"].job_uid)
            time.sleep(0.02)
    except BaseException as error:  # noqa: BLE001 - lo dice SubprocessTest
        watched["error"] = error
    watched.update(events=events, asked=asked)


def _tabular_params(role: str, reader: str = provenance.DH_CSV, **changes: Any) -> dict:
    settings = XLSX_SETTINGS if reader == provenance.DH_XLSX else CSV_SETTINGS
    params = {"reader": reader, "name": f"Campaña 2026 · {role}", "role": role,
              "mapping": _mapping(role), "declaration": dh_jobs.declaration_json(_declaration()),
              "settings": settings, "crs": CRS_JSON, "vertical": VERTICAL_JSON,
              "project_holes": [], "catalogs": None}
    params.update(changes)
    return params


# --- El caso de un trabajo en el hilo ------------------------------------------------------------


class _JobCase(unittest.TestCase):
    """Un trabajo de la 005 en el hilo, con el ``WorkerContext`` de la 004 y su envoltorio
    (``workers/<tipo>.py``, ``main``)."""

    def setUp(self) -> None:
        self.root = _STATE["base"] / "hilo" / self.id().rpartition(".")[2]
        self.root.mkdir(parents=True)
        self.extractor = dh_content.use_mdb_extractor(None)
        self.addCleanup(dh_content.use_mdb_extractor, self.extractor)

    def prepare(self, worker: str, params: dict, *, inputs: dict | None = None,
                loose: dict | None = None) -> Any:
        """La carpeta del trabajo ``worker`` con su ``request.json`` y sus entradas en ``in/``:
        ``inputs`` (ficheros de ``entradas/``, copiados con ``JobDir.copy_input``) y
        ``loose`` (arrays sueltos, ``JobDir.write_array``, como ``launch_job(arrays=…)``)."""
        request = protocol.new_request(worker, label=f"Prueba de {worker}", owner="dh",
                                       params=params, operation_uid=OPERATION_UID,
                                       environment="blender", timeout_s=600.0,
                                       grace_s=dh_jobs.CANCEL_GRACE_S)
        folder = job_paths.job_dir(self.root / "jobs", request.job_uid).create()
        found = {name: folder.copy_input(_STATE["inputs"] / file, name)
                 for name, file in (inputs or {}).items()}
        found |= {name: folder.write_array(name, array) for name, array in (loose or {}).items()}
        protocol.write_request(folder, dataclasses.replace(request, inputs=found))
        return folder

    def context(self, folder: Any, *, paths: dict | None = None, sink: Any = None,
                cancel: threading.Event | None = None) -> Any:
        request = protocol.read_request(folder)
        return worker_api.WorkerContext(request, folder, sink or worker_api.QueueSink(),
                                        cancel_event=cancel, paths=paths)

    def run_job(self, worker: str, params: dict, *, inputs: dict | None = None,
                loose: dict | None = None, paths: dict | None = None) -> tuple[dict, Any, Any]:
        """Ejecuta ``main(ctx)`` del envoltorio y comprueba lo común: cada resultado
        declarado está en ``out/`` con su huella, no hay otro, el resumen es JSON y la
        petición no lleva ninguna ruta (ARQ-11)."""
        folder = self.prepare(worker, params, inputs=inputs, loose=loose)
        ctx = self.context(folder, paths=paths)
        summary = import_geoblender(f"workers.{worker}").main(ctx)
        json.dumps(summary, allow_nan=False)
        found = sorted(path.relative_to(folder.path).as_posix()
                       for path in folder.outputs_dir.rglob("*") if path.is_file())
        self.assertEqual(found, sorted(ref.path for ref in ctx.outputs))
        for ref in ctx.outputs:
            file = folder.path / ref.path
            self.assertEqual((ref.sha256, ref.size),
                             (_support.sha256_file(file), file.stat().st_size))
        text = (folder.path / job_paths.REQUEST_FILE).read_text("utf-8")
        shown = str(_STATE["base"])
        for form in (shown, shown.replace("\\", "/"), json.dumps(shown)[1:-1]):
            self.assertNotIn(form, text)
        return summary, ctx, folder

    @staticmethod
    def output(ctx: Any, folder: Any, role: str) -> Path:
        (ref,) = [ref for ref in ctx.outputs if ref.role == role]
        return folder.path / ref.path

    def table(self, ctx: Any, folder: Any, table: str) -> Any:
        return dh_jobs.read_table_output(self.output(ctx, folder, table), table)


def _base_params(**changes: Any) -> dict:
    params = {"crs": CRS_JSON, "vertical": VERTICAL_JSON, "count": 200}
    params.update(changes)
    return params


# --- Las lecturas de una fuente ------------------------------------------------------------------


class ImportTabularTest(_JobCase):
    def test_tables_read_in_their_declaration_with_the_source_hash(self) -> None:
        """RF-005-03, RF-005-05, RF-005-06, RF-005-09, RF-005-10, RF-005-11, RF-005-12,
        RF-008-09 (plan §5.6.5 y §5.6.7): ``dh_import_tabular`` copia la fuente a ``in/``
        (``--path``, nunca en la petición; la copia, con su huella), la lee con la
        correspondencia de columnas y la declaración de la petición y deja ``source.npz`` (lo
        que lee el importador, ``read_role``, en lo declarado, bit a bit y sin *pickle*) y
        ``report.json``; su resumen trae el ``ContentDigest`` de la fuente (el que da su lector
        de la T39 con las declaraciones de la entrada), la huella del fichero, los códigos
        nuevos frente a los catálogos del proyecto y los sondeos que ya están en la base. Un
        CSV de bocas, de litología y de análisis en columnas, y la hoja «bocas» del XLSX
        equivalente, que da lo mismo que el CSV (RF-005-06)."""
        sources = _STATE["sources"]
        project = model.Catalogs(lithology=(model.LithologyCode("PZ"),))
        cases = [(role, provenance.DH_CSV, sources / FILES[role])
                 for role in ("collar", "lithology", "assay_wide")]
        cases.append(("collar", provenance.DH_XLSX, sources / "csv_basico.xlsx"))
        read: dict[tuple[str, str], Any] = {}
        for role, reader_id, path in cases:
            with self.subTest(papel=role, lector=reader_id):
                params = _tabular_params(role, reader_id, project_holes=["s-01 ", "Z-9"],
                                         catalogs=arrays.catalogs_json(project))
                summary, ctx, folder = self.run_job(dh_jobs.IMPORT_TABULAR, params,
                                                    paths={"source_main": path})
                rows = _read_role(role)
                dto = arrays.load_npz(self.output(ctx, folder, dh_jobs.OUT_SOURCE.role))
                tables, catalogs = arrays.tables_of(dto)
                _same_tables(self, tables, {"collars": rows.collars, "surveys": rows.surveys,
                                            "lithology": rows.lithology,
                                            "assays": rows.assays})
                self.assertEqual(catalogs, rows.catalogs)
                read[(role, reader_id)] = tables
                copy = folder.inputs_dir / f"source_main{path.suffix}"
                self.assertEqual(sorted(p.name for p in folder.inputs_dir.iterdir()),
                                 [copy.name])
                self.assertEqual(_support.sha256_file(copy), _support.sha256_file(path))
                reader = dh_content.DH_CSV if reader_id == provenance.DH_CSV else \
                    dh_content.DH_XLSX
                declarations = provenance.source_declarations(reader_id, _declaration(),
                                                              role=role, mapping=_mapping(role))
                request = reader.request(provenance.input_kind(reader_id, role), declarations,
                                         {"main": path}, params["settings"])
                source = summary["source"]
                self.assertEqual(source["digest"], dh_jobs.digest_json(
                    readers.read_content(reader, request)))
                self.assertEqual(source["declarations"], declarations)
                stat = path.stat()
                self.assertEqual(source["files"]["main"],
                                 {"sha256": _support.sha256_file(path), "size": stat.st_size,
                                  "mtime_ns": stat.st_mtime_ns})
                container = model.DrillholeSet(
                    crs=CRS, vertical=VERTICAL, collars=rows.collars, surveys=rows.surveys,
                    lithology=rows.lithology, assays=rows.assays, catalogs=rows.catalogs)
                report = json.loads(self.output(ctx, folder, dh_jobs.OUT_REPORT.role)
                                    .read_text("utf-8"))
                self.assertEqual(report["counts"], rows.counts.as_dict())
                self.assertEqual(report["rejected"], [list(item) for item in rows.rejected])
                new = {kind: list(codes) for kind, codes in
                       interop_base.new_codes(container, project).items()}
                self.assertEqual((summary["new_codes"], report["new_codes"]), (new, new))
                register = interop_base.registrations(container, project)  # T25
                self.assertEqual((summary["register_codes"], report["register_codes"]),
                                 (register, register))
                self.assertEqual(summary["existing_holes"],
                                 ["S-01"] if role == "collar" else [])
        self.assertTrue(read[("lithology", provenance.DH_CSV)]["lithology"].code.size)
        _same_tables(self, read[("collar", provenance.DH_XLSX)],
                     read[("collar", provenance.DH_CSV)])

    def test_explained_failures_and_bad_requests(self) -> None:
        """RF-005-07, RF-004-12: unas bocas sin datum declarado no se leen
        (``dh.declaration_missing``, un ``JobFailed`` con su texto en español) y ``out/``
        queda vacía; una petición que no vale (lector o papel desconocidos, sin la ruta de la
        fuente) es ``request_invalid``; una fuente que cambia mientras se copia,
        ``source_changed``."""
        path = _STATE["sources"] / FILES["collar"]
        params = _tabular_params("collar", declaration=dh_jobs.declaration_json(
            _declaration(vertical=None)))
        folder = self.prepare(dh_jobs.IMPORT_TABULAR, params)
        with self.assertRaises(worker_api.JobFailed) as caught:
            import_geoblender("workers.dh_import_tabular").main(
                self.context(folder, paths={"source_main": path}))
        self.assertEqual(caught.exception.code, "dh.declaration_missing")
        self.assertEqual(list(folder.outputs_dir.iterdir()), [])
        for bad, paths in ((_tabular_params("collar", reader="io.nada@1"),
                            {"source_main": path}),
                           (dict(_tabular_params("collar"), role="bocas"), {"source_main": path}),
                           (_tabular_params("collar"), {})):
            with self.subTest(peticion=bad["reader"], papel=bad["role"], rutas=list(paths)):
                folder = self.prepare(dh_jobs.IMPORT_TABULAR, bad)
                with self.assertRaises(job_messages.JobError) as caught:
                    import_geoblender("workers.dh_import_tabular").main(
                        self.context(folder, paths=paths))
                self.assertEqual(caught.exception.code, "request_invalid")
                self.assertEqual(list(folder.outputs_dir.iterdir()), [])
        stamps = iter([(1, 1), (2, 2)])  # la fuente antes y después de copiarla
        folder = self.prepare(dh_jobs.IMPORT_TABULAR, _tabular_params("collar"))
        with (mock.patch.object(dh_jobs, "_stamp", side_effect=lambda p: next(stamps)),
              self.assertRaises(job_messages.JobError) as caught):
            import_geoblender("workers.dh_import_tabular").main(
                self.context(folder, paths={"source_main": path}))
        self.assertEqual(caught.exception.code, "source_changed")
        self.assertEqual(list(folder.outputs_dir.iterdir()), [])


class ImportRecminTest(_JobCase):
    def recmin_params(self, **changes: Any) -> dict:
        params = {"name": "Base de RecMin", "declaration": dh_jobs.declaration_json(
            _recmin_declaration()), "settings": {"decimal": "."}, "accept_schema": False,
            "crs": CRS_JSON, "vertical": VERTICAL_JSON, "project_holes": ["r-01"],
            "catalogs": None}
        params.update(changes)
        return params

    def run_recmin(self, extractor: Any, **changes: Any) -> tuple[dict, Any, Any]:
        dh_content.use_mdb_extractor(extractor)
        return self.run_job(dh_jobs.IMPORT_RECMIN, self.recmin_params(**changes),
                            paths={"source_main": _STATE["sources"] / "base.mdb"})

    def test_recmin_base_read_with_the_reader_hash(self) -> None:
        """RF-005-13, RF-005-03, RF-008-09 (plan §5.6.5 y §5.6.7; ADR-0018): ``dh_import_recmin``
        copia la base a ``in/`` y el extractor abre esa copia (su bloqueo queda junto a ella,
        nunca junto a la fuente), deja su crudo en ``out/mdb``, lee las tablas con
        ``read_drillholes`` (``source.npz``, bit a bit) y su informe, y da el ``ContentDigest``
        de ``io.recmin_mdb@1`` sin extraer la base otra vez: el mismo que da el lector sobre la
        fuente con el mismo extractor."""
        tables = _v12()
        fake = _FakeExtractor(tables)
        summary, ctx, folder = self.run_recmin(fake)
        self.assertEqual(len(fake.opened), 1)
        self.assertEqual(fake.opened[0].parent, folder.inputs_dir)
        self.assertEqual([ref.path for ref in ctx.outputs if ref.role == dh_jobs.OUT_RAW_ROLE],
                         ["out/mdb/schema.json"])
        decl = _recmin_declaration()
        dset, report = recmin_reader.read_drillholes(list(tables.values()), decl)
        dto, catalogs = arrays.tables_of(arrays.load_npz(
            self.output(ctx, folder, dh_jobs.OUT_SOURCE.role)))
        _same_tables(self, dto, {name: getattr(dset, name) for name in model.TABLES})
        self.assertEqual(catalogs, dset.catalogs)
        saved = json.loads(self.output(ctx, folder, dh_jobs.OUT_REPORT.role).read_text("utf-8"))
        self.assertEqual(saved["counts"], {table: counts.as_dict()
                                           for table, counts in report.per_table.items()})
        self.assertEqual((summary["schema_version"], summary["existing_holes"]), (12, ["R-01"]))
        self.assertEqual(summary["register_codes"], interop_base.registrations(dset))
        declarations = provenance.source_declarations(provenance.RECMIN_MDB, decl)
        request = dh_content.RECMIN_MDB.request(
            "drillholes", declarations, {"main": _STATE["sources"] / "base.mdb"},
            {"decimal": "."})
        self.assertEqual(summary["source"]["digest"],
                         dh_jobs.digest_json(readers.read_content(dh_content.RECMIN_MDB,
                                                                  request)))

    @unittest.skipUnless(os.name == "nt", "las bases de Access se crean y se leen en Windows")
    def test_with_the_access_engine(self) -> None:
        """RF-005-13, RF-005-03, RF-005-02 (ADR-0018): con el extractor de
        ``adapters.registry`` y el motor de Access del equipo, la base de Jet 4 de
        ``recmin_v12.sql`` da lo mismo que sus tablas sin motor (lo leído, bit a bit, con los
        Single por su decimal más corto, y el mismo hash de contenido); el crudo del motor
        queda en ``out/mdb`` y la carpeta de la base no cambia (ni bloqueo, ni nada nuevo)."""
        _STATE["jet4"].join(WAIT_S)
        if "jet4_error" in _STATE:
            raise _STATE["jet4_error"]
        path = _STATE["jet4_base"]
        before = source_state(path.parent)
        summary, ctx, folder = self.run_job(dh_jobs.IMPORT_RECMIN, self.recmin_params(),
                                            paths={"source_main": path})
        self.assertEqual(source_changes(before, source_state(path.parent)), [])
        raw = [ref.path for ref in ctx.outputs if ref.role == dh_jobs.OUT_RAW_ROLE]
        self.assertIn("out/mdb/schema.json", raw)
        expected, _ctx, _folder = self.run_recmin(_FakeExtractor(_v12()))
        self.assertEqual(summary["source"]["digest"], expected["source"]["digest"])
        dset, _report = recmin_reader.read_drillholes(list(_v12().values()),
                                                      _recmin_declaration())
        dto, catalogs = arrays.tables_of(arrays.load_npz(
            self.output(ctx, folder, dh_jobs.OUT_SOURCE.role)))
        _same_tables(self, dto, {name: getattr(dset, name) for name in model.TABLES})
        self.assertEqual(catalogs, dset.catalogs)

    def test_unknown_schema_needs_confirmation(self) -> None:
        """RF-005-15: con una versión de esquema que no es 11 ni 12, el trabajo termina sin
        resultados y con ``needs_confirmation`` (el código, la versión y el aviso); con la
        confirmación (``accept_schema``) lee la base y avisa."""
        summary, ctx, folder = self.run_recmin(_FakeExtractor(_v12(13)))
        found = summary["needs_confirmation"]
        self.assertEqual((found["code"], found["version"]), ("dh.recmin_schema_unknown", 13))
        self.assertIn("13", found["text"])
        self.assertEqual((ctx.outputs, list(folder.outputs_dir.iterdir())), ((), []))
        summary, ctx, folder = self.run_recmin(_FakeExtractor(_v12(13)), accept_schema=True)
        self.assertNotIn("needs_confirmation", summary)
        self.assertEqual(summary["schema_version"], 13)
        self.assertTrue(any("13" in text for text in summary["warnings"]))

    def test_engine_missing_and_cancellation(self) -> None:
        """RF-005-14, RF-005-04 (RF-004-09): sin motor, ``io.mdb_engine_missing`` con el formato
        y ``out/`` vacía; cancelar mientras el extractor lee para el trabajo en ≤ 2 s
        (``JobCancelled``), el extractor ve la cancelación y ``out/`` queda vacía."""
        missing = ports.engine_missing("base.mdb", ports.MdbFormat.ACE, ("ACE.16",))
        dh_content.use_mdb_extractor(_FakeExtractor({}, error=missing))
        folder = self.prepare(dh_jobs.IMPORT_RECMIN, self.recmin_params())
        with self.assertRaises(worker_api.JobFailed) as caught:
            import_geoblender("workers.dh_import_recmin").main(
                self.context(folder, paths={"source_main": _STATE["sources"] / "base.mdb"}))
        self.assertEqual(caught.exception.code, ports.MDB_ENGINE_MISSING)
        self.assertEqual(list(folder.outputs_dir.iterdir()), [])
        fake = _FakeExtractor(_v12(), block=True)
        dh_content.use_mdb_extractor(fake)
        cancel = threading.Event()
        folder = self.prepare(dh_jobs.IMPORT_RECMIN, self.recmin_params())
        ctx = self.context(folder, paths={"source_main": _STATE["sources"] / "base.mdb"},
                           cancel=cancel)
        threading.Timer(0.2, cancel.set).start()
        start = time.perf_counter()
        with self.assertRaises(worker_api.JobCancelled):
            import_geoblender("workers.dh_import_recmin").main(ctx)
        self.assertLessEqual(time.perf_counter() - start - 0.2, CANCEL_BUDGET_S)
        self.assertTrue(fake.cancelled_seen.is_set())
        self.assertEqual(list(folder.outputs_dir.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "el extractor real lanza un proceso hijo de Windows")
    def test_cancel_terminates_the_child_process(self) -> None:
        """RF-005-04, RNF-008-11 (plan §5.6.12): con el extractor real (su proceso hijo, aquí un
        Python que da un avance y espera, en lugar de ``powershell.exe``), cancelar el trabajo
        cuando el hijo ya lee una tabla lo para en ≤ 2 s y el hijo ya no vive."""
        child = [sys.executable, "-B", "-s", "-c",
                 "import json, sys, time\n"
                 "event = {'v': 1, 't': 'progress', 'ts': time.time(), 'frac': 0.25,"
                 " 'table': 't', 'index': 1, 'tables': 4, 'row': 3, 'rows': 10}\n"
                 "sys.stdout.write(json.dumps(event) + '\\n'); sys.stdout.flush()\n"
                 "time.sleep(30)\n"]
        processes: list[Any] = []
        real = mdb_reader.subprocess.Popen

        def spawn(*args: Any, **kwargs: Any) -> Any:
            process = real(*args, **kwargs)
            processes.append(process)
            return process

        dh_content.use_mdb_extractor(mdb_reader.OleDbProcessMdbExtractor((mdb_reader.JET4_32,)))
        cancel = threading.Event()
        asked: list[float] = []

        class Sink:
            def send(self, event: Any) -> None:
                if event.type == "progress" and "fila" in event.msg and not asked:
                    asked.append(time.perf_counter())
                    cancel.set()

        folder = self.prepare(dh_jobs.IMPORT_RECMIN, self.recmin_params())
        ctx = self.context(folder, paths={"source_main": _STATE["sources"] / "base.mdb"},
                           sink=Sink(), cancel=cancel)
        with (mock.patch.object(mdb_reader, "_command", side_effect=lambda bits: child),
              mock.patch.object(mdb_reader.subprocess, "Popen", side_effect=spawn),
              mock.patch.object(worker_api, "PROGRESS_INTERVAL_S", 0.0),
              self.assertRaises(worker_api.JobCancelled)):
            import_geoblender("workers.dh_import_recmin").main(ctx)
        self.assertTrue(asked)
        self.assertLessEqual(time.perf_counter() - asked[0], CANCEL_BUDGET_S)
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll())
        self.assertEqual(list(folder.outputs_dir.iterdir()), [])


# --- Aplicar, la base, la validación, las trazas y la vista --------------------------------------


class ApplyTest(_JobCase):
    def test_decisions_give_the_rows_of_the_imported_tables(self) -> None:
        """RF-005-10, RF-005-11, RF-005-12, RF-005-04 (plan §5.6.5): ``dh_import_apply`` con lo
        leído de las bocas (copiado a ``in/``) deja fuera los sondeos que conservan sus
        registros (``keep_holes``, sin mayúsculas: sus bocas y su orientación en boca), da de
        alta los códigos nuevos (la litología con un color determinista distinto de los del
        proyecto) y deja las filas de cada ``dh_src_<rol>`` (las de ``store.source_tables``,
        bit a bit) con el hash de ``schema.table_digest``."""
        taken = ["#4DD9A6", "#808080"]
        codes = {"lithology": [["lithology", "NUEVA"]], "element": [["Zn", "ppm"]],
                 "sector": ["Norte"]}
        params = {"name": "Campaña 2026", "crs": CRS_JSON, "keep_holes": ["s-12 "],
                  "replace_holes": ["S-01", "s-12"], "register_codes": codes,
                  "taken_colors": taken, "count": 50}
        summary, ctx, folder = self.run_job(dh_jobs.IMPORT_APPLY, params,
                                            inputs={"source": "leido_collar.npz"})
        rows = _read_role("collar")
        keep = np.array([model.name_key(n) != "s-12" for n in rows.collars.name.tolist()])
        stations = np.array([model.name_key(n) != "s-12" for n in rows.surveys.hole_name.tolist()])
        (color,) = dh_jobs.new_colors(1, taken)
        self.assertNotIn(color, taken)
        catalogs = model.Catalogs(
            lithology=(model.LithologyCode("NUEVA", color=color),),
            elements=(model.Element("Zn", "ppm"),), sectors=(model.CatalogEntry("Norte"),))
        expected = store.source_tables(collars=rows.collars.take(np.flatnonzero(keep)),
                                       surveys=rows.surveys.take(np.flatnonzero(stations)),
                                       catalogs=catalogs)
        self.assertEqual(sorted(summary["outputs"]), sorted(f"dh_src_{r}" for r in expected))
        for role, table_rows in expected.items():
            with self.subTest(papel=role):
                name = f"dh_src_{role}"
                self.assertEqual(list(self.table(ctx, folder, name)), _stored(table_rows))
                self.assertEqual(summary["outputs"][name]["digest"], dh_jobs.digest_json(
                    schema.table_digest(schema.source_layout(role), table_rows, CRS)))
        self.assertEqual(summary["removed"]["collars"], 1)
        self.assertEqual(summary["removed"]["surveys"], int((~stations).sum()))
        # RF-005-12 (T25): las filas de los sondeos que sustituyen a los del proyecto (S-12 se
        # conserva: no cuenta).
        s01 = rows.surveys.hole_name == "S-01"
        self.assertEqual((summary["replaced"]["collars"], summary["replaced"]["surveys"]),
                         (1, int(s01.sum())))
        self.assertEqual(summary["registered"]["lithology"], [["lithology", "NUEVA", color]])
        self.assertEqual(dh_jobs.new_colors(3, taken), dh_jobs.new_colors(3, taken))
        self.assertEqual(len(set(dh_jobs.new_colors(40, taken))), 40)


class BaseJobsTest(_JobCase):
    def test_build_base_gives_the_tables_of_build_base(self) -> None:
        """RF-005-08, RF-005-11, RF-005-22, RF-008-26 (plan §5.6.1 y §5.6.7): ``dh_build_base``
        con lo importado de las seis entradas de ``csv_basico`` en arrays sueltos de ``in/``
        (``launch_job(arrays=…)``) da las once tablas de ``build_base`` (sus filas, bit a bit, y
        su hash de ``schema.table_digest``), los sondeos cuya huella de la desviación cambia
        frente a ``previous`` y ninguna transformación (todo en el CRS del proyecto: no
        necesita pyproj)."""
        built = _STATE["built"]
        entries = []
        loose: dict[str, np.ndarray] = {}
        for number, entry in enumerate(_STATE["entries"], start=1):
            name = f"e{number}"
            loose |= dh_jobs.loose_arrays(name, arrays.entry_arrays(entry))
            entries.append({"input": name, "uid": entry.input_uid, "label": entry.label,
                            "declaration": dh_jobs.declaration_json(entry.declaration)})
        previous = dict(built.survey_hashes, **{"S-01": "0" * 64})
        params = _base_params(project_uid=PROJECT_UID, entries=entries, previous=previous)
        self.assertFalse(dh_jobs.needs_site(dh_jobs.BUILD_BASE, params))
        summary, ctx, folder = self.run_job(dh_jobs.BUILD_BASE, params, loose=loose)
        for table in schema.BASE_TABLES:
            with self.subTest(tabla=table):
                expected = built.rows(table)
                self.assertEqual(list(self.table(ctx, folder, table)), _stored(expected))
                self.assertEqual(summary["outputs"][table]["digest"], dh_jobs.digest_json(
                    schema.table_digest(schema.LAYOUTS[table], expected, CRS)))
        self.assertEqual((summary["changed"], summary["transforms"], summary["holes"]),
                         (["S-01"], [], len(built.dset.collars)))

    def test_validation_with_the_dem_and_the_error_cases(self) -> None:
        """RF-005-16, RF-005-17, RF-005-18 (plan §5.6.6): ``dh_validate`` sobre la base de
        ``in/`` da las filas de ``dh_validation_issue`` de ``validate`` (con su mensaje en
        español) y su hash: ``csv_basico`` con el MDT de ``in/dem.tif`` (bilineal) y la ventana,
        sin incidencias y con la diferencia de cada boca; tres casos de ``csv_errores`` sin MDT
        (la nota «sin MDT») y, en DH-W15, con la posición de las bocas en la capa."""
        built = _STATE["built"]
        window = dh_sets.work_window()
        params = _base_params(thresholds=THRESHOLDS, work_window=gis_jobs.window_json(window),
                              dem_crs=CRS_JSON, dem_vertical=VERTICAL_JSON)
        summary, ctx, folder = self.run_job(dh_jobs.VALIDATE, params,
                                            inputs={"base": "base.npz", "dem": "dem.tif"})
        source = geotiff_reader.read_geotiff(DEM)
        sampler = surface.raster_sampler(gis.Raster(source.grid, source.values, CRS, VERTICAL))
        report = validate.validate(built.dset, validate.ValidationParams(**THRESHOLDS),
                                   surface=sampler, work_window=window)
        self.assertEqual((summary["issues"], list(self.table(ctx, folder,
                                                             "dh_validation_issue"))),
                         (0, []))
        saved = json.loads(self.output(ctx, folder, dh_jobs.OUT_REPORT.role).read_text("utf-8"))
        self.assertEqual(saved["collar_dem_dz"], report.collar_dem_dz.tolist())
        self.assertEqual(saved["notes"], [])
        for code, case in _STATE["errors"].items():
            with self.subTest(caso=code):
                loose = {} if case.stored_geom_xyz is None else {
                    "stored_xyz": np.ascontiguousarray(case.stored_geom_xyz)}
                params = _base_params(thresholds=THRESHOLDS,
                                      work_window=gis_jobs.window_json(window))
                summary, ctx, folder = self.run_job(
                    dh_jobs.VALIDATE, params, inputs={"base": f"error_{code}.npz"}, loose=loose)
                report = validate.validate(case.dset, validate.ValidationParams(**THRESHOLDS),
                                           work_window=window,
                                           stored_geom_xyz=case.stored_geom_xyz)
                expected = [_issue_row(issue) for issue in report.issues]
                self.assertEqual(dh_jobs.issue_rows(report), expected)
                self.assertIn(code, [row[2] for row in expected])
                self.assertEqual(list(self.table(ctx, folder, "dh_validation_issue")),
                                 _stored(expected))
                self.assertEqual(summary["outputs"]["dh_validation_issue"]["digest"],
                                 dh_jobs.digest_json(schema.table_digest(
                                     schema.LAYOUTS["dh_validation_issue"], expected, CRS)))
                saved = json.loads(self.output(ctx, folder, dh_jobs.OUT_REPORT.role)
                                   .read_text("utf-8"))
                self.assertEqual([note["code"] for note in saved["notes"]],
                                 [note.code for note in report.notes])
                self.assertEqual(summary["excluded_holes"], int(report.excluded().holes.sum()))

    def test_desurvey_traces_without_the_excluded_holes(self) -> None:
        """RF-005-20, RF-005-17, RF-005-22 (plan §5.6.6): ``dh_desurvey`` sobre la base de
        ``in/`` da una fila de ``dh_trace`` por sondeo con traza (la polilínea cada 2 m por
        mínima curvatura, ``LINESTRING`` con Z en el CRS del proyecto, la longitud, el fondo y
        la huella de la desviación de su boca) y su hash; un sondeo con un error de alcance S
        (DH-E06) no tiene traza y se nombra."""
        built = _STATE["built"]
        params = _base_params(method="minimum_curvature", depth_tolerance_m=0.01,
                              trace_step_m=TRACE_STEP_M)
        summary, ctx, folder = self.run_job(
            dh_jobs.DESURVEY, params,
            inputs={"base": "base.npz", "survey_sha256": "hashes.npy"})
        traces = desurvey.desurvey(built.dset)
        offsets, xyz = desurvey.polylines(traces, None, TRACE_STEP_M)
        expected = []
        for hole in np.flatnonzero(traces.computed).tolist():
            last = traces.hole_start[hole + 1] - 1
            end = traces.xyz[last]
            expected.append((wkb.encode_geometry("LINESTRING", xyz[offsets[hole]:offsets[hole + 1]],
                                                 25830, True),
                             hole + 1, "minimum_curvature", float(traces.md[last]),
                             float(end[0]), float(end[1]), float(end[2]),
                             _STATE["hashes"][hole]))
        self.assertEqual(list(self.table(ctx, folder, "dh_trace")), expected)
        self.assertEqual(summary["outputs"]["dh_trace"]["digest"], dh_jobs.digest_json(
            schema.table_digest(schema.LAYOUTS["dh_trace"], expected, CRS)))
        self.assertEqual((summary["traces"], summary["excluded"]), (len(expected), []))
        case = _STATE["errors"]["DH-E06"]
        hashes = np.array(["0" * 64] * len(case.dset.collars), dtype=np.bytes_)
        summary, ctx, folder = self.run_job(dh_jobs.DESURVEY, params,
                                            inputs={"base": "error_DH-E06.npz"},
                                            loose={"survey_sha256": hashes})
        excluded = validate.hole_exclusions(case.dset, depth_tolerance_m=0.01)
        names = case.dset.collars.name.tolist()
        self.assertEqual(summary["excluded"], [names[i] for i in np.flatnonzero(excluded)])
        self.assertTrue(summary["excluded"])
        holes = {row[1] - 1 for row in self.table(ctx, folder, "dh_trace")}
        self.assertEqual(holes, set(np.flatnonzero(~excluded).tolist()))

    def test_view_arrays(self) -> None:
        """RF-005-23, RF-005-24, RF-005-25 (plan §5.6.8): ``dh_view_arrays`` sobre la base de
        ``in/`` da en ``view.npz`` las curvas de la litología (con su leyenda), las barras del
        oro con la leyenda por defecto y las etiquetas con la profundidad en el fondo: las de
        ``drillholes.view_data`` con las trazas por mínima curvatura, bit a bit."""
        built = _STATE["built"]
        params = _base_params(method="minimum_curvature", depth_tolerance_m=0.01,
                              max_step_m=TRACE_STEP_M, log_set="lithology", element="Au",
                              unit="g/t", offset_m=1.0, width_m=0.5, labels_at_end=True)
        summary, ctx, folder = self.run_job(dh_jobs.VIEW_ARRAYS, params,
                                            inputs={"base": "base.npz"})
        view = dh_jobs.read_view(self.output(ctx, folder, dh_jobs.OUT_VIEW.role))
        dset = built.dset
        traces = desurvey.desurvey(dset)
        excluded = validate.Exclusions(np.zeros(len(dset.collars), dtype=bool))
        curves = view_data.lithology_curves(dset, traces, "lithology", TRACE_STEP_M,
                                            excluded=excluded)
        legend = view_data.default_grade_legend(
            view_data.grade_values(dset, "Au", "g/t", excluded=excluded), "g/t")
        bars = view_data.grade_bars(dset, traces, "Au", legend, 1.0, 0.5,
                                    max_step_m=TRACE_STEP_M, excluded=excluded)
        self.assertEqual(_columns(view.curves), _columns(curves))
        self.assertEqual(_columns(view.bars), _columns(bars))
        self.assertEqual(view.lithology_legend, view_data.lithology_legend(dset, "lithology"))
        self.assertEqual(view.grade_legend, legend)
        self.assertEqual(view.labels, tuple(view_data.labels(dset, traces, True)))
        self.assertEqual((summary["curves"], summary["labels"]),
                         (len(curves.curve_sizes), 2 * len(dset.collars)))


class RegistryTest(_JobCase):
    def test_job_hashes_are_the_registry_hashes(self) -> None:
        """RF-008-17, RF-008-26 (plan §5.6.5 y §5.6.7; «Hecho cuando» de T23): el hash de cada
        tabla que da un trabajo es el que calcula el registro de la 008 al leerla escrita en un
        proyecto de esquema 2 con las filas del trabajo (``drillholes.arrays.TableRows``): lo
        importado de unas bocas, las once tablas de la base, las incidencias de un caso de
        ``csv_errores`` y las trazas."""
        found: dict[str, tuple[Any, str, Any, str]] = {}
        params = {"name": "Prueba", "crs": CRS_JSON, "count": 50}
        summary, ctx, folder = self.run_job(dh_jobs.IMPORT_APPLY, params,
                                            inputs={"source": "leido_collar.npz"})
        for name, item in summary["outputs"].items():
            role = name.removeprefix("dh_src_")
            found[name] = (schema.source_layout(role),
                           schema.source_table(role, "Prueba", _uid(7)),
                           self.table(ctx, folder, name), item["digest"]["content_sha256"])
        entries, loose = [], {}
        for number, entry in enumerate(_STATE["entries"][:2], start=1):
            entries.append({"input": f"e{number}", "uid": entry.input_uid,
                            "label": entry.label,
                            "declaration": dh_jobs.declaration_json(entry.declaration)})
            loose |= dh_jobs.loose_arrays(f"e{number}", arrays.entry_arrays(entry))
        summary, ctx, folder = self.run_job(
            dh_jobs.BUILD_BASE, _base_params(project_uid=PROJECT_UID, entries=entries),
            loose=loose)
        for name in schema.BASE_TABLES:
            found[name] = (schema.LAYOUTS[name], name, self.table(ctx, folder, name),
                           summary["outputs"][name]["digest"]["content_sha256"])
        window = gis_jobs.window_json(dh_sets.work_window())
        summary, ctx, folder = self.run_job(
            dh_jobs.VALIDATE, _base_params(thresholds=THRESHOLDS, work_window=window),
            inputs={"base": "error_DH-E10.npz"})
        found["dh_validation_issue"] = (
            schema.LAYOUTS["dh_validation_issue"], "dh_validation_issue",
            self.table(ctx, folder, "dh_validation_issue"),
            summary["outputs"]["dh_validation_issue"]["digest"]["content_sha256"])
        summary, ctx, folder = self.run_job(
            dh_jobs.DESURVEY, _base_params(depth_tolerance_m=0.01, trace_step_m=TRACE_STEP_M),
            inputs={"base": "base.npz", "survey_sha256": "hashes.npy"})
        found["dh_trace"] = (schema.LAYOUTS["dh_trace"], "dh_trace",
                             self.table(ctx, folder, "dh_trace"),
                             summary["outputs"]["dh_trace"]["digest"]["content_sha256"])
        self.assertTrue(len(found["dh_validation_issue"][2]))
        (self.root / "proyectos").mkdir()
        project = create.create_project(self.root / "proyectos", make_settings(),
                                        make_session(), userdata_mod.UserData(self.root / "u"),
                                        clock=FakeClock()).project
        self.addCleanup(project.close)
        with project.write_transaction() as conn:
            for name, (layout, table, rows, digest) in found.items():
                with self.subTest(tabla=name):
                    schema.create_table(conn, layout, table,
                                        25830 if layout.geometry_type else None)
                    schema.insert_rows(conn, layout, table, list(rows))
                    spec = dataset_model.DatasetSpec(
                        name, "dh", layout.kind, dataset_model.Store.GPKG, table,
                        reader=builtin.GPKG_LAYER.id, role="data")
                    computed = dataset_registry._computed(conn, project, spec,
                                                          builtin.GPKG_LAYER.id,
                                                          encoder.NORMALIZER)
                    self.assertEqual(computed.content_sha256, digest)


# --- Lo común: cancelar, el proyecto, los tipos ------------------------------------------------


class CancelTest(_JobCase):
    """Cancelar a mitad deja ``out/`` sin resultados (RF-005-04, RF-004-09)."""

    def cases(self) -> dict:
        sources = _STATE["sources"]
        entry = {"input": "e1", "uid": _uid(1), "label": "collar",
                 "declaration": dh_jobs.declaration_json(_declaration())}
        return {
            dh_jobs.IMPORT_TABULAR: (_tabular_params("collar"), {},
                                     {"source_main": sources / FILES["collar"]}),
            dh_jobs.IMPORT_RECMIN: (
                {"name": "RecMin", "declaration": dh_jobs.declaration_json(
                    _recmin_declaration()), "settings": {}, "crs": CRS_JSON,
                 "vertical": VERTICAL_JSON}, {}, {"source_main": sources / "base.mdb"}),
            dh_jobs.IMPORT_APPLY: ({"crs": CRS_JSON}, {"source": "leido_collar.npz"}, {}),
            dh_jobs.BUILD_BASE: (_base_params(project_uid=PROJECT_UID, entries=[entry]),
                                 {"e1": "leido_collar.npz"}, {}),
            dh_jobs.VALIDATE: (_base_params(thresholds=THRESHOLDS),
                               {"base": "base.npz", "dem": "dem.tif"}, {}),
            dh_jobs.DESURVEY: (_base_params(depth_tolerance_m=0.01, trace_step_m=2.0),
                               {"base": "base.npz", "survey_sha256": "hashes.npy"}, {}),
            dh_jobs.VIEW_ARRAYS: (_base_params(depth_tolerance_m=0.01, max_step_m=2.0,
                                               log_set="lithology"), {"base": "base.npz"}, {}),
        }

    def test_cancel_midway_leaves_out_without_results(self) -> None:
        """RF-005-04 (RF-004-09; spec 005 §8 «Corte de red o cancelación a mitad de importar»):
        en cada trabajo, cancelar a mitad, o con todo escrito justo antes de terminar, lo para
        (``JobCancelled``) y deja ``out/`` vacía: ningún resultado a medias ni entero."""
        cases = self.cases()
        self.assertEqual(sorted(cases), sorted(EXPECTED_WORKERS))
        for worker, (params, inputs, paths) in cases.items():
            for threshold in (0.5, 1.0):
                with self.subTest(trabajo=worker, cancelar_en=threshold):
                    dh_content.use_mdb_extractor(_FakeExtractor(_v12()))
                    cancel = threading.Event()
                    seen: list[float] = []

                    class Sink:
                        def send(self, event: Any, cancel: Any = cancel, seen: Any = seen,
                                 threshold: float = threshold) -> None:
                            if event.type == "progress":
                                seen.append(event.frac)
                                if event.frac >= threshold:
                                    cancel.set()

                    folder = self.prepare(worker, params, inputs=inputs)
                    ctx = self.context(folder, paths=paths, sink=Sink(), cancel=cancel)
                    with (mock.patch.object(worker_api, "PROGRESS_INTERVAL_S", 0.0),
                          self.assertRaises(worker_api.JobCancelled)):
                        import_geoblender(f"workers.{worker}").main(ctx)
                    self.assertTrue(cancel.is_set())
                    self.assertEqual(list(folder.outputs_dir.iterdir()), [])
                    if threshold == 1.0:
                        self.assertEqual(seen[-1], 1.0)


class ProjectUntouchedTest(_JobCase):
    def test_no_job_opens_a_database_file(self) -> None:
        """RF-004-02, RF-004-14, ARQ-11 (plan §5.3.3: «Ningún trabajo recibe la ruta del
        proyecto ni abre ``project.gpkg``»): los siete trabajos en el hilo solo abren bases de
        SQLite en memoria (las del hash de una tabla) y no escriben nada fuera de su carpeta:
        la de las entradas y la de las fuentes no cambian."""
        opened: list[Any] = []
        real = sqlite3.connect

        def connect(database: Any, *args: Any, **kwargs: Any) -> Any:
            opened.append(database)
            return real(database, *args, **kwargs)

        before = source_state(_STATE["inputs"])
        with mock.patch.object(sqlite3, "connect", side_effect=connect):
            for worker, (params, inputs, paths) in CancelTest.cases(self).items():
                with self.subTest(trabajo=worker):
                    dh_content.use_mdb_extractor(_FakeExtractor(_v12()))
                    self.run_job(worker, params, inputs=inputs, paths=paths)
        self.assertTrue(opened)
        self.assertEqual(set(opened), {":memory:"})
        self.assertEqual(source_changes(before, source_state(_STATE["inputs"])), [])


class WorkerInfoTest(unittest.TestCase):
    def test_worker_infos_and_their_wrappers(self) -> None:
        """RNF-005-06 (plan §5.3.3 y §5.6.7; plan 004 §5.3.1): los siete tipos de trabajo de la
        005, en el entorno de Blender: las dos lecturas de una fuente, siempre en proceso
        aparte (sin ``run``: su función, en ``interop.dh_jobs``); los demás, automáticos, con
        su función ``run`` y su estimación por ``count``; todos con su nombre visible traducido
        y su envoltorio ``workers/<tipo>.py`` con ``main``. ``dh_build_base`` necesita las
        ruedas (pyproj) solo si transforma o calcula la convergencia (:func:`needs_site`)."""
        infos = dh_jobs.WORKER_INFOS
        self.assertEqual(tuple(info.name for info in infos), EXPECTED_WORKERS)
        self.assertEqual(dh_jobs.WORKER_NAMES, EXPECTED_WORKERS)
        texts = import_geoblender("core.i18n").load_messages()
        imports = (dh_jobs.IMPORT_TABULAR, dh_jobs.IMPORT_RECMIN)
        for info in infos:
            with self.subTest(trabajo=info.name):
                self.assertIsInstance(info, catalog.WorkerInfo)
                self.assertEqual(info.environment, "blender")
                self.assertTrue(texts.get(info.label_msgid))
                self.assertTrue((EXTENSION_DIR / "workers" / f"{info.name}.py").is_file())
                self.assertTrue(callable(import_geoblender(f"workers.{info.name}").main))
                job = protocol.new_request(info.name, label="x", owner="dh",
                                           params={"count": 10})
                if info.name in imports:
                    self.assertEqual((info.policy, info.run), ("subprocess", None))
                    self.assertEqual(policy.choose_executor(info, job), "subprocess")
                else:
                    self.assertEqual(info.policy, "auto")
                    self.assertTrue(callable(info.run))
                    self.assertIsNone(info.estimate_s({}))
                    self.assertLess(info.estimate_s({"count": 10}),
                                    policy.INPROCESS_MAX_ESTIMATED_S)
                    self.assertEqual(policy.choose_executor(info, job), "inprocess")
        base = {"crs": CRS_JSON, "vertical": VERTICAL_JSON}
        same = dh_jobs.declaration_json(_declaration())
        for label, declaration, expected in (
                ("mismo CRS", same, False),
                ("ED50", dict(same, crs={"epsg": 23030}), True),
                ("elipsoidal", dict(same, vertical={"ellipsoidal": 4937}), True),
                ("magnético", dict(same, azimuth_ref="magnetic", declination_deg=0.25), True),
                ("sin CRS", dict(same, crs=None, vertical=None), False)):
            with self.subTest(entrada=label):
                params = {**base, "entries": [{"input": "e1", "uid": _uid(1),
                                               "declaration": declaration}]}
                self.assertEqual(dh_jobs.needs_site(dh_jobs.BUILD_BASE, params), expected)
        self.assertFalse(dh_jobs.needs_site(dh_jobs.VALIDATE, base))

    def test_request_values_round_trip(self) -> None:
        """RF-005-07, RF-005-02 (plan §5.6.7): la declaración de una fuente va en la petición en
        JSON y vuelve igual (CRS, datum, referencia del azimut, declinación, convenio, unidades,
        centinelas, decimal y formato de fecha); los catálogos del proyecto, también; lo que no
        es una de ellas, ``ValueError``."""
        declaration = _declaration(azimuth_ref="magnetic", declination_deg=-1.25,
                                   value_rules=model.ValueRules(",", frozenset({"-99", "ND"}),
                                                                True),
                                   date_format=None)
        shown = json.loads(json.dumps(dh_jobs.declaration_json(declaration)))
        self.assertEqual(dh_jobs.declaration_of(shown), declaration)
        catalogs = _read_role("lithology_catalog").catalogs
        catalogs = dataclasses.replace(catalogs, elements=_read_role("element_catalog")
                                       .catalogs.elements)
        back = json.loads(json.dumps(arrays.catalogs_json(catalogs)))
        self.assertEqual(arrays.catalogs_of(back), catalogs)
        for bad in ({"crs": None}, dict(shown, crs={"epsg": 4326}), 25830):
            with self.subTest(declaracion=bad), self.assertRaises((ValueError, TypeError)):
                dh_jobs.declaration_of(bad)

    def test_arrays_without_pickle(self) -> None:
        """RF-005-02, ARQ-16 (plan §5.3.3: «DTO sin pickle»): un ``DrillholeSet`` en arrays
        (``drillholes.arrays``) se guarda en un npz que se lee con ``allow_pickle=False`` y
        vuelve bit a bit, con textos con tildes y «Ñ», nulos, fechas, ``extra`` y catálogos;
        las filas de una tabla (``TableRows``) vuelven iguales por trozos, con ``NULL`` donde
        había NaN o ``None``, y la geometría con sus mismos bytes."""
        dset = _STATE["built"].dset
        collars = dset.collars
        name = collars.name.copy()
        name[0] = "Ñandú-1"
        comments = collars.comments.copy()
        comments[1] = "Pizarra «árida»"
        extra = collars.extra.copy()
        extra[2] = {"LADO": "N", "n": 2.5}
        changed = dataclasses.replace(dset, collars=collars.take(
            np.arange(len(collars)), name=name, comments=comments, extra=extra))
        path = self.root_path("set.npz")
        arrays.save_npz(path, arrays.set_arrays(changed))
        with np.load(path, allow_pickle=False) as data:
            self.assertFalse(any(data[key].dtype.hasobject for key in data.files))
        back = arrays.set_of(arrays.load_npz(path), crs=CRS, vertical=VERTICAL)
        _same_tables(self, {table: getattr(back, table) for table in model.TABLES},
                     {table: getattr(changed, table) for table in model.TABLES})
        self.assertEqual(back.catalogs, dset.catalogs)
        rows = _STATE["built"].rows("dh_collar")
        found = arrays.TableRows(schema.LAYOUTS["dh_collar"],
                                 arrays.rows_arrays(schema.LAYOUTS["dh_collar"], rows))
        self.assertEqual(len(found), len(rows))
        self.assertEqual(found[1:3] + [found[0], found[-1]],
                         _stored(rows[1:3] + [rows[0], rows[-1]]))
        with self.assertRaises(ValueError):
            arrays.save_npz(path, {"x": np.array([object()])})

    def root_path(self, name: str) -> Path:
        folder = _STATE["base"] / "arrays"
        folder.mkdir(exist_ok=True)
        return folder / name


class SubprocessTest(unittest.TestCase):
    """Las dos lecturas en proceso aparte, lanzadas al empezar el módulo
    (:func:`_launch_subprocesses`) y seguidas desde otro hilo (:func:`_watch`): las bocas
    terminan; los análisis grandes se cancelan a mitad."""

    @classmethod
    def setUpClass(cls) -> None:
        launched = _STATE["subprocess"]
        launched["watcher"].join(WAIT_S)
        watched = launched["watched"]
        if "error" in watched:
            raise watched["error"]
        cls.handles, cls.events, cls.asked = (launched["handles"], watched["events"],
                                              watched["asked"])

    def test_import_runs_in_a_subprocess(self) -> None:
        """RF-005-05, RF-004-03, ARQ-11 (plan §5.6.7): ``dh_import_tabular`` va en proceso
        aparte (su tipo no tiene ``run``) y da allí lo mismo que en el hilo (el hash de la
        fuente y lo leído); la petición no lleva ninguna ruta ni proyecto."""
        handle = self.handles["bocas"]
        result = handle.result()
        self.assertEqual(result.state, "succeeded", handle.message)
        record = records.read_record(handle.job_dir)
        self.assertEqual(record.executor, runner_mod.EXECUTOR_SUBPROCESS)
        text = (handle.job_dir.path / job_paths.REQUEST_FILE).read_text("utf-8")
        shown = str(_STATE["base"])
        for form in (shown, shown.replace("\\", "/"), json.dumps(shown)[1:-1]):
            self.assertNotIn(form, text)
        self.assertIsNone(json.loads(text)["project_uid"])
        path = _STATE["sources"] / FILES["collar"]
        declarations = provenance.source_declarations(provenance.DH_CSV, _declaration(),
                                                      role="collar", mapping=_mapping("collar"))
        request = dh_content.DH_CSV.request("drillholes", declarations, {"main": path},
                                            CSV_SETTINGS)
        self.assertEqual(result.summary["source"]["digest"], dh_jobs.digest_json(
            readers.read_content(dh_content.DH_CSV, request)))
        (ref,) = [ref for ref in result.outputs if ref.role == dh_jobs.OUT_SOURCE.role]
        tables, _ = arrays.tables_of(arrays.load_npz(handle.job_dir.path / ref.path))
        rows = _read_role("collar")
        _same_tables(self, tables, {"collars": rows.collars, "surveys": rows.surveys})

    def test_import_cancels_within_two_seconds(self) -> None:
        """RF-005-04 (RF-004-09): cancelar una lectura grande en curso (ya calculando el hash
        de la fuente) la para en ≤ 2 s, sin resultado y con ``out/`` vacía."""
        handle = self.handles["grande"]
        self.assertEqual(handle.state, "cancelled", handle.message)
        events = self.events[handle.job_uid]
        self.assertNotIn("result", [event.type for event in events])
        cancelled = [event for event in events if event.type == "cancelled"]
        took = (cancelled[0].ts if cancelled else time.time()) - self.asked["grande"]
        self.assertLessEqual(took, CANCEL_BUDGET_S)
        self.assertEqual(list(handle.job_dir.outputs_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
