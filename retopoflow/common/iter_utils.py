

class AttrIter:
    def __init__(self, it, attr):
        self.it = iter(it)
        self.attr = attr
    
    def __iter__(self):
        return self
    
    def __next__(self):
        return getattr(next(self.it), self.attr)


class CastIter:
    def __init__(self, it, cast_type):
        self.it = iter(it)
        self.cast_type = cast_type
    
    def __iter__(self):
        return self
    
    def __next__(self):
        return self.cast_type(next(self.it))
