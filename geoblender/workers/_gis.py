# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo común de los envoltorios de los trabajos de la topografía (``workers/gis_*.py``; spec
006, T26; RF-006-28; plan 006 §5.3.4 y §5.6.4).

Cada envoltorio llama a :func:`run` con el nombre de su función de ``gis.jobs``, que mira la
cancelación, registra los lectores de contenido de la lista estática del trabajo de hash (los
de ``core`` y los de ``gis``, con el lector de tablas de ``interop`` que necesitan los de
``gis``: ``core_content_hash.register_readers``) y llama a esa función, la misma que ejecuta el
hilo dentro de Blender (``WorkerInfo.run``): los dos ejecutores hacen lo mismo. ``gis`` se
importa después de mirar la cancelación: importarlo cuesta unas décimas, y un trabajo
cancelado nada más lanzarse lo atiende dentro de su plazo de gracia (como en T40).

No es un tipo de trabajo (su nombre empieza por «_»). No importa ``bl`` ni ``core.project``
(ARQ-11): lo del proyecto llega copiado a ``in/``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def run(ctx: Any, function: str) -> Mapping[str, Any]:
    """Mira la cancelación, registra los lectores y llama a ``gis.jobs.<function>(ctx)``."""
    ctx.check_cancelled()
    from ..gis import jobs
    from .core_content_hash import register_readers

    register_readers()
    return getattr(jobs, function)(ctx)


__all__ = ["run"]
