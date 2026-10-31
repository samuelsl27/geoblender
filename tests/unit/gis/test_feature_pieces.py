# SPDX-License-Identifier: GPL-3.0-or-later
"""Una capa de entidades del proyecto leída por trozos (spec 012, T37; RF-012-08; RNF-012-04 y
RNF-012-06; plan 012 §5.2.3, A6).

``gis.store.feature_pieces`` lee ``gis_fea_`` por rangos de ``fid``, cada lectura con su conexión,
y descodifica en trozos de pocas entidades, con la caja del sector como filtro (la envolvente de
la cabecera del blob, sin descodificar). Aquí, cada cosa frente a lo de siempre,
``gis.store.read_features``:

- los trozos de una capa, unidos, son la capa entera: números, atributos y partes (X e Y
  absolutas) bit a bit, en el orden de su número, con trozos pequeños y lecturas cortas;
- con una caja, solo salen las entidades cuya caja la toca (las demás cuentan como leídas), cada
  una igual que en la capa entera;
- una cabecera que no es la que escribe Geoblender (sin envolvente) no se juzga: se descodifica;
- no se sostiene ninguna lectura entre dos trozos (otra operación puede escribir mientras tanto);
- ``feature_source`` y ``feature_sources`` (varias capas con una sola lectura: abrirla cuesta
  1,3 ms) rechazan al llamar, sin leer entidades, lo que ``load_features`` rechazaba.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.unit.core.constraints.test_operations import _LayersCase

gstore = import_geoblender("gis.store")
vector = import_geoblender("gis.vector")
messages = import_geoblender("gis.messages")

NAME = "gis_fea_trozos"
COLUMNS = (vector.FieldColumn("nombre", "nombre", "TEXT"),)
WEST, SOUTH = 699_000.5, 4_399_000.25
COUNT = 40


def _layer(kind: str, count: int, rng: np.random.Generator) -> Any:
    """``count`` entidades de la geometría ``kind`` al azar en 1 km² (con partes y huecos)."""
    parts = []
    for _ in range(count):
        x, y = WEST + rng.uniform(0, 1000.0), SOUTH + rng.uniform(0, 1000.0)
        if kind == "point":
            parts.append(tuple((np.array([[x + 3.0 * k, y]]),) for k in range(int(rng.integers(1, 3)))))
        elif kind == "line":
            parts.append(tuple(
                (np.column_stack([x + 40.0 * k + np.arange(4) * 5.0, y + rng.uniform(0, 9, 4)]),)
                for k in range(int(rng.integers(1, 3)))))
        else:
            w, h = rng.uniform(3.0, 30.0, 2)
            outer = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]])
            hole = np.array([[x + w / 4, y + h / 4], [x + w / 4, y + h / 2],
                             [x + w / 2, y + h / 2], [x + w / 2, y + h / 4], [x + w / 4, y + h / 4]])
            parts.append(((outer, hole),))
    return vector.FeatureLayer(
        kind, tuple(range(10, 10 + 3 * count, 3)), tuple(parts), COLUMNS,
        {"nombre": tuple(f"Entidad {index}" if index % 5 else None for index in range(count))})


def same(first: Any, second: Any) -> None:
    """Dos capas iguales bit a bit: geometría, números, columnas, atributos y partes."""
    assert first.kind == second.kind
    assert first.fids == second.fids, (first.fids, second.fids)
    assert first.columns == second.columns
    assert dict(first.values) == dict(second.values)
    assert len(first.parts) == len(second.parts)
    for mine, theirs in zip(first.parts, second.parts, strict=True):
        assert len(mine) == len(theirs)
        for a, b in zip(mine, theirs, strict=True):
            assert len(a) == len(b)
            for ring, other in zip(a, b, strict=True):
                np.testing.assert_array_equal(ring, other)
                assert ring.dtype == other.dtype == np.float64


def joined(pieces: list[Any]) -> Any:
    """Las entidades de unos trozos como una sola capa."""
    layers = [piece.layer for piece in pieces if piece.layer is not None]
    first = layers[0]
    return vector.FeatureLayer(
        first.kind, tuple(fid for found in layers for fid in found.fids),
        tuple(part for found in layers for part in found.parts), first.columns,
        {name: tuple(value for found in layers for value in found.values[name])
         for name in first.values})


class PiecesTest(_LayersCase):
    """Los trozos frente a ``read_features`` en las tres geometrías."""

    kinds = ("point", "line", "polygon")

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        rng = np.random.default_rng(37)
        for kind in cls.kinds:
            cls.write_layer(f"{NAME}_{kind}", _layer(kind, COUNT, rng))
        cls.write_layer("gis_pts_ajena", _layer("point", 3, rng))  # de otra familia

    def whole(self, kind: str) -> Any:
        return gstore.load_features(self.project, f"{NAME}_{kind}")

    def pieces(self, kind: str, **options: Any) -> list[Any]:
        source = gstore.feature_source(self.project, f"{NAME}_{kind}")
        return list(gstore.feature_pieces(self.project, source, **options))

    def test_the_pieces_are_the_whole_layer(self) -> None:
        """RF-012-08: unidos, los trozos son la capa de ``read_features``, bit a bit y en su
        orden, con lecturas de pocas filas (también una sola) y trozos de pocas entidades o de
        pocos bytes; cada trozo respeta sus límites y las filas leídas suman las de la tabla."""
        for kind in self.kinds:
            wanted = self.whole(kind)
            for options in ({}, {"rows": 7, "features": 3}, {"rows": 50, "piece_bytes": 200},
                            {"rows": 16, "features": 5, "piece_bytes": 1}):
                with self.subTest(kind=kind, options=options):
                    found = self.pieces(kind, **options)
                    same(joined(found), wanted)
                    self.assertEqual(sum(piece.scanned for piece in found), len(wanted))
                    if "features" in options:
                        self.assertTrue(all(len(piece.layer) <= options["features"]
                                            for piece in found))
                    if options.get("piece_bytes") == 1:  # un trozo cierra tras la primera entidad
                        self.assertTrue(all(len(piece.layer) == 1 for piece in found))
        self.assertGreater(len(self.pieces("polygon", rows=7, features=3)), COUNT // 7)
        one = self.pieces("point", rows=1, features=1)  # una fila por lectura
        same(joined(one), self.whole("point"))
        self.assertEqual(len(one), COUNT)

    def test_a_window_skips_what_is_apart_and_counts_it_as_read(self) -> None:
        """Con una caja solo salen las entidades cuya caja la toca, cada una como en la capa
        entera; las demás suman a las filas leídas. Una caja que lo deja todo fuera da trozos sin
        capa; una enorme, todo."""
        window = (WEST + 200.0, SOUTH + 200.0, WEST + 800.0, SOUTH + 800.0)
        for kind in self.kinds:
            wanted = self.whole(kind)
            touching = []
            for index, fid in enumerate(wanted.fids):
                points = np.vstack([path for part in wanted.parts[index] for path in part])
                if (points[:, 0].max() >= window[0] and points[:, 0].min() <= window[2]
                        and points[:, 1].max() >= window[1] and points[:, 1].min() <= window[3]):
                    touching.append(index)
            with self.subTest(kind=kind):
                self.assertTrue(5 < len(touching) < len(wanted.fids))
                for options in ({}, {"rows": 9, "features": 4}):
                    found = self.pieces(kind, window=window, **options)
                    kept = joined(found)
                    same(kept, vector.FeatureLayer(
                        wanted.kind, tuple(wanted.fids[i] for i in touching),
                        tuple(wanted.parts[i] for i in touching), wanted.columns,
                        {name: tuple(values[i] for i in touching)
                         for name, values in wanted.values.items()}))
                    self.assertEqual(sum(piece.scanned for piece in found), len(wanted))
                nothing = self.pieces(kind, window=(0.0, 0.0, 1.0, 1.0), rows=40)
                self.assertTrue(all(piece.layer is None for piece in nothing))
                self.assertEqual(sum(piece.scanned for piece in nothing), len(wanted))
                everything = self.pieces(kind, window=(0.0, 0.0, 1e7, 1e7))
                same(joined(everything), wanted)

    def test_a_header_without_envelope_is_decoded_not_judged(self) -> None:
        """Una geometría cuya cabecera no lleva la envolvente que escribe Geoblender (otro
        escritor) no se juzga por ella: se descodifica entera y sale aunque la caja la deje
        fuera; el resto, no."""
        name = f"{NAME}_point"
        with self.project.read() as conn:
            fid, blob = conn.execute(f'SELECT fid, geom FROM "{name}" ORDER BY fid LIMIT 1 '
                                     'OFFSET 5').fetchone()
        self.assertEqual(blob[3], 0b11)  # lleva envolvente: 4 doubles tras la cabecera
        bare = blob[:3] + b"\x01" + blob[4:8] + blob[40:]
        with self.project.write_transaction() as conn:
            conn.execute(f'UPDATE "{name}" SET geom = ? WHERE fid = ?', (bare, fid))
        try:
            wanted = self.whole("point")
            index = wanted.fids.index(fid)
            window = (0.0, 0.0, 1.0, 1.0)  # lejos de todo
            found = [piece for piece in self.pieces("point", window=window, rows=40)
                     if piece.layer is not None]
            self.assertEqual(len(found), 1)
            same(found[0].layer, vector.FeatureLayer(
                wanted.kind, (fid,), (wanted.parts[index],), wanted.columns,
                {key: (values[index],) for key, values in wanted.values.items()}))
        finally:
            with self.project.write_transaction() as conn:
                conn.execute(f'UPDATE "{name}" SET geom = ? WHERE fid = ?', (blob, fid))

    def test_no_read_is_held_between_two_pieces(self) -> None:
        """Entre dos trozos no queda ninguna lectura abierta: otra operación puede escribir en
        el proyecto mientras la búsqueda espera su siguiente paso (rollback journal: una lectura
        abierta bloquearía la escritura)."""
        source = gstore.feature_source(self.project, f"{NAME}_polygon")
        pieces = gstore.feature_pieces(self.project, source, rows=10, features=2)
        first = next(pieces)
        self.assertEqual(len(first.layer), 2)
        self.write_layer(f"{NAME}_otra", _layer("point", 3, np.random.default_rng(1)))
        rest = list(pieces)
        self.assertEqual(sum(piece.scanned for piece in rest) + first.scanned, COUNT)

    def test_the_source_rejects_when_called(self) -> None:
        """Una capa desconocida, la tabla que falta y un dato que no es de entidades se
        rechazan al pedir la fuente, como ``load_features``, y ``feature_pieces`` rechaza lo que
        no es un número positivo."""
        with self.assertRaises(messages.GisError) as caught:
            gstore.feature_source(self.project, "gis_fea_no_existe")
        self.assertEqual(caught.exception.code, "gis.dataset_unknown")
        with self.assertRaises(ValueError):
            gstore.feature_source(self.project, "gis_pts_ajena")
        self.write_layer(f"{NAME}_sin_tabla", _layer("point", 3, np.random.default_rng(2)))
        with self.project.write_transaction() as conn:
            conn.execute(f'DROP TABLE "{NAME}_sin_tabla"')
        with self.assertRaises(messages.GisError) as caught:
            gstore.feature_source(self.project, f"{NAME}_sin_tabla")
        self.assertEqual(caught.exception.code, "gis.dataset_file_missing")
        source = gstore.feature_source(self.project, f"{NAME}_line")
        self.assertEqual((source.name, source.table, source.kind),
                         (f"{NAME}_line", f"{NAME}_line", "line"))
        self.assertEqual([column.column for column in source.columns], ["nombre"])
        names = [f"{NAME}_polygon", f"{NAME}_point", f"{NAME}_line"]
        with mock.patch.object(type(self.project), "read", autospec=True,
                               side_effect=type(self.project).read) as spy:
            several = gstore.feature_sources(self.project, names)
        self.assertEqual(spy.call_count, 1)  # una sola lectura para todas
        self.assertEqual([item.name for item in several], names)
        self.assertEqual(several[2], source)
        with self.assertRaises(messages.GisError):
            gstore.feature_sources(self.project, [names[0], "gis_fea_no_existe", names[1]])
        for bad in (0, -3, True, 2.5):
            with self.assertRaises(ValueError, msg=bad):
                next(gstore.feature_pieces(self.project, source, rows=bad))


if __name__ == "__main__":
    unittest.main()
