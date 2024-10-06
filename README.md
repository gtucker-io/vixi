VIXI · Virtual Kernel CI
========================

_Work in Progress_

This is a [Renelick](https://gitlab.com/gtucker.io/renelick) application to
continuously test the upstream kernel in virtual environments.

## Workflow

This is currently limited to a single x86 build which allows for some
simplifications and a streamlined pipeline.  Extended coverage may be added
incrementally so as to keep it fast.

* ☐ revision trigger event
  * ☑ manual
  * ☐ either new patch from email
  * ☐ discovered in git tree
  * ☐ via git hook
* kbuild task
  * ☑ checkout the git revision
  * ☑ build the kernel using a korg container
  * ☐ upload artifacts to GCS
* ☐ kboot task
  * ☐ boot a kernel image using KVM
* ☐ ktest task
  * run some tests in the VM
* ☐ kunit task
  * ☐ checkout the git revision
  * ☐ run KUnit in a korg container
* ☐ static checks
  * ☐ checkpatch

☐ _not done_
☑ _done_

## Implementation

Ideally, after a kbuild task, the kboot task can pick the kernel binary
directly within the same Tekton pipeline and boot it with KubeVirt.

Each step has a task to send data to the Renelick API with the results and logs
etc.  For example, at the end of the checkout, a task will be sending the
results while another one will be starting the build in parallel (both "ruh
after checkout").

Node hierarchy:

* run
    kernel revision
    pipeline type
  * checkpatch (if from mailing list)
  * kunit
  * kbuild (multiple: gcc, clang, various configs, x86_64, arm)
    * kboot (at least one for each build)
      * ktest (multiple)

### Incremental builds

The assumption is that incremental builds are reliable as per the upstream
kernel standards.  As such, build directories are kept in a persistent volume
to be reused.  They should be unique at least for each combination of compiler
and architecture.  Each tree has a persistent separate checkout directory which
also makes the builds more likely to be incremental.

### Git mirror

For each tree, a mirror repository is kept in a read-only PersistentVolumeClaim
which is shared by the workers.  A Tekton task can be run at any time to update
a given mirror, typically once a week.

> **Note**: The per-tree build directories could be deleted at the same rate as
> the mirror syncs, so probably once a week.
