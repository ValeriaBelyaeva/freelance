# core_logic.py
import os
import ast
import sys
from pathlib import Path
import logging

# Попытка импорта опциональных библиотек для парсинга
try:
    import PyPDF2
    # Дополнительная проверка на версию, если известны проблемы совместимости
except ImportError:
    PyPDF2 = None # type: ignore[assignment] # Mypy может ругаться на переопределение
    logging.getLogger(__name__).info("PyPDF2 not installed. PDF parsing will be unavailable.")

try:
    import docx # python-docx
except ImportError:
    docx = None # type: ignore[assignment]
    logging.getLogger(__name__).info("python-docx not installed. DOCX parsing will be unavailable.")

try:
    from stdlib_list import stdlib_list as get_stdlib_list_for_version
except ImportError:
    get_stdlib_list_for_version = None # type: ignore[assignment]
    logging.getLogger(__name__).warning(
        "Package 'stdlib_list' not installed. Standard library module detection might be incomplete."
    )

logger = logging.getLogger(__name__)

# --- Парсинг файлов условий ---
def parse_condition_file(filepath: str) -> str | None:
    """
    Извлекает текстовое содержимое из файла условия.
    Поддерживаемые форматы: .pdf, .docx, .txt.

    Args:
        filepath (str): Путь к файлу условия.

    Returns:
        str | None: Извлеченный текст в виде единой строки (абзацы разделены '\\n')
                    или None, если файл не найден, не поддерживается или произошла ошибка парсинга.
                    В случае ошибки парсинга из-за отсутствия библиотеки, возвращает строку с сообщением об ошибке.
    """
    path_obj = Path(filepath)
    file_ext = path_obj.suffix.lower()
    text_content: str | None = None

    if not path_obj.is_file():
        logger.error(f"File not found for parsing: {filepath}")
        return None

    try:
        if file_ext == ".txt":
            with open(filepath, 'r', encoding='utf-8') as f:
                text_content = f.read()
        elif file_ext == ".pdf":
            if PyPDF2:
                reader = PyPDF2.PdfReader(filepath)
                text_parts = [page.extract_text() for page in reader.pages if page.extract_text()]
                text_content = "\n".join(text_parts)
                if not text_content:
                    logger.warning(f"PyPDF2 could not extract text from PDF: {filepath}. "
                                   "It might be an image-based PDF or empty.")
            else:
                logger.warning("PyPDF2 is not installed. Cannot parse PDF file: {filepath}")
                return "Error: PyPDF2 library not available for PDF parsing."
        elif file_ext == ".docx":
            if docx:
                document = docx.Document(filepath)
                text_content = "\n".join([para.text for para in document.paragraphs if para.text.strip()])
                if not text_content:
                     logger.warning(f"python-docx could not extract text from DOCX: {filepath}. "
                                    "It might be empty or structured unusually.")
            else:
                logger.warning("python-docx is not installed. Cannot parse DOCX file: {filepath}")
                return "Error: python-docx library not available for DOCX parsing."
        else:
            logger.warning(f"Unsupported file type for parsing: {file_ext} for file {filepath}")
            return f"Error: Unsupported file type '{file_ext}'."

        if text_content is not None:
             logger.info(f"Successfully parsed file: {filepath}, extracted approx. {len(text_content)} chars.")
        return text_content

    except PyPDF2.errors.PdfReadError as e: # Специфичная ошибка для PyPDF2
        logger.error(f"Error reading PDF file {filepath} with PyPDF2: {e}")
        return f"Error: Could not read PDF file '{Path(filepath).name}'. It may be corrupted or password-protected."
    except Exception as e:
        logger.error(f"Error parsing file {filepath} (ext: {file_ext}): {e}", exc_info=True)
        return f"Error: An unexpected error occurred while parsing '{Path(filepath).name}'."


# --- Генерация структуры каталогов и файлов на диске ---
def _create_recursive(item: dict, current_path_obj: Path, generated_paths: list[str]) -> None:
    """
    Вспомогательная рекурсивная функция для создания элементов файловой структуры.
    Создает директории и пустые файлы.

    Args:
        item (dict): Словарь, описывающий текущий элемент (файл или директорию).
                     Ожидаемые ключи: 'name' (str), 'type' ('directory'|'file'),
                     'children' (list[dict], опционально для директорий).
        current_path_obj (Path): Объект Path, представляющий родительскую директорию
                                 для текущего элемента.
        generated_paths (list[str]): Список, в который добавляются пути к созданным
                                     элементам (для отчетности).

    Raises:
        OSError: Если возникает ошибка при создании файла или директории (например, нет прав).
    """
    item_name = item.get('name')
    item_type = item.get('type')

    if not item_name or not item_type:
        logger.warning(f"Skipping item with missing 'name' or 'type': {item} under {current_path_obj}")
        return

    invalid_os_chars = r'<>:"/\|?*' # Базовый набор для Windows
    if any(char in item_name for char in invalid_os_chars) or item_name == "." or item_name == "..":
        logger.error(f"Invalid characters or reserved name in item '{item_name}' "
                       f"for type '{item_type}' at {current_path_obj}. Skipping.")
        return

    item_path = current_path_obj / item_name
    try:
        if item_type == 'directory':
            item_path.mkdir(parents=True, exist_ok=True)
            generated_paths.append(str(item_path))
            logger.debug(f"Created/Ensured directory: {item_path}")
            for child in item.get('children', []):
                if not isinstance(child, dict):
                    logger.warning(f"Child item is not a dictionary, skipping: {child} under {item_path}")
                    continue
                _create_recursive(child, item_path, generated_paths)
        elif item_type == 'file':
            item_path.parent.mkdir(parents=True, exist_ok=True) # Гарантируем наличие родительской папки
            item_path.touch(exist_ok=True)
            generated_paths.append(str(item_path))
            logger.debug(f"Created/Ensured file: {item_path}")
        else:
            logger.warning(f"Unknown item type: '{item_type}' for item '{item_name}' at {item_path}")
    except OSError as e:
        logger.error(f"OS error creating '{item_path}': {e}")
        raise # Пробрасываем выше для централизованной обработки в generate_folder_structure


def generate_folder_structure(structure_data: dict, output_path_str: str) -> list[str] | None:
    """
    Генерирует файловую структуру (папки и пустые файлы) на диске.

    Структура задается словарем, где корневой элемент описывает проект.
    Пример `structure_data`: `{"name": "MyProject", "type": "directory", "children": [...]}`.
    Проект `MyProject` будет создан внутри `output_path_str`.

    Args:
        structure_data (dict): Иерархический словарь, описывающий структуру проекта.
        output_path_str (str): Путь к корневой директории, внутри которой будет
                               создана структура проекта.

    Returns:
        list[str] | None: Список абсолютных путей к созданным/обновленным элементам
                          файловой системы. None в случае критической ошибки
                          (например, невалидные входные данные, ошибка доступа к `output_path_str`).
    """
    output_path = Path(output_path_str)
    if not structure_data or not isinstance(structure_data, dict) or \
       'name' not in structure_data or 'type' not in structure_data:
        logger.error(f"Invalid or empty structure_data provided for generation: {structure_data}")
        return None

    try: # Гарантируем, что базовая папка вывода существует
        output_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to create or access base output directory '{output_path}': {e}")
        return None

    generated_items: list[str] = []
    project_root_name = structure_data['name']
    project_root_type = structure_data['type']
    
    invalid_os_chars = r'<>:"/\|?*'
    if any(char in project_root_name for char in invalid_os_chars) or project_root_name in (".", ".."):
        logger.error(f"Invalid characters or reserved name in project root name '{project_root_name}'. Cannot generate structure.")
        return None

    project_actual_root_path = output_path / project_root_name

    try:
        if project_root_type == 'directory':
            project_actual_root_path.mkdir(parents=True, exist_ok=True)
            generated_items.append(str(project_actual_root_path))
            logger.info(f"Created/Ensured root directory: {project_actual_root_path}")
            for child in structure_data.get('children', []):
                if not isinstance(child, dict): # Доп. проверка
                    logger.warning(f"Child item of root is not a dictionary, skipping: {child}")
                    continue
                _create_recursive(child, project_actual_root_path, generated_items)
        elif project_root_type == 'file':
            project_actual_root_path.touch(exist_ok=True) # Родительская (output_path) уже проверена
            generated_items.append(str(project_actual_root_path))
            logger.info(f"Created/Ensured root file: {project_actual_root_path}")
        else:
            logger.error(f"Invalid root item type: '{project_root_type}' for '{project_root_name}'")
            return None

        logger.info(f"Folder structure generation completed. {len(generated_items)} items processed in '{output_path_str}'.")
        return generated_items
    except OSError as e:
        logger.error(f"Failed to generate folder structure at '{output_path}' due to OS error: {e}", exc_info=True)
        return None
    except Exception as e: # Непредвиденные ошибки
        logger.error(f"Unexpected error during folder generation in '{output_path_str}': {e}", exc_info=True)
        return None


# --- Обработка ASCII-дерева ---
def _parse_ascii_line_detailed(line: str, config: dict) -> tuple[int, str, bool, str | None]:
    """
    Детально парсит одну строку ASCII-представления дерева файлов.

    Извлекает начальный отступ, имя элемента, его тип (папка/файл) и проверяет
    на базовые ошибки формата и именования.

    Args:
        line (str): Строка из ASCII-дерева.
        config (dict): Словарь конфигурации приложения, содержащий секцию `ascii_validation`
                       с параметрами парсинга (indent_char, indent_size, dir_suffix и т.д.).

    Returns:
        tuple[int, str, bool, str | None]: Кортеж:
            - int: Длина начального отступа в символах `indent_char`.
            - str: "Чистое" имя элемента (без префиксов и суффикса папки).
            - bool: True, если элемент является директорией, иначе False.
            - str | None: Строка с описанием ошибки, если обнаружена, иначе None.
    """
    # Параметры из конфигурации для удобства
    ascii_conf = config['ascii_validation']
    indent_char = ascii_conf['indent_char']
    indent_size = ascii_conf['indent_size'] # Используется для валидации, но не для определения глубины здесь
    dir_suffix = ascii_conf['dir_suffix']
    
    initial_indent_len = 0
    for char_in_line in line:
        if char_in_line == indent_char:
            initial_indent_len += 1
        else:
            break
            
    rest_of_line = line[initial_indent_len:]
    
    # Удаляем стандартные префиксы ветвления, если они есть, для извлечения имени
    # Порядок важен: от более длинных/специфичных к коротким/общим
    branch_prefixes_ordered = [
        ascii_conf['last_branch_prefix'], # e.g., "└── "
        ascii_conf['branch_prefix'],    # e.g., "├── "
        ascii_conf['pipe_prefix'],      # e.g., "│   "
        ascii_conf['space_prefix']      # e.g., "    " (если используется как префикс-заполнитель)
    ]

    name_part_after_prefixes = rest_of_line
    for prefix_val in branch_prefixes_ordered:
        if name_part_after_prefixes.startswith(prefix_val):
            name_part_after_prefixes = name_part_after_prefixes[len(prefix_val):]
            break # Удален один из структурных префиксов

    name_part_final = name_part_after_prefixes.lstrip() # Убираем пробелы перед фактическим именем

    if not name_part_final:
        return initial_indent_len, "", False, "Пустое имя элемента после удаления префиксов и отступов."

    is_directory = name_part_final.endswith(dir_suffix)
    clean_name = name_part_final[:-len(dir_suffix)] if is_directory else name_part_final

    if not clean_name:
         return initial_indent_len, "", is_directory, f"Имя элемента пустое после удаления суффикса '{dir_suffix}'."

    invalid_os_chars = r'<>:"/\|?*'
    if any(char in clean_name for char in invalid_os_chars):
       return initial_indent_len, clean_name, is_directory, f"Недопустимые символы ОС в имени: '{clean_name}'."
    if clean_name == "." or clean_name == "..":
        return initial_indent_len, clean_name, is_directory, f"Имя элемента не может быть '.' или '..': '{clean_name}'."

    return initial_indent_len, clean_name, is_directory, None


def ascii_to_structure(ascii_string: str, config: dict) -> dict | None:
    """
    Конвертирует многострочное ASCII-представление дерева файлов/папок
    в иерархическую структуру словарей.

    Args:
        ascii_string (str): Строка, содержащая ASCII-дерево.
        config (dict): Словарь конфигурации приложения с секцией `ascii_validation`.

    Returns:
        dict | None: Словарь, представляющий корневой элемент структуры,
                     или None в случае ошибки парсинга или пустого ввода.
                     Структура словаря: `{'name': str, 'type': str ('directory'|'file'),
                     'children': list (для 'directory')}`.
    """
    lines = [line for line in ascii_string.splitlines() if line.strip()]
    if not lines:
        logger.info("ascii_to_structure: пустая входная строка ASCII, возвращено None.")
        return None

    # Парсинг корневого элемента
    root_indent_len, root_name, root_is_dir, error = _parse_ascii_line_detailed(lines[0], config)
    
    if error:
        logger.error(f"Ошибка парсинга корневого элемента ASCII (строка 1): {error}. Строка: '{lines[0]}'")
        return None
    # Корневой элемент не должен иметь префиксов ветвления, и его отступ должен быть 0
    # для канонического представления.
    if root_indent_len != 0:
        logger.error(f"Корневой элемент ASCII '{lines[0]}' имеет ненулевой начальный отступ ({root_indent_len}), ожидался 0.")
        return None
    
    # Проверка, что у корневого элемента нет префиксов ветвления
    first_line_lstripped_for_prefix_check = lines[0].lstrip(config['ascii_validation']['indent_char'])
    branching_prefixes_to_check = [
        config['ascii_validation']['branch_prefix'],
        config['ascii_validation']['last_branch_prefix'],
        config['ascii_validation']['pipe_prefix'] # │ тоже не должен быть у корня
    ]
    for bp_val in branching_prefixes_to_check:
        if first_line_lstripped_for_prefix_check.startswith(bp_val):
            logger.error(f"Корневой элемент ASCII не должен иметь префиксов ветвления типа '{bp_val}'. Строка: '{lines[0]}'")
            return None

    root_structure: dict = {"name": root_name, "type": "directory" if root_is_dir else "file"}
    if root_is_dir:
        root_structure["children"] = []

    # Стек для отслеживания родительских узлов: (длина_отступа_в_символах, узел_словаря)
    parent_stack: list[tuple[int, dict]] = [(root_indent_len, root_structure)]

    for i, line_content in enumerate(lines[1:], start=2): # Начиная со второй строки
        indent_len, name, is_dir, line_error = _parse_ascii_line_detailed(line_content, config)

        if line_error:
            logger.error(f"Ошибка парсинга ASCII на строке {i}: {line_error}. Строка: '{line_content}'")
            return None

        current_item_dict: dict = {"name": name, "type": "directory" if is_dir else "file"}
        if is_dir:
            current_item_dict["children"] = []

        # Найти правильного родителя в стеке: элемент с меньшим отступом
        while parent_stack and indent_len <= parent_stack[-1][0]:
            parent_stack.pop()

        if not parent_stack:
            logger.error(f"Ошибка структуры дерева ASCII на строке {i}: Не найден родитель в стеке. "
                           f"Возможно, несколько корней или некорректные отступы. Строка: '{line_content}'")
            return None

        # Отступ текущего элемента должен быть строго больше отступа родителя.
        # Это основное правило для определения вложенности.
        if indent_len <= parent_stack[-1][0]: # Эта проверка дублирует логику while, но для ясности
             logger.error(f"Ошибка структуры дерева ASCII на строке {i}: Некорректный уровень вложенности. "
                           f"Отступ {indent_len} не больше родительского {parent_stack[-1][0]}. Строка: '{line_content}'")
             return None

        parent_node_dict = parent_stack[-1][1]
        if parent_node_dict["type"] != "directory":
            logger.error(f"Ошибка структуры дерева ASCII на строке {i}: Попытка добавить дочерний элемент "
                           f"'{name}' не в директорию '{parent_node_dict['name']}'. Строка: '{line_content}'")
            return None
        
        parent_node_dict.setdefault("children", []).append(current_item_dict) # setdefault для надежности

        if is_dir: # Если текущий элемент - директория, он может стать родителем
            parent_stack.append((indent_len, current_item_dict))
            
    logger.info("ASCII structure successfully parsed to dictionary.")
    return root_structure


def _build_ascii_recursive(item: dict, current_depth_prefix_str: str, is_last_child_in_parent: bool,
                           buffer: list[str], config: dict) -> None:
    """
    Рекурсивно строит ASCII-представление для элемента структуры и его дочерних элементов.

    Args:
        item (dict): Словарь, описывающий текущий элемент.
        current_depth_prefix_str (str): Строка префикса, состоящая из символов '│' и пробелов,
                                       формирующая отступ от предыдущих уровней вложенности.
        is_last_child_in_parent (bool): True, если текущий элемент является последним
                                        в списке дочерних элементов своего родителя.
        buffer (list[str]): Список строк, в который добавляется сгенерированное ASCII-представление.
        config (dict): Словарь конфигурации приложения с секцией `ascii_validation`.
    """
    ascii_conf = config['ascii_validation']
    name_display = item['name']
    if item['type'] == 'directory':
        name_display += ascii_conf['dir_suffix']

    line = current_depth_prefix_str

    if is_last_child_in_parent:
        line += ascii_conf['last_branch_prefix']  # e.g., "└── "
    else:
        line += ascii_conf['branch_prefix']     # e.g., "├── "
    
    line += name_display
    buffer.append(line)

    if item['type'] == 'directory' and item.get('children'): # Проверяем наличие 'children'
        num_children = len(item['children'])
        # Определяем сегмент префикса для дочерних элементов этого узла
        # Если текущий узел был последним, то его дети не должны иметь вертикальной черты на этом уровне.
        next_level_prefix_segment = ascii_conf['space_prefix'] if is_last_child_in_parent else ascii_conf['pipe_prefix']
        
        for i, child in enumerate(item['children']):
            if not isinstance(child, dict): # Проверка типа ребенка
                logger.warning(f"Skipping non-dict child item during ASCII generation: {child}")
                continue
            _build_ascii_recursive(child, current_depth_prefix_str + next_level_prefix_segment,
                                   i == num_children - 1, buffer, config)

def structure_to_ascii(structure_data: dict | None, config: dict) -> str:
    """
    Конвертирует иерархическую структуру (словарь) в многострочное ASCII-представление дерева.

    Args:
        structure_data (dict | None): Словарь, описывающий корневой элемент структуры,
                                 или None для пустой структуры.
        config (dict): Словарь конфигурации приложения с секцией `ascii_validation`.

    Returns:
        str: Строка, содержащая ASCII-дерево. Возвращает пустую строку,
             если `structure_data` некорректен или None.
    """
    if not structure_data or not isinstance(structure_data, dict) or \
       'name' not in structure_data or 'type' not in structure_data:
        logger.warning(f"structure_to_ascii: получены некорректные или пустые входные данные structure_data.")
        return ""

    buffer: list[str] = []
    ascii_conf = config['ascii_validation']
    
    root_display_name = structure_data['name']
    if structure_data['type'] == 'directory':
        root_display_name += ascii_conf['dir_suffix']
    buffer.append(root_display_name) # Корневой элемент без префиксов ветвления

    if structure_data['type'] == 'directory' and structure_data.get('children'):
        num_children = len(structure_data['children'])
        # Дети корневого элемента не имеют префикса от родительских ветвей (`current_depth_prefix_str` пуст)
        for i, child in enumerate(structure_data['children']):
            if not isinstance(child, dict):
                logger.warning(f"Skipping non-dict child of root during ASCII generation: {child}")
                continue
            _build_ascii_recursive(child, "", i == num_children - 1, buffer, config)
    
    result_string = "\n".join(buffer)
    logger.info(f"Structure successfully converted to ASCII string (approx. {len(result_string)} chars).")
    return result_string


def validate_ascii_tree(ascii_string: str, config: dict) -> list[str]:
    """
    Валидирует ASCII-представление дерева на соответствие формату и правилам.

    Основная валидация происходит через попытку парсинга с помощью `ascii_to_structure`.
    Дополнительные проверки могут быть добавлены при необходимости.

    Args:
        ascii_string (str): Строка, содержащая ASCII-дерево.
        config (dict): Словарь конфигурации приложения с секцией `ascii_validation`.

    Returns:
        list[str]: Список строк с сообщениями об ошибках. Пустой список означает,
                   что ASCII-дерево валидно (включая полностью пустую строку).
    """
    errors: list[str] = []
    
    # Пустая строка или строка только из пробельных символов считается валидным (пустое дерево)
    if not ascii_string.strip():
        logger.info("validate_ascii_tree: пустая или пробельная строка ASCII, считается валидной.")
        return []

    lines = ascii_string.splitlines() # Для анализа, если парсинг упадет

    # Основная проверка - возможность корректно распарсить структуру.
    # `ascii_to_structure` выполняет детальный парсинг и логирует ошибки.
    parsed_structure = ascii_to_structure(ascii_string, config)
    
    if parsed_structure is None:
        # Если парсинг не удался, значит есть структурные ошибки.
        # ascii_to_structure уже должен был залогировать специфическую ошибку.
        # Здесь мы добавляем общее сообщение для пользователя.
        errors.append("Ошибка структуры дерева. Проверьте отступы, префиксы ветвления или "
                      "общую вложенность элементов. Детали можно найти в логе приложения.")
        logger.warning(f"ASCII tree validation failed due to parsing error. Input sample: '{ascii_string[:100]}...'")
        return errors

    # Если парсинг успешен, можно добавить более тонкие проверки,
    # которые не покрываются логикой `ascii_to_structure`, если таковые потребуются.
    # Например, проверка на максимальную глубину вложенности или общее количество узлов.
    # На данный момент, успешный парсинг считается достаточным для валидации.

    if not errors:
        logger.info("ASCII tree validation successful.")
    return errors


# --- Логика для requirements.txt ---
def _get_stdlib_modules() -> set[str]:
    """
    Возвращает множество имен модулей стандартной библиотеки Python.

    Использует `sys.stdlib_module_names` (Python 3.10+), затем `stdlib_list` (если установлен),
    и в крайнем случае - небольшой жестко закодированный список.

    Returns:
        set[str]: Множество имен модулей стандартной библиотеки.
    """
    # Python 3.10+
    if hasattr(sys, 'stdlib_module_names'):
        logger.debug("Using sys.stdlib_module_names for standard library list.")
        # sys.stdlib_module_names может быть None, если не инициализирован интерпретатором в особом режиме
        # или frozenset. Преобразуем в set для консистентности.
        return set(sys.stdlib_module_names) if sys.stdlib_module_names else set() # type: ignore[attr-defined]

    if get_stdlib_list_for_version:
        try:
            current_py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
            stdlib_set = set(get_stdlib_list_for_version(current_py_version)) # type: ignore[operator] # mypy может не знать о callable
            logger.debug(f"Using stdlib_list for Python {current_py_version}. Found {len(stdlib_set)} modules.")
            return stdlib_set
        except Exception as e:
            logger.warning(f"Failed to get stdlib list using 'stdlib_list' for Python {current_py_version}: {e}")

    # Крайний случай: жестко закодированный список (неполный, но лучше, чем ничего)
    hardcoded_stdlib = {
        "os", "sys", "math", "json", "datetime", "re", "argparse", "logging", "pathlib", "ast",
        "itertools", "collections", "subprocess", "threading", "time", "random", "typing",
        "functools", "operator", "io", "shutil", "tempfile", "unittest", "pickle", "copy",
        "weakref", "gc", "inspect", "zipfile", "tarfile", "csv", "configparser", "base64",
        "hashlib", "socket", "select", "struct", "enum", "urllib", "http", "xml"
    }
    logger.warning(f"Falling back to a minimal hardcoded standard library list ({len(hardcoded_stdlib)} modules). "
                   "This may be inaccurate. Consider installing 'stdlib_list' package.")
    return hardcoded_stdlib


def scan_python_imports(project_path_str: str) -> set[str]:
    """
    Рекурсивно сканирует .py файлы в указанной директории на наличие инструкций import.

    Извлекает имена импортированных модулей верхнего уровня (например, 'pandas' из 'import pandas.DataFrame').
    Игнорирует относительные импорты (начинающиеся с '.').

    Args:
        project_path_str (str): Путь к директории проекта для сканирования.

    Returns:
        set[str]: Множество уникальных имен импортированных внешних модулей.
                  Возвращает пустое множество, если путь не является директорией
                  или в случае других ошибок доступа.
    """
    project_path = Path(project_path_str)
    if not project_path.is_dir():
        logger.error(f"Project path '{project_path_str}' is not a directory or does not exist. Cannot scan imports.")
        return set()

    imports_found: set[str] = set()
    parsed_files_count = 0
    syntax_error_files: list[str] = []

    for py_file in project_path.rglob("*.py"): # Рекурсивный поиск .py файлов
        try:
            with open(py_file, "r", encoding="utf-8", errors='ignore') as f_source: # errors='ignore' для проблемных файлов
                source_code = f_source.read()
            
            tree = ast.parse(source_code, filename=str(py_file))
            parsed_files_count += 1
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name: # Проверка, что имя не пустое
                            imports_found.add(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    # Игнорируем относительные импорты (level > 0)
                    # node.module может быть None для "from . import X", но level будет > 0
                    if node.module and node.level == 0:
                        imports_found.add(node.module.split('.')[0])
        except SyntaxError as e:
            logger.warning(f"Syntax error parsing '{py_file}' for imports: {e}")
            syntax_error_files.append(str(py_file))
        except Exception as e:
            logger.error(f"Error processing file '{py_file}' for imports: {e}", exc_info=True)
    
    if syntax_error_files:
        logger.warning(f"Could not parse {len(syntax_error_files)} .py files due to syntax errors: {syntax_error_files}")
    logger.info(f"Import scan complete for '{project_path_str}'. Parsed {parsed_files_count} .py files. "
                f"Found {len(imports_found)} unique top-level import names: {sorted(list(imports_found)) if imports_found else 'None'}")
    return imports_found


def generate_requirements_content(imports_set: set[str], project_path_str: str) -> str:
    """
    Формирует содержимое для файла requirements.txt на основе списка импортированных модулей.

    Фильтрует модули стандартной библиотеки Python и локальные модули проекта.
    Локальные модули определяются как файлы .py или пакеты (директории с __init__.py или без,
    если они импортируются как пространства имен) в корне проекта или в директории 'src/'.

    Args:
        imports_set (set[str]): Множество имен импортированных модулей,
                                полученных от `scan_python_imports`.
        project_path_str (str): Путь к корневой директории проекта. Используется
                                для определения локальных модулей.

    Returns:
        str: Строка, содержащая имена внешних зависимостей, каждая на новой строке,
             отсортированные в алфавитном порядке (без учета регистра).
             Версии пакетов не определяются.
    """
    stdlib_modules = _get_stdlib_modules()
    project_path = Path(project_path_str)

    local_modules: set[str] = set()
    # Сканируем корень проекта и папку 'src' на наличие потенциальных локальных модулей
    paths_to_scan_for_local = [project_path]
    src_path = project_path / "src"
    if src_path.is_dir():
        paths_to_scan_for_local.append(src_path)

    for scan_dir in paths_to_scan_for_local:
        if scan_dir.is_dir(): # Дополнительная проверка
            for item in scan_dir.iterdir():
                # Считаем локальным модулем, если это .py файл (без расширения)
                # или директория (потенциальный пакет)
                if (item.is_file() and item.suffix == '.py') or item.is_dir():
                    local_modules.add(item.stem) # item.stem для 'file.py' -> 'file'; для 'dir' -> 'dir'
    
    logger.debug(f"Determined local modules for project '{project_path_str}': {sorted(list(local_modules))}")

    external_deps: list[str] = []
    for imp_name in sorted(list(imports_set), key=str.lower): # Сортировка без учета регистра
        if imp_name and imp_name not in stdlib_modules and imp_name not in local_modules:
            # Дополнительно проверяем, не является ли импорт частью стандартного пакета с точкой (e.g. xml.etree)
            # Это частично покрывается stdlib_modules, но для надежности.
            # if '.' in imp_name and imp_name.split('.')[0] in stdlib_modules:
            #    continue # Пропускаем, если корневой модуль стандартный
            external_deps.append(imp_name)
    
    logger.info(f"External dependencies determined for requirements.txt: {external_deps}")
    return "\n".join(external_deps)