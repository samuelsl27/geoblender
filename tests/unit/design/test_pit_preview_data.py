# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de la vista previa de una corta, **sin GPU y sin proyecto** (spec 018, T29; HU-018-1, HU-018-4; RF-018-32, RF-015-26, RNF-018-08; plan 018 §5.5; comprobación manual M3): con el
proyecto, en ``milestone_pit_preview_data``; lo que se dibuja con ellos, en ``tests/blender/test_pit_preview.py``.

- **Qué se pide** (:class:`PitAskTest`): ``PitAsk`` es de la corta que se prepara (su petición) o de una de la versión (su código), y lo que ya hizo «Calcular» es solo de la primera.
- **Antes de calcular** (:class:`BeforeCalculatingTest`): de un ``PitJob`` salen los polígonos de fondo o de límite, los sectores, **una flecha por rango de la roseta** con la dirección de su cara (el
  azimut, en el medio del rango, medido desde el norte hacia el este), el punto de inicio de las rampas, las zonas sin rampa y los bancos fijados.
- **Tras calcular** (:class:`AfterCalculatingTest`): de un ``PitOutcome`` salen las polilíneas por banco y por tipo, la línea de cielo, el eje de cada rampa y los hallazgos con su lugar.
- **La vista** (:class:`PitPreviewTest`): ``drawable``, las líneas del resumen en los dos idiomas y los mensajes nuevos.
- **El coste** (:class:`PitScaleTest`): preparar lo que se dibuja de 60 bancos de 2 polilíneas de 2.000 vértices (RNF-018-08) no pasa de 1 s.
"""

from __future__ import annotations

import time
import unittest
from typing import Any

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender
from tests.unit.design import test_pit_bench_ramp as bra
from tests.unit.design import test_pit_bench_up as up

pit_model = import_geoblender("design.pit_model")
pit_preview = import_geoblender("design.pit_preview")
pit_rose = import_geoblender("design.pit_rose")
preview = import_geoblender("design.preview")
access = import_geoblender("gis.masks.access")
messages = import_geoblender("design.messages")

SECTOR_CODE = "S-1"


def rose(*ranges: tuple[float, float, float, float]) -> tuple[Any, ...]:
    return tuple(pit_rose.RoseRange(*item) for item in ranges)


FOUR = rose((0.0, 90.0, 60.0, 6.0), (90.0, 180.0, 55.0, 6.0), (180.0, 270.0, 50.0, 8.0), (270.0, 360.0, 45.0, 8.0))


def line(kind: str, bench: int, z: float, size: float = 10.0, *, closed: bool = True) -> Any:
    ring = np.array([[0.0, 0.0, z], [size, 0.0, z], [size, size, z], [0.0, size, z]]) + [pd.absolute(np.array([[0.0, 0.0]]))[0, 0], pd.absolute(np.array([[0.0, 0.0]]))[0, 1], 0.0]
    return pit_model.Polyline(kind, bench, ring, closed=closed)


def outcome(**changes: Any) -> Any:
    window = (slice(0, 4), slice(0, 5))
    values: dict[str, Any] = {"name": "Corta 1", "code": "PIT-001", "mode": "up", "window": window, "surface": np.zeros((4, 5)), "footprint": np.zeros((4, 5), bool)}
    values.update(changes)
    return pit_model.PitOutcome(**values)


class PitAskTest(unittest.TestCase):
    """RF-018-32: lo que se pide es de una sola cosa."""

    def test_a_it_is_the_pit_that_is_prepared_or_one_of_the_version(self) -> None:
        """RF-018-32: la petición **o** el código; con los dos o con ninguno, ``ValueError``; lo que hizo «Calcular» es de la petición; ``by`` es ``bench`` o ``type``."""
        request = up.request()
        self.assertEqual(preview.PitAsk(request=request).by, "bench")
        self.assertEqual(preview.PitAsk(code="PIT-001", by="type").by, "type")
        for bad in ({}, {"request": request, "code": "PIT-001"}, {"code": "PIT-001", "prepared": object()}, {"code": "PIT-001", "outcome": object()}, {"request": request, "by": "color"}):
            with self.assertRaises(ValueError, msg=str(bad)):
                preview.PitAsk(**bad)
        with self.assertRaises(TypeError):
            preview.pit_preview_steps(object(), request, "uid")  # type: ignore[arg-type]


class BeforeCalculatingTest(unittest.TestCase):
    """RF-018-32: lo que se dibuja antes de calcular sale de lo leído."""

    def test_a_the_polygons_the_sectors_and_the_zones_come_from_the_job(self) -> None:
        """RF-018-32: los polígonos de origen, los de cada sector, las zonas sin rampa y los bancos fijados, tal cual (absolutos, float64)."""
        zone = (((np.array([[10.0, 10.0], [20.0, 10.0], [20.0, 20.0]]) + [pd.absolute(np.array([[0.0, 0.0]]))[0, 0], pd.absolute(np.array([[0.0, 0.0]]))[0, 1]]),),)
        sector = pit_model.PitSector(SECTOR_CODE, "Sector norte", zone)
        fixed = pit_model.FixedBench("Fijado", line("foot", 2, 145.0).vertices, bench=2, closed=True)
        found = pit_preview.job_parts(up.job(sectors=(sector,), noramp=zone, fixed=(fixed,), rose=FOUR))
        (source,) = found["sources"]
        self.assertEqual((source.name, source.level_m), ("fondo", pd.FLOOR_Z_M))
        np.testing.assert_array_equal(source.rings[0], pd.absolute(pd.circle_ring()))
        self.assertEqual([(item.name, len(item.rings)) for item in found["sectors"]], [("Sector norte", 1)])
        self.assertEqual(len(found["noramp"]), 1)
        np.testing.assert_array_equal(found["noramp"][0], zone[0][0])
        (kept,) = found["fixed"]
        self.assertEqual((kept.kind, kept.bench, kept.closed), ("fixed", 2, True))
        np.testing.assert_array_equal(kept.vertices, fixed.vertices)

    def test_b_one_arrow_per_range_of_the_rose_in_the_middle_of_it(self) -> None:
        """RF-018-32, RF-018-07: una flecha por rango, con el azimut del **medio** del rango (hacia donde baja la cara, desde el norte hacia el este), su desde, hasta, α y B, anclada en el
        centro del polígono y de un largo positivo que cabe en él; sin roseta, ninguna."""
        found = pit_preview.rose_arrows(up.job(rose=FOUR))
        self.assertEqual([item.azimuth_deg for item in found], [45.0, 135.0, 225.0, 315.0])
        self.assertEqual([(item.from_deg, item.to_deg, item.face_deg, item.berm_m) for item in found],
                         [(0.0, 90.0, 60.0, 6.0), (90.0, 180.0, 55.0, 6.0), (180.0, 270.0, 50.0, 8.0), (270.0, 360.0, 45.0, 8.0)])
        centre = pd.absolute(np.array([pd.CENTER]))[0]
        for item in found:
            self.assertEqual(item.sector, "")
            np.testing.assert_allclose((item.x, item.y), centre, atol=0.5)
            self.assertTrue(0.0 < item.length_m <= pd.CIRCLE_RADIUS_M)
        self.assertEqual(pit_preview.rose_arrows(up.job()), ())

    def test_c_a_sector_with_its_own_rose_gets_its_arrows_at_its_own_place(self) -> None:
        """RF-018-32, RF-018-06: un sector con roseta propia lleva sus flechas, ancladas en **su** polígono y con su nombre; uno sin ella usa la de la corta y no repite flechas."""
        base = pd.absolute(np.array([[0.0, 0.0]]))[0]
        ring = np.array([[10.0, 10.0], [30.0, 10.0], [30.0, 30.0], [10.0, 30.0]]) + base
        own = pit_model.PitSector(SECTOR_CODE, "Sector norte", ((ring,),), rose=rose((0.0, 180.0, 60.0, 6.0), (180.0, 360.0, 45.0, 6.0)))
        plain = pit_model.PitSector("S-2", "Sector sur", ((ring + 100.0,),))
        found = pit_preview.rose_arrows(up.job(sectors=(own, plain), rose=FOUR))
        mine = [item for item in found if item.sector == "Sector norte"]
        self.assertEqual([item.azimuth_deg for item in mine], [90.0, 270.0])
        np.testing.assert_allclose([(item.x, item.y) for item in mine], [(20.0 + base[0], 20.0 + base[1])] * 2, atol=1e-9)
        self.assertEqual(len([item for item in found if item.sector == ""]), 4)
        self.assertEqual([item for item in found if item.sector == "Sector sur"], [])

    def test_d_the_start_of_a_ramp_is_a_point_only_when_the_layer_gave_one(self) -> None:
        """RF-018-32, RF-018-15: el inicio de una rampa que sale de un punto de su capa se dibuja con su nombre; el que parte de un banco no tiene lugar antes de calcular."""
        base = pd.absolute(np.array([[0.0, 0.0]]))[0]
        at_point = pit_model.RampStart("rampa", point=(float(base[0] + 50.0), float(base[1] + 60.0)), layer="gis_fea_inicios", name="Inicio A")
        found = pit_preview.job_parts(bra.spiral_job(at_point))
        (start,) = found["starts"]
        self.assertEqual((start.ramp, start.name, start.x, start.y), ("rampa", "Inicio A", base[0] + 50.0, base[1] + 60.0))
        self.assertEqual(pit_preview.job_parts(bra.spiral_job())["starts"], ())


class AfterCalculatingTest(unittest.TestCase):
    """RF-018-32: lo que se dibuja tras calcular sale de lo que dejó «Calcular»."""

    def test_a_the_polylines_the_skyline_the_ramps_and_the_findings(self) -> None:
        """RF-018-32, RF-018-26: las polilíneas en su orden registrado con su tipo y su banco, la línea de cielo, el eje de cada rampa con su longitud y sus pendientes y cada hallazgo con su lugar."""
        base = pd.absolute(np.array([[0.0, 0.0]]))[0]
        axis = np.array([[base[0], base[1], 125.0], [base[0] + 30.0, base[1], 128.0], [base[0] + 60.0, base[1], 131.0]])
        sky = np.array([[base[0], base[1], 170.0], [base[0] + 5.0, base[1] + 5.0, 171.0]])
        finding = pit_model.Finding("berm_width", 3.0, 6.0, (base[0] + 1.0, base[1] + 2.0), bench=2)
        done = outcome(polylines=(line("foot", 1, 125.0), line("crest", 1, 135.0), line("foot", 2, 135.0)), skyline=(sky,),
                       ramps=(pit_model.RampPath("rampa", 1, axis, np.full(3, 5.0)),), findings=(finding,), benches=(), stop="surface")
        found = pit_preview.outcome_parts(done)
        self.assertEqual([(item.kind, item.bench) for item in found["polylines"]], [("foot", 1), ("crest", 1), ("foot", 2)])
        self.assertEqual([item.kind for item in found["skyline"]], ["sky"])
        np.testing.assert_array_equal(found["skyline"][0].vertices, sky)
        (ramp,) = found["ramps"]
        self.assertEqual((ramp.code, ramp.bench), ("rampa", 1))
        self.assertAlmostEqual(ramp.length_m, 60.0)
        self.assertAlmostEqual(ramp.gradient_mean_pct, 10.0)
        self.assertEqual(found["findings"], (finding,))
        self.assertEqual(found["stop"], "surface")
        self.assertEqual(found["bench_numbers"], (1, 2))

    def test_b_nothing_calculated_gives_nothing(self) -> None:
        """RF-018-32: un resultado sin polilíneas ni rampas ni hallazgos da todo vacío."""
        found = pit_preview.outcome_parts(outcome())
        self.assertEqual((found["polylines"], found["skyline"], found["ramps"], found["findings"], found["bench_numbers"]), ((), (), (), (), ()))


class PitPreviewTest(unittest.TestCase):
    """RF-018-32: la vista con su resumen."""

    def test_a_drawable_and_the_lines_of_the_summary_in_both_languages(self) -> None:
        """RF-018-32, RF-015-26: con máscaras que no están al día o con el rechazo de «Calcular» no hay dibujo, solo el aviso; antes y tras calcular hay dibujo y el resumen se dice en español y en inglés."""
        empty = preview.PitPreview("Corta 1", "", "V01", access.MaskState.MISSING, notices=(preview.Notice("des.preview_entity_masks_missing", {"version": "V01", "entity": "Corta 1"}),))
        self.assertFalse(empty.drawable)
        self.assertTrue(empty.lines("es")[0][1])  # un aviso en alerta
        before = preview.PitPreview("Corta 1", "PIT-001", "V01", access.MaskState.CURRENT, sources=(preview.PitShape("fondo", (pd.circle_ring(),), 125.0),),
                                    notices=(preview.Notice("des.preview_pit_before", {"entity": "Corta 1", "code": "PIT-001", "version": "V01", "surface": "terreno", "sources": 1, "arrows": 4,
                                                                                        "starts": 0, "noramp": 0, "fixed": 0}),))
        self.assertTrue(before.drawable)
        self.assertFalse(before.calculated)
        self.assertIn("Vista previa de «Corta 1» (PIT-001) en V01", before.lines("es")[0][0])
        self.assertIn("Preview of «Corta 1» (PIT-001) in V01", before.lines("en")[0][0])
        after = preview.PitPreview("Corta 1", "PIT-001", "V01", access.MaskState.CURRENT, calculated=True, polylines=(preview.PitLine("foot", 1, line("foot", 1, 125.0).vertices, True),),
                                   notices=(preview.Notice("des.preview_pit_calculated", {"entity": "Corta 1", "code": "PIT-001", "version": "V01", "benches": 1, "cut": 12345.6, "ramps": 0,
                                                                                           "findings": 2, "by": "bench"}),))
        self.assertTrue(after.drawable)
        self.assertIn("12.346", after.lines("es")[0][0].replace(" ", "."), "el corte, a metros cúbicos enteros")
        one = preview.Notice("des.preview_pit_calculated", {"entity": "C", "code": "PIT-001", "version": "V01", "benches": 1, "cut": 1.0, "ramps": 1, "findings": 1, "by": "type"})
        many = preview.Notice("des.preview_pit_calculated", {"entity": "C", "code": "PIT-001", "version": "V01", "benches": 5, "cut": 1.0, "ramps": 1, "findings": 1, "by": "type"})
        self.assertNotEqual(one.text("es"), many.text("es"), "1 banco y 5 bancos se dicen distinto")

    def test_b_every_new_message_is_in_the_catalog_with_its_two_languages(self) -> None:
        """RF-018-32: ``des.preview_pit_before``, ``_calculated`` y ``_stored`` son notas con su inglés y su español."""
        for code in ("des.preview_pit_before", "des.preview_pit_calculated", "des.preview_pit_stored"):
            found = messages.lookup(code)
            self.assertEqual(found.severity, "note")
            self.assertTrue(found.msgid and found.es)


class PitCrowdingTest(unittest.TestCase):
    """RF-018-32, RF-018-31 (T40c; H3-2): el texto y las etiquetas de la vista previa de lo calculado no tapan la vista."""

    def test_a_the_text_of_a_calculated_preview_lists_a_few_warnings_per_code_and_says_how_many_more(self) -> None:
        """RF-018-32: 21 avisos de un mismo código no llenan la vista: la nota, 3 avisos y «… y 18 avisos como éste»; los de otros códigos, a su cuenta."""
        note = preview.Notice("des.preview_pit_calculated", {"entity": "C", "code": "PIT-001", "version": "V01", "benches": 5, "cut": 1.0, "ramps": 1, "findings": 21, "by": "bench"})
        radius = tuple(preview.Notice("des.pit_ramp_radius_reduced", {"entity": "Espiral", "bench": number, "vertex": 2, "fitted": 15.0, "radius": 20.0, "x": 1.0, "y": 2.0}) for number in range(21))
        shown = preview.PitPreview("C", "PIT-001", "V01", access.MaskState.CURRENT, calculated=True, notices=(note, *radius)).lines("es")
        self.assertEqual(len(shown), 5)
        self.assertFalse(shown[0][1])
        self.assertIn("18 avisos como éste", shown[-1][0])
        self.assertEqual(sum("des.pit_ramp" in text for text, _alert in shown), 0, "ninguna clave interna")

    def test_b_the_findings_that_get_a_name_are_one_per_place_and_at_most_a_few(self) -> None:
        """RF-018-32: 21 hallazgos, 7 en un mismo lugar, se nombran como mucho ``PIT_FINDING_LABELS`` y ninguno en el lugar de otro; la cruz de todos se dibuja igual."""
        found = [pit_model.Finding("ramp", 15.0, 20.0, (700_000.0 + 3.0 * (number // 7) * 50.0, 4_400_000.0 + 10.0 * (number % 3)), 1, "m", "Espiral: des.pit_ramp_radius_reduced")
                 for number in range(21)]
        named = preview.finding_labels(found)
        self.assertLessEqual(len(named), preview.PIT_FINDING_LABELS)
        self.assertEqual(len({(round(item.place[0]), round(item.place[1])) for item in named}), len(named))
        self.assertEqual(preview.finding_labels(found[:2]), preview.finding_labels(found[:2]))
        self.assertEqual(len(preview.finding_labels([])), 0)


class PitScaleTest(unittest.TestCase):
    """RNF-018-08: el coste de preparar lo que se dibuja de una corta grande."""

    def test_a_sixty_benches_of_two_polylines_are_prepared_within_a_second(self) -> None:
        """RNF-018-08: 60 bancos de 2 polilíneas de 2.000 vértices (pie y cresta) se convierten en lo que se dibuja en ≤ 1 s, y cada una es una vista de lo dado."""
        rings = pd.scale_rings(60, 60 * 2 * 2_000)
        lines = []
        for number in range(60):
            for offset, kind in enumerate(("foot", "crest")):
                ring = rings[2 * number + offset]
                z = np.full(len(ring), 100.0 + 10.0 * number)
                lines.append(pit_model.Polyline(kind, number + 1, np.column_stack([ring + 700_000.0, z]), closed=True))
        done = outcome(polylines=tuple(lines))
        started = time.perf_counter()
        found = pit_preview.outcome_parts(done)
        spent = time.perf_counter() - started
        self.assertEqual(len(found["polylines"]), 120)
        self.assertLess(spent, 1.0)


if __name__ == "__main__":
    unittest.main()
