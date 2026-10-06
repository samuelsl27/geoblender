# SPDX-License-Identifier: GPL-3.0-or-later
"""Tiempo de repetir sin cambios el espejo seguro de 1 000 ficheros (RNF-007-03).

Se ejecuta con ``tools/check.py --rendimiento`` (Python de Blender). La publicación
compara el destino con el estado del último espejo, hace el espejo y lo comprueba
(``gbtools.safe_mirror``; plan 007 §5.4.7 y §5.4.8): aquí se mide esa secuencia, repetida
sin cambios, sobre una carpeta del proyecto sintética de 1 000 ficheros con sus dos
repositorios (la documentación y, dentro, el código, cada uno con su ``.git``), con el
origen y el destino en ``%TEMP%`` y el estado en un perfil local temporal (nunca el NAS
ni el perfil real).
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.support import mirror as mirror_support
from tests.support.repo import tools_on_path

tools_on_path()

from gbtools import layout, safe_mirror  # noqa: E402

FILES = 1000
BUDGET_S = 5.0  # RNF-007-03: ≤ 5 s y 0 ficheros copiados
CODE = layout.CODE_DIR_IN_DOCS
# Carpetas de la carpeta del proyecto sintética: de la documentación, del código y de
# los dos .git (objetos sueltos, como los deja git).
FOLDERS: tuple[str, ...] = (
    "docs/adr",
    "specs/007-core-ejemplo",
    "Documentacion/informes",
    ".git/objects/ab",
    f"{CODE}/{layout.EXTENSION_DIR}/core",
    f"{CODE}/{layout.EXTENSION_DIR}/bl/ui",
    f"{CODE}/tools/gbtools",
    f"{CODE}/tests/unit",
    f"{CODE}/.git/objects/cd",
)


def _seconds(value: float) -> str:
    """Segundos con dos decimales y coma decimal (salida en español)."""
    return f"{value:.2f}".replace(".", ",")


def build_project(project: Path) -> int:
    """1 000 ficheros de unos 6 KiB repartidos entre los dos repositorios, más lo que
    el espejo excluye; devuelve cuántos se reflejan."""
    body = ("# SPDX-License-Identifier: GPL-3.0-or-later\n" + "x = 1\n" * 1000).encode()
    for number in range(FILES):
        folder = project / FOLDERS[number % len(FOLDERS)]
        if not folder.is_dir():
            folder.mkdir(parents=True)
        (folder / f"fichero_{number:04d}.txt").write_bytes(body + str(number).encode())
    for excluded in ("dist/viejo.zip", f"{CODE}/.deps/site/x.txt", "docs/Thumbs.db"):
        path = project / excluded
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"excluido")
    return FILES


def mirror_once(project: Path, dest: Path, environ: dict[str, str]) -> safe_mirror.MirrorReport:
    """La secuencia del espejo de la publicación (sin git): comparación con la base,
    espejo, comprobación y estado guardado."""
    base = safe_mirror.load_base(dest, environ)
    assert base is not None
    source = safe_mirror.scan_source(project)
    listing = safe_mirror.scan_destination(dest)
    pending = safe_mirror.load_pending(dest, environ)
    changes, observed = safe_mirror.destination_changes(dest, base, source, listing, pending)
    assert not changes, changes
    with safe_mirror.mirror_lock(dest, environ):
        report = safe_mirror.mirror(project, dest, source, listing, observed, base, environ)
        result = safe_mirror.verify(dest, source, report, observed)
        assert not result.changes and not result.problems, (result.changes, result.problems)
        state = safe_mirror.new_state(dest, project, result, {}, environ)
        safe_mirror.save_state(dest, environ, state)
    return report


class SafeMirrorSpeedTest(unittest.TestCase):
    def test_remirror_1000_files_under_5_s(self) -> None:
        """RNF-007-03: repetir sin cambios el espejo de una carpeta sintética de 1 000
        ficheros (dos repositorios) a un destino local copia 0 ficheros y, con la
        comparación y la comprobación, tarda ≤ 5 s."""
        with tempfile.TemporaryDirectory(prefix="geoblender-rendimiento-") as tmp:
            project, dest, profile = Path(tmp) / "proyecto", Path(tmp) / "destino", Path(tmp) / "perfil"
            expected = build_project(project)
            dest.mkdir()
            environ = {"LOCALAPPDATA": str(profile)}
            mirror_support.write_photo(profile, dest, files={})
            start = time.perf_counter()
            first = mirror_once(project, dest, environ)
            first_s = time.perf_counter() - start
            start = time.perf_counter()
            second = mirror_once(project, dest, environ)
            seconds = time.perf_counter() - start
        print(
            f"RNF-007-03: repetir sin cambios el espejo de {FILES} ficheros (dos "
            f"repositorios): {_seconds(seconds)} s, {len(second.copied)} copiados "
            f"(presupuesto {_seconds(BUDGET_S)} s; primer espejo {_seconds(first_s)} s, "
            f"{len(first.copied)} copiados)",
            file=sys.stderr,
            flush=True,
        )
        self.assertEqual(len(first.copied), expected)
        self.assertEqual(second.copied, [])
        self.assertEqual(second.deleted, [])
        self.assertEqual(second.unchanged, expected)
        self.assertLessEqual(seconds, BUDGET_S)


if __name__ == "__main__":
    unittest.main()
