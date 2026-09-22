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
import os
import sys
from pathlib import Path

from pyxaseco.core.aseco import Aseco


def setup_logging(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('logfile.txt', mode='a', encoding='utf-8'),
        ]
    )


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
    args = parser.parse_args()

    setup_logging(args.debug)
    logger = logging.getLogger('pyxaseco')

    # Resolve config to an absolute path so sibling files
    # (apps.toml, adminops.toml, apps/ folder, etc.) are always
    # found correctly regardless of working directory.
    config_path = str(Path(args.config).resolve())

    aseco = Aseco(debug=args.debug)
    try:
        await aseco.run(config_path)
    except KeyboardInterrupt:
        print('\n[PyXaseco] Shutting down...')
        await aseco.release_event('onShutdown', None)
        await aseco.client.disconnect()
        return
    except Exception as e:
        if aseco.restart_requested:
            logger.error(
                'Run failed while restart was requested; retrying controller re-exec: %s',
                e,
                exc_info=True,
            )
            await _restart_controller(logger, 'restart-requested after fatal run error')
            return
        logger.critical('Fatal error: %s', e, exc_info=True)
        sys.exit(1)

    if aseco.restart_requested:
        await _restart_controller(logger, 'clean shutdown restart request')


if __name__ == '__main__':
    asyncio.run(main())
