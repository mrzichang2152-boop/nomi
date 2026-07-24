from __future__ import annotations

from typing import Protocol

from app.web_search.schema import ProviderSearchResult, SearchRequest


class WebSearchProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True, error_type: str = "provider_error") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.error_type = error_type


class WebSearchProvider(Protocol):
    name: str

    def search(self, request: SearchRequest) -> ProviderSearchResult: ...
