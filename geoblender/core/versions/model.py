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
- :func:`version_code` (1 → «V01») y :func:`revision_label` («V10.r2»).
- :class:`VersionError`: el rechazo para el usuario, con un código ``core.version_*`` del
  catálogo :data:`MESSAGES` (``msgid`` en inglés, con su español en
  ``core/i18n/messages.toml``) y :func:`render`, el texto en los dos idiomas.

Python puro; solo importa ``core.errors`` y ``core.i18n`` (``core.provenance`` lo usará sin
ciclos, ARQ-08).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from ..errors import GeoblenderError
from ..i18n import LANGUAGES, translate

type JsonScalar = str | int | float | bool | None


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
