# main_app.py
import sys
import json
import logging
from pathlib import Path
import difflib

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QTextEdit, QTreeView, QSplitter, QMessageBox,
    QPlainTextEdit, QSizePolicy
)
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QPalette, QColor, QFont, QIcon, QCloseEvent
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings

from core_logic import (
    parse_condition_file, generate_folder_structure,
    ascii_to_structure, structure_to_ascii, validate_ascii_tree,
    scan_python_imports, generate_requirements_content
)
from ai_client import GeminiClient

# --- Глобальная конфигурация логирования ---
log_format = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(message)s'
logger = logging.getLogger(__name__)

# --- Состояния приложения (константы) ---
APP_STATE_INITIAL = "Initial"
APP_STATE_ACCEPTED = "Accepted"
APP_STATE_DRAFT = "Draft"
EDIT_MODE_TREE = "Tree"
EDIT_MODE_ASCII = "Ascii"

# --- Класс для логирования в QTextEdit ---
class QTextEditLogger(logging.Handler):
    """
    Обработчик логирования Python, который направляет сообщения в виджет QTextEdit.
    """
    def __init__(self, text_edit_widget: QTextEdit):
        super().__init__()
        self.widget = text_edit_widget
        self.widget.setReadOnly(True)

    def emit(self, record: logging.LogRecord) -> None:
        """
        Форматирует и добавляет запись лога в QTextEdit.

        Args:
            record (logging.LogRecord): Объект записи лога.
        """
        msg = self.format(record)
        self.widget.append(msg)
        scrollbar = self.widget.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

# --- Рабочие потоки для длительных операций ---
class AIWorker(QThread):
    """
    Рабочий поток для выполнения запросов к AI (GeminiClient)
    без блокировки основного GUI потока.
    """
    finished_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)

    def __init__(self, ai_client_instance: GeminiClient, file_content: str, user_query: str):
        """
        Args:
            ai_client_instance (GeminiClient): Экземпляр клиента AI.
            file_content (str): Текстовое содержимое файла-условия.
            user_query (str): Дополнительный запрос пользователя к AI.
        """
        super().__init__()
        self.ai_client = ai_client_instance
        self.file_content = file_content
        self.user_query = user_query
        logger.debug("AIWorker initialized.")

    def run(self) -> None:
        """
        Основной метод потока, выполняющий запрос к AI.
        Эмитирует finished_signal с результатом или error_signal с сообщением об ошибке.
        """
        logger.info("AIWorker thread started.")
        try:
            if not self.ai_client or not self.ai_client.model:
                 error_msg = "Клиент AI не инициализирован или модель AI недоступна. Проверьте API ключ."
                 logger.warning(f"AIWorker: {error_msg}")
                 self.error_signal.emit(error_msg)
                 return

            suggestion = self.ai_client.get_structure_suggestion(self.file_content, self.user_query)
            
            if isinstance(suggestion, dict) and "error" in suggestion:
                error_type = suggestion.get("error", "UNKNOWN_AI_ERROR")
                error_message = suggestion.get("message", "Неизвестная ошибка от AI клиента.")
                logger.warning(f"AIWorker received error from AI client: {error_type} - {error_message}")
                self.error_signal.emit(f"Ошибка AI ({error_type}): {error_message}")
            else:
                self.finished_signal.emit(suggestion)
                logger.info(f"AIWorker finished, emitted suggestion (type: {type(suggestion)}).")

        except Exception as e:
            logger.error(f"AIWorker unhandled exception: {e}", exc_info=True)
            self.error_signal.emit(f"Непредвиденная ошибка в потоке AI: {e}")
        logger.debug("AIWorker thread finished execution.")


class ReqScanWorker(QThread):
    """
    Рабочий поток для сканирования Python файлов на импорты
    с целью генерации requirements.txt.
    """
    finished_signal = pyqtSignal(set)
    error_signal = pyqtSignal(str)

    def __init__(self, project_path: str):
        """
        Args:
            project_path (str): Путь к директории проекта для сканирования.
        """
        super().__init__()
        self.project_path = project_path
        logger.debug(f"ReqScanWorker initialized for path: '{self.project_path}'.")

    def run(self) -> None:
        """
        Основной метод потока, выполняющий сканирование импортов.
        Эмитирует finished_signal с множеством найденных импортов или error_signal.
        """
        logger.info(f"ReqScanWorker thread started for path: '{self.project_path}'.")
        try:
            imports = scan_python_imports(self.project_path)
            self.finished_signal.emit(imports)
            logger.info(f"ReqScanWorker finished successfully, emitted {len(imports)} unique import names.")
        except Exception as e:
           logger.error(f"ReqScanWorker unhandled exception: {e}", exc_info=True)
           self.error_signal.emit(f"Непредвиденная ошибка сканирования зависимостей: {e}")
        logger.debug("ReqScanWorker thread finished execution.")


class MainWindow(QMainWindow):
    """
    Главное окно приложения "LabFolder Generator".
    Отвечает за отображение GUI, управление состояниями приложения
    и взаимодействие с бизнес-логикой и AI-клиентом.
    """
    def __init__(self, config_data: dict):
        """
        Args:
            config_data (dict): Словарь конфигурации приложения, загруженный из config.json.
        """
        super().__init__()
        self.config: dict = config_data
        self.current_app_state: str = APP_STATE_INITIAL
        self.current_edit_mode: str = EDIT_MODE_TREE
        self.draft_from_ai_flag: bool = False

        self.accepted_structure_dict: dict | None = None
        self.draft_structure_dict: dict | None = None

        self.condition_file_path: str | None = None
        
        self.settings = QSettings(
            QApplication.organizationName(),
            QApplication.applicationName()
        )
        default_output = self.config.get("default_output_folder", "")
        if not default_output:
            default_output = str(Path.home() / "LabGeneratorProjects")
        self.output_folder_path: str = self.settings.value("paths/output_folder", default_output, type=str)

        self.ai_client: GeminiClient | None = self._initialize_ai_client()

        self.ai_worker: AIWorker | None = None
        self.req_scan_worker: ReqScanWorker | None = None

        self._init_ui()
        self._setup_logging_to_ui()
        
        self._log_to_ui(f"Приложение '{self.config.get('app_name')}' v{self.config.get('version')} запущено.", level="INFO")
        self.update_ui_for_state()

    def _initialize_ai_client(self) -> GeminiClient | None:
        """ Инициализирует AI клиент на основе конфигурации. """
        api_key = self.config.get("gemini_api_key", "")
        prompt_template = self.config.get("ai_prompt_template", "")

        if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE_OR_LEAVE_EMPTY_FOR_USER_INPUT":
            logger.warning("AI Client not initialized: API key missing or placeholder in config.")
            # Информационное сообщение пользователю при первом запуске или при попытке использовать AI
            # QMessageBox.information(self, "AI не настроен", ...) # Можно отложить до первого использования
            return None
        try:
            client = GeminiClient(api_key, prompt_template)
            if not client.model:
                logger.warning("AI Client initialized, but its model is not available. AI features might be limited.")
            return client
        except Exception as e:
            logger.error(f"Failed to initialize AI Client in MainWindow: {e}", exc_info=True)
            QMessageBox.critical(self, "Ошибка инициализации AI",
                                 f"Не удалось инициализировать AI клиент: {e}\n"
                                 "Функции AI будут недоступны. Проверьте API ключ и лог приложения.")
            return None
            
    def _log_to_ui(self, message: str, level: str = "INFO") -> None:
        """
        Логирует сообщение в стандартный логгер Python.

        Args:
            message (str): Текст сообщения.
            level (str, optional): Уровень логирования. По умолчанию "INFO".
        """
        log_level_map = {
            "DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING,
            "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL
        }
        python_log_level = log_level_map.get(level.upper(), logging.INFO)
        logger.log(python_log_level, message)

    def _setup_logging_to_ui(self) -> None:
        """ Настраивает перенаправление логов Python в виджет QTextEdit в GUI. """
        text_edit_handler = QTextEditLogger(self.log_view_widget)
        # Пытаемся получить форматтер от уже существующих обработчиков корневого логгера
        # (например, от FileHandler или StreamHandler, настроенных в main)
        root_logger_handlers = logging.getLogger().handlers
        if root_logger_handlers and hasattr(root_logger_handlers[0], 'formatter') and root_logger_handlers[0].formatter:
            formatter_to_use = root_logger_handlers[0].formatter
        else: # Fallback, если не удалось получить форматтер
            formatter_to_use = logging.Formatter(log_format)
        text_edit_handler.setFormatter(formatter_to_use)
        
        logging.getLogger().addHandler(text_edit_handler)
        text_edit_handler.setLevel(logging.DEBUG) # Логи в UI будут с уровня DEBUG


    def _init_ui(self) -> None:
        """ Инициализирует и размещает все элементы графического интерфейса. """
        self.setWindowTitle(f"{self.config.get('app_name', 'LabFolder Generator')} v{self.config.get('version', 'dev')}")
        
        geometry_bytes = self.settings.value("window/geometry")
        if geometry_bytes and isinstance(geometry_bytes, (bytes, bytearray)):
            self.restoreGeometry(geometry_bytes)
        else:
            self.setGeometry(100, 100, 950, 750)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)

        input_panel_grid = QGridLayout()
        input_panel_grid.setSpacing(5)
        main_layout.addLayout(input_panel_grid)

        self.condition_file_label = QLabel("Файл условия:")
        self.condition_file_path_display = QLabel("(не выбран)")
        self.condition_file_path_display.setToolTip("Полный путь к выбранному файлу условия лаборатории")
        self.condition_file_path_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.condition_file_button = QPushButton("Выбрать...")
        self.condition_file_button.setToolTip("Открыть диалог выбора файла условия (.pdf, .docx, .txt)")
        self.condition_file_button.clicked.connect(self.on_select_condition_file)
        
        input_panel_grid.addWidget(self.condition_file_label, 0, 0)
        input_panel_grid.addWidget(self.condition_file_path_display, 0, 1)
        input_panel_grid.addWidget(self.condition_file_button, 0, 2)

        self.output_folder_label = QLabel("Папка вывода:")
        self.output_folder_path_display = QLabel(self.output_folder_path or "(не выбрана)")
        self.output_folder_path_display.setToolTip("Полный путь к папке, куда будет сгенерирована структура")
        self.output_folder_path_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.output_folder_button = QPushButton("Выбрать...")
        self.output_folder_button.setToolTip("Открыть диалог выбора папки для вывода результатов")
        self.output_folder_button.clicked.connect(self.on_select_output_folder)

        input_panel_grid.addWidget(self.output_folder_label, 1, 0)
        input_panel_grid.addWidget(self.output_folder_path_display, 1, 1)
        input_panel_grid.addWidget(self.output_folder_button, 1, 2)
        
        input_panel_grid.setColumnStretch(1, 1)

        main_buttons_layout = QHBoxLayout()
        main_layout.addLayout(main_buttons_layout)

        self.ai_generate_button = QPushButton("AI-генерация")
        self.ai_generate_button.setToolTip("Сгенерировать черновик структуры с помощью AI (Gemini)")
        self.ai_generate_button.clicked.connect(self.on_ai_generate_clicked)
        self.accept_button = QPushButton("Принять")
        self.accept_button.setToolTip("Принять текущий черновик структуры")
        self.accept_button.clicked.connect(self.on_accept_clicked)
        self.cancel_button = QPushButton("Отменить")
        self.cancel_button.setToolTip("Отменить черновик и вернуться к последней принятой структуре (если есть)")
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        
        main_buttons_layout.addWidget(self.ai_generate_button)
        main_buttons_layout.addWidget(self.accept_button)
        main_buttons_layout.addWidget(self.cancel_button)
        main_buttons_layout.addStretch(1)

        self.edit_button = QPushButton("Редактировать")
        self.edit_button.setToolTip("Переключиться в режим ручного редактирования структуры в текстовом виде")
        self.edit_button.clicked.connect(self.on_edit_toggle_clicked)
        self.update_req_button = QPushButton("Обновить requirements")
        self.update_req_button.setToolTip("Проанализировать .py файлы в папке вывода и обновить/создать requirements.txt")
        self.update_req_button.clicked.connect(self.on_update_requirements_clicked)

        main_buttons_layout.addWidget(self.edit_button)
        main_buttons_layout.addWidget(self.update_req_button)

        self.generate_folders_button = QPushButton("⚡ Сгенерировать каталоги на диске")
        self.generate_folders_button.setToolTip("Создать папки и пустые файлы на диске на основе принятой структуры")
        font_gen_btn = self.generate_folders_button.font()
        font_gen_btn.setPointSize(font_gen_btn.pointSize() + 2)
        font_gen_btn.setBold(True)
        self.generate_folders_button.setFont(font_gen_btn)
        self.generate_folders_button.setStyleSheet("padding: 6px; background-color: #D0E0F0;")
        self.generate_folders_button.clicked.connect(self.on_generate_folders_clicked)
        main_layout.addWidget(self.generate_folders_button)

        self.splitter_widget = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter_widget, 1)

        self.left_panel_container = QWidget()
        self.left_panel_layout = QVBoxLayout(self.left_panel_container)
        self.left_panel_layout.setContentsMargins(0,0,0,0)

        self.tree_view_widget = QTreeView()
        self.tree_model = QStandardItemModel()
        self.tree_view_widget.setModel(self.tree_model)
        self.tree_view_widget.setHeaderHidden(True)
        self.tree_view_widget.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.left_panel_layout.addWidget(self.tree_view_widget)

        self.ascii_editor_widget = QPlainTextEdit()
        ascii_font_family = self.config.get("ascii_editor_font_family", "Courier New")
        ascii_font_size = self.config.get("ascii_editor_font_size", 10)
        ascii_font = QFont(ascii_font_family, ascii_font_size)
        if not QFont(ascii_font).exactMatch(): ascii_font = QFont("Monospace", ascii_font_size)
        self.ascii_editor_widget.setFont(ascii_font)
        self.ascii_editor_widget.setVisible(False)
        default_ascii = self.config.get('default_ascii_template', 'MyProject/\n└── main.py')
        self.ascii_editor_widget.setPlaceholderText(
            f"Вставьте или отредактируйте ASCII-дерево здесь...\nПример:\n{default_ascii}"
        )
        self.left_panel_layout.addWidget(self.ascii_editor_widget)
        
        self.splitter_widget.addWidget(self.left_panel_container)

        self.error_highlight_timer = QTimer(self)
        self.error_highlight_timer.setSingleShot(True)
        self.error_highlight_timer.timeout.connect(self._clear_editor_error_highlight)

        self.log_view_widget = QTextEdit()
        self.log_view_widget.setReadOnly(True)
        log_font_family = self.config.get("log_font_family", "Consolas")
        log_font_size = self.config.get("log_font_size", 9)
        log_font = QFont(log_font_family, log_font_size)
        if not QFont(log_font).exactMatch(): log_font = QFont("Monospace", log_font_size)
        self.log_view_widget.setFont(log_font)
        self.splitter_widget.addWidget(self.log_view_widget)

        splitter_state_bytes = self.settings.value("window/splitter_state")
        if splitter_state_bytes and isinstance(splitter_state_bytes, (bytes, bytearray)):
            self.splitter_widget.restoreState(splitter_state_bytes)
        else:
            self.splitter_widget.setSizes([600, 300])

        logger.debug("UI initialization complete.")

    def _populate_tree_view(self, structure_data: dict | None, is_draft: bool = False) -> None:
        """
        Заполняет виджет QTreeView данными из словаря `structure_data`.

        Args:
            structure_data (dict | None): Словарь, описывающий структуру проекта.
            is_draft (bool, optional): Если True, элементы дерева будут отображаться
                                       специальным цветом. По умолчанию False.
        """
        self.tree_model.clear()
        if not structure_data:
            logger.debug("_populate_tree_view: No structure data to display, tree cleared.")
            return

        root_item_model = self.tree_model.invisibleRootItem()
        
        def add_items_recursive(parent_qt_item: QStandardItem, current_struct_item: dict) -> None:
            node_text = current_struct_item.get('name', 'UnnamedNode')
            item_type = current_struct_item.get('type', 'unknown')

            if item_type == 'directory':
                node_text += self.config.get('ascii_validation', {}).get('dir_suffix', '/')
            
            qt_item = QStandardItem(node_text)
            qt_item.setEditable(False)
            qt_item.setData(current_struct_item, Qt.ItemDataRole.UserRole + 1)
            parent_qt_item.appendRow(qt_item)

            if item_type == 'directory':
                for child_struct_item in current_struct_item.get('children', []):
                    if isinstance(child_struct_item, dict):
                        add_items_recursive(qt_item, child_struct_item)
                    else:
                        logger.warning(f"Skipping non-dictionary child item: {child_struct_item}")
        
        try:
            add_items_recursive(root_item_model, structure_data)
            self.tree_view_widget.expandAll()
            logger.debug(f"Tree view populated with root: '{structure_data.get('name')}', is_draft: {is_draft}")
        except Exception as e:
            logger.error(f"Error populating tree view: {e}", exc_info=True)
            self._log_to_ui(f"Ошибка отображения структуры в дереве: {e}", "ERROR")
            self.tree_model.clear()


    def update_ui_for_state(self) -> None:
        """
        Обновляет состояние всех интерактивных элементов GUI.
        """
        is_initial = self.current_app_state == APP_STATE_INITIAL
        is_accepted = self.current_app_state == APP_STATE_ACCEPTED
        is_draft = self.current_app_state == APP_STATE_DRAFT
        is_editing_ascii = self.current_edit_mode == EDIT_MODE_ASCII

        ai_task_active = bool(self.ai_worker and self.ai_worker.isRunning())
        req_scan_task_active = bool(self.req_scan_worker and self.req_scan_worker.isRunning())
        any_long_task_active = ai_task_active or req_scan_task_active

        can_select_files = not any_long_task_active
        self.condition_file_button.setEnabled(can_select_files)
        self.output_folder_button.setEnabled(can_select_files)

        self.ai_generate_button.setEnabled(
            not is_editing_ascii and 
            bool(self.condition_file_path) and 
            bool(self.ai_client and self.ai_client.model) and
            not any_long_task_active
        )
        self.ai_generate_button.setText("AI-генерация..." if ai_task_active else "AI-генерация")

        self.accept_button.setEnabled(is_draft and not is_editing_ascii and not any_long_task_active)
        self.cancel_button.setEnabled(is_draft and not is_editing_ascii and not any_long_task_active)

        can_start_edit = (is_accepted or is_draft) and not any_long_task_active
        self.edit_button.setEnabled(can_start_edit or (is_editing_ascii and not any_long_task_active))
        self.edit_button.setText("Завершить редакцию" if is_editing_ascii else "Редактировать")

        self.update_req_button.setEnabled(
            bool(self.output_folder_path) and 
            not is_editing_ascii and 
            not any_long_task_active
        )
        self.update_req_button.setText("Обновление req..." if req_scan_task_active else "Обновить requirements")

        self.generate_folders_button.setEnabled(
            is_accepted and 
            bool(self.accepted_structure_dict) and 
            bool(self.output_folder_path) and 
            not is_editing_ascii and
            not any_long_task_active
        )

        self.tree_view_widget.setVisible(not is_editing_ascii)
        self.ascii_editor_widget.setVisible(is_editing_ascii)

        palette = self.tree_view_widget.palette()
        if not hasattr(self, 'default_ai_button_stylesheet'):
             self.default_ai_button_stylesheet = self.ai_generate_button.styleSheet()

        if is_draft:
            palette.setColor(QPalette.ColorRole.Text, QColor("gray"))
            if self.draft_from_ai_flag:
                self.ai_generate_button.setStyleSheet("background-color: #A0D0F0; border: 1px solid #60A0D0;")
            else:
                self.ai_generate_button.setStyleSheet(self.default_ai_button_stylesheet)
        else:
            palette.setColor(QPalette.ColorRole.Text, QColor(Qt.GlobalColor.black))
            self.ai_generate_button.setStyleSheet(self.default_ai_button_stylesheet)
        
        self.tree_view_widget.setPalette(palette)

        self._log_to_ui(f"UI updated. State: {self.current_app_state}, Edit Mode: {self.current_edit_mode}, "
                        f"AI Task: {ai_task_active}, ReqScan Task: {req_scan_task_active}", "DEBUG")

    def on_select_condition_file(self) -> None:
        """ Обрабатывает нажатие кнопки выбора файла-условия. """
        last_used_dir = self.settings.value("paths/last_condition_dir", str(Path.home()), type=str)
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Выбрать файл условия лаборатории", last_used_dir,
            "Поддерживаемые файлы (*.pdf *.docx *.txt);;PDF файлы (*.pdf);;"
            "Word документы (*.docx);;Текстовые файлы (*.txt);;Все файлы (*)"
        )
        if filepath:
            self.condition_file_path = filepath
            self.condition_file_path_display.setText(Path(filepath).name)
            self.condition_file_path_display.setToolTip(filepath)
            self.settings.setValue("paths/last_condition_dir", str(Path(filepath).parent))
            self._log_to_ui(f"Выбран файл условия: {filepath}", "INFO")
            
            if self.draft_structure_dict:
                reply = QMessageBox.question(self, "Новый файл условия",
                                             "Выбран новый файл условия. Текущий черновик структуры будет сброшен. Продолжить?",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                             QMessageBox.StandardButton.Yes)
                if reply == QMessageBox.StandardButton.Yes:
                    self._reset_to_last_accepted_or_initial()
            
            self.update_ui_for_state()
        else:
            self._log_to_ui("Выбор файла условия был отменен.", "DEBUG")


    def on_select_output_folder(self) -> None:
        """ Обрабатывает нажатие кнопки выбора папки вывода. """
        current_output_path = self.output_folder_path or str(Path.home())
        folderpath = QFileDialog.getExistingDirectory(
            self, "Выбрать папку для генерации структуры", current_output_path
        )
        if folderpath:
            self.output_folder_path = folderpath
            self.output_folder_path_display.setText(folderpath)
            self.output_folder_path_display.setToolTip(folderpath)
            self.settings.setValue("paths/output_folder", folderpath)
            self._log_to_ui(f"Выбрана папка вывода: {folderpath}", "INFO")
            self.update_ui_for_state()
        else:
            self._log_to_ui("Выбор папки вывода был отменен.", "DEBUG")
            
    def _reset_to_last_accepted_or_initial(self) -> None:
        """
        Сбрасывает состояние приложения к последней принятой структуре или к начальному.
        """
        self.draft_structure_dict = None
        self.draft_from_ai_flag = False
        if self.accepted_structure_dict:
            self.current_app_state = APP_STATE_ACCEPTED
            self._populate_tree_view(self.accepted_structure_dict, is_draft=False)
            self._log_to_ui("Состояние сброшено к последней принятой структуре.", "INFO")
        else:
            self.current_app_state = APP_STATE_INITIAL
            self._populate_tree_view(None)
            self._log_to_ui("Состояние сброшено к начальному (нет принятой структуры).", "INFO")


    def on_ai_generate_clicked(self) -> None:
        """ Обрабатывает нажатие кнопки AI-генерации структуры. """
        if not self.condition_file_path:
            QMessageBox.warning(self, "Файл не выбран", "Пожалуйста, сначала выберите файл условия лаборатории.")
            return
        if not self.ai_client or not self.ai_client.model:
            QMessageBox.critical(self, "Ошибка конфигурации AI", 
                                 "Клиент AI не инициализирован или модель AI недоступна.\n"
                                 "Проверьте API ключ в файле config.json или лог ошибок приложения.\n"
                                 "AI-генерация не может быть выполнена.")
            self._log_to_ui("Попытка AI-генерации без готового AI клиента или модели.", "ERROR")
            return

        self._log_to_ui(f"Чтение файла условия '{Path(self.condition_file_path).name}' для AI...", "INFO")
        file_content_text = parse_condition_file(self.condition_file_path)
        
        if file_content_text is None or file_content_text.startswith("Error:"):
            error_msg = file_content_text if file_content_text else "Неизвестная ошибка чтения файла."
            QMessageBox.critical(self, "Ошибка чтения файла", 
                                 f"Не удалось прочитать или обработать файл условия:\n'{Path(self.condition_file_path).name}'\n\n{error_msg}")
            self._log_to_ui(f"Ошибка чтения файла условия для AI: {Path(self.condition_file_path).name}. Детали: {error_msg}", "ERROR")
            return

        self._log_to_ui("Запуск AI-генерации структуры проекта...", "INFO")
        user_query_for_ai = ""

        self.ai_worker = AIWorker(self.ai_client, file_content_text, user_query_for_ai)
        self.ai_worker.finished_signal.connect(self._handle_ai_success)
        self.ai_worker.error_signal.connect(self._handle_ai_error)
        self.ai_worker.started.connect(lambda: self._log_to_ui("Поток AI-генерации запущен.", "DEBUG"))
        self.ai_worker.finished.connect(lambda: self._log_to_ui("Поток AI-генерации завершил работу.", "DEBUG"))
        self.ai_worker.start()
        
        self.update_ui_for_state()

    def _handle_ai_success(self, suggested_structure: dict | None) -> None:
        """
        Обрабатывает успешное получение структуры от AIWorker.
        
        Args:
            suggested_structure (dict | None): Предложенная структура или None.
        """
        if suggested_structure and isinstance(suggested_structure, dict):
            self.draft_structure_dict = suggested_structure
            self.draft_from_ai_flag = True
            self.current_app_state = APP_STATE_DRAFT
            self._populate_tree_view(self.draft_structure_dict, is_draft=True)
            self._log_to_ui("AI успешно сгенерировал черновик структуры проекта.", "INFO")
        else:
            self._log_to_ui("AI не вернул валидную структуру. Черновик не обновлен.", "WARNING")
        
        self.ai_worker = None
        self.update_ui_for_state()

    def _handle_ai_error(self, error_message: str) -> None:
        """
        Обрабатывает ошибку, полученную от AIWorker.

        Args:
            error_message (str): Текст сообщения об ошибке.
        """
        QMessageBox.critical(self, "Ошибка AI-генерации", 
                             f"Во время AI-генерации произошла ошибка:\n{error_message}")
        self._log_to_ui(f"Ошибка AI-генерации: {error_message}", "ERROR")
        self.ai_worker = None
        self.update_ui_for_state()

    def on_accept_clicked(self) -> None:
        """ Обрабатывает нажатие кнопки "Принять" для черновика структуры. """
        if self.current_app_state == APP_STATE_DRAFT and self.draft_structure_dict:
            self.accepted_structure_dict = self.draft_structure_dict
            self.draft_structure_dict = None
            self.draft_from_ai_flag = False
            self.current_app_state = APP_STATE_ACCEPTED
            self._populate_tree_view(self.accepted_structure_dict, is_draft=False)
            self._log_to_ui("Черновик структуры успешно принят.", "INFO")
        else:
            self._log_to_ui("Нет активного черновика для принятия.", "WARNING")
        self.update_ui_for_state()

    def on_cancel_clicked(self) -> None:
        """ Обрабатывает нажатие кнопки "Отменить" для черновика структуры. """
        if self.current_app_state == APP_STATE_DRAFT:
            self._reset_to_last_accepted_or_initial()
            self._log_to_ui("Черновик структуры отменен. Восстановлено предыдущее состояние.", "INFO")
        else:
            self._log_to_ui("Нет активного черновика для отмены.", "DEBUG")
        self.update_ui_for_state()

    def on_edit_toggle_clicked(self) -> None:
        """
        Обрабатывает нажатие кнопки "Редактировать" / "Завершить редакцию".
        """
        if self.current_edit_mode == EDIT_MODE_TREE:
            structure_to_display_in_ascii = self.draft_structure_dict if self.draft_structure_dict else self.accepted_structure_dict
            
            ascii_text_to_edit = ""
            if structure_to_display_in_ascii:
                try:
                    ascii_text_to_edit = structure_to_ascii(structure_to_display_in_ascii, self.config)
                except Exception as e:
                    logger.error(f"Ошибка конвертации структуры в ASCII: {e}", exc_info=True)
                    QMessageBox.critical(self, "Ошибка конвертации", f"Не удалось преобразовать структуру в ASCII: {e}")
                    return
            else:
                ascii_text_to_edit = self.config.get("default_ascii_template", "MyProject/\n└── main.py")
            
            self.ascii_editor_widget.setPlainText(ascii_text_to_edit)
            self.current_edit_mode = EDIT_MODE_ASCII
            self._clear_editor_error_highlight()
            self.ascii_editor_widget.setFocus()
            self._log_to_ui("Переход в режим редактирования структуры ASCII.", "INFO")

        elif self.current_edit_mode == EDIT_MODE_ASCII:
            ascii_text_from_editor = self.ascii_editor_widget.toPlainText()
            
            validation_errors = validate_ascii_tree(ascii_text_from_editor, self.config)
            if validation_errors:
                self._show_editor_error_highlight()
                error_msg_display = "\n".join(validation_errors[:5])
                if len(validation_errors) > 5:
                    error_msg_display += f"\n... и еще {len(validation_errors) - 5} ошибок."
                QMessageBox.warning(self, "Ошибка валидации ASCII-структуры",
                                    f"Обнаружены ошибки в формате введенной ASCII-структуры:\n{error_msg_display}")
                self._log_to_ui(f"Ошибки валидации ASCII-структуры: {validation_errors}", "ERROR")
                return

            try:
                parsed_structure_from_ascii = ascii_to_structure(ascii_text_from_editor, self.config)
            except Exception as e:
                logger.error(f"Критическая ошибка при парсинге ASCII-структуры: {e}", exc_info=True)
                QMessageBox.critical(self, "Ошибка парсинга ASCII", f"Произошла критическая ошибка при парсинге ASCII: {e}")
                self._show_editor_error_highlight()
                return

            if parsed_structure_from_ascii:
                self.draft_structure_dict = parsed_structure_from_ascii
                self.draft_from_ai_flag = False
                self.current_app_state = APP_STATE_DRAFT
                self.current_edit_mode = EDIT_MODE_TREE
                self._populate_tree_view(self.draft_structure_dict, is_draft=True)
                self._log_to_ui("Структура из ASCII-редактора успешно принята как черновик.", "INFO")
            else:
                if not ascii_text_from_editor.strip():
                    self.draft_structure_dict = None 
                    self.draft_from_ai_flag = False
                    self.current_app_state = APP_STATE_DRAFT
                    self.current_edit_mode = EDIT_MODE_TREE
                    self._populate_tree_view(None, is_draft=True)
                    self._log_to_ui("Пустое ASCII-дерево принято как пустой черновик.", "INFO")
                else:
                    msg = ("Не удалось преобразовать ASCII-текст в структуру после валидации. "
                           "Это неожиданная ситуация, пожалуйста, проверьте лог приложения.")
                    QMessageBox.critical(self, "Ошибка конвертации ASCII", msg)
                    self._log_to_ui(msg + f" Текст: '{ascii_text_from_editor[:100]}...'", "ERROR")
                    self._show_editor_error_highlight()
                    return
        
        self.update_ui_for_state()

    def _show_editor_error_highlight(self) -> None:
        """ Включает визуальную подсветку ошибки для ASCII-редактора. """
        error_style = "border: 1.5px solid red; background-color: #FFF0F0;"
        self.ascii_editor_widget.setStyleSheet(error_style)
        highlight_duration_ms = self.config.get("highlight_error_duration_ms", 1000)
        self.error_highlight_timer.start(highlight_duration_ms)
        self._log_to_ui("Визуальная подсветка ошибки для ASCII-редактора активирована.", "DEBUG")

    def _clear_editor_error_highlight(self) -> None:
        """ Снимает подсветку ошибки с ASCII-редактора. """
        self.ascii_editor_widget.setStyleSheet("")
        self._log_to_ui("Подсветка ошибки ASCII-редактора снята.", "DEBUG")

    def on_update_requirements_clicked(self) -> None:
        """ Обрабатывает нажатие кнопки "Обновить requirements.txt". """
        if not self.output_folder_path:
            QMessageBox.warning(self, "Папка не указана", "Пожалуйста, сначала выберите папку вывода.")
            return
        if not Path(self.output_folder_path).is_dir():
            QMessageBox.warning(self, "Папка не найдена", 
                                f"Указанная папка вывода '{self.output_folder_path}' не существует или не является директорией.")
            return

        self._log_to_ui(f"Запуск сканирования .py файлов для requirements.txt в '{self.output_folder_path}'...", "INFO")
        
        self.req_scan_worker = ReqScanWorker(self.output_folder_path)
        self.req_scan_worker.finished_signal.connect(self._handle_req_scan_success)
        self.req_scan_worker.error_signal.connect(self._handle_req_scan_error)
        self.req_scan_worker.started.connect(lambda: self._log_to_ui("Поток сканирования зависимостей запущен.", "DEBUG"))
        self.req_scan_worker.finished.connect(lambda: self._log_to_ui("Поток сканирования зависимостей завершил работу.", "DEBUG"))
        self.req_scan_worker.start()

        self.update_ui_for_state()

    def _handle_req_scan_success(self, scanned_imports: set) -> None:
        """
        Обрабатывает успешное завершение сканирования импортов.

        Args:
            scanned_imports (set): Множество строк с именами импортированных модулей.
        """
        self.req_scan_worker = None
        
        if not scanned_imports:
            self._log_to_ui("Не найдено внешних зависимостей для `requirements.txt`.", "INFO")
            QMessageBox.information(self, "Обновление requirements.txt", 
                                    "Не найдено внешних зависимостей для добавления в `requirements.txt`.")
            self.update_ui_for_state()
            return

        try:
            new_req_content = generate_requirements_content(scanned_imports, self.output_folder_path)
        except Exception as e:
            logger.error(f"Ошибка при генерации содержимого requirements.txt: {e}", exc_info=True)
            QMessageBox.critical(self, "Ошибка генерации requirements", f"Не удалось сформировать список зависимостей: {e}")
            self.update_ui_for_state()
            return

        req_file_path = Path(self.output_folder_path) / "requirements.txt"
        
        old_req_content = ""
        if req_file_path.is_file():
            try:
                with open(req_file_path, "r", encoding="utf-8") as f:
                    old_req_content = f.read().strip()
            except IOError as e:
                self._log_to_ui(f"Ошибка чтения существующего файла requirements.txt: {e}", "ERROR")
                QMessageBox.warning(self, "Ошибка чтения файла", 
                                    f"Не удалось прочитать существующий файл requirements.txt:\n{e}\n"
                                    "Он будет перезаписан, если вы согласитесь.")
        
        if old_req_content == new_req_content.strip():
            self._log_to_ui("Файл requirements.txt не требует обновления.", "INFO")
            QMessageBox.information(self, "Обновление requirements.txt", "Файл requirements.txt уже актуален.")
        else:
            diff_lines = list(difflib.unified_diff(
                old_req_content.splitlines(keepends=True),
                new_req_content.splitlines(keepends=True),
                fromfile='Текущий requirements.txt',
                tofile='Новый requirements.txt (предлагаемый)',
                lineterm=''
            ))
            
            diff_text_for_dialog = "".join(diff_lines)
            if not diff_text_for_dialog and old_req_content != new_req_content.strip():
                diff_text_for_dialog = (f"--- Текущий requirements.txt:\n{old_req_content or '(пусто)'}\n\n"
                                        f"+++ Новый requirements.txt:\n{new_req_content or '(пусто)'}")

            MAX_DIFF_DISPLAY_LEN = 1500 
            if len(diff_text_for_dialog) > MAX_DIFF_DISPLAY_LEN:
                diff_text_for_dialog = diff_text_for_dialog[:MAX_DIFF_DISPLAY_LEN] + \
                                       "\n\n[...Diff слишком большой для полного отображения...]"

            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle("Обновить файл requirements.txt?")
            msg_box.setText(f"Обнаружены изменения для файла `requirements.txt` в папке:\n'{self.output_folder_path}'.\n\n"
                            "Хотите обновить файл на диске?")
            msg_box.setDetailedText(diff_text_for_dialog)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
            reply = msg_box.exec()

            if reply == QMessageBox.StandardButton.Yes:
                try:
                    with open(req_file_path, "w", encoding="utf-8") as f:
                        f.write(new_req_content + ("\n" if new_req_content else ""))
                    self._log_to_ui(f"Файл requirements.txt успешно обновлен: {req_file_path}", "INFO")
                    QMessageBox.information(self, "Успех", f"Файл requirements.txt успешно обновлен:\n'{req_file_path}'.")
                except IOError as e:
                    QMessageBox.critical(self, "Ошибка записи файла", f"Не удалось записать файл requirements.txt: {e}")
                    self._log_to_ui(f"Ошибка записи файла requirements.txt ({req_file_path}): {e}", "ERROR")
            else:
                self._log_to_ui("Обновление файла requirements.txt отменено пользователем.", "INFO")
        
        self.update_ui_for_state()

    def _handle_req_scan_error(self, error_message: str) -> None:
        """ Обрабатывает ошибку, полученную от ReqScanWorker. """
        QMessageBox.critical(self, "Ошибка сканирования зависимостей", 
                             f"Во время сканирования файлов на импорты произошла ошибка:\n{error_message}")
        self._log_to_ui(f"Ошибка сканирования Python импортов: {error_message}", "ERROR")
        self.req_scan_worker = None
        self.update_ui_for_state()

    def on_generate_folders_clicked(self) -> None:
        """
        Обрабатывает нажатие кнопки "Сгенерировать каталоги на диске".
        """
        if not self.accepted_structure_dict:
            QMessageBox.warning(self, "Нет принятой структуры", 
                                "Сначала необходимо принять структуру проекта.")
            return
        if not self.output_folder_path:
            QMessageBox.warning(self, "Папка вывода не указана", "Пожалуйста, выберите папку для генерации структуры.")
            return
        
        output_path_obj = Path(self.output_folder_path)
        warning_msg = ""
        if not output_path_obj.exists():
            warning_msg = f"Папка вывода '{self.output_folder_path}' не существует и будет создана.\n"
        elif not output_path_obj.is_dir():
            QMessageBox.critical(self, "Ошибка папки вывода", 
                                 f"Указанный путь для вывода '{self.output_folder_path}' существует, но не является папкой.")
            return
        
        project_root_name_on_disk = self.accepted_structure_dict.get('name', 'UnknownProject')
        project_root_on_disk_path = output_path_obj / project_root_name_on_disk
        overwrite_warning = ""
        if project_root_on_disk_path.exists():
            overwrite_warning = (f"\n\nВНИМАНИЕ: Элемент '{project_root_name_on_disk}' "
                                 f"уже существует в '{self.output_folder_path}'.\n"
                                 "Существующие файлы не будут удалены, но могут быть созданы новые.")
        
        reply = QMessageBox.question(self, "Подтверждение генерации структуры",
                                     f"{warning_msg}Сгенерировать структуру проекта "
                                     f"в '{self.output_folder_path}'?"
                                     f"{overwrite_warning}",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No:
            self._log_to_ui("Генерация каталогов на диске отменена пользователем.", "INFO")
            return

        self._log_to_ui(f"Начало генерации файловой структуры в '{self.output_folder_path}'...", "INFO")
        try:
            generated_paths_list = generate_folder_structure(self.accepted_structure_dict, self.output_folder_path)
            if generated_paths_list is not None:
                count = len(generated_paths_list)
                self._log_to_ui(f"Файловая структура успешно сгенерирована. Элементов: {count}.", "INFO")
                QMessageBox.information(self, "Генерация завершена", 
                                        f"Структура проекта ({count} эл.) сгенерирована в '{self.output_folder_path}'.")
            else:
                QMessageBox.critical(self, "Ошибка генерации структуры", 
                                     "При генерации файловой структуры произошла ошибка. Проверьте лог и права доступа.")
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при вызове generate_folder_structure: {e}", exc_info=True)
            QMessageBox.critical(self, "Критическая ошибка генерации", f"Произошла непредвиденная ошибка: {e}")
            self._log_to_ui(f"Критическая ошибка при генерации каталогов: {e}", "CRITICAL")
        
        self.update_ui_for_state()


    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Обрабатывает событие закрытия главного окна.

        Args:
            event (QCloseEvent): Событие закрытия окна.
        """
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/splitter_state", self.splitter_widget.saveState())
        
        if self.condition_file_path:
             self.settings.setValue("paths/last_condition_dir", str(Path(self.condition_file_path).parent))

        if self.current_app_state == APP_STATE_DRAFT and self.draft_structure_dict:
            reply = QMessageBox.question(self, 'Подтверждение выхода',
                                       "Имеется непринятый черновик структуры.\n"
                                       "Несохраненные изменения будут утеряны.\n\n"
                                       "Выйти из приложения?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self._log_to_ui("Приложение закрывается (непринятый черновик отброшен).", "INFO")
                event.accept()
            else:
                self._log_to_ui("Выход из приложения отменен пользователем.", "INFO")
                event.ignore()
        else:
            self._log_to_ui("Приложение закрывается.", "INFO")
            event.accept()


def load_config(config_path_str: str = "config.json") -> dict:
    """
    Загружает конфигурацию приложения из JSON-файла.

    Args:
        config_path_str (str, optional): Путь к файлу конфигурации. По умолчанию "config.json".

    Returns:
        dict: Словарь с настройками приложения.
    """
    config_path = Path(config_path_str)
    default_config = {
        "gemini_api_key": "YOUR_GEMINI_API_KEY_HERE_OR_LEAVE_EMPTY_FOR_USER_INPUT",
        "default_output_folder": str(Path.home() / "LabFolderGenerator_Output"),
        "ai_prompt_template": (
            "Выполни следующий алгоритм действий\n"
            "Проанализируй вложенный файл-условие и пользовательский запрос:\n"
            "{user_query}\n"
            "Выдели из анализа только грубую структуру директорий и названия файлов.\n"
            "После уточни нейминг директорий/файлов и добавь пустые файлы по необходимости.\n"
            "Ответ ожидается в JSON-формате с древовидной структурой. Каждый узел должен иметь 'name' (строка) и 'type' ('directory' или 'file'). "
            "Директории могут иметь поле 'children' (список узлов).\n\n"
            "Содержимое файла-условия:\n{file_content}"
        ),
        "log_file_path": "lab_folder_generator_app.log",
        "log_level": "INFO",
        "app_name": "LabFolder Generator",
        "version": "0.3.0",
        "ascii_validation": {
            "indent_char": " ", "indent_size": 4, 
            "branch_prefix": "├── ", "last_branch_prefix": "└── ",
            "pipe_prefix": "│   ", "space_prefix": "    ",
            "dir_suffix": "/",
            "valid_prefix_chars": ["├", "─", "└", "│", " "]
        },
        "highlight_error_duration_ms": 1500,
        "default_ascii_template": "MyNewProject/\n├── src/\n│   └── main.py\n└── README.md",
        "ascii_editor_font_family": "Courier New",
        "ascii_editor_font_size": 10,
        "log_font_family": "Consolas",
        "log_font_size": 9
    }
    
    if not config_path.is_file():
        temp_logger = logging.getLogger("config_loader") # Используем отдельный логгер для этапа загрузки конфига
        temp_logger.warning(f"Файл конфигурации '{config_path}' не найден. Создание файла с настройками по умолчанию.")
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            temp_logger.info(f"Файл конфигурации по умолчанию создан: '{config_path}'")
            return default_config
        except IOError as e:
            temp_logger.error(f"Не удалось создать файл конфигурации '{config_path}': {e}. Используются встроенные настройки.")
            return default_config

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            loaded_config_raw = json.load(f)
        
        final_config = default_config.copy()
        
        def recursive_update(target: dict, source: dict) -> None:
            for key, value in source.items():
                if isinstance(value, dict) and isinstance(target.get(key), dict):
                    recursive_update(target[key], value)
                elif key in target: # Обновляем только если ключ существует в default_config
                    target[key] = value
        
        recursive_update(final_config, loaded_config_raw)
        logging.getLogger("config_loader").info(f"Конфигурация успешно загружена и объединена из '{config_path}'.")
        return final_config
            
    except json.JSONDecodeError as e:
        logging.getLogger("config_loader").error(f"Ошибка декодирования JSON из '{config_path}': {e}. Используются настройки по умолчанию.", exc_info=True)
        return default_config
    except IOError as e:
        logging.getLogger("config_loader").error(f"Ошибка чтения файла конфигурации '{config_path}': {e}. Используются настройки по умолчанию.", exc_info=True)
        return default_config


def main() -> None:
    """
    Главная функция для запуска приложения LabFolder Generator.
    """
    QApplication.setOrganizationName("MyCompany")
    QApplication.setApplicationName("LabFolderGenerator")

    app = QApplication(sys.argv)
    
    config = load_config("config.json")

    log_level_str = config.get("log_level", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    logging.basicConfig(level=log_level, format=log_format, stream=sys.stdout)

    if config.get("log_file_path"):
        log_file_path_obj = Path(config["log_file_path"])
        try:
            log_file_path_obj.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file_path_obj, encoding='utf-8', mode='a')
            file_formatter = logging.Formatter(log_format)
            file_handler.setFormatter(file_formatter)
            logging.getLogger().addHandler(file_handler)
            logging.info(f"Логирование в файл '{log_file_path_obj}' настроено (уровень: {log_level_str}).")
        except Exception as e:
            print(f"ERROR: Не удалось настроить логирование в файл '{log_file_path_obj}': {e}", file=sys.stderr)
            logging.error(f"Не удалось настроить логирование в файл '{log_file_path_obj}': {e}", exc_info=True)

    logging.info(f"Приложение '{config.get('app_name')}' запускается...")
    
    main_win = MainWindow(config)
    main_win.show()
    
    exit_code = app.exec()
    logging.info(f"Приложение '{config.get('app_name')}' завершило работу с кодом выхода: {exit_code}.")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()