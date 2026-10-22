"""Local instance/configuration CLI; no controller process is started."""

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tomllib

from .config_store import ManagementError
from .instances import InstanceRegistry
from .operations import ManagementOperations, read_config


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='PyXaseco local administrator (headless foundation)')
    parser.add_argument('--registry', help='Explicit instance inventory JSON path')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='List registered local installations')
    register = commands.add_parser('register', help='Register an existing installation without starting it')
    register.add_argument('folder')
    register.add_argument('--name', required=True)
    register.add_argument('--python', dest='python_path', default=sys.executable)
    register.add_argument('--dedicated')
    prepare = commands.add_parser('service-prepare', help='Generate definitions only; does not register/start services')
    prepare.add_argument('--instance', required=True)
    prepare.add_argument('--platform', choices=('windows', 'linux'), required=True)
    prepare.add_argument('--output', required=True)
    prepare.add_argument('--manage-dedicated', action='store_true')
    prepare.add_argument('--user', default='')
    prepare.add_argument('--automatic', action='store_true')
    services = commands.add_parser('service', help='Query or explicitly control already-installed instance services')
    services.add_argument('--plan', required=True)
    services.add_argument('target', choices=('controller', 'dedicated', 'both'))
    services.add_argument('action', choices=('status', 'start', 'stop', 'restart', 'enable', 'disable', 'reset-failure'))
    services.add_argument('--confirm', action='store_true')
    stop = commands.add_parser('service-signal', help='Internal graceful-stop helper for WinSW')
    stop.add_argument('--folder', required=True)
    stop.add_argument('--timeout', type=float, default=50)
    bridge = commands.add_parser('bridge-init', help='Provision private local credentials; never starts a listener')
    target = bridge.add_mutually_exclusive_group(required=True)
    target.add_argument('--instance')
    target.add_argument('--folder')
    bridge.add_argument('--offline', action='store_true')
    bridge.add_argument('--enable', action='store_true', help='Enable optional bridge for next controller start')
    bridge.add_argument('--service-reader', action='store_true', help='Grant Windows LocalService token read access on creation')
    online = commands.add_parser('online', help='Contact the optional authenticated local bridge')
    target = online.add_mutually_exclusive_group(required=True)
    target.add_argument('--instance')
    target.add_argument('--folder')
    online.add_argument('action', choices=('status', 'apps', 'capabilities', 'result', 'submit'))
    online.add_argument('--request-id', help='Stable ID for submit, or existing ID for result')
    online.add_argument('--request-file', help='JSON command file, or - for standard input; keeps secrets out of arguments')
    online.add_argument('--wait', type=float, default=0, help='Wait up to 60 seconds for a submitted operation')
    for command in ('inspect', 'validate', 'config-read', 'config-set', 'app-state'):
        item = commands.add_parser(command)
        target = item.add_mutually_exclusive_group(required=True)
        target.add_argument('--instance', help='Registered stable ID or unique name')
        target.add_argument('--folder', help='Controller or dedicated-server folder')
        if command in ('config-read', 'config-set'):
            item.add_argument('file', help='Relative config path')
        if command == 'config-set':
            item.add_argument('--key', nargs='+', required=True, help='TOML path segments')
            item.add_argument('--value-json', required=True, help='Typed JSON value; quote TOML strings')
        if command == 'app-state':
            item.add_argument('app')
            item.add_argument('state', choices=('enable', 'disable'))
        if command in ('config-set', 'app-state'):
            item.add_argument('--revision', required=True, help='Revision from config-read')
            item.add_argument('--offline', action='store_true', help='Confirm the controller is stopped')
    args = parser.parse_args(argv)
    try:
        registry = InstanceRegistry(args.registry)
        if args.command == 'list':
            result = [asdict(instance) for instance in registry.list()]
        elif args.command == 'register':
            result = asdict(registry.register(args.folder, name=args.name, python=args.python_path,
                                             dedicated=args.dedicated))
        elif args.command == 'service-prepare':
            from .services import ServicePlan, prepare_bundle
            instance = registry.get(args.instance)
            plan = ServicePlan.from_instance(instance, platform=args.platform,
                manage_dedicated=args.manage_dedicated, user=args.user, automatic=args.automatic)
            result = {'plan': str(prepare_bundle(plan, args.output)), 'installed': False, 'started': False}
        elif args.command == 'service-signal':
            from .lifecycle import signal_service_stop
            result = signal_service_stop(args.folder, args.timeout)
        elif args.command == 'service':
            from .services import ServiceAdapter, ServicePlan
            plan = ServicePlan.read(args.plan)
            adapter = ServiceAdapter(plan)
            if args.action == 'reset-failure':
                if not args.confirm or args.target != 'controller':
                    raise ManagementError('Failure reset requires controller --confirm and a stopped controller')
                from .lifecycle import reset_failure_history
                reset_failure_history(Path(plan.controller))
                if plan.platform == 'linux':
                    adapter._run(['systemctl', '--no-ask-password', 'reset-failed', plan.controller_service + '.service'])
                result = {'reset': True, 'started': False}
            elif args.action == 'status':
                targets = ('controller', 'dedicated') if args.target == 'both' else (args.target,)
                result = {target: adapter.status(target) for target in targets}
            else:
                result = adapter.action(args.target, args.action, confirmed=args.confirm)
        elif args.command == 'bridge-init':
            from .credentials import initialize_bridge
            instance = registry.get(args.instance) if args.instance else None
            result = initialize_bridge(args.folder if instance is None else instance.controller,
                instance_id=instance.id if instance else None, offline=args.offline,
                enable=args.enable, service_reader=args.service_reader)
        elif args.command == 'online':
            from .runtime_client import RuntimeClient
            root = args.folder if args.folder else registry.get(args.instance).controller
            if not 0 <= args.wait <= 60:
                raise ManagementError('Wait timeout must be between 0 and 60 seconds')
            payload = None
            if args.action == 'submit':
                if not args.request_file:
                    raise ManagementError('submit requires --request-file (or - for standard input)')
                if args.request_file == '-':
                    raw = sys.stdin.read(16385)
                else:
                    with Path(args.request_file).open(encoding='utf-8') as stream:
                        raw = stream.read(16385)
                if len(raw.encode('utf-8')) > 16384:
                    raise ManagementError('Operation body exceeds 16 KiB')
                payload = json.loads(raw)
            async def contact():
                async with RuntimeClient(root) as client:
                    if args.action == 'submit':
                        submitted = await client.submit(payload, request_id=args.request_id)
                        return await client.wait(submitted['id'], timeout=args.wait) if args.wait else submitted
                    if args.action == 'result':
                        return await client.result(args.request_id)
                    return await getattr(client, args.action)()
            result = asyncio.run(contact())
        else:
            root = args.folder if args.folder else registry.get(args.instance).controller
            operations = ManagementOperations(root)
            if args.command == 'inspect':
                result = operations.inspect()
            elif args.command == 'validate':
                result = operations.validate()
            elif args.command == 'config-read':
                result = read_config(operations, args.file)
            elif args.command == 'config-set':
                saved = operations.set_config(args.file, tuple(args.key), json.loads(args.value_json),
                                              expected=args.revision, offline=args.offline)
                result = {**asdict(saved), 'application': 'saved; restart required, runtime not contacted'}
            else:
                saved = operations.set_app_state(args.app, args.state == 'enable',
                                                 expected=args.revision, offline=args.offline)
                result = {**asdict(saved), 'application': 'saved; restart required, runtime not contacted'}
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0 if not isinstance(result, dict) or (result.get('valid', True)
            and result.get('state') not in {'failed', 'cancelled', 'saved-not-applied'}) else 1
    except (ManagementError, OSError, ValueError, TypeError, KeyError) as exc:
        # Parsers may embed the input (including passwords) in exception messages.
        if isinstance(exc, (tomllib.TOMLDecodeError, json.JSONDecodeError)):
            message = 'Invalid configuration/value syntax; input contents omitted'
        elif isinstance(exc, ManagementError):
            message = str(exc)
        else:
            message = f'Operation failed ({type(exc).__name__}); check paths, permissions and input types'
        print(json.dumps({'error': message}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
