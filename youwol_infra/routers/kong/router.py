import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import aiohttp
from fastapi import APIRouter, Depends
from starlette.requests import Request
from starlette.responses import FileResponse

from youwol_infra.context import Context
from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import StatusBase, Sanity, HelmValues, install_pack
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.k8s_utils import (
    k8s_namespaces, k8s_create_namespace, k8s_create_secrets_if_needed,
    k8s_port_forward, k8s_get_service,
    )
from youwol_infra.utils.sql_utils import sql_exec_commands
from youwol_infra.utils.utils import to_json_response, get_port_number
from youwol_infra.web_sockets import WebSocketsStore
from youwol_utils import raise_exception_from_response

router = APIRouter()


class Status(StatusBase):
    pass


@dataclass
class Kong(HelmPackage):

    postgre_sql_pod_name: str = "postgresql-postgresql-0"
    name: str = "api"
    namespace: str = "api-gateway"

    icon: str = "/api/youwol-infra/kong/icon"

    chart_folder: Path = Configuration.charts_folder / 'kong'
    with_values: dict = field(default_factory=lambda: {})

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
            await k8s_create_namespace(name=self.namespace)

        context and await context.info(f"Create secrets", json=to_json_response(self.secrets))
        await k8s_create_secrets_if_needed(namespace="api-gateway", secrets=self.secrets)

        await sql_exec_commands(
            pod_name=self.postgre_sql_pod_name,
            commands=self.postgres_commands,
            context=context
            )

        await super().install(context)


async def send_status(
        request: Request,
        config: DynamicConfiguration,
        namespace: str):

    context = Context(
        request=request,
        config=config,
        web_socket=WebSocketsStore.logs
        )

    kong = next(p for p in config.deployment_configuration.packages
                if p.name == Kong.name and p.namespace == namespace)

    is_installed = await kong.is_installed()
    resp = Status(
        installed=is_installed,
        package=kong,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    if is_installed:
        await k8s_port_forward(namespace=namespace, service_name="api-kong-admin", target_port="kong-admin",
                               local_port=kong.kong_admin_port_fwd, context=context)
    await WebSocketsStore.ws.send_json(to_json_response(resp))


@router.get("/icon")
async def icon():
    path = Path(__file__).parent / 'kong.png'
    return FileResponse(path)


@router.get("/{namespace}/status", summary="trigger fetching status of Kong component")
async def status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    asyncio.ensure_future(send_status(request=request, namespace=namespace, config=config))


@router.post("/{namespace}/install", summary="trigger install of Kong component")
async def install(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await install_pack(
        request=request,
        config=config,
        name='api',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )


@router.get("/{namespace}/kong-admin/info", summary="kon admin service info")
async def kong_admin_info(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    service = await k8s_get_service(namespace=namespace, name='api-kong-admin')

    return to_json_response(service.to_dict())


@router.get("/{namespace}/kong-admin/services", summary="published services")
async def kong_admin_services(namespace: str):

    url = f"http://localhost:{Kong.kong_admin_port_fwd}/services"
    async with aiohttp.ClientSession() as session:
        async with await session.get(url=url) as resp:
            if resp.status == 200:
                return to_json_response(await resp.json())
            await raise_exception_from_response(resp, url=url)


@router.get("/{namespace}/kong-admin/services/{service}/routes", summary="published services")
async def kong_admin_services(namespace: str, service: str):

    url = f"http://localhost:{Kong.kong_admin_port_fwd}/services/{service}/routes"
    async with aiohttp.ClientSession() as session:
        async with await session.get(url=url) as resp:
            if resp.status == 200:
                return to_json_response(await resp.json())
            await raise_exception_from_response(resp, url=url)
