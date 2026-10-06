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

**Comparación** (plan 007 §5.4.7, RF-007-29): el origen (:func:`scan_source`, el sha256
de cada fichero de la carpeta del proyecto) y el destino (:func:`scan_destination`, el
tamaño y la fecha de cada fichero, sin leerlo) se recorren sin lo excluido
(``layout.MIRROR_EXCLUDED``, D-17) y sin seguir enlaces. :func:`destination_changes`
compara el destino con la base **sin distinguir mayúsculas** (como NTFS y el recurso
SMB): un fichero con el tamaño y la fecha del estado no ha cambiado; si difieren, se lee
su sha256 (con su tamaño y fecha justo antes y justo después). Es un cambio del NAS
(nuevo, cambiado, borrado, o una carpeta nueva aunque esté vacía o solo tenga
excluidos) salvo que el destino ya tenga lo del PC (mismo sha256, o falte en los dos),
solo haya cambiado la fecha, o sea lo que iba a dejar un espejo en curso de este PC
(``estado-<clave>.en-curso.json``). Lo observado de cada fichero (tamaño, fecha y
sha256 comprobados) es lo que el espejo mira otra vez antes de tocarlo. Límite
declarado: un fichero editado en el NAS que conserva tamaño y fecha no se ve sin leer
todo el NAS.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .ignore import IgnoreSpec
from .layout import CODE_DIR_IN_DOCS, MIRROR_EXCLUDED, MIRROR_STATE_PARTS

FORMAT = 1
KIND_STATE = "estado"
KIND_PENDING = "en-curso"
STATE_PREFIX = "estado-"
PENDING_SUFFIX = ".en-curso.json"
PHOTO_GLOB = "foto-*.json"
KEY_LENGTH = 16
ENV_LOCAL_APPDATA = "LOCALAPPDATA"
HASH_CHUNK = 1 << 20
READ_ATTEMPTS = 3  # lecturas de un fichero que cambia mientras se lee su sha256
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

# Tipos de cambio del destino (RF-007-29) y repositorio de cada ruta.
NEW = "nuevo"
CHANGED = "cambiado"
DELETED = "borrado"
NEW_FOLDER = "carpeta nueva"
REPO_CODE = "código"
REPO_DOCS = "documentación"
GIT_FOLDER = ".git"

# Las exclusiones del espejo, sin distinguir mayúsculas (NTFS y SMB no las distinguen).
_EXCLUDED = IgnoreSpec.from_lines(pattern.casefold() for pattern in MIRROR_EXCLUDED)


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


@dataclass(frozen=True)
class DestChange:
    """Un cambio del destino desde el último espejo: su ruta (con «/» y su mayúscula),
    su tipo (``NEW``, ``CHANGED``, ``DELETED`` o ``NEW_FOLDER``) y si está dentro de un
    ``.git``."""

    path: str
    kind: str
    in_git: bool

    @property
    def repo(self) -> str:
        """El repositorio de la ruta: el código (su carpeta) o la documentación."""
        return repo_of(self.path)


@dataclass
class SourceTree:
    """La carpeta del proyecto, sin lo excluido: el sha256 de cada fichero, sus
    carpetas (también las vacías) y el tamaño y la fecha con que se leyó cada sha256."""

    files: dict[str, str] = field(default_factory=dict)
    folders: set[str] = field(default_factory=set)
    stats: dict[str, tuple[int, int]] = field(default_factory=dict)


@dataclass
class DestinationTree:
    """El destino sin leer ningún fichero: tamaño y ``mtime_ns`` de cada uno, sus
    carpetas y lo excluido que se encontró (las carpetas, con «/» final)."""

    files: dict[str, tuple[int, int]] = field(default_factory=dict)
    folders: set[str] = field(default_factory=set)
    excluded: list[str] = field(default_factory=list)


@dataclass
class Pending:
    """Lo que iba a dejar un espejo en curso de este PC (rutas sin distinguir
    mayúsculas): el sha256 de cada fichero, los borrados, sus temporales y las carpetas
    que crea."""

    files: dict[str, str] = field(default_factory=dict)
    deleted: set[str] = field(default_factory=set)
    temps: set[str] = field(default_factory=set)
    folders: set[str] = field(default_factory=set)


def fold(rel: str) -> str:
    """La clave de una ruta sin distinguir mayúsculas."""
    return rel.casefold()


def in_git(rel: str) -> bool:
    """Si la ruta está dentro de un ``.git`` (de cualquiera de los dos repositorios)."""
    return any(part.casefold() == GIT_FOLDER for part in rel.split("/"))


def repo_of(rel: str) -> str:
    """``REPO_CODE`` si la ruta está en la carpeta del código; si no, ``REPO_DOCS``."""
    first = rel.split("/", 1)[0]
    return REPO_CODE if first.casefold() == CODE_DIR_IN_DOCS.casefold() else REPO_DOCS


def is_excluded(rel: str, is_dir: bool = False) -> bool:
    """Si el espejo deja fuera la ruta ``rel`` (o una carpeta suya): ni la copia, ni la
    compara, ni la borra (D-17)."""
    return _EXCLUDED.matches(fold(rel), is_dir)


def sha256_of(path: Path) -> str:
    """El sha256 de un fichero, leído por trozos."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_case_clashes(paths: Iterable[str]) -> None:
    """:class:`MirrorError` si dos rutas solo difieren en mayúsculas: en NTFS y en el
    recurso SMB serían el mismo fichero."""
    seen: dict[str, str] = {}
    for rel in sorted(paths):
        other = seen.setdefault(fold(rel), rel)
        if other != rel:
            raise MirrorError(
                f"«{other}» y «{rel}» solo difieren en mayúsculas: en el destino serían el "
                "mismo fichero; renombre uno de los dos en el PC"
            )


def _walk(root: Path, links_allowed: bool) -> tuple[dict[str, os.stat_result], set[str], list[str]]:
    """Recorre ``root`` sin seguir enlaces ni lo excluido: (ficheros con su ``lstat``,
    carpetas, excluidos encontrados). Un enlace, si no se admite, es :class:`MirrorError`;
    si se admite (el destino), cuenta como fichero."""
    files: dict[str, os.stat_result] = {}
    folders: set[str] = set()
    excluded: list[str] = []
    pending = [(Path(root), "")]
    while pending:
        current, prefix = pending.pop()
        with os.scandir(current) as listing:
            entries = sorted(listing, key=lambda entry: entry.name)
        for entry in entries:
            rel = prefix + entry.name
            link = entry.is_symlink() or entry.is_junction()
            is_dir = not link and entry.is_dir(follow_symlinks=False)
            if _EXCLUDED.matches_entry(fold(rel), is_dir):
                excluded.append(rel + "/" if is_dir else rel)
                continue
            if link and not links_allowed:
                raise MirrorError(
                    f"«{rel}» es un enlace simbólico o una unión en la carpeta del "
                    "proyecto: el espejo no copia enlaces (el NAS es un recurso SMB); "
                    "sustitúyalo por el fichero o la carpeta real"
                )
            if is_dir:
                folders.add(rel)
                pending.append((Path(entry.path), rel + "/"))
            else:
                files[rel] = entry.stat(follow_symlinks=False)
    return files, folders, sorted(excluded)


def scan_source(project: Path, previous: SourceTree | None = None) -> SourceTree:
    """La carpeta del proyecto (RF-007-22): el sha256 de cada fichero, los dos ``.git``
    incluidos, y sus carpetas, sin lo excluido. Con ``previous`` (un recorrido anterior
    de la misma publicación), el sha256 de un fichero con el mismo tamaño y la misma
    fecha no se vuelve a leer (el espejo comprueba igualmente cada copia contra el
    fichero). Un enlace, o dos rutas que solo difieren en mayúsculas, es
    :class:`MirrorError`."""
    files, folders, _excluded = _walk(project, links_allowed=False)
    check_case_clashes([*files, *folders])
    tree = SourceTree(folders=folders)
    for rel, info in files.items():
        stat = (info.st_size, info.st_mtime_ns)
        known = previous.files.get(rel) if previous is not None else None
        if known is not None and previous is not None and previous.stats.get(rel) == stat:
            tree.files[rel] = known
        else:
            tree.files[rel] = sha256_of(Path(project) / rel)
        tree.stats[rel] = stat
    return tree


def scan_destination(destination: Path) -> DestinationTree:
    """El destino sin leer ningún fichero: tamaño y fecha de cada uno, sus carpetas y lo
    excluido que tiene (RF-007-23: el informe lo nombra)."""
    files, folders, excluded = _walk(destination, links_allowed=True)
    return DestinationTree(
        {rel: (info.st_size, info.st_mtime_ns) for rel, info in files.items()},
        folders,
        excluded,
    )


def observe(path: Path) -> FileState | None:
    """El tamaño, la fecha y el sha256 de un fichero del destino, con el tamaño y la
    fecha leídos justo antes y justo después del sha256 (si no coinciden, otra vez; a
    la tercera, o si desaparece, ``None``: está cambiando)."""
    for _attempt in range(READ_ATTEMPTS):
        try:
            before = os.stat(path, follow_symlinks=False)
            digest = sha256_of(path)
            after = os.stat(path, follow_symlinks=False)
        except OSError:
            return None
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
            return FileState(after.st_size, after.st_mtime_ns, digest)
    return None


def pending_file(destination: str | os.PathLike[str], environ: Mapping[str, str]) -> Path:
    """El registro del espejo en curso de ``destination`` (``…en-curso.json``)."""
    key = destination_key(destination)
    return state_dir(environ) / f"{STATE_PREFIX}{key}{PENDING_SUFFIX}"


def load_pending(destination: Path, environ: Mapping[str, str]) -> Pending | None:
    """El registro de un espejo en curso (o interrumpido) de este PC a ``destination``;
    ``None`` si no hay o no se puede leer (entonces lo que dejó cuenta como cambio del
    NAS: se para, nunca se pierde nada)."""
    path = pending_file(destination, environ)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
        if data.get("formato") != FORMAT or data.get("tipo") != KIND_PENDING:
            return None
        files = data["ficheros"]
        lists = [data[key] for key in ("borrados", "temporales", "carpetas")]
        if not isinstance(files, dict) or not all(isinstance(item, list) for item in lists):
            return None
        rels = [*files, *(rel for item in lists for rel in item)]
        if not all(valid_rel(rel) for rel in rels):
            return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    deleted, temps, folders = ({fold(rel) for rel in item} for item in lists)
    return Pending({fold(rel): str(sha) for rel, sha in files.items()}, deleted, temps, folders)


def _topmost(folders: Iterable[str]) -> list[str]:
    """De unas carpetas, las que no están dentro de otra de ellas."""
    chosen = sorted(folders, key=lambda rel: (rel.count("/"), fold(rel)))
    keys: set[str] = set()
    result: list[str] = []
    for rel in chosen:
        parts = fold(rel).split("/")
        if any("/".join(parts[:depth]) in keys for depth in range(1, len(parts))):
            continue
        keys.add(fold(rel))
        result.append(rel)
    return result


def destination_changes(
    destination: Path,
    base: MirrorState,
    source: SourceTree,
    listing: DestinationTree,
    pending: Pending | None = None,
) -> tuple[list[DestChange], dict[str, FileState]]:
    """Los cambios del destino respecto a ``base`` (plan 007 §5.4.7; RF-007-29),
    ordenados por ruta, y lo observado de cada fichero del destino (por su ruta en el
    destino): lo del estado si no cambió su tamaño ni su fecha, o lo leído ahora."""
    pend = pending or Pending()
    src = {fold(rel): sha for rel, sha in source.files.items()}
    old = {fold(rel): (rel, info) for rel, info in base.files.items() if not is_excluded(rel)}
    now = {fold(rel): (rel, stat) for rel, stat in listing.files.items()}
    changes: list[DestChange] = []
    observed: dict[str, FileState] = {}
    for key in sorted(set(old) | set(now)):
        if key not in now:
            rel = old[key][0]
            if key in src and key not in pend.deleted:
                changes.append(DestChange(rel, DELETED, in_git(rel)))
            continue
        rel, stat = now[key]
        before = old.get(key)
        if before is not None and stat == (before[1].size, before[1].mtime_ns):
            observed[rel] = before[1]
            continue
        state = observe(Path(destination) / rel)
        kind = CHANGED if before is not None else NEW
        if state is None:
            changes.append(DestChange(rel, kind, in_git(rel)))
            continue
        observed[rel] = state
        if before is not None and state.sha256 == before[1].sha256:
            continue  # solo cambió la fecha
        if src.get(key) == state.sha256:
            continue  # el destino ya tiene lo del PC
        if pend.files.get(key) == state.sha256 or key in pend.temps:
            continue  # lo dejó un espejo en curso de este PC
        changes.append(DestChange(rel, kind, in_git(rel)))
    known = {fold(rel) for rel in (*base.folders, *source.folders)} | pend.folders
    unknown = [rel for rel in listing.folders if fold(rel) not in known]
    changes += [DestChange(rel, NEW_FOLDER, in_git(rel)) for rel in _topmost(unknown)]
    changes.sort(key=lambda change: fold(change.path))
    return changes, observed


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
