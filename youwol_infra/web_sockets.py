from dataclasses import dataclass

from starlette.websockets import WebSocket, WebSocketDisconnect

from youwol_utils import log_info


@dataclass(frozen=False)
class WebSocketsStore:

    environment: WebSocket = None
    logs: WebSocket = None
    k8s_dashboard: WebSocket = None
    postgre_sql: WebSocket = None
    kong: WebSocket = None
    minio: WebSocket = None


async def start_web_socket(ws: WebSocket):
    while True:
        try:
            _ = await ws.receive_text()
        except WebSocketDisconnect:
            log_info(f'{ws.scope["client"]} - "WebSocket {ws.scope["path"]}" [disconnected]')
            break
