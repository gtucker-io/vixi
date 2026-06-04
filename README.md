VIXI · Virtual Kernel CI
========================

VIXI is a [Renelick](https://gitlab.com/gtucker.io/renelick) application to
continuously test the upstream Linux kernel in virtual environments.  It's
currently at the proof-of-concept stage although it can already produce some
useful results.

## Workflow

To keep things simple initially, only plain defconfig x86 builds are enabled
which allows for a streamlined pipeline to focus on feature development.
Coverage will then grow incrementally as things evolve to keep optimising the
whole design along the way.  The build then goes through a boot test using KVM
and KUnit is also run in parallel.

Here's the list of high-level features and their current status:

* ☐ revision trigger events
  * ☑ manual
  * ☐ new patch from email
  * ☐ Git tree polling
  * ☐ Git hook in remote repository
* ☑ kbuild pipeline
  * ☑ check out the Git revision with persistent mirror
  * ☑ build the kernel using a kernel.org toolchain
  * ☑ upload artifacts to storage via SSH
  * ☑ propagate build status
  * ☐ parse logs for warnings and errors
* ☑ kboot pipeline
  * ☑ boot a kernel image using KVM in KubeVirt
  * ☐ parse logs and look for any kernel errors
* ☐ kselftest task
  * boot and run some kselftests in a VM
  * ☐ parse results
* ☑ kunit task
  * ☑ check out the Git revision
  * ☑ run KUnit in a kernel.org toolchain
  * ☑ parse results
* ☐ static checks
  * ☐ checkpatch
  * ☐ TBD: define list of useful checks
* ☑ post-processing
  * ☑ compute delta between test results from two revisions
  * ☑ schedule extra tests to cover base commit with mainline
  * ☑ run Git automated bisection
  * ☐ run [Scalpel](https://gitlab.com/gtucker/scalpel) automated bisection
* ☐ email reports

## Test Coverage

The following builds with KVM boot and KUnit tests are available and run on
demand but not continuously yet:

* Cutting-edge compilers on linux-next (latest LLVM from kernel.org)
* Latest stable compiler on mainline (latest GCC from kernel.org + Rust)
* Oldest supported compiler on LTS

> **Note**: The plan is to use VIXI among other use-cases to help finalise
> Renelick v1.0-rc1.  Once this has been released, the API should become stable
> which would be a good point in time to enable continuous coverage in VIXI.

## Design Overview

When a new revision is found, which could be a series of patches via email, a
Git branch or anything of this kind, a trigger event is sent with the
corresponding information.  The orchestrator service then receives this event
and schedules all the tasks that match its configuration rules.  Typically,
this would be a kernel build and a KUnit run.  Some suitable schedulers need to
accept the tasks and run them in their dedicated runtime environment such as a
[Tekton pipeline](https://tekton.dev/docs/pipelines).  When each of them
completes, the orchestrator receives a corresponding event and may then
schedule downstream tasks.  For example, kernel builds are followed by a KVM
boot test in KubeVirt and all pipelines have a dedicated task to parse the
results and logs: build, boot, KUnit, kselftest etc.  Results are then added to
the database with a standard schema so they can be post-processed in a generic
way to detect regressions and run bisections.

The orchestrator rules can use any event and specify any fields that need to
match in the event data.  There are currently 3 categories of events, each sent
to their respective pub/sub channel: `node`, `task` and `vixi`.  Tekton
pipelines and other tasks produce some data nodes with results and artifacts.
An event is sent every time a node is created on the `node` channel which can
be used to trigger tasks in a data-driven way.  When tasks are scheduled, run,
complete or change state in any respect, events are sent to the `task` channel
which can be used to chain other tasks directly rather than relying on the data
they produce.  While this might be easier to set up, it is more fragile as it
relies on implicit expectations about what each task actually does.  Then the
VIXI application uses some specific events on the `vixi` channel to get the
initial trigger with a new revision to test or to send real-time updates while
tasks are running such as bisection iterations and progress.

Low-level tasks which require substantial compure power are run in the `tekton`
runtime to build kernels, boot them in KVM and run KUnit.  They produce some
raw data which then needs to be processed to determine whether things passed or
failed.  The post-processing is typically done in the `inline` runtime which
executes tasks directly in the Python process.  These tasks are meant to be
short-lived and last a few seconds at most or use small amounts of compute
resources.  For example, KUnit JSON results are processed inline once the
Tekton task has completed to create a tree of data nodes.  Bisection tasks are
run inline but stay around for a while as they need to maintain the Git bisect
state between each iteration.

Based on this, any behaviour or workflow can be configured.  A single revision
can trigger multiple builds, and each build can trigger multiple boots and
tests.  Initially, the pipelines will be doing only a linear series of tasks
with a single optimised path and then scale gradually.  Subsequent tests can be
run after a boot completes and other post-processing tasks may be run such as
bisections, statistics, log parsers, report generators etc.

### Checkouts with Git mirrors

For each tree, a mirror repository is kept in a read-only persistent volume
which is shared by all the runtime instances.  A Tekton task can be run at any
time to update a given mirror, typically daily.  Mirrors may also be deleted
from time to time to avoid keeping stale data or accumulating any other kind of
long-term decay.  These mirrors are then mounted in each task as a local volume
and used to speed up Git checkouts using `git clone --reference <mirror>`.

### Incremental builds with kernel.org toolchains

The assumption is that incremental builds are reliable as per the upstream
kernel standards.  As such, build directories are kept in a persistent volume
to be reused.  They should be unique at least for each combination of Git
branch, compiler version and CPU architecture to make the builds more likely to
be incremental.  Whenever a build failure is found, a subsequent pipeline
should be run with a full, clean build to confirm the error as part of the
post-processing checks.  This may also be done explicitly for particular
revisions e.g. daily linux-next or mainline tags.  The same applies to KUnit
tests as they include their own build.

A distinctive feature about the VIXI builds is that they rely solely on
[kernel.org toolchain containers](https://gitlab.com/gtucker/korg) as initially
proposed on
[LKML](https://lore.kernel.org/all/f80acb84-1d98-44d3-84b7-d976de77d8ce@gtucker.io/)
and at LPC 2024.  It's a first experimental step towards putting this in
practice and having it supported directly upstream.

### Booting with KVM

The current approach for booting kernels is via KVM and KubeVirt inside a
Tekton pipeline.  This involves a thinly wrapped Docker image around the kernel
image to boot the VM.  Support for other runtimes should be enabled too, for
example with KVM-enabled QEMU directly on a bare-metal host machine.  Then the
orchestrator can decide which runtime to use for each test and schedule tasks
accordingly.  The main advantage of KubeVirt is that the underlying Cloud
infrastructure can scale automatically.  An alternative kind of runtime could
be on-demand VMs in e.g. GCP to avoid the combined complexity of Kubernetes,
Tekton and KubeVirt but would require more low-level provisioning and resource
management.

Building upon this, other tests can be run in the same environment such as
kselftest or LTP.

## Setup

Deployment is meant to happen in a Kubernetes cluster.  Currently, minikube and
GKE are supported out of the box.  minikube is fine by default for development,
GKE is better suited for variable production workloads.

To create a minikube cluster, first make sure you've got
[Docker](https://docs.docker.com/engine/install/debian/) installed.  Then you
can run the installation script to set up the local cluster:

```
deploy/minikube
```

To create a GKE cluster, you'll need to provide a GCP project name, cluster
name and the region where to deploy it:

```
deploy/gke exp-001-430112 vixi-001 europe-west1-c
```

You'll then need to install the standard `kubectl` tool as per the [Kubernetes
documentation](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/#install-using-native-package-management)
to manage the cluster.

Make sure your cluster is the one currently selected with `kubectl use-context`
and deploy all the Kubernetes resources:

```
deploy/tekton
deploy/kubevirt
deploy/vixi
```

> **Note**: You can skip `deploy/kubevirt` if you don't want to run KVM runtime
> tests.  Builds and KUnit can still be run in Tekton without it.

As a special tip and to highlight the flexibility of Kubernetes deployments,
it's possible to use e.g. a laptop for develoment with the orchestrator and
monitor while deploying the schedulers on a fixed workstation to do the heavy
lifting.  This can be done by specifying the list of features to install with
`deploy/vixi`:

```
orchestrator monitor sched-inline sched-tekton sched-tekton-kvm
```

By default, everything gets deployed.  If KVM isn't supported, you can run the
script with all the other features listed on the command line.  It's also
possible to deploy just the lightweight services locally and Tekton on a
different machine, for example:

```
deploy/vixi orchestrator monitor sched-inline
```

```
deploy/vixi sched-inline sched-tekton
```

Any number of `sched-tekton` and `sched-inline` instances may be deployed as
Renelick tasks will only be accepted by one matching scheduler to provide
classic load balancing and redundancy.  Monitors can be deployed on each worker
machine too as they just read events and logs them locally.  There should
however be only one orchestrator service deployed, otherwise the rules will be
applied multiple times and tasks will be duplicated.

## Usage

Jobs are meant to be scheduled via the Renelick orchestrator deployed in
Kubernetes.  Individual low-level tasks can also be scheduled manually during
development.  To do this, you'll typically need to have the `renelick` client
either installed natively on your host machine or in a Docker image and use the
`renelick task run` command.  We'll first focus on the high-level approach
which relies on the orchestrator using VIXI events.

Updating Git mirrors is not done via the orchestrator as it's a property of
each local worker machine.  Instead, they can be run with `kubectl`:

```
kubectl create -f tekton/mirror-torvalds.yaml
```

Then to cause the orchestrator to trigger pipelines on a particular Git
revision, a VIXI event such as this one can be sent:

```
renelick send vixi event=trigger source=git tree=torvalds revision=v6.19-rc5
```

This will result in `kbuild` and `kunit` pipelines to be run in Tekton with
their subsequent tasks e.g. KVM boot and post-processing.

Now, to manually trigger a kernel build instead without going through the
orchestrator:

```
renelick task run tekton \
    name=kbuild \
    tree=torvalds \
    url=https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git \
    revision=master
```

Please note that tasks that are started manually still generate data and events
which may cause the orchestrator to run other tasks.  To avoid this, add an
`orch=debug` attribute to the task and the orchestrator will filter it out.  In
the example above, it would otherwise typically start a KVM boot pipeline when
the build completes.

## Demo time

A number of demos are provided to showcase how this all fits together:

1. [From Git to KUnit](/docs/demo-1-git-to-kunit/index.md)
1. [Delta and Git bisect](/docs/demo-2-delta-and-git-bisect/index.md)
1. [Automated replay](/docs/demo-3-automated-replay/index.md)
