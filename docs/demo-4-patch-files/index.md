VIXI Demo No.4 - Applying patch files
=====================================

This demo showcases how to automatically apply arbitrary patch files on top of
plain checkouts.  It can currently be used with `kbuild` and `kunit` although
any task that relies on a kernel checkout can use it.  Like all task metadata,
this can be replayed in `delta` and `bisect` too.  The primary use case is to
apply a fix and verify it's working as expected.  A common scenario when
reporting issues from test bots on kernel mailing lists is when someone e.g. a
maintainer replies with a fix which needs verification in the exact same
environment where the issue was initially discovered.

Another use case is to isolate a particular issue among multiple ones.  Making
a patch to work around or fix a known issue makes it possible to automatically
bisect a separate issue on the same branch.  There is a fuzzy mode for this in
VIXI to try and apply the patch as best effort at each step and discard errors
raised by `git am`.  Bisections aren't reliable by nature so the outcome will
need to be tested to rule out false positives in any case, so applying such
patches can only improve the chances of success.

> **Note**: The data nodes mentioned in this demo are all publicly available
> via the Renelick Beta Testing instance on
> [beta.renelick.org](https://beta.renelick.org) and can be retrieved with `rk
> node get <id>`.

## Demo branch with 2 build errors

We'll be using a specially crafted branch
[linux-7.0-rc3-kbuild-break](https://gitlab.com/gtucker/linux/-/commits/linux-7.0-rc3-kbuild-break?ref_type=heads)
which introduces two separate plain build errors in `init/main.c` and
`init/init_task.c` as per its commit history:

```
8f966751cd74 BISECT 7.noop
000ec52f3cca BISECT 6.noop
3d172d09c5d8 BISECT 5.kbuild-fail:init/init_task.c
f48068163a6b BISECT 4.noop
17f9c791ed30 BISECT 3.noop
6da2e2feb458 BISECT 2.kbuild-fail:init/main.c
e77133081317 BISECT 1.noop
1f318b96cc84 Linux 7.0-rc3
```

The build errors are bluntly introduced at the preprocessor stage e.g.:

```
#error BROKEN BUILD main.c
```

To trigger this revision manually:

```
rk send vixi event=trigger source=git tree=gtucker revision=linux-7.0-rc3-kbuild-break
```

The orchestrator will schedule `kbuild` and `kunit` tasks as usual.  Both will
fail as the errors also impact the KUnit builds, and they will both get
detected as regressions.  For this demo, we'll just focus on the `kbuild`
results.

## First build error

As expected, the builds fail very quickly and some `delta` nodes get created to
capture the regressions based on `v7.0-rc3` as showcased in previous demos.
Bisection tasks also get scheduled as a result.  However, we know there are two
separate build errors on this branch.  All build errors are considered to be
the same here since there is no fingerprint feature yet (e.g. the actual
compiler error message or files involved).  The tasks only look for the status
code returned by the build command.  This means that all the revisions will
fail to build starting from `6da2e2feb458 "BISECT 2.kbuild-fail:init/main.c"`
regardless of which file gets compiled first and the second error will
effectively be masked.  As such, this first breaking commit is the one that the
bisection should land on.

Here's an extract from the [monitor log](demo-4-1st-bisect.txt) confirming
this:

```
I  2026-05-26T10:24:46.591687+00:00 NODE   add           6a1574eefb5895aeac6052d9              vixi.kbuild.step    gtucker:v7.0-rc3-7-g8f966751cd74:image
I  2026-05-26T10:24:53.330886+00:00 NODE   populate      6a1574f5fb5895aeac6052dd              batch:1             kbuild
I  2026-05-26T10:24:58.211081+00:00 NODE   populate      6a1574fafb5895aeac6052e2              batch:1             image:break
I  2026-05-26T10:25:00.008167+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              check:bad           8f966751cd7411732d4e85afd6f532dc263f4dfe
I  2026-05-26T10:26:06.334835+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              check:good          1f318b96cc84d7c2ab792fcc0bfd42a7ca890681
I  2026-05-26T10:28:02.069124+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              iter  1/3           17f9c791ed30b6477db4582fad44fc89c39751c5
I  2026-05-26T10:29:07.371837+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              iter  2/3           6da2e2feb458ad11f168fb63edc239ed62288204
I  2026-05-26T10:30:13.719685+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              iter  3/3           e7713308131761272dec27e281dfaa46126e0ddc
I  2026-05-26T10:32:03.953357+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              found               6da2e2feb458ad11f168fb63edc239ed62288204
```

And here's the bisection node with the result:

```
rk node get 6a1576a4fb5895aeac60535a -k path -k data
```
``` json
{
  "path": [
    "gtucker:v7.0-rc3-7-g8f966751cd74:checkout",
    "gtucker:v7.0-rc3-7-g8f966751cd74:defconfig",
    "gtucker:v7.0-rc3-7-g8f966751cd74:image",
    "kbuild",
    "image",
    "image:break",
    "bisect:6da2e2feb458ad11f168fb63edc239ed62288204"
  ],
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
      "sha1": "6da2e2feb458ad11f168fb63edc239ed62288204",
      "describe": "v7.0-rc3-2-g6da2e2feb458",
      "subject": "BISECT 2.kbuild-fail:init/main.c",
      "tree": "gtucker",
      "url": "https://gitlab.com/gtucker/linux.git",
      "digest": "5ec93315b678cc06bae2234a2b05864883fc2ec9e4fa5a23a8e9a55c06a8c1d5",
      "patches": []
    },
...
```

### The fix

Now let's assume a patch becomes available with a fix for this first build
error:
[0007-BISECT-FIX-init-main.c.patch](https://storage.gtucker.io/vixi/patches/0007-BISECT-FIX-init-main.c.patch)

This is where the VIXI capability to test the failing revision `6da2e2feb458`
with the patch applied comes into play.  A full test coverage could be
triggered with an event but we'll keep that for later.  Instead, we'll bypass
the orchestrator altogether by scheduling a `kbuild` task directly as a
fine-grained way of verifying the fix:

```
rk run tekton kbuild \
   tree=gtucker \
   url=https://gitlab.com/gtucker/linux.git \
   revision=6da2e2feb458ad11f168fb63edc239ed62288204 \
   patches="https://storage.gtucker.io/vixi/patches/0007-BISECT-FIX-init-main.c.patch"
```

The task gets started and the checkout completes:

```
I  2026-05-26T10:41:18.723548+00:00 TASK   ack           a1d83d3d-ed37-4332-b146-c72d00e31c2d  tekton              kbuild
I  2026-05-26T10:41:45.071839+00:00 NODE   add           6a1578e9fb5895aeac60538f              vixi.kbuild.step    gtucker:v7.0-rc3-2-g6da2e2feb458:checkout
I  2026-05-26T10:41:45.820274+00:00 NODE   add           6a1578e9fb5895aeac605390              artifact-v1         checkout-script
I  2026-05-26T10:41:45.964351+00:00 NODE   add           6a1578e9fb5895aeac605391              artifact-v1         0007-BISECT-FIX-init-main.c.patch
I  2026-05-26T10:41:46.106487+00:00 NODE   add           6a1578eafb5895aeac605392              artifact-v1         patchset.diff
I  2026-05-26T10:41:46.252175+00:00 NODE   add           6a1578eafb5895aeac605393              artifact-v1         checkout-log.txt
```

The URL to the patch file was passed as a task attribute and we can see in
`checkout-log.txt` that it is being applied on top of the specified revision:

```
rk storage get 6a1578eafb5895aeac605393 -
```
```
Tree:     gtucker
URL:      https://gitlab.com/gtucker/linux.git
Revision: 6da2e2feb458ad11f168fb63edc239ed62288204
Path:     /workspace/sandbox/src/kbuild/gtucker
User:     VIXI
Email:    vixi@renelick.org
Remote repositories:
origin	https://gitlab.com/gtucker/linux.git (fetch)
origin	https://gitlab.com/gtucker/linux.git (push)
From https://gitlab.com/gtucker/linux
 * branch                      6da2e2feb458ad11f168fb63edc239ed62288204 -> FETCH_HEAD
HEAD is now at 8f966751cd74 BISECT 7.noop
Previous HEAD position was 8f966751cd74 BISECT 7.noop
HEAD is now at 6da2e2feb458 BISECT 2.kbuild-fail:init/main.c
From https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux
 * branch                      HEAD       -> FETCH_HEAD
commit 6da2e2feb458ad11f168fb63edc239ed62288204
Author: Guillaume Tucker <gtucker@gtucker.io>
Date:   Mon Oct 27 12:21:56 2025 +0100

    BISECT 2.kbuild-fail:init/main.c
2.8G	/workspace/sandbox/src/kbuild/gtucker
Applying: BISECT FIX init/main.c
History:
5dfc3bb37434 BISECT FIX init/main.c
6da2e2feb458 BISECT 2.kbuild-fail:init/main.c
```

This time, the patch file was added as an extra artifact under the `checkout`
step node as well as the plain `patchset.diff` that was used to compute the
digest:

```
rk storage get 6a1578eafb5895aeac605392 -
```
```
diff --git a/init/main.c b/init/main.c
index 54dead402e68..1cb395dd94e4 100644
--- a/init/main.c
+++ b/init/main.c
@@ -15,2 +14,0 @@
-#error BROKEN BUILD main.c
-
```

It's also worth noting that the data nodes now include the patch URL and their
`.digest` field is different from the plain checkout ones:

```
rk node get 6a1578e9fb5895aeac60538f -k data.revision
```
``` json
{
  "data": {
    "revision": {
      "sha1": "6da2e2feb458ad11f168fb63edc239ed62288204",
      "describe": "v7.0-rc3-2-g6da2e2feb458",
      "subject": "BISECT 2.kbuild-fail:init/main.c",
      "tree": "gtucker",
      "url": "https://gitlab.com/gtucker/linux.git",
      "digest": "0cf441af8a5d51480cdf68bc695bf9da6b7e5526ec2d2059798a75390e8ad5e9",
      "patches": [
        {
          "url": "https://storage.gtucker.io/vixi/patches/0007-BISECT-FIX-init-main.c.patch",
          "subject": "BISECT FIX init/main.c"
        }
      ]
    }
  }
}
```

The digest is a SHA256 sum computed with the base commit SHA1 and the plain
diff from all the patches applied on top.  This strips all the metadata and
context so that different patch files that result in the same code changes
should also produce the same digest, as much as possible.  Things like code
identation, syntax tweaks, comments etc. aren't stripped or normalised.  It
should however factor out commit messages, date and time, author, patch series
breakdown, lines of diff context and even the base commit.

### Fixed build

This time, the build [carries on](demo-4-1st-kbuild-fixed.txt) to completion as
anticipated:

```
I  2026-05-26T10:42:01.409939+00:00 NODE   add           6a1578f9fb5895aeac605394              vixi.kbuild.step    gtucker:v7.0-rc3-2-g6da2e2feb458:defconfig
I  2026-05-26T10:42:37.365052+00:00 NODE   add           6a15791dfb5895aeac605398              vixi.kbuild.step    gtucker:v7.0-rc3-2-g6da2e2feb458:image
I  2026-05-26T10:42:53.488089+00:00 NODE   add           6a15792dfb5895aeac60539c              vixi.kbuild.step    gtucker:v7.0-rc3-2-g6da2e2feb458:modules
I  2026-05-26T10:42:59.010493+00:00 NODE   populate      6a157932fb5895aeac6053a0              batch:1             kbuild
I  2026-05-26T10:42:59.062065+00:00 TASK   complete      a1d83d3d-ed37-4332-b146-c72d00e31c2d  tekton              kbuild
```

The `kbuild` result node confirms this:

```
rk node get 6a157932fb5895aeac6053a0 \
   -k data.revision.sha1 \
   -k data.revision.patches \
   -k data.result
```
``` json
{
  "data": {
    "revision": {
      "sha1": "6da2e2feb458ad11f168fb63edc239ed62288204",
      "patches": [
        {
          "url": "https://storage.gtucker.io/vixi/patches/0007-BISECT-FIX-init-main.c.patch",
          "subject": "BISECT FIX init/main.c"
        }
      ]
    },
    "result": "pass"
  }
}
```

This may be a trivial example from a coding point of view but it highlights the
VIXI patching capabilities.  It's also possible to specify a list of patch URLs
for more complicated issues or to test a full series.

One build error down, one to go!

## Second build error

In a real scenario, a second failure on the same branch may have gone unnoticed
thusfar.  That would typically be the case if it were say, a kernel panic as
the build error in the earlier revision would prevent the later one from being
built yet alone booting a kernel.  With this in mind, let's trigger a full test
coverage on the original branch but with the first fix supplied as a patch.
Typically, a maintainer may want to check these results to further verify the
fix before applying it.

```
rk send vixi \
   event=trigger \
   source=git \
   tree=gtucker \
   revision=linux-7.0-rc3-kbuild-break \
   patches="https://storage.gtucker.io/vixi/patches/0007-BISECT-FIX-init-main.c.patch"
```

Surprise surprise: the build fails again.  Let's take a closer look at this
[second monitor log](demo-4-2nd-bisect-fail.txt):

```
vixi-monitor  | I  2026-06-04T12:31:15.146037+00:00 VIXI   trigger       gtucker                               git                 linux-7.0-rc3-kbuild-break
vixi-monitor  | I  2026-06-04T12:31:46.329588+00:00 NODE   add           6a217032fb5895aeac608b4a              vixi.kbuild.step    gtucker:v7.0-rc3-7-g8f966751cd74:checkout
vixi-monitor  | I  2026-06-04T12:31:47.575749+00:00 NODE   add           6a217033fb5895aeac608b4d              artifact-v1         checkout-script
vixi-monitor  | I  2026-06-04T12:31:47.731276+00:00 NODE   add           6a217033fb5895aeac608b4f              artifact-v1         0007-BISECT-FIX-init-main.c.patch
vixi-monitor  | I  2026-06-04T12:31:47.902514+00:00 NODE   add           6a217033fb5895aeac608b51              artifact-v1         patchset.diff
vixi-monitor  | I  2026-06-04T12:32:16.661115+00:00 NODE   add           6a217050fb5895aeac608b5f              vixi.kbuild.step    gtucker:v7.0-rc3-7-g8f966751cd74:image
vixi-monitor  | I  2026-06-04T12:32:17.346023+00:00 NODE   add           6a217051fb5895aeac608b60              artifact-v1         image-log.txt
vixi-monitor  | I  2026-06-04T12:32:22.460138+00:00 TASK   complete      12e305a9-d436-4213-8aa3-b51a9f0b381a  tekton              kbuild
```

For completeness, this is the build log `image-log.txt` showing the second
compiler error so we know we're not hitting the `init/main.c` one:

```
rk storage get 6a217051fb5895aeac608b60 -
```
```
make[1]: Entering directory '/workspace/sandbox/src/kbuild/gtucker/build/x86_64/gcc-15.2'
  GEN     Makefile
  HOSTCC  scripts/basic/fixdep
  UPD     include/generated/compile.h
  DESCEND objtool
  UPD     include/config/kernel.release
  UPD     include/generated/utsrelease.h
  CALL    /workspace/sandbox/src/kbuild/gtucker/scripts/checksyscalls.sh
  INSTALL libsubcmd_headers
  CC      init/main.o
  CC      kernel/sys.o
  CC      init/init_task.o
  CC      init/version.o
/workspace/sandbox/src/kbuild/gtucker/init/init_task.c:20:2: error: #error BROKEN BUILD init_task.c
   20 | #error BROKEN BUILD init_task.c
      |  ^~~~~
make[4]: *** [/workspace/sandbox/src/kbuild/gtucker/scripts/Makefile.build:289: init/init_task.o] Error 1
make[4]: *** Waiting for unfinished jobs....
make[3]: *** [/workspace/sandbox/src/kbuild/gtucker/scripts/Makefile.build:546: init] Error 2
make[3]: *** Waiting for unfinished jobs....
  CC      kernel/module/main.o
  AR      kernel/module/built-in.a
  AR      kernel/built-in.a
make[2]: *** [/workspace/sandbox/src/kbuild/gtucker/Makefile:2101: .] Error 2
make[1]: *** [/workspace/sandbox/src/kbuild/gtucker/Makefile:248: __sub-make] Error 2
make[1]: Leaving directory '/workspace/sandbox/src/kbuild/gtucker/build/x86_64/gcc-15.2'
make: *** [Makefile:248: __sub-make] Error 2
```

### Bisection issue

As usual, this build failure gets caught by the `delta` task which stores the
regression in a node.  This in turn causes the orchestrator to schedule a new
bisection which also carries the patch as per the replay feature.  But then the
check for the "good" revision fails, which is the mainline base tag `v7.0-rc3`:

```
vixi-monitor  | I  2026-06-04T12:32:22.574160+00:00 TASK   ack           cbf02808-7a30-4cc8-badc-3b37a8eb5ad6  inline-vixi         delta
vixi-monitor  | I  2026-06-04T12:32:26.476133+00:00 NODE   populate      6a21705afb5895aeac608b67              batch:1             image:break
vixi-monitor  | I  2026-06-04T12:32:26.645693+00:00 TASK   ack           edff165a-b08a-489b-b658-099be11be2c5  inline-vixi         bisect
vixi-monitor  | I  2026-06-04T12:32:28.346446+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              check:bad           8f966751cd7411732d4e85afd6f532dc263f4dfe
vixi-monitor  | I  2026-06-04T12:33:30.808809+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              check:good          1f318b96cc84d7c2ab792fcc0bfd42a7ca890681
vixi-monitor  | I  2026-06-04T12:34:01.939524+00:00 NODE   add           6a2170b9fb5895aeac608b7f              vixi.kbuild.step    gtucker:v7.0-rc3:checkout
vixi-monitor  | I  2026-06-04T12:34:02.645231+00:00 NODE   add           6a2170bafb5895aeac608b80              artifact-v1         checkout-script
vixi-monitor  | I  2026-06-04T12:34:02.790494+00:00 NODE   add           6a2170bafb5895aeac608b81              artifact-v1         0007-BISECT-FIX-init-main.c.patch
vixi-monitor  | I  2026-06-04T12:34:02.891211+00:00 NODE   add           6a2170bafb5895aeac608b82              artifact-v1         checkout-log.txt
vixi-monitor  | I  2026-06-04T12:34:09.116021+00:00 NODE   populate      6a2170c1fb5895aeac608b83              batch:1             kbuild
vixi-monitor  | I  2026-06-04T12:34:09.163148+00:00 TASK   complete      4094f776-e149-40cf-8985-d179c2fc8be5  tekton              kbuild
vixi-monitor  | I  2026-06-04T12:34:09.407695+00:00 TASK   complete      edff165a-b08a-489b-b658-099be11be2c5  inline-vixi         bisect
```

What happened?  The `kbuild` task stopped at the checkout step so let's take a
look at `checkout-log.txt`:

```
rk storage get 6a2170bafb5895aeac608b82 -
```
```
Tree:     gtucker
URL:      https://gitlab.com/gtucker/linux.git
Revision: 1f318b96cc84d7c2ab792fcc0bfd42a7ca890681
Path:     /workspace/sandbox/src/kbuild/gtucker
User:     VIXI
Email:    vixi@renelick.org
Remote repositories:
origin	https://gitlab.com/gtucker/linux.git (fetch)
origin	https://gitlab.com/gtucker/linux.git (push)
From https://gitlab.com/gtucker/linux
 * branch                      1f318b96cc84d7c2ab792fcc0bfd42a7ca890681 -> FETCH_HEAD
HEAD is now at 1f318b96cc84 Linux 7.0-rc3
HEAD is now at 1f318b96cc84 Linux 7.0-rc3
From https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux
 * branch                      HEAD       -> FETCH_HEAD
 * [new tag]                   v7.1-rc6   -> v7.1-rc6
commit 1f318b96cc84d7c2ab792fcc0bfd42a7ca890681
Author: Linus Torvalds <torvalds@linux-foundation.org>
Date:   Sun Mar 8 16:56:54 2026 -0700

    Linux 7.0-rc3
2.8G	/workspace/sandbox/src/kbuild/gtucker
error: patch failed: init/main.c:12
error: init/main.c: patch does not apply
hint: Use 'git am --show-current-patch=diff' to see the failed patch
Applying: BISECT FIX init/main.c
Patch failed at 0001 BISECT FIX init/main.c
When you have resolved this problem, run "git am --continue".
If you prefer to skip this patch, run "git am --skip" instead.
To restore the original branch and stop patching, run "git am --abort".
---
 init/main.c | 2 --
 1 file changed, 2 deletions(-)

diff --git a/init/main.c b/init/main.c
index 54dead402e68..1cb395dd94e4 100644
--- a/init/main.c
+++ b/init/main.c
@@ -12,8 +12,6 @@

 #define DEBUG		/* Enable initcall_debug */

-#error BROKEN BUILD main.c
-
 #include <linux/types.h>
 #include <linux/export.h>
 #include <linux/extable.h>
--
2.47.3

Traceback (most recent call last):
  File "/workspace/artifacts/checkout/checkout-script", line 3, in <module>
    vixi.kbuild.env_checkout(
  File "/workspace/common/venv/lib/python3.10/site-packages/vixi/kbuild.py", line 272, in env_checkout
    apply_patches(patches, rev['sha1'], artifacts, cwd, 'rnr' in flags)
  File "/workspace/common/venv/lib/python3.10/site-packages/vixi/kbuild.py", line 222, in apply_patches
    raise RenelickError(f"Failed to apply patch: {patch_name}")
renelick.client.exceptions.RenelickError: Failed to apply patch: 0007-BISECT-FIX-init-main.c.patch
```

Obviously, this base revision predates the first build error so the patch to
fix it doesn't apply there yet.  Luckily, VIXI has a solution for this with
permissive or "fuzzy" patching.

### 🎸 Fuzzy patching

Unlike the initial use case which was applying a fix to verify it, here we just
want to supply a patch to enable the bisection to run without the first build
error in order to uncover the second one.  As such, we don't necessarily need
the patch to cleanly apply if at all in each bisection step.  Instead, we just
want it to be applied as best effort - pretty much what one may reasonably
expect from a bisection anyway.  So in principle, the patch will apply where
applicable and if things go well things will work.  This is what real-world
kernel bug hunting looks like using semi-automated bisections.

An experimental feature to achieve this can be enabled in VIXI tasks via the
`flags=rnr` attribute.  However, this isn't a standard thing to do and it's not
currently handled with trigger events.  Instead, we'll schedule a `kbuild` task
with this flag and also set the `orch=vixi` attribute to let the orchestrator
pick up the `kbuild` result later and schedule the `delta` and `bisect` tasks:

```
rk run tekton kbuild \
   tree=gtucker \
   url=https://gitlab.com/gtucker/linux.git \
   revision=linux-7.0-rc3-kbuild-break \
   patches="https://storage.gtucker.io/vixi/patches/0007-BISECT-FIX-init-main.c.patch"\
   orch=vixi \
   flags=rnr
```

For lack of a better name, `rnr` stands for Rock & Roll which accurately
describes the feature's attitude.  If applying a patch with `git am` fails,
this will try again using `patch --no-backup-if-mismatch -r- -p1` directly to
pick up any pieces that might apply, discard the ones that don't, commit what's
left and carry on.

Let's take a closer look at the [monitor log again](demo-4-2nd-bisect-rnr.txt):

```
vixi-monitor  | I  2026-06-04T14:07:44.946298+00:00 TASK   ack           a48ec23c-5445-46f5-8b64-d352768166b7  tekton              kbuild
vixi-monitor  | I  2026-06-04T14:08:09.945324+00:00 NODE   add           6a2186c9fb5895aeac608c21              vixi.kbuild.step    gtucker:v7.0-rc3-7-g8f966751cd74:checkout
vixi-monitor  | I  2026-06-04T14:08:26.375152+00:00 NODE   add           6a2186dafb5895aeac608c26              vixi.kbuild.step    gtucker:v7.0-rc3-7-g8f966751cd74:defconfig
vixi-monitor  | I  2026-06-04T14:08:39.964857+00:00 NODE   add           6a2186e7fb5895aeac608c2a              vixi.kbuild.step    gtucker:v7.0-rc3-7-g8f966751cd74:image
vixi-monitor  | I  2026-06-04T14:08:46.604430+00:00 TASK   complete      a48ec23c-5445-46f5-8b64-d352768166b7  tekton              kbuild
vixi-monitor  | I  2026-06-04T14:08:46.740507+00:00 TASK   ack           705b7c12-53a3-47d8-a72e-34bdaf64e477  inline-vixi         delta
vixi-monitor  | I  2026-06-04T14:08:48.575878+00:00 NODE   populate      6a2186f0fb5895aeac608c32              batch:1             image:break
vixi-monitor  | I  2026-06-04T14:08:48.748775+00:00 TASK   ack           96f9d936-df53-4c63-8fa5-3c25852a1045  inline-vixi         bisect
vixi-monitor  | I  2026-06-04T14:08:49.767229+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              check:bad           8f966751cd7411732d4e85afd6f532dc263f4dfe
vixi-monitor  | I  2026-06-04T14:09:56.076368+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              check:good          1f318b96cc84d7c2ab792fcc0bfd42a7ca890681
vixi-monitor  | I  2026-06-04T14:09:56.415237+00:00 TASK   ack           fbc0a705-4a61-44d7-90f9-f2cf975f3096  tekton              kbuild
vixi-monitor  | I  2026-06-04T14:10:24.140117+00:00 NODE   add           6a218750fb5895aeac608c44              vixi.kbuild.step    gtucker:v7.0-rc3:checkout
vixi-monitor  | I  2026-06-04T14:10:24.811145+00:00 NODE   add           6a218750fb5895aeac608c45              artifact-v1         checkout-script
vixi-monitor  | I  2026-06-04T14:10:24.912485+00:00 NODE   add           6a218750fb5895aeac608c46              artifact-v1         checkout-log.txt
vixi-monitor  | I  2026-06-04T14:10:39.720459+00:00 NODE   add           6a21875ffb5895aeac608c47              vixi.kbuild.step    gtucker:v7.0-rc3:defconfig
vixi-monitor  | I  2026-06-04T14:11:16.921015+00:00 NODE   add           6a218784fb5895aeac608c4b              vixi.kbuild.step    gtucker:v7.0-rc3:image
vixi-monitor  | I  2026-06-04T14:11:33.414385+00:00 NODE   add           6a218795fb5895aeac608c4f              vixi.kbuild.step    gtucker:v7.0-rc3:modules
vixi-monitor  | I  2026-06-04T14:11:40.421219+00:00 NODE   populate      6a21879cfb5895aeac608c53              batch:1             kbuild
vixi-monitor  | I  2026-06-04T14:11:40.464081+00:00 TASK   complete      fbc0a705-4a61-44d7-90f9-f2cf975f3096  tekton              kbuild
```

This time, the "good" revision checkout worked as it just ignored the patch
errors, as per the new `checkout-log.txt`:

```
rk storage get 6a218750fb5895aeac608c46 -
```
```
Tree:     gtucker
URL:      https://gitlab.com/gtucker/linux.git
Revision: 1f318b96cc84d7c2ab792fcc0bfd42a7ca890681
Path:     /workspace/sandbox/src/kbuild/gtucker
User:     VIXI
Email:    vixi@renelick.org
Remote repositories:
origin	https://gitlab.com/gtucker/linux.git (fetch)
origin	https://gitlab.com/gtucker/linux.git (push)
From https://gitlab.com/gtucker/linux
 * branch                      1f318b96cc84d7c2ab792fcc0bfd42a7ca890681 -> FETCH_HEAD
HEAD is now at b4c9e067135b BISECT FIX init/main.c
Warning: you are leaving 1 commit behind, not connected to
any of your branches:

  b4c9e067135b BISECT FIX init/main.c

If you want to keep it by creating a new branch, this may be a good time
to do so with:

 git branch <new-branch-name> b4c9e067135b

HEAD is now at 1f318b96cc84 Linux 7.0-rc3
From https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux
 * branch                      HEAD       -> FETCH_HEAD
commit 1f318b96cc84d7c2ab792fcc0bfd42a7ca890681
Author: Linus Torvalds <torvalds@linux-foundation.org>
Date:   Sun Mar 8 16:56:54 2026 -0700

    Linux 7.0-rc3
2.8G	/workspace/sandbox/src/kbuild/gtucker
🎸 RnR enabled
error: patch failed: init/main.c:12
error: init/main.c: patch does not apply
hint: Use 'git am --show-current-patch=diff' to see the failed patch
Applying: BISECT FIX init/main.c
Patch failed at 0001 BISECT FIX init/main.c
When you have resolved this problem, run "git am --continue".
If you prefer to skip this patch, run "git am --skip" instead.
To restore the original branch and stop patching, run "git am --abort".
patching file init/main.c
Reversed (or previously applied) patch detected!  Assume -R? [n]
Apply anyway? [n]
Skipping patch.
1 out of 1 hunk ignored
History:
1f318b96cc84 Linux 7.0-rc3
```

The bisection then proceeds and completes:

```
vixi-monitor  | I  2026-06-04T14:11:40.836912+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              iter  1/3           17f9c791ed30b6477db4582fad44fc89c39751c5
vixi-monitor  | I  2026-06-04T14:13:26.215817+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              iter  2/3           3d172d09c5d8f17fe87c3af245570617c9f68b1b
vixi-monitor  | I  2026-06-04T14:14:34.280214+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              iter  3/3           f48068163a6b5d281e9748c2b52e8fd015dcb08b
vixi-monitor  | I  2026-06-04T14:17:17.397998+00:00 VIXI   bisect        v7.0-rc3-7-g8f966751cd74              found               3d172d09c5d8f17fe87c3af245570617c9f68b1b
vixi-monitor  | I  2026-06-04T14:17:17.633932+00:00 NODE   add           6a2188edfb5895aeac608c95              vixi.bisect         bisect:3d172d09c5d8f17fe87c3af245570617c9f68b1b
vixi-monitor  | I  2026-06-04T14:17:18.278060+00:00 NODE   add           6a2188eefb5895aeac608c96              artifact-v1         bisect.txt
vixi-monitor  | I  2026-06-04T14:17:18.326604+00:00 TASK   complete      96f9d936-df53-4c63-8fa5-3c25852a1045  inline-vixi         bisect
```

Finally, the second bisection result node:

```
rk node get 6a2188edfb5895aeac608c95 -k path -k data
```
``` json
{
  "path": [
    "gtucker:v7.0-rc3-7-g8f966751cd74:checkout",
    "gtucker:v7.0-rc3-7-g8f966751cd74:defconfig",
    "gtucker:v7.0-rc3-7-g8f966751cd74:image",
    "kbuild",
    "image",
    "image:break",
    "bisect:3d172d09c5d8f17fe87c3af245570617c9f68b1b"
  ],
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
      "sha1": "3d172d09c5d8f17fe87c3af245570617c9f68b1b",
      "describe": "v7.0-rc3-5-g3d172d09c5d8",
      "subject": "BISECT 5.kbuild-fail:init/init_task.c",
      "tree": "gtucker",
      "url": "https://gitlab.com/gtucker/linux.git",
      "digest": "226bb66445148fb1649a9f2f3292f92c48a964021cb13228ee2bf50f352ed7be",
      "patches": [
        {
          "url": "https://storage.gtucker.io/vixi/patches/0007-BISECT-FIX-init-main.c.patch",
          "subject": "BISECT FIX init/main.c"
        }
      ]
    },
...
```

## Wrap up

I realise this was a rather long demo with quite a few concepts bundled
together and lots of data.  Still this is how things usually go with real bugs
as each bisection is its own little story with a hit-and-miss dimension.  There
are many further topics related to applying patch files from mailing list,
Patchwork etc. and as such it felt better to cover all the initial features
here.

Once again, don't forget that the data nodes and artifacts are all available
via the [Beta Testing](https://beta.renelick.org) Renelick instance which is
publicly available.

More demos and [blog posts](https://gtucker.io/tags/renelick/) coming soon!
