# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprobación de licencias y ruedas de Geoblender (plan 001 §5.4.11; ADR-0002).

Se ejecuta con el Python de Blender desde la raíz del repositorio (órdenes en
``AGENTS.md``), sin opciones, y forma parte de ``tools/check.py`` (paso «licencias»):

- LIC-01 y LIC-02 (RF-001-22): ruedas de ``tools/wheels.toml``, lista ``wheels`` del
  manifiesto y ficheros de ``geoblender/wheels/`` (``gbtools.wheels``), con las
  expresiones SPDX evaluadas como fija ADR-0017 §3. LIC-01 valida también el lock del
  motor de cálculo, ``geoblender/jobs/runtime_lock.toml`` (spec 004, RF-004-21;
  ``gbtools.runtime_lock``), donde numpy sí entra (ADR-0017 §6).
- LIC-03 (RF-001-23): ``LICENSE``, con ``\\r\\n`` → ``\\n``, tiene el sha256 del texto
  GPL-3.0-or-later de Blender 5.2 (``GPL_SHA256``, ADR-0002), y el manifiesto declara
  exactamente ``license = ["SPDX:GPL-3.0-or-later"]``. El árbol de trabajo puede tener
  ``LICENSE`` con CRLF y git lo guarda en LF: el hash no depende de eso.
- LIC-04 (RF-001-24): ``LICENSES/CC0-1.0.txt`` es el texto oficial de CC0-1.0
  (``CC0_SHA256``); ``REUSE.toml`` tiene ``version = 1`` y una anotación CC0-1.0 para
  ``assets/**``, ``geoblender/resources/**`` y ``packaging/app_template/**``, y cada
  licencia que nombra tiene su ``LICENSES/<id>.txt``; cada carpeta con activos bajo esas
  rutas tiene un ``LICENSE`` igual (en LF) al texto CC0, que es lo que viaja en el zip;
  cada carpeta ``geoblender/thirdparty/<origen>/`` está cubierta por una anotación
  propia (``precedence = "override"``) con una licencia que no es CC0, su texto en
  ``LICENSES/`` y un ``LICENSE`` de carpeta igual a él; y no hay fuentes editables de
  activos (``.svg``, ``.xcf``, ``.psd``, ``.kra``, ``.ai``) dentro de ``geoblender/``.
  Cada fuente SVG de ``assets/`` lleva además los metadatos RDF de CC0-1.0 de II §1.7
  (``dc:rights`` «CC0-1.0», ``cc:license`` con la URL de CC0 y el autor «IMGA»; spec 003,
  T30; ``gbtools.icons.license_problems``).

Imprime cada incumplimiento como ``fichero:línea: [REGLA] mensaje``. Códigos de
salida: 0 correcto, 1 algún incumplimiento, 2 error de uso o de entorno.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en Z: (plan 001 §5.3)

import hashlib  # noqa: E402
import re  # noqa: E402
import tomllib  # noqa: E402
from collections.abc import Mapping, Sequence  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from gbtools import icons, manifest, runtime_lock, wheels  # noqa: E402
from gbtools.findings import Finding, format_findings  # noqa: E402
from gbtools.layout import (  # noqa: E402
    EXTENSION_DIR,
    RESOURCES_RELPATH,
    THIRDPARTY_RELPATH,
)
from gbtools.repo import iter_repo_files, relpath, repo_root  # noqa: E402
from gbtools.rules.text import ASSET_ROOTS  # noqa: E402

RULES = "LIC-01 a LIC-04"
RULE_GPL = "LIC-03"
RULE_ASSETS = "LIC-04"

GPL_LICENSE_RELPATH = "LICENSE"
# sha256 del texto GPL-3.0-or-later de Blender 5.2 (license/spdx/GPL-3.0-or-later.txt
# de la instalación) con los finales normalizados a LF (ADR-0002).
GPL_SHA256 = "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903"
MANIFEST_LICENSE: list[str] = ["SPDX:GPL-3.0-or-later"]

LICENSES_DIR = "LICENSES"
CC0_ID = "CC0-1.0"
CC0_RELPATH = f"{LICENSES_DIR}/{CC0_ID}.txt"
# sha256 de text/CC0-1.0.txt de la SPDX License List (spdx/license-list-data), en UTF-8
# y LF (D-6, DP-12; T17).
CC0_SHA256 = "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499"
REUSE_RELPATH = "REUSE.toml"
REUSE_VERSION = 1
# Rutas de los activos propios, CC0-1.0 (plan 001 §5.2); ASSET_ROOTS son las mismas
# carpetas, cuyo LICENSE queda fuera de TXT-02.
CC0_PATHS: tuple[str, ...] = (
    "assets/**",
    f"{RESOURCES_RELPATH}/**",
    "packaging/app_template/**",
)
THIRDPARTY_ROOT = f"{THIRDPARTY_RELPATH}/"
ASSETS_ROOT = "assets/"
EXTENSION_ROOT = f"{EXTENSION_DIR}/"
EDITABLE_SOURCE_SUFFIXES: frozenset[str] = frozenset(
    {".svg", ".xcf", ".psd", ".kra", ".ai"}
)

_LICENSE_KEY = re.compile(r"^\s*license\s*=")
_TABLE = re.compile(r"^\s*\[")
_TOML_LINE = re.compile(r"at line (\d+)")
_SPDX_SPLIT = re.compile(r"[\s()]+")
_SPDX_OPERATORS: frozenset[str] = frozenset({"AND", "OR", "WITH"})


def lf_sha256(data: bytes) -> str:
    """sha256 de ``data`` con los finales ``\\r\\n`` normalizados a ``\\n``."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _license_line(lines: Sequence[str]) -> int:
    for number, line in enumerate(lines, start=1):
        if _TABLE.match(line):
            break
        if _LICENSE_KEY.match(line):
            return number
    return 0


def check_gpl_license(root: Path) -> list[Finding]:
    """Incumplimientos de LIC-03: texto de ``LICENSE`` y licencia del manifiesto."""
    root = Path(root)
    findings: list[Finding] = []
    path = root / GPL_LICENSE_RELPATH
    if not path.is_file():
        findings.append(
            Finding(
                GPL_LICENSE_RELPATH,
                0,
                RULE_GPL,
                "no existe LICENSE: copie el texto GPL-3.0-or-later de Blender 5.2 "
                "(license/spdx/GPL-3.0-or-later.txt de la instalación; ADR-0002)",
            )
        )
    else:
        actual = lf_sha256(path.read_bytes())
        if actual != GPL_SHA256:
            findings.append(
                Finding(
                    GPL_LICENSE_RELPATH,
                    0,
                    RULE_GPL,
                    f"el texto de LICENSE, con finales LF, tiene sha256 {actual} y "
                    f"debe ser el GPL-3.0-or-later de Blender 5.2 (sha256 "
                    f"{GPL_SHA256}, ADR-0002): restáurelo sin cambios desde "
                    "license/spdx/GPL-3.0-or-later.txt de la instalación",
                )
            )

    rel = manifest.MANIFEST_RELPATH
    expected = f"license = {MANIFEST_LICENSE}".replace("'", '"')
    try:
        text = (root / rel).read_bytes().decode("utf-8").removeprefix("﻿")
        data = tomllib.loads(text)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        findings.append(
            Finding(
                rel,
                0,
                RULE_GPL,
                f"no se puede leer el manifiesto para comprobar «{expected}» ({exc})",
            )
        )
        return findings
    value = data.get("license")
    if value != MANIFEST_LICENSE:
        shown = "no está" if value is None else f"vale {value!r}"
        findings.append(
            Finding(
                rel,
                _license_line(text.split("\n")),
                RULE_GPL,
                f"«license» {shown} y debe ser exactamente «{expected}» (ADR-0002)",
            )
        )
    return findings


def _reuse_glob(pattern: str) -> re.Pattern[str]:
    """Patrón de ``path`` de ``REUSE.toml``: ``*`` no cruza «/», ``**`` sí; ``\\``
    hace literal el carácter siguiente."""
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            out.append(re.escape(pattern[index + 1]))
            index += 2
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif char == "*":
            out.append("[^/]*")
            index += 1
        else:
            out.append(re.escape(char))
            index += 1
    return re.compile("".join(out))


def _paths(annotation: Mapping[str, Any]) -> list[str]:
    value = annotation.get("path")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _identifier(annotation: Mapping[str, Any]) -> str | None:
    value = annotation.get("SPDX-License-Identifier")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _license_ids(expression: str) -> list[str]:
    """Identificadores (licencias y excepciones) de una expresión SPDX."""
    return [
        token
        for token in _SPDX_SPLIT.split(expression)
        if token and token not in _SPDX_OPERATORS
    ]


def _line_of(lines: Sequence[str], needle: str) -> int:
    for number, line in enumerate(lines, start=1):
        if needle in line:
            return number
    return 0


def _read_reuse(root: Path, findings: list[Finding]) -> list[Mapping[str, Any]] | None:
    """Anotaciones de ``REUSE.toml``; ``None`` (con su incumplimiento) si no se lee."""
    rel = REUSE_RELPATH
    path = root / rel
    if not path.is_file():
        findings.append(
            Finding(
                rel,
                0,
                RULE_ASSETS,
                "no existe REUSE.toml: declara la licencia CC0-1.0 de los activos y la "
                "de los datos de terceros (plan 001 §5.2)",
            )
        )
        return None
    try:
        text = path.read_bytes().decode("utf-8")
        data = tomllib.loads(text)
    except UnicodeDecodeError as exc:
        findings.append(Finding(rel, 0, RULE_ASSETS, f"no es UTF-8 válido ({exc})"))
        return None
    except tomllib.TOMLDecodeError as exc:
        match = _TOML_LINE.search(str(exc))
        line = int(match.group(1)) if match else 0
        findings.append(Finding(rel, line, RULE_ASSETS, f"no es TOML válido: {exc}"))
        return None
    lines = text.split("\n")
    if data.get("version") != REUSE_VERSION:
        findings.append(
            Finding(
                rel,
                _line_of(lines, "version"),
                RULE_ASSETS,
                f"«version» vale {data.get('version')!r} y debe ser {REUSE_VERSION} "
                "(formato REUSE.toml)",
            )
        )
    annotations = data.get("annotations", [])
    if not isinstance(annotations, list) or not all(
        isinstance(item, dict) for item in annotations
    ):
        findings.append(
            Finding(
                rel,
                _line_of(lines, "annotations"),
                RULE_ASSETS,
                "«annotations» debe ser una lista de tablas «[[annotations]]»",
            )
        )
        return []

    if not any(
        _identifier(item) == CC0_ID and set(CC0_PATHS) <= set(_paths(item))
        for item in annotations
    ):
        paths = ", ".join(f"«{path}»" for path in CC0_PATHS)
        findings.append(
            Finding(
                rel,
                _line_of(lines, "[[annotations]]"),
                RULE_ASSETS,
                f"ninguna anotación declara SPDX-License-Identifier = \"{CC0_ID}\" "
                f"para {paths}: los activos propios son CC0-1.0 (ADR-0002, plan 001 "
                "§5.2)",
            )
        )
    reported: set[str] = set()
    for item in annotations:
        expression = _identifier(item)
        if expression is None:
            findings.append(
                Finding(
                    rel,
                    _line_of(lines, "[[annotations]]"),
                    RULE_ASSETS,
                    "una anotación no tiene «SPDX-License-Identifier»",
                )
            )
            continue
        for license_id in _license_ids(expression):
            if license_id == CC0_ID or license_id in reported:
                continue  # el texto CC0 tiene su propia comprobación
            if not (root / LICENSES_DIR / f"{license_id}.txt").is_file():
                reported.add(license_id)
                findings.append(
                    Finding(
                        rel,
                        _line_of(lines, f'"{expression}"'),
                        RULE_ASSETS,
                        f"la licencia «{license_id}» no tiene su texto en "
                        f"{LICENSES_DIR}/{license_id}.txt",
                    )
                )
    return annotations


def _asset_folder_findings(root: Path, files: Sequence[str]) -> list[Finding]:
    """Cada carpeta con activos propios tiene un ``LICENSE`` con el texto CC0."""
    folders: dict[str, list[str]] = {}
    for rel in files:
        if rel.startswith(ASSET_ROOTS):
            folder, _, name = rel.rpartition("/")
            folders.setdefault(folder, []).append(name)
    findings: list[Finding] = []
    for folder, names in sorted(folders.items()):
        if all(name == "LICENSE" for name in names):
            continue
        rel = f"{folder}/LICENSE"
        if "LICENSE" not in names:
            findings.append(
                Finding(
                    rel,
                    0,
                    RULE_ASSETS,
                    f"falta: la carpeta «{folder}/» tiene activos y necesita un "
                    f"LICENSE con el texto de {CC0_RELPATH} (CC0-1.0; el LICENSE "
                    "viaja en el zip y REUSE.toml no)",
                )
            )
        elif lf_sha256((root / rel).read_bytes()) != CC0_SHA256:
            findings.append(
                Finding(
                    rel,
                    0,
                    RULE_ASSETS,
                    f"no es el texto de {CC0_RELPATH}: los activos propios son CC0-1.0 "
                    "(ADR-0002); cópielo sin cambios",
                )
            )
    return findings


def _svg_license_findings(root: Path, files: Sequence[str]) -> list[Finding]:
    """Cada fuente SVG de ``assets/`` lleva los metadatos CC0 de II §1.7 (spec 003)."""
    findings: list[Finding] = []
    for rel in files:
        if not rel.startswith(ASSETS_ROOT) or not rel.lower().endswith(".svg"):
            continue
        try:
            text = (root / rel).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(Finding(rel, 0, RULE_ASSETS, f"no se puede leer en UTF-8: {exc}"))
            continue
        findings.extend(
            Finding(rel, 0, RULE_ASSETS,
                    f"{problem}: los activos propios son CC0-1.0 (ADR-0002) y lo dicen")
            for problem in icons.license_problems(text)
        )
    return findings


def _thirdparty_findings(
    root: Path,
    folder: str,
    files: Sequence[str],
    annotations: Sequence[Mapping[str, Any]],
) -> list[Finding]:
    """Una carpeta ``geoblender/thirdparty/<origen>/``, con su anotación y su
    licencia."""
    covering = [
        item
        for item in annotations
        if _paths(item)
        and all(
            any(_reuse_glob(pattern).fullmatch(rel) for pattern in _paths(item))
            for rel in files
        )
    ]
    if not covering:
        return [
            Finding(
                folder,
                0,
                RULE_ASSETS,
                f"los datos de terceros de «{folder}/» no están declarados en "
                f"REUSE.toml: añada una anotación propia (path = [\"{folder}/**\"], "
                "precedence = \"override\") con su licencia, tras el ADR que los "
                "admita (plan 001 §5.3, contrato 8)",
            )
        ]
    annotation = covering[-1]  # en REUSE.toml manda la última anotación que casa
    findings: list[Finding] = []
    if annotation.get("precedence") != "override":
        findings.append(
            Finding(
                folder,
                0,
                RULE_ASSETS,
                f"la anotación de REUSE.toml que cubre «{folder}/» debe tener "
                "precedence = \"override\": es una anotación propia de esos datos",
            )
        )
    expression = _identifier(annotation)
    ids = _license_ids(expression) if expression else []
    if expression is None or len(ids) != 1 or ids[0] != expression:
        findings.append(
            Finding(
                folder,
                0,
                RULE_ASSETS,
                f"la anotación que cubre «{folder}/» debe declarar un solo "
                f"identificador SPDX (tiene {expression!r})",
            )
        )
        return findings
    if expression == CC0_ID:
        findings.append(
            Finding(
                folder,
                0,
                RULE_ASSETS,
                f"«{folder}/» son datos de terceros y se declaran como CC0-1.0: "
                "declare su licencia real (CC0 es solo para los activos propios)",
            )
        )
        return findings
    text_rel = f"{LICENSES_DIR}/{expression}.txt"
    text_path = root / text_rel
    if not text_path.is_file():
        findings.append(
            Finding(
                folder,
                0,
                RULE_ASSETS,
                f"«{folder}/» se declara {expression} y falta {text_rel} con su texto",
            )
        )
    license_rel = f"{folder}/LICENSE"
    license_path = root / license_rel
    if not license_path.is_file():
        findings.append(
            Finding(
                license_rel,
                0,
                RULE_ASSETS,
                f"falta: copie {text_rel} como LICENSE de «{folder}/» (viaja en el "
                "zip)",
            )
        )
    elif text_path.is_file() and lf_sha256(license_path.read_bytes()) != lf_sha256(
        text_path.read_bytes()
    ):
        findings.append(
            Finding(
                license_rel,
                0,
                RULE_ASSETS,
                f"no es igual a {text_rel}, la licencia que declara REUSE.toml para "
                f"«{folder}/»",
            )
        )
    return findings


def check_assets(root: Path) -> list[Finding]:
    """Incumplimientos de LIC-04: texto CC0, ``REUSE.toml``, ``LICENSE`` de las
    carpetas de activos y de datos de terceros, y fuentes editables en la extensión."""
    root = Path(root)
    findings: list[Finding] = []
    cc0_path = root / CC0_RELPATH
    if not cc0_path.is_file():
        findings.append(
            Finding(
                CC0_RELPATH,
                0,
                RULE_ASSETS,
                "no existe: copie text/CC0-1.0.txt de la SPDX License List "
                "(spdx/license-list-data), en UTF-8 y LF (D-6, DP-12)",
            )
        )
    else:
        actual = lf_sha256(cc0_path.read_bytes())
        if actual != CC0_SHA256:
            findings.append(
                Finding(
                    CC0_RELPATH,
                    0,
                    RULE_ASSETS,
                    f"no es el texto oficial de CC0-1.0: su sha256 en LF es {actual} y "
                    f"debe ser {CC0_SHA256} (text/CC0-1.0.txt de la SPDX License List, "
                    "spdx/license-list-data)",
                )
            )

    annotations = _read_reuse(root, findings) or []
    files = [relpath(root, path) for path in iter_repo_files(root)]
    findings.extend(_asset_folder_findings(root, files))
    findings.extend(_svg_license_findings(root, files))

    origins: dict[str, list[str]] = {}
    for rel in files:
        if not rel.startswith(THIRDPARTY_ROOT):
            continue
        rest = rel[len(THIRDPARTY_ROOT) :]
        if "/" not in rest:
            findings.append(
                Finding(
                    rel,
                    0,
                    RULE_ASSETS,
                    f"los datos de terceros van en {THIRDPARTY_ROOT}<origen>/, cada "
                    "carpeta con su LICENSE y su anotación en REUSE.toml (plan 001 "
                    "§5.3, contrato 8)",
                )
            )
            continue
        origins.setdefault(rest.split("/", 1)[0], []).append(rel)
    for origin, rels in sorted(origins.items()):
        findings.extend(
            _thirdparty_findings(root, THIRDPARTY_ROOT + origin, rels, annotations)
        )

    for rel in files:
        if rel.startswith(EXTENSION_ROOT) and (
            Path(rel).suffix.lower() in EDITABLE_SOURCE_SUFFIXES
        ):
            findings.append(
                Finding(
                    rel,
                    0,
                    RULE_ASSETS,
                    "es una fuente editable de un activo: va en assets/, y en "
                    f"{EXTENSION_ROOT} solo su derivado (p. ej. el PNG generado)",
                )
            )
    return sorted(findings)


def check(root: Path) -> list[Finding]:
    """Incumplimientos de las reglas de licencias bajo ``root``, ordenados."""
    return sorted(
        [
            *wheels.check(root),
            *runtime_lock.check(root),
            *check_gpl_license(root),
            *check_assets(root),
        ]
    )


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    """Ejecuta la comprobación y devuelve el código de salida.

    ``root`` (por defecto, la raíz del repositorio de este fichero) solo lo cambian las
    pruebas.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    if args:
        print(
            f"Opción no admitida: {' '.join(args)}. Uso: tools/check_licenses.py "
            "(sin opciones)",
            file=sys.stderr,
        )
        return 2
    if root is None:
        try:
            root = repo_root(Path(__file__))
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    findings = check(root)
    if findings:
        print(format_findings(findings))
        print(f"Licencias ({RULES}): NO VERDE, {len(findings)} incumplimientos")
        return 1
    print(f"Licencias ({RULES}): correcto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
