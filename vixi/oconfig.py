# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025, 2026 Guillaume Tucker

"""VIXI orchestrator configuration stored in nodes from local YAML"""

import argparse
from datetime import datetime
import os.path
import requests
import rich
import rich.json
import yaml
from renelick.client import Client, NewNode as Node, NewNodeData as Data


def _get_latest(rk):
    latest = rk.api.node.find(
        ['kind=vixi.oconfig', 'created__sort=down'], limit=1
    )
    return latest[0] if latest else None


def _upload(rk, parent, oconfig):
    now = datetime.isoformat(datetime.now())
    return rk.api.node.add(Node(
        name=f'oconfig-{now}',
        kind='vixi.oconfig',
        parent=parent.id if parent else None,
        data=Data.from_dict(oconfig),
    ))


def push(path, url=None, force=False, verbose=False, dump=False):
    """Open the orchestrator config from a YAML file and send it as a Node

    If the latest config is identical, no new node is created unless `force` is
    True.  The latest config node is set as the parent for any new one so the
    history of changes can be found in the lineage.
    """
    rk = Client()
    if url:
        if verbose:
            print(f"Downloading config from {url}")
        with requests.get(url) as req:
            oconfig = yaml.safe_load(req.text)
    elif os.path.exists(path):
        if verbose:
            print(f"Opening config from {path}")
        with open(path, encoding='utf-8') as oconfig_file:
            oconfig = yaml.safe_load(oconfig_file)
    else:
        raise FileNotFoundError("No oconfig.yaml found")
    latest = _get_latest(rk)
    if force is True or latest is None or latest.data.to_dict() != oconfig:
        if verbose:
            print("Uploading new config")
        node = _upload(rk, latest, oconfig)
    else:
        if verbose:
            print("Keeping current config")
        node = latest
    print(node.id)
    if dump:
        rich.print(rich.json.JSON.from_data(node.data.to_dict()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser('VIXI orchestrator config manager')
    parser.add_argument('--path', default='vixi/oconfig.yaml',
                        help="Path to the local config file")
    parser.add_argument('--url',
                        help="URL to override the local config file")
    parser.add_argument('--force', action='store_true',
                        help="Force-push config even with no changes")
    parser.add_argument('--verbose', action='store_true',
                        help="Print more information")
    parser.add_argument('--dump', action='store_true',
                        help="Dump the active configuration")
    args = parser.parse_args()
    push(args.path, args.url, args.force, args.verbose, args.dump)
