from pathlib import Path

from youwol_infra.deployment_configuration import DeploymentConfiguration, General
from youwol_infra.routers.assets_backend.router import AssetsBackend
from youwol_infra.routers.assets_gateway.router import AssetsGateway
from youwol_infra.routers.cdn.router import CDN
from youwol_infra.routers.docdb.router import DocDb
from youwol_infra.routers.flux_backend.router import FluxBackend
from youwol_infra.routers.flux_builder.router import FluxBuilder
from youwol_infra.routers.flux_runner.router import FluxRunner
from youwol_infra.routers.front_api.router import FrontApi
from youwol_infra.routers.k8s_dashboard.router import K8sDashboard
from youwol_infra.routers.keycloak.router import Keycloak
from youwol_infra.routers.kong.router import Kong
from youwol_infra.routers.minio.router import Minio
from youwol_infra.routers.network.router import Network
from youwol_infra.routers.postgre_sql.router import PostgreSQL
from youwol_infra.routers.redis.router import Redis
from youwol_infra.routers.scylla.router import Scylla
from youwol_infra.routers.storage.router import Storage
from youwol_infra.routers.treedb_backend.router import TreedbBackend
from youwol_infra.routers.workspace_explorer.router import WorkspaceExplorer

platform_folder: Path = Path.home() / 'Projects' / 'platform'
charts_folder: Path = platform_folder / 'deployment' / 'charts'
services_folder: Path = platform_folder / 'services'
secrets_folder: Path = platform_folder / "secrets" / "gc"

open_id_host = "gc.auth.youwol.com"


def get_ingress(developers_only: bool, host: str = "gc.platform.youwol.com"):
    return {
        "hosts[0].host": host,
        "annotations": {
            "konghq.com/plugins": "oidc-dev" if developers_only else "oidc-user"
            }
        }


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
         },
    acme_hosts=[
        open_id_host,
        "gc.cdn.youwol.com",
        "gc.platform.youwol.com"
        ],
    secrets={
        "gitlab-docker": secrets_folder / "gitlab-docker.yaml",
        "oidc": secrets_folder / "kong" / "oidc.yaml"
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

keycloak = Keycloak(
    with_values={
        "ingress": {
            "rules[0].host": open_id_host
            },
        "extraenv[4].value": f"https://{open_id_host}/auth"
        })

docdb = DocDb(
    namespace='prod',
    with_values={
        "ingress": get_ingress(developers_only=True),
        "keycloak": {
            "host": f"https://{open_id_host}"
            },
        "image": {
            "repository": "registry.gitlab.com/youwol/platform/docdb",
            "tag": "0.3.42"
            },
        "imagePullSecrets[0].name": "gitlab-docker"
        },
    secrets={
        "gitlab-docker": secrets_folder / "gitlab" / "gitlab-docker.yaml",
        "keycloak": secrets_folder / "keycloak" / "admin.yaml"
        }
    )

storage = Storage(
    namespace='prod',
    with_values={
        "ingress": get_ingress(developers_only=True),
        "keycloak": {
            "host": f"https://{open_id_host}"
            },
        "image": {
            "repository": "registry.gitlab.com/youwol/platform/storage",
            "tag": "0.2.13"
            },
        "imagePullSecrets[0].name": "gitlab-docker"
        },
    secrets={
        "gitlab-docker": secrets_folder / "gitlab" / "gitlab-docker.yaml",
        "keycloak": secrets_folder / "keycloak" / "admin.yaml"
        }
    )

cdn = CDN(
    namespace='prod',
    with_values={
        "ingress": get_ingress(developers_only=True, host="gc.cdn.youwol.com"),
        "image": {
            "repository": "registry.gitlab.com/youwol/platform/cdn-backend",
            "tag": "0.2.11"
            },
        "imagePullSecrets[0].name": "gitlab-docker",
        "keycloak": {
            "host": open_id_host
            }
        },
    secrets={
        "youwol-auth":  secrets_folder / "keycloak" / "youwol-auth.yaml",
        "gitlab-docker": secrets_folder / "gitlab" / "gitlab-docker.yaml"
        }
    )


treedb = TreedbBackend(
    namespace='prod',
    with_values={
        "image": {
            "repository": "registry.gitlab.com/youwol/platform/treedb-backend",
            "tag": "0.3.7"
            },
        "imagePullSecrets[0].name": "gitlab-docker",
        "ingress": get_ingress(developers_only=True),
        "keycloak": {
            "host": open_id_host
            },
        },
    secrets={
        "youwol-auth": secrets_folder / "keycloak" / "youwol-auth.yaml",
        "gitlab-docker": secrets_folder / "gitlab" / "gitlab-docker.yaml"
        }
    )

assets_backend = AssetsBackend(
    namespace='prod',
    with_values={
        "image": {
            "repository": "registry.gitlab.com/youwol/platform/assets-backend",
            "tag": "0.3.7"
            },
        "imagePullSecrets[0].name": "gitlab-docker",
        "ingress": get_ingress(developers_only=True),
        "keycloak": {
            "host": open_id_host
            },
        },
    secrets={
        "youwol-auth": secrets_folder / "keycloak" / "youwol-auth.yaml",
        "gitlab-docker": secrets_folder / "gitlab" / "gitlab-docker.yaml"
        }
    )

flux_backend = FluxBackend(
    namespace='prod',
    with_values={
        "image": {
            "repository": "registry.gitlab.com/youwol/platform/flux-backend",
            "tag": "0.1.8"
            },
        "imagePullSecrets[0].name": "gitlab-docker",
        "ingress": get_ingress(developers_only=True),
        "keycloak": {
            "host": open_id_host
            },
        },
    secrets={
        "youwol-auth": secrets_folder / "keycloak" / "youwol-auth.yaml",
        "gitlab-docker": secrets_folder / "gitlab" / "gitlab-docker.yaml"
        }
    )

assets_gateway = AssetsGateway(
    namespace='prod',
    with_values={
        "image": {
            "repository": "registry.gitlab.com/youwol/platform/assets-gateway",
            "tag": "1.1.25"
            },
        "imagePullSecrets[0].name": "gitlab-docker",
        "ingress": get_ingress(developers_only=False),
        "keycloak": {
            "host": open_id_host
            },
        },
    secrets={
        "youwol-auth": secrets_folder / "keycloak" / "youwol-auth.yaml",
        "gitlab-docker": secrets_folder / "gitlab" / "gitlab-docker.yaml"
        }
    )


front_api = FrontApi(
    namespace='prod',
    with_values={
        "image": {
            "repository": "registry.gitlab.com/youwol/platform/front-api",
            "tag": "0.1.8"
            },
        "imagePullSecrets[0].name": "gitlab-docker",
        "ingress": {"hosts[0].host": "gc.platform.youwol.com"}
        },
    secrets={
        "gitlab-docker": secrets_folder / "gitlab" / "gitlab-docker.yaml"
        }
    )

workspace_explorer = WorkspaceExplorer(
    namespace='prod',
    with_values={
        "image": {
            "repository": "registry.gitlab.com/youwol/platform/workspace-explorer",
            "tag": "0.0.3"
            },
        "imagePullSecrets[0].name": "gitlab-docker",
        "ingress": {"hosts[0].host": "gc.platform.youwol.com"}
        },
    secrets={
        "gitlab-docker": secrets_folder / "gitlab" / "gitlab-docker.yaml"
        }
    )

flux_builder = FluxBuilder(
    namespace='prod',
    values_filename='values-gc.yaml',
    with_values={
        "image": {
            "tag": "0.0.6"
            }
        },
    secrets={
        "gitlab-docker": secrets_folder / "gitlab" / "gitlab-docker.yaml"
        }
    )

flux_runner = FluxRunner(
    namespace='prod',
    values_filename='values-gc.yaml',
    with_values={
        "image": {
            "tag": "0.0.2"

network = Network(
    namespace='prod',
    values_filename='values-gc.yaml',
    with_values={
        "image": {
            "tag": versions["Network"]
            }
        },
    secrets={
        "gitlab-docker": secrets_folder / "gitlab" / "gitlab-docker.yaml"
        }
    )


async def configuration():

    return DeploymentConfiguration(
        general=General(
            contextName="gke_thematic-grove-252706_europe-west1_gc-tricot",
            proxyPort=8001,
            openIdHost=open_id_host,
            secretsFolder=secrets_folder
            ),
        packages=[
            k8s_dashboard,
            postgre_sql,
            kong,
            minio,
            scylla,
            redis,
            keycloak,
            docdb,
            storage,
            cdn,
            treedb,
            assets_backend,
            flux_backend,
            assets_gateway,
            front_api,
            workspace_explorer,
            flux_builder,
            flux_runner,
            network
            ]
        )
