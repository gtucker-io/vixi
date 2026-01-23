# SPDX-License-Identifier: MIT
#
# Copyright (C) 2026 Guillaume Tucker

"""VIXI kernel boot module"""

import json
import os

from renelick.client import (
    Client,
    NewNode as Node,
    NewNodeData as Data,
    NewTree as Tree,
)
from .base import iter_files, rk_storage


def load_metadata(task):
    """Make a list of trees using the metadata.json file from artifacts"""
    meta_path = os.path.join(os.getenv('ARTIFACTS'), 'metadata.json')
    if not os.path.isfile(meta_path):
        return []
    with open(meta_path, 'r', encoding='utf-8') as meta_file:
        meta_data = json.load(meta_file)
        result = meta_data.pop('result')
        meta = Tree(root=Node(
            name='metadata',
            kind='vixi.test',
            task=task,
            data=Data.from_dict({
                'path': ['kboot', 'metadata'],
                'result': result,
                'metadata': meta_data,
            }),
        ))
    os.unlink(meta_path)
    return [meta]


def upload_artifacts(kbuild, task):
    """Upload kboot artifacts found in the base directory except metadata"""
    storage = rk_storage(os.getenv('STORAGE'))
    artifacts = os.getenv('ARTIFACTS')
    dest = os.path.join(
        'vixi',
        kbuild.data['revision']['tree'],
        kbuild.data['revision']['describe'],
        'kboot',
        str(kbuild.task.id),
    )
    nodes = []
    for path in iter_files(artifacts):
        fname = os.path.basename(path)
        if fname == 'metadata.json':
            print("ERROR: metadata file found in artifacts")
            continue
        url = storage.upload_single((path, fname), dest)
        print(url)
        nodes.append(Tree(root=Node(
            name=fname,
            kind='artifact-v1',
            task=task,
            data=Data.from_dict({
                'url': url,
                'storage': storage.config.name,
            }),
        )))
    return nodes


def add_results(api, kbuild, task, branches):
    """Add a database vixi.group tree for a kboot pipeline"""
    result = 'pass' if os.getenv('STATUS') == 'Succeeded' else 'fail'
    run = Tree(root=Node(
        name='run',
        kind='vixi.test',
        task=task,
        data=Data.from_dict({
            'path': ['kboot', 'run'],
            'result': result,
        }),
    ))
    tree = Tree(
        root=Node(
            name='kboot',
            kind='vixi.group',
            parent=kbuild.id,
            task=task,
            data=Data.from_dict({
                'revision': kbuild.data['revision'],
                'params': kbuild.data['params'],
                'result': result,
            })
        ),
        branches=branches + [run],
    )
    return api.node.add_batch([tree])[0]


def summary():
    """Entry point to create the summary nodes for a kboot pipeline"""
    rk = Client()
    kbuild = rk.api.node.get(os.getenv('PARENT'))
    task = rk.api.task.get(os.getenv('UUID'))
    branches = load_metadata(task)
    branches.extend(upload_artifacts(kbuild, task))
    kboot = add_results(rk.api, kbuild, task, branches)
    print('  '.join((kboot.id, kboot.name)))
