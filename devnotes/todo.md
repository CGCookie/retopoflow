- Contours
    - move label position code into separate method called on target or view change

- Relax
    - Use 3D accel structure.  note: verts change position, but accel struct will see only initial position... probably ok, though!

- Loops and Strokes
    - remove Stopwatch, and handle this code correctly!

- predraw Drawing callback only fires if pre3d, post3d, or post2d exists!
- remove sprint and other debug calls
- use stopwatch to wrap select single so that smart selection is more dependable
