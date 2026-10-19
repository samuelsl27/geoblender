# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de las versiones, las revisiones y las instantáneas (spec 009, T28; RNF-009-01,
RNF-009-02, RNF-009-03, RNF-009-04 y RNF-009-06; plan 009 §2.2 y §7.3, ``tests/rendimiento/core``).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender (su numpy 2.3.4) en el PC
de referencia de la spec 008 §5, en disco local (``%TEMP%``). Cada prueba imprime su cifra en
una línea ``RNF-009-nn: …`` con el intérprete y el espacio libre del disco en que escribe (trampa
§6: un ``fsync`` lento con el disco casi lleno), que ``tools/check.py`` recoge, y la compara con
su presupuesto, sin relajarlo. Datos sintéticos, generados aquí y borrados al terminar
(``tests/support/versions_perf.py``).

- RNF-009-01 (:class:`StateChangeTest`): en el proyecto de D-13 de la 008 con seis versiones
  (diez operaciones cada una sobre las cadenas de D-13, su r1 congelada y su r2 abierta), declarar
  VIGENTE una versión con otra VIGENTE (la anterior pasa a SUPERADO y su revisión abierta se
  cierra): la transacción y la cabecera, mediana de 5, ≤ 0,1 s; la lista de ficheros con sus
  huellas, igual salvo la base, su diario y la cabecera.
- RNF-009-02 (:class:`FreezeTest`): congelar en V01 1 GB sintético (diez rejillas de 4 096 ×
  4 096 celdas Float64 con el terreno de ``gis_perf``, la malla de 1,5 M vértices y la tabla de
  250 000 filas) de disco local a disco local con ``freeze_steps``, llevado como el temporizador
  de su orden: ≤ 30 s, ningún hueco del avance de más de 1 s; Esc con el avance a la mitad: nada
  queda (ni la carpeta temporal, ni el GeoPackage de la caché) y la revisión sigue abierta, en
  ≤ 2 s (la llamada más larga más cerrar los pasos).
- RNF-009-03 (:class:`SnapshotCheckTest`): 200 revisiones congeladas de verdad (20 versiones ×
  10), el paso «instantáneas» de la comprobación de apertura (``quick_steps``), mediana de 5 tras
  una primera vuelta: ≤ 0,5 s, y su paso más largo (mediana de 5) ≤ 20 ms, sin ninguna alterada.
- RNF-009-06 (:class:`GrowthTest`): congelar sin cambios una revisión de 1 000 y una de 2 000
  elementos (operaciones, sus tablas, sus cifras y los parámetros que leen; todo ya copiado en la
  anterior): el proyecto sin ``cache/`` crece ≤ lo copiado + 1 MB.

En la red (:class:`NetworkTest`; recurso «red»: la carpeta de pruebas de
``GEOBLENDER_NET_TEST_DIR``, nunca la de los expedientes ni la del espejo; sin ella, se omiten),
cada una en una subcarpeta temporal que se borra: RNF-009-01 con el proyecto de D-13 en la red
(≤ 1 s) y RNF-009-04, las 200 revisiones copiadas a la red (≤ 5 s). RNF-009-05 (5 GB en ``Z:``)
es la T29, a mano, con el arnés de :class:`FreezeTest`.
"""

from __future__ import annotations

import shutil
import statistics
import unittest
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from tests.support import network
from tests.support import provenance_fixtures as d13
from tests.support import versions_fixtures as fixtures
from tests.support import versions_perf as perf
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.resources import requires

freeze = import_geoblender("core.versions.freeze")
vcheck = import_geoblender("core.versions.check")
vread = import_geoblender("core.versions.read")

STATE_BUDGET_S = 0.1  # RNF-009-01, en disco local
NET_STATE_BUDGET_S = 1.0  # RNF-009-01, en Z:
FREEZE_BUDGET_S = 30.0  # RNF-009-02
PROGRESS_GAP_S = 1.0  # RNF-009-02: progreso cada ≤ 1 s
CANCEL_BUDGET_S = 2.0  # RNF-009-02: cancelación efectiva en ≤ 2 s
CHECK_BUDGET_S = 0.5  # RNF-009-03, en disco local
NET_CHECK_BUDGET_S = 5.0  # RNF-009-04, en Z:
CHECK_STEP_BUDGET_S = 0.020  # plan §7.3: cada paso de la comprobación de apertura (RNF-008-12)
GROWTH_MARGIN_BYTES = 1_000_000  # RNF-009-06: lo copiado + 1 MB
GROWTH_ELEMENTS = (1_000, 2_000)  # plan §7.3 y D-39
RUNS = 5  # medianas de 5


def _seconds(value: float, digits: int = 3) -> str:
    return perf.number(value, digits)


def _ms(value: float) -> str:
    return perf.number(value * 1000, 1)


# --- RNF-009-01 -------------------------------------------------------------------------------


def _state_changes(test: unittest.TestCase, built: Any, codes: list[str], where: str,
                   budget: float, *, hashes: bool = True) -> None:
    """Declara VIGENTE, una tras otra, las versiones ``codes[1:]`` (``codes[0]`` ya lo es) del
    proyecto de D-13 ``built`` y comprueba la mediana contra ``budget``."""
    project = built.project
    root = built.root
    listing = perf.listing(root, hashes=hashes)
    totals: list[float] = []
    writes: list[float] = []
    closed: list[str] = []
    for code in codes[1:]:
        found = built.declare(code)
        totals.append(found.total_s)
        writes.append(found.write_s)
        closed.extend(found.closed)
        test.assertEqual(found.change.superseded.status, "SUPERADO")
    test.assertEqual(perf.listing(root, hashes=hashes), listing)
    test.assertEqual(len(closed), len(codes) - 1)
    with project.read() as conn:
        statuses = [vread.version(conn, code).status for code in codes]
    test.assertEqual(statuses, ["SUPERADO"] * (len(codes) - 1) + ["VIGENTE"])
    median = statistics.median(totals)
    perf.report(
        f"RNF-009-01: declarar VIGENTE una versión con otra VIGENTE (que pasa a SUPERADO y "
        f"cierra su revisión abierta) en el proyecto de D-13 {where} ({perf.count(d13.OPERATIONS)} "
        f"operaciones, {perf.count(d13.DATASETS)} datos y {len(codes)} versiones de "
        f"{built.version_operations} operaciones), {len(totals)} veces: transacción y cabecera, "
        f"mediana {_seconds(median)} s (máximo {_seconds(max(totals))} s; la transacción, "
        f"mediana {_seconds(statistics.median(writes))} s); {perf.count(len(listing))} ficheros "
        f"y carpetas "
        f"iguales{' con sus huellas' if hashes else ' (tamaño y fecha)'} (presupuesto "
        f"{_seconds(budget, 1)} s; {perf.free_space(root)})"
    )
    test.assertLessEqual(median, budget)


class StateChangeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.stack = ExitStack()
        try:
            tmp = cls.stack.enter_context(project_tmp("gb-009-st-"))
            cls.stack.enter_context(perf.versions_registered())
            cls.built = perf.build_d13_versions(tmp / "proyectos", tmp / "fuentes")
            cls.stack.callback(cls.built.close)
        except BaseException:
            cls.stack.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stack.close()
        super().tearDownClass()

    def test_declare_current_in_the_d13_project(self) -> None:
        """RNF-009-01: en el proyecto de D-13 en disco local, declarar VIGENTE una versión con
        otra VIGENTE (la anterior pasa a SUPERADO y su revisión abierta se cierra) tarda ≤ 0,1 s
        (mediana de 5, con la cabecera) y no crea, cambia ni borra ningún fichero salvo la base,
        su diario y la cabecera."""
        _state_changes(self, self.built, self.built.codes, "en disco local", STATE_BUDGET_S)


# --- RNF-009-02 -------------------------------------------------------------------------------


class FreezeTest(unittest.TestCase):
    """El GB de §2.2 en V01 del proyecto de la demostración de versiones, en disco local."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.stack = ExitStack()
        try:
            tmp = cls.stack.enter_context(project_tmp("gb-009-fz-"))
            cls.made = cls.stack.enter_context(perf.big_project(tmp, perf.GIGABYTE))
        except BaseException:
            cls.stack.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stack.close()
        super().tearDownClass()

    def test_freeze_a_gigabyte(self) -> None:
        """RNF-009-02: congelar en V01 una revisión que copia 1 GB sintético (diez rejillas,
        la malla y la tabla) de disco local a disco local, con los pasos de su orden, tarda
        ≤ 30 s con un avance cada ≤ 1 s; Esc con el avance a la mitad no deja nada (ni la
        carpeta temporal ni el GeoPackage de la caché; la revisión sigue abierta) en ≤ 2 s."""
        made = self.made
        project = made.project
        plan = freeze.freeze_plan(project, "V01")
        self.assertGreaterEqual(plan.bytes_to_copy, perf.GIGABYTE.min_bytes)
        accepted = freeze.Acceptance.of(plan)
        before = perf.listing(made.root, hashes=False, skip_dirs=("cache",))
        stopped = perf.drive(lambda: freeze.freeze_steps(project, "V01", reason="Entrega",
                                                         accepted=accepted), cancel_at=0.5)
        self.assertIsNotNone(stopped.cancelled_s, "la congelación terminó antes de la mitad")
        self.assertEqual(perf.listing(made.root, hashes=False, skip_dirs=("cache",)), before)
        self.assertEqual(perf.cache_leftovers(project), [])
        with project.read() as conn:
            self.assertEqual(vread.open_revision(conn, made.version_uid).number, 1)
        cancel = stopped.longest_s + stopped.cancelled_s
        made.clock.advance(minutes=1)
        found = perf.drive(lambda: freeze.freeze_steps(project, "V01", reason="Entrega",
                                                       accepted=accepted))
        outcome = found.result
        self.assertIsNotNone(outcome.frozen)
        self.assertGreaterEqual(outcome.copied_bytes, perf.GIGABYTE.min_bytes)
        phases = ", ".join(f"{phase} {_seconds(seconds, 2)} s"
                           for phase, seconds in found.phases.items())
        perf.report(
            f"RNF-009-02: congelar {outcome.label} con {perf.GIGABYTE.label} "
            f"({perf.number(outcome.copied_bytes / 1e9, 3)} GB copiados en "
            f"{len(outcome.files)} ficheros) de disco local a disco local: "
            f"{_seconds(found.total_s, 2)} s en {found.steps} llamadas ({phases}), la más larga "
            f"{_ms(found.longest_s)} ms ({found.longest_phase}), el mayor hueco del avance "
            f"{_ms(found.gap_s)} ms; Esc con "
            f"el avance al {stopped.cancelled_at * 100:.0f} % (a los "
            f"{_seconds(stopped.total_s, 1)} s): cerrar los pasos {_ms(stopped.cancelled_s)} ms, "
            f"con la llamada más larga {_ms(cancel)} ms, sin nada en snapshots/ ni en la caché "
            f"(presupuestos {_seconds(FREEZE_BUDGET_S, 0)} s, {_seconds(PROGRESS_GAP_S, 0)} s y "
            f"{_seconds(CANCEL_BUDGET_S, 0)} s; {perf.free_space(made.root)})"
        )
        self.assertLessEqual(found.total_s, FREEZE_BUDGET_S)
        self.assertLessEqual(found.gap_s, PROGRESS_GAP_S)
        self.assertLessEqual(stopped.gap_s, PROGRESS_GAP_S)
        self.assertLessEqual(cancel, CANCEL_BUDGET_S)


# --- RNF-009-03 y 04 --------------------------------------------------------------------------

_SHARED: dict[str, Any] = {}
_STACK = ExitStack()


def _revisions() -> Any:
    """El proyecto de las 200 revisiones congeladas, cerrado, en disco local (se construye la
    primera vez: unos 25 s)."""
    if "local" not in _SHARED:
        tmp = _STACK.enter_context(project_tmp("gb-009-rv-"))
        _SHARED["local"] = perf.build_revisions(tmp)
    return _SHARED["local"]


def tearDownModule() -> None:
    _SHARED.clear()
    _STACK.close()


def _snapshot_checks(test: unittest.TestCase, made: Any, folder: Path, where: str,
                     budget: float) -> None:
    """La comprobación de apertura del proyecto de las 200 revisiones abierto en ``folder``
    (la primera vez y :data:`RUNS` más) y su paso «instantáneas» contra ``budget``; su paso
    más largo, contra :data:`CHECK_STEP_BUDGET_S` solo en disco local (el de RNF-008-12; en la
    red, cada paso incluye la espera de un listado y se anota)."""
    with perf.open_revisions(made, folder) as project:
        runs = [perf.open_check(project) for _ in range(RUNS + 1)]
    first, rest = runs[0], runs[1:]
    for run in runs:
        test.assertEqual(run.revisions, made.revisions)
        test.assertEqual(run.altered, ())
    totals = [run.phase_s for run in rest]
    longest = [run.longest_s for run in rest]
    median = statistics.median(totals)
    step = statistics.median(longest)
    local = budget == CHECK_BUDGET_S
    requirement = "RNF-009-03" if local else "RNF-009-04"
    step_budget = (f"presupuestos {_seconds(budget, 1)} s y {_ms(CHECK_STEP_BUDGET_S)} ms" if local
                   else f"presupuesto {_seconds(budget, 1)} s; el paso, anotado")
    perf.report(
        f"{requirement}: el paso «{vcheck.PHASE}» de la comprobación de apertura con "
        f"{first.revisions} revisiones congeladas ({made.versions} versiones × "
        f"{made.per_version}; cada una, {made.own_files} ficheros propios, "
        f"{made.other_files} datos en otra instantánea y un manifiesto de "
        f"{perf.number(made.manifest_bytes / 1000, 1)} kB) {where}: la primera vez "
        f"{_seconds(first.phase_s)} s; las {len(rest)} siguientes, mediana {_seconds(median)} s "
        f"(máximo {_seconds(max(totals))} s), paso más largo mediana {_ms(step)} ms (máximo "
        f"{_ms(max(longest))} ms); la comprobación entera, mediana "
        f"{_seconds(statistics.median(run.total_s for run in rest))} s ({step_budget}; "
        f"{perf.free_space(folder)})"
    )
    test.assertLessEqual(median, budget)
    if local:
        test.assertLessEqual(step, CHECK_STEP_BUDGET_S)


class SnapshotCheckTest(unittest.TestCase):
    def test_two_hundred_revisions_at_opening(self) -> None:
        """RNF-009-03: con 200 revisiones congeladas en disco local, el paso de las
        instantáneas de la comprobación de apertura (la huella de cada manifiesto y la
        existencia y el tamaño de cada fichero) tarda ≤ 0,5 s (mediana de 5 tras una primera
        vuelta), con ningún paso de más de 20 ms (mediana de 5), y no da ninguna alterada."""
        made = _revisions()
        _snapshot_checks(self, made, made.folder, "en disco local", CHECK_BUDGET_S)


# --- RNF-009-06 -------------------------------------------------------------------------------


class GrowthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.stack = ExitStack()
        try:
            tmp = cls.stack.enter_context(project_tmp("gb-009-gr-"))
            cls.made = cls.stack.enter_context(perf.growth_project(tmp, GROWTH_ELEMENTS))
        except BaseException:
            cls.stack.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stack.close()
        super().tearDownClass()

    def test_unchanged_revision_grows_less_than_a_megabyte(self) -> None:
        """RNF-009-06: congelar sin cambios una revisión de 1 000 elementos y otra de 2 000
        (todo ya copiado en la revisión anterior de su versión) hace crecer el proyecto (sin
        ``cache/``) como mucho lo que copia más 1 MB."""
        made = self.made
        for code, elements in zip(made.codes, GROWTH_ELEMENTS, strict=True):
            with self.subTest(code=code, elements=elements):
                grown = perf.freeze_unchanged(made, code)
                self.assertEqual(grown.elements, elements)
                self.assertEqual(grown.copied_bytes, 0)
                perf.report(
                    f"RNF-009-06: congelar sin cambios {grown.label}, de "
                    f"{perf.count(grown.elements)} elementos ({grown.kinds}), todo ya copiado "
                    f"en la anterior: el proyecto sin cache/ crece "
                    f"{perf.number(grown.grown_bytes / 1e6, 3)} MB (la base "
                    f"{perf.number(grown.database_bytes / 1e6, 3)} MB, el manifiesto "
                    f"{perf.number(grown.manifest_bytes / 1e6, 3)} MB; "
                    f"{perf.number(grown.grown_bytes / grown.elements / 1000, 2)} kB por "
                    f"elemento) con {grown.copied_bytes} B copiados (presupuesto lo copiado + "
                    f"{perf.number(GROWTH_MARGIN_BYTES / 1e6, 0)} MB; {perf.free_space(made.root)})"
                )
                self.assertLessEqual(grown.grown_bytes, grown.copied_bytes + GROWTH_MARGIN_BYTES)


# --- En la red: RNF-009-01 y 04 ---------------------------------------------------------------


class NetworkTest(unittest.TestCase):
    @requires(network.NET, network.NET_HINT)
    def test_declare_current_on_the_network(self) -> None:
        """RNF-009-01: con el proyecto de D-13 en la carpeta de pruebas de la red, declarar
        VIGENTE una versión con otra VIGENTE tarda ≤ 1 s (mediana de 5, con la cabecera) y no
        cambia ningún fichero salvo la base, su diario y la cabecera."""
        with ExitStack() as stack:
            remote = stack.enter_context(network.net_tmp("gb-009-st-"))
            stack.enter_context(perf.versions_registered())
            built = perf.build_d13_versions(remote / "proyectos", remote / "fuentes")
            stack.callback(built.close)
            _state_changes(self, built, built.codes, "en la red", NET_STATE_BUDGET_S,
                           hashes=False)

    @requires(network.NET, network.NET_HINT)
    def test_two_hundred_revisions_on_the_network(self) -> None:
        """RNF-009-04: con el proyecto de las 200 revisiones congeladas copiado a la carpeta de
        pruebas de la red, el paso de las instantáneas de la comprobación de apertura tarda
        ≤ 5 s (mediana de 5 tras una primera vuelta) y no da ninguna alterada."""
        made = _revisions()
        with network.net_tmp("gb-009-rv-") as remote:
            for part in ("proyectos", "fuentes"):
                shutil.copytree(made.folder / part, remote / part)
            _snapshot_checks(self, made, remote, "en la red", NET_CHECK_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
