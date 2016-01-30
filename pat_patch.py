'''
Created on Jul 15, 2015

@author: Patrick
'''
from .lib.pulp import LpVariable, LpProblem, LpMinimize, LpMaximize, LpInteger, LpStatus, lpSum, LpSolverDefault, LpAffineExpression, LpConstraint

from .patterns import *
import time
import math


def PuLP_to_dict(lp_prob):
    '''
    extracts dictionary of variables from class PuLp LpProblem
    customized to ignore minimzation variables that are not
    relevatnt to patch geometry.  Returned sorted hopefully
    '''
    sol_dict_raw  = {}
    sol_dict = {}
    for v in lp_prob.variables():
        if "min" not in v.name:
            sol_dict_raw[v.name] = int(v.varValue)
    
    #make sure they are alphabetized
    keys = [vname for vname in sol_dict_raw.keys()]
    keys.sort()
    for vname in keys:
        sol_dict[vname] = sol_dict_raw[vname]
        
    return sol_dict
    
    
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
    
    #print('this is the raw subdivision fed into the permutations')
    #print(L)
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
    #print('these are the supplied permutations')
    #for p, sd in zip(perms, shift_dir):
    #    print((p, sd))
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
        self.pattern = 0  #default the simplest pattern

        self.reductions = {}
        self.edges_reduced = []
        
        self.perms = []
        self.perm_index = -1 #step through all the permutations
        self.pat_index = 0  #step through each pattern for all permutations
        
        self.active_solution_index = -1
        self.valid_perms = []
        self.valid_rot_dirs = []
        self.valid_patterns = []
        self.valid_solutions = []
        
        self.any_solved = False
        self.all_solved = False
        
        self.param_index = 0
        self.delta = 0
        
    def validate(self):
        self.valid = False
        self.valid |= len(self.corners) == len(self.edges_reduced)
        self.valid |= (sum(self.edge_subdivision) % 2) == 0  #even subdiv
        
        return self.valid
    
    def n_patterns(self):
        N = len(self.edge_subdivision)
        pat_dict = {}
        pat_dict[2] = 2
        pat_dict[3] = 2
        pat_dict[4] = 5
        pat_dict[5] = 4
        pat_dict[6] = 4
        
        return pat_dict[N]
    
    def find_next_solution(self):
        pat_dict = {}
        pat_dict[2] = 2
        pat_dict[3] = 2
        pat_dict[4] = 5
        pat_dict[5] = 4
        pat_dict[6] = 4
        
        #SPEED UP only test reasonable permutatins
        #To do this...will need to iterate patterns first
        #and only test reasonably rotations/reversals
        N = len(self.edge_subdivision)
        
        if self.all_solved:
            print('already solved all of the permutations')
            return
        elif not self.any_solved:
            print('have not found initial solution')
            return
        
        perm = self.perms[self.perm_index]
        pat = self.pat_index
        
        if N == 6:
            sol = PatchSolver6(perm, pat)
        elif N == 5:
            sol = PatchSolver5(perm, pat)
        elif N == 4:    
            sol = PatchSolver4(perm, pat)
        elif N == 3:    
            sol = PatchSolver3(perm, pat)
        elif N == 2:
            print('attempting doublet solver')
            sol = PatchSolver2(perm, pat)  
        else:
            return
            
        #print('solving permutation %i for pattern %i' % (self.perm_index, pat))
        #print(perm)
        sol.solve(report = False)

        if sol.prob.status == 1:
            sol_dict = PuLP_to_dict(sol.prob)
            self.valid_perms += [perm]
            self.valid_rot_dirs += [self.rot_dirs[self.perm_index]]
            self.valid_patterns += [pat]
            self.valid_solutions += [sol_dict]
        
        #clean up PuLp and CBC instances, feeble effor to prevent crashes
        del sol.prob
        del sol  
          
        #check if we are done
        if self.perm_index == len(self.perms)-1 and self.pat_index == pat_dict[N]-1:
            self.all_solved = True
            return
            
        self.pat_index = (self.pat_index + 1) % pat_dict[N]
        if self.pat_index == 0:
            self.perm_index += 1
    
        
    def permute_and_find_first_solution(self):
        
        self.validate()
        pat_dict = {}
        pat_dict[2] = 2
        pat_dict[3] = 2
        pat_dict[4] = 5
        pat_dict[5] = 4
        pat_dict[6] = 4
        
        #SPEED UP only test reasonable permutatins
        #To do this...will need to iterate patterns first
        #and only test reasonably rotations/reversals
        self.perms, self.rot_dirs = permute_subdivs(self.edge_subdivision)
        
        self.active_solution_index = -1
        self.perm_index = 0
        self.valid_perms = []
        self.valid_rot_dirs = []
        self.valid_patterns = []
        self.valid_solutions = []
        N = len(self.edge_subdivision)
        
        for i, perm in enumerate(self.perms):
            for pat in range(0,pat_dict[N]):
                if N == 6:
                    sol = PatchSolver6(perm, pat)
                elif N == 5:
                    sol = PatchSolver5(perm, pat)
                elif N == 4:    
                    sol = PatchSolver4(perm, pat)                   
                elif N == 3:    
                    sol = PatchSolver3(perm, pat)   
                elif N == 2:
                    sol = PatchSolver2(perm, pat)
                else:
                    print('N is not valid')
                    return
                
                #print('solving permutation %i for pattern %i' % (i, pat))
                sol.solve(report = False)
                
                
                #time.sleep(sleep_time)
                #time.sleep(sleep_time)
                if sol.prob.status == 1:
                    sol_dict = PuLP_to_dict(sol.prob)
                    self.valid_perms += [perm]
                    self.valid_rot_dirs += [self.rot_dirs[i]]
                    self.valid_patterns += [pat]
                    self.valid_solutions += [sol_dict] #<----wonder if this is ok to have a bunch of these instances around
                    self.active_solution_index = 0
                    self.any_solved = True
                    
                    #clean up these to maybe help CBC?
                    del sol.prob
                    del sol
                                        
                    if i == len(self.perms)-1 and pat == pat_dict[N]-1:
                        print('crazy that last permutaion and last pattern only fit')
                        self.all_solved = True
                        self.any_solved = True
                        return
                        
                    elif pat == pat_dict[N]-1:
                        #print('increment pattern and perm')
                        self.pat_index = 0
                        self.perm_index += 1
                    else:
                        #print('just increment pattern')
                        self.pat_index += 1
                        

                    if i == len(self.perms) -1:
                        self.all_solved = True
                        self.perm_index = -1
                    return
                
                else:
                    del sol.prob
                    del sol

        if len(self.valid_patterns):
            self.active_solution_index = 0
        else:
            self.active_solution_index = -1          
    
    def progress(self):
        
        if self.perm_index == -1: return 0
        
        N_perms = len(self.edge_subdivision)
        n_pats = self.n_patterns()
        total_solves = 2*N_perms * n_pats
        
        prog = ((self.perm_index * n_pats) + (self.pat_index))/ total_solves
        
        return prog
        
    def get_active_solution(self):
        
        n = self.active_solution_index
        
        if n > len(self.valid_perms)-1:
            print('not enough valid perms')
            print(n)
            for perm in self.valid_perms:
                print(perm)
            
            return None, (None, None), None, None
        if n == -1:
            print('no valid solutions')
            return None, (None, None), None, None
        
        L, rot_dir, pat, sol_dict = self.valid_perms[n], self.valid_rot_dirs[n], self.valid_patterns[n], self.valid_solutions[n]
        
        return L, rot_dir, pat, sol_dict
    
    def get_active_solution_variables(self):
        '''
        gets the varibales, in alphabetical order from the stored
        solution dictionary, returns just a list of those variables
        '''
        if self.active_solution_index == -1:
            print('no solution, permute and find solutions first')
            return []
        
        #solutions are stored as dictionary now
        soldict = self.valid_solutions[self.active_solution_index]
        
        keys = [k for k in soldict.keys()]
        keys.sort()
        e_vars = [soldict[k] for k in keys]
        return e_vars
    

    def get_adjust_variable_name(self):
        if self.active_solution_index == -1: return None
        
        sol_dict = self.valid_solutions[self.active_solution_index]
        n = self.param_index
        keys = [v for v in sol_dict.keys()]
        keys.sort()
        
        return keys[n]
         
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
            
            self.valid_solutions += [PuLP_to_dict(new_sol.prob)]
            self.active_solution_index = len(self.valid_perms) -1
            print('the adjusted variables') 
            new_vars = self.get_active_solution_variables()
            print(new_vars)
            
            del new_sol.prob
            del new_sol
            return True
        else:
            del new_sol.prob
            del new_sol
            print('desired adjustment not possible')
            return False
    def report(self):
        if self.active_solution_index == -1:
            print('no active soluton')
            return
        
        sol_dict = self.valid_solutions[self.active_solution_index]
        
        for var_name in sol_dict:
            print(var_name + ": " + str(sol_dict[var_name]))
        
        
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

                
class PatchSolver6(object):
    def __init__(self, L, pattern):
        self.pattern = pattern
        self.L = L
        self.prob_type = 'solve'
        self.prob = LpProblem("NSixPatch", LpMaximize)

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
    
    def solve(self, report = True, MPS = False):
        #LpSolverDefault.msg = 1
        self.prob.solve(use_mps = MPS)
        
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
        self.prob = LpProblem("N6PatchAdjust", LpMinimize)
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
                    
            add_constraints_6p2(self.prob, L,p0,p1,p2,p3,p4,p5,x,y,q0,q3)
        
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
        
    def solve(self, report = True, MPS = False):
        #LpSolverDefault.msg = 1
        self.prob.solve(use_mps = MPS)
        
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
        self.prob = LpProblem("N5Patch", LpMaximize)
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
            
    def solve(self, report = True, MPS = False):
        #LpSolverDefault.msg = 1
        self.prob.solve(use_mps = MPS)
        
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
        self.prob = LpProblem("N5PatchAdjust", LpMinimize)
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
        
    def solve(self, report = True, MPS = False):
        #LpSolverDefault.msg = 1
        self.prob.solve(use_mps = MPS)
        
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
        self.prob = LpProblem("N4Patch", LpMaximize)
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

    def solve(self, report = True, MPS = False):
        #LpSolverDefault.msg = 1
        self.prob.solve(use_mps = MPS)
        
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
        self.prob = LpProblem("N4PatchAdjust", LpMinimize)
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

    def solve(self, report = True, MPS = False):
        #LpSolverDefault.msg = 1
        self.prob.solve(use_mps = MPS)
        
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
        self.prob = LpProblem("N3Patch", LpMaximize)
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
    
    def solve(self, report = True, MPS = False):
        #LpSolverDefault.msg = 1
        self.prob.solve(use_mps = MPS)
        
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
        self.prob = LpProblem("N3PatchAdjust", LpMinimize)
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
        

    def solve(self, report = True, MPS = False):
        #LpSolverDefault.msg = 1
        self.prob.solve(use_mps = MPS)
        
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
        self.prob = LpProblem("N2Patch", LpMaximize)
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
    
    def solve(self, report = True, MPS = False):
        #LpSolverDefault.msg = 1
        self.prob.solve(use_mps = MPS)
        
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
        self.prob = LpProblem("N2PatchAdjust", LpMinimize)
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
        

    def solve(self, report = True, MPS = False):
        #LpSolverDefault.msg = 1
        self.prob.solve(use_mps = MPS)
        
        if self.prob.status == 1 and report:
            self.report()
            
    def report(self):
        print(self.L)
        print('%i sided Patch with Pattern: %i' % (len(self.L),self.pattern))
        print('Status: ' + LpStatus[self.prob.status])
        for v in self.prob.variables():
            print(v.name + ' = ' + str(v.varValue))