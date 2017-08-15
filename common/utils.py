import bpy

def iter_pairs(items, wrap, repeat=False):
    if not items: return
    while True:
        for i0,i1 in zip(items[:-1],items[1:]): yield i0,i1
        if wrap: yield items[-1],items[0]
        if not repeat: return

def rotate_cycle(cycle, offset):
    l = len(cycle)
    return [cycle[(l + ((i - offset) % l)) % l] for i in range(l)]

def hash_cycle(cycle):
    l = len(cycle)
    h = [hash(v) for v in cycle]
    m = min(h)
    mi = h.index(m)
    h = rotate_cycle(h, -mi)
    if h[1] > h[-1]:
       h.reverse()
       h = rotate_cycle(h, 1)
    return ' '.join(str(c) for c in h)

def max_index(vals, key=None):
    if not key: return max(enumerate(vals), key=lambda ival:ival[1])[0]
    return max(enumerate(vals), key=lambda ival:key(ival[1]))[0]

def min_index(vals, key=None):
    if not key: return min(enumerate(vals), key=lambda ival:ival[1])[0]
    return min(enumerate(vals), key=lambda ival:key(ival[1]))[0]


def blender_version(op, ver):
    def nop(*args, **kwargs): pass
    def nop_decorator(fn): return nop
    def fn_decorator(fn): return fn
    
    major,minor,rev = bpy.app.version
    blenderver = '%d.%02d' % (major,minor)
    print('%s %s %s' % (ver, op, blenderver))
    if   op == '<':  retfn = (blenderver < ver)
    elif op == '<=': retfn = (blenderver <= ver)
    elif op == '==': retfn = (blenderver == ver)
    elif op == '>=': retfn = (blenderver >= ver)
    elif op == '>':  retfn = (blenderver > ver)
    elif op == '!=': retfn = (blenderver != ver)
    else: assert False, 'unhandled op: "%s"' % op
    return fn_decorator if retfn else nop_decorator

