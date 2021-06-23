from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, WebSocket, Depends
from starlette.requests import Request
from starlette.responses import FileResponse

from youwol_infra.context import Context
from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import install_package, StatusBase, Sanity
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.k8s_utils import k8s_create_secrets_if_needed
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore, start_web_socket

router = APIRouter()


class Status(StatusBase):
    pass


@dataclass
class Storage(HelmPackage):

    name: str = "storage"
    namespace: str = "prod"
    chart_folder: Path = Configuration.services_folder / "storage" / "chart"
    with_values: dict = field(default_factory=lambda: {
        "ingress": {
            "hosts[0].host": f"gc.platform.youwol.com"
            },
        "image": {
            "tag": "0.2.12-master"
            }
        })

    secrets: dict = field(default_factory=lambda: {
        "youwol-docker": Configuration.secrets_folder / "youwol-docker.yaml",
        "keycloak": Configuration.secrets_folder / "keycloak.yaml"
        })

    async def install(self, context: Context = None):

        await k8s_create_secrets_if_needed(namespace=self.namespace, secrets=self.secrets, context=context)
        await super().install(context=context)


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    WebSocketsStore.storage = ws
    await WebSocketsStore.storage.send_json({})
    await start_web_socket(ws)


async def send_status(request: Request, config: DynamicConfiguration):

    storage = Storage()
    is_installed = await storage.is_installed()
    if not is_installed:
        resp = Status(
            installed=is_installed,
            sanity=Sanity.SANE if is_installed else None,
            pending=False
            )
        await WebSocketsStore.storage.send_json(to_json_response(resp))
        return

    resp = Status(
        installed=is_installed,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    await WebSocketsStore.storage.send_json(to_json_response(resp))


@router.get("/icon")
async def icon():
    path = Path(__file__).parent / 'storage.png'
    return FileResponse(path)


@router.get("/status", summary="trigger fetching status of Storage component")
async def status(request: Request, config: DynamicConfiguration = Depends(dynamic_config)):
    await send_status(request=request, config=config)


@router.get("/install", summary="trigger install of Storage component")
async def install(request: Request, config: DynamicConfiguration = Depends(dynamic_config)):

    package = Storage()
    try:
        await install_package(request=request, config=config, package=package,
                              channel_ws=WebSocketsStore.storage)
    finally:
        await send_status(request=request, config=config)


# @router.get("/upgrade", summary="trigger upgrade of Storage component")
# async def upgrade(request: Request, config: DynamicConfiguration = Depends(dynamic_config)):
#
#     package = Minio()
#     try:
#         await upgrade_package(request=request, config=config, package=package,
#                               channel_ws=WebSocketsStore.minio)
#     finally:
#         await send_status(request=request, config=config)
