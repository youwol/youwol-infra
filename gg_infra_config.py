from youwol_infra.deployment_configuration import DeploymentConfiguration, General
from youwol_infra.routers.docdb.router import DocDb
from youwol_infra.routers.k8s_dashboard.router import K8sDashboard
from youwol_infra.routers.kong.router import Kong
from youwol_infra.routers.minio.router import Minio
from youwol_infra.routers.postgre_sql.router import PostgreSQL
from youwol_infra.routers.redis.router import Redis
from youwol_infra.routers.scylla.router import Scylla
from youwol_infra.routers.storage.router import Storage

k8s_dashboard = K8sDashboard()

postgre_sql = PostgreSQL(
    with_values={
        "persistence": {
            "storageClass": "standard",
            "size": "2Gi"
            }
        }
    )

kong = Kong(
    with_values={
         "proxy": {
             "loadBalancerIP": "104.199.0.92"
             }
         }
    )

minio = Minio(
    namespace='prod',
    with_values={
        "replicas": 1,
        "persistence": {
            "storageClass": "standard",
            "size": "1Gi"
            },
        "ingress": {
            "enabled": "true",
            "hosts[0]": f"minio.gc.platform.youwol.com"
            }
        })

scylla = Scylla(
    with_values={
            "persistence": {
                "enabled": "false",
                "storageClass": "standard",
                "size": "10Gi"
                }
            }
    )

redis = Redis()

docdb = DocDb(
    namespace='prod',
    with_values={
        "ingress": {
            "hosts[0].host": f"gc.platform.youwol.com"
            },
        "image": {
            "tag": "0.3.40-master"
            }
        })

storage = Storage(
    namespace='prod',
    with_values={
        "ingress": {
            "hosts[0].host": f"gc.platform.youwol.com"
            },
        "image": {
            "tag": "0.2.12-master"
            }
        })


async def configuration():

    return DeploymentConfiguration(
        general=General(
            contextName="gke_thematic-grove-252706_europe-west1_gc-tricot",
            proxyPort=8001
            ),
        packages=[
            k8s_dashboard,
            postgre_sql,
            kong,
            minio,
            scylla,
            redis,
            docdb,
            storage
            ]
        )
