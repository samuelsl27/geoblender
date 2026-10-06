# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de ``geoblender.core.gpkg``: geometría GeoPackage, cabecera SQLite, conexión,
estructura del GeoPackage, protección de las tablas internas y vuelta desde WAL (spec 002).

Los GeoPackage de prueba se crean en carpetas temporales (``tests.support.core_fixtures.
project_tmp``), nunca en el repositorio.
"""
