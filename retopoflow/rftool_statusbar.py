import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Dict, Any, Tuple, List, TYPE_CHECKING

import bpy
import platform

from .common.icons import draw_rftool_icon, Icon
from ..addon_common.common.useractions import blenderop_to_kmis, kmi_to_op_properties
from .rftool_base import RFTool_Base
from .preferences import RF_Prefs


if TYPE_CHECKING:
    from .rfcore import RFCore


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #
# MARK: Globals
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #

is_macOS = 'macOS' in platform.platform()


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #
# MARK: Helper Functions
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #

re_status_entry = re.compile(r'((?P<icon>LMB|MMB|RMB): *)?(?P<text>.*)')
status_map_icons = {
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
    label: str | Callable[[bpy.types.Context], str]
    icons: List[str] = field(default_factory=list)
    op_id: Optional[str] = None
    filter_op_props: Optional[Dict[str, Any]] = None  # to filter keymap items by op properties
    poll_tools: Optional[Tuple[str, ...]] = None  # list of tool idnames to poll for (in upper-case!)
    poll_fn: Optional[Callable[[bpy.types.Context], bool]] = None
    context: str | Tuple[str, ...] = 'init'  # 'init' by default
    _tags: set[str] = field(default_factory=set)

    def poll(self, context: bpy.types.Context, active_tool_idname: Optional[str] = None) -> bool:
        if self.poll_tools is not None and active_tool_idname is not None:
            if 'INVERT_POLL_TOOLS' in self._tags:
                return active_tool_idname not in self.poll_tools
            else:
                return active_tool_idname in self.poll_tools
        if self.poll_fn is not None:
            return self.poll_fn(context)
        return True

    def get_label(self, context: bpy.types.Context) -> str:
        if isinstance(self.label, str):
            return self.label
        elif callable(self.label):
            return self.label(context)
        else:
            return ''

    def get_icons(self) -> List[str]:
        if len(self.icons) > 0:
            # used cached icons
            return self.icons
        icons: List[str] = []
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

    def get_kmi(self) -> Optional[bpy.types.KeyMapItem]:
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

    def _draw_icons(self, context: bpy.types.Context, layout: bpy.types.UILayout):
        sub = layout.row(align=True)
        for icon in self.get_icons():
            sub.label(text='', icon=icon)
            if icon == 'EVENT_CTRL':
                sub.separator(factor=1.5)
            elif icon == 'EVENT_ALT':
                sub.separator(factor=1)
        sub.label(text=self.get_label(context))
        layout.separator()

    def draw(self, context: bpy.types.Context, active_tool_idname: str, km_context: str, layout: bpy.types.UILayout):
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
    SharedStatusbarKeymap(label="Tweak Brush", icons=['EVENT_CTRL', 'EVENT_SHIFT', 'MOUSE_LMB_DRAG'], poll_tools = ('TWEAK')).invert_poll_tools(),

    SharedStatusbarKeymap(label="Relax Brush", icons=['EVENT_SHIFT', 'MOUSE_LMB_DRAG'], poll_tools = ('RELAX')).invert_poll_tools(),

    SharedStatusbarKeymap(label="Topo Rotate", icons=['EVENT_ALT', 'EVENT_R'], poll_tools = ('CONTOURS')).invert_poll_tools(),

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

def draw_rftool_statusbar(statusbar: bpy.types.Header, context: bpy.types.Context, tool: RFTool_Base, rfc: 'RFCore'):
    layout: bpy.types.UILayout = statusbar.layout

    # Selected Tool Icon.
    # draw_rftool_icon(tool, layout, scale=0.9)
    # layout.separator()

    row = layout.row(align=True)

    km_status_override = rfc.km_status_override
    if km_status_override:
        if isinstance(km_status_override, (tuple, list)):
            for status in km_status_override:
                icon, text = parse_status_entry(status)
                row.label(text=text, icon=icon)
                row.separator()
        elif isinstance(km_status_override, str):
            icon, text = parse_status_entry(km_status_override)
            row.label(text=text, icon=icon)
        else:
            print(f'Unknown type of km_status_override: {type(km_status_override)}')
        return

    km_context = rfc.km_context
    if km_context is None:
        return

    active_tool_idname = tool.rf_idname.split('.')[-1].upper()
    for km in SHARED_STATUSBAR_KEYMAPS__PRE_TOOL:
        km.draw(context, active_tool_idname, km_context, row)

    for km in tool.bl_keymap:
        op_id, km_event, op_props = km
        if op_props is None:
            continue
        if 'km_context' not in op_props:
            continue
        if isinstance(op_props['km_context'], (tuple, list)):
            if km_context not in op_props['km_context']:
                continue
        else:
            if op_props['km_context'] != km_context:
                continue

        if 'km_poll' in op_props:
            if not op_props['km_poll'](context):
                continue

        op_id = op_id.split('.')[-1]

        km_label = op_props.get('km_label', None)
        if km_label is None:
            op = getattr(bpy.ops.retopoflow, op_id, None)
            if not op or not hasattr(op, 'get_rna_type'): continue
            try:
                op_rna = op.get_rna_type()
            except Exception as e:
                print(f'Caught exception while trying to get RNA type for {op_id}')
                print(f'  {e}')
                continue
            km_label = op_rna.name

        # print(f'{op_id=} {km_event=} {op_props=}')
        if not isinstance(km_event, dict): continue
        event_type: str = km_event['type']
        event_value: str = km_event['value']

        for mod_key in ('ctrl', 'shift', 'alt'):
            if mod_key in km_event and bool(km_event[mod_key]) or f'LEFT_{mod_key.upper()}' == event_type:
                row.label(text='', icon=f'EVENT_{mod_key.upper()}')
                if is_macOS:
                    continue
                elif mod_key == 'ctrl':
                    row.separator(factor=1.5)
                elif mod_key == 'alt':
                    row.separator(factor=1)
        if len(event_type) == 1 and 'A' <= event_type <= 'Z':
            row.label(text='', icon=f'EVENT_{event_type.upper()}')
        if event_type.endswith('MOUSE') and not event_type.startswith(('M', 'W')):
            mouse_button_key: str = event_type[0].upper() # L->'LMB', M->'MMB', R->'RMB'
            icon = f'MOUSE_{mouse_button_key}MB'
            if bpy.app.version >= (4, 3, 0):
                if event_value == 'DOUBLE_CLICK' and mouse_button_key == 'L':
                    icon += '_2X'
            elif event_value == 'CLICK_DRAG':
                icon += '_DRAG'
            row.label(text='', icon=icon)
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
