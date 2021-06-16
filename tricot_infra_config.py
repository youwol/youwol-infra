from youwol_infra.deployment_configuration import DeploymentConfiguration, General


async def configuration():

    return DeploymentConfiguration(
        general=General(
            contextName="juju-context",
            proxyPort=8002
            )
        )
