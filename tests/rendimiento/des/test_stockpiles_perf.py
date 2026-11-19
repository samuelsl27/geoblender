# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de los acopios, el contrafuerte y los cuerpos apoyados (spec 016, T37; RNF-016-01, RNF-016-02, RNF-016-03,
RNF-016-04 y RNF-016-07; plan 016 §7.1, §7.3 y §7.4, ``tests/rendimiento/des``), con la forma de ``test_entities_perf.py`` de la
015: los guiones de medida de ``plan.md`` §7.3 convertidos en pruebas.

Se ejecuta con ``tools/check.py --rendimiento``, nunca en el «verde»: el Python de Blender (su numpy 2.3.4), en el PC de
referencia de la spec 001 §5 y en disco local (``%TEMP%``). Cada cifra se imprime en una línea ``RNF-016-nn: …`` con el equipo y
el intérprete y se compara con su presupuesto, **sin relajarlo** (mediana de 5, como la 013 a la 015; la primera ejecución, que
calienta la caché de lectura, no cuenta).

**Datos** (``tests/support/stockpile_perf.py`` y ``stockpile_data.py``, T01, que no versionan ninguno): el proyecto de escala de
la 015 —la rejilla de 1.654 × 1.699 celdas de 1 m (2,81 M) con su terreno de 145 a 215 m, el límite legal y el perímetro, los 20
sectores, los diez perfiles de banco y las máscaras de V01 al día— con el levantamiento de escala (el terreno con **100 marcas y
2.000 zonas candidatas**), las capas de marcas (20 y 100), el levantamiento de **9 acopios de 38.000 m²**, las zonas de
coronación (2 y 10 ha), las huellas de los cuerpos (1, 18, 20 y 100 ha), los **10.000 datos de espesor** sueltos y las secciones
(líneas 3D con el espesor en su Z).

- RNF-016-01 (:class:`DetectTest`): detectar con 20 marcas y los candidatos (leer, A1 a A5, escribir), de la primera llamada de
  «Calcular» a «Crear», ≤ 15 s (en ``Z:``, ≤ 30 s, :class:`NetworkDetectTest`); también con las 100.
- RNF-016-02 (:class:`CalculateTest`): una retirada (y «como plataforma»), un contrafuerte de 2 y de 10 ha, un cuerpo apoyado
  «sobre una base» con 10.000 datos sueltos de 100 ha y con secciones de 20 y de 100 ha, de «Calcular» a «Crear», ≤ 10 s (en
  ``Z:``, ≤ 20 s, :class:`NetworkCalculateTest`).
- RNF-016-03 (cada prueba de las dos de arriba): cada llamada del hilo de Blender de «Calcular» (cada ``next`` de los pasos del
  dominio con el presupuesto de la interfaz, 0,05 s), en CPU del proceso, ≤ 0,2 s. Las órdenes reales, dentro de Blender
  (``perf_stockpiles.py``).
- RNF-016-04 (:meth:`DetectTest.test_c_memory` y :meth:`CalculateTest.test_z_memory`): el pico de memoria adicional
  (``tracemalloc``, con la de numpy) ≤ 1,5 GB.
- RNF-016-07 (:class:`DiskTest`): lo que guarda en el proyecto una detección de 9 acopios y 38.000 m² ≤ 2 MiB, una retirada, un
  contrafuerte o un cuerpo «sobre una base» ≤ 17 MiB, una revisión con 20 ≤ 0,35 GiB y un cuerpo «bajo un techo» (sus datos
  dispersos) ≤ 2 MiB, con 1, 18 y 100 ha. **MiB y GiB son de 2^20 y 2^30 bytes.** Las que la medida **no cumple** (el cuerpo de
  100 ha «sobre una base» y «bajo un techo», y el de 18 ha «bajo un techo» por un 3 %) **fijan el hueco** con ``assertRaises``
  (la prueba pasa mientras el hueco esté y se pone roja cuando se cierre: ``expectedFailure`` no es verde, TST-07) y su cifra
  impresa dice «NO SE CUMPLE»: el presupuesto es el de la spec, que decide Samuel (``tasks.md``, «Para Samuel», 3), no esta
  prueba. **El hueco está acotado** (T49, E-2 de la verificación única): ``assertRaises`` solo dice «supera el presupuesto» y
  pasaría con cualquier tamaño (de 21 a 200 MiB seguiría en verde), así que cada una de esas pruebas afirma, además, un **techo
  medido** (:data:`BODY_GAP_CEILING_BYTES`, :data:`ROOF_GAP_CEILING_BYTES`: lo medido más ≈ 5 %): que el cuerpo empeore también
  la pone roja. Si Samuel decide subir el presupuesto, la afirmación pasa a la normal con la cifra nueva y el techo se quita.
- RNF-016-02 con secciones muy separadas (:meth:`CalculateTest.test_i_body_with_8_wide_sections_100_ha_is_over_the_budget_and_warns`, T49, E-4): **no se
  cumple** (11,3 s de «Calcular» a «Crear», frente a 10 s) y la prueba lo fija **con su aviso** (``des.body_sections_large``, T44) y
  un techo de tiempo (≤ 15 s), sin pretender cumplir el RNF: que el hueco quede escrito en una prueba y no solo en la prosa.

RNF-012-02 con la base de los acopios (la verificación de la 012 con una banda más por final) lo mide ``tests/rendimiento/res/
test_compliance_perf.py`` (T31): no se repite aquí. Esc a mitad de cada cálculo (RNF-016-05) y lo que hace Geoblender en cada
llamada con las órdenes reales (RNF-016-03), dentro de Blender (``perf_stockpiles.py``).
"""

from __future__ import annotations

import gc
import statistics
import unittest
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any, ClassVar

from tests.support import design_perf as dperf
from tests.support import entity_perf as ep
from tests.support import gis_perf, network
from tests.support import stockpile_perf as sp
from tests.support import stockpile_scale as scale
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.resources import requires

design_model = import_geoblender("design.model")
entity_store = import_geoblender("design.entity_store")
steps = import_geoblender("design.steps")
thickness = import_geoblender("design.thickness")

SLOW_NOTICE = "des.body_sections_large"  # T44: el aviso del coste del TIN

DETECT_BUDGET_S = 15.0  # RNF-016-01, en disco local
DETECT_NETWORK_BUDGET_S = 30.0  # RNF-016-01 en Z:
CALCULATE_BUDGET_S = 10.0  # RNF-016-02, en disco local
CALCULATE_NETWORK_BUDGET_S = 20.0  # RNF-016-02 en Z:
CALL_BUDGET_S = 0.2  # RNF-016-03: cada llamada del hilo de Blender, en CPU
MEMORY_BUDGET_BYTES = int(1.5 * 1024**3)  # RNF-016-04: 1,5 GB
MIB = 1024**2
DETECTION_BUDGET_BYTES = 2 * MIB  # RNF-016-07: una detección de 9 acopios y 38.000 m²
ENTITY_BUDGET_BYTES = 17 * MIB  # RNF-016-07: una retirada, un contrafuerte o un cuerpo «sobre una base»
REVISION_BUDGET_BYTES = int(0.35 * 1024**3)  # RNF-016-07: una revisión con 20 de ellos
ROOF_BUDGET_BYTES = 2 * MIB  # RNF-016-07: un cuerpo «bajo un techo» (sus datos dispersos)
BODY_GAP_CEILING_BYTES = 22 * MIB
"""El techo **medido** del hueco del cuerpo «sobre una base» de 100 ha (T49, E-2): 21,09 a 21,11 MiB medidos (la superficie entera,
≈ 16,4 MiB, más el espesor disperso, más las tablas) más un 4 %: más que esto es que el cuerpo ha empeorado, no el hueco de siempre."""
ROOF_GAP_CEILING_BYTES = {"18": int(2.2 * MIB), "100": int(11.5 * MIB)}
"""Los techos **medidos** del hueco del cuerpo «bajo un techo» (T49, E-2; sus datos dispersos): 18 ha, 2,06 MiB medidos (el
presupuesto es de 2) y 100 ha, 10,60 MiB; con un 7 % y un 8 % más (≈ 0,11 MiB por hectárea)."""
WIDE_SECTIONS_BUDGET_S = 15.0
"""El techo de tiempo del cuerpo con 8 secciones a 200 m (T49, E-4): 11,3 s medidos (10,09 s calculados): el RNF-016-02 (10 s) **no
se cumple** en ese caso y esta cifra no lo relaja: fija el hueco con un techo para que empeorar ponga la prueba roja."""
RUNS = 5  # como la 013 a la 015 (su spec §5): mediana de 5
NETWORK_RUNS = 3  # en Z: cada ejecución escribe superficies de 17 MiB: mediana de 3
CHAIN = 20  # las entidades de la revisión de RNF-016-07
MACHINE = gis_perf.MACHINE
number = gis_perf.number
count = gis_perf.count
seconds_of = gis_perf.median_line


def mib(value: float) -> str:
    """Bytes en MiB de 2^20 (con coma decimal)."""
    return number(value / MIB, 2)


def median(found: list[sp.Calculated], what: Callable[[sp.Calculated], float]) -> float:
    return statistics.median(what(item) for item in found)


class NetworkProject:
    """El proyecto de escala en una subcarpeta temporal de la carpeta de pruebas de la red (``Z:``), borrada al terminar, con los
    datos de usuario en disco local (``tests.support.network``: con ``GEOBLENDER_NET_TEST_DIR``, a mano; sin ella, se omite; nunca
    la de los expedientes de clientes)."""

    WHERE = "con el proyecto en la carpeta de pruebas de la red"

    @classmethod
    def make_project(cls) -> Any:
        stack = ExitStack()
        cls.addClassCleanup(stack.close)  # type: ignore[attr-defined]
        remote = stack.enter_context(network.net_tmp("gb-016-t37-"))
        local = stack.enter_context(project_tmp("gb-016-u-"))
        return stack.enter_context(sp.scale_project(folder=remote, userdata=local / "u"))


class ScaleCase(unittest.TestCase):
    """Un proyecto de escala por clase (disco local), con lo que miden todas: repetir ``cycle`` con un nombre nuevo."""

    BUDGET_S = DETECT_BUDGET_S
    RUNS = RUNS
    WHERE = "proyecto en disco local"
    data: ClassVar[Any]

    @classmethod
    def make_project(cls) -> Any:
        return cls.enterClassContext(sp.scale_project())

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = cls.make_project()

    def repeat(self, make: Callable[[], sp.Calculated]) -> list[sp.Calculated]:
        """:data:`RUNS` ejecuciones seguidas de ``make`` (con la basura recogida antes de cada una), después de una que calienta la
        caché de lectura y no cuenta."""
        make()
        found = []
        for _ in range(self.RUNS):
            gc.collect()
            found.append(make())
        return found

    def calls_line(self, found: list[sp.Calculated]) -> str:
        """Las llamadas de «Calcular» de ``found``: cuántas y la más larga, en CPU y en pared (ayuda: no es una prueba)."""
        worst = max(found, key=lambda item: item.calls.longest_cpu_s)
        return (f"llamadas de «Calcular» (presupuesto de {number(0.05, 2)} s): {worst.calls.count} en la última, la más larga de "
                f"todas {number(max(item.calls.longest_s for item in found) * 1000, 0)} ms de pared y "
                f"{number(max(item.calls.longest_cpu_s for item in found) * 1000, 0)} ms de CPU (presupuesto "
                f"{number(CALL_BUDGET_S * 1000, 0)} ms de CPU)")


# --- RNF-016-01, RNF-016-04: detectar -------------------------------------------------------------------------


class DetectTest(ScaleCase):
    """RNF-016-01 y RNF-016-04 con el proyecto de escala (2,81 M celdas, 100 marcas, 2.000 zonas candidatas): cada ejecución
    detecta con un nombre nuevo (el proyecto guarda una detección más, sin descartar: de cada una no parte ninguna entidad)."""

    def detect(self, layer: str = sp.MARKS_20_LAYER, surface: str = sp.SURVEY) -> sp.Calculated:
        """«Calcular» y «Crear» una detección de las marcas de ``layer`` con los candidatos."""
        self.data.clock.advance(minutes=1)
        made = sp.calculate(self.data, steps.stockpile_run, sp.detect_request(ep.fresh_name("Detección"), layer, surface=surface))
        self.data.clock.advance(minutes=1)
        return made

    def line(self, found: list[sp.Calculated], marks: int) -> str:
        last = found[-1].calculation.outcome
        total = [item.total_s for item in found]
        return (f"detectar con {marks} marcas (los candidatos sin marca, {count(len(last.candidates.items))} que pasan los "
                f"filtros) sobre {count(dperf.CELLS)} celdas de 1 m, de «Calcular» (leer la superficie y las marcas, A1 a A5) a "
                f"«Crear» (escribir los datos dispersos y las tablas; {self.WHERE}; {MACHINE}): {seconds_of(total)}; «Calcular» "
                f"{number(median(found, lambda item: item.calculate_s), 2)} s y «Crear» "
                f"{number(median(found, lambda item: item.create_s), 2)} s de mediana; {count(len(last.stockpiles))} acopios "
                f"formados y {count(len(last.rejected))} marcas rechazadas; presupuesto {number(self.BUDGET_S, 0)} s")

    def test_a_detect_20_marks(self) -> None:
        """RNF-016-01, RNF-016-03: detectar con 20 marcas y los candidatos sobre 2,81 M celdas, de la primera llamada de «Calcular»
        (leer la superficie y las marcas, la apertura morfológica, el plano, la huella y los candidatos) a «Crear» (los datos
        dispersos y las tablas, en una transacción), en ≤ 15 s (mediana de 5; la primera no cuenta); cada llamada de «Calcular» ≤
        0,2 s de CPU."""
        found = self.repeat(self.detect)
        gis_perf.report(f"RNF-016-01: {self.line(found, sp.MARKS)}")
        gis_perf.report(f"RNF-016-03: detectar con 20 marcas, {self.calls_line(found)}")
        self.assertGreater(len(found[-1].calculation.outcome.stockpiles), 10, "casi ninguna marca da un acopio: no mide nada")
        self.assertGreater(len(found[-1].calculation.outcome.candidates.items), 0, "ningún candidato: no mide nada")
        self.assertLessEqual(statistics.median(item.total_s for item in found), self.BUDGET_S)
        self.assertLessEqual(max(item.calls.longest_cpu_s for item in found), CALL_BUDGET_S)

    def test_b_detect_100_marks(self) -> None:
        """RNF-016-01: lo mismo con las 100 marcas de la escala (el plan 016 §7.1 las pide; la spec, 20), con el mismo
        presupuesto."""
        found = self.repeat(lambda: self.detect(sp.MARKS_100_LAYER))
        gis_perf.report(f"RNF-016-01: {self.line(found, 100)}")
        gis_perf.report(f"RNF-016-03: detectar con 100 marcas, {self.calls_line(found)}")
        self.assertLessEqual(statistics.median(item.total_s for item in found), self.BUDGET_S)
        self.assertLessEqual(max(item.calls.longest_cpu_s for item in found), CALL_BUDGET_S)

    def test_c_memory(self) -> None:
        """RNF-016-04: el pico de memoria adicional (``tracemalloc``, con la de numpy) de detectar con 20 y con 100 marcas, de
        «Calcular» a «Crear», ≤ 1,5 GB."""
        self.detect()  # sin caché de lectura
        peaks = {marks: gis_perf.peak_bytes(lambda layer=layer: self.detect(layer))
                 for marks, layer in ((sp.MARKS, sp.MARKS_20_LAYER), (100, sp.MARKS_100_LAYER))}
        gis_perf.report(
            f"RNF-016-04: pico de memoria adicional (tracemalloc, con la de numpy) de detectar con 20 marcas y los candidatos "
            f"sobre {count(dperf.CELLS)} celdas de 1 m, de «Calcular» a «Crear» ({MACHINE}): {number(peaks[20] / MIB, 0)} MiB; "
            f"con 100 marcas: {number(peaks[100] / MIB, 0)} MiB; presupuesto {number(MEMORY_BUDGET_BYTES / MIB, 0)} MiB")
        for marks, peak in peaks.items():
            self.assertLessEqual(peak, MEMORY_BUDGET_BYTES, f"{marks} marcas")


# --- RNF-016-02, RNF-016-03, RNF-016-04: retirar, el contrafuerte y el cuerpo -------------------------------------


class CalculateTest(ScaleCase):
    """RNF-016-02, RNF-016-03 y RNF-016-04 con el proyecto de escala y una detección de las 100 marcas (``STK-001``): cada
    ejecución calcula, crea y **descarta** su entidad (de cada superficie parte una sola) con un nombre nuevo, y encadena lo que
    la orden encadena (``after_entity_change``), medido aparte."""

    BUDGET_S = CALCULATE_BUDGET_S
    detection: ClassVar[Any]
    biggest: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.data.clock.advance(minutes=1)
        cls.detection = sp.calculate(cls.data, steps.stockpile_run, sp.detect_request("Acopios", sp.MARKS_100_LAYER))
        cls.data.clock.advance(minutes=1)
        found = cls.detection.calculation.outcome.stockpiles
        cls.biggest = max(found, key=lambda item: item.volume_m3).key

    def request_line(self, what: str, found: list[sp.Calculated], extra: str = "") -> str:
        total = [item.total_s for item in found]
        return (f"{what} sobre {count(dperf.CELLS)} celdas de 1 m, de «Calcular» a «Crear» (escribir la superficie y las tablas; "
                f"{self.WHERE}; {MACHINE}): {seconds_of(total)}; «Calcular» "
                f"{number(median(found, lambda item: item.calculate_s), 2)} s y «Crear» "
                f"{number(median(found, lambda item: item.create_s), 2)} s de mediana{extra}; lo que encadena la orden "
                f"({number(median(found, lambda item: item.chain_s), 2)} s: la declaración, las máscaras y la capa de entidades) no "
                f"cuenta; presupuesto {number(self.BUDGET_S, 0)} s")

    def check(self, what: str, found: list[sp.Calculated], extra: str = "") -> None:
        """Imprime las cifras de ``what`` (tiempo y llamadas) y las compara con su presupuesto (ayuda: no es una prueba)."""
        gis_perf.report(f"RNF-016-02: {self.request_line(what, found, extra)}")
        gis_perf.report(f"RNF-016-03: {what}, {self.calls_line(found)}")
        self.assertLessEqual(statistics.median(item.total_s for item in found), self.BUDGET_S)
        self.assertLessEqual(max(item.calls.longest_cpu_s for item in found), CALL_BUDGET_S)

    def removal(self) -> sp.Calculated:
        return sp.cycle(self.data, steps.removal_run, sp.removal_request(
            ep.fresh_name("Retirada"), self.biggest, detection=self.detection.calculation.entity.code))

    def removal_as_platform(self) -> sp.Calculated:
        request = design_model.PlatformRequest.of_stockpile(
            ep.fresh_name("Retirada como plataforma"), f"{self.detection.calculation.entity.code}#{self.biggest}", sp.SURVEY,
            edge_angle_deg=35.0, reach_m=40.0)
        return sp.cycle(self.data, steps.platform_run, request)

    def buttress(self, zone: str) -> sp.Calculated:
        return sp.cycle(self.data, steps.buttress_run, sp.buttress_request(ep.fresh_name("Contrafuerte"), zone, sp.crown_level(zone)))

    def body(self, footprint: str, data_layer: str = sp.POINTS, **changes: Any) -> sp.Calculated:
        return sp.cycle(self.data, steps.body_run, sp.body_request(ep.fresh_name("Cuerpo"), footprint, sense="on_base",
                                                                   data_layer=data_layer, **changes))

    def sections(self, key: str, footprint: str) -> sp.Calculated:
        return self.body(footprint, sp.SECTION_NAMES[key], field="Z", data_from="z")

    def test_a_removal(self) -> None:
        """RNF-016-02: retirar el mayor de los acopios de la detección sobre 2,81 M celdas (A6 a A8: la transición, lo apoyado y
        la pared), de «Calcular» a «Crear» (la superficie entera y las tablas), en ≤ 10 s."""
        found = self.repeat(self.removal)
        outcome = found[-1].calculation.outcome
        self.check(f"retirar el acopio mayor ({number(outcome.removed_m3, 0)} m³ retirados)", found)

    def test_b_removal_as_platform(self) -> None:
        """RNF-016-02, RF-016-16: retirar ese acopio «como plataforma» (la huella como geometría y el borde de la 015, una sola
        operación), en ≤ 10 s."""
        found = self.repeat(self.removal_as_platform)
        self.check("retirar el acopio mayor «como plataforma»", found)

    def test_c_buttress_2_ha(self) -> None:
        """RNF-016-02: un contrafuerte de una zona de 2 ha a +12 m sobre el terreno (A10: la envolvente y el escalonado),
        en ≤ 10 s."""
        found = self.repeat(lambda: self.buttress("Zona de 2 ha"))
        self.check(f"un contrafuerte de 2 ha ({number(found[-1].calculation.outcome.volume_m3, 0)} m³)", found)

    def test_d_buttress_10_ha(self) -> None:
        """RNF-016-02: un contrafuerte de una zona de 10 ha a +20 m sobre el terreno, en ≤ 10 s."""
        found = self.repeat(lambda: self.buttress("Zona de 10 ha"))
        self.check(f"un contrafuerte de 10 ha ({number(found[-1].calculation.outcome.volume_m3, 0)} m³)", found)

    def test_e_body_with_loose_data_100_ha(self) -> None:
        """RNF-016-02: un cuerpo apoyado «sobre una base» de 100 ha con los 10.000 datos de espesor sueltos (A11: triangular,
        rasterizar por bandas y el dato más próximo), en ≤ 10 s."""
        found = self.repeat(lambda: self.body("Cuerpo de 100 ha"))
        self.check("un cuerpo «sobre una base» de 100 ha con 10.000 datos sueltos", found)

    def test_f_body_with_sections_20_ha(self) -> None:
        """RNF-016-02: un cuerpo «sobre una base» de 20 ha con datos de líneas 3D (secciones diagonales a 45°, el peor caso del TIN
        de la T24), en ≤ 10 s."""
        found = self.repeat(lambda: self.sections("20", "Cuerpo de 20 ha"))
        self.check(f"un cuerpo «sobre una base» de 20 ha con {count(found[-1].calculation.outcome.tin_points)} datos en secciones",
                   found)

    def test_g_body_with_sections_100_ha(self) -> None:
        """RNF-016-02: un cuerpo «sobre una base» de 100 ha con 7.500 datos en 10 secciones diagonales a 45°, a 100 m una de otra
        (las de la T24; el plan midió 7.985: el límite que el resumen avisa, P-7), en ≤ 10 s."""
        found = self.repeat(lambda: self.sections("100", "Cuerpo de 100 ha"))
        lines = scale.SECTION_SPECS["100"][2]
        self.check(f"un cuerpo «sobre una base» de 100 ha con {count(found[-1].calculation.outcome.tin_points)} datos en {lines} "
                   f"secciones", found)
        outcome = found[-1].calculation.outcome  # T44: el coste estimado del TIN, por debajo del límite del aviso
        self.assertNotIn(SLOW_NOTICE, [notice.code for notice in outcome.notices])
        gis_perf.report(f"RNF-016-02: ese cuerpo cuesta, estimado por las cajas del TIN, {number(outcome.estimated_s, 1)} s "
                        f"(aviso a partir de {number(thickness.SLOW_BODY_S, 0)} s)")

    def test_h_body_with_wide_sections_100_ha(self) -> None:
        """RNF-016-02 (T44): las mismas 100 ha con las secciones al doble de separación (200 m de desplazamiento, 141 m entre ellas, 5
        líneas): el TIN tiene más astillas largas y el cálculo sube con la **separación**, no solo con el área ni con el número de datos; el
        aviso del resumen, que antes solo miraba el área, ahora sale por el **coste estimado de las cajas del TIN** (más de 8 s) y la
        causa es la separación de las secciones. **Sin presupuesto**: una sola medida (el RNF-016-02 se cumple si se hace caso del aviso)."""
        made = self.sections("100 anchas", "Cuerpo de 100 ha")
        lines = scale.SECTION_SPECS["100 anchas"][2]
        gis_perf.report(
            f"RNF-016-02: un cuerpo «sobre una base» de 100 ha con {count(made.calculation.outcome.tin_points)} datos en {lines} "
            f"secciones diagonales a 141 m una de otra (una sola medida, sin presupuesto; aviso para Samuel; {self.WHERE}; {MACHINE}): "
            f"«Calcular» {number(made.calculate_s, 2)} s y «Crear» {number(made.create_s, 2)} s; llamada más larga "
            f"{number(made.calls.longest_s * 1000, 0)} ms de pared y {number(made.calls.longest_cpu_s * 1000, 0)} ms de CPU; coste "
            f"estimado por las cajas del TIN {number(made.calculation.outcome.estimated_s, 1)} s")
        warned = [notice for notice in made.calculation.outcome.notices if notice.code == SLOW_NOTICE]
        self.assertEqual(len(warned), 1, "el resumen avisa: el coste estimado pasa del límite")
        self.assertGreater(made.calculation.outcome.estimated_s, thickness.SLOW_BODY_S)

    def test_i_body_with_8_wide_sections_100_ha_is_over_the_budget_and_warns(self) -> None:
        """RNF-016-02 (T49, E-4 de la verificación única): las mismas 100 ha con **8 secciones a 200 m** (4.600 datos: 500, 700, 900, 900,
        700, 500, 300 y 100 por línea; 10,09 s calculados y 11,3 s medidos en la T37 y la T44), el único caso medido por encima de 10 s.
        **No se cumple, y esta prueba fija el hueco sin pretender cumplir el RNF** (hasta ahora estaba solo en la prosa de la T37 y la
        T44): el resumen **avisa** (``des.body_sections_large``, el coste estimado por las cajas del TIN pasa de
        :data:`~design.thickness.SLOW_BODY_S`) y el tiempo de «Calcular» a «Crear» tiene un **techo medido**
        (:data:`WIDE_SECTIONS_BUDGET_S`, ≤ 15 s: que empeore ponga la prueba roja). Una sola medida, sin presupuesto del RNF: se hace en
        local (en ``Z:`` no, como la :meth:`test_h_body_with_wide_sections_100_ha`)."""
        made = self.sections("100 anchas 8", "Cuerpo de 100 ha")
        outcome = made.calculation.outcome
        lines = scale.SECTION_SPECS["100 anchas 8"][2]
        over = made.total_s > self.BUDGET_S
        gis_perf.report(
            f"RNF-016-02: un cuerpo «sobre una base» de 100 ha con {count(outcome.tin_points)} datos en {lines} secciones diagonales a "
            f"200 m de desplazamiento (una sola medida; {self.WHERE}; {MACHINE}): «Calcular» {number(made.calculate_s, 2)} s y «Crear» "
            f"{number(made.create_s, 2)} s, {number(made.total_s, 2)} s en total; presupuesto del RNF {number(self.BUDGET_S, 0)} s"
            f"{': NO SE CUMPLE' if over else ''}; techo de esta prueba {number(WIDE_SECTIONS_BUDGET_S, 0)} s; coste estimado por las cajas "
            f"del TIN {number(outcome.estimated_s, 1)} s (aviso a partir de {number(thickness.SLOW_BODY_S, 0)} s)")
        self.assertEqual(outcome.tin_points, 4_600, "no son las 8 secciones a 200 m de la T37 (4.600 datos)")
        warned = [notice for notice in outcome.notices if notice.code == SLOW_NOTICE]
        self.assertEqual(len(warned), 1, "el resumen avisa de lo lento: el coste estimado pasa del límite")
        self.assertGreater(outcome.estimated_s, thickness.SLOW_BODY_S)
        self.assertLessEqual(made.total_s, WIDE_SECTIONS_BUDGET_S, "el cuerpo con 8 secciones a 200 m ha empeorado: pasó del techo medido")

    def test_z_memory(self) -> None:
        """RNF-016-04: el pico de memoria adicional (``tracemalloc``, con la de numpy) de cada orden —la retirada, «como
        plataforma», los contrafuertes de 2 y 10 ha y los cuerpos de 100 ha con 10.000 datos sueltos y con secciones— de «Calcular»
        a «Crear» ≤ 1,5 GB."""
        cases: dict[str, Callable[[], sp.Calculated]] = {
            "la retirada": self.removal, "la retirada «como plataforma»": self.removal_as_platform,
            "el contrafuerte de 2 ha": lambda: self.buttress("Zona de 2 ha"),
            "el contrafuerte de 10 ha": lambda: self.buttress("Zona de 10 ha"),
            "el cuerpo de 100 ha con 10.000 datos sueltos": lambda: self.body("Cuerpo de 100 ha"),
            "el cuerpo de 100 ha con secciones": lambda: self.sections("100", "Cuerpo de 100 ha")}
        peaks = {}
        for what, make in cases.items():
            make()  # sin caché de lectura
            peaks[what] = gis_perf.peak_bytes(make)
        gis_perf.report(
            f"RNF-016-04: pico de memoria adicional (tracemalloc, con la de numpy) sobre {count(dperf.CELLS)} celdas de 1 m, de "
            f"«Calcular» a «Crear» ({MACHINE}): " + "; ".join(f"{what} {number(peak / MIB, 0)} MiB" for what, peak in peaks.items())
            + f"; presupuesto {number(MEMORY_BUDGET_BYTES / MIB, 0)} MiB")
        for what, peak in peaks.items():
            self.assertLessEqual(peak, MEMORY_BUDGET_BYTES, what)


# --- RNF-016-07: lo que guarda en el proyecto ----------------------------------------------------------------


class DiskTest(ScaleCase):
    """RNF-016-07 con el proyecto de escala: lo que deja en disco cada entidad (su superficie en la rejilla entera comprimida o
    sus datos dispersos, más lo que crece la base del proyecto con sus tablas, operaciones, parámetros y cifras)."""

    detection: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.data.clock.advance(minutes=1)
        cls.detection = sp.calculate(cls.data, steps.stockpile_run, sp.detect_request("Acopios", sp.MARKS_100_LAYER))
        cls.data.clock.advance(minutes=1)

    def once(self, run: Any, request: Any, **options: Any) -> sp.Calculated:
        """Calcula y crea ``request`` una vez (**sin** descartar: lo que mide es lo que queda)."""
        self.data.clock.advance(minutes=1)
        made = sp.calculate(self.data, run, request, **options)
        self.data.clock.advance(minutes=1)
        return made

    def drop(self, *made: sp.Calculated) -> None:
        """Descarta las entidades de ``made`` (de cada superficie parte una sola) con lo que encadena la orden, para que las
        siguientes pruebas puedan partir de ella."""
        for item in reversed(made):
            self.data.clock.advance(minutes=1)
            ep.finish(entity_store.discard_entity_steps(self.data.project, self.data.v1.uid, item.calculation.entity.code,
                                                        reason="Medición de rendimiento"))

    def test_a_nine_stockpiles(self) -> None:
        """RNF-016-07: una detección de 9 acopios y 38.000 m² de huella (sus datos dispersos —la base, el espesor, el terreno sin
        acopios y la superficie con que se detectó— y sus tablas) ≤ 2 MiB."""
        made = self.once(steps.stockpile_run, sp.detect_request("Nueve acopios", sp.MARKS_NINE_LAYER, surface=sp.SURVEY_NINE))
        outcome = made.calculation.outcome
        area = sum(item.area_m2 for item in outcome.stockpiles)
        gis_perf.report(
            f"RNF-016-07: lo que guarda en el proyecto una detección de {count(len(outcome.stockpiles))} acopios y "
            f"{count(round(area))} m² de huella (datos dispersos {mib(made.raster_bytes)} MiB y tablas {mib(made.db_bytes)} MiB; "
            f"{MACHINE}): {mib(made.disk_bytes)} MiB; presupuesto {mib(DETECTION_BUDGET_BYTES)} MiB")
        self.assertEqual(len(outcome.stockpiles), 9)
        self.assertAlmostEqual(area, 38_000.0, delta=760.0, msg="no son los 38.000 m² de huella de la spec (± 2 %)")
        self.assertLessEqual(made.disk_bytes, DETECTION_BUDGET_BYTES)

    def test_b_removal_buttress_and_body(self) -> None:
        """RNF-016-07: una retirada, un contrafuerte de 10 ha ≤ 17 MiB (su superficie entera, comprimida, más sus tablas)."""
        removal = self.once(steps.removal_run, sp.removal_request(
            "Retirada", max(self.detection.calculation.outcome.stockpiles, key=lambda item: item.volume_m3).key,
            detection=self.detection.calculation.entity.code))
        buttress = self.once(steps.buttress_run, sp.buttress_request("Contrafuerte", "Zona de 10 ha", sp.crown_level("Zona de 10 ha")))
        self.drop(removal, buttress)
        gis_perf.report(
            f"RNF-016-07: lo que guarda en el proyecto una retirada ({mib(removal.raster_bytes)} MiB de superficie y "
            f"{mib(removal.db_bytes)} MiB de tablas) y un contrafuerte de 10 ha ({mib(buttress.raster_bytes)} MiB y "
            f"{mib(buttress.db_bytes)} MiB; la superficie entera de {count(dperf.CELLS)} celdas de 1 m, comprimida; {MACHINE}): "
            f"{mib(removal.disk_bytes)} MiB y {mib(buttress.disk_bytes)} MiB; presupuesto {mib(ENTITY_BUDGET_BYTES)} MiB cada una")
        self.assertLessEqual(removal.disk_bytes, ENTITY_BUDGET_BYTES, "una retirada")
        self.assertLessEqual(buttress.disk_bytes, ENTITY_BUDGET_BYTES, "un contrafuerte de 10 ha")

    def test_c_twenty_entities(self) -> None:
        """RNF-016-07: una revisión con 20 retiradas en cadena (cada una de la superficie de la anterior, con lo que encadena la
        orden: la capa de entidades) ≤ 0,35 GiB, cada una ≤ 17 MiB."""
        stockpiles = sorted(self.detection.calculation.outcome.stockpiles, key=lambda item: -item.volume_m3)[:CHAIN]
        start, sizes = sp.SURVEY, []
        for index, item in enumerate(stockpiles, start=1):
            made = self.once(steps.removal_run, sp.removal_request(
                f"Retirada {index}", item.key, start=start, detection=self.detection.calculation.entity.code), chain=True)
            start = f"entity:{made.calculation.entity.code}"
            sizes.append(made.disk_bytes)
        total = sum(sizes)
        gis_perf.report(
            f"RNF-016-07: lo que guardan {len(sizes)} retiradas en cadena (superficie entera de {count(dperf.CELLS)} celdas de 1 m "
            f"comprimida más sus tablas; {MACHINE}): la mayor {mib(max(sizes))} MiB, la mediana {mib(statistics.median(sizes))} MiB, "
            f"presupuesto {mib(ENTITY_BUDGET_BYTES)} MiB; la revisión con las {len(sizes)}: {number(total / 1024**3, 3)} GiB "
            f"({mib(total)} MiB), presupuesto {number(REVISION_BUDGET_BYTES / 1024**3, 2)} GiB")
        self.assertEqual(len(sizes), CHAIN)
        self.assertLessEqual(total, REVISION_BUDGET_BYTES, "la revisión con 20")
        self.assertLessEqual(max(sizes), ENTITY_BUDGET_BYTES, "una entidad")

    def test_d_body_on_a_base_100_ha_is_over_the_budget(self) -> None:
        """RNF-016-07: un cuerpo «sobre una base» de 100 ha con 10.000 datos (la superficie entera comprimida, más el espesor
        disperso y las tablas) ≤ 17 MiB. **No se cumple, y esta prueba fija el hueco** (``assertRaises``: se pone roja cuando se
        cierre; ``expectedFailure`` no es verde, TST-07): la superficie entera sola ya mide ≈ 16,4 MiB y el espesor disperso de 100 ha,
        ≈ 5 MiB; lo decide Samuel (``tasks.md``, «Para Samuel», 3). **Acotado** (T49, E-2): además, ≤ :data:`BODY_GAP_CEILING_BYTES` (el
        hueco medido, 21,1 MiB, más un 4 %): ``assertRaises`` solo dice que pasa de 17 MiB y no vería que el cuerpo guarde 40 MiB."""
        made = self.once(steps.body_run, sp.body_request("Cuerpo sobre una base", "Cuerpo de 100 ha", sense="on_base"))
        self.drop(made)
        gis_perf.report(
            f"RNF-016-07: lo que guarda un cuerpo «sobre una base» de 100 ha con 10.000 datos sueltos (superficie entera y espesor "
            f"disperso {mib(made.raster_bytes)} MiB y tablas {mib(made.db_bytes)} MiB; {MACHINE}): {mib(made.disk_bytes)} MiB; "
            f"presupuesto {mib(ENTITY_BUDGET_BYTES)} MiB: NO SE CUMPLE; techo del hueco {mib(BODY_GAP_CEILING_BYTES)} MiB")
        with self.assertRaises(AssertionError, msg="el cuerpo de 100 ha «sobre una base» ya cabe en 17 MiB: quite el hueco"):
            self.assertLessEqual(made.disk_bytes, ENTITY_BUDGET_BYTES)
        self.assertLessEqual(made.disk_bytes, BODY_GAP_CEILING_BYTES,
                             f"el cuerpo de 100 ha «sobre una base» pasó de los {mib(BODY_GAP_CEILING_BYTES)} MiB medidos del hueco: ha empeorado")

    def roof(self, footprint: str) -> sp.Calculated:
        """Un cuerpo «bajo un techo» de ``footprint`` con los datos sueltos (la superficie conocida es el terreno)."""
        return self.once(steps.body_run, sp.body_request(ep.fresh_name("Cuerpo bajo un techo"), footprint, sense="under_roof"))

    def check_roof(self, footprint: str, hectares: str, *, gap: bool = False) -> None:
        """Mide el cuerpo «bajo un techo» de ``footprint`` y lo compara con el presupuesto; con ``gap``, **fija** que no lo cumple **y
        que no pasa del techo medido** (:data:`ROOF_GAP_CEILING_BYTES`: T49, E-2)."""
        made = self.roof(footprint)
        ceiling = ROOF_GAP_CEILING_BYTES.get(hectares)
        self.assertTrue(not gap or ceiling is not None, f"el hueco de {hectares} ha no tiene su techo medido")
        gis_perf.report(
            f"RNF-016-07: lo que guarda un cuerpo «bajo un techo» de {hectares} ha (sus datos dispersos: el espesor y la base, "
            f"{mib(made.raster_bytes)} MiB; las tablas, {mib(made.db_bytes)} MiB más; {MACHINE}): presupuesto "
            f"{mib(ROOF_BUDGET_BYTES)} MiB de datos dispersos"
            + (f": NO SE CUMPLE; techo del hueco {mib(ceiling or 0)} MiB" if gap else ""))
        if gap:
            with self.assertRaises(AssertionError, msg=f"el cuerpo «bajo un techo» de {hectares} ha ya cabe en 2 MiB: quite el hueco"):
                self.assertLessEqual(made.raster_bytes, ROOF_BUDGET_BYTES)
            self.assertLessEqual(made.raster_bytes, ceiling or 0,
                                 f"el cuerpo «bajo un techo» de {hectares} ha pasó de los {mib(ceiling or 0)} MiB medidos del hueco: ha empeorado")
        else:
            self.assertLessEqual(made.raster_bytes, ROOF_BUDGET_BYTES)

    def test_e_body_under_a_roof_1_ha(self) -> None:
        """RNF-016-07: un cuerpo «bajo un techo» de 1 ha (sus datos dispersos) ≤ 2 MiB."""
        self.check_roof("Cuerpo de 1 ha", "1")

    def test_f_body_under_a_roof_18_ha_is_over_the_budget_by_3_percent(self) -> None:
        """RNF-016-07: un cuerpo «bajo un techo» de 18 ha (sus datos dispersos) ≤ 2 MiB. La T25 midió ≈ 0,11 MiB por hectárea (el
        espesor y la base, float64 de un ruido que se comprime poco): 2 MiB son ≈ 18 ha. **No se cumple, por un 3 %, y esta prueba
        fija el hueco** (``assertRaises``)."""
        self.check_roof("Cuerpo de 18 ha", "18", gap=True)

    def test_g_body_under_a_roof_100_ha_is_over_the_budget(self) -> None:
        """RNF-016-07: un cuerpo «bajo un techo» de 100 ha con 10.000 datos (sus datos dispersos) ≤ 2 MiB. **No se cumple, y esta
        prueba fija el hueco** (``assertRaises``): ≈ 10,6 MiB; lo decide Samuel (``tasks.md``, «Para Samuel», 3)."""
        self.check_roof("Cuerpo de 100 ha", "100", gap=True)


# --- En la red ------------------------------------------------------------------------------------------------------
#
# **Ojo**: en el PC de referencia la variable GEOBLENDER_NET_TEST_DIR está definida en el usuario y este módulo, lanzado tal
# cual, también corre estas clases (``docs/trampas.md`` §7); para medir solo en local, sin ella: ``Remove-Item
# Env:GEOBLENDER_NET_TEST_DIR`` (PowerShell) o ``env -u GEOBLENDER_NET_TEST_DIR …`` (Git Bash).


@requires(network.NET, network.NET_HINT)
class NetworkDetectTest(NetworkProject, DetectTest):
    """RNF-016-01 en ``Z:``: detectar con 20 y con 100 marcas con el proyecto en la red, en ≤ 30 s (mediana de
    :data:`NETWORK_RUNS`)."""

    BUDGET_S = DETECT_NETWORK_BUDGET_S
    RUNS = NETWORK_RUNS
    test_c_memory = None  # type: ignore[assignment]  # la memoria no depende de dónde esté el proyecto


@requires(network.NET, network.NET_HINT)
class NetworkCalculateTest(NetworkProject, CalculateTest):
    """RNF-016-02 en ``Z:``: la retirada, los contrafuertes y los cuerpos con el proyecto en la red, en ≤ 20 s (mediana de
    :data:`NETWORK_RUNS`; cada ejecución escribe en la red una superficie de 17 MiB)."""

    BUDGET_S = CALCULATE_NETWORK_BUDGET_S
    RUNS = NETWORK_RUNS
    test_h_body_with_wide_sections_100_ha = None  # type: ignore[assignment]  # una sola medida, sin presupuesto: se hace en local
    test_i_body_with_8_wide_sections_100_ha_is_over_the_budget_and_warns = None  # type: ignore[assignment]  # ídem, con su techo local
    test_z_memory = None  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
