"""Code to handle a Xiaomi Gateway."""
import logging

from construct.core import ChecksumError
from micloud import MiCloud
from miio import DeviceException, gateway
from miio.gateway.gateway import GATEWAY_MODEL_EU

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_AVAILABLE,
    CONF_CLOUD_COUNTRY,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_SUBDEVICES,
    CONF_CLOUD_USERNAME,
    DOMAIN,
    AuthException,
    SetupException,
)

_LOGGER = logging.getLogger(__name__)


class ConnectXiaomiGateway:
    """Class to async connect to a Xiaomi Gateway."""

    def __init__(self, hass, config_entry):
        """Initialize the entity."""
        self._hass = hass
        self._config_entry = config_entry
        self._gateway_device = None
        self._gateway_info = None
        self._use_cloud = None
        self._cloud_username = None
        self._cloud_password = None
        self._cloud_country = None
        self._host = None
        self._token = None

    @property
    def gateway_device(self):
        """Return the class containing all connections to the gateway."""
        return self._gateway_device

    @property
    def gateway_info(self):
        """Return the class containing gateway info."""
        return self._gateway_info

    async def async_connect_gateway(self, host, token):
        """Connect to the Xiaomi Gateway."""
        _LOGGER.debug("Initializing with host %s (token %s...)", host, token[:5])

        self._host = host
        self._token = token
        self._use_cloud = self._config_entry.options.get(CONF_CLOUD_SUBDEVICES, False)
        self._cloud_username = self._config_entry.data.get(CONF_CLOUD_USERNAME)
        self._cloud_password = self._config_entry.data.get(CONF_CLOUD_PASSWORD)
        self._cloud_country = self._config_entry.data.get(CONF_CLOUD_COUNTRY)

        await self._hass.async_add_executor_job(self.connect_gateway)

        _LOGGER.debug(
            "%s %s %s detected",
            self._gateway_info.model,
            self._gateway_info.firmware_version,
            self._gateway_info.hardware_version,
        )

    def connect_gateway(self):
        """Connect the gateway in a way that can called by async_add_executor_job."""

        try:
            self._gateway_device = gateway.Gateway(self._host, self._token)
            self._gateway_info = self._gateway_device.info()
        except DeviceException as error:
            if isinstance(error.__cause__, ChecksumError):
                raise AuthException(error) from error

            raise SetupException(
                f"DeviceException during setup of xiaomi gateway with host {self._host}"
            ) from error

        # Get the connected sub devices.
        devices = self._get_connected_devices()

        # Set the device information.
        self._gateway_device.set_devices(devices)

    def get_devices_from_cloud(
        self, cloud_username: str, cloud_password: str, cloud_country: str
    ) -> list:
        """Get the devices from the Miio Cloud."""
        miio_cloud = MiCloud(cloud_username, cloud_password)
        devices_raw = miio_cloud.get_devices(cloud_country)
        return devices_raw

    def _get_connected_devices(self):
        """Get the connected sub devices."""

        use_cloud = self._use_cloud or self._gateway_info.model == GATEWAY_MODEL_EU
        if not use_cloud:
            try:
                self._gateway_device.discover_devices()
            except DeviceException as error:
                _LOGGER.info(
                    (
                        "DeviceException during getting subdevices of xiaomi gateway"
                        " with host %s, trying cloud to obtain subdevices: %s"
                    ),
                    self._host,
                    error,
                )
                use_cloud = True

        if use_cloud:
            if (
                self._cloud_username is None
                or self._cloud_password is None
                or self._cloud_country is None
            ):
                raise AuthException(
                    "Missing cloud credentials in Xiaomi Miio configuration"
                )

            devices_raw = self.get_devices_from_cloud(
                self._cloud_username, self._cloud_password, self._cloud_country
            )
            devices = [XiaomiGatewayDevice.from_dict(device) for device in devices_raw]
        else:
            devices = self._gateway_device.devices

        return devices


class XiaomiGatewayDevice(CoordinatorEntity, Entity):
    """Representation of a base Xiaomi Gateway Device."""

    def __init__(self, coordinator, sub_device, entry):
        """Initialize the Xiaomi Gateway Device."""
        super().__init__(coordinator)
        self._sub_device = sub_device
        self._entry = entry
        self._unique_id = sub_device.sid
        self._name = f"{sub_device.name} ({sub_device.sid})"

    @property
    def unique_id(self):
        """Return an unique ID."""
        return self._unique_id

    @property
    def name(self):
        """Return the name of this entity, if any."""
        return self._name

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info of the gateway."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._sub_device.sid)},
            via_device=(DOMAIN, self._entry.unique_id),
            manufacturer="Xiaomi",
            name=self._sub_device.name,
            model=self._sub_device.model,
            sw_version=self._sub_device.firmware_version,
            hw_version=self._sub_device.zigbee_model,
        )

    @property
    def available(self):
        """Return if entity is available."""
        if self.coordinator.data is None:
            return False

        return self.coordinator.data[ATTR_AVAILABLE]
