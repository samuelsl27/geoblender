# SPDX-License-Identifier: GPL-3.0-or-later
"""Las superficies de una cubicación (spec 011; RF-011-02; plan 011 §5.3.1, A1, D-24).

- :class:`SurfaceRef`: a qué superficie se refiere una cubicación o una unidad de la columna de
  materiales, sin leerla: un dato (``dataset``, por su nombre: estable al recalcularlo), un dato
  congelado en la revisión de la que parte la versión activa (``frozen``) o una cota constante
  (``elevation``, m, float64). ``label`` es el nombre que ve una persona (no cuenta al
  comparar).

La comprobación de dos superficies, su lectura por bandas y la propuesta de orden (A1, D-31) se
añaden aquí con la lectura de las superficies. Python puro (nivel 9).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = ["SurfaceRef"]


@dataclass(frozen=True, slots=True)
class SurfaceRef:
    """Una superficie, sin leerla: exactamente una de ``dataset`` (el nombre de un dato),
    ``frozen`` (un dato congelado en la revisión de la que parte la versión activa, RF-011-02)
    o ``elevation`` (una cota constante, m, número finito). ``label``, su nombre para una
    persona (no cuenta al comparar dos). Una referencia incoherente es un error del programa
    (:class:`ValueError`)."""

    dataset: str | None = None
    frozen: str | None = None
    elevation: float | None = None
    label: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        given = [name for name in ("dataset", "frozen", "elevation")
                 if getattr(self, name) is not None]
        if len(given) != 1:
            raise ValueError("una superficie es un dato, un dato congelado o una cota "
                             f"constante (una sola), no {given or 'ninguna'}")
        for name in ("dataset", "frozen"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"el {name} de una superficie es un nombre, no {value!r}")
        elevation = self.elevation
        if elevation is not None:
            if isinstance(elevation, bool) or not isinstance(elevation, int | float):
                raise ValueError(f"una cota constante es un número, no {elevation!r}")
            if not math.isfinite(elevation):
                raise ValueError(f"una cota constante es un número finito, no {elevation!r}")
            object.__setattr__(self, "elevation", float(elevation))
        if not isinstance(self.label, str):
            raise ValueError(f"el nombre de una superficie es un texto, no {self.label!r}")

    @property
    def shown(self) -> str:
        """El nombre para una persona: ``label`` o, sin él, el dato o la cota (m)."""
        if self.label:
            return self.label
        if self.elevation is not None:
            return f"{self.elevation!r} m"
        return self.dataset if self.dataset is not None else str(self.frozen)
