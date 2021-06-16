from dataclasses import dataclass

from starlette.websockets import WebSocket, WebSocketDisconnect

from youwol_utils import log_info


@dataclass(frozen=False)
class WebSocketsStore:

    environment: WebSocket
    logs: WebSocket
    k8s_dashboard: WebSocket


async def start_web_socket(ws: WebSocket):
    while True:
        try:
            _ = await ws.receive_text()
        except WebSocketDisconnect:
            log_info(f'{ws.scope["client"]} - "WebSocket {ws.scope["path"]}" [disconnected]')
            break
