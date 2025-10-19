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

### Managing backups

The integration keeps every archive in the configured backup directory so they are immediately available on the Home Assistant host. Additional helper services are provided to move, import, and restore backups when needed:

* `ha_backupper.download_backup` – Copy a backup from the integration's backup directory to another location on the local filesystem (for example a mounted USB drive or shared folder). Provide the backup name (the `.zip` extension is optional) and the destination path. Set `overwrite: true` to replace an existing file at the destination.
* `ha_backupper.upload_backup` – Import an existing archive into the backup directory. Supply the source path, optionally override the stored filename with `backup_name`, and set `overwrite: true` to replace an existing archive with the same name.
* `ha_backupper.restore_backup` – Restore files from a stored archive back into the Home Assistant configuration directory. Use the optional `targets` list to limit restoration to specific files or directories. Enable `overwrite` to replace existing files.

> ⚠️ Restoring a backup will overwrite configuration files when `overwrite` is enabled. Consider taking an additional backup before performing a restore.
