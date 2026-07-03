'''
Copyright (C) 2026 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

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

from typing import Generic, TypeVar
from collections.abc import Iterable, Iterator

T = TypeVar('T')

class UnionFind(Generic[T]):
    """
    Weighted Quick-Union implementation of dynamic connectivity data structure.
    """

    _things : list[T]
    _parents : dict[T, T | None]
    _sizes : dict[T, int]

    def __iter__(self) -> Iterator[T]:
        return iter(self._things)

    def __init__(self, things : Iterable[T]):
        self._things  = list(things)
        self._parents = { thing: None for thing in self }
        self._sizes   = { thing: 1 for thing in self }

    def roots(self) -> Iterable[T]:
        yield from (
            t
            for (t,p) in self._parents.items()
            if not p
        )

    def root(self, thing : T) -> T:
        return self.root(parent) if (parent := self._parents[thing]) else thing

    def is_connected(self, t0 : T, t1 : T) -> bool:
        return self.root(t0) == self.root(t1)

    def connect(self, t0 : T, t1 : T):
        r0, r1 = self.root(t0), self.root(t1)
        if r0 == r1:
            return
        if self._sizes[r0] < self._sizes[r1]:
            r0, r1 = r1, r0
        self._parents[r1] = r0
        self._sizes[r0] += self._sizes[r1]
