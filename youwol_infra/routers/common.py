import os
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Awaitable

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.websockets import WebSocket

from youwol_infra.context import Context
from youwol_infra.dynamic_configuration import DynamicConfiguration, dynamic_config
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore


class Sanity(Enum):
    SANE = "SANE",
    WARNINGS = "WARNINGS",
    BROKEN = "BROKEN",
    PENDING = "PENDING"


class StatusBase(BaseModel):
    installed: bool
    namespace: str
    sanity: Optional[Sanity]
    pending: bool


class HelmValues(BaseModel):
    values: dict


async def install_pack(
        request: Request,
        config: DynamicConfiguration,
        name: str,
        namespace: str,
        helm_values: dict,
        channel_ws: WebSocket,
        finally_action: Callable[[], Awaitable]
        ):

    package = next(p for p in config.deployment_configuration.packages
                   if p.name == name and p.namespace == namespace)

    try:
        context = Context(
            request=request,
            config=config,
            web_socket=WebSocketsStore.logs
            )
        async with context.start(action=f"Install {package.name} in {package.namespace}") as ctx:

            is_installed = await package.is_installed()
            if is_installed:
                ctx.info(text=f"{package.name} already installed")
                return
            resp = StatusBase(
                installed=is_installed,
                namespace=namespace,
                sanity=Sanity.SANE if is_installed else None,
                pending=True
                )
            await channel_ws.send_json(to_json_response(resp))
            await package.install(ctx)

    finally:
        await finally_action()


async def upgrade_pack(
        request: Request,
        config: DynamicConfiguration,
        name: str,
        namespace: str,
        helm_values: dict,
        channel_ws: WebSocket,
        finally_action: Callable[[], Awaitable]
        ):

    package = next(p for p in config.deployment_configuration.packages
                   if p.name == name and p.namespace == namespace)

    try:
        context = Context(
            request=request,
            config=config,
            web_socket=WebSocketsStore.logs
            )
        async with context.start(action=f"Upgrade {package.name} in {package.namespace}") as ctx:

            is_installed = await package.is_installed()

            resp = StatusBase(
                installed=is_installed,
                sanity=Sanity.SANE if is_installed else None,
                pending=True,
                namespace=namespace
                )
            await channel_ws.send_json(to_json_response(resp))
            await package.upgrade(ctx)
    finally:
        await finally_action()


router = APIRouter()


@router.get("/charts/{name}/namespaces/{namespace}", summary="return chart files & folders")
async def chart(
        name: str,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    package = next(p for p in config.deployment_configuration.packages
                   if p.name == name and p.namespace == namespace)
    response = {}
    for root, folders, files in os.walk(package.chart_folder):
        parent = Path(root).relative_to(package.chart_folder)
        response[str(parent)] = {
            "files": [{"name": f, "path": str(parent / f)} for f in files],
            "folders": [{"name": f, "path": str(parent / f)} for f in folders]}

    return response


@router.get("/charts/{name}/namespaces/{namespace}/files/{rest_of_path:path}", summary="return file content")
async def chart(
        name: str,
        namespace: str,
        rest_of_path: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    package = next(p for p in config.deployment_configuration.packages
                   if p.name == name and p.namespace == namespace)

    return FileResponse(package.chart_folder / rest_of_path)


