# SPDX-License-Identifier: GPL-3.0-or-later
"""Versiones y revisiones como datos (spec 009; RF-009-01 a RF-009-04; plan 009 §5.3.1;
ADR-0013).

- :class:`VersionStatus`: los cuatro estados de una versión, escritos como los escribe
  ADR-0013 (``BORRADOR``, ``VIGENTE``, ``SUPERADO``, ``DESCARTADO``), con su etiqueta inglesa
  (``msgid``: «DRAFT», «CURRENT»…); :data:`EDITABLE`, los de una versión en la que se trabaja;
  :data:`TRANSITIONS`, los cambios que admite la base (``core.versions.schema``), y
  :data:`REQUESTED`, los que puede pedir una persona (RF-009-03: una VIGENTE pasa a SUPERADO
  solo al declarar VIGENTE otra).
- :class:`RevisionState`: abierta, congelada o cerrada («cerrada al superarse», RF-009-25).
- :class:`Version` y :class:`Revision`: una fila de ``gb_version`` y de ``gb_revision``.
- Lo congelado de una revisión (``gb_revision_item``, RF-009-07, RF-009-19): :class:`ItemKind`
  (dato, entrada, parámetro, operación o cifra), :class:`ItemPart` (lo producido por la
  versión, lo de aguas arriba, lo inmutable del proyecto o lo heredado de la padre),
  :class:`ItemState` (el estado que tenía al congelarse) y :class:`RevisionItem`, una fila.
- Dónde van las instantáneas: :data:`SNAPSHOTS_DIR`, :data:`FREEZING_MARK` (la carpeta
  temporal de una congelación en curso) y :data:`SNAPSHOT_MANIFEST`; el manifiesto, compacto
  al escribirlo (:func:`compact_manifest`: sin lo que vale lo de por defecto,
  :data:`MANIFEST_ENTRY_DEFAULTS` y :data:`MANIFEST_DEFAULTS`, y cada fichero de otra
  instantánea una vez, :data:`MANIFEST_REFERENCED` y :data:`MANIFEST_REF`; T33, RNF-009-06) y
  entero al leerlo (:func:`expand_manifest`, igual que lo escribía la T13).
- :func:`version_code` (1 → «V01») y :func:`revision_label` («V10.r2»);
  :func:`version_locator`, la ubicación de un dato de una versión con su código
  («des_final_v10.tif», D-34).
- :class:`Decision`: una decisión de la propiedad con sus enlaces (RF-009-13, D-33) y cómo se
  muestra como decisor.
- :class:`VersionError`: el rechazo para el usuario, con un código ``core.version_*`` del
  catálogo :data:`MESSAGES` (``msgid`` en inglés, con su español en
  ``core/i18n/messages.toml``) y :func:`render`, el texto en los dos idiomas;
  :func:`ensure_editable`, el de RF-009-04 para una versión SUPERADO o DESCARTADO.

Python puro; solo importa ``core.errors`` y ``core.i18n`` (``core.provenance`` lo usará sin
ciclos, ARQ-08).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..errors import GeoblenderError
from ..i18n import LANGUAGES, translate

type JsonScalar = str | int | float | bool | None
type JsonDefault = JsonScalar | tuple[()] | Mapping[str, object]
"""Lo de por defecto de una clave del manifiesto de una instantánea (``()``: una lista vacía;
un ``Mapping`` vacío: un objeto vacío)."""


class VersionStatus(StrEnum):
    """El estado de una versión (``gb_version.status``), como lo escribe ADR-0013."""

    BORRADOR = "BORRADOR"
    VIGENTE = "VIGENTE"
    SUPERADO = "SUPERADO"
    DESCARTADO = "DESCARTADO"

    @property
    def msgid(self) -> str:
        """Su etiqueta en inglés, que es su ``msgid`` en ``messages.toml`` («DRAFT»…)."""
        return _STATUS_MSGIDS[self]


_STATUS_MSGIDS: Mapping[VersionStatus, str] = MappingProxyType({
    VersionStatus.BORRADOR: "DRAFT",
    VersionStatus.VIGENTE: "CURRENT",
    VersionStatus.SUPERADO: "SUPERSEDED",
    VersionStatus.DESCARTADO: "DISCARDED",
})

EDITABLE: frozenset[VersionStatus] = frozenset({VersionStatus.BORRADOR, VersionStatus.VIGENTE})
"""Los estados de una versión en la que se trabaja: tiene su revisión abierta y en ella se
registran operaciones y se cambian sus parámetros (RF-009-04)."""

TRANSITIONS: Mapping[VersionStatus, frozenset[VersionStatus]] = MappingProxyType({
    VersionStatus.BORRADOR: frozenset({VersionStatus.VIGENTE, VersionStatus.DESCARTADO}),
    VersionStatus.VIGENTE: frozenset({VersionStatus.SUPERADO, VersionStatus.DESCARTADO}),
    VersionStatus.SUPERADO: frozenset(),
    VersionStatus.DESCARTADO: frozenset(),
})
"""Los cambios de estado que admite la base (RF-009-03; ``core.versions.schema.TRANSITIONS``):
una SUPERADO o DESCARTADO ya no cambia."""

REQUESTED: Mapping[VersionStatus, frozenset[VersionStatus]] = MappingProxyType({
    VersionStatus.BORRADOR: frozenset({VersionStatus.VIGENTE, VersionStatus.DESCARTADO}),
    VersionStatus.VIGENTE: frozenset({VersionStatus.DESCARTADO}),
})
"""Los que puede pedir una persona (RF-009-03): BORRADOR → VIGENTE o DESCARTADO y VIGENTE →
DESCARTADO. VIGENTE → SUPERADO lo hace declarar VIGENTE otra versión (D-3)."""


class RevisionState(StrEnum):
    """El estado de una revisión (``gb_revision.state``)."""

    OPEN = "open"
    FROZEN = "frozen"
    CLOSED = "closed"


SNAPSHOTS_DIR = "snapshots"
"""La carpeta de las instantáneas en el proyecto (``snapshots/V10.r2/``; plan §5.2.5)."""
FREEZING_MARK = ".congelando-"
"""Lo que lleva el nombre de la carpeta temporal de una congelación en curso
(``snapshots/V10.r2.congelando-<8 hex>``, plan A6)."""
SNAPSHOT_MANIFEST = "manifest.json"
"""El manifiesto de una instantánea (``snapshots/V10.r2/manifest.json``; plan §5.2.5)."""

FIRST_REVISION_REASON = "Revisión inicial"
"""El motivo de la r1 que abre crear una versión (plan A1)."""
CLOSED_ON_SUPERSEDING = "cerrada al superarse"
"""Lo que es una revisión cerrada: la abierta de una versión que pasó a SUPERADO o DESCARTADO,
sin instantánea; sus resultados quedan como historia no reproducible (RF-009-25, D-11)."""


def version_code(number: int) -> str:
    """El código de la versión ``number`` (1 → «V01», 10 → «V10», 100 → «V100»).
    :class:`TypeError` si no es un entero y :class:`ValueError` si es menor que 1."""
    if isinstance(number, bool) or not isinstance(number, int):
        raise TypeError(f"el número de una versión es un entero, no {number!r}")
    if number < 1:
        raise ValueError(f"el número de una versión empieza en 1, no {number}")
    return f"V{number:02d}"


def revision_label(code: str, number: int) -> str:
    """La etiqueta de la revisión ``number`` de la versión ``code`` («V10.r2»)."""
    return f"{code}.r{number}"


_CODE = re.compile(r"V[0-9]{2,}")


def version_locator(locator: str, code: str) -> str:
    """La ubicación de un dato de la versión ``code`` (D-34): ``locator`` con el código en
    minúsculas tras su nombre y antes de su extensión («rasters/des_final.tif» y «V10» →
    «rasters/des_final_v10.tif»; «des_string» → «des_string_v10»), porque una ubicación no se
    reutiliza nunca (``gb_dataset_location``) y dos versiones pueden tener un dato con el mismo
    nombre. :class:`TypeError` si no son textos; :class:`ValueError` con un código que no es el
    de una versión («V01», «V100») o sin nombre de fichero o de tabla."""
    if not isinstance(locator, str) or not isinstance(code, str):
        raise TypeError(f"la ubicación y el código de la versión son textos, no {locator!r} y "
                        f"{code!r}")
    if _CODE.fullmatch(code) is None:
        raise ValueError(f"el código de una versión es «V01», «V10» o «V100», no {code!r}")
    folder, slash, name = locator.rpartition("/")
    if not name or name != name.strip() or locator != locator.strip():
        raise ValueError(f"la ubicación de un dato termina en el nombre de su fichero o de su "
                         f"tabla, sin espacios a los lados: {locator!r}")
    stem, dot, extension = name.rpartition(".")
    if not stem:  # sin extensión (una tabla) o un nombre que empieza por «.»
        stem, dot, extension = name, "", ""
    return f"{folder}{slash}{stem}_{code.lower()}{dot}{extension}"


@dataclass(frozen=True, slots=True)
class Version:
    """Una fila de ``gb_version``: el código inmutable (V01…), el rasgo, el título (lo cambia el
    renombrado, RF-009-22), el estado, de cuál parte y su última revisión congelada al crearla,
    el encargo, los motivos, quién y cuándo (fechas UTC ``AAAA-MM-DDTHH:MM:SS.mmmZ``)."""

    uid: str
    code: str
    feature: str
    title: str
    status: VersionStatus
    parent_uid: str | None
    parent_revision_uid: str | None
    request: str | None
    reason_created: str
    reason_closed: str | None
    created_at: str
    created_by: str
    status_changed_at: str
    status_changed_by: str
    modified_at: str

    @property
    def label(self) -> str:
        """«V10 · Definitiva»."""
        return f"{self.code} · {self.title}"

    @property
    def editable(self) -> bool:
        """Verdadero en BORRADOR o VIGENTE (RF-009-04)."""
        return self.status in EDITABLE


@dataclass(frozen=True, slots=True)
class Revision:
    """Una fila de ``gb_revision``: de qué versión, su número, su estado, el motivo, quién y
    cuándo la abrió y la congeló o la cerró, su instantánea (carpeta relativa, huella del
    manifiesto y bytes copiados), la versión de Geoblender con que se congeló, lo aceptado al
    congelar y la marca de «alterada» (JSON tal como se guarda)."""

    uid: str
    version_uid: str
    number: int
    state: RevisionState
    reason: str
    created_at: str
    created_by: str
    closed_at: str | None
    closed_by: str | None
    snapshot_dir: str | None
    snapshot_sha256: str | None
    snapshot_bytes: int | None
    geoblender_version: str | None
    accepted: str | None
    altered_at: str | None
    altered_detail: str | None

    def label(self, code: str) -> str:
        """«V10.r2», con el código de su versión."""
        return revision_label(code, self.number)

    @property
    def altered(self) -> bool:
        """Verdadero si está marcada «alterada» (RF-009-09; D-31)."""
        return self.altered_at is not None


class ItemKind(StrEnum):
    """Qué es un elemento de lo congelado (``gb_revision_item.item_kind``)."""

    DATASET = "dataset"  # un dato (gb_dataset)
    INPUT = "input"  # una entrada (gb_input), con su original
    PARAMETER = "parameter"  # una fila de parámetro (gb_parameter), con la rev que se usó
    OPERATION = "operation"  # una operación (gb_operation)
    FIGURE = "figure"  # una cifra (gb_figure)


class ItemPart(StrEnum):
    """De dónde es un elemento de lo congelado (``gb_revision_item.part``; plan A5 (2))."""

    PRODUCED = "produced"  # lo producido por la versión (sus datos, operaciones y cifras)
    UPSTREAM = "upstream"  # lo derivado o editable a mano del proyecto, aguas arriba
    IMMUTABLE = "immutable"  # lo inmutable del proyecto: lo importado y sus entradas (D-18)
    INHERITED = "inherited"  # lo congelado de la versión de la que parte (Use.frozen, D-27)


class ItemState(StrEnum):
    """El estado que tenía un elemento al congelarse (``gb_revision_item.state``; RF-009-08,
    RF-009-19): al día, obsoleto, a la espera de revisión a mano, una entrada no localizable o
    lo que no se puede reproducir (consumió un contenido que ya no existe ni está congelado, o
    un modelo de bloques hasta R-22, D-37)."""

    CURRENT = "current"
    STALE = "stale"
    REVIEW = "review"
    UNLOCATABLE = "unlocatable"
    NOT_REPRODUCIBLE = "not_reproducible"


@dataclass(frozen=True, slots=True)
class RevisionItem:
    """Una fila de ``gb_revision_item``: lo congelado en una revisión (RF-009-07). De qué
    revisión; qué es (:class:`ItemKind`) y su uid; de dónde es (:class:`ItemPart`); de un
    parámetro, la fila de su historial que se usó (``item_rev``); el contenido congelado (de un
    dato o una entrada, su hash de contenido; de un parámetro, su ``value_sha256``); si su
    contenido se copia en **esta** instantánea (``copied``) y dónde está la copia, en esta o
    en otra (``snapshot_path``, relativa al proyecto, y su capa en el GeoPackage, con la huella
    y el tamaño del fichero cuando se conocen; ``None`` en lo inmutable del proyecto), y el
    estado que tenía al congelarse (:class:`ItemState`)."""

    revision_uid: str
    item_kind: ItemKind
    item_uid: str
    part: ItemPart
    item_rev: int | None
    content_sha256: str | None
    copied: bool
    snapshot_path: str | None
    snapshot_layer: str | None
    file_sha256: str | None
    file_size: int | None
    state: ItemState


# --- El manifiesto de una instantánea, compacto (009/T33) ------------------------------------

MANIFEST_REFERENCED = "referenced"
"""En la raíz del manifiesto compacto, la lista de los ficheros de **otras** instantáneas que
referencia la revisión (rutas relativas al proyecto, «snapshots/V01.r1/V01.r1.gpkg»), cada uno
una sola vez y en el orden en que aparecen sus datos (T33; RNF-009-06)."""
MANIFEST_REF = "ref"
"""En un dato del manifiesto compacto, el índice de su fichero en :data:`MANIFEST_REFERENCED`:
el dato está en otra instantánea (``location`` «other») y su ``path`` es ese."""

MANIFEST_ENTRY_DEFAULTS: Mapping[str, Mapping[str, JsonDefault]] = MappingProxyType({
    "datasets": MappingProxyType({
        "name": None, "kind": None, "store": "gpkg", "reader": "core.gpkg_layer@1",
        "normalizer": "gbch/1", "selector": None, "content_sha256": None, "part": "produced",
        "state": "current", "location": None, "path": None, "layer": None,
    }),
    "inputs": MappingProxyType({
        "name": None, "content_sha256": None, "part": "immutable", "state": "current",
        "originals": (),
    }),
    "parameters": MappingProxyType({
        "key": None, "scope": "project", "scope_uid": "", "rev": None, "value_sha256": None,
        "part": "produced", "state": "current",
    }),
    "operations": MappingProxyType({
        "op_type": None, "op_version": None, "module": None, "reproducible": None,
        "part": "produced", "state": "current",
    }),
    "figures": MappingProxyType({
        "key": None, "value": None, "unit": None, "kind": "CALCULADO",
        "scope": MappingProxyType({}), "operation_uid": None, "part": "produced",
        "state": "current",
    }),
})
"""Lo que vale en el manifiesto de una instantánea cada clave de un elemento que no se escribe
(plan §5.2.5; T33): lo nulo, el estado «al día», la parte de siempre (lo producido por la
versión; lo inmutable, en una entrada), un dato de una tabla o capa del GeoPackage leída con
``core.gpkg_layer@1`` y normalizada con ``gbch/1``, el ámbito del proyecto, ningún original, una
cifra CALCULADO (la de una operación, 008) y sin ámbito. Son del formato (``schema`` 1), no del
código: no cambian aunque cambie el lector de un dato; una lista vacía va como ``()`` y un
objeto vacío como un ``MappingProxyType`` vacío (al leer, ``[]`` y ``{}`` nuevos)."""
MANIFEST_DEFAULTS: Mapping[str, JsonDefault] = MappingProxyType({
    "files": (), "datasets": (), "inputs": (), "parameters": (), "operations": (),
    "figures": (), "accepted": None,
})
"""Lo que vale cada sección de la raíz del manifiesto que no se escribe: ninguna, y nada
aceptado."""


def compact_manifest(body: Mapping[str, Any]) -> dict[str, Any]:
    """El manifiesto entero de una instantánea (``body``, el de §5.2.5 con todas sus claves)
    como se escribe desde la T33 (RNF-009-06): sin las claves de cada elemento que valen lo de
    por defecto (:data:`MANIFEST_ENTRY_DEFAULTS`; un nulo donde lo de por defecto no es nulo se
    escribe), sin las secciones vacías ni lo aceptado nulo (:data:`MANIFEST_DEFAULTS`) y con la
    ruta de cada fichero de otra instantánea **una sola vez**, en :data:`MANIFEST_REFERENCED`,
    y su índice en cada dato (:data:`MANIFEST_REF`, en lugar de ``location`` y ``path``). No
    cambia ``body``; :func:`expand_manifest` lo deshace."""
    found: dict[str, Any] = {}
    referenced: list[str] = []
    places: dict[str, int] = {}
    for key, value in body.items():
        if key in MANIFEST_DEFAULTS and _is_default(value, MANIFEST_DEFAULTS[key]):
            continue
        defaults = MANIFEST_ENTRY_DEFAULTS.get(key)
        if defaults is None or not isinstance(value, list):
            found[key] = _json_copy(value)
            continue
        found[key] = [
            _compact_entry(entry, defaults, (referenced, places) if key == "datasets" else None)
            if isinstance(entry, dict) else _json_copy(entry)
            for entry in value
        ]
    if referenced:
        found[MANIFEST_REFERENCED] = referenced
    return found


def expand_manifest(body: Mapping[str, Any]) -> dict[str, Any]:
    """El manifiesto de una instantánea con todas sus claves, como lo escribía la T13: de uno
    compacto (:func:`compact_manifest`) pone lo que vale lo de por defecto y la ruta de cada
    dato de otra instantánea (``location`` «other» y ``path``; un índice que no está en
    :data:`MANIFEST_REFERENCED`, sin ruta); de uno ya entero devuelve lo mismo. Quien lee un
    manifiesto (comprobar, y reproducir al comprobar antes) lo lee así. Lo que no es una
    entrada se deja como está. No cambia ``body``: todo lo que devuelve es nuevo."""
    found = {key: _json_copy(value) for key, value in body.items()}
    listed = found.pop(MANIFEST_REFERENCED, None)
    referenced = listed if isinstance(listed, list) else []
    for key, default in MANIFEST_DEFAULTS.items():
        if key not in found:
            found[key] = _fresh(default)
    for key, defaults in MANIFEST_ENTRY_DEFAULTS.items():
        entries = found[key]
        if isinstance(entries, list):
            found[key] = [
                _expand_entry(entry, defaults, referenced if key == "datasets" else None)
                if isinstance(entry, dict) else entry
                for entry in entries
            ]
    return found


def _compact_entry(entry: Mapping[str, Any], defaults: Mapping[str, JsonDefault],
                   references: tuple[list[str], dict[str, int]] | None) -> dict[str, Any]:
    found = {key: _json_copy(value) for key, value in entry.items()
             if key not in defaults or not _is_default(value, defaults[key])}
    path = found.get("path")
    if references is not None and found.get("location") == "other" and isinstance(path, str):
        referenced, places = references
        index = places.get(path)
        if index is None:
            index = places[path] = len(referenced)
            referenced.append(path)
        del found["location"], found["path"]
        found[MANIFEST_REF] = index
    return found


def _expand_entry(entry: dict[str, Any], defaults: Mapping[str, JsonDefault],
                  referenced: list[Any] | None) -> dict[str, Any]:
    found = {key: _fresh(default) for key, default in defaults.items() if key not in entry}
    found.update(entry)
    if referenced is not None and MANIFEST_REF in found:
        index = found.pop(MANIFEST_REF)
        path = (referenced[index] if isinstance(index, int) and not isinstance(index, bool)
                and 0 <= index < len(referenced) else None)
        found["location"] = "other"
        found["path"] = path if isinstance(path, str) else None
    return found


def _is_default(value: object, default: JsonDefault) -> bool:
    """Si ``value`` (de un JSON) es lo de por defecto: el mismo tipo y valor (``0`` no es
    ``False``), una lista vacía o un objeto vacío."""
    if isinstance(default, tuple):
        return isinstance(value, list) and not value
    if isinstance(default, Mapping):
        return isinstance(value, dict) and not value
    if default is None:
        return value is None
    return type(value) is type(default) and value == default


def _fresh(default: JsonDefault) -> Any:
    """Lo de por defecto como se lee: ``[]`` y ``{}`` nuevos cada vez."""
    if isinstance(default, tuple):
        return []
    if isinstance(default, Mapping):
        return {}
    return default


def _json_copy(value: Any) -> Any:
    """Una copia de un valor de un JSON con sus listas y sus objetos nuevos."""
    if isinstance(value, dict):
        return {key: _json_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_copy(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class Decision:
    """Una decisión de la propiedad (``gb_decision`` con sus enlaces de ``gb_decision_link``;
    RF-009-13, D-33): quién decide (``decided_by``), el día en que se decidió (``decided_at``,
    «AAAA-MM-DD»), qué se decide, su origen (una entrada registrada de tipo documento,
    ``source_input_uid``, con el nombre que tiene hoy, ``source_name``, o una referencia en
    texto, ``source_text``, o las dos), quién y cuándo la registró, y a qué afecta: las claves
    de parámetro (``parameters``: todos sus ámbitos) y las versiones (``versions``, sus uid, y
    ``version_codes``, sus códigos, en el mismo orden), en el orden en que se enlazaron. Nada de
    ella cambia nunca (RF-009-12)."""

    uid: str
    decided_by: str
    decided_at: str
    what: str
    source_input_uid: str | None
    source_name: str | None
    source_text: str | None
    recorded_by: str
    recorded_at: str
    parameters: tuple[str, ...]
    versions: tuple[str, ...]
    version_codes: tuple[str, ...]

    @property
    def day(self) -> str:
        """El día de la decisión como se muestra: «03/10/2026»."""
        year, month, day = self.decided_at.split("-")
        return f"{day}/{month}/{year}"

    def decider(self, language: str = "es") -> str:
        """Cómo se muestra como decisor de un parámetro o de una versión (plan A10):
        «Propiedad: D. Juan … · 03/10/2026» (``language`` ``"en"``: «Owner: …»)."""
        return render("core.version_decision_decider", language=language, who=self.decided_by,
                      date=self.day)


# --- Mensajes ---------------------------------------------------------------------------------

MESSAGES: Mapping[str, str] = MappingProxyType({
    # RF-009-04 (spec §4.1; Versión no editable, barra-superior §7.3).
    "core.version_not_editable": "{version} is in state {state}: create a new version from it",
    "core.version_unknown": "There is no version {version} in the project",
    "core.version_state_unknown": (
        "«{target}» is not a state of a version: DRAFT, CURRENT, SUPERSEDED or DISCARDED"
    ),
    "core.version_same_state": "{version} is already in state {state}",
    "core.version_transition": (
        "{version} cannot go from {state} to {target}: a DRAFT version becomes CURRENT or "
        "DISCARDED, and a CURRENT one DISCARDED (it becomes SUPERSEDED when another version is "
        "declared CURRENT)"
    ),
    "core.version_freeze_first": "Freeze a revision of {version} first",
    "core.version_discard_reason": "State the reason for discarding {version}",
    "core.version_feature_required": (
        "State the feature of the new version (what sets it apart)"
    ),
    "core.version_title_required": "State the title of the version",
    "core.version_reason_required": "State the reason for the new version",
    "core.version_text_path": "«{text}» cannot contain an absolute path: the project stores none",
    "core.version_dataset_unknown": "There is no dataset {dataset} in the project",
    "core.version_dataset_title_required": "State the title of dataset «{dataset}»",
    # Operaciones de versión (RF-009-05, RF-009-01; plan A3, D-14, D-27).
    "core.version_required": (
        "This command belongs to a version: choose the active version or create one "
        "(Project ▸ Versions)"
    ),
    "core.version_data_in_project": (
        "The project operation «{op_type}» cannot use «{dataset}» of {version}: register it "
        "as a project input"
    ),
    "core.version_data_other": (
        "Operation «{op_type}» of {version} cannot use «{dataset}» of {owner}: from another "
        "version only what is frozen in the revision it starts from can be used"
    ),
    "core.version_frozen_not_parent": (
        "{version} can only take what is frozen in the revision it starts from "
        "({parent_revision}), not «{dataset}» of {revision}"
    ),
    "core.version_frozen_altered": (
        "Revision {revision} is altered: what is frozen in it is not used («{dataset}»)"
    ),
    "core.version_frozen_missing": "«{dataset}» is not frozen in {revision}",
    "core.version_frozen_project": (
        "«{dataset}» belongs to the project: its current content is used, not the one frozen "
        "in {revision}"
    ),
    # Lo que impide congelar una revisión (RF-009-08; plan A5 (1), D-40).
    "core.version_freeze_read_only": "The project is open read-only: {revision} cannot be frozen",
    "core.version_freeze_checking": (
        "Checking the project…: wait until it finishes to freeze {revision}"
    ),
    "core.version_freeze_in_progress": (
        "A revision is already being frozen ({names}): wait until it finishes"
    ),
    "core.version_freeze_running": (
        "{revision} has operations in progress ({names}): wait until they finish to freeze it"
    ),
    "core.version_freeze_input_changed": (
        "Inputs upstream of {revision} changed and are not decided yet ({names}): update them "
        "or keep the copy before freezing it"
    ),
    # La copia de una instantánea (RF-009-07; plan A5 (5) y A6).
    "core.version_freeze_no_space": (
        "There is no space to freeze {revision}: {needed} are needed in «{folder}» and {free} "
        "are left"
    ),
    "core.version_freeze_changed": (
        "«{dataset}» changed while {revision} was being frozen: nothing has been left "
        "half-done; freeze it again"
    ),
    "core.version_freeze_mismatch": (
        "The copy of «{dataset}» does not have its registered content: {revision} has not been "
        "frozen and nothing has been left half-done; check the disk and try again"
    ),
    "core.version_freeze_failed": (
        "{revision} could not be frozen ({reason}): nothing has been left half-done; check the "
        "free space, the permissions and that no program has «{file}» open"
    ),
    "core.version_freeze_leftover": (
        "There are leftovers of an earlier freeze in «{folder}»: open the project again to set "
        "them aside"
    ),
    # Congelar: el motivo, lo aceptado y la confirmación (RF-009-06, RF-009-08; plan A7, D-40).
    "core.version_freeze_reason": "State the reason for the new revision",
    "core.version_freeze_accept": (
        "To freeze {revision}, first accept what will be recorded as it is ({names})"
    ),
    "core.version_freeze_operation": (
        "«{op_type}» was registered in {version} while {revision} was being frozen: nothing "
        "has been left half-done; freeze it again"
    ),
    # Comprobar las instantáneas: una revisión alterada y lo que no coincide (RF-009-09; plan
    # A8, D-5, D-31).
    "core.version_snapshot_altered": (
        "Revision {revision} is altered: {count} files do not match what was frozen ({what}). "
        "It will not be used or reproduced"
    ),
    "core.version_snapshot_altered_one": (
        "Revision {revision} is altered: 1 file does not match what was frozen ({what}). It "
        "will not be used or reproduced"
    ),
    "core.version_snapshot_restored": "Revision {revision} matches what was frozen again",
    "core.version_mismatch_missing": "{path}: missing",
    "core.version_mismatch_size": "{path}: different size",
    "core.version_mismatch_sha256": "{path}: different fingerprint",
    "core.version_mismatch_imported_missing": "imported «{path}»: missing",
    "core.version_mismatch_imported_damaged": "imported «{path}»: damaged",
    # Reproducir una revisión: los rechazos, el avance, el informe y las causas (RF-009-11;
    # plan A9, D-32).
    "core.version_reproduce_unknown": "There is no revision {revision} in the project",
    "core.version_reproduce_not_frozen": (
        "{revision} is not frozen: only a frozen revision is reproduced"
    ),
    "core.version_reproduce_altered": (
        "Revision {revision} is altered ({what}): it is not reproduced"
    ),
    "core.version_reproduce_no_space": (
        "There is no space to reproduce {revision}: {needed} are needed in «{folder}» and "
        "{free} are left"
    ),
    "core.version_reproduce_failed": (
        "{revision} could not be reproduced ({reason}): nothing has been left half-done"
    ),
    "core.version_reproduce_progress": (
        "Reproducing {revision}: «{op_type}» ({index} of {count})…"
    ),
    "core.version_reproduce_summary": (
        "{revision} reproduced: {outputs} of {outputs_total} outputs and {figures} of "
        "{figures_total} figures match"
    ),
    "core.version_reproduce_differs": "«{name}» does not match: {cause}",
    "core.version_reproduce_taken": "{count} operations taken from what was frozen ({names})",
    "core.version_reproduce_taken_one": "1 operation taken from what was frozen ({names})",
    "core.version_reproduce_not_reproducible": "{count} operations not reproducible ({names})",
    "core.version_reproduce_not_reproducible_one": "1 operation not reproducible ({names})",
    "core.version_reproduce_cancelled": "Reproduction cancelled: nothing has been left half-done",
    "core.version_reproduce_why_import": "{op_type}, import",
    "core.version_reproduce_why_manual": "{op_type}, manual edit",
    "core.version_reproduce_why_type": "{op_type}, its type is not reproduced",
    "core.version_reproduce_why_module": "{op_type}, its module is not installed",
    "core.version_reproduce_why_unfrozen": "{op_type}: it used a content that was not frozen",
    "core.version_reproduce_why_failed": "{op_type} failed: {reason}",
    "core.version_cause_algorithm": "{op_type} {installed} installed, frozen with {frozen}",
    "core.version_cause_geoblender": "Geoblender {installed} installed, frozen with {frozen}",
    "core.version_cause_library": "{library} {installed} installed, frozen with {frozen}",
    "core.version_cause_unknown": "no known cause",
    "core.version_cause_missing": "{op_type} did not give it again",
    "core.version_cause_unreadable": "it cannot be read ({reason})",
    # Las decisiones de la propiedad (RF-009-13; plan A10, D-33).
    "core.version_decision_by_required": "State who decides",
    "core.version_decision_what_required": "State what is decided",
    "core.version_decision_date_required": "State when it was decided",
    "core.version_decision_date": (
        "The date of the decision is a day («YYYY-MM-DD»), not «{date}»"
    ),
    "core.version_decision_source_required": (
        "State the document or the reference of the decision (a document registered as an "
        "input or a text, such as «email of 03/10/2026»)"
    ),
    "core.version_decision_input_unknown": "There is no input {input} in the project",
    "core.version_decision_input_kind": (
        "Input «{input}» is not a document (it is of type {kind}): an owner decision rests on a "
        "registered document or on a text reference"
    ),
    "core.version_decision_parameter_unknown": "There is no parameter «{key}» in the project",
    "core.version_decision_decider": "Owner: {who} · {date}",
    # La revisión de un dato en su ficha (spec 009, T17; RF-009-20, D-9; plan A11):
    # «en curso (r2) · vigente: r1», «cerrada (r2) · congelada: r1 (alterada)».
    "core.version_revision_in_progress": "in progress ({revision})",
    "core.version_revision_current": "current: {revision}",
    "core.version_revision_frozen": "frozen: {revision}",
    "core.version_revision_closed": "closed ({revision})",
    "core.version_revision_altered": "{revision} (altered)",
})
"""Código → ``msgid`` (en inglés; su español, en ``core/i18n/messages.toml``)."""

MISSING_VALUE = "?"
"""Lo que se ve en lugar de un valor que falta (nunca el marcador ``{…}``)."""

_STATE_VALUES = frozenset({"state", "target"})
"""Los marcadores cuyo valor es un estado de versión: en inglés, con su etiqueta inglesa."""


class _Shown(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return MISSING_VALUE


def _show(name: str, value: object, language: str) -> str:
    if value is None:
        return MISSING_VALUE
    if name in _STATE_VALUES and isinstance(value, str) and value in VersionStatus:
        status = VersionStatus(value)
        return status.value if language == "es" else status.msgid
    return str(value)


def render(code: str, /, *, language: str = "es", **values: object) -> str:
    """El texto de ``code`` con ``values`` en sus marcadores, en ``language`` (``"es"``, de
    ``messages.toml``; ``"en"``, el ``msgid``), con los estados en su idioma. El marcador sin
    valor queda «?». :class:`ValueError` si el código o el idioma no existen."""
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    msgid = MESSAGES.get(code)
    if msgid is None:
        raise ValueError(f"el código de mensaje «{code}» no es de core.versions")
    template = translate(language, msgid)
    shown = _Shown({name: _show(name, value, language) for name, value in values.items()})
    return template.format_map(shown)


def _json_value(value: object) -> JsonScalar:
    if value is None or isinstance(value, str | int | float | bool):
        return str(value) if isinstance(value, VersionStatus) else value
    return str(value)


class VersionError(GeoblenderError):
    """Un rechazo de las versiones para el usuario: ``code`` (``core.version_*``), ``msgid``,
    ``values`` (JSON: los de sus marcadores, para el registro y para mostrarlo en inglés con
    :func:`render`), el objeto (la versión, si se conoce), el campo y el valor, y ``text`` en
    español, que es también ``str(error)`` y ``message``."""

    def __init__(self, code: str, /, *, field: str, value: object = None,
                 **values: object) -> None:
        msgid = MESSAGES.get(code)
        if msgid is None:
            raise ValueError(f"el código de mensaje «{code}» no es de core.versions")
        self.msgid = msgid
        self.values: dict[str, JsonScalar] = {k: _json_value(v) for k, v in values.items()}
        self.text = render(code, **self.values)
        version = self.values.get("version")
        obj = f"Versión {version}" if isinstance(version, str) else "Versiones del proyecto"
        super().__init__(code, self.text, obj=obj, field=field, value=value,
                         context=self.values)
        self.args = (self.text,)


def ensure_editable(version: Version) -> Version:
    """``version`` si es BORRADOR o VIGENTE; si no, :class:`VersionError`
    ``core.version_not_editable`` con el texto de RF-009-04 («V09 está en estado SUPERADO: cree
    una versión nueva a partir de ella»)."""
    if not version.editable:
        raise VersionError("core.version_not_editable", field="estado",
                           value=version.status.value, version=version.code,
                           state=version.status)
    return version
