"""
ZeroWall — Safe Transform Engine (Base + Registry)
====================================================
All code mutation goes through this safe, deterministic pipeline.

SAFETY DESIGN:
- AI/model ONLY selects the transform TYPE and high-level params
- Actual code changes are applied by deterministic AST/CST transformers
- No free-form AI code generation is allowed
- All transforms are behavior-preserving by construction
"""

import libcst as cst
from pathlib import Path
from typing import Dict, Type, Any
from core.models import TransformType


class BaseTransformer:
    """Base class for all ZeroWall safe code transformers."""

    name: TransformType = None

    def apply(self, source_code: str, params: Dict[str, Any]) -> str:
        """
        Apply transform to source code.
        Returns mutated source code string.
        Must be deterministic: same inputs → same output.
        """
        raise NotImplementedError

    def describe(self, params: Dict[str, Any]) -> str:
        """Returns human-readable description of this transform application."""
        raise NotImplementedError


# Registry of all available safe transforms
_TRANSFORM_REGISTRY: Dict[TransformType, Type[BaseTransformer]] = {}


def register_transform(cls: Type[BaseTransformer]) -> Type[BaseTransformer]:
    """Decorator to register a transformer."""
    _TRANSFORM_REGISTRY[cls.name] = cls
    return cls


def get_transformer(transform_type: TransformType) -> BaseTransformer:
    """Retrieve a registered transformer by type."""
    if transform_type not in _TRANSFORM_REGISTRY:
        raise ValueError(f"Unknown transform type: {transform_type}")
    return _TRANSFORM_REGISTRY[transform_type]()


def list_transforms() -> list:
    """List all registered transform types."""
    return list(_TRANSFORM_REGISTRY.keys())


def apply_transform(source_code: str, transform_type: TransformType, params: Dict[str, Any]) -> tuple[str, str]:
    """
    Apply a named transform to source code.
    Returns (mutated_code, description).
    """
    transformer = get_transformer(transform_type)
    mutated = transformer.apply(source_code, params)
    description = transformer.describe(params)
    return mutated, description
