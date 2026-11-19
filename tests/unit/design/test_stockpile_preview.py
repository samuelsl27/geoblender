# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que dibuja la vista previa de las marcas de los acopios y de la zona de coronación del contrafuerte, **antes de calcular** y
sin escribir nada (spec 016, T32; HU-016-1, HU-016-3; RF-016-23, RF-015-26; plan 016 §5.5; comprobación manual M4).

El dominio de la vista previa (``design.preview.stockpile_preview_steps`` y ``buttress_preview_steps``), sin Blender: lo que el dibujo
de ``bl.draw.entity`` pinta y dice (sus lotes y su leyenda se prueban en ``tests/blender/test_stockpile_preview.py``). Sobre la cantera
de los acopios (2 m, 200 × 200 celdas), con sus cinco marcas (cuadrados de 20 × 20 m: **10 × 10 celdas**; el Acopio 3 con su margen de
6 m y las demás con el de la detección, 10 m) y la zona de coronación «Contrafuerte del acopio 3» (22 × 22 m: 121 celdas). Las cuentas
se hacen a mano o por fuerza bruta, no con el código:

- **Las marcas** (:class:`StockpilePreviewTest`): el contorno de cada marca son sus celdas (las de centro dentro de su polígono,
  ``mark_cells``), el de su **marca ampliada** es la dilatación de esas celdas con un disco de su margen (por fuerza bruta), sin
  contorno de más si el margen es 0; el ámbito, el código y el nombre son los de la detección que se calcularía; nada se escribe;
  lo que rechazaría la preparación (capa, campos, márgenes, marcas solapadas…) es el aviso en lugar del dibujo, con el mismo texto.
- **La zona de coronación** (:class:`ButtressPreviewTest`): sus 121 celdas, su contorno, la zona con su resguardo (fuerza bruta,
  distancia euclídea entre centros) y lo que declarará; sin resguardo, solo la zona y el aviso de que falta; los rechazos de la
  capa y de la geometría, con el mismo texto que «Calcular».
"""

from __future__ import annotations

import math
import unittest
from collections.abc import Iterator
from typing import Any

import numpy as np

from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.unit.design import test_buttress_operation as bop
from tests.unit.design import test_stockpile_prepare as tp

core_model = import_geoblender("core.constraints.model")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
preview = import_geoblender("design.preview")
stockpile_store = import_geoblender("design.stockpile_store")
supported_store = import_geoblender("design.supported_store")

DesignError = messages.DesignError
GRID = tp.GRID
CELL_M = GRID.dx
"""El lado de las celdas de la cantera (2 m)."""
MARK_CELLS = 100
"""Las celdas de cada marca (10 × 10)."""
DEFAULT_MARGIN_M = 10.0
"""El margen de la detección (D-3: ADOPTADO «sin confirmar»), el de las marcas sin campo ``margen``."""
EMPTY_ZONE_LAYER = "gis_fea_coronacion_sin_celdas"
"""Una capa con una zona más pequeña que una celda (ningún centro dentro): sin zona de coronación."""
STEP_BUDGET_S = 0.05


def finish(steps: Iterator[Any]) -> tuple[Any, int]:
    """El resultado del último ``Progress`` de unos pasos y cuántos dieron."""
    result, count = None, 0
    for step in steps:
        count += 1
        result = step.result or result
    return result, count


def ring_area(rings: tuple[np.ndarray, ...]) -> float:
    """El área (m²) que encierran unos anillos ABSOLUTOS por la fórmula del cordón: el exterior antihorario suma y sus huecos, horarios,
    restan; el resultado es el área rellena."""
    total = 0.0
    for ring in rings:
        x, y = np.asarray(ring, dtype=np.float64)[:, 0], np.asarray(ring, dtype=np.float64)[:, 1]
        total += 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    return total


def box_of(rings: tuple[np.ndarray, ...]) -> tuple[float, float, float, float]:
    """La caja ``(oeste, sur, este, norte)`` (m absolutos) de unos anillos."""
    points = np.concatenate([np.asarray(ring, dtype=np.float64) for ring in rings])
    return (float(points[:, 0].min()), float(points[:, 1].min()), float(points[:, 0].max()), float(points[:, 1].max()))


def cells_of(box: tuple[float, float, float, float]) -> set[tuple[int, int]]:
    """A mano: las celdas ``(fila, columna)`` con el centro dentro de la caja local ``box`` (un bucle, no el código)."""
    return {(int(index) // GRID.ncols, int(index) % GRID.ncols) for index in tp.hand_cells(box)}


def disc_by_force(cells: set[tuple[int, int]], radius_cells: float) -> set[tuple[int, int]]:
    """A mano, por fuerza bruta: las celdas a una distancia entre centros de ``radius_cells`` celdas o menos de alguna de ``cells`` (un
    disco exacto, de lado a lado de las filas: lo que es dilatar con un disco)."""
    reach = int(math.floor(radius_cells))
    offsets = [(di, dj) for di in range(-reach, reach + 1) for dj in range(-reach, reach + 1) if di * di + dj * dj <= radius_cells ** 2]
    return {(i + di, j + dj) for i, j in cells for di, dj in offsets
            if 0 <= i + di < GRID.nrows and 0 <= j + dj < GRID.ncols}


def centre_of(cells: set[tuple[int, int]]) -> tuple[float, float]:
    """El centro absoluto de la caja de ``cells`` (m)."""
    rows, cols = [i for i, _j in cells], [j for _i, j in cells]
    x = GRID.west + (min(cols) + max(cols) + 1) / 2.0 * GRID.dx
    y = GRID.north - (min(rows) + max(rows) + 1) / 2.0 * GRID.dy
    return x, y


class StockpilePreviewTest(bop.ButtressCase):
    """RF-016-23, RF-015-26: la vista previa de las marcas de la capa de la cantera, con su margen, sin escribir nada."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        defects = {layer.name: layer for layer in tp.defect_layers()}
        for name in (tp.LAYER_OVERLAP, tp.LAYER_NEGATIVE, tp.LAYER_BLANK):
            sdata.write_layer(cls.project, cls.clock, defects[name])
        cls.clock.advance(minutes=1)

    def preview_of(self, asked: Any, version: Any = "default", **options: Any) -> Any:
        """La vista previa de ``asked`` en V01 (``None``: sin versión), sin escribir nada: lo que da el último paso."""
        which = self.v1.uid if version == "default" else version
        before = self.state()
        found, count = finish(preview.stockpile_preview_steps(self.project, asked, which, budget_s=STEP_BUDGET_S, **options))
        self.assertEqual(self.state(), before, "la vista previa no escribe nada")
        self.assertGreaterEqual(count, 1)
        return found

    # --- Las marcas -----------------------------------------------------------------------------------------------

    def test_a_each_mark_is_drawn_with_its_cells_and_enlarged_by_its_margin(self) -> None:
        """RF-016-23, RF-016-02: el contorno de cada marca son sus 100 celdas (las de centro dentro de su polígono) y el de su marca
        ampliada, la dilatación de esas celdas con un disco de su margen (a mano, por fuerza bruta): 10 m por defecto y 6 m el Acopio 3; con
        su centro, su material y sin base (no se lee el campo). La detección es **del proyecto** (el levantamiento lo es) con el código
        que tendría, ``STK-001``; no escribe nada."""
        found = self.preview_of(tp.request())
        self.assertEqual((found.name, found.code, found.scope, found.version, found.surface, found.layer),
                         ("Acopios", "STK-001", stockpile_store.PROJECT, "", sdata.SURVEY_DATASET, sdata.MARKS_LAYER))
        self.assertIsNone(found.refusal)
        self.assertTrue(found.drawable)
        self.assertEqual((found.cell_m, found.margin_m, found.candidates), (CELL_M, DEFAULT_MARGIN_M, False))
        self.assertEqual([mark.key for mark in found.marks], list(tp.NAMES))
        for mark in found.marks:
            with self.subTest(mark=mark.key):
                own = cells_of(tp.BOXES[mark.key])
                margin = 6.0 if mark.key == "Acopio 3" else DEFAULT_MARGIN_M
                grown = disc_by_force(own, margin / CELL_M)
                self.assertEqual((mark.cells, mark.area_m2, mark.enlarged_cells), (MARK_CELLS, MARK_CELLS * CELL_M ** 2, len(grown)))
                self.assertEqual((mark.margin_m, mark.own_margin), (margin, mark.key == "Acopio 3"))
                self.assertEqual(ring_area(mark.rings), len(own) * CELL_M ** 2)
                self.assertEqual(ring_area(mark.enlarged), len(grown) * CELL_M ** 2)
                west, south, east, north = box_of(mark.rings)
                self.assertEqual((east - west, north - south), (20.0, 20.0))
                rows, cols = [i for i, _j in grown], [j for _i, j in grown]
                self.assertEqual(box_of(mark.enlarged), (GRID.west + min(cols) * CELL_M, GRID.north - (max(rows) + 1) * CELL_M,
                                                         GRID.west + (max(cols) + 1) * CELL_M, GRID.north - min(rows) * CELL_M))
                self.assertEqual((mark.x, mark.y), centre_of(own))
                self.assertEqual(mark.material, {"Acopio 1": "mineral", "Acopio 2": "mineral", "Acopio 3": "estéril",
                                                 "Acopio 4": "estéril", "Acopio 5": "mineral"}[mark.key])
                self.assertIsNone(mark.base)
        for ring in found.marks[0].rings + found.marks[0].enlarged:  # cerrados, de celda en celda
            self.assertTrue(np.array_equal(ring[0], ring[-1]))
            self.assertTrue(np.all(np.mod((ring[:, 0] - GRID.west) / CELL_M, 1.0) == 0.0))

    def test_b_the_scope_and_the_code_are_the_ones_the_detection_would_have(self) -> None:
        """RF-016-23, RF-016-02, D-15: sobre una superficie **de una versión** la detección es de la versión (su código, ``V01``, el
        ``STK-001`` de su registro) y pide la versión; sobre una del proyecto, del proyecto, con o sin versión activa. Una superficie de
        versión sin versión es el aviso de siempre (``core.version_required``), no un error, y no dibuja nada."""
        by_version = self.preview_of(tp.request(surface=tp.VERSION_SURFACE))
        self.assertEqual((by_version.scope, by_version.version, by_version.code, by_version.surface),
                         (stockpile_store.VERSION, "V01", "STK-001", tp.VERSION_SURFACE))
        self.assertEqual(len(by_version.marks), 5)
        alone = self.preview_of(tp.request(), version=None)
        self.assertEqual((alone.scope, alone.version, alone.code), (stockpile_store.PROJECT, "", "STK-001"))
        self.assertEqual([mark.cells for mark in alone.marks], [MARK_CELLS] * 5)
        none = self.preview_of(tp.request(surface=tp.VERSION_SURFACE), version=None)
        self.assertEqual((none.marks, none.drawable, none.refusal.code), ((), False, "core.version_required"))
        self.assertEqual(none.lines("es")[0], (none.refusal.message, True))  # un error de ``core``: su mensaje, en español

    def test_c_a_margin_of_zero_has_no_enlarged_outline(self) -> None:
        """RF-016-23: con margen 0 la marca ampliada es la marca: no se dibuja dos veces (``enlarged`` vacío, y sus celdas, las de la
        marca); el margen sale del diálogo (``margin_m``), que manda sobre el de por defecto pero no sobre el del campo del Acopio 3."""
        found = self.preview_of(tp.request(margin_m=0.0))
        self.assertEqual(found.margin_m, 0.0)
        for mark in found.marks:
            with self.subTest(mark=mark.key):
                if mark.key == "Acopio 3":
                    self.assertEqual((mark.margin_m, mark.own_margin), (6.0, True))
                    self.assertNotEqual(mark.enlarged, ())
                else:
                    self.assertEqual((mark.margin_m, mark.enlarged, mark.enlarged_cells), (0.0, (), MARK_CELLS))

    def test_d_what_the_preparation_would_refuse_is_the_warning_instead_of_the_drawing(self) -> None:
        """RF-016-23, RF-015-08: lo que rechazaría la preparación de la detección —una marca sin su campo, un margen negativo, dos marcas
        solapadas nombrando las dos, un campo de la capa que no está— es el aviso de la vista previa **en lugar del dibujo** y con
        el mismo código y el mismo texto, en los dos idiomas; el rechazo no escribe nada."""
        cases = {
            "solape": (tp.request(layer=tp.LAYER_OVERLAP, marks={"margin_field": None, "material_field": None}),
                       "des.stockpile_marks_overlap"),
            "margen negativo": (tp.request(layer=tp.LAYER_NEGATIVE, marks={"material_field": None}), "des.entity_param_range"),
            "nombre": (tp.request(layer=tp.LAYER_BLANK, marks={"name_field": "etiqueta", "margin_field": None, "material_field": None}),
                       "des.entity_field_value"),
            "campo": (tp.request(marks={"margin_field": "no_existe"}), "des.stockpile_layer_field"),
            "áreas": (tp.request(candidates=True, min_area_m2=500.0, max_area_m2=100.0), "des.entity_param_range"),
        }
        for label, (asked, code) in cases.items():
            with self.subTest(caso=label):
                found = self.preview_of(asked)
                with self.assertRaises(DesignError) as raised:
                    self.prepare(asked, version=None)
                expected = raised.exception
                self.assertEqual((found.marks, found.drawable), ((), False))
                self.assertEqual(found.refusal.code, expected.code)
                if code is not None:
                    self.assertEqual(expected.code, code)
                for language in ("es", "en"):
                    self.assertEqual(found.lines(language)[0], (expected.text_in(language), True))
                    self.assertNotIn("{", found.lines(language)[0][0])
        overlap = self.preview_of(cases["solape"][0]).refusal
        self.assertEqual({overlap.values["mark"], overlap.values["other"]}, {"A", "B"})

    def test_e_a_repeated_name_and_the_candidates_are_said(self) -> None:
        """RF-016-23: un nombre que ya tiene una detección del proyecto se rechaza como al calcular (``des.stockpile_name_repeated_project``);
        pidiendo los candidatos, una nota dice que se buscarán en el perímetro de actuación (no se dibujan: no tienen marca) y,
        sin marcas pero con candidatos, la vista previa sale sin dibujo y lo dice sin error."""
        found = self.preview_of(tp.request(candidates=True))
        self.assertTrue(found.candidates)
        self.assertIn("des.preview_stockpile_candidates", [notice.code for notice in found.notices])
        plain = self.preview_of(tp.request())
        self.assertNotIn("des.preview_stockpile_candidates", [notice.code for notice in plain.notices])
        self.assertEqual(len(found.marks), 5)

    def test_f_the_summary_says_what_will_be_detected_in_both_languages(self) -> None:
        """RF-016-23: las notas de la vista previa dicen la detección (su nombre, su código, el ámbito, cuántas marcas y su área, la
        superficie y el margen) en español y en inglés, con la coma decimal del español, sin ningún marcador sin llenar y sin avisos."""
        found = self.preview_of(tp.request())
        header = found.lines("es")[0][0]
        self.assertIn("«Acopios» (STK-001)", header)
        self.assertIn("5 marcas", header)
        self.assertRegex(header, r"2.000 m²")  # 5 × 400 m², con el espacio fino de miles del español
        self.assertIn(sdata.SURVEY_DATASET, header)
        self.assertIn("10,0 m", header)
        english = found.lines("en")[0][0]
        self.assertIn("5 marks", english)
        self.assertIn("2,000 m²", english)
        self.assertIn("10.0 m", english)
        self.assertFalse(any(alert for _text, alert in found.lines("es")))
        for language in ("es", "en"):
            for text, _alert in found.lines(language):
                self.assertNotIn("{", text)
        in_version = self.preview_of(tp.request(surface=tp.VERSION_SURFACE))
        self.assertIn("V01", in_version.lines("es")[0][0])

    def test_g_it_is_made_by_steps_and_closing_it_halfway_leaves_nothing(self) -> None:
        """RF-016-23, RNF-016-03: se prepara por pasos (cada marca, uno como mucho): hay varios; cerrar los pasos a mitad no deja nada y
        solo el último lleva el resultado."""
        steps = preview.stockpile_preview_steps(self.project, tp.request(), self.v1.uid, budget_s=0.0)
        before = self.state()
        seen = [step.result is None for step in steps]
        self.assertGreaterEqual(len(seen), 6)
        self.assertEqual(seen[:-1], [True] * (len(seen) - 1))
        halfway = preview.stockpile_preview_steps(self.project, tp.request(), self.v1.uid, budget_s=0.0)
        next(halfway)
        next(halfway)
        halfway.close()
        self.assertEqual(self.state(), before)

    # --- Lo que pide quien la lanza -------------------------------------------------------------------------------

    def test_h_only_the_marks_and_nothing_else_of_the_preparation_is_read(self) -> None:
        """RF-016-23, RNF-016-03: la vista previa **no calcula ni lee la superficie entera**: nada de ``read_surface`` ni de las máscaras
        (la detección de la versión las compila al calcular, y la vista previa no escribe); sigue siendo la misma de siempre con las
        máscaras de V01 obsoletas."""
        from unittest import mock

        with mock.patch.object(stockpile_store, "read_surface_steps", side_effect=AssertionError("lee la superficie")), \
                mock.patch.object(stockpile_store, "_loaded_masks", side_effect=AssertionError("carga las máscaras")):
            found = self.preview_of(tp.request(surface=tp.VERSION_SURFACE))
        self.assertEqual(len(found.marks), 5)


class ButtressPreviewTest(bop.ButtressCase):
    """RF-016-23, RF-015-26: la vista previa de la zona de coronación del contrafuerte con su resguardo, sin escribir nada."""

    ZONE_CELLS = 121
    """La zona «Contrafuerte del acopio 3» de 22 × 22 m (11 × 11 celdas de 2 m)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        ring = tp.cfx.absolute([(100.2, 100.2), (100.8, 100.2), (100.8, 100.8), (100.2, 100.8), (100.2, 100.2)])
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(EMPTY_ZONE_LAYER, "polygon", (((ring,),),), ("Mínima",), {}))
        cls.clock.advance(minutes=1)

    def preview_of(self, asked: Any, version: Any = "default") -> Any:
        """La vista previa de ``asked`` en V01, sin escribir nada."""
        which = self.v1.uid if version == "default" else version
        before = self.state()
        found, count = finish(preview.buttress_preview_steps(self.project, asked, which, budget_s=STEP_BUDGET_S))
        self.assertEqual(self.state(), before, "la vista previa no escribe nada")
        self.assertGreaterEqual(count, 1)
        return found

    def zone(self) -> set[tuple[int, int]]:
        (zone,) = [item for item in sdata.CROWN_ZONES if item.name == bop.ZONE]
        return cells_of(zone.box)

    def test_a_the_crown_zone_and_its_guard_are_drawn_before_calculating(self) -> None:
        """RF-016-23, RF-016-17, RF-015-10 (P-8, D-1): la zona de coronación son sus 121 celdas (a mano) y su contorno; con el resguardo
        (10 m, **obligatorio** si protege, que es lo por defecto) la zona que declarará «sin corte» son las celdas a ≤ 10 m de la zona
        entre centros de celda (por fuerza bruta); con la cota y el perfil que se piden, el código que tendría ``BTR-001`` y su partida; el
        centro de la zona para su nombre. No escribe nada."""
        found = self.preview_of(bop.asked())
        zone = self.zone()
        self.assertIsNone(found.refusal)
        self.assertTrue(found.drawable)
        self.assertEqual((found.name, found.code, found.version, found.start_surface, found.layer, found.feature),
                         (bop.BUTTRESS, "BTR-001", "V01", bop.SURVEY, sdata.CROWN_LAYER, bop.ZONE))
        self.assertEqual((found.crown_cells, found.crown_area_m2, found.cell_m), (self.ZONE_CELLS, self.ZONE_CELLS * 4.0, CELL_M))
        self.assertEqual(len(zone), self.ZONE_CELLS)
        self.assertEqual(ring_area(found.crown_rings), self.ZONE_CELLS * 4.0)
        self.assertEqual(box_of(found.crown_rings)[2] - box_of(found.crown_rings)[0], 22.0)
        self.assertEqual((found.crown_m, found.profile, found.protects, found.guard_m), (bop.CROWN_M, bop.PROFILE, True, bop.GUARD_M))
        self.assertEqual((found.x, found.y), centre_of(zone))
        guarded = {(i, j) for i in range(GRID.nrows) for j in range(GRID.ncols)
                   if min(math.hypot((i - a) * CELL_M, (j - b) * CELL_M) for a, b in zone) <= bop.GUARD_M + 1e-9}
        self.assertEqual((found.zone_cells, found.zone_area_m2), (len(guarded), len(guarded) * 4.0))
        self.assertEqual(ring_area(found.zone), len(guarded) * 4.0)
        self.assertEqual(found.declares, core_model.ConstraintType.NO_CUT)
        self.assertEqual([notice.severity for notice in found.notices], ["note"] * len(found.notices))

    def test_b_without_protecting_there_is_no_guard_and_without_a_guard_it_is_said(self) -> None:
        """RF-016-23, RF-015-10, D-19: sin proteger no hay zona con resguardo ni restricción declarada (se dice); protegiendo (por defecto)
        sin resguardo —que no tiene valor por defecto— se dibuja solo la zona de coronación y se avisa de que falta; sin cota de coronación
        también se dibuja, y se dice que aún no está elegida."""
        loose = self.preview_of(bop.asked(protect=False, guard=None))
        self.assertEqual((loose.protects, loose.zone, loose.zone_cells, loose.declares, loose.guard_m), (False, (), 0, None, None))
        self.assertEqual(loose.crown_cells, self.ZONE_CELLS)
        self.assertIn("des.preview_buttress_declares_none", [notice.code for notice in loose.notices])
        missing = self.preview_of(bop.asked(guard=None))
        self.assertEqual((missing.protects, missing.zone, missing.declares), (True, (), None))
        self.assertEqual(missing.crown_cells, self.ZONE_CELLS)
        warning = [notice for notice in missing.notices if notice.code == "des.preview_buttress_guard_missing"]
        self.assertEqual(len(warning), 1)
        self.assertEqual(warning[0].severity, "warning")
        self.assertTrue(any(alert for _text, alert in missing.lines("es")))
        uncrowned = self.preview_of(bop.asked(crown=None))
        self.assertIsNone(uncrowned.crown_m)
        self.assertEqual(uncrowned.crown_cells, self.ZONE_CELLS)
        self.assertIn("des.preview_buttress_crown_none", [notice.code for notice in uncrowned.notices])

    def test_c_what_calculate_would_refuse_of_the_zone_is_the_warning_instead_of_the_drawing(self) -> None:
        """RF-016-23, RF-015-08: lo que rechaza «Calcular» de la capa y de la zona —que no sea de polígonos, que la geometría no esté, un
        resguardo negativo, una partida que es la superficie de una entidad que no existe— es el aviso de la vista previa **en lugar del
        dibujo**, con el mismo código y el mismo texto en los dos idiomas; una zona sin ninguna celda (más pequeña que una) no es un
        rechazo: no hay nada que dibujar y la vista previa lo dice."""
        cases = {
            "capa de puntos": bop.asked(layer=sdata.THICKNESS_POINTS_LAYER),
            "zona que no está": bop.asked(feature="No existe"),
            "resguardo negativo": bop.asked(guard=-1.0),
            "partida de una entidad sin calcular": bop.asked(start="entity:BTR-009"),
        }
        for label, asked in cases.items():
            with self.subTest(caso=label):
                found = self.preview_of(asked)
                with self.assertRaises(DesignError) as raised:
                    supported_store.prepare_buttress(self.project, asked, version=self.v1.uid, masks=self.masks_v1)
                self.assertEqual((found.crown_rings, found.drawable), ((), False))
                self.assertEqual(found.refusal.code, raised.exception.code, label)
                for language in ("es", "en"):
                    self.assertEqual(found.lines(language)[0], (raised.exception.text_in(language), True))
        empty = self.preview_of(bop.asked(layer=EMPTY_ZONE_LAYER, feature="Mínima"))
        self.assertEqual((empty.crown_cells, empty.crown_rings, empty.drawable, empty.refusal), (0, (), False, None))
        self.assertIn("des.preview_buttress_zone_empty", [notice.code for notice in empty.notices])
        self.assertTrue(any(alert for _text, alert in empty.lines("es")))

    def test_d_the_summary_says_the_zone_the_crown_and_what_it_declares_in_both_languages(self) -> None:
        """RF-016-23: las notas dicen la zona (su geometría y su capa, las celdas y el área), la cota de coronación con su perfil y lo
        que declarará (el resguardo y el área con él), en español y en inglés, sin ningún marcador sin llenar."""
        found = self.preview_of(bop.asked())
        spanish = " | ".join(text for text, _alert in found.lines("es"))
        self.assertIn("«Contrafuerte sobre el acopio 3» (BTR-001)", spanish)
        self.assertIn("121 celdas", spanish)
        self.assertIn("484 m²", spanish.replace(" ", " "))
        self.assertIn(bop.ZONE, spanish)
        self.assertIn("115,00 m", spanish)
        self.assertIn(bop.PROFILE, spanish)
        self.assertIn("resguardo de 10,0 m", spanish)
        english = " | ".join(text for text, _alert in found.lines("en"))
        self.assertIn("121 cells", english)
        self.assertIn("115.00 m", english)
        self.assertIn("guard of 10.0 m", english)
        for language in ("es", "en"):
            for text, _alert in found.lines(language):
                self.assertNotIn("{", text)

    def test_e_it_reads_neither_the_start_surface_nor_the_masks(self) -> None:
        """RF-016-23, RNF-016-03: dibujar la zona no lee la partida ni las máscaras ni el perfil (solo la geometría de la capa y la
        cuadrícula del proyecto): sigue funcionando con las máscaras de V01 sin leer."""
        from unittest import mock

        with mock.patch.object(supported_store, "read_surface_window", side_effect=AssertionError("lee la partida")), \
                mock.patch.object(supported_store, "_profile_values", side_effect=AssertionError("lee el perfil")), \
                mock.patch.object(supported_store.access, "load_masks_steps", side_effect=AssertionError("lee las máscaras"), create=True):
            found = self.preview_of(bop.asked())
        self.assertEqual(found.crown_cells, self.ZONE_CELLS)

    def test_f_it_is_made_by_steps_and_closing_it_halfway_leaves_nothing(self) -> None:
        """RF-016-23: por pasos; cerrar a mitad no deja nada; un código de versión que no existe es un error al avanzar."""
        before = self.state()
        steps = preview.buttress_preview_steps(self.project, bop.asked(), self.v1.uid, budget_s=0.0)
        seen = [step.result is None for step in steps]
        self.assertGreaterEqual(len(seen), 4)
        self.assertEqual(seen[:-1], [True] * (len(seen) - 1))
        halfway = preview.buttress_preview_steps(self.project, bop.asked(), self.v1.uid, budget_s=0.0)
        next(halfway)
        halfway.close()
        self.assertEqual(self.state(), before)
        with self.assertRaises(ValueError):
            finish(preview.buttress_preview_steps(self.project, bop.asked(), "V99", budget_s=STEP_BUDGET_S))


if __name__ == "__main__":
    unittest.main()
