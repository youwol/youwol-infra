from typing import Optional, List, Any
from pydantic import BaseModel

from youwol_infra.deployment_models import Package


class ClusterInfo(BaseModel):
    access_token: str
    nodes: List[Any] # V1NodeStatus
    api_gateway_ip: Optional[str]
    k8s_api_proxy: str


class General(BaseModel):
    contextName: str
    proxyPort: int
    openIdHost: str


class DeploymentConfiguration(BaseModel):
    general: General
    packages: List[Any]
