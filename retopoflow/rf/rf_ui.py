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

import os
import json
import time
import inspect
from datetime import datetime
import contextlib


import urllib.request
from concurrent.futures import ThreadPoolExecutor

import bpy
import bmesh

from ...addon_common.cookiecutter.cookiecutter import CookieCutter
from ...addon_common.common.boundvar import BoundVar, BoundBool, BoundFloat
from ...addon_common.common.utils import delay_exec
from ...addon_common.common.globals import Globals
from ...addon_common.common.blender import get_preferences
from ...addon_common.common import ui
from ...addon_common.common.ui_styling import load_defaultstylings
from ...addon_common.common.profiler import profiler

from ...config.options import (
    options, themes, visualization,
    retopoflow_issues_url, retopoflow_tip_url,
    retopoflow_version, retopoflow_version_git,
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
    env_details += ['- RetopoFlow: %s' % (retopoflow_version, )]
    if retopoflow_version_git:
        env_details += ['- RF git: %s' % (retopoflow_version_git, )]
    env_details += ['- Blender: %s' % (' '.join([
        blender_version,
        blender_branch,
        blender_date
    ]), )]
    env_details += ['- Platform: %s' % (', '.join([
        platform_system,
        platform_release,
        platform_version,
        platform_machine,
        platform_processor
    ]), )]
    env_details += ['- GPU: %s' % (', '.join([
        gpu_vendor,
        gpu_renderer,
        gpu_version,
        gpu_shading
    ]), )]
    env_details += ['- Timestamp: %s' % datetime.today().isoformat(' ')]

    return '\n'.join(env_details)


def get_trace_details(undo_stack, msghash=None, message=None):
    trace_details = []
    trace_details += ['- Undo: %s' % (', '.join(undo_stack[:10]),)]
    if msghash:
        trace_details += ['']
        trace_details += ['Error Hash: %s' % (str(msghash),)]
    if message:
        trace_details += ['']
        trace_details += ['Trace:\n']
        trace_details += [message]
    return '\n'.join(trace_details)





class RetopoFlow_UI:
    @CookieCutter.Exception_Callback
    def handle_exception(self, e):
        if False:
            print('RF_UI.handle_exception', e)
            for entry in inspect.stack(): print('  %s' % str(entry))
        message,h = Globals.debugger.get_exception_info_and_hash()
        message = '\n'.join('- %s'%l for l in message.splitlines())
        self.alert_user(title='Exception caught', message=message, level='exception', msghash=h)
        self.rftool._reset()

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
            if bpy.data.filepath == '':
                # startup file
                filepath = os.path.abspath(ss_filename)
            else:
                # loaded .blend file
                filepath = os.path.split(os.path.abspath(bpy.data.filepath))[0]
                filepath = os.path.join(filepath, ss_filename)
            bpy.ops.screen.screenshot(filepath=filepath)
            self.alert_user(message='Saved screenshot to "%s"' % filepath)
        def open_issues():
            bpy.ops.wm.url_open(url=retopoflow_issues_url)
        def search():
            url = 'https://github.com/CGCookie/retopoflow/issues?q=is%%3Aissue+%s' % msghash
            bpy.ops.wm.url_open(url=url)
        def report():
            nonlocal msg_report
            nonlocal report_details

            path = os.path.join(os.path.dirname(__file__), '..', '..', 'help', 'issue_template.md')
            issue_template = open(path, 'rt').read()
            data = {
                'title': '%s: %s' % (self.rftool.name, title),
                'body': '%s\n\n```\n%s\n```' % (issue_template, msg_report),
            }
            url = '%s?%s' % (options['github new issue url'], urllib.parse.urlencode(data))
            bpy.ops.wm.url_open(url=url)

        if msghash:
            ui_checker = ui.collapsible(label='Report an issue', classes='issue-checker', collapsed=False)
            ui_label = ui.markdown(mdown='Checking reported issues...', parent=ui_checker)
            ui_buttons = ui.div(parent=ui_checker)

            def check_github():
                nonlocal win, ui_buttons
                try:
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
                        ui.button(label='Open', on_mouseclick=go, title='Open this issue on the RetopoFlow Issue Tracker', parent=ui_buttons)
                except Exception as e:
                    ui.set_markdown(ui_label, 'Sorry, but we could not reach the RetopoFlow Isssues Tracker.\n\nClick the Similar button to search for similar issues.')
                    pass
                    print('Caught exception while trying to pull issues from GitHub')
                    print('URL: "%s"' % url)
                    print(e)
                    # ignore for now
                    pass
                ui.button(label='Screenshot', classes='action', on_mouseclick=screenshot, title='Save a screenshot of Blender', parent=ui_buttons)
                ui.button(label='Similar', classes='action', on_mouseclick=search, title='Search the RetopoFlow Issue Tracker for similar issues', parent=ui_buttons)
                ui.button(label='All Issues', classes='action', on_mouseclick=open_issues, title='Open RetopoFlow Issue Tracker', parent=ui_buttons)
                ui.button(label='Report', classes='action', on_mouseclick=report, title='Report a new issue on the RetopoFlow Issue Tracker', parent=ui_buttons)

            executor = ThreadPoolExecutor()
            executor.submit(check_github)

        if level in {'note'}:
            title = 'Note' + (': %s' % title if title else '')
            message = message or 'a note'
        elif level in {'warning'}:
            title = 'Warning' + (': %s' % title if title else '')
            darken = True
        elif level in {'error'}:
            title = 'Error' + (': %s' % title if title else '!')
            show_quit = True
            darken = True
        elif level in {'assert', 'exception'}:
            if level == 'assert':
                title = 'Assert Error' + (': %s' % title if title else '!')
                desc = 'An internal assertion has failed.'
            else:
                title = 'Unhandled Exception Caught' + (': %s' % title if title else '!')
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

            ui_details = ui.collapsible(id='crashdetails', label='Crash details')
            ui_details.builder([
                ui.label(innerText='Crash Details:', style="border:0px; padding:0px; margin:0px"),  # align=0
                ui.pre(innerText=msg_report),    # fontid=fontid
                ui.button(label='Copy details to clipboard', on_mouseclick=clipboard, title='Copy crash details to clipboard'), # bgcolor=(0.5,0.5,0.5,0.4),margin=1
            ])

            show_quit = True
            darken = True
        else:
            title = '%s' % (level.upper()) + (': %s' % title if title else '')
            message = message or 'a note'

        def close():
            nonlocal win
            self.document.body.delete_child(win)
            self.alert_windows -= 1
        def quit():
            self.done()

        if self.alert_windows >= 5:
            return
            #self.exit = True

        win = ui.framed_dialog(label=title, classes='alertdialog %s'%str(level))
        ui.markdown(mdown=message, parent=win)
        if ui_details or ui_checker:
            container = ui.div(parent=win)
            if ui_details:
                container.append_child(ui_details)
            if ui_checker:
                container.append_child(ui_checker)
        ui_bottombuttons = ui.div(id='alertdialog-buttons', parent=win)
        ui_close = ui.button(label='Close', on_mouseclick=close, title='Close this alert window', parent=ui_bottombuttons)
        if show_quit:
            ui.button(label='Exit', on_mouseclick=quit, title='Exit RetopoFlow', parent=ui_bottombuttons)
        else:
            ui_close.style = 'width:100%'

        #self.window_manager.set_focus(win, darken=darken)
        self.document.body.append_child(win)
        self.alert_windows += 1
        if level in {'note', None}:
            win.style = 'width:600px;'
            # win.style = 'left:auto; top:auto;'
            self.document.force_clean(self.actions.context)
            self.document.center_on_mouse(win)

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
            self.ui_options.dirty('update', parent=True, children=True)

    def blender_ui_set(self, scale_to_unit_box=True, add_rotate=True, hide_target=True):
        # print('RetopoFlow: blender_ui_set', 'scale_to_unit_box='+str(scale_to_unit_box), 'add_rotate='+str(add_rotate))
        if scale_to_unit_box: self.scale_to_unit_box()
        self.viewaa_simplify()

        self.manipulator_hide() # <---------------------------------------------------------------
        self._space.show_gizmo = True

        if get_preferences().system.use_region_overlap:
            # DO NOT HIDE HEADER WHEN REGION OVERLAP IS OFF!!!
            # bug in 282a (at least)
            self.panels_hide()
        self.overlays_hide()
        self.region_darken()
        self.header_text_set('RetopoFlow')
        bpy.ops.object.mode_set(mode='OBJECT')
        if add_rotate: self.setup_rotate_about_active()
        if hide_target: self.hide_target()

    def blender_ui_reset(self):
        # print('RetopoFlow: blender_ui_reset')
        self.end_rotate_about_active()
        self.teardown_target()
        self.unscale_from_unit_box()
        self.restore_window_state()
        self._cc_blenderui_end()
        bpy.ops.object.mode_set(mode='EDIT')

    @contextlib.contextmanager
    def blender_ui_pause(self):
        self.blender_ui_reset()
        yield None
        self.blender_ui_set()

    def update_ui_geometry(self):
        self.ui_geometry.is_visible = False  # toggle visibility as workaround hack for relaying out table :(
        self.ui_geometry_verts.innerText = str(self.rftarget.get_vert_count())
        self.ui_geometry_edges.innerText = str(self.rftarget.get_edge_count())
        self.ui_geometry_faces.innerText = str(self.rftarget.get_face_count())
        self.ui_geometry.is_visible = True
        # TODO: FIX WORKAROUND HACK!

    def setup_ui_blender(self):
        self.blender_ui_set(scale_to_unit_box=False, add_rotate=False, hide_target=False)

    def setup_ui(self):
        # NOTE: lambda is needed on next line so that RF keymaps are bound!
        humanread = lambda x: self.actions.to_human_readable(x)

        self.hide_target()

        # load ui.css
        self.reload_stylings()

        self._var_auto_hide_options = BoundBool('''options['tools autohide']''', on_change=self.update_ui)

        self.alert_windows = 0

        def setup_tiny_ui():
            return
            self.ui_tiny = ui.framed_dialog(label='RetopoFlow %s' % retopoflow_version, id='tinydialog', closeable=False, parent=self.document.body)
            ui_tools = ui.div(id='ttools', parent=self.ui_tiny)
            def add_tool(rftool):
                nonlocal ui_tools
                # must be a fn so that local vars are unique and correctly captured
                lbl, img = rftool.name, rftool.icon
                if hasattr(self, 'rf_starting_tool'):
                    checked = rftool.name == self.rf_starting_tool
                else:
                    checked = not hasattr(add_tool, 'notfirst')
                if checked: self.select_rftool(rftool)
                radio = ui.input_radio(
                    id='ttool-%s'%lbl.lower(),
                    value=lbl.lower(),
                    title=rftool.description,
                    name="tool",
                    classes="tool",
                    checked=checked,
                    parent=ui_tools,
                )
                radio.add_eventListener('on_input', delay_exec('''if radio.checked: self.select_rftool(rftool)'''))
                ui.img(src=img, parent=radio, title=rftool.description)
                #ui.label(innerText=lbl, parent=radio, title=rftool.description)
                add_tool.notfirst = True
            for rftool in self.rftools: add_tool(rftool)

        def setup_counts_ui():
            self.ui_geometry = ui.framed_dialog(label="Geometry", id="geometrydialog", resizable=False, closeable=True, hide_on_close=True, close_callback=delay_exec('self.ui_show_geometry.disabled=False'), parent=self.document.body, children=[
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
            ])
            self.ui_geometry_verts = self.ui_geometry.getElementById('geometry-verts')
            self.ui_geometry_edges = self.ui_geometry.getElementById('geometry-edges')
            self.ui_geometry_faces = self.ui_geometry.getElementById('geometry-faces')
            self.update_ui_geometry()

        def setup_main_ui():
            self.ui_main = ui.framed_dialog(label='RetopoFlow %s' % retopoflow_version, id="maindialog", closeable=False, parent=self.document.body)

            # tools
            ui_tools = ui.div(id="tools", parent=self.ui_main)
            def add_tool(rftool):
                nonlocal ui_tools
                # must be a fn so that local vars are unique and correctly captured
                lbl, img = rftool.name, rftool.icon
                if hasattr(self, 'rf_starting_tool'):
                    checked = rftool.name == self.rf_starting_tool
                else:
                    checked = not hasattr(add_tool, 'notfirst')
                if checked: self.select_rftool(rftool)
                radio = ui.input_radio(
                    id='tool-%s'%lbl.lower(),
                    value=lbl.lower(),
                    title='%s (%s)' % (rftool.description, humanread(rftool.shortcut)),
                    name="tool",
                    classes="tool",
                    checked=checked,
                    parent=ui_tools
                )
                radio.add_eventListener('on_input', delay_exec('''if radio.checked: self.select_rftool(rftool)'''))
                ui.img(src=img, parent=radio, title=rftool.description)
                ui.label(innerText=lbl, parent=radio, title=rftool.description)
                add_tool.notfirst = True
            for rftool in self.rftools: add_tool(rftool)

            ui.collapsible(label='Help', id='help-buttons', parent=self.ui_main, children=[
                ui.button(
                    label='Welcome!',
                    title='Show the "Welcome!" message from the RetopoFlow team',
                    on_mouseclick=delay_exec("self.helpsystem_open('welcome.md')")
                ),
                ui.button(
                    label='Table of Contents',
                    title='Show help table of contents (%s)' % humanread('all help'),
                    on_mouseclick=delay_exec("self.helpsystem_open('table_of_contents.md')")
                ),
                ui.button(
                    label='General',
                    title='Show general help (%s)' % humanread('general help'),
                    on_mouseclick=delay_exec("self.helpsystem_open('general.md')")
                ),
                ui.button(
                    label='Tool',
                    title='Show help for currently selected tool (%s)' % humanread('tool help'),
                    on_mouseclick=delay_exec("self.helpsystem_open(self.rftool.help)")
                ),
            ])
            ui_show = ui.collapsible(label='Windows', parent=self.ui_main)
            self.ui_show_options = ui.button(label='Show Options', title='Show options window', disabled=True, parent=ui_show, on_mouseclick=delay_exec('self.ui_options.is_visible = True; self.ui_show_options.disabled = True'))
            self.ui_show_geometry = ui.button(label='Show Geometry', title='Show geometry window', disabled=True, parent=ui_show, on_mouseclick=delay_exec('self.ui_geometry.is_visible = True; self.ui_show_geometry.disabled = True'))
            ui.button(label='Report Issue', title='Report an issue with RetopoFlow', parent=self.ui_main, on_mouseclick=delay_exec("bpy.ops.wm.url_open(url=retopoflow_issues_url)"))
            ui.button(label='Exit', title='Quit RetopoFlow (%s)' % humanread('done'), parent=self.ui_main, on_mouseclick=self.done)
            if False:
                ui.button(label='Reload Styles', parent=self.ui_main, on_mouseclick=self.reload_stylings)
            if False:
                def printout_profiler():
                    profiler.printout()
                    print("Children: %d" % self.document.body.count_children())
                ui.button(label='Profiler', parent=self.ui_main, on_mouseclick=printout_profiler)
                ui.button(label='Profiler Clear', parent=self.ui_main, on_mouseclick=profiler.reset)


        def setup_options():
            self.ui_options = ui.framed_dialog(label='Options', id='optionsdialog', right=0, closeable=True, hide_on_close=True, close_callback=delay_exec('self.ui_show_options.disabled = False'), parent=self.document.body)

            options['remove doubles dist']

            def theme_change(e):
                if not e.target.checked: return
                options['color theme'] = e.target.value
            def reset_options():
                options.reset()
                self.update_ui()
                self.document.body.dirty(children=True)

            def update_esctoquit():
                if options['escape to quit']:
                    self.actions.keymap2['done'].add('ESC')
                else:
                    self.actions.keymap2['done'].discard('ESC')

            self.ui_options.append_child(
                ui.collapsible(label='General', title='General options', id='generaloptions', children=[
                    ui.labeled_input_text(label='UI Scale', title='Custom UI scaling setting', value=BoundFloat('''options['ui scale']''', min_value=0.25, max_value=4)),
                    ui.input_checkbox(
                        label='Auto Hide Tool Options',
                        title='If enabled, options for selected tool will show while other tool options hide.',
                        checked=self._var_auto_hide_options,
                        style='display:block;width:100%',
                    ),
                    # ui.button(label='Maximize Area'),
                    ui.collapsible(label='Target Cleaning', id='target-cleaning', children=[
                        ui.collection(label='Snap Verts', id='snap-verts', children=[
                            ui.button(label="All", title='Snap all target vertices to nearest point on source(s).', on_mouseclick=self.snap_all_verts),
                            ui.button(label="Selected", title='Snap selected target vertices to nearest point on source(s).', on_mouseclick=self.snap_selected_verts),
                        ]),
                        ui.collection(label='Merge by Distance', id='merge-by-distance', children=[
                            ui.labeled_input_text(label='Distance', title='Distance within which vertices will be merged.', value=BoundFloat('''options['remove doubles dist']''', min_value=0)),
                            ui.button(label='All', title='Merge all vertices within given distance.', on_mouseclick=self.remove_all_doubles),
                            ui.button(label='Selected', title='Merge selected vertices within given distance.', on_mouseclick=self.remove_selected_doubles)
                        ]),
                    ]),
                    ui.collapsible(label='View Options', id='view-options', children=[
                        ui.collection(label='Clipping', id='clipping', children=[
                            ui.labeled_input_text(label='Start', title='Near clipping distance', value=BoundFloat('''self.actions.space.clip_start''', min_value=0)),
                            ui.labeled_input_text(label='End', title='Far clipping distance', value=BoundFloat('''self.actions.space.clip_end''', min_value=0)),
                        ]),
                        ui.collection(label='Theme', children=[
                            ui.input_radio(
                                id='theme-color-green',
                                title='Draw the target mesh using a green theme.',
                                value='Green',
                                checked=(options['color theme']=='Green'),
                                name='theme-color',
                                classes='symmetry-viz',
                                children=[ui.label(innerText='Green', title='Draw the target mesh using a green theme.')],
                                on_input=theme_change,
                            ),
                            ui.input_radio(
                                id='theme-color-blue',
                                title='Draw the target mesh using a blue theme.',
                                value='Blue',
                                checked=(options['color theme']=='Blue'),
                                name='theme-color',
                                classes='symmetry-viz',
                                children=[ui.label(innerText='Blue', title='Draw the target mesh using a blue theme.')],
                                on_input=theme_change,
                            ),
                            ui.input_radio(
                                id='theme-color-orange',
                                title='Draw the target mesh using a orange theme.',
                                value='Orange',
                                checked=(options['color theme']=='Orange'),
                                name='theme-color',
                                classes='symmetry-viz',
                                children=[ui.label(innerText='Orange', title='Draw the target mesh using a orange theme.')],
                                on_input=theme_change,
                            ),
                        ]),
                        ui.collapsible(label='Target Drawing', children=[
                            ui.labeled_input_text(label='Above', title='Set transparency of target mesh that is above the source', value=BoundFloat('''options['target alpha']''', min_value=0.0, max_value=1.0)),
                            ui.labeled_input_text(label='Below', title='Set transparency of target mesh that is below the source', value=BoundFloat('''options['target hidden alpha']''', min_value=0.0, max_value=1.0)),
                            ui.labeled_input_text(label='Vertex Size', title='Draw radius of vertices.', value=BoundFloat('''options['target vert size']''', min_value=0.1)),
                            ui.labeled_input_text(label='Edge Size', title='Draw width of edges.', value=BoundFloat('''options['target edge size']''', min_value=0.1)),
                        ]),
                    ]),
                    ui.collapsible(label='Visibility Test', title='These options are used to tune the parameters for visibility testing', children=[
                        ui.labeled_input_text(label='BBox Factor', title='Factor on minimum bounding box dimension', value=BoundFloat('''options['visible bbox factor']''', min_value=0.0, max_value=1.0, on_change=self.get_vis_accel)),
                        ui.labeled_input_text(label='Distance Offset', title='Offset added to max distance', value=BoundFloat('''options['visible dist offset']''', min_value=0.0, max_value=1.0, on_change=self.get_vis_accel)),
                        ui.collection(label='Presets', id='vistest-presets', children=[
                            ui.button(label='Tiny', title='Preset options for working on tiny objects', on_mouseclick=self.visibility_preset_tiny),
                            ui.button(label='Normal', title='Preset options for working on normal-sized objects', on_mouseclick=self.visibility_preset_normal),
                        ]),
                    ]),
                    ui.input_checkbox(label='Escape to Quit', title='Check to allow Esc key to quit RetopoFlow', checked=BoundVar('''options['escape to quit']''', on_change=update_esctoquit)),
                    ui.collapsible(label='Advanced', title='Advanced options and commands', children=[
                        ui.div(innerText='FPS: 0', id='fpsdiv'),
                        ui.collapsible(label='Tooltip Settings', children=[
                            ui.input_checkbox(label='Show', title='Check to show tooltips', checked=BoundVar('''options['show tooltips']''')),
                            ui.labeled_input_text(label='Delay', title='Set delay before tooltips show', value=BoundFloat('''options['tooltip delay']''', min_value=0.0)),
                        ]),
                        ui.collapsible(label='Keyboard Settings', children=[
                            ui.labeled_input_text(label='Repeat Delay', title='Set delay time before keyboard start repeating', value=BoundFloat('''options['keyboard repeat delay']''', min_value=0.02)),
                            ui.labeled_input_text(label='Repeat Pause', title='Set pause time between keyboard repeats', value=BoundFloat('''options['keyboard repeat pause']''', min_value=0.02)),
                            ui.button(label='Reset Keyboard Settings', on_mouseclick=delay_exec('''options.reset(keys=['keyboard repeat delay','keyboard repeat pause'], version=False)''')),
                        ]),
                        ui.button(label='Reset All Settings', title='Reset RetopoFlow back to factory settings', on_mouseclick=reset_options),
                    ])
                ]),
            )
            self.ui_fpsdiv = self.document.body.getElementById('fpsdiv')

            def symmetry_viz_change(e):
                if not e.target.checked: return
                options['symmetry view'] = e.target.value
            symmetryoptions = ui.collapsible(label='Symmetry', title='Symmetry (mirroring) options', id='symmetryoptions', parent=self.ui_options, children=[
                ui.input_checkbox(label='x', title='Check to mirror along x-axis', classes='symmetry-enable', checked=BoundVar('''self.rftarget.mirror_mod.x''')),
                ui.input_checkbox(label='y', title='Check to mirror along y-axis', classes='symmetry-enable', checked=BoundVar('''self.rftarget.mirror_mod.y''')),
                ui.input_checkbox(label='z', title='Check to mirror along z-axis', classes='symmetry-enable', checked=BoundVar('''self.rftarget.mirror_mod.z''')),
                ui.labeled_input_text(label='Threshold', title='Distance within which mirrored vertices will be merged.', value=BoundFloat('''self.rftarget.mirror_mod.symmetry_threshold''', min_value=0)),
                ui.labeled_input_text(label='Effect', title='Effect of symmetry visualization.', value=BoundFloat('''options['symmetry effect']''', min_value=0.0, max_value=1.0)),
                ui.input_radio(id='symmetry-viz-none', title='If checked, no symmetry will be visualized, even if symmetry is enabled (above).', value='None', checked=(options['symmetry view']=='None'), name='symmetry-viz', classes='symmetry-viz', children=[ui.label(innerText='None', title='If checked, no symmetry will be visualized, even if symmetry is enabled (above).')], on_input=symmetry_viz_change),
                ui.input_radio(id='symmetry-viz-edge', title='If checked, symmetry will be visualized as a line, the intersection of the source meshes and the mirroring plane(s).', value='Edge', checked=(options['symmetry view']=='Edge'), name='symmetry-viz', classes='symmetry-viz', children=[ui.label(innerText='Edge', title='If checked, symmetry will be visualized as a line, the intersection of the source meshes and the mirroring plane(s).')], on_input=symmetry_viz_change),
                ui.input_radio(id='symmetry-viz-face', title='If checked, symmetry will be visualized by coloring the mirrored side of source mesh(es).', value='Face', checked=(options['symmetry view']=='Face'), name='symmetry-viz', classes='symmetry-viz', children=[ui.label(innerText='Face', title='If checked, symmetry will be visualized by coloring the mirrored side of source mesh(es).')], on_input=symmetry_viz_change),
            ])
            def symmetry_changed():
                s = []
                if self.rftarget.mirror_mod.x: s += ['X']
                if self.rftarget.mirror_mod.y: s += ['Y']
                if self.rftarget.mirror_mod.z: s += ['Z']
                if not s: s = ['(none)']
                symmetryoptions.innerText = 'Symmetry: %s' % ','.join(s)
            symmetry_changed()
            for opt in self.ui_options.getElementsByClassName('symmetry-enable'):
                opt.add_eventListener('on_input', symmetry_changed)

            self.rftools_ui = {}
            for rftool in self.rftools:
                ui_elems = rftool._callback('ui setup')
                self.rftools_ui[rftool] = ui_elems
                for ui_elem in ui_elems:
                    self.ui_options.append_child(ui_elem)


        def setup_delete_ui():
            self.ui_delete = ui.framed_dialog(
                label='Delete/Dissolve',
                id='deletedialog',
                parent=self.document.body,
                resizable_x=False,
                hide_on_close=True,
                )
            self.ui_delete.width = 200
            self.ui_delete.is_visible = False
            def hide_ui_delete():
                self.ui_delete.is_visible = False
            def key(e):
                if e.key == 'ESC': hide_ui_delete()
            self.ui_delete.add_eventListener('on_focusout', hide_ui_delete)
            self.ui_delete.add_eventListener('on_keypress', key)

            def act(opt):
                self.delete_dissolve_option(opt)
                self.ui_delete.is_visible = False

            ui_delete = ui.collection('Delete', parent=self.ui_delete)
            ui.button(label='Vertices', title='Delete selected vertices',                     on_mouseclick=delay_exec('''act(('Delete','Vertices'))'''), parent=ui_delete)
            ui.button(label='Edges', title='Delete selected edges and vertices',              on_mouseclick=delay_exec('''act(('Delete','Edges'))'''), parent=ui_delete)
            ui.button(label='Faces', title='Delete selected faces, edges, and vertices',      on_mouseclick=delay_exec('''act(('Delete','Faces'))'''), parent=ui_delete)
            ui.button(label='Only Edges & Faces', title='Delete only selected edges & faces', on_mouseclick=delay_exec('''act(('Delete','Only Edges & Faces'))'''), parent=ui_delete)
            ui.button(label='Only Faces', title='Delete only selected faces',                 on_mouseclick=delay_exec('''act(('Delete','Only Faces'))'''), parent=ui_delete)

            ui_dissolve = ui.collection('Dissolve', parent=self.ui_delete)
            ui.button(label='Vertices', title='Dissolve selected vertices', on_mouseclick=delay_exec('''act(('Dissolve','Vertices'))'''), parent=ui_dissolve)
            ui.button(label='Edges', title='Dissolve selected edges',       on_mouseclick=delay_exec('''act(('Dissolve','Edges'))'''), parent=ui_dissolve)
            ui.button(label='Faces', title='Dissolve selected faces',       on_mouseclick=delay_exec('''act(('Dissolve','Faces'))'''), parent=ui_dissolve)
            ui.button(label='Loops', title='Dissolve selected edge loops',  on_mouseclick=delay_exec('''act(('Dissolve','Loops'))'''), parent=ui_dissolve)

        setup_main_ui()
        setup_tiny_ui()
        setup_options()
        setup_delete_ui()
        setup_counts_ui()

        self.ui_tools = self.document.body.getElementsByName('tool')
        self.update_ui()
        if options['welcome']:
            self.helpsystem_open('welcome.md')
            # options['welcome'] = False

