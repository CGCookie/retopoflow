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

#CGCookie Imports
from .lib.common_utilities import dcallstack

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
def_rf_key_map['update'] = {'CTRL+U'}
def_rf_key_map['zip'] = {'Z'}
def_rf_key_map['zip down'] = {'CTRL+NUMPAD_PLUS'}
def_rf_key_map['zip up'] = {'CTRL+NUMPAD_MINUS'}

#TWEAK UNIQUE KEYS
def_rf_key_map['tweak tool move'] = {'LEFTMOUSE'}
def_rf_key_map['tweak tool relax'] = {'SHIFT+LEFTMOUSE'}

navigation_events = {'Rotate View', 'Move View', 'Zoom View','Dolly View',
                     'View Pan', 'View Orbit', 'Rotate View', 
                     'View Persp/Ortho', 'View Numpad', 'NDOF Orbit View', 
                     'NDOF Pan View', 'View Selected', 'Center View to Cursor'}



def kmi_details(kmi):
        kmi_ctrl    = 'CTRL+'  if kmi.ctrl  else ''
        kmi_shift   = 'SHIFT+' if kmi.shift else ''
        kmi_alt     = 'ALT+'   if kmi.alt   else ''
        
        kmi_ftype   = kmi_ctrl + kmi_shift + kmi_alt
        if kmi.type == 'WHEELINMOUSE':
            print('WHEELUPMOUSE substituted for WHEELINMOUSE')
            kmi_ftype += 'WHEELUPMOUSE'
        
        elif kmi.type == 'WHEELOUTMOUSE':
            print('WHEELDOWNMOUSE substituted for WHEELOUTMOUSE')
            kmi_ftype += 'WHEELDOWNMOUSE'
        
        else:
            kmi_ftype  += kmi.type
        
        return kmi_ftype


def add_to_dict(km_dict, key, value, safety = True):   
    if safety:
        for k in km_dict.keys():
            if value in km_dict[k]:
                print('%s is already part of keymap "%s"' % (value, key))
                dcallstack()
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
        print('No User Keymap, default keymap generated')
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
 
