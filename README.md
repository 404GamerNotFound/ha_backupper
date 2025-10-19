# HA Backupper

A Home Assistant Custom Component that provides an on-demand backup service for key configuration files. Trigger the `ha_backupper.backup_now` service to create a timestamped zip archive containing your configuration, automation, and script definitions.

## Installation

1. Copy the `custom_components/ha_backupper` folder to your Home Assistant `custom_components` directory (or install through HACS once published).
2. Restart Home Assistant.

## Configuration

Add an entry to your `configuration.yaml` file (optional):

```yaml
ha_backupper:
  backup_directory: backups
  sources:
    - configuration.yaml
    - automations.yaml
    - scripts.yaml
    - blueprints
  max_backups: 10
```

* `backup_directory` – Relative path within the Home Assistant configuration directory where backups are stored. Defaults to `backups`.
* `sources` – List of files or directories (relative to the configuration directory) to include when creating backups. Defaults to core configuration files and folders.
* `max_backups` – Optional number of most recent backups to retain. Older archives beyond this limit are removed.

## Usage

Call the `ha_backupper.backup_now` service from the Developer Tools or automations. Optionally override the paths for a single backup by passing a `paths` list in the service data.

Each backup is created as a zip archive named `ha_backup_YYYYMMDD_HHMMSS.zip` and stored in the configured backup directory.
