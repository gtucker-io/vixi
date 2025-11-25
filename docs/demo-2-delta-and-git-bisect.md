VIXI Demo No.2 – Delta and Git bisect
=====================================

Building upon the [first demo](demo-1-git-to-kunit.md), this time we'll start
looking at some post-processing tasks to detect new test failures and
automatically find the breaking commit using `git bisect`.  To simplify the
logs, we'll just have the `kbuild` and `kunit` pipelines running and no
`kboot`.  The automated bisection logic currently only works with KUnit, a
follow-up demo will showcase how this applies to any test results including
builds and boots.  It's using an especially prepared branch
[linux-6.18-rc4-kunit-fail](https://gitlab.com/gtucker/linux/-/commits/linux-6.18-rc4-kunit-fail?ref_type=heads)
based on the arbitrary `v6.18-rc4` mainline tag with a short history including
a commit that breaks one KUnit test.

We'll leave the Renelick API and VIXI orchestrator logs aside to focus on the
monitor since it provides all the high-level information we need.  It's
[implemented](https://gitlab.com/gtucker/vixi/-/blob/main/vixi/monitor.py?ref_type=heads)
in a derived class to format `vixi` events on top of the generic Renelick ones
`node` and `task`.  The log also now shows timestamps from the event objects
themselves rather than the Python logging framework to paint a more accurate
picture and give some insights into the kind of latency involved.  As in the
previous demo, the API is hosted on a remove server `renelick.gtucker.io`.  One
key difference is that the Tekton pipelines are now handled by a static VM
worker near the API while the monitor and orchestrator are still on the
development laptop.  So the updated topology looks like this:

* `renelick.gtucker.io` server: Renelick API + HTTP file storage
* laptop: minikube with monitor, orchestrator and inline schedulers
* worker VM: minikube with Tekton and inline schedulers

Each `inline` scheduler runs tasks directly in its current Python process,
whereas a `tekton` scheduler runs [Tetkon](https://tekton.dev/) tasks or
pipelines in Kubernetes.  All schedulers are plain Renelick clients with
outgoing connections only so no special setup is required to deploy them.  The
client TOML settings and credentials with a persistent API key are provided via
standard Kubernetes secrets.  The only critical thing to keep in mind is to
deploy only one orchestrator to avoid having the same tasks scheduled more than
once.

> **Note**: The full monitor service log can be found in
> [`demo-2-monitor-log.txt`](demo-2-monitor-log.txt).

## Initial trigger

With everything set up and mirrors already populated, the only manual input to
run and start the whole demo is to send a trigger event:

```
renelick event send vixi event=trigger source=git tree=gtucker revision=linux-6.18-rc4-kunit-fail
```

The orchestrator will then receive it and schedule the `kbuild` and `kunit`
tasks as per the YAML configuration.  These will in turn get accepted by the
`tekton` scheduler which will take care of running the actual Tekton pipelines:

```
I  2025-11-20T21:54:06.194801+00:00 VIXI   trigger       gtucker                               git                 linux-6.18-rc4-kunit-fail
I  2025-11-20T21:54:06.369038+00:00 TASK   add           9cb3ad9f-1ecc-4a5d-88c7-b8994cd2817a  tekton              kbuild
I  2025-11-20T21:54:06.372444+00:00 TASK   accept        9cb3ad9f-1ecc-4a5d-88c7-b8994cd2817a  tekton              kbuild
I  2025-11-20T21:54:06.462179+00:00 TASK   add           bc3ee1c1-5765-4bd9-8ea2-b7f89034a623  tekton              kunit
I  2025-11-20T21:54:06.462678+00:00 TASK   accept        bc3ee1c1-5765-4bd9-8ea2-b7f89034a623  tekton              kunit
```

Before going further, let's take a look at the `linux-6.18-rc4-kunit-fail`
branch history:

```
9d4c9276e5d2 HACK BISECT 4.noop
0cd8120e9a75 HACK BISECT 3.noop
9d793b6ea4b0 HACK fail KUnit overflow.shift_sane_test
3d4134666f41 HACK BISECT 1.noop
6146a0f1dfae Linux 6.18-rc4
```

It contains a simple change to cause one KUnit test to fail:

``` diff
diff --git a/lib/tests/overflow_kunit.c b/lib/tests/overflow_kunit.c
index 19cb03b25dc5..839b93e69fb3 100644
--- a/lib/tests/overflow_kunit.c
+++ b/lib/tests/overflow_kunit.c
@@ -422,7 +422,7 @@ static void shift_sane_test(struct kunit *test)
        /* Sane shifts. */
        TEST_ONE_SHIFT(1, 0, u8, 1 << 0, false);
        TEST_ONE_SHIFT(1, 4, u8, 1 << 4, false);
-       TEST_ONE_SHIFT(1, 7, u8, 1 << 7, false);
+       TEST_ONE_SHIFT(1, 7, u8, 1 << 6, false);
        TEST_ONE_SHIFT(0xF, 4, u8, 0xF << 4, false);
        TEST_ONE_SHIFT(1, 0, u16, 1 << 0, false);
        TEST_ONE_SHIFT(1, 10, u16, 1 << 10, false);
```

The other commits just add one line in a plain text file with no effect on the
code itself.  The trigger will cause the head of the branch to be tested i.e.
commit `9d4c9276e5d2` which has the broken test.

As a side note, we can also already get an idea of the latency by looking at
the timestamps: it took about 150ms for the orchestrator to schedule the first
task and another 100ms for the second one, with a ping time to the API server
of 25ms.  The `tekton` scheduler accepted them almost instantly, with a ping
time around 3ms.  This shows that the stack works already quite well as-is with
FastAPI and Redis and no optimisation.

## Racing pipelines

The next events show when the Git checkouts complete which is about 30s after
the initial trigger for both pipelines:

```
I  2025-11-20T21:54:39.017773+00:00 NODE   add           691f8e1fc3bca0e8094ca999              vixi.kbuild.step    gtucker:v6.18-rc4-4-g9d4c9276e5d2:checkout
I  2025-11-20T21:54:39.670369+00:00 NODE   add           691f8e1fc3bca0e8094ca99a              artifact-v1         checkout.sh
I  2025-11-20T21:54:39.838496+00:00 NODE   add           691f8e1fc3bca0e8094ca99b              artifact-v1         checkout.txt
I  2025-11-20T21:54:40.139950+00:00 NODE   add           691f8e20c3bca0e8094ca99c              vixi.kunit.step     gtucker:v6.18-rc4-4-g9d4c9276e5d2:checkout
I  2025-11-20T21:54:40.742785+00:00 NODE   add           691f8e20c3bca0e8094ca99d              artifact-v1         checkout.sh
I  2025-11-20T21:54:40.885139+00:00 NODE   add           691f8e20c3bca0e8094ca99e              artifact-v1         checkout.txt
```

It also includes the artifacts with the checkout scripts and logs.  They then
keep running in parallel on the same machine, with `kbuild` completing first
while `kunit` is running tests and crosses the finish line about 40s later:

```
I  2025-11-20T21:55:49.869122+00:00 TASK   complete      9cb3ad9f-1ecc-4a5d-88c7-b8994cd2817a  tekton              kbuild
I  2025-11-20T21:56:24.718606+00:00 NODE   add           691f8e88c3bca0e8094ca9b1              vixi.kunit.step     gtucker:v6.18-rc4-4-g9d4c9276e5d2:exec
I  2025-11-20T21:56:25.339027+00:00 NODE   add           691f8e89c3bca0e8094ca9b2              artifact-v1         exec.txt
I  2025-11-20T21:56:25.482839+00:00 NODE   add           691f8e89c3bca0e8094ca9b3              artifact-v1         kunit.json
I  2025-11-20T21:56:25.626302+00:00 NODE   add           691f8e89c3bca0e8094ca9b4              artifact-v1         exec.sh
I  2025-11-20T21:56:31.258509+00:00 TASK   complete      bc3ee1c1-5765-4bd9-8ea2-b7f89034a623  tekton              kunit
```

## Post-processing KUnit results

This is where we really go beyond what was covered in the first demo.  After
completing, the KUnit JSON results are parsed and data nodes are populated like
before.  Then a `delta` task is run to compare the results with a previous
revision on the same branch.  In this case, it will look for the base commit
with mainline so `v6.18-rc4` which happens to have already been tested here to
keep things simpler.  Failing that, the `delta` task itself would have
triggered an extra `kunit` run for the base revision before doing the
comparison.  This is to always work out if the current branch has any new
failures not already in mainline, which is a very useful feature for kernel
subsystem maintainers who gather many changes ahead of a merge window.

As far as the monitor log goes, we can see a sequence of events with first the
KUnit results in a tree of nodes, then a delta node with the test case that
failed and a bisection task scheduled as a result:

```
I  2025-11-20T21:56:31.743158+00:00 TASK   add           d17bfdc8-1402-4dc2-8c86-6f8e488bafb0  inline-vixi         kunit-parser
I  2025-11-20T21:56:31.748607+00:00 TASK   accept        d17bfdc8-1402-4dc2-8c86-6f8e488bafb0  inline-vixi         kunit-parser
I  2025-11-20T21:56:34.288346+00:00 NODE   populate      691f8e90c3bca0e8094ca9b5              batch:1             kunit
I  2025-11-20T21:56:34.520806+00:00 TASK   complete      d17bfdc8-1402-4dc2-8c86-6f8e488bafb0  inline-vixi         kunit-parser
I  2025-11-20T21:56:34.633456+00:00 TASK   add           16b1638b-53bf-479c-ad8e-ab5b49d82ed5  inline-vixi         delta
I  2025-11-20T21:56:34.637179+00:00 TASK   accept        16b1638b-53bf-479c-ad8e-ab5b49d82ed5  inline-vixi         delta
I  2025-11-20T21:56:37.305930+00:00 NODE   populate      691f8e95c3bca0e8094cacf9              batch:1             shift_sane_test:break
I  2025-11-20T21:56:37.349615+00:00 TASK   complete      16b1638b-53bf-479c-ad8e-ab5b49d82ed5  inline-vixi         delta
I  2025-11-20T21:56:37.524719+00:00 TASK   add           4c35ed94-f399-4e49-93ee-226744d8b7c3  inline-vixi         bisect
I  2025-11-20T21:56:37.528562+00:00 TASK   accept        4c35ed94-f399-4e49-93ee-226744d8b7c3  inline-vixi         bisect
```

Here are the relevant orchestrator
[config](https://gitlab.com/gtucker/vixi/-/blob/main/vixi/oconfig.yaml?ref_type=heads)
entries for `delta` and `bisect`:

``` yaml
  # compute delta between test results
- task: delta
  channel: node
  match: {kind: vixi.group, op: populate}
  scheduler: inline-vixi

  # run a Git bisection based on found delta
- task: bisect
  channel: node
  match: {kind: vixi.delta, op: populate}
  scheduler: inline-vixi
```

In human words, this means "run a delta task when a test group has been
populated" and then "run a bisect task when delta nodes have been populated".
Here we have one `delta` node for the `shift_same_test` case that failed.

> **Note**: To `populate` some nodes basically means the same as to `add` one
> node except `populate` events only refer to the root nodes when trees of
> nodes get added togher in a batch via a single API call.  The aim is to avoid
> flooding clients with events.  For example, a full KUnit job amounts to about
> 850 nodes but only one event is sent for the whole tree.

The [full delta node](demo-2-delta-node.json) itself is also attached to the
demo.  It basically contains the path to the test case that failed and details
about the old and new revisions with parameters such as the CPU architecture,
compiler version, defconfig etc.

## Bisecting

Finally, let's take a look at the `bisect` task that got scheduled right after
the `delta` node landed.  Custom VIXI events are sent for each step of the
bisection which is running in the inline scheduler while the KUnit pipelines
are run in Tekton.  These are only here to provide feedback to users and
facilitate development.  It's entirely possible to add orchestrator entries and
do useful things with them, for example to add more metadata nodes for a
specific UI, generate some stats or influence the course of concurrent
bisections.  As such, the `bisect` task acts a bit like a short-term,
specialised orchestrator.

The logic will first check that the `bad` and `good` revisions from the delta
node respectively fail and pass the test.  It will then start the bisection per
se, with each iteration containing a full KUnit pipeline (checkout, build, run)
in Tekton and results parser inline.  We'll omit them here for brevity,
interested readers will find it all in the [full monitor log
file](demo-2-monitor-log.txt).

```
I  2025-11-20T21:56:41.987494+00:00 VIXI   bisect        v6.18-rc4-4-g9d4c9276e5d2             check:bad           9d4c9276e5d2c45101c5f74f568392bdd4003c6e
I  2025-11-20T21:58:04.894027+00:00 VIXI   bisect        v6.18-rc4-4-g9d4c9276e5d2             check:good          6146a0f1dfae5d37442a9ddcba012add260bceb0
I  2025-11-20T21:59:20.831537+00:00 VIXI   bisect        v6.18-rc4-4-g9d4c9276e5d2             iter  1/2           9d793b6ea4b057f29c5275e300035ad24ecb619b
I  2025-11-20T22:00:40.721727+00:00 VIXI   bisect        v6.18-rc4-4-g9d4c9276e5d2             iter  2/2           3d4134666f41dba5257bd18a0bed99a6b449fafc
I  2025-11-20T22:02:02.070720+00:00 VIXI   bisect        v6.18-rc4-4-g9d4c9276e5d2             found               9d793b6ea4b057f29c5275e300035ad24ecb619b
```

As there is only one Tekton scheduler, all the successive KUnit pipelines land
in the same runtime and reuse the same kernel checkout to do incremental builds
which is why iterations are rather quick.  The `bisect` task itself which is
run `inline` doesn't require an actual source checkout, only the Git history.

The outcome of each pipeline is fed into the classic `git bisect` command to
figure out what to do next.  As it estimates the number of iterations, events
are sent with some kind of progress status until the breaking commit is found.
We can see that the SHA1 checksum matches the `9d793b6ea4b0 HACK fail KUnit
overflow.shift_sane_test` commit as expected.

It then wraps up by creating a `bisect` node with all the relevant data,
uploading the standard bisection log and marking the task as complete:

```
I  2025-11-20T22:02:02.645671+00:00 NODE   add           691f8fdac3bca0e8094cad8a              vixi.bisect         bisect:9d793b6ea4b057f29c5275e300035ad24ecb619b
I  2025-11-20T22:02:03.249746+00:00 NODE   add           691f8fdbc3bca0e8094cad8b              artifact-v1         bisect.txt
I  2025-11-20T22:02:03.290073+00:00 TASK   complete      4c35ed94-f399-4e49-93ee-226744d8b7c3  inline-vixi         bisect
```

## Shortcomings

While this "lab experiment" worked and showed that the Renelick API with the
client-side facilities can enable this kind of advanced use case, there are
still quite a few things to address to get a fully-featured bisection tool.
Some are minor things that just require implementation gaps to be filled:

* deal with other kinds of `delta` than just a breaking test e.g. a fix or
  tests that have always failed
* deal with bisections that don't converge on a particular commit
* verify the bisection result with a revert in-place and a revert on top of the
  head of the branch
* look for results on the current branch between the base commit and the head
  to avoid repeating the same bisections

While all these merely require some extra bits of logic, they're fairly
straightforward to address.  A more conceptual issue is about running the tasks
involved to produce a given set of results, such as when `delta` needs to test
a base commit and during each iteration in a bisection.  Right now, this is
hard coded as a KUnit pipeline run followed by a KUnit parser task.  A simple
solution would be to require every result to be the outcome of a single task
which can be atomically reproduced.  For KUnit, it would mean including the
JSON parsing inside the Tekton pipeline or adding a "managing" task on top to
connect the Tekton pipeline with the inline parsing.  This is however far from
ideal as it imposes many additional constraints on the orchestration.  A
similar issue is going to arise with `kbuild` and `kboot` tasks chained
together, and these two really can't be bundled into a single one.

While there are many conceivable alternatives, only practical experiments will
tell what actually works.  My best bet right now is to have some very
high-level built-in assumptions to enable looking for an initial checkout and
the final results in the tree of nodes.  From there, it should be possible to
work out the sequence of tasks that were run and how they propagated their
results to each other in order to reproduce it with a different revision.  The
highest priority here is to highlight any potential issue on the Renelick API
side and see if anything needs to be changed in how tasks are being handled
before putting a stamp on the v1.0 stable release candidate.  I believe it can
all be done within the embedded payloads of task and node objects which are all
managed by the client-side application logic but I'm always happy to be proven
wrong!
