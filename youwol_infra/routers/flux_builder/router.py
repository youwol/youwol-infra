import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Depends
from starlette.requests import Request
from starlette.responses import FileResponse

from youwol_infra.deployment_models import HelmPackage
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.routers.common import StatusBase, Sanity, HelmValues, install_pack, upgrade_pack
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore

router = APIRouter()


class Status(StatusBase):
    pass


@dataclass
class FluxBuilder(HelmPackage):

    name: str = "flux-builder"
    namespace: str = "prod"
    icon: str = f"/api/youwol-infra/{name}/icon"

    chart_folder: Path = Configuration.services_folder / name / "chart"
    with_values: dict = field(default_factory=lambda: {})


async def send_status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration
        ):

    flux = next(p for p in config.deployment_configuration.packages
                if p.name == FluxBuilder.name and p.namespace == namespace)

    is_installed = await flux.is_installed()
    if not is_installed:
        resp = Status(
            installed=is_installed,
            package=flux,
            sanity=Sanity.SANE if is_installed else None,
            pending=False
            )
        await WebSocketsStore.ws.send_json(to_json_response(resp))
        return

    resp = Status(
        installed=is_installed,
        package=flux,
        sanity=Sanity.SANE if is_installed else None,
        pending=False
        )
    await WebSocketsStore.ws.send_json(to_json_response(resp))


@router.get("/icon")
async def icon():
    path = Path(__file__).parent / 'flux.png'
    return FileResponse(path)


@router.get("/{namespace}/status", summary="trigger fetching status of Flux-builder component")
async def status(
        request: Request,
        namespace: str,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):
    asyncio.ensure_future(send_status(request=request, namespace=namespace, config=config))


@router.post("/{namespace}/install", summary="trigger install of Flux-builder component")
async def install(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await install_pack(
        request=request,
        config=config,
        name=FluxBuilder.name,
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )


@router.post("/{namespace}/upgrade", summary="trigger upgrade of Flux-builder component")
async def upgrade(
        request: Request,
        namespace: str,
        body: HelmValues,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    await upgrade_pack(
        request=request,
        config=config,
        name=FluxBuilder.name,
        namespace=namespace,
        helm_values=body.values,
        channel_ws=WebSocketsStore.ws,
        finally_action=lambda: status(request, namespace, config)
        )
