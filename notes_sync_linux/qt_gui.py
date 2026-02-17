from __future__ import annotations

import hashlib
import queue
import subprocess
import threading
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .core import (
    AppConfig,
    DownloadOptions,
    FolderDownloadProgress,
    NoteItem,
    NotesDownloader,
    StorageManager,
    SyncedFileItem,
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


class NoteDialog(QDialog):
    def __init__(self, parent: QWidget, dialog_title: str, initial_title: str = "", initial_url: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(dialog_title)
        self.setModal(True)
        self.resize(680, 180)

        self.result: Optional[tuple[str, str]] = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.title_edit = QLineEdit(initial_title)
        self.url_edit = QLineEdit(initial_url)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #f87171;")

        form.addRow("Title", self.title_edit)
        form.addRow("Public link", self.url_edit)

        layout.addLayout(form)
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.title_edit.setFocus()

    def _on_save(self) -> None:
        title = self.title_edit.text().strip()
        url = self.url_edit.text().strip()

        if not title:
            self.error_label.setText("Title cannot be empty")
            return

        if not url:
            self.error_label.setText("URL cannot be empty")
            return

        self.result = (title, url)
        self.accept()


class NotesSyncQtWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NotesSyncLinux (Qt)")
        self.resize(1460, 920)
        self.setMinimumSize(1120, 700)

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
        self.source_items: dict[str, QTreeWidgetItem] = {}
        self.expanded_folder_ids: set[str] = set()

        self.is_syncing = False
        self.is_stopping = False
        self.sync_cancel_event: Optional[threading.Event] = None
        self.sync_thread: Optional[threading.Thread] = None
        self.inflight_downloads: set[str] = set()
        self.last_auto_sync_at: datetime = datetime.min

        self.ui_queue: queue.Queue = queue.Queue()

        self._build_ui()
        self._apply_theme()
        self._refresh_notes_table()
        self._refresh_source_tree()
        self._update_controls_state()

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._process_ui_queue)
        self.ui_timer.start(120)

        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self._auto_sync_tick)
        self.auto_timer.start(20_000)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self._add_note)
        controls.addWidget(self.add_btn)

        self.edit_btn = QPushButton("Edit")
        self.edit_btn.clicked.connect(self._edit_note)
        controls.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete_note)
        controls.addWidget(self.delete_btn)

        self.update_selected_btn = QPushButton("Update selected")
        self.update_selected_btn.clicked.connect(self._sync_selected)
        controls.addWidget(self.update_selected_btn)

        self.update_all_btn = QPushButton("Update all")
        self.update_all_btn.clicked.connect(self._sync_all)
        controls.addWidget(self.update_all_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop_sync)
        controls.addWidget(self.stop_btn)

        self.open_btn = QPushButton("Open selected file")
        self.open_btn.clicked.connect(self._open_selected_file)
        controls.addWidget(self.open_btn)

        controls.addSpacing(14)

        self.skip_video_checkbox = QCheckBox("Skip videos")
        self.skip_video_checkbox.setChecked(self.config_data.skip_video_files)
        self.skip_video_checkbox.stateChanged.connect(self._persist_config_safe)
        controls.addWidget(self.skip_video_checkbox)

        self.skip_large_checkbox = QCheckBox("Skip >")
        self.skip_large_checkbox.setChecked(self.config_data.skip_large_files)
        self.skip_large_checkbox.stateChanged.connect(self._persist_config_safe)
        controls.addWidget(self.skip_large_checkbox)

        self.max_size_spin = QSpinBox()
        self.max_size_spin.setRange(1, 100_000)
        self.max_size_spin.setValue(max(1, int(self.config_data.max_file_size_mb)))
        self.max_size_spin.setSuffix(" MB")
        self.max_size_spin.setFixedWidth(110)
        controls.addWidget(self.max_size_spin)

        self.max_size_set_btn = QPushButton("Set")
        self.max_size_set_btn.clicked.connect(self._apply_max_size)
        controls.addWidget(self.max_size_set_btn)

        controls.addStretch(1)

        controls.addWidget(QLabel("Auto every"))

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 100_000)
        self.interval_spin.setValue(max(5, int(self.config_data.check_interval_minutes)))
        self.interval_spin.setSuffix(" min")
        self.interval_spin.setFixedWidth(110)
        controls.addWidget(self.interval_spin)

        self.interval_apply_btn = QPushButton("Apply")
        self.interval_apply_btn.clicked.connect(self._apply_interval)
        controls.addWidget(self.interval_apply_btn)

        layout.addLayout(controls)

        self.notes_table = QTableWidget(0, 5)
        self.notes_table.setHorizontalHeaderLabels(["Title", "Status", "Last checked", "Last updated", "Source URL"])
        self.notes_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.notes_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.notes_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.notes_table.verticalHeader().setVisible(False)
        self.notes_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.notes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.notes_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.notes_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.notes_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.notes_table.itemSelectionChanged.connect(self._on_note_selection)
        self.notes_table.setAlternatingRowColors(True)
        layout.addWidget(self.notes_table, stretch=3)

        src_label = QLabel("Files in source")
        src_label.setObjectName("SectionLabel")
        layout.addWidget(src_label)

        self.source_tree = QTreeWidget()
        self.source_tree.setColumnCount(4)
        self.source_tree.setHeaderLabels(["File", "Size", "Modified", "Type"])
        self.source_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.source_tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self.source_tree.setAlternatingRowColors(True)
        self.source_tree.itemSelectionChanged.connect(self._on_source_selection)
        self.source_tree.itemDoubleClicked.connect(self._on_source_double_click)
        self.source_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.source_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.source_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.source_tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.source_tree, stretch=4)

        status_line = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.syncing_label = QLabel("")
        self.syncing_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_line.addWidget(self.status_label, stretch=1)
        status_line.addWidget(self.syncing_label)
        layout.addLayout(status_line)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        self.setCentralWidget(root)

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app:
            app.setStyle("Fusion")

        self.setStyleSheet(
            """
            QMainWindow {
                background: #0f1424;
            }
            QWidget {
                color: #e5e7eb;
                font-size: 13px;
            }
            QLabel#SectionLabel {
                font-size: 15px;
                font-weight: 600;
                color: #bfdbfe;
                margin-top: 4px;
            }
            QPushButton {
                background: #1d4ed8;
                color: white;
                border: 1px solid #3b82f6;
                border-radius: 8px;
                padding: 6px 10px;
                min-height: 22px;
            }
            QPushButton:hover {
                background: #2563eb;
            }
            QPushButton:disabled {
                background: #374151;
                color: #9ca3af;
                border-color: #4b5563;
            }
            QLineEdit, QSpinBox {
                background: #111827;
                border: 1px solid #374151;
                border-radius: 8px;
                padding: 4px 8px;
                selection-background-color: #1d4ed8;
            }
            QTableWidget, QTreeWidget {
                background: #0b1220;
                alternate-background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 10px;
                gridline-color: #334155;
                selection-background-color: #1d4ed8;
                selection-color: #ffffff;
            }
            QHeaderView::section {
                background: #111827;
                color: #cbd5e1;
                border: 0px;
                border-right: 1px solid #1f2937;
                padding: 6px 8px;
                font-weight: 600;
            }
            QCheckBox {
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                border: 1px solid #64748b;
                border-radius: 4px;
                background: #0b1220;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #3b82f6;
                border-radius: 4px;
                background: #1d4ed8;
            }
            """
        )

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

    def _persist_config_safe(self, _state: object = None) -> None:
        self._persist_config()

    def _persist_config(self) -> None:
        cfg = AppConfig(
            check_interval_minutes=max(5, int(self.interval_spin.value())),
            skip_video_files=bool(self.skip_video_checkbox.isChecked()),
            skip_large_files=bool(self.skip_large_checkbox.isChecked()),
            max_file_size_mb=max(1, int(self.max_size_spin.value())),
            notes=self.notes,
        )
        self.storage.save_config(cfg)

    def _refresh_notes_table(self) -> None:
        selected = self.selected_note_id

        self.notes_table.setRowCount(0)
        for note in self.notes:
            row = self.notes_table.rowCount()
            self.notes_table.insertRow(row)

            title_item = QTableWidgetItem(note.title)
            title_item.setData(Qt.ItemDataRole.UserRole, note.id)
            status_item = QTableWidgetItem(note.status)
            checked_item = QTableWidgetItem(iso_to_display(note.last_checked_at))
            updated_item = QTableWidgetItem(iso_to_display(note.last_updated_at))
            url_item = QTableWidgetItem(note.url)

            for item in (title_item, status_item, checked_item, updated_item, url_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.notes_table.setItem(row, 0, title_item)
            self.notes_table.setItem(row, 1, status_item)
            self.notes_table.setItem(row, 2, checked_item)
            self.notes_table.setItem(row, 3, updated_item)
            self.notes_table.setItem(row, 4, url_item)

        target_row = None
        if selected:
            for row in range(self.notes_table.rowCount()):
                item = self.notes_table.item(row, 0)
                if item and item.data(Qt.ItemDataRole.UserRole) == selected:
                    target_row = row
                    break

        if target_row is None and self.notes_table.rowCount() > 0:
            target_row = 0

        if target_row is not None:
            self.notes_table.selectRow(target_row)
            item = self.notes_table.item(target_row, 0)
            if item:
                self.selected_note_id = item.data(Qt.ItemDataRole.UserRole)
        else:
            self.selected_note_id = None

    def _refresh_source_tree(self) -> None:
        self.expanded_folder_ids = {
            iid for iid, node in self.source_nodes.items() if node.get("is_folder") and iid in self.source_items and self.source_items[iid].isExpanded()
        }

        selected_note = self._find_note(self.selected_note_id)
        selected_tree_id = self.selected_source_tree_id

        self.source_nodes = {}
        self.source_items = {}
        self.source_tree.clear()

        if not selected_note or selected_note.source_type != "folder" or not selected_note.folder_files:
            self.selected_source_tree_id = None
            self._update_controls_state()
            return

        nodes = self._build_source_tree_data(selected_note.folder_files)
        for node in nodes:
            self._insert_source_node(None, node)

        target_id: Optional[str] = None
        if selected_tree_id and selected_tree_id in self.source_items:
            target_id = selected_tree_id
        else:
            target_id = self._first_file_tree_id()

        if target_id and target_id in self.source_items:
            self.source_tree.setCurrentItem(self.source_items[target_id])
            self.selected_source_tree_id = target_id
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

    def _insert_source_node(self, parent: Optional[QTreeWidgetItem], node: dict) -> None:
        file_obj: Optional[SyncedFileItem] = node["file"]
        values = [
            node["name"],
            "-" if node["is_folder"] else human_size(file_obj.size_bytes if file_obj else None),
            "-" if node["is_folder"] else iso_to_display(file_obj.modified_at if file_obj else None),
            "folder" if node["is_folder"] else (file_obj.mime_type if file_obj and file_obj.mime_type else "-"),
        ]

        item = QTreeWidgetItem(values)
        item.setData(0, Qt.ItemDataRole.UserRole, node["id"])
        if node["is_folder"]:
            item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon))
        else:
            item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_FileIcon))

        if parent is None:
            self.source_tree.addTopLevelItem(item)
        else:
            parent.addChild(item)

        item.setExpanded(node["id"] in self.expanded_folder_ids)

        self.source_nodes[node["id"]] = node
        self.source_items[node["id"]] = item

        for child in node["children"]:
            self._insert_source_node(item, child)

    def _first_file_tree_id(self) -> Optional[str]:
        for iid, node in self.source_nodes.items():
            if not node.get("is_folder"):
                return iid
        return None

    def _on_note_selection(self) -> None:
        row = self.notes_table.currentRow()
        if row < 0:
            self.selected_note_id = None
            self.selected_source_tree_id = None
            self._refresh_source_tree()
            self._update_controls_state()
            return

        item = self.notes_table.item(row, 0)
        note_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.selected_note_id = note_id
        self.selected_source_tree_id = None
        self._refresh_source_tree()
        self._update_controls_state()

    def _on_source_selection(self) -> None:
        selected = self.source_tree.selectedItems()
        if not selected:
            self.selected_source_tree_id = None
        else:
            self.selected_source_tree_id = selected[0].data(0, Qt.ItemDataRole.UserRole)
        self._update_controls_state()

    def _on_source_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        iid = item.data(0, Qt.ItemDataRole.UserRole)
        if not iid or iid not in self.source_nodes:
            return

        self.source_tree.setCurrentItem(item)
        self.selected_source_tree_id = iid
        node = self.source_nodes[iid]

        if node.get("is_folder"):
            item.setExpanded(not item.isExpanded())
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
            self.status_label.setText(f"Opened file: {file_obj.local_relative_path}")
            return

        self._start_missing_download(note.id, file_obj.id)

    def _start_missing_download(self, note_id: str, file_id: str) -> None:
        key = f"{note_id}:{file_id}"
        if key in self.inflight_downloads:
            self.status_label.setText("Already downloading selected file")
            return

        note = self._find_note(note_id)
        if note is None:
            return

        file_obj = next((x for x in note.folder_files if x.id == file_id), None)
        if file_obj is None:
            return

        self.inflight_downloads.add(key)
        self.status_label.setText(f"Local file missing. Starting download: {file_obj.local_relative_path}")

        thread = threading.Thread(target=self._missing_download_worker, args=(note_id, file_id), daemon=True)
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
            QMessageBox.critical(self, "Error", "Select a note first")
            return

        if note.source_type == "folder":
            selected = self.source_tree.selectedItems()
            if not selected:
                QMessageBox.critical(self, "Error", "Select a file in the folder tree")
                return

            node_id = selected[0].data(0, Qt.ItemDataRole.UserRole)
            node = self.source_nodes.get(node_id)
            if not node:
                QMessageBox.critical(self, "Error", "Select a file in the folder tree")
                return
            if node.get("is_folder"):
                QMessageBox.critical(self, "Error", "Select a file, not a folder")
                return

            file_obj: SyncedFileItem = node["file"]
            self._open_or_download_source_file(note, file_obj)
            return

        file_path = self.storage.single_file_path(note)
        if not file_path.exists():
            QMessageBox.critical(self, "Error", "Local file is missing. Run sync first.")
            return

        self._open_path(file_path)
        self.status_label.setText(f"Opened in default app: {note.title}")

    def _open_path(self, path: Path) -> None:
        try:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Open failed", str(exc))

    def _add_note(self) -> None:
        dlg = NoteDialog(self, "Add note")
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result:
            return

        title, raw_url = dlg.result
        normalized = self._normalize_source_url(raw_url)
        if not normalized:
            QMessageBox.critical(self, "Error", "URL is invalid. Use public http/https or ya-disk-public link.")
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
        self.status_label.setText("Added 1 note")
        self._persist_config()
        self._refresh_notes_table()
        self._refresh_source_tree()
        self._update_controls_state()

    def _edit_note(self) -> None:
        note = self._find_note(self.selected_note_id)
        if note is None:
            return

        dlg = NoteDialog(self, "Edit note", note.title, note.url)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result:
            return

        title, raw_url = dlg.result
        normalized = self._normalize_source_url(raw_url)
        if not normalized:
            QMessageBox.critical(self, "Error", "URL is invalid. Use public http/https or ya-disk-public link.")
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

        self.status_label.setText("Note updated")
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
        self.status_label.setText("Deleted 1 note")

        self._persist_config()
        self._refresh_notes_table()
        self._refresh_source_tree()
        self._update_controls_state()

    def _current_download_options(self) -> DownloadOptions:
        max_size_mb = max(1, int(self.max_size_spin.value()))
        return DownloadOptions(
            skip_video_files=bool(self.skip_video_checkbox.isChecked()),
            skip_large_files=bool(self.skip_large_checkbox.isChecked()),
            max_file_size_bytes=max_size_mb * 1_048_576,
        )

    def _sync_selected(self) -> None:
        if not self.selected_note_id:
            QMessageBox.critical(self, "Error", "Select a note first")
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
        self.status_label.setText("Stopping sync...")
        self.sync_cancel_event.set()
        self._update_controls_state()

    def _start_sync(self, note_ids: list[str], reason: str) -> None:
        if self.is_syncing:
            self.status_label.setText("Sync already in progress")
            return
        if not note_ids:
            self.status_label.setText("No notes to sync")
            return

        self.is_syncing = True
        self.is_stopping = False
        self.sync_cancel_event = threading.Event()
        self.status_label.setText("Sync started")
        self.syncing_label.setText("Syncing...")
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
                self.syncing_label.setText("")
                self.last_auto_sync_at = datetime.utcnow()

                if stopped:
                    self.status_label.setText(f"Sync stopped. Updated: {updated_count}, errors: {error_count}")
                elif error_count == 0:
                    self.status_label.setText(f"Sync complete. Updated: {updated_count}")
                else:
                    self.status_label.setText(f"Sync complete. Updated: {updated_count}, errors: {error_count}")
                    if reason == "manual":
                        QMessageBox.warning(self, "Sync finished", "Some notes failed to sync. Check status column.")

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
                self.status_label.setText(f"Downloaded and opening: {Path(destination).name}")
                self._open_path(Path(destination))
            elif event_type == "missing_download_err":
                _, _note_id, _file_id, error_message = event
                self.status_label.setText(f"Download failed: {error_message}")
                QMessageBox.critical(self, "Download failed", error_message)
            elif event_type == "missing_download_done":
                _, key = event
                self.inflight_downloads.discard(key)

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

        self.status_label.setText(f"Syncing {note_title}: {progress.processed_count}/{progress.total_count}")
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
        self.max_size_spin.setValue(max(1, self.max_size_spin.value()))
        self._persist_config()

    def _apply_interval(self) -> None:
        self.interval_spin.setValue(max(5, self.interval_spin.value()))
        self._persist_config()

    def _auto_sync_tick(self) -> None:
        if not self.is_syncing and self.notes:
            interval = max(5, int(self.interval_spin.value()))
            elapsed = (datetime.utcnow() - self.last_auto_sync_at).total_seconds()
            if elapsed >= interval * 60:
                self._start_sync([n.id for n in self.notes], reason="auto")

    def _update_controls_state(self) -> None:
        has_note = self._find_note(self.selected_note_id) is not None
        has_notes = len(self.notes) > 0

        enabled_when_idle = not self.is_syncing
        self.add_btn.setEnabled(enabled_when_idle)
        self.edit_btn.setEnabled(enabled_when_idle and has_note)
        self.delete_btn.setEnabled(enabled_when_idle and has_note)
        self.update_selected_btn.setEnabled(enabled_when_idle and has_note)
        self.update_all_btn.setEnabled(enabled_when_idle and has_notes)
        self.stop_btn.setEnabled(self.is_syncing and not self.is_stopping)

        note = self._find_note(self.selected_note_id)
        can_open = False
        if note:
            if note.source_type == "folder":
                selected = self.source_tree.selectedItems()
                if selected:
                    node_id = selected[0].data(0, Qt.ItemDataRole.UserRole)
                    node = self.source_nodes.get(node_id)
                    can_open = bool(node and not node.get("is_folder"))
            else:
                can_open = True

        self.open_btn.setEnabled(can_open)


def launch_app() -> None:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("NotesSyncLinux")
    window = NotesSyncQtWindow()
    window.show()
    app.exec()
