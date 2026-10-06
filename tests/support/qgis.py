# SPDX-License-Identifier: GPL-3.0-or-later
"""El GDAL de QGIS para las pruebas de compatibilidad del GeoPackage (spec 002, T35; plan
002 §7: la prueba con GDAL y QGIS es opcional y se omite con ``[ENTORNO] qgis``).

QGIS llega por ``GEOBLENDER_QGIS_DIR``, la carpeta de su instalación (la que tiene
``bin\\ogrinfo.exe``); su ruta no se escribe en ningún sitio. Las órdenes se lanzan con
el entorno que prepara su ``bin\\o4w_env.bat`` (``PATH``, ``GDAL_DATA``,
``GDAL_DRIVER_PATH``, ``PROJ_DATA`` y el ``PYTHONHOME`` de su Python), sin el
``PROJ_LIB`` ni las demás variables ``PROJ_*``, ``GDAL_*``, ``PYTHON*`` y ``OSGEO4W_*``
del puesto (en el de IMGA, ``PROJ_LIB`` apunta al ``proj.db`` de PostGIS: Silvestre
TOP-05), con ``GDAL_PAM_ENABLED=NO`` (sin ``.aux.xml``) y sin escribir ``__pycache__``.
Las pruebas solo leen con GDAL: nunca escriben con él en un proyecto.

El recurso ``qgis`` (:data:`QGIS`, ``tests.support.resources``) está disponible si la
variable apunta a una carpeta con ``bin\\ogrinfo.exe`` y un Python en ``apps\\Python3*``
con ``osgeo`` y el ``validate_gpkg.py`` de ``osgeo_utils``.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

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
