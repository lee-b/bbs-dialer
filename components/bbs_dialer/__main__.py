import os
import subprocess
import yaml
from dataclasses import dataclass, fields, asdict
from pathlib import Path
from typing import Optional, List
from urllib.parse import urlparse
import dialog

APP_NAME = 'bbs-dialer'
DEFAULT_CONFIG_FILE = Path.home() / '.config' / APP_NAME / 'config.yaml'
DEFAULT_BBS_ENTRY_DIR_PATH = Path.home() / '.config' / APP_NAME / 'bbs_sources'
DEFAULT_BBS_CACHE_FILE = Path.home() / '.cache' / APP_NAME / 'bbs_db.yaml'

@dataclass
class BBSEntry:
    name: str
    url: str
    description: str

@dataclass
class AppConfig:
    source_dirs: List[Path]
    cache_file: Path

def load_app_config(config_file: Path) -> AppConfig:
    try:
        with open(config_file, 'r') as file:
            config_data = yaml.safe_load(file)
            return AppConfig(**config_data)
    except FileNotFoundError:
        return AppConfig(
            source_dirs=[DEFAULT_BBS_ENTRY_DIR_PATH],
            cache_file=DEFAULT_BBS_CACHE_FILE
        )

def save_app_config(config: AppConfig, config_file: Path):
    with open(config_file, 'w') as file:
        yaml.dump(asdict(config), file)

def load_bbs_entries_from_files(paths: List[Path]) -> List[BBSEntry]:
    entries = []
    for path in paths:
        for file_path in path.rglob('*.yaml'):
            if file_path.is_file():
                with open(file_path, 'r') as file:
                    entries.extend([BBSEntry(**entry) for entry in yaml.safe_load(file) or []])
    return entries

def save_bbs_entries_to_cache(entries: List[BBSEntry], cache_file: Path):
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, 'w') as file:
        yaml.dump([asdict(entry) for entry in entries], file)

def load_bbs_entries_from_cache(cache_file: Path) -> List[BBSEntry]:
    try:
        with open(cache_file, 'r') as file:
            return [BBSEntry(**entry) for entry in yaml.safe_load(file) or []]
    except FileNotFoundError:
        return []

def refresh_bbs_cache(config: AppConfig):
    if config.cache_file.is_file():
        cache_mtime = config.cache_file.stat().st_mtime
        latest_dir_mtime = max((dir_path.stat().st_mtime for dir_path in config.source_dirs if dir_path.is_dir()), default=0)
        if latest_dir_mtime <= cache_mtime:
            return

    bbs_entries = load_bbs_entries_from_files(config.source_dirs)
    save_bbs_entries_to_cache(bbs_entries, config.cache_file)
    return bbs_entries

def launch_bbs(entry: BBSEntry):
    url_parts = urlparse(entry.url)
    if url_parts.scheme == 'telnet':
        subprocess.run(['telnet', url_parts.netloc])
    elif url_parts.scheme == 'ssh':
        subprocess.run(['ssh', url_parts.netloc])
    elif url_parts.scheme == 'https':
        subprocess.run(['xdg-open', entry.url])
    else:
        print(f"Unsupported URL scheme: {url_parts.scheme}")

def add_bbs_entry():
    print("Adding a new BBS entry")
    return BBSEntry("(new entry)", "telnet://newbbs.example.com:23", "")

def edit_bbs_entry(entry: BBSEntry):
    d = dialog.Dialog(dialog="dialog")
    field_choices = [(field.name, getattr(entry, field.name)) for field in fields(BBSEntry)]
    while True:
        code, tag = d.menu("Edit BBS Entry:", choices=field_choices, cancel_label="Back")
        if code == d.OK:
            field_to_edit = next((field for field in fields(BBSEntry) if field.name == tag), None)
            if field_to_edit:
                field_value = getattr(entry, field_to_edit.name)
                new_code, new_value = d.inputbox(f"Edit {field_to_edit.name}", init=field_value)
                if new_code == d.OK and new_value != field_value:
                    setattr(entry, field_to_edit.name, new_value)
                    field_choices = [(field.name, getattr(entry, field.name)) for field in fields(BBSEntry)]
        else:
            break

def delete_bbs_entry(entry: BBSEntry, bbs_entries: List[BBSEntry]):
    print(f"Deleting BBS entry: {entry.name}")
    bbs_entries.remove(entry)
    if not bbs_entries:
        default_entry = BBSEntry("Default BBS", "telnet://default.example.com", "Default Entry")
        bbs_entries.append(default_entry)

def manage_bbs(app_config: AppConfig, selected_entry: Optional[BBSEntry], bbs_entries: List[BBSEntry]):
    d = dialog.Dialog(dialog="dialog")
    while True:
        if not bbs_entries:
            default_entry = BBSEntry("Default BBS", "telnet://default.example.com", "Default Entry")
            bbs_entries.append(default_entry)
        choices = [("Add", "Add a new entry")]
        if selected_entry:
            choices.extend([
                ("Launch", f"Connect to {selected_entry.name}"),
                ("Edit", f"Edit {selected_entry.name}"), 
                ("Delete", f"Delete {selected_entry.name}")
            ])
        choices.append(("Refresh Cache", "Reload BBS entries from sources"))
        code, tag = d.menu("Manage BBS Entries:", choices=choices, cancel_label="Back")
        if code == d.OK:
            if tag == "Launch":
                launch_bbs(selected_entry)
            elif tag == "Add":
                new_entry = add_bbs_entry()
                bbs_entries.append(new_entry)
            elif tag == "Edit":
                edit_bbs_entry(selected_entry)
            elif tag == "Delete":
                delete_bbs_entry(selected_entry, bbs_entries)
                selected_entry = None
            elif tag == "Refresh Cache":
                bbs_entries.clear()
                bbs_entries += refresh_bbs_cache(app_config)
        else:
            break

def demo_bbs_entries() -> List[BBSEntry]:
    return [
        BBSEntry("BBS1", "telnet://bbs1.example.com", "Classic BBS on Telnet"),
        BBSEntry("BBS2", "ssh://bbs2.example.com", "Secure BBS on SSH"),
        BBSEntry("BBS3", "https://bbs3.example.com", "Web-based BBS on HTTPS"),
    ]

def main():
    d = dialog.Dialog(dialog="dialog")
    d.set_background_title("BBS Dialer")

    app_config = load_app_config(DEFAULT_CONFIG_FILE)

    bbs_entries = refresh_bbs_cache(app_config)
    if not bbs_entries:
        bbs_entries = demo_bbs_entries()
        save_bbs_entries_to_cache(bbs_entries, app_config.cache_file)

    while True:
        choices = [(entry.name, entry.description) for entry in bbs_entries]
        code, tag = d.menu("Choose an action:", choices=choices, ok_label="Select", cancel_label="Exit")
        if code == d.OK:
            selected_entry = next((entry for entry in bbs_entries if entry.name == tag), None)
            manage_bbs(app_config, selected_entry, bbs_entries)
        elif code == d.CANCEL:
            break
    return 0
