from typing import Any

from infrahub_sdk.checks import InfrahubCheck

# Service, firewall, firewall interface, interco, PE interface, PE.
SERVICE_TO_PE_DEPTH = 5


class PciFirewalls(InfrahubCheck):
    query = "pci_services"

    async def validate(self, data: dict[str, Any]) -> None:
        devices = {edge["node"]["id"]: edge["node"] for edge in data["NetDevice"]["edges"]}
        pe_ids = {device_id for device_id, device in devices.items() if device["role"]["value"] == "pe"}
        certified = {
            device_id
            for device_id, device in devices.items()
            if device["role"]["value"] == "firewall" and device["pci_certified"]["value"]
        }
        for edge in data["NetAppService"]["edges"]:
            service = edge["node"]
            reachable = await self.client.reachable_nodes(
                service["id"], ["NetDevice"], max_depth=SERVICE_TO_PE_DEPTH, branch=self.branch_name
            )
            service_name = service["name"]["value"]
            for pe_id in [dependency.node.id for dependency in reachable.dependencies if dependency.node.id in pe_ids]:
                pe_name = devices[pe_id]["name"]["value"]
                # Every path counts: the shortest one alone would hide a longer bypass.
                result = await self.client.traverse_paths(
                    service["id"],
                    pe_id,
                    max_depth=SERVICE_TO_PE_DEPTH,
                    shortest_paths_only=False,
                    branch=self.branch_name,
                )
                # A search cut short by the server time budget may miss the bypass path.
                if result.truncated_at_depth is not None:
                    self.log_error(
                        message=f"{service_name} to {pe_name}: the path search stopped at depth {result.truncated_at_depth}, so the rule cannot be confirmed",
                        object_id=service_name,
                        object_type="NetAppService",
                    )
                for path in result.paths:
                    if any(hop.node.id in certified for hop in path.hops):
                        continue
                    hops = " > ".join(hop.node.display_label for hop in path.hops)
                    self.log_error(
                        message=f"{service_name} reaches {pe_name} without a PCI-DSS certified firewall: {hops}",
                        object_id=service_name,
                        object_type="NetAppService",
                    )
