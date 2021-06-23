import argparse
import asyncio
import functools
import os
import sys
from pathlib import Path

from dataclasses import dataclass
from typing import NamedTuple

parser = argparse.ArgumentParser()

parser.add_argument('--conf', help='Path to a configuration file')

args = parser.parse_args()


@dataclass(frozen=False)
class Configuration:
    starting_config_path: Path
    open_api_prefix: str
    http_port: int
    base_path: str
    service_name: str = 'youwol-infra'
    platform_folder: Path = Path.home() / 'Projects' / 'platform'
    charts_folder: Path = platform_folder / 'deployment' / 'charts'
    services_folder: Path = platform_folder / 'services'
    secrets_folder: Path = platform_folder / "secrets"


def assert_python():

    print(f"Running with python:\n\t{sys.executable}\n\t{sys.version}")
    version_info = sys.version_info
    if not (version_info.major == 3 and version_info.minor == 9):
        print(f"""Your version of python is not compatible: Required: 3.9.x""")
        exit(1)


def get_port_number(name: str):
    port = functools.reduce(lambda acc, e: acc + ord(e), name, 0)
    # need to check if somebody is already listening
    return 2000 + port % 1000


class MainArguments(NamedTuple):
    config_path: Path
    execution_folder = Path(os.getcwd())


def get_yw_config_starter() -> Path:

    main_args = MainArguments(
        config_path=Path(args.conf)
        )
    if main_args.config_path:
        return main_args.config_path

    # if no config provided by the command line => check if yw_config.py in current folder
    current_folder = main_args.execution_folder
    if (current_folder / 'yw_infra_config.py').exists():
        return current_folder / 'yw_infra_config.py'

    print("No config path has been provided as argument (using --conf),"
          f" and no yw_infra_config.py file is found in the current folder ({str(current_folder)}).\n"
          )
    exit()


async def get_service_config():
    return Configuration(
        starting_config_path=get_yw_config_starter(),
        open_api_prefix='',
        http_port=get_port_number(Configuration.service_name),
        base_path=""
        )

configuration: Configuration = asyncio.get_event_loop().run_until_complete(get_service_config())

