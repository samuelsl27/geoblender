# SPDX-License-Identifier: GPL-3.0-or-later
"""Un proyecto en disco con la demostración de la procedencia, para las pruebas (spec 008, T40;
plan 008 §7 y §7.1).

:class:`DemoProjectTestCase` es la base de las pruebas que recorren la cadena de la demostración
(``tests.support.provenance_demo``) sobre un proyecto real del esquema 2 en disco, como lo
usará Geoblender: las del módulo de demostración, las regresiones de Silvestre de la 008 y el
caso de referencia de la procedencia (``tests/referencia/core``). Cada prueba crea, en una
carpeta temporal de ruta corta que se borra al terminar:

- ``proyectos/<Nombre>.gbproj``: un proyecto nuevo (ajustes y sesión sintéticos de
  ``tests.support.core_fixtures``) con un reloj simulado (:class:`FakeClock`), que
  :meth:`DemoProjectTestCase.run_step` adelanta un minuto tras cada paso;
- ``fuentes/``: la carpeta del cliente, fuera del proyecto, con ``Limites_v1.gpkg`` copiado de
  ``tests/data/core/provenance/`` (:attr:`DemoProjectTestCase.source`); :meth:`deliver` pone otro
  fichero de esos datos en su lugar (el cliente entrega otra versión con el mismo nombre);
- ``u/``: los datos de usuario de la sesión.

:meth:`DemoProjectTestCase.chain` recorre la cadena entera de la demostración (T41) y
:meth:`DemoProjectTestCase.obsolete` dice qué deja obsoleto la caché del proyecto.

La demostración se registra antes de crear el proyecto y se quita al terminar, y la prueba
comprueba entonces que el proceso queda como estaba (:func:`process_state`).

Solo fuera de Blender: importa ``tests.support.core_fixtures`` y los datos de prueba, que
dentro de Blender cargarían otra copia de Geoblender. Datos solo sintéticos: nada de clientes.
"""

from __future__ import annotations

import math
import shutil
import sqlite3
import sys
import unittest
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.support import provenance_data as data
from tests.support import provenance_demo as demo_support
from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.package import PACKAGE_NAME, import_geoblender
from tests.support.provenance_contract import snapshot

create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
userdata_mod = import_geoblender("core.userdata")
params = import_geoblender("core.params")
readers = import_geoblender("core.content.readers")
i18n = import_geoblender("core.i18n")
figures = import_geoblender("core.provenance.figures")
recompute = import_geoblender("core.provenance.recompute")

SESSION = make_session()
"""La sesión sintética de las pruebas (equipo «PC-PRUEBA-A», usuario «prueba»)."""
REL_TOL = 1e-9
"""La tolerancia relativa de las cifras de referencia de la demostración (plan 008 §7)."""


@dataclass(frozen=True)
class Chain:
    """Las operaciones de la cadena entera de la demostración (:meth:`DemoProjectTestCase.chain`):
    la importación del límite (su ``LayerImport``) y las demás (su ``OperationHandle``)."""

    boundary: Any
    area: Any
    digitize: Any
    years: Any
    detect: Any
    filter: Any
    balance: Any

    @property
    def operations(self) -> tuple[Any, ...]:
        """Las operaciones de la demostración, en su orden (sin la importación)."""
        return (self.area, self.digitize, self.years, self.detect, self.filter, self.balance)


def process_state() -> tuple[Any, ...]:
    """Lo que la demostración puede tocar del proceso: los cuatro registros de la procedencia,
    las definiciones de parámetros, los lectores, la lista de códigos de módulo que ve cada
    módulo de Geoblender y las traducciones instaladas."""
    prefix = f"{PACKAGE_NAME}."
    codes = {name: module.MODULE_CODES for name, module in sorted(sys.modules.items())
             if name.startswith(prefix) and hasattr(module, "MODULE_CODES")}
    return (snapshot(), dict(params.DEFINITIONS), dict(readers.READERS), codes,
            dict(i18n._STATE.installed))


class DemoProjectTestCase(unittest.TestCase):
    """Un proyecto nuevo por prueba con la demostración registrada y la fuente
    ``fuentes/Limites_v1.gpkg``, junto a él (véase el módulo)."""

    tmp_prefix = "gb-dp-"
    """El prefijo de la carpeta temporal de cada prueba (corto: rutas de Windows)."""

    def setUp(self) -> None:
        before = process_state()
        self.addCleanup(lambda: self.assertEqual(process_state(), before))
        self.demo = demo_support.Demo()
        self.enterContext(self.demo.registered())
        self.tmp = self.enterContext(project_tmp(self.tmp_prefix))
        parent = self.tmp / "proyectos"
        parent.mkdir()
        self.sources = self.tmp / "fuentes"
        self.sources.mkdir()
        self.source = self.deliver(data.BOUNDARY_V1)
        self.clock = FakeClock()
        self.userdata = userdata_mod.UserData(self.tmp / "u")
        self.project = create.create_project(parent, make_settings(), SESSION, self.userdata,
                                             clock=self.clock).project
        self.addCleanup(self._close)

    def _close(self) -> None:
        self.project.close()

    # --- Fuentes ----------------------------------------------------------------------------

    def deliver(self, name: str, target: str = data.BOUNDARY_V1) -> Path:
        """Pone en ``fuentes/<target>`` una copia de ``name`` de ``tests/data/core/provenance/``
        (con fecha de ahora) y devuelve su ruta."""
        path = self.sources / target
        shutil.copyfile(data.DATA_DIR / name, path)
        return path

    # --- Proyecto ---------------------------------------------------------------------------

    def run_step(self, work: Callable[[], Any]) -> Any:
        """Un paso de la demostración y un minuto más en el reloj."""
        result = work()
        self.clock.advance(minutes=1)
        return result

    def read(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        """``work`` con una conexión de lectura del proyecto."""
        with self.project.read() as conn:
            return work(conn)

    def reopen(self) -> Any:
        """Cierra el proyecto (si no lo está) y lo vuelve a abrir en escritura con la misma
        sesión y el mismo reloj; devuelve el proyecto abierto."""
        self.project.close()
        self.project = open_mod.open_project(self.project.root, SESSION, self.userdata,
                                             clock=self.clock).project
        return self.project

    def chain(self) -> Chain:
        """La cadena entera de la demostración, un paso por minuto: ``fuentes/Limites_v1.gpkg``
        importado y su área, los bancos y las marcas, los años por banco, los dos acopios
        acoplados y el balance (:class:`Chain`)."""
        boundary = self.run_step(lambda: self.demo.import_boundary(self.project, self.source))
        area = self.run_step(lambda: self.demo.area(self.project, boundary.dataset.name))
        digitize = self.run_step(lambda: self.demo.digitize(self.project))
        years = self.run_step(lambda: self.demo.bench_years(self.project))
        detect, kept = self.run_step(lambda: self.demo.stockpiles(self.project))
        balance = self.run_step(lambda: self.demo.balance(self.project))
        return Chain(boundary, area, digitize, years, detect, kept, balance)

    def obsolete(self) -> set[tuple[str, str]]:
        """Lo obsoleto según la caché del proyecto (``gb_stale``), sin la historia (las
        operaciones sustituidas, que la caché también guarda): la clase y el uid de cada
        operación vigente y cada dato vivo con alguna causa."""
        return self.read(lambda conn: {(item_kind, uid) for item_kind, uid in conn.execute(
            "SELECT DISTINCT s.item_kind, s.item_uid FROM gb_stale AS s "
            "LEFT JOIN gb_operation AS o ON s.item_kind = 'operation' AND o.uid = s.item_uid "
            "WHERE s.item_kind <> 'operation' OR o.superseded_by IS NULL")})

    # --- Cifras -----------------------------------------------------------------------------

    def figures_of(self, operation_uid: str) -> list[Any]:
        """Las cifras que registró la operación (``FigureRecord``), en su orden."""
        found, _warnings = self.demo.figures(self.project, operation_uid)
        self.assertTrue(all(isinstance(figure, figures.FigureRecord) for figure in found))
        return found

    def years(self, operation_uid: str) -> dict[str, float]:
        """Los años por banco que registró la operación, por banco."""
        return {figure.scope["bench"]: figure.value for figure in self.figures_of(operation_uid)}

    def recompute_all(self) -> Any:
        """«Recalcular lo obsoleto» de todo el proyecto hasta el final; su resultado."""
        progress = list(recompute.recompute_steps(self.project))
        outcome = progress[-1].result
        self.assertIsInstance(outcome, recompute.RecomputeOutcome)
        self.clock.advance(minutes=1)
        return outcome

    def assertClose(self, value: float, expected: float) -> None:  # noqa: N802 - unittest
        """``value`` es ``expected`` dentro de la tolerancia relativa :data:`REL_TOL`."""
        self.assertTrue(math.isclose(value, expected, rel_tol=REL_TOL),
                        f"{value!r} no es {expected!r} (tolerancia relativa {REL_TOL})")
