# Workload Chart Generator

Генератор графиков рабочей нагрузки на Python. Обрабатывает данные из JSON, сглаживает их и сохраняет график в виде PNG-файла.

---

## Возможности

| Функция                 | Описание                                                                                       |
|-------------------------|---------------------------------------------------------------------------------------------------|
| **Обработка данных**    | Агрегирует проценты по проектам и датам, фильтрует пустые дни.                                    |
| **Сглаживание**         | Применяет скользящее среднее (размер окна настраивается через методы get_smooth/set_smooth).     |
| **Генерация графика**   | Строит график рабочей нагрузки по проектам во времени.                                           |
| **Сохранение**          | Сохраняет график в PNG-файл во временную директорию (по умолчанию).                              |
| **Логирование**         | Использует стандартный модуль logging для статуса и ошибок.                                      |

---

## Зависимости

- Python 3.7+
- pandas
- matplotlib

---

## Структура проекта

```
WorkloadChartGenerator/
├── charts/                   # (Не используется по умолчанию)
├── workloadChartGenerator.py # Основной модуль
├── reports.json              # Пример входных данных
├── requirements.txt          # Зависимости
└── README.md                 # Этот файл
```

---

## Быстрый старт

1. **Перейдите в директорию проекта:**
    ```bash
    cd путь/к/WorkloadChartGenerator
    ```
2. **Создайте и активируйте виртуальное окружение:**
    ```bash
    python -m venv .venv
    .\.venv\Scripts\activate  # Windows
    # или source .venv/bin/activate  # Linux/macOS
    ```
3. **Установите зависимости:**
    ```bash
    pip install -r requirements.txt
    ```
4. **Запустите основной скрипт:**
    ```bash
    python workloadChartGenerator.py
    ```
    По умолчанию будет обработан файл `reports.json`, график сохранится во временную директорию, путь к файлу появится в логе.

---

## Использование класса

### Инициализация

```python
from workloadChartGenerator import WorkloadChartGenerator
import json

with open('reports.json', encoding='utf-8') as f:
    raw = json.load(f)

gen = WorkloadChartGenerator(raw, year=2025, smooth=3)
```
- `raw` (dict): Исходные данные (загрузите из JSON самостоятельно)
- `year` (int, по умолчанию 2025): Год для дат
- `smooth` (int, по умолчанию 3): Размер окна сглаживания (1 — без сглаживания)

### Основные методы

- **prepare()** — готовит данные для графика (агрегирует, преобразует, фильтрует, вызывает сглаживание)
- **get_smooth() / set_smooth(value)** — получить/установить размер окна сглаживания и автоматически обновить сглажённые данные
- **save(size=(14,7), legend="upper left", anchor=(1.02,1), show=False)** — сохраняет график в PNG-файл во временную директорию, возвращает путь к файлу

### Пример

```python
import json
from workloadChartGenerator import WorkloadChartGenerator, run

with open('reports.json', encoding='utf-8') as f:
    raw = json.load(f)

gen = WorkloadChartGenerator(raw, year=2025, smooth=3)
gen.prepare()
gen.set_smooth(5)  # изменить окно сглаживания
chart_path = gen.save(show=True)
print(f'График сохранён: {chart_path}')

# Быстрый способ:
chart_path = run(raw, year=2025, smooth=3)
```

---

## Примечания

- Даты в `reports.json` должны быть в формате "ММ-ДД" (например, "01-15").
- Скрипт связывает даты с указанным годом (`year`).
- График сохраняется во временную директорию ОС (например, `/tmp` или `C:\Users\...\AppData\Local\Temp`).
- Для логирования используется стандартный модуль logging.

---

*Автор: Валерия Беляева, 2025 г.*