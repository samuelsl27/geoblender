# SPDX-License-Identifier: GPL-3.0-or-later
"""El estilo por tipo de las capas de restricciones en ``layer_styles`` (spec 012, T20; RF-012-20,
RF-008-62; plan 012 D-32).

QGIS 4.2 aplica sin preguntar el estilo **por defecto** que una capa de un GeoPackage tiene en la
tabla ``layer_styles``: la capa de restricciones se abre desde el GeoPackage del proyecto con su
estilo por tipo y sin hacer nada. Este módulo lo escribe, en la misma transacción que crea las
capas (:func:`write_styles`, que llaman las operaciones de :mod:`.provenance`), y lo declara como
dato de ``core`` (:func:`dataset_spec`, ``core_layer_styles``, ``layer_styles`` en
``project.gpkg``, editable a mano: QGIS la escribe al guardar un estilo) para que la
comprobación de la 008 no la avise como «tabla sin registrar» (RF-008-62). Anticipa una parte de
R-73 solo para estas capas (D-32).

**El estilo** (:func:`style_for`, uno por capa: polígonos, líneas, puntos): un renderizador por
reglas (``RuleRenderer``) con una regla por tipo, en el orden de
:class:`~.model.ConstraintType` (``"ctype" = '<tipo>'``, con su nombre en español), y una última,
``ELSE``, para lo sin tipo (la restricción incompleta, dibujada en QGIS). Cada tipo tiene un color
(:data:`COLORS`): el contorno de los polígonos, la línea o el punto; los polígonos van rellenos
con ese color translúcido salvo los límites (legal y de actuación), que solo llevan contorno para
no tapar lo que rodean. Los colores van como ``r,g,b,a`` (QGIS lee ``#rrggbbaa`` como
``#AARRGGBB``: ``docs/trampas.md`` §6). Solo la simbología (``styleCategories="Symbology"``): no
toca las demás propiedades de la capa. Los textos que ve la persona en QGIS, en español.

**La tabla** tiene el esquema que crea QGIS 4.2 al guardar un estilo en un GeoPackage (el mismo de
``gis.vector``, que el nivel 0 no puede importar; una prueba comprueba que son iguales) y se
registra en ``gpkg_contents`` como ``attributes``. :func:`write_styles` solo escribe el estilo de
una capa que no tiene ya uno por defecto: repetirla no duplica y lo que guardó QGIS se respeta.

**Las capas de una versión** (spec 015, T22; RF-012-20, RF-015-27, RF-009-05; plan 015 §5.7, §5.8 y §8):
``des_decl_<vNN>`` (las restricciones que declaran las entidades de la versión, :mod:`.declared`) y
``des_enl_<vNN>`` (la capa de entidades de ``design``, T30) son de **una versión**, no editables a mano
(RF-008-56) y se abren en QGIS con su estilo por defecto igual que las del proyecto.
:func:`style_for` da el de cada una (:class:`VersionLayer`): la de las declaradas, **el mismo** por tipo
que la de polígonos del proyecto (:data:`COLORS`); la de entidades, por tipo de entidad (``kind``) y por
estado (``state``: la descartada, atenuada; la de «apoyo retirado», marcada), sobre los campos que fija
:data:`ENTITY_FIELDS` (el contrato con la tabla que escribe ``design``: ``kind``, ``name``, ``state``,
``supports`` y ``chain``, más ``fid`` y la geometría ``geom``, más lo que quiera añadir). **La marca «no
editable»** es lo que QGIS 4.2 admite en un estilo por defecto (comprobado con PyQGIS 4.2.0): en la
categoría de formularios (``Forms``), ``<editable><field name="…" editable="0"/></editable>`` con **todos**
los campos de la capa (QGIS los da por de solo lectura en el formulario y en la tabla de atributos), y en la
de notas (``Notes``) la nota de la capa, que QGIS enseña en el panel de capas, con el porqué. La marca de
**capa** de solo lectura (``readOnly`` del QML, ``QgsVectorLayer.setReadOnly``) **no viaja en el estilo**: QGIS
4.2 la guarda en el proyecto de QGIS y la ignora al aplicar un estilo; la protección de la capa entera es la de
RF-008-56 (``qgis_editable=False``: si se edita, se bloquea y no se compila con ella). Sin las categorías de
campos (``Fields``) ni de las demás: el resto de la capa (sus listas de valores, alias) queda como está.

**La capa de ejes de pistas** (spec 017, T26; RF-017-27, D-19): ``des_rax_<vNN>`` (``design.road_layer``) es de **una versión**, no editable a mano y se
abre en QGIS con su estilo **por clase** (:class:`VersionLayer` ``ROADS``): líneas, con una categoría por cada clase normativa (el campo ``class_name``)
y por estado —la descartada, atenuada; la de «apoyo retirado», marcada— y «otra clase» para la que el estilo no conoce, sobre los campos de
:data:`ROAD_FIELDS`. **Las clases son abiertas** (el texto de un perfil de pista): salen de la propia tabla al escribir el estilo
(:func:`insert_version_styles`) y, si aparece una clase nueva, **el estilo que escribió Geoblender se rehace** con ella (lo reconoce por su nombre,
:data:`ROAD_STYLE_NAME`); el que guardó una persona desde QGIS, con otro nombre, no se toca nunca.

**Una operación de versión no escribe ``core_layer_styles`` como salida** (RF-009-05: sus salidas son de su
versión; el dato es del proyecto, de la operación de la 012 que lo creó): :func:`write_version_styles` escribe
la fila de ``layer_styles`` **en la transacción de la operación que escribe la capa** (si falla, no queda
nada) y **anota** el dato (``registry.note_content``: su hash y su seguimiento al día, y su cambio en la
historia con esa operación) para que la comprobación de datos no lo tome por una edición hecha fuera de
Geoblender (RF-008-21). Si ya había una edición sin comprobar, no la da por buena: la comprobación sigue
viéndola. Sin ``layer_styles`` (ninguna operación de la 012 la creó) no se crea aquí: quedaría como «tabla sin
registrar» (RF-008-62); lo escribe la declaración siguiente.

Python puro (``core``).
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from ..content.builtin import GPKG_LAYER
from ..datasets import DatasetSpec, Store
from ..datasets import registry as dataset_registry
from ..datasets import tracking as dataset_tracking
from ..datasets.external import Signal, probe_dataset
from ..datasets.model import DatasetRecord, DatasetStatus
from .declared import COLUMN_NAMES as DECLARED_COLUMNS
from .declared import DATASET_NAME as DECLARED_LAYER
from .model import ConstraintType
from .store import CONSTRAINT_LAYERS

__all__ = [
    "COLORS",
    "DECLARED_LAYER",
    "DECLARED_STYLE_NAME",
    "ELSE_COLOR",
    "ELSE_LABEL",
    "ENTITY_FADED_STATES",
    "ENTITY_FIELDS",
    "ENTITY_KINDS",
    "ENTITY_LAYER",
    "ENTITY_MARKED_STATES",
    "ENTITY_OTHER_COLOR",
    "ENTITY_OTHER_LABEL",
    "ENTITY_STYLE_NAME",
    "FILL_ALPHA",
    "MARK_COLOR",
    "QGIS_VERSION",
    "ROAD_CLASS_COLORS",
    "ROAD_FIELDS",
    "ROAD_LAYER",
    "ROAD_OTHER_COLOR",
    "ROAD_OTHER_LABEL",
    "ROAD_STYLE_NAME",
    "STYLES_DATASET",
    "STYLES_TABLE",
    "StyleRow",
    "VersionLayer",
    "dataset_spec",
    "insert_version_styles",
    "style_for",
    "version_layer",
    "write_styles",
    "write_version_styles",
]

STYLES_TABLE = "layer_styles"
"""La tabla de los estilos de QGIS de un GeoPackage (la que QGIS lee al añadir una capa)."""
STYLES_DATASET = "core_layer_styles"
"""El dato de ``core`` que la registra."""
QGIS_VERSION = "4.2.0"
"""La versión de QGIS con la que se comprobó el QML (la que lo escribe en su cabecera)."""
STYLE_NAME = "Restricciones por tipo"
STYLE_DESCRIPTION = "Geoblender: un color por tipo de restricción (reglas sobre el campo ctype)"
ELSE_LABEL = "Sin tipo (incompleta)"
"""La regla de lo que no tiene tipo."""
GEOMETRY_COLUMN = "geom"

COLORS: Mapping[ConstraintType, tuple[int, int, int]] = MappingProxyType({
    ConstraintType.LEGAL_LIMIT: (20, 60, 150),
    ConstraintType.ACTION_PERIMETER: (30, 150, 60),
    ConstraintType.UNTOUCHABLE: (200, 20, 20),
    ConstraintType.EXCLUSION: (140, 20, 100),
    ConstraintType.NO_CUT: (230, 130, 20),
    ConstraintType.FILL_ONLY: (40, 120, 220),
    ConstraintType.RESTORATION_ONLY: (120, 80, 170),
    ConstraintType.SETBACK: (200, 180, 40),
    ConstraintType.NO_FILL: (110, 160, 40),
    ConstraintType.AVOID: (245, 175, 60),
    ConstraintType.REQUIRES_ACCESS: (60, 160, 170),
})
"""El color de cada tipo (``r, g, b``): contorno, línea o punto."""
ELSE_COLOR = (130, 130, 130)
"""El de lo sin tipo."""
_OUTLINE_ONLY = (ConstraintType.LEGAL_LIMIT, ConstraintType.ACTION_PERIMETER)
FILL_ALPHA = 110
"""La opacidad (0 a 255) del relleno de un polígono con relleno."""
_ELSE_ALPHA = 60
_LIMIT_MM = 0.9
_OUTLINE_MM = 0.5
_LINE_MM = 0.7
_POINT_MM = 3.5

ENTITY_LAYER = "des_enl"
"""El nombre del dato de la capa de entidades de la versión (``des_enl_<vNN>`` es su ubicación): el mismo
que ``design.provenance.dataset_name("enl")`` (``core`` no importa ``design``; una prueba lo comprueba)."""
DECLARED_STYLE_NAME = "Restricciones declaradas"
"""El nombre del estilo de las declaradas (como mucho 30 caracteres, ``TEXT(30)`` de QGIS)."""
ENTITY_STYLE_NAME = "Entidades de diseño"
"""El nombre del estilo de la capa de entidades."""
ROAD_LAYER = "des_rax"
"""El nombre del dato de la capa de ejes de pistas de la versión (``des_rax_<vNN>`` es su ubicación; spec 017, T26): el mismo que ``design.provenance.dataset_name("rax")`` (``core`` no importa
``design``; una prueba lo comprueba)."""
ROAD_STYLE_NAME = "Ejes de pistas"
"""El nombre del estilo de la capa de ejes de pistas (como mucho 30 caracteres): por él se reconoce el que escribió Geoblender."""
ROAD_FIELDS: tuple[str, ...] = ("code", "name", "class_name", "state", "profile")
"""Los campos de la capa de ejes de pistas que el estilo conoce (el contrato con la tabla ``des_rax_<vNN>`` de ``design``, T26): el código de la pista, su nombre, su clase normativa (``class_name``: por
ella se pinta), su estado (``EntityState``) y su perfil. La tabla lleva más (las cifras): el estilo marca de solo lectura los que la tabla tiene de verdad."""
ROAD_OTHER_LABEL = "Otra clase"
"""El nombre de las pistas de una clase que el estilo no conoce (una clase que apareció después de escribirlo)."""
ROAD_OTHER_COLOR = (110, 110, 110)
"""Su color."""
ROAD_CLASS_COLORS: tuple[tuple[int, int, int], ...] = (
    (0, 114, 178), (213, 94, 0), (0, 158, 115), (204, 121, 167), (230, 159, 0), (86, 180, 233))
"""El color de cada clase, por su orden (la paleta de Okabe e Ito, legible con daltonismo); con más clases que colores, vuelve al primero."""
_ROAD_DESCRIPTION = ("Geoblender: un color por clase normativa de pista; la descartada, atenuada, y la de apoyo retirado, marcada "
                     "(no se edita a mano)")
_ROAD_NOTE = ("Ejes de las pistas de esta versión (Geoblender): líneas con la rasante en su Z, que Geoblender regenera tras cada orden de "
              "pistas; no se edita a mano, se cambian en la pista. Si la edita, Geoblender la bloquea.")
_ROAD_LINE_MM = 0.9
_ROAD_FADED_MM = 0.4
_ROAD_MARK_MM = 1.4
_DECLARED_DESCRIPTION = ("Geoblender: el estilo por tipo de las restricciones del proyecto, para las que "
                         "declaran las entidades de diseño (no se editan a mano)")
_ENTITY_DESCRIPTION = ("Geoblender: un color por tipo de entidad de diseño; la descartada, atenuada, y la de "
                       "apoyo retirado, marcada (no se edita a mano)")
_DECLARED_NOTE = ("Restricciones declaradas por las entidades de diseño de esta versión (Geoblender): no se "
                  "edita a mano, se cambian en la entidad. Si edita esta capa, Geoblender la bloquea y no "
                  "compila las máscaras con ella hasta que acepte la edición con un motivo o la entidad la "
                  "vuelva a poner.")
_ENTITY_NOTE = ("Entidades de diseño de esta versión (Geoblender): la regenera Geoblender tras cada orden "
                "de entidades y no se edita a mano; si la edita, Geoblender la bloquea.")
VERSION_CATEGORIES = "Symbology|Forms|Notes"
"""Las categorías del estilo de una capa de versión: la simbología, los formularios (la editabilidad de
sus campos) y las notas de la capa. Sin ``Fields`` ni las demás: lo que ya tiene la capa no se toca."""

ENTITY_FIELDS: tuple[str, ...] = ("kind", "name", "state", "supports", "chain")
"""Los campos de la capa de entidades que el estilo conoce (el contrato con la tabla ``des_enl_<vNN>`` de
``design``, T30): ``kind`` (el tipo de la entidad: ``EntityKind``), ``name``, ``state`` (``EntityState``),
``supports`` y ``chain``. La tabla puede llevar más (las cifras principales): el estilo marca de solo
lectura los que la tabla tiene de verdad (:func:`insert_version_styles`)."""
ENTITY_KINDS: Mapping[str, tuple[str, tuple[int, int, int]]] = MappingProxyType({
    "platform": ("Plataforma", (176, 96, 64)),
    "stockpile": ("Acopio", (217, 140, 26)),
    "removal": ("Retirada", (204, 77, 64)),
    "buttress": ("Contrafuerte", (128, 102, 204)),
    "body": ("Cuerpo apoyado", (77, 140, 217)),
    "road": ("Pista", (118, 118, 118)),
    "access": ("Accesibilidad", (51, 166, 153)),
    "pit": ("Corta", (166, 77, 128)),
})
"""Los tipos de entidad con estilo propio: el valor de ``kind`` → (su nombre en español, su color ``r, g, b``). Los cuatro de
la 016 (spec 016, T35; decisión del 19/11/2026) llevan **los colores de los objetos de la vista** (``bl.scene.entity_views.COLORS``, de 0 a 1,
a 0 a 255): la fila de un acopio de una detección, la retirada, el contrafuerte y el cuerpo apoyado. Un tipo que no esté aquí se dibuja como
«otra entidad». De la 017 (T03), la pista (gris: sale en la capa con su huella) y la accesibilidad (sin huella: no tiene filas en la
capa; el contrato con ``design.entities.EntityKind`` pide un estilo por tipo y esta es la del día en que tenga alguna)."""
ENTITY_OTHER_LABEL = "Otra entidad"
"""El nombre de las entidades de un tipo que aún no tiene estilo propio."""
ENTITY_OTHER_COLOR = (110, 110, 140)
"""Su color."""
ENTITY_FADED_STATES: tuple[str, ...] = ("discarded",)
"""Los estados (``state``) que se dibujan atenuados: la entidad descartada («registro, no usar»)."""
ENTITY_MARKED_STATES: tuple[str, ...] = ("support_removed",)
"""Los estados que se dibujan marcados: la entidad con el apoyo retirado (RF-015-17)."""
_FADED_LABEL = "descartada"
_MARKED_LABEL = "con el apoyo retirado"
MARK_COLOR = (200, 20, 20)
"""El color del contorno de lo marcado (``r, g, b``)."""
_FADED_FILL_ALPHA = 30
_FADED_OUTLINE_ALPHA = 110
_FADED_MM = 0.3
_MARK_MM = 1.2

# Como la crea QGIS 4.2 al guardar un estilo en un GeoPackage (comprobado con PyQGIS 4.2.0); el
# mismo texto que ``gis.vector._STYLES_DDL``.
_STYLES_DDL = (
    f'CREATE TABLE "{STYLES_TABLE}" ( "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, '
    '"f_table_catalog" TEXT(256), "f_table_schema" TEXT(256), "f_table_name" TEXT(256), '
    '"f_geometry_column" TEXT(256), "styleName" TEXT(30), "styleQML" TEXT, "styleSLD" TEXT, '
    '"useAsDefault" BOOLEAN, "description" TEXT, "owner" TEXT(30), "ui" TEXT(30), '
    '"update_time" DATETIME DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%fZ\',\'now\')))'
)
_STYLES_INSERT = (
    f'INSERT INTO "{STYLES_TABLE}" (f_table_catalog, f_table_schema, f_table_name, '
    "f_geometry_column, styleName, styleQML, styleSLD, useAsDefault, description, owner) "
    "VALUES ('', '', ?, ?, ?, ?, '', 1, ?, '')"
)


@dataclass(frozen=True, slots=True)
class StyleRow:
    """El estilo por defecto de una capa: su nombre (como mucho 30 caracteres, ``TEXT(30)`` de
    QGIS), su descripción y el documento QML entero."""

    name: str
    description: str
    qml: str


# --- El QML --------------------------------------------------------------------------------


def _color(rgb: tuple[int, int, int], alpha: int = 255) -> str:
    return f"{rgb[0]},{rgb[1]},{rgb[2]},{alpha}"


def _symbol(index: int, kind: str, layer_class: str, options: Iterable[tuple[str, str]]) -> str:
    lines = "\n".join(f'      <Option name="{key}" type="QString" value="{value}"/>'
                      for key, value in options)
    return (f'   <symbol type="{kind}" name="{index}" alpha="1" clip_to_extent="1" '
            'force_rhr="0">\n'
            f'    <layer class="{layer_class}" enabled="1" locked="0" pass="0">\n'
            '     <Option type="Map">\n'
            f"{lines}\n"
            "     </Option>\n"
            "    </layer>\n"
            "   </symbol>")


def _fill(index: int, rgb: tuple[int, int, int], *, outline_only: bool, alpha: int,
          dashed: bool, width_mm: float) -> str:
    return _symbol(index, "fill", "SimpleFill", (
        ("color", _color(rgb, alpha)), ("joinstyle", "bevel"),
        ("outline_color", _color(rgb)), ("outline_style", "dash" if dashed else "solid"),
        ("outline_width", f"{width_mm:g}"), ("outline_width_unit", "MM"),
        ("style", "no" if outline_only else "solid")))


def _line(index: int, rgb: tuple[int, int, int], *, dashed: bool) -> str:
    return _symbol(index, "line", "SimpleLine", (
        ("capstyle", "round"), ("joinstyle", "round"), ("line_color", _color(rgb)),
        ("line_style", "dash" if dashed else "solid"), ("line_width", f"{_LINE_MM:g}"),
        ("line_width_unit", "MM")))


def _marker(index: int, rgb: tuple[int, int, int], *, alpha: int) -> str:
    return _symbol(index, "marker", "SimpleMarker", (
        ("color", _color(rgb, alpha)), ("name", "circle"), ("outline_color", _color(rgb)),
        ("outline_style", "solid"), ("outline_width", f"{_OUTLINE_MM:g}"),
        ("outline_width_unit", "MM"), ("size", f"{_POINT_MM:g}"), ("size_unit", "MM")))


def _rule_key(table_index: int, rule_index: int) -> str:
    return f"{{5a1c0e00-{table_index:04x}-4e8b-9a51-6d2e7c1b{rule_index:04x}}}"


def _by_type(table_index: int, kind: str) -> tuple[str, str]:
    """Las reglas (una por tipo de restricción en el orden de :class:`~.model.ConstraintType` y la de lo
    sin tipo) y los símbolos de una capa de restricciones de la geometría ``kind`` (``fill``, ``line`` o
    ``marker``): las líneas ya unidas, las reglas y los símbolos."""
    rules = []
    symbols = []
    items: list[tuple[ConstraintType | None, str, tuple[int, int, int]]] = [
        (ctype, f"&quot;ctype&quot; = '{ctype.value}'", COLORS[ctype]) for ctype in ConstraintType]
    items.append((None, "ELSE", ELSE_COLOR))
    for index, (ctype, condition, rgb) in enumerate(items):
        label = ELSE_LABEL if ctype is None else ctype.label("es")
        rules.append(f'   <rule key="{_rule_key(table_index, index + 1)}" filter="{condition}" '
                     f'label="{label}" symbol="{index}"/>')
        if kind == "fill":
            symbols.append(_fill(index, rgb, outline_only=ctype in _OUTLINE_ONLY,
                                 alpha=_ELSE_ALPHA if ctype is None else FILL_ALPHA,
                                 dashed=ctype is None,
                                 width_mm=_LIMIT_MM if ctype in _OUTLINE_ONLY else _OUTLINE_MM))
        elif kind == "line":
            symbols.append(_line(index, rgb, dashed=ctype is None))
        else:
            symbols.append(_marker(index, rgb, alpha=_ELSE_ALPHA if ctype is None else 200))
    return "\n".join(rules), "\n".join(symbols)


_DOCTYPE = "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"


def _renderer(table_index: int, rule_lines: str, symbol_lines: str) -> str:
    """El renderizador por reglas de una capa: sus reglas y sus símbolos."""
    return (
        ' <renderer-v2 type="RuleRenderer" symbollevels="0" enableorderby="0" '
        'forceraster="0" referencescale="-1">\n'
        f'  <rules key="{_rule_key(table_index, 0)}">\n'
        f"{rule_lines}\n"
        "  </rules>\n"
        "  <symbols>\n"
        f"{symbol_lines}\n"
        "  </symbols>\n"
        " </renderer-v2>\n"
    )


def _qml(table: str) -> str:
    tables = tuple(CONSTRAINT_LAYERS.values())
    table_index = tables.index(table) + 1
    kind = {tables[0]: "fill", tables[1]: "line", tables[2]: "marker"}[table]
    rule_lines, symbol_lines = _by_type(table_index, kind)
    return (
        f"{_DOCTYPE}"
        f'<qgis version="{QGIS_VERSION}" styleCategories="Symbology">\n'
        f"{_renderer(table_index, rule_lines, symbol_lines)}"
        "</qgis>\n"
    )


# --- El QML de las capas de una versión ------------------------------------------------------


class VersionLayer(StrEnum):
    """Las capas de una versión que tienen estilo: las restricciones que declaran las entidades
    (``des_decl_<vNN>``), la capa de entidades (``des_enl_<vNN>``) y, de la 017 (T26), la capa de ejes de pistas
    (``des_rax_<vNN>``)."""

    DECLARED = "declared"
    ENTITIES = "entities"
    ROADS = "roads"


_VERSION_LAYER = re.compile(rf"(?P<layer>{DECLARED_LAYER}|{ENTITY_LAYER}|{ROAD_LAYER})_v[0-9]+")
_LAYER_OF_NAME = {DECLARED_LAYER: VersionLayer.DECLARED, ENTITY_LAYER: VersionLayer.ENTITIES, ROAD_LAYER: VersionLayer.ROADS}
_TABLE_INDEX = {VersionLayer.DECLARED: 4, VersionLayer.ENTITIES: 5, VersionLayer.ROADS: 6}
"""El número de capa de las claves de regla de cada capa de versión (1 a 3: las del proyecto)."""


def version_layer(table: object) -> VersionLayer | None:
    """La capa de versión que es la tabla ``table`` (``des_decl_v01``, ``des_enl_v12`` o ``des_rax_v03``: la ubicación
    de ``des_decl``, ``des_enl`` y ``des_rax`` con el código de la versión, ``core.versions.model.version_locator``) o
    ``None`` si no es de ninguna (lo que no es un texto, tampoco)."""
    found = _VERSION_LAYER.fullmatch(table) if isinstance(table, str) else None
    if found is None:
        return None
    return _LAYER_OF_NAME[found["layer"]]


def _attr(text: str) -> str:
    """``text`` como valor de un atributo XML entre comillas dobles."""
    return text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _version_qml(layer: VersionLayer, rule_lines: str, symbol_lines: str, note: str,
                 fields: Sequence[str]) -> str:
    """El documento QML de una capa de versión: la simbología, la nota de la capa y la editabilidad (``0``)
    de **cada** campo de ``fields``."""
    editable = "\n".join(f'  <field name="{_attr(name)}" editable="0"/>' for name in fields)
    return (
        f"{_DOCTYPE}"
        f'<qgis version="{QGIS_VERSION}" styleCategories="{VERSION_CATEGORIES}">\n'
        f"{_renderer(_TABLE_INDEX[layer], rule_lines, symbol_lines)}"
        f' <userNotes value="{_attr(note)}"/>\n'
        " <editable>\n"
        f"{editable}\n"
        " </editable>\n"
        "</qgis>\n"
    )


def _state_condition(states: Sequence[str]) -> str:
    quoted = ", ".join(f"'{state}'" for state in states)
    return f"&quot;state&quot; = {quoted}" if len(states) == 1 else f"&quot;state&quot; IN ({quoted})"


def _entity_symbol(index: int, rgb: tuple[int, int, int], *, fill_alpha: int,
                   outline: tuple[int, int, int], outline_alpha: int, style: str,
                   width_mm: float) -> str:
    return _symbol(index, "fill", "SimpleFill", (
        ("color", _color(rgb, fill_alpha)), ("joinstyle", "bevel"),
        ("outline_color", _color(outline, outline_alpha)), ("outline_style", style),
        ("outline_width", f"{width_mm:g}"), ("outline_width_unit", "MM"), ("style", "solid")))


def _entity_rules() -> tuple[str, str]:
    """Las reglas (seis: cada tipo con estilo propio y «otra entidad», cada una normal, descartada y con el
    apoyo retirado) y los símbolos de la capa de entidades. Las reglas no se solapan (una entidad
    recibe un solo símbolo)."""
    known = ", ".join(f"'{kind}'" for kind in ENTITY_KINDS)
    special = ", ".join(f"'{state}'" for state in (*ENTITY_FADED_STATES, *ENTITY_MARKED_STATES))
    kinds: list[tuple[str, str, tuple[int, int, int]]] = [
        (label, f"&quot;kind&quot; = '{kind}'", rgb) for kind, (label, rgb) in ENTITY_KINDS.items()]
    kinds.append((ENTITY_OTHER_LABEL, f"coalesce(&quot;kind&quot;, '') NOT IN ({known})",
                  ENTITY_OTHER_COLOR))
    rules = []
    symbols = []
    index = 0
    for label, of_kind, rgb in kinds:
        variants = (
            (label, f"{of_kind} AND coalesce(&quot;state&quot;, '') NOT IN ({special})",
             _entity_symbol(index, rgb, fill_alpha=FILL_ALPHA, outline=rgb, outline_alpha=255,
                            style="solid", width_mm=_OUTLINE_MM)),
            (f"{label} {_FADED_LABEL}", f"{of_kind} AND {_state_condition(ENTITY_FADED_STATES)}",
             _entity_symbol(index + 1, rgb, fill_alpha=_FADED_FILL_ALPHA, outline=rgb,
                            outline_alpha=_FADED_OUTLINE_ALPHA, style="dash", width_mm=_FADED_MM)),
            (f"{label} {_MARKED_LABEL}", f"{of_kind} AND {_state_condition(ENTITY_MARKED_STATES)}",
             _entity_symbol(index + 2, rgb, fill_alpha=FILL_ALPHA, outline=MARK_COLOR,
                            outline_alpha=255, style="dash dot", width_mm=_MARK_MM)),
        )
        for text, condition, symbol in variants:
            rules.append(f'   <rule key="{_rule_key(_TABLE_INDEX[VersionLayer.ENTITIES], index + 1)}" '
                         f'filter="{condition}" label="{_attr(text)}" symbol="{index}"/>')
            symbols.append(symbol)
            index += 1
    return "\n".join(rules), "\n".join(symbols)


def _road_symbol(index: int, rgb: tuple[int, int, int], *, alpha: int, style: str, width_mm: float) -> str:
    return _symbol(index, "line", "SimpleLine", (
        ("capstyle", "round"), ("joinstyle", "round"), ("line_color", _color(rgb, alpha)), ("line_style", style),
        ("line_width", f"{width_mm:g}"), ("line_width_unit", "MM")))


def _road_rules(classes: Iterable[str]) -> tuple[str, str]:
    """Las reglas (de cada clase de ``classes`` —por orden, sin repetir— y de «otra clase», cada una normal, descartada y con el
    apoyo retirado) y los símbolos de la capa de ejes de pistas (spec 017, T26): **categorías por el campo de la clase**
    (``class_name``). Las reglas no se solapan (una pista recibe un solo símbolo); la clase con comillas, «&» o «<» va escapada."""
    ordered = sorted({name for name in classes if isinstance(name, str) and name}, key=lambda name: (name.casefold(), name))
    special = ", ".join(f"'{state}'" for state in (*ENTITY_FADED_STATES, *ENTITY_MARKED_STATES))
    known = ", ".join("'" + _attr(name.replace("'", "''")) + "'" for name in ordered)
    items: list[tuple[str, str, tuple[int, int, int]]] = [
        (name, "&quot;class_name&quot; = '" + _attr(name.replace("'", "''")) + "'", ROAD_CLASS_COLORS[number % len(ROAD_CLASS_COLORS)])
        for number, name in enumerate(ordered)]
    items.append((ROAD_OTHER_LABEL, f"coalesce(&quot;class_name&quot;, '') NOT IN ({known})" if ordered else "TRUE", ROAD_OTHER_COLOR))
    rules = []
    symbols = []
    index = 0
    for label, of_class, rgb in items:
        variants = (
            (label, f"{of_class} AND coalesce(&quot;state&quot;, '') NOT IN ({special})",
             _road_symbol(index, rgb, alpha=255, style="solid", width_mm=_ROAD_LINE_MM)),
            (f"{label} {_FADED_LABEL}", f"{of_class} AND {_state_condition(ENTITY_FADED_STATES)}",
             _road_symbol(index + 1, rgb, alpha=_FADED_OUTLINE_ALPHA, style="dash", width_mm=_ROAD_FADED_MM)),
            (f"{label} {_MARKED_LABEL}", f"{of_class} AND {_state_condition(ENTITY_MARKED_STATES)}",
             _road_symbol(index + 2, MARK_COLOR, alpha=255, style="dash dot", width_mm=_ROAD_MARK_MM)),
        )
        for text, condition, symbol in variants:
            rules.append(f'   <rule key="{_rule_key(_TABLE_INDEX[VersionLayer.ROADS], index + 1)}" '
                         f'filter="{condition}" label="{_attr(text)}" symbol="{index}"/>')
            symbols.append(symbol)
            index += 1
    return "\n".join(rules), "\n".join(symbols)


def _check_fields(fields: Iterable[str]) -> tuple[str, ...]:
    found = tuple(dict.fromkeys(fields))
    if not found or any(not isinstance(name, str) or not name for name in found):
        raise ValueError(f"los campos de una capa son nombres no vacíos y al menos uno, no {found!r}")
    return found


def style_for(table: str, fields: Iterable[str] | None = None, classes: Iterable[str] | None = None) -> StyleRow:
    """El estilo por defecto de la capa ``table``: una de las tres capas de restricciones del proyecto
    (:data:`CONSTRAINT_LAYERS`; ``fields`` no cuenta: su QML no cambia) o de una versión (:func:`version_layer`:
    ``des_decl_<vNN>``, ``des_enl_<vNN>``, ``des_rax_<vNN>``), con la editabilidad de solo lectura de **cada** campo de
    ``fields`` (por defecto, ``fid`` y los que conoce el estilo: :data:`~.declared.COLUMN_NAMES`,
    :data:`ENTITY_FIELDS` o :data:`ROAD_FIELDS`; quien escribe la fila pasa los que la tabla tiene de verdad). ``classes``
    (solo la capa de ejes de pistas, T26): las clases normativas que tienen las pistas, una categoría cada una
    (:func:`_road_rules`). ``ValueError`` si ``table`` no es ninguna de ellas o ``fields`` no son nombres."""
    layer = version_layer(table)
    if layer is None:
        if table not in CONSTRAINT_LAYERS.values():
            raise ValueError(f"solo hay estilo de las capas de restricciones "
                             f"({', '.join(CONSTRAINT_LAYERS.values())}) y de las de una versión "
                             f"({DECLARED_LAYER}_<vNN>, {ENTITY_LAYER}_<vNN>, {ROAD_LAYER}_<vNN>), no de «{table}»")
        return StyleRow(STYLE_NAME, STYLE_DESCRIPTION, _qml(table))
    if layer is VersionLayer.DECLARED:
        named = _check_fields(("fid", *DECLARED_COLUMNS) if fields is None else fields)
        rule_lines, symbol_lines = _by_type(_TABLE_INDEX[layer], "fill")
        return StyleRow(DECLARED_STYLE_NAME, _DECLARED_DESCRIPTION,
                        _version_qml(layer, rule_lines, symbol_lines, _DECLARED_NOTE, named))
    if layer is VersionLayer.ROADS:
        named = _check_fields(("fid", *ROAD_FIELDS) if fields is None else fields)
        rule_lines, symbol_lines = _road_rules(() if classes is None else classes)
        return StyleRow(ROAD_STYLE_NAME, _ROAD_DESCRIPTION, _version_qml(layer, rule_lines, symbol_lines, _ROAD_NOTE, named))
    named = _check_fields(("fid", *ENTITY_FIELDS) if fields is None else fields)
    rule_lines, symbol_lines = _entity_rules()
    return StyleRow(ENTITY_STYLE_NAME, _ENTITY_DESCRIPTION,
                    _version_qml(layer, rule_lines, symbol_lines, _ENTITY_NOTE, named))


# --- La tabla ------------------------------------------------------------------------------


def write_styles(conn: sqlite3.Connection, tables: Iterable[str]) -> tuple[str, ...]:
    """Escribe, en la transacción de ``conn``, el estilo por defecto de cada capa de
    restricciones entre ``tables`` que aún no tiene uno por defecto (crea ``layer_styles`` si
    falta, con el esquema de QGIS y su fila de ``gpkg_contents``). Devuelve
    ``(STYLES_DATASET,)`` si escribió algo, para que quien llama lo declare como salida, y ``()``
    si no (sin capas de restricciones, o todas ya con su estilo)."""
    wanted = [table for table in dict.fromkeys(tables) if table in CONSTRAINT_LAYERS.values()]
    if not wanted:
        return ()
    written = False
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                          (STYLES_TABLE,)).fetchone()
    if exists is None:
        conn.execute(_STYLES_DDL)
        written = True
    registered = conn.execute("SELECT 1 FROM gpkg_contents WHERE table_name = ?",
                              (STYLES_TABLE,)).fetchone()
    if registered is None:
        conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description) "
                     "VALUES (?, 'attributes', ?, '')", (STYLES_TABLE, STYLES_TABLE))
        written = True
    for table in wanted:
        has_default = conn.execute(
            f'SELECT 1 FROM "{STYLES_TABLE}" WHERE f_table_name = ? AND f_geometry_column = ? '
            "AND useAsDefault", (table, GEOMETRY_COLUMN)).fetchone()
        if has_default is not None:
            continue
        row = style_for(table)
        conn.execute(_STYLES_INSERT, (table, GEOMETRY_COLUMN, row.name, row.qml, row.description))
        written = True
    return (STYLES_DATASET,) if written else ()


def _exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                        (table,)).fetchone() is not None


def _pending(conn: sqlite3.Connection, tables: Iterable[str]) -> list[str]:
    """Las capas de versión de ``tables`` que existen en el GeoPackage y aún no tienen un estilo por
    defecto (sin ``layer_styles``, ninguna: no se crea aquí)."""
    if not _exists(conn, STYLES_TABLE):
        return []
    found = []
    for table in dict.fromkeys(tables):
        if version_layer(table) is None or not _exists(conn, table):
            continue
        has_default = conn.execute(
            f'SELECT 1 FROM "{STYLES_TABLE}" WHERE f_table_name = ? AND f_geometry_column = ? '
            "AND useAsDefault", (table, GEOMETRY_COLUMN)).fetchone()
        if has_default is None:
            found.append(table)
    return found


def _fields_of(conn: sqlite3.Connection, table: str) -> list[str]:
    """Los campos que tiene de verdad la capa ``table``: sus columnas menos la de la geometría (que QGIS
    no cuenta entre sus campos)."""
    geometry = {str(row[0]) for row in conn.execute(
        "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?", (table,))}
    return [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')
            if str(row[1]) not in geometry]


def _classes_of(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    """Las clases normativas que tienen las pistas de la capa de ejes ``table`` (``class_name``), por orden; vacío si ``table`` no es la
    capa de ejes de pistas o no tiene ese campo (spec 017, T26)."""
    if version_layer(table) is not VersionLayer.ROADS:
        return ()
    try:
        found = conn.execute(f'SELECT DISTINCT class_name FROM "{table}" WHERE class_name IS NOT NULL AND class_name != \'\'').fetchall()
    except sqlite3.OperationalError:
        return ()
    return tuple(sorted((str(row[0]) for row in found), key=lambda name: (name.casefold(), name)))


_STYLES_UPDATE = (
    f'UPDATE "{STYLES_TABLE}" SET styleQML = ?, description = ?, update_time = strftime(\'%Y-%m-%dT%H:%M:%fZ\',\'now\') '
    "WHERE f_table_name = ? AND f_geometry_column = ? AND useAsDefault AND styleName = ?"
)


def _stale_road_styles(conn: sqlite3.Connection, tables: Iterable[str]) -> list[str]:
    """Las capas de ejes de pistas de ``tables`` cuyo estilo por defecto **escribió Geoblender** (por su nombre, :data:`ROAD_STYLE_NAME`) y ya no es el
    que daría hoy, porque las clases de sus pistas cambiaron (spec 017, T26): se rehace. El que guardó una persona desde QGIS (otro nombre) no cuenta nunca, ni
    una capa sin estilo (esa es de :func:`_pending`)."""
    if not _exists(conn, STYLES_TABLE):
        return []
    found = []
    for table in dict.fromkeys(tables):
        if version_layer(table) is not VersionLayer.ROADS or not _exists(conn, table):
            continue
        row = conn.execute(f'SELECT styleQML FROM "{STYLES_TABLE}" WHERE f_table_name = ? AND f_geometry_column = ? AND useAsDefault AND styleName = ?',
                           (table, GEOMETRY_COLUMN, ROAD_STYLE_NAME)).fetchone()
        if row is not None and row[0] != style_for(table, _fields_of(conn, table), _classes_of(conn, table)).qml:
            found.append(table)
    return found


def insert_version_styles(conn: sqlite3.Connection, tables: Iterable[str]) -> tuple[str, ...]:
    """Escribe, en la transacción de ``conn``, el estilo por defecto de cada capa de versión entre ``tables``
    (:func:`version_layer`) que existe y aún no lo tiene (RF-012-20, RF-015-27): con la editabilidad de
    solo lectura de **cada columna que la capa tiene** (:func:`_fields_of`) y, la capa de ejes de pistas, con las clases que tiene
    (:func:`_classes_of`; spec 017, T26). Devuelve las capas cuya fila escribió. De la capa de ejes de pistas, además, **rehace** el estilo que
    escribió Geoblender si cambiaron las clases (:func:`_stale_road_styles`). No crea ``layer_styles`` (la crea la primera operación de la
    012: :func:`write_styles`) ni anota el dato ``core_layer_styles``: es lo que hace :func:`write_version_styles`. Repetirla no
    duplica y lo que guardó QGIS se respeta."""
    named = tuple(dict.fromkeys(tables))
    written = []
    for table in _pending(conn, named):
        row = style_for(table, _fields_of(conn, table), _classes_of(conn, table))
        conn.execute(_STYLES_INSERT, (table, GEOMETRY_COLUMN, row.name, row.qml, row.description))
        written.append(table)
    for table in _stale_road_styles(conn, named):
        row = style_for(table, _fields_of(conn, table), _classes_of(conn, table))
        conn.execute(_STYLES_UPDATE, (row.qml, row.description, table, GEOMETRY_COLUMN, ROAD_STYLE_NAME))
        written.append(table)
    return tuple(written)


def _synced_styles(conn: sqlite3.Connection, project: dataset_registry.DatasetProject
                   ) -> DatasetRecord | None:
    """El dato ``core_layer_styles`` si está vivo, vigente y **al día** (nadie cambió su tabla desde que se
    anotó: el prefiltro de la comprobación de datos no salta), o ``None``."""
    record = dataset_registry.get(conn, STYLES_DATASET)
    if (record is None or not record.live or record.status is not DatasetStatus.CURRENT
            or record.store is not Store.GPKG or not record.tracked):
        return None
    states = dataset_tracking.table_states(conn, [record.locator])
    return record if probe_dataset(project, record, states).signal is Signal.UNCHANGED else None


def write_version_styles(conn: sqlite3.Connection, project: dataset_registry.DatasetProject,
                         tables: Iterable[str], *, operation_uid: str) -> tuple[str, ...]:
    """Escribe el estilo por defecto de cada capa de versión entre ``tables`` que aún no lo tiene
    (:func:`insert_version_styles`) **en la transacción ``conn`` de la operación de versión
    ``operation_uid``** (en curso) que escribe la capa, y anota el dato ``core_layer_styles`` del proyecto
    (``registry.note_content``: su hash y su seguimiento al día, y el cambio en su historia con esa
    operación) para que la comprobación de datos no lo tome por una edición hecha fuera de Geoblender
    (RF-008-21) ni lo bloquee (RF-008-56). La operación **no** lo declara como salida (RF-009-05: sus
    salidas son de su versión; el dato es del proyecto). Si el dato ya no estaba al día (alguien guardó un
    estilo en QGIS y nadie lo comprobó), la fila se escribe igual pero **no** se anota: la comprobación
    sigue viendo esa edición. Si el proyecto no tiene ``layer_styles``, no escribe nada. Devuelve las capas
    cuya fila escribió; si la transacción se deshace, no queda nada."""
    named = tuple(dict.fromkeys(tables))
    pending = [*_pending(conn, named), *_stale_road_styles(conn, named)]
    if not pending:
        return ()
    synced = _synced_styles(conn, project)
    written = insert_version_styles(conn, pending)
    if written and synced is not None:
        dataset_registry.note_content(conn, project, synced.uid, operation_uid=operation_uid,
                                      detail={"layers": list(written)})
    return written


def dataset_spec() -> DatasetSpec:
    """El dato de ``core`` de la tabla de estilos (D-32): ``core_layer_styles``, la tabla
    ``layer_styles`` de ``project.gpkg`` leída con ``core.gpkg_layer@1``, editable a mano en QGIS
    (RF-008-56)."""
    return DatasetSpec(STYLES_DATASET, "core", "table", Store.GPKG, STYLES_TABLE,
                       reader=GPKG_LAYER.id, role="styles", qgis_editable=True)
