import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, TypeAlias

import oci
from dataclasses_json import DataClassJsonMixin, LetterCase, dataclass_json
from oci.config import DEFAULT_CONFIG as OCI_DEFAULT_CONFIG
from oci.core import ComputeClient
from oci.exceptions import ServiceError
from oci.identity import IdentityClient

OciConfig: TypeAlias = Dict[str, str]


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class AuthConfig(DataClassJsonMixin):
    userId: str
    fingerprint: str
    tenancyId: str
    region: str
    apiKey: str

    def toOciConfig(self) -> OciConfig:
        config = dict(OCI_DEFAULT_CONFIG)
        config.update({
            'user': self.userId,
            'fingerprint': self.fingerprint,
            'tenancy': self.tenancyId,
            'region': self.region,
            'key_content': self.apiKey
        })
        return config


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class VmConfig(DataClassJsonMixin):
    compartmentId: str
    shape: str
    imageId: str
    subnetId: str
    sshPublicKey: str


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ScriptConfig(DataClassJsonMixin):
    auth: AuthConfig
    vmConfig: VmConfig


class VmCreator:

    def __init__(self, cfgPath: Path) -> None:
        self._config: ScriptConfig = self._loadConfig(cfgPath=cfgPath)

    @property
    def _ociConfig(self) -> OciConfig:
        return self._config.auth.toOciConfig()

    @property
    def _vmConfig(self) -> VmConfig:
        return self._config.vmConfig

    def create(self) -> None:
        attemptCounter = 0

        existingVms = self._getExistingVms()
        if len(existingVms) > 0:
            print(" ===> VM already exists:", existingVms)
            return

        while True:
            availabilityDomains = self._getAvailabilityDomains()
            print(f" ==> Detected {len(availabilityDomains)} availability domains:")
            for availabilityDomain in availabilityDomains:
                print(availabilityDomain)
            print()

            for availabilityDomain in availabilityDomains:
                try:
                    attemptCounter += 1
                    print(f" ==> Attempting to create VM:\n - trial='{attemptCounter}',\n - availabilityDomain='{availabilityDomain}'\n")
                    response = self._requestCreation(availabilityDomain=availabilityDomain)

                    self._awaitRunning(instanceId=response.data.id)
                    return

                except ServiceError as ex:
                    print(f"ServiceError error: [{ex.status}]:'{ex.message}'\n")
                except Exception as ex:
                    print(f"Exception occurred: {str(ex)}\n")
                finally:
                    time.sleep(30)

    def _requestCreation(self, availabilityDomain: str) -> oci.response.Response:
        return ComputeClient(self._ociConfig).launch_instance(
            launch_instance_details=oci.core.models.LaunchInstanceDetails(
                availability_domain=availabilityDomain,
                compartment_id=self._vmConfig.compartmentId,
                shape=self._vmConfig.shape,
                subnet_id=self._vmConfig.subnetId,
                metadata={
                    "ssh_authorized_keys": self._vmConfig.sshPublicKey
                },
                create_vnic_details=oci.core.models.CreateVnicDetails(
                    assign_public_ip=True,
                    assign_private_dns_record=True,
                    subnet_id=self._vmConfig.subnetId
                ),
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                    ocpus=4,
                    memory_in_gbs=24),
                source_details=oci.core.models.InstanceSourceViaImageDetails(
                    source_type="image",
                    image_id=self._vmConfig.imageId
                ),
                display_name="PythonInstance"
            )
        )

    def _awaitRunning(self, instanceId: str) -> None:
        print(f" ==> Instance {instanceId} created! Awaiting start...")
        while True:
            instance = ComputeClient(self._ociConfig).get_instance(instanceId).data
            if instance.lifecycle_state == "RUNNING":
                print(f" ==> Instance {instanceId} is running!")
                break

            print(instance)
            time.sleep(30)

    def _getAvailabilityDomains(self) -> List[str]:
        identityClient = IdentityClient(self._ociConfig)
        response = identityClient.list_availability_domains(compartment_id=self._vmConfig.compartmentId)
        return [ad.name for ad in response.data]

    def _getExistingVms(self) -> List[Dict[str, str]]:
        return ComputeClient(self._ociConfig).list_instances(compartment_id=self._vmConfig.compartmentId).data

    @staticmethod
    def _loadConfig(cfgPath: Path) -> ScriptConfig:
        with open(cfgPath) as f:
            return ScriptConfig.from_json(f.read())


def main() -> None:
    scriptDir = Path(__file__).parent
    vmCreator = VmCreator(cfgPath=scriptDir / 'config.json')
    vmCreator.create()


if __name__ == '__main__':
    main()
