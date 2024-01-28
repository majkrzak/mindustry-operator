import kopf
from kubernetes.client.api import CoreV1Api
from kubernetes.stream import stream
from kubernetes.client.models import V1PersistentVolumeClaim, V1Pod
import logging
from .const import (
    API_GROUP,
    API_VERSION,
    API_SERVER_PLURAL,
    API_SERVER_KIND,
    RELEASES_URI,
)


def build_pvc() -> V1PersistentVolumeClaim:
    pvc = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "1Gi"}},
        },
    }
    kopf.adopt(pvc)
    return CoreV1Api().create_namespaced_persistent_volume_claim(
        pvc["metadata"]["namespace"], pvc
    )


def build_pod(version: str, pvc_name: str) -> V1Pod:
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "spec": {
            "initContainers": [
                {
                    "name": "installer",
                    "image": "alpine:latest",
                    "command": [
                        "/bin/sh",
                        "-c",
                        "\n".join(
                            [
                                " ".join(
                                    [
                                        "wget",
                                        f"{RELEASES_URI}{version}/server-release.jar",
                                        "-O /opt/mindustry/server-release.jar",
                                    ]
                                )
                            ]
                        ),
                    ],
                    "volumeMounts": [
                        {"name": "server", "mountPath": "/opt/mindustry/"}
                    ],
                }
            ],
            "containers": [
                {
                    "name": "server",
                    "image": "openjdk:17-slim",
                    "workingDir": "/opt/mindustry/",
                    "command": ["java"],
                    "args": ["-jar", "/opt/mindustry/server-release.jar"],
                    "stdin": True,
                    "volumeMounts": [
                        {"name": "server", "mountPath": "/opt/mindustry/"},
                        {"name": "config", "mountPath": "/opt/mindustry/config/"},
                    ],
                }
            ],
            "volumes": [
                {"name": "server", "emptyDir": {}},
                {"name": "config", "persistentVolumeClaim": {"claimName": pvc_name}},
            ],
        },
    }
    kopf.adopt(pod)
    return CoreV1Api().create_namespaced_pod(pod["metadata"]["namespace"], pod)


@kopf.on.create(API_GROUP, API_VERSION, API_SERVER_PLURAL)
def on_create(spec: kopf.Spec, **_):
    pvc = build_pvc()
    pod = build_pod(spec["version"], pvc.metadata.name)
    logging.debug(f"Created: {[pvc, pod]!r}")


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
    connection = stream(
        CoreV1Api().connect_get_namespaced_pod_attach,
        name=name,
        namespace=namespace,
        stderr=True,
        stdout=True,
        stdin=True,
        tty=False,
        _preload_content=False,
    )
    connection.update(timeout=1)
    connection.write_stdin("host\n")
    connection.close()
