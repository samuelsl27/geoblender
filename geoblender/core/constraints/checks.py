# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo incompleto de una restricción (spec 012; RF-012-04; plan 012 §5.1, §5.3.1 y D-23).

:func:`incomplete` lista, de cada restricción **activa** en la versión que se compila (o cuya
«activa» falta: no se sabe si lo está), lo que impide compilar las máscaras, un
:class:`Incomplete` por problema, en este orden:

1. el código: vacío (dibujada en QGIS), mal formado o repetido en las tres capas (D-22) o con el de una
   restricción **declarada por una entidad** (``dec__…``: el de una restricción del proyecto que lo copia o
   lo escribe a mano, y el de la declarada, con un mensaje propio que no manda a «Restricciones…»: una
   declarada no se corrige a mano; spec 015, T45, B-6); sin un código válido no hay claves de parámetros y no
   se miran;
2. el tipo (``None``: ninguno de los once), el motivo y el decisor (vacíos o solo espacios);
3. un límite (legal o perímetro) que no es un polígono (D-23);
4. cada parámetro que pide su tipo, en el orden de ``ConstraintType.requires``: sin valor, con
   un valor que su definición no admite, o un resguardo hacia fuera de 0 m en una línea o un
   punto (no ocuparía ninguna celda).

La geometría no válida (se corta a sí misma, sin área, sin longitud) la mira ``gis``. Los
valores llegan resueltos en la versión (clave → valor, o el ``ResolvedParam`` de
``core.params``; sin la clave, sin valor). Python puro (``core``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..i18n import translate
from ..params import ParamError, ParamValue
from ..params.store import ResolvedParam
from .messages import render
from .model import (
    Constraint,
    ConstraintParam,
    ConstraintType,
    GeometryKind,
    is_code,
    shown_name,
)
from .params import family, param_key

__all__ = ["NO_TYPE_MSGID", "PROBLEMS", "Incomplete", "incomplete"]

NO_TYPE_MSGID = "no type"
"""Lo que se ve como tipo de una restricción sin tipo válido."""

PROBLEMS: tuple[str, ...] = (
    "core.constraint_no_code",
    "core.constraint_code_invalid",
    "core.constraint_code_repeated",
    "core.constraint_code_repeated_declared",
    "core.constraint_no_type",
    "core.constraint_no_reason",
    "core.constraint_no_decider",
    "core.constraint_limit_not_polygon",
    "core.constraint_param_missing",
    "core.constraint_param_invalid",
    "core.constraint_buffer_not_positive",
)
"""Los problemas que puede listar :func:`incomplete` (códigos de :mod:`.messages`)."""

type Resolved = ParamValue | ResolvedParam | None


@dataclass(frozen=True, slots=True)
class Incomplete:
    """Un problema de una restricción (RF-012-04): su código, nombre y tipo, el ``problem``
    (un código de :data:`PROBLEMS`), el campo (``code``, ``ctype``, ``reason``,
    ``decided_by``, ``geometry`` o la clave del parámetro) y el valor; su capa, su fid y su
    geometría."""

    code: str
    name: str
    ctype: ConstraintType | None
    problem: str
    field: str
    value: object
    layer: str
    fid: int
    kind: GeometryKind

    def text(self, language: str = "es") -> str:
        """El problema como lo lee una persona en ``language``, con el nombre y el tipo."""
        values: dict[str, object] = {
            "name": shown_name(self.name, self.code, self.layer, self.fid, language),
            "ctype": (translate(language, NO_TYPE_MSGID) if self.ctype is None
                      else self.ctype.label(language)),
            "value": self.value,
        }
        if self.field == "geometry":
            values["geometry"] = translate(language, GeometryKind(self.value).article_msgid)
        elif self.field.startswith("core.constraint."):
            param = ConstraintParam(self.field.rpartition(".")[2])
            defn = family(param).template
            values.update(key=self.field, param=translate(language, defn.label_msgid),
                          range=defn.range_text(language),
                          geometry=translate(language, GeometryKind(self.kind).article_msgid))
        return render(self.problem, language=language, **values)


def _value(found: Resolved) -> ParamValue | None:
    return found.value if isinstance(found, ResolvedParam) else found


def _blank(text: object) -> bool:
    return not isinstance(text, str) or not text.strip()


def incomplete(constraints: Iterable[Constraint],
               resolved: Mapping[str, Resolved]) -> tuple[Incomplete, ...]:
    """Lo que impide compilar ``constraints`` (RF-012-04), en su orden y, en cada una, en el
    orden del módulo; las desactivadas (``active`` resuelto a ``False``) no se listan.
    ``resolved``: los valores de sus parámetros en la versión, por clave."""
    constraints = tuple(constraints)
    counts = Counter(item.code for item in constraints if is_code(item.code))
    found: list[Incomplete] = []
    for item in constraints:
        found.extend(_problems(item, resolved, counts))
    return tuple(found)


def _problems(item: Constraint, resolved: Mapping[str, Resolved],
              counts: Counter[str]) -> list[Incomplete]:
    def problem(code: str, field: str, value: object) -> Incomplete:
        return Incomplete(item.code, item.name, item.ctype, code, field, value, item.layer,
                          item.fid, item.kind)

    keyed = is_code(item.code)
    if keyed and _value(resolved.get(param_key(item.code, ConstraintParam.ACTIVE))) is False:
        return []
    found: list[Incomplete] = []
    if not item.code:
        found.append(problem("core.constraint_no_code", "code", item.code))
    elif not keyed:
        found.append(problem("core.constraint_code_invalid", "code", item.code))
    elif counts[item.code] > 1:
        found.append(problem("core.constraint_code_repeated_declared" if item.declared
                             else "core.constraint_code_repeated", "code", item.code))
    if item.ctype is None:
        found.append(problem("core.constraint_no_type", "ctype", None))
    if _blank(item.reason):
        found.append(problem("core.constraint_no_reason", "reason", item.reason))
    if _blank(item.decided_by):
        found.append(problem("core.constraint_no_decider", "decided_by", item.decided_by))
    if item.ctype is not None and not item.ctype.accepts(item.kind):
        found.append(problem("core.constraint_limit_not_polygon", "geometry", item.kind.value))
    if keyed:
        params = item.ctype.requires if item.ctype is not None else (ConstraintParam.ACTIVE,)
        for param in params:
            key = param_key(item.code, param)
            value = _value(resolved.get(key))
            if value is None:
                found.append(problem("core.constraint_param_missing", key, None))
                continue
            try:
                value = family(param).template.check(value)
            except ParamError:
                found.append(problem("core.constraint_param_invalid", key, value))
                continue
            if (param is ConstraintParam.BUFFER_OUT and item.kind is not GeometryKind.POLYGON
                    and value <= 0.0):
                found.append(problem("core.constraint_buffer_not_positive", key, value))
    return found
