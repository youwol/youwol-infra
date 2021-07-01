import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, WebSocket, Depends
from starlette.requests import Request
from starlette.responses import FileResponse

from youwol_infra.context import Context
from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import StatusBase, Sanity, HelmValues, install_pack, upgrade_pack
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.k8s_utils import k8s_create_secrets_if_needed
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore, start_web_socket

router = APIRouter()


class Status(StatusBase):
    pass


@dataclass
class DocDb(HelmPackage):

    name: str = "docdb"
    namespace: str = "prod"

    icon: str = "/api/youwol-infra/docdb/icon"

    chart_folder: Path = Configuration.services_folder / "docdb" / "chart"
    with_values: dict = field(default_factory=lambda: {})

    docdb_port_fwd = get_port_number(name='docdb', ports_range=(2000, 3000))


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    WebSocketsStore.docdb = ws
    await WebSocketsStore.docdb.send_json({})
    await start_web_socket(ws)


async def send_status(
        request: Request,
        config: DynamicConfiguration,
        namespace: str
        ):

    context = Context(
        request=request,
        config=config,
        web_socket=WebSocketsStore.logs
        )

    docdb = next(p for p in config.deployment_configuration.packages
                 if p.name == DocDb.name and p.namespace == namespace)

    is_installed = await docdb.is_installed()
    if not is_installed:
        resp = Status(
            installed=is_installed,
            package=docdb,
            sanity=Sanity.SANE if is_installed else None,
            pending=False
            )
        await WebSocketsStore.ws.send_json(to_json_response(resp))
        return

    await k8s_port_forward(namespace=namespace, service_name="docdb", target_port='http',
                           local_port=docdb.docdb_port_fwd, context=context)

    resp = Status(
        installed=is_installed,
        package=docdb,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    await WebSocketsStore.ws.send_json(to_json_response(resp))


@router.get("/icon")
async def icon():
    path = Path(__file__).parent / 'docdb.png'
    return FileResponse(path)


@router.get("/{namespace}/status", summary="trigger fetching status of DocDb component")
async def status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    asyncio.ensure_future(send_status(request=request, namespace=namespace, config=config))


@router.post("/{namespace}/install", summary="trigger install of DocDb component")
async def install(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await install_pack(
        request=request,
        config=config,
        name='docdb',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )


@router.post("/{namespace}/upgrade", summary="trigger install of DocDb component")
async def upgrade(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await upgrade_pack(
        request=request,
        config=config,
        name='docdb',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )