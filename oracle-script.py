import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, TypeAlias

import oci
from dataclasses_json import DataClassJsonMixin, LetterCase, dataclass_json
from oci.core import ComputeClient
from oci.exceptions import ServiceError
from oci.identity import IdentityClient

OracleConfig: TypeAlias = Dict[str, str]


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ScriptConfig(DataClassJsonMixin):
    compartmentId: str
    shape: str
    imageId: str
    subnetId: str
    sshPublicKeyPath: str


class VmCreator:

    def __init__(self, cfgDirPath: Path) -> None:
        self._cfgOracle: OracleConfig = self._getOracleConfig(cfgDirPath=cfgDirPath)
        self._cfgScript: ScriptConfig = self._getScriptConfig(cfgDirPath=cfgDirPath)

    def create(self) -> None:
        attemptCounter = 0

        existingVms = self._getExistingVms()
        if len(existingVms) > 0:
            print(" ===> VM already exists:", existingVms)
            return

        availabilityDomains = self._getAvailabilityDomains()
        print(f" ==> Detected {len(availabilityDomains)} availability domains:")
        for availabilityDomain in availabilityDomains:
            print(availabilityDomain)
        print()

        while True:
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
        return ComputeClient(self._cfgOracle).launch_instance(
            launch_instance_details=oci.core.models.LaunchInstanceDetails(
                availability_domain=availabilityDomain,
                compartment_id=self._cfgScript.compartmentId,
                shape=self._cfgScript.shape,
                subnet_id=self._cfgScript.subnetId,
                metadata={
                    "ssh_authorized_keys": self._getSshPublicKey()
                },
                create_vnic_details=oci.core.models.CreateVnicDetails(
                    assign_public_ip=True,
                    assign_private_dns_record=True,
                    subnet_id=self._cfgScript.subnetId
                ),
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                    ocpus=4,
                    memory_in_gbs=24),
                source_details=oci.core.models.InstanceSourceViaImageDetails(
                    source_type="image",
                    image_id=self._cfgScript.imageId
                ),
                display_name="PythonInstance"
            )
        )

    def _awaitRunning(self, instanceId: str) -> None:
        print(f" ==> Instance {instanceId} created! Awaiting start...")
        while True:
            instance = ComputeClient(self._cfgOracle).get_instance(instanceId).data
            if instance.lifecycle_state == "RUNNING":
                print(f" ==> Instance {instanceId} is running!")
                break

            print(instance)
            time.sleep(30)

    def _getAvailabilityDomains(self) -> List[str]:
        identityClient = IdentityClient(self._cfgOracle)
        response = identityClient.list_availability_domains(compartment_id=self._cfgScript.compartmentId)
        return [ad.name for ad in response.data]

    def _getExistingVms(self) -> List[Dict[str, str]]:
        return ComputeClient(self._cfgOracle).list_instances(compartment_id=self._cfgScript.compartmentId).data

    def _getSshPublicKey(self) -> str:
        with open(Path(self._cfgScript.sshPublicKeyPath).expanduser()) as f:
            return f.read()

    @staticmethod
    def _getOracleConfig(cfgDirPath: Path) -> OracleConfig:
        return oci.config.from_file(file_location=cfgDirPath / 'config-oracle.ini')

    @staticmethod
    def _getScriptConfig(cfgDirPath: Path) -> ScriptConfig:
        with open(cfgDirPath / 'config-script.json') as f:
            return ScriptConfig.from_json(f.read())


def main() -> None:
    scriptDir = Path(__file__).absolute().parent
    vmCreator = VmCreator(cfgDirPath=scriptDir / 'config')
    vmCreator.create()


if __name__ == '__main__':
    main()
