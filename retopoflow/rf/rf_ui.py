'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

import gc
import os
import sys
import json
import time
import shutil
import inspect
from datetime import datetime
import contextlib


import urllib.request

import bpy

from ...addon_common.cookiecutter.cookiecutter import CookieCutter
from ...addon_common.common.boundvar import BoundVar, BoundBool, BoundFloat, BoundString, BoundInt
from ...addon_common.common.utils import delay_exec
from ...addon_common.common.globals import Globals
from ...addon_common.common.blender import get_path_from_addon_root
from ...addon_common.common.blender_preferences import get_preferences
from ...addon_common.common.ui_core import UI_Element
from ...addon_common.common.ui_styling import load_defaultstylings
from ...addon_common.common.profiler import profiler

from ...config.options import (
    options, themes, visualization,
    retopoflow_urls, retopoflow_product,   # these are needed for UI
    build_platform,
    platform_system, platform_node, platform_release, platform_version, platform_machine, platform_processor,
)


class RetopoFlow_UI:
    @CookieCutter.Exception_Callback
    def handle_exception(self, e):
        print(f'RF_UI.handle_exception: {e}')
        if False:
            for entry in inspect.stack():
                print(f'  {entry}')
        message,h = Globals.debugger.get_exception_info_and_hash()
        message = '\n'.join(f'- {l}' for l in message.splitlines())
        self.alert_user(title='Exception caught', message=message, level='exception', msghash=h)
        self.rftool._reset()


    #################################
    # pie menu

    def setup_pie_menu(self):
        path_pie_menu_html = get_path_from_addon_root('retopoflow', 'html', 'pie_menu.html')
        self.ui_pie_menu = UI_Element.fromHTMLFile(path_pie_menu_html)[0]
        self.ui_pie_menu.can_hover = False
        self.document.body.append_child(self.ui_pie_menu)

    def show_pie_menu(self, options, fn_callback, highlighted=None, release=None, always_callback=False, rotate=0):
        if len(options) == 0: return
        self.pie_menu_rotation = rotate - 90
        self.pie_menu_callback = fn_callback
        self.pie_menu_options = list(options)
        self.pie_menu_highlighted = highlighted
        self.pie_menu_release = release or 'pie menu'
        self.pie_menu_always_callback = always_callback
        self.fsm.force_set_state('pie menu')


    #################################
    # ui

    def blender_ui_set(self, scale_to_unit_box=True, add_rotate=True, hide_target=True):
        # print('RetopoFlow: blender_ui_set', 'scale_to_unit_box='+str(scale_to_unit_box), 'add_rotate='+str(add_rotate))
        bpy.ops.object.mode_set(mode='OBJECT')
        if scale_to_unit_box:
            self.start_normalize()
            self.scene_scale_set(1.0)
        self.viewaa_simplify()

        if self.shading_type_get() in {'WIREFRAME', 'RENDERED'}:
            self.shading_type_set('SOLID')

        self.gizmo_hide()

        if get_preferences().system.use_region_overlap or options['hide panels no overlap']:
            ignore = None if options['hide header panel'] else {'header'}
            self.panels_hide(ignore=ignore)
        if options['hide overlays']:
            self.overlays_hide()
        self.blender_shading_update()
        self.quadview_hide()
        self.region_darken()
        self.header_text_set('RetopoFlow')
        self.statusbar_text_set('')
        if add_rotate: self.setup_rotate_about_active()
        if hide_target: self.hide_target()

    def blender_shading_update(self):
        if options['override shading'] == 'off':
            self.shading_restore()
            return

        # common optimizations
        self.shading_type_set(options['shading view'])
        self.shading_backface_set(options['shading backface culling'])
        self.shading_shadows_set(options['shading shadows'])
        self.shading_xray_set(options['shading xray'])
        self.shading_cavity_set(options['shading cavity'])
        self.shading_outline_set(options['shading outline'])

        # theme-based optimizations
        matcap = None
        if options['override shading'] == 'light':
            self.shading_color_set(options['shading color light'])
            self.shading_colortype_set(options['shading colortype'])
            matcap = options['shading matcap light']
        elif options['override shading'] == 'dark':
            self.shading_color_set(options['shading color dark'])
            self.shading_colortype_set(options['shading colortype'])
            matcap = options['shading matcap dark']
        if matcap:
            if matcap not in bpy.context.preferences.studio_lights:
                path_rf_matcap = os.path.join(get_path_from_addon_root('matcaps'), matcap)
                print(f'RetopoFlow: Loading maptcap {matcap} {path_rf_matcap}')
                ret = bpy.context.preferences.studio_lights.load(path_rf_matcap, 'MATCAP')
                if not ret: matcap = None
            if matcap:
                self.shading_light_set(options['shading light'])
                self.shading_matcap_set(matcap)

    def blender_ui_reset(self, *, ignore_panels=False):
        # IMPORTANT: changes here should also go in rf_blender_save.backup_recover()
        self.end_rotate_about_active()
        self.teardown_target()
        self.end_normalize(self.context)
        self._cc_blenderui_end(ignore=({'panels'} if ignore_panels else None))
        bpy.ops.object.mode_set(mode='EDIT')

    @contextlib.contextmanager
    def blender_ui_pause(self, *, ignore_panels=False):
        self.blender_ui_reset(ignore_panels=ignore_panels)
        yield None
        self.blender_ui_set()
        self.update_clip_settings(rescale=False)

    def setup_ui_blender(self):
        self.blender_ui_set(scale_to_unit_box=False, add_rotate=False, hide_target=False)





    def update_ui(self):
        if not hasattr(self, 'rftools_ui'): return
        autohide = options['tools autohide']
        changed = False
        for rftool in self.rftools_ui.keys():
            show = not autohide or (rftool == self.rftool)
            for ui_elem in self.rftools_ui[rftool]:
                if ui_elem.get_is_visible() == show: continue
                ui_elem.is_visible = show
                changed = True
        if changed:
            self.ui_options.dirty(cause='update', parent=True, children=True)

    def update_ui_geometry(self):
        if not self.ui_geometry: return
        vis = self.ui_geometry.is_visible
        # TODO: FIX WORKAROUND HACK!
        #       toggle visibility as workaround hack for relaying out table :(
        if vis: self.ui_geometry.is_visible = False
        self.ui_geometry.getElementById('geometry-verts').innerText = f'{self.rftarget.get_vert_count()}'
        self.ui_geometry.getElementById('geometry-edges').innerText = f'{self.rftarget.get_edge_count()}'
        self.ui_geometry.getElementById('geometry-faces').innerText = f'{self.rftarget.get_face_count()}'
        if vis: self.ui_geometry.is_visible = True

    def minimize_geometry_window(self, target):
        if target.id != 'geometrydialog': return
        options['show geometry window'] = False
        self.ui_geometry.is_visible     = False
        self.ui_geometry_min.is_visible = True
        self.ui_geometry_min.left = self.ui_geometry.left
        self.ui_geometry_min.top  = self.ui_geometry.top
        self.document.force_clean(self.actions.context)
    def restore_geometry_window(self, target):
        if target.id != 'geometrydialog-minimized': return
        options['show geometry window'] = True
        self.ui_geometry.is_visible     = True
        self.ui_geometry_min.is_visible = False
        self.ui_geometry.left = self.ui_geometry_min.left
        self.ui_geometry.top  = self.ui_geometry_min.top
        self.update_ui_geometry()
        self.document.force_clean(self.actions.context)

    def minimize_options_window(self, target):
        if target.id != 'optionsdialog': return
        options['show options window'] = False
        self.ui_options.is_visible     = False
        self.ui_options_min.is_visible = True
        self.ui_options_min.left = self.ui_options.left
        self.ui_options_min.top  = self.ui_options.top
        self.document.force_clean(self.actions.context)
    def restore_options_window(self, target):
        if target.id != 'optionsdialog-minimized': return
        options['show options window'] = True
        self.ui_options.is_visible     = True
        self.ui_options_min.is_visible = False
        self.ui_options.left = self.ui_options_min.left
        self.ui_options.top  = self.ui_options_min.top
        self.document.force_clean(self.actions.context)

    def show_options_window(self):
        options['show options window'] = True
        self.ui_options.is_visible = True
        # self.ui_main.getElementById('show-options').disabled = True
    def hide_options_window(self):
        options['show options window'] = False
        self.ui_options.is_visible = False
        # self.ui_main.getElementById('show-options').disabled = False
    def options_window_visibility_changed(self):
        if self.ui_hide: return
        visible = self.ui_options.is_visible
        options['show options window'] = visible
        # self.ui_main.getElementById('show-options').disabled = visible

    def show_main_ui_window(self):
        options['show main window'] = True
        self.ui_tiny.is_visible = False
        self.ui_main.is_visible = True
    def show_tiny_ui_window(self):
        options['show main window'] = False
        self.ui_tiny.is_visible = True
        self.ui_main.is_visible = False
    def update_main_ui_window(self):
        if self.ui_hide: return
        if self._ui_windows_updating: return
        pre = self._ui_windows_updating
        self._ui_windows_updating = True
        options['show main window'] = self.ui_main.is_visible
        if not options['show main window']:
            self.ui_tiny.is_visible = True
            self.ui_tiny.left = self.ui_main.left
            self.ui_tiny.top = self.ui_main.top
            # self.ui_tiny.clean()
        self._ui_windows_updating = pre
    def update_tiny_ui_window(self):
        if self.ui_hide: return
        if self._ui_windows_updating: return
        pre = self._ui_windows_updating
        self._ui_windows_updating = True
        options['show main window'] = not self.ui_tiny.is_visible
        if options['show main window']:
            self.ui_main.is_visible = True
            self.ui_main.left = self.ui_tiny.left
            self.ui_main.top = self.ui_tiny.top
            # self.ui_main.clean()
        self._ui_windows_updating = pre
    def update_main_tiny_ui_windows(self):
        if self.ui_hide: return

        pre = self._ui_windows_updating
        self._ui_windows_updating = True
        self.ui_main.is_visible = options['show main window']
        self.ui_tiny.is_visible = not options['show main window']
        self._ui_windows_updating = pre

    def setup_ui(self):
        # NOTE: lambda is needed on next line so that RF keymaps are bound!
        humanread = lambda x: self.actions.to_human_readable(x, sep=' / ')

        self.hide_target()

        # load ui.css
        self.reload_stylings()
        self.ui_hide = False

        self._var_auto_hide_options = BoundBool('''options['tools autohide']''', on_change=self.update_ui)
        self._var_use_cython = BoundBool('''options['use cython']''', on_change=lambda : setattr(self.rftarget, 'accel_recompute', True))

        rf_starting_tool = getattr(self, 'rf_starting_tool', None) or options['starting tool']

        def setup_counts_ui():
            self.document.body.append_children(UI_Element.fromHTMLFile(get_path_from_addon_root('retopoflow', 'html', 'geometry.html')))
            self.ui_geometry = self.document.body.getElementById('geometrydialog')
            self.ui_geometry_min = self.document.body.getElementById('geometrydialog-minimized')
            self.ui_geometry.is_visible = options['show geometry window']
            self.ui_geometry_min.is_visible = not options['show geometry window']
            self.update_ui_geometry()

        def setup_tiny_ui():
            nonlocal humanread
            self.ui_tiny = UI_Element.fromHTMLFile(get_path_from_addon_root('retopoflow', 'html', 'main_tiny.html'))[0]
            self.document.body.append_child(self.ui_tiny)

        def setup_main_ui():
            nonlocal humanread
            self.ui_main = UI_Element.fromHTMLFile(get_path_from_addon_root('retopoflow', 'html', 'main_full.html'))[0]
            self.document.body.append_child(self.ui_main)

        def setup_tool_buttons():
            ui_tools  = self.ui_main.getElementById('tools')
            ui_ttools = self.ui_tiny.getElementById('ttools')
            def add_tool(rftool):               # IMPORTANT: must be a fn so that local vars are unique and correctly captured
                nonlocal self, humanread        # IMPORTANT: need this so that these are captured
                shortcut = humanread({rftool.shortcut})
                quick = humanread({rftool.quick_shortcut}) if rftool.quick_shortcut else ''
                title = f'{rftool.name}: {rftool.description}. Shortcut: {shortcut}.'
                if quick: title += f' Quick: {quick}.'
                val = f'{rftool.name.lower()}'
                ui_tools.append_child(UI_Element.fromHTML(
                    f'<label title="{title}" class="tool">'
                    f'''<input type="radio" id="tool-{val}" value="{val}" name="tool" class="tool" on_input="if this.checked: self.select_rftool(rftool)">'''
                    f'<img src="{rftool.icon}" title="{title}">'
                    f'<span title="{title}">{rftool.name}</span>'
                    f'</label>'
                )[0])
                ui_ttools.append_child(UI_Element.fromHTML(
                    f'<label title="{title}" class="ttool">'
                    f'''<input type="radio" id="ttool-{val}" value="{val}" name="ttool" class="ttool" on_input="if this.checked: self.select_rftool(rftool)">'''
                    f'<img src="{rftool.icon}" title="{title}">'
                    f'</label>'
                )[0])
            for rftool in self.rftools: add_tool(rftool)

        def setup_options():
            nonlocal self, humanread

            self.document.defer_cleaning = True

            self.document.body.append_children(UI_Element.fromHTMLFile(get_path_from_addon_root('retopoflow', 'html', 'options_dialog.html')))
            self.ui_options = self.document.body.getElementById('optionsdialog')
            self.ui_options_min = self.document.body.getElementById('optionsdialog-minimized')
            self.ui_options.is_visible = options['show options window']
            self.ui_options_min.is_visible = not options['show options window']

            self.setup_pie_menu()

            self.rftools_ui = {}
            for rftool in self.rftools:
                ui_elems = []
                def add_elem(ui_elem):
                    if not ui_elem:
                        return
                    if type(ui_elem) is list:
                        for ui in ui_elem:
                            add_elem(ui)
                        return
                    ui_elems.append(ui_elem)
                    self.ui_options.getElementById('options-contents').append_child(ui_elem)
                if rftool.ui_config:
                    path_folder = os.path.dirname(inspect.getfile(rftool.__class__))
                    path_html = os.path.join(path_folder, rftool.ui_config)
                    ret = rftool.call_with_self_in_context(UI_Element.fromHTMLFile, path_html)
                    add_elem(ret)
                ret = rftool._callback('ui setup')
                add_elem(ret)

                self.rftools_ui[rftool] = ui_elems
                for ui_elem in ui_elems:
                    self.ui_options.getElementById('options-contents').append_child(ui_elem)

            # if options['show options window']:
            #     self.show_options_window()
            # else:
            #     self.hide_options_window()

            self.document.defer_cleaning = False


        def setup_quit_ui():
            def hide_ui_quit():
                self.ui_quit.is_visible = False
                self.document.sticky_element = None
                self.document.clear_last_under()
            def mouseleave_event():
                if self.ui_quit.is_hovered: return
                hide_ui_quit()
            def key(e):
                if e.key in {'ESC', 'TAB'}: hide_ui_quit()
                if e.key in {'RET', 'NUMPAD_ENTER'}: self.done()

            self.ui_quit = UI_Element.fromHTMLFile(get_path_from_addon_root('retopoflow', 'html', 'quit_dialog.html'))[0]
            self.ui_quit.is_visible = False
            self.document.body.append_child(self.ui_quit)

        def setup_delete_ui():
            def hide_ui_delete():
                self.ui_delete.is_visible = False
                self.document.sticky_element = None
                self.document.clear_last_under()
            def mouseleave_event():
                if self.ui_delete.is_hovered: return
                hide_ui_delete()
            def key(e):
                if e.key == 'ESC': hide_ui_delete()
            def act(opt):
                self.delete_dissolve_collapse_option(opt)
                hide_ui_delete()

            self.ui_delete = UI_Element.fromHTMLFile(get_path_from_addon_root('retopoflow', 'html', 'delete_dialog.html'))[0]
            self.ui_delete.is_visible = False
            self.document.body.append_child(self.ui_delete)

        self._ui_windows_updating = True
        setup_main_ui()
        setup_tiny_ui()
        setup_tool_buttons()
        setup_options()
        setup_quit_ui()
        setup_delete_ui()
        setup_counts_ui()
        self.update_main_tiny_ui_windows()
        self._ui_windows_updating = False

        for rftool in self.rftools:
            if rftool.name == rf_starting_tool:
                self.select_rftool(rftool)

        self.ui_tools = self.document.body.getElementsByName('tool')
        self.update_ui()

    def show_welcome_message(self):
        show = options['welcome'] or options['version update']
        if not show: return
        options['version update'] = False
        self.document.defer_cleaning = True
        self.helpsystem_open('welcome.md')
        self.document.defer_cleaning = False

    def show_quit_dialog(self):
        w,h = self.actions.region.width,self.actions.region.height
        self.ui_quit.reposition(
            left = self.actions.mouse.x - 100,
            top = self.actions.mouse.y - h + 20,
        )
        self.ui_quit.is_visible = True
        self.document.focus(self.ui_quit)
        self.document.sticky_element = self.ui_quit


    def show_delete_dialog(self):
        if not self.any_selected():
            self.alert_user('No geometry selected to delete/dissolve', title='Delete/Dissolve')
            return

        w,h = self.actions.region.width,self.actions.region.height
        self.ui_delete.reposition(
            left = self.actions.mouse.x - 100,
            top = self.actions.mouse.y - h + 20,
        )
        self.ui_delete.is_visible = True
        self.document.focus(self.ui_delete)
        self.document.sticky_element = self.ui_delete

        # # The following is what is done with dialogs
        # self.document.force_clean(self.actions.context)
        # self.document.center_on_mouse(win)
        # self.document.sticky_element = win

    def show_merge_dialog(self):
        if not self.any_selected():
            self.alert_user('No geometry selected to merge', title='Merge')
            return

        w,h = self.actions.region.width,self.actions.region.height
        self.ui_delete.reposition(
            left = self.actions.mouse.x - 100,
            top = self.actions.mouse.y - h + 20,
        )
        self.ui_delete.is_visible = True
        self.document.focus(self.ui_delete)
        self.document.sticky_element = self.ui_delete

