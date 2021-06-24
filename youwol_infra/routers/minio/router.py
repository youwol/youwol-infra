import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, Depends
from kubernetes import client
from starlette.requests import Request
from starlette.responses import FileResponse

from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import (
    StatusBase, Sanity, install_pack, HelmValues,
    upgrade_pack,
    )
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.k8s_utils import k8s_get_ingress
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore, start_web_socket

router = APIRouter()


class Status(StatusBase):
    url: Optional[str]
    accessKey: Optional[str]
    secretKey: Optional[str]


@dataclass
class Minio(HelmPackage):

    postgre_sql_pod_name: str = "postgresql-postgresql-0"
    name: str = "minio"
    namespace: str = "prod"

    icon: str = "/api/youwol-infra/minio/icon"

    chart_folder: Path = Configuration.charts_folder / name
    with_values: dict = field(default_factory=lambda: {})


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    WebSocketsStore.minio = ws
    await WebSocketsStore.minio.send_json({})
    await start_web_socket(ws)


@router.get("/icon")
async def icon():
    path = Path(__file__).parent / 'minio.png'
    return FileResponse(path)


async def send_status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration
        ):

    minio = next(p for p in config.deployment_configuration.packages
                 if p.name == Minio.name and p.namespace == namespace)

    is_installed = await minio.is_installed()
    if not is_installed:
        resp = Status(
            installed=is_installed,
            namespace=namespace,
            sanity=Sanity.SANE if is_installed else None,
            pending=False,
            url=None,
            accessKey=None,
            secretKey=None
            )
        await WebSocketsStore.minio.send_json(to_json_response(resp))
        return
    ingress = await k8s_get_ingress(namespace=minio.namespace, name=minio.name)
    secret = client.CoreV1Api().read_namespaced_secret(name="minio", namespace=minio.namespace).data
    resp = Status(
        installed=is_installed,
        namespace=namespace,
        sanity=Sanity.SANE if is_installed else None,
        pending=False,
        url=f"https://{ingress.spec.rules[0].host}",
        accessKey=base64.b64decode(secret["accesskey"]).decode('ascii'),
        secretKey=base64.b64decode(secret["secretkey"]).decode('ascii')
        )
    await WebSocketsStore.minio.send_json(to_json_response(resp))


@router.get("/{namespace}/status", summary="trigger fetching status of Minio component")
async def status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    await send_status(request=request, namespace=namespace, config=config)


@router.post("/{namespace}/install", summary="trigger install of Minio component")
async def install(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await install_pack(
        request=request,
        config=config,
        name='minio',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.minio,
        finally_action=lambda: status(request, namespace, config)
        )


@router.post("/{namespace}/upgrade", summary="trigger upgrade of Minio component")
async def upgrade(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await upgrade_pack(
        request=request,
        config=config,
        name='minio',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.minio,
        finally_action=lambda: status(request, namespace, config)
        )
