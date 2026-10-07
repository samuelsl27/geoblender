# SPDX-License-Identifier: GPL-3.0-or-later
"""Lock del motor de cálculo: regla LIC-01 (spec 004, T24; RF-004-21; plan 004 §5.2.5;
ADR-0009 y ADR-0017).

``jobs/runtime_lock.toml`` de la extensión fija los paquetes del motor de cálculo (el numpy
de PyPI con OpenBLAS y lo que pidan las specs siguientes). La extensión lo lee para
instalar el motor (``jobs.runtime.read_lock``) y ``tools/lock_runtime.py`` lo actualiza.
Esta comprobación, parte de ``tools/check_licenses.py``, exige:

- la cabecera ``schema = "geoblender.runtime_lock/1"``, ``python = "3.13"`` y
  ``platform = "win_amd64"``, al menos una tabla ``[[package]]`` y ninguna otra clave;
- en cada paquete: ``name``; ``version`` exacta; ``filename`` con las etiquetas de
  ADR-0009 (``cp313``/``abi3`` + ``win_amd64`` o ``py3-none-any``), su nombre y su
  versión; ``url`` de ``https://files.pythonhosted.org/`` que acaba en ese fichero;
  ``sha256`` de 64 hexadecimales; ``size`` e ``installed_size``, enteros positivos (bytes
  de la rueda e instalados, que mide ``tools/lock_runtime.py``); ``license`` y cada
  elemento de ``bundled_licenses`` admitidos como fija ADR-0017 §3
  (``gbtools.wheels.evaluate_license``); ``required_by``, las specs que lo piden
  (ADR-0009: nada «por si acaso»); ni claves desconocidas ni paquetes repetidos.
- ``FORBIDDEN`` no se aplica: el motor necesita numpy (ADR-0017 §6). Cada rueda del lock
  es la de PyPI sin modificar (url y sha256 de PyPI), así que la condición de LGPL y EUPL
  (``unmodified``) se cumple por construcción.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import wheels
from .findings import Finding
from .layout import RUNTIME_LOCK_RELPATH

LOCK_RELPATH = RUNTIME_LOCK_RELPATH
RULE = wheels.RULE_WHEEL  # LIC-01
LOCK_SCHEMA = "geoblender.runtime_lock/1"
LOCK_PYTHON = "3.13"
LOCK_PLATFORM = "win_amd64"
PYPI_FILES_URL = "https://files.pythonhosted.org/"
TABLE = "package"
HEADER: Mapping[str, str] = {
    "schema": LOCK_SCHEMA,
    "python": LOCK_PYTHON,
    "platform": LOCK_PLATFORM,
}
PACKAGE_KEYS: tuple[str, ...] = (
    "name",
    "version",
    "filename",
    "url",
    "sha256",
    "size",
    "installed_size",
    "license",
    "bundled_licenses",
    "required_by",
)
TOOL_HINT = "ejecute tools/lock_runtime.py"

_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_SPEC = re.compile(r"\d{3}")
_TOML_LINE = re.compile(r"at line (\d+)")


def _label(entry: Mapping[str, Any], index: int) -> str:
    name = entry.get("name")
    if isinstance(name, str) and name.strip():
        return f"el paquete «{name}» del lock"
    return f"el paquete n.º {index + 1} del lock"


def header_problems(data: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Problemas de la cabecera y de la lista de paquetes como ``(clave, mensaje)``."""
    problems: list[tuple[str, str]] = []
    for key, expected in HEADER.items():
        if data.get(key) != expected:
            problems.append(
                (key, f"«{key}» vale {data.get(key)!r} y debe ser «{expected}» (plan "
                 "004 §5.2.5)")
            )
    for key in data:
        if key not in HEADER and key != TABLE:
            problems.append(
                (key, f"clave desconocida «{key}»: cada paquete va en una tabla "
                 f"[[{TABLE}]]")
            )
    packages = data.get(TABLE)
    if not isinstance(packages, list) or not all(isinstance(p, dict) for p in packages):
        problems.append((TABLE, f"«{TABLE}» debe ser una lista de tablas [[{TABLE}]]"))
    elif not packages:
        problems.append((TABLE, f"el lock no tiene ningún paquete ([[{TABLE}]])"))
    return problems


def package_problems(entry: Mapping[str, Any], index: int = 0) -> list[tuple[str, str]]:
    """Problemas LIC-01 de una tabla ``[[package]]`` como ``(clave, mensaje)``; la clave
    vacía señala la tabla entera."""
    label = _label(entry, index)
    problems: list[tuple[str, str]] = []

    def add(key: str, message: str) -> None:
        problems.append((key, f"{label}: {message}"))

    for key in entry:
        if key not in PACKAGE_KEYS:
            add(key, f"clave desconocida «{key}» (admitidas: {', '.join(PACKAGE_KEYS)})")
    missing = [key for key in PACKAGE_KEYS if key not in entry]
    if missing:
        keys = ", ".join(f"«{key}»" for key in missing)
        add("", f"{'faltan' if len(missing) > 1 else 'falta'} {keys} (plan 004 §5.2.5; "
            f"{TOOL_HINT})")

    texts: dict[str, str] = {}
    for key in ("name", "version", "filename", "url", "sha256", "license"):
        value = entry.get(key)
        if key not in entry:
            continue
        if not isinstance(value, str) or not value.strip():
            add(key, f"«{key}» debe ser un texto no vacío")
        else:
            texts[key] = value

    name, version = texts.get("name"), texts.get("version")
    if version is not None and not wheels.exact_version(version):
        add("version", f"«version» vale «{version}» y debe ser una versión exacta")
    sha = texts.get("sha256")
    if sha is not None and not _SHA256.fullmatch(sha):
        add("sha256", f"«sha256» debe tener 64 hexadecimales (el que publica PyPI; "
            f"{TOOL_HINT})")
    filename = texts.get("filename")
    if filename is not None:
        try:
            tags = wheels.parse_filename(filename)
        except ValueError as exc:
            add("filename", str(exc))
        else:
            if not wheels.tag_allowed(tags):
                add(
                    "filename",
                    f"las etiquetas «{tags.python}-{tags.abi}-{tags.platform}» no son "
                    "«cp313-win_amd64» (o «cp313-abi3-win_amd64») ni «py3-none-any» "
                    "(ADR-0009)",
                )
            if name is not None and wheels.normalize_name(tags.name) != (
                wheels.normalize_name(name)
            ):
                add("filename", f"«{filename}» no es una rueda de «{name}»")
            if version is not None and tags.version != version:
                add("filename", f"«{filename}» es de la versión «{tags.version}» y "
                    f"«version» vale «{version}»")
    url = texts.get("url")
    if url is not None and (
        not url.startswith(PYPI_FILES_URL)
        or (filename is not None and not url.endswith("/" + filename))
    ):
        add("url", f"«url» vale «{url}» y debe ser la de la rueda en PyPI "
            f"({PYPI_FILES_URL}…/<filename>; {TOOL_HINT})")
    for key in ("size", "installed_size"):
        if key not in entry:
            continue
        value = entry[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            add(key, f"«{key}» vale {value!r} y debe ser un número de bytes mayor que 0 "
                f"(lo mide tools/lock_runtime.py; {TOOL_HINT})")

    license_expression = texts.get("license")
    if license_expression is not None:
        verdict = wheels.evaluate_license(license_expression)
        if not verdict.allowed:
            add("license", verdict.reason)
    if "bundled_licenses" in entry:
        for key, message in wheels.bundled_problems(
            entry["bundled_licenses"], unmodified=True
        ):
            add(key, message)
    required = entry.get("required_by")
    if "required_by" in entry and (
        not isinstance(required, list)
        or not required
        or not all(isinstance(spec, str) and _SPEC.fullmatch(spec) for spec in required)
    ):
        add("required_by", f"«required_by» vale {required!r} y debe ser la lista de las "
            "specs que piden el paquete («004»…; ADR-0009)")
    return problems


def _packages(data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    packages = data.get(TABLE)
    if not isinstance(packages, list):
        return []
    return [entry for entry in packages if isinstance(entry, dict)]


def check_text(text: str, rel: str = LOCK_RELPATH) -> list[Finding]:
    """Incumplimientos de LIC-01 del lock con el texto ``text`` (``rel``, su ruta en los
    mensajes)."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        match = _TOML_LINE.search(str(exc))
        line = int(match.group(1)) if match else 0
        return [Finding(rel, line, RULE, f"no es TOML válido: {exc}")]
    lines: Sequence[str] = text.split("\n")
    findings = [
        Finding(rel, wheels.top_key_line(lines, key, 1), RULE, message)
        for key, message in header_problems(data)
    ]
    packages = _packages(data)
    spans = wheels.table_spans(lines, TABLE)
    if len(spans) != len(packages):
        spans = []
    seen: dict[str, int] = {}
    for index, entry in enumerate(packages):
        span = spans[index] if spans else None
        findings.extend(
            Finding(rel, wheels.key_line(lines, span, key), RULE, message)
            for key, message in package_problems(entry, index)
        )
        name = entry.get("name")
        if isinstance(name, str):
            key = wheels.normalize_name(name)
            if key in seen:
                findings.append(
                    Finding(rel, wheels.key_line(lines, span, ""), RULE,
                            f"el paquete «{name}» está repetido en el lock: una sola "
                            f"tabla [[{TABLE}]] por paquete")
                )
            else:
                seen[key] = index
    return sorted(findings)


def check(root: Path) -> list[Finding]:
    """Incumplimientos de LIC-01 del lock del motor de cálculo bajo ``root``."""
    path = Path(root) / LOCK_RELPATH
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return [
            Finding(LOCK_RELPATH, 0, RULE, "no existe: la extensión lo necesita para "
                    f"instalar el motor de cálculo (plan 004 §5.2.5; {TOOL_HINT})")
        ]
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding(LOCK_RELPATH, 0, RULE, f"no se puede leer en UTF-8: {exc}")]
    return check_text(text)
