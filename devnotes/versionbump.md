# Version Bump

When doing a version bump, update the versions in the following files:

- `__init__.py`: `bl_info`
    - update `"version": (3, 2, 5)`
    - comment / uncomment the `warning` keys as appropriate
        - note: there is no `warning` for official releases
- `Makefile`
    - update `VERSION = "v3.2.5"`
    - comment / uncomment the `RELEASE` var as appropriate
        - note: there is a `RELEASE` for official releases
- `config/options.py`
    - update `retopoflow_version = '3.2.5'`
        - append α / β as applicable
    - update `retopoflow_version_tuple = (3, 2, 5)` (no alpha, beta, etc.)
- add line to `help/changelist.md`
- `hive.json`
    - update `"version": "3.2.5"` (no alpha, beta, etc.)
