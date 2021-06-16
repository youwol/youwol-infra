from fastapi import FastAPI, APIRouter, Depends
import uvicorn
from starlette.responses import JSONResponse
from starlette.requests import Request

import routers.environment.router as environment
import routers.logs.router as logs
import routers.k8s_dashboard.router as k8s_dashboard
import routers.postgre_sql.router as postgre_sql
import routers.kong.router as kong

from youwol_infra.dynamic_configuration import dynamic_config
from youwol_infra.service_configuration import configuration, assert_python
from youwol_utils import YouWolException, log_error


app = FastAPI(
    title="YouWol Infrastructure API",
    openapi_prefix=configuration.open_api_prefix,
    dependencies=[Depends(dynamic_config)],
    root_path=f"/api/{configuration.service_name}")


web_socket = None


def get_web_socket():
    return web_socket


router = APIRouter()

app.include_router(environment.router, prefix=configuration.base_path+"/environment", tags=["environment"])
app.include_router(logs.router, prefix=configuration.base_path+"/logs", tags=["logs"])
app.include_router(k8s_dashboard.router, prefix=configuration.base_path+"/k8s-dashboard", tags=["K8s dashboard"])
app.include_router(postgre_sql.router, prefix=configuration.base_path+"/postgre-sql", tags=["Postgre SQL"])
app.include_router(kong.router, prefix=configuration.base_path+"/kong", tags=["Kong"])


@app.exception_handler(YouWolException)
async def youwol_exception_handler(request: Request, exc: YouWolException):

    log_error(f"{exc.detail}", exc.parameters)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": exc.exceptionType,
            "detail": f"{exc.detail}",
            "parameters": exc.parameters
            }
        )


@app.get(configuration.base_path + "/healthz")
async def healthz():
    return {"status": "youwol-infra ok"}


def main():
    assert_python()
    uvicorn.run(app, host="localhost", port=configuration.http_port)


if __name__ == "__main__":
    main()
