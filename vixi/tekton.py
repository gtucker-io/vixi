# SPDX-License-Identifier: MIT
#
# Copyright (C) 2026 Guillaume Tucker

"""VIXI Tekton runtime driver variant"""

import argparse
import dataclasses
import json
import requests

from renelick.client import Task, SimpleScheduler
from renelick.client.cli import globs
from renelick.client.runtime.tekton import Tekton, TektonConfig
from .base import ExtendedClient


@dataclasses.dataclass(frozen=True)
class TektonVIXIConfig(TektonConfig):
    """VIXI Tekton runtime configuration"""
    slot: int = 0

    @classmethod
    def from_settings(cls, settings, name, **kwargs):
        config_kwargs = cls._get_kwargs(settings, name)
        config_kwargs.update(kwargs)
        config_kwargs.setdefault('driver', name)
        return cls(name, **config_kwargs)


class TektonVIXI(Tekton):
    """Tekton VIXI runtime

    Based on the Tekton runtime, this can translate the VIXI-specific
    input-nodes attribute to standard trigger parameters as plain strings.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print(f"VIXI Tekton Runtime {self._config.name}-{self._config.slot}")

    def _trigger(self, task):
        task_id = str(task.id)
        self.log.info('%s  %s', task_id, task.name)
        params = task.attributes.to_dict()
        params['uuid'] = task_id
        params['slot'] = self._config.slot
        params.setdefault('storage', self._config.storage)
        params.update({
            f"{name}-node-id": node['id']
            for name, node in params.pop('input-nodes', {}).items()
        })
        return requests.get(
            f"http://el-{task.name}-trigger-listener{self._ns}:8080",
            data=json.dumps(params),
            timeout=self._config.request_timeout,
            headers={'Content-Type': 'application/json'}
        )

    def _wait(self, sub, task_id):
        status = None
        while status is None:
            ev = self._api.event.receive(sub)
            if ev.data['id'] == task_id:
                op = ev.data['op']
                self.log.info("%s  %s", task_id, op)
                if op == 'complete':
                    status = True
                elif op in {'abort', 'timeout'}:
                    status = False
        return status

    def run_task(self, task: Task):
        task_id = str(task.id)
        sub = self._api.event.subscribe('task')
        resp = self._trigger(task)
        if not resp.ok:
            self.log.error("Failed to trigger: %s", task.name)
            self._api.task.abort(task_id)
        else:
            self._api.task.ack(task_id)
            status = self._wait(sub, task_id)
            if status is False:
                self.log.error("Failed to run: %s", task.name)
        self._api.event.unsubscribe(sub)


if __name__ == '__main__':
    parser = argparse.ArgumentParser("VIXI Tetkton Runtime")
    parser.add_argument(
        '--name', default='tekton',
        help="Runtime instance name, also used in scheduler task queue"
    )
    parser.add_argument(
        '--slot', type=int, default=0,
        help="Slot number, must be unique among other task queue consumers"
    )
    args = parser.parse_args()
    config = TektonVIXIConfig.from_settings(
        globs.settings, args.name, slot=args.slot
    )
    client = ExtendedClient()
    runtime = TektonVIXI(config, client.api)
    SimpleScheduler(runtime, client.api).loop()
