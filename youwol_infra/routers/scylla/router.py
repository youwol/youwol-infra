import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Depends
from starlette.requests import Request
from starlette.responses import FileResponse

from youwol_infra.context import Context
from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import StatusBase, Sanity, HelmValues, install_pack, upgrade_pack
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.k8s_utils import k8s_create_secrets_if_needed, k8s_pod_exec
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore

router = APIRouter()


class Status(StatusBase):
    cqlsh_url: str


@dataclass
class Scylla(HelmPackage):

    name: str = "scylla"
    namespace: str = "infra"
    icon: str = "/api/youwol-infra/scylla/icon"
    chart_folder: Path = Configuration.charts_folder / "scylladb"
    with_values: dict = field(default_factory=lambda: {})

    secrets: dict = field(default_factory=lambda: {
        "gitlab-docker": Configuration.secrets_folder / "gitlab-docker.yaml"
        })

    async def install(self, context: Context = None):

        await k8s_create_secrets_if_needed(namespace="infra", secrets=self.secrets)
        await super().install(context=context)


async def send_status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration):

    scylla = next(p for p in config.deployment_configuration.packages
                  if p.name == Scylla.name and p.namespace == namespace)

    is_installed = await scylla.is_installed()
    cqlsh_url=f"http://localhost:{config.deployment_configuration.general.proxyPort}/api/v1/namespaces/" + \
              "kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/#/" + \
              f"shell/{namespace}/scylla-0/scylladb?namespace={namespace}"
    if not is_installed:
        resp = Status(
            installed=is_installed,
            package=scylla,
            cqlsh_url=cqlsh_url,
            sanity=Sanity.SANE if is_installed else None,
            pending=False
            )
        await WebSocketsStore.ws.send_json(to_json_response(resp))
        return

    resp = Status(
        installed=is_installed,
        package=scylla,
        cqlsh_url=cqlsh_url,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    await WebSocketsStore.ws.send_json(to_json_response(resp))


@router.get("/icon")
async def icon():
    path = Path(__file__).parent / 'scylla.png'
    return FileResponse(path)


@router.get("/{namespace}/status", summary="trigger fetching status of Scylla component")
async def status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    asyncio.ensure_future(send_status(request=request, namespace=namespace, config=config))


@router.post("/{namespace}/install", summary="trigger install of Scylla component")
async def install(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await install_pack(
        request=request,
        config=config,
        name='scylla',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )


@router.post("/{namespace}/upgrade", summary="trigger install of Scylla component")
async def upgrade(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await upgrade_pack(
        request=request,
        config=config,
        name='scylla',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )


@router.get("/{namespace}/keyspaces", summary="list keyspaces")
async def get_keyspaces(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    context = Context(
        request=request,
        config=config,
        web_socket=WebSocketsStore.logs
        )

    async with context.start(action=f"Get Scylla's keyspaces list") as ctx:
        command = "cqlsh -e 'SELECT * FROM system_schema.keyspaces;'"
        keyspaces = await k8s_pod_exec(pod_name='scylla-0', namespace=namespace, commands=[command], context=ctx)
        items = [{'name': line.split('|')[0].strip(),
                  'durableWrites': line.split('|')[1].strip() == 'True',
                  'replication': json.loads(line.split('|')[2].replace('\'', "\""))}
                 for line in keyspaces[0][3:-2]]
        return {"keyspaces": items}


@router.get("/{namespace}/keyspaces/{keyspace}/tables", summary="list keyspaces")
async def get_tables(
        request: Request,
        namespace: str,
        keyspace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    context = Context(
        request=request,
        config=config,
        web_socket=WebSocketsStore.logs
        )
    async with context.start(action=f"Get Scylla's tables list from keyspace '{keyspace}' ") as ctx:
        command = f"cqlsh -e 'SELECT * FROM system_schema.tables WHERE keyspace_name=\$\${keyspace}\$\$;'"
        tables = await k8s_pod_exec(pod_name='scylla-0', namespace=namespace, commands=[command], context=ctx)
        items = [{'keyspaceName': line.split('|')[0].strip(), "tableName":line.split('|')[1].strip()}
                 for line in tables[0][3:-2]]

    return {"tables": items}
