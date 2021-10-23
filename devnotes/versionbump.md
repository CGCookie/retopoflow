# Version Bump

When doing a version bump, update the versions in the following files:

- `__init__.py`: `bl_info`
    - update `"version": (3, 2, 5)`
    - comment / uncomment the `warning` keys as needed
- `Makefile`
    - update `VERSION = "v3.2.5"`
    - comment / uncomment the `RELEASE` var as needed
- `config/options.py`
    - update `retopoflow_version = '3.2.5'`
    - update `retopoflow_version_tuple = (3, 2, 5)`
- add line to `help/changelist.md`
- `hive.json`
    - update `"version": "3.2.5"`
