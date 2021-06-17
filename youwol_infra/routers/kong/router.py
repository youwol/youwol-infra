from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from fastapi import APIRouter, WebSocket, Depends
from starlette.requests import Request

from youwol_infra.context import Context
from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import install_package, StatusBase, Sanity
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.k8s_utils import k8s_namespaces, k8s_create_namespace, k8s_create_secrets_if_needed
from youwol_infra.utils.sql_utils import sql_exec_commands
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore, start_web_socket

router = APIRouter()


class Status(StatusBase):
    pass


@dataclass
class Kong(HelmPackage):

    postgre_sql_pod_name: str = "postgresql-postgresql-0"
    name: str = "api"
    namespace: str = "api-gateway"
    welcome_messages: List[str] = field(default_factory=list)
    success_messages: List[str] = field(default_factory=list)
    chart_folder: Path = Configuration.charts_folder / 'kong'
    with_values: dict = field(default_factory=lambda: {
             "proxy": {
                 "loadBalancerIP": "104.199.0.92"
                 }
             })

    secrets: dict = field(default_factory=lambda: {
        "gitlab-docker": Configuration.secrets_folder / "gitlab-docker.yaml",
        "oidc": Configuration.secrets_folder / "kong" / "oidc.yaml"
        })

    postgres_commands: List[str] = field(default_factory=lambda: [
        "CREATE USER kong IN GROUP youwol PASSWORD \$\$postgres\$\$;",
        "CREATE DATABASE kong;",
        "GRANT ALL PRIVILEGES ON DATABASE kong TO kong;"
        ])

    async def install(self, context: Context = None):

        if self.namespace not in k8s_namespaces():
            context and await context.info(f"Create namespace {self.namespace}")
            k8s_create_namespace(name=self.namespace)

        context and await context.info(f"Create secrets", json=to_json_response(self.secrets))
        k8s_create_secrets_if_needed(namespace="api-gateway", secrets=self.secrets)

        await sql_exec_commands(
            pod_name=self.postgre_sql_pod_name,
            commands=self.postgres_commands,
            context=context
            )

        await super().install(context)


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    WebSocketsStore.kong = ws
    await WebSocketsStore.kong.send_json({})
    await start_web_socket(ws)


async def send_status(configuration: DynamicConfiguration):

    kong = Kong()
    is_installed = await kong.is_installed()
    resp = Status(
        installed=is_installed,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    await WebSocketsStore.kong.send_json(to_json_response(resp))


@router.get("/status", summary="trigger fetching status of Kong component")
async def status(config: DynamicConfiguration = Depends(dynamic_config)):
    await send_status(config)


@router.get("/install", summary="trigger install of Kong component")
async def install(request: Request, config: DynamicConfiguration = Depends(dynamic_config)):

    package = Kong()
    try:
        await install_package(request=request, config=config, package=package,
                              channel_ws=WebSocketsStore.kong)
    finally:
        await send_status(config)