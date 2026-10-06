# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos del catálogo de comandos y su validación (spec 003; RF-003-06, RF-003-07,
RF-003-18; plan 003 §5.2 y §5.3; BS §7.1).

Un **comando** es una orden del usuario con su identificador definitivo: un operador
(``geoblender.<módulo>_<acción>``, con propiedades fijas si las lleva:
``geoblender.ui_set_view?view=PLAN``), un menú o un panel (su clase), un comando nativo
de Blender (``view3d.view_all``, ``TOPBAR_MT_help``) o una propiedad nativa
(``tool_settings.use_snap``). Se define **una sola vez**, en su casa (un menú de la barra o
un submenú; los paneles, los nativos del acceso rápido y los auxiliares internos no
tienen casa), y todos los demás sitios lo referencian: accesos cruzados ↗, espejos,
acceso rápido, menús circulares y contextuales, atajos.

Los textos tienen ``msgid`` en inglés (que es la versión inglesa) y su traducción al
español al lado (ADR-0012 §4; plan 003 DT1).

:func:`validate` devuelve las incidencias de un catálogo con el fichero, la clave, el
campo y el valor que las causan. Las expresiones de los nombres de ADR-0011
(:data:`CLASS_RE`, :data:`IDNAME_RE`) son copia de las de ``tools/gbtools/rules/naming.py``
(NOM-01 y NOM-02, que no ven las clases creadas con ``type()``); una prueba comprueba que
las dos copias son iguales. Puro: no importa ``bpy`` (ADR-0004).
"""

from __future__ import annotations

import re
import string
from collections.abc import Mapping
from dataclasses import dataclass, field

# Códigos de módulo (docs/sdd/convenciones.md §5) y nombres de ADR-0011: copia de
# tools/gbtools/rules/naming.py.
MODULE_CODES: tuple[str, ...] = (
    "core",
    "ui",
    "jobs",
    "gis",
    "dh",
    "geo",
    "imp",
    "bm",
    "opt",
    "des",
    "res",
    "plan",
    "io",
)
_CODES = "|".join(MODULE_CODES)
CLASS_RE = re.compile(rf"^GEOBLENDER_(OT|PT|MT|PG|UL)_({_CODES})_[a-z0-9_]+$")
IDNAME_RE = re.compile(rf"^geoblender\.({_CODES})_[a-z0-9_]+$")

KINDS: tuple[str, ...] = ("operator", "menu", "panel", "native", "internal", "property")
ACTIONS: tuple[str, ...] = ("A", "D", "P", "H", "S", "T")  # README §6
BRANCHES: tuple[str, ...] = ("common", "geology", "design", "convergence", "transversal")
KEYMAPS: tuple[str, ...] = ("Window", "3D View")
SCOPES: tuple[str, ...] = ("project", "view")
DISPLAYS: tuple[str, ...] = (
    "icon",  # botón de icono
    "icon_text",  # icono con texto o número (Refrescar · n)
    "menu",  # desplegable de icono
    "menu_text",  # desplegable con texto (Banda «±5 | 10 m»)
    "popover",  # ventana emergente de icono
    "popover_text",  # ventana emergente con texto (Versión activa, Objeto actual)
    "switch",  # el conmutador [GB|B]
    "toggle_menu",  # conmutador nativo + desplegable (Encaje)
)
PIE_SLOTS: tuple[str, ...] = ("W", "E", "S", "N", "NW", "NE", "SW", "SE")  # orden de Blender
CONTEXT_KINDS: tuple[str, ...] = (
    "DRILLHOLES", "SECTION", "SURFACE", "POINTS", "POLYLINE", "CONSTRAINT", "SOLID",
    "BLOCK_MODEL", "DESIGN", "DESIGN_ENTITY", "PHASE", "VERSION", "DRAWING", "SELECTION",
)
ENTRY_RE = re.compile(r"^(\d{3}|R-\d{2}|Blender)$")
OWN_ICON_RE = re.compile(r"^gb_(logo|menu|branch|qat|state|kind|type)(_[a-z0-9]+)*$")
NATIVE_ICON_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")

PropValue = str | int | bool


@dataclass(frozen=True)
class Command:
    """Una orden del usuario con su definición única (plan 003 §5.2)."""

    key: str  # bl_idname o clase, más «?prop=valor&…» si fija propiedades
    idname: str  # la clave sin propiedades
    kind: str  # KINDS
    props: tuple[tuple[str, PropValue], ...]
    label: str  # msgid (inglés)
    label_es: str
    description: str  # msgid (inglés)
    description_es: str
    module: str  # código de ADR-0011; "" en lo nativo
    entry: str  # "002", "R-38", "Blender"; "" en un submenú sin entrada propia
    action: str  # ACTIONS
    background: bool  # se ejecuta como trabajo en segundo plano (·2p)
    frequency: int  # 0 ○, 1 ●, 2 ●●, 3 ●●●
    icon: str | None  # icono propio (II §1.4)
    icon_fallback: str  # icono nativo de reserva ("NONE" si no lleva)
    aliases: tuple[str, ...]  # alias de la línea de comandos (F10)
    jargon: tuple[tuple[str, str], ...]  # (programa, término)
    home: str  # menú donde se define; "" sin casa
    home_group: str  # msgid del grupo de su casa ("" si no tiene)
    order: int  # orden de definición en el catálogo
    source: str  # fichero de datos (ruta relativa con «/»)
    dynamic: bool = False  # menú cuyo contenido se calcula al dibujarlo
    doc_id: tuple[str, ...] = ()  # identificadores con que lo lista BS §8, si son otros


@dataclass(frozen=True)
class MenuItem:
    """Un elemento de un menú: un comando (su definición, un acceso cruzado ↗ o un
    espejo), un separador o, en los menús contextuales, una etiqueta de algo que aún no
    es un comando (una propiedad del tipo, con su entrada)."""

    key: str | None = None
    cross: bool = False  # ↗: el comando tiene su casa en otro menú
    separator: bool = False
    placeholder: tuple[str, str] | None = None  # (msgid, español)
    entry: str = ""  # entrada del marcador


@dataclass(frozen=True)
class Group:
    """Un grupo de un menú: un rótulo gris (``msgid``; "" sin rótulo) y sus elementos."""

    label: str
    label_es: str
    items: tuple[MenuItem, ...]


@dataclass(frozen=True)
class MenuSpec:
    """El contenido de un menú (los 13 de la barra, sus submenús y los espejos)."""

    id: str
    groups: tuple[Group, ...]
    parent: str  # el menú donde está su casa ("" en los de la barra)
    stage: str = ""  # msgid de la etapa («Paso n de 11 · <etapa>»)
    stage_es: str = ""
    step: int | None = None
    branch: str = ""
    source: str = ""


@dataclass(frozen=True)
class QuickAccessItem:
    """Un control de acceso rápido (AR §2 y §3.1)."""

    key: str
    scope: str  # "project" (barra superior) o "view" (fila 2 de cada Vista 3D)
    group: str
    order: int
    display: str  # DISPLAYS
    extra: str | None = None  # el segundo comando del control (el ▾ de Encaje…)
    compact_step: int | None = None  # paso del plegado que lo deja en solo icono (1)
    fold_step: int | None = None  # paso que lo lleva a «»» (2–5); None: nunca
    edit_modes: bool = False  # se queda en los modos de edición
    width_text: str = ""  # texto de ejemplo para medir su anchura («±5 | 10 m»)
    source: str = ""


@dataclass(frozen=True)
class PieSpec:
    """Un menú circular (AR §4): sus 8 ranuras en el orden de Blender (O, E, S, N, NO, NE,
    SO, SE)."""

    id: str
    slots: tuple[str, ...]
    source: str = ""


@dataclass(frozen=True)
class ContextSpec:
    """El menú «<Tipo> ▾» de un tipo de objeto (PC §3) o de la selección de varios tipos
    (PC §4), con sus dos iconos de acción."""

    kind: str
    id: str
    items: tuple[MenuItem, ...]
    icons: tuple[MenuItem, ...]
    source: str = ""


@dataclass(frozen=True)
class Shortcut:
    """Un atajo del modo Geoblender (AT §2)."""

    key: str  # comando (o variante de un operador del catálogo)
    keymap: str  # KEYMAPS
    event: str  # tipo de evento de Blender (F10, PAGE_UP, NUMPAD_PLUS, ONE…)
    ctrl: bool = False
    shift: bool = False
    alt: bool = False
    label: str = ""  # msgid, si la clave no es un comando del catálogo
    label_es: str = ""
    source: str = ""

    @property
    def idname(self) -> str:
        return self.key.partition("?")[0]

    def combo(self) -> str:
        """La combinación en inglés de Blender (``Ctrl+Shift+F5``), para los mensajes."""
        mods = [name for name, on in (("Ctrl", self.ctrl), ("Shift", self.shift),
                                       ("Alt", self.alt)) if on]
        return "+".join([*mods, self.event])


@dataclass(frozen=True)
class EntryRef:
    """Una entrada del roadmap o una spec, con su título (para «Disponible en …»)."""

    id: str
    title: str  # msgid
    title_es: str
    delivered: bool = False  # su spec ya entrega sus comandos (002, 003…)
    source: str = ""


@dataclass(frozen=True)
class LayoutSpec:
    """Una disposición de Geoblender (CW §6.2): espacio de trabajo marcado."""

    id: str  # valor del enumerado de ui_add_layout
    workspace: str  # nombre del espacio de trabajo en geoblender_ui.blend
    label: str
    label_es: str
    description: str
    description_es: str
    entry: str
    main: bool = False
    source: str = ""


@dataclass(frozen=True)
class IconSpec:
    """Un icono propio (II §1.4): su nombre, su reserva nativa (``NONE`` si no tiene) y,
    si la reserva es un texto («GB», «[MED]»), ese texto."""

    name: str
    fallback: str = "NONE"
    fallback_text: str = ""
    source: str = ""


@dataclass(frozen=True)
class CatalogIssue:
    """Un problema del catálogo: dónde está (fichero, clave, campo, valor) y qué pasa."""

    file: str
    key: str
    field: str
    value: str
    message: str

    def __str__(self) -> str:
        where = f"{self.file}: {self.key}" if self.key else self.file
        return f"{where} · {self.field} = «{self.value}»: {self.message}"


@dataclass(frozen=True)
class Catalog:
    """El catálogo cargado: comandos (en orden de definición), menús, espejos, atajos,
    entradas y disposiciones; ``load_issues``, lo que no se pudo leer o resolver."""

    commands: Mapping[str, Command]
    menus: Mapping[str, MenuSpec]
    top_menus: tuple[str, ...]
    quick_access_items: tuple[QuickAccessItem, ...]
    quick_access_groups: Mapping[str, tuple[str, str]]  # id → (msgid, español)
    pies: Mapping[str, PieSpec]
    contexts: Mapping[str, ContextSpec]
    shortcut_list: tuple[Shortcut, ...]
    entries: Mapping[str, EntryRef]
    layouts: tuple[LayoutSpec, ...]
    load_issues: tuple[CatalogIssue, ...] = ()
    icons: Mapping[str, IconSpec] = field(default_factory=dict)  # los propios (II §1.4)
    _by_idname: Mapping[str, tuple[Command, ...]] = field(default_factory=dict, repr=False)

    def by_idname(self, idname: str) -> tuple[Command, ...]:
        """Los comandos de un ``bl_idname`` o una clase (todas sus variantes)."""
        return self._by_idname.get(idname, ())

    def operator_idnames(self) -> frozenset[str]:
        """Los ``bl_idname`` de los operadores de Geoblender (también los internos)."""
        return frozenset(c.idname for c in self.commands.values()
                         if c.kind in ("operator", "internal"))

    def class_names(self) -> frozenset[str]:
        """Las clases de menú y de panel de Geoblender del catálogo."""
        names = {c.idname for c in self.commands.values() if c.kind in ("menu", "panel")}
        return frozenset(name for name in names if name.startswith("GEOBLENDER_"))

    def quick_access(self, scope: str) -> tuple[QuickAccessItem, ...]:
        """Los controles de acceso rápido de ``scope`` (``project`` o ``view``) en orden."""
        return tuple(sorted((item for item in self.quick_access_items if item.scope == scope),
                            key=lambda item: item.order))

    def shortcuts(self) -> tuple[Shortcut, ...]:
        return self.shortcut_list

    def shortcuts_for(self, key: str) -> tuple[Shortcut, ...]:
        """Los atajos de un comando (por su clave exacta)."""
        return tuple(s for s in self.shortcut_list if s.key == key)

    def context(self, kind: str) -> ContextSpec | None:
        """El menú contextual de un tipo de objeto (PC §3) o ``SELECTION`` (PC §4)."""
        return self.contexts.get(kind)

    def path(self, key: str) -> tuple[str, ...]:
        """Los ``msgid`` de la ruta canónica de un comando desde la barra: menús, grupo
        de su casa y su etiqueta (``("Project", "Georeference", "Work window…")``)."""
        command = self.commands[key]
        parts: list[str] = [command.label]
        if command.home_group:
            parts.append(command.home_group)
        menu = command.home
        seen: set[str] = set()
        while menu and menu not in seen:
            seen.add(menu)
            owner = self.commands.get(menu)
            if owner is None:
                break
            parts.append(owner.label)
            if owner.home_group:
                parts.append(owner.home_group)
            menu = owner.home
        return tuple(reversed(parts))

    def msgids(self) -> list[str]:
        """Todos los ``msgid`` del catálogo, con traducción o sin ella (RNF-003-08)."""
        found: dict[str, None] = {}
        for command in self.commands.values():
            found.update(dict.fromkeys(filter(None, (command.label, command.description))))
        for menu in self.menus.values():
            found.update(dict.fromkeys(filter(None, (menu.stage, *(g.label for g in menu.groups)))))
        for context in self.contexts.values():
            for item in (*context.items, *context.icons):
                if item.placeholder and item.placeholder[0]:
                    found[item.placeholder[0]] = None
        found.update(dict.fromkeys(filter(None, (m for m, _ in self.quick_access_groups.values()))))
        found.update(dict.fromkeys(filter(None, (s.label for s in self.shortcut_list))))
        found.update(dict.fromkeys(filter(None, (e.title for e in self.entries.values()))))
        for layout in self.layouts:
            found.update(dict.fromkeys(filter(None, (layout.label, layout.description))))
        return list(found)

    def translations(self) -> dict[str, str]:
        """``msgid`` → español de todos los textos del catálogo (``core.i18n.install``)."""
        table: dict[str, str] = {}

        def add(msgid: str, spanish: str) -> None:
            if msgid and spanish:
                table.setdefault(msgid, spanish)

        for command in self.commands.values():
            add(command.label, command.label_es)
            add(command.description, command.description_es)
        for menu in self.menus.values():
            add(menu.stage, menu.stage_es)
            for group in menu.groups:
                add(group.label, group.label_es)
        for context in self.contexts.values():
            for item in (*context.items, *context.icons):
                if item.placeholder:
                    add(*item.placeholder)
        for msgid, spanish in self.quick_access_groups.values():
            add(msgid, spanish)
        for shortcut in self.shortcut_list:
            add(shortcut.label, shortcut.label_es)
        for entry in self.entries.values():
            add(entry.title, entry.title_es)
        for layout in self.layouts:
            add(layout.label, layout.label_es)
            add(layout.description, layout.description_es)
        return table


def format_value(value: PropValue) -> str:
    """Un valor de propiedad como va en una clave (``True``, ``-1``, ``PLAN``)."""
    return str(value)


def parse_value(text: str) -> PropValue:
    """El valor de una propiedad de una clave: ``True``/``False``, un entero o un texto."""
    if text in ("True", "False"):
        return text == "True"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def make_key(idname: str, props: Mapping[str, PropValue]) -> str:
    """La clave de un comando: el ``bl_idname`` o la clase y, si fija propiedades,
    ``?nombre=valor&…`` en orden de nombre (``geoblender.ui_set_view?view=PLAN``)."""
    if not props:
        return idname
    return idname + "?" + "&".join(f"{name}={format_value(props[name])}"
                                   for name in sorted(props))


def split_key(key: str) -> tuple[str, tuple[tuple[str, PropValue], ...]]:
    """(``bl_idname`` o clase, propiedades en el orden en que se escribieron) de una
    clave; ``ValueError`` si una propiedad no es ``nombre=valor``."""
    idname, _, query = key.partition("?")
    props: list[tuple[str, PropValue]] = []
    if query:
        for part in query.split("&"):
            name, equals, text = part.partition("=")
            if not equals or not re.fullmatch(r"[a-z_][a-z0-9_]*", name) or not text:
                raise ValueError(f"propiedad «{part}»: se escribe nombre=valor")
            props.append((name, parse_value(text)))
    return idname, tuple(props)


def is_operator_key(key: str) -> bool:
    """Verdadero si la clave es de un operador de Geoblender (``geoblender.…``)."""
    return key.startswith("geoblender.")


def kind_for(key: str) -> str:
    """El tipo que corresponde al prefijo de una clave (sin ``internal``, que se
    declara)."""
    idname = key.partition("?")[0]
    if idname.startswith("geoblender."):
        return "operator"
    if idname.startswith("GEOBLENDER_MT_"):
        return "menu"
    if idname.startswith("GEOBLENDER_PT_"):
        return "panel"
    if "." in idname and idname.split(".", 1)[0] in ("tool_settings", "space_data", "scene"):
        return "property"
    return "native"


def module_of(idname: str) -> str:
    """El código de módulo de un ``bl_idname`` o una clase de Geoblender ("" si no es)."""
    match = IDNAME_RE.match(idname) or CLASS_RE.match(idname)
    if match is None:
        return ""
    return match.group(1) if idname.startswith("geoblender.") else match.group(2)


def placeholders(text: str) -> set[str]:
    """Los nombres de los marcadores ``{nombre}`` de un texto (``str.format``)."""
    try:
        return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name}
    except ValueError:
        return {"<llaves sin cerrar>"}


def _issue(source: str, key: str, field_name: str, value: object, message: str) -> CatalogIssue:
    return CatalogIssue(source, key, field_name, str(value), message)


class _Validator:
    def __init__(self, cat: Catalog, roadmap_ids: frozenset[str] | None,
                 messages: Mapping[str, str] | None) -> None:
        self.cat = cat
        self.roadmap_ids = roadmap_ids
        self.messages = messages or {}
        self.found: list[CatalogIssue] = list(cat.load_issues)
        self.msgids: dict[str, tuple[str, str, str, str]] = {}  # msgid → (es, fichero, clave, campo)

    def add(self, source: str, key: str, field_name: str, value: object, message: str) -> None:
        self.found.append(_issue(source, key, field_name, value, message))

    # Textos ----------------------------------------------------------------------------

    def text(self, source: str, key: str, field_name: str, msgid: str, spanish: str) -> None:
        """Un par ``msgid`` / español: los dos presentes, el ``msgid`` sin letras del
        español, los mismos marcadores y una sola traducción por ``msgid``."""
        if not msgid.strip():
            self.add(source, key, f"{field_name}.en", msgid,
                     "falta el texto en inglés (el msgid)")
            return
        if not spanish.strip():
            self.add(source, key, f"{field_name}.es", spanish,
                     f"falta la traducción al español de «{msgid}»")
            return
        if set(msgid) & SPANISH_LETTERS:
            self.add(source, key, f"{field_name}.en", msgid,
                     "el msgid está en inglés: tiene letras del español")
        if placeholders(msgid) != placeholders(spanish):
            self.add(source, key, f"{field_name}.es", spanish,
                     f"tiene otros marcadores {{…}} que el msgid «{msgid}»")
        previous = self.msgids.get(msgid)
        if previous is None:
            known = self.messages.get(msgid)
            if known is not None and known != spanish:
                self.add(source, key, f"{field_name}.es", spanish,
                         f"«{msgid}» ya se traduce «{known}» en core/i18n/messages.toml: un "
                         "msgid, una traducción (cambie el msgid o la traducción)")
            self.msgids[msgid] = (spanish, source, key, field_name)
        elif previous[0] != spanish:
            self.add(source, key, f"{field_name}.es", spanish,
                     f"«{msgid}» ya se traduce «{previous[0]}» en {previous[1]} "
                     f"({previous[2] or previous[3]}): un msgid, una traducción")

    # Comandos --------------------------------------------------------------------------

    def command(self, command: Command) -> None:
        source, key = command.source, command.key
        if command.kind not in KINDS:
            self.add(source, key, "kind", command.kind, f"tipo desconocido: {', '.join(KINDS)}")
        expected = kind_for(key)
        if command.kind != expected and not (command.kind == "internal" and expected == "operator"):
            self.add(source, key, "kind", command.kind,
                     f"la clave es de un {expected}: no puede ser «{command.kind}»")
        if command.kind in ("operator", "internal") and not IDNAME_RE.match(command.idname):
            self.add(source, key, "key", key,
                     "el bl_idname no cumple ADR-0011: geoblender.<módulo>_<acción> en "
                     f"minúsculas, con un módulo de {', '.join(MODULE_CODES)}")
        if command.kind in ("menu", "panel") and not CLASS_RE.match(command.idname):
            self.add(source, key, "key", key,
                     "la clase no cumple ADR-0011: GEOBLENDER_<MT|PT>_<módulo>_<nombre> en "
                     f"minúsculas, con un módulo de {', '.join(MODULE_CODES)}")
        if "?" in key:
            canonical = make_key(command.idname, dict(command.props))
            if canonical != key:
                self.add(source, key, "key", key,
                         f"las propiedades van en orden de nombre: «{canonical}»")
        self.text(source, key, "label", command.label, command.label_es)
        self.text(source, key, "description", command.description, command.description_es)
        if command.action not in ACTIONS:
            self.add(source, key, "action", command.action,
                     f"tipo de acción desconocido: {', '.join(ACTIONS)} (README §6)")
        if not 0 <= command.frequency <= 3:
            self.add(source, key, "frequency", command.frequency,
                     "la frecuencia va de 0 (○) a 3 (●●●)")
        self.entry(source, key, command.entry, allow_empty=command.kind == "menu")
        if command.icon is not None and not OWN_ICON_RE.match(command.icon):
            self.add(source, key, "icon", command.icon,
                     "un icono propio se llama gb_<grupo>_<concepto> (II §1.3)")
        if not NATIVE_ICON_RE.match(command.icon_fallback):
            self.add(source, key, "icon_fallback", command.icon_fallback,
                     "la reserva es el nombre de un icono nativo de Blender (MAYÚSCULAS)")
        for alias in command.aliases:
            if not alias.strip():
                self.add(source, key, "aliases", alias, "alias vacío")
        for program, term in command.jargon:
            if not program.strip() or not term.strip():
                self.add(source, key, "jargon", f"{program}: {term}",
                         "cada término de otro programa es [programa, término]")

    def entry(self, source: str, key: str, entry: str, *, allow_empty: bool = False) -> None:
        if not entry:
            if not allow_empty:
                self.add(source, key, "entry", entry, "falta la entrada (spec o R-id)")
            return
        if entry not in self.cat.entries:
            self.add(source, key, "entry", entry,
                     "entrada sin título en entries.toml: «Disponible en …» no se podría "
                     "escribir")

    # Referencias -----------------------------------------------------------------------

    def resolve(self, source: str, owner: str, field_name: str, key: str,
                *, needs_home: bool = False) -> None:
        command = self.cat.commands.get(key)
        if command is None:
            self.add(source, key, field_name, key,
                     f"referencia a un comando que no está en el catálogo (en {owner})")
            return
        if needs_home and command.kind == "operator" and not command.home:
            self.add(source, key, field_name, key,
                     f"{owner} es un espejo: apunta a un comando con casa en un menú")

    def menus(self) -> None:
        cat = self.cat
        for menu in cat.menus.values():
            if menu.id not in cat.commands:
                self.add(menu.source, menu.id, "id", menu.id,
                         "contenido de un menú que no está en ningún sitio: falta su "
                         "definición (etiqueta, entrada) en un menú o con label aquí")
            if menu.stage:
                self.text(menu.source, menu.id, "stage", menu.stage, menu.stage_es)
            if menu.branch and menu.branch not in BRANCHES:
                self.add(menu.source, menu.id, "branch", menu.branch,
                         f"rama desconocida: {', '.join(BRANCHES)}")
            for group in menu.groups:
                if group.label:
                    self.text(menu.source, menu.id, "group.label", group.label, group.label_es)
                for item in group.items:
                    if item.key is not None and (item.cross or item.key not in cat.commands
                                                 or cat.commands[item.key].home != menu.id):
                        field_name = "ref" if item.cross else "mirror"
                        self.resolve(menu.source, menu.id, field_name, item.key)
        with_content = (set(cat.menus) | set(cat.pies)
                        | {context.id for context in cat.contexts.values()})
        for command in cat.commands.values():
            if (command.kind == "menu" and command.idname.startswith("GEOBLENDER_")
                    and command.idname not in with_content and not command.dynamic):
                self.add(command.source, command.key, "menu", "",
                         "submenú sin contenido: defínalo con sus elementos aquí o en un "
                         "[[menu]] con su id, o márquelo dynamic")

    def mirrors(self) -> None:
        cat = self.cat
        for item in cat.quick_access_items:
            for key in filter(None, (item.key, item.extra)):
                self.resolve(item.source, f"el acceso rápido ({item.scope})", "key", key,
                             needs_home=True)
            if item.display not in DISPLAYS:
                self.add(item.source, item.key, "display", item.display,
                         f"presentación desconocida: {', '.join(DISPLAYS)}")
        for pie in cat.pies.values():
            if len(pie.slots) != len(PIE_SLOTS):
                self.add(pie.source, pie.id, "slots", len(pie.slots),
                         f"un menú circular tiene {len(PIE_SLOTS)} ranuras ({' '.join(PIE_SLOTS)})")
            for key in pie.slots:
                if key:
                    self.resolve(pie.source, pie.id, "slot", key, needs_home=True)
        for context in cat.contexts.values():
            if context.kind not in CONTEXT_KINDS:
                self.add(context.source, context.id, "kind", context.kind,
                         f"tipo de objeto desconocido: {', '.join(CONTEXT_KINDS)}")
            for item in (*context.items, *context.icons):
                if item.key is not None:
                    self.resolve(context.source, context.id, "item", item.key, needs_home=True)
                elif item.placeholder is not None:
                    self.text(context.source, context.id, "placeholder", *item.placeholder)
                    self.entry(context.source, context.id, item.entry)

    def shortcuts(self) -> None:
        cat = self.cat
        seen: dict[tuple[str, str, bool, bool, bool], Shortcut] = {}
        for shortcut in cat.shortcut_list:
            source, key = shortcut.source, shortcut.key
            if key not in cat.commands and not cat.by_idname(shortcut.idname):
                self.add(source, key, "key", key,
                         "atajo de un comando que no está en el catálogo")
            elif key not in cat.commands and not shortcut.label:
                self.add(source, key, "label", "",
                         "la clave no es un comando del catálogo: el atajo lleva su label")
            if shortcut.label:
                self.text(source, key, "label", shortcut.label, shortcut.label_es)
            if shortcut.keymap not in KEYMAPS:
                self.add(source, key, "keymap", shortcut.keymap,
                         f"mapa de teclas desconocido: {', '.join(KEYMAPS)}")
            if shortcut.ctrl and shortcut.alt:
                self.add(source, key, "event", shortcut.combo(),
                         "Ctrl+Alt está prohibido: es AltGr en el teclado español (AT §1)")
            combo = (shortcut.keymap, shortcut.event, shortcut.ctrl, shortcut.shift, shortcut.alt)
            first = seen.get(combo)
            if first is not None:
                self.add(source, key, "event", shortcut.combo(),
                         f"atajo repetido en el mapa «{shortcut.keymap}»: ya es de "
                         f"{first.key}")
            else:
                seen[combo] = shortcut

    def entries(self) -> None:
        for entry in self.cat.entries.values():
            if not ENTRY_RE.match(entry.id):
                self.add(entry.source, entry.id, "entry", entry.id,
                         "una entrada es una spec (NNN), un R-id (R-nn) o «Blender»")
            self.text(entry.source, entry.id, "title", entry.title, entry.title_es)
            if (self.roadmap_ids is not None and entry.id.startswith("R-")
                    and entry.id not in self.roadmap_ids):
                self.add(entry.source, entry.id, "entry", entry.id,
                         "R-id que no está en docs/producto/roadmap.md")

    def icons(self) -> None:
        for icon in self.cat.icons.values():
            if not OWN_ICON_RE.match(icon.name):
                self.add(icon.source, icon.name, "name", icon.name,
                         "un icono propio se llama gb_<grupo>_<concepto> (II §1.3)")
            if not NATIVE_ICON_RE.match(icon.fallback):
                self.add(icon.source, icon.name, "fallback", icon.fallback,
                         "la reserva es el nombre de un icono nativo de Blender (MAYÚSCULAS)")
        for command in self.cat.commands.values():
            if (self.cat.icons and command.icon is not None
                    and command.icon not in self.cat.icons):
                self.add(command.source, command.key, "icon", command.icon,
                         "icono propio que no está en icons.toml (II §1.4)")

    def layouts(self) -> None:
        for layout in self.cat.layouts:
            self.text(layout.source, layout.id, "label", layout.label, layout.label_es)
            self.text(layout.source, layout.id, "description", layout.description,
                      layout.description_es)
            self.entry(layout.source, layout.id, layout.entry)

    def run(self) -> list[CatalogIssue]:
        for command in self.cat.commands.values():
            self.command(command)
        self.menus()
        self.mirrors()
        self.shortcuts()
        self.entries()
        self.layouts()
        self.icons()
        for msgid, spanish in self.cat.quick_access_groups.values():
            self.text("quick_access.toml", "", "groups", msgid, spanish)
        unique = {(i.file, i.key, i.field, i.value, i.message): i for i in self.found}
        return sorted(unique.values(), key=lambda i: (i.file, i.key, i.field, i.value))


def validate(cat: Catalog, *, roadmap_ids: frozenset[str] | None = None,
             messages: Mapping[str, str] | None = None) -> list[CatalogIssue]:
    """Las incidencias del catálogo, ordenadas por fichero, clave y campo (vacía si es
    válido). Con ``roadmap_ids``, también los R-id que no están en el roadmap; con
    ``messages`` (el ``messages.toml`` de ``core.i18n``), los ``msgid`` que allí tienen
    otra traducción."""
    return _Validator(cat, roadmap_ids, messages).run()

