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

from ..common.blender import get_text_block


class CookieCutter_Debug:
    cc_debug_print_to = 'CookieCutter_Debug'
    cc_debug_all_enabled = False
    cc_debug_actions_enabled = False

    def debug_print(self, label, *args, override_enabled=False, **kwargs):
        if not override_enabled and not self.cc_debug_all_enabled: return

        text_block = get_text_block(self.cc_debug_print_to)
        assert text_block
        text_block.cursor_set(0x7fffffff)   # move cursor to last line
        text_block.write(f'{label}: {", ".join(args)}\n')
        for k,v in kwargs.items():
            text_block.write(f'  {k} = {v}\n')
        text_block.write('\n')

    def debug_print_actions(self, *args, **kwargs):
        self.debug_print(
            'Action',
            *args,
            override_enabled=self.cc_debug_actions_enabled,
            **kwargs
        )
