- Contours
    - move label position code into separate method called on target or view change

- Relax
    - Use 3D accel structure.  note: verts change position, but accel struct will see only initial position... probably ok, though!

- Loops and Strokes
    - remove Stopwatch, and handle this code correctly!
    - add planar rotation to loops (in addition to screen rotation, similar to contours)

- General
    - predraw Drawing callback only fires if pre3d, post3d, or post2d exists!
    - general rotate and scale should have viz
    - build accel structs async

- IMPORTANT, BEFORE RELEASE
    - remove sprint and other debug calls
    - use stopwatch to wrap select single so that smart selection is more dependable


