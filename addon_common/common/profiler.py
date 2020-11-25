'''
Copyright (C) 2020 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

import os
import time
import inspect
import contextlib

from .globals import Globals

def clamp(v, m, M):
    return max(m, min(M, v))

class ProfilerHelper:
    def __init__(self, pr, text):
        full_text = (pr.stack[-1].full_text+'^' if pr.stack else '') + text
        parent_text = (pr.stack[-1].full_text) if pr.stack else None
        if full_text in pr.d_start:
            Profiler._broken = True
            assert False, '"%s" found in profiler already?' % text
        self.pr = pr
        self.text = text
        self.full_text = full_text
        self.parent_text = parent_text
        self.all_call = '~~ All Calls ~~^%s' % text
        self.parent_all_call = pr.stack[-1].all_call if pr.stack else None
        self.direct_call = '~~ Direct Calls ~~^%s --> %s' % (pr.stack[-1].text if pr.stack else 'None', text)
        self.parent_direct_call = pr.stack[-1].direct_call if pr.stack else None
        self._is_done = False
        self.pr.d_start[self.full_text] = time.time()
        self.pr.stack.append(self)

    def __del__(self):
        if Profiler._broken:
            return
        if self._is_done:
            return
        Profiler._broken = True
        print('Deleting Profiler (%s) before finished' % self.full_text)
        #assert False, 'Deleting Profiler before finished'

    def update(self, key, delta, key_parent=None):
        self.pr.d_count[key] = self.pr.d_count.get(key, 0) + 1
        self.pr.d_times[key] = self.pr.d_times.get(key, 0) + delta
        if self.pr._keep_all_times:
            if key not in self.pr.d_times_all:
                self.pr.d_times_all[key] = []
            self.pr.d_times_all[key].append(delta)
        if key_parent:
            self.pr.d_times_sub[key_parent] = self.pr.d_times_sub.get(key_parent, 0) + delta
        self.pr.d_mins[key] = min(
            self.pr.d_mins.get(key, float('inf')), delta)
        self.pr.d_maxs[key] = max(
            self.pr.d_maxs.get(key, float('-inf')), delta)
        self.pr.d_last[key] = delta

    def done(self):
        while self.pr.stack and self.pr.stack[-1] != self:
            self.pr.stack.pop()
        if not self.pr.stack:
            if self.full_text in self.pr.d_start:
                del self.pr.d_start[self.full_text]
            return
        #assert self.pr.stack[-1] == self
        assert not self._is_done
        self.pr.stack.pop()
        self._is_done = True
        st = self.pr.d_start[self.full_text]
        en = time.time()
        delta = en-st
        self.update(self.full_text, delta, key_parent=self.parent_text)
        self.update('~~ All Calls ~~', delta)
        self.update(self.all_call, delta, key_parent=self.parent_all_call)
        self.update('~~ Direct Calls ~~', delta)
        self.update(self.direct_call, delta, key_parent=self.parent_direct_call)
        del self.pr.d_start[self.full_text]
        self.pr.clear_handler()

class ProfilerHelper_Ignore:
    def __init__(self, *args, **kwargs): pass
    def done(self): pass
profilerhelper_ignore = ProfilerHelper_Ignore()



class Profiler:
    _enabled = False
    _keep_all_times = False
    _filename = 'Profiler'
    _broken = False
    _clear = False

    @staticmethod
    def set_profiler_enabled(v):
        Profiler._enabled = v

    @staticmethod
    def get_profiler_enabled():
        return Profiler._enabled

    @staticmethod
    def set_profiler_filename(path):
        Profiler._filename = path

    @staticmethod
    def get_profiler_filename():
        return Profiler._filename

    def __init__(self):
        self.clear_handler(force=True)

    def reset(self):
        self._broken = False
        self.clear()

    @staticmethod
    def is_broken():
        return Profiler._broken

    def clear_handler(self, force=False):
        if not force:
            if not self._clear: return
            if self.stack: return
        self.d_start = {}
        self.d_times = {}
        self.d_times_sub = {}
        self.d_times_all = {}
        self.d_mins = {}
        self.d_maxs = {}
        self.d_last = {}
        self.d_count = {}
        self.stack = []
        self.last_profile_out = 0
        self.clear_time = time.time()
        self._clear = False

    def clear(self):
        self._clear = True
        self.clear_handler()

    def _start(self, text=None, addFile=True, enabled=True, n_backs=1):
        # assert not Profiler._broken
        if Profiler._broken:
            print('Profiler broken. Ignoring')
            return profilerhelper_ignore
        if not Profiler._enabled:
            return profilerhelper_ignore
        if not enabled:
            return profilerhelper_ignore

        frame = inspect.currentframe()
        for _ in range(n_backs): frame = frame.f_back
        filename = os.path.basename(frame.f_code.co_filename)
        linenum = frame.f_lineno
        fnname = frame.f_code.co_name
        if addFile:
            text = text or fnname
            space = ' '*(30-len(text))
            text = '%s%s (%s:%d)' % (text, space, filename, linenum)
        else:
            text = text or fnname
        return ProfilerHelper(self, text)

    def __del__(self):
        # self.printout()
        pass

    def add_note(self, *args, **kwargs):
        self._start(*args, n_backs=2, **kwargs).done()

    @contextlib.contextmanager
    def code(self, *args, enabled=True, **kwargs):
        if not Profiler._enabled or not enabled:
            yield None
            return
        try:
            pr = self._start(*args, n_backs=3, **kwargs)  # n_backs=3 for contextlib wrapper
            yield pr
            pr.done()
        except Exception as e:
            pr.done()
            print('Caught exception while profiling:', args, kwargs)
            Globals.debugger.print_exception()
            raise e

    # def function_params(self, *args):
    #     if not Profiler._enabled:
    #         def nowrapper(fn):
    #             return fn
    #         return nowrapper
        


    def function(self, fn):
        if not Profiler._enabled:
            return fn

        frame = inspect.currentframe().f_back
        f_locals = frame.f_locals
        filename = os.path.basename(frame.f_code.co_filename)
        clsname = f_locals['__qualname__'] if '__qualname__' in f_locals else ''
        linenum = frame.f_lineno
        fnname = fn.__name__  # frame.f_code.co_name
        if clsname:
            fnname = clsname + '.' + fnname
        space = ' '*(30-len(fnname))
        text = '%s%s (%s:%d)' % (fnname, space, filename, linenum)

        def wrapper(*args, **kwargs):
            # assert not Profiler._broken
            if Profiler._broken:
                return fn(*args, **kwargs)
            if not Profiler._enabled:
                return fn(*args, **kwargs)

            pr = self._start(text=text, addFile=False)
            ret = None
            try:
                ret = fn(*args, **kwargs)
                pr.done()
                return ret
            except Exception as e:
                pr.done()
                print('CAUGHT EXCEPTION ' + str(e))
                print(text)
                Globals.debugger.print_exception()
                raise e
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    def strout(self):
        all_width = 50
        all_chars = '.:-=+#%%@'
        # all_chars = ' .:;+=xX$'
        if not Profiler._enabled:
            return ''
        s = [
            'Profiler:',
            '  run: %6.2fsecs' % (time.time() - self.clear_time),
            '----------------------------------------------------------------------------------------------',
            '     total      call   ------- seconds / call -------             delta                         ',
            '      secs /   count =   last,    min,    avg,    max  (  fps) -  time  - call stack            ',
            '----------------------------------------------------------------------------------------------',
        ]
        for text in sorted(self.d_times):
            tottime = self.d_times[text]
            totcount = self.d_count[text]
            deltime = self.d_times[text] - self.d_times_sub.get(text, 0)
            avgt = tottime / totcount
            mint = self.d_mins[text]
            maxt = self.d_maxs[text]
            last = self.d_last[text]
            calls = text.split('^')
            t = text if len(calls) == 1 else (
                ' |  '*(len(calls)-2) + ' \\- ' + calls[-1])
            fps = totcount / tottime if tottime > 0 else 1000
            fps = ' 1k+ ' if fps >= 1000 else '%5.1f' % fps
            s += ['  %8.4f / %7d = %6.4f, %6.4f, %6.4f, %6.4f, (%s) - %6.2f - %s' % (
                tottime, totcount, last, mint, avgt, maxt, fps, deltime, t)]
            if self._keep_all_times and maxt > mint:
                histo = [0 for _ in range(all_width)]
                l = len(all_chars)
                for t in self.d_times_all[text]:
                    i = int(clamp((t - mint) / (maxt - mint) * all_width, 0, all_width-1))
                    histo[i] += 1
                m = max(histo)
                if m:
                    histo = [' ' if v==0 else all_chars[int(clamp(v/m*l, 0, l-1))] for v in histo]
                    s += ['                       [%s]' % ''.join(histo)]
        s += ['run: %6.2fsecs' % (time.time() - self.clear_time)]
        return '\n'.join(s)

    def printout(self):
        if not Profiler._enabled:
            return
        print('%s\n\n\n' % self.strout())

    def printfile(self, interval=0.25):
        # $ # to watch the file from terminal (bash) use:
        # $ watch --interval 0.1 cat filename

        if not Profiler._enabled:
            return

        if time.time() < self.last_profile_out + interval:
            return
        self.last_profile_out = time.time()

        # .. back to retopoflow root
        path = os.path.dirname(os.path.abspath(__file__))
        filename = os.path.join(path, '..', Profiler._filename)
        open(filename, 'wt').write(self.strout())

profiler = Profiler()
Globals.set(profiler)

# class CodeProfiler:
#     def __init__(self, *args, **kwargs):
#         self.args = args
#         self.kwargs = kwargs
#     def __enter__(self):
#         self.pr = profiler._start(*self.args, n_backs=2, **self.kwargs)
#     def __exit__(self, exc_type, exc_val, exc_tb):
#         self.pr.done()
# profiler.code = CodeProfiler



@contextlib.contextmanager
def time_it(*args, **kwargs):
    start = time.time()

    frame = inspect.currentframe()
    n_backs = 2
    for _ in range(n_backs): frame = frame.f_back
    filename = os.path.basename(frame.f_code.co_filename)
    linenum = frame.f_lineno
    fnname = frame.f_code.co_name

    try:
        yield None
    finally:
        print('time_it %s:%d fn:%s = %f' % (filename, linenum, fnname, time.time() - start))


