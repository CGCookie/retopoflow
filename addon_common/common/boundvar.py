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

import re
import copy
import math
import inspect

class IgnoreChange(Exception): pass

class BoundVar:
    def __init__(self, value_str, *, on_change=None, frame_depth=1, frames_deep=1, f_globals=None, f_locals=None, callbacks=None, validators=None, disabled=False, pre_wrap=None, post_wrap=None, wrap=None):
        assert type(value_str) is str, f'BoundVar: constructor needs value as string, but received {value_str} instead!'
        if f_globals is None or f_locals is None:
            frame = inspect.currentframe()
            ff_globals, ff_locals = {}, {}
            for i in range(frame_depth + frames_deep):
                if i >= frame_depth:
                    ff_globals = frame.f_globals | ff_globals
                    ff_locals  = frame.f_locals  | ff_locals
                frame = frame.f_back
            self._f_globals = f_globals or ff_globals
            self._f_locals  = dict(f_locals or ff_locals)
        else:
            self._f_globals = f_globals
            self._f_locals = dict(f_locals)
        try:
            exec(value_str, self._f_globals, self._f_locals)
        except Exception as e:
            print(f'Caught exception when trying to bind to variable')
            print(f'exception: {e}')
            print(f'globals: {self._f_globals}')
            print(f'locals: {self._f_locals}')
            assert False, f'BoundVar: value string ("{value_str}") must be a valid variable!'
        self._f_locals.update({'boundvar_interface': self._boundvar_interface})
        self._value_str  = value_str
        self._callbacks  = callbacks or []
        self._validators = validators or []
        self._disabled   = disabled
        self._pre_wrap  = wrap if wrap is not None else pre_wrap  if pre_wrap  is not None else ''
        self._post_wrap = wrap if wrap is not None else post_wrap if post_wrap is not None else ''
        if on_change: self.on_change(on_change)

    def clone_with_overrides(self, **overrides):
        # perform SHALLOW copy (shared attribs, such as _callbacks!) and override attribs as given
        other = copy.copy(self)
        for k, v in overiddes.iteritems():
            try:
                setattr(other, k, v)
            except AttributeError:
                setattr(other, f'_{k}', v)
        return other

    def _boundvar_interface(self, v): self._v = v
    def _call_callbacks(self):
        for cb in self._callbacks: cb()

    def __str__(self): return str(self.value)

    def get(self):
        return self.value
    def set(self, value):
        self.value = value

    @property
    def disabled(self):
        return self._disabled
    @disabled.setter
    def disabled(self, v):
        self._disabled = bool(v)
        self._call_callbacks()

    def get_value(self):
        exec(f'boundvar_interface({self._value_str})', self._f_globals, self._f_locals)
        return self._v
    def set_value(self, value):
        try:
            for validator in self._validators: value = validator(value)
        except IgnoreChange:
            return
        if self.value == value: return
        exec(f'{self._value_str} = {self._pre_wrap}{value}{self._post_wrap}', self._f_globals, self._f_locals)
        self._call_callbacks()

    @property
    def value(self):        return self.get_value()
    @value.setter
    def value(self, value): self.set_value(value)
    @property
    def value_as_str(self): return str(self)

    @property
    def is_bounded(self): return False

    def on_change(self, fn): self._callbacks.append(fn)

    def add_validator(self, fn): self._validators.append(fn)


class BoundString(BoundVar):
    def __init__(self, value_str, *, frame_depth=2, **kwargs):
        super().__init__(value_str, frame_depth=frame_depth, wrap='"', **kwargs)

class BoundStringToBool(BoundVar):
    def __init__(self, value_str, true_str, *, frame_depth=2, **kwargs):
        self._true_str = true_str
        super().__init__(value_str, frame_depth=frame_depth, wrap='"', **kwargs)

    @property
    def value(self):
        return self.get_value() == self._true_str
    @value.setter
    def value(self, v):
        if bool(v): self.set_value(self._true_str)
    @property
    def checked(self):
        return self.get_value() == self._true_str
    @checked.setter
    def checked(self, v):
        # sets to a true str iff v is True
        # assuming that some other BoundStringToBool will get set to True
        if bool(v): self.value = self._true_str


class BoundBool(BoundVar):
    def __init__(self, value_str, *, frame_depth=2, **kwargs):
        super().__init__(value_str, frame_depth=frame_depth, **kwargs)
    @property
    def checked(self): return self.get_value()
    @checked.setter
    def checked(self,v): self.set_value(v)


class BoundInt(BoundVar):
    def __init__(self, value_str, *, min_value=None, max_value=None, step_size=None, frame_depth=2, **kwargs):
        super().__init__(value_str, frame_depth=frame_depth, **kwargs)
        self._min_value = min_value
        self._max_value = max_value
        self._step_size = step_size or 0
        self.add_validator(self.int_validator)

    @property
    def min_value(self): return self._min_value

    @property
    def max_value(self): return self._max_value

    @property
    def step_size(self): return self._step_size

    @property
    def is_bounded(self):
        return self._min_value is not None and self._max_value is not None

    @property
    def bounded_ratio(self):
        assert self.is_bounded, f'Cannot compute bounded_ratio of unbounded BoundInt'
        return (self.value - self.min_value) / (self.max_value - self.min_value)

    def int_validator(self, value):
        try:
            t = type(value)
            if   t is str:   nv = int(re.sub(r'[^\d.-]', '', value))
            elif t is int:   nv = value
            elif t is float: nv = int(value)
            else: assert False, 'Unhandled type of value: %s (%s)' % (str(value), str(t))
            if self._min_value is not None: nv = max(nv, self._min_value)
            if self._max_value is not None: nv = min(nv, self._max_value)
            if self._step_size and self._min_value is not None:
                nv = math.floor((nv - self._min_value) / self._step_size) * self._step_size + self._min_value
            return nv
        except ValueError as e:
            raise IgnoreChange()
        except Exception:
            # ignoring all exceptions?
            raise IgnoreChange()

    def add_delta(self, scale):
        self.value += self.step_size * scale


class BoundFloat(BoundVar):
    def __init__(self, value_str, *, min_value=None, max_value=None, step_size=None, frame_depth=2, format_str=None, **kwargs):
        super().__init__(value_str, frame_depth=frame_depth, **kwargs)
        self._min_value = min_value
        self._max_value = max_value
        self._step_size = step_size or 0
        self.add_validator(self.float_validator)
        self._format_str = '%0.5f' if format_str is None else format_str

    def __str__(self):
        return self._format_str % self.value

    @property
    def min_value(self): return self._min_value

    @property
    def max_value(self): return self._max_value

    @property
    def step_size(self): return self._step_size

    @property
    def is_bounded(self):
        return self._min_value is not None and self._max_value is not None

    @property
    def bounded_ratio(self):
        assert self.is_bounded, f'Cannot compute bounded_ratio of unbounded BoundFloat'
        return (self.value - self.min_value) / (self.max_value - self.min_value)

    def float_validator(self, value):
        try:
            t = type(value)
            if   t is str:   nv = float(re.sub(r'[^\d.-]', '', value))
            elif t is int:   nv = float(value)
            elif t is float: nv = value
            else: assert False, 'Unhandled type of value: %s (%s)' % (str(value), str(t))
            if self._min_value is not None: nv = max(nv, self._min_value)
            if self._max_value is not None: nv = min(nv, self._max_value)
            if self._step_size and self._min_value is not None:
                nv = math.floor((nv - self._min_value) / self._step_size) * self._step_size + self._min_value
            return nv
        except ValueError as e:
            raise IgnoreChange()
        except Exception:
            # ignoring all exceptions?
            raise IgnoreChange()

    def add_delta(self, scale):
        self.value += self.step_size * scale

