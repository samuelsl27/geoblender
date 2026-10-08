# SPDX-License-Identifier: GPL-3.0-or-later
"""Mensajes de topografía (spec 006; plan 006 §5.1 y §5.5; constitución, principio 10).

Cada error o aviso que ``gis`` puede mostrar tiene un **código** estable en inglés con el
prefijo ``gis.`` (``"gis.step_invalid"``), un ``msgid`` en inglés (también su versión
inglesa) y su texto en español, con marcadores de ``str.format`` (``{file}``) con nombre en
inglés, los mismos en los dos. El texto nombra el objeto, el campo y el valor, y dice qué
hacer (los ejemplos del plan §5.5 salen tal cual); el marcador ``{value}`` es siempre el
valor que se rechaza o se avisa (el ``value`` de :class:`GisError`).

- :class:`Message`: un mensaje del catálogo (``severity``: ``"error"`` o ``"warning"``);
  :data:`CATALOG`, todos; :data:`MESSAGES`, por código.
- :data:`CATALOG_ES`: ``msgid`` → español, para ``core.i18n.install`` al registrar.
- :func:`render`: el texto de un código con sus valores, en español o en inglés
  (:func:`format_value`, cada valor).
- :class:`GisError`: el error para el usuario, con código, ``msgid``, valores (JSON),
  objeto, campo y valor (un ``GeoblenderError``).

Las coordenadas y las cotas de un mensaje llegan ya escritas como texto
(``core.i18n.format_number`` y ``format_xyz``: coma decimal y espacio fino de miles); los
demás números, como números, y :func:`render` los escribe en el formato del idioma. Las
tareas siguientes de la 006 añaden aquí los códigos que necesiten.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..core.errors import GeoblenderError
from ..core.i18n import LANGUAGES

type JsonScalar = str | int | float | bool | None

MISSING_VALUE = "?"
"""Lo que se ve en lugar de un valor que falta (nunca el marcador ``{…}``)."""

SEVERITIES = ("error", "warning")


@dataclass(frozen=True, slots=True)
class Message:
    """Un mensaje del catálogo: código ``gis.*``, ``msgid`` en inglés, texto en español y
    gravedad (``"error"``: se lanza como :class:`GisError`; ``"warning"``: se informa y,
    si la spec lo pide, se confirma)."""

    code: str
    msgid: str
    es: str
    severity: str = "error"


CATALOG: tuple[Message, ...] = (
    # Rejilla y volumen (RF-006-01 a RF-006-03) ------------------------------------------
    Message(
        "gis.step_invalid",
        "Grid step {value} m is not valid: it must be a multiple of 0.5 m between 0.5 and "
        "5 m.",
        "El paso de rejilla {value} m no es válido: debe ser múltiplo de 0,5 m entre 0,5 y "
        "5 m.",
    ),
    Message(
        "gis.window_not_aligned",
        "Edge {edge} = {value} m of the work window is not a multiple of {unit} m, the "
        "alignment unit of grid step {step} m: change the project's work window so that it "
        "is aligned again.",
        "El borde {edge} = {value} m de la ventana de trabajo no es múltiplo de {unit} m, la "
        "unidad de alineación del paso de rejilla {step} m: cambie la ventana de trabajo del "
        "proyecto para que se vuelva a alinear.",
    ),
    Message(
        "gis.grid_mismatch",
        "Surfaces «{upper}» and «{lower}» are not on the same grid ({detail}): bring both "
        "to the project grid first.",
        "Las superficies «{upper}» y «{lower}» no están en la misma rejilla ({detail}): "
        "llévelas antes a la rejilla del proyecto.",
    ),
    # Remuestreo (RF-006-11, RF-006-30) -------------------------------------------------
    Message(
        "gis.classes_not_integer",
        "Class grid «{source}»: {value} is not a whole-number class code. Elevations are "
        "resampled with the area-weighted mean or the bilinear interpolation.",
        "Rejilla de clases «{source}»: {value} no es un código de clase entero. Las cotas se "
        "remuestrean con la media ponderada por área o con la interpolación bilineal.",
    ),
    # CRS y datum vertical (RF-006-04 a RF-006-07, RF-006-31) ----------------------------
    Message(
        "gis.crs_undeclared",
        "«{source}» does not declare its horizontal CRS: declare it before importing it "
        "(the project's is not assumed).",
        "«{source}» no declara su CRS horizontal: declárelo antes de importarlo (no se "
        "supone el del proyecto).",
    ),
    Message(
        "gis.vertical_undeclared",
        "«{source}» does not declare its vertical datum: declare it before importing it "
        "(the project's is not assumed).",
        "«{source}» no declara su datum vertical: declárelo antes de importarlo (no se "
        "supone el del proyecto).",
    ),
    Message(
        "gis.transform_unknown_accuracy",
        "There is no transformation of known accuracy from {source_crs} to {target_crs}: "
        "«{source}» has not been imported.",
        "No hay una transformación de precisión conocida de {source_crs} a {target_crs}: "
        "«{source}» no se ha importado.",
    ),
    Message(
        "gis.coordinates_unknown_accuracy",
        "There is no transformation of known accuracy from {source_crs} to {target_crs}: "
        "the coordinates have not been transformed.",
        "No hay una transformación de precisión conocida de {source_crs} a {target_crs}: "
        "las coordenadas no se han transformado.",
    ),
    Message(
        "gis.crs_catalog_mismatch",
        "The definition of {crs} in the coordinate transformation library differs from "
        "the one in Geoblender's catalog: transformations are disabled.",
        "La definición de {crs} en la biblioteca de transformación de coordenadas difiere "
        "de la del catálogo de Geoblender: las transformaciones quedan desactivadas.",
    ),
    Message(
        "gis.crs_service_version",
        "Coordinate transformations are disabled: Blender loaded pyproj {found} and "
        "Geoblender needs {expected} (another extension may have brought its own). The "
        "rest of Geoblender works normally.",
        "Las transformaciones de coordenadas están desactivadas: Blender cargó pyproj "
        "{found} y Geoblender necesita {expected} (otra extensión puede haber traído la "
        "suya). El resto de Geoblender funciona con normalidad.",
    ),
    Message(
        "gis.crs_service_broken",
        "Coordinate transformations are disabled: {detail}. The rest of Geoblender works "
        "normally.",
        "Las transformaciones de coordenadas están desactivadas: {detail}. El resto de "
        "Geoblender funciona con normalidad.",
    ),
    # Importar un MDT (RF-006-08, RF-006-09) ---------------------------------------------
    Message(
        "gis.tiff_compression_unsupported",
        "DTM «{file}»: compression {name} (code {value}) is not supported. Save it in "
        "QGIS with DEFLATE or LZW compression and import it again.",
        "MDT «{file}»: compresión {name} (código {value}) no admitida. Guárdelo en QGIS "
        "con compresión DEFLATE o LZW y vuelva a importarlo.",
    ),
    Message(
        "gis.raster_dtype_unsupported",
        "DTM «{file}»: data type {value} is not supported (integers of 8 to 32 bits and "
        "floats of 32 and 64 bits are). Convert it to Float32 in QGIS and import it "
        "again.",
        "MDT «{file}»: el tipo de dato {value} no se admite (sí los enteros de 8 a 32 bits "
        "y los flotantes de 32 y 64 bits). Conviértalo a Float32 en QGIS y vuelva a "
        "importarlo.",
    ),
    Message(
        "gis.raster_bands_unsupported",
        "DTM «{file}»: it has {value} bands and only single-band rasters are imported. "
        "Save the elevation band alone in QGIS and import it again.",
        "MDT «{file}»: tiene {value} bandas y solo se importan rásteres de una banda. "
        "Guarde en QGIS solo la banda de cotas y vuelva a importarlo.",
    ),
    Message(
        "gis.raster_rotated",
        "DTM «{file}»: its georeferencing is rotated or sheared ({value}). Warp it in QGIS "
        "to a north-up grid and import it again.",
        "MDT «{file}»: su georreferencia está girada o cizallada ({value}). Remuestréelo "
        "en QGIS a una rejilla orientada al norte y vuelva a importarlo.",
    ),
    Message(
        "gis.raster_scale_offset",
        "DTM «{file}»: its values have scale {scale} and offset {offset}. Save the real "
        "elevations in QGIS, without scale or offset, and import it again.",
        "MDT «{file}»: sus valores tienen escala {scale} y offset {offset}. Guarde en QGIS "
        "las cotas reales, sin escala ni offset, y vuelva a importarlo.",
    ),
    Message(
        "gis.raster_too_large",
        "DTM «{file}»: it has {value} cells and the limit is {limit}. Clip it in QGIS to "
        "the work area and import it again.",
        "MDT «{file}»: tiene {value} celdas y el límite es {limit}. Recórtelo en QGIS a la "
        "zona de trabajo y vuelva a importarlo.",
    ),
    Message(
        "gis.raster_empty",
        "DTM «{file}»: it has no cell with data.",
        "MDT «{file}»: no tiene ninguna celda con dato.",
    ),
    Message(
        "gis.raster_not_georeferenced",
        "DTM «{file}»: it has no georeferencing (ModelPixelScale and ModelTiepoint, or "
        "ModelTransformation). Georeference it in QGIS and import it again.",
        "MDT «{file}»: no tiene georreferencia (ModelPixelScale y ModelTiepoint, o "
        "ModelTransformation). Georreferéncielo en QGIS y vuelva a importarlo.",
    ),
    Message(
        "gis.raster_crs_unsupported",
        "DTM «{file}»: its CRS {value} is not in Geoblender's catalog (projected CRS in "
        "metres). Reproject it in QGIS to a CRS of the catalog (e.g. EPSG:25830) and import "
        "it again.",
        "MDT «{file}»: su CRS {value} no está en el catálogo de Geoblender (CRS proyectados "
        "en metros). Reproyéctelo en QGIS a un CRS del catálogo (p. ej. EPSG:25830) y "
        "vuelva a importarlo.",
    ),
    Message(
        "gis.raster_vertical_unsupported",
        "DTM «{file}»: its vertical CRS {value} is not in Geoblender's catalog. Convert its "
        "elevations in QGIS to a vertical datum of the catalog (e.g. EPSG:5782, Alicante "
        "height) and import it again.",
        "MDT «{file}»: su CRS vertical {value} no está en el catálogo de Geoblender. "
        "Convierta sus cotas en QGIS a un datum vertical del catálogo (p. ej. EPSG:5782, "
        "altitud de Alicante) y vuelva a importarlo.",
    ),
    Message(
        "gis.tiff_invalid",
        "DTM «{file}»: it is not a GeoTIFF that can be read ({detail}). Open it in QGIS, "
        "save it as GeoTIFF and import it again.",
        "MDT «{file}»: no es un GeoTIFF que se pueda leer ({detail}). Ábralo en QGIS, "
        "guárdelo como GeoTIFF y vuelva a importarlo.",
    ),
    Message(
        "gis.tiff_feature_unsupported",
        "DTM «{file}»: {feature} = {value} is not supported. Save it in QGIS as a "
        "single-band GeoTIFF, north-up and in metres, with DEFLATE or LZW compression, and "
        "import it again.",
        "MDT «{file}»: {feature} = {value} no se admite. Guárdelo en QGIS como GeoTIFF de "
        "una banda, orientado al norte y en metros, con compresión DEFLATE o LZW, y vuelva "
        "a importarlo.",
    ),
    Message(
        "gis.tiff_block_corrupt",
        "DTM «{file}»: block {block} of {blocks} is damaged ({detail}). Save it again in "
        "QGIS and import it again.",
        "MDT «{file}»: el bloque {block} de {blocks} está dañado ({detail}). Vuelva a "
        "guardarlo en QGIS y a importarlo.",
    ),
    Message(
        "gis.crs_user_defined",
        "DTM «{file}» defines its CRS with its own parameters, without an EPSG code: "
        "declare its CRS when importing it.",
        "El MDT «{file}» define su CRS con parámetros propios, sin código EPSG: declare su "
        "CRS al importarlo.",
        "warning",
    ),
    Message(
        "gis.asc_header_invalid",
        "DTM «{file}»: its ESRI ASCII Grid header is not valid ({detail}). Correct it "
        "(ncols, nrows, xllcorner or xllcenter, yllcorner or yllcenter, cellsize or dx and "
        "dy, and NODATA_value if there is one) or save it again from QGIS, and import it "
        "again.",
        "MDT «{file}»: su cabecera de ESRI ASCII Grid no es válida ({detail}). Corríjala "
        "(ncols, nrows, xllcorner o xllcenter, yllcorner o yllcenter, cellsize o dx y dy, y "
        "NODATA_value si lo hay) o vuelva a guardarlo desde QGIS, y vuelva a importarlo.",
    ),
    Message(
        "gis.asc_value_count",
        "DTM «{file}»: it has {value} values and its header asks for {expected} (ncols "
        "{ncols} × nrows {nrows}). Check that the file is complete, export it again and "
        "import it again.",
        "MDT «{file}»: tiene {value} valores y su cabecera pide {expected} (ncols {ncols} × "
        "nrows {nrows}). Compruebe que el fichero está completo, vuelva a exportarlo y a "
        "importarlo.",
    ),
    Message(
        "gis.asc_value_invalid",
        "DTM «{file}», row {row}, column {column} from the north-west corner: «{value}» is "
        "not a number. Correct that value (with a decimal point) or export the file again, "
        "and import it again.",
        "MDT «{file}», fila {row}, columna {column} desde la esquina noroeste: «{value}» no "
        "es un número. Corrija ese valor (con punto decimal) o vuelva a exportar el fichero, "
        "y vuelva a importarlo.",
    ),
    Message(
        "gis.prj_unidentified",
        "The CRS declared by «{prj}» has not been recognised in Geoblender's catalog: "
        "declare the CRS of «{file}» when importing it.",
        "El CRS que declara «{prj}» no se ha reconocido en el catálogo de Geoblender: "
        "declare el CRS de «{file}» al importarlo.",
        "warning",
    ),
    Message(
        "gis.xyz_not_grid",
        "File «{file}» is not a regular grid ({detail}). Import it as points (Topography "
        "▸ Import ▸ Points and breaklines…).",
        "El fichero «{file}» no es una malla regular ({detail}). Impórtelo como puntos "
        "(Topografía ▸ Importar ▸ Puntos y líneas de rotura…).",
    ),
    Message(
        "gis.xyz_line_invalid",
        "DTM «{file}», line {line}: {detail}. Correct it (X, Y and Z on each line, with the "
        "chosen separator and decimal mark) or export the file again, and import it again.",
        "MDT «{file}», línea {line}: {detail}. Corríjala (X, Y y Z en cada línea, con el "
        "separador y el decimal elegidos) o vuelva a exportar el fichero, y vuelva a "
        "importarlo.",
    ),
    Message(
        "gis.pixel_is_point",
        "DTM «{file}» declares PixelIsPoint: its grid has been moved half a cell so that "
        "each cell is an area.",
        "El MDT «{file}» declara PixelIsPoint: su rejilla se ha desplazado medio paso para "
        "que cada celda sea un área.",
        "warning",
    ),
    Message(
        "gis.ellipsoidal_suspected",
        "The median difference with DTM «{dtm}» is {median} m: the elevations may be "
        "ellipsoidal heights (GNSS or drone without geoid). Continue?",
        "La mediana de la diferencia con el MDT «{dtm}» es de {median} m: las cotas pueden "
        "ser alturas elipsoidales (GNSS o dron sin geoide). ¿Continuar?",
        "warning",
    ),
    # Puntos, líneas y capas (RF-006-12) -------------------------------------------------
    Message(
        "gis.value_not_number",
        "Points «{file}», row {row}, column {column} («{header}»): «{value}» is not a "
        "number.",
        "Puntos «{file}», fila {row}, columna {column} («{header}»): «{value}» no es un "
        "número.",
    ),
    Message(
        "gis.value_empty",
        "Points «{file}», row {row}, column {column} («{header}»): it is empty.",
        "Puntos «{file}», fila {row}, columna {column} («{header}»): está vacía.",
    ),
    Message(
        "gis.row_columns",
        "Points «{file}», row {row}: it has {value} columns and {expected} are expected. "
        "Check the separator and the decimal mark chosen.",
        "Puntos «{file}», fila {row}: tiene {value} columnas y se esperan {expected}. "
        "Compruebe el separador y el decimal elegidos.",
    ),
    Message(
        "gis.breakline_no_elevation",
        "Points «{file}», row {row}: this vertex of line «{line}» has no elevation (Z); a "
        "breakline without elevation is not accepted, so the whole line is rejected.",
        "Puntos «{file}», fila {row}: este vértice de la línea «{line}» no tiene cota (Z); "
        "no se acepta una línea de rotura sin cota, así que se rechaza la línea entera.",
    ),
    Message(
        "gis.line_rejected",
        "Points «{file}», row {row}: line «{line}» is rejected whole because its row "
        "{bad_row} is not valid. Correct that row and import the file again.",
        "Puntos «{file}», fila {row}: se rechaza entera la línea «{line}» porque su fila "
        "{bad_row} no es válida. Corrija esa fila y vuelva a importar el fichero.",
    ),
    Message(
        "gis.line_single_point",
        "Points «{file}», row {row}: line «{line}» has a single point; a line needs at "
        "least two.",
        "Puntos «{file}», fila {row}: la línea «{line}» tiene un solo punto; una línea "
        "necesita al menos dos.",
    ),
    Message(
        "gis.m_discarded",
        "Layer «{layer}»: its M values have been discarded.",
        "Capa «{layer}»: se han descartado sus valores M.",
        "warning",
    ),
    Message(
        "gis.gpkg_unreadable",
        "GeoPackage «{file}» cannot be read: {detail}.",
        "No se puede leer el GeoPackage «{file}»: {detail}.",
    ),
    Message(
        "gis.layer_not_found",
        "«{file}» has no feature layer «{value}»: choose one of its layers.",
        "«{file}» no tiene ninguna capa vectorial «{value}»: elija una de sus capas.",
    ),
    Message(
        "gis.layer_geometry_unsupported",
        "Layer «{layer}» of «{file}»: geometry type {value} is not supported (points, lines "
        "and polygons, single or multi-part, 2D or with Z, are). Convert it in QGIS (e.g. "
        "curves with Segmentize) and import it again.",
        "Capa «{layer}» de «{file}»: el tipo de geometría {value} no se admite (sí los "
        "puntos, las líneas y los polígonos, simples o múltiples, 2D o con Z). Conviértala "
        "en QGIS (p. ej. las curvas con Segmentar) y vuelva a importarla.",
    ),
    Message(
        "gis.layer_crs_unsupported",
        "Layer «{layer}» of «{file}»: its CRS {value} is not in Geoblender's catalog "
        "(projected CRS in metres). Reproject it in QGIS to a CRS of the catalog (e.g. "
        "EPSG:25830) and import it again.",
        "Capa «{layer}» de «{file}»: su CRS {value} no está en el catálogo de Geoblender "
        "(CRS proyectados en metros). Reproyéctela en QGIS a un CRS del catálogo (p. ej. "
        "EPSG:25830) y vuelva a importarla.",
    ),
    Message(
        "gis.layer_crs_undeclared",
        "Layer «{layer}» of «{file}» has no EPSG CRS ({value}): declare its CRS when "
        "importing it.",
        "La capa «{layer}» de «{file}» no tiene un CRS EPSG ({value}): declare su CRS al "
        "importarla.",
        "warning",
    ),
    Message(
        "gis.features_without_geometry",
        "Layer «{layer}» of «{file}»: {value} features without geometry (empty or null) have "
        "been skipped.",
        "Capa «{layer}» de «{file}»: se han omitido {value} entidades sin geometría (vacías "
        "o nulas).",
        "warning",
    ),
    Message(
        "gis.feature_geometry_invalid",
        "Layer «{layer}» of «{file}», feature {row}: its geometry cannot be read ({detail}).",
        "Capa «{layer}» de «{file}», entidad {row}: su geometría no se puede leer "
        "({detail}).",
    ),
    Message(
        "gis.feature_srs_mismatch",
        "Layer «{layer}» of «{file}», feature {row}: its geometry declares SRS {value} and "
        "the layer {expected}.",
        "Capa «{layer}» de «{file}», entidad {row}: su geometría declara el SRS {value} y la "
        "capa, el {expected}.",
    ),
    Message(
        "gis.feature_role_mismatch",
        "Layer «{layer}», feature {row}: it is a {value} and only {expected} are imported as "
        "{role}.",
        "Capa «{layer}», entidad {row}: es un {value} y como {role} solo se importan "
        "{expected}.",
    ),
    Message(
        "gis.feature_without_z",
        "Layer «{layer}», feature {row}: it has no elevation (Z) and a geometry without "
        "elevation is not accepted as {role}.",
        "Capa «{layer}», entidad {row}: no tiene cota (Z) y no se acepta como {role} una "
        "geometría sin cota.",
    ),
    # TIN (RF-006-13, RF-006-14) ---------------------------------------------------------
    Message(
        "gis.breaklines_cross",
        "TIN «{tin}»: breaklines «{first}» and «{second}» cross at ({position}) with "
        "elevations {first_z} m and {second_z} m.",
        "TIN «{tin}»: las líneas de rotura «{first}» y «{second}» se cruzan en "
        "({position}) con cotas {first_z} m y {second_z} m.",
    ),
    Message(
        "gis.breaklines_overlap",
        "TIN «{tin}»: breaklines «{first}» and «{second}» overlap at ({position}) with "
        "elevations {first_z} m and {second_z} m.",
        "TIN «{tin}»: las líneas de rotura «{first}» y «{second}» se solapan en "
        "({position}) con cotas {first_z} m y {second_z} m.",
    ),
    Message(
        "gis.point_on_breakline",
        "TIN «{tin}»: point «{first}» lies on breakline «{second}» at ({position}) with "
        "elevations {first_z} m and {second_z} m.",
        "TIN «{tin}»: el punto «{first}» está sobre la línea de rotura «{second}» en "
        "({position}) con cotas {first_z} m y {second_z} m.",
    ),
    Message(
        "gis.points_conflict",
        "TIN «{tin}»: points «{first}» and «{second}» coincide in plan at ({position}) with "
        "elevations {first_z} m and {second_z} m.",
        "TIN «{tin}»: los puntos «{first}» y «{second}» coinciden en planta en "
        "({position}) con cotas {first_z} m y {second_z} m.",
    ),
    Message(
        "gis.duplicate_conflicts",
        "TIN «{tin}»: {value} pairs of points coincide in plan within {tol_xy} m with "
        "elevations that differ by more than {tol_z} m. Choose how to resolve them: mean, "
        "minimum, maximum, first or cancel.",
        "TIN «{tin}»: {value} parejas de puntos coinciden en planta a ≤ {tol_xy} m con cotas "
        "que difieren más de {tol_z} m. Elija cómo resolverlas: media, mínima, máxima, "
        "primero o cancelar.",
    ),
    Message(
        "gis.duplicates_cancelled",
        "TIN «{tin}» has not been created: {value} pairs of points coincide in plan with "
        "different elevations and you chose to cancel.",
        "No se ha creado el TIN «{tin}»: {value} parejas de puntos coinciden en planta con "
        "cotas distintas y se eligió cancelar.",
    ),
    Message(
        "gis.constraint_conflicts",
        "TIN «{tin}» has not been created: {value} conflicts between breaklines and points "
        "within {tol_xy} m with elevations that differ by more than {tol_z} m. Correct the "
        "lines in their source or choose how to resolve the points, and create it again.",
        "No se ha creado el TIN «{tin}»: {value} conflictos entre líneas de rotura y puntos "
        "a ≤ {tol_xy} m con cotas que difieren más de {tol_z} m. Corrija las líneas en su "
        "fuente o elija cómo resolver los puntos, y vuelva a crearlo.",
    ),
    Message(
        "gis.triangulation_contract",
        "Triangulator {name} did not fulfil its contract: {detail}.",
        "El triangulador {name} no cumplió su contrato: {detail}.",
    ),
    Message(
        "gis.triangulation_input",
        "Triangulator {name} cannot triangulate this data: {detail}.",
        "El triangulador {name} no puede triangular estos datos: {detail}.",
    ),
    # Exportar (RF-006-10) ---------------------------------------------------------------
    Message(
        "gis.export_over_input",
        "«{file}» is registered as an input of the project and is never overwritten: "
        "choose another destination.",
        "«{file}» está registrado como entrada del proyecto y nunca se sobrescribe: elija "
        "otro destino.",
    ),
    # Escribir un GeoTIFF (RF-006-08, RF-006-24) -----------------------------------------
    Message(
        "gis.export_nodata_collision",
        "GeoTIFF «{file}»: {count} cells have an elevation that in float32 is −9999, the "
        "no-data value of GeoTIFF deliverables (the first one, {value} m, in row {row} and "
        "column {column} from the north-west corner). Correct those elevations and export "
        "it again.",
        "GeoTIFF «{file}»: {count} celdas tienen una cota que en float32 es −9999, el sin "
        "dato de los GeoTIFF entregables (la primera, {value} m, en la fila {row} y la "
        "columna {column} desde la esquina noroeste). Corrija esas cotas y vuelva a "
        "exportarlo.",
    ),
    Message(
        "gis.export_value_out_of_range",
        "GeoTIFF «{file}»: {count} cells have an elevation that does not fit in float32, the "
        "type of GeoTIFF deliverables (the first one, {value} m, in row {row} and column "
        "{column} from the north-west corner). Correct those elevations and export it "
        "again.",
        "GeoTIFF «{file}»: {count} celdas tienen una cota que no cabe en float32, el tipo de "
        "los GeoTIFF entregables (la primera, {value} m, en la fila {row} y la columna "
        "{column} desde la esquina noroeste). Corrija esas cotas y vuelva a exportarlo.",
    ),
    Message(
        "gis.raster_target_locked",
        "«{file}» cannot be replaced: another program has it open (e.g. QGIS). Remove the "
        "layer in QGIS or close that program and try again; the previous file is intact.",
        "No se puede sustituir «{file}»: otro programa lo tiene abierto (p. ej. QGIS). "
        "Quite la capa en QGIS o cierre ese programa y vuelva a intentarlo; el fichero "
        "anterior sigue intacto.",
    ),
    Message(
        "gis.raster_write_failed",
        "«{file}» could not be written ({detail}): check that the folder exists, that there "
        "is free space and that you may write in it; no half-written file is left.",
        "No se ha podido escribir «{file}» ({detail}): compruebe que la carpeta existe, que "
        "queda espacio y que tiene permiso de escritura; no ha quedado ningún fichero a "
        "medias.",
    ),
    # Parámetros (gis/params.py) ---------------------------------------------------------
    Message(
        "gis.param_not_number",
        "Parameter «{key}»: «{value}» is not a number.",
        "Parámetro «{key}»: «{value}» no es un número.",
    ),
    Message(
        "gis.param_not_integer",
        "Parameter «{key}»: «{value}» is not a whole number.",
        "Parámetro «{key}»: «{value}» no es un número entero.",
    ),
    Message(
        "gis.param_not_list",
        "Parameter «{key}»: «{value}» is not a list of {length} numbers in ascending "
        "order.",
        "Parámetro «{key}»: «{value}» no es una lista de {length} números en orden "
        "creciente.",
    ),
    Message(
        "gis.param_out_of_range",
        "Parameter «{key}»: {value} is outside its range {range}.",
        "Parámetro «{key}»: {value} está fuera de su rango {range}.",
    ),
)

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in CATALOG})
"""El catálogo por código (solo lectura)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType({m.msgid: m.es for m in CATALOG})
"""``msgid`` → texto en español, para ``core.i18n.install`` (solo lectura)."""


def lookup(code: str) -> Message:
    """El mensaje de ``code``; :class:`ValueError` si no está en el catálogo (un error del
    programa: todo mensaje de ``gis`` tiene aquí su texto en español)."""
    message = MESSAGES.get(code)
    if message is None:
        raise ValueError(
            f"el código de mensaje «{code}» no está en el catálogo de topografía "
            "(gis/messages.py)"
        )
    return message


def render(code: str, /, *, language: str = "es", **values: object) -> str:
    """El texto de ``code`` con ``values`` en sus marcadores, en ``language`` (``"es"`` o
    ``"en"``, el ``msgid``). El marcador sin valor queda :data:`MISSING_VALUE`; los valores
    que sobran se ignoran. Los decimales salen con coma en español y con punto en inglés."""
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    message = lookup(code)
    template = message.es if language == "es" else message.msgid
    shown = _Shown({name: format_value(value, language) for name, value in values.items()})
    return template.format_map(shown)


def json_value(value: object) -> JsonScalar:
    """``value`` como se guarda en el registro (JSON): los escalares tal cual y lo demás
    (una ``Path``, una tupla) como texto."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


class GisError(GeoblenderError):
    """Error de topografía para el usuario: ``code`` del catálogo, ``msgid``, ``values``
    (JSON, para el registro y para mostrarlo en otro idioma con :func:`render`), el
    objeto, el campo y el valor (``GeoblenderError``) y ``text`` en español, que es también
    ``str(error)`` y ``message``. El valor es también el marcador ``{value}`` del texto.
    Un código de aviso no es un error: :class:`ValueError`."""

    def __init__(
        self,
        code: str,
        /,
        *,
        obj: str,
        field: str,
        value: object = None,
        **values: object,
    ) -> None:
        message = lookup(code)
        if message.severity != "error":
            raise ValueError(f"«{code}» es un aviso, no un error: se informa, no se lanza")
        shown = {"value": value, **values}
        self.msgid = message.msgid
        self.values: dict[str, JsonScalar] = {k: json_value(v) for k, v in shown.items()}
        self.text = render(code, **shown)
        super().__init__(code, self.text, obj=obj, field=field, value=value,
                         context=self.values)
        self.args = (self.text,)


class _Shown(dict[str, str]):
    """Valores ya presentados; el que falta se ve como :data:`MISSING_VALUE`."""

    def __missing__(self, key: str) -> str:
        return MISSING_VALUE


def format_value(value: object, language: str = "es") -> str:
    """Un valor como lo lee una persona en ``language``: un decimal con coma en español
    (``0.25`` → ``0,25``) y sin decimales si es entero (``2.0`` → ``2``); un booleano, «sí»
    o «no»; ``None``, :data:`MISSING_VALUE`; lo demás, su texto."""
    if value is None:
        return MISSING_VALUE
    if isinstance(value, bool):
        if language == "es":
            return "sí" if value else "no"
        return "yes" if value else "no"
    if isinstance(value, float):
        text = str(int(value)) if value.is_integer() else repr(value)
        return text.replace(".", ",") if language == "es" else text
    return str(value)
