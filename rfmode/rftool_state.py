class RFTool_State():
    def __init__(self, **kwargs):
        self.update(kwargs)
    def update(self, kv):
        for k,v in kv.items():
            self.__setattr__(k, v)
