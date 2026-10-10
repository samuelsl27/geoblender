# SPDX-License-Identifier: GPL-3.0-or-later
"""La carpeta de pruebas de la red, para las medidas en ``Z:`` (spec 008, T42; plan 008 §7 y
§7.3; ``docs/decisiones-pendientes.md``, DP-66).

Quien desarrolla define en su usuario de Windows ``GEOBLENDER_NET_TEST_DIR`` con una carpeta de
pruebas que crea IMGA en el NAS, fuera de la de los expedientes de clientes y fuera del espejo
del repositorio (``GEOBLENDER_NAS_ESPEJO``). Una prueba que la necesita se decora con
``resources.requires(NET, NET_HINT)``: sin la variable (o sin la carpeta) se omite con
``[ENTORNO] red: …`` y ``tools/check.py`` termina «VERDE CON OMISIONES».

Nunca se escribe en la carpeta de la variable: cada prueba trabaja en una subcarpeta temporal
propia (:func:`net_tmp`) que se borra entera al terminar. Una variable que apunta a los
expedientes de clientes (la primera carpeta de la unidad o del recurso compartido se llama como
:data:`DOSSIERS`) o dentro del espejo es un error de la prueba (:class:`ValueError`), nunca una
omisión: así no se escribe nada allí aunque la variable esté mal. Solo biblioteca estándar.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath

from tests.support import resources

NET = "red"  # el recurso de tests.support.resources
NET_TEST_DIR_ENV = "GEOBLENDER_NET_TEST_DIR"
NAS_MIRROR_ENV = "GEOBLENDER_NAS_ESPEJO"
NET_HINT = (
    f"defina {NET_TEST_DIR_ENV} en su usuario de Windows con la carpeta de pruebas de IMGA en "
    "la red (fuera de los expedientes de clientes y del espejo del repositorio; DP-66)"
)
DOSSIERS = "an"
"""La primera carpeta de la unidad del NAS con los expedientes de clientes: solo lectura."""


def _absolute(value: str) -> PureWindowsPath:
    """La ruta completa y resuelta de ``value`` (una unidad de red da su UNC)."""
    return PureWindowsPath(os.path.realpath(os.path.abspath(value)))


def _within(inner: PureWindowsPath, outer: PureWindowsPath) -> bool:
    """Si ``inner`` es ``outer`` o está dentro, por componentes (sin distinguir mayúsculas):
    ``…\\Geo_blender_pruebas`` no está dentro de ``…\\Geo_blender``."""
    return inner == outer or outer in inner.parents


def check_net_dir(value: str, mirror: str | None = None) -> Path:
    """La carpeta de pruebas ``value`` como ruta completa, si se puede escribir en ella:
    :class:`ValueError` si es (o está dentro de) la carpeta de los expedientes de clientes o
    el espejo ``mirror``. No mira si existe."""
    if not value.strip():
        raise ValueError(f"{NET_TEST_DIR_ENV} está vacía")
    resolved = _absolute(value)
    first = resolved.parts[1:2]
    if first and first[0].casefold() == DOSSIERS:
        raise ValueError(
            f"{NET_TEST_DIR_ENV} apunta a la carpeta de los expedientes de clientes, de solo "
            "lectura: defina una carpeta de pruebas"
        )
    if mirror and mirror.strip() and _within(resolved, _absolute(mirror)):
        raise ValueError(
            f"{NET_TEST_DIR_ENV} está dentro del espejo del repositorio ({NAS_MIRROR_ENV}), que "
            "solo escribe tools/publish.py: defina una carpeta de pruebas fuera de él"
        )
    return Path(str(resolved))


def net_test_dir(environ: Mapping[str, str] | None = None) -> Path | None:
    """La carpeta de pruebas de la red (:func:`check_net_dir`), o ``None`` si la variable no
    está definida o la carpeta no existe."""
    env = os.environ if environ is None else environ
    value = env.get(NET_TEST_DIR_ENV)
    if value is None or not value.strip():
        return None
    folder = check_net_dir(value, env.get(NAS_MIRROR_ENV))
    return folder if folder.is_dir() else None


def net_available() -> bool:
    """Si hay carpeta de pruebas de la red."""
    return net_test_dir() is not None


@contextmanager
def net_tmp(prefix: str) -> Iterator[Path]:
    """Una subcarpeta temporal nueva dentro de la carpeta de pruebas de la red; al salir se
    borra entera (solo ella). :class:`RuntimeError` si no hay carpeta de pruebas."""
    base = net_test_dir()
    if base is None:
        raise RuntimeError(f"no hay carpeta de pruebas de la red: {NET_HINT}")
    folder = Path(tempfile.mkdtemp(prefix=prefix, dir=base))
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


resources.register_resource(NET, net_available)
