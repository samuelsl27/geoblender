# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos de prueba de la vista (spec 010, T02; plan 010 §5.1 y §7.1).

Un proyecto sintético pequeño para las pruebas de la marca en vivo, de Refrescar y de los
paneles de la 010 (:class:`ViewsProject`): ventana de :data:`SIZE_M` × :data:`SIZE_M` m desde
(:data:`WEST`; :data:`SOUTH`) con paso de :data:`STEP_M` m (EPSG:25830 + EPSG:5782, los de
``tests.support.core_fixtures``) y, en ella, :data:`GRIDS` rejillas del proyecto (``gis_dtm_``)
de :data:`GRID_CELLS` × :data:`GRID_CELLS` celdas, cada una en su sitio de la ventana y con
otras cotas, escritas como las deja «Rejilla del proyecto desde un MDT» (``gis.resample``):
``core.provenance.operations.begin_operation`` y ``gis.store.ResultWriter`` (como
``tests/rendimiento/blender/perf_gis.py``), con la procedencia de la 008. La operación de la
primera lee el parámetro de resultado de la 006 :data:`STALE_PARAM`; las demás, ninguno.

Las ayudas hacen lo que hacen las órdenes, sin interfaz:

- **leer** (no escriben: no cambian el contador de cambios de la cabecera de ``project.gpkg``,
  :meth:`~ViewsProject.change_counter`): el registro de un dato (:meth:`~ViewsProject.record`,
  por uid o por el nombre de uno vivo), si está obsoleto (``gb_stale``,
  :meth:`~ViewsProject.stale`), su sucesor (``core.datasets.successor``) y el estado de una
  entrada (:meth:`~ViewsProject.input_status`);
- **cargar** en la escena con ``bl.scene.views.load_datasets`` (:meth:`~ViewsProject.load`) y
  ver lo cargado (:func:`loaded`, :func:`objects_of`);
- **cambiar el proyecto**: recalcular una rejilla con otros valores (el mismo dato con otro
  hash, :meth:`~ViewsProject.recompute`), dejarla obsoleta cambiando :data:`STALE_PARAM`
  (:meth:`~ViewsProject.make_stale`), importar un MDT de un GeoTIFF de fuera del proyecto
  (``gis.import_dtm``, lo importado ``gis_src_``: :meth:`~ViewsProject.import_grid`), sustituir
  su entrada por otra con otros valores (lo importado de la anterior queda «sustituido» y su
  sucesor es lo de la nueva, RF-008-11: :meth:`~ViewsProject.substitute`), descartar una entrada
  (lo suyo, «descartado», RF-008-55: :meth:`~ViewsProject.discard`) y borrar el fichero de un
  dato («falta» tras la comprobación de los datos de la 008, RF-008-57:
  :meth:`~ViewsProject.delete_file`);
- **la escena del usuario**: objetos suyos sueltos y en la colección «99 Trabajo», sin dato del
  proyecto (:func:`user_objects`).

Solo dentro de Blender (``tests/blender/``, ``tests/rendimiento/blender/``), con la extensión
habilitada: usa los módulos de la copia que importó Blender (:func:`extension`, por
``tests.support.blender_ext.module_name``), los mismos que registran sus operaciones, sus
lectores y sus cargadores (con ``tests.support.package.import_geoblender`` sería otra copia del
paquete, sin ellos). No importa los módulos de Blender (ARQ-01): lo que toca la escena recibe
``bpy.context`` o ``bpy.data`` de la prueba. Los datos son sintéticos; las fuentes de las
importaciones se escriben en ``fuentes/``, junto a la carpeta del proyecto, dentro de la
carpeta temporal de la prueba.
"""

from __future__ import annotations

import importlib
from collections.abc import Collection
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values

WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 200.0
STEP_M = 1.0
WINDOW: tuple[float, float, float, float] = (WEST, SOUTH, WEST + SIZE_M, SOUTH + SIZE_M)
"""La ventana de trabajo del proyecto (xmin, ymin, xmax, ymax), en m."""
GRID_CELLS = 10
"""Celdas de cada rejilla por lado (de :data:`STEP_M` m)."""
SLOTS = int(SIZE_M // (GRID_CELLS * STEP_M))
"""Rejillas por fila de la ventana (y filas): caben ``SLOTS ** 2``, sin solaparse."""
GRIDS = 3
"""Las rejillas del proyecto por defecto."""
STALE_PARAM = "gis.resample.min_valid_fraction"
"""El parámetro de resultado de la 006 que lee la operación de las rejillas elegidas."""
STALE_STEP = 0.05
"""Lo que baja :data:`STALE_PARAM` cada vez que se cambia (empieza en 1)."""
SHIFT_M = 1.0
"""Lo que suben las cotas al recalcular una rejilla o al sustituir una entrada."""
WORK_COLLECTION = "99 Trabajo"
"""La colección de trabajo del usuario (spec 010 §8: Refrescar no la toca)."""
REASON = "Datos de la prueba de la vista"
"""El motivo de lo que lo pide (sustituir y descartar una entrada, cambiar un parámetro)."""


def extension(name: str) -> ModuleType:
    """El módulo ``name`` (``"gis.store"``) de la copia de la extensión que importó Blender."""
    return importlib.import_module(f"{module_name()}.{name}")


def change_counter(project: Any) -> int:
    """El contador de cambios de la cabecera de ``project.gpkg`` (bytes 24 a 27): lo sube cada
    transacción que escribe; leer no lo cambia."""
    return int(extension("core.gpkg.header").read_header(project.database_path).change_counter)


class ViewsProject:
    """El proyecto sintético de la vista, creado en ``folder/proyectos`` (las fuentes de sus
    importaciones, en ``folder/fuentes``) con ``grids`` rejillas (``gis_dtm_rejilla_01``…, en
    :attr:`names`); las operaciones de las de los índices ``param_readers`` leen
    :data:`STALE_PARAM`. Con ``one_operation`` (spec 010, T08: para medir con muchas, unas 2,5
    veces más rápido), todas las escribe una sola operación, que lee :data:`STALE_PARAM` si
    ``param_readers`` no está vacío (todas quedan obsoletas a la vez) y que no se recalculan una
    a una. Queda abierto en escritura (no en la sesión: :meth:`attach`)."""

    def __init__(self, folder: Path, *, grids: int = GRIDS,
                 param_readers: Collection[int] = (0,), one_operation: bool = False) -> None:
        if not 0 < grids <= SLOTS * SLOTS:
            raise ValueError(f"caben de 1 a {SLOTS * SLOTS} rejillas en la ventana, no {grids}")
        self._prov = extension("gis.provenance")
        self._store = extension("gis.store")
        self._ops = extension("core.provenance.operations")
        self._registry = extension("core.datasets.registry")
        self._inputs = extension("core.inputs")
        self._session = extension("bl.scene.project_session")
        folder = Path(folder)
        parent = folder / "proyectos"
        parent.mkdir()
        self.sources = folder / "fuentes"
        self.sources.mkdir()
        settings = extension("core.project").ProjectSettings(
            **settings_values(window=WINDOW, grid_step_m=STEP_M))
        self.project: Any = extension("core.project").create_project(
            parent, settings, self._session.session(), self._session.userdata()).project
        self.root = Path(self.project.root)
        self.crs, self.vertical = self._store.project_references(self.project)
        self._slot = 0
        self._files = 0
        self._rasters: dict[str, Any] = {}  # por nombre de dato: lo último que se escribió
        self._labels: dict[str, str] = {}  # por nombre de dato: el nombre de su orden
        self._readers: set[str] = set()  # los datos cuya operación lee STALE_PARAM
        self._entries: dict[str, str] = {}  # por nombre de la importación: su entrada activa
        self._shared: set[str] = set()  # las rejillas de una operación de varias
        names = []
        batch: list[tuple[str, str, Any]] = []
        for index in range(grids):
            label = f"Rejilla {index + 1:02d}"
            name = self._prov.dataset_name(self._prov.PROJECT_GRID, label)
            if index in param_readers or (one_operation and param_readers):
                self._readers.add(name)
            batch.append((label, name, self._raster(self._next_slot())))
            if not one_operation:
                self._write_grids(batch)
                batch = []
            names.append(name)
        if batch:
            self._write_grids(batch)
            self._shared.update(name for _label, name, _raster in batch)
        self.names: tuple[str, ...] = tuple(names)
        """Los nombres de las rejillas del proyecto (``gis_dtm_``), en su orden."""

    # --- Sesión ------------------------------------------------------------------------------

    def attach(self) -> None:
        """Deja el proyecto como el de la sesión (``bl.scene.project_session.attach``)."""
        self._session.attach(self.project)
        self._session.take_notices()

    def close(self) -> None:
        """Cierra el proyecto (el de la sesión, con ella); cerrarlo otra vez no hace nada."""
        if self._session.current() is self.project:
            self._session.close()
        else:
            self.project.close()

    # --- Leer ----------------------------------------------------------------------------------

    def change_counter(self) -> int:
        """El contador de cambios de la cabecera del proyecto (:func:`change_counter`)."""
        return change_counter(self.project)

    def record(self, ref: str) -> Any:
        """El registro (``DatasetRecord``) del dato con el uid ``ref`` o, si no lo hay, del
        dato vivo con ese nombre. ``LookupError`` si no hay ninguno."""
        with self.project.read() as conn:
            found = self._registry.get(conn, ref)
        if found is None:
            raise LookupError(f"no hay ningún dato «{ref}» en el proyecto")
        return found

    def stale(self, ref: str) -> bool:
        """Si el dato ``ref`` está obsoleto (la caché ``gb_stale`` de la 008)."""
        uid = self.record(ref).uid
        with self.project.read() as conn:
            found = conn.execute("SELECT 1 FROM gb_stale WHERE item_kind = 'dataset' AND "
                                 "item_uid = ? LIMIT 1", (uid,)).fetchone()
        return found is not None

    def successor(self, ref: str) -> Any:
        """El dato vivo que sigue a ``ref`` (``core.datasets.successor``): él mismo si está
        vivo, lo que lo sustituye o ``None`` si se descartó."""
        uid = self.record(ref).uid
        with self.project.read() as conn:
            return self._registry.successor(conn, uid)

    def input_status(self, input_uid: str) -> str:
        """El estado de la entrada ``input_uid`` (``gb_input.status``: «current»…)."""
        with self.project.read() as conn:
            found = self._inputs.get(conn, input_uid)
        if found is None:
            raise LookupError(f"no hay ninguna entrada «{input_uid}» en el proyecto")
        return str(found.status)

    # --- La vista ----------------------------------------------------------------------------

    def load(self, context: Any, *refs: str, lod: int = 0) -> Any:
        """Carga de una vez en la escena de ``context`` (``bpy.context``) los datos ``refs``
        (uids o nombres; sin ninguno, las rejillas de :attr:`names`) con
        ``bl.scene.views.load_datasets``; su ``LoadOutcome``. No escribe en el proyecto."""
        views = extension("bl.scene.views")
        return views.load_datasets(context, self.project, refs or self.names, lod=lod)

    # --- Cambiar el proyecto ----------------------------------------------------------------

    def recompute(self, ref: str, *, shift_m: float = SHIFT_M) -> Any:
        """Recalcula la rejilla ``ref`` con sus cotas ``shift_m`` más arriba, en una operación
        que sustituye a la que la escribió (como «Recalcular»): el mismo dato con otro hash.
        Devuelve su registro."""
        record = self.record(ref)
        if record.name not in self._labels or record.input_uid is not None:
            raise ValueError(f"«{record.name}» no es una rejilla calculada de la prueba")
        if record.name in self._shared:
            raise ValueError(f"«{record.name}» la escribió una operación de varias "
                             "(one_operation): no se recalcula sola")
        raster = self._shifted(record.name, shift_m)
        self._write_grids([(self._labels[record.name], record.name, raster)],
                          supersedes=record.operation_uid)
        return self.record(record.uid)

    def derive(self, ref: str, label: str) -> Any:
        """Una rejilla del proyecto nueva (``gis_dtm_<label>``, en el siguiente sitio libre)
        calculada del dato ``ref`` (spec 010, T14): su operación ``gis.resample`` consume ``ref``
        (papel ``source``, como «Rejilla del proyecto desde un MDT») y lee :data:`STALE_PARAM`,
        así que es un derivado de ``ref`` que :meth:`make_stale` deja obsoleto. Devuelve su
        registro."""
        source = self.record(ref)
        name = self._prov.dataset_name(self._prov.PROJECT_GRID, label)
        self._readers.add(name)
        use = self._ops.Use(source.uid, "source")
        self._write_grids([(label, name, self._raster(self._next_slot()))], inputs=(use,))
        return self.record(name)

    def make_stale(self) -> tuple[str, ...]:
        """Cambia :data:`STALE_PARAM` (:data:`STALE_STEP` menos), con su motivo: queda
        obsoleto lo que lo leyó. Devuelve las rejillas de :attr:`names` obsoletas."""
        params = extension("core.params")
        store = params.ParameterStore(self.project)
        current = store.get(STALE_PARAM)
        if current is None:
            raise ValueError(f"ninguna operación de la prueba leyó «{STALE_PARAM}»")
        value = round(float(current.value) - STALE_STEP, 6)
        with self.project.write_transaction() as conn:
            store.change(conn, STALE_PARAM, value=value, kind="ADOPTADO",
                         source="Prueba de la vista", source_kind="document",
                         decided_by="la prueba", reason=REASON)
        with self.project.read() as conn:  # una lectura para todas (T08: con 200)
            stale = {row[0] for row in conn.execute(
                "SELECT item_uid FROM gb_stale WHERE item_kind = 'dataset'")}
            return tuple(name for name in self.names
                         if self._registry.get(conn, name).uid in stale)

    def import_grid(self, label: str) -> Any:
        """Importa como MDT (``gis.import_dtm``) un GeoTIFF nuevo de ``fuentes/`` con una
        rejilla en el siguiente sitio libre de la ventana, en el CRS del proyecto, como la
        entrada ``label``. Devuelve el registro de lo importado (``gis_src_<label>``)."""
        if label in self._entries:
            raise ValueError(f"la entrada «{label}» ya se importó: sustitúyala")
        return self._import(label, self._raster(self._next_slot()))

    def substitute(self, label: str, *, shift_m: float = SHIFT_M) -> tuple[Any, Any]:
        """Sustituye la entrada ``label`` por otro GeoTIFF con las cotas ``shift_m`` más
        arriba (como «Actualizar la entrada», con su motivo; RF-008-11). Devuelve los
        registros de lo importado de la anterior, ya «sustituido», y de la nueva."""
        name = self._prov.dataset_name(self._prov.SOURCE_GRID, label)
        old = self.record(name)
        with self.project.read() as conn:
            previous = self._inputs.get(conn, self._entries[label])
        new = self._import(label, self._shifted(name, shift_m), previous=previous)
        return self.record(old.uid), new

    def discard(self, label: str) -> Any:
        """Descarta la entrada ``label`` con su motivo (RF-008-55, ``core.inputs.discard``).
        Devuelve el registro de lo importado de ella, ya «descartado»."""
        uid = self.record(self._prov.dataset_name(self._prov.SOURCE_GRID, label)).uid
        with self.project.write_transaction() as conn:
            self._inputs.discard(conn, self.project, self._entries.pop(label), REASON)
        return self.record(uid)

    def delete_file(self, ref: str) -> Any:
        """Borra el fichero del dato ``ref`` y pasa la comprobación de los datos de la 008
        (``core.datasets.external.external_check_steps``, la de la apertura), que lo marca
        «falta» (RF-008-57). Devuelve su registro."""
        record = self.record(ref)
        Path(self.root, *record.locator.split("/")).unlink()
        for _step in extension("core.datasets.external").external_check_steps(self.project):
            pass
        return self.record(record.uid)

    # --- Por dentro ------------------------------------------------------------------------

    def _next_slot(self) -> int:
        slot = self._slot
        if slot >= SLOTS * SLOTS:
            raise ValueError(f"no caben más de {SLOTS * SLOTS} rejillas en la ventana")
        self._slot += 1
        return slot

    def _raster(self, slot: int) -> Any:
        """La rejilla del sitio ``slot`` de la ventana (de oeste a este y de norte a sur),
        con cotas en pendiente y distintas en cada sitio (otro hash)."""
        column, row = slot % SLOTS, slot // SLOTS
        side = GRID_CELLS * STEP_M
        grid = extension("gis.grid").Grid(WEST + column * side, SOUTH + SIZE_M - row * side,
                                          STEP_M, STEP_M, GRID_CELLS, GRID_CELLS)
        rows, columns = np.mgrid[0:GRID_CELLS, 0:GRID_CELLS]
        values = 100.0 + 0.5 * columns - 0.25 * rows + float(slot)
        return extension("gis.raster").Raster(grid, values.astype(np.float64), self.crs,
                                              self.vertical)

    def _shifted(self, name: str, shift_m: float) -> Any:
        """La última rejilla escrita de ``name`` con sus cotas ``shift_m`` más arriba."""
        raster = self._rasters[name]
        return type(raster)(raster.grid, raster.values + float(shift_m), raster.crs,
                            raster.vertical)

    def _write_grids(self, grids: list[tuple[str, str, Any]], *,
                     supersedes: str | None = None, inputs: tuple[Any, ...] = ()) -> None:
        """Las rejillas ``grids`` del proyecto (orden ``label``, dato ``name`` y ``raster`` de
        cada una) en una operación ``gis.resample`` (la de la primera orden), que consume
        ``inputs`` (``Use``) y lee :data:`STALE_PARAM` si alguna lo lee."""
        reads = any(name in self._readers for _label, name, _raster in grids)
        handle = self._ops.begin_operation(self.project, self._prov.RESAMPLE,
                                           settings={"nombre": grids[0][0]}, inputs=inputs,
                                           params=[STALE_PARAM] if reads else [],
                                           executor="blender", supersedes=supersedes)
        library, version = extension("gis.crs").crs_library()
        with self._store.ResultWriter(self.project, handle) as out:
            for label, _name, raster in grids:
                out.raster(label, raster)
            out.commit(software={library: version}, message=REASON)
        for label, name, raster in grids:
            self._rasters[name] = raster
            self._labels[name] = label

    def _source(self, label: str, raster: Any) -> Any:
        """El GeoTIFF de ``raster`` en ``fuentes/`` y su entrada ``label`` (``InputSpec``,
        con su ancla, su huella y el hash que da su lector: lo que da el trabajo)."""
        self._files += 1
        path = self.sources / f"fuente-{self._files:02d}.tif"
        extension("gis.geotiff.writer").write_geotiff(raster, path, profile="project")
        reader = extension("gis.content").GEOTIFF
        anchors = [self._inputs.locate_source(path, self.project, self._session.userdata(),
                                              role="main")]
        status = path.stat()
        prints = [self._inputs.SourcePrint(extension("core.hashing").sha256_file(path),
                                           size=status.st_size, mtime_ns=status.st_mtime_ns)]
        declarations = self._store.source_declarations(reader.id, self.crs, self.vertical)
        request = reader.request(reader.kinds[0], declarations,
                                 dict(zip(self._inputs.reader_roles(anchors), [path],
                                          strict=True)), {})
        digest = extension("core.content.readers").read_content(reader, request)
        return self._store.source_input(reader.id, label, files=anchors, file_prints=prints,
                                        digest=digest, crs=self.crs, vertical=self.vertical)

    def _import(self, label: str, raster: Any, *, previous: Any = None) -> Any:
        """``gis.import_dtm`` de ``raster`` como la entrada ``label`` (sustituyendo a
        ``previous``, si la hay); el registro de lo importado."""
        spec = self._source(label, raster)
        handle = self._ops.begin_operation(
            self.project, self._prov.IMPORT_DTM, settings={"nombre": label},
            executor="blender", supersedes=None if previous is None else previous.operation_uid)
        with self._store.ResultWriter(self.project, handle) as out:
            found = out.declare_input(spec, previous_uid=None if previous is None
                                      else previous.uid,
                                      reason=None if previous is None else REASON)
            if isinstance(found, self._inputs.Reuse):
                raise AssertionError(f"la entrada «{label}» ya estaba: no se importa otra vez")
            out.raster(label, raster, family=self._prov.SOURCE_GRID)
            out.commit(message=REASON)
            entry = out.input
        name = self._prov.dataset_name(self._prov.SOURCE_GRID, label)
        self._entries[label] = entry.uid
        self._rasters[name] = raster
        return self.record(name)


# --- La escena -----------------------------------------------------------------------------


def loaded(data: Any) -> dict[str, list[Any]]:
    """Los objetos de ``data`` (``bpy.data``) que muestran un dato de un proyecto, por el
    uid de su dato (no el ancla ni los del usuario, sin dato)."""
    found: dict[str, list[Any]] = {}
    for obj in data.objects:
        uid = obj.geoblender.dataset_uid
        if uid:
            found.setdefault(uid, []).append(obj)
    return found


def objects_of(data: Any, uid: str) -> list[Any]:
    """Los objetos de ``data`` (``bpy.data``) que muestran el dato ``uid``."""
    return loaded(data).get(uid, [])


def user_objects(data: Any, scene: Any, *, count: int = 2) -> tuple[Any, tuple[Any, ...]]:
    """Objetos del usuario en ``scene``, sin dato del proyecto: ``count`` vacíos sueltos en
    su colección («Croquis n») y ``count`` mallas de un triángulo en la colección
    :data:`WORK_COLLECTION` (la de antes, o una nueva enlazada a la escena). ``data`` es
    ``bpy.data``. Devuelve la colección y los objetos."""
    work = data.collections.get(WORK_COLLECTION)
    if work is None:
        work = data.collections.new(WORK_COLLECTION)
    if work.name not in scene.collection.children:
        scene.collection.children.link(work)
    objects: list[Any] = []
    for index in range(1, count + 1):
        loose = data.objects.new(f"Croquis {index}", None)
        scene.collection.objects.link(loose)
        mesh = data.meshes.new(f"Trabajo {index}")
        mesh.from_pydata([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [], [(0, 1, 2)])
        inner = data.objects.new(f"Trabajo {index}", mesh)
        work.objects.link(inner)
        objects.extend((loose, inner))
    return work, tuple(objects)
