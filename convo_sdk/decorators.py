"""
convo_sdk.decorators
~~~~~~~~~~~~~~~~~~~~

Developer-friendly decorators for defining tools and domain agents with zero boilerplate.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, List, Optional, Type
from convo_registry.contracts import ToolDefinition, ToolInputSchema


def _python_type_to_json_type(py_type: Type) -> str:
    if py_type in (int,):
        return "integer"
    elif py_type in (float,):
        return "number"
    elif py_type in (bool,):
        return "boolean"
    elif py_type in (list, List):
        return "array"
    elif py_type in (dict,):
        return "object"
    return "string"


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    version: str = "1.0.0",
    requires_approval: bool = False,
    timeout_seconds: float = 30.0,
    tags: Optional[List[str]] = None,
) -> Callable:
    """
    Decorator converting a standard Python async or sync function into a Convo Tool Contract.
    Inspects type signatures to automatically generate JSON Schema parameters.
    """
    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        tool_desc = description or (fn.__doc__.strip() if fn.__doc__ else f"Tool {tool_name}")

        sig = inspect.signature(fn)
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            param_type = param.annotation if param.annotation != inspect.Parameter.empty else str
            json_type = _python_type_to_json_type(param_type)

            properties[param_name] = {
                "type": json_type,
                "description": f"Parameter {param_name}",
            }
            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        input_schema = ToolInputSchema(properties=properties, required=required)

        tool_def = ToolDefinition(
            name=tool_name,
            description=tool_desc,
            version=version,
            input_schema=input_schema,
            requires_approval=requires_approval,
            timeout_seconds=timeout_seconds,
            tags=tags or [],
        )

        fn.__tool_definition__ = tool_def  # type: ignore

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            if inspect.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            return fn(*args, **kwargs)

        wrapper.__tool_definition__ = tool_def  # type: ignore
        return wrapper

    return decorator


def agent(
    name: str,
    description: str = "",
    version: str = "1.0.0",
) -> Callable:
    """
    Decorator tagging a class or agent factory with Convo Agent metadata.
    """
    def decorator(cls_or_fn: Any) -> Any:
        cls_or_fn.__convo_agent__ = {
            "name": name,
            "description": description,
            "version": version,
        }
        return cls_or_fn

    return decorator
