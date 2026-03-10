# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI kernel build module"""

import json
import hashlib
import os
import re
from urllib.parse import urlparse

import unidiff

from renelick.client import (
    Client,
    NewNode as Node,
    NewNodeData as Data,
    NewTree as Tree,
    RenelickError,
)
from renelick.client.cli import storage as cli_storage
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


def _dump_env(base, fname, keys, extra=None, append=False):
    mode = 'a' if append else 'w'
    with open(os.path.join(base, fname), mode, encoding='utf-8') as env_file:
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


def save_env(base):
    """Save the kbuild environment variables in plain-text files"""
    _dump_env(base, 'global.env', [
        'UUID', 'STORAGE', 'JOB', 'FILTER', 'FLAGS',
    ])
    _dump_env(base, 'source.env', [
        'TREE', 'URL', 'REVISION', 'PATCHES',
    ])
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
    if patches := os.getenv('PATCHES').split():
        print("Patches:")
        for patch in patches:
            print(f"  {patch}")
    print("Parameters:")
    with open(os.path.join(base, 'params.json'), encoding='utf-8') as pfile:
        params = json.load(pfile)
        for key, value in params.items():
            print(f"  {key.lower():12s}  {value}")


def checkout(sandbox, path, revspec, clean=False, gitonly=False):
    """Initialise or update a kernel checkout"""
    tree, url, rev = (revspec[key] for key in ('tree', 'url', 'rev'))
    print(f"Tree:     {tree}")
    print(f"URL:      {url}")
    print(f"Revision: {rev}")
    cwd = os.path.join(sandbox, path, tree)
    if gitonly is True:
        cwd += '.git'
    print(f"Path:     {cwd}", flush=True)
    if clean is True:
        print("Deleting any existing checkout", flush=True)
        shx(f'rm -rf {cwd}')
    if not os.path.exists(cwd):
        shx(f'mkdir -p {cwd}')
        mirror = os.path.join(sandbox, 'mirror', f'{tree}.git')
        print(f"New checkout, mirror: {mirror}", flush=True)
        opts = '--bare' if gitonly else ''
        shx(f'git clone -v --reference-if-able={mirror} {opts} {url} {cwd}')
    print("User:     ", end='', flush=True)
    if shx('git config user.name', cwd, retcode=True) != 0:
        shx('git config user.name VIXI', cwd)
    print("Email:    ", end='', flush=True)
    if shx('git config user.email', cwd, retcode=True) != 0:
        shx('git config user.email vixi@renelick.org', cwd)
    print("Remote repositories:", flush=True)
    shx('git remote -v', cwd)
    shx(f'git fetch --tags --force origin {rev}', cwd)
    if not gitonly:
        shx('git reset --hard', cwd)
        if os.path.exists(os.path.join(cwd, '.git/rebase-apply')):
            print("Aborting previous mailbox patch")
            shx('git am --abort', cwd)
        shx('git checkout FETCH_HEAD', cwd)
        shx(f'git fetch --tags {TORVALDS}', cwd)
        print(sh('git log -n1', cwd), flush=True)
    shx(f'du -hs {cwd}')
    return cwd


def _normalise_diff(path):
    with open(path, encoding='utf-8') as diff_file:
        patchset = unidiff.PatchSet(diff_file)
    for patch in patchset:
        yield str(patch.patch_info)
        yield f'--- {patch.source_file}\n'
        yield f'+++ {patch.target_file}\n'
        for hunk in patch:
            yield (
                f'@@ -{hunk.source_start:d},{hunk.source_length:d} '
                f'+{hunk.target_start:d},{hunk.target_length:d} @@\n'
            )
            for line in hunk:
                yield str(line)


def _apply_patch_rnr(patch_path, cwd):
    with open(patch_path, encoding='utf-8') as pfile:
        shx('patch --no-backup-if-mismatch -r- -p1', cwd, True, stdin=pfile)
    shx('git add --update', cwd)
    diff = sh('git diff --cached', cwd)
    if not diff:
        shx('git am --abort', cwd)
        os.unlink(patch_path)
        return None
    print(diff, flush=True)
    shx('git am --continue', cwd)
    with open(patch_path, 'w', encoding='utf-8') as patch_file:
        shx('git format-patch --stdout HEAD^', cwd, stdout=patch_file)
    return "🎸 " + sh('git show --format=%s -s', cwd).strip()


def apply_patches(patches, sha1, artifacts, cwd, rnr=False):
    """Apply a series of patches in a checkout and generate normalised diff"""
    if rnr is True:
        print("🎸 RnR enabled", flush=True)
    applied = []
    for patch_url in patches:
        patch_name = urlparse(patch_url).path.split('/')[-1]
        dest = os.path.join(artifacts, patch_name)
        cli_storage.download_raw(patch_url, dest)
        if shx(f'git am {dest}', cwd, retcode=True) == 0:
            applied.append({
                'url': patch_url,
                'subject': sh('git show --format=%s -s', cwd).strip(),
            })
        elif rnr is True:
            subject = _apply_patch_rnr(dest, cwd)
            if subject:
                applied.append({'url': patch_url, 'subject': subject})
        else:
            shx('git am --show-current-patch=diff', cwd)
            shx('git am --abort', cwd)
            raise RenelickError(f"Failed to apply patch: {patch_name}")
    print("History:", flush=True)
    shx(f'git log --oneline --abbrev=12 {sha1}^..HEAD', cwd)
    checksum = hashlib.sha256(sha1.encode('utf-8'))
    if applied:
        diff_path = os.path.join(artifacts, 'patchset.diff')
        with open(diff_path, 'w', encoding='utf-8') as diff_file:
            diff_file.write(sh(f'git diff -U0 {sha1}..HEAD', cwd))
        for line in _normalise_diff(diff_path):
            checksum.update(line.encode('utf-8'))
    return {
        'digest': checksum.hexdigest(),
        'patches': applied,
    }


def _gather_revision(opt, cwd):
    sha1 = sh('git show --format=%H -s', cwd).strip()
    return {
        'sha1': sha1,
        'describe': sh('git describe --always', cwd),
        'subject': sh('git show --format=%s -s', cwd).strip(),
        'tree': opt['TREE'],
        'url': opt['URL'],
        'digest': hashlib.sha256(sha1.encode('utf-8')).hexdigest(),
        'patches': [],
    }


def env_checkout(base, sandbox):
    """Initialise a kernel checkout using environment variables"""
    opt, _ = _load_opt(base)
    path = os.path.join('src', opt['JOB'])
    artifacts = os.path.join(base, opt['STEP'])
    flags = opt['FLAGS'].split()
    patches = opt['PATCHES'].split()
    revspec = {
        'tree': opt['TREE'],
        'url': opt['URL'],
        'rev': opt['REVISION'],
    }
    rev_path = os.path.join(base, 'revision.json')
    with open(rev_path, 'w', encoding='utf-8') as rev_file:
        json.dump(revspec, rev_file)
    cwd = checkout(sandbox, path, revspec, 'clean' in flags)
    rev = _gather_revision(opt, cwd)
    with open(rev_path, 'w', encoding='utf-8') as rev_file:
        json.dump(rev, rev_file)
    _dump_env(base, 'source.env', [], {'DESCRIBE': rev['describe']}, True)
    rev.update(
        apply_patches(patches, rev['sha1'], artifacts, cwd, 'rnr' in flags)
    )
    with open(rev_path, 'w', encoding='utf-8') as rev_file:
        json.dump(rev, rev_file)
    return cwd


def add_result_node(base):
    """Add a database result node for a kbuild step"""
    opt, params = _load_opt(base)
    with open(os.path.join(base, 'revision.json'), encoding='utf-8') as revf:
        revision = json.load(revf)
    uuid, job, step = (opt.get(key) for key in ('UUID', 'JOB', 'STEP'))
    time_px = os.path.join(base, step)
    status = int(read_string(os.path.join(base, '.'.join((step, 'status')))))
    rk = Client().api
    return rk.node.add(Node(
        name=':'.join(
            opt.get(key, 'unknown') for key in ('TREE', 'DESCRIBE', 'STEP')
        ),
        kind='.'.join(('vixi', job, 'step')),
        parent=opt.get('PARENT') or None,
        task=rk.task.get(uuid) if uuid else None,
        data=Data.from_dict({
            'step': step,
            'start-time': read_string(f'{time_px}-start-time'),
            'end-time': read_string(f'{time_px}-end-time'),
            'status': status,
            'revision': revision,
            'params': params,
        }),
    ))


def add_results(base, steps, job='kbuild'):
    """Add a database vixi.group tree for a primitive job pipeline"""
    uuid = _load_env(base, 'global.env').get('UUID')
    if not uuid:
        print("WARNING - no task UUID defined, not adding summary node")
        return None

    results = []
    for step in steps:
        step_path = os.path.join(base, '.'.join((step, 'status')))
        if os.path.exists(step_path):
            step_status = int(read_string(step_path))
            step_result = 'pass' if step_status == 0 else 'fail'
        else:
            step_status = None
            step_result = 'skip'
        results.append((step, step_status, step_result))
    complete = list(step for (step, stat, _) in results if stat is not None)
    if not any(complete):
        print("WARNING - no step node found, not adding summary node")
        return None

    rk = Client().api
    parent = rk.node.find([
        f'kind=vixi.{job}.step', f'task.id={uuid}', f'data.step={complete[-1]}'
    ], limit=1)[0]
    steps = [
        Tree(root=Node(
            name=name,
            kind='vixi.test',
            task=parent.task,
            data=Data.from_dict({
                'path': [job, name],
                'result': result,
            }),
        )) for name, stat, result in results
    ]
    tree = Tree(
        root=Node(
            name=job,
            kind='vixi.group',
            parent=parent.id,
            task=parent.task,
            data=Data.from_dict({
                'revision': parent.data['revision'],
                'params': parent.data['params'],
                'result': (
                    'pass'
                    if read_string(os.path.join(base, 'result')) == 'Succeeded'
                    else 'fail'
                )
            })
        ),
        branches=steps,
    )
    return rk.node.add_batch([tree])[0]


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
            'vixi',
            parent.data['revision']['tree'],
            parent.data['revision'].get('describe', 'unknown'),
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
