"""
GbxRemote 2 async client for TrackMania Forever.

Faithful port of GbxRemote.inc.php (IXR_Client_Gbx / IXR_ClientMulticall_Gbx)
to Python asyncio.

Protocol:
  - After TCP connect, server sends: uint32 size + 'GBXRemote 2'
  - Every outgoing request:   uint32 xml_len + uint32 handle + xml_bytes
  - Every incoming packet:    uint32 xml_len + uint32 handle + xml_bytes
    - If handle MSB is set   (handle & 0x80000000): it is a RESPONSE to our call
    - If handle MSB is clear (handle & 0x80000000 == 0): it is a SERVER CALLBACK
"""

import asyncio
import struct
import xml.etree.ElementTree as ET
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)

# Maximum allowed packet size (4 MB, same as PHP original)
MAX_PACKET_SIZE = 4 * 1024 * 1024
# Maximum outgoing request size (512 KB - 8 bytes header)
MAX_REQUEST_SIZE = 512 * 1024 - 8

# First request handle value (matches PHP: 0x80000000)
HANDLE_ORIGIN = 0x80000000


# ---------------------------------------------------------------------------
# XML-RPC value serialiser
# ---------------------------------------------------------------------------

def _py_to_xmlrpc(value: Any) -> str:
    """Recursively convert a Python value to an XML-RPC <value> element string."""
    if isinstance(value, bool):
        return f'<value><boolean>{"1" if value else "0"}</boolean></value>'
    if isinstance(value, int):
        return f'<value><int>{value}</int></value>'
    if isinstance(value, float):
        return f'<value><double>{value}</double></value>'
    if isinstance(value, (bytes, bytearray)):
        import base64
        return f'<value><base64>{base64.b64encode(value).decode()}</base64></value>'
    if isinstance(value, str):
        escaped = (value
                   .replace('&', '&amp;')
                   .replace('<', '&lt;')
                   .replace('>', '&gt;')
                   .replace('"', '&quot;')
                   .replace("'", '&apos;'))
        return f'<value><string>{escaped}</string></value>'
    if isinstance(value, dict):
        members = ''
        for k, v in value.items():
            members += f'<member><name>{k}</name>{_py_to_xmlrpc(v)}</member>\n'
        return f'<value><struct>{members}</struct></value>'
    if isinstance(value, (list, tuple)):
        items = ''.join(f'{_py_to_xmlrpc(v)}' for v in value)
        return f'<value><array><data>{items}</data></array></value>'
    # fallback: stringify
    return f'<value><string>{str(value)}</string></value>'


def _build_request_xml(method: str, args: list) -> str:
    """Build a full XML-RPC methodCall document."""
    params = ''.join(f'<param>{_py_to_xmlrpc(a)}</param>' for a in args)
    return (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<methodCall><methodName>{method}</methodName>'
            f'<params>{params}</params></methodCall>')


# ---------------------------------------------------------------------------
# XML-RPC response parser
# ---------------------------------------------------------------------------

def _parse_value(elem: ET.Element) -> Any:
    """Parse a single <value> element into a Python object."""
    # If <value> has no child elements, its text content is a bare string
    child = list(elem)
    if not child:
        return (elem.text or '').strip()

    tag = child[0].tag
    text = (child[0].text or '').strip()

    if tag in ('int', 'i4'):
        return int(text)
    if tag == 'double':
        return float(text)
    if tag == 'boolean':
        return text == '1'
    if tag == 'string':
        return child[0].text or ''
    if tag == 'base64':
        import base64
        return base64.b64decode(text)
    if tag == 'dateTime.iso8601':
        return text  # return raw ISO string; plugins can parse further
    if tag == 'array':
        data_elem = child[0].find('data')
        if data_elem is None:
            return []
        return [_parse_value(v) for v in data_elem.findall('value')]
    if tag == 'struct':
        result = {}
        for member in child[0].findall('member'):
            name_elem = member.find('name')
            val_elem = member.find('value')
            if name_elem is not None and val_elem is not None:
                result[name_elem.text or ''] = _parse_value(val_elem)
        return result
    return text  # unknown tag → bare text


def _parse_response(xml_bytes: bytes) -> tuple[str, list]:
    """
    Parse a raw XML-RPC packet.

    Returns:
        (message_type, params)
        message_type: 'methodResponse' | 'fault' | 'methodCall'
        params: list of decoded Python values, or for callbacks a dict
                {'method': name, 'params': [...]}
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise ValueError(f'XML parse error: {e}')

    tag = root.tag

    if tag == 'methodCall':
        # Incoming callback from server
        method_name_elem = root.find('methodName')
        method_name = method_name_elem.text if method_name_elem is not None else ''
        params_elem = root.find('params')
        params = []
        if params_elem is not None:
            for p in params_elem.findall('param'):
                v = p.find('value')
                if v is not None:
                    params.append(_parse_value(v))
        return 'methodCall', [{'method': method_name, 'params': params}]

    if tag == 'methodResponse':
        fault = root.find('fault')
        if fault is not None:
            val = fault.find('value')
            fault_data = _parse_value(val) if val is not None else {}
            return 'fault', [fault_data]
        params_elem = root.find('params')
        params = []
        if params_elem is not None:
            for p in params_elem.findall('param'):
                v = p.find('value')
                if v is not None:
                    params.append(_parse_value(v))
        return 'methodResponse', params

    raise ValueError(f'Unexpected root tag: {tag}')


# ---------------------------------------------------------------------------
# GbxError
# ---------------------------------------------------------------------------

class GbxError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self):
        return f'[{self.code}] {self.message}'


# ---------------------------------------------------------------------------
# Main async client
# ---------------------------------------------------------------------------

class GbxClient:
    """
    Async GbxRemote 2 client.

    Usage:
        client = GbxClient()
        await client.connect('127.0.0.1', 5000)
        await client.authenticate('SuperAdmin', 'SuperAdmin')

        # Call a method and get the result:
        result = await client.query('GetVersion')

        # Fire-and-forget (no result read):
        await client.query_ignore_result('ChatSendServerMessage', 'Hello!')

        # Read pending callbacks (non-blocking):
        callbacks = client.get_cb_responses()
    """

    def __init__(self):
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._handle: int = HANDLE_ORIGIN
        self._pending: dict[int, asyncio.Future] = {}  # handle → Future(result)
        self._cb_queue: list[tuple[str, list]] = []    # buffered server callbacks
        self._read_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()                    # serialise sends

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self, host: str, port: int, timeout: float = 10.0):
        """Open TCP connection and perform GbxRemote handshake."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout
            )
        except (asyncio.TimeoutError, OSError) as e:
            raise GbxError(-32300, f'transport error - could not connect: {e}')

        # --- handshake: read uint32 size + protocol string ---
        header_size_bytes = await self._read_exactly(4)
        (size,) = struct.unpack_from('<I', header_size_bytes)
        if size > 64:
            raise GbxError(-32300, 'transport error - wrong lowlevel protocol header')
        handshake = (await self._read_exactly(size)).decode('utf-8', errors='replace')
        if handshake != 'GBXRemote 2':
            raise GbxError(-32300,
                f'transport error - unsupported protocol: "{handshake}" '
                '(only GBXRemote 2 is supported)')

        logger.info('GbxRemote handshake OK: %s', handshake)

        # Start the background reader
        self._read_task = asyncio.ensure_future(self._reader_loop())

    async def disconnect(self):
        """Close the connection cleanly."""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None
        logger.info('GbxClient disconnected')

    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    # ------------------------------------------------------------------
    # Authentication helper
    # ------------------------------------------------------------------

    async def authenticate(self, login: str, password: str):
        """Call Authenticate on the dedicated server."""
        result = await self.query('Authenticate', login, password)
        if result is not True:
            raise GbxError(-32300, f'Authentication failed (result={result!r})')
        logger.info('Authenticated as %s', login)

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    async def query(self, method: str, *args) -> Any:
        """
        Send an XML-RPC call and await the result.
        Raises GbxError on fault or transport error.
        """
        xml = _build_request_xml(method, list(args))
        xml_bytes = xml.encode('utf-8')
        if len(xml_bytes) > MAX_REQUEST_SIZE:
            raise GbxError(-32300, f'transport error - request too large ({len(xml_bytes)})')

        async with self._lock:
            handle = self._next_handle()
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending[handle] = fut
            try:
                await self._send_packet(xml_bytes, handle)
            except Exception as e:
                del self._pending[handle]
                raise GbxError(-32300, f'transport error - send failed: {e}')

        # Wait for the background reader to deliver our result
        try:
            result = await asyncio.wait_for(fut, timeout=20.0)
        except asyncio.TimeoutError:
            self._pending.pop(handle, None)
            raise GbxError(-32300, f'transport error - timeout waiting for response to {method}')
        return result

    async def query_ignore_result(self, method: str, *args) -> bool:
        """
        Send an XML-RPC call without waiting for the result.
        For system.multicall with oversized payload, splits into two calls.
        """
        xml = _build_request_xml(method, list(args))
        xml_bytes = xml.encode('utf-8')

        if len(xml_bytes) > MAX_REQUEST_SIZE:
            if method == 'system.multicall' and args:
                calls = list(args[0])
                count = len(calls)
                if count < 2:
                    raise GbxError(-32300, f'transport error - request too large ({len(xml_bytes)})')
                mid = count // 2
                r1 = await self.query_ignore_result('system.multicall', calls[:mid])
                r2 = await self.query_ignore_result('system.multicall', calls[mid:])
                return r1 and r2
            raise GbxError(-32300, f'transport error - request too large ({len(xml_bytes)})')

        async with self._lock:
            handle = self._next_handle()
            # We don't register a future — we don't care about the response.
            # The background reader will see the response, find no pending future,
            # and silently discard it.
            try:
                await self._send_packet(xml_bytes, handle)
            except Exception as e:
                raise GbxError(-32300, f'transport error - send failed: {e}')
        return True

    # ------------------------------------------------------------------
    # Multicall helper
    # ------------------------------------------------------------------

    def build_multicall(self) -> 'Multicall':
        """Return a Multicall builder for system.multicall."""
        return Multicall(self)

    # ------------------------------------------------------------------
    # Callback retrieval
    # ------------------------------------------------------------------

    def get_cb_responses(self) -> list[tuple[str, list]]:
        """
        Return and clear all buffered server callbacks.
        Each entry is (method_name, params_list).
        """
        cbs = self._cb_queue[:]
        self._cb_queue.clear()
        return cbs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_handle(self) -> int:
        self._handle += 1
        # Keep within uint32; keep MSB set so it's always a response handle
        if self._handle >= 0xFFFFFFFF:
            self._handle = HANDLE_ORIGIN + 1
        return self._handle

    async def _send_packet(self, xml_bytes: bytes, handle: int):
        """Send: uint32 len + uint32 handle + xml_bytes (little-endian)."""
        header = struct.pack('<II', len(xml_bytes), handle)
        self._writer.write(header + xml_bytes)
        await self._writer.drain()

    async def _read_exactly(self, n: int) -> bytes:
        """Read exactly n bytes from the server, raising on EOF."""
        data = await self._reader.readexactly(n)
        return data

    async def _reader_loop(self):
        """
        Background coroutine that continuously reads packets from the server.
        Routes them to waiting futures (responses) or the callback queue.
        """
        try:
            while True:
                # Read 8-byte header: uint32 size + uint32 handle
                header = await self._read_exactly(8)
                size, handle = struct.unpack_from('<II', header)

                # amd64 sign-extension fix (mirrors PHP original)
                # On 64-bit PHP the handle could come back sign-extended;
                # we mask to uint32 range.
                handle = handle & 0xFFFFFFFF

                if handle == 0 or size == 0:
                    logger.error('GbxRemote: connection interrupted (zero handle/size)')
                    break
                if size > MAX_PACKET_SIZE:
                    logger.error('GbxRemote: packet too large (%d), dropping', size)
                    break

                xml_bytes = await self._read_exactly(size)

                is_response = bool(handle & 0x80000000)

                if is_response:
                    # This is a response to one of our queries
                    fut = self._pending.pop(handle, None)
                    try:
                        msg_type, params = _parse_response(xml_bytes)
                    except ValueError as e:
                        logger.error('GbxRemote: parse error for response %08x: %s', handle, e)
                        if fut and not fut.done():
                            fut.set_exception(GbxError(-32700, f'parse error: {e}'))
                        continue

                    if fut and not fut.done():
                        if msg_type == 'fault':
                            fault = params[0] if params else {}
                            fut.set_exception(GbxError(
                                fault.get('faultCode', -1),
                                fault.get('faultString', 'unknown fault')
                            ))
                        else:
                            # Return the first param (standard XML-RPC response)
                            fut.set_result(params[0] if params else None)
                    # If fut is None: query_ignore_result — silently drop
                else:
                    # This is a server-initiated callback
                    try:
                        msg_type, params = _parse_response(xml_bytes)
                        if msg_type == 'methodCall' and params:
                            cb_info = params[0]
                            self._cb_queue.append((cb_info['method'], cb_info['params']))
                    except ValueError as e:
                        logger.warning('GbxRemote: callback parse error: %s', e)

        except asyncio.IncompleteReadError:
            logger.warning('GbxRemote: server closed connection')
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error('GbxRemote: reader loop crashed: %s', e, exc_info=True)
        finally:
            # Unblock any pending futures with an error
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(GbxError(-32300, 'transport error - connection lost'))
            self._pending.clear()


# ---------------------------------------------------------------------------
# Multicall builder (mirrors IXR_ClientMulticall_Gbx)
# ---------------------------------------------------------------------------

class Multicall:
    """
    Builds a system.multicall payload and executes it.

    Usage:
        mc = client.build_multicall()
        mc.add('ChatSendServerMessage', 'Hello')
        mc.add('SetNextChallengeIndex', 3)
        results = await mc.query()      # returns list of results
        await mc.query_ignore_result()  # fire and forget
    """

    def __init__(self, client: GbxClient):
        self._client = client
        self._calls: list[dict] = []

    def add(self, method: str, *args) -> 'Multicall':
        self._calls.append({'methodName': method, 'params': list(args)})
        return self

    async def query(self) -> list:
        calls = self._calls[:]
        self._calls.clear()
        result = await self._client.query('system.multicall', calls)
        # system.multicall returns a list of single-element lists (or fault structs)
        if isinstance(result, list):
            out = []
            for item in result:
                if isinstance(item, list):
                    out.append(item[0] if item else None)
                elif isinstance(item, dict) and 'faultCode' in item:
                    out.append(GbxError(item['faultCode'], item.get('faultString', '')))
                else:
                    out.append(item)
            return out
        return []

    async def query_ignore_result(self) -> bool:
        calls = self._calls[:]
        self._calls.clear()
        return await self._client.query_ignore_result('system.multicall', calls)
