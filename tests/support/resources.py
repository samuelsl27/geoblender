# SPDX-License-Identifier: GPL-3.0-or-later
"""Omisión de pruebas por un recurso opcional (plan 001 §5.2 y §5.3, contrato 5).

Una prueba que necesita un recurso que puede faltar en un puesto (el motor de cálculo,
el motor de Access, QGIS…) se decora con :func:`requires`. Si el recurso no está
disponible, se omite con el motivo ``[ENTORNO] <recurso>: <orden que lo instala>``;
``tools/check.py`` cuenta esas omisiones y termina en «VERDE CON OMISIONES (n)», con
código 0 y la lista de recursos y órdenes. Una omisión no es un fallo, pero se ve: una
spec no se cierra con omisiones de sus propios recursos (``definicion-de-hecho.md`` §3).

Cada spec registra cómo se sabe si su recurso está disponible
(:func:`register_resource`, p. ej. ``runtime`` en la 004, ``ace`` en la 005, ``qgis``
en la 002 y la 006). La disponibilidad se consulta al ejecutar la prueba, no al
importarla. Un recurso sin comprobación registrada es un error de la prueba, no una
omisión: un nombre mal escrito no puede quedar omitido para siempre.

Una prueba que solo sabe si le falta algo al intentarlo (crear un enlace simbólico,
encontrar Blender en la ruta por defecto) se omite con :func:`skip_reason`, también con
el recurso y la orden. Una omisión sin ese motivo (``@unittest.skip``,
``skipTest("…")``) no es una omisión por un recurso: ``tools/check.py`` la cuenta como
fallo de su paso, porque esconde una prueba que no se ejecuta (convergencia de la spec
001, T42).

Los recursos válidos son una lista cerrada, :data:`RESOURCES`: los de la plataforma
(``symlink``, ``windows`` y ``blender``) y los que añada cada spec en su tarea, aquí y en
su plan (``git``, de la 007: lo registra ``tests.support.gitrepo``; ``qgis``, de la 002:
lo registra ``tests.support.qgis``). ``tools/check.py`` la lee de este fichero (sin
importarlo: solo biblioteca
estándar, HER-01) y cuenta como omisión sin recurso, un fallo, cualquier «[ENTORNO]
<recurso>» que no esté en ella: un recurso inventado (``skip_reason('nada', 'nada')``) o
el de una spec que aún no lo ha declarado (convergencia de la spec 001, T47). Por eso
:data:`RESOURCES` es una tupla de textos literales.
"""

from __future__ import annotations

import functools
import unittest
from collections.abc import Callable
from typing import Any, TypeVar

SKIP_PREFIX = "[ENTORNO]"

# Recursos de la plataforma, para skip_reason (spec 001).
SYMLINK = "symlink"
SYMLINK_HINT = (
    "permita crear enlaces simbólicos: active el modo de desarrollador de Windows "
    "(Configuración › Sistema › Para programadores) o ejecute las pruebas como "
    "administrador"
)
WINDOWS = "windows"
WINDOWS_HINT = "ejecute las pruebas en Windows (ADR-0003: la plataforma es windows-x64)"
BLENDER = "blender"  # el motivo es el mensaje del localizador (gbtools.blender)

# Lista cerrada de los recursos por los que se puede omitir una prueba: la lee
# tools/check.py como texto (ast.literal_eval), así que solo textos literales. Cada spec
# añade aquí el suyo (p. ej. «runtime» la 004, «ace» la 005; «git» la 007, para las
# pruebas de la publicación; «qgis» la 002, el GDAL de QGIS, que lo registra
# tests.support.qgis, y también lo usará la 006; «docs» la 003, la carpeta de la
# documentación, contra la que se comprueba el catálogo de comandos, que lo registra
# tests.support.docs; «runtime» la 004, el motor de cálculo de pruebas de
# tools/make_runtime.py, que lo registra tests.support.runtime).
RESOURCES: tuple[str, ...] = (
    "symlink", "windows", "blender", "git", "qgis", "docs", "runtime"
)

T = TypeVar("T")

_CHECKS: dict[str, Callable[[], bool]] = {}


def register_resource(resource: str, is_available: Callable[[], bool]) -> None:
    """Registra la función que dice si ``resource`` está disponible en este puesto."""
    _CHECKS[resource] = is_available


def unregister_resource(resource: str) -> None:
    """Retira la comprobación de ``resource`` (si no estaba, no hace nada)."""
    _CHECKS.pop(resource, None)


def skip_reason(resource: str, install_hint: str) -> str:
    """Motivo de la omisión: ``[ENTORNO] <recurso>: <orden que lo instala>``."""
    return f"{SKIP_PREFIX} {resource}: {install_hint}"


def is_available(resource: str) -> bool:
    """Verdadero si el recurso está disponible; ``KeyError`` si no está registrado."""
    check = _CHECKS.get(resource)
    if check is None:
        raise KeyError(
            f"el recurso «{resource}» no tiene comprobación registrada: regístrela con "
            "tests.support.resources.register_resource antes de usar requires"
        )
    return bool(check())


def requires(resource: str, install_hint: str) -> Callable[[T], T]:
    """Decorador de clase de prueba o de método que omite si falta ``resource``.

    En una clase, la omisión se decide en ``setUpClass`` (no se ejecuta la preparación
    de la clase); en un método, al empezar la prueba.
    """
    reason = skip_reason(resource, install_hint)

    def decorate(obj: T) -> T:
        if isinstance(obj, type):
            if not issubclass(obj, unittest.TestCase):
                raise TypeError(
                    f"requires decora clases de unittest.TestCase o métodos, no {obj!r}"
                )
            return _decorate_class(obj, resource, reason)  # type: ignore[return-value]
        if not callable(obj):
            raise TypeError(f"requires decora clases de prueba o métodos, no {obj!r}")
        return _decorate_method(obj, resource, reason)  # type: ignore[return-value]

    return decorate


def _decorate_method(
    method: Callable[..., Any], resource: str, reason: str
) -> Callable[..., Any]:
    @functools.wraps(method)
    def wrapper(self: unittest.TestCase, *args: Any, **kwargs: Any) -> Any:
        if not is_available(resource):
            self.skipTest(reason)
        return method(self, *args, **kwargs)

    return wrapper


def _decorate_class(
    case: type[unittest.TestCase], resource: str, reason: str
) -> type[unittest.TestCase]:
    own = case.__dict__.get("setUpClass")

    def set_up_class(cls: type[unittest.TestCase]) -> None:
        if not is_available(resource):
            raise unittest.SkipTest(reason)
        if isinstance(own, classmethod):
            own.__func__(cls)
        else:
            super(case, cls).setUpClass()

    case.setUpClass = classmethod(set_up_class)  # type: ignore[method-assign,assignment]
    return case
