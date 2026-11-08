"""Release catalogue and ZIP validation. Never imports downloaded code."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import io
import json
import re
import stat
from urllib.parse import urlsplit
import zipfile
import zlib

from .app_policy import MANAGEABLE_STANDALONE_APPS
from .config_store import ManagementError, revision
from .installation import payload_path


METADATA_LIMIT = 2 * 1024 * 1024
PACKAGE_LIMIT = 64 * 1024 * 1024
EXPANDED_LIMIT = 128 * 1024 * 1024
FILE_LIMIT = 16 * 1024 * 1024
SIGNING_CONTEXT = b'PyXaseco release catalogue v1\n'
GITHUB_HOSTS = frozenset(('github.com', 'raw.githubusercontent.com', 'api.github.com'))
GITHUB_DOWNLOAD_HOSTS = GITHUB_HOSTS | frozenset(('release-assets.githubusercontent.com', 'objects.githubusercontent.com'))
WEBSITE_HOSTS = frozenset(('tmtrialgy.com', 'www.tmtrialgy.com'))
ASSET_HOSTS = GITHUB_HOSTS | WEBSITE_HOSTS | frozenset((
    'release-assets.githubusercontent.com', 'objects.githubusercontent.com',
))
PUBLIC_APPS = frozenset(MANAGEABLE_STANDALONE_APPS) - {'server_admin_bridge'}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ManagementError('Duplicate field in release metadata')
        result[key] = value
    return result


def read_json(data):
    try:
        return json.loads(data, object_pairs_hook=_unique_pairs,
                          parse_constant=lambda value: _invalid('Non-finite release metadata'))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ManagementError('Invalid release metadata') from exc


def _invalid(message):
    raise ManagementError(message)


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,4}\.\d{1,4}(?:\.\d{1,4})?', value):
        raise ManagementError('Release versions must use major.minor[.patch]')
    parts = tuple(int(part) for part in value.split('.'))
    return parts + (0,) * (3 - len(parts))


def https_url(value, allowed):
    try:
        url = urlsplit(value)
        if (not isinstance(value, str) or any(ord(char) <= 32 for char in value)
                or '\\' in value or url.scheme != 'https' or url.hostname not in allowed
                or url.username or url.password or url.port not in (None, 443) or url.fragment):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ManagementError('Release URLs must use HTTPS on the approved publishing hosts') from None
    return value


def _hex(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _decode(value, size=None):
    try:
        decoded = base64.b64decode(value, validate=True)
    except (TypeError, ValueError, binascii.Error):
        raise ManagementError('Invalid release signature encoding') from None
    if size is not None and len(decoded) != size:
        raise ManagementError('Invalid release signature length')
    return decoded


def package_path(name, package):
    if not isinstance(name, str):
        raise ManagementError('Invalid package file path')
    # Reuse the installer's Windows-safe path checks, also for packages staged on Linux.
    if name.endswith(('/README.md', '/LICENSE')) and name.startswith('apps/'):
        payload_path(name.rsplit('/', 1)[0] + '/app.py')
    else:
        payload_path(name)
    if package['kind'] == 'app':
        if not name.startswith('apps/' + package['id'] + '/'):
            raise ManagementError('An app package may only own files inside its own app folder')
    elif name.startswith('apps/') and name.split('/')[1] in MANAGEABLE_STANDALONE_APPS:
        raise ManagementError('Controller packages must not bundle independently managed optional apps')


def _range(value):
    if not isinstance(value, dict) or set(value) != {'min', 'max_exclusive'}:
        raise ManagementError('Compatibility requires min and max_exclusive versions')
    if version(value['min']) >= version(value['max_exclusive']):
        raise ManagementError('Invalid compatibility range')


def validate_package(package):
    fields = {'id', 'kind', 'version', 'sha256', 'size', 'urls', 'files',
              'python', 'controller', 'requires_apps', 'python_requirements'}
    if not isinstance(package, dict) or not fields <= package.keys() or set(package) - fields - {'baseline'}:
        raise ManagementError('Unsupported package metadata fields')
    identity = package['id']
    if not ((package['kind'] == 'controller' and identity == 'controller')
            or (package['kind'] == 'app' and isinstance(identity, str) and identity in PUBLIC_APPS)):
        raise ManagementError('Unknown or private package identity')
    version(package['version'])
    if not _hex(package['sha256']) or not _integer(package['size'], 1, PACKAGE_LIMIT):
        raise ManagementError('Invalid package checksum or size')
    urls = package['urls']
    if not isinstance(urls, list) or not 1 <= len(urls) <= 2:
        raise ManagementError('A package requires one or two download locations')
    for url in urls:
        https_url(url, ASSET_HOSTS)
    _range(package['python'])
    _range(package['controller'])
    required = package['requires_apps']
    if not isinstance(required, dict) or len(required) > 64:
        raise ManagementError('Invalid app dependencies')
    for app, bounds in required.items():
        if not re.fullmatch('[a-z][a-z0-9_]{0,63}', app) or app == identity:
            raise ManagementError('Invalid app dependency identity')
        _range(bounds)
    requirements = package['python_requirements']
    if not isinstance(requirements, list) or len(requirements) > 128:
        raise ManagementError('Invalid Python dependency inventory')
    for item in requirements:
        if (not isinstance(item, dict) or not {'name', 'version'} <= item.keys()
                or set(item) - {'name', 'version', 'sha256'}
                or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,99}', str(item['name']))
                or not re.fullmatch('[0-9][A-Za-z0-9.!+_-]{0,79}', str(item['version']))
                or ('sha256' in item and (not isinstance(item['sha256'], list)
                    or not 1 <= len(item['sha256']) <= 64 or not all(_hex(digest) for digest in item['sha256'])))):
            raise ManagementError('Python dependencies must have exact versions')
    files = package['files']
    if not isinstance(files, dict) or not 1 <= len(files) <= 4096:
        raise ManagementError('Invalid package inventory')
    names = {name.casefold() for name in files}
    if len(names) != len(files):
        raise ManagementError('Case-colliding package paths')
    total = 0
    directories = {}
    for name, entry in files.items():
        package_path(name, package)
        parents = name.split('/')[:-1]
        if any('/'.join(parents[:index]).casefold() in names for index in range(1, len(parents) + 1)):
            raise ManagementError('A package file conflicts with a directory')
        for index in range(1, len(parents) + 1):
            directory = '/'.join(parents[:index])
            if directories.setdefault(directory.casefold(), directory) != directory:
                raise ManagementError('Inconsistent directory casing in package paths')
        if (not isinstance(entry, dict) or set(entry) != {'sha256', 'size'}
                or not _hex(entry['sha256']) or not _integer(entry['size'], 0, FILE_LIMIT)):
            raise ManagementError('Invalid file checksum or size')
        total += entry['size']
    if total > EXPANDED_LIMIT:
        raise ManagementError('Package exceeds expanded size limit')
    if package['kind'] == 'app':
        # Apps may be namespace packages; their executable entrypoint is app.py.
        required_files = {f'apps/{identity}/app.py'}
    else:
        required_files = {'main.py', 'pyxaseco/core/aseco.py', 'pyxaseco/management/config_store.py'}
    if not required_files <= files.keys():
        raise ManagementError('Package is missing its entrypoint or maintenance protection')
    if 'baseline' in package:
        baseline = package['baseline']
        if not isinstance(baseline, dict) or set(baseline) != {'version', 'files'}:
            raise ManagementError('Invalid original-release baseline')
        version(baseline['version'])
        previous = baseline['files']
        if not isinstance(previous, dict) or len(previous) > 4096 or len({name.casefold() for name in previous}) != len(previous):
            raise ManagementError('Invalid original-release file inventory')
        for name, item in previous.items():
            package_path(name, package)
            if (not isinstance(item, dict) or set(item) != {'sha256', 'size'}
                    or not _hex(item['sha256']) or not _integer(item['size'], 0, FILE_LIMIT)):
                raise ManagementError('Invalid original-release file checksum')


def parse_checksum(blob, filename):
    try:
        line = blob.decode('ascii').strip()
    except UnicodeError:
        raise ManagementError('Invalid SHA-256 checksum file') from None
    match = re.fullmatch(r'([0-9a-fA-F]{64})(?:[ \t]+\*?' + re.escape(filename) + r')?', line)
    if not match:
        raise ManagementError('Invalid SHA-256 checksum or filename')
    return match[1].lower()


def verify_catalogue(blob, public_key, channel, *, now=None, verification='signed'):
    if len(blob) > METADATA_LIMIT:
        raise ManagementError('Release metadata exceeds the download limit')
    fields = {'schema', 'sequence', 'channel', 'packages'}
    if verification == 'signed':
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        envelope = read_json(blob)
        if not isinstance(envelope, dict) or set(envelope) != {'signed', 'signature'}:
            raise ManagementError('Unsupported signed release envelope')
        payload = _decode(envelope['signed'])
        key = _decode(public_key, 32)
        try:
            Ed25519PublicKey.from_public_bytes(key).verify(
                _decode(envelope['signature'], 64), SIGNING_CONTEXT + payload)
        except InvalidSignature:
            raise ManagementError('Release signature does not match the locally trusted public key') from None
        schema = 1
        fields.add('expires')
    elif verification == 'sha256':
        payload, schema = blob, 2
    else:
        raise ManagementError('Unsupported release verification mode')
    catalogue = read_json(payload)
    if (not isinstance(catalogue, dict) or set(catalogue) != fields
            or type(catalogue['schema']) is not int or catalogue['schema'] != schema
            or not _integer(catalogue['sequence'], 1, 2**53 - 1)
            or catalogue['channel'] != channel or channel not in {'stable', 'development'}):
        raise ManagementError('Unsupported release catalogue or channel')
    if schema == 1:
        try:
            expires = datetime.strptime(catalogue['expires'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            raise ManagementError('Invalid release expiry') from None
        if expires <= (now or datetime.now(timezone.utc)):
            raise ManagementError('Release approval expired; publishing metadata must be refreshed')
    packages = catalogue['packages']
    if not isinstance(packages, list) or not 1 <= len(packages) <= 64:
        raise ManagementError('Invalid catalogue package list')
    seen = set()
    for package in packages:
        validate_package(package)
        if schema == 2:
            filename = package['id'] + '-' + package['version'] + '.zip'
            urls = package['urls']
            if len(urls) != 2:
                raise ManagementError('SHA-256 releases require both publishing locations')
            github = urlsplit(https_url(urls[0], {'github.com'}))
            website = urlsplit(https_url(urls[1], WEBSITE_HOSTS))
            if (github.query or website.query
                    or not re.fullmatch(r'/[^/]+/[^/]+/releases/download/[^/]+/' + re.escape(filename), github.path)
                    or website.path != f"/api/pyxaseco/updates/files/{channel}/{package['version']}/{filename}"):
                raise ManagementError('Invalid versioned release asset URLs')
        if package['id'] in seen:
            raise ManagementError('Duplicate package identity')
        seen.add(package['id'])
    return catalogue, revision(payload)


def compatibility(package, controller_version, python_version):
    reasons = []
    for label, current, bounds in (('Python', python_version, package['python']),
                                   ('controller', controller_version, package['controller'])):
        if not version(bounds['min']) <= version(current) < version(bounds['max_exclusive']):
            reasons.append(f"Requires {label} {bounds['min']} to below {bounds['max_exclusive']}")
    return reasons


def archive_inventory(blob, package):
    if not 1 <= len(blob) <= PACKAGE_LIMIT:
        raise ManagementError('Release ZIP exceeds the download limit')
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            entries = archive.infolist()
            files = [item for item in entries if not item.is_dir()]
            names = {item.filename for item in files}
            if (len(entries) > 8192 or len(names) != len(files) or len(names) > 4096
                    or any(len(item.filename) > 512 or item.orig_filename != item.filename for item in entries)
                    or len({item.filename.casefold() for item in entries}) != len(entries)):
                raise ManagementError('ZIP contains duplicate paths or too many entries')
            parents = {name.rsplit('/', depth)[0] + '/' for name in names
                       for depth in range(1, name.count('/') + 1)}
            if sum(item.file_size for item in files) > EXPANDED_LIMIT:
                raise ManagementError('Package exceeds expanded size limit')
            result = {}
            for item in entries:
                mode = stat.S_IFMT(item.external_attr >> 16)
                if item.is_dir():
                    if (item.filename not in parents or mode not in (0, stat.S_IFDIR)
                            or item.file_size or item.flag_bits & 1):
                        raise ManagementError('ZIP contains an unexpected directory')
                    continue
                package_path(item.filename, package)
                if (mode not in (0, stat.S_IFREG) or item.flag_bits & 1 or item.file_size > FILE_LIMIT
                        or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ManagementError('ZIP contains a non-regular, encrypted or oversized file')
                result[item.filename] = {'sha256': revision(archive.read(item)), 'size': item.file_size}
            return result
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, ValueError, zlib.error) as exc:
        if isinstance(exc, ManagementError):
            raise
        raise ManagementError('Invalid release ZIP') from exc


def validate_archive(blob, package):
    validate_package(package)
    if len(blob) != package['size'] or revision(blob) != package['sha256']:
        raise ManagementError('Package download size/checksum differs from the approved release')
    if archive_inventory(blob, package) != package['files']:
        raise ManagementError('ZIP inventory or file checksum differs from the approved package inventory')
