'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning

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

from __future__ import annotations
from typing import Any, Iterable
from contextlib import contextmanager
from enum import IntEnum, auto, StrEnum
from ..ext import termcolor
import random
import time
import textwrap


class TextColor(StrEnum):
    BLACK = 'black'
    RED = 'red'
    GREEN = 'green'
    YELLOW = 'yellow'
    BLUE = 'blue'
    MAGENTA = 'magenta'
    CYAN = 'cyan'
    WHITE = 'white'
    LIGHT_GREY = 'light_grey'
    LIGHT_GRAY = 'light_grey'
    DARK_GREY = 'dark_grey'
    DARK_GRAY = 'dark_grey'
    LIGHT_RED = 'light_red'
    LIGHT_GREEN = 'light_green'
    LIGHT_YELLOW = 'light_yellow'
    LIGHT_BLUE = 'light_blue'
    LIGHT_MAGENTA = 'light_magenta'
    LIGHT_CYAN = 'light_cyan'

class HighlightColor(StrEnum):
    BLACK = 'on_black'
    RED = 'on_red'
    GREEN = 'on_green'
    YELLOW = 'on_yellow'
    BLUE = 'on_blue'
    MAGENTA = 'on_magenta'
    CYAN = 'on_cyan'
    WHITE = 'on_white'
    LIGHT_GREY = 'on_light_grey'
    LIGHT_GRAY = 'on_light_grey'
    DARK_GREY = 'on_dark_grey'
    DARK_GRAY = 'on_dark_grey'
    LIGHT_RED = 'on_light_red'
    LIGHT_GREEN = 'on_light_green'
    LIGHT_YELLOW = 'on_light_yellow'
    LIGHT_BLUE = 'on_light_blue'
    LIGHT_MAGENTA = 'on_light_magenta'
    LIGHT_CYAN = 'on_light_cyan'

class TextAttribute(StrEnum):
    BOLD = 'bold'
    DARK = 'dark'
    ITALIC = 'italic'
    UNDERLINE = 'underline'
    BLINK = 'blink'
    REVERSE = 'reverse'
    CONCEALED = 'concealed'
    STRIKE = 'strike'

def colored(
    text: str,
    textcolor: TextColor | str | None = None,
    *,
    highlight: HighlightColor | str | None = None,
    attributes: Iterable[TextAttribute | str] | None = None,
    no_color: bool | None = None,
    force_color: bool | None = None,
) -> str:
    if textcolor is not None:
        textcolor = str(textcolor)
    if highlight is not None:
        highlight = f'on_{highlight}'
    if attributes is not None:
        attributes = [ str(attr) for attr in attributes ]
    return termcolor.colored(
        text,
        color=textcolor,
        on_color=highlight,
        attrs=attributes,
        no_color=no_color,
        force_color=force_color,
    )

def cprint(
    text: str,
    *,
    color: TextColor | str | None = None,
    highlight: HighlightColor | str | None = None,
    attributes: Iterable[TextAttribute | str] | None = None,
    no_color: bool | None = None,
    force_color: bool | None = None,
    **kwargs: Any,
) -> None:
    print(
        colored(
            text,
            textcolor=color,
            highlight=highlight,
            attributes=attributes,
            no_color=no_color,
            force_color=force_color,
        ),
        **kwargs,
    )

class BorderType(IntEnum):
    # TODO: eventually switch all code to use enum
    SINGLE = auto()
    DOUBLE = auto()

def boxed(
    *olines : str,
    title : str | None = None,
    prefix : str = '',
    margin : str = '',                                          # margin around box
    pad : str = ' ',                                            # padding just inside box
    sides : BorderType | str = BorderType.SINGLE,               # single- or double-sided walls
    color : TextColor | str | None = None,                      # color of text
    highlight : HighlightColor | str | None = None,             # color of background
    attributes : Iterable[TextAttribute | str] | None = None,   # any attributes
    wrap : int = 120,
    indent : int = 4,
):
    lines = [line for oline in olines for line in oline.splitlines()]
    # https://www.w3.org/TR/xml-entity-names/025.html
    tl,tm,tr,lm,rm,bl,bm,br,lt,rt = {
        'single': '┌─┐││└─┘┤├',
        'double': '╔═╗║║╚═╝╡╞',
        BorderType.SINGLE: '┌─┐││└─┘┤├',
        BorderType.DOUBLE: '╔═╗║║╚═╝╡╞',
    }[sides]
    if title:
        title = f'{tm}{lt} {title} {rt}{tm}'
        title_width = len(title)
    else:
        title_width = 0
    pad_width = len(pad) * 2
    width = max(max(len(line) for line in lines), title_width)
    lines = [ wline for line in lines for wline in textwrap.wrap(line, wrap) ]
    # if wrap and width > wrap:
    #     width = wrap
    #     wrapped_lines = []
    #     for line in lines:
    #         cur_indent = len(line) - len(line.lstrip()) + indent
    #         first = True
    #         while True:
    #             if first: first = False
    #             else:     line = (' '*cur_indent) + line
    #             wrapped_lines.append(line[:wrap])
    #             line = line[wrap:]
    #             if not line: break
    #     lines = wrapped_lines
    if prefix: print(prefix, end='')
    if title:
        cprint(f'{margin}{tl}{title}{tm*(width+pad_width-len(title))}{tr}{margin}', color=color, highlight=highlight, attributes=attributes)
    else:
        cprint(f'{margin}{tl}{tm*(width+pad_width)}{tr}{margin}', color=color, highlight=highlight, attributes=attributes)
    if pad:
        cprint(f'{margin}{lm}{pad}{" "*width}{pad}{rm}{margin}', color=color, highlight=highlight, attributes=attributes)
    for line in lines:
        if prefix: print(prefix, end='')
        cprint(f'{margin}{lm}{pad}{line}{" "*(width - len(line))}{pad}{rm}{margin}', color=color, highlight=highlight, attributes=attributes)
    if prefix: print(prefix, end='')
    if pad:
        cprint(f'{margin}{lm}{pad}{" "*width}{pad}{rm}{margin}', color=color, highlight=highlight, attributes=attributes)
    cprint(f'{margin}{bl}{bm*(width+pad_width)}{br}{margin}', color=color, highlight=highlight, attributes=attributes)

sprint_data = {
    'width':  5,
    'index': -1,
    'time':  None,
}
def sprint(*args):
    global sprint_data
    sprint_data['index'] = (sprint_data['index']+1) % sprint_data['width']
    d = time.time() - sprint_data['time'] if sprint_data['time'] else 0
    sprint_data['time'] = time.time()
    m = ' '*sprint_data['index'] + '*' + ' '*(sprint_data['width']-sprint_data['index']-1)
    s = " ".join(f'{arg}' for arg in args)
    print(f'[{m}] {d:0.4f}s | {s}')
