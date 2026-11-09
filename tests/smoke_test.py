"""
Smoke test: RetopoFlow enables, registers, draws its UI, and unregisters cleanly in headless Blender.

    "/Applications/Blender 5.2.app/Contents/MacOS/Blender" -b --factory-startup --python-exit-code 1 \
        --python tests/smoke_test.py

Registers and unregisters twice, and checks that:
- nothing raises, and RF prints no exception that it caught and carried on from
- every keymap item RF adds calls an operator, menu or panel that exists
- the preferences, RF's menus, the items RF adds to Blender's menus, and each tool's settings in the
  tool header and sidebar (plus every panel and menu those open) draw without raising, and every
  operator, property, menu and panel they name exists
- unregister removes every class, property, keymap item, menu item, app handler and function patch
  that register added

Prints PASS or FAIL for each check and exits 1 if any check fails. Takes about a second. Needs
Blender 5.2 or newer, because RF compiles shaders when its modules import and 5.2 is the first
version with gpu.init().

RF's __init__ skips registration in background mode, so this enables the add-on through a temporary
extension repo that links to this checkout, then calls RFCore.register() itself. --factory-startup
keeps the temporary repo out of the saved preferences.
"""

import bpy, bmesh, gpu
import os, sys, io, inspect, tempfile, importlib, traceback, contextlib
from bl_ui import space_toolsystem_common

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = 'rf_smoke'
ADDON = f'bl_ext.{REPO}.retopoflow'

# Lines RF prints when it catches an exception and carries on
SWALLOWED_ERROR_MARKERS = ('traceback (most recent call last)', 'exception info', 'caught exception')


results = []
def check(title, cond, extra=''):
    print(f'{"PASS" if cond else "FAIL"} {title} {extra}')
    results.append(bool(cond))

def check_empty(title, problems, limit=20):
    check(title, not problems, f'({len(problems)} problems)' if problems else '')
    for problem in problems[:limit]:
        print(f'    {problem}')
    if len(problems) > limit:
        print(f'    ... and {len(problems) - limit} more')

def finish():
    os.unlink(os.path.join(repo_dir, 'retopoflow'))
    with contextlib.suppress(OSError):
        os.rmdir(repo_dir)
    failed = results.count(False)
    print(f'\n{len(results) - failed} passed, {failed} failed')
    sys.exit(1 if failed else 0)


class Tee(io.TextIOBase):
    def __init__(self, stream, buffer):
        self.stream, self.buffer = stream, buffer
    def write(self, s):
        self.buffer.write(s)
        return self.stream.write(s)
    def flush(self):
        self.stream.flush()

def run_phase(title, fn):
    """Run fn and fail if it raises or prints an exception that RF caught. Returns whether fn raised."""
    buffer = io.StringIO()
    stdout, stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = Tee(stdout, buffer), Tee(stderr, buffer)
    raised = None
    try:
        fn()
    except Exception:
        raised = traceback.format_exc()
    finally:
        sys.stdout, sys.stderr = stdout, stderr
    problems = [line.strip() for line in buffer.getvalue().splitlines() if any(m in line.lower() for m in SWALLOWED_ERROR_MARKERS)]
    if raised:
        problems.insert(0, raised.strip().splitlines()[-1])
        print(raised)
    check_empty(f'{title} runs without errors', problems)
    return raised is not None


###########################################################
# Blender state that registering adds and unregistering must remove

def describe(value):
    if callable(value):
        return f'{getattr(value, "__module__", "?")}.{getattr(value, "__qualname__", repr(value))}'
    return repr(value)

def iter_keymap_items():
    for kc in bpy.context.window_manager.keyconfigs:
        for km in kc.keymaps:
            for kmi in km.keymap_items:
                yield kc, km, kmi

def keymap_item_key(kc, km, kmi):
    return (kc.name, km.name, kmi.idname, kmi.type, kmi.value, kmi.any, kmi.shift, kmi.ctrl, kmi.alt, kmi.oskey)

def snapshot():
    types, draw_functions = {}, {}
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        rna = getattr(cls, 'bl_rna', None)
        if rna is None: continue
        types[name] = frozenset(rna.properties.keys())
        # Blender keeps a menu's list of draw functions after the last appended one is removed, so
        # compare the functions themselves
        draw = getattr(cls, 'draw', None)
        if draw: draw_functions[name] = tuple(describe(fn) for fn in getattr(draw, '_draw_funcs', None) or (draw,))
    return {
        'registered types': types,
        'keymap items': frozenset(keymap_item_key(*item) for item in iter_keymap_items()),
        'draw functions': draw_functions,
        'app handlers': {
            name: tuple(describe(fn) for fn in handlers)
            for name in dir(bpy.app.handlers)
            if isinstance(handlers := getattr(bpy.app.handlers, name), list)
        },
        # RF replaces these two module functions while registered
        'patched functions': {
            'bmesh.update_edit_mesh': bmesh.update_edit_mesh,
            'space_toolsystem_common.activate_by_id': space_toolsystem_common.activate_by_id,
        },
    }

def diff(before, after):
    lines = []
    for kind, a in before.items():
        b = after[kind]
        if isinstance(a, frozenset):
            lines += [f'{kind}: left behind {item}' for item in sorted(b - a)]
            lines += [f'{kind}: lost {item}' for item in sorted(a - b)]
            continue
        for name in sorted(set(a) | set(b)):
            va, vb = a.get(name), b.get(name)
            if va == vb: continue
            if va is None:
                lines.append(f'{kind}: left behind {name}')
            elif vb is None:
                lines.append(f'{kind}: lost {name}')
            elif isinstance(va, frozenset):
                lines.append(f'{kind}: {name} gained {sorted(vb - va)}, lost {sorted(va - vb)}')
            else:
                lines.append(f'{kind}: {name} changed from {describe(va)} to {describe(vb)}')
    return lines


###########################################################
# Name lookups for keymaps and UI

def operator_rna(idname):
    if '_OT_' in idname:
        module, name = idname.split('_OT_', 1)
        idname = f'{module.lower()}.{name}'
    module, _, name = idname.partition('.')
    try:
        return getattr(getattr(bpy.ops, module), name).get_rna_type()
    except (AttributeError, KeyError):
        return None

CALL_UI_OPERATORS = {'wm.call_menu': 'menu', 'wm.call_menu_pie': 'menu', 'wm.call_panel': 'panel'}

def keymap_problems(new_keys):
    problems = []
    for kc, km, kmi in iter_keymap_items():
        if keymap_item_key(kc, km, kmi) not in new_keys: continue
        where = f'{km.name}: {kmi.idname} ({kmi.type})'
        if not operator_rna(kmi.idname):
            problems.append(f'{where}: operator does not exist')
        elif kmi.idname in CALL_UI_OPERATORS:
            if not hasattr(bpy.types, kmi.properties.name):
                problems.append(f'{where}: {kmi.properties.name!r} does not exist')
    return problems


class OperatorProperties:
    """Stands in for what UILayout.operator() returns, checking each property the draw code sets."""
    def __init__(self, layout, idname, rna):
        object.__setattr__(self, '_layout', layout)
        object.__setattr__(self, '_idname', idname)
        object.__setattr__(self, '_names', set(rna.properties.keys()))
    def __setattr__(self, name, value):
        if name not in self._names:
            self._layout._problem(f'operator {self._idname!r} has no property {name!r}')
        elif name == 'name' and self._idname in CALL_UI_OPERATORS:
            self._layout._follow(CALL_UI_OPERATORS[self._idname], value)

class Layout:
    """Stands in for UILayout. Accepts any call and checks the operators, menus, panels and
    properties that the draw code names, since a real layout only reports those as red text."""
    def __init__(self, run, where):
        object.__setattr__(self, '_run', run)
        object.__setattr__(self, '_where', where)
    def _problem(self, message):
        self._run.problem(f'{self._where}: {message}')
    def _child(self, *args, **kwargs):
        return Layout(self._run, self._where)
    def _check_prop(self, data, prop):
        if data is None:
            self._problem(f'property {prop!r} drawn from None')
        elif prop.startswith('['):
            pass  # custom property path
        elif not hasattr(data, 'bl_rna'):
            self._problem(f'property {prop!r} drawn from {type(data).__name__}, which is not Blender data')
        elif prop not in data.bl_rna.properties.keys():
            self._problem(f'{data.bl_rna.identifier} has no property {prop!r}')
    def _follow(self, kind, name):
        cls = getattr(bpy.types, name, None)
        if cls is None:
            self._problem(f'{kind} {name!r} does not exist')
        else:
            self._run.draw_class(cls)

    def __getattr__(self, name):
        return self._child
    def __setattr__(self, name, value):
        pass
    def __bool__(self):
        return True

    def operator(self, operator, *args, **kwargs):
        rna = operator_rna(operator)
        if not rna:
            self._problem(f'operator {operator!r} does not exist')
            return self._child()
        return OperatorProperties(self, operator, rna)
    def operator_menu_enum(self, operator, property, *args, **kwargs):
        rna = operator_rna(operator)
        if not rna:
            self._problem(f'operator {operator!r} does not exist')
        elif property not in rna.properties.keys():
            self._problem(f'operator {operator!r} has no property {property!r}')
        return self._child()
    def prop(self, data, property, *args, **kwargs):
        self._check_prop(data, property)
        return self._child()
    prop_enum = prop_menu_enum = prop_tabs_enum = props_enum = prop_with_popover = prop_with_menu = prop
    def prop_search(self, data, property, search_data, search_property, *args, **kwargs):
        self._check_prop(data, property)
        self._check_prop(search_data, search_property)
        return self._child()
    def menu(self, menu, *args, **kwargs):
        self._follow('menu', menu)
        return self._child()
    menu_contents = menu
    def popover(self, panel, *args, **kwargs):
        self._follow('panel', panel)
        return self._child()
    def panel(self, *args, **kwargs):
        return self._child(), self._child()
    def panel_prop(self, data, property, *args, **kwargs):
        self._check_prop(data, property)
        return self._child(), self._child()


class DrawHost:
    """Stands in for the Panel, Menu or AddonPreferences instance a draw function gets as self."""
    def __init__(self, cls, layout, instance=None):
        object.__setattr__(self, 'layout', layout)
        object.__setattr__(self, '_cls', cls)
        object.__setattr__(self, '_instance', instance)
    def __getattr__(self, name):
        if self._instance is not None and not inspect.isfunction(getattr(self._cls, name, None)):
            return getattr(self._instance, name)
        value = getattr(self._cls, name)
        return value.__get__(self) if inspect.isfunction(value) else value


def is_rf(obj):
    return getattr(obj, '__module__', '').startswith(ADDON)

def view3d_override(region_type='WINDOW'):
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == region_type)
    return bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region)

class DrawRun:
    """Draws RF's UI with one tool active. Follows popover and menu references into RF's panels and
    menus, the way Blender draws them when the artist opens them, drawing each class once."""
    def __init__(self, tool_label, problems, reached):
        self.tool_label, self.problems, self.reached, self.drawn = tool_label, problems, reached, set()

    def problem(self, text):
        # The same problem usually shows up with every tool active, so collect the tools per problem
        self.problems.setdefault(text, []).append(self.tool_label)

    def call(self, where, fn, *args):
        try:
            fn(*args)
        except Exception as e:
            frame = traceback.extract_tb(e.__traceback__)[-1]
            self.problem(f'{where}: raised {type(e).__name__}: {e} ({os.path.basename(frame.filename)}:{frame.lineno})')

    def draw_function(self, where, fn, host_cls, instance=None):
        self.call(where, fn, DrawHost(host_cls, Layout(self, where), instance), bpy.context)

    def draw_class(self, cls, instance=None):
        if cls in self.drawn: return
        self.drawn.add(cls)
        self.reached.add(cls)
        poll = getattr(cls, 'poll', None)
        if is_rf(poll) and not poll(bpy.context): return
        for method in ('draw_header', 'draw'):
            fn = getattr(cls, method, None)
            if is_rf(fn): self.draw_function(f'{cls.__name__}.{method}', fn, cls, instance)

def ui_problems(new_type_names, rftools):
    """Draw RF's UI with a stand-in layout: the preferences, then for each tool in the toolbar its
    settings in the tool header and the sidebar, RF's menus, and the items RF adds to Blender's menus.
    Returns the problems, and the RF panels that nothing drew."""
    problems, reached = {}, set()
    context = bpy.context
    rf_classes = [getattr(bpy.types, name) for name in sorted(new_type_names)]
    rf_menus = [cls for cls in rf_classes if issubclass(cls, bpy.types.Menu)]
    rf_panels = [cls for cls in rf_classes if issubclass(cls, bpy.types.Panel)]
    appended = [
        (cls, fn)
        for cls in (getattr(bpy.types, name) for name in dir(bpy.types))
        for fn in getattr(getattr(cls, 'draw', None), '_draw_funcs', None) or ()
        if is_rf(fn)
    ]

    with view3d_override():
        prefs = context.preferences.addons[ADDON].preferences
        DrawRun(None, problems, reached).draw_class(type(prefs), instance=prefs)

    for idname, rftool in rftools.items():
        if rftool.rf_hide_from_toolbar: continue
        # Pause RFCore so the tool switch does not start RF's modal operator, which cannot run headless
        with view3d_override(), RFCore.paused():
            bpy.ops.wm.tool_set_by_id(name=idname)
        tool = context.workspace.tools.from_space_view3d_mode(context.mode)
        if tool.idname != idname:
            problems[f'could not make {idname} the active tool'] = [None]
            continue
        for region_type in ('TOOL_HEADER', 'UI'):
            run = DrawRun(rftool.bl_label, problems, reached)
            where = f'{rftool.__name__}.draw_settings in {region_type}'
            with view3d_override(region_type):
                run.call(where, rftool.draw_settings, context, Layout(run, where), tool)
        run = DrawRun(rftool.bl_label, problems, reached)
        with view3d_override():
            for cls in rf_menus:
                run.draw_class(cls)
            for cls, fn in appended:
                run.draw_function(f'{cls.__name__} item {fn.__qualname__}', fn, cls)

    with view3d_override(), RFCore.paused():
        bpy.ops.wm.tool_set_by_id(name='builtin.select_box')

    lines = []
    for text, tool_labels in problems.items():
        tool_labels = [label for label in dict.fromkeys(tool_labels) if label]
        lines.append(f'{text} (with {", ".join(tool_labels)} active)' if tool_labels else text)
    return lines, [cls.__name__ for cls in rf_panels if cls not in reached]


###########################################################
# Setup

if not hasattr(gpu, 'init'):
    print(f'FAIL Blender {bpy.app.version_string} has no gpu.init(), so RF cannot import headless. Use Blender 5.2 or newer.')
    sys.exit(1)
gpu.init()

# A source to retopologize and a target in Edit Mode, so draw code sees what it sees in use
bpy.ops.mesh.primitive_uv_sphere_add()
bpy.context.active_object.name = 'Source'
bpy.ops.mesh.primitive_plane_add(location=(0, 0, 2))
bpy.context.active_object.name = 'Target'
bpy.ops.object.mode_set(mode='EDIT')

repo_dir = tempfile.mkdtemp(prefix='rf_smoke_')
os.symlink(ROOT, os.path.join(repo_dir, 'retopoflow'))
repo = bpy.context.preferences.extensions.repos.new(name=REPO, module=REPO, custom_directory=repo_dir)
repo.use_custom_directory = True
bpy.ops.extensions.repo_refresh_all()

RFCore = RFTools = None
def enable():
    global RFCore, RFTools
    bpy.ops.preferences.addon_enable(module=ADDON)
    rfcore = importlib.import_module(f'{ADDON}.retopoflow.rfcore')
    RFCore, RFTools = rfcore.RFCore, rfcore.RFTools
if run_phase('enabling the add-on and importing RFCore', enable):
    finish()
check('add-on is listed as enabled', ADDON in bpy.context.preferences.addons)


###########################################################
# Register and unregister twice. The second round catches state the first unregister left behind,
# which is what an artist hits when they disable and re-enable the add-on.

before = snapshot()
for label in ('', ' again'):
    if run_phase(f'register{label}', RFCore.register):
        finish()
    registered = snapshot()
    new_types = set(registered['registered types']) - set(before['registered types'])
    new_keymap_items = registered['keymap items'] - before['keymap items']
    check(
        f'register{label} adds classes and keymap items',
        new_types and new_keymap_items,
        f'({len(new_types)} classes, {len(new_keymap_items)} keymap items)',
    )
    check_empty(f'register{label}: keymap items call operators and menus that exist', keymap_problems(new_keymap_items))
    problems, undrawn = ui_problems(new_types, RFTools)
    check_empty(f'register{label}: UI draws without errors and names things that exist', problems)
    if undrawn:
        print(f'    note: no tool settings or menu opens these panels, so they were not drawn: {", ".join(undrawn)}')

    if run_phase(f'unregister{label}', RFCore.unregister):
        finish()
    check_empty(f'unregister{label} leaves Blender as it was before register', diff(before, snapshot()))

finish()
