'''
Copyright (C) 2018 CG Cookie
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

debugger = None
dprint = None
profiler = None
logger = None

def set_global(o):
    global debugger, dprint
    global profiler, logger

    cn = type(o).__name__
    if cn == 'Debugger':
        # print('setting debugger: ' + str(o))
        debugger = o
        dprint = o.dprint
    elif cn == 'Profiler':
        # print('setting profiler: ' + str(o))
        profiler = o
    elif cn == 'Logger':
        # print('setting logger: ' + str(o))
        logger = o
    else:
        assert False

def get_global(s):
    global debuggor, dprint
    global profiler, logger
    if s == 'debugger':
        return debugger
    if s == 'dprint':
        return dprint
    if s == 'profiler':
        return profiler
    if s == 'logger':
        return logger
    assert False
