# SPDX-License-Identifier: GPL-3.0-or-later
"""Operadores reales del módulo ``ui`` (spec 003; plan 003 §5.3).

- ``geoblender.ui_toggle_mode`` (RF-003-01, RF-003-02; CW §2 y §3): conmuta la ventana
  entre Geoblender y Blender con ``bl.ui.switcher``; ``target`` = ``TOGGLE`` (por defecto,
  el atajo Ctrl+F10 y F3), ``GEOBLENDER`` o ``BLENDER`` (los dos botones del conmutador).
  Pedir el modo activo no hace nada. Si hubo que anexar el espacio de trabajo desde los
  recursos, lo dice. Funciona en los dos modos y desde cualquier editor (su atajo está en
  el mapa «Window»), así que no pasa por la puerta de modo. Sin ``UNDO``: conmutar no es
  un paso de deshacer (CW §3.3).
- ``geoblender.ui_call_pie`` y ``geoblender.ui_call_panel`` (internos; RF-003-18,
  RF-003-19; AT §1, regla 2): abren un menú circular (``name``) o un panel flotante
  (``name``, ``keep_open``) de Geoblender con ``wm.call_menu_pie`` y ``wm.call_panel``,
  que no saben del modo: sus atajos están en la Vista 3D, así que pasan por la puerta de
  modo (``bl.ui.gate``) y en modo Blender la tecla queda para Blender.
- ``geoblender.ui_call_context_menu``, ``geoblender.ui_toggle_context_pin`` y
  ``geoblender.ui_show_context_panel`` (internos; RF-003-17; PC §1): Mayús+Alt+B abre bajo el
  cursor el menú «<Tipo> ▾» del contexto de la vista (sin tipo, «Herramientas»;
  ``bl.ui.headers``), con la puerta de modo; la chincheta de la fila 1 fija o suelta el
  contexto de esa Vista 3D; «Parámetros…» abre la barra lateral N de la Vista 3D de
  destino en la pestaña del tipo.
- ``geoblender.ui_set_view`` (RF-003-12; spec §6.1 y §7; BS §8.12; AR §4): pone la Vista
  3D de destino (``bl.ui.views.target_view3d``) en una vista minera (``view``), en
  ortográfica. Su ``bl_label`` es el del menú donde viven sus variantes («Vistas», regla de
  ``bl.ui.provisional.base_command``) y su descripción emergente, la de la vista pedida.
  Sin ninguna Vista 3D en la ventana, su ``poll`` falla y lo dice.
- ``geoblender.ui_frame_work_window`` (RF-003-13; Mayús+Alt+Inicio): encuadra en la Vista
  3D de destino la ventana de trabajo del proyecto con las cotas de lo visible en ella y
  ajusta el recorte de la vista (``bl.ui.views.frame_work_window``). Sin proyecto o sin
  ventana de trabajo, su ``poll`` falla con el paso previo y su ruta (spec §8).
- ``geoblender.ui_store_view`` y ``geoblender.ui_recall_view`` (RF-003-14; Ctrl+Mayús+F5…F8
  y Ctrl+F5…F8): guardan y recuperan la vista de la ranura ``slot`` (1–4) de la escena.
  Guardar cambia la escena, así que lleva ``UNDO``. Recuperar una ranura vacía informa
  «Guarde antes la vista n (…)» y no cambia nada; su descripción emergente lo dice y los
  menús la dibujan desactivada.
- Los tres tienen atajo en la Vista 3D: pasan por la puerta de modo (contrato 2).
- ``geoblender.ui_edit_legend`` y ``geoblender.ui_edit_data_filter`` (RF-003-09; contrato
  6; BS §8.12, Consulta ▸): la Leyenda y el Filtro de datos genéricos, con el proveedor
  del tipo del objeto activo (``bl.ui.context``). Sin proveedor, su ``poll`` falla con
  «Seleccione sondeos (005) o un modelo de bloques (R-22)». La Leyenda, sin ``field``,
  abre su ventana emergente (la lista de campos); con él, lo aplica (un campo que no es
  del tipo, no). El Filtro abre un diálogo con los campos y la expresión, y la aplica; si
  el proveedor la rechaza, informa su motivo y no cambia nada. Lo que aplican cambia la
  escena (colores, visibilidad): llevan ``UNDO``.
- ``geoblender.ui_toggle_quick_access_row`` (RF-003-11; AR §3.3): Herramientas ▸
  Disposición ▸ «Mostrar la fila de acceso rápido de la vista» (``bl.ui.quick_access``):
  si la fila ya se ve, apaga la preferencia; si no, la enciende y muestra la fila 2 de las
  Vistas 3D de la pantalla.
- ``geoblender.ui_add_layout``, ``geoblender.ui_remove_layout`` y
  ``geoblender.ui_restore_layout`` (RF-003-16; CW §6.4; BS §8.12, Disposición ▸): activar
  una disposición (``layout``; si el fichero no la tiene, se anexa de los recursos y lo
  dice), quitar la de esta ventana o restaurarla desde los recursos (``bl.ui.layouts``).
  Quitar y Restaurar actúan sobre el espacio de la ventana o sobre el que nombra
  ``workspace``; la principal no se quita y nunca se borran datos: si no se puede, lo
  dicen y no cambian nada. Las disposiciones de una entrada aún no entregada (R-62, R-57)
  informan «Disponible en …» y no cambian nada. Son interfaz: sin ``UNDO``.
- ``geoblender.ui_open_command_line`` (RF-003-26; F10, con la puerta de modo;
  Herramientas ▸ Línea de comandos): abre una ventana con el campo ``query`` ya activo; al
  escribir, la lista son los resultados de la búsqueda del catálogo (``bl.ui.
  command_line``), los no disponibles con su «Disponible en …»; al confirmar, ejecuta el
  elegido (o el primer resultado) en la Vista 3D de destino o informa «Disponible en …» sin
  cambiar nada. Con ``query`` (un script, un atajo propio), no abre la ventana. Sin ``UNDO``:
  el comando elegido pone su propio paso de deshacer.
- ``geoblender.ui_show_shortcuts``, ``ui_show_aliases`` y ``ui_show_glossary``
  (RF-003-27; Ayuda): la hoja de atajos (los registrados, tal como están), de alias de F10 o
  el glosario (``bl.ui.help``), en una ventana emergente con el botón de su versión
  imprimible; con ``printable``, la página HTML en la carpeta de datos de la extensión,
  abierta en el navegador. ``geoblender.ui_run_diagnostics`` (RF-003-27): el diagnóstico de
  la instalación en una ventana emergente (sin interfaz, en la consola); con ``copy``, lo
  copia al portapapeles. ``geoblender.ui_show_about``: versión, licencias y la atribución
  de los datos de terceros. ``geoblender.ui_show_preferences``: abre Preferencias ▸
  Complementos en Geoblender. ``geoblender.ui_set_language`` (RF-003-21; Ayuda ▸ Idioma de
  Geoblender): fija la preferencia (cuyo ``update`` aplica el idioma en el siguiente ciclo,
  ``bl.ui.i18n``) y la marca para que Blender la guarde. Ninguno cambia la escena: sin
  ``UNDO``.
- ``geoblender.ui_repair_interface`` (RF-003-24; CW §5): Ayuda ▸ Reparar la interfaz
  (``bl.ui.repair``): la barra superior, una sola vez aunque otro complemento la haya
  sustituido, y los atajos. Se puede pulsar siempre.

``bl_label`` y ``bl_description`` son los ``msgid`` del catálogo (contrato 1 del plan
003); ``bl.ui.registry`` los pone en el idioma de Geoblender al registrar la interfaz.
"""

from __future__ import annotations

from typing import Any

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from ...core import catalog as core_catalog
from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ..props.ui import LANGUAGE_ITEMS, LANGUAGES
from ..ui import gate

TRANSLATION_CONTEXT = "Geoblender"
# Vistas mineras (spec §6.1): los nombres son las etiquetas del catálogo.
VIEW_ITEMS = [
    ("PLAN", "Plan", ""),
    ("NORTH", "Looking north (E-W section)", ""),
    ("SOUTH", "Looking south", ""),
    ("EAST", "Looking east (N-S section)", ""),
    ("WEST", "Looking west", ""),
    ("ISO_NE", "Isometric NE", ""),
    ("ISO_NW", "Isometric NW", ""),
    ("ISO_SE", "Isometric SE", ""),
    ("ISO_SW", "Isometric SW", ""),
]
# Disposiciones (layouts.toml): los nombres son las etiquetas del catálogo.
LAYOUT_ITEMS = [(item.id, item.label, "") for item in core_catalog.load().layouts]
TARGET_ITEMS = [
    ("TOGGLE", "Toggle", "Switch to the other interface"),
    ("GEOBLENDER", "Geoblender", "Switch to the Geoblender interface"),
    ("BLENDER", "Blender", "Switch to the Blender interface"),
]


class GEOBLENDER_OT_ui_toggle_mode(bpy.types.Operator):
    """Switch this window between the Geoblender interface and the Blender one"""

    bl_idname = "geoblender.ui_toggle_mode"
    bl_label = "Switch Geoblender ⇄ Blender"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    target: EnumProperty(  # type: ignore[valid-type]
        name="Target",
        items=TARGET_ITEMS,
        default="TOGGLE",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return getattr(context, "window", None) is not None

    def execute(self, context: Any) -> set[str]:
        from ..ui import switcher  # diferido: bl/ui importa bl/ops

        result = switcher.toggle(context.window, self.target)
        if result.workspace is None:
            return {"CANCELLED"}
        if result.appended:
            self.report({"INFO"}, tr("The Geoblender workspace has been added to this file"))
        return {"FINISHED"}


class GEOBLENDER_OT_ui_call_pie(bpy.types.Operator):
    """Open a Geoblender pie menu (only in Geoblender mode)"""

    bl_idname = "geoblender.ui_call_pie"
    bl_label = "Pie menu"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"INTERNAL"}

    name: StringProperty(name="Menu", default="", options={"SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return gate.poll(cls, context)

    def execute(self, context: Any) -> set[str]:
        return bpy.ops.wm.call_menu_pie(name=self.name)

    def invoke(self, context: Any, event: Any) -> set[str]:
        return self.execute(context)


class GEOBLENDER_OT_ui_call_panel(bpy.types.Operator):
    """Open a Geoblender panel at the cursor (only in Geoblender mode)"""

    bl_idname = "geoblender.ui_call_panel"
    bl_label = "Floating panel"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"INTERNAL"}

    name: StringProperty(name="Panel", default="", options={"SKIP_SAVE"})  # type: ignore[valid-type]
    keep_open: BoolProperty(name="Keep open", default=False, options={"SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return gate.poll(cls, context)

    def execute(self, context: Any) -> set[str]:
        return bpy.ops.wm.call_panel(name=self.name, keep_open=self.keep_open)

    def invoke(self, context: Any, event: Any) -> set[str]:
        return self.execute(context)


class GEOBLENDER_OT_ui_call_context_menu(bpy.types.Operator):
    """Open under the cursor the menu of the type of the active object"""

    bl_idname = "geoblender.ui_call_context_menu"
    bl_label = "Menu of the active type"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return gate.poll(cls, context)

    def execute(self, context: Any) -> set[str]:
        from ..ui import headers

        return bpy.ops.wm.call_menu(name=headers.context_menu_id(context))

    def invoke(self, context: Any, event: Any) -> set[str]:
        return self.execute(context)


class GEOBLENDER_OT_ui_toggle_context_pin(bpy.types.Operator):
    """Keep the menu and the tab of the current item although the selection changes"""

    bl_idname = "geoblender.ui_toggle_context_pin"
    bl_label = "Pin the context"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        area = getattr(context, "area", None)
        return area is not None and getattr(area, "type", "") == "VIEW_3D"

    def execute(self, context: Any) -> set[str]:
        from ..ui import context as ui_context

        ui_context.toggle_pin(context)
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()
        return {"FINISHED"}


class GEOBLENDER_OT_ui_show_context_panel(bpy.types.Operator):
    """Parameters of the active item"""

    bl_idname = "geoblender.ui_show_context_panel"
    bl_label = "Parameters…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        from ..ui import headers

        if not gate.poll(cls, context) or not _poll_view3d(cls, context):
            return False
        if headers.context_spec(context)[0] is None:
            cls.poll_message_set(tr("Select an item of Geoblender"))
            return False
        return True

    def execute(self, context: Any) -> set[str]:
        from ..ui import commands, headers, views

        target = views.target_view3d(context)
        spec, _count = headers.context_spec(context)
        if target is None or spec is None:
            return {"CANCELLED"}
        target.space.show_region_ui = True
        tab = commands.text(commands.catalog().commands[spec.id].label)
        for region in target.area.regions:
            if region.type == "UI":
                try:
                    region.active_panel_category = tab
                except (AttributeError, TypeError, ValueError):
                    pass  # sin pestañas en la región, o la del tipo aún no existe
        return {"FINISHED"}


def _variant_description(idname: str, properties: Any) -> str:
    """La descripción de la variante del catálogo con esas propiedades, en el idioma de
    Geoblender."""
    from ..ui import commands, provisional  # diferido, como el conmutador

    cmd = provisional.variant_for(commands.catalog(), idname, properties)
    return commands.text(cmd.description) if cmd is not None else ""


def _poll_gated_view3d(cls: Any, context: Any) -> bool:
    """La puerta de modo (tiene atajo en la Vista 3D) y una Vista 3D de destino."""
    return gate.poll(cls, context) and _poll_view3d(cls, context)


def _poll_view3d(cls: Any, context: Any) -> bool:
    """Hay una Vista 3D de destino; si no, lo dice."""
    from ..ui import views

    if views.target_view3d(context) is not None:
        return True
    cls.poll_message_set(tr("There is no 3D view in this window"))
    return False


class GEOBLENDER_OT_ui_set_view(bpy.types.Operator):
    """Mining views, framing and saved views"""

    bl_idname = "geoblender.ui_set_view"
    bl_label = "Views"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    view: EnumProperty(name="View", items=VIEW_ITEMS, default="PLAN")  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _poll_view3d(cls, context)

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        return _variant_description(cls.bl_idname, properties)

    def execute(self, context: Any) -> set[str]:
        from ..ui import views

        target = views.target_view3d(context)
        if target is None:
            return {"CANCELLED"}
        views.set_view(target, self.view)
        return {"FINISHED"}


class GEOBLENDER_OT_ui_frame_work_window(bpy.types.Operator):
    """Show the whole work window of the project and adjust the clipping distance of the view"""

    bl_idname = "geoblender.ui_frame_work_window"
    bl_label = "Frame the work window"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        from ..ui import views

        if not _poll_gated_view3d(cls, context):
            return False
        if views.work_window_local() is None:
            cls.poll_message_set(views.no_work_window_message())
            return False
        return True

    def execute(self, context: Any) -> set[str]:
        from ..ui import views

        target = views.target_view3d(context)
        if target is None or not views.frame_work_window(target, context):
            self.report({"WARNING"}, views.no_work_window_message())
            return {"CANCELLED"}
        return {"FINISHED"}


class GEOBLENDER_OT_ui_store_view(bpy.types.Operator):
    """Save the orientation, centre, distance and projection of the view in a slot"""

    bl_idname = "geoblender.ui_store_view"
    bl_label = "Save view"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    slot: IntProperty(name="Slot", min=1, max=4, default=1)  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _poll_gated_view3d(cls, context)

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        return _variant_description(cls.bl_idname, properties)

    def execute(self, context: Any) -> set[str]:
        from ..ui import views

        target = views.target_view3d(context)
        if target is None:
            return {"CANCELLED"}
        views.store_view(target, context.scene, self.slot)
        self.report({"INFO"}, tr("View {n} saved", n=self.slot))
        return {"FINISHED"}


class GEOBLENDER_OT_ui_recall_view(bpy.types.Operator):
    """Restore a saved view: orientation, centre, distance and projection"""

    bl_idname = "geoblender.ui_recall_view"
    bl_label = "Recall view"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    slot: IntProperty(name="Slot", min=1, max=4, default=1)  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _poll_gated_view3d(cls, context)

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        from ..ui import views

        scene = getattr(context, "scene", None) or bpy.context.scene
        if views.saved_view(scene, properties.slot) is None:
            return views.empty_slot_message(properties.slot)
        return _variant_description(cls.bl_idname, properties)

    def execute(self, context: Any) -> set[str]:
        from ..ui import views

        target = views.target_view3d(context)
        if target is None:
            return {"CANCELLED"}
        if not views.recall_view(target, context.scene, self.slot):
            self.report({"WARNING"}, views.empty_slot_message(self.slot))
            return {"CANCELLED"}
        return {"FINISHED"}


def _poll_provider(cls: Any, context: Any, provider: Any) -> bool:
    """Hay proveedor para el tipo activo; si no, el paso previo (spec §8)."""
    from ..ui import context as ui_context

    if provider is not None:
        return True
    cls.poll_message_set(ui_context.no_provider_message())
    return False


class GEOBLENDER_OT_ui_edit_legend(bpy.types.Operator):
    """Colour the items of the active type by one of their fields"""

    bl_idname = "geoblender.ui_edit_legend"
    bl_label = "Legend: colour by field…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    field: StringProperty(name="Field", default="", options={"SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        from ..ui import context as ui_context

        return _poll_provider(cls, context, ui_context.legend_provider(context))

    def invoke(self, context: Any, event: Any) -> set[str]:
        from ..ui import context as ui_context

        if not self.field:
            return bpy.ops.wm.call_panel(name=ui_context.LEGEND_PANEL)
        return self.execute(context)

    def execute(self, context: Any) -> set[str]:
        from ..ui import context as ui_context

        provider = ui_context.legend_provider(context)
        if provider is None or not self.field:
            return {"CANCELLED"}
        if self.field not in {field.id for field in provider.fields(context)}:
            self.report({"ERROR"}, tr("The field «{field}» is not one of the active type",
                                      field=self.field))
            return {"CANCELLED"}
        try:
            provider.apply(context, self.field)
        except GeoblenderError as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}
        return {"FINISHED"}


class GEOBLENDER_OT_ui_edit_data_filter(bpy.types.Operator):
    """Show only the items of the active type that meet an expression"""

    bl_idname = "geoblender.ui_edit_data_filter"
    bl_label = "Data filter by expression…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    expression: StringProperty(name="Expression", default="")  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        from ..ui import context as ui_context

        return _poll_provider(cls, context, ui_context.data_filter_provider(context))

    def invoke(self, context: Any, event: Any) -> set[str]:
        from ..ui import context as ui_context

        provider = ui_context.data_filter_provider(context)
        if provider is not None:
            self.expression = provider.current(context)
        return context.window_manager.invoke_props_dialog(self, width=420, translate=False)

    def draw(self, context: Any) -> None:
        from ..ui import context as ui_context

        layout = self.layout
        provider = ui_context.data_filter_provider(context)
        if provider is not None:
            column = layout.column(align=True)
            column.active = False
            for field in provider.fields(context):
                column.label(text=" · ".join((field.id, field.label)), translate=False)
        layout.prop(self, "expression", text="", translate=False)

    def execute(self, context: Any) -> set[str]:
        from ..ui import context as ui_context

        provider = ui_context.data_filter_provider(context)
        if provider is None:
            return {"CANCELLED"}
        try:
            provider.apply(context, self.expression)
        except GeoblenderError as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}
        return {"FINISHED"}


class GEOBLENDER_OT_ui_toggle_quick_access_row(bpy.types.Operator):
    """Show or hide row 2 of the 3D views"""

    bl_idname = "geoblender.ui_toggle_quick_access_row"
    bl_label = "Show the quick access row of the view"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return getattr(context, "screen", None) is not None

    def execute(self, context: Any) -> set[str]:
        from ..ui import quick_access  # diferido, como el conmutador

        quick_access.toggle_row(context)
        return {"FINISHED"}


class GEOBLENDER_OT_ui_add_layout(bpy.types.Operator):
    """Add, remove or restore the Geoblender layouts"""

    bl_idname = "geoblender.ui_add_layout"
    bl_label = "Layouts"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    layout: EnumProperty(name="Layout", items=LAYOUT_ITEMS)  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return getattr(context, "window", None) is not None

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        from ..ui import commands, layouts, provisional

        about = _variant_description(cls.bl_idname, properties)
        if commands.is_available(layouts.add_key(properties.layout)):
            return about
        note = provisional.message(commands.catalog(), cls.bl_idname, properties)
        return f"{about}\n{note}" if about and note else (about or note)

    def execute(self, context: Any) -> set[str]:
        from ..ui import commands, layouts, provisional

        if not commands.is_available(layouts.add_key(self.layout)):
            self.report({"INFO"}, provisional.message(
                commands.catalog(), commands.command_idname(self.bl_idname), self.properties))
            return {"CANCELLED"}
        name, appended = layouts.activate_layout(context.window, self.layout)
        if appended and name == layouts.main_name():
            self.report({"INFO"}, tr("The Geoblender workspace has been added to this file"))
        elif appended:
            self.report({"INFO"}, tr("The layout «{name}» has been added to this file",
                                     name=name))
        return {"FINISHED"}


def _layout_workspace(operator: Any, context: Any) -> Any:
    """El espacio sobre el que actúa Quitar o Restaurar (o ``None``, y lo dice)."""
    from ..ui import layouts

    workspace = layouts.target_workspace(context, operator.workspace)
    if workspace is None and operator.workspace:
        operator.report({"WARNING"}, tr("There is no workspace «{name}»",
                                        name=operator.workspace))
    return workspace


class GEOBLENDER_OT_ui_remove_layout(bpy.types.Operator):
    """Delete only this workspace, never data; the main one cannot be removed"""

    bl_idname = "geoblender.ui_remove_layout"
    bl_label = "Remove this layout"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    workspace: StringProperty(name="Workspace", default="", options={"SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return getattr(context, "window", None) is not None

    def execute(self, context: Any) -> set[str]:
        from ..ui import layouts

        workspace = _layout_workspace(self, context)
        if workspace is None and self.workspace:
            return {"CANCELLED"}
        problem = layouts.remove_problem(workspace)
        if problem:
            self.report({"WARNING"}, problem)
            return {"CANCELLED"}
        name = workspace.name
        layouts.remove(workspace)
        self.report({"INFO"}, tr("The layout «{name}» has been removed; the data stay in "
                                 "the file", name=name))
        return {"FINISHED"}


class GEOBLENDER_OT_ui_restore_layout(bpy.types.Operator):
    """Append it again from the Geoblender resources"""

    bl_idname = "geoblender.ui_restore_layout"
    bl_label = "Restore the layout"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    workspace: StringProperty(name="Workspace", default="", options={"SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return getattr(context, "window", None) is not None

    def execute(self, context: Any) -> set[str]:
        from ..ui import layouts

        workspace = _layout_workspace(self, context)
        if workspace is None and self.workspace:
            return {"CANCELLED"}
        problem = layouts.restore_problem(workspace)
        if problem:
            self.report({"WARNING"}, problem)
            return {"CANCELLED"}
        name = workspace.name
        layouts.restore(workspace)
        self.report({"INFO"}, tr("The layout «{name}» has been restored", name=name))
        return {"FINISHED"}


def _command_line_search(_operator: Any, _context: Any, edit_text: str) -> list[str]:
    """La lista del campo de la línea de comandos al escribir (``bl.ui.command_line``)."""
    from ..ui import command_line  # diferido, como el conmutador

    return command_line.suggestions(edit_text)


class GEOBLENDER_OT_ui_open_command_line(bpy.types.Operator):
    """Find any command by its name in Spanish or English, its alias or its entry"""

    bl_idname = "geoblender.ui_open_command_line"
    bl_label = "Command line"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    query: StringProperty(  # type: ignore[valid-type]
        name="Command",
        default="",
        search=_command_line_search,
        search_options={"SUGGESTION"},
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return gate.poll(cls, context)

    def invoke(self, context: Any, event: Any) -> set[str]:
        if self.query:
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(
            self, width=800, title=self.bl_label, confirm_text=tr("Run"), translate=False,
        )

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.activate_init = True  # se escribe sin tener que pulsar en el campo
        layout.prop(self, "query", text="", icon="VIEWZOOM", translate=False)
        hint = layout.row()
        hint.active = False
        hint.label(text=tr("Name in Spanish or English, alias or entry (R-38)"),
                   translate=False)

    def execute(self, context: Any) -> set[str]:
        from ..ui import command_line

        outcome = command_line.run(context, self.query)
        if outcome.message:
            self.report({outcome.level or "INFO"}, outcome.message)
        return outcome.status


class _HelpSheet:
    """Una hoja de ayuda (``bl.ui.help``): sin ``printable``, una ventana emergente con
    la hoja y el botón de su versión imprimible; con él, la página HTML en la carpeta de
    datos de la extensión, abierta en el navegador."""

    kind = ""
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    printable: BoolProperty(name="Printable", default=False, options={"SKIP_SAVE"})  # type: ignore[valid-type]

    def invoke(self, context: Any, event: Any) -> set[str]:
        return self.execute(context)

    def execute(self, context: Any) -> set[str]:
        from ..ui import help as ui_help

        if self.printable:
            path = ui_help.write_sheet(self.kind)
            if not ui_help.open_page(path):
                self.report({"INFO"}, tr("Page written in {path}", path=str(path)))
            return {"FINISHED"}
        if bpy.app.background:
            return {"FINISHED"}
        return context.window_manager.invoke_popup(self, width=1000)

    def draw(self, context: Any) -> None:
        from ..ui import commands
        from ..ui import help as ui_help

        layout = self.layout
        ui_help.draw_sheet(layout, self.kind)
        props = layout.operator(commands.command_idname(self.bl_idname),
                                text=tr("Printable version…"),
                                icon="FILE_TEXT", translate=False)
        props.printable = True


class GEOBLENDER_OT_ui_show_shortcuts(_HelpSheet, bpy.types.Operator):
    """The shortcuts of Geoblender, printable"""

    bl_idname = "geoblender.ui_show_shortcuts"
    bl_label = "Shortcut sheet"
    kind = "shortcuts"


class GEOBLENDER_OT_ui_show_aliases(_HelpSheet, bpy.types.Operator):
    """The aliases that the command line (F10) understands"""

    bl_idname = "geoblender.ui_show_aliases"
    bl_label = "Command line aliases"
    kind = "aliases"


class GEOBLENDER_OT_ui_show_glossary(_HelpSheet, bpy.types.Operator):
    """Terms of RecMin and other programs and their standard term"""

    bl_idname = "geoblender.ui_show_glossary"
    bl_label = "Glossary"
    kind = "glossary"


class GEOBLENDER_OT_ui_run_diagnostics(bpy.types.Operator):
    """Blender, extension, PROJ, compute engine, shortcuts and icons"""

    bl_idname = "geoblender.ui_run_diagnostics"
    bl_label = "Installation diagnostics"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    copy: BoolProperty(name="Copy", default=False, options={"SKIP_SAVE"})  # type: ignore[valid-type]

    def invoke(self, context: Any, event: Any) -> set[str]:
        return self.execute(context)

    def execute(self, context: Any) -> set[str]:
        from ..ui import help as ui_help

        if self.copy:
            context.window_manager.clipboard = ui_help.diagnostics_text()
            self.report({"INFO"}, tr("Diagnostics copied to the clipboard"))
            return {"FINISHED"}
        if bpy.app.background:
            print(ui_help.diagnostics_text())
            return {"FINISHED"}
        return context.window_manager.invoke_popup(self, width=720)

    def draw(self, context: Any) -> None:
        from ..ui import commands
        from ..ui import help as ui_help

        layout = self.layout
        ui_help.draw_rows(layout, self.bl_label, ui_help.diagnostics())
        props = layout.operator(commands.command_idname(self.bl_idname),
                                text=tr("Copy to the clipboard"),
                                icon="COPYDOWN", translate=False)
        props.copy = True


class GEOBLENDER_OT_ui_show_about(bpy.types.Operator):
    """Version, licence GPL-3.0-or-later and components"""

    bl_idname = "geoblender.ui_show_about"
    bl_label = "About Geoblender"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    def invoke(self, context: Any, event: Any) -> set[str]:
        return self.execute(context)

    def execute(self, context: Any) -> set[str]:
        if bpy.app.background:
            return {"FINISHED"}
        return context.window_manager.invoke_popup(self, width=720)

    def draw(self, context: Any) -> None:
        from ..ui import help as ui_help

        ui_help.draw_rows(self.layout, self.bl_label, ui_help.about())


class GEOBLENDER_OT_ui_show_preferences(bpy.types.Operator):
    """Language, titles of the bar, quick access row and status bar"""

    bl_idname = "geoblender.ui_show_preferences"
    bl_label = "Geoblender preferences…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[str]:
        if not bpy.app.background:  # sin interfaz no hay ventana de preferencias
            from .. import ADDON_PACKAGE

            bpy.ops.preferences.addon_show(module=ADDON_PACKAGE)
        return {"FINISHED"}


class GEOBLENDER_OT_ui_set_language(bpy.types.Operator):
    """Language of the Geoblender interface, independent of the Blender one"""

    bl_idname = "geoblender.ui_set_language"
    bl_label = "Geoblender language"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    language: EnumProperty(name="Language", items=LANGUAGE_ITEMS, default="ES")  # type: ignore[valid-type]

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        return _variant_description(cls.bl_idname, properties)

    def execute(self, context: Any) -> set[str]:
        from ..ui import commands, i18n as ui_i18n

        prefs = commands.preferences()
        if prefs is None:
            ui_i18n.schedule(LANGUAGES[self.language])
            return {"FINISHED"}
        if prefs.language != self.language:
            prefs.language = self.language  # su update deja el cambio pendiente
            try:
                context.preferences.is_dirty = True  # Blender la guardará con las demás
            except (AttributeError, TypeError):
                pass
        return {"FINISHED"}


class GEOBLENDER_OT_ui_repair_interface(bpy.types.Operator):
    """Install the top bar, the shortcuts and the icons again"""

    bl_idname = "geoblender.ui_repair_interface"
    bl_label = "Repair the interface"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[str]:
        from .. import ui  # diferido, como el conmutador

        mode = ui.repair()
        if mode == "compat":
            self.report({"WARNING"}, tr("Geoblender interface in compatibility mode"))
        else:
            self.report({"INFO"}, tr("Geoblender interface repaired"))
        return {"FINISHED"}


# En orden de registro.
classes: tuple[type, ...] = (
    GEOBLENDER_OT_ui_toggle_mode,
    GEOBLENDER_OT_ui_call_pie,
    GEOBLENDER_OT_ui_call_panel,
    GEOBLENDER_OT_ui_call_context_menu,
    GEOBLENDER_OT_ui_toggle_context_pin,
    GEOBLENDER_OT_ui_show_context_panel,
    GEOBLENDER_OT_ui_set_view,
    GEOBLENDER_OT_ui_frame_work_window,
    GEOBLENDER_OT_ui_store_view,
    GEOBLENDER_OT_ui_recall_view,
    GEOBLENDER_OT_ui_edit_legend,
    GEOBLENDER_OT_ui_edit_data_filter,
    GEOBLENDER_OT_ui_toggle_quick_access_row,
    GEOBLENDER_OT_ui_add_layout,
    GEOBLENDER_OT_ui_remove_layout,
    GEOBLENDER_OT_ui_restore_layout,
    GEOBLENDER_OT_ui_open_command_line,
    GEOBLENDER_OT_ui_show_shortcuts,
    GEOBLENDER_OT_ui_show_aliases,
    GEOBLENDER_OT_ui_show_glossary,
    GEOBLENDER_OT_ui_run_diagnostics,
    GEOBLENDER_OT_ui_show_about,
    GEOBLENDER_OT_ui_show_preferences,
    GEOBLENDER_OT_ui_set_language,
    GEOBLENDER_OT_ui_repair_interface,
)
