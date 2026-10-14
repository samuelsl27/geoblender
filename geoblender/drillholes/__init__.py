# SPDX-License-Identifier: GPL-3.0-or-later
"""Sondeos (código ``dh``, nivel 3): modelo, almacén, validación, desurvey y
compositado.

Dominio puro: solo importa paquetes de nivel menor (ARQ-07). Importarlo no tiene efectos ni
importa sus módulos; :mod:`.model` (spec 005, T03) da los registros, el ``DrillholeSet``
columnar, la declaración de una fuente y el DTO de una importación; :mod:`.conventions`
(T04), el paso de los convenios de la fuente a los internos (inclinación, azimut de
cuadrícula con la convergencia de las bocas y unidades de las leyes); :mod:`.values` (T05),
los valores de las columnas de texto (vacíos, centinelas, «<x», «>x», negativos y
rechazos) y los Single de RecMin por su decimal más corto; :mod:`.desurvey` (T06 y T07), las
trazas por mínima curvatura, tangente o tangente equilibrada, la posición de cualquier
profundidad y las polilíneas densificadas; :mod:`.validate` (T08 a T10), las comprobaciones
de la tabla 4.4.1 de la spec, lo que excluyen sus errores, la profundidad deducida y la
diferencia de las bocas con el MDT; :mod:`.ports` (T10), el puerto de la cota del MDT
(``SurfaceSampler``); :mod:`.surface` (T10), su implementación con una rejilla de la 006;
:mod:`.report` (T11), el informe de validación en CSV para Excel en español, y
:mod:`.view_data` (T17), los arrays de la vista 3D: curvas de litología, barras de leyes con
su leyenda de clases y etiquetas.
"""
