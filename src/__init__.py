import kopf
from kubernetes.stream import stream
from kubernetes.client import (
    CoreV1Api,
    V1PersistentVolumeClaim,
    V1Pod,
    V1PersistentVolumeClaimSpec,
    V1VolumeResourceRequirements,
    V1PodSpec,
    V1Container,
    V1VolumeMount,
    V1Volume,
    V1EmptyDirVolumeSource,
    V1PersistentVolumeClaimVolumeSource,
)
import logging
from .const import (
    API_GROUP,
    API_VERSION,
    API_SERVER_PLURAL,
    API_SERVER_KIND,
    RELEASES_URI,
)


def build_pvc() -> V1PersistentVolumeClaim:
    pvc: kopf = V1PersistentVolumeClaim(
        spec=V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            resources=V1VolumeResourceRequirements(requests={"storage": "1Gi"}),
        )
    )
    kopf.adopt(pvc)
    return CoreV1Api().create_namespaced_persistent_volume_claim(
        pvc.metadata.namespace, pvc
    )


def build_pod(version: str, pvc_name: str) -> V1Pod:
    pod = V1Pod(
        spec=V1PodSpec(
            init_containers=[
                V1Container(
                    name="installer",
                    image="alpine:latest",
                    command=[
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
                    volume_mounts=[
                        V1VolumeMount(
                            name="server",
                            mount_path="/opt/mindustry/",
                        )
                    ],
                )
            ],
            containers=[
                V1Container(
                    name="server",
                    image="openjdk:17-slim",
                    working_dir="/opt/mindustry/",
                    command=["java"],
                    args=["-jar", "/opt/mindustry/server-release.jar"],
                    stdin=True,
                    volume_mounts=[
                        V1VolumeMount(
                            name="server",
                            mount_path="/opt/mindustry/",
                        ),
                        V1VolumeMount(
                            name="config",
                            mount_path="/opt/mindustry/config",
                        ),
                    ],
                ),
            ],
            volumes=[
                V1Volume(
                    name="server",
                    empty_dir=V1EmptyDirVolumeSource(),
                ),
                V1Volume(
                    name="config",
                    persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                        claim_name=pvc_name
                    ),
                ),
            ],
        )
    )
    kopf.adopt(pod)
    return CoreV1Api().create_namespaced_pod(pod.metadata.namespace, pod)


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
