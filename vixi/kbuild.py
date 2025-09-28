# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI kernel build module"""

import json
import os
import re

from renelick.client import NewNode as Node, NewNodeData as Data
from .base import sh, read_string, iter_files, rk_client, rk_storage


def mirror_node(base):
    """Create a database node for the kbuild mirror task"""
    uuid, tree, url = (os.getenv(key) for key in ('UUID', 'TREE', 'URL'))
    cwd = f'{tree}.git'
    rk = rk_client()
    return rk.node.add(Node(
        name=f'kbuild-mirror-{tree}',
        kind='vixi-mirror',
        task=rk.task.get(uuid) if uuid else None,
        data=Data.from_dict({
            'revision': {
                'sha1': sh('git show --format=%H -s', cwd=cwd),
                'describe': sh('git describe', cwd=cwd),
                'tree': tree,
                'url': url,
                'git-head': sh("git log -n1", cwd=cwd),
            },
            'start-time': read_string(f'{base}/mirror-start'),
            'end-time': read_string(f'{base}/mirror-end'),
        }),
    ))


def _dump_env(base, fname, keys, extra=None):
    with open(os.path.join(base, fname), 'w', encoding='utf-8') as env_file:
        for key in keys:
            value = os.getenv(key)
            env_file.write(f'export {key}="{value}"\n')
        if extra:
            for key, value in extra.items():
                env_file.write(f'export {key}="{value}"\n')


def _load_env(base, fname):
    env_re = re.compile(r'^export ([A-Z_]+)="(.*)"$')
    with open(os.path.join(base, fname), encoding='utf-8') as env_file:
        return dict(env_re.match(line).groups() for line in env_file)


def _load_opt(base):
    with open(os.path.join(base, 'params.json'), encoding='utf-8') as pfile:
        opt = json.load(pfile)
    params = {key.lower(): value for key, value in opt.items()}
    opt.update({key: os.getenv(key) for key in ('PARENT', 'STEP')})
    opt.update(_load_env(base, 'storage.env'))
    opt.update(_load_env(base, 'source.env'))
    return opt, params


def _gather_revision(opt):
    cwd = opt['TREE']
    return {
        'sha1': sh('git show --format=%H -s', cwd),
        'describe': opt['DESCRIBE'],
        'subject': sh('git show --format=%s -s', cwd),
        'tree': opt['TREE'],
        'url': opt['URL'],
    }


def save_env(base):
    """Save the kbuild environment variables in plain-text files"""
    _dump_env(base, 'storage.env', ['UUID', 'STORAGE'])
    _dump_env(base, 'source.env', ['TREE', 'URL', 'REVISION', 'CLEAN'])
    arch, cc, ccver = (os.getenv(key) for key in ('ARCH', 'CC', 'CVER'))
    _dump_env(base, 'params.env', [
        'ARCH', 'DEFCONFIG', 'OPTS', 'CC', 'CCVER', 'CCARCH',
    ], {
        'BDIR': f'build/{arch}/{cc}-{ccver}',
    })


def save_params(base):
    """Save the kbuild parameters in a JSON file"""
    params = {
        key: os.getenv(key) for key in [
            'ARCH', 'DEFCONFIG', 'OPTS', 'CC', 'CCVER', 'CCARCH',
        ]
    }
    path = os.path.join(base, 'params.json')
    with open(path, 'w', encoding='utf-8') as json_file:
        json.dump(params, json_file, indent=2)
    return params


def dump_info(base):
    """Print information about the API user and kbuild parameters"""
    rk = rk_client()
    user = rk.user.whoami()
    print("User:")
    print(f"  {'username':12s}  {user.username}")
    print(f"  {'email':12s}  {user.email}")
    print(f"  {'full name':12s}  {user.full_name}")
    print("Revision:")
    for key in ['TREE', 'URL', 'REVISION']:
        value = os.getenv(key)
        print(f"  {key.lower():12s}  {value}")
    print("Parameters:")
    with open(os.path.join(base, 'params.json'), encoding='utf-8') as pfile:
        params = json.load(pfile)
        for key, value in params.items():
            print(f"  {key.lower():12s}  {value}")


def add_result_node(base):
    """Add a database result node for a kbuild step"""
    opt, params = _load_opt(base)
    revision = _gather_revision(opt)
    uuid = opt.get('UUID')
    time_px = os.path.join(base, opt['STEP'])
    rk = rk_client()
    return rk_client().node.add(Node(
        name=':'.join(opt[key] for key in ('TREE', 'DESCRIBE', 'STEP')),
        kind='vixi.kbuild',
        parent=opt.get('PARENT') or None,
        task=rk.task.get(uuid) if uuid else None,
        data=Data.from_dict({
            'step': opt['STEP'],
            'start-time': read_string(f'{time_px}-start-time'),
            'end-time': read_string(f'{time_px}-end-time'),
            'revision': revision,
            'params': params,
        }),
    ))


def upload_artifacts(base, verbose=True):
    """Upload kbuild artifacts found in the base directory"""
    opt = _load_env(base, 'storage.env')
    storage_name, uuid = (opt.get(key) for key in ('STORAGE', 'UUID'))
    if not storage_name:
        print("WARNING - no storage defined, artifacts will not be saved")
    elif not uuid:
        print("WARNING - no task UUID defined, artifacts will not be saved")
    else:
        rk = rk_client()
        storage = rk_storage(storage_name)
        parent, step = (os.getenv(key) for key in ('PARENT', 'STEP'))
        dest = f"kbuild-{uuid}"
        task = rk.task.get(uuid)
        for path in iter_files(os.path.join(base, step)):
            if verbose:
                print(f"Uploading {path}")
            fname = os.path.basename(path)
            url = storage.upload_single((path, fname), dest)
            if verbose:
                print(url)
            rk.node.add(Node(
                name=fname,
                kind='artifact-v1',
                parent=parent,
                task=task,
                data=Data.from_dict({
                    'url': url,
                    'storage': storage_name,
                }),
            ))


def add_docker_node(base):
    """Add a database node for a kernel Docker image"""
    opt, params = _load_opt(base)
    uuid = opt.get('UUID')
    if not uuid:
        print("WARNING - no task UUID defined, not building Docker image")
        return None
    rk = rk_client()
    return rk.node.add(Node(
        name=':'.join((opt['TREE'], opt['DESCRIBE'], 'docker')),
        kind='vixi.docker',
        parent=opt['PARENT'],
        task=rk.task.get(uuid),
        data=Data.from_dict({
            'image': f'docker.io/gtucker/kernel-image:{uuid}',
            'revision': _gather_revision(opt),
            'params': params,
        }),
    ))
