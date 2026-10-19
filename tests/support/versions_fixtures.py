# SPDX-License-Identifier: GPL-3.0-or-later
"""El proyecto de la demostración de versiones, para las pruebas (spec 009, T08; plan 009 §7.1).

Un proyecto sintético en disco (esquema 3, EPSG:25830 + EPSG:5782, los ajustes de
``tests.support.core_fixtures``) con la cadena entera de la demostración de la 008 sobre
``fuentes/Limites_v1.gpkg`` (el límite importado, su área, los bancos y las marcas, los años
por banco, los acopios acoplados y el balance; ``tests.support.provenance_demo``) y las
versiones **V01** («Definitiva») y **V02** («Ampliación») en BORRADOR, cada una con su r1
abierta y sin datos. :func:`build` lo crea en una carpeta (``proyectos/``, ``fuentes/`` y los
datos de usuario ``u/``) con la demostración de versiones registrada
(:class:`~tests.support.versions_demo.VersionsDemo`) y un reloj simulado que avanza un minuto
por paso.

:class:`VersionsProjectCase` es la base de las pruebas que lo usan: se crea **una vez por
proceso** (:func:`template`) y cada prueba trabaja en su copia (``proyectos/`` y ``fuentes/``,
con sus fechas),
abierta en escritura con la misma sesión, un reloj posterior y la demostración registrada; al
terminar comprueba que el proceso queda como estaba (``process_state``). Sus ayudas hacen lo que
harán las órdenes, sin interfaz:

- leer (no mueven el contador de cambios de la base): una versión (:meth:`~VersionsProjectCase.version`),
  un dato de un ámbito (:meth:`~VersionsProjectCase.record`), consultas;
- escribir: crear una versión (:meth:`~VersionsProjectCase.new_version`, que regenera la
  cabecera), cambiar su estado (:meth:`~VersionsProjectCase.set_status`) y **congelar por SQL**
  la revisión abierta (:meth:`~VersionsProjectCase.freeze`; la congelación de verdad, con su
  instantánea, es la T13): la revisión pasa a «frozen» con una huella simulada, lo congelado va a
  ``gb_revision_item`` y se abre la siguiente;
- mirar el disco: :func:`files` (cada fichero de la carpeta del proyecto con su tamaño, su huella
  y su fecha, sin la base, su diario ni la cabecera), :func:`change_counter` (el contador de
  cambios de la cabecera de ``project.gpkg``: lo sube cada transacción que escribe) y
  :func:`alter_file` (cambia un byte de un fichero, por ejemplo de una instantánea, sin cambiar
  su tamaño ni su fecha, y devuelve cómo deshacerlo).

Solo fuera de Blender (importa ``tests.support.core_fixtures``). Datos solo sintéticos.
"""

from __future__ import annotations

import atexit
import hashlib
import math
import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from tests.support import provenance_data as data
from tests.support import versions_demo
from tests.support.core_fixtures import (
    FakeClock,
    FakePids,
    make_session,
    make_settings,
    project_tmp,
)
from tests.support.demo_project import REL_TOL, process_state
from tests.support.package import import_geoblender

create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
userdata_mod = import_geoblender("core.userdata")
header_mod = import_geoblender("core.gpkg.header")
params = import_geoblender("core.params")
registry = import_geoblender("core.datasets.registry")
dataset_model = import_geoblender("core.datasets.model")
versions_read = import_geoblender("core.versions.read")
versions_store = import_geoblender("core.versions.store")
timeutil = import_geoblender("core.timeutil")
for _name in versions_demo.MODULES:  # antes de cualquier prueba (process_state los compara)
    import_geoblender(_name)

SESSION = make_session()
"""La sesión sintética de las pruebas (equipo «PC-PRUEBA-A», usuario «prueba»)."""
USER = SESSION.user_host
PIDS = FakePids({SESSION.pid})
DATABASE = "project.gpkg"
WRITTEN: tuple[str, ...] = ("project.gpkg", "project.gpkg-journal", "manifest.json")
"""La base, su diario y la cabecera: lo que :func:`files` no lista (cambian al escribir)."""
CHAIN_STEPS: tuple[str, ...] = ("boundary", "area", "digitize", "years", "detect", "filter",
                                "balance")
"""Los pasos de la cadena de la 008, en su orden (``boundary``: la importación del límite)."""
VERSIONS: tuple[tuple[str, str], ...] = (("definitiva", "Definitiva"),
                                         ("ampliacion", "Ampliación"))
"""El rasgo y el título de V01 y de V02."""
VERSION_REASON = "Alternativa de la demostración"
SNAPSHOT_SHA256 = "a" * 64
"""La huella simulada del manifiesto de una revisión congelada por SQL."""
COPIED_PARTS: tuple[str, ...] = ("produced", "upstream")
"""Las partes de lo congelado cuyo contenido se copia a la instantánea (plan A5): lo
producido y lo derivado o editable de aguas arriba; lo inmutable y lo heredado de la padre se
referencian."""


# --- El disco ------------------------------------------------------------------------------


def files(root: Path, *, skip: Sequence[str] = WRITTEN,
          skip_dirs: Sequence[str] = ()) -> dict[str, object]:
    """Cada fichero de la carpeta del proyecto ``root`` (ruta relativa con «/» → tamaño, sha256
    y fecha en ns) y cada carpeta («carpeta»), sin ``skip`` (por defecto, la base, su diario y
    la cabecera) ni lo que hay bajo las carpetas de primer nivel ``skip_dirs`` (``"cache"``)."""
    root = Path(root)
    found: dict[str, object] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel in skip or rel.split("/")[0] in skip_dirs:
            continue
        if path.is_dir():
            found[rel] = "carpeta"
        else:
            stat = path.stat()
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1 << 20):
                    digest.update(chunk)
            found[rel] = (stat.st_size, digest.hexdigest(), stat.st_mtime_ns)
    return found


def change_counter(root: Path) -> int:
    """El contador de cambios de la cabecera de la base del proyecto ``root`` (bytes 24 a 27):
    lo sube cada transacción que escribe; leer no lo cambia."""
    return int(header_mod.read_header(Path(root) / DATABASE).change_counter)


def alter_file(path: Path, *, offset: int | None = None) -> Callable[[], None]:
    """Cambia el byte ``offset`` (por defecto, el del medio) del fichero ``path`` sin cambiar
    su tamaño ni su fecha de modificación (otra huella, lo que solo ve la comprobación
    completa); devuelve la función que lo deja como estaba (el byte y la fecha)."""
    path = Path(path)
    stat = path.stat()
    if stat.st_size == 0:
        raise ValueError(f"«{path.name}» está vacío: no hay ningún byte que cambiar")
    where = stat.st_size // 2 if offset is None else offset
    if not 0 <= where < stat.st_size:
        raise ValueError(f"«{path.name}» tiene {stat.st_size} bytes: no hay byte {where}")
    with path.open("r+b") as stream:
        stream.seek(where)
        (original,) = stream.read(1)
        stream.seek(where)
        stream.write(bytes([original ^ 0xFF]))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    def undo() -> None:
        with path.open("r+b") as stream:
            stream.seek(where)
            stream.write(bytes([original]))
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    return undo


# --- El proyecto ---------------------------------------------------------------------------


@dataclass
class VersionsProject:
    """El proyecto de :func:`build`, abierto en escritura: la carpeta (``folder``, con
    ``proyectos/``, ``fuentes/`` y ``u/``), la fuente del límite, los datos de usuario, el reloj,
    el nombre de lo importado del límite, el uid de la operación de cada paso de la cadena
    (:data:`CHAIN_STEPS`) y las versiones V01 y V02 (``Version``)."""

    project: Any
    folder: Path
    source: Path
    userdata: Any
    clock: FakeClock
    boundary: str
    chain: dict[str, str]
    v1: Any
    v2: Any


def create_version(project: Any, *, feature: str, title: str, reason: str = VERSION_REASON,
                   parent: str | None = None) -> Any:
    """Una versión nueva (``core.versions.store.create_version``) y la cabecera regenerada,
    como lo hará su orden; devuelve su ``Version``."""
    with project.write_transaction() as conn:
        version, _revision = versions_store.create_version(
            conn, project, feature=feature, title=title, reason=reason, parent=parent)
    project.refresh_header()
    return version


def freeze_rows(conn: sqlite3.Connection, version: Any, *, now: str,
                items: Sequence[tuple[Any, ...]] | None = None, reason: str = "Siguiente",
                figures: Sequence[str] | None = None, user: str = USER) -> str:
    """Congela **por SQL**, en la transacción ``conn`` y con la fecha ``now``, la revisión
    abierta de ``version`` (``Version``) y abre la siguiente con ``reason``; devuelve el uid de
    la congelada. Lo de :meth:`VersionsProjectCase.freeze` (que la usa), fuera de una prueba:
    el proyecto de D-13 con versiones de ``tests.support.versions_perf``. No escribe ningún
    fichero: solo las filas."""
    uid, number = conn.execute(
        "SELECT uid, number FROM gb_revision WHERE version_uid = ? AND state = 'open'",
        (version.uid,)).fetchone()
    label = f"{version.code}.r{number}"
    folder = f"snapshots/{label}"
    chosen = items
    if chosen is None:
        live = tuple(str(status) for status in dataset_model.LIVE_STATUSES)
        chosen = [(registry.get(conn, row[0]), "produced") for row in conn.execute(
            f"SELECT uid FROM gb_dataset WHERE version_uid = ? AND version_uid <> '' "
            f"AND status IN "
            f"({', '.join('?' for _ in live)}) ORDER BY fid", (version.uid, *live))]
    conn.execute(
        "UPDATE gb_revision SET state = 'frozen', closed_at = ?, closed_by = ?, "
        "snapshot_dir = ?, snapshot_sha256 = ?, snapshot_bytes = 0, "
        "geoblender_version = ? WHERE uid = ?",
        (now, user, folder, SNAPSHOT_SHA256, "0.1.0", uid))
    for item in chosen:
        record, part, *where = item
        copied = part in COPIED_PARTS
        if where:
            path, layer = where
        elif not copied:
            path, layer = None, None
        elif str(record.store) == "gpkg":
            path, layer = f"{folder}/{label}.gpkg", record.locator
        else:
            path, layer = f"{folder}/{record.locator}", None
        conn.execute(
            "INSERT INTO gb_revision_item (revision_uid, item_kind, item_uid, part, "
            "content_sha256, copied, snapshot_path, snapshot_layer) "
            "VALUES (?, 'dataset', ?, ?, ?, ?, ?, ?)",
            (uid, record.uid, part, record.content_sha256, int(copied), path, layer))
    chosen_figures = figures
    if chosen_figures is None:
        chosen_figures = [str(row[0]) for row in conn.execute(
            "SELECT f.uid FROM gb_revision AS r CROSS JOIN gb_operation AS op "
            "ON op.revision_uid = r.uid AND op.revision_uid <> '' "
            "CROSS JOIN gb_figure AS f ON f.operation_uid = op.uid "
            "WHERE r.version_uid = ? AND op.status = 'done' "
            "AND op.superseded_by IS NULL ORDER BY f.fid", (version.uid,))]
    conn.executemany(
        "INSERT INTO gb_revision_item (revision_uid, item_kind, item_uid, part) "
        "VALUES (?, 'figure', ?, 'produced')",
        [(uid, figure) for figure in chosen_figures])
    conn.execute(
        "INSERT INTO gb_revision (uid, version_uid, number, state, reason, created_at, "
        "created_by) VALUES (?, ?, ?, 'open', ?, ?, ?)",
        (str(uuid.uuid4()), version.uid, number + 1, reason, now, user))
    return str(uid)


def build(folder: Path, demo: versions_demo.VersionsDemo, *,
          clock: FakeClock | None = None) -> VersionsProject:
    """Crea en ``folder`` el proyecto de la demostración de versiones (véase el módulo) con
    ``demo`` ya registrada; lo deja abierto en escritura."""
    folder = Path(folder)
    parent = folder / "proyectos"
    parent.mkdir()
    sources = folder / "fuentes"
    sources.mkdir()
    source = sources / data.BOUNDARY_V1
    shutil.copyfile(data.DATA_DIR / data.BOUNDARY_V1, source)
    clock = FakeClock() if clock is None else clock
    userdata = userdata_mod.UserData(folder / "u")
    project = create.create_project(parent, make_settings(), SESSION, userdata,
                                    clock=clock).project
    try:
        chain: dict[str, str] = {}

        def step(name: str, work: Callable[[], Any]) -> Any:
            result = work()
            chain[name] = result.uid
            clock.advance(minutes=1)
            return result

        boundary = step("boundary", lambda: demo.import_boundary(project, source))
        step("area", lambda: demo.area(project, boundary.dataset.name))
        step("digitize", lambda: demo.digitize(project))
        step("years", lambda: demo.bench_years(project))
        detect, kept = demo.stockpiles(project)
        chain.update(detect=detect.uid, filter=kept.uid)
        clock.advance(minutes=1)
        step("balance", lambda: demo.balance(project))
        made = []
        for feature, title in VERSIONS:
            made.append(create_version(project, feature=feature, title=title))
            clock.advance(minutes=1)
    except BaseException:
        project.close()
        raise
    return VersionsProject(project, folder, source, userdata, clock, boundary.dataset.name,
                           chain, *made)


_TEMPLATE: dict[str, Any] = {}


def template() -> Mapping[str, Any]:
    """El proyecto de :func:`build`, creado (y cerrado) la primera vez que se pide en el
    proceso, en una carpeta temporal que se borra al salir: lo que copia cada prueba de
    :class:`VersionsProjectCase` (``folder``, ``name`` de la carpeta del proyecto, ``now`` del
    reloj al terminar, ``boundary``, ``chain`` y los uid de ``versions``). No se modifica."""
    if not _TEMPLATE:
        folder = Path(tempfile.mkdtemp(prefix="gb-vt-"))
        atexit.register(shutil.rmtree, folder, ignore_errors=True)
        with versions_demo.VersionsDemo().registered() as demo:
            built = build(folder, demo)
            built.project.close()
        _TEMPLATE.update(folder=folder, name=Path(built.project.root).name,
                         now=built.clock.now(), boundary=built.boundary,
                         chain=dict(built.chain), versions=(built.v1.uid, built.v2.uid))
    return _TEMPLATE


class VersionsProjectCase(unittest.TestCase):
    """Una copia por prueba del proyecto de :func:`build` (que se crea una vez por proceso,
    :func:`template`), abierta en escritura (``self.project``, en ``self.root``) con la
    demostración de versiones registrada (``self.demo``), el reloj ``self.clock`` (posterior al
    del proyecto), sus datos de usuario y ``self.store`` (``ParameterStore``); ``self.v1`` y
    ``self.v2`` son V01 y V02, ``self.boundary`` el nombre de lo importado del límite y
    ``self.chain`` el uid de la operación de cada paso de la cadena de la 008."""

    tmp_prefix: ClassVar[str] = "gb-vp-"
    """El prefijo de las carpetas temporales (corto: rutas de Windows)."""

    def setUp(self) -> None:
        made = template()  # antes de mirar el proceso: la registra y la quita
        before = process_state()
        self.addCleanup(lambda: self.assertEqual(process_state(), before))
        self.demo = versions_demo.VersionsDemo()
        self.enterContext(self.demo.registered())
        self.folder = self.enterContext(project_tmp(self.tmp_prefix))
        for part in ("proyectos", "fuentes"):
            shutil.copytree(made["folder"] / part, self.folder / part)
        self.source = self.folder / "fuentes" / data.BOUNDARY_V1
        self.clock = FakeClock(made["now"])
        self.clock.advance(minutes=1)
        self.userdata = userdata_mod.UserData(self.folder / "u")
        self.project = open_mod.open_project(
            self.folder / "proyectos" / made["name"], SESSION, self.userdata,
            clock=self.clock, pid_alive=PIDS).project
        self.addCleanup(self.project.close)
        self.root = Path(self.project.root)
        self.store = params.ParameterStore(self.project)
        self.boundary: str = made["boundary"]
        self.chain: dict[str, str] = dict(made["chain"])
        self.v1, self.v2 = (self.version(uid) for uid in made["versions"])

    # --- Leer -------------------------------------------------------------------------------

    def read(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        """``work`` con una conexión de lectura del proyecto."""
        with self.project.read() as conn:
            return work(conn)

    def query(self, sql: str, args: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        """Las filas de ``sql`` en una conexión de lectura."""
        with self.project.read() as conn:
            return conn.execute(sql, tuple(args)).fetchall()

    def version(self, ref: str) -> Any:
        """La versión ``ref`` (uid o código). ``LookupError`` si no la hay."""
        found = self.read(lambda conn: versions_read.version(conn, ref))
        if found is None:
            raise LookupError(f"no hay ninguna versión «{ref}» en el proyecto")
        return found

    def record(self, ref: str, version: str | None = None) -> Any:
        """El registro (``DatasetRecord``) del dato con el uid ``ref`` o, si no lo hay, del
        dato vivo con ese nombre en ``version`` (uid o código; ``None``, el proyecto).
        ``LookupError`` si no hay ninguno."""
        scope = "" if version is None else self.version(version).uid
        found = self.read(lambda conn: registry.get(conn, ref, version_uid=scope))
        if found is None:
            raise LookupError(f"no hay ningún dato «{ref}» en {version or 'el proyecto'}")
        return found

    def files(self, **kw: Any) -> dict[str, object]:
        """:func:`files` de la carpeta del proyecto."""
        return files(self.root, **kw)

    def change_counter(self) -> int:
        """:func:`change_counter` de la base del proyecto."""
        return change_counter(self.root)

    def now(self) -> str:
        """La hora del reloj simulado, como la escribe el proyecto."""
        return timeutil.format_utc(self.clock.now())

    # --- Escribir ---------------------------------------------------------------------------

    def tick(self) -> None:
        """Un minuto más en el reloj."""
        self.clock.advance(minutes=1)

    def write(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        """``work`` en una transacción de escritura del proyecto; su resultado."""
        with self.project.write_transaction() as conn:
            return work(conn)

    def new_version(self, feature: str, title: str, parent: str | None = None, *,
                    reason: str = VERSION_REASON) -> Any:
        """Una versión nueva (de ``parent``, uid o código, si se da), un minuto después."""
        self.tick()
        return create_version(self.project, feature=feature, title=title, reason=reason,
                              parent=parent)

    def set_status(self, version: Any, target: str, reason: str | None = None) -> Any:
        """Cambia el estado de ``version`` (``Version``, uid o código) a ``target``, un minuto
        después; su ``StatusChange``."""
        uid = version.uid if hasattr(version, "uid") else self.version(version).uid
        self.tick()
        return self.write(lambda conn: versions_store.set_status(conn, self.project, uid, target,
                                                                 reason=reason))

    def freeze(self, version: Any, items: Sequence[tuple[Any, ...]] | None = None, *,
               reason: str = "Siguiente", figures: Sequence[str] | None = None) -> str:
        """Congela **por SQL** la revisión abierta de ``version`` (``Version``, uid o código)
        y abre la siguiente con ``reason``; devuelve el uid de la congelada. Lo congelado
        (``gb_revision_item``): cada elemento de ``items`` es ``(registro, parte)`` o
        ``(registro, parte, snapshot_path, snapshot_layer)``; por defecto, cada dato vivo de la
        versión como ``produced``. Lo de las partes :data:`COPIED_PARTS` (``produced`` y
        ``upstream``, plan A5) queda copiado: una tabla, en el GeoPackage de la instantánea
        (``snapshots/V01.r1/V01.r1.gpkg``) con su nombre; un fichero, en la carpeta de la
        instantánea con su ruta; lo inmutable y lo heredado, sin copia. Y las cifras
        ``figures`` (uid; por defecto, las de las operaciones hechas y sin sustituir de la
        versión), como ``produced`` (T09: las vigentes de la versión, D-9). No escribe ningún
        fichero (eso lo hará la T13): solo las filas."""
        target = version if hasattr(version, "uid") else self.version(version)
        self.tick()
        now = self.now()
        return self.write(lambda conn: freeze_rows(conn, target, now=now, items=items,
                                                   reason=reason, figures=figures))

    # --- Comprobar --------------------------------------------------------------------------

    def assertClose(self, value: float, expected: float) -> None:  # noqa: N802 - unittest
        """``value`` es ``expected`` dentro de la tolerancia relativa de la demostración."""
        self.assertTrue(math.isclose(value, expected, rel_tol=REL_TOL),
                        f"{value!r} no es {expected!r} (tolerancia relativa {REL_TOL})")
