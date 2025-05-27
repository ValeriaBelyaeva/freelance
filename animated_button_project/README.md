# `animated_button.py`

Утилита демонстрирует кастомный Qt-виджет — кнопку, плавно расширяющуюся в спинбокс, с анимациями и темизацией.

---

## Подробная документация приложена в pdf файле

---

## Зависимости

- Python 3.7+  
- PyQt5  

---

## Содержание

- **Логгер**: `get_logger(name)` → настраивает вывод в консоль.  
- **`ButtonState`**: `Enum` со всеми состояниями виджета (IDLE, HOVERED, EXPANDED и т. д.).  
- **Вспомогательные виджеты**:  
  - `_ArrowButton` — кастомная кнопка-треугольник вверх/вниз;  
  - `_ValueSpinBox` — расширенный `QSpinBox` с закрытием при Enter.  
- **`AnimatedButton`** — главный класс, наследник `QWidget`:
  - при клике разворачивается в спинбокс, при повторном клике — сворачивается назад;  
  - все переходы (ширина, непрозрачность, границы) анимируются `QPropertyAnimation` в `QParallelAnimationGroup`;  
  - тема (`_ThemeConfig`) хранит размеры, цвета и скорость анимации, рассчитывается с учётом заданного масштаба и переопределений;  
  - сигналы:  
    - `valueChanged(int)` — при изменении значения;  
    - `clicked()` — при развёртывании/сворачивании.  
  - публичные методы:
    - `set_scale(scale: float)` — изменить масштаб;  
    - `apply_custom_style(overrides: dict)` — динамические переопределения темы;  
    - `value()` / `setValue(int)` — получить/задать текущее число;  
    - `expand_button()` / `collapse_button()` — программно развернуть/свернуть.  

---

## Быстрый старт

```python
from animated_button import AnimatedButton
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout
import sys

app = QApplication(sys.argv)
win = QWidget()
layout = QVBoxLayout(win)

btn = AnimatedButton(
    initial_text="Количество:",
    initial_value=5,
    scale=1.2,
    on_update=lambda v: print("Новое значение:", v)
)
layout.addWidget(btn)

win.show()
sys.exit(app.exec_())
```