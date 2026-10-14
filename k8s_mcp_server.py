import logging
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("k8s-mcp")

mcp = FastMCP("k8s troubleshooting agent")

def get_clients():
    try:
        config.load_kube_config()
    except config.ConfigException as e:
        config.load_kube_config()

    return client.CoreV1Api()

def handle_error(exc):
    if isinstance(exc, ApiException):
        if exc.status == 403:
            return "Access denied by Kubernetes RBAC."
        if exc.status == 404:
            return "Resource not found. Check its name and namespace."
        return f"Kubernetes API error: HTTP {exc.status}"
    logger.exception("Kubernetes tool failed")
    return "Kubernetes operation failed. Check server logs."

@mcp.tool()
def list_pods(namespace: str = "default") -> str:
    """List pods in a Kubernetes namespace with status and restart counts."""
    try:
        api = get_clients()
        pods = api.list_namespaced_pod(namespace=namespace)

        if not pods.items:
            return f"No pods found in namespace {namespace}."

        results = []
        for pod in pods.items:
            restarts = sum(
                status.restart_count or 0
                for status in (pod.status.container_statuses or [])
            )
            results.append({
                "name": pod.metadata.name,
                "namespace": namespace,
                "phase": pod.status.phase,
                "restarts": restarts,
                "node": pod.spec.node_name,
            })

        return str(results)
    except Exception as exc:
        return handle_error(exc)

@mcp.tool()
def get_pod_logs(
    pod_name: str,
    namespace: str = "default",
) -> str:
    """Get the last 100 lines of a pod's current container logs."""
    try:
        api = get_clients()
        return api.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=100,
            timestamps=True,
        )
    except Exception as exc:
        return handle_error(exc)

@mcp.tool()
def get_pod_events(
    namespace: str = "default",
    pod_name: str = "",
) -> str:
    """Get recent Kubernetes events, optionally filtered by pod name."""
    try:
        api = get_clients()
        events = api.list_namespaced_event(namespace=namespace)

        results = []
        for event in events.items:
            involved = event.involved_object
            if pod_name and involved.name != pod_name:
                continue

            results.append({
                "reason": event.reason,
                "message": event.message,
                "object": involved.name,
                "type": event.type,
                "count": event.count,
            })

        return str(results[-30:])
    except Exception as exc:
        return handle_error(exc)


@mcp.tool()
def list_services(namespace: str = "default") -> str:
    """List services and their types and cluster IPs."""
    try:
        api = get_clients()
        services = api.list_namespaced_service(namespace=namespace)

        return str([
            {
                "name": service.metadata.name,
                "type": service.spec.type,
                "cluster_ip": service.spec.cluster_ip,
                "ports": [
                    port.port for port in (service.spec.ports or [])
                ],
            }
            for service in services.items
        ])
    except Exception as exc:
        return handle_error(exc)


@mcp.tool()
def list_nodes() -> str:
    """List Kubernetes nodes and their readiness conditions."""
    try:
        api = get_clients()
        nodes = api.list_node()

        return str([
            {
                "name": node.metadata.name,
                "conditions": [
                    {
                        "type": condition.type,
                        "status": condition.status,
                    }
                    for condition in (node.status.conditions or [])
                    if condition.type == "Ready"
                ],
            }
            for node in nodes.items
        ])
    except Exception as exc:
        return handle_error(exc)


if __name__ == "__main__":
    mcp.run()
