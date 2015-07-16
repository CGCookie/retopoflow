'''
Created on Jul 15, 2015

@author: Patrick
'''

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
        
    def validate(self):
        self.valid = False
        self.valid |= len(self.corner) == len(self.sides)
        self.valid |= (sum(self.edge_subdivision) % 2) == 0  #even subdiv
        
        return self.valid
        
        
    def reduce_input_cornered(self):
        '''
        slices off the biggest quad patches it can at a time
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
            new_subdivs = reduce_edges(edge_subdivs, ks[best], ds[best])
            
            ks, ds, pots = reducible(new_subdivs)
            print(new_subdivs)
            edge_subdivs = new_subdivs
         
        self.edges_reduced = new_subdivs
    
    def reduce_input_centered(self):
        '''
        slices off the smallest quad patches it can at a time
        produces a more centered pole arrangment?
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
                #there is only one alpha
                print('need to ask the authors about this one!')
                print('but I think you have a choice between pattern 2 and pattern 3')
                print('there are also editable parameters x and  y that may be used to separate the poles')
                
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
    def identify_tri_pattern(self):
        pass
        
    def identify_quad_pattern(self):
        pass
    def identify_pent_pattern(self):
        pass
    def identify_hex_pattern(self):
        if len(set(self.edges_reduced)) == 1:
            #pattern [1,1,1,1,1,1]
            self.pattern = 0
            print('Hex pattern 0')
        elif len(set(self.edges_reduced)) == 2:
            pass
            
            
    