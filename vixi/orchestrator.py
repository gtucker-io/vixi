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
        channels=['node', 'vixi', 'task'],
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

    def _match(self, channel, evdata, spec):
        if spec['channel'] != channel:
            return False
        for key, value in spec['match'].items():
            if evdata.get(key) != value:
                return False
        for param in spec.get('params', []):
            if param not in evdata:
                self.log.error(
                    f"Missing parameter '{param}' in '{spec['task']}'"
                )
                return False
        return True

    async def _dispatch_event(self, channel, event):
        self.log.debug(event)
        for evdata in event.data.get('batch', [event.data]):
            self.log.debug(evdata)
            for spec in self._oconfig['switchboard']:
                self.log.debug(spec)
                if self._match(channel, evdata, spec):
                    self.log.debug("MATCH %s", spec['task'])
                    handler = '_'.join((
                        '', 'run', spec['task'].replace('-', '_')
                    ))
                    await getattr(self, handler)(evdata, spec['scheduler'])

    async def _run_oconfig_reload(self, event, _):
        node = self._api.node.get(event['id'])
        self.load_oconfig(node)

    async def _run_kbuild_mirror(self, event, scheduler):
        tree = event['tree']
        tree_config = self._oconfig['trees'].get(tree)
        if tree_config is None:
            raise RenelickError(f"Unknown tree: {tree}")
        task = self._api.task.schedule(Task(
            name='kbuild-mirror',
            scheduler=scheduler,
            timeout=datetime.now() + timedelta(minutes=30),
            attributes=TaskAttributes.from_dict({
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
            name='kbuild',
            scheduler=scheduler,
            timeout=datetime.now() + timedelta(minutes=90),
            attributes=TaskAttributes.from_dict({
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
            name='kunit',
            scheduler=scheduler,
            timeout=datetime.now() + timedelta(minutes=90),
            attributes=TaskAttributes.from_dict({
                'tree': tree,
                'url': tree_config['url'],
                'revision': revision,
                'job': 'kunit',
            }),
        ))
        tag = f"kunit-{tree}-{revision}"
        self.log.info(f"{tag:48s}  {task.id}")

    async def _run_kunit_parser(self, event, scheduler):
        # The task is gone at this point which is why we need to retrive a node
        task_id = event['id']
        found = self._api.node.find([
            f'task.id={task_id}', 'kind=artifact-v1', 'name=kunit.json'
        ])
        if len(found) != 1:
            self.log.error(f"Found {len(found)} JSON artifacts, expected 1")
            return
        artifact = found[0]
        # ToDo: add syntax to match with attributes in oconfig.yaml directly
        if artifact.task.attributes.to_dict().get('job') != 'kunit':
            return
        task = self._api.task.schedule(Task(
            name='kunit-parser',
            scheduler=scheduler,
            timeout=datetime.now() + timedelta(minutes=15),
            attributes=TaskAttributes.from_dict({
                'artifact': artifact.id,
                'job': 'kunit',
            }),
        ))
        parent = self._api.node.get(artifact.parent)
        data = parent.data.to_dict()
        tag = '-'.join([
            'kunit',
            'parser',
            data['revision']['tree'],
            data['revision']['describe'],
            data['params']['cc'],
        ])
        self.log.info(f"{tag:48s}  {task.id}")

    async def _run_delta(self, event, scheduler):
        parent = self._api.node.get(event['id'])
        if parent.task.attributes.to_dict().get('job') != 'kunit':
            return
        data = parent.data.to_dict()
        task = self._api.task.schedule(Task(
            name='delta',
            scheduler=scheduler,
            timeout=datetime.now() + timedelta(minutes=30),
            attributes=TaskAttributes.from_dict({
                'parent': parent.id,
            }),
        ))
        tag = '-'.join([
            parent.name,
            'delta',
            data['revision']['tree'],
            data['revision']['describe'],
            data['params']['cc'],
        ])
        self.log.info(f"{tag:48s}  {task.id}")

    async def _run_bisect(self, event, scheduler):
        delta = self._api.node.get(event['id'])
        data = delta.data.to_dict()
        task = self._api.task.schedule(Task(
            name='bisect',
            scheduler=scheduler,
            timeout=datetime.now() + timedelta(minutes=180),
            attributes=TaskAttributes.from_dict({
                'delta': delta.id,
            }),
        ))
        revision = data['new']['revision']
        params = data['new']['params']
        tag = '-'.join([
            data['root'],
            'bisect',
            revision['tree'],
            revision['describe'],
            params['cc'],
        ])
        self.log.info(f"{tag:48s}  {task.id}")

    async def _run_kboot_docker(self, event, scheduler):
        node = self._api.node.get(event['id'])
        data = node.data.to_dict()
        task = self._api.task.schedule(Task(
            name='kboot',
            scheduler=scheduler,
            timeout=datetime.now() + timedelta(minutes=15),
            attributes=TaskAttributes.from_dict({
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
