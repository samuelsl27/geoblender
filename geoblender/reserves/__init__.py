# SPDX-License-Identifier: GPL-3.0-or-later
"""Cubicación y reservas (código ``res``, nivel 9; ADR-0004): con la spec 011, la cubicación
entre superficies; después, balance, sensibilidad, reservas, fases, avance, programación e
informes.

La spec 011 (plan 011 §5.1) cubica entre dos superficies del proyecto por pasos, en una sola
pasada por bandas de filas, con el área real de cada celda y su reparto exacto por dominios,
rodajas y unidades de la columna de materiales; sus cifras salen de dos operaciones de versión
encadenadas (``res.volume`` y ``res.tonnage``). Un módulo pequeño por algoritmo, que se importa
por su nombre (este paquete no importa ninguno):

- ``messages``: los rechazos, avisos y notas ``res.*`` en los dos idiomas (``ResError``);
- ``params``: los parámetros del proyecto (espesor mínimo, umbral de presencia de lo antrópico,
  tolerancia de los momentos) y la comprobación de la altura de banco;
- y, en las tareas siguientes, ``slices``, ``coverage``, ``polygons``, ``kernel``,
  ``materials``, ``tonnage``, ``surfaces``, ``volumes``, ``table``, ``scale``, ``provenance``,
  ``store``, ``reproduce``, ``stages`` y ``export``.

Dominio puro: solo importa paquetes de nivel menor (``core`` y ``gis``; ARQ-07); lo de Blender
está en ``bl/`` (``bl/ops/res.py`` registra lo que declara este paquete).
"""
