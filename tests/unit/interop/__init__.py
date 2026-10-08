# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas unitarias de ``geoblender.interop`` (spec 005): tablas CSV y XLSX,
correspondencia de columnas y RecMin.

Los ficheros en otras codificaciones que leen (Windows-1252, OEM 850, ISO-8859-1, UTF-8
con BOM) se generan en la propia prueba, en la carpeta temporal, desde texto UTF-8: nunca
se versionan (TXT-01 de la 001).
"""
