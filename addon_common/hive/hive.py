import json

from ..common.blender import get_path_from_addon_root

class Hive:
    def __init__(self):
        path_hive = get_path_from_addon_root('hive.json')
        self._data = json.load(open(path_hive, 'rt'))
    def __getitem__(self, k):
        return self._data[k]
