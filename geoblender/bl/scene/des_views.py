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

**El recinto excavable** (spec 014, T20; HU-014-1; RF-014-01; plan 014 §5.1): el dato
``des_rcn_<nombre>`` de «Límite desde el perímetro…» («Recinto excavable», del mismo tipo
:data:`KIND`) es una zona (1 dentro, sin dato fuera), no una cota: su cargador
(:func:`load_area_grid`) lo dibuja con la misma malla **sobre su superficie de partida** (la que
guardan los ajustes de su operación, leída en su versión): un vértice en el centro de cada celda
del recinto a la cota de esa superficie, y ninguno fuera. Una partida que ya no está en la rejilla
del recinto se rechaza (``des.surface_mismatch``), y una que ya no existe, con el error de
``design.surfaces``.

**Las rejillas de una cantera con dos superficies** (spec 014, T22; HU-014-3; RF-014-15, RF-014-16;
plan 014 §5.1, §5.2.3), del mismo tipo :data:`KIND`: las dos superficies (``des_exp_<nombre>``,
«Superficie de explotación», y ``des_fin_<nombre>``, «Superficie final») y sus envolventes
(``des_xen_``, «Envolvente de explotación», y ``des_fen_``, «Envolvente final») son cotas y se
cargan como las de la 013 (:func:`load_design_grid`); así ningún diálogo las propone como el
terreno (``bl.ops.surface_proposal``). **La clasificación** (``des_cls_<nombre>``, «Clasificación»:
0 sin diferencia, 1 desdoblado, 2 relleno, sin dato fuera del dominio; P-1) no es una cota: su
cargador (:func:`load_class_grid`) la dibuja **sobre la superficie final** de su cantera (la de los
ajustes de su operación, leída en su versión), con un vértice en cada celda clasificada, y **un
color por clase** en cada cara (:data:`CLASS_LEGEND`: gris, naranja y verde), el de la mayoría de
sus tres vértices (:func:`face_classes`): el color va en el atributo de cara
:data:`COLOR_ATTRIBUTE` (y la clase, en :data:`CLASS_ATTRIBUTE`) con el material
:data:`CLASS_MATERIAL`, que lo pinta en «Vista previa del material», como la rejilla de diferencias
de la 011 (``bl.scene.res_views``). Las clases no se promedian: con un nivel de detalle, la
clasificación se carga entera y lo dice. Las cifras salen de la clasificación registrada, nunca de
la malla.

**La transición con el terreno no afectado** (spec 014, T28; RF-014-19): ``des_trn_<nombre>``
(«Transición con el terreno no afectado», del mismo tipo :data:`KIND`) es una superficie de diseño
y se carga como las cotas de la 013 (:func:`load_design_grid`).

**La superficie ajustada a un límite nuevo** (spec 014, T33; RF-014-27): cada
``des_adj_<ajuste>_<superficie>`` («Superficie ajustada a un límite nuevo», del tipo :data:`KIND`)
es también una superficie de diseño y se carga igual; con su cargador, no se propone como terreno.

**Lo que dejan los acopios y los cuerpos apoyados** (spec 016, T33; RF-016-09, RF-016-24; plan 016 §5.5): la
base (``des_stb_<detección>_<material>``), el espesor (``des_stt_…``) y el terreno sin acopios en las huellas
(``des_stg_<detección>``) de una detección, y el espesor (``des_bdt_<cuerpo>``) y la base dispersa
(``des_bds_<cuerpo>``) de un cuerpo apoyado se cargan **como cualquier superficie** (:func:`load_design_grid`):
una malla con un vértice en cada celda con dato y ninguno en las demás (P-4: están dispersas). Del tipo
:data:`KIND`, con un nombre cada una; el espesor se dibuja a su cota de «espesor» (no sobre una superficie), como
la rejilla de cotas de berma.

**Lo alcanzable de una accesibilidad** (spec 017, T31; HU-017-3; RF-017-24, RF-017-25; plan 017 §5.1; decisión T31-a: un objeto por accesibilidad, sin cadena
ni huella): ``des_acc_<nombre>`` («Lo alcanzable por las pistas», del mismo tipo :data:`KIND`) es una zona (1 alcanzable y 0 no, sin NaN), **no una cota**: su
cargador (:func:`load_access_grid`) la dibuja con la misma malla que las demás rejillas **sobre la superficie en que se calculó** (la entrada de su operación con el
papel de superficie, leída en su versión), como el recinto excavable (:func:`load_area_grid`): un vértice en el centro de cada celda alcanzable a la cota de esa
superficie y ninguno en las demás. Una superficie que ya no está en la rejilla de lo alcanzable se rechaza (``des.surface_mismatch``), y una que ya no existe, con el
error de ``design.surfaces``. Sus bermas, plataformas y zonas (``des_acb_``, ``des_acp_``, ``des_acz_``) no se cargan: la barra N las lee del proyecto.
"""

from __future__ import annotations

import json
from collections.abc import Generator

import bpy
import numpy as np

from ...core.i18n import tr
from ...core.versions import read as versions_read
from ...design import provenance as design_provenance
from ...design.model import CellClass
from ...gis.crs import reference_label
from ...gis.grid import Grid
from ...gis.mesh import MeshArrays
from ...gis.messages import GisError
from ...gis.raster import Raster
from ...gis.store import project_references
from ...gis.tin import raster_to_tin_steps
from . import gis_views, views
from .gis_views import _blocks, _scaled, _surface
from .mesh import set_attribute

__all__ = ["CLASS_ATTRIBUTE", "CLASS_LEGEND", "CLASS_MATERIAL", "COLOR_ATTRIBUTE", "KIND",
           "LOADERS", "class_colors", "ensure_class_material", "face_classes", "load_access_grid",
           "load_area_grid", "load_class_grid", "load_design_grid", "loader_of", "register",
           "unregister"]

KIND = "DESIGN"
"""El tipo (``Object.geoblender.kind``) de los objetos de las rejillas de un diseño."""
LOADERS: tuple[tuple[str, str], ...] = (
    (design_provenance.ENVELOPE_GRID, "Envelope"),
    (design_provenance.DESIGN_GRID, "Design surface"),
    (design_provenance.BERMS_GRID, "Berm elevations"),
    (design_provenance.EXCAVATION_AREA_GRID, "Excavation boundary"),
    (design_provenance.EXPLOITATION_GRID, "Exploitation surface"),
    (design_provenance.FINAL_GRID, "Final surface"),
    (design_provenance.EXPLOITATION_ENVELOPE_GRID, "Exploitation envelope"),
    (design_provenance.FINAL_ENVELOPE_GRID, "Final envelope"),
    (design_provenance.CLASSIFICATION_GRID, "Classification"),
    (design_provenance.TRANSITION_GRID, "Transition with the untouched terrain"),
    (design_provenance.REFIT_GRID, "Surface refitted to a new limit"),
    (design_provenance.STOCKPILE_BASE_GRID, "Stockpile base"),
    (design_provenance.STOCKPILE_THICKNESS_GRID, "Stockpile thickness"),
    (design_provenance.STOCKPILE_GROUND_GRID, "Ground without stockpiles"),
    (design_provenance.BODY_THICKNESS_GRID, "Body thickness"),
    (design_provenance.BODY_BASE_GRID, "Body base"),
    (design_provenance.ACCESS_GRID, "Reachable by the roads"),
    (design_provenance.PIT_POLYLINES_TABLE, "Pit TIN"),
    (design_provenance.PIT_BENCHES_TABLE, "Pit excavation solid"),
)
"""Las familias de datos que se cargan (``design.provenance``) con el ``msgid`` de su nombre en el
nombre generado de sus objetos: las tres rejillas de un diseño de la 013, el recinto excavable de
la 014 (T20), las cinco rejillas de una cantera con dos superficies (T22), la superficie con la
transición con el terreno no afectado (T28), la superficie ajustada a un límite nuevo (T33) y, de la 016
(T33; plan 016 §5.5: «como cualquier superficie»), las rejillas **dispersas** de los acopios y de los cuerpos
apoyados: la base, el espesor y el terreno sin acopios de una detección (por material, el terreno una por
detección) y el espesor y la base de un cuerpo; solo tienen dato donde hay acopio o cuerpo (sin vértice en las
demás celdas) y, de la 017 (T31), lo alcanzable de una accesibilidad (``des_acc_``: una zona, dibujada sobre su
superficie, :func:`load_access_grid`) y, de la 018 (T30), el **TIN** (``des_pbl_``) y el **sólido de excavación** (``des_pbk_``) de una corta, vistas a petición
con su aviso de triángulos (``bl.scene.pit_views``: su cargador y sus datos compañeros). La superficie con que se detectó (``des_stp_``) y la de una entidad
(``des_psf_``) no tienen cargador propio: las dibuja el objeto de la entidad (``bl.scene.entity_views``)."""
CLASS_ATTRIBUTE = "gb_class"
"""El atributo de cara con el código de su clase (``CellClass.code``: 0, 1 o 2)."""
COLOR_ATTRIBUTE = "gb_color"
"""El atributo de cara con el color lineal de su clase."""
CLASS_MATERIAL = "GB_QuarryClasses"
"""El material de la vista de la clasificación (su color, el de cada cara)."""
CLASS_LEGEND: tuple[tuple[int, tuple[float, float, float, float], str], ...] = (
    (CellClass.NONE.code, (0.5, 0.5, 0.5, 1.0), "0 · gray: no difference"),
    (CellClass.UNSPLIT.code, (0.9, 0.3, 0.02, 1.0), "1 · orange: unsplit"),
    (CellClass.FILL.code, (0.05, 0.55, 0.1, 1.0), "2 · green: restoration fill"),
)
"""La leyenda de la clasificación (RF-014-15; P-1): por clase, su código en la rejilla, su color
lineal con alfa en la vista y el ``msgid`` de su línea en la leyenda de la barra N."""
MATERIAL_VERSION = 1
"""La versión del material :data:`CLASS_MATERIAL`: cambiarlo aquí es subirla."""
VERSION_PROPERTY = "geoblender_version"
"""La propiedad de ID con la versión del material."""


def prefix(family: str) -> str:
    """El comienzo del nombre de los datos de la familia ``family`` (``des_env_``…)."""
    return design_provenance.FAMILIES_BY_CODE[family].prefix


def load_design_grid(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """La rejilla de cotas ``request.record`` de un diseño (``des_env_``, ``des_srf_`` o
    ``des_brm_``; de una cantera, ``des_exp_``, ``des_fin_``, ``des_xen_`` o ``des_fen_``) como
    malla de superficie, en pasos (véase el módulo); con ``lod`` 1 o 2, su versión de 2 o 5 m
    (RF-006-22). Cerrados antes de terminar, borra lo que creó."""
    from ...design import surfaces  # al cargar: no al habilitar

    project, record = request.project, request.record
    with project.read() as conn:
        owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
    raster = surfaces.read_surface(project, record.name, version_uid=owner)
    _check_references(project, raster, record.name)
    yield 0.05
    return (yield from gis_views.raster_view_steps(request, raster))


def load_area_grid(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """El recinto excavable ``request.record`` (``des_rcn_``) como malla de superficie sobre su
    superficie de partida, en pasos (véase el módulo; RF-014-01); con ``lod`` 1 o 2, su versión de
    2 o 5 m (RF-006-22). Cerrados antes de terminar, borra lo que creó. Solo lee."""
    from ...design import surfaces  # al cargar: no al habilitar

    project, record = request.project, request.record
    with project.read() as conn:
        owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
        row = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?",
                           (record.operation_uid,)).fetchone()
    settings = json.loads(str(row[0])) if row is not None and row[0] else {}
    _name, start = design_provenance.excavation_area_start(settings)
    area = surfaces.read_surface(project, record.name, version_uid=owner)
    _check_references(project, area, record.name)
    yield 0.02
    ground = surfaces.read_surface(project, start, version_uid=owner, expect=area,
                                   role="superficie de partida")
    yield 0.05
    with np.errstate(invalid="ignore"):
        heights = np.where(np.isfinite(area.values), ground.values, np.nan)
    shown = Raster(area.grid, heights, area.crs, area.vertical)
    return (yield from gis_views.raster_view_steps(request, shown))


def load_access_grid(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """Lo alcanzable de una accesibilidad ``request.record`` (``des_acc_``) como malla de superficie **sobre la superficie en que se calculó**, en pasos (véase el
    módulo; RF-017-24, RF-017-25): un vértice en el centro de cada celda alcanzable (1; las de 0, sin dato) a la cota de esa superficie, la entrada de su operación
    con el papel de superficie (``design.access_store.read_access_surface``), leída en su versión y comparada con la rejilla de lo alcanzable antes de leer una celda;
    con ``lod`` 1 o 2, su versión de 2 o 5 m (RF-006-22). Cerrados antes de terminar, borra lo que creó. Solo lee."""
    from ...design import access_store, surfaces  # al cargar: no al habilitar

    project, record = request.project, request.record
    with project.read() as conn:
        owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
        start = access_store.read_access_surface(conn, record.operation_uid)
    reach = surfaces.read_surface(project, record.name, version_uid=owner)
    _check_references(project, reach, record.name)
    yield 0.02
    if start is None:  # la operación no consumió ninguna superficie: un proyecto dañado (como unos ajustes sin su nombre), no una cota que inventar
        raise ValueError(f"la operación de lo alcanzable «{record.name}» no consumió ninguna superficie: no se sabe a qué cota dibujarlo")
    ground = surfaces.read_surface(project, start, version_uid=owner, expect=reach, role="superficie de la accesibilidad")
    yield 0.05
    with np.errstate(invalid="ignore"):
        heights = np.where(reach.values > 0.5, ground.values, np.nan)
    shown = Raster(reach.grid, heights, reach.crs, reach.vertical)
    return (yield from gis_views.raster_view_steps(request, shown))


def class_colors(codes: np.ndarray) -> np.ndarray:
    """El color lineal con alfa (``(n, 4)``, float32) de cada código de clase ``codes`` (0, 1 o 2:
    los de :data:`CLASS_LEGEND`). ``ValueError`` si alguno no es de una clase."""
    found = np.asarray(codes, dtype=np.int64)
    palette = {code: color for code, color, _label in CLASS_LEGEND}
    unknown = sorted(set(np.unique(found).tolist()) - set(palette))
    if unknown:
        raise ValueError(f"códigos de clase sin color: {unknown}")
    table = np.array([palette[code] for code in sorted(palette)], dtype=np.float32)
    return table[found]


def face_classes(vertex_codes: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """La clase de cada cara triangular ``faces`` (``(m, 3)``, índices de vértice): la de la
    mayoría de sus tres vértices (``vertex_codes``) o, si los tres son distintos, la del medio
    (desdoblado, entre sin diferencia y relleno); ``np.intc``."""
    corners = np.sort(np.asarray(vertex_codes, dtype=np.int64)[np.asarray(faces)], axis=1)
    return corners[:, 1].astype(np.intc)


def _cell_values(vertices: np.ndarray, grid: Grid, values: np.ndarray) -> np.ndarray:
    """El valor de ``values`` (en ``grid``) en cada vértice absoluto de una malla de A13: el de la
    celda de la que es centro."""
    columns = np.rint((vertices[:, 0] - grid.west) / grid.dx - 0.5).astype(np.int64)
    rows = np.rint((grid.north - vertices[:, 1]) / grid.dy - 0.5).astype(np.int64)
    return values[rows, columns]


def ensure_class_material() -> bpy.types.Material:
    """El material :data:`CLASS_MATERIAL` de esta versión: el que hay o uno nuevo (o rehecho en
    su sitio): su color base, el atributo :data:`COLOR_ATTRIBUTE` de la geometría; en la vista
    sólida, gris. Es un dato de la escena (se guarda con el ``.blend``), no de la extensión."""
    material = bpy.data.materials.get(CLASS_MATERIAL)
    if material is not None and material.get(VERSION_PROPERTY) == MATERIAL_VERSION:
        return material
    if material is None:
        material = bpy.data.materials.new(CLASS_MATERIAL)
    material.diffuse_color = CLASS_LEGEND[0][1]
    tree = material.node_tree
    if tree is not None:  # en 5.2 nace con el BSDF principista y la salida
        for node in list(tree.nodes):
            tree.nodes.remove(node)
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
        attribute = tree.nodes.new("ShaderNodeAttribute")
        attribute.attribute_type = "GEOMETRY"
        attribute.attribute_name = COLOR_ATTRIBUTE
        attribute.location = (-300.0, 0.0)
        output.location = (300.0, 0.0)
        tree.links.new(attribute.outputs["Color"], shader.inputs["Base Color"])
        tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    material[VERSION_PROPERTY] = MATERIAL_VERSION
    return material


def load_class_grid(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """La clasificación ``request.record`` (``des_cls_``) de una cantera como malla de superficie
    **sobre su superficie final**, con el color de su clase en cada cara (véase el módulo;
    RF-014-15), en pasos. Con ``lod`` 1 o 2 se carga entera (las clases no se promedian) y lo dice.
    Cerrados antes de terminar, borra lo que creó. Solo lee."""
    from ...design import surfaces  # al cargar: no al habilitar

    project, record = request.project, request.record
    with project.read() as conn:
        owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
        row = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?",
                           (record.operation_uid,)).fetchone()
    settings = json.loads(str(row[0])) if row is not None and row[0] else {}
    classes = surfaces.read_surface(project, record.name, version_uid=owner)
    _check_references(project, classes, record.name)
    yield 0.02
    final_name = design_provenance.dataset_name(design_provenance.FINAL_GRID,
                                                str(settings.get("name") or ""))
    final = surfaces.read_surface(project, final_name, version_uid=owner, expect=classes,
                                  role="superficie final")
    yield 0.05
    shown = np.isfinite(classes.values) & np.isfinite(final.values)
    surface = Raster(classes.grid, np.where(shown, final.values, np.nan), classes.crs,
                     classes.vertical)
    notes: list[str] = []
    if request.lod > 0:
        notes.append(tr("The classification «{name}» is loaded whole: its classes are not "
                        "averaged", name=record.name))
    yield 0.1
    tin = yield from _scaled(_blocks(raster_to_tin_steps(surface, name=record.name)), 0.1, 0.25)
    faces = np.ascontiguousarray(tin.faces, dtype=np.int32)
    codes = face_classes(_cell_values(tin.vertices, surface.grid, classes.values), faces)
    colors = class_colors(codes)
    parts = yield from _surface(request, tin, MeshArrays(tin.vertices, faces), request.name, notes,
                                0.3)
    try:
        for obj in parts.objects:
            set_attribute(obj.data, COLOR_ATTRIBUTE, "FACE", "FLOAT_COLOR", colors)
            set_attribute(obj.data, CLASS_ATTRIBUTE, "FACE", "INT", codes)
            obj.data.materials.append(ensure_class_material())
    except BaseException:
        for obj in parts.objects:
            mesh = obj.data
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)
        raise
    return parts


def _check_references(project: object, raster: Raster, name: str) -> None:
    """La vista no transforma coordenadas: ``raster`` (el dato ``name``) ha de estar en el CRS y
    la referencia vertical del proyecto (``gis.view_references_mismatch``)."""
    crs, vertical = project_references(project)
    if (raster.crs, raster.vertical) != (crs, vertical):
        raise GisError("gis.view_references_mismatch", obj=f"«{name}»", field="CRS",
                       value=reference_label(raster.crs, raster.vertical), name=name,
                       expected=reference_label(crs, vertical))


def loader_of(family: str) -> views.ViewLoader:
    """El cargador de los datos de la familia ``family`` de :data:`LOADERS`: el del recinto
    (:func:`load_area_grid`), el de la clasificación de una cantera (:func:`load_class_grid`), el de lo
    alcanzable de una accesibilidad (:func:`load_access_grid`), los del TIN y el sólido de una corta (``bl.scene.pit_views``) o el de las rejillas de cotas de un diseño
    (:func:`load_design_grid`)."""
    if family == design_provenance.EXCAVATION_AREA_GRID:
        return load_area_grid
    if family == design_provenance.CLASSIFICATION_GRID:
        return load_class_grid
    if family == design_provenance.ACCESS_GRID:
        return load_access_grid
    if family in (design_provenance.PIT_POLYLINES_TABLE, design_provenance.PIT_BENCHES_TABLE):
        from . import pit_views  # al registrar: pit_views importa este módulo

        return pit_views.load_pit_tin if family == design_provenance.PIT_POLYLINES_TABLE else pit_views.load_pit_solid
    return load_design_grid


def _companions_of(family: str) -> views.CompanionsReader | None:
    """Los datos compañeros que declara el cargador de ``family`` (el TIN y el sólido de una corta; los demás, ninguno)."""
    if family not in (design_provenance.PIT_POLYLINES_TABLE, design_provenance.PIT_BENCHES_TABLE):
        return None
    from . import pit_views  # al registrar: pit_views importa este módulo

    return pit_views.COMPANIONS[family]


def _own_title_of(family: str) -> views.OwnTitleReader | None:
    """El nombre propio que declara el cargador de ``family`` (el TIN y el sólido de una corta se llaman como la corta; los demás, ninguno)."""
    if family not in (design_provenance.PIT_POLYLINES_TABLE, design_provenance.PIT_BENCHES_TABLE):
        return None
    from . import pit_views  # al registrar: pit_views importa este módulo

    return pit_views.OWN_TITLES[family]


def register() -> None:
    """Registra los cargadores de :data:`LOADERS` que aún no tengan uno; idempotente."""
    current = views.loaders()
    for family, label in LOADERS:
        if prefix(family) not in current:
            views.register_loader(prefix(family), KIND, label, loader_of(family), companions=_companions_of(family), own_title=_own_title_of(family))


def unregister() -> None:
    """Quita los cargadores de :data:`LOADERS` (el de otro con el mismo comienzo, no);
    idempotente."""
    current = views.loaders()
    for family, _label in reversed(LOADERS):
        found = current.get(prefix(family))
        if found is not None and found.load is loader_of(family):
            views.unregister_loader(prefix(family))
