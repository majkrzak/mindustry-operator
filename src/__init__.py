import kopf
import time
from kubernetes.stream import stream
from kubernetes.client import (
    CoreV1Api,
    ApiextensionsV1Api,
    V1CustomResourceDefinition,
    V1CustomResourceDefinitionSpec,
    V1CustomResourceDefinitionNames,
    V1CustomResourceDefinitionVersion,
    V1CustomResourceValidation,
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
    V1ContainerPort,
    V1Service,
    V1ServiceSpec,
    V1ObjectMeta,
    V1ServicePort,
    V1JSONSchemaProps,
)
from .const import (
    API_GROUP,
    API_VERSION,
    API_SERVER_PLURAL,
    API_SERVER_SINGULAR,
    API_SERVER_KIND,
    RELEASES_URI,
    LABEL,
)
from .model import ServerSpecs


def build_crd():
    crd = V1CustomResourceDefinition(
        metadata=V1ObjectMeta(name=f"{API_SERVER_PLURAL}.{API_GROUP}"),
        spec=V1CustomResourceDefinitionSpec(
            group=API_GROUP,
            names=V1CustomResourceDefinitionNames(
                kind=API_SERVER_KIND,
                singular=API_SERVER_SINGULAR,
                plural=API_SERVER_PLURAL,
            ),
            scope="Namespaced",
            versions=[
                V1CustomResourceDefinitionVersion(
                    name=API_VERSION,
                    served=True,
                    storage=True,
                    schema=V1CustomResourceValidation(
                        open_apiv3_schema=V1JSONSchemaProps(
                            type="object",
                            properties={
                                "spec": ServerSpecs.SCHEMA,
                            },
                        ),
                    ),
                ),
            ],
        ),
    )
    ApiextensionsV1Api().create_custom_resource_definition(crd)


@kopf.on.create(
    "",
    "v1",
    "pod",
    when=lambda name, namespace, **_: (name, namespace)
    == ("mindustry-operator", "kube-system"),
)
def on_startup(**_):
    build_crd()


def adopt(name: str, entity):
    kopf.label(entity, {LABEL: name})
    kopf.adopt(entity)
    return entity


def build_pvc(name: str) -> V1PersistentVolumeClaim:
    pvc = adopt(
        name,
        V1PersistentVolumeClaim(
            metadata=V1ObjectMeta(name=name),
            spec=V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                resources=V1VolumeResourceRequirements(requests={"storage": "1Gi"}),
            ),
        ),
    )
    return CoreV1Api().create_namespaced_persistent_volume_claim(
        pvc.metadata.namespace, pvc
    )


def build_pod(name: str, version: str) -> V1Pod:
    pod = adopt(
        name,
        V1Pod(
            metadata=V1ObjectMeta(name=name),
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
                        ports=[
                            V1ContainerPort(
                                name="tcp",
                                container_port=6567,
                                protocol="TCP",
                            ),
                            V1ContainerPort(
                                name="udp",
                                container_port=6567,
                                protocol="UDP",
                            ),
                            V1ContainerPort(
                                name="adm",
                                container_port=6569,
                                protocol="TCP",
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
                            claim_name=name
                        ),
                    ),
                ],
            ),
        ),
    )
    return CoreV1Api().create_namespaced_pod(pod.metadata.namespace, pod)


def build_svc(name: str, external_i_ps: [str], external_port: int):
    service = adopt(
        name,
        V1Service(
            metadata=V1ObjectMeta(name=name),
            spec=V1ServiceSpec(
                selector={LABEL: name},
                external_i_ps=external_i_ps,
                ports=[
                    V1ServicePort(
                        name="tcp",
                        protocol="TCP",
                        port=external_port,
                        target_port="tcp",
                    ),
                    V1ServicePort(
                        name="udp",
                        protocol="UDP",
                        port=external_port,
                        target_port="udp",
                    ),
                ],
            ),
        ),
    )
    return CoreV1Api().create_namespaced_service(service.metadata.namespace, service)


@kopf.on.create(API_GROUP, API_VERSION, API_SERVER_PLURAL)
def on_create(name: str, spec: ServerSpecs, **_):
    build_pvc(name)
    build_pod(name, spec.version)
    build_svc(name, spec.external_i_ps, spec.external_port)


@kopf.on.update(
    "",
    "v1",
    "pods",
    labels={LABEL: kopf.PRESENT},
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
    connection.write_stdin(
        "\n".join(
            [
                "config port 6567",
                "config socketInputPort 6569",
                "config socketInputAddress 0.0.0.0",
                "config socketInput true",
                "host",
                "",
            ]
        )
    )
    connection.close()
