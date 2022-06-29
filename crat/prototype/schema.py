# Quasi-canonical representation of a counting schema
# For use by both top-down and bottom-up schema generators

import sys
from pysat.solvers import Solver
import readwrite

# Use glucose4 as solver
solverId = 'g4'

class SchemaException(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return "Schema Exception: " + str(self.value)


# Manage set of literals
class LiteralSet:
    litSet = set([])
    # Maintain list of lists of additions, so that can revert back to earlier version
    epochs = [[]]

    def __init__(self):
        self.litSet = set([])
        self.epochs = [[]]

    def startEpoch(self):
        self.epochs.append([])
        
    def revertEpoch(self):
        last = self.epochs[-1]
        self.epochs = self.epochs[:-1]
        for lit in last:
            self.litSet.remove(lit)

    def add(self, lit):
        if lit in self.litSet:
            return
        if -lit in self.litSet:
            raise SchemaException("Attempted to add literal %d to set.  Negation already member" % lit)
        self.litSet.add(lit)
        self.epochs[-1].append(lit)

    def __contains__(self, val):
        return val in self.litSet

    def show(self):
        print("Units:")
        for e in self.epochs:
            print("   " + str(e))
    
# Original implementation of reasoner.  Used own implementation of unit propagation
class LocalReasoner:
    clauseList = []
    unitSet = None
    solver = None

    def __init__(self):
        self.clauseList = []
        self.unitSet = LiteralSet()
        self.solver = Solver(solverId, with_proof = True)

    def addClauses(self, clist):
        self.clauseList += clist
        self.solver.append_formula(clist)
        self.unitProp()

    def startEpoch(self):
        self.unitSet.startEpoch()

    def revertEpoch(self):
        self.unitSet.revertEpoch()
        # Might have added some clauses that can propagate
        self.unitProp()

    # Attempt unit propagation on clause
    # Return: ("unit", ulit), ("conflict", None), ("satisfied", lit), ("none", None)
    def unitPropClause(self, clause):
        ulit = None
        for lit in clause:
            if lit in self.unitSet:
                return ("satisfied", lit)
            if -lit not in self.unitSet:
                if ulit is None:
                    ulit = lit
                else:
                    # No unit literal found
                    return ("none", None)
        if ulit is None:
            return ("conflict", None)
        self.unitSet.add(ulit)
        return ("unit", ulit)

    # Perform unit propagation on set of clauses.
    # Return True if encounter conflict
    def unitProp(self):
        changed = True
        while changed:
            changed = False
            for clause in self.clauseList:
                (res, ulit) = self.unitPropClause(clause)
                if res == "conflict":
                    return True
                elif res == "unit":
                    changed = True
        return False
                
    def rupCheck(self, clause, failOK = False):
        self.startEpoch()
        for lit in clause:
            self.unitSet.add(-lit)
        result = self.unitProp()
        if not result and not failOK:
            print("UH-OH RUP check failed.  Clause = %s" % (str(clause)))
            self.show()
        self.revertEpoch()
        return result

    def isUnit(self, lit):
        lval = lit in self.unitSet
        return lval
    
    def addUnit(self, lit):
        self.unitSet.add(lit)
        self.unitProp()

    def show(self):
        self.unitSet.show()

    def justifyUnit(self, lit, context):
        clauses =  []
        if self.isUnit(lit):
            return clauses
        pclause = readwrite.invertClause(context)
        pclause.append(lit)
        if self.rupCheck(pclause, failOK=True):
            clauses.append(pclause)
            self.addClauses([pclause])
            # Sanity check
            if not self.isUnit(lit):
                print("WARNING.  Added RUP clause %s, but still don't have unit literal %s in context %s" % (str(pclause), lit, str(context)))
                raise SchemaException("Proof failure.  Added RUP clause %s, but still don't have unit literal %s in context %s" % (str(pclause), lit, str(context)))
            return clauses
        # Bring out the big guns!
        sstate = self.solver.solve(assumptions=context + [-lit])
        if sstate == True:
            print("WARNING. Proof failure. Couldn't justify literal %d with context  %s" % (lit, str(context)))
            raise SchemaException("Proof failure. Couldn't justify literal %d with context  %s" % (lit, str(context)))
            return clauses
        slist = self.solver.get_proof()
        for sclause in slist:
            try:
                fields = [int(s) for s in sclause.split()]
            except:
                raise SchemaException("Proof failure.  SAT solver returned invalid proof clause %s" % sclause)
            if len(fields) == 0 or fields[-1] != 0:
                raise SchemaException("Proof failure.  SAT solver returned invalid proof clause %s" % sclause)
            clause = fields[:-1]
            if len(clause) ==  0:
                continue
            clauses.append(clause)
        self.addClauses(clauses)
        # Sanity check
        if not self.isUnit(lit):
            print("WARNING.  Added SAT clauses %s, but still don't have unit literal %s in context %s" % (str(clauses), lit, str(context)))
            raise SchemaException("Proof failure.  Added SAT clauses %s, but still don't have unit literal %s in context %s" % (str(clauses), lit, str(context)))
        return clauses

# Version of reasoner that uses both local unit prop + solver
class DualReasoner:
    clauseList = []
    unitSet = None
    solver = None

    def __init__(self):
        self.clauseList = []
        self.unitSet = LiteralSet()
        self.solver = Solver(solverId, with_proof = True)

    def addClauses(self, clist):
        self.clauseList += clist
        self.solver.append_formula(clist)
        self.unitProp()

    def startEpoch(self):
        self.unitSet.startEpoch()

    def revertEpoch(self):
        self.unitSet.revertEpoch()
        # Might have added some clauses that can propagate
        self.unitProp()

    # Attempt unit propagation on clause
    # Return: ("unit", ulit), ("conflict", None), ("satisfied", lit), ("none", None)
    def unitPropClause(self, clause):
        ulit = None
        for lit in clause:
            if lit in self.unitSet:
                return ("satisfied", lit)
            if -lit not in self.unitSet:
                if ulit is None:
                    ulit = lit
                else:
                    # No unit literal found
                    return ("none", None)
        if ulit is None:
            return ("conflict", None)
        self.unitSet.add(ulit)
        return ("unit", ulit)

    # Perform unit propagation on set of clauses.
    # Return True if encounter conflict
    def unitProp(self):
        changed = True
        while changed:
            changed = False
            for clause in self.clauseList:
                (res, ulit) = self.unitPropClause(clause)
                if res == "conflict":
                    return True
                elif res == "unit":
                    changed = True
        return False
                
    def rupCheck(self, clause, context, failOK = False):
        self.startEpoch()
        for lit in clause:
            self.unitSet.add(-lit)
        result = self.unitProp()
        if not result and not failOK:
            print("UH-OH RUP check failed.  Clause = %s" % (str(clause)))
            self.show()
        self.revertEpoch()
        assumptions = context + readwrite.invertClause(clause)
        sprop, slits = self.solver.propagate(assumptions=assumptions)
        sresult = not sprop
        if sresult != result:
            print("WARNING.  Got different results from local vs. solver RUP Check.  Context = %s.  Clause = %s.  Lits=%s" % (str(context), str(clause), str(slits)))
        return result

    # See if literal among current units
    def isUnit(self, lit, context):
        lval = lit in self.unitSet
        # Compare to value from solver
        ok, lits = self.solver.propagate(assumptions=context)
        sval = ok and lit in lits
        if sval != lval:
            print("WARNING.  Got different results from local vs. solver unit propagation.  Lit = %d.  Context = %s.  Lits=%s" % (lit, str(context), str(lits)))
        return lval
    
    def addUnit(self, lit):
        self.unitSet.add(lit)
        self.unitProp()

    def show(self):
        self.unitSet.show()

    def justifyUnit(self, lit, context):
        clauses =  []
        if self.isUnit(lit, context):
            return clauses
        pclause = readwrite.invertClause(context)
        pclause.append(lit)
        if self.rupCheck(pclause, context, failOK=True):
            clauses.append(pclause)
            self.addClauses([pclause])
            # Sanity check
            if not self.isUnit(lit, context):
                print("WARNING.  Added RUP clause %s, but still don't have unit literal %s in context %s" % (str(pclause), lit, str(context)))
                raise SchemaException("Proof failure.  Added RUP clause %s, but still don't have unit literal %s in context %s" % (str(pclause), lit, str(context)))
            return clauses
        # Bring out the big guns!
        sstate = self.solver.solve(assumptions=context + [-lit])
        if sstate == True:
            print("WARNING. Proof failure. Couldn't justify literal %d with context  %s" % (lit, str(context)))
            raise SchemaException("Proof failure. Couldn't justify literal %d with context  %s" % (lit, str(context)))
            return clauses
        slist = self.solver.get_proof()
        for sclause in slist:
            try:
                fields = [int(s) for s in sclause.split()]
            except:
                raise SchemaException("Proof failure.  SAT solver returned invalid proof clause %s" % sclause)
            if len(fields) == 0 or fields[-1] != 0:
                raise SchemaException("Proof failure.  SAT solver returned invalid proof clause %s" % sclause)
            clause = fields[:-1]
            if len(clause) ==  0:
                continue
            clauses.append(clause)
        self.addClauses(clauses)
        # Sanity check
        if not self.isUnit(lit, context):
            print("WARNING.  Added SAT clauses %s, but still don't have unit literal %s in context %s" % (str(clauses), lit, str(context)))
            raise SchemaException("Proof failure.  Added SAT clauses %s, but still don't have unit literal %s in context %s" % (str(clauses), lit, str(context)))
        return clauses

# Version of reasoner that relies purely on SAT solver
class Reasoner:
    solver = None
    # Caching of last results
    lastAssumptions = None
    lastPropagate = None
    lastLiterals = None

    def __init__(self):
        self.solver = Solver(solverId, with_proof = True)
        self.killCache()

    def killCache(self):
        self.lastAssumptions = None
        self.lastPropagate = None
        self.lastLiterals = None

    def propagate(self, assumptions):
        ta = tuple(assumptions)
        if self.lastAssumptions == ta:
            return self.lastPropagate, self.lastLiterals
        else:
            prop, lits = self.solver.propagate(assumptions)
            self.lastAssumptions = tuple(assumptions)
            self.lastPropagate = prop
            self.lastLiterals = lits
            return prop, lits

    def addClauses(self, clist):
        self.solver.append_formula(clist)
        self.killCache()

    def startEpoch(self):
        pass

    def revertEpoch(self):
        pass
                
    def rupCheck(self, clause, context, failOK = False):
        assumptions = context + readwrite.invertClause(clause)
        prop, slits = self.propagate(assumptions)
        result = not prop
        return result

    # See if literal among current units
    def isUnit(self, lit, context):
        ok, lits = self.propagate(context)
        val = ok and lit in lits
        return val
    
    def addUnit(self, lit):
        pass

    def show(self):
        print("Nothing to show")

    def justifyUnit(self, lit, context):
        clauses =  []
        if self.isUnit(lit, context):
            return clauses
        pclause = readwrite.invertClause(context)
        pclause.append(lit)
        if self.rupCheck(pclause, context, failOK=True):
            clauses.append(pclause)
            self.addClauses([pclause])
            # Sanity check
            if not self.isUnit(lit, context):
                print("WARNING.  Added RUP clause %s, but still don't have unit literal %s in context %s" % (str(pclause), lit, str(context)))
                raise SchemaException("Proof failure.  Added RUP clause %s, but still don't have unit literal %s in context %s" % (str(pclause), lit, str(context)))
            return clauses
        # Bring out the big guns!
        sstate = self.solver.solve(assumptions=context + [-lit])
        if sstate == True:
            print("WARNING. Proof failure. Couldn't justify literal %d with context  %s" % (lit, str(context)))
            raise SchemaException("Proof failure. Couldn't justify literal %d with context  %s" % (lit, str(context)))
            return clauses
        slist = self.solver.get_proof()
        for sclause in slist:
            try:
                fields = [int(s) for s in sclause.split()]
            except:
                raise SchemaException("Proof failure.  SAT solver returned invalid proof clause %s" % sclause)
            if len(fields) == 0 or fields[-1] != 0:
                raise SchemaException("Proof failure.  SAT solver returned invalid proof clause %s" % sclause)
            clause = fields[:-1]
            if len(clause) ==  0:
                continue
            clauses.append(clause)
        self.addClauses(clauses)
        # Sanity check
        if not self.isUnit(lit, context):
            print("WARNING.  Added SAT clauses %s, but still don't have unit literal %s in context %s" % (str(clauses), lit, str(context)))
            raise SchemaException("Proof failure.  Added SAT clauses %s, but still don't have unit literal %s in context %s" % (str(clauses), lit, str(context)))
        return clauses
    

class NodeType:
    tcount = 5
    tautology, variable, negation, conjunction, disjunction = range(5)
    typeName = ["taut", "var", "neg", "conjunct", "disjunct"]
    definingClauseCount = [0, 0, 0, 3, 3]

# Prototype node.  Used for unique table lookup
class ProtoNode:
    ntype = None
    children =  None
    
    def __init__(self, ntype, children):
        self.ntype = ntype
        self.children = children

    def key(self):
        return tuple([self.ntype] + [c.xlit for c in self.children])

    def isOne(self):
        return self.ntype == NodeType.tautology

    def isZero(self):
        return self.ntype == NodeType.negation and self.children[0].isOne()

    def isConstant(self):
        return self.isOne() or self.isZero()

class Node(ProtoNode):
    xlit = None
    # Information used during proof generation.  Holdover from when node represented ITE
    iteVar = None
 
    def __init__(self, xlit, ntype, children):
        ProtoNode.__init__(self, ntype, children)
        self.xlit = xlit
        self.iteVar = None
    
    def __hash__(self):
        return self.xlit

    def __str__(self):
        return "%s-%d" % (NodeType.typeName[self.ntype], self.xlit)

    def __eq__(self, other):
        return self.xlit == other.xlit

    def getLit(self):
        return None

class Variable(Node):
    level = 1  # For ordering

    def __init__(self, id):
        Node.__init__(self, id, NodeType.variable, [])

    def key(self):
        return (self.ntype, self.xlit)

    def getLit(self):
        return self.xlit

class One(Node):
    def __init__(self):
        Node.__init__(self, readwrite.tautologyId, NodeType.tautology, [])

    def __str__(self):
        return "TAUT"

class Negation(Node):
    
    def __init__(self, child):
        Node.__init__(self, -child.xlit, NodeType.negation, [child])

    def __str__(self):
        return "-" + str(self.children[0])

    def getLit(self):
        clit = self.children[0].getLit()
        return clit if clit is None else -clit

class Conjunction(Node):
    clauseId = None

    def __init__(self, child1, child2, xlit, clauseId):
        Node.__init__(self, xlit, NodeType.conjunction, [child1, child2])
        self.clauseId = clauseId

    def __str__(self):
        return "P%d" % self.xlit

class Disjunction(Node):
    clauseId = None

    def __init__(self, child1, child2, xlit, clauseId):
        Node.__init__(self, xlit, NodeType.disjunction, [child1, child2])
        self.clauseId = clauseId

    def __str__(self):
        return "S%d" % self.xlit

# Represent overall schema
class Schema:
    
    # List of variables, ordered by id
    variables = []
    # Constant Nodes
    leaf1 = None
    leaf0 = None
    # Mapping (ntype, arg1, ..., argk) to nodes
    uniqueTable = {}
    # All Nodes
    nodes = []
    # Verbosity level
    verbLevel = 1
    cwriter = None
    clauseList = []
    reasoner = None
    # Statistics:
    # Count of each node by type
    nodeCounts = []
    # Traverses of nodes by type
    nodeVisits = []
    # Added RUP clause counts, indexed by number of clauses to justify single literal
    literalClauseCounts = {}
    # Added RUP clause counts, indexed by node type
    nodeClauseCounts = []

    def __init__(self, variableCount, clauseList, fname, verbLevel = 1):
        self.verbLevel = verbLevel
        self.uniqueTable = {}
        self.clauseList = clauseList
        self.cwriter = readwrite.CratWriter(variableCount, clauseList, fname, verbLevel)
        self.reasoner = Reasoner()
        self.reasoner.addClauses(clauseList)
        self.nodeCounts = [0] * NodeType.tcount
        self.literalClauseCounts = {}
        self.nodeClauseCounts = [0] * NodeType.tcount
        self.leaf1 = One()
        self.store(self.leaf1)
        self.leaf0 = Negation(self.leaf1)
        self.store(self.leaf0)
        self.variables = []
        for i in range(1, variableCount+1):
            v = Variable(i)
            self.variables.append(v)
            self.store(v)
        # Reset so that constant nodes are not included
        self.nodeCounts = [0] * NodeType.tcount
        self.nodeVisits = [0] * NodeType.tcount
        
    def lookup(self, ntype, children):
        n = ProtoNode(ntype, children)
        key = n.key()
        if key in self.uniqueTable:
            return self.uniqueTable[key]
        return None

    def getVariable(self, id):
        return self.variables[id-1]

    def store(self, node):
        key = node.key()
        self.uniqueTable[key] = node
        self.nodes.append(node)
        self.nodeCounts[node.ntype] += 1

    def addNegation(self, child):
        if child.ntype == NodeType.negation:
            return child.children[0]
        n = self.lookup(NodeType.negation, [child])
        if n is None:
            n = Negation(child) 
            self.store(n)
        return n

    def addConjunction(self, child1, child2):
        if child1.isZero() or child2.isZero():
            return self.leaf0
        if child1.isOne():
            return child2
        if child2.isOne():
            return child1
        n = self.lookup(NodeType.conjunction, [child1, child2])
        if n is None:
            xlit, clauseId = self.cwriter.doAnd(child1.xlit, child2.xlit)
            n = Conjunction(child1, child2, xlit, clauseId)
            if self.verbLevel >= 2:
                self.addComment("Node %s = AND(%s, %s)" % (str(n), str(child1), str(child2)))
            self.store(n)
        return n

    def addDisjunction(self, child1, child2, hints = None):
        if child1.isOne() or child2.isOne():
            return self.leaf1
        if child1.isZero():
            return child2
        if child2.isZero():
            return child1
        n = self.lookup(NodeType.disjunction, [child1, child2])
        if n is None:
            xlit, clauseId = self.cwriter.doOr(child1.xlit, child2.xlit, hints)
            n = Disjunction(child1, child2, xlit, clauseId)
            if self.verbLevel >= 2:
                self.addComment("Node %s = OR(%s, %s)" % (str(n), str(child1), str(child2)))
            self.store(n)
        return n

    def addIte(self, nif, nthen, nelse):
        if nif.isOne():
            result = nthen
        elif nif.isZero():
            result = nelse
        elif nthen == nelse:
            result = nthen
        elif nthen.isOne() and nelse.isZero():
            result = nif
        elif nthen.isZero() and nelse.isOne():
            result = self.addNegation(nif)
        elif nthen.isOne():
            result = self.addNegation(self.addConjunction(self.addNegation(nif), self.addNegation(nelse)))
        elif nthen.isZero():
            result = self.addConjunction(self.addNegation(nif), nelse)
        elif nelse.isOne():
            result = self.addNegation(self.addConjunction(nif, self.addNegation(nthen)))
        elif nelse.isZero():
            result = self.addConjunction(nif, nthen)
        else:
            ntrue = self.addConjunction(nif, nthen)
            nfalse = self.addConjunction(self.addNegation(nif), nelse)
            hints = [ntrue.clauseId+1, nfalse.clauseId+1]
            n = self.addDisjunction(ntrue, nfalse, hints)
            result = n
        if self.verbLevel >= 3:
            print("ITE(%s, %s, %s) --> %s" % (str(nif), str(nthen), str(nelse), str(result)))
        return result

    # hlist members can be clauseId or (node, offset), where 0 <= offset < 3
    def addClause(self, nodes, hlist = None):
        lits = [n.xlit for n in nodes]
        if hlist is None:
            hints = ['*']
        else:
            hints = []
            for h in hlist:
                if type(h) == type((1,2)):
                    hint = h[0].clauseId = h[1]
                else:
                    hint = h
                hints.append(hint)
        self.cwriter.doClause(lits, hints)

    def addComment(self, s):
        self.cwriter.doComment(s)

    def deleteClause(self, id, hlist = None):
        self.cwriter.doDeleteClause(id, hlist)

    def deleteOperation(self, node):
        self.cwriter.doDeleteOperation(node.xlit, node.clauseId)
        
    # Generate justification of root nodes
    # context is list of literals that are assigned in the current context
    # Returns list of unit clauses that should be deleted
    def validateUp(self, root, context, parent = None):
        self.nodeVisits[root.ntype] += 1
        rstring = " (root)" if parent is None else ""
        extraUnits = []
        if root.ntype == NodeType.disjunction:
            if root.iteVar is None:
                raise SchemaException("Don't know how to validate OR node %s that is not from ITE" % str(root))
            svar = root.iteVar
            # Set up children
            self.reasoner.startEpoch()
            self.reasoner.addUnit(svar)
            extraUnits += self.validateUp(root.children[0], context + [svar], root)
            self.reasoner.revertEpoch()
            self.reasoner.startEpoch()
            self.reasoner.addUnit(-svar)
            extraUnits += self.validateUp(root.children[1], context + [-svar], root)
            self.reasoner.revertEpoch()
            # Assert extension literal.  Requires two steps to get both sides of disjunction
            if self.verbLevel >= 2:
                self.addComment("Assert ITE at node %s%s" % (str(root), rstring))
            icontext = readwrite.invertClause(context)
            clause = [root.iteVar, root.xlit] + icontext
            self.cwriter.doClause(clause)
            clause = clause[1:]
            cid = self.cwriter.doClause(clause)
            self.nodeClauseCounts[root.ntype] += 2
            if parent is not None and len(context) == 0:
                extraUnits.append(cid)
        elif root.ntype == NodeType.conjunction:
            vcount = 0
            for c in root.children:
                clit = c.getLit()
                if clit is None:
                    extraUnits += self.validateUp(c, context, root)
                    vcount += 1
                else:
                    clauses = self.reasoner.justifyUnit(clit, context)
                    if len(clauses) == 0:
                        if self.verbLevel >= 3:
                            print("Found unit literal %d in context %s" % (clit, str(context)))
                    elif self.verbLevel >= 2:
                        self.addComment("Justify literal %d in context %s " % (clit, str(context)))
                        if self.verbLevel >= 3:
                            print("Justified unit literal %d in context %s with %d proof steps" % (clit, str(context), len(clauses)))
                    for clause in clauses:
                        self.cwriter.doClause(clause)
                    nc = len(clauses)
                    if nc in self.literalClauseCounts:
                        self.literalClauseCounts[nc] += 1
                    else:
                        self.literalClauseCounts[nc] = 1
            if vcount > 1:
                # Assert extension literal
                if self.verbLevel >= 2:
                    self.addComment("Assert unit clause for AND node %s%s" % (str(root), rstring))
                clause = [root.xlit] + readwrite.invertClause(context)
                cid = self.cwriter.doClause(clause)
                self.nodeClauseCounts[root.ntype] += 1
                if parent is not None and len(context) == 0:
                    extraUnits.append(cid)
        else:
            if root.iteVar is not None:
                # This node was generated from an ITE.
                if self.verbLevel >= 2:
                    self.addComment("Assert clause for root of ITE %s" % rstring)
                clause = [root.xlit] + readwrite.invertClause(context)
                cid = self.cwriter.doClause(clause)
                self.nodeClauseCounts[root.ntype] += 1
                if parent is not None and len(context) == 0:
                    extraUnits.append(cid)
        return extraUnits
                
    def doValidate(self):
        root = self.nodes[-1]
        extraUnits = self.validateUp(root, [], parent = None)
        if self.verbLevel >= 1 and len(extraUnits) > 0:
            self.addComment("Delete extra unit clauses")
        for cid in extraUnits:
            self.deleteClause(cid)
        if self.verbLevel >= 1:
            self.addComment("Delete input clauses")
        for cid in range(1, len(self.clauseList)+1):
            self.deleteClause(cid)
            
    def finish(self):
        self.cwriter.finish()
        if self.verbLevel >= 1:
            nnode = 0
            ndclause = 0
            print("c Nodes by type")
            for t in range(NodeType.tcount):
                if self.nodeCounts[t] == 0:
                    continue
                print("c    %s: %d" % (NodeType.typeName[t], self.nodeCounts[t]))
                nnode += self.nodeCounts[t]
                ndclause += NodeType.definingClauseCount[t] * self.nodeCounts[t]
            print("c    TOTAL: %d" % nnode)
            print("c Total defining clauses: %d" % ndclause)
            nvnode = 0
            print("c Node visits during proof generation (by node type)")
            for t in range(NodeType.tcount):
                if self.nodeVisits[t] == 0:
                    continue
                print("c    %s: %d" % (NodeType.typeName[t], self.nodeVisits[t]))
                nvnode += self.nodeVisits[t]
            print("c    TOTAL: %d" % nvnode)
            nlclause = 0
            print("c Literal justification clause counts (by number of clauses in justification:")
            for count in sorted(self.literalClauseCounts.keys()):
                nc = self.literalClauseCounts[count]
                print("c    %d : %d" % (count, nc))
                nlclause += count * nc
            print("c    TOTAL: %d" % nlclause)
            nnclause = 0
            print("c RUP clauses for node justification (by node type):")
            for t in range(NodeType.tcount):
                if self.nodeClauseCounts[t] == 0:
                    continue
                print("c    %s: %d" % (NodeType.typeName[t], self.nodeClauseCounts[t]))
                nnclause += self.nodeClauseCounts[t]
            print("c    TOTAL: %d" % nnclause)
            niclause = len(self.clauseList)
            nclause = niclause + ndclause + nlclause + nnclause
            print("Total clauses: %d input + %d defining + %d literal justification + %d node justifications = %d" % (niclause, ndclause, nlclause, nnclause, nclause))

    def doMark(self, root, markSet):
        if root.xlit in markSet:
            return
        markSet.add(root.xlit)
        for c in root.children:
            self.doMark(c, markSet)
        

    def compress(self):
        markSet = set([])
        root = self.nodes[-1]
        self.doMark(root, markSet)
        nnodes = []
        for node in self.nodes:
            if node.xlit in markSet:
                nnodes.append(node)
        if self.verbLevel >= 2:
            print("Compressed schema from %d to %d nodes" % (len(self.nodes), len(nnodes)))
        self.nodes = nnodes

    def show(self):
        for node in self.nodes:
            if node.ntype != NodeType.negation:
                outs = str(node)
                schildren = [str(c) for c in node.children]
                if len(schildren) > 0:
                    outs += " (" + ", ".join(schildren) + ")"
                print(outs)
        print("Root = %s" % str(self.nodes[-1]))
            
        
        
