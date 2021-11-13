import asyncio
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
from youwol_infra.utils.k8s_utils import k8s_create_secrets_if_needed
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore

router = APIRouter()


class Status(StatusBase):
    pass


@dataclass
class Storage(HelmPackage):

    name: str = "storage"
    namespace: str = "prod"
    icon: str = "/api/youwol-infra/storage/icon"

    chart_folder: Path = Configuration.services_folder / "storage" / "chart"
    with_values: dict = field(default_factory=lambda: {})


async def send_status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration
        ):

    storage = next(p for p in config.deployment_configuration.packages
                   if p.name == Storage.name and p.namespace == namespace)

    is_installed = await storage.is_installed()
    if not is_installed:
        resp = Status(
            installed=is_installed,
            package=storage,
            sanity=Sanity.SANE if is_installed else None,
            pending=False
            )
        await WebSocketsStore.ws.send_json(to_json_response(resp))
        return

    resp = Status(
        installed=is_installed,
        package=storage,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    await WebSocketsStore.ws.send_json(to_json_response(resp))


@router.get("/icon")
async def icon():
    path = Path(__file__).parent / 'storage.png'
    return FileResponse(path)


@router.get("/{namespace}/status", summary="trigger fetching status of Storage component")
async def status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    asyncio.ensure_future(send_status(request=request, namespace=namespace, config=config))


@router.post("/{namespace}/install", summary="trigger install of Storage component")
async def install(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await install_pack(
        request=request,
        config=config,
        name='storage',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )


@router.post("/{namespace}/upgrade", summary="trigger upgrade of Storage component")
async def upgrade(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await upgrade_pack(
        request=request,
        config=config,
        name='storage',
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )


"""

Some piece of code saved for latter use if auto-sync w/ local storage is needed

@router.post("/{namespace}/sync-local-buckets", summary="synchronize a provided list of local bucket")
async def sync_local_buckets(
        request: Request,
        namespace: str,
        body: SyncLocalTableBody,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
        
    async def export_file(bucket: str, bucket_path: Path, file_path: Path):
        storage_client = await config.get_storage_client(bucket_name=bucket, context=context)
        name = file_path.relative_to(bucket_path)
        await storage_client.post_object(path=name, content=file_path.read_bytes(), content_type="",
                                         owner='/youwol-users')


    async with context.start(action=f"Export databases") as ctx:

        await ctx.info(step=ActionStep.RUNNING, content=f"Synchronise minio's documents")

        buckets_path = [config.pathsBook.local_storage / name  for name in targets_databases]

        all_files = [(bucket, bucket_path, Path(dirpath) / filename)
                      for bucket, bucket_path in zip(targets_databases, buckets_path)
                      for (dirpath, dirnames, filenames) in os.walk(bucket_path / 'youwol-users')
                      for filename in filenames if isfile(Path(dirpath) / filename)]
        
         for index, (bucket, bucket_path, file_path) in enumerate(all_files[0:5]):
             await ctx.info(step=ActionStep.RUNNING, content=f'storage => proceed file {index}/{len(all_files)}')
             await export_file(bucket, bucket_path, file_path)
"""