'''
Created on Jan 22, 2016

@author: Patrick
'''
from .lib.pulp import LpVariable, LpProblem, LpMinimize, LpMaximize, LpInteger, LpStatus, lpSum, LpSolverDefault, LpAffineExpression, LpConstraint


def verify_L_2p0(L):
    valid = False
    valid |= L[0] >= 3
    valid |= L[1] >= 1
    return valid
    
def add_constraints_2p0(prob, L, p0, p1, x, y):
    print('constraints added for doublet pattern 0')
    
    #prob +=  2*p1 + 2*x + y    == L[0] - 3, "Side 0"  old way
    aff0 = LpAffineExpression([(p1,2),(x,2),(y,1)])
    cons0 = LpConstraint(e = aff0, sense = 0, name = "Side0", rhs = L[0]-3)
    prob += cons0
    
    #prob +=  2*p0 + y          == L[1] - 1, "Side 1"
    aff1 = LpAffineExpression([(p0,2),(y,1)])
    cons1 = LpConstraint(e = aff1, sense = 0, name = "Side1", rhs = L[1]-1)
    prob += cons1
    
    
def verify_L_2p1(L):
    valid = False
    valid |= L[0] >= 2
    valid |= L[1] >= 2
    return valid
          
def add_constraints_2p1(prob, L, p0, p1, x, y):
    print('constraints added for doublet pattern 1') 
    #prob +=  2*p1 + x + y      == L[0] - 2, "Side 0"
    aff0 = LpAffineExpression([(p1,2),(x,1),(y,1)])
    cons0 = LpConstraint(e = aff0, sense = 0, name = "Side0", rhs = L[0]-2)
    prob += cons0
    
    #prob +=  2*p0 + x + y      == L[1] - 2, "Side 1"
    aff1 = LpAffineExpression([(p0,2),(x,1),(y,1)])
    cons1 = LpConstraint(e = aff0, sense = 0, name = "Side1", rhs = L[1]-2)
    prob += cons1
    
def verify_L_3p0(L):
    valid = False
    valid |= L[0] >= 2
    return valid
        
def add_constraints_3p0(prob, L, p0, p1, p2):
    prob +=  p2 + p1            == L[0] - 2, "Side0"
    prob +=  p0 + p2            == L[1] - 1, "Side1"
    prob +=  p1 + p0            == L[2] - 1, "Side2"

def verify_L_3p1(L):
    valid = False
    valid |= L[0] >= 4
    return valid

def add_constraints_3p1(prob, L, p0, p1, p2, x, q1, q2):
    #prob +=  p2 + p1 +2*x + q1 + q2    == L[0] - 4, "Side 0"
    aff0 = LpAffineExpression([(p2,1),(p1,1),(x,2),(q1,1),(q2,1)])
    cons0 = LpConstraint(e = aff0, sense = 0, name = "Side0", rhs = L[0]-4 )
    prob += cons0
    
    prob +=  p0 + p2 + q2              == L[1] - 1, "Side1"
    prob +=  p1 + p0 + q1              == L[2] - 1, "Side2"

def verify_L_4p0(L):
    valid = False
    valid |= L[0] >= 1
    return valid    
def add_constraints_4p0(prob, L, p0, p1, p2, p3):
    prob +=  p3 + p1            == L[0] - 1, "Side0"
    prob +=  p0 + p2            == L[1] - 1, "Side1"
    prob +=  p1 + p3            == L[2] - 1, "Side2"
    prob +=  p2 + p0            == L[3] - 1, "Side3"

def verify_L_4p1(L):
    valid = False
    valid |= L[0] >= 2
    valid |= L[1] >= 2
    return valid
def add_constraints_4p1(prob, L, p0, p1, p2, p3, x):
    prob +=  p3 + p1 + x        == L[0] - 2, "Side0"
    prob +=  p0 + p2 + x        == L[1] - 2, "Side1"
    prob +=  p1 + p3            == L[2] - 1, "Side2"
    prob +=  p2 + p0            == L[3] - 1, "Side3"

def verify_L_4p2(L):
    valid = False
    valid |= L[0] >= 3
    return valid 
  
def add_constraints_4p2(prob, L, p0, p1, p2, p3, x, y):
    prob +=  p3 + p1 + x + y    == L[0] - 3, "Side0"
    prob +=  p0 + p2 + x        == L[1] - 1, "Side1"
    prob +=  p1 + p3            == L[2] - 1, "Side2"
    prob +=  p2 + p0 + y        == L[3] - 1, "Side3"

def verify_L_4p3(L):
    valid = False
    valid |= L[0] >= 3
    return valid
def add_constraints_4p3(prob, L, p0, p1, p2, p3, x, q1):
    '''
    p1 + q1 = constant
    '''
    #prob +=  p3 + p1 + 2*x +q1    == L[0] - 3, "Side 0"
    aff0 = LpAffineExpression([(p3,1),(p1,1),(x,2),(q1,1)])
    cons0 = LpConstraint(e = aff0, sense = 0, name = "Side0", rhs = L[0]-3)
    prob += cons0
    
    
    prob +=  p0 + p2              == L[1] - 1, "Side1"
    prob +=  p1 + p3 + q1         == L[2] - 1, "Side2"
    prob +=  p2 + p0              == L[3] - 1, "Side3"

def verify_L_4p4(L):
    valid = False
    valid |= L[0] >= 4
    valid |= L[1] >= 2
    return valid   
def add_constraints_4p4(prob, L, p0, p1, p2, p3, x, y, q1):
    '''
    p0 + q0 = constant
    '''
    #prob +=  p1 + p3 + 2*x + y +q1  == L[0] - 4, "Side 0"
    aff0 = LpAffineExpression([(p1,1),(p3,1),(x,2),(y,1),(q1,1)])
    cons0 = LpConstraint(e = aff0, sense = 0, name = "Side0", rhs = L[0]-4)
    prob += cons0
    
    prob +=  p0 + p2 + y            == L[1] - 2, "Side1"
    prob +=  p1 + p3  +q1           == L[2] - 1, "Side2"
    prob +=  p2 + p0                == L[3] - 1, "Side3"

def verify_L_5p0(L):
    valid = False
    valid |= L[0] >= 2
    return valid

def add_constraints_5p0(prob, L, p0, p1, p2, p3, p4):
    prob +=  p4 + p1            == L[0] - 2, "Side0"
    prob +=  p0 + p2            == L[1] - 1, "Side1"
    prob +=  p1 + p3            == L[2] - 1, "Side2"
    prob +=  p2 + p4            == L[3] - 1, "Side3"
    prob +=  p3 + p0            == L[4] - 1, "Side4"

def verify_L_5p1(L):
    valid = False
    valid |= L[0] >= 2
    return valid   
def add_constraints_5p1(prob, L, p0, p1, p2, p3, p4, x, q4): 
    '''
    q4 + p4 = constant
    '''
    prob +=  p4 + p1 + x + q4       == L[0] - 2, "Side0"
    prob +=  p0 + p2 + x            == L[1] - 1, "Side1"
    prob +=  p1 + p3                == L[2] - 1, "Side2"
    prob +=  p2 + p4 + q4           == L[3] - 1, "Side3"
    prob +=  p3 + p0                == L[4] - 1, "Side4"

def verify_L_5p2(L):
    valid = False
    valid |= L[0] >= 4
    return valid    
def add_constraints_5p2(prob, L, p0, p1, p2, p3, p4, x, q0, q1, q4):
    '''
    p0 + q0 = constant
    p1 + q1 = constant
    '''
    #prob +=  p4 + p1 + 2*x + q1 + q4  == L[0] - 4, "Side 0"
    aff0 = LpAffineExpression([(p4,1),(p1,1),(x,2),(q1,1),(q4,1)])
    cons0 = LpConstraint(e = aff0, sense = 0, name = "Side0", rhs = L[0]-4)
    prob += cons0
    
    prob +=  p0 + p2  + q0            == L[1] - 1, "Side1"
    prob +=  p1 + p3 + q1             == L[2] - 1, "Side2"
    prob +=  p2 + p4 + q4             == L[3] - 1, "Side3"
    prob +=  p3 + p0 + q0             == L[4] - 1, "Side4"
 
def verify_L_5p3(L):
    valid = False
    valid |= L[0] >= 5
    valid |= L[1] >= 2
    return valid  
def add_constraints_5p3(prob, L, p0, p1, p2, p3, p4, x, y, q1, q4):
    '''
    p0 + q1 = constant
    p4 + q4 = constant
    '''
    #prob +=  p4 + p1 + 2*x + y + q1 + q4  == L[0] - 5, "Side 0"
    aff0 = LpAffineExpression([(p4,1),(p1,1),(x,2),(y,1),(q1,1),(q4,1)])
    cons0 = LpConstraint(e = aff0, sense = 0, name = "Side0", rhs = L[0]-5 )
    prob += cons0
    
    prob +=  p0 + p2 + y                  == L[1] - 2, "Side 1"
    prob +=  p1 + p3 + q1                 == L[2] - 1, "Side 2"
    prob +=  p2 + p4 + q4                 == L[3] - 1, "Side 3"
    prob +=  p3 + p0                      == L[4] - 1, "Side 4"

def verify_L_6p0(L):
    valid = True
    return valid
                  
def add_constraints_6p0(prob, L, p0, p1, p2, p3, p4, p5, x): 
    prob +=  p5 + p1 + x        == L[0] - 1, "Side0"
    prob +=  p0 + p2            == L[1] - 1, "Side1"
    prob +=  p1 + p3            == L[2] - 1, "Side2"
    prob +=  p2 + p4 + x        == L[3] - 1, "Side3"
    prob +=  p3 + p5            == L[4] - 1, "Side4"
    prob +=  p4 + p0            == L[5] - 1, "Side5"

def verify_L_6p1(L):
    valid = False
    valid |= L[0] >= 2
    valid |= L[1] >= 2
    return valid      
def add_constraints_6p1(prob, L, p0, p1, p2, p3, p4, p5, x, y, z, w): 
    prob +=  p5 + p1 + x + y       == L[0] - 2, "Side0"
    prob +=  p0 + p2 + x + z       == L[1] - 2, "Side1"
    prob +=  p1 + p3 + w           == L[2] - 1, "Side2"
    prob +=  p2 + p4 + y           == L[3] - 1, "Side3"
    prob +=  p3 + p5 + z           == L[4] - 1, "Side4"
    prob +=  p4 + p0 + w           == L[5] - 1, "Side5"

def verify_L_6p2(L):
    valid = False
    valid |= L[0] >= 3
    return valid
   
def add_constraints_6p2(prob, L, p0, p1, p2, p3, p4, p5, x, y, q0, q3):  
    '''
    q3 + p3 = constant, q0 + p0 = constant
    '''
    #prob +=  p5 + p1 + 2*x + y      == L[0] - 3, "Side 0"
    aff0 = LpAffineExpression([(p5,1),(p1,1),(x,2),(y,1)])
    cons0 = LpConstraint(e = aff0, sense = 0, name = "SideZero", rhs = L[0]-3)
    prob += cons0
    
    #prob +=  p0 + p2 + q0           == L[1] - 1, "SideOne"
    aff1 = lpSum([p0,p2,q0])
    cons1 = LpConstraint(e=aff1, sense =0, name = "SideOne", rhs = L[1]-1)
    prob += cons1
    
    #prob +=  p1 + p3 + q3           == L[2] - 1, "SideTwo"
    aff2 = lpSum([p1,p3,q3])
    cons2 = LpConstraint(e=aff2, sense=0, name = "SideTwo", rhs = L[2]-1)
    prob += cons2
    
    #prob +=  p2 + p4 + y            == L[3] - 1, "SideThree"
    aff3 = lpSum([p2,p4,y])
    cons3 = LpConstraint(e=aff3, sense=0, name = "SideThree", rhs = L[3]-1)
    prob += cons3
    
    #prob +=  p3 + p5 + q3           == L[4] - 1, "Side4"
    aff4 = lpSum([p3,p5,q3])
    cons4 = LpConstraint(e=aff4, sense=0, name = "SideFour", rhs = L[4]-1)
    prob += cons4
    
    #prob +=  p4 + p0 + q0           == L[5] - 1, "SideFive"
    aff5 = lpSum([p4,p0, q0])
    cons5 = LpConstraint(e=aff5, sense=0, name = "SideFive", rhs = L[5]-1)
    prob += cons5
    
def verify_L_6p3(L):
    valid = False
    valid |= L[0] >= 4
    valid |= L[1] >= 2
    return valid    
def add_constraints_6p3(prob, L, p0, p1, p2, p3, p4, p5, x, y, z, q3):
    '''
    q3 + p3 = constant
    '''
    #prob +=  p5 + p1 + 2*x + y + z  == L[0] - 4, "Side 0"
    aff0 = LpAffineExpression([(p5,1),(p1,1),(x,2),(y,1),(z,1)])
    cons0 = LpConstraint(e=aff0, sense =0, name = "SideZero", rhs = L[0]-4)
    prob += cons0
    
    #prob +=  p0 + p2 + y            == L[1] - 2, "Side1"
    aff1 = lpSum([p0,p2,y])
    cons1 = LpConstraint(e=aff1, sense=0, name = "SideOne", rhs = L[1]-2)
    prob += cons1
    
    #prob +=  p1 + p3 + q3           == L[2] - 1, "SideTwo"
    aff2 = lpSum([p1,p3,q3])
    cons2 = LpConstraint(e=aff2, sense=0, name = "SideTwo", rhs = L[2]-1)
    prob += cons2
    
    #prob +=  p2 + p4 + z            == L[3] - 1, "SideThree"
    aff3 = lpSum([p2,p4,z])
    cons3 = LpConstraint(e=aff3, sense=0, name = "SideThree", rhs = L[3]-1)
    prob += cons3
    
    #prob +=  p3 + p5 + q3           == L[4] - 1, "SideFour"
    aff4 = lpSum([p3,p5,q3])
    cons4 = LpConstraint(e=aff4, sense=0, name = "SideFour", rhs = L[4]-1)
    prob += cons4
    
    #prob +=  p4 + p0                == L[5] - 1, "SideFive"
    aff5 = lpSum([p4,p0])
    cons5 = LpConstraint(e=aff5, sense=0, name = "SideFive", rhs = L[5]-1)
    prob += cons5
    
  