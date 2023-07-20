- IMPORTANT, BEFORE RELEASE
    - remove sprint and other debug calls
    - use stopwatch to wrap select single so that smart selection is more dependable
    - general rotate and scale need updated!  (rf_fsm.py)

- Contours
    - move label position code into separate method called on target or view change
    - new cut into symmetry line sometimes doesn't stick to line of symmetry

- PolyPen
    - moving verts near symmetry line can be difficult

- Relax
    - Use 3D accel structure.  note: verts change position, but accel struct will see only initial position... probably ok, though!

- Loops and Strokes
    - remove Stopwatch, and handle this code correctly!
    - add planar rotation to loops (in addition to screen rotation, similar to contours)

- Strokes
    - remove internal mergeSnapped code
    - improve move selected code (base on PolyPen or Select)

- General
    - predraw Drawing callback only fires if pre3d, post3d, or post2d exists!
    - general rotate and scale should have viz
    - build accel structs async
    - add clamp to symmetry option to prevent verts from moving away from symmetry line??
    - new method for finding nearest geometry (use selection framebuffer, see draw_selection_buffer)


- Symmetry
    - If action (ex: grab) is started on mirrored side, updates should be be mirrored correctly