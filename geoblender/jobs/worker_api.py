# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que usa la función de dominio de un trabajo en los dos ejecutores (spec 004;
RF-004-09, RF-004-12; plan 004 §5.3.1 y §5.3.4).

- :class:`JobCancelled`: el trabajo atendió la cancelación (salida 3 en proceso aparte;
  «Cancelado», o «Tiempo agotado» si la pidió el tiempo máximo).
- :class:`JobFailed`: el cálculo falló por una causa que se explica al usuario (salida 2 y
  evento ``error`` en proceso aparte; «Fallido» en los dos ejecutores), con su código, su
  ``msgid`` en inglés, sus valores y su texto en español (RF-004-12).

``WorkerContext`` y los sumideros de eventos (stdout y cola) llegan con la tarea T07.
"""

from __future__ import annotations

from collections.abc import Mapping

from .messages import JobError
from .protocol import JsonValue, plain_json


class JobCancelled(Exception):
    """El trabajo paró porque se le pidió (RF-004-09). El texto, si lo hay, dice dónde
    («Cancelado en el trozo 11 de 20») y va al registro."""


class JobFailed(Exception):
    """Fallo de un cálculo explicado al usuario (RF-004-12): ``code`` (identificador
    estable en inglés, ``"engine_missing_orientation"``), ``msgid`` (inglés, con sus
    marcadores), ``values`` (JSON, para mostrarlo en otro idioma) y ``text`` (español, ya
    relleno), que es también ``str(error)``. Nunca lleva una traza de Python: la traza va
    al registro (``job.log``)."""

    def __init__(
        self,
        code: str,
        *,
        msgid: str,
        text: str,
        values: Mapping[str, JsonValue] | None = None,
    ) -> None:
        for name, value in (("code", code), ("msgid", msgid), ("text", text)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"el fallo de un trabajo necesita {name} (texto no vacío)")
        copied = plain_json({} if values is None else values, "values")
        if not isinstance(copied, dict):
            raise ValueError("los valores (values) del fallo no son un objeto JSON")
        self.code = code
        self.msgid = msgid
        self.text = text
        self.values: dict[str, JsonValue] = copied
        super().__init__(text)

    @classmethod
    def from_error(cls, error: JobError) -> JobFailed:
        """El fallo con el código, el ``msgid``, los valores y el texto de un
        :class:`~.messages.JobError` del catálogo de los trabajos (``request_invalid``…)."""
        return cls(error.code, msgid=error.msgid, text=error.text, values=error.values)
