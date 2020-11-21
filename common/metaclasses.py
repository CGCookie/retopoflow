'''
Copyright (C) 2020 Taylor University, CG Cookie

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


class SingletonClass(type):
    '''
    from https://stackoverflow.com/questions/6760685/creating-a-singleton-in-python
    '''  # noqa

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            supercls = super(SingletonClass, cls)
            cls._instances[cls] = supercls.__call__(*args, *kwargs)
        return cls._instances[cls]

    # def __getattr__(cls, name):
    #    return cls._instances[cls].__getattr__(name)


class RegisterClass(type):
    '''
    # from http://python-3-patterns-idioms-test.readthedocs.io/en/latest/Metaprogramming.html#example-self-registration-of-subclasses
    '''  # noqa

    def __init__(cls, name, bases, nmspc):
        super(RegisterClass, cls).__init__(name, bases, nmspc)
        if not hasattr(cls, 'registry'):
            cls.registry = set()
        cls.registry.add(cls)
        cls.registry -= set(bases)  # Remove base classes

    # Metamethods, called on class objects:
    def __iter__(cls):
        return iter(cls.registry)

    def __str__(cls):
        if cls in cls.registry:
            return cls.__name__
        return cls.__name__ + ": " + ", ".join([sc.__name__ for sc in cls])

    def __len__(cls):
        return len(cls.registry)


class SingletonRegisterClass(SingletonClass, RegisterClass):
    pass
