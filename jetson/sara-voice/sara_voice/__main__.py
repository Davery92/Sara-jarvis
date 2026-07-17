"""Entry point: python -m sara_voice"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from sara_voice.service import VoiceVisionService


def setup_logging(log_level: str = "INFO", log_file: str | None = None):
    """Configure logging for the service."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path))

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


async def main():
    service = VoiceVisionService()
    config = service.config

    setup_logging(
        log_level=config.get("service", {}).get("log_level", "INFO"),
        log_file=config.get("service", {}).get("log_file"),
    )
    logger = logging.getLogger("sara_voice")
    logger.info("Sara Voice + Vision Agent v%s starting...", "1.0.0")

    # Graceful shutdown on SIGTERM/SIGINT
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    try:
        await service.start()
        logger.info("All components started. Listening...")
        await shutdown_event.wait()
    except Exception:
        logger.exception("Fatal error during startup")
        sys.exit(1)
    finally:
        logger.info("Shutting down...")
        await service.stop()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
