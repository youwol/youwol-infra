from enum import Enum
from typing import Optional

from pydantic import BaseModel
from starlette.requests import Request
from starlette.websockets import WebSocket

from youwol_infra.context import Context
from youwol_infra.deployment_models import Package
from youwol_infra.dynamic_configuration import DynamicConfiguration
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore


class Sanity(Enum):
    SANE = "SANE",
    WARNINGS = "WARNINGS",
    BROKEN = "BROKEN",
    PENDING = "PENDING"


class StatusBase(BaseModel):
    installed: bool
    sanity: Optional[Sanity]
    pending: bool


async def install_package(
        request: Request,
        config: DynamicConfiguration,
        package: Package,
        channel_ws: WebSocket):

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
            sanity=Sanity.SANE if is_installed else None,
            pending=True
            )
        await channel_ws.send_json(to_json_response(resp))
        await package.install(ctx)


async def upgrade_package(
        request: Request,
        config: DynamicConfiguration,
        package: Package,
        channel_ws: WebSocket):

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
            pending=True
            )
        await channel_ws.send_json(to_json_response(resp))
        await package.upgrade(ctx)
