import traceback
import uuid
from contextlib import asynccontextmanager
from enum import Enum


from typing import Union, NamedTuple, Any, List

from pydantic import BaseModel, Json
from starlette.requests import Request
from starlette.websockets import WebSocket

from youwol_infra.web_sockets import WebSocketsStore
from youwol_utils import JSON


YouwolConfiguration = "youwol.configuration.youwol_configuration"


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ActionStep(Enum):
    STARTED = "STARTED"
    PREPARATION = "PREPARATION"
    STATUS = "STATUS"
    RUNNING = "RUNNING"
    PACKAGING = "PACKAGING"
    DONE = "DONE"


class Action(Enum):
    INSTALL = "INSTALL"
    CONF = "CONF"
    SYNC_USER = "SYNC_USER"
    BUILD = "BUILD"
    TEST = "TEST"
    CDN = "CDN"
    SYNC = "SYNC"
    SERVE = "SERVE"
    WATCH = "WATCH"


class MessageWebSocket(BaseModel):
    action: str
    level: str
    step: str
    target: str
    content: Union[Json, str]


class ActionException(Exception):
    def __init__(self, action: str, message: str):
        self.action = action
        self.message = message
        super().__init__(self.message)


class UserCodeException(Exception):
    def __init__(self, message: str, tb: Any):
        self.traceback = tb
        self.message = message
        super().__init__(self.message)


async def log(
        level: LogLevel,
        text: Union[Json, str],
        json: JSON = None,
        context_id: List[str] = None,
        ):
    if not  WebSocketsStore.logs:
        return
    web_socket = WebSocketsStore.logs
    message = {
        "level": level.name,
        "text": text,
        "json": json,
        "contextId": context_id or []
        }
    web_socket and await web_socket.send_json(message)


class Context(NamedTuple):

    web_socket: WebSocket
    config: YouwolConfiguration
    request: Request = None
    target: Union[str, None] = None
    action: Union[str, None] = None
    path: List[str] = [str(uuid.uuid4())]

    def with_target(self, name: str) -> 'Context':
        return Context(web_socket=self.web_socket, config=self.config, action=self.action, target=name)

    def with_action(self, action: str) -> 'Context':
        return Context(web_socket=self.web_socket, config=self.config, target=self.target, action=action)

    @asynccontextmanager
    async def start(self, action: str, json: JSON = None):
        ctx = Context(web_socket=self.web_socket, config=self.config, target=self.target, action=action,
                      path=self.path+[str(uuid.uuid4())])
        try:
            await ctx.info(text=f"<i class='fas fa-play mr-2'> </i> {action} started", json=json)
            yield ctx
        except UserCodeException as _:
            await ctx.abort(text=f"Exception during {action} while executing custom code")
            traceback.print_exc()
        except ActionException as e:
            await ctx.abort(text=f"Exception during {action}: {e.message}")
            traceback.print_exc()
        except Exception as e:
            await ctx.abort(text=f"Exception during {action}", json={"error": str(e)})
            traceback.print_exc()
            raise e
        else:
            await ctx.info(text=f"<i class='fas fa-flag-checkered mr-2'> </i> {action} done")

    async def debug(self, text: str, json: JSON = None):
        await log(level=LogLevel.DEBUG, text=text, json=json, context_id=self.path)

    async def info(self, text: str, json: JSON = None):
        await log(level=LogLevel.INFO, text=text, json=json, context_id=self.path)

    async def error(self, text: str, json: JSON = None):
        await log(level=LogLevel.ERROR, text=text, json=json, context_id=self.path)

    async def abort(self, text: str, json: JSON = None):
        await log(level=LogLevel.ERROR, text=text, json=json, context_id=self.path)
