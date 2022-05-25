# Version Bump

When doing a version bump, update the versions in the following files:

- `__init__.py`
    - in `bl_info` dict
        - update `"version": (3, 2, 5)`
        - comment / uncomment the `warning` keys as appropriate
            - note: there is no `warning` for official releases
- `Makefile`
    - update `VERSION = "v3.2.5"`
    - comment / uncomment the `RELEASE` var as appropriate
        - note: there is a `RELEASE` for official releases
- `hive.json`
    - update `"version": "3.2.5"` (no alpha, beta, etc.)
- `config/options.py`
    - update `retopoflow_version = '3.2.5'`
        - append α / β as applicable
    - update `retopoflow_version_tuple = (3, 2, 5)` (no alpha, beta, etc.)
- `help/changelist.md`
    - add new section
