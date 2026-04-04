"""trdex entry point."""

from __future__ import annotations

import asyncio
import logging
import sys

import uvicorn

from trdex.config import pin_event_loop_policy, settings


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


async def run() -> None:
    """Start the trdex system."""
    logger = logging.getLogger("trdex")
    logger.info("Starting trdex in %s mode", settings.mode.value)

    # Start FastAPI server
    config = uvicorn.Config(
        "trdex.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


def main() -> None:
    pin_event_loop_policy()
    setup_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
