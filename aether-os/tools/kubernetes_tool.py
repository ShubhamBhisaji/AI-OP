"""
kubernetes_tool — Monitor and manage Kubernetes clusters.

Requires:  pip install kubernetes
Env vars:
    KUBECONFIG — Path to your kubeconfig file (default: ~/.kube/config).
                 For GKE/EKS/AKS the cluster must already be authenticated.

Actions — Read
───────────────────────────────────────────────────────────────────
  list_pods        : List pods in a namespace (default: default).
  list_deployments : List deployments in a namespace.
  list_services    : List services in a namespace.
  list_namespaces  : List all namespaces in the cluster.
  list_nodes       : List cluster nodes with status and resource info.
  get_pod_logs     : Fetch logs from a pod (last N lines).
  describe_pod     : Full status, events, and container info for a pod.

Actions — Write (require confirm="yes")
───────────────────────────────────────────────────────────────────
  restart_deployment : Rollout-restart a deployment (triggers new pods).
  scale_deployment   : Set the replica count for a deployment.
  delete_pod         : Delete (evict) a pod so it restarts from its controller.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def kubernetes_tool(
    action: str,
    namespace: str = "default",
    pod: str = "",
    deployment: str = "",
    service: str = "",
    container: str = "",
    log_lines: int = 50,
    replicas: int = 1,
    confirm: str = "",
) -> str:
    """
    Interact with a Kubernetes cluster.

    action      : See module-level Actions list.
    namespace   : Kubernetes namespace (default: 'default').
    pod         : Pod name for pod-specific actions.
    deployment  : Deployment name for deployment actions.
    service     : Service name (reserved for future use).
    container   : Container name within a pod (optional).
    log_lines   : Number of tail lines for get_pod_logs (default: 50).
    replicas    : Target replica count for scale_deployment.
    confirm     : Pass 'yes' for write operations (restart, scale, delete).
    """
    try:
        from kubernetes import client as k8s_client, config as k8s_config  # type: ignore
        from kubernetes.client.rest import ApiException                      # type: ignore
    except ImportError:
        return (
            "Error: kubernetes package not installed.\n"
            "Install with: pip install kubernetes"
        )

    action = (action or "").strip().lower()
    if not action:
        return "Error: 'action' is required."

    # Load kube config
    kubeconfig = os.environ.get("KUBECONFIG", "").strip()
    try:
        if kubeconfig:
            k8s_config.load_kube_config(config_file=kubeconfig)
        else:
            try:
                k8s_config.load_incluster_config()   # running inside a pod
            except k8s_config.ConfigException:
                k8s_config.load_kube_config()        # local ~/.kube/config
    except Exception as exc:
        return (
            f"Failed to load Kubernetes config: {exc}\n"
            "Ensure KUBECONFIG is set or ~/.kube/config exists and is valid."
        )

    v1     = k8s_client.CoreV1Api()
    apps_v1 = k8s_client.AppsV1Api()

    try:
        # ── list_namespaces ──────────────────────────────────────────
        if action == "list_namespaces":
            ns_list = v1.list_namespace()
            lines = ["Namespaces:"]
            for ns in ns_list.items:
                phase = ns.status.phase or "Unknown"
                lines.append(f"  • {ns.metadata.name}  [{phase}]")
            return "\n".join(lines) if len(lines) > 1 else "No namespaces found."

        # ── list_nodes ───────────────────────────────────────────────
        if action == "list_nodes":
            node_list = v1.list_node()
            lines = ["Cluster Nodes:"]
            for node in node_list.items:
                name  = node.metadata.name
                ready = next(
                    (c.status for c in node.status.conditions if c.type == "Ready"),
                    "Unknown",
                )
                cpu   = node.status.capacity.get("cpu", "?")
                mem   = node.status.capacity.get("memory", "?")
                lines.append(f"  • {name}  Ready={ready}  CPU={cpu}  Mem={mem}")
            return "\n".join(lines) if len(lines) > 1 else "No nodes found."

        # ── list_pods ────────────────────────────────────────────────
        if action == "list_pods":
            pod_list = v1.list_namespaced_pod(namespace=namespace)
            if not pod_list.items:
                return f"No pods in namespace '{namespace}'."
            lines = [f"Pods in '{namespace}':"]
            for p in pod_list.items:
                phase = p.status.phase or "Unknown"
                restarts = sum(
                    (cs.restart_count or 0)
                    for cs in (p.status.container_statuses or [])
                )
                lines.append(
                    f"  • {p.metadata.name}  [{phase}]  "
                    f"restarts={restarts}  IP={p.status.pod_ip or 'none'}"
                )
            return "\n".join(lines)

        # ── list_deployments ─────────────────────────────────────────
        if action == "list_deployments":
            dep_list = apps_v1.list_namespaced_deployment(namespace=namespace)
            if not dep_list.items:
                return f"No deployments in namespace '{namespace}'."
            lines = [f"Deployments in '{namespace}':"]
            for d in dep_list.items:
                desired   = d.spec.replicas or 0
                available = d.status.available_replicas or 0
                lines.append(
                    f"  • {d.metadata.name}  "
                    f"{available}/{desired} replicas available  "
                    f"image={d.spec.template.spec.containers[0].image}"
                )
            return "\n".join(lines)

        # ── list_services ────────────────────────────────────────────
        if action == "list_services":
            svc_list = v1.list_namespaced_service(namespace=namespace)
            if not svc_list.items:
                return f"No services in namespace '{namespace}'."
            lines = [f"Services in '{namespace}':"]
            for svc in svc_list.items:
                stype    = svc.spec.type
                cluster_ip = svc.spec.cluster_ip
                ports    = ", ".join(
                    f"{p.port}/{p.protocol}" for p in (svc.spec.ports or [])
                )
                lines.append(f"  • {svc.metadata.name}  [{stype}]  {cluster_ip}  ports: {ports}")
            return "\n".join(lines)

        # ── get_pod_logs ─────────────────────────────────────────────
        if action == "get_pod_logs":
            if not pod:
                return "Error: 'pod' is required for get_pod_logs."
            kwargs: dict = {"namespace": namespace, "tail_lines": max(1, min(log_lines, 500))}
            if container:
                kwargs["container"] = container
            logs = v1.read_namespaced_pod_log(name=pod, **kwargs)
            return f"Logs for pod '{pod}' (last {log_lines} lines):\n{logs}" if logs else "(no logs)"

        # ── describe_pod ─────────────────────────────────────────────
        if action == "describe_pod":
            if not pod:
                return "Error: 'pod' is required for describe_pod."
            p = v1.read_namespaced_pod(name=pod, namespace=namespace)
            lines = [
                f"Pod: {p.metadata.name}  Namespace: {p.metadata.namespace}",
                f"Phase      : {p.status.phase}",
                f"Pod IP     : {p.status.pod_ip}",
                f"Node       : {p.spec.node_name}",
                f"Start Time : {p.status.start_time}",
                "",
                "Containers:",
            ]
            for cs in (p.status.container_statuses or []):
                lines.append(
                    f"  • {cs.name}  ready={cs.ready}  "
                    f"restarts={cs.restart_count}  image={cs.image}"
                )
            # Events
            events = v1.list_namespaced_event(namespace=namespace,
                                               field_selector=f"involvedObject.name={pod}")
            recent = sorted(events.items, key=lambda e: e.last_timestamp or e.event_time or "", reverse=True)[:5]
            if recent:
                lines.append("\nRecent Events:")
                for ev in recent:
                    lines.append(f"  [{ev.type}] {ev.reason}: {ev.message}")
            return "\n".join(lines)

        # ── restart_deployment ───────────────────────────────────────
        if action == "restart_deployment":
            if not deployment:
                return "Error: 'deployment' is required for restart_deployment."
            if confirm.strip().lower() != "yes":
                return f"⚠ Pass confirm='yes' to restart deployment '{deployment}' in '{namespace}'."
            import datetime
            patch = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": datetime.datetime.utcnow().isoformat()
                            }
                        }
                    }
                }
            }
            apps_v1.patch_namespaced_deployment(name=deployment, namespace=namespace, body=patch)
            return f"Rollout restart triggered for deployment '{deployment}' in '{namespace}'."

        # ── scale_deployment ─────────────────────────────────────────
        if action == "scale_deployment":
            if not deployment:
                return "Error: 'deployment' is required for scale_deployment."
            if confirm.strip().lower() != "yes":
                return (
                    f"⚠ Pass confirm='yes' to scale deployment '{deployment}' "
                    f"to {replicas} replica(s)."
                )
            replicas = max(0, replicas)
            patch = {"spec": {"replicas": replicas}}
            apps_v1.patch_namespaced_deployment(name=deployment, namespace=namespace, body=patch)
            return f"Deployment '{deployment}' scaled to {replicas} replica(s)."

        # ── delete_pod ───────────────────────────────────────────────
        if action == "delete_pod":
            if not pod:
                return "Error: 'pod' is required for delete_pod."
            if confirm.strip().lower() != "yes":
                return f"⚠ Pass confirm='yes' to delete pod '{pod}' in '{namespace}'."
            v1.delete_namespaced_pod(name=pod, namespace=namespace)
            return f"Pod '{pod}' deleted from '{namespace}' — its controller will recreate it."

        return f"Unknown action '{action}'. See module docstring for valid actions."

    except ApiException as exc:  # type: ignore[possibly-undefined]
        return f"Kubernetes API error ({exc.status}): {exc.reason}"
    except Exception as exc:
        logger.error("kubernetes_tool: %s", exc)
        return f"Error: {exc}"
