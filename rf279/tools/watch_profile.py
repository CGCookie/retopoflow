#!/usr/bin/python3

'''
Copyright (C) 2017 CG Cookie
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


import os
import sys
import time
import shutil
import Levenshtein

filename = 'profile.txt'
sleeptime = 0.1


# https://en.wikipedia.org/wiki/ANSI_escape_code
def cursorSet(row=1, col=1): sys.stdout.write('\033[%i;%iH' % (row, col))
def cursorUp(): sys.stdout.write('\033[A')
def cursorDown(): sys.stdout.write('\033[B')
def cursorRight(): sys.stdout.write('\033[C')
def cursorLeft(): sys.stdout.write('\033[D')
def cls(clearDisplay=True, clearBuffer=True, resetCursor=True):
    # clear terminal, clear buffer, reset cursor position
    if clearDisplay: sys.stdout.write('\033[2J')
    if clearBuffer: sys.stdout.write('\033[3J')
    if resetCursor: sys.stdout.write('\033[H')
def getANSI(opts=None):
    if not opts:
        # reset
        return '\033[0m'
    optcodes = {
        'reset':          0,
        'bold':           1,
        'underline':      4,
        'blink':          5, # 5:slow; 6:rapid
        'inverse':        7,
        'normal':        22, # normal color or intensity
        'underline off': 24,
        'blink off':     25,
        'inverse off':   27,
        'fg:black':      30,
        'fg:red':        31,
        'fg:green':      32,
        'fg:brown':      33,
        'fg:blue':       34,
        'fg:purple':     35,
        'fg:cyan':       36,
        'fg:white':      37,
        'fg:default':    39,
        'bg:black':      40,
        'bg:red':        41,
        'bg:green':      42,
        'bg:brown':      43,
        'bg:blue':       44,
        'bg:purple':     45,
        'bg:cyan':       46,
        'bg:white':      47,
        'bg:default':    49,
    }
    codes = [optcodes[opt] for opt in opts]
    code = ';'.join(map(str, codes))
    return '\033[%sm' % code
def writeANSI(opts=None): sys.stdout.write(getANSI(opts))
def getc(s, opts=None):
    return '%s%s%s' % (getANSI(opts), s, getANSI() if opts else '')

def printc(s, opts=None): writec('%s\n' % s, opts=opts)
def writec(s, opts=None): sys.stdout.write(getc(s, opts=opts))

# https://docs.python.org/3/library/shutil.html#querying-the-size-of-the-output-terminal
def getTermSize():
    return shutil.get_terminal_size()

def getChanges(line, prev):
    bestline,bestcost = None,-1
    for prevl in prev:
        if line == prevl:
            return getc(line)
        cost = Levenshtein.distance(line, prevl)
        if not bestline or cost < bestcost:
            bestline,bestcost = prevl,cost
    if not bestline:
        return getc(line, opts={'bg:green','fg:white','bold'})
    s = []
    for op,i0,l0,i1,l1 in Levenshtein.opcodes(bestline, line):
        if op == 'equal':
            s += [getc(line[i1:l1], opts={'normal'})]
        elif op == 'insert':
            s += [getc(line[i1:l1], opts={'bg:green','fg:white','bold'})]
        elif op == 'replace':
            s += [getc(line[i1:l1], opts={'fg:green','bold'})]
    return ''.join(s)


fp = []
repeat = False
while True:
    cols,rows = getTermSize()
    
    f = fp
    while True:
        f_ = open(filename, 'rt').read().splitlines()
        if f_ == f: break
        f = f_
        time.sleep(sleeptime)
    
    if f == fp:
        continue
    #    if not repeat: continue
    #    repeat = False
    #else:
    #    repeat = True
    
    changes = [getChanges(line, fp) for line in f[:rows-1]]
    
    cls()
    sys.stdout.write('\n'.join(changes))
    
    fp = f
    
    time.sleep(sleeptime)

