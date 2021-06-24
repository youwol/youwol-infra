from youwol_infra.deployment_configuration import DeploymentConfiguration, General
from youwol_infra.routers.docdb.router import DocDb
from youwol_infra.routers.k8s_dashboard.router import K8sDashboard
from youwol_infra.routers.kong.router import Kong
from youwol_infra.routers.minio.router import Minio
from youwol_infra.routers.postgre_sql.router import PostgreSQL
from youwol_infra.routers.redis.router import Redis
from youwol_infra.routers.scylla.router import Scylla
from youwol_infra.routers.storage.router import Storage

minio_hosts = {
    "infra": "minio.youwol.com",
    "dev": "minio.dev.platform.youwol.com",
    "test": "minio.test.platform.youwol.com",
    "staging": "minio.staging.platform.youwol.com",
    "demo": "minio.staging.demo.youwol.com",
    "prod": "minio.prod.platform.youwol.com",
    "cdn": "minio.cdn.youwol.com",
    }


def namespace_charts(namespace: str):

    return [
        DocDb(namespace=namespace),
        Storage(namespace=namespace),
        Minio(
            namespace=namespace,
            with_values={
                "ingress": {
                    "hosts[0]": minio_hosts[namespace]
                    }
                }
            )
        ]


infra_packages = [
    K8sDashboard(),
    PostgreSQL(),
    Kong(),
    Minio(
        namespace='infra',
        with_values={
            "ingress": {
                "hosts[0]": minio_hosts['infra']
                }
            }
        ),
    Scylla(),
    Redis()
    ]

dev_packages = namespace_charts('dev')
prod_packages = namespace_charts('prod')
cdn_packages = [
        DocDb(namespace='cdn'),
        Storage(namespace='cdn'),
        Minio(
            namespace='cdn',
            with_values={
                "ingress": {
                    "hosts[0]": minio_hosts['cdn']
                    }
                }
            )
        ]


async def configuration():

    return DeploymentConfiguration(
        general=General(
            contextName="juju-context",
            proxyPort=8002
            ),
        packages=infra_packages + dev_packages + prod_packages + cdn_packages
        )
