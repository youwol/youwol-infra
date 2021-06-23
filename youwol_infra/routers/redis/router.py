from dataclasses import dataclass, field
from pathlib import Path

from fastapi import WebSocket, Depends, APIRouter
from starlette.requests import Request
from starlette.responses import FileResponse

from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import install_package, Sanity, StatusBase, HelmValues, install_pack
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore, start_web_socket


router = APIRouter()


class Status(StatusBase):
    pass


@dataclass
class Redis(HelmPackage):

    postgre_sql_pod_name: str = None
    name: str = "redis"
    namespace: str = "infra"
    icon: str = "/api/youwol-infra/redis/icon"
    chart_folder: Path = Configuration.charts_folder / name
    with_values: dict = field(default_factory=lambda: {})


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    WebSocketsStore.redis = ws
    await WebSocketsStore.redis.send_json({})
    await start_web_socket(ws)


async def send_status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration):

    redis = Redis()
    is_installed = await redis.is_installed()
    if not is_installed:
        resp = Status(
            installed=is_installed,
            namespace=namespace,
            sanity=Sanity.SANE if is_installed else None,
            pending=False
            )
        await WebSocketsStore.redis.send_json(to_json_response(resp))
        return

    resp = Status(
        installed=is_installed,
        namespace=namespace,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    await WebSocketsStore.redis.send_json(to_json_response(resp))


@router.get("/icon")
async def icon():
    path = Path(__file__).parent / 'redis.png'
    return FileResponse(path)


@router.get("/{namespace}/status", summary="trigger fetching status of Redis component")
async def status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    await send_status(request=request, namespace=namespace, config=config)


@router.post("/{namespace}/install", summary="trigger install of Redis component")
async def install(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await install_pack(
        request=request,
        config=config,
        name='redis',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.redis,
        finally_action=lambda: status(request, namespace, config)
        )
