# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI common functions and tools"""

from datetime import datetime, timedelta
import os
import subprocess

import renelick
import renelick.client
import renelick.client.cli


def sh(cmd, cwd=None):
    """Run a shell command and return stdout

    The output of the command is returned in a string with any trainling
    newline stripped.  Raise a CalledProcessError if the command fails.
    """
    return subprocess.check_output(
        cmd.split(), cwd=cwd
    ).decode('utf-8').strip()


def shx(cmd, cwd=None):
    """Run a shell command and return stdout

    As a simpler version of sh(), run a command and raise a CalledProcessError
    if it fails.  The output is printed on stdout as-is.
    """
    subprocess.check_call(cmd.split(), cwd=cwd)


def read_string(path):
    """Load a single string from a file"""
    with open(path, encoding='utf-8') as str_file:
        return str_file.readline().strip()


def write_string(path, value):
    """Save a single string to a file"""
    with open(path, 'w', encoding='utf-8') as str_file:
        str_file.write(str(value))


def iter_files(base):
    """Iterate through the paths to all the files found in a directory"""
    for root, dirs, files in os.walk(base):
        for fname in files:
            yield os.path.join(base, fname)
        for dname in dirs:
            iter_files(os.path.join(root, dname))


def rk_storage(name):  # ToDo: use renelick.storage.init() in v0.21
    """Get a Renelick storage object"""
    renelick.client.cli.globs.init()
    return renelick.client.cli.globs.get_storage(name)


def complete(uuid=None):
    """Complete the task associated with the current UUID if defined"""
    if uuid := uuid or os.getenv('UUID'):
        renelick.client.Client().api.task.complete(uuid)


def run_and_wait(api, task):
    """Schedule a Task to run and wait for it to complete"""
    sub = api.event.subscribe('task')
    task = api.task.schedule(task)
    task_id = str(task.id)
    print(f"Waiting for task to complete: {task_id} {task.name}")
    status = None
    while status is None:
        ev = api.event.receive(sub)
        if ev.data['id'] == task_id:
            op = ev.data['op']
            print(f"{ev['time']}  {op}")
            if op == 'complete':
                status = True
            elif op == 'abort' or op == 'timeout':
                status = False
    api.event.unsubscribe(sub)
    if status != True:
        raise renelick.client.RenelickError("Task failed to run")
    return task


class ExtendedClient(renelick.client.Client):
    """Extended client features based on the Renelick API"""

    def __init__(self, *args, verbose=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._verbose = verbose

    def run_and_wait(self, **kwargs):
        """Schedule a Task with provided kwargs and wait for it to complete"""
        sub = self.api.event.subscribe('task')
        task = self.api.task.schedule(renelick.client.Task(**kwargs))
        task_id = str(task.id)
        if self._verbose:
            print(f"{task_id}  {task.name}  {task.scheduler}")
        status = None
        while status is None:
            ev = self.api.event.receive(sub)
            if ev.data['id'] == task_id:
                op = ev.data['op']
                if self._verbose:
                    print(f"{ev['time']}  {op}")
                if op == 'complete':
                    status = True
                elif op in {'abort', 'timeout'}:
                    status = False
        self.api.event.unsubscribe(sub)
        if status is not True:
            raise renelick.client.RenelickError("Task failed to run")
        return task

    def find_single_node(self, *fields):
        """Find a single node matching the provided fields"""
        found = self.api.node.find(fields)
        if len(found) != 1:
            raise renelick.client.RenelickError(
                f"Failed to find single node: {fields}, found: {len(found)}"
            )
        return found[0]

    def get_tasks_history(self, node):
        """Reconstruct the history of Tasks that were run to produce a node"""
        tasks = [current := node.task]
        while node.parent:
            node = self.api.node.get(node.parent)
            if node.task.id != current.id:
                tasks.append(current := node.task)
        return list(reversed(tasks))

    def replay_tasks(self, node, patch):
        """Replay the tasks that were required to produce a node

        The history of tasks from the lineage of the ``node`` object will be
        run with the same schedulers and attributes, relying on 'input-nodes'
        to find data nodes produced by the previous task in the chain.  Each
        task should also have a 'timeout-spec' attribute, otherwise the default
        is 90 minutes.

        Any attribute may be overridded using the provided ``patch``
        dictionary.  This only applies to attributes that already exist in a
        task to avoid adding additional ones which may lead to unexpected
        results.
        """
        replay = []
        run = None
        for task in self.get_tasks_history(node):
            attrs = task.attributes.to_dict()
            for key, value in patch.items():
                orig = attrs.get(key)
                if orig is not None:
                    attrs[key] = value
            timeout_spec = attrs.get('timeout-spec', {'minutes': 90})
            if run and (input_data := attrs.get('input-nodes')):
                for _, input_fields in input_data.items():
                    search_fields = input_fields.copy()
                    search_fields.pop('id')
                    search_fields['task.id'] = run.id
                    input_fields['id'] = self.find_single_node(tuple(
                        '='.join((str(key), str(value)))
                        for key, value in search_fields.items()
                    )).id
            run = self.run_and_wait(name=task.name,
                scheduler=task.scheduler,
                timeout=datetime.now() + timedelta(**timeout_spec),
                attributes=renelick.client.TaskAttributes.from_dict(attrs),
            )
            replay.append(run)
        return replay
