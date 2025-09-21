from crystal.util.xtyping import IntStr
from typing import Literal, TypeAlias, TypedDict


# ------------------------------------------------------------------------------
# Create Group

class CreateGroupFormData(TypedDict):
    source_choices: 'list[SourceChoice]'
    predicted_url_pattern: str
    predicted_source_value: 'SourceChoiceValue | None'
    predicted_name: str

class SourceChoice(TypedDict):
    display_name: str
    value: 'SourceChoiceValue | None'

class SourceChoiceValue(TypedDict):
    type: Literal['root_resource', 'resource_group']
    id: IntStr

class CreateGroupRequest(TypedDict):
    url_pattern: str
    source: SourceChoiceValue | None
    name: str
    download_immediately: bool


CreateGroupResponse: TypeAlias = 'CreateGroupErrorResponse | CreateGroupSuccessResponse'

class CreateGroupErrorResponse(TypedDict):
    error: str

class CreateGroupSuccessResponse(TypedDict):
    status: str
    message: str
    group_id: IntStr


# ------------------------------------------------------------------------------
