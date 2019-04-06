'''
Copyright (C) 2017 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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

import os
import re
import json

import bpy
from bpy.types import (
    AddonPreferences,
    Menu,
    Operator,
    Panel,
)
from bpy.props import (
    EnumProperty, StringProperty, BoolProperty,
    IntProperty, FloatVectorProperty, FloatProperty,
)

from . import addon_updater_ops

from .rfmode.rftool import RFTool
from .rfmode.rfmode import RFMode

from .icons import load_icons
from .common.blender import show_blender_text
from .common.logger import logger
from .options import (
    options,
    retopoflow_tip_url,
    retopoflow_version,
)
from .help import help_quickstart


class RF_OpenWebTip(Operator):
    """Open RetopoFlow Tip page in default web browser"""

    bl_category = 'Retopology'
    bl_idname = "cgcookie.rf_open_webtip"
    bl_label = "Open RetopoFlow Tip Page"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        bpy.ops.wm.url_open(url=retopoflow_tip_url)
        return {'FINISHED'}


class RF_OpenLog(Operator):
    """Open RetopoFlow Error Log in new window"""

    bl_category = 'Retopology'
    bl_idname = "cgcookie.rf_open_errorlog"
    bl_label = "Open RetopoFlow Error Log"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    @classmethod
    def poll(cls, context):
        return logger.has_log()

    def execute(self, context):
        logger.open_log()
        return {'FINISHED'}


class RF_OpenQuickStart(Operator):
    """Open RetopoFlow Quick Start Guide in new window"""

    bl_category = 'Retopology'
    bl_idname = 'cgcookie.rf_open_quickstart'
    bl_label = "Open RetopoFlow Quick Start Guide"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        self.openTextFile()
        return {'FINISHED'}

    def openTextFile(self):
        # simple processing of help_quickstart
        t = help_quickstart
        t = re.sub(r'^\n*', r'', t)         # remove leading newlines
        t = re.sub(r'\n*$', r'', t)         # remove trailing newlines
        t = re.sub(r'\n\n+', r'\n\n', t)    # make uniform paragraph separations
        ps = t.split('\n\n')
        l = []
        for p in ps:
            if p.startswith('- '):
                l += [p]
                continue
            lines = p.split('\n')
            if len(lines) == 2 and (lines[1].startswith('---') or lines[1].startswith('===')):
                l += [p]
                continue
            l += ['  '.join(lines)]
        t = '\n\n'.join(l)

        # play it safe!
        if options['quickstart_filename'] not in bpy.data.texts:
            # create a log file for error writing
            bpy.data.texts.new(options['quickstart_filename'])
        # restore data, just in case
        txt = bpy.data.texts[options['quickstart_filename']]
        txt.from_string(t)
        txt.current_line_index = 0

        show_blender_text(options['quickstart_filename'])


class RF_Recover(Operator):
    """Recovers from last auto-save"""

    bl_category    = "Retopology"
    bl_idname      = "cgcookie.rf_recover"
    bl_label       = "Recover Auto Save"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    rf_icon = 'rf_recover_icon'

    @classmethod
    def poll(cls, context):
        return os.path.exists(options.temp_filepath('blend')) and os.path.exists(options.temp_filepath('state'))

    def invoke(self, context, event):
        RFMode.backup_recover()
        return {'FINISHED'}


class RF_Recover_Clear(Operator):
    """Deletes auto-save files"""

    bl_category    = "Retopology"
    bl_idname      = "cgcookie.rf_recover_clear"
    bl_label       = "Clear Auto Save"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    rf_icon = None

    @classmethod
    def poll(cls, context):
        return os.path.exists(options.temp_filepath('blend')) and os.path.exists(options.temp_filepath('state'))

    def invoke(self, context, event):
        os.remove(options.temp_filepath('blend'))
        os.remove(options.temp_filepath('state'))
        return {'FINISHED'}


class RF_SnapObjects(bpy.types.PropertyGroup):
    max_count = 1000
    name_map = {}
    name_map_rev = {}

    @staticmethod
    def get_boolprop_name(name):
        if name not in RF_SnapObjects.name_map:
            c = len(RF_SnapObjects.name_map)
            assert c < RF_SnapObjects.max_count
            RF_SnapObjects.name_map[name] = c
            RF_SnapObjects.name_map_rev[c] = name
        return 'mesh%04d' % RF_SnapObjects.name_map[name]

    @staticmethod
    def get_boolprop_value(name):
        name = RF_SnapObjects.get_boolprop_name(name)
        return getattr(RF_SnapObjects, name)

    @staticmethod
    def generate_boolprops():
        # generate a bunch of BoolProperty objects, because we (seemingly) cannot
        # instantiate them when we need them (during draw of RF_PT_Panel)
        for i in range(RF_SnapObjects.max_count):
            name = 'mesh%04d' % i
            def getter_setter():
                i_ = i
                name_ = name
                def getter(self):
                    return RFMode.get_source_snap(RF_SnapObjects.name_map_rev[i_])
                def setter(self, val):
                    return RFMode.set_source_snap(RF_SnapObjects.name_map_rev[i_], val)
                return (getter, setter)
            getter, setter = getter_setter()
            setattr(RF_SnapObjects, name, BoolProperty(name=name, description="Check to snap target to this source.", default=True, get=getter, set=setter))

RF_SnapObjects.generate_boolprops()


class RF_PT_Panel(Panel):
    bl_category = "Retopology"
    bl_label = "RetopoFlow %s" % retopoflow_version
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    def draw(self, context):
        # https://docs.blender.org/api/current/bpy.types.UILayout.html#bpy.types.UILayout

        def human_readable(c):
            if c < 10000:
                return str(c)
            if c < 1000000:
                c = round(c / 1000)
                return '%sk' % str(c)
            c = round(c / 1000000)
            return '%sm' % str(c)

        layout = self.layout

        # explicitly call to check for update in background
        # note: built-in checks ensure it runs at most once
        addon_updater_ops.check_for_update_background()

        icons = load_icons()

        col = layout.column(align=True)
        col.operator("cgcookie.rf_open_quickstart", "Quick Start Guide")
        col.operator("cgcookie.rf_open_webissues",  "Report an Issue")
        # col.operator("cgcookie.rf_open_webtip",     "Send us a tip")

        target = RFMode.get_target()
        layout.label('Target:')
        box = layout.box()
        if not target:
            box.label("Creating New", icon='NEW')
        else:
            if RFMode.dense_target():
                box.alert = True
                warncol = box.column(align=True)
                warncol.label("High Polycount!", icon="ERROR")
                warncol.label("Might load slowly")
            n = target.name
            c = len(target.data.polygons)
            box.label('%s (%s)' % (n, human_readable(c)))

        sources = RFMode.get_sources()
        c = len(sources)
        layout.label('%d Source%s:' % (c, '' if c==1 else 's'))
        box = layout.box()
        if not sources:
            warncol = box.column(align=True)
            warncol.label('None detected', icon='ERROR')
        else:
            if RFMode.dense_sources():
                #box.alert = True
                warncol = box.column(align=True)
                warncol.label("High Polycount!", icon="ERROR")
                warncol.label("Might load slowly")
            namecol = box.column(align=True)
            for source in sources:
                n = source.name
                c = len(source.data.polygons)
                namecol.prop(context.scene.snapobjects, RF_SnapObjects.get_boolprop_name(n), text='%s (%s)' % (n, human_readable(c)))
                #namecol.label('%s (%s)' % (n, human_readable(c)))
            namecol.label('Check to snap')

        col = layout.column(align=True)
        col.alignment = 'CENTER'

        # col.operator("cgcookie.rfmode")
        for ids,rft in RFTool.get_tools():
            icon_name = rft.rf_icon
            if icon_name is not None:
                icon = icons.get(icon_name)
                col.operator(ids, rft.rf_label, icon_value=icon.icon_id)
            else:
                col.operator(ids)

        col = layout.column(align=True)
        col.alignment = 'CENTER'
        col.label('Help')
        col.operator('cgcookie.rf_recover') #, icon_value=icons.get('rf_recover_icon').icon_id)
        col.operator('cgcookie.rf_recover_clear') #, icon_value=icons.get('rf_recover_icon').icon_id)
        col.operator("cgcookie.rf_open_errorlog", "Open Error Log")

        addon_updater_ops.update_notice_box_ui(self, context)


class RF_Menu(Menu):
    bl_label = "RetopoFlow %s" % retopoflow_version
    bl_space_type = 'VIEW_3D'
    bl_idname = "object.retopology_menu"

    def draw(self, context):
        layout = self.layout

        # explicitly call to check for update in background
        # note: built-in checks ensure it runs at most once
        addon_updater_ops.check_for_update_background()

        layout.operator_context = 'INVOKE_DEFAULT'

        icons = load_icons()

        col = layout.column(align=True)
        col.alignment = 'CENTER'
        # col.operator("cgcookie.rfmode")
        for ids,rft in RFTool.get_tools():
            icon_name = rft.rf_icon
            if icon_name is not None:
                icon = icons.get(icon_name)
                col.operator(ids, icon_value=icon.icon_id)
            else:
                col.operator(ids)


class RF_Preferences(AddonPreferences):
    # bl_idname **MUST** be same as the root folder of RF add-on
    bl_idname = os.path.basename(os.path.dirname(os.path.abspath(__file__)))

    # addon updater preferences
    auto_check_update = BoolProperty(
        name = "Auto-check for Update",
        description = "If enabled, auto-check for updates using an interval",
        default = False,
        )
    updater_intrval_months = IntProperty(
        name='Months',
        description = "Number of months between checking for updates",
        default=0,
        min=0
        )
    updater_intrval_days = IntProperty(
        name='Days',
        description = "Number of days between checking for updates",
        default=7,
        min=0,
        )
    updater_intrval_hours = IntProperty(
        name='Hours',
        description = "Number of hours between checking for updates",
        default=0,
        min=0,
        max=23
        )
    updater_intrval_minutes = IntProperty(
        name='Minutes',
        description = "Number of minutes between checking for updates",
        default=0,
        min=0,
        max=59
        )


    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.label("All RetopoFlow options are accessible in RetopoFlow Mode")

        # updater draw function
        addon_updater_ops.update_settings_ui(self,context)


