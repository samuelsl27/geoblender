# SPDX-License-Identifier: GPL-3.0-or-later
"""Puntos de entrada de los trabajos pesados, que se ejecutan en el subproceso del
entorno de cálculo (ADR-0009).

Nunca importan ``bl`` ni escriben en la base de datos del proyecto (ADR-0010).
"""
