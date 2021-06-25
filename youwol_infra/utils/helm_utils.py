import asyncio
import os
from pathlib import Path
from typing import NamedTuple, Optional

from youwol_infra.context import Context
from youwol_infra.utils.utils import exec_command


class Selector(NamedTuple):
    name: Optional[str]


class Resource(NamedTuple):
    name: str
    namespace: str
    revision: str
    updated: str
    status: str
    chart: str
    app_version: str


async def helm_list(namespace: str = None, selector: Selector = None):
    cmd = "helm list"
    if namespace:
        cmd += f" --namespace {namespace}"
    if selector and selector.name:
        cmd += f" --selector name={selector.name}"

    outputs, errors = await exec_command(cmd) # output = os.popen(cmd).read()

    def to_resource(line):
        elements = line.split("\t")
        return Resource(
            name=elements[0].strip(),
            namespace=elements[1].strip(),
            revision=elements[2].strip(),
            updated=elements[3].strip(),
            status=elements[4].strip(),
            chart=elements[5].strip(),
            app_version=elements[6]
            )
    return [to_resource(line) for line in outputs[1:] if line]


async def helm_install(release_name: str, namespace: str, values_file: Path, chart_folder: Path,
                       timeout=120, args="", context: Context = None):
    cmd = f"helm install {release_name} --create-namespace --namespace {namespace} --values {str(values_file)} " +\
          f"--atomic --timeout {timeout}s {str(chart_folder)} {args}"
    context and await context.info(text=cmd)

    await exec_command(cmd, context)


async def helm_upgrade(release_name: str, namespace: str, values_file: Path, chart_folder: Path, timeout=120, args="",
                       context: Context = None):
    cmd = f"helm upgrade {release_name} --namespace {namespace} --values {str(values_file)} " +\
          f"--atomic --timeout {timeout}s {str(chart_folder)}  {args}"

    context and await context.info(text=cmd)

    await exec_command(cmd, context)


async def helm_install_or_upgrade(release_name: str, namespace: str, values_file: Path, chart_folder: Path, timeout=120):

    if release_name in [r.name for r in helm_list(namespace=namespace)]:
        await helm_upgrade(release_name, namespace, values_file, chart_folder, timeout)
    else:
        await helm_install(release_name, namespace, values_file, chart_folder, timeout)


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
