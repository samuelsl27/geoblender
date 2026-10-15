# SPDX-License-Identifier: GPL-3.0-or-later
"""Los tubos de los sondeos: el grupo de Geometry Nodes ``GB_DrillTubes`` y el material de su
vista (spec 005, T29; RF-005-23, RF-005-24; plan 005 §5.1, §5.4 «Vista» y §5.6.8; D9 del plan;
ADR-0011: prefijo ``GB_`` de los grupos).

La vista de los sondeos (``bl.scene.dh_view``) dibuja la litología como curvas ``POLY`` (una por
tramo, con el color lineal de su litología en el atributo de punto ``gb_color``) y les pone el
modificador de Geometry Nodes de este grupo (:func:`add_tubes`): cada curva pasa a un tubo
(``Curve to Mesh`` con un círculo de :data:`PROFILE_RESOLUTION` lados) del radio de su entrada
``Radius`` (en m: el de la representación, que se cambia en vivo sin reconstruir nada,
:func:`set_tube_radius`), con el material :data:`MATERIAL_NAME`. Los atributos de las curvas
llegan a la malla de los tubos (``gb_color``, como atributo de color: lo comprobó el plan en
5.2.1, §2.1).

El **material** (:func:`ensure_material`) pinta con el atributo ``gb_color`` de la geometría
(nodo «Atributo» al color base): en «Vista previa del material», los tubos y las barras de leyes
(su ``gb_color`` es de cara) con el color de su litología o de su clase, con los contactos
nítidos (M3).

El grupo y el material son **datos de la escena** (se guardan con el ``.blend``, regenerables;
plan §3, principio 8), no estado de la extensión: desactivar Geoblender no los quita. Están
**versionados en el código** (:data:`VERSION`, en su propiedad de ID
:data:`VERSION_PROPERTY`): :func:`ensure_group` y :func:`ensure_material` devuelven los que hay
si son de esta versión y, si no (de otra versión o tocados a mano sin ella), los rehacen en su
sitio, así que los objetos que los usan siguen con ellos. Las entradas del modificador, con
``bl.compat`` (en 5.2, ``mod.properties.inputs.Socket_N.value``).
"""

from __future__ import annotations

from typing import Any

import bpy

from .. import compat

__all__ = [
    "COLOR_ATTRIBUTE",
    "GROUP_NAME",
    "MATERIAL_NAME",
    "PROFILE_RESOLUTION",
    "RADIUS_INPUT",
    "VERSION",
    "VERSION_PROPERTY",
    "add_tubes",
    "ensure_group",
    "ensure_material",
    "set_tube_radius",
    "tube_radius",
]

GROUP_NAME = "GB_DrillTubes"
"""El nombre del grupo de Geometry Nodes de los tubos (y de su modificador)."""
MATERIAL_NAME = "GB_Drillholes"
"""El nombre del material de la vista de los sondeos (tubos y barras)."""
VERSION = 1
"""La versión del grupo y del material: cambiarlos aquí es subirla."""
VERSION_PROPERTY = "geoblender_version"
"""La propiedad de ID con la versión del grupo y del material."""
COLOR_ATTRIBUTE = "gb_color"
"""El atributo con el color lineal de cada punto de las curvas (o de cada cara de las barras)."""
RADIUS_INPUT = "Radius"
"""El nombre de la entrada del grupo con el radio de los tubos (m)."""
PROFILE_RESOLUTION = 8
"""Los lados del círculo de la sección de los tubos."""
DEFAULT_RADIUS_M = 0.5
"""El radio por defecto de la entrada del grupo (el de la representación, por defecto)."""
_GRAY = (0.5, 0.5, 0.5, 1.0)


def _current(item: Any) -> bool:
    return item is not None and item.get(VERSION_PROPERTY) == VERSION


def ensure_material() -> bpy.types.Material:
    """El material de la vista de los sondeos (:data:`MATERIAL_NAME`) de esta versión: el que
    hay o uno nuevo (o rehecho en su sitio): su color base, el atributo :data:`COLOR_ATTRIBUTE`
    de la geometría; en la vista sólida, gris."""
    material = bpy.data.materials.get(MATERIAL_NAME)
    if _current(material):
        return material
    if material is None:
        material = bpy.data.materials.new(MATERIAL_NAME)
    material.diffuse_color = _GRAY
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
    material[VERSION_PROPERTY] = VERSION
    return material


def _radius_socket(group: bpy.types.NodeTree) -> Any:
    """La entrada :data:`RADIUS_INPUT` de ``group`` (``None`` si no la tiene)."""
    return next((item for item in group.interface.items_tree
                 if getattr(item, "in_out", None) == "INPUT"
                 and item.name == RADIUS_INPUT), None)


def ensure_group() -> bpy.types.NodeTree:
    """El grupo de Geometry Nodes de los tubos (:data:`GROUP_NAME`) de esta versión: el que
    hay o uno nuevo (o rehecho en su sitio): la geometría (las curvas) a ``Curve to Mesh`` con
    un círculo de radio 1 y :data:`PROFILE_RESOLUTION` lados como sección, escalado por la
    entrada :data:`RADIUS_INPUT`, y el material de la vista (:func:`ensure_material`)."""
    group = bpy.data.node_groups.get(GROUP_NAME)
    if _current(group) and _radius_socket(group) is not None:
        return group
    material = ensure_material()
    if group is None:
        group = bpy.data.node_groups.new(GROUP_NAME, "GeometryNodeTree")
    group.interface.clear()
    group.nodes.clear()
    interface = group.interface
    interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    radius = interface.new_socket(RADIUS_INPUT, in_out="INPUT", socket_type="NodeSocketFloat")
    radius.default_value = DEFAULT_RADIUS_M
    radius.min_value = 0.0
    interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = group.nodes, group.links
    inputs = nodes.new("NodeGroupInput")
    circle = nodes.new("GeometryNodeCurvePrimitiveCircle")
    circle.mode = "RADIUS"
    circle.inputs["Resolution"].default_value = PROFILE_RESOLUTION
    circle.inputs["Radius"].default_value = 1.0
    tubes = nodes.new("GeometryNodeCurveToMesh")
    painted = nodes.new("GeometryNodeSetMaterial")
    painted.inputs["Material"].default_value = material
    outputs = nodes.new("NodeGroupOutput")
    for x, node in enumerate((inputs, circle, tubes, painted, outputs)):
        node.location = (x * 220.0 - 440.0, 0.0)
    links.new(inputs.outputs[0], tubes.inputs["Curve"])
    links.new(circle.outputs["Curve"], tubes.inputs["Profile Curve"])
    links.new(inputs.outputs[1], tubes.inputs["Scale"])
    links.new(tubes.outputs["Mesh"], painted.inputs["Geometry"])
    links.new(painted.outputs["Geometry"], outputs.inputs[0])
    group[VERSION_PROPERTY] = VERSION
    return group


def _modifier(obj: bpy.types.Object) -> Any:
    """El modificador de los tubos de ``obj`` (``None`` si no lo tiene)."""
    return next((modifier for modifier in obj.modifiers if modifier.type == "NODES"
                 and modifier.node_group is not None
                 and modifier.node_group.name == GROUP_NAME), None)


def add_tubes(obj: bpy.types.Object, radius_m: float) -> bpy.types.Modifier:
    """Pone a ``obj`` (un objeto de curvas) el modificador de los tubos (:func:`ensure_group`)
    con el radio ``radius_m`` (m); si ya lo tiene, solo le cambia el radio."""
    modifier = _modifier(obj)
    if modifier is None:
        modifier = obj.modifiers.new(GROUP_NAME, "NODES")
        modifier.node_group = ensure_group()
    set_tube_radius(obj, radius_m)
    return modifier


def tube_radius(obj: bpy.types.Object) -> float | None:
    """El radio (m) de los tubos de ``obj``; ``None`` si no tiene su modificador."""
    modifier = _modifier(obj)
    if modifier is None:
        return None
    socket = _radius_socket(modifier.node_group)
    return float(compat.modifier_input(modifier, socket.identifier))  # type: ignore[arg-type]


def set_tube_radius(obj: bpy.types.Object, radius_m: float) -> None:
    """Cambia el radio (m) de los tubos de ``obj`` (sin reconstruir nada: lo evalúa Blender).
    ``ValueError`` si ``obj`` no tiene su modificador."""
    modifier = _modifier(obj)
    if modifier is None:
        raise ValueError(f"«{obj.name}» no tiene los tubos de los sondeos ({GROUP_NAME})")
    socket = _radius_socket(modifier.node_group)
    compat.set_modifier_input(modifier, socket.identifier, float(radius_m))
