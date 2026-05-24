from __future__ import annotations

from carapace.cache import SessionListCache
from carapace.models.config import CacheConfig


def test_session_list_cache_key_distinguishes_user_all_from_global_scope() -> None:
    cache = SessionListCache(CacheConfig())

    global_key = cache._cache_key(False, False)
    user_all_key = cache._cache_key(False, False, user="all")

    assert global_key == "carapace:sessions:list:scope:all:0:0"
    assert user_all_key == "carapace:sessions:list:user:all:0:0"
    assert user_all_key != global_key
