import sys
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QLineEdit, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget, QHBoxLayout


class JointWidget(QWidget):
    def __init__(self, name, parent=None):
        super().__init__(parent)

        # Creating widgets
        self.label = QLabel(name, self)
        self.label.setFixedWidth(100)
        self.line_edit = QLineEdit(self)
        self.line_edit.setText(name)
        self.button = QPushButton("Add selected", self)
        self.button.clicked.connect(self.add_selected)

        # Horizontal layout for placing widgets
        layout = QHBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.line_edit)
        layout.addWidget(self.button)

        # Setting the horizontal layout in the widget
        self.setLayout(layout)

    def delete_self(self):
        '''
        A function for self-deleting an object
        :return:pass
        '''
        self.deleteLater()

    def add_selected(self):
        '''The temporary function'''
        print(self.label.text())


class JointReplacementDialog(QtWidgets.QDialog):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.item_list = list()
        self.data = data

        # global layout
        layout = QtWidgets.QVBoxLayout()
        namespace_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(namespace_layout)

        # _________________________________ Global change button
        # creation
        self.namespace_label = QLabel('Namespace: ')
        self.namespace_le = QLineEdit()
        self.namespace_butten_add = QPushButton('Add')
        self.namespace_butten_sub = QPushButton('Subtract')
        # set location
        namespace_layout.addWidget(self.namespace_label)
        namespace_layout.addWidget(self.namespace_le)
        namespace_layout.addWidget(self.namespace_butten_add)
        namespace_layout.addWidget(self.namespace_butten_sub)
        # connection
        self.namespace_butten_add.clicked.connect(self.edit_namespace_add)
        self.namespace_butten_sub.clicked.connect(self.edit_namespace_sub)

        # _________________________________ central layout for items
        # creation
        self.items_layout = QVBoxLayout()
        self.inside_layout = QVBoxLayout()
        widget = QWidget()

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        # set location
        widget.setLayout(self.inside_layout)
        scroll_area.setWidget(widget)
        layout.addWidget(scroll_area)
        self.items_layout.addWidget(scroll_area)

        self.add_items()

        # ____________________________________ bottom buttons
        self.button_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(self.button_layout)
        # creation
        self.apply_button = QPushButton("Apply", self)
        self.cancel_button = QPushButton("Cancel", self)
        # set location
        self.button_layout.addWidget(self.apply_button)
        self.button_layout.addWidget(self.cancel_button)
        # connection
        self.apply_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        self.setLayout(layout)

    def edit_namespace_add(self):
        '''
        The function is linked to the button to add a prefix in all lines
        :return: pass
        '''
        namespace = self.namespace_le.text()
        if namespace == '':
            return

        index = 0
        for name in self.data.keys():
            self.item_list[index].line_edit.setText(namespace+':'+self.item_list[i].line_edit.text())
            index += 1

    def edit_namespace_sub(self):
        '''
        The function is linked to the button to remove the prefix in all lines
        if the prefix is at the root and is completely identical to the given one (and is not the name)
        :return: pass
        '''
        namespace = self.namespace_le.text()

        i = 0
        for name in self.data.keys():
            if namespace + ':' == self.item_list[i].line_edit.text()[:len(namespace) + 1]:
                self.item_list[i].line_edit.setText(self.item_list[i].line_edit.text()[len(namespace)+1:])
            i += 1

    def add_items(self):
        '''
        Adds all objects according to the data
        :return: pass
        '''
        for name in self.data:
            items_widget = JointWidget(name)
            self.item_list.append(items_widget)
            self.inside_layout.addWidget(items_widget)

    def get_data(self) -> dict:
        '''
        Функция, выполняемая при закрытии окна для сохранения изменений
        :return: adjusted joint
        '''

        i=0
        new_data = dict()
        for i in self.item_list:
            new_data[i.line_edit.text()] = self.data[i.label.text()]
        self.data = new_data
        return self.data


in_weights = {u'joint2': [0.361232, 0.146, 0.3612324, 0.14643, 0.5037043, 0.496184, 0.503704, 0.4961843],
              u'joint3': [0.017592, 0.098, 0.0175928, 0.09826, 0.054493, 0.48558, 0.054493, 0.485],
              u'joint4': [0.017592, 0.098, 0.0175928, 0.09826, 0.054493, 0.48558, 0.054493, 0.485],
              u'joint1': [0.62117, 0.7553003, 0.6211, 0.75530, 0.4418, 0.0182300, 0.4418018, 0.018230],
              'paint_weights': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
              'skinningMethod': 0}


def is_obj_in_scene(obj):
    """Заглушка функции проверки"""
    return obj in [u'joint4', u'joint3']


def joint_replacement_system(in_weights):
    '''
    The presence of these objects in the scene is being checked.
    is_obj_in_scene is a function for checking the presence of an object in the scene.
    If all the names from the dictionary are present in the scene, then the function returns
    the same dictionary that came to the input.
    Otherwise, a custom dialog box opens to change the dictionary keys by adding or
    subtracting a prefix of the form "pfx:".
    :param in_weights: A dictionary whose keys are 3D scene objects, with the exception of 'paint_weights' and 'skinningMethod'.
    :return: The entered dictionary of necessary objects. Or a window opens for editing
    '''
    to_change = dict()
    to_not_change = dict()
    for obj in in_weights.keys():
        if obj in ['paint_weights', 'skinningMethod']:
            continue
        if not is_obj_in_scene(obj):
            to_change[obj] = in_weights[obj].copy()
        else:
            to_not_change[obj] = in_weights[obj].copy()

    if len(to_change.keys()) == 0:
        return in_weights

    window = JointReplacementDialog(to_change.copy())
    message_text = dict()
    if window.exec_() == QtWidgets.QDialog.Accepted:
        message_text = window.get_data()

    in_weights = dict()
    for key in message_text.keys():
        in_weights[key] = message_text[key]
    for key in to_not_change.keys():
        in_weights[key] = to_not_change[key]
    return in_weights


app = QtWidgets.QApplication(sys.argv)
print(joint_replacement_system(in_weights))
sys.exit(app.exec_())