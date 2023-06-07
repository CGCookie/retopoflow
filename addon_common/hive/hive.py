import re
import json

from ..common import term_printer
from ..common.blender import get_path_from_addon_root

class Hive:
    _hive_data_path = get_path_from_addon_root('hive.json')
    _hive_data = json.load(open(_hive_data_path, 'rt'))

    @staticmethod
    def get(k, *, default=None):
        return Hive._hive_data.get(k, default)

    @staticmethod
    def __getitem__(k):
        return Hive.get(k)

    @staticmethod
    def get_version(k):
        v = Hive.get(k)
        return tuple(int(i) for i in v.split('.')) if v else None

    @staticmethod
    def update_bl_info(bl_info, init_filepath):
        get, ver = Hive.get, Hive.get_version
        update_details = [
            # bl_info key   hive key           hive value
            ('name',        'name',            get('name')),
            ('description', 'description',     get('description')),
            ('author',      'author',          get('author')),
            ('blender',     'blender_min_ver', ver('blender minimum version')),
            ('version',     'version',         ver('version')),
            ('doc_url',     'doc_url',         get('documentation url')),
            ('tracker_url', 'issue_url',       get('issue url')),
            ('warning',     'release',         get('release').title()),  # warning removed if official
        ]

        # collect all needed updates
        updates = []
        for bli_key, hive_key, hive_val in update_details:
            if bli_key == 'warning':
                # special case
                bli_val = bl_info.get('warning', 'Official')
                if bli_val != hive_val:
                    if hive_val == 'Official':
                        # comment out warning line
                        updates.append((
                            rf'"warning"(?P<mid>.*#.*)(?P<hive>@hive\.release)(?P<post>.*)',
                            rf'# "warning"\1\2\3'
                        ))
                        bl_info.pop('warning')
                    else:
                        # uncomment warning line (if needed)
                        updates.append((
                            rf'(# )?"warning":(?P<mid0> *)"[^"]+"(?P<mid>.*#.*)(?P<hive>@hive\.release)(?P<post>.*)',
                            rf'"warning":\2"{hive_val}"\3\4\5'
                        ))
                        bl_info['warning'] = hive_val
            elif bl_info[bli_key] != hive_val:
                bli_val = bl_info[bli_key]
                # detected a change
                if bli_key in {'blender', 'version'}:
                    updates.append((
                        rf'{re.escape(f"{bli_val}")}(?P<mid>.*#.*)(?P<hive>@hive\.{hive_key})(?P<post>.*)',
                        rf'{hive_val}\1\2\3'
                    ))
                else:
                    updates.append((
                        rf'"{re.escape(bli_val)}"(?P<mid>.*#.*)(?P<hive>@hive\.{hive_key})(?P<post>.*)',
                        rf'"{hive_val}"\1\2\3'
                    ))
                bl_info[bli_key] = hive_val

        if not updates:
            # no changes were detected!
            return

        # changes detected!  update!
        term_printer.boxed('RetopoFlow: UPDATING __init__.py!', color='black', highlight='yellow', margin=' ')
        init_file = open(init_filepath, 'rt').read()
        for update in updates: init_file = re.sub(*update, init_file)
        open(init_filepath, 'wt').write(init_file)
