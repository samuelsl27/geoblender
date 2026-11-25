# SPDX-License-Identifier: GPL-3.0-or-later
"""La cola de avisos con caducidad (spec 019, T05; RF-019-18; D-10; UI-09 y UI-11). El tiempo se inyecta (P-6)."""

from __future__ import annotations

import unittest

from tests.support.package import import_geoblender

notices = import_geoblender("core.notices")
errors = import_geoblender("core.errors")


class QueueTest(unittest.TestCase):
    def test_a_notice_lives_15_seconds(self) -> None:
        queue = notices.Queue()
        queue.add("info", "Saved {name}", {"name": "A"}, now=100.0)
        self.assertEqual(notices.DEFAULT_TTL, 15)
        self.assertEqual(queue.latest(100.0).msgid, "Saved {name}")
        self.assertIsNotNone(queue.latest(114.9))
        self.assertIsNone(queue.latest(115.0))  # a los 15 s ya no está, aunque nadie barra
        self.assertEqual(queue.expire(115.0), 1)
        self.assertEqual(len(queue), 0)

    def test_latest_is_the_last_alive(self) -> None:
        queue = notices.Queue()
        queue.add("info", "one", {}, now=0.0)
        queue.add("warning", "two", {}, now=5.0, ttl=3)
        self.assertEqual(queue.latest(6.0).msgid, "two")
        self.assertEqual(queue.latest(9.0).msgid, "one")  # "two" caducó a los 8 s
        self.assertIsNone(queue.latest(15.0))

    def test_expire_keeps_the_alive_ones(self) -> None:
        queue = notices.Queue()
        queue.add("info", "one", {}, now=0.0)
        queue.add("info", "two", {}, now=10.0)
        self.assertEqual(queue.expire(16.0), 1)
        self.assertEqual([n.msgid for n in queue.alive(16.0)], ["two"])

    def test_clear_removes_for_each_reason(self) -> None:
        for reason in notices.REASONS:
            queue = notices.Queue()
            queue.add("info", "one", {}, now=0.0)
            queue.add("error", "two", {}, now=1.0)
            self.assertEqual(queue.clear(reason), 2, reason)
            self.assertIsNone(queue.latest(2.0), reason)

    def test_reasons_cover_the_spec(self) -> None:
        for reason in ("cancel", "project", "version", "switch", "selection"):
            self.assertIn(reason, notices.REASONS)

    def test_unknown_reason_is_an_error(self) -> None:
        with self.assertRaises(errors.GeoblenderError):
            notices.Queue().clear("because")

    def test_a_repeated_notice_counts_once(self) -> None:
        queue = notices.Queue()
        queue.add("info", "Saved {name}", {"name": "A"}, now=0.0)
        queue.add("info", "Saved {name}", {"name": "A"}, now=10.0)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue.latest(10.0).repeats, 2)
        # el plazo se renueva con la repetición
        self.assertIsNotNone(queue.latest(24.0))
        self.assertIsNone(queue.latest(25.0))
        # otro texto o otros campos no son el mismo aviso
        queue.add("info", "Saved {name}", {"name": "B"}, now=11.0)
        queue.add("warning", "Saved {name}", {"name": "A"}, now=12.0)
        self.assertEqual(len(queue), 3)

    def test_a_repeated_notice_becomes_the_latest(self) -> None:
        queue = notices.Queue()
        queue.add("info", "one", {}, now=0.0)
        queue.add("info", "two", {}, now=1.0)
        queue.add("info", "one", {}, now=2.0)
        self.assertEqual(queue.latest(3.0).msgid, "one")

    def test_text_uses_the_translation(self) -> None:
        queue = notices.Queue()
        queue.add("info", "Saved {name}", {"name": "A"}, now=0.0)
        self.assertEqual(queue.latest(0.0).text(), "Saved A")

    def test_invalid_input(self) -> None:
        queue = notices.Queue()
        with self.assertRaises(errors.GeoblenderError):
            queue.add("loud", "x", {}, now=0.0)
        with self.assertRaises(errors.GeoblenderError):
            queue.add("info", "x", {}, now=0.0, ttl=0)
        with self.assertRaises(errors.GeoblenderError):
            queue.add("info", "", {}, now=0.0)

    def test_the_module_does_not_read_the_clock(self) -> None:
        import inspect

        source = inspect.getsource(notices)
        self.assertNotIn("time.time", source)
        self.assertNotIn("monotonic", source)


if __name__ == "__main__":
    unittest.main()
