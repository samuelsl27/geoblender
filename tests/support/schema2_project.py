# SPDX-License-Identifier: GPL-3.0-or-later
"""Un proyecto del esquema 2 de prueba, hecho con el código de partida de la spec 009 (T03;
RF-009-02, RF-009-23; plan 009 §7.1).

``tests/data/core/projects/esquema2.zip`` (:data:`ZIP_PATH`) es un proyecto sintético del
**esquema 2** (el de la 008) que escribió este generador con el código de ``main`` antes de
cualquier cambio de la 009 (la rama en ``b1ce246``): la ida de la migración ``m0003`` (T04) y
las comprobaciones de las instantáneas (copia local, publicación y migración sin cambiar un
byte, RF-009-23) parten de él, y ningún código posterior puede volver a escribirlo (por eso se
versiona el resultado y no se genera en cada prueba). Ningún dato de clientes: todo sale de los
datos sintéticos de las specs 005, 006 y 008.

**Huella** de ``esquema2.zip``: 319 693 bytes, sha256
``f29bcf17927f55ca1adb9c6a2ce8a081458d9b690a1be61c4467a4376fbd83f0`` (:data:`ZIP_SHA256`,
:data:`ZIP_BYTES`; la misma línea en ``tests/data/core/projects/README.md``). La comprueba
``tests/unit/core/project/test_schema2_fixture.py``.

**Lo que tiene** (dentro del zip, ``proyectos/Cantera Esquema 2.gbproj/`` y, junto a él, la
carpeta de las entregas ``fuentes/``, a la que apuntan sus entradas con rutas relativas):

- la ventana de trabajo de ``csv_basico`` (699 900 a 700 200 y 4 399 900 a 4 400 200), paso de
  1 m, EPSG:25830 + EPSG:5782, con la sesión sintética de ``tests.support.core_fixtures``
  (equipo «PC-PRUEBA-A», usuario «prueba»), no la del equipo que lo generó;
- **la 008**: la cadena entera de la demostración (``tests.support.provenance_demo``), con
  ``fuentes/Limites.gpkg`` (``Limites_v1.gpkg``) importado y su área, los bancos y las marcas
  de acopio, los años por banco, los dos acopios acoplados y el balance;
- **la 006**: el MDT de 1 m ``fuentes/mdt_1m.tif`` (``tests/data/gis/geotiff/f64_strip.tif``)
  importado con ``geoblender.gis_import_dtm`` (``gis_src_mdt``, en ``rasters/``) y su rejilla del
  proyecto con ``geoblender.gis_resample_to_grid`` (``gis_dtm_mdt``, que lee el parámetro
  ``gis.resample.min_valid_fraction``);
- **la 005**: los seis ficheros de ``csv_basico`` importados con
  ``geoblender.dh_import_drillholes`` (sus códigos nuevos dados de alta), la base, su validación y
  las trazas (``geoblender.dh_desurvey``);
- **la vista** ``scenes/principal.blend``, guardada con ``geoblender.core_save_project`` con el MDT
  importado y los sondeos cargados.

Sin ``cache/`` ni ``.lock`` (lo que tampoco copian la copia local ni la publicación de la 002) y
cerrado. Las fechas de los ficheros del zip son una fija (:data:`ZIP_DATE`): al descomprimirlo,
los ficheros tienen la fecha de ese momento, como una copia restaurada.

**Para usarlo**: :func:`extract` lo descomprime en una carpeta (la de la prueba) y devuelve la
carpeta del proyecto. Solo lectura del repositorio; no importa Geoblender ni ``bpy``.

**Cómo se generó** (desde la raíz del repositorio de código, en PowerShell, con un perfil
temporal y el código de partida; con el esquema 3 ya no se puede, y se niega)::

    $env:BLENDER_USER_RESOURCES = (New-Item -ItemType Directory -Force "$env:TEMP\\gb-perfil-s2").FullName
    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" -b --factory-startup `
        --python-exit-code 1 --python tools/inblender/schema2_project.py -- [--salida ZIP]

El guion de ``tools/inblender/`` solo le da ``bpy`` a :func:`generate` (este módulo no importa
los módulos de Blender, ARQ-01). Dentro de Blender, como ``tools/run_blender_tests.py``: copia
la extensión a una carpeta temporal, la registra como repositorio ``gb_tests`` y la habilita
(``tests.support.blender_ext``), construye el proyecto en otra carpeta temporal con las órdenes
reales (las lecturas de las tablas de sondeos, en el hilo con la función de su proceso aparte,
como ``tests/blender/test_dh_import_tabular.py``; el ``--site`` de las ruedas, ``.deps/site``,
como ``tests/blender/gis/test_ops_dtm.py``), escribe el zip y lo deja todo como estaba.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import zipfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

ROOT: Path = Path(__file__).resolve().parents[2]
DATA_DIR: Path = ROOT / "tests" / "data" / "core" / "projects"
ZIP_PATH: Path = DATA_DIR / "esquema2.zip"
ZIP_SHA256 = "f29bcf17927f55ca1adb9c6a2ce8a081458d9b690a1be61c4467a4376fbd83f0"
"""El sha256 de :data:`ZIP_PATH` (su huella; también en el docstring y en el README)."""
ZIP_BYTES = 319_693
"""El tamaño de :data:`ZIP_PATH`, en bytes."""
MAX_ZIP_BYTES = 2 * 1024 * 1024
"""El tamaño máximo del zip (tasks.md, T03): 2 MiB."""
ZIP_DATE = (2026, 10, 18, 0, 0, 0)
"""La fecha de todos los ficheros del zip (la del código de partida)."""

SCHEMA = 2
"""El esquema del proyecto del zip."""
PROJECT_NAME = "Cantera Esquema 2"
PROJECTS_FOLDER = "proyectos"
SOURCES_FOLDER = "fuentes"
PROJECT_FOLDER = f"{PROJECTS_FOLDER}/{PROJECT_NAME}.gbproj"
"""La carpeta del proyecto dentro del zip (y dentro de la de :func:`extract`)."""
VIEW = "scenes/principal.blend"
"""La vista guardada, relativa a la carpeta del proyecto."""
EXCLUDED = ("cache", ".lock")
"""Lo que no entra en el zip (lo que tampoco copian la copia local ni la publicación)."""

WINDOW: tuple[float, float, float, float] = (699_900.0, 4_399_900.0, 700_200.0, 4_400_200.0)
"""La ventana de trabajo (la de ``tests/data/dh/csv_basico/esperado.json``), en m."""
STEP_M = 1.0
SESSION = {
    "session_uid": "00000000-0000-4000-8000-000000000001",
    "host": "PC-PRUEBA-A",
    "user": "prueba",
}
"""La sesión sintética con la que se generó (la de ``tests.support.core_fixtures``)."""
DTM_SOURCE = "geotiff/f64_strip.tif"
"""El MDT de 1 m de la 006 (``tests/data/gis/``) que se importa."""
DTM_FILE = "mdt_1m.tif"
DTM_NAME = "MDT"
BOUNDARY_FILE = "Limites.gpkg"
DH_FILES: tuple[str, ...] = ("bocas.csv", "desviaciones.csv", "litologia.csv",
                             "analisis_columnas.csv", "litologias.csv", "elementos.csv")
"""Los ficheros de ``csv_basico`` que se importan (los análisis en columnas, no en filas)."""
DH_DECLARED = {"crs": "EPSG:25830", "vertical": "PROJECT", "azimuth_ref": "GRID",
               "inclination_convention": "NEGATIVE_DOWN", "all_vertical": True,
               "decimal_mark": "COMMA", "separator": "SEMICOLON", "encoding": "UTF8",
               "date_format": "%d/%m/%Y", "units": "Au=g/t; Ag=ppm; Cu=%",
               "density_kind": "ADOPTADO"}
"""Lo declarado de ``csv_basico`` (``tests/data/dh/README.md``)."""

JOB_WAIT_S = 120.0
MAX_TICKS = 300


def sha256(path: Path) -> str:
    """El sha256 del fichero ``path``."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def extract(target: Path) -> Path:
    """Descomprime :data:`ZIP_PATH` en ``target`` (que debe existir) y devuelve la carpeta del
    proyecto (``target/proyectos/Cantera Esquema 2.gbproj``); ``fuentes/`` queda junto a
    ``proyectos/``."""
    target = Path(target)
    with zipfile.ZipFile(ZIP_PATH) as archive:
        for name in archive.namelist():
            if name.startswith(("/", "\\")) or ".." in Path(name).parts or ":" in name:
                raise ValueError(f"«{name}» no es una ruta relativa dentro del zip")
        archive.extractall(target)
    return target / PROJECTS_FOLDER / f"{PROJECT_NAME}.gbproj"


# --- La generación (dentro de Blender) --------------------------------------------------------


def _members(work: Path) -> Iterator[tuple[str, Path]]:
    """Lo que va al zip, en orden: la ruta dentro del zip y la de disco (las carpetas, con
    «/» al final), sin :data:`EXCLUDED` del proyecto."""
    project = work / PROJECT_FOLDER
    for top in (work / SOURCES_FOLDER, project):
        yield f"{top.relative_to(work).as_posix()}/", top
        for path in sorted(top.rglob("*")):
            rel = path.relative_to(work).as_posix()
            if top is project and path.relative_to(project).parts[0] in EXCLUDED:
                continue
            yield (f"{rel}/" if path.is_dir() else rel), path


def write_zip(work: Path, target: Path) -> None:
    """El zip de ``work/proyectos/<proyecto>`` y ``work/fuentes`` en ``target`` (comprimido, en
    orden y con la fecha :data:`ZIP_DATE`)."""
    partial = target.with_name(target.name + ".tmp")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for name, path in _members(work):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            if name.endswith("/"):
                info.external_attr = (0o40755 << 16) | 0x10
                archive.writestr(info, b"")
            else:
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes(), compresslevel=9)
    os.replace(partial, target)


class _Builder:  # pragma: no cover - solo dentro de Blender, con la extensión habilitada
    """Construye el proyecto en ``work`` con las órdenes reales (véase el módulo)."""

    def __init__(self, bpy: Any, work: Path) -> None:
        import importlib

        from tests.support.blender_ext import module_name

        def ext(name: str):  # noqa: ANN202 - un módulo de la copia de la extensión
            return importlib.import_module(f"{module_name()}.{name}")

        self.ext = ext
        self.bpy = bpy
        self.work = work
        self.sources = work / SOURCES_FOLDER
        self.ps = ext("bl.scene.project_session")
        self.session = ext("bl.ops.core_provenance")
        self.jobs_ops = ext("bl.ops.jobs")
        self.dh_ops = ext("bl.ops.dh")
        self.gis_ops = ext("bl.ops.gis")
        self.catalog = ext("jobs.catalog")
        self.project = None

    # --- Trabajos ------------------------------------------------------------------------------

    def finish(self) -> None:
        """Avanza a mano el monitor de los trabajos y las colas de incorporación de los sondeos
        y de la topografía hasta que no queda nada (en ``blender -b`` no corren los
        temporizadores)."""
        import time

        runner = self.jobs_ops.MONITOR.runner
        deadline = time.monotonic() + JOB_WAIT_S
        while time.monotonic() < deadline:
            self.jobs_ops.tick()
            self.dh_ops.incorporation_tick()
            self.gis_ops.incorporation_tick()
            if self.dh_ops.pending_incorporations() or self.gis_ops.pending_incorporations():
                continue
            if not any(snapshot.active for snapshot in runner.snapshots()):
                self.jobs_ops.tick()
                if (not any(snapshot.active for snapshot in runner.snapshots())
                        and not self.dh_ops.pending_incorporations()
                        and not self.gis_ops.pending_incorporations()):
                    return
            time.sleep(0.002)
        raise RuntimeError("los trabajos no terminan")

    def run(self, idname: str, **props: object) -> None:
        """La orden ``idname`` (``EXEC_DEFAULT``) y sus trabajos hasta el final."""
        group, name = idname.split(".")
        result = getattr(getattr(self.bpy.ops, group), name)("EXEC_DEFAULT", **props)
        if result != {"FINISHED"}:
            raise RuntimeError(f"{idname} terminó con {result}")
        self.finish()
        self.ps.take_notices()

    def read_in_thread(self) -> None:
        """La lectura de una tabla de sondeos en el hilo, con la función de su proceso aparte
        (como ``tests/blender/test_dh_import_tabular.py``)."""
        import dataclasses

        reading = self.ext("interop.dh_jobs")
        name = self.ext("drillholes.jobs").IMPORT_TABULAR
        info = self.catalog.WORKERS[name]
        fast = dataclasses.replace(info, policy="auto", estimate_s=lambda params: 0.01,
                                   run=reading.run_import_tabular)
        self.catalog.unregister_worker(name)
        self.catalog.register_worker(fast)

    # --- El proyecto ---------------------------------------------------------------------------

    def create(self) -> None:
        """El proyecto nuevo, abierto en la sesión con su comprobación de apertura hecha."""
        from tests.support.core_fixtures import settings_values

        core = self.ext("core.project")
        parent = self.work / PROJECTS_FOLDER
        parent.mkdir()
        settings = core.ProjectSettings(**settings_values(name=PROJECT_NAME, window=WINDOW,
                                                          grid_step_m=STEP_M))
        project = core.create_project(parent, settings, self.ps.session(),
                                      self.ps.userdata()).project
        if project.record.schema_version != SCHEMA:
            raise RuntimeError(f"el código de partida crea el esquema {SCHEMA}, no el "
                               f"{project.record.schema_version}")
        self.ps.attach(project)
        for _ in range(MAX_TICKS):
            if self.session.check_tick() is None:
                break
        self.ps.take_notices()
        self.project = project

    def demo_chain(self) -> None:
        """La 008: la cadena entera de la demostración, con el límite de ``fuentes/``."""
        from tests.support import provenance_data
        from tests.support.blender_ext import module_name
        from tests.support.provenance_demo import Demo

        source = self.sources / BOUNDARY_FILE
        shutil.copyfile(provenance_data.DATA_DIR / provenance_data.BOUNDARY_V1, source)
        project = self.project
        with Demo(module_name()).registered() as demo:
            boundary = demo.import_boundary(project, source)
            demo.area(project, boundary.dataset.name)
            demo.digitize(project)
            demo.bench_years(project)
            demo.stockpiles(project)
            demo.balance(project)

    def dtm(self) -> None:
        """La 006: el MDT de 1 m importado y su rejilla del proyecto."""
        source = self.sources / DTM_FILE
        shutil.copyfile(ROOT / "tests" / "data" / "gis" / DTM_SOURCE, source)
        self.run("geoblender.gis_import_dtm", filepath=str(source), name=DTM_NAME,
                 vertical="PROJECT")
        shown, _note = self.gis_ops.fraction_field(self.project)
        self.run("geoblender.gis_resample_to_grid", source="gis_src_mdt", name=DTM_NAME,
                 min_valid_fraction=shown)

    def drillholes(self) -> None:
        """La 005: los seis ficheros de ``csv_basico`` (sus códigos nuevos dados de alta), la
        base, su validación y las trazas."""
        import json

        bpy = self.bpy
        data = ROOT / "tests" / "data" / "dh" / "csv_basico"
        roles = {name: role for role, name in json.loads(
            (data / "esperado.json").read_text(encoding="utf-8"))["files"].items()}
        for name in DH_FILES:
            shutil.copyfile(data / name, self.sources / name)
        self.read_in_thread()
        mapping = [{"file": name, "role": roles[name]} for name in DH_FILES]
        result = bpy.ops.geoblender.dh_import_drillholes(
            "EXEC_DEFAULT", directory=str(self.sources),
            files=[{"name": name} for name in DH_FILES], mapping_json=json.dumps(mapping),
            **DH_DECLARED)
        if result != {"FINISHED"}:
            raise RuntimeError(f"la importación de los sondeos terminó con {result}")
        self.finish()
        waiting = list(self.dh_ops.waiting_imports())
        if waiting:
            (uid,) = waiting
            props = self.ext("bl.props.dh")
            pending = getattr(bpy.context.window_manager, props.IMPORT_PROPERTY)
            pending.register_codes = True
            if bpy.ops.geoblender.dh_import_drillholes("EXEC_DEFAULT", stage="APPLY",
                                                      pending=uid) != {"FINISHED"}:
                raise RuntimeError("no se pudo aplicar la importación de los sondeos")
            self.finish()
        self.ps.take_notices()
        self.run("geoblender.dh_desurvey")  # las trazas y, después, su vista

    def save_view(self) -> None:
        """La vista: el MDT importado cargado (los sondeos ya lo están) y guardada en
        ``scenes/principal.blend``."""
        bpy = self.bpy
        views = self.ext("bl.scene.views")
        views.load_datasets(bpy.context, self.project, ["gis_src_mdt"])
        dh_view = self.ext("bl.scene.dh_view")
        if not dh_view.loaded_objects(self.project):
            raise RuntimeError("los sondeos no están cargados en la vista")
        if bpy.ops.geoblender.core_save_project("EXEC_DEFAULT") != {"FINISHED"}:
            raise RuntimeError("no se pudo guardar la vista")
        if not (self.project.root / VIEW).is_file():
            raise RuntimeError(f"la vista no está en «{VIEW}»")

    def build(self) -> None:
        """Todo, y el proyecto cerrado."""
        from unittest import mock

        sysinfo = self.ext("core.sysinfo")
        version = self.ps.session().geoblender_version
        self.ps._STATE.session = sysinfo.SessionInfo(  # la sesión sintética, no la del equipo
            SESSION["session_uid"], SESSION["host"], SESSION["user"], os.getpid(), version)
        self.sources.mkdir()
        site = ROOT / ".deps" / "site"
        try:
            with mock.patch.object(self.gis_ops, "wheels_site", lambda: site):
                self.create()
                self.demo_chain()
                self.dtm()
                self.drillholes()
                self.save_view()
        finally:
            self.jobs_ops.MONITOR.stop()
            self.ps.close()


def _arguments(argv: Sequence[str]) -> Path:
    args = list(argv)
    args = args[args.index("--") + 1:] if "--" in args else []
    if not args:
        return ZIP_PATH
    if len(args) == 2 and args[0] == "--salida":
        return Path(args[1]).resolve()
    raise SystemExit("uso: … --python tools/inblender/schema2_project.py -- [--salida ZIP]")


def generate(bpy: Any, argv: Sequence[str]) -> int:  # pragma: no cover - dentro de Blender
    """Genera el zip (véase el módulo) con el ``bpy`` de la sesión de Blender que lo pide (el
    guion de ``tools/inblender/``) y los argumentos de su línea de órdenes; devuelve el código
    de salida."""
    import importlib
    import tempfile

    target = _arguments(argv)
    from gbtools import ext_copy  # tools/ en sys.path: lo pone el guion

    from tests.support import blender_ext

    temp = Path(tempfile.mkdtemp(prefix="gb-s2e-"))
    work = Path(tempfile.mkdtemp(prefix="gb-s2-"))
    module = "bl_ext.gb_tests.geoblender"
    repos = bpy.context.preferences.extensions.repos
    repo = None
    try:
        ext_copy.make_copy(ROOT, temp)
        repo = repos.new(name="Geoblender (esquema 2)", module="gb_tests",
                         custom_directory=str(temp), source="USER")
        os.environ[blender_ext.ENV_MODULE] = module
        blender_ext.enable()
        schema = importlib.import_module(f"{module}.core.project.schema")
        if schema.SCHEMA_VERSION != SCHEMA:
            print(f"Este generador escribe un proyecto del esquema {SCHEMA} con el código de "
                  f"partida; este código es del esquema {schema.SCHEMA_VERSION}: no se genera",
                  file=sys.stderr)
            return 1
        _Builder(bpy, work).build()
        write_zip(work, target)
    finally:
        if module in sys.modules:
            blender_ext.release()
        for key in [k for k in sys.modules if k == module or k.startswith(module + ".")]:
            del sys.modules[key]
        os.environ.pop(blender_ext.ENV_MODULE, None)
        if repo is not None:
            repos.remove(repo)
        shutil.rmtree(temp, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
    print(f"{target}: {target.stat().st_size} bytes, sha256 {sha256(target)}")
    return 0

