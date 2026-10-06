# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipos del proyecto ``.gbproj`` (spec 002; plan 002 §5.1 y §5.3).

- :class:`ProjectRecord`: la fila de ``gb_project``, la identidad y la georreferencia del
  proyecto tal como las guarda la base de datos, que es la fuente de verdad (la cabecera
  ``manifest.json`` es una copia legible que se reescribe desde ella).

Coordenadas: la ventana de trabajo y el GeoOrigin son **absolutos** (CRS del proyecto,
m); el GeoOrigin, en metros enteros.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields

from ..georef.origin import GeoOrigin, Window


@dataclass(frozen=True)
class ProjectRecord:
    """La fila de ``gb_project`` (esquema 1; formato-proyecto §3.2).

    ``vcrs_epsg`` es ``None`` en una referencia vertical local, que lleva entonces su
    descripción en ``vcrs_note`` y no lleva ``vcrs_wkt``. Las fechas, en UTC ISO 8601 con
    milisegundos y «Z».
    """

    uid: str
    name: str
    schema_version: int
    min_reader_schema: int
    created_with: str
    last_written_with: str
    crs_epsg: int
    crs_name: str
    crs_wkt: str
    vcrs_epsg: int | None
    vcrs_name: str
    vcrs_wkt: str | None
    vcrs_note: str | None
    origin_x: int
    origin_y: int
    origin_z: int
    grid_step_m: float
    window_xmin: float
    window_ymin: float
    window_xmax: float
    window_ymax: float
    created_at: str
    modified_at: str
    code: str | None = None
    client: str | None = None
    description: str | None = None
    active_version_uid: str | None = None

    @property
    def origin(self) -> GeoOrigin:
        """El GeoOrigin (X0, Y0, Z0) en metros enteros; ``ValidationError`` si la fila
        no tiene un origen válido."""
        return GeoOrigin(self.origin_x, self.origin_y, self.origin_z)

    @property
    def window(self) -> Window:
        """La ventana de trabajo alineada, absoluta (m)."""
        return Window(self.window_xmin, self.window_ymin, self.window_xmax, self.window_ymax)

    @property
    def vertical_is_local(self) -> bool:
        """Verdadero si las cotas van referidas a una referencia local (sin EPSG)."""
        return self.vcrs_epsg is None

    def as_row(self) -> dict[str, object]:
        """Columna → valor, para escribir la fila."""
        return asdict(self)

    @classmethod
    def columns(cls) -> tuple[str, ...]:
        """Las columnas de ``gb_project`` que lleva el registro (todas salvo ``fid``)."""
        return tuple(item.name for item in fields(cls))

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> ProjectRecord:
        """El registro de una fila leída (columna → valor)."""
        return cls(**{name: row[name] for name in cls.columns()})  # type: ignore[arg-type]
