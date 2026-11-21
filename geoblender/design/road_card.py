# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que el proyecto dice de una pista y de una accesibilidad para la barra N (spec 017, T31b; HU-017-1, HU-017-3; RF-015-25, RF-017-23, RF-017-25; plan 017 §5.1 y §5.5).

**Solo lee**: nada se calcula ni se escribe. Es el dominio de lectura de la ficha de la barra N «Entidad» y «Elemento activo» (``bl.ui.des_panels``, que solo escribe los textos
traducidos): de lo **guardado** de la operación vigente de la entidad, no de un cálculo abierto ni de la vista.

- :func:`read_road_facts`: de una **pista**, lo de su informe (``des_prp_``: la longitud, las cotas, las pendientes con su abscisa y su lugar, las curvas, el corte y el relleno de la
  sección y del borde, la pared del borde) y de sus cifras (la calzada y la sección), lo que la persona confirmó al crearla (RF-017-17, RF-017-22) y sus avisos con su código.
- :func:`stale_other_designs`: los **otros diseños** que lee la pista (entrada ``other_design``, RF-017-05 (b)) y que han cambiado o están cambiando: la causa de una pista obsoleta
  por un diseño que no es el suyo (H2-2: ``Recalcular lo obsoleto`` no la asienta si ese diseño se apoya ahora en ella).
- :func:`marked_layer`: si la capa de ejes de pistas de la versión (``des_rax_``) está **marcada** para esta pista: dice otro estado que el registro (RF-017-27; T26-b: cambiar el valor de
  un perfil deja las pistas obsoletas por el grafo y no la regenera al instante).
- :func:`read_access_facts`: de una **accesibilidad**, las cotas mínima y máxima alcanzables y las listas de tramos de berma, plataformas y zonas «requiere acceso» **comunicados o no**
  (``des_acb_``, ``des_acp_`` y ``des_acz_`` de su operación vigente), con el lugar que guardan —el tramo de berma y la zona que no se comunica— o el que sale de la huella de la plataforma.

Python puro (nivel 8). ``design.road_card`` es un módulo pesado de la 017 (importa ``road_store`` y ``access_store``): lo importa la barra N al usarlo, no ``bl`` al registrarse
(``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..core.provenance import stale
from ..gis.grid import project_grid
from . import entities, entity_store, provenance, road_layer, road_profiles
from .access_store import AccessZone, read_zone_table
from .preview import Named, Notice
from .road_store import RoadConfirmed, confirmed_of

__all__ = [
    "AccessFacts",
    "AccessSpot",
    "BermRow",
    "PlatformRow",
    "RoadFacts",
    "footprint_spot",
    "marked_layer",
    "profile_name",
    "read_access_facts",
    "read_road_facts",
    "report_notices",
    "stale_other_designs",
]

_FIGURE_KEYS = ("des.road_width_m", "des.road_section_m", "des.road_net_m3")
_FIGURES = "SELECT key, value FROM gb_figure WHERE operation_uid = ? AND key IN ({marks}) ORDER BY fid"
_SETTINGS = "SELECT settings FROM gb_operation WHERE uid = ?"
_OTHER_DESIGNS = (
    "SELECT d.name, d.status, d.content_sha256, d.operation_uid, io.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.item_kind = 'dataset' AND io.role = ? ORDER BY io.fid")
_FINAL_SURFACE = (
    "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.item_kind = 'dataset' AND io.role = ? ORDER BY io.fid")


# --- Los avisos guardados ----------------------------------------------------------------------------------


def _named(item: object) -> object:
    """Un elemento de una lista de un aviso guardado como JSON: el de un texto que se dice en el idioma de quien lee (``{"code", "values"}``) vuelve a ser un :class:`~.preview.Named`."""
    if isinstance(item, Mapping) and "code" in item:
        values = item.get("values", {})
        return Named(str(item["code"]), _restore(values) if isinstance(values, Mapping) else {})
    return item


def _restore(values: Mapping[str, object]) -> dict[str, object]:
    """Los valores de un aviso guardado como JSON con lo que el aviso llevaba al guardarse: sus listas son tuplas (de números o de :class:`~.preview.Named`)."""
    return {str(name): tuple(_named(item) for item in value) if isinstance(value, list) else value for name, value in values.items()}


def report_notices(report: Sequence[tuple[str, float | None, str | None, str | None]]) -> tuple[Notice, ...]:
    """Los avisos y las notas del informe ``report`` de una pista o de una accesibilidad (``entity_store.read_entity_report``: las filas ``warning`` y ``note`` llevan el código y los
    valores en JSON, no el texto) como :class:`~.preview.Notice`, en su orden y listos para escribirse en el idioma de la interfaz. Una lista de un aviso (los tramos de un aviso de la pista)
    vuelve a ser una tupla de :class:`~.preview.Named`; lo que no se puede leer, o cuyo código ya no es del catálogo, **no sale** (no se inventa un texto). Solo lee."""
    found: list[Notice] = []
    for quantity, _value, _unit, note in report:
        if quantity not in ("warning", "note") or not note:
            continue
        try:
            decoded = json.loads(note)
            values = decoded.get("values", {})
            notice = Notice(str(decoded["code"]), _restore(values) if isinstance(values, Mapping) else {})
            notice.severity  # noqa: B018 - el código ha de ser del catálogo: si no, lanza
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        found.append(notice)
    return tuple(found)


# --- La pista ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoadFacts:
    """Lo guardado de la operación vigente de una pista (:func:`read_road_facts`), en metros y por cientos: la ``length_m`` del eje, las cotas de inicio (``z_start_m``) y de fin
    (``z_end_m``) de la rasante, la pendiente media y la máxima (``gradient_mean_pct`` y ``gradient_max_pct``) con la abscisa de esta (``gradient_max_station_m``) y su lugar absoluto
    (``gradient_max_place``: ``(x, y)``), cuántas ``curves`` tiene y el radio mínimo de la menor (``radius_min_m``; ``None`` sin curvas), la anchura de la calzada (``width_m``) y de la
    sección (``section_m``), el corte y el relleno **de la sección** (``section_cut_m3`` y ``section_fill_m3``) y **del borde** (``edge_cut_m3`` y ``edge_fill_m3``), el neto, la mayor
    pared del borde (``wall_max_m``, con su lugar) y lo que la persona **confirmó** al crearla (``confirmed``), más los ``notices`` del cálculo, en su orden. ``None`` lo que no se guardó."""

    length_m: float | None
    z_start_m: float | None
    z_end_m: float | None
    gradient_mean_pct: float | None
    gradient_max_pct: float | None
    gradient_max_station_m: float | None
    gradient_max_place: tuple[float, float] | None
    curves: int
    radius_min_m: float | None
    width_m: float | None
    section_m: float | None
    section_cut_m3: float | None
    section_fill_m3: float | None
    edge_cut_m3: float | None
    edge_fill_m3: float | None
    net_m3: float | None
    wall_max_m: float | None
    wall_place: tuple[float, float] | None
    confirmed: RoadConfirmed | None
    notices: tuple[Notice, ...]


def _place(note: str | None) -> tuple[float, float] | None:
    """El lugar absoluto ``x;y`` (float64 en texto) que anota una fila del informe, o ``None`` si no lo lleva o no es un lugar."""
    if not note or ";" not in note:
        return None
    try:
        x, _, y = note.partition(";")
        found = (float(x), float(y))
    except ValueError:
        return None
    return found if all(math.isfinite(value) for value in found) else None


def read_road_facts(conn: sqlite3.Connection, operation_uid: str) -> RoadFacts | None:
    """Lo que guardó la operación ``operation_uid`` de una pista (su informe ``des_prp_``, sus cifras y lo que confirmó la persona, ajustes de la operación), leído con ``conn``; ``None`` si
    la operación no escribió ningún informe (RF-015-25: sin lo guardado, la barra N no inventa cifras). Solo lee. ``sqlite3.Error`` sigue."""
    report = entity_store.read_entity_report(conn, operation_uid)
    if not report:
        return None
    first: dict[str, tuple[float | None, str | None]] = {quantity: (value, note) for quantity, value, _unit, note in reversed(report)}

    def number(key: str) -> float | None:
        found = first.get(key, (None, None))[0]
        return None if found is None or not math.isfinite(found) else found

    radii = [value for quantity, value, _unit, _note in report if quantity == "curve" and value is not None and math.isfinite(value)]
    figures = {str(key): float(value) for key, value in conn.execute(_FIGURES.format(marks=", ".join("?" for _ in _FIGURE_KEYS)), (operation_uid, *_FIGURE_KEYS)).fetchall()
               if value is not None}
    try:
        row = conn.execute(_SETTINGS, (operation_uid,)).fetchone()
        confirmed = confirmed_of(json.loads(str(row[0])) if row and row[0] else {})
    except ValueError:  # unos ajustes que no son una confirmación: no se inventa
        confirmed = None
    curves = number("curves")
    wall = first.get("edge_wall_max_m")
    return RoadFacts(number("axis_m"), number("z_start_m"), number("z_end_m"), number("gradient_mean_pct"), number("gradient_max_pct"), number("gradient_max_station_m"),
                     _place(first.get("gradient_max_pct", (None, None))[1]), 0 if curves is None else int(curves), min(radii) if radii else None, figures.get("des.road_width_m"),
                     figures.get("des.road_section_m"), number("section_cut_m3"), number("section_fill_m3"), number("edge_cut_m3"), number("edge_fill_m3"),
                     figures.get("des.road_net_m3"), None if wall is None or wall[0] is None or not math.isfinite(wall[0]) else wall[0], None if wall is None else _place(wall[1]),
                     confirmed, report_notices(report))


def profile_name(conn: sqlite3.Connection, code: str) -> str | None:
    """El nombre del perfil de pista de código ``code`` en el proyecto, o ``None`` si ya no está (un perfil que se quitó o que no es de pista). Solo lee."""
    return next((item.name for item in road_profiles.read_profiles(conn) if item.code == code), None)


def stale_other_designs(conn: sqlite3.Connection, operation_uid: str) -> tuple[str, ...]:
    """Los nombres de los datos de **otros diseños** que lee la pista de la operación ``operation_uid`` (entrada con el papel ``other_design``: RF-017-05 (b), T19-b) **y que han cambiado
    o están cambiando** desde que la pista los leyó: el dato ya no está vivo, su contenido es otro que el anotado, o la operación que lo escribió está ella misma obsoleta. Es la **causa de
    una pista obsoleta por un diseño que no es el suyo** (H2-2, decisión de la sesión principal de 21/11/2026): el sistema no impide que ese diseño se apoye luego en la pista, y entonces
    «Recalcular lo obsoleto» no la asienta; la salida es rehacerla sobre la superficie de ese diseño o descartarla. Por orden de lectura; ninguno si no lee ninguno o ninguno cambió. Solo lee."""
    found: list[str] = []
    for name, status, content_now, writer, content_used in conn.execute(_OTHER_DESIGNS, (operation_uid, provenance.ROAD_OTHER_DESIGN_ROLE)).fetchall():
        changed = (str(status) != "current" or content_now != content_used
                   or (writer is not None and bool(stale.item_causes(conn, stale.OPERATION, str(writer)))))
        if changed and str(name) not in found:
            found.append(str(name))
    return tuple(found)


def marked_layer(project: Any, conn: sqlite3.Connection, version_uid: str, code: str) -> bool:
    """Si la capa de ejes de pistas de la versión ``version_uid`` está **marcada para la pista** ``code``: la capa existe, se puede usar y su fila de esa pista dice otro nombre, otro estado,
    otra clase u otro perfil que el registro de hoy (``road_layer.marked_roads``; RF-017-27, T26-b). Solo lee."""
    return code in road_layer.marked_roads(project, conn, version_uid)


# --- La accesibilidad ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccessSpot:
    """Un lugar al que lleva «Ir a»: su centro absoluto (``x`` e ``y``, m, float64: ADR-0005) y su área (``area_m2``, m²; ``0`` si no se guardó), que da el radio del encuadre."""

    x: float
    y: float
    area_m2: float = 0.0


@dataclass(frozen=True, slots=True)
class BermRow:
    """Un tramo de berma de ``des_acb_``: su ``number``, el dato de bermas de que sale (``source``), su cota real (``level_m``), su área (``area_m2``), si queda comunicado y su lugar
    guardado (``x`` e ``y``, absolutos)."""

    number: int
    source: str | None
    level_m: float
    area_m2: float
    connected: bool
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class PlatformRow:
    """Una plataforma de ``des_acp_``: su ``code`` y su ``name`` (de ahora, o el código si ya no está), si queda comunicada, la cota a que se llega (``level_m``) y su ``place``: **el centro de
    su huella** (``des_epr_`` de la plataforma, no se guarda en la tabla), ``None`` si la huella ya no se puede leer."""

    code: str
    name: str
    connected: bool
    level_m: float | None
    place: AccessSpot | None


@dataclass(frozen=True, slots=True)
class AccessFacts:
    """Lo guardado de la operación vigente de una accesibilidad (:func:`read_access_facts`): la ``surface`` sobre la que se hizo y la ``final`` de su cantera (``None`` si no la tiene), las
    cotas mínima y máxima alcanzables (``z_min_m`` y ``z_max_m``; ``None`` si no se alcanzó nada), el ``area_m2`` alcanzable, la cota mínima sobre la final (``z_min_final_m``), las listas
    **enteras** de tramos de ``berms``, ``platforms`` y ``zones`` «requiere acceso» (comunicados o no: lo que guardan ``des_acb_``, ``des_acp_`` y ``des_acz_``) y los ``notices`` del cálculo.
    El lugar de una zona es el que guarda la tabla, **solo de la que no se comunica** (su celda más próxima a lo alcanzable); el de una comunicada no se guarda y no hay «Ir a»."""

    surface: str | None
    final: str | None
    z_min_m: float | None
    z_max_m: float | None
    area_m2: float | None
    z_min_final_m: float | None
    berms: tuple[BermRow, ...]
    platforms: tuple[PlatformRow, ...]
    zones: tuple[AccessZone, ...]
    notices: tuple[Notice, ...]


def footprint_spot(window: Any, step_m: float, runs: Sequence[Sequence[int]]) -> AccessSpot | None:
    """El centro absoluto de las celdas de una huella dada en tramos de fila ``(fila, primera columna, columna final excluida)`` de la rejilla del proyecto (``window``, ``step_m``) y su
    área (m²): como ``access_store.access_places`` lo hace con las celdas del cálculo, el mismo punto. float64: nunca float32 (regla 4 de ``AGENTS.md``). ``None`` sin celdas."""
    grid = project_grid(window, step_m)
    cells, rows, cols = 0, 0.0, 0.0
    for row, first, last in runs:
        count = int(last) - int(first)
        if count <= 0:
            continue
        cells += count
        rows += float(row) * count
        cols += count * (int(first) + int(last) - 1) / 2.0
    if not cells:
        return None
    return AccessSpot(float(grid.west + (cols / cells + 0.5) * grid.dx), float(grid.north - (rows / cells + 0.5) * grid.dy), float(cells * grid.cell_area))


def _platform_spot(project: Any, conn: sqlite3.Connection, entry: entities.EntityEntry | None) -> AccessSpot | None:
    """El centro de la huella de la plataforma ``entry`` (su ``des_epr_`` vigente); ``None`` si no está en el registro, no tiene operación o su huella no se puede leer."""
    if entry is None or entry.operation_uid is None:
        return None
    table = entity_store.operation_table(conn, str(entry.operation_uid), provenance.ENTITY_ROLE)
    if table is None:
        return None
    try:
        footprint = entity_store.read_entity_footprint(conn, table)
        return footprint_spot(project.record.window, float(project.record.grid_step_m), footprint.runs)
    except (ValueError, TypeError, KeyError, sqlite3.Error):
        return None


def _finite(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and math.isfinite(float(value)) else None  # type: ignore[arg-type]


def read_access_facts(project: Any, conn: sqlite3.Connection, version: Any, entry: entities.EntityEntry) -> AccessFacts | None:
    """Lo que guardó la operación vigente de la accesibilidad ``entry`` (``version``: su :class:`~core.versions.model.Version`): las cotas de su informe, la superficie y la final que
    consumió, las tres tablas ``des_acb_``, ``des_acp_`` y ``des_acz_`` y los avisos del cálculo (RF-017-25; RF-015-25: **todo leído del proyecto**), con ``conn``; ``None`` si la entidad
    no tiene operación (sin calcular) o la operación no escribió su informe ni ninguna tabla. De cada plataforma, su nombre de ahora y el centro de su huella; de cada tramo de berma y de
    cada zona que no se comunica, el lugar que guardan. Solo lee; ``sqlite3.Error`` sigue."""
    operation = entry.operation_uid
    if operation is None:
        return None
    operation = str(operation)
    report = entity_store.read_entity_report(conn, operation)
    first = {quantity: value for quantity, value, _unit, _note in reversed(report)}
    tables = {role: entity_store.operation_table(conn, operation, role)
              for role in (provenance.ROAD_ACCESS_BERMS_ROLE, provenance.ROAD_ACCESS_PLATFORMS_ROLE, provenance.ROAD_ACCESS_ZONES_ROLE)}
    if not report and all(table is None for table in tables.values()):
        return None
    berm_table, platform_table, zone_table = (tables[provenance.ROAD_ACCESS_BERMS_ROLE], tables[provenance.ROAD_ACCESS_PLATFORMS_ROLE], tables[provenance.ROAD_ACCESS_ZONES_ROLE])
    berms = () if berm_table is None else tuple(
        BermRow(int(number), None if source is None else str(source), float(level), float(area), bool(connected), float(x), float(y))
        for number, source, level, area, connected, x, y in conn.execute(f'SELECT stretch, source, level_m, area_m2, connected, x, y FROM "{berm_table}" ORDER BY fid'))
    listed = entities.registry(project, version.uid, conn=conn)
    platforms: list[PlatformRow] = []
    if platform_table is not None:
        for code, connected, level in conn.execute(f'SELECT code, connected, level_m FROM "{platform_table}" ORDER BY fid').fetchall():
            there = listed.get(str(code))
            platforms.append(PlatformRow(str(code), str(code) if there is None else there.record.name, bool(connected), _finite(level), _platform_spot(project, conn, there)))
    zones = () if zone_table is None else read_zone_table(conn, zone_table)
    surface = conn.execute(_FINAL_SURFACE, (operation, provenance.SURFACE_ROLE)).fetchone()
    final = conn.execute(_FINAL_SURFACE, (operation, provenance.ACCESS_FINAL_ROLE)).fetchone()
    return AccessFacts(None if surface is None else str(surface[0]), None if final is None else str(final[0]), _finite(first.get("z_min_m")), _finite(first.get("z_max_m")),
                       _finite(first.get("area_m2")), _finite(first.get("z_min_final_m")), berms, tuple(platforms), zones, report_notices(report))
