# SPDX-License-Identifier: GPL-3.0-or-later
"""Bases de sondeos de RecMin (spec 005, HU-005-2; RF-005-02, RF-005-13, RF-005-15; plan 005
§5.4 «RecMin», §5.6.2 y §5.6.12; ``docs/arquitectura/datos/sondeos.md`` §5).

RecMin solo es una fuente, en solo lectura: nada se escribe hacia RecMin. Sus tablas llegan
crudas (``interop.ports.RawTable``, las que extrae el motor de la base en un proceso aparte,
ADR-0018) y aquí se interpretan, sin motor:

- :mod:`.schema`: las tablas y columnas conocidas de los esquemas 11 y 12, las adicionales de
  litología y de muestras reconocidas por su forma, la lista de las que lee el importador (la
  que hashea el lector de contenido ``io.recmin_mdb@1``) y la versión de esquema
  (``ACTUALIZACION.ULTIMA``).
- :mod:`.drillholes`: de las tablas crudas a un ``drillholes.model.DrillholeSet`` (una tabla
  por papel: bocas, desviaciones, litología, análisis, intersecciones, cortes y catálogos) y
  su ``interop.base.ImportReport``.

Dominio puro: Python y numpy (ARQ-07).
"""
