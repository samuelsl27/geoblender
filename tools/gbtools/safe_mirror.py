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

import datetime
import getpass
import hashlib
import json
import os
import platform
import re
import shutil
import stat
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .ignore import IgnoreSpec
from .layout import CODE_DIR_IN_DOCS, MIRROR_EXCLUDED, MIRROR_STATE_PARTS, MIRROR_TEMP_SUFFIX

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
    mayúsculas): el sha256 de cada fichero (o los de varios espejos cortados seguidos),
    los borrados, sus temporales y las carpetas que crea."""

    files: dict[str, set[str]] = field(default_factory=dict)
    deleted: set[str] = field(default_factory=set)
    temps: set[str] = field(default_factory=set)
    folders: set[str] = field(default_factory=set)


class MirrorBusy(MirrorError):
    """Otro espejo desde este PC a ese destino está en curso (o quedó su cerrojo)."""


class DestinationChanged(MirrorError):
    """Un fichero del destino cambió (o apareció) después de la comparación: no se ha
    tocado (RF-007-34)."""

    def __init__(self, message: str, changes: list[DestChange]) -> None:
        super().__init__(message)
        self.changes = changes


@dataclass
class MirrorReport:
    """Lo que hizo un espejo, con rutas relativas y «/»: copiados (con el tamaño, la
    fecha y el sha256 comprobados de su temporal, ``verified``), renombrados (solo
    mayúsculas), borrados, sin cambios, carpetas creadas, quitadas y conservadas (no
    vacías por lo excluido), lo excluido que tenía el destino y el orden de las copias
    y los borrados."""

    copied: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unchanged: int = 0
    created_folders: list[str] = field(default_factory=list)
    removed_folders: list[str] = field(default_factory=list)
    kept_folders: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    verified: dict[str, FileState] = field(default_factory=dict)
    order: list[tuple[str, str]] = field(default_factory=list)


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
        shas = {
            fold(rel): {value} if isinstance(value, str) else {str(sha) for sha in value}
            for rel, value in files.items()
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    deleted, temps, folders = ({fold(rel) for rel in item} for item in lists)
    return Pending(shas, deleted, temps, folders)


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
        if state.sha256 in pend.files.get(key, ()) or key in pend.temps:
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


# --- El espejo (plan 007 §5.4.8; RF-007-22, RF-007-34) ---------------------------------

LOCK_SUFFIX = ".lock"
RENAME_MARK = ".renombrando"
STAGE_OBJECTS, STAGE_WORK, STAGE_GIT, STAGE_REFS = 0, 1, 2, 3
ACTION_COPY = "copiar"
ACTION_DELETE = "borrar"
HOOK_RENAME = "renombrar"
HOOK_REPLACE = "sustituir"
HOOK_DELETE = "borrar"

Hook = Callable[[str, str], None]


def who(environ: Mapping[str, str]) -> str:
    """``usuario@equipo`` de quien hace el espejo."""
    user = environ.get("USERNAME") or getpass.getuser()
    host = environ.get("COMPUTERNAME") or platform.node()
    return f"{user}@{host}"


def now_text() -> str:
    """La fecha y la hora locales, ``AAAA-MM-DDTHH:MM:SS``."""
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def lock_file(destination: str | os.PathLike[str], environ: Mapping[str, str]) -> Path:
    """El cerrojo del espejo a ``destination`` desde este PC (``…lock``)."""
    key = destination_key(destination)
    return state_dir(environ) / f"{STATE_PREFIX}{key}{LOCK_SUFFIX}"


@contextmanager
def mirror_lock(destination: Path, environ: Mapping[str, str]) -> Iterator[Path]:
    """El cerrojo del espejo a ``destination`` (creación exclusiva, con usuario, equipo,
    fecha y PID): si ya existe, :class:`MirrorBusy` sin tocarlo. Se quita al salir."""
    path = lock_file(destination, environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        handle = os.open(path, flags)
    except FileExistsError:
        try:
            owner = path.read_bytes().decode("utf-8", "replace").strip()[:200]
        except OSError:
            owner = ""
        raise MirrorBusy(
            f"hay otro espejo en curso desde este PC a este destino, o uno interrumpido "
            f"(cerrojo «{path}»: {owner}); si no hay ninguno en marcha, borre ese fichero "
            "y repita"
        ) from None
    data = {
        "quien": who(environ),
        "pid": os.getpid(),
        "desde": now_text(),
        "destino": str(destination),
    }
    with os.fdopen(handle, "wb") as stream:
        stream.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    try:
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def copy_stage(rel: str) -> int:
    """En qué tanda se copia ``rel`` (plan 007 §5.4.8, paso 3): los objetos de git, los
    ficheros de trabajo, el resto de cada ``.git`` y, al final, sus referencias
    (``refs/``, ``packed-refs``, ``HEAD`` e ``index``). Así un corte a mitad nunca deja
    una referencia que apunte a un objeto que no está."""
    parts = [part.casefold() for part in rel.split("/")]
    if GIT_FOLDER not in parts:
        return STAGE_WORK
    inner = parts[parts.index(GIT_FOLDER) + 1 :]
    if inner[:1] == ["objects"]:
        return STAGE_OBJECTS
    if inner[:1] == ["refs"] or inner in (["packed-refs"], ["head"], ["index"]):
        return STAGE_REFS
    return STAGE_GIT


def _copy_key(rel: str) -> tuple[int, int, str]:
    """Orden de las copias: por tanda; en los paquetes, el ``.pack`` antes que su
    ``.idx``, ``.rev`` o ``.bitmap``."""
    pack_rank = 0 if rel.casefold().endswith(".pack") else 1
    return copy_stage(rel), pack_rank, fold(rel)


def _make_writable(path: Path) -> None:
    """Quita el atributo de solo lectura (git lo pone a sus objetos) sin cambiar la
    fecha del fichero."""
    mode = os.stat(path, follow_symlinks=False).st_mode
    if not mode & stat.S_IWRITE:
        os.chmod(path, mode | stat.S_IWRITE)


def _remove_file(path: Path) -> None:
    """Borra un fichero propio (un temporal), también de solo lectura."""
    try:
        _make_writable(path)
        os.unlink(path)
    except FileNotFoundError:
        pass


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    """Escribe ``data`` en ``path`` (UTF-8) a través de un temporal: nunca queda a
    medias."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))
    os.replace(temp, path)


def _write_pending(
    destination: Path,
    environ: Mapping[str, str],
    files: Mapping[str, str],
    deleted: Iterable[str],
    temps: Iterable[str],
    folders: Iterable[str],
) -> None:
    """Escribe el registro del espejo en curso (antes de tocar el destino), con lo de
    un registro anterior (un espejo cortado) que siga en él."""
    previous = load_pending(destination, environ) or Pending()
    shas: dict[str, set[str]] = {key: set(values) for key, values in previous.files.items()}
    for rel, sha in files.items():
        shas.setdefault(fold(rel), set()).add(sha)
    data = {
        "formato": FORMAT,
        "tipo": KIND_PENDING,
        "destino": str(destination),
        "iniciado": now_text(),
        "quien": who(environ),
        "ficheros": {rel: sorted(values) for rel, values in sorted(shas.items())},
        "borrados": sorted({*previous.deleted, *(fold(rel) for rel in deleted)}),
        "temporales": sorted({*previous.temps, *(fold(rel) for rel in temps)}),
        "carpetas": sorted({*previous.folders, *(fold(rel) for rel in folders)}),
    }
    _write_json(pending_file(destination, environ), data)


class _Mirror:
    """Un espejo en marcha: el plan, su ejecución y lo que va haciendo."""

    def __init__(
        self,
        project: Path,
        destination: Path,
        source: SourceTree,
        listing: DestinationTree,
        observed: Mapping[str, FileState],
        hook: Hook | None,
    ) -> None:
        self.project = Path(project)
        self.dest = Path(destination)
        self.source = source
        self.observed = dict(observed)
        self.hook: Hook = hook or (lambda _action, _rel: None)
        self.report = MirrorReport(excluded=list(listing.excluded))
        self.dest_files = {fold(rel): rel for rel in listing.files}
        self.dest_folders = {fold(rel): rel for rel in listing.folders}

    def expect(self, rel: str, state: FileState | None) -> None:
        """Justo antes de tocarlo (RF-007-34): el fichero ``rel`` del destino sigue con
        el tamaño y la fecha con que se comparó (``state``), o sigue sin existir
        (``None``); si no, :class:`DestinationChanged` sin tocarlo."""
        try:
            info = os.stat(self.dest / rel, follow_symlinks=False)
        except FileNotFoundError:
            info = None
        if state is None and info is None:
            return
        if state is not None and info is not None:
            if (info.st_size, info.st_mtime_ns) == (state.size, state.mtime_ns):
                return
        kind = NEW if state is None else (DELETED if info is None else CHANGED)
        raise DestinationChanged(
            f"«{rel}» cambió en el destino durante el espejo: no se ha tocado",
            [DestChange(rel, kind, in_git(rel))],
        )

    def rename(self, current: str, rel: str, folder: bool = False) -> None:
        """Renombra en dos pasos ``current`` a ``rel`` (solo cambian mayúsculas); un
        fichero, solo si sigue como se comparó."""
        self.hook(HOOK_RENAME, current)
        if not folder:
            self.expect(current, self.observed.get(current))
        middle = self.dest / f"{current}{RENAME_MARK}{MIRROR_TEMP_SUFFIX}"
        os.rename(self.dest / current, middle)
        os.rename(middle, self.dest / rel)
        self.report.renamed.append((current, rel))
        if not folder and current in self.observed:
            self.observed[rel] = self.observed.pop(current)

    def copy(self, rel: str) -> None:
        """Copia ``rel`` a un temporal en su carpeta, lo comprueba y, si el fichero del
        destino sigue como se comparó, lo sustituye."""
        sha = self.source.files[rel]
        target = self.dest / rel
        temp_rel = f"{rel}{MIRROR_TEMP_SUFFIX}"
        temp = self.dest / temp_rel
        self.make_folder(target.parent)
        if os.path.lexists(temp):  # de un espejo cortado (lo reconoció la comparación)
            leftover = self.dest_files.get(fold(temp_rel), temp_rel)
            self.expect(leftover, self.observed.get(leftover))
            _remove_file(temp)
        for _attempt in range(2):
            shutil.copy2(self.project / rel, temp)
            if sha256_of(temp) == sha:
                break
            _remove_file(temp)
        else:
            raise MirrorError(
                f"la copia de «{rel}» en el destino no tiene el sha256 del PC tras dos "
                "intentos: no se ha sustituido; compruebe el destino y repita"
            )
        info = os.stat(temp, follow_symlinks=False)
        verified = FileState(info.st_size, info.st_mtime_ns, sha)
        self.hook(HOOK_REPLACE, rel)
        exists = fold(rel) in self.dest_files
        try:
            self.expect(rel, self.observed.get(rel) if exists else None)
        except DestinationChanged:
            _remove_file(temp)
            raise
        if os.path.lexists(target):
            _make_writable(target)
        os.replace(temp, target)
        self.report.copied.append(rel)
        self.report.verified[rel] = verified
        self.report.order.append((ACTION_COPY, rel))

    def delete(self, rel: str) -> None:
        """Borra ``rel`` del destino si sigue como se comparó (si ya no está, nada)."""
        self.hook(HOOK_DELETE, rel)
        path = self.dest / rel
        if not os.path.lexists(path):
            return
        self.expect(rel, self.observed.get(rel))
        _make_writable(path)
        os.unlink(path)
        self.report.deleted.append(rel)
        self.report.order.append((ACTION_DELETE, rel))

    def make_folder(self, folder: Path) -> None:
        """Crea ``folder`` (y sus madres) en el destino si falta, y lo anota."""
        missing = []
        current = folder
        while current != self.dest and not current.is_dir():
            missing.append(current)
            current = current.parent
        for path in reversed(missing):
            path.mkdir()
            self.report.created_folders.append(path.relative_to(self.dest).as_posix())

    def run(self, environ: Mapping[str, str]) -> MirrorReport:
        source_keys = {fold(rel) for rel in self.source.files}
        source_folders = {fold(rel): rel for rel in self.source.folders}
        renames: dict[str, str] = {}
        copies: list[str] = []
        for rel, sha in self.source.files.items():
            current = self.dest_files.get(fold(rel))
            if current is not None and current.rsplit("/", 1)[-1] != rel.rsplit("/", 1)[-1]:
                renames[rel] = current
            seen = self.observed.get(current) if current is not None else None
            if seen is not None and seen.sha256 == sha:
                self.report.unchanged += 1
            else:
                copies.append(rel)
        deletions = sorted(
            (rel for key, rel in self.dest_files.items() if key not in source_keys), key=fold
        )
        folder_renames = sorted(
            (
                (self.dest_folders[key], rel)
                for key, rel in source_folders.items()
                if key in self.dest_folders
                and self.dest_folders[key].rsplit("/", 1)[-1] != rel.rsplit("/", 1)[-1]
            ),
            key=lambda pair: pair[1].count("/"),
        )
        removable = [rel for key, rel in self.dest_folders.items() if key not in source_folders]
        temps = [f"{rel}{MIRROR_TEMP_SUFFIX}" for rel in copies]
        temps += [f"{old}{RENAME_MARK}{MIRROR_TEMP_SUFFIX}" for old in renames.values()]
        temps += [f"{old}{RENAME_MARK}{MIRROR_TEMP_SUFFIX}" for old, _new in folder_renames]
        new_folders = [rel for key, rel in source_folders.items() if key not in self.dest_folders]
        copied = {rel: self.source.files[rel] for rel in copies}
        _write_pending(self.dest, environ, copied, deletions, temps, new_folders)
        for old, new in folder_renames:
            self.rename(old, new, folder=True)
        for rel in sorted({*copies, *renames}, key=_copy_key):
            if rel in renames:
                self.rename(renames[rel], rel)
            if rel in copied:
                self.copy(rel)
        for rel in deletions:
            self.delete(rel)
        for rel in sorted(removable, key=lambda item: (-item.count("/"), fold(item))):
            try:
                os.rmdir(self.dest / rel)
            except FileNotFoundError:
                continue
            except OSError:  # no está vacía: conserva algo excluido
                self.report.kept_folders.append(rel)
                continue
            self.report.removed_folders.append(rel)
        for rel in sorted(self.source.folders, key=fold):
            self.make_folder(self.dest / rel)
        return self.report


def mirror(
    project: Path,
    destination: Path,
    source: SourceTree,
    listing: DestinationTree,
    observed: Mapping[str, FileState],
    base: MirrorState,
    environ: Mapping[str, str],
    hook: Hook | None = None,
) -> MirrorReport:
    """Deja ``destination`` igual que la carpeta del proyecto (plan 007 §5.4.8; RF-007-22
    y RF-007-34), tras una comparación con ``base`` sin cambios del NAS: ``source``,
    ``listing`` y ``observed`` son los de esa comparación.

    Escribe antes el registro en curso y, en este orden: renombra lo que solo cambió de
    mayúsculas (en dos pasos); copia los objetos de git (el ``.pack`` antes que su
    ``.idx``), los ficheros de trabajo, el resto de cada ``.git`` y sus referencias;
    borra lo que el PC ya no tiene; quita las carpetas que quedan vacías (``os.rmdir``,
    nunca ``shutil.rmtree``) y crea las que faltan. Cada copia va a un temporal en su
    carpeta que se lee de vuelta (sha256 del PC; si no, otra vez; a la segunda,
    :class:`MirrorError`) y sustituye al fichero del destino solo si este sigue con el
    tamaño y la fecha con que se comparó (o sigue sin existir): si no, no lo toca,
    borra su temporal y lanza :class:`DestinationChanged`. Lo excluido nunca se crea,
    cambia ni borra. ``hook(acción, ruta)`` (solo las pruebas) se llama justo antes de
    mirar el fichero del destino que se va a renombrar, sustituir o borrar."""
    del base  # la comparación ya la usó: el plan sale del origen y del destino
    return _Mirror(project, destination, source, listing, observed, hook).run(environ)


# --- Comprobación y estado (plan 007 §5.4.8, pasos 4 y 5; RF-007-23, RF-007-30) ------


@dataclass
class Verification:
    """El resultado de comprobar el destino tras el espejo: problemas (falta un
    fichero, o difiere en mayúsculas: código 1), cambios del NAS (otro contenido, algo
    que sobra: código 3), y lo que guardará el estado si no hay ninguno: cada fichero
    con el tamaño, la fecha y el sha256 con que se comprobó, y las carpetas."""

    problems: list[str] = field(default_factory=list)
    changes: list[DestChange] = field(default_factory=list)
    files: dict[str, FileState] = field(default_factory=dict)
    folders: set[str] = field(default_factory=set)
    identical: int = 0


def verify(
    destination: Path,
    source: SourceTree,
    report: MirrorReport,
    observed: Mapping[str, FileState],
) -> Verification:
    """Comprueba el destino tras el espejo sin copiar ni borrar nada (RF-007-23): cada
    fichero del PC debe estar, con su nombre exacto, y con el tamaño y la fecha con que
    se comprobó (el de su temporal si se copió; el comparado si no); si no los tiene,
    se lee su sha256, y si no es el del PC es un cambio del NAS. Un fichero o una
    carpeta que no está en el PC (salvo una que el espejo dejó por tener algo
    excluido) es un cambio del NAS, nunca un sobrante que borrar."""
    destination = Path(destination)
    listing = scan_destination(destination)
    now = {fold(rel): (rel, stat) for rel, stat in listing.files.items()}
    compared = {fold(rel): state for rel, state in observed.items()}
    result = Verification(folders=set(listing.folders))
    for rel, sha in source.files.items():
        entry = now.get(fold(rel))
        if entry is None:
            result.problems.append(f"falta «{rel}» en el destino")
            continue
        name, stat = entry
        if name != rel:
            result.problems.append(f"«{name}» del destino debería llamarse «{rel}»")
        expected = report.verified.get(rel) or compared.get(fold(rel))
        if expected is not None and expected.sha256 == sha:
            if stat == (expected.size, expected.mtime_ns):
                result.files[name] = expected
                result.identical += 1
                continue
        state = observe(destination / name)
        if state is None or state.sha256 != sha:
            result.changes.append(DestChange(name, CHANGED, in_git(name)))
            continue
        result.files[name] = state
        result.identical += 1
    source_keys = {fold(rel) for rel in source.files}
    for key, (name, _stat) in now.items():
        if key not in source_keys:
            result.changes.append(DestChange(name, NEW, in_git(name)))
    known = {fold(rel) for rel in (*source.folders, *report.kept_folders)}
    unknown = [rel for rel in listing.folders if fold(rel) not in known]
    result.changes += [DestChange(rel, NEW_FOLDER, in_git(rel)) for rel in _topmost(unknown)]
    result.changes.sort(key=lambda change: fold(change.path))
    return result


def new_state(
    destination: Path,
    project: Path,
    verification: Verification,
    repos: Mapping[str, Any],
    environ: Mapping[str, str],
) -> MirrorState:
    """El estado que deja un espejo comprobado: lo de ``verification`` (lo comprobado,
    nunca una lectura posterior), los repositorios, quién y cuándo."""
    return MirrorState(
        destination=str(destination),
        source=str(project),
        taken=now_text(),
        who=who(environ),
        repos=dict(repos),
        files=dict(verification.files),
        folders=set(verification.folders),
    )


def save_state(destination: Path, environ: Mapping[str, str], state: MirrorState) -> Path:
    """Guarda el estado del último espejo de ``destination`` (RF-007-30) en el perfil
    local, a través de un temporal, y borra el registro en curso: el espejo terminó y
    se comprobó. Devuelve el fichero del estado."""
    data = {
        "formato": FORMAT,
        "tipo": KIND_STATE,
        "destino": state.destination,
        "destino_real": os.path.realpath(destination),
        "origen": state.source,
        "tomada": state.taken,
        "quien": state.who,
        "repositorios": state.repos,
        "ficheros": {
            rel: {"size": info.size, "mtime_ns": info.mtime_ns, "sha256": info.sha256}
            for rel, info in sorted(state.files.items())
        },
        "carpetas": sorted(state.folders),
    }
    path = state_file(destination, environ)
    _write_json(path, data)
    try:
        pending_file(destination, environ).unlink()
    except FileNotFoundError:
        pass
    return path
