VIXI · Virtual Kernel CI
========================

_Work in Progress_

This is a [Renelick](https://gitlab.com/gtucker.io/renelick) application to
continuously test the upstream Linux kernel in virtual environments.

## Workflow

This is currently limited to a single x86 build which allows for some
simplifications and a streamlined pipeline.  Extended coverage may be added
incrementally so as to keep it fast.

* ☐ revision trigger event
  * ☑ manual
  * ☐ new patch from email
  * ☐ discovered in git tree
  * ☐ via git hook
* ☑ kbuild pipeline
  * ☑ checkout the git revision with persistent mirror
  * ☑ build the kernel using a korg container
  * ☑ upload artifacts to storage via SSH
* ☑ kboot pipeline
  * ☑ boot a kernel image using KVM
* ☐ ktest task
  * run some tests in the VM
* ☐ kunit task
  * ☐ checkout the git revision
  * ☐ run KUnit in a korg container
* ☐ static checks
  * ☐ checkpatch

## Build Coverage

* ☐ Cutting-edge compilers on linux-next (latest LLVM from k.org)
* ☑ Latest stable compiler on mainline (latest GCC from k.org + Rust)
* ☐ Oldest supported compiler on LTS

## Design Overview

When a new revision is found, which could be a series of patches via email, a
Git branch or anything of this kind, a trigger event is sent with the
corresponding information.  Then the orchestrator service receives the event
and schedules a task to be run if the event matched one of its rules.
Typically, this would be a kernel build or a KUnit run.  Then a suitable
scheduler accepts the task and runs it in a dedicated runtime environment such
as a Tekton pipeline with Kubevirt enabled.

Each pipeline produces some data nodes with the results and artifacts, and an
event is sent every time a node is created.  These events are also received by
the orchestrator to schedule subsequent tasks, typically to start a boot
pipeline when a build is complete.

A single revision can trigger multiple builds, and each build can trigger
multiple boots.  Initially, the pipelines will be doing only a linear series of
tasks with a single optimised path to runtime results and then scale gradually.
Subsequent tests can be run after the boot completes, and other post-processing
tasks may be run such as bisections, statistics, log parsers, report generators
etc.

### Checkouts with Git mirrors

For each tree, a mirror repository is kept in a read-only persistent volume
which is shared by the workers.  A Tekton task can be run at any time to update
a given mirror, typically daily.  Mirrors may also be deleted from time to time
to avoid keeping stale data or any other kind of long-term decay.

### Incremental builds with kernel.org toolchains

The assumption is that incremental builds are reliable as per the upstream
kernel standards.  As such, build directories are kept in a persistent volume
to be reused.  They should be unique at least for each combination of Git
branch, compiler version and CPU architecture.  Having a persistent checkout
directory for each tree makes the builds more likely to be incremental.
Whenever a build failure is found, a subsequent pipeline should be run with a
full, clean build to confirm the error as part of the post-processing checks.

Also, this relies on [kernel.org toolchain
containers](https://gitlab.com/gtucker/korg) as initially proposed on
[LKML](https://lore.kernel.org/all/f80acb84-1d98-44d3-84b7-d976de77d8ce@gtucker.io/)
and LPC 2024.  It's a first experimental step towards putting this in practice.

### Booting with KVM

The current approach for booting kernels is via KVM and KubeVirt inside a
Tekton pipeline.  This relies on having a thin wrapper Docker image around the
kernel image to boot the VM.  Support for other runtimes should be enabled too,
for example with KVM-enabled QEMU directly on a bare-metal host machine.  Then
the orchestrator can decide which runtime to use for which tests and schedule
tasks accordingly.  The main advantage of KubeVirt is that the underlying Cloud
infrastructure can scale automatically.

## Setup

First of all, deployment is meant to happen in a Kubernetes cluster.
Currently, MiniKube and GKE are supported out of the box.  MiniKube is fine by
default for development, GKE is better suited for production workloads and if
you already have a Google Cloud account.

To create a MiniKube cluster:

```
deploy/minikube
```

To create a GKE cluster, you'll need to provide a cluster name and the region
where to deploy it:

```
deploy/gke exp-001-430112 vixi-001 europe-west1-c
```

You'll then need to install the standard `kubectl` tool as per the [Kubernetes
documentation](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/#install-using-native-package-management).

Then make sure your cluster is the one currently selected with `kubectl
use-context` and deploy all the Kubernetes resources:

```
deploy/tekton
# deploy/kubevirt (skipped for now)
deploy/vixi
```

## Usage

Jobs are meant to be run via the Renelick scheduler deployed in Kubernetes.
This is typically done by an orchestrator service, although it is still under
development.  For now, tasks can be scheduled manually instead.  To do this,
you'll typically need to have the `renelick` client installed either directly
on your host or in Docker and use the `renelick task run` command.

For example, to schedule a mirror update:

```
renelick task run tekton \
    name=kbuild-mirror \
    tree=torvalds
    url=https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git
```

Then to start a kernel build:

```
renelick task run tekton \
    name=kbuild \
    tree=torvalds \
    url=https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git \
    revision=master
```

### Debugging

Alternatively, you can set up port forwarding for the Tekton listeners and send
some plain `curl` commands:

Set up port forwarding for the event listeners:

```
kubectl port-forward -n vixi svc/el-kbuild-mirror-trigger-listener 9101:8080
kubectl port-forward -n vixi svc/el-kbuild-trigger-listener 9102:8080
```

To trigger Git mirror updates:

```
curl -d '{"tree": "torvalds", "url": "git://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"}' http://localhost:9101
```
