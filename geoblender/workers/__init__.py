# SPDX-License-Identifier: GPL-3.0-or-later
"""Puntos de entrada de los trabajos pesados, que se ejecutan en el subproceso del
entorno de cálculo (ADR-0009).

Cada tipo de trabajo que corre en proceso aparte tiene aquí su módulo
``workers/<tipo>.py`` con ``main(ctx: WorkerContext) -> resumen JSON``: un envoltorio de la
función de dominio registrada como ``WorkerInfo.run`` (``workers/selftest.py`` →
``jobs.selftest.run``). Los lanza ``workers/_bootstrap.py``, el arranque aislado (plan 004
§5.3.3 y §5.4.3).

Nunca importan ``bl`` ni escriben en la base de datos del proyecto (ADR-0010).
"""
