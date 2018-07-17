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


'''
This script will scan through the entire directory to check that
the GPL license has been applied to the top of every .py file
'''

import os
import glob

def checktop(path):
    contents = open(path, 'rt').read()
    # limit to top 50 lines
    contents = '\n'.join(contents.splitlines()[:50])
    # make lowercase for simple searching
    contents = contents.lower()
    # check if 'copyright' and 'gpl' are in contents
    checkfor = ['copyright', 'gnu general public license']
    missing = [chk for chk in checkfor if chk not in contents]
    if missing:
        print('%s: missing %s' % (path, ', '.join(missing)))

def scan(rootpath):
    for path in glob.glob(os.path.join(rootpath, '*')):
        if os.path.splitext(path)[1] == '.py':
            checktop(path)
        if os.path.isdir(path):
            scan(path)

if __name__ == '__main__':
    scan('.')