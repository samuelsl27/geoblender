# SPDX-License-Identifier: GPL-3.0-or-later
"""Qué es una entrada registrada (spec 008; RF-008-07, RF-008-54; RF-002-19; ADR-0024 §1, §3 y
§6; plan 008 §5.2.1, §5.3.1 y §5.4.8).

Una **entrada** es una fuente que un módulo importa al proyecto: uno o más ficheros (un ASC
con su ``.prj``) o una capa. Su fila de ``gb_input`` la registra con su nombre lógico, su
tipo, el módulo y el lector que la leyeron (para siempre, ADR-0024 §6), su capa, sus CRS
declarados, sus ajustes, sus hashes y su entrega; cada fichero, en ``gb_input_file``.

- :class:`SourceFile`: un fichero de la fuente y dónde se ancla (``gb_input_file.anchor``;
  RF-002-19; ninguna ruta absoluta en el proyecto, ADR-0006 §5):

  - ``project``: dentro del proyecto; ruta relativa a su raíz, con «/»;
  - ``project_table``: una capa o tabla de ``project.gpkg`` (una creada desde QGIS); su nombre;
  - ``original``: fuera del proyecto y en el volumen del proyecto **original** (en una copia
    local, el original de la red, RF-002-31); ruta relativa a la raíz del original, con «/»;
  - ``external``: en otro volumen: solo su nombre, y su ruta completa anotada con ``ref_uid``
    en los datos de usuario de cada equipo (sin anotación, «no localizable»; nunca se supone).

- :class:`SourcePrint`: la huella (sha256 de sus bytes), el tamaño y la fecha (ns) de cada
  fichero al importarlo; de una tabla del proyecto, solo su huella (su ``last_change`` lo anota
  el registro al registrarla).
- :class:`InputSpec`: lo que declara el módulo al importar, comprobado al crearlo: una
  declaración mal formada es un error del programa (``TypeError`` o ``ValueError``). Un CRS sin
  declarar (``None``) sí se admite aquí: lo rechazan, para la persona, ``classify_import`` y
  ``register_input`` (``core.input_crs_missing``; nunca se supone).
- :class:`InputRecord` e :class:`InputFileRecord`: una fila de ``gb_input`` y de
  ``gb_input_file``.

**CRS declarados** (``gb_input.crs_h`` y ``crs_v``, JSON canónico). Horizontal:
``{"epsg": n}``, ``{"wkt2": texto}`` o ``{"not_applicable": true}``; vertical: ``{"epsg": n}``,
``{"local": nota}`` (la cota de obra), ``{"ellipsoidal": código o texto}`` o
``{"not_applicable": true}``. Un tipo con coordenadas (:data:`COORDINATE_KINDS`) no admite «no
aplica» en la horizontal, y uno con cotas (:data:`ELEVATION_KINDS`), tampoco en la vertical.

**Declaraciones** del hash de contenido (``DECL``, ADR-0024 §3), :func:`input_declarations`:
``{"conventions": {…}, "crs_h": …, "crs_v": …}``, con los ajustes que son contenido (las
convenciones declaradas al importar: referencia del azimut, unidades…). El hash de contenido
de una entrada es el de sus datos con ellas: se comprueba al declararla.

**Ajustes** (``gb_input.settings``): el JSON canónico de ``{"content_keys": […], "values":
{…}}``: todos los ajustes de la importación (lo que vuelve a recibir su lector) y cuáles son
contenido, para poder rehacer sus declaraciones. **Huella de los ajustes**
(``settings_sha256``): la de ``{"content_keys", "crs_h", "crs_v", "layer", "values"}``; dos
importaciones de los mismos datos con la misma huella son la misma entrada (RF-008-54). La
entrega (fecha y quién) y el nombre lógico no son ajustes (ADR-0024 §3). **Huella conjunta**
(``bytes_sha256``): sha256 del JSON canónico de la lista de las huellas de sus ficheros, en su
orden.

Python puro (ADR-0004).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any

from ..catalog.schema import MODULE_CODES
from ..content.encoder import NORMALIZERS, ContentDigest, content_sha256
from ..hashing import canonical_json, sha256_bytes
from ..paths import find_absolute_paths


class InputStatus(StrEnum):
    """El estado de una entrada (``gb_input.status``)."""

    CURRENT = "current"  # vigente
    CHANGED = "changed"  # cambiada, sin decidir (RF-008-10)
    KEPT = "kept"  # cambiada · se mantiene la copia (RF-008-12)
    SUPERSEDED = "superseded"  # sustituida por otra (RF-008-11)
    DISCARDED = "discarded"  # descartada · registro, no usar (RF-008-55)


ACTIVE_STATUSES: tuple[InputStatus, ...] = (
    InputStatus.CURRENT,
    InputStatus.CHANGED,
    InputStatus.KEPT,
)
"""Los estados que ocupan el nombre lógico (índice ``gb_input_name_active``)."""
INACTIVE_STATUSES: tuple[InputStatus, ...] = (InputStatus.SUPERSEDED, InputStatus.DISCARDED)
"""Los estados de una entrada que queda como historia y libera su nombre lógico."""


class FileAnchor(StrEnum):
    """Dónde se ancla un fichero de una entrada (``gb_input_file.anchor``; RF-002-19)."""

    PROJECT = "project"  # dentro del proyecto
    PROJECT_TABLE = "project_table"  # una capa o tabla de project.gpkg
    ORIGINAL = "original"  # junto al proyecto original, en su volumen
    EXTERNAL = "external"  # en otro volumen, con su ruta en los datos de usuario


class FileRole(StrEnum):
    """El papel de un fichero de una entrada (``gb_input_file.role``)."""

    MAIN = "main"  # el fichero principal (el primero)
    SIDECAR = "sidecar"  # un compañero: el .prj de un ASC


class OriginalState(StrEnum):
    """Si la entrada guarda una copia de su original (``gb_input.original``; RF-008-53)."""

    STORED = "stored"  # guardado en originals/<uid>/
    TOO_LARGE = "too_large"  # «original no guardado»: pasa del límite
    NOT_APPLICABLE = "not_applicable"  # no se guarda (ráster, nube) o aún no se ha guardado


INPUT_KINDS: tuple[str, ...] = (
    "raster",
    "vector",
    "table",
    "drillholes",
    "mesh",
    "point_cloud",
    "document",
    "other",
)
"""Los tipos de una entrada (``gb_input.kind``)."""
COORDINATE_KINDS: tuple[str, ...] = ("raster", "vector", "drillholes", "mesh", "point_cloud")
"""Los tipos con coordenadas: su CRS horizontal se declara y no es «no aplica»."""
ELEVATION_KINDS: tuple[str, ...] = ("drillholes", "mesh", "point_cloud")
"""Los tipos con cotas: tampoco su CRS vertical es «no aplica»."""
HORIZONTAL = "horizontal"
VERTICAL = "vertical"
AXES: tuple[str, ...] = (HORIZONTAL, VERTICAL)
NOT_APPLICABLE = "not_applicable"
"""``{"not_applicable": true}``: el CRS declarado «no aplica» (un documento, una tabla sin
coordenadas, la vertical de una capa plana)."""
CRS_FORMS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    HORIZONTAL: ("epsg", "wkt2", NOT_APPLICABLE),
    VERTICAL: ("epsg", "local", "ellipsoidal", NOT_APPLICABLE),
})
"""Las formas de un CRS declarado, por eje (``gb_input.crs_h`` y ``crs_v``)."""

_READER_ID = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+@[1-9][0-9]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REF_UID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


# --- Comprobaciones ---------------------------------------------------------------------------


def _text(what: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    return value


def _label(what: str, value: object) -> str:
    """Un texto no vacío, sin espacios a los lados y sin rutas absolutas."""
    text = _text(what, value)
    if not text.strip() or text != text.strip():
        raise ValueError(f"{what} no puede quedar vacío ni llevar espacios a los lados: "
                         f"{value!r}")
    _no_paths(what, text)
    return text


def _no_paths(what: str, value: object) -> None:
    """Ninguna ruta absoluta en lo que se guarda en el proyecto (ADR-0006 §5)."""
    found = find_absolute_paths(value)
    if found:
        raise ValueError(f"{what} no puede llevar rutas absolutas: se guarda en el proyecto "
                         f"(ADR-0006 §5): {found}")


def _sequence(what: str, value: object) -> tuple[Any, ...]:
    if isinstance(value, str | bytes | Mapping) or not isinstance(value, Iterable):
        raise TypeError(f"{what} son una lista, no {value!r}")
    return tuple(value)


def _integer(what: str, value: object, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{what} es un entero, no {value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{what} no puede ser menor que {minimum}: {value}")
    return value


def check_crs(value: object, axis: str) -> dict[str, Any] | None:
    """El CRS ``axis`` (:data:`HORIZONTAL` o :data:`VERTICAL`) declarado, como diccionario
    nuevo con una de sus formas (:data:`CRS_FORMS`), o ``None`` si no se declaró.
    ``TypeError``/``ValueError`` si está mal formado (un error del programa)."""
    if axis not in AXES:
        raise ValueError(f"el eje de un CRS es {HORIZONTAL} o {VERTICAL}, no {axis!r}")
    if value is None:
        return None
    forms = CRS_FORMS[axis]
    if not isinstance(value, Mapping):
        raise TypeError(f"el CRS {axis} declarado es {{forma: valor}} con una forma de "
                        f"{forms} (o None), no {value!r}")
    found = dict(value)
    if len(found) != 1 or next(iter(found)) not in forms:
        raise ValueError(f"el CRS {axis} declarado tiene una sola forma de {forms}, no "
                         f"{found!r}")
    ((form, item),) = found.items()
    if form == "epsg":
        _integer(f"el código EPSG del CRS {axis}", item, minimum=1)
    elif form == NOT_APPLICABLE:
        if item is not True:
            raise ValueError(f"un CRS {axis} que no aplica es {{\"not_applicable\": true}}, no "
                             f"{found!r}")
    elif form == "ellipsoidal" and not isinstance(item, str):
        _integer(f"el código del CRS {axis} elipsoidal", item, minimum=1)
    else:
        _label(f"el CRS {axis} declarado ({form})", item)  # sin rutas absolutas
    return found


def is_not_applicable(crs: Mapping[str, Any] | None) -> bool:
    """Si un CRS declarado es «no aplica»."""
    return crs is not None and crs.get(NOT_APPLICABLE) is True


def crs_text(crs: Mapping[str, Any] | None, language: str = "es") -> str:
    """Un CRS declarado como lo lee una persona: «EPSG:25830», «local «cota de obra»», «no
    aplica»…; «—» si no se declaró."""
    if crs is None:
        return "—"
    ((form, item),) = crs.items()
    if form == "epsg":
        return f"EPSG:{item}"
    if form == "wkt2":
        return "WKT2"
    if form == "local":
        return f"local «{item}»"
    if form == "ellipsoidal":
        shown = f"EPSG:{item}" if isinstance(item, int) else item
        return f"elipsoidal ({shown})" if language == "es" else f"ellipsoidal ({shown})"
    return "no aplica" if language == "es" else "not applicable"


def input_declarations(crs_h: Mapping[str, Any] | None, crs_v: Mapping[str, Any] | None,
                       conventions: Mapping[str, Any]) -> dict[str, Any]:
    """Las declaraciones del hash de contenido de una entrada (``DECL``, ADR-0024 §3): sus CRS
    declarados y sus convenciones (los ajustes que son contenido), en JSON. Las usan el
    importador al calcular el hash y la comprobación al volver a calcularlo."""
    if not isinstance(conventions, Mapping):
        raise TypeError(f"las convenciones de una entrada son un diccionario, no "
                        f"{conventions!r}")
    return {
        "conventions": json.loads(canonical_json(dict(conventions))),
        "crs_h": check_crs(crs_h, HORIZONTAL),
        "crs_v": check_crs(crs_v, VERTICAL),
    }


def _relative_path(path: str, anchor: FileAnchor) -> None:
    """Una ruta relativa con «/», sin unidad ni barras invertidas; dentro del proyecto, sin
    salir de él."""
    windows = PureWindowsPath(path)
    parts = path.split("/")
    inside = anchor is FileAnchor.PROJECT
    if (
        "\\" in path
        or windows.drive
        or windows.is_absolute()
        or PurePosixPath(path).is_absolute()
        or any(part in ("", ".") for part in parts)
        or (inside and ".." in parts)
    ):
        where = ("a la raíz del proyecto, sin salir de él" if inside
                 else "a la raíz del proyecto original")
        raise ValueError(f"un fichero «{anchor}» se guarda con su ruta relativa {where}, con "
                         f"«/», no {path!r}")


# --- Ficheros ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceFile:
    """Un fichero de una fuente y dónde se ancla (véase el módulo): ``path`` (relativa, el
    nombre de la tabla o, en otro volumen, solo el nombre del fichero), ``role``
    (:class:`FileRole`), ``anchor`` (:class:`FileAnchor`) y ``ref_uid`` (solo en
    ``external``: su anotación en los datos de usuario). Lo da ``locate_source``."""

    path: str
    role: FileRole
    anchor: FileAnchor
    _: KW_ONLY
    ref_uid: str | None = None

    def __post_init__(self) -> None:
        path = _label("la ruta de un fichero de una entrada", self.path)
        try:
            role = FileRole(_text("el papel de un fichero", self.role))
            anchor = FileAnchor(_text("el ancla de un fichero", self.anchor))
        except ValueError:
            raise ValueError(
                f"un fichero de una entrada tiene un papel de {[str(r) for r in FileRole]} y un "
                f"ancla de {[str(a) for a in FileAnchor]}, no {self.role!r} y {self.anchor!r}"
            ) from None
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "anchor", anchor)
        if anchor is FileAnchor.EXTERNAL:
            if any(char in path for char in "/\\:"):
                raise ValueError(f"de un fichero de otro volumen solo se guarda su nombre, no "
                                 f"{path!r}")
            if self.ref_uid is None or _REF_UID.fullmatch(_text("ref_uid", self.ref_uid)) is None:
                raise ValueError(f"un fichero de otro volumen («{path}») lleva la anotación de "
                                 f"su ruta en los datos de usuario (ref_uid), no "
                                 f"{self.ref_uid!r}")
            return
        if self.ref_uid is not None:
            raise ValueError(f"solo un fichero de otro volumen lleva ref_uid, no uno "
                             f"«{anchor}» ({path!r})")
        if anchor is not FileAnchor.PROJECT_TABLE:
            _relative_path(path, anchor)


@dataclass(frozen=True)
class SourcePrint:
    """La huella (sha256 de sus bytes, en hexadecimal), el tamaño (bytes) y la fecha de
    modificación (``st_mtime_ns``) de un fichero de una fuente al importarlo; de una tabla del
    proyecto, solo su huella (la de su contenido)."""

    sha256: str
    _: KW_ONLY
    size: int | None = None
    mtime_ns: int | None = None

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(_text("la huella de un fichero", self.sha256)) is None:
            raise ValueError(f"la huella de un fichero es un sha256 en 64 cifras hexadecimales "
                             f"en minúsculas, no {self.sha256!r}")
        if self.size is not None:
            _integer("el tamaño de un fichero", self.size, minimum=0)
        if self.mtime_ns is not None:
            _integer("la fecha de un fichero (ns)", self.mtime_ns)


# --- Lo que declara el módulo -------------------------------------------------------------------


def check_name(value: object) -> str:
    """El nombre lógico de una entrada: un texto no vacío, sin espacios a los lados y sin
    rutas absolutas (``TypeError``/``ValueError`` si no). Que no lo tenga otra entrada activa
    lo comprueba el registro."""
    return _label("el nombre lógico de una entrada", value)


def check_received_at(value: object) -> str | None:
    """La fecha de entrega (D-11) como se guarda, «AAAA-MM-DD» (de un ``date`` o de ese
    texto), o ``None``; ``TypeError``/``ValueError`` si no es un día."""
    return _received_at(value)


def check_received_from(value: object) -> str | None:
    """Quién entrega una entrada (D-11): ``None`` o un texto no vacío, sin espacios a los
    lados y sin rutas absolutas."""
    if value is None:
        return None
    return _label("quién entrega una entrada", value)


def _received_at(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        raise TypeError(f"la fecha de entrega es un día (date o «AAAA-MM-DD»), no una fecha y "
                        f"hora: {value!r}")
    if isinstance(value, dt.date):
        return value.isoformat()
    text = _text("la fecha de entrega", value)
    try:
        if _DATE.fullmatch(text) is None:
            raise ValueError
        dt.date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"la fecha de entrega es «AAAA-MM-DD», no {text!r}") from None
    return text


def _content_keys(keys: object, settings: Mapping[str, Any]) -> tuple[str, ...]:
    found = _sequence("los ajustes que son contenido (content_settings_keys)", keys)
    for key in found:
        _text("un ajuste que es contenido", key)
    missing = sorted(set(found) - set(settings))
    if missing:
        raise ValueError(f"los ajustes que son contenido tienen que estar entre los ajustes: "
                         f"faltan {missing}")
    return tuple(sorted(set(found)))


def _crs_json(crs: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    return None if crs is None else MappingProxyType(dict(crs))


@dataclass(frozen=True)
class InputSpec:
    """Lo que declara un módulo al importar una fuente (plan 008 §5.3.1):

    - ``name``: su nombre lógico (por defecto, el del fichero principal sin extensión; único
      entre las entradas activas);
    - ``kind``: de :data:`INPUT_KINDS`; ``module``: el código del módulo del importador;
      ``reader``: su lector con versión (``"gis.geotiff@1"``), con el que se compara siempre;
    - ``files`` (:class:`SourceFile`, el principal el primero) y ``file_prints``
      (:class:`SourcePrint`, en el mismo orden);
    - ``digest``: el :class:`~geoblender.core.content.ContentDigest` que calculó el
      importador con su lector y las declaraciones de la entrada
      (:func:`input_declarations`);
    - ``crs_h`` y ``crs_v``: sus CRS declarados (``None``: sin declarar, véase el módulo);
    - ``layer``: la capa o tabla leída; ``settings``: los ajustes de la importación (JSON, sin
      rutas absolutas); ``content_settings_keys``: los que son contenido (sus convenciones);
    - ``received_at`` (``date`` o «AAAA-MM-DD») y ``received_from``: la entrega (D-11).

    Calcula :attr:`declarations`, :attr:`settings_json` (lo que se guarda),
    :attr:`settings_sha256` y :attr:`bytes_sha256` (véase el módulo)."""

    name: str
    kind: str
    module: str
    reader: str
    _: KW_ONLY
    files: Sequence[SourceFile]
    file_prints: Sequence[SourcePrint]
    digest: ContentDigest
    crs_h: Mapping[str, Any] | None
    crs_v: Mapping[str, Any] | None
    layer: str | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)
    content_settings_keys: Iterable[str] = ()
    received_at: dt.date | str | None = None
    received_from: str | None = None
    declarations: Mapping[str, Any] = field(init=False, repr=False)
    settings_json: str = field(init=False, repr=False)
    settings_sha256: str = field(init=False, repr=False)
    bytes_sha256: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        name = check_name(self.name)
        kind = _text("el tipo de una entrada", self.kind)
        if kind not in INPUT_KINDS:
            raise ValueError(f"tipo de entrada desconocido {kind!r}: es uno de "
                             f"{', '.join(INPUT_KINDS)}")
        if _text("el módulo de una entrada", self.module) not in MODULE_CODES:
            raise ValueError(f"módulo desconocido {self.module!r}: es uno de "
                             f"{', '.join(MODULE_CODES)}")
        if _READER_ID.fullmatch(_text("el lector de una entrada", self.reader)) is None:
            raise ValueError(f"el lector de una entrada lleva su versión («gis.geotiff@1»), no "
                             f"{self.reader!r}")
        files, prints = self._files()
        crs_h = check_crs(self.crs_h, HORIZONTAL)
        crs_v = check_crs(self.crs_v, VERTICAL)
        if self.layer is not None:
            _label("la capa de una entrada", self.layer)
        if not isinstance(self.settings, Mapping):
            raise TypeError(f"los ajustes de una entrada son un diccionario, no "
                            f"{self.settings!r}")
        values = json.loads(canonical_json(dict(self.settings)))
        _no_paths("los ajustes de una entrada", values)
        keys = _content_keys(self.content_settings_keys, values)
        received_at = check_received_at(self.received_at)
        check_received_from(self.received_from)
        declarations = input_declarations(crs_h, crs_v, {key: values[key] for key in keys})
        self._check_digest(name, kind, declarations)
        identity = {"content_keys": list(keys), "crs_h": crs_h, "crs_v": crs_v,
                    "layer": self.layer, "values": values}
        for attribute, value in (
            ("files", files),
            ("file_prints", prints),
            ("crs_h", _crs_json(crs_h)),
            ("crs_v", _crs_json(crs_v)),
            ("settings", MappingProxyType(values)),
            ("content_settings_keys", keys),
            ("received_at", received_at),
            ("declarations", MappingProxyType(declarations)),
            ("settings_json", canonical_json({"content_keys": list(keys), "values": values})
             .decode("utf-8")),
            ("settings_sha256", sha256_bytes(canonical_json(identity))),
            ("bytes_sha256", sha256_bytes(canonical_json([item.sha256 for item in prints]))),
        ):
            object.__setattr__(self, attribute, value)

    def _files(self) -> tuple[tuple[SourceFile, ...], tuple[SourcePrint, ...]]:
        files = _sequence("los ficheros de una entrada", self.files)
        prints = _sequence("las huellas de los ficheros de una entrada", self.file_prints)
        for item in files:
            if not isinstance(item, SourceFile):
                raise TypeError(f"un fichero de una entrada es un SourceFile, no {item!r}")
        for item in prints:
            if not isinstance(item, SourcePrint):
                raise TypeError(f"la huella de un fichero es un SourcePrint, no {item!r}")
        if not files:
            raise ValueError(f"la entrada «{self.name}» no tiene ningún fichero")
        if len(prints) != len(files):
            raise ValueError(f"la entrada «{self.name}» tiene {len(files)} ficheros y "
                             f"{len(prints)} huellas: una por fichero, en su orden")
        mains = [item for item in files if item.role is FileRole.MAIN]
        if files[0].role is not FileRole.MAIN or len(mains) != 1:
            raise ValueError(f"la entrada «{self.name}» tiene un solo fichero principal, el "
                             "primero")
        places = [(str(item.anchor), item.path) for item in files]
        if len(set(places)) != len(places):
            raise ValueError(f"la entrada «{self.name}» repite un fichero: {places}")
        tables = any(item.anchor is FileAnchor.PROJECT_TABLE for item in files)
        if tables and len(files) != 1:
            raise ValueError(f"una entrada anclada a una tabla del proyecto («{self.name}») no "
                             "tiene más ficheros")
        for item, printed in zip(files, prints, strict=True):
            stat = (printed.size, printed.mtime_ns)
            if item.anchor is FileAnchor.PROJECT_TABLE and stat != (None, None):
                raise ValueError(f"una tabla del proyecto ({item.path!r}) no tiene tamaño ni "
                                 "fecha: se sigue por su last_change")
            if item.anchor is not FileAnchor.PROJECT_TABLE and None in stat:
                raise ValueError(f"del fichero {item.path!r} se registran su tamaño y su fecha")
        return files, prints

    def _check_digest(self, name: str, kind: str, declarations: Mapping[str, Any]) -> None:
        """El hash es el de sus datos con sus declaraciones, dado por su lector."""
        digest = self.digest
        if not isinstance(digest, ContentDigest):
            raise TypeError(f"los hashes de una entrada son un ContentDigest, no {digest!r}")
        if digest.reader != self.reader:
            raise ValueError(f"los hashes de «{name}» los dio el lector «{digest.reader}», no el "
                             f"suyo («{self.reader}»)")
        if digest.normalizer not in NORMALIZERS:
            raise ValueError(f"este Geoblender no calcula el normalizador "
                             f"«{digest.normalizer}» de «{name}»")
        expected = content_sha256(kind, declarations, digest.data_sha256,
                                  normalizer=digest.normalizer)
        if digest.content_sha256 != expected:
            raise ValueError(
                f"el hash de contenido de «{name}» no es el de sus datos con sus declaraciones "
                "(CRS horizontal y vertical y convenciones: input_declarations, ADR-0024 §3)"
            )


# --- Lo registrado ------------------------------------------------------------------------------


@dataclass(frozen=True)
class InputFileRecord:
    """Una fila de ``gb_input_file``: un fichero de una entrada con su ancla, su tamaño, su
    fecha (``last_change`` en una tabla del proyecto) y su huella al registrarla, su última
    comprobación y su original (RF-008-53)."""

    ord: int
    role: FileRole
    anchor: FileAnchor
    path: str
    ref_uid: str | None
    size: int | None
    mtime_ns: int | None
    last_change: str | None
    sha256: str
    checked_size: int | None
    checked_mtime_ns: int | None
    checked_last_change: str | None
    checked_at: str | None
    original_path: str | None
    original_sha256: str | None
    original_size: int | None
    original_mtime_ns: int | None

    @property
    def source(self) -> SourceFile:
        """Su ubicación como :class:`SourceFile`."""
        return SourceFile(self.path, self.role, self.anchor, ref_uid=self.ref_uid)

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> InputFileRecord:
        """El registro de una fila con las columnas de :data:`FILE_COLUMNS`."""
        values = dict(zip(FILE_COLUMNS, row, strict=True))
        return cls(**{**values, "role": FileRole(values["role"]),
                      "anchor": FileAnchor(values["anchor"])})


FILE_COLUMNS: tuple[str, ...] = (
    "ord",
    "role",
    "anchor",
    "path",
    "ref_uid",
    "size",
    "mtime_ns",
    "last_change",
    "sha256",
    "checked_size",
    "checked_mtime_ns",
    "checked_last_change",
    "checked_at",
    "original_path",
    "original_sha256",
    "original_size",
    "original_mtime_ns",
)
"""Las columnas de ``gb_input_file`` que lee :meth:`InputFileRecord.from_row`, en su orden."""


@dataclass(frozen=True)
class InputRecord:
    """Una fila de ``gb_input`` con sus ficheros (:attr:`files`, por su orden). ``crs_h``,
    ``crs_v`` y ``settings`` (los valores de los ajustes), ya leídos del JSON;
    ``settings_json``, el texto guardado; fechas en UTC (``AAAA-MM-DDTHH:MM:SS.mmmZ``) y la de
    entrega, «AAAA-MM-DD»."""

    uid: str
    name: str
    kind: str
    module: str
    reader: str
    normalizer: str
    layer: str | None
    crs_h: Mapping[str, Any]
    crs_v: Mapping[str, Any]
    settings: Mapping[str, Any]
    content_settings_keys: tuple[str, ...]
    settings_json: str
    settings_sha256: str
    bytes_sha256: str
    data_sha256: str
    content_sha256: str
    received_at: str | None
    received_from: str | None
    registered_by: str
    registered_at: str
    operation_uid: str
    previous_uid: str | None
    status: InputStatus
    status_at: str | None
    status_by: str | None
    status_reason: str | None
    seen_sha256: str | None
    original: OriginalState
    created_at: str
    modified_at: str
    files: tuple[InputFileRecord, ...]

    @property
    def active(self) -> bool:
        """Si ocupa su nombre lógico (ni sustituida ni descartada)."""
        return self.status in ACTIVE_STATUSES

    @property
    def conventions(self) -> dict[str, Any]:
        """Los ajustes que son contenido, con su valor."""
        return {key: self.settings[key] for key in self.content_settings_keys}

    @property
    def declarations(self) -> dict[str, Any]:
        """Sus declaraciones (:func:`input_declarations`): con ellas, su lector y su
        normalizador se vuelve a calcular su hash de contenido (ADR-0024 §6)."""
        return input_declarations(self.crs_h, self.crs_v, self.conventions)

    @property
    def digest(self) -> ContentDigest:
        """Sus hashes con su normalizador y su lector."""
        return ContentDigest(self.data_sha256, self.content_sha256, self.normalizer,
                             self.reader)

    @classmethod
    def from_row(cls, row: tuple[Any, ...],
                 files: Sequence[InputFileRecord] = ()) -> InputRecord:
        """El registro de una fila con las columnas de :data:`INPUT_COLUMNS` y sus ficheros."""
        values = dict(zip(INPUT_COLUMNS, row, strict=True))
        text = values.pop("settings")
        stored = json.loads(text)
        if isinstance(stored, dict) and set(stored) == {"content_keys", "values"}:
            settings, keys = stored["values"], tuple(stored["content_keys"])
        else:  # una fila escrita por otro camino: todo son valores
            settings, keys = stored, ()
        crs_h = json.loads(values.pop("crs_h"))
        crs_v = json.loads(values.pop("crs_v"))
        status = InputStatus(values.pop("status"))
        original = OriginalState(values.pop("original"))
        return cls(
            **values,
            crs_h=MappingProxyType(crs_h),
            crs_v=MappingProxyType(crs_v),
            settings=MappingProxyType(settings),
            content_settings_keys=keys,
            settings_json=text,
            status=status,
            original=original,
            files=tuple(files),
        )


INPUT_COLUMNS: tuple[str, ...] = (
    "uid",
    "name",
    "kind",
    "module",
    "reader",
    "normalizer",
    "layer",
    "crs_h",
    "crs_v",
    "settings",
    "settings_sha256",
    "bytes_sha256",
    "data_sha256",
    "content_sha256",
    "received_at",
    "received_from",
    "registered_by",
    "registered_at",
    "operation_uid",
    "previous_uid",
    "status",
    "status_at",
    "status_by",
    "status_reason",
    "seen_sha256",
    "original",
    "created_at",
    "modified_at",
)
"""Las columnas de ``gb_input`` que lee :meth:`InputRecord.from_row`, en su orden."""
