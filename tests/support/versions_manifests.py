# SPDX-License-Identifier: GPL-3.0-or-later
"""Las instantáneas de un proyecto de pruebas con el manifiesto **entero**, como lo escribía la
009/T13 antes del formato compacto de la T33 (plan 009 §5.2.5, D-39; RNF-009-06): para
comprobar que comprobar y reproducir leen igual uno y otro.

:func:`rewrite_full` reescribe el manifiesto de cada revisión congelada con todas sus claves
(``core.versions.model.expand_manifest``, en JSON canónico) y anota su huella nueva en
``gb_revision.snapshot_sha256``: de una revisión congelada la base solo deja cambiar la marca de
alterada (el disparador ``gb_revision_state``), así que en esa transacción se quita el
disparador y se vuelve a crear con el mismo SQL. Solo en una copia de pruebas.

Solo fuera de Blender. Datos solo sintéticos.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tests.support.package import import_geoblender

vmodel = import_geoblender("core.versions.model")
vschema = import_geoblender("core.versions.schema")
hashing = import_geoblender("core.hashing")

STATE_TRIGGER = "gb_revision_state"
"""El disparador que no deja cambiar nada de una revisión congelada salvo la marca de
alterada (``core.versions.schema``)."""


def rewrite_full(project: Any) -> dict[str, str]:
    """Reescribe con todas sus claves el manifiesto de cada revisión congelada de ``project``
    (abierto en escritura) y anota su huella en la base; devuelve uid de la revisión → huella
    nueva. Lo que lee del manifiesto compacto sale entero; uno ya entero queda igual (bytes
    iguales, la misma huella)."""
    root = Path(project.root)
    with project.read() as conn:
        rows = conn.execute("SELECT uid, snapshot_dir FROM gb_revision WHERE state = 'frozen' "
                            "ORDER BY fid").fetchall()
    written: dict[str, str] = {}
    for uid, folder in rows:
        path = root.joinpath(*str(folder).split("/"), vmodel.SNAPSHOT_MANIFEST)
        data = hashing.canonical_json(vmodel.expand_manifest(json.loads(path.read_bytes())))
        path.write_bytes(data)
        written[str(uid)] = hashlib.sha256(data).hexdigest()
    with project.write_transaction() as conn:
        conn.execute(f'DROP TRIGGER "{STATE_TRIGGER}"')
        conn.executemany("UPDATE gb_revision SET snapshot_sha256 = ? WHERE uid = ?",
                         [(sha, uid) for uid, sha in written.items()])
        conn.execute(vschema.TRIGGERS[STATE_TRIGGER])
    return written
