import bpy
from bpy.types import Context, UILayout, OperatorProperties, KeyMapItem

def draw_keymap_options(self, layout : UILayout, keymap_item : KeyMapItem | None, title: str, in_RF_tools: str, trigger_prop: str = 'pie_tool_context'):
    ''' in_RF_tools: 'optional' shows the artist's own Triggers-From dropdown (trigger_prop);
    'only' or 'never' means the hotkey's tool context is fixed, so show a greyed-out label instead. '''
    if not keymap_item:
        return
    split = layout.split(factor=0.25)
    label = split.row()
    label.alignment = 'RIGHT'
    label.label(text=title)
    row = split.row(align=True)
    row.prop(keymap_item, 'active', text='', icon_only=False, toggle=False)
    sub_split = row.split()
    sub_split.enabled = keymap_item.active
    options = sub_split.split(factor=0.33)
    key = options.row(align=True)
    key.prop(keymap_item, 'type', text='', event=True)
    modifiers = options.row(align=True)
    modifiers.prop(keymap_item, 'shift_ui', toggle=True)
    modifiers.prop(keymap_item, 'ctrl_ui', toggle=True)
    modifiers.prop(keymap_item, 'alt_ui', toggle=True)
    trigger = sub_split.row()
    if in_RF_tools == 'optional':
        trigger.enabled = keymap_item and keymap_item.active
        trigger.prop(self, trigger_prop, text='', expand=False)
    else:
        trigger.enabled = False
        trigger.label(text='Retopoflow Tools' if in_RF_tools == 'only' else 'Non-Retopoflow Tools')


def draw_expandable_enum(context : Context, layout : UILayout, props : OperatorProperties, prop_name:str, breakpoint:int=600, text:str|None=None):
    if text == None:
        text = props.bl_rna.properties[prop_name].name

    if context.region.width < breakpoint or context.region.type == 'TOOL_HEADER':
        layout.prop(props, prop_name, text=text)
    else:
        layout.row().prop(props, prop_name, text=text, expand=True)


def draw_line_separator(layout):
    if bpy.app.version >= (4,2,0):
        return layout.separator(type='LINE')
    else:
        return layout.separator()


def draw_section_indent(context : Context, layout : UILayout):
    if context.region.type != 'TOOL_HEADER':
        if context.region.width > 600:
            layout.label(icon='BLANK1')
        if context.region.width > 1000:
            layout.label(icon='BLANK1')


def draw_section_header(context, layout, text='', icon=''):
    row = layout.row(align=True)
    draw_section_indent(context, row)
    if icon:
        row.label(text=text, icon=icon)
    else:
        row.label(text=text)


def get_temp_windows(context):
    temp_windows = []
    for win in context.window_manager.windows:
        if win.screen.is_temporary:
            temp_windows.append(win)
    return temp_windows


def show_message(message: str, title: str, icon: str = "INFO"):
    def popup_handler(self, context):
        col = self.layout.column(align=True)
        for line in message.split("\n"):
            col.label(text=line)
    bpy.context.window_manager.popup_menu(popup_handler, title=title, icon=icon)


def update_toolbar():
    from ..rftool_base import RFTool_Base
    RFTool_Base.unregister_all()
    RFTool_Base.register_all()
