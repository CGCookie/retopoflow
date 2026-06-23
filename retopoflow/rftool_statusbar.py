'''
Copyright (C) 2026 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, cast
from collections.abc import Sequence

import bpy
from bpy.types import Context, Header, UILayout, KeyMapItem
import platform

from .rfglobals import RFGlobals
from .common.icons import Icon
from .common.accel import SourceCache
from ..addon_common.common.useractions import blenderop_to_kmis, kmi_to_op_properties
from .rftool_base import RFTool_Base



# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #
# MARK: StatusbarYield
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #

class StatusbarYield:
    """
    Temporarily hide RF's custom status bar so Blender can show native operator reports.

    Intercept bmesh.update_edit_mesh in rfcore.register() to track the last time
    RF's own Python code pushed a mesh change.  Built-in C operators (e.g. Merge by Distance,
    Remove Doubles) never call Python's bmesh.update_edit_mesh, so a geometry depsgraph
    update that arrives more than 0.2 s after the last RF mesh write must have come from an
    external operator. We temporarily yield the status bar so its report is visible.

    Detection is skipped while an RF brush operator is mid-stroke (Relax/Tweak actively
    painting), because those tools stamp _last_rf_mesh_update_time continuously and the
    0.2 s threshold would never be exceeded anyway.
    """

    _yield_until: float = 0.0

    @classmethod
    def is_active(cls) -> bool:
        """Return True while the native status bar is being shown in place of RF's bar."""
        return cls._yield_until > time.monotonic()

    @classmethod
    def begin(cls, duration: float = 3.0):
        """
        Start a yield window: schedule the timer that hides the RF bar.
        Sets the deadline first so the timer callback can verify the window is still valid
        if the user cancels between scheduling and firing.
        """
        cls._yield_until = time.monotonic() + duration
        if not bpy.app.timers.is_registered(cls._show_timer):
            bpy.app.timers.register(cls._show_timer, first_interval=0.01)

    @classmethod
    def cancel(cls):
        """
        Cancel an active yield window and unregister any pending timers.
        Does not restore the RF status bar. Callers should call RFCore._update_statusbar()
        if they want an immediate restore.
        """
        cls._yield_until = 0.0
        for fn in (cls._show_timer, cls._restore_timer):
            if bpy.app.timers.is_registered(fn):
                bpy.app.timers.unregister(fn)

    @classmethod
    def _show_timer(cls):
        """bpy.app.timers callback (~10 ms after detection): hide RF bar, schedule restore."""
        RFCore = RFGlobals.RFCore_None
        if not RFCore or not RFCore.is_running or not RFCore.selected_RFTool_idname:
            return None
        if not cls.is_active():
            return None  # yield was cancelled before this timer fired; do nothing
        try:
            bpy.context.workspace.status_text_set(None)
        except Exception as e:
            print(f'RF: could not show native status bar: {e}')
            return None
        if not bpy.app.timers.is_registered(cls._restore_timer):
            # Schedule the restore to fire when the yield window actually expires.
            # Using the remaining time (not a hardcoded constant) avoids over-running
            # when _show_timer itself fires late due to Blender load.
            remaining = max(0.1, cls._yield_until - time.monotonic())
            bpy.app.timers.register(cls._restore_timer, first_interval=remaining)
        return None

    @classmethod
    def _restore_timer(cls):
        """bpy.app.timers callback: restore RF bar once the yield window expires."""
        RFCore = RFGlobals.RFCore_None
        if not RFCore or not RFCore.is_running or not RFCore.selected_RFTool_idname:
            return None
        remaining = cls._yield_until - time.monotonic()
        if remaining > 0.1:
            return remaining + 0.1  # Yield window was extended by a second external op; wait longer
        # Clear the deadline BEFORE calling _update_statusbar so its yield guard does not
        # block re-registration (fixes the "two ops within 100 ms" permanent-blank bug).
        cls._yield_until = 0.0
        try:
            RFCore._update_statusbar(bpy.context)
        except Exception as e:
            print(f'RF: could not restore RF status bar: {e}')
        return None


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #
# MARK: Globals
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #

is_macOS = 'macOS' in platform.platform()


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #
# MARK: Helper Functions
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #

re_status_entry = re.compile(r'((?P<icon>LMB|MMB|RMB): *)?(?P<text>.*)')
status_map_icons : dict[str, str] = {
    'LMB': 'MOUSE_LMB',
    'MMB': 'MOUSE_MMB',
    'RMB': 'MOUSE_RMB',
}
def parse_status_entry(status_entry: str) -> tuple[str, str]:
    match = re_status_entry.match(status_entry)
    if not match:
        return 'NONE', ''
    icon = match.group('icon')
    text = match.group('text')
    return status_map_icons.get(icon, icon), text


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #
# MARK: SharedStatusbarKeymap
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #

'''
These shared or generic keymaps will be drawn in the statusbar, right-aligned and after the active tool keymaps.
- 'context' for all these keymaps is 'init' by default.
- 'op_id': if not set or set to None, set 'event_type' as a string for the EventType.
'''
@dataclass
class SharedStatusbarKeymap:
    label: str | Callable[[Context], str]
    icons: list[str] = field(default_factory=list)
    op_id: str | None = None
    filter_op_props: dict[str, ...] | None = None  # to filter keymap items by op properties
    poll_tools: Sequence[str] | None = None  # list of tool idnames to poll for (in upper-case!)
    poll_fn: Callable[[Context], bool] | None = None
    context: str | tuple[str, ...] = 'init'  # 'init' by default
    _tags: set[str] = field(default_factory=set)

    def poll(self, context: Context, active_tool_idname: str | None = None) -> bool:
        if self.poll_tools is not None and active_tool_idname is not None:
            if 'INVERT_POLL_TOOLS' in self._tags:
                return active_tool_idname not in self.poll_tools
            else:
                return active_tool_idname in self.poll_tools
        if self.poll_fn is not None:
            return self.poll_fn(context)
        return True

    def get_label(self, context: Context) -> str:
        if isinstance(self.label, str):
            return self.label
        elif callable(self.label):
            return self.label(context)
        else:
            return ''

    def get_icons(self) -> list[str]:
        if len(self.icons) > 0:
            # used cached icons
            return self.icons
        icons: list[str] = []
        kmi = self.get_kmi()
        if kmi is None:
            return []
        for mod_key in ('ctrl', 'shift', 'alt'):
            if getattr(kmi, mod_key, False):
                icons.append(f'EVENT_{mod_key.upper()}')
        if kmi.type:
            event_type: str = kmi.type
            event_value: str = kmi.value
            if len(event_type) == 1 and 'A' <= event_type <= 'Z':
                icons.append(f'EVENT_{kmi.type.upper()}')
            elif len(event_type) == 2 and event_type[0] == 'F':
                icons.append(f'EVENT_{kmi.type.upper()}')
            elif event_type.endswith('MOUSE') and not event_type.startswith(('M', 'W')):
                mouse_button_key: str = event_type[0].upper() # L->'LMB', M->'MMB', R->'RMB'
                icon = f'MOUSE_{mouse_button_key}MB'
                if event_value == 'DOUBLE_CLICK' and mouse_button_key == 'L':
                    if bpy.app.version >= (4, 3, 0):
                        # MOUSE_LMB_2X did not show up until Blender 4.3
                        # https://docs.blender.org/api/4.2/bpy_types_enum_items/icon_items.html
                        # https://docs.blender.org/api/4.3/bpy_types_enum_items/icon_items.html
                        icon += '_2X'
                elif event_value == 'CLICK_DRAG':
                    icon += '_DRAG'
                icons.append(icon)
            elif 'WHEEL' in event_type:
                icons.append('MOUSE_MMB_SCROLL')

        self.icons = icons
        return icons

    def add_tag(self, tag: str):
        self._tags.add(tag)
        return self

    def invert_poll_tools(self):
        return self.add_tag('INVERT_POLL_TOOLS')

    def set_modifiers(self, ctrl: bool | int = False, shift: bool | int = False, alt: bool | int = False):
        if alt:
            self.icons.insert(0, 'EVENT_ALT')
        if shift:
            self.icons.insert(0, 'EVENT_SHIFT')
        if ctrl:
            self.icons.insert(0, 'EVENT_CTRL')
        return self

    def get_kmi(self) -> KeyMapItem | None:
        if self.op_id is None:
            return None
        kmis = blenderop_to_kmis(self.op_id)
        if not kmis:
            return None
        if self.filter_op_props is None:
            kmi = list(kmis)[0]
            if not kmi.active:
                return None
            return kmi
        filtered_kmis = set()
        for kmi in kmis:
            op, op_props = kmi_to_op_properties(kmi)
            if kmi.active and all(op_props.get(k, None) == v for k, v in self.filter_op_props.items()):
                filtered_kmis.add(kmi)
        if not filtered_kmis:
            return None
        kmi = list(filtered_kmis)[0]
        return kmi

    def get_op_props(self):
        kmi = self.get_kmi()
        if kmi is None:
            return None
        return kmi_to_op_properties(kmi)

    def _draw_icons(self, context: Context, layout: UILayout):
        sub = layout.row(align=True)
        for icon in self.get_icons():
            sub.label(text='', icon=icon)
            if icon == 'EVENT_CTRL':
                sub.separator(factor=1.5)
            elif icon == 'EVENT_ALT':
                sub.separator(factor=1)
        sub.label(text=self.get_label(context))
        layout.separator()

    def draw(self, context: Context, active_tool_idname: str, km_context: str, layout: UILayout):
        if self.context is None:
            return
        if isinstance(self.context, (tuple, list)):
            if km_context not in self.context:
                return
        else:
            if km_context != self.context:
                return
        if not self.poll(context, active_tool_idname):
            return
        if self.op_id and not self.get_kmi():
            return
        self._draw_icons(context, layout)


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #
# MARK: Shared Keymaps Definition
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #

SHARED_STATUSBAR_KEYMAPS__PRE_TOOL = (
    SharedStatusbarKeymap(label="Tweak", icons=['MOUSE_LMB_DRAG'], poll_tools=('TWEAK', 'RELAX')).invert_poll_tools(),
)

SHARED_STATUSBAR_KEYMAPS__POST_TOOL = (
    SharedStatusbarKeymap(
        label="Tweak Brush",
        icons=['EVENT_CTRL', 'EVENT_SHIFT', 'MOUSE_LMB_DRAG'],
        poll_tools = ('TWEAK')
    ).invert_poll_tools(),

    SharedStatusbarKeymap(
        label="Relax Brush",
        icons=['EVENT_SHIFT', 'MOUSE_LMB_DRAG'],
        poll_tools = ('RELAX')
    ).invert_poll_tools(),

    SharedStatusbarKeymap(
        label="Topo Rotate",
        icons=['EVENT_ALT', 'EVENT_R'],
        poll_tools = ('CONTOURS')
    ).invert_poll_tools(),

    SharedStatusbarKeymap(
        label="RF Pie Menu",
        op_id="3D View | wm.call_menu_pie",
        filter_op_props={'name': 'RF_MT_Tools'}
    ),

    SharedStatusbarKeymap(
        label="Open Docs",
        op_id="3D View | retopoflow.launch_help"
    ),

    SharedStatusbarKeymap(
        label="Report Issue",
        op_id="3D View | retopoflow.launch_newissue"
    ),

    # SharedStatusbarKeymap(label="Knife", icons=['EVENT_K']), # static version
    SharedStatusbarKeymap( # dynamic version
        label="Knife",
        op_id="Mesh | mesh.knife_tool",
        filter_op_props={'only_selected': False}
    ),

    # SharedStatusbarKeymap(label="Toggle Proportional Editing", icons=['EVENT_O']), # static version
    SharedStatusbarKeymap( # dynamic version
        label=lambda context: f"{'Disable' if context.scene.tool_settings.use_proportional_edit else 'Enable'} Proportional Editing",
        op_id="Mesh | wm.context_toggle",
        filter_op_props={'data_path': 'tool_settings.use_proportional_edit'},
        poll_tools=('POLYSTRIPS', 'STROKES')
    ),
)


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #
# MARK: Draw Statusbar
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #

def draw_rftool_statusbar(statusbar: Header, context: Context, tool: type[RFTool_Base]):
    RFCore = RFGlobals.RFCore_None
    if not RFCore: return

    if not statusbar.layout: return
    layout: UILayout = statusbar.layout

    # Cache build progress gets exclusive use of the status bar while rebuilding
    if SourceCache.building and hasattr(layout, 'progress'):
        layout.separator_spacer()
        row = layout.row(align=True)
        row.separator_spacer()
        prog = row.row(align=True)
        prog.scale_x = 1.8
        prog.progress(factor=SourceCache.progress, text=f'Source Cache {SourceCache.progress * 100:.0f}%', type='BAR')
        prog.operator('retopoflow.cancel_source_cache_rebuild', text='', icon='X')
        row.separator_spacer()
        layout.separator_spacer()
        return

    # Selected Tool Icon.
    # draw_rftool_icon(tool, layout, scale=0.9)
    # layout.separator()

    row = layout.row(align=True)

    km_status_override = RFCore.km_status_override
    if km_status_override:
        if isinstance(km_status_override, tuple | list):
            for status in km_status_override:
                icon, text = parse_status_entry(status)
                row.label(text=text, icon=icon) # pyright: ignore[reportArgumentType]
                row.separator()
        elif isinstance(km_status_override, str):
            icon, text = parse_status_entry(km_status_override)
            row.label(text=text, icon=icon) # pyright: ignore[reportArgumentType]
        else:
            print(f'Unknown type of km_status_override: {type(km_status_override)}')
        return

    km_context = RFCore.km_context
    if km_context is None:
        return

    active_tool_idname = tool.rf_idname.split('.')[-1].upper()
    for km in SHARED_STATUSBAR_KEYMAPS__PRE_TOOL:
        km.draw(context, active_tool_idname, km_context, row)

    for km in tool.bl_keymap:
        op_id, km_event, op_props = km
        if op_props is None: continue
        if 'km_context' not in op_props: continue
        if isinstance(op_props['km_context'], (tuple, list)):
            if km_context not in op_props['km_context']:
                continue
        else:
            if op_props['km_context'] != km_context:
                continue

        km_poll = op_props.get('km_poll', None)
        if isinstance(km_poll, Callable) and not km_poll(context): continue

        op_id = op_id.split('.')[-1]

        km_label = op_props.get('km_label', None)
        if not isinstance(km_label, str):
            op = getattr(bpy.ops.retopoflow, op_id, None)
            if not op or not hasattr(op, 'get_rna_type'): continue
            try:
                op_rna = op.get_rna_type()
            except Exception as e:
                print(f'Caught exception while trying to get RNA type for {op_id}')
                print(f'  {e}')
                continue
            km_label = str(op_rna.name)

        event_type = km_event['type']
        event_value = km_event['value']
        if not isinstance(event_type, str) or not isinstance(event_value, str): continue

        for mod_key in ('ctrl', 'shift', 'alt'):
            if mod_key in km_event and bool(km_event[mod_key]) or f'LEFT_{mod_key.upper()}' == event_type:
                row.label(text='', icon=f'EVENT_{mod_key.upper()}') # pyright: ignore[reportArgumentType]
                if is_macOS:
                    continue
                elif mod_key == 'ctrl':
                    row.separator(factor=1.5)
                elif mod_key == 'alt':
                    row.separator(factor=1)
        if len(event_type) == 1 and 'A' <= event_type <= 'Z':
            row.label(text='', icon=f'EVENT_{event_type.upper()}') # pyright: ignore[reportArgumentType]
        if event_type.endswith('MOUSE') and not event_type.startswith(('M', 'W')):
            mouse_button_key: str = event_type[0].upper() # L->'LMB', M->'MMB', R->'RMB'
            icon = f'MOUSE_{mouse_button_key}MB'
            if event_value == 'DOUBLE_CLICK' and mouse_button_key == 'L':
                if bpy.app.version >= (4, 3, 0):
                    # MOUSE_LMB_2X did not show up until Blender 4.3
                    # https://docs.blender.org/api/4.2/bpy_types_enum_items/icon_items.html
                    # https://docs.blender.org/api/4.3/bpy_types_enum_items/icon_items.html
                    icon += '_2X'
            elif event_value == 'CLICK_DRAG':
                icon += '_DRAG'
            row.label(text='', icon=icon) # pyright: ignore[reportArgumentType]
        if 'WHEEL' in event_type:
            if bpy.app.version >= (4, 3, 0):
                # MOUSE_MMB_SCROLL did not show up until Blender 4.3
                # https://docs.blender.org/api/4.2/bpy_types_enum_items/icon_items.html
                # https://docs.blender.org/api/4.3/bpy_types_enum_items/icon_items.html
                row.label(text='', icon='MOUSE_MMB_SCROLL')

        row.label(text=km_label)
        row.separator()

    if len(SHARED_STATUSBAR_KEYMAPS__POST_TOOL) > 0:
        if context.window.width < 1600:
            Icon.SEPARATOR.draw(row, left_space=1.0, right_space=1.0)
        else:
            layout.separator_spacer()

    row = layout.row(align=True)
    for km in SHARED_STATUSBAR_KEYMAPS__POST_TOOL:
        km.draw(context, active_tool_idname, km_context, row)

    layout.separator_spacer()

    layout.label(text=context.screen.statusbar_info())
