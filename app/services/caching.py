"""Cache-aside with explicit invalidation.

A TTL alone is the easy half. It bounds how stale an entry can get, but it also
guarantees every entry *is* stale for up to that long -- so a host creates a game
and cannot find it in search for two minutes. Shortening the TTL to fix that
throws away the hit rate the cache existed for.

So entries expire on time *and* are deleted on write. Each one is registered
against one or more tags; a write invalidates a tag and every entry carrying it
goes. The TTL then only has to bound entries whose tag nobody touches again.

Tags are Redis sets, given a slightly longer TTL than their members so they
cannot outlive them and accumulate dead keys.
"""

import hashlib
import json

from app.extensions import cache

# Bumping this retires every existing entry at once, which is what a change to
# a cached value's *shape* needs: stale entries would otherwise deserialize into
# something the code no longer understands.
CACHE_VERSION = "v1"

TAG_PREFIX = f"{CACHE_VERSION}:tag"
TAG_TTL_MARGIN = 60  # seconds a tag set outlives the entries it tracks

MAX_INLINE_KEY_LENGTH = 120


class CacheStats:
    """Hit/miss counters. Process-local, and only ever used for reporting."""

    def __init__(self):
        self.hits = 0
        self.misses = 0

    @property
    def total(self):
        return self.hits + self.misses

    @property
    def hit_rate(self):
        return self.hits / self.total if self.total else 0.0

    def reset(self):
        self.hits = self.misses = 0

    def as_dict(self):
        return {"hits": self.hits, "misses": self.misses, "hit_rate": round(self.hit_rate, 3)}


stats = CacheStats()


def _redis():
    """The raw client, for the set operations Flask-Caching does not expose."""
    backend = getattr(cache, "cache", None)
    return getattr(backend, "_write_client", None) or getattr(backend, "_client", None)


def _key_prefix():
    """Flask-Caching namespaces the keys it writes; raw client calls must too."""
    return getattr(getattr(cache, "cache", None), "key_prefix", "") or ""


def enabled():
    """False when the configured backend is a null cache."""
    return _redis() is not None


def make_key(namespace, **parts):
    """Build a stable cache key.

    Sorted so argument order cannot produce two keys for one question, and
    hashed past a length that would make the key unwieldy.
    """
    encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    if len(encoded) > MAX_INLINE_KEY_LENGTH:
        encoded = hashlib.sha256(encoded.encode()).hexdigest()[:32]
    return f"{CACHE_VERSION}:{namespace}:{encoded}"


def get_or_set(key, producer, ttl, tags=()):
    """Return the cached value, or produce, store and tag it."""
    if not enabled():
        return producer()

    cached = cache.get(key)
    if cached is not None:
        stats.hits += 1
        return cached

    stats.misses += 1
    value = producer()
    cache.set(key, value, timeout=ttl)
    _tag(key, tags, ttl)
    return value


def _tag(key, tags, ttl):
    client = _redis()
    if not client or not tags:
        return
    pipe = client.pipeline()
    for tag in tags:
        tag_key = f"{TAG_PREFIX}:{tag}"
        pipe.sadd(tag_key, key)
        pipe.expire(tag_key, ttl + TAG_TTL_MARGIN)
    pipe.execute()


def invalidate(*tags):
    """Drop every cached entry carrying any of these tags.

    Returns the number of entries actually removed. One round trip per tag
    rather than one per entry: a busy grid cell can carry hundreds of keys.
    """
    client = _redis()
    if not client or not tags:
        return 0

    prefix = _key_prefix()
    removed = 0
    for tag in tags:
        tag_key = f"{TAG_PREFIX}:{tag}"
        members = [_as_text(member) for member in client.smembers(tag_key)]
        if not members:
            client.delete(tag_key)
            continue

        pipe = client.pipeline()
        for member in members:
            pipe.delete(prefix + member)
        pipe.delete(tag_key)
        # The last reply is the tag set's own deletion.
        removed += sum(1 for reply in pipe.execute()[:-1] if reply)
    return removed


def _as_text(value):
    return value.decode() if isinstance(value, bytes) else value


def clear_all():
    """Drop everything. Used by the tests and the seed command."""
    if enabled():
        cache.clear()
    stats.reset()
