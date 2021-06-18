import subprocess
from pathlib import Path
from signal import SIGTERM
from typing import List, Dict, Optional, Union

import yaml
from kubernetes.client import V1Namespace, V1Service, ExtensionsV1beta1Api, ExtensionsV1beta1Ingress
from psutil import process_iter

from .utils import exec_command, to_json_response, get_port_number
from kubernetes import client

from ..context import Context


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


async def k8s_get_service(namespace: str, name: str) -> Optional[V1Service]:
    services = client.CoreV1Api().list_namespaced_service(namespace).items
    service = next((s for s in services if s.metadata.name == name), None)
    return service


async def k8s_pod_exec(pod_name: str, namespace: str, commands: List[str], context: Context = None):

    for cmd in commands:
        full = f'kubectl exec -i  {pod_name} -n {namespace} -- bash -c "{cmd}"'
        context and await context.info(full)
        await exec_command(full, context=context)


def kill_k8s_proxy(port: int):
    for proc in process_iter():
        try:
            for conns in proc.connections(kind='inet'):
                if conns.laddr.port == port:
                    proc.send_signal(SIGTERM)  # or SIGKILL
        except:
            pass


async def k8s_port_forward(namespace: str, service_name: str, target_port: Optional[Union[str, int]],
                           local_port: int, context: Context):

    service = await k8s_get_service(namespace=namespace, name=service_name)
    ports = service.spec.ports

    port_number = ports[0].target_port

    if isinstance(target_port, int):
        port_number = ports[target_port].target_port
    if isinstance(target_port, str):
        port_number = next(p for p in ports if p.name == target_port).target_port

    cmd = f"kubectl port-forward -n {namespace} service/{service_name} {local_port}:{port_number}"
    kill_k8s_proxy(local_port)
    print(cmd)
    # await context.info(text=cmd, json=to_json_response({service_name: service.to_dict()}))
    subprocess.Popen(cmd, shell=True)


async def k8s_get_ingress(namespace: str, name: str) -> Optional[ExtensionsV1beta1Ingress]:
    ingresses = ExtensionsV1beta1Api().list_namespaced_ingress(namespace=namespace)
    ingress = next((i for i in ingresses.items if i.metadata.name == name), None)
    return ingress

