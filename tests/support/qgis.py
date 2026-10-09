# SPDX-License-Identifier: GPL-3.0-or-later
"""El GDAL de QGIS para las pruebas de compatibilidad del GeoPackage (spec 002, T35; plan
002 §7: la prueba con GDAL y QGIS es opcional y se omite con ``[ENTORNO] qgis``) y para las
de la procedencia (spec 008, T41: :func:`edit_gpkg`).

QGIS llega por ``GEOBLENDER_QGIS_DIR``, la carpeta de su instalación (la que tiene
``bin\\ogrinfo.exe``); su ruta no se escribe en ningún sitio. Las órdenes se lanzan con
el entorno que prepara su ``bin\\o4w_env.bat`` (``PATH``, ``GDAL_DATA``,
``GDAL_DRIVER_PATH``, ``PROJ_DATA`` y el ``PYTHONHOME`` de su Python), sin el
``PROJ_LIB`` ni las demás variables ``PROJ_*``, ``GDAL_*``, ``PYTHON*`` y ``OSGEO4W_*``
del puesto (en el de IMGA, ``PROJ_LIB`` apunta al ``proj.db`` de PostGIS: Silvestre
TOP-05), con ``GDAL_PAM_ENABLED=NO`` (sin ``.aux.xml``) y sin escribir ``__pycache__``.
Las pruebas de la 002 solo leen con GDAL. Las de la 008 editan con él, como QGIS, un
GeoPackage de una carpeta temporal (una fuente o el proyecto de la prueba): :func:`edit_gpkg`
aplica en un solo proceso del Python de QGIS las ediciones de :func:`resave_layer`,
:func:`move_vertex`, :func:`set_field` y :func:`change_field_type`, cada una abriendo y
cerrando el GeoPackage, y dice de cada una si GDAL la dio por buena o el error con que falló.

El recurso ``qgis`` (:data:`QGIS`, ``tests.support.resources``) está disponible si la
variable apunta a una carpeta con ``bin\\ogrinfo.exe`` y un Python en ``apps\\Python3*``
con ``osgeo`` y el ``validate_gpkg.py`` de ``osgeo_utils``.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.support import resources
from tests.support.repo import tools_on_path

tools_on_path()

from gbtools import blender  # noqa: E402

QGIS = "qgis"  # el recurso de tests.support.resources
ENV_QGIS_DIR = "GEOBLENDER_QGIS_DIR"
QGIS_HINT = (
    "instale QGIS 4.2 y defina GEOBLENDER_QGIS_DIR con su carpeta de instalación (la que "
    "tiene bin\\ogrinfo.exe)"
)
RUN_TIMEOUT_S = 300.0
# Variables del puesto que cambiarían lo que hace el GDAL de QGIS (prefijos, sin
# distinguir mayúsculas): las de PROJ y GDAL, las de Python y las de OSGeo4W.
DROPPED_PREFIXES: tuple[str, ...] = ("PROJ_", "GDAL_", "PYTHON", "OSGEO4W_")
VALIDATE_GPKG_RELPATH = Path("Lib", "site-packages", "osgeo_utils", "samples", "validate_gpkg.py")
OSGEO_RELPATH = Path("Lib", "site-packages", "osgeo", "__init__.py")


@dataclass(frozen=True)
class QgisInstall:
    """Una instalación de QGIS con su GDAL y su Python."""

    root: Path
    python_home: Path

    @property
    def bin_dir(self) -> Path:
        return self.root / "bin"

    @property
    def python(self) -> Path:
        return self.python_home / "python.exe"

    @property
    def validate_gpkg(self) -> Path:
        return self.python_home / VALIDATE_GPKG_RELPATH

    def tool(self, name: str) -> Path:
        """Un programa de ``bin`` (``ogrinfo``…)."""
        return self.bin_dir / f"{name}.exe"


def find_install(environ: Mapping[str, str] | None = None) -> QgisInstall | None:
    """La instalación de ``GEOBLENDER_QGIS_DIR`` si tiene lo que usan las pruebas; si no
    (sin la variable, carpeta inexistente o incompleta), ``None``."""
    value = (os.environ if environ is None else environ).get(ENV_QGIS_DIR, "").strip()
    if not value:
        return None
    root = Path(value)
    if not (root / "bin" / "ogrinfo.exe").is_file():
        return None
    for home in sorted(root.glob("apps/Python3*"), reverse=True):
        install = QgisInstall(root, home)
        if (
            install.python.is_file()
            and install.validate_gpkg.is_file()
            and (home / OSGEO_RELPATH).is_file()
        ):
            return install
    return None


def qgis_available() -> bool:
    """Si ``GEOBLENDER_QGIS_DIR`` da una instalación de QGIS utilizable."""
    return find_install() is not None


resources.register_resource(QGIS, qgis_available)


def gdal_env(install: QgisInstall, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copia de ``base`` (por defecto, el entorno del proceso) con el entorno de
    ``o4w_env.bat`` de ``install`` y sin las variables del puesto de
    :data:`DROPPED_PREFIXES`."""
    source = os.environ if base is None else base
    env = {
        name: value
        for name, value in source.items()
        if not name.upper().startswith(DROPPED_PREFIXES) and name.upper() != "PATH"
    }
    windir = source.get("WINDIR") or source.get("SystemRoot") or r"C:\Windows"
    root = install.root
    env.update(
        {
            "OSGEO4W_ROOT": str(root),
            "PATH": os.pathsep.join(
                [
                    str(install.bin_dir),
                    str(install.python_home / "Scripts"),
                    str(Path(windir) / "system32"),
                    windir,
                    str(Path(windir) / "system32" / "WBem"),
                ]
            ),
            "GDAL_DATA": str(root / "apps" / "gdal" / "share" / "gdal"),
            "GDAL_DRIVER_PATH": str(root / "apps" / "gdal" / "lib" / "gdalplugins"),
            "GDAL_PAM_ENABLED": "NO",
            "PROJ_DATA": str(root / "share" / "proj"),
            "PYTHONHOME": str(install.python_home),
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return env


def _install() -> QgisInstall:
    install = find_install()
    if install is None:
        raise RuntimeError(
            f"no hay QGIS utilizable en {ENV_QGIS_DIR}: decore la prueba con "
            f"tests.support.resources.requires({QGIS!r}, …)"
        )
    return install


def run_tool(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Ejecuta un programa de GDAL de QGIS (``ogrinfo``…) con :func:`gdal_env`."""
    install = _install()
    return blender.run(
        [str(install.tool(name)), *args], env=gdal_env(install), timeout=RUN_TIMEOUT_S
    )


def run_python(*args: str) -> subprocess.CompletedProcess[str]:
    """Ejecuta el Python de QGIS (``-B -s``) con :func:`gdal_env`: ``args`` es un guion y
    sus argumentos, o ``-c`` y un texto."""
    install = _install()
    return blender.run(
        [str(install.python), "-B", "-s", *args], env=gdal_env(install), timeout=RUN_TIMEOUT_S
    )


def validate_gpkg_script() -> str:
    """La ruta del ``validate_gpkg.py`` del GDAL de QGIS."""
    return str(_install().validate_gpkg)


def output_of(result: subprocess.CompletedProcess[str]) -> str:
    """La salida estándar y la de errores de una orden, juntas y sin blancos al final."""
    parts = [(result.stdout or "").rstrip(), (result.stderr or "").rstrip()]
    return "\n".join(part for part in parts if part)


# --- Ediciones con el GDAL de QGIS (spec 008, T41) ------------------------------------------

EDIT_SCRIPT = r"""
import json
import sys

from osgeo import gdal, ogr

gdal.UseExceptions()


def find(layer, where):
    field, value = where
    layer.ResetReading()
    for feature in layer:
        if feature.GetField(field) == value:
            return feature
    raise ValueError(f"no hay ninguna entidad con {field} = {value!r}")


def resave_layer(dataset, edit):
    layer = dataset.GetLayerByName(edit["layer"])
    features = list(layer)
    layer.StartTransaction()
    for feature in features:
        layer.SetFeature(feature)
    layer.CommitTransaction()


def move_vertex(dataset, edit):
    layer = dataset.GetLayerByName(edit["layer"])
    feature = find(layer, edit["where"])
    ring = feature.GetGeometryRef().GetGeometryRef(0)
    points = [ring.GetPoint_2D(i) for i in range(ring.GetPointCount())]
    x, y = points[edit["vertex"]]
    points[edit["vertex"]] = (x + edit["dx"], y + edit["dy"])
    if edit["vertex"] == 0:
        points[-1] = points[0]
    moved = ogr.Geometry(ogr.wkbLinearRing)
    for point in points:
        moved.AddPoint_2D(*point)
    polygon = ogr.Geometry(ogr.wkbPolygon)
    polygon.AddGeometry(moved)
    feature.SetGeometry(polygon)
    layer.SetFeature(feature)


def set_field(dataset, edit):
    layer = dataset.GetLayerByName(edit["layer"])
    feature = find(layer, edit["where"])
    feature.SetField(edit["field"], edit["value"])
    layer.SetFeature(feature)


def change_field_type(dataset, edit):
    layer = dataset.GetLayerByName(edit["layer"])
    index = layer.GetLayerDefn().GetFieldIndex(edit["field"])
    field = ogr.FieldDefn(edit["field"], getattr(ogr, "OFT" + edit["type"]))
    layer.AlterFieldDefn(index, field, ogr.ALTER_TYPE_FLAG)


EDITS = {name: globals()[name] for name in ("resave_layer", "move_vertex", "set_field",
                                            "change_field_type")}
results = []
for edit in json.loads(sys.argv[1]):
    try:
        dataset = gdal.OpenEx(edit["path"], gdal.OF_VECTOR | gdal.OF_UPDATE)
        try:
            EDITS[edit["edit"]](dataset, edit)
        finally:
            dataset.Close()
        results.append([True, None])
    except Exception as exc:
        results.append([False, str(exc)])
print(json.dumps({"gdal": gdal.__version__, "results": results}))
"""
"""El guion que aplica las ediciones con el Python de QGIS: una lista JSON de ediciones en su
primer argumento; en la salida, la versión de GDAL y ``[bien, error]`` de cada una."""


@dataclass(frozen=True)
class EditResult:
    """Lo que dijo GDAL de una edición: si la dio por buena y, si no, su error."""

    ok: bool
    error: str | None


@dataclass(frozen=True)
class EditOutcome:
    """Las ediciones de :func:`edit_gpkg`: la versión de GDAL de QGIS y el resultado de cada
    una, en su orden."""

    version: str
    results: tuple[EditResult, ...]


def _edit(kind: str, path: str | os.PathLike[str], layer: str, **values: Any) -> dict[str, Any]:
    return {"edit": kind, "path": os.fspath(path), "layer": layer, **values}


def resave_layer(path: str | os.PathLike[str], layer: str) -> dict[str, Any]:
    """Abrir y guardar sin cambios la capa ``layer`` de ``path``: reescribe todas sus entidades
    tal cual, en una transacción (como QGIS al guardar)."""
    return _edit("resave_layer", path, layer)


def move_vertex(path: str | os.PathLike[str], layer: str, where: tuple[str, Any], vertex: int,
                *, dx: float = 0.0, dy: float = 0.0) -> dict[str, Any]:
    """Mueve (``dx``, ``dy``, en las unidades del CRS) el vértice ``vertex`` del anillo
    exterior del polígono (simple, sin huecos) de la entidad cuyo campo ``where[0]`` vale
    ``where[1]``."""
    return _edit("move_vertex", path, layer, where=list(where), vertex=vertex, dx=dx, dy=dy)


def set_field(path: str | os.PathLike[str], layer: str, where: tuple[str, Any], field: str,
              value: Any) -> dict[str, Any]:
    """Pone ``value`` en el campo ``field`` de la entidad (o fila) cuyo campo ``where[0]`` vale
    ``where[1]``."""
    return _edit("set_field", path, layer, where=list(where), field=field, value=value)


def change_field_type(path: str | os.PathLike[str], layer: str, field: str,
                      field_type: str) -> dict[str, Any]:
    """Cambia el tipo del campo ``field`` a ``field_type`` (el de OGR sin «OFT»:
    ``Integer64``, ``Real``, ``String``…): GDAL rehace la tabla."""
    return _edit("change_field_type", path, layer, field=field, type=field_type)


def edit_gpkg(*edits: Mapping[str, Any]) -> EditOutcome:
    """Aplica ``edits`` (de :func:`resave_layer`, :func:`move_vertex`, :func:`set_field` y
    :func:`change_field_type`) en su orden con el GDAL de QGIS, en un solo proceso de su
    Python; cada una abre el GeoPackage en escritura y lo cierra. :class:`RuntimeError` si el
    proceso no termina bien (una edición que GDAL rechaza no lo es: queda en su resultado)."""
    result = run_python("-c", EDIT_SCRIPT, json.dumps([dict(edit) for edit in edits]))
    if result.returncode != 0:
        raise RuntimeError(f"el GDAL de QGIS no aplicó las ediciones: {output_of(result)}")
    found = json.loads(result.stdout.strip().splitlines()[-1])
    return EditOutcome(found["gdal"], tuple(EditResult(ok, error)
                                            for ok, error in found["results"]))
