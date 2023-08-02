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

def fix_string(s, *, remove_indentation=True, remove_initial_newline=True, remove_trailing_spaces=True):
    if remove_initial_newline:
        s = re.sub(r'^\n', '', s)

    if remove_trailing_spaces:
        s = re.sub(r' +\n', '\n', s)
        s = re.sub(r' +$', '', s)

    if remove_indentation:
        indent = min((
            len(line) - len(line.lstrip())
            for line in s.splitlines()
            if line.strip()
        ), default=0)

        s = '\n'.join(
            line if not line.strip() else line[indent:]
            for line in s.splitlines()
        )

    return s
