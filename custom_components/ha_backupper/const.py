"""Constants for the HA Backupper integration."""

from __future__ import annotations

DOMAIN = "ha_backupper"
DEFAULT_BACKUP_DIR = "backups"
DEFAULT_SOURCES = [
    "configuration.yaml",
    "automations.yaml",
    "scripts.yaml",
    "blueprints",
    "automations",
    "scripts",
]

CONF_BACKUP_DIR = "backup_directory"
CONF_SOURCES = "sources"
CONF_MAX_BACKUPS = "max_backups"

SERVICE_BACKUP_NOW = "backup_now"
ATTR_PATHS = "paths"
