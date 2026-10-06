# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos de usuario de la extensión: lo que es de este equipo y no de un proyecto
(spec 002; RF-002-08, RF-002-13, RF-002-19, RF-002-30, RF-002-31; plan 002 §5.2).

``bl`` calcula la raíz con ``bpy.utils.extension_path_user(bl.ADDON_PACKAGE, …)`` en
``register()`` y la pasa a ``core`` como ``Path`` (``core`` no sabe de Blender). Dentro:

- ``projects/recent.json``: los 10 proyectos abiertos por última vez (RF-002-08);
- ``projects/<uid>/external_refs.json``: ``ref_uid`` → ruta completa de las fuentes de
  otro volumen (RF-002-19);
- ``projects/<uid>/checkout.json``: el registro de una copia local (original, copia,
  sesión, huellas de partida; RF-002-31);
- ``cache/<uid>/``: la caché de un proyecto abierto desde la red o en solo lectura
  (RF-002-30), y ``cache/_sin_proyecto/`` sin proyecto;
- ``readonly/<sesión>/``: las copias privadas de lectura (RF-002-13);
- ``checkouts/``: las copias locales por defecto (spec 002, D-4).

Nada de esto entra en un proyecto (ADR-0006 §5). Los JSON se escriben de forma atómica
(fichero temporal y ``os.replace``); uno que no se puede leer cuenta como vacío. Calcular
una ruta no crea ninguna carpeta: las crea quien escribe en ellas.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ValidationError

RECENT_LIMIT = 10
NO_PROJECT_CACHE = "_sin_proyecto"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class RecentProject:
    """Un proyecto de la lista de recientes."""

    uid: str
    name: str
    path: Path
    opened_at: str  # UTC ISO 8601 con milisegundos y «Z»


def _check_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.match(value):
        raise ValidationError(
            "core.userdata_id_invalid",
            "debe ser un identificador (letras, cifras, «-» y «_»): no puede contener "
            "barras, «..» ni dos puntos",
            obj="Datos de usuario",
            field=field,
            value=value,
        )
    return value


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class UserData:
    """Los datos de usuario de la extensión bajo ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # Carpetas -----------------------------------------------------------------------

    def project_dir(self, uid: str) -> Path:
        """``projects/<uid>/``."""
        return self.root / "projects" / _check_id(uid, "uid del proyecto")

    def cache_dir(self, uid: str) -> Path:
        """``cache/<uid>/``: caché de un proyecto en red o en solo lectura."""
        return self.root / "cache" / _check_id(uid, "uid del proyecto")

    def no_project_cache_dir(self) -> Path:
        """``cache/_sin_proyecto/``: caché cuando no hay proyecto abierto."""
        return self.root / "cache" / NO_PROJECT_CACHE

    def private_read_dir(self, session_uid: str) -> Path:
        """``readonly/<sesión>/``: copias privadas de lectura de esta sesión."""
        return self.root / "readonly" / _check_id(session_uid, "sesión")

    def checkouts_dir(self) -> Path:
        """``checkouts/``: carpeta por defecto de las copias locales (D-4)."""
        return self.root / "checkouts"

    # Rutas de fuentes de otro volumen (RF-002-19) -----------------------------------

    def _external_file(self, uid: str) -> Path:
        return self.project_dir(uid) / "external_refs.json"

    def external_refs(self, uid: str) -> dict[str, str]:
        """``ref_uid`` → ruta completa, de las fuentes anotadas de un proyecto."""
        data = _read_json(self._external_file(uid))
        if not isinstance(data, dict):
            return {}
        return {str(key): str(value) for key, value in data.items()}

    def set_external_ref(self, uid: str, ref_uid: str, path: Path) -> None:
        """Anota la ruta completa de la fuente ``ref_uid`` del proyecto ``uid``."""
        refs = self.external_refs(uid)
        refs[_check_id(ref_uid, "ref_uid")] = os.fspath(path)
        _write_json(self._external_file(uid), refs)

    def external_ref(self, uid: str, ref_uid: str) -> Path | None:
        """La ruta anotada, o ``None`` si en este equipo no hay anotación."""
        value = self.external_refs(uid).get(ref_uid)
        return None if value is None else Path(value)

    # Copia local de trabajo (RF-002-31) -----------------------------------------------

    def _checkout_file(self, uid: str) -> Path:
        return self.project_dir(uid) / "checkout.json"

    def checkout_record(self, uid: str) -> dict[str, Any] | None:
        """El registro de la copia local de ``uid``, o ``None``."""
        data = _read_json(self._checkout_file(uid))
        return data if isinstance(data, dict) else None

    def set_checkout_record(self, uid: str, record: Mapping[str, Any]) -> None:
        """Guarda el registro de la copia local (debe incluir ``original``)."""
        _write_json(self._checkout_file(uid), dict(record))

    def clear_checkout_record(self, uid: str) -> None:
        """Borra el registro de la copia local (si no hay, no hace nada)."""
        target = self._checkout_file(uid)
        if target.exists():
            target.unlink()

    def checkout_original(self, uid: str) -> Path | None:
        """La raíz del proyecto original de una copia local, o ``None``."""
        record = self.checkout_record(uid)
        original = None if record is None else record.get("original")
        return Path(original) if isinstance(original, str) and original else None

    # Proyectos recientes (RF-002-08) --------------------------------------------------

    def _recent_file(self) -> Path:
        return self.root / "projects" / "recent.json"

    def recent_projects(self) -> list[RecentProject]:
        """Los proyectos recientes, el más reciente primero (como mucho 10)."""
        data = _read_json(self._recent_file())
        if not isinstance(data, list):
            return []
        found: list[RecentProject] = []
        for item in data:
            if isinstance(item, dict) and all(
                isinstance(item.get(key), str) for key in ("uid", "name", "path", "opened_at")
            ):
                found.append(
                    RecentProject(item["uid"], item["name"], Path(item["path"]), item["opened_at"])
                )
        return found[:RECENT_LIMIT]

    def add_recent(self, uid: str, name: str, path: Path, opened_at: str) -> None:
        """Pone el proyecto el primero de la lista (sin repetirlo) y conserva 10."""
        _check_id(uid, "uid del proyecto")
        entries = [item for item in self.recent_projects() if item.uid != uid]
        entries.insert(0, RecentProject(uid, name, Path(path), opened_at))
        _write_json(
            self._recent_file(),
            [
                {
                    "uid": item.uid,
                    "name": item.name,
                    "path": os.fspath(item.path),
                    "opened_at": item.opened_at,
                }
                for item in entries[:RECENT_LIMIT]
            ],
        )
