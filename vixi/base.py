# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI common functions and tools"""

import subprocess

import renelick.client.cli
import renelick


def sh(cmd):
    """Run a shell command"""
    return subprocess.check_output(cmd.split()).decode('utf-8')


def read_string(path):
    """Load a single string from a file"""
    with open(path, encoding='utf-8') as ts_file:
        return ts_file.readline().strip()


def rk_client():  # ToDo: use renelick.client.init() in v0.21
    """Get a Renelick client object"""
    renelick.client.cli.globs.init()
    return renelick.client.cli.globs.get_api()


def complete(uuid=None):
    """Complete the task associated with the current UUID if defined"""
    if uuid := uuid or os.getenv('UUID'):
        rk_client().task.complete(uuid)
