from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, Depends
from pydantic import BaseModel
from starlette.requests import Request

from youwol_infra.context import Context
from youwol_infra.deployment_models import Deployment
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.utils.k8s_utils import k8s_namespaces
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore, start_web_socket

router = APIRouter()


class Sanity(Enum):
    SANE = "SANE",
    WARNINGS = "WARNINGS",
    BROKEN = "BROKEN",
    PENDING = "PENDING"


class Status(BaseModel):
    installed: bool
    sanity: Optional[Sanity]
    pending: bool
    dashboardUrl: str
    accessToken: str


@dataclass
class K8sDashboard(Deployment):
    name: str = "k8sDashboard"
    namespace: str = "kubernetes-dashboard"
    url: str = "https://raw.githubusercontent.com/kubernetes/dashboard/v2.2.0/aio/deploy/recommended.yaml"
    path: Path = None

    async def is_installed(self):
        return self.namespace in k8s_namespaces()

    def dashboard_url(self, proxy_port: int):
        base_url = f"http://localhost:{proxy_port}/api/v1/namespaces/{self.namespace}"
        service = self.namespace
        return f"{base_url}/services/https:{service}:/proxy/#/pod?namespace=_all"


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    WebSocketsStore.k8s_dashboard = ws
    await WebSocketsStore.k8s_dashboard.send_json({})
    # config = await dynamic_config()
    # await send_status(configuration=config)
    await start_web_socket(ws)


async def send_status(configuration: DynamicConfiguration):

    k8s_dashboard = K8sDashboard()
    is_installed = await k8s_dashboard.is_installed()
    resp = Status(
        installed=is_installed,
        sanity=Sanity.SANE if is_installed else None,
        pending=False,
        dashboardUrl=k8s_dashboard.dashboard_url(configuration.deployment_configuration.general.proxyPort),
        accessToken=configuration.cluster_info.access_token
        )
    await WebSocketsStore.k8s_dashboard.send_json(to_json_response(resp))


@router.get("/status", summary="trigger fetching status of k8s dashboard component")
async def status(config: DynamicConfiguration = Depends(dynamic_config)):
    await send_status(config)


@router.get("/install", summary="trigger install of k8s dashboard component")
async def install(request: Request, config: DynamicConfiguration = Depends(dynamic_config)):

    context = Context(
        request=request,
        config=config,
        web_socket=WebSocketsStore.logs
        )
    async with context.start(action="Install K8s dashboard") as ctx:
        k8s_dashboard = K8sDashboard()
        is_installed = await k8s_dashboard.is_installed()
        if is_installed:
            ctx.info(content="dashboard already installed")
            return
        resp = Status(
            installed=is_installed,
            sanity=Sanity.SANE if is_installed else None,
            pending=True,
            dashboardUrl=k8s_dashboard.dashboard_url(config.deployment_configuration.general.proxyPort),
            accessToken=config.cluster_info.access_token
            )
        await WebSocketsStore.k8s_dashboard.send_json(to_json_response(resp))
        try:
            await k8s_dashboard.install()
        finally:
            await send_status(config)
