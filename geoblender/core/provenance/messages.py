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
cual), sus avisos (``core.figure_differs``, RF-008-59) y los motivos de lo que se deja fuera de
«Recalcular lo obsoleto» (``core.recompute_*``). Python puro (ADR-0004).
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
    # Sustituir, mantener la copia, descartar y editar (T21; RF-008-11, RF-008-12,
    # RF-008-55; D-11): una entrada sustituida o descartada queda como historia.
    Message(
        "core.input_unknown",
        "There is no input {input} in project «{project}».",
        "No hay ninguna entrada {input} en el proyecto «{project}».",
    ),
    Message(
        "core.input_superseded",
        "Input «{name}» is already superseded: it is kept as history and does not change.",
        "La entrada «{name}» ya está sustituida: queda como historia y no cambia.",
    ),
    Message(
        "core.input_discarded",
        "Input «{name}» is discarded: it is kept as a record and does not change.",
        "La entrada «{name}» está descartada: queda como registro y no cambia.",
    ),
    Message(
        "core.input_supersede_reason_missing",
        "State the reason for replacing input «{name}».",
        "Indique el motivo de la sustitución de la entrada «{name}».",
    ),
    Message(
        "core.input_discard_reason_missing",
        "State the reason for discarding input «{name}».",
        "Indique el motivo para descartar la entrada «{name}».",
    ),
    Message(
        "core.input_not_changed",
        "Input «{name}» has not changed: there is no change to decide on.",
        "La entrada «{name}» no ha cambiado: no hay ningún cambio que decidir.",
    ),
    Message(
        "core.input_already_kept",
        "Input «{name}» is already «changed · copy kept».",
        "La entrada «{name}» ya está «cambiada · se mantiene la copia».",
    ),
    # Comprobación de las fuentes (T25; RF-008-10, RF-008-13): el aviso de la spec §8 de una
    # entrada cambiada, con la fecha de su fuente, y las que no se pueden comprobar.
    Message(
        "core.input_changed",
        "Input «{name}» has changed since it was registered ({registered}). Depending on it: "
        "{datasets}, {operations} and {figures}.",
        "La entrada «{name}» ha cambiado desde su registro ({registered}). Dependen de ella: "
        "{datasets}, {operations} y {figures}.",
    ),
    Message(
        "core.input_changed_source",
        "Date of the source: {source_date}.",
        "Fecha de la fuente: {source_date}.",
    ),
    Message(
        "core.input_unreachable",
        "The source of input «{name}» cannot be found ({file}): not locatable; the imported "
        "data is still used.",
        "No se encuentra la fuente de la entrada «{name}» ({file}): no localizable; se sigue "
        "con lo importado.",
    ),
    Message(
        "core.input_unreadable",
        "The source of input «{name}» cannot be read with its reader «{reader}» ({reason}): the "
        "imported data is still used.",
        "No se puede leer la fuente de la entrada «{name}» con su lector «{reader}» "
        "({reason}): se sigue con lo importado.",
    ),
    # Originales (T22; RF-008-53, RF-008-14): el aviso de la spec §8 por encima del límite
    # (D-18) y los rechazos de la copia verificada, que nunca se rehace desde la fuente.
    Message(
        "core.original_too_large",
        "The original of «{file}» ({size} MB) exceeds the limit of {limit} MB: only the "
        "imported data is kept.",
        "El original de «{file}» ({size} MB) pasa del límite de {limit} MB: se guarda solo lo "
        "importado.",
    ),
    Message(
        "core.original_copy_missing",
        "The verified copy of «{file}» of input «{name}» is missing: its original is not kept; "
        "import it again.",
        "Falta la copia verificada de «{file}» de la entrada «{name}»: no se guarda su "
        "original; vuelva a importarla.",
    ),
    Message(
        "core.original_copy_mismatch",
        "The verified copy of «{file}» of input «{name}» does not match its registered "
        "fingerprint: its original is not kept; import it again.",
        "La copia verificada de «{file}» de la entrada «{name}» no coincide con su huella "
        "registrada: no se guarda su original; vuelva a importarla.",
    ),
    Message(
        "core.original_exists",
        "There is already a file «{path}» in the originals of the project: it is not "
        "overwritten.",
        "Ya hay un fichero «{path}» en los originales del proyecto: no se sobrescribe.",
    ),
    Message(
        "core.original_copy_failed",
        "The original of «{file}» of input «{name}» could not be kept ({reason}): nothing is "
        "left half-done.",
        "No se ha podido guardar el original de «{file}» de la entrada «{name}» ({reason}): no "
        "queda nada a medias.",
    ),
    # Guarda de las escrituras (T23; RF-008-15, RF-008-14; S-3 del plan): los rechazos de la
    # spec §8 y los avisos de las carpetas de solo lectura.
    Message(
        "core.write_target_source_folder",
        "Cannot write in folder «{folder}»: it contains the source of input «{name}».",
        "No se puede escribir en la carpeta «{folder}»: contiene la fuente de la entrada "
        "«{name}».",
    ),
    Message(
        "core.write_target_source",
        "Cannot write to «{file}»: it is the source of input «{name}».",
        "No se puede escribir en «{file}»: es la fuente de la entrada «{name}».",
    ),
    Message(
        "core.write_target_read_only",
        "Folder «{folder}» is read-only in the Geoblender preferences.",
        "La carpeta «{folder}» es de solo lectura en las preferencias de Geoblender.",
    ),
    Message(
        "core.read_only_dirs_empty",
        "There is no read-only folder: neither the variable {variable} nor the Geoblender "
        "preferences declare any, so client dossiers are not protected from Geoblender writes.",
        "No hay ninguna carpeta de solo lectura: ni la variable {variable} ni las preferencias "
        "de Geoblender declaran ninguna, así que los expedientes de clientes no están "
        "protegidos de las escrituras de Geoblender.",
    ),
    Message(
        "core.read_only_dir_ignored",
        "Read-only folder «{folder}» is ignored: it is not a full path, with its drive or on "
        "the network.",
        "No se tiene en cuenta la carpeta de solo lectura «{folder}»: no es una ruta completa, "
        "con su unidad o de red.",
    ),
    # Obsolescencia deducida (T26; RF-008-24, RF-008-25): «Obsoleto: …» y una causa por
    # clase de ``gb_stale.cause_kind`` (``core.cause_<clase>``).
    Message("core.stale", "Stale: {causes}", "Obsoleto: {causes}"),
    Message("core.cause_dataset_changed", "«{name}» changed", "cambió «{name}»"),
    Message("core.cause_parameter_changed", "{name} changed", "cambió {name}"),
    Message("core.cause_input_updated", "input «{name}» was updated",
            "se actualizó la entrada «{name}»"),
    Message("core.cause_input_discarded", "input «{name}» was discarded",
            "se descartó la entrada «{name}»"),
    Message("core.cause_dataset_missing", "«{name}» is missing", "falta «{name}»"),
    Message("core.cause_dataset_blocked", "«{name}» is blocked by an external edit",
            "«{name}» está bloqueado por una edición externa"),
    Message("core.cause_dataset_damaged", "«{name}» is damaged: it can only be reimported",
            "«{name}» está dañado: solo se puede reimportar"),
    Message(
        "core.cause_algorithm",
        "Geoblender changes the algorithm of {op_type} ({registered} → {installed})",
        "Geoblender cambia el algoritmo de {op_type} ({registered} → {installed})",
    ),
    Message("core.cause_group", "it is coupled in group «{group}»",
            "está acoplada en el grupo «{group}»"),
    # Plan de «Recalcular lo obsoleto» (T28; RF-008-25, RF-008-26, RF-008-27): por qué una
    # operación obsoleta se deja fuera (un tipo que no está instalado da
    # ``core.operation_unregistered``).
    Message(
        "core.recompute_review",
        "Review by hand: operation «{op_type}» is not repeated on its own; redo it or accept "
        "it as good.",
        "Revisar a mano: la operación «{op_type}» no se repite sola; rehágala o dela por "
        "buena.",
    ),
    Message(
        "core.recompute_waits",
        "Waits for what is upstream of it and is not recomputed now: {operations}.",
        "Espera a lo que tiene aguas arriba y no se recalcula ahora: {operations}.",
    ),
    Message(
        "core.recompute_group",
        "It is coupled in group «{group}» and is not recomputed without {operations}.",
        "Está acoplada en el grupo «{group}» y no se recalcula sin {operations}.",
    ),
    Message(
        "core.recompute_newer_algorithm",
        "Computed with {op_type} {version}: update Geoblender",
        "Calculado con {op_type} {version}: actualice Geoblender",
    ),
    # Ejecución del plan (T29; RF-008-26): una unidad que al empezar no se ejecuta (sigue
    # obsoleta) y una que no se pudo recalcular.
    Message(
        "core.recompute_input_changed",
        "Not recomputed: input «{name}» has changed and it has not been decided whether to "
        "update it or keep the copy.",
        "No se recalcula: la entrada «{name}» ha cambiado y no se ha decidido si actualizarla "
        "o mantener la copia.",
    ),
    Message(
        "core.recompute_dataset_unusable",
        "Not recomputed: dataset «{name}» that it consumes is missing, blocked or damaged.",
        "No se recalcula: el dato «{name}» que consume falta, está bloqueado o dañado.",
    ),
    Message(
        "core.recompute_no_successor",
        "Not recomputed: «{name}», which it consumed, was discarded and has no successor.",
        "No se recalcula: «{name}», que consumía, se descartó y no tiene sucesor.",
    ),
    Message(
        "core.recompute_failed",
        "Operation «{op_type}» could not be recomputed: {reason}",
        "No se pudo recalcular la operación «{op_type}»: {reason}",
    ),
    # «Dar por buena» una operación que espera revisión a mano (T29; RF-008-27, D-12).
    Message(
        "core.accept_review_reason_missing",
        "A reason is missing: accepting operation «{op_type}» as good is recorded with it.",
        "Falta el motivo: dar por buena la operación «{op_type}» queda registrado con él.",
    ),
    Message(
        "core.accept_review_not_review",
        "Operation «{op_type}» ({operation}) is not waiting for review by hand: there is "
        "nothing to accept as good.",
        "La operación «{op_type}» ({operation}) no espera revisión a mano: no hay nada que dar "
        "por bueno.",
    ),
    Message(
        "core.accept_review_upstream",
        "Operation «{op_type}» cannot be accepted as good yet: what it consumes is still "
        "stale ({names}); recompute or review it first.",
        "La operación «{op_type}» aún no se puede dar por buena: lo que consume sigue "
        "obsoleto ({names}); recalcúlelo o revíselo antes.",
    ),
    Message(
        "core.accept_review_imported",
        "Operation «{op_type}» wrote what was imported from input «{name}»: it is not "
        "accepted as good; update or reimport the input.",
        "La operación «{op_type}» escribió lo importado de la entrada «{name}»: no se da por "
        "buena; actualice o reimporte la entrada.",
    ),
    Message(
        "core.accept_review_output",
        "Dataset «{name}» written by operation «{op_type}» is missing, blocked or damaged: "
        "resolve it before accepting the operation as good.",
        "El dato «{name}» que escribió la operación «{op_type}» falta, está bloqueado o "
        "dañado: resuélvalo antes de dar la operación por buena.",
    ),
    Message(
        "core.accept_review_changed",
        "Dataset «{name}» is no longer the one written by operation «{op_type}»: check the "
        "project data before accepting it as good.",
        "El dato «{name}» ya no es el que escribió la operación «{op_type}»: compruebe los "
        "datos del proyecto antes de darla por buena.",
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
