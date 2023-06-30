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


class UI_Core_Debug:
    def _init_debug(self):
        self._debug_list       = []

    def debug_print(self, d, already_printed):
        sp = '    '*d
        tag = self.as_html
        tagc = f'</{self._tagName}>'
        tagsc = f'{tag[:-1]} />'
        if self in already_printed:
            print(f'{sp}{tag}...{tagc}')
            return
        already_printed.add(self)
        if self._pseudoelement == 'text':
            innerText = self._innerText.replace('\n', '\\n') if self._innerText else ''
            print(f'{sp}"{innerText}"')
        elif self._children_all:
            print(f'{sp}{tag}')
            for c in self._children_all:
                c.debug_print(d+1, already_printed)
            print(f'{sp}{tagc}')
        else:
            print(f'{sp}{tagsc}')

    def structure(self, depth=0, all_children=False):
        l = self._children if not all_children else self._children_all
        return '\n'.join([('  '*depth) + str(self)] + [child.structure(depth+1) for child in l])

