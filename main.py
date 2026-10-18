#!/usr/bin/env python3
"""
PyXaseco — Python port of Xaseco for TrackMania Forever.

Usage:
    python main.py [config.toml] [--debug]

Run this from the folder that contains config.toml, apps.toml, etc.
"""

import asyncio
import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from pathlib import Path

from pyxaseco.core.aseco import Aseco


class ControllerFormatter(logging.Formatter):
    def format(self, record):
        if getattr(record, 'console_text', False):
            return record.getMessage()
        return super().format(record)


def setup_logging(debug: bool):
    from pyxaseco.core.log_limits import RepeatTraceFilter
    stream = logging.StreamHandler(sys.stdout)
    file = RotatingFileHandler('logfile.txt', maxBytes=64 * 1024 * 1024,
                               backupCount=4, encoding='utf-8')
    for handler in (stream, file):
        handler.addFilter(RepeatTraceFilter())
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s%(repeat_summary)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            stream,
            file,
        ]
    )
    formatter = ControllerFormatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s%(repeat_summary)s',
        datefmt='%Y-%m-%d %H:%M:%S')
    stream.setFormatter(formatter)
    file.setFormatter(formatter)
    console = logging.getLogger('pyxaseco.console.file')
    console.setLevel(logging.INFO)
    console.propagate = False
    console.handlers = [file]


async def _restart_controller(logger: logging.Logger, reason: str) -> None:
    logger.info('PyXaseco restart requested - re-executing the controller process (%s)', reason)
    await asyncio.sleep(2.0)
    os.execv(sys.executable, [sys.executable, *sys.argv])


async def main():
    parser = argparse.ArgumentParser(description='PyXaseco - TMF server controller')
    parser.add_argument('config', nargs='?', default='config.toml',
                        help='Config file (default: config.toml)')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')
    parser.add_argument('--perf', action='store_true',
                        help='Log bounded performance summaries every 60 seconds')
    args = parser.parse_args()

    setup_logging(args.debug)
    logger = logging.getLogger('pyxaseco')

    # Resolve config to an absolute path so sibling files
    # (apps.toml, adminops.toml, apps/ folder, etc.) are always
    # found correctly regardless of working directory.
    config_path = str(Path(args.config).resolve())

    aseco = Aseco(debug=args.debug, performance=args.perf)
    restart_reason = 'clean shutdown restart request'
    try:
        await aseco.run(config_path)
    except KeyboardInterrupt:
        print('\n[PyXaseco] Shutting down...')
        await aseco._notify_shutdown()
        return
    except Exception as e:
        if aseco.restart_requested:
            logger.error(
                'Run failed while restart was requested; retrying controller re-exec: %s',
                e,
                exc_info=True,
            )
            restart_reason = 'restart-requested after fatal run error'
        else:
            logger.critical('Fatal error: %s', e, exc_info=True)
            sys.exit(1)
    finally:
        try:
            await aseco.close_background()
        finally:
            try:
                await aseco.client.disconnect()
            finally:
                await aseco.performance.stop()

    if aseco.restart_requested:
        await _restart_controller(logger, restart_reason)


if __name__ == '__main__':
    asyncio.run(main())
