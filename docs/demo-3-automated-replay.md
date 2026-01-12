VIXI Demo No.3 – Automated replay
=================================

In the [previous demo](demo-2-delta-and-git-bisect.md) we saw how the `delta`
and `bisect` post-processing features can detect differences in test results
and isolate the commits that caused them.  It was an early proof of concept and
hard-coded to only work with KUnit.  In this demo, we'll see how the task
definitions have been improved to be able to replay any sequence of tasks while
changing some arbitrary parameters.  In particular, the `bisect` logic will now
automatically discover how to reproduce KUnit results and plain builds with
different kernel revisions just by inspecting existing data.  Let's dive in!

## Task inputs

A key principle of Renelick is to run tasks when some particular kind of data
nodes are created.  As such, we need a way to specify these input nodes for
each task.  The VIXI orchestrator already does this using the
[`oconfig.yaml`](/vixi/oconfig.yaml) file although part of the logic is done
directly in the event handler implementation.  For example, the config says
that the `kunit-parser` task should be run when the `kunit` task has completed
but the information about passing the results JSON artifact is buried inside
the code.

> **Note**: Relying more on `oconfig.yaml` and less on the code would in fact
> be an improvement for a future version, this is still under development.

Regardless of how the tasks were created, it's ideal to make them
self-contained and directly include the information required to run them again
outside of the orchestrator.  Tasks already contain scheduler information as
part of their native schema, but that's not quite enough.  The VIXI approach is
to add attributes to describe the `input-nodes` and the `timeout-spec`.  This
is done entirely on the application side with the standard Renelick API.

The "replay" feature starts with a tree of result nodes we want to be able to
reproduce.  It then walks its way back through the linage and determines the
various tasks that created each node until it gets to the root.  In practice,
this is what it looks like for KUnit from checkout to delta with a failing
test:

```
NAME                                        KIND             TASK
------------------------------------------------------------------------------
gtucker:v6.19-rc3-4-gb1d2fdbfdf5f:checkout  vixi.kunit.step  kunit
gtucker:v6.19-rc3-4-gb1d2fdbfdf5f:build     vixi.kunit.step  kunit
gtucker:v6.19-rc3-4-gb1d2fdbfdf5f:exec      vixi.kunit.step  kunit
kunit                                       vixi.group       kunit-parser
overflow                                    vixi.group       kunit-parser
shift_sane_test                             vixi.test        kunit-parser
shift_sane_test:break                       vixi.delta       delta
```

We can see that the `delta` task produced a `vixi.delta` node with the
information about the failing test.  The 3 parent nodes are either `vixi.test`
or `vixi.group` ones and were all produced by the `kunit-parser` task.  Then
likewise, their `vixi.kunit.step` parents were produced by the `kunit` task.
The first of these steps is `checkout` which is the root node here with no
parent and therefore no input node: this is where we'll start.  Let's take a
look at the original `kunit` task:

``` json
  "task": {
    "name": "kunit",
    "attributes": {
      "tree": "gtucker",
      "url": "https://gitlab.com/gtucker/linux.git",
      "revision": "linux-6.19-rc3-kunit-fail",
      "filter": "",
      "orch": "vixi",
      "timeout-spec": {
        "minutes": 90
      }
    },
    "scheduler": "tekton",
    "id": "0365a602-7c45-40ad-880a-c04795ee53db",
    "timeout": "2026-01-12T18:50:01.099000"
  }
```

A few things need to be done before we can schedule our new task, say if we're
running a bisection:

* To pick another commit on the same branch, we can simply replace the
  `revision` value with the Git SHA1 given by `git bisect`.
* The task `name` and `scheduler` should be left as-is.
* The `orch` attribute should be changed to `bisect` so that the main `vixi`
  orchestrator rules don't apply (e.g. we don't want an email report sent for
  each bisection step).
* The `timeout-spec` attribute tells us how to determine the new `timeout`
  value, 90 minutes from now.
* The `filter` attribute should contain the name of the test being bisected in
  dotted syntax (e.g. `"overflow"."shift_sane_test"`) to avoid running the
  entire test suite if possible.
* The `id` will be automatically generated when scheduling the new task.

> **Note**: The same logic can be used to replay tasks with other arbitrary
> parameters, for example `kbuild` could be run with a different toolchain
> version to compare the results.

Once this task has completed, we can look at the original `kunit-parser`
definition to determine what to do next:

``` json
  "task": {
    "name": "kunit-parser",
    "attributes": {
      "orch": "vixi",
      "input-nodes": {
        "artifact": {
          "id": "69652dbe67ff704f772f8d00",
          "kind": "artifact-v1",
          "name": "kunit.json"
        }
      },
      "timeout-spec": {
        "minutes": 15
      }
    },
    "scheduler": "inline-vixi",
    "id": "9ba6a2d9-72a1-49e4-bcfc-aca0325874b7",
    "timeout": "2026-01-12T17:38:36.756000"
  }
```

There's no revision to change here as this was only relevant during checkout.
One difference is that we now need to find the input node.  This could be done
manually via the CLI, if we replace `<UUID>` with the generated id of the first
`kunit` task we just ran:

```
renelick node find kind=artifact-v1 name=kunit.json task.id=<UUID>
```

The replay feature used by `bisect` does something similar using the API Python
bindings directly.  It then works out the values of all the fields as described
earlier and replaces the artifact node id with the one it just found to
schedule the new `kunit-parser` task.  It can then wait for it to complete and
take a look at the results again.

## Bisection in action

To illustrate this a bit further, let's consider a full example using a branch
that introduces a KUnit test failure on purpose.  This is similar to the
previous demo:

```
$ git log --oneline --no-decorate v6.19-rc3^..gtucker/linux-6.19-rc3-kunit-fail
b1d2fdbfdf5f HACK BISECT 4.noop
9e1c130d734e HACK BISECT 3.noop
76819e0f306e HACK fail KUnit overflow.shift_sane_test
71746a491c0f HACK BISECT 1.noop
f8f9c1f4d0c7 Linux 6.19-rc3
```

Looking at the VIXI [monitor log](demo-3-monitor-log.txt) we can notice a few
key events:

```
I  2026-01-12T17:18:39.505717+00:00 VIXI   trigger       gtucker                               git                 linux-6.19-rc3-kunit-fail
I  2026-01-12T17:18:39.874351+00:00 TASK   add           0365a602-7c45-40ad-880a-c04795ee53db  tekton              kunit
I  2026-01-12T17:18:39.878066+00:00 TASK   receive       0365a602-7c45-40ad-880a-c04795ee53db  tekton              kunit
I  2026-01-12T17:18:39.918199+00:00 TASK   ack           0365a602-7c45-40ad-880a-c04795ee53db  tekton              kunit
```

Here, the trigger was sent to point at the branch we want to test and a `kunit`
task was scheduled by the orchestrator.

The `ack` event is a new one to help solve infrastructure issues, for example
if the Tekton trigger listener loses a message.  It has a short timeout of
typically one minute after which the task may be retried by the API or aborted.

A `kbuild` task was also run in parallel but we'll ignore it in this example.
One thing worth mentioning is that it got retried, which illustrates the value
of the `ack` event:

```
I  2026-01-12T17:18:39.772086+00:00 TASK   add           45846319-929d-4fe2-b128-4965ca1360b7  tekton              kbuild
I  2026-01-12T17:18:39.778631+00:00 TASK   receive       45846319-929d-4fe2-b128-4965ca1360b7  tekton              kbuild
I  2026-01-12T17:19:45.221861+00:00 TASK   retry         45846319-929d-4fe2-b128-4965ca1360b7  tekton              kbuild
I  2026-01-12T17:19:45.224168+00:00 TASK   receive       45846319-929d-4fe2-b128-4965ca1360b7  tekton              kbuild
I  2026-01-12T17:19:45.262758+00:00 TASK   ack           45846319-929d-4fe2-b128-4965ca1360b7  tekton              kbuild
I  2026-01-12T17:21:26.269820+00:00 TASK   complete      45846319-929d-4fe2-b128-4965ca1360b7  tekton              kbuild
```

Back to our KUnit example, we can see further down when the plain JSON results
are in:

```
I  2026-01-12T17:22:05.844831+00:00 NODE   add           69652dbd67ff704f772f8cfe              vixi.kunit.step     gtucker:v6.19-rc3-4-gb1d2fdbfdf5f:exec
I  2026-01-12T17:22:06.426290+00:00 NODE   add           69652dbe67ff704f772f8cff              artifact-v1         exec.txt
I  2026-01-12T17:22:06.531947+00:00 NODE   add           69652dbe67ff704f772f8d00              artifact-v1         kunit.json
I  2026-01-12T17:22:06.665331+00:00 NODE   add           69652dbe67ff704f772f8d01              artifact-v1         exec.sh
I  2026-01-12T17:22:14.847210+00:00 TASK   complete      0365a602-7c45-40ad-880a-c04795ee53db  tekton              kunit
```

The orchestrator then starts a `kunit-parser` task which populates the result
nodes, followed by a `delta` task which finds the failing test as expected:

```
I  2026-01-12T17:22:15.510677+00:00 TASK   add           9ba6a2d9-72a1-49e4-bcfc-aca0325874b7  inline-vixi         kunit-parser
I  2026-01-12T17:22:18.566051+00:00 NODE   populate      69652dc867ff704f772f8d02              batch:1             kunit
I  2026-01-12T17:22:18.741926+00:00 TASK   complete      9ba6a2d9-72a1-49e4-bcfc-aca0325874b7  inline-vixi         kunit-parser
I  2026-01-12T17:22:18.942489+00:00 TASK   add           72e89f23-7f09-4cca-835f-11bb96ee3f68  inline-vixi         delta
I  2026-01-12T17:22:21.857355+00:00 TASK   complete      72e89f23-7f09-4cca-835f-11bb96ee3f68  inline-vixi         delta
I  2026-01-12T17:22:21.821146+00:00 NODE   populate      69652dcd67ff704f772f9080              batch:1             shift_sane_test:break
```

See the [delta node JSON](demo-3-delta-node.json) for the full object.  It then
starts a `bisect` task for this failing test which goes away and finds the
breaking individual commit (dropping many events for clarity here):

```
I  2026-01-12T17:22:22.251833+00:00 TASK   add           0c8ab94d-290f-48be-8090-683c0da56c5d  inline-vixi         bisect
I  2026-01-12T17:22:23.532738+00:00 VIXI   bisect        v6.19-rc3-4-gb1d2fdbfdf5f             check:bad           b1d2fdbfdf5f9d869bea4714c3e00c5cb3faea38
I  2026-01-12T17:23:49.670967+00:00 VIXI   bisect        v6.19-rc3-4-gb1d2fdbfdf5f             check:good          f8f9c1f4d0c7a64600e2ca312dec824a0bc2f1da
I  2026-01-12T17:25:18.153491+00:00 VIXI   bisect        v6.19-rc3-4-gb1d2fdbfdf5f             iter  1/2           76819e0f306e1d1682ffcdeba5cd408c0eeb85c5
I  2026-01-12T17:26:43.290082+00:00 VIXI   bisect        v6.19-rc3-4-gb1d2fdbfdf5f             iter  2/2           71746a491c0f6557d43047dc9eca5f0a5613f37c
I  2026-01-12T17:28:09.578434+00:00 VIXI   bisect        v6.19-rc3-4-gb1d2fdbfdf5f             found               76819e0f306e1d1682ffcdeba5cd408c0eeb85c5
I  2026-01-12T17:28:09.907141+00:00 NODE   add           69652f2967ff704f772f9115              vixi.bisect         bisect:76819e0f306e1d1682ffcdeba5cd408c0eeb85c5
I  2026-01-12T17:28:10.478395+00:00 NODE   add           69652f2a67ff704f772f9116              artifact-v1         bisect.txt
I  2026-01-12T17:28:10.530563+00:00 TASK   complete      0c8ab94d-290f-48be-8090-683c0da56c5d  inline-vixi         bisect
```

Each iteration goes through the same series of tasks as the orchestrator would
have run, except it's now managed by the `bisect` task as replays.  Here's one
for example:

```
I  2026-01-12T17:25:18.153491+00:00 VIXI   bisect        v6.19-rc3-4-gb1d2fdbfdf5f             iter  1/2           76819e0f306e1d1682ffcdeba5cd408c0eeb85c5
I  2026-01-12T17:25:18.426504+00:00 TASK   add           56a462d0-c7e1-4b75-805d-b3fbcdac618f  tekton              kunit
I  2026-01-12T17:25:18.431137+00:00 TASK   receive       56a462d0-c7e1-4b75-805d-b3fbcdac618f  tekton              kunit
I  2026-01-12T17:25:18.490985+00:00 TASK   ack           56a462d0-c7e1-4b75-805d-b3fbcdac618f  tekton              kunit
I  2026-01-12T17:25:43.483090+00:00 NODE   add           69652e9767ff704f772f90cd              vixi.kunit.step     gtucker:v6.19-rc3-2-g76819e0f306e:checkout
I  2026-01-12T17:25:44.081419+00:00 NODE   add           69652e9867ff704f772f90ce              artifact-v1         checkout.sh
I  2026-01-12T17:25:44.224660+00:00 NODE   add           69652e9867ff704f772f90cf              artifact-v1         checkout.txt
I  2026-01-12T17:26:22.212244+00:00 NODE   add           69652ebe67ff704f772f90d0              vixi.kunit.step     gtucker:v6.19-rc3-2-g76819e0f306e:build
I  2026-01-12T17:26:22.858207+00:00 NODE   add           69652ebe67ff704f772f90d1              artifact-v1         defconfig
I  2026-01-12T17:26:22.999513+00:00 NODE   add           69652ebe67ff704f772f90d2              artifact-v1         build.txt
I  2026-01-12T17:26:23.142182+00:00 NODE   add           69652ebf67ff704f772f90d3              artifact-v1         build.sh
I  2026-01-12T17:26:23.325233+00:00 NODE   add           69652ebf67ff704f772f90d4              artifact-v1         bzImage
I  2026-01-12T17:26:33.236907+00:00 NODE   add           69652ec967ff704f772f90d5              vixi.kunit.step     gtucker:v6.19-rc3-2-g76819e0f306e:exec
I  2026-01-12T17:26:33.825461+00:00 NODE   add           69652ec967ff704f772f90d6              artifact-v1         exec.txt
I  2026-01-12T17:26:33.926415+00:00 NODE   add           69652ec967ff704f772f90d7              artifact-v1         kunit.json
I  2026-01-12T17:26:34.071373+00:00 NODE   add           69652eca67ff704f772f90d8              artifact-v1         exec.sh
I  2026-01-12T17:26:41.608714+00:00 TASK   complete      56a462d0-c7e1-4b75-805d-b3fbcdac618f  tekton              kunit
I  2026-01-12T17:26:42.131412+00:00 TASK   add           d12f54f3-a02a-482a-ad48-99c08bcee67f  inline-vixi         kunit-parser
I  2026-01-12T17:26:42.137969+00:00 TASK   receive       d12f54f3-a02a-482a-ad48-99c08bcee67f  inline-vixi         kunit-parser
I  2026-01-12T17:26:42.532926+00:00 NODE   populate      69652ed267ff704f772f90d9              batch:1             kunit
I  2026-01-12T17:26:42.192877+00:00 TASK   ack           d12f54f3-a02a-482a-ad48-99c08bcee67f  inline-vixi         kunit-parser
I  2026-01-12T17:26:42.585107+00:00 TASK   complete      d12f54f3-a02a-482a-ad48-99c08bcee67f  inline-vixi         kunit-parser
```

We now have a `vixi.bisect` additional node in the lineage with the result, see
the [bisect node JSON](demo-3-bisect-node.json) for the full object:

``` json
  "data": {
    "root": "kunit",
    "path": [
      "overflow",
      "shift_sane_test"
    ],
    "params": {
      "arch": "x86_64",
      "defconfig": "defconfig",
      "opts": "",
      "cc": "gcc",
      "ccver": "15.2",
      "ccarch": "-x86"
    },
    "revision": {
      "sha1": "76819e0f306e1d1682ffcdeba5cd408c0eeb85c5",
      "describe": "v6.19-rc3-2-g76819e0f306e",
      "subject": "HACK fail KUnit overflow.shift_sane_test",
      "tree": "gtucker",
      "url": "https://gitlab.com/gtucker/linux.git"
    },
    "history": [...]
  }
```

And more importantly, this showed how it could automatically replay arbitrary
tasks at every iteration and in any runtime: KUnit is running in Tekton and the
parser as a plain Python module in the `inline` runtime.

## Bonus: kbuild bisection

To have more than one sample in our experiment, let's also take a quick look at
a `kbuild` bisection.  This uses exactly the same logic and the same code which
is now agnostic of the test or task being bisected.  The `delta` and `bisect`
features can deal with anything that follows the convention of defining
`input-nodes` in the task attributes and produces `vixi.group` and `vixi.test`
nodes with the results:

```
I  2026-01-12T19:53:37.966950+00:00 VIXI   trigger       gtucker                               git                 linux-6.19-rc5-kbuild-break
I  2026-01-12T19:53:38.086273+00:00 TASK   add           32bdfc5f-cbdc-43dc-bda8-6f19340f4a26  tekton              kbuild
I  2026-01-12T19:54:05.086624+00:00 NODE   add           6965515d67ff704f772f911a              vixi.kbuild.step    gtucker:v6.19-rc5-6-g4fbb47471cc1:checkout
I  2026-01-12T19:54:22.648991+00:00 NODE   add           6965516e67ff704f772f911d              vixi.kbuild.step    gtucker:v6.19-rc5-6-g4fbb47471cc1:defconfig
I  2026-01-12T19:55:59.860222+00:00 NODE   add           696551cf67ff704f772f9124              vixi.kbuild.step    gtucker:v6.19-rc5-6-g4fbb47471cc1:image
I  2026-01-12T19:56:00.503140+00:00 NODE   add           696551d067ff704f772f9125              artifact-v1         image.txt
I  2026-01-12T19:56:00.651056+00:00 NODE   add           696551d067ff704f772f9126              artifact-v1         image.sh
I  2026-01-12T19:56:06.919688+00:00 NODE   populate      696551d667ff704f772f9127              batch:1             kbuild
I  2026-01-12T19:56:07.129054+00:00 TASK   add           f7dcf35d-9123-44ef-bf1a-7124e0255a72  inline-vixi         delta
I  2026-01-12T19:56:07.780093+00:00 TASK   complete      32bdfc5f-cbdc-43dc-bda8-6f19340f4a26  tekton              kbuild
```

Here the `kbuild` task creates some result nodes with a failure for the `image`
step.  Then a standard `delta` task gets run to look at the results and finds
that the base commit from mainline `v6.19-rc5` hasn't been built yet so it goes
off and does that first:

```
I  2026-01-12T19:56:09.971258+00:00 TASK   add           76cfcba9-7b01-44ad-be5c-82d7c56537ab  tekton              kbuild
I  2026-01-12T19:56:33.296450+00:00 NODE   add           696551f167ff704f772f912c              vixi.kbuild.step    gtucker:v6.19-rc5:checkout
I  2026-01-12T19:56:50.888600+00:00 NODE   add           6965520267ff704f772f9132              vixi.kbuild.step    gtucker:v6.19-rc5:defconfig
I  2026-01-12T20:03:15.973293+00:00 NODE   add           6965538367ff704f772f9136              vixi.kbuild.step    gtucker:v6.19-rc5:image
I  2026-01-12T20:03:35.474186+00:00 NODE   add           6965539767ff704f772f913a              vixi.kbuild.step    gtucker:v6.19-rc5:modules
I  2026-01-12T20:03:42.421443+00:00 NODE   populate      6965539e67ff704f772f913e              batch:1             kbuild
I  2026-01-12T20:03:43.336063+00:00 TASK   complete      76cfcba9-7b01-44ad-be5c-82d7c56537ab  tekton              kbuild
I  2026-01-12T20:03:44.707904+00:00 NODE   populate      696553a067ff704f772f9143              batch:1             image:break
I  2026-01-12T20:03:44.752929+00:00 TASK   complete      f7dcf35d-9123-44ef-bf1a-7124e0255a72  inline-vixi         delta
```

The base commit build completes, and as expected a `vixi.delta` node is then
added to report the broken `image` step which is being treated as a test result
here.  This then gets picked up by the orchestrator again which starts a
`bisect` and we know how this ends.  The difference here is that there's no
separate build log parser task, the result nodes are all added directly in the
Tekton pipeline itself so it's a bit easier to replay.  We'll look at a `kboot`
bisection next time which uses `kbuild` nodes as an input.

So this is the simplified monitor log for the bisection:

```
I  2026-01-12T20:03:44.907272+00:00 TASK   add           b1fbe076-6b42-4d1d-986f-a8a2f48d0683  inline-vixi         bisect
I  2026-01-12T20:03:47.261728+00:00 VIXI   bisect        v6.19-rc5-6-g4fbb47471cc1             check:bad           4fbb47471cc12409d0e9ea77415d87109ba728c8
I  2026-01-12T20:04:58.909224+00:00 VIXI   bisect        v6.19-rc5-6-g4fbb47471cc1             check:good          0f61b1860cc3f52aef9036d7235ed1f017632193
I  2026-01-12T20:06:46.418152+00:00 VIXI   bisect        v6.19-rc5-6-g4fbb47471cc1             iter  1/3           b71e7a5303e5e13f3565944a6b03f96ce34fed74
I  2026-01-12T20:07:51.927107+00:00 VIXI   bisect        v6.19-rc5-6-g4fbb47471cc1             iter  2/3           d0dd74d442a633697391abcedfcbc182784b520d
I  2026-01-12T20:09:39.307420+00:00 VIXI   bisect        v6.19-rc5-6-g4fbb47471cc1             found               b71e7a5303e5e13f3565944a6b03f96ce34fed74
I  2026-01-12T20:09:39.665379+00:00 NODE   add           6965550367ff704f772f918a              vixi.bisect         bisect:b71e7a5303e5e13f3565944a6b03f96ce34fed74
I  2026-01-12T20:09:40.353931+00:00 NODE   add           6965550467ff704f772f918b              artifact-v1         bisect.txt
I  2026-01-12T20:09:40.397977+00:00 TASK   complete      b1fbe076-6b42-4d1d-986f-a8a2f48d0683  inline-vixi         bisect
```

Similarly to KUnit, it creates a `vixi.bisect` node with the breaking commit:

``` json
  "data": {
    "root": "kbuild",
    "path": [
      "kbuild",
      "image"
    ],
    "params": {
      "arch": "x86_64",
      "defconfig": "defconfig",
      "opts": "",
      "cc": "gcc",
      "ccver": "15.2",
      "ccarch": "-x86"
    },
    "revision": {
      "sha1": "b71e7a5303e5e13f3565944a6b03f96ce34fed74",
      "describe": "v6.19-rc5-3-gb71e7a5303e5",
      "subject": "HACK BISECT 3.fail kbuild.image",
      "tree": "gtucker",
      "url": "https://gitlab.com/gtucker/linux.git"
    },
    "history": [...]
```

## Next up

And this wraps up the third demo.  Next time we'll look at `kboot` for a more
complex sequence of tasks to handle using `kbuild` artifacts as its inputs and
how to deal with build failures when bisecting (e.g. skipping revisions).  The
Renelick v1.0 features appear to be pretty stable so it's time to start
preparing the release candidate too.  In the meantime, feel free to comment
here on GitLab or send any queries by email.
