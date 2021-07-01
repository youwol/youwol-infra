import asyncio
import functools
import json
from datetime import datetime
from enum import Enum
from pathlib import Path, PosixPath
from typing import Union, Mapping, List, Callable, Any

import aiohttp
from fastapi import HTTPException
from pydantic import BaseModel

from youwol_infra.context import Context


async def decorate_with(it, prefix):
    async for item in it:
        yield prefix, item


async def exec_command(cmd: str, context: Context = None):

    p = await asyncio.create_subprocess_shell(
        cmd=cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        shell=True)

    outputs = []
    errors = []
    async for is_out, f in merge(decorate_with(p.stdout, True),  decorate_with(p.stderr, False)):
        line = f.decode('utf-8')
        if is_out:
            context and await context.info(text=line)
            outputs.append(line)
        else:
            context and await context.error(text=line)
            errors.append(line)

    await p.communicate()
    return outputs, errors


async def merge(*iterables):
    # https://stackoverflow.com/questions/50901182/watch-stdout-and-stderr-of-a-subprocess-simultaneously
    iter_next = {it.__aiter__(): None for it in iterables}
    while iter_next:
        for it, it_next in iter_next.items():
            if it_next is None:
                fut = asyncio.ensure_future(it.__anext__())
                fut._orig_iter = it
                iter_next[it] = fut
        done, _ = await asyncio.wait(iter_next.values(),
                                     return_when=asyncio.FIRST_COMPLETED)
        for fut in done:
            iter_next[fut._orig_iter] = None
            try:
                ret = fut.result()
            except StopAsyncIteration:
                del iter_next[fut._orig_iter]
                continue
            yield ret


JSON = Union[str, int, float, bool, None, Mapping[str, 'JSON'], List['JSON']]


def to_camel_case(key: str):
    components = key.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])


def to_serializable(obj):
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, PosixPath):
        return str(obj)
    if isinstance(obj, Callable):
        return "function"
    if isinstance(obj, Enum):
        return obj.name
    if isinstance(obj, datetime):
        return str(obj)
    if isinstance(obj, dict):
        return obj
    return obj.__dict__


def to_json_response(obj: Union[BaseModel, dict]) -> JSON:

    a = json.dumps(to_serializable(obj), default=lambda o: to_serializable(o))
    b = json.loads(a)

    def to_json_rec(_obj: Any):
        result = {}
        if isinstance(_obj, dict):
            for k, v in _obj.items():
                result[to_camel_case(k)] = to_json_rec(v)
        elif isinstance(_obj, list):
            result = [to_json_rec(v) for v in _obj]
        else:
            result = _obj

        return result

    return to_json_rec(b)


def parse_json(path: Union[str, Path]):
    return json.loads(open(str(path)).read())


def write_json(data: json, path: Path):
    open(str(path), 'w').write(json.dumps(data, indent=4))


def get_port_number(name: str, ports_range: (int, int)):

    port = functools.reduce(lambda acc, e: acc + ord(e), name, 0)
    # need to check if somebody is already listening
    return ports_range[0] + port % (ports_range[1]-ports_range[0])


def get_aiohttp_session(verify_ssl: bool = False, total_timeout: int = 5):
    return aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(verify_ssl=verify_ssl),
            timeout=aiohttp.ClientTimeout(total=total_timeout)
        )


async def get_client_credentials(
        openid_host,
        client_id: str,
        client_secret: str,
        scope: str):

    form = aiohttp.FormData()
    form.add_field("client_id", client_id)
    form.add_field("client_secret", client_secret)
    form.add_field("grant_type", "client_credentials")
    form.add_field("scope", scope)
    url = f"https://{openid_host}/auth/realms/youwol/protocol/openid-connect/token"
    async with get_aiohttp_session() as session:
        async with await session.post(url=url, data=form) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=resp.status, detail=await resp.read())
            resp = await resp.json()
            return resp['access_token']

