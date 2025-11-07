# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI common functions and tools"""

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
