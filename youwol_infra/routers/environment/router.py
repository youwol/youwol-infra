import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, WebSocket, Depends
from pydantic import BaseModel
from starlette.requests import Request

from youwol_infra.context import Context, ActionStep
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration, DynamicConfigurationFactory
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore, start_web_socket

router = APIRouter()


class FolderContentResp(BaseModel):
    configurations: List[str]
    files: List[str]
    folders: List[str]


class FolderContentBody(BaseModel):
    path: List[str]


class SwitchConfigurationBody(BaseModel):
    path: List[str]


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    WebSocketsStore.environment = ws
    config = await dynamic_config()
    await send_status(configuration=config)
    await start_web_socket(ws)


async def send_status(configuration: DynamicConfiguration):

    await WebSocketsStore.environment.send_json(to_json_response(configuration))


@router.post("/switch-configuration",
             summary="switch configuration")
async def switch_configuration(
        request: Request,
        body: SwitchConfigurationBody,
        config: DynamicConfiguration = Depends(dynamic_config)
        ):

    context = Context(
        request=request,
        config=config,
        web_socket=WebSocketsStore.logs
        )
    await DynamicConfigurationFactory.switch(path='/'.join(body.path), context=context)
    config = await dynamic_config()
    await send_status(configuration=config)
    #load_status = await YouwolConfigurationFactory.switch('/'.join(body.path), context)
    return {}


@router.post("/folder-content",
             response_model=FolderContentResp,
             summary="return the items in target folder")
async def folder_content(
        request: Request,
        body: FolderContentBody
        ):
    def is_conf_file(filename: str):
        if '.py' not in filename:
            return False
        content = (path / filename).read_text()
        if "async def configuration" in content and "DeploymentConfiguration" in content:
            return True
        return False
    path = Path('/'.join(body.path))
    items = os.listdir(path)
    configurations = [item for item in items if os.path.isfile(path / item) and is_conf_file(item)]
    return FolderContentResp(
        configurations=configurations,
        files=[item for item in items if os.path.isfile(path / item) and item not in configurations],
        folders=[item for item in items if os.path.isdir(path / item)])

