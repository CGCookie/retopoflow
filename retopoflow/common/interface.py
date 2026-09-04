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


def draw_tool_settings(context : Context, layout : UILayout, *, tool_props=None, masking : bool = False, snapping : bool = True):
    '''
    tool_props: the tool's operator properties, drawn as the Tweaking popover. Pass None for the
                brush tools, which are the tweaking tools and so have nothing to hand off to.
    masking:    draw the masking controls inline instead of leaving them to Tweaking. Brush tools.
    snapping:   draw the Snapping popover.
    '''
    # deferred: rfpanels imports back out of this module
    from ..preferences import RF_Prefs
    from ..rfpanels.mirror_panel import draw_mirror_popover
    from ..rfpanels.tweaking_panel import draw_tweaking_popover

    prefs = RF_Prefs.get_prefs(context)
    props_scene = context.scene.retopoflow

    if masking:
        if prefs.expand_masking:
            draw_line_separator(layout)
            layout.row(heading='Selected:', align=True).prop(props_scene, 'mask_selected', expand=True, icon_only=True)
            layout.separator()
            layout.row(heading='Boundary:', align=True).prop(props_scene, 'mask_boundary', expand=True, icon_only=True)
            # layout.prop(props_scene, 'mask_symmetry', text="Symmetry")  # TODO: Implement
            layout.separator()
            if prefs.setup_pinning:
                row = layout.row(align=True)
                row.operator('retopoflow.pinverts', text='', icon='PINNED')
                row.operator('retopoflow.unpinverts', text='', icon='UNPINNED')
                row.popover('RF_PT_Pinning', text='Masking')
            else:
                layout.popover('RF_PT_Pinning', text='Masking')
        else:
            layout.popover('RF_PT_Masking')

    draw_line_separator(layout)

    if tool_props is not None:
        draw_tweaking_popover(context, layout, tool_props)
    row = layout.row(align=True)
    row.popover('RF_PT_MeshCleanup', text='Clean Up')
    row.operator('retopoflow.meshcleanup', text='', icon='TRIA_RIGHT').affect_all = False
    draw_mirror_popover(context, layout)
    if snapping:
        layout.popover('RF_PT_Snapping', text='Snapping')
    if prefs.expand_offset:
        layout.prop(props_scene, 'retopo_offset', text='Overlay Offset')
    layout.popover('RF_PT_General', text='', icon='OPTIONS')
    layout.popover('RF_PT_Help', text='', icon='INFO_LARGE' if bpy.app.version >= (4,3,0) else 'INFO')


def draw_tool_panels(context : Context, layout : UILayout, *, tweaking : bool = True, snapping : bool = True, guide_loops : bool = False):
    '''
    tweaking:    draw the Tweaking panel. Off for the brush tools, same as tool_props above.
    snapping:    draw the Snapping panel.
    guide_loops: include the guide loops setting inside Snapping. Brush tools only.
    '''
    # deferred: rfpanels imports back out of this module
    from ..rfpanels.general_panel import draw_general_panel
    from ..rfpanels.help_panel import draw_help_panel
    from ..rfpanels.masking_panel import draw_masking_panel
    from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
    from ..rfpanels.mirror_panel import draw_mirror_panel
    from ..rfpanels.rfpanel_snapping import draw_snapping_panel
    from ..rfpanels.tweaking_panel import draw_tweaking_panel

    if tweaking:
        draw_tweaking_panel(context, layout)
    draw_masking_panel(context, layout)
    draw_cleanup_panel(context, layout)
    draw_mirror_panel(context, layout)
    if snapping:
        # One idname across every tool, matching the other shared panels, so open/closed state
        # survives a tool switch. The tools used to each pass their own.
        draw_snapping_panel(context, layout, idname='snapping_panel', guide_loops=guide_loops)
    draw_general_panel(context, layout)
    draw_help_panel(context, layout)


def _region_width_is_layout_width(context : Context) -> bool:
    """ Whether context.region.width describes the space the layout actually gets. """
    region, space = context.region, context.space_data
    if not region: return False
    if region.type == 'UI': return True
    return region.type == 'WINDOW' and space is not None and space.type == 'PROPERTIES'


def draw_expandable_enum(context : Context, layout : UILayout, props : OperatorProperties, prop_name:str, breakpoint:int=750, text:str|None=None):
    if text == None:
        text = props.bl_rna.properties[prop_name].name

    if not _region_width_is_layout_width(context) or context.region.width < breakpoint:
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
