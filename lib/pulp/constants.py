# PuLP : Python LP Modeler

# Copyright (c) 2002-2005, Jean-Sebastien Roy (js@jeannot.org)
# Modifications Copyright (c) 2007- Stuart Anthony Mitchell (s.mitchell@auckland.ac.nz)
# $Id:constants.py 1791 2008-04-23 22:54:34Z smit023 $

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
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE."""

"""
This file contains the constant definitions for PuLP
Note that hopefully these will be changed into something more pythonic
"""
VERSION = '1.6.0'
EPS = 1e-7

# variable categories
LpContinuous = "Continuous"
LpInteger = "Integer"
LpBinary = "Binary"
LpCategories = {LpContinuous: "Continuous", LpInteger: "Integer",
                LpBinary: "Binary"}

# objective sense
LpMinimize = 1
LpMaximize = -1
LpSenses = {LpMaximize:"Maximize", LpMinimize:"Minimize"}

# problem status
LpStatusNotSolved = 0
LpStatusOptimal = 1
LpStatusInfeasible = -1
LpStatusUnbounded = -2
LpStatusUndefined = -3
LpStatus = { LpStatusNotSolved:"Not Solved",
    LpStatusOptimal:"Optimal",
    LpStatusInfeasible:"Infeasible",
    LpStatusUnbounded:"Unbounded",
    LpStatusUndefined:"Undefined",
    }

# constraint sense
LpConstraintLE = -1
LpConstraintEQ = 0
LpConstraintGE = 1
LpConstraintSenses = {LpConstraintEQ:"=", LpConstraintLE:"<=", LpConstraintGE:">="}

# LP line size
LpCplexLPLineSize = 78

def isiterable(obj):
    try: obj=iter(obj)
    except: return False
    else: return True

class PulpError(Exception):
    """
    Pulp Exception Class
    """
    pass
