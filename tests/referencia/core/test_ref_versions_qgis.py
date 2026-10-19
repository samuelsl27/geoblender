# SPDX-License-Identifier: GPL-3.0-or-later
"""QGIS sigue abriendo todas las capas del proyecto al declarar VIGENTE otra versión (spec 009,
T27; CE-009-01; RF-009-02; plan 009 §7.1, ``tests/referencia/core``; ADR-0013 y ADR-0026;
Silvestre, error 24: renombrar la carpeta de una versión rompió 211 capas de QGIS).

Caso de referencia: el proyecto de la demostración de versiones
(``tests.support.versions_fixtures``) con dos versiones **congeladas de verdad**
(``core.versions.freeze.freeze_steps``): V01, VIGENTE, con V01.r1 (el hueco: su rejilla GeoTIFF,
su malla npz y la tabla de sus bancos; su volumen; y las rampas dibujadas a mano, una capa de
líneas) y V02, en BORRADOR, con V02.r1 (otro hueco, con 20 m de berma, y su volumen). Se declara
VIGENTE V02 como lo hace la orden (``core.versions.store.set_status`` en una transacción y la
cabecera): V01 pasa a SUPERADO y su r2 se cierra.

La referencia externa es QGIS 4.2 (``GEOBLENDER_QGIS_DIR``): PyQGIS sin interfaz, con su GDAL y
un perfil temporal (``tests.support.qgis.reopen_layers``), sobre dos copias del proyecto, la de
antes y la de después del cambio (QGIS puede pasar a WAL lo que abre: ``docs/trampas.md`` §6),
nunca sobre el proyecto:

- las capas que QGIS lista en ``project.gpkg`` y en cada GeoPackage y GeoTIFF del proyecto
  (los de ``snapshots/`` y los de ``rasters/``) son las mismas antes y después, con las mismas
  rutas, y QGIS las abre todas, con su contenido; entre ellas, todo lo congelado que QGIS lee
  (cada tabla y capa del GeoPackage de cada revisión y cada rejilla copiada). Las tablas
  internas de la base (``gb_…``, fuera de ``gpkg_contents``) QGIS las lista, pero no las abre;
  solo se comprueba que son las mismas;
- un proyecto de QGIS guardado antes con todas ellas (rutas relativas) abre después todas sus
  capas, en las mismas rutas y con el mismo contenido;
- ningún fichero del proyecto cambia salvo la base, su diario y la cabecera (nombre, tamaño,
  huella y fecha), ni ninguna ruta guardada en la base (la carpeta de cada revisión, lo
  congelado y la ubicación de cada dato).

Sin QGIS (sin la variable, o sin su GDAL) la clase se omite con «[ENTORNO] qgis», que
``tools/check.py`` cuenta como «VERDE CON OMISIONES»; la spec 009 no se cierra sin una
ejecución con QGIS anotada en su T27.
"""

from __future__ import annotations

import shutil
import sqlite3
import unittest
from pathlib import Path
from typing import Any

from tests.support import qgis
from tests.support import versions_demo as vdemo
from tests.support import versions_fixtures as fixtures
from tests.support.core_fixtures import FakeClock, project_tmp
from tests.support.demo_project import process_state
from tests.support.package import import_geoblender
from tests.support.resources import requires

freeze = import_geoblender("core.versions.freeze")
versions_read = import_geoblender("core.versions.read")
versions_store = import_geoblender("core.versions.store")
open_mod = import_geoblender("core.project.open")
userdata_mod = import_geoblender("core.userdata")

QGIS_SUFFIXES = (".gpkg", ".tif")
"""Lo que QGIS abre del proyecto: los GeoPackage y los GeoTIFF (las mallas npz, no)."""
SKIPPED = ("cache", "project.gpkg-journal", ".lock")
"""Lo que no se copia para QGIS: la caché, el diario y el cerrojo de la sesión."""
STATE_REASON = "Revisión de la propiedad: se adopta la ampliación"
PIT_V02_BERM_M = 20.0
"""La berma del hueco de V02: otra rejilla que la de V01 (se copia, no se referencia)."""
STORED_PATHS = (
    "SELECT 'revision', uid, snapshot_dir, NULL FROM gb_revision",
    "SELECT 'item', revision_uid || '/' || item_kind || '/' || item_uid, snapshot_path, "
    "snapshot_layer FROM gb_revision_item",
    "SELECT 'dataset', uid, locator, NULL FROM gb_dataset",
    "SELECT 'input', input_uid || '/' || ord, path, original_path FROM gb_input_file",
)
"""Las rutas guardadas en la base: la carpeta de cada revisión, lo congelado, la ubicación de
cada dato y los ficheros de cada entrada (y su original guardado)."""


def _last(steps: Any) -> Any:
    result = None
    for step in steps:
        if step.result is not None:
            result = step.result
    return result


def _freeze(project: Any, version: str, reason: str) -> Any:
    outcome = _last(freeze.freeze_steps(project, version, reason=reason))
    if outcome is None or outcome.frozen is None:
        raise AssertionError(f"no se ha congelado {version}")
    return outcome.frozen


def _copy(root: Path, target: Path) -> Path:
    """Copia la carpeta del proyecto ``root`` en ``target`` (con su nombre y sus fechas), sin
    :data:`SKIPPED`."""
    destination = target / root.name
    shutil.copytree(root, destination, ignore=lambda folder, names: [
        name for name in names if Path(folder) == root and name in SKIPPED])
    return destination


def _qgis_files(root: Path) -> list[str]:
    """Los GeoPackage y GeoTIFF de la carpeta ``root`` (ruta relativa con «/»), en orden."""
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*")
                  if path.is_file() and path.suffix.lower() in QGIS_SUFFIXES)


def _stored_paths(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return sorted((row for sql in STORED_PATHS for row in conn.execute(sql)), key=repr)


@requires(qgis.QGIS, qgis.QGIS_HINT)
class QgisVersionsReferenceTest(unittest.TestCase):
    """El proyecto con V01 VIGENTE y V02 congelada, antes y después de declarar VIGENTE V02,
    abierto con QGIS en dos copias (véase el módulo)."""

    @classmethod
    def setUpClass(cls) -> None:
        # QGIS arranca (≈ 1 s) mientras se prepara el proyecto.
        started = cls.enterClassContext(qgis.start_reopen())
        made = fixtures.template()  # antes de mirar el proceso: la registra y la quita
        before = process_state()
        cls.addClassCleanup(cls._same_process_state, before)
        demo = cls.enterClassContext(vdemo.VersionsDemo().registered())
        tmp = cls.enterClassContext(project_tmp("gb-vq-"))
        for part in ("proyectos", "fuentes"):
            shutil.copytree(made["folder"] / part, tmp / part)
        clock = FakeClock(made["now"])
        clock.advance(minutes=1)
        project = open_mod.open_project(
            tmp / "proyectos" / made["name"], fixtures.SESSION,
            userdata_mod.UserData(tmp / "u"), clock=clock, pid_alive=fixtures.PIDS).project
        cls.addClassCleanup(project.close)
        cls.project = project
        root = cls.root = Path(project.root)

        demo.pit(project, "V01")
        demo.pit_volume(project, "V01")
        demo.sketch(project, "V01")
        clock.advance(minutes=1)
        cls.v01_r1 = _freeze(project, "V01", "Entrega a la propiedad")
        cls.set_status("V01", "VIGENTE", None)
        clock.advance(minutes=1)
        demo.pit(project, "V02", berm_m=PIT_V02_BERM_M)
        demo.pit_volume(project, "V02")
        clock.advance(minutes=1)
        cls.v02_r1 = _freeze(project, "V02", "Ampliación al sur")
        clock.advance(minutes=1)

        cls.files_before = fixtures.files(root)
        cls.paths_before = cls.read(_stored_paths)
        cls.states_before = cls.read(cls._states)
        cls.before = _copy(root, tmp / "antes")
        cls.change = cls.set_status("V02", "VIGENTE", STATE_REASON)
        cls.files_after = fixtures.files(root)
        cls.paths_after = cls.read(_stored_paths)
        cls.states_after = cls.read(cls._states)
        cls.after = _copy(root, tmp / "despues")

        cls.qgis_files = _qgis_files(cls.before)
        cls.qgis_files_after = _qgis_files(cls.after)
        cls.frozen = cls.read(lambda conn: conn.execute(
            "SELECT snapshot_path, snapshot_layer FROM gb_revision_item WHERE copied = 1 "
            "ORDER BY fid").fetchall())
        cls.outcome = qgis.reopen_layers(cls.before, cls.after, cls.qgis_files,
                                         started=started)

    @classmethod
    def _same_process_state(cls, before: Any) -> None:
        if process_state() != before:
            raise AssertionError("la demostración no dejó el proceso como estaba")

    @classmethod
    def read(cls, work: Any) -> Any:
        with cls.project.read() as conn:
            return work(conn)

    @classmethod
    def set_status(cls, code: str, target: str, reason: str | None) -> Any:
        """Cambia el estado de la versión ``code`` como la orden: la transacción y la
        cabecera."""
        uid = cls.read(lambda conn: versions_read.version(conn, code)).uid
        with cls.project.write_transaction() as conn:
            change = versions_store.set_status(conn, cls.project, uid, target, reason=reason)
        cls.project.refresh_header()
        return change

    @staticmethod
    def _states(conn: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
        """El estado de cada versión y el de cada una de sus revisiones."""
        return {version.code: (str(version.status), *(
            f"r{revision.number}:{revision.state}"
            for revision in versions_read.revisions(conn, version.uid)))
            for version in versions_read.versions(conn)}

    def test_el_estado_cambia(self) -> None:
        """RF-009-02, RF-009-03 (CE-009-01): el cambio de la prueba es el de E1: V02 pasa a
        VIGENTE y V01, a SUPERADO, con su r2 cerrada; las revisiones congeladas siguen
        congeladas."""
        self.assertEqual(self.states_before, {"V01": ("VIGENTE", "r1:frozen", "r2:open"),
                                              "V02": ("BORRADOR", "r1:frozen", "r2:open")})
        self.assertEqual(self.states_after, {"V01": ("SUPERADO", "r1:frozen", "r2:closed"),
                                             "V02": ("VIGENTE", "r1:frozen", "r2:open")})
        self.assertEqual(self.change.superseded.code, "V01")

    def test_ningun_fichero_ni_ruta_cambia(self) -> None:
        """RF-009-02 (CE-009-01; Silvestre, error 24): declarar VIGENTE V02 no crea, cambia,
        mueve, renombra ni borra ningún fichero del proyecto salvo la base, su diario y la
        cabecera (mismo nombre, tamaño, huella y fecha), ni cambia ninguna ruta guardada en la
        base: la carpeta de cada revisión, lo congelado y la ubicación de cada dato."""
        self.assertEqual(self.files_after, self.files_before)
        self.assertEqual(self.paths_after, self.paths_before)
        self.assertEqual(self.qgis_files_after, self.qgis_files)

    def test_qgis_encuentra_las_mismas_capas(self) -> None:
        """RF-009-02 (CE-009-01, con QGIS 4.2): las capas que QGIS lista en ``project.gpkg`` y
        en cada GeoPackage y GeoTIFF del proyecto son las mismas antes y después de declarar
        VIGENTE V02, en los mismos ficheros y con el mismo tipo y la misma geometría; y antes
        las abre todas, salvo las tablas internas de la base (fuera de ``gpkg_contents``: QGIS
        las lista, pero no las abre), con su contenido."""
        listed, opened = self.outcome.listed_before, self.outcome.before
        self.assertEqual(self.outcome.listed_after, listed, self.outcome.version)
        self.assertEqual(sorted({layer.path for layer in listed}), self.qgis_files)
        self.assertEqual({layer.path for layer in listed if layer.internal}, {"project.gpkg"})
        self.assertEqual([layer.listing for layer in opened],
                         [layer for layer in listed if not layer.internal])
        self.assertEqual([layer.key for layer in opened if not layer.valid], [])
        self.assertEqual([layer.key for layer in opened if min(layer.size) < 1], [])
        self.assertGreaterEqual(len(opened), 16)

    def test_qgis_abre_todo_lo_congelado(self) -> None:
        """RF-009-02, RF-009-07 (CE-009-01; ADR-0026: las instantáneas, en formatos que QGIS
        lee): entre las capas que QGIS abre están, en su ruta, todas las copias de V01.r1 y
        V02.r1 que lee QGIS (cada tabla y capa del GeoPackage de la revisión y cada rejilla
        GeoTIFF), con su contenido, y las rampas dibujadas, como líneas."""
        expected = sorted((path, layer or "") for path, layer in self.frozen
                          if Path(path).suffix.lower() in QGIS_SUFFIXES)
        self.assertIn(("snapshots/V01.r1/rasters/demo_pit_grid_v01.tif", ""), expected)
        self.assertIn(("snapshots/V02.r1/rasters/demo_pit_grid_v02.tif", ""), expected)
        found = {layer.key: layer for layer in self.outcome.before}
        self.assertEqual([item for item in expected if item not in found], [])
        self.assertEqual([item for item in expected if not found[item].valid], [])
        sketch = f"{vdemo.SKETCH_LAYER}_v01"
        self.assertEqual([(layer.kind, layer.geometry, layer.size) for layer in (
            found[("snapshots/V01.r1/V01.r1.gpkg", sketch)], found[("project.gpkg", sketch)])],
            [("vector", "LineString", (len(vdemo.DEFAULT_RAMPS),))] * 2)

    def test_el_proyecto_de_qgis_abre_todas_sus_capas(self) -> None:
        """RF-009-02 (CE-009-01; Silvestre, error 24): un proyecto de QGIS guardado antes del
        cambio con todas las capas que QGIS abre del proyecto (rutas relativas) abre después,
        en la copia de después, todas sus capas, en las mismas rutas, con el mismo tipo y el
        mismo contenido."""
        reopened, opened = self.outcome.reopened, self.outcome.before
        self.assertEqual([layer.key for layer in reopened if not layer.valid], [])
        self.assertEqual(reopened, opened)




if __name__ == "__main__":
    unittest.main()
