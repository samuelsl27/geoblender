# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrato de procedencia de los módulos y mensajes de la procedencia (spec 008, T15;
RF-008-17, RF-008-25; ADR-0025 §2; plan 008 §5.1 y §5.3.1).

Cada módulo **declara** sus tipos de operación (:class:`OperationDef`), sus grupos de
operaciones acopladas (:class:`CoupledGroupDef`), sus cifras (:class:`FigureDef`) y sus
importadores (:class:`ImporterDef`) con tipos de ``core`` y los **registra** desde ``bl/``
(``core`` no importa los módulos, ADR-0004). Las declaraciones mal formadas se rechazan al
crearlas o al registrarlas: un tipo que no es ``<código>.<acción>``, una versión del algoritmo
que no es ``M.m``, una operación repetible sin función de recálculo, un grupo con tipos sin
registrar y dos registros del mismo tipo. Quitar lo registrado deja el registro como estaba.
``core`` declara sus propias operaciones: ``core.external_edit``, ``core.accept_review`` y
``core.import_layer`` (esta, sin recálculo ni importador hasta T34).

``core.provenance.messages`` da los mensajes de la procedencia con su código, su ``msgid`` en
inglés y su texto en español, y :class:`ProvenanceError` (principio 10).

Los registros son del proceso: cada prueba quita lo que registra y comprueba al terminar que
el registro quedó como lo encontró.
"""

from __future__ import annotations

import dataclasses
import string
import unittest
from collections.abc import Iterable
from typing import Any

from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered, snapshot

provenance = import_geoblender("core.provenance")
contract = import_geoblender("core.provenance.contract")
messages = import_geoblender("core.provenance.messages")
errors = import_geoblender("core.errors")
i18n = import_geoblender("core.i18n")
params = import_geoblender("core.params")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")


def _recompute(request: Any) -> Any:
    """Función de recálculo de prueba (nunca se llama aquí)."""
    return request


def _reimport(request: Any) -> Any:
    """Función de reimportación de prueba (nunca se llama aquí)."""
    return request


def op(op_type: str = "res.balance", version: str = "1.0", *, module: str | None = None,
       label: str = "Mass balance", repeatable: bool = True, **kw: Any) -> Any:
    """Un :class:`OperationDef` válido salvo lo que se cambie; repetible con recálculo."""
    if module is None:
        module = op_type.partition(".")[0] if isinstance(op_type, str) else "res"
    if repeatable is True and "recompute" not in kw:
        kw["recompute"] = _recompute
    return contract.OperationDef(op_type, version, module, label, repeatable, **kw)


def figure(key: str = "res.sellable_t", unit: str = "t", label: str = "Sellable tonnage",
           **kw: Any) -> Any:
    return contract.FigureDef(key, unit, label, **kw)


def _placeholders(text: str) -> set[str]:
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name}


class _RegistryCase(unittest.TestCase):
    """Comprueba al terminar cada prueba que el registro está como al empezarla."""

    def setUp(self) -> None:
        before = snapshot()
        # La primera limpieza que se añade es la última que se ejecuta: tras quitar lo que
        # registró la prueba (tearDown iría antes que las limpiezas).
        self.addCleanup(lambda: self.assertEqual(snapshot(), before,
                                                 "la prueba dejó algo registrado"))

    def register(self, *declarations: Any) -> None:
        """Registra en orden y lo quita al terminar la prueba, en orden inverso."""
        manager = registered(*declarations)
        manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)


class OperationDefTest(unittest.TestCase):
    def test_valid_declaration(self) -> None:
        """RF-008-17 (ADR-0025 §2): una declaración válida guarda su tipo, su versión, su
        módulo, su ámbito, sus órdenes y sus bibliotecas, y no se puede cambiar."""
        defn = op("gis.resample", "1.10", commands=["geoblender.gis_resample"],
                  libraries=["numpy"], group="gis.terrain")
        self.assertEqual(defn.op_type, "gis.resample")
        self.assertEqual(defn.module, "gis")
        self.assertEqual(defn.version, "1.10")
        self.assertEqual(defn.version_tuple, (1, 10))
        self.assertGreater(defn.version_tuple, op("gis.resample", "1.9").version_tuple)
        self.assertEqual(defn.scope, "project")
        self.assertEqual(defn.commands, ("geoblender.gis_resample",))
        self.assertEqual(defn.libraries, ("numpy",))
        self.assertEqual(defn.group, "gis.terrain")
        self.assertIs(defn.recompute, _recompute)
        self.assertEqual(op(scope="version").scope, "version")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            defn.version = "2.0"

    def test_type_is_code_dot_action(self) -> None:
        """RF-008-17 (ADR-0025 §2): el tipo es ``<código>.<acción>``, con un código de módulo
        de Geoblender y una acción en minúsculas; si no, se rechaza nombrándolo."""
        bad = ("gis", "gis.", ".resample", "gis.resample.fine", "GIS.resample", "gis.Resample",
               "gis.1resample", "gis.re-sample", "gis resample", "gis.resample ", "xyz.resample",
               "", "geoblender.gis_resample", "gis..resample", None, 3)
        for op_type in bad:
            with self.subTest(op_type=op_type), self.assertRaises(ValueError) as caught:
                op(op_type, module="gis")
            self.assertIn(repr(op_type), str(caught.exception))
        for good in ("gis.resample", "core.external_edit", "dh.desurvey", "res.balance2"):
            with self.subTest(good=good):
                self.assertEqual(op(good).op_type, good)

    def test_version_is_major_dot_minor(self) -> None:
        """RF-008-17, RF-008-24 (ADR-0025 §2): la versión del algoritmo es el texto ``M.m``
        (enteros sin ceros a la izquierda); cualquier otra forma se rechaza."""
        bad = ("1", "1.0.0", "v1.0", "01.0", "1.01", "1.a", " 1.0", "1.0 ", "", "1,0", "-1.0",
               "1.", ".1", "１.０", "1０.0", "1.1０", 1.0, 1, None)
        for version in bad:
            with self.subTest(version=version), self.assertRaises(ValueError) as caught:
                op(version=version)
            self.assertIn(repr(version), str(caught.exception))
        for good, expected in (("0.1", (0, 1)), ("1.0", (1, 0)), ("2.15", (2, 15)),
                               ("10.0", (10, 0))):
            with self.subTest(good=good):
                self.assertEqual(op(version=good).version_tuple, expected)
                self.assertEqual(contract.parse_version(good), expected)
        with self.assertRaises(ValueError):
            contract.parse_version("1.0.0")

    def test_repeatable_needs_recompute(self) -> None:
        """RF-008-26, RF-008-27 (ADR-0025 §2): una operación repetible declara su función de
        recálculo y una que no se repite sola (importación, edición a mano) no la tiene."""
        with self.assertRaises(ValueError) as caught:
            op(repeatable=True, recompute=None)
        self.assertIn("recompute", str(caught.exception))
        with self.assertRaises(ValueError):
            op(repeatable=False, recompute=_recompute)
        self.assertIsNone(op(repeatable=False).recompute)
        with self.assertRaises(TypeError):
            op(repeatable=1)
        with self.assertRaises(TypeError):
            op(recompute="res.balance")

    def test_drops_discarded_only_in_a_repeatable_type(self) -> None:
        """RF-008-26, RF-008-55 (spec 005, T42; plan 005 §5.6.10): un tipo cuyo recálculo
        reúne él mismo todo lo vigente (la base de los sondeos) lo declara con
        ``drops_discarded`` (por defecto, no); solo uno que se repite solo, y es verdadero o
        falso."""
        self.assertFalse(op().drops_discarded)
        self.assertTrue(op(drops_discarded=True).drops_discarded)
        with self.assertRaises(ValueError) as caught:
            op(repeatable=False, drops_discarded=True)
        self.assertIn("drops_discarded", str(caught.exception))
        with self.assertRaises(TypeError):
            op(drops_discarded=1)

    def test_other_fields_are_checked(self) -> None:
        """RF-008-17 (ADR-0025 §2): el módulo es el del tipo, el nombre visible un ``msgid``
        en inglés, el ámbito de proyecto o de versión, el grupo ``<código>.<nombre>``, las
        órdenes ``bl_idname`` de Geoblender y las bibliotecas nombres sin repetir."""
        cases: tuple[tuple[str, dict[str, Any]], ...] = (
            ("module", {"module": "dh"}),
            ("module", {"module": "xyz"}),
            ("label_msgid", {"label": ""}),
            ("label_msgid", {"label": "   "}),
            ("label_msgid", {"label": None}),
            ("label_msgid", {"label": "Edición externa"}),
            ("scope", {"scope": "sector"}),
            ("scope", {"scope": None}),
            ("group", {"group": "stockpiles"}),
            ("group", {"group": "xyz.stockpiles"}),
            ("group", {"group": ""}),
            ("commands", {"commands": "geoblender.res_balance"}),
            ("commands", {"commands": ("res.balance",)}),
            ("commands", {"commands": ("geoblender.xyz_balance",)}),
            ("commands", {"commands": ("geoblender.res_balance", "geoblender.res_balance")}),
            ("commands", {"commands": None}),
            ("libraries", {"libraries": "numpy"}),
            ("libraries", {"libraries": ("",)}),
            ("libraries", {"libraries": ("numpy", "numpy")}),
            ("libraries", {"libraries": ("num py",)}),
        )
        for name, change in cases:
            with self.subTest(name=name, change=change), self.assertRaises(ValueError) as caught:
                op(**change)
            self.assertIn(name, str(caught.exception))


class FigureDefTest(unittest.TestCase):
    def test_valid_declaration(self) -> None:
        """RF-008-30 (ADR-0025 §2): una cifra declara clave, unidad del catálogo, nombre
        visible y si admite cero o negativos (por defecto, cero sí y negativos no)."""
        defn = figure()
        self.assertEqual((defn.key, defn.unit, defn.label_msgid), ("res.sellable_t", "t",
                                                                     "Sellable tonnage"))
        self.assertEqual(defn.module, "res")
        self.assertTrue(defn.allow_zero)
        self.assertFalse(defn.allow_negative)
        net = figure("res.net_fill_m3", "m3", "Net fill", allow_negative=True, allow_zero=False)
        self.assertEqual((net.allow_zero, net.allow_negative), (False, True))
        self.assertEqual(figure("gis.slope_ratio", "-").unit, "-")

    def test_malformed_declarations_are_rejected(self) -> None:
        """RF-008-30 (ADR-0025 §2): la clave ``<código>.<nombre>``, la unidad por su código
        del catálogo (``m3``, no ``m³``) y un ``msgid`` en inglés; si no, se rechaza."""
        for key in ("sellable_t", "res", "xyz.sellable_t", "res.Sellable", "", None):
            with self.subTest(key=key), self.assertRaises(ValueError):
                figure(key)
        for unit in ("m³", "furlong", "", None):
            with self.subTest(unit=unit), self.assertRaises(ValueError) as caught:
                figure(unit=unit)
            self.assertIn("unidad", str(caught.exception))
        for label in ("", None, "Tonelaje vendible ñ"):
            with self.subTest(label=label), self.assertRaises(ValueError):
                figure(label=label)
        for name in ("allow_zero", "allow_negative"):
            with self.subTest(name=name), self.assertRaises(TypeError):
                figure(**{name: 1})


def setting(key: str = "interval_m", label: str = "Interval", **kw: Any) -> Any:
    """Un :class:`SettingDef` válido salvo lo que se cambie; un número en metros."""
    kw.setdefault("unit", "m")
    return contract.SettingDef(key, label, **kw)


class SettingDefTest(unittest.TestCase):
    def test_declaration(self) -> None:
        """RF-008-29 (spec 006, T58): un ajuste que enseña la procedencia de una operación
        dice dónde está en sus ajustes («.» entra en uno anidado), su nombre visible y su
        unidad (un número) o sus elecciones (cada valor guardado con el nombre con que se
        elige); un ``OperationDef`` los lleva en su orden (ninguno, por defecto), y los dos se
        comparan y no se pueden cambiar."""
        number = setting()
        choice = setting("read.decimal", "Decimal mark", unit=None,
                         choices=[(".", "Point"), (",", "Comma"), (None, "Automatic")])
        self.assertEqual((number.key, number.label_msgid, number.unit, number.choices),
                         ("interval_m", "Interval", "m", ()))
        self.assertEqual((choice.unit, choice.choices),
                         (None, ((".", "Point"), (",", "Comma"), (None, "Automatic"))))
        self.assertEqual([choice.choice_msgid(value) for value in (",", None, ";")],
                         ["Comma", "Automatic", None])
        self.assertEqual(setting("count", "Count", unit="-").unit, "-")
        defn = op(settings=[number, choice])
        self.assertEqual(defn.settings, (number, choice))
        self.assertEqual(defn, op(settings=(setting(), choice)))
        self.assertEqual(hash(defn), hash(op(settings=(setting(), choice))))
        self.assertEqual(op().settings, ())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            number.unit = "km"

    def test_malformed_settings_are_rejected(self) -> None:
        """RF-008-29 (spec 006, T58): una clave que no es un nombre en minúsculas, un nombre
        visible que no es un ``msgid`` en inglés, una unidad fuera del catálogo, un ajuste
        con unidad y elecciones o sin ninguna de las dos, una elección mal formada o repetida
        y un ``OperationDef`` con dos ajustes con la misma clave son errores del programa
        (``ValueError``); un ajuste que no es un ``SettingDef``, ``TypeError``."""
        cases: tuple[tuple[str, dict[str, Any]], ...] = (
            ("key", {"key": "Interval"}),
            ("key", {"key": "read..decimal"}),
            ("key", {"key": "read.decimal."}),
            ("key", {"key": ""}),
            ("key", {"key": None}),
            ("label_msgid", {"label": ""}),
            ("label_msgid", {"label": "Método"}),
            ("unit", {"unit": "m³"}),
            ("unit", {"unit": "metros"}),
            ("unit", {"unit": None}),
            ("unit", {"choices": [("a", "A")]}),
            ("choices", {"unit": None, "choices": [("a",)]}),
            ("choices", {"unit": None, "choices": [("a", "Opción")]}),
            ("choices", {"unit": None, "choices": [(["a"], "A")]}),
            ("choices", {"unit": None, "choices": [("a", "A"), ("a", "B")]}),
            ("choices", {"unit": None, "choices": "ab"}),
        )
        for name, change in cases:
            with self.subTest(name=name, change=change), self.assertRaises(ValueError) as caught:
                setting(**change)
            self.assertIn(name, str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            op(settings=[setting(), setting(label="Contour interval")])
        self.assertIn("settings", str(caught.exception))
        with self.assertRaises(ValueError):
            op(settings=setting())
        with self.assertRaises(TypeError):
            op(settings=[setting(), "interval_m"])


class ImporterDefTest(unittest.TestCase):
    def test_declaration(self) -> None:
        """RF-008-11 (ADR-0025 §2): un importador nombra el lector de contenido de sus
        entradas, sin versión (reimporta las de cualquier versión), y su función de
        reimportación."""
        defn = contract.ImporterDef("core.gpkg_layer", _reimport)
        self.assertEqual((defn.reader_id, defn.module), ("core.gpkg_layer", "core"))
        self.assertIs(defn.reimport, _reimport)
        for reader_id in ("core.gpkg_layer@1", "gpkg_layer", "Core.gpkg", "", None):
            with self.subTest(reader_id=reader_id), self.assertRaises(ValueError):
                contract.ImporterDef(reader_id, _reimport)
        with self.assertRaises(TypeError):
            contract.ImporterDef("core.gpkg_layer", None)


class CoupledGroupDefTest(unittest.TestCase):
    def test_declaration(self) -> None:
        """RF-008-25: un grupo de operaciones acopladas tiene nombre ``<código>.<nombre>`` y
        dos o más tipos distintos, en su orden de ejecución."""
        group = contract.CoupledGroupDef("res.stockpiles",
                                         ["res.detect_stockpiles", "res.filter_stockpiles"])
        self.assertEqual(group.op_types, ("res.detect_stockpiles", "res.filter_stockpiles"))
        self.assertEqual(group.module, "res")
        bad: tuple[tuple[Any, Any], ...] = (
            ("stockpiles", ("res.a", "res.b")),
            ("res.stockpiles", ("res.a",)),
            ("res.stockpiles", ("res.a", "res.a")),
            ("res.stockpiles", ("res.a", "res")),
            ("res.stockpiles", "res.a"),
            ("res.stockpiles", ()),
        )
        for name, op_types in bad:
            with self.subTest(name=name, op_types=op_types), self.assertRaises(ValueError):
                contract.CoupledGroupDef(name, op_types)


class RegistryTest(_RegistryCase):
    def test_register_and_find(self) -> None:
        """RF-008-17, RF-008-25 (ADR-0025 §2): lo registrado se encuentra en las vistas y con
        las búsquedas, que son de solo lectura."""
        detect = op("res.detect_stockpiles", group="res.stockpiles")
        filter_ = op("res.filter_stockpiles", group="res.stockpiles")
        group = contract.CoupledGroupDef("res.stockpiles", (detect.op_type, filter_.op_type))
        sellable = figure()
        importer = contract.ImporterDef("res.recmin", _reimport)
        self.register(detect, filter_, group, sellable, importer)
        self.assertIs(contract.OPERATIONS["res.detect_stockpiles"], detect)
        self.assertIs(contract.operation_def("res.filter_stockpiles"), filter_)
        self.assertIs(contract.GROUPS["res.stockpiles"], group)
        self.assertIs(contract.group_def("res.stockpiles"), group)
        self.assertIs(contract.FIGURES["res.sellable_t"], sellable)
        self.assertIs(contract.figure_def("res.sellable_t"), sellable)
        self.assertIs(contract.IMPORTERS["res.recmin"], importer)
        self.assertIs(contract.importer_def("res.recmin"), importer)
        for view in (contract.OPERATIONS, contract.GROUPS, contract.FIGURES,
                     contract.IMPORTERS):
            with self.assertRaises(TypeError):
                view["res.other"] = detect

    def test_two_registrations_of_the_same_type_are_rejected(self) -> None:
        """RF-008-17 (ADR-0025 §2): un tipo, una cifra, un grupo o un importador se registra
        una sola vez; el segundo registro se rechaza y el primero se queda."""
        first = op()
        self.register(first, figure(), contract.ImporterDef("res.recmin", _reimport))
        again: tuple[tuple[Any, Any, str], ...] = (
            (contract.register_operation, op(version="2.0"), "res.balance"),
            (contract.register_figure, figure(unit="kt"), "res.sellable_t"),
            (contract.register_importer, contract.ImporterDef("res.recmin", _recompute),
             "res.recmin"),
        )
        for register, declaration, name in again:
            with self.subTest(name=name), self.assertRaises(ValueError) as caught:
                register(declaration)
            self.assertIn(name, str(caught.exception))
        self.assertIs(contract.OPERATIONS["res.balance"], first)
        self.assertEqual(contract.FIGURES["res.sellable_t"].unit, "t")
        self.assertIs(contract.IMPORTERS["res.recmin"].reimport, _reimport)
        a = op("res.detect_stockpiles", group="res.stockpiles")
        b = op("res.filter_stockpiles", group="res.stockpiles")
        group = contract.CoupledGroupDef("res.stockpiles", (a.op_type, b.op_type))
        self.register(a, b, group)
        with self.assertRaises(ValueError):
            contract.register_group(contract.CoupledGroupDef("res.stockpiles",
                                                             (a.op_type, b.op_type)))
        self.assertIs(contract.GROUPS["res.stockpiles"], group)

    def test_group_with_unregistered_types_is_rejected(self) -> None:
        """RF-008-25: un grupo acoplado solo se registra con todos sus tipos ya registrados,
        cada uno declarándolo, sin que otro tipo lo declare fuera de él y todos igual de
        repetibles y del mismo ámbito (si no, se recalcularía una sin las demás)."""
        a = op("res.detect_stockpiles", group="res.stockpiles")
        b = op("res.filter_stockpiles", group="res.stockpiles")
        self.register(a)  # b, sin registrar
        loose = op("res.loose_a", group="res.loose")
        free = op("res.loose_b")  # no declara su grupo
        inside_a = op("res.inside_a", group="res.inside")
        inside_b = op("res.inside_b", group="res.inside")
        outsider = op("res.outsider", group="res.inside")  # lo declara sin estar en él
        manual = op("res.manual", repeatable=False, group="res.pair")
        auto = op("res.auto", group="res.pair")
        versioned = op("res.versioned", scope="version", group="res.scopes")
        projected = op("res.projected", group="res.scopes")
        self.register(loose, free, inside_a, inside_b, outsider, manual, auto, versioned,
                      projected)
        rejected = (
            (contract.CoupledGroupDef("res.stockpiles", (a.op_type, b.op_type)),
             "res.filter_stockpiles"),
            (contract.CoupledGroupDef("res.loose", (loose.op_type, free.op_type)),
             "res.loose_b"),
            (contract.CoupledGroupDef("res.inside", (inside_a.op_type, inside_b.op_type)),
             "res.outsider"),
            (contract.CoupledGroupDef("res.pair", (manual.op_type, auto.op_type)), "repet"),
            (contract.CoupledGroupDef("res.scopes", (versioned.op_type, projected.op_type)),
             "ámbito"),
        )
        for candidate, mentioned in rejected:
            with self.subTest(group=candidate.name), \
                    self.assertRaises(ValueError) as caught:
                contract.register_group(candidate)
            self.assertIn(mentioned, str(caught.exception))
        self.assertEqual({name for name in contract.GROUPS if name.startswith("res.")}, set())
        self.register(b)  # con todos sus tipos registrados, el grupo ya se registra
        self.register(contract.CoupledGroupDef("res.stockpiles", (a.op_type, b.op_type)))
        self.assertEqual(contract.GROUPS["res.stockpiles"].op_types,
                         ("res.detect_stockpiles", "res.filter_stockpiles"))

    def test_registered_group_closes_its_members(self) -> None:
        """RF-008-25: con el grupo registrado no se registra otro tipo que lo declare ni se
        quita uno de sus tipos (``unregister_group`` antes)."""
        a = op("res.detect_stockpiles", group="res.stockpiles")
        b = op("res.filter_stockpiles", group="res.stockpiles")
        self.register(a, b, contract.CoupledGroupDef("res.stockpiles", (a.op_type, b.op_type)))
        with self.assertRaises(ValueError):
            contract.register_operation(op("res.sum_stockpiles", group="res.stockpiles"))
        self.assertNotIn("res.sum_stockpiles", contract.OPERATIONS)
        with self.assertRaises(ValueError) as caught:
            contract.unregister_operation("res.detect_stockpiles")
        self.assertIn("res.stockpiles", str(caught.exception))
        self.assertIs(contract.OPERATIONS["res.detect_stockpiles"], a)

    def test_unregister_leaves_the_registry_as_it_was(self) -> None:
        """RF-008-17, RF-008-25 (ADR-0025 §2; principio 8): quitar lo registrado, en orden
        inverso, deja los cuatro registros como estaban, sin tocar lo de otro módulo; quitar
        lo que no está no hace nada."""
        self.register(op("dh.desurvey"), figure("dh.collar_count", "-", "Collars"))
        before = snapshot()
        a = op("res.detect_stockpiles", group="res.stockpiles")
        b = op("res.filter_stockpiles", group="res.stockpiles")
        group = contract.CoupledGroupDef("res.stockpiles", (a.op_type, b.op_type))
        contract.register_operation(a)
        contract.register_operation(b)
        contract.register_group(group)
        contract.register_figure(figure())
        contract.register_importer(contract.ImporterDef("res.recmin", _reimport))
        self.assertNotEqual(snapshot(), before)
        self.assertEqual(contract.unregister_importer("res.recmin"), 1)
        self.assertEqual(contract.unregister_figure("res.sellable_t"), 1)
        self.assertEqual(contract.unregister_group("res.stockpiles"), 1)
        self.assertEqual(contract.unregister_operation("res.filter_stockpiles"), 1)
        self.assertEqual(contract.unregister_operation("res.detect_stockpiles"), 1)
        self.assertEqual(snapshot(), before)
        for unregister, name in ((contract.unregister_importer, "res.recmin"),
                                 (contract.unregister_figure, "res.sellable_t"),
                                 (contract.unregister_group, "res.stockpiles"),
                                 (contract.unregister_operation, "res.detect_stockpiles")):
            with self.subTest(name=name):
                self.assertEqual(unregister(name), 0)
        self.assertEqual(snapshot(), before)
        self.assertIn("dh.desurvey", contract.OPERATIONS)
        self.assertIn("dh.collar_count", contract.FIGURES)

    def test_lookup_of_what_is_not_registered(self) -> None:
        """RF-008-17 (ADR-0025, «Negativas»): buscar un tipo, un grupo, una cifra o un
        importador sin registrar da un :class:`ProvenanceError` que lo nombra: el módulo que
        lo declara no está activo."""
        cases = (
            (contract.operation_def, "res.nothing", "core.operation_unregistered"),
            (contract.group_def, "res.nothing", "core.group_unregistered"),
            (contract.figure_def, "res.nothing", "core.figure_unregistered"),
            (contract.importer_def, "res.nothing", "core.importer_unregistered"),
        )
        for lookup, name, code in cases:
            with self.subTest(code=code), self.assertRaises(messages.ProvenanceError) as caught:
                lookup(name)
            self.assertEqual(caught.exception.code, code)
            self.assertIn("«res.nothing»", str(caught.exception))
            self.assertIsInstance(caught.exception, errors.GeoblenderError)

    def test_only_declarations_are_registered(self) -> None:
        """ADR-0025 §2: cada registro acepta solo su tipo de declaración."""
        wrong = (
            (contract.register_operation, figure()),
            (contract.register_group, op()),
            (contract.register_figure, op()),
            (contract.register_importer, figure()),
        )
        for register, declaration in wrong:
            with self.subTest(register=register.__name__), self.assertRaises(TypeError):
                register(declaration)
        for unregister in (contract.unregister_operation, contract.unregister_group,
                           contract.unregister_figure, contract.unregister_importer):
            with self.subTest(unregister=unregister.__name__), self.assertRaises(TypeError):
                unregister(None)


class CoreOperationsTest(_RegistryCase):
    def test_core_operations(self) -> None:
        """RF-008-17, RF-008-21, RF-008-27, RF-008-62 (plan §5.4.4, §5.4.9; D8, D9, D14): las
        operaciones de ``core`` son la edición externa (la de proyecto y, desde la spec 015, T20,
        la de un dato **de una versión**, RF-008-56, RF-015-11: una operación de proyecto no
        puede usarlo, D-14 de la 009), «dar por buena» y registrar una capa como entrada;
        ninguna se repite sola ni tiene recálculo, y ``core.import_layer`` no tiene importador
        hasta T34."""
        by_type = {defn.op_type: defn for defn in contract.CORE_OPERATIONS}
        self.assertEqual(set(by_type), {"core.external_edit", "core.external_edit_version",
                                        "core.accept_review", "core.import_layer"})
        self.assertEqual(contract.EXTERNAL_EDIT, "core.external_edit")
        self.assertEqual(contract.EXTERNAL_EDIT_VERSION, "core.external_edit_version")
        self.assertEqual(contract.ACCEPT_REVIEW, "core.accept_review")
        self.assertEqual(contract.IMPORT_LAYER, "core.import_layer")
        for defn in contract.CORE_OPERATIONS:
            with self.subTest(op_type=defn.op_type):
                self.assertEqual(defn.module, "core")
                self.assertEqual(defn.version, "1.0")
                self.assertFalse(defn.repeatable)
                self.assertIsNone(defn.recompute)
                self.assertIsNone(defn.group)
                self.assertEqual(defn.scope, "version" if defn.op_type == contract.EXTERNAL_EDIT_VERSION
                                 else "project")
                self.assertIn(defn.label_msgid, messages.CATALOG_ES)
        self.assertEqual(by_type["core.external_edit"].commands, ())
        self.assertEqual(by_type["core.external_edit_version"].commands, ())
        self.assertEqual(by_type["core.external_edit_version"].label_msgid,
                         by_type["core.external_edit"].label_msgid)
        self.assertEqual(by_type["core.accept_review"].commands,
                         ("geoblender.core_accept_review",))
        self.assertEqual(by_type["core.import_layer"].commands,
                         ("geoblender.core_resolve_unregistered",))
        before = snapshot()
        with registered(*contract.CORE_OPERATIONS):
            for defn in contract.CORE_OPERATIONS:
                self.assertIs(contract.operation_def(defn.op_type), defn)
            self.assertNotIn("core.gpkg_layer", contract.IMPORTERS)
        self.assertEqual(snapshot(), before)


class MessagesTest(unittest.TestCase):
    def _all(self) -> Iterable[tuple[str, str, str]]:
        for code, message in messages.MESSAGES.items():
            yield code, message.msgid, message.es
        for msgid, spanish in messages.LABELS.items():
            yield msgid, msgid, spanish

    def test_msgid_in_english_and_text_in_spanish(self) -> None:
        """Principio 10 (plan §3): todo mensaje de la procedencia tiene un código
        ``core.*``, un ``msgid`` en inglés y su texto en español, distintos y con los mismos
        marcadores; todo nombre visible, igual."""
        self.assertGreaterEqual(len(messages.MESSAGES), 5)
        self.assertGreaterEqual(len(messages.LABELS), 3)
        for code, message in messages.MESSAGES.items():
            with self.subTest(code=code):
                self.assertRegex(code, r"^core\.[a-z][a-z0-9_]*$")
                self.assertEqual(message.code, code)
        for name, msgid, spanish in self._all():
            with self.subTest(name=name):
                self.assertTrue(msgid.strip(), "msgid vacío")
                self.assertTrue(spanish.strip(), "texto en español vacío")
                self.assertNotEqual(msgid, spanish)
                self.assertEqual(set(msgid) & SPANISH_LETTERS, set(),
                                 f"msgid con letras del español: {msgid}")
                self.assertEqual(_placeholders(msgid), _placeholders(spanish))
                self.assertEqual(messages.CATALOG_ES[msgid], spanish)
        self.assertEqual(len(messages.CATALOG_ES),
                         len({msgid for _name, msgid, _es in self._all()}))

    def test_one_translation_per_msgid(self) -> None:
        """Principio 10: un ``msgid`` de la procedencia que también está en el catálogo de
        idioma o en el de los parámetros tiene allí la misma traducción (la tabla de
        ``core.i18n`` es una sola)."""
        others = {**i18n.load_messages(), **params.CATALOG_ES}
        for msgid, spanish in messages.CATALOG_ES.items():
            if msgid in others:
                with self.subTest(msgid=msgid):
                    self.assertEqual(others[msgid], spanish)

    def test_catalog_is_read_only(self) -> None:
        """Principio 10: el catálogo es fijo."""
        with self.assertRaises(TypeError):
            messages.MESSAGES["core.x"] = messages.Message("core.x", "X", "Equis")
        with self.assertRaises(TypeError):
            messages.CATALOG_ES["X"] = "Equis"
        with self.assertRaises(TypeError):
            messages.LABELS["X"] = "Equis"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            messages.MESSAGES["core.read_only"].es = "otro"

    def test_render(self) -> None:
        """Principio 10: ``render`` rellena los marcadores en español (o en inglés, el
        ``msgid``); el que falta queda «?» y un código o un idioma desconocido es un error
        del programa."""
        self.assertEqual(
            messages.render("core.operation_unregistered", op_type="gis.resample"),
            "No hay ninguna operación registrada del tipo «gis.resample»: el módulo que la "
            "declara no está activo o es de otra versión de Geoblender.",
        )
        self.assertEqual(
            messages.render("core.operation_unregistered", language="en",
                            op_type="gis.resample"),
            "No operation of type «gis.resample» is registered: the module that declares it "
            "is not active or belongs to another version of Geoblender.",
        )
        self.assertEqual(
            messages.render("core.read_only", project="Cantera Norte"),
            "El proyecto «Cantera Norte» está abierto en solo lectura (?): no se ha "
            "registrado nada.",
        )
        for code, values in (("core.no_such", {}), ("core.read_only", {"language": "fr"})):
            with self.subTest(code=code), self.assertRaises(ValueError):
                messages.render(code, **values)

    def test_provenance_error(self) -> None:
        """Principio 10: :class:`ProvenanceError` lleva el código, el ``msgid``, los valores
        (JSON) y el texto en español, que es lo que se muestra."""
        error = messages.ProvenanceError("core.read_only", project="Cantera Norte",
                                         reason="otra sesión lo tiene en escritura")
        expected = ("El proyecto «Cantera Norte» está abierto en solo lectura (otra sesión lo "
                    "tiene en escritura): no se ha registrado nada.")
        self.assertEqual(str(error), expected)
        self.assertEqual(error.text, expected)
        self.assertEqual(error.message, expected)
        self.assertEqual(error.code, "core.read_only")
        self.assertEqual(error.msgid, messages.MESSAGES["core.read_only"].msgid)
        self.assertEqual(error.values, {"project": "Cantera Norte",
                                        "reason": "otra sesión lo tiene en escritura"})
        self.assertIsInstance(error, errors.GeoblenderError)
        with self.assertRaises(ValueError):
            messages.ProvenanceError("core.no_such")


class PackageTest(unittest.TestCase):
    def test_public_api(self) -> None:
        """Plan §5.1: ``core.provenance`` reexporta la API pública del contrato y de los
        mensajes."""
        for name in ("OperationDef", "CoupledGroupDef", "FigureDef", "ImporterDef",
                     "SettingDef", "register_operation", "unregister_operation", "register_group",
                     "unregister_group", "register_figure", "unregister_figure",
                     "register_importer", "unregister_importer", "OPERATIONS", "GROUPS",
                     "FIGURES", "IMPORTERS", "CORE_OPERATIONS", "ProvenanceError",
                     "MESSAGES", "CATALOG_ES"):
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
                self.assertTrue(hasattr(provenance, name))
        self.assertIs(provenance.OperationDef, contract.OperationDef)
        self.assertIs(provenance.ProvenanceError, messages.ProvenanceError)


if __name__ == "__main__":
    unittest.main()
