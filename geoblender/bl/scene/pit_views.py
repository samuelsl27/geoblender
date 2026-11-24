# SPDX-License-Identifier: GPL-3.0-or-later
"""El TIN y el sólido de excavación de una corta por bancos en la vista (spec 018, T30; HU-018-4; RF-018-30, RNF-018-09; plan 018 §4, §5.5; ADR-0005, ADR-0021; comprobación manual M4).

Dos vistas **regenerables** (010) de una corta calculada, a petición y **sin escribir nada** en el proyecto ni sacar de ellas ninguna cifra (la rejilla del proyecto es la superficie oficial, D-10):

- **El TIN** (:func:`load_pit_tin`, sobre ``des_pbl_<nombre>``, las polilíneas de la corta): una triangulación de Delaunay restringida con las polilíneas (pies, crestas y líneas fijadas) y la
  **línea de cielo** (``des_psk_<nombre>``) como aristas, con la cota de cada vértice. La CDT rellena la envolvente convexa; aquí solo queda **lo que encierra la línea más externa**: se quitan los
  triángulos a los que se llega desde fuera de la envolvente sin cruzar una arista obligatoria. Si la línea de cielo cruza una polilínea (dos aristas obligatorias que se cortan), el TIN se dibuja sin
  ella y lo dice. Triangula la **CDT de Blender solo para esta vista** y solo si su tiempo estimado cabe en ``gis.tin.blender_cdt_max_s`` (ADR-0021; :func:`~.triangulator.choose_triangulation`); si
  no, el ``PureTriangulator`` por pasos (cancelable), y si la CDT de Blender incumple su contrato, también el puro.
- **El sólido de excavación** (:func:`load_pit_solid`, sobre ``des_pbk_<nombre>``, las cifras por banco: es el dato de la corta que no es una polilínea): una malla **cerrada** entre la superficie
  de partida de la corta (su entrada con el papel de superficie) y la superficie que deja (``des_psf_<nombre>``), en las celdas donde la corta baja de la partida: la parte de arriba es la partida,
  la de abajo la corta y las paredes unen las dos por el borde. Va por centros de celda, como las demás mallas de superficie de la 006: su volumen no es el de corte de la rejilla (que es la cifra).

**El aviso de triángulos** (RNF-018-09) sale **antes de crear nada**: el TIN estima ``2·puntos`` triángulos (la CDT sin recortar) y el sólido cuenta los suyos (los de dos superficies y sus paredes); por
encima de ``max_triangles`` (un parámetro de la vista; :data:`MAX_TRIANGLES`, 300.000, por defecto) lanzan ``des.pit_view_large`` y no queda ninguna malla; con ``max_triangles=None`` (el sí de la persona,
que pide la orden de la fase H) se crea. :func:`tin_loader` y :func:`solid_loader` dan el cargador con otro límite.

Las mallas tienen los vértices en **locales** relativos al GeoOrigin (``bl.scene.mesh``, ADR-0005: el cálculo, en float64 y absoluto) y matriz identidad; se crean en pasos y, cerrados antes de terminar,
no dejan nada. Cargar no cambia ninguna operación.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import bpy
import numpy as np

from ...core.datasets import registry as dataset_registry
from ...core.datasets.model import DatasetRecord
from ...core.i18n import tr
from ...core.params.store import ParameterStore
from ...core.versions import read as versions_read
from ...design import pit_lines
from ...design import provenance as design_provenance
from ...design.messages import DesignError
from ...gis import cdt
from ...gis.mesh import surface_mesh_from_tin
from ...gis.messages import GisError
from ...gis.raster import Raster
from ...gis.tin import Tin, raster_to_tin_steps
from . import des_views, triangulator, views
from .gis_views import _blocks, _object, _scaled, _surface
from .mesh import mesh_steps, mesh_vertices_local

__all__ = ["MAX_TRIANGLES", "SKYLINE_FAMILY", "SOLID_FAMILY", "SOLID_LABEL", "TIN_FAMILY", "TIN_LABEL", "confirmed", "limit", "load_pit_solid", "load_pit_tin", "solid_companions", "solid_loader",
           "solid_steps", "take_large", "tin_companions", "tin_loader", "tin_steps", "unlimited"]

TIN_FAMILY = design_provenance.PIT_POLYLINES_TABLE
"""La familia de datos con la que se carga el TIN: las polilíneas de la corta (``des_pbl_``)."""
SKYLINE_FAMILY = design_provenance.PIT_SKYLINE_TABLE
"""La línea de cielo (``des_psk_``): sus aristas entran en el TIN."""
SOLID_FAMILY = design_provenance.PIT_BENCHES_TABLE
"""La familia de datos con la que se carga el sólido: las cifras por banco de la corta (``des_pbk_``)."""
TIN_LABEL = "Pit TIN"
"""El ``msgid`` del nombre del TIN en el nombre generado de su objeto."""
SOLID_LABEL = "Pit excavation solid"
"""El ``msgid`` del nombre del sólido."""
MAX_TRIANGLES = 300_000
"""El límite de triángulos de una vista antes de avisar (RNF-018-09)."""
_MILLIMETRE = 1_000.0


_STATE: dict[str, Any] = {"unlimited": False, "large": None}
"""Lo que comparten los cargadores registrados y la orden «Superficie y sólido…» (spec 018, T33): si se ha confirmado crear sin límite de triángulos y el último aviso de triángulos que dio un cargador."""


def limit() -> int | None:
    """El límite de triángulos de los cargadores registrados ahora: :data:`MAX_TRIANGLES`, o ``None`` (sin aviso) mientras dura un :func:`unlimited`. Se lee al cargar: cambiar la constante vale en la carga siguiente."""
    return None if _STATE["unlimited"] else MAX_TRIANGLES


def confirmed() -> bool:
    """Si ahora mismo se está creando una vista confirmada por encima del límite (:func:`unlimited`)."""
    return bool(_STATE["unlimited"])


@contextmanager
def unlimited() -> Iterator[None]:
    """Mientras dura, los cargadores registrados **no avisan** de los triángulos: lo que hace la orden tras confirmar el aviso (RNF-018-09). Se quita al salir, también si los pasos se cierran a mitad (Esc)."""
    _STATE["unlimited"] = True
    try:
        yield
    finally:
        _STATE["unlimited"] = False


def take_large() -> DesignError | None:
    """El último ``des.pit_view_large`` que dio un cargador registrado, **y lo olvida** (``None`` si no hubo): la orden lo pide tras una carga que no creó nada, para preguntar si se crea de todos modos."""
    found = _STATE["large"]
    _STATE["large"] = None
    return found  # type: ignore[no-any-return]


def _warned(loader: views.ViewLoader, request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """Los pasos de ``loader`` apuntando el aviso de triángulos que dé (:func:`take_large`)."""
    try:
        return (yield from loader(request))
    except DesignError as error:
        if error.code == "des.pit_view_large":
            _STATE["large"] = error
        raise


def _suffix(name: str, family: str) -> str:
    """El nombre de la corta de un dato ``name`` de la familia ``family`` (``des_pbl_<nombre>``)."""
    return name.removeprefix(des_views.prefix(family))


def _named(family: str, suffix: str) -> str:
    return des_views.prefix(family) + suffix


def _large(pit: str, what: str, triangles: int, limit: int) -> DesignError:
    """``des.pit_view_large``; ``what`` es el nombre de la vista, ya en el idioma de quien llama."""
    return DesignError("des.pit_view_large", obj=f"Corta «{pit}»", field="triángulos", value=triangles, name=pit, what=what, limit=limit)


def _empty(pit: str, what: str, reason: str) -> DesignError:
    """``des.pit_view_empty``; ``what`` y ``reason`` llegan ya en el idioma de quien llama."""
    return DesignError("des.pit_view_empty", obj=f"Corta «{pit}»", field=what, value=0, name=pit, what=what, reason=reason)


# --- El TIN ------------------------------------------------------------------------------------------------------------------


def _edges_and_points(lines: Sequence[tuple[np.ndarray, bool]], origin_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Los puntos (sin repetir, al milímetro; la cota del primero de cada grupo, en el orden en que llegan), sus coordenadas locales en planta y las aristas obligatorias de ``lines``
    (cada una ``(puntos (n, 3), cerrada)``; una cerrada que repite su primer vértice al final lo quita)."""
    points: list[np.ndarray] = []
    spans: list[tuple[int, int, bool]] = []
    start = 0
    for found, closed in lines:
        array = np.asarray(found, dtype=np.float64).reshape(-1, 3)
        if closed and len(array) > 1 and np.array_equal(array[0], array[-1]):
            array = array[:-1]
        points.append(array)
        spans.append((start, start + len(array), bool(closed)))
        start += len(array)
    stacked = np.vstack(points)
    keys = np.rint((stacked[:, :2] - origin_xy) * _MILLIMETRE).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    inverse = np.asarray(inverse).reshape(-1)
    rank = np.empty(len(first), dtype=np.int64)
    rank[np.argsort(first, kind="stable")] = np.arange(len(first))
    remap = rank[inverse]
    pieces = []
    for low, high, closed in spans:
        ids = remap[low:high]
        pairs = np.column_stack([ids[:-1], ids[1:]]) if len(ids) > 1 else np.empty((0, 2), dtype=np.int64)
        if closed and len(ids) > 2:
            pairs = np.vstack([pairs, [[ids[-1], ids[0]]]])
        pieces.append(pairs)
    edges = np.vstack(pieces) if pieces else np.empty((0, 2), dtype=np.int64)
    edges = edges[edges[:, 0] != edges[:, 1]]
    edges = np.unique(np.sort(edges, axis=1), axis=0).astype(np.int32)
    order = np.sort(first)
    return stacked[order], stacked[order][:, :2] - origin_xy, edges


def _inside_faces(faces: np.ndarray, edges: np.ndarray, count: int) -> np.ndarray:
    """Las caras de ``faces`` que **no** son de fuera: a las de fuera se llega desde la envolvente convexa sin cruzar una arista obligatoria de ``edges`` (``count`` puntos)."""
    sides = np.stack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=1).astype(np.int64)  # (m, 3, 2)
    keys = (np.minimum(sides[..., 0], sides[..., 1]) * count + np.maximum(sides[..., 0], sides[..., 1])).ravel()
    unique, inverse, times = np.unique(keys, return_inverse=True, return_counts=True)
    inverse = np.asarray(inverse).reshape(-1)
    held = np.isin(unique, edges[:, 0].astype(np.int64) * count + edges[:, 1].astype(np.int64))
    owner = np.repeat(np.arange(len(faces)), 3)
    hull_face = owner[(times[inverse] == 1) & ~held[inverse]]
    order = np.argsort(inverse, kind="stable")
    shared = np.flatnonzero((times == 2) & ~held)
    first_pos = np.searchsorted(inverse[order], shared)
    a, b = owner[order[first_pos]], owner[order[first_pos + 1]]
    both = np.concatenate([a, b]), np.concatenate([b, a])
    sort = np.argsort(both[0], kind="stable")
    neighbours = both[1][sort].tolist()
    starts = np.searchsorted(both[0][sort], np.arange(len(faces) + 1)).tolist()
    outside = np.zeros(len(faces), dtype=bool)
    outside[hull_face] = True
    queue = deque(np.unique(hull_face).tolist())
    while queue:
        current = queue.popleft()
        for other in neighbours[starts[current]:starts[current + 1]]:
            if not outside[other]:
                outside[other] = True
                queue.append(other)
    return ~outside


def _triangulate(request: Any, xy_local: np.ndarray, edges: np.ndarray, limit_s: float | None) -> Generator[float, None, tuple[np.ndarray, str]]:
    """Los triángulos de ``xy_local`` con ``edges`` y el nombre de quien los hizo: la CDT de Blender si cabe en el tiempo (ADR-0021) y, si no o si incumple su contrato, la pura por pasos."""
    choice = triangulator.choose_triangulation(len(xy_local), limit_s=limit_s)
    if choice.in_process:
        try:
            native = triangulator.BlenderTriangulator()
            return native.triangulate(xy_local, edges), native.name
        except cdt.TriangulatorError as error:
            if error.code != "gis.triangulation_contract":
                raise
    pure = cdt.PureTriangulator()
    work = pure.triangulate_steps(xy_local, edges)
    try:
        while True:
            try:
                next(work)
            except StopIteration as done:
                return np.asarray(done.value), pure.name
            yield 0.3
    finally:
        work.close()


def tin_steps(request: Any, lines: Sequence[tuple[np.ndarray, bool]], skyline: Sequence[tuple[np.ndarray, bool]] = (), *, max_triangles: int | None = MAX_TRIANGLES,
              limit_s: float | None = None) -> Generator[float, None, views.ViewParts]:
    """Los pasos del TIN de la corta ``request.record`` (``des_pbl_<nombre>``) con las ``lines`` (``(vértices absolutos (n, 3), cerrada)``) y la línea de cielo ``skyline`` como aristas
    (véase el módulo): un objeto con la malla del TIN recortado a lo que encierra la línea más externa, en locales, y su aviso si ha habido que dejar fuera la línea de cielo. Si el número estimado
    de triángulos (``2·puntos``) pasa de ``max_triangles``, ``des.pit_view_large`` **antes de crear nada**. ``limit_s``: el máximo de la CDT de Blender (por defecto, el parámetro). Cerrados
    antes de terminar, no dejan nada."""
    pit = _suffix(request.record.name, TIN_FAMILY)
    origin_xy = np.array([float(request.origin.x0), float(request.origin.y0)])
    notes: list[str] = []
    used = [*lines, *skyline]
    absolute, xy, edges = _edges_and_points(used, origin_xy)
    if len(xy) < 3 or not len(edges):
        raise _empty(pit, tr("Pit TIN"), tr("its lines do not enclose any area"))
    if max_triangles is not None and 2 * len(xy) > max_triangles:
        raise _large(pit, tr("Pit TIN"), 2 * len(xy), max_triangles)
    yield 0.05
    try:
        faces, who = yield from _triangulate(request, xy, edges, limit_s)
    except cdt.TriangulatorError as error:
        if error.code != "gis.triangulation_input" or not skyline:
            raise
        notes.append(tr("The skyline of «{name}» crosses a bench line and could not be used as edges of the TIN: it is drawn without it", name=pit))
        absolute, xy, edges = _edges_and_points(list(lines), origin_xy)
        faces, who = yield from _triangulate(request, xy, edges, limit_s)
    yield 0.4
    inside = _inside_faces(faces, edges, len(xy))
    faces = np.ascontiguousarray(faces[inside], dtype=np.int32)
    if not len(faces):
        raise _empty(pit, tr("Pit TIN"), tr("its lines do not enclose any area"))
    yield 0.5
    tin = Tin(absolute, faces, edges, np.full(len(absolute), 3, dtype=np.uint8), triangulator=who)
    arrays = surface_mesh_from_tin(tin)
    return (yield from _surface(request, tin, arrays, request.name, notes, 0.55))


def _cdt_limit(project: Any) -> float | None:
    """El ``gis.tin.blender_cdt_max_s`` del proyecto, si lo tiene registrado; si no, ``None`` (el valor por defecto)."""
    record = ParameterStore(project).get(triangulator.MAX_SECONDS_KEY)
    return None if record is None else float(record.value)


def tin_loader(max_triangles: int | None = MAX_TRIANGLES) -> views.ViewLoader:
    """El cargador del TIN de la corta (``des_pbl_``) con el límite de triángulos ``max_triangles`` (``None``: sin aviso)."""

    def load(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
        project, record = request.project, request.record
        with project.read() as conn:
            owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
            lines = pit_lines.read_pit_lines(conn, record.locator, pit_lines.POLYLINES, closed_column="closed")
            sky = dataset_registry.get(conn, _named(SKYLINE_FAMILY, _suffix(record.name, TIN_FAMILY)), version_uid=owner)
            sky_lines = () if sky is None or not sky.live else pit_lines.read_pit_lines(conn, sky.locator, pit_lines.SKYLINE)
        yield 0.02
        found = [(row.points, row.closed) for row in lines]
        skyline = [(row.points, bool(np.array_equal(row.points[0], row.points[-1]))) for row in sky_lines]
        return (yield from tin_steps(request, found, skyline, max_triangles=max_triangles, limit_s=_cdt_limit(project)))

    return load


def load_pit_tin(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """El cargador registrado del TIN: con el límite de triángulos de ahora (:func:`limit`: el por defecto, o ninguno mientras se confirma con :func:`unlimited`)."""
    return (yield from _warned(tin_loader(limit()), request))


def tin_companions(conn: Any, record: DatasetRecord) -> tuple[DatasetRecord, ...]:
    """Los datos compañeros del TIN (``views.CompanionsReader``): la línea de cielo (``des_psk_``) de su versión, cuyas aristas entran en él. Solo lee."""
    owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
    found = dataset_registry.get(conn, _named(SKYLINE_FAMILY, _suffix(record.name, TIN_FAMILY)), version_uid=owner)
    return () if found is None or not found.live else (found,)


# --- El sólido ---------------------------------------------------------------------------------------------------------------


def _wall_edges(faces: np.ndarray, count: int) -> np.ndarray:
    """Las aristas de borde de ``faces`` (antihorarias, ``count`` vértices): ``(a, b)`` dirigidas cuya inversa no está en otra cara."""
    sides = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]).astype(np.int64)
    forward = sides[:, 0] * count + sides[:, 1]
    backward = sides[:, 1] * count + sides[:, 0]
    return sides[~np.isin(forward, backward)]


def solid_steps(request: Any, start: Raster, surface: Raster, *, max_triangles: int | None = MAX_TRIANGLES) -> Generator[float, None, views.ViewParts]:
    """Los pasos del sólido de excavación de la corta ``request.record`` (``des_pbk_<nombre>``) entre la superficie de partida ``start`` y la de la corta ``surface`` (la misma rejilla; véase el
    módulo): una malla cerrada en las celdas donde ``surface`` baja de ``start``, en locales. ``des.pit_view_empty`` si no baja en ninguna; ``des.pit_view_large`` **antes de crear nada** si
    sus triángulos pasan de ``max_triangles``. Cerrados antes de terminar, no dejan nada."""
    pit = _suffix(request.record.name, SOLID_FAMILY)
    with np.errstate(invalid="ignore"):
        cut = np.isfinite(start.values) & np.isfinite(surface.values) & (surface.values < start.values)
    if not cut.any():
        raise _empty(pit, tr("Pit excavation solid"), tr("the pit does not lower the start surface anywhere"))
    top = Raster(start.grid, np.where(cut, start.values, np.nan), start.crs, start.vertical)
    try:
        tin = yield from _scaled(_blocks(raster_to_tin_steps(top, name=request.record.name)), 0.0, 0.3)
    except GisError as error:
        if error.code != "gis.grid_tin_empty":
            raise
        raise _empty(pit, tr("Pit excavation solid"), tr("the cells it lowers are too few to make a surface")) from error
    count = len(tin.vertices)
    faces = np.ascontiguousarray(tin.faces, dtype=np.int64)
    walls = _wall_edges(faces, count)
    triangles = 2 * len(faces) + 2 * len(walls)
    if max_triangles is not None and triangles > max_triangles:
        raise _large(pit, tr("Pit excavation solid"), triangles, max_triangles)
    yield 0.35
    bottom = tin.vertices.copy()
    bottom[:, 2] = des_views._cell_values(tin.vertices, surface.grid, surface.values)  # noqa: SLF001 - el valor de la celda de que es centro cada vértice
    top_a, top_b = walls[:, 0], walls[:, 1]
    low_a, low_b = top_a + count, top_b + count
    around = np.concatenate([np.column_stack([top_a, low_a, low_b]), np.column_stack([top_a, low_b, top_b])])
    solid = np.vstack([faces, faces[:, ::-1] + count, around]).astype(np.int32)  # arriba, abajo (al revés) y las paredes hacia fuera
    vertices = np.vstack([tin.vertices, bottom])
    yield 0.4
    mesh = yield from _scaled(mesh_steps(request.name, vertices, solid, origin=request.origin), 0.4, 0.95)
    try:
        return _object(request.name, mesh, (), mesh_vertices_local(mesh))
    except BaseException:
        bpy.data.meshes.remove(mesh)
        raise


def solid_loader(max_triangles: int | None = MAX_TRIANGLES) -> views.ViewLoader:
    """El cargador del sólido de excavación (``des_pbk_``) con el límite de triángulos ``max_triangles`` (``None``: sin aviso)."""

    def load(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
        from ...design import access_store, surfaces  # al cargar: no al habilitar

        project, record = request.project, request.record
        pit = _suffix(record.name, SOLID_FAMILY)
        with project.read() as conn:
            owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
            start_name = access_store.read_access_surface(conn, record.operation_uid)  # su entrada con el papel de superficie (el nombre del helper es de la 017)
        if start_name is None:  # un proyecto dañado: no se sabe de qué superficie parte
            raise ValueError(f"la operación de la corta «{pit}» no consumió ninguna superficie: no se sabe entre qué superficies dibujar el sólido")
        surface = surfaces.read_surface(project, _named(design_provenance.ENTITY_SURFACE_GRID, pit), version_uid=owner, role="superficie de la corta")
        des_views._check_references(project, surface, record.name)  # noqa: SLF001 - la misma comprobación
        yield 0.05
        start = surfaces.read_surface(project, start_name, version_uid=owner, expect=surface, role="superficie de partida")
        yield 0.1
        return (yield from _scaled(solid_steps(request, start, surface, max_triangles=max_triangles), 0.1, 1.0))

    return load


def load_pit_solid(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """El cargador registrado del sólido: con el límite de triángulos de ahora (:func:`limit`)."""
    return (yield from _warned(solid_loader(limit()), request))


def solid_companions(conn: Any, record: DatasetRecord) -> tuple[DatasetRecord, ...]:
    """Los datos compañeros del sólido (``views.CompanionsReader``): la superficie de la corta (``des_psf_``) y la de partida de su operación, vivas y de su versión: cambiar cualquiera deja la
    vista «no al día». Solo lee."""
    from ...design import access_store  # al cargar: no al habilitar

    owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
    names = [_named(design_provenance.ENTITY_SURFACE_GRID, _suffix(record.name, SOLID_FAMILY))]
    start = access_store.read_access_surface(conn, record.operation_uid)
    if start is not None:
        names.append(start)
    found = (dataset_registry.get(conn, name, version_uid=owner) for name in names)
    return tuple(item for item in found if item is not None and item.live)


COMPANIONS: dict[str, Callable[[Any, DatasetRecord], tuple[DatasetRecord, ...]]] = {TIN_FAMILY: tin_companions, SOLID_FAMILY: solid_companions}


def _pit_title(role: str) -> views.OwnTitleReader:
    """El lector del nombre propio de los datos de la corta con el papel ``role``: el nombre de la corta (el de hoy: «Corta E1») de la que sale el dato ``name`` de la versión ``version_uid``, si es el
    vigente suyo (spec 018, T40e, H3-6); si no, ``""`` (el nombre del dato)."""

    def title(project: Any, conn: Any, version_uid: str, name: str) -> str:
        from ...design import pit_layer  # al usarlo: habilitar no lo carga (RNF-001-03; trae las máscaras)

        version = versions_read.version(conn, version_uid) if version_uid else None
        if version is None:
            return ""
        for head in pit_layer.pit_heads(project, conn, version):
            try:
                _table, found = pit_layer.pit_data(conn, head, version, role, "")
            except (DesignError, ValueError):
                continue
            if found == name:
                return head.name
        return ""

    return title


OWN_TITLES: dict[str, views.OwnTitleReader] = {TIN_FAMILY: _pit_title(design_provenance.PIT_POLYLINES_ROLE), SOLID_FAMILY: _pit_title(design_provenance.PIT_BENCHES_ROLE)}
"""El nombre propio de los objetos del TIN y del sólido de una corta (``views.OwnTitleReader``): el nombre de la corta, no el del dato."""
"""Los datos compañeros de cada vista por familia (``des_views.register`` se los da al cargador)."""
