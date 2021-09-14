# Version Bump

When doing a version bump, update the versions in the following files:

- `__init__.py`
    - in `bl_info`, for example: `"version": (3, 2, 2)`
    - comment / uncomment the `warning` keys as needed
- `Makefile`
    - update `RELEASE` and `VERSION`
- `config/options.py`
    - for `retopoflow_version` and `retopoflow_version_tuple`
- add line to `help/changelist.md`
- update `hive.json`
