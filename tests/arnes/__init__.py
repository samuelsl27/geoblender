# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas del propio arnés que lanzan Blender entero (``blender.exe``).

Las ejecuta el paso «arnés» de ``tools/check.py --completo`` (spec 001 0.6, RF-001-06; D-9
de la spec 002): prueban ``tools/`` y ``tests/support/``, no la extensión. La comprobación
de cada tarea va sin ellas (RNF-001-01, ≤ 45 s) y ``tools/publish.py`` las pide siempre.
"""
