"""Cache-aside with explicit invalidation.

A TTL alone is the easy half. It bounds how stale an entry can get, but it also
guarantees every entry *is* stale for up to that long -- so a host creates a game
and cannot find it in search for two minutes. Shortening the TTL to fix that
throws away the hit rate the cache existed for.

The answer is to expire on time *and* delete on write. Each cached entry is
registered against one or more tags; a write invalidates a tag, and every entry
carrying it goes. The TTL then only has to bound entries whose tag nobody
happens to touch again.

Tags live in Redis sets. The set is given a slightly longer TTL than its members
so it cannot outlive them by much and accumulate dead keys.
"""

import functools
import hashlib
import json
import time

from flask import current_app

from app.extensions import cache

# Bumping this retires every existing entry at once, which is what you want when
# a cached value's *shape* changes and stale entries would deserialize wrongly.
CACHE_VERSION = "v1"

TAG_PREFIX = f"{CACHE_VERSION}:tag"
TAG_TTL_MARGIN = 60  # seconds a tag set outlives the entries it tracks


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
    client = getattr(backend, "_write_client", None) or getattr(backend, "_client", None)
    return client


def enabled():
    """False when the configured backend is a null cache."""
    return _redis() is not None


def make_key(namespace, **parts):
    """Build a stable cache key.

    Sorted so that argument order cannot produce two keys for one question, and
    hashed past a certain length so a key stays a sane size.
    """
    encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    if len(encoded) > 120:
        encoded = hashlib.sha256(encoded.encode()).hexdigest()[:32]
    return f"{CACHE_VERSION}:{namespace}:{encoded}"


def get_or_set(key, producer, ttl, tags=()):
    """Cache-aside: return the cached value, or produce, store and tag it."""
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
        # The tag set must outlive its members, or invalidation misses entries
        # that are still live.
        pipe.expire(tag_key, ttl + TAG_TTL_MARGIN)
    pipe.execute()


def invalidate(*tags):
    """Drop every cached entry carrying any of these tags.

    Returns the number of entries removed, which is what the tests assert on.
    """
    client = _redis()
    if not client or not tags:
        return 0

    removed = 0
    for tag in tags:
        tag_key = f"{TAG_PREFIX}:{tag}"
        members = client.smembers(tag_key)
        if members:
            # Flask-Caching prefixes keys; delete through it so the prefix is
            # applied consistently rather than reimplemented here.
            for member in members:
                name = member.decode() if isinstance(member, bytes) else member
                if cache.delete(name):
                    removed += 1
        client.delete(tag_key)
    return removed


def clear_all():
    """Drop everything. Used by tests and by the seed command."""
    if enabled():
        cache.clear()
    stats.reset()


def timed(label):
    """Log how long a cache-backed view took, and whether it hit.

    Cheap enough to leave on: one perf_counter pair per request.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            before = stats.hits
            started = time.perf_counter()
            result = fn(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - started) * 1000
            current_app.logger.debug(
                "%s %s in %.1fms", label, "HIT" if stats.hits > before else "MISS", elapsed_ms
            )
            return result

        return wrapped

    return decorator
