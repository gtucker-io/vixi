VIXI Demo #1 – From Git to KUnit results
========================================

More than a plain example, this is an end-to-end demo to showcase what VIXI
currently does.  It uses a Renelick v0.21 instance and SSH to upload artifacts
to storage.  Many details are being omitted here for the sake of clarity.
Although all the code is available, it's not meant to be easily reproducible
locally.  A proper user guide will come later with setup instructions once this
has become more stable.

The assumption here is that all the VIXI services are up and running and
workspaces have been initialised with their local Git mirrors.  For the sake of
this demo, the kernel builds will be run in directories that have already been
built i.e. doing incremental builds with no source changes.  In fact this is
useful as it shows the shortest path to the results, except for KUnit tests
which do get run fully.  Actual build durations from scratch will depend
entirely on the underlying machines running them so it's not too relevant for
this demo.  The Renelick API and storage are hosted on remote servers while the
VIXI application is running in a local Minikube deployment on a regular laptop.

## Background logs

To better show what is going on, several real-time logs can be opened in
individual terminals.  To keep track of all the events, the standard Renelick
client-side monitor can be run to listen on the `node`, `task` and `vixi`
pub/sub channels:
```
$ rk service monitor task node vixi
2025-10-22T18:01:31.578966 I  API URL:    https://renelick.gtucker.io
2025-10-22T18:01:31.657015 I  Version:    Renelick API 0.21.0
2025-10-22T18:01:31.743982 I  Username:   gtucker
2025-10-22T18:01:31.744074 I  Email:      gtucker@gtucker.io
2025-10-22T18:01:31.744131 I  Channels:   task, node, vixi
```

Then the central component of VIXI is the Orchestrator, so we'll keep an eye on
its Kubernetes logs too:
```
$ kubectl logs -f deploy/orchestrator
2025-10-22T17:53:36.756199 I  VIXI Orchestrator
2025-10-22T17:53:36.935869 I  Config:     oconfig-2025-10-22T13:16:36.514214
2025-10-22T17:53:36.935953 I  API URL:    https://renelick.gtucker.io
2025-10-22T17:53:37.010622 I  Version:    Renelick API 0.21.0
2025-10-22T17:53:37.084745 I  Username:   vixi
2025-10-22T17:53:37.084851 I  Email:      vixi@renelick.org
```

> **Note**: The `Config` value shows the name of the data node containing the
> orchestrator [configuration](../vixi/oconfig.yaml).  We won't get into that
> here but it'll be covered in the documentation once is has stabilised.

> **Note**: The monitor service was started on my laptop with my personal user
> account `gtucker` whereas the orchestrator is running from the Kubernetes
> deployment with the dedicated `vixi` account.

## Overview

We'll be exercising a full set of tasks, starting with a basic trigger event
pointing at a kernel Git repository.  The orchestrator will then schedule both
a kernel build and a KUnit run in parallel in Tekton.  These tasks will produce
data nodes and generate events which will in turn cause the orchestrator to
schedule some follow-up tasks.  In particular, it will schedule a KVM boot in
Tekton using KubeVirt when the kernel image is available and a task directly on
a Kubernetes pod to parse the KUnit results when the plain JSON results are
available.  So here's a simplified version of the orchestration logic:

* trigger event ⇒ kbuild, kunit
* kbuild kernel image ⇒ kboot
* kunit JSON results ⇒ kunit-parser

## Initial trigger event

First, let's manually send the initial event which will get everything going.
We'll pick the `next-20251022` tag of the `linux-next` tree:
```
$ rk event send vixi event=trigger source=git tree=next revision=next-20251022
f4f2294f-51c4-4840-855d-c7daf7a7b4fd
```
This event can be seen in the monitor:
```
2025-10-22T18:10:44.993601 I  EVENT vixi          f4f2294f-51c4-4840-855d-c7daf7a7b4fd  {'source': '/event', 'type': 'renelick.api'}
```

Then the orchestrator receives the event and schedules the `kbuild` and `kunit`
tasks as per its configuration:
```
2025-10-22T18:10:45.088009 I  kbuild-next-next-20251022                         6685d1f3-fd6d-49cf-a8a7-83208e4f9d71
2025-10-22T18:10:45.169312 I  kunit-next-next-20251022                          462bece4-0808-49e9-9111-e5abe9055285
```
In turn, we can see these events in the monitor:
```
2025-10-22T18:10:45.207940 I  TASK  add           6685d1f3-fd6d-49cf-a8a7-83208e4f9d71  tekton        kbuild
2025-10-22T18:10:45.324539 I  TASK  accept        6685d1f3-fd6d-49cf-a8a7-83208e4f9d71  tekton        kbuild
2025-10-22T18:10:45.523396 I  TASK  add           462bece4-0808-49e9-9111-e5abe9055285  tekton        kunit
2025-10-22T18:10:45.637223 I  TASK  accept        462bece4-0808-49e9-9111-e5abe9055285  tekton        kunit
```
These tasks are running in Tekton and we can see the pipelines there too with
the `tkn` command line tool:
```
$ tkn pipelinerun list
NAME                              STARTED          DURATION   STATUS
kbuild-next-next-20251022-jztbf   12 seconds ago   ---        Running
kunit-next-next-20251022-475dp    12 seconds ago   ---        Running
```

## `kbuild`

These two pipelines will keep running in parallel, creating nodes and uploading
artifacts at every step.  They are designed to just get the low-level work done
without any added logic or post-processing.  We can track their progress via
the monitor log:
```
2025-10-22T18:11:14.196547 I  NODE  add           68f91df633354f99ac6e2f42              vixi.kunit    next:next-20251022:checkout
2025-10-22T18:11:15.134294 I  NODE  add           68f91df733354f99ac6e2f43              vixi.kbuild   next:next-20251022:checkout
2025-10-22T18:11:15.404516 I  NODE  add           68f91df733354f99ac6e2f44              artifact-v1   checkout.txt
2025-10-22T18:11:15.818030 I  NODE  add           68f91df733354f99ac6e2f45              artifact-v1   checkout.sh
2025-10-22T18:11:16.188680 I  NODE  add           68f91df833354f99ac6e2f46              artifact-v1   checkout.txt
2025-10-22T18:11:16.562908 I  NODE  add           68f91df833354f99ac6e2f47              artifact-v1   checkout.sh
2025-10-22T18:11:23.723650 I  NODE  add           68f91dff33354f99ac6e2f48              vixi.kbuild   next:next-20251022:defconfig
2025-10-22T18:11:24.822422 I  NODE  add           68f91e0033354f99ac6e2f49              artifact-v1   defconfig.sh
2025-10-22T18:11:25.239192 I  NODE  add           68f91e0133354f99ac6e2f4a              artifact-v1   defconfig
2025-10-22T18:11:25.673446 I  NODE  add           68f91e0133354f99ac6e2f4b              artifact-v1   defconfig.txt
2025-10-22T18:11:38.452742 I  NODE  add           68f91e0e33354f99ac6e2f4c              vixi.kunit    next:next-20251022:build
2025-10-22T18:11:39.581903 I  NODE  add           68f91e0f33354f99ac6e2f4d              artifact-v1   build.sh
2025-10-22T18:11:39.975677 I  NODE  add           68f91e0f33354f99ac6e2f4e              artifact-v1   build.txt
2025-10-22T18:11:40.403290 I  NODE  add           68f91e1033354f99ac6e2f4f              artifact-v1   defconfig
2025-10-22T18:11:41.922755 I  NODE  add           68f91e1133354f99ac6e2f50              artifact-v1   bzImage
2025-10-22T18:11:57.011602 I  NODE  add           68f91e2033354f99ac6e2f51              vixi.kbuild   next:next-20251022:image
2025-10-22T18:11:58.441286 I  NODE  add           68f91e2233354f99ac6e2f52              artifact-v1   image.sh
2025-10-22T18:11:58.781995 I  NODE  add           68f91e2233354f99ac6e2f53              artifact-v1   image.txt
2025-10-22T18:12:00.054312 I  NODE  add           68f91e2333354f99ac6e2f54              artifact-v1   bzImage
2025-10-22T18:12:07.283036 I  NODE  add           68f91e2b33354f99ac6e2f55              vixi.kbuild   next:next-20251022:modules
2025-10-22T18:12:08.273573 I  NODE  add           68f91e2c33354f99ac6e2f56              vixi.docker   next:next-20251022:docker
```

The `vixi.kbuild` and `vixi.kunit` nodes contain summaries of the individual
steps of the `kbuild` and `kunit` pipelines respectively.  So when a node
appears, it means the step has completed.

All the `artifact-v1` nodes are individual artifact files that have been
uploaded to storage.  Each step is typically run in a script and produces a log
file in addition to any generated files.  So the kernel image build is run from
the `image.sh` script, the output log is `image.txt` and the generated artifact
is `bzImage` in this case.  All the artifact nodes have the step summary node
as their parent, for example with the `next:next-20251022:image` node:
```
$ rk node find parent=68f91e2033354f99ac6e2f51 kind=artifact-v1 | jq '.[].data'
```
``` json
{
  "url": "https://storage.gtucker.io/next/next-20251022/kbuild/6685d1f3-fd6d-49cf-a8a7-83208e4f9d71/image.sh",
  "storage": "gtucker.io"
}
{
  "url": "https://storage.gtucker.io/next/next-20251022/kbuild/6685d1f3-fd6d-49cf-a8a7-83208e4f9d71/image.txt",
  "storage": "gtucker.io"
}
{
  "url": "https://storage.gtucker.io/next/next-20251022/kbuild/6685d1f3-fd6d-49cf-a8a7-83208e4f9d71/bzImage",
  "storage": "gtucker.io"
}
```
Using a shortcut for downloading an artifact from a data node, we can also get
the build log directly from its ID rather than the full URL.  For example, to
get the image build log:
```
$ rk storage get-artifact 68f91e2233354f99ac6e2f53 | tail
  LD      arch/x86/boot/compressed/vmlinux
  ZOFFSET arch/x86/boot/zoffset.h
  OBJCOPY arch/x86/boot/vmlinux.bin
  AS      arch/x86/boot/header.o
  LD      arch/x86/boot/setup.elf
  OBJCOPY arch/x86/boot/setup.bin
  BUILD   arch/x86/boot/bzImage
Kernel: arch/x86/boot/bzImage is ready  (#6)
make[1]: Leaving directory '/workspace/sandbox/kbuild/next/build/x86_64/gcc-15.2'
```

# `kboot`

Then the node of the `vixi.docker` kind which appears at the bottom of the log
excerpt is created once a Docker image itself containing the kernel image is
available.  This is used by KubeVirt to boot a custom kernel in Kubernetes.
Let's take a look at its data:
```
$ rk node get 68f91e2c33354f99ac6e2f56 | jq .data
```
``` json
{
  "image": "docker.io/gtucker/kernel-image:6685d1f3-fd6d-49cf-a8a7-83208e4f9d71",
  "revision": {
    "sha1": "aaa9c3550b60d6259d6ea8b1175ade8d1242444e",
    "describe": "next-20251022",
    "subject": "Add linux-next specific files for 20251022",
    "tree": "next",
    "url": "https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
  },
  "params": {
    "arch": "x86_64",
    "defconfig": "defconfig",
    "opts": "",
    "cc": "gcc",
    "ccver": "15.2",
    "ccarch": "-x86"
  }
}
```

> **Note**: These kernel Docker images aren't actually pushed to docker.io as
> the KubeVirt pipeline will be running on the same node as where the image was
> built.  A full production deployment with more distributed infrastructure
> would need to go via an actual image registry.

This causes the orchestrator to start a `kboot` task to boot the kernel:
```
2025-10-22T18:12:08.441016 I  kboot-next-next-20251022-x86_64-gcc-15.2          3a4afb2e-78e7-4142-af18-1724666c6561
```
which can be seen in the monitor logs, intertwined here with the modules build
artifacts as it ran in parallel with the Docker image step:
```
2025-10-22T18:12:08.401277 I  NODE  add           68f91e2c33354f99ac6e2f57              artifact-v1   modules.txt
2025-10-22T18:12:08.568693 I  TASK  add           3a4afb2e-78e7-4142-af18-1724666c6561  tekton        kboot
2025-10-22T18:12:08.692554 I  TASK  accept        3a4afb2e-78e7-4142-af18-1724666c6561  tekton        kboot
2025-10-22T18:12:08.748374 I  NODE  add           68f91e2c33354f99ac6e2f58              artifact-v1   modules.sh
2025-10-22T18:12:09.167334 I  NODE  add           68f91e2d33354f99ac6e2f59              artifact-v1   modules.tar.gz
2025-10-22T18:12:14.897329 I  TASK  complete      6685d1f3-fd6d-49cf-a8a7-83208e4f9d71  tekton        kbuild
```

The `kbuild` pipeline has now completed.  This took place while the `kboot`
pipeline was starting since it was triggered as soon as the kernel Docker image
was available and the modules aren't currently covered by `kboot`.  In
parallel, the `kunit` pipeline is going through its own steps too but we'll
look into them in the next section.

Here's the rest of the monitor log:
```
2025-10-22T18:12:48.171597 I  NODE  add           68f91e5433354f99ac6e2f5a              vixi.kboot    kboot
2025-10-22T18:12:50.799880 I  NODE  add           68f91e5633354f99ac6e2f5b              artifact-v1   cpuinfo.txt
2025-10-22T18:12:53.519007 I  NODE  add           68f91e5933354f99ac6e2f5c              artifact-v1   meminfo.txt
2025-10-22T18:12:56.029183 I  NODE  add           68f91e5b33354f99ac6e2f5d              artifact-v1   dmesg.txt
2025-10-22T18:12:56.397303 I  NODE  add           68f91e5c33354f99ac6e2f5e              vixi.kunit    next:next-20251022:exec
2025-10-22T18:12:57.520291 I  NODE  add           68f91e5d33354f99ac6e2f5f              artifact-v1   exec.sh
2025-10-22T18:12:57.907943 I  NODE  add           68f91e5d33354f99ac6e2f60              artifact-v1   exec.txt
2025-10-22T18:12:58.284402 I  NODE  add           68f91e5e33354f99ac6e2f61              artifact-v1   kunit.json
2025-10-22T18:12:58.680558 I  TASK  add           10ee73fd-d992-4f0f-ab57-3374aafe9ea0  inline-vixi   kunit-parser
2025-10-22T18:12:58.796751 I  TASK  accept        10ee73fd-d992-4f0f-ab57-3374aafe9ea0  inline-vixi   kunit-parser
2025-10-22T18:13:00.958653 I  NODE  populate      68f91e5f33354f99ac6e2f62              vixi.group    kunit
2025-10-22T18:13:01.151431 I  TASK  complete      10ee73fd-d992-4f0f-ab57-3374aafe9ea0  inline-vixi   kunit-parser
2025-10-22T18:13:01.620033 I  TASK  complete      3a4afb2e-78e7-4142-af18-1724666c6561  tekton        kboot
2025-10-22T18:13:03.719315 I  TASK  complete      462bece4-0808-49e9-9111-e5abe9055285  tekton        kunit
```

The `kboot` pipeline starts a VM using KubeVirt, boots the kernel and runs some
very basic commands.  It produces several artifacts: `cpuinfo.txt`,
`meminfo.txt` and `dmesg.txt`.  Let's take a look at the boot log from `dmesg`:
```
$ rk storage get-artifact 68f91e5b33354f99ac6e2f5d | head -n4
[    0.000000] Linux version 6.18.0-rc2-next-20251022 (kbuild@kbuild-next-next-20251022-jztbf-image-pod) (x86_64-linux-gcc (GCC) 15.2.0, GNU ld (GNU Binutils) 2.45) #6 SMP PREEMPT_DYNAMIC Wed Oct 22 18:11:34 UTC 2025
[    0.000000] Command line: console=ttyS0 root=/dev/vda1 rw setenforce 0
[    0.000000] BIOS-provided physical RAM map:
[    0.000000] BIOS-e820: [mem 0x0000000000000000-0x000000000009fbff] usable
```

Nothing gets further triggered by the orchestrator from the `kboot` pipeline
for now.  Typically, a follow-up task would be needed to look at the results,
parse the logs to find kernel errors, report regressions, send notification
emails and start bisections if something was found.

## `kunit`

Meanwhile, the `kunit` pipeline also completed with its own steps all run with
QEMU in regular Tekton (no KubeVirt or KVM here).  As soon as the `kunit.json`
artifact became available, the `kunit-parser` task was scheduled by the
Orchestrator to run directly on a Kubernetes node to parse the results and
produce data nodes:

> **Note**: KUnit is often run in User-Mode Linux rather than with a true
> hardware CPU architecture.  However, the VIXI builds rely entirely on the
> toolchains from kernel.org which can only be used to build kernels and not
> user-space executables.  As a result, it falls back to the QEMU approach
> which is fine when using plain containers with no KVM acceleration.

```
2025-10-22T18:12:58.538320 I  kunit-parser-next-next-20251022-gcc               10ee73fd-d992-4f0f-ab57-3374aafe9ea0
```

The monitor logs show that this task was run by the `inline-vixi` scheduler
whereas the other tasks were run by `tekton`.  It was scheduled at `18:12:58`
and completed at `18:13:01` so took about 3 seconds to start, download the JSON
file, parse it and upload a tree of about 800 data nodes with the results to
the API.  Again, both the API and storage services are hosted on a remote
machine so it's a pretty fair representation of the latencies involved.

We can see when the `kboot` and `kunit` tasks finally complete, at `18:13:03`.
The initial trigger event was sent at `18:10:44` so this entire process, from
checkout to build, boot and KUnit results took just under 2 minutes and 30
seconds.  The steps to upload artifacts and send data nodes are run in parallel
with the next kernel build ones, for example the kernel image build starts
while the defconfig files are still being uploaded to reduce the overall
pipeline duration.

While this isn't a reliable benchmark as it's using Minikube in a noisy laptop
environment, it gives an idea of the capability of the sytem.  With a
reasonably fast machine e.g. a 16-core Cloud VM, some fresh kernel builds for
both `kbuild` and `kunit` could complete within 5 minutes taking the full
duration to less than 10 minutes.

## Show me some data

Each result node has its task object populated so we can easily count
the ones that were created by the `kunit-parser` task:
```
$ rk node count task.id=10ee73fd-d992-4f0f-ab57-3374aafe9ea0
836
```

The top-level "root" node ID is `68f91e5f33354f99ac6e2f62`.  Let's start from
there and take a look at a specific test case result somewhere within the tree:
```
$ rk node find parent=68f91e5f33354f99ac6e2f62 --limit=4 | jq -r '.[] | "\(.name) \(.id)"'
example_init 68f91e5f33354f99ac6e2f63
miscdev_init 68f91e5f33354f99ac6e2f65
printk-ringbuffer 68f91e5f33354f99ac6e2f71
irq_test_cases 68f91e5f33354f99ac6e2f73
```

Taking the `irq_test_cases` group of result, we can fetch one random test case
from its child nodes:
```
$ rk node find parent=68f91e5f33354f99ac6e2f73 --limit=1
```
``` json
[
  {
    "id": "68f91e5f33354f99ac6e2f74",
    "name": "irq_disable_depth_test",
    "lineage": [
      "68f91df633354f99ac6e2f42",
      "68f91e0e33354f99ac6e2f4c",
      "68f91e5c33354f99ac6e2f5e",
      "68f91e5f33354f99ac6e2f62",
      "68f91e5f33354f99ac6e2f73",
      "68f91e5f33354f99ac6e2f74"
    ],
    "path": [
      "next:next-20251022:checkout",
      "next:next-20251022:build",
      "next:next-20251022:exec",
      "kunit",
      "irq_test_cases",
      "irq_disable_depth_test"
    ],
    "created": "2025-10-22T18:11:43.155000",
    "owner": {
      "email": "vixi@renelick.org",
      "username": "vixi",
      "full_name": "VIXI Service Account"
    },
    "parent": "68f91e5f33354f99ac6e2f73",
    "kind": "vixi.test",
    "data": {
      "result": "pass"
    },
    "task": {
      "attributes": {
        "name": "kunit-parser",
        "artifact": "68f91e5e33354f99ac6e2f61",
        "parent": "68f91e5c33354f99ac6e2f5e"
      },
      "scheduler": "inline-vixi",
      "id": "10ee73fd-d992-4f0f-ab57-3374aafe9ea0",
      "timeout": "2025-10-22T18:27:58.453000"
    }
  }
]
```

This could also be found using the `task.id` and `name` attributes:
```
$ rk node find task.id=10ee73fd-d992-4f0f-ab57-3374aafe9ea0 name=irq_disable_depth_test
```

## Next steps

As with the `kbuild` and `kboot` pipelines, the `kunit` results aren't
processed further than that.  The next logical steps here would be to look for
any failed test cases, compare them with previous results to detect new
failures, send notification emails, schedule bisections and any other
post-processing task according to the outcome.  That's for the next demo!
