# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI logic for comparing absolute results

Full logic (work in progress):

☑ Work out the base commit with the reference tree/branch
☑ Look at the incoming results to find failures
☐ Look for previous results on the same branch and compare
  (use Git history between base commit and HEAD)
  (node find tree=tree etc. data.created__gte=commit-timestamp)
☑ If no results, schedule single task with list of tests at base commit
  (then the task itself will deal with that list and run what's needed)
☑ Wait for the task to complete to get the results
  (either with orchestrator one-off hook or Python async)
☐ Remove dependency on kunit-parser
  (either enforce a single task to produce results or provide the chain)
☑ Store found regressions in vixi.delta nodes

Note: While this isn't as flexible as the Scalpel approach based on
floating-point numbers and statistics, it's a very effective way of dealing
with clear-cut pass/fail/skip results.  It might ultimately be superseded by
Scalpel.  Having both post-processing solutions available in parallel is a
useful experiment in any case.
"""

import re
from subprocess import SubprocessError

from renelick.client import (
    NewNode as Node,
    NewNodeData as Data,
    NewTree as Tree,
    RenelickError,
)

from . import kbuild
from .base import ExtendedClient, sh, shx


class Results:

    def __init__(self, api, root):
        self.root = root
        self.data = self.root.data.to_dict()
        self.revision = self.data['revision']
        self.params = self.data['params']
        self.failed = {
            tuple(fail.data.to_dict()['path']): fail
            for fail in api.node.find([
                'kind=vixi.test',
                f'task.id={self.root.task.id}',
                'data.result=fail'
            ])
        }
        self.names = set(self.failed.keys())


class Delta:

    REMOTE_RE = re.compile(r'^([a-zA-Z0-9_\-\.]+)\t(.*\.git) \(fetch\)$')

    def __init__(self, client, root_id, task):
        self._client = client
        self._api = self._client.api
        self._task = task
        root = self._api.node.get(root_id)
        if root.kind != 'vixi.group':
            raise RenelickError(
                f"Wrong node kind: {root.kind}, expected vixi.group"
            )
        self._res = Results(self._api, root)

    def _add_remote(self, cwd, name, url):
        remotes = {}
        for line in sh('git remote -v', cwd).split('\n'):
            if fetch := self.REMOTE_RE.match(line):
                remotes[fetch.group(1)] = fetch.group(2)
        current_url = remotes.get(name)
        if current_url != url:
            if current_url:
                shx(f'git remote rm {name}', cwd)
            shx(f'git remote add {name} {url}', cwd)

    def _get_base_sha1(self, cwd, url, branch):
        self._add_remote(cwd, 'base', url)
        shx(f'git fetch base {branch}', cwd)
        sha1 = self._res.revision['sha1']
        try:
            return sh(f'git merge-base {sha1} base/{branch}', cwd)
        except SubprocessError as ex:
            raise RenelickError("Failed to find base commit") from ex

    def _get_base(self, base_sha1):
        base = self._api.node.find([
            f"data.params.{key}{'__str' if value[0].isdigit() else ''}={value}"
            for (key, value) in self._res.params.items() if value
        ] + [
            'kind=vixi.group',
            f'name={self._res.root.name}',
            f'data.revision.sha1__str={base_sha1}',
            'created__sort=down',
        ], limit=1)
        return base[0] if base else None

    def _make_base(self, base_sha1):
        replay = self._client.replay_tasks(
            self._res.root, {'orch': 'delta', 'revision': base_sha1}
        )
        return self._client.find_single_node(
            'kind=vixi.group',
            f'task.id={replay[-1].id}',
            f'name={self._res.root.name}',
        )

    def _make_delta(self, base, base_node, res_node, category):
        # ToDo: node.data as object with DataNode
        base_data, res_data = (
            node.data.to_dict() for node in (base_node, res_node)
        )
        return Node(
            name=':'.join((res_node.name, category)),  # ToDo: use full path?
            kind='vixi.delta',
            parent=res_node.id,
            task=self._task,
            data=Data.from_dict({
                'category': category,
                'root': self._res.root.name,
                'path': res_data['path'],
                'old': {
                    'id': base_node.id,
                    'revision': base.revision,
                    'params': base.params,
                    'result': base_data.get('result'),
                },
                'new': {
                    'id': res_node.id,
                    'revision': self._res.revision,
                    'params': self._res.params,
                    'result': res_data.get('result'),
                },
            }),
        )

    # def _get_fixed(self, base):
    #     for name in base.names.difference(self._res.names):
    #         pass

    # def _get_failing(self, base):
    #     for name in base.names.intersection(self._res.names):
    #         pass

    def _get_breaking(self, base):
        for name in self._res.names.difference(base.names):
            passed = self._api.node.find([
                f'task.id={base.root.task.id}', f'data.path={list(name)}'
            ])[0]
            failed = self._res.failed[name]
            yield self._make_delta(base, passed, failed, 'break')

    def compare(self, base):
        fixed = []
        failing = []
        breaking = self._api.node.add_batch([
            Tree(root=delta) for delta in self._get_breaking(base)
        ])
        return fixed, failing, breaking

    def run(self, sandbox):
        revspec = {key: self._res.revision[revkey] for (key, revkey) in [
            ('tree', 'tree'), ('url', 'url'), ('rev', 'sha1'),
        ]}
        cwd = kbuild.checkout(sandbox, 'src/delta', revspec, gitonly=True)
        base_sha1 = self._get_base_sha1(cwd, kbuild.TORVALDS, 'master')
        base_node = self._get_base(base_sha1) or self._make_base(base_sha1)
        base = Results(self._api, base_node)
        return self.compare(base)


if __name__ == '__main__':
    import sys

    root = sys.argv[1] if len(sys.argv) > 1 else '6946874e2a7e93d186fde207'
    client = ExtendedClient(verbose=True)
    _, _, breaking = Delta(client, root, None).run('/workspace/sandbox')

    for delta in breaking:
        delta_data = delta.data.to_dict()
        print(f"BREAK {delta_data['root']} {' '.join(delta_data['path'])}")
