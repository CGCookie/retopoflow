from __future__ import annotations
from typing import Any, Iterable
from contextlib import contextmanager
from ..ext import termcolor

def colored(
    text: str,
    color: str | None = None,
    *,
    highlight: str | None = None,
    attributes: Iterable[str] | None = None,
    no_color: bool | None = None,
    force_color: bool | None = None,
) -> str:
    return termcolor.colored(
        text,
        color=color,
        on_color=f'on_{highlight}' if highlight else None,
        attrs=attributes,
        no_color=no_color,
        force_color=force_color,
    )

def cprint(
    text: str,
    *,
    color: str | None = None,
    highlight: str | None = None,
    attributes: Iterable[str] | None = None,
    no_color: bool | None = None,
    force_color: bool | None = None,
    **kwargs: Any,
) -> None:
    print(
        colored(
            text,
            color=color,
            highlight=highlight,
            attributes=attributes,
            no_color=no_color,
            force_color=force_color,
        ),
        **kwargs,
    )

def boxed(*lines, prefix='', margin='', pad=' ', sides='single', color=None, highlight=None, attributes=None):
    # https://www.w3.org/TR/xml-entity-names/025.html
    tl,tm,tr,lm,rm,bl,bm,br = {
        'single': '┌─┐││└─┘',
        'double': '╔═╗║║╚═╝',
    }[sides]
    pad_width = len(pad) * 2
    width = max(len(line) for line in lines)
    if prefix: print(prefix, end='')
    cprint(f'{margin}{tl}{tm*(width+pad_width)}{tr}{margin}', color=color, highlight=highlight, attributes=attributes)
    for line in lines:
        if prefix: print(prefix, end='')
        cprint(f'{margin}{lm}{pad}{line}{" "*(width - len(line))}{pad}{rm}{margin}', color=color, highlight=highlight, attributes=attributes)
    if prefix: print(prefix, end='')
    cprint(f'{margin}{bl}{bm*(width+pad_width)}{br}{margin}', color=color, highlight=highlight, attributes=attributes)

