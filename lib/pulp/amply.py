#! /usr/bin/env python
# Amply: a GNU MathProg data-parser

# Copyright (c) 2010, Q. Lim (qlim001@aucklanduni.ac.nz)

# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:

# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""
Amply: a GNU MathProg data-parser

This module implements a parser for a subset of the GNU MathProg language,
namely parameter and set data records.

Amply uses the Pyparsing library to parse input:
    http://pyparsing.wikispaces.com

Usage:
    Create an Amply object, optionally passing in a string to parse.

    >>> a = Amply("param T := 3;")

    Symbols that are defined can be accessed as attributes or items.

    >>> print(a.T)
    3.0
    >>> print(a['T'])
    3.0

    The load_string and load_file methods can be used to parse additional data

    >>> a.load_string("set N := 1 2 3;")
    >>> a.load_file(open('some_file.dat'))

    An Amply object can be constructed from a file using Amply.from_file

    >>> a = Amply.from_file(open('some_file.dat'))


How it works:
    The Amply class parses the input using Pyparsing. This results in a list
    of Stmt objects, each representing a MathProg statement. The statements
    are then evaluated by calling their eval() method.
"""
try:
    import pyparsing
except ImportError:
    pass
else:
    from pyparsing import alphas, nums, alphanums, delimitedList, oneOf
    from pyparsing import Combine, Dict, Forward, Group, Literal, NotAny
    from pyparsing import OneOrMore, Optional, ParseResults, QuotedString
    from pyparsing import StringEnd, Suppress, Word, ZeroOrMore

    from itertools import chain

    __all__ = ['Amply', 'AmplyError']


    class AmplyObject(object):
        """
        Represents the value of some object (e.g. a Set object
        or Parameter object
        """

    class AmplyStmt(object):
        """
        Represents a statement that has been parsed

        Statements implement an eval method. When the eval method is called, the
        Stmt object is responsible for modifying the Amply object that
        gets passed in appropriately (i.e. by adding or modifying a symbol)
        """

        def eval(self, amply): # pragma: no coverage
            raise NotImplementedError()


    class NoDefault(object):
        """
        Sentinel
        """


    class AmplyError(Exception):
        """
        Amply Exception Class
        """


    def chunk(it, n):
        """
        Yields n-tuples from iterator
        """
        c = []
        for i, x in enumerate(it):
            c.append(x)
            if (i + 1) % n == 0:
                yield tuple(c)
                c = []
        if c:
            yield tuple(c)


    def access_data(curr_dict, keys, default=NoDefault):
        """
        Convenience method for walking down a series of nested dictionaries

        keys is a tuple of strings
        
        access_data(dict, ('key1', 'key2', 'key3') is equivalent to
        dict['key1']['key2']['key3']

        All dictionaries must exist, but the last dictionary in the hierarchy
        does not have to contain the final key, if default is set.
        """

        if keys in curr_dict:
            return curr_dict[keys]

        if isinstance(keys, tuple):
            for sym in keys[:-1]:
                curr_dict = curr_dict[sym]
            r = curr_dict.get(keys[-1], default)
            if r is not NoDefault:
                return r

        if default is not NoDefault:
            return default

        raise KeyError()


    def transpose(data):
        """
        Transpose a matrix represented as a dict of dicts
        """

        rows = list(data.keys())
        cols = set()
        for d in list(data.values()):
            cols.update(list(d.keys()))

        d = {}

        for col in cols:
            d[col] = {}
            for row in rows:
                d[col][row] = data[row][col]
        return d


    class SetDefStmt(AmplyStmt):
        """
        Represents a set definition statement
        """

        def __init__(self, tokens):
            assert (tokens[0] == 'set')
            self.name = tokens[1]
            self.dimen = tokens.get('dimen', None)
            self.subscripts = len(tokens.get('subscripts', ()))

        def __repr__(self): # pragma: no cover
            return '<%s: %s[%s]>' % (self.__class__.__name__, self.name,
                    self.dimen)

        def eval(self, amply):
            set_obj = SetObject(subscripts=self.subscripts, dimen=self.dimen)
            amply._addSymbol(self.name, set_obj)


    class SetStmt(AmplyStmt):
        """
        Represents a set statement
        """

        def __init__(self, tokens):
            assert(tokens[0] == 'set')
            self.name = tokens[1]
            self.records = tokens.get('records')
            self.member = tokens.get('member', None)

        def __repr__(self):
            return '<%s: %s[%s] = %s>' % (self.__class__.__name__, self.name,
                                          self.member, self.records)

        def eval(self, amply):
            if self.name in amply.symbols:
                obj = amply.symbols[self.name]
                assert isinstance(obj, SetObject)
            else:
                obj = SetObject()

            obj.addData(self.member, self.records)
            amply._addSymbol(self.name, obj)


    class SliceRecord(object):
        """
        Represents a parameter or set slice record
        """

        def __init__(self, tokens):
            self.components = tuple(tokens)

        def __repr__(self):
            return '<%s: %s>' % (self.__class__.__name__, self.components)


    class TabularRecord(object):
        """
        Represents a parameter tabular record
        """

        def __init__(self, tokens):
            self._columns = tokens.columns
            self._data = tokens.data
            self.transposed = False

        def setTransposed(self, t):
            self.transposed = t

        def _rows(self):
            c = Chunker(self._data)
            while c.notEmpty():
                row_label = c.chunk()
                data = c.chunk(len(self._columns))
                yield row_label, data

        def data(self):
            d = {}
            for row, data in self._rows():
                d[row] = {}
                for col, value in zip(self._columns, data):
                    d[row][col] = value
            if self.transposed:
                return transpose(d)
            else:
                return d

        def __repr__(self):
            return '<%s: %s>' % (self.__class__.__name__, self.data())


    class MatrixData(TabularRecord):
        """
        Represents a set matrix data record
        """

        def _rows(self):
            for row in self._data:
                yield row[0], row[1:]

        def data(self):
            d = []
            for row_label, data in self._rows():
                for col, value in zip(self._columns, data):
                    if value == '+':
                        if self.transposed:
                            d.append((col, row_label))
                        else:
                            d.append((row_label, col))
            return d


    class ParamStmt(AmplyStmt):
        """
        Represents a parameter statement
        """

        def __init__(self, tokens):
            assert(tokens[0] == 'param')
            self.name = tokens.name
            self.records = tokens.records
            self.default = tokens.get('default', 0)

        def __repr__(self):
            return '<%s: %s = %s>' % (self.__class__.__name__, self.name,
                                      self.records)

        def eval(self, amply):
            if self.name in amply.symbols:
                obj = amply.symbols[self.name]
                assert isinstance(obj, ParamObject)
            else:
                obj = ParamObject()

            if obj.subscripts == 0:
                assert len(self.records) == 1
                assert len(self.records[0]) == 1
                amply._addSymbol(self.name, self.records[0][0])
            else:
                obj.addData(self.records.asList(), default=self.default)

                amply._addSymbol(self.name, obj)


    class Chunker(object):
        """
        Chunker class - used to consume tuples from
        an iterator
        """

        def __init__(self, it):
            """
            it is a sequence or iterator
            """

            self.it = iter(it)
            self.empty = False
            self.next = None
            self._getNext()

        def _getNext(self):
            """
            basically acts as a 1 element buffer so that
            we can detect if we've reached the end of the
            iterator
            """

            old = self.next
            try:
                self.next = next(self.it)
            except StopIteration:
                self.empty = True
            return old

        def notEmpty(self):
            """
            Test if the iterator has reached the end
            """

            return not self.empty

        def chunk(self, n=None):
            """
            Return a list with the next n elements from the iterator,
            or the next element if n is None
            """
            if n is None:
                return self._getNext()
            return [self._getNext() for i in range(n)]


    class ParamTabbingStmt(AmplyStmt):
        """
        Represents a parameter tabbing data statement
        """

        def __init__(self, tokens):
            assert(tokens[0] == 'param')

            self.default = tokens.get('default', 0)
            self.params = tokens.params
            self.data = tokens.data

        def eval(self, amply):
            for i, param_name in enumerate(self.params):
                if param_name in amply.symbols:
                    obj = amply.symbols[param_name]
                else:
                    raise AmplyError("Param %s not previously defined" %
                                     param_name)

                for subs, data in self._rows(obj.subscripts):
                    obj.setValue(subs, data[i])

        def _rows(self, n_subscripts):
            c = Chunker(self.data)
            while c.notEmpty():
                subscripts = c.chunk(n_subscripts)
                data = c.chunk(len(self.params))
                yield (subscripts, data)


    class ParamDefStmt(AmplyStmt):
        """
        Represents a parameter definition
        """

        def __init__(self, tokens):
            assert(tokens[0] == 'param')
            self.name = tokens[1]
            self.subscripts = tokens.get('subscripts')
            self.default = tokens.get('default', NoDefault)

        def eval(self, amply):

            def _getDimen(symbol):
                s = amply[symbol]
                if s is None or s.dimen is None:
                    return 1
                return s.dimen
            num_subscripts = sum(_getDimen(s) for s in self.subscripts)
            amply._addSymbol(self.name, ParamObject(num_subscripts, self.default))


    class ParamObject(AmplyObject):

        def __init__(self, subscripts=0, default=NoDefault):
            self.subscripts = subscripts
            self.default = default

            self.data = {}

            # initial slice is all *'s
            self._setSlice(SliceRecord(['*'] * self.subscripts))

        def addData(self, data, default=0):

            def _v(v):
                if v == '.':
                    return default
                return v

            for record in data:
                if isinstance(record, SliceRecord):
                    self._setSlice(record)
                elif isinstance(record, list):
                    # a plain data record
                    rec_len = len(self.free_indices) + 1
                    if len(record) % rec_len != 0:
                        raise AmplyError("Incomplete data record, expecting %d"
                                         " subscripts per value" %
                                         len(self.free_indices))
                    for c in chunk(record, len(self.free_indices) + 1):
                        self.setValue(c[:-1], _v(c[-1]))
                elif isinstance(record, TabularRecord):
                    record_data = record.data()
                    for row_symbol in record_data:
                        for col_symbol, value in list(record_data[row_symbol].items()):
                            self.setValue((row_symbol, col_symbol), _v(value))

        def _setSlice(self, slice):
            self.current_slice = list(slice.components) #copy
            self.free_indices = [i for i, v in enumerate(self.current_slice)
                                 if v == '*']

        def setValue(self, symbols, value):
            if value == '.':
                value = self.default

            assert len(symbols) == len(self.free_indices)
            symbol_path = self.current_slice
            for index, symbol in zip(self.free_indices, symbols):
                symbol_path[index] = symbol

            curr_dict = self.data
            for symbol in symbol_path[:-1]:
                if symbol not in curr_dict:
                    curr_dict[symbol] = {}
                curr_dict = curr_dict[symbol]
            curr_dict[symbol_path[-1]] = value

        def __getitem__(self, key):
            return access_data(self.data, key, self.default)

        def __repr__(self):
            return '<%s: %s>' % (self.__class__.__name__, self.data)

        def __eq__(self, other):
            return self.data == other

        def __ne__(self, other):
            return self.data != other


    class SetObject(AmplyObject):

        def __init__(self, subscripts=0, dimen=None):
            self.dimen = dimen
            self.subscripts = subscripts

            if self.subscripts == 0:
                self.data = []
            else:
                self.data = {}

            self.current_slice = None

        def addData(self, member, data):
            dest_list = self._memberList(member)

            if self.dimen is not None and self.current_slice is None:
                self._setSlice(['*'] * self.dimen)

            for record in data:
                if isinstance(record, SliceRecord):
                    self._setSlice(record.components)
                elif isinstance(record, MatrixData):
                    if self.dimen is None:
                        self.dimen = 2
                        self._setSlice(['*'] * 2)
                    d = record.data()
                    for v in d:
                        self._addValue(dest_list, v)

                else: # simple-data
                    self._addSimpleData(dest_list, record)

        def _setSlice(self, slice):
            self.current_slice = slice
            self.free_indices = [i for i, v in enumerate(self.current_slice)
                                 if v == '*']

        def _memberList(self, member):
            if member is None:
                return self.data
            assert len(member) == self.subscripts

            curr_dict = self.data
            for symbol in member[:-1]:
                if symbol not in curr_dict:
                    curr_dict[symbol] = {}
                curr_dict = curr_dict[symbol]
            if member[-1] not in curr_dict:
                curr_dict[member[-1]] = []
            return curr_dict[member[-1]]

        def _dataLen(self, d):
            if isinstance(d, (tuple, list)):
                return len(d)
            return 1

        def _addSimpleData(self, data_list, data):
            if isinstance(data[0], ParseResults):
                inferred_dimen = len(data[0])
            else:
                inferred_dimen = 1

            if self.dimen == None:
                # infer dimension from records
                self.dimen = inferred_dimen

            if self.current_slice == None:
                self._setSlice(tuple(['*'] * self.dimen))

            if len(self.free_indices) == inferred_dimen:
                for d in data.asList():
                    self._addValue(data_list, d)
            elif len(self.free_indices) > 1 and inferred_dimen:
                for c in chunk(data, len(self.free_indices)):
                    self._addValue(data_list, c)
            else:
                raise AmplyError("Dimension of elements (%d) does not match "
                                 "declared dimension, (%d)" %
                        (inferred_dimen, self.dimen))

        def _addValue(self, data_list, item):
            if self.dimen == 1:
                data_list.append(item)
            else:
                assert len(self.free_indices) == self._dataLen(item)

                to_add = list(self.current_slice)
                if isinstance(item, (tuple, list)):
                    for index, value in zip(self.free_indices, item):
                        to_add[index] = value
                else:
                    assert len(self.free_indices) == 1
                    to_add[self.free_indices[0]] = item
                data_list.append(tuple(to_add))


        def __getitem__(self, key):
            if not self.subscripts:
                return self.data[key]
            return access_data(self.data, key)

        def __len__(self):
            return len(self.data)

        def __iter__(self):
            return iter(self.data)

        def __contains__(self, item):
            return item in self.data

        def __eq__(self, other):
            return self.data == other

        def __ne__(self, other):
            return self.data != other

        def __repr__(self):
            return '<%s: %s>' % (self.__class__.__name__, self.data) 

    def mark_transposed(tokens):
        tokens[0].setTransposed(True)
        return tokens


    # What follows is a Pyparsing description of the grammar

    symbol = Word(alphas, alphanums + "_")
    sign = Optional(oneOf("+ -"))
    integer = Combine(sign + Word(nums)).setParseAction(lambda t: int(t[0]))
    number = Combine(Word( "+-"+nums, nums) +
                   Optional("." + Optional(Word(nums))) +
                   Optional(oneOf("e E") + Word("+-"+nums, nums)))\
            .setParseAction(lambda t: float(t[0]))
                   
    LPAREN = Suppress('(')
    RPAREN = Suppress(')')
    LBRACE = Suppress('{')
    RBRACE = Suppress('}')
    LBRACKET = Suppress('[')
    RBRACKET = Suppress(']')
    END = Suppress(';')

    PLUS = Literal('+')
    MINUS = Literal('-')

    single = number | symbol | QuotedString('"') | QuotedString("'")
    tuple_ = Group(LPAREN + delimitedList(single) + RPAREN)
    subscript_domain = LBRACE + Group(delimitedList(symbol)) \
            .setResultsName('subscripts') + RBRACE

    data = single | tuple_

    # should not match a single (tr)
    simple_data = Group(NotAny('(tr)') + data + ZeroOrMore(Optional(Suppress(',')) + data))
    # the first element of a set data record  cannot be 'dimen', or else
    # these would match set_def_stmts
    non_dimen_simple_data = ~Literal('dimen') + simple_data

    matrix_row = Group(single + OneOrMore(PLUS | MINUS))
    matrix_data = ":" + OneOrMore(single).setResultsName('columns') \
            + ":=" + OneOrMore(matrix_row).setResultsName('data')
    matrix_data.setParseAction(MatrixData)

    tr_matrix_data = Suppress("(tr)") + matrix_data
    tr_matrix_data.setParseAction(mark_transposed)

    set_slice_component = number | symbol | '*'
    set_slice_record = LPAREN + NotAny('tr') + delimitedList(set_slice_component) + RPAREN
    set_slice_record.setParseAction(SliceRecord)

    _set_record = set_slice_record | matrix_data | tr_matrix_data | Suppress(":=")
    set_record = simple_data | _set_record
    non_dimen_set_record = non_dimen_simple_data | _set_record

    set_def_stmt = "set" + symbol + Optional(subscript_domain) + \
            Optional("dimen" + integer.setResultsName('dimen')) + END
    set_def_stmt.setParseAction(SetDefStmt)

    set_member = LBRACKET + delimitedList(data) + RBRACKET

    set_stmt = "set" + symbol + Optional(set_member).setResultsName("member") + \
            Group(non_dimen_set_record + ZeroOrMore(Optional(Suppress(',')) + set_record)) \
            .setResultsName("records") + END
    set_stmt.setParseAction(SetStmt)

    subscript = single

    param_data = data | '.'
    plain_data = param_data | subscript + ZeroOrMore(Optional(Suppress(',')) +
                                               subscript) + param_data
    # should not match a single (tr)
    plain_data_record = Group(NotAny('(tr)') + plain_data + NotAny(plain_data) | \
            plain_data + OneOrMore(plain_data) + NotAny(plain_data))

    tabular_record = ":" + OneOrMore(single).setResultsName("columns") \
            + ":=" + OneOrMore(single | '.').setResultsName('data')
    tabular_record.setParseAction(TabularRecord)

    tr_tabular_record = Suppress("(tr)") + tabular_record
    tr_tabular_record.setParseAction(mark_transposed)

    param_slice_component = number | symbol | '*'
    param_slice_record = LBRACKET + delimitedList(param_slice_component) + RBRACKET
    param_slice_record.setParseAction(SliceRecord)

    param_record = param_slice_record | plain_data_record | tabular_record | \
            tr_tabular_record | Suppress(":=")

    param_default = Optional("default" + data.setResultsName('default'))

    param_stmt = "param" + symbol.setResultsName('name') + param_default + \
            Group(OneOrMore(param_record)).setResultsName('records') + END
    param_stmt.setParseAction(ParamStmt)

    param_tabbing_stmt = "param" + param_default + ':' + Optional(symbol + ':') + \
            OneOrMore(data).setResultsName('params') \
            + ':=' + OneOrMore(single).setResultsName('data') + END
    param_tabbing_stmt.setParseAction(ParamTabbingStmt)

    param_def_stmt = "param" + symbol + Optional(subscript_domain) + \
            param_default + END
    param_def_stmt.setParseAction(ParamDefStmt)

    stmts = set_stmt | set_def_stmt | param_stmt | param_def_stmt | \
            param_tabbing_stmt
    grammar = ZeroOrMore(stmts) + StringEnd()


    class Amply(object):
        """
        Data parsing interface
        """

        def __init__(self, s=""):
            """
            Create an Amply parser instance

            @param s (default ""): initial string to parse
            """

            self.symbols = {}

            self.load_string(s)

        def __getitem__(self, key):
            """
            Override so that symbols can be accessed using
            [] subscripts
            """
            if key in self.symbols:
                return self.symbols[key]

        def __getattr__(self, name):
            """
            Override so that symbols can be accesed as attributes
            """
            if name in self.symbols:
                return self.symbols[name]
            return super(Amply, self).__getattr__(name)

        def _addSymbol(self, name, value):
            """
            Adds a symbol to this instance.

            Typically, this class is called by objects created by
            the parser, and should not need to be called by users
            directly
            """

            self.symbols[name] = value

        def load_string(self, string):
            """
            Load and parse string

            @param string string to parse
            """
            for obj in grammar.parseString(string):
                obj.eval(self)

        def load_file(self, f):
            """
            Load and parse file

            @param f file-like object
            """
            self.load_string(f.read())

        @staticmethod
        def from_file(f):
            """
            Create a new Amply instance from file (factory method)

            @param f file-like object
            """
            return Amply(f.read())

