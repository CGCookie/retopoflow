'''
Created on Jul 15, 2015

@author: Patrick
'''
from .lib.pulp import LpVariable, LpProblem, LpMinimize, LpMaximize, LpInteger, LpStatus, lpSum, LpSolverDefault
import time
import math

def identify_patch_pattern(edges_reduced, check_pattern = -1):
    '''
    takes reduced edges, identifies pattern, identifies rotation/order
    
    returns -
        pattern
        nl0
        direction  - 1 or -1
    '''  
    n_sides = len(edges_reduced)
    unique = set(edges_reduced)
    alpha = max(unique)
    beta = None
    
    nl0 = 0
    direction = 1
    pattern = 10
    
    if len(edges_reduced) == 3:
        if alpha == 2:
            pattern = 0
            nl0 = edges_reduced.index(alpha)
            direction = 1
        else:
            pattern = 1
            nl0 = edges_reduced.index(alpha)
            direction = 1
      
    elif len(edges_reduced) == 4:
        if alpha == 1:
            pattern = 0
            
        elif len(unique) == 2 and edges_reduced.count(alpha) == 1:
            #there is only one alpha
            x = (alpha - 3) / 2
            if x == 0:
                pattern = 2
                nl0 = edges_reduced.index(alpha)
                direction = 1
                print('[A,1,1,1] and x = 0, need to parameterize y?')
            else:
                print('[A,1,1,1] and A = 3 + 2x   Really unsure on these!')
                nl0 = edges_reduced.index(alpha)
                direction = 1
                pattern = 3
                
        elif len(unique) == 2 and edges_reduced.count(alpha) == 2:
            pattern = 1
            print('[A,B,1,1] and A = B -> [A,A,1,1]')
            nl0 = edges_reduced.index(alpha)
            if edges_reduced[-1] == alpha:
                nl0 = 3
            else:
                nl0 = edges_reduced.index(alpha)
            
            direction = 1
           
        elif len(unique) == 3:
            pattern = 4
            print('[A,B,1,1]  A = B + 2 + 2x')
            beta = (unique - set([1,alpha])).pop()
            nl0 = edges_reduced.index(alpha)
            d_beta = (edges_reduced.index(alpha) - nl0) % n_sides
            if d_beta != 1:
                print('%i : dbeta should be 3' % d_beta)
                direction = -1
            else:
                direction = 1
                      
    elif len(edges_reduced) == 5:
        if len(unique) == 2 and alpha ==2:
            pattern = 0
            print('[A,1,1,1,1] and A = 2')
            nl0 = edges_reduced.index(alpha)
            direction = 1    
        elif len(unique) == 2 and alpha > 2:
            pattern = 2
            print('[A,1,1,1,1] and A = 4 + 2x')
            nl0 = edges_reduced.index(alpha)
            direction = 1    
        elif len(unique) == 3:
            beta = (unique - set([1,alpha])).pop()
            if beta == alpha -1:
                pattern = 1
                print('[A,B,1,1,1] and A = B + 1')
                nl0 = edges_reduced.index(alpha)
                d_beta = (edges_reduced.index(beta) - nl0) % n_sides
                if d_beta != 1:
                    print('%i : dbeta should be 3' % d_beta)
                    direction = -1
                else:
                    direction = 1
                
                
            else:
                pattern = 3
                print('[A,B,1,1,1] and A = B + 3 + 2x')
                nl0 = edges_reduced.index(alpha)
                d_beta = (edges_reduced.index(beta) - nl0) % n_sides
                if d_beta != 1:
                    print('%i : dbeta should be 3' % d_beta)
                    direction = -1
                else:
                    direction = 1
                               
    elif len(edges_reduced) == 6:
        
        if len(unique) == 1:
            pattern = 0
            print('[1,1,1,1,1,1] parameter x = 0')
            
        elif len(unique) == 2 and edges_reduced.count(alpha) == 1:
            pattern = 2
            print('[A,1,1,1,1,1] parameter y = 0')
            nl0 = edges_reduced.index(alpha)        
            direction = 1
            
        elif len(unique) == 2 and edges_reduced.count(alpha) == 2:
            k = edges_reduced.index(alpha)
            k_plu1 = (k + 1) % n_sides
            k_min1 = (k - 1) % n_sides
            
            if edges_reduced[k_plu1] == alpha or edges_reduced[k_min1] == alpha:
                pattern = 1
                print('[A,B,1,1,1,1] and A = B -> [A,A,1,1,1,1]')
                nl0 = edges_reduced.index(alpha)
                d_beta = (edges_reduced.index(alpha, nl0 + 1) - nl0) % n_sides
                if d_beta != 1:
                    print('%i : dbeta should be 5' % d_beta)
                    direction = -1
                else:
                    direction = 1
            else:
                pattern = 0
                print('[A,1,1,B,1,1] and A = B ->  [A,1,1,A,1,1]')
                nl0 = edges_reduced.index(alpha)
                direction = 1
            
        elif len(unique) == 3:
            k = edges_reduced.index(alpha)
            k_plu1 = (k + 1) % 6
            k_min1 = (k - 1) % 6
            beta = (unique - set([1,alpha])).pop()
            if edges_reduced[k_plu1] == beta or edges_reduced[k_min1] == beta:
                pattern = 3
                print('[A,B,1,1,1,1] and A = B + 2 + 2x')
                nl0 = edges_reduced.index(alpha)
                d_beta = (edges_reduced.index(beta) - nl0) % n_sides
                if d_beta != 1:
                    print('%i : dbeta should be 5' % d_beta)
                    direction = -1
                else:
                    direction = 1
            else:
                pattern = 2
                print('[A,1,1,B,1,1] and A = B + 2 + 2x')
                nl0 = edges_reduced.index(alpha)
                direction = 1
                
    else:
        print('bad patch!')
        
    if check_pattern != -1:
        if pattern == check_pattern:
            print('everything matches!  great')
            return pattern, nl0, direction
        else:
            print('%i sided patch with pattern #%i' % (n_sides, pattern))
            print('UH OH!!  this pattern doesnt match ilp provided')
            return check_pattern, nl0, direction

    print('Alpha = %i' % alpha)
    print('Beta = %s' % str(beta))
    print('%i sided patch with pattern #%i' % (n_sides, pattern))
    return pattern, nl0, direction

def permute_subdivs(L, reverse = True):
    '''
    returns a list of permutations that preserves the original
    list order of the sides going CW and CCW around the loop
    
    args:
        L = list of integers representing subdivisions on side of polygon
        reverse = Bool, whether to permute reverse direction around the poly.
                  Not necessary for rotationally symetric patterns
    return:
        permutations - lsit of lists
        shift_dir - list of tuple (k, rev) 
                    k represents the index in the original list 
                    which is now the 0th element in the permutation.
    '''
    perms = []
    shift_dir = []
    N = len(L)
    
    print('this is the raw subdivision fed into the permutations')
    print(L)
    for i in range(0, N):  #N - 1
        p = L[i:] + L[:i]
        perms += [p]
        shift_dir += [(i, 1)]
        
        if reverse:
            pr =  L[i:] + L[:i]
            pr.reverse()
            pr = [pr[-1]] + pr[0:len(pr)-1] #this keeps the original start side after list reversal
            perms += [pr]
            #shift_dir += [((i+N-1) % N, -1)] #this may be totally wrong, seems like it is
            shift_dir += [(i, -1)]
    print('these are the supplied permutations')
    for p, sd in zip(perms, shift_dir):
        print((p, sd))
    return perms, shift_dir
    
def reducible(edge_subdivs):
    '''
    see section 2.1 in the paper #TODO paper reference    
    '''
    N = len(edge_subdivs)
    reducible_ks = []
    reduction_ds = []
    reduction_potientials = []
    
    for k, l in enumerate(edge_subdivs):
        k_min_1 = (k - 1) % N
        k_plu_1 = (k + 1) % N
        
        l_k = edge_subdivs[k]
        l_k_min_1 = edge_subdivs[k_min_1]
        l_k_plu_1 = edge_subdivs[k_plu_1]

        if l_k_min_1 > 1 and l_k_plu_1 > 1:
            d = min(l_k_min_1, l_k_plu_1) - 1
            reducible_ks += [k]
            reduction_ds += [d]
            reduction_potientials += [d * l_k]

        
    return reducible_ks, reduction_ds, reduction_potientials
        
def reduce_edges(edge_subdivs, k, d):
    '''
    list of edge subdivisions
    k  - side to reduce on
    d - amount to reduce by
    '''
    N = len(edge_subdivs)
    new_subdivs = []
    k_min_1 = (k - 1) % N
    k_plu_1 = (k + 1) % N
            
    for i in range(0,N):
        
        if i == k_min_1 or i == k_plu_1:
            new_subdivs.append(edge_subdivs[i] - d)
        else:
            new_subdivs.append(edge_subdivs[i])
            
    return new_subdivs
    
class Patch():
    def __init__(self):
        
        self.valid = False
        self.corners = []  #list of vectors representing locations of corners
        self.edge_subdivision = []  # a list of integers representingthe segments of each side.  l0.....lN-1
        self.pattern = 0  #fundamental pattern

        self.reductions = {}
        self.edges_reduced = []
        
        self.active_solution_index = -1
        self.valid_perms = []
        self.valid_rot_dirs = []
        self.valid_patterns = []
        self.valid_solutions = []
        
        self.param_index = 0
        self.delta = 0
        
    def validate(self):
        self.valid = False
        self.valid |= len(self.corners) == len(self.sides)
        self.valid |= (sum(self.edge_subdivision) % 2) == 0  #even subdiv
        
        return self.valid
        
    def permute_and_find_solutions(self):
        
        pat_dict = {}
        pat_dict[2] = 2
        pat_dict[3] = 2
        pat_dict[4] = 5
        pat_dict[5] = 4
        pat_dict[6] = 4
        
        #SPEED UP only test reasonable permutatins
        #To do this...will need to iterate patterns first
        #and only test reasonably rotations/reversals
        perms, rot_dirs = permute_subdivs(self.edge_subdivision)
        
        self.valid_perms = []
        self.valid_rot_dirs = []
        self.valid_patterns = []
        self.valid_solutions = []
        N = len(self.edge_subdivision)
        
        for i, perm in enumerate(perms):
            for pat in range(0,pat_dict[N]):
                if N == 6:
                    sol = PatchSolver6(perm, pat)
                    sleep_time = .7
                elif N == 5:
                    sol = PatchSolver5(perm, pat)
                    sleep_time = .2
                elif N == 4:    
                    sol = PatchSolver4(perm, pat)
                    sleep_time = .2
                elif N == 3:    
                    sol = PatchSolver3(perm, pat)
                    sleep_time = .2
                    
                elif N == 2:
                    print('attempting doublet solver')
                    sol = PatchSolver2(perm, pat)
                    sleep_time = .2
                    
                else:
                    return
                
                print('solving permutation %i for pattern %i' % (i, pat))
                sol.solve(report = False)
                #time.sleep(sleep_time)
                #time.sleep(sleep_time)
                if sol.prob.status == 1:
                    self.valid_perms += [perm]
                    self.valid_rot_dirs += [rot_dirs[i]]
                    self.valid_patterns += [pat]
                    self.valid_solutions += [sol] #<----wonder if this is ok to have a bunch of these instances around
        if len(self.valid_patterns):
            self.active_solution_index = 0
        else:
            self.active_solution_index = -1          
    
    def get_active_solution(self):
        
        n = self.active_solution_index
        
        if n > len(self.valid_perms)-1:
            print('not enough valid perms')
            print(n)
            for perm in self.valid_perms:
                print(perm)
            
            return
        if n == -1:
            print('no valid solutions')
            return
        
        L, rot_dir, pat, sol = self.valid_perms[n], self.valid_rot_dirs[n], self.valid_patterns[n], self.valid_solutions[n]
        
        return L, rot_dir, pat, sol
    
    def get_active_solution_variables(self):
        if self.active_solution_index == -1:
            print('no solution, permute and find solutions first')
            return
        
        
        sol = self.valid_solutions[self.active_solution_index]
        
        if sol.prob_type == 'adjust':
            existing_vars = [int(v.varValue) for v in sol.prob.variables() if "min" not in v.name]
        else:
            existing_vars = [int(v.varValue) for v in sol.prob.variables()]
        return existing_vars
    
    def get_adjust_variable_name(self):
        if self.active_solution_index == -1: return None
        
        sol = self.valid_solutions[self.active_solution_index]
        n = self.param_index
        
        if sol.prob_type == 'adjust':
            var_names = [v.name for v in sol.prob.variables() if "min" not in v.name]
        else:
            var_names = [v.name for v in sol.prob.variables()]
        return var_names[n]
         
    def rotate_solution(self,step):
        #look for same pattern, with different rotation
        if len(self.valid_patterns) == 0:
            print('Need to permute and find solutions or perhaps...infeasible :-(')
            return False
        
        pat_id = self.valid_patterns[self.active_solution_index]
        n_orig, rot_dir = self.valid_rot_dirs[self.active_solution_index]
        
        target_n = (n_orig + step) % len(self.edge_subdivision)
        acceptable_soln_inds = []
        
        for i, sol in enumerate(self.valid_solutions):
            if self.valid_patterns[i] == pat_id:
                n, r_dir = self.valid_rot_dirs[i]
                if r_dir == rot_dir and n == target_n:                    
                    self.active_solution_index = i
                    print('found a solution!')
                    
                    self.param_index = 0
                    self.delta = 0
                    return True
                    
        return False
                     
    def mirror_solution(self):
        #look for same pattern, with different rotation
        if len(self.valid_patterns) == 0:
            print('Need to permute and find solutions or perhaps...infeasible :-(')
            return False
        
        pat_id = self.valid_patterns[self.active_solution_index]
        n_orig, rot_dir = self.valid_rot_dirs[self.active_solution_index]
        
        for i, sol in enumerate(self.valid_solutions):
            if self.valid_patterns[i] == pat_id:
                n, r_dir = self.valid_rot_dirs[i]
                
                if r_dir != rot_dir and n == n_orig:                    
                    
                    self.active_solution_index = i
                    print('found a solution with same L0 but reversed')
                    self.param_index = 0
                    self.delta = 0
                    return True
        return False
    
    def change_pattern(self,pattern):
        '''
        TODO, sort solutions and try to keep the rotation of current solution
        '''
        #look for same pattern, with different rotation
        if len(self.valid_patterns) == 0:
            print('Need to permute and find solutions or perhaps...infeasible :-(')
            return False
        
        print('valid patterns')
        print(list(set(self.valid_patterns)))
        pat_id = pattern
        n_orig, rot_dir = self.valid_rot_dirs[self.active_solution_index]
        
        for i, sol in enumerate(self.valid_solutions):
            if self.valid_patterns[i] == pat_id:
                                   
                self.active_solution_index = i
                print('found a solution with pattern:%i' % pat_id)
                return True
                    
        return False
    
    def adjust_patch(self):
        
        param_index = self.param_index
        delta = self.delta
        
        L, rot_dir, pat, sol = self.get_active_solution()
        existing_vars = self.get_active_solution_variables()
        print('the existing variables are')
        print(existing_vars)
        new_vars = existing_vars.copy()
        new_vars[param_index] = max(0, new_vars[param_index] + delta) #make sure nothing goes negative
        print('the target variables are')
        print(new_vars)
        
        N = len(self.edge_subdivision)
            
        if N == 6:
            new_sol = PatchAdjuster6(L, pat, existing_vars, new_vars)
        elif N == 5:
            new_sol = PatchAdjuster5(L, pat, existing_vars, new_vars)
        elif N == 4:    
            new_sol = PatchAdjuster4(L, pat, existing_vars, new_vars)
        elif N == 3:    
            new_sol = PatchAdjuster3(L, pat, existing_vars, new_vars)
        elif N == 2:    
            new_sol = PatchAdjuster2(L, pat, existing_vars, new_vars)
        else:
            return False
        
        new_sol.solve(report = False)
        
        #print('the adjusted variables are')
        #for v in new_sol.prob.variables():
        #    print(v.name + ' = ' + str(v.varValue))        
        #time.sleep(sleep_time)
        #if this solution is valid...keep it.
        if new_sol.prob.status == 1:
            print('successfuly adjusted patch')
            self.valid_perms += [L]
            self.valid_rot_dirs += [rot_dir]
            self.valid_patterns += [pat]
            self.valid_solutions += [new_sol]
            self.active_solution_index = len(self.valid_perms) -1
            print('the adjusted variables') 
            new_vars = self.get_active_solution_variables()
            print(new_vars)
            return True
        else:
            print('desired adjustment not possible')
            return False
    def report(self):
        if self.active_solution_index == -1:
            print('no active soluton')
            return
        
        self.valid_solutions[self.active_solution_index].report()
        
        
    ######### DEPRICATED AND ONLY USEFUL FOR DEMO/UNDERSTANDING##########
    def reduce_input_cornered(self):
        '''
        slices off the biggest quad patches it can at a time
        this is not needed for patch solving, just proves
        generality of the approach
        '''
        print('THIS METHOD IS DEPRICATED AND SHOULD NOT BE USED')
        edge_subdivs = self.edge_subdivision.copy()
        print('\n')
        print('Reduction series for edges')
        print(edge_subdivs)
        ks, ds, pots = reducible(edge_subdivs)
        
        if not len(ks):
            print('already maximally reduced')
            self.edges_reduced = edge_subdivs
            return
        
        
        iters = 0
        while len(ks) and iters < 10:
            iters += 1
            best = pots.index(max(pots))
            new_subdivs = reduce_edges(edge_subdivs, ks[best], ds[best])
            
            ks, ds, pots = reducible(new_subdivs)
            print(new_subdivs)
            edge_subdivs = new_subdivs
         
        self.edges_reduced = new_subdivs
    
    def reduce_input_centered(self):
        '''
        slices off the smallest quad patches it can at a time

        this is not needed for patch solving, just proves
        generality of the approach
        '''
        
        edge_subdivs = self.edge_subdivision.copy()
        ks, ds, pots = reducible(edge_subdivs)
        print(edge_subdivs)
        if not len(ks):
            print('maximally reduced')
            return
        iters = 0
        while len(ks) and iters < 10:
            iters += 1
            best = pots.index(min(pots))
            new_subdivs = reduce_edges(edge_subdivs, ks[best], ds[best])
            
            
            ks, ds, pots = reducible(new_subdivs)
            print(new_subdivs)
            edge_subdivs = new_subdivs
        
        print('centered reduced in %i iters' % iters)
   
        self.edges_reduced = new_subdivs
    
    def reduce_input_padding(self):
        '''
        slices 1 strip off the biggest quad patches it can at a time
        this is not needed for patch solving, just proves
        generality of the approach
        '''
        
        edge_subdivs = self.edge_subdivision.copy()
        print('\n')
        print('Reduction series for edges')
        print(edge_subdivs)
        ks, ds, pots = reducible(edge_subdivs)
        
        if not len(ks):
            print('already maximally reduced')
            self.edges_reduced = edge_subdivs
            return
        
        iters = 0
        while len(ks) and iters < 10:
            iters += 1
            best = pots.index(max(pots))
            new_subdivs = reduce_edges(edge_subdivs, ks[best], 1)
            
            ks, ds, pots = reducible(new_subdivs)
            print(new_subdivs)
            edge_subdivs = new_subdivs
         
        self.edges_reduced = new_subdivs
            
    def identify_patch_pattern(self):   
        n_sides = len(self.edges_reduced)
        unique = set(self.edges_reduced)
        alpha = max(unique)
        beta = None
        x = None
        
        if len(self.edge_subdivision) == 3:
            if alpha == 2:
                self.pattern = 0
            else:
                self.pattern = 1
                x = (alpha - 4)/2
                
        elif len(self.edge_subdivision) == 4:
            if alpha == 1:
                self.pattern = 0
                
            elif len(unique) == 2 and self.edges_reduced.count(alpha) == 1:
                #there is only one alp
                x = (alpha - 3) / 2
                if x == 0:
                    self.pattern = 2
                    print('[A,1,1,1] and x = 0, need to parameterize y?')
                else:
                    print('[A,1,1,1] and A = 3 + 2x   REally unsure on these!')
                    self.pattern = 3
                    
            elif len(unique) == 2 and self.edges_reduced.count(alpha) == 2:
                self.pattern = 1
                print('[A,B,1,1] and A = B -> [A,A,1,1]')
                
               
            elif len(unique) == 3:
                self.pattern = 4
                print('[A,B,1,1]  A = B + 2 + 2x')
                beta = (unique - set([1,alpha])).pop()
                
                       
        elif len(self.edge_subdivision) == 5:
            if len(unique) == 2 and alpha ==2:
                self.pattern = 0
                print('[A,1,1,1,1] and A = 2')
                    
            elif len(unique) == 2 and alpha > 2:
                self.pattern = 2
                print('[A,1,1,1,1] and A = 4 + 2x')
                    
            elif len(unique) == 3:
                beta = (unique - set([1,alpha])).pop()
                if beta == alpha -1:
                    self.pattern = 1
                    print('[A,B,1,1,1] and A = B + 1')
                else:
                    self.pattern = 3
                    print('[A,B,1,1,1] and A = B + 3 + 2x')
                    
                                   
        elif len(self.edge_subdivision) == 6:
            
            if len(unique) == 1:
                self.pattern = 0
                print('[1,1,1,1,1,1] parameter x = 0')
                
            elif len(unique) == 2 and self.edges_reduced.count(alpha) == 1:
                self.pattern = 2
                print('[A,1,1,1,1,1] parameter y = 0')
                
            elif len(unique) == 2 and self.edges_reduced.count(alpha) == 2:
                k = self.edges_reduced.index(alpha)
                k_plu1 = (k + 1) % n_sides
                k_min1 = (k - 1) % n_sides
                
                if self.edges_reduced[k_plu1] == alpha or self.edges_reduced[k_min1] == alpha:
                    self.pattern = 1
                    print('[A,B,1,1,1,1] and A = B -> [A,A,1,1,1,1]')
                else:
                    self.pattern = 0
                    print('[A,1,1,B,1,1] and A = B ->  [A,1,1,A,1,1]')
                    
                
            elif len(unique) == 3:
                k = self.edges_reduced.index(alpha)
                k_plu1 = (k + 1) % 6
                k_min1 = (k - 1) % 6
                beta = (unique - set([1,alpha])).pop()
                if self.edges_reduced[k_plu1] == beta or self.edges_reduced[k_min1] == beta:
                    self.pattern = 3
                    print('[A,B,1,1,1,1] and A = B + 2 + 2x')
                else:
                    self.pattern = 2
                    print('[A,1,1,B,1,1] and A = B + 2 + 2x')
                    
        else:
            print('bad patch!')
            
        print('Alpha = %i' % alpha)
        print('Beta = %s' % str(beta))
        print('%i sided patch with pattern #%i' % (n_sides, self.pattern))
        k0 = self.edges_reduced.index(alpha)
        print('l_0  side is side #%i, value %i' % (k0, self.edges[k0]))

#    def rotate_solution(self,direction = 1):

def add_constraints_2p0(prob, L, p0, p1, x, y):
    print('constraints added for doublet pattern 0')
    prob +=  2*p1 + 2*x + y    == L[0] - 3, "Side 0"
    prob +=  2*p0 + y          == L[1] - 1, "Side 1"
          
def add_constraints_2p1(prob, L, p0, p1, x, y):
    print('constraints added for doublet pattern 1') 
    prob +=  2*p1 + x + y      == L[0] - 2, "Side 0"
    prob +=  2*p0 + x + y      == L[1] - 2, "Side 1"
    
    
def add_constraints_3p0(prob, L, p0, p1, p2):
    prob +=  p2 + p1            == L[0] - 2, "Side 0"
    prob +=  p0 + p2            == L[1] - 1, "Side 1"
    prob +=  p1 + p0            == L[2] - 1, "Side 2"

def add_constraints_3p1(prob, L, p0, p1, p2, x, q1, q2):
    prob +=  p2 + p1 +2*x + q1 + q2    == L[0] - 4, "Side 0"
    prob +=  p0 + p2 + q2              == L[1] - 1, "Side 1"
    prob +=  p1 + p0 + q1              == L[2] - 1, "Side 2"
    
def add_constraints_4p0(prob, L, p0, p1, p2, p3):
    prob +=  p3 + p1            == L[0] - 1, "Side 0"
    prob +=  p0 + p2            == L[1] - 1, "Side 1"
    prob +=  p1 + p3            == L[2] - 1, "Side 2"
    prob +=  p2 + p0            == L[3] - 1, "Side 3"

def add_constraints_4p1(prob, L, p0, p1, p2, p3, x):
    prob +=  p3 + p1 + x        == L[0] - 2, "Side 0"
    prob +=  p0 + p2 + x        == L[1] - 2, "Side 1"
    prob +=  p1 + p3            == L[2] - 1, "Side 2"
    prob +=  p2 + p0            == L[3] - 1, "Side 3"
    
def add_constraints_4p2(prob, L, p0, p1, p2, p3, x, y):
    prob +=  p3 + p1 + x + y    == L[0] - 3, "Side 0"
    prob +=  p0 + p2 + x        == L[1] - 1, "Side 1"
    prob +=  p1 + p3            == L[2] - 1, "Side 2"
    prob +=  p2 + p0 + y        == L[3] - 1, "Side 3"

def add_constraints_4p3(prob, L, p0, p1, p2, p3, x, q1):
    '''
    p1 + q1 = constant
    '''
    prob +=  p3 + p1 + 2*x +q1    == L[0] - 3, "Side 0"
    prob +=  p0 + p2              == L[1] - 1, "Side 1"
    prob +=  p1 + p3 + q1         == L[2] - 1, "Side 2"
    prob +=  p2 + p0              == L[3] - 1, "Side 3"
   
def add_constraints_4p4(prob, L, p0, p1, p2, p3, x, y, q1):
    '''
    p0 + q0 = constant
    '''
    prob +=  p1 + p3 + 2*x + y +q1  == L[0] - 4, "Side 0"
    prob +=  p0 + p2 + y            == L[1] - 2, "Side 1"
    prob +=  p1 + p3  +q1           == L[2] - 1, "Side 2"
    prob +=  p2 + p0                == L[3] - 1, "Side 3"

def add_constraints_5p0(prob, L, p0, p1, p2, p3, p4):
    prob +=  p4 + p1            == L[0] - 2, "Side 0"
    prob +=  p0 + p2            == L[1] - 1, "Side 1"
    prob +=  p1 + p3            == L[2] - 1, "Side 2"
    prob +=  p2 + p4            == L[3] - 1, "Side 3"
    prob +=  p3 + p0            == L[4] - 1, "Side 4"
   
def add_constraints_5p1(prob, L, p0, p1, p2, p3, p4, x, q4): 
    '''
    q4 + p4 = constant
    '''
    prob +=  p4 + p1 + x + q4       == L[0] - 2, "Side 0"
    prob +=  p0 + p2 + x            == L[1] - 1, "Side 1"
    prob +=  p1 + p3                == L[2] - 1, "Side 2"
    prob +=  p2 + p4 + q4           == L[3] - 1, "Side 3"
    prob +=  p3 + p0                == L[4] - 1, "Side 4"
    
def add_constraints_5p2(prob, L, p0, p1, p2, p3, p4, x, q0, q1, q4):
    '''
    p0 + q0 = constant
    p1 + q1 = constant
    '''
    prob +=  p4 + p1 + 2*x + q1 + q4  == L[0] - 4, "Side 0"
    prob +=  p0 + p2  + q0            == L[1] - 1, "Side 1"
    prob +=  p1 + p3 + q1             == L[2] - 1, "Side 2"
    prob +=  p2 + p4 + q4             == L[3] - 1, "Side 3"
    prob +=  p3 + p0 + q0             == L[4] - 1, "Side 4"
  
def add_constraints_5p3(prob, L, p0, p1, p2, p3, p4, x, y, q1, q4):
    '''
    p0 + q1 = constant
    p4 + q4 = constant
    '''
    prob +=  p4 + p1 + 2*x + y + q1 + q4  == L[0] - 5, "Side 0"
    prob +=  p0 + p2 + y                  == L[1] - 2, "Side 1"
    prob +=  p1 + p3 + q1                 == L[2] - 1, "Side 2"
    prob +=  p2 + p4 + q4                 == L[3] - 1, "Side 3"
    prob +=  p3 + p0                      == L[4] - 1, "Side 4"
                
def add_constraints_6p0(prob, L, p0, p1, p2, p3, p4, p5, x): 
    prob +=  p5 + p1 + x        == L[0] - 1, "Side 0"
    prob +=  p0 + p2            == L[1] - 1, "Side 1"
    prob +=  p1 + p3            == L[2] - 1, "Side 2"
    prob +=  p2 + p4 + x        == L[3] - 1, "Side 3"
    prob +=  p3 + p5            == L[4] - 1, "Side 4"
    prob +=  p4 + p0            == L[5] - 1, "Side 5"
    
def add_constraints_6p1(prob, L, p0, p1, p2, p3, p4, p5, x, y, z, w): 
    prob +=  p5 + p1 + x + y       == L[0] - 2, "Side 0"
    prob +=  p0 + p2 + x + z       == L[1] - 2, "Side 1"
    prob +=  p1 + p3 + w           == L[2] - 1, "Side 2"
    prob +=  p2 + p4 + y           == L[3] - 1, "Side 3"
    prob +=  p3 + p5 + z           == L[4] - 1, "Side 4"
    prob +=  p4 + p0 + w           == L[5] - 1, "Side 5"
    
def add_constraints_6p2(prob, L, p0, p1, p2, p3, p4, p5, x, y, q0, q3):  
    '''
    q3 + p3 = constant, q0 + p0 = constant
    '''
    prob +=  p5 + p1 + 2*x + y      == L[0] - 3, "Side 0"
    prob +=  p0 + p2 + q0           == L[1] - 1, "Side 1"
    prob +=  p1 + p3 + q3           == L[2] - 1, "Side 2"
    prob +=  p2 + p4 + y            == L[3] - 1, "Side 3"
    prob +=  p3 + p5 + q3           == L[4] - 1, "Side 4"
    prob +=  p4 + p0 + q0           == L[5] - 1, "Side 5"
    
def add_constraints_6p3(prob, L, p0, p1, p2, p3, p4, p5, x, y, z, q3):
    '''
    q3 + p3 = constant
    '''
    prob +=  p5 + p1 + 2*x + y + z  == L[0] - 4, "Side 0"
    prob +=  p0 + p2 + y            == L[1] - 2, "Side 1"
    prob +=  p1 + p3 + q3           == L[2] - 1, "Side 2"
    prob +=  p2 + p4 + z            == L[3] - 1, "Side 3"
    prob +=  p3 + p5 + q3           == L[4] - 1, "Side 4"
    prob +=  p4 + p0                == L[5] - 1, "Side 5"
    
                  
class PatchSolver6(object):
    def __init__(self, L, pattern):
        self.pattern = pattern
        self.L = L
        self.prob_type = 'solve'
        self.prob = LpProblem("N6 Patch", LpMaximize)

        max_p0 = float(min(L[1], L[5]) - 1)
        max_p1 = float(min(L[0], L[2]) - 1)
        max_p2 = float(min(L[1], L[3]) - 1)
        max_p3 = float(min(L[2], L[4]) - 1)
        max_p4 = float(min(L[3], L[5]) - 1)
        max_p5 = float(min(L[4], L[0]) - 1)

        p0 = LpVariable("p0",0,max_p0,LpInteger)
        p1 = LpVariable("p1",0,max_p1,LpInteger)
        p2 = LpVariable("p2",0,max_p2,LpInteger)
        p3 = LpVariable("p3",0,max_p3,LpInteger)
        p4 = LpVariable("p4",0,max_p4,LpInteger)
        p5 = LpVariable("p5",0,max_p5,LpInteger)
        
        q0 = LpVariable("q0",0,max_p0,LpInteger)
        q3 = LpVariable("q3",0,max_p3,LpInteger)
        
        x = LpVariable("x",0,None,LpInteger)
        y = LpVariable("y",0,None,LpInteger)
        z = LpVariable("z",0,None,LpInteger)
        w = LpVariable("w",0,None,LpInteger)
        
        #first objective, maximize padding  
        self.prob += p0 + p1 + p2 + p3 + p4 + p5
        
        if self.pattern == 0:
            add_constraints_6p0(self.prob, L,p0,p1,p2,p3,p4,p5,x)
        elif self.pattern == 1:
            add_constraints_6p1(self.prob, L,p0,p1,p2,p3,p4,p5,x,y,z,w)
        elif self.pattern == 2:
            add_constraints_6p2(self.prob, L,p0,p1,p2,p3,p4,p5,x,y,q0,q3)
        elif self.pattern == 3:
            add_constraints_6p3(self.prob, L,p0,p1,p2,p3,p4,p5,x,y,z,q3)
    
    def solve(self, report = True):
        #LpSolverDefault.msg = 1
        self.prob.solve()
        
        if self.prob.status == 1 and report:
            self.report()
        
    def report(self):
        print(self.L)
        print('%i sided Patch with Pattern: %i' % (len(self.L),self.pattern))
        print('Status: ' + LpStatus[self.prob.status])
        for v in self.prob.variables():
            print(v.name + ' = ' + str(v.varValue))

class PatchAdjuster6():
    def __init__(self, L, pattern, existing_vars, target_vars):
        '''
        L needs to be a list of edge subdivisions with Alpha being L[0]
        you may need to rotate or reverse L to adequately represent the patch
        '''
        self.prob_type = 'adjust'
        self.prob = LpProblem("N6 Patch Adjust", LpMinimize)
        self.pattern = pattern
        self.L = L
        
        max_p0 = float(min(L[1], L[5]) - 1)
        max_p1 = float(min(L[0], L[2]) - 1)
        max_p2 = float(min(L[1], L[3]) - 1)
        max_p3 = float(min(L[2], L[4]) - 1)
        max_p4 = float(min(L[3], L[5]) - 1)
        max_p5 = float(min(L[4], L[0]) - 1)

        p0 = LpVariable("p0",0,max_p0,LpInteger)
        p1 = LpVariable("p1",0,max_p1,LpInteger)
        p2 = LpVariable("p2",0,max_p2,LpInteger)
        p3 = LpVariable("p3",0,max_p3,LpInteger)
        p4 = LpVariable("p4",0,max_p4,LpInteger)
        p5 = LpVariable("p5",0,max_p5,LpInteger)
        
        q0 = LpVariable("q0",0,max_p0,LpInteger)
        q3 = LpVariable("q3",0,max_p3,LpInteger)
        
        x = LpVariable("x",0,None,LpInteger)
        y = LpVariable("y",0,None,LpInteger)
        z = LpVariable("z",0,None,LpInteger)
        w = LpVariable("w",0,None,LpInteger)

        changes = []
        for i, (tv, ev) in enumerate(zip(target_vars,existing_vars)):
            if ev != tv:
                changes += [i]
        
        if self.pattern == 0:
            PULP_vars = [p0,p1,p2,p3,p4,p5,x]
            
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
            
            #set the target constraints rigidly
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
            #add the normal patch topology constraint    
            add_constraints_6p0(self.prob,L, p0, p1, p2, p3,p4,p5,x)
            
            
        elif self.pattern == 1:
            PULP_vars = [p0,p1,p2,p3,p4,p5,x,y,z,w]
            #set the objective
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars): #I may need to re-eval this statement
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
                
            #set the target constraints rigidly
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
            add_constraints_6p1(self.prob, L, p0, p1, p2, p3, p4,p5,x,y,z,w)
        
        elif self.pattern == 2:
            PULP_vars = [p0,p1,p2,p3,p4,p5,x,y,q0,q3]
            #set the objective
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
            #set the target constraints rigidly
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
                    
            add_constraints_6p2(self.prob, L, p0,p1,p2,p3,p4,p5,x,y)
        
        elif self.pattern == 3:
            PULP_vars = [p0,p1,p2,p3,p4,p5,x,y,z,q3]
            #set the objective
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
            #set the target constraints rigidly
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
            add_constraints_6p3(self.prob, L, p0,p1,p2,p3,p4,p5,x,y,z,q3)
        
    def solve(self, report = True):
        ##LpSolverDefault.msg = 1
        self.prob.solve()
        
        if self.prob.status == 1 and report:
            self.report()
            
    def report(self):
        print(self.L)
        if self.prop.status == 0:
            print('still solving...')
            return
        print('%i sided Patch with Pattern: %i' % (len(self.L),self.pattern))
        print('Status: ' + LpStatus[self.prob.status])
        for v in self.prob.variables():
            print(v.name + ' = ' + str(v.varValue))
                            
class PatchSolver5():
    def __init__(self, L, pattern):
        '''
        L needs to be a list of edge subdivisions with Alpha being L[0]
        you may need to rotate or reverse L to adequately represent the patch
        '''
        self.prob_type = 'solve'
        self.prob = LpProblem("N5 Patch", LpMaximize)
        self.pattern = pattern
        self.L = L
        
        max_p0 = float(min(L[4] ,L[1]) - 1)
        max_p1 = float(min(L[0], L[2]) - 1)
        max_p2 = float(min(L[1], L[3]) - 1)
        max_p3 = float(min(L[2], L[4]) - 1)
        max_p4 = float(min(L[3], L[0]) - 1)

        p0 = LpVariable("p0",0,max_p0,LpInteger)
        p1 = LpVariable("p1",0,max_p1,LpInteger)
        p2 = LpVariable("p2",0,max_p2,LpInteger)
        p3 = LpVariable("p3",0,max_p3,LpInteger)
        p4 = LpVariable("p4",0,max_p4,LpInteger)
        
        q0 = LpVariable("q0",0,max_p0,LpInteger)
        q1 = LpVariable("q1",0,max_p1,LpInteger)
        q4 = LpVariable("q4",0,max_p4,LpInteger)
        
        x = LpVariable("x",0,None,LpInteger)
        y = LpVariable("y",0,None,LpInteger)

        #first objective, maximize padding  
        self.prob += p0 + p1 + p2 + p3 + p4
        
        if self.pattern == 0:
            add_constraints_5p0(self.prob, L, p0, p1, p2, p3, p4)
        elif self.pattern == 1:
            add_constraints_5p1(self.prob, L, p0, p1, p2, p3, p4, x, q4)
        elif self.pattern == 2:
            add_constraints_5p2(self.prob, L, p0, p1, p2, p3, p4, x, q0, q1, q4)
        elif self.pattern == 3:
            add_constraints_5p3(self.prob, L, p0, p1, p2, p3, p4, x, y, q1, q4)
            
    def solve(self, report = True):
        #LpSolverDefault.msg = 1
        self.prob.solve()
        
        if self.prob.status == 1 and report:
            self.report()
        
    def report(self):
        
        print(self.L)
        if self.prob.status == 0:
            print('still soliving...ask later')
        print('%i sided Patch with Pattern: %i' % (len(self.L),self.pattern))
        print('Status: ' + LpStatus[self.prob.status])
        for v in self.prob.variables():
            print(v.name + ' = ' + str(v.varValue))

class PatchAdjuster5():
    def __init__(self, L, pattern, existing_vars, target_vars):
        '''
        L needs to be a list of edge subdivisions with Alpha being L[0]
        you may need to rotate or reverse L to adequately represent the patch
        '''
        self.prob_type = 'adjust'
        self.prob = LpProblem("N5 Patch Adjust", LpMinimize)
        self.pattern = pattern
        self.L = L
        
        max_p0 = float(min(L[4] ,L[1]) - 1)
        max_p1 = float(min(L[0], L[2]) - 1)
        max_p2 = float(min(L[1], L[3]) - 1)
        max_p3 = float(min(L[2], L[4]) - 1)
        max_p4 = float(min(L[3], L[0]) - 1)

        p0 = LpVariable("p0",0,max_p0,LpInteger)
        p1 = LpVariable("p1",0,max_p1,LpInteger)
        p2 = LpVariable("p2",0,max_p2,LpInteger)
        p3 = LpVariable("p3",0,max_p3,LpInteger)
        p4 = LpVariable("p4",0,max_p4,LpInteger)
        
        q0 = LpVariable("q0",0,max_p0,LpInteger)
        q1 = LpVariable("q1",0,max_p1,LpInteger)
        q4 = LpVariable("q4",0,max_p4,LpInteger)
        
        x = LpVariable("x",0,None,LpInteger)
        y = LpVariable("y",0,None,LpInteger)

        changes = []
        for i, (tv, ev) in enumerate(zip(target_vars,existing_vars)):
            if ev != tv:
                changes += [i]
        
        if self.pattern == 0:
            PULP_vars = [p0,p1,p2,p3,p4]
            
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
            
            #set the target constraints rigidly
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
            #add the normal patch topology constraint    
            add_constraints_5p0(self.prob, L, p0, p1, p2, p3,p4)
            
            
        elif self.pattern == 1:
            PULP_vars = [p0,p1,p2,p3,p4,x,q4]
            #set the objective
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
                
            #set the target constraints rigidly
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
            add_constraints_5p1(self.prob, L, p0, p1, p2, p3, p4, x, q4)
        
        elif self.pattern == 2:
            PULP_vars = [p0,p1,p2,p3,p4,x, q0, q1, q4]
            #set the objective
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
            #set the target constraints rigidly
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
                    
            add_constraints_5p2(self.prob, L, p0, p1, p2, p3, p4, x, q0, q1, q4)
        
        elif self.pattern == 3:
            PULP_vars = [p0,p1,p2,p3,p4,x,y, q1, q4]
            #set the objective
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
            #set the target constraints rigidly
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
            add_constraints_5p3(self.prob, L, p0, p1, p2, p3, p4, x, y, q1, q4)
        
    def solve(self, report = True):
        #LpSolverDefault.msg = 1
        self.prob.solve()
        
        if self.prob.status == 1 and report:
            self.report()
            
    def report(self):
        print(self.L)
        print('%i sided Patch with Pattern: %i' % (len(self.L),self.pattern))
        print('Status: ' + LpStatus[self.prob.status])
        for v in self.prob.variables():
            print(v.name + ' = ' + str(v.varValue))

class PatchSolver4():
    def __init__(self, L, pattern):
        '''
        L needs to be a list of edge subdivisions with Alpha being L[0]
        you may need to rotate or reverse L to adequately represent the patch
        '''
        self.prob_type = 'solve'
        self.prob = LpProblem("N4 Patch", LpMaximize)
        self.pattern = pattern
        self.L = L
        
        max_p0 = float(min(L[3], L[1]) - 1)
        max_p1 = float(min(L[0], L[2]) - 1)
        max_p2 = float(min(L[1], L[3]) - 1)
        max_p3 = float(min(L[2], L[0]) - 1)
        p0 = LpVariable("p0",0,max_p0,LpInteger)
        p1 = LpVariable("p1",0,max_p1,LpInteger)
        p2 = LpVariable("p2",0,max_p2,LpInteger)
        p3 = LpVariable("p3",0,max_p3,LpInteger)

        q1 = LpVariable("q1",0,max_p1,LpInteger)
        
        x = LpVariable("x",0,None,LpInteger)
        y = LpVariable("y",0,None,LpInteger)

        #first objective, maximize padding 
        self.prob += p0 + p1 + p2 + p3
        
        if self.pattern == 0:
            add_constraints_4p0(self.prob, L, p0, p1, p2, p3)
        elif self.pattern == 1:
            add_constraints_4p1(self.prob, L, p0, p1, p2, p3, x)
        elif self.pattern == 2:
            add_constraints_4p2(self.prob, L, p0, p1, p2, p3, x, y)
        elif self.pattern == 3:
            add_constraints_4p3(self.prob, L, p0, p1, p2, p3, x, q1)
        elif self.pattern == 4:
            add_constraints_4p4(self.prob, L, p0, p1, p2, p3, x, y, q1)

    def solve(self, report = True):
        #LpSolverDefault.msg = 1
        self.prob.solve()
        
        if self.prob.status == 1 and report:
            self.report()
        
    def report(self):
        print(self.L)
        print('%i sided Patch with Pattern: %i' % (len(self.L),self.pattern))
        print('Status: ' + LpStatus[self.prob.status])
        for v in self.prob.variables():
            print(v.name + ' = ' + str(v.varValue))

class PatchAdjuster4():
    def __init__(self, L, pattern, existing_vars, target_vars):
        '''
        L needs to be a list of edge subdivisions with Alpha being L[0]
        you may need to rotate or reverse L to adequately represent the patch
        '''
        self.prob_type = 'adjust'
        self.prob = LpProblem("N4 Patch Adjust", LpMinimize)
        self.pattern = pattern
        self.L = L
        
        max_p0 = float(min(L[3], L[1]) - 1)
        max_p1 = float(min(L[0], L[2]) - 1)
        max_p2 = float(min(L[1], L[3]) - 1)
        max_p3 = float(min(L[2], L[0]) - 1)
        p0 = LpVariable("p0",0,max_p0,LpInteger)
        p1 = LpVariable("p1",0,max_p1,LpInteger)
        p2 = LpVariable("p2",0,max_p2,LpInteger)
        p3 = LpVariable("p3",0,max_p3,LpInteger)

        q1 = LpVariable("q1",0,max_p1,LpInteger)
         
        x = LpVariable("x",0,None,LpInteger)
        y = LpVariable("y",0,None,LpInteger)

        changes = []
        for i, (tv, ev) in enumerate(zip(target_vars,existing_vars)):
            if ev != tv:
                changes += [i]
        
        if self.pattern == 0:
            PULP_vars = [p0,p1,p2,p3]
            
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
            
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
            
            #add the normal patch topology constraint    
            add_constraints_4p0(self.prob, L, p0, p1, p2, p3)
            
            
        elif self.pattern == 1:
            PULP_vars = [p0,p1,p2,p3,x]
            #set the objective
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
                
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
            add_constraints_4p1(self.prob, L, p0, p1, p2, p3, x)
        elif self.pattern == 2:
            PULP_vars = [p0,p1,p2,p3,x,y]
            #set the objective
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
            
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
            add_constraints_4p2(self.prob, L, p0, p1, p2, p3, x, y)
        
        elif self.pattern == 3:
            PULP_vars = [p0,p1,p2,p3,x, q1]
            #set the objective
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
                    
            add_constraints_4p3(self.prob, L, p0, p1, p2, p3, x, q1)
        
        elif self.pattern == 4:
            PULP_vars = [p0,p1,p2,p3,x,y, q1]
            #set the objective
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
            
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
                    
            add_constraints_4p4(self.prob, L, p0, p1, p2, p3, x, y, q1)

    def solve(self, report = True):
        #LpSolverDefault.msg = 1
        self.prob.solve()
        
        if self.prob.status == 1 and report:
            self.report()
            
    def report(self):
        print(self.L)
        print('%i sided Patch with Pattern: %i' % (len(self.L),self.pattern))
        print('Status: ' + LpStatus[self.prob.status])
        for v in self.prob.variables():
            print(v.name + ' = ' + str(v.varValue))
                
                
class PatchSolver3():
    def __init__(self, L, pattern):
        '''
        L needs to be a list of edge subdivisions with Alpha being L[0]
        you may need to rotate or reverse L to adequately represent the patch
        '''
        self.prob_type = 'solve'
        self.prob = LpProblem("N6 Patch", LpMaximize)
        self.adjust_prob = None
        
        self.pattern = pattern
        self.L = L
        
        max_p0 = float(min(L[2], L[1]) - 1)
        max_p1 = float(min(L[0], L[2]) - 1)
        max_p2 = float(min(L[1], L[0]) - 1)

        p0 = LpVariable("p0",0,max_p0,LpInteger)
        p1 = LpVariable("p1",0,max_p1,LpInteger)
        p2 = LpVariable("p2",0,max_p2,LpInteger)
       

        x = LpVariable("x",0,None,LpInteger)
        
        q1 = LpVariable("q1",0,max_p1,LpInteger)
        q2 = LpVariable("q2",0,max_p2,LpInteger)

        #first objective, maximize padding
        self.prob += p0 + p1 + p2    
    
        if self.pattern == 0:
            add_constraints_3p0(self.prob, L, p0, p1, p2)
        elif self.pattern == 1:
            add_constraints_3p1(self.prob, L, p0, p1, p2, x, q1, q2)
    
    def solve(self, report = True):
        #LpSolverDefault.msg = 1
        self.prob.solve()
        
        if self.prob.status == 1 and report:
            self.report()
        
    def report(self):
        print(self.L)
        print('%i sided Patch with Pattern: %i' % (len(self.L),self.pattern))
        print('Status: ' + LpStatus[self.prob.status])
        for v in self.prob.variables():
            print(v.name + ' = ' + str(v.varValue))
            
class PatchAdjuster3():
    def __init__(self, L, pattern, existing_vars, target_vars):
        '''
        L needs to be a list of edge subdivisions with Alpha being L[0]
        you may need to rotate or reverse L to adequately represent the patch
        '''
        self.prob_type = 'adjust'
        self.prob = LpProblem("N3 Patch Adjust", LpMinimize)
        self.pattern = pattern
        self.L = L
        
        max_p0 = float(min(L[2], L[1]) - 1)
        max_p1 = float(min(L[0], L[2]) - 1)
        max_p2 = float(min(L[1], L[0]) - 1)

        p0 = LpVariable("p0",0,max_p0,LpInteger)
        p1 = LpVariable("p1",0,max_p1,LpInteger)
        p2 = LpVariable("p2",0,max_p2,LpInteger)

        x = LpVariable("x",0,None,LpInteger)
        q1 = LpVariable("q1", 0, max_p1, LpInteger)
        q2 = LpVariable("q2", 0, max_p2, LpInteger)

        changes = []
        for i, (tv, ev) in enumerate(zip(target_vars,existing_vars)):
            if ev != tv:
                changes += [i]
        
        if self.pattern == 0:
            PULP_vars = [p0,p1,p2]
            
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
            
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
            #add the normal patch topology constraint    
            add_constraints_3p0(self.prob, L, p0, p1, p2)
            
            
        elif self.pattern == 1:
            PULP_vars = [p0,p1,p2,x,q1,q2]
            #set the objective
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
                
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
                    
            add_constraints_3p1(self.prob, L, p0, p1, p2, x, q1, q2)
        

    def solve(self, report = True):
        #LpSolverDefault.msg = 1
        self.prob.solve()
        
        if self.prob.status == 1 and report:
            self.report()
            
    def report(self):
        print(self.L)
        print('%i sided Patch with Pattern: %i' % (len(self.L),self.pattern))
        print('Status: ' + LpStatus[self.prob.status])
        for v in self.prob.variables():
            print(v.name + ' = ' + str(v.varValue))
            
            
class PatchSolver2():
    def __init__(self, L, pattern):
        '''
        L needs to be a list of edge subdivisions with Alpha being L[0]
        you may need to rotate or reverse L to adequately represent the patch
        '''
        self.prob_type = 'solve'
        self.prob = LpProblem("N2 Patch", LpMaximize)
        self.adjust_prob = None
        
        self.pattern = pattern
        self.L = L
        
        max_p0 = float(math.floor(L[1]/2))
        max_p1 = float(math.floor(L[0]/2))
        
        p0 = LpVariable("p0",0,max_p0,LpInteger)
        p1 = LpVariable("p1",0,max_p1,LpInteger)
       

        x = LpVariable("x",0,None,LpInteger)
        y = LpVariable("y",0,None,LpInteger)
        

        #first objective, maximize padding
        self.prob += p0 + p1   
    
        if self.pattern == 0:
            add_constraints_2p0(self.prob, L, p0, p1, x, y)
        elif self.pattern == 1:
            add_constraints_2p1(self.prob, L, p0, p1, x, y)
    
    def solve(self, report = True):
        #LpSolverDefault.msg = 1
        self.prob.solve()
        
        if self.prob.status == 1 and report:
            self.report()
        
    def report(self):
        print(self.L)
        print('%i sided Patch with Pattern: %i' % (len(self.L),self.pattern))
        print('Status: ' + LpStatus[self.prob.status])
        for v in self.prob.variables():
            print(v.name + ' = ' + str(v.varValue))
            
class PatchAdjuster2():
    def __init__(self, L, pattern, existing_vars, target_vars):
        '''
        L needs to be a list of edge subdivisions with Alpha being L[0]
        you may need to rotate or reverse L to adequately represent the patch
        '''
        self.prob_type = 'adjust'
        self.prob = LpProblem("N2 Patch Adjust", LpMinimize)
        self.pattern = pattern
        self.L = L
        
        max_p0 = float(math.floor(L[1]/2))
        max_p1 = float(math.floor(L[0]/2))
        
        p0 = LpVariable("p0",0,max_p0,LpInteger)
        p1 = LpVariable("p1",0,max_p1,LpInteger)

        x = LpVariable("x",0,None,LpInteger)
        y = LpVariable("y",0,None,LpInteger)
        

        changes = []
        for i, (tv, ev) in enumerate(zip(target_vars,existing_vars)):
            if ev != tv:
                changes += [i]
        
        if self.pattern == 0:
            PULP_vars = [p0,p1,x,y]
            
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
            
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
            #add the normal patch topology constraint    
            add_constraints_2p0(self.prob, L, p0, p1, x, y)
            
            
        elif self.pattern == 1:
            PULP_vars = [p0,p1,x,y]
            #set the objective
            #new variable for minimization problem
            min_vars = [LpVariable("min_" +v.name,0,None,LpInteger) for v in PULP_vars]
            
            self.prob += lpSum(min_vars), "Minimize the sum of differences in variables"
            
            for i, ev in enumerate(existing_vars):
                self.prob += min_vars[i] >= -(PULP_vars[i] - ev), 'abs val neg contstaint ' + str(i)
                self.prob += min_vars[i] >= (PULP_vars[i] - ev), 'abs val pos contstaint ' + str(i)
                
            #set the target constraints
            for i in changes:
                delta = target_vars[i] - existing_vars[i]
                if delta > 0:
                    self.prob += PULP_vars[i] >= target_vars[i], "Soft Constraint" + str(i)
                else:
                    self.prob += PULP_vars[i] <= target_vars[i], "Soft Constraint" + str(i)
                    
            add_constraints_2p1(self.prob, L, p0, p1, x,y)
        

    def solve(self, report = True):
        #LpSolverDefault.msg = 1
        self.prob.solve()
        
        if self.prob.status == 1 and report:
            self.report()
            
    def report(self):
        print(self.L)
        print('%i sided Patch with Pattern: %i' % (len(self.L),self.pattern))
        print('Status: ' + LpStatus[self.prob.status])
        for v in self.prob.variables():
            print(v.name + ' = ' + str(v.varValue))