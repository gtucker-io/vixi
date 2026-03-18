# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI KUnit module"""

import requests

from renelick.client import (
    DataNode,
    NewNode as Node,
    NewNodeData as Data,
    NewTree as Tree,
)


def _parse_results(api, group, root, path):
    branches = []
    for test_case in group.get('test_cases', []):
        test_name = test_case['name']
        branches.append(Tree(root=Node(
            name=test_name,
            kind='vixi.test',
            task=root.task,
            data=Data.from_dict({
                'path': list(path + (test_name,)),
                'result': test_case['status'].lower(),
            }),
        )))
    for sub_group in group.get('sub_groups', []):
        sub_name = sub_group['name']
        sub_root = Node(
            name=sub_name,
            kind='vixi.group',
            task=root.task,
        )
        tree = _parse_results(api, sub_group, sub_root, path + (sub_name,))
        branches.append(tree)
    return Tree(root=root, branches=branches)


def parse(api, artifact_id, task):
    artifact = api.node.get(artifact_id)
    # ToDo: Storage.download(artifact) with timeout from settings etc.
    artifact_data = DataNode(artifact).get_obj(api)
    resp = requests.get(artifact_data.url, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    parent = api.node.get(artifact.parent)
    parent_data = parent.data.to_dict()
    root = Node(
        name='kunit-results',
        kind='vixi.group',
        parent=parent.id,
        task=task,
        data=Data.from_dict({
            key: parent_data.get(key) for key in ['revision', 'params']
        })
    )
    tree = _parse_results(api, data, root, ())
    return api.node.add_batch([tree])


if __name__ == '__main__':
    import sys
    from renelick.client import Client
    aid = sys.argv[1] if len(sys.argv) > 1 else '6910894b32cb46920f0e6e87'
    res = parse(Client().api, aid, None)
    print(f"Added {len(res)} nodes")
