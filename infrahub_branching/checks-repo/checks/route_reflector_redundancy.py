from typing import Any

from infrahub_sdk.checks import InfrahubCheck

MIN_ROUTE_REFLECTORS = 2


class RouteReflectorRedundancy(InfrahubCheck):
    query = "pe_route_reflectors"

    def validate(self, data: dict[str, Any]) -> None:
        for edge in data["NetDevice"]["edges"]:
            pe = edge["node"]
            active = []
            for session in pe["bgp_sessions"]["edges"]:
                peer = session["node"]["peer"]["node"]
                if session["node"]["status"]["value"] != "established" or not peer:
                    continue
                rr = peer["device"]["node"]
                if rr["status"]["value"] == "active":
                    active.append(rr["name"]["value"])
            if len(active) < MIN_ROUTE_REFLECTORS:
                self.log_error(
                    message=f"{pe['name']['value']} keeps {len(active)} active route reflector(s): {', '.join(active) or 'none'}",
                    object_id=pe["name"]["value"],
                    object_type="NetDevice",
                )
