"""Home Assistant custom integration for configuration backups."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Iterable
import zipfile

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_PATHS,
    CONF_BACKUP_DIR,
    CONF_MAX_BACKUPS,
    CONF_SOURCES,
    DEFAULT_BACKUP_DIR,
    DEFAULT_SOURCES,
    DOMAIN,
    SERVICE_BACKUP_NOW,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the HA Backupper component."""
    hass.data.setdefault(DOMAIN, {})

    domain_config = config.get(DOMAIN, {}) if config else {}

    backup_dir = Path(hass.config.path(domain_config.get(CONF_BACKUP_DIR, DEFAULT_BACKUP_DIR)))
    sources = domain_config.get(CONF_SOURCES, DEFAULT_SOURCES)
    max_backups = domain_config.get(CONF_MAX_BACKUPS)

    backupper = Backupper(hass, backup_dir, sources, max_backups)
    hass.data[DOMAIN]["backupper"] = backupper

    async def handle_backup_service(call: ServiceCall) -> None:
        override_paths = call.data.get(ATTR_PATHS)
        archive_path = await backupper.async_backup(override_paths)
        if archive_path:
            hass.bus.async_fire(
                f"{DOMAIN}_backup_completed",
                {"path": str(archive_path)},
            )

    async def _handle_shutdown(event) -> None:
        await backupper.async_close()

    hass.services.async_register(DOMAIN, SERVICE_BACKUP_NOW, handle_backup_service)
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _handle_shutdown)

    return True


class Backupper:
    """Handle creating zip backups of configuration files."""

    def __init__(
        self,
        hass: HomeAssistant,
        backup_dir: Path,
        default_sources: Iterable[str],
        max_backups: int | None,
    ) -> None:
        self._hass = hass
        self._backup_dir = backup_dir
        self._default_sources = tuple(str(source) for source in default_sources)

        max_backups_value = 0
        if max_backups is not None:
            try:
                max_backups_value = max(0, int(max_backups))
            except (TypeError, ValueError):
                _LOGGER.warning("Invalid max_backups value %s; ignoring", max_backups)
        self._max_backups = max_backups_value

    async def async_backup(self, override_paths: Iterable[str] | None = None) -> Path | None:
        """Create a backup archive."""
        sources = list(override_paths) if override_paths else list(self._default_sources)
        if not sources:
            _LOGGER.warning("No sources provided for backup")
            return None

        return await self._hass.async_add_executor_job(self._run_backup, sources)

    def _run_backup(self, sources: list[str]) -> Path | None:
        """Create the backup archive in the executor."""
        config_dir = Path(self._hass.config.path())
        resolved_sources: list[Path] = []

        for source in sources:
            source_path = config_dir / source
            if not source_path.exists():
                _LOGGER.debug("Skipping missing backup source: %s", source_path)
                continue
            resolved_sources.append(source_path)

        if not resolved_sources:
            _LOGGER.warning("No valid sources found for backup")
            return None

        self._backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = self._backup_dir / f"ha_backup_{timestamp}.zip"

        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source_path in resolved_sources:
                self._add_to_archive(archive, source_path, config_dir)

        _LOGGER.info("Created HA backup at %s", archive_path)

        if self._max_backups:
            self._enforce_retention()

        return archive_path

    def _add_to_archive(self, archive: zipfile.ZipFile, source_path: Path, base_path: Path) -> None:
        """Add a file or directory to the archive."""
        if source_path.is_dir():
            for file_path in sorted(source_path.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(base_path))
        else:
            archive.write(source_path, source_path.relative_to(base_path))

    def _enforce_retention(self) -> None:
        """Remove old backups if the limit is exceeded."""
        backups = sorted(self._backup_dir.glob("ha_backup_*.zip"))
        excess = len(backups) - self._max_backups
        for old_backup in backups[:max(0, excess)]:
            try:
                old_backup.unlink()
                _LOGGER.debug("Removed old backup %s", old_backup)
            except OSError as err:
                _LOGGER.warning("Failed to remove old backup %s: %s", old_backup, err)

    async def async_close(self) -> None:
        """Placeholder for cleanup when Home Assistant stops."""
        # No persistent resources at the moment.
        return
