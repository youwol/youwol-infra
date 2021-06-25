import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import aiohttp
from fastapi import APIRouter, Depends
# from kubernetes_asyncio import utils as k8s_utils, client as k8s_client
from kubernetes_asyncio import utils as k8s_utils, client as k8s_client
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
from youwol_infra.utils.utils import to_json_response, get_port_number, exec_command
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

    acme_plugin: Path = Configuration.platform_folder / 'deployment' / 'k8s' / 'kong' / 'certs_gc.yaml'
    acme_hosts: List[str] = field(default_factory=list)

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


@router.post("/{namespace}/acme/install-certificates", summary="trigger install of certificates")
async def install_certificate(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    kong = next(p for p in config.deployment_configuration.packages
                if p.name == Kong.name and p.namespace == namespace)

    context = Context(
        request=request,
        config=config,
        web_socket=WebSocketsStore.logs
        )

    included_services = await kong_admin_services(namespace=namespace)

    async with context.start(action="Install certificates") as ctx:

        url_services, url_routes, url_acme = [f"http://localhost:{Kong.kong_admin_port_fwd}/{service}"
                                              for service in ['services', 'routes', 'acme']]

        await ctx.info("Create the acme plugin", json=to_json_response(kong))
        #await k8s_utils.create_from_yaml(k8s_client.ApiClient(), str(kong.acme_plugin))
        await exec_command(f"kubectl apply -f {str(kong.acme_plugin)} -n {namespace}", ctx)

        async with aiohttp.ClientSession() as session:

            for host in kong.acme_hosts:
                name = host.replace('.', '-')
                if name in [s['name'] for s in included_services['data']]:
                    await ctx.info(f"Dummy service {name} already declared")
                    continue
                await ctx.info(f"Create certificate for {host}")

                body_service = {
                    "name": name,
                    "host": host,
                    "url": "http://127.0.0.1:65535"
                    }
                async with await session.post(url=url_services,
                                              json=body_service) as resp:
                    if resp.status != 201:
                        await raise_exception_from_response(resp, url=url_services)
                await ctx.info(f"dummy service create", json=body_service)
                body_route = {
                    "name": name,
                    "hosts": [host],
                    "paths": ["/.well-known/acme-challenge"],
                    "service": {"name": name}
                    }
                async with await session.post(url=url_routes,
                                              json=body_route) as resp:
                    if resp.status != 201:
                        await raise_exception_from_response(resp, url=url_routes)

                await ctx.info(f"dummy route created", json=body_route)

            for host in kong.acme_hosts:

                await ctx.info(f"Create certificate on {host}")
                async with await session.post(url=url_acme,
                                              json={'host': host}) as resp:
                    if resp.status == 201:
                        await ctx.info(f"Certificate created successfully")
                    else:
                        await ctx.error(f"Certificate creation failed", json=await resp.json())

                async with await session.post(url=url_acme,
                                              json={'host': host, "test_http_challenge_flow": True}) as resp:
                    if resp.status == 200:
                        await ctx.info(f"Sanity test successful")
                    else:
                        await ctx.error(f"Sanity test failed", json=await resp.json())


@router.get("/{namespace}/kong-admin/info", summary="kon admin service info")
async def kong_admin_info(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    kong = next(p for p in config.deployment_configuration.packages
                if p.name == Kong.name and p.namespace == namespace)
    service = await k8s_get_service(namespace=kong.namespace, name="api-kong-admin")

    return to_json_response({"service": service.to_dict(), "port forward": kong.kong_admin_port_fwd})


@router.get("/{namespace}/kong-admin/services", summary="published services")
async def kong_admin_services(namespace: str):

    url = f"http://localhost:{Kong.kong_admin_port_fwd}/services"
    async with aiohttp.ClientSession() as session:
        async with await session.get(url=url) as resp:
            if resp.status == 200:
                return to_json_response(await resp.json())
            await raise_exception_from_response(resp, url=url)


@router.get("/{namespace}/kong-admin/services/{service}/routes", summary="published services")
async def kong_admin_routes(namespace: str, service: str):

    url = f"http://localhost:{Kong.kong_admin_port_fwd}/services/{service}/routes"
    async with aiohttp.ClientSession() as session:
        async with await session.get(url=url) as resp:
            if resp.status == 200:
                return to_json_response(await resp.json())
            await raise_exception_from_response(resp, url=url)
