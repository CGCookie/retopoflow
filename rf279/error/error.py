'''
Copyright (C) 2018 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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

from ..options import (
    retopoflow_version, retopoflow_version_git,
    build_platform,
    platform_system, platform_node, platform_release, platform_version, platform_machine, platform_processor,
    gpu_vendor, gpu_renderer, gpu_version, gpu_shading,
)


def get_environment_details():
    blender_version = '%d.%02d.%d' % bpy.app.version
    blender_branch = bpy.app.build_branch.decode('utf-8')
    blender_date = bpy.app.build_commit_date.decode('utf-8')

    env_details = []
    env_details += ['Environment:\n']
    env_details += ['- RetopoFlow: %s' % (retopoflow_version, )]
    if retopoflow_version_git:
        env_details += ['- RF git: %s' % (retopoflow_version_git, )]
    env_details += ['- Blender: %s' % (' '.join([
        blender_version,
        blender_branch,
        blender_date
    ]), )]
    env_details += ['- Platform: %s' % (', '.join([
        platform_system,
        platform_release,
        platform_version,
        platform_machine,
        platform_processor
    ]), )]
    env_details += ['- GPU: %s' % (', '.join([
        gpu_vendor,
        gpu_renderer,
        gpu_version,
        gpu_shading
    ]), )]
    env_details += ['- Timestamp: %s' % datetime.today().isoformat(' ')]

    return '\n'.join(env_details)


def get_trace_details(undo_stack, msghash=None, message=None):
    trace_details = []
    trace_details += ['- Undo: %s' % (', '.join(undo_stack[:10]),)]
    if msghash:
        trace_details += ['']
        trace_details += ['Error Hash: %s' % (str(msghash),)]
    if message:
        trace_details += ['']
        trace_details += ['Trace:\n']
        trace_details += [message]
    return '\n'.join(trace_details)

