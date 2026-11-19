# SPDX-License-Identifier: GPL-3.0-or-later
"""La verificación por recinto con la base de los acopios, sin proyecto (spec 016, T30; HU-016-2; RF-012-24, RF-012-30,
RF-012-31, RF-012-25; plan 016 §5.4 A12, §5.7 P-10; DIFF-012 §2 y §4).

El «verde» lleva lo que no necesita proyecto (P-13); lo que lo necesita —elegir la base de las detecciones de la cantera de
los acopios, la operación en el proyecto, recalcular, congelar y reproducir— está en ``milestone_compliance_store_stockpile``.
Aquí, ``verify_steps`` sobre una rejilla de 10 × 10 celdas de 1 m, con las superficies en GeoTIFF (el caso de referencia (a) del
diff: terreno a 100 m, un acopio de 4 × 4 celdas hasta 103 m, su base a 100 m) y dos recintos: «r_sin_corte» (sin corte, las
filas 0 a 6, donde está el acopio) y «torre» (intocable, las filas 7 a 9):

- **RF-012-30, RF-012-24**: con la base, la retirada da corte de terreno 0 m³, 48 m³ de acopios y «cumple»; la tabla lleva, de
  cada recinto de terreno, el corte de acopios (``stockpile_cut_m3``) y ``cut_terrain`` como lo que cuenta, y, del final 0, una
  fila por base y otra por detección que no se usó, con su causa; la cifra CALCULADO del corte de acopios solo en las zonas de
  terreno. Una celda por debajo de la base «no cumple». Los demás recintos cuentan todo el movimiento.
- **P-10**: con dos bases que cubren una celda, la menor (a mano: 23 m³ de terreno; solo la A, 27; solo la B, 38).
- **RF-012-31**: una base en otra rejilla se rechaza al llamar como RF-011-03, nombrando la base; la petición, las superficies y
  la selección tienen que casar.
- **Sin base**: la tabla y las cifras de siempre, sin ninguna fila ni cifra de acopios.
- **RF-012-24, RF-012-25**: la selección va en los ajustes (y se lee de ellos), cada base tiene su papel y sus mensajes nombran la
  detección y la causa; lo guardado se lee y congelar da los m³ de corte de terreno.
"""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from types import MappingProxyType
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
writer = import_geoblender("gis.geotiff.writer")
model = import_geoblender("core.constraints.model")
combine = import_geoblender("gis.masks.combine")
zones_mod = import_geoblender("gis.masks.zones")
access = import_geoblender("gis.masks.access")
figures_mod = import_geoblender("core.provenance.figures")
surfaces = import_geoblender("reserves.surfaces")
compliance = import_geoblender("reserves.compliance")
cstore = import_geoblender("reserves.compliance_store")
res_messages = import_geoblender("reserves.messages")

NAN = float("nan")
GRID = gis.Grid(500000.0, 4400010.0, 1.0, 1.0, 10, 10)
"""10 × 10 celdas de 1 m: la fila 0 es la del norte."""
FINE = gis.Grid(500000.0, 4400010.0, 0.5, 0.5, 20, 20)
"""La misma ventana con celdas de 0,5 m: otra rejilla."""
V = compliance.Verdict
C = compliance.Counts
ZONE, TOWER = "r_sin_corte", "torre"
NAME = "Retirada"
USED_TEXT = "Base de acopios: detección STK-001 «Acopios» (mineral)"


def _last(steps: Iterator[Any]) -> Any:
    found = None
    for step in steps:
        if step.result is not None:
            found = step.result
    return found


def _runs(mask: np.ndarray) -> Any:
    rows, cols = np.nonzero(mask)
    return zones_mod.Runs(rows, cols, cols + 1)


def _masks() -> Any:
    """Las máscaras de la rejilla: todo dentro del perímetro y del límite; ``r_sin_corte`` (sin corte, las filas 0 a 6) y
    ``torre`` (intocable, las filas 7 a 9)."""
    classes = np.full(GRID.shape, np.uint16(combine.ClassBit.PERIMETER) | np.uint16(combine.ClassBit.LEGAL),
                      dtype=np.uint16)
    upper = np.zeros(GRID.shape, dtype=bool)
    upper[:7] = True
    zones = {ZONE: _runs(upper), TOWER: _runs(~upper)}
    ctypes = {ZONE: model.ConstraintType.NO_CUT, TOWER: model.ConstraintType.UNTOUCHABLE}
    return access.MaskSet(GRID, "v" * 32, "o" * 32, access.MaskState.CURRENT, (), classes, (), MappingProxyType(zones),
                          MappingProxyType({}), (), MappingProxyType(ctypes))


def _terrain(value: float = 100.0) -> np.ndarray:
    return np.full(GRID.shape, value)


def _start() -> np.ndarray:
    """Terreno a 100 m con un acopio de 4 × 4 celdas (filas y columnas 3 a 6) hasta 103 m."""
    found = _terrain()
    found[3:7, 3:7] = 103.0
    return found


def _base(block: tuple[slice, slice], level: float) -> np.ndarray:
    found = np.full(GRID.shape, NAN)
    found[block] = level
    return found


def _selection(*bases: str, skipped: tuple[Any, ...] = ()) -> Any:
    """La selección de las bases ``bases`` (sus etiquetas de superficie) de la detección ``STK-001`` «Acopios»."""
    found = []
    for position, label in enumerate(bases, start=1):
        item = cstore.StockpileBase("STK-001", "Acopios", "project", "mineral", surfaces.SurfaceRef(dataset=label))
        found.append(cstore.StockpileBase(item.detection, item.name, item.scope, item.material,
                                          surfaces.SurfaceRef(dataset=label, label=f"{item.text()} {position}")))
    return cstore.BaseSelection(tuple(found), skipped)


OTHER = cstore.SkippedDetection("STK-001", "Acopios de V01", "version", "other_surface", "des_stp_levantamiento_de_v01")
STALE = cstore.SkippedDetection("STK-002", "Viejos", "project", "stale", "gis_dtm_levantamiento",
                                "Obsoleto: cambió el umbral de la huella (res.anthropic_presence_m)")


class VerifyStepsWithBaseTest(unittest.TestCase):
    """RF-012-24, RF-012-30, RF-012-31, P-10: ``verify_steps`` con la base de los acopios, en memoria."""

    @classmethod
    def setUpClass(cls) -> None:
        folder = cls.enterClassContext(project_tmp("gb-csb-"))
        pit = _terrain()
        pit[4, 4] = 99.5  # una celda del acopio por debajo de su base
        pit[0, 0] = 99.5  # y otra de fuera del acopio por debajo del terreno
        pit[8, 2] = 98.0  # y un corte en la torre
        five = _start()
        five[3:6, 3:6] = 97.0
        cls.arrays = {
            "start": _start(), "removed": _terrain(), "pit": pit, "five": five,
            "base_a": _base((slice(3, 7), slice(3, 7)), 100.0),
            "two_a": _base((slice(3, 6), slice(3, 6)), 100.0), "two_b": _base((slice(3, 5), slice(3, 5)), 99.0)}
        cls.paths = {}
        for key, values in cls.arrays.items():
            cls.paths[key] = folder / f"{key}.tif"
            writer.write_geotiff(gis.Raster(GRID, values, fx.CRS, fx.VERTICAL), cls.paths[key], profile="project")
        cls.fine = folder / "fine.tif"
        writer.write_geotiff(gis.Raster(FINE, np.full(FINE.shape, 100.0), fx.CRS, fx.VERTICAL), cls.fine,
                             profile="project")
        cls.masks = _masks()

    def source(self, key: str, name: str | None = None) -> Any:
        return surfaces.grid_source(self.paths[key], name=name or key, crs=fx.CRS, vertical=fx.VERTICAL)

    def verify(self, finals: tuple[str, ...], bases: Any = None, *, start: str = "start", band_rows: int = 256,
               sources: dict[str, Any] | None = None) -> Any:
        """``verify_steps`` de ``finals`` (claves de :attr:`arrays`) con la selección ``bases`` (``BaseSelection``; sin ella,
        sin base) sobre el terreno ``start``."""
        selection = cstore.BaseSelection() if bases is None else bases
        request = compliance.ComplianceRequest(
            NAME, surfaces.SurfaceRef(dataset="gis_dtm_inicial", label="Levantamiento"),
            tuple(surfaces.SurfaceRef(dataset=f"gis_dtm_{key}") for key in finals), self.masks, 0.02,
            bases=selection.refs)
        found = {cstore.START_ROLE: self.source(start, "Levantamiento"),
                 **{cstore.final_role(k): self.source(key) for k, key in enumerate(finals, start=1)},
                 **{cstore.base_role(k): self.source(ref.dataset, ref.label)
                    for k, ref in enumerate(selection.refs, start=1)}}
        steps = cstore.verify_steps(request, sources or found, references=(fx.CRS, fx.VERTICAL), selection=selection,
                                    band_rows=band_rows)
        return _last(steps)

    @staticmethod
    def rows(result: Any, *, zone: str = "", final: int | None = None) -> dict[str, Any]:
        """La tabla de ``result`` por cantidad de un recinto (y final): (valor, nota)."""
        return {row[2]: (row[3], row[5]) for row in result.table_rows()
                if row[0] == zone and (final is None or row[1] == final)}

    def test_a_the_removal_complies_and_the_table_names_the_base(self) -> None:
        """RF-012-30, RF-012-24, RF-012-31: con la base de la detección, la retirada (a 100 m) da corte de terreno 0 m³ y 48 m³
        de acopios y «cumple» (también por bandas de 1 y 3 filas); la tabla lleva ese corte de acopios y ``cut_terrain``,
        del final 0 la base que usó y las detecciones que no (con su causa), y las cifras la del corte de acopios solo de
        la zona de terreno; la torre cuenta todo el movimiento y sin fila de acopios."""
        selection = _selection("base_a", skipped=(OTHER, STALE))
        for band_rows in (256, 1, 3):
            with self.subTest(band_rows=band_rows):
                result = self.verify(("removed",), selection, band_rows=band_rows)
                zone = result.finals[0].zone(ZONE)
                self.assertEqual((zone.counts, zone.cut_m3, zone.counted_m3, zone.stockpile_cut_m3, zone.verdict),
                                 (C.CUT_TERRAIN, 48.0, 0.0, 48.0, V.COMPLIES))
        self.assertEqual(result.fails, (False,))
        found = self.rows(result, zone=ZONE, final=1)
        self.assertEqual((found["counted_m3"], found["stockpile_cut_m3"], found["cut_m3"]),
                         ((0.0, "cut_terrain"), (48.0, None), (48.0, None)))
        self.assertEqual(found["verdict"], (None, "complies"))
        self.assertNotIn("stockpile_cut_m3", self.rows(result, zone=TOWER, final=1))
        self.assertEqual(self.rows(result, zone=TOWER, final=1)["counted_m3"], (0.0, "any"))
        general = self.rows(result)
        self.assertEqual(general["stockpile_base"], (None, f"{USED_TEXT}"))
        skipped = [row[5] for row in result.table_rows() if row[2] == "stockpile_skipped"]
        self.assertEqual(len(skipped), 2)
        self.assertIn("Acopios de V01", skipped[0])
        self.assertIn("des_stp_levantamiento_de_v01", skipped[0])
        self.assertIn("Levantamiento", skipped[0])
        self.assertIn("obsoleta", skipped[1])
        self.assertIn("res.anthropic_presence_m", skipped[1])
        scopes = {(spec.key, figures_mod.scope_json(spec.scope)): spec.value for spec in result.figures}
        stock = {key: value for key, value in scopes.items() if key[0] == "res.check_stockpile_cut_m3"}
        self.assertEqual(stock, {("res.check_stockpile_cut_m3",
                                  figures_mod.scope_json({"check": NAME, "final": 1, "zone": ZONE})): 48.0})
        self.assertTrue(all(np.isfinite(value) for value in scopes.values()))
        self.assertEqual(result.selection, selection)
        self.assertEqual(result.start_name, "Levantamiento")

    def test_b_a_cell_below_the_base_does_not_comply_and_the_other_zones_count_all(self) -> None:
        """RF-012-30, RF-012-22: una celda del acopio por debajo de su base (99,5 m) y otra de fuera (99,5 m) dan 1 m³ de
        corte de terreno, «no cumple» y 48 m³ de acopios (49 m³ de corte en total); el corte en la torre (2 m³) cuenta entero."""
        result = self.verify(("pit",), _selection("base_a"))
        zone = result.finals[0].zone(ZONE)
        self.assertEqual((zone.cut_m3, zone.counted_m3, zone.stockpile_cut_m3, zone.verdict),
                         (49.0, 1.0, 48.0, V.FAILS))
        self.assertEqual(result.fails, (True,))
        tower = result.finals[0].zone(TOWER)
        self.assertEqual((tower.counts, tower.cut_m3, tower.counted_m3, tower.stockpile_cut_m3, tower.verdict),
                         (C.ANY, 2.0, 2.0, 0.0, V.FAILS))
        self.assertEqual(sorted(group.zone for group in result.finals[0].groups), sorted([ZONE, ZONE, TOWER]))

    def test_c_without_a_base_the_table_and_the_figures_are_the_old_ones(self) -> None:
        """RF-012-24, RF-012-30: sin base (la selección vacía o sin dar), todo el corte cuenta (48 m³, «no cumple»), la tabla
        no tiene ninguna fila de acopios y las cifras son las cuatro de siempre."""
        for selection in (None, cstore.BaseSelection()):
            with self.subTest(selection=selection):
                result = self.verify(("removed",), selection)
                zone = result.finals[0].zone(ZONE)
                self.assertEqual((zone.counts, zone.cut_m3, zone.counted_m3, zone.stockpile_cut_m3, zone.verdict),
                                 (C.CUT, 48.0, 48.0, 0.0, V.FAILS))
                quantities = {row[2] for row in result.table_rows()}
                self.assertFalse(quantities & {"stockpile_cut_m3", "stockpile_base", "stockpile_skipped"})
                self.assertEqual({spec.key for spec in result.figures},
                                 {"res.check_cut_m3", "res.check_fill_m3", "res.check_moved_area_m2",
                                  "res.check_nodata_area_m2"})
        self.assertEqual(result.selection, cstore.BaseSelection())

    def test_d_two_bases_the_lower_one_counts(self) -> None:
        """P-10, RF-012-30: con dos bases que cubren una misma celda, la menor; a mano, final a 97 m en 9 celdas del acopio:
        la base A (100 m en las 9), la B (99 m en 4 de ellas): terreno = 4 · 2 + 5 · 3 = 23 m³ y acopios = 54 − 23 = 31; solo A
        daría 27 m³ y solo B, 38 m³; el orden de las bases no importa."""
        for bases in (("two_a", "two_b"), ("two_b", "two_a")):
            with self.subTest(orden=bases):
                zone = self.verify(("five",), _selection(*bases)).finals[0].zone(ZONE)
                self.assertEqual((zone.cut_m3, zone.counted_m3, zone.stockpile_cut_m3), (54.0, 23.0, 31.0))
        for base, wanted in (("two_a", 27.0), ("two_b", 38.0)):
            zone = self.verify(("five",), _selection(base)).finals[0].zone(ZONE)
            self.assertEqual(zone.counted_m3, wanted, base)

    def test_e_a_base_in_another_grid_is_rejected_at_the_call(self) -> None:
        """RF-012-31, RF-011-03: una base en otra rejilla (celdas de 0,5 m) se rechaza al llamar con ``res.surfaces_mismatch``,
        nombrando la base (su etiqueta, con la detección), sin dar ningún paso."""
        selection = cstore.BaseSelection((cstore.StockpileBase(
            "STK-001", "Acopios", "project", "mineral",
            surfaces.SurfaceRef(dataset="fine", label=USED_TEXT)),))
        request = compliance.ComplianceRequest(
            NAME, surfaces.SurfaceRef(dataset="gis_dtm_inicial"), (surfaces.SurfaceRef(dataset="gis_dtm_removed"),),
            self.masks, 0.02, bases=selection.refs)
        sources = {cstore.START_ROLE: self.source("start"), cstore.final_role(1): self.source("removed"),
                   cstore.base_role(1): surfaces.grid_source(self.fine, name=USED_TEXT, crs=fx.CRS,
                                                             vertical=fx.VERTICAL)}
        with self.assertRaises(res_messages.ResError) as caught:
            cstore.verify_steps(request, sources, references=(fx.CRS, fx.VERTICAL), selection=selection)
        self.assertEqual(caught.exception.code, "res.surfaces_mismatch")
        self.assertIn(USED_TEXT, caught.exception.text)
        with self.assertRaises(res_messages.ResError) as direct:
            cstore.check_sources(sources, self.masks, (fx.CRS, fx.VERTICAL))
        self.assertEqual(direct.exception.code, "res.surfaces_mismatch")

    def test_f_the_request_the_sources_and_the_selection_agree(self) -> None:
        """RF-012-24: falta la superficie de una base de la petición, o la selección no es la de la petición, es un error del
        programa (``ValueError``) al llamar."""
        request = compliance.ComplianceRequest(
            NAME, surfaces.SurfaceRef(dataset="gis_dtm_inicial"), (surfaces.SurfaceRef(dataset="gis_dtm_removed"),),
            self.masks, 0.02, bases=_selection("base_a").refs)
        sources = {cstore.START_ROLE: self.source("start"), cstore.final_role(1): self.source("removed")}
        with self.assertRaises(ValueError) as missing:
            cstore.verify_steps(request, sources, references=(fx.CRS, fx.VERTICAL))
        self.assertIn(cstore.base_role(1), str(missing.exception))
        sources[cstore.base_role(1)] = self.source("base_a")
        with self.assertRaises(ValueError):
            cstore.verify_steps(request, sources, references=(fx.CRS, fx.VERTICAL), selection=_selection("two_a"))
        with self.assertRaises(ValueError):
            cstore.BaseSelection(("base_a",))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            cstore.BaseSelection(skipped=("otra",))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            cstore.base_role(0)

    def test_g_the_selection_is_noted_in_the_settings_and_read_back(self) -> None:
        """RF-012-24, RF-012-31: ``verify_settings`` anota la base que usó y las detecciones que no (con su causa) y solo
        eso: sin acopios, los ajustes de siempre; ``BaseSelection.of_settings`` los lee y da la misma selección (también
        pasando por JSON)."""
        import json

        start = surfaces.SurfaceRef(dataset="gis_dtm_inicial", label="Levantamiento")
        finals = (surfaces.SurfaceRef(dataset="gis_dtm_removed"),)
        plain = cstore.verify_settings(NAME, start, finals, ["s1"], ["Sector 1"])
        self.assertEqual(sorted(plain), ["finals", "name", "pending_names", "pending_sectors", "start"])
        self.assertEqual(cstore.verify_settings(NAME, start, finals, ["s1"], ["Sector 1"], cstore.BaseSelection()), plain)
        selection = _selection("uid-a", "uid-b", skipped=(OTHER, STALE))
        noted = cstore.verify_settings(NAME, start, finals, ["s1"], ["Sector 1"], selection)
        self.assertEqual({key: value for key, value in noted.items() if key not in ("bases", "skipped")}, plain)
        self.assertEqual([(item["dataset"], item["detection"], item["name"], item["scope"], item["material"])
                          for item in noted["bases"]],
                         [("uid-a", "STK-001", "Acopios", "project", "mineral"),
                          ("uid-b", "STK-001", "Acopios", "project", "mineral")])
        self.assertEqual([(item["name"], item["reason"], item["cause"] != "") for item in noted["skipped"]],
                         [("Acopios de V01", "other_surface", False), ("Viejos", "stale", True)])
        for settings in (noted, json.loads(json.dumps(noted))):
            self.assertEqual(cstore.BaseSelection.of_settings(settings), selection)
        self.assertEqual(cstore.BaseSelection.of_settings(plain), cstore.BaseSelection())
        only_skipped = cstore.verify_settings(NAME, start, finals, bases=cstore.BaseSelection((), (OTHER,)))
        self.assertEqual(sorted(only_skipped), ["finals", "name", "pending_names", "pending_sectors", "skipped", "start"])
        with self.assertRaises(ValueError):
            cstore.BaseSelection.of_settings({"bases": [{"dataset": "x"}]})

    def test_h_the_messages_name_the_detection_and_the_cause(self) -> None:
        """RF-012-31: lo que no se usa se avisa nombrando la detección y la causa (obsoleta: lo que cambió; otra superficie: la
        de la detección y la de partida), en español y en inglés, sin marcadores sin llenar; una base usada, su detección y
        su material («sin material» si no tiene)."""
        for language in ("es", "en"):
            for text in (OTHER.text("Levantamiento", language), STALE.text("Levantamiento", language),
                         _selection("x").bases[0].text(language)):
                with self.subTest(language=language, text=text[:40]):
                    self.assertNotIn("{", text)
                    self.assertNotIn("?", text)
        text = STALE.text("Levantamiento")
        self.assertIn("STK-002", text)
        self.assertIn("«Viejos»", text)
        self.assertIn("obsoleta", text)
        self.assertIn(STALE.cause, text)
        other = OTHER.text("Levantamiento")
        self.assertIn("«Acopios de V01»", other)
        self.assertIn("«des_stp_levantamiento_de_v01»", other)
        self.assertIn("«Levantamiento»", other)
        self.assertIn("stale", STALE.text("Levantamiento", "en"))
        bare = cstore.StockpileBase("STK-003", "Cono", "version", None, surfaces.SurfaceRef(dataset="x"))
        self.assertIn("sin material", bare.text())
        self.assertEqual(_selection("x").bases[0].text(), USED_TEXT)

    def test_h_the_cause_of_a_stale_detection_is_kept_in_both_languages_and_shown_in_the_interface_one(self) -> None:
        """RF-012-31 (T48; hallazgo D-5 de la verificación única): la causa de una detección obsoleta se guarda en los ajustes **en los dos
        idiomas** (``cause`` en español, ``cause_en`` en inglés) y el aviso la escribe en el de la interfaz: en inglés, dentro de la
        frase inglesa, ya no la causa en español; sin la inglesa (lo anotado antes), la de siempre."""
        stale = cstore.SkippedDetection("STK-002", "Viejos", "project", "stale", "gis_dtm_levantamiento",
                                        "Obsoleto: cambió el umbral de la huella", "Stale: the footprint threshold changed")
        self.assertEqual((stale.cause, stale.cause_en), ("Obsoleto: cambió el umbral de la huella",
                                                         "Stale: the footprint threshold changed"))
        text_es, text_en = stale.text("Levantamiento", "es"), stale.text("Levantamiento", "en")
        self.assertIn("Obsoleto: cambió el umbral de la huella", text_es)
        self.assertNotIn("Stale: the footprint threshold changed", text_es)
        self.assertIn("Stale: the footprint threshold changed", text_en)
        self.assertNotIn("cambió", text_en)
        self.assertIn("stale", text_en)
        self.assertEqual(STALE.cause_en, "", "lo anotado antes no la trae")
        self.assertIn(STALE.cause, STALE.text("Levantamiento", "en"), "sin la inglesa, la de siempre")
        selection = cstore.BaseSelection((), (stale, OTHER))
        noted = cstore.verify_settings(NAME, surfaces.SurfaceRef(dataset="gis_dtm_inicial"), (), [], [], selection)
        self.assertEqual([(item["cause"], item["cause_en"]) for item in noted["skipped"]],
                         [("Obsoleto: cambió el umbral de la huella", "Stale: the footprint threshold changed"), ("", "")])
        self.assertEqual(cstore.BaseSelection.of_settings(noted), selection)
        old = {"skipped": [{"detection": "STK-002", "name": "Viejos", "scope": "project", "reason": "stale", "surface": "s",
                            "cause": "Obsoleto: x"}]}
        self.assertEqual(cstore.BaseSelection.of_settings(old).skipped[0].cause_en, "")

    def test_i_the_stored_table_is_read_and_a_terrain_cut_has_its_freeze_note(self) -> None:
        """RF-012-24, RF-012-25, RF-012-30: de la tabla que se guarda, el recinto de terreno da su corte de acopios y ``cut_terrain``
        (``None`` en los demás y sin base) y congelar con lo que no cumple da los m³ de **corte de terreno**
        (``res.freeze_cut_terrain``) y, en los demás, lo de siempre."""
        result = self.verify(("pit",), _selection("base_a"))
        stored = {item.zone: item for item in cstore._stored_zones(result.table_rows())}
        self.assertEqual((stored[ZONE].counts, stored[ZONE].counted_m3, stored[ZONE].stockpile_cut_m3, stored[ZONE].verdict),
                         ("cut_terrain", 1.0, 48.0, "fails"))
        self.assertEqual((stored[TOWER].counts, stored[TOWER].stockpile_cut_m3), ("any", None))
        plain = {item.zone: item for item in cstore._stored_zones(self.verify(("pit",)).table_rows())}
        self.assertEqual((plain[ZONE].counts, plain[ZONE].stockpile_cut_m3), ("cut", None))
        notes = cstore._failures(result.table_rows(), "Retirada")
        self.assertEqual(len(notes), 1)
        self.assertIn("«torre»: 2,0 m³ de movimiento", notes[0])
        self.assertIn(f"«{ZONE}»: 1,0 m³ de corte de terreno", notes[0])
        old = cstore._failures(self.verify(("pit",)).table_rows(), "Retirada")
        self.assertIn(f"«{ZONE}»: 49,0 m³ de corte", old[0])

    def test_j_the_roles_and_the_planned_units(self) -> None:
        """RF-012-24: el papel de cada base se cuenta de 1 en 1 y cuelga del de la detección (``stockpile_base``); con la base,
        el avance prevé una unidad más por cada 64 filas de grupos (el corte de terreno) y por cada banda de cada base."""
        self.assertEqual([cstore.base_role(k) for k in (1, 2, 10)],
                         ["stockpile_base_1", "stockpile_base_2", "stockpile_base_10"])
        for bad in (0, -1, True, "1"):
            with self.assertRaises(ValueError):
                cstore.base_role(bad)  # type: ignore[arg-type]
        grid = gis.Grid(0.0, 1000.0, 1.0, 1.0, 1000, 1000)
        plain = cstore.planned_units(grid, 2, 1)
        with_base = cstore.planned_units(grid, 3, 1, with_base=True)
        bands, quarter = -(-grid.nrows // 256), -(-grid.nrows // 64)
        self.assertEqual(with_base - plain, bands + quarter)
        self.assertEqual(cstore.planned_units(grid, 3, 1), plain + bands)

    def test_k_the_stored_selection_and_the_start_name_are_read_from_the_settings_of_the_operation(self) -> None:
        """RF-012-24, RF-012-30, RF-012-31 (T42): ``_stored_selection`` lee de los ajustes (JSON) de una verificación la selección de las
        bases y el nombre de la partida (lo que necesita la ventana para escribir sus líneas en el idioma de la interfaz y no con el texto
        en español de la tabla); sin acopios, la selección vacía y la partida; con unos ajustes que no se entienden, lo que sí se entiende
        y, de lo demás, nada, sin lanzar; ``StoredVerification`` sin ellos, vacíos."""
        import json

        start = surfaces.SurfaceRef(dataset="gis_dtm_inicial", label="Levantamiento")
        finals = (surfaces.SurfaceRef(dataset="gis_dtm_removed"),)
        selection = _selection("uid-a", "uid-b", skipped=(OTHER, STALE))
        noted = json.dumps(cstore.verify_settings(NAME, start, finals, ["s1"], ["Sector 1"], selection))
        self.assertEqual(cstore._stored_selection(noted), (selection, "Levantamiento"))
        plain = json.dumps(cstore.verify_settings(NAME, start, finals))
        self.assertEqual(cstore._stored_selection(plain), (cstore.BaseSelection(), "Levantamiento"))
        unlabelled = json.dumps(cstore.verify_settings(NAME, surfaces.SurfaceRef(dataset="gis_dtm_inicial"), finals))
        self.assertEqual(cstore._stored_selection(unlabelled)[1], "gis_dtm_inicial", "sin etiqueta, el dato, como la nombra la tabla")
        self.assertEqual(cstore._stored_selection(json.dumps(cstore.verify_settings(
            NAME, surfaces.SurfaceRef(elevation=100.0), finals)))[1], "100.0 m")
        half = '{"start": {"dataset": "d", "label": "L"}, "bases": [{"dataset": "x"}]}'
        for text, wanted in ((half, (cstore.BaseSelection(), "L")), ('{"name": "x"}', (cstore.BaseSelection(), "")),
                             ("", (cstore.BaseSelection(), "")), ("no es json", (cstore.BaseSelection(), "")),
                             ("[]", (cstore.BaseSelection(), "")), ("null", (cstore.BaseSelection(), "")),
                             (None, (cstore.BaseSelection(), ""))):
            with self.subTest(text=text):
                self.assertEqual(cstore._stored_selection(text), wanted)
        bare = cstore.StoredVerification("op", "Prueba", False, (), (), (), (), (), {})
        self.assertEqual((bare.selection, bare.start_name, bare.bases, bare.skipped), (cstore.BaseSelection(), "", (), ()))


if __name__ == "__main__":
    unittest.main()
