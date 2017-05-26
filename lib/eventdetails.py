class EventDetails:
    def __init__(self):
        self.context = None
        self.region  = None
        self.r3d     = None
        self.event   = None
        
        self.ctrl  = False
        self.shift = False
        self.alt   = False
        self.value = False
        self.type  = False
        
        self.ftype   = ''
        self.press   = ''
        self.release = ''
        
        self.mousedown = None
        self.mousepre = None
        self.mouse    = None
        
    
    def update(self, context, event):
        event_ctrl  = 'CTRL+'  if event.ctrl  else ''
        event_shift = 'SHIFT+' if event.shift else ''
        event_alt   = 'ALT+'   if event.alt   else ''
        event_oskey = 'OSKEY+' if event.oskey else ''
        event_ftype = event_ctrl + event_shift + event_alt + event_oskey + event.type
        
        self.context = context
        self.region  = context.region
        self.r3d     = context.space_data.region_3d
        self.event   = event

        self.ctrl  = event.ctrl
        self.shift = event.shift
        self.alt   = event.alt
        self.value = event.value
        self.type  = event.type

        self.ftype   = event_ftype
        self.press   = event_ftype if event.value=='PRESS'   else None
        self.release = event_ftype if event.value=='RELEASE' else None

        if event.value == 'PRESS' and event.type in {'LEFTMOUSE','MIDDLEMOUSE','RIGHTMOUSE'}:
            # TODO: only handles (correctly) one mousepress at a time!
            self.mousedown = (float(event.mouse_region_x), float(event.mouse_region_y))
        self.mousepre = self.mouse
        self.mouse    = (float(event.mouse_region_x), float(event.mouse_region_y))
