from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from youwol_infra.context import Context
from youwol_infra.deployment_models import HelmPackage
from youwol_infra.service_configuration import Configuration
from youwol_infra.utils.sql_utils import sql_exec_commands


@dataclass
class Keycloak(HelmPackage):

    postgre_sql_pod_name: str = "postgresql-postgresql-0"
    name: str = "auth"
    namespace: str = "infra"

    chart_folder: Path = Configuration.charts_folder / "keycloak"
    with_values: dict = field(default_factory=lambda: {})

    postgres_commands: List[str] = field(default_factory=lambda: [
        "CREATE USER keycloak IN GROUP youwol PASSWORD \$\$postgres\$\$;",
        "CREATE DATABASE keycloak;",
        "GRANT ALL PRIVILEGES ON DATABASE keycloak TO keycloak;"
        ])

    async def install(self, context: Context = None):
        await sql_exec_commands(
            pod_name=self.postgre_sql_pod_name,
            commands=self.postgres_commands
            )
        await super().install(context)
