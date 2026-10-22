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

from pyxaseco.management.config_store import ManagementError, runtime_lock

MANAGEMENT_RUNTIME_LOCK = 1
Aseco = None


def _create_controller(**kwargs):
    global Aseco
    if Aseco is None:
        from pyxaseco.core.aseco import Aseco as controller_class
        Aseco = controller_class
    return Aseco(**kwargs)


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
    parser.add_argument('--supervised', action='store_true',
                        help='Let the OS service manager own restart/recovery')
    parser.add_argument('--service-plan', help='Prepared per-installation service plan')
    args = parser.parse_args()
    if args.supervised != bool(args.service_plan):
        parser.error('--supervised and --service-plan must be supplied together')

    try:
        with runtime_lock(Path(args.config).resolve().parent):
            if args.supervised:
                return await _run_service_controller(args)
            restart_reason = await _run_controller(args)
    except (ManagementError, OSError, ValueError) as exc:
        if not args.supervised:
            raise
        detail = str(exc) if isinstance(exc, ManagementError) else 'check plan syntax, paths and permissions'
        print(f'[PyXaseco] Service startup refused ({type(exc).__name__}): {detail}', file=sys.stderr)
        return 0 if os.name == 'nt' else 78
    if restart_reason:
        await _restart_controller(logging.getLogger('pyxaseco'), restart_reason)


async def _run_controller(args):
    setup_logging(args.debug)
    logger = logging.getLogger('pyxaseco')

    # Resolve config to an absolute path so sibling files
    # (apps.toml, adminops.toml, apps/ folder, etc.) are always
    # found correctly regardless of working directory.
    config_path = str(Path(args.config).resolve())

    aseco = _create_controller(debug=args.debug, performance=args.perf)
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
        return restart_reason


async def _run_service_controller(args):
    from pyxaseco.management.lifecycle import ServiceSession, arm_exit_watchdog, run_supervised
    from pyxaseco.management.services import ManagedLifecycle, ServicePlan
    config = Path(args.config).resolve()
    plan = ServicePlan.read(args.service_plan)
    if Path(plan.config).resolve() != config:
        raise ManagementError('Service plan does not belong to this controller config')
    if plan.platform != ('windows' if os.name == 'nt' else 'linux'):
        raise ManagementError('Service plan targets a different operating system')
    # Explicit CWD prevents a service from loading another folder's .env/logs.
    os.chdir(config.parent)
    setup_logging(args.debug)
    session = ServiceSession(config.parent, plan.instance_id)
    try:
        aseco = _create_controller(debug=args.debug, performance=args.perf)
        aseco.register_service('management.lifecycle', ManagedLifecycle(plan), owner='management')
    except Exception:
        logging.getLogger('pyxaseco').exception('Controller construction/import failed under service supervision')
        if len(session.failures()) >= 3:
            session.publish('blocked', exit_code=78)
            return 0 if os.name == 'nt' else 78
        code = session.record_failure()
        session.publish('failed', exit_code=code)
        return code
    code = await run_supervised(aseco, str(config), session)
    arm_exit_watchdog(code)
    return code


if __name__ == '__main__':
    try:
        sys.exit(asyncio.run(main()) or 0)
    except ManagementError as exc:
        print(f'[PyXaseco] {exc}', file=sys.stderr)
        sys.exit(2)
