import os
import sys
import subprocess
import uuid
from dataclasses import dataclass, fields, asdict
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import dialog
import yaml


APP_NAME = 'bbs-dialer'

DEFAULT_CONFIG_FILE = Path.home() / '.config' / APP_NAME / 'config.yaml'

DEFAULT_BBS_ENTRY_DIR_PATH = Path.home() / '.config' / APP_NAME / 'bbs_sources'
DEFAULT_LOCAL_BBS_ENTRY_DIR_PATH = DEFAULT_BBS_ENTRY_DIR_PATH / 'local'
DEFAULT_BBS_CACHE_FILE = Path.home() / '.cache' / APP_NAME / 'bbs_db.yaml'

DEFAULT_BBS_NAME = "Default BBS"
DEFAULT_BBS_URL = "telnet://default.example.com"
DEFAULT_BBS_DESC = "Default Entry"
DEFAULT_BBS_SOURCE_PATH_TEMPLATE = '{id}.yaml'


@dataclass
class BBSEntry:
    id: str
    name: str
    url: str
    description: str
    source_path: Path

    @classmethod
    def new(cls, dir_path: Path) -> 'BBSEntry':
        id = str(uuid.uuid4())
        
        return BBSEntry(
            id,
            DEFAULT_BBS_NAME,
            DEFAULT_BBS_URL,
            DEFAULT_BBS_DESC,
            dir_path / DEFAULT_BBS_SOURCE_PATH_TEMPLATE.format(id=id),
        )

    @classmethod
    def deserialize(cls, raw_pairs: Dict[str, str]) -> 'BBSEntry':
        cleaned_pairs = {}
        for k, v in raw_pairs.items():
            if k == 'source_path':
                v = Path(v)
            elif k == 'id':
                v = uuid.UUID(v)
            cleaned_pairs[k] = v

        return BBSEntry(**cleaned_pairs)

    def serialize(self) -> Dict[str, str]:
        return { k : str(v) for k, v in asdict(self).items() }


@dataclass
class AppConfig:
    source_dirs: List[Path]
    cache_file: Path
    local_entry_dir: Path

    @classmethod
    def new(cls) -> 'AppConfig':
        return cls(
            source_dirs = [ DEFAULT_BBS_ENTRY_DIR_PATH ],
            cache_file = DEFAULT_BBS_CACHE_FILE,
            local_entry_dir = DEFAULT_LOCAL_BBS_ENTRY_DIR_PATH,
        )

def load_app_config(config_file: Path) -> AppConfig:
    try:
        with open(config_file, 'r') as file:
            config_data = yaml.safe_load(file)
            return AppConfig(**config_data)
    except FileNotFoundError:
        return AppConfig.new()

def save_app_config(config: AppConfig, config_file: Path):
    with open(config_file, 'w') as file:
        yaml.dump(asdict(config), file)

def load_bbs_entries_from_files(paths: List[Path]) -> List[BBSEntry]:
    entries = []
    for path in paths:
        for file_path in path.rglob('*.yaml'):
            if file_path.is_file():
                with open(file_path, 'r') as file:
                    new_entry = BBSEntry.deserialize(yaml.safe_load(file))
                    entries.append(new_entry)
    return entries

def save_bbs_entry(entry: BBSEntry, app_config: AppConfig):
    entry.source_path.parent.mkdir(parents=True, exist_ok=True)
    with open(entry.source_path, 'w') as file:
        yaml.dump(entry.serialize(), file)

def save_all_bbs_entries(entries: List[BBSEntry], app_config: AppConfig):
    for entry in entries:
        save_bbs_entry(entry, app_config)

def save_bbs_entries_to_cache(entries: List[BBSEntry], cache_file: Path):
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, 'w') as file:
        yaml.dump([entry.serialize() for entry in entries], file)

def load_bbs_entries_from_cache(cache_file: Path) -> List[BBSEntry]:
    try:
        with open(cache_file, 'r') as file:
            return [BBSEntry.deserialize(entry) for entry in yaml.safe_load(file) or []]
    except FileNotFoundError:
        return []

def refresh_bbs_cache(config: AppConfig, existing_bbs_entries: Optional[List[BBSEntry]] = None) -> List[BBSEntry]:
    if config.cache_file.is_file():
        cache_mtime = config.cache_file.stat().st_mtime
        latest_dir_mtime = max((dir_path.stat().st_mtime for dir_path in config.source_dirs if dir_path.is_dir()), default=0)
        if latest_dir_mtime <= cache_mtime:
            if existing_bbs_entries:
                return existing_bbs_entries
            else:
                return load_bbs_entries_from_cache(config.cache_file)

    bbs_entries = load_bbs_entries_from_files(config.source_dirs)

    save_bbs_entries_to_cache(bbs_entries, config.cache_file)

    return bbs_entries

def launch_bbs(entry: BBSEntry):
    url_parts = urlparse(entry.url)

    if url_parts.scheme == 'telnet':
        port = str(url_parts.port) if url_parts.port else '23'
        args = [
            'telnet',
            url_parts.hostname,
            port,
        ]
        res = subprocess.run(args)
        if res.returncode != 0:
            print(f"ERROR running {args!r}", file=sys.stderr)
    elif url_parts.scheme == 'ssh':
        port = str(url_parts.port) if url_parts.port else '22'
        args = [
            'ssh',
            url_parts.hostname,
            port,
        ]
        res = subprocess.run(args)
        if res.returncode != 0:
            print(f"ERROR running {args!r}", file=sys.stderr)
    elif url_parts.scheme == 'https':
        subprocess.run(['xdg-open', entry.url])
    else:
        d = dialog.error(f"Unsupported URL scheme: {url_parts.scheme}")
        d.complete_message()


def add_bbs_entry(app_config: AppConfig) -> BBSEntry:
    new_entry = BBSEntry.new(app_config.local_entry_dir)
    save_bbs_entry(new_entry, app_config)
    return new_entry

def edit_bbs_entry(entry: BBSEntry, app_config: AppConfig):
    d = dialog.Dialog(dialog="dialog")
    field_choices = [(field.name, str(getattr(entry, field.name))) for field in fields(BBSEntry) if field.name != 'id']
    while True:
        code, tag = d.menu("Edit BBS Entry:", choices=field_choices, cancel_label="Back")
        if code == d.OK:
            field_to_edit = next((field for field in fields(BBSEntry) if field.name == tag), None)
            if field_to_edit:
                field_value = getattr(entry, field_to_edit.name)
                new_code, new_value = d.inputbox(f"Edit {field_to_edit.name}", init=str(field_value))
                if new_code == d.OK and new_value != field_value:
                    fieldtype = type(field_value)
                    setattr(entry, field_to_edit.name, fieldtype(new_value))
                    field_choices = [(field.name, str(getattr(entry, field.name))) for field in fields(BBSEntry)]
        else:
            break

    save_bbs_entry(entry, app_config)


def delete_bbs_entry(entry: BBSEntry, bbs_entries: List[BBSEntry], app_config: AppConfig):
    entry.source_path.unlink()

    if len(bbs_entries) == 0:
        bbs_entries.append(BBSEntry.new(app_config.local_entry_dir))

def generate_choices_from_entries(bbs_entries: List[BBSEntry]) -> List[tuple]:
    return [(entry.name, entry.description) for entry in bbs_entries]

def manage_bbs(app_config: AppConfig, selected_entry: Optional[BBSEntry], bbs_entries: List[BBSEntry]) -> List[BBSEntry]:
    d = dialog.Dialog(dialog="dialog")

    if not bbs_entries:
        bbs_entries.append(BBSEntry.new(app_config.local_entry_dir))

    choices = [("Add", "Add a new entry")]
    if selected_entry:
        choices.extend([
            ("Launch", f"Connect to {selected_entry.name}"),
            ("Edit", f"Edit {selected_entry.name}"),
        ])

    if selected_entry.source_path and selected_entry.source_path.exists():
        choices.extend([
            ("Delete", f"Delete {selected_entry.name}"),
        ])

    choices.append(("Refresh Cache", "Reload BBS entries from sources"))
    code, tag = d.menu("Manage BBS Entries:", choices=choices, cancel_label="Back")
    if code == d.OK:
        if tag == "Launch":
            launch_bbs(selected_entry)
        elif tag == "Add":
            new_entry = add_bbs_entry(app_config)
            bbs_entries.append(new_entry)
        elif tag == "Edit":
            edit_bbs_entry(selected_entry, app_config)
            save_bbs_entries_to_cache(bbs_entries, app_config.cache_file)
        elif tag == "Delete":
            delete_bbs_entry(selected_entry, bbs_entries, app_config)
            save_bbs_entries_to_cache(bbs_entries, app_config.cache_file)
            selected_entry = None
        elif tag == "Refresh Cache":
            new_bbs_entries = refresh_bbs_cache(app_config)
            if new_bbs_entries:
                bbs_entries = new_bbs_entries

    return bbs_entries


def demo_bbs_entries(app_config) -> List[BBSEntry]:
    return [ BBSEntry.new(app_config.local_entry_dir) ]


def main():
    d = dialog.Dialog(dialog="dialog")
    d.set_background_title("BBS Dialer")

    app_config = load_app_config(DEFAULT_CONFIG_FILE)

    bbs_entries = refresh_bbs_cache(app_config)
    if not bbs_entries:
        bbs_entries = demo_bbs_entries(app_config)
        save_bbs_entries_to_cache(bbs_entries, app_config.cache_file)

    second_pass = False
    while True:
        choices = generate_choices_from_entries(bbs_entries)  # Update choices here

        code, tag = d.menu("Choose an action:", choices=choices, ok_label="Select", cancel_label="Exit")

        if code == d.OK:
            selected_entry = next((entry for entry in bbs_entries if entry.name == tag), None)
            new_bbs_entries = manage_bbs(app_config, selected_entry, bbs_entries)

        elif code == d.CANCEL:
            break

    print("\033[39m")

    return 0
