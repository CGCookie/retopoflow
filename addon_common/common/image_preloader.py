'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import os
import glob
import atexit

from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

from .blender import get_path_from_addon_root
from .ui_core_images import preload_image, set_image_cache


# preload images to view faster
class ImagePreloader:
    _paused = False
    _quitted = False

    @classmethod
    def pause(cls):  cls._paused = True
    @classmethod
    def resume(cls): cls._paused = False
    @classmethod
    def paused(cls): return cls._paused

    @classmethod
    def quit(cls):   cls._quitted = True
    @classmethod
    def quitted(cls): return cls._quitted

    @classmethod
    def start(cls, paths, *, version='thread'):
        path_images = []

        path_cur = os.getcwd()
        for path in paths:
            os.chdir(get_path_from_addon_root(*path))
            path_images.extend(glob.glob('*.png'))
        os.chdir(path_cur)

        match version:
            case 'process':
                # this version spins up new Processes, so Python's GIL isn't an issue
                # :) loading is much FASTER!      (truly parallel loading)
                # :( DIFFICULT to pause or abort  (no shared resources)
                def setter(p):
                    if cls.quitted(): return
                    for path_image, img in p.result():
                        if img is None: continue
                        print(f'CookieCutter: {path_image} is preloaded')
                        set_image_cache(path_image, img)
                executor = ProcessPoolExecutor() # ThreadPoolExecutor()
                for path_image in path_images:
                    p = executor.submit(preload_image, path_image)
                    p.add_done_callback(setter)
                def abort():
                    nonlocal executor
                    cls.quit()
                    # the following line causes a crash :(
                    # executor.shutdown(wait=False)
                atexit.register(abort)

            case 'thread':
                # this version spins up new Threads, so Python's GIL is used
                # :( loading is much SLOWER!  (serial loading)
                # :) EASY to pause and abort  (shared resources)
                def abort():
                    cls.quit()
                atexit.register(abort)
                def start():
                    for png in path_images:
                        print(f'CookieCutter: preloading image "{png}"')
                        preload_image(png)
                        time.sleep(0.5)
                        for loop in range(10):
                            if not cls.paused(): break
                            if cls.quitted(): break
                            time.sleep(0.5)
                        else:
                            # if looped too many times, just quit
                            return
                        if cls.quitted(): return
                    print(f'CookieCutter: all images preloaded')
                ThreadPoolExecutor().submit(start)
