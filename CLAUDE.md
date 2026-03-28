# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VIXI (Virtual Kernel CI) is a [Renelick](https://gitlab.com/gtucker.io/renelick) application for continuously testing the Linux kernel in virtual environments. It is at the proof-of-concept stage. The Python package (`vixi/`) runs as services in Kubernetes.

## Commands

```bash
# Deploy infrastructure
deploy/minikube                              # Create local minikube cluster
deploy/gke <project> <cluster> <region>     # Create GKE cluster
deploy/tekton                               # Install Tekton pipelines
deploy/kubevirt                             # Add KVM runtime (optional)
deploy/vixi [orchestrator] [monitor] [sched-inline] [sched-tekton[=N]] [sched-tekton-kvm[=N]]

# Update a Git mirror
kubectl create -f tekton/mirror-torvalds.yaml

# Trigger via orchestrator
renelick event send vixi event=trigger source=git tree=torvalds revision=v6.19-rc5

# Manually trigger a kernel build (bypassing orchestrator)
renelick task run tekton name=kbuild tree=torvalds \
    url=https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git \
    revision=master

# Dump oconfig
python -m vixi.oconfig --path vixi/oconfig.yaml --verbose --dump
```

The optional `=N` suffix on `sched-tekton` and `sched-tekton-kvm` limits the number of parallel pipeline instances (e.g. `sched-tekton=4`). Each instance has its own sandbox PVC, so this also controls how many PVCs are provisioned. Any number of `sched-tekton` and `sched-inline` instances may be deployed; Renelick distributes tasks across them for load balancing and redundancy. Only one orchestrator instance should be deployed.

Add `orch=debug` to manually triggered tasks to prevent the orchestrator from acting on their results.

## Architecture

VIXI is event-driven. Events flow through three pub/sub channels:
- `vixi` — application-level events (trigger, bisect progress)
- `node` — fired when a data node is created in the database
- `task` — fired when task state changes

**Services:**
- **Orchestrator** (`orchestrator.py`): Subscribes to all three channels and applies switchboard rules from `oconfig.yaml` to schedule tasks. Only one instance should be deployed.
- **Monitor** (`monitor.py`): Read-only event logger. Can be deployed on any machine.
- **Schedulers** (deployed as separate K8s services):
  - `sched-tekton` / `sched-tekton-kvm`: Heavy compute tasks (builds, KVM boots, KUnit)
  - `sched-inline` (`inline.py`): Lightweight tasks run directly in Python (parsing, delta, bisection)

**Data flow:**
```
vixi trigger event
  → Orchestrator (applies oconfig.yaml rules)
  → Scheduler (tekton or inline)
  → Task execution (Tekton pipeline or Python process)
  → Node created in database
  → node event → Orchestrator → next task (e.g. kbuild → kboot, kunit → kunit-parser)
```

**Key modules:**
- `kbuild.py` — kernel checkout, patching, build orchestration
- `kunit.py` — parses KUnit JSON results into database nodes
- `kboot.py` — handles KVM boot test result artifacts and nodes
- `delta.py` — regression detection by comparing test results between two revisions
- `bisect.py` — automated Git bisection to find regression commits
- `oconfig.py` / `oconfig.yaml` — configuration: kernel trees, schedulers, switchboard rules
- `base.py` — `sh()`/`shx()` shell helpers, `ExtendedClient` (Renelick client with history/replay)
- `tekton.py` — converts VIXI input-nodes to Tekton EventListener trigger parameters

**Kubernetes resources** (`k8s/`): namespace, per-service deployments, and three categories of PVC:
- `common`: shared 100Gi volume for Git mirrors and the Python venv
- `sandbox`: one PVC per `sched-tekton` / `sched-tekton-kvm` instance, used for build directories
- `kboot`: single PVC holding a formatted disk image; each kboot pipeline creates a temporary directory there for its artifacts

**Tekton pipelines** (`tekton/`): `kbuild-pipeline.yaml`, `kunit-pipeline.yaml`, `kboot-pipeline.yaml`, plus task definitions, triggers, and mirror jobs.

## Renelick Framework

Renelick is the underlying distributed task orchestration framework ([docs](https://renelick-gtucker-7b1c5d7d50ce51f57b4ff6327302e38a0a8f8c72d652a5.gitlab.io/)). Key concepts:
- **Nodes**: Hierarchical data records stored in a database (e.g. `vixi.test`, `vixi.delta`, `artifact-v1`)
- **Tasks**: Units of work accepted by a scheduler and executed in a runtime
- **Channels**: Pub/sub event streams (`node`, `task`, `vixi`)
- `ExtendedClient` in `base.py` wraps the Renelick client with VIXI-specific helpers (task replay, history tracking, node searching)

## Git Mirrors and Incremental Builds

Each tree has a read-only mirror PVC shared across all runtime instances. Checkouts use `git clone --reference <mirror>` for speed. Build directories are also persisted per (tree, compiler, arch) combination to enable incremental builds. Clean builds should be triggered explicitly to confirm failures.
