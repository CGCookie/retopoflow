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


class Actions:
    default_keymap = {
        # common
        'navigate': set(),          # to be filled in by self.load_keymap()
        'maximize area': set(),     # to be filled in by self.load_keymap()
        'action': {'LEFTMOUSE'},
        'select': {'RIGHTMOUSE'},   # TODO: update based on bpy.context.user_preferences.inputs.select_mouse
        'select add': {'SHIFT+RIGHTMOUSE'},
        'select all': {'A'},
        'cancel': {'ESC', 'RIGHTMOUSE'},
        'cancel no select': {'ESC'},
        'confirm': {'RET', 'NUMPAD_ENTER', 'LEFTMOUSE'},
        'undo': {'CTRL+Z'},
        'redo': {'CTRL+SHIFT+Z'},
        'done': {'ESC', 'RET', 'NUMPAD_ENTER'},
        
        'insert': {'CTRL+LEFTMOUSE'},
        'grab': {'G'},
        
        # widget
        'brush size': {'F'},
        'brush falloff': {'CTRL+SHIFT+F'},
        'brush strength': {'SHIFT+F'},
        
        # shortcuts to tools
        'move tool': {'T'},
        'relax tool': {'R'},
        'polypen tool': {'P'},
        'polystrips tool': {'S'},
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
    
    def load_keymap(self, keyconfig_name):
        if keyconfig_name not in bpy.context.window_manager.keyconfigs:
            dprint('No keyconfig named "%s"' % keyconfig_name)
            return
        keyconfig = bpy.context.window_manager.keyconfigs[keyconfig_name]
        for kmi in keyconfig.keymaps['3D View'].keymap_items:
            if kmi.name in self.navigation_events:
                self.keymap['navigate'].add(kmi_details(kmi))
        for kmi in keyconfig.keymaps['Screen'].keymap_items:
            if kmi.idname == 'screen.screen_full_area':
                self.keymap['maximize area'].add(kmi_details(kmi))
    
    def __init__(self):
        self.keymap = deepcopy(self.default_keymap)
        self.load_keymap('Blender')
        self.load_keymap('Blender User')
        #print('navigation: ' + str(self.keymap['navigate']))
        
        self.context = None
        self.region = None
        self.r3d = None
        self.size = (-1, -1)
        
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
        self.region,self.r3d  = context.region,context.space_data.region_3d
        self.size = (context.region.width,context.region.height)
        
        self.timer = (event.type in {'TIMER'})
        if self.timer:
            self.time_delta = timer.time_delta
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
    
    
    def using(self, actions):
        actions = self.convert(actions)
        return any(p in actions for p in self.now_pressed.values())
    
    def pressed(self, actions, unpress=True):
        actions = self.convert(actions)
        ret = self.just_pressed in actions
        if ret and unpress: self.just_pressed = None
        return ret
    
    def released(self, actions):
        return not self.using(actions)
    
    def warp_mouse(self, xy:Point2D):
        rx,ry = self.region.x,self.region.y
        mx,my = xy
        self.context.window.cursor_warp(rx + mx, ry + my)
    
    def valid_mouse(self):
        mx,my = self.mouse
        sx,sy = self.size
        return mx >= 0 and my >= 0 and mx < sx and my < sy


class RFContext_Actions:
    def _init_actions(self):
        self.actions = Actions()
    
    def _process_event(self, context, event):
        self.actions.update(context, event, self.timer)



