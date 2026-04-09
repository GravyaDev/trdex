"""Test the LiveExecutor against Binance testnet.

Usage:
    uv run python -m trdex.scripts.test_live_executor
    uv run python -m trdex.scripts.test_live_executor --symbol BTC/USDT --qty 0.001

Prerequisites:
    - BINANCE_API_KEY and BINANCE_API_SECRET set in .env
      (testnet keys from https://testnet.binance.vision/)
    - TRDEX_BINANCE_TESTNET=true (default)

What it does:
    1. Creates a LiveExecutor pointed at Binance testnet
    2. Loads market specs (lot size, min notional)
    3. Places a market BUY order for the specified qty
    4. Waits for fill confirmation
    5. Places a market SELL order to close the position
    6. Reports the round-trip P&L including fees
    7. Closes the exchange connection

This is a destructive test on testnet — it uses fake money
but real exchange API calls. Never run with TRDEX_BINANCE_TESTNET=false
unless you intend to trade with real money.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from decimal import Decimal

from trdex.config import get_settings
from trdex.execution.live_executor import LiveExecutor
from trdex.execution.models import Order, OrderType, Side
from trdex.market import specs as market_specs

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("trdex.test_live")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTC/USDT", help="Trading pair")
    parser.add_argument("--qty", type=float, default=0.001, help="Quantity to buy/sell")
    args = parser.parse_args()

    settings = get_settings()

    if not settings.binance_testnet:
        logger.critical("REFUSING to run: TRDEX_BINANCE_TESTNET is false (production mode)")
        return 1

    if not settings.binance_api_key or not settings.binance_effective_secret:
        logger.critical("BINANCE_API_KEY and BINANCE_API_SECRET (or TRDEX_BINANCE_API_SECRET_FILE) must be set")
        return 1

    logger.info("=== LiveExecutor testnet test ===")
    logger.info("symbol: %s  qty: %s  testnet: %s", args.symbol, args.qty, settings.binance_testnet)

    executor = LiveExecutor.from_settings(settings)

    try:
        # Load market specs for lot size truncation
        await market_specs.load(executor._exchange)
        step = market_specs.get_step_size(args.symbol)
        min_notional = market_specs.get_min_notional(args.symbol)
        logger.info("market specs: step_size=%s  min_notional=%s", step, min_notional)

        qty = market_specs.truncate_qty(args.symbol, Decimal(str(args.qty)))
        logger.info("qty after truncation: %s", qty)

        if qty <= 0:
            logger.error("qty truncated to 0 — increase --qty above step_size %s", step)
            return 1

        # BUY
        logger.info("--- BUY ---")
        buy_order = Order(
            symbol=args.symbol,
            side=Side.BUY,
            type=OrderType.MARKET,
            amount=qty,
            price=None,
        )
        buy_result = await executor.execute(buy_order)
        logger.info(
            "BUY filled: qty=%s @ %s  fee=%s  order_id=%s",
            buy_result.filled_amount, buy_result.filled_price,
            buy_result.fee, buy_result.order_id,
        )

        # Small delay to let the exchange settle
        await asyncio.sleep(1)

        # SELL (close position)
        logger.info("--- SELL ---")
        sell_order = Order(
            symbol=args.symbol,
            side=Side.SELL,
            type=OrderType.MARKET,
            amount=buy_result.filled_amount,
            price=None,
        )
        sell_result = await executor.execute(sell_order)
        logger.info(
            "SELL filled: qty=%s @ %s  fee=%s  order_id=%s",
            sell_result.filled_amount, sell_result.filled_price,
            sell_result.fee, sell_result.order_id,
        )

        # Round-trip summary
        gross = (sell_result.filled_price - buy_result.filled_price) * buy_result.filled_amount
        total_fees = buy_result.fee + sell_result.fee
        net = gross - total_fees
        logger.info("=== ROUND-TRIP SUMMARY ===")
        logger.info("  buy  @ %s", buy_result.filled_price)
        logger.info("  sell @ %s", sell_result.filled_price)
        logger.info("  gross P&L: %s", gross)
        logger.info("  fees: %s (buy) + %s (sell) = %s", buy_result.fee, sell_result.fee, total_fees)
        logger.info("  net P&L: %s", net)
        logger.info("=== TEST PASSED ===")
        return 0

    except Exception as exc:
        logger.exception("Test failed: %s", exc)
        return 1
    finally:
        await executor.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
