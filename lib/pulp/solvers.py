# PuLP : Python LP Modeler
# Version 1.4.2

# Copyright (c) 2002-2005, Jean-Sebastien Roy (js@jeannot.org)
# Modifications Copyright (c) 2007- Stuart Anthony Mitchell (s.mitchell@auckland.ac.nz)
# $Id:solvers.py 1791 2008-04-23 22:54:34Z smit023 $

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
This file contains the solver classes for PuLP
Note that the solvers that require a compiled extension may not work in
the current version
"""

import os
import subprocess
import sys
from time import clock
try:
    import configparser
except ImportError:
    import ConfigParser as configparser
from . import sparse
import collections
import warnings
from tempfile import mktemp
from .constants import *

import logging
log = logging.getLogger(__name__)

class PulpSolverError(PulpError):
    """
    Pulp Solver-related exceptions
    """
    pass

#import configuration information
def initialize(filename, operating_system='linux', arch='64'):
    """ reads the configuration file to initialise the module"""
    here = os.path.dirname(filename)
    config = configparser.SafeConfigParser({'here':here,
        'os':operating_system, 'arch':arch})
    config.read(filename)

    try:
        cplex_dll_path = config.get("locations", "CplexPath")
    except configparser.Error:
        cplex_dll_path = 'libcplex110.so'
    try:
        try:
            ilm_cplex_license = config.get("licenses",
                "ilm_cplex_license").decode("string-escape").replace('"','')
        except AttributeError:
            ilm_cplex_license = config.get("licenses",
                "ilm_cplex_license").replace('"','')
    except configparser.Error:
        ilm_cplex_license = ''
    try:
        ilm_cplex_license_signature = config.getint("licenses",
                "ilm_cplex_license_signature")
    except configparser.Error:
        ilm_cplex_license_signature = 0
    try:
        coinMP_path = config.get("locations", "CoinMPPath").split(', ')
    except configparser.Error:
        coinMP_path = ['libCoinMP.so']
    try:
        gurobi_path = config.get("locations", "GurobiPath")
    except configparser.Error:
        gurobi_path = '/opt/gurobi201/linux32/lib/python2.5'
    try:
        cbc_path = config.get("locations", "CbcPath")
    except configparser.Error:
        cbc_path = 'cbc'
    try:
        glpk_path = config.get("locations", "GlpkPath")
    except configparser.Error:
        glpk_path = 'glpsol'
    try:
        pulp_cbc_path = config.get("locations", "PulpCbcPath")
    except configparser.Error:
        pulp_cbc_path = 'cbc'
    for i,path in enumerate(coinMP_path):
        if not os.path.dirname(path):
            #if no pathname is supplied assume the file is in the same directory
            coinMP_path[i] = os.path.join(os.path.dirname(config_filename),path)
    return cplex_dll_path, ilm_cplex_license, ilm_cplex_license_signature,\
        coinMP_path, gurobi_path, cbc_path, glpk_path, pulp_cbc_path

#pick up the correct config file depending on operating system
PULPCFGFILE = "pulp.cfg"
is_64bits = sys.maxsize > 2**32
if is_64bits:
    arch = '64'
else:
    arch = '32'
operating_system = None
if sys.platform in ['win32', 'cli']:
    operating_system = 'win'
    PULPCFGFILE += ".win"
elif sys.platform in ['darwin']:
    operating_system = "osx"
    arch = '64'
    PULPCFGFILE += ".osx"
else:
    operating_system = "linux"
    PULPCFGFILE += ".linux"

if __name__ != '__main__':
    DIRNAME = os.path.dirname(__file__)
    config_filename = os.path.join(DIRNAME,
                                   PULPCFGFILE)
else: #run as a script
    from .pulp import __file__ as fname
    DIRNAME = os.path.dirname(fname)
    config_filename = os.path.join(DIRNAME,
                                   PULPCFGFILE)
cplex_dll_path, ilm_cplex_license, ilm_cplex_license_signature, \
        coinMP_path, gurobi_path, cbc_path, glpk_path, pulp_cbc_path = \
        initialize(config_filename, operating_system, arch)


# See later for LpSolverDefault definition
class LpSolver:
    """A generic LP Solver"""

    def __init__(self, mip = True, msg = True, options = [], *args, **kwargs):
        self.mip = mip
        self.msg = msg
        self.options = options

    def available(self):
        """True if the solver is available"""
        raise NotImplementedError

    def actualSolve(self, lp):
        """Solve a well formulated lp problem"""
        raise NotImplementedError

    def actualResolve(self,lp, **kwargs):
        """
        uses existing problem information and solves the problem
        If it is not implelemented in the solver
        just solve again
        """
        self.actualSolve(lp, **kwargs)

    def copy(self):
        """Make a copy of self"""

        aCopy = self.__class__()
        aCopy.mip = self.mip
        aCopy.msg = self.msg
        aCopy.options = self.options
        return aCopy

    def solve(self, lp):
        """Solve the problem lp"""
        # Always go through the solve method of LpProblem
        return lp.solve(self)

    #TODO: Not sure if this code should be here or in a child class
    def getCplexStyleArrays(self,lp,
                       senseDict={LpConstraintEQ:"E", LpConstraintLE:"L", LpConstraintGE:"G"},
                       LpVarCategories = {LpContinuous: "C",LpInteger: "I"},
                       LpObjSenses = {LpMaximize : -1,
                                      LpMinimize : 1},
                       infBound =  1e20
                       ):
        """returns the arrays suitable to pass to a cdll Cplex
        or other solvers that are similar

        Copyright (c) Stuart Mitchell 2007
        """
        rangeCount = 0
        variables=list(lp.variables())
        numVars = len(variables)
        #associate each variable with a ordinal
        self.v2n=dict(((variables[i],i) for i in range(numVars)))
        self.vname2n=dict(((variables[i].name,i) for i in range(numVars)))
        self.n2v=dict((i,variables[i]) for i in range(numVars))
        #objective values
        objSense = LpObjSenses[lp.sense]
        NumVarDoubleArray = ctypes.c_double * numVars
        objectCoeffs=NumVarDoubleArray()
        #print "Get objective Values"
        for v,val in lp.objective.items():
            objectCoeffs[self.v2n[v]]=val
        #values for variables
        objectConst = ctypes.c_double(0.0)
        NumVarStrArray = ctypes.c_char_p * numVars
        colNames = NumVarStrArray()
        lowerBounds = NumVarDoubleArray()
        upperBounds = NumVarDoubleArray()
        initValues = NumVarDoubleArray()
        for v in lp.variables():
            colNames[self.v2n[v]] = str(v.name)
            initValues[self.v2n[v]] = 0.0
            if v.lowBound != None:
                lowerBounds[self.v2n[v]] = v.lowBound
            else:
                lowerBounds[self.v2n[v]] = -infBound
            if v.upBound != None:
                upperBounds[self.v2n[v]] = v.upBound
            else:
                upperBounds[self.v2n[v]] = infBound
        #values for constraints
        numRows =len(lp.constraints)
        NumRowDoubleArray = ctypes.c_double * numRows
        NumRowStrArray = ctypes.c_char_p * numRows
        NumRowCharArray = ctypes.c_char * numRows
        rhsValues = NumRowDoubleArray()
        rangeValues = NumRowDoubleArray()
        rowNames = NumRowStrArray()
        rowType = NumRowCharArray()
        self.c2n = {}
        self.n2c = {}
        i = 0
        for c in lp.constraints:
            rhsValues[i] = -lp.constraints[c].constant
            #for ranged constraints a<= constraint >=b
            rangeValues[i] = 0.0
            rowNames[i] = str(c)
            rowType[i] = senseDict[lp.constraints[c].sense]
            self.c2n[c] = i
            self.n2c[i] = c
            i = i+1
        #return the coefficient matrix as a series of vectors
        coeffs = lp.coefficients()
        sparseMatrix = sparse.Matrix(list(range(numRows)), list(range(numVars)))
        for var,row,coeff in coeffs:
            sparseMatrix.add(self.c2n[row], self.vname2n[var], coeff)
        (numels, mystartsBase, mylenBase, myindBase,
         myelemBase) = sparseMatrix.col_based_arrays()
        elemBase = ctypesArrayFill(myelemBase, ctypes.c_double)
        indBase = ctypesArrayFill(myindBase, ctypes.c_int)
        startsBase = ctypesArrayFill(mystartsBase, ctypes.c_int)
        lenBase = ctypesArrayFill(mylenBase, ctypes.c_int)
        #MIP Variables
        NumVarCharArray = ctypes.c_char * numVars
        columnType = NumVarCharArray()
        if lp.isMIP():
            for v in lp.variables():
                columnType[self.v2n[v]] = LpVarCategories[v.cat]
        self.addedVars = numVars
        self.addedRows = numRows
        return  (numVars, numRows, numels, rangeCount,
            objSense, objectCoeffs, objectConst,
            rhsValues, rangeValues, rowType, startsBase, lenBase, indBase,
            elemBase, lowerBounds, upperBounds, initValues, colNames,
            rowNames, columnType, self.n2v, self.n2c)


class LpSolver_CMD(LpSolver):
    """A generic command line LP Solver"""
    def __init__(self, path=None, keepFiles=0, mip=1, msg=1, options=[]):
        LpSolver.__init__(self, mip, msg, options)
        if path is None:
            self.path = self.defaultPath()
        else:
            self.path = path
        self.keepFiles = keepFiles
        self.setTmpDir()

    def copy(self):
        """Make a copy of self"""

        aCopy = LpSolver.copy(self)
        aCopy.path = self.path
        aCopy.keepFiles = self.keepFiles
        aCopy.tmpDir = self.tmpDir
        return aCopy

    def setTmpDir(self):
        """Set the tmpDir attribute to a reasonnable location for a temporary
        directory"""
        if os.name != 'nt':
            # On unix use /tmp by default
            self.tmpDir = os.environ.get("TMPDIR", "/tmp")
            self.tmpDir = os.environ.get("TMP", self.tmpDir)
        else:
            # On Windows use the current directory
            self.tmpDir = os.environ.get("TMPDIR", "")
            self.tmpDir = os.environ.get("TMP", self.tmpDir)
            self.tmpDir = os.environ.get("TEMP", self.tmpDir)
        if not os.path.isdir(self.tmpDir):
            self.tmpDir = ""
        elif not os.access(self.tmpDir, os.F_OK + os.W_OK):
            self.tmpDir = ""

    def defaultPath(self):
        raise NotImplementedError

    def executableExtension(name):
        if os.name != 'nt':
            return name
        else:
            return name+".exe"
    executableExtension = staticmethod(executableExtension)

    def executable(command):
        """Checks that the solver command is executable,
        And returns the actual path to it."""

        if os.path.isabs(command):
            if os.path.exists(command) and os.access(command, os.X_OK):
                return command
        for path in os.environ.get("PATH", []).split(os.pathsep):
            new_path = os.path.join(path, command)
            if os.path.exists(new_path) and os.access(new_path, os.X_OK):
                return os.path.join(path, command)
        return False
    executable = staticmethod(executable)

class GLPK_CMD(LpSolver_CMD):
    """The GLPK LP solver"""
    def defaultPath(self):
        return self.executableExtension(glpk_path)

    def available(self):
        """True if the solver is available"""
        return self.executable(self.path)

    def actualSolve(self, lp):
        """Solve a well formulated lp problem"""
        if not self.executable(self.path):
            raise PulpSolverError("PuLP: cannot execute "+self.path)
        if not self.keepFiles:
            pid = os.getpid()
            tmpLp = os.path.join(self.tmpDir, "%d-pulp.lp" % pid)
            tmpSol = os.path.join(self.tmpDir, "%d-pulp.sol" % pid)
        else:
            tmpLp = lp.name+"-pulp.lp"
            tmpSol = lp.name+"-pulp.sol"
        lp.writeLP(tmpLp, writeSOS = 0)
        proc = ["glpsol", "--cpxlp", tmpLp, "-o", tmpSol]
        if not self.mip: proc.append('--nomip')
        proc.extend(self.options)

        self.solution_time = clock()
        if not self.msg:
            proc[0] = self.path
            pipe = open(os.devnull, 'w')
            rc = subprocess.call(proc, stdout = pipe,
                             stderr = pipe)
            if rc:
                raise PulpSolverError("PuLP: Error while trying to execute "+self.path)
        else:
            if os.name != 'nt':
                rc = os.spawnvp(os.P_WAIT, self.path, proc)
            else:
                rc = os.spawnv(os.P_WAIT, self.executable(self.path), proc)
            if rc == 127:
                raise PulpSolverError("PuLP: Error while trying to execute "+self.path)
        self.solution_time += clock()

        if not os.path.exists(tmpSol):
            raise PulpSolverError("PuLP: Error while executing "+self.path)
        lp.status, values = self.readsol(tmpSol)
        lp.assignVarsVals(values)
        if not self.keepFiles:
            try: os.remove(tmpLp)
            except: pass
            try: os.remove(tmpSol)
            except: pass
        return lp.status

    def readsol(self,filename):
        """Read a GLPK solution file"""
        with open(filename) as f:
            f.readline()
            rows = int(f.readline().split()[1])
            cols = int(f.readline().split()[1])
            f.readline()
            statusString = f.readline()[12:-1]
            glpkStatus = {
                "INTEGER OPTIMAL":LpStatusOptimal,
                "INTEGER NON-OPTIMAL":LpStatusOptimal,
                "OPTIMAL":LpStatusOptimal,
                "INFEASIBLE (FINAL)":LpStatusInfeasible,
                "INTEGER UNDEFINED":LpStatusUndefined,
                "UNBOUNDED":LpStatusUnbounded,
                "UNDEFINED":LpStatusUndefined,
                "INTEGER EMPTY":LpStatusInfeasible
                }
            #print "statusString ",statusString
            if statusString not in glpkStatus:
                raise PulpSolverError("Unknown status returned by GLPK")
            status = glpkStatus[statusString]
            isInteger = statusString in ["INTEGER NON-OPTIMAL","INTEGER OPTIMAL","INTEGER UNDEFINED"]
            values = {}
            for i in range(4): f.readline()
            for i in range(rows):
                line = f.readline().split()
                if len(line) ==2: f.readline()
            for i in range(3):
                f.readline()
            for i in range(cols):
                line = f.readline().split()
                name = line[1]
                if len(line) ==2: line = [0,0]+f.readline().split()
                if isInteger:
                    if line[2] == "*": value = int(float(line[3]))
                    else: value = float(line[2])
                else:
                    value = float(line[3])
                values[name] = value
        return status, values
GLPK = GLPK_CMD

class CPLEX_CMD(LpSolver_CMD):
    """The CPLEX LP solver"""
    
    def __init__(self, path = None, keepFiles = 0, mip = 1,
            msg = 0, options = [], timelimit = None):
        LpSolver_CMD.__init__(self, path, keepFiles, mip, msg, options)
        self.timelimit = timelimit
    
    def defaultPath(self):
        return self.executableExtension("cplex")

    def available(self):
        """True if the solver is available"""
        return self.executable(self.path)

    def actualSolve(self, lp):
        """Solve a well formulated lp problem"""
        if not self.executable(self.path):
            raise PulpSolverError("PuLP: cannot execute "+self.path)
        if not self.keepFiles:
            pid = os.getpid()
            tmpLp = os.path.join(self.tmpDir, "%d-pulp.lp" % pid)
            tmpSol = os.path.join(self.tmpDir, "%d-pulp.sol" % pid)
        else:
            tmpLp = lp.name+"-pulp.lp"
            tmpSol = lp.name+"-pulp.sol"
        lp.writeLP(tmpLp, writeSOS = 1)
        try: os.remove(tmpSol)
        except: pass
        if not self.msg:
            cplex = subprocess.Popen(self.path, stdin = subprocess.PIPE,
                stdout = subprocess.PIPE, stderr = subprocess.PIPE)
        else:
            cplex = subprocess.Popen(self.path, stdin = subprocess.PIPE)
        cplex_cmds = "read "+tmpLp+"\n"
        if self.timelimit is not None:
            cplex_cmds += "set timelimit " + str(self.timelimit) + "\n"
        for option in self.options:
            cplex_cmds += option+"\n"
        if lp.isMIP():
            if self.mip:
                cplex_cmds += "mipopt\n"
                cplex_cmds += "change problem fixed\n"
            else:
                cplex_cmds += "change problem lp\n"

        cplex_cmds += "optimize\n"
        cplex_cmds += "write "+tmpSol+"\n"
        cplex_cmds += "quit\n"
        cplex_cmds = cplex_cmds.encode('UTF-8')
        cplex.communicate(cplex_cmds)
        if cplex.returncode != 0:
            raise PulpSolverError("PuLP: Error while trying to execute "+self.path)
        if not self.keepFiles:
            try: os.remove(tmpLp)
            except: pass
        if not os.path.exists(tmpSol):
            status = LpStatusInfeasible
        else:
            status, values, reducedCosts, shadowPrices, slacks = self.readsol(tmpSol)
        if not self.keepFiles:
            try: os.remove(tmpSol)
            except: pass
            try: os.remove("cplex.log")
            except: pass
        if status != LpStatusInfeasible:
            lp.assignVarsVals(values)
            lp.assignVarsDj(reducedCosts)
            lp.assignConsPi(shadowPrices)
            lp.assignConsSlack(slacks)
        lp.status = status
        return status

    def readsol(self,filename):
        """Read a CPLEX solution file"""
        try:
            import xml.etree.ElementTree as et
        except ImportError:
            import elementtree.ElementTree as et
        solutionXML = et.parse(filename).getroot()
        solutionheader = solutionXML.find("header")
        statusString = solutionheader.get("solutionStatusString")
        cplexStatus = {
            "optimal":LpStatusOptimal,
            }
        if statusString not in cplexStatus:
            raise PulpSolverError("Unknown status returned by CPLEX: "+statusString)
        status = cplexStatus[statusString]

        shadowPrices = {}
        slacks = {}
        shadowPrices = {}
        slacks = {}
        constraints = solutionXML.find("linearConstraints")
        for constraint in constraints:
                name = constraint.get("name")
                shadowPrice = constraint.get("dual")
                slack = constraint.get("slack")
                shadowPrices[name] = float(shadowPrice)
                slacks[name] = float(slack)

        values = {}
        reducedCosts = {}
        for variable in solutionXML.find("variables"):
                name = variable.get("name")
                value = variable.get("value")
                reducedCost = variable.get("reducedCost")
                values[name] = float(value)
                reducedCosts[name] = float(reducedCost)

        return status, values, reducedCosts, shadowPrices, slacks

def CPLEX_DLL_load_dll(path):
    """
    function that loads the DLL useful for debugging installation problems
    """
    import ctypes
    if os.name in ['nt','dos']:
        lib = ctypes.windll.LoadLibrary(path)
    else:
        lib = ctypes.cdll.LoadLibrary(path)
    return lib

try:
    import ctypes
    class CPLEX_DLL(LpSolver):
        """
        The CPLEX LP/MIP solver (via a Dynamic library DLL - windows or SO - Linux)

        This solver wraps the c library api of cplex.
        It has been tested against cplex 11.
        For api functions that have not been wrapped in this solver please use
        the ctypes library interface to the cplex api in CPLEX_DLL.lib
        """
        lib = CPLEX_DLL_load_dll(cplex_dll_path)
        #parameters manually found in solver manual
        CPX_PARAM_EPGAP = 2009
        CPX_PARAM_MEMORYEMPHASIS = 1082 # from Cplex 11.0 manual
        CPX_PARAM_TILIM = 1039
        CPX_PARAM_LPMETHOD = 1062
        #argtypes for CPLEX functions
        lib.CPXsetintparam.argtypes = [ctypes.c_void_p,
                         ctypes.c_int, ctypes.c_int]
        lib.CPXsetdblparam.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                ctypes.c_double]
        lib.CPXfopen.argtypes = [ctypes.c_char_p,
                                      ctypes.c_char_p]
        lib.CPXfopen.restype = ctypes.c_void_p
        lib.CPXsetlogfile.argtypes = [ctypes.c_void_p,
                                      ctypes.c_void_p]

        def __init__(self,
                    mip = True,
                    msg = True,
                    timeLimit = None,
                    epgap = None,
                    logfilename = None,
                    emphasizeMemory = False):
            """
            Initializes the CPLEX_DLL solver.

            @param mip: if False the solver will solve a MIP as an LP
            @param msg: displays information from the solver to stdout
            @param epgap: sets the integer bound gap
            @param logfilename: sets the filename of the cplex logfile
            @param emphasizeMemory: makes the solver emphasize Memory over
              solution time
            """
            LpSolver.__init__(self, mip, msg)
            self.timeLimit = timeLimit
            self.grabLicence()
            self.setMemoryEmphasis(emphasizeMemory)
            if epgap is not None:
                self.changeEpgap(epgap)
            if timeLimit is not None:
                self.setTimeLimit(timeLimit)
            if logfilename is not None:
                self.setlogfile(logfilename)
            else:
                self.logfile = None

        def setlogfile(self, filename):
            """
            sets the logfile for cplex output
            """
            self.logfilep = CPLEX_DLL.lib.CPXfopen(filename, "w")
            CPLEX_DLL.lib.CPXsetlogfile(self.env, self.logfilep)

        def changeEpgap(self, epgap = 10**-4):
            """
            Change cplex solver integer bound gap tolerence
            """
            CPLEX_DLL.lib.CPXsetdblparam(self.env,CPLEX_DLL.CPX_PARAM_EPGAP,
                                            epgap)

        def setLpAlgorithm(self, algo):
            """
            Select the LP algorithm to use.

            See your CPLEX manual for valid values of algo.  For CPLEX
            12.1 these are 0 for "automatic", 1 primal, 2 dual, 3 network, 4
            barrier, 5 sifting and 6 concurrent.  Currently the default setting
            0 always choooses dual simplex.
            """
            CPLEX_DLL.lib.CPXsetintparam(self.env,CPLEX_DLL.CPX_PARAM_LPMETHOD,
                                         algo)

        def setTimeLimit(self, timeLimit = 0.0):
            """
            Make cplex limit the time it takes --added CBM 8/28/09
            """
            CPLEX_DLL.lib.CPXsetdblparam(self.env,CPLEX_DLL.CPX_PARAM_TILIM,
                                                float(timeLimit))

        def setMemoryEmphasis(self, yesOrNo = False):
            """
            Make cplex try to conserve memory at the expense of
            performance.
            """
            CPLEX_DLL.lib.CPXsetintparam(self.env,
                            CPLEX_DLL.CPX_PARAM_MEMORYEMPHASIS,yesOrNo)

        def findSolutionValues(self, lp, numcols, numrows):
            byref = ctypes.byref
            solutionStatus = ctypes.c_int()
            objectiveValue = ctypes.c_double()
            x = (ctypes.c_double * numcols)()
            pi = (ctypes.c_double * numrows)()
            slack = (ctypes.c_double * numrows)()
            dj = (ctypes.c_double * numcols)()
            status= CPLEX_DLL.lib.CPXsolwrite(self.env, self.hprob,
                                                "CplexTest.sol")
            if lp.isMIP():
                solutionStatus.value = CPLEX_DLL.lib.CPXgetstat(self.env,
                                                                 self.hprob)
                status = CPLEX_DLL.lib.CPXgetobjval(self.env, self.hprob,
                                                    byref(objectiveValue))
                if status != 0 and status != 1217: #no solution exists
                    raise PulpSolverError("Error in CPXgetobjval status="
                                          + str(status))

                status = CPLEX_DLL.lib.CPXgetx(self.env, self.hprob,
                                                byref(x), 0, numcols - 1)
                if status != 0 and status != 1217:
                    raise PulpSolverError("Error in CPXgetx status=" + str(status))
            else:
                status = CPLEX_DLL.lib.CPXsolution(self.env, self.hprob,
                                              byref(solutionStatus),
                                              byref(objectiveValue),
                                              byref(x), byref(pi),
                                              byref(slack), byref(dj))
            # 102 is the cplex return status for
            # integer optimal within tolerance
            # and is useful for breaking symmetry.
            CplexLpStatus = {1: LpStatusOptimal, 3: LpStatusInfeasible,
                                  2: LpStatusUnbounded, 0: LpStatusNotSolved,
                                  101: LpStatusOptimal, 102: LpStatusOptimal,
                                  103: LpStatusInfeasible}
            #populate pulp solution values
            variablevalues = {}
            variabledjvalues = {}
            constraintpivalues = {}
            constraintslackvalues = {}
            for i in range(numcols):
                variablevalues[self.n2v[i].name] = x[i]
                variabledjvalues[self.n2v[i].name] = dj[i]
            lp.assignVarsVals(variablevalues)
            lp.assignVarsDj(variabledjvalues)
            #put pi and slack variables against the constraints
            for i in range(numrows):
                constraintpivalues[self.n2c[i]] = pi[i]
                constraintslackvalues[self.n2c[i]] = slack[i]
            lp.assignConsPi(constraintpivalues)
            lp.assignConsSlack(constraintslackvalues)
            #TODO: clear up the name of self.n2c
            if self.msg:
                print("Cplex status=", solutionStatus.value)
            lp.resolveOK = True
            for var in lp.variables():
                var.isModified = False
            lp.status = CplexLpStatus.get(solutionStatus.value,
                                          LpStatusUndefined)
            return lp.status

        def __del__(self):
            #LpSolver.__del__(self)
            self.releaseLicence()

        def available(self):
            """True if the solver is available"""
            return True

        def grabLicence(self):
            """
            Returns True if a CPLEX licence can be obtained.
            The licence is kept until releaseLicence() is called.
            """
            status = ctypes.c_int()
            # If the config file allows to do so (non null params), try to
            # grab a runtime license.
            if ilm_cplex_license and ilm_cplex_license_signature:
                runtime_status = CPLEX_DLL.lib.CPXsetstaringsol(
                        ilm_cplex_license,
                        ilm_cplex_license_signature)
                # if runtime_status is not zero, running with a runtime
                # license will fail. However, no error is thrown (yet)
                # because the second call might still succeed if the user
                # has another license. Let us forgive bad user
                # configuration:
                if not (runtime_status == 0) and self.msg:
                    print(
                    "CPLEX library failed to load the runtime license" +
                    "the call returned status=%s" % str(runtime_status) +
                    "Please check the pulp config file.")
            self.env = CPLEX_DLL.lib.CPXopenCPLEX(ctypes.byref(status))
            self.hprob = None
            if not(status.value == 0):
                raise PulpSolverError("CPLEX library failed on " +
                                    "CPXopenCPLEX status=" + str(status))


        def releaseLicence(self):
            """Release a previously obtained CPLEX licence"""
            if getattr(self,"env",False):
                status=CPLEX_DLL.lib.CPXcloseCPLEX(self.env)
                self.env = self.hprob = None
            else:
                raise PulpSolverError("No CPLEX enviroment to close")

        def callSolver(self, isMIP):
            """Solves the problem with cplex
            """
            #solve the problem
            self.cplexTime = -clock()
            if isMIP and self.mip:
                status= CPLEX_DLL.lib.CPXmipopt(self.env, self.hprob)
                if status != 0:
                    raise PulpSolverError("Error in CPXmipopt status="
                                        + str(status))
            else:
                status = CPLEX_DLL.lib.CPXlpopt(self.env, self.hprob)
                if status != 0:
                    raise PulpSolverError("Error in CPXlpopt status="
                                            + str(status))
            self.cplexTime += clock()

        def actualSolve(self, lp):
            """Solve a well formulated lp problem"""
            #TODO alter so that msg parameter is handled correctly
            status = ctypes.c_int()
            byref = ctypes.byref   #shortcut to function
            if self.hprob is not None:
                CPLEX_DLL.lib.CPXfreeprob(self.env, self.hprob)
            self.hprob = CPLEX_DLL.lib.CPXcreateprob(self.env,
                                                    byref(status), lp.name)
            if status.value != 0:
                raise PulpSolverError("Error in CPXcreateprob status="
                                    + str(status))
            (numcols, numrows, numels, rangeCount,
                objSense, obj, objconst,
                rhs, rangeValues, rowSense, matbeg, matcnt, matind,
                matval, lb, ub, initValues, colname,
                rowname, xctype, n2v, n2c )= self.getCplexStyleArrays(lp)
            status.value = CPLEX_DLL.lib.CPXcopylpwnames (self.env, self.hprob,
                                 numcols, numrows,
                                 objSense, obj, rhs, rowSense, matbeg, matcnt,
                                 matind, matval, lb, ub, None, colname, rowname)
            if status.value != 0:
                raise PulpSolverError("Error in CPXcopylpwnames status=" +
                                        str(status))
            if lp.isMIP() and self.mip:
                status.value = CPLEX_DLL.lib.CPXcopyctype(self.env,
                                                          self.hprob,
                                                          xctype)
            if status.value != 0:
                raise PulpSolverError("Error in CPXcopyctype status=" +
                                        str(status))
            #set the initial solution
            self.callSolver(lp.isMIP())
            #get the solution information
            solutionStatus = self.findSolutionValues(lp, numcols, numrows)
            for var in lp.variables():
                var.modified = False
            return solutionStatus


        def actualResolve(self,lp):
            """looks at which variables have been modified and changes them
            """
            #TODO: Add changing variables not just adding them
            #TODO: look at constraints
            modifiedVars = [var for var in lp.variables() if var.modified]
            #assumes that all variables flagged as modified
            #need to be added to the problem
            newVars = modifiedVars
            #print newVars
            self.v2n.update([(var, i+self.addedVars)
                                for i,var in enumerate(newVars)])
            self.n2v.update([(i+self.addedVars, var)
                                for i,var in enumerate(newVars)])
            self.vname2n.update([(var.name, i+self.addedVars)
                                for i,var in enumerate(newVars)])
            oldVars = self.addedVars
            self.addedVars += len(newVars)
            (ccnt,nzcnt,obj,cmatbeg,
            cmatlen, cmatind,cmatval,
            lb,ub, initvals,
            colname, coltype) = self.getSparseCols(newVars, lp, oldVars,
                                defBound = 1e20)
            CPXaddcolsStatus = CPLEX_DLL.lib.CPXaddcols(self.env, self.hprob,
                                          ccnt, nzcnt,
                                          obj,cmatbeg,
                                          cmatind,cmatval,
                                          lb,ub,colname)
            #add the column types
            if lp.isMIP() and self.mip:
                indices = (ctypes.c_int * len(newVars))()
                for i,var in enumerate(newVars):
                    indices[i] = oldVars +i
                CPXchgctypeStatus = CPLEX_DLL.lib.CPXchgctype (self.env,
                                                 self.hprob,
                                                 ccnt, indices, coltype);
            #solve the problem
            self.callSolver(lp.isMIP())
            #get the solution information
            solutionStatus = self.findSolutionValues(lp, self.addedVars,
                                                     self.addedRows)
            for var in modifiedVars:
                var.modified = False
            return solutionStatus

        def getSparseCols(self, vars, lp, offset = 0, defBound = 1e20):
            """
            outputs the variables in var as a sparse matrix,
            suitable for cplex and Coin

            Copyright (c) Stuart Mitchell 2007
            """
            numVars = len(vars)
            obj = (ctypes.c_double * numVars)()
            cmatbeg = (ctypes.c_int * numVars)()
            mycmatind = []
            mycmatval = []
            rangeCount = 0
            #values for variables
            colNames =  (ctypes.c_char_p * numVars)()
            lowerBounds =  (ctypes.c_double * numVars)()
            upperBounds =  (ctypes.c_double * numVars)()
            initValues =  (ctypes.c_double * numVars)()
            i=0
            for v in vars:
                colNames[i] = str(v.name)
                initValues[i] = v.init
                if v.lowBound != None:
                    lowerBounds[i] = v.lowBound
                else:
                    lowerBounds[i] = -defBound
                if v.upBound != None:
                    upperBounds[i] = v.upBound
                else:
                    upperBounds[i] = defBound
                i+= 1
                #create the new variables
            #values for constraints
            #return the coefficient matrix as a series of vectors
            myobjectCoeffs = {}
            numRows = len(lp.constraints)
            sparseMatrix = sparse.Matrix(list(range(numRows)), list(range(numVars)))
            for var in vars:
                for row,coeff in var.expression.items():
                   if row.name == lp.objective.name:
                        myobjectCoeffs[var] = coeff
                   else:
                        sparseMatrix.add(self.c2n[row.name], self.v2n[var] - offset, coeff)
            #objective values
            objectCoeffs = (ctypes.c_double * numVars)()
            for var in vars:
                objectCoeffs[self.v2n[var]-offset] = myobjectCoeffs[var]
            (numels, mystartsBase, mylenBase, myindBase,
             myelemBase) = sparseMatrix.col_based_arrays()
            elemBase = ctypesArrayFill(myelemBase, ctypes.c_double)
            indBase = ctypesArrayFill(myindBase, ctypes.c_int)
            startsBase = ctypesArrayFill(mystartsBase, ctypes.c_int)
            lenBase = ctypesArrayFill(mylenBase, ctypes.c_int)
            #MIP Variables
            NumVarCharArray = ctypes.c_char * numVars
            columnType = NumVarCharArray()
            if lp.isMIP():
                CplexLpCategories = {LpContinuous: "C",
                                    LpInteger: "I"}
                for v in vars:
                    columnType[self.v2n[v] - offset] = CplexLpCategories[v.cat]
            return  numVars, numels,  objectCoeffs, \
                startsBase, lenBase, indBase, \
                elemBase, lowerBounds, upperBounds, initValues, colNames, \
                columnType

        def objSa(self, vars = None):
            """Objective coefficient sensitivity analysis.

            Called after a problem has been solved, this function
            returns a dict mapping variables to pairs (lo, hi) indicating
            that the objective coefficient of the variable can vary
            between lo and hi without changing the optimal basis
            (if other coefficients remain constant).  If an iterable
            vars is given, results are returned only for variables in vars.
            """
            if vars is None:
                v2n = self.v2n
            else:
                v2n = dict((v, self.v2n[v]) for v in vars)
            ifirst = min(v2n.values())
            ilast = max(v2n.values())

            row_t = ctypes.c_double * (ilast - ifirst + 1)
            lo = row_t()
            hi = row_t()
            status = ctypes.c_int()
            status.value = CPLEX_DLL.lib.CPXobjsa(self.env, self.hprob,
                                                  ifirst, ilast, lo, hi)
            if status.value != 0:
                raise PulpSolverError("Error in CPXobjsa, status="
                                        + str(status))
            return dict((v, (lo[i - ifirst], hi[i - ifirst]))
                        for v, i in v2n.items())



    CPLEX = CPLEX_DLL
except (ImportError,OSError):
    class CPLEX_DLL(LpSolver):
        """The CPLEX LP/MIP solver PHANTOM Something went wrong!!!!"""
        def available(self):
            """True if the solver is available"""
            return False
        def actualSolve(self, lp):
            """Solve a well formulated lp problem"""
            raise PulpSolverError("CPLEX_DLL: Not Available")
    CPLEX = CPLEX_CMD

try:
    import cplex
except (ImportError):
    class CPLEX_PY(LpSolver):
        """The CPLEX LP/MIP solver from python PHANTOM Something went wrong!!!!"""
        def available(self):
            """True if the solver is available"""
            return False
        def actualSolve(self, lp):
            """Solve a well formulated lp problem"""
            raise PulpSolverError("CPLEX_PY: Not Available")
else:
    class CPLEX_PY(LpSolver):
        """
        The CPLEX LP/MIP solver (via a Python Binding)

        This solver wraps the python api of cplex.
        It has been tested against cplex 12.3.
        For api functions that have not been wrapped in this solver please use
        the base cplex classes
        """
        CplexLpStatus = {cplex.Cplex.solution.status.MIP_optimal: LpStatusOptimal,
                        cplex.Cplex.solution.status.optimal: LpStatusOptimal,
                        cplex.Cplex.solution.status.optimal_tolerance: LpStatusOptimal,
                        cplex.Cplex.solution.status.infeasible: LpStatusInfeasible,
                        cplex.Cplex.solution.status.infeasible_or_unbounded:  LpStatusInfeasible,
                        cplex.Cplex.solution.status.MIP_infeasible: LpStatusInfeasible,
                        cplex.Cplex.solution.status.MIP_infeasible_or_unbounded:  LpStatusInfeasible,
                        cplex.Cplex.solution.status.unbounded: LpStatusUnbounded,
                        cplex.Cplex.solution.status.MIP_unbounded: LpStatusUnbounded,
                        cplex.Cplex.solution.status.abort_dual_obj_limit: LpStatusNotSolved,
                        cplex.Cplex.solution.status.abort_iteration_limit: LpStatusNotSolved,
                        cplex.Cplex.solution.status.abort_obj_limit: LpStatusNotSolved,
                        cplex.Cplex.solution.status.abort_relaxed: LpStatusNotSolved,
                        cplex.Cplex.solution.status.abort_time_limit: LpStatusNotSolved,
                        cplex.Cplex.solution.status.abort_user: LpStatusNotSolved,
                        }

        def __init__(self,
                    mip = True,
                    msg = True,
                    timeLimit = None,
                    epgap = None,
                    logfilename = None):
            """
            Initializes the CPLEX_PY solver.

            @param mip: if False the solver will solve a MIP as an LP
            @param msg: displays information from the solver to stdout
            @param epgap: sets the integer bound gap
            @param logfilename: sets the filename of the cplex logfile
            """
            LpSolver.__init__(self, mip, msg)
            self.timeLimit = timeLimit
            self.epgap = epgap
            self.logfilename = logfilename

        def available(self):
            """True if the solver is available"""
            return True

        def actualSolve(self, lp, callback = None):
            """
            Solve a well formulated lp problem

            creates a cplex model, variables and constraints and attaches
            them to the lp model which it then solves
            """
            self.buildSolverModel(lp)
            #set the initial solution
            log.debug("Solve the Model using cplex")
            self.callSolver(lp)
            #get the solution information
            solutionStatus = self.findSolutionValues(lp)
            for var in lp.variables():
                var.modified = False
            for constraint in lp.constraints.values():
                constraint.modified = False
            return solutionStatus

        def buildSolverModel(self, lp):
            """
            Takes the pulp lp model and translates it into a cplex model
            """
            self.n2v = dict((var.name, var) for var in lp.variables())
            if len(self.n2v) != len(lp.variables()):
                raise PulpSolverError(
                        'Variables must have unique names for cplex solver')
            log.debug("create the cplex model")
            self.solverModel = lp.solverModel = cplex.Cplex()
            log.debug("set the name of the problem")
            if not self.mip:
                self.solverModel.set_problem_name(lp.name)
            log.debug("set the sense of the problem")
            if lp.sense == LpMaximize:
                lp.solverModel.objective.set_sense(
                                    lp.solverModel.objective.sense.maximize)
            obj = [float(lp.objective.get(var, 0.0)) for var in lp.variables()]
            def cplex_var_lb(var):
                if var.lowBound is not None:
                    return float(var.lowBound)
                else:
                    return -cplex.infinity
            lb = [cplex_var_lb(var) for var in lp.variables()]
            def cplex_var_ub(var):
                if var.upBound is not None:
                    return float(var.upBound)
                else:
                    return cplex.infinity
            ub = [cplex_var_ub(var) for var in lp.variables()]
            colnames = [var.name for var in lp.variables()]
            def cplex_var_types(var):
                if var.cat == LpInteger:
                    return 'I'
                else:
                    return 'C'
            ctype = [cplex_var_types(var) for var in lp.variables()]
            ctype = "".join(ctype)
            lp.solverModel.variables.add(obj=obj, lb=lb, ub=ub, types=ctype,
                       names=colnames)
            rows = []
            senses = []
            rhs = []
            rownames = []
            for name,constraint in lp.constraints.items():
                #build the expression
                expr = [(var.name, float(coeff)) for var, coeff in constraint.items()]
                if not expr:
                    #if the constraint is empty
                    rows.append(([],[]))
                else:
                    rows.append(list(zip(*expr)))
                if constraint.sense == LpConstraintLE:
                    senses.append('L')
                elif constraint.sense == LpConstraintGE:
                    senses.append('G')
                elif constraint.sense == LpConstraintEQ:
                    senses.append('E')
                else:
                    raise PulpSolverError('Detected an invalid constraint type')
                rownames.append(name)
                rhs.append(float(-constraint.constant))
            lp.solverModel.linear_constraints.add(lin_expr=rows, senses=senses,
                                rhs=rhs, names=rownames)
            log.debug("set the type of the problem")
            if not self.mip:
                self.solverModel.set_problem_type(cplex.Cplex.problem_type.LP)
            log.debug("set the logging")
            if not self.msg:
                self.solverModel.set_error_stream(None)
                self.solverModel.set_log_stream(None)
                self.solverModel.set_warning_stream(None)
                self.solverModel.set_results_stream(None)
            if self.logfilename is not None:
                self.setlogfile(self.logfilename)
            if self.epgap is not None:
                self.changeEpgap(self.epgap)
            if self.timeLimit is not None:
                self.setTimeLimit(self.timeLimit)

        def setlogfile(self, filename):
            """
            sets the logfile for cplex output
            """
            self.solverModel.set_log_stream(filename)

        def changeEpgap(self, epgap = 10**-4):
            """
            Change cplex solver integer bound gap tolerence
            """
            self.solverModel.parameters.mip.tolerances.mipgap.set(epgap)

        def setTimeLimit(self, timeLimit = 0.0):
            """
            Make cplex limit the time it takes --added CBM 8/28/09
            """
            self.solverModel.parameters.timelimit.set(timeLimit)

        def callSolver(self, isMIP):
            """Solves the problem with cplex
            """
            #solve the problem
            self.solveTime = -clock()
            self.solverModel.solve()
            self.solveTime += clock()

        def findSolutionValues(self, lp):
            lp.cplex_status = lp.solverModel.solution.get_status()
            lp.status = self.CplexLpStatus.get(lp.cplex_status, LpStatusUndefined)
            var_names = [var.name for var in lp.variables()]
            con_names = [con for con in lp.constraints]
            try:
                objectiveValue = lp.solverModel.solution.get_objective_value()
                variablevalues = dict(zip(var_names, lp.solverModel.solution.get_values(var_names)))
                lp.assignVarsVals(variablevalues)
                constraintslackvalues = dict(zip(con_names, lp.solverModel.solution.get_linear_slacks(con_names)))
                lp.assignConsSlack(constraintslackvalues)
                if lp.solverModel.get_problem_type == cplex.Cplex.problem_type.LP:
                    variabledjvalues = dict(zip(var_names, lp.solverModel.solution.get_reduced_costs(var_names)))
                    lp.assignVarsDj(variabledjvalues)
                    constraintpivalues = dict(zip(con_names, lp.solverModel.solution.get_dual_values(con_names)))
                    lp.assignConsPi(constraintpivalues)
            except cplex.exceptions.CplexSolverError:
                #raises this error when there is no solution
                pass
            #put pi and slack variables against the constraints
            #TODO: clear up the name of self.n2c
            if self.msg:
                print("Cplex status=", lp.cplex_status)
            lp.resolveOK = True
            for var in lp.variables():
                var.isModified = False
            return lp.status

        def actualResolve(self,lp):
            """
            looks at which variables have been modified and changes them
            """
            raise NotImplementedError("Resolves in CPLEX_PY not yet implemented")

    CPLEX = CPLEX_PY


class XPRESS(LpSolver_CMD):
    """The XPRESS LP solver"""
    def defaultPath(self):
        return self.executableExtension("optimizer")

    def available(self):
        """True if the solver is available"""
        return self.executable(self.path)

    def actualSolve(self, lp):
        """Solve a well formulated lp problem"""
        if not self.executable(self.path):
            raise PulpSolverError("PuLP: cannot execute "+self.path)
        if not self.keepFiles:
            pid = os.getpid()
            tmpLp = os.path.join(self.tmpDir, "%d-pulp.lp" % pid)
            tmpSol = os.path.join(self.tmpDir, "%d-pulp.prt" % pid)
        else:
            tmpLp = lp.name+"-pulp.lp"
            tmpSol = lp.name+"-pulp.prt"
        lp.writeLP(tmpLp, writeSOS = 1, mip = self.mip)
        if not self.msg:
            xpress = os.popen(self.path+" "+lp.name+" > /dev/null 2> /dev/null", "w")
        else:
            xpress = os.popen(self.path+" "+lp.name, "w")
        xpress.write("READPROB "+tmpLp+"\n")
        if lp.sense == LpMaximize:
            xpress.write("MAXIM\n")
        else:
            xpress.write("MINIM\n")
        if lp.isMIP() and self.mip:
            xpress.write("GLOBAL\n")
        xpress.write("WRITEPRTSOL "+tmpSol+"\n")
        xpress.write("QUIT\n")
        if xpress.close() != None:
            raise PulpSolverError("PuLP: Error while executing "+self.path)
        status, values = self.readsol(tmpSol)
        if not self.keepFiles:
            try: os.remove(tmpLp)
            except: pass
            try: os.remove(tmpSol)
            except: pass
        lp.status = status
        lp.assignVarsVals(values)
        if abs(lp.infeasibilityGap(self.mip)) > 1e-5: # Arbitrary
            lp.status = LpStatusInfeasible
        return lp.status

    def readsol(self,filename):
        """Read an XPRESS solution file"""
        with open(filename) as f:
            for i in range(6): f.readline()
            l = f.readline().split()

            rows = int(l[2])
            cols = int(l[5])
            for i in range(3): f.readline()
            statusString = f.readline().split()[0]
            xpressStatus = {
                "Optimal":LpStatusOptimal,
                }
            if statusString not in xpressStatus:
                raise PulpSolverError("Unknown status returned by XPRESS: "+statusString)
            status = xpressStatus[statusString]
            values = {}
            while 1:
                l = f.readline()
                if l == "": break
                line = l.split()
                if len(line) and line[0] == 'C':
                    name = line[2]
                    value = float(line[4])
                    values[name] = value
        return status, values

class COIN_CMD(LpSolver_CMD):
    """The COIN CLP/CBC LP solver
    now only uses cbc
    """

    def defaultPath(self):
        return self.executableExtension(cbc_path)

    def __init__(self, path = None, keepFiles = 0, mip = 1,
            msg = 0, cuts = None, presolve = None, dual = None,
            strong = None, options = [],
            fracGap = None, maxSeconds = None, threads = None):
        LpSolver_CMD.__init__(self, path, keepFiles, mip, msg, options)
        self.cuts = cuts
        self.presolve = presolve
        self.dual = dual
        self.strong = strong
        self.fracGap = fracGap
        self.maxSeconds = maxSeconds
        self.threads = threads
        #TODO hope this gets fixed in cbc as it does not like the c:\ in windows paths
        if os.name == 'nt':
            self.tmpDir = ''

    def copy(self):
        """Make a copy of self"""
        aCopy = LpSolver_CMD.copy(self)
        aCopy.cuts = self.cuts
        aCopy.presolve = self.presolve
        aCopy.dual = self.dual
        aCopy.strong = self.strong
        return aCopy

    def actualSolve(self, lp, **kwargs):
        """Solve a well formulated lp problem"""
        return self.solve_CBC(lp, **kwargs)

    def available(self):
        """True if the solver is available"""
        return self.executable(self.path)

    def solve_CBC(self, lp, use_mps=True):
        """Solve a MIP problem using CBC"""
        if not self.executable(self.path):
            raise PulpSolverError("Pulp: cannot execute %s cwd: %s"%(self.path,
                                   os.getcwd()))
        if not self.keepFiles:
            pid = os.getpid()
            tmpLp = os.path.join(self.tmpDir, "%d-pulp.lp" % pid)
            tmpMps = os.path.join(self.tmpDir, "%d-pulp.mps" % pid)
            tmpSol = os.path.join(self.tmpDir, "%d-pulp.sol" % pid)
        else:
            tmpLp = lp.name+"-pulp.lp"
            tmpMps = lp.name+"-pulp.mps"
            tmpSol = lp.name+"-pulp.sol"
        if use_mps:
            vs, variablesNames, constraintsNames, objectiveName = lp.writeMPS(
                        tmpMps, rename = 1)
            cmds = ' '+tmpMps+" "
            if lp.sense == LpMaximize:
                cmds += 'max '
        else:
            lp.writeLP(tmpLp)
            cmds = ' '+tmpLp+" "
        if self.threads:
            cmds += "threads %s "%self.threads
        if self.fracGap is not None:
            cmds += "ratio %s "%self.fracGap
        if self.maxSeconds is not None:
            cmds += "sec %s "%self.maxSeconds
        if self.presolve:
            cmds += "presolve on "
        if self.strong:
            cmds += "strong %d " % self.strong
        if self.cuts:
            cmds += "gomory on "
            #cbc.write("oddhole on "
            cmds += "knapsack on "
            cmds += "probing on "
        for option in self.options:
            cmds += option+" "
        if self.mip:
            cmds += "branch "
        else:
            cmds += "initialSolve "
        cmds += "printingOptions all "
        cmds += "solution "+tmpSol+" "
        if self.msg:
            pipe = None
        else:
            pipe = open(os.devnull, 'w')
        log.debug(self.path + cmds)
        cbc = subprocess.Popen((self.path + cmds).split(), stdout = pipe,
                             stderr = pipe)
        if cbc.wait() != 0:
            raise PulpSolverError("Pulp: Error while trying to execute " +  \
                                    self.path)
        if not os.path.exists(tmpSol):
            raise PulpSolverError("Pulp: Error while executing "+self.path)
        if use_mps:
            lp.status, values, reducedCosts, shadowPrices, slacks = self.readsol_MPS(
                        tmpSol, lp, lp.variables(),
                        variablesNames, constraintsNames, objectiveName)
        else:
            lp.status, values, reducedCosts, shadowPrices, slacks = self.readsol_LP(
                    tmpSol, lp, lp.variables())
        lp.assignVarsVals(values)
        lp.assignVarsDj(reducedCosts)
        lp.assignConsPi(shadowPrices)
        lp.assignConsSlack(slacks, activity=True)
        if not self.keepFiles:
            try:
                os.remove(tmpMps)
            except:
                pass
            try:
                os.remove(tmpLp)
            except:
                pass
            try:
                os.remove(tmpSol)
            except:
                pass
        return lp.status

    def readsol_MPS(self, filename, lp, vs, variablesNames, constraintsNames,
                objectiveName):
        """
        Read a CBC solution file generated from an mps file (different names)
        """
        values = {}

        reverseVn = {}
        for k, n in variablesNames.items():
            reverseVn[n] = k
        reverseCn = {}
        for k, n in constraintsNames.items():
            reverseCn[n] = k


        for v in vs:
            values[v.name] = 0.0

        reducedCosts = {}
        shadowPrices = {}
        slacks = {}
        cbcStatus = {'Optimal': LpStatusOptimal,
                    'Infeasible': LpStatusInfeasible,
                    'Unbounded': LpStatusUnbounded,
                    'Stopped': LpStatusNotSolved}
        with open(filename) as f:
            statusstr = f.readline().split()[0]
            status = cbcStatus.get(statusstr, LpStatusUndefined)
            for l in f:
                if len(l)<=2:
                    break
                l = l.split()
                #incase the solution is infeasible
                if l[0] == '**':
                    l = l[1:]
                vn = l[1]
                val = l[2]
                dj = l[3]
                if vn in reverseVn:
                    values[reverseVn[vn]] = float(val)
                    reducedCosts[reverseVn[vn]] = float(dj)
                if vn in reverseCn:
                    slacks[reverseCn[vn]] = float(val)
                    shadowPrices[reverseCn[vn]] = float(dj)
        return status, values, reducedCosts, shadowPrices, slacks

    def readsol_LP(self, filename, lp, vs):
        """
        Read a CBC solution file generated from an lp (good names)
        """
        values = {}
        reducedCosts = {}
        shadowPrices = {}
        slacks = {}
        for v in vs:
            values[v.name] = 0.0
        cbcStatus = {'Optimal': LpStatusOptimal,
                    'Infeasible': LpStatusInfeasible,
                    'Unbounded': LpStatusUnbounded,
                    'Stopped': LpStatusNotSolved}
        with open(filename) as f:
            statusstr = f.readline().split()[0]
            status = cbcStatus.get(statusstr, LpStatusUndefined)
            for l in f:
                if len(l)<=2:
                    break
                l = l.split()
                if l[0] == '**':
                    l = l[1:]
                vn = l[1]
                val = l[2]
                dj = l[3]
                if vn in values:
                    values[vn] = float(val)
                    reducedCosts[vn] = float(dj)
                if vn in lp.constraints:
                    slacks[vn] = float(val)
                    shadowPrices[vn] = float(dj)
        return status, values, reducedCosts, shadowPrices, slacks

COIN = COIN_CMD

class PULP_CBC_CMD(COIN_CMD):
    """
    This solver uses a precompiled version of cbc provided with the package
    """
    pulp_cbc_path = pulp_cbc_path
    try:
        if os.name != 'nt':
            if not os.access(pulp_cbc_path, os.X_OK):
                import stat
                os.chmod(pulp_cbc_path, stat.S_IXUSR + stat.S_IXOTH)
    except: #probably due to incorrect permissions
        def available(self):
            """True if the solver is available"""
            return False
        def actualSolve(self, lp, callback = None):
            """Solve a well formulated lp problem"""
            raise PulpSolverError("PULP_CBC_CMD: Not Available (check permissions on %s)" % self.pulp_cbc_path)
    else:
        def __init__(self, path=None, *args, **kwargs):
            """
            just loads up COIN_CMD with the path set
            """
            if path is not None:
                raise PulpSolverError('Use COIN_CMD if you want to set a path')
            #check that the file is executable
            COIN_CMD.__init__(self, path=self.pulp_cbc_path, *args, **kwargs)

def COINMP_DLL_load_dll(path):
    """
    function that loads the DLL useful for debugging installation problems
    """
    import ctypes
    if os.name == 'nt':
        lib = ctypes.windll.LoadLibrary(path[-1])
    else:
        #linux hack to get working
        mode = ctypes.RTLD_GLOBAL
        for libpath in path[:-1]:
            #RTLD_LAZY = 0x00001
            ctypes.CDLL(libpath, mode = mode)
        lib = ctypes.CDLL(path[-1], mode = mode)
    return lib

class COINMP_DLL(LpSolver):
    """
    The COIN_MP LP MIP solver (via a DLL or linux so)

    :param timeLimit: The number of seconds before forcing the solver to exit
    :param epgap: The fractional mip tolerance
    """
    try:
        lib = COINMP_DLL_load_dll(coinMP_path)
    except (ImportError, OSError):
        @classmethod
        def available(cls):
            """True if the solver is available"""
            return False
        def actualSolve(self, lp):
            """Solve a well formulated lp problem"""
            raise PulpSolverError("COINMP_DLL: Not Available")
    else:
        COIN_INT_LOGLEVEL = 7
        COIN_REAL_MAXSECONDS = 16
        COIN_REAL_MIPMAXSEC = 19
        COIN_REAL_MIPFRACGAP = 34
        lib.CoinGetInfinity.restype = ctypes.c_double
        lib.CoinGetVersionStr.restype = ctypes.c_char_p
        lib.CoinGetSolutionText.restype=ctypes.c_char_p
        lib.CoinGetObjectValue.restype=ctypes.c_double
        lib.CoinGetMipBestBound.restype=ctypes.c_double

        def __init__(self, mip = 1, msg = 1, cuts = 1, presolve = 1, dual = 1,
            crash = 0, scale = 1, rounding = 1, integerPresolve = 1, strong = 5,
            timeLimit = None, epgap = None):
            LpSolver.__init__(self, mip, msg)
            self.maxSeconds = None
            if timeLimit is not None:
                self.maxSeconds = float(timeLimit)
            self.fracGap = None
            if epgap is not None:
                self.fracGap = float(epgap)
            #Todo: these options are not yet implemented
            self.cuts = cuts
            self.presolve = presolve
            self.dual = dual
            self.crash = crash
            self.scale = scale
            self.rounding = rounding
            self.integerPresolve = integerPresolve
            self.strong = strong

        def copy(self):
            """Make a copy of self"""

            aCopy = LpSolver.copy()
            aCopy.cuts = self.cuts
            aCopy.presolve = self.presolve
            aCopy.dual = self.dual
            aCopy.crash = self.crash
            aCopy.scale = self.scale
            aCopy.rounding = self.rounding
            aCopy.integerPresolve = self.integerPresolve
            aCopy.strong = self.strong
            return aCopy

        @classmethod
        def available(cls):
            """True if the solver is available"""
            return True

        def getSolverVersion(self):
            """
            returns a solver version string

            example:
            >>> COINMP_DLL().getSolverVersion() # doctest: +ELLIPSIS
            '...'
            """
            return self.lib.CoinGetVersionStr()

        def actualSolve(self, lp):
            """Solve a well formulated lp problem"""
            #TODO alter so that msg parameter is handled correctly
            self.debug = 0
            #initialise solver
            self.lib.CoinInitSolver("")
            #create problem
            self.hProb = hProb = self.lib.CoinCreateProblem(lp.name);
            #set problem options
            if self.maxSeconds:
                if self.mip:
                    self.lib.CoinSetRealOption(hProb, self.COIN_REAL_MIPMAXSEC,
                                          ctypes.c_double(self.maxSeconds))
                else:
                    self.lib.CoinSetRealOption(hProb, self.COIN_REAL_MAXSECONDS,
                                          ctypes.c_double(self.maxSeconds))
            if self.fracGap:
               #Hopefully this is the bound gap tolerance
               self.lib.CoinSetRealOption(hProb, self.COIN_REAL_MIPFRACGAP,
                                          ctypes.c_double(self.fracGap))
            #CoinGetInfinity is needed for varibles with no bounds
            coinDblMax = self.lib.CoinGetInfinity()
            if self.debug: print("Before getCoinMPArrays")
            (numVars, numRows, numels, rangeCount,
                objectSense, objectCoeffs, objectConst,
                rhsValues, rangeValues, rowType, startsBase,
                lenBase, indBase,
                elemBase, lowerBounds, upperBounds, initValues, colNames,
                rowNames, columnType, n2v, n2c) = self.getCplexStyleArrays(lp)
            self.lib.CoinLoadProblem(hProb,
                                   numVars, numRows, numels, rangeCount,
                                   objectSense, objectConst, objectCoeffs,
                                   lowerBounds, upperBounds, rowType,
                                   rhsValues, rangeValues, startsBase,
                                   lenBase, indBase, elemBase,
                                   colNames, rowNames, "Objective")
            if lp.isMIP() and self.mip:
                self.lib.CoinLoadInteger(hProb,columnType)
            if self.msg == 0:
                #close stdout to get rid of messages
                tempfile = open(mktemp(),'w')
                savestdout = os.dup(1)
                os.close(1)
                if os.dup(tempfile.fileno()) != 1:
                    raise PulpSolverError("couldn't redirect stdout - dup() error")
            self.coinTime = -clock()
            self.lib.CoinOptimizeProblem(hProb, 0);
            self.coinTime += clock()

            if self.msg == 0:
                #reopen stdout
                os.close(1)
                os.dup(savestdout)
                os.close(savestdout)

            CoinLpStatus = {0:LpStatusOptimal,
                            1:LpStatusInfeasible,
                            2:LpStatusInfeasible,
                            3:LpStatusNotSolved,
                            4:LpStatusNotSolved,
                            5:LpStatusNotSolved,
                            -1:LpStatusUndefined
                            }
            solutionStatus = self.lib.CoinGetSolutionStatus(hProb)
            solutionText = self.lib.CoinGetSolutionText(hProb,solutionStatus)
            objectValue =  self.lib.CoinGetObjectValue(hProb)

            #get the solution values
            NumVarDoubleArray = ctypes.c_double * numVars
            NumRowsDoubleArray = ctypes.c_double * numRows
            cActivity = NumVarDoubleArray()
            cReducedCost = NumVarDoubleArray()
            cSlackValues = NumRowsDoubleArray()
            cShadowPrices = NumRowsDoubleArray()
            self.lib.CoinGetSolutionValues(hProb, ctypes.byref(cActivity),
                                         ctypes.byref(cReducedCost),
                                         ctypes.byref(cSlackValues),
                                         ctypes.byref(cShadowPrices))

            variablevalues = {}
            variabledjvalues = {}
            constraintpivalues = {}
            constraintslackvalues = {}
            if lp.isMIP() and self.mip:
                lp.bestBound = self.lib.CoinGetMipBestBound(hProb)
            for i in range(numVars):
                variablevalues[self.n2v[i].name] = cActivity[i]
                variabledjvalues[self.n2v[i].name] = cReducedCost[i]
            lp.assignVarsVals(variablevalues)
            lp.assignVarsDj(variabledjvalues)
            #put pi and slack variables against the constraints
            for i in range(numRows):
                constraintpivalues[self.n2c[i]] = cShadowPrices[i]
                constraintslackvalues[self.n2c[i]] = \
                    rhsValues[i] - cSlackValues[i]
            lp.assignConsPi(constraintpivalues)
            lp.assignConsSlack(constraintslackvalues)

            self.lib.CoinFreeSolver()
            lp.status = CoinLpStatus[self.lib.CoinGetSolutionStatus(hProb)]
            return lp.status

if COINMP_DLL.available():
    COIN = COINMP_DLL

# to import the gurobipy name into the module scope
gurobipy = None
class GUROBI(LpSolver):
    """
    The Gurobi LP/MIP solver (via its python interface)

    The Gurobi variables are available (after a solve) in var.solverVar
    Constriaints in constraint.solverConstraint
    and the Model is in prob.solverModel
    """
    try:
        sys.path.append(gurobi_path)
        # to import the name into the module scope
        global gurobipy
        import gurobipy
    except: #FIXME: Bug because gurobi returns
            #a gurobi exception on failed imports
        def available(self):
            """True if the solver is available"""
            return False
        def actualSolve(self, lp, callback = None):
            """Solve a well formulated lp problem"""
            raise PulpSolverError("GUROBI: Not Available")
    else:
        def __init__(self,
                    mip = True,
                    msg = True,
                    timeLimit = None,
                    epgap = None,
                    **solverParams):
            """
            Initializes the Gurobi solver.

            @param mip: if False the solver will solve a MIP as an LP
            @param msg: displays information from the solver to stdout
            @param timeLimit: sets the maximum time for solution
            @param epgap: sets the integer bound gap
            """
            LpSolver.__init__(self, mip, msg)
            self.timeLimit = timeLimit
            self.epgap = epgap
            #set the output of gurobi
            if not self.msg:
                gurobipy.setParam("OutputFlag", 0)
            #set the gurobi parameter values
            for key,value in solverParams.items():
                gurobipy.setParam(key, value)

        def findSolutionValues(self, lp):
            model = lp.solverModel
            solutionStatus = model.Status
            GRB = gurobipy.GRB
            gurobiLpStatus = {GRB.OPTIMAL: LpStatusOptimal,
                                   GRB.INFEASIBLE: LpStatusInfeasible,
                                   GRB.INF_OR_UNBD: LpStatusInfeasible,
                                   GRB.UNBOUNDED: LpStatusUnbounded,
                                   GRB.ITERATION_LIMIT: LpStatusNotSolved,
                                   GRB.NODE_LIMIT: LpStatusNotSolved,
                                   GRB.TIME_LIMIT: LpStatusNotSolved,
                                   GRB.SOLUTION_LIMIT: LpStatusNotSolved,
                                   GRB.INTERRUPTED: LpStatusNotSolved,
                                   GRB.NUMERIC: LpStatusNotSolved,
                                   }
            #populate pulp solution values
            for var in lp.variables():
                try:
                    var.varValue = var.solverVar.X
                except gurobipy.GurobiError:
                    pass
                try:
                    var.dj = var.solverVar.RC
                except gurobipy.GurobiError:
                    pass
            #put pi and slack variables against the constraints
            for constr in lp.constraints.values():
                try:
                    constr.pi = constr.solverConstraint.Pi
                except gurobipy.GurobiError:
                    pass
                try:
                    constr.slack = constr.solverConstraint.Slack
                except gurobipy.GurobiError:
                    pass
            if self.msg:
                print("Gurobi status=", solutionStatus)
            lp.resolveOK = True
            for var in lp.variables():
                var.isModified = False
            lp.status = gurobiLpStatus.get(solutionStatus, LpStatusUndefined)
            return lp.status

        def available(self):
            """True if the solver is available"""
            return True

        def callSolver(self, lp, callback = None):
            """Solves the problem with gurobi
            """
            #solve the problem
            self.solveTime = -clock()
            lp.solverModel.optimize(callback = callback)
            self.solveTime += clock()

        def buildSolverModel(self, lp):
            """
            Takes the pulp lp model and translates it into a gurobi model
            """
            log.debug("create the gurobi model")
            lp.solverModel = gurobipy.Model(lp.name)
            log.debug("set the sense of the problem")
            if lp.sense == LpMaximize:
                lp.solverModel.setAttr("ModelSense", -1)
            if self.timeLimit:
                lp.solverModel.setParam("TimeLimit", self.timeLimit)
            if self.epgap:
                lp.solverModel.setParam("MIPGap", self.epgap)
            log.debug("add the variables to the problem")
            for var in lp.variables():
                lowBound = var.lowBound
                if lowBound is None:
                    lowBound = -gurobipy.GRB.INFINITY
                upBound = var.upBound
                if upBound is None:
                    upBound = gurobipy.GRB.INFINITY
                obj = lp.objective.get(var, 0.0)
                varType = gurobipy.GRB.CONTINUOUS
                if var.cat == LpInteger and self.mip:
                    varType = gurobipy.GRB.INTEGER
                var.solverVar = lp.solverModel.addVar(lowBound, upBound,
                            vtype = varType,
                            obj = obj, name = var.name)
            lp.solverModel.update()
            log.debug("add the Constraints to the problem")
            for name,constraint in lp.constraints.items():
                #build the expression
                expr = gurobipy.LinExpr(list(constraint.values()),
                            [v.solverVar for v in constraint.keys()])
                if constraint.sense == LpConstraintLE:
                    relation = gurobipy.GRB.LESS_EQUAL
                elif constraint.sense == LpConstraintGE:
                    relation = gurobipy.GRB.GREATER_EQUAL
                elif constraint.sense == LpConstraintEQ:
                    relation = gurobipy.GRB.EQUAL
                else:
                    raise PulpSolverError('Detected an invalid constraint type')
                constraint.solverConstraint = lp.solverModel.addConstr(expr,
                    relation, -constraint.constant, name)
            lp.solverModel.update()

        def actualSolve(self, lp, callback = None):
            """
            Solve a well formulated lp problem

            creates a gurobi model, variables and constraints and attaches
            them to the lp model which it then solves
            """
            self.buildSolverModel(lp)
            #set the initial solution
            log.debug("Solve the Model using gurobi")
            self.callSolver(lp, callback = callback)
            #get the solution information
            solutionStatus = self.findSolutionValues(lp)
            for var in lp.variables():
                var.modified = False
            for constraint in lp.constraints.values():
                constraint.modified = False
            return solutionStatus

        def actualResolve(self, lp, callback = None):
            """
            Solve a well formulated lp problem

            uses the old solver and modifies the rhs of the modified constraints
            """
            log.debug("Resolve the Model using gurobi")
            for constraint in lp.constraints.values():
                if constraint.modified:
                    constraint.solverConstraint.setAttr(gurobipy.GRB.Attr.RHS,
                                                        -constraint.constant)
            lp.solverModel.update()
            self.callSolver(lp, callback = callback)
            #get the solution information
            solutionStatus = self.findSolutionValues(lp)
            for var in lp.variables():
                var.modified = False
            for constraint in lp.constraints.values():
                constraint.modified = False
            return solutionStatus

class GUROBI_CMD(LpSolver_CMD):
    """The GUROBI_CMD solver"""
    def defaultPath(self):
        return self.executableExtension("gurobi_cl")

    def available(self):
        """True if the solver is available"""
        return self.executable(self.path)

    def actualSolve(self, lp):
        """Solve a well formulated lp problem"""
        if not self.executable(self.path):
            raise PulpSolverError("PuLP: cannot execute "+self.path)
        if not self.keepFiles:
            pid = os.getpid()
            tmpLp = os.path.join(self.tmpDir, "%d-pulp.lp" % pid)
            tmpSol = os.path.join(self.tmpDir, "%d-pulp.sol" % pid)
        else:
            tmpLp = lp.name+"-pulp.lp"
            tmpSol = lp.name+"-pulp.sol"
        lp.writeLP(tmpLp, writeSOS = 1)
        try: os.remove(tmpSol)
        except: pass
        cmd = self.path
        cmd += ' ' + ' '.join(['%s=%s' % (key, value)
                    for key, value in self.options])
        cmd += ' ResultFile=%s' % tmpSol
        if lp.isMIP():
            if not self.mip:
                warnings.warn('GUROBI_CMD does not allow a problem to be relaxed')
        cmd += ' %s' % tmpLp
        if self.msg:
            pipe = None
        else:
            pipe = open(os.devnull, 'w')

        return_code = subprocess.call(cmd.split(), stdout = pipe, stderr = pipe)

        if return_code != 0:
            raise PulpSolverError("PuLP: Error while trying to execute "+self.path)
        if not self.keepFiles:
            try: os.remove(tmpLp)
            except: pass
        if not os.path.exists(tmpSol):
            warnings.warn('GUROBI_CMD does provide good solution status of non optimal solutions')
            status = LpStatusNotSolved
        else:
            status, values, reducedCosts, shadowPrices, slacks = self.readsol(tmpSol)
        if not self.keepFiles:
            try: os.remove(tmpSol)
            except: pass
            try: os.remove("gurobi.log")
            except: pass
        if status != LpStatusInfeasible:
            lp.assignVarsVals(values)
            lp.assignVarsDj(reducedCosts)
            lp.assignConsPi(shadowPrices)
            lp.assignConsSlack(slacks)
        lp.status = status
        return status

    def readsol(self, filename):
        """Read a Gurobi solution file"""
        with open(filename) as my_file:
            try:
                next(my_file) # skip the objective value
            except StopIteration:
                # Empty file not solved
                warnings.warn('GUROBI_CMD does provide good solution status of non optimal solutions')
                status = LpStatusNotSolved
                return status, {}, {}, {}, {}
            #We have no idea what the status is assume optimal
            status = LpStatusOptimal

            shadowPrices = {}
            slacks = {}
            shadowPrices = {}
            slacks = {}
            values = {}
            reducedCosts = {}
            for line in my_file:
                    name, value  = line.split()
                    values[name] = float(value)
        return status, values, reducedCosts, shadowPrices, slacks

#get the glpk name in global scope
glpk = None
class PYGLPK(LpSolver):
    """
    The glpk LP/MIP solver (via its python interface)

    Copyright Christophe-Marie Duquesne 2012

    The glpk variables are available (after a solve) in var.solverVar
    The glpk constraints are available in constraint.solverConstraint
    The Model is in prob.solverModel
    """
    try:
        #import the model into the global scope
        global glpk
        import glpk.glpkpi as glpk
    except:
        def available(self):
            """True if the solver is available"""
            return False
        def actualSolve(self, lp, callback = None):
            """Solve a well formulated lp problem"""
            raise PulpSolverError("GLPK: Not Available")
    else:
        def __init__(self,
                    mip = True,
                    msg = True,
                    timeLimit = None,
                    epgap = None,
                    **solverParams):
            """
            Initializes the glpk solver.

            @param mip: if False the solver will solve a MIP as an LP
            @param msg: displays information from the solver to stdout
            @param timeLimit: not handled
            @param epgap: not handled
            @param solverParams: not handled
            """
            LpSolver.__init__(self, mip, msg)
            if not self.msg:
                glpk.glp_term_out(glpk.GLP_OFF)

        def findSolutionValues(self, lp):
            prob = lp.solverModel
            if self.mip and self.hasMIPConstraints(lp.solverModel):
                solutionStatus = glpk.glp_mip_status(prob)
            else:
                solutionStatus = glpk.glp_get_status(prob)
            glpkLpStatus = {glpk.GLP_OPT: LpStatusOptimal,
                                   glpk.GLP_UNDEF: LpStatusUndefined,
                                   glpk.GLP_FEAS: LpStatusNotSolved,
                                   glpk.GLP_INFEAS: LpStatusInfeasible,
                                   glpk.GLP_NOFEAS: LpStatusInfeasible,
                                   glpk.GLP_UNBND: LpStatusUnbounded
                                   }
            #populate pulp solution values
            for var in lp.variables():
                if self.mip and self.hasMIPConstraints(lp.solverModel):
                    var.varValue = glpk.glp_mip_col_val(prob, var.glpk_index)
                else:
                    var.varValue = glpk.glp_get_col_prim(prob, var.glpk_index)
                var.dj = glpk.glp_get_col_dual(prob, var.glpk_index)
            #put pi and slack variables against the constraints
            for constr in lp.constraints.values():
                if self.mip and self.hasMIPConstraints(lp.solverModel):
                    row_val = glpk.glp_mip_row_val(prob, constr.glpk_index)
                else:
                    row_val = glpk.glp_get_row_prim(prob, constr.glpk_index)
                constr.slack = -constr.constant - row_val
                constr.pi = glpk.glp_get_row_dual(prob, constr.glpk_index)
            lp.resolveOK = True
            for var in lp.variables():
                var.isModified = False
            lp.status = glpkLpStatus.get(solutionStatus,
                    LpStatusUndefined)
            return lp.status

        def available(self):
            """True if the solver is available"""
            return True

        def hasMIPConstraints(self, solverModel):
            return (glpk.glp_get_num_int(solverModel) > 0 or
                    glpk.glp_get_num_bin(solverModel) > 0)

        def callSolver(self, lp, callback = None):
            """Solves the problem with glpk
            """
            self.solveTime = -clock()
            glpk.glp_adv_basis(lp.solverModel, 0)
            glpk.glp_simplex(lp.solverModel, None)
            if self.mip and self.hasMIPConstraints(lp.solverModel):
                status = glpk.glp_get_status(lp.solverModel)
                if status in (glpk.GLP_OPT, glpk.GLP_UNDEF, glpk.GLP_FEAS):
                    glpk.glp_intopt(lp.solverModel, None)
            self.solveTime += clock()

        def buildSolverModel(self, lp):
            """
            Takes the pulp lp model and translates it into a glpk model
            """
            log.debug("create the glpk model")
            prob = glpk.glp_create_prob()
            glpk.glp_set_prob_name(prob, lp.name)
            log.debug("set the sense of the problem")
            if lp.sense == LpMaximize:
                glpk.glp_set_obj_dir(prob, glpk.GLP_MAX)
            log.debug("add the constraints to the problem")
            glpk.glp_add_rows(prob, len(list(lp.constraints.keys())))
            for i, v in enumerate(lp.constraints.items(), start=1):
                name, constraint = v
                glpk.glp_set_row_name(prob, i, name)
                if constraint.sense == LpConstraintLE:
                    glpk.glp_set_row_bnds(prob, i, glpk.GLP_UP,
                            0.0, -constraint.constant)
                elif constraint.sense == LpConstraintGE:
                    glpk.glp_set_row_bnds(prob, i, glpk.GLP_LO,
                            -constraint.constant, 0.0)
                elif constraint.sense == LpConstraintEQ:
                    glpk.glp_set_row_bnds(prob, i, glpk.GLP_FX,
                            -constraint.constant, -constraint.constant)
                else:
                    raise PulpSolverError('Detected an invalid constraint type')
                constraint.glpk_index = i
            log.debug("add the variables to the problem")
            glpk.glp_add_cols(prob, len(lp.variables()))
            for j, var in enumerate(lp.variables(), start=1):
                glpk.glp_set_col_name(prob, j, var.name)
                lb = 0.0
                ub = 0.0
                t = glpk.GLP_FR
                if not var.lowBound is None:
                    lb = var.lowBound
                    t = glpk.GLP_LO
                if not var.upBound is None:
                    ub = var.upBound
                    t = glpk.GLP_UP
                if not var.upBound is None and not var.lowBound is None:
                    if ub == lb:
                        t = glpk.GLP_FX
                    else:
                        t = glpk.GLP_DB
                glpk.glp_set_col_bnds(prob, j, t, lb, ub)
                if var.cat == LpInteger:
                    glpk.glp_set_col_kind(prob, j, glpk.GLP_IV)
                    assert glpk.glp_get_col_kind(prob, j) == glpk.GLP_IV
                var.glpk_index = j
            log.debug("set the objective function")
            for var in lp.variables():
                value = lp.objective.get(var)
                if value:
                    glpk.glp_set_obj_coef(prob, var.glpk_index, value)
            log.debug("set the problem matrix")
            for constraint in lp.constraints.values():
                l = len(list(constraint.items()))
                ind = glpk.intArray(l + 1)
                val = glpk.doubleArray(l + 1)
                for j, v in enumerate(constraint.items(), start=1):
                    var, value = v
                    ind[j] = var.glpk_index
                    val[j] = value
                glpk.glp_set_mat_row(prob, constraint.glpk_index, l, ind,
                        val)
            lp.solverModel = prob
            #glpk.glp_write_lp(prob, None, "glpk.lp")

        def actualSolve(self, lp, callback = None):
            """
            Solve a well formulated lp problem

            creates a glpk model, variables and constraints and attaches
            them to the lp model which it then solves
            """
            self.buildSolverModel(lp)
            #set the initial solution
            log.debug("Solve the Model using glpk")
            self.callSolver(lp, callback = callback)
            #get the solution information
            solutionStatus = self.findSolutionValues(lp)
            for var in lp.variables():
                var.modified = False
            for constraint in lp.constraints.values():
                constraint.modified = False
            return solutionStatus

        def actualResolve(self, lp, callback = None):
            """
            Solve a well formulated lp problem

            uses the old solver and modifies the rhs of the modified
            constraints
            """
            log.debug("Resolve the Model using glpk")
            for constraint in lp.constraints.values():
                i = constraint.glpk_index
                if constraint.modified:
                    if constraint.sense == LpConstraintLE:
                        glpk.glp_set_row_bnds(prob, i, glpk.GLP_UP,
                                0.0, -constraint.constant)
                    elif constraint.sense == LpConstraintGE:
                        glpk.glp_set_row_bnds(prob, i, glpk.GLP_LO,
                                -constraint.constant, 0.0)
                    elif constraint.sense == LpConstraintEQ:
                        glpk.glp_set_row_bnds(prob, i, glpk.GLP_FX,
                                -constraint.constant, -constraint.constant)
                    else:
                        raise PulpSolverError('Detected an invalid constraint type')
            self.callSolver(lp, callback = callback)
            #get the solution information
            solutionStatus = self.findSolutionValues(lp)
            for var in lp.variables():
                var.modified = False
            for constraint in lp.constraints.values():
                constraint.modified = False
            return solutionStatus

yaposib = None
class YAPOSIB(LpSolver):
    """
    COIN OSI (via its python interface)

    Copyright Christophe-Marie Duquesne 2012

    The yaposib variables are available (after a solve) in var.solverVar
    The yaposib constraints are available in constraint.solverConstraint
    The Model is in prob.solverModel
    """
    try:
        #import the model into the global scope
        global yaposib
        import yaposib
    except ImportError:
        def available(self):
            """True if the solver is available"""
            return False
        def actualSolve(self, lp, callback = None):
            """Solve a well formulated lp problem"""
            raise PulpSolverError("YAPOSIB: Not Available")
    else:
        def __init__(self,
                    mip = True,
                    msg = True,
                    timeLimit = None,
                    epgap = None,
                    solverName = None,
                    **solverParams):
            """
            Initializes the yaposib solver.

            @param mip:          if False the solver will solve a MIP as
                                 an LP
            @param msg:          displays information from the solver to
                                 stdout
            @param timeLimit:    not supported
            @param epgap:        not supported
            @param solverParams: not supported
            """
            LpSolver.__init__(self, mip, msg)
            if solverName:
                self.solverName = solverName
            else:
                self.solverName = yaposib.available_solvers()[0]

        def findSolutionValues(self, lp):
            model = lp.solverModel
            solutionStatus = model.status
            yaposibLpStatus = {"optimal": LpStatusOptimal,
                                   "undefined": LpStatusUndefined,
                                   "abandoned": LpStatusInfeasible,
                                   "infeasible": LpStatusInfeasible,
                                   "limitreached": LpStatusInfeasible
                                   }
            #populate pulp solution values
            for var in lp.variables():
                var.varValue = var.solverVar.solution
                var.dj = var.solverVar.reducedcost
            #put pi and slack variables against the constraints
            for constr in lp.constraints.values():
                constr.pi = constr.solverConstraint.dual
                constr.slack = -constr.constant - constr.solverConstraint.activity
            if self.msg:
                print("yaposib status=", solutionStatus)
            lp.resolveOK = True
            for var in lp.variables():
                var.isModified = False
            lp.status = yaposibLpStatus.get(solutionStatus,
                    LpStatusUndefined)
            return lp.status

        def available(self):
            """True if the solver is available"""
            return True

        def callSolver(self, lp, callback = None):
            """Solves the problem with yaposib
            """
            if self.msg == 0:
                #close stdout to get rid of messages
                tempfile = open(mktemp(),'w')
                savestdout = os.dup(1)
                os.close(1)
                if os.dup(tempfile.fileno()) != 1:
                    raise PulpSolverError("couldn't redirect stdout - dup() error")
            self.solveTime = -clock()
            lp.solverModel.solve(self.mip)
            self.solveTime += clock()
            if self.msg == 0:
                #reopen stdout
                os.close(1)
                os.dup(savestdout)
                os.close(savestdout)

        def buildSolverModel(self, lp):
            """
            Takes the pulp lp model and translates it into a yaposib model
            """
            log.debug("create the yaposib model")
            lp.solverModel = yaposib.Problem(self.solverName)
            prob = lp.solverModel
            prob.name = lp.name
            log.debug("set the sense of the problem")
            if lp.sense == LpMaximize:
                prob.obj.maximize = True
            log.debug("add the variables to the problem")
            for var in lp.variables():
                col = prob.cols.add(yaposib.vec([]))
                col.name = var.name
                if not var.lowBound is None:
                    col.lowerbound = var.lowBound
                if not var.upBound is None:
                    col.upperbound = var.upBound
                if var.cat == LpInteger:
                    col.integer = True
                prob.obj[col.index] = lp.objective.get(var, 0.0)
                var.solverVar = col
            log.debug("add the Constraints to the problem")
            for name, constraint in lp.constraints.items():
                row = prob.rows.add(yaposib.vec([(var.solverVar.index,
                    value) for var, value in constraint.items()]))
                if constraint.sense == LpConstraintLE:
                    row.upperbound = -constraint.constant
                elif constraint.sense == LpConstraintGE:
                    row.lowerbound = -constraint.constant
                elif constraint.sense == LpConstraintEQ:
                    row.upperbound = -constraint.constant
                    row.lowerbound = -constraint.constant
                else:
                    raise PulpSolverError('Detected an invalid constraint type')
                row.name = name
                constraint.solverConstraint = row

        def actualSolve(self, lp, callback = None):
            """
            Solve a well formulated lp problem

            creates a yaposib model, variables and constraints and attaches
            them to the lp model which it then solves
            """
            self.buildSolverModel(lp)
            #set the initial solution
            log.debug("Solve the model using yaposib")
            self.callSolver(lp, callback = callback)
            #get the solution information
            solutionStatus = self.findSolutionValues(lp)
            for var in lp.variables():
                var.modified = False
            for constraint in lp.constraints.values():
                constraint.modified = False
            return solutionStatus

        def actualResolve(self, lp, callback = None):
            """
            Solve a well formulated lp problem

            uses the old solver and modifies the rhs of the modified
            constraints
            """
            log.debug("Resolve the model using yaposib")
            for constraint in lp.constraints.values():
                row = constraint.solverConstraint
                if constraint.modified:
                    if constraint.sense == LpConstraintLE:
                        row.upperbound = -constraint.constant
                    elif constraint.sense == LpConstraintGE:
                        row.lowerbound = -constraint.constant
                    elif constraint.sense == LpConstraintEQ:
                        row.upperbound = -constraint.constant
                        row.lowerbound = -constraint.constant
                    else:
                        raise PulpSolverError('Detected an invalid constraint type')
            self.callSolver(lp, callback = callback)
            #get the solution information
            solutionStatus = self.findSolutionValues(lp)
            for var in lp.variables():
                var.modified = False
            for constraint in lp.constraints.values():
                constraint.modified = False
            return solutionStatus

try:
    import ctypes
    def ctypesArrayFill(myList, type=ctypes.c_double):
        """
        Creates a c array with ctypes from a python list
        type is the type of the c array
        """
        ctype= type * len(myList)
        cList = ctype()
        for i,elem in enumerate(myList):
            cList[i] = elem
        return cList
except(ImportError):
    def ctypesArrayFill(myList, type = None):
        return None

class GurobiFormulation(object):
    """
    The Gurobi LP/MIP solver (via its python interface)
    without holding our own copy of the constraints

    Contributed by  Ben Hollis<ben.hollis@polymathian.com>

    This is an experimental interface that implements some of the
    LpProblem interface, this should probably be done with an ABC
    Also needs tests
    """
    try:
        sys.path.append(gurobi_path)
        global gurobipy
        import gurobipy
    except:
        def __init__(self, sense):
            raise PulpSolverError("GUROBI: Not Available")
    else:

        def __init__(self, name, sense):
            self.gurobi_model = gurobipy.Model(name)
            self.sense = sense
            if sense == LpMaximize:
                self.gurobi_model.setAttr("ModelSense", -1)
            self.varables = {}
            self.objective = None
            self.status = None

        def addVariable(self, v):
            if v.name not in self.varables:
                self.varables[v.name] = v
                lower_bound = v.getLb()
                if lower_bound is None:
                    lower_bound = -gurobipy.GRB.INFINITY
                upper_bound = v.getUb()
                if upper_bound is None:
                    upper_bound = gurobipy.GRB.INFINITY
                varType = gurobipy.GRB.CONTINUOUS
                if v.isInteger():
                    varType = gurobipy.GRB.INTEGER
                v.solver_var = self.gurobi_model.addVar(lower_bound, upper_bound, vtype = varType, obj = 0, name = v.name)
                return v

        def update(self):
            self.gurobi_model.update()

        def numVariables(self):
            return self.gurobi_model.getAttr('NumVars')

        def numConstraints(self):
            return self.gurobi_model.getAttr('NumConstrs')

        def getSense(self):
            return self.sense

        def addVariables(self, variables):
            [self.addVariable(v) for v in variables]

        def add(self, constraint, name = None):
            self.addConstraint(constraint, name)

        def solve(self, callback = None):
            print("***Solving using thin Gurobi Formulation")
            self.gurobi_model.reset()
            for var, coeff in self.objective.items():
                var.solver_var.setAttr("Obj", coeff)
            self.gurobi_model.optimize(callback = callback)
            return self.findSolutionValues()

        def findSolutionValues(self):
            for var in self.varables.values():
                try:
                    var.varValue = var.solver_var.X
                except gurobipy.GurobiError:
                    pass
            GRB = gurobipy.GRB
            gurobiLPStatus = {
                GRB.OPTIMAL: LpStatusOptimal,
                GRB.INFEASIBLE: LpStatusInfeasible,
                GRB.INF_OR_UNBD: LpStatusInfeasible,
                GRB.UNBOUNDED: LpStatusUnbounded,
                GRB.ITERATION_LIMIT: LpStatusNotSolved,
                GRB.NODE_LIMIT: LpStatusNotSolved,
                GRB.TIME_LIMIT: LpStatusNotSolved,
                GRB.SOLUTION_LIMIT: LpStatusNotSolved,
                GRB.INTERRUPTED: LpStatusNotSolved,
                GRB.NUMERIC: LpStatusNotSolved,
            }
            self.status = gurobiLPStatus.get(self.gurobi_model.Status, LpStatusUndefined)
            return self.status

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
            #if self._addVariables(constraint.keys()):
                #self.gurobi_model.update()


            expr = gurobipy.LinExpr(constraint.values(), [v.solver_var for v in constraint.keys()])  # Solver_var is added inside addVariable
            if constraint.sense == LpConstraintLE:
                relation = gurobipy.GRB.LESS_EQUAL
            elif constraint.sense == LpConstraintGE:
                relation = gurobipy.GRB.GREATER_EQUAL
            elif constraint.sense == LpConstraintEQ:
                relation = gurobipy.GRB.EQUAL
            else:
                raise PulpSolverError('Detected an invalid constraint type')
            self.gurobi_model.addConstr(expr, relation, -constraint.constant, name)

        def __iadd__(self, other):
            if isinstance(other, tuple):
                other, name = other
            else:
                name = None
            if other is True:
                return self
            elif isinstance(other, LpConstraint):
                self.addConstraint(other, name)
            elif isinstance(other, LpAffineExpression):
                self.objective = other
                self.objective.name = name
            elif isinstance(other, LpVariable) or isinstance(other, (int, float)):
                self.objective = LpAffineExpression(other)
                self.objective.name = name
            else:
                raise TypeError("Can only add LpConstraint, LpAffineExpression or True objects")
            return self
