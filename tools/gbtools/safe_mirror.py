# SPDX-License-Identifier: GPL-3.0-or-later
"""El espejo seguro del NAS: «avisar y no borrar» (spec 007, HU-007-7; plan 007 §5.2 y
§5.4.6 a §5.4.9; ADR-0023).

El NAS es el espejo de la carpeta del proyecto (la documentación con el código dentro,
los dos ``.git`` incluidos) y solo lo escribe ``tools/publish.py``. Para no perder nunca
lo que alguien deje allí, cada espejo se compara con el **estado del último espejo** de
ese destino, que guarda el perfil local de quien publica (``%LOCALAPPDATA%\\Geoblender\\
espejo``), fuera de los repositorios y del destino:

- ``estado-<clave>.json``: de cada fichero del destino, su sha256 y el tamaño y la fecha
  (``mtime_ns``) con que se comprobó; y sus carpetas. ``<clave>`` = los 16 primeros
  caracteres hexadecimales del sha256 de la ruta real del destino (``os.path.realpath``,
  que da la UNC de una unidad de red), sin distinguir mayúsculas: ``Z:\\…`` y
  ``\\\\servidor\\recurso\\…`` son el mismo destino (plan 007 §2.1, 17).
- ``foto-*.json``: la foto inicial de un destino, tomada antes del primer espejo (sin
  carpetas: las suyas son las madres de sus ficheros). Solo vale si no hay estado, y se
  encuentra por la ruta real de su ``destino``, no por el texto. Nunca se modifica.

Un estado que existe y no se puede leer no se sustituye por la foto
(:class:`StateUnreadable`): la publicación remite a ``--rehacer-estado``. Las rutas del
estado se validan (relativas, con «/», sin «..»): nunca se usan fuera del destino.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .layout import MIRROR_STATE_PARTS

FORMAT = 1
KIND_STATE = "estado"
STATE_PREFIX = "estado-"
PHOTO_GLOB = "foto-*.json"
KEY_LENGTH = 16
ENV_LOCAL_APPDATA = "LOCALAPPDATA"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MirrorError(Exception):
    """El espejo no se puede hacer: el mensaje dice por qué."""


class StateUnreadable(MirrorError):
    """El estado del último espejo de un destino existe y no se puede leer."""


@dataclass(frozen=True)
class FileState:
    """Un fichero del destino tal como se comprobó: tamaño, ``mtime_ns`` y sha256."""

    size: int
    mtime_ns: int
    sha256: str


@dataclass
class MirrorState:
    """La base de la comparación de un destino: el estado de su último espejo o, en el
    primero, su foto inicial (``photo``). Rutas relativas con «/», con su mayúscula."""

    destination: str
    source: str
    taken: str
    who: str = ""
    repos: dict[str, Any] = field(default_factory=dict)
    files: dict[str, FileState] = field(default_factory=dict)
    folders: set[str] = field(default_factory=set)
    photo: bool = False
    path: Path | None = None  # el fichero del que se leyó


def state_dir(environ: Mapping[str, str]) -> Path:
    """La carpeta de los estados y las fotos: ``%LOCALAPPDATA%\\Geoblender\\espejo``,
    con el ``LOCALAPPDATA`` de ``environ``."""
    value = environ.get(ENV_LOCAL_APPDATA, "").strip()
    if not value:
        raise MirrorError(
            f"no se sabe dónde está el estado del espejo: falta la variable "
            f"{ENV_LOCAL_APPDATA} (el perfil local del usuario de Windows)"
        )
    return Path(value).joinpath(*MIRROR_STATE_PARTS)


def real_destination(destination: str | os.PathLike[str]) -> str:
    """La ruta real del destino, sin distinguir mayúsculas (``normcase``)."""
    return os.path.normcase(os.path.realpath(os.path.abspath(destination)))


def destination_key(destination: str | os.PathLike[str]) -> str:
    """Los 16 primeros caracteres del sha256 de la ruta real del destino."""
    digest = hashlib.sha256(real_destination(destination).encode("utf-8")).hexdigest()
    return digest[:KEY_LENGTH]


def state_file(destination: str | os.PathLike[str], environ: Mapping[str, str]) -> Path:
    """El fichero del estado del último espejo de ``destination``."""
    return state_dir(environ) / f"{STATE_PREFIX}{destination_key(destination)}.json"


def valid_rel(rel: object) -> bool:
    """Si ``rel`` es una ruta relativa con «/», sin «..», «.», vacíos ni unidad."""
    if not isinstance(rel, str) or not rel or "\\" in rel or ":" in rel:
        return False
    if PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).is_absolute():
        return False
    return all(part not in ("", ".", "..") for part in rel.split("/"))


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_files(data: Mapping[str, Any]) -> dict[str, FileState]:
    raw = data["ficheros"]
    if not isinstance(raw, dict):
        raise ValueError("«ficheros» no es un objeto")
    files: dict[str, FileState] = {}
    for rel, info in raw.items():
        if not valid_rel(rel):
            raise ValueError(f"la ruta «{rel}» no es relativa al destino")
        if not isinstance(info, dict):
            raise ValueError(f"«{rel}» no tiene tamaño, fecha y sha256")
        size, mtime, sha = info.get("size"), info.get("mtime_ns"), info.get("sha256")
        if not (_is_int(size) and _is_int(mtime) and isinstance(sha, str)):
            raise ValueError(f"«{rel}» no tiene tamaño, fecha y sha256 válidos")
        if not _SHA256.match(sha):
            raise ValueError(f"el sha256 de «{rel}» no lo es")
        files[rel] = FileState(size, mtime, sha)
    return files


def parents_of(paths: object) -> set[str]:
    """Las carpetas que contienen a cada ruta de ``paths`` (todas las madres)."""
    folders: set[str] = set()
    for rel in paths:  # type: ignore[attr-defined]
        parts = str(rel).split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            folders.add("/".join(parts[:depth]))
    return folders


def _text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key, "")
    return value if isinstance(value, str) else ""


def _read_state(path: Path) -> MirrorState:
    data = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("no es un objeto JSON")
    if data.get("formato") != FORMAT or data.get("tipo") != KIND_STATE:
        raise ValueError(f"no es un estado del formato {FORMAT}")
    if not isinstance(data.get("destino"), str):
        raise ValueError("le falta «destino»")
    folders = data["carpetas"]
    if not isinstance(folders, list) or not all(valid_rel(rel) for rel in folders):
        raise ValueError("«carpetas» no es una lista de rutas relativas al destino")
    repos = data.get("repositorios", {})
    return MirrorState(
        destination=data["destino"],
        source=_text(data, "origen"),
        taken=_text(data, "tomada"),
        who=_text(data, "quien"),
        repos=repos if isinstance(repos, dict) else {},
        files=_parse_files(data),
        folders=set(folders),
        photo=False,
        path=path,
    )


def _read_photo(path: Path) -> MirrorState:
    data = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(data, dict) or data.get("formato") != FORMAT:
        raise ValueError(f"no es una foto del formato {FORMAT}")
    if not isinstance(data.get("destino"), str):
        raise ValueError("le falta «destino»")
    files = _parse_files(data)
    return MirrorState(
        destination=data["destino"],
        source=_text(data, "origen"),
        taken=_text(data, "tomada"),
        files=files,
        folders=parents_of(files),
        photo=True,
        path=path,
    )


def load_base(destination: Path, environ: Mapping[str, str]) -> MirrorState | None:
    """La base de la comparación de ``destination`` (RF-007-31): su estado; si no hay,
    la foto cuyo ``destino`` tiene la misma ruta real; si tampoco, ``None``. Un estado
    que existe y no se lee es :class:`StateUnreadable` (nunca se vuelve a la foto); una
    foto que no se lee se salta (no se sabe de qué destino es)."""
    path = state_file(destination, environ)
    if path.exists():
        try:
            return _read_state(path)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise StateUnreadable(
                f"el estado del último espejo de este destino («{path.name}» en "
                f"«{path.parent}») no se puede leer: {exc}"
            ) from exc
    real = real_destination(destination)
    for photo in sorted(state_dir(environ).glob(PHOTO_GLOB)):
        try:
            base = _read_photo(photo)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if real_destination(base.destination) == real:
            return base
    return None
