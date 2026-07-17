"""CLI entry for wake-sensor scaffold."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from .config import WakeSensorConfig
from .service import WakeSensorService


def _load_local_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            if key not in os.environ:
                os.environ[key] = value.strip()


async def _run() -> None:
    _load_local_env(".env")
    config = WakeSensorConfig.from_env()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    service = WakeSensorService(config)
    stop_event = asyncio.Event()

    def _handle_stop(*_args):
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_stop)

    main_task = asyncio.create_task(service.start())
    await stop_event.wait()
    await service.stop()
    main_task.cancel()
    try:
        await main_task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(_run())
