# SPDX-License-Identifier: GPL-3.0-or-later
"""Los sondeos en Blender (código ``dh``, spec 005; plan 005 §5.6; ADR-0025 §2).

Registra lo que los sondeos declaran a la 008. (T39) Sus **lectores de contenido**
(``interop.dh_content``: ``io.dh_csv@1``, ``io.dh_xlsx@1`` e ``io.recmin_mdb@1``) en
``core.content`` (RF-005-12, RF-008-09): así la lista estática del trabajo ``core_content_hash``
(``workers/core_content_hash.py``) coincide con lo que registra Blender. Los lectores resuelven
solos lo que necesitan (el extractor de bases de Access, de ``adapters.registry``): no hay que
darles nada. T24 añade aquí los parámetros, los tipos de trabajo, las declaraciones de
procedencia y los operadores.

:func:`register` pone lo que falta y apunta cómo quitarlo; :func:`unregister` quita solo eso, en
orden inverso: lo que otro registró antes con la misma clave, o puso después en su lugar, es
suyo y se queda. Los dos son simétricos e idempotentes (como ``bl/ops/gis.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...core.content import readers as content_readers
from ...interop import dh_content

classes: tuple[type, ...] = ()

_UNDO: list[Callable[[], None]] = []


def register() -> None:
    """Registra los lectores de contenido de los sondeos que aún no están; idempotente."""
    for reader in dh_content.CONTENT_READERS:
        if reader.id not in content_readers.READERS:
            content_readers.register_reader(reader)
            _UNDO.append(_unregister_if(content_readers.READERS, reader.id, reader,
                                        content_readers.unregister_reader))


def unregister() -> None:
    """Quita lo que puso :func:`register`, en orden inverso (lo que otro cambió después es
    suyo); idempotente."""
    while _UNDO:
        _UNDO.pop()()


def _unregister_if(view: Any, key: str, item: object,
                   remove: Callable[[str], object]) -> Callable[[], None]:
    def undo() -> None:
        if view.get(key) is item:  # si otro lo cambió, es suyo
            remove(key)

    return undo
