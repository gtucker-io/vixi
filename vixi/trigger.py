# SPDX-License-Identifier: MIT
#
# Copyright (C) 2026 Guillaume Tucker

"""VIXI pipeline trigger"""

import argparse
import json
from renelick.client import Client, RenelickError
from . import sh


def _load_config(rk, tree):
    oconfig = rk.node.search(
        ['kind=vixi.oconfig'], sort=['created=down'], limit=1
    )
    if not oconfig:
        raise RenelickError("Orchestrator config not found")
    oconfig = oconfig[0]
    print(f"Config:  {oconfig.name}")
    tree = oconfig.data['trees'].get(args.tree)
    if tree is None:
        raise RenelickError(f"Tree config not found: {args.tree}")
    return tree


def _search_root(rk, url, sha1, job):
    root = rk.node.search([
        'parent=null',
        f'kind=vixi.{job}.step',
        f'data.revision.url={url}',
        f'data.revision.sha1={sha1}',
        'data.revision.patches=[]',
    ], sort=['created=down'], limit=1)
    return root[0] if root else None


def check(rk, url, branch, job):
    """Check if a new revision has appeared on the tree/branch

    Return a 2-tuple with the current HEAD of the tree/branch and the matching
    root node for the given job if there is one or None (in which case a new
    trigger event is due).
    """
    head = sh(f'git ls-remote {url} refs/heads/{branch}').split()[0]
    node = _search_root(rk, url, head, job)
    return head, node


def send(rk, tree, revision):
    """Send a trigger event for the given tree and revision"""
    return rk.event.send('vixi', {
        'event': 'trigger',
        'source': 'git',
        'tree': tree,
        'revision': revision,
    })


def run(rk, tree, url, branch, task):
    """Check for new revision and send trigger event if needed"""
    _, node = check(rk, url, branch, 'kbuild')
    if not node:
        send(rk, tree, branch)


def main(args):
    """Entry point for the CLI which will look up the tree in oconfig"""
    rk = Client().api
    tree = _load_config(rk, args.tree)
    print(f"URL:     {tree['url']}")
    branch = args.branch or tree['branch']
    print(f"Branch:  {branch}")
    head, found = check(rk, tree['url'], branch, args.job)
    print(f"Head:    {head}")
    if found:
        print(f"Found:   {found.id if found else 'none'}")
    else:
        ev = send(rk, args.tree, branch)
        print("Event:    ", json.dumps(ev.data))


if __name__ == '__main__':
    parser = argparse.ArgumentParser('VIXI Trigger')
    parser.add_argument('tree', help="Name of the tree to monitor")
    parser.add_argument('--branch',
                        help="Name of the branch to check for last revision")
    parser.add_argument('--job', default='kbuild',
                        help="Name of the job to check for last revision")
    args = parser.parse_args()
    main(args)
