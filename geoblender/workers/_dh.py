# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo común de los envoltorios de los trabajos de los sondeos (``workers/dh_*.py``; spec 005,
T23; RNF-005-06; plan 005 §5.3.3 y §5.6.7).

Cada envoltorio llama a :func:`run` con el módulo y el nombre de su función: las dos lecturas
de una fuente (``dh_import_tabular`` y ``dh_import_recmin``), de ``interop.dh_jobs`` (leer
formatos ajenos es de ``interop``), y las demás, de ``drillholes.jobs``: la misma función que
ejecuta el hilo dentro de Blender (``WorkerInfo.run``), así que los dos ejecutores hacen lo
mismo. Ninguna usa el registro de lectores de contenido: leen con sus lectores
(``interop.dh_content``, ``core.gpkg_layer@1``) directamente. El módulo se importa después de
mirar la cancelación: importarlo cuesta unas décimas (carga ``gis``), y un trabajo cancelado
nada más lanzarse lo atiende dentro de su plazo de gracia (como ``workers/_gis.py``).

No es un tipo de trabajo (su nombre empieza por «_»). No importa ``bl`` ni ``core.project``
(ARQ-11): lo del proyecto llega copiado a ``in/``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

IMPORTS = "interop"
"""Las funciones de las lecturas de una fuente (``interop.dh_jobs``)."""
DOMAIN = "drillholes"
"""Las demás (``drillholes.jobs``)."""


def run(ctx: Any, module: str, function: str) -> Mapping[str, Any]:
    """Mira la cancelación y llama a ``<module>.<function>(ctx)`` (:data:`IMPORTS` o
    :data:`DOMAIN`)."""
    ctx.check_cancelled()
    if module == IMPORTS:
        from ..interop import dh_jobs as found
    elif module == DOMAIN:
        from ..drillholes import jobs as found  # type: ignore[no-redef]
    else:
        raise ValueError(f"los trabajos de los sondeos están en {IMPORTS} o {DOMAIN}, no "
                         f"{module!r}")
    return getattr(found, function)(ctx)


__all__ = ["DOMAIN", "IMPORTS", "run"]
