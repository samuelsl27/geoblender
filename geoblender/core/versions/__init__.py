# SPDX-License-Identifier: GPL-3.0-or-later
"""Versiones, revisiones e instantáneas del proyecto (spec 009; R-07; ADR-0013, ADR-0026;
plan 009 §5.1 y §5.3.1).

Una **versión** (V01, V02…) es una alternativa del proyecto con identidad inmutable y un estado
(BORRADOR, VIGENTE, SUPERADO o DESCARTADO) que es un atributo; una **revisión** (V10.r2) es un
momento de una versión: una abierta en cada versión viva y las demás congeladas en su
**instantánea** (``snapshots/V10.r2/``) o cerradas al superarse.

Python puro, sin Blender. El paquete no importa nada: cada módulo se importa por su nombre
(``core.versions.schema``, ``model``, ``read``, ``store``, ``freeze``, ``copy``, ``check``,
``reproduce`` y ``decisions``), para que ``core.provenance`` pueda leer las versiones
(``read``) sin cargar lo que a su vez la usa (ARQ-08).
"""
