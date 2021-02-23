'''
Copyright (C) 2021 CG Cookie
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
import re
import bpy

from ..updater import updater

from ...addon_common.common.globals import Globals
from ...addon_common.common.utils import delay_exec, abspath
from ...addon_common.common.ui_styling import load_defaultstylings
from ...addon_common.common.ui_core import UI_Element

from ...config.options import options, retopoflow_version, retopoflow_helpdocs_url, retopoflow_blendermarket_url
from ...config.keymaps import get_keymaps

class RetopoFlow_UpdaterSystem:
    @staticmethod
    def reload_stylings():
        load_defaultstylings()
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'ui.css')
        try:
            Globals.ui_draw.load_stylesheet(path)
        except AssertionError as e:
            # TODO: show proper dialog to user here!!
            print('could not load stylesheet "%s"' % path)
            print(e)
        Globals.ui_document.body.dirty(cause='Reloaded stylings', children=True)
        Globals.ui_document.body.dirty_styling()
        Globals.ui_document.body.dirty_flow()

    def substitute_keymaps(self, mdown, wrap='`', pre='', post='', separator=', ', onlyfirst=None):
        if type(wrap) is str: wrap_pre, wrap_post = wrap, wrap
        else: wrap_pre, wrap_post = wrap
        while True:
            m = re.search(r'{{(?P<action>[^}]+)}}', mdown)
            if not m: break
            action = { s.strip() for s in m.group('action').split(',') }
            sub = f'{pre}{wrap_pre}' + self.actions.to_human_readable(action, join=f'{wrap_post}{separator}{wrap_pre}', onlyfirst=onlyfirst) + f'{wrap_post}{post}'
            mdown = mdown[:m.start()] + sub + mdown[m.end():]
        return mdown

    def substitute_options(self, mdown, wrap='', pre='', post='', separator=', ', onlyfirst=None):
        if type(wrap) is str: wrap_pre, wrap_post = wrap, wrap
        else: wrap_pre, wrap_post = wrap
        while True:
            m = re.search(r'{\[(?P<option>[^\]]+)\]}', mdown)
            if not m: break
            opts = { s.strip() for s in m.group('option').split(',') }
            sub = f'{pre}{wrap_pre}' + separator.join(str(options[opt]) for opt in opts) + f'{wrap_post}{post}'
            mdown = mdown[:m.start()] + sub + mdown[m.end():]
        return mdown

    def substitute_python(self, mdown, wrap='', pre='', post=''):
        if type(wrap) is str: wrap_pre, wrap_post = wrap, wrap
        else: wrap_pre, wrap_post = wrap
        while True:
            m = re.search(r'{`(?P<python>[^`]+)`}', mdown)
            if not m: break
            pyret = eval(m.group('python'), globals(), locals())
            sub = f'{pre}{wrap_pre}{pyret}{wrap_post}{post}'
            mdown = mdown[:m.start()] + sub + mdown[m.end():]
        return mdown

    def updater_open(self): #, mdown_path, done_on_esc=False, closeable=True, *args, **kwargs):
        newversion = ''
        keymaps = get_keymaps()
        def close():
            self.done()
            # e = self.document.body.getElementById('updaterdialog')
            # if not e: return
            # self.document.body.delete_child(e)
        def key(e):
            nonlocal keymaps, self
            if e.key == 'ESC':
                close()
        def blendermarket():
            bpy.ops.wm.url_open(url=retopoflow_blendermarket_url)

        def done_updating(module_name, res=None):
            ui_updater.getElementById('select-version').is_visible = False
            if res is None:
                # success!
                ui_updater.getElementById('update-succeeded').is_visible = True
                ui_updater.getElementById('new-version').innerText = newversion
            else:
                # error
                ui_updater.getElementById('update-failed').is_visible = True
                ui_updater.getElementById('fail-version').innerText = newversion
                ui_updater.getElementById('fail-message').innerText = str(res)
            ui_updater.dirty(children=True)

        def try_again():
            ui_updater.getElementById('update-succeeded').is_visible = False
            ui_updater.getElementById('update-failed').is_visible = False
            ui_updater.getElementById('select-version').is_visible = True
            ui_updater.dirty(children=True)

        def load():
            nonlocal newversion
            uis = self.document.body.getElementsByName('version')
            tag = None
            for ui in uis:
                if ui.checked:
                    tag = ui.value
                    break
            assert tag
            if tag == 'none':
                # do nothing (should never get here, though)
                return
            elif tag == 'custom':
                # commit or branch specified
                tag = ui_updater.getElementById('custom').value
                newversion += tag
                link = f'https://github.com/CGCookie/retopoflow/archive/{tag}.zip'
                updater._update_ready = True
                updater._update_version = None
                updater._update_link = link
            else:
                # release/tag specified
                newversion += tag
                updater._update_ready = True
                updater.set_tag(tag)
            updater.run_update(callback=done_updating)

        ui_updater = UI_Element.fromHTMLFile(abspath('updater_dialog.html'))[0]
        ui_updater.getElementById('current-version').innerText = retopoflow_version
        ui_updater.getElementById('update-succeeded').is_visible = False
        ui_updater.getElementById('update-failed').is_visible = False
        self.document.body.append_child(ui_updater)
        self.document.body.dirty()

        def version_on_input(this):
            if this is None: return
            if this.value == 'none':
                self.document.body.getElementById('load-version').disabled = this.checked

        def set_option(value):
            for ui in ui_updater.getElementsByName('version'):
                if ui.value == value: ui.checked = True

        def add_version_options(update_status):
            nonlocal version_on_input, set_option
            ui_versions = ui_updater.getElementById('version-options')
            ui_versions.append_children(UI_Element.fromHTML(
                f'''<label><input type="radio" name="version" value="none" on_input="version_on_input(this)" checked>Keep current version</label>'''
            ))
            # for tag in updater._tags:
            #     print(tag)
            for tag in updater.tags:
                tag = tag.replace('\n', '').replace('\r', '').replace('\t','')
                ui_versions.append_children(UI_Element.fromHTML(
                    f'''<label><input type="radio" name="version" on_input="version_on_input(this)" value="{tag}">{tag}</label>'''
                ))
            ui_versions.append_children(UI_Element.fromHTML(
                f'''<label class="option-custom"><input type="radio" name="version" on_input="version_on_input(this)" value="custom">Advanced: Commit / Branch</label><input type="text" id="custom" value="" title="Enter commit hash or branch name" on_focus="set_option('custom')">'''
            ))

        updater.include_branches = False
        updater.get_tags()
        add_version_options(None)
        #updater.check_for_update_now(add_version_options)

