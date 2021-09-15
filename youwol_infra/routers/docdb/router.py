import asyncio
import glob
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Mapping, Any

from aiohttp import ClientSession
from fastapi import APIRouter, WebSocket, Depends
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import FileResponse

from youwol_infra.context import Context
from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import StatusBase, Sanity, HelmValues, install_pack, upgrade_pack
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.k8s_utils import k8s_port_forward
from youwol_infra.utils.utils import to_json_response, get_port_number, get_aiohttp_session, parse_json
from youwol_infra.web_sockets import WebSocketsStore, start_web_socket
from youwol_utils import raise_exception_from_response, QueryBody

router = APIRouter()


class Status(StatusBase):
    pass


@dataclass
class DocDb(HelmPackage):

    name: str = "docdb"
    namespace: str = "prod"

    icon: str = "/api/youwol-infra/docdb/icon"

    chart_folder: Path = Configuration.services_folder / "docdb" / "chart"
    with_values: dict = field(default_factory=lambda: {})

    docdb_port_fwd = get_port_number(name='docdb', ports_range=(2000, 3000))


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    WebSocketsStore.docdb = ws
    await WebSocketsStore.docdb.send_json({})
    await start_web_socket(ws)


async def send_status(
        request: Request,
        config: DynamicConfiguration,
        namespace: str
        ):

    context = Context(
        request=request,
        config=config,
        web_socket=WebSocketsStore.logs
        )

    docdb = next(p for p in config.deployment_configuration.packages
                 if p.name == DocDb.name and p.namespace == namespace)

    is_installed = await docdb.is_installed()
    if not is_installed:
        resp = Status(
            installed=is_installed,
            package=docdb,
            sanity=Sanity.SANE if is_installed else None,
            pending=False
            )
        await WebSocketsStore.ws.send_json(to_json_response(resp))
        return

    await k8s_port_forward(namespace=namespace, service_name="docdb", target_port='http',
                           local_port=docdb.docdb_port_fwd, context=context)

    resp = Status(
        installed=is_installed,
        package=docdb,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    await WebSocketsStore.ws.send_json(to_json_response(resp))


@router.get("/icon")
async def icon():
    path = Path(__file__).parent / 'docdb.png'
    return FileResponse(path)


@router.get("/{namespace}/status", summary="trigger fetching status of DocDb component")
async def status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    asyncio.ensure_future(send_status(request=request, namespace=namespace, config=config))


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
        name='docdb',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )


@router.post("/{namespace}/upgrade", summary="trigger install of DocDb component")
async def upgrade(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await upgrade_pack(
        request=request,
        config=config,
        name='docdb',
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
    docdb = next(p for p in config.deployment_configuration.packages
                 if p.name == DocDb.name and p.namespace == namespace)

    url = f"http://127.0.0.1:{docdb.docdb_port_fwd}/api/v0-alpha1/keyspaces"

    async with context.start(action=f"Get docdb keyspaces list",
                             json={"url": url, "namespace": namespace}) as ctx:
        access_token = await config.get_client_credentials(
            client_id="youwol-dev",
            scope="email profile youwol_dev",
            context=ctx
            )
        headers = {
            "authorization": f"Bearer {access_token}"
            }

        async with get_aiohttp_session() as session:
            async with await session.get(url=url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"keyspaces": data}
                await raise_exception_from_response(resp, url=url)


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
    docdb = next(p for p in config.deployment_configuration.packages
                 if p.name == DocDb.name and p.namespace == namespace)
    url = f"http://127.0.0.1:{docdb.docdb_port_fwd}/api/v0-alpha1/{keyspace}/tables"

    async with context.start(
            action=f"Get docdb table list",
            json={"url": url, "namespace": namespace, "keyspace": keyspace}) as ctx:

        access_token = await config.get_client_credentials(
            client_id="youwol-dev",
            scope="email profile youwol_dev",
            context=ctx
            )
        headers = {
            "authorization": f"Bearer {access_token}"
            }

        async with get_aiohttp_session() as session:
            async with await session.get(url=url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"tables": data}
                await raise_exception_from_response(resp, url=url)


class Query(BaseModel):
    queryStr: str


@router.post("/{namespace}/keyspaces/{keyspace}/tables/{table}/query", summary="list keyspaces")
async def query_table(
        request: Request,
        namespace: str,
        keyspace: str,
        table: str,
        body: Query,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    context = Context(
        request=request,
        config=config,
        web_socket=WebSocketsStore.logs
        )
    docdb = next(p for p in config.deployment_configuration.packages
                 if p.name == DocDb.name and p.namespace == namespace)
    url = f"http://127.0.0.1:{docdb.docdb_port_fwd}/api/v0-alpha1/{keyspace}/{table}/query"
    query_body = QueryBody.parse(body.queryStr)
    async with context.start(
            action=f"Query docdb table",
            json={"url": url, "namespace": namespace, "keyspace": keyspace, "table": table, "query": body.queryStr,
                  "query_body": query_body.dict()
                  }
            ) as ctx:

        access_token = await config.get_client_credentials(
            client_id="youwol-dev",
            scope="email profile youwol_dev",
            context=ctx
            )
        headers = {
            "authorization": f"Bearer {access_token}"
            }
        params = {"owner": "/youwol-users"}

        async with get_aiohttp_session() as session:
            async with await session.post(url=url, json=query_body.dict(), params=params, headers=headers) as resp:
                if resp.status == 200:
                    resp = await resp.json()
                    return {"documents": resp["documents"][0:query_body.max_results],
                            "tableName": table
                            }

                await raise_exception_from_response(resp, url=url)


class LocalTablesBody(BaseModel):
    folder: str


class LocalTable(BaseModel):
    keyspace: str
    name: str


class LocalTablesResponse(BaseModel):
    tables: List[LocalTable]


@router.post("/local-tables", summary="list docdb tables in a local folder")
async def local_tables(
        body: LocalTablesBody
        ):
    paths_data = glob.glob(f'{body.folder}/**/data.json', recursive=True)
    tables = [LocalTable(keyspace=path.split('/')[-3], name=path.split('/')[-2]) for path in paths_data]
    return LocalTablesResponse(tables=tables)


class SyncLocalTableBody(BaseModel):
    folder: str
    operationId: str
    tables: List[LocalTable]


def chunk(from_list: List[Any], chunk_size: int) -> List[List[Any]]:
    n = chunk_size
    final = [from_list[i * n:(i + 1) * n] for i in range((len(from_list) + n - 1) // n)]
    return final


@router.post("/{namespace}/sync-local-tables", summary="synchronize a provided list of local tables")
async def sync_local_tables(
        request: Request,
        namespace: str,
        body: SyncLocalTableBody,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    context = Context(
        request=request,
        config=config,
        web_socket=WebSocketsStore.logs
        )
    channel_ws = WebSocketsStore.ws

    docdb = next(p for p in config.deployment_configuration.packages
                 if p.name == DocDb.name and p.namespace == namespace)

    def get_documents(folder_path: Path):
        return parse_json(folder_path / 'data.json')['documents']

    async def export_document(http_session: ClientSession, keyspace: str, table: str, document: Mapping[str, any]):
        url = f"http://127.0.0.1:{docdb.docdb_port_fwd}/api/v0-alpha1/{keyspace}/{table}/document"
        async with await http_session.post(url=url, json=document, params=params, headers=headers) as resp:
            if resp.status == 201:
                return
            await raise_exception_from_response(resp, url=url)

    async with context.start(
            action=f"Synchronize local tables",
            json={"namespace": namespace, "tables": body.json(), "folder": body.folder}
            ) as ctx:
        await channel_ws.send_json({
            "topic": "Docdb.SyncLocalData",
            "operationId": body.operationId,
            "package": {"name": docdb.name, "namespace": docdb.namespace},
            "progress": 0
            })

        access_token = await config.get_client_credentials(
            client_id="youwol-dev",
            scope="email profile youwol_dev",
            context=ctx
            )
        headers = {"authorization": f"Bearer {access_token}"}
        params = {"owner": "/youwol-users"}
        all_documents = [(keyspace, table, doc)
                         for keyspace in {t.keyspace for t in body.tables}
                         for table in {t.name for t in body.tables if t.keyspace == keyspace}
                         for doc in get_documents(Path(body.folder) / keyspace / table)
                         ]
        batches = chunk(all_documents, 5)
        async with get_aiohttp_session() as session:
            for index, batch in enumerate(batches):
                await asyncio.gather(
                    ctx.info(text=f'scylla => proceed batch {index}/{len(batches)}', json=batch),
                    channel_ws.send_json({
                        "topic": "Docdb.SyncLocalData",
                        "operationId": body.operationId,
                        "package": {"name": docdb.name, "namespace": docdb.namespace},
                        "progress": index/len(batches)
                        }),
                    *[export_document(session, keyspace, table, doc) for keyspace, table, doc in batch]
                    )
        await channel_ws.send_json({
            "topic": "Docdb.SyncLocalData",
            "operationId": body.operationId,
            "package": {"name": docdb.name, "namespace": docdb.namespace},
            "progress": 1
            })
        return {}
