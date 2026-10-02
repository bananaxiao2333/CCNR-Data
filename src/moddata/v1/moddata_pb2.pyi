import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class EventKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    EVENT_KIND_UNSPECIFIED: _ClassVar[EventKind]
    EVENT_KIND_ROUND_ENDED: _ClassVar[EventKind]
    EVENT_KIND_GAME_OVER: _ClassVar[EventKind]
    EVENT_KIND_PHASE_ADVANCED: _ClassVar[EventKind]
    EVENT_KIND_CONFIG_EVENT_TRIGGERED: _ClassVar[EventKind]
    EVENT_KIND_EVENT_ENDED: _ClassVar[EventKind]
    EVENT_KIND_EVENTS_CLEARED: _ClassVar[EventKind]
    EVENT_KIND_CHARACTER_DEPLOYED: _ClassVar[EventKind]
    EVENT_KIND_CHARACTER_DEATH: _ClassVar[EventKind]
    EVENT_KIND_CHARACTER_KILL: _ClassVar[EventKind]
    EVENT_KIND_EVACUATION: _ClassVar[EventKind]
    EVENT_KIND_SPAWN_WAVE_TRIGGERED: _ClassVar[EventKind]

class RolePolicy(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ROLE_POLICY_UNSPECIFIED: _ClassVar[RolePolicy]
    ROLE_POLICY_OPEN: _ClassVar[RolePolicy]
    ROLE_POLICY_FROZEN: _ClassVar[RolePolicy]
    ROLE_POLICY_FORCED_ON: _ClassVar[RolePolicy]
EVENT_KIND_UNSPECIFIED: EventKind
EVENT_KIND_ROUND_ENDED: EventKind
EVENT_KIND_GAME_OVER: EventKind
EVENT_KIND_PHASE_ADVANCED: EventKind
EVENT_KIND_CONFIG_EVENT_TRIGGERED: EventKind
EVENT_KIND_EVENT_ENDED: EventKind
EVENT_KIND_EVENTS_CLEARED: EventKind
EVENT_KIND_CHARACTER_DEPLOYED: EventKind
EVENT_KIND_CHARACTER_DEATH: EventKind
EVENT_KIND_CHARACTER_KILL: EventKind
EVENT_KIND_EVACUATION: EventKind
EVENT_KIND_SPAWN_WAVE_TRIGGERED: EventKind
ROLE_POLICY_UNSPECIFIED: RolePolicy
ROLE_POLICY_OPEN: RolePolicy
ROLE_POLICY_FROZEN: RolePolicy
ROLE_POLICY_FORCED_ON: RolePolicy

class GetPlayerRequest(_message.Message):
    __slots__ = ("player_uuid", "server_id")
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    player_uuid: str
    server_id: str
    def __init__(self, player_uuid: _Optional[str] = ..., server_id: _Optional[str] = ...) -> None: ...

class PlayerData(_message.Message):
    __slots__ = ("player_uuid", "server_id", "username", "experience", "level", "roles", "version", "updated_at")
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    EXPERIENCE_FIELD_NUMBER: _ClassVar[int]
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    ROLES_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    player_uuid: str
    server_id: str
    username: str
    experience: int
    level: int
    roles: _containers.RepeatedScalarFieldContainer[str]
    version: int
    updated_at: _timestamp_pb2.Timestamp
    def __init__(self, player_uuid: _Optional[str] = ..., server_id: _Optional[str] = ..., username: _Optional[str] = ..., experience: _Optional[int] = ..., level: _Optional[int] = ..., roles: _Optional[_Iterable[str]] = ..., version: _Optional[int] = ..., updated_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class GetPlayerResponse(_message.Message):
    __slots__ = ("player",)
    PLAYER_FIELD_NUMBER: _ClassVar[int]
    player: PlayerData
    def __init__(self, player: _Optional[_Union[PlayerData, _Mapping]] = ...) -> None: ...

class ApplyExperienceRequest(_message.Message):
    __slots__ = ("request_id", "player_uuid", "server_id", "delta", "reason", "level", "username")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    DELTA_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    player_uuid: str
    server_id: str
    delta: int
    reason: str
    level: int
    username: str
    def __init__(self, request_id: _Optional[str] = ..., player_uuid: _Optional[str] = ..., server_id: _Optional[str] = ..., delta: _Optional[int] = ..., reason: _Optional[str] = ..., level: _Optional[int] = ..., username: _Optional[str] = ...) -> None: ...

class ApplyExperienceResponse(_message.Message):
    __slots__ = ("success", "experience", "level", "version")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    EXPERIENCE_FIELD_NUMBER: _ClassVar[int]
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    success: bool
    experience: int
    level: int
    version: int
    def __init__(self, success: _Optional[bool] = ..., experience: _Optional[int] = ..., level: _Optional[int] = ..., version: _Optional[int] = ...) -> None: ...

class SettlementLine(_message.Message):
    __slots__ = ("rule_id", "title", "value")
    RULE_ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    rule_id: str
    title: str
    value: int
    def __init__(self, rule_id: _Optional[str] = ..., title: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...

class RecordSettlementRequest(_message.Message):
    __slots__ = ("request_id", "server_id", "player_uuid", "match_id", "reason", "xp_before", "xp_after", "level_before", "level_after", "gain", "lines", "settled_at", "username")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    MATCH_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    XP_BEFORE_FIELD_NUMBER: _ClassVar[int]
    XP_AFTER_FIELD_NUMBER: _ClassVar[int]
    LEVEL_BEFORE_FIELD_NUMBER: _ClassVar[int]
    LEVEL_AFTER_FIELD_NUMBER: _ClassVar[int]
    GAIN_FIELD_NUMBER: _ClassVar[int]
    LINES_FIELD_NUMBER: _ClassVar[int]
    SETTLED_AT_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    server_id: str
    player_uuid: str
    match_id: str
    reason: str
    xp_before: int
    xp_after: int
    level_before: int
    level_after: int
    gain: int
    lines: _containers.RepeatedCompositeFieldContainer[SettlementLine]
    settled_at: _timestamp_pb2.Timestamp
    username: str
    def __init__(self, request_id: _Optional[str] = ..., server_id: _Optional[str] = ..., player_uuid: _Optional[str] = ..., match_id: _Optional[str] = ..., reason: _Optional[str] = ..., xp_before: _Optional[int] = ..., xp_after: _Optional[int] = ..., level_before: _Optional[int] = ..., level_after: _Optional[int] = ..., gain: _Optional[int] = ..., lines: _Optional[_Iterable[_Union[SettlementLine, _Mapping]]] = ..., settled_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., username: _Optional[str] = ...) -> None: ...

class RecordSettlementResponse(_message.Message):
    __slots__ = ("success", "xp_after", "level_after", "version", "line_count", "xp_diverged", "stored_xp_before")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    XP_AFTER_FIELD_NUMBER: _ClassVar[int]
    LEVEL_AFTER_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    XP_DIVERGED_FIELD_NUMBER: _ClassVar[int]
    STORED_XP_BEFORE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    xp_after: int
    level_after: int
    version: int
    line_count: int
    xp_diverged: bool
    stored_xp_before: int
    def __init__(self, success: _Optional[bool] = ..., xp_after: _Optional[int] = ..., level_after: _Optional[int] = ..., version: _Optional[int] = ..., line_count: _Optional[int] = ..., xp_diverged: _Optional[bool] = ..., stored_xp_before: _Optional[int] = ...) -> None: ...

class RecordEventRequest(_message.Message):
    __slots__ = ("request_id", "server_id", "kind", "match_id", "phase_id", "previous_phase_id", "definition_id", "actor_uuid", "target_uuid", "payload_json", "occurred_at")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    MATCH_ID_FIELD_NUMBER: _ClassVar[int]
    PHASE_ID_FIELD_NUMBER: _ClassVar[int]
    PREVIOUS_PHASE_ID_FIELD_NUMBER: _ClassVar[int]
    DEFINITION_ID_FIELD_NUMBER: _ClassVar[int]
    ACTOR_UUID_FIELD_NUMBER: _ClassVar[int]
    TARGET_UUID_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_JSON_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    server_id: str
    kind: EventKind
    match_id: str
    phase_id: str
    previous_phase_id: str
    definition_id: str
    actor_uuid: str
    target_uuid: str
    payload_json: str
    occurred_at: _timestamp_pb2.Timestamp
    def __init__(self, request_id: _Optional[str] = ..., server_id: _Optional[str] = ..., kind: _Optional[_Union[EventKind, str]] = ..., match_id: _Optional[str] = ..., phase_id: _Optional[str] = ..., previous_phase_id: _Optional[str] = ..., definition_id: _Optional[str] = ..., actor_uuid: _Optional[str] = ..., target_uuid: _Optional[str] = ..., payload_json: _Optional[str] = ..., occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class RecordEventResponse(_message.Message):
    __slots__ = ("success", "seq")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    success: bool
    seq: int
    def __init__(self, success: _Optional[bool] = ..., seq: _Optional[int] = ...) -> None: ...

class SetRoleOverrideRequest(_message.Message):
    __slots__ = ("request_id", "player_uuid", "server_id", "role", "enabled", "source")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    player_uuid: str
    server_id: str
    role: str
    enabled: bool
    source: str
    def __init__(self, request_id: _Optional[str] = ..., player_uuid: _Optional[str] = ..., server_id: _Optional[str] = ..., role: _Optional[str] = ..., enabled: _Optional[bool] = ..., source: _Optional[str] = ...) -> None: ...

class SetRoleOverrideResponse(_message.Message):
    __slots__ = ("success", "current_roles", "version")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_ROLES_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    success: bool
    current_roles: _containers.RepeatedScalarFieldContainer[str]
    version: int
    def __init__(self, success: _Optional[bool] = ..., current_roles: _Optional[_Iterable[str]] = ..., version: _Optional[int] = ...) -> None: ...

class GetServerConfigRequest(_message.Message):
    __slots__ = ("server_id",)
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    server_id: str
    def __init__(self, server_id: _Optional[str] = ...) -> None: ...

class GetServerConfigResponse(_message.Message):
    __slots__ = ("server_id", "role_policy", "config_json", "version", "updated_at")
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_POLICY_FIELD_NUMBER: _ClassVar[int]
    CONFIG_JSON_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    server_id: str
    role_policy: RolePolicy
    config_json: str
    version: int
    updated_at: _timestamp_pb2.Timestamp
    def __init__(self, server_id: _Optional[str] = ..., role_policy: _Optional[_Union[RolePolicy, str]] = ..., config_json: _Optional[str] = ..., version: _Optional[int] = ..., updated_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class UpdateServerConfigRequest(_message.Message):
    __slots__ = ("request_id", "server_id", "role_policy", "config_json", "actor")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_POLICY_FIELD_NUMBER: _ClassVar[int]
    CONFIG_JSON_FIELD_NUMBER: _ClassVar[int]
    ACTOR_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    server_id: str
    role_policy: RolePolicy
    config_json: str
    actor: str
    def __init__(self, request_id: _Optional[str] = ..., server_id: _Optional[str] = ..., role_policy: _Optional[_Union[RolePolicy, str]] = ..., config_json: _Optional[str] = ..., actor: _Optional[str] = ...) -> None: ...

class UpdateServerConfigResponse(_message.Message):
    __slots__ = ("success", "config")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    success: bool
    config: GetServerConfigResponse
    def __init__(self, success: _Optional[bool] = ..., config: _Optional[_Union[GetServerConfigResponse, _Mapping]] = ...) -> None: ...

class WatchChangesRequest(_message.Message):
    __slots__ = ("server_id", "since_seq")
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    SINCE_SEQ_FIELD_NUMBER: _ClassVar[int]
    server_id: str
    since_seq: int
    def __init__(self, server_id: _Optional[str] = ..., since_seq: _Optional[int] = ...) -> None: ...

class ChangeEvent(_message.Message):
    __slots__ = ("seq", "change_type", "server_id", "player_uuid", "version", "payload_json", "occurred_at")
    SEQ_FIELD_NUMBER: _ClassVar[int]
    CHANGE_TYPE_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_JSON_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    seq: int
    change_type: str
    server_id: str
    player_uuid: str
    version: int
    payload_json: str
    occurred_at: _timestamp_pb2.Timestamp
    def __init__(self, seq: _Optional[int] = ..., change_type: _Optional[str] = ..., server_id: _Optional[str] = ..., player_uuid: _Optional[str] = ..., version: _Optional[int] = ..., payload_json: _Optional[str] = ..., occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
