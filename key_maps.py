'''
Copyright (C) 2017 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, Patrick Moore

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

'''
Patrick Moore
Modify this file to change your default keymap for Retopoflow Tools

Events reported at 'CTRL+SHIFT+ALT+TYPE'
eg.   'CTRL+SHIFT+A' is a valid event but 'SHIFT+CTRL+A' is not

For a list of available key types, see
http://www.blender.org/documentation/blender_python_api_2_70a_release/bpy.types.Event.html?highlight=event.type#bpy.types.Event.type

DO NOT REMOVE ANY ITEMS from the default key_maps
If you want an item unmapped, do it as follows
def_cs_map['example_op'] = {}

Decent Resources:
#http://www.blender.org/documentation/blender_python_api_2_70a_release/bpy.types.KeyMapItem.html
#http://www.blender.org/documentation/blender_python_api_2_70a_release/bpy.types.KeyMap.html
#http://www.blender.org/documentation/blender_python_api_2_70a_release/bpy.types.KeyConfig.html
http://blender.stackexchange.com/questions/4832/how-to-find-the-right-keymap-to-change-on-addon-registration
'''
#Python Imports
import inspect
from copy import deepcopy

#Blender Imports
import bpy
from bpy.app.handlers import persistent

#CGCookie Imports
from .common.globals import dprint, debugger

def_rf_key_map = {}
#SHARED KEYS
def_rf_key_map['action'] = {'LEFTMOUSE'}
def_rf_key_map['select'] = {'LEFTMOUSE'}  #this is only used if there is conflict with user preferences
def_rf_key_map['select all'] = {'A'}
def_rf_key_map['cancel'] = {'ESC', 'CTRL+ALT+DEL'}
def_rf_key_map['confirm'] = {'RET', 'NUMPAD_ENTER'}
def_rf_key_map['modal confirm'] = {'SPACE', 'RET', 'NUMPAD_ENTER'}
def_rf_key_map['modal cancel'] = {'ESC'}
def_rf_key_map['modal precise'] = 'SHIFT'
def_rf_key_map['modal constrain'] = 'ALT'
def_rf_key_map['scale'] = {'S'}
def_rf_key_map['translate'] = {'G'}
def_rf_key_map['rotate'] = {'R'}
def_rf_key_map['delete'] = {'X', 'DEL'}
def_rf_key_map['view cursor'] = {'C'}
def_rf_key_map['undo'] = {'CTRL+Z'}
def_rf_key_map['redo'] = {'CTRL+SHIFT+Z'}
def_rf_key_map['help'] = {'SHIFT+SLASH'}
def_rf_key_map['snap cursor'] = {'SHIFT+S'}
def_rf_key_map['navigate'] = set() #To be filled in last
def_rf_key_map['up count'] = {'SHIFT+NUMPAD_PLUS','SHIFT+WHEELUPMOUSE'}
def_rf_key_map['dn count'] = {'SHIFT+NUMPAD_MINUS','SHIFT+WHEELDOWNMOUSE'}

#CONTOURS UNIQUE KEYS
def_rf_key_map['smooth'] = {'CTRL+S'}
#def_rf_key_map['bridge'] = {'B'}
def_rf_key_map['new'] = {'N'}
def_rf_key_map['align'] = {'SHIFT+A', 'CRTL+A', 'ALT+A'}
def_rf_key_map['up shift'] = {'LEFT_ARROW'}
def_rf_key_map['dn shift'] = {'RIGHT_ARROW'}
def_rf_key_map['mode'] = {'TAB'}

#POLYSTRIPS UNIQUE KEYS
def_rf_key_map['brush size'] = {'F'}
def_rf_key_map['brush falloff'] = {'CTRL+SHIFT+F'}
def_rf_key_map['brush strength'] = {'SHIFT+F'}
def_rf_key_map['change junction'] = {'CTRL+C'}
def_rf_key_map['dissolve'] = {'CTRL+D'}
def_rf_key_map['fill'] = {'SHIFT+F'}
def_rf_key_map['knife'] = {'K'}
def_rf_key_map['merge'] = {'M'}
def_rf_key_map['rip'] = {'CTRL+R'}
def_rf_key_map['rotate pole'] = {'R', 'SHIFT+R'}
def_rf_key_map['scale handles'] = {'CTRL+S'}
def_rf_key_map['align handles'] = {'C'}
def_rf_key_map['symmetry_x'] = {'SHIFT+X'}
def_rf_key_map['tweak move'] = {'T'}
def_rf_key_map['tweak relax'] = {'SHIFT+T'}
def_rf_key_map['untweak'] = {'CTRL+T'}
def_rf_key_map['update'] = {'CTRL+U'}
def_rf_key_map['zip'] = {'Z'}
def_rf_key_map['zip down'] = {'CTRL+NUMPAD_PLUS'}
def_rf_key_map['zip up'] = {'CTRL+NUMPAD_MINUS'}

#TWEAK UNIQUE KEYS
def_rf_key_map['tweak tool move'] = {'LEFTMOUSE'}
def_rf_key_map['tweak tool relax'] = {'SHIFT+LEFTMOUSE'}

#POLYPEN UNIQUE KEYS
def_rf_key_map['polypen action'] = {'CTRL+LEFTMOUSE'}
def_rf_key_map['polypen alt action'] = {'CTRL+ALT+LEFTMOUSE'}

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

def navigation_language():
    lang = bpy.context.user_preferences.system.language

    nav_dict = navigation_events
    old_dict = dict(nav_dict)

    for key, value in old_dict.items():
        for kmi in bpy.context.window_manager.keyconfigs['Blender'].keymaps['3D View'].keymap_items:
            try:
                if kmi.idname == value:
                    nav_dict[kmi.name] = nav_dict.pop(key)
                    # print('Updated key map item to "' + lang + '": ' + kmi.name)
            except KeyError as e:
                print('Key of ' + str(e) + ' not found, trying again')


def kmi_details(kmi):
    kmi_ctrl    = 'CTRL+'  if kmi.ctrl  else ''
    kmi_shift   = 'SHIFT+' if kmi.shift else ''
    kmi_alt     = 'ALT+'   if kmi.alt   else ''
    kmi_os      = 'OSKEY+'  if kmi.oskey else ''
    
    kmi_ftype   = kmi_ctrl + kmi_shift + kmi_alt + kmi_os
    if kmi.type == 'WHEELINMOUSE':
        dprint('WHEELUPMOUSE substituted for WHEELINMOUSE')
        kmi_ftype += 'WHEELUPMOUSE'
    
    elif kmi.type == 'WHEELOUTMOUSE':
        dprint('WHEELDOWNMOUSE substituted for WHEELOUTMOUSE')
        kmi_ftype += 'WHEELDOWNMOUSE'
    
    else:
        kmi_ftype  += kmi.type
    
    return kmi_ftype


def add_to_dict(km_dict, key, value, safety = True):
    if safety:
        for k in km_dict.keys():
            if value in km_dict[k]:
                dprint('%s is already part of keymap "%s"' % (value, key))
                debugger.dcallstack()
                return False

    if key not in km_dict:
        km_dict[key] = set([value])
        return True
    
    d = km_dict[key]
    if value not in d:
        d.add(value)
        return True
    else:
        return False

def rtflow_default_keymap_generate():
    km_dict = deepcopy(def_rf_key_map)
    
    for kmi in bpy.context.window_manager.keyconfigs['Blender'].keymaps['3D View'].keymap_items:
        if kmi.name in navigation_events:     
            add_to_dict(km_dict,'navigate',kmi_details(kmi))
    
    return km_dict


def rtflow_user_keymap_generate():
    km_dict = deepcopy(def_rf_key_map)
    if 'Blender User' not in bpy.context.window_manager.keyconfigs:
        dprint('No User Keymap, default keymap generated')
        return rtflow_default_keymap_generate()
    
    for kmi in bpy.context.window_manager.keyconfigs['Blender User'].keymaps['3D View'].keymap_items:
        if kmi.name in navigation_events:     
            add_to_dict(km_dict,'navigate',kmi_details(kmi))
    
    return km_dict

rtflow_keymap = None

def rtflow_keymap_retrieve():
    global rtflow_keymap  #TODO, make this classy
    if rtflow_keymap:
        return rtflow_keymap
    else:
        rtflow_keymap = rtflow_user_keymap_generate()
        return rtflow_keymap
 
