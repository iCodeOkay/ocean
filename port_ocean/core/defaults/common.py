import json
from pathlib import Path
from typing import Type, Any, Optional

import httpx
import yaml
from pydantic import ConfigDict, BaseModel, Field
from starlette import status

# Using this one instead of typing.TypedDict because of https://errors.pydantic.dev/2.5/u/typed-dict-version
from typing_extensions import TypedDict

from port_ocean.clients.port.client import PortClient
from port_ocean.core.handlers.port_app_config.models import PortAppConfig
from port_ocean.exceptions.port_defaults import (
    UnsupportedDefaultFileType,
)

YAML_EXTENSIONS = [".yaml", ".yml"]
ALLOWED_FILE_TYPES = [".json", *YAML_EXTENSIONS]


class Preset(TypedDict):
    blueprint: str
    data: list[dict[str, Any]]


class Defaults(BaseModel):
    blueprints: list[dict[str, Any]] = []
    actions: list[Preset] = []
    scorecards: list[Preset] = []
    port_app_config: Optional[PortAppConfig] = Field(
        default=None, alias="port-app-config"
    )
    model_config = ConfigDict(populate_by_name=True)


async def is_integration_exists(port_client: PortClient) -> bool:
    try:
        await port_client.get_current_integration(should_log=False)
        return True
    except httpx.HTTPStatusError as e:
        if e.response.status_code != status.HTTP_404_NOT_FOUND:
            raise e

    return False


def deconstruct_blueprints_to_creation_steps(
    raw_blueprints: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], ...]:
    """
    Deconstructing the blueprint into stages so the api wont fail to create a blueprint if there is a conflict
    example: Preventing the failure of creating a blueprint with a relation to another blueprint
    """
    (
        bare_blueprint,
        with_relations,
        full_blueprint,
    ) = ([], [], [])

    for blueprint in raw_blueprints.copy():
        full_blueprint.append(blueprint.copy())

        blueprint.pop("calculationProperties", {})
        blueprint.pop("mirrorProperties", {})
        with_relations.append(blueprint.copy())

        blueprint.pop("teamInheritance", {})
        blueprint.pop("relations", {})
        bare_blueprint.append(blueprint)

    return (
        bare_blueprint,
        with_relations,
        full_blueprint,
    )


def get_port_integration_defaults(
    port_app_config_class: Type[PortAppConfig], base_path: Path = Path(".")
) -> Defaults | None:
    defaults_dir = base_path / ".port/resources"
    if not defaults_dir.exists():
        return None

    if not defaults_dir.is_dir():
        raise UnsupportedDefaultFileType(
            f"Defaults directory is not a directory: {defaults_dir}"
        )

    default_jsons = {}
    allowed_file_names = [
        field_model.alias for _, field_model in Defaults.model_fields.items()
    ]
    for path in defaults_dir.iterdir():
        if path.stem in allowed_file_names:
            if not path.is_file() or path.suffix not in ALLOWED_FILE_TYPES:
                raise UnsupportedDefaultFileType(
                    f"Defaults directory should contain only one of the next types: {ALLOWED_FILE_TYPES}. Found: {path}"
                )

            if path.suffix in YAML_EXTENSIONS:
                default_jsons[path.stem] = yaml.safe_load(path.read_text())
            else:
                default_jsons[path.stem] = json.loads(path.read_text())

    return Defaults(
        blueprints=default_jsons.get("blueprints", []),
        actions=default_jsons.get("actions", []),
        scorecards=default_jsons.get("scorecards", []),
        port_app_config=port_app_config_class(
            **default_jsons.get("port-app-config", {})
        ),
    )
