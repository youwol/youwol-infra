from typing import List

from k8s_utils import k8s_pod_exec


async def sql_exec_commands(pod_name: str, commands: List[str]):

    await k8s_pod_exec(
        pod_name=pod_name,
        namespace='infra',
        commands=[f"export PGPASSWORD=postgres && psql -U postgres -c '{cmd}'"
                  for cmd in commands
                  ]
        )
