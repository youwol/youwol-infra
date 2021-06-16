from enum import Enum
from typing import Optional, List, Any

from kubernetes.client import V1NodeStatus
from pydantic import BaseModel


class ClusterInfo(BaseModel):
    access_token: str
    nodes: List[Any] # V1NodeStatus
    api_gateway_ip: Optional[str]
    k8s_api_proxy: str


class General(BaseModel):
    contextName: str
    proxyPort: int


class DeploymentConfiguration(BaseModel):
    general: General
