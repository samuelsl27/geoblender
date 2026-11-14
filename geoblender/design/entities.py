# SPDX-License-Identifier: GPL-3.0-or-later
"""Las entidades de diseño (spec 015, T02; HU-015-1; RF-015-01; plan 015 §5.1 y §5.3.1; ADR-0030).

Una entidad es una operación de versión con su nombre y un **código inmutable por versión**
(``PLT-001``) cuyos parámetros son la familia ``des.platform.{e}.*`` (:mod:`design.params`):
sin fila no hay entidad; con fila y sin operación, está «sin calcular». Su estado se **deduce** del
grafo (ADR-0025 §5), no se apunta. Python puro, sin leer el proyecto (la lectura es de la T03).

- :class:`EntityKind`: el tipo (en esta spec, la plataforma; la 016 añade los suyos) y su prefijo
  de código.
- :class:`EntityState`: el estado de una entidad (RF-015-25): sin calcular, al día, obsoleta,
  descartada o «apoyo retirado».
- :class:`EntityRecord`: lo que el dominio sabe de una entidad: su código, su nombre, su tipo, su
  superficie de partida y la de apoyo (si la hay) y su estado.
- :func:`format_code` y :func:`next_code`: el código ``PLT-nnn``, correlativo y nunca reutilizado.
- :func:`declared_reason`: el motivo generado de la restricción que declara una entidad
  (RF-015-10: «declarada por la plataforma P1»).

``design.entities`` es un módulo pesado de la 015: lo importan el almacén y las órdenes al usarlo, no
``bl`` al registrarse ni ``design.provenance`` (``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from .messages import DesignError, render
from .params import entity_segment

__all__ = [
    "EntityKind",
    "EntityRecord",
    "EntityState",
    "declared_reason",
    "format_code",
    "next_code",
]


class EntityKind(StrEnum):
    """El tipo de una entidad (RF-015-01): en esta spec, la plataforma; el acopio, el contrafuerte
    y el cuerpo apoyado son de la 016. El valor es el que va en la clave de sus parámetros
    (``des.platform.{e}.*``); :attr:`prefix`, el principio de su código (``PLT``)."""

    PLATFORM = "platform"

    @property
    def prefix(self) -> str:
        """El principio del código de una entidad de este tipo: ``PLT`` de ``PLT-001``."""
        return _PREFIXES[self]


_PREFIXES: dict[EntityKind, str] = {EntityKind.PLATFORM: "PLT"}
_REASONS: dict[EntityKind, str] = {EntityKind.PLATFORM: "des.platform_declared_reason"}
_CODE = re.compile(r"(?P<prefix>[A-Z]{2,5})-(?P<number>[0-9]{3,})")


class EntityState(StrEnum):
    """El estado de una entidad (RF-015-25; plan 015 §5.2.3), deducido y no apuntado (ADR-0025 §5):
    ``UNCALCULATED`` (sus parámetros sin operación vigente: lo que deja «Traer las entidades de…»),
    ``CURRENT`` (al día), ``STALE`` (obsoleta: el grafo, con su causa), ``DISCARDED`` (sus datos
    descartados, «registro, no usar»: nada se borra, RF-009-12) y ``SUPPORT_REMOVED`` («apoyo
    retirado»: una entrada suya está descartada, RF-015-17)."""

    UNCALCULATED = "uncalculated"
    CURRENT = "current"
    STALE = "stale"
    DISCARDED = "discarded"
    SUPPORT_REMOVED = "support_removed"


def format_code(kind: EntityKind | str, number: int) -> str:
    """El código de la entidad número ``number`` de su tipo: ``PLT-001``, con al menos tres cifras
    (``PLT-1000`` pasa de 999). :class:`TypeError` si ``number`` no es un entero y
    :class:`ValueError` si es menor que 1 o ``kind`` no es un tipo (errores del programa)."""
    prefix = EntityKind(kind).prefix
    if isinstance(number, bool) or not isinstance(number, int):
        raise TypeError(f"el número de una entidad es un entero, no {number!r}")
    if number < 1:
        raise ValueError(f"el número de una entidad es 1 o más, no {number}")
    return f"{prefix}-{number:03d}"


def next_code(kind: EntityKind | str, existing: Iterable[str]) -> str:
    """El código que corresponde a la siguiente entidad de tipo ``kind`` en una versión cuyas
    entidades tienen ya los códigos ``existing`` (todas, también las descartadas, que siguen en la
    versión): el mayor número de ese tipo más uno (``PLT-001`` si no hay ninguno). Es correlativo
    por versión y **nunca reutiliza** uno (el código es inmutable, ADR-0030: lo citan las
    restricciones declaradas, las dependencias y el informe); si falta alguno por el camino, el
    hueco se queda. Los códigos de otro tipo cuentan aparte (cada tipo, su prefijo y su cuenta).

    No lee el proyecto: ``existing`` son los códigos que le da el registro de la versión (T03).
    :class:`TypeError` si uno no es un texto y :class:`ValueError` si uno no es un código de
    entidad (``PLT-001``): errores del programa."""
    prefix = EntityKind(kind).prefix
    highest = 0
    for code in existing:
        if not isinstance(code, str):
            raise TypeError(f"el código de una entidad es un texto, no {code!r}")
        found = _CODE.fullmatch(code)
        if found is None:
            raise ValueError(f"el código {code!r} no es de una entidad (PLT-001: letras "
                             "mayúsculas, un guion y al menos tres cifras)")
        if found["prefix"] == prefix:
            highest = max(highest, int(found["number"]))
    return format_code(kind, highest + 1)


def _text_or_none(value: object, what: str) -> str | None:
    """``value`` sin los espacios de los extremos (``None`` si es ``None`` o está en blanco);
    :class:`TypeError` si no es un texto."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    return value.strip() or None


@dataclass(frozen=True, slots=True)
class EntityRecord:
    """Lo que el dominio sabe de una entidad de una versión (RF-015-01, RF-015-04): su ``code``
    inmutable (``PLT-001``, el de su ``kind``), su ``name`` (único en la versión), su tipo, la
    superficie de la que parte (``start``) y la de apoyo (``support``), si la hay, ambas sin valor
    hasta que se eligen, y su ``state``, deducido del grafo («sin calcular» por defecto).

    Una entidad sin nombre se rechaza (``DesignError`` ``des.entity_name_missing``); un código que
    no es de su tipo es un error del programa (:class:`ValueError`)."""

    code: str
    name: str
    kind: EntityKind | str
    start: str | None = None
    support: str | None = None
    state: EntityState | str = EntityState.UNCALCULATED

    def __post_init__(self) -> None:
        kind = EntityKind(self.kind)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "state", EntityState(self.state))
        if not isinstance(self.code, str):
            raise TypeError(f"el código de una entidad es un texto, no {self.code!r}")
        found = _CODE.fullmatch(self.code)
        if found is None or found["prefix"] != kind.prefix:
            raise ValueError(f"el código {self.code!r} no es el de una entidad de tipo "
                             f"{kind.value} ({kind.prefix}-001)")
        if not isinstance(self.name, str):
            raise TypeError(f"el nombre de una entidad es un texto, no {self.name!r}")
        name = self.name.strip()
        if not name:
            raise DesignError("des.entity_name_missing", obj=f"Entidad «{self.code}»",
                              field="name", value=self.name)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "start", _text_or_none(self.start, "la superficie de partida"))
        object.__setattr__(self, "support", _text_or_none(self.support, "la superficie de apoyo"))

    @property
    def segment(self) -> str:
        """El código como segmento de la clave de sus parámetros: ``plt_001`` de ``PLT-001``."""
        return entity_segment(self.code)


def declared_reason(kind: EntityKind | str, name: str, *, language: str = "es") -> str:
    """El motivo generado de la restricción que declara la entidad de tipo ``kind`` y nombre
    ``name`` (RF-015-10; D-4): «declarada por la plataforma P1», en español o, con
    ``language="en"``, en inglés. La persona lo puede editar en la entidad (el parámetro
    ``reason``); sin edición, es éste. :class:`TypeError` si ``name`` no es un texto y
    :class:`ValueError` si está en blanco (la entidad que declara ya tiene nombre, RF-015-01) o
    ``language`` no es de Geoblender: errores del programa."""
    if not isinstance(name, str):
        raise TypeError(f"el nombre de una entidad es un texto, no {name!r}")
    shown = name.strip()
    if not shown:
        raise ValueError("una entidad sin nombre no declara nada (RF-015-01)")
    return render(_REASONS[EntityKind(kind)], language=language, name=shown)
