# SPDX-License-Identifier: GPL-3.0-or-later
"""Ruedas fijadas en ``tools/wheels.toml``: reglas LIC-01 y LIC-02 (plan 001 §5.4.11).

``tools/wheels.toml`` tiene ``schema_version = 1`` y una tabla ``[[wheel]]`` por rueda
(plan 001 §5.2; ADR-0002, ADR-0009). Reglas (RF-001-22):

- LIC-01, por rueda: ``name``, ``version`` (exacta), ``filename``, ``sha256`` (64
  hexadecimales), ``license``, ``target`` (``extension`` o ``dev``), ``spec`` y ``adr``;
  nombre normalizado (PEP 503) fuera de ``FORBIDDEN``; etiquetas del fichero
  ``cp313``/``abi3`` + ``win_amd64`` o ``py3-none-any``, con el nombre y la versión de
  la rueda; licencia de ``ALLOWED_LICENSES``, o ``A OR B`` (basta una permitida) o
  ``A AND B`` (todas permitidas), sin paréntesis ni mezcla de ``OR`` y ``AND``;
  ``unmodified = true`` si la licencia elegida es LGPL o EUPL; cada licencia de
  ``bundled_licenses`` (bibliotecas nativas que trae la rueda) en la lista blanca o en
  ``ADR_ALLOWED_BUNDLED``.
- LIC-02, coherencia: la lista ``wheels`` del manifiesto (``./wheels/<fichero>``), las
  ruedas de destino ``extension`` y los ficheros de ``geoblender/wheels/`` coinciden,
  y cada fichero tiene el sha256 fijado. Blender empaqueta todo lo que haya en esa
  carpeta, esté o no en el manifiesto (plan 001 §2.1, 2).
"""

from __future__ import annotations

import hashlib
import os
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from . import manifest
from .findings import Finding
from .layout import WHEELS_DIR_RELPATH

WHEELS_TOML_RELPATH = "tools/wheels.toml"
RULE_WHEEL = "LIC-01"
RULE_COHERENCE = "LIC-02"
SCHEMA_VERSION = 1
FETCH_SCRIPT_RELPATH = "tools/fetch_wheels.py"
FETCH_HINT = f"ejecute {FETCH_SCRIPT_RELPATH}"
# Almacén local o del NAS con las ruedas fijadas (plan 001 §5.4.12): la carpeta por
# defecto de «tools/fetch_wheels.py --desde».
ENV_WHEELHOUSE = "GEOBLENDER_WHEELHOUSE"

TARGETS: tuple[str, ...] = ("extension", "dev")
REQUIRED_FIELDS: tuple[str, ...] = (
    "name",
    "version",
    "filename",
    "sha256",
    "license",
    "target",
    "spec",
    "adr",
)
OPTIONAL_FIELDS: tuple[str, ...] = ("bundled_licenses", "unmodified")

# Lista blanca de ADR-0002 §4 (identificadores SPDX).
ALLOWED_LICENSES: frozenset[str] = frozenset(
    {
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "PSF-2.0",
        "ISC",
        "Zlib",
        "MPL-2.0",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "EUPL-1.2",
    }
)
# Solo como rueda de PyPI sin modificar (ADR-0002 §4).
UNMODIFIED_REQUIRED: frozenset[str] = frozenset(
    {
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "EUPL-1.2",
    }
)
# Nombres normalizados (PEP 503) que nunca entran (ADR-0002 §5, ADR-0009).
FORBIDDEN: frozenset[str] = frozenset({"numpy", "triangle", "meshpy", "pseudoflow"})
# Licencias que un ADR aceptado admite solo en «bundled_licenses». Vacía hasta que se
# acepte ADR-0017 (spec 004, D-5).
ADR_ALLOWED_BUNDLED: frozenset[str] = frozenset()

_FORBIDDEN_REASONS: Mapping[str, str] = {
    "numpy": (
        "la extensión usa el numpy de Blender y nunca lo empaqueta; el cálculo pesado "
        "usa el del motor de cálculo (ADR-0009)"
    ),
    "triangle": "su licencia no es comercial ni de código abierto (ADR-0002)",
    "meshpy": "incluye Triangle, con licencia no comercial (ADR-0002)",
    "pseudoflow": "su licencia no es comercial ni de código abierto (ADR-0002)",
}
_CANONICAL_LICENSES: Mapping[str, str] = {
    license.lower(): license for license in ALLOWED_LICENSES
}
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
# Versión exacta de PEP 440 (sin época): nunca un rango ni un comodín.
_EXACT_VERSION = re.compile(
    r"\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?"
    r"(?:\+[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*)?"
)
_SPEC = re.compile(r"\d{3}")
_ADR = re.compile(r"ADR-\d{4}")
_BUILD_TAG = re.compile(r"\d\w*")
_OPERATOR = re.compile(r"\s+(OR|AND)\s+")
_WHEEL_HEADER = re.compile(r"^\s*\[\[\s*wheel\s*\]\]")
_TABLE_HEADER = re.compile(r"^\s*\[")
_TOML_LINE = re.compile(r"at line (\d+)")


@dataclass(frozen=True)
class WheelSpec:
    """Una rueda fijada en ``tools/wheels.toml``."""

    name: str
    version: str
    filename: str
    sha256: str
    license: str
    target: Literal["extension", "dev"]
    spec: str
    adr: str
    unmodified: bool = False
    bundled_licenses: tuple[str, ...] = ()


@dataclass(frozen=True)
class WheelTags:
    """Partes del nombre de un fichero de rueda (PEP 427), sin la etiqueta de
    compilación."""

    name: str
    version: str
    python: str
    abi: str
    platform: str


def normalize_name(name: str) -> str:
    """Nombre de distribución normalizado (PEP 503): ``Py_Proj`` → ``py-proj``."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_filename(filename: str) -> WheelTags:
    """Nombre, versión y etiquetas de un fichero de rueda (PEP 427):
    ``<nombre>-<versión>[-<compilación>]-<python>-<abi>-<plataforma>.whl``.

    Lanza ``ValueError`` si no es un nombre de fichero de rueda.
    """
    if "/" in filename or "\\" in filename:
        raise ValueError(
            f"«{filename}» debe ser solo el nombre del fichero, sin carpeta"
        )
    if not filename.endswith(".whl"):
        raise ValueError(f"«{filename}» no es un fichero de rueda («.whl»)")
    parts = filename[: -len(".whl")].split("-")
    if len(parts) == 6:
        if not _BUILD_TAG.fullmatch(parts[2]):
            raise ValueError(
                f"«{filename}»: la etiqueta de compilación «{parts[2]}» debe empezar "
                "por un dígito"
            )
        del parts[2]
    if len(parts) != 5 or not all(parts):
        raise ValueError(
            f"«{filename}» no sigue "
            "«<nombre>-<versión>-<python>-<abi>-<plataforma>.whl»"
        )
    return WheelTags(*parts)


def tag_allowed(tags: WheelTags) -> bool:
    """Etiquetas de ADR-0009: ``cp313`` + (``cp313`` o ``abi3``) + ``win_amd64``, o
    (``py3`` o ``py2.py3``) + ``none`` + ``any``."""
    if tags.python == "cp313":
        return tags.abi in ("cp313", "abi3") and tags.platform == "win_amd64"
    return (
        tags.python in ("py3", "py2.py3")
        and tags.abi == "none"
        and tags.platform == "any"
    )


def _parse_expression(expression: str) -> tuple[str | None, list[str]]:
    """``(operador, términos)`` de una expresión SPDX sin paréntesis.

    Lanza ``ValueError`` con el motivo si está vacía, tiene paréntesis o mezcla
    ``OR`` y ``AND``.
    """
    text = expression.strip()
    if not text:
        raise ValueError("la licencia está vacía")
    if "(" in text or ")" in text:
        raise ValueError(
            f"«{expression}» tiene paréntesis: escriba un identificador, «A OR B» o "
            "«A AND B»; una expresión compuesta necesita revisión y un ADR"
        )
    pieces = _OPERATOR.split(text)
    operators = set(pieces[1::2])
    if len(operators) > 1:
        raise ValueError(
            f"«{expression}» mezcla «OR» y «AND»: sin paréntesis la precedencia es "
            "ambigua; escriba solo «A OR B» o solo «A AND B»"
        )
    return (operators.pop() if operators else None), pieces[0::2]


def _canonical(term: str) -> str | None:
    return _CANONICAL_LICENSES.get(term.lower())


def license_allowed(expression: str) -> tuple[bool, str]:
    """``(admitida, motivo)`` de una expresión de licencia frente a la lista blanca.

    Un identificador de ``ALLOWED_LICENSES``; ``A OR B``, si alguna lo está;
    ``A AND B``, si lo están todas. El motivo está vacío si se admite.
    """
    try:
        operator, terms = _parse_expression(expression)
    except ValueError as exc:
        return False, str(exc)
    refused = [term for term in terms if _canonical(term) is None]
    whitelist = f"la lista blanca de ADR-0002 ({', '.join(sorted(ALLOWED_LICENSES))})"
    if operator == "OR":
        if len(refused) < len(terms):
            return True, ""
        return False, (
            f"ninguna de las alternativas de «{expression}» está en {whitelist}; una "
            "licencia nueva necesita un ADR"
        )
    if not refused:
        return True, ""
    listed = ", ".join(f"«{term}»" for term in refused)
    verb = "no están" if len(refused) > 1 else "no está"
    return False, f"{listed} {verb} en {whitelist}; una licencia nueva necesita un ADR"


def unmodified_required(expression: str) -> bool:
    """Verdadero si la licencia que se aplica es LGPL o EUPL (ADR-0002 §4).

    Con ``A OR B`` se elige una alternativa permitida sin esa condición si la hay; con
    ``A AND B`` se aplican todas.
    """
    try:
        operator, terms = _parse_expression(expression)
    except ValueError:
        return False
    canonical = [name for name in (_canonical(term) for term in terms) if name]
    if operator == "OR":
        return bool(canonical) and all(
            name in UNMODIFIED_REQUIRED for name in canonical
        )
    return any(name in UNMODIFIED_REQUIRED for name in canonical)


def bundled_allowed(expression: str) -> bool:
    """Licencia de una biblioteca incluida: lista blanca o ``ADR_ALLOWED_BUNDLED``."""
    return expression in ADR_ALLOWED_BUNDLED or license_allowed(expression)[0]


def wheelhouse(environ: Mapping[str, str] | None = None) -> str | None:
    """Carpeta de ``GEOBLENDER_WHEELHOUSE`` (sin espacios ni comillas alrededor), o
    ``None`` si no está definida o está vacía."""
    env = os.environ if environ is None else environ
    value = env.get(ENV_WHEELHOUSE, "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value or None


def fetch_command(
    python: str | os.PathLike[str], environ: Mapping[str, str] | None = None
) -> str:
    """La orden de PowerShell que descarga las ruedas fijadas, desde la raíz del
    repositorio; con ``--desde`` y el almacén si ``GEOBLENDER_WHEELHOUSE`` está
    definida (no necesita red si el almacén las tiene)."""
    command = f'& "{python}" {FETCH_SCRIPT_RELPATH}'
    store = wheelhouse(environ)
    return f'{command} --desde "{store}"' if store else command


def sha256_file(path: Path) -> str:
    """sha256 del fichero, en hexadecimal en minúsculas."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _label(entry: Mapping[str, Any], index: int) -> str:
    for key in ("name", "filename"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return f"la rueda «{value}»"
    return f"la rueda n.º {index + 1}"


def entry_problems(entry: Mapping[str, Any], index: int = 0) -> list[tuple[str, str]]:
    """Problemas LIC-01 de una tabla ``[[wheel]]`` como ``(clave, mensaje)``.

    La clave vacía señala la tabla entera (p. ej. una clave que falta).
    """
    label = _label(entry, index)
    known = REQUIRED_FIELDS + OPTIONAL_FIELDS
    problems: list[tuple[str, str]] = []

    def add(key: str, message: str) -> None:
        problems.append((key, f"{label}: {message}"))

    for key in entry:
        if key not in known:
            add(key, f"clave desconocida «{key}» (admitidas: {', '.join(known)})")
    values: dict[str, str] = {}
    missing: list[str] = []
    for key in REQUIRED_FIELDS:
        value = entry.get(key)
        if value is None:
            missing.append(key)
        elif not isinstance(value, str) or not value.strip():
            add(key, f"«{key}» debe ser un texto no vacío")
        else:
            values[key] = value
    if missing:
        keys = ", ".join(f"«{key}»" for key in missing)
        add("", f"{'faltan' if len(missing) > 1 else 'falta'} {keys} (plan 001 §5.2)")

    name = values.get("name")
    if name is not None and normalize_name(name) in FORBIDDEN:
        reason = _FORBIDDEN_REASONS[normalize_name(name)]
        add("name", f"está prohibida: {reason}")
    version = values.get("version")
    if version is not None and not _EXACT_VERSION.fullmatch(version):
        add(
            "version",
            f"«version» vale «{version}» y debe ser una versión exacta (p. ej. "
            "«1.5.7»), nunca un rango ni un comodín",
        )
    sha = values.get("sha256")
    if sha is not None and not _SHA256.fullmatch(sha):
        add("sha256", "«sha256» debe tener 64 hexadecimales (el que publica PyPI)")
    target = values.get("target")
    if target is not None and target not in TARGETS:
        add("target", f"«target» vale «{target}» y debe ser «extension» o «dev»")
    spec = values.get("spec")
    if spec is not None and not _SPEC.fullmatch(spec):
        add("spec", f"«spec» vale «{spec}» y debe ser el número de la spec («006»)")
    adr = values.get("adr")
    if adr is not None and not _ADR.fullmatch(adr):
        add(
            "adr",
            f"«adr» vale «{adr}» y debe ser «ADR-NNNN» (constitución, principio 4)",
        )

    filename = values.get("filename")
    if filename is not None:
        try:
            tags = parse_filename(filename)
        except ValueError as exc:
            add("filename", str(exc))
        else:
            if not tag_allowed(tags):
                add(
                    "filename",
                    f"las etiquetas «{tags.python}-{tags.abi}-{tags.platform}» no son "
                    "«cp313-win_amd64» (o «cp313-abi3-win_amd64») ni «py3-none-any» "
                    "(ADR-0009)",
                )
            if name is not None and normalize_name(tags.name) != normalize_name(name):
                add("filename", f"«{filename}» no es una rueda de «{name}»")
            if version is not None and tags.version != version:
                add(
                    "filename",
                    f"«{filename}» es de la versión «{tags.version}» y «version» vale "
                    f"«{version}»",
                )

    unmodified = entry.get("unmodified")
    if unmodified is not None and not isinstance(unmodified, bool):
        add("unmodified", "«unmodified» debe ser «true» o «false»")
    license_expression = values.get("license")
    if license_expression is not None:
        ok, reason = license_allowed(license_expression)
        if not ok:
            add("license", reason)
        elif unmodified_required(license_expression) and unmodified is not True:
            add(
                "license",
                f"la licencia «{license_expression}» solo se admite en una rueda de "
                "PyPI sin modificar: declárelo con «unmodified = true» (ADR-0002 §4)",
            )

    bundled = entry.get("bundled_licenses")
    if bundled is not None:
        if not isinstance(bundled, list) or not all(
            isinstance(item, str) for item in bundled
        ):
            add(
                "bundled_licenses",
                "«bundled_licenses» debe ser una lista de licencias SPDX",
            )
        else:
            for item in bundled:
                if not bundled_allowed(item):
                    add(
                        "bundled_licenses",
                        f"una biblioteca incluida tiene la licencia «{item}», que no "
                        "está en la lista blanca de ADR-0002 ni en la de un ADR "
                        "aceptado (ADR_ALLOWED_BUNDLED)",
                    )
    return problems


def _document_problems(data: Mapping[str, Any]) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            (
                "schema_version",
                f"«schema_version» vale {data.get('schema_version')!r} y esta versión "
                f"de las herramientas lee {SCHEMA_VERSION}",
            )
        )
    for key in data:
        if key not in ("schema_version", "wheel"):
            problems.append(
                (
                    key,
                    f"clave desconocida «{key}»: cada rueda va en una tabla [[wheel]]",
                )
            )
    wheel = data.get("wheel", [])
    if not isinstance(wheel, list) or not all(isinstance(w, dict) for w in wheel):
        problems.append(("wheel", "«wheel» debe ser una lista de tablas «[[wheel]]»"))
    return problems


def _entries(data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    wheel = data.get("wheel", [])
    if not isinstance(wheel, list):
        return []
    return [entry for entry in wheel if isinstance(entry, dict)]


def _read(path: Path) -> tuple[str, dict[str, Any]]:
    """Texto y contenido de ``tools/wheels.toml``; lanza ``ValueError`` si no se lee."""
    try:
        text = Path(path).read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise ValueError(
            f"no existe «{WHEELS_TOML_RELPATH}» (con «schema_version = 1» basta)"
        ) from None
    except UnicodeDecodeError as exc:
        raise ValueError(f"no es UTF-8 válido ({exc.reason})") from None
    try:
        return text, tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"no es TOML válido: {exc}") from None


def load(path: Path) -> list[WheelSpec]:
    """Las ruedas de ``tools/wheels.toml``; ``ValueError`` con todos los problemas
    LIC-01 si alguna no cumple."""
    _text, data = _read(path)
    problems = [message for _key, message in _document_problems(data)]
    entries = _entries(data)
    for index, entry in enumerate(entries):
        problems.extend(message for _key, message in entry_problems(entry, index))
    names = [normalize_name(str(entry.get("name", ""))) for entry in entries]
    problems.extend(
        f"la rueda «{name}» está repetida"
        for name in sorted({n for n in names if names.count(n) > 1})
    )
    if problems:
        raise ValueError(f"«{WHEELS_TOML_RELPATH}»: " + "; ".join(problems))
    return [
        WheelSpec(
            name=entry["name"],
            version=entry["version"],
            filename=entry["filename"],
            sha256=entry["sha256"].lower(),
            license=entry["license"],
            target=entry["target"],
            spec=entry["spec"],
            adr=entry["adr"],
            unmodified=entry.get("unmodified", False),
            bundled_licenses=tuple(entry.get("bundled_licenses", ())),
        )
        for entry in entries
    ]


def _spans(lines: Sequence[str]) -> list[tuple[int, int]]:
    """``(inicio, fin)`` (índices desde 0) de cada tabla ``[[wheel]]``."""
    spans: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        if _WHEEL_HEADER.match(line):
            end = next(
                (
                    later
                    for later in range(index + 1, len(lines))
                    if _TABLE_HEADER.match(lines[later])
                ),
                len(lines),
            )
            spans.append((index, end))
    return spans


def _key_line(lines: Sequence[str], span: tuple[int, int] | None, key: str) -> int:
    """Línea (desde 1) de ``key`` en la tabla ``span``, o la de su cabecera."""
    if span is None:
        return 0
    start, end = span
    if key:
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for index in range(start + 1, end):
            if pattern.match(lines[index]):
                return index + 1
    return start + 1


def _top_key_line(lines: Sequence[str], key: str) -> int:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for index, line in enumerate(lines):
        if _TABLE_HEADER.match(line):
            break
        if pattern.match(line):
            return index + 1
    return 1 if key == "schema_version" else 0


def _manifest_line(lines: Sequence[str], entry: str) -> int:
    for index, line in enumerate(lines):
        if f'"{entry}"' in line or f"'{entry}'" in line:
            return index + 1
    for index, line in enumerate(lines):
        if line.startswith("wheels"):
            return index + 1
    return 0


def _coherence(
    root: Path, entries: Sequence[Mapping[str, Any]], lines: Sequence[int]
) -> list[Finding]:
    """LIC-02: manifiesto, ruedas ``extension`` y ``geoblender/wheels/``."""
    findings: list[Finding] = []
    declared: dict[str, tuple[str, int, str]] = {}
    for entry, line in zip(entries, lines):
        filename = entry.get("filename")
        sha = entry.get("sha256")
        target = entry.get("target")
        if not isinstance(filename, str) or not isinstance(sha, str):
            continue
        if not isinstance(target, str):
            continue
        if target in TARGETS and "/" not in filename and "\\" not in filename:
            declared.setdefault(filename, (sha.lower(), line, target))
    extension = {name: v for name, v in declared.items() if v[2] == "extension"}

    rel_manifest = manifest.MANIFEST_RELPATH
    listed: dict[str, int] = {}
    try:
        manifest_text = (Path(root) / rel_manifest).read_bytes().decode("utf-8")
        data = tomllib.loads(manifest_text.removeprefix("﻿"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        findings.append(
            Finding(
                rel_manifest,
                0,
                RULE_COHERENCE,
                f"no se puede leer el manifiesto para comparar sus ruedas ({exc})",
            )
        )
    else:
        manifest_lines = manifest_text.split("\n")
        for item in manifest.wheel_files(data):
            line = _manifest_line(manifest_lines, item)
            name = item.removeprefix(manifest.WHEELS_FOLDER)
            if (
                not item.startswith(manifest.WHEELS_FOLDER)
                or not name
                or "/" in name
                or "\\" in name
            ):
                findings.append(
                    Finding(
                        rel_manifest,
                        line,
                        RULE_COHERENCE,
                        f"la entrada «{item}» de «wheels» debe ser "
                        f"«{manifest.WHEELS_FOLDER}<fichero>.whl»: {FETCH_HINT}",
                    )
                )
                continue
            listed[name] = line

    for name, line in sorted(listed.items()):
        if name in extension:
            continue
        if name in declared:
            message = (
                f"la rueda «{name}» es de desarrollo (target = \"dev\" en "
                f"{WHEELS_TOML_RELPATH}) y no se empaqueta: quítela de «wheels» "
                f"({FETCH_HINT})"
            )
        else:
            message = (
                f"la rueda «{name}» está en «wheels» pero no en {WHEELS_TOML_RELPATH} "
                "con target = \"extension\": fíjela allí con versión, sha256 y "
                f"licencia (ADR-0009) y {FETCH_HINT}"
            )
        findings.append(Finding(rel_manifest, line, RULE_COHERENCE, message))
    for name, (_sha, line, _target) in sorted(extension.items()):
        if name not in listed:
            findings.append(
                Finding(
                    WHEELS_TOML_RELPATH,
                    line,
                    RULE_COHERENCE,
                    f"la rueda «{name}» (target = \"extension\") no está en «wheels» "
                    f"del manifiesto: {FETCH_HINT}",
                )
            )

    present: dict[str, Path] = {}
    wheels_dir = Path(root) / WHEELS_DIR_RELPATH
    if wheels_dir.is_dir():
        with os.scandir(wheels_dir) as scan:
            items = sorted(scan, key=lambda item: item.name)
        for item in items:
            rel = f"{WHEELS_DIR_RELPATH}/{item.name}"
            if item.is_file(follow_symlinks=False) and item.name in extension:
                present[item.name] = Path(item.path)
                continue
            if item.name in declared:
                why = (
                    f"es una rueda de desarrollo (target = \"dev\" en "
                    f"{WHEELS_TOML_RELPATH}): va solo a .deps/site/"
                )
            else:
                why = (
                    "no es una rueda de la extensión declarada en "
                    f"{WHEELS_TOML_RELPATH} (target = \"extension\")"
                )
            findings.append(
                Finding(
                    rel,
                    0,
                    RULE_COHERENCE,
                    f"«{item.name}» {why}, y Blender mete en el zip todo lo que hay en "
                    f"{WHEELS_DIR_RELPATH}/: bórrela o {FETCH_HINT}",
                )
            )
    for name, (sha, line, _target) in sorted(extension.items()):
        path = present.get(name)
        if path is None:
            findings.append(
                Finding(
                    WHEELS_TOML_RELPATH,
                    line,
                    RULE_COHERENCE,
                    f"falta «{WHEELS_DIR_RELPATH}/{name}»: {FETCH_HINT}",
                )
            )
            continue
        actual = sha256_file(path)
        if actual != sha:
            findings.append(
                Finding(
                    f"{WHEELS_DIR_RELPATH}/{name}",
                    0,
                    RULE_COHERENCE,
                    f"su sha256 es {actual} y {WHEELS_TOML_RELPATH} fija {sha}: no es "
                    f"la rueda fijada; {FETCH_HINT}",
                )
            )
    return findings


def check(root: Path) -> list[Finding]:
    """Incumplimientos de LIC-01 y LIC-02 bajo ``root``."""
    root = Path(root)
    rel = WHEELS_TOML_RELPATH
    try:
        text, data = _read(root / rel)
    except ValueError as exc:
        match = _TOML_LINE.search(str(exc))
        line = int(match.group(1)) if match else 0
        return [Finding(rel, line, RULE_WHEEL, str(exc))]
    lines = text.split("\n")
    findings = [
        Finding(rel, _top_key_line(lines, key), RULE_WHEEL, message)
        for key, message in _document_problems(data)
    ]
    entries = _entries(data)
    spans = _spans(lines)
    if len(spans) != len(entries):
        spans = []
    entry_lines: list[int] = []
    for index, entry in enumerate(entries):
        span = spans[index] if spans else None
        entry_lines.append(_key_line(lines, span, ""))
        findings.extend(
            Finding(rel, _key_line(lines, span, key), RULE_WHEEL, message)
            for key, message in entry_problems(entry, index)
        )
    seen: dict[str, int] = {}
    for index, entry in enumerate(entries):
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        key = normalize_name(name)
        if key in seen:
            findings.append(
                Finding(
                    rel,
                    entry_lines[index],
                    RULE_WHEEL,
                    f"la rueda «{name}» está repetida (ya está en la línea "
                    f"{entry_lines[seen[key]]}): una sola tabla por paquete",
                )
            )
        else:
            seen[key] = index
    findings.extend(_coherence(root, entries, entry_lines))
    return sorted(findings)
