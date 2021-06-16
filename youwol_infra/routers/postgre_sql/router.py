from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, WebSocket, Depends
from pydantic import BaseModel
from starlette.requests import Request

from youwol_infra.context import Context
from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import install_package, StatusBase, Sanity
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.sql_utils import sql_exec_commands
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore, start_web_socket

router = APIRouter()


class Status(StatusBase):
    pass


@dataclass
class PostgreSQL(HelmPackage):

    name: str = "postgresql"
    namespace: str = "infra"
    postgre_sql_pod_name: str = "postgresql-postgresql-0"
    chart_folder: Path = Configuration.charts_folder / name

    with_values: dict = field(default_factory=lambda: {
            "persistence": {
                "storageClass": "standard",
                "size": "2Gi"
                }
            })

    postgres_commands: List[str] = field(default_factory=lambda: [
        "CREATE ROLE youwoluser WITH LOGIN;",
        "CREATE GROUP youwol WITH ROLE youwoluser;"
        ])

    async def install(self, context: Context = None):
        await super().install(context)
        context and await context.info(text="Create sql resources", json={"postgres_commands": self.postgres_commands})
        await sql_exec_commands(
            pod_name=self.postgre_sql_pod_name,
            commands=self.postgres_commands
            )


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    WebSocketsStore.postgre_sql = ws
    await WebSocketsStore.postgre_sql.send_json({})
    await start_web_socket(ws)


async def send_status(configuration: DynamicConfiguration):

    postgre_sql = PostgreSQL()
    is_installed = await postgre_sql.is_installed()
    resp = Status(
        installed=is_installed,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    await WebSocketsStore.postgre_sql.send_json(to_json_response(resp))


@router.get("/status", summary="trigger fetching status of postgre SQL component")
async def status(config: DynamicConfiguration = Depends(dynamic_config)):
    await send_status(config)


@router.get("/install", summary="trigger install of postgre SQL component")
async def install(request: Request, config: DynamicConfiguration = Depends(dynamic_config)):

    package = PostgreSQL()
    try:
        await install_package(request=request, config=config, package=package,
                              channel_ws=WebSocketsStore.postgre_sql)
    finally:
        await send_status(config)

