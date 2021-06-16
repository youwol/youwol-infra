import asyncio
from datetime import datetime
from enum import Enum
from pathlib import Path, PosixPath
from typing import Union, Mapping, List, Callable, Any

from pydantic import BaseModel

from youwol_infra.context import Context


async def exec_command(cmd: str, context: Context = None):

    p = await asyncio.create_subprocess_shell(
        cmd=cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        shell=True)

    async for f in merge(p.stdout, p.stderr):
        context and await context.info(text=f.decode('utf-8'))
        # print(f.decode('utf-8'))

    await p.communicate()


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


def to_json_response(obj: BaseModel) -> JSON:

    def to_camel_case(key: str):
        components = key.split('_')
        return components[0] + ''.join(x.title() for x in components[1:])

    def to_serializable(v):
        if isinstance(v, Path):
            return str(v)
        if isinstance(v, PosixPath):
            return str(v)
        if isinstance(v, Callable):
            return "function"
        if isinstance(v, Enum):
            return v.name
        if isinstance(v, datetime):
            return str(v)
        return v

    base = obj.dict()
    target = {}

    def to_json_rec(_obj: Any, target):

        if isinstance(_obj, dict):
            for k, v in _obj.items():
                keyCC = to_camel_case(k)
                if not isinstance(v, dict) and not isinstance(v, list):
                    target[keyCC] = to_serializable(v)
                if isinstance(v, dict):
                    target[keyCC] = {}
                    to_json_rec(v, target[keyCC])
                if isinstance(v, list):
                    target[keyCC] = []
                    for i, e in enumerate(v):
                        if not isinstance(e, dict) and not isinstance(e, list):
                            target[keyCC].append(to_serializable(e))
                        else:
                            child = {}
                            to_json_rec(e, child)
                            target[keyCC].append(child)

    to_json_rec(base, target)
    return target
