#!/usr/bin/python3

import os
import re
import glob
import wget
import shutil
import tarfile
import datetime

assert False, 'do not use this anymore'

now = datetime.datetime.now()
user = os.path.expanduser('~')
urlroot='https://builder.blender.org'
url='%s/download/' % urlroot
tmp='/tmp/download.html'
blendertar=os.path.join(user, 'software/blender-2.80-%04d%02d%02d.tar.bz2' % (now.year, now.month, now.day))
blenderpath=os.path.join(user, 'software/blender-2.80-%04d%02d%02d' % (now.year, now.month, now.day))
blendersym=os.path.join(user, 'software/blender-2.80')

print('finding latest blender 2.80')
tmp=wget.download(url=url, out=tmp, bar=None)
html=open(tmp, 'rt').read()
m = re.search(r'/download/blender-2\.80-[0-9a-f]+-linux-glibc[^-]*?-x86_64\.tar\.bz2', html)
assert m, 'could not find match'

url = '%s/%s' % (urlroot, m.group(0))
print('downloading %s' % url)
blendertar=wget.download(url=url, out=blendertar, bar=None)

print('extracting from %s' % blendertar)
t = tarfile.open(name=blendertar)
t.extractall(path=blenderpath)

innerpath=list(glob.glob(os.path.join(blenderpath,'*')))[0]
print('moving from inner folder (%s) to outer' % innerpath)
for f in glob.glob(os.path.join(innerpath, '*')):
    shutil.move(f, blenderpath)
os.rmdir(innerpath)

print('creating new symlink and cleaning up')
os.unlink(blendertar)
os.unlink(blendersym)
os.symlink(blenderpath, blendersym)
