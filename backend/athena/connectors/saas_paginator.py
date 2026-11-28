"""A dlt paginator for APIs that page with a "has more" flag plus a cursor (imported only when fetching: it needs dlt).

Copied verbatim into exported scripts, so it must stay self-contained.
"""
from __future__ import annotations

from dlt.sources.helpers.rest_client.paginators import BasePaginator


class _AthenaHasMorePaginator(BasePaginator):
    """Pages while a flag in the response says there is more, sending either a cursor taken from the response
    (Zendesk: meta.after_cursor -> page[after]) or the id of the last record (Stripe: starting_after)."""

    def __init__(self, has_more_path, cursor_param, cursor_path=None, last_item_key=None):
        super().__init__()
        self.has_more_path, self.cursor_param = has_more_path, cursor_param
        self.cursor_path, self.last_item_key = cursor_path, last_item_key
        self._cursor = None

    @staticmethod
    def _get(obj, path):
        for part in path.split("."):
            obj = obj.get(part) if isinstance(obj, dict) else None
        return obj

    def update_state(self, response, data=None):
        body = response.json()
        if self.cursor_path:
            cursor = self._get(body, self.cursor_path)
        else:
            cursor = data[-1].get(self.last_item_key) if data else None
        self._cursor = cursor
        self._has_next_page = bool(self._get(body, self.has_more_path)) and cursor is not None

    def update_request(self, request):
        request.params = dict(request.params or {})
        request.params[self.cursor_param] = self._cursor
