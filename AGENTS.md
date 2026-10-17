# Agent guidelines

Conventions for AI coding agents working in this repository.

## Formatting

- Format every changed file before committing: Python with Ruff (`uvx ruff format`), and Markdown, JSON, YAML, etc. with Prettier (`npx prettier --write`). Prettier doesn't handle TOML or Swift, so leave those as they are. There's no Ruff or Prettier config yet, so the defaults apply.
- Don't hard-wrap prose. Write each paragraph, bullet, comment, docstring paragraph, or string as one line, without manual line breaks at ~72/80/120 columns. This applies to commit message bodies, PR descriptions, Markdown, and code comments, docstrings, and string literals (don't split a message into concatenated f-strings just for length). Let Ruff wrap code itself; it doesn't reflow comments or strings.

## Commits

- Make focused commits as you go: one commit per logical change (e.g. a feature, then its error handling, then tests), committed once each piece is done and verified (formatted, type-checked, tests passing), rather than one big commit at the end.
- Don't push unless asked.

## Dependencies

- Prefer adding a library over hand-rolled code, e.g. shapely, pyproj, or duckdb for geometry, projections, and data access, rather than custom math or parsing.

## Being polite to providers

The routing, map-matching, and geocoding services this app calls are often free public servers (e.g. brouter.de, valhalla1.openstreetmap.de, Nominatim), so keep the load on them low:

- Avoid bursts: keep concurrency per server low and space requests out (see `pleasant_rides/politeness.py`).
- Back off on rate limits (e.g. BRouter's "403 Please, retry later!"), and stop sending a server requests once it's rate-limited you.
- Don't retry errors that won't change, like a bad request or a feature that needs a paid plan.
- Prefer cached results over refetching, and avoid changes that force a full refetch (e.g. changing a cached function's signature) unless needed.
