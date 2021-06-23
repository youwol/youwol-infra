from dataclasses import dataclass, field
from pathlib import Path

from youwol_infra.deployment_models import HelmPackage
from youwol_infra.service_configuration import Configuration


@dataclass
class Prometheus(HelmPackage):

    postgre_sql_pod_name: str = None
    name: str = "prometheus"
    namespace: str = "infra"
    chart_folder: Path = Configuration.charts_folder / name
    with_values: dict = field(default_factory=lambda: {
                   "server": {
                       "persistentVolume": {
                           "storageClass": "standard",
                           "size": "1Gi"
                           }
                       },
                   "pushgateway": {
                       "enabled": "false"
                       },
                   "alertmanager": {
                       "enabled": "false"
                       }
                   })
