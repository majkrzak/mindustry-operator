from kopf import Spec
from kubernetes.client import V1JSONSchemaProps


class ServerSpecs(Spec):
    SCHEMA = V1JSONSchemaProps(
        type="object",
        properties={
            "version": V1JSONSchemaProps(type="string"),
            "externalIPs": V1JSONSchemaProps(
                type="array", items=V1JSONSchemaProps(type="string")
            ),
            "externalPort": V1JSONSchemaProps(type="integer"),
        },
    )

    @property
    def version(self) -> str:
        return self.get("version")

    @property
    def external_i_ps(self) -> [str]:
        return self.get("externalIPs")

    @property
    def external_port(self) -> int:
        return self.get("externalPort")

    @classmethod
    def cast(cls, f):
        def decorator(spec: Spec, **kwargs):
            spec.__class__ = cls
            return f(spec=spec, **kwargs)

        return decorator
