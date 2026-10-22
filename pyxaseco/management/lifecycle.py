"""Graceful supervised lifecycle, independent of the optional management bridge."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import csv
import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
import time
from uuid import uuid4

from .config_store import ManagementError, runtime_lock


EXIT_RESTART = 75
EXIT_CONFIGURATION = 78
logger = logging.getLogger(__name__)


def arm_exit_watchdog(exit_code: int, delay=10):
    """Bound asyncio/executor interpreter teardown after supervised cleanup returns."""
    def expired():
        with suppress(OSError):
            os.write(2, b'[PyXaseco] Supervised interpreter shutdown timed out; forcing own process exit. Retained files are preserved.\n')
        os._exit(exit_code)
    timer = threading.Timer(delay, expired)
    timer.daemon = True
    timer.start()


def _write_json(path: Path, data):
    fd, name = tempfile.mkstemp(prefix='.service-', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path):
    if path.is_symlink() or path.stat().st_size > 16384:
        raise ManagementError('Invalid service control file')
    return json.loads(path.read_text(encoding='utf-8'))


def private_control_directory(root: Path) -> Path:
    directory = root / '.management-control'
    if directory.is_symlink():
        raise ManagementError('Service control directory may not be a symbolic link')
    directory.mkdir(mode=0o700, exist_ok=True)
    if os.name != 'nt':
        if directory.stat().st_uid != os.getuid():
            raise ManagementError('Service control directory must belong to the runtime user')
        os.chmod(directory, 0o700)
    else:
        # Grant only this process identity, SYSTEM and Administrators, never Everyone.
        system = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32'
        who = subprocess.run([str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'],
                             capture_output=True, text=True, timeout=10, check=True)
        sid = next(csv.reader([who.stdout.strip()]))[-1]
        if not re.fullmatch(r'S-1-[0-9-]+', sid):
            raise ManagementError('Could not identify the service account SID')
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        descriptor = ctypes.c_void_p()
        api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        api.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        sddl = f'D:P(A;OICI;FA;;;{sid})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'
        if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise ManagementError('Cannot construct service control ACL')
        try:
            if not api.SetFileSecurityW(str(directory), 0x80000004, descriptor):
                raise ManagementError('Cannot secure service control directory; refusing supervised startup')
        finally:
            kernel.LocalFree(descriptor)
    return directory


class ServiceSession:
    def __init__(self, root: Path, instance_id: str):
        self.root = root
        self.directory = private_control_directory(root)
        self.instance_id = instance_id
        self.run_id = uuid4().hex
        self.stop = asyncio.Event()
        self.state = 'starting'
        self.signals = {}

    def publish(self, state: str, *, exit_code: int | None = None):
        self.state = state
        data = {'instance_id': self.instance_id, 'run_id': self.run_id, 'pid': os.getpid(),
                'state': state, 'updated_at': time.time(), 'exit_code': exit_code}
        _write_json(self.directory / 'status.json', data)

    def stop_requested(self) -> bool:
        try:
            request = _read_json(self.directory / 'stop.json')
            if request.get('run_id') == self.run_id and request.get('action') == 'stop':
                self.stop.set()
        except FileNotFoundError:
            pass
        except (OSError, ValueError, ManagementError):
            logger.warning('Ignoring invalid service stop request')
        return self.stop.is_set()

    async def watch(self, aseco):
        while not self.stop_requested():
            if self.state == 'starting' and not getattr(aseco, 'startup_phase', True):
                self.publish('running (application health not yet verified)')
            await asyncio.sleep(.25)

    def install_signals(self):
        loop = asyncio.get_running_loop()
        for name in ('SIGTERM', 'SIGINT'):
            signum = getattr(signal, name)
            self.signals[signum] = signal.getsignal(signum)
            try:
                loop.add_signal_handler(signum, self.stop.set)
            except (NotImplementedError, RuntimeError):
                # ProactorEventLoop does not implement add_signal_handler on Windows.
                signal.signal(signum, lambda _sig, _frame: loop.call_soon_threadsafe(self.stop.set))

    def restore_signals(self):
        loop = asyncio.get_running_loop()
        for signum, previous in self.signals.items():
            with suppress(NotImplementedError, RuntimeError):
                loop.remove_signal_handler(signum)
            signal.signal(signum, previous)

    def failures(self) -> list[float]:
        try:
            values = _read_json(self.directory / 'failures.json')
            now = time.time()
            return [value for value in values if type(value) in (float, int) and 0 <= now - value < 300]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, TypeError):
            raise ManagementError('Service failure history is invalid; inspect it before resetting')

    def record_failure(self) -> int:
        values = [*self.failures(), time.time()]
        _write_json(self.directory / 'failures.json', values[-5:])
        return EXIT_CONFIGURATION if len(values) >= 3 else 1


async def _bounded(awaitable, timeout):
    task = asyncio.ensure_future(awaitable)
    done, _ = await asyncio.wait((task,), timeout=max(.05, timeout))
    if not done:
        task.cancel()
        task.add_done_callback(lambda finished: finished.exception() if not finished.cancelled() else None)
        raise TimeoutError('Service operation exceeded its graceful-stop budget')
    return task.result()


async def run_supervised(aseco, config: str, session: ServiceSession, *, stop_timeout=45) -> int:
    """OS supervises restarts; this function never forks, re-execs or retries run()."""
    if len(session.failures()) >= 3:
        session.publish('blocked (three failures in five minutes)', exit_code=EXIT_CONFIGURATION)
        # WinSW treats nonzero exits as restartable. Stop cleanly on the next launch.
        return 0
    session.publish('starting')
    session.install_signals()
    run = asyncio.create_task(aseco.run(config), name='supervised-controller')
    watcher = asyncio.create_task(session.watch(aseco), name='service-stop-monitor')
    exit_code = 0
    requested_stop = False
    deadline = None
    try:
        done, _ = await asyncio.wait((run, watcher), return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            await watcher  # Watcher failure must not masquerade as a clean stop.
        requested_stop = session.stop_requested()
        if requested_stop:
            deadline = asyncio.get_running_loop().time() + stop_timeout
            session.publish('stopping')
            aseco._restart_requested = False
            # A service-stop means this controller only, not the dedicated service.
            aseco._shutdown_stop_server = False
            await _bounded(aseco.shutdown(stop_server=False), stop_timeout / 2)
            if getattr(aseco, 'startup_phase', True):
                run.cancel()
            try:
                await _bounded(asyncio.shield(run), stop_timeout / 2)
            except asyncio.CancelledError:
                if not run.cancelled():
                    raise
        else:
            await run
            exit_code = EXIT_RESTART if aseco.restart_requested else 0
    except asyncio.CancelledError:
        requested_stop = True
        run.cancel()
        raise
    except Exception:
        logger.exception('Supervised controller failed; recovery belongs to the OS service manager')
        exit_code = EXIT_RESTART if aseco.restart_requested and not requested_stop else session.record_failure()
    finally:
        if deadline is None:
            deadline = asyncio.get_running_loop().time() + stop_timeout
        watcher.cancel()
        if not run.done():
            run.cancel()
        finished, pending = await asyncio.wait((run, watcher), timeout=min(
            max(.05, deadline - asyncio.get_running_loop().time()), 5))
        for task in finished:
            with suppress(BaseException):
                task.result()
        if pending:
            logger.error('Controller tasks resisted cancellation; OS service stop timeout remains the final bound')
            exit_code = session.record_failure()
        async def cleanup():
            try:
                await aseco.close_background()
            finally:
                try:
                    await aseco.client.disconnect()
                finally:
                    await aseco.performance.stop()
        try:
            await _bounded(cleanup(), deadline - asyncio.get_running_loop().time())
        except Exception:
            logger.exception('Supervised cleanup did not complete; retained files are left intact')
            exit_code = session.record_failure()
        finally:
            session.restore_signals()
        if requested_stop:
            # Never turn an intentional service stop into recovery/restart.
            session.publish('stopped' if exit_code == 0 else 'stopped (cleanup failed)', exit_code=exit_code)
            exit_code = 0
        else:
            session.publish('restart-requested' if exit_code == EXIT_RESTART else 'stopped' if exit_code == 0 else 'failed',
                            exit_code=exit_code)
    return exit_code


def signal_service_stop(root: str | Path, timeout=50) -> dict:
    """WinSW stop helper: request a graceful stop, never terminate an arbitrary PID."""
    root = Path(root).resolve()
    if not 0 < timeout <= 120:
        raise ManagementError('Stop timeout must be between 0 and 120 seconds')
    directory = root / '.management-control'
    if directory.is_symlink():
        raise ManagementError('Unsafe service control directory')
    deadline = time.monotonic() + timeout
    requested = None
    while time.monotonic() < deadline:
        try:
            with runtime_lock(root):
                return {'stopped': True, 'forced': False}
        except ManagementError:
            pass
        try:
            status = _read_json(directory / 'status.json')
        except FileNotFoundError:
            time.sleep(.1)
            continue
        if not re.fullmatch(r'[0-9a-f]{32}', str(status.get('run_id', ''))):
            raise ManagementError('Invalid service run identity')
        if requested is not None and status['run_id'] != requested:
            raise ManagementError('Controller changed generation during stop; inspect service status')
        if requested is None:
            requested = status['run_id']
            _write_json(directory / 'stop.json', {'run_id': requested, 'action': 'stop'})
        time.sleep(.1)
    raise ManagementError('Graceful stop timed out; no forced termination was issued by the helper')


def reset_failure_history(root: Path):
    with runtime_lock(root):
        directory = root / '.management-control'
        if directory.is_symlink():
            raise ManagementError('Unsafe service control directory')
        if directory.exists():
            _write_json(directory / 'failures.json', [])
