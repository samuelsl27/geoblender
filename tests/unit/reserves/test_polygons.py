# SPDX-License-Identifier: GPL-3.0-or-later
"""Validar y recortar los polígonos de una capa (spec 011, T07; HU-011-2; RF-011-08, RF-011-07,
RF-011-01; plan 011 A6 y D-21).

``reserves.polygons`` comprueba una capa de dominios antes de cubicar con ella (RF-011-08: cada
polígono simple, con área y con el campo lleno; ninguno se solapa con otro, salvo 1 mm²) y
recorta cada dominio por el ámbito por **clasificación de aristas** (A6): las aristas de los dos
se parten en sus cruces y en los vértices del otro que caen sobre ellas (a ≤ 1 mm), cada trozo se
queda si está dentro del otro y los comunes, una vez si van en el mismo sentido. Las aristas que
quedan son el borde orientado de la intersección: su área con signo es la del solape, y con ellas
se calcula la fracción de celda (A5). Los pesos de una banda reparten cada celda entre los
dominios y la fila «Fuera de los dominios», que cierra con el ámbito.

Las referencias son independientes del recorte: áreas de rectángulos a mano y la del recorte de
Sutherland–Hodgman por un polígono convexo.
"""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

import numpy as np

from tests.support import res_fixtures as fx
from tests.support import timing
from tests.support.package import import_geoblender

polygons = import_geoblender("reserves.polygons")
coverage = import_geoblender("reserves.coverage")
messages = import_geoblender("reserves.messages")
gis = import_geoblender("gis")

Grid = gis.Grid
ResError = messages.ResError

WEST = 735_000.0
SOUTH = 4_434_000.0
ORIGIN = np.array([WEST, SOUTH])
FIELD = "fase"
LAYER = "Fases 2027"
TOLERANCE = 1e-12
"""Error relativo admitido de un área y absoluto de una fracción de celda."""
PAIR_BUDGET_S = 0.020
"""A6: un par de polígonos con unos miles de vértices, ≤ 20 ms."""


# Datos y referencias ------------------------------------------------------------------------


def _ring(points) -> np.ndarray:
    """Un anillo ABSOLUTO desde coordenadas relativas a (WEST, SOUTH)."""
    return np.asarray(points, dtype=np.float64) + ORIGIN


def _rect(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    return _ring([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


def _rotated(points, angle: float, center) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return _ring(np.asarray(points, dtype=np.float64) @ np.array([[c, s], [-s, c]])
                 + np.asarray(center, dtype=np.float64))


def _square(side: float, angle: float, center) -> np.ndarray:
    h = side / 2.0
    return _rotated([[-h, -h], [h, -h], [h, h], [-h, h]], angle, center)


def _polygon(fid: int, value: str, *rings: np.ndarray):
    return polygons.Polygon(fid, value, tuple(rings))


def _open(ring: np.ndarray) -> np.ndarray:
    ring = np.asarray(ring, dtype=np.float64)[:, :2]
    return ring[:-1] if np.array_equal(ring[0], ring[-1]) else ring


def _shoelace(points) -> float:
    pairs = zip(points, points[1:] + points[:1])
    return math.fsum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in pairs) / 2.0


def _sh_area(subject: np.ndarray, clip: np.ndarray) -> float:
    """El área (m²) de ``subject`` recortado por el polígono CONVEXO ``clip`` (Sutherland–
    Hodgman; con un sujeto cóncavo deja aristas degeneradas sobre el borde, que no cambian el
    área), en metros relativos a (WEST, SOUTH)."""
    points = [tuple(p) for p in (_open(subject) - ORIGIN).tolist()]
    window = _open(clip) - ORIGIN
    if _shoelace([tuple(p) for p in window.tolist()]) < 0.0:
        window = window[::-1]
    for (ax, ay), (bx, by) in zip(window.tolist(), np.roll(window, -1, axis=0).tolist()):
        if not points:
            return 0.0

        def side(p, ax=ax, ay=ay, bx=bx, by=by) -> float:
            return (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)

        out = []
        for current, following in zip(points, points[1:] + points[:1]):
            sc, sf = side(current), side(following)
            if sc >= 0.0:
                out.append(current)
            if (sc >= 0.0) != (sf >= 0.0):
                t = sc / (sc - sf)
                out.append((current[0] + t * (following[0] - current[0]),
                            current[1] + t * (following[1] - current[1])))
        points = out
    return abs(_shoelace(points)) if len(points) >= 3 else 0.0


def _edges_area(edges: np.ndarray) -> float:
    """El área con signo (m²) de unas aristas orientadas (el borde de una región)."""
    edges = np.asarray(edges, dtype=np.float64)
    return 0.5 * float(np.sum(edges[:, 0, 0] * edges[:, 1, 1] - edges[:, 1, 0] * edges[:, 0, 1]))


def _clip_area(domain, scope) -> float:
    return _edges_area(polygons.clip_to_scope(domain, scope, origin=(WEST, SOUTH)))


def _wavy(p: np.ndarray, q: np.ndarray, count: int, amplitude: float, seed: int) -> np.ndarray:
    t = np.linspace(0.0, 1.0, count)
    points = p[None, :] + t[:, None] * (q - p)[None, :]
    normal = np.array([-(q - p)[1], (q - p)[0]]) / math.hypot(*(q - p))
    offset = amplitude * np.sin(np.pi * t * (3 + seed % 5)) * np.sin(np.pi * t)
    return points + offset[:, None] * normal[None, :]


def _partition(columns: int, rows: int, box: tuple[float, float, float, float],
               count: int = 12) -> tuple[list[np.ndarray], np.ndarray]:
    """``columns × rows`` anillos ABSOLUTOS que parten el rectángulo ``box`` (relativo a WEST,
    SOUTH) con bordes interiores ondulados **comunes** (cada lado se genera una vez y el vecino
    lo recorre al revés, con los mismos vértices), y ese rectángulo."""
    xs = np.linspace(box[0], box[2], columns + 1)
    ys = np.linspace(box[1], box[3], rows + 1)
    sides: dict[tuple, np.ndarray] = {}

    def side(p: np.ndarray, q: np.ndarray) -> np.ndarray:
        key = (tuple(p), tuple(q))
        if key[::-1] in sides:
            return sides[key[::-1]][::-1]
        if key not in sides:
            straight = (p[0] == q[0] and p[0] in (xs[0], xs[-1])) or (
                p[1] == q[1] and p[1] in (ys[0], ys[-1]))
            seed = int(abs(p[0] * 7 + p[1] * 13 + q[0] * 3 + q[1])) % 97
            sides[key] = _wavy(p, q, count, 0.0 if straight else 1.5, seed)
        return sides[key]

    rings = []
    for i in range(columns):
        for j in range(rows):
            a, b = np.array([xs[i], ys[j]]), np.array([xs[i + 1], ys[j]])
            c, d = np.array([xs[i + 1], ys[j + 1]]), np.array([xs[i], ys[j + 1]])
            rings.append(_ring(np.concatenate(
                [side(a, b)[:-1], side(b, c)[:-1], side(c, d)[:-1], side(d, a)[:-1]])))
    return rings, _rect(xs[0], ys[0], xs[-1], ys[-1])


def _layer_with_problems() -> list:
    """Una capa con un polígono de cada problema de RF-011-08 y uno válido."""
    return [
        _polygon(1, "Fase 1", _rect(0, 0, 10, 10)),                           # válido
        _polygon(2, "Fase 2", _ring([[20, 0], [30, 0], [20, 10], [30, 10]])),  # pajarita
        _polygon(3, "Fase 3", _ring([[40, 0], [50, 0], [45, 0]])),             # sin área
        _polygon(4, "", _rect(0, 20, 10, 30)),                                 # campo vacío
        _polygon(5, "Fase 5", _rect(20, 20, 30, 30)),
        _polygon(6, "Fase 6", _rect(25, 23, 40, 27)),                          # 5 × 4 = 20 m²
    ]


# Pruebas ----------------------------------------------------------------------------------


class ValidateTest(unittest.TestCase):
    def test_invalid_polygons_are_listed_and_rejected(self) -> None:
        """RF-011-08: un polígono que se corta a sí mismo, uno sin área, uno con el campo vacío y
        dos que se solapan se rechazan con ``res.domains_invalid`` y la lista: identificador,
        valor del campo, problema y, en un solape, su área en m² (exacta en rectángulos: 20)."""
        layer = _layer_with_problems()
        found = polygons.problems(layer)
        self.assertEqual(
            [(p.code, p.fid, p.value, p.other_fid, p.other_value) for p in found],
            [("res.domain_self_intersecting", 2, "Fase 2", None, None),
             ("res.domain_no_area", 3, "Fase 3", None, None),
             ("res.domain_value_empty", 4, "", None, None),
             ("res.domain_overlap", 5, "Fase 5", 6, "Fase 6")],
        )
        self.assertEqual(found[-1].area_m2, 20.0)
        self.assertEqual([p.area_m2 for p in found[:-1]], [None, None, None])
        with self.assertRaises(ResError) as caught:
            polygons.validate(layer, field=FIELD, layer=LAYER)
        error = caught.exception
        self.assertEqual(error.code, "res.domains_invalid")
        self.assertEqual(error.field, FIELD)
        self.assertEqual(error.value, 4)
        self.assertEqual(error.problems, found)
        self.assertEqual(
            str(error),
            "La capa de dominios «Fases 2027» no sirve para repartir por «fase»: el polígono 2 "
            "(«Fase 2») se corta a sí mismo; el polígono 3 («Fase 3») no tiene área; el "
            "polígono 4 tiene vacío el campo «fase»; los polígonos 5 («Fase 5») y 6 («Fase 6») "
            "se solapan en 20,00 m². Corríjala y vuelva a importarla; no se ha cubicado nada.",
        )
        # En inglés, la plantilla del msgid (el número, en el idioma activo de la interfaz).
        self.assertTrue(found[-1].text(FIELD, "en").startswith(
            "polygons 5 («Fase 5») and 6 («Fase 6») overlap over 20"))
        self.assertEqual(found[0].text(FIELD, "en"), "polygon 2 («Fase 2») intersects itself")
        self.assertEqual(found[2].text(FIELD, "en"), "polygon 4 has an empty «fase»")
        self.assertIsNone(polygons.validate(layer[:1] + layer[4:5], field=FIELD, layer=LAYER))

    def test_an_invalid_scope_is_listed_and_rejected(self) -> None:
        """RF-011-01 (regresión de la T37; como RF-011-08): un ámbito con partes que se solapan
        contaría dos veces el solape, y uno que se corta a sí mismo daría pesos con signo; se
        rechaza con ``res.scope_invalid``, que nombra la capa, cada polígono, su problema y el
        área del solape. Sus polígonos no tienen valor: no es un problema. Partes que solo
        comparten un lado sí valen."""
        scope = [
            _polygon(1, "", _rect(0, 0, 10, 10)),
            _polygon(2, "", _ring([[20, 0], [30, 0], [20, 10], [30, 10]])),  # pajarita
            _polygon(3, "", _ring([[40, 0], [50, 0], [45, 0]])),             # sin área
            _polygon(4, "", _rect(5, 5, 15, 15)),                            # 5 × 5 = 25 m²
        ]
        found = polygons.scope_problems(scope)
        self.assertEqual([(p.code, p.fid, p.other_fid, p.area_m2) for p in found],
                         [("res.scope_self_intersecting", 2, None, None),
                          ("res.scope_no_area", 3, None, None),
                          ("res.scope_overlap", 1, 4, 25.0)])
        with self.assertRaises(ResError) as caught:
            polygons.validate_scope(scope, layer="Ámbito sur")
        error = caught.exception
        self.assertEqual(error.code, "res.scope_invalid")
        self.assertEqual(error.value, 3)
        self.assertEqual(error.problems, found)
        self.assertEqual(
            str(error),
            "La capa «Ámbito sur» no sirve de ámbito: el polígono 2 se corta a sí mismo; el "
            "polígono 3 no tiene área; los polígonos 1 y 4 se solapan en 25,00 m². Corríjala y "
            "vuelva a importarla; no se ha cubicado nada.")
        self.assertEqual(found[-1].text("", "en")[:30], "polygons 1 and 4 overlap over ")
        side_by_side = [_polygon(1, "", _rect(0, 0, 10, 10)), _polygon(2, "", _rect(10, 0, 20, 10))]
        self.assertEqual(polygons.scope_problems(side_by_side), ())
        self.assertIsNone(polygons.validate_scope(side_by_side, layer="Ámbito sur"))

    def test_the_domains_of_a_layer_one_polygon_per_part(self) -> None:
        """RF-011-07, RF-011-08, RF-011-20 (T32): las entidades de una capa de dominios
        (``gis.store.DomainFeature``) dan un polígono por parte, con su número y el valor de su
        campo como texto (un entero, sus cifras; sin valor, vacío: lo rechaza la validación);
        un campo que la capa no tiene, ``ValueError``."""
        square, hole = _rect(0.0, 0.0, 10.0, 10.0), _rect(2.0, 2.0, 4.0, 4.0)[::-1]
        other = _rect(20.0, 0.0, 30.0, 10.0)
        features = (SimpleNamespace(fid=4, attributes={FIELD: 7, "n": "a"},
                                    polygons=((square, hole), (other,))),
                    SimpleNamespace(fid=9, attributes={FIELD: None, "n": "b"},
                                    polygons=((_rect(40.0, 0.0, 50.0, 10.0),),)))
        found = polygons.domain_polygons(features, FIELD)
        self.assertEqual([(p.fid, p.value, len(p.rings)) for p in found],
                         [(4, "7", 2), (4, "7", 1), (9, "", 1)])
        self.assertIs(found[0].rings[1], hole)
        self.assertEqual([p.code for p in polygons.problems(found)], ["res.domain_value_empty"])
        self.assertEqual(polygons.domain_polygons(features, "n")[2].value, "b")
        with self.assertRaises(ValueError):
            polygons.domain_polygons(features, "fase_2")

    def test_other_invalid_geometries(self) -> None:
        """RF-011-08, A6: también se cortan a sí mismos uno con un pico que vuelve sobre su lado,
        uno con un hueco que toca el exterior y uno cuyos lados no contiguos pasan a ≤ 1 mm; no
        tiene área uno de ≤ 1 mm² o con vértices a ≤ 1 mm; y un hueco fuera del exterior o dentro
        de otro hueco no vale. Un polígono con un hueco bien puesto, sí."""
        cases = {
            "pico": (_ring([[0, 0], [10, 0], [10, 10], [5, 10], [5, 15], [5, 10], [0, 10]]),),
            "hueco que toca": (_rect(0, 0, 10, 10), _ring([[0, 0], [3, 2], [2, 3]])),
            "cuello de 0,5 mm": (_ring([[0, 0], [10, 0], [10, 4.9995], [5, 4.9995], [5, 5.0],
                                        [10, 5.0], [10, 10], [0, 10]]),),
            "1 mm²": (_ring([[0, 0], [0.002, 0], [0.002, 0.0005], [0, 0.0005]]),),
            "vértices a 1 mm": (_ring([[0, 0], [10, 0], [10.0004, 0.0003]]),),
            "hueco fuera": (_rect(0, 0, 10, 10), _rect(20, 20, 22, 22)),
            "hueco en un hueco": (_rect(0, 0, 10, 10), _rect(2, 2, 8, 8), _rect(4, 4, 5, 5)),
        }
        expected = {
            "pico": "res.domain_self_intersecting",
            "hueco que toca": "res.domain_self_intersecting",
            "cuello de 0,5 mm": "res.domain_self_intersecting",
            "1 mm²": "res.domain_no_area",
            "vértices a 1 mm": "res.domain_no_area",
            "hueco fuera": "res.domain_hole_outside",
            "hueco en un hueco": "res.domain_hole_outside",
        }
        for fid, (name, rings) in enumerate(cases.items(), start=1):
            with self.subTest(name):
                found = polygons.problems([_polygon(fid, name, *rings)])
                self.assertEqual([(p.code, p.fid) for p in found], [(expected[name], fid)])
        self.assertEqual(
            polygons.problems([_polygon(1, "Fase 1", _rect(0, 0, 10, 10), _rect(2, 2, 8, 8))]),
            (),
        )
        text = polygons.problems([_polygon(7, "Fase 7", *cases["hueco fuera"])])[0].text(FIELD)
        self.assertEqual(text, "el polígono 7 («Fase 7») tiene un hueco fuera de su contorno o "
                               "dentro de otro hueco")

    def test_shared_sides_and_contacts_do_not_overlap(self) -> None:
        """RF-011-08, A6: dos polígonos que comparten un lado entero o en parte, que solo se tocan
        en una esquina o que, dibujados a mano, dejan un solape de 0,4 mm (≤ 1 mm) no se
        solapan; una partición con bordes ondulados comunes, tampoco. Dos cuadrados girados que
        se solapan dan el área de Sutherland–Hodgman (≤ 10⁻¹²)."""
        layer = [
            _polygon(1, "A", _rect(0, 0, 10, 10)),
            _polygon(2, "B", _rect(10, 0, 20, 10)),        # lado común entero con A
            _polygon(3, "C", _rect(0, 10, 5, 20)),         # medio lado con A
            _polygon(4, "D", _rect(20, 10, 30, 20)),       # una esquina con B
            _polygon(5, "E", _rect(6, 9.9996, 9, 14)),     # 0,4 mm dentro de A, a mano
        ]
        self.assertEqual(polygons.overlaps(layer), ())
        self.assertEqual(polygons.problems(layer), ())
        rings, _ = _partition(4, 3, (3.3, 2.1, 83.7, 61.9))
        partition = [_polygon(fid, f"Zona {fid}", ring) for fid, ring in enumerate(rings, 1)]
        self.assertEqual(polygons.overlaps(partition), ())
        first = _square(20.0, 0.3, (100.0, 100.0))
        second = _square(16.0, 0.9, (108.0, 104.0))
        found = polygons.overlaps([_polygon(1, "P", first), _polygon(2, "Q", second)])
        self.assertEqual([(o.first, o.second) for o in found], [(0, 1)])
        reference = _sh_area(first, second)
        self.assertGreater(reference, 50.0)
        self.assertLessEqual(abs(found[0].area_m2 - reference) / reference, TOLERANCE)


class ClipTest(unittest.TestCase):
    def test_the_cases_of_the_prototype(self) -> None:
        """RF-011-01, A6, D-21: el recorte por el ámbito da el área exacta: dos rectángulos que se
        cruzan, 20 m²; un dominio con un lado común con el ámbito en el mismo sentido, 100 m²; dos
        que solo se tocan, nada; una L contra un cuadrado girado con un hueco, la de Sutherland–
        Hodgman (≤ 10⁻¹²; 1 640,42 m² en el plan, §2.2)."""
        domain = _polygon(1, "D", _rect(0, 0, 10, 10))
        self.assertEqual(_clip_area(domain, _polygon(0, "", _rect(5, 3, 20, 7))), 20.0)
        self.assertEqual(_clip_area(domain, _polygon(0, "", _rect(0, 0, 30, 10))), 100.0)
        touching = polygons.clip_to_scope(domain, _polygon(0, "", _rect(10, 0, 20, 10)),
                                          origin=(WEST, SOUTH))
        self.assertEqual(touching.shape, (0, 2, 2))
        outer = _square(60.0, 0.4, (40.0, 40.0))
        hole = _square(10.0, 0.4, (40.0, 40.0))
        letter = _ring([[0, 0], [60, 0], [60, 20], [20, 20], [20, 60], [0, 60]]) + 10.0
        area = _clip_area(_polygon(1, "L", letter), _polygon(0, "", outer, hole))
        reference = _sh_area(letter, outer) - _sh_area(letter, hole)
        self.assertAlmostEqual(reference, 1640.42, delta=0.01)
        self.assertLessEqual(abs(area - reference) / reference, TOLERANCE)

    def test_inside_outside_around_and_on_the_border(self) -> None:
        """RF-011-01, A6: un dominio entero dentro del ámbito es él mismo; entero fuera, nada; uno
        que rodea el ámbito, el ámbito (con su hueco); uno dibujado a mano 0,4 mm fuera del lado
        del ámbito, el del ámbito (tolerancia de 1 mm); y una partición de 20 polígonos con bordes
        ondulados, recortada por un cuadrado girado, da en cada uno el área de Sutherland–Hodgman
        y entre todos la del rectángulo recortado (≤ 10⁻¹²)."""
        scope = _polygon(0, "", _rect(0, 0, 50, 40), _rect(20, 15, 30, 25))
        inside = _polygon(1, "dentro", _ring([[2, 3], [12, 2], [9, 11]]))
        edges = polygons.clip_to_scope(inside, scope, origin=(WEST, SOUTH))
        self.assertEqual(edges.shape, (3, 2, 2))
        self.assertEqual(_edges_area(edges), 43.5)
        outside = _polygon(2, "fuera", _rect(60, 0, 70, 10))
        self.assertEqual(polygons.clip_to_scope(outside, scope, origin=(WEST, SOUTH)).shape,
                         (0, 2, 2))
        around = _polygon(3, "alrededor", _rect(-10, -10, 60, 50))
        self.assertEqual(_clip_area(around, scope), 50 * 40 - 10 * 10)
        sloppy = _polygon(4, "a mano", _rect(-0.0004, -0.0003, 10, 10.0004))
        self.assertEqual(_clip_area(sloppy, _polygon(0, "", _rect(0, 0, 10, 10))), 100.0)
        rings, box = _partition(5, 4, (3.3, 2.1, 103.7, 81.9))
        window = _square(70.0, 0.35, (60.0, 45.0))
        areas = []
        for fid, ring in enumerate(rings, 1):
            with self.subTest(fid=fid):
                area = _clip_area(_polygon(fid, "zona", ring), _polygon(0, "", window))
                reference = _sh_area(ring, window)
                self.assertLessEqual(abs(area - reference), TOLERANCE * max(reference, 1.0))
                areas.append(area)
        total = _sh_area(box, window)
        self.assertLessEqual(abs(math.fsum(areas) - total) / total, TOLERANCE)
        on_border = [_clip_area(_polygon(fid, "zona", ring), _polygon(0, "", box))
                     for fid, ring in enumerate(rings, 1)]
        for ring, area in zip(rings, on_border, strict=True):
            self.assertAlmostEqual(area, abs(coverage.signed_area(ring)),
                                   delta=TOLERANCE * area)

    def test_a_pair_with_thousands_of_vertices(self) -> None:
        """A6, RNF-011-04: el recorte de un par de polígonos de 2 000 vértices cada uno, que se
        cortan en decenas de puntos, tarda ≤ 20 ms (la mejor de tres) y da la misma área en los
        dos sentidos (≤ 10⁻¹²), menor que la de cada uno."""
        t = np.linspace(0.0, 2.0 * np.pi, 2000, endpoint=False)
        first = np.stack([60.0 + (40.0 + 3.0 * np.sin(37 * t)) * np.cos(t),
                          60.0 + (40.0 + 3.0 * np.sin(37 * t)) * np.sin(t)], axis=1)
        second = np.stack([80.0 + (35.0 + 4.0 * np.sin(23 * t + 0.5)) * np.cos(t),
                           67.0 + (35.0 + 4.0 * np.sin(23 * t + 0.5)) * np.sin(t)], axis=1)
        domain, scope = _polygon(1, "D", _ring(first)), _polygon(2, "S", _ring(second))
        best = timing.best_of(
            lambda: polygons.clip_to_scope(domain, scope, origin=(WEST, SOUTH)), PAIR_BUDGET_S)
        self.assertLessEqual(best, PAIR_BUDGET_S)
        area = _clip_area(domain, scope)
        self.assertLessEqual(abs(area - _clip_area(scope, domain)) / area, TOLERANCE)
        self.assertLess(area, min(abs(coverage.signed_area(first)),
                                  abs(coverage.signed_area(second))))
        self.assertGreater(area, 1000.0)


class WeightsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.grid = Grid(WEST, SOUTH + 60.0, 1.0, 1.0, 80, 60)
        rings, _ = _partition(4, 3, (3.3, 2.1, 70.7, 52.9))
        values = ["Fase 1", "Fase 2", "Fase 3", "Fase 1"] + [f"Zona {k}" for k in range(8)]
        self.layer = [_polygon(fid, value, ring)
                      for fid, (value, ring) in enumerate(zip(values, rings, strict=True), 1)]
        self.scope = _polygon(0, "", _square(40.0, 0.5, (50.0, 30.0)))

    def _dense(self, weights) -> np.ndarray:
        out = np.zeros((*self.grid.shape, weights.count + 1))
        out[weights.rows, weights.cols, weights.domain] = weights.weight
        return out

    def test_the_outside_row_closes_with_the_scope(self) -> None:
        """RF-011-07, RF-011-01, A5, A6: con un ámbito que corta la partición, cada celda se
        reparte entre los dominios (recortados) y la fila «Fuera de los dominios», y la suma es la
        fracción de la celda dentro del ámbito (≤ 10⁻¹²); cada dominio, su área recortada (los
        polígonos con el mismo valor, juntos); por bandas, bit a bit lo mismo que de una vez."""
        grid = self.grid
        domains = polygons.domain_edges(self.layer, grid, scope=self.scope)
        self.assertEqual([d.value for d in domains],
                         ["Fase 1", "Fase 2", "Fase 3"] + [f"Zona {k}" for k in range(8)])
        scope = polygons.scope_edges(self.scope, grid)
        whole = polygons.weights([d.edges for d in domains], scope, grid, slice(None))
        self.assertEqual(whole.count, len(domains))
        self.assertEqual((whole.start, whole.stop), (0, grid.nrows))
        for name in ("rows", "cols", "domain"):
            self.assertEqual(getattr(whole, name).dtype, np.int64)
        dense = self._dense(whole)
        fraction = np.zeros(grid.shape)
        band = coverage.band_coverage(scope, grid, slice(None))
        fraction[band.rows, band.cols] = band.fraction
        np.testing.assert_array_equal(whole.scope, fraction)
        self.assertLessEqual(float(np.abs(dense.sum(axis=2) - fraction).max()), TOLERANCE)
        outside = dense[:, :, whole.count]
        self.assertGreater(float(outside.sum()), 10.0)
        for k, domain in enumerate(domains):
            area = float(np.sum(dense[:, :, k])) * grid.cell_area
            self.assertLessEqual(abs(area - _edges_area(domain.edges)), 1e-9 * max(area, 1.0))
        first = _clip_area(self.layer[0], self.scope) + _clip_area(self.layer[3], self.scope)
        self.assertAlmostEqual(_edges_area(domains[0].edges), first, delta=1e-9)
        for size in (5, 32):
            with self.subTest(rows=size):
                joined = np.zeros_like(dense)
                for start in range(0, grid.nrows, size):
                    part = polygons.weights([d.edges for d in domains], scope, grid,
                                            slice(start, start + size))
                    self.assertTrue(np.all((part.rows >= start) & (part.rows < start + size)))
                    self.assertEqual(part.scope.shape, (min(size, grid.nrows - start),
                                                        grid.ncols))
                    joined += self._dense(part)
                np.testing.assert_array_equal(joined, dense)

    def test_without_scope_and_without_domains(self) -> None:
        """RF-011-07, A5: sin ámbito, cada celda reparte 1 entre los dominios y la fila de fuera
        (≤ 10⁻¹²) y no hay fracción del ámbito; sin dominios, no hay entradas, solo el ámbito."""
        grid = self.grid
        domains = polygons.domain_edges(self.layer, grid)
        weights = polygons.weights([d.edges for d in domains], None, grid, slice(10, 30))
        self.assertIsNone(weights.scope)
        dense = self._dense(weights)
        self.assertLessEqual(float(np.abs(dense[10:30].sum(axis=2) - 1.0).max()), TOLERANCE)
        self.assertEqual(float(np.abs(dense[:10]).max()), 0.0)
        scope = polygons.scope_edges([self.scope], grid)
        alone = polygons.weights([], scope, grid, slice(None))
        self.assertEqual((alone.count, alone.weight.size), (0, 0))
        area = float(np.sum(alone.scope)) * grid.cell_area
        exact = abs(coverage.signed_area(self.scope.rings[0]))   # ≈ 1 600 m² (vértices girados)
        self.assertLessEqual(abs(area - exact) / exact, TOLERANCE)
        self.assertIsNone(polygons.weights([], None, grid, slice(None)).scope)

    def test_the_pyramid_quadrants_split_their_window(self) -> None:
        """RF-011-07, CE-011-01: los cuatro cuadrantes de la pirámide son una capa válida que parte
        su ventana: sin ámbito, la fila de fuera queda vacía (≤ 10⁻¹²)."""
        layer = [polygons.Polygon(q.fid, q.value, q.rings)
                 for q in fx.pyramid_quadrants(fx.pyramid_apexes(2.0)[23])]
        polygons.validate(layer, field=fx.QUADRANT_FIELD, layer="Cuadrantes")
        grid = fx.pyramid_grid(2.0)
        domains = polygons.domain_edges(layer, grid)
        weights = polygons.weights([d.edges for d in domains], None, grid, slice(None))
        outside = weights.weight[weights.domain == weights.count]
        self.assertLessEqual(float(np.abs(outside).sum()), TOLERANCE)


if __name__ == "__main__":
    unittest.main()
