from youwol_infra.deployment_configuration import DeploymentConfiguration, General


async def configuration():

    return DeploymentConfiguration(
        general=General(
            contextName="gke_thematic-grove-252706_europe-west1_gc-tricot",
            proxyPort=8001
            )
        )
