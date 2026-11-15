# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de las entidades de diseño paramétricas: la plataforma y su cadena (spec 015, T33; RNF-015-01,
RNF-015-02, RNF-015-04, RNF-015-08 y RNF-015-09; plan 015 §7.1 y §7.3, ``tests/rendimiento/des``), con la
forma de ``test_quarry_perf.py`` de la 014.

Se ejecuta con ``tools/check.py --rendimiento``, nunca en el «verde»: el Python de Blender (su numpy 2.3.4), en
el PC de referencia de la spec 001 §5 y en disco local (``%TEMP%``). Cada cifra se imprime en una línea
``RNF-015-nn: …`` con el equipo y el intérprete y se compara con su presupuesto, sin relajarlo (mediana de 5,
como la 013 y la 014; la primera ejecución, que calienta la caché de lectura, no cuenta).

**Datos** (los de §2.2 del plan 013; ``tests/support/entity_perf.py`` y ``entity_data.py``, que no versionan
ninguno): el proyecto de escala de la 014 —la rejilla de 1.654 × 1.699 celdas de 1 m (2,81 M) con su terreno
de 145 a 215 m, los 20 sectores con su búsqueda cerrada, el límite legal y el perímetro, las máscaras de V01 al
día— con una capa de plataformas: la **grande** (eje de 500 m y 200 m de ancho, 10 ha, «en corte y relleno», con
la distancia euclídea exacta y 150 m de alcance) y las **veinte** de la cadena (de ≤ 1 ha, «en corte»,
protegidas con 5 m, con 40 m de alcance, cada una de la superficie de la anterior).

- RNF-015-01 (:class:`PlatformTest`): la plataforma grande, de la primera llamada de «Calcular» (leer la partida y
  las máscaras, la ventana de trabajo, huella, aplicar, borde, perfil, cifras y resumen) a «Crear» (escribir la
  superficie, las tablas y completar la operación), en un proyecto en disco local, ≤ 10 s. En ``Z:`` (≤ 20 s,
  :class:`NetworkPlatformTest`) se mide a mano en la carpeta de pruebas de la red (``GEOBLENDER_NET_TEST_DIR``,
  nunca la de los expedientes de clientes).
- RNF-015-04 (:class:`PlatformTest`): el pico de memoria adicional de ese cálculo (``tracemalloc``, con la de
  numpy; aparte de las de tiempo) ≤ 1,5 GB.
- RNF-015-02 (:class:`ListsTest`): con **200 entidades** en la versión (la primera de verdad y 199 que se apoyan
  en ella), lo que se apoya en una, en qué se apoya la última y lo que declara, ≤ 1 s (en ``Z:``, ≤ 3 s).
- RNF-015-08 (:class:`ChainTest`): la cadena de **20 entidades** de ≤ 1 ha con su borde (con la declaración y la
  capa de entidades que cada orden encadena), tras cambiar la cota de la primera: «Recalcular lo obsoleto» hasta
  que no queda nada, ≤ 60 s (en ``Z:``, ≤ 2 min).
- RNF-015-09 (:class:`ChainTest`, de las mismas veinte): lo que guarda en el proyecto cada una —su superficie en
  la rejilla entera comprimida (DEFLATE con predictor) más sus tablas— ≤ 17 MiB y la revisión con las 20 ≤ 0,35 GiB
  (spec 0.5, 15/11/2026: la 0.4 decía «≤ 16 MB», pero medía 16,3 MiB con el terreno de §2.2 de la 013, y Samuel aceptó
  17 MiB). **MiB y GiB son de 2^20 y 2^30 bytes**, como las cifras medidas de la spec (13,7 y 15,7 MiB: unas colinas
  y las mismas con ruido de 5 cm, sobre las 2,81 M celdas).

Lo que hace Geoblender en cada llamada del hilo de Blender con las órdenes reales (RNF-015-03, 05 y 06) se mide
dentro de Blender (``perf_entities.py``).
"""

from __future__ import annotations

import gc
import statistics
import time
import unittest
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from tests.support import design_perf as dperf
from tests.support import entity_data as edata
from tests.support import entity_perf as ep
from tests.support import gis_perf, network
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.resources import requires

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")

PLATFORM_BUDGET_S = 10.0  # RNF-015-01, en disco local
PLATFORM_NETWORK_BUDGET_S = 20.0  # RNF-015-01 en Z:
MEMORY_BUDGET_BYTES = int(1.5 * 1024**3)  # RNF-015-04: 1,5 GB
LISTS_BUDGET_S = 1.0  # RNF-015-02, en disco local
LISTS_NETWORK_BUDGET_S = 3.0  # RNF-015-02 en Z:
CASCADE_BUDGET_S = 60.0  # RNF-015-08, en disco local
CASCADE_NETWORK_BUDGET_S = 120.0  # RNF-015-08 en Z:: 2 min
ENTITY_BUDGET_BYTES = 17 * 1024**2  # RNF-015-09: 17 MiB por entidad (spec 0.5; la 0.4 decía 16 «MB»)
REVISION_BUDGET_BYTES = int(0.35 * 1024**3)  # RNF-015-09: 0,35 GiB con 20
RUNS = 5  # como la 013 y la 014 (su spec §5): mediana de 5
NETWORK_RUNS = 3  # en Z: cada ejecución escribe superficies de 17 MB: mediana de 3
MACHINE = gis_perf.MACHINE
number = gis_perf.number
count = gis_perf.count
seconds_of = gis_perf.median_line
MIB = 1024**2
FIRST_KEY = design_params.entity_key("PLT-001", "start_level_m")


def mib(value: float) -> str:
    """Bytes en MB de 2^20 (con coma decimal)."""
    return number(value / MIB, 2)


def surface_bytes(project: Any, code: str, version_uid: str) -> int:
    """Lo que ocupa en disco la superficie (``des_psf_``) de la entidad ``code`` de la versión."""
    entry = entities.registry(project, version_uid).get(code)
    assert entry is not None and entry.operation_uid is not None, code
    with project.read() as conn:
        rows = conn.execute(
            "SELECT d.locator FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.role = ?",
            (entry.operation_uid, provenance.ENTITY_SURFACE_ROLE)).fetchall()
    ((locator,),) = rows
    path = Path(project.root) / str(locator)
    assert path.is_file(), path
    return path.stat().st_size


class NetworkProject:
    """El proyecto de escala en una subcarpeta temporal de la carpeta de pruebas de la red (``Z:``), borrada
    al terminar, con los datos de usuario en disco local (``tests.support.network``: con
    ``GEOBLENDER_NET_TEST_DIR``, a mano; sin ella, se omite; nunca la de los expedientes de clientes)."""

    WHERE = "con el proyecto en la carpeta de pruebas de la red"

    @classmethod
    def make_project(cls) -> Any:
        stack = ExitStack()
        cls.addClassCleanup(stack.close)  # type: ignore[attr-defined]
        remote = stack.enter_context(network.net_tmp("gb-015-t33-"))
        local = stack.enter_context(project_tmp("gb-015-u-"))
        return stack.enter_context(ep.scale_project(folder=remote, userdata=local / "u"))


# --- RNF-015-01 y RNF-015-04: la plataforma con su borde -----------------------------------------


@dataclass(frozen=True, slots=True)
class Platform:
    """Una plataforma grande calculada, creada y descartada: lo que tardaron «Calcular» y «Crear» y lo que dejó."""

    calculate_s: float
    create_s: float
    outcome: Any

    @property
    def total_s(self) -> float:
        return self.calculate_s + self.create_s


class PlatformTest(unittest.TestCase):
    """RNF-015-01 y RNF-015-04 con el proyecto de escala (2,81 M celdas) y su capa de plataformas, en disco
    local: sobre el terreno de la plataforma grande, cada ejecución la calcula, la crea y la descarta (de cada
    superficie parte una sola entidad), con un nombre nuevo."""

    BUDGET_S = PLATFORM_BUDGET_S
    RUNS = RUNS
    WHERE = "proyecto en disco local"
    data: ClassVar[Any]

    @classmethod
    def make_project(cls) -> Any:
        return cls.enterClassContext(ep.scale_project())

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = cls.make_project()

    def platform(self) -> Platform:
        """«Calcular» y «Crear» la plataforma grande y descartarla (lo último no cuenta)."""
        data = self.data
        data.clock.advance(minutes=1)
        made = ep.calculate(data, ep.big_request(ep.fresh_name("Grande")))
        data.clock.advance(minutes=1)
        code = [entry.record.code for entry in entities.registry(data.project, data.v1.uid)][-1]
        entity_store.discard_entity(data.project, data.v1.uid, code, reason="Medición de rendimiento")
        return Platform(made.calculate_s, made.create_s, made.outcome)

    def repeat(self) -> list[Platform]:
        """``RUNS`` ejecuciones seguidas (con la basura recogida antes de cada una), después de una que calienta la
        caché de lectura y no cuenta."""
        self.platform()
        found = []
        for _ in range(self.RUNS):
            gc.collect()
            found.append(self.platform())
        return found

    def test_a_platform_with_its_edge(self) -> None:
        """RNF-015-01: una plataforma con su borde sobre 2,81 M celdas —de 500 m de eje y 200 m de ancho (10 ha,
        100.000 celdas), «en corte y relleno», con la distancia euclídea exacta y 150 m de alcance— de la primera
        llamada de «Calcular» (leer la partida y las máscaras, la ventana de trabajo, huella y rasante, aplicar, el
        borde, la contrapendiente, las cifras y el resumen) a «Crear» (escribir la superficie, las tablas y
        completar la operación), en un proyecto en disco local, en ≤ 10 s (mediana de 5; la primera, que calienta
        la caché, no cuenta)."""
        found = self.repeat()
        last = found[-1].outcome
        total = [item.total_s for item in found]
        length = edata.BIG_AXIS_LOCAL[1][0] - edata.BIG_AXIS_LOCAL[0][0]
        gis_perf.report(
            f"RNF-015-01: una plataforma con su borde (eje de {number(length, 0)} m y "
            f"{number(edata.BIG_WIDTH_M, 0)} m de ancho, {count(last.footprint.cell_count)} celdas de huella, «en "
            f"corte y relleno», distancia euclídea exacta, {number(edata.BIG_REACH_M, 0)} m de alcance) sobre "
            f"{count(dperf.CELLS)} celdas de 1 m, de «Calcular» (leer la partida y las máscaras, ventana, huella, "
            f"aplicar, borde, cifras y resumen) a «Crear» (escribir la superficie y las tablas y completar; "
            f"{self.WHERE}; {MACHINE}): {seconds_of(total)}; «Calcular» "
            f"{number(statistics.median(item.calculate_s for item in found), 2)} s y «Crear» "
            f"{number(statistics.median(item.create_s for item in found), 2)} s de mediana; presupuesto "
            f"{number(self.BUDGET_S, 0)} s")
        self.assertGreater(last.footprint.cell_count, 90_000, "la plataforma no tiene su huella: no mide nada")
        self.assertLessEqual(statistics.median(total), self.BUDGET_S)

    def test_b_memory(self) -> None:
        """RNF-015-04: el pico de memoria adicional (``tracemalloc``, con la de numpy) de la plataforma de
        RNF-015-01, de «Calcular» a «Crear», ≤ 1,5 GB."""
        self.platform()  # sin caché de lectura
        peak = gis_perf.peak_bytes(self.platform)
        gis_perf.report(
            f"RNF-015-04: pico de memoria adicional (tracemalloc, con la de numpy) de una plataforma con su borde "
            f"sobre {count(dperf.CELLS)} celdas de 1 m, de «Calcular» a «Crear» ({MACHINE}): "
            f"{number(peak / MIB, 0)} MiB; presupuesto {number(MEMORY_BUDGET_BYTES / MIB, 0)} MiB")
        self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)


# --- RNF-015-02: las listas con 200 entidades ----------------------------------------------------


class ListsTest(unittest.TestCase):
    """La primera entidad de verdad y 199 que se apoyan en ella, en un proyecto de escala."""

    BUDGET_S = LISTS_BUDGET_S
    WHERE = "proyecto en disco local"
    data: ClassVar[Any]

    @classmethod
    def make_project(cls) -> Any:
        return cls.enterClassContext(ep.scale_project())

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = cls.make_project()
        cls.data.clock.advance(minutes=1)
        ep.calculate(cls.data, ep.chain_request(0))
        ep.add_dependents(cls.data)

    def timed(self, what: Callable[[], Any]) -> tuple[list[float], Any]:
        """:data:`RUNS` ejecuciones seguidas de ``what`` (la primera, en frío, también cuenta: una lista no tiene
        caché propia) y lo que dio la última."""
        times, found = [], None
        for _ in range(RUNS):
            gc.collect()
            began = time.perf_counter()
            found = what()
            times.append(time.perf_counter() - began)
        return times, found

    def test_lists(self) -> None:
        """RNF-015-02: con 200 entidades en la versión, «lo que se apoya en» la primera (199, cada una con su
        volumen), «en qué se apoya» la última y lo que declara apoyarse (``declared_supports``) tardan ≤ 1 s cada
        una (mediana de 5): son una consulta de entradas y cifras, sin leer ninguna superficie."""
        project, version = self.data.project, self.data.v1
        last = f"PLT-{edata.SYNTHETIC_ENTITIES:03d}"
        self.assertEqual(len(entities.registry(project, version.uid)), edata.SYNTHETIC_ENTITIES)
        resting, listed = self.timed(lambda: entities.dependents(project, version.uid, "PLT-001"))
        rests, based = self.timed(lambda: entities.dependencies_of(project, version.uid, last))
        declared, said = self.timed(lambda: entity_store.declared_supports(project, version, last))
        registry, _read = self.timed(lambda: entities.registry(project, version.uid))
        self.assertEqual(len(listed), edata.SYNTHETIC_ENTITIES - 1)
        self.assertEqual(len(based), 1)
        self.assertEqual(said, ())
        gis_perf.report(
            f"RNF-015-02: con {edata.SYNTHETIC_ENTITIES} entidades en la versión ({self.WHERE}; {MACHINE}), lo "
            f"que se apoya en la primera ({len(listed)} filas con su volumen): {seconds_of(resting)}; en qué se "
            f"apoya la última: {seconds_of(rests)}; lo que declara: {seconds_of(declared)}; el registro de las "
            f"entidades: {seconds_of(registry)}; presupuesto {number(self.BUDGET_S, 0)} s cada una")
        for what, times in (("lo que se apoya en", resting), ("en qué se apoya", rests),
                            ("lo que declara", declared)):
            self.assertLessEqual(statistics.median(times), self.BUDGET_S, what)


# --- RNF-015-08 y RNF-015-09: la cadena de 20 entidades ------------------------------------------


@dataclass(frozen=True, slots=True)
class Cascaded:
    """Una cascada: lo que tardó de cambiar la primera a que no quedara nada obsoleto, las operaciones que rehízo,
    las vueltas de «Recalcular lo obsoleto» que hicieron falta y las plataformas que rehízo."""

    seconds: float
    units: int
    rounds: int
    platforms: int


class ChainTest(unittest.TestCase):
    """La cadena de 20 plataformas de ≤ 1 ha en V01, con lo que cada orden encadena (la declaración de las
    restricciones que protegen, las máscaras y la capa de entidades), creada una vez por clase: RNF-015-08 y
    RNF-015-09 en disco local."""

    BUDGET_S = CASCADE_BUDGET_S
    CASCADES = RUNS
    WHERE = "proyecto en disco local"
    data: ClassVar[Any]
    made: ClassVar[list[ep.Calculated]]
    created_s: ClassVar[float]
    level: ClassVar[float]
    sizes: ClassVar[list[tuple[int, int]]]

    @classmethod
    def make_project(cls) -> Any:
        return cls.enterClassContext(ep.scale_project())

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = cls.make_project()
        before = ep.database_bytes(cls.data.project)
        began = time.perf_counter()
        cls.made = ep.create_chain(cls.data)
        cls.created_s = time.perf_counter() - began
        cls.chain_db_bytes = ep.database_bytes(cls.data.project) - before
        version = cls.data.v1.uid
        cls.sizes = [(surface_bytes(cls.data.project, f"PLT-{index + 1:03d}", version), item.db_bytes)
                     for index, item in enumerate(cls.made)]
        with cls.data.project.read() as conn:
            cls.level = float(core_params.ParameterStore(cls.data.project).get(
                FIRST_KEY, version=version, conn=conn).value)

    def types_of(self, result: Any) -> set[str]:
        """Los tipos de las operaciones que rehízo una unidad."""
        marks = ", ".join("?" for _ in result.operations)
        with self.data.project.read() as conn:
            return {str(op_type) for (op_type,) in conn.execute(
                f"SELECT op_type FROM gb_operation WHERE uid IN ({marks})", tuple(result.operations))}

    def cascade(self, flip: int) -> Cascaded:
        """Cambia la cota de la primera (``flip`` par: media cota más abajo; impar: la de antes) y lleva «Recalcular
        lo obsoleto» hasta que no queda nada obsoleto: lo que tardó."""
        data = self.data
        value = self.level - 0.5 if flip % 2 == 0 else self.level
        gc.collect()
        began = time.perf_counter()
        data.clock.advance(minutes=1)
        with data.project.write_transaction() as conn:
            core_params.ParameterStore(data.project).change(
                conn, FIRST_KEY, value=value, version=data.v1.uid, reason="Medición de rendimiento")
        units = platforms = rounds = 0
        while True:
            data.clock.advance(minutes=1)
            outcome = ep.finish(recompute_mod.recompute_steps(data.project))
            rounds += 1
            units += len(outcome.results)
            platforms += sum(1 for result in outcome.results if provenance.PLATFORM in self.types_of(result))
            if not outcome.remaining.units:
                break
            self.assertLess(rounds, 5 * edata.CHAIN_LENGTH, "«Recalcular lo obsoleto» no acaba")
        return Cascaded(time.perf_counter() - began, units, rounds, platforms)

    def test_a_disk(self) -> None:
        """RNF-015-09: lo que guarda en el proyecto cada una de las 20 —su superficie en la rejilla entera
        comprimida (DEFLATE con predictor) más sus tablas, las del crecimiento de la base al crearla— ≤ 17 MiB (spec
        0.5; la mayor, con el terreno de §2.2 de la 013 y ruido de 5 cm, mide 16,29 MiB) y la revisión con las 20
        ≤ 0,35 GiB (MiB y GiB de 2^20 y 2^30 bytes)."""
        per_entity = [raster + tables for raster, tables in self.sizes]
        total = sum(per_entity)
        worst = max(per_entity)
        gis_perf.report(
            f"RNF-015-09: lo que guarda cada una de las {edata.CHAIN_LENGTH} entidades de la cadena (superficie en "
            f"la rejilla entera de {count(dperf.CELLS)} celdas de 1 m, comprimida con DEFLATE y predictor, más sus "
            f"tablas; terreno de §2.2 de la 013 con ruido de 5 cm; {MACHINE}): la mayor {mib(worst)} MiB, la "
            f"mediana {mib(statistics.median(per_entity))} MiB (superficie "
            f"{mib(statistics.median(raster for raster, _tables in self.sizes))} MiB, tablas "
            f"{mib(statistics.median(tables for _raster, tables in self.sizes))} MiB), presupuesto "
            f"{mib(ENTITY_BUDGET_BYTES)} MiB; la revisión con las {edata.CHAIN_LENGTH}: "
            f"{number(total / 1024**3, 3)} GiB ({mib(total)} MiB), presupuesto "
            f"{number(REVISION_BUDGET_BYTES / 1024**3, 2)} GiB; la base creció {mib(self.chain_db_bytes)} MiB con "
            f"las {edata.CHAIN_LENGTH} y lo que cada orden encadena (declaración, máscaras y capa)")
        self.assertLessEqual(total, REVISION_BUDGET_BYTES, "la revisión con 20 entidades")
        self.assertLessEqual(worst, ENTITY_BUDGET_BYTES, "una entidad")

    def test_b_cascade(self) -> None:
        """RNF-015-08: recalcular en cascada una cadena de 20 entidades de ≤ 1 ha con su borde (protegidas, con la
        declaración y la capa de entidades que cada orden encadena), tras cambiar la cota de la primera, sobre
        2,81 M celdas: «Recalcular lo obsoleto» hasta que no queda nada obsoleto, en disco local, en ≤ 60 s (mediana
        de 5; la primera, que calienta la caché, no cuenta)."""
        for index, item in enumerate(self.made):
            self.assertLessEqual(item.outcome.footprint.cell_count, edata.FOOTPRINT_LIMIT_CELLS,
                                 f"la plataforma {index + 1} pasa de 1 ha")
        first = self.cascade(0)
        found = [self.cascade(flip) for flip in range(1, self.CASCADES + 1)]
        times = [item.seconds for item in found]
        gis_perf.report(
            f"RNF-015-08: recalcular en cascada una cadena de {edata.CHAIN_LENGTH} entidades de ≤ 1 ha («en "
            f"corte», protegidas con {number(edata.CHAIN_GUARD_M, 0)} m, borde de "
            f"{number(edata.CHAIN_REACH_M, 0)} m de alcance, distancia exacta) con lo que encadena cada una "
            f"(declaración, máscaras y capa), tras cambiar la cota de la primera, sobre {count(dperf.CELLS)} "
            f"celdas de 1 m ({self.WHERE}; {MACHINE}): {seconds_of(times)}; {found[-1].platforms} plataformas y "
            f"{found[-1].units} operaciones rehechas en {found[-1].rounds} vueltas de «Recalcular lo obsoleto»; "
            f"la primera, en frío, {number(first.seconds, 2)} s; crear las {edata.CHAIN_LENGTH} (cada una con lo "
            f"que sigue) {number(self.created_s, 1)} s; presupuesto {number(self.BUDGET_S, 0)} s")
        for item in found:
            self.assertGreaterEqual(item.platforms, edata.CHAIN_LENGTH, "no rehízo las 20 plataformas")
        self.assertLessEqual(statistics.median(times), self.BUDGET_S)


# --- En la red ------------------------------------------------------------------------------------
#
# **Ojo**: en el PC de referencia la variable GEOBLENDER_NET_TEST_DIR está definida en el usuario y este
# módulo, lanzado tal cual, también corre estas clases (``docs/trampas.md`` §7); para medir solo en local, sin
# ella: ``Remove-Item Env:GEOBLENDER_NET_TEST_DIR`` (PowerShell) o ``env -u GEOBLENDER_NET_TEST_DIR …`` (Git Bash).


@requires(network.NET, network.NET_HINT)
class NetworkPlatformTest(NetworkProject, PlatformTest):
    """RNF-015-01 en ``Z:``: la plataforma grande de «Calcular» a «Crear» con el proyecto en la red, en ≤ 20 s
    (mediana de :data:`NETWORK_RUNS`; cada ejecución escribe en la red una superficie de 17 MB)."""

    BUDGET_S = PLATFORM_NETWORK_BUDGET_S
    RUNS = NETWORK_RUNS
    test_b_memory = None  # type: ignore[assignment]  # la memoria no depende de dónde esté el proyecto


@requires(network.NET, network.NET_HINT)
class NetworkListsTest(NetworkProject, ListsTest):
    """RNF-015-02 en ``Z:``: las listas con 200 entidades con el proyecto en la red, ≤ 3 s cada una."""

    BUDGET_S = LISTS_NETWORK_BUDGET_S


@requires(network.NET, network.NET_HINT)
class NetworkChainTest(NetworkProject, ChainTest):
    """RNF-015-08 en ``Z:``: la cascada de 20 entidades con el proyecto en la red, en ≤ 2 min (mediana de
    :data:`NETWORK_RUNS`; la primera, en frío, no cuenta)."""

    BUDGET_S = CASCADE_NETWORK_BUDGET_S
    CASCADES = NETWORK_RUNS
    test_a_disk = None  # type: ignore[assignment]  # el disco es el mismo: se mide en local


if __name__ == "__main__":
    unittest.main()
