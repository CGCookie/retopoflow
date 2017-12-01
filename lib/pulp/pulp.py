#! /usr/bin/env python
# PuLP : Python LP Modeler


# Copyright (c) 2002-2005, Jean-Sebastien Roy (js@jeannot.org)
# Modifications Copyright (c) 2007- Stuart Anthony Mitchell (s.mitchell@auckland.ac.nz)
# $Id: pulp.py 1791 2008-04-23 22:54:34Z smit023 $

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
PuLP is an LP modeler written in python. PuLP can generate MPS or LP files
and call GLPK[1], COIN CLP/CBC[2], CPLEX[3], and GUROBI[4] to solve linear
problems.

See the examples directory for examples.

PuLP requires Python >= 2.5.

The examples require at least a solver in your PATH or a shared library file.

Documentation is found on https://www.coin-or.org/PuLP/.
A comprehensive wiki can be found at https://www.coin-or.org/PuLP/

Use LpVariable() to create new variables. To create a variable 0 <= x <= 3
>>> x = LpVariable("x", 0, 3)

To create a variable 0 <= y <= 1
>>> y = LpVariable("y", 0, 1)

Use LpProblem() to create new problems. Create "myProblem"
>>> prob = LpProblem("myProblem", LpMinimize)

Combine variables to create expressions and constraints and add them to the
problem.
>>> prob += x + y <= 2

If you add an expression (not a constraint), it will
become the objective.
>>> prob += -4*x + y

Choose a solver and solve the problem. ex:
>>> status = prob.solve(GLPK(msg = 0))

Display the status of the solution
>>> LpStatus[status]
'Optimal'

You can get the value of the variables using value(). ex:
>>> value(x)
2.0

Exported Classes:
    - LpProblem -- Container class for a Linear programming problem
    - LpVariable -- Variables that are added to constraints in the LP
    - LpConstraint -- A constraint of the general form
      a1x1+a2x2 ...anxn (<=, =, >=) b
    - LpConstraintVar -- Used to construct a column of the model in column-wise
      modelling

Exported Functions:
    - value() -- Finds the value of a variable or expression
    - lpSum() -- given a list of the form [a1*x1, a2x2, ..., anxn] will construct
      a linear expression to be used as a constraint or variable
    - lpDot() --given two lists of the form [a1, a2, ..., an] and
      [ x1, x2, ..., xn] will construct a linear epression to be used
      as a constraint or variable

Comments, bug reports, patches and suggestions are welcome.
pulp-or-discuss@googlegroups.com

References:
[1] http://www.gnu.org/software/glpk/glpk.html
[2] http://www.coin-or.org/
[3] http://www.cplex.com/
[4] http://www.gurobi.com/
"""

import types
import string
import itertools

from .constants import *
from .solvers import *
from collections import Iterable

import logging
log = logging.getLogger(__name__)

try:  # allow Python 2/3 compatibility
    maketrans = str.maketrans
except AttributeError:
    from string import maketrans

_DICT_TYPE = dict

if sys.platform not in ['cli']:
    # iron python does not like an OrderedDict
    try:
        from odict import OrderedDict
        _DICT_TYPE = OrderedDict
    except ImportError:
        pass
    try:
        #python 2.7 or 3.1
        from collections import OrderedDict
        _DICT_TYPE = OrderedDict
    except ImportError:
        pass


def setConfigInformation(**keywords):
    """
    set the data in the configuration file
    at the moment will only edit things in [locations]
    the keyword value pairs come from the keywords dictionary
    """
    #TODO: extend if we ever add another section in the config file
    #read the old configuration
    config = ConfigParser.SafeConfigParser()
    config.read(config_filename)
    #set the new keys
    for (key,val) in keywords.items():
        config.set("locations",key,val)
    #write the new configuration
    fp = open(config_filename,"w")
    config.write(fp)
    fp.close()


# Default solver selection
if PULP_CBC_CMD().available():
    LpSolverDefault = PULP_CBC_CMD()
elif GLPK_CMD().available():
    LpSolverDefault = GLPK_CMD()
elif COIN_CMD().available():
    LpSolverDefault = COIN_CMD()
else:
    LpSolverDefault = None

class LpElement(object):
    """Base class for LpVariable and LpConstraintVar
    """
    #to remove illegal characters from the names
    trans = maketrans("-+[] ->/","________")
    def setName(self,name):
        if name:
            self.__name = str(name).translate(self.trans)
        else:
            self.__name = None
    def getName(self):
        return self.__name
    name = property(fget = getName,fset = setName)

    def __init__(self, name):
        self.name = name
         # self.hash MUST be different for each variable
        # else dict() will call the comparison operators that are overloaded
        self.hash = id(self)
        self.modified = True

    def __hash__(self):
        return self.hash

    def __str__(self):
        return self.name
    def __repr__(self):
        return self.name

    def __neg__(self):
        return - LpAffineExpression(self)

    def __pos__(self):
        return self

    def __bool__(self):
        return 1

    def __add__(self, other):
        return LpAffineExpression(self) + other

    def __radd__(self, other):
        return LpAffineExpression(self) + other

    def __sub__(self, other):
        return LpAffineExpression(self) - other

    def __rsub__(self, other):
        return other - LpAffineExpression(self)

    def __mul__(self, other):
        return LpAffineExpression(self) * other

    def __rmul__(self, other):
        return LpAffineExpression(self) * other

    def __div__(self, other):
        return LpAffineExpression(self)/other

    def __rdiv__(self, other):
        raise TypeError("Expressions cannot be divided by a variable")

    def __le__(self, other):
        return LpAffineExpression(self) <= other

    def __ge__(self, other):
        return LpAffineExpression(self) >= other

    def __eq__(self, other):
        return LpAffineExpression(self) == other

    def __ne__(self, other):
        if isinstance(other, LpVariable):
            return self.name is not other.name
        elif isinstance(other, LpAffineExpression):
            if other.isAtomic():
                return self is not other.atom()
            else:
                return 1
        else:
            return 1


class LpVariable(LpElement):
    """
    This class models an LP Variable with the specified associated parameters

    :param name: The name of the variable used in the output .lp file
    :param lowbound: The lower bound on this variable's range.
        Default is negative infinity
    :param upBound: The upper bound on this variable's range.
        Default is positive infinity
    :param cat: The category this variable is in, Integer, Binary or
        Continuous(default)
    :param e: Used for column based modelling: relates to the variable's
        existence in the objective function and constraints
    """
    def __init__(self, name, lowBound = None, upBound = None,
                  cat = LpContinuous, e = None):
        LpElement.__init__(self,name)
        self.lowBound = lowBound
        self.upBound = upBound
        self.cat = cat
        self.varValue = None
        self.dj = None
        self.init = 0
        #code to add a variable to constraints for column based
        # modelling
        if cat == LpBinary:
            self.lowBound = 0
            self.upBound = 1
            self.cat = LpInteger
        if e:
            self.add_expression(e)

    def add_expression(self,e):
        self.expression = e
        self.addVariableToConstraints(e)

    def matrix(self, name, indexs, lowBound = None, upBound = None, cat = LpContinuous,
            indexStart = []):
        if not isinstance(indexs, tuple): indexs = (indexs,)
        if "%" not in name: name += "_%s" * len(indexs)

        index = indexs[0]
        indexs = indexs[1:]
        if len(indexs) == 0:
            return [LpVariable(name % tuple(indexStart + [i]),
                                            lowBound, upBound, cat)
                        for i in index]
        else:
            return [LpVariable.matrix(name, indexs, lowBound,
                                        upBound, cat, indexStart + [i])
                       for i in index]
    matrix = classmethod(matrix)

    def dicts(self, name, indexs, lowBound = None, upBound = None, cat = LpContinuous,
        indexStart = []):
        """
        Creates a dictionary of LP variables

        This function creates a dictionary of LP Variables with the specified
            associated parameters.

        :param name: The prefix to the name of each LP variable created
        :param indexs: A list of strings of the keys to the dictionary of LP
            variables, and the main part of the variable name itself
        :param lowbound: The lower bound on these variables' range. Default is
            negative infinity
        :param upBound: The upper bound on these variables' range. Default is
            positive infinity
        :param cat: The category these variables are in, Integer or
            Continuous(default)

        :return: A dictionary of LP Variables
        """
        if not isinstance(indexs, tuple): indexs = (indexs,)
        if "%" not in name: name += "_%s" * len(indexs)

        index = indexs[0]
        indexs = indexs[1:]
        d = {}
        if len(indexs) == 0:
            for i in index:
                d[i] = LpVariable(name % tuple(indexStart + [str(i)]), lowBound, upBound, cat)
        else:
            for i in index:
                d[i] = LpVariable.dicts(name, indexs, lowBound, upBound, cat, indexStart + [i])
        return d
    dicts = classmethod(dicts)

    def dict(self, name, indexs, lowBound = None, upBound = None, cat = LpContinuous):
        if not isinstance(indexs, tuple): indexs = (indexs,)
        if "%" not in name: name += "_%s" * len(indexs)

        lists = indexs

        if len(indexs)>1:
            # Cartesian product
            res = []
            while len(lists):
                first = lists[-1]
                nres = []
                if res:
                    if first:
                        for f in first:
                            nres.extend([[f]+r for r in res])
                    else:
                        nres = res
                    res = nres
                else:
                    res = [[f] for f in first]
                lists = lists[:-1]
            index = [tuple(r) for r in res]
        elif len(indexs) == 1:
            index = indexs[0]
        else:
            return {}

        d = {}
        for i in index:
         d[i] = self(name % i, lowBound, upBound, cat)
        return d
    dict = classmethod(dict)

    def getLb(self):
        return self.lowBound

    def getUb(self):
        return self.upBound

    def bounds(self, low, up):
        self.lowBound = low
        self.upBound = up
        self.modified = True

    def positive(self):
        self.bounds(0, None)

    def value(self):
        return self.varValue

    def round(self, epsInt = 1e-5, eps = 1e-7):
        if self.varValue is not None:
            if self.upBound != None and self.varValue > self.upBound and self.varValue <= self.upBound + eps:
                self.varValue = self.upBound
            elif self.lowBound != None and self.varValue < self.lowBound and self.varValue >= self.lowBound - eps:
                self.varValue = self.lowBound
            if self.cat == LpInteger and abs(round(self.varValue) - self.varValue) <= epsInt:
                self.varValue = round(self.varValue)

    def roundedValue(self, eps = 1e-5):
        if self.cat == LpInteger and self.varValue != None \
            and abs(self.varValue - round(self.varValue)) <= eps:
            return round(self.varValue)
        else:
            return self.varValue

    def valueOrDefault(self):
        if self.varValue != None:
            return self.varValue
        elif self.lowBound != None:
            if self.upBound != None:
                if 0 >= self.lowBound and 0 <= self.upBound:
                    return 0
                else:
                    if self.lowBound >= 0:
                        return self.lowBound
                    else:
                        return self.upBound
            else:
                if 0 >= self.lowBound:
                    return 0
                else:
                    return self.lowBound
        elif self.upBound != None:
            if 0 <= self.upBound:
                return 0
            else:
                return self.upBound
        else:
            return 0

    def valid(self, eps):
        if self.varValue == None: return False
        if self.upBound != None and self.varValue > self.upBound + eps:
            return False
        if self.lowBound != None and self.varValue < self.lowBound - eps:
            return False
        if self.cat == LpInteger and abs(round(self.varValue) - self.varValue) > eps:
            return False
        return True

    def infeasibilityGap(self, mip = 1):
        if self.varValue == None: raise ValueError("variable value is None")
        if self.upBound != None and self.varValue > self.upBound:
            return self.varValue - self.upBound
        if self.lowBound != None and self.varValue < self.lowBound:
            return self.varValue - self.lowBound
        if mip and self.cat == LpInteger and round(self.varValue) - self.varValue != 0:
            return round(self.varValue) - self.varValue
        return 0

    def isBinary(self):
        return self.cat == LpInteger and self.lowBound == 0 and self.upBound == 1

    def isInteger(self):
        return self.cat == LpInteger

    def isFree(self):
        return self.lowBound == None and self.upBound == None

    def isConstant(self):
        return self.lowBound != None and self.upBound == self.lowBound

    def isPositive(self):
        return self.lowBound == 0 and self.upBound == None

    def asCplexLpVariable(self):
        if self.isFree(): return self.name + " free"
        if self.isConstant(): return self.name + " = %.12g" % self.lowBound
        if self.lowBound == None:
            s= "-inf <= "
        # Note: XPRESS and CPLEX do not interpret integer variables without
        # explicit bounds
        elif (self.lowBound == 0 and self.cat == LpContinuous):
            s = ""
        else:
            s= "%.12g <= " % self.lowBound
        s += self.name
        if self.upBound != None:
            s+= " <= %.12g" % self.upBound
        return s

    def asCplexLpAffineExpression(self, name, constant = 1):
        return LpAffineExpression(self).asCplexLpAffineExpression(name, constant)

    def __ne__(self, other):
        if isinstance(other, LpElement):
            return self.name is not other.name
        elif isinstance(other, LpAffineExpression):
            if other.isAtomic():
                return self is not other.atom()
            else:
                return 1
        else:
            return 1

    def addVariableToConstraints(self,e):
        """adds a variable to the constraints indicated by
        the LpConstraintVars in e
        """
        for constraint, coeff in e.items():
            constraint.addVariable(self,coeff)

    def setInitialValue(self,val):
        """sets the initial value of the Variable to val
        may of may not be supported by the solver
        """
        raise NotImplementedError


class LpAffineExpression(_DICT_TYPE):
    """
    A linear combination of :class:`LpVariables<LpVariable>`.
    Can be initialised with the following:

    #.   e = None: an empty Expression
    #.   e = dict: gives an expression with the values being the coefficients of the keys (order of terms is undetermined)
    #.   e = list or generator of 2-tuples: equivalent to dict.items()
    #.   e = LpElement: an expression of length 1 with the coefficient 1
    #.   e = other: the constant is initialised as e

    Examples:

       >>> f=LpAffineExpression(LpElement('x'))
       >>> f
       1*x + 0
       >>> x_name = ['x_0', 'x_1', 'x_2']
       >>> x = [LpVariable(x_name[i], lowBound = 0, upBound = 10) for i in range(3) ]
       >>> c = LpAffineExpression([ (x[0],1), (x[1],-3), (x[2],4)])
       >>> c
       1*x_0 + -3*x_1 + 4*x_2 + 0
    """
    #to remove illegal characters from the names
    trans = maketrans("-+[] ","_____")
    def setName(self,name):
        if name:
            self.__name = str(name).translate(self.trans)
        else:
            self.__name = None

    def getName(self):
        return self.__name

    name = property(fget=getName, fset=setName)

    def __init__(self, e = None, constant = 0, name = None):
        self.name = name
        #TODO remove isinstance usage
        if e is None:
            e = {}
        if isinstance(e, LpAffineExpression):
            # Will not copy the name
            self.constant = e.constant
            super(LpAffineExpression, self).__init__(list(e.items()))
        elif isinstance(e, dict):
            self.constant = constant
            super(LpAffineExpression, self).__init__(list(e.items()))
        elif isinstance(e, Iterable):
            self.constant = constant
            super(LpAffineExpression, self).__init__(e)
        elif isinstance(e,LpElement):
            self.constant = 0
            super(LpAffineExpression, self).__init__( [(e, 1)])
        else:
            self.constant = e
            super(LpAffineExpression, self).__init__()

    # Proxy functions for variables

    def isAtomic(self):
        return len(self) == 1 and self.constant == 0 and list(self.values())[0] == 1

    def isNumericalConstant(self):
        return len(self) == 0

    def atom(self):
        return list(self.keys())[0]

    # Functions on expressions

    def __bool__(self):
        return (float(self.constant) != 0.0) or (len(self) > 0)

    def value(self):
        s = self.constant
        for v,x in self.items():
            if v.varValue is None:
                return None
            s += v.varValue * x
        return s

    def valueOrDefault(self):
        s = self.constant
        for v,x in self.items():
            s += v.valueOrDefault() * x
        return s

    def addterm(self, key, value):
            y = self.get(key, 0)
            if y:
                y += value
                self[key] = y
            else:
                self[key] = value

    def emptyCopy(self):
        return LpAffineExpression()

    def copy(self):
        """Make a copy of self except the name which is reset"""
        # Will not copy the name
        return LpAffineExpression(self)

    def __str__(self, constant = 1):
        s = ""
        for v in self.sorted_keys():
            val = self[v]
            if val<0:
                if s != "": s += " - "
                else: s += "-"
                val = -val
            elif s != "": s += " + "
            if val == 1: s += str(v)
            else: s += str(val) + "*" + str(v)
        if constant:
            if s == "":
                s = str(self.constant)
            else:
                if self.constant < 0: s += " - " + str(-self.constant)
                elif self.constant > 0: s += " + " + str(self.constant)
        elif s == "":
            s = "0"
        return s

    def sorted_keys(self):
        """
        returns the list of keys sorted by name
        """
        result = [(v.name, v) for v in self.keys()]
        result.sort()
        result = [v for _, v in result]
        return result

    def __repr__(self):
        l = [str(self[v]) + "*" + str(v)
                        for v in self.sorted_keys()]
        l.append(str(self.constant))
        s = " + ".join(l)
        return s

    @staticmethod
    def _count_characters(line):
        #counts the characters in a list of strings
        return sum(len(t) for t in line)

    def asCplexVariablesOnly(self, name):
        """
        helper for asCplexLpAffineExpression
        """
        result = []
        line = ["%s:" % name]
        notFirst = 0
        variables = self.sorted_keys()
        for v in variables:
            val = self[v]
            if val < 0:
                sign = " -"
                val = -val
            elif notFirst:
                sign = " +"
            else:
                sign = ""
            notFirst = 1
            if val == 1:
                term = "%s %s" %(sign, v.name)
            else:
                term = "%s %.12g %s" % (sign, val, v.name)

            if self._count_characters(line) + len(term) > LpCplexLPLineSize:
                result += ["".join(line)]
                line = [term]
            else:
                line += [term]
        return result, line

    def asCplexLpAffineExpression(self, name, constant = 1):
        """
        returns a string that represents the Affine Expression in lp format
        """
        #refactored to use a list for speed in iron python
        result, line = self.asCplexVariablesOnly(name)
        if not self:
            term = " %s" % self.constant
        else:
            term = ""
            if constant:
                if self.constant < 0:
                    term = " - %s" % (-self.constant)
                elif self.constant > 0:
                    term = " + %s" % self.constant
        if self._count_characters(line) + len(term) > LpCplexLPLineSize:
            result += ["".join(line)]
            line = [term]
        else:
            line += [term]
        result += ["".join(line)]
        result = "%s\n" % "\n".join(result)
        return result

    def addInPlace(self, other):
        if other is 0: return self
        if other is None: return self
        if isinstance(other,LpElement):
            self.addterm(other, 1)
        elif isinstance(other,LpAffineExpression):
            self.constant += other.constant
            for v,x in other.items():
                self.addterm(v, x)
        elif isinstance(other,dict):
            for e in other.values():
                self.addInPlace(e)
        elif (isinstance(other,list)
              or isinstance(other, Iterable)):
           for e in other:
                self.addInPlace(e)
        else:
            self.constant += other
        return self

    def subInPlace(self, other):
        if other is 0: return self
        if other is None: return self
        if isinstance(other,LpElement):
            self.addterm(other, -1)
        elif isinstance(other,LpAffineExpression):
            self.constant -= other.constant
            for v,x in other.items():
                self.addterm(v, -x)
        elif isinstance(other,dict):
            for e in other.values():
                self.subInPlace(e)
        elif (isinstance(other,list)
              or isinstance(other, Iterable)):
            for e in other:
                self.subInPlace(e)
        else:
            self.constant -= other
        return self

    def __neg__(self):
        e = self.emptyCopy()
        e.constant = - self.constant
        for v,x in self.items():
            e[v] = - x
        return e

    def __pos__(self):
        return self

    def __add__(self, other):
        return self.copy().addInPlace(other)

    def __radd__(self, other):
        return self.copy().addInPlace(other)

    def __iadd__(self, other):
        return self.addInPlace(other)

    def __sub__(self, other):
        return self.copy().subInPlace(other)

    def __rsub__(self, other):
        return (-self).addInPlace(other)

    def __isub__(self, other):
        return (self).subInPlace(other)


    def __mul__(self, other):
        e = self.emptyCopy()
        if isinstance(other,LpAffineExpression):
            e.constant = self.constant * other.constant
            if len(other):
                if len(self):
                    raise TypeError("Non-constant expressions cannot be multiplied")
                else:
                    c = self.constant
                    if c != 0:
                        for v,x in other.items():
                            e[v] = c * x
            else:
                c = other.constant
                if c != 0:
                    for v,x in self.items():
                        e[v] = c * x
        elif isinstance(other,LpVariable):
            return self * LpAffineExpression(other)
        else:
            if other != 0:
                e.constant = self.constant * other
                for v,x in self.items():
                    e[v] = other * x
        return e

    def __rmul__(self, other):
        return self * other

    def __div__(self, other):
        if isinstance(other,LpAffineExpression) or isinstance(other,LpVariable):
            if len(other):
                raise TypeError("Expressions cannot be divided by a non-constant expression")
            other = other.constant
        e = self.emptyCopy()
        e.constant = self.constant / other
        for v,x in self.items():
            e[v] = x / other
        return e

    def __truediv__(self, other):
        if isinstance(other,LpAffineExpression) or isinstance(other,LpVariable):
            if len(other):
                raise TypeError("Expressions cannot be divided by a non-constant expression")
            other = other.constant
        e = self.emptyCopy()
        e.constant = self.constant / other
        for v,x in self.items():
            e[v] = x / other
        return e

    def __rdiv__(self, other):
        e = self.emptyCopy()
        if len(self):
            raise TypeError("Expressions cannot be divided by a non-constant expression")
        c = self.constant
        if isinstance(other,LpAffineExpression):
            e.constant = other.constant / c
            for v,x in other.items():
                e[v] = x / c
        else:
            e.constant = other / c
        return e

    def __le__(self, other):
        return LpConstraint(self - other, LpConstraintLE)

    def __ge__(self, other):
        return LpConstraint(self - other, LpConstraintGE)

    def __eq__(self, other):
        return LpConstraint(self - other, LpConstraintEQ)

class LpConstraint(LpAffineExpression):
    """An LP constraint"""
    def __init__(self, e = None, sense = LpConstraintEQ,
                  name = None, rhs = None):
        """
        :param e: an instance of :class:`LpAffineExpression`
        :param sense: one of :data:`~pulp.constants.LpConstraintEQ`, :data:`~pulp.constants.LpConstraintGE`, :data:`~pulp.constants.LpConstraintLE` (0, 1, -1 respectively)
        :param name: identifying string
        :param rhs: numerical value of constraint target
        """
        LpAffineExpression.__init__(self, e, name = name)
        if rhs is not None:
            self.constant = - rhs
        self.sense = sense
        self.pi = None
        self.slack = None
        self.modified = True

    def getLb(self):
        if ( (self.sense == LpConstraintGE) or
             (self.sense == LpConstraintEQ) ):
            return -self.constant
        else:
            return None

    def getUb(self):
        if ( (self.sense == LpConstraintLE) or
             (self.sense == LpConstraintEQ) ):
            return -self.constant
        else:
            return None

    def __str__(self):
        s = LpAffineExpression.__str__(self, 0)
        if self.sense is not None:
            s += " " + LpConstraintSenses[self.sense] + " " + str(-self.constant)
        return s

    def asCplexLpConstraint(self, name):
        """
        Returns a constraint as a string
        """
        result, line = self.asCplexVariablesOnly(name)
        if not list(self.keys()):
            line += ["0"]
        c = -self.constant
        if c == 0:
            c = 0 # Supress sign
        term = " %s %.12g" % (LpConstraintSenses[self.sense], c)
        if self._count_characters(line)+len(term) > LpCplexLPLineSize:
            result += ["".join(line)]
            line = [term]
        else:
            line += [term]
        result += ["".join(line)]
        result = "%s\n" % "\n".join(result)
        return result

    def changeRHS(self, RHS):
        """
        alters the RHS of a constraint so that it can be modified in a resolve
        """
        self.constant = -RHS
        self.modified = True

    def __repr__(self):
        s = LpAffineExpression.__repr__(self)
        if self.sense is not None:
            s += " " + LpConstraintSenses[self.sense] + " 0"
        return s

    def copy(self):
        """Make a copy of self"""
        return LpConstraint(self, self.sense)

    def emptyCopy(self):
        return LpConstraint(sense = self.sense)

    def addInPlace(self, other):
        if isinstance(other,LpConstraint):
            if self.sense * other.sense >= 0:
                LpAffineExpression.addInPlace(self, other)
                self.sense |= other.sense
            else:
                LpAffineExpression.subInPlace(self, other)
                self.sense |= - other.sense
        elif isinstance(other,list):
            for e in other:
                self.addInPlace(e)
        else:
            LpAffineExpression.addInPlace(self, other)
            #raise TypeError, "Constraints and Expressions cannot be added"
        return self

    def subInPlace(self, other):
        if isinstance(other,LpConstraint):
            if self.sense * other.sense <= 0:
                LpAffineExpression.subInPlace(self, other)
                self.sense |= - other.sense
            else:
                LpAffineExpression.addInPlace(self, other)
                self.sense |= other.sense
        elif isinstance(other,list):
            for e in other:
                self.subInPlace(e)
        else:
            LpAffineExpression.subInPlace(self, other)
            #raise TypeError, "Constraints and Expressions cannot be added"
        return self

    def __neg__(self):
        c = LpAffineExpression.__neg__(self)
        c.sense = - c.sense
        return c

    def __add__(self, other):
        return self.copy().addInPlace(other)

    def __radd__(self, other):
        return self.copy().addInPlace(other)

    def __sub__(self, other):
        return self.copy().subInPlace(other)

    def __rsub__(self, other):
        return (-self).addInPlace(other)

    def __mul__(self, other):
        if isinstance(other,LpConstraint):
            c = LpAffineExpression.__mul__(self, other)
            if c.sense == 0:
                c.sense = other.sense
            elif other.sense != 0:
                c.sense *= other.sense
            return c
        else:
            return LpAffineExpression.__mul__(self, other)

    def __rmul__(self, other):
        return self * other

    def __div__(self, other):
        if isinstance(other,LpConstraint):
            c = LpAffineExpression.__div__(self, other)
            if c.sense == 0:
                c.sense = other.sense
            elif other.sense != 0:
                c.sense *= other.sense
            return c
        else:
            return LpAffineExpression.__mul__(self, other)

    def __rdiv__(self, other):
        if isinstance(other,LpConstraint):
            c = LpAffineExpression.__rdiv__(self, other)
            if c.sense == 0:
                c.sense = other.sense
            elif other.sense != 0:
                c.sense *= other.sense
            return c
        else:
            return LpAffineExpression.__mul__(self, other)

    def valid(self, eps = 0):
        val = self.value()
        if self.sense == LpConstraintEQ: return abs(val) <= eps
        else: return val * self.sense >= - eps

    def makeElasticSubProblem(self, *args, **kwargs):
        """
        Builds an elastic subproblem by adding variables to a hard constraint

        uses FixedElasticSubProblem
        """
        return FixedElasticSubProblem(self, *args, **kwargs)

class LpFractionConstraint(LpConstraint):
    """
    Creates a constraint that enforces a fraction requirement a/b = c
    """
    def __init__(self, numerator, denominator = None, sense = LpConstraintEQ,
                 RHS = 1.0, name = None,
                 complement = None):
        """
        creates a fraction Constraint to model constraints of
        the nature
        numerator/denominator {==, >=, <=} RHS
        numerator/(numerator + complement) {==, >=, <=} RHS

        :param numerator: the top of the fraction
        :param denominator: as described above
        :param sense: the sense of the relation of the constraint
        :param RHS: the target fraction value
        :param complement: as described above
        """
        self.numerator = numerator
        if denominator is None and complement is not None:
            self.complement = complement
            self.denominator = numerator + complement
        elif denominator is not None and complement is None:
            self.denominator = denominator
            self.complement = denominator - numerator
        else:
            self.denominator = denominator
            self.complement = complement
        lhs = self.numerator - RHS * self.denominator
        LpConstraint.__init__(self, lhs,
              sense = sense, rhs = 0, name = name)
        self.RHS = RHS

    def findLHSValue(self):
        """
        Determines the value of the fraction in the constraint after solution
        """
        if abs(value(self.denominator))>= EPS:
            return value(self.numerator)/value(self.denominator)
        else:
            if abs(value(self.numerator))<= EPS:
                #zero divided by zero will return 1
                return 1.0
            else:
                raise ZeroDivisionError

    def makeElasticSubProblem(self, *args, **kwargs):
        """
        Builds an elastic subproblem by adding variables and splitting the
        hard constraint

        uses FractionElasticSubProblem
        """
        return FractionElasticSubProblem(self, *args, **kwargs)

class LpConstraintVar(LpElement):
    """A Constraint that can be treated as a variable when constructing
    a LpProblem by columns
    """
    def __init__(self, name = None ,sense = None,
                 rhs = None, e = None):
        LpElement.__init__(self,name)
        self.constraint = LpConstraint(name = self.name, sense = sense,
                                       rhs = rhs , e = e)

    def addVariable(self, var, coeff):
        """
        Adds a variable to the constraint with the
        activity coeff
        """
        self.constraint.addterm(var, coeff)

    def value(self):
        return self.constraint.value()

class LpProblem(object):
    """An LP Problem"""
    def __init__(self, name = "NoName", sense = LpMinimize):
        """
        Creates an LP Problem

        This function creates a new LP Problem  with the specified associated parameters

        :param name: name of the problem used in the output .lp file
        :param sense: of the LP problem objective.  \
                Either :data:`~pulp.constants.LpMinimize` (default) \
                or :data:`~pulp.constants.LpMaximize`.
        :return: An LP Problem
        """
        self.objective = None
        self.constraints = _DICT_TYPE()
        self.name = name
        self.sense = sense
        self.sos1 = {}
        self.sos2 = {}
        self.status = LpStatusNotSolved
        self.noOverlap = 1
        self.solver = None
        self.initialValues = {}
        self.modifiedVariables = []
        self.modifiedConstraints = []
        self.resolveOK = False
        self._variables = []
        self._variable_ids = {}  #old school using dict.keys() for a set
        self.dummyVar = None


        # locals
        self.lastUnused = 0

    def __repr__(self):
        string = self.name+":\n"
        if self.sense == 1:
            string += "MINIMIZE\n"
        else:
            string += "MAXIMIZE\n"
        string += repr(self.objective) +"\n"

        if self.constraints:
            string += "SUBJECT TO\n"
            for n, c in self.constraints.items():
                string += c.asCplexLpConstraint(n) +"\n"
        string += "VARIABLES\n"
        for v in self.variables():
            string += v.asCplexLpVariable() + " " + LpCategories[v.cat] + "\n"
        return string

    def copy(self):
        """Make a copy of self. Expressions are copied by reference"""
        lpcopy = LpProblem(name = self.name, sense = self.sense)
        lpcopy.objective = self.objective
        lpcopy.constraints = self.constraints.copy()
        lpcopy.sos1 = self.sos1.copy()
        lpcopy.sos2 = self.sos2.copy()
        return lpcopy

    def deepcopy(self):
        """Make a copy of self. Expressions are copied by value"""
        lpcopy = LpProblem(name = self.name, sense = self.sense)
        if self.objective is not None:
            lpcopy.objective = self.objective.copy()
        lpcopy.constraints = {}
        for k,v in self.constraints.items():
            lpcopy.constraints[k] = v.copy()
        lpcopy.sos1 = self.sos1.copy()
        lpcopy.sos2 = self.sos2.copy()
        return lpcopy

    def normalisedNames(self):
        constraintsNames = {}
        i = 0
        for k in self.constraints:
            constraintsNames[k] = "C%07d" % i
            i += 1
        variablesNames = {}
        i = 0
        for k in self.variables():
            variablesNames[k.name] = "X%07d" % i
            i += 1
        return constraintsNames, variablesNames, "OBJ"

    def isMIP(self):
        for v in self.variables():
            if v.cat == LpInteger: return 1
        return 0

    def roundSolution(self, epsInt = 1e-5, eps = 1e-7):
        """
        Rounds the lp variables

        Inputs:
            - none

        Side Effects:
            - The lp variables are rounded
        """
        for v in self.variables():
            v.round(epsInt, eps)

    def unusedConstraintName(self):
        self.lastUnused += 1
        while 1:
            s = "_C%d" % self.lastUnused
            if s not in self.constraints: break
            self.lastUnused += 1
        return s

    def valid(self, eps = 0):
        for v in self.variables():
            if not v.valid(eps): return False
        for c in self.constraints.values():
            if not c.valid(eps): return False
        else:
            return True

    def infeasibilityGap(self, mip = 1):
        gap = 0
        for v in self.variables():
            gap = max(abs(v.infeasibilityGap(mip)), gap)
        for c in self.constraints.values():
            if not c.valid(0):
                gap = max(abs(c.value()), gap)
        return gap

    def addVariable(self, variable):
        """
        Adds a variable to the problem before a constraint is added

        @param variable: the variable to be added
        """
        if id(variable) not in self._variable_ids:
            self._variables.append(variable)
            self._variable_ids[id(variable)] = variable

    def addVariables(self, variables):
        """
        Adds variables to the problem before a constraint is added

        @param variables: the variables to be added
        """
        for v in variables:
            self.addVariable(v)

    def variables(self):
        """
        Returns a list of the problem variables

        Inputs:
            - none

        Returns:
            - A list of the problem variables
        """
        if self.objective:
            self.addVariables(list(self.objective.keys()))
        for c in self.constraints.values():
            self.addVariables(list(c.keys()))
        variables = self._variables
        #sort the varibles DSU
        variables = [[v.name, v] for v in variables]
        variables.sort()
        variables = [v for _, v in variables]
        return variables

    def variablesDict(self):
        variables = {}
        if self.objective:
            for v in self.objective:
                variables[v.name] = v
        for c in list(self.constraints.values()):
            for v in c:
                variables[v.name] = v
        return variables

    def add(self, constraint, name = None):
        self.addConstraint(constraint, name)

    def addConstraint(self, constraint, name = None):
        if not isinstance(constraint, LpConstraint):
            raise TypeError("Can only add LpConstraint objects")
        if name:
            constraint.name = name
        try:
            if constraint.name:
                name = constraint.name
            else:
                name = self.unusedConstraintName()
        except AttributeError:
            raise TypeError("Can only add LpConstraint objects")
            #removed as this test fails for empty constraints
#        if len(constraint) == 0:
#            if not constraint.valid():
#                raise ValueError, "Cannot add false constraints"
        if name in self.constraints:
            if self.noOverlap:
                raise PulpError("overlapping constraint names: " + name)
            else:
                print("Warning: overlapping constraint names:", name)
        self.constraints[name] = constraint
        self.modifiedConstraints.append(constraint)
        self.addVariables(list(constraint.keys()))

    def setObjective(self,obj):
        """
        Sets the input variable as the objective function. Used in Columnwise Modelling

        :param obj: the objective function of type :class:`LpConstraintVar`

        Side Effects:
            - The objective function is set
        """
        if isinstance(obj, LpVariable):
            # allows the user to add a LpVariable as an objective
            obj = obj + 0.0
        try:
            obj = obj.constraint
            name = obj.name
        except AttributeError:
            name = None
        self.objective = obj
        self.objective.name = name
        self.resolveOK = False

    def __iadd__(self, other):
        if isinstance(other, tuple):
            other, name = other
        else:
            name = None
        if other is True:
            return self
        if isinstance(other, LpConstraintVar):
            self.addConstraint(other.constraint)
        elif isinstance(other, LpConstraint):
            self.addConstraint(other, name)
        elif isinstance(other, LpAffineExpression):
            self.objective = other
            self.objective.name = name
        elif isinstance(other, LpVariable) or isinstance(other, (int, float)):
            self.objective = LpAffineExpression(other)
            self.objective.name = name
        else:
            raise TypeError("Can only add LpConstraintVar, LpConstraint, LpAffineExpression or True objects")
        return self

    def extend(self, other, use_objective = True):
        """
        extends an LpProblem by adding constraints either from a dictionary
        a tuple or another LpProblem object.

        @param use_objective: determines whether the objective is imported from
        the other problem

        For dictionaries the constraints will be named with the keys
        For tuples an unique name will be generated
        For LpProblems the name of the problem will be added to the constraints
        name
        """
        if isinstance(other, dict):
            for name in other:
                self.constraints[name] = other[name]
        elif isinstance(other, LpProblem):
            for v in set(other.variables()).difference(self.variables()):
                v.name = other.name + v.name
            for name,c in other.constraints.items():
                c.name = other.name + name
                self.addConstraint(c)
            if use_objective:
                self.objective += other.objective
        else:
            for c in other:
                if isinstance(c,tuple):
                    name = c[0]
                    c = c[1]
                else:
                    name = None
                if not name: name = c.name
                if not name: name = self.unusedConstraintName()
                self.constraints[name] = c

    def coefficients(self, translation = None):
        coefs = []
        if translation == None:
            for c in self.constraints:
                cst = self.constraints[c]
                coefs.extend([(v.name, c, cst[v]) for v in cst])
        else:
            for c in self.constraints:
                ctr = translation[c]
                cst = self.constraints[c]
                coefs.extend([(translation[v.name], ctr, cst[v]) for v in cst])
        return coefs

    def writeMPS(self, filename, mpsSense = 0, rename = 0, mip = 1):
        wasNone, dummyVar = self.fixObjective()
        f = open(filename, "w")
        if mpsSense == 0: mpsSense = self.sense
        cobj = self.objective
        if mpsSense != self.sense:
            n = cobj.name
            cobj = - cobj
            cobj.name = n
        if rename:
            constraintsNames, variablesNames, cobj.name = self.normalisedNames()
        f.write("*SENSE:"+LpSenses[mpsSense]+"\n")
        n = self.name
        if rename: n = "MODEL"
        f.write("NAME          "+n+"\n")
        vs = self.variables()
        # constraints
        f.write("ROWS\n")
        objName = cobj.name
        if not objName: objName = "OBJ"
        f.write(" N  %s\n" % objName)
        mpsConstraintType = {LpConstraintLE:"L", LpConstraintEQ:"E", LpConstraintGE:"G"}
        for k,c in self.constraints.items():
            if rename: k = constraintsNames[k]
            f.write(" "+mpsConstraintType[c.sense]+"  "+k+"\n")
        # matrix
        f.write("COLUMNS\n")
        # Creation of a dict of dict:
        # coefs[nomVariable][nomContrainte] = coefficient
        coefs = {}
        for k,c in self.constraints.items():
            if rename: k = constraintsNames[k]
            for v in c:
                n = v.name
                if rename: n = variablesNames[n]
                if n in coefs:
                    coefs[n][k] = c[v]
                else:
                    coefs[n] = {k:c[v]}

        for v in vs:
            if mip and v.cat == LpInteger:
                f.write("    MARK      'MARKER'                 'INTORG'\n")
            n = v.name
            if rename: n = variablesNames[n]
            if n in coefs:
                cv = coefs[n]
                # Most of the work is done here
                for k in cv: f.write("    %-8s  %-8s  % .12e\n" % (n,k,cv[k]))

            # objective function
            if v in cobj: f.write("    %-8s  %-8s  % .12e\n" % (n,objName,cobj[v]))
            if mip and v.cat == LpInteger:
                f.write("    MARK      'MARKER'                 'INTEND'\n")
        # right hand side
        f.write("RHS\n")
        for k,c in self.constraints.items():
            c = -c.constant
            if rename: k = constraintsNames[k]
            if c == 0: c = 0
            f.write("    RHS       %-8s  % .12e\n" % (k,c))
        # bounds
        f.write("BOUNDS\n")
        for v in vs:
            n = v.name
            if rename: n = variablesNames[n]
            if v.lowBound != None and v.lowBound == v.upBound:
                f.write(" FX BND       %-8s  % .12e\n" % (n, v.lowBound))
            elif v.lowBound == 0 and v.upBound == 1 and mip and v.cat == LpInteger:
                f.write(" BV BND       %-8s\n" % n)
            else:
                if v.lowBound != None:
                    # In MPS files, variables with no bounds (i.e. >= 0)
                    # are assumed BV by COIN and CPLEX.
                    # So we explicitly write a 0 lower bound in this case.
                    if v.lowBound != 0 or (mip and v.cat == LpInteger and v.upBound == None):
                        f.write(" LO BND       %-8s  % .12e\n" % (n, v.lowBound))
                else:
                    if v.upBound != None:
                        f.write(" MI BND       %-8s\n" % n)
                    else:
                        f.write(" FR BND       %-8s\n" % n)
                if v.upBound != None:
                    f.write(" UP BND       %-8s  % .12e\n" % (n, v.upBound))
        f.write("ENDATA\n")
        f.close()
        self.restoreObjective(wasNone, dummyVar)
        # returns the variables, in writing order
        if rename == 0:
            return vs
        else:
            return vs, variablesNames, constraintsNames, cobj.name

    def writeLP(self, filename, writeSOS = 1, mip = 1):
        """
        Write the given Lp problem to a .lp file.

        This function writes the specifications (objective function,
        constraints, variables) of the defined Lp problem to a file.

        :param filename:  the name of the file to be created.

        Side Effects:
            - The file is created.
        """
        f = open(filename, "w")
        f.write("\\* "+self.name+" *\\\n")
        if self.sense == 1:
            f.write("Minimize\n")
        else:
            f.write("Maximize\n")
        wasNone, dummyVar = self.fixObjective()
        objName = self.objective.name
        if not objName: objName = "OBJ"
        f.write(self.objective.asCplexLpAffineExpression(objName, constant = 0))
        f.write("Subject To\n")
        ks = list(self.constraints.keys())
        ks.sort()
        for k in ks:
            constraint = self.constraints[k]
            if not list(constraint.keys()):
                #empty constraint add the dummyVar
                dummyVar = self.get_dummyVar()
                constraint += dummyVar
                #set this dummyvar to zero so infeasible problems are not made feasible
                f.write((dummyVar == 0.0).asCplexLpConstraint("_dummy"))
            f.write(constraint.asCplexLpConstraint(k))
        vs = self.variables()
        # check if any names are longer than 100 characters
        long_names = [v.name for v in vs if len(v.name) > 100]
        if long_names:
            raise PulpError('Variable names too long for Lp format\n'
                                + str(long_names))
        # check for repeated names
        repeated_names = {}
        for v in vs:
            repeated_names[v.name] = repeated_names.get(v.name, 0) + 1
        repeated_names = [(key, value) for key, value in list(repeated_names.items())
                            if value >= 2]
        if repeated_names:
            raise PulpError('Repeated variable names in Lp format\n'
                                + str(repeated_names))
        # Bounds on non-"positive" variables
        # Note: XPRESS and CPLEX do not interpret integer variables without
        # explicit bounds
        if mip:
            vg = [v for v in vs if not (v.isPositive() and v.cat == LpContinuous) \
                and not v.isBinary()]
        else:
            vg = [v for v in vs if not v.isPositive()]
        if vg:
            f.write("Bounds\n")
            for v in vg:
                f.write("%s\n" % v.asCplexLpVariable())
        # Integer non-binary variables
        if mip:
            vg = [v for v in vs if v.cat == LpInteger and not v.isBinary()]
            if vg:
                f.write("Generals\n")
                for v in vg: f.write("%s\n" % v.name)
            # Binary variables
            vg = [v for v in vs if v.isBinary()]
            if vg:
                f.write("Binaries\n")
                for v in vg: f.write("%s\n" % v.name)
        # Special Ordered Sets
        if writeSOS and (self.sos1 or self.sos2):
            f.write("SOS\n")
            if self.sos1:
                for sos in self.sos1.values():
                    f.write("S1:: \n")
                    for v,val in sos.items():
                        f.write(" %s: %.12g\n" % (v.name, val))
            if self.sos2:
                for sos in self.sos2.values():
                    f.write("S2:: \n")
                    for v,val in sos.items():
                        f.write(" %s: %.12g\n" % (v.name, val))
        f.write("End\n")
        f.close()
        self.restoreObjective(wasNone, dummyVar)

    def assignVarsVals(self, values):
        variables = self.variablesDict()
        for name in values:
            if name != '__dummy':
                variables[name].varValue = values[name]

    def assignVarsDj(self,values):
        variables = self.variablesDict()
        for name in values:
            if name != '__dummy':
                variables[name].dj = values[name]

    def assignConsPi(self, values):
        for name in values:
            self.constraints[name].pi = values[name]

    def assignConsSlack(self, values, activity=False):
        for name in values:
            if activity:
                #reports the activitynot the slack
                self.constraints[name].slack = -1 * (
                        self.constraints[name].constant + float(values[name]))
            else:
                self.constraints[name].slack = float(values[name])

    def get_dummyVar(self):
        if self.dummyVar is None:
            self.dummyVar = LpVariable("__dummy", 0, 0)
        return self.dummyVar

    def fixObjective(self):
        if self.objective is None:
            self.objective = 0
            wasNone = 1
        else:
            wasNone = 0
        if not isinstance(self.objective, LpAffineExpression):
            self.objective = LpAffineExpression(self.objective)
        if self.objective.isNumericalConstant():
            dummyVar = self.get_dummyVar()
            self.objective += dummyVar
        else:
            dummyVar = None
        return wasNone, dummyVar

    def restoreObjective(self, wasNone, dummyVar):
        if wasNone:
            self.objective = None
        elif not dummyVar is None:
            self.objective -= dummyVar

    def solve(self, solver = None, **kwargs):
        """
        Solve the given Lp problem.

        This function changes the problem to make it suitable for solving
        then calls the solver.actualSolve() method to find the solution

        :param solver:  Optional: the specific solver to be used, defaults to the
              default solver.

        Side Effects:
            - The attributes of the problem object are changed in
              :meth:`~pulp.solver.LpSolver.actualSolve()` to reflect the Lp solution
        """

        if not(solver): solver = self.solver
        if not(solver): solver = LpSolverDefault
        wasNone, dummyVar = self.fixObjective()
        #time it
        self.solutionTime = -clock()
        status = solver.actualSolve(self, **kwargs)
        self.solutionTime += clock()
        self.restoreObjective(wasNone, dummyVar)
        self.solver = solver
        return status

    def sequentialSolve(self, objectives, absoluteTols = None,
                        relativeTols = None, solver = None, debug = False):
        """
        Solve the given Lp problem with several objective functions.

        This function sequentially changes the objective of the problem
        and then adds the objective function as a constraint

        :param objectives: the list of objectives to be used to solve the problem
        :param absoluteTols: the list of absolute tolerances to be applied to
           the constraints should be +ve for a minimise objective
        :param relativeTols: the list of relative tolerances applied to the constraints
        :param solver: the specific solver to be used, defaults to the default solver.

        """
        #TODO Add a penalty variable to make problems elastic
        #TODO add the ability to accept different status values i.e. infeasible etc

        if not(solver): solver = self.solver
        if not(solver): solver = LpSolverDefault
        if not(absoluteTols):
            absoluteTols = [0] * len(objectives)
        if not(relativeTols):
            relativeTols  = [1] * len(objectives)
        #time it
        self.solutionTime = -clock()
        statuses = []
        for i,(obj,absol,rel) in enumerate(zip(objectives,
                                               absoluteTols, relativeTols)):
            self.setObjective(obj)
            status = solver.actualSolve(self)
            statuses.append(status)
            if debug: self.writeLP("%sSequence.lp"%i)
            if self.sense == LpMinimize:
                self += obj <= value(obj)*rel + absol,"%s_Sequence_Objective"%i
            elif self.sense == LpMaximize:
                self += obj >= value(obj)*rel + absol,"%s_Sequence_Objective"%i
        self.solutionTime += clock()
        self.solver = solver
        return statuses

    def resolve(self, solver = None, **kwargs):
        """
        resolves an Problem using the same solver as previously
        """
        if not(solver): solver = self.solver
        if self.resolveOK:
            return self.solver.actualResolve(self, **kwargs)
        else:
            return self.solve(solver = solver, **kwargs)

    def setSolver(self,solver = LpSolverDefault):
        """Sets the Solver for this problem useful if you are using
        resolve
        """
        self.solver = solver

    def setInitial(self,values):
        self.initialValues = values

    def numVariables(self):
        return len(self._variable_ids)

    def numConstraints(self):
        return len(self.constraints)

    def getSense(self):
        return self.sense

class FixedElasticSubProblem(LpProblem):
    """
    Contains the subproblem generated by converting a fixed constraint
    :math:`\sum_{i}a_i x_i = b` into an elastic constraint.

    :param constraint: The LpConstraint that the elastic constraint is based on
    :param penalty: penalty applied for violation (+ve or -ve) of the constraints
    :param proportionFreeBound:
        the proportional bound (+ve and -ve) on
        constraint violation that is free from penalty
    :param proportionFreeBoundList: the proportional bound on \
        constraint violation that is free from penalty, expressed as a list\
        where [-ve, +ve]
    """
    def __init__(self, constraint, penalty = None,
                                        proportionFreeBound = None,
                                        proportionFreeBoundList = None):
        subProblemName =  "%s_elastic_SubProblem" % constraint.name
        LpProblem.__init__(self, subProblemName, LpMinimize)
        self.objective = LpAffineExpression()
        self.constraint = constraint
        self.constant = constraint.constant
        self.RHS = - constraint.constant
        self.objective = LpAffineExpression()
        self += constraint, "_Constraint"
        #create and add these variables but disabled
        self.freeVar = LpVariable("_free_bound",
                                  upBound = 0, lowBound = 0)
        self.upVar = LpVariable("_pos_penalty_var",
                                upBound = 0, lowBound = 0)
        self.lowVar = LpVariable("_neg_penalty_var",
                                 upBound = 0, lowBound = 0)
        constraint.addInPlace(self.freeVar + self.lowVar + self.upVar)
        if proportionFreeBound:
            proportionFreeBoundList = [proportionFreeBound, proportionFreeBound]
        if proportionFreeBoundList:
            #add a costless variable
            self.freeVar.upBound = abs(constraint.constant *
                                        proportionFreeBoundList[0])
            self.freeVar.lowBound = -abs(constraint.constant *
                                       proportionFreeBoundList[1])
            # Note the reversal of the upbound and lowbound due to the nature of the
            # variable
        if penalty is not None:
            #activate these variables
            self.upVar.upBound = None
            self.lowVar.lowBound = None
            self.objective = penalty*self.upVar - penalty*self.lowVar

    def _findValue(self, attrib):
        """
        safe way to get the value of a variable that may not exist
        """
        var = getattr(self, attrib, 0)
        if var:
            if value(var) is not None:
                return value(var)
            else:
                return 0.0
        else:
            return 0.0

    def isViolated(self):
        """
        returns true if the penalty variables are non-zero
        """
        upVar = self._findValue("upVar")
        lowVar = self._findValue("lowVar")
        freeVar = self._findValue("freeVar")
        result = abs(upVar + lowVar) >= EPS
        if result:
            log.debug("isViolated %s, upVar %s, lowVar %s, freeVar %s result %s"%(
                        self.name, upVar, lowVar, freeVar, result))
            log.debug("isViolated value lhs %s constant %s"%(
                         self.findLHSValue(), self.RHS))
        return result

    def findDifferenceFromRHS(self):
        """
        The amount the actual value varies from the RHS (sense: LHS - RHS)
        """
        return self.findLHSValue() - self.RHS


    def findLHSValue(self):
        """
        for elastic constraints finds the LHS value of the constraint without
        the free variable and or penalty variable assumes the constant is on the
        rhs
        """
        upVar = self._findValue("upVar")
        lowVar = self._findValue("lowVar")
        freeVar = self._findValue("freeVar")
        return self.constraint.value() - self.constant - \
                upVar - lowVar - freeVar

    def deElasticize(self):
        """ de-elasticize constraint """
        self.upVar.upBound = 0
        self.lowVar.lowBound = 0

    def reElasticize(self):
        """
        Make the Subproblem elastic again after deElasticize
        """
        self.upVar.lowBound = 0
        self.upVar.upBound = None
        self.lowVar.upBound = 0
        self.lowVar.lowBound = None

    def alterName(self, name):
        """
        Alters the name of anonymous parts of the problem

        """
        self.name = "%s_elastic_SubProblem" % name
        if hasattr(self, 'freeVar'):
            self.freeVar.name = self.name + "_free_bound"
        if hasattr(self, 'upVar'):
            self.upVar.name = self.name + "_pos_penalty_var"
        if hasattr(self, 'lowVar'):
            self.lowVar.name = self.name + "_neg_penalty_var"


class FractionElasticSubProblem(FixedElasticSubProblem):
    """
    Contains the subproblem generated by converting a Fraction constraint
    numerator/(numerator+complement) = b
    into an elastic constraint

    :param name: The name of the elastic subproblem
    :param penalty: penalty applied for violation (+ve or -ve) of the constraints
    :param proportionFreeBound: the proportional bound (+ve and -ve) on
        constraint violation that is free from penalty
    :param proportionFreeBoundList: the proportional bound on
        constraint violation that is free from penalty, expressed as a list
        where [-ve, +ve]
    """
    def __init__(self, name, numerator, RHS, sense,
                                        complement = None,
                                        denominator = None,
                                        penalty = None,
                                        proportionFreeBound = None,
                                        proportionFreeBoundList = None):
        subProblemName = "%s_elastic_SubProblem" % name
        self.numerator = numerator
        if denominator is None and complement is not None:
            self.complement = complement
            self.denominator = numerator + complement
        elif denominator is not None and complement is None:
            self.denominator = denominator
            self.complement = denominator - numerator
        else:
            raise PulpError('only one of denominator and complement must be specified')
        self.RHS = RHS
        self.lowTarget = self.upTarget = None
        LpProblem.__init__(self, subProblemName, LpMinimize)
        self.freeVar = LpVariable("_free_bound",
                                  upBound = 0, lowBound = 0)
        self.upVar = LpVariable("_pos_penalty_var",
                                upBound = 0, lowBound = 0)
        self.lowVar = LpVariable("_neg_penalty_var",
                                 upBound = 0, lowBound = 0)
        if proportionFreeBound:
            proportionFreeBoundList = [proportionFreeBound, proportionFreeBound]
        if proportionFreeBoundList:
            upProportionFreeBound, lowProportionFreeBound = \
                    proportionFreeBoundList
        else:
            upProportionFreeBound, lowProportionFreeBound = (0, 0)
        #create an objective
        self += LpAffineExpression()
        #There are three cases if the constraint.sense is ==, <=, >=
        if sense in [LpConstraintEQ, LpConstraintLE]:
            #create a constraint the sets the upper bound of target
            self.upTarget = RHS + upProportionFreeBound
            self.upConstraint = LpFractionConstraint(self.numerator,
                                    self.complement,
                                    LpConstraintLE,
                                    self.upTarget,
                                    denominator = self.denominator)
            if penalty is not None:
                self.lowVar.lowBound = None
                self.objective += -1* penalty * self.lowVar
                self.upConstraint += self.lowVar
            self += self.upConstraint, '_upper_constraint'
        if sense in [LpConstraintEQ, LpConstraintGE]:
            #create a constraint the sets the lower bound of target
            self.lowTarget = RHS - lowProportionFreeBound
            self.lowConstraint = LpFractionConstraint(self.numerator,
                                                 self.complement,
                                                LpConstraintGE,
                                                self.lowTarget,
                                                denominator = self.denominator)
            if penalty is not None:
                self.upVar.upBound = None
                self.objective += penalty * self.upVar
                self.lowConstraint += self.upVar
            self += self.lowConstraint, '_lower_constraint'

    def findLHSValue(self):
        """
        for elastic constraints finds the LHS value of the constraint without
        the free variable and or penalty variable assumes the constant is on the
        rhs
        """
        # uses code from LpFractionConstraint
        if abs(value(self.denominator))>= EPS:
            return value(self.numerator)/value(self.denominator)
        else:
            if abs(value(self.numerator))<= EPS:
                #zero divided by zero will return 1
                return 1.0
            else:
                raise ZeroDivisionError

    def isViolated(self):
        """
        returns true if the penalty variables are non-zero
        """
        if abs(value(self.denominator))>= EPS:
            if self.lowTarget is not None:
                if self.lowTarget > self.findLHSValue():
                    return True
            if self.upTarget is not None:
                if self.findLHSValue() > self.upTarget:
                    return True
        else:
            #if the denominator is zero the constraint is satisfied
            return False

class LpVariableDict(dict):
    """An LP variable generator"""
    def __init__(self, name, data = {}, lowBound = None, upBound = None, cat = LpContinuous):
        self.name = name
        dict.__init__(self, data)

    def __getitem__(self, key):
        if key in self:
            return dict.__getitem__(self, key)
        else:
            self[key] = LpVariable(self.name % key, lowBound, upBound, cat)
            return self[key]

# Utility functions

def lpSum(vector):
    """
    Calculate the sum of a list of linear expressions

    :param vector: A list of linear expressions
    """
    return LpAffineExpression().addInPlace(vector)

def lpDot(v1, v2):
    """Calculate the dot product of two lists of linear expressions"""
    if not isiterable(v1) and not isiterable(v2):
        return v1 * v2
    elif not isiterable(v1):
        return lpDot([v1]*len(v2),v2)
    elif not isiterable(v2):
        return lpDot(v1,[v2]*len(v1))
    else:
        return lpSum([lpDot(e1,e2) for e1,e2 in zip(v1,v2)])

def isNumber(x):
    """Returns true if x is an int or a float"""
    return isinstance(x, (int, float))

def value(x):
    """Returns the value of the variable/expression x, or x if it is a number"""
    if isNumber(x): return x
    else: return x.value()

def valueOrDefault(x):
    """Returns the value of the variable/expression x, or x if it is a number
    Variable without value (None) are affected a possible value (within their
    bounds)."""
    if isNumber(x): return x
    else: return x.valueOrDefault()

def combination(orgset, k = None):
    """
    returns an iterator that lists the combinations of orgset of
    length k

    :param orgset: the list to be iterated
    :param k: the cardinality of the subsets

    :return: an iterator of the subsets

    example:

    >>> c = combination([1,2,3,4],2)
    >>> for s in c:
    ...     print(s)
    (1, 2)
    (1, 3)
    (1, 4)
    (2, 3)
    (2, 4)
    (3, 4)
    """
    try:
        from itertools import combination as _it_combination
        return _it_combination(orgset, k)
    except ImportError:
        return __combination(orgset,k)

def __combination(orgset,k):
    """
    fall back if probstat is not installed note it is GPL so cannot
    be included
    """
    if k == 1:
        for i in orgset:
            yield (i,)
    elif k>1:
        for i,x in enumerate(orgset):
            #iterates though to near the end
            for s in __combination(orgset[i+1:],k-1):
                yield (x,) + s

def permutation(orgset, k = None):
    """
    returns an iterator that lists the permutations of orgset of
    length k

    :param orgset: the list to be iterated
    :param k: the cardinality of the subsets

    :return: an iterator of the subsets

    example:

    >>> c = permutation([1,2,3,4],2)
    >>> for s in c:
    ...     print(s)
    (1, 2)
    (1, 3)
    (1, 4)
    (2, 1)
    (2, 3)
    (2, 4)
    (3, 1)
    (3, 2)
    (3, 4)
    (4, 1)
    (4, 2)
    (4, 3)
    """
    try:
        from itertools import permutation as _it_permutation
        return _it_permutation(orgset, k)
    except ImportError:
        return __permutation(orgset, k)

def __permutation(orgset, k):
    """
    fall back if probstat is not installed note it is GPL so cannot
    be included
    """
    if k == 1:
        for i in orgset:
            yield (i,)
    elif k>1:
        for i,x in enumerate(orgset):
            #iterates though to near the end
            for s in __permutation(orgset[:i] + orgset[i+1:],k-1):
                yield (x,)+ s

def allpermutations(orgset,k):
    """
    returns all permutations of orgset with up to k items

    :param orgset: the list to be iterated
    :param k: the maxcardinality of the subsets

    :return: an iterator of the subsets

    example:

    >>> c = allpermutations([1,2,3,4],2)
    >>> for s in c:
    ...     print(s)
    (1,)
    (2,)
    (3,)
    (4,)
    (1, 2)
    (1, 3)
    (1, 4)
    (2, 1)
    (2, 3)
    (2, 4)
    (3, 1)
    (3, 2)
    (3, 4)
    (4, 1)
    (4, 2)
    (4, 3)
    """
    return itertools.chain(*[permutation(orgset,i) for i in range(1,k+1)])

def allcombinations(orgset,k):
    """
    returns all permutations of orgset with up to k items

    :param orgset: the list to be iterated
    :param k: the maxcardinality of the subsets

    :return: an iterator of the subsets

    example:

    >>> c = allcombinations([1,2,3,4],2)
    >>> for s in c:
    ...     print(s)
    (1,)
    (2,)
    (3,)
    (4,)
    (1, 2)
    (1, 3)
    (1, 4)
    (2, 3)
    (2, 4)
    (3, 4)
    """
    return itertools.chain(*[combination(orgset,i) for i in range(1,k+1)])

def makeDict(headers, array, default = None):
    """
    makes a list into a dictionary with the headings given in headings
    headers is a list of header lists
    array is a list with the data
    """
    result, defdict = __makeDict(headers, array, default)
    return result

def __makeDict(headers, array, default = None):
    #this is a recursive function so end the recursion as follows
    result ={}
    returndefaultvalue = None
    if len(headers) == 1:
        result.update(dict(zip(headers[0],array)))
        defaultvalue = default
    else:
        for i,h in enumerate(headers[0]):
            result[h],defaultvalue = __makeDict(headers[1:],array[i],default)
    if default != None:
        f = lambda :defaultvalue
        defresult = collections.defaultdict(f)
        defresult.update(result)
        result = defresult
        returndefaultvalue = collections.defaultdict(f)
    return result, returndefaultvalue

def splitDict(Data):
    """
    Split a dictionary with lists as the data, into smaller dictionaries

    :param Data: A dictionary with lists as the values

    :return: A tuple of dictionaries each containing the data separately,
            with the same dictionary keys
    """
    # find the maximum number of items in the dictionary
    maxitems = max([len(values) for values in Data.values()])
    output =[dict() for i in range(maxitems)]
    for key, values in Data.items():
        for i, val in enumerate(values):
            output[i][key] = val

    return tuple(output)

def read_table(data, coerce_type, transpose=False):
    '''
    Reads in data from a simple table and forces it to be a particular type

    This is a helper function that allows data to be easily constained in a
    simple script
    ::return: a dictionary of with the keys being a tuple of the strings
       in the first row and colum of the table
    ::param data: the multiline string containing the table data
    ::param coerce_type: the type that the table data is converted to
    ::param transpose: reverses the data if needed

    Example:
    >>> table_data = """
    ...         L1      L2      L3      L4      L5      L6
    ... C1      6736    42658   70414   45170   184679  111569
    ... C2      217266  227190  249640  203029  153531  117487
    ... C3      35936   28768   126316  2498    130317  74034
    ... C4      73446   52077   108368  75011   49827   62850
    ... C5      174664  177461  151589  153300  59916   135162
    ... C6      186302  189099  147026  164938  149836  286307
    ... """
    >>> table = read_table(table_data, int)
    >>> table[("C1","L1")]
    6736
    >>> table[("C6","L5")]
    149836
    '''
    lines = data.splitlines()
    headings = lines[1].split()
    result = {}
    for row in lines[2:]:
        items = row.split()
        for i, item in enumerate(items[1:]):
            if transpose:
                key = (headings[i], items[0])
            else:
                key = (items[0], headings[i])
            result[key] = coerce_type(item)
    return result

def configSolvers():
    """
    Configure the path the the solvers on the command line

    Designed to configure the file locations of the solvers from the
    command line after installation
    """
    configlist = [(cplex_dll_path,"cplexpath","CPLEX: "),
                  (coinMP_path, "coinmppath","CoinMP dll (windows only): ")]
    print("Please type the full path including filename and extension \n" +
           "for each solver available")
    configdict = {}
    for (default, key, msg) in configlist:
        value = input(msg + "[" + str(default) +"]")
        if value:
            configdict[key] = value
    setConfigInformation(**configdict)


def pulpTestAll():
    from .tests import pulpTestSolver
    solvers = [PULP_CBC_CMD,
               CPLEX_DLL,
               CPLEX_CMD,
               CPLEX_PY,
               COIN_CMD,
               COINMP_DLL,
               GLPK_CMD,
               XPRESS,
               GUROBI,
               GUROBI_CMD,
               PYGLPK,
               YAPOSIB
               ]

    failed = False
    for s in solvers:
        if s().available():
            try:
                pulpTestSolver(s)
                print("* Solver %s passed." % s)
            except Exception as e:
                print(e)
                print("* Solver", s, "failed.")
                failed = True
        else:
            print("Solver %s unavailable" % s)
    if failed:
        raise PulpError("Tests Failed")

def pulpDoctest():
    """
    runs all doctests
    """
    import doctest
    if __name__ != '__main__':
        from . import pulp
        doctest.testmod(pulp)
    else:
        doctest.testmod()


if __name__ == '__main__':
    # Tests
    pulpTestAll()
    pulpDoctest()
