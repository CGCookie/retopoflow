# Dev Notes

## Version bump

When doing a version bump, update the versions in the following files:

- `__init__.py`
    - in `bl_info`, for example: `"version": (3, 2, 2)`
- `Makefile`
    - for `VERSION` and `GIT_TAG`
- `config/options.py`
    - for `retopoflow_version` and `retopoflow_version_tuple`
- add line to `help/changelist.md`
- update `hive.json`