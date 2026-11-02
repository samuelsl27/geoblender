# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas unitarias de ``geoblender.design`` (spec 013): envolventes y escalonado.

Los datos de referencia (el cono, la pared, el plano inclinado, el sector de 10,6°, la corta
circular, los tres sectores, la ladera, el relleno ×40 y el proyecto del diseño) están en
``tests/support/design_fixtures.py``; los oráculos (la fuerza bruta euclídea y el Dijkstra sobre
los desplazamientos del *chamfer*), en ``tests/support/design_oracles.py``.
"""
