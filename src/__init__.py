import kopf
import kubernetes
import logging
from .const import API_GROUP, API_VERSION, API_SERVER_PLURAL, API_SERVER_KIND


@kopf.on.create(API_GROUP, API_VERSION, API_SERVER_PLURAL)
def on_create(**_):
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "spec": {
            "containers": [
                {
                    "image": "busybox",
                    "name": "sleep",
                    "args": ["/bin/sh", "-c", "cat"],
                    "stdin": True,
                }
            ]
        },
    }
    kopf.adopt(pod)
    api = kubernetes.client.CoreV1Api()
    api.create_namespaced_pod(pod["metadata"]["namespace"], pod)


def is_server_pod(meta: kopf.Meta, **_) -> bool:
    for ownerReference in meta.get("ownerReferences") or []:
        if (
            ownerReference["kind"] == API_SERVER_KIND
            and ownerReference["apiVersion"] == f"{API_GROUP}/{API_VERSION}"
        ):
            return True
    return False


@kopf.on.update(
    "",
    "v1",
    "pods",
    when=is_server_pod,
    field="status.phase",
    old="Pending",
    new="Running",
)
def on_pod_(name: str, namespace: str, **_):
    api = kubernetes.client.CoreV1Api()

    stream = kubernetes.stream.stream(
        api.connect_get_namespaced_pod_attach,
        name=name,
        namespace=namespace,
        stderr=True,
        stdout=True,
        stdin=True,
        tty=False,
        _preload_content=False,
    )

    stream.update(timeout=1)
    stream.write_stdin("Hello moto!\n")
    stream.close()
