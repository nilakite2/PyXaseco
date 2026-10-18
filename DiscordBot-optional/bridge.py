from __future__ import annotations

import socket
import struct
import xml.etree.ElementTree as ET

if __package__:
    from .config import BotInstance
else:
    from config import BotInstance

_GBX_REQ_ID = 0x80000000


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _xml_val(v):
    if v is None:
        return "<nil/>"
    if isinstance(v, bool):
        return f"<boolean>{1 if v else 0}</boolean>"
    if isinstance(v, int):
        return f"<int>{v}</int>"
    if isinstance(v, float):
        return f"<double>{v}</double>"
    if isinstance(v, (list, tuple)):
        inner = "".join(f"<value>{_xml_val(x)}</value>" for x in v)
        return f"<array><data>{inner}</data></array>"
    if isinstance(v, dict):
        items = "".join(
            f"<member><name>{k}</name><value>{_xml_val(val)}</value></member>"
            for k, val in v.items()
        )
        return f"<struct>{items}</struct>"
    return f"<string>{_xml_escape(str(v))}</string>"


def _xml_build_call(method: str, params: list) -> bytes:
    params_xml = "".join(f"<param><value>{_xml_val(p)}</value></param>" for p in (params or []))
    xml = f"""<?xml version="1.0"?>
<methodCall>
  <methodName>{method}</methodName>
  <params>{params_xml}</params>
</methodCall>"""
    return xml.encode("utf-8")


def _xml_parse_value(val_el: ET.Element):
    if len(list(val_el)) == 0 and val_el.text is not None:
        return val_el.text
    child = next(iter(val_el), None)
    if child is None:
        return None
    tag = child.tag.lower()
    tx = child.text or ""
    if tag.endswith("i4") or tag.endswith("int"):
        return int(tx or "0")
    if tag.endswith("boolean"):
        return tx.strip() in ("1", "true", "True")
    if tag.endswith("double"):
        return float(tx or "0")
    if tag.endswith("string"):
        return tx
    if tag.endswith("array"):
        data = child.find(".//data")
        out = []
        if data is not None:
            for v in data.findall("value"):
                out.append(_xml_parse_value(v))
        return out
    if tag.endswith("struct"):
        out = {}
        for m in child.findall("member"):
            name_el = m.find("name")
            ve = m.find("value")
            if name_el is not None and ve is not None:
                out[name_el.text or ""] = _xml_parse_value(ve)
        return out
    return tx


def _xml_parse_response(body: bytes):
    root = ET.fromstring(body)
    fault = root.find(".//fault")
    if fault is not None:
        val = fault.find("value")
        data = _xml_parse_value(val) if val is not None else None
        if isinstance(data, dict):
            code = data.get("faultCode", -1)
            string = data.get("faultString", "Fault")
        else:
            code = -1
            string = str(data)
        raise RuntimeError(f"XML-RPC fault [{code}]: {string}")
    val = root.find(".//params/param/value")
    return _xml_parse_value(val) if val is not None else None


def _gbx_recvn(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("Socket closed while reading")
        buf += chunk
    return buf


def _gbx_expect_handshake(sock: socket.socket, *, timeout: float = 3.0) -> None:
    sock.settimeout(timeout)
    buf = b""
    try:
        while True:
            chunk = sock.recv(32)
            if not chunk:
                break
            buf += chunk
            if b"GBXRemote 2" in buf or len(buf) > 64:
                return
    except socket.timeout:
        return


def gbx_call_sequence(instance: BotInstance, calls: list[tuple[str, list]], timeout: float = 5.0) -> list:
    global _GBX_REQ_ID
    results: list = []
    with socket.create_connection((instance.xmlrpc_host, instance.xmlrpc_port), timeout=timeout) as s:
        s.settimeout(timeout)
        try:
            _gbx_expect_handshake(s)
        except Exception:
            pass

        for method, params in calls:
            xml_bytes = _xml_build_call(method, params or [])
            _GBX_REQ_ID = (_GBX_REQ_ID + 1) & 0xFFFFFFFF
            header = struct.pack("<II", len(xml_bytes), _GBX_REQ_ID)
            s.sendall(header + xml_bytes)
            hdr = _gbx_recvn(s, 8)
            resp_len, _resp_id = struct.unpack("<II", hdr)
            body = _gbx_recvn(s, resp_len)
            results.append(_xml_parse_response(body))
    return results


def send_chat_to_instance(instance: BotInstance, message: str) -> None:
    msg = str(message or "").strip()
    if not msg:
        raise RuntimeError("Empty message")

    res = gbx_call_sequence(
        instance,
        [
            ("Authenticate", [instance.xmlrpc_login, instance.xmlrpc_password]),
            ("ChatSend", [msg]),
        ],
        timeout=5.0,
    )
    if not isinstance(res, list) or len(res) < 2:
        raise RuntimeError("Malformed GBX response")
    if not res[0]:
        raise RuntimeError("Authenticate returned falsy")
    if not res[1]:
        raise RuntimeError("ChatSend returned falsy")
