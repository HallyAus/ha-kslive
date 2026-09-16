"""Base entity for KSLive."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import KSLiveCoordinator


class KSLiveEntity(CoordinatorEntity[KSLiveCoordinator]):
    """Base class shared by KSLive entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KSLiveCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=NAME,
            manufacturer="KSLive",
            model="Subscriber audio",
            configuration_url="https://kslive.com.au",
        )

