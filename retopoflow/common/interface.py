import bpy


def draw_keymap_options(layout, keymap_item):
    if not keymap_item:
        return
    row = layout.row(align=True)
    row.prop(keymap_item, 'active', text='', icon_only=False, toggle=False)
    split = row.split()
    split.enabled = keymap_item.active
    key = split.row(align=True)
    key.prop(keymap_item, 'type', text='', event=True)
    modifiers = split.row(align=True)
    modifiers.prop(keymap_item, 'shift_ui', toggle=True)
    modifiers.prop(keymap_item, 'ctrl_ui', toggle=True)
    modifiers.prop(keymap_item, 'alt_ui', toggle=True)


def draw_line_separator(layout):
    if bpy.app.version >= (4,2,0):
        return layout.separator(type='LINE')
    else:
        return layout.separator()


def draw_section_indent(context, layout):
    if context.region.type != 'TOOL_HEADER':
        if context.region.width > 350:
            layout.label(icon='BLANK1')
        if context.region.width > 570:
            layout.label(icon='BLANK1')


def draw_section_header(context, layout, text='', icon=''):
    row = layout.row(align=True)
    draw_section_indent(context, row)
    if icon:
        row.label(text=text, icon=icon)
    else:
        row.label(text=text)


def update_toolbar(self, context):
    from ..rftool_base import RFTool_Base
    RFTool_Base.unregister_all()
    RFTool_Base.register_all()


def show_message(message: str, title: str, icon: str = "INFO"):
    def popup_handler(self, context):
        col = self.layout.column(align=True)
        for line in message.split("\n"):
            col.label(text=line)
    bpy.context.window_manager.popup_menu(popup_handler, title=title, icon=icon)
