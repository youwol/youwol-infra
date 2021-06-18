from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import aiohttp
from fastapi import APIRouter, WebSocket, Depends
from starlette.requests import Request

from youwol_infra.context import Context
from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import install_package, StatusBase, Sanity
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.k8s_utils import (
    k8s_namespaces, k8s_create_namespace, k8s_create_secrets_if_needed,
    k8s_port_forward, k8s_get_service,
    )
from youwol_infra.utils.sql_utils import sql_exec_commands
from youwol_infra.utils.utils import to_json_response, get_port_number
from youwol_infra.web_sockets import WebSocketsStore, start_web_socket
from youwol_utils import raise_exception_from_response

router = APIRouter()


class Status(StatusBase):
    pass


@dataclass
class Kong(HelmPackage):

    postgre_sql_pod_name: str = "postgresql-postgresql-0"
    name: str = "api"
    namespace: str = "api-gateway"
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

    kong_admin_port_fwd = get_port_number(name='kong-admin', ports_range=(2000, 3000))

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


async def send_status(request: Request, config: DynamicConfiguration):

    context = Context(
        request=request,
        config=config,
        web_socket=WebSocketsStore.logs
        )

    kong = Kong()
    is_installed = await kong.is_installed()
    resp = Status(
        installed=is_installed,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    if is_installed:
        await k8s_port_forward(namespace='api-gateway', service_name="api-kong-admin", target_port="kong-admin",
                               local_port=kong.kong_admin_port_fwd, context=context)
    await WebSocketsStore.kong.send_json(to_json_response(resp))


@router.get("/status", summary="trigger fetching status of Kong component")
async def status(request: Request, config: DynamicConfiguration = Depends(dynamic_config)):
    await send_status(request=request, config=config)


@router.get("/install", summary="trigger install of Kong component")
async def install(request: Request, config: DynamicConfiguration = Depends(dynamic_config)):

    package = Kong()
    try:
        await install_package(request=request, config=config, package=package,
                              channel_ws=WebSocketsStore.kong)
    finally:
        await send_status(request=request, config=config)


@router.get("/kong-admin/info", summary="kon admin service info")
async def kong_admin_info(request: Request, config: DynamicConfiguration = Depends(dynamic_config)):

    service = await k8s_get_service(namespace=Kong.namespace, name='api-kong-admin')

    return to_json_response(service.to_dict())


@router.get("/kong-admin/services", summary="published services")
async def kong_admin_services():

    url = f"http://localhost:{Kong.kong_admin_port_fwd}/services"
    async with aiohttp.ClientSession() as session:
        async with await session.get(url=url) as resp:
            if resp.status == 200:
                return to_json_response(await resp.json())
            await raise_exception_from_response(resp, url=url)


@router.get("/kong-admin/services/{service}/routes", summary="published services")
async def kong_admin_services(service: str):

    url = f"http://localhost:{Kong.kong_admin_port_fwd}/services/{service}/routes"
    async with aiohttp.ClientSession() as session:
        async with await session.get(url=url) as resp:
            if resp.status == 200:
                return to_json_response(await resp.json())
            await raise_exception_from_response(resp, url=url)

