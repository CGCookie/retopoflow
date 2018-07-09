'''
Copyright (C) 2015 CG Cookie
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
import inspect
import time
from ...common_utilities import dprint, dcallstack, print_exception
from ....options import options, retopoflow_profiler


class Profiler:
    debug = options['profiler']
    filename = options['profiler_filename']
    broken = False

    class ProfilerHelper(object):
        def __init__(self, pr, text):
            full_text = (pr.stack[-1].full_text+'^' if pr.stack else '') + text
            if full_text in pr.d_start:
                Profiler.broken = True
                assert False, '"%s" found in profiler already?' % text
            self.pr = pr
            self.text = text
            self.full_text = full_text
            self._is_done = False
            self.pr.d_start[self.full_text] = time.time()
            self.pr.stack.append(self)

        def __del__(self):
            if Profiler.broken:
                return
            if self._is_done:
                return
            Profiler.broken = True
            print('Deleting Profiler before finished')
            #assert False, 'Deleting Profiler before finished'

        def update(self, key, delta):
            self.pr.d_count[key] = self.pr.d_count.get(key, 0) + 1
            self.pr.d_times[key] = self.pr.d_times.get(key, 0) + delta
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
            self.update(self.full_text, delta)
            self.update('~~ All Calls ~~', delta)
            self.update('~~ All Calls ~~^%s' % self.text, delta)
            del self.pr.d_start[self.full_text]

    class ProfilerHelper_Ignore:
        def __init__(self, *args, **kwargs): pass

        def done(self): pass

    def __init__(self):
        self.clear()

    def disable(self):
        self.debug = False
        options['profiler'] = False

    def enable(self):
        self.debug = True
        options['profiler'] = True

    def reset(self):
        self.broken = False
        self.clear()

    def clear(self):
        self.d_start = {}
        self.d_times = {}
        self.d_mins = {}
        self.d_maxs = {}
        self.d_last = {}
        self.d_count = {}
        self.stack = []
        self.last_profile_out = 0
        self.clear_time = time.time()

    def start(self, text=None, addFile=True):
        #assert not Profiler.broken
        if Profiler.broken:
            print('Profiler broken. Ignoring')
            return self.ProfilerHelper_Ignore()
        if not retopoflow_profiler or not self.debug:
            return self.ProfilerHelper_Ignore()

        frame = inspect.currentframe().f_back
        filename = os.path.basename(frame.f_code.co_filename)
        linenum = frame.f_lineno
        fnname = frame.f_code.co_name
        if addFile:
            text = text or fnname
            space = ' '*(30-len(text))
            text = '%s%s (%s:%d)' % (text, space, filename, linenum)
        else:
            text = text or fnname
        return self.ProfilerHelper(self, text)

    def __del__(self):
        # self.printout()
        pass

    def profile(self, fn):
        if not retopoflow_profiler or not self.debug:
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
            #assert not Profiler.broken
            if Profiler.broken:
                return fn(*args, **kwargs)
            pr = self.start(text=text, addFile=False)
            ret = None
            try:
                ret = fn(*args, **kwargs)
                pr.done()
                return ret
            except Exception as e:
                pr.done()
                print('CAUGHT EXCEPTION ' + str(e))
                print(text)
                print_exception()
                raise e
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    def strout(self):
        if not retopoflow_profiler or not self.debug:
            return ''
        s = [
            'Profiler:',
            '  run: %6.2fsecs' % (time.time() - self.clear_time),
            '----------------------------------------------------------------------------------------------',
            '   total      call   ------- seconds / call -------',
            '    secs /   count =   last,    min,    avg,    max  (  fps) - call stack',
            '----------------------------------------------------------------------------------------------',
        ]
        for text in sorted(self.d_times):
            tottime = self.d_times[text]
            totcount = self.d_count[text]
            avgt = tottime / totcount
            mint = self.d_mins[text]
            maxt = self.d_maxs[text]
            last = self.d_last[text]
            calls = text.split('^')
            t = text if len(calls) == 1 else (
                '    '*(len(calls)-2) + ' \\- ' + calls[-1])
            fps = totcount / tottime if tottime > 0 else 1000
            fps = ' 1k+ ' if fps >= 1000 else '%5.1f' % fps
            s += ['  %6.2f / %7d = %6.4f, %6.4f, %6.4f, %6.4f, (%s) - %s' % (
                tottime, totcount, last, mint, avgt, maxt, fps, t)]
        return '\n'.join(s)

    def printout(self):
        if not retopoflow_profiler or not self.debug:
            return
        dprint('%s\n\n\n' % self.strout(), l=0)

    def printfile(self, interval=0.25):
        # $ # to watch the file from terminal (bash) use:
        # $ watch --interval 0.1 cat filename

        if not retopoflow_profiler or not self.debug:
            return

        if time.time() < self.last_profile_out + interval:
            return
        self.last_profile_out = time.time()

        path, _ = os.path.split(os.path.abspath(__file__))
        # .. back to retopoflow root
        filename = os.path.join(path, '..', '..', '..', self.filename)
        open(filename, 'wt').write(self.strout())


profiler = Profiler()
