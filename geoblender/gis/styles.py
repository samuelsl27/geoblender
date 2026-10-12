# SPDX-License-Identifier: GPL-3.0-or-later
"""Estilos de QGIS de las capas entregables (spec 006, T55; RF-006-18, RF-006-25; M4).

Un :class:`LayerStyle` es lo que QGIS guarda de una capa en la tabla ``layer_styles`` de un
GeoPackage: su nombre, su descripción y su QML. ``gis.vector.write_layers`` lo escribe con la
capa como su estilo **por defecto** (``useAsDefault = 1``), el que QGIS aplica sin preguntar al
añadirla; el esquema de la tabla es el que crea QGIS 4.2 al guardar un estilo en un GeoPackage.

:data:`CONTOUR_STYLE`, el de las curvas de nivel (``gis_cnt_``, columna ``is_index`` de su
tabla, plan §5.2.3): un renderizador por reglas con «Maestras» (``"is_index"``) en un trazo de
:data:`INDEX_WIDTH_MM` y «Intermedias» (el resto) en uno de :data:`INTERMEDIATE_WIDTH_MM`, en
milímetros de pantalla o de papel, las maestras en un marrón más oscuro. Solo la simbología
(``styleCategories="Symbology"``): el estilo no toca las demás propiedades de la capa. Los
colores van como «r,g,b,a»: QGIS lee ``#rrggbbaa`` como ``#AARRGGBB`` (``docs/trampas.md`` §6).
Los textos que ve la persona en QGIS (las reglas de la leyenda, el nombre y la descripción del
estilo) van en español, como el identificador y la descripción de las capas entregables
(``gis.store``).

Solo los GeoPackage **entregables** llevan estilo. El del proyecto no: la comprobación de
apertura de la 008 avisa de toda tabla que no es del estándar, de SQLite, interna ni de un dato
(RF-008-62: ``layer_styles`` sería una «tabla sin registrar»), y los estilos del proyecto con la
paleta de IMGA son de R-73.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CONTOUR_STYLE",
    "INDEX_COLOR",
    "INDEX_WIDTH_MM",
    "INTERMEDIATE_COLOR",
    "INTERMEDIATE_WIDTH_MM",
    "LayerStyle",
    "contour_qml",
]

INDEX_WIDTH_MM = 0.5
"""El trazo de las curvas maestras en QGIS (mm)."""
INTERMEDIATE_WIDTH_MM = 0.25
"""El trazo de las curvas intermedias en QGIS (mm)."""
INDEX_COLOR = "120,72,36,255"
"""El color de las maestras, «r,g,b,a»."""
INTERMEDIATE_COLOR = "150,105,60,255"
"""El color de las intermedias, «r,g,b,a»."""
QGIS_VERSION = "4.2.0"
"""La versión de QGIS con la que se comprobó el QML (la que lo escribe en su cabecera)."""
STYLE_NAME_LIMIT = 30
"""Caracteres de ``layer_styles.styleName`` en QGIS (``TEXT(30)``)."""


@dataclass(frozen=True, slots=True)
class LayerStyle:
    """El estilo de QGIS de una capa entregable: ``name`` (como mucho
    :data:`STYLE_NAME_LIMIT` caracteres), ``qml`` (el documento QML entero) y ``description``.
    ``ValueError``/``TypeError`` si no lo cumple (un error del programa)."""

    name: str
    qml: str
    description: str = ""

    def __post_init__(self) -> None:
        for key in ("name", "qml", "description"):
            if not isinstance(getattr(self, key), str):
                raise TypeError(f"«{key}» de un estilo es un texto, no {getattr(self, key)!r}")
        if not self.name or len(self.name) > STYLE_NAME_LIMIT:
            raise ValueError(f"el nombre de un estilo tiene de 1 a {STYLE_NAME_LIMIT} "
                             f"caracteres, no {self.name!r}")
        if not self.qml.lstrip().startswith("<!DOCTYPE qgis"):
            raise ValueError("el QML de un estilo empieza por «<!DOCTYPE qgis»")


def _line_symbol(name: str, color: str, width_mm: float) -> str:
    """Un símbolo de línea simple de QGIS: continua, con extremos y uniones redondeados."""
    options = (("capstyle", "round"), ("joinstyle", "round"), ("line_color", color),
               ("line_style", "solid"), ("line_width", f"{width_mm:g}"),
               ("line_width_unit", "MM"))
    lines = "\n".join(f'      <Option name="{key}" type="QString" value="{value}"/>'
                      for key, value in options)
    return (f'   <symbol type="line" name="{name}" alpha="1" clip_to_extent="1" force_rhr="0">\n'
            '    <layer class="SimpleLine" enabled="1" locked="0" pass="0">\n'
            '     <Option type="Map">\n'
            f"{lines}\n"
            "     </Option>\n"
            "    </layer>\n"
            "   </symbol>")


def contour_qml(field: str = "is_index") -> str:
    """El QML de :data:`CONTOUR_STYLE`: reglas sobre el campo booleano ``field`` (las maestras
    donde es verdadero), con las claves de sus reglas fijas (el mismo texto cada vez)."""
    return (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        f'<qgis version="{QGIS_VERSION}" styleCategories="Symbology">\n'
        ' <renderer-v2 type="RuleRenderer" symbollevels="0" enableorderby="0" '
        'forceraster="0" referencescale="-1">\n'
        '  <rules key="{4f1d2b6e-0c3a-4e8b-9a51-6d2e7c1b0a10}">\n'
        '   <rule key="{4f1d2b6e-0c3a-4e8b-9a51-6d2e7c1b0a11}" '
        f'filter="&quot;{field}&quot;" label="Maestras" symbol="0"/>\n'
        '   <rule key="{4f1d2b6e-0c3a-4e8b-9a51-6d2e7c1b0a12}" filter="ELSE" '
        'label="Intermedias" symbol="1"/>\n'
        "  </rules>\n"
        "  <symbols>\n"
        f"{_line_symbol('0', INDEX_COLOR, INDEX_WIDTH_MM)}\n"
        f"{_line_symbol('1', INTERMEDIATE_COLOR, INTERMEDIATE_WIDTH_MM)}\n"
        "  </symbols>\n"
        " </renderer-v2>\n"
        "</qgis>\n"
    )


CONTOUR_STYLE = LayerStyle(
    "Curvas de nivel",
    contour_qml(),
    "Geoblender: curvas maestras (is_index) con trazo más grueso que las intermedias",
)
"""El estilo por defecto de las curvas de nivel en un GeoPackage entregable (T55)."""
