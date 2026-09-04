import bpy, os
from math import degrees, radians
from bpy.types import Context, Menu, OperatorProperties, UILayout
from bpy.utils import previews

from ..common.icons import Icon
from ..common.operator import RFRegisterClass
from ..rftool_polypen.polypen import PolyPen_Insert_Modes
from ..rftool_patches.patches import USE_NEW_PATCHES
from ..rftool_legacy_patches.legacy_patches_logic import LegacyPatches_Logic
from .tool_options_panel import RFMenu_PT_ToolOptions, has_tool_options

PATCHES_IDNAME = 'retopoflow.patches' if USE_NEW_PATCHES else 'retopoflow.legacy_patches'
PATCHES_SWITCH_IDNAME = 'retopoflow.switch_to_patches' if USE_NEW_PATCHES else 'retopoflow.switch_to_legacy_patches'


class RFOperator_SetToolProp(RFRegisterClass, bpy.types.Operator):
    bl_idname : str = 'retopoflow.set_tool_prop'
    bl_label : str = 'Set Tool Property'
    bl_description : str = 'Set a property of the active RetopoFlow tool'
    bl_options : set[str] = {'INTERNAL'}

    prop: bpy.props.StringProperty(
        name='Property',
        description='Name of the property on the active tool to set',
    )
    value: bpy.props.FloatProperty(
        name='Value',
        description='Value to set the property to, or to offset it by when Relative is on',
    )
    relative: bpy.props.BoolProperty(
        name='Relative',
        description='Add Value to the current setting instead of replacing it',
        default=False,
    )

    @classmethod
    def description(cls, context : Context, properties) -> str:
        # The step buttons are icons, so the value they set only shows up here
        props = rftool_props(context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False))
        rna = props.bl_rna.properties.get(properties.prop) if props else None
        if rna is None: return cls.bl_description
        return f'Set {rna.name} to {_label_for(rna, properties.value)}'

    def execute(self, context : Context) -> set[str]:
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        if tool is None: return {'CANCELLED'}
        props = tool.operator_properties(tool.idname)
        rna = props.bl_rna.properties.get(self.prop)
        if rna is None: return {'CANCELLED'}

        value = getattr(props, self.prop) + self.value if self.relative else self.value
        # RNA clamps a plain property on assignment, but a property with a custom set() callback
        # (every OperatorPropertyWrapper one) hands the raw value straight to the callback, so
        # clamp here and both kinds behave the same.
        value = min(max(value, rna.hard_min), rna.hard_max)
        setattr(props, self.prop, round(value) if rna.type == 'INT' else value)

        if context.area: context.area.tag_redraw()
        return {'FINISHED'}

def _label_for(rna, value, decimals : int = 0) -> str:
    if rna.subtype == 'ANGLE': return f'{degrees(value):.0f}°'
    if rna.type == 'INT': return str(int(value))
    if not value: return '0'      # not '.0': zero is off, matching its own icon
    if not decimals: return f'{value:g}'
    text = f'{value:.{decimals}f}'
    # trim a character without losing precision, so a row of buttons stays narrow and even:
    # .25 rather than 0.25 below one, 1.0 rather than 1.00 above it
    if abs(value) < 1: return text.replace('0.', '.', 1)
    # the '.' stops rstrip, so '10.00' trims to '10' rather than '1'
    return text.rstrip('0').rstrip('.')

def _is_current(current, value) -> bool:
    if isinstance(current, int): return current == int(value)
    return abs(current - value) <= max(1e-4, abs(value) * 1e-3) # close enough

def _step_icons(steps) -> list[str]:
    # A zero bottom step takes STEP_ICONS[0] and then ramps from [2]
    STEP_ICONS = ('LAYER_USED', 'DECORATE', 'LAYER_ACTIVE', 'RECORD_ON', 'SHADING_SOLID')
    zero = bool(steps) and not steps[0]
    ramp = STEP_ICONS[2:] if zero else STEP_ICONS[1:]
    n = len(steps) - zero
    icons = [ramp[-1] if n <= 1 else ramp[round(i * (len(ramp) - 1) / (n - 1))] for i in range(n)]
    return ([STEP_ICONS[0]] if zero else []) + icons


def draw_prop_steps(
    layout : UILayout,
    props : OperatorProperties,
    prop : str,
    steps,
    *,
    text : str | None = None,
    label_factor : float = 0.35,
    use_dots : bool = True,
):
    rna = props.bl_rna.properties[prop]
    current = getattr(props, prop)
    steps = tuple(steps)
    decimals = 0 if use_dots else (
        # decimals the widest step needs, so a row reads evenly: .25 / .50 / .75 / 1
        max((len(f'{v:g}'.partition('.')[2]) for v in steps), default=0)
    )
    icons = _step_icons(steps) if use_dots else ['NONE'] * len(steps)
    # text='' asks for no label, as does a zero factor; None still means "use the RNA name"
    if label_factor and text != '':
        split = layout.row().split(factor=label_factor, align=True)
        split.label(text=text if text is not None else rna.name)
        row = split.split(align=True)
    else:
        row = layout.row().split(align=True)
    for value, icon in zip(steps, icons):
        op = row.operator(
            RFOperator_SetToolProp.bl_idname,
            text='' if use_dots else _label_for(rna, value, decimals),
            icon=icon,
            depress=_is_current(current, value),
        )
        op.prop, op.value, op.relative = prop, float(value), False


def pie_section(back, pie_emboss, text, panel_idname=None):
    """ Draw a section header and return the box beneath it for the section's contents.
    Given a panel idname the header becomes a button raising that panel. """
    row = back.row()
    row.emboss = pie_emboss
    if panel_idname:
        row.operator('wm.call_panel', text=text, icon='RIGHTARROW').name = panel_idname
    else:
        row.label(text=text)
    return back.box().column()


def rftool_props(tool):
    """ The active tool's operator properties, or None """
    if not tool or tool.idname.split('.')[0] != 'retopoflow': return None
    try: return tool.operator_properties(tool.idname)
    except Exception: return None


class RFMenu_MT_ToolPie(Menu):
    bl_idname = 'RF_MT_Tools'
    bl_label = 'Retopoflow Tools Pie Menu'

    @classmethod
    def poll(cls, context):
        if context.mode != 'EDIT_MESH':
            return False
        from ..preferences import RF_Prefs
        prefs = RF_Prefs.get_prefs(context)
        if prefs.pie_tool_context == 'ANY_TOOL':
            return True
        if prefs.pie_tool_context == 'RF_TOOL':
            tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
            return tool is not None and tool.idname.split('.')[0] == 'retopoflow'
        return False

    def draw_bottom_menu(self, context, pie):
        scene_props = context.scene.retopoflow
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        pie_emboss = 'PIE_MENU' if bpy.app.version >= (5,0,0) else 'RADIAL_MENU'

        back = pie.box().column(align=True)

        section = pie_section(back, pie_emboss, 'Clean Up', 'RF_PT_MeshCleanup')
        row = section.split(align=True)
        row.operator('retopoflow.meshcleanup', text='Selected').affect_all=False
        row.operator('retopoflow.meshcleanup', text='All').affect_all=True
        section.separator(type='LINE', factor=0.5)
        row = section.row(align=True)
        row.operator_context = 'INVOKE_REGION_WIN' # So ops below can seed their defaults from the RF scene settings
        row.operator('retopoflow.space_evenly', text='Even')
        row.operator('retopoflow.relax_selected', text='Relax')

        # None for a tool the options panel cannot draw, which leaves that header a plain label
        tool_options = RFMenu_PT_ToolOptions.bl_idname if has_tool_options(tool) else None

        # Tweak and Relax have neither of these, so they get no Tweaking section
        tool_props = rftool_props(tool)
        declared = tool_props.bl_rna.properties if tool_props else ()
        has_curves = 'show_curve_handles' in declared
        has_loops = 'select_loops' in declared
        if has_curves or has_loops:
            section = pie_section(back, pie_emboss, 'Tweaking', 'RF_PT_TweakCommon')
            row = section.split(align=True)
            if has_curves:
                row.prop(tool_props, 'show_curve_handles', text='Handles', toggle=True, icon='IPO_BEZIER')
            if has_loops:
                row.prop(tool_props, 'select_loops', text='Loops', toggle=True, icon_value=Icon.LOOP.icon_id)

        if tool.idname == 'retopoflow.polypen':
            props = tool.operator_properties(tool.idname)
            section = pie_section(back, pie_emboss, 'PolyPen', tool_options)
            section.ui_units_x = 8
            section.split(align=True).prop(props, 'insert_mode', expand=True, icon_only=True)
            if PolyPen_Insert_Modes.insert_mode == 4:
                draw_prop_steps(section, props, 'quad_stability', (0, 0.25, 0.75, 1.0), text='Stability')
            col = section.column(align=True)
            row = col.row().split()
            row.label(text='Knife')
            row.prop(props, 'constrain_edge_vert', toggle=False)
            row = col.row().split()
            row.prop(props, 'use_loop_cuts', toggle=False)
            row.prop(props, 'quad_preserve', text='Junctions', toggle=False)

        elif tool.idname == 'retopoflow.polystrips':
            props = tool.operator_properties(tool.idname)
            section = pie_section(back, pie_emboss, 'PolyStrips', tool_options)
            section.ui_units_x = 8
            col = section.column(align=False)
            col.row(align=True).prop(props, 'size_mode', expand=True)
            if props.size_mode == 'LENGTH':
                draw_prop_steps(col, props, 'span_length', (0.01, 0.1, 0.5, 1.0), label_factor=0.25)
            else:
                draw_prop_steps(col, props, 'brush_radius', (25, 50, 100, 200), label_factor=0.25)
            draw_prop_steps(col, props, 'split_angle', (radians(45), radians(75), radians(95)),
                            text='Split', use_dots=False, label_factor=0.25)

        elif tool.idname == 'retopoflow.strokes':
            props = tool.operator_properties(tool.idname)
            section = pie_section(back, pie_emboss, 'Strokes', tool_options)
            section.ui_units_x = 10
            col = section.column(align=False)
            col.row(align=True).prop(props, 'span_insert_mode', expand=True)
            if props.span_insert_mode == 'FIXED':
                draw_prop_steps(col, props, 'cut_count', (4, 8, 16, 32), text='Count')
            else:
                draw_prop_steps(col, props, 'brush_radius', (25, 50, 100, 200), text='Radius')
            draw_prop_steps(col, props, 'smooth_angle', (0.0, 0.5, 1.0, 1.5), text='Blending')
            col.row(align=True).prop(props, 'extrapolate_mode', expand=True)

        elif tool.idname == 'retopoflow.contours':
            props = tool.operator_properties(tool.idname)
            section = pie_section(back, pie_emboss, 'Contours', tool_options)
            section.ui_units_x = 8
            section.row(align=True).prop(props, 'span_insert_mode', expand=True)
            draw_prop_steps(section, props, 'span_count', (4, 8, 16, 32), text='', use_dots=False, label_factor=0.25)
            section.row(align=True).prop(props, 'process_source_method', expand=True)
            draw_prop_steps(section, props, 'curvature_bias', (0, 0.5, 1), text='Curvature', use_dots=False, label_factor=0.5)
            draw_prop_steps(section, props, 'space_evenly', (0, 0.5, 1), use_dots=False, label_factor=0.5)

        elif tool.idname == 'retopoflow.tweak' or tool.idname == 'retopoflow.relax':
            tool_name = 'Tweak' if tool.idname == 'retopoflow.tweak' else 'Relax'
            props = tool.operator_properties(tool.idname)
            section = pie_section(back, pie_emboss, tool_name, tool_options)
            section.ui_units_x = 9
            col = section.column(align=False)
            draw_prop_steps(col, props, 'brush_radius', (75, 150, 250, 400))
            draw_prop_steps(col, props, 'brush_strength', (0.25, 0.5, 0.75, 1.0))
            draw_prop_steps(col, props, 'brush_falloff', (0, 0.4, 0.6, 1.0))

            if tool.idname == 'retopoflow.relax':
                col = section.column(align=True)
                row = col.split(factor=0.5)
                row.prop(props, 'algorithm_laplacian', text='Smooth', toggle=False)
                row.prop(props, 'algorithm_average_edge_lengths', text='Average', toggle=False)
                row = col.split(factor=0.5)
                row.prop(props, 'algorithm_straighten_edges', text='Straighten', toggle=False)
                row.prop(props, 'algorithm_equalize_faces', text='Equalize', toggle=False)

            section = pie_section(back, pie_emboss, 'Masking', 'RF_PT_Pinning')
            row = section.row(align=True)
            row.operator('retopoflow.pinverts', text='Pin', icon='PINNED')
            row.operator('retopoflow.unpinverts', text='Unpin', icon='UNPINNED')
            col = section.column(align=False)
            split = col.row().split(factor=0.4, align=True)
            split.label(text='Selected')
            split.prop(scene_props, 'mask_selected', expand=True, icon_only=True)
            split = col.row().split(factor=0.4, align=True)
            split.label(text='Boundary')
            split.prop(scene_props, 'mask_boundary', expand=True, icon_only=True)
            split = col.row().split(factor=0.4, align=True)
            split.label(text='Seams')
            split.prop(scene_props, 'mask_seams', expand=True, icon_only=True)
            row = col.row(align=True)
            row.prop(scene_props, 'include_corners')
            row.prop(scene_props, 'include_pinned')

        elif tool.idname == PATCHES_IDNAME and not USE_NEW_PATCHES:
            L = LegacyPatches_Logic
            props = tool.operator_properties(tool.idname)
            section = pie_section(back, pie_emboss, 'Patches', tool_options)
            section.ui_units_x = 9
            # only the non-redo half of draw_patches_props applies: these four always show, and
            # the rest below follow the fill flags of whatever is selected
            section.row(align=True).prop(props, 'span_insert_mode', expand=True)
            if props.span_insert_mode == 'FIXED':
                draw_prop_steps(section, props, 'crosses', (1, 2, 4, 8), text='Count', use_dots=False)
            elif props.span_insert_mode == 'LENGTH':
                draw_prop_steps(section, props, 'span_length', (0.05, 0.1, 0.25, 0.5), text='Distance', use_dots=False)
            draw_prop_steps(section, props, 'split_angle', (radians(45), radians(75), radians(95)), text='Split', use_dots=False)
            draw_prop_steps(section, props, 'smooth', (0, 5, 10), use_dots=False)

            # A grid fill's solution and offset and a loft's twist stay in the sidebar: they are
            # rotation indices that wrap, so there is no preset to jump to and no ceiling to stop
            # at, which leaves nothing a pie can offer in one release.
            if L.has_quad or L.has_offset:
                section.separator(type='LINE', factor=0.5)
                if L.has_quad:
                    draw_prop_steps(section, props, 'crosses', (1, 2, 4, 8), text='Cuts')
                if L.has_offset:
                    draw_prop_steps(section, props, 'steps', (1, 2, 4, 8))
                    if L.has_free_step:
                        draw_prop_steps(section, props, 'step_scale', (0.5, 1.0, 2.0), text='Distance')



    def draw(self, context):
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        layout = self.layout
        pie = layout.menu_pie()

        # West
        _ = pie.operator(
            'retopoflow.switch_to_polystrips',
            text='PolyStrips',
            icon_value=RF_icons['POLYSTRIPS'].icon_id,
            depress=tool.idname=='retopoflow.polystrips'
        )

        # East
        _ = pie.operator(
            'retopoflow.switch_to_tweak',
            text='Tweak',
            icon_value=RF_icons['TWEAK'].icon_id,
            depress=tool.idname=='retopoflow.tweak'
        )

        # South
        self.draw_bottom_menu(context, pie)

        # North
        _ = pie.operator(
            'retopoflow.switch_to_contours',
            text='Contours',
            icon_value=RF_icons['CONTOURS'].icon_id,
            depress=tool.idname=='retopoflow.contours'
        )

        # Northwest
        _ = pie.operator(
            'retopoflow.switch_to_strokes',
            text='Strokes',
            icon_value=RF_icons['STROKES'].icon_id,
            depress=tool.idname=='retopoflow.strokes'
        )

        # Northeast
        _ = pie.operator(
            PATCHES_SWITCH_IDNAME,
            text='Patches',
            icon_value=RF_icons['PATCHES'].icon_id,
            depress=tool.idname==PATCHES_IDNAME,
        )

        # Southwest
        _ = pie.operator(
            'retopoflow.switch_to_polypen',
            text='PolyPen',
            icon_value=RF_icons['POLYPEN'].icon_id,
            depress=tool.idname=='retopoflow.polypen'
        )

        # Southeast
        _ = pie.operator(
            'retopoflow.switch_to_relax',
            text='Relax',
            icon_value=RF_icons['RELAX'].icon_id,
            depress=tool.idname=='retopoflow.relax'
        )



keymaps = []
RF_icons = None


def register():
    bpy.utils.register_class(RFMenu_MT_ToolPie)

    wm = bpy.context.window_manager
    keyconfigs = wm.keyconfigs.addon
    if keyconfigs:
        keymap = keyconfigs.keymaps.new(name='3D View', space_type='VIEW_3D')
        keymap_item = keymap.keymap_items.new('wm.call_menu_pie', 'W', 'PRESS', ctrl=False, shift=False, alt=False)
        keymap_item.properties.name =  RFMenu_MT_ToolPie.bl_idname
        keymaps.append((keymap, keymap_item))

    global RF_icons
    RF_icons = previews.new()
    icons_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, 'icons'))
    RF_icons.load('POLYPEN', os.path.join(icons_dir, 'polypen-icon.png'), 'IMAGE')
    RF_icons.load('POLYSTRIPS', os.path.join(icons_dir, 'polystrips-icon.png'), 'IMAGE')
    RF_icons.load('STROKES', os.path.join(icons_dir, 'strokes-icon.png'), 'IMAGE')
    RF_icons.load('CONTOURS', os.path.join(icons_dir, 'contours-icon.png'), 'IMAGE')
    RF_icons.load('PATCHES', os.path.join(icons_dir, 'patches-icon.png'), 'IMAGE')
    RF_icons.load('TWEAK', os.path.join(icons_dir, 'tweak-icon.png'), 'IMAGE')
    RF_icons.load('RELAX', os.path.join(icons_dir, 'relax-icon.png'), 'IMAGE')

def unregister():
    bpy.utils.unregister_class(RFMenu_MT_ToolPie)

    for keymap, keymap_item in keymaps:
        keymap.keymap_items.remove(keymap_item)
    keymaps.clear()

    global RF_icons
    previews.remove(RF_icons)
