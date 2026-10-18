"""Joined local disk operations. Never put network I/O on this executor."""

import asyncio


async def file_io(operation, *args, cancel_cleanup=None, **kwargs):
    future = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    cancelled = False
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            cancelled = True
    result = future.result()
    if cancelled:
        if cancel_cleanup is not None:
            await cancel_cleanup(result)
        raise asyncio.CancelledError
    return result
