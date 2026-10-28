# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipos, reglas y códigos de las restricciones (spec 012, T05; HU-012-2; RF-012-02,
RF-012-04, RF-012-13; plan 012 §5.2.1, §5.3.1, D-16, D-22 y D-23).

``core.constraints.model`` es Python puro de nivel 0: los once tipos de restricción
(``ConstraintType``) con su ``msgid`` y su español, qué pide cada uno (D-23) y qué prohíbe
(RF-012-13); las geometrías; la restricción, la intención del cliente, el sector y la búsqueda
de intocables como datos; y el código inmutable de una restricción (D-22), que sale de su
nombre al crearla y no cambia al renombrarla.
"""

from __future__ import annotations

import dataclasses
import re
import unittest
from datetime import date

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender

model = import_geoblender("core.constraints.model")
i18n = import_geoblender("core.i18n")

ConstraintType = model.ConstraintType
ConstraintParam = model.ConstraintParam
GeometryKind = model.GeometryKind
SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
CODE = re.compile(r"[a-z][a-z0-9_]*")

OUT, IN, WEIGHT, ACTIVE = ("buffer_out_m", "buffer_in_m", "weight", "active")
ALL_KINDS = {"polygon", "line", "point"}

# Plan §5.2.1 (D-23 y RF-012-13): ctype → (lo que pide, geometrías, límite, prohíbe el corte,
# prohíbe el relleno, sale del dominio por defecto).
TABLE: dict[str, tuple[tuple[str, ...], set[str], bool, bool, bool, bool]] = {
    "legal_limit": ((IN, ACTIVE), {"polygon"}, True, False, False, False),
    "action_perimeter": ((ACTIVE,), {"polygon"}, True, False, False, False),
    "untouchable": ((OUT, ACTIVE), ALL_KINDS, False, True, True, True),
    "exclusion": ((OUT, ACTIVE), ALL_KINDS, False, True, True, True),
    "no_cut": ((OUT, ACTIVE), ALL_KINDS, False, True, False, False),
    "fill_only": ((OUT, ACTIVE), ALL_KINDS, False, True, False, False),
    "restoration_only": ((OUT, ACTIVE), ALL_KINDS, False, True, False, False),
    "setback": ((OUT, ACTIVE), ALL_KINDS, False, True, False, False),
    "no_fill": ((OUT, ACTIVE), ALL_KINDS, False, False, True, False),
    "avoid": ((OUT, WEIGHT, ACTIVE), ALL_KINDS, False, False, False, False),
    "requires_access": ((OUT, ACTIVE), ALL_KINDS, False, False, False, False),
}


def tower(**changes: object) -> object:
    """Una restricción de punto completa (la torre de la línea de 132 kV)."""
    fields: dict[str, object] = {
        "uid": "a" * 32, "code": "torre_132", "name": "Torre 132 kV",
        "ctype": ConstraintType.UNTOUCHABLE, "kind": GeometryKind.POINT,
        "parts": ((fx.absolute([(186.25, 100.125)]),),), "priority": 0,
        "reason": "Servidumbre de la línea", "decided_by": "Propiedad",
        "decided_on": date(2026, 10, 1), "decision_uid": None, "intention_uid": None,
        "source_input": "b" * 32, "source_fid": 7, "layer": "core_constraint_point", "fid": 1,
    }
    fields.update(changes)
    return model.Constraint(**fields)


class TypesTest(unittest.TestCase):
    def test_the_eleven_types_with_their_spanish(self) -> None:
        """RF-012-02 (D-16): los once tipos del plan §5.2.1, con su código de ``ctype``, su
        ``msgid`` en inglés (distinto en cada uno) y su nombre en la interfaz en español
        («Banda de resguardo» para ``setback``)."""
        self.assertEqual([member.value for member in ConstraintType], list(TABLE))
        self.assertEqual(set(TABLE), set(fx.CONSTRAINT_TYPES))
        msgids = [member.label_msgid for member in ConstraintType]
        self.assertEqual(len(set(msgids)), len(msgids))
        for member in ConstraintType:
            with self.subTest(ctype=member.value):
                self.assertEqual(set(member.label_msgid) & SPANISH_LETTERS, set())
                self.assertEqual(i18n.translate("es", member.label_msgid),
                                 fx.CONSTRAINT_TYPES[member.value])
                self.assertEqual(member.label("es"), fx.CONSTRAINT_TYPES[member.value])
                self.assertEqual(member.label("en"), member.label_msgid)

    def test_what_each_type_requires_and_forbids(self) -> None:
        """RF-012-02, RF-012-04 (D-23): el límite legal pide su resguardo hacia dentro; el
        perímetro, nada; los demás, su resguardo hacia fuera; «preferible no afectar», además su
        peso; todos, «activa». Un límite solo es un polígono. RF-012-13: los intocables y las
        exclusiones salen del dominio y prohíben todo movimiento; sin corte, solo relleno, solo
        restauración y banda de resguardo prohíben el corte; sin relleno, el relleno;
        «preferible no afectar» y «requiere acceso» no prohíben nada; los límites prohíben fuera
        (no dentro: lo combinan las máscaras)."""
        for member in ConstraintType:
            requires, kinds, limit, cut, fill, domain = TABLE[member.value]
            with self.subTest(ctype=member.value):
                self.assertEqual(tuple(item.value for item in member.requires), requires)
                self.assertTrue(all(isinstance(item, ConstraintParam)
                                    for item in member.requires))
                self.assertEqual({kind.value for kind in member.geometry_kinds}, kinds)
                self.assertIs(member.is_limit, limit)
                self.assertIs(member.forbids_cut, cut)
                self.assertIs(member.forbids_fill, fill)
                self.assertIs(member.removes_from_domain, domain)
                self.assertTrue(member.accepts(GeometryKind.POLYGON))
                self.assertIs(member.accepts(GeometryKind.LINE), not limit)
                self.assertIs(member.accepts(GeometryKind.POINT), not limit)

    def test_geometry_kinds_and_parameters(self) -> None:
        """RF-012-01: tres geometrías (polígono, línea, punto), una por capa del proyecto, con
        su nombre en español; los cuatro parámetros de una restricción con su sufijo de clave
        (RF-012-02)."""
        self.assertEqual([kind.value for kind in GeometryKind], ["polygon", "line", "point"])
        self.assertEqual([kind.label("es") for kind in GeometryKind],
                         ["Polígono", "Línea", "Punto"])
        self.assertEqual([item.value for item in ConstraintParam], [OUT, IN, WEIGHT, ACTIVE])

    def test_intention_roles(self) -> None:
        """RF-012-26: los seis roles de una marca del cliente con su español; solo «explotar a
        una cota» pide la cota."""
        self.assertEqual([role.value for role in model.IntentionRole],
                         list(fx.INTENTION_ROLES))
        for role in model.IntentionRole:
            with self.subTest(role=role.value):
                self.assertEqual(role.label("es"), fx.INTENTION_ROLES[role.value])
                self.assertEqual(set(role.label_msgid) & SPANISH_LETTERS, set())
                self.assertIs(role.requires_elevation, role.value == "mine_to_elevation")


class CodeTest(unittest.TestCase):
    def test_code_from_the_name(self) -> None:
        """RF-012-02 (D-22): el código sale del nombre en ASCII, en minúsculas, sin tildes y con
        «_» en lugar de lo demás; con ``r_`` delante si no empieza por una letra y ``r`` si no
        queda nada; siempre ``[a-z][a-z0-9_]*``."""
        cases = {
            "Torre 132 kV": "torre_132_kv",
            "Línea eléctrica (Iberdrola)": "linea_electrica_iberdrola",
            "  Zona Ñ-3 ": "zona_n_3",
            "132 kV": "r_132_kv",
            "": "r",
            "¿?": "r",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                code = model.constraint_code(name, ())
                self.assertEqual(code, expected)
                self.assertIsNotNone(CODE.fullmatch(code))
        long_code = model.constraint_code("x" * 100, ())
        self.assertEqual(len(long_code), model.CODE_MAX_LENGTH)

    def test_codes_are_unique(self) -> None:
        """RF-012-02 (D-22): un código ya tomado (en cualquiera de las tres capas) recibe
        ``_2``, ``_3``…, también cuando el nombre llena la longitud máxima."""
        taken = {"torre", "torre_2"}
        self.assertEqual(model.constraint_code("Torre", taken), "torre_3")
        self.assertEqual(model.constraint_code("Torre", {"torre"}), "torre_2")
        full = model.constraint_code("y" * 100, ())
        second = model.constraint_code("y" * 100, {full})
        self.assertNotEqual(second, full)
        self.assertEqual(len(second), model.CODE_MAX_LENGTH)
        self.assertTrue(second.endswith("_2"))

    def test_renaming_keeps_the_code(self) -> None:
        """RF-012-02 (D-22): el código es inmutable: renombrar una restricción no lo cambia, y
        con él tampoco sus parámetros."""
        first = tower()
        renamed = dataclasses.replace(first, name="Apoyo 14 de la línea")
        self.assertEqual(renamed.code, "torre_132")
        self.assertEqual(renamed.param_key(ConstraintParam.BUFFER_OUT),
                         first.param_key(ConstraintParam.BUFFER_OUT))
        self.assertEqual(first.param_key(ConstraintParam.BUFFER_OUT),
                         "core.constraint.torre_132.buffer_out_m")
        self.assertTrue(model.is_code("torre_132"))
        for wrong in ("", "Torre", "1torre", "torre 132", "torre-132", None):
            with self.subTest(code=wrong):
                self.assertFalse(model.is_code(wrong))


class RecordsTest(unittest.TestCase):
    def test_constraint_keeps_absolute_float64(self) -> None:
        """RF-012-01, RF-012-02: la geometría se guarda absoluta en float64, bit a bit, como
        tuplas de anillos o caminos ``(k, 2)``; el tipo y la geometría se normalizan a sus
        enumeraciones y un tipo ausente (dibujada en QGIS) es ``None``."""
        point = fx.absolute([(186.25, 100.125)])
        found = tower(ctype="untouchable", kind="point", parts=((point.tolist(),),))
        self.assertIs(found.ctype, ConstraintType.UNTOUCHABLE)
        self.assertIs(found.kind, GeometryKind.POINT)
        stored = found.parts[0][0]
        self.assertEqual(stored.dtype, np.float64)
        self.assertEqual(stored.shape, (1, 2))
        self.assertEqual(stored.tobytes(), point.tobytes())
        self.assertFalse(stored.flags.writeable)
        self.assertIsNone(tower(ctype=None).ctype)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            found.name = "otra"  # type: ignore[misc]
        with self.assertRaises(ValueError):
            tower(ctype="landslide")
        with self.assertRaises(ValueError):
            tower(parts=((np.zeros((3, 3)),),))

    def test_constraint_shown_name(self) -> None:
        """RF-012-04: lo que nombra una restricción en una lista: su nombre, o su código, o su
        capa y su fid si se dibujó en QGIS sin rellenar nada."""
        self.assertEqual(tower().shown_name("es"), "Torre 132 kV")
        self.assertEqual(tower(name="").shown_name("es"), "torre_132")
        bare = tower(name="", code="")
        self.assertEqual(bare.shown_name("es"), "Sin nombre (core_constraint_point, fid 1)")
        self.assertEqual(bare.shown_name("en"), "Unnamed (core_constraint_point, fid 1)")

    def test_intention_sector_and_search(self) -> None:
        """RF-012-07, RF-012-09, RF-012-26: la intención (rol, cota solo si la pide), el sector
        (anillos absolutos float64) y la búsqueda con sus entidades halladas: convertida con su
        restricción o descartada con su motivo."""
        ring = fx.rectangle(0, 0, 100, 100)
        intention = model.Intention(
            uid="c" * 32, name="Plataforma de acopio", role="mine_to_elevation",
            kind="polygon", parts=((ring,),), elevation_m=712.5,
            stated_on=date(2026, 9, 30), document_input="d" * 32, decision_uid=None,
            source_input="e" * 32, source_fid=3, fid=1)
        self.assertIs(intention.role, model.IntentionRole.MINE_TO_ELEVATION)
        self.assertEqual(intention.parts[0][0].tobytes(), ring.tobytes())
        with self.assertRaises(ValueError):
            dataclasses.replace(intention, elevation_m=None)
        with self.assertRaises(ValueError):
            dataclasses.replace(intention, role="protect")
        sector = model.Sector(uid="f" * 32, code="norte", name="Norte", rings=(ring.tolist(),))
        self.assertEqual(sector.rings[0].tobytes(), ring.tobytes())
        record = model.SearchRecord(
            uid="1" * 32, operation_uid="2" * 32, sector_code="norte", sector_sha256="3" * 64,
            distance_m=25.0, closed_by="samuel@pc", closed_at="2026-10-28T10:00:00.000Z")
        self.assertEqual(record.distance_m, 25.0)
        converted = model.SearchHit(
            search_uid=record.uid, layer_dataset="gis_fea_infra_12345678", feature_fid=4,
            distance_m=11.5, attributes={"nombre": "Torre 14"}, decision="converted",
            reason="Torre de alta tensión", constraint_code="torre_14")
        self.assertIs(converted.decision, model.HitDecision.CONVERTED)
        with self.assertRaises(ValueError):
            dataclasses.replace(converted, constraint_code=None)
        with self.assertRaises(ValueError):
            dataclasses.replace(converted, decision="discarded", reason=" ")
        discarded = dataclasses.replace(converted, decision="discarded", constraint_code=None,
                                        reason="Fuera de servicio")
        self.assertIs(discarded.decision, model.HitDecision.DISCARDED)
        with self.assertRaises(ValueError):
            dataclasses.replace(discarded, constraint_code="torre_14")


if __name__ == "__main__":
    unittest.main()
