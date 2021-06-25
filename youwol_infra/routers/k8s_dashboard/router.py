import asyncio
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends
from starlette.requests import Request
from starlette.responses import FileResponse

from youwol_infra.deployment_models import Deployment
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import StatusBase, Sanity, HelmValues, install_pack
from youwol_infra.utils.k8s_utils import k8s_namespaces
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore

router = APIRouter()


class Status(StatusBase):
    dashboardUrl: str
    accessToken: str


@dataclass
class K8sDashboard(Deployment):
    name: str = "k8sDashboard"
    namespace: str = "kubernetes-dashboard"
    icon: str = "/api/youwol-infra/k8s-dashboard/icon"
    url: str = "https://raw.githubusercontent.com/kubernetes/dashboard/v2.2.0/aio/deploy/recommended.yaml"
    path: Path = None

    async def is_installed(self):
        namespaces = await k8s_namespaces()
        return self.namespace in namespaces

    def dashboard_url(self, proxy_port: int):
        base_url = f"http://localhost:{proxy_port}/api/v1/namespaces/{self.namespace}"
        service = self.namespace
        return f"{base_url}/services/https:{service}:/proxy/#/pod?namespace=_all"


async def send_status(namespace: str, config: DynamicConfiguration):

    k8s_dashboard = next(p for p in config.deployment_configuration.packages
                         if p.name == K8sDashboard.name and p.namespace == namespace)

    is_installed = await k8s_dashboard.is_installed()
    resp = Status(
        installed=is_installed,
        package=k8s_dashboard,
        sanity=Sanity.SANE if is_installed else None,
        pending=False,
        dashboardUrl=k8s_dashboard.dashboard_url(config.deployment_configuration.general.proxyPort),
        accessToken=config.cluster_info.access_token
        )
    await WebSocketsStore.ws.send_json(to_json_response(resp))


@router.get("/icon")
async def icon():
    path = Path(__file__).parent / 'k8s-dashboard.png'
    return FileResponse(path)


@router.get("/{namespace}/status", summary="trigger fetching status of k8s dashboard component")
async def status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)):

    asyncio.ensure_future(send_status(namespace=namespace, config=config))


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
        name=K8sDashboard.name,
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )
