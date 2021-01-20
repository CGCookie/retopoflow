'''
Copyright (C) 2020 CG Cookie
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
import inspect
from datetime import datetime
import contextlib


import urllib.request
from concurrent.futures import ThreadPoolExecutor

import bpy

from ...addon_common.cookiecutter.cookiecutter import CookieCutter
from ...addon_common.common.boundvar import BoundVar, BoundBool, BoundFloat, BoundString
from ...addon_common.common.utils import delay_exec, abspath
from ...addon_common.common.globals import Globals
from ...addon_common.common.blender import get_preferences
from ...addon_common.common import ui
from ...addon_common.common.ui_core import UI_Element
from ...addon_common.common.ui_proxy import UI_Proxy
from ...addon_common.common.ui_styling import load_defaultstylings
from ...addon_common.common.profiler import profiler

from ...config.options import (
    options, themes, visualization,
    retopoflow_issues_url, retopoflow_tip_url,
    retopoflow_version, retopoflow_version_git, retopoflow_cgcookie_built,
    build_platform,
    platform_system, platform_node, platform_release, platform_version, platform_machine, platform_processor,
    gpu_vendor, gpu_renderer, gpu_version, gpu_shading,
)

def get_environment_details():
    blender_version = '%d.%02d.%d' % bpy.app.version
    blender_branch = bpy.app.build_branch.decode('utf-8')
    blender_date = bpy.app.build_commit_date.decode('utf-8')

    env_details = []
    env_details += ['Environment:\n']
    env_details += [f'- RetopoFlow: {retopoflow_version}']
    if retopoflow_version_git:
        env_details += [f'- RF git: {retopoflow_version_git}']
    if retopoflow_cgcookie_built:
        env_details += ['- CG Cookie built']
    env_details += [f'- Blender: {blender_version} {blender_branch} {blender_date}']
    env_details += [f'- Platform: {platform_system}, {platform_release}, {platform_version}, {platform_machine}, {platform_processor}']
    env_details += [f'- GPU: {gpu_vendor}, {gpu_renderer}, {gpu_version}, {gpu_shading}']
    env_details += [f'- Timestamp: {datetime.today().isoformat(" ")}']

    return '\n'.join(env_details)


def get_trace_details(undo_stack, msghash=None, message=None):
    trace_details = []
    trace_details += [f'- Undo: {", ".join(undo_stack[:10])}']
    if msghash:
        trace_details += ['']
        trace_details += [f'Error Hash: {msghash}']
    if message:
        trace_details += ['']
        trace_details += ['Trace:\n']
        trace_details += [message]
    return '\n'.join(trace_details)





class RetopoFlow_UI:
    GitHub_checks = 0
    GitHub_limit = 10

    @CookieCutter.Exception_Callback
    def handle_exception(self, e):
        print('RF_UI.handle_exception', e)
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
        path_pie_menu_html = abspath('pie_menu.html')
        self.ui_pie_menu = UI_Element.fromHTMLFile(path_pie_menu_html)[0]
        self.ui_pie_menu.can_hover = False
        self.document.body.append_child(self.ui_pie_menu)
        self.ui_pie_table = self.ui_pie_menu.getElementById('pie-menu-table')
        # 7 0 1
        # 6   2
        # 5 4 3
        self.ui_pie_sections = [
            (
                self.ui_pie_menu.getElementById(f'pie-menu-{n}'),
                self.ui_pie_menu.getElementById(f'pie-menu-{n}-text'),
                self.ui_pie_menu.getElementById(f'pie-menu-{n}-image'),
            )
            for n in ['topcenter', 'topright', 'middleright', 'bottomright', 'bottomcenter', 'bottomleft', 'middleleft', 'topleft']
        ]

    def show_pie_menu(self, options, fn_callback, highlighted=None, release=None, always_callback=False):
        if len(options) == 0: return
        assert len(options) <= 8, f'Unhandled number of pie menu options ({len(options)}): {options}'
        self.pie_menu_callback = fn_callback
        self.pie_menu_options = options
        self.pie_menu_highlighted = highlighted
        self.pie_menu_release = release or 'pie menu'
        self.pie_menu_always_callback = always_callback
        self.fsm.force_set_state('pie menu')



    def alert_user(self, message=None, title=None, level=None, msghash=None):
        show_quit = False
        level = level.lower() if level else 'note'
        blender_version = '%d.%02d.%d' % bpy.app.version
        blender_branch = bpy.app.build_branch.decode('utf-8')
        blender_date = bpy.app.build_commit_date.decode('utf-8')
        darken = False

        ui_checker = None
        ui_show = None
        message_orig = message
        report_details = ''
        msg_report = None

        if title is None and self.rftool: title = self.rftool.name

        def screenshot():
            ss_filename = options['screenshot filename']
            if getattr(bpy.data, 'filepath', ''):
                # loaded .blend file
                filepath = os.path.split(os.path.abspath(bpy.data.filepath))[0]
                filepath = os.path.join(filepath, ss_filename)
            else:
                # startup file
                filepath = os.path.abspath(ss_filename)
            bpy.ops.screen.screenshot(filepath=filepath)
            self.alert_user(message=f'Saved screenshot to "{filepath}"')
        def open_issues():
            bpy.ops.wm.url_open(url=retopoflow_issues_url)
        def search():
            url = f'https://github.com/CGCookie/retopoflow/issues?q=is%3Aissue+{msghash}'
            bpy.ops.wm.url_open(url=url)
        def report():
            nonlocal msg_report
            nonlocal report_details

            path = abspath('..', '..', 'help', 'issue_template_simple.md')
            issue_template = open(path, 'rt').read()
            data = {
                'title': f'{self.rftool.name}: {title}',
                'body': f'{issue_template}\n\n```\n{msg_report}\n```',
            }
            url =  f'{options["github new issue url"]}?{urllib.parse.urlencode(data)}'
            bpy.ops.wm.url_open(url=url)

        if msghash:
            ui_checker = UI_Element.DETAILS(classes='issue-checker', open=True)
            UI_Element.SUMMARY(innerText='Report an issue', parent=ui_checker)
            ui_label = ui.markdown(mdown='Checking reported issues...', parent=ui_checker)
            ui_buttons = UI_Element.DIV(parent=ui_checker, classes='action-buttons')

            def check_github():
                nonlocal win, ui_buttons
                buttons = 4
                try:
                    if self.GitHub_checks < self.GitHub_limit:
                        self.GitHub_checks += 1
                        # attempt to see if this issue already exists!
                        # note: limited to 60 requests/hour!  see
                        #     https://developer.github.com/v3/#rate-limiting
                        #     https://developer.github.com/v3/search/#rate-limit

                        # make it unsecure to work around SSL issue
                        # https://medium.com/@moreless/how-to-fix-python-ssl-certificate-verify-failed-97772d9dd14c
                        import ssl
                        if (not os.environ.get('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None)):
                            ssl._create_default_https_context = ssl._create_unverified_context

                        url = "https://api.github.com/repos/CGCookie/retopoflow/issues?state=all"
                        response = urllib.request.urlopen(url)
                        text = response.read().decode('utf-8')
                        issues = json.loads(text)
                        exists,solved,issueurl = False,False,None
                        for issue in issues:
                            if msghash not in issue['body']: continue
                            issueurl = issue['html_url']
                            exists = True
                            if issue['state'] == 'closed': solved = True
                        if not exists:
                            print('GitHub: Not reported, yet')
                            ui.set_markdown(ui_label, 'This issue does not appear to be reported, yet.\n\nPlease consider reporting it so we can fix it.')
                        else:
                            if not solved:
                                print('GitHub: Already reported!')
                                ui.set_markdown(ui_label, 'This issue appears to have been reported already.\n\nClick Open button to see the current status.')
                            else:
                                print('GitHub: Already solved!')
                                ui.set_markdown(ui_label, 'This issue appears to have been solved already!\n\nAn updated RetopoFlow should fix this issue.')
                            def go():
                                bpy.ops.wm.url_open(url=issueurl)
                            UI_Element.BUTTON(innerText='Open', on_mouseclick=go, title='Open this issue on the RetopoFlow Issue Tracker', classes='fifth-size', parent=ui_buttons)
                            buttons = 5
                    else:
                        ui.set_markdown(ui_label, 'Could not run the check.\n\nPlease consider reporting it so we can fix it.')
                except Exception as e:
                    ui.set_markdown(ui_label, 'Sorry, but we could not reach the RetopoFlow Isssues Tracker.\n\nClick the Similar button to search for similar issues.')
                    pass
                    print('Caught exception while trying to pull issues from GitHub')
                    print(f'URL: "{url}"')
                    print(e)
                    # ignore for now
                    pass
                size = f'{"fourth" if buttons==4 else "fifth"}-size'
                UI_Element.BUTTON(innerText='Screenshot', classes=f'action {size}', on_mouseclick=screenshot, title='Save a screenshot of Blender', parent=ui_buttons)
                UI_Element.BUTTON(innerText='Similar',    classes=f'action {size}', on_mouseclick=search, title='Search the RetopoFlow Issue Tracker for similar issues', parent=ui_buttons)
                UI_Element.BUTTON(innerText='All Issues', classes=f'action {size}', on_mouseclick=open_issues, title='Open RetopoFlow Issue Tracker', parent=ui_buttons)
                UI_Element.BUTTON(innerText='Report',     classes=f'action {size}', on_mouseclick=report, title='Report a new issue on the RetopoFlow Issue Tracker', parent=ui_buttons)

            executor = ThreadPoolExecutor()
            executor.submit(check_github)

        if level in {'note'}:
            title = 'Note' + (f': {title}' if title else '')
            message = message or 'a note'
        elif level in {'warning'}:
            title = 'Warning' + (f': {title}' if title else '')
            darken = True
        elif level in {'error'}:
            title = 'Error' + (f': {title}' if title else '!')
            show_quit = True
            darken = True
        elif level in {'assert', 'exception'}:
            if level == 'assert':
                title = 'Assert Error' + (f': {title}' if title else '!')
                desc = 'An internal assertion has failed.'
            else:
                title = 'Unhandled Exception Caught' + (f': {title}' if title else '!')
                desc = 'An unhandled exception was thrown.'

            message = '\n'.join([
                desc,
                'This was unexpected.',
                '',
                'If this happens again, please report as bug so we can fix it.',
                ])

            msg_report = '\n'.join([
                get_environment_details(),
                get_trace_details(self.undo_stack_actions(), msghash=msghash, message=message_orig),
            ])

            def clipboard():
                try: bpy.context.window_manager.clipboard = msg_report
                except: pass

            show_quit = True
            darken = True
        else:
            title = level.upper() + (f': {title}' if title else '')
            message = message or 'a note'

        def close():
            nonlocal win
            if win.parent:
                self.document.body.delete_child(win)
                self.alert_windows -= 1
            if self.document.sticky_element == win:
                self.document.sticky_element = None
            self.document.clear_last_under()
        def mouseleave_event(e):
            nonlocal win
            if not win.is_hovered: close()
        def keypress_event(e):
            if e.key == 'ESC': close()
        def quit():
            self.done()

        if self.alert_windows >= 5:
            return
            #self.exit = True

        win = UI_Element.fromHTMLFile(abspath('alert_dialog.html'))[0]
        self.document.body.append_child(win)
        win.getElementById('alert-title').innerText = title
        ui.markdown(mdown=message, ui_container=win.getElementById('alert-message'))
        if not msg_report and not ui_checker:
            win.getElementById('alert-details').is_visible = False
        if msg_report: win.getElementById('alert-report').innerText = msg_report
        else:          win.getElementById('alert-report').is_visible = False
        if ui_checker: win.getElementById('alert-checker').append_child(ui_checker)
        else:          win.getElementById('alert-checker').is_visible = False
        if not show_quit:
            win.getElementById('alert-close').style = 'width:100%'
            win.getElementById('alert-quit').is_visible = False

        self.document.focus(win)
        self.alert_windows += 1
        if level in {'warning', 'note', None}:
            win.style = 'width:600px;'
            self.document.force_clean(self.actions.context)
            self.document.center_on_mouse(win)
            # self.document.sticky_element = win
            win.dirty(cause='new window', parent=False, children=True)
        else:
            self.document.force_clean(self.actions.context)
            self.document.center_on_mouse(win)
            win.dirty(cause='new window', parent=False, children=True)
        if level in {'note', None}:
            win.add_eventListener('on_mouseleave', mouseleave_event)
            win.add_eventListener('on_keypress', keypress_event)

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

    def blender_ui_set(self, scale_to_unit_box=True, add_rotate=True, hide_target=True):
        # print('RetopoFlow: blender_ui_set', 'scale_to_unit_box='+str(scale_to_unit_box), 'add_rotate='+str(add_rotate))
        bpy.ops.object.mode_set(mode='OBJECT')
        if scale_to_unit_box:
            self.scale_to_unit_box()
            self.scene_scale_set(1.0)
        self.viewaa_simplify()

        self.manipulator_hide() # <---------------------------------------------------------------
        self._space.show_gizmo = True

        if get_preferences().system.use_region_overlap:
            # DO NOT HIDE HEADER WHEN REGION OVERLAP IS OFF!!!
            # bug in 282a (at least)
            self.panels_hide()
        if options['hide overlays']: self.overlays_hide()
        self.region_darken()
        self.header_text_set('RetopoFlow')
        self.statusbar_stats_hide()
        if add_rotate: self.setup_rotate_about_active()
        if hide_target: self.hide_target()

    def blender_ui_reset(self, ignore_panels=False):
        # IMPORTANT: changes here should also go in rf_blendersave.backup_recover()
        self.end_rotate_about_active()
        self.teardown_target()
        self.unscale_from_unit_box()
        self.restore_window_state(ignore_panels=ignore_panels)
        self._cc_blenderui_end(ignore_panels=ignore_panels)
        bpy.ops.object.mode_set(mode='EDIT')

    @contextlib.contextmanager
    def blender_ui_pause(self):
        self.blender_ui_reset()
        yield None
        self.blender_ui_set()

    def update_ui_geometry(self):
        vis = self.ui_geometry.is_visible
        # TODO: FIX WORKAROUND HACK!
        #       toggle visibility as workaround hack for relaying out table :(
        if vis: self.ui_geometry.is_visible = False
        self.ui_geometry_verts.innerText = str(self.rftarget.get_vert_count())
        self.ui_geometry_edges.innerText = str(self.rftarget.get_edge_count())
        self.ui_geometry_faces.innerText = str(self.rftarget.get_face_count())
        if vis: self.ui_geometry.is_visible = True

    def setup_ui_blender(self):
        self.blender_ui_set(scale_to_unit_box=False, add_rotate=False, hide_target=False)

    def show_geometry_window(self):
        options['show geometry window'] = True
        self.ui_geometry.is_visible = True
        self.ui_main.getElementById('show-geometry').disabled = True
    def hide_geometry_window(self):
        options['show geometry window'] = False
        self.ui_geometry.is_visible = False
        self.ui_main.getElementById('show-geometry').disabled = False
    def update_geometry_window_visibility(self):
        visible = self.ui_geometry.is_visible
        options['show geometry window'] = visible
        self.ui_main.getElementById('show-geometry').disabled = visible

    def show_options_window(self):
        options['show options window'] = True
        self.ui_options.is_visible = True
        self.ui_main.getElementById('show-options').disabled = True
    def hide_options_window(self):
        options['show options window'] = False
        self.ui_options.is_visible = False
        self.ui_main.getElementById('show-options').disabled = False
    def update_options_window_visibility(self):
        visible = self.ui_options.is_visible
        options['show options window'] = visible
        self.ui_main.getElementById('show-options').disabled = visible

    def show_main_ui_window(self):
        options['show main window'] = True
        self.ui_tiny.is_visible = False
        self.ui_main.is_visible = True
    def show_tiny_ui_window(self):
        options['show main window'] = False
        self.ui_tiny.is_visible = True
        self.ui_main.is_visible = False
    def update_main_ui_window(self):
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
        pre = self._ui_windows_updating
        self._ui_windows_updating = True
        self.ui_main.is_visible = options['show main window']
        self.ui_tiny.is_visible = not options['show main window']
        self._ui_windows_updating = pre

    def setup_ui(self):
        # NOTE: lambda is needed on next line so that RF keymaps are bound!
        humanread = lambda x: self.actions.to_human_readable(x, join=' / ')

        self.hide_target()

        # load ui.css
        self.reload_stylings()

        self._var_auto_hide_options = BoundBool('''options['tools autohide']''', on_change=self.update_ui)

        self.alert_windows = 0
        rf_starting_tool = getattr(self, 'rf_starting_tool', None) or options['quickstart tool']

        def setup_counts_ui():
            self.ui_geometry = UI_Element.fromHTMLFile(abspath('geometry.html'))[0]
            self.document.body.append_child(self.ui_geometry)
            self.ui_geometry_verts = self.ui_geometry.getElementById('geometry-verts')
            self.ui_geometry_edges = self.ui_geometry.getElementById('geometry-edges')
            self.ui_geometry_faces = self.ui_geometry.getElementById('geometry-faces')
            self.update_ui_geometry()
            if options['show geometry window']:
                self.show_geometry_window()
            else:
                self.hide_geometry_window()

        def setup_tiny_ui():
            nonlocal humanread
            self.ui_tiny = UI_Element.fromHTMLFile(abspath('main_tiny.html'))[0]
            self.document.body.append_child(self.ui_tiny)

        def setup_main_ui():
            nonlocal humanread
            self.ui_main = UI_Element.fromHTMLFile(abspath('main_full.html'))[0]
            self.document.body.append_child(self.ui_main)

        def setup_tool_buttons():
            ui_tools  = self.ui_main.getElementById('tools')
            ui_ttools = self.ui_tiny.getElementById('ttools')
            def add_tool(rftool):               # IMPORTANT: must be a fn so that local vars are unique and correctly captured
                nonlocal self, humanread        # IMPORTANT: need this so that these are captured
                title = f'{rftool.name}: {rftool.description}. Shortcut: {humanread(rftool.shortcut)}'
                val = f'{rftool.name.lower()}'
                ui_tools.append_child(UI_Element.fromHTML(
                    f'<label title="{title}" class="tool">'
                    f'<input type="radio" id="tool-{val}" value="{val}" name="tool" class="tool" on_input="if this.checked: self.select_rftool(rftool)">'
                    f'<img src="{rftool.icon}">'
                    f'<span>{rftool.name}</span>'
                    f'</label>'
                )[0])
                ui_ttools.append_child(UI_Element.fromHTML(
                    f'<label title="{title}" class="ttool">'
                    f'<input type="radio" id="ttool-{val}" value="{val}" name="ttool" class="ttool" on_input="if this.checked: self.select_rftool(rftool)">'
                    f'<img src="{rftool.icon}">'
                    f'</label>'
                )[0])
            for rftool in self.rftools: add_tool(rftool)

        def setup_options():
            nonlocal self

            self.document.defer_cleaning = True

            self.ui_options = UI_Element.fromHTMLFile(abspath('options_dialog.html'))[0]
            self.document.body.append_child(self.ui_options)

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
                if getattr(rftool, 'ui_config', None):
                    path_folder = os.path.dirname(inspect.getfile(rftool.__class__))
                    path_html = os.path.join(path_folder, rftool.ui_config)
                    ret = rftool.call_with_self_in_context(UI_Element.fromHTMLFile, path_html)
                    add_elem(ret)
                ret = rftool._callback('ui setup')
                add_elem(ret)

                self.rftools_ui[rftool] = ui_elems
                for ui_elem in ui_elems:
                    self.ui_options.getElementById('options-contents').append_child(ui_elem)

            if options['show options window']:
                self.show_options_window()
            else:
                self.hide_options_window()

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

            self.ui_quit = UI_Element.fromHTMLFile(abspath('quit_dialog.html'))[0]
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
                self.delete_dissolve_option(opt)
                hide_ui_delete()

            self.ui_delete = UI_Element.fromHTMLFile(abspath('delete_dialog.html'))[0]
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
        if not options['welcome']: return
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
