# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista regenerable frente a su proyecto (spec 010; RF-010-01 a RF-010-08; ADR-0006;
plan 010 §5.1 y §5.3.1).

La vista de Blender no es fuente de verdad (ADR-0006): se pone al día desde el proyecto sin
escribir nada en él. Este paquete es lo que hay que saber del proyecto para ello, en Python puro
(ADR-0004: solo importa ``core``), y no reexporta nada: sus módulos se importan por su nombre.

- ``state``: el estado de cada dato cargado en la escena frente al proyecto (al día, estado u
  obsoleto que poner al día, no al día, sustituido por un sucesor, sin respaldo en el proyecto o
  que falta), leído en una instantánea, el plan de «Refrescar las vistas desde el proyecto» (F5)
  y lo que cuenta el control 7 (RF-010-01, RF-010-02, RF-010-03).
- ``inventory``: lo registrado en el proyecto, cargado o no, con sus marcas, y su página
  filtrada (RF-010-07).
- ``card``: la ficha de «Elemento activo» de un dato y las cifras de varios datos con sus marcas
  (RF-010-06, RF-010-08).
- ``locate``: cuándo no se ofrece abrir el proyecto de una vista, dónde está y si una carpeta es
  ese proyecto (RF-010-04, RF-010-05).
"""
