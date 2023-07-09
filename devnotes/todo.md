- Contours
    - move label position code into separate method called on target or view change

- Relax
    - Use 3D accel structure.  note: verts change position, but accel struct will see only initial position... probably ok, though!

- Loops and Strokes
    - remove Stopwatch, and handle this code correctly!

- predraw Drawing callback only fires if pre3d, post3d, or post2d exists!
- remove sprint and other debug calls
- use stopwatch to wrap select single so that smart selection is more dependable
- releasing LMB after canceling action with Esc/RMB will unselect geometry!?
- add planar rotation to loops (in addition to screen rotation, similar to contours)
- rf_fsm: `_stopwatch_view_change` uses Stopwatch
- build accel structs async