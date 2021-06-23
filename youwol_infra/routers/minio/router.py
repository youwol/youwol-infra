import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, WebSocket, Depends
from kubernetes import client
from kubernetes.client import ExtensionsV1beta1Api
from starlette.requests import Request
from starlette.responses import FileResponse

from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import install_package, StatusBase, Sanity, upgrade_package
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.k8s_utils import k8s_get_ingress
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore, start_web_socket

router = APIRouter()


class Status(StatusBase):
    url: str
    accessKey: str
    secretKey: str


@dataclass
class Minio(HelmPackage):

    postgre_sql_pod_name: str = "postgresql-postgresql-0"
    name: str = "minio"
    namespace: str = "prod"
    chart_folder: Path = Configuration.charts_folder / name
    with_values: dict = field(default_factory=lambda: {
            "replicas": 1,
            "persistence": {
                "storageClass": "standard",
                "size": "1Gi"
                },
            "ingress": {
                "enabled": "true",
                "hosts[0]": f"minio.gc.platform.youwol.com"
                }
            })


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


async def send_status(request: Request, config: DynamicConfiguration):

    minio = Minio()
    is_installed = await minio.is_installed()
    ingress = await k8s_get_ingress(namespace=minio.namespace, name=minio.name)
    secret = client.CoreV1Api().read_namespaced_secret(name="minio", namespace=minio.namespace).data
    resp = Status(
        installed=is_installed,
        sanity=Sanity.SANE if is_installed else None,
        pending=False,
        url=f"https://{ingress.spec.rules[0].host}",
        accessKey=base64.b64decode(secret["accesskey"]).decode('ascii'),
        secretKey=base64.b64decode(secret["secretkey"]).decode('ascii')
        )
    await WebSocketsStore.minio.send_json(to_json_response(resp))


@router.get("/status", summary="trigger fetching status of Minio component")
async def status(request: Request, config: DynamicConfiguration = Depends(dynamic_config)):
    await send_status(request=request, config=config)


@router.get("/install", summary="trigger install of Minio component")
async def install(request: Request, config: DynamicConfiguration = Depends(dynamic_config)):

    package = Minio()
    try:
        await install_package(request=request, config=config, package=package,
                              channel_ws=WebSocketsStore.minio)
    finally:
        await send_status(request=request, config=config)


@router.get("/upgrade", summary="trigger upgrade of Minio component")
async def upgrade(request: Request, config: DynamicConfiguration = Depends(dynamic_config)):

    package = Minio()
    try:
        await upgrade_package(request=request, config=config, package=package,
                              channel_ws=WebSocketsStore.minio)
    finally:
        await send_status(request=request, config=config)
