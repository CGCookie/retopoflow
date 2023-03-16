'''
Copyright (C) 2022 CG Cookie
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
from ...addon_common.common.blender import get_preferences, get_path_from_addon_root
from ...addon_common.common.boundvar import BoundVar, BoundBool, BoundFloat, BoundString
from ...addon_common.common.globals import Globals
from ...addon_common.common.inspect import ScopeBuilder
from ...addon_common.common.profiler import profiler
from ...addon_common.common.ui_core import UI_Element
from ...addon_common.common.ui_styling import load_defaultstylings
from ...addon_common.common.utils import delay_exec

from ...config.options import (
    options, themes, visualization,
    retopoflow_urls, retopoflow_product, retopoflow_files,
    build_platform,
    platform_system, platform_node, platform_release, platform_version, platform_machine, platform_processor,
    gpu_info,
)

def get_environment_details():
    blender_version = '%d.%02d.%d' % bpy.app.version
    blender_branch = bpy.app.build_branch.decode('utf-8')
    blender_date = bpy.app.build_commit_date.decode('utf-8')

    env_details = []
    env_details += ['Environment:\n']
    env_details += [f'- RetopoFlow: {retopoflow_product["version"]}']
    if retopoflow_product['git version']:
        env_details += [f'- RF git: {retopoflow_product["git version"]}']
    elif retopoflow_product['cgcookie built']:
        if retopoflow_product['github']:
            env_details += ['- CG Cookie built for GitHub']
        elif retopoflow_product['blender market']:
            env_details += ['- CG Cookie built for Blender Market']
        else:
            env_details += ['- CG Cookie built for ??']
    else:
        env_details += ['- Self built']
    env_details += [f'- Blender: {blender_version} {blender_branch} {blender_date}']
    env_details += [f'- Platform: {platform_system}, {platform_release}, {platform_version}, {platform_machine}, {platform_processor}']
    env_details += [f'- GPU: {gpu_info}']
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





class RetopoFlow_UI_Alert:
    GitHub_checks = 0
    GitHub_limit = 10

    @CookieCutter.Exception_Callback
    def handle_exception(self, e):
        print('RetopoFlow_UI_Alert.handle_exception', e)
        if False:
            for entry in inspect.stack():
                print(f'  {entry}')
        message,h = Globals.debugger.get_exception_info_and_hash()
        message = '\n'.join(f'- {l}' for l in message.splitlines())
        self.alert_user(
            title='Exception caught',
            message=message,
            level='exception',
            msghash=h,
        )
        if hasattr(self, 'rftool'): self.rftool._reset()

    def alert_user(self, message=None, title=None, level=None, msghash=None):
        scope = ScopeBuilder()

        if not hasattr(self, '_msghashes'): self._msghashes = set()
        if not hasattr(self, 'alert_windows'): self.alert_windows = 0
        if msghash and msghash in self._msghashes: return # have already seen this error!!
        self._msghashes.add(msghash)

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
            ss_filename = retopoflow_files['screenshot filename']
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
            bpy.ops.wm.url_open(url=retopoflow_urls['github issues'])
        def search():
            url = f'https://github.com/CGCookie/retopoflow/issues?q=is%3Aissue+{msghash}'
            bpy.ops.wm.url_open(url=url)
        def report():
            nonlocal msg_report
            nonlocal report_details

            path = get_path_from_addon_root('help', 'issue_template_simple.md')
            issue_template = open(path, 'rt').read()
            data = {
                'title': f'{self.rftool.name}: {title}',
                'body': f'{issue_template}\n\n```\n{msg_report}\n```',
            }
            url =  f'{retopoflow_urls["new github issue"]}?{urllib.parse.urlencode(data)}'
            bpy.ops.wm.url_open(url=url)

        if msghash:
            ui_checker = UI_Element.DETAILS(classes='issue-checker', open=True)
            UI_Element.SUMMARY(innerText='Report an issue', parent=ui_checker)
            ui_label = UI_Element.ARTICLE(classes='mdown', parent=ui_checker)
            ui_buttons = UI_Element.DIV(parent=ui_checker, classes='action-buttons')

            ui_label.set_markdown(mdown='Checking reported issues...')

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
                            ui_label.set_markdown(mdown='This issue does not appear to be reported, yet.\n\nPlease consider reporting it so we can fix it.')
                        else:
                            if not solved:
                                print('GitHub: Already reported!')
                                ui_label.set_markdown('This issue appears to have been reported already.\n\nClick Open button to see the current status.')
                            else:
                                print('GitHub: Already solved!')
                                ui_label.set_markdown('This issue appears to have been solved already!\n\nAn updated RetopoFlow should fix this issue.')
                            def go():
                                bpy.ops.wm.url_open(url=issueurl)
                            UI_Element.BUTTON(innerText='Open', on_mouseclick=go, title='Open this issue on the RetopoFlow Issue Tracker', classes='fifth-size', parent=ui_buttons)
                            buttons = 5
                    else:
                        ui_label.set_markdown('Could not run the check.\n\nPlease consider reporting it so we can fix it.')
                except Exception as e:
                    ui_label.set_markdown('Sorry, but we could not reach the RetopoFlow Isssues Tracker.\n\nClick the Similar button to search for similar issues.')
                    pass
                    print('Caught exception while trying to pull issues from GitHub')
                    print(f'URL: "{url}"')
                    print(e)
                    # ignore for now
                    pass
                size = 'fourth-size' if buttons==4 else 'fifth-size'
                UI_Element.BUTTON(innerText='Screenshot', classes=f'action {size}', parent=ui_buttons, on_mouseclick=screenshot,  title='Save a screenshot of Blender')
                UI_Element.BUTTON(innerText='Similar',    classes=f'action {size}', parent=ui_buttons, on_mouseclick=search,      title='Search the RetopoFlow Issue Tracker for similar issues')
                UI_Element.BUTTON(innerText='All Issues', classes=f'action {size}', parent=ui_buttons, on_mouseclick=open_issues, title='Open RetopoFlow Issue Tracker')
                UI_Element.BUTTON(innerText='Report',     classes=f'action {size}', parent=ui_buttons, on_mouseclick=report,      title='Report a new issue on the RetopoFlow Issue Tracker')

            executor = ThreadPoolExecutor()
            executor.submit(check_github)

        msg_report = ''
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
            self.save_emergency()  # make an emergency save!

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

            undo_stack_actions = self.undo_stack_actions() if hasattr(self, 'undo_stack_actions') else []
            msg_report = '\n'.join([
                get_environment_details(),
                get_trace_details(undo_stack_actions, msghash=msghash, message=message_orig),
            ])

            show_quit = True
            darken = True
        else:
            title = level.upper() + (f': {title}' if title else '')
            message = message or 'a note'

        @scope.capture_fn
        def close():
            nonlocal win
            if win.parent:
                self.document.body.delete_child(win)
                self.alert_windows -= 1
            if self.document.sticky_element == win:
                self.document.sticky_element = None
            self.document.clear_last_under()
        @scope.capture_fn
        def mouseleave_event(e):
            nonlocal win
            if not win.is_hovered: close()
        @scope.capture_fn
        def keypress_event(e):
            if e.key == 'ESC': close()
        @scope.capture_fn
        def quit():
            self.done()
        @scope.capture_fn
        def copy_to_clipboard():
            nonlocal msg_report
            try: bpy.context.window_manager.clipboard = msg_report
            except: pass

        if self.alert_windows >= 5:
            return
            #self.exit = True

        scope.capture_var('level')

        win = UI_Element.fromHTMLFile(
            get_path_from_addon_root('retopoflow', 'html', 'alert_dialog.html'),
            frame_depth=2,
            **scope
        )[0]
        self.document.body.append_child(win)
        win.getElementById('alert-title').innerText = title
        win.getElementById('alert-message').set_markdown(mdown=message, frame_depth=2, **scope)
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
