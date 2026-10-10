# SPDX-License-Identifier: GPL-3.0-or-later
"""El manifiesto de la extensión, ``geoblender/blender_manifest.toml`` (plan 001 §5.2).

Es la fuente única de la versión (``convenciones.md`` §3). Reglas:

- MAN-01 (ADR-0003, ADR-0009): sin BOM; ``id = "geoblender"``, ``type = "add-on"``,
  ``license = ["SPDX:GPL-3.0-or-later"]``, ``blender_version_min = "5.2.0"`` y
  ``platforms = ["windows-x64"]``; ``[permissions] files`` presente; lema y motivos de
  permiso de 64 caracteres o menos y sin puntuación final (la misma comprobación que
  hace Blender); ``AGENTS.md``, ``CLAUDE.md`` y ``__pycache__/`` en
  ``[build] paths_exclude_pattern``; ``numpy`` nunca en ``wheels``.
- NOM-04 (ADR-0011): ``version`` casa la expresión oficial de SemVer 2.0.0.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .findings import Finding
from .layout import MANIFEST_RELPATH
from .repo import read_bytes

RULE_MANIFEST = "MAN-01"
RULE_SEMVER = "NOM-04"

# Expresión oficial de semver.org para SemVer 2.0.0.
SEMVER_RE: re.Pattern[str] = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

EXPECTED: Mapping[str, object] = {
    "id": "geoblender",
    "type": "add-on",
    "license": ["SPDX:GPL-3.0-or-later"],
    "blender_version_min": "5.2.0",
    "platforms": ["windows-x64"],
}
REQUIRED_EXCLUDES: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md", "__pycache__/")
TERSE_MAX_LENGTH = 64  # TERSE_DESCRIPTION_MAX_LENGTH de Blender 5.2
FORBIDDEN_WHEELS: frozenset[str] = frozenset({"numpy"})
WHEELS_FOLDER = "./wheels/"

_BOM = b"\xef\xbb\xbf"
_TOML_LINE = re.compile(r"at line (\d+)")
_TABLE = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*(?:#.*)?$")
_WHEELS_BLOCK = re.compile(r"^wheels[ \t]*=[ \t]*\[[^\]]*\]", re.MULTILINE)


def load(path: Path) -> dict[str, Any]:
    """Lee el manifiesto (UTF-8 estricto; con BOM, ``tomllib`` lo rechaza)."""
    return tomllib.loads(Path(path).read_bytes().decode("utf-8"))


def blender_min(manifest: Mapping[str, Any]) -> tuple[int, int, int]:
    """``blender_version_min`` como tupla: ``"5.2.0"`` → ``(5, 2, 0)``."""
    value = manifest.get("blender_version_min")
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError(
            f"«blender_version_min» debe ser «X.Y.Z» con enteros, no {value!r}"
        )
    major, minor, patch = (int(part) for part in value.split("."))
    return major, minor, patch


def exclude_patterns(manifest: Mapping[str, Any]) -> list[str]:
    """Patrones de ``[build] paths_exclude_pattern`` (lista vacía si no hay)."""
    build = manifest.get("build", {})
    patterns = build.get("paths_exclude_pattern", []) if isinstance(build, dict) else []
    return [str(pattern) for pattern in patterns]


def wheel_files(manifest: Mapping[str, Any]) -> list[str]:
    """Entradas de ``wheels`` tal como están escritas (``./wheels/<fichero>``)."""
    return [str(wheel) for wheel in manifest.get("wheels", [])]


def terse_text_problem(value: str) -> str | None:
    """Problema de un lema o motivo de permiso para Blender, o ``None`` si vale.

    Igual que Blender 5.2: como mucho 64 caracteres, sin espacios al principio ni al
    final, y el último carácter alfanumérico o un cierre de paréntesis.
    """
    if len(value) > TERSE_MAX_LENGTH:
        return f"tiene {len(value)} caracteres y Blender admite {TERSE_MAX_LENGTH}"
    if not value.strip():
        return "está vacío"
    if value != value.strip():
        return "empieza o termina con espacios"
    if not (value[-1].isalnum() or value[-1] in ")]}"):
        return f"termina con «{value[-1]}»: Blender no admite puntuación final"
    return None


def with_wheels(text: str, filenames: Sequence[str], where: str = "") -> str:
    """El texto del manifiesto con el bloque ``wheels = [...]`` sustituido por
    ``./wheels/<fichero>`` (finales LF); el resto, igual.

    Lanza ``ValueError`` si el texto no tiene el bloque (``where`` nombra el fichero en
    el mensaje).
    """
    if not _WHEELS_BLOCK.search(text):
        raise ValueError(
            f"«{where or MANIFEST_RELPATH}» no tiene un bloque «wheels = [...]» al "
            "principio de una línea: añádalo (puede estar vacío, «wheels = []») antes "
            "de descargar ruedas"
        )
    if filenames:
        entries = "".join(f'  "{WHEELS_FOLDER}{name}",\n' for name in filenames)
        block = f"wheels = [\n{entries}]"
    else:
        block = "wheels = []"
    new_text = _WHEELS_BLOCK.sub(lambda _match: block, text, count=1)
    return new_text.replace("\r\n", "\n")


def rewrite_wheels(path: Path, filenames: Sequence[str]) -> bool:
    """Sustituye solo el bloque ``wheels = [...]`` por ``./wheels/<fichero>``.

    ``filenames`` son nombres de fichero de rueda, sin carpeta. El resto del manifiesto
    queda igual byte a byte; se escribe en UTF-8 sin BOM y con finales LF, y solo si
    cambia algo (si no, ni se reescribe ni cambia su fecha). Devuelve si lo escribió.
    Lanza ``ValueError`` (sin escribir nada) si el manifiesto no tiene el bloque.
    """
    path = Path(path)
    raw = path.read_bytes()
    new_raw = with_wheels(raw.decode("utf-8"), filenames, str(path)).encode("utf-8")
    if new_raw == raw:
        return False
    path.write_bytes(new_raw)
    return True


def _key_line(lines: Sequence[str], key: str, table: str | None = None) -> int:
    """Línea (desde 1) de ``key`` en ``table`` (``None``: fuera de las tablas)."""
    current: str | None = None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for number, line in enumerate(lines, start=1):
        header = _TABLE.match(line)
        if header and not line.lstrip().startswith("[["):
            current = header.group(1)
            continue
        if current == table and pattern.match(line):
            return number
    return 0


def _wheel_distribution(entry: str) -> str:
    name = entry.replace("\\", "/").rsplit("/", 1)[-1].split("-", 1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def _field_findings(data: Mapping[str, Any], lines: Sequence[str]) -> list[Finding]:
    rel = MANIFEST_RELPATH
    findings: list[Finding] = []

    def add(rule: str, key: str, message: str, table: str | None = None) -> None:
        findings.append(Finding(rel, _key_line(lines, key, table), rule, message))

    for key, expected in EXPECTED.items():
        if key not in data:
            add(RULE_MANIFEST, key, f"falta «{key}»; debe ser {expected!r} (ADR-0003)")
        elif data[key] != expected:
            add(
                RULE_MANIFEST,
                key,
                f"«{key}» vale {data[key]!r} y debe ser {expected!r} (ADR-0003)",
            )

    version = data.get("version")
    if not isinstance(version, str) or not SEMVER_RE.fullmatch(version):
        add(
            RULE_SEMVER,
            "version",
            f"«version» vale {version!r} y debe ser SemVer 2.0.0 («X.Y.Z», p. ej. "
            "«0.1.0» o «1.0.0-rc.1»; ADR-0011)",
        )

    tagline = data.get("tagline")
    if not isinstance(tagline, str):
        add(RULE_MANIFEST, "tagline", "falta «tagline», el lema de la extensión")
    elif (problem := terse_text_problem(tagline)) is not None:
        add(RULE_MANIFEST, "tagline", f"el lema «{tagline}» {problem}")

    permissions = data.get("permissions")
    if not isinstance(permissions, dict) or "files" not in permissions:
        add(
            RULE_MANIFEST,
            "files",
            "falta «[permissions] files» con el motivo del acceso a ficheros",
            table="permissions",
        )
    if isinstance(permissions, dict):
        for name, reason in permissions.items():
            if not isinstance(reason, str):
                add(
                    RULE_MANIFEST,
                    name,
                    f"el permiso «{name}» debe llevar su motivo como texto",
                    table="permissions",
                )
            elif (problem := terse_text_problem(reason)) is not None:
                add(
                    RULE_MANIFEST,
                    name,
                    f"el motivo del permiso «{name}» («{reason}») {problem}",
                    table="permissions",
                )

    patterns = exclude_patterns(data)
    missing = [pattern for pattern in REQUIRED_EXCLUDES if pattern not in patterns]
    if missing:
        add(
            RULE_MANIFEST,
            "paths_exclude_pattern",
            "faltan en «[build] paths_exclude_pattern»: "
            + ", ".join(f"«{pattern}»" for pattern in missing)
            + " (no deben llegar al zip)",
            table="build",
        )

    for entry in wheel_files(data):
        if _wheel_distribution(entry) in FORBIDDEN_WHEELS:
            add(
                RULE_MANIFEST,
                "wheels",
                f"la rueda «{entry}» es numpy: la extensión usa el numpy de Blender y "
                "nunca lo empaqueta (ADR-0009)",
            )
    return findings


def check(root: Path) -> list[Finding]:
    """Incumplimientos de MAN-01 y NOM-04 en el manifiesto de ``root``."""
    path = Path(root) / MANIFEST_RELPATH
    rel = MANIFEST_RELPATH
    if not path.is_file():
        return [
            Finding(rel, 0, RULE_MANIFEST, "no existe el manifiesto de la extensión")
        ]
    raw = read_bytes(path)
    findings: list[Finding] = []
    if raw.startswith(_BOM):
        findings.append(
            Finding(
                rel,
                1,
                RULE_MANIFEST,
                "empieza por BOM: Blender no lo valida («Invalid statement (at line 1, "
                "column 1)»); guárdelo en UTF-8 sin BOM",
            )
        )
        raw = raw[len(_BOM) :]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        findings.append(
            Finding(rel, 0, RULE_MANIFEST, f"no es UTF-8 válido ({exc.reason})")
        )
        return sorted(findings)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        match = _TOML_LINE.search(str(exc))
        line = int(match.group(1)) if match else 0
        findings.append(Finding(rel, line, RULE_MANIFEST, f"no es TOML válido: {exc}"))
        return sorted(findings)
    findings.extend(_field_findings(data, text.split("\n")))
    return sorted(findings)
