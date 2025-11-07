# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI kernel build module"""

import json
import os
import re

from renelick.client import (
    Client,
    NewNode as Node,
    NewNodeData as Data,
)
from .base import sh, shx, read_string, iter_files, rk_storage

TORVALDS = 'https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git'


def mirror_node(base):
    """Create a database node for the kbuild mirror task"""
    uuid, tree, url = (os.getenv(key) for key in ('UUID', 'TREE', 'URL'))
    cwd = f'{tree}.git'
    rk = Client().api
    return rk.node.add(Node(
        name=f'kbuild-mirror-{tree}',
        kind='vixi.mirror',
        task=rk.task.get(uuid) if uuid else None,
        data=Data.from_dict({
            'revision': {
                'sha1': sh('git show --format=%H -s', cwd=cwd),
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
    opt.update(_load_env(base, 'global.env'))
    opt.update(_load_env(base, 'source.env'))
    return opt, params


def _gather_revision(opt):
    cwd = os.path.join(opt['JOB'], opt['TREE'])
    return {
        'sha1': sh('git show --format=%H -s', cwd).strip(),
        'describe': opt['DESCRIBE'],
        'subject': sh('git show --format=%s -s', cwd).strip(),
        'tree': opt['TREE'],
        'url': opt['URL'],
    }


def save_env(base):
    """Save the kbuild environment variables in plain-text files"""
    _dump_env(base, 'global.env', ['UUID', 'STORAGE', 'JOB'])
    _dump_env(base, 'source.env', ['TREE', 'URL', 'REVISION', 'CLEAN'])
    arch, cc, ccver = (os.getenv(key) for key in ('ARCH', 'CC', 'CCVER'))
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
    rk = Client().api
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


def checkout(sandbox, path, revision, clean=False, gitonly=False):
    """Initialise or update a kernel checkout"""
    tree, url, sha1 = (revision[key] for key in ('tree', 'url', 'sha1'))
    print(f"Tree:     {tree}")
    print(f"URL:      {url}")
    print(f"Revision: {sha1}")
    cwd = os.path.join(sandbox, path, tree)
    print(f"Checkout directory: {cwd}")
    if clean is True:
        print("Deleting any existing checkout")
        shx(f'rm -rf {cwd}')
    if not os.path.exists(cwd):
        shx(f'mkdir -p {cwd}')
        mirror = os.path.join(sandbox, 'mirror', f'{tree}.git')
        print(f"New checkout, mirror: {mirror}")
        opts = '--no-checkout' if gitonly else ''
        shx(f'git clone -v --reference-if-able={mirror} {opts} {url} {cwd}')
    shx('git remote -v', cwd)
    shx(f'git fetch --tags origin {sha1}', cwd)
    if not gitonly:
        shx('git checkout FETCH_HEAD', cwd)
        shx(f'git fetch --tags {TORVALDS}', cwd)
        print(sh('git log -n1', cwd))
    shx(f'du -hs {cwd}')
    return cwd


def add_result_node(base):
    """Add a database result node for a kbuild step"""
    opt, params = _load_opt(base)
    revision = _gather_revision(opt)
    uuid, job = (opt.get(key) for key in ('UUID', 'JOB'))
    time_px = os.path.join(base, opt['STEP'])
    rk = Client().api
    return rk.node.add(Node(
        name=':'.join(opt[key] for key in ('TREE', 'DESCRIBE', 'STEP')),
        kind='.'.join(('vixi', job, 'step')),
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


def upload_artifacts(base, parent):
    """Upload kbuild artifacts found in the base directory"""
    # ToDo: load default storage from settings instead
    glob = _load_env(base, 'global.env')
    storage_name, job = (glob.get(key) for key in ('STORAGE', 'JOB'))
    urls = []
    if not storage_name:
        print("WARNING - no storage defined, artifacts will not be saved")
    elif not parent.task or not parent.task.id:
        print("WARNING - no task UUID defined, artifacts will not be saved")
    else:
        rk = Client().api
        storage = rk_storage(storage_name)
        dest = os.path.join(
            parent.data['revision']['tree'],
            parent.data['revision']['describe'],
            job,
            str(parent.task.id),
        )
        for path in iter_files(os.path.join(base, os.getenv('STEP'))):
            fname = os.path.basename(path)
            url = storage.upload_single((path, fname), dest)
            urls.append(url)
            rk.node.add(Node(
                name=fname,
                kind='artifact-v1',
                parent=parent.id,
                task=parent.task,
                data=Data.from_dict({
                    'url': url,
                    'storage': storage_name,
                }),
            ))
    return urls


def add_docker_node(base):
    """Add a database node for a kernel Docker image"""
    opt, params = _load_opt(base)
    uuid, job = (opt.get(key) for key in ('UUID', 'JOB'))
    if not uuid:
        print("WARNING - no task UUID defined, not building Docker image")
        return None
    rk = Client().api
    return rk.node.add(Node(
        name=':'.join((opt['TREE'], opt['DESCRIBE'], 'docker')),
        kind='.'.join(('vixi', job, 'docker')),
        parent=opt['PARENT'],
        task=rk.task.get(uuid),
        data=Data.from_dict({
            'image': f'docker.io/gtucker/kernel-image:{uuid}',
            'revision': _gather_revision(opt),
            'params': params,
        }),
    ))
