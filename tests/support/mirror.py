# SPDX-License-Identifier: GPL-3.0-or-later
"""Estados y fotos del espejo para las pruebas de la spec 007 (plan 007 §5.2).

Escriben a mano, en el perfil local de la prueba (una carpeta temporal que hace de
``LOCALAPPDATA``), la foto inicial de un destino (``foto-*.json``) o el estado de su
último espejo (``estado-<clave>.json``), con el formato que lee
``gbtools.safe_mirror.load_base``. Nunca tocan el perfil real del puesto.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from tests.support.repo import tools_on_path

tools_on_path()

from gbtools import layout  # noqa: E402

PHOTO_NAME = "foto-prueba.json"
TAKEN = "2026-10-05T23:09:01"


def state_folder(profile: Path) -> Path:
    """La carpeta de estados del espejo dentro del perfil local ``profile``."""
    return Path(profile).joinpath(*layout.MIRROR_STATE_PARTS)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_of_text(text: str) -> str:
    """El sha256 de ``text`` escrito en UTF-8 (como lo escriben las pruebas)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def describe(folder: Path) -> dict[str, dict[str, Any]]:
    """Cada fichero bajo ``folder`` (rutas relativas con «/»): su tamaño, su
    ``mtime_ns`` y su sha256, como los guarda el estado."""
    found: dict[str, dict[str, Any]] = {}
    for current, _dirs, files in os.walk(folder):
        for name in files:
            path = Path(current) / name
            info = path.stat()
            rel = path.relative_to(folder).as_posix()
            found[rel] = {
                "size": info.st_size,
                "mtime_ns": info.st_mtime_ns,
                "sha256": sha256_of(path),
            }
    return found


def folders_of(folder: Path) -> list[str]:
    """Las carpetas bajo ``folder`` (rutas relativas con «/»)."""
    return sorted(
        (Path(current) / name).relative_to(folder).as_posix()
        for current, dirs, _files in os.walk(folder)
        for name in dirs
    )


def _write(path: Path, data: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))
    return path


def write_photo(
    profile: Path,
    destination: str | os.PathLike[str],
    files: Mapping[str, Mapping[str, Any]] | None = None,
    name: str = PHOTO_NAME,
) -> Path:
    """Una foto inicial del destino ``destination`` (por defecto, de lo que tiene ahora)."""
    data = {
        "formato": 1,
        "descripcion": "Foto de prueba",
        "destino": str(destination),
        "origen": "proyecto de prueba",
        "tomada": TAKEN,
        "ficheros": dict(describe(Path(destination)) if files is None else files),
    }
    return _write(state_folder(profile) / name, data)


def write_state(
    profile: Path,
    destination: Path,
    files: Mapping[str, Mapping[str, Any]] | None = None,
    folders: Iterable[str] | None = None,
    state_path: Path | None = None,
) -> Path:
    """El estado del último espejo de ``destination`` (por defecto, lo que tiene ahora),
    en ``state_path`` o en el fichero que le toca (``safe_mirror.state_file``)."""
    from gbtools import safe_mirror

    data = {
        "formato": 1,
        "tipo": "estado",
        "destino": str(destination),
        "destino_real": os.path.realpath(destination),
        "origen": "proyecto de prueba",
        "tomada": "2026-10-05T23:40:00",
        "quien": "pruebas@equipo",
        "repositorios": {},
        "ficheros": dict(describe(destination) if files is None else files),
        "carpetas": list(folders_of(destination) if folders is None else folders),
    }
    target = state_path or safe_mirror.state_file(destination, {"LOCALAPPDATA": str(profile)})
    return _write(target, data)
