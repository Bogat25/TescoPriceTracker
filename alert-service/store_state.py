"""Which stores are switched on, read from the shared store registry."""

import asyncio

from stores.registry import registry


async def enabled_store_ids() -> set[str]:
    """Enabled store IDs. The registry is cached and falls back to its defaults."""
    stores = await asyncio.to_thread(registry.enabled)
    return {store.id for store in stores}


async def store_names() -> dict[str, str]:
    stores = await asyncio.to_thread(registry.all)
    return {store.id: store.name for store in stores}
