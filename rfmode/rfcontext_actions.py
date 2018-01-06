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

import bpy
from copy import deepcopy

from ..common.maths import Point2D
from .. import key_maps
from ..lib.eventdetails import EventDetails


def kmi_details(kmi):
    kmi_ctrl  = 'CTRL+'  if kmi.ctrl  else ''
    kmi_shift = 'SHIFT+' if kmi.shift else ''
    kmi_alt   = 'ALT+'   if kmi.alt   else ''
    kmi_os    = 'OSKEY+' if kmi.oskey else ''

    kmi_ftype = kmi_ctrl + kmi_shift + kmi_alt + kmi_os
    if kmi.type == 'WHEELINMOUSE':
        kmi_ftype += 'WHEELUPMOUSE'
    elif kmi.type == 'WHEELOUTMOUSE':
        kmi_ftype += 'WHEELDOWNMOUSE'
    else:
        kmi_ftype += kmi.type

    return kmi_ftype

def strip_mods(action):
    if action is None: return None
    return action.replace('CTRL+','').replace('SHIFT+','').replace('ALT+','').replace('OSKEY+','')

class Actions:
    default_keymap = {
        # common
        'navigate': {'TRACKPADPAN','TRACKPADZOOM'},     # to be filled in by self.load_keymap()
        'window actions': set(),                        # to be filled in by self.load_keymap()
        
        'action': {'LEFTMOUSE'},
        'action alt0': {'SHIFT+LEFTMOUSE'},
        'action alt1': {'CTRL+SHIFT+LEFTMOUSE'},
        
        'select': {'RIGHTMOUSE'},   # TODO: update based on bpy.context.user_preferences.inputs.select_mouse
        'select add': {'SHIFT+RIGHTMOUSE'},
        'select smart': {'CTRL+SHIFT+RIGHTMOUSE'},
        'select all': {'A'},
        
        'tool help': {'F1'},

        'autosave': {'TIMER_AUTOSAVE'},
        
        'cancel': {'ESC', 'RIGHTMOUSE'},
        'cancel no select': {'ESC'},
        'confirm': {'RET', 'NUMPAD_ENTER', 'LEFTMOUSE'},
        'done': {'ESC', 'RET', 'NUMPAD_ENTER'},
        
        'undo': {'CTRL+Z'},
        'redo': {'CTRL+SHIFT+Z'},
        
        'edit mode': {'TAB'},

        'insert': {'CTRL+LEFTMOUSE'},
        'insert alt0': {'SHIFT+LEFTMOUSE'},
        'insert alt1': {'CTRL+SHIFT+LEFTMOUSE'},
        
        'grab': {'G'},
        'delete': {'X','DELETE'},
        'dissolve': {'SHIFT+X','SHIFT+DELETE'},
        'dissolve vert': {'SHIFT+X','SHIFT+DELETE'},
        'dissolve edge': {'CTRL+X','CTRL+DELETE'},
        'dissolve face': {'CTRL+SHIFT+X', 'CTRL+SHIFT+DELETE'},

        # contours
        'increase count': {'EQUAL','SHIFT+EQUAL','SHIFT+UP_ARROW', 'SHIFT+WHEELUPMOUSE'},
        'decrease count': {'MINUS','SHIFT+DOWN_ARROW','SHIFT+WHEELDOWNMOUSE'},
        'shift': {'S'},             # rotation of loops
        'rotate': {'SHIFT+S'},

        # relax
        'relax selected': {'SHIFT+S'},
        
        # loops
        'slide': {'S'},
        
        # patches
        'fill': {'F'},

        # widget
        'brush radius': {'F'},
        'brush size': {'F'},
        'brush falloff': {'CTRL+F'},
        'brush strength': {'SHIFT+F'},

        # shortcuts to tools
        'contours tool': {'Q'},
        'polystrips tool': {'W'},
        'polypen tool': {'E'},
        'relax tool': {'R'},
        'move tool': {'T'},
        'loops tool': {'Y'},
        'patches tool': {'U'},
        }

    navigation_events = {
        'Rotate View': 'view3d.rotate',
        'Move View': 'view3d.move',
        'Zoom View': 'view3d.zoom',
        'Dolly View': 'view3d.dolly',
        'View Pan': 'view3d.view_pan',
        'View Orbit': 'view3d.view_orbit',
        'View Persp/Ortho': 'view3d.view_persportho',
        'View Numpad': 'view3d.viewnumpad',
        'NDOF Orbit View': 'view3d.ndof_orbit',
        'NDOF Pan View': 'view3d.ndof_pan',
        'NDOF Move View': 'view3d.ndof_all',
        'View Selected': 'view3d.view_selected',
        'Center View to Cursor': 'view3d.view_center_cursor'
        }

    window_actions = {
        'wm.window_fullscreen_toggle',
        'screen.screen_full_area',
    }

    def load_keymap(self, keyconfig_name):
        if keyconfig_name not in bpy.context.window_manager.keyconfigs:
            dprint('No keyconfig named "%s"' % keyconfig_name)
            return
        keyconfig = bpy.context.window_manager.keyconfigs[keyconfig_name]
        for kmi in keyconfig.keymaps['3D View'].keymap_items:
            if kmi.name not in self.navigation_events: continue
            if kmi.active: self.keymap['navigate'].add(kmi_details(kmi))
            else: self.keymap['navigate'].discard(kmi_details(kmi))
        for map_name in ['Screen', 'Window']:
            for kmi in keyconfig.keymaps[map_name].keymap_items:
                if kmi.idname not in self.window_actions: continue
                if kmi.active: self.keymap['window actions'].add(kmi_details(kmi))
                else: self.keymap['window actions'].discard(kmi_details(kmi))
            

    def __init__(self, context):
        self.keymap = deepcopy(self.default_keymap)
        self.load_keymap('Blender')
        self.load_keymap('Blender User')

        self.context = context
        self.region = context.region
        self.size = (context.region.width,context.region.height)
        self.r3d = context.space_data.region_3d

        self.actions_using = set()
        self.actions_pressed = set()
        self.now_pressed = {}
        self.just_pressed = None

        self.mouse = None
        self.mouse_prev = None
        self.mousedown = None
        self.mousedown_left = None
        self.mousedown_middle = None
        self.mousedown_right = None
        
        self.trackpad = False

        self.hit_pos = None
        self.hit_norm = None

        self.ctrl = False
        self.ctrl_left = False
        self.ctrl_right = False
        self.shift = False
        self.shift_left = False
        self.shift_right = False
        self.alt = False
        self.alt_left = False
        self.alt_right = False

        self.timer = False

    def update(self, context, event, timer):
        self.just_pressed = None

        self.context = context
        
        if context.region and hasattr(context.space_data, 'region_3d'):
            self.region = context.region
            self.size = (context.region.width,context.region.height)
            self.r3d = context.space_data.region_3d
        
        # # handle strange edge cases
        # if not context.area:
        #     #dprint('Context with no area')
        #     #dprint(context)
        #     return {'RUNNING_MODAL'}
        # if not hasattr(context.space_data, 'region_3d'):
        #     #dprint('context.space_data has no region_3d')
        #     #dprint(context)
        #     #dprint(context.space_data)
        #     return {'RUNNING_MODAL'}

        self.timer = (event.type in {'TIMER'})
        if self.timer:
            self.time_delta = timer.time_delta
            self.trackpad = False
            return

        t,pressed = event.type, event.value=='PRESS'

        if t in {'OSKEY','LEFT_CTRL','LEFT_SHIFT','LEFT_ALT','RIGHT_CTRL','RIGHT_SHIFT','RIGHT_ALT'}:
            if t == 'OSKEY':
                self.oskey = pressed
            else:
                l = t.startswith('LEFT_')
                if t in {'LEFT_CTRL', 'RIGHT_CTRL'}:
                    self.ctrl = pressed
                    if l: self.ctrl_left = pressed
                    else: self.ctrl_right = pressed
                if t in {'LEFT_SHIFT', 'RIGHT_SHIFT'}:
                    self.shift = pressed
                    if l: self.shift_left = pressed
                    else: self.shift_right = pressed
                if t in {'LEFT_ALT', 'RIGHT_ALT'}:
                    self.alt = pressed
                    if l: self.alt_left = pressed
                    else: self.alt_right = pressed
            return

        if t in {'MOUSEMOVE','INBETWEEN_MOUSEMOVE'}:
            self.mouse_prev = self.mouse
            self.mouse = Point2D((float(event.mouse_region_x), float(event.mouse_region_y)))
            return
        
        self.trackpad = (t == 'TRACKPADPAN') or (t == 'TRACKPADZOOM')

        if pressed and t in {'LEFTMOUSE','MIDDLEMOUSE','RIGHTMOUSE'}:
            self.mousedown = Point2D((float(event.mouse_region_x), float(event.mouse_region_y)))
            if event.type == 'LEFTMOUSE':
                self.mousedown_left = self.mousedown
            elif event.type == 'MIDDLEMOUSE':
                self.mousedown_middle = self.mousedown
            elif event.type == 'RIGHTMOUSE':
                self.mousedown_right = self.mousedown

        ftype = kmi_details(event)
        if pressed:
            if event.type not in self.now_pressed:
                self.just_pressed = ftype
            if 'WHEELUPMOUSE' in ftype or 'WHEELDOWNMOUSE' in ftype:
                # mouse wheel actions have no release, so handle specially
                self.just_pressed = ftype
            self.now_pressed[event.type] = ftype
        else:
            if event.type in self.now_pressed:
                del self.now_pressed[event.type]

    def convert(self, actions):
        t = type(actions)
        if t is list: actions = set(actions)
        elif t is not set: actions = {actions}
        ret = set()
        for action in actions:
            if action in self.keymap:
                ret |= self.keymap[action]
            else:
                ret.add(action)
        return ret


    def unuse(self, actions):
        actions = self.convert(actions)
        keys = [k for k,v in self.now_pressed.items() if v in actions]
        for k in keys: del self.now_pressed[k]
        self.just_pressed = None

    def unpress(self): self.just_pressed = None


    def using(self, actions, using_all=False):
        if actions is None: return False
        actions = self.convert(actions)
        if using_all:
            return all(p in actions for p in self.now_pressed.values())
        return any(p in actions for p in self.now_pressed.values())
    
    def navigating(self):
        actions = self.convert('navigate')
        if self.trackpad: return True
        if any(p in actions for p in self.now_pressed.values()): return True
        return False

    def pressed(self, actions, unpress=True, ignoremods=False):
        if actions is None: return False
        actions = self.convert(actions)
        just_pressed = self.just_pressed if not ignoremods else strip_mods(self.just_pressed)
        ret = just_pressed in actions
        if ret and unpress: self.just_pressed = None
        return ret

    def released(self, actions, released_all=False):
        if actions is None: return False
        return not self.using(actions, using_all=released_all)

    def warp_mouse(self, xy:Point2D):
        rx,ry = self.region.x,self.region.y
        mx,my = xy
        self.context.window.cursor_warp(rx + mx, ry + my)

    def valid_mouse(self):
        if self.mouse is None: return False
        mx,my = self.mouse
        sx,sy = self.size
        return mx >= 0 and my >= 0 and mx < sx and my < sy


class RFContext_Actions:
    def _init_actions(self):
        self.actions = Actions(self.rfmode.context)

    def _process_event(self, context, event):
        #if event.type not in {'TIMER','MOUSEMOVE','INBETWEEN_MOUSEMOVE'}: print(event.type)
        self.actions.update(context, event, self.timer)
