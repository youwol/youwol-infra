import pprint
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Union, Optional, NamedTuple, Dict, Any
import kubernetes as k8s
from pydantic import BaseModel, ValidationError
from urllib3.exceptions import NewConnectionError, ConnectTimeoutError, MaxRetryError

from youwol_infra.context import Context
from youwol_infra.deployment_configuration import DeploymentConfiguration, ClusterInfo
from youwol_infra.utils.k8s_utils import k8s_access_token, k8s_get_service, kill_k8s_proxy
from youwol_infra.service_configuration import get_service_config
from youwol_infra.utils.utils import parse_json, get_client_credentials


class DeadlinedCache(NamedTuple):

    value: any
    deadline: float
    dependencies: Dict[str, str]

    def is_valid(self, dependencies) -> bool:

        for k, v in self.dependencies.items():
            if k not in dependencies or dependencies[k] != v:
                return False
        margin = self.deadline - datetime.timestamp(datetime.now())
        return margin > 0


class DynamicConfiguration(BaseModel):

    config_filepath: Path
    deployment_configuration: DeploymentConfiguration
    cluster_info: Union[None, ClusterInfo]

    tokensCache: List[Any] = []

    async def get_client_credentials(self, client_id: str, scope: str, context: Context, use_cache=True):

        secret_path = self.deployment_configuration.general.secretsFolder / "keycloak" / (client_id+".json")
        openid_host = self.deployment_configuration.general.openIdHost
        dependencies = {
            "client_id": client_id,
            "secret_path": secret_path,
            "openid_host": openid_host,
            "type": "auth_token"
            }
        cached_token = next((c for c in self.tokensCache if c.is_valid(dependencies)), None)
        if use_cache and cached_token:
            return cached_token.value

        secrets = parse_json(secret_path)

        try:
            access_token = await get_client_credentials(
                client_id=secrets['clientId'],
                client_secret=secrets['clientSecret'],
                openid_host=openid_host,
                scope=scope
                )
        except Exception as e:
            raise RuntimeError(f"Can not authorize client {client_id} (using secret {str(secret_path)})" +
                               f". Got error: {e}")

        deadline = datetime.timestamp(datetime.now()) + 1 * 60 * 60 * 1000
        self.tokensCache.append(DeadlinedCache(value=access_token, deadline=deadline, dependencies=dependencies))

        await context.info(text="Client credentials retrieved",
                           json={"openIdHost": openid_host,
                                 "clientId": client_id,
                                 "access_token": access_token,
                                 "scope": scope
                                 }
                           )
        return access_token


class ErrorResponse(BaseModel):

    reason: str
    hints: List[str] = []


class Check(BaseModel):
    name: str
    status: Union[bool, ErrorResponse, None] = None


class ConfigurationLoadingStatus(BaseModel):

    path: str
    validated: bool = False
    checks: List[Check]


class DynamicConfigurationFactory:

    __cached_config: DynamicConfiguration = None

    @staticmethod
    async def get():
        cached = DynamicConfigurationFactory.__cached_config
        config = cached or await DynamicConfigurationFactory.init()

        return config

    @staticmethod
    async def init():
        path = (await get_service_config()).starting_config_path
        conf, status = await safe_load(path=path, context=None)
        if not conf:
            for check in status.checks:
                if isinstance(check.status, ErrorResponse):
                    pprint.pprint(check)
            # raise ConfigurationLoadingException(status)
            raise Exception(status)

        DynamicConfigurationFactory.__cached_config = conf
        return DynamicConfigurationFactory.__cached_config

    @staticmethod
    async def switch(path: Union[str, Path],
                     context: Context) -> ConfigurationLoadingStatus:

        async with context.start("Switch Configuration", json={"path": str(path)}) as ctx:
            path = Path(path)
            cached = DynamicConfigurationFactory.__cached_config
            kill_k8s_proxy(port=cached.deployment_configuration.general.proxyPort)

            conf, status = await safe_load(path=path, context=context)
            if not conf:
                errors = [c.dict() for c in status.checks if isinstance(c.status, ErrorResponse)]
                await ctx.abort(content='Failed to switch configuration',
                                json={
                                    "first error": next(e for e in errors),
                                    "errors": errors,
                                    "all checks": [c.dict() for c in status.checks]})
                return status
            await ctx.info(text='Switched to new conf. successful', json=status.dict())
            DynamicConfigurationFactory.__cached_config = conf
        return status


async def dynamic_config() -> DynamicConfiguration:
    return await DynamicConfigurationFactory.get()


class CheckConfPath(Check):
    name: str = "Configuration path exist?"


class CheckValidTextFile(Check):
    name: str = "Valid text file?"


class CheckValidPythonScript(Check):
    name: str = "Valid python script?"


class CheckValidConfigurationFunction(Check):
    name: str = "Configuration function valid?"


async def safe_load(path: Path, context: Optional[Context]) \
        -> (DynamicConfiguration, ConfigurationLoadingStatus):

    check_conf_path = CheckConfPath()
    check_valid_text = CheckValidTextFile()
    check_valid_python = CheckValidPythonScript()
    check_valid_conf_fct = CheckValidConfigurationFunction()

    def get_status(validated: bool = False):
        return ConfigurationLoadingStatus(
            path=str(path),
            validated=validated,
            checks=[
                check_conf_path,
                check_valid_text,
                check_valid_python,
                check_valid_conf_fct,
                ]
            )

    if not path.exists():
        check_conf_path.status = ErrorResponse(
            reason="The specified configuration path does not exist.",
            hints=[f"Double check the location '{str(path)}' do exist."]
            )
        return None, get_status()

    check_conf_path.status = True
    try:
        source = Path(path).read_text()
    except Exception as e:
        print(e)
        check_valid_text.status = ErrorResponse(
            reason="The specified configuration path is not a valid text file.",
            hints=[f"Double check the file at location '{str(path)}' is a valid text file."]
            )
        return None, get_status()

    check_valid_text.status = True

    try:
        scope = {}
        exec(source, scope)
    except SyntaxError as err:
        error_class = err.__class__.__name__
        detail = err.args[0]
        line_number = err.lineno
        check_valid_python.status = ErrorResponse(
            reason=f"There is a syntax error in the python file.",
            hints=[f"{error_class} at line {line_number}: {detail}"]
            )
        return None, get_status()
    except Exception as err:
        check_valid_python.status = format_unknown_error(
            reason=f"There was an exception parsing your python file.",
            error=err)
        return None, get_status()

    check_valid_python.status = True

    if 'configuration' not in scope:
        check_valid_conf_fct.status = ErrorResponse(
                reason=f"The configuration file need to define a 'configuration' function.",
                hints=[f"""Make sure the configuration file include a function with signature :
                'async def configuration(main_args: MainArguments)."""])
        return None, get_status()

    try:
        k8s_config: DeploymentConfiguration = await scope.get('configuration')()

        if not isinstance(k8s_config, DeploymentConfiguration):
            check_valid_conf_fct.status = ErrorResponse(
                reason=f"The function 'configuration' must return an instance of type 'UserConfiguration'",
                hints=[f"You can have a look at the default_config_yw.py located in 'py-youwol/system'"])
            return None, get_status()
    except ValidationError as err:

        check_valid_conf_fct.status = ErrorResponse(
            reason=f"Parsing the 'configuration' object to UserConfiguration failed.",
            hints=[f"{str(err)}"])
        return None, get_status()
    except TypeError as err:

        ex_type, ex, tb = sys.exc_info()
        traceback.print_tb(tb)
        check_valid_conf_fct.status = ErrorResponse(
            reason=f"Misused of configuration function",
            hints=[f"details: {str(err)}"])
        return None, get_status()
    except FileNotFoundError as err:

        check_valid_conf_fct.status = ErrorResponse(
            reason=f"File or directory not found: {err.filename}",
            hints=["Make sure the intended path is correct. "
                   "You may also want to create the directory in your config. file"])
        return None, get_status()
    except Exception as err:

        ex_type, ex, tb = sys.exc_info()
        traceback.print_tb(tb)
        check_valid_conf_fct.status = format_unknown_error(
                reason=f"There was an exception calling the 'configuration'.",
                error=err)
        return None, get_status()

    check_valid_conf_fct.status = True

    k8s.config.load_kube_config(
        config_file=str(Path.home() / '.kube' / 'config'),
        # when creating the cluster using the command line 'gcloud container cluster create' an
        # entry is added in the file k8s_config, the context name is provided in here
        context=k8s_config.general.contextName
        )
    start_k8s_proxy(port=k8s_config.general.proxyPort, context_name=k8s_config.general.contextName)
    cluster_info = await get_cluster_info(k8s_config)
    return (
        DynamicConfiguration(config_filepath=path, deployment_configuration=k8s_config,
                             cluster_info=cluster_info),
        get_status()
        )


def start_k8s_proxy(context_name: str, port: int):

    cmd = f"kubectl config use-context {context_name} && kubectl proxy --port={port}"
    print(cmd)
    subprocess.Popen(cmd, shell=True)


async def get_api_gateway_ip() -> Optional[str]:
    kong = await k8s_get_service(namespace='api_gateway', name='kong-kong-proxy')
    if not kong:
        return None
    return None


async def get_cluster_info(k8s_config: DeploymentConfiguration) -> Optional[ClusterInfo]:
    access_token = await k8s_access_token()

    try:
        nodes = k8s.client.CoreV1Api().list_node(_request_timeout=2)
        nodes = [n.status.to_dict() for n in nodes.items]
    except (NewConnectionError, ConnectTimeoutError, MaxRetryError):
        print("Failed to retrieve nodes, cluster up and running?")
        return None

    api_gateway_ip = await get_api_gateway_ip()

    return ClusterInfo(
        nodes=nodes,
        access_token=access_token,
        k8s_api_proxy=f"http://localhost:{k8s_config.general.proxyPort}",
        api_gateway_ip=api_gateway_ip
        )


def format_unknown_error(reason: str, error: Exception):

    detail = error.args[0]
    error_class = error.__class__.__name__
    cl, exc, tb = sys.exc_info()
    line_number = traceback.extract_tb(tb)[-1][1]
    return ErrorResponse(
        reason=reason,
        hints=[f"{error_class} at line {line_number}: {detail}"]
        )
