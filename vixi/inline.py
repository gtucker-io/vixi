# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI inline runtime and scheduler service"""

import tempfile

from renelick.client import Client, Task, SimpleScheduler
from renelick.client.runtime import Runtime, Config as RuntimeConfig
import vixi.bisect
import vixi.delta
import vixi.kunit


class InlineVIXI(Runtime):
    """Inline VIXI runtime

    This runtime driver runs tasks directly in the current Python process.
    It's especially efficient for pure data processing tasks that don't require
    additional dedicated compute resources.
    """

    WORKSPACE = '/workspace/sandbox'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._storage = Client().storage

    def run_task(self, task: Task):
        func = getattr(self, '_'.join(['', 'run'] + task.name.split('-')), None)
        if not func:
            self.log.warning(f"No method found for task: {task.name}")
        else:
            self.log.info('  '.join([str(task.id), task.name]))
            func(task)

    def _run_kunit_parser(self, task: Task):
        attrs = task.attributes.to_dict()
        vixi.kunit.parse(
            self._api, attrs['input-nodes']['artifact']['id'], task
        )
        self._api.task.complete(task.id)

    def _run_delta(self, task: Task):
        attrs = task.attributes.to_dict()
        vixi.delta.Delta(self._api, attrs['parent'], task).run(self.WORKSPACE)
        self._api.task.complete(task.id)

    def _run_bisect(self, task: Task):
        attrs = task.attributes.to_dict()
        with tempfile.TemporaryDirectory() as artifacts:
            vixi.bisect.Bisection(
                self._api, self._storage, attrs['delta'], task
            ).run(
                self.WORKSPACE,
                artifacts,
            )
        self._api.task.complete(task.id)


if __name__ == '__main__':
    api = Client().api
    config = RuntimeConfig(name='inline-vixi', driver='inline-vixi')
    runtime = InlineVIXI(config, api)
    SimpleScheduler(runtime, api).loop()
