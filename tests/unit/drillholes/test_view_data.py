# SPDX-License-Identifier: GPL-3.0-or-later
"""Arrays de la vista de los sondeos (spec 005, T17; HU-005-5; RF-005-23, RF-005-24,
RF-005-25; plan 005 §5.3.2 y §5.4, «Vista»).

- **Curvas de litología** (RF-005-23): una por tramo del esquema elegido y una por hueco sin
  dato (gris), con los puntos de la traza cada ≤ ``max_step_m`` y los dos límites del tramo,
  en absoluto y sobre la traza (``desurvey.md_to_xyz``); el color del catálogo pasado de sRGB a
  lineal (los atributos ``FLOAT_COLOR`` de Blender son lineales) en cada punto; solapes,
  códigos sin catálogo y tramos imposibles; lo que excluye la validación (RF-005-17: la
  litología de un esquema con un error de alcance T no se pinta, la traza sí) y la leyenda del
  esquema.
- **Barras de leyes** (RF-005-24): una por tramo analizado del elemento, en la horizontal
  perpendicular a la traza, a su derecha según se baja (al este en un sondeo vertical),
  separada ``offset_m`` y de ancho ``width_m``, del color de su clase; la clase «< LD» para
  los valores bajo el límite de detección; sin barra lo vacío, lo no analizado, lo que no es
  primario y lo que no está en la unidad de la leyenda (contado).
- **Leyenda de clases** (RF-005-24): por defecto, 5 clases por quintiles redondeados a 2
  cifras significativas, más «< LD»; editable (cortes y colores en la unidad del elemento).
- **Etiquetas** (RF-005-25): «S-12 (160,00 m)» en la boca y, si se pide, la profundidad en el
  fondo, en el formato del idioma.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.support import dh_sets
from tests.support.package import import_geoblender

view_data = import_geoblender("drillholes.view_data")
desurvey = import_geoblender("drillholes.desurvey")
validate = import_geoblender("drillholes.validate")
model = import_geoblender("drillholes.model")
i18n = import_geoblender("core.i18n")

H25830, V5782 = dh_sets.H25830, dh_sets.V5782
COLLAR = (701_000.5, 4_401_000.5, 815.375)
NAN = math.nan
STEP = 2.0
THIN = i18n.THIN_SPACE
COLORS = {"SUE": "#8B6B3D", "CAL": "#9DB7D5", "MIN": "#C0392B"}
LITHOLOGY_CODES = (
    model.LithologyCode("MIN", color=COLORS["MIN"], sort_order=3, description="Mineral"),
    model.LithologyCode("SUE", color=COLORS["SUE"], sort_order=1, description="Suelo"),
    model.LithologyCode("CAL", color=COLORS["CAL"], sort_order=2),
    model.LithologyCode("OCU", color="#112233", sort_order=4, show_in_legend=False),
    model.LithologyCode("ARG", log_set="alteracion", color="#0A0A0A"),
)
LEGEND = None  # se crea en setUpModule, con la clase que se prueba


def _srgb(value: int) -> float:
    """Un canal sRGB de 8 bits en lineal (IEC 61966-2-1), a mano."""
    c = value / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear(color: str) -> list[float]:
    """El color «#RRGGBB» en lineal con alfa 1, en float32 (como los atributos de Blender)."""
    channels = [int(color[k:k + 2], 16) for k in (1, 3, 5)]
    return np.array([*map(_srgb, channels), 1.0], dtype=np.float32).tolist()


def _t(azimuth: float, inclination: float) -> np.ndarray:
    i, a = math.radians(90.0 + inclination), math.radians(azimuth)
    return np.array([math.sin(i) * math.sin(a), math.sin(i) * math.cos(a), -math.cos(i)])


def _collar(name: str, east: float, depth: float | None, **extra):
    return model.Collar(name, COLLAR[0] + east, COLLAR[1], COLLAR[2], depth, **extra)


def _vertical(name: str):
    return model.SurveyStation(name, 0.0, 0.0, -90.0, source="declared_vertical")


def _lith(hole: str, start: float, end: float, code: str, log_set: str = "lithology"):
    return model.LithologyInterval(hole, start, end, code, log_set=log_set)


def _assay(hole: str, start: float, end: float, value: float | None, *, element: str = "Au",
           unit: str = "g/t", **extra):
    return model.AssayValue(hole, start, end, element, value, unit, **extra)


def _set(lithology=(), assays=()):
    """Cinco sondeos: V-1 vertical (100 m), I-1 recto a 90°/−60° (50 m), C-1 curvo de 45°/−60°
    a 75°/−50° (60 m), N-1 vertical sin litología (30 m) y X-1 sin estaciones (sin traza)."""
    collars = [_collar("V-1", 0.0, 100.0), _collar("I-1", 20.0, 50.0),
               _collar("C-1", 40.0, 60.0), _collar("N-1", 60.0, 30.0),
               _collar("X-1", 80.0, 40.0)]
    stations = [_vertical("V-1"),
                model.SurveyStation("I-1", 0.0, 90.0, -60.0, source="collar"),
                model.SurveyStation("C-1", 0.0, 45.0, -60.0),
                model.SurveyStation("C-1", 60.0, 75.0, -50.0),
                _vertical("N-1")]
    catalogs = model.Catalogs(lithology=LITHOLOGY_CODES,
                              elements=(model.Element("Au", "g/t"), model.Element("Cu", "%")))
    return model.DrillholeSet.from_records(
        crs=H25830, vertical=V5782, collars=collars, surveys=stations, lithology=lithology,
        assays=assays, catalogs=catalogs)


def _traces(dset):
    """Las trazas de los sondeos con estaciones (X-1 no tiene)."""
    mask = np.zeros(len(dset.collars), dtype=np.bool_)
    mask[np.unique(dset.surveys.hole)] = True
    return desurvey.desurvey(dset, holes=mask)


BASIC_LITHOLOGY = (
    _lith("V-1", 0.0, 10.0, "SUE"), _lith("V-1", 10.0, 40.0, "CAL"),
    _lith("V-1", 45.0, 90.0, "MIN"), _lith("V-1", 0.0, 100.0, "ARG", log_set="alteracion"),
    _lith("I-1", 5.0, 20.0, "cal"), _lith("C-1", 0.0, 60.0, "MIN"), _lith("X-1", 0.0, 10.0, "SUE"),
)


def _curves(arrays) -> list[tuple]:
    """(sondeo, desde, hasta, código) de cada curva."""
    return list(zip(arrays.hole.tolist(), arrays.from_m.tolist(), arrays.to_m.tolist(),
                    arrays.code.tolist(), strict=True))


def _split(arrays):
    """Las profundidades, los puntos y los colores de cada curva."""
    ends = np.cumsum(arrays.curve_sizes)
    starts = ends - arrays.curve_sizes
    return [(arrays.md[a:b], arrays.points_abs[a:b], arrays.color_linear[a:b])
            for a, b in zip(starts.tolist(), ends.tolist(), strict=True)]


def _snapshot(dset) -> dict[str, list]:
    return {name: [getattr(getattr(dset, name), field).tolist()
                   for field in ("hole", "from_m", "to_m")]
            for name in ("lithology", "assays")}


def setUpModule() -> None:  # noqa: N802 (nombre de unittest)
    global LEGEND
    LEGEND = view_data.GradeLegend("g/t", (1.0,), ("#2C7BB6", "#D7263D"))


class SrgbTest(unittest.TestCase):
    def test_srgb_to_linear(self) -> None:
        """RF-005-23: los colores «#RRGGBB» del catálogo (sRGB) pasan a lineal por los dos
        tramos de la curva de IEC 61966-2-1 (lineal hasta 0,04045 y potencia 2,4), con alfa 1,
        en float32; las minúsculas valen y otro texto es un error."""
        found = view_data.srgb_to_linear(["#000000", "#FFFFFF", "#808080", "#0a0b0c",
                                          "#C0392B"])
        self.assertEqual(found.dtype, np.float32)
        self.assertEqual(found.shape, (5, 4))
        self.assertEqual(found.tolist(), [_linear(c) for c in
                                          ("#000000", "#FFFFFF", "#808080", "#0A0B0C",
                                           "#C0392B")])
        self.assertEqual(found[2, 0], np.float32(0.21586050011389926))  # 0x80 = 128
        self.assertEqual(found[3, 0], np.float32(10 / 255 / 12.92))  # tramo lineal
        self.assertEqual(view_data.srgb_to_linear([]).shape, (0, 4))
        for bad in ("808080", "#80808", "#GG0000", None):
            with self.subTest(bad=bad), self.assertRaises((ValueError, TypeError)):
                view_data.srgb_to_linear([bad])


class LithologyCurvesTest(unittest.TestCase):
    def test_one_curve_per_interval_and_per_gap(self) -> None:
        """RF-005-23: una curva por tramo del esquema elegido y una por hueco sin dato
        (gris), en orden de sondeo y profundidad; solo los sondeos con traza; el sondeo sin
        litología, una curva gris de la boca al fondo; el código, sin distinguir mayúsculas
        en el catálogo."""
        dset = _set(BASIC_LITHOLOGY)
        found = view_data.lithology_curves(dset, _traces(dset), "lithology", STEP)
        self.assertEqual(_curves(found), [
            (0, 0.0, 10.0, "SUE"), (0, 10.0, 40.0, "CAL"), (0, 40.0, 45.0, None),
            (0, 45.0, 90.0, "MIN"), (0, 90.0, 100.0, None),
            (1, 0.0, 5.0, None), (1, 5.0, 20.0, "cal"), (1, 20.0, 50.0, None),
            (2, 0.0, 60.0, "MIN"),
            (3, 0.0, 30.0, None),
        ])
        self.assertEqual(found.row.tolist(), [0, 1, -1, 2, -1, -1, 4, -1, 5, -1])
        self.assertEqual(found.curve_sizes.dtype, np.int32)
        self.assertEqual(found.hole.dtype, np.int32)
        self.assertEqual(found.points_abs.dtype, np.float64)
        self.assertEqual(found.color_linear.dtype, np.float32)
        self.assertEqual(int(found.curve_sizes.sum()), len(found.points_abs))
        self.assertEqual(found.color_linear.shape, (len(found.points_abs), 4))
        other = view_data.lithology_curves(dset, _traces(dset), "ALTERACION", STEP)
        self.assertEqual(_curves(other), [(0, 0.0, 100.0, "ARG"), (1, 0.0, 50.0, None),
                                          (2, 0.0, 60.0, None), (3, 0.0, 30.0, None)])

    def test_points_on_the_trace_every_step(self) -> None:
        """RF-005-23: cada curva empieza y acaba en los límites de su tramo, sus puntos van
        cada ≤ 2 m (con los nodos de la traza) y están sobre la traza: en el vertical, X e Y de
        la boca y Z − profundidad; en el recto, boca + profundidad·dirección; en el curvo, la
        posición de ``md_to_xyz``; todo en absoluto y float64."""
        dset = _set(BASIC_LITHOLOGY)
        traces = _traces(dset)
        found = view_data.lithology_curves(dset, traces, "lithology", STEP)
        for (hole, start, end, _), (md, xyz, _) in zip(_curves(found), _split(found),
                                                        strict=True):
            with self.subTest(hole=hole, start=start):
                self.assertEqual((md[0], md[-1]), (start, end))
                self.assertTrue((np.diff(md) > 0.0).all())
                self.assertLessEqual(float(np.diff(md).max()), STEP + 1e-12)
                self.assertEqual(len(md), math.ceil((end - start) / STEP) + 1)
                np.testing.assert_allclose(xyz, desurvey.md_to_xyz(traces, hole, md),
                                           rtol=0, atol=1e-9)
        md, xyz, _ = _split(found)[1]  # V-1, de 10 a 40 m
        self.assertEqual(xyz[:, :2].tolist(), [list(COLLAR[:2])] * len(md))
        np.testing.assert_allclose(xyz[:, 2], COLLAR[2] - md, rtol=0, atol=1e-9)
        md, xyz, _ = _split(found)[6]  # I-1, de 5 a 20 m
        expected = np.array(COLLAR) + [20.0, 0.0, 0.0] + md[:, None] * _t(90.0, -60.0)
        np.testing.assert_allclose(xyz, expected, rtol=0, atol=1e-9)

    def test_colors_from_the_catalog_in_linear(self) -> None:
        """RF-005-23: cada punto lleva el color de su litología en el catálogo, en lineal;
        los huecos, gris (``NO_DATA_COLOR``)."""
        dset = _set(BASIC_LITHOLOGY)
        found = view_data.lithology_curves(dset, _traces(dset), "lithology", STEP)
        grey = _linear(view_data.NO_DATA_COLOR)
        self.assertEqual(view_data.NO_DATA_COLOR, model.DEFAULT_COLOR)
        for (_, _, _, code), (md, _, color) in zip(_curves(found), _split(found), strict=True):
            expected = grey if code is None else _linear(COLORS[code.upper()])
            self.assertEqual(color.tolist(), [expected] * len(md))

    def test_overlaps_unknown_codes_and_impossible_intervals(self) -> None:
        """RF-005-23: dos tramos solapados se dibujan los dos y el hueco se mide desde el
        hasta más hondo; un código sin catálogo, en gris con su código; un tramo imposible
        (desde < 0, desde ≥ hasta, sin desde) o sin boca no se dibuja (queda el hueco)."""
        dset = _set([
            _lith("V-1", 0.0, 30.0, "CAL"), _lith("V-1", 20.0, 50.0, "MIN"),
            _lith("V-1", 60.0, 70.0, "XXX"), _lith("V-1", -1.0, 5.0, "SUE"),
            _lith("V-1", 80.0, 80.0, "SUE"), _lith("V-1", 95.0, 90.0, "SUE"),
            _lith("V-1", NAN, 99.0, "SUE"), _lith("Z-9", 0.0, 10.0, "SUE"),
        ])
        found = view_data.lithology_curves(dset, _traces(dset), "lithology", STEP)
        self.assertEqual(_curves(found)[:5], [
            (0, 0.0, 30.0, "CAL"), (0, 20.0, 50.0, "MIN"), (0, 50.0, 60.0, None),
            (0, 60.0, 70.0, "XXX"), (0, 70.0, 100.0, None)])
        colors = [color[0] for _, _, color in _split(found)[:5]]
        self.assertEqual(colors[3].tolist(), _linear(view_data.NO_DATA_COLOR))
        self.assertEqual(colors[1].tolist(), _linear(COLORS["MIN"]))

    def test_validation_exclusions(self) -> None:
        """RF-005-17 y RF-005-23: la litología de un esquema excluido en un sondeo (alcance
        T) no se pinta y su traza queda en gris; un registro excluido (R) deja su hueco; un
        sondeo excluido (S) no se dibuja; lo demás, igual."""
        dset = _set(BASIC_LITHOLOGY)
        holes = np.zeros(len(dset.collars), dtype=np.bool_)
        holes[3] = True
        excluded = validate.Exclusions(
            holes=holes, tables=frozenset({(0, "dh_lithology", " LITHOLOGY "),
                                           (2, "dh_lithology", "alteracion"),
                                           (2, "dh_assay", "Au")}),
            records=frozenset({("dh_lithology", 4), ("dh_assay", 5)}))
        found = view_data.lithology_curves(dset, _traces(dset), "lithology", STEP,
                                           excluded=excluded)
        self.assertEqual(_curves(found), [(0, 0.0, 100.0, None), (1, 0.0, 50.0, None),
                                          (2, 0.0, 60.0, "MIN")])

    def test_csv_basico(self) -> None:
        """RF-005-23 con ``tests/data/dh/csv_basico``: los 24 tramos, sin huecos, con el
        color de su código y sus puntos sobre la traza (≤ 10⁻⁹ m)."""
        dset = dh_sets.basico_set()
        traces = desurvey.desurvey(dset)
        found = view_data.lithology_curves(dset, traces, "lithology", STEP)
        self.assertEqual(len(found.curve_sizes), len(dset.lithology))
        self.assertNotIn(None, found.code.tolist())
        catalog = {code.code: code.color for code in dset.catalogs.lithology}
        for (hole, _, _, code), (md, xyz, color) in zip(_curves(found), _split(found),
                                                        strict=True):
            self.assertEqual(color.tolist(), [_linear(catalog[code])] * len(md))
            np.testing.assert_allclose(xyz, desurvey.md_to_xyz(traces, hole, md),
                                       rtol=0, atol=1e-9)

    def test_contract(self) -> None:
        """RF-005-23: la entrada no cambia; unas trazas de otro conjunto, un paso que no es
        positivo, un esquema que no es texto o unas exclusiones de otro tamaño son un error;
        sin sondeos con traza, nada."""
        dset = _set(BASIC_LITHOLOGY)
        traces = _traces(dset)
        before = _snapshot(dset)
        view_data.lithology_curves(dset, traces, "lithology", STEP)
        self.assertEqual(_snapshot(dset), before)
        other = desurvey.desurvey(dh_sets.basico_set())
        with self.assertRaises(ValueError):
            view_data.lithology_curves(dset, other, "lithology", STEP)
        with self.assertRaises(ValueError):
            view_data.lithology_curves(dset, traces, "lithology", 0.0)
        with self.assertRaises(TypeError):
            view_data.lithology_curves(dset, traces, None, STEP)
        with self.assertRaises(ValueError):
            view_data.lithology_curves(dset, traces, "lithology", STEP,
                                       excluded=validate.Exclusions(np.zeros(2, np.bool_)))
        empty = desurvey.desurvey(dset, holes=np.zeros(len(dset.collars), np.bool_))
        found = view_data.lithology_curves(dset, empty, "lithology", STEP)
        self.assertEqual((len(found.curve_sizes), found.points_abs.shape), (0, (0, 3)))

    def test_lithology_legend(self) -> None:
        """RF-005-23: la leyenda del esquema, los códigos del catálogo que salen en la
        leyenda por su orden, con su color y su descripción, y «Sin dato» en gris."""
        dset = _set()
        found = view_data.lithology_legend(dset, "Lithology")
        self.assertEqual([(e.label, e.color, e.description) for e in found], [
            ("SUE", COLORS["SUE"], "Suelo"), ("CAL", COLORS["CAL"], None),
            ("MIN", COLORS["MIN"], "Mineral"), ("Sin dato", view_data.NO_DATA_COLOR, None)])
        self.assertEqual(list(found[0].linear), _linear(COLORS["SUE"]))
        self.assertEqual([e.label for e in view_data.lithology_legend(dset, "alteracion")],
                         ["ARG", "Sin dato"])


class GradeLegendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("es")

    def test_default_quintiles_with_two_significant_figures(self) -> None:
        """RF-005-24: la leyenda por defecto tiene 5 clases por quintiles redondeados a 2
        cifras significativas, más «< LD», en la unidad del elemento; los textos, en el
        formato del idioma."""
        values = np.arange(1, 101, dtype=np.float64)  # quintiles 20,8; 40,6; 60,4; 80,2
        for scale, breaks, labels in (
            (1.0, (21.0, 41.0, 60.0, 80.0), ["< 21", "21 – 41", "41 – 60", "60 – 80", "≥ 80"]),
            (0.01, (0.21, 0.41, 0.6, 0.8),
             ["< 0,21", "0,21 – 0,41", "0,41 – 0,6", "0,6 – 0,8", "≥ 0,8"]),
            (100.0, (2100.0, 4100.0, 6000.0, 8000.0),
             [f"< 2{THIN}100", f"2{THIN}100 – 4{THIN}100", f"4{THIN}100 – 6{THIN}000",
              f"6{THIN}000 – 8{THIN}000", f"≥ 8{THIN}000"]),
        ):
            with self.subTest(scale=scale):
                legend = view_data.default_grade_legend(values * scale, "ppm")
                self.assertEqual(legend.unit, "ppm")
                self.assertEqual(legend.breaks, breaks)
                self.assertEqual(legend.colors, view_data.DEFAULT_RAMP)
                self.assertEqual(legend.below_dl_color, view_data.BELOW_DL_COLOR)
                entries = legend.entries()
                self.assertEqual([e.label for e in entries], [*labels, "< LD"])
                self.assertEqual([e.color for e in entries],
                                 [*view_data.DEFAULT_RAMP, view_data.BELOW_DL_COLOR])
        self.assertEqual(len(set(view_data.DEFAULT_RAMP)), 5)
        self.assertNotIn(view_data.BELOW_DL_COLOR, (*view_data.DEFAULT_RAMP,
                                                    view_data.NO_DATA_COLOR))

    def test_default_legend_edge_cases(self) -> None:
        """RF-005-24: sin valores finitos, una sola clase; cortes repetidos tras redondear,
        una vez (menos clases); otro número de clases, sus cuantiles; en inglés, «< DL»."""
        legend = view_data.default_grade_legend(np.array([NAN]), "g/t")
        self.assertEqual((legend.breaks, len(legend.colors)), ((), 1))
        self.assertEqual([e.label for e in legend.entries()], ["Todos los valores", "< LD"])
        legend = view_data.default_grade_legend(np.full(10, 5.0), "g/t")
        self.assertEqual((legend.breaks, len(legend.colors)), ((5.0,), 2))
        legend = view_data.default_grade_legend(np.arange(1, 101, dtype=np.float64), "g/t",
                                                n_classes=4)
        self.assertEqual(legend.breaks, (26.0, 50.0, 75.0))  # 25,75; 50,5; 75,25
        with self.assertRaises(ValueError):
            view_data.default_grade_legend(np.ones(3), "g/t", n_classes=0)
        i18n.set_language("en")
        legend = view_data.default_grade_legend(np.arange(1, 101) * 0.01, "g/t")
        self.assertEqual([e.label for e in legend.entries()][-2:], ["≥ 0.8", "< DL"])

    def test_classify(self) -> None:
        """RF-005-24: un valor justo en un corte es de la clase de arriba; NaN, de ninguna;
        la clase «< LD» es la última de las entradas."""
        legend = view_data.GradeLegend("g/t", (0.5, 1.0, 5.0), ("#000001", "#000002",
                                                                 "#000003", "#000004"))
        found = legend.classify(np.array([0.1, 0.5, 0.99, 1.0, 4.0, 5.0, 50.0, NAN]))
        self.assertEqual(found.tolist(), [0, 1, 1, 2, 2, 3, 3, -1])
        self.assertEqual(legend.below_dl_class, 4)
        self.assertEqual(len(legend.entries()), 5)

    def test_editable_legend(self) -> None:
        """RF-005-24: la leyenda se puede editar (cortes y colores en la unidad del
        elemento); lo que no forma una leyenda es un error."""
        legend = view_data.GradeLegend("g/t", (0.5, 2.0), ("#2c7bb6", "#F2D43D", "#D7263D"),
                                       below_dl_color="#eeeeee")
        self.assertEqual(legend.colors, ("#2C7BB6", "#F2D43D", "#D7263D"))
        self.assertEqual(legend.below_dl_color, "#EEEEEE")
        for unit, breaks, colors in (
            ("g/t", (2.0, 0.5), ("#000000",) * 3), ("g/t", (0.5, 0.5), ("#000000",) * 3),
            ("g/t", (0.5, NAN), ("#000000",) * 3), ("g/t", (0.5,), ("#000000",) * 3),
            ("g/t", (0.5,), ("#000000", "negro")), ("", (0.5,), ("#000000",) * 2),
            ("text", (0.5,), ("#000000",) * 2),
        ):
            with self.subTest(unit=unit, breaks=breaks, colors=colors):
                with self.assertRaises((ValueError, TypeError)):
                    view_data.GradeLegend(unit, breaks, colors)


class GradeBarsTest(unittest.TestCase):
    ASSAYS = (
        _assay("V-1", 10.0, 12.0, 0.5),
        _assay("V-1", 12.0, 14.0, 2.0),
        _assay("V-1", 14.0, 16.0, 0.01, detection_flag="below_dl"),
        _assay("V-1", 16.0, 18.0, None),
        _assay("V-1", 18.0, 20.0, None, detection_flag="not_analysed"),
        _assay("V-1", 10.0, 12.0, 0.6, is_primary=False),
        _assay("V-1", 20.0, 22.0, 1.5, unit="ppm"),
        _assay("V-1", 10.0, 12.0, 0.3, element="Cu", unit="%"),
        _assay("V-1", 22.0, 24.0, 1.0, element="au"),
        _assay("V-1", 24.0, 26.0, 3.0, detection_flag="above_ul"),
        _assay("X-1", 0.0, 2.0, 5.0),
    )

    def _faces(self, bars) -> np.ndarray:
        """Los cuatro vértices de cada cara: (caras, 4, 3)."""
        return bars.vertices_abs[bars.faces]

    def test_vertical_hole_bars_to_the_east(self) -> None:
        """RF-005-24: en un sondeo vertical, una barra por tramo analizado al este de la
        traza, de ``offset_m`` a ``offset_m`` + ``width_m``, del color de su clase (un valor
        justo en el corte, la de arriba; «>x», por su valor) y «< LD» para el bajo el límite;
        sin barra lo vacío, lo no analizado, lo que no es primario, otro elemento y un sondeo
        sin traza; lo que no está en la unidad de la leyenda, contado."""
        dset = _set(assays=self.ASSAYS)
        bars = view_data.grade_bars(dset, _traces(dset), "AU", LEGEND, 0.5, 1.0)
        self.assertEqual(bars.row.tolist(), [0, 1, 2, 8, 9])
        self.assertEqual(bars.hole.tolist(), [0] * 5)
        self.assertEqual(bars.grade_class.tolist(), [0, 1, 2, 1, 1])
        self.assertEqual(bars.skipped_units, 1)
        self.assertEqual(bars.vertices_abs.dtype, np.float64)
        self.assertEqual(bars.faces.dtype, np.int32)
        self.assertEqual(bars.faces.tolist(), np.arange(20).reshape(5, 4).tolist())
        colors = [*LEGEND.colors, LEGEND.below_dl_color]
        self.assertEqual(bars.color_linear.tolist(),
                         [_linear(colors[k]) for k in (0, 1, 2, 1, 1)])
        x, y, z = COLLAR
        for face, (start, end) in zip(self._faces(bars), [(10, 12), (12, 14), (14, 16),
                                                          (22, 24), (24, 26)], strict=True):
            np.testing.assert_allclose(face, [[x + 0.5, y, z - start], [x + 0.5, y, z - end],
                                              [x + 1.5, y, z - end], [x + 1.5, y, z - start]],
                                       rtol=0, atol=1e-9)

    def test_horizontal_perpendicular_on_the_right(self) -> None:
        """RF-005-24: en un sondeo inclinado, la barra va en la horizontal perpendicular a
        la traza, a su derecha según se baja (azimut + 90°): al sur en uno a 90°, al sureste
        en uno a 45°."""
        collars = [_collar("E-1", 0.0, 40.0), _collar("D-1", 30.0, 40.0)]
        stations = [model.SurveyStation("E-1", 0.0, 90.0, -60.0, source="collar"),
                    model.SurveyStation("D-1", 0.0, 45.0, -45.0, source="collar")]
        assays = [_assay("E-1", 5.0, 9.0, 2.0), _assay("D-1", 3.0, 4.5, 0.2)]
        dset = model.DrillholeSet.from_records(crs=H25830, vertical=V5782, collars=collars,
                                               surveys=stations, assays=assays)
        traces = desurvey.desurvey(dset)
        bars = view_data.grade_bars(dset, traces, "Au", LEGEND, 0.25, 2.0)
        for k, (azimuth, start, end) in enumerate([(90.0, 5.0, 9.0), (45.0, 3.0, 4.5)]):
            with self.subTest(azimuth=azimuth):
                side = np.array([math.cos(math.radians(azimuth)),
                                 -math.sin(math.radians(azimuth)), 0.0])
                inner = desurvey.md_to_xyz(traces, k, np.array([start, end])) + 0.25 * side
                outer = inner + 2.0 * side
                np.testing.assert_allclose(self._faces(bars)[k],
                                           [inner[0], inner[1], outer[1], outer[0]],
                                           rtol=0, atol=1e-9)

    def test_densified_bars_follow_the_trace(self) -> None:
        """RF-005-24: con ``max_step_m``, la barra de un tramo largo de un sondeo curvo sigue
        la traza en partes de ≤ 2 m, cada cara plana y perpendicular en horizontal a su
        cuerda; sin él, una cara por tramo."""
        dset = _set(assays=[_assay("C-1", 0.0, 60.0, 2.0)])
        traces = _traces(dset)
        single = view_data.grade_bars(dset, traces, "Au", LEGEND, 0.5, 1.0)
        self.assertEqual(len(single.faces), 1)
        bars = view_data.grade_bars(dset, traces, "Au", LEGEND, 0.5, 1.0, max_step_m=STEP)
        self.assertEqual(len(bars.faces), 30)
        self.assertEqual(bars.row.tolist(), [0] * 30)
        faces = self._faces(bars)
        md = np.arange(0.0, 61.0, 2.0)
        axis = desurvey.md_to_xyz(traces, 2, md)
        chord = np.diff(axis, axis=0)
        side = faces[:, 3] - faces[:, 0]
        np.testing.assert_allclose(side[:, 2], 0.0, rtol=0, atol=1e-9)
        np.testing.assert_allclose(np.linalg.norm(side, axis=1), 1.0, rtol=0, atol=1e-9)
        np.testing.assert_allclose(np.einsum("ij,ij->i", side[:, :2], chord[:, :2]), 0.0,
                                   rtol=0, atol=1e-9)
        np.testing.assert_allclose(faces[:, 0], axis[:-1] + 0.5 * side, rtol=0, atol=1e-9)
        np.testing.assert_allclose(faces[:, 1], axis[1:] + 0.5 * side, rtol=0, atol=1e-9)
        np.testing.assert_allclose(faces[:, 2] - faces[:, 1], side, rtol=0, atol=1e-9)

    def test_exclusions_and_values_for_the_legend(self) -> None:
        """RF-005-17 y RF-005-24: un elemento excluido en un sondeo (alcance T) o un valor
        excluido (R) no tienen barra; ``grade_values`` da los valores que se clasifican por
        clases (primarios, en la unidad, ni vacíos ni «< LD»), también los de sondeos sin
        traza, y es la entrada de la leyenda por defecto."""
        dset = _set(assays=self.ASSAYS)
        traces = _traces(dset)
        excluded = validate.Exclusions(
            holes=np.zeros(len(dset.collars), dtype=np.bool_),
            tables=frozenset({(0, "dh_assay", "AU ")}))
        self.assertEqual(len(view_data.grade_bars(dset, traces, "Au", LEGEND, 0.5, 1.0,
                                                  excluded=excluded).faces), 0)
        excluded = validate.Exclusions(holes=np.zeros(len(dset.collars), dtype=np.bool_),
                                       records=frozenset({("dh_assay", 1)}))
        bars = view_data.grade_bars(dset, traces, "Au", LEGEND, 0.5, 1.0, excluded=excluded)
        self.assertEqual(bars.row.tolist(), [0, 2, 8, 9])
        found = view_data.grade_values(dset, "au", "g/t")
        self.assertEqual(found.tolist(), [0.5, 2.0, 1.0, 3.0, 5.0])
        self.assertEqual(view_data.grade_values(dset, "Au", "g/t", excluded=excluded).tolist(),
                         [0.5, 1.0, 3.0, 5.0])
        legend = view_data.default_grade_legend(found, "g/t")
        self.assertEqual(legend.breaks, (0.9, 1.6, 2.4, 3.4))  # 0,5 1 2 3 5

    def test_contract(self) -> None:
        """RF-005-24: la entrada no cambia; separación o ancho no válidos, una leyenda que no
        lo es o unas trazas de otro conjunto son un error; un elemento sin análisis, nada."""
        dset = _set(assays=self.ASSAYS)
        traces = _traces(dset)
        before = _snapshot(dset)
        view_data.grade_bars(dset, traces, "Au", LEGEND, 0.5, 1.0)
        self.assertEqual(_snapshot(dset), before)
        for offset, width in ((-0.1, 1.0), (0.5, 0.0), (NAN, 1.0), (0.5, math.inf)):
            with self.subTest(offset=offset, width=width), self.assertRaises(ValueError):
                view_data.grade_bars(dset, traces, "Au", LEGEND, offset, width)
        with self.assertRaises(TypeError):
            view_data.grade_bars(dset, traces, "Au", None, 0.5, 1.0)
        with self.assertRaises(ValueError):
            view_data.grade_bars(dset, desurvey.desurvey(dh_sets.basico_set()), "Au", LEGEND,
                                 0.5, 1.0)
        bars = view_data.grade_bars(dset, traces, "Zn", LEGEND, 0.5, 1.0)
        self.assertEqual((bars.vertices_abs.shape, bars.faces.shape, bars.skipped_units),
                         ((0, 3), (0, 4), 0))


class LabelsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("es")

    def test_collar_labels_csv_basico(self) -> None:
        """RF-005-25 con ``csv_basico``: en la boca de cada sondeo, su nombre y su
        profundidad total con dos decimales («S-12 (160,00 m)»), en su X, Y, Z absoluta; y,
        si se pide, la profundidad en el fondo, sobre la traza."""
        dset = dh_sets.basico_set()
        traces = desurvey.desurvey(dset)
        found = view_data.labels(dset, traces, at_end=False)
        self.assertEqual([label.text for label in found], [
            "S-01 (150,00 m)", "S-02 (300,00 m)", "S-03 (240,00 m)", "S-04 (100,00 m)",
            "S-12 (160,00 m)", "C-01 (4,50 m)"])
        collars = dset.collars
        self.assertEqual([label.xyz for label in found],
                         list(zip(collars.x.tolist(), collars.y.tolist(), collars.z.tolist(),
                                  strict=True)))
        self.assertEqual({label.bottom for label in found}, {False})
        found = view_data.labels(dset, traces, at_end=True)
        bottom = [label for label in found if label.bottom]
        self.assertEqual([label.text for label in bottom], [
            "150,00 m", "300,00 m", "240,00 m", "100,00 m", "160,00 m", "4,50 m"])
        self.assertEqual([label.hole for label in bottom], list(range(6)))
        for label in bottom:
            expected = desurvey.md_to_xyz(traces, label.hole, collars.depth[label.hole])[0]
            np.testing.assert_allclose(label.xyz, expected, rtol=0, atol=1e-9)

    def test_formats_and_holes_without_data(self) -> None:
        """RF-005-25: miles con espacio fino; sin profundidad, solo el nombre; sin X, Y o Z,
        sin etiqueta; sin traza, sin la del fondo; en inglés, punto decimal."""
        collars = [model.Collar("L-1", *COLLAR, 1234.5), model.Collar("L-2", *COLLAR, None),
                   model.Collar("L-3", COLLAR[0], None, COLLAR[2], 20.0),
                   model.Collar("L-4", *COLLAR, 12.0)]
        dset = model.DrillholeSet.from_records(
            crs=H25830, vertical=V5782, collars=collars, surveys=[_vertical("L-1")])
        traces = desurvey.desurvey(dset, holes=np.array([0]))
        found = view_data.labels(dset, traces, at_end=True)
        self.assertEqual([(label.hole, label.text) for label in found], [
            (0, f"L-1 (1{THIN}234,50 m)"), (0, f"1{THIN}234,50 m"), (1, "L-2"),
            (3, "L-4 (12,00 m)")])
        i18n.set_language("en")
        found = view_data.labels(dset, traces, at_end=False)
        self.assertEqual(found[0].text, "L-1 (1,234.50 m)")


if __name__ == "__main__":
    unittest.main()
