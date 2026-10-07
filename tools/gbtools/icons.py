# SPDX-License-Identifier: GPL-3.0-or-later
"""Iconos propios de Geoblender: validación de las fuentes SVG, manifiesto y comprobación
de los PNG generados (spec 003, T30; RF-003-22; RNF-003-09; plan 003 §5.4, 12; II §1.6 y
§1.7). Biblioteca estándar: sin ``bpy`` (el rasterizado lo hace
``tools/inblender/rasterize_icons.py`` dentro de Blender).

- :func:`svg_problems`: una fuente ``assets/icons/<nombre>.svg`` es válida si su raíz es
  ``<svg>`` con ``viewBox="0 0 16 16"``; fuera de ``<metadata>`` solo usa ``path``,
  ``rect``, ``circle``, ``line``, ``polyline``, ``polygon`` y ``g`` (sin texto, sin
  imágenes incrustadas, sin ``use``, ``style``, ``script`` ni manejadores ``on…``); no
  tiene referencias externas (``href``, ``url(…)`` a otro sitio, DOCTYPE o entidades) y
  lleva los metadatos RDF de licencia de II §1.7 (:func:`license_problems`: ``dc:rights``
  «CC0-1.0», ``cc:license`` con la URL de CC0 y el autor «IMGA»).
- :func:`build_manifest`: ``resources/icons/manifest.json`` = ``{"blender": versión,
  "icons": {nombre: {"svg": sha256, "png32": sha256, "png64": sha256}}}``.
- :func:`check_problems` (``tools/build_icons.py --check``, paso «iconos» de
  ``tools/check.py``): cada SVG con su entrada del manifiesto y el mismo sha256 (si se
  tocó sin regenerar, falla), sus dos PNG con el sha256 del manifiesto, de 32 y 64 px y
  ≤ 8 KB, y ningún PNG ni entrada del manifiesto sin su SVG. No rasteriza nada.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .layout import RESOURCES_RELPATH

SVG_NS = "http://www.w3.org/2000/svg"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DC_NS = "http://purl.org/dc/elements/1.1/"
CC_NS = "http://creativecommons.org/ns#"
CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
CC0_ID = "CC0-1.0"
AUTHOR = "IMGA"
VIEW_BOX = "0 0 16 16"
ALLOWED_SHAPES = frozenset({"svg", "g", "path", "rect", "circle", "line", "polyline",
                            "polygon", "metadata"})
SIZES: tuple[int, ...] = (32, 64)
MAX_PNG_BYTES = 8 * 1024  # RNF-003-09
MANIFEST_NAME = "manifest.json"
SVG_DIR_RELPATH = "assets/icons"
PNG_DIR_RELPATH = f"{RESOURCES_RELPATH}/icons"
NAME_RE = re.compile(r"^gb_[a-z0-9]+(?:_[a-z0-9]+)*$")
PNG_RE = re.compile(r"^(?P<name>.+)_(?P<size>\d+)\.png$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_EXTERNAL_URL = re.compile(r"url\(\s*['\"]?(?!#)", re.IGNORECASE)


def _local(tag: str) -> tuple[str, str]:
    """(espacio de nombres, nombre) de una etiqueta de ``ElementTree``."""
    if tag.startswith("{"):
        namespace, _, name = tag[1:].partition("}")
        return namespace, name
    return "", tag


def sha256_file(path: Path) -> str:
    """El sha256 de un fichero, en hexadecimal."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def png_names(name: str) -> tuple[str, ...]:
    """Los PNG de un icono: ``<nombre>_32.png`` y ``<nombre>_64.png``."""
    return tuple(f"{name}_{size}.png" for size in SIZES)


def png_size(path: Path) -> tuple[int, int] | None:
    """(ancho, alto) de un PNG leído de su cabecera, o ``None`` si no es un PNG."""
    data = Path(path).read_bytes()[:24]
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


# Validación de las fuentes ---------------------------------------------------------------


def _metadata_texts(root: ET.Element) -> tuple[list[str], list[str], list[str]]:
    """Los ``dc:rights``, los ``rdf:resource`` de ``cc:license`` y los autores
    (``dc:creator``) del bloque ``<metadata>``."""
    rights: list[str] = []
    licenses: list[str] = []
    authors: list[str] = []
    for metadata in root.iter(f"{{{SVG_NS}}}metadata"):
        for node in metadata.iter():
            namespace, name = _local(node.tag)
            if (namespace, name) == (DC_NS, "rights"):
                rights.append(" ".join("".join(node.itertext()).split()))
            elif (namespace, name) == (CC_NS, "license"):
                licenses.append(node.get(f"{{{RDF_NS}}}resource", "").strip())
            elif (namespace, name) == (DC_NS, "creator"):
                authors.append(" ".join("".join(node.itertext()).split()))
    return rights, licenses, authors


def license_problems(text: str) -> list[str]:
    """Los motivos por los que un SVG no lleva los metadatos CC0 de II §1.7 (vacío si los
    lleva). Lo usa también ``tools/check_licenses.py`` (LIC-04)."""
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        return [f"no es XML válido ({exc})"]
    rights, licenses, authors = _metadata_texts(root)
    problems: list[str] = []
    if CC0_ID not in rights:
        problems.append(f"falta dc:rights «{CC0_ID}» en <metadata> (II §1.7)")
    if CC0_URL not in licenses:
        problems.append(f"falta cc:license rdf:resource=«{CC0_URL}» en <metadata> (II §1.7)")
    if not any(AUTHOR in author for author in authors):
        problems.append(f"falta el autor «{AUTHOR}» (dc:creator) en <metadata> (II §1.7)")
    return problems


def _attribute_problems(node: ET.Element, name: str) -> list[str]:
    problems: list[str] = []
    for key, value in node.attrib.items():
        _namespace, attribute = _local(key)
        if attribute.lower().startswith("on"):
            problems.append(f"<{name}> tiene un manejador «{attribute}» (sin scripts)")
        elif attribute == "href":
            problems.append(f"<{name}> tiene una referencia «{attribute}={value}» "
                            "(sin referencias externas)")
        elif _EXTERNAL_URL.search(value):
            problems.append(f"<{name}> {attribute}=«{value}» es una referencia externa")
    return problems


def svg_problems(path: Path) -> list[str]:
    """Los motivos por los que ``path`` no es una fuente de icono válida (II §1.6, 1);
    vacía si lo es."""
    path = Path(path)
    if not NAME_RE.match(path.stem):
        return [f"el nombre «{path.stem}» no es gb_<grupo>_<concepto> (II §1.3)"]
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"no se puede leer en UTF-8: {exc}"]
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return ["tiene DOCTYPE o entidades (sin referencias externas)"]
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        return [f"no es XML válido ({exc})"]
    problems: list[str] = []
    if _local(root.tag) != (SVG_NS, "svg"):
        problems.append(f"la raíz es <{_local(root.tag)[1]}> y no <svg> de {SVG_NS}")
    if " ".join(root.get("viewBox", "").split()) != VIEW_BOX:
        problems.append(f"viewBox=«{root.get('viewBox', '')}»: tiene que ser «{VIEW_BOX}»")
    inside_metadata: set[int] = set()
    for metadata in root.iter(f"{{{SVG_NS}}}metadata"):
        inside_metadata.update(id(node) for node in metadata.iter() if node is not metadata)
    for node in root.iter():
        if id(node) in inside_metadata:
            continue
        namespace, name = _local(node.tag)
        if namespace != SVG_NS or name not in ALLOWED_SHAPES:
            what = "texto (conviértalo a trazos)" if name in ("text", "tspan") else (
                "una imagen incrustada" if name == "image" else f"un elemento <{name}>")
            problems.append(f"tiene {what}: solo path, rect, circle, line, polyline, "
                            "polygon y g")
            continue
        problems.extend(_attribute_problems(node, name))
    problems.extend(license_problems(text))
    return problems


def svg_files(svg_dir: Path) -> list[Path]:
    """Las fuentes SVG de una carpeta, por nombre."""
    folder = Path(svg_dir)
    return sorted(folder.glob("*.svg")) if folder.is_dir() else []


# Manifiesto y comprobación ---------------------------------------------------------------


def build_manifest(svg_dir: Path, png_dir: Path, blender_version: str) -> dict[str, Any]:
    """El manifiesto de los iconos de ``svg_dir`` con sus PNG de ``png_dir``."""
    icons: dict[str, dict[str, str]] = {}
    for svg in svg_files(svg_dir):
        entry = {"svg": sha256_file(svg)}
        for size, png in zip(SIZES, png_names(svg.stem), strict=True):
            entry[f"png{size}"] = sha256_file(Path(png_dir) / png)
        icons[svg.stem] = entry
    return {"blender": blender_version, "icons": icons}


def write_manifest(png_dir: Path, manifest: Mapping[str, Any]) -> Path:
    """Escribe ``manifest.json`` en ``png_dir`` (UTF-8, LF, claves ordenadas)."""
    path = Path(png_dir) / MANIFEST_NAME
    text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_bytes(text.encode("utf-8"))
    return path


def orphan_pngs(svg_dir: Path, png_dir: Path) -> list[Path]:
    """Los PNG de ``png_dir`` que no son de ninguna fuente de ``svg_dir``."""
    wanted = {png for svg in svg_files(svg_dir) for png in png_names(svg.stem)}
    folder = Path(png_dir)
    found = sorted(folder.glob("*.png")) if folder.is_dir() else []
    return [png for png in found if png.name not in wanted]


def _read_manifest(png_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = Path(png_dir) / MANIFEST_NAME
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{MANIFEST_NAME}: no se puede leer ({exc})"
    if not isinstance(data, dict) or not isinstance(data.get("icons"), dict):
        return None, f"{MANIFEST_NAME}: falta el objeto «icons»"
    return data, None


def _png_problems(png: Path, size: int, expected: object) -> Iterable[str]:
    if not png.is_file():
        yield f"falta {png.name}"
        return
    if sha256_file(png) != expected:
        yield f"{png.name} no es el del manifiesto (¿se tocó a mano?)"
    if png_size(png) != (size, size):
        yield f"{png.name} mide {png_size(png)} y no {size} × {size} px"
    if png.stat().st_size > MAX_PNG_BYTES:
        yield f"{png.name} ocupa {png.stat().st_size} bytes (> {MAX_PNG_BYTES}; RNF-003-09)"


def check_problems(svg_dir: Path, png_dir: Path) -> list[str]:
    """Lo que no cuadra entre las fuentes, los PNG y el manifiesto (vacía si todo
    cuadra). Sin fuentes ni PNG, no hay nada que comprobar."""
    svgs = svg_files(svg_dir)
    manifest, error = _read_manifest(png_dir)
    problems: list[str] = [error] if error else []
    orphans = orphan_pngs(svg_dir, png_dir)
    problems.extend(f"sobra {png.name}: no tiene fuente en {SVG_DIR_RELPATH}" for png in orphans)
    if not svgs:
        return problems
    if manifest is None:
        problems.append(f"falta {MANIFEST_NAME}: ejecute tools/build_icons.py")
        return problems
    icons: Mapping[str, Any] = manifest["icons"]
    names = {svg.stem for svg in svgs}
    problems.extend(f"{MANIFEST_NAME} tiene «{name}» y no hay {name}.svg"
                    for name in sorted(set(icons) - names))
    for svg in svgs:
        entry = icons.get(svg.stem)
        if not isinstance(entry, dict):
            problems.append(f"{svg.name} no está en {MANIFEST_NAME}: ejecute tools/build_icons.py")
            continue
        if sha256_file(svg) != entry.get("svg"):
            problems.append(f"{svg.name} ha cambiado y sus PNG no se han regenerado: "
                            "ejecute tools/build_icons.py")
        for size, name in zip(SIZES, png_names(svg.stem), strict=True):
            problems.extend(_png_problems(Path(png_dir) / name, size, entry.get(f"png{size}")))
    return problems
