# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI kernel build module"""

from renelick.client import NewNode as Node, NewNodeData as Data
from .base import sh, read_string, rk_client


def mirror_node(tmp, uuid, tree, url):
    """Create a database node for the kbuild mirror task"""
    rk = rk_client()

    return rk.node.add(Node(
        name=f'kbuild-mirror-{tree}',
        kind='vixi-mirror',
        task=rk.task.get(uuid) if uuid else None,
        data=Data.from_dict({
            'revision': {
                'sha1': sh('git show --format=%H -s'),
                'describe': sh('git describe'),
                'tree': tree,
                'url': url,
                'git-head': sh("git log -n1"),
            },
            'start-time': read_string(f'{tmp}/mirror-start'),
            'end-time': read_string(f'{tmp}/mirror-end'),
        }),
    ))
