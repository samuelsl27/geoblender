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

Python puro (``core``).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..content.builtin import GPKG_LAYER
from ..datasets import DatasetSpec, Store
from .model import ConstraintType
from .store import CONSTRAINT_LAYERS

__all__ = [
    "COLORS",
    "ELSE_COLOR",
    "ELSE_LABEL",
    "QGIS_VERSION",
    "STYLES_DATASET",
    "STYLES_TABLE",
    "StyleRow",
    "dataset_spec",
    "style_for",
    "write_styles",
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
_FILL_ALPHA = 110
_ELSE_ALPHA = 60
_LIMIT_MM = 0.9
_OUTLINE_MM = 0.5
_LINE_MM = 0.7
_POINT_MM = 3.5

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


def _qml(table: str) -> str:
    tables = tuple(CONSTRAINT_LAYERS.values())
    table_index = tables.index(table) + 1
    kind = {tables[0]: "fill", tables[1]: "line", tables[2]: "marker"}[table]
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
                                 alpha=_ELSE_ALPHA if ctype is None else _FILL_ALPHA,
                                 dashed=ctype is None,
                                 width_mm=_LIMIT_MM if ctype in _OUTLINE_ONLY else _OUTLINE_MM))
        elif kind == "line":
            symbols.append(_line(index, rgb, dashed=ctype is None))
        else:
            symbols.append(_marker(index, rgb, alpha=_ELSE_ALPHA if ctype is None else 200))
    rule_lines = "\n".join(rules)
    symbol_lines = "\n".join(symbols)
    return (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        f'<qgis version="{QGIS_VERSION}" styleCategories="Symbology">\n'
        ' <renderer-v2 type="RuleRenderer" symbollevels="0" enableorderby="0" '
        'forceraster="0" referencescale="-1">\n'
        f'  <rules key="{_rule_key(table_index, 0)}">\n'
        f"{rule_lines}\n"
        "  </rules>\n"
        "  <symbols>\n"
        f"{symbol_lines}\n"
        "  </symbols>\n"
        " </renderer-v2>\n"
        "</qgis>\n"
    )


def style_for(table: str) -> StyleRow:
    """El estilo por defecto de la capa de restricciones ``table`` (:data:`CONSTRAINT_LAYERS`);
    ``ValueError`` si no es una de las tres."""
    if table not in CONSTRAINT_LAYERS.values():
        raise ValueError(f"solo hay estilo de las capas de restricciones "
                         f"({', '.join(CONSTRAINT_LAYERS.values())}), no de «{table}»")
    return StyleRow(STYLE_NAME, STYLE_DESCRIPTION, _qml(table))


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


def dataset_spec() -> DatasetSpec:
    """El dato de ``core`` de la tabla de estilos (D-32): ``core_layer_styles``, la tabla
    ``layer_styles`` de ``project.gpkg`` leída con ``core.gpkg_layer@1``, editable a mano en QGIS
    (RF-008-56)."""
    return DatasetSpec(STYLES_DATASET, "core", "table", Store.GPKG, STYLES_TABLE,
                       reader=GPKG_LAYER.id, role="styles", qgis_editable=True)
