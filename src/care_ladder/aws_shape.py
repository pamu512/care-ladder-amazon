"""Check boto3 payloads against the pinned botocore service model.

No network. Used so SageMaker and AgentCore requests fail in CI when a
field name does not exist on the installed SDK.
"""

from __future__ import annotations

from typing import Any


class AwsShapeError(RuntimeError):
    """Pinned boto3 cannot express this request."""


_SCALAR = frozenset(
    {"string", "integer", "long", "float", "double", "boolean", "timestamp", "blob"}
)
# ponytail: _fill recurses along the object it builds and stops at this depth.
# Member-name lookup is iterative. Upgrade path: build the payload with an
# explicit stack too.
_MAX_DEPTH = 32


def _visit_key(shape: Any) -> str:
    name = getattr(shape, "name", None)
    if isinstance(name, str) and name:
        return "n:" + name
    model = getattr(shape, "_shape_model", None)
    return "m:" + str(id(model) if model is not None else id(shape))


def _resolve_ref(shape: Any, ref: Any) -> Any:
    resolve = getattr(shape, "_resolve_shape_ref", None)
    if resolve is None or not isinstance(ref, dict) or "shape" not in ref:
        raise AwsShapeError(f"unresolved shape ref: {ref!r}")
    return resolve(ref)


def _structure_members(shape: Any) -> list[tuple[str, Any]]:
    """Member shapes from the raw model. Avoids Shape.members on cyclic models."""
    model = getattr(shape, "_shape_model", None) or {}
    members = model.get("members") or {}
    return [(name, _resolve_ref(shape, ref)) for name, ref in members.items()]


def _list_item(shape: Any) -> Any:
    model = getattr(shape, "_shape_model", None) or {}
    return _resolve_ref(shape, model.get("member"))


def _map_value(shape: Any) -> Any:
    model = getattr(shape, "_shape_model", None) or {}
    return _resolve_ref(shape, model.get("value"))


def service_model(name: str) -> Any:
    import botocore.session
    from botocore.exceptions import UnknownServiceError

    try:
        return botocore.session.get_session().get_service_model(name)
    except UnknownServiceError as exc:
        raise AwsShapeError(str(exc)) from exc


def input_shape(service: str, operation: str) -> Any:
    model = service_model(service)
    if operation not in model.operation_names:
        similar = [
            n
            for n in model.operation_names
            if operation[:8].lower() in n.lower() or "Gateway" in n or "Endpoint" in n
        ]
        raise AwsShapeError(
            f"{service}.{operation} is not in this boto3. Similar: {similar[:25]}"
        )
    return model.operation_model(operation).input_shape


def shape_summary(
    shape: Any,
    depth: int = 3,
    indent: int = 0,
    seen: frozenset[str] | None = None,
) -> str:
    pad = "  " * indent
    if depth < 0:
        return pad + "..."
    seen = seen or frozenset()
    name = getattr(shape, "name", "") or ""
    if name and name in seen:
        return pad + f"(cycle {name})"
    if name:
        seen = seen | {name}
    kind = shape.type_name
    if kind == "structure":
        lines = [pad + "structure"]
        required = set(getattr(shape, "required_members", []) or [])
        for member_name, member in _structure_members(shape):
            flag = " required" if member_name in required else ""
            enum = getattr(member, "enum", None)
            extra = f" enum={enum}" if enum else ""
            lines.append(f"{pad}  {member_name}: {member.type_name}{flag}{extra}")
            if member.type_name == "structure" and depth > 1:
                lines.append(shape_summary(member, depth - 1, indent + 2, seen))
            elif member.type_name == "list" and depth > 1:
                lines.append(shape_summary(_list_item(member), depth - 1, indent + 2, seen))
        return "\n".join(lines)
    if kind == "list":
        return pad + "list\n" + shape_summary(_list_item(shape), depth - 1, indent + 1, seen)
    enum = getattr(shape, "enum", None)
    return pad + kind + (f" enum={enum}" if enum else "")


def _enum_values(shape: Any) -> list[str]:
    enum = getattr(shape, "enum", None)
    return list(enum) if enum else []


def coerce_enum(shape: Any, value: Any, name: str) -> Any:
    enum = _enum_values(shape)
    if not enum or not isinstance(value, str):
        return value
    if value in enum:
        return value
    for item in enum:
        if item.lower() == value.lower():
            return item
    raise AwsShapeError(f"{name}={value!r} is not in {enum}")


def strings_as_list_member(member: Any, values: list[str]) -> list[Any]:
    """Copy string ids into a list member.

    ponytail: objects are filled only when they have one string id field.
    Two required strings need an explicit dict.
    """
    if member.type_name != "list":
        raise AwsShapeError(f"expected a list, got {member.type_name}")
    if not isinstance(values, list) or any(not isinstance(item, str) or not item for item in values):
        raise AwsShapeError("list member values must be non-empty strings")
    item = _list_item(member)
    if item.type_name in _SCALAR:
        enum = _enum_values(item)
        if enum and any(value not in enum for value in values):
            raise AwsShapeError(f"{values!r} is not in {enum}")
        return list(values)
    if item.type_name != "structure":
        raise AwsShapeError(f"list items are {item.type_name}")
    fields = _structure_members(item)
    required = set(getattr(item, "required_members", []) or [])
    strings = [name for name, shape in fields if shape.type_name == "string"]
    required_strings = [name for name in strings if name in required]
    other_required = [name for name in required if name not in set(required_strings)]
    if other_required or (len(required_strings) != 1 and len(strings) != 1):
        seen = ", ".join(name for name, _shape in fields) or "(none)"
        raise AwsShapeError(f"list items have no single string id field: {seen}")
    field = required_strings[0] if len(required_strings) == 1 else strings[0]
    field_shape = dict(fields)[field]
    return [{field: coerce_enum(field_shape, value, field)} for value in values]


def validate_payload(service: str, operation: str, payload: Any) -> None:
    shape = input_shape(service, operation)
    errors = _walk(shape, payload, operation)
    if errors:
        raise AwsShapeError(
            "\n".join(errors) + "\n" + shape_summary(shape)
        )


def _walk(shape: Any, payload: Any, path: str) -> list[str]:
    kind = shape.type_name
    if kind == "structure":
        if not isinstance(payload, dict):
            return [f"{path} expected an object"]
        errors: list[str] = []
        required = set(getattr(shape, "required_members", []) or [])
        for name in required:
            if name not in payload:
                errors.append(f"{path}.{name} is required")
        members = dict(_structure_members(shape))
        for key, val in payload.items():
            if key not in members:
                errors.append(f"{path}.{key} is not in the SDK shape")
                continue
            errors.extend(_walk(members[key], val, f"{path}.{key}"))
        return errors
    if kind == "list":
        if not isinstance(payload, list):
            return [f"{path} expected a list"]
        errors = []
        item_shape = _list_item(shape)
        for i, item in enumerate(payload):
            errors.extend(_walk(item_shape, item, f"{path}[{i}]"))
        return errors
    if kind == "map":
        if not isinstance(payload, dict):
            return [f"{path} expected a map"]
        errors = []
        value_shape = _map_value(shape)
        for key, val in payload.items():
            errors.extend(_walk(value_shape, val, f"{path}.{key}"))
        return errors
    enum = _enum_values(shape)
    if enum and isinstance(payload, str) and payload not in enum:
        return [f"{path}={payload!r} is not in {enum}"]
    return []


def fill_shape(
    shape: Any,
    values: dict[str, Any],
    *,
    optional: set[str] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Place `values` into `shape`. Keys that do not fit stay in the leftover dict.

    Optional keys that miss an enum are left unused instead of raising.
    """
    optional = optional or set()
    return _fill(shape, dict(values), optional, (), {})


def _member_names(
    shape: Any,
    cache: dict[str, frozenset[str]],
    _stack: tuple[str, ...] = (),
    _depth: int = 0,
) -> frozenset[str]:
    """Names nested under this shape. Each shape name is visited once."""
    key = _visit_key(shape)
    cached = cache.get(key)
    if cached is not None:
        return cached
    found: set[str] = set()
    seen: set[str] = set()
    pending: list[Any] = [shape]
    while pending:
        current = pending.pop()
        current_key = _visit_key(current)
        if current_key in seen:
            continue
        seen.add(current_key)
        kind = current.type_name
        if kind == "structure":
            for member_name, member in _structure_members(current):
                found.add(member_name)
                if member.type_name in {"structure", "list", "map"}:
                    pending.append(member)
        elif kind == "list":
            item = _list_item(current)
            if item.type_name not in _SCALAR:
                pending.append(item)
        elif kind == "map":
            value = _map_value(current)
            if value.type_name not in _SCALAR:
                pending.append(value)
    result = frozenset(found)
    cache[key] = result
    return result


def _fill(
    shape: Any,
    values: dict[str, Any],
    optional: set[str],
    stack: tuple[str, ...],
    cache: dict[str, frozenset[str]],
    depth: int = 0,
) -> tuple[Any, dict[str, Any]]:
    if depth > _MAX_DEPTH:
        return None, values
    key = _visit_key(shape)
    if key in stack:
        return None, values
    nxt = stack + (key,)
    kind = shape.type_name
    if kind == "structure":
        unused = dict(values)
        out: dict[str, Any] = {}
        members = _structure_members(shape)
        for name, member in members:
            if name not in unused:
                continue
            if member.type_name in _SCALAR:
                try:
                    out[name] = coerce_enum(member, unused[name], name)
                except AwsShapeError:
                    if name in optional:
                        continue
                    raise
                unused.pop(name)
            elif (
                member.type_name == "list"
                and _list_item(member).type_name in _SCALAR
                and isinstance(unused[name], list)
            ):
                item_shape = _list_item(member)
                enum = _enum_values(item_shape)
                if enum and any(isinstance(item, str) and item not in enum for item in unused[name]):
                    if name in optional:
                        continue
                    raise AwsShapeError(f"{name}={unused[name]!r} is not in {enum}")
                out[name] = list(unused.pop(name))
        progress = True
        while progress and unused:
            progress = False
            best: tuple[int, str, Any, dict[str, Any]] | None = None
            pending = set(unused)
            for name, member in members:
                if name in out or member.type_name not in {"structure", "list"}:
                    continue
                if member.type_name == "list" and _list_item(member).type_name in _SCALAR:
                    continue
                if not (pending & _member_names(member, cache, ())):
                    continue
                frag, rest = _fill(member, unused, optional, nxt, cache, depth + 1)
                if frag is None:
                    continue
                consumed = len(unused) - len(rest)
                if consumed > 0 and (best is None or consumed > best[0]):
                    best = (consumed, name, frag, rest)
            if best is not None:
                _, name, frag, rest = best
                out[name] = frag
                unused = rest
                progress = True
        if not out:
            return None, values
        return out, unused
    if kind == "list" and _list_item(shape).type_name not in _SCALAR:
        frag, rest = _fill(_list_item(shape), values, optional, nxt, cache, depth + 1)
        if frag is None:
            return None, values
        return [frag], rest
    return None, values


def build_operation(
    service: str,
    operation: str,
    required: dict[str, Any],
    optional: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fill an operation input. Unknown optional keys are dropped."""
    optional = optional or {}
    shape = input_shape(service, operation)
    payload, leftover = fill_shape(shape, {**required, **optional}, optional=set(optional))
    if not isinstance(payload, dict):
        raise AwsShapeError(f"{service}.{operation} fill produced no object")
    missing_required_keys = [k for k in required if k in leftover]
    if missing_required_keys:
        raise AwsShapeError(
            f"{service}.{operation} could not place {missing_required_keys}\n"
            + shape_summary(shape)
        )
    if leftover:
        payload, leftover = fill_shape(
            shape,
            {k: v for k, v in {**required, **optional}.items() if k not in leftover or k in required},
            optional=set(optional),
        )
        if not isinstance(payload, dict):
            raise AwsShapeError(f"{service}.{operation} fill produced no object")
        still = [k for k in required if k in leftover]
        if still:
            raise AwsShapeError(
                f"{service}.{operation} could not place {still}\n" + shape_summary(shape)
            )
    validate_payload(service, operation, payload)
    return payload
