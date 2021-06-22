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
from ...config.keymaps import get_keymaps, reset_all_keymaps, save_custom_keymaps, reset_keymap

class RetopoFlow_KeymapSystem:
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

    def keymap_config_open(self): #, mdown_path, done_on_esc=False, closeable=True, *args, **kwargs):
        newversion = ''
        keymaps = get_keymaps(force_reload=True)
        humanread = self.actions.to_human_readable
        tokmi = self.actions.from_human_readable

        def ok():
            save_custom_keymaps()
            self.done()
        def cancel():
            get_keymaps(force_reload=True)
            self.done()
        def reset_all():
            reset_all_keymaps()
            rebuild()
            self.alert_user(
                message='Keymaps reset, but changes will not be saved until OK is clicked',
                title='Keymaps Config System',
                level='warning',
            )

        def key(e):
            nonlocal keymaps, self
            pass
            # if e.key == 'ESC': close()

        def action_to_label(action):
            for category,actions in keymap_details:
                for a,al in actions:
                    if a == action: return al
            return action
        def action_to_id(a):
            aid = a.replace(' ', '_')
            return aid

        def set_edit_key_span(hk, is_key=True):
            if not is_key:
                clear_edit_key_span()
                return
            span = self.document.body.getElementById('edit-key-span')
            span.innerText  = f'Key: {hk}'
            # span.style = ''
        def capture_edit_key_span():
            span = self.document.body.getElementById('edit-key-span')
            span.innerText = '(capturing... press key to capture)'
            # span.style = 'color: rgba(255, 255, 255, 0.5)'
        def clear_edit_key_span():
            span = self.document.body.getElementById('edit-key-span')
            span.innerText = '(click to start capture)'
            # span.style = 'color: rgba(255, 255, 255, 0.5)'

        edit_data = {}
        def edit_capture():
            ui_button = self.document.body.getElementById('edit-key-span')
            ui_button.can_focus = True
            self.document.focus(ui_button, full=True)
            capture_edit_key_span()
        def edit_lmb():
            clear_edit_key_span()
            edit_data['key'] = 'LMB'
        def edit_mmb():
            clear_edit_key_span()
            edit_data['key'] = 'MMB'
        def edit_rmb():
            clear_edit_key_span()
            edit_data['key'] = 'RMB'
        def edit_wheelup():
            clear_edit_key_span()
            edit_data['key'] = 'WheelUp'
        def edit_wheeldown():
            clear_edit_key_span()
            edit_data['key'] = 'WheelDown'
        def edit_capture_key(event):
            ui_button = self.document.body.getElementById('edit-key-span')
            if self.document.activeElement != ui_button: return
            key = event.key.replace('CTRL+','').replace('SHIFT+','').replace('ALT+','').replace('OSKEY+','')
            set_edit_key_span(humanread([key], visible=True))
            edit_data['key'] = key
            self.document.blur()
        def edit_ok():
            nonlocal edit_data, keymaps, tokmi
            if edit_data['key'] == '':
                self.alert_user(
                    message='Must select a key or mouse interaction first',
                    title='Keymaps Config System',
                    level='warning',
                )
                return
            editor = self.document.body.getElementById('keymapconfig')
            editor.style = "display: none"
            self.document.body.getElementById('keymapsystem-cover').style = "display: none"
            nk = ''
            nk += 'CTRL+'  if editor.getElementById('edit-ctrl').checked  else ''
            nk += 'SHIFT+' if editor.getElementById('edit-shift').checked else ''
            nk += 'ALT+'   if editor.getElementById('edit-alt').checked   else ''
            nk += 'OSKEY+' if editor.getElementById('edit-oskey').checked else ''
            nk += tokmi(edit_data['key'])[0]
            nk += '+CLICK'  if editor.getElementById('edit-click').checked  else ''
            nk += '+DOUBLE' if editor.getElementById('edit-double').checked else ''
            nk += '+DRAG'   if editor.getElementById('edit-drag').checked   else ''
            a = edit_data['action']
            # do not change ordering of keymaps, just update
            idx = keymaps[a].index(edit_data['keymap'])
            keymaps[a][idx] = nk
            rebuild_action(a)
        def edit_cancel():
            self.document.body.getElementById('keymapconfig').style = "display: none"
            self.document.body.getElementById('keymapsystem-cover').style = "display: none"
            if edit_data['keymap'] == '':
                keymaps[edit_data['action']].remove('')
        def edit_delete():
            self.document.body.getElementById('keymapconfig').style = "display: none"
            self.document.body.getElementById('keymapsystem-cover').style = "display: none"
            delete_keymap(edit_data['action'], edit_data['keymap'])
        def edit_start(a, k):
            nonlocal edit_data, keymaps
            aid = action_to_id(a)
            ok = str(k)
            hkctrl,   k = 'CTRL+'   in k, k.replace('CTRL+',   '')
            hkshift,  k = 'SHIFT+'  in k, k.replace('SHIFT+',  '')
            hkalt,    k = 'ALT+'    in k, k.replace('ALT+',    '')
            hkoskey,  k = 'OSKEY+'  in k, k.replace('OSKEY+',  '')
            hkclick,  k = '+CLICK'  in k, k.replace('+CLICK',  '')
            hkdouble, k = '+DOUBLE' in k, k.replace('+DOUBLE', '')
            hkdrag,   k = '+DRAG'   in k, k.replace('+DRAG',   '')
            hk = humanread(k, visible=True)
            is_key = hk not in {'LMB', 'MMB', 'RMB', 'WheelUp', 'WheelDown', ''}
            if not is_key: hm, hk = hk, ''
            else: hm = ''
            edit_data['action'] = a
            edit_data['keymap'] = ok
            edit_data['key'] = k
            self.document.body.getElementById('keymapsystem-cover').style = ""
            editor = self.document.body.getElementById('keymapconfig')
            editor.style = ''
            editor.getElementById('edit-action').innerText = action_to_label(a)
            set_edit_key_span(hk, is_key)
            editor.getElementById('edit-key').checked = is_key
            editor.getElementById('edit-lmb').checked = (hm == 'LMB')
            editor.getElementById('edit-mmb').checked = (hm == 'MMB')
            editor.getElementById('edit-rmb').checked = (hm == 'RMB')
            editor.getElementById('edit-wu').checked  = (hm == 'WheelUp')
            editor.getElementById('edit-wd').checked  = (hm == 'WheelDown')
            editor.getElementById('edit-ctrl').checked   = hkctrl
            editor.getElementById('edit-shift').checked  = hkshift
            editor.getElementById('edit-alt').checked    = hkalt
            editor.getElementById('edit-oskey').checked  = hkoskey
            editor.getElementById('edit-press').checked  = not (hkclick or hkdouble or hkdrag)
            editor.getElementById('edit-click').checked  = hkclick
            editor.getElementById('edit-double').checked = hkdouble
            editor.getElementById('edit-drag').checked   = hkdrag

        def add_keymap(a):
            nonlocal keymaps
            keymaps[a].append('')
            edit_start(a, '')
        def delete_keymap(a, k):
            keymaps[a].remove(k)
            rebuild_action(a)

        def keymap_html(a):
            nonlocal edit_start, delete_keymap, rebuild_action, add_keymap
            aid = action_to_id(a)
            html = ''
            for k in keymaps[a]:
                html += f'''<button id="keymap-{aid}-key" class="key" on_mouseclick="edit_start('{a}', '{k}')">{humanread(k, visible=True)}</button>'''
                html += f'''<button id="keymap-{aid}-del" class="delkey" on_mouseclick="delete_keymap('{a}', '{k}')">✕</button>'''
            html += f'''<button class="half-size" on_mouseclick="add_keymap('{a}')">+ Add New Keymap</button>'''
            html += f'''<button class="half-size" on_mouseclick="reset_keymap('{a}'); rebuild_action('{a}')">Reset Keymap</button>'''
            return html
        def rebuild_action(a):
            # vvv this must be here so fromHTML() can see these fns!
            nonlocal edit_start, delete_keymap, rebuild_action, add_keymap
            # ^^^ this must be here so fromHTML() can see these fns!

            aid = action_to_id(a)
            ui_td = self.document.body.getElementById(f'keymap-{aid}')
            ui_td.clear_children()
            ui_td.append_children(UI_Element.fromHTML(keymap_html(a)))
        def rebuild():
            # vvv this must be here so fromHTML() can see these fns!
            nonlocal edit_start, delete_keymap, rebuild_action, add_keymap
            # ^^^ this must be here so fromHTML() can see these fns!

            ui_keymaps = self.document.body.getElementById('keymaps')
            html = ''
            for category,actions in keymap_details:
                html += f'<details>'
                html += f'<summary>{category}</summary>'
                html += f'<table>'
                for a,al in actions:
                    aid = action_to_id(a)
                    html += f'<tr>'
                    html += f'<td class="action">{al}:</td>'
                    html += f'<td id="keymap-{aid}" class="keymap">{keymap_html(a)}</td>'
                    html += f'</tr>'
                html += f'</table>'
                html += f'</details>'
            ui_keymaps.clear_children()
            ui_keymaps.append_children(UI_Element.fromHTML(html))


        ui_keymaps = UI_Element.fromHTMLFile(abspath('keymaps_dialog.html'))
        self.document.body.append_children(ui_keymaps)
        self.document.body.getElementById('keymapconfig').style = 'display: none'
        self.document.body.getElementById('keymapsystem-cover').style = "display: none"
        rebuild()
        self.document.body.dirty()


keymap_details = [
    ('General', [
        ('confirm', 'Confirm'),
        ('confirm drag', 'Confirm with Drag (sometimes this is needed for certain actions)'),
        ('cancel', 'Cancel'),
    ]),
    ('Insert, Move, Rotate, Scale', [
        ('insert', 'Insert new geometry'),
        # ('insert alt0', 'Insert new geometry (alt0)'),
        # ('insert alt1', 'Insert new geometry (alt1)'),
        ('quick insert', 'Quick insert (Knife, Loops)'),
        ('increase count', 'Increase Count'),
        ('decrease count', 'Decrease Count'),
        ('action', 'Action'),
        ('action alt0', 'Action (alt0)'),
        ('action alt1', 'Action (alt1)'),
        ('grab', 'Grab / move'),
        ('rotate', 'Rotate'),
        ('scale', 'Scale'),
        ('delete', 'Show delete menu'),
        ('delete pie menu', 'Show delete pie menu'),
        ('smooth edge flow', 'Smooth edge flow of selected geometry'),
        ('rotate plane', 'Contours: rotate plane'),
        ('rotate screen', 'Contours: rotate screen'),
        ('slide', 'Loops: slide loop'),
        ('fill', 'Patches: fill'),
        ('knife reset', 'Knife: reset'),
    ]),
    ('Selection, Hiding/Reveal', [
        ('select all', 'Select all'),
        ('select invert', 'Select invert'),
        ('deselect all', 'Deselect all'),
        ('hide selected', 'Hide selected geometry'),
        ('hide unselected', 'Hide unselected geometry'),
        ('reveal hidden', 'Reveal hidden geometry'),
        ('select single', 'Select single item (default depends on Blender selection setting)'),
        ('select single add', 'Add single item to selection (default depends on Blender selection setting)'),
        ('select smart', 'Smart selection (default depends on Blender selection setting)'),
        ('select smart add', 'Smart add to selection (default depends on Blender selection setting)'),
        ('select paint', 'Selection painting (default depends on Blender selection setting)'),
        ('select paint add', 'Paint to add to selection (default depends on Blender selection setting)'),
        ('select path add', 'Select along shortest path (default depends on Blender selection setting)'),
    ]),
    ('Switching Between Tools', [
        ('contours tool', 'Switch to Contours'),
        ('polystrips tool', 'Switch to PolyStrips'),
        ('strokes tool', 'Switch to Strokes'),
        ('patches tool', 'Switch to Patches'),
        ('polypen tool', 'Switch to PolyPen'),
        ('knife tool', 'Switch to Knife'),
        ('knife quick', 'Quick switch to Knife'),
        ('loops tool', 'Switch to Loops'),
        ('loops quick', 'Quick switch to Loops'),
        ('tweak tool', 'Switch to Tweak'),
        ('tweak quick', 'Quick switch to Tweak'),
        ('relax tool', 'Switch to Relax'),
        ('relax quick', 'Quick switch to Relax'),
    ]),
    ('Brush Actions', [
        ('brush', 'Brush'),
        ('brush alt', 'Brush (alt)'),
        ('brush radius', 'Change brush radius'),
        ('brush falloff', 'Change brush falloff'),
        ('brush strength', 'Change brush strength'),
    ]),
    ('Pie Menus', [
        ('pie menu', 'Show pie menu'),
        ('pie menu alt0', 'Show tool/alt pie menu'),
    ]),
    ('Help', [
        ('all help', 'Show all help'),
        ('general help', 'Show general help'),
        ('tool help', 'Show help for selected tool'),
    ]),
]

