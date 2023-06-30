'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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

from .blender import tag_redraw_all
from .profiler import profiler, time_it
from .utils import iter_head, any_args, join

from . import ui_settings  # needs to be first
from .ui_core_utilities import UI_Core_Utils


class UI_Core_Dirtiness:
    def _init_dirtiness(self):
        # dirty properties
        # used to inform parent and children to recompute
        self._dirty_properties = {              # set of dirty properties, add through self.dirty to force propagation of dirtiness
            'style',                            # force recalculations of style
            'style parent',                     # force recalculations of style if parent selector changes
            'content',                          # content of self has changed
            'blocks',                           # children are grouped into blocks
            'size',                             # force recalculations of size
            'renderbuf',                        # force re-rendering buffer (if applicable)
        }
        self._new_content = True
        self._dirtying_flow = True
        self._dirtying_children_flow = True
        self._dirty_causes = []
        self._dirty_callbacks = { k:set() for k in UI_Core_Utils._cleaning_graph_nodes }
        self._dirty_propagation = {             # contains deferred dirty propagation for parent and children; parent will be dirtied later
            'defer':           False,           # set to True to defer dirty propagation (useful when many changes are occurring)
            'parent':          set(),           # set of properties to dirty for parent
            'parent callback': set(),           # set of dirty properties to inform parent
            'children':        set(),           # set of properties to dirty for children
        }
        self._defer_clean = False               # set to True to defer cleaning (useful when many changes are occurring)
        self._clean_debugging = {}
        self._do_not_dirty_parent = False       # special situation where self._parent attrib was set specifically in __init__ (ex: UI_Elements from innerText)
        self._draw_dirty_style = 0              # keeping track of times style is dirtied since last draw

    @profiler.function
    def dirty(self, **kwargs):
        self._dirty(**kwargs)
    @profiler.function
    def dirty_selector(self, **kwargs):
        self._dirty(properties={'selector'}, **kwargs)
    @profiler.function
    def dirty_style_parent(self, **kwargs):
        self._dirty(properties={'style parent'}, **kwargs)
    @profiler.function
    def dirty_style(self, **kwargs):
        self._dirty(properties={'style'}, **kwargs)
    @profiler.function
    def dirty_content(self, **kwargs):
        self._dirty(properties={'content'}, **kwargs)
    @profiler.function
    def dirty_blocks(self, **kwargs):
        self._dirty(properties={'blocks'}, **kwargs)
    @profiler.function
    def dirty_size(self, **kwargs):
        self._dirty(properties={'size'}, **kwargs)
    @profiler.function
    def dirty_renderbuf(self, **kwargs):
        self._dirty(properties={'renderbuf'}, **kwargs)

    def _dirty(self, *, cause=None, properties=None, parent=False, children=False, propagate_up=True):
        # assert cause
        if cause is None: cause = 'Unspecified cause'
        if properties is None: properties = set(UI_Core_Utils._cleaning_graph_nodes)
        elif type(properties) is str:  properties = {properties}
        elif type(properties) is list: properties = set(properties)
        properties -= self._dirty_properties    # ignore dirtying properties that are already dirty
        if not properties: return               # no new dirtiness
        # if getattr(self, '_cleaning', False): print(f'{self} was dirtied ({properties}) while cleaning')
        self._dirty_properties |= properties
        if ui_settings.DEBUG_DIRTY: self._dirty_causes.append(cause)
        if self._do_not_dirty_parent: parent = False
        if parent:   self._dirty_propagation['parent']          |= properties   # dirty parent also (ex: size of self changes, so parent needs to layout)
        else:        self._dirty_propagation['parent callback'] |= properties   # let parent know self is dirty (ex: background color changes, so we need to update style of self but not parent)
        if children: self._dirty_propagation['children']        |= properties   # dirty all children also (ex: :hover pseudoclass added, so children might be affected)

        # any dirtiness _ALWAYS_ dirties renderbuf of self and parent
        self._dirty_properties.add('renderbuf')
        self._dirty_propagation['parent'].add('renderbuf')

        if propagate_up: self.propagate_dirtiness_up()
        self.dirty_flow(children=False)
        # print(f'{self} had {properties} dirtied, because {cause}')
        tag_redraw_all("UI_Element dirty")

    def add_dirty_callback(self, child, properties):
        if type(properties) is str: properties = [properties]
        if not properties: return
        propagate_props = {
            p for p in properties
            if p not in self._dirty_properties
                and child not in self._dirty_callbacks[p]
        }
        if not propagate_props: return
        for p in propagate_props: self._dirty_callbacks[p].add(child)
        self.add_dirty_callback_to_parent(propagate_props)

    def add_dirty_callback_to_parent(self, properties):
        if not self._parent: return
        if self._do_not_dirty_parent: return
        if not properties: return
        self._parent.add_dirty_callback(self, properties)


    @profiler.function
    def dirty_styling(self):
        '''
        NOTE: this function clears style cache for self and all descendants
        '''
        self._computed_styles = {}
        self._styling_parent = None
        # self._styling_custom = None
        self._style_content_hash = None
        self._style_size_hash = None
        for child in self._children_all: child.dirty_styling()
        self.dirty_style(cause='Dirtying style cache')



    @profiler.function
    def dirty_flow(self, parent=True, children=True):
        if self._dirtying_flow and self._dirtying_children_flow: return
        if not self._dirtying_flow:
            if parent and self._parent and not self._do_not_dirty_parent:
                self._parent.dirty_flow(children=False)
            self._dirtying_flow = True
        self._dirtying_children_flow |= self._computed_styles.get('display', 'block') == 'table'
        tag_redraw_all("UI_Element dirty_flow")

    @property
    def is_dirty(self):
        return any_args(
            self._dirty_properties,
            self._dirty_propagation['parent'],
            self._dirty_propagation['parent callback'],
            self._dirty_propagation['children'],
        )

    @profiler.function
    def propagate_dirtiness_up(self):
        if self._dirty_propagation['defer']: return

        if self._dirty_propagation['parent']:
            if self._parent and not self._do_not_dirty_parent:
                cause = ''
                if ui_settings.DEBUG_DIRTY:
                    cause = ' -> '.join(f'{cause}' for cause in (self._dirty_causes+[
                        f"\"propagating dirtiness ({self._dirty_propagation['parent']} from {self} to parent {self._parent}\""
                    ]))
                self._parent.dirty(
                    cause=cause,
                    properties=self._dirty_propagation['parent'],
                    parent=True,
                    children=False,
                )
            self._dirty_propagation['parent'].clear()

        if not self._do_not_dirty_parent:
            self.add_dirty_callback_to_parent(self._dirty_propagation['parent callback'])
        self._dirty_propagation['parent callback'].clear()

        self._dirty_causes = []

    @profiler.function
    def propagate_dirtiness_down(self):
        if self._dirty_propagation['defer']: return

        if not self._dirty_propagation['children']: return

        # no need to dirty ::before, ::after, or text, because they will be reconstructed
        for child in self._children:
            child.dirty(
                cause=f'propagating {self._dirty_propagation["children"]}',
                properties=self._dirty_propagation['children'],
                parent=False,
                children=True,
            )
        for child in self._children_gen:
            child.dirty(
                cause=f'propagating {self._dirty_propagation["children"]}',
                properties=self._dirty_propagation['children'],
                parent=False,
                children=True
            )
        self._dirty_propagation['children'].clear()



    @property
    def defer_dirty_propagation(self):
        return self._dirty_propagation['defer']
    @defer_dirty_propagation.setter
    def defer_dirty_propagation(self, v):
        self._dirty_propagation['defer'] = bool(v)
        self.propagate_dirtiness_up()

    def _call_preclean(self):
        if not self.is_dirty:  return
        if not self._preclean: return
        self._preclean()
    def _call_postclean(self):
        if not self._was_dirty: return
        self._was_dirty = False
        if not self._postclean: return
        self._postclean()
    def _call_postflow(self):
        if not self._postflow: return
        if not self.is_visible: return
        self._postflow()

    @property
    def defer_clean(self):
        if not self._document: return True
        if self._document.defer_cleaning: return True
        if self._defer_clean: return True
        # if not self.is_dirty: return True
        return False
    @defer_clean.setter
    def defer_clean(self, value):
        self._defer_clean = value

    @profiler.function
    def clean(self, depth=0):
        '''
        No need to clean if
        - already clean,
        - possibly more dirtiness to propagate,
        - if deferring cleaning.
        '''

        if self._dirty_propagation['defer']: return
        if self.defer_clean: return
        if not self.is_dirty: return

        self._was_dirty = True   # used to know if postclean should get called

        self._cleaning = True

        profiler.add_note(f'pre: {self._dirty_properties}, {self._dirty_causes} {self._dirty_propagation}')
        if ui_settings.DEBUG_LIST: self._debug_list.append(f'{time.ctime()} clean started defer={self.defer_clean}')

        # propagate dirtiness one level down
        self.propagate_dirtiness_down()

        # self.call_cleaning_callbacks()
        self._compute_selector()
        self._compute_style()
        if self.is_visible:
            self._compute_content()
            self._compute_blocks()
            self._compute_static_content_size()
            self._renderbuf()

            profiler.add_note(f'mid: {self._dirty_properties}, {self._dirty_causes} {self._dirty_propagation}')

            for child in self._children_all:
               child.clean(depth=depth+1)

        profiler.add_note(f'post: {self._dirty_properties}, {self._dirty_causes} {self._dirty_propagation}')
        if ui_settings.DEBUG_LIST: self._debug_list.append(f'{time.ctime()} clean done')

        # self._debug_list.clear()

        self._cleaning = False


    @profiler.function
    def call_cleaning_callbacks(self):
        g = UI_Core_Utils._cleaning_graph
        working = set(UI_Core_Utils._cleaning_graph_roots)
        done = set()
        restarts = []
        while working:
            current = working.pop()
            curnode = g[current]
            assert current not in done, f'cycle detected in cleaning callbacks ({current})'
            if not all(p in done for p in curnode['parents']): continue
            do_cleaning = False
            do_cleaning |= current in self._dirty_properties
            do_cleaning |= bool(self._dirty_callbacks.get(current, False))
            if do_cleaning:
                curnode['fn'](self)
            redirtied = [d for d in self._dirty_properties if d in done]
            if redirtied:
                # print('UI_Core.call_cleaning_callbacks:', self, current, 'dirtied', redirtied)
                if len(restarts) < 50:
                    profiler.add_note('restarting')
                    working = set(UI_Core_Utils._cleaning_graph_roots)
                    done = set()
                    restarts.append((curnode, self._dirty_properties))
                else:
                    return
            else:
                working.update(curnode['children'])
                done.add(current)
