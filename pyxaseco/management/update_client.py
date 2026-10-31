"""Two-publisher validation, download, comparison and explicit file replacement."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tomllib
from urllib.parse import urljoin, urlsplit

import aiohttp

from .config_store import ManagementError, file_lock
from .installation import safe_path
from .maintenance import _bytes, _replace
from pyxaseco.core.file_io import file_io
from .release_manifest import (
    ASSET_HOSTS, GITHUB_HOSTS, GITHUB_DOWNLOAD_HOSTS, WEBSITE_HOSTS, METADATA_LIMIT, PACKAGE_LIMIT,
    compatibility, https_url, read_json, validate_archive, verify_catalogue,
)


class PublisherUnavailable(ManagementError):
    """An unavailable mirror can be skipped; bad approval/integrity cannot."""


class UpdateClient:
    def __init__(self, root, controller_version, *, settings=None):
        self.root = safe_path(root)
        if settings is None:
            path = safe_path(self.root / 'apps/apps_manager/app_defaults.toml')
            try:
                if path.exists() and path.stat().st_size > 65536:
                    raise ManagementError('Apps Manager update settings exceed the size limit')
                data = tomllib.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
                section = data.get('apps_manager', {})
                settings = section.get('updates', {}) if isinstance(section, dict) else None
            except (tomllib.TOMLDecodeError, UnicodeError):
                raise ManagementError('Apps Manager update settings contain invalid TOML') from None
        if not isinstance(settings, dict):
            raise ManagementError('Apps Manager updates must be configured as a TOML table')
        self.settings = settings
        self.controller_version = controller_version
        self.area = safe_path(self.root / '.management-maintenance/releases')

    def _configuration(self):
        if self.settings.get('enabled') is not True:
            raise ManagementError('Release downloads are disabled until publishing URLs and the trusted public key are configured')
        github = https_url(self.settings.get('github_manifest', ''), GITHUB_HOSTS)
        website = https_url(self.settings.get('validation_manifest', ''), WEBSITE_HOSTS)
        channel = self.settings.get('channel', 'stable')
        key = self.settings.get('public_key', '')
        if channel not in {'stable', 'development'} or not isinstance(key, str) or not key:
            raise ManagementError('Configure the release channel and locally trusted signing public key')
        return github, website, channel, key

    async def _fetch(self, session, url, allowed, limit):
        for _ in range(6):
            https_url(url, allowed)
            async with session.get(url, allow_redirects=False) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get('Location')
                    if not location:
                        raise ManagementError('Release download redirect has no location')
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    endpoint = urlsplit(url)
                    location = endpoint.hostname + endpoint.path
                    hint = ''
                    if response.headers.get('cf-mitigated', '').lower() == 'challenge':
                        hint = ' (Cloudflare browser challenge)'
                    elif response.headers.get('X-RateLimit-Remaining') == '0':
                        hint = ' (publisher rate limit exhausted)'
                    # Redirect queries can contain signed download tokens; never log them.
                    raise PublisherUnavailable(
                        f'Release publisher {location} returned HTTP {response.status}{hint}; nothing installed')
                if response.content_length is not None and response.content_length > limit:
                    raise ManagementError('Release download exceeds its approved size')
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > limit:
                        raise ManagementError('Release download exceeds its approved size')
                return bytes(data)
        raise ManagementError('Too many release download redirects')

    def _remember(self, catalogue, digest):
        safe_path(self.area)
        self.area.mkdir(parents=True, mode=0o700, exist_ok=True)
        path = safe_path(self.area / ('seen-' + catalogue['channel'] + '.json'))
        with file_lock(safe_path(self.area / 'catalogue.lock')):
            before = _bytes(path)
            previous = read_json(before) if before else None
            if previous is not None:
                if (not isinstance(previous, dict) or type(previous.get('sequence')) is not int
                        or not isinstance(previous.get('digest'), str)):
                    raise ManagementError('Invalid local release history; review before downloading')
                if (catalogue['sequence'] < previous['sequence']
                        or (catalogue['sequence'] == previous['sequence'] and digest != previous['digest'])):
                    raise ManagementError('Release metadata is older than, or conflicts with, a previously approved catalogue')
            data = json.dumps({'sequence': catalogue['sequence'], 'digest': digest}).encode()
            if before != data:
                from .config_store import revision
                _replace(path, data, revision(before) if before else None)

    async def _check(self, session):
        github, website, channel, key = self._configuration()
        # Independent origins are required, including every redirect hop.
        first = await self._fetch(session, github, GITHUB_DOWNLOAD_HOSTS, METADATA_LIMIT)
        second = await self._fetch(session, website, WEBSITE_HOSTS, METADATA_LIMIT)
        catalogue, digest = await asyncio.to_thread(verify_catalogue, first, key, channel)
        _approved, approved_digest = await asyncio.to_thread(verify_catalogue, second, key, channel)
        if digest != approved_digest:
            raise ManagementError('GitHub and tmtrialgy.com do not approve the same catalogue; update postponed')
        await asyncio.to_thread(self._remember, catalogue, digest)
        return catalogue, digest

    @staticmethod
    def _session():
        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45, connect=10),
                                     trust_env=False, auto_decompress=False, headers={'Accept-Encoding': 'identity'})

    async def check(self):
        try:
            async with self._session() as session:
                return (await self._check(session))[0]
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise ManagementError('A release publisher is unavailable; no update was performed') from None

    def _store(self, blob, package, catalogue, digest):
        validate_archive(blob, package)
        safe_path(self.area)
        self.area.mkdir(parents=True, mode=0o700, exist_ok=True)
        name = package['id'] + '-' + package['sha256']
        folder = safe_path(self.area / name)
        folder.mkdir(mode=0o700, exist_ok=True)
        target = safe_path(folder / 'package.zip')
        with file_lock(safe_path(folder / 'stage.lock')):
            existing = target.read_bytes() if target.exists() and target.stat().st_size <= PACKAGE_LIMIT else None
            if target.exists() and existing is None:
                raise ManagementError('Existing staged package is too large; review local staging files')
            if existing is None:
                _replace(target, blob, None)
            elif existing != blob:
                raise ManagementError('Existing staged package differs; no files overwritten')
            evidence = {'catalogue': catalogue, 'catalogue_sha256': digest, 'package': package['id'],
                        'installed': False, 'dependencies_installed': False}
            path = safe_path(folder / 'review.json')
            from .config_store import revision
            before = _bytes(path)
            _replace(path, (json.dumps(evidence, indent=2) + '\n').encode(), revision(before) if before else None)
        return {'id': package['id'], 'version': package['version'], 'staged': str(target), 'installed': False}

    @staticmethod
    def _package(catalogue, identity):
        package = next((item for item in catalogue['packages'] if item['id'] == identity), None)
        if package is None:
            raise ManagementError('Package is not present in the approved catalogue')
        return package

    def _staged_blob(self, package):
        path = safe_path(self.area / (package['id'] + '-' + package['sha256']) / 'package.zip')
        if not path.is_file():
            raise ManagementError('Download this approved package first, then request its review')
        if path.stat().st_size != package['size']:
            raise ManagementError('Staged ZIP size differs from the current approved release; download/review it again')
        with path.open('rb') as stream:
            blob = stream.read(package['size'] + 1)
        validate_archive(blob, package)
        return blob

    def _compatible(self, package, *, dependencies=False):
        reasons = compatibility(package, self.controller_version, '.'.join(map(str, sys.version_info[:3])))
        if reasons:
            raise ManagementError('; '.join(reasons))
        if not dependencies:
            return
        # Use existing libraries; never create or switch Python environments.
        from importlib.metadata import PackageNotFoundError, version as installed_version
        for item in package['python_requirements']:
            try:
                installed = installed_version(item['name'])
            except PackageNotFoundError:
                installed = None
            if installed != item['version']:
                raise ManagementError('Install required library ' + item['name'] + '==' + item['version'] + ' with your existing Python, then retry')
        if package['requires_apps']:
            from .file_updates import FileUpdates
            from .app_policy import MANAGEABLE_STANDALONE_APPS
            from .release_manifest import version
            ledger, _raw = FileUpdates(self.root)._ledger()
            loadout_path = safe_path(self.root / 'apps.toml')
            loadout = tomllib.loads((_bytes(loadout_path) or b'').decode()).get('loadout', {})
            for identity, bounds in package['requires_apps'].items():
                entry = ledger['packages'].get(identity)
                found = entry['version'] if entry else (self.controller_version if identity not in MANAGEABLE_STANDALONE_APPS else None)
                if (not (self.root / 'apps' / identity / 'app.py').is_file()
                        or 'app/' + identity not in loadout.get('enabled', []) or found is None
                        or not version(bounds['min']) <= version(found) < version(bounds['max_exclusive'])):
                    raise ManagementError('Required app is missing, disabled or incompatible: ' + identity)

    async def apply(self, identity, *, reviewed=None, force=False, confirmed=False):
        if confirmed is not True:
            raise ManagementError('Confirm file replacement first; nothing installed')
        from .file_updates import FileUpdates
        try:
            async with self._session() as session:
                catalogue, _digest = await self._check(session)
                package = self._package(catalogue, identity)
                self._compatible(package, dependencies=True)
                blob = await asyncio.to_thread(self._staged_blob, package)
                # Join disk writes even if shutdown cancels the request. No background writer is abandoned.
                return await file_io(FileUpdates(self.root).apply, package, blob,
                    reviewed=reviewed, force=force, confirmed=True)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise ManagementError('A release publisher is unavailable; package installation postponed') from None

    async def preview(self, identity, *, force=False):
        from .file_updates import FileUpdates
        try:
            async with self._session() as session:
                catalogue, _digest = await self._check(session)
                package = self._package(catalogue, identity)
                self._compatible(package)
                # Local review.json is diagnostic only; recheck fresh approvals and the ZIP itself.
                blob = await asyncio.to_thread(self._staged_blob, package)
                plan = await asyncio.to_thread(FileUpdates(self.root).preview, package, blob, force=force)
                plan['requirements'] = []
                try:
                    self._compatible(package, dependencies=True)
                except ManagementError as error:
                    plan['requirements'].append(str(error))
                return plan
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise ManagementError('A release publisher is unavailable; package review postponed') from None

    async def stage(self, identity):
        try:
            async with self._session() as session:
                catalogue, digest = await self._check(session)
                package = self._package(catalogue, identity)
                reasons = compatibility(package, self.controller_version, '.'.join(map(str, sys.version_info[:3])))
                if reasons:
                    raise ManagementError('; '.join(reasons))
                blob = None
                for url in package['urls']:
                    try:
                        blob = await self._fetch(session, url, ASSET_HOSTS, package['size'])
                        break
                    except (aiohttp.ClientError, asyncio.TimeoutError, PublisherUnavailable):
                        continue
                if blob is None:
                    raise ManagementError('Package mirrors are unavailable; nothing installed')
                # Recheck expiration after a potentially slow package transfer.
                from datetime import datetime, timezone
                if datetime.strptime(catalogue['expires'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
                    raise ManagementError('Release approval expired during download; nothing staged')
                return await asyncio.to_thread(self._store, blob, package, catalogue, digest)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise ManagementError('A release publisher is unavailable; no update was performed') from None


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Validate, download, review and copy releases. Restart manually with //pyres.')
    parser.add_argument('--root', default='.')
    parser.add_argument('--controller-version', required=True, help='Currently installed controller version')
    parser.add_argument('action', choices=('check', 'stage', 'review', 'apply'))
    parser.add_argument('package', nargs='?')
    parser.add_argument('--confirm', action='store_true', help='Confirm backed-up file replacement')
    parser.add_argument('--force', action='store_true', help='Also replace modified official code, after backing it up')
    parser.add_argument('--review', help='Optional review hash returned by the review action')
    args = parser.parse_args(argv)
    try:
        client = UpdateClient(Path(args.root), args.controller_version)
        if args.action != 'check' and not args.package:
            raise ManagementError('stage/review/apply requires a package ID')
        operation = client.check() if args.action == 'check' else (
            client.stage(args.package) if args.action == 'stage' else (
                client.preview(args.package, force=args.force) if args.action == 'review' else
                client.apply(args.package, reviewed=args.review, force=args.force, confirmed=args.confirm)))
        result = asyncio.run(operation)
        print(json.dumps(result, indent=2))
        return 0
    except (ManagementError, OSError) as exc:
        message = str(exc) if isinstance(exc, ManagementError) else 'Could not read/write local release staging files'
        print(json.dumps({'error': message}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
