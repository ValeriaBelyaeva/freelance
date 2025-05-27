import sys

from PyQt5 import QtWidgets
from PyQt5.QtCore import (
    QEvent,
    QPointF,
    QParallelAnimationGroup,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)


class JointWidget(QWidget):
    """Widget with a label, line edit, and 'Add selected' button."""

    def __init__(
        self,
        name,
        parent=None,
    ) -> None:
        """Initialize JointWidget."""
        super().__init__(parent)

        # Create internal widgets
        self.label = QLabel(name, self)
        self.label.setFixedWidth(100)
        self.line_edit = QLineEdit(self)
        self.line_edit.setText(name)
        self.button = QPushButton("Add selected", self)
        self.button.clicked.connect(self.add_selected)

        # Layout setup
        layout = QHBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.line_edit)
        layout.addWidget(self.button)
        self.setLayout(layout)

    def delete_self(self):
        """Delete this widget."""
        self.deleteLater()

    def add_selected(self):
        """Print the current label text."""
        print(self.label.text())


class JointReplacementDialog(QtWidgets.QDialog):
    """Dialog to replace joint names with optional namespace prefix."""

    def __init__(self, data, parent=None) -> None:
        """Initialize JointReplacementDialog."""
        super().__init__(parent)
        self.data = data
        self.item_list = []

        # Global layout
        layout = QtWidgets.QVBoxLayout(self)
        namespace_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(namespace_layout)

        # Namespace controls
        self.namespace_label = QLabel("Namespace:", self)
        self.namespace_le = QLineEdit(self)
        self.namespace_button_add = QPushButton("Add", self)
        self.namespace_button_sub = QPushButton("Subtract", self)
        namespace_layout.addWidget(self.namespace_label)
        namespace_layout.addWidget(self.namespace_le)
        namespace_layout.addWidget(self.namespace_button_add)
        namespace_layout.addWidget(self.namespace_button_sub)
        self.namespace_button_add.clicked.connect(self.edit_namespace_add)
        self.namespace_button_sub.clicked.connect(self.edit_namespace_sub)

        # Scroll area for items
        self.inside_layout = QVBoxLayout()
        container = QWidget()
        container.setLayout(self.inside_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(container)
        layout.addWidget(scroll_area)

        self.add_items()

        # Bottom buttons
        button_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(button_layout)
        self.apply_button = QPushButton("Apply", self)
        self.cancel_button = QPushButton("Cancel", self)
        button_layout.addWidget(self.apply_button)
        button_layout.addWidget(self.cancel_button)
        self.apply_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def edit_namespace_add(self):
        """Add namespace prefix to all joint names."""
        namespace = self.namespace_le.text()
        if not namespace:
            return

        for widget in self.item_list:
            text = widget.line_edit.text()
            widget.line_edit.setText(f"{namespace}:{text}")

    def edit_namespace_sub(self):
        """Remove namespace prefix from all joint names."""
        namespace = self.namespace_le.text()
        if not namespace:
            return

        prefix = f"{namespace}:"
        for widget in self.item_list:
            text = widget.line_edit.text()
            if text.startswith(prefix):
                widget.line_edit.setText(text[len(prefix):])

    def add_items(self):
        """Create JointWidget for each joint in data."""
        for name in self.data:
            widget = JointWidget(name, self)
            self.item_list.append(widget)
            self.inside_layout.addWidget(widget)

    def get_data(self):
        """Return updated data mapping new names to original values."""
        new_data = {}
        for widget in self.item_list:
            key = widget.line_edit.text()
            value = self.data.get(widget.label.text())
            new_data[key] = value.copy() if hasattr(value, "copy") else value
        return new_data


def is_obj_in_scene(obj):
    """Stub: check if object is in the scene."""
    return obj in ["joint4", "joint3"]


def joint_replacement_system(in_weights):
    """Check scene objects and prompt for namespace edits if needed."""
    to_change = {}
    to_keep = {}
    for key, val in in_weights.items():
        if key in ("paint_weights", "skinningMethod"):
            to_keep[key] = val
        elif not is_obj_in_scene(key):
            to_change[key] = val.copy()
        else:
            to_keep[key] = val.copy()

    if not to_change:
        return in_weights

    dialog = JointReplacementDialog(to_change.copy())
    if dialog.exec_() == QtWidgets.QDialog.Accepted:
        updated = dialog.get_data()
    else:
        updated = {}

    result = {**updated, **to_keep}
    return result


in_weights = {
    "joint1": [0.62117, 0.7553003, 0.6211, 0.75530, 0.4418, 0.0182300, 0.4418018, 0.018230],
    "joint2": [0.361232, 0.146, 0.3612324, 0.14643, 0.5037043, 0.496184, 0.503704, 0.4961843],
    "joint3": [0.017592, 0.098, 0.0175928, 0.09826, 0.054493, 0.48558, 0.054493, 0.485],
    "joint4": [0.017592, 0.098, 0.0175928, 0.09826, 0.054493, 0.48558, 0.054493, 0.485],
    "paint_weights": [0.0] * 8,
    "skinningMethod": 0,
}


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    result = joint_replacement_system(in_weights)
    print(result)
    sys.exit(app.exec_())
