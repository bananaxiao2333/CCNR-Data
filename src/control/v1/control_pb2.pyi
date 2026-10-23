import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AuthorizeReason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    AUTHORIZE_REASON_UNSPECIFIED: _ClassVar[AuthorizeReason]
    AUTHORIZE_REASON_ALLOWED: _ClassVar[AuthorizeReason]
    AUTHORIZE_REASON_NOT_LINKED: _ClassVar[AuthorizeReason]
    AUTHORIZE_REASON_EMAIL_UNVERIFIED: _ClassVar[AuthorizeReason]
    AUTHORIZE_REASON_BANNED: _ClassVar[AuthorizeReason]
    AUTHORIZE_REASON_WHITELIST_ONLY: _ClassVar[AuthorizeReason]
    AUTHORIZE_REASON_ROLE_DENIED: _ClassVar[AuthorizeReason]
    AUTHORIZE_REASON_CASDOOR_UNAVAILABLE: _ClassVar[AuthorizeReason]
    AUTHORIZE_REASON_POLICY_ERROR: _ClassVar[AuthorizeReason]

class ProxyEventKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PROXY_EVENT_KIND_UNSPECIFIED: _ClassVar[ProxyEventKind]
    PROXY_EVENT_KIND_SESSION_STARTED: _ClassVar[ProxyEventKind]
    PROXY_EVENT_KIND_SESSION_HEARTBEAT: _ClassVar[ProxyEventKind]
    PROXY_EVENT_KIND_SERVER_SWITCHED: _ClassVar[ProxyEventKind]
    PROXY_EVENT_KIND_SESSION_ENDED: _ClassVar[ProxyEventKind]
    PROXY_EVENT_KIND_LOGIN_DENIED: _ClassVar[ProxyEventKind]

class IdentitySource(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    IDENTITY_SOURCE_UNSPECIFIED: _ClassVar[IdentitySource]
    IDENTITY_SOURCE_ADMIN: _ClassVar[IdentitySource]
    IDENTITY_SOURCE_BOT: _ClassVar[IdentitySource]
    IDENTITY_SOURCE_SKIN: _ClassVar[IdentitySource]
    IDENTITY_SOURCE_IMPORT: _ClassVar[IdentitySource]
    IDENTITY_SOURCE_PASS: _ClassVar[IdentitySource]

class SubjectType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SUBJECT_TYPE_UNSPECIFIED: _ClassVar[SubjectType]
    SUBJECT_TYPE_PLAYER_UUID: _ClassVar[SubjectType]
    SUBJECT_TYPE_USERNAME: _ClassVar[SubjectType]
    SUBJECT_TYPE_CASDOOR_USER: _ClassVar[SubjectType]

class RuleEffect(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RULE_EFFECT_UNSPECIFIED: _ClassVar[RuleEffect]
    RULE_EFFECT_ALLOW: _ClassVar[RuleEffect]
    RULE_EFFECT_DENY: _ClassVar[RuleEffect]

class AccessMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ACCESS_MODE_UNSPECIFIED: _ClassVar[AccessMode]
    ACCESS_MODE_OPEN: _ClassVar[AccessMode]
    ACCESS_MODE_WHITELIST: _ClassVar[AccessMode]

class DeviceLoginStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DEVICE_LOGIN_STATUS_UNSPECIFIED: _ClassVar[DeviceLoginStatus]
    DEVICE_LOGIN_STATUS_PENDING: _ClassVar[DeviceLoginStatus]
    DEVICE_LOGIN_STATUS_APPROVED: _ClassVar[DeviceLoginStatus]
    DEVICE_LOGIN_STATUS_DENIED: _ClassVar[DeviceLoginStatus]
    DEVICE_LOGIN_STATUS_EXPIRED: _ClassVar[DeviceLoginStatus]
AUTHORIZE_REASON_UNSPECIFIED: AuthorizeReason
AUTHORIZE_REASON_ALLOWED: AuthorizeReason
AUTHORIZE_REASON_NOT_LINKED: AuthorizeReason
AUTHORIZE_REASON_EMAIL_UNVERIFIED: AuthorizeReason
AUTHORIZE_REASON_BANNED: AuthorizeReason
AUTHORIZE_REASON_WHITELIST_ONLY: AuthorizeReason
AUTHORIZE_REASON_ROLE_DENIED: AuthorizeReason
AUTHORIZE_REASON_CASDOOR_UNAVAILABLE: AuthorizeReason
AUTHORIZE_REASON_POLICY_ERROR: AuthorizeReason
PROXY_EVENT_KIND_UNSPECIFIED: ProxyEventKind
PROXY_EVENT_KIND_SESSION_STARTED: ProxyEventKind
PROXY_EVENT_KIND_SESSION_HEARTBEAT: ProxyEventKind
PROXY_EVENT_KIND_SERVER_SWITCHED: ProxyEventKind
PROXY_EVENT_KIND_SESSION_ENDED: ProxyEventKind
PROXY_EVENT_KIND_LOGIN_DENIED: ProxyEventKind
IDENTITY_SOURCE_UNSPECIFIED: IdentitySource
IDENTITY_SOURCE_ADMIN: IdentitySource
IDENTITY_SOURCE_BOT: IdentitySource
IDENTITY_SOURCE_SKIN: IdentitySource
IDENTITY_SOURCE_IMPORT: IdentitySource
IDENTITY_SOURCE_PASS: IdentitySource
SUBJECT_TYPE_UNSPECIFIED: SubjectType
SUBJECT_TYPE_PLAYER_UUID: SubjectType
SUBJECT_TYPE_USERNAME: SubjectType
SUBJECT_TYPE_CASDOOR_USER: SubjectType
RULE_EFFECT_UNSPECIFIED: RuleEffect
RULE_EFFECT_ALLOW: RuleEffect
RULE_EFFECT_DENY: RuleEffect
ACCESS_MODE_UNSPECIFIED: AccessMode
ACCESS_MODE_OPEN: AccessMode
ACCESS_MODE_WHITELIST: AccessMode
DEVICE_LOGIN_STATUS_UNSPECIFIED: DeviceLoginStatus
DEVICE_LOGIN_STATUS_PENDING: DeviceLoginStatus
DEVICE_LOGIN_STATUS_APPROVED: DeviceLoginStatus
DEVICE_LOGIN_STATUS_DENIED: DeviceLoginStatus
DEVICE_LOGIN_STATUS_EXPIRED: DeviceLoginStatus

class AuthorizePlayerRequest(_message.Message):
    __slots__ = ("player_uuid", "username", "proxy_id", "server_id", "client_version", "protocol_version")
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    PROXY_ID_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    CLIENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    player_uuid: str
    username: str
    proxy_id: str
    server_id: str
    client_version: str
    protocol_version: int
    def __init__(self, player_uuid: _Optional[str] = ..., username: _Optional[str] = ..., proxy_id: _Optional[str] = ..., server_id: _Optional[str] = ..., client_version: _Optional[str] = ..., protocol_version: _Optional[int] = ...) -> None: ...

class AuthorizePlayerResponse(_message.Message):
    __slots__ = ("allowed", "reason", "message", "roles", "casdoor_user_id", "cache_ttl_seconds")
    ALLOWED_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ROLES_FIELD_NUMBER: _ClassVar[int]
    CASDOOR_USER_ID_FIELD_NUMBER: _ClassVar[int]
    CACHE_TTL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    allowed: bool
    reason: AuthorizeReason
    message: str
    roles: _containers.RepeatedScalarFieldContainer[str]
    casdoor_user_id: str
    cache_ttl_seconds: int
    def __init__(self, allowed: _Optional[bool] = ..., reason: _Optional[_Union[AuthorizeReason, str]] = ..., message: _Optional[str] = ..., roles: _Optional[_Iterable[str]] = ..., casdoor_user_id: _Optional[str] = ..., cache_ttl_seconds: _Optional[int] = ...) -> None: ...

class ReportProxyEventRequest(_message.Message):
    __slots__ = ("request_id", "kind", "session_id", "player_uuid", "username", "server_id", "from_server_id", "occurred_at", "client_version", "protocol_version", "end_reason", "deny_reason", "proxy_id")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    FROM_SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    CLIENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    END_REASON_FIELD_NUMBER: _ClassVar[int]
    DENY_REASON_FIELD_NUMBER: _ClassVar[int]
    PROXY_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    kind: ProxyEventKind
    session_id: str
    player_uuid: str
    username: str
    server_id: str
    from_server_id: str
    occurred_at: _timestamp_pb2.Timestamp
    client_version: str
    protocol_version: int
    end_reason: str
    deny_reason: str
    proxy_id: str
    def __init__(self, request_id: _Optional[str] = ..., kind: _Optional[_Union[ProxyEventKind, str]] = ..., session_id: _Optional[str] = ..., player_uuid: _Optional[str] = ..., username: _Optional[str] = ..., server_id: _Optional[str] = ..., from_server_id: _Optional[str] = ..., occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., client_version: _Optional[str] = ..., protocol_version: _Optional[int] = ..., end_reason: _Optional[str] = ..., deny_reason: _Optional[str] = ..., proxy_id: _Optional[str] = ...) -> None: ...

class ReportProxyEventResponse(_message.Message):
    __slots__ = ("success", "server_time")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    SERVER_TIME_FIELD_NUMBER: _ClassVar[int]
    success: bool
    server_time: _timestamp_pb2.Timestamp
    def __init__(self, success: _Optional[bool] = ..., server_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class OnlinePlayer(_message.Message):
    __slots__ = ("player_uuid", "username", "server_id", "proxy_id", "session_id", "started_at", "last_seen_at")
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    PROXY_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    LAST_SEEN_AT_FIELD_NUMBER: _ClassVar[int]
    player_uuid: str
    username: str
    server_id: str
    proxy_id: str
    session_id: str
    started_at: _timestamp_pb2.Timestamp
    last_seen_at: _timestamp_pb2.Timestamp
    def __init__(self, player_uuid: _Optional[str] = ..., username: _Optional[str] = ..., server_id: _Optional[str] = ..., proxy_id: _Optional[str] = ..., session_id: _Optional[str] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., last_seen_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ListOnlinePlayersRequest(_message.Message):
    __slots__ = ("server_id", "limit")
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    server_id: str
    limit: int
    def __init__(self, server_id: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class ListOnlinePlayersResponse(_message.Message):
    __slots__ = ("players", "total")
    PLAYERS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    players: _containers.RepeatedCompositeFieldContainer[OnlinePlayer]
    total: int
    def __init__(self, players: _Optional[_Iterable[_Union[OnlinePlayer, _Mapping]]] = ..., total: _Optional[int] = ...) -> None: ...

class GetPlayerPlaytimeRequest(_message.Message):
    __slots__ = ("player_uuid", "username", "casdoor_user_id", "from_time", "to_time")
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    CASDOOR_USER_ID_FIELD_NUMBER: _ClassVar[int]
    FROM_TIME_FIELD_NUMBER: _ClassVar[int]
    TO_TIME_FIELD_NUMBER: _ClassVar[int]
    player_uuid: str
    username: str
    casdoor_user_id: str
    from_time: _timestamp_pb2.Timestamp
    to_time: _timestamp_pb2.Timestamp
    def __init__(self, player_uuid: _Optional[str] = ..., username: _Optional[str] = ..., casdoor_user_id: _Optional[str] = ..., from_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., to_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ServerPlaytime(_message.Message):
    __slots__ = ("server_id", "seconds", "sessions")
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    SECONDS_FIELD_NUMBER: _ClassVar[int]
    SESSIONS_FIELD_NUMBER: _ClassVar[int]
    server_id: str
    seconds: int
    sessions: int
    def __init__(self, server_id: _Optional[str] = ..., seconds: _Optional[int] = ..., sessions: _Optional[int] = ...) -> None: ...

class GetPlayerPlaytimeResponse(_message.Message):
    __slots__ = ("found", "player_uuid", "username", "total_seconds", "sessions", "servers", "last_seen_at")
    FOUND_FIELD_NUMBER: _ClassVar[int]
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    SESSIONS_FIELD_NUMBER: _ClassVar[int]
    SERVERS_FIELD_NUMBER: _ClassVar[int]
    LAST_SEEN_AT_FIELD_NUMBER: _ClassVar[int]
    found: bool
    player_uuid: str
    username: str
    total_seconds: int
    sessions: int
    servers: _containers.RepeatedCompositeFieldContainer[ServerPlaytime]
    last_seen_at: _timestamp_pb2.Timestamp
    def __init__(self, found: _Optional[bool] = ..., player_uuid: _Optional[str] = ..., username: _Optional[str] = ..., total_seconds: _Optional[int] = ..., sessions: _Optional[int] = ..., servers: _Optional[_Iterable[_Union[ServerPlaytime, _Mapping]]] = ..., last_seen_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class GetProxyStatsRequest(_message.Message):
    __slots__ = ("server_id", "from_time", "to_time")
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    FROM_TIME_FIELD_NUMBER: _ClassVar[int]
    TO_TIME_FIELD_NUMBER: _ClassVar[int]
    server_id: str
    from_time: _timestamp_pb2.Timestamp
    to_time: _timestamp_pb2.Timestamp
    def __init__(self, server_id: _Optional[str] = ..., from_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., to_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ServerStats(_message.Message):
    __slots__ = ("server_id", "unique_players", "sessions", "seconds", "peak_online")
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    UNIQUE_PLAYERS_FIELD_NUMBER: _ClassVar[int]
    SESSIONS_FIELD_NUMBER: _ClassVar[int]
    SECONDS_FIELD_NUMBER: _ClassVar[int]
    PEAK_ONLINE_FIELD_NUMBER: _ClassVar[int]
    server_id: str
    unique_players: int
    sessions: int
    seconds: int
    peak_online: int
    def __init__(self, server_id: _Optional[str] = ..., unique_players: _Optional[int] = ..., sessions: _Optional[int] = ..., seconds: _Optional[int] = ..., peak_online: _Optional[int] = ...) -> None: ...

class DenyStats(_message.Message):
    __slots__ = ("reason", "count")
    REASON_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    reason: str
    count: int
    def __init__(self, reason: _Optional[str] = ..., count: _Optional[int] = ...) -> None: ...

class GetProxyStatsResponse(_message.Message):
    __slots__ = ("unique_players", "sessions", "total_seconds", "login_failures", "servers", "denies")
    UNIQUE_PLAYERS_FIELD_NUMBER: _ClassVar[int]
    SESSIONS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    LOGIN_FAILURES_FIELD_NUMBER: _ClassVar[int]
    SERVERS_FIELD_NUMBER: _ClassVar[int]
    DENIES_FIELD_NUMBER: _ClassVar[int]
    unique_players: int
    sessions: int
    total_seconds: int
    login_failures: int
    servers: _containers.RepeatedCompositeFieldContainer[ServerStats]
    denies: _containers.RepeatedCompositeFieldContainer[DenyStats]
    def __init__(self, unique_players: _Optional[int] = ..., sessions: _Optional[int] = ..., total_seconds: _Optional[int] = ..., login_failures: _Optional[int] = ..., servers: _Optional[_Iterable[_Union[ServerStats, _Mapping]]] = ..., denies: _Optional[_Iterable[_Union[DenyStats, _Mapping]]] = ...) -> None: ...

class ResolvePlayerRequest(_message.Message):
    __slots__ = ("player_uuid", "username", "casdoor_user_id")
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    CASDOOR_USER_ID_FIELD_NUMBER: _ClassVar[int]
    player_uuid: str
    username: str
    casdoor_user_id: str
    def __init__(self, player_uuid: _Optional[str] = ..., username: _Optional[str] = ..., casdoor_user_id: _Optional[str] = ...) -> None: ...

class ResolvePlayerResponse(_message.Message):
    __slots__ = ("found", "player_uuid", "username", "casdoor_user_id", "source", "linked_at")
    FOUND_FIELD_NUMBER: _ClassVar[int]
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    CASDOOR_USER_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    LINKED_AT_FIELD_NUMBER: _ClassVar[int]
    found: bool
    player_uuid: str
    username: str
    casdoor_user_id: str
    source: str
    linked_at: _timestamp_pb2.Timestamp
    def __init__(self, found: _Optional[bool] = ..., player_uuid: _Optional[str] = ..., username: _Optional[str] = ..., casdoor_user_id: _Optional[str] = ..., source: _Optional[str] = ..., linked_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class BindPlayerIdentityRequest(_message.Message):
    __slots__ = ("request_id", "player_uuid", "username", "casdoor_user_id", "source", "actor", "overwrite")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    CASDOOR_USER_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    ACTOR_FIELD_NUMBER: _ClassVar[int]
    OVERWRITE_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    player_uuid: str
    username: str
    casdoor_user_id: str
    source: IdentitySource
    actor: str
    overwrite: bool
    def __init__(self, request_id: _Optional[str] = ..., player_uuid: _Optional[str] = ..., username: _Optional[str] = ..., casdoor_user_id: _Optional[str] = ..., source: _Optional[_Union[IdentitySource, str]] = ..., actor: _Optional[str] = ..., overwrite: _Optional[bool] = ...) -> None: ...

class BindPlayerIdentityResponse(_message.Message):
    __slots__ = ("success", "created", "player_uuid", "casdoor_user_id")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    CREATED_FIELD_NUMBER: _ClassVar[int]
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    CASDOOR_USER_ID_FIELD_NUMBER: _ClassVar[int]
    success: bool
    created: bool
    player_uuid: str
    casdoor_user_id: str
    def __init__(self, success: _Optional[bool] = ..., created: _Optional[bool] = ..., player_uuid: _Optional[str] = ..., casdoor_user_id: _Optional[str] = ...) -> None: ...

class AccessRule(_message.Message):
    __slots__ = ("id", "subject_type", "subject", "effect", "scope", "expires_at", "reason", "actor", "created_at")
    ID_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_TYPE_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_FIELD_NUMBER: _ClassVar[int]
    EFFECT_FIELD_NUMBER: _ClassVar[int]
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    ACTOR_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    id: int
    subject_type: SubjectType
    subject: str
    effect: RuleEffect
    scope: str
    expires_at: _timestamp_pb2.Timestamp
    reason: str
    actor: str
    created_at: _timestamp_pb2.Timestamp
    def __init__(self, id: _Optional[int] = ..., subject_type: _Optional[_Union[SubjectType, str]] = ..., subject: _Optional[str] = ..., effect: _Optional[_Union[RuleEffect, str]] = ..., scope: _Optional[str] = ..., expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., reason: _Optional[str] = ..., actor: _Optional[str] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class SetAccessRuleRequest(_message.Message):
    __slots__ = ("request_id", "subject_type", "subject", "effect", "scope", "expires_at", "reason", "actor")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_TYPE_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_FIELD_NUMBER: _ClassVar[int]
    EFFECT_FIELD_NUMBER: _ClassVar[int]
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    ACTOR_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    subject_type: SubjectType
    subject: str
    effect: RuleEffect
    scope: str
    expires_at: _timestamp_pb2.Timestamp
    reason: str
    actor: str
    def __init__(self, request_id: _Optional[str] = ..., subject_type: _Optional[_Union[SubjectType, str]] = ..., subject: _Optional[str] = ..., effect: _Optional[_Union[RuleEffect, str]] = ..., scope: _Optional[str] = ..., expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., reason: _Optional[str] = ..., actor: _Optional[str] = ...) -> None: ...

class SetAccessRuleResponse(_message.Message):
    __slots__ = ("rule",)
    RULE_FIELD_NUMBER: _ClassVar[int]
    rule: AccessRule
    def __init__(self, rule: _Optional[_Union[AccessRule, _Mapping]] = ...) -> None: ...

class ListAccessRulesRequest(_message.Message):
    __slots__ = ("subject_type", "subject", "scope", "include_expired")
    SUBJECT_TYPE_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_FIELD_NUMBER: _ClassVar[int]
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_EXPIRED_FIELD_NUMBER: _ClassVar[int]
    subject_type: SubjectType
    subject: str
    scope: str
    include_expired: bool
    def __init__(self, subject_type: _Optional[_Union[SubjectType, str]] = ..., subject: _Optional[str] = ..., scope: _Optional[str] = ..., include_expired: _Optional[bool] = ...) -> None: ...

class ListAccessRulesResponse(_message.Message):
    __slots__ = ("rules",)
    RULES_FIELD_NUMBER: _ClassVar[int]
    rules: _containers.RepeatedCompositeFieldContainer[AccessRule]
    def __init__(self, rules: _Optional[_Iterable[_Union[AccessRule, _Mapping]]] = ...) -> None: ...

class DeleteAccessRuleRequest(_message.Message):
    __slots__ = ("request_id", "id")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    id: int
    def __init__(self, request_id: _Optional[str] = ..., id: _Optional[int] = ...) -> None: ...

class DeleteAccessRuleResponse(_message.Message):
    __slots__ = ("success",)
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    def __init__(self, success: _Optional[bool] = ...) -> None: ...

class AccessPolicy(_message.Message):
    __slots__ = ("scope", "mode", "updated_at")
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    scope: str
    mode: AccessMode
    updated_at: _timestamp_pb2.Timestamp
    def __init__(self, scope: _Optional[str] = ..., mode: _Optional[_Union[AccessMode, str]] = ..., updated_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class SetAccessPolicyRequest(_message.Message):
    __slots__ = ("request_id", "scope", "mode", "actor")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    ACTOR_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    scope: str
    mode: AccessMode
    actor: str
    def __init__(self, request_id: _Optional[str] = ..., scope: _Optional[str] = ..., mode: _Optional[_Union[AccessMode, str]] = ..., actor: _Optional[str] = ...) -> None: ...

class SetAccessPolicyResponse(_message.Message):
    __slots__ = ("policy",)
    POLICY_FIELD_NUMBER: _ClassVar[int]
    policy: AccessPolicy
    def __init__(self, policy: _Optional[_Union[AccessPolicy, _Mapping]] = ...) -> None: ...

class ListAccessPoliciesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListAccessPoliciesResponse(_message.Message):
    __slots__ = ("policies",)
    POLICIES_FIELD_NUMBER: _ClassVar[int]
    policies: _containers.RepeatedCompositeFieldContainer[AccessPolicy]
    def __init__(self, policies: _Optional[_Iterable[_Union[AccessPolicy, _Mapping]]] = ...) -> None: ...

class BeginDeviceLoginRequest(_message.Message):
    __slots__ = ("player_uuid", "username", "proxy_id")
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    PROXY_ID_FIELD_NUMBER: _ClassVar[int]
    player_uuid: str
    username: str
    proxy_id: str
    def __init__(self, player_uuid: _Optional[str] = ..., username: _Optional[str] = ..., proxy_id: _Optional[str] = ...) -> None: ...

class BeginDeviceLoginResponse(_message.Message):
    __slots__ = ("login_id", "user_code", "verification_uri", "expires_in", "interval")
    LOGIN_ID_FIELD_NUMBER: _ClassVar[int]
    USER_CODE_FIELD_NUMBER: _ClassVar[int]
    VERIFICATION_URI_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_IN_FIELD_NUMBER: _ClassVar[int]
    INTERVAL_FIELD_NUMBER: _ClassVar[int]
    login_id: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int
    def __init__(self, login_id: _Optional[str] = ..., user_code: _Optional[str] = ..., verification_uri: _Optional[str] = ..., expires_in: _Optional[int] = ..., interval: _Optional[int] = ...) -> None: ...

class GetDeviceLoginStatusRequest(_message.Message):
    __slots__ = ("login_id",)
    LOGIN_ID_FIELD_NUMBER: _ClassVar[int]
    login_id: str
    def __init__(self, login_id: _Optional[str] = ...) -> None: ...

class GetDeviceLoginStatusResponse(_message.Message):
    __slots__ = ("status", "player_uuid", "casdoor_user_id", "message")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    PLAYER_UUID_FIELD_NUMBER: _ClassVar[int]
    CASDOOR_USER_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    status: DeviceLoginStatus
    player_uuid: str
    casdoor_user_id: str
    message: str
    def __init__(self, status: _Optional[_Union[DeviceLoginStatus, str]] = ..., player_uuid: _Optional[str] = ..., casdoor_user_id: _Optional[str] = ..., message: _Optional[str] = ...) -> None: ...
