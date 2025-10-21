# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI Orchestrator"""

from datetime import datetime, timedelta
from renelick.client import Client, ServiceConfig
from renelick.client.api import Task, TaskAttributes
from renelick.client.exceptions import RenelickError
from renelick.client.service import Subscriber


class VixiOrchestrator(Subscriber):
    """VIXI orchestrator service implmentation

    This orchestrator expects pub/sub events from node operations and the
    'vixi' dedicated channel e.g. when a new Git revision has been discovered.
    It's currently hard-coded to run tasks in a 'tekton' scheduler.

    The orchestrator configuration is stored in a 'vixi.oconfig' kind of node
    and loaded dynamically when the service starts.  It will get reloaded too
    every time a new config node has been added, without restarting the
    service.
    """

    _config = ServiceConfig(
        name='vixi',
        channels=['node', 'vixi'],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._oconfig = None

    def load_oconfig(self, node=None):
        """Load the orchestrator config from a database node"""
        if node is None:
            latest = self._api.node.find(
                ['kind=vixi.oconfig', 'created__sort=down'], limit=1
            )
            if not latest:
                raise RenelickError("Orchestrator config not found")
            node = latest[0]
        self.log.info(f"Config:     {node.name}")
        self._oconfig = node.data.to_dict()

    def show_config(self):
        self.log.info("VIXI Orchestrator")
        self.load_oconfig()
        super().show_config()

    def _match(self, event, spec):
        for key, value in spec['match'].items():
            if event.data.get(key) != value:
                return False
        for param in spec.get('params', []):
            if param not in event.data:
                self.log.error(
                    f"Missing parameter '{param}' in '{spec['task']}'"
                )
                return False
        return True

    async def _dispatch_event(self, channel, event):
        self.log.debug(event)
        for spec in self._oconfig['switchboard'][channel]:
            if self._match(event, spec):
                handler = '_'.join(('', 'run', spec['task'].replace('-', '_')))
                await getattr(self, handler)(event.data, spec['scheduler'])

    async def _run_oconfig_reload(self, event, _):
        node = self._api.node.get(event['id'])
        self.load_oconfig(node)

    async def _run_kbuild_mirror(self, event, scheduler):
        tree = event['tree']
        tree_config = self._oconfig['trees'].get(tree)
        if tree_config is None:
            raise RenelickError(f"Unknown tree: {tree}")
        task = self._api.task.schedule(Task(
            scheduler=scheduler,
            timeout=datetime.now() + timedelta(minutes=30),
            attributes=TaskAttributes.from_dict({
                'name': 'kbuild-mirror',
                'tree': tree,
                'url': tree_config['url'],
            }),
        ))
        tag = f"kbuild-mirror-{tree}"
        self.log.info(f"{tag:48s}  {task.id}")

    async def _run_kbuild(self, event, scheduler):
        tree, revision = (event[key] for key in ['tree', 'revision'])
        tree_config = self._oconfig['trees'].get(tree)
        if tree_config is None:
            raise RenelickError(f"Unknown tree: {tree}")
        task = self._api.task.schedule(Task(
            scheduler=scheduler,
            timeout=datetime.now() + timedelta(minutes=90),
            attributes=TaskAttributes.from_dict({
                'name': 'kbuild',
                'tree': tree,
                'url': tree_config['url'],
                'revision': revision,
            }),
        ))
        tag = f"kbuild-{tree}-{revision}"
        self.log.info(f"{tag:48s}  {task.id}")

    # ToDo: consolidate with kbuild
    async def _run_kunit(self, event, scheduler):
        tree, revision = (event[key] for key in ['tree', 'revision'])
        tree_config = self._oconfig['trees'].get(tree)
        if tree_config is None:
            raise RenelickError(f"Unknown tree: {tree}")
        task = self._api.task.schedule(Task(
            scheduler=scheduler,
            timeout=datetime.now() + timedelta(minutes=90),
            attributes=TaskAttributes.from_dict({
                'name': 'kunit',
                'tree': tree,
                'url': tree_config['url'],
                'revision': revision,
            }),
        ))
        tag = f"kunit-{tree}-{revision}"
        self.log.info(f"{tag:48s}  {task.id}")

    async def _run_kboot_docker(self, event, scheduler):
        node = self._api.node.get(event['id'])
        data = node.data.to_dict()
        task = self._api.task.schedule(Task(
            scheduler=scheduler,
            timeout=datetime.now() + timedelta(minutes=15),
            attributes=TaskAttributes.from_dict({
                'name': 'kboot',
                'parent': node.id,
                'kernel-image': data['image'],
            }),
        ))
        tag = '-'.join((
            'kboot',
            data['revision']['tree'],
            data['revision']['describe'],
            data['params']['arch'],
            data['params']['cc'],
            data['params']['ccver'],
        ))
        self.log.info(f"{tag:48s}  {task.id}")


if __name__ == '__main__':
    VixiOrchestrator(Client().api).loop()
