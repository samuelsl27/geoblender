# SPDX-License-Identifier: GPL-3.0-or-later
"""Mensajes de los trabajos en segundo plano (spec 004 §8; RF-004-07, RF-004-12; plan 004
§5.3.4).

Cada error que un trabajo puede mostrar tiene un **código** estable en inglés
(``"worker_unknown"``), un ``msgid`` en inglés (también su versión inglesa) y su texto en
español, el del §8 de la spec, con marcadores de ``str.format`` (``{job}``) con nombre en
inglés, los mismos en los dos (constitución, principio 10).

- :class:`Message`: un mensaje del catálogo; :data:`MESSAGES`, el catálogo por código.
- :data:`CATALOG_ES`: ``msgid`` → español, para ``core.i18n.install`` al registrar.
- :func:`render`: el texto de un código con sus valores, en español (el del registro y de
  ``msg`` en los eventos) o en inglés. Rellena todos los marcadores (un valor que falta
  queda «?») y nunca devuelve una traza de Python (RF-004-07).
- :class:`JobError`: el error de un trabajo para el usuario, con código, ``msgid``,
  valores (JSON) y texto.

Además de los del §8, ``source_changed`` (plan §5.3.1): la fuente de una entrada cambió
mientras se copiaba a la carpeta del trabajo.

Los errores propios de cada cálculo (``engine_missing_orientation``…) no están aquí:
llegan del worker con su código, su ``msgid`` y su texto en español.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..core.errors import GeoblenderError
from ..core.i18n import LANGUAGES

type JsonScalar = str | int | float | bool | None

MISSING_VALUE = "?"
"""Lo que se ve en lugar de un valor que falta (nunca el marcador ``{…}``)."""

TRACEBACK_MARK = "Traceback"

FLAG_TEXTS: Mapping[str, Mapping[str, str]] = MappingProxyType({
    "forced": MappingProxyType({"es": " (forzado)", "en": " (forced)"}),
})
"""Marcadores que reciben un booleano: verdadero, el sufijo en el idioma; falso, nada."""

ERROR_OBJECT = "Trabajo en segundo plano"


@dataclass(frozen=True, slots=True)
class Message:
    """Un mensaje del catálogo: código estable, ``msgid`` en inglés y texto en español."""

    code: str
    msgid: str
    es: str


_INTERPRETER_MSGID = "Could not start the interpreter {path}: {detail}."
_INTERPRETER_ES = "No se pudo arrancar el intérprete {path}: {detail}."
_OUTPUT_MSGID = "Result {path} of job «{job}» is missing or does not match its hash."
_OUTPUT_ES = "El resultado {path} del trabajo «{job}» falta o no coincide con su huella."

_CATALOG: tuple[Message, ...] = (
    Message(
        "request_invalid",
        "The request of job «{job}» is not valid: {detail}.",
        "La petición del trabajo «{job}» no es válida: {detail}.",
    ),
    Message(
        "request_path_outside_job",
        "Job «{job}» uses a path outside its folder: {path}.",
        "El trabajo «{job}» usa una ruta fuera de su carpeta: {path}.",
    ),
    Message(
        "worker_unknown",
        "Job type «{worker}» does not exist.",
        "No existe el tipo de trabajo «{worker}».",
    ),
    Message("interpreter_not_found", _INTERPRETER_MSGID, _INTERPRETER_ES),
    Message("interpreter_failed", _INTERPRETER_MSGID, _INTERPRETER_ES),
    Message(
        "runtime_missing",
        "This calculation needs the compute engine, which is not installed "
        "(Tools ▸ Jobs ▸ Compute engine).",
        "Este cálculo necesita el motor de cálculo, que no está instalado "
        "(Herramientas ▸ Trabajos ▸ Motor de cálculo).",
    ),
    Message(
        "runtime_mismatch",
        "The installed compute engine ({installed}) is not the one this version of "
        "Geoblender needs ({required}): update it.",
        "El motor de cálculo instalado ({installed}) no es el que necesita esta versión de "
        "Geoblender ({required}): actualícelo.",
    ),
    Message(
        "runtime_numpy_wrong",
        "The calculation loaded numpy from {path} and not from the compute engine; it "
        "stopped without calculating.",
        "El cálculo cargó numpy desde {path} y no desde el motor de cálculo; se ha detenido "
        "sin calcular.",
    ),
    Message(
        "runtime_package_mismatch",
        "Package {package} of the engine has version {actual} and the lock requires "
        "{locked}: repair the engine.",
        "El paquete {package} del motor tiene la versión {actual} y el lock exige {locked}: "
        "repare el motor.",
    ),
    Message(
        "runtime_blas_missing",
        "The numpy of the engine does not use an optimized BLAS (BLAS: {blas}).",
        "El numpy del motor no usa una BLAS optimizada (BLAS: {blas}).",
    ),
    Message(
        "wheel_hash_mismatch",
        "The hash of {file} does not match the one in the lock: installation cancelled, "
        "nothing has been installed.",
        "La huella de {file} no coincide con la del lock: instalación cancelada, no se ha "
        "instalado nada.",
    ),
    Message(
        "wheel_not_found",
        "{file} is not in the wheel store {folder}.",
        "No se encuentra {file} en el almacén de ruedas {folder}.",
    ),
    Message(
        "network_not_allowed",
        "Installing from PyPI needs internet and Blender has it disabled: turn on «Allow "
        "Online Access» (Preferences ▸ System) or set up the wheel store.",
        "Instalar desde PyPI necesita internet y Blender lo tiene desactivado: active "
        "«Permitir acceso en línea» (Preferencias ▸ Sistema) o configure el almacén de ruedas.",
    ),
    Message(
        "network_error",
        "Could not download {package}: {detail}.",
        "No se pudo descargar {package}: {detail}.",
    ),
    Message(
        "disk_space",
        "Not enough space on {drive}: {needed} MB are needed and {free} MB are left.",
        "No hay espacio en {drive}: hacen falta {needed} MB y quedan {free} MB.",
    ),
    Message(
        "external_python_invalid",
        "The external interpreter {path} is not valid: {reason}. Python 3.13 with numpy is "
        "needed.",
        "El intérprete externo {path} no sirve: {reason}. Hace falta Python 3.13 con numpy.",
    ),
    Message(
        "job_cancelled",
        "Job «{job}» cancelled{forced}.",
        "Trabajo «{job}» cancelado{forced}.",
    ),
    Message(
        "job_timeout",
        "Job «{job}» exceeded its maximum time of {seconds} s and has been stopped.",
        "El trabajo «{job}» superó su tiempo máximo de {seconds} s y se ha detenido.",
    ),
    Message(
        "job_interrupted",
        "Job «{job}» was interrupted: Geoblender closed while it was running.",
        "El trabajo «{job}» quedó interrumpido: Geoblender se cerró mientras se ejecutaba.",
    ),
    Message(
        "worker_crashed",
        "Calculation «{job}» ended unexpectedly (code {exit_code}). Details in its log.",
        "El cálculo «{job}» terminó de forma inesperada (código {exit_code}). Detalles en su "
        "registro.",
    ),
    Message(
        "protocol_no_result",
        "Job «{job}» ended without delivering results.",
        "El trabajo «{job}» terminó sin entregar resultados.",
    ),
    Message("output_missing", _OUTPUT_MSGID, _OUTPUT_ES),
    Message("output_hash_mismatch", _OUTPUT_MSGID, _OUTPUT_ES),
    # Del plan 004 §5.3.1 (copia verificada de entradas, ``paths.JobDir.copy_input``).
    Message(
        "source_changed",
        "File {path} changed while it was being copied for job «{job}»: it has not been "
        "used; try again when nobody is modifying it.",
        "El fichero {path} cambió mientras se copiaba para el trabajo «{job}»: no se ha "
        "usado; vuelva a intentarlo cuando nadie lo esté modificando.",
    ),
)

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in _CATALOG})
"""El catálogo por código (solo lectura)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType({m.msgid: m.es for m in _CATALOG})
"""``msgid`` → texto en español, para ``core.i18n.install`` (solo lectura)."""


def lookup(code: str) -> Message:
    """El mensaje de ``code``; :class:`ValueError` si no está en el catálogo (un error
    del programa: todo error de un trabajo tiene su texto en español aquí)."""
    message = MESSAGES.get(code)
    if message is None:
        raise ValueError(
            f"el código de mensaje «{code}» no está en el catálogo de los trabajos "
            "(jobs/messages.py)"
        )
    return message


def render(code: str, /, *, language: str = "es", **values: object) -> str:
    """El texto de ``code`` con ``values`` en sus marcadores, en ``language`` (``"es"``,
    el del registro, o ``"en"``, el ``msgid``).

    Rellena todos los marcadores: el que no tiene valor queda :data:`MISSING_VALUE` y los
    valores que sobran se ignoran. Los números salen en el formato del idioma; un booleano
    de :data:`FLAG_TEXTS`, como su sufijo. De un texto con una traza de Python solo queda
    su última línea, y las líneas de un texto se unen con espacios (RF-004-07).
    """
    if language not in LANGUAGES:
        raise ValueError(
            f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}"
        )
    message = lookup(code)
    template = message.es if language == "es" else message.msgid
    shown = _Shown({name: _show(name, value, language) for name, value in values.items()})
    return template.format_map(shown)


def json_value(value: object) -> JsonScalar:
    """``value`` como se guarda en el registro (JSON): los escalares tal cual y lo
    demás (una ``Path``) como texto."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


class JobError(GeoblenderError):
    """Error de un trabajo para el usuario (RF-004-12): ``code`` del catálogo, ``msgid``,
    ``values`` (JSON, para el registro y para mostrarlo en otro idioma con :func:`render`)
    y ``text`` en español, que es también ``str(error)`` y ``message``."""

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


def _show(name: str, value: object, language: str) -> str:
    """Un valor como lo lee una persona en ``language``."""
    if value is None:
        return MISSING_VALUE
    if isinstance(value, bool):
        flag = FLAG_TEXTS.get(name)
        if flag is not None:
            return flag[language] if value else ""
        if language == "es":
            return "sí" if value else "no"
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = str(int(value)) if value.is_integer() else repr(value)
        return text.replace(".", ",") if language == "es" else text
    return _one_line(str(value))


def _one_line(text: str) -> str:
    """``text`` en una línea; de una traza de Python, solo su última línea (la excepción)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if any(TRACEBACK_MARK in line for line in lines):
        lines = [line for line in lines if TRACEBACK_MARK not in line][-1:]
    return " ".join(lines)
