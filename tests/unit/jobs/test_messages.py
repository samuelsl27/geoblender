# SPDX-License-Identifier: GPL-3.0-or-later
"""Catálogo de mensajes de los trabajos en segundo plano (spec 004, T02; RF-004-07,
RF-004-12; spec 004 §8; plan 004 §5.3.4).

- Cada código del §8 de la spec tiene un ``msgid`` en inglés y su texto en español, que es
  el de la spec (con los marcadores con nombre en inglés, como los de ``core/i18n``), y los
  dos tienen los mismos marcadores (constitución, principio 10).
- ``render`` rellena todos los marcadores del texto, también si falta un valor, y nunca
  devuelve una traza de Python (RF-004-07): de un valor con una traza queda su última línea.
- ``JobError`` lleva el código, el ``msgid``, los valores y el texto en español (RF-004-12),
  y es un ``GeoblenderError`` (``core/errors``: las specs derivan sus errores de la base).
- ``CATALOG_ES`` (``msgid`` → español) se entrega a ``core.i18n.install`` y da el mismo texto
  que ``render``.
"""

import json
import re
import string
import unittest
from pathlib import Path

from tests.support.package import import_geoblender

messages = import_geoblender("jobs.messages")
errors = import_geoblender("core.errors")
i18n = import_geoblender("core.i18n")

# Los mensajes del §8 de la spec 004, tal cual (los marcadores, en español).
SPEC_TEXTS: dict[str, str] = {
    "request_invalid": "La petición del trabajo «{trabajo}» no es válida: {detalle}.",
    "request_path_outside_job": "El trabajo «{trabajo}» usa una ruta fuera de su carpeta: {ruta}.",
    "worker_unknown": "No existe el tipo de trabajo «{tipo}».",
    "interpreter_not_found": "No se pudo arrancar el intérprete {ruta}: {detalle}.",
    "interpreter_failed": "No se pudo arrancar el intérprete {ruta}: {detalle}.",
    "runtime_missing": (
        "Este cálculo necesita el motor de cálculo, que no está instalado "
        "(Herramientas ▸ Trabajos ▸ Motor de cálculo)."
    ),
    "runtime_mismatch": (
        "El motor de cálculo instalado ({instalado}) no es el que necesita esta versión de "
        "Geoblender ({vigente}): actualícelo."
    ),
    "runtime_numpy_wrong": (
        "El cálculo cargó numpy desde {ruta} y no desde el motor de cálculo; se ha detenido "
        "sin calcular."
    ),
    "runtime_package_mismatch": (
        "El paquete {paquete} del motor tiene la versión {real} y el lock exige {lock}: "
        "repare el motor."
    ),
    "runtime_blas_missing": "El numpy del motor no usa una BLAS optimizada (BLAS: {blas}).",
    "wheel_hash_mismatch": (
        "La huella de {fichero} no coincide con la del lock: instalación cancelada, no se ha "
        "instalado nada."
    ),
    "wheel_not_found": "No se encuentra {fichero} en el almacén de ruedas {carpeta}.",
    "network_not_allowed": (
        "Instalar desde PyPI necesita internet y Blender lo tiene desactivado: active "
        "«Permitir acceso en línea» (Preferencias ▸ Sistema) o configure el almacén de ruedas."
    ),
    "network_error": "No se pudo descargar {paquete}: {detalle}.",
    "disk_space": "No hay espacio en {unidad}: hacen falta {necesario} MB y quedan {libre} MB.",
    "external_python_invalid": (
        "El intérprete externo {ruta} no sirve: {motivo}. Hace falta Python 3.13 con numpy."
    ),
    "job_cancelled": "Trabajo «{trabajo}» cancelado{forzado}.",
    "job_timeout": (
        "El trabajo «{trabajo}» superó su tiempo máximo de {segundos} s y se ha detenido."
    ),
    "job_interrupted": (
        "El trabajo «{trabajo}» quedó interrumpido: Geoblender se cerró mientras se ejecutaba."
    ),
    "worker_crashed": (
        "El cálculo «{trabajo}» terminó de forma inesperada (código {codigo}). Detalles en su "
        "registro."
    ),
    "protocol_no_result": "El trabajo «{trabajo}» terminó sin entregar resultados.",
    "output_missing": (
        "El resultado {ruta} del trabajo «{trabajo}» falta o no coincide con su huella."
    ),
    "output_hash_mismatch": (
        "El resultado {ruta} del trabajo «{trabajo}» falta o no coincide con su huella."
    ),
}

# Marcador de la spec → nombre en el código (identificadores en inglés).
PLACEHOLDER_NAMES: dict[str, str] = {
    "trabajo": "job",
    "detalle": "detail",
    "ruta": "path",
    "tipo": "worker",
    "instalado": "installed",
    "vigente": "required",
    "paquete": "package",
    "real": "actual",
    "lock": "locked",
    "blas": "blas",
    "fichero": "file",
    "carpeta": "folder",
    "unidad": "drive",
    "necesario": "needed",
    "libre": "free",
    "motivo": "reason",
    "forzado": "forced",
    "segundos": "seconds",
    "codigo": "exit_code",
}

SPANISH_ONLY = re.compile(r"[áéíóúüñÁÉÍÓÚÜÑ¿¡]")
CODE_FORMAT = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")

TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "C:\\x\\workers\\_bootstrap.py", line 12, in <module>\n'
    "    main()\n"
    "ModuleNotFoundError: No module named 'numpy'\n"
)


def spec_text(code: str) -> str:
    """El texto del §8 con los marcadores con su nombre en el código."""
    return re.sub(r"\{(\w+)\}", lambda m: "{" + PLACEHOLDER_NAMES[m[1]] + "}",
                  SPEC_TEXTS[code])


def sample_values(text: str) -> dict[str, str]:
    """Un valor reconocible para cada marcador de ``text``."""
    return {name: f"<{name}>" for name in i18n.placeholders(text)}


def has_placeholder(text: str) -> bool:
    """Si en ``text`` queda algún marcador ``{…}`` sin rellenar."""
    return any(name is not None for _lit, name, _spec, _conv in string.Formatter().parse(text))


class CatalogTest(unittest.TestCase):
    def test_every_code_of_the_spec(self) -> None:
        """RF-004-12 (§8): el catálogo tiene todos los códigos del §8 de la spec, cada uno
        con el texto de la spec."""
        missing = sorted(set(SPEC_TEXTS) - set(messages.MESSAGES))
        self.assertEqual(missing, [], "códigos del §8 sin mensaje")
        for code, expected in SPEC_TEXTS.items():
            with self.subTest(code=code):
                message = messages.MESSAGES[code]
                self.assertIsInstance(message, messages.Message)
                self.assertEqual(message.code, code)
                self.assertEqual(message.es, spec_text(code))

    def test_msgid_in_english_and_text_in_spanish(self) -> None:
        """RF-004-07 y RF-004-12 (principio 10): todo código es un identificador estable
        en inglés y tiene ``msgid`` en inglés y texto en español, con los mismos
        marcadores."""
        for code, message in messages.MESSAGES.items():
            with self.subTest(code=code):
                self.assertRegex(code, CODE_FORMAT)
                self.assertTrue(message.msgid.strip(), "msgid vacío")
                self.assertTrue(message.es.strip(), "texto en español vacío")
                self.assertNotEqual(message.msgid, message.es)
                self.assertIsNone(SPANISH_ONLY.search(message.msgid),
                                  f"msgid con letras del español: {message.msgid}")
                self.assertEqual(i18n.placeholders(message.msgid),
                                 i18n.placeholders(message.es))

    def test_same_msgid_same_text(self) -> None:
        """RF-004-12 (principio 10): los códigos que comparten mensaje
        (``interpreter_not_found`` e ``interpreter_failed``; ``output_missing`` y
        ``output_hash_mismatch``) comparten ``msgid`` y texto, y un ``msgid`` tiene una sola
        traducción."""
        self.assertEqual(messages.MESSAGES["interpreter_not_found"].msgid,
                         messages.MESSAGES["interpreter_failed"].msgid)
        self.assertEqual(messages.MESSAGES["output_missing"].msgid,
                         messages.MESSAGES["output_hash_mismatch"].msgid)
        by_msgid: dict[str, set[str]] = {}
        for message in messages.MESSAGES.values():
            by_msgid.setdefault(message.msgid, set()).add(message.es)
        self.assertEqual({m: t for m, t in by_msgid.items() if len(t) > 1}, {})

    def test_no_traceback_in_the_catalog(self) -> None:
        """RF-004-07: ningún texto ni ``msgid`` del catálogo contiene «Traceback»."""
        for code, message in messages.MESSAGES.items():
            with self.subTest(code=code):
                self.assertNotIn("Traceback", message.msgid)
                self.assertNotIn("Traceback", message.es)

    def test_catalog_is_read_only(self) -> None:
        """RF-004-12 (plan 004 §5.3.4): el catálogo es fijo; nadie lo cambia en
        ejecución."""
        extra = messages.Message("x_y", "X", "Equis")
        with self.assertRaises(TypeError):
            messages.MESSAGES["x_y"] = extra  # type: ignore[index]
        with self.assertRaises(TypeError):
            messages.CATALOG_ES["X"] = "Equis"  # type: ignore[index]
        with self.assertRaises(AttributeError):
            messages.MESSAGES["job_timeout"].es = "otro"  # type: ignore[misc]


class RenderTest(unittest.TestCase):
    def test_render_fills_every_placeholder(self) -> None:
        """RF-004-07 y RF-004-12: ``render`` rellena todos los marcadores del texto en
        español con sus valores."""
        for code, message in messages.MESSAGES.items():
            with self.subTest(code=code):
                values = sample_values(message.es)
                text = messages.render(code, **values)
                self.assertFalse(has_placeholder(text), text)
                self.assertEqual(text, message.es.format(**values))

    def test_render_without_values_leaves_no_placeholder(self) -> None:
        """RF-004-12: un valor que falta no deja el marcador a la vista ni lanza (el camino
        del error no puede romper el seguimiento); los que sobran se ignoran."""
        for code in messages.MESSAGES:
            with self.subTest(code=code):
                text = messages.render(code, unused="x")
                self.assertFalse(has_placeholder(text), text)
                self.assertNotIn("{", text)
        self.assertEqual(messages.render("worker_unknown"), "No existe el tipo de trabajo «?».")

    def test_examples(self) -> None:
        """RF-004-07, RF-004-11 y RF-004-12: casos concretos en español, con números en el
        formato del idioma y la cancelación forzada como sufijo."""
        self.assertEqual(
            messages.render("job_timeout", job="Suma de prueba", seconds=3600),
            "El trabajo «Suma de prueba» superó su tiempo máximo de 3600 s y se ha detenido.")
        self.assertEqual(
            messages.render("disk_space", drive="C:", needed=12.5, free=3.0),
            "No hay espacio en C:: hacen falta 12,5 MB y quedan 3 MB.")
        self.assertEqual(messages.render("job_cancelled", job="Suma", forced=True),
                         "Trabajo «Suma» cancelado (forzado).")
        self.assertEqual(messages.render("job_cancelled", job="Suma", forced=False),
                         "Trabajo «Suma» cancelado.")
        self.assertEqual(messages.render("worker_crashed", job="Suma", exit_code=1),
                         "El cálculo «Suma» terminó de forma inesperada (código 1). "
                         "Detalles en su registro.")
        self.assertEqual(
            messages.render("request_path_outside_job", job="Suma", path=Path("..") / "x.npy"),
            "El trabajo «Suma» usa una ruta fuera de su carpeta: ..\\x.npy.")

    def test_render_in_english(self) -> None:
        """RF-004-07 (principio 10): en inglés, ``render`` usa el ``msgid`` con los mismos
        valores, con punto decimal y el sufijo de forzado en inglés."""
        self.assertEqual(
            messages.render("job_cancelled", language="en", job="Sum", forced=True),
            "Job «Sum» cancelled (forced).")
        self.assertEqual(
            messages.render("disk_space", language="en", drive="C:", needed=12.5, free=3),
            messages.MESSAGES["disk_space"].msgid.format(drive="C:", needed="12.5", free="3"))
        with self.assertRaises(ValueError):
            messages.render("job_timeout", language="fr", job="x", seconds=1)

    def test_render_never_shows_a_traceback(self) -> None:
        """RF-004-07: de un valor con una traza de Python (la salida de error de un
        intérprete que no arranca) solo queda su última línea, y nunca varias líneas."""
        text = messages.render("interpreter_failed", path="python.exe", detail=TRACEBACK)
        self.assertNotIn("Traceback", text)
        self.assertNotIn('File "', text)
        self.assertNotIn("\n", text)
        self.assertEqual(text, "No se pudo arrancar el intérprete python.exe: "
                               "ModuleNotFoundError: No module named 'numpy'.")
        two_lines = messages.render("network_error", package="numpy", detail="línea 1\nlínea 2")
        self.assertEqual(two_lines, "No se pudo descargar numpy: línea 1 línea 2.")

    def test_unknown_code(self) -> None:
        """RF-004-12: un código fuera del catálogo es un error del programa, dicho en
        español."""
        with self.assertRaisesRegex(ValueError, "no_such_code"):
            messages.render("no_such_code")


class JobErrorTest(unittest.TestCase):
    def test_job_error_carries_code_msgid_values_and_text(self) -> None:
        """RF-004-12: ``JobError`` lleva el código, el ``msgid``, los valores y el texto en
        español del §8, que es también su mensaje para el usuario."""
        exc = messages.JobError("worker_unknown", worker="no_existe")
        self.assertIsInstance(exc, errors.GeoblenderError)
        self.assertEqual(exc.code, "worker_unknown")
        self.assertEqual(exc.msgid, messages.MESSAGES["worker_unknown"].msgid)
        self.assertEqual(exc.values, {"worker": "no_existe"})
        self.assertEqual(exc.text, "No existe el tipo de trabajo «no_existe».")
        self.assertEqual(str(exc), exc.text)
        self.assertEqual(exc.message, exc.text)

    def test_values_are_json(self) -> None:
        """RF-004-12 y RF-004-15: los valores se guardan en el registro (JSON): una ruta
        queda como texto y el sufijo de forzado como booleano, y de ellos sale el mismo
        texto."""
        exc = messages.JobError("job_cancelled", job="Suma", forced=True)
        self.assertEqual(exc.values, {"job": "Suma", "forced": True})
        self.assertEqual(exc.text, "Trabajo «Suma» cancelado (forzado).")
        self.assertEqual(messages.render("job_cancelled", **exc.values), exc.text)
        exc = messages.JobError("request_path_outside_job", job="Suma", path=Path("a") / "b")
        self.assertEqual(json.loads(json.dumps(exc.values)), {"job": "Suma", "path": "a\\b"})

    def test_unknown_code_is_rejected(self) -> None:
        """RF-004-12 (principio 10): no hay ``JobError`` sin mensaje en español en el
        catálogo."""
        with self.assertRaisesRegex(ValueError, "no_such_code"):
            messages.JobError("no_such_code")


class I18nTest(unittest.TestCase):
    def test_catalog_es_goes_to_core_i18n(self) -> None:
        """RF-004-07 (plan 004 §5.3.4): ``CATALOG_ES`` (``msgid`` → español) se instala en
        ``core.i18n`` y la interfaz obtiene con ``translate`` el mismo texto que
        ``render``."""
        self.assertEqual(dict(messages.CATALOG_ES),
                         {m.msgid: m.es for m in messages.MESSAGES.values()})
        i18n.install(messages.CATALOG_ES)
        self.assertEqual(i18n.untranslated(messages.CATALOG_ES), [])
        for code, message in messages.MESSAGES.items():
            values = sample_values(message.es)
            with self.subTest(code=code):
                self.assertEqual(i18n.translate("es", message.msgid, **values),
                                 messages.render(code, **values))


if __name__ == "__main__":
    unittest.main()
