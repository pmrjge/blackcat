---
name: k8s-ops
description: Load for Kubernetes work — manifests, kubectl, Helm/kustomize, rollouts, debugging pods.
---
# Kubernetes operations

Part of `self-hosting-ops` (principles: one change at a time, rollback written first). Images: `container-images`; cluster infrastructure as code: `terraform-opentofu`; CI deploy jobs: `ci-cd-pipelines`. Kubernetes 1.37.1 and Helm 4.3.0 are current (Verified 2026-10-02 `git ls-remote --tags` of github.com/kubernetes/kubernetes and github.com/helm/helm).

## Safety
- Know the target first: `kubectl config current-context` and `kubectl config get-contexts`; pass `--context` explicitly in scripts.
- Read freely (`get`, `describe`, `logs`, `events`); anything that writes to a shared or production cluster (`apply`, `delete`, `scale`, `drain`, `helm upgrade`) needs the user's go-ahead with the diff shown first.
- kubectl is supported within one minor version (older or newer) of the API server; check with `kubectl version`.
- Local practice clusters: kind, k3d/k3s, minikube.

## Manifests
- Deployments: image pinned by digest; `resources.requests` (scheduling) and `limits.memory` (OOM bound); readiness probe (traffic), liveness probe (restart, only for real deadlocks), startup probe for slow starts.
- Pod `securityContext`: `runAsNonRoot: true`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities: {drop: ["ALL"]}`, `seccompProfile: {type: RuntimeDefault}`; enforce per namespace with Pod Security Admission (`pod-security.kubernetes.io/enforce: restricted`).
- Availability: `replicas` ≥ 2 plus a PodDisruptionBudget for anything that must survive node drains; `topologySpreadConstraints` across nodes.
- Network: a default-deny NetworkPolicy per namespace, then allow what is needed (needs a CNI that enforces policies).
- Secrets: base64 is encoding, not encryption; keep them out of git (External Secrets Operator, Sealed Secrets or SOPS), mount as files rather than env vars where the app allows.
- Config per environment with kustomize overlays (`kubectl apply -k overlays/prod`) or Helm values; never hand-edit live objects (`kubectl edit`) without porting the change back to git.

## Change workflow
1. Render: `kustomize build overlays/prod` or `helm template <release> <chart> -f values.yaml`.
2. Validate: `kubeconform -strict -summary` on the rendered output; `kubectl apply --dry-run=server -f -` (admission webhooks and schemas of the real cluster).
3. Diff: `kubectl diff -f -` (exit 1 = differences).
4. Apply (after the go-ahead), then `kubectl rollout status deployment/<name> --timeout=5m`.
5. Roll back: `kubectl rollout undo deployment/<name>` or `helm rollback <release> <revision>`; then fix in git.

## Debugging
| Symptom | Look | Usual cause |
|---|---|---|
| `Pending` | `kubectl describe pod` events | insufficient CPU/memory, taints without tolerations, unbound PVC |
| `ImagePullBackOff` | events | wrong tag/digest, private registry without `imagePullSecrets`, architecture mismatch |
| `CrashLoopBackOff` | `kubectl logs <pod> --previous` | app error at start, missing config or secret, failing liveness probe |
| `OOMKilled` (exit 137) | `kubectl describe pod` last state | memory limit too low or a leak |
| Service unreachable | `kubectl get endpointslices -l kubernetes.io/service-name=<svc>` | selector/label mismatch, readiness failing |
- Cluster-wide view: `kubectl get events -A --sort-by=.lastTimestamp`, `kubectl top pods` (needs metrics-server).
- Shell into a running pod without changing its image: `kubectl debug -it <pod> --image=busybox --target=<container>` (ephemeral container); port-forward to test a service: `kubectl port-forward svc/<svc> 8080:80`.

## Verify
- Rendered manifests pass `kubeconform -strict` and `kubectl apply --dry-run=server`; `kubectl diff` shows only the intended change.
- `kubectl rollout status` succeeded; pods Ready, no restarts in `kubectl get pods`; the rollback command is written down.
