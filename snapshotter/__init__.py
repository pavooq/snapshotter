# pylint: disable=missing-docstring

import pathlib
import asyncio
import argparse

from . import webserver
from . import snapshotter


def entrypoint():

    parent_parser = argparse.ArgumentParser()

    subparsers = parent_parser.add_subparsers(
        dest="command", metavar="command", help="action to execute"
    )

    auth_parser = subparsers.add_parser(
        "auth", help=webserver.entrypoint.__doc__
    )

    auth_parser.add_argument(
        "host", type=str, default="localhost", nargs="?",
        help="interface to listen on (default: localhost)"
    )

    auth_parser.add_argument(
        "port", type=int, default=8080, nargs="?",
        help="port to listen on (default: 8080)"
    )

    auth_parser.add_argument(
        "--keys-file", dest="datapath", type=pathlib.Path, default=".",
        help="path to the working directory (default: current directory)"
    )

    collect_parser = subparsers.add_parser(
        "collect", help="collect, obscure and store workspace data"
    )

    collect_parser.add_argument(
        "--keys-file", dest="datapath", type=pathlib.Path, default=".",
        help="path to the working directory (default: current directory)"
    )

    arguments = parent_parser.parse_args()

    if arguments.command not in subparsers.choices:
        parent_parser.parse_args(["--help"])

    if arguments.command == "collect":
        return asyncio.run(snapshotter.entrypoint(arguments.datapath))
    return webserver.entrypoint(
        arguments.host, arguments.port, arguments.datapath
    )
