import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends
from starlette.requests import Request
from starlette.responses import FileResponse

from youwol_infra.context import Context
from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import DynamicConfiguration, dynamic_config
from youwol_infra.routers.common import StatusBase, Sanity, HelmValues, install_pack, upgrade_pack
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.k8s_utils import k8s_port_forward
from youwol_infra.utils.sql_utils import sql_exec_commands
from youwol_infra.utils.utils import to_json_response, get_port_number
from youwol_infra.web_sockets import WebSocketsStore


router = APIRouter()


class Status(StatusBase):
    pass


@dataclass
class Keycloak(HelmPackage):

    postgre_sql_pod_name: str = "postgresql-postgresql-0"
    name: str = "auth"
    namespace: str = "infra"

    icon: str = "/api/youwol-infra/keycloak/icon"

    chart_folder: Path = Configuration.charts_folder / "keycloak"
    with_values: dict = field(default_factory=lambda: {})

    postgres_commands: List[str] = field(default_factory=lambda: [
        "CREATE USER keycloak IN GROUP youwol PASSWORD \$\$postgres\$\$;",
        "CREATE DATABASE keycloak;",
        "GRANT ALL PRIVILEGES ON DATABASE keycloak TO keycloak;"
        ])

    keycloak_http_port_fwd = get_port_number(name='keycloak_http', ports_range=(2000, 3000))

    post_install_messages: List[str] = field(default_factory=lambda: [
        "WARNING!! : the property extraEnv KEYCLOAK_FRONTEND_URL need to be updated !!"
        ])

    async def install(self, context: Context = None):
        await sql_exec_commands(
            pod_name=self.postgre_sql_pod_name,
            commands=self.postgres_commands
            )
        await super().install(context)


async def send_status(request: Request, namespace: str, config: DynamicConfiguration):

    context = Context(
        request=request,
        config=config,
        web_socket=WebSocketsStore.logs
        )

    keycloak = next(p for p in config.deployment_configuration.packages
                    if p.name == Keycloak.name and p.namespace == namespace)

    is_installed = await keycloak.is_installed()
    resp = Status(
        installed=is_installed,
        package=keycloak,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    if is_installed:
        await k8s_port_forward(namespace=namespace, service_name="keycloak-http", target_port='http',
                               local_port=keycloak.keycloak_http_port_fwd, context=context)

    await WebSocketsStore.ws.send_json(to_json_response(resp))


@router.get("/icon")
async def icon():
    path = Path(__file__).parent / 'keycloak.png'
    return FileResponse(path)


@router.get("/{namespace}/status", summary="trigger fetching status of Keycloak component")
async def status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)):

    asyncio.ensure_future(send_status(request=request, namespace=namespace, config=config))


@router.post("/{namespace}/install", summary="trigger install of Keycloak component")
async def install(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await install_pack(
        request=request,
        config=config,
        name=Keycloak.name,
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )


@router.post("/{namespace}/upgrade", summary="trigger upgrade of Keycloak component")
async def install(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await upgrade_pack(
        request=request,
        config=config,
        name=Keycloak.name,
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )
