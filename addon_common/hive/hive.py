import re
import json

from ..terminal import term_printer
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
    def to_bl_info():
        get, ver = Hive.get, Hive.get_version
        bl_info_from_hive = {
            'name':        get('name'),
            'description': get('description'),
            'author':      get('author'),
            'blender':     ver('blender minimum version'),
            'version':     ver('version'),
            'doc_url':     get('documentation url'),
            'tracker_url': get('issue url'),
            'location':    get('blender location'),
            'category':    get('blender category'),
        }
        if get('release').lower() != 'official':
            bl_info_from_hive['warning'] = get('release').title()
        return bl_info_from_hive

    @staticmethod
    def update_bl_info(bl_info, init_filepath):
        bl_hive = Hive.to_bl_info()
        same = True
        same &= all(k in bl_info and bl_info[k] == bl_hive[k] for k in bl_hive)
        same &= all(k in bl_hive and bl_hive[k] == bl_info[k] for k in bl_info)
        if same: return

        # changes detected!  update!
        term_printer.boxed('RetopoFlow: UPDATING __init__.py!', color='black', highlight='yellow', margin=' ')
        init_file = open(init_filepath, 'rt').read()
        insert = '\n' + '\n'.join([
            f'''{f'    "{k}":':20s}{f'"{v}"' if isinstance(v, str) else f'{v}'},'''
            for (k,v) in Hive.to_bl_info().items()
        ]) + '\n'
        init_file = re.sub(
            r'(?P<start>bl_info *= *\{)(?P<replace>[^}]+)(?P<end>\})',
            rf'\1{insert}\3',
            init_file
        )
        open(init_filepath, 'wt').write(init_file)
