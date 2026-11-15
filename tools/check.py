# SPDX-License-Identifier: GPL-3.0-or-later
"""La comprobación completa de Geoblender: la definición de «verde» (plan 001 §5.4.7;
ADR-0015; RF-001-06, RF-001-07, RF-001-09).

Se ejecuta con el Python de Blender, desde la raíz del repositorio::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\5.2\\python\\bin\\python.exe" tools/check.py [--completo] [--rendimiento] [--banco] [--documentacion]

1. Entorno: localiza Blender (``GEOBLENDER_BLENDER`` o la ruta por defecto) con la
   versión mínima del manifiesto, y exige que el intérprete sea el Python de ese Blender
   y que no se ejecute dentro de Blender. Si algo falla, lo dice con la orden o la
   variable que lo corrige y sale con 2 sin ejecutar nada. Después, el cerrojo del equipo
   (spec 006, T46; ``gbtools.check_lock``): un solo ``check.py`` a la vez en el equipo,
   sea de la carpeta que sea (dos a la vez compiten por los procesadores, tardan más y las
   pruebas que miden tiempos fallan). Es ``%LOCALAPPDATA%\\Geoblender\\check.lock`` (o
   ``GEOBLENDER_CHECK_LOCK``), con un bloqueo del sistema que se suelta solo si el proceso
   muere. Si otro lo tiene, escribe tras la cabecera una línea «ESPERANDO: …» con su pid y
   su carpeta, y espera; el tiempo que informa, y que se compara con RNF-001-01, empieza al
   tomarlo. Las órdenes de los pasos llevan ``GEOBLENDER_CHECK_LOCK_HELD`` con su pid: un
   ``check.py`` lanzado desde ellas no espera a su padre. Si no se puede usar, un aviso, y
   sigue sin él. ``tools/publish.py``, que lo lanza, espera igual.
2. Pasos, en este orden (el de la tabla ``STEPS``, que es el del resumen) y todos aunque
   falle alguno: «unitarias» (``tests/unit``, que incluye las reglas de arquitectura y del
   repositorio), «referencia» (``tests/referencia``; sin casos es correcto), «licencias»
   (``tools/check_licenses.py``), «iconos» (``tools/build_icons.py --check``; spec 003,
   T30), «manifiesto» (``blender --command extension validate``) y «blender»
   (``tools/run_blender_tests.py`` dentro de Blender, en segundo plano, de fábrica, con
   ``--python-exit-code 1``). Con ``--completo``, además, «motor»
   (spec 004, RF-004-28: ``tests/unit`` de los paquetes de dominio con el numpy del motor
   de cálculo de pruebas, el Python de Blender con ``-S`` y la carpeta ``site`` del motor
   en ``PYTHONPATH``; el motor lo crea ``tools/make_runtime.py`` en
   ``.deps/runtime/<lock_id>/``, o lo da ``GEOBLENDER_TEST_RUNTIME_SITE``; sin motor, el
   paso se omite por el recurso ``runtime`` con la orden que lo crea: «VERDE CON
   OMISIONES») y, justo después, «arnés» (``tests/arnes`` como «unitarias»: las pruebas
   del propio arnés que lanzan Blender entero; sin pruebas, fallo; spec 001 0.6, D-9 de
   la spec 002) y, tras él, «hito» (spec 015, T48; plan 015 §7.4: las pruebas de hito, que
   pesan demasiado para la comprobación de cada tarea: los ``milestone_*.py`` de ``tests/unit``,
   con ``unittest``, y de ``tests/blender``, dentro de Blender, cada grupo en sus partes y todas
   a la vez; sin pruebas, fallo; ``tests.unit.repo.test_test_folders`` y la regla TST-02 las
   admiten con ese nombre y el «verde» no las descubre). Sin la opción no se ejecutan (ni se
   busca el motor), y el resumen lo dice
   antes de ``RESULTADO``: la comprobación de cada tarea va sin ella (RNF-001-01, ≤ 48 s;
   «motor» solo con ella desde la spec 004 0.4 y la 001 0.7, tarea 005/T50) y
   ``tools/publish.py`` la pide siempre. Solo si se piden, y después de los obligatorios:
   «rendimiento» (``--rendimiento``: ``tests/rendimiento`` con el Python de Blender y
   ``tests/rendimiento/blender/perf_*.py`` dentro de Blender), «banco» (``--banco``:
   ``tools/bench_silvestre.py``; sin banco disponible, «omitido», que no es un fallo) y
   «documentación» (``--documentacion``,
   spec 007, RF-007-14: ``tools/check_docs.py`` sobre la documentación que encuentra
   ``repo.find_docs``, la de ``GEOBLENDER_DOCS_DIR`` o la carpeta madre; si no hay o no
   se alcanza, «omitido» con el motivo, que no es un fallo). Los pasos de Blender usan
   un perfil temporal en ``%TEMP%``, que se borra al terminar.

   Los pasos se ejecutan uno tras otro, en ese orden (RF-001-06), salvo los que van a la
   vez que «blender» (``Step.alongside``): desde la spec 001 0.8 (tarea 009/T34;
   RNF-001-01), «referencia», «licencias» e «iconos», y desde la 0.10 (tarea 011/T30;
   RNF-001-01), «unitarias»: se ejecutan con él, tras «manifiesto»,
   que pasa a ser el primero. Empiezan a la vez, cada uno en su hilo y con su
   duración, el fallo de uno no para a los demás y el paso siguiente espera a todos; sus
   líneas del resumen van en su lugar de la tabla, aunque acaben en otro orden: las de
   «unitarias» a «blender» salen cuando han terminado todos. «motor» (``--completo``) iba
   también con ellos (spec 004, T30), y desde la tarea 011/T36 va solo, después de «blender»
   (ver ``STEPS``). Dentro de un paso,
   «unitarias», «referencia» (spec 006, T59) y «blender» reparten sus pruebas en partes que
   se ejecutan a la vez (spec 003,
   T40; RNF-007-01: ≤ 48 s, ≤ 46 s en la spec 007 0.7, ≤ 45 s en la 0.6 y ≤ 40 s antes, sin quitar ninguna prueba): hasta ``UNIT_PARTS`` y
   ``REFERENCE_PARTS`` procesos de ``tools/unittest_part.py`` y ``BLENDER_PARTS`` Blender
   con ``run_blender_tests.py --parte i/n``, sin pasar del número de módulos de prueba en
   disco ni del de procesadores (con uno, la orden de siempre). Cada parte descubre
   todas las pruebas y ejecuta las de sus módulos (``gbtools.parts``); con los tiempos
   medidos, las de ``unittest_part.py`` reparten los ficheros sin importarlos y solo
   importan los suyos (spec 006, T48). Cada Blender, con su propio perfil temporal (la
   parte 1, el de «manifiesto») y con la copia de la extensión que comparten todos
   (``--copia``: ``gbtools.ext_copy.prepare`` la hace en otro hilo, mientras corren los
   pasos anteriores, y la compila; si no se puede, un aviso y cada parte hace la suya;
   :class:`SharedCopy`, spec 006, T48). Las órdenes de Python (las partes de «unitarias»,
   «referencia» y «motor», «licencias»…) van con ``-B`` y reciben en ``PYTHONPYCACHEPREFIX``
   la carpeta del código compilado de la raíz, fuera del repositorio
   (``gbtools.pyc_cache``: la extensión, las pruebas y las herramientas, validadas por el
   hash de su fuente, y la biblioteca de Python), que se refresca al empezar en otro hilo
   (:class:`BytecodeRefresh`; spec 005, T44): leen lo compilado en vez de compilarlo cada
   una; lo que falte o ya no valga lo compila Python en memoria, como antes, y si no se
   puede refrescar, un aviso. Los módulos se reparten
   por su duración medida en la comprobación anterior (spec 004, T39; RNF-001-01): un
   almacén fuera del repositorio, en la carpeta temporal del sistema y uno por raíz
   (:func:`default_times_store`), guarda la de cada módulo de cada suite con partes
   («unitarias», «referencia», «blender» y las de «motor»); antes de los pasos se copia a
   la carpeta temporal de la comprobación y cada parte recibe el fichero de su suite
   (``--tiempos``) y escribe la duración de sus módulos (``--medidas``); al terminar, las
   medidas sustituyen a las guardadas (:class:`PartTimes`). Sin medidas (la primera vez,
   o un almacén borrado o ilegible), el reparto es por número de pruebas, el de la spec
   003 (T40); la salida y los códigos no cambian. Con medidas, además, las partes de cada
   suite se reparten los módulos según acaban (spec 006, T59; ``--cola``,
   ``gbtools.parts.Queue``): cada una empieza por uno de los que más tardan y toma después
   el siguiente que ninguna ha tomado de una cola que comparten, en la carpeta temporal de
   la comprobación; así acaban casi a la vez aunque un módulo tarde más o menos que la vez
   anterior, y cada una escribe su línea «PARTE …» al terminar. Los módulos con la misma afinidad
   (``PART_AFFINITY``: los que pasan las reglas por el repositorio) van a la misma parte, y
   con medidas las carpetas de «motor» se reparten entre ellas sus partes por su tiempo
   (:func:`runtime_parts`; spec 006, T47). El paso dura lo que
   tarda la más lenta, y su línea suma las pruebas de todas (si alguna no llegó a
   contarlas, lo dice: «750 pruebas en 3 de 4 partes»). Un fichero de pruebas
   cuenta como cargado si lo carga cualquier parte; y si las partes no son 1…n, no
   dicen el mismo total o no lo suman («PARTE i de n: r de T pruebas»), o un mismo
   fichero se ejecutó en dos, el reparto perdió o repitió pruebas y el paso falla
   («reparto incompleto»; si por eso no se cargó un fichero, es ese el diagnóstico, y no
   el de los ficheros sin cargar; spec 003, T45). Con Ctrl+C mientras
   se ejecutan, se paran todas (``gbtools.blender.stop_all``), también las de los pasos
   que van a la vez, antes de borrar la carpeta temporal.
3. Resumen: una línea por paso (resultado, duración y pruebas), las pruebas omitidas por
   un recurso opcional (``[ENTORNO] <recurso>: <orden>``) agrupadas con la orden que lo
   instala, la salida entera de cada paso que falla y ``RESULTADO: VERDE``,
   ``RESULTADO: VERDE CON OMISIONES (n)`` o ``RESULTADO: NO VERDE``. Si «licencias»
   falla porque faltan ruedas (un clon o *worktree* nuevo), su línea lleva la orden que
   las descarga (``tools/fetch_wheels.py``, con ``--desde`` si ``GEOBLENDER_WHEELHOUSE``
   está definida).

No hay modo «solo una parte»: un verde parcial se confunde con el verde. Para iterar se
ejecuta ``unittest`` directamente (órdenes en ``AGENTS.md``). ``--completo`` no es una
parte: sin él se ejecutan todas las reglas y todas las pruebas de la extensión, dentro y
fuera de Blender; solo quedan fuera las autopruebas del arnés que relanzan Blender entero,
que prueban ``tools/`` y ``tests/support/`` y no la extensión (plan 001 §5.4.7), y la
segunda pasada de las pruebas unitarias de dominio con el numpy del motor, que «unitarias»
ya ejecuta con el de Blender (spec 004 0.4, RF-004-28).

En los pasos con pruebas, un fichero de pruebas en disco que ``unittest`` no cargó (en
una carpeta sin ``__init__.py``, con un nombre que no es un módulo válido o sin pruebas)
pone el paso en fallo aunque la orden termine con 0 o «sin pruebas» (``gbtools.
discovery``; convergencia de la spec 001, T35). Y un código 0 (o el 5 «sin pruebas» de
``unittest``) solo vale si la salida llega al resumen de ``unittest`` («Ran N tests» y
«OK», o «NO TESTS RAN») y, en el lanzador, a su línea final («FIN DEL LANZADOR: n
pruebas, código 0», con el mismo número): un proceso que sale a mitad con
``os._exit(0)`` no deja ni lo uno ni lo otro (T37). Y «OK (expected failures=n)» no es
verde: una prueba roja marcada con ``expectedFailure`` («con fallos esperados»; T59).

Una omisión es «VERDE CON OMISIONES» solo si es por un recurso opcional, con el motivo
``[ENTORNO] <recurso>: <orden>`` de ``tests.support.resources``: cualquier otra
(``@unittest.skip``, ``skipTest("…")``, el recurso vacío) esconde una prueba que no se
ejecuta y pone su paso en fallo con «OMISIONES SIN RECURSO» (convergencia de la spec
001, T42). El recurso, además, tiene que estar en la lista cerrada ``RESOURCES`` de
``tests/support/resources.py``, que se lee como texto (sin importar ``tests``): un
recurso inventado, o uno que su spec aún no ha declarado, también es una omisión sin
recurso; y si la lista no se puede leer, todas lo son (T47).

Las pruebas y las herramientas solo escriben en carpetas temporales (spec 001 §11;
RF-001-09): la comprobación hace una foto del repositorio (rutas, tamaños y
``mtime_ns``, ignorados incluidos y sin ``.git/``) antes del primer paso y otra tras el
último; si difieren, una línea «repositorio» en fallo y «REPOSITORIO MODIFICADO» con la
lista de cambios (también un ``__pycache__``), aunque todos los pasos sean correctos
(convergencia de la spec 001, T41). La foto guarda también la fecha de cada carpeta:
un fichero que una prueba crea y borra al terminar no queda, pero cambia la fecha de su
carpeta (T51).

Códigos de salida: 0 verde (también con omisiones); 1 algún paso falló (también una
suite obligatoria sin pruebas o un manifiesto ilegible); 2 entorno (Blender ausente o
anterior al mínimo, otro intérprete, dentro de Blender) u opción no válida.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en Z: (plan 001 §5.3)

import ast  # noqa: E402
import hashlib  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402

from gbtools import blender, check_lock, discovery, ext_copy, layout, manifest  # noqa: E402
from gbtools import parts, pyc_cache, repo, wheels  # noqa: E402
from gbtools.blender import BlenderInstall, EnvironmentProblem  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402
from gbtools.rules import imports  # noqa: E402
from make_runtime import ENV_TEST_SITE as ENV_TEST_RUNTIME_SITE  # noqa: E402
from make_runtime import TestRuntime, find_test_runtime  # noqa: E402

STATUS_OK = "correcto"
STATUS_FAIL = "fallo"
STATUS_SKIPPED = "omitido"

# Cómo se interpreta el código de salida de cada orden.
KIND_PLAIN = "orden"  # 0 correcto; otro, fallo
KIND_UNITTEST = "unittest"  # 0 correcto; 5 sin pruebas; otro, fallo
KIND_LAUNCHER = "lanzador"  # run_blender_tests.py: 0; 1 sin pruebas (T57); otro
KIND_BANK = "banco"  # bench_silvestre.py: 0 correcto; 3 omitido; otro, fallo

UNITTEST_NO_TESTS = 5  # «NO TESTS RAN» (plan 001 §2.1, 9)
BANK_OMITTED = 3  # bench_silvestre.py: ningún banco disponible (plan 001 §5.2)
LAUNCHER_NO_TESTS = "NO HAY PRUEBAS"
NO_TESTS = "sin pruebas"
NO_CASES = "sin casos"
SUMMARY_MISSING = "sin el resumen de unittest"
LAUNCHER_END_MISSING = "sin la línea final del lanzador"
EXPECTED_FAILURES = "con fallos esperados"  # «OK (expected failures=n)» (T59)

SKIP_PREFIX = "[ENTORNO]"  # el de tests/support/resources.py
OTHER_SKIPS = "otras omisiones"  # sin «[ENTORNO] <recurso>»: fallo del paso (T42)
RESOURCES_RELPATH = "tests/support/resources.py"  # su lista cerrada de recursos (T47)
RESOURCES_NAME = "RESOURCES"
TEMP_PREFIX = "geoblender-check-"
PROFILE_FOLDER = "perfil"
# La copia de pruebas de la extensión que comparten las partes de «blender» (spec 006, T48;
# gbtools.ext_copy), en la carpeta temporal de la comprobación, y la opción del lanzador
# que la recibe (run_blender_tests.COPY_OPTION).
COPY_FOLDER = "copia"
COPY_OPTION = "--copia"
COPY_THREAD = "check-copia"
# El código compilado de las órdenes de Python (spec 005, T44; gbtools.pyc_cache): la
# variable con que lo reciben y el hilo que lo refresca.
ENV_BYTECODE = pyc_cache.ENV_PREFIX
BYTECODE_THREAD = "check-pyc"
STEP_TIMEOUT_S = 1800.0  # sin --completo, la comprobación tarda ≤ 48 s (RNF-001-01)
# El plazo de cada orden de «rendimiento» y de «banco» (Step.timeout_s; tarea 009/T38, F-3 de
# su verificación): con GEOBLENDER_NET_TEST_DIR, el unittest de tests/rendimiento tardaba unos
# 2 200 s (test_versions_perf, ≈ 1 091 s, crea 5 GB en la red y los congela dos veces) y se
# paraba a los 1 800 s sin dar ninguna medida. El paso no se parte: su orden tiene más plazo.
LONG_STEP_TIMEOUT_S = 7200.0
LAUNCHER_RELPATH = "tools/run_blender_tests.py"
PART_RELPATH = "tools/unittest_part.py"  # una parte de «unittest discover» (T40)
# Partes de «unitarias» y de «blender» (spec 003, T40; RNF-007-01): a la vez, sin pasar
# del número de módulos de prueba ni del de procesadores (part_count). Con el reparto por
# tiempo (spec 004, T39), 6 partes de «unitarias» tardan ≈ 14 s frente a ≈ 21 s con 4;
# por número de pruebas, más partes podían juntar los módulos lentos en una. En el PC de
# referencia (24 hilos; spec 006, T38), 12 partes de «unitarias» tardan ≈ 12,5 s frente a
# ≈ 16 s con 6 (y ≈ 12,5 s con 10: el suelo es su módulo más lento, test_check_cli, con el
# arranque de la parte), y 5 de «blender» con «motor» a la vez ≈ 14 s frente a ≈ 18 s con
# 3 y ≈ 15,5 s con 4 (con 6, igual que con 5: el suelo es test_jobs, con su trabajo de
# 10 s). Con las pruebas de la 006 y de la 008 juntas y test_check_cli partido en cuatro
# (spec 006, T46), 16 partes de «unitarias» tardan ≈ 18 s frente a ≈ 19,6 s con 12 (con 20,
# igual que con 16: el suelo es test_naming, que recorre el repositorio entero con todas
# las reglas, con el arranque de la parte). «blender» sigue con 5, que con «motor» a la vez
# tardan ≈ 16,5 s con sus partes ya igualadas: partir test_jobs no rinde (con 5 partes,
# ≈ 17,6 s, porque sus trabajos reales coinciden con los de otras partes; con 6, ≈ 15,9 s,
# pero con la CPU llena el autodiagnóstico de 10 s, que mide sus avances en tiempo real,
# falla una de cada cuatro veces). Con las reglas analizando cada fichero una sola vez por
# proceso y las pruebas que las pasan por el repositorio juntas (spec 006, T47:
# PART_AFFINITY, gbtools.parts.affinity_of), los módulos de «unitarias» suman ≈ 183 s en vez
# de ≈ 207 s, el proceso que las pasa ya no tarda ≈ 2 s en cerrarse (rules.pyast.clear_caches)
# y el paso tarda ≈ 15 s: el suelo es el reparto, con el arranque de cada parte. Con las
# pruebas de la fase 5 de la 006 y la 008 completa (spec 006, T48), cada parte de
# «unitarias» importaba todos los módulos de prueba para ejecutar los suyos (≈ 1,7 s en
# reposo): repartiendo los ficheros por su tiempo y cargando solo los suyos
# (gbtools.parts.select_files), 16 partes tardan ≈ 15,5 s frente a ≈ 17,5 s (con 20, igual).
# Y las clases de las pruebas de Blender que no prueban el registro ya no vuelven a importar
# la extensión al habilitarla (tests.support.blender_ext.release: 76 → 44 s en serie), las
# partes de «blender» comparten una copia de la extensión ya compilada (SharedCopy) y su
# código compilado se guarda tras descubrir las pruebas: con «motor» a la vez, 6 partes de
# «blender» tardan ≈ 17 s frente a ≈ 19 s con 5 (con 7, ≈ 16,3 s). Con las pruebas de la
# fase 5 de la 006 (spec 006, T59), y sin las importaciones de más (la prueba de la GPU al
# final de su parte, run_blender_tests.py, y las clases del registro con
# tests.support.blender_ext.fresh), con «motor» a la vez y el almacén de tiempos medido con
# las mismas partes, 7 partes tardan ≈ 19,0 s (18,6–19,9) frente a ≈ 20,2 s (19,2–20,4)
# con 6: el suelo vuelve a ser test_jobs, con sus trabajos reales. Y cada parte de
# «unitarias» ya no analiza todos los ficheros para leer su afinidad (solo los que la
# nombran: ≈ 0,64 s menos por parte; gbtools.parts.source_affinity): con 20 partes, ≈ 16,1 s
# frente a ≈ 16,7 s con 16, pero el equipo va más cargado y la cancelación del trabajo de
# hash de la 008 (tests/unit/workers/test_core_content_hash.py, frágil con carga) falló 5
# de 5 veces frente a 0 de 3 con 16; con 24, ≈ 17,3 s. Con las pruebas de la fase 2 de la
# 005 (spec 005, T44), las órdenes de Python leen su código compilado (gbtools.pyc_cache) y
# las bases de RecMin se crean una vez (tests.support.recmin.shared_bases): cada parte
# importa en ≈ 1 s en vez de ≈ 1,4 s y el equipo va menos cargado, y 18 partes tardan
# ≈ 18,8 s frente a ≈ 19,5 s con 16 (con 20, igual que con 18), sin fallos en las 11 veces
# que se midió. Desde la spec 001 0.10 (tarea 011/T30), «unitarias» va a la vez que
# «blender»: con 18 partes, más las 7 de «blender» y las 3 de «referencia», los 24
# procesadores se llenan y fallaron pruebas de plazos (las cancelaciones en ≤ 2 s de la 008 y
# la 006, el cierre de los huérfanos en ≤ 3 s, el avance cada 0,5 s) en 5 de 6 vueltas; con 12
# (12 + 7 + 3 ≈ los procesadores, menos el hilo de Blender), ninguna de unitarias en 3 vueltas, y
# la comprobación, 37–39 s.
UNIT_PARTS = 12
BLENDER_PARTS = 7
# Partes de «referencia» (spec 006, T59; RNF-001-01): el paso iba solo, con el equipo casi
# libre, y en una orden tardaba ≈ 2,0 s con sus 28 casos (dos de ellos lanzan el Python de
# QGIS). En reposo, con 2 partes ≈ 1,36 s, con 3 ≈ 1,14 s, con 4 ≈ 1,0 s y con 5, 6 o 9
# ≈ 0,87 s: el suelo es su módulo más lento (el de GDAL), con el arranque de la parte. Desde
# la spec 001 0.8 (tarea 009/T34) va a la vez que «blender», que tarda ≈ 19 s: con 6, 3 o 2
# partes tarda ≈ 2,3 s (su suelo, el caso de QGIS de la 009, ≈ 2 s), y «blender» y la
# comprobación, lo mismo dentro del ruido (con el equipo cargado: medianas de 3, 45,1, 43,9 y
# 45,0 s); con 3, la mitad de procesos que con 6 le quitan procesador a «blender».
REFERENCE_PARTS = 3
THREAD_PREFIX = "check-parte-"  # los hilos que esperan a cada parte
JOIN_POLL_S = 0.1  # se espera a los hilos a ratos: así Ctrl+C llega enseguida
SIGINT_WAIT_S = 0.25  # tras Ctrl+C, lo que espera subprocess antes de parar la orden
STOP_WAIT_S = 30.0  # después, lo que se espera a cada hilo con su orden ya parada
PARTS_PROBLEM = "reparto incompleto"
UNITTEST_PATTERN = discovery.UNITTEST_PATTERN  # el de unittest discover sin «-p»
LAUNCHER_PATTERN = "test_*.py"  # el del lanzador sin «--patron» (DEFAULT_PATTERN)
OPTION_COMPLETE = layout.CHECK_COMPLETE_OPTION  # «--completo»: los pasos «motor» y «arnés»
OPTION_PERFORMANCE = "--rendimiento"
OPTION_BANK = "--banco"
OPTION_DOCS = "--documentacion"
OPTIONS: tuple[str, ...] = (OPTION_COMPLETE, OPTION_PERFORMANCE, OPTION_BANK, OPTION_DOCS)
HARNESS_STEP = "arnés"
HARNESS_FOLDER = layout.HARNESS_TESTS_RELPATH
RUNTIME_STEP = "motor"
# El paso de las pruebas de hito (spec 015, T48; plan 015 §7.4; solo con ``--completo``): las
# ``milestone_*.py`` de ``tests/unit`` (``unittest``) y de ``tests/blender`` (dentro de Blender),
# que pesan demasiado para la comprobación de cada tarea. Van en partes, como sus hermanas: las
# unitarias de hito suman ≈ 85 s de módulos (8 partes ≈ 11 s) y las de Blender ≈ 30 s (4 partes,
# una por módulo, ≈ 10 s con el arranque de la extensión), y corren a la vez.
MILESTONE_STEP = "hito"
MILESTONE_PATTERN = discovery.MILESTONE_PATTERN
MILESTONE_UNIT_FOLDER = "tests/unit"
MILESTONE_BLENDER_FOLDER = "tests/blender"
MILESTONE_UNIT_PARTS = 8
MILESTONE_BLENDER_PARTS = 4
# La línea del resumen sin --completo (RF-001-06; spec 001 0.7, spec 004 0.4: RF-004-28).
NOT_COMPLETE = (
    f"Sin {OPTION_COMPLETE}: no se han ejecutado las pruebas del arnés que lanzan Blender "
    f"entero ({HARNESS_FOLDER}) ni las unitarias de los paquetes de dominio con el motor "
    f"de cálculo de pruebas («{RUNTIME_STEP}», RF-004-28) ni las pruebas de hito "
    f"(«{MILESTONE_STEP}», {MILESTONE_PATTERN} de tests/unit y de tests/blender); las ejecuta "
    f"tools/check.py {OPTION_COMPLETE}, y la publicación (tools/publish.py) las pide siempre."
)
RUNTIME_RESOURCE = "runtime"  # el recurso de tests/support/resources.py (spec 004)
DOMAIN_TESTS = "tests/unit"  # tests/unit/<paquete de dominio> (imports.LEVELS)
# Partes de cada carpeta de dominio en «motor», que va a la vez que «blender» (spec 004,
# T30): con 2, «blender» tarda ≈ 1 s más (≈ 2 s con el equipo cargado) y «motor» acaba
# antes que él; después de él (≈ 12 s más) no cabría en RNF-001-01. Con 2 de cada carpeta,
# tests/unit/jobs tarda ≈ 12–13,5 s, casi lo que 5 partes de «blender» (spec 006, T38);
# con 4, «motor» acaba en ≈ 8,5 s (con 3, ≈ 9,3 s), y «blender» tarda lo mismo con 3 o 4.
# A la vez que «unitarias» no compensa: las alarga lo mismo (≈ 2,5 s) que a «blender».
# Con las pruebas de la 006 y de la 008 juntas, tests/unit/core suma ≈ 62 s de módulos y,
# con 4, «motor» tarda ≈ 18,5 s, más que «blender» (≈ 16,5 s): con 6, ≈ 15,4 s (con 5,
# ≈ 16,8 s), y el suelo vuelve a ser «blender», que tarda lo mismo. Desde la tarea 011/T36,
# «motor» va solo, después de «blender» (ver STEPS): las partes no cambian (≈ 19–22 s).
RUNTIME_PARTS = 6
# Con las duraciones medidas de los módulos de todas las carpetas de dominio, «motor» no
# reparte RUNTIME_PARTS por carpeta sino, como mucho, RUNTIME_PROCESSES entre todas, por su
# tiempo (spec 006, T47; gbtools.parts.share), y nunca más que con RUNTIME_PARTS: con
# tests/unit/core en ≈ 72 s de módulos, jobs en ≈ 42 s y gis en ≈ 7,5 s, 6 de cada una (19
# órdenes) dejan «blender» ∥ «motor» en ≈ 16,8 s (core, el suelo de «motor», ≈ 15 s); 16
# por tiempo (core 8, jobs 5, gis 2 e interop 1), en ≈ 16,4 s, con «motor» en ≈ 12,8 s; 14
# (7, 4, 2 y 1), igual; con 18 (10, 6 y 2) acaba antes «motor», pero «blender» no, y con el
# equipo lleno fallan las pruebas de tiempo de tests/unit/jobs (test_cancel_timeout).
RUNTIME_PROCESSES = 16
# Las duraciones medidas de los módulos de prueba (spec 004, T39; RNF-001-01): el almacén,
# en la carpeta temporal del sistema (uno por raíz), y los ficheros de las partes, en la
# de la comprobación. Cada suite con partes tiene su clave (times_key): con qué se
# ejecuta (el Python de Blender, el motor de cálculo de pruebas o Blender), su carpeta y
# su patrón.
TIMES_STORE_FOLDER = "geoblender-tiempos"
TIMES_WORK_FOLDER = "tiempos"
TIMES_PYTHON = "python"
TIMES_RUNTIME = "motor"
TIMES_BLENDER = "blender"
DOCS_STEP = "documentación"
DOCS_RELPATH = "tools/check_docs.py"
NO_DOCS = f"no hay documentación en la carpeta madre ni en {layout.ENV_DOCS_DIR}"
REPOSITORY = "repositorio"  # la línea del resumen si la comprobación cambió el árbol
REPOSITORY_SKIP = (".git",)  # lo cambia git, no la comprobación

USAGE = """Uso (con el Python de Blender, desde la raíz del repositorio):
  & "<Blender>\\5.2\\python\\bin\\python.exe" tools/check.py [--completo] [--rendimiento] [--banco] [--documentacion]

  --completo        añade, a la vez que «blender», las pruebas unitarias de los
                    paquetes de dominio con el motor de cálculo de pruebas («motor»,
                    tools/make_runtime.py) y, tras ellas, las del arnés que lanzan
                    Blender entero (tests/arnes) y las pruebas de hito («hito»:
                    milestone_*.py de tests/unit y de tests/blender); la publicación
                    (tools/publish.py) la pide siempre, y la comprobación de cada tarea
                    va sin ella
  --rendimiento     añade las pruebas de rendimiento (también las de dentro de Blender)
  --banco           añade los bancos privados: Silvestre (GEOBLENDER_SILVESTRE_DIR) y
                    la base de RecMin (GEOBLENDER_RECMIN_BANK_DIR)
  --documentacion   añade la comprobación de la documentación (tools/check_docs.py en
                    GEOBLENDER_DOCS_DIR o en la carpeta madre; sin ella, «omitido»)
  --ayuda, -h       muestra esta ayuda

Blender: GEOBLENDER_BLENDER (ruta a blender.exe o a su carpeta) o la ruta por defecto
«C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe».
Códigos: 0 verde (también con omisiones), 1 no verde, 2 entorno u opción no válida."""

_RAN = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)
_OK_LINE = re.compile(r"^OK( \(.*\))?$")  # «OK» u «OK (skipped=3)» tras «Ran N tests»
_NO_TESTS_LINE = re.compile(r"^NO TESTS RAN$")
_LAUNCHER_NO_TESTS_LINE = re.compile(rf"^{LAUNCHER_NO_TESTS} en ", re.MULTILINE)
_TEST_HEAD = discovery.TEST_HEAD
_SKIPPED = re.compile(
    r"\.\.\. skipped (?P<reason>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")\s*$"
)
# Donde empieza una medida «RNF-NNN-nn: …»; no tras otro requisito de la misma lista
# («RNF-008-11, RNF-005-05: …» es una sola: spec 005, T60).
_MEASURE_START = re.compile(r"(?<!-\d{3}-\d{2}, )(?=RNF-\d{3}-\d{2}: )")
# La cabecera de una prueba sola en su línea (``unittest -v``; spec 005, T60): la línea
# siguiente es la primera de su docstring. Al empezar la prueba, «nombre (módulo.Clase.
# nombre)»; la de una subprueba que falla, con sangría y sus parámetros; en el informe de
# un fallo, tras «FAIL: », «ERROR: » o «UNEXPECTED SUCCESS: ».
_DESCRIBED_HEAD = re.compile(
    r"^(?:(?:FAIL|ERROR|UNEXPECTED SUCCESS): | *)"
    r"(?P<name>[A-Za-z_]\w*) \([\w.]+\.(?P=name)\)(?: .*)?$"
)
_OMITTED_BANK = re.compile(r"^OMITIDO: (?P<bank>[^:]+): (?P<why>.+)$", re.MULTILINE)
_CLASS_FIXTURES = frozenset(
    {"setUpClass", "tearDownClass", "setUpModule", "tearDownModule"}
)


class UsageError(Exception):
    """Opciones no válidas: el mensaje dice cuál."""


class ManifestProblem(Exception):
    """El manifiesto no permite saber la versión mínima de Blender."""


@dataclass(frozen=True)
class Options:
    flags: frozenset[str] = frozenset()  # opciones pedidas: --completo, --rendimiento…
    show_help: bool = False


@dataclass(frozen=True)
class Run:
    """Una orden de un paso: qué se ejecuta, con qué entorno y cómo se interpreta.

    En las de pruebas, ``folder`` (relativa a la raíz) y ``pattern`` dicen qué ficheros
    de prueba hay en disco, para comprobar que ``unittest`` los cargó todos.
    """

    command: list[str]
    env: dict[str, str]
    kind: str = KIND_PLAIN
    empty: str | None = None  # sin pruebas: None es fallo; si no, el texto (correcto)
    folder: str | None = None
    pattern: str | None = None
    part: tuple[int, int] | None = None  # (i, n): una parte de unas pruebas (T40)


def default_times_store(root: Path) -> Path:
    """El almacén de las duraciones medidas de los módulos de prueba de la raíz ``root``
    (spec 004, T39): un fichero en la carpeta temporal del sistema, fuera del repositorio
    (las herramientas solo escriben en carpetas temporales: RF-001-09), y uno por raíz
    (cada clon o *worktree* tiene sus pruebas)."""
    name = os.path.normcase(os.path.abspath(root))
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / TIMES_STORE_FOLDER / f"{digest}.json"


def times_key(flavor: str, folder: str, pattern: str) -> str:
    """La clave de una suite con partes en el almacén de tiempos: con qué se ejecuta
    (``TIMES_PYTHON``, ``TIMES_RUNTIME`` o ``TIMES_BLENDER``), su carpeta y su patrón."""
    return f"{flavor}:{folder}:{pattern}"


@dataclass
class PartTimes:
    """Las duraciones medidas de los módulos de las suites con partes (spec 004, T39;
    RNF-001-01, RNF-007-01): las del almacén ``store`` (``{suite: {módulo: s}}``), que se
    copian, una suite por fichero, a ``folder`` (en la carpeta temporal de la
    comprobación), donde cada parte escribe también las suyas. Lo crea :meth:`load`; las
    órdenes de las partes llevan :meth:`options`; :meth:`save`, tras los pasos, guarda
    las medidas en el almacén."""

    store: Path
    folder: Path
    stored: dict[str, dict[str, float]] = field(default_factory=dict)
    parts_of: dict[str, int] = field(default_factory=dict)  # suite → partes ejecutadas

    @classmethod
    def load(cls, store: Path, folder: Path) -> PartTimes:
        """Lee el almacén (si falta o no se puede leer, sin medidas) y copia los tiempos
        de cada suite a ``folder``."""
        found = cls(store, folder, parts.read_store(store))
        folder.mkdir(parents=True, exist_ok=True)
        for key, modules in found.stored.items():
            parts.write_times(found.times_file(key), modules)
        return found

    @staticmethod
    def _name(key: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")

    def times_file(self, key: str) -> Path:
        """El fichero con los tiempos guardados de la suite ``key`` (``--tiempos``)."""
        return self.folder / f"{self._name(key)}.json"

    def measures_file(self, key: str, part: tuple[int, int]) -> Path:
        """El fichero en que escribe sus medidas la parte ``part`` de la suite ``key``."""
        return self.folder / f"{self._name(key)}-{part[0]}de{part[1]}.json"

    def queue_folder(self, key: str) -> Path:
        """La carpeta de la cola que comparten las partes de la suite ``key`` (spec 006,
        T59; ``--cola``, ``gbtools.parts.Queue``): una por suite y comprobación."""
        return self.folder / f"{self._name(key)}-cola"

    def options(self, key: str, part: tuple[int, int]) -> list[str]:
        """Las opciones de la orden de la parte ``part`` de la suite ``key``: si hay
        medidas guardadas, el fichero de sus tiempos y la cola que comparten sus partes
        (spec 006, T59: se reparten los módulos según acaban; sin ellas, la parte reparte
        por número de pruebas), y el fichero de sus medidas."""
        self.parts_of[key] = part[1]
        found: list[str] = []
        if key in self.stored:
            found += [parts.TIMES_OPTION, str(self.times_file(key)),
                      parts.QUEUE_OPTION, str(self.queue_folder(key))]
        return [*found, parts.MEASURES_OPTION, str(self.measures_file(key, part))]

    def save(self) -> None:
        """Guarda en el almacén las medidas de las partes que se ejecutaron
        (``parts.merge``: las de todas las partes de una suite sustituyen a las guardadas;
        si falta alguna, se conservan las demás); las suites que no se ejecutaron se
        conservan. Si nada cambia, no escribe."""
        suites = dict(self.stored)
        for key, count in self.parts_of.items():
            measures = [
                found
                for number in range(1, count + 1)
                if (found := parts.read_measures(self.measures_file(key, (number, count))))
                is not None
            ]
            if measures:
                suites[key] = parts.merge(self.stored.get(key, {}), measures)
        if suites != self.stored:
            parts.write_store(self.store, suites)


class SharedCopy:
    """La copia de pruebas de la extensión que usan todas las partes de «blender» (spec
    006, T48; RNF-001-01): ``prepare(raíz, destino)`` (``gbtools.ext_copy.prepare``) la
    hace en otro hilo mientras corren los pasos anteriores; :meth:`result` espera a que
    termine y da la carpeta, o ``None`` si no se pudo (entonces, la primera vez, un aviso
    con el motivo, y cada parte hace la suya, como antes)."""

    def __init__(self, prepare: Callable[[Path, Path], Path], root: Path, target: Path) -> None:
        self._prepare = prepare
        self._root = root
        self._target = target
        self._folder: Path | None = None
        self.problem: str | None = None
        self._warned = False
        self._thread = threading.Thread(target=self._run, name=COPY_THREAD, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self._folder = self._prepare(self._root, self._target)
        except Exception as exc:  # noqa: BLE001 - sin copia compartida, la de cada parte
            self.problem = f"{type(exc).__name__}: {exc}"

    def result(self) -> Path | None:
        """La carpeta de la copia, cuando está hecha, o ``None`` si no se pudo hacer."""
        self._thread.join()
        if self._folder is None and not self._warned:
            self._warned = True
            print(
                "AVISO: no se pudo preparar la copia de la extensión para las partes de "
                f"«blender» ({self.problem}): cada parte hace la suya",
                flush=True,
            )
        return self._folder


class BytecodeRefresh:
    """El refresco de la carpeta del código compilado de las órdenes de Python (spec 005,
    T44; RNF-001-01; ``gbtools.pyc_cache.prepare``): ``refresh(carpeta, raíz, sites)`` en
    otro hilo desde que empieza la comprobación. No hay que esperarlo: lo que una orden
    importe antes de que esté compilado (o lo que no se pudo compilar), Python lo compila
    en memoria, como sin la carpeta. :meth:`wait` espera a que acabe y, si falló, da el
    aviso con el motivo; la comprobación no cambia."""

    def __init__(
        self,
        refresh: Callable[[Path, Path, Sequence[Path]], object],
        folder: Path,
        root: Path,
        sites: Sequence[Path],
    ) -> None:
        self.folder = folder
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run, args=(refresh, folder, root, list(sites)),
            name=BYTECODE_THREAD, daemon=True,
        )
        self._thread.start()

    def _run(self, refresh: Callable[[Path, Path, Sequence[Path]], object], folder: Path,
             root: Path, sites: list[Path]) -> None:
        try:
            refresh(folder, root, sites)
        except Exception as exc:  # noqa: BLE001 - se avisa; sin la carpeta, como antes
            self._error = exc

    def wait(self) -> str | None:
        """Espera a que termine; si falló, el aviso (si no, ``None``)."""
        self._thread.join()
        if self._error is None:
            return None
        return (f"AVISO: no se pudo preparar el código compilado de las pruebas en "
                f"«{self.folder}»: {self._error}; las órdenes compilan lo que les falte, "
                "como antes")


@dataclass(frozen=True)
class Context:
    """Lo que necesitan los pasos para construir sus órdenes."""

    root: Path
    install: BlenderInstall
    profile: Path
    blender_modules: frozenset[str] = frozenset()
    # Donde se buscan la documentación (GEOBLENDER_DOCS_DIR) y el motor de cálculo de
    # pruebas (GEOBLENDER_TEST_RUNTIME_SITE); None: el del proceso.
    environ: Mapping[str, str] | None = None
    # Cómo se busca el motor de cálculo de pruebas (spec 004, T30).
    find_runtime: Callable[[Path, Mapping[str, str]], TestRuntime] = find_test_runtime
    # Las duraciones medidas de los módulos de prueba (spec 004, T39); None: sin almacén,
    # las órdenes de siempre.
    times: PartTimes | None = None
    # El pid del check.py que tiene el cerrojo del equipo (este, o su padre si lo heredó;
    # spec 006, T46): sus órdenes lo llevan en GEOBLENDER_CHECK_LOCK_HELD, para que un
    # check.py lanzado desde ellas no lo espere. None: sin cerrojo, las órdenes de siempre.
    lock_owner: int | None = None
    # La copia de pruebas de la extensión que comparten las partes de «blender» (spec 006,
    # T48); None: cada parte hace la suya, las órdenes de siempre.
    shared_copy: SharedCopy | None = None
    # La carpeta del código compilado de las órdenes de Python (spec 005, T44;
    # gbtools.pyc_cache); None: sin PYTHONPYCACHEPREFIX, las órdenes de siempre.
    bytecode: Path | None = None

    def _with_lock(self, env: dict[str, str]) -> dict[str, str]:
        """``env`` con ``GEOBLENDER_CHECK_LOCK_HELD`` si hay cerrojo (spec 006, T46)."""
        if self.lock_owner is not None:
            env[check_lock.ENV_HELD] = str(self.lock_owner)
        return env

    def part_options(self, flavor: str, folder: str, pattern: str,
                     part: tuple[int, int]) -> list[str]:
        """Las opciones de tiempos de la orden de una parte (:meth:`PartTimes.options`),
        o ninguna sin almacén."""
        if self.times is None:
            return []
        return self.times.options(times_key(flavor, folder, pattern), part)

    def docs_environ(self) -> Mapping[str, str]:
        """El entorno en que se busca la documentación (``repo.find_docs``)."""
        return os.environ if self.environ is None else self.environ

    def test_runtime(self) -> TestRuntime:
        """El motor de cálculo de pruebas (``make_runtime.find_test_runtime``): su carpeta
        ``site`` o el motivo por el que no hay."""
        return self.find_runtime(self.root, self.docs_environ())

    def python_env(self) -> dict[str, str]:
        """Entorno del Python de Blender fuera de Blender (``gbtools.blender``), con la
        carpeta del código compilado en ``PYTHONPYCACHEPREFIX`` si la hay (spec 005, T44);
        si no, sin esa variable."""
        env = blender.python_env(self.root)
        env.pop(imports.ENV_BLENDER_MODULES, None)
        if self.blender_modules:
            env[imports.ENV_BLENDER_MODULES] = ",".join(sorted(self.blender_modules))
        env.pop(ENV_BYTECODE, None)
        if self.bytecode is not None:
            env[ENV_BYTECODE] = str(self.bytecode)
        return self._with_lock(env)

    def part_profile(self, number: int) -> Path:
        """El perfil temporal de la parte ``number`` de unas pruebas de Blender: el de
        siempre para la 1 y, para las demás, uno propio a su lado (``perfil-2``…), que
        ``main`` crea con el de siempre (T40)."""
        if number == 1:
            return self.profile
        return self.profile.with_name(f"{self.profile.name}-{number}")

    def blender_env(self, part: tuple[int, int] | None = None) -> dict[str, str]:
        """Entorno de Blender con el perfil temporal (``gbtools.blender``), el de la
        parte si se da."""
        profile = self.profile if part is None else self.part_profile(part[0])
        return self._with_lock(blender.isolated_env(profile))

    def parts_of(self, folder: str, pattern: str, limit: int) -> int:
        """En cuántas partes se ejecutan las pruebas de ``folder``: ``limit``, sin pasar
        del número de ficheros de prueba en disco ni del de procesadores
        (:func:`part_count`)."""
        found = discovery.expected_modules(self.root / folder, pattern, self.root)
        return part_count(limit, len(found))

    def python(self, *args: str, kind: str = KIND_PLAIN, empty: str | None = None) -> Run:
        """Una orden con el Python de Blender (``-B -s -X utf8``)."""
        return Run(blender.python_cmd(self.install, *args), self.python_env(), kind, empty)

    def unittest(
        self,
        folder: str,
        pattern: str | None = None,
        empty: str | None = None,
        part: tuple[int, int] | None = None,
        *,
        site: Path | None = None,
    ) -> Run:
        """``unittest discover -v`` de ``folder`` con la raíz como nivel superior; una
        prueba que devuelve algo (``async def`` en un ``TestCase``, o con ``yield``) es
        un error y no solo un aviso (``-W``; convergencia de la spec 001, T54). Con
        ``part``, solo esa parte, con ``tools/unittest_part.py`` (T40). Con ``site`` (la
        carpeta de paquetes del motor de cálculo de pruebas; spec 004, RF-004-28), con su
        numpy: el Python de Blender con ``-S`` (sin su ``site-packages``, donde está el
        numpy de Blender) y ``site`` al principio de ``PYTHONPATH``, delante de
        ``.deps/site``."""
        args = ["-W", discovery.UNITTEST_WARNINGS]
        if part is None:
            args += ["-m", "unittest"]
        else:
            args += [PART_RELPATH, parts.OPTION, parts.label(*part)]
            flavor = TIMES_PYTHON if site is None else TIMES_RUNTIME
            suite_pattern = UNITTEST_PATTERN if pattern is None else pattern
            args += self.part_options(flavor, folder, suite_pattern, part)
        args += ["discover", "-v", "-s", folder, "-t", "."]
        if pattern is not None:
            args += ["-p", pattern]
        env = self.python_env()
        if site is not None:
            args = ["-S", *args]
            env["PYTHONPATH"] = os.pathsep.join([str(site), env["PYTHONPATH"]])
        return Run(
            blender.python_cmd(self.install, *args),
            env,
            KIND_UNITTEST,
            empty,
            folder,
            UNITTEST_PATTERN if pattern is None else pattern,
            part,
        )

    def unittest_parts(
        self, folder: str, limit: int, empty: str | None = None, pattern: str | None = None
    ) -> list[Run]:
        """Las pruebas de ``folder`` (``unittest``) en tantas partes como
        :meth:`parts_of`; con una, la orden de siempre (T40). ``empty``, el de cada orden
        y ``pattern``, el de sus ficheros (:meth:`unittest`)."""
        count = self.parts_of(folder, UNITTEST_PATTERN if pattern is None else pattern, limit)
        if count == 1:
            return [self.unittest(folder, pattern=pattern, empty=empty)]
        return [
            self.unittest(folder, pattern=pattern, empty=empty, part=(i, count))
            for i in range(1, count + 1)
        ]

    def blender_tests(
        self,
        folder: str,
        pattern: str | None = None,
        empty: str | None = None,
        part: tuple[int, int] | None = None,
    ) -> Run:
        """``tools/run_blender_tests.py`` sobre ``folder``, dentro de Blender; con
        ``part``, solo esa parte (``--parte i/n``) y con su perfil (T40); con la copia
        compartida, ``--copia`` (spec 006, T48)."""
        args = ["--carpeta", folder]
        if pattern is not None:
            args += ["--patron", pattern]
        if part is not None:
            args += [parts.OPTION, parts.label(*part)]
            suite_pattern = LAUNCHER_PATTERN if pattern is None else pattern
            args += self.part_options(TIMES_BLENDER, folder, suite_pattern, part)
        copy = self.shared_copy.result() if self.shared_copy is not None else None
        if copy is not None:
            args += [COPY_OPTION, str(copy)]
        command = blender.background_cmd(self.install, self.root / LAUNCHER_RELPATH, *args)
        return Run(
            command,
            self.blender_env(part),
            KIND_LAUNCHER,
            empty,
            folder,
            LAUNCHER_PATTERN if pattern is None else pattern,
            part,
        )

    def blender_tests_parts(
        self, folder: str, limit: int, pattern: str | None = None
    ) -> list[Run]:
        """Las pruebas de ``folder`` (lanzador, con ``pattern`` si se da) en tantas partes
        como :meth:`parts_of`; con una, la orden de siempre (T40)."""
        count = self.parts_of(folder, LAUNCHER_PATTERN if pattern is None else pattern, limit)
        if count == 1:
            return [self.blender_tests(folder, pattern)]
        return [
            self.blender_tests(folder, pattern, part=(i, count)) for i in range(1, count + 1)
        ]

    def extension(self, *args: str) -> Run:
        """``blender --factory-startup --command extension …`` con el perfil temporal."""
        return Run(blender.extension_cmd(self.install, *args), self.blender_env())


@dataclass(frozen=True)
class Step:
    """Un paso de la comprobación: su nombre, sus órdenes, si es opcional la opción que
    lo pide (``None``: obligatorio), si falla, qué orden propone el resumen a partir de
    su salida (``advice``) y, antes de ejecutar nada, si hay que omitirlo (``omit``
    devuelve el motivo, o ``None``): un paso omitido no es un fallo, y el resumen lo
    cuenta como omisión con su motivo, por el recurso ``resource`` (si no se da, el
    nombre del paso). Sin órdenes que ejecutar, el paso es correcto con el detalle
    ``empty``. Con ``alongside``, el paso se ejecuta a la vez que ese otro paso de la tabla,
    si también se ejecuta y va solo (:func:`run_steps`): cuando le toca a él, aunque el paso
    esté antes en la tabla (spec 004, T30; spec 001 0.8, tarea 009/T34), y su línea va en su
    lugar. ``timeout_s`` es el plazo de cada una de sus órdenes: la que no termina en él es un
    fallo del paso (tarea 009/T38: «rendimiento» y «banco», ``LONG_STEP_TIMEOUT_S``)."""

    name: str
    runs: Callable[[Context], Sequence[Run]]
    option: str | None = None
    advice: Callable[[Context, str], list[str]] | None = None
    omit: Callable[[Context], str | None] | None = None
    resource: str | None = None
    alongside: str | None = None
    empty: str | None = None
    timeout_s: float = STEP_TIMEOUT_S


@dataclass(frozen=True)
class Skip:
    """Una prueba omitida: cuál, qué recurso falta y la orden que lo instala."""

    test: str
    resource: str
    hint: str


@dataclass
class StepResult:
    """Resultado de un paso (plan 001 §5.2)."""

    name: str
    status: str
    seconds: float
    tests: int | None = None
    detail: list[str] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)
    output: str = ""
    measurements: list[str] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)


@dataclass
class _RunOutcome:
    status: str
    tests: int | None
    detail: str
    skipped: list[Skip]
    output: str
    text: str


def _unit(ctx: Context) -> list[Run]:
    return ctx.unittest_parts("tests/unit", UNIT_PARTS)


def _reference(ctx: Context) -> list[Run]:
    return ctx.unittest_parts("tests/referencia", REFERENCE_PARTS, empty=NO_CASES)


def _licenses(ctx: Context) -> list[Run]:
    return [ctx.python("tools/check_licenses.py")]


def _icons(ctx: Context) -> list[Run]:
    """Paso «iconos» (spec 003, T30; RNF-003-09): fuentes SVG, PNG y manifiesto al día,
    sin rasterizar (``tools/build_icons.py --check``)."""
    return [ctx.python("tools/build_icons.py", "--check")]


def _licenses_advice(ctx: Context, text: str) -> list[str]:
    """Si LIC-02 falla porque faltan ruedas o no coinciden (un clon o *worktree* nuevo),
    la orden exacta que las descarga (plan 001 §5.4.12)."""
    if f"[{wheels.RULE_COHERENCE}]" not in text or wheels.FETCH_HINT not in text:
        return []
    return [f"faltan ruedas o no coinciden: {wheels.fetch_command(ctx.install.python)}"]


def _manifest(ctx: Context) -> list[Run]:
    return [ctx.extension("validate", layout.EXTENSION_DIR)]


def _blender(ctx: Context) -> list[Run]:
    return ctx.blender_tests_parts("tests/blender", BLENDER_PARTS)


def domain_test_folders(root: Path) -> list[str]:
    """Las carpetas ``tests/unit/<paquete>`` de los paquetes de dominio
    (``imports.LEVELS``, en su orden) que existen (spec 004, RF-004-28)."""
    return [
        f"{DOMAIN_TESTS}/{name}"
        for name in imports.LEVELS
        if (Path(root) / DOMAIN_TESTS / name).is_dir()
    ]


def runtime_parts(ctx: Context) -> dict[str, int]:
    """En cuántas partes va cada carpeta de dominio en «motor». Sin medidas, las de
    siempre: hasta ``RUNTIME_PARTS`` cada una (:meth:`Context.parts_of`). Con las
    duraciones guardadas de los módulos de todas las que tienen más de uno (spec 006,
    T47; RNF-001-01), por su tiempo (``parts.share``): entre todas, como mucho
    ``RUNTIME_PROCESSES`` y nunca más que las de siempre; al menos dos cada una (con una,
    iría después de las demás) y una la que tiene un solo módulo. Un módulo sin medida
    (nuevo) cuenta lo que la media de los de su carpeta."""
    folders = domain_test_folders(ctx.root)
    always = {folder: ctx.parts_of(folder, UNITTEST_PATTERN, RUNTIME_PARTS) for folder in folders}
    if ctx.times is None:
        return always
    seconds: dict[str, list[float]] = {}
    limits: dict[str, int] = {}
    for folder in folders:
        modules = discovery.expected_modules(ctx.root / folder, UNITTEST_PATTERN, ctx.root)
        limit = part_count(RUNTIME_PROCESSES, len(modules))
        if limit == 1:
            continue
        stored = ctx.times.stored.get(times_key(TIMES_RUNTIME, folder, UNITTEST_PATTERN), {})
        measured = [stored[name] for name in modules if name in stored]
        if not measured:
            return always
        mean = sum(measured) / len(measured)
        seconds[folder] = [max(stored.get(name, mean), parts.MIN_SECONDS) for name in modules]
        limits[folder] = limit
    single = sum(count for folder, count in always.items() if folder not in seconds)
    budget = min(RUNTIME_PROCESSES, sum(always.values())) - single
    return {**always, **parts.share(seconds, limits, budget)}


def _runtime(ctx: Context) -> list[Run]:
    """Paso «motor» (spec 004, T30; RF-004-28, Silvestre REN-01; solo con ``--completo``,
    spec 004 0.4; solo, tras «blender», desde la tarea 011/T36): con el motor de cálculo
    de pruebas, ``tests/unit`` de cada paquete de dominio con su numpy (el mismo código,
    probado también con el numpy de Blender en «unitarias»), cada carpeta en las partes de
    :func:`runtime_parts`. Las carpetas en una sola parte van después de todas las partes:
    :func:`_launch_all` lanza a la vez solo las partes seguidas, y una orden sin partes
    entre dos carpetas con partes dejaría las de detrás para después (spec 005, T02:
    ``tests/unit/drillholes``, de un módulo, delante de ``tests/unit/interop``, de dos).
    Sin motor no hay órdenes: lo omite :func:`_runtime_omit`."""
    site = ctx.test_runtime().site
    if site is None:
        return []
    runs: list[Run] = []
    singles: list[Run] = []
    for folder, count in runtime_parts(ctx).items():
        if count == 1:
            singles.append(ctx.unittest(folder, site=site))
        else:
            runs.extend(
                ctx.unittest(folder, part=(i, count), site=site) for i in range(1, count + 1)
            )
    return runs + singles


def _runtime_omit(ctx: Context) -> str | None:
    """Sin motor de cálculo de pruebas, el motivo (con la orden ``tools/make_runtime.py``):
    el paso «motor» se omite por el recurso ``runtime`` (D-6 de la spec 004)."""
    found = ctx.test_runtime()
    return None if found.site is not None else found.reason


def _harness(ctx: Context) -> list[Run]:
    """Las pruebas del arnés que lanzan Blender entero (``--completo``); sin pruebas, o
    con un fichero sin cargar, el paso falla como «unitarias» (RF-001-06, RF-001-07)."""
    return [ctx.unittest(HARNESS_FOLDER)]


def _milestone(ctx: Context) -> list[Run]:
    """Paso «hito» (spec 015, T48; plan 015 §7.4; solo con ``--completo``): las pruebas de
    hito, ``milestone_*.py``, de ``tests/unit`` (``unittest``, como «unitarias») y de
    ``tests/blender`` (dentro de Blender, como «blender»), cada grupo en sus partes, todas a la
    vez. Sin pruebas, o con un fichero sin cargar, falla como «unitarias» (RF-001-06,
    RF-001-07)."""
    return [
        *ctx.unittest_parts(MILESTONE_UNIT_FOLDER, MILESTONE_UNIT_PARTS, pattern=MILESTONE_PATTERN),
        *ctx.blender_tests_parts(
            MILESTONE_BLENDER_FOLDER, MILESTONE_BLENDER_PARTS, pattern=MILESTONE_PATTERN
        ),
    ]


def _performance(ctx: Context) -> list[Run]:
    return [
        ctx.unittest("tests/rendimiento", pattern="test_*.py", empty=NO_TESTS),
        ctx.blender_tests("tests/rendimiento/blender", pattern="perf_*.py", empty=NO_TESTS),
    ]


def _bank(ctx: Context) -> list[Run]:
    return [ctx.python("tools/bench_silvestre.py", kind=KIND_BANK)]


def _docs_folder(ctx: Context) -> tuple[Path | None, str | None]:
    """La documentación que encuentra ``repo.find_docs`` desde la raíz del código, o el
    motivo por el que no la hay (no hay carpeta, o no existe o no lo es)."""
    found = repo.find_docs(ctx.root, ctx.docs_environ())
    if found is None:
        return None, NO_DOCS
    try:
        return repo.docs_root(found), None
    except repo.DocsProblem as exc:
        return None, str(exc)


def _docs(ctx: Context) -> list[Run]:
    folder, _reason = _docs_folder(ctx)
    return [] if folder is None else [ctx.python(DOCS_RELPATH, str(folder))]


def _docs_omit(ctx: Context) -> str | None:
    return _docs_folder(ctx)[1]


# Tabla de pasos (plan 001 §5.4.7). Las specs siguientes añaden el suyo en su lugar:
# «iconos» (003, T30) tras «licencias» y «motor» (004) tras «blender», a la vez que él
# (T30: después no cabe en RNF-001-01). Desde la spec 001 0.8 (tarea 009/T34; RNF-001-01),
# «referencia», «licencias» e «iconos» también van a la vez que «blender», tras «manifiesto»,
# con sus líneas en su lugar: con las pruebas de la 009, solos, uno tras otro, sumaban
# ≈ 2,7 s (la referencia, ≈ 2,4 s, con su caso de QGIS como suelo) a una comprobación de
# ≈ 42–43 s; a la vez que «blender», la comprobación tarda ≈ 2,2 s menos (009/T30), y
# «manifiesto» y «blender» juntos, con ellos, ≈ 20 s con el equipo cargado: lo que tardaban de
# «referencia» a «blender» en el código de partida. Desde la 0.10 (tarea 011/T30; RNF-001-01),
# también «unitarias»: con la 011, uno tras otro, la mediana en reposo era 44,4 s (≈ 25 s
# «unitarias» y ≈ 18 s «blender»); a la vez, 39,3 s. Los opcionales se ejecutan siempre
# después de los obligatorios (RF-001-10), en el orden de la tabla: los de --completo los
# primeros, tras «blender»: «motor» (spec 004 0.4, RF-004-28: con la CPU llena, la
# comprobación de cada tarea tardaba ≈ 42 s con él, frente a ≤ 40 s de RNF-001-01, hoy ≤ 48 s;
# spec 005, T50) y «arnés» (spec 001 0.6); «documentación» (spec 007, RF-007-14), el último.
# «motor» iba a la vez que «blender» (spec 004, T30) y, desde la tarea 011/T36, va solo,
# después de él: con «unitarias» también a la vez (0.10), corrían juntas 12 partes de
# «unitarias», 7 de «blender», 3 de «referencia» y hasta 16 de «motor» en 24 procesadores, y
# fallaban los plazos de tests/unit/jobs y workers (cancelar ≤ 2 s, colas, huérfanos) en las
# dos suites: --completo NO VERDE 6 de 6 en reposo (119–202 s). Solo, después: VERDE 3 de 3
# seguidas en reposo (128,7 / 125,4 / 123,4 s; «motor» 19–22 s, sin presupuesto: RNF-001-01)
# y la comprobación de cada tarea, igual (mediana 37,5 s frente a 37,4 / 38,1 s).
STEPS: tuple[Step, ...] = (
    Step("unitarias", _unit, alongside="blender"),
    Step("referencia", _reference, alongside="blender"),
    Step("licencias", _licenses, advice=_licenses_advice, alongside="blender"),
    Step("iconos", _icons, alongside="blender"),
    Step("manifiesto", _manifest),
    Step("blender", _blender),
    Step(
        RUNTIME_STEP,
        _runtime,
        option=OPTION_COMPLETE,
        omit=_runtime_omit,
        resource=RUNTIME_RESOURCE,
        empty=NO_CASES,
    ),
    Step(HARNESS_STEP, _harness, option=OPTION_COMPLETE),
    Step(MILESTONE_STEP, _milestone, option=OPTION_COMPLETE),
    Step("rendimiento", _performance, option=OPTION_PERFORMANCE,
         timeout_s=LONG_STEP_TIMEOUT_S),
    Step("banco", _bank, option=OPTION_BANK, timeout_s=LONG_STEP_TIMEOUT_S),
    Step(DOCS_STEP, _docs, option=OPTION_DOCS, omit=_docs_omit),
)


def parse_args(args: Sequence[str]) -> Options:
    """Lee las opciones; lanza :class:`UsageError` si alguna no existe."""
    show_help = False
    flags: set[str] = set()
    for arg in args:
        if arg in ("--ayuda", "-h", "--help"):
            show_help = True
        elif arg in OPTIONS:
            flags.add(arg)
        else:
            raise UsageError(f"opción desconocida «{arg}»")
    return Options(flags=frozenset(flags), show_help=show_help)


def select_steps(steps: Sequence[Step], flags: Collection[str]) -> list[Step]:
    """Los obligatorios en su orden y, después, los opcionales pedidos (RF-001-10)."""
    mandatory = [step for step in steps if step.option is None]
    optional = [step for step in steps if step.option is not None and step.option in flags]
    return mandatory + optional


def read_minimum(root: Path) -> tuple[int, int, int]:
    """``blender_version_min`` del manifiesto (con BOM se lee igual: lo señalan TXT-01,
    MAN-01 y el paso «manifiesto»)."""
    path = Path(root) / manifest.MANIFEST_RELPATH
    try:
        data = tomllib.loads(path.read_bytes().decode("utf-8-sig"))
        return manifest.blender_min(data)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        raise ManifestProblem(
            f"no se puede leer «blender_version_min» de «{manifest.MANIFEST_RELPATH}» "
            f"(MAN-01): {exc}. Corrija el manifiesto: hace falta para localizar Blender"
        ) from None


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _seconds(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def tests_ran(text: str) -> int | None:
    """Número de pruebas de la última línea «Ran N tests» (``None`` si no hay)."""
    found = _RAN.findall(text)
    return int(found[-1]) if found else None


def known_resources(root: Path) -> frozenset[str] | None:
    """La lista cerrada de recursos por los que se puede omitir una prueba:
    ``RESOURCES`` de ``tests/support/resources.py``, leída como texto (``ast``, sin
    importar ``tests``: HER-01). ``None`` si no se puede leer o no es una tupla de
    textos literales no vacíos (entonces ninguna omisión cuenta como omisión por un
    recurso). Si se asigna varias veces, vale la última."""
    path = Path(root) / RESOURCES_RELPATH
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (OSError, SyntaxError, ValueError):
        return None
    found: frozenset[str] | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == RESOURCES_NAME for t in targets):
            continue
        try:
            names = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            names = None
        valid = isinstance(names, tuple) and all(
            isinstance(name, str) and name.strip() for name in names
        )
        found = frozenset(names) if valid else None
    return found


def _unlisted(reason: str, resource: str, resources: Collection[str] | None) -> str:
    """El motivo de una omisión cuyo recurso no vale, con lo que falta."""
    where = f"{RESOURCES_NAME} de {RESOURCES_RELPATH}"
    if resources is None:
        return (
            f"{reason} (no se puede leer la lista cerrada de recursos, {where}: debe ser "
            "una tupla de textos literales)"
        )
    return (
        f"{reason} (el recurso «{resource}» no está en la lista cerrada de recursos, "
        f"{where}: {', '.join(sorted(resources)) or 'vacía'})"
    )


def parse_skips(text: str, resources: Collection[str] | None) -> list[Skip]:
    """Pruebas omitidas en la salida detallada de ``unittest`` (``-v``).

    Una omisión cuenta por su recurso solo si el motivo es ``[ENTORNO] <recurso>:
    <orden>`` y el recurso está en ``resources`` (la lista cerrada,
    :func:`known_resources`; ``None`` si no se pudo leer); si no, va a
    ``OTHER_SKIPS`` con el motivo y por qué no vale.

    Límite declarado (hallazgo F5 de la ronda 4; T63): una omisión por un recurso de la
    lista con una condición que no comprueba ese recurso (``@skipUnless(os.environ.get(
    "X"), skip_reason("symlink", …))``) cuenta como omisión por el recurso: la salida de
    ``unittest`` no dice por qué se omitió, y la regla TST-04 solo ve las condiciones
    constantes. Lo revisa la persona en la revisión del código: la condición debe ser la
    comprobación del recurso (``tests.support.resources.requires``)."""
    skips: list[Skip] = []
    head: re.Match[str] | None = None
    for line in text.splitlines():
        current = _TEST_HEAD.match(line)
        if current is not None:
            head = current
        match = _SKIPPED.search(line)
        if match is None:
            continue
        try:
            reason = str(ast.literal_eval(match.group("reason")))
        except (ValueError, SyntaxError):
            reason = match.group("reason")[1:-1]
        test = "?"
        if head is not None:
            name, where = head.group("name"), head.group("where")
            test = f"{where} ({name})" if name in _CLASS_FIXTURES else where
        resource, _sep, hint = reason[len(SKIP_PREFIX) :].strip().partition(":")
        resource = resource.strip()
        if not reason.startswith(SKIP_PREFIX) or not resource:
            skips.append(Skip(test, OTHER_SKIPS, reason))
        elif resources is None or resource not in resources:
            skips.append(Skip(test, OTHER_SKIPS, _unlisted(reason, resource, resources)))
        else:
            skips.append(Skip(test, resource, hint.strip()))
        head = None
    return skips


def parse_bank_omissions(text: str) -> list[Skip]:
    """Bancos omitidos por ``tools/bench_silvestre.py`` («OMITIDO: <banco>: <motivo>»)."""
    return [
        Skip(f"comparaciones de «{m.group('bank')}»", m.group("bank"), m.group("why"))
        for m in _OMITTED_BANK.finditer(text)
    ]


def parse_measurements(text: str) -> list[str]:
    """Líneas de medida «RNF-NNN-nn: …» que imprimen las pruebas de rendimiento.

    La primera línea del docstring de la prueba no cuenta, empiece por uno o por varios
    requisitos («RNF-001-01, RNF-007-01: …»; spec 005, T60): ``unittest -v`` la escribe en
    la línea siguiente a la cabecera de la prueba (``_DESCRIBED_HEAD``), seguida de « ... »
    al empezarla (lo que la prueba imprime después sí cuenta) y sola en el informe de un
    fallo. Una medida que empieza por varios RNF sale entera.
    """
    found: list[str] = []
    described = False  # la línea anterior es la cabecera de una prueba
    for line in text.splitlines():
        rest = line
        if described:
            # Sin « ... » (el informe de un fallo), toda la línea es el docstring.
            rest = line.partition(" ... ")[2]
        described = " ... " not in line and _DESCRIBED_HEAD.match(line) is not None
        for chunk in _MEASURE_START.split(rest):
            chunk = chunk.strip()
            if not chunk.startswith("RNF-") or chunk.endswith("...") or " ... " in chunk:
                continue
            found.append(chunk)
    return found


def _output_of(result: subprocess.CompletedProcess[str]) -> str:
    texts = [text.rstrip() for text in (result.stdout or "", result.stderr or "")]
    return "\n".join(text for text in texts if text)


def part_count(limit: int, modules: int, cpus: int | None = None) -> int:
    """En cuántas partes se ejecutan unas pruebas (T40): ``limit``, sin pasar de
    ``modules`` (ficheros de prueba en disco: así ninguna parte queda vacía) ni de los
    procesadores (``cpus``; si no se da, ``os.cpu_count()``, y uno si no se sabe); al
    menos una."""
    if cpus is None:
        cpus = os.cpu_count() or 1
    return max(1, min(limit, modules, cpus))


_Launched = subprocess.CompletedProcess[str] | _RunOutcome


def _launch(
    run: Run, root: Path, runner: blender.Runner, timeout_s: float = STEP_TIMEOUT_S
) -> _Launched:
    """Ejecuta la orden de ``run`` con el plazo ``timeout_s`` (el de su paso); si no se
    puede lanzar o no termina a tiempo, el fallo ya interpretado."""
    try:
        return runner(run.command, env=run.env, cwd=root, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        message = f"no terminó en {timeout_s:.0f} s: {' '.join(run.command)}"
        return _RunOutcome(STATUS_FAIL, None, "tiempo agotado", [], message, "")
    except OSError as exc:
        message = f"no se pudo ejecutar «{' '.join(run.command)}»: {exc}"
        return _RunOutcome(STATUS_FAIL, None, "no se pudo ejecutar", [], message, "")


def _launch_together(
    indices: Sequence[int],
    runs: Sequence[Run],
    root: Path,
    runner: blender.Runner,
    results: list[_Launched | None],
    timeout_s: float = STEP_TIMEOUT_S,
) -> None:
    """Ejecuta a la vez, cada una en su hilo, las órdenes ``runs[i]`` de ``indices``
    (las partes de unas pruebas), cada una con el plazo ``timeout_s``, y deja su resultado
    en ``results[i]``. Si la espera se interrumpe (Ctrl+C), como ``subprocess.run``: espera
    ``SIGINT_WAIT_S`` a que las órdenes terminen solas, para las que sigan
    (``blender.stop_all``), espera a los hilos y deja pasar la interrupción. Una excepción
    de una orden (que no sea de lanzarla o de tiempo, ya interpretadas) se lanza aquí, como
    sin hilos. Límite: una orden parada así no limpia lo suyo (la copia de la extensión de
    un Blender queda en ``%TEMP%``), igual que con una sola orden."""
    if len(indices) == 1:
        results[indices[0]] = _launch(runs[indices[0]], root, runner, timeout_s)
        return
    errors: dict[int, BaseException] = {}

    def work(index: int) -> None:
        try:
            results[index] = _launch(runs[index], root, runner, timeout_s)
        except BaseException as exc:  # noqa: BLE001 - se lanza en el hilo principal
            errors[index] = exc

    threads: list[threading.Thread] = []
    for index in indices:
        part = runs[index].part
        name = THREAD_PREFIX + (parts.label(*part) if part is not None else str(index))
        threads.append(threading.Thread(target=work, args=(index,), name=name, daemon=True))
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            while thread.is_alive():
                thread.join(JOIN_POLL_S)
    except BaseException:
        # Se espera a todos los hilos que llegaron a arrancar, también al que arrancaba
        # cuando llegó la interrupción (spec 004, T30).
        started = [thread for thread in threads if thread.ident is not None]
        try:
            # Como subprocess.run con Ctrl+C: un momento para que las órdenes, que
            # también lo reciben de la consola, terminen solas; después, se paran.
            deadline = time.monotonic() + SIGINT_WAIT_S
            for thread in started:
                thread.join(max(0.0, deadline - time.monotonic()))
        finally:
            blender.stop_all()
            for thread in started:
                thread.join(STOP_WAIT_S)
        raise
    for index in indices:
        if index in errors:
            raise errors[index]


def _launch_all(
    runs: Sequence[Run],
    root: Path,
    runner: blender.Runner,
    timeout_s: float = STEP_TIMEOUT_S,
) -> list[_Launched]:
    """Ejecuta las órdenes de un paso en su orden, una tras otra, salvo las partes
    seguidas de unas pruebas (``Run.part``), que van a la vez (T40); cada una, con el
    plazo del paso, ``timeout_s`` (tarea 009/T38)."""
    results: list[_Launched | None] = [None] * len(runs)
    batch: list[int] = []
    for index, run in enumerate(runs):
        if run.part is not None:
            batch.append(index)
            continue
        if batch:
            _launch_together(batch, runs, root, runner, results, timeout_s)
            batch = []
        results[index] = _launch(run, root, runner, timeout_s)
    if batch:
        _launch_together(batch, runs, root, runner, results, timeout_s)
    done: list[_Launched] = []
    for result in results:
        if result is None:  # no ocurre: _launch_together deja todos o lanza
            raise RuntimeError("una orden del paso quedó sin resultado")
        done.append(result)
    return done


def _interpret(
    run: Run,
    root: Path,
    result: _Launched,
    resources: Collection[str] | None,
    check_unloaded: bool = True,
) -> _RunOutcome:
    """El resultado de una orden. Con ``check_unloaded`` falso no se buscan los ficheros
    de prueba sin cargar: los de las partes de unas pruebas, en la salida de todas, los
    busca :func:`_interpret_all`."""
    if isinstance(result, _RunOutcome):
        return result
    output = _output_of(result)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    tests = tests_ran(text)
    if run.kind == KIND_BANK:
        skipped = parse_bank_omissions(text)
    elif run.kind in (KIND_UNITTEST, KIND_LAUNCHER):
        skipped = parse_skips(text, resources)
    else:
        skipped = []
    code = result.returncode
    empty = (run.kind == KIND_UNITTEST and code == UNITTEST_NO_TESTS) or (
        run.kind == KIND_LAUNCHER and code == 1 and launcher_found_no_tests(text)
    )
    if code == 0:
        status, detail = STATUS_OK, ""
    elif run.kind == KIND_BANK and code == BANK_OMITTED:
        status, detail = STATUS_SKIPPED, ""
    elif empty and run.empty is not None:
        status, detail = STATUS_OK, run.empty
    elif empty:
        status, detail = STATUS_FAIL, NO_TESTS
    else:
        status, detail = STATUS_FAIL, f"código {code}"
    problem = summary_problem(run, code, text) if status != STATUS_FAIL else None
    if problem is not None:
        status, detail = STATUS_FAIL, problem[0]
        output = f"{problem[1]}\n{output}"
    unloaded = unloaded_files(run, root, text) if check_unloaded else []
    if unloaded:
        detail, output = _with_unloaded(run, unloaded, status, detail, output)
        status = STATUS_FAIL
    unresourced = [skip for skip in skipped if skip.resource == OTHER_SKIPS]
    if unresourced:
        skipped = [skip for skip in skipped if skip.resource != OTHER_SKIPS]
        count = _plural(len(unresourced), "omisión sin recurso", "omisiones sin recurso")
        detail = count if status != STATUS_FAIL else f"{detail}, {count}"
        status = STATUS_FAIL
        listed = "\n".join(f"  {skip.test}: {skip.hint}" for skip in unresourced)
        output = (
            f"OMISIONES SIN RECURSO ({len(unresourced)}): una prueba omitida sin "
            f"«{SKIP_PREFIX} <recurso>: <orden>», o por un recurso que no está en la "
            f"lista cerrada ({RESOURCES_NAME} de {RESOURCES_RELPATH}), no se ejecuta y "
            "no es una omisión por un recurso opcional, sino una prueba escondida "
            "(RF-001-06). Si falta un recurso de la lista, omítala con "
            "tests.support.resources.requires (o skip_reason); si el recurso es nuevo, "
            "lo declara su spec en esa lista; si no, quite la omisión y arregle la "
            f"prueba.\n{listed}\n{output}"
        )
    if status == STATUS_FAIL:
        output = f"(código {code}) {' '.join(run.command)}\n{output}"
    return _RunOutcome(status, tests, detail, skipped, output, text)


def _with_unloaded(
    run: Run, unloaded: Sequence[str], status: str, detail: str, output: str
) -> tuple[str, str]:
    """El detalle y la salida de una orden con ficheros de prueba sin cargar
    (``unloaded``), con la pista de ``discovery.HINT``."""
    count = _plural(len(unloaded), "fichero sin cargar", "ficheros sin cargar")
    detail = count if status != STATUS_FAIL else f"{detail}, {count}"
    listed = "\n".join(f"  {rel}" for rel in unloaded)
    output = (
        f"FICHEROS DE PRUEBA SIN CARGAR ({len(unloaded)}) en «{run.folder}» con el "
        f"patrón «{run.pattern}»: unittest no los importó y sus pruebas no se "
        f"ejecutaron; {discovery.HINT}\n{listed}\n{output}"
    )
    return detail, output


def launcher_found_no_tests(text: str) -> bool:
    """Si el lanzador terminó porque no había pruebas: su línea «NO HAY PRUEBAS en …» al
    principio de una línea y, como última línea final, «FIN DEL LANZADOR: 0 pruebas,
    código 1». El texto suelto en otra parte (p. ej. en el error de una medición) no
    cuenta (convergencia de la spec 001, T57)."""
    if _LAUNCHER_NO_TESTS_LINE.search(text) is None:
        return False
    ends = discovery.LAUNCHER_END.findall(text)
    return bool(ends) and tuple(int(value) for value in ends[-1]) == (0, 1)


def summary_problem(run: Run, code: int, text: str) -> tuple[str, str] | None:
    """``(detalle, explicación)`` si una orden de pruebas que dice haber terminado bien
    (código 0, o 5 «sin pruebas» de ``unittest``) no llega al resumen de ``unittest`` y,
    en el lanzador, a su línea final con el mismo número de pruebas y código 0. Un
    proceso que sale a mitad (``os._exit(0)``) no deja ni lo uno ni lo otro. Un «OK
    (expected failures=n)» tampoco vale: una prueba roja marcada con ``expectedFailure``
    no es verde (convergencia de la spec 001, T59).

    Límite declarado (hallazgo F4 de la ronda 4; T63): una prueba que imprime ella misma
    un resumen falso («Ran N tests» y «OK» y, en el lanzador, la línea final con el mismo
    número) y sale con ``os._exit(0)`` no se distingue de una ejecución que terminó bien:
    aquí solo se ven la salida y el código. No es un descuido sino una imitación
    deliberada; la ve la persona en la revisión del código."""
    if run.kind not in (KIND_UNITTEST, KIND_LAUNCHER):
        return None
    if code == 0:
        verdict, expected = _OK_LINE, "OK"
    elif run.kind == KIND_UNITTEST and code == UNITTEST_NO_TESTS:
        verdict, expected = _NO_TESTS_LINE, "NO TESTS RAN"
    else:
        return None
    ran = list(_RAN.finditer(text))
    if not ran:
        return (
            SUMMARY_MISSING,
            "la salida no llega al resumen de unittest («Ran N tests»): el proceso "
            "terminó antes que unittest (p. ej. con os._exit) y no se sabe qué pruebas "
            "pasaron",
        )
    after = text[ran[-1].end() :].splitlines()[1:]
    following = next((line.strip() for line in after if line.strip()), "")
    if not verdict.match(following):
        return (
            SUMMARY_MISSING,
            f"tras «Ran N tests», unittest no dice «{expected}» sino «{following}»",
        )
    if discovery.EXPECTED_FAILURES_MARK in following:
        return (
            EXPECTED_FAILURES,
            f"unittest dice «{following}»: {discovery.EXPECTED_FAILURES_HINT}",
        )
    if run.kind != KIND_LAUNCHER:
        return None
    count = int(ran[-1].group(1))
    ends = discovery.LAUNCHER_END.findall(text)
    if not ends:
        return (
            LAUNCHER_END_MISSING,
            "falta la línea final del lanzador "
            f"(«{discovery.launcher_end_line(count, 0)}»): Blender terminó antes que el "
            "lanzador",
        )
    end_count, end_code = (int(value) for value in ends[-1])
    if (end_count, end_code) != (count, 0):
        return (
            LAUNCHER_END_MISSING,
            f"la línea final del lanzador dice {end_count} pruebas y "
            f"código {end_code}, y unittest, {count} pruebas; Blender salió con {code}",
        )
    return None


def _test_files(run: Run, root: Path) -> dict[str, str]:
    """``{módulo: fichero}`` de las pruebas de ``run.folder`` en disco (vacío si la orden
    no es de pruebas). Los módulos son relativos a la raíz o, si la carpeta está fuera
    de ella, a la propia carpeta (como en el lanzador)."""
    if run.folder is None or run.pattern is None:
        return {}
    folder = Path(root) / run.folder
    inside = folder.resolve().is_relative_to(Path(root).resolve())
    top = Path(root) if inside else folder
    return discovery.expected_modules(folder, run.pattern, top)


def unloaded_files(run: Run, root: Path, text: str) -> list[str]:
    """Ficheros de prueba de ``run.folder`` en disco cuyo módulo no nombra la salida de
    ``unittest -v`` (vacío si la orden no es de pruebas)."""
    return discovery.missing_modules(_test_files(run, root), discovery.loaded_in_output(text))


def _suite_of(run: Run) -> tuple[str | None, str | None]:
    return run.folder, run.pattern


def _interpret_all(
    runs: Sequence[Run],
    launched: Sequence[_Launched],
    root: Path,
    resources: Collection[str] | None,
) -> list[_RunOutcome]:
    """El resultado de cada orden de un paso. Las partes de unas pruebas (T40) buscan
    los ficheros sin cargar en la salida de todas (no, si alguna no se pudo ejecutar) y
    tienen que haber repartido igual (:func:`different_distribution`): si no, el
    diagnóstico es «reparto incompleto», también para los ficheros que por eso no cargó
    ninguna, aunque falle otra cosa (T45); si sí, los ficheros sin cargar llevan la
    pista de siempre, y una parte sin su línea «PARTE …» es «reparto incompleto» solo
    si ninguna parte falló (su fallo ya lo explica)."""
    outcomes = [
        _interpret(run, root, result, resources, check_unloaded=run.part is None)
        for run, result in zip(runs, launched)
    ]
    for key in dict.fromkeys(_suite_of(run) for run in runs if run.part is not None):
        group = [
            index
            for index, run in enumerate(runs)
            if run.part is not None and _suite_of(run) == key
        ]
        if any(isinstance(launched[i], _RunOutcome) for i in group):
            continue  # alguna no se pudo ejecutar: su fallo lo explica
        group_runs = [runs[i] for i in group]
        texts = [outcomes[i].text for i in group]
        first = outcomes[group[0]]
        unloaded = unloaded_files(group_runs[0], root, "\n".join(texts))
        failed = any(outcomes[i].status == STATUS_FAIL for i in group)
        problem = different_distribution(group_runs, texts, root)
        if problem is None and not unloaded and not failed:
            found, unit = parts.part_lines(texts)
            problem = parts.consistency(found, len(group), unit=unit)
        if problem is not None:
            first.detail = f"{first.detail}, {PARTS_PROBLEM}" if first.detail else PARTS_PROBLEM
            first.status = STATUS_FAIL
            explanation = parts_message(group_runs, texts, problem, unloaded)
            first.output = f"{explanation}\n{first.output}".rstrip()
        elif unloaded:
            first.detail, first.output = _with_unloaded(
                group_runs[0], unloaded, first.status, first.detail, first.output
            )
            first.status = STATUS_FAIL
    return outcomes


def repeated_files(run: Run, root: Path, texts: Sequence[str]) -> dict[str, list[int]]:
    """``{fichero: [partes]}`` de los ficheros de prueba de ``run.folder`` que nombra la
    salida de más de una parte (``texts``, una por parte, en su orden): el reparto es
    por fichero entero, así que cada uno se ejecuta en una sola (T45)."""
    names = [discovery.loaded_in_output(text) for text in texts]
    found: dict[str, list[int]] = {}
    for module, rel in _test_files(run, root).items():
        where = [n for n, loaded in enumerate(names, start=1)
                 if discovery.is_loaded(module, loaded)]
        if len(where) > 1:
            found[rel] = where
    return dict(sorted(found.items()))


def different_distribution(runs: Sequence[Run], texts: Sequence[str], root: Path) -> str | None:
    """Por qué las partes de unas pruebas (``runs`` y su salida, en su orden) no
    repartieron igual, o ``None``: todas dicen su línea «PARTE i de n: r de T pruebas»
    (o, por ficheros, «PARTE i de n: m de M módulos»; spec 006, T48) y no cuadran
    (``gbtools.parts.consistency``), o un mismo fichero se ejecutó en más de una
    (:func:`repeated_files`). Cada parte calcula el reparto por su cuenta: si no
    descubren lo mismo, un fichero puede quedar sin ejecutar en ninguna (T45)."""
    found, unit = parts.part_lines(texts)
    if all(info is not None for info in found):
        problem = parts.consistency(found, len(runs), unit=unit)
        if problem is not None:
            return problem
    repeated = repeated_files(runs[0], root, texts)
    if repeated:
        listed = "; ".join(
            f"{rel}, en las partes {', '.join(str(n) for n in numbers[:-1])} y {numbers[-1]}"
            for rel, numbers in repeated.items()
        )
        return f"un mismo fichero se ejecutó en más de una parte ({listed})"
    return None


def parts_message(
    runs: Sequence[Run], texts: Sequence[str], problem: str, unloaded: Sequence[str] = ()
) -> str:
    """La explicación de un reparto que no cuadra (``problem``), con la línea y la orden
    de cada parte y, si los hay, los ficheros que por eso no cargó ninguna (T45)."""
    found, unit = parts.part_lines(texts)
    listed = "\n".join(
        f"  {parts.describe(info, unit) if info is not None else '(sin línea)'}: "
        f"{' '.join(run.command)}"
        for run, info in zip(runs, found)
    )
    message = (
        f"REPARTO INCOMPLETO en «{runs[0].folder}» ({len(runs)} partes): {problem}. Cada "
        "prueba se ejecuta en una sola parte y todas las partes descubren las mismas "
        "(gbtools.parts): si no cuadran, alguna prueba no se ejecutó o se ejecutó dos "
        f"veces.\n{listed}"
    )
    if unloaded:
        which = _plural(len(unloaded), "fichero", "ficheros")
        files = "\n".join(f"  {rel}" for rel in unloaded)
        message += (
            f"\nPor eso ninguna parte ejecutó {which} de «{runs[0].folder}» con el "
            f"patrón «{runs[0].pattern}»:\n{files}"
        )
    return message


def _partial(runs: Sequence[Run], outcomes: Sequence[_RunOutcome]) -> str:
    """« en k de n partes» si alguna parte de unas pruebas no dijo cuántas ejecutó (sin
    el resumen de ``unittest``): el número del paso es solo el de las demás (T45); si
    no, ""."""
    parted = [outcome for run, outcome in zip(runs, outcomes) if run.part is not None]
    counted = sum(1 for outcome in parted if outcome.tests is not None)
    return f" en {counted} de {len(parted)} partes" if counted < len(parted) else ""


def execute_step(step: Step, ctx: Context, runner: blender.Runner) -> StepResult:
    """Ejecuta las órdenes de ``step`` y reúne su resultado; si ``step.omit`` da un
    motivo, no ejecuta nada y el paso queda «omitido» con él."""
    start = time.perf_counter()
    reason = step.omit(ctx) if step.omit is not None else None
    if reason is not None:
        return StepResult(
            step.name,
            STATUS_SKIPPED,
            time.perf_counter() - start,
            detail=[reason],
            skipped=[Skip(f"el paso «{step.name}»", step.resource or step.name, reason)],
        )
    resources = known_resources(ctx.root)
    runs = list(step.runs(ctx))
    if not runs and step.empty is not None:
        return StepResult(
            step.name, STATUS_OK, time.perf_counter() - start, detail=[step.empty]
        )
    launched = _launch_all(runs, ctx.root, runner, step.timeout_s)
    outcomes = _interpret_all(runs, launched, ctx.root, resources)
    seconds = time.perf_counter() - start
    if any(outcome.status == STATUS_FAIL for outcome in outcomes):
        status = STATUS_FAIL
    elif outcomes and all(outcome.status == STATUS_SKIPPED for outcome in outcomes):
        status = STATUS_SKIPPED
    else:
        status = STATUS_OK
    counts = [outcome.tests for outcome in outcomes if outcome.tests]
    tests = sum(counts) if counts else None
    detail: list[str] = []
    if tests:
        detail.append(_plural(tests, "prueba", "pruebas") + _partial(runs, outcomes))
    for outcome in outcomes:
        if outcome.detail and outcome.detail not in detail:
            if outcome.status == STATUS_OK and tests:
                continue  # «sin casos» de una parte cuando otra sí tiene pruebas
            detail.append(outcome.detail)
    skipped = [skip for outcome in outcomes for skip in outcome.skipped]
    if skipped:
        detail.append(_plural(len(skipped), "omitida", "omitidas"))
    output = "\n".join(o.output for o in outcomes if o.status == STATUS_FAIL)
    measurements = [m for outcome in outcomes for m in parse_measurements(outcome.text)]
    advice: list[str] = []
    if status == STATUS_FAIL and step.advice is not None:
        advice = step.advice(ctx, "\n".join(outcome.text for outcome in outcomes))
    return StepResult(
        step.name, status, seconds, tests, detail, skipped, output, measurements, advice
    )


def execute_together(
    step: Step, partners: Sequence[Step], ctx: Context, runner: blender.Runner
) -> tuple[StepResult, list[StepResult]]:
    """Ejecuta ``step`` en este hilo y, a la vez, cada paso de ``partners`` en el suyo
    (``Step.alongside``; spec 004, T30; spec 001 0.8), y devuelve sus resultados cuando han
    terminado todos. Cada paso mide su propia duración, y el fallo de uno no para a los
    demás. Si llega Ctrl+C, para todas las órdenes en marcha (``blender.stop_all``), también
    las que un paso compañero lance después (:func:`_stop_threads`), espera a los hilos y
    deja pasar la interrupción; una excepción de un paso compañero se lanza aquí."""
    found: dict[int, StepResult] = {}
    errors: list[BaseException] = []

    def work(index: int, partner: Step) -> None:
        try:
            found[index] = execute_step(partner, ctx, runner)
        except BaseException as exc:  # noqa: BLE001 - se lanza en el hilo principal
            errors.append(exc)

    threads = [
        threading.Thread(target=work, args=(index, partner),
                         name=THREAD_PREFIX + partner.name, daemon=True)
        for index, partner in enumerate(partners)
    ]
    try:
        for thread in threads:
            thread.start()
        result = execute_step(step, ctx, runner)
        for thread in threads:
            while thread.is_alive():
                thread.join(JOIN_POLL_S)
    except BaseException:
        _stop_threads([thread for thread in threads if thread.ident is not None])
        raise
    if errors:
        raise errors[0]
    return result, [found[index] for index in range(len(partners))]


def _stop_threads(threads: Sequence[threading.Thread]) -> None:
    """Tras Ctrl+C, para las órdenes en marcha (``blender.stop_all``) hasta que terminan los
    hilos de ``threads``, ``STOP_WAIT_S`` como mucho: un paso compañero que aún preparaba
    sus órdenes, o que pasa a la siguiente, las lanza después de la primera parada, y
    también se paran (spec 001 0.8, tarea 009/T34)."""
    deadline = time.monotonic() + STOP_WAIT_S
    blender.stop_all()
    for thread in threads:
        while thread.is_alive() and time.monotonic() < deadline:
            thread.join(JOIN_POLL_S)
            blender.stop_all()


def run_steps(
    selected: Sequence[Step], ctx: Context, runner: blender.Runner
) -> Iterator[StepResult]:
    """Los resultados de los pasos ``selected``, en su orden (el de la tabla: RF-001-06).
    Se ejecutan uno tras otro, salvo los que van a la vez que otro (``Step.alongside``),
    que se ejecutan con él cuando le toca a él, aunque estén antes en la tabla (spec 001
    0.8 y 0.10: «unitarias», «referencia», «licencias» e «iconos», con «blender», tras
    «manifiesto»); un
    paso solo va a la vez que otro que se ejecuta y va solo, y si no, va solo, en su lugar.
    Cada resultado sale cuando han salido los de los pasos anteriores: el de un paso que
    va con otro posterior, y los que hay entre ellos, cuando ha terminado ese otro."""
    names = {step.name for step in selected}
    alone = {step.name for step in selected if step.alongside not in names}
    leads = [step.alongside if step.alongside in alone else None for step in selected]
    ready: dict[int, StepResult] = {}
    following = 0
    for index, step in enumerate(selected):
        if leads[index] is not None:
            continue
        partners = [i for i, lead in enumerate(leads) if lead == step.name]
        if partners:
            result, others = execute_together(step, [selected[i] for i in partners], ctx,
                                              runner)
            ready.update(zip(partners, others))
        else:
            result = execute_step(step, ctx, runner)
        ready[index] = result
        while following in ready:
            yield ready.pop(following)
            following += 1


def format_step(result: StepResult) -> str:
    """Línea del resumen: ``  correcto  unitarias     8,9 s  (190 pruebas)``."""
    line = f"  {result.status:<8}  {result.name:<12} {_seconds(result.seconds):>5} s"
    if result.detail:
        line += f"  ({', '.join(result.detail)})"
    return line


def _omissions(results: Sequence[StepResult]) -> list[str]:
    groups: dict[tuple[str, str], list[str]] = {}
    for result in results:
        for skip in result.skipped:
            groups.setdefault((skip.resource, skip.hint), []).append(
                f"{skip.test} [{result.name}]"
            )
    total = sum(len(tests) for tests in groups.values())
    lines = [f"\nOmisiones ({total}), por recurso y con la orden que lo instala:"]
    for (resource, hint), tests in groups.items():
        lines.append(f"  {resource} ({len(tests)}){': ' + hint if hint else ''}")
        lines.extend(f"      {test}" for test in tests)
    return lines


def _verdict(results: Sequence[StepResult], seconds: float) -> str:
    failed = [result.name for result in results if result.status == STATUS_FAIL]
    omitted = sum(len(result.skipped) for result in results)
    total = f"({_seconds(seconds)} s)"
    if failed:
        names = ", ".join(f"«{name}»" for name in failed)
        verb = "falla" if len(failed) == 1 else "fallan"
        return f"RESULTADO: NO VERDE {total}: {verb} {names}"
    if omitted:
        return f"RESULTADO: VERDE CON OMISIONES ({omitted}) {total}"
    return f"RESULTADO: VERDE {total}"


def repository_result(
    root: Path, before: repo.Snapshot, seconds: float
) -> StepResult | None:
    """Fallo «repositorio» si, tras el último paso, el repositorio (rutas, tamaños y
    ``mtime_ns``, ignorados incluidos y sin ``.git/``) no es el de antes del primero:
    las pruebas y las herramientas solo escriben en carpetas temporales (spec 001 §11;
    RF-001-09). ``None`` si no cambió nada. Límite declarado (hallazgo F8 de la ronda 4;
    T63): un fichero que se modifica y se restaura con los mismos bytes y la misma fecha
    no se ve (``gbtools.repo.snapshot``)."""
    start = time.perf_counter()
    changes = repo.snapshot_changes(before, repo.snapshot(root, REPOSITORY_SKIP))
    seconds += time.perf_counter() - start
    if not changes:
        return None
    count = _plural(len(changes), "cambio", "cambios")
    listed = "\n".join(f"  {change}" for change in changes)
    output = (
        f"REPOSITORIO MODIFICADO durante la comprobación ({count}): las pruebas y las "
        "herramientas solo escriben en carpetas temporales (spec 001 §11; RF-001-09). "
        "Lo que dejó el paso o la prueba que lo hizo sigue en el árbol: búsquelo, "
        "corríjalo y bórrelo; si solo cambió la fecha de una carpeta, algo se creó y "
        f"se borró en ella (convergencia, T51).\n{listed}"
    )
    return StepResult(REPOSITORY, STATUS_FAIL, seconds, detail=[count], output=output)


def _remove_tree(folder: Path, attempts: int = 5) -> None:
    """Borra ``folder`` con algunos reintentos (Windows puede retener un fichero)."""
    for attempt in range(attempts):
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.2 * (attempt + 1))


def not_complete_note(steps: Sequence[Step], flags: Collection[str]) -> str | None:
    """La línea del resumen, antes de ``RESULTADO``, si la tabla tiene pasos de
    ``--completo`` y no se pidió: esas pruebas («arnés» y «motor») no se han ejecutado y la
    publicación las pide siempre (RF-001-06, spec 001 0.6 y 0.7; RF-004-28). No es una
    omisión por un recurso: el resultado no cambia."""
    if OPTION_COMPLETE in flags or not any(s.option == OPTION_COMPLETE for s in steps):
        return None
    return NOT_COMPLETE


def correct_command(python: Path | str) -> str:
    """La orden correcta, en PowerShell, desde la raíz del repositorio."""
    return f'& "{python}" tools/check.py'


def _scripts_dir(install: BlenderInstall) -> Path:
    major, minor, _patch = install.version
    return install.exe.parent / f"{major}.{minor}" / "scripts"


def _print_wait(holder: check_lock.Holder | None) -> None:
    print(check_lock.wait_message(holder), flush=True)


def take_lock(
    lock_file: Callable[[Mapping[str, str]], Path | None],
    environ: Mapping[str, str],
    root: Path,
) -> check_lock.CheckLock | None:
    """Toma el cerrojo del equipo (spec 006, T46; RNF-001-01, RNF-007-01): el fichero de
    ``lock_file(environ)`` (``None``: sin cerrojo), con la carpeta ``root``; si otro
    ``check.py`` lo tiene, escribe a quién espera y espera. Si este desciende del que lo
    tiene (``GEOBLENDER_CHECK_LOCK_HELD`` de ``environ``), sigue con el suyo. Si no se puede
    usar, un aviso y ``None``: la comprobación sigue sin él."""
    try:
        path = lock_file(environ)
        if path is None:
            return None
        lock = check_lock.CheckLock(path, root)
        lock.acquire(inherited=environ.get(check_lock.ENV_HELD), on_wait=_print_wait)
    except check_lock.LockProblem as exc:
        print(f"AVISO: {exc}; la comprobación sigue sin el cerrojo del equipo (otro "
              "tools/check.py a la vez la estorbaría)", flush=True)
        return None
    return lock


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    runner: blender.Runner = blender.run,
    locate: Callable[[tuple[int, int, int]], BlenderInstall] = blender.locate_blender,
    executable: str | None = None,
    loaded_modules: Collection[str] | None = None,
    steps: Sequence[Step] = STEPS,
    environ: Mapping[str, str] | None = None,
    find_runtime: Callable[[Path, Mapping[str, str]], TestRuntime] = find_test_runtime,
    times_store: Callable[[Path], Path | None] = default_times_store,
    lock_file: Callable[[Mapping[str, str]], Path | None] = check_lock.lock_path,
    test_copy: Callable[[Path, Path], Path] | None = ext_copy.prepare,
    bytecode: Callable[[Path], Path | None] = pyc_cache.default_folder,
    refresh_bytecode: Callable[[Path, Path, Sequence[Path]], object] = pyc_cache.prepare,
) -> int:
    """Ejecuta la comprobación completa y devuelve el código de salida.

    Los parámetros con nombre solo los cambian las pruebas: raíz, ejecutor de órdenes,
    localizador de Blender, intérprete en uso, módulos cargados, tabla de pasos, el
    entorno en que se buscan la documentación (``GEOBLENDER_DOCS_DIR``) y el motor de
    cálculo de pruebas (``GEOBLENDER_TEST_RUNTIME_SITE``; por defecto, el del proceso),
    cómo se busca ese motor (``make_runtime.find_test_runtime``) y dónde está el almacén
    de tiempos de la raíz (:func:`default_times_store`; ``None``: sin almacén, las
    partes por número de pruebas y sin medir) y dónde está el cerrojo del equipo según
    ese entorno (:func:`gbtools.check_lock.lock_path`; ``None``: sin cerrojo y sin
    esperar a nadie; spec 006, T46) y cómo se prepara la copia de pruebas de la extensión
    que comparten las partes de «blender» (``gbtools.ext_copy.prepare``; ``None``: cada
    parte hace la suya; spec 006, T48), dónde va el código compilado de las órdenes de
    Python de la raíz (``gbtools.pyc_cache.default_folder``; ``None``: sin carpeta, las
    órdenes de siempre) y cómo se refresca (``gbtools.pyc_cache.prepare``; spec 005, T44).
    """
    started = time.perf_counter()
    executable = sys.executable if executable is None else executable
    modules = sys.modules if loaded_modules is None else loaded_modules
    if "bpy" in modules:
        print(
            "ERROR DE ENTORNO: tools/check.py no se ejecuta dentro de Blender: lance la "
            "comprobación con el Python de Blender desde la raíz del repositorio: "
            f"{correct_command(executable)}",
            file=sys.stderr,
        )
        return 2
    try:
        options = parse_args(list(sys.argv[1:] if argv is None else argv))
    except UsageError as exc:
        print(f"Error: {exc}\n\n{USAGE}", file=sys.stderr)
        return 2
    if options.show_help:
        print(__doc__)
        print(USAGE)
        return 0
    if root is None:
        try:
            root = repo_root(Path(__file__))
        except FileNotFoundError as exc:
            print(f"ERROR DE ENTORNO: {exc}", file=sys.stderr)
            return 2
    try:
        minimum = read_minimum(root)
    except ManifestProblem as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"RESULTADO: NO VERDE ({_seconds(time.perf_counter() - started)} s)")
        return 1
    try:
        install = locate(minimum)
    except EnvironmentProblem as exc:
        print(f"ERROR DE ENTORNO: {exc}", file=sys.stderr)
        return 2
    if not blender.is_blender_python(install, executable):
        print(
            f"ERROR DE ENTORNO: tools/check.py se ejecuta con el Python de Blender "
            f"{'.'.join(map(str, install.version))} («{install.python}»), no con "
            f"«{executable}». Desde la raíz del repositorio: "
            f"{correct_command(install.python)}",
            file=sys.stderr,
        )
        return 2

    version = ".".join(str(part) for part in install.version)
    selected = select_steps(steps, options.flags)
    extras = " ".join(option for option in OPTIONS if option in options.flags)
    print(
        f"Geoblender · comprobación completa · Blender {version} ({install.exe})"
        + (f" · {extras}" if extras else "")
    )
    lock = take_lock(lock_file, os.environ if environ is None else environ, root)
    # El tiempo que se informa, y que se compara con RNF-001-01, empieza al tomar el
    # cerrojo: no cuenta la espera a otro check.py (spec 006, T46).
    started = time.perf_counter()
    try:
        work = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
        results: list[StepResult] = []
        shared: SharedCopy | None = None
        refreshing: BytecodeRefresh | None = None
        try:
            if test_copy is not None and any(s.runs is _blender for s in selected):
                shared = SharedCopy(test_copy, root, work / COPY_FOLDER)
            profile = work / PROFILE_FOLDER
            profile.mkdir()
            store = times_store(root)
            times = None if store is None else PartTimes.load(store, work / TIMES_WORK_FOLDER)
            ctx = Context(
                root=root,
                install=install,
                profile=profile,
                blender_modules=imports.installation_modules(_scripts_dir(install)),
                environ=environ,
                find_runtime=find_runtime,
                times=times,
                lock_owner=None if lock is None else lock.owner,
                shared_copy=shared,
                bytecode=bytecode(root),
            )
            if ctx.bytecode is not None:
                # La carpeta site del motor, solo si se ejecuta «motor» (--completo; spec
                # 005, T50): sin él, ni se busca el motor ni se repasa lo compilado de su numpy.
                engine = any(step.runs is _runtime for step in selected)
                site = ctx.test_runtime().site if engine else None
                refreshing = BytecodeRefresh(refresh_bytecode, ctx.bytecode, root,
                                             [] if site is None else [site])
            # Los perfiles de las demás partes de las pruebas de Blender (T40).
            for number in range(2, BLENDER_PARTS + 1):
                ctx.part_profile(number).mkdir()
            # Foto del repositorio antes del primer paso, para compararla tras el último.
            snapshot_start = time.perf_counter()
            before = repo.snapshot(root, REPOSITORY_SKIP)
            snapshot_seconds = time.perf_counter() - snapshot_start
            for result in run_steps(selected, ctx, runner):
                results.append(result)
                print(format_step(result), flush=True)
                for line in (*result.measurements, *result.advice):
                    print(f"            {line}", flush=True)
            modified = repository_result(root, before, snapshot_seconds)
            if modified is not None:
                results.append(modified)
                print(format_step(modified), flush=True)
            if times is not None:
                try:
                    times.save()
                except OSError as exc:
                    print(f"AVISO: no se pudieron guardar las duraciones de las pruebas en "
                          f"«{times.store}»: {exc}")
        finally:
            if refreshing is not None:
                warning = refreshing.wait()
                if warning is not None:
                    print(warning, flush=True)
            if shared is not None:
                shared.result()  # que termine antes de borrar su carpeta
            try:
                _remove_tree(work)
            except OSError as exc:
                print(f"AVISO: no se pudo borrar la carpeta temporal «{work}»: {exc}")

        if any(result.skipped for result in results):
            print("\n".join(_omissions(results)))
        for result in results:
            if result.status == STATUS_FAIL:
                print(f"\n--- Salida del paso «{result.name}» ---")
                print(result.output)
                print(f"--- Fin de la salida del paso «{result.name}» ---")
        note = not_complete_note(steps, options.flags)
        if note is not None:
            print(note)
        print(_verdict(results, time.perf_counter() - started))
        return 1 if any(result.status == STATUS_FAIL for result in results) else 0
    finally:
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(_stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    sys.exit(main())
