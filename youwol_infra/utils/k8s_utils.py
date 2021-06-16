from pathlib import Path
from typing import List, Dict, Optional

import yaml
from kubernetes.client import V1Namespace, V1Secret, V1ServiceList, V1Service

from .utils import exec_command
from kubernetes import client


def k8s_access_token():
    return client.CoreV1Api().api_client.configuration.api_key['authorization'].strip('Bearer').strip()


def k8s_namespaces() -> List[str]:
    namespaces = client.CoreV1Api().list_namespace()
    names = [n.metadata.name for n in namespaces.items]
    return names


def k8s_secrets(namespace: str) -> List[str]:
    secrets = client.CoreV1Api().list_namespaced_secret(namespace)
    names = [n.metadata.name for n in secrets.items]
    return names


def k8s_create_secret(namespace: str, file_path: Path):
    with open(file_path) as f:
        data = yaml.safe_load(f)
        client.CoreV1Api().create_namespaced_secret(namespace=namespace, body=data)


def k8s_create_secrets_if_needed(namespace: str, secrets: Dict[str, Path]):
    existing = k8s_secrets(namespace=namespace)
    needed = [k for k in secrets.keys() if k not in existing]
    for name in needed:
        k8s_create_secret(namespace=namespace, file_path=secrets[name])


def k8s_create_namespace(name: str):
    client.CoreV1Api().create_namespace(body=V1Namespace(metadata=dict(name=name)))


def k8s_get_service(namespace: str, name: str) -> Optional[V1Service]:
    services = client.CoreV1Api().list_namespaced_service(namespace).items
    service = next( (s for s in services if s.metadata.name == name), None)
    return service


async def k8s_pod_exec(pod_name: str, namespace: str, commands: List[str]):

    for cmd in commands:
        full = f'kubectl exec -i  {pod_name} -n {namespace} -- bash -c "{cmd}"'
        print(full)
        await exec_command(full)

