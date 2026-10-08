# SPDX-License-Identifier: GPL-3.0-or-later
"""Vectores de referencia del normalizador ``gbch/1`` (spec 008, T05 y T06; RF-008-08;
ADR-0024 §6): ``tests/data/core/content/golden_gbch1.json``.

Cada caso describe una entrada pequeña (su tipo, sus declaraciones y sus datos en una forma
que JSON puede guardar) y sus dos hashes esperados. :func:`build` la pasa por
``core.content`` y devuelve su ``ContentDigest``; las pruebas comparan sus hashes con los
guardados.

Una versión publicada del normalizador no cambia: un hash guardado que deja de coincidir es un
cambio de forma (una versión nueva), nunca un dato que se regenera. Por eso :func:`fill_missing`
solo **añade** los hashes de los casos nuevos y para si uno escrito no coincide. Para añadir
casos, se escriben a mano en el JSON y después, desde la raíz del código::

    & $PY -B -s -X utf8 -m tests.support.content_golden

Marcas en los valores: ``{"nan": true}``, ``{"inf": 1}``, ``{"inf": -1}`` y
``{"f64": "<16 cifras hexadecimales>"}`` (los bits exactos de un float64, para NaN con otra
carga); un trozo de documento es un texto (UTF-8) o ``{"b64": …}``; una parte de un compuesto
puede citar el hash de datos de otro caso con ``{"case": id}``.
"""

from __future__ import annotations

import base64
import json
import struct
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

GOLDEN: Path = ROOT / "tests" / "data" / "core" / "content" / "golden_gbch1.json"
HASH_KEYS: tuple[str, str] = ("data_sha256", "content_sha256")
METHODS: tuple[str, ...] = ("grid", "document", "composite")
"""Los métodos de ``ContentHasher`` que saben construir los casos (uno por caso)."""
_COMPACT_WIDTH = 96


def load(path: Path = GOLDEN) -> dict[str, Any]:
    """El fichero de vectores de referencia, tal cual."""
    return json.loads(path.read_text(encoding="utf-8"))


def index(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Los casos por su ``id`` (``ValueError`` si alguno se repite)."""
    found: dict[str, Mapping[str, Any]] = {}
    for case in document["cases"]:
        if case["id"] in found:
            raise ValueError(f"el caso «{case['id']}» está repetido")
        found[case["id"]] = case
    return found


def method_of(case: Mapping[str, Any]) -> str:
    """El método de ``ContentHasher`` del caso (la única clave de :data:`METHODS`)."""
    methods = [name for name in METHODS if name in case]
    if len(methods) != 1:
        raise ValueError(f"el caso «{case['id']}» tiene que tener uno de {METHODS}")
    return methods[0]


def decode_float(value: object) -> float:
    """Un número o una marca (``nan``, ``inf``, ``f64``) como ``float`` de Python (los bits de
    ``f64`` se conservan tal cual, también la carga de un NaN)."""
    if isinstance(value, Mapping):
        if value.get("nan") is True and len(value) == 1:
            return float("nan")
        if set(value) == {"inf"} and value["inf"] in (1, -1):
            return float("inf") * value["inf"]
        if set(value) == {"f64"}:
            return struct.unpack(">d", bytes.fromhex(value["f64"]))[0]
        raise ValueError(f"marca desconocida: {value!r}")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{value!r} no es un número")
    return value


def decode_grid(spec: Mapping[str, Any]) -> tuple[dict[str, Any], np.ndarray]:
    """La cabecera (con el sin dato descodificado) y la matriz de un caso ``grid``."""
    header = dict(spec["header"])
    if isinstance(header.get("nodata"), Mapping):
        header["nodata"] = decode_float(header["nodata"])
    dtype = np.dtype(spec["dtype"])
    rows = spec["values"]
    if dtype.kind == "f":
        bits = [
            [struct.unpack("<Q", struct.pack("<d", decode_float(item)))[0] for item in row]
            for row in rows
        ]
        wide = np.array(bits, dtype="<u8").view("<f8")
        with np.errstate(invalid="ignore", over="ignore"):
            values = wide.astype(dtype)
    else:
        values = np.array(rows, dtype=dtype)
    return header, values


def decode_chunks(spec: Mapping[str, Any]) -> list[bytes]:
    """Los trozos de un caso ``document``: textos en UTF-8 o ``{"b64": …}``."""
    chunks: list[bytes] = []
    for chunk in spec["chunks"]:
        if isinstance(chunk, str):
            chunks.append(chunk.encode("utf-8"))
        else:
            chunks.append(base64.b64decode(chunk["b64"], validate=True))
    return chunks


def build(case: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> Any:
    """El ``ContentDigest`` del caso, calculado con ``core.content``."""
    content = import_geoblender("core.content")
    hasher = content.ContentHasher(
        case["kind"], declarations=case["declarations"], reader=case.get("reader", "")
    )
    method = method_of(case)
    if method == "grid":
        header, values = decode_grid(case["grid"])
        hasher.grid(header, [values])
    elif method == "document":
        hasher.document(decode_chunks(case["document"]))
    else:
        parts: dict[str, tuple[str, str]] = {}
        for name, (kind, data) in case["composite"]["parts"].items():
            if isinstance(data, Mapping):
                data = build(by_id[data["case"]], by_id).data_sha256
            parts[name] = (kind, data)
        hasher.composite(parts)
    return hasher.digest()


def fill_missing(path: Path = GOLDEN) -> tuple[list[str], list[str]]:
    """Añade los hashes que faltan y reescribe el fichero; nunca cambia uno escrito.

    Devuelve ``(rellenados, discrepancias)`` con los ``id``; si hay alguna discrepancia, no
    escribe nada."""
    document = load(path)
    by_id = index(document)
    filled: list[str] = []
    mismatched: list[str] = []
    for case in document["cases"]:
        digest = build(case, by_id)
        found = {key: getattr(digest, key) for key in HASH_KEYS}
        if all(key in case for key in HASH_KEYS):
            if any(case[key] != found[key] for key in HASH_KEYS):
                mismatched.append(case["id"])
            continue
        if any(key in case for key in HASH_KEYS):
            mismatched.append(case["id"])
            continue
        case.update(found)
        filled.append(case["id"])
    if not mismatched and filled:
        path.write_text(dumps(document), encoding="utf-8", newline="\n")
    return filled, mismatched


def dumps(value: Any) -> str:
    """El JSON del fichero: dos espacios de sangría y, en una sola línea, lo que cabe en
    :data:`_COMPACT_WIDTH` caracteres (las filas de valores, las marcas, las partes)."""
    return _dump(value, 0) + "\n"


def _dump(value: Any, level: int) -> str:
    compact = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if not isinstance(value, Mapping | list) or len(compact) <= _COMPACT_WIDTH:
        return compact
    inner = "  " * (level + 1)
    outer = "  " * level
    if isinstance(value, Mapping):
        items = [
            f"{inner}{json.dumps(key, ensure_ascii=False)}: {_dump(item, level + 1)}"
            for key, item in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + outer + "}"
    items = [inner + _dump(item, level + 1) for item in value]
    return "[\n" + ",\n".join(items) + "\n" + outer + "]"


def main(argv: Sequence[str] | None = None) -> int:
    """Rellena los hashes que faltan; código 1 si alguno escrito no coincide."""
    filled, mismatched = fill_missing()
    for name in filled:
        print(f"rellenado: {name}")
    for name in mismatched:
        print(f"NO COINCIDE (no se escribe nada): {name}", file=sys.stderr)
    if not filled and not mismatched:
        print("nada que rellenar")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
