'''
Copyright (C) 2018 CG Cookie
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
import bpy
import bgl
import blf
import json
import math
import time
import urllib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from mathutils import Vector

from .rftool import RFTool

from ..common.profiler import profiler
from ..common.maths import Point, Point2D, Vec2D, XForm, clamp, matrix_normal
from ..common.ui import Drawing
from ..common.ui import (
    UI_WindowManager,
    UI_Button, UI_Image,
    UI_Options,
    UI_Checkbox, UI_Checkbox2,
    UI_Label, UI_WrappedLabel, UI_Markdown,
    UI_Spacer, UI_Rule,
    UI_Container, UI_Collapsible, UI_EqualContainer,
    UI_IntValue, UI_UpdateValue,
    GetSet,
    )
from ..common import bmesh_render as bmegl

from ..options import (
    retopoflow_version,retopoflow_version_git,
    retopoflow_profiler,
    retopoflow_issues_url,retopoflow_tip_url,
    options,
    themes,
    build_platform,
    platform_system,platform_node,platform_release,platform_version,platform_machine,platform_processor,
    gpu_vendor,gpu_renderer,gpu_version,gpu_shading
    )

from ..help import help_general, firsttime_message


class RFContext_UI:

    def quit(self): self.exit = True

    def set_symmetry(self, axis, enable):
        if enable: self.rftarget.enable_symmetry(axis)
        else: self.rftarget.disable_symmetry(axis)
        #for rfs in self.rfsources: rfs.dirty()
        self.rftarget.dirty()
    def get_symmetry(self, axis): return self.rftarget.has_symmetry(axis)

    def toggle_help(self, general=None):
        if general is None:
            self.window_manager.clear_focus()
            self.window_help.visible = False
            self.window_manager.clear_active()
            self.help_button.set_label('')
        else:
            if general:
                self.ui_helplabel.set_markdown(help_general)
            else:
                self.ui_helplabel.set_markdown(self.tool.helptext())
            self.window_help.scrollto_top()
            self.window_manager.set_focus(self.window_help)
            #self.window_help.visible = True

    def toggle_help_button(self):
        if self.help_button.get_label() == 'General Help':
            self.toggle_general_help()
        else:
            self.toggle_tool_help()

    def toggle_general_help(self):
        if self.help_button.get_label() == 'Tool Help':
            self.toggle_help()
        else:
            self.help_button.set_label('Tool Help')
            self.toggle_help(True)
    def toggle_tool_help(self):
        if self.help_button.get_label() == 'General Help':
            self.toggle_help()
        else:
            self.help_button.set_label('General Help')
            self.toggle_help(False)

    def alert_assert(self, must_be_true_condition, title=None, message=None, throw=True):
        if must_be_true_condition: return True
        self.alert_user(title=title, message=message, level='assert')
        if throw: assert False
        return False

    def option_user(self, options, callback, title=None):
        def close():
            nonlocal win
            self.window_manager.delete_window(win)
        def event_handler(context, event):
            nonlocal win
            if event.type == 'ESC' and event.value == 'RELEASE':
                close()
            #if event.type == 'HOVER' and event.value == 'LEAVE':
            #    close()
            # print(event)

        def create_option(opt, grpopt, tooltip, container):
            def fn():
                close()
                callback(grpopt)
            return container.add(UI_Button(opt, fn, tooltip=tooltip, align=-1, bordercolor=None, hovercolor=(0.27, 0.50, 0.72, 0.90), margin=0))

        opts = {
            'pos': self.actions.mouse + Vec2D((-20,10)),
            'movable': False,
            'bgcolor': (0.2, 0.2, 0.2, 0.8),
            'event handler': event_handler,
            'padding': 0,
            }
        win = self.window_manager.create_window(title, opts)
        bigcontainer = win.add(UI_Container(margin=0))
        # win.add(UI_Rule())
        prev_container = False
        for opt in options:
            if prev_container: bigcontainer.add(UI_Rule(color=(0,0,0,0.1)))
            if type(opt) is tuple:
                n,opts2 = opt
                container = bigcontainer.add(UI_Container(margin=0))
                container.add(UI_Label(n, align=0, color=(1,1,1,0.5)))
                for opt2 in opts2:
                    create_option(opt2, (n,opt2), '%s: %s' % (n,opt2), container)
                prev_container = True
            else:
                create_option(opt, opt, opt, bigcontainer)
                prev_container = False
        self.window_manager.set_focus(win, darken=False, close_on_leave=True)

    def alert_user(self, title=None, message=None, level=None, msghash=None):
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
            data = {
                'title': '%s: %s' % (self.tool.name(), title),
                'body': '\n'.join([
                    'Please tell us what you were trying to do, what you expected RetopoFlow to do, and what actually happened.',
                    'Provide as much information as you can so that we can reproduce the problem and fix it.',
                    'Screenshots and .blend files are very helpful.',
                    'Also, change the title of this bug report to something descriptive and helpful.',
                    'Thank you!',
                    '',
                    '-------------------------------------',
                    '',
                    '```',msg_report,'```'
                ])
            }
            url = '%s?%s' % (options['github new issue url'], urllib.parse.urlencode(data))
            bpy.ops.wm.url_open(url=url)

        if msghash:
            ui_checker = UI_Container(background=(0,0,0,0.4))
            ui_checker.add(UI_Label('RetopoFlow Issue Tracker', align=0))
            ui_label = ui_checker.add(UI_Markdown('Checking reported issues...', min_size=Vec2D((400,36))))
            ui_buttons = ui_checker.add(UI_EqualContainer(margin=1, vertical=False))

            def check_github():
                try:
                    # attempt to see if this issue already exists!
                    # note: limited to 60 requests/hour!  see
                    #     https://developer.github.com/v3/#rate-limiting
                    #     https://developer.github.com/v3/search/#rate-limit
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
                        ui_label.set_markdown('This issue does not appear to be reported, yet.\n\nPlease consider reporting it so we can fix it.')
                    else:
                        if not solved:
                            ui_label.set_markdown('This issue appears to have been reported already.\n\nClick Open button to see the current status.')
                        else:
                            ui_label.set_markdown('This issue appears to have been solved already!\n\nAn updated RetopoFlow should fix this issue.')
                        def go():
                            bpy.ops.wm.url_open(url=issueurl)
                        ui_buttons.add(UI_Button('Open', go, tooltip='Open this issue on the RetopoFlow Issue Tracker', bgcolor=(1,1,1,0.3), margin=1))
                except Exception as e:
                    ui_label.set_markdown('Sorry, but we could not reach the RetopoFlow Isssues Tracker.\n\nClick the Similar button to search for similar issues.')
                    print('Caught exception while trying to pull issues from GitHub')
                    print('URL: "%s"' % url)
                    print(e)
                    # ignore for now
                    pass
                ui_buttons.add(UI_Button('Screenshot', screenshot, tooltip='Save a screenshot of Blender', bgcolor=(1,1,1,0.3), margin=1))
                ui_buttons.add(UI_Button('Similar', search, tooltip='Search the RetopoFlow Issue Tracker for similar issues', bgcolor=(1,1,1,0.3), margin=1))
                ui_buttons.add(UI_Button('All Issues', open_issues, tooltip='Open RetopoFlow Issue Tracker', bgcolor=(1,1,1,0.3), margin=1))
                ui_buttons.add(UI_Button('Report', report, tooltip='Report a new issue on the RetopoFlow Issue Tracker', bgcolor=(1,1,1,0.3), margin=1))

            executor = ThreadPoolExecutor()
            executor.submit(check_github)

        if level in {'note'}:
            bgcolor = (0.20, 0.20, 0.30, 0.95)
            title = 'Note' + (': %s' % title if title else '')
            message = message or 'a note'
        elif level in {'warning'}:
            bgcolor = (0.35, 0.25, 0.15, 0.95)
            title = 'Warning' + (': %s' % title if title else '')
            darken = True
        elif level in {'error'}:
            bgcolor = (0.30, 0.15, 0.15, 0.95)
            title = 'Error' + (': %s' % title if title else '!')
            darken = True
        elif level in {'assert', 'exception'}:
            if level == 'assert':
                bgcolor = (0.30, 0.15, 0.15, 0.95)
                title = 'Assert Error' + (': %s' % title if title else '!')
                desc = 'An internal assertion has failed.'
            else:
                bgcolor = (0.15, 0.07, 0.07, 0.95)
                title = 'Unhandled Exception Caught' + (': %s' % title if title else '!')
                desc = 'An unhandled exception was thrown.'

            message = '\n'.join([
                desc,
                'This was unexpected.',
                '',
                'If this happens again, please report as bug so we can fix it.',
                ])

            msg_report = ['Environment:\n']
            msg_report += ['- RetopoFlow: %s' % (retopoflow_version,)]
            if retopoflow_version_git:
                msg_report += ['- RF git: %s' % (retopoflow_version_git,)]
            msg_report += ['- Blender: %s %s %s' % (blender_version, blender_branch, blender_date)]
            msg_report += ['- Platform: %s' % (', '.join([platform_system,platform_release,platform_version,platform_machine,platform_processor]), )]
            msg_report += ['- GPU: %s' % (', '.join([gpu_vendor, gpu_renderer, gpu_version, gpu_shading]), )]
            msg_report += ['- Timestamp: %s' % datetime.today().isoformat(' ')]
            if msghash:
                msg_report += ['\n\nError Hash: %s' % (str(msghash),)]
            if message_orig:
                msg_report += ['\n\nTrace:\n\n%s' % (message_orig,)]
            msg_report = '\n'.join(msg_report)

            def clipboard():
                try: bpy.context.window_manager.clipboard = msg_report
                except: pass

            ui_details = UI_Container(background=(0,0,0,0.4))
            ui_details.add(UI_Label('Crash Details', align=0))
            ui_details.add(UI_Markdown(msg_report, min_size=Vec2D((600,36))))
            ui_details.add(UI_Button('Copy Details to Clipboard', clipboard, tooltip='Copy Crash Details to clipboard', bgcolor=(0.5,0.5,0.5,0.4), margin=1))
            ui_details.visible = False

            show_quit = True
            darken = True
        else:
            bgcolor = (0.40, 0.20, 0.30, 0.95)
            title = '%s' % (level.upper()) + (': %s' % title if title else '')
            message = message or 'a note'

        def toggle_details():
            ui_details.visible = not ui_details.visible
            if ui_details.visible:
                ui_show.set_label('Hide Details')
            else:
                ui_show.set_label('Show Details')
        def close():
            nonlocal win
            self.window_manager.delete_window(win)
            # self.alert_windows -= 1
        def quit():
            self.exit = True

        def event_handler(context, event):
            if event.type == 'WINDOW' and event.value == 'CLOSE':
                self.alert_windows -= 1
            if event.type == 'ESC' and event.value == 'RELEASE':
                close()

        if self.alert_windows >= 5:
            return
            #self.exit = True

        opts = {
            'sticky': 5,
            'movable': False,
            'bgcolor': bgcolor,
            'event handler': event_handler,
            }
        win = self.window_manager.create_window(title, opts)
        win.add(UI_Rule())
        win.add(UI_Markdown(message, min_size=Vec2D((400,36))))
        if ui_details: win.add(ui_details)
        if ui_checker: win.add(ui_checker)
        win.add(UI_Rule())
        container = win.add(UI_EqualContainer(margin=1, vertical=False), footer=True)
        if ui_details:
            ui_show = container.add(UI_Button('Show Details', toggle_details, tooltip='Show/hide crash details', bgcolor=(0.5,0.5,0.5,0.4), margin=1))
        container.add(UI_Button('Close', close, tooltip='Close this alert window', bgcolor=(0.5,0.5,0.5,0.4), margin=1))
        # if show_quit:
        #     container.add(UI_Button('Exit', quit, tooltip='Exit RetopoFlow', bgcolor=(0.5,0.5,0.5,0.4), margin=1))

        self.window_manager.set_focus(win, darken=darken)

        self.alert_windows += 1

    def show_lowfps_warning(self):
        if self.fps_low_warning: return             # already showing the warning
        self.fps_low_warning = True

        blender_version = '%d.%02d.%d' % bpy.app.version
        blender_branch = bpy.app.build_branch.decode('utf-8')
        blender_date = bpy.app.build_commit_date.decode('utf-8')

        nsrcs = len(self.rfsources)
        nsrcv = sum(rfmesh.get_vert_count() for rfmesh in self.rfsources)
        nsrce = sum(rfmesh.get_edge_count() for rfmesh in self.rfsources)
        nsrcf = sum(rfmesh.get_face_count() for rfmesh in self.rfsources)

        def clipboard(): bpy.context.window_manager.clipboard = msg_report

        msg_report = ['Details:\n']
        msg_report += ['- RetopoFlow: %s' % (retopoflow_version,)]
        if retopoflow_version_git:
            msg_report += ['- RF git: %s' % (retopoflow_version_git,)]
        msg_report += ['- Blender: %s %s %s' % (blender_version, blender_branch, blender_date)]
        msg_report += ['- Platform: %s' % (', '.join([platform_system,platform_release,platform_version,platform_machine,platform_processor]), )]
        msg_report += ['- GPU: %s' % (', '.join([gpu_vendor, gpu_renderer, gpu_version, gpu_shading]), )]
        msg_report += ['- Target: verts:%d, edges:%d, faces:%d' % (self.rftarget.get_vert_count(), self.rftarget.get_edge_count(), self.rftarget.get_face_count())]
        msg_report += ['- Sources: number:%d, verts:%d, edges:%d, faces:%d' % (nsrcs, nsrcv, nsrce, nsrcf)]
        msg_report += ['- FPS: current:%f, threshold:%s, time:%s' % (self.fps, str(options['low fps threshold']), str(options['low fps time']))]
        msg_report = '\n'.join(msg_report)

        ui_details = UI_Container(background=(0,0,0,0.4))
        ui_details.add(UI_Label('System Details', align=0))
        ui_details.add(UI_Markdown(msg_report, min_size=Vec2D((600,36))))
        ui_details.add(UI_Button('Copy Details to Clipboard', clipboard, tooltip='Copy System Details to clipboard', bgcolor=(0.5,0.5,0.5,0.4), margin=1))

        def submit():
            bpy.ops.wm.url_open(url=options['github low fps url'])
        def disable():
            nonlocal win
            options['low fps warn'] = False
            self.window_manager.delete_window(win)
        def close():
            nonlocal win
            self.window_manager.delete_window(win)
        def event_handler(context, event):
            if event.type == 'WINDOW' and event.value == 'CLOSE':
                self.fps_low_warning = False
                self.fps_low_start = time.time()
            if event.type == 'ESC' and event.value == 'RELEASE':
                close()

        message = '\n'.join([
            'Low FPS (<%s fps for %s+ seconds) has been detected.' % (str(options['low fps threshold']), str(options['low fps time'])),
            '',
            'This is a known problem that we are still working on a solution, but we need your help!',
            '',
            'Please consider submitting your system specifications using the Open button below.',
            ])

        opts = {
            'sticky': 5,
            'movable': False,
            'bgcolor': (0.5,0.2,0.2,0.95),
            'event handler': event_handler,
            }
        win = self.window_manager.create_window('Low FPS Warning', opts)
        win.add(UI_Rule())
        win.add(UI_Markdown(message, min_size=Vec2D((400,36))))
        win.add(ui_details)
        win.add(UI_Rule())
        container = win.add(UI_EqualContainer(margin=1, vertical=False), footer=True)
        container.add(UI_Button('Open Issue', submit, tooltip='Open the Low FPS issue in the RetopoFlow Issue Tracker', bgcolor=(0.5,0.5,0.5,0.4), margin=1))
        container.add(UI_Button('Disable Check', disable, tooltip='Disable the low FPS check (can re-enable in Options > Advanced > Low FPS Options', bgcolor=(0.5,0.5,0.5,0.4), margin=1))
        container.add(UI_Button('Close', close, tooltip='Close this low FPS warning', bgcolor=(0.5,0.5,0.5,0.4), margin=1))

        self.window_manager.set_focus(win, darken=True)


    def _init_ui(self):
        self.drawing = Drawing.get_instance()
        self.window_manager = UI_WindowManager()

        self.drawing.set_region(self.actions.region, self.actions.r3d, bpy.context.window)

        self.alert_windows = 0

        optget = options.getter
        optset = options.setter
        optgetset = options.gettersetter
        replace_opts = lambda v: self.replace_opts()

        def get_selected_tool():
            return self.tool.name()
        def set_selected_tool(value):
            for ids,rft in RFTool.get_tools():
                if rft.bl_label == value: #get_label() == name:
                    self.set_tool(rft.rft_class())
        def update_tool_collapsed():
            b = options['tools_min']
            self.tool_min.visible = b
            self.tool_max.visible = not b
        def get_tool_collapsed():
            update_tool_collapsed()
            return options['tools_min']
        def set_tool_collapsed(b):
            options['tools_min'] = b
            update_tool_collapsed()
        def show_reporting():
            options['welcome'] = True
            self.window_manager.set_focus(self.window_welcome)
            #self.window_welcome.visible = options['welcome']
        def hide_reporting():
            options['welcome'] = False
            self.window_welcome.visible = options['welcome']
            #self.window_manager.clear_active()
            self.window_manager.clear_focus()

        def open_github():
            bpy.ops.wm.url_open(url=retopoflow_issues_url)
        def open_tip():
            bpy.ops.wm.url_open(url=retopoflow_tip_url)

        def reset_options():
            options.reset()
            self.replace_opts()
        def update_profiler_visible():
            nonlocal prof_print, prof_reset, prof_disable, prof_enable
            v = profiler.get_profiler_enabled()
            prof_print.visible = v
            prof_reset.visible = v
            prof_disable.visible = v
            prof_enable.visible = not v
        def enable_profiler():
            options['profiler'] = True
            update_profiler_visible()
        def disable_profiler():
            options['profiler'] = False
            update_profiler_visible()
        def get_lens():  return int(self.actions.space.lens)
        def set_lens(v): self.actions.space.lens = clamp(int(v), 1, 250)
        def get_clip_start():  return self.actions.space.clip_start
        def set_clip_start(v): self.actions.space.clip_start = clamp(v, 1e-6, 1e9)
        def upd_clip_start(u):
            l = 2
            v = math.log(self.actions.space.clip_start) / math.log(l)
            v = clamp(v + u/10, -10, 10)
            v = math.pow(l, v)
            self.actions.space.clip_start = v
        def get_clip_end():    return self.actions.space.clip_end
        def set_clip_end(v):   self.actions.space.clip_end = clamp(v, 1e-6, 1e9)
        def upd_clip_end(u):
            l = 2
            v = math.log(self.actions.space.clip_end) / math.log(l)
            v = clamp(v + u/10, -10, 10)
            v = math.pow(l, v)
            self.actions.space.clip_end = v
        def get_clip_start_print_value(): return '%0.4f' % self.actions.space.clip_start
        def set_clip_start_print_value(v): set_clip_start(v)
        def get_clip_end_print_value():   return '%0.4f' % self.actions.space.clip_end
        def set_clip_end_print_value(v): set_clip_end(v)

        def wrap_pos_option(key):
            def get():
                v = options[key]
                if type(v) is int: return v
                return Point2D(v)
            def set(v):
                if type(v) is int: options[key] = v
                else: options[key] = tuple(v)
            return GetSet(get, set)
        def wrap_bool_option(key, default_val):
            key = key.lower()
            def get(): return options[key]
            def set(v): options[key] = v
            options.set_default(key, default_val)
            return GetSet(get, set)

        self.tool_window = self.window_manager.create_window('Tools', {'fn_pos':wrap_pos_option('tools pos')})
        self.tool_max = UI_Container(margin=0)
        self.tool_min = UI_Container(margin=0, vertical=False)
        self.tool_selection_max = UI_Options(get_selected_tool, set_selected_tool, vertical=True)
        self.tool_selection_min = UI_Options(get_selected_tool, set_selected_tool, vertical=False)
        tools_options = []
        for i,rft_data in enumerate(RFTool.get_tools()):
            ids,rft = rft_data
            self.tool_selection_max.add_option(rft.get_label(), value=rft.bl_label, icon=rft.rft_class().get_ui_icon(), tooltip=rft.get_tooltip())
            self.tool_selection_min.add_option(rft.get_label(), value=rft.bl_label, icon=rft.rft_class().get_ui_icon(), tooltip=rft.get_tooltip(), showlabel=False)
            ui_options = rft.rft_class().get_ui_options()
            if ui_options: tools_options.append((rft.bl_label, ui_options))
        get_tool_collapsed()
        self.tool_max.add(self.tool_selection_max)

        extra = self.tool_max.add(UI_Container())
        #help_icon = UI_Image('help_32.png')
        #help_icon.set_size(16, 16)
        extra.add(UI_Button('General Help', self.toggle_general_help, tooltip='Show help for general RetopoFlow (F1)', margin=0)) # , icon=help_icon
        extra.add(UI_Button('Tool Help', self.toggle_tool_help, tooltip='Show help for selected tool (F2)', margin=0)) # , icon=help_icon
        extra.add(UI_Button('Minimize', lambda: set_tool_collapsed(True), tooltip='Minimizes tool menu', margin=0))
        #extra.add(UI_Checkbox('Collapsed', get_tool_collapsed, set_tool_collapsed))
        extra.add(UI_Button('Exit', self.quit, tooltip='Quit RetopoFlow (TAB/ESC)', margin=0))
        self.tool_min.add(self.tool_selection_min)
        self.tool_min.add(UI_Checkbox(None, get_tool_collapsed, set_tool_collapsed, tooltip='Restores tool menu (un-minimize)'))
        self.tool_window.add(self.tool_max)
        self.tool_window.add(self.tool_min)


        window_info = self.window_manager.create_window('RetopoFlow %s' % retopoflow_version, {'fn_pos':wrap_pos_option('info pos')})
        #window_info.add(UI_Label('RetopoFlow %s' % retopoflow_version, align=0))
        container = window_info.add(UI_Container(margin=0, vertical=False))
        container.add(UI_Button('Welcome!', show_reporting, tooltip='Show "Welcome!" message', margin=0))
        container.add(UI_Button('Report Issue', open_github, tooltip='Report an issue with RetopoFlow (opens default browser)', margin=0))
        window_info.add(UI_Button('Buy us a drink', open_tip, tooltip='Send us a "Thank you"', margin=0))

        window_tool_options = self.window_manager.create_window('Options', {'fn_pos':wrap_pos_option('options pos')})

        dd_general = window_tool_options.add(UI_Collapsible('General', fn_collapsed=wrap_bool_option('tools general collapsed', False)))
        dd_general.add(UI_Button('Maximize Area', self.rfmode.ui_toggle_maximize_area, tooltip='Toggle maximize area (make 3D View fill entire window)'))
        container_snap = dd_general.add(UI_Container(vertical=False))
        container_snap.add(UI_Label('Snap Verts:'))
        container_snap.add(UI_Button('All', self.snap_all_verts, tooltip='Snap all target vertices to nearest source point', margin=0))
        container_snap.add(UI_Button('Selected', self.snap_selected_verts, tooltip='Snap selected target vertices to nearest source point', margin=0))
        dd_general.add(UI_IntValue('Lens', get_lens, set_lens, tooltip='Set viewport lens angle'))
        container_clip = dd_general.add(UI_Container())
        container_clip.add(UI_UpdateValue('Clip Start', get_clip_start, set_clip_start, upd_clip_start, tooltip='Set viewport clip start', fn_get_print_value=get_clip_start_print_value, fn_set_print_value=set_clip_start_print_value, margin=0))
        container_clip.add(UI_UpdateValue('Clip End',   get_clip_end,   set_clip_end,   upd_clip_end,   tooltip='Set viewport clip end',   fn_get_print_value=get_clip_end_print_value, fn_set_print_value=set_clip_end_print_value, margin=0))
        container_alpha = dd_general.add(UI_Container())
        container_alpha.add(UI_Label('Target Alpha:', margin=0))
        container_alpha.add(UI_IntValue('Above', *options.gettersetter('target alpha', getwrap=lambda v:int(v*100), setwrap=lambda v:clamp(float(v)/100,0,1)), margin=0, tooltip='Set transparency of target mesh that is above the source'))
        container_alpha.add(UI_IntValue('Below', *options.gettersetter('target hidden alpha', getwrap=lambda v:int(v*100), setwrap=lambda v:clamp(float(v)/100,0,1)), margin=0, tooltip='Set transparency of target mesh that is below the source'))
        container_alpha.add(UI_IntValue('Backface', *options.gettersetter('target alpha backface', getwrap=lambda v:int(v*100), setwrap=lambda v:clamp(float(v)/100,0,1)), margin=0, tooltip='Set transparency of target mesh that is facing away from camera'))
        dd_general.add(UI_Checkbox('Cull Backfaces', *options.gettersetter('target cull backfaces')))
        container_theme = dd_general.add(UI_Container(vertical=False))
        container_theme.add(UI_Label('Theme:', margin=4))
        opt_theme = container_theme.add(UI_Options(*optgetset('color theme', setcallback=replace_opts), vertical=False, margin=0))
        opt_theme.add_option('Blue', icon=UI_Image('theme_blue.png'), showlabel=False, align=0)
        opt_theme.add_option('Green', icon=UI_Image('theme_green.png'), showlabel=False, align=0)
        opt_theme.add_option('Orange', icon=UI_Image('theme_orange.png'), showlabel=False, align=0)
        opt_theme.set_option(options['color theme'])
        dd_general.add(UI_Checkbox('Auto Collapse Options', *optgetset('tools autocollapse'), tooltip='If enabled, options for selected tool will expand while other tool options collapse'))
        dd_general.add(UI_Checkbox('Show Tooltips', *optgetset('show tooltips', setcallback=self.window_manager.set_show_tooltips), tooltip='If enabled, tooltips (like these!) will show'))
        dd_general.add(UI_Checkbox('Undo Changes Tool', *optgetset('undo change tool'), tooltip='If enabled, undoing will switch to the previously selected tool'))

        # inform window manager about the tooltip checkbox option
        self.window_manager.set_show_tooltips(options['show tooltips'])


        container_symmetry = window_tool_options.add(UI_Collapsible('Symmetry', fn_collapsed=wrap_bool_option('tools symmetry collapsed', True)))
        dd_symmetry = container_symmetry.add(UI_EqualContainer(vertical=False))
        dd_symmetry.add(UI_Checkbox2('x', lambda: self.get_symmetry('x'), lambda v: self.set_symmetry('x',v), tooltip='Toggle X-Symmetry for target', spacing=0))
        dd_symmetry.add(UI_Checkbox2('y', lambda: self.get_symmetry('y'), lambda v: self.set_symmetry('y',v), tooltip='Toggle Y-Symmetry for target', spacing=0))
        dd_symmetry.add(UI_Checkbox2('z', lambda: self.get_symmetry('z'), lambda v: self.set_symmetry('z',v), tooltip='Toggle Z-Symmetry for target', spacing=0))
        opt_symmetry_view = container_symmetry.add(UI_Options(*optgetset('symmetry view', setcallback=replace_opts), vertical=False))
        opt_symmetry_view.add_option('None', tooltip='Disable visualization of symmetry', align=0)
        opt_symmetry_view.add_option('Edge', tooltip='Highlight symmetry on source meshes as edge loop(s)', align=0)
        opt_symmetry_view.add_option('Face', tooltip='Highlight symmetry by coloring source meshes', align=0)
        def get_symmetry_effect():
            return int(options['symmetry effect'] * 100)
        def set_symmetry_effect(v):
            options['symmetry effect'] = clamp(v / 100.0, 0.0, 1.0)
        container_symmetry.add(UI_IntValue('Effect', *optgetset('symmetry effect', getwrap=lambda v:int(v*100), setwrap=lambda v:clamp(v/100, 0.0, 1.0)), tooltip='Controls strength of symmetry visualization'))

        for tool_name,tool_options in tools_options:
            # window_tool_options.add(UI_Spacer(height=5))
            ui_options = window_tool_options.add(UI_Collapsible(tool_name, fn_collapsed=wrap_bool_option('tool %s collapsed' % tool_name, True)))
            for tool_option in tool_options: ui_options.add(tool_option)

        info_adv = window_tool_options.add(UI_Collapsible('Advanced', collapsed=True))

        info_adv.add(UI_IntValue('Debug Level', *optgetset('debug level', setwrap=lambda v:clamp(int(v),0,5))))
        info_adv.add(UI_Checkbox('Debug Actions', *optgetset('debug actions'), tooltip="Print actions (except MOUSEMOVE) to console"))
        info_adv.add(UI_Checkbox('Instrument', *optgetset('instrument'), tooltip="Enable to record all of your actions to a text block. CAUTION: will slow down responsiveness!"))
        info_adv.add(UI_Checkbox('Async Loading', *optgetset('async mesh loading'), tooltip="Load meshes asynchronously"))

        ui_save = info_adv.add(UI_Collapsible('Auto Save', collapsed=True))
        self.window_debug_save = ui_save.add(UI_Label('Time: inf', tooltip="Seconds until auto save is triggered (based on Blender settings)"))
        ui_save.add(UI_Button('Save Now', self.rfmode.backup_save, tooltip="Save backup now"))

        ui_lowfps = info_adv.add(UI_Collapsible('FPS Options', collapsed=True))
        self.window_debug_fps = ui_lowfps.add(UI_Label('FPS: 0.00'))
        ui_lowfps.add(UI_Checkbox('Perform Check', *optgetset('low fps warn'), tooltip='Enable low FPS checking'))
        ui_lowfps.add(UI_IntValue('Threshold', *optgetset('low fps threshold', setwrap=lambda v:min(60,max(1,v))), tooltip='Set low FPS threshold'))
        ui_lowfps.add(UI_IntValue('Timing', *optgetset('low fps time', setwrap=lambda v:min(120,max(1,v))), tooltip='Set low FPS timing'))
        ui_lowfps.add(UI_Button('Show FPS Dialog', self.show_lowfps_warning, tooltip='Show FPS dialog'))

        if retopoflow_profiler:
            info_profiler = info_adv.add(UI_Collapsible('Profiler', collapsed=True, vertical=False))
            prof_print = info_profiler.add(UI_Button('Print', profiler.printout))
            prof_reset = info_profiler.add(UI_Button('Reset', profiler.clear))
            prof_disable = info_profiler.add(UI_Button('Disable', disable_profiler))
            prof_enable = info_profiler.add(UI_Button('Enable', enable_profiler))
            update_profiler_visible()

        info_adv.add(UI_Button('Reset Options', reset_options, tooltip='Reset all of the options to default values'))

        def welcome_event_handler(context, event):
            if event.type == 'ESC' and event.value == 'RELEASE':
                hide_reporting()
        self.window_welcome = self.window_manager.create_window('Welcome!', {'sticky':5, 'visible':options['welcome'], 'movable':False, 'bgcolor':(0.2,0.2,0.2,0.95), 'event handler':welcome_event_handler})
        self.window_welcome.add(UI_Rule())
        self.window_welcome.add(UI_Markdown(firsttime_message))
        self.window_welcome.add(UI_Rule())
        self.window_welcome.add(UI_Button('Close', hide_reporting, bgcolor=(0.5,0.5,0.5,0.4), margin=2), footer=True)
        if options['welcome']: self.window_manager.set_focus(self.window_welcome)

        def help_event_handler(context, event):
            if event.type == 'ESC' and event.value == 'RELEASE':
                self.toggle_help()
        self.window_help = self.window_manager.create_window('Help', {'sticky':5, 'visible':False, 'movable':False, 'bgcolor':(0.2,0.2,0.2,0.95), 'event handler':help_event_handler})
        self.window_help.add(UI_Rule())
        self.ui_helplabel = UI_Markdown('help text here!')
        # self.window_help.add(UI_Scrollable(self.ui_helplabel))
        self.window_help.add(self.ui_helplabel)
        self.window_help.add(UI_Rule())
        container = self.window_help.add(UI_EqualContainer(margin=1, vertical=False), footer=True)
        self.help_button = container.add(UI_Button('', self.toggle_help_button, tooltip='Switch between General Help (F1) and Tool Help (F2)', bgcolor=(0.5,0.5,0.5,0.4), margin=1))
        container.add(UI_Button('Close', self.toggle_help, bgcolor=(0.5,0.5,0.5,0.4), margin=1))

