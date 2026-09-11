'''
Copyright (C) 2024 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

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

import bpy

DEBUG = False


def current_version() -> tuple[int, int, int]:
    ''' RetopoFlow's own version. '''
    # deferred: the add-on root imports rfcore, which reaches this module
    # bl_info['version'] is RetopoFlow's version. bl_info['blender'] is the minimum Blender version,
    # and the two are the same tuple as of 4.2.0, so reading the wrong one looks right for now.
    from .. import bl_info
    return tuple(bl_info['version'])


def saved_version(props) -> tuple[int, int, int]:
    ''' The RetopoFlow that last entered this scene, or (0, 0, 0) if none ever has. '''
    return tuple(getattr(props, 'rf_version', (0, 0, 0)))


def stamp_version(scene):
    ''' Record that the running RetopoFlow has this scene's settings in their current shape. '''
    props = getattr(scene, 'retopoflow', None)
    if props is None:
        return
    version = current_version()
    # Only on a change: writing marks the .blend modified, and entering RF should not do that on its own
    if saved_version(props) != version:
        props.rf_version = version


def _holds_default(group, name : str) -> bool:
    ''' True while `group.name` still reads as its default, i.e. nothing has chosen a value yet.

    Key presence cannot answer this on the destination. Merely READING a PointerProperty on a
    PropertyGroup materialises its ID property, so any panel that draws the field makes an untouched
    property look set. Only the value distinguishes them.
    '''
    current = getattr(group, name, None)
    if current is None:
        return True   # an unset PointerProperty, which has no meaningful RNA default to compare
    rna = group.bl_rna.properties.get(name)
    return bool(rna) and current == getattr(rna, 'default', None)


def move_props(group, subgroup_name : str, names : tuple[str, ...]) -> list[str]:
    ''' Move old flat values on `group` into `group.<subgroup_name>`. Returns what moved. '''
    moved = []

    # Every write goes through a freshly fetched sub-group, and the old keys only come off once all
    # the writes are done. Removing an ID property rewrites the group that holds it, which leaves any
    # sub-group wrapper fetched beforehand pointing at memory that has moved.
    for name in names:
        if name not in group:
            continue
        subgroup = getattr(group, subgroup_name, None)
        if subgroup is None:
            return moved
        # An old value only wins while the artist has not chosen a new one. A file opened by a
        # RetopoFlow between the move and this migration can hold both, and the newer one is theirs.
        if not _holds_default(subgroup, name):
            continue
        try:
            setattr(subgroup, name, group[name])
            moved.append(name)
        except (TypeError, AttributeError) as e:
            # Wrong stored type for the destination, e.g. the property changed kind as well as
            # place. Dropping to the default beats refusing to open the file.
            if DEBUG: print(f'RF versioning: could not carry over {name!r}: {e}')

    # Stale either way now, whether it was carried over or the artist already had a newer value.
    # Leaving it would re-apply an old setting over a new one on some later load.
    for name in names:
        if name in group:
            del group[name]

    return moved


def migrate_scene(scene) -> list[str]:
    ''' Bring one scene's RetopoFlow settings up to the running version. Returns what changed. '''
    props = getattr(scene, 'retopoflow', None)
    if props is None:
        return []

    saved = saved_version(props)
    if saved >= current_version():
        return []   # stamped by this RetopoFlow or a later one, so nothing here applies

    changed = []

    if saved < (4, 2, 0):
        # The snapping settings were gathered out of scene.retopoflow into scene.retopoflow.snapping
        changed += move_props(props, 'snapping', ('snap_object', 'snap_collection', 'snap_only_selected'))

    stamp_version(scene)

    return changed


def migrate_all():
    scenes = getattr(bpy.data, 'scenes', None)
    if scenes is None:
        return
    for scene in scenes:
        changed = migrate_scene(scene)
        if changed and DEBUG:
            print(f'RF versioning: carried over {changed} on scene {scene.name!r}')


@bpy.app.handlers.persistent
def handle_load_post(_path_blend : str):
    migrate_all()


def _deferred_migrate():
    ''' The already-open-file sweep, one tick after registering. Returns None to retire itself. '''
    migrate_all()
    return None


def register():
    if handle_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(handle_load_post)
    # A file that was already open when RetopoFlow was enabled never fires load_post, so it needs its own sweep.
    # That cannot happen here though as data is restricted, and a timer is the first moment the data is reachable.
    if not bpy.app.timers.is_registered(_deferred_migrate):
        bpy.app.timers.register(_deferred_migrate, first_interval=0)


def unregister():
    if handle_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(handle_load_post)
    if bpy.app.timers.is_registered(_deferred_migrate):
        bpy.app.timers.unregister(_deferred_migrate)
