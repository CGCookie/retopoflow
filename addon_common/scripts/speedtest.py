import timeit
from collections import namedtuple

from ..maths import Vector, Point, Direction, Normal

NTPoint = namedtuple('Point', ['x', 'y', 'z'])

kwargs = {
    'number': 10000,
    'globals': globals(),
}

timings = []
timings += [timeit.timeit('[Vector((0,1,2)) for i in range(1000)]',     **kwargs)]
#timings += [timeit.timeit('[VectorOld((0,1,2)) for i in range(1000)]',  **kwargs)]
timings += [timeit.timeit('[Point((0,1,2)) for i in range(1000)]',      **kwargs)]
timings += [timeit.timeit('[Direction((0,1,2)) for i in range(1000)]',  **kwargs)]
timings += [timeit.timeit('[Normal((0,1,2)) for i in range(1000)]',     **kwargs)]
timings += [timeit.timeit('[(0,1,2) for i in range(1000)]',             **kwargs)]
timings += [timeit.timeit('[[0,1,2] for i in range(1000)]',             **kwargs)]
timings += [timeit.timeit('[NTPoint(0,1,2) for i in range(1000)]',      **kwargs)]


print(timings)
