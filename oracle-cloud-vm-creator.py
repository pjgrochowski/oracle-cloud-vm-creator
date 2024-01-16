import time
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, TypeAlias

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

    def tryCreate(self, persistent: bool = False) -> None:
        existingVms = self._getExistingVms()
        if len(existingVms) > 0:
            print(" ===> VM already exists:", existingVms)
            return

        print(f" ===> Run mode: '{'persistent' if persistent else 'oneshot'}' (Cooldowns: {self._getCooldown(persistent=persistent)}s)\n")

        for runNumber in self._makeRunCounter(persistent=persistent):
            availabilityDomains = self._getAvailabilityDomains()
            print(f" ===> Detected {len(availabilityDomains)} availability domains:\n%s\n" % '\n'.join(availabilityDomains))

            for domainNumber, domainName in enumerate(availabilityDomains):
                time.sleep(self._getCooldown(persistent=persistent))
                try:
                    attemptNumber = domainNumber + runNumber * len(availabilityDomains) + 1
                    print(f" ==> Attempt {attemptNumber} to create VM. Using availability domain: '{domainName}'")
                    response = self._requestCreation(availabilityDomain=domainName)

                    instanceId = response.data.id
                    print(f" ==> Instance {instanceId} created successfully!")

                    if persistent:
                        self._awaitRunning(instanceId=instanceId)

                    return

                except ServiceError as ex:
                    print(f"ServiceError error: [{ex.status}]:'{ex.message}'\n")
                except Exception as ex:
                    print(f"Exception occurred: {str(ex)}\n")

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
        try:
            print(f" ==> Awaiting start...")
            while True:
                instance = ComputeClient(self._ociConfig).get_instance(instanceId).data
                if instance.lifecycle_state == "RUNNING":
                    print(f" ==> Instance {instanceId} is running!")
                    break

                print(instance)
                time.sleep(self._getCooldown(persistent=True))

        except Exception as ex:
            print(f"Exception occurred: {str(ex)}\n")

    def _getAvailabilityDomains(self) -> List[str]:
        identityClient = IdentityClient(self._ociConfig)
        response = identityClient.list_availability_domains(compartment_id=self._vmConfig.compartmentId)
        return [ad.name for ad in response.data]

    def _getExistingVms(self) -> List[Dict[str, str]]:
        return ComputeClient(self._ociConfig).list_instances(compartment_id=self._vmConfig.compartmentId).data

    @staticmethod
    def _getCooldown(persistent: bool) -> int:
        return 30 if persistent else 1

    @staticmethod
    def _makeRunCounter(persistent: bool) -> Iterator[int]:
        counter = 0
        yield counter
        while persistent:
            counter += 1
            yield counter

    @staticmethod
    def _loadConfig(cfgPath: Path) -> ScriptConfig:
        with open(cfgPath) as f:
            return ScriptConfig.from_json(f.read())


def main() -> None:
    argParser = ArgumentParser(description='Oracle cloud Ampere VM creator')
    argParser.add_argument('-p', '--persistent', help='Run in a loop until succeeds (includes longer cooldowns)', action='store_true')
    args = argParser.parse_args()

    scriptDir = Path(__file__).parent
    vmCreator = VmCreator(cfgPath=scriptDir / 'config.json')
    vmCreator.tryCreate(persistent=args.persistent)


if __name__ == '__main__':
    main()
