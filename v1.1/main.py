#!/usr/bin/env python3
"""
PyXaseco — Python port of Xaseco for TrackMania Forever.

Usage:
    python main.py [config.xml] [--debug]

Run this from the folder that contains config.xml, plugins.xml, etc.
"""

import asyncio
import argparse
import logging
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


async def main():
    parser = argparse.ArgumentParser(description='PyXaseco - TMF server controller')
    parser.add_argument('config', nargs='?', default='config.xml',
                        help='Config file (default: config.xml)')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')
    args = parser.parse_args()

    setup_logging(args.debug)

    # Resolve config to an absolute path so sibling files
    # (plugins.xml, adminops.xml, plugins/ folder, etc.) are always
    # found correctly regardless of working directory.
    config_path = str(Path(args.config).resolve())

    aseco = Aseco(debug=args.debug)
    try:
        await aseco.run(config_path)
    except KeyboardInterrupt:
        print('\n[PyXaseco] Shutting down...')
        await aseco.release_event('onShutdown', None)
        await aseco.client.disconnect()
    except Exception as e:
        logging.getLogger('pyxaseco').critical('Fatal error: %s', e, exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
