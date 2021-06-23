from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from fastapi import APIRouter, WebSocket, Depends
from starlette.requests import Request
from starlette.responses import FileResponse

from youwol_infra.context import Context
from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import StatusBase, Sanity, HelmValues, install_pack, upgrade_pack
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

    icon: str = "/api/youwol-infra/postgre-sql/icon"

    postgre_sql_pod_name: str = "postgresql-postgresql-0"
    chart_folder: Path = Configuration.charts_folder / name

    with_values: dict = field(default_factory=lambda: {})

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


async def send_status(namespace: str, configuration: DynamicConfiguration):

    postgre_sql = PostgreSQL()
    is_installed = await postgre_sql.is_installed()
    resp = Status(
        installed=is_installed,
        namespace=namespace,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    await WebSocketsStore.postgre_sql.send_json(to_json_response(resp))


@router.get("/icon")
async def icon():
    path = Path(__file__).parent / 'postgre.svg'
    return FileResponse(path)


@router.get("/{namespace}/status", summary="trigger fetching status of postgre SQL component")
async def status(
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    await send_status(namespace=namespace, configuration=config)


@router.post("/{namespace}/install", summary="trigger install of PostgreSql component")
async def install(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await install_pack(
        request=request,
        config=config,
        name='postgresql',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.postgre_sql,
        finally_action=lambda: status(request, namespace, config)
        )


@router.post("/{namespace}/upgrade", summary="trigger upgrade of PostgreSql component")
async def upgrade(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await upgrade_pack(
        request=request,
        config=config,
        name='postgresql',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.postgre_sql,
        finally_action=lambda: status(request, namespace, config)
        )
