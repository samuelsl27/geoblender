# SPDX-License-Identifier: GPL-3.0-or-later
"""Diario de Ctrl+Z de lo registrado en la sesión (spec 008, T38; RF-008-32; plan 008
§5.3.1 y §5.4.11).

:class:`UndoJournal` numera cada cambio registrado (un parámetro, una decisión sobre una
entrada, una operación); ``bl`` copia ese número en la escena sin empujar un paso de deshacer.
Cuando Ctrl+Z o Ctrl+Mayús+Z restaura una escena con otro número, el diario dice qué deja atrás
o qué recupera la escena, con el texto de la barra de estado («Ctrl+Z no deshace la operación
«gis.resample»: sigue en el proyecto»): nada de lo registrado se deshace, y el diario no cambia
lo anotado. Aquí las escenas se simulan con sus números; los manejadores de Blender son T57.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tests.support.package import import_geoblender

provenance = import_geoblender("core.provenance")
undo = import_geoblender("core.provenance.undo")
messages = import_geoblender("core.provenance.messages")

UndoJournal = undo.UndoJournal
UndoKind = undo.UndoKind
UndoDirection = undo.UndoDirection

RESAMPLE = "gis.resample"
SWELL = "res.swell_factor"
BOUNDARY = "Limites_v1"

UNDO_RESAMPLE = "Ctrl+Z no deshace la operación «gis.resample»: sigue en el proyecto"
UNDO_SWELL = "Ctrl+Z no deshace el cambio de «res.swell_factor»: sigue en el proyecto"
UNDO_BOUNDARY = ("Ctrl+Z no deshace la decisión sobre la entrada «Limites_v1»: sigue en el "
                 "proyecto")
REDO_RESAMPLE = ("Ctrl+Mayús+Z no rehace la operación «gis.resample»: no se deshizo y sigue "
                 "en el proyecto")


def _journal(*changes: tuple[str, str]) -> tuple[object, list[int]]:
    """Un diario con los cambios ``(clase, etiqueta)`` registrados en orden, cada uno sobre la
    escena del anterior (como los sella ``bl``), y sus números."""
    journal = UndoJournal()
    return journal, [journal.record(kind, label) for kind, label in changes]


class NumberingTest(unittest.TestCase):
    def test_each_recorded_change_has_a_number(self) -> None:
        """RF-008-32: cada cambio registrado (parámetro, decisión sobre una entrada,
        operación) tiene su número, creciente y sin repetir desde 1 (0 es una escena sin nada
        registrado); la clase se da con su enumeración o con su texto, y una clase
        desconocida o una etiqueta vacía o que no es texto se rechazan sin anotar nada."""
        journal = UndoJournal()
        self.assertEqual((journal.last, journal.scene_seq, journal.entries), (0, 0, ()))
        first = journal.record(UndoKind.OPERATION, RESAMPLE)
        second = journal.record("parameter", SWELL)
        third = journal.record(UndoKind.INPUT, BOUNDARY)
        self.assertEqual((first, second, third), (1, 2, 3))
        self.assertEqual((journal.last, journal.scene_seq), (3, 3))
        self.assertEqual(
            [(e.seq, e.kind, e.label, e.parent) for e in journal.entries],
            [(1, UndoKind.OPERATION, RESAMPLE, 0), (2, UndoKind.PARAMETER, SWELL, 1),
             (3, UndoKind.INPUT, BOUNDARY, 2)],
        )
        self.assertEqual({str(kind) for kind in UndoKind}, {"parameter", "input", "operation"})
        before = journal.entries
        for kind, label, error in (("figure", "x", ValueError), (UndoKind.INPUT, "", ValueError),
                                   (UndoKind.INPUT, "  ", ValueError),
                                   (UndoKind.INPUT, None, TypeError), (3, "x", ValueError)):
            with self.subTest(kind=kind, label=label), self.assertRaises(error):
                journal.record(kind, label)
        self.assertEqual(journal.entries, before)
        self.assertEqual(journal.last, 3)
        with self.assertRaises(AttributeError):
            journal.entries[0].label = "otra"  # type: ignore[misc]

    def test_numbers_never_go_back(self) -> None:
        """RF-008-32: después de deshacer, lo que se registra sigue numerándose después de lo
        último (nunca se reutiliza un número); con la escena de un ``.blend`` de otra sesión,
        después de su número."""
        journal, _ = _journal(("operation", RESAMPLE), ("parameter", SWELL))
        journal.restored(0)
        self.assertEqual(journal.record("operation", "res.area"), 3)
        loaded = UndoJournal(scene_seq=57)
        self.assertEqual(loaded.record("parameter", SWELL), 58)
        journal.scene_loaded(40)
        self.assertEqual(journal.record("input", BOUNDARY), 41)
        for bad, error in ((-1, ValueError), (True, TypeError), ("3", TypeError),
                           (1.0, TypeError)):
            with self.subTest(bad=bad):
                with self.assertRaises(error):
                    UndoJournal(scene_seq=bad)
                with self.assertRaises(error):
                    journal.since(bad)
                with self.assertRaises(error):
                    journal.restored(bad)
                with self.assertRaises(error):
                    journal.scene_loaded(bad)


class SinceTest(unittest.TestCase):
    def test_since_gives_what_was_undone_and_its_text(self) -> None:
        """RF-008-32: ``since(n)`` da lo que la escena con el número ``n`` deja atrás
        respecto a la actual, en el orden en que se registró, y cada cosa su texto de la
        barra de estado en español y en inglés («Ctrl+Z no deshace la operación
        «gis.resample»: sigue en el proyecto»; «… el cambio de «res.swell_factor»…»)."""
        journal, numbers = _journal(("operation", RESAMPLE), ("parameter", SWELL),
                                    ("input", BOUNDARY))
        self.assertEqual(numbers, [1, 2, 3])
        self.assertEqual([e.label for e in journal.since(0)], [RESAMPLE, SWELL, BOUNDARY])
        self.assertEqual([e.label for e in journal.since(2)], [BOUNDARY])
        self.assertEqual(journal.since(3), [])
        self.assertEqual([e.text() for e in journal.since(0)],
                         [UNDO_RESAMPLE, UNDO_SWELL, UNDO_BOUNDARY])
        self.assertEqual(
            [e.text(language="en") for e in journal.since(0)],
            ["Ctrl+Z does not undo operation «gis.resample»: it stays in the project",
             "Ctrl+Z does not undo the change of «res.swell_factor»: it stays in the project",
             "Ctrl+Z does not undo the decision on input «Limites_v1»: it stays in the "
             "project"],
        )
        self.assertEqual(journal.since(1)[0].text(UndoDirection.REDO),
                         "Ctrl+Mayús+Z no rehace el cambio de «res.swell_factor»: no se "
                         "deshizo y sigue en el proyecto")
        self.assertEqual(journal.since(0)[0].text("redo", language="en"),
                         "Ctrl+Shift+Z does not redo operation «gis.resample»: it was not "
                         "undone and stays in the project")
        with self.assertRaises(ValueError):
            journal.since(0)[0].text(language="fr")
        with self.assertRaises(ValueError):
            journal.since(0)[0].text("sideways")
        # Un número que la escena actual no tiene debajo (otra rama o de otro .blend): nada.
        self.assertEqual(journal.since(9), [])

    def test_label_is_shown_as_is(self) -> None:
        """RF-008-32: la etiqueta se ve tal cual, también con llaves o comillas (nunca se
        interpreta como marcador del texto)."""
        journal, _ = _journal(("input", "Collares {v2} «b»"))
        self.assertEqual(journal.since(0)[0].text(),
                         "Ctrl+Z no deshace la decisión sobre la entrada «Collares {v2} «b»»: "
                         "sigue en el proyecto")


class RestoredTest(unittest.TestCase):
    def test_undo_redo_undo_gives_three_texts(self) -> None:
        """RF-008-32: la escena restaurada con un número anterior avisa de lo que deja atrás
        («Ctrl+Z no deshace la operación «gis.resample»: sigue en el proyecto»); rehacer, con
        su propio texto, de lo que recupera; y la secuencia deshacer → rehacer → deshacer da
        los tres textos correctos. Nada de lo anotado cambia, y la misma escena otra vez no
        avisa."""
        journal = UndoJournal()
        scene = journal.record("operation", RESAMPLE)
        self.assertEqual(scene, 1)
        entries = journal.entries
        texts = []
        for restored, direction in ((0, UndoDirection.UNDO), (1, UndoDirection.REDO),
                                    (0, UndoDirection.UNDO)):
            notice = journal.restored(restored)
            self.assertIsNotNone(notice)
            self.assertEqual(notice.direction, direction)
            self.assertEqual([e.label for e in notice.entries], [RESAMPLE])
            self.assertEqual(journal.scene_seq, restored)
            texts.append(notice.text())
            self.assertIsNone(journal.restored(restored))
        self.assertEqual(texts, [UNDO_RESAMPLE, REDO_RESAMPLE, UNDO_RESAMPLE])
        self.assertEqual(journal.entries, entries)
        self.assertEqual(journal.last, 1)
        self.assertEqual(journal.restored(1).text(language="en"),
                         "Ctrl+Shift+Z does not redo operation «gis.resample»: it was not "
                         "undone and stays in the project")

    def test_step_by_step(self) -> None:
        """RF-008-32: cada paso avisa solo de lo suyo: deshacer de la escena 2 a la 1 deja
        atrás el cambio de «res.swell_factor», de la 1 a la 0 la operación, y rehacer de la 0
        a la 1 recupera la operación."""
        journal, _ = _journal(("operation", RESAMPLE), ("parameter", SWELL))
        self.assertEqual(journal.restored(1).text(), UNDO_SWELL)
        self.assertEqual(journal.restored(0).text(), UNDO_RESAMPLE)
        self.assertEqual(journal.restored(1).text(), REDO_RESAMPLE)
        self.assertEqual(journal.since(0)[0].label, RESAMPLE)

    def test_several_changes_in_one_step(self) -> None:
        """RF-008-32: si un paso deja atrás (o recupera) varios cambios registrados, el aviso
        nombra el más reciente y cuenta los demás, en español y en inglés."""
        journal, _ = _journal(("operation", RESAMPLE), ("parameter", SWELL),
                              ("input", BOUNDARY))
        notice = journal.restored(0)
        self.assertEqual([e.seq for e in notice.entries], [1, 2, 3])
        self.assertEqual(notice.text(),
                         "Ctrl+Z no deshace la decisión sobre la entrada «Limites_v1» ni otros "
                         "2 cambios registrados: siguen en el proyecto")
        self.assertEqual(notice.text(language="en"),
                         "Ctrl+Z does not undo the decision on input «Limites_v1» or 2 other "
                         "recorded changes: they stay in the project")
        self.assertEqual(journal.restored(3).text(),
                         "Ctrl+Mayús+Z no rehace la decisión sobre la entrada «Limites_v1» ni "
                         "otros 2 cambios registrados: no se deshicieron y siguen en el "
                         "proyecto")
        journal.restored(1)
        notice = journal.restored(3)
        self.assertEqual(notice.text(),
                         "Ctrl+Mayús+Z no rehace la decisión sobre la entrada «Limites_v1» ni "
                         "otro cambio registrado: no se deshicieron y siguen en el proyecto")
        self.assertEqual(notice.text(language="en"),
                         "Ctrl+Shift+Z does not redo the decision on input «Limites_v1» or "
                         "another recorded change: they were not undone and stay in the "
                         "project")
        self.assertEqual(journal.restored(1).text(),
                         "Ctrl+Z no deshace la decisión sobre la entrada «Limites_v1» ni otro "
                         "cambio registrado: siguen en el proyecto")
        self.assertEqual(journal.restored(0).text(language="en"),
                         "Ctrl+Z does not undo operation «gis.resample»: it stays in the "
                         "project")

    def test_change_after_undo(self) -> None:
        """RF-008-32: lo registrado con la escena deshecha cuelga de esa escena: deshacerlo
        avisa solo de ello (lo deshecho antes ya no estaba en la escena), y una escena de la
        rama abandonada no avisa."""
        journal, _ = _journal(("operation", RESAMPLE), ("parameter", SWELL))
        self.assertEqual(journal.restored(0).text(),
                         "Ctrl+Z no deshace el cambio de «res.swell_factor» ni otro cambio "
                         "registrado: siguen en el proyecto")
        area = journal.record("operation", "res.area")
        self.assertEqual(area, 3)
        self.assertEqual(journal.entries[-1].parent, 0)
        self.assertEqual([e.label for e in journal.since(0)], ["res.area"])
        notice = journal.restored(0)
        self.assertEqual(notice.text(),
                         "Ctrl+Z no deshace la operación «res.area»: sigue en el proyecto")
        self.assertEqual(journal.restored(3).direction, UndoDirection.REDO)
        self.assertIsNone(journal.restored(2))
        self.assertEqual(journal.scene_seq, 2)
        self.assertEqual(len(journal.entries), 3)

    def test_scene_without_number_or_from_another_blend(self) -> None:
        """RF-008-32 (plan §8): una escena sin número (sin ``Scene.geoblender``) no avisa ni
        mueve nada; la de un ``.blend`` recién abierto empieza su historia sin aviso, y lo
        registrado antes de abrirlo nunca sale en sus avisos."""
        journal, _ = _journal(("operation", RESAMPLE), ("parameter", SWELL))
        self.assertIsNone(journal.restored(None))
        self.assertEqual(journal.scene_seq, 2)
        # El mismo .blend guardado tras el último cambio y abierto otra vez.
        journal.scene_loaded(2)
        self.assertEqual(journal.since(1), [])
        self.assertIsNone(journal.restored(1))
        journal.scene_loaded(1)
        self.assertEqual(journal.scene_seq, 1)
        self.assertEqual(journal.since(0), [])
        swell = journal.record("parameter", SWELL)
        self.assertEqual(swell, 3)
        self.assertEqual(journal.restored(1).text(), UNDO_SWELL)
        self.assertEqual(journal.restored(3).direction, UndoDirection.REDO)
        # Un .blend guardado en otra sesión con un número mayor que todo lo de esta.
        journal.scene_loaded(57)
        self.assertEqual(journal.record("operation", RESAMPLE), 58)
        self.assertEqual(journal.restored(57).text(), UNDO_RESAMPLE)
        self.assertIsNone(journal.restored(2))
        self.assertEqual(len(journal.entries), 4)


class ModuleTest(unittest.TestCase):
    def test_the_journal_never_touches_the_project(self) -> None:
        """RF-008-32: el diario no deshace ni altera nada de lo registrado: no tiene
        proyecto, conexión ni base de datos; solo importa la biblioteca estándar y los
        mensajes de la procedencia."""
        tree = ast.parse(Path(undo.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(("." * node.level) + (node.module or ""))
        self.assertLessEqual(imported, {"__future__", "collections.abc", "dataclasses", "enum",
                                        "types", "typing", ".messages"})
        self.assertIn(".messages", imported)

    def test_messages_and_public_api(self) -> None:
        """RF-008-32 (plan §5.3.1): los textos están en el catálogo de la procedencia con su
        ``msgid`` en inglés; ``core.provenance`` reexporta el diario al usarlo, sin cargarlo
        al importarse."""
        for code in undo.MESSAGE_CODES:
            with self.subTest(code=code):
                self.assertIn(code, messages.MESSAGES)
        for name in provenance.UNDO_API:
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
                self.assertIn(name, dir(provenance))
                self.assertIs(getattr(provenance, name), getattr(undo, name))
        self.assertLessEqual({"UndoJournal", "UndoEntry", "UndoNotice", "UndoKind",
                              "UndoDirection"}, set(provenance.UNDO_API))
        tree = ast.parse(Path(provenance.__file__).read_text(encoding="utf-8"))
        imported = {alias.name for node in tree.body if isinstance(node, ast.ImportFrom)
                    for alias in node.names} | {node.module for node in tree.body
                                                if isinstance(node, ast.ImportFrom)}
        self.assertNotIn("undo", imported)


if __name__ == "__main__":
    unittest.main()
