# SPDX-License-Identifier: GPL-3.0-or-later
"""Preferencias de los trabajos en segundo plano (spec 004; RF-004-04, RF-004-17,
RF-004-24, RF-004-26; plan 004 §5.2.7).

:class:`GEOBLENDER_PG_jobs_preferences` es el grupo ``jobs`` de la **única**
``GeoblenderPreferences`` (``bl/props/preferences.py``, PLT-02); esta spec no crea otra
clase de preferencias:

- ``max_parallel_jobs``: trabajos en curso a la vez en proceso aparte, de 1 a 4 y 2 por
  defecto (DP-32; el máximo de ``jobs.runner.JobRunner``, que lo recibe al crearse y, al
  cambiarlo, con ``reconfigure``: ``bl.ops.jobs.on_max_parallel_changed``); los demás
  esperan «En cola» (RF-004-04);
- ``retention_days``: días que se conservan las carpetas de los trabajos terminados, de 1
  a 90 y 7 por defecto (DP-33; ``jobs.cleanup.purge`` al abrir un proyecto, RF-004-17);
- ``runtime_source``: de dónde se instala el motor de cálculo (``AUTO``: el almacén de
  ruedas si hay uno configurado y, si no, PyPI; ``WHEELHOUSE``; ``PYPI``), y
  ``wheelhouse_dir``: la carpeta del almacén de ruedas, local o del NAS (RF-004-24);
- ``use_external_python`` y ``external_python``: el intérprete externo de Python 3.13 con
  numpy para los trabajos del motor de cálculo (RF-004-26). La ruta solo la guarda,
  después de comprobarla, ``geoblender.jobs_set_external_python`` (T33): el panel de
  preferencias la muestra sin dejar editarla.

Ninguna ruta por defecto escrita en el código (ARQ-15): las dos empiezan vacías (sin
almacén, sin intérprete externo). Nada es animable (``options=set()``).
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

# Trabajos a la vez en proceso aparte (DP-32): el mismo valor por defecto que
# jobs.runner.DEFAULT_MAX_SUBPROCESS (lo comprueba tests/blender/test_jobs.py).
MAX_PARALLEL_DEFAULT = 2
MAX_PARALLEL_MIN = 1
MAX_PARALLEL_MAX = 4
# Días que se conservan los trabajos terminados (DP-33).
RETENTION_DEFAULT = 7
RETENTION_MIN = 1
RETENTION_MAX = 90
# Origen del motor de cálculo (el mismo enumerado que jobs_setup_runtime, plan §5.3).
RUNTIME_SOURCE_DEFAULT = "AUTO"
RUNTIME_SOURCE_ITEMS = [
    ("AUTO", "Automatic", "The wheel store if one is configured; otherwise PyPI"),
    ("WHEELHOUSE", "Wheel store", "Only the wheel store folder, without internet"),
    ("PYPI", "PyPI", "Download from PyPI (needs online access)"),
]
_STATIC: set[str] = set()  # ni animable ni nada más


def _max_parallel_changed(group: GEOBLENDER_PG_jobs_preferences, context: object) -> None:
    """El nuevo máximo llega al momento al lanzador de la sesión (RF-004-04)."""
    from ..ops import jobs  # diferido: bl/ops importa bl/props

    jobs.on_max_parallel_changed(group.max_parallel_jobs)


class GEOBLENDER_PG_jobs_preferences(bpy.types.PropertyGroup):
    """Preferencias de los trabajos en segundo plano y del motor de cálculo (spec 004)."""

    max_parallel_jobs: IntProperty(  # type: ignore[valid-type]
        name="Jobs at once (separate process)",
        description=(
            "Maximum number of jobs running at the same time in a separate process; "
            "the others wait in the queue"
        ),
        default=MAX_PARALLEL_DEFAULT,
        min=MAX_PARALLEL_MIN,
        max=MAX_PARALLEL_MAX,
        options=_STATIC,
        update=_max_parallel_changed,
    )
    retention_days: IntProperty(  # type: ignore[valid-type]
        name="Keep finished jobs (days)",
        description=(
            "Days after which the folders of finished jobs are deleted when a project "
            "is opened"
        ),
        default=RETENTION_DEFAULT,
        min=RETENTION_MIN,
        max=RETENTION_MAX,
        options=_STATIC,
    )
    runtime_source: EnumProperty(  # type: ignore[valid-type]
        name="Compute engine source",
        description="Where the compute engine is installed from",
        items=RUNTIME_SOURCE_ITEMS,
        default=RUNTIME_SOURCE_DEFAULT,
        options=_STATIC,
    )
    wheelhouse_dir: StringProperty(  # type: ignore[valid-type]
        name="Wheel store folder",
        description="Local or NAS folder with the wheels of the compute engine (empty: none)",
        default="",
        subtype="DIR_PATH",
        options=_STATIC,
    )
    use_external_python: BoolProperty(  # type: ignore[valid-type]
        name="Use an external interpreter",
        description=(
            "Run the jobs that need the compute engine with the external interpreter "
            "(development)"
        ),
        default=False,
        options=_STATIC,
    )
    external_python: StringProperty(  # type: ignore[valid-type]
        name="External interpreter",
        description=(
            "Python 3.13 interpreter with numpy, checked when it is set (empty: none)"
        ),
        default="",
        subtype="FILE_PATH",
        options=_STATIC,
    )


# En orden de registro (el grupo, antes de GeoblenderPreferences, que lo usa).
classes: tuple[type, ...] = (GEOBLENDER_PG_jobs_preferences,)
