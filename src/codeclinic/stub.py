from __future__ import annotations
import functools
import warnings
from typing import Callable, TypeVar, Any, cast

F = TypeVar("F", bound=Callable[..., Any])


def stub(func: F) -> F:
    """Mark a function/method as a *stub* and warn on call.

    - Sets attribute ``__codeclinic_stub__ = True`` for runtime tools.
    - Emits a ``UserWarning`` whenever the function is called.
    """
    setattr(func, "__codeclinic_stub__", True)

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        warnings.warn(
            f"codeclinic: calling stubbed function '{func.__module__}.{func.__name__}'",
            category=UserWarning,
            stacklevel=2,
        )
        return func(*args, **kwargs)

    # Preserve type for static checkers
    return cast(F, wrapper)
