# SPDX-License-Identifier: GPL-3.0-or-later
"""El cargador de vista de los sondeos (spec 005, T24; RF-005-23 a RF-005-25; RF-006-29; plan
005 §5.1 y §5.6.8).

:func:`register` registra en ``bl.scene.views`` el cargador de las trazas de los sondeos, por
el comienzo del nombre de su dato (:data:`PREFIX`, ``dh_trace``), con objetos del tipo
``DRILLHOLES`` en la rama «Sondeos» de la colección del proyecto; :func:`unregister` lo quita
(el de otro con el mismo comienzo, no). Los dos son idempotentes.

Las curvas por tramo y las barras de leyes, por pasos con los arrays del trabajo
``dh_view_arrays`` (plan §5.6.8), llegan con su orden: hasta entonces :func:`load_traces` dice
que la vista de los sondeos aún no está disponible (``dh.not_delivered``) y no crea nada, y la
orden de cargar sigue con los demás datos.
"""

from __future__ import annotations

from typing import Any

from ...core.errors import GeoblenderError
from ...drillholes.schema import LAYOUTS
from . import views

PREFIX = LAYOUTS["dh_trace"].name
"""El comienzo del nombre del dato que se carga: las trazas de los sondeos (``dh_trace``)."""
KIND = "DRILLHOLES"
"""El tipo de sus objetos (``Object.geoblender.kind``)."""
LABEL = "Drillholes"
"""El ``msgid`` de ese tipo en el nombre generado de sus objetos."""
NOT_DELIVERED = "dh.not_delivered"
"""El código del error de lo que aún no está disponible de los sondeos (spec 005)."""


def load_traces(request: Any) -> Any:
    """Las trazas de los sondeos en la vista (``bl.scene.views.ViewLoader``). Aún no están
    disponibles: ``GeoblenderError`` (``dh.not_delivered``) sin crear nada."""
    raise GeoblenderError(NOT_DELIVERED, "aún no está disponible: llega con la spec 005",
                          obj="Sondeos en la vista", field="dato", value=PREFIX)


def register() -> None:
    """Registra el cargador de las trazas si no hay otro para su comienzo; idempotente."""
    if PREFIX not in views.loaders():
        views.register_loader(PREFIX, KIND, LABEL, load_traces)


def unregister() -> None:
    """Quita el cargador de las trazas si es el suyo (el de otro, no); idempotente."""
    found = views.loaders().get(PREFIX)
    if found is not None and found.load is load_traces:
        views.unregister_loader(PREFIX)
