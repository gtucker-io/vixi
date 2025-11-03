# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI logic for running a standard Git bisection"""

from datetime import datetime, timedelta
import os
import re
import uuid

from renelick.client import (
    NewNode as Node,
    NewNodeData as Data,
    RenelickError,
    Task,
    TaskAttributes,
)

from .base import sh, shx, run_and_wait
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

    def __init__(self, api, storage, delta_id, task):
        self._api = api
        self._storage = storage
        self._task = task
        self._delta = api.node.get(delta_id)
        if self._delta.kind != 'vixi.delta':
            raise RenelickError(
                f"Wrong node kind: {self._delta.kind}, expected vixi.delta"
            )
        self._data = self._delta.data.to_dict()
        self._old, self._new = (
            self._data[key]['revision'] for key in ('old', 'new')
        )
        self._marker = str(uuid.uuid4())

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

    def _find_one(self, *fields):
        found = self._api.node.find(fields)
        if len(found) != 1:
            raise RenelickError(f"Failed to find single node {fields}")
        return found[0]

    def _test(self, revision):
        task = run_and_wait(self._api, Task(
            name=self._data['root'],  # ToDo: rename to something clearer
            scheduler='tekton', # ToDo: self.data['scheduler']
            timeout=datetime.now() + timedelta(minutes=30),
            attributes=TaskAttributes.from_dict({
                'tree': revision['tree'],
                'url': revision['url'],
                'revision': revision['sha1'],
                'job': 'bisect',
                'filter': '.'.join(
                    f'"{step}"' for step in self._data['path'][:-1]
                ),
                'marker': self._marker,
            }),
        ))
        artifact = self._find_one(
            f'task.id={task.id}', 'kind=artifact-v1', 'name=kunit.json',
        )
        task = run_and_wait(self._api, Task(
            name='kunit-parser',
            scheduler='inline-vixi',
            timeout=datetime.now() + timedelta(minutes=10),
            attributes=TaskAttributes.from_dict({
                'artifact': artifact.id,
                'parent': artifact.parent,
                'job': 'bisect',
                'marker': self._marker,
            }),
        ))
        test = self._find_one(
            'kind=vixi.test',
            f'data.path={self._delta.data["path"]}',
            f'task.id={task.id}',
        )
        return test, self.PASS_FAIL.get(test.data.to_dict().get('result'))

    def _check(self, revision, expected):
        _, result = self._test(revision)
        return result == expected

    def _iterate(self, cwd):
        good, bad = (obj['sha1'] for obj in (self._old, self._new))
        shx(f'git bisect reset {bad}', cwd)
        sh('git bisect start', cwd)  # --no-checkout
        sh(f'git bisect bad {bad}', cwd)
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
            if result is True:
                step = 'good'
            elif result is False:
                step = 'bad'
            else:
                step = 'skip'
            history.append([test, step])
            msg = sh(f'git bisect {step}', cwd)
        self._event({'found': sha1})
        return sha1, history

    def _add_result_node(self, sha1, history):
        checkout = self._find_one(
            f'task.attributes.marker={self._marker}',
            f'data.revision.sha1={sha1}',
            'parent=',
        )
        revision = checkout.data['revision']
        history_data = [{
            'id': node.id,
            'revision': self._api.node.get(node.lineage[0]).data['revision'],
            'result': result
        } for (node, result) in history]
        return self._api.node.add(Node(
            name=':'.join(('bisect', sha1)),
            kind='vixi.bisect',
            parent=self._delta.id,
            task=self._task,
            data=Data.from_dict({
                'root': self._data['root'],
                'path': self._data['path'],
                'params': self._data['new']['params'],
                'revision': revision,
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
            str(parent.task.id) if parent.task else self._marker,
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
        cwd = kbuild.checkout(sandbox, 'src/bisect', self._new)
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
    from renelick.client import Client
    client = Client()
    delta = sys.argv[1] if len(sys.argv) > 1 else '691ee899c3bca0e8094c9693'
    result = Bisection(client.api, client.storage, delta, None).run(
        os.path.join('/workspace/sandbox'), '/tmp'
    )
    if result:
        revision = result.data['revision']
        print(f"Found commit: {revision['sha1']}  {revision['subject']}")
