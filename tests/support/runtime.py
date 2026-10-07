# SPDX-License-Identifier: GPL-3.0-or-later
"""El motor de cálculo de pruebas, para las pruebas que lo necesitan (spec 004, T30;
RF-004-28; plan 004 §7.1).

Una prueba que necesita el motor de cálculo (el numpy de PyPI con su OpenBLAS) se decora con
``resources.requires(RUNTIME, RUNTIME_HINT)``: si no hay motor de pruebas, se omite con
``[ENTORNO] runtime: <la orden que lo crea>`` y ``tools/check.py`` termina «VERDE CON
OMISIONES». El motor es el que encuentra ``tools/make_runtime.py``
(``find_test_runtime``): la carpeta ``site`` de ``GEOBLENDER_TEST_RUNTIME_SITE`` o la del
motor del lock en ``.deps/runtime/<lock_id>/`` de este repositorio, si está listo. Se mira al
ejecutar la prueba, no al importarla.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from tests.support import resources
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

import make_runtime  # noqa: E402

RUNTIME = "runtime"  # el recurso de tests.support.resources
RUNTIME_HINT = make_runtime.HINT
ENV_TEST_RUNTIME_SITE = make_runtime.ENV_TEST_SITE


def runtime_site(environ: Mapping[str, str] | None = None) -> Path | None:
    """La carpeta ``site`` del motor de cálculo de pruebas, o ``None`` si no hay
    (``environ``: donde se busca ``GEOBLENDER_TEST_RUNTIME_SITE``; por defecto, el del
    proceso)."""
    return make_runtime.find_test_runtime(ROOT, environ).site


def runtime_available() -> bool:
    """Si hay motor de cálculo de pruebas."""
    return runtime_site() is not None


resources.register_resource(RUNTIME, runtime_available)
