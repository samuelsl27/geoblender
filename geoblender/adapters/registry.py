# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolución diferida de los adaptadores que el dominio no recibe por argumento (ADR-0004;
plan 006 §5.1; excepción de ARQ-10 del plan 001).

El dominio no importa ``adapters`` salvo este módulo, y solo dentro de una función
(ARQ-07); este módulo importa sus hermanos también solo dentro de funciones (ARQ-10), así
que importar el dominio no carga ninguna librería externa ni sus DLL.

- :func:`crs_service`: el servicio de CRS (``gis.ports.CrsService``) de
  ``adapters.pyproj_crs`` (spec 006: RF-006-05, RF-006-07, RF-006-31). Si no se puede usar,
  lanza ``gis.ports.CrsServiceUnavailable``, que ``gis.crs`` convierte en el error para el
  usuario.
- :func:`crs_library`: la biblioteca del servicio de CRS y su versión fijada (spec 006, T28:
  la procedencia de una operación que transforma, RF-006-26), sin cargar la biblioteca.
- :func:`mdb_extractor`: el extractor de bases de Access (``interop.ports.MdbExtractor``) de
  ``adapters.mdb_reader``, con el motor de Access del equipo en un ``powershell.exe`` aparte
  (spec 005, T16: RF-005-13, RF-005-14; ADR-0018).
"""

from __future__ import annotations

from ..gis.ports import CrsService
from ..interop.ports import MdbExtractor


def crs_service() -> CrsService:
    """El servicio de CRS con pyproj (comprueba su versión antes de cargarlo; se crea una
    vez). Lanza ``gis.ports.CrsServiceUnavailable`` si no se puede usar (RF-006-31)."""
    from . import pyproj_crs

    return pyproj_crs.load_service()


def crs_library() -> tuple[str, str]:
    """La biblioteca del servicio de CRS y la versión que fija Geoblender
    (``tools/wheels.toml``), sin importarla ni comprobar la instalada."""
    from . import pyproj_crs

    return pyproj_crs.PACKAGE, pyproj_crs.PYPROJ_VERSION


def mdb_extractor() -> MdbExtractor:
    """El extractor de bases de Access con los motores por defecto (ACE de 64 bits, después
    los de 32 y Jet 4.0 de Windows). No carga ningún motor en este proceso (ADR-0018)."""
    from . import mdb_reader

    return mdb_reader.OleDbProcessMdbExtractor()
