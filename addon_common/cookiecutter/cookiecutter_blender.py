'''
Copyright (C) 2023 CG Cookie

https://github.com/CGCookie/retopoflow

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

import math
from inspect import ismethod, isfunction, signature
from contextlib import contextmanager

import bpy

from ..common.blender import region_label_to_data, create_simple_context, StoreRestore, BlenderSettings
from ..common.decorators import blender_version_wrapper, ignore_exceptions
from ..common.functools import find_fns, self_wrapper
from ..common.debug import debugger
from ..common.blender_cursors import Cursors
from ..common.utils import iter_head



class CookieCutter_Blender(BlenderSettings):
    def _cc_blenderui_init(self):
        self.storerestore_init()
        for _,fn in find_fns(self, '_blender_change_callback'):
            self.register_blender_change_callback(self_wrapper(self, fn))
        self._storerestore.store_all()

    @staticmethod
    def blender_change_callback(fn):
        fn._blender_change_callback = True
        return fn
    def register_blender_change_callback(self, fn):
        self._storerestore.register_storage_change_callback(fn)
    def blender_change_init(self, storage):
        self._storerestore.init_storage(storage)

    def _cc_blenderui_end(self, ignore=None):
        self._storerestore.restore_all(ignore=ignore)

        self.header_text_restore()
        self.statusbar_text_restore()
        self.cursor_restore()


