# SPDX-License-Identifier: GPL-3.0-or-later
"""Las rejillas del diseño en la vista (spec 013, T27; HU-013-6; RF-013-32; plan 013 §5.1, D-32;
ADR-0005).

:func:`register` registra en ``bl.scene.views`` el cargador de cada una de las tres rejillas de un
diseño (:func:`load_design_grid`) y :func:`unregister` los quita (desactivar Geoblender no deja
ninguno). Las tres son del mismo tipo, :data:`KIND` (``DESIGN``, ``Object.geoblender.kind``), y se
distinguen por el comienzo de su nombre en ``gb_dataset``:

- la **envolvente** (``des_env_<nombre>``, «Envolvente»): las cotas de la envolvente en las celdas
  del dominio de trabajo que alcanza;
- la **superficie de diseño** (``des_srf_<nombre>``, «Superficie de diseño»): el terreno con los
  bancos y las bermas compuesto con las máscaras;
- la **rejilla de cotas de berma** (``des_brm_<nombre>``, «Cotas de berma»): la cota real de cada
  celda de berma, sin dato en las demás.

Un tipo para las tres con tres nombres (D-32: la barra N es la misma): dos objetos de la misma
operación no pueden llamarse igual, y el nombre generado de la vista lleva el del tipo («Envolvente
hoyo · V01 [VIGENTE]»). Lo que hace la vista con lo cargado (la colección de su versión,
``Object.geoblender`` con sus cifras registradas, su nombre generado, el recorte) es de ``views``,
como con los demás datos.

El cargador dibuja la rejilla registrada, **tal como está** (``design.surfaces.read_surface``: cada
celda en float64, NaN donde no hay dato), con la malla de la 006 (la de
``gis.mesh.surface_mesh_from_raster``: los centros de las celdas con dato, con sus niveles de detalle
y la comprobación de la malla de ``bl.scene.gis_views.raster_view_steps``): una celda sin dato no
tiene vértice. Las coordenadas absolutas (float64) pasan a locales respecto al GeoOrigin con
``bl.scene.mesh`` (ADR-0005). La vista no transforma coordenadas: una rejilla en otro CRS o
referencia vertical que el proyecto se rechaza (``gis.view_references_mismatch``). Cargar no escribe
nada en el proyecto ni cambia ninguna operación. Una rejilla de bermas con las bermas más estrechas
que dos celdas no tiene ningún triángulo (``gis.grid_tin_empty``): se avisa, no se carga.
"""

from __future__ import annotations

from collections.abc import Generator

from ...core.versions import read as versions_read
from ...design import provenance as design_provenance
from ...gis.crs import reference_label
from ...gis.messages import GisError
from ...gis.store import project_references
from . import gis_views, views

__all__ = ["KIND", "LOADERS", "load_design_grid", "register", "unregister"]

KIND = "DESIGN"
"""El tipo (``Object.geoblender.kind``) de los objetos de las rejillas de un diseño."""
LOADERS: tuple[tuple[str, str], ...] = (
    (design_provenance.ENVELOPE_GRID, "Envelope"),
    (design_provenance.DESIGN_GRID, "Design surface"),
    (design_provenance.BERMS_GRID, "Berm elevations"),
)
"""Las familias de datos que se cargan (``design.provenance``) con el ``msgid`` de su nombre en el
nombre generado de sus objetos."""


def prefix(family: str) -> str:
    """El comienzo del nombre de los datos de la familia ``family`` (``des_env_``…)."""
    return design_provenance.FAMILIES_BY_CODE[family].prefix


def load_design_grid(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """La rejilla ``request.record`` de un diseño (``des_env_``, ``des_srf_`` o ``des_brm_``) como
    malla de superficie, en pasos (véase el módulo); con ``lod`` 1 o 2, su versión de 2 o 5 m
    (RF-006-22). Cerrados antes de terminar, borra lo que creó."""
    from ...design import surfaces  # al cargar: no al habilitar

    project, record = request.project, request.record
    with project.read() as conn:
        owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
    raster = surfaces.read_surface(project, record.name, version_uid=owner)
    crs, vertical = project_references(project)
    if (raster.crs, raster.vertical) != (crs, vertical):
        raise GisError("gis.view_references_mismatch", obj=f"«{record.name}»", field="CRS",
                       value=reference_label(raster.crs, raster.vertical), name=record.name,
                       expected=reference_label(crs, vertical))
    yield 0.05
    return (yield from gis_views.raster_view_steps(request, raster))


def register() -> None:
    """Registra los cargadores de las tres rejillas que aún no tengan uno; idempotente."""
    current = views.loaders()
    for family, label in LOADERS:
        if prefix(family) not in current:
            views.register_loader(prefix(family), KIND, label, load_design_grid)


def unregister() -> None:
    """Quita los cargadores de las tres rejillas (el de otro con el mismo comienzo, no);
    idempotente."""
    current = views.loaders()
    for family, _label in reversed(LOADERS):
        found = current.get(prefix(family))
        if found is not None and found.load is load_design_grid:
            views.unregister_loader(prefix(family))
