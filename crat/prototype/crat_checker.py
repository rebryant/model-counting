#!/usr/bin/python3

#####################################################################################
# Copyright (c) 2021 Marijn Heule, Randal E. Bryant, Carnegie Mellon University
# Last edit: Feb. 16, 2021
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
# associated documentation files (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge, publish, distribute,
# sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all copies or
# substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
# NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
# DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT
# OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
########################################################################################


# Checker for CRAT schema.
import sys
import getopt
import datetime

def usage(name):
    print("Usage: %s [-v] -i FILE.cnf -p FILE.crat [-w W1:W2:...:Wn]" % name)
    print("   -v         Print more helpful diagnostic information if there is an error")
    print("   -w WEIGHTS Provide colon-separated set of input weights.")
    print("              Each should be between 0 and 100 (will be scaled by 1/100)")

######################################################################################
# CRAT Syntax
######################################################################################
# Notation
#  Id: Clause Id
#  Var: Variable
#  Lit: Literal +/- Var

# Lit*: Clause consisting of specified literals
# HINT: Either Id+ or *

# Id  i [Lit*] 0             -- Input clause
# Id  a [Lit*] 0    HINT 0   -- RUP clause addition
#    dc Id          HINT 0   -- RUP clause deletion
# Id  p Var Lit Lit          -- And operation
# Id  a Var Lit Lit HINT 0   -- Or operation
#    do Var                  -- Operation deletion

######################################################################################

# Global variable.  Set to False if cut corners in check
fullProof = True


def trim(s):
    while len(s) > 0 and s[-1] in ' \r\n\t':
        s = s[:-1]
    return s

# Clean up clause.
# Remove duplicates
# Sort in reverse order of variable number
# Don't allow clause to have opposite literals
def cleanClause(literalList):
    slist = sorted(literalList, key = lambda v: -abs(v))
    if len(slist) <= 1:
        return slist
    nlist = [slist[0]]
    for i in range(1, len(slist)):
        if slist[i-1] == slist[i]:
            continue
        if slist[i-1] == -slist[i]:
            return None
        nlist.append(slist[i])
    return nlist

def regularClause(clause):
    return clause is not None

def showClause(clause):
    if clause is None:
        return "NONE"
    return str(clause)

class RupException(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return "RUP Exception: " + str(self.value)


# Clause comparison.  Assumes both have been processed by cleanClause
def testClauseEquality(clause1, clause2):
    if clause1 is None or clause2 is None:
        return False
    if len(clause1) != len(clause2):
        return False
    for l1, l2 in zip(clause1, clause2):
        if l1 != l2:
            return False
    return True

# Read CNF file.
# Save list of clauses, each is a list of literals (zero at end removed)
class CnfReader():
    file = None
    clauses = []
    # List of input variables.
    nvar = 0
    failed = False
    errorMessage = ""
    
    def __init__(self, fname):
        self.failed = False
        self.errorMessage = ""
        try:
            self.file = open(fname, 'r')
        except Exception:
            self.fail("Could not open file '%s'" % fname)
            return
        self.readCnf()
        print("Read %d clauses from file %s" % (len(self.clauses), fname))
        self.file.close()
        
    def fail(self, msg):
        self.failed = True
        self.errorMessage = msg

    def readCnf(self):
        self.nvar = 0
        lineNumber = 0
        nclause = 0
        clauseCount = 0
        for line in self.file:
            lineNumber += 1
            line = trim(line)
            if len(line) == 0:
                continue
            elif line[0] == 'c':
                pass
            elif line[0] == 'p':
                fields = line[1:].split()
                if fields[0] != 'cnf':
                    self.fail("Line %d.  Bad header line '%s'.  Not cnf" % (lineNumber, line))
                    return
                try:
                    self.nvar = int(fields[1])
                    nclause = int(fields[2])
                except Exception:
                    self.fail("Line %d.  Bad header line '%s'.  Invalid number of variables or clauses" % (lineNumber, line))
                    return
            else:
                if nclause == 0:
                    self.fail("Line %d.  No header line.  Not cnf" % (lineNumber))
                    return
                # Check formatting
                try:
                    lits = [int(s) for s in line.split()]
                except:
                    self.fail("Line %d.  Non-integer field" % lineNumber)
                    return
                # Last one should be 0
                if lits[-1] != 0:
                    self.fail("Line %d.  Clause line should end with 0" % lineNumber)
                    return
                lits = lits[:-1]
                vars = sorted([abs(l) for l in lits])
                if len(vars) == 0:
                    self.fail("Line %d.  Empty clause" % lineNumber)                    
                    return
                if vars[-1] > self.nvar or vars[0] == 0:
                    self.fail("Line %d.  Out-of-range literal" % lineNumber)
                    return
                for i in range(len(vars) - 1):
                    if vars[i] == vars[i+1]:
                        self.fail("Line %d.  Opposite or repeated literal" % lineNumber)
                        return
                self.clauses.append(lits)
                clauseCount += 1
        if clauseCount != nclause:
            self.fail("Line %d: Got %d clauses.  Expected %d" % (lineNumber, clauseCount, nclause))
            return


# Clause processing
class ClauseManager:
    # Number of input clauses
    inputClauseCount = 0
    # Mapping from Id to clause.  Deleted clauses represented by None
    clauseDict = {}
    # For each literal, count of clauses containing it
    literalCountDict = {}
    # For each literal, set of clauses containing it (only in verbose mode)
    literalSetDict = {}
    # Track whether have empty clause
    addedEmpty = False
    # Counters
    liveClauseCount = 0
    maxLiveClauseCount = 0
    totalClauseCount = 0
    # Maximum clause ID.  Used to ensure ascending order
    maxClauseId = 0
    # Clauses that haven't been deleted (only in verbose mode)
    liveClauseSet = set([])
    # Final root node
    root = None

    def __init__(self, verbose, clauseCount):
        self.inputClauseCount = clauseCount
        self.verbose = verbose
        self.clauseDict = {}
        self.literalCountDict = {}
        self.literalSetDict = {}
        self.addedEmpty = False
        self.liveClauseCount = 0
        self.maxLiveClauseCount = 0
        self.totalClauseCount = 0
        self.liveClauseSet = set([])
        self.root = None

    def findClause(self, id):
        if id not in self.clauseDict:
            return (None, "Clause #%d never defined" % id)
        elif self.clauseDict[id] is None:
            return (None, "Clause #%d has been deleted" % id)
        else:
            return (self.clauseDict[id], "")

    # Add clause.  Should have been processed with cleanClause
    # Return (T/F, reason)
    def addClause(self, clause, id):
        if not regularClause(clause):
            return (False, "Cannot add clause %s" % showClause(clause))
        if id <= self.maxClauseId:
            return (False, "Invalid clause Id %d.  Not in ascending order" % (id))
        self.maxClauseId = id
        self.clauseDict[id] = clause
        if len(clause) == 0:
            self.addedEmpty = True
        self.liveClauseCount += 1
        self.totalClauseCount += 1
        if self.verbose:
            self.liveClauseSet.add(id)
        self.maxLiveClauseCount = max(self.liveClauseCount, self.maxLiveClauseCount)
        # Add literals
        for lit in clause:
            if lit in self.literalCountDict:
                self.literalCountDict[lit] += 1
                if self.verbose:
                    self.literalSetDict[lit].add(id)
            else:
                self.literalCountDict[lit] = 1
                if self.verbose:
                    self.literalSetDict[lit] = set([id])
        return (True, "")
        
    # Delete clause.
    # Return (T/F, reason)
    def deleteClause(self, id):
        clause, msg = self.findClause(id)
        if clause is None:
            return (False, "Cannot delete clause %d: %s" % (id, msg))
        self.clauseDict[id] = None
        self.liveClauseCount -= 1
        if self.verbose:
            self.liveClauseSet.remove(id)
        for lit in clause:
            self.literalCountDict[lit] -= 1
            if self.verbose:
                self.literalSetDict[lit].remove(id)
        return (True, "")
        
    # Check that clause is generated by set of antecedents
    # Assumes clause has been processed by cleanClause
    # Return (T/F, Reason)
    def checkRup(self, clause, hints):
        global fullProof
        if len(hints) == 1 and hints[0] == '*':
            # This needs a real check
            fullProof = False
            return (True, "")
        unitSet = set([-lit for lit in clause])
        history = "INIT:"
        for lit in clause:
            history += " %d" % -lit
        history += ". "
        for id in hints:
            rclause, msg = self.findClause(id)
            if rclause is None:
                return (False, "RUP failed: %s" % msg)
            ulit = None
            history += "#%d=%s:" % (id, str(rclause))
            for lit in rclause:
                if -lit not in unitSet:
                    if lit in unitSet:
                        return (False, "RUP failed: Literal %d true in clause #%d (history = %s)" % (lit, id, history))
                    elif ulit is None:
                        ulit = lit
                    else:
                        return (False, "RUP failed: No unit literal found in clause #%d %s (history = %s)" % (id, showClause(rclause), history))
            if ulit is None:
                return (True, "")
            unitSet.add(ulit)
            history += " %d. " % ulit 
        return (False, "RUP failed: No conflict found (history = %s)" % history)

    def checkFinal(self):
        # All input clauses should have been deleted
        neverDefined = []
        notDeleted = []
        for id in range(1, self.inputClauseCount+1):
            if id in self.clauseDict:
                if self.clauseDict[id] is not None:
                    notDeleted.append(id)
            else:
                neverDefined.append(id)
        if len(neverDefined) > 0:
            return (False, "Input clauses %s never defined" % str(neverDefined))
        if len(notDeleted) > 0:
            return (False, "Input clauses %s not deleted" % str(notDeleted))
        # Should only be one unit clause
        self.root = None
        for id in sorted(self.clauseDict.keys()):
            entry = self.clauseDict[id]
            if entry is None:
                continue
            if len(entry) == 1:
                nroot = entry[0]
                if self.root is not None:
                    return (False, "At least two possible root nodes: %d, %d" % (root, nroot))
                self.root = nroot
        if self.root is None:
            return (False, "No root node found")
        print("Root node %d" % self.root)
        return (True, "")

class OperationManager:
    conjunction, disjunction = range(2)
    
    # Number of input variables
    inputVariableCount = 0
    # Operation indexed by output variable.  Each entry of form (op, arg1, arg2, id)
    operationDict = {}
    # For each variable, the variables on which it depends
    dependencySetDict = {}

    # Clause Manager
    cmgr = None
    verbose = False

    def __init__(self, cmgr, varCount):
        self.inputVariableCount = varCount
        self.cmgr = cmgr
        self.verbose = cmgr.verbose
        self.operationDict = {}
        self.dependencySetDict = { v : set([v]) for v in range(1, varCount+1) }

    def addOperation(self, op, outVar, inLit1, inLit2, id):
        if outVar in self.dependencySetDict:
            return (False, "Operator output variable %d already in use" % outVar)
        inVar1 = abs(inLit1)
        inVar2 = abs(inLit2)
        if inVar1 not in self.dependencySetDict:
            return (False, "Operator input literal %d undefined" % inLit1)            
        if inVar2 not in self.dependencySetDict:
            return (False, "Operator input literal %d undefined" % inLit2)

        dset1 = self.dependencySetDict[inVar1]
        dset2 = self.dependencySetDict[inVar2]
        if op == self.conjunction and not dset1.isdisjoint(dset2):
            return (False, "Dependency sets of conjunction operation inputs %s and %s are not disjoint" % (inLit1, inLit2))
        self.dependencySetDict[outVar] = dset1.union(dset2)
        if op == self.conjunction:
            (ok, msg) = self.cmgr.addClause([outVar, -inLit1, -inLit2], id)
            if not ok:
                return (ok, msg)
            (ok, msg) = self.cmgr.addClause([-outVar, inLit1], id+1)
            if not ok:
                return (ok, msg)
            (ok, msg) = self.cmgr.addClause([-outVar, inLit2], id+2)            
            if not ok:
                return (ok, msg)
        elif op == self.disjunction:
            (ok, msg) = self.cmgr.addClause([-outVar, inLit1, inLit2], id)
            if not ok:
                return (ok, msg)
            (ok, msg) = self.cmgr.addClause([outVar, -inLit1], id+1)
            if not ok:
                return (ok, msg)
            (ok, msg) = self.cmgr.addClause([outVar, -inLit2], id+2)
            if not ok:
                return (ok, msg)
        self.operationDict[outVar] = (op, inLit1, inLit2, id)
        return (True, "")

    def checkDisjunction(self, inLit1, inLit2, hints):
        return self.cmgr.checkRup([-inLit1, -inLit2], hints)

    def deleteOperation(self, outVar):
        if outVar not in self.operationDict:
            return (False, "Operator %d undefined" % outVar)
        (op, inLit1, inLit2, id) = self.operationDict[outVar]
        (ok, msg) = self.cmgr.deleteClause(id)
        if not ok:
            return (False, "Could not delete defining clause for operation %d: %s" % (outVar, msg))
        (ok, msg) = self.cmgr.deleteClause(id+1)
        if not ok:
            return (False, "Could not delete defining clause for operation %d: %s" % (outVar, msg))
        (ok, msg) = self.cmgr.deleteClause(id+2)
        if not ok:
            return (False, "Could not delete defining clause for operation %d: %s" % (outVar, msg))
        del self.operationDict[outVar]
        del self.dependencySetDict[outVar]
        return (True, "")

    # Optionally provide dictionary of weights.  Otherwise assume unweighted
    def count(self, root, weights = None):
        if weights is None:
            weights = {}
        beta = 1.0
        for v in range(1, self.inputVariableCount+1):
            if v not in weights:
                weights[v] = 0.5
                beta *= 2.0
        for outVar in sorted(self.operationDict.keys()):
            (op, arg1, arg2, cid) = self.operationDict[outVar]
            var1 = abs(arg1)
            val1 = weights[var1]
            if arg1 < 0:
                val1 = 1.0 - val1
            var2 = abs(arg2)
            val2 = weights[var2]
            if arg2 < 0:
                val2 = 1.0 - val2
            result = val1 * val2 if op == self.conjunction else val1 + val2
            weights[outVar] = result
        rootVar = abs(root)
        rval = weights[rootVar]
        if root < 0:
            rval = 1.0 - rval
        return rval * beta

class ProofException(Exception):
    def __init__(self, value, lineNumber = None):
        self.value = value
        self.lineNumber = lineNumber

    def __str__(self):
        nstring = " (Line %d)" % self.lineNumber if self.lineNumber is not None else ""
        return ("Proof Exception%s: " % nstring) + str(self.value)

class Prover:
    verbose = False
    lineNumber = 0
    # Clause Manager
    cmgr = None
    # Operation Manager
    omgr = None
    failed = False

    def __init__(self, creader, verbose = False):
        self.verbose = verbose
        self.lineNumber = 0
        self.cmgr = ClauseManager(verbose, len(creader.clauses))
        self.omgr = OperationManager(self.cmgr, creader.nvar)
        self.failed = False
        self.subsetOK = False
        self.ruleCounters = { 'i' : 0, 'a' : 0, 'dc' : 0, 'p' : 0, 's' : 0, 'do' : 0 }

        id = 0
        for clause in creader.clauses:
            nclause = cleanClause(clause)
            if not regularClause(nclause):
                self.failProof("Cannot add %s as input clause" % showClause(clause))
                break
            id += 1
            (ok, msg) = self.cmgr.addClause(nclause, id)
            if not ok:
                self.failProof(msg)
                break

    def flagError(self, msg):
        print("ERROR.  Line %d: %s" % (self.lineNumber, msg))
        self.failed = True

    # Find zero-terminated list of integers in fields (or single field consisting of '*').  Return (list, rest)
    # Flag error if something goes wrong
    def findList(self, fields, starOk = False):
        ls = []
        rest = fields
        starOk = True
        while len(rest) > 0:
            field = rest[0]
            rest = rest[1:]
            if starOk and field == '*':
                val = '*'
            else:
                try:
                    val = int(field)
                except:
                    self.flagError("Non-integer value '%s' encountered" % field)
                    return (ls, rest)
            if val == 0:
                return (ls, rest)
            ls.append(val)
            starOk = False
        self.flagError("No terminating 0 found")
        return (ls, rest)

    def prove(self, fname):
        if self.failed:
            self.failProof("Problem with CNF file")
            return
        try:
            pfile = open(fname)
        except:
            self.failProof("Couldn't open proof file '%s" % fname)
            return
        for line in pfile:
            self.lineNumber += 1
            fields = line.split()
            if len(fields) == 0 or fields[0][0] == 'c':
                continue
            id = None
            if fields[0] not in ['dc', 'do']:
                try:
                    id = int(fields[0])
                except:
                    self.flagError("Looking for clause Id.  Got '%s'" % fields[0])
                    break
                fields = fields[1:]
            cmd = fields[0]
            rest = fields[1:]
            # Dispatch on command
            # Level command requires special consideration, since it only occurs at beginning of file
            if cmd == 'i':
                self.doInput(id, rest)
            elif cmd == 'a':
                self.doAddRup(id, rest)
            elif cmd == 'dc':
                self.doDeleteRup(id, rest)
            elif cmd == 'p':
                self.doProduct(id, rest)
            elif cmd == 's':
                self.doSum(id, rest)
            elif cmd == 'do':
                self.doDeleteOperation(rest)
            else:
                self.invalidCommand(cmd)
            if self.failed:
                break
            self.ruleCounters[cmd] += 1
        (ok, msg) = self.cmgr.checkFinal()
        if not ok:
            self.flagError(msg)
        pfile.close()
        self.checkProof()
            
    def count(self, weights = None):
        root = self.cmgr.root
        if root is None:
            print("Can't determine count.  Don't know root")
            return 0.0
        return self.omgr.count(self.cmgr.root, weights)

    def invalidCommand(self, cmd):
        self.flagError("Invalid command '%s' in proof" % cmd)

    def doInput(self, id, rest):
        (lits, rest) = self.findList(rest)
        if self.failed:
            return
        if len(rest) > 0:
            self.flagError("Items beyond terminating 0")
        clause = cleanClause(lits)
        if not testClauseEquality(clause, self.cmgr.clauseDict[id]):
            self.flagError("Clause %s does not match input clause #%d" % (showClause(lits), id))
            return

    def doAddRup(self, id, rest):
        (lits, rest) = self.findList(rest)
        if self.failed:
            return
        (hints, rest) = self.findList(rest, starOk = True)
        if self.failed:
            return
        if len(rest) > 0:
            self.flagError("Coudn't add clause #%d: Items beyond terminating 0" % (id))
            return
        clause = cleanClause(lits)
        (ok, msg) = self.cmgr.checkRup(clause, hints)
        if not ok:
            self.flagError("Couldn't add clause #%d: %s" % (id, msg))
            return
        (ok, msg) = self.cmgr.addClause(clause, id)
        if not ok:
            self.flagError("Couldn't add clause #%d: %s" % (id, msg))
        

    def doDeleteRup(self, id, rest):
        if len(rest) < 1:
            self.flagError("Must specify Id of clause to delete")
            return
        try:
            id = int(rest[0])
        except:
            self.flagError("Couldn't delete clause.  Invalid clause Id '%s'" % rest[0])
            return
        rest = rest[1:]
        (hints, rest) = self.findList(rest, starOk = True)
        if self.failed:
            return
        if len(rest) > 0:
            self.flagError("Couldn't delete clause #%d: Items beyond terminating 0" % (id))
            return
        (clause, msg) = self.cmgr.findClause(id)
        if clause is None:
            self.flagError("Couldn't delete clause #%d: %s" % (id, msg))
            return
        (ok, msg) = self.cmgr.deleteClause(id)
        if not ok:
            self.flagError("Couldn't delete clause #%d: %s" % (id, msg))
            return
        (ok, msg) = self.cmgr.checkRup(clause, hints)
        if not ok:
            self.flagError("Couldn't delete clause #%d: %s" % (id, msg))
            return
        
    def doProduct(self, id, rest):
        if len(rest) != 3:
            self.flagError("Couldn't add operation with clause #%d: Invalid number of operands" % (id))
            return
        try:
            args = [int(field) for field in rest]
        except:
            self.flagError("Couldn't add operation with clause #%d: Non-integer arguments" % (id))
            return
        (ok, msg) = self.omgr.addOperation(self.omgr.conjunction, args[0], args[1], args[2], id)
        if not ok:
            self.flagError("Couldn't add operation with clause #%d: %s" % (id, msg))

    def doSum(self, id, rest):
        if len(rest) < 3:
            self.flagError("Couldn't add operation with clause #%d: Invalid number of operands" % (id))
            return
        try:
            args = [int(field) for field in rest[:3]]
            rest = rest[3:]
        except:
            self.flagError("Couldn't add operation with clause #%d: Non-integer arguments" % (id))
            return
        (hints, rest) = self.findList(rest, starOk = True)
        if self.failed:
            return
        (ok, msg) = self.omgr.addOperation(self.omgr.disjunction, args[0], args[1], args[2], id)
        if not ok:
            self.flagError("Couldn't add operation with clause #%d: %s" % (id, msg))
            return
        if len(rest) > 0:
            self.flagError("Couldn't add operation with clause #%d: Items beyond terminating 0" % (id))
            return
        (ok, msg) = self.omgr.checkDisjunction(args[1], args[2], hints)
        if not ok:
            self.flagError("Couldn't add operation with clause #%d: %s" % (id, msg))
            return

    def doDeleteOperation(self, id, rest):
        if len(rest) != 1:
            self.flagError("Must specify output variable for operation deletion")
            return
        try:
            outVar = int(rest[0])
        except:
            self.flagError("Invalid operand '%s' to operation deletion" % rest[0])
            return
        (ok, msg) = self.omgr.deleteOperation(outVar)
        if not ok:
            self.flagError("Could not delete operation %d: %s" % (outVar, msg))

    def failProof(self, reason):
        self.failed = True
        msg = "PROOF FAILED"
        if reason != "":
            msg += ": " + reason
        print(msg)

    def checkProof(self):
        if self.failed:
            self.failProof("")
        else:
            if fullProof:
                print("PROOF SUCCESSFUL")
            else:
                print("PROOF PARTIALLY VERIFIED")
        self.summarize()
            
    def summarize(self):
        clist = sorted(self.ruleCounters.keys())
        tcount = 0
        print("%d total clauses" % self.cmgr.totalClauseCount)
        print("%d maximum live clauses" % self.cmgr.maxLiveClauseCount)
        print("Command occurences:")
        for cmd in clist:
            count = self.ruleCounters[cmd]
            if count > 0:
                tcount += count
                print("    %2s   : %d" % (cmd, count))
        print("    TOTAL: %d" % (tcount))


def run(name, args):
    cnfName = None
    proofName = None
    verbose = False
    weights = None
    optList, args = getopt.getopt(args, "hvi:p:w:")
    for (opt, val) in optList:
        if opt == '-h':
            usage(name)
            return
        elif opt == '-v':
            verbose = True
        elif opt == '-i':
            cnfName = val
        elif opt == '-p':
            proofName = val
        elif opt == '-w':
            wlist = val.split(":")
            try:
                weights = { v : int(wlist[v-1])/100.0 for v in range(1, len(wlist)+1) }
            except:
                print("Couldn't extract weights from '%s'." % val)
                usage(name)
                return
        else:
            usage(name)
            return
    if cnfName is None:
        print("Need CNF file name")
        return
    if proofName is None:
        print("Need proof file name")
        return
    start = datetime.datetime.now()
    creader = CnfReader(cnfName)
    if creader.failed:
        print("Error reading CNF file: %s" % creader.errorMessage)
        print("PROOF FAILED")
        return
    prover = Prover(creader, verbose)
    prover.prove(proofName)
    delta = datetime.datetime.now() - start
    seconds = delta.seconds + 1e-6 * delta.microseconds
    print("Elapsed time for check: %.2f seconds" % seconds)
    count = prover.count(weights)
    if weights is None:
        print("Unweighted count = %.0f" % count)
    else:
        print("Weighted count = %.5f" % count)
    
if __name__ == "__main__":
    run(sys.argv[0], sys.argv[1:])