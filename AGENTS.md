# AGENTS.md — Geoblender (código)

Extensión de **Blender 5.2 LTS** (Python 3.13, Windows x64) que convierte Blender en un
software minero; la desarrolla IMGA con Spec-Driven Development. Este repositorio tiene solo
el código: la extensión (`geoblender/`), `tools/` y `tests/`.

## Antes de nada: la documentación

La constitución, el proceso, los ADR, las specs, las reglas completas de los agentes y las
trampas conocidas **no están aquí**. Están en la carpeta madre de este repositorio o, si está
definida, en la carpeta de `$env:GEOBLENDER_DOCS_DIR`. Antes de cualquier tarea, lee allí
`AGENTS.md` (la guía completa), `docs/constitution.md` (manda sobre todo lo demás) y la spec
de la tarea. **Si no tienes esa guía en tu contexto, léela entera ahora**: abrir el código no
la carga sola. Si no encuentras la documentación, para y pídela. No escribas su ruta aquí.

Dentro de la extensión manda además `geoblender/AGENTS.md`.

## Órdenes

Desde la raíz de este repositorio, en PowerShell, siempre con el Python de Blender:

```powershell
$PY = "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe"
& $PY -B tools/check.py          # el «verde»; --completo (al publicar), --rendimiento, --banco, --documentacion
# Solo las unitarias, para iterar (no sustituye a check.py)
$env:PYTHONPATH = "$PWD\.deps\site"; & $PY -B -s -X utf8 -m unittest discover -s tests/unit -t .
& $PY -B tools/check_docs.py     # la documentación (carpeta madre o GEOBLENDER_DOCS_DIR)
& $PY -B tools/dev_install.py    # perfil aislado; --abrir, --desinstalar
& $PY -B tools/build.py          # manifiesto y zip en dist/; --probar-instalacion
& $PY -B tools/fetch_wheels.py   # ruedas fijadas (lo ejecuta una persona)
& $PY -B tools/publish.py        # sube y refleja en el NAS: solo quien publica (abajo)
```

Si no pudiste ejecutar una orden, dilo: no simules su resultado. Blender, en pruebas, siempre
con `--python-exit-code 1` y un perfil temporal, nunca con el perfil real del usuario.

## Verificación obligatoria al terminar

1. `tools/check.py` en verde con el Python de Blender; lo que no se pudo ejecutar, se dice.
2. La tarea marcada en el `tasks.md` de su spec, en la documentación, con su *Verificación*.
3. Un commit por tarea: Conventional Commits en español, con los trailers `Spec:`, `Tarea:`
   y `Requisitos:`.

## Lo que no admite espera

- Aquí no entra nada de la documentación ni ninguna ruta del NAS, de la carpeta del proyecto
  o de la carpeta de expedientes de clientes; los datos de clientes, nunca.
- Los agentes no aprueban specs, no integran en `main` y no publican, salvo que una persona
  de IMGA lo pida expresamente en esa tarea.
- Toda subida a GitHub y todo espejo al NAS los hace `tools/publish.py`, y solo quien
  publica (una persona, o un agente al que ella se lo pida): nunca `git push` a mano ni
  fusiones en la web de GitHub. Si para con código 3 (`CAMBIOS EN EL DESTINO`), no la
  fuerces: enseña la lista a quien publica. `--rehacer-estado`, solo si ella lo pide.
- Sin `__pycache__` en el repositorio (`-B`); texto en UTF-8 sin BOM y LF; cabecera SPDX en
  cada `.py`; ningún enlace simbólico.
