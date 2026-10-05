# SPDX-License-Identifier: GPL-3.0-or-later
"""Adaptadores: el único sitio que importa librerías externas, un módulo dueño por
librería (ARQ-04, ARQ-05).

Cada adaptador implementa un puerto (``<paquete>/ports.py``) e importa solo ``core``
y los módulos ``ports`` (ARQ-10). El dominio los recibe por argumento o los
resuelve ``adapters/registry.py`` dentro de una función (ADR-0004).
"""
