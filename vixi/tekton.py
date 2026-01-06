# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Copyright (C) 2026 Guillaume Tucker

"""VIXI Tekton runtime driver variant"""

import json
import requests

from renelick.client import Task, SimpleScheduler
from renelick.client.cli import globs
from renelick.client.runtime.tekton import Tekton, TektonConfig
from .base import ExtendedClient


class TektonVIXI(Tekton):
    """Tekton VIXI runtime

    Based on the Tekton runtime, this can translate the VIXI-specific
    input-nodes attribute to standard trigger parameters as plain strings.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print("VIXI Tekton Runtime")

    def run_task(self, task: Task):
        task_id = str(task.id)
        self.log.info('%s  %s', task_id, task.name)
        params = task.attributes.to_dict()
        params['uuid'] = task_id
        params.setdefault('storage', self._config.storage)
        params.update({
            f"{name}-node-id": node['id']
            for name, node in params.pop('input-nodes', {}).items()
        })
        resp = requests.get(
            f"http://el-{task.name}-trigger-listener{self._ns}:8080",
            data=json.dumps(params),
            timeout=self._config.request_timeout,
            headers={'Content-Type': 'application/json'}
        )
        if not resp.ok:
            self.log.error("Failed to trigger: %s", task.name)
            self._api.task.abort(task_id)
        else:
            self._api.task.ack(task_id)


def get_runtime(settings, name, api):
    """Get a TektonVIXI instance created using the provided arguments"""
    config = TektonConfig.from_settings(settings, name)
    return TektonVIXI(config, api)


if __name__ == '__main__':
    # needed until the driver can be loaded from an absolute module path
    client = ExtendedClient()
    runtime = get_runtime(globs.settings, 'tekton-kvm', client.api)
    SimpleScheduler(runtime, client.api).loop()
