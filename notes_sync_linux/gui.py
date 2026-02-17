from __future__ import annotations

import copy
import hashlib
import queue
import re
import subprocess
import threading
import urllib.parse
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import messagebox, ttk

from .core import (
    AppConfig,
    DownloadOptions,
    FolderDownloadProgress,
    NoteItem,
    NotesDownloader,
    StorageManager,
    SyncedFileItem,
    SyncCancelled,
    SyncEngine,
    iso_to_display,
    now_iso,
)


def human_size(num: Optional[int]) -> str:
    if num is None:
        return "-"
    value = float(num)
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.1f} {units[idx]}"


class NoteDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, title: str, initial_title: str = "", initial_url: str = "") -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self.result: Optional[tuple[str, str]] = None

        self.title_var = tk.StringVar(value=initial_title)
        self.url_var = tk.StringVar(value=initial_url)
        self.error_var = tk.StringVar(value="")

        body = ttk.Frame(self, padding=14)
        body.grid(row=0, column=0, sticky="nsew")

        ttk.Label(body, text="Title").grid(row=0, column=0, sticky="w")
        title_entry = ttk.Entry(body, textvariable=self.title_var, width=54)
        title_entry.grid(row=1, column=0, sticky="ew", pady=(2, 8))

        ttk.Label(body, text="Public link").grid(row=2, column=0, sticky="w")
        url_entry = ttk.Entry(body, textvariable=self.url_var, width=54)
        url_entry.grid(row=3, column=0, sticky="ew", pady=(2, 8))

        ttk.Label(body, textvariable=self.error_var, foreground="#b42318").grid(row=4, column=0, sticky="w")

        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self._on_cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Save", command=self._on_save).grid(row=0, column=1)

        self.bind("<Return>", lambda _e: self._on_save())
        self.bind("<Escape>", lambda _e: self._on_cancel())
        title_entry.focus_set()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()

    def _on_save(self) -> None:
        title = self.title_var.get().strip()
        url = self.url_var.get().strip()

        if not title:
            self.error_var.set("Title cannot be empty")
            return

        if not url:
            self.error_var.set("URL cannot be empty")
            return

        self.result = (title, url)
        self.destroy()


class NotesSyncLinuxApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("NotesSyncLinux")
        self.geometry("1420x920")
        self.minsize(1080, 680)

        self.storage = StorageManager()
        self.downloader = NotesDownloader()
        self.engine = SyncEngine(self.storage, self.downloader)

        self.config_data = self.storage.load_config()
        self.notes: list[NoteItem] = self.config_data.notes
        for note in self.notes:
            if not note.file_name:
                note.file_name = self.storage.make_file_name(note.title, note.id)

        self.selected_note_id: Optional[str] = None
        self.selected_source_tree_id: Optional[str] = None
        self.source_nodes: dict[str, dict] = {}
        self.expanded_folder_ids: set[str] = set()

        self.is_syncing = False
        self.is_stopping = False
        self.sync_cancel_event: Optional[threading.Event] = None
        self.sync_thread: Optional[threading.Thread] = None
        self.inflight_downloads: set[str] = set()
        self.last_auto_sync_at: datetime = datetime.min

        self.ui_queue: queue.Queue = queue.Queue()

        self.status_var = tk.StringVar(value="Ready")
        self.interval_var = tk.StringVar(value=str(self.config_data.check_interval_minutes))
        self.max_size_var = tk.StringVar(value=str(self.config_data.max_file_size_mb))
        self.skip_video_var = tk.BooleanVar(value=self.config_data.skip_video_files)
        self.skip_large_var = tk.BooleanVar(value=self.config_data.skip_large_files)

        self._build_ui()
        self._refresh_notes_table()
        self._refresh_source_tree()
        self._update_controls_state()

        self.after(120, self._process_ui_queue)
        self.after(20_000, self._auto_sync_tick)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        controls = ttk.Frame(root)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        controls.columnconfigure(12, weight=1)

        self.add_btn = ttk.Button(controls, text="Add", command=self._add_note)
        self.add_btn.grid(row=0, column=0, padx=(0, 6))

        self.edit_btn = ttk.Button(controls, text="Edit", command=self._edit_note)
        self.edit_btn.grid(row=0, column=1, padx=(0, 6))

        self.delete_btn = ttk.Button(controls, text="Delete", command=self._delete_note)
        self.delete_btn.grid(row=0, column=2, padx=(0, 12))

        self.update_selected_btn = ttk.Button(controls, text="Update selected", command=self._sync_selected)
        self.update_selected_btn.grid(row=0, column=3, padx=(0, 6))

        self.update_all_btn = ttk.Button(controls, text="Update all", command=self._sync_all)
        self.update_all_btn.grid(row=0, column=4, padx=(0, 6))

        self.stop_btn = ttk.Button(controls, text="Stop", command=self._stop_sync)
        self.stop_btn.grid(row=0, column=5, padx=(0, 6))

        self.open_btn = ttk.Button(controls, text="Open selected file", command=self._open_selected_file)
        self.open_btn.grid(row=0, column=6, padx=(0, 12))

        ttk.Checkbutton(controls, text="Skip videos", variable=self.skip_video_var, command=self._persist_config_safe).grid(
            row=0, column=7, padx=(0, 8)
        )
        ttk.Checkbutton(controls, text="Skip >", variable=self.skip_large_var, command=self._persist_config_safe).grid(
            row=0, column=8, padx=(0, 4)
        )

        self.max_size_entry = ttk.Entry(controls, textvariable=self.max_size_var, width=6)
        self.max_size_entry.grid(row=0, column=9)
        ttk.Label(controls, text="MB").grid(row=0, column=10, padx=(4, 4))
        ttk.Button(controls, text="Set", command=self._apply_max_size).grid(row=0, column=11, padx=(0, 12))

        ttk.Label(controls, text="Auto every").grid(row=0, column=13)
        self.interval_entry = ttk.Entry(controls, textvariable=self.interval_var, width=6)
        self.interval_entry.grid(row=0, column=14, padx=(6, 0))
        ttk.Label(controls, text="min").grid(row=0, column=15, padx=(4, 4))
        ttk.Button(controls, text="Apply", command=self._apply_interval).grid(row=0, column=16)

        notes_frame = ttk.Frame(root)
        notes_frame.grid(row=1, column=0, sticky="nsew")
        root.rowconfigure(1, weight=2)
        notes_frame.rowconfigure(0, weight=1)
        notes_frame.columnconfigure(0, weight=1)

        notes_columns = ("title", "status", "last_checked", "last_updated", "source_url")
        self.notes_tree = ttk.Treeview(notes_frame, columns=notes_columns, show="headings", selectmode="browse")
        self.notes_tree.heading("title", text="Title")
        self.notes_tree.heading("status", text="Status")
        self.notes_tree.heading("last_checked", text="Last checked")
        self.notes_tree.heading("last_updated", text="Last updated")
        self.notes_tree.heading("source_url", text="Source URL")

        self.notes_tree.column("title", width=220, anchor="w")
        self.notes_tree.column("status", width=320, anchor="w")
        self.notes_tree.column("last_checked", width=150, anchor="w")
        self.notes_tree.column("last_updated", width=150, anchor="w")
        self.notes_tree.column("source_url", width=520, anchor="w")

        notes_scroll = ttk.Scrollbar(notes_frame, orient="vertical", command=self.notes_tree.yview)
        self.notes_tree.configure(yscrollcommand=notes_scroll.set)
        self.notes_tree.grid(row=0, column=0, sticky="nsew")
        notes_scroll.grid(row=0, column=1, sticky="ns")

        self.notes_tree.bind("<<TreeviewSelect>>", self._on_note_selection)

        source_frame = ttk.Frame(root)
        source_frame.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        root.rowconfigure(2, weight=3)
        source_frame.rowconfigure(1, weight=1)
        source_frame.columnconfigure(0, weight=1)

        ttk.Label(source_frame, text="Files in source", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.source_tree = ttk.Treeview(source_frame, columns=("size", "modified", "type"), show="tree headings", selectmode="browse")
        self.source_tree.heading("#0", text="File")
        self.source_tree.heading("size", text="Size")
        self.source_tree.heading("modified", text="Modified")
        self.source_tree.heading("type", text="Type")

        self.source_tree.column("#0", width=680, anchor="w")
        self.source_tree.column("size", width=120, anchor="e")
        self.source_tree.column("modified", width=160, anchor="w")
        self.source_tree.column("type", width=220, anchor="w")

        source_scroll = ttk.Scrollbar(source_frame, orient="vertical", command=self.source_tree.yview)
        self.source_tree.configure(yscrollcommand=source_scroll.set)
        self.source_tree.grid(row=1, column=0, sticky="nsew")
        source_scroll.grid(row=1, column=1, sticky="ns")

        self.source_tree.bind("<<TreeviewSelect>>", self._on_source_selection)
        self.source_tree.bind("<Double-1>", self._on_source_double_click)

        status = ttk.Frame(root)
        status.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.syncing_label = ttk.Label(status, text="")
        self.syncing_label.grid(row=0, column=1, sticky="e")

    def _find_note(self, note_id: Optional[str]) -> Optional[NoteItem]:
        if not note_id:
            return None
        for note in self.notes:
            if note.id == note_id:
                return note
        return None

    def _normalize_source_url(self, raw: str) -> Optional[str]:
        value = raw.strip()
        if not value:
            return None

        if value.lower().startswith("ya-disk-public://"):
            return value.replace(" ", "+")

        if "://" not in value:
            value = "https://" + value

        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in ("http", "https"):
            return None
        if not parsed.netloc:
            return None
        return parsed.geturl()

    def _persist_config_safe(self) -> None:
        self._persist_config()

    def _persist_config(self) -> None:
        try:
            interval = max(5, int(self.interval_var.get() or "180"))
        except ValueError:
            interval = 180

        try:
            max_size = max(1, int(self.max_size_var.get() or "100"))
        except ValueError:
            max_size = 100

        cfg = AppConfig(
            check_interval_minutes=interval,
            skip_video_files=bool(self.skip_video_var.get()),
            skip_large_files=bool(self.skip_large_var.get()),
            max_file_size_mb=max_size,
            notes=self.notes,
        )
        self.storage.save_config(cfg)

    def _refresh_notes_table(self) -> None:
        selected = self.selected_note_id
        for iid in self.notes_tree.get_children(""):
            self.notes_tree.delete(iid)

        for note in self.notes:
            self.notes_tree.insert(
                "",
                "end",
                iid=note.id,
                values=(
                    note.title,
                    note.status,
                    iso_to_display(note.last_checked_at),
                    iso_to_display(note.last_updated_at),
                    note.url,
                ),
            )

        if selected and self.notes_tree.exists(selected):
            self.notes_tree.selection_set(selected)
        elif self.notes:
            first = self.notes[0].id
            self.notes_tree.selection_set(first)
            self.selected_note_id = first
        else:
            self.selected_note_id = None

    def _refresh_source_tree(self) -> None:
        self.expanded_folder_ids = {
            iid
            for iid, node in self.source_nodes.items()
            if node.get("is_folder") and self.source_tree.exists(iid) and bool(self.source_tree.item(iid, "open"))
        }

        selected_note = self._find_note(self.selected_note_id)
        selected_tree_id = self.selected_source_tree_id

        self.source_nodes = {}
        self.source_tree.delete(*self.source_tree.get_children(""))

        if not selected_note or selected_note.source_type != "folder" or not selected_note.folder_files:
            self.selected_source_tree_id = None
            self._update_controls_state()
            return

        nodes = self._build_source_tree_data(selected_note.folder_files)
        for node in nodes:
            self._insert_source_node("", node)

        if selected_tree_id and self.source_tree.exists(selected_tree_id):
            self.source_tree.selection_set(selected_tree_id)
            self.selected_source_tree_id = selected_tree_id
        else:
            first_file = self._first_file_tree_id()
            if first_file:
                self.source_tree.selection_set(first_file)
                self.selected_source_tree_id = first_file
            else:
                self.selected_source_tree_id = None

        self._update_controls_state()

    def _folder_tree_id(self, path: str) -> str:
        return "folder:" + hashlib.sha1(path.encode("utf-8")).hexdigest()

    def _file_tree_id(self, path: str) -> str:
        return "file:" + hashlib.sha1(path.encode("utf-8")).hexdigest()

    def _build_source_tree_data(self, files: list[SyncedFileItem]) -> list[dict]:
        class BuildNode:
            def __init__(self, name: str, path: str, file_obj: Optional[SyncedFileItem]) -> None:
                self.name = name
                self.path = path
                self.file_obj = file_obj
                self.children: dict[str, BuildNode] = {}

        root = BuildNode("", "", None)

        for file in sorted(files, key=lambda x: x.local_relative_path.lower()):
            components = [x for x in file.local_relative_path.split("/") if x]
            if not components:
                continue

            current = root
            prefix: list[str] = []

            for folder in components[:-1]:
                prefix.append(folder)
                path = "/".join(prefix)
                if folder not in current.children:
                    current.children[folder] = BuildNode(folder, path, None)
                current = current.children[folder]

            file_name = components[-1]
            file_path = "/".join(components)
            current.children[file_name] = BuildNode(file_name, file_path, file)

        def freeze(node: BuildNode) -> dict:
            if node.file_obj is not None:
                return {
                    "id": self._file_tree_id(node.path),
                    "name": node.name,
                    "path": node.path,
                    "is_folder": False,
                    "file": node.file_obj,
                    "children": [],
                }

            children = [freeze(child) for child in node.children.values()]
            children.sort(key=lambda x: (0 if x["is_folder"] else 1, x["name"].lower()))

            return {
                "id": self._folder_tree_id(node.path),
                "name": node.name,
                "path": node.path,
                "is_folder": True,
                "file": None,
                "children": children,
            }

        top = [freeze(child) for child in root.children.values()]
        top.sort(key=lambda x: (0 if x["is_folder"] else 1, x["name"].lower()))
        return top

    def _insert_source_node(self, parent: str, node: dict) -> None:
        file_obj: Optional[SyncedFileItem] = node["file"]
        values = (
            "-" if node["is_folder"] else human_size(file_obj.size_bytes if file_obj else None),
            "-" if node["is_folder"] else iso_to_display(file_obj.modified_at if file_obj else None),
            "folder" if node["is_folder"] else (file_obj.mime_type if file_obj and file_obj.mime_type else "-"),
        )

        self.source_tree.insert(
            parent,
            "end",
            iid=node["id"],
            text=node["name"],
            values=values,
            open=node["id"] in self.expanded_folder_ids,
        )

        self.source_nodes[node["id"]] = node

        for child in node["children"]:
            self._insert_source_node(node["id"], child)

    def _first_file_tree_id(self) -> Optional[str]:
        for iid, node in self.source_nodes.items():
            if not node.get("is_folder"):
                return iid
        return None

    def _on_note_selection(self, _event: object) -> None:
        selected = self.notes_tree.selection()
        self.selected_note_id = selected[0] if selected else None
        self.selected_source_tree_id = None
        self._refresh_source_tree()
        self._update_controls_state()

    def _on_source_selection(self, _event: object) -> None:
        selected = self.source_tree.selection()
        self.selected_source_tree_id = selected[0] if selected else None
        self._update_controls_state()

    def _on_source_double_click(self, event: tk.Event) -> None:
        iid = self.source_tree.identify_row(event.y)
        if not iid or iid not in self.source_nodes:
            return

        self.source_tree.selection_set(iid)
        self.selected_source_tree_id = iid
        node = self.source_nodes[iid]

        if node.get("is_folder"):
            current_open = bool(self.source_tree.item(iid, "open"))
            self.source_tree.item(iid, open=not current_open)
            return

        file_obj: SyncedFileItem = node["file"]
        note = self._find_note(self.selected_note_id)
        if not note:
            return

        self._open_or_download_source_file(note, file_obj)

    def _open_or_download_source_file(self, note: NoteItem, file_obj: SyncedFileItem) -> None:
        local_path = self.storage.source_file_path(note, file_obj.local_relative_path)
        if local_path.exists():
            self._open_path(local_path)
            self.status_var.set(f"Opened file: {file_obj.local_relative_path}")
            return

        self._start_missing_download(note.id, file_obj.id)

    def _start_missing_download(self, note_id: str, file_id: str) -> None:
        key = f"{note_id}:{file_id}"
        if key in self.inflight_downloads:
            self.status_var.set("Already downloading selected file")
            return

        note = self._find_note(note_id)
        if note is None:
            return

        file_obj = next((x for x in note.folder_files if x.id == file_id), None)
        if file_obj is None:
            return

        self.inflight_downloads.add(key)
        self.status_var.set(f"Local file missing. Starting download: {file_obj.local_relative_path}")

        thread = threading.Thread(
            target=self._missing_download_worker,
            args=(note_id, file_id),
            daemon=True,
        )
        thread.start()

    def _missing_download_worker(self, note_id: str, file_id: str) -> None:
        key = f"{note_id}:{file_id}"
        try:
            note = self._find_note(note_id)
            if note is None:
                raise RuntimeError("Note not found")

            file_obj = next((x for x in note.folder_files if x.id == file_id), None)
            if file_obj is None:
                raise RuntimeError("File not found in source tree")

            note_copy = NoteItem.from_dict(note.to_dict())
            file_copy = SyncedFileItem.from_dict(file_obj.to_dict())

            destination, new_hash = self.engine.download_missing_file(note_copy, file_copy)
            self.ui_queue.put(("missing_download_ok", note_id, file_id, str(destination), new_hash))
        except Exception as exc:  # noqa: BLE001
            self.ui_queue.put(("missing_download_err", note_id, file_id, str(exc)))
        finally:
            self.ui_queue.put(("missing_download_done", key))

    def _open_selected_file(self) -> None:
        note = self._find_note(self.selected_note_id)
        if note is None:
            messagebox.showerror("Error", "Select a note first")
            return

        if note.source_type == "folder":
            selected = self.source_tree.selection()
            if not selected:
                messagebox.showerror("Error", "Select a file in the folder tree")
                return
            node = self.source_nodes.get(selected[0])
            if not node:
                messagebox.showerror("Error", "Select a file in the folder tree")
                return
            if node.get("is_folder"):
                messagebox.showerror("Error", "Select a file, not a folder")
                return
            file_obj: SyncedFileItem = node["file"]
            self._open_or_download_source_file(note, file_obj)
            return

        file_path = self.storage.single_file_path(note)
        if not file_path.exists():
            messagebox.showerror("Error", "Local file is missing. Run sync first.")
            return
        self._open_path(file_path)
        self.status_var.set(f"Opened in default app: {note.title}")

    def _open_path(self, path: Path) -> None:
        try:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open failed", str(exc))

    def _add_note(self) -> None:
        dlg = NoteDialog(self, "Add note")
        self.wait_window(dlg)
        if not dlg.result:
            return

        title, raw_url = dlg.result
        normalized = self._normalize_source_url(raw_url)
        if not normalized:
            messagebox.showerror("Error", "URL is invalid. Use public http/https or ya-disk-public link.")
            return

        note_id = str(uuid.uuid4())
        note = NoteItem(
            id=note_id,
            title=title.strip(),
            url=normalized,
            file_name=self.storage.make_file_name(title, note_id),
            status="Never synced",
        )
        self.notes.append(note)
        self.selected_note_id = note.id
        self.status_var.set("Added 1 note")
        self._persist_config()
        self._refresh_notes_table()
        self._refresh_source_tree()
        self._update_controls_state()

    def _edit_note(self) -> None:
        note = self._find_note(self.selected_note_id)
        if note is None:
            return

        dlg = NoteDialog(self, "Edit note", note.title, note.url)
        self.wait_window(dlg)
        if not dlg.result:
            return

        title, raw_url = dlg.result
        normalized = self._normalize_source_url(raw_url)
        if not normalized:
            messagebox.showerror("Error", "URL is invalid. Use public http/https or ya-disk-public link.")
            return

        url_changed = note.url != normalized

        note.title = title.strip()
        note.url = normalized
        note.status = "Edited. Sync recommended"
        note.last_error = None

        if url_changed:
            note.sha256 = None
            note.source_type = None
            note.folder_files = []
            self.storage.single_file_path(note).unlink(missing_ok=True)
            source_dir = self.storage.source_dir(note)
            if source_dir.exists():
                import shutil

                shutil.rmtree(source_dir, ignore_errors=True)

        self.status_var.set("Note updated")
        self._persist_config()
        self._refresh_notes_table()
        self._refresh_source_tree()

    def _delete_note(self) -> None:
        note = self._find_note(self.selected_note_id)
        if note is None:
            return

        self.storage.single_file_path(note).unlink(missing_ok=True)
        source_dir = self.storage.source_dir(note)
        if source_dir.exists():
            import shutil

            shutil.rmtree(source_dir, ignore_errors=True)

        self.notes = [n for n in self.notes if n.id != note.id]
        self.selected_note_id = None
        self.selected_source_tree_id = None
        self.status_var.set("Deleted 1 note")

        self._persist_config()
        self._refresh_notes_table()
        self._refresh_source_tree()
        self._update_controls_state()

    def _current_download_options(self) -> DownloadOptions:
        try:
            max_size_mb = max(1, int(self.max_size_var.get() or "100"))
        except ValueError:
            max_size_mb = 100
        return DownloadOptions(
            skip_video_files=bool(self.skip_video_var.get()),
            skip_large_files=bool(self.skip_large_var.get()),
            max_file_size_bytes=max_size_mb * 1_048_576,
        )

    def _sync_selected(self) -> None:
        if not self.selected_note_id:
            messagebox.showerror("Error", "Select a note first")
            return
        self._start_sync([self.selected_note_id], reason="manual")

    def _sync_all(self) -> None:
        self._start_sync([n.id for n in self.notes], reason="manual")

    def _stop_sync(self) -> None:
        if not self.is_syncing or self.sync_cancel_event is None:
            return
        if self.is_stopping:
            return

        self.is_stopping = True
        self.status_var.set("Stopping sync...")
        self.sync_cancel_event.set()
        self._update_controls_state()

    def _start_sync(self, note_ids: list[str], reason: str) -> None:
        if self.is_syncing:
            self.status_var.set("Sync already in progress")
            return
        if not note_ids:
            self.status_var.set("No notes to sync")
            return

        self.is_syncing = True
        self.is_stopping = False
        self.sync_cancel_event = threading.Event()
        self.status_var.set("Sync started")
        self.syncing_label.configure(text="Syncing...")
        self._update_controls_state()

        options = self._current_download_options()

        self.sync_thread = threading.Thread(
            target=self._sync_worker,
            args=(note_ids, reason, options, self.sync_cancel_event),
            daemon=True,
        )
        self.sync_thread.start()

    def _sync_worker(
        self,
        note_ids: list[str],
        reason: str,
        options: DownloadOptions,
        cancel_event: threading.Event,
    ) -> None:
        updated_count = 0
        error_count = 0
        stopped = False

        for offset, note_id in enumerate(note_ids):
            if cancel_event.is_set():
                stopped = True
                break

            note = self._find_note(note_id)
            if note is None:
                continue

            self.ui_queue.put(("note_precheck", note_id, offset + 1, len(note_ids)))

            note_copy = NoteItem.from_dict(note.to_dict())

            def on_progress(progress: FolderDownloadProgress, nid: str = note_id, title: str = note_copy.title) -> None:
                self.ui_queue.put(("folder_progress", nid, title, progress))

            result = self.engine.sync_single_note(
                note_copy,
                options,
                progress_cb=on_progress,
                cancel_event=cancel_event,
            )

            synced = result.note
            if synced.last_error:
                error_count += 1
            elif synced.status == "Updated" or synced.status.startswith("Folder synced:"):
                updated_count += 1

            if synced.status == "Stopped":
                stopped = True

            self.ui_queue.put(("note_synced", synced))

            if cancel_event.is_set():
                stopped = True
                break

        self.ui_queue.put(("sync_finished", updated_count, error_count, stopped, reason))

    def _process_ui_queue(self) -> None:
        while True:
            try:
                event = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event[0]
            if event_type == "note_precheck":
                _, note_id, idx, total = event
                note = self._find_note(note_id)
                if note:
                    note.status = f"Checking ({idx}/{total})"
                    note.last_error = None
                    self._refresh_notes_table()
            elif event_type == "folder_progress":
                _, note_id, title, progress = event
                self._apply_folder_progress(note_id, title, progress)
            elif event_type == "note_synced":
                _, synced_note = event
                self._replace_note(synced_note)
                self._persist_config()
            elif event_type == "sync_finished":
                _, updated_count, error_count, stopped, reason = event
                self.is_syncing = False
                self.is_stopping = False
                self.sync_cancel_event = None
                self.syncing_label.configure(text="")
                self.last_auto_sync_at = datetime.utcnow()

                if stopped:
                    self.status_var.set(f"Sync stopped. Updated: {updated_count}, errors: {error_count}")
                elif error_count == 0:
                    self.status_var.set(f"Sync complete. Updated: {updated_count}")
                else:
                    self.status_var.set(f"Sync complete. Updated: {updated_count}, errors: {error_count}")
                    if reason == "manual":
                        messagebox.showwarning("Sync finished", "Some notes failed to sync. Check status column.")

                self._persist_config()
                self._refresh_notes_table()
                self._refresh_source_tree()
                self._update_controls_state()
            elif event_type == "missing_download_ok":
                _, note_id, file_id, destination, new_hash = event
                note = self._find_note(note_id)
                if note:
                    for f in note.folder_files:
                        if f.id == file_id:
                            f.sha256 = new_hash
                            break
                    note.last_updated_at = now_iso()
                    self._persist_config()
                    self._refresh_source_tree()
                self.status_var.set(f"Downloaded and opening: {Path(destination).name}")
                self._open_path(Path(destination))
            elif event_type == "missing_download_err":
                _, note_id, file_id, error_message = event
                self.status_var.set(f"Download failed: {error_message}")
                messagebox.showerror("Download failed", error_message)
            elif event_type == "missing_download_done":
                _, key = event
                self.inflight_downloads.discard(key)

        self.after(120, self._process_ui_queue)

    def _apply_folder_progress(self, note_id: str, note_title: str, progress: FolderDownloadProgress) -> None:
        note = self._find_note(note_id)
        if note is None:
            return

        note.source_type = "folder"
        note.status = f"Checking folder ({progress.processed_count}/{progress.total_count})"

        if progress.latest_file:
            latest = progress.latest_file
            item = SyncedFileItem(
                relative_path=latest.remote_path,
                local_relative_path=latest.local_relative_path,
                sha256="",
                modified_at=latest.modified_at,
                size_bytes=latest.size_bytes,
                mime_type=latest.mime_type,
            )

            existing = next((i for i, x in enumerate(note.folder_files) if x.id == item.id), None)
            if existing is None:
                note.folder_files.append(item)
            else:
                note.folder_files[existing] = item

            note.folder_files.sort(key=lambda x: x.local_relative_path.lower())

        self.status_var.set(f"Syncing {note_title}: {progress.processed_count}/{progress.total_count}")
        self._refresh_notes_table()
        if self.selected_note_id == note_id:
            self._refresh_source_tree()

    def _replace_note(self, synced_note: NoteItem) -> None:
        for idx, existing in enumerate(self.notes):
            if existing.id == synced_note.id:
                self.notes[idx] = synced_note
                break
        else:
            self.notes.append(synced_note)

        self._refresh_notes_table()
        if self.selected_note_id == synced_note.id:
            self._refresh_source_tree()

    def _apply_max_size(self) -> None:
        try:
            value = max(1, int(self.max_size_var.get() or "100"))
        except ValueError:
            messagebox.showerror("Error", "Max file size must be an integer (MB)")
            return

        self.max_size_var.set(str(value))
        self._persist_config()

    def _apply_interval(self) -> None:
        try:
            value = max(5, int(self.interval_var.get() or "180"))
        except ValueError:
            messagebox.showerror("Error", "Interval must be an integer")
            return

        self.interval_var.set(str(value))
        self._persist_config()

    def _auto_sync_tick(self) -> None:
        try:
            if not self.is_syncing and self.notes:
                try:
                    interval = max(5, int(self.interval_var.get() or "180"))
                except ValueError:
                    interval = 180

                elapsed = (datetime.utcnow() - self.last_auto_sync_at).total_seconds()
                if elapsed >= interval * 60:
                    self._start_sync([n.id for n in self.notes], reason="auto")
        finally:
            self.after(20_000, self._auto_sync_tick)

    def _update_controls_state(self) -> None:
        has_note = self._find_note(self.selected_note_id) is not None
        has_notes = len(self.notes) > 0

        self.add_btn.configure(state="disabled" if self.is_syncing else "normal")
        self.edit_btn.configure(state="disabled" if self.is_syncing or not has_note else "normal")
        self.delete_btn.configure(state="disabled" if self.is_syncing or not has_note else "normal")

        self.update_selected_btn.configure(state="disabled" if self.is_syncing or not has_note else "normal")
        self.update_all_btn.configure(state="disabled" if self.is_syncing or not has_notes else "normal")
        self.stop_btn.configure(state="normal" if self.is_syncing and not self.is_stopping else "disabled")

        note = self._find_note(self.selected_note_id)
        can_open = False
        if note:
            if note.source_type == "folder":
                selected = self.source_tree.selection()
                if selected:
                    node = self.source_nodes.get(selected[0])
                    can_open = bool(node and not node.get("is_folder"))
            else:
                can_open = True

        self.open_btn.configure(state="normal" if can_open else "disabled")


def launch_app() -> None:
    app = NotesSyncLinuxApp()
    app.mainloop()
