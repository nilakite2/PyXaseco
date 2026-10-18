"""TMX preparation workers and ordered, confirmed command completions."""

from __future__ import annotations

import asyncio
import json
import pathlib
import random
import re
import urllib.parse
from dataclasses import dataclass

import aiohttp

from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
from pyxaseco.core.http_sessions import HttpPolicy
from pyxaseco.core.file_io import file_io


SUMMARY_FIELDS = 'TrackId,TrackName,UId,Authors,Environment,Style,AuthorTime'
MAX_JSON_BYTES = 1024 * 1024
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
TMX_JOB_POLICY = JobPolicy(capacity=8, workers=1, deadline_seconds=45)
TMX_HTTP_POLICY = HttpPolicy(connections=2, connect_seconds=5, read_seconds=10, total_seconds=20)


async def ordered_commit(operation):
    """Do not abandon an accepted map halfway through commit or rollback."""
    task = asyncio.create_task(operation)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


@dataclass(frozen=True, slots=True)
class PreparedTrack:
    path: pathlib.Path | None
    tracks_root: pathlib.Path
    download_dir: str
    host: str
    track_id: int
    section: str
    metadata: dict
    existing: dict | None = None


class TmxTransport:
    def __init__(self, aseco):
        self.aseco = aseco
        self._prepare_lock = asyncio.Lock()

    def session(self):
        return self.aseco.jobs.http.get('tmx_downloads', TMX_HTTP_POLICY)

    async def summary(self, section: str, track_id: int, routes: dict) -> dict | None:
        from . import backend as b
        url = routes[section]['api'] + '&' + urllib.parse.urlencode({'id': int(track_id)})
        async with self.session().get(url, timeout=aiohttp.ClientTimeout(total=5),
                                      headers={'User-Agent': 'PyXaseco/1.3'}) as response:
            if response.status == 404:
                return None
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.content.iter_chunked(65536):
                size += len(chunk)
                if size > MAX_JSON_BYTES:
                    raise ValueError('TMX metadata exceeds the response limit')
                chunks.append(chunk)
        data = json.loads(b''.join(chunks))
        if not isinstance(data, dict) or not isinstance(data.get('Results'), list):
            raise ValueError('Invalid TMX metadata response')
        rows = data['Results']
        if not rows:
            return None
        if not isinstance(rows[0], dict):
            raise ValueError('Invalid TMX metadata row')
        row = rows[0]
        if int(row.get('TrackId', 0) or 0) != track_id:
            raise ValueError('TMX API returned a different track ID')
        result = b._normalise_tmx_track_row(row, section)
        if result is not None:
            result['uid'] = str(row.get('UId', '') or '').strip()
            result['author_time'] = int(row.get('AuthorTime', 0) or 0)
        return result

    async def random_reference(self, section: str, routes: dict) -> int:
        async with self.session().get(f"https://{routes[section]['public']}/trackrandom",
                                      timeout=aiohttp.ClientTimeout(total=5),
                                      max_redirects=5, headers={'User-Agent': 'PyXaseco/1.3'}) as response:
            response.raise_for_status()
            url = str(response.url)
        match = re.search(r'/trackshow/(\d+)', urllib.parse.urlparse(url).path, re.IGNORECASE)
        if match is not None:
            return int(match.group(1))
        values = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        for key in ('id', 'trackid'):
            if values.get(key, [''])[0].isdigit():
                return int(values[key][0])
        raise ValueError('TMX random endpoint did not resolve a track ID')

    async def prepare(self, payload: dict, request_id: str) -> PreparedTrack:
        async with self._prepare_lock:
            if payload['kind'] == 'random':
                sections = list(payload['sections'])
                random.shuffle(sections)
                ignored = {str(item).casefold() for item in payload['ignored_styles']}
                for attempt in range(max(6, len(sections) * 6)):
                    section = sections[attempt % len(sections)]
                    try:
                        track_id = await self.random_reference(section, payload['routes'])
                        summary = await self.summary(section, track_id, payload['routes'])
                    except (aiohttp.ClientError, TimeoutError, ValueError):
                        continue
                    if not summary:
                        continue
                    if str(summary.get('style', '')).casefold() in ignored:
                        continue
                    limit = int(payload['max_author_time_seconds'])
                    author = int(summary.get('author_time', 0) or 0)
                    if limit > 0 and (author <= 0 or author > limit * 1000):
                        continue
                    uid = str(summary.get('uid', ''))
                    if uid in payload['queued_uids']:
                        continue
                    if uid and uid in payload['live_uids']:
                        return PreparedTrack(None, pathlib.Path(payload['tracks_root']),
                                             payload['download_dir'], payload['routes'][section]['public'],
                                             track_id, section, summary, {'UId': uid})
                    return await self._download(payload, request_id, section, track_id, summary)
                raise ValueError('No eligible random TMX map within the attempt limit')
            section, track_id = payload['section'], int(payload['track_id'])
            try:
                summary = await self.summary(section, track_id, payload['routes'])
            except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError):
                # Explicit adds historically work without API enrichment.
                # Wrong IDs/oversized responses and available-API UID conflicts
                # remain hard failures; random selection still needs metadata.
                summary = None
            return await self._download(payload, request_id, section, track_id, summary)

    async def _download(self, payload, request_id, section, track_id, summary):
        from . import backend as b
        root = pathlib.Path(payload['tracks_root']).resolve()
        directory = (root / payload['download_dir']).resolve()
        if not directory.is_relative_to(root) or directory == root:
            raise ValueError('TMX download directory must stay inside the tracks root')
        # A request-owned .part file cannot be mistaken for a live challenge.
        path = directory / f'.pyxaseco_{request_id}.part'
        handle = None
        created = False
        host = payload['routes'][section]['public']
        try:
            await file_io(directory.mkdir, parents=True, exist_ok=True)
            # Opening a local file does not perform network I/O. Keep ownership
            # in this task so cancellation cannot strand an executor-open handle.
            handle = path.open('xb')
            created = True
            async with self.session().get(f'https://{host}/trackgbx/{track_id}',
                                          headers={'Accept-Encoding': 'identity', 'User-Agent': 'PyXaseco/1.3'},
                                          auto_decompress=False) as response:
                response.raise_for_status()
                length = response.content_length
                if length is not None and length > MAX_DOWNLOAD_BYTES:
                    raise ValueError('TMX download exceeds 64 MiB')
                written = 0
                async for chunk in response.content.iter_chunked(65536):
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise ValueError('TMX download exceeds 64 MiB')
                    await file_io(handle.write, chunk)
                if length is not None and length != written:
                    raise ValueError('Incomplete TMX download')
            await file_io(handle.close)
            handle = None
            def metadata_from_file():
                with path.open('rb') as stream:
                    if stream.read(3) != b'GBX':
                        raise ValueError('TMX download is not a GBX file')
                return b._parse_gbx_metadata(path)
            metadata = await file_io(metadata_from_file)
            uid = str(metadata.get('uid', '') or '').strip()
            if not uid:
                raise ValueError('TMX download has no readable UID')
            api_uid = str((summary or {}).get('uid', '') or '')
            if api_uid and uid != api_uid:
                raise ValueError('TMX download/API UID mismatch')
            for field in ('name', 'author', 'environment'):
                metadata[field] = metadata.get(field) or (summary or {}).get(field, '')
            metadata['uid'] = uid
            return PreparedTrack(path, root, payload['download_dir'], host, track_id, section, metadata)
        except BaseException:
            try:
                if handle is not None:
                    await file_io(handle.close)
            finally:
                if created:
                    await file_io(path.unlink, missing_ok=True)
            raise

    async def promote(self, track: PreparedTrack) -> tuple:
        from . import backend as b
        if track.path is None:
            raise ValueError('existing tracks do not need file promotion')
        wanted = track.tracks_root / track.download_dir / b._safe_track_filename(
            track.metadata.get('name') or f'Track {track.track_id}', track.track_id, track.host,
        )
        async def cancelled(result):
            path, created = result
            if created:
                await file_io(path.unlink, missing_ok=True)
        path, created = await file_io(b._select_download_path, track.path, wanted,
                                      cancel_cleanup=cancelled)
        metadata = dict(track.metadata, _download_created_file=created)
        rel = str(path.relative_to(track.tracks_root)).replace('\\', '/')
        return path, rel, track.host, track.track_id, metadata

    async def discard(self, track: PreparedTrack | None) -> None:
        if track is not None and track.path is not None:
            await file_io(track.path.unlink, missing_ok=True)


class TmxJobs:
    def __init__(self, aseco):
        self.aseco = aseco
        self.transport = TmxTransport(aseco)
        self.service = aseco.jobs.service('tmx_downloads', TMX_JOB_POLICY)
        self._commit_lock = asyncio.Lock()

    def routes(self):
        from . import backend as b
        service = b._tmx_service(self.aseco)
        if service is None:
            raise RuntimeError('TMX service is unavailable')
        return {section: {
            'public': service.tmx_public_host_for_section(section),
            'api': b._tmx_api_url(section, 'tracks', fields=SUMMARY_FIELDS),
        } for section in b.TMX_SECTION_CHOICES}

    def payload(self):
        from . import backend as b
        root = pathlib.Path(getattr(self.aseco.settings, 'tracks_root',
                                   self.aseco._base_dir.parent / 'GameData' / 'Tracks' / 'Challenges')).resolve()
        return {'tracks_root': str(root), 'download_dir': b.TMX_DOWNLOAD_DIR,
                'routes': self.routes()}

    async def request(self, *, login, nickname, complete, ref='', section='', random_filters=None,
                      vote=False, require_feature_flags=True, current_map=False,
                      guard=None, discarded=None, acknowledge=True, persist=False) -> Admission:
        from . import backend as b
        if 'jukebox' not in self.aseco.active_apps:
            raise RuntimeError('The Jukebox app is disabled.')
        payload = self.payload()
        requester = self.aseco.server.players.get_player(login) if login else None
        if random_filters is not None:
            sections = b._normalise_tmx_sections(random_filters['sections'])
            from pyxaseco.core.playlist import playlist
            tracks = await playlist(self.aseco).snapshot()
            payload.update(kind='random', sections=sections,
                           ignored_styles=list(random_filters['ignored_styles']),
                           max_author_time_seconds=int(random_filters['max_author_time_seconds']),
                           queued_uids=list(b.jukebox), live_uids=[
                               str(track.get('UId', '') or track.get('Uid', ''))
                               for track in tracks if isinstance(track, dict)
                           ])
            key = 'random'
        else:
            if not section:
                section = await b._default_tmx_section(self.aseco)
            host, track_id = b.parse_tmx_reference(ref, section)
            section = b._tmx_section_for_public_host(host)
            payload.update(kind='add', section=section, track_id=track_id)
            key = f'{section}:{track_id}:{vote}'
        key += f':{persist}:{id(requester)}'
        live_uids = tuple(payload.pop('live_uids', ()))
        job = JobEnvelope.capture(self.aseco.capture_job_context(login=login, nickname=nickname), payload)

        async def operation(envelope):
            captured = envelope.payload()
            if captured['kind'] == 'random':
                captured['live_uids'] = list(live_uids)
            return await self.transport.prepare(captured, envelope.request_id)

        async def discard(result):
            await self.transport.discard(result.value)
            if discarded is not None:
                await discarded()
            elif (self.aseco.jobs.running and not self.aseco._shutdown_requested
                  and (requester is None or self.aseco.server.players.get_player(login) is requester)):
                await b._reply(self.aseco, login, '{#server}> {#error}Pending TMX request cancelled after context changed.')

        async def commit(prepared):
            try:
                async with self._commit_lock:
                    if guard is not None and not await guard():
                        if discarded is not None:
                            await discarded()
                        return
                    if ('jukebox' not in self.aseco.active_apps or
                            (require_feature_flags and not (b.feature_jukebox and b.feature_tmxadd))):
                        await complete(False, 'TMX adds are currently disabled.')
                        return
                    if vote:
                        await complete(True, prepared)
                        return
                    if prepared.existing is not None:
                        live = await b._find_server_track_by_uid_or_filename(
                            self.aseco, prepared.metadata.get('uid', ''), prepared.existing.get('FileName', ''),
                        )
                        if live is None:
                            await complete(False, 'The selected live map was removed while preparing; retry /tmxr.')
                            return
                        ok, info = await b._queue_server_track(self.aseco, server_track=live,
                                                             login=login, nick=nickname)
                    else:
                        try:
                            promoted = await self.transport.promote(prepared)
                        except (OSError, ValueError) as error:
                            await complete(False, f'TMX file promotion failed ({type(error).__name__}).')
                            return
                        ok, info = await b.admin_add_tmx_track(self.aseco, str(prepared.track_id), login,
                                                             prepared.section, use_add_challenge=True,
                                                             prepared=promoted, requester_nick=nickname,
                                                             persist=persist)
                    if random_filters is not None and ok:
                        info = {'name': info, 'section': prepared.section, 'uid': prepared.metadata.get('uid', '')}
                    await complete(ok, info)
            finally:
                await self.transport.discard(prepared)

        async def apply(result):
            if result.status != 'completed':
                await complete(False, f'TMX preparation failed ({result.error_type}).')
                return
            await ordered_commit(commit(result.value))

        outcome = self.service.submit(job, operation, apply, dedupe_key=key,
                                      current_map=vote or current_map, discard=discard)
        message = {
            Admission.ACCEPTED: '{#server}> {#message}TMX request queued; preparing the map.',
            Admission.DUPLICATE: '{#server}> {#message}This TMX request is already pending.',
            Admission.FULL: '{#server}> {#error}TMX queue is full; try again later.',
            Admission.STOPPED: '{#server}> {#error}TMX preparation is stopping; try again after restart.',
            Admission.COOLDOWN: '{#server}> {#error}TMX service is cooling down after failures; try again later.',
        }[outcome]
        if acknowledge and login:
            await b._reply(self.aseco, login, message)
        return outcome


def get_tmx_jobs(aseco) -> TmxJobs:
    service = aseco.services.get('tmx_jobs')
    if service is None:
        service = TmxJobs(aseco)
        aseco.services.register('tmx_jobs', service, owner='jukebox')
    return service
