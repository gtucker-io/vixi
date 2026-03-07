# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI logic for running a standard Git bisection"""

import os
import re

from renelick.client import (
    NewNode as Node,
    NewNodeData as Data,
    RenelickError,
)

from .base import ExtendedClient, sh, shx
from . import kbuild


class Bisection:

    BISECTING_RE = re.compile(
        r'^Bisecting\: ([\d]+) revision[s]? .* \(roughly ([\d]+) step[s]?\)$'
    )
    COMMIT_RE = re.compile(
        r'\[([0-9a-f]{40})\] .*'
    )
    FIRST_BAD_RE = re.compile(
        r'([0-9a-f]{40}) is the first bad commit$'
    )
    PASS_FAIL = {
        'pass': True,
        'fail': False,
    }
    GOOD_BAD = {
        True: 'good',
        False: 'bad',
    }

    def __init__(self, client, delta_id, task):
        self._client = client
        self._api = self._client.api
        self._storage = self._client.storage
        self._task = task
        self._delta = self._api.node.get(delta_id)
        if self._delta.kind != 'vixi.delta':
            raise RenelickError(
                f"Wrong node kind: {self._delta.kind}, expected vixi.delta"
            )
        self._data = self._delta.data.to_dict()
        self._old, self._new = (
            self._data[key]['revision'] for key in ('old', 'new')
        )
        self._new_node = self._api.node.get(self._data['new']['id'])

    def _parse_msg(self, msg):
        lines = msg.split('\n')
        if bisecting := self.BISECTING_RE.match(lines[0]):
            revs, iters = (int(value) for value in bisecting.groups())
            commit = self.COMMIT_RE.match(lines[1]).group(1)
            return False, commit, (revs, iters)
        if first_bad := self.FIRST_BAD_RE.match(lines[0]):
            bad = first_bad.group(1)
            return True, bad, (0, 0)
        print(f"Warning: unexpected message: {msg}")
        return None

    def _event(self, payload):
        data = {
            'event': 'bisect',
            'known': self._new['describe'],
        }
        data.update(payload)
        self._api.event.send('vixi', data)

    def _test(self, revision):
        replay = self._client.replay_tasks(
            self._new_node, {
                'orch': 'bisect',
                'tree': revision['tree'],
                'url': revision['url'],
                'revision': revision['sha1'],
                'filter': '.'.join(
                    f'"{step}"' for step in self._data['path'][:-1]
                ),
            }
        )
        test = self._client.find_single_node(
            'kind=vixi.test',
            f'data.path={self._delta.data["path"]}',
            f'task.id={replay[-1].id}',
        )
        return test, self.PASS_FAIL.get(test.data.to_dict().get('result'))

    def _check(self, revision, expected):
        _, result = self._test(revision)
        return result == expected

    def _iterate(self, cwd):
        good, bad = (obj['sha1'] for obj in (self._old, self._new))
        shx('git bisect start --no-checkout', cwd)
        shx(f'git bisect bad {bad}', cwd)
        it = 0
        history = []
        msg = sh(f'git bisect good {good}', cwd)
        revision = self._new.copy()
        while True:
            it += 1
            found, sha1, (revs, iters) = self._parse_msg(msg)
            if found:
                break
            print(f"Iteration {it} / {iters + it}, revisions left: {revs}")
            self._event({'iter': [it, iters + it], 'revs': revs, 'sha1': sha1})
            revision['sha1'] = sha1
            test, result = self._test(revision)
            step = self.GOOD_BAD.get(result, 'skip')
            history.append([test, step])
            msg = sh(f'git bisect {step}', cwd)
        self._event({'found': sha1})
        return sha1, history

    def _add_result_node(self, sha1, history):
        history_data = [{
            'id': node.id,
            'result': result,
            'revision': self._api.node.get(node.lineage[0]).data['revision'],
        } for (node, result) in history]
        found_revision = None
        for item in history_data:
            if item['revision']['sha1'] == sha1:
                found_revision = item['revision']
                break
        return self._api.node.add(Node(
            name=':'.join(('bisect', sha1)),
            kind='vixi.bisect',
            parent=self._delta.id,
            task=self._task,
            data=Data.from_dict({
                'root': self._data['root'],
                'path': self._data['path'],
                'params': self._data['new']['params'],
                'revision': found_revision,
                'history': history_data,
            }),
        ))

    def _upload_log(self, cwd, artifacts, parent):
        log = sh('git bisect log', cwd)
        print("--------------------------------------------------------------")
        print(log)
        print("--------------------------------------------------------------")
        fname = 'bisect.txt'
        log_path = os.path.join(artifacts, fname)
        with open(log_path, 'w', encoding='utf-8') as log_file:
            log_file.write(log)
        dest = os.path.join(
            'vixi',
            self._new['tree'],
            self._new['describe'],
            'bisect',
            str(parent.task.id) if parent.task else f'result-{parent.id}',
        )
        url = self._storage.upload_single((log_path, fname), dest)
        os.unlink(log_path)
        return self._api.node.add(Node(
            name=fname,
            kind='artifact-v1',
            parent=parent.id,
            task=parent.task,
            data=Data.from_dict({
                'url': url,
                'storage': self._storage.config.name,
            }),
        ))

    def run(self, sandbox, artifacts):
        print(f"Test:     {self._data['root']}:{self._delta.name}")
        revspec = {key: self._new[revkey] for (key, revkey) in [
            ('tree', 'tree'), ('url', 'url'), ('rev', 'sha1'),
        ]}
        cwd = kbuild.checkout(sandbox, 'src/bisect', revspec, gitonly=True)
        print(f"Checking bad revision: {self._new['describe']}")
        self._event({'check': 'bad', 'sha1': self._new['sha1']})
        if not self._check(self._new, False):
            print("Bad revision check failed, aborting")
            return False
        print(f"Checking good revision: {self._old['describe']}")
        self._event({'check': 'good', 'sha1': self._old['sha1']})
        if not self._check(self._old, True):
            print("Good revision check failed, aborting")
            return False
        sha1, history = self._iterate(cwd)
        history = [
            [self._api.node.get(self._data['new']['id']), 'bad'],
            [self._api.node.get(self._data['old']['id']), 'good'],
        ] + history
        result = self._add_result_node(sha1, history)
        print(f'{result.id}  {result.name}')
        log = self._upload_log(cwd, artifacts, result)
        print(log.data['url'])
        return result


if __name__ == '__main__':
    import sys

    client = ExtendedClient()
    delta_id = sys.argv[1] if len(sys.argv) > 1 else '6946d7fd2a7e93d186fe1c3f'
    result = Bisection(client, delta_id, None).run(
        os.path.join('/workspace/sandbox'), '/tmp'
    )

    if result:
        revision = result.data['revision']
        print(f"Found commit: {revision['sha1']}  {revision['subject']}")
