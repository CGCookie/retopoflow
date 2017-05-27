import bpy
import bgl
from bpy.types import SpaceView3D


class RFMode_UI:

    def ui_start(self):
        self.cb_pv_handle  = SpaceView3D.draw_handler_add(self.draw_callback_postview,  (self.context, ), 'WINDOW', 'POST_VIEW')
        self.cb_pp_handle  = SpaceView3D.draw_handler_add(self.draw_callback_postpixel, (self.context, ), 'WINDOW', 'POST_PIXEL')
        self.context.area.header_text_set('RetopoFlow Mode')
    
    def ui_end(self):
        if self.cb_pv_handle:
            SpaceView3D.draw_handler_remove(self.cb_pv_handle, "WINDOW")
            self.cb_pv_handle = None
        if self.cb_pp_handle:
            SpaceView3D.draw_handler_remove(self.cb_pp_handle, "WINDOW")
            self.cb_pp_handle = None
        self.context.area.header_text_set()

    ####################################################################
    # Draw handler function
    def draw_callback_postview(self, context):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        self.context = context
        try:
            self.draw_postview()
        except:
            self.handle_exception()
        bgl.glPopAttrib()                           # restore OpenGL attributes

    def draw_callback_postpixel(self, context):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        self.context = context
        try:
            self.draw_postpixel()
            if self.settings.show_help and self.help_box:
                self.help_box.draw()
        except:
            self.handle_exception()
        bgl.glPopAttrib()                           # restore OpenGL attributes

    def process_event_details(self, context, event):
        '''
        Construct an event dictionary that is *slightly* more
        convenient than stringing together a bunch of logical
        conditions
        '''
        self.context = context
        self.event   = event

        event_ctrl  = 'CTRL+'  if event.ctrl  else ''
        event_shift = 'SHIFT+' if event.shift else ''
        event_alt   = 'ALT+'   if event.alt   else ''
        event_oskey = 'OSKEY+' if event.oskey else ''
        event_ftype = event_ctrl + event_shift + event_alt + event_oskey + event.type

        self.eventd = {
            'context': context,
            'region':  context.region,
            'r3d':     context.space_data.region_3d,

            'event':   event,

            'ctrl':    event.ctrl,
            'shift':   event.shift,
            'alt':     event.alt,
            'value':   event.value,
            'type':    event.type,

            'ftype':   event_ftype,
            'press':   event_ftype if event.value=='PRESS'   else None,
            'release': event_ftype if event.value=='RELEASE' else None,

            'mouse':   (float(event.mouse_region_x), float(event.mouse_region_y)),
            'mousepre':self.eventd['mouse'],
        }
        
        return self.eventd

