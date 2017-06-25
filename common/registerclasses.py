'''
Copyright (C) 2017 Taylor University, CG Cookie

Created by Dr. Jon Denning and Spring 2015 COS 424 class

Some code copied from CG Cookie Retopoflow project
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


from abc import ABCMeta, abstractmethod

'''
RegisterRFClasses handles self registering classes to simplify creating new tools, cursors, etc.
With self registration, the new entities only need to by imported in, and they automatically
show up as an available entity.
'''

# from http://python-3-patterns-idioms-test.readthedocs.io/en/latest/Metaprogramming.html#example-self-registration-of-subclasses
class RegisterClasses(type, metaclass=ABCMeta):
    def __init__(cls, name, bases, nmspc):
        super(RegisterClasses, cls).__init__(name, bases, nmspc)
        if not hasattr(cls, 'registry'): cls.registry = set()
        cls.registry.add(cls)
        cls.registry -= set(bases) # Remove base classes
    # Metamethods, called on class objects:
    def __iter__(cls):
        return iter(cls.registry)
    def __str__(cls):
        if cls in cls.registry: return cls.__name__
        return cls.__name__ + ": " + ", ".join([sc.__name__ for sc in cls])
