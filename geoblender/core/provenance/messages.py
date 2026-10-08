# SPDX-License-Identifier: GPL-3.0-or-later
"""Mensajes de la procedencia (spec 008 §8; plan 008 §3, principio 10, y §5.1).

Cada error de la procedencia que llega a una persona tiene un **código** estable en inglés
(``"core.operation_unregistered"``), un ``msgid`` en inglés (también su versión inglesa) y su
texto en español, con marcadores de ``str.format`` (``{op_type}``) con nombre en inglés, los
mismos en los dos (constitución, principio 10). Los nombres visibles de las operaciones de
``core`` (:data:`LABELS`) son también ``msgid`` con su español.

- :class:`Message`: un mensaje del catálogo; :data:`MESSAGES`, el catálogo por código.
- :data:`LABELS`: ``msgid`` → español de los nombres visibles de ``core``
  (``OperationDef.label_msgid`` de :mod:`.contract`).
- :data:`CATALOG_ES`: ``msgid`` → español de todo lo anterior, para ``core.i18n.install`` al
  registrar (``bl/ops/core_provenance.py``, T44).
- :func:`render`: el texto de un código con sus valores, en español o en inglés; el marcador
  sin valor queda «?».
- :class:`ProvenanceError`: el error de la procedencia para el usuario, con código,
  ``msgid``, valores (JSON) y texto; en solo lectura, todo lo que escribiría lanza
  ``core.read_only`` sin tocar nada (plan §5.3.1).

Cada tarea de la 008 añade aquí los códigos de sus rechazos (los textos de la spec §8, tal
cual) y sus avisos (``core.figure_differs``, RF-008-59). Python puro (ADR-0004).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..errors import GeoblenderError
from ..i18n import LANGUAGES

type JsonScalar = str | int | float | bool | None

MISSING_VALUE = "?"
"""Lo que se ve en lugar de un valor que falta (nunca el marcador ``{…}``)."""

ERROR_OBJECT = "Procedencia"
"""El objeto de un :class:`ProvenanceError` (``GeoblenderError.obj``)."""


@dataclass(frozen=True, slots=True)
class Message:
    """Un mensaje del catálogo: código ``core.*``, ``msgid`` en inglés y texto en español."""

    code: str
    msgid: str
    es: str


_INACTIVE_EN = (
    "the module that declares it is not active or belongs to another version of Geoblender."
)
_INACTIVE_ES = (
    "el módulo que {pronoun} declara no está activo o es de otra versión de Geoblender."
)

_CATALOG: tuple[Message, ...] = (
    Message(
        "core.read_only",
        "Project «{project}» is open read-only ({reason}): nothing has been recorded.",
        "El proyecto «{project}» está abierto en solo lectura ({reason}): no se ha registrado "
        "nada.",
    ),
    Message(
        "core.operation_unregistered",
        "No operation of type «{op_type}» is registered: " + _INACTIVE_EN,
        "No hay ninguna operación registrada del tipo «{op_type}»: "
        + _INACTIVE_ES.format(pronoun="la"),
    ),
    Message(
        "core.group_unregistered",
        "No group of coupled operations «{group}» is registered: " + _INACTIVE_EN,
        "No hay ningún grupo de operaciones acopladas «{group}» registrado: "
        + _INACTIVE_ES.format(pronoun="lo"),
    ),
    Message(
        "core.figure_unregistered",
        "No figure «{key}» is registered: " + _INACTIVE_EN,
        "No hay ninguna cifra «{key}» registrada: " + _INACTIVE_ES.format(pronoun="la"),
    ),
    Message(
        "core.importer_unregistered",
        "No importer is registered for reader «{reader}»: its inputs cannot be reimported "
        "until the module that declares it is active.",
        "No hay ningún importador registrado para el lector «{reader}»: sus entradas no se "
        "pueden reimportar hasta que esté activo el módulo que lo declara.",
    ),
    # Operaciones (T17; RF-008-18, RF-008-23, RF-008-51).
    Message(
        "core.operation_unknown",
        "There is no operation {operation} in project «{project}».",
        "No hay ninguna operación {operation} en el proyecto «{project}».",
    ),
    Message(
        "core.operation_not_running",
        "Operation «{op_type}» ({operation}) is no longer running: a finished operation does "
        "not change.",
        "La operación «{op_type}» ({operation}) ya no está en curso: una operación terminada "
        "no cambia.",
    ),
    Message(
        "core.operation_dataset_unknown",
        "Operation «{op_type}» consumes dataset «{item}», which is not in the project.",
        "La operación «{op_type}» consume el dato «{item}», que no está en el proyecto.",
    ),
    Message(
        "core.operation_dataset_not_live",
        "Operation «{op_type}» cannot consume dataset «{item}»: it is superseded or discarded "
        "and kept as history (consume its successor).",
        "La operación «{op_type}» no puede consumir el dato «{item}»: está sustituido o "
        "descartado y queda como historia (consuma su sucesor).",
    ),
    Message(
        "core.operation_input_unknown",
        "Operation «{op_type}» consumes input «{item}», which is not registered in the "
        "project.",
        "La operación «{op_type}» consume la entrada «{item}», que no está registrada en el "
        "proyecto.",
    ),
    Message(
        "core.operation_input_not_live",
        "Operation «{op_type}» cannot consume input «{item}»: it is superseded or discarded "
        "and kept as history.",
        "La operación «{op_type}» no puede consumir la entrada «{item}»: está sustituida o "
        "descartada y queda como historia.",
    ),
    Message(
        "core.operation_supersedes_unknown",
        "Operation «{op_type}» supersedes {supersedes}, which is not an operation of the "
        "project.",
        "La operación «{op_type}» sustituye a {supersedes}, que no es ninguna operación del "
        "proyecto.",
    ),
    Message(
        "core.operation_supersedes_not_done",
        "Operation «{op_type}» can only supersede a finished (done) operation, and "
        "{supersedes} is not.",
        "La operación «{op_type}» solo sustituye a una operación hecha, y {supersedes} no lo "
        "está.",
    ),
    Message(
        "core.operation_already_superseded",
        "Operation {supersedes} is already superseded, or another running operation is "
        "superseding it: «{op_type}» does not supersede it again.",
        "La operación {supersedes} ya está sustituida, o la está sustituyendo otra en curso: "
        "«{op_type}» no la vuelve a sustituir.",
    ),
    Message(
        "core.operation_output_not_saved",
        "Result «{name}» of operation «{op_type}» is not saved in the project ({locator}): "
        "save it in the project before completing the operation.",
        "El resultado «{name}» de la operación «{op_type}» no está guardado en el proyecto "
        "({locator}): se guarda en el proyecto antes de completar la operación.",
    ),
    Message(
        "core.operation_not_completed",
        "Operation «{op_type}» ended without completing its record: it is left failed and its "
        "results are not accepted.",
        "La operación «{op_type}» terminó sin completar su registro: queda fallida y sus "
        "resultados no se dan por buenos.",
    ),
    # Cifras (T19; RF-008-30, RF-008-59; spec §8): el rechazo nombra su clave y su operación.
    Message(
        "core.figure_operation_missing",
        "Figure «{key}» has no originating operation: only a running operation records it.",
        "La cifra «{key}» no tiene operación de origen: solo la registra una operación en "
        "curso.",
    ),
    Message(
        "core.figure_operation_not_running",
        "Figure «{key}» of operation «{op_type}» is not recorded: the operation is no longer "
        "running.",
        "La cifra «{key}» de la operación «{op_type}» no se registra: la operación ya no está "
        "en curso.",
    ),
    Message(
        "core.figure_kind_missing",
        "Figure «{key}» of operation «{op_type}» needs a type: CALCULATED, or that of the "
        "parameter it shows.",
        "La cifra «{key}» de la operación «{op_type}» necesita un tipo: CALCULADO, o el del "
        "parámetro que muestra.",
    ),
    Message(
        "core.figure_kind_unknown",
        "Figure «{key}» of operation «{op_type}» has type «{kind}», which is not MEASURED, "
        "CALCULATED, ADOPTED or HYPOTHESIS.",
        "La cifra «{key}» de la operación «{op_type}» tiene el tipo «{kind}», que no es "
        "MEDIDO, CALCULADO, ADOPTADO ni HIPÓTESIS.",
    ),
    Message(
        "core.figure_kind_without_parameter",
        "Figure «{key}» of operation «{op_type}» is {kind} and shows no parameter: what an "
        "operation computes is CALCULATED, and only a figure that shows a parameter carries "
        "its type.",
        "La cifra «{key}» de la operación «{op_type}» es {kind} y no muestra ningún "
        "parámetro: lo que calcula una operación es CALCULADO, y solo la cifra que muestra un "
        "parámetro lleva su tipo.",
    ),
    Message(
        "core.figure_parameter_kind",
        "Figure «{key}» of operation «{op_type}» shows parameter «{parameter}», which is "
        "{parameter_kind}: it carries that type, not {kind}.",
        "La cifra «{key}» de la operación «{op_type}» muestra el parámetro «{parameter}», que "
        "es {parameter_kind}: lleva su tipo, no {kind}.",
    ),
    Message(
        "core.figure_parameter_value",
        "Figure «{key}» of operation «{op_type}» shows parameter «{parameter}» "
        "({parameter_value}) and is {value}: if the operation computes it, the figure is "
        "CALCULATED.",
        "La cifra «{key}» de la operación «{op_type}» muestra el parámetro «{parameter}» "
        "({parameter_value}) y vale {value}: si la operación lo calcula, la cifra es "
        "CALCULADO.",
    ),
    Message(
        "core.figure_unit_missing",
        "Figure «{key}» of operation «{op_type}» needs its unit from Geoblender's unit "
        "catalog («-» if it is dimensionless).",
        "La cifra «{key}» de la operación «{op_type}» necesita su unidad del catálogo de "
        "unidades de Geoblender («-» si es adimensional).",
    ),
    Message(
        "core.figure_unit_unknown",
        "Figure «{key}» of operation «{op_type}» is in «{unit}», which is not in Geoblender's "
        "unit catalog.",
        "La cifra «{key}» de la operación «{op_type}» está en «{unit}», que no está en el "
        "catálogo de unidades de Geoblender.",
    ),
    Message(
        "core.figure_unit_other",
        "Figure «{key}» of operation «{op_type}» is in «{unit}» and its definition declares "
        "it in «{declared}».",
        "La cifra «{key}» de la operación «{op_type}» está en «{unit}» y su definición la "
        "declara en «{declared}».",
    ),
    Message(
        "core.figure_value_missing",
        "Figure «{key}» of operation «{op_type}» has no value: check its inputs.",
        "La cifra «{key}» de la operación «{op_type}» no tiene valor: revise sus entradas.",
    ),
    Message(
        "core.figure_nan",
        "Figure «{key}» of operation «{op_type}» is NaN: check its inputs.",
        "La cifra «{key}» de la operación «{op_type}» es NaN: revise sus entradas.",
    ),
    Message(
        "core.figure_infinite",
        "Figure «{key}» of operation «{op_type}» is infinite: check its inputs.",
        "La cifra «{key}» de la operación «{op_type}» es infinita: revise sus entradas.",
    ),
    Message(
        "core.figure_zero",
        "Figure «{key}» of operation «{op_type}» is zero and its definition does not admit "
        "it: check its inputs.",
        "La cifra «{key}» de la operación «{op_type}» es cero y su definición no lo admite: "
        "revise sus entradas.",
    ),
    Message(
        "core.figure_negative",
        "Figure «{key}» of operation «{op_type}» is negative ({value}) and its definition "
        "does not admit it: check its inputs.",
        "La cifra «{key}» de la operación «{op_type}» es negativa ({value}) y su definición no "
        "lo admite: revise sus entradas.",
    ),
    # El aviso de RF-008-59 (spec §8): el parámetro no cambia.
    Message(
        "core.figure_differs",
        "Operation «{op_type}» computes {name} = {value}; the {kind} value is "
        "{parameter_value} ({decided_by}, {decided_on}).",
        "La operación «{op_type}» calcula {name} = {value}; el valor {kind} es "
        "{parameter_value} ({decided_by}, {decided_on}).",
    ),
    # Entradas (T20; RF-008-07, RF-008-11, RF-008-54): el CRS declarado nunca se supone y la
    # misma fuente no se duplica.
    Message(
        "core.input_crs_missing",
        "Input «{name}» ({kind}) does not declare its {axis} CRS: declare it when importing; "
        "Geoblender never assumes it.",
        "La entrada «{name}» ({kind}) no declara su CRS {axis}: declárelo al importar; "
        "Geoblender nunca lo supone.",
    ),
    Message(
        "core.input_crs_not_applicable",
        "Input «{name}» is of type «{kind}», which has coordinates: its {axis} CRS cannot be "
        "«not applicable».",
        "La entrada «{name}» es de tipo «{kind}», con coordenadas: su CRS {axis} no puede ser "
        "«no aplica».",
    ),
    Message(
        "core.input_reused",
        "Input «{name}» is already registered with the same content ({registered_on}).",
        "La entrada «{name}» ya está registrada con el mismo contenido ({registered_on}).",
    ),
    Message(
        "core.input_substitution_required",
        "Input «{name}» has the same content as «{existing}» with other import settings "
        "({differences}): the import replaces it, with a reason.",
        "La entrada «{name}» tiene el mismo contenido que «{existing}» con otros ajustes de "
        "importación ({differences}): la importación la sustituye, con un motivo.",
    ),
    Message(
        "core.input_reason_missing",
        "State the reason for replacing input «{previous}» with «{name}».",
        "Indique el motivo de la sustitución de la entrada «{previous}» por «{name}».",
    ),
    Message(
        "core.input_name_taken",
        "There is already another input «{name}» in the project: choose another name or "
        "update that input.",
        "Ya hay otra entrada «{name}» en el proyecto: elija otro nombre o actualice esa "
        "entrada.",
    ),
    Message(
        "core.input_previous_unknown",
        "The input that «{name}» replaces ({previous}) is not in the project.",
        "La entrada a la que sustituye «{name}» ({previous}) no está en el proyecto.",
    ),
    Message(
        "core.input_previous_discarded",
        "Input «{previous}» is discarded: it is kept as a record and is not updated.",
        "La entrada «{previous}» está descartada: queda como registro y no se actualiza.",
    ),
    Message(
        "core.input_previous_replaced",
        "Input «{previous}» is already replaced by «{other}»: «{name}» does not replace it "
        "again.",
        "La entrada «{previous}» ya está sustituida por «{other}»: «{name}» no la vuelve a "
        "sustituir.",
    ),
    Message(
        "core.input_operation_missing",
        "Input «{name}» is registered with its import operation: without provenance it is not "
        "accepted.",
        "La entrada «{name}» se registra con su operación de importación: sin procedencia no "
        "se admite.",
    ),
    Message(
        "core.input_operation_unknown",
        "The import operation of input «{name}» ({operation}) is not in the project.",
        "La operación de importación de la entrada «{name}» ({operation}) no está en el "
        "proyecto.",
    ),
    Message(
        "core.input_operation_not_running",
        "Import operation «{op_type}» of input «{name}» ({operation}) is no longer running: the "
        "input is registered before completing it.",
        "La operación de importación «{op_type}» de la entrada «{name}» ({operation}) ya no "
        "está en curso: la entrada se registra antes de completarla.",
    ),
    Message(
        "core.input_table_missing",
        "Table «{table}» of input «{name}» is not a layer or table of the project.",
        "La tabla «{table}» de la entrada «{name}» no es una capa ni una tabla del proyecto.",
    ),
)

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in _CATALOG})
"""Los mensajes por código (solo lectura)."""

EXTERNAL_EDIT_MSGID = "External edit"
ACCEPT_REVIEW_MSGID = "Accept as good"
IMPORT_LAYER_MSGID = "Register layer as input"

LABELS: Mapping[str, str] = MappingProxyType({
    EXTERNAL_EDIT_MSGID: "Edición externa",
    ACCEPT_REVIEW_MSGID: "Dar por buena",
    IMPORT_LAYER_MSGID: "Registrar la capa como entrada",
})
"""Nombres visibles de las operaciones de ``core``: ``msgid`` → español (solo lectura)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType(
    {**{m.msgid: m.es for m in _CATALOG}, **LABELS}
)
"""``msgid`` → español de los mensajes y los nombres visibles, para ``core.i18n.install``
(solo lectura)."""


def lookup(code: str) -> Message:
    """El mensaje de ``code``; :class:`ValueError` si no está en el catálogo (un error del
    programa: todo error de la procedencia tiene aquí su texto en español)."""
    message = MESSAGES.get(code)
    if message is None:
        raise ValueError(
            f"el código de mensaje «{code}» no está en el catálogo de la procedencia "
            "(core/provenance/messages.py)"
        )
    return message


def render(code: str, /, *, language: str = "es", **values: object) -> str:
    """El texto de ``code`` con ``values`` en sus marcadores, en ``language`` (``"es"`` o
    ``"en"``, el ``msgid``). El marcador sin valor queda :data:`MISSING_VALUE`; los valores
    que sobran se ignoran. :class:`ValueError` si el código o el idioma no existen."""
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    message = lookup(code)
    template = message.es if language == "es" else message.msgid
    shown = _Shown({name: _show(value, language) for name, value in values.items()})
    return template.format_map(shown)


def json_value(value: object) -> JsonScalar:
    """``value`` como se guarda en el registro (JSON): los escalares tal cual y lo demás
    como texto."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


class ProvenanceError(GeoblenderError):
    """Error de la procedencia para el usuario: ``code`` del catálogo, ``msgid``, ``values``
    (JSON, para el registro y para mostrarlo en otro idioma con :func:`render`) y ``text`` en
    español, que es también ``str(error)`` y ``message``."""

    def __init__(self, code: str, /, **values: object) -> None:
        message = lookup(code)
        self.msgid = message.msgid
        self.values: dict[str, JsonScalar] = {k: json_value(v) for k, v in values.items()}
        self.text = render(code, **self.values)
        super().__init__(code, self.text, obj=ERROR_OBJECT, field="código", value=code,
                         context=self.values)
        self.args = (self.text,)


class _Shown(dict[str, str]):
    """Valores ya presentados; el que falta se ve como :data:`MISSING_VALUE`."""

    def __missing__(self, key: str) -> str:
        return MISSING_VALUE


def _show(value: object, language: str) -> str:
    """Un valor como lo lee una persona en ``language``: decimales con coma en español."""
    if value is None:
        return MISSING_VALUE
    if isinstance(value, bool):
        if language == "es":
            return "sí" if value else "no"
        return "yes" if value else "no"
    if isinstance(value, float):
        text = str(int(value)) if value.is_integer() else repr(value)
        return text.replace(".", ",") if language == "es" else text
    return str(value)
