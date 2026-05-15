from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from gold_analyzer._compat import ensure_legacy_src_path


ConnectFactory = Callable[[str | None], Iterator[Any]]


def default_connect(dsn: str | None = None) -> Iterator[Any]:
    ensure_legacy_src_path()
    from db import connect

    return connect(dsn)


class Repository:
    def __init__(self, *, dsn: str | None = None, connect_factory: ConnectFactory | None = None) -> None:
        self.dsn = dsn
        self._connect_factory = connect_factory or default_connect

    @contextmanager
    def connect(self) -> Iterator[Any]:
        with self._connect_factory(self.dsn) as conn:
            yield conn
