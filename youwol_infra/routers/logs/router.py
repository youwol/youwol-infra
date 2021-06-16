import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, WebSocket, Depends
from pydantic import BaseModel
from starlette.requests import Request

from youwol_infra.context import Context, ActionStep, log, LogLevel
from youwol_infra.dynamic_configuration import dynamic_config, DynamicConfiguration
from youwol_infra.utils.utils import to_json_response
from youwol_infra.web_sockets import WebSocketsStore, start_web_socket

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    WebSocketsStore.logs = ws

    await log(level=LogLevel.INFO, text="Hello YouWol")

    await start_web_socket(ws)
