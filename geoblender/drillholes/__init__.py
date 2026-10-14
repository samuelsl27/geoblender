# SPDX-License-Identifier: GPL-3.0-or-later
"""Sondeos (código ``dh``, nivel 3): modelo, almacén, validación, desurvey y
compositado.

Dominio puro: solo importa paquetes de nivel menor (ARQ-07). Importarlo no tiene efectos ni
importa sus módulos; :mod:`.model` (spec 005, T03) da los registros, el ``DrillholeSet``
columnar, la declaración de una fuente y el DTO de una importación; :mod:`.conventions`
(T04), el paso de los convenios de la fuente a los internos (inclinación, azimut de
cuadrícula con la convergencia de las bocas y unidades de las leyes); :mod:`.values` (T05),
los valores de las columnas de texto (vacíos, centinelas, «<x», «>x», negativos y
rechazos) y los Single de RecMin por su decimal más corto, y :mod:`.desurvey` (T06), las
trazas por mínima curvatura, tangente o tangente equilibrada.
"""
