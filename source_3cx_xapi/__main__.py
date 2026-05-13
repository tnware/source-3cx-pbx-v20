"""Entry point: python -m source_3cx_xapi <command> [options]"""

import sys

from airbyte_cdk.entrypoint import launch

from .source import Source3cxXapi


def run():
    source = Source3cxXapi()
    launch(source, sys.argv[1:])


if __name__ == "__main__":
    run()
