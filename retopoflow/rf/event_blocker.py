import functools
from ...addon_common.common.globals import Globals

def block_if_outside_working_area(fn):
    @functools.wraps(fn)
    def wrapped(self, *args, **kwargs):
        if is_outside_working_area(self):
            return
        return fn(self, *args, **kwargs)
    return wrapped

def block_if_idle_or_outside_working_area(default_return=None):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapped(self, *args, **kwargs):
            if self.actions.is_navigating:
                return default_return
            # BUG: this is causing issues with some tools (e.g. PolyPen)
            # if self.actions.is_idle:
            #     return default_return
            if is_outside_working_area(self):
                return default_return
            return fn(self, *args, **kwargs)
        return wrapped
    return decorator

def is_outside_working_area(self):
    # Only perform the check if no rftool is active.
    '''active_tool_state = self.rftool._fsm_in_main() # and (not self.rftool.rfwidget or self.rftool.rfwidget._fsm_in_main())
    if not active_tool_state:
        print('is_outside_context: active tool found - current state:', self.rftool._fsm.state)
        return False'''

    # Retrieve region from global drawing settings.
    area = Globals.drawing.area
    left   = area.x
    bottom = area.y
    right  = area.x + area.width
    top    = area.y + area.height

    # Get the mouse coordinates relative to the window.
    actions = self.actions
    mx = actions.mouse_win[0]
    my = actions.mouse_win[1]

    inside_region = (left <= mx <= right) and (bottom <= my <= top)

    # If the mouse is outside the region or if the UI document is hovered,
    # then skip processing.
    if not inside_region or self.document.is_hovering_any_element:
        return True # Block event processing.

    return False
