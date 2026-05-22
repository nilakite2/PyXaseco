from __future__ import annotations

from typing import Any


def _get_service(aseco, *names: str):
    if aseco is None:
        return None
    for name in names:
        try:
            service = aseco.get_service(name)
        except Exception:
            service = None
        if service is not None:
            return service
    return None


def get_localdb_service(aseco):
    return _get_service(aseco, 'localdb', 'service/localdb', 'core/localdb')


def get_tmx_service(aseco):
    return _get_service(aseco, 'tmx', 'service/tmx')


def get_dedimania_service(aseco):
    return _get_service(aseco, 'dedimania', 'service/dedimania')


def get_dedi_db(aseco) -> dict[str, Any]:
    service = get_dedimania_service(aseco)
    data = getattr(service, 'dedi_db', None) if service is not None else None
    return data if isinstance(data, dict) else {}


def map_country(aseco, nation: str) -> str:
    service = get_localdb_service(aseco)
    impl = getattr(service, 'map_country', None) if service is not None else None
    if callable(impl):
        return impl(nation)
    return nation[:3].upper() if nation else ''


async def localdb_get_pool(aseco):
    service = get_localdb_service(aseco)
    impl = getattr(service, 'get_pool', None) if service is not None else None
    return await impl() if callable(impl) else None


async def localdb_get_player_id(aseco, login: str) -> int:
    service = get_localdb_service(aseco)
    impl = getattr(service, 'get_player_id', None) if service is not None else None
    return int(await impl(login)) if callable(impl) else 0


async def localdb_get_style(aseco, login: str) -> str:
    service = get_localdb_service(aseco)
    impl = getattr(service, 'ldb_get_style', None) if service is not None else None
    return await impl(aseco, login) if callable(impl) else ''


async def localdb_set_style(aseco, login: str, style_name: str):
    service = get_localdb_service(aseco)
    impl = getattr(service, 'ldb_set_style', None) if service is not None else None
    if callable(impl):
        return await impl(aseco, login, style_name)
    return None


async def localdb_get_panels(aseco, login: str):
    service = get_localdb_service(aseco)
    impl = getattr(service, 'ldb_get_panels', None) if service is not None else None
    return await impl(aseco, login) if callable(impl) else {}


async def localdb_get_cps(aseco, login: str):
    service = get_localdb_service(aseco)
    impl = getattr(service, 'ldb_get_cps', None) if service is not None else None
    return await impl(aseco, login) if callable(impl) else {}


async def localdb_set_cps(aseco, login: str, cps: int, dedicps: int):
    service = get_localdb_service(aseco)
    impl = getattr(service, 'ldb_set_cps', None) if service is not None else None
    if callable(impl):
        return await impl(aseco, login, cps, dedicps)
    return None


async def localdb_get_donations(aseco, login: str) -> int:
    service = get_localdb_service(aseco)
    impl = getattr(service, 'ldb_get_donations', None) if service is not None else None
    return int(await impl(aseco, login)) if callable(impl) else 0


async def localdb_update_donations(aseco, login: str, amount: int):
    service = get_localdb_service(aseco)
    impl = getattr(service, 'ldb_update_donations', None) if service is not None else None
    if callable(impl):
        return await impl(aseco, login, amount)
    return None
