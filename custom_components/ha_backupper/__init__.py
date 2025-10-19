"""Home Assistant custom integration for configuration backups."""

from __future__ import annotations

import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_BACKUP_NAME,
    ATTR_DESTINATION,
    ATTR_OVERWRITE,
    ATTR_PATHS,
    ATTR_SOURCE,
    ATTR_TARGETS,
    CONF_BACKUP_DIR,
    CONF_MAX_BACKUPS,
    CONF_SOURCES,
    DEFAULT_BACKUP_DIR,
    DEFAULT_SOURCES,
    DOMAIN,
    SERVICE_BACKUP_NOW,
    SERVICE_DOWNLOAD_BACKUP,
    SERVICE_RESTORE_BACKUP,
    SERVICE_UPLOAD_BACKUP,
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

    async def handle_download_service(call: ServiceCall) -> None:
        backup_name_value = call.data.get(ATTR_BACKUP_NAME)
        destination_value = call.data.get(ATTR_DESTINATION)
        overwrite = bool(call.data.get(ATTR_OVERWRITE, False))

        if not backup_name_value or not destination_value:
            raise HomeAssistantError("backup_name and destination must be provided")

        backup_name = str(backup_name_value)
        destination = str(destination_value)

        try:
            dest_path = await backupper.async_download_backup(
                backup_name,
                destination,
                overwrite,
            )
        except FileExistsError as err:
            raise HomeAssistantError(str(err)) from err
        except FileNotFoundError as err:
            raise HomeAssistantError(str(err)) from err
        hass.bus.async_fire(
            f"{DOMAIN}_backup_downloaded",
            {"path": str(dest_path)},
        )

    async def handle_upload_service(call: ServiceCall) -> None:
        source_value = call.data.get(ATTR_SOURCE)
        backup_name_value = call.data.get(ATTR_BACKUP_NAME)
        overwrite = bool(call.data.get(ATTR_OVERWRITE, False))

        if not source_value:
            raise HomeAssistantError("source must be provided")

        source = str(source_value)
        backup_name = str(backup_name_value) if backup_name_value is not None else None

        try:
            uploaded_path = await backupper.async_upload_backup(
                source,
                backup_name,
                overwrite,
            )
        except FileExistsError as err:
            raise HomeAssistantError(str(err)) from err
        except FileNotFoundError as err:
            raise HomeAssistantError(str(err)) from err
        hass.bus.async_fire(
            f"{DOMAIN}_backup_uploaded",
            {"path": str(uploaded_path)},
        )

    async def handle_restore_service(call: ServiceCall) -> None:
        backup_name_value = call.data.get(ATTR_BACKUP_NAME)
        targets_value = call.data.get(ATTR_TARGETS)
        overwrite = bool(call.data.get(ATTR_OVERWRITE, False))

        if not backup_name_value:
            raise HomeAssistantError("backup_name must be provided")

        backup_name = str(backup_name_value)
        targets = None
        if targets_value is not None:
            if isinstance(targets_value, (list, tuple, set)):
                targets = [str(target) for target in targets_value]
            else:
                targets = [str(targets_value)]

        try:
            restored = await backupper.async_restore_backup(
                backup_name,
                targets,
                overwrite,
            )
        except FileExistsError as err:
            raise HomeAssistantError(str(err)) from err
        except (FileNotFoundError, HomeAssistantError, ValueError) as err:
            raise HomeAssistantError(str(err)) from err

        hass.bus.async_fire(
            f"{DOMAIN}_backup_restored",
            {"restored": [str(path) for path in restored]},
        )

    async def _handle_shutdown(event) -> None:
        await backupper.async_close()

    hass.services.async_register(DOMAIN, SERVICE_BACKUP_NOW, handle_backup_service)
    hass.services.async_register(
        DOMAIN, SERVICE_DOWNLOAD_BACKUP, handle_download_service
    )
    hass.services.async_register(DOMAIN, SERVICE_UPLOAD_BACKUP, handle_upload_service)
    hass.services.async_register(DOMAIN, SERVICE_RESTORE_BACKUP, handle_restore_service)
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

    async def async_backup(
        self, override_paths: Iterable[str] | None = None
    ) -> Path | None:
        """Create a backup archive."""
        sources = list(override_paths) if override_paths else list(self._default_sources)
        if not sources:
            _LOGGER.warning("No sources provided for backup")
            return None

        return await self._hass.async_add_executor_job(self._run_backup, sources)

    async def async_download_backup(
        self, backup_name: str, destination: str, overwrite: bool
    ) -> Path:
        """Copy a backup archive to a destination path."""
        return await self._hass.async_add_executor_job(
            self._download_backup,
            backup_name,
            destination,
            overwrite,
        )

    async def async_upload_backup(
        self, source: str, backup_name: str | None, overwrite: bool
    ) -> Path:
        """Copy an external archive into the backup directory."""
        return await self._hass.async_add_executor_job(
            self._upload_backup,
            source,
            backup_name,
            overwrite,
        )

    async def async_restore_backup(
        self, backup_name: str, targets: Iterable[str] | None, overwrite: bool
    ) -> list[Path]:
        """Restore files from a backup archive."""
        return await self._hass.async_add_executor_job(
            self._restore_backup,
            backup_name,
            targets,
            overwrite,
        )

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

    def _download_backup(self, backup_name: str, destination: str, overwrite: bool) -> Path:
        """Copy a backup to a destination on the local filesystem."""
        backup_file = self._resolve_backup_file(backup_name)
        destination_str = str(destination)
        destination_path = self._resolve_filesystem_path(destination_str)

        if destination_path.is_dir() or destination_str.endswith("/"):
            destination_file = destination_path / backup_file.name
        else:
            destination_file = destination_path

        destination_file.parent.mkdir(parents=True, exist_ok=True)

        if destination_file.exists() and not overwrite:
            raise FileExistsError(f"Destination {destination_file} already exists")

        shutil.copy2(backup_file, destination_file)
        _LOGGER.info("Copied backup %s to %s", backup_file, destination_file)
        return destination_file

    def _upload_backup(
        self, source: str, backup_name: str | None, overwrite: bool
    ) -> Path:
        """Copy an external archive into the backup directory."""
        source_path = self._resolve_filesystem_path(source)
        if not source_path.exists():
            raise FileNotFoundError(f"Source {source_path} does not exist")

        dest_name = backup_name or source_path.name
        dest_name_path = Path(dest_name)
        if dest_name_path.is_absolute():
            raise HomeAssistantError("backup_name must not be an absolute path")
        if any(part == ".." for part in dest_name_path.parts):
            raise HomeAssistantError("backup_name must not traverse directories")

        destination_file = self._backup_dir / dest_name_path.name
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        if destination_file.exists() and not overwrite:
            raise FileExistsError(f"Backup {destination_file.name} already exists")

        shutil.copy2(source_path, destination_file)
        _LOGGER.info("Uploaded backup %s to %s", source_path, destination_file)
        return destination_file

    def _restore_backup(
        self, backup_name: str, targets: Iterable[str] | None, overwrite: bool
    ) -> list[Path]:
        """Restore files from a backup archive into the config directory."""
        backup_file = self._resolve_backup_file(backup_name)
        config_dir = Path(self._hass.config.path())
        config_root = config_dir.resolve()

        normalized_targets: list[str] = []
        if targets:
            for target in targets:
                target_path = Path(target)
                if target_path.is_absolute():
                    raise HomeAssistantError("targets must be relative paths")
                normalized = target_path.as_posix().lstrip("./")
                if normalized:
                    normalized_targets.append(normalized)

        restored_paths: list[Path] = []

        with zipfile.ZipFile(backup_file, mode="r") as archive:
            for member in archive.infolist():
                name = member.filename
                if not name or name.endswith("/"):
                    continue

                normalized_name = name.lstrip("./")
                if normalized_targets and not any(
                    normalized_name == target
                    or normalized_name.startswith(f"{target}/")
                    for target in normalized_targets
                ):
                    continue

                target_path = (config_dir / normalized_name).resolve()
                if not str(target_path).startswith(str(config_root)):
                    raise HomeAssistantError(
                        f"Unsafe path {normalized_name} in backup {backup_file.name}"
                    )

                if target_path.exists() and not overwrite:
                    raise FileExistsError(
                        f"Destination {target_path} already exists; enable overwrite"
                    )

                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, mode="r") as source_file, target_path.open(
                    "wb"
                ) as target_file:
                    shutil.copyfileobj(source_file, target_file)

                restored_paths.append(target_path)

        _LOGGER.info("Restored %d items from %s", len(restored_paths), backup_file)
        return restored_paths

    def _resolve_backup_file(self, backup_name: str) -> Path:
        """Return the path to a backup file stored in the backup directory."""
        backup_dir = self._backup_dir
        candidate = Path(backup_name)

        if candidate.is_absolute():
            if candidate.parent != backup_dir:
                raise HomeAssistantError("Backups must reside within the configured directory")
            backup_file = candidate
        else:
            backup_file = backup_dir / candidate

        if not backup_file.exists() and backup_file.suffix != ".zip":
            alt = backup_file.with_suffix(".zip")
            if alt.exists():
                backup_file = alt

        if not backup_file.exists():
            raise FileNotFoundError(f"Backup {backup_file.name} does not exist")

        if backup_file.resolve().parent != backup_dir.resolve():
            raise HomeAssistantError("Backups must reside within the configured directory")

        return backup_file

    def _resolve_filesystem_path(self, path_value: str) -> Path:
        """Resolve a filesystem path relative to the Home Assistant config directory."""
        path = Path(path_value)
        if not path.is_absolute():
            path = Path(self._hass.config.path(path_value))
        return path

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
