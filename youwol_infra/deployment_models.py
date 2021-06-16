import functools
import itertools
import os
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from utils.helm_utils import helm_install, helm_list, helm_upgrade

from kubernetes import client, utils

from youwol_infra.context import Context


@dataclass
class Package:

    name: str
    namespace: str

    async def install(self, context: Context = None):
        pass

    async def upgrade(self, context: Context = None):
        pass

    async def is_installed(self):
        pass


@dataclass
class Deployment(Package):

    url: Optional[str]
    path: Optional[Path]

    async def install(self, context: Context = None):

        path_tmp = self.path if self.path else Path('.') / str(uuid.uuid4())
        if not self.path:
            context and context.info(text="Fetched remote deployment", json={"url": self.url})
            urllib.request.urlretrieve(
                self.url,
                path_tmp
                )
        try:
            utils.create_from_yaml(client.ApiClient(), str(path_tmp))
        finally:
            if not self.path:
                os.remove(path_tmp)


@dataclass
class HelmPackage(Package):

    chart_folder: Path
    with_values: dict

    async def install(self, context: Context = None):

        keys = HelmPackage.flatten_schema_values(self.with_values)
        args = functools.reduce(lambda acc, e: acc + f"--set {e[1:]} ", keys, "")
        await helm_install(
            release_name=self.name,
            namespace=self.namespace,
            values_file=self.chart_folder / 'values.yaml',
            chart_folder=Path(self.chart_folder),
            timeout=240,
            args=args,
            context=context)

    async def upgrade(self, context: Context = None):

        keys = HelmPackage.flatten_schema_values(self.with_values)
        args = functools.reduce(lambda acc, e: acc + f"--set {e[1:]} ", keys, "")
        await helm_upgrade(
            release_name=self.name,
            namespace=self.namespace,
            values_file=self.chart_folder / 'values.yaml',
            chart_folder=Path(self.chart_folder),
            timeout=240,
            args=args,
            context=context)

    async def is_installed(self):
        names = [r.name for r in helm_list(namespace=self.namespace)]
        return self.name in names

    @staticmethod
    def flatten_schema_values(dict_object: dict, prefix=""):
        r = []
        for k, v in dict_object.items():
            if isinstance(v, dict):
                r.append(HelmPackage.flatten_schema_values(v, prefix + "." + k))
            else:
                r.append([prefix + "." + k + "=" + str(v)])
        return list(itertools.chain.from_iterable(r))


# async def install(package: Package):
#     print("Install package "+package.name)
#
#     is_installed = await package.is_installed()
#     if not is_installed:
#         await package.install()
#     else:
#         print(f"The package {package.name} is already installed")
#
#
# async def upgrade(package: Package):
#     print("Upgrade package "+package.name)
#     await package.upgrade()
