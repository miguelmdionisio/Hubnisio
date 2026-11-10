"""Health results as pure functions (ADR-0009): no database, no I/O.

Per activity (`activity.derive`, computed at ingest into `activity_derived`): load from heart
rate, time in zones, mean-maximal curves, best efforts, graded pace, efficiency and
decoupling, an estimated VO2max, climbing speed. Later slices and the MCP server call the same
functions on stored streams.
"""
