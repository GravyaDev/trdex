"""Strategies designed for the polars-vectorised backtest engine.

These classes implement ``trdex.backtest.engine.Strategy`` (synchronous,
DataFrame in / Series out). They are intentionally separate from the
async, signal-by-signal strategies under ``strategy/examples/`` which
serve the agent runner — the two interfaces are not interchangeable.
"""
