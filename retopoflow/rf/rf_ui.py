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
from ...addon_common.common.boundvar import BoundVar, BoundBool, BoundFloat
from ...addon_common.common.utils import delay_exec
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
        self.ui_pie_menu = ui.div(id='pie-menu', atomic=True, can_hover=False, parent=self.document.body, children=[
            ui.table(id='pie-menu-table', children=[
                ui.tr(id='pie-menu-top', children=[
                    ui.td(classes='pie-menu-section', children=[
                        ui.div(id='pie-menu-topleft', classes='pie-menu-option', children=[
                            ui.div(id='pie-menu-topleft-text',       classes='pie-menu-option-text'),
                            ui.img(id='pie-menu-topleft-image',      classes='pie-menu-option-image'),
                        ]),
                    ]),
                    ui.td(classes='pie-menu-section', children=[
                        ui.div(id='pie-menu-topcenter', classes='pie-menu-option', children=[
                            ui.div(id='pie-menu-topcenter-text',     classes='pie-menu-option-text'),
                            ui.img(id='pie-menu-topcenter-image',    classes='pie-menu-option-image'),
                        ]),
                    ]),
                    ui.td(classes='pie-menu-section', children=[
                        ui.div(id='pie-menu-topright', classes='pie-menu-option', children=[
                            ui.div(id='pie-menu-topright-text',      classes='pie-menu-option-text'),
                            ui.img(id='pie-menu-topright-image',     classes='pie-menu-option-image'),
                        ]),
                    ]),
                ]),
                ui.tr(id='pie-menu-middle', children=[
                    ui.td(classes='pie-menu-section', children=[
                        ui.div(id='pie-menu-middleleft', classes='pie-menu-option', children=[
                            ui.div(id='pie-menu-middleleft-text',    classes='pie-menu-option-text'),
                            ui.img(id='pie-menu-middleleft-image',   classes='pie-menu-option-image'),
                        ]),
                    ]),
                    ui.td(classes='pie-menu-section', children=[
                        ui.div(id='pie-menu-middlecenter', classes='pie-menu-option', children=[
                            ui.div(id='pie-menu-middlecenter-text',  classes='pie-menu-option-text'),
                            ui.img(id='pie-menu-middlecenter-image', classes='pie-menu-option-image'),
                        ]),
                    ]),
                    ui.td(classes='pie-menu-section', children=[
                        ui.div(id='pie-menu-middleright', classes='pie-menu-option', children=[
                            ui.div(id='pie-menu-middleright-text',   classes='pie-menu-option-text'),
                            ui.img(id='pie-menu-middleright-image',  classes='pie-menu-option-image'),
                        ]),
                    ]),
                ]),
                ui.tr(id='pie-menu-bottom', children=[
                    ui.td(classes='pie-menu-section', children=[
                        ui.div(id='pie-menu-bottomleft', classes='pie-menu-option', children=[
                            ui.div(id='pie-menu-bottomleft-text',    classes='pie-menu-option-text'),
                            ui.img(id='pie-menu-bottomleft-image',   classes='pie-menu-option-image'),
                        ]),
                    ]),
                    ui.td(classes='pie-menu-section', children=[
                        ui.div(id='pie-menu-bottomcenter', classes='pie-menu-option', children=[
                            ui.div(id='pie-menu-bottomcenter-text',  classes='pie-menu-option-text'),
                            ui.img(id='pie-menu-bottomcenter-image', classes='pie-menu-option-image'),
                        ]),
                    ]),
                    ui.td(classes='pie-menu-section', children=[
                        ui.div(id='pie-menu-bottomright', classes='pie-menu-option', children=[
                            ui.div(id='pie-menu-bottomright-text',   classes='pie-menu-option-text'),
                            ui.img(id='pie-menu-bottomright-image',  classes='pie-menu-option-image'),
                        ]),
                    ]),
                ]),
            ])
        ])
        self.ui_pie_table = self.document.body.getElementById('pie-menu-table')
        # 7 0 1
        # 6   2
        # 5 4 3
        self.ui_pie_sections = [
            (
                self.document.body.getElementById(f'pie-menu-{n}'),
                self.document.body.getElementById(f'pie-menu-{n}-text'),
                self.document.body.getElementById(f'pie-menu-{n}-image'),
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
        ui_details = None
        ui_show = None
        message_orig = message
        report_details = ''

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

            path = os.path.join(os.path.dirname(__file__), '..', '..', 'help', 'issue_template_simple.md')
            issue_template = open(path, 'rt').read()
            data = {
                'title': f'{self.rftool.name}: {title}',
                'body': f'{issue_template}\n\n```\n{msg_report}\n```',
            }
            url =  f'{options["github new issue url"]}?{urllib.parse.urlencode(data)}'
            bpy.ops.wm.url_open(url=url)

        if msghash:
            ui_checker = ui.details(classes='issue-checker', open=True)
            ui.summary(innerText='Report an issue', parent=ui_checker)
            ui_label = ui.markdown(mdown='Checking reported issues...', parent=ui_checker)
            ui_buttons = ui.div(parent=ui_checker, classes='action-buttons')

            def check_github():
                nonlocal win, ui_buttons
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
                            ui.button(innerText='Open', on_mouseclick=go, title='Open this issue on the RetopoFlow Issue Tracker', parent=ui_buttons)
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
                ui.button(innerText='Screenshot', classes='action', on_mouseclick=screenshot, title='Save a screenshot of Blender', parent=ui_buttons)
                ui.button(innerText='Similar', classes='action', on_mouseclick=search, title='Search the RetopoFlow Issue Tracker for similar issues', parent=ui_buttons)
                ui.button(innerText='All Issues', classes='action', on_mouseclick=open_issues, title='Open RetopoFlow Issue Tracker', parent=ui_buttons)
                ui.button(innerText='Report', classes='action', on_mouseclick=report, title='Report a new issue on the RetopoFlow Issue Tracker', parent=ui_buttons)

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

            ui_details = ui.details(id='crashdetails', children=[
                ui.summary(innerText='Crash details'),
                ui.label(innerText='Crash Details:', style="border:0px; padding:0px; margin:0px"),
                ui.pre(innerText=msg_report),
                ui.button(innerText='Copy details to clipboard', on_mouseclick=clipboard, title='Copy crash details to clipboard'),
            ])

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

        win = ui.framed_dialog(label=title, classes=f'alertdialog {level}', close_callback=close, parent=self.document.body)
        ui.markdown(mdown=message, parent=win)
        if ui_details or ui_checker:
            container = ui.div(parent=win)
            if ui_details:
                container.append_child(ui_details)
            if ui_checker:
                container.append_child(ui_checker)
        ui_bottombuttons = ui.div(classes='alertdialog-buttons', parent=win)
        ui_close = ui.button(innerText='Close', on_mouseclick=close, title='Close this alert window', parent=ui_bottombuttons)
        if show_quit:
            ui.button(innerText='Exit', on_mouseclick=quit, title='Exit RetopoFlow', parent=ui_bottombuttons)
        else:
            ui_close.style = 'width:100%'

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
        self.ui_show_geometry.disabled = True
    def hide_geometry_window(self):
        options['show geometry window'] = False
        self.ui_geometry.is_visible = False
        self.ui_show_geometry.disabled = False

    def show_options_window(self):
        options['show options window'] = True
        self.ui_options.is_visible = True
        self.ui_show_options.disabled = True
    def hide_options_window(self):
        options['show options window'] = False
        self.ui_options.is_visible = False
        self.ui_show_options.disabled = False

    def show_main_ui_window(self):
        options['show main window'] = True
        self.ui_tiny.is_visible = False
        self.ui_main.is_visible = True
    def show_tiny_ui_window(self):
        options['show main window'] = False
        self.ui_tiny.is_visible = True
        self.ui_main.is_visible = False

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
            self.ui_geometry = ui.framed_dialog(
                label="Poly Count",
                id="geometrydialog",
                left=0,
                resizable=False,
                closeable=True,
                hide_on_close=True,
                close_callback=self.hide_geometry_window,
                parent=self.document.body,
                children=[
                    ui.table(children=[
                        ui.tr(children=[
                            ui.td(children=[ui.div(innerText='Verts:')]),
                            ui.td(children=[ui.div(innerText='0', id='geometry-verts')]),
                        ]),
                        ui.tr(children=[
                            ui.td(children=[ui.div(innerText='Edges:')]),
                            ui.td(children=[ui.div(innerText='0', id='geometry-edges')]),
                        ]),
                        ui.tr(children=[
                            ui.td(children=[ui.div(innerText='Faces:')]),
                            ui.td(children=[ui.div(innerText='0', id='geometry-faces')]),
                        ]),
                    ])
                ],
            )
            self.ui_geometry_verts = self.ui_geometry.getElementById('geometry-verts')
            self.ui_geometry_edges = self.ui_geometry.getElementById('geometry-edges')
            self.ui_geometry_faces = self.ui_geometry.getElementById('geometry-faces')
            self.update_ui_geometry()
            if options['show geometry window']:
                self.show_geometry_window()
            else:
                self.hide_geometry_window()

        def setup_tiny_ui():
            self.ui_tiny = ui.framed_dialog(
                label=f'RetopoFlow {retopoflow_version}',
                id='tinydialog',
                closeable=False,
                hide_on_close=True,
                close_callback=self.show_main_ui_window,
                is_visible=False,
                parent=self.document.body,
            )
            ui_tools = ui.div(id='ttools', parent=self.ui_tiny)
            ui.button(title='Maximize this window', classes='dialog-expand', on_mouseclick=self.show_main_ui_window, parent=ui_tools)
            def add_tool(rftool):   # IMPORTANT: must be a fn so that local vars are unique and correctly captured
                nonlocal self       # IMPORTANT: need this so that self is captured in delay_exec below
                lbl, img = rftool.name, rftool.icon
                id_radio = f'ttool-{lbl.lower()}'
                title = f'{rftool.name}: {rftool.description}. Shortcut: {humanread(rftool.shortcut)}'
                checked = (rftool.name == rf_starting_tool)
                # if checked: self.select_rftool(rftool)
                ui_label = ui.label(
                    title=title,
                    classes="ttool",
                    parent=ui_tools,
                    children=[
                        ui.input_radio(
                            id=id_radio,
                            value=lbl.lower(),
                            title=title,
                            name='ttool',
                            classes='ttool',
                            checked=checked,
                        ),
                        ui.img(
                            src=img,
                            title=title,
                        ),
                    ],
                )
                ui_radio = ui_label.getElementById(id_radio)
                ui_radio.add_eventListener('on_input', delay_exec('''if ui_radio.checked: self.select_rftool(rftool)'''))
            for rftool in self.rftools: add_tool(rftool)
            # ui_close = UI_Element(tagName='button', classes='dialog-close', title=title, on_mouseclick=close, parent=ui_header)

        def debug_doc(ui, level=0):
            print(f"{'  '*level} {ui}: document={ui.document}, root={ui.get_root()}")
            if type(ui) is UI_Proxy:
                print(f"{'  '*(level+1)} {ui.proxy_default_element}: document={ui.proxy_default_element.document}, root={ui.proxy_default_element.get_root()}")
            for c in ui.children:
                debug_doc(c, level+1)

        def setup_main_ui():
            self.ui_main = ui.framed_dialog(
                label=f'RetopoFlow {retopoflow_version}',
                id="maindialog",
                closeable=False,
                parent=self.document.body,
            )

            # tools
            ui_tools = ui.div(id="tools", parent=self.ui_main)
            def add_tool(rftool):   # IMPORTANT: must be a fn so that local vars are unique and correctly captured
                nonlocal self       # IMPORTANT: need this so that self is captured in delay_exec below
                lbl, img = rftool.name, rftool.icon
                id_radio = f'tool-{lbl.lower()}'
                title = f'{rftool.name}: {rftool.description}. Shortcut: {humanread(rftool.shortcut)}'
                checked = (rftool.name == rf_starting_tool)
                # if checked: self.select_rftool(rftool)
                ui_label = ui.label(
                    title=title,
                    classes="tool",
                    parent=ui_tools,
                    children=[
                        ui.input_radio(
                            id=id_radio,
                            value=lbl.lower(),
                            title=title,
                            name='tool',
                            classes='tool',
                            checked=checked,
                        ),
                        ui.img(
                            src=img,
                            title=title,
                        ),
                        ui.span(
                            innerText=lbl,
                            title=title,
                        ),
                    ],
                )
                ui_radio = ui_label.getElementById(id_radio)
                ui_radio.add_eventListener('on_input', delay_exec('''if ui_radio.checked: self.select_rftool(rftool)'''))
            for rftool in self.rftools: add_tool(rftool)

            ui_help = ui.details(id='help-buttons', parent=self.ui_main, children=[
                ui.summary(innerText='Documentation'),
                ui.div(classes='contents', children=[
                    ui.button(
                        innerText='Welcome!',
                        title='Show the "Welcome!" message from the RetopoFlow team',
                        on_mouseclick=delay_exec("self.helpsystem_open('welcome.md')")
                    ),
                    ui.button(
                        innerText='Table of Contents',
                        title=f'Show help table of contents ({humanread("all help")})',
                        on_mouseclick=delay_exec("self.helpsystem_open('table_of_contents.md')")
                    ),
                    ui.button(
                        innerText='Quick start guide',
                        title='Show how to get started with RetopoFlow',
                        on_mouseclick=delay_exec("self.helpsystem_open('quick_start.md')")
                    ),
                    ui.button(
                        innerText='General',
                        title=f'Show general help ({humanread("general help")})',
                        on_mouseclick=delay_exec("self.helpsystem_open('general.md')")
                    ),
                    ui.button(
                        innerText='Active Tool',
                        title=f'Show help for currently selected tool ({humanread("tool help")})',
                        on_mouseclick=delay_exec("self.helpsystem_open(self.rftool.help)")
                    ),
                ]),
            ])
            ui_show = ui.details(parent=self.ui_main, children=[
                ui.summary(innerText='Windows'),
                ui.div(classes='contents', children=[
                    ui.button(innerText='Minimize Tools', title='Minimize this window', on_mouseclick=self.show_tiny_ui_window),
                    ui.button(innerText='Show Options', title='Show options window', id='show-options', disabled=True, on_mouseclick=self.show_options_window),
                    ui.button(innerText='Show Poly Count', title='Show poly count window', id='show-geometry', disabled=True, on_mouseclick=self.show_geometry_window),
                ]),
            ])
            self.ui_show_options = ui_show.getElementById('show-options')
            self.ui_show_geometry = ui_show.getElementById('show-geometry')
            ui.button(innerText='Report Issue', title='Report an issue with RetopoFlow', parent=self.ui_main, on_mouseclick=delay_exec("bpy.ops.wm.url_open(url=retopoflow_issues_url)"))
            ui.button(innerText='Exit', title=f'Quit RetopoFlow ({humanread("done")})', parent=self.ui_main, on_mouseclick=self.done)
            if False:
                ui.button(innerText='Reload Styles', parent=self.ui_main, on_mouseclick=self.reload_stylings)
            if False:
                def printout_profiler():
                    profiler.printout()
                    print("Children: %d" % self.document.body.count_children())
                ui.button(innerText='Profiler', parent=self.ui_main, on_mouseclick=printout_profiler)
                ui.button(innerText='Profiler Clear', parent=self.ui_main, on_mouseclick=profiler.reset)


        def setup_options():
            self.ui_options = ui.framed_dialog(
                label='Options',
                id='optionsdialog',
                right=0,
                closeable=True,
                hide_on_close=True,
                close_callback=self.hide_options_window,
                parent=self.document.body,
            )
            self.document.defer_cleaning = True

            options['remove doubles dist']

            def theme_change(e):
                if not e.target.checked: return
                if e.target.value is None: return
                options['color theme'] = e.target.value
            def reset_options():
                options.reset()
                self.update_ui()
                self.document.body.dirty(children=True)
            def update_hide_overlays():
                if options['hide overlays']: self.overlays_hide()
                else: self.overlays_restore()

            ui.details(title='General options', id='generaloptions', parent=self.ui_options, children=[
                ui.summary(innerText='General'),
                ui.div(classes='contents', children=[
                    ui.div(classes='collection', children=[
                        ui.h1(
                            innerText='Quit Options',
                            title='These options control quitting RetopoFlow',
                        ),
                        ui.label(
                            innerText='Confirm quit on Tab',
                            title='Check to confirm quitting when pressing Tab',
                            children=[
                                ui.input_checkbox(
                                    title='Check to confirm quitting when pressing Tab',
                                    checked=BoundBool('''options['confirm tab quit']'''),
                                ),
                            ],
                        ),
                        ui.label(
                            innerText='Escape to Quit',
                            title='Check to allow Esc key to quit RetopoFlow',
                            children=[
                                ui.input_checkbox(
                                    title='Check to allow Esc key to quit RetopoFlow',
                                    checked=BoundBool('''options['escape to quit']'''),
                                ),
                            ],
                        ),
                    ]),
                    ui.div(classes='collection', children=[
                        ui.h1(
                            innerText='Start Up Checks',
                            title='These options control what checks are run when RetopoFlow starts',
                        ),
                        ui.label(
                            innerText='Check Auto Save',
                            title='If enabled, check if Auto Save is disabled at start',
                            children=[
                                ui.input_checkbox(
                                    title='If enabled, check if Auto Save is disabled at start',
                                    checked=BoundBool('''options['check auto save']'''),
                                ),
                            ],
                        ),
                        ui.label(
                            innerText='Check Unsaved',
                            title='If enabled, check if blend file is unsaved at start',
                            children=[
                                ui.input_checkbox(
                                    title='If enabled, check if blend file is unsaved at start',
                                    checked=BoundBool('''options['check unsaved']'''),
                                ),
                            ],
                        ),
                    ]),
                    ui.details(children=[
                        ui.summary(innerText='Advanced'),
                        ui.div(
                            classes='contents',
                            children=[
                                ui.div(classes='collection', children=[
                                    ui.h1(innerText='Keyboard Settings'),
                                    ui.labeled_input_text(label='Repeat Delay', title='Set delay time before keyboard start repeating', value=BoundFloat('''options['keyboard repeat delay']''', min_value=0.02)),
                                    ui.labeled_input_text(label='Repeat Pause', title='Set pause time between keyboard repeats', value=BoundFloat('''options['keyboard repeat pause']''', min_value=0.02)),
                                    ui.button(innerText='Reset Keyboard Settings', on_mouseclick=delay_exec('''options.reset(keys=['keyboard repeat delay','keyboard repeat pause'], version=False)''')),
                                ]),
                                ui.div(classes='collection', children=[
                                    ui.h1(
                                        innerText='Visibility Testing',
                                        title='These options are used to tune the parameters for visibility testing',
                                    ),
                                    ui.labeled_input_text(label='BBox Factor', title='Factor on minimum bounding box dimension', value=BoundFloat('''options['visible bbox factor']''', min_value=0.0, max_value=1.0, on_change=self.get_vis_accel)),
                                    ui.labeled_input_text(label='Distance Offset', title='Offset added to max distance', value=BoundFloat('''options['visible dist offset']''', min_value=0.0, max_value=1.0, on_change=self.get_vis_accel)),
                                    ui.div(classes='collection', children=[
                                        ui.h1(innerText='Presets'),
                                        ui.button(innerText='Tiny', title='Preset options for working on tiny objects', classes='half-size', on_mouseclick=self.visibility_preset_tiny),
                                        ui.button(innerText='Normal', title='Preset options for working on normal-sized objects', classes='half-size', on_mouseclick=self.visibility_preset_normal),
                                    ]),
                                ]),
                                ui.div(classes='collection', children=[
                                    ui.h1(innerText='Debugging'),
                                    ui.div(innerText='FPS: 0', id='fpsdiv'),
                                    ui.label(
                                        innerText='Print actions',
                                        title='Check to print (most) input actions to system console',
                                        children=[
                                            ui.input_checkbox(
                                                title='Check to print (most) input actions to system console',
                                                checked=BoundBool('''self._debug_print_actions'''),
                                            ),
                                        ],
                                    ),
                                ]),
                                ui.button(innerText='Reset All Settings', title='Reset RetopoFlow back to factory settings', on_mouseclick=reset_options),
                            ],
                        ),
                    ]),
                ]),
            ]),
            ui.details(title='Display options', id='view-options', parent=self.ui_options, children=[
                ui.summary(innerText='Display'),
                ui.div(
                    classes='contents',
                    children=[
                        ui.label(
                            innerText='Auto Hide Tool Options',
                            title='If enabled, options for selected tool will show while other tool options hide.',
                            children=[
                                ui.input_checkbox(
                                    title='If enabled, options for selected tool will show while other tool options hide.',
                                    checked=self._var_auto_hide_options,
                                ),
                            ],
                        ),
                        ui.label(
                            innerText='Hide Overlays',
                            title='If enabled, overlays (source wireframes, grid, axes, etc.) are hidden.',
                            children=[
                                ui.input_checkbox(
                                    title='If enabled, overlays (source wireframes, grid, axes, etc.) are hidden.',
                                    checked=BoundBool('''options['hide overlays']'''),
                                    on_input=update_hide_overlays,
                                ),
                            ],
                        ),
                        ui.labeled_input_text(label='UI Scale', title='Custom UI scaling setting', value=BoundFloat('''options['ui scale']''', min_value=0.25, max_value=4)),
                        ui.div(classes='collection', children=[
                            ui.h1(innerText='Theme'),
                            ui.label(
                                innerText='Green',
                                title='Draw the target mesh using a green theme.',
                                forId='theme-color-green',
                                classes='third-size',
                                children=[
                                    ui.input_radio(
                                        id='theme-color-green',
                                        title='Draw the target mesh using a green theme.',
                                        value='Green',
                                        checked=(options['color theme']=='Green'),
                                        name='theme-color',
                                        on_input=theme_change,
                                    ),
                                ],
                            ),
                            ui.label(
                                innerText='Blue',
                                title='Draw the target mesh using a blue theme.',
                                forId='theme-color-blue',
                                classes='third-size',
                                children=[
                                    ui.input_radio(
                                        id='theme-color-blue',
                                        title='Draw the target mesh using a blue theme.',
                                        value='Blue',
                                        checked=(options['color theme']=='Blue'),
                                        name='theme-color',
                                        on_input=theme_change,
                                    ),
                                ],
                            ),
                            ui.label(
                                innerText='Orange',
                                title='Draw the target mesh using a orange theme.',
                                forId='theme-color-orange',
                                classes='third-size',
                                children=[
                                    ui.input_radio(
                                        id='theme-color-orange',
                                        title='Draw the target mesh using a orange theme.',
                                        value='Orange',
                                        checked=(options['color theme']=='Orange'),
                                        name='theme-color',
                                        on_input=theme_change,
                                    ),
                                ],
                            ),
                        ]),
                        ui.div(classes='collection', id='clipping', children=[
                            ui.h1(innerText='Clipping'),
                            ui.labeled_input_text(label='Start', title='Near clipping distance', value=BoundFloat('''self.actions.space.clip_start''', min_value=0)),
                            ui.labeled_input_text(label='End', title='Far clipping distance', value=BoundFloat('''self.actions.space.clip_end''', min_value=0)),
                        ]),
                        ui.div(classes='collection', children=[
                            ui.h1(innerText='Target Drawing'),
                            ui.labeled_input_text(label='Normal Offset', title='Sets how far geometry is pushed in visualization', value=BoundFloat('''options['normal offset multiplier']''', min_value=0.0, max_value=2.0)),
                            ui.labeled_input_text(label='Alpha Above', title='Set transparency of target mesh that is above the source', value=BoundFloat('''options['target alpha']''', min_value=0.0, max_value=1.0)),
                            ui.labeled_input_text(label='Alpha Below', title='Set transparency of target mesh that is below the source', value=BoundFloat('''options['target hidden alpha']''', min_value=0.0, max_value=1.0)),
                            ui.labeled_input_text(label='Vertex Size', title='Draw radius of vertices.', value=BoundFloat('''options['target vert size']''', min_value=0.1)),
                            ui.labeled_input_text(label='Edge Size', title='Draw width of edges.', value=BoundFloat('''options['target edge size']''', min_value=0.1)),
                            ui.details(children=[
                                ui.summary(innerText='Individual Alpha Values'),
                                ui.div(
                                    classes='contents',
                                    children=[
                                        ui.div(classes='collection', children=[
                                            ui.h1(innerText='Verts'),
                                            ui.labeled_input_text(label='Normal', title='Set transparency of normal target vertices', value=BoundFloat('''options['target alpha point']''', min_value=0.0, max_value=1.0)),
                                            ui.labeled_input_text(label='Selected', title='Set transparency of selected target vertices', value=BoundFloat('''options['target alpha point selected']''', min_value=0.0, max_value=1.0)),
                                            ui.labeled_input_text(label='Mirror', title='Set transparency of mirrored target vertices', value=BoundFloat('''options['target alpha point mirror']''', min_value=0.0, max_value=1.0)),
                                            ui.labeled_input_text(label='Mirror Selected', title='Set transparency of selected, mirrored target vertices', value=BoundFloat('''options['target alpha point mirror selected']''', min_value=0.0, max_value=1.0)),
                                            ui.labeled_input_text(label='Highlight', title='Set transparency of highlighted target vertices', value=BoundFloat('''options['target alpha point highlight']''', min_value=0.0, max_value=1.0)),
                                        ]),
                                        ui.div(classes='collection', children=[
                                            ui.h1(innerText="Edges"),
                                            ui.labeled_input_text(label='Normal', title='Set transparency of normal target edges', value=BoundFloat('''options['target alpha line']''', min_value=0.0, max_value=1.0)),
                                            ui.labeled_input_text(label='Selected', title='Set transparency of selected target edges', value=BoundFloat('''options['target alpha line selected']''', min_value=0.0, max_value=1.0)),
                                            ui.labeled_input_text(label='Mirror', title='Set transparency of mirrored target edges', value=BoundFloat('''options['target alpha line mirror']''', min_value=0.0, max_value=1.0)),
                                            ui.labeled_input_text(label='Mirror Selected', title='Set transparency of selected, mirrored target edges', value=BoundFloat('''options['target alpha line mirror selected']''', min_value=0.0, max_value=1.0)),
                                        ]),
                                        ui.div(classes='collection', children=[
                                            ui.h1(innerText='Faces'),
                                            ui.labeled_input_text(label='Normal', title='Set transparency of normal target faces', value=BoundFloat('''options['target alpha poly']''', min_value=0.0, max_value=1.0)),
                                            ui.labeled_input_text(label='Selected', title='Set transparency of selected target faces', value=BoundFloat('''options['target alpha poly selected']''', min_value=0.0, max_value=1.0)),
                                            ui.labeled_input_text(label='Mirror', title='Set transparency of mirrored target faces', value=BoundFloat('''options['target alpha poly mirror']''', min_value=0.0, max_value=1.0)),
                                            ui.labeled_input_text(label='Mirror Selected', title='Set transparency of selected, mirrored target faces', value=BoundFloat('''options['target alpha poly mirror selected']''', min_value=0.0, max_value=1.0)),
                                        ]),
                                    ],
                                ),
                            ]),
                        ]),
                        ui.details(children=[
                            ui.summary(innerText='Tooltips'),
                            ui.div(
                                classes='contents',
                                children=[
                                    ui.label(
                                        innerText='Show',
                                        title='Check to show tooltips',
                                        children=[
                                            ui.input_checkbox(
                                                title='Check to show tooltips',
                                                checked=BoundVar('''options['show tooltips']''')
                                            ),
                                        ]
                                    ),
                                    ui.labeled_input_text(label='Delay', title='Set delay before tooltips show', value=BoundFloat('''options['tooltip delay']''', min_value=0.0)),
                                ],
                            ),
                        ]),
                    ],
                ),
            ])

            ui.details(title='Target cleaning options', id='target-cleaning', parent=self.ui_options, children=[
                ui.summary(innerText='Target Cleaning'),
                ui.div(
                    classes='contents',
                    children=[
                        ui.div(classes='collection', children=[
                            ui.h1(innerText='Snap Verts'),
                            ui.button(innerText="All", title='Snap all target vertices to nearest point on source(s).', classes='half-size', on_mouseclick=self.snap_all_verts),
                            ui.button(innerText="Selected", title='Snap selected target vertices to nearest point on source(s).', classes='half-size', on_mouseclick=self.snap_selected_verts),
                        ]),
                        ui.div(classes='collection', children=[
                            ui.h1(innerText='Merge by Distance'),
                            ui.labeled_input_text(label='Distance', title='Distance within which vertices will be merged.', value=BoundFloat('''options['remove doubles dist']''', min_value=0)),
                            ui.button(innerText='All', title='Merge all vertices within given distance.', classes='half-size', on_mouseclick=self.remove_all_doubles),
                            ui.button(innerText='Selected', title='Merge selected vertices within given distance.', classes='half-size', on_mouseclick=self.remove_selected_doubles)
                        ]),
                    ],
                ),
            ])


            def symmetry_viz_change(e):
                if not e.target.checked: return
                options['symmetry view'] = e.target.value

            symmetryoptions = ui.details(title='Symmetry (mirroring) options', id='symmetryoptions', parent=self.ui_options, children=[
                ui.summary(innerText='Symmetry', id='symmetryoptions_summary'),
                ui.div(
                    classes='contents',
                    children=[
                        ui.label(
                            innerText='x',
                            title='Check to mirror along x-axis',
                            classes='symmetry-enable',
                            children=[
                                ui.input_checkbox(
                                    title='Check to mirror along x-axis',
                                    checked=BoundVar('''self.rftarget.mirror_mod.x''')
                                ),
                            ],
                        ),
                        ui.label(
                            innerText='y',
                            title='Check to mirror along y-axis',
                            classes='symmetry-enable',
                            children=[
                                ui.input_checkbox(
                                    title='Check to mirror along y-axis',
                                    checked=BoundVar('''self.rftarget.mirror_mod.y''')
                                ),
                            ],
                        ),
                        ui.label(
                            innerText='z',
                            title='Check to mirror along z-axis',
                            classes='symmetry-enable',
                            children=[
                                ui.input_checkbox(
                                    title='Check to mirror along z-axis',
                                    checked=BoundVar('''self.rftarget.mirror_mod.z''')
                                ),
                            ],
                        ),
                        ui.div(classes='collection', children=[
                            ui.h1(innerText='Visualization'),
                            ui.label(
                                innerText='None',
                                title='If checked, no symmetry will be visualized, even if symmetry is enabled (above).',
                                forId='symmetry-viz-none',
                                classes='third-size',
                                children=[
                                    ui.input_radio(
                                        id='symmetry-viz-none',
                                        title='If checked, no symmetry will be visualized, even if symmetry is enabled (above).',
                                        value='None',
                                        checked=(options['symmetry view']=='None'),
                                        name='symmetry-viz',
                                        on_input=symmetry_viz_change
                                    ),
                                ],
                            ),
                            ui.label(
                                innerText='Edge',
                                title='If checked, symmetry will be visualized as a line, the intersection of the source meshes and the mirroring plane(s).',
                                forId='symmetry-viz-edge',
                                classes='third-size',
                                children=[
                                    ui.input_radio(
                                        id='symmetry-viz-edge',
                                        title='If checked, symmetry will be visualized as a line, the intersection of the source meshes and the mirroring plane(s).',
                                        value='Edge',
                                        checked=(options['symmetry view']=='Edge'),
                                        name='symmetry-viz',
                                        on_input=symmetry_viz_change
                                    ),
                                ],
                            ),
                            ui.label(
                                innerText='Face',
                                title='If checked, symmetry will be visualized by coloring the mirrored side of source mesh(es).',
                                forId='symmetry-viz-face',
                                classes='third-size',
                                children=[
                                    ui.input_radio(
                                        id='symmetry-viz-face',
                                        title='If checked, symmetry will be visualized by coloring the mirrored side of source mesh(es).',
                                        value='Face',
                                        checked=(options['symmetry view']=='Face'),
                                        name='symmetry-viz',
                                        on_input=symmetry_viz_change
                                    ),
                                ],
                            ),
                            ui.labeled_input_text(
                                label='Source Effect',
                                title='Effect of symmetry source visualization.',
                                value=BoundFloat('''options['symmetry effect']''', min_value=0.0, max_value=1.0),
                                scrub=True,
                            ),
                            ui.input_range(
                                title='Effect of symmetry source visualization.',
                                value=BoundFloat('''options['symmetry effect']''', min_value=0.0, max_value=1.0),
                            ),
                            ui.labeled_input_text(
                                label='Target Effect',
                                title='Factor for alpha of mirrored target visualization.',
                                value=BoundFloat('''options['target alpha mirror']''', min_value=0.0, max_value=1.0),
                                scrub=True,
                            ),
                            ui.input_range(
                                title='Factor for alpha of mirrored target visualization.',
                                value=BoundFloat('''options['target alpha mirror']''', min_value=0.0, max_value=1.0),
                            ),
                        ]),
                        ui.labeled_input_text(
                            label='Threshold',
                            title='Distance within which mirrored vertices will be merged.',
                            value=BoundFloat('''self.rftarget.mirror_mod.symmetry_threshold''', min_value=0, step_size=0.01),
                            scrub=True,
                        ),
                        ui.button(
                            innerText='Apply symmetry',
                            title='Apply symmetry to target mesh',
                            on_mouseclick=delay_exec('''self.apply_symmetry()'''),
                        ),
                    ],
                ),
            ])
            symmetryoptions_summary = symmetryoptions.getElementById('symmetryoptions_summary')
            def symmetry_changed():
                s = []
                if self.rftarget.mirror_mod.x: s += ['X']
                if self.rftarget.mirror_mod.y: s += ['Y']
                if self.rftarget.mirror_mod.z: s += ['Z']
                if not s: s = ['(none)']
                symmetryoptions_summary.innerText = f'Symmetry: {",".join(s)}'
            symmetry_changed()
            for opt in symmetryoptions.getElementsByClassName('symmetry-enable'):
                opt.add_eventListener('on_input', symmetry_changed)


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
                    self.ui_options.append_child(ui_elem)
                if getattr(rftool, 'ui_config', None):
                    path_folder = os.path.dirname(inspect.getfile(rftool.__class__))
                    path_html = os.path.join(path_folder, rftool.ui_config)
                    ret = rftool.call_with_self_in_context(UI_Element.fromHTMLFile, path_html)
                    add_elem(ret)
                ret = rftool._callback('ui setup')
                add_elem(ret)

                self.rftools_ui[rftool] = ui_elems
                for ui_elem in ui_elems:
                    self.ui_options.append_child(ui_elem)

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
            def mouseleave_event(e):
                if self.ui_quit.is_hovered: return
                hide_ui_quit()
            def key(e):
                if e.key in {'ESC', 'TAB'}: hide_ui_quit()
                if e.key in {'RET', 'NUMPAD_ENTER'}: self.done()

            self.ui_quit = ui.framed_dialog(
                label='Quit RetopoFlow?',
                id='quitdialog',
                parent=self.document.body,
                resizable_x=False,
                hide_on_close=True,
                close_callback=hide_ui_quit,
                style='width:200px',
                children=[
                    ui.div(children=[
                        ui.button(innerText='Yes (Enter)', on_mouseclick=delay_exec('''self.done()'''), classes='half-size'),
                        ui.button(innerText='No (Esc)', on_mouseclick=delay_exec('''hide_ui_quit()'''), classes='half-size'),
                    ]),
                    ui.label(
                        innerText='Confirm quit on Tab',
                        title='Check to confirm quitting when pressing Tab',
                        children=[
                            ui.input_checkbox(
                                title='Check to confirm quitting when pressing Tab',
                                checked=BoundVar('''options['confirm tab quit']'''),
                            ),
                        ],
                    ),
                ],
            )
            self.ui_quit.is_visible = False
            self.ui_quit.add_eventListener('on_mouseleave', mouseleave_event)
            self.ui_quit.add_eventListener('on_keypress', key)

        def setup_delete_ui():
            def hide_ui_delete():
                self.ui_delete.is_visible = False
                self.document.sticky_element = None
                self.document.clear_last_under()
            def mouseleave_event(e):
                if self.ui_delete.is_hovered: return
                hide_ui_delete()
            def key(e):
                if e.key == 'ESC': hide_ui_delete()

            def act(opt):
                self.delete_dissolve_option(opt)
                hide_ui_delete()

            self.ui_delete = ui.framed_dialog(
                label='Delete/Dissolve',
                id='deletedialog',
                parent=self.document.body,
                resizable_x=False,
                hide_on_close=True,
                close_callback=hide_ui_delete,
                style='width:200px',
                children=[
                    ui.div(classes='collection', children=[
                        ui.h1(innerText='Delete'),
                        ui.button(innerText='Vertices', title='Delete selected vertices',                     on_mouseclick=delay_exec('''act(('Delete','Vertices'))''')),
                        ui.button(innerText='Edges', title='Delete selected edges and vertices',              on_mouseclick=delay_exec('''act(('Delete','Edges'))''')),
                        ui.button(innerText='Faces', title='Delete selected faces, edges, and vertices',      on_mouseclick=delay_exec('''act(('Delete','Faces'))''')),
                        ui.button(innerText='Only Edges & Faces', title='Delete only selected edges & faces', on_mouseclick=delay_exec('''act(('Delete','Only Edges & Faces'))''')),
                        ui.button(innerText='Only Faces', title='Delete only selected faces',                 on_mouseclick=delay_exec('''act(('Delete','Only Faces'))''')),
                    ]),
                    ui.div(classes='collection', children=[
                        ui.h1(innerText='Dissolve'),
                        ui.button(innerText='Vertices', title='Dissolve selected vertices', on_mouseclick=delay_exec('''act(('Dissolve','Vertices'))''')),
                        ui.button(innerText='Edges', title='Dissolve selected edges',       on_mouseclick=delay_exec('''act(('Dissolve','Edges'))''')),
                        ui.button(innerText='Faces', title='Dissolve selected faces',       on_mouseclick=delay_exec('''act(('Dissolve','Faces'))''')),
                        ui.button(innerText='Loops', title='Dissolve selected edge loops',  on_mouseclick=delay_exec('''act(('Dissolve','Loops'))''')),
                    ])
                ],
                )
            self.ui_delete.is_visible = False
            # self.ui_delete.add_eventListener('on_focusout', hide_ui_delete)
            self.ui_delete.add_eventListener('on_mouseleave', mouseleave_event)
            self.ui_delete.add_eventListener('on_keypress', key)


        setup_main_ui()
        setup_tiny_ui()
        setup_options()
        setup_quit_ui()
        setup_delete_ui()
        setup_counts_ui()

        for rftool in self.rftools:
            if rftool.name == rf_starting_tool:
                self.select_rftool(rftool)

        if options['show main window']:
            self.show_main_ui_window()
        else:
            self.show_tiny_ui_window()

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
