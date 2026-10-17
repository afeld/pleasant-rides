"""The app's Benchmark page compares provider variants (e.g. different routing parameters) by their scores on a set of
sample trips: `variants` defines them, `runner` runs them, and `table` lays out the results.

Results depend on the providers' live servers and map data, so they can drift over time; compare new variants against
the baselines (the "(current)" ones) from the same run.
"""
