# SPDX-License-Identifier: GPL-3.0-or-later
"""Los sectores de diseño y el talud general máximo que impone cada uno (spec 013; RF-013-05,
RF-013-06, RF-013-07, RF-013-08, RF-013-09, RF-013-10; plan 013 §5.2.2, §5.3.1, D-5, D-15, D-23;
ADR-0029; D-9 y D-26 de la 012; RF-008-05, RF-009-24).

**Los sectores** de diseño son los de búsqueda de intocables de la 012 (D-5: una sola declaración
por proyecto; ``gis.masks.store.search_sectors``): :func:`design_sectors` los da en su orden con su
código, su nombre, el estado de su búsqueda (``pending``: sin una búsqueda vigente, A12 de la 012),
su área y el talud que imponen. Sin sectores declarados, el perímetro de actuación es el único
(código ``""``, D-26). El **área** es la de cuadrícula de la rejilla del proyecto, como las demás de
la 013: las celdas cuyo centro está dentro del sector (D-16) por el área de una celda.

**Los que toca el dominio** (D-15): :func:`touched` da los que tienen alguna celda en el dominio de
trabajo (``DomainSet.touched``), no los que tocan el dominio por defecto; acotar el trabajo a un
sector o a una capa cambia cuáles son. Solo esos pueden impedir calcular.

**El rechazo** (RF-013-05; D-9 de la 012): :func:`refuse_pending` lanza ``des.sector_pending`` si
alguno de los que toca el dominio tiene la búsqueda pendiente, nombrándolos y con la orden «Buscar
elementos intocables por sector…»; no escribe ni calcula nada. **La marca** (RF-013-06):
:func:`pending_marks` da, de los sectores que tocó un resultado ya producido, los que siguen con la
búsqueda pendiente ahora: «búsqueda de intocables pendiente» con el sector.

**El talud impuesto** (RF-013-08, RF-013-09; ADR-0029): un parámetro por sector es la familia de
versión ``des.sector.{s}.max_general_slope_deg`` de ``core.params`` cuyo segmento ``{s}`` es el
**código** del sector (:func:`slope_key`; el perímetro como sector único, el segmento reservado
``perimeter__``): sin esquema nuevo y sin tocar las specs 008 y 009. Se resuelve para cada sector
con el valor **del sector en la versión activa o, si no lo tiene, el del sector en el
proyecto** (``ParameterStore.resolve_many``, RF-009-24): un sector sin fila en ningún ámbito no
impone ningún talud (no hay valor general de respaldo) y uno con la fila **sin valor** en la
versión lo levanta en ella aunque el proyecto lo imponga (D-4 de la 012). Lo resuelto
(:class:`SectorSlope`) lleva el sector, el ámbito, el uid del parámetro y la entrada del historial
que se usó (RF-008-05) más el registro, con su tipo, origen y decisor, para enseñarlos (RF-013-07);
:func:`slope_params` da las claves que se pasan a ``begin_operation(params=…)`` para que la
operación anote lo mismo, y :func:`imposed_slopes` los grados comprobados (0 a 90 ° ambos
excluidos, ``check_sector_slope``) de los sectores que imponen uno.

**Redeclarar y renombrar** (RF-013-10): como la clave lleva el código, redeclarar los sectores
(``core.declare_sectors``, que les da uid nuevos) conserva los valores con su historial, y un
sector que desaparece o se renombra (su código cambia) deja el suyo sin borrar:
:func:`orphan_slopes` los lista, de cualquier ámbito, para que la persona los pase al sector nuevo.

Solo lee: nada de esto escribe en el proyecto (declarar o cambiar un talud es de las órdenes de
``bl``). Python puro (nivel 8), con numpy.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from ..core.params import (
    PROJECT_SCOPE,
    VERSION_SCOPE,
    ParameterRecord,
    ParameterStore,
    ResolvedParam,
)
from ..core.versions import read as versions_read
from ..gis.grid import project_grid
from ..gis.masks.store import search_sectors, sector_states_now
from ..gis.store import StoreProject
from .messages import DesignError, render
from .model import PERIMETER_SEGMENT
from .params import FAMILIES, SECTOR_SLOPE, check_sector_slope, sector_slope_key
from .seeds import DomainSet
from .zones import sector_labels

__all__ = [
    "DesignSector",
    "OrphanSlope",
    "PendingMark",
    "SectorSlope",
    "design_sectors",
    "imposed_slopes",
    "orphan_slopes",
    "pending_marks",
    "refuse_pending",
    "slope_key",
    "slope_params",
    "touched",
]

_FAMILY = next(item for item in FAMILIES if item.pattern == f"des.sector.{{s}}.{SECTOR_SLOPE}")
"""La familia del talud impuesto por un sector (plan §5.2.2)."""
_PENDING_FIELD = "búsqueda de intocables"
_PENDING_OBJECT = "Sectores de diseño"


def slope_key(code: str) -> str:
    """La clave del talud general máximo impuesto del sector de código ``code``
    (``des.sector.sector_2.max_general_slope_deg``) o, con ``""`` —el perímetro de actuación como
    sector único—, la del segmento reservado ``perimeter__`` (ADR-0029). El segmento es siempre el
    código, nunca el nombre ni el uid. ``ValueError`` (un error del programa) si no es
    ``[a-z][a-z0-9_]*`` o si es el propio segmento reservado, que se pide con ``""``."""
    if code == PERIMETER_SEGMENT:
        raise ValueError(f"«{PERIMETER_SEGMENT}» es el segmento reservado del perímetro de "
                         "actuación (ADR-0029): su código es el vacío, «»")
    return sector_slope_key(PERIMETER_SEGMENT if code == "" else code)


# --- Lo resuelto -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SectorSlope:
    """El talud impuesto de un sector, tal como se resolvió (RF-013-09; RF-008-05): el ``sector``
    (su código, ``""`` el perímetro), la ``key`` y el ``value`` (° sin comprobar; ``None``: la fila
    del ámbito elegido no tiene valor, y entonces no impone nada), ``param`` (lo que anota una
    operación: el ámbito, su uid, el uid del parámetro y la revisión del historial que se usó) y
    ``record`` (el registro de ese ámbito, con su tipo, origen, decisor, motivo y marca «sin
    confirmar»)."""

    sector: str
    key: str
    value: float | None
    param: ResolvedParam
    record: ParameterRecord

    @property
    def scope(self) -> str:
        """``"version"`` o ``"project"``: de dónde salió el valor."""
        return self.param.scope

    @property
    def rev(self) -> int:
        """La revisión del historial que se usó."""
        return self.param.rev

    def imposed(self) -> float | None:
        """El talud en grados, comprobado (``check_sector_slope``: de 0 a 90 °, ambos excluidos), o
        ``None`` si la fila no tiene valor. ``DesignError`` ``des.sector_slope_range`` si está
        fuera de su rango."""
        if self.value is None:
            return None
        return check_sector_slope(self.sector or PERIMETER_SEGMENT, self.value)


@dataclass(frozen=True, slots=True)
class DesignSector:
    """Un sector de diseño (RF-013-07): su ``code`` (``""``: el perímetro de actuación) y su
    ``name``; las celdas (``cells``) y el área (``area_m2``, de cuadrícula) de la rejilla del
    proyecto que son suyas; si su búsqueda de intocables está pendiente (``pending``) y su
    ``slope``, el talud impuesto resuelto en la versión pedida (``None``: ninguna fila en ningún
    ámbito)."""

    code: str
    name: str
    cells: int
    area_m2: float
    pending: bool
    slope: SectorSlope | None

    @property
    def key(self) -> str:
        """La clave del talud impuesto del sector (:func:`slope_key`)."""
        return slope_key(self.code)

    @property
    def imposed_deg(self) -> float | None:
        """El talud que impone, en grados y comprobado, o ``None`` si no impone ninguno
        (:meth:`SectorSlope.imposed`; ``DesignError`` si está fuera de rango)."""
        return None if self.slope is None else self.slope.imposed()


@dataclass(frozen=True, slots=True)
class OrphanSlope:
    """Un valor del talud impuesto de un sector que ya no existe (RF-013-10): el ``segment`` de su
    clave (el código del sector que desapareció o se renombró; ``perimeter__`` si el perímetro ya
    no es el sector único), su ``key``, el ``scope`` (``"project"`` o ``"version"``), el
    ``version`` (su código; vacío en el proyecto), el ``value`` (°) y el ``record`` con su
    historial. No se borra nunca."""

    segment: str
    key: str
    scope: str
    version: str
    value: float | None
    record: ParameterRecord


@dataclass(frozen=True, slots=True)
class PendingMark:
    """La marca «búsqueda de intocables pendiente» de un resultado (RF-013-06): el sector (``code``
    y ``name``) que tocó su dominio de trabajo y sigue sin búsqueda vigente."""

    code: str
    name: str

    def text(self, language: str = "es") -> str:
        """La marca en ``language`` (``"es"`` o ``"en"``): «Búsqueda de intocables pendiente en
        «Sector 2».»"""
        return render("des.sector_pending_mark", language=language,
                      sector=_shown(self.code, self.name))


def _shown(code: str, name: str) -> str:
    """Cómo se nombra un sector: «su nombre»; el perímetro de actuación, sin guillemets."""
    return name if code == "" else f"«{name}»"


# --- Los sectores ------------------------------------------------------------------------------


def _read_slopes(conn: sqlite3.Connection, project: StoreProject, codes: Sequence[str],
                 version: str | None) -> dict[str, SectorSlope]:
    """El talud de cada sector de ``codes`` que tiene fila: la de la versión ``version`` (uid o
    código) y, si no, la del proyecto; solo la del proyecto sin versión."""
    store = ParameterStore(project)
    keys = {slope_key(code): code for code in codes}
    if not keys:
        return {}
    chain = (PROJECT_SCOPE,) if version is None else (VERSION_SCOPE, PROJECT_SCOPE)
    resolved = store.resolve_many(conn, keys, chain, version=version)
    found: dict[str, SectorSlope] = {}
    for key, param in resolved.items():
        record = store.get(key, version=param.scope_uid or None, conn=conn)
        assert record is not None  # acaba de resolverse: la fila existe
        value = None if param.value is None else float(param.value)  # type: ignore[arg-type]
        found[keys[key]] = SectorSlope(keys[key], key, value, param, record)
    return found


def design_sectors(project: StoreProject, version_uid: str | None) -> tuple[DesignSector, ...]:
    """Los sectores de diseño de ``project`` en la versión ``version_uid`` (uid o código; ``None``:
    solo lo del proyecto), en el orden de la 012: los de búsqueda declarados o, sin ninguno, el
    perímetro de actuación. Cada uno con su estado, su área y su talud impuesto resuelto (véase el
    módulo); ninguno si no hay sectores ni perímetro. Solo lee, en una sola lectura. Un talud
    fuera de rango no falla aquí (la ventana de sectores tiene que poder listarlo y corregirlo):
    falla al usarlo (:func:`imposed_slopes`). ``ValueError`` si el proyecto está abierto solo con
    su cabecera (no tiene rejilla)."""
    record = project.record
    if record is None:
        raise ValueError("el proyecto está abierto solo con su cabecera: no tiene rejilla")
    grid = project_grid(record.window, float(record.grid_step_m))
    version = version_uid or None
    with project.read() as conn:
        found = tuple(sector for sector, _source in search_sectors(conn, project, version))
        states = sector_states_now(conn, project, version)
        slopes = _read_slopes(conn, project, [sector.code for sector in found], version)
    counts = np.bincount(sector_labels(found, grid).ravel(), minlength=len(found) + 1)
    area = grid.cell_area
    return tuple(
        DesignSector(sector.code, sector.name, int(counts[index]), int(counts[index]) * area,
                     not state.current, slopes.get(sector.code))
        for index, (sector, state) in enumerate(zip(found, states, strict=True), start=1))


def touched(sectors: Sequence[DesignSector], domain: DomainSet) -> tuple[DesignSector, ...]:
    """De ``sectors``, los que toca el dominio de trabajo ``domain`` (D-15: los que tienen alguna
    celda en él), en su orden. Un sector que el dominio toca y ``sectors`` no tiene es un error del
    programa (``ValueError``: la declaración cambió entre preparar el dominio y comprobarlo); no se
    salta una comprobación."""
    wanted = {ref.code for ref in domain.touched}
    unknown = sorted(wanted - {item.code for item in sectors})
    if unknown:
        raise ValueError("el dominio de trabajo toca sectores que no son de los sectores de "
                         f"diseño: {', '.join(repr(code) for code in unknown)}")
    return tuple(item for item in sectors if item.code in wanted)


def refuse_pending(touched_sectors: Iterable[DesignSector]) -> None:
    """RF-013-05: si alguno de ``touched_sectors`` (los que toca el dominio de trabajo,
    :func:`touched`) tiene la búsqueda de intocables pendiente, lanza ``des.sector_pending``
    nombrando todos los pendientes y la orden «Buscar elementos intocables por sector…» (el
    perímetro de actuación, si no hay sectores). No devuelve nada si no hay ninguno; no escribe ni
    calcula nada."""
    pending = [item for item in touched_sectors if item.pending]
    if not pending:
        return
    names = ", ".join(_shown(item.code, item.name) for item in pending)
    obj = f"Sector {names}" if len(pending) == 1 else _PENDING_OBJECT
    raise DesignError("des.sector_pending", obj=obj, field=_PENDING_FIELD, value=names,
                      codes=", ".join(item.code or PERIMETER_SEGMENT for item in pending))


def pending_marks(touched_codes: Iterable[str], sectors: Sequence[DesignSector]
                  ) -> tuple[PendingMark, ...]:
    """RF-013-06, RF-012-10: las marcas «búsqueda de intocables pendiente» de un resultado ya
    producido, cuyo dominio de trabajo tocó los sectores ``touched_codes`` (sus códigos, tal como
    se anotaron al calcular): una por cada uno que en ``sectors`` (ahora) tiene la búsqueda
    pendiente, en el orden de ``sectors``. Un sector que ya no existe no se puede decir
    pendiente y no tiene marca."""
    if isinstance(touched_codes, str):
        raise TypeError("los sectores que tocó un resultado son una secuencia de códigos, "
                        f"no el texto {touched_codes!r}")
    wanted = set(touched_codes)
    return tuple(PendingMark(item.code, item.name) for item in sectors
                 if item.pending and item.code in wanted)


# --- El talud impuesto -------------------------------------------------------------------------


def imposed_slopes(sectors: Sequence[DesignSector]) -> dict[str, float]:
    """Código → talud general máximo impuesto (°, float64, comprobado con ``check_sector_slope``)
    de los sectores que imponen uno (RF-013-09): los que no tienen fila o la tienen sin valor no
    salen. ``DesignError`` ``des.sector_slope_range`` si el valor de alguno está fuera de (0; 90) °
    (``ParamDef`` solo excluye el mínimo, y el 90 no se rechaza al guardarlo)."""
    found: dict[str, float] = {}
    for item in sectors:
        degrees = item.imposed_deg
        if degrees is not None:
            found[item.code] = degrees
    return found


def slope_params(sectors: Sequence[DesignSector]) -> tuple[str, ...]:
    """Las claves de los parámetros que la operación lee de ``sectors`` (RF-013-09, RF-008-05):
    las de los que tienen fila en algún ámbito —también la que no tiene valor, que levanta el talud
    en la versión—, en su orden. Es lo que se pasa a ``begin_operation(params=…)``, que anota
    de cada una el ámbito y la revisión del historial que resuelve; un sector sin fila no se
    nombra (no se registra un parámetro vacío por defecto)."""
    return tuple(item.slope.key for item in sectors if item.slope is not None)


def orphan_slopes(project: StoreProject, sectors: Sequence[DesignSector]
                  ) -> tuple[OrphanSlope, ...]:
    """Los valores del talud impuesto cuyo sector ya no es de ``sectors`` (RF-013-10): los de
    cualquier ámbito (el proyecto y cada versión) con una clave de la familia que no es la de
    ningún sector actual, por clave y, en cada una, el proyecto antes que las versiones (por su
    número). Un sector renombrado cambia de código y deja el suyo aquí; si el perímetro de actuación
    deja de ser el sector único, también el suyo. Nunca se borran: la persona los pasa al sector
    nuevo. Solo lee."""
    active = {slope_key(item.code) for item in sectors}
    store = ParameterStore(project)
    found: list[OrphanSlope] = []
    with project.read() as conn:
        rows = conn.execute("SELECT DISTINCT key FROM gb_parameter WHERE key LIKE 'des.sector.%' "
                            "ORDER BY key").fetchall()
        for (key,) in rows:
            segments = _FAMILY.match(key)
            if segments is None or key in active:
                continue
            for record in store.scopes(key, conn=conn):
                version = ""
                if record.scope == VERSION_SCOPE:
                    owner = versions_read.version(conn, record.scope_uid)
                    version = record.scope_uid if owner is None else owner.code
                value = None if record.value is None else float(record.value)  # type: ignore[arg-type]
                found.append(OrphanSlope(segments[0], key, record.scope, version, value, record))
    return tuple(found)
