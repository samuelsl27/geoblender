# SPDX-License-Identifier: GPL-3.0-or-later
"""Ayudantes de las pruebas que se ejecutan dentro de Blender (plan 001 §5.2 y §5.3).

Solo se importan dentro de Blender, desde ``tests/blender/`` y
``tests/rendimiento/blender/``: ``tools/run_blender_tests.py`` copia la extensión a una
carpeta temporal, la registra como repositorio de pruebas y deja en ``ENV_MODULE`` el
nombre con el que Blender la importa (``bl_ext.gb_tests.geoblender``).

La huella del estado de Blender (RF-001-05) reúne lo que la extensión puede cambiar al
registrarse y que la API pública permite enumerar: tipos de ``bpy.types`` y clases
registradas (``dir(bpy.types)`` no lista los ``PropertyGroup``), las propiedades de
**todos** los tipos de ``bpy.types`` con ``bl_rna`` (no solo los principales: una que
quedara en ``Curve`` o en ``Material`` también es un rastro), manejadores de
``bpy.app.handlers``, atajos del mapa de complementos, ``draw_left`` de la barra
superior y las funciones de dibujo de **todos** los menús, cabeceras y paneles (las
añadidas con ``append``/``prepend``, como el importador de las specs 005 y 006 en
``TOPBAR_MT_file_import``, y una ``draw`` sustituida) (convergencia de la spec 001,
T49).

Los temporizadores y las traducciones no se pueden enumerar con la API pública, así que
el lanzador los sigue durante la sesión (convergencia de la spec 001, T50; la regla de
``geoblender/AGENTS.md``: ``unregister()`` deshace los temporizadores y las
traducciones): :func:`track_registrations` envuelve ``bpy.app.timers.register`` para
anotar cada función que se registra, y la huella lista las anotadas que siguen
registradas (``timers``); y la huella lista los módulos de la copia de la extensión
(:data:`EXTENSION_MODULES`, que deja el lanzador) que tienen traducciones registradas
(``translations``): ``bpy.app.translations.register`` falla si el nombre ya tiene
datos, así que se prueba con una sonda que se retira enseguida.

Lo mismo con lo que usarán la interfaz (spec 003) y los sondeos (spec 005), que tampoco
se puede enumerar (convergencia, T62): :func:`track_registrations` envuelve también
``draw_handler_add``/``draw_handler_remove`` de ``bpy.types.Space`` (los heredan
``SpaceView3D`` y los demás editores) y ``draw_cursor_add``/``draw_cursor_remove`` de
``WindowManager`` (``draw_handlers``), ``bpy.utils.previews.new`` y
``ImagePreviewCollection.close``, que es lo que llama ``remove`` (``previews``), y
``bpy.msgbus.subscribe_rna`` y ``clear_by_owner`` (``msgbus``); la huella lista lo
registrado durante la sesión que sigue vivo. Y vuelca lo que sí se puede leer: las
propiedades de ``preferences.view``, ``.system``, ``.inputs``, ``.edit`` y
``.filepaths`` (``preferences``, con un nivel de punteros y las colecciones por su
número de elementos), los módulos de ``preferences.addons`` (``addons``) y las claves de
``bpy.app.driver_namespace`` (``driver_namespace``). Límite: una suscripción de msgbus
que Blender borra al abrir otro ``.blend`` (sin ``PERSISTENT``) se seguiría viendo; una
prueba que abre ficheros la quita con ``clear_by_owner``.

La referencia es la huella del principio de la sesión de pruebas
(:func:`session_baseline`), que el lanzador toma tras registrar el repositorio de
pruebas y antes de cualquier prueba, y con la que compara también al terminar: una
huella tomada a mitad de sesión, después de que otra prueba habilitara la extensión,
incluiría una fuga que se repite igual en cada habilitación (convergencia de la spec
001, T36).

Las funciones de la huella (``draw_left``, los manejadores y las funciones añadidas al
menú de la barra superior) se comparan por el objeto, no solo por ``módulo.nombre``
(:class:`CallableRef`): ``functools.wraps`` copia ``__module__`` y ``__qualname__``, y
una envoltura que no se deshizo al deshabilitar tendría el mismo nombre que la original
(convergencia de la spec 001, T40).

La instantánea de la interfaz (:func:`ui_snapshot`, spec 003, T01) añade a la huella los
espacios de trabajo del fichero y el de cada ventana, y :data:`UI_DRAW_TARGETS` nombra
las cabeceras y los menús de Blender que amplía la 003. Vive aquí y no en un
``tests/blender/support/state_snapshot.py`` (como dice la T01): TST-02 no admite en una
carpeta de pruebas un ``.py`` que no case con su patrón, y ARQ-01 solo deja importar
``bpy`` en ``tests/support/`` a este módulo.
"""

from __future__ import annotations

import contextlib
import functools
import importlib
import os
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import addon_utils
import bpy

ENV_MODULE = "GEOBLENDER_TEST_EXTENSION"

# Huella del principio de la sesión de pruebas: la deja tools/run_blender_tests.py.
SESSION_BASELINE: dict[str, object] | None = None

# Módulos de la copia de la extensión (el raíz y sus submódulos), para buscar sus
# traducciones registradas: los deja tools/run_blender_tests.py (extension_modules).
EXTENSION_MODULES: tuple[str, ...] = ()

# Lo que se registra desde track_registrations() y la API no deja enumerar: funciones de
# bpy.app.timers.register (T50), y manejadores de dibujo, colecciones de previews y
# suscripciones de msgbus (T62), con lo sustituido para deshacerlo (_PATCHES).
_TIMERS: list[object] = []
_DRAW_HANDLERS: list[CallableRef] = []  # objetivo: el manejador que devuelve Blender
_PREVIEWS: list[CallableRef] = []  # objetivo: la colección
_SUBSCRIPTIONS: list[tuple[object, CallableRef]] = []  # (dueño, función que avisa)
_PATCHES: list[tuple[object, str, object]] = []  # (objeto, atributo, valor original)
_TRANSLATION_PROBE = {"es_ES": {("*", "geoblender: sonda de la huella"): "sonda"}}
# Grupos de las preferencias que se vuelcan en la huella (T62).
PREFERENCE_GROUPS: tuple[str, ...] = ("view", "system", "inputs", "edit", "filepaths")
# Lo que Blender deduce de la GPU que ha detectado, no algo guardado que pueda cambiar la
# extensión: en ``blender -b`` sin GPU iniciada, ``system.gpu_preferred_device`` vale «AUTO»
# (la única opción) y, tras ``gpu.init()`` (la prueba de la superposición de las curvas
# maestras, spec 006, T55), la GPU detectada («OPENGL»), sin que cambie la preferencia.
DETECTED_PREFERENCES: frozenset[str] = frozenset({"system.gpu_preferred_device"})


def module_name() -> str:
    """Nombre con el que Blender importa la copia de pruebas (p. ej.
    ``"bl_ext.gb_tests.geoblender"``)."""
    name = os.environ.get(ENV_MODULE, "")
    if not name:
        raise RuntimeError(
            f"Falta la variable {ENV_MODULE}: estas pruebas se ejecutan dentro de Blender "
            "con tools/run_blender_tests.py, que instala la copia de pruebas"
        )
    return name


def _collect(errors: list[BaseException]) -> Callable[[BaseException], None]:
    return errors.append


def enable() -> ModuleType:
    """Habilita la extensión como lo hace Blender y devuelve su módulo raíz.

    Lanza ``RuntimeError`` (con la causa) si Blender informa de algún error.
    """
    name = module_name()
    errors: list[BaseException] = []
    module = addon_utils.enable(name, default_set=True, handle_error=_collect(errors))
    if errors or module is None:
        raise RuntimeError(f"No se pudo habilitar «{name}»") from (
            errors[0] if errors else None
        )
    return module


def disable() -> None:
    """Deshabilita la extensión; lanza ``RuntimeError`` si Blender informa de un error."""
    name = module_name()
    errors: list[BaseException] = []
    addon_utils.disable(name, default_set=True, handle_error=_collect(errors))
    if errors:
        raise RuntimeError(f"Error al deshabilitar «{name}»") from errors[0]


def is_enabled() -> bool:
    """Verdadero si la extensión está habilitada en esta sesión.

    Lee la marca ``__addon_enabled__`` que pone ``addon_utils`` (lo mismo que
    ``addon_utils.check``, sin su aviso cuando el módulo solo se ha importado).
    """
    module = sys.modules.get(module_name())
    return getattr(module, "__addon_enabled__", False) is True


def loaded_modules() -> list[str]:
    """Módulos de la extensión presentes en ``sys.modules``."""
    name = module_name()
    return sorted(key for key in sys.modules if key == name or key.startswith(name + "."))


def unload() -> None:
    """Deshabilita la extensión si lo está y la quita de ``sys.modules``: la siguiente
    importación o habilitación parte de cero."""
    if is_enabled():
        disable()
    for key in loaded_modules():
        del sys.modules[key]


def release() -> None:
    """Deshabilita la extensión si lo está y deja sus módulos en ``sys.modules`` (spec 006,
    T48; RNF-001-01): la siguiente :func:`enable` la registra otra vez sobre los mismos
    módulos, como al desactivarla y activarla en las preferencias, sin importarla de nuevo.

    Es lo que usan las clases que solo necesitan la extensión habilitada (operadores,
    paneles, trabajos…), al empezar y al terminar: habilitarla tras :func:`unload` importa
    otra vez ``core``, ``gis``, ``bl``… y lee el catálogo (unos 0,26 s cada vez, y con unas
    170 habilitaciones, más de la mitad del paso «blender» de ``tools/check.py``); tras
    ``release``, unos 0,03 s. Las que prueban el registro, la huella o lo que carga la
    importación parten de cero con :func:`fresh` (spec 006, T59), que al terminar devuelve
    estos módulos; :func:`unload` los quita del todo. Deshabilitada, Blender queda
    como al principio de la sesión (``unregister()`` deshace todo lo que hizo
    ``register()``; lo comprueba la huella del lanzador al terminar)."""
    if is_enabled():
        disable()


@contextlib.contextmanager
def fresh() -> Iterator[None]:
    """La extensión de cero mientras dura (spec 006, T59; RNF-001-01), para las clases que
    prueban el registro, la huella o lo que carga la importación: al entrar la deshabilita
    si lo está y aparta de ``sys.modules`` sus módulos (los que comparten las clases que
    usan :func:`release`), así que habilitarla o importarla la importa otra vez; al salir,
    pase lo que pase, la deshabilita, quita lo importado dentro (:func:`unload`) y devuelve
    los módulos apartados, sin importarlos de nuevo (también el que cuelga del paquete del
    repositorio de pruebas, que la importación de dentro sustituyó). Con :func:`unload` al
    terminar, la clase siguiente que solo la habilita tenía que importarla entera (≈ 0,3 s
    en reposo y hasta 0,8 s con el equipo cargado, unas diez veces por comprobación)."""
    if is_enabled():
        disable()
    kept = {name: sys.modules.pop(name) for name in loaded_modules()}
    try:
        yield
    finally:
        try:
            unload()
        finally:
            sys.modules.update(kept)
            root = module_name()
            parent, _, child = root.rpartition(".")
            if root in kept and parent in sys.modules:
                setattr(sys.modules[parent], child, kept[root])


def import_root() -> ModuleType:
    """Importa la extensión **sin** habilitarla (como hace Blender al listarla)."""
    return importlib.import_module(module_name())


def _callable_name(function: object) -> str:
    module = getattr(function, "__module__", None)
    name = getattr(function, "__qualname__", None) or getattr(function, "__name__", None)
    return f"{module}.{name}" if name else repr(function)


@dataclass(frozen=True, eq=False, repr=False)
class CallableRef:
    """Una función de la huella: su nombre (``módulo.nombre``) y el objeto mismo.

    Dos son iguales solo si son el mismo objeto (``is``): ``functools.wraps`` copia el
    módulo y el nombre, así que el nombre solo no distingue una envoltura de la
    original. La huella guarda el objeto, no su ``id()``: mientras viva la huella, su
    dirección no la puede reutilizar otro objeto.
    """

    name: str
    target: object

    @classmethod
    def of(cls, function: object) -> CallableRef:
        return cls(_callable_name(function), function)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CallableRef):
            return NotImplemented
        return self.target is other.target and self.name == other.name

    def __hash__(self) -> int:
        return hash((self.name, id(self.target)))

    def __str__(self) -> str:
        return f"{self.name} (objeto {id(self.target):#x})"

    __repr__ = __str__


def _type_properties() -> dict[str, list[str]]:
    """Las propiedades de cada tipo de ``bpy.types`` con ``bl_rna`` (unos 4 000 tipos en
    Blender 5.2.1, en unos 30 ms)."""
    properties: dict[str, list[str]] = {}
    for name in dir(bpy.types):
        rna = getattr(getattr(bpy.types, name, None), "bl_rna", None)
        if rna is not None:
            properties[name] = sorted(rna.properties.keys())
    return properties


def _draw_functions() -> dict[str, list[CallableRef]]:
    """Las funciones que dibujan cada menú, cabecera y panel de ``bpy.types``.

    Tras el primer ``append`` o ``prepend``, Blender sustituye ``draw`` por una función
    que llama a las de ``draw._draw_funcs`` (la original y las añadidas, en orden), y la
    deja así aunque luego se quite todo lo añadido. Por eso cuenta la lista
    ``_draw_funcs`` si existe y, si no, ``[draw]``: antes del primer ``append`` y después
    de quitar lo añadido es la misma, con la misma ``draw`` original."""
    kinds = (bpy.types.Menu, bpy.types.Header, bpy.types.Panel)
    drawers: dict[str, list[CallableRef]] = {}
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        if not isinstance(cls, type) or not issubclass(cls, kinds):
            continue
        draw = getattr(cls, "draw", None)
        if draw is None:
            continue
        functions = getattr(draw, "_draw_funcs", None)
        drawers[name] = [CallableRef.of(f) for f in (functions if functions else [draw])]
    return drawers


def _keymap_item(item: bpy.types.KeyMapItem) -> str:
    return repr(
        (
            item.idname,
            item.map_type,
            item.type,
            item.value,
            item.any,
            item.shift,
            item.ctrl,
            item.alt,
            item.oskey,
            item.key_modifier,
            item.active,
        )
    )


def _registered_classes() -> list[str]:
    """Clases de Python registradas en Blender (``módulo.nombre``).

    ``dir(bpy.types)`` no lista los ``PropertyGroup`` registrados (sí operadores,
    paneles y menús): se recorren las subclases de ``bpy_struct`` con
    ``is_registered``.
    """
    names: list[str] = []
    seen: set[type] = set()
    pending: list[type] = [bpy.types.bpy_struct]
    while pending:
        for subclass in pending.pop().__subclasses__():
            if subclass in seen:
                continue
            seen.add(subclass)
            pending.append(subclass)
            if "bl_rna" in subclass.__dict__ and getattr(subclass, "is_registered", False):
                names.append(_callable_name(subclass))
    return sorted(names)


def extension_modules(folder: Path, name: str) -> tuple[str, ...]:
    """Nombres de módulo de la copia de la extensión en ``folder`` importada como
    ``name`` (``bl_ext.gb_tests.geoblender``, ``….bl``, ``….bl.props``…)."""
    found = {name}
    for path in folder.rglob("*.py"):
        parts = list(path.relative_to(folder).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        found.add(".".join([name, *parts]))
    return tuple(sorted(found))


def _patch(owner: object, name: str, replacement: object) -> None:
    """Sustituye el atributo ``name`` del módulo o la clase ``owner`` y anota el valor
    original (el de su ``__dict__``) para :func:`untrack_registrations`."""
    original = vars(owner)[name]
    setattr(owner, name, replacement)
    _PATCHES.append((owner, name, original))


def _track_timers() -> None:
    """Anota cada función que se registra con ``bpy.app.timers.register`` (T50)."""
    original = bpy.app.timers.register

    @functools.wraps(original)
    def register(function: Callable[[], float | None], *args: Any, **kwargs: Any) -> Any:
        if not any(known is function for known in _TIMERS):
            _TIMERS.append(function)
        return original(function, *args, **kwargs)

    _patch(bpy.app.timers, "register", register)


def _track_handler_pair(owner: type, add: str, remove: str) -> None:
    """Anota los manejadores de dibujo que se añaden con el método de clase ``add`` de
    ``owner`` (y de sus subclases) y olvida los que se quitan con ``remove`` (T62)."""
    add_original = vars(owner)[add]
    remove_original = vars(owner)[remove]

    def added(cls: type, *args: Any, **kwargs: Any) -> object:
        handle = add_original.__get__(None, cls)(*args, **kwargs)
        function = args[0] if args else kwargs.get("callback")
        where = f"{cls.__name__}.{add} → {_callable_name(function)}"
        _DRAW_HANDLERS.append(CallableRef(where, handle))
        return handle

    def removed(cls: type, handle: object, *args: Any, **kwargs: Any) -> object:
        result = remove_original.__get__(None, cls)(handle, *args, **kwargs)
        _DRAW_HANDLERS[:] = [ref for ref in _DRAW_HANDLERS if ref.target is not handle]
        return result

    _patch(owner, add, classmethod(added))
    _patch(owner, remove, classmethod(removed))


def _track_previews() -> None:
    """Anota las colecciones de ``bpy.utils.previews.new`` y olvida las que se cierran
    (``remove`` llama a ``ImagePreviewCollection.close``) (T62)."""
    previews = importlib.import_module("bpy.utils.previews")
    original_new = previews.new
    collection_type = previews.ImagePreviewCollection
    original_close = vars(collection_type)["close"]

    @functools.wraps(original_new)
    def new(*args: Any, **kwargs: Any) -> object:
        collection = original_new(*args, **kwargs)
        creator = sys._getframe(1).f_globals.get("__name__", "?")
        _PREVIEWS.append(CallableRef(f"bpy.utils.previews.new desde {creator}", collection))
        return collection

    @functools.wraps(original_close)
    def close(self: object, *args: Any, **kwargs: Any) -> object:
        result = original_close(self, *args, **kwargs)
        _PREVIEWS[:] = [ref for ref in _PREVIEWS if ref.target is not self]
        return result

    _patch(previews, "new", new)
    _patch(collection_type, "close", close)


def _track_msgbus() -> None:
    """Anota las suscripciones de ``bpy.msgbus.subscribe_rna`` con su dueño y olvida las
    de un dueño que pasa por ``clear_by_owner`` (T62)."""
    msgbus = bpy.msgbus
    original_subscribe = msgbus.subscribe_rna
    original_clear = msgbus.clear_by_owner

    @functools.wraps(original_subscribe)
    def subscribe_rna(*args: Any, **kwargs: Any) -> object:
        result = original_subscribe(*args, **kwargs)
        owner = kwargs.get("owner", args[1] if len(args) > 1 else None)
        notify = kwargs.get("notify", args[3] if len(args) > 3 else None)
        where = f"bpy.msgbus.subscribe_rna → {_callable_name(notify)}"
        _SUBSCRIPTIONS.append((owner, CallableRef(where, notify)))
        return result

    @functools.wraps(original_clear)
    def clear_by_owner(owner: object) -> object:
        result = original_clear(owner)
        _SUBSCRIPTIONS[:] = [entry for entry in _SUBSCRIPTIONS if entry[0] is not owner]
        return result

    _patch(msgbus, "subscribe_rna", subscribe_rna)
    _patch(msgbus, "clear_by_owner", clear_by_owner)


def track_registrations() -> None:
    """Envuelve las funciones de registro que la API no deja enumerar para anotar lo que
    se registre desde ahora: temporizadores (T50), manejadores de dibujo de los editores
    y del cursor, colecciones de previews y suscripciones de msgbus (T62). Lo llama el
    lanzador antes de la huella de referencia; si ya están envueltas, no hace nada."""
    if _PATCHES:
        return
    _track_timers()
    _track_handler_pair(bpy.types.Space, "draw_handler_add", "draw_handler_remove")
    _track_handler_pair(bpy.types.WindowManager, "draw_cursor_add", "draw_cursor_remove")
    _track_previews()
    _track_msgbus()


def untrack_registrations() -> None:
    """Deshace :func:`track_registrations` (en orden inverso) y olvida lo anotado."""
    while _PATCHES:
        owner, name, original = _PATCHES.pop()
        setattr(owner, name, original)
    _TIMERS.clear()
    _DRAW_HANDLERS.clear()
    _PREVIEWS.clear()
    _SUBSCRIPTIONS.clear()


def _from_extension(function: object) -> bool:
    """Verdadero si ``function`` es de la copia de pruebas de la extensión."""
    module = str(getattr(function, "__module__", "") or "")
    name = os.environ.get(ENV_MODULE, "")
    return bool(name) and (module == name or module.startswith(name + "."))


def load_file(filepath: str | os.PathLike[str] | None = None) -> None:
    """Abre ``filepath`` (sin él, la escena de fábrica, sin tocar las preferencias ni los
    complementos) y olvida las suscripciones de msgbus que los complementos de **Blender**
    hacen al cargar un fichero (spec 002, T22).

    Al cargar, ``copy_global_transform`` y ``pose_library`` vuelven a suscribirse desde su
    ``load_post``: no son un rastro de la extensión, pero el seguimiento de
    :func:`track_registrations` las vería como nuevas. Las de la extensión se conservan:
    una que no se quite sigue siendo un rastro."""
    with loading():
        if filepath is None:
            bpy.ops.wm.read_homefile(use_factory_startup=True)
        else:
            bpy.ops.wm.open_mainfile(filepath=os.fspath(filepath))


@contextlib.contextmanager
def loading() -> Iterator[None]:
    """Para abrir un fichero con otra orden de Blender (``wm.recover_last_session``,
    ``wm.recover_auto_save``; spec 010, T12): al salir del bloque, olvida como
    :func:`load_file` las suscripciones de msgbus que hicieron dentro los complementos de
    **Blender** (las de la extensión se conservan)."""
    before = list(_SUBSCRIPTIONS)
    try:
        yield
    finally:
        _SUBSCRIPTIONS[:] = [
            entry
            for entry in _SUBSCRIPTIONS
            if any(entry is old for old in before) or _from_extension(entry[1].target)
        ]


def registered_timers() -> list[CallableRef]:
    """Las funciones anotadas por :func:`track_registrations` que siguen registradas (en
    ``blender -b`` los temporizadores no se ejecutan: uno que no se quita, sigue)."""
    return [
        CallableRef.of(function)
        for function in _TIMERS
        if bpy.app.timers.is_registered(function)
    ]


def registered_translations(names: Iterable[str]) -> list[str]:
    """Los nombres de ``names`` con traducciones registradas en Blender.

    ``bpy.app.translations.register`` lanza ``ValueError`` si el nombre ya tiene datos
    (también vacíos); si no, la sonda se registra y se retira enseguida."""
    found: list[str] = []
    for name in sorted(set(names)):
        try:
            bpy.app.translations.register(name, _TRANSLATION_PROBE)
        except ValueError:
            found.append(name)
        else:
            bpy.app.translations.unregister(name)
    return found


def _plain_value(value: object) -> object:
    """Un valor de una propiedad que se puede comparar e imprimir: los conjuntos (de
    los enumerados de varios valores) ordenados y las listas de RNA como tuplas."""
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, set | frozenset):
        return tuple(sorted(value))
    try:
        return tuple(value)  # type: ignore[call-overload]
    except TypeError:
        return repr(value)


def _rna_values(struct: object, prefix: str, values: dict[str, object], depth: int) -> None:
    """Las propiedades de ``struct`` en ``values`` («grupo.propiedad»): los punteros a
    estructuras que no son datos (``ID``), ``depth`` niveles más; las colecciones, por su
    número de elementos."""
    for prop in struct.bl_rna.properties:  # type: ignore[attr-defined]
        key = prop.identifier
        if key == "rna_type":
            continue
        name = f"{prefix}.{key}"
        try:
            value = getattr(struct, key)
        except (AttributeError, RuntimeError, ValueError):
            continue
        if prop.type == "POINTER":
            if depth > 0 and value is not None and not isinstance(value, bpy.types.ID):
                _rna_values(value, name, values, depth - 1)
        elif prop.type == "COLLECTION":
            values[name] = len(value)
        else:
            values[name] = _plain_value(value)


def _preferences() -> dict[str, object]:
    """Las preferencias de :data:`PREFERENCE_GROUPS` (unas 260, en menos de 1 ms), salvo
    las que Blender deduce de la GPU (:data:`DETECTED_PREFERENCES`): una extensión que
    cambia una y no la devuelve deja rastro (T62)."""
    values: dict[str, object] = {}
    preferences = bpy.context.preferences
    for group in PREFERENCE_GROUPS:
        _rna_values(getattr(preferences, group), group, values, depth=1)
    for key in DETECTED_PREFERENCES:
        values.pop(key, None)
    return values


def state_fingerprint() -> dict[str, object]:
    """Huella del estado de Blender que la extensión puede cambiar (RF-001-05)."""
    # Primero lo que recorre todos los tipos de bpy.types: Blender crea la clase de
    # Python de cada tipo la primera vez que se pide, y las clases registradas se
    # enumeran después, ya con todas creadas (si no, la segunda huella tendría más).
    properties = _type_properties()
    draw_funcs = _draw_functions()
    handlers: dict[str, list[CallableRef]] = {}
    for name in dir(bpy.app.handlers):
        value = getattr(bpy.app.handlers, name)
        if isinstance(value, list):
            handlers[name] = [CallableRef.of(function) for function in value]
    keymaps: dict[str, list[str]] | None = None
    addon_keyconfig = bpy.context.window_manager.keyconfigs.addon
    if addon_keyconfig is not None:
        keymaps = {
            f"{keymap.name}|{keymap.space_type}|{keymap.region_type}": [
                _keymap_item(item) for item in keymap.keymap_items
            ]
            for keymap in addon_keyconfig.keymaps
        }
    return {
        "types": sorted(dir(bpy.types)),
        "registered_classes": _registered_classes(),
        "properties": properties,
        "handlers": handlers,
        "addon_keymaps": keymaps,
        # Sin draw_left (la prueba del respaldo de compatibilidad, spec 003, T13), None.
        "topbar_draw_left": CallableRef.of(
            getattr(bpy.types.TOPBAR_HT_upper_bar, "draw_left", None)
        ),
        "draw_funcs": draw_funcs,
        "timers": registered_timers(),
        "translations": registered_translations(EXTENSION_MODULES),
        # Convergencia, T62.
        "draw_handlers": list(_DRAW_HANDLERS),
        "previews": list(_PREVIEWS),
        "msgbus": [ref for _owner, ref in _SUBSCRIPTIONS],
        "preferences": _preferences(),
        "addons": sorted(addon.module for addon in bpy.context.preferences.addons),
        "driver_namespace": sorted(bpy.app.driver_namespace),
    }


# Cabeceras y menús de Blender que la interfaz (spec 003) sustituye o amplía (CW §4; PC §1;
# AR §6): la instantánea de la interfaz comprueba que existen en la versión instalada.
UI_DRAW_TARGETS: tuple[str, ...] = (
    "TOPBAR_HT_upper_bar",
    "TOPBAR_MT_editor_menus",
    "VIEW3D_MT_editor_menus",
    "VIEW3D_HT_tool_header",
    "STATUSBAR_HT_header",
    "VIEW3D_MT_object_context_menu",
    "VIEW3D_MT_edit_curve_context_menu",
    "OUTLINER_MT_object",
    "OUTLINER_MT_collection",
)


def ui_snapshot() -> dict[str, object]:
    """Instantánea de lo que toca la interfaz (spec 003, T01; RF-003-23, CE-003-02): la
    huella de :func:`state_fingerprint` (``draw_left``, las funciones de dibujo de todas
    las cabeceras y menús, el mapa de complementos, las clases, las propiedades, los
    manejadores y los temporizadores) más los espacios de trabajo del fichero y el de
    cada ventana, por nombre (el estado de sesión del conmutador no se guarda, CW §3.1).
    Se compara con :func:`fingerprint_diff`."""
    snapshot = state_fingerprint()
    snapshot["workspaces"] = sorted(workspace.name for workspace in bpy.data.workspaces)
    snapshot["window_workspaces"] = [
        window.workspace.name if window.workspace else None
        for window in bpy.context.window_manager.windows
    ]
    return snapshot


def session_baseline() -> dict[str, object]:
    """Huella del principio de la sesión de pruebas, antes de que ninguna prueba
    habilitara la extensión (la toma ``tools/run_blender_tests.py``)."""
    if SESSION_BASELINE is None:
        raise RuntimeError(
            "No hay huella del principio de la sesión: estas pruebas se ejecutan dentro "
            "de Blender con tools/run_blender_tests.py, que la toma antes de la primera"
        )
    return SESSION_BASELINE


_SAME_NAME = "mismo nombre y otro objeto: ¿una envoltura (functools.wraps) sin deshacer?"


def _list_change(old: list[object], new: list[object]) -> str:
    added = sorted(set(map(str, new)) - set(map(str, old)))
    removed = sorted(set(map(str, old)) - set(map(str, new)))
    if not added and not removed:
        return "mismos elementos en otro orden o repetidos"
    # La pista de la envoltura, solo si se quitó una función y se añadió otra con su
    # nombre; no si solo se añadió una (una fuga repetida; convergencia, T55).
    added_names = {
        item.name for item in new if isinstance(item, CallableRef) and str(item) in added
    }
    removed_names = {
        item.name for item in old if isinstance(item, CallableRef) and str(item) in removed
    }
    if added_names & removed_names:
        return f"añadidos {added}, quitados {removed} ({_SAME_NAME})"
    return f"añadidos {added}, quitados {removed}"


def _value_change(old: object, new: object) -> str:
    if (
        isinstance(old, CallableRef)
        and isinstance(new, CallableRef)
        and old.name == new.name
    ):
        moved = f"{id(old.target):#x} → {id(new.target):#x}"
        return f"{old.name}: {_SAME_NAME} ({moved})"
    return f"{old!r} → {new!r}"


def fingerprint_diff(before: dict[str, object], after: dict[str, object]) -> list[str]:
    """Claves de la huella que cambian, con lo que sobra y lo que falta (también en las
    listas de un diccionario, como las propiedades de cada tipo), para los mensajes."""
    lines: list[str] = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        if isinstance(old, list) and isinstance(new, list):
            lines.append(f"{key}: {_list_change(old, new)}")
        elif isinstance(old, dict) and isinstance(new, dict):
            for sub in sorted(set(old) | set(new)):
                old_sub, new_sub = old.get(sub), new.get(sub)
                if old_sub == new_sub:
                    continue
                # Una clave que aparece o desaparece (p. ej. el tipo de un operador
                # registrado), como una lista vacía: se nombra lo que tiene.
                if isinstance(old_sub, list | None) and isinstance(new_sub, list | None):
                    change = _list_change(old_sub or [], new_sub or [])
                    lines.append(f"{key}[{sub}]: {change}")
                else:
                    lines.append(f"{key}[{sub}]: {_value_change(old_sub, new_sub)}")
        else:
            lines.append(f"{key}: {_value_change(old, new)}")
    return lines
