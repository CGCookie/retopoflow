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

from ..options import (
    retopoflow_version, retopoflow_version_git,
    build_platform,
    platform_system,platform_node,platform_release,platform_version,platform_machine,platform_processor,
    gpu_vendor,gpu_renderer,gpu_version,gpu_shading,
)

def get_error_report():
    message = '\n'.join([
        desc,
        'This was unexpected.',
        '',
        'If this happens again, please report as bug so we can fix it.',
        ])

    msg_report = ['Environment:\n']
    msg_report += ['- RetopoFlow: %s' % (retopoflow_version,)]
    if retopoflow_version_git:
        msg_report += ['- RF git: %s' % (retopoflow_version_git,)]
    msg_report += ['- Blender: %s %s %s' % (blender_version, blender_branch, blender_date)]
    msg_report += ['- Platform: %s' % (', '.join([platform_system,platform_release,platform_version,platform_machine,platform_processor]), )]
    msg_report += ['- GPU: %s' % (', '.join([gpu_vendor, gpu_renderer, gpu_version, gpu_shading]), )]
    msg_report += ['- Timestamp: %s' % datetime.today().isoformat(' ')]
    msg_report += ['- Undo: %s' % (', '.join(self.undo_stack_actions()[:10]),)]
    if msghash:
        msg_report += ['']
        msg_report += ['Error Hash: %s' % (str(msghash),)]
    if message_orig:
        msg_report += ['']
        msg_report += ['Trace:\n']
        msg_report += [message_orig]
    msg_report = '\n'.join(msg_report)

    return msg_report