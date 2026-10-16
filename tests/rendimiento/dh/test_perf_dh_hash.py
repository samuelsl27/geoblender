# SPDX-License-Identifier: GPL-3.0-or-later
"""Hash de contenido de una base de RecMin de 100 MB (spec 005, T43; RNF-008-11 y RNF-005-05;
S-4 de la 008; plan 005 §5.6.11 y plan 008 §7.3).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender en el PC de referencia
de la spec 001 §5, en disco local (``%TEMP%``), **con el motor de Access** (ACE de 64 bits:
``requires("ace", …)``; sin él, todo el módulo se omite con ``[ENTORNO] ace``). Cada cifra se
imprime en una línea ``RNF-008-11: …`` con el equipo y el intérprete (``tools/check.py`` las
recoge) y se compara con su presupuesto, sin relajarlo.

**Datos** (se generan y no se versionan): V-ref de ``tests/data/dh/sintetico.py`` como base
de RecMin ACE con el esquema 12 (``tests.support.recmin.vref_base``, la de la T33) y su tabla
de muestras multiplicada por :data:`SCALE` (``build_mdb.ps1 -Scale``: sus filas copiadas con
``INSERT … SELECT``, cada copia con su número nuevo): 2.000 sondeos, 20.000 estaciones,
50.000 tramos de litología y 875.000 muestras con 20 elementos en Single (17,5 M valores), unos
101 MB. Se crea una vez para el módulo (alrededor de un minuto) y no pasa por el almacén de
las bases de las pruebas.

- :class:`BigRecminHashTest`: el arnés ``BigHashHarness`` de la 008
  (``tests/support/provenance_fixtures.py``, el de ``BigHashTest`` y el de la 006) con
  ``io.recmin_mdb@1``: el hash de contenido de la base por el camino del trabajo
  ``core_content_hash`` (``jobs.content_hash.run`` con la ruta en ``paths``: la copia verificada
  a ``in/`` que pide el lector, su copia privada, la extracción con el ``powershell.exe`` hijo y
  el hash de las tablas que lee el importador): ≤ 30 s (mediana de :data:`REPETITIONS`), un
  aviso de progreso cada ≤ 1 s y la cancelación mirada cada ≤ 2 s, también mientras copia;
  cancelar al empezar y a mitad (con el ``powershell.exe`` extrayendo la base) lo para en
  ≤ 2 s y en ≤ 2 s no queda vivo ningún proceso hijo de este.
- :class:`NetworkBigRecminHashTest`: con ``GEOBLENDER_NET_TEST_DIR`` (recurso «red»; nunca la
  carpeta de los expedientes ni la del espejo; sin ella, se omite), la misma base en una
  subcarpeta temporal de la red que se borra al final: la copia verificada desde ``Z:`` y el
  trabajo dan el mismo hash que en disco local, con los mismos avisos y la misma cancelación;
  lo que tardan se anota (los 30 s de RNF-008-11 se miden en disco local).
"""

from __future__ import annotations

import gc
import os
import shutil
import statistics
import tempfile
import time
import unittest
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from tests.support import dh_sets, jobs_fixtures, network, recmin
from tests.support import gis_perf as perf
from tests.support import provenance_fixtures as d13
from tests.support.package import import_geoblender
from tests.support.resources import is_available, requires, skip_reason
from tests.support.trees import remove_tree

dh_content = import_geoblender("interop.dh_content")
model = import_geoblender("drillholes.model")
provenance = import_geoblender("drillholes.provenance")
readers = import_geoblender("core.content.readers")

BUDGET_S = 30.0  # RNF-008-11: una base de RecMin (MDB) de 100 MB
REPETITIONS = perf.REPETITIONS  # mediana de 5

# V-ref (spec 005 §5) y la base de 100 MB.
VREF_HOLES = 2_000
VREF_STATIONS = 20_000
VREF_LITHOLOGY = 50_000
VREF_SAMPLES = 25_000
ELEMENTS = 20
SCALE = 35  # las muestras de V-ref, 35 veces: unos 101 MB
SAMPLES = SCALE * VREF_SAMPLES
BIG_BYTES = 100_000_000  # lo que mide como poco la base (100 MB)
ROWS = {"sondeos": VREF_HOLES, "angulos": VREF_STATIONS, "litologia": VREF_LITHOLOGY,
        recmin.VREF_SAMPLES: SAMPLES, "elementos": ELEMENTS}
"""Las filas que cuenta el motor en las tablas de la base que se comprueban."""

DECIMAL = ","  # el de los números escritos como texto (RecMin no tiene)
CHILD = "powershell.exe"  # el hijo que extrae la base (ADR-0018)
PROCESS_POLL_S = 0.02  # lo que se espera entre dos miradas a los procesos del equipo
WAIT_S = 600.0  # plazo de seguridad: un proceso colgado no cuelga la prueba
LABEL = (f"una base de RecMin ACE con V-ref y {perf.count(SAMPLES)} muestras de {ELEMENTS} "
         "elementos")
MACHINE = perf.MACHINE


# --- Datos ---------------------------------------------------------------------------------


class _Data:
    """Lo que comparten las pruebas, creado una vez en :func:`setUpModule`."""

    folder: Path  # la carpeta temporal del módulo
    base: Any  # la base de RecMin de 100 MB (recmin.BuiltBase)
    build_s: float  # lo que tardó build_mdb.ps1 en crearla
    digest: Any = None  # su ContentDigest en disco local (para comparar el de la red)


_DATA = _Data()


def setUpModule() -> None:
    """La base de RecMin de 100 MB (``build_mdb.ps1 -Scale``) en una carpeta temporal del
    módulo, que se borra al final."""
    if not is_available(recmin.ACE):
        raise unittest.SkipTest(skip_reason(recmin.ACE, recmin.ACE_HINT))
    stack = ExitStack()
    unittest.addModuleCleanup(stack.close)
    _DATA.folder = Path(stack.enter_context(tempfile.TemporaryDirectory(
        prefix="gb-dhh-", ignore_cleanup_errors=True)))
    started = time.perf_counter()
    _DATA.base = recmin.vref_base(_DATA.folder / "fuente", scale=SCALE)
    _DATA.build_s = time.perf_counter() - started


def _declaration() -> Any:
    """Lo que declara quien importa la base (como en la T33): EPSG:25830 y EPSG:5782, azimut
    de cuadrícula y «−x = <x»."""
    return model.SourceDeclaration(
        crs=dh_sets.H25830, vertical=dh_sets.V5782, azimuth_ref=model.AzimuthRef.GRID,
        declination_deg=None, inclination_convention=model.InclinationConvention.NEGATIVE_DOWN,
        units={}, value_rules=model.ValueRules(decimal_mark=DECIMAL, negative_is_below_dl=True))


def _source(path: Path, where: str) -> d13.BigSource:
    """La base ``path`` como fuente del arnés: una entrada ``drillholes`` con las
    declaraciones de su importación y el decimal de sus ajustes."""
    declarations = provenance.source_declarations(dh_content.RECMIN_MDB.id, _declaration())
    return d13.BigSource({"main": path}, "drillholes", declarations, {"decimal": DECIMAL},
                         f"{LABEL}{where}")


def _local_digest() -> Any:
    """El ``ContentDigest`` de la base en disco local: el de :class:`BigRecminHashTest` si ya
    se calculó o, si no, leído en el hilo (``read_content``)."""
    if _DATA.digest is None:
        source = _source(_DATA.base.path, "")
        reader = dh_content.RECMIN_MDB
        request = reader.request(source.kind, source.declarations, source.files,
                                 dict(source.settings))
        _DATA.digest = readers.read_content(reader, request)
    return _DATA.digest


# --- El arnés de la 008 con io.recmin_mdb@1 --------------------------------------------------


class _RecminHash(d13.BigHashHarness):
    """Lo común de las dos clases: el lector, su presupuesto, la línea de la medida y la
    cancelación con los procesos hijos de este proceso a la vista."""

    reader = dh_content.RECMIN_MDB
    budget_s = BUDGET_S
    cancel_children: list[str]  # los hijos vivos al pedir parar, en la última cancelación

    @classmethod
    def report(cls, text: str) -> None:
        perf.report(f"{text} [{MACHINE}]")

    def tearDown(self) -> None:
        self.clean_jobs()
        super().tearDown()

    def clean_jobs(self) -> None:
        """Borra las carpetas de los trabajos de hash ya hechos (su copia de 100 MB)."""
        remove_tree(self.big_folder / d13.JOBS_FOLDER)

    def _cancelled_when(self, wanted: Callable[[float], bool], moment: str) -> None:
        """La cancelación del arnés y, además, los procesos hijos de este proceso (y los
        suyos) cuando se pide parar (``cancel_children``) y lo que tardan en no quedar
        ninguno vivo, que se comprueba con el mismo presupuesto."""
        before = jobs_fixtures.processes()
        root = os.getpid()
        seen: list[tuple[float, dict[int, str]]] = []

        def watched(fraction: float) -> bool:
            if not wanted(fraction):
                return False
            if not seen:
                seen.append((time.perf_counter(), jobs_fixtures.descendants(
                    before, jobs_fixtures.processes(), [root])))
            return True

        super()._cancelled_when(watched, moment)
        asked, children = seen[0]
        while True:
            alive = jobs_fixtures.descendants(before, jobs_fixtures.processes(), [root])
            exited = time.perf_counter() - asked
            if not alive or exited > WAIT_S:
                break
            time.sleep(PROCESS_POLL_S)
        self.cancel_children = sorted({name.casefold() for name in children.values()})
        alive_text = ", ".join(self.cancel_children) or "ninguno"
        self.report(
            f"{self.requirement}: cancelar {moment} el hash de contenido de "
            f"{self.source.label} con {self.reader.id}: procesos hijos vivos al pedirlo: "
            f"{alive_text}; ninguno vivo en {perf.number(exited)} s (presupuesto "
            f"{perf.number(self.cancel_budget_s, 0)} s)")
        test: Any = self
        test.assertEqual(alive, {})
        test.assertLessEqual(exited, self.cancel_budget_s)

    def test_big_hash_cancelled_at_half(self) -> None:
        """RNF-008-11, RNF-005-05: cancelar a mitad el hash de contenido de la base, con su
        ``powershell.exe`` hijo extrayéndola, lo para en ≤ 2 s (``JobCancelled``) y en ≤ 2 s
        no queda vivo ningún proceso hijo."""
        super().test_big_hash_cancelled_at_half()
        test: Any = self
        test.assertIn(CHILD, self.cancel_children)


@requires(recmin.ACE, recmin.ACE_HINT)
class BigRecminHashTest(_RecminHash, unittest.TestCase):
    """RNF-008-11 con ``io.recmin_mdb@1``: la base de RecMin de 100 MB en disco local, por el
    trabajo de hash ``core_content_hash`` (el arnés de la 008, S-4)."""

    @classmethod
    def make_source(cls, folder: Path) -> d13.BigSource:
        return _source(_DATA.base.path, "")

    def test_base_of_100_mb(self) -> None:
        """RNF-008-11: la base medida es V-ref como base de RecMin ACE con sus muestras
        multiplicadas (``build_mdb.ps1 -Scale``): mide 100 MB como poco y el motor cuenta en
        ella los sondeos, las estaciones, los tramos y los elementos de V-ref y
        :data:`SCALE` veces sus muestras."""
        base = _DATA.base
        size = base.path.stat().st_size
        rows = {name.casefold(): table.rows for name, table in base.tables.items()}
        perf.report(
            f"RNF-008-11: {LABEL}: {perf.number(size / 1e6, 1)} MB, creada por "
            f"build_mdb.ps1 -Scale {SCALE} en {perf.number(_DATA.build_s, 1)} s [{MACHINE}]")
        self.assertEqual(base.engine, recmin.ACE)
        self.assertGreaterEqual(size, BIG_BYTES)
        self.assertEqual({name: rows.get(name) for name in ROWS}, ROWS)

    def test_big_hash(self) -> None:
        """RNF-008-11: el hash de contenido de la base de RecMin de 100 MB por el trabajo de
        hash tarda ≤ 30 s (mediana de :data:`REPETITIONS`), con un aviso de progreso cada
        ≤ 1 s y la cancelación mirada cada ≤ 2 s en cada una (también mientras copia la
        base), y todas dan el mismo hash."""
        times: list[float] = []
        copies: list[float] = []
        gaps: list[float] = []
        looks: list[float] = []
        ticks: list[int] = []
        digests: list[Any] = []
        for _ in range(REPETITIONS):
            self.clean_jobs()
            gc.collect()
            clock = d13.ProgressClock()
            digest, copy_s = self.hash_source(progress=clock.tick)
            total, gap = clock.finish()
            times.append(total)
            copies.append(copy_s)
            gaps.append(gap)
            looks.append(self._looks_gap(clock.started + total))
            ticks.append(clock.ticks)
            digests.append(digest)
        _DATA.digest = digests[0]
        self.report(
            f"{self.requirement}: hash de contenido de {self.source.label} ({self._size()}) "
            f"con {self.reader.id} por el trabajo core_content_hash: {perf.median_line(times)}"
            f" (copia verificada, mediana {perf.number(statistics.median(copies), 2)} s), "
            f"{min(ticks)}–{max(ticks)} avisos de progreso, el mayor hueco "
            f"{perf.number(max(gaps))} s, la cancelación mirada cada "
            f"≤ {perf.number(max(looks))} s (presupuestos {perf.number(self.budget_s, 0)} s, "
            f"{perf.number(self.progress_gap_s, 0)} s y {perf.number(self.cancel_budget_s, 0)} s)")
        self.assertEqual({digest.reader for digest in digests}, {self.reader.id})
        self.assertEqual(len(set(digests)), 1)
        self.assertTrue(all(copy_s > 0.0 for copy_s in copies))
        self.assertLessEqual(statistics.median(times), self.budget_s)
        self.assertLessEqual(max(gaps), self.progress_gap_s)
        self.assertLessEqual(max(looks), self.cancel_budget_s)


@requires(recmin.ACE, recmin.ACE_HINT)
@requires(network.NET, network.NET_HINT)
class NetworkBigRecminHashTest(_RecminHash, unittest.TestCase):
    """La misma base de RecMin de 100 MB en la carpeta de pruebas de la red (``Z:``): la copia
    verificada del trabajo de hash la lee de la red; lo que tardan la subida, la copia y el
    trabajo se anota (para H3), con el mismo hash que en disco local, los avisos de progreso
    y la cancelación del arnés."""

    upload_s: float = 0.0

    @classmethod
    def make_source(cls, folder: Path) -> d13.BigSource:
        remote = cls._big_stack.enter_context(network.net_tmp("gb-005-hash-"))
        started = time.perf_counter()
        target = Path(shutil.copyfile(_DATA.base.path, remote / _DATA.base.path.name))
        cls.upload_s = time.perf_counter() - started
        return _source(target, " en la red")

    def test_big_hash(self) -> None:
        """RNF-008-11 (en la red, para H3): el hash de contenido de la base en ``Z:`` por el
        trabajo de hash (su copia verificada lee la red) da el mismo que en disco local, con
        un aviso de progreso cada ≤ 1 s y la cancelación mirada cada ≤ 2 s; lo que tardan la
        copia y el trabajo se anota."""
        clock = d13.ProgressClock()
        digest, copy_s = self.hash_source(progress=clock.tick)
        total, gap = clock.finish()
        looks = self._looks_gap(clock.started + total)
        self.report(
            f"{self.requirement}: hash de contenido de {self.source.label} ({self._size()}, "
            f"subida en {perf.number(self.upload_s, 2)} s) con {self.reader.id} por el "
            f"trabajo core_content_hash: {perf.number(total, 2)} s con la copia verificada "
            f"desde la red en {perf.number(copy_s, 2)} s (sin presupuesto en la red: se anota "
            f"para H3), {clock.ticks} avisos de progreso, el mayor hueco {perf.number(gap)} s, "
            f"la cancelación mirada cada ≤ {perf.number(looks)} s (presupuestos "
            f"{perf.number(self.progress_gap_s, 0)} s y {perf.number(self.cancel_budget_s, 0)} s)")
        self.assertEqual(digest, _local_digest())
        self.assertLessEqual(gap, self.progress_gap_s)
        self.assertLessEqual(looks, self.cancel_budget_s)


if __name__ == "__main__":
    unittest.main()
