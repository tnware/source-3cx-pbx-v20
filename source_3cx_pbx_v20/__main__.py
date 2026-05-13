"""Entry point: python -m source_3cx_pbx_v20 <command> [options]"""

import sys

from airbyte_cdk.entrypoint import launch

from .source import Source3cxPbxV20


def run():
    source = Source3cxPbxV20()
    launch(source, sys.argv[1:])


if __name__ == "__main__":
    run()
