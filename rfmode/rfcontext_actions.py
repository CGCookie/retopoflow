import bpy

from .. import key_maps
from ..lib.eventdetails import EventDetails

class Actions:
    def __init__(self):
        self.action = False
        self.cancel = False

class RFContext_Actions:
    def _init_actions(self):
        self.actions = Actions()
        
        self.eventd = EventDetails()    # context, event details, etc.
        # TODO: keymaps need rewritten
        self.keymap = key_maps.rtflow_default_keymap_generate()
        key_maps.navigation_language() # check keymap against system language
        user = key_maps.rtflow_user_keymap_generate()
        self.events_nav = user['navigate']
        self.events_selection = set()
        self.events_selection.update(user['select'])
        self.events_selection.update(user['select all'])
        self.events_confirm = user['confirm']
    
    def _process_event(self, context, event):
        self.eventd.update(context, event)
        
        if self.eventd.press in {'LEFTMOUSE'}:
            self.actions.action = True
        elif self.eventd.release in {'LEFTMOUSE'}:
            self.actions.action = False
