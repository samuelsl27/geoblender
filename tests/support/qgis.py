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
:func:`move_vertex`, :func:`set_field`, :func:`change_field_type` y :func:`set_geometry`, cada
una abriendo y cerrando el GeoPackage, y dice de cada una si GDAL la dio por buena o el error con que falló.

El recurso ``qgis`` (:data:`QGIS`, ``tests.support.resources``) está disponible si la
variable apunta a una carpeta con ``bin\\ogrinfo.exe`` y un Python en ``apps\\Python3*``
con ``osgeo`` y el ``validate_gpkg.py`` de ``osgeo_utils``.

Lo que solo sabe QGIS (spec 006, T55: si carga el estilo por defecto de una capa) se pregunta
a PyQGIS sin interfaz con :func:`run_pyqgis`: un proceso del Python de QGIS con su paquete
``qgis``, la plataforma ``offscreen`` de Qt y un perfil de QGIS temporal (nunca el del
usuario ni su QGIS abierto); tarda alrededor de 1 s. Con él, :func:`reopen_layers` (spec 009,
T27) lista y abre como QGIS las capas de unos ficheros en dos copias de un proyecto, la de
antes y la de después de un cambio, y abre en la de después un proyecto de QGIS guardado en la
de antes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
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


PYQGIS_PROFILE_ENV = "GEOBLENDER_PYQGIS_PROFILE"
_PYQGIS_START = (
    "import os as _gb_os\n"
    "from qgis.core import QgsApplication as _GbApplication\n"
    f"_gb_app = _GbApplication([], False, _gb_os.environ[{PYQGIS_PROFILE_ENV!r}])\n"
    "_gb_app.initQgis()\n"
    "try:\n"
)
_PYQGIS_END = "finally:\n    _gb_app.exitQgis()\n"


def pyqgis_env(install: QgisInstall, profile: Path) -> dict[str, str]:
    """El entorno de :func:`gdal_env` con lo que necesita PyQGIS sin interfaz (spec 006, T55):
    su paquete ``qgis`` y sus bibliotecas (``apps\\qgis`` y ``apps\\qt6``), la plataforma
    ``offscreen`` de Qt con las fuentes de Windows (sin ellas, los textos salen como cuadros:
    ``docs/trampas.md`` §6) y el perfil de QGIS ``profile`` (no el del usuario)."""
    env = gdal_env(install)
    apps = install.root / "apps"
    windir = env.get("WINDIR") or env.get("SystemRoot") or r"C:\Windows"
    env.update({
        "PATH": os.pathsep.join([str(apps / "qgis" / "bin"), str(apps / "qt6" / "bin"),
                                 env["PATH"]]),
        "PYTHONPATH": str(apps / "qgis" / "python"),
        "QGIS_PREFIX_PATH": str(apps / "qgis"),
        "QT_PLUGIN_PATH": os.pathsep.join([str(apps / "qgis" / "qtplugins"),
                                           str(apps / "qt6" / "plugins")]),
        "QT_QPA_PLATFORM": "offscreen",
        "QT_QPA_FONTDIR": str(Path(windir) / "Fonts"),
        "QGIS_CUSTOM_CONFIG_PATH": str(profile),
        PYQGIS_PROFILE_ENV: str(profile),
    })
    return env


def _pyqgis(code: str) -> tuple[QgisInstall, str]:
    """La instalación con PyQGIS y el guion que ejecuta ``code`` en una ``QgsApplication``
    ya iniciada. :class:`RuntimeError` si no tiene PyQGIS."""
    install = _install()
    if not (install.root / "apps" / "qgis" / "python" / "qgis").is_dir():
        raise RuntimeError(f"la instalación de QGIS de {ENV_QGIS_DIR} no tiene PyQGIS "
                           "(apps\\qgis\\python\\qgis)")
    return install, _PYQGIS_START + textwrap.indent(textwrap.dedent(code), "    ") + _PYQGIS_END


def run_pyqgis(code: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Ejecuta ``code`` con PyQGIS sin interfaz (``-c``, con ``args`` en ``sys.argv[1:]``)
    dentro de una ``QgsApplication`` ya iniciada con un perfil de QGIS temporal, que se borra
    al terminar: no se toca el QGIS del usuario ni su perfil. :class:`RuntimeError` si la
    instalación no tiene PyQGIS (``apps\\qgis\\python\\qgis``)."""
    install, script = _pyqgis(code)
    profile = Path(tempfile.mkdtemp(prefix="gb-pyqgis-"))
    try:
        return blender.run([str(install.python), "-B", "-s", "-c", script, *args],
                           env=pyqgis_env(install, profile), timeout=RUN_TIMEOUT_S)
    finally:
        shutil.rmtree(profile, ignore_errors=True)


_ARGS_FROM_STDIN = ("import json as _gb_json, sys as _gb_sys\n"
                    "_gb_sys.argv[1:] = _gb_json.loads(_gb_sys.stdin.readline())\n")


class PyqgisProcess:
    """``code`` con PyQGIS sin interfaz, como :func:`run_pyqgis`, pero lanzado **antes** de
    tener sus argumentos (spec 009, T27): QGIS arranca (≈ 1 s) mientras la prueba prepara lo
    que va a abrir, y :meth:`finish` le pasa los argumentos (``sys.argv[1:]``) por la entrada
    estándar, en una línea JSON, y espera a que termine. :meth:`close` (también al salir de
    ``with``) lo termina si no ha terminado y borra su perfil temporal."""

    def __init__(self, code: str) -> None:
        install, script = _pyqgis(_ARGS_FROM_STDIN + textwrap.dedent(code))
        self._profile = Path(tempfile.mkdtemp(prefix="gb-pyqgis-"))
        try:
            self._process = subprocess.Popen(
                [str(install.python), "-B", "-s", "-c", script],
                env=pyqgis_env(install, self._profile), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace")
        except BaseException:
            shutil.rmtree(self._profile, ignore_errors=True)
            raise

    def finish(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Le pasa ``args`` y devuelve su código y su salida, como :func:`run_pyqgis`;
        ``subprocess.TimeoutExpired`` si no termina en :data:`RUN_TIMEOUT_S`."""
        try:
            stdout, stderr = self._process.communicate(json.dumps(list(args)) + "\n",
                                                       timeout=RUN_TIMEOUT_S)
        finally:
            self.close()
        return subprocess.CompletedProcess(self._process.args, self._process.returncode,
                                           stdout, stderr)

    def close(self) -> None:
        """Lo termina si sigue en marcha y borra su perfil."""
        if self._process.poll() is None:
            self._process.kill()
            self._process.communicate()
        shutil.rmtree(self._profile, ignore_errors=True)

    def __enter__(self) -> PyqgisProcess:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


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


def set_geometry(dataset, edit):
    layer = dataset.GetLayerByName(edit["layer"])
    feature = find(layer, edit["where"])
    feature.SetGeometry(ogr.CreateGeometryFromWkt(edit["wkt"]))
    layer.SetFeature(feature)


EDITS = {name: globals()[name] for name in ("resave_layer", "move_vertex", "set_field",
                                            "change_field_type", "set_geometry")}
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


def set_geometry(path: str | os.PathLike[str], layer: str, where: tuple[str, Any],
                 wkt: str) -> dict[str, Any]:
    """Sustituye la geometría de la entidad cuyo campo ``where[0]`` vale ``where[1]`` por la del
    texto WKT ``wkt`` (spec 012, T20: redibujar un perímetro en QGIS), con el SRS de la capa."""
    return _edit("set_geometry", path, layer, where=list(where), wkt=wkt)


def edit_gpkg(*edits: Mapping[str, Any]) -> EditOutcome:
    """Aplica ``edits`` (de :func:`resave_layer`, :func:`move_vertex`, :func:`set_field`,
    :func:`change_field_type` y :func:`set_geometry`) en su orden con el GDAL de QGIS, en un
    solo proceso de su Python; cada una abre el GeoPackage en escritura y lo cierra. :class:`RuntimeError` si el
    proceso no termina bien (una edición que GDAL rechaza no lo es: queda en su resultado)."""
    result = run_python("-c", EDIT_SCRIPT, json.dumps([dict(edit) for edit in edits]))
    if result.returncode != 0:
        raise RuntimeError(f"el GDAL de QGIS no aplicó las ediciones: {output_of(result)}")
    found = json.loads(result.stdout.strip().splitlines()[-1])
    return EditOutcome(found["gdal"], tuple(EditResult(ok, error)
                                            for ok, error in found["results"]))


# --- Capas abiertas con QGIS antes y después de un cambio (spec 009, T27) --------------------

QGZ_NAME = "geoblender-capas.qgz"
"""El proyecto de QGIS de :func:`reopen_layers`: se guarda en la carpeta de antes y se abre
copiado en la de después."""
INTERNAL_PREFIX = "gb_"
"""El prefijo de las tablas internas de Geoblender en ``project.gpkg``. No están en
``gpkg_contents``: QGIS 4.2 las lista, pero no las abre (la capa no es válida: su GDAL no abre
una tabla sin registrar sin ``LIST_ALL_TABLES=YES``), así que :func:`reopen_layers` solo las
lista."""

REOPEN_SCRIPT = r"""
import json
import shutil
import sys
from pathlib import Path

from qgis.core import (Qgis, QgsProject, QgsProviderRegistry, QgsProviderSublayerDetails,
                       QgsWkbTypes)

before, after = Path(sys.argv[1]), Path(sys.argv[2])
files = json.loads(sys.argv[3])
qgz, internal = sys.argv[4], sys.argv[5]
registry = QgsProviderRegistry.instance()
project = QgsProject.instance()
options = QgsProviderSublayerDetails.LayerOptions(project.transformContext())


def where(provider, uri, root):
    parts = registry.decodeUri(provider, uri)
    path = Path(parts.get("path") or "")
    try:
        found = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        found = path.as_posix()
    return {"path": found, "layer": parts.get("layerName") or ""}


def kind_of(layer_type):
    if layer_type == Qgis.LayerType.Raster:
        return "raster"
    if layer_type == Qgis.LayerType.Vector:
        return "vector"
    return str(layer_type)


def geometry_of(kind, wkb_type):
    if kind != "vector" or QgsWkbTypes.geometryType(wkb_type) in (Qgis.GeometryType.Null,
                                                                  Qgis.GeometryType.Unknown):
        return ""
    return QgsWkbTypes.displayString(wkb_type)


def listed(root):
    found = []
    for name in files:
        for details in registry.querySublayers(str(root / name)):
            kind = kind_of(details.type())
            found.append((details, {**where(details.providerKey(), details.uri(), root),
                                    "provider": details.providerKey(), "kind": kind,
                                    "geometry": geometry_of(kind, details.wkbType())}))
    return found


def describe(layer, root):
    kind = kind_of(layer.type())
    if kind == "raster":
        geometry, size = "", [layer.width(), layer.height(), layer.bandCount()]
    elif kind == "vector":
        geometry, size = geometry_of(kind, layer.wkbType()), [layer.featureCount()]
    else:
        geometry, size = "", []
    return {**where(layer.providerType(), layer.source(), root),
            "provider": layer.providerType(), "kind": kind, "geometry": geometry,
            "valid": layer.isValid(), "size": size}


found = {"qgis": Qgis.version()}
sublayers = listed(before)
found["listed_before"] = [item for _details, item in sublayers]
layers = [details.toLayer(options) for details, item in sublayers
          if not item["layer"].startswith(internal)]
found["before"] = [describe(layer, before) for layer in layers]
project.addMapLayers(layers)
project.setFilePathStorage(Qgis.FilePathType.Relative)
found["written"] = project.write(str(before / qgz))
project.clear()
shutil.copyfile(before / qgz, after / qgz)
found["listed_after"] = [item for _details, item in listed(after)]
found["read"] = project.read(str(after / qgz))
found["reopened"] = [describe(node.layer(), after)
                     for node in project.layerTreeRoot().findLayers()]
project.clear()
print(json.dumps(found))
"""
"""El guion de :func:`reopen_layers` (PyQGIS): las carpetas de antes y de después, la lista JSON
de ficheros, el nombre del proyecto de QGIS y :data:`INTERNAL_PREFIX`; en la salida, la versión
de QGIS, las capas listadas antes, las abiertas antes, si se escribió y se leyó el proyecto,
las listadas después y las que abrió el proyecto."""


@dataclass(frozen=True)
class QgisSublayer:
    """Una capa como la lista QGIS en un fichero: su fichero (ruta relativa a la carpeta del
    proyecto, con «/»), su nombre en él (``""`` en un GeoTIFF), el proveedor (``ogr``,
    ``gdal``), el tipo (``vector``, ``raster``) y la geometría (``LineString``…; ``""`` en una
    tabla o un ráster)."""

    path: str
    layer: str
    provider: str
    kind: str
    geometry: str

    @property
    def key(self) -> tuple[str, str]:
        """El fichero y el nombre de la capa en él."""
        return (self.path, self.layer)

    @property
    def internal(self) -> bool:
        """Si es una tabla interna de Geoblender (:data:`INTERNAL_PREFIX`)."""
        return self.layer.startswith(INTERNAL_PREFIX)


@dataclass(frozen=True)
class QgisLayer(QgisSublayer):
    """Una capa abierta con QGIS: lo de :class:`QgisSublayer`, si QGIS la da por válida y su
    tamaño (las entidades; o el ancho, el alto y las bandas)."""

    valid: bool
    size: tuple[int, ...]

    @property
    def listing(self) -> QgisSublayer:
        """La capa como se lista (sin lo que se sabe al abrirla)."""
        return QgisSublayer(self.path, self.layer, self.provider, self.kind, self.geometry)


@dataclass(frozen=True)
class ReopenOutcome:
    """Lo que vio QGIS en :func:`reopen_layers`: su versión; las capas listadas en los
    ficheros de la carpeta de antes y las de los mismos ficheros en la de después; las que abrió
    en la de antes (todas menos las internas) y las que abrió en la de después el proyecto de
    QGIS guardado antes con ellas. Cada lista, ordenada por fichero y capa."""

    version: str
    listed_before: tuple[QgisSublayer, ...]
    listed_after: tuple[QgisSublayer, ...]
    before: tuple[QgisLayer, ...]
    reopened: tuple[QgisLayer, ...]


def _sorted(layers: list[Any]) -> tuple[Any, ...]:
    return tuple(sorted(layers, key=lambda layer: layer.key))


def _sublayers(found: list[dict[str, Any]]) -> tuple[QgisSublayer, ...]:
    return _sorted([QgisSublayer(**item) for item in found])


def _layers(found: list[dict[str, Any]]) -> tuple[QgisLayer, ...]:
    return _sorted([QgisLayer(**{**item, "size": tuple(item["size"])}) for item in found])


def start_reopen() -> PyqgisProcess:
    """El proceso de :func:`reopen_layers`, lanzado ya (QGIS tarda ≈ 1 s en arrancar) para
    pasárselo después con ``started``; con ``with``, se termina si no se llegó a usar."""
    return PyqgisProcess(REOPEN_SCRIPT)


def reopen_layers(before: Path, after: Path, files: list[str], *,
                  started: PyqgisProcess | None = None) -> ReopenOutcome:
    """Con PyQGIS sin interfaz (:func:`run_pyqgis`, o ``started``, de :func:`start_reopen`),
    en un solo proceso: lista las capas de cada fichero ``files`` (rutas relativas con «/») de
    la carpeta ``before`` y abre todas menos las tablas internas (:data:`INTERNAL_PREFIX`); las
    guarda en un proyecto de QGIS con rutas relativas (``before/`` :data:`QGZ_NAME`), que copia
    a ``after``; lista las capas de los mismos ficheros en ``after`` y abre allí el proyecto
    copiado. ``before`` y ``after`` son copias de un proyecto (QGIS puede escribir en lo que
    abre: ``docs/trampas.md`` §6), y ``after`` aún no tiene el proyecto de QGIS.
    :class:`RuntimeError` si el proceso no termina bien o no se escribe o no se lee el proyecto
    de QGIS."""
    if (Path(after) / QGZ_NAME).exists():
        raise ValueError(f"«{after}» ya tiene un {QGZ_NAME}")
    args = (str(before), str(after), json.dumps(list(files)), QGZ_NAME, INTERNAL_PREFIX)
    result = (run_pyqgis(REOPEN_SCRIPT, *args) if started is None
              else started.finish(*args))
    if result.returncode != 0:
        raise RuntimeError(f"PyQGIS no abrió las capas: {output_of(result)}")
    found = json.loads(result.stdout.strip().splitlines()[-1])
    if not (found["written"] and found["read"]):
        raise RuntimeError(f"PyQGIS no escribió o no leyó {QGZ_NAME}: {output_of(result)}")
    return ReopenOutcome(found["qgis"], _sublayers(found["listed_before"]),
                         _sublayers(found["listed_after"]), _layers(found["before"]),
                         _layers(found["reopened"]))
