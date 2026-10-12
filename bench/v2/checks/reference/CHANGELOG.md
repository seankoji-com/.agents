# Changelog

## Unreleased

- Fixed: amounts are parsed exactly; totals are no longer a cent low. Invalid amounts are rejected.
- Added: `report FILE --by month`.
- Security: `export` neutralises spreadsheet formula cells and refuses to overwrite its input file.

## 0.1.0

- `total` and `export` commands.
