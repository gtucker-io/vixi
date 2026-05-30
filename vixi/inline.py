# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI inline runtime and scheduler service"""

import tempfile

from renelick.client import Task, SimpleScheduler
from renelick.client.runtime import Runtime, Config as RuntimeConfig
import vixi.bisect
import vixi.delta
import vixi.kunit
import vixi.trigger
from .base import ExtendedClient


class InlineVIXI(Runtime):
    """Inline VIXI runtime

    This runtime driver runs tasks directly in the current Python process.
    It's especially efficient for pure data processing tasks that don't require
    additional dedicated compute resources.
    """

    SANDBOX = '/workspace/common/inline'
    MIRROR = '/workspace/common/mirror'

    def __init__(self, config, client, sandbox):
        super().__init__(config, client.api)
        self._client = client
        self._sandbox = sandbox

    def run_task(self, task: Task):
        func = getattr(
            self, '_'.join(['', 'run'] + task.name.split('-')), None
        )
        if not func:
            self.log.warning(f"No method found for task: {task.name}")
            self._api.task.abort(task.id)
        else:
            self.log.info('  '.join([str(task.id), task.name]))
            self._api.task.ack(task.id)
            attrs = task.attributes.to_dict()
            func(task, attrs)
            self._api.task.complete(task.id)

    def _run_trigger(self, task, attrs):
        vixi.trigger.run(
            self._api, attrs['tree'], attrs['url'], attrs['branch'], task
        )

    def _run_kunit_parser(self, task, attrs):
        vixi.kunit.parse(
            self._api, attrs['input-nodes']['artifact']['id'], task
        )

    def _run_delta(self, task, attrs):
        vixi.delta.Delta(
            self._client, attrs['parent'], task
        ).run(
            self._sandbox, self.MIRROR,
        )

    def _run_bisect(self, task, attrs):
        vixi.bisect.Bisection(
            self._client, attrs['delta'], task
        ).run(
            self._sandbox, self.MIRROR,
        )


if __name__ == '__main__':
    client = ExtendedClient()
    config = RuntimeConfig(name='inline-vixi', driver='inline-vixi')
    with tempfile.TemporaryDirectory(dir=InlineVIXI.SANDBOX) as sandbox:
        runtime = InlineVIXI(config, client, sandbox)
        SimpleScheduler(runtime, client.api).loop()
