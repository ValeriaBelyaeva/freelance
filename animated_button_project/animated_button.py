
import sys
import logging
from dataclasses import dataclass, field # Keep field if used elsewhere, not in this snippet
from enum import Enum, auto
from typing import Optional, Callable, Dict, Any

# ------ PyQt imports ------
from PyQt5.QtWidgets import (
    QWidget, QApplication,
    QHBoxLayout, QVBoxLayout,
    QLabel, QSpinBox, QSizePolicy, QPushButton,
    QStyle, QToolButton, QSpacerItem, QGraphicsOpacityEffect
)
from PyQt5.QtCore import (
    Qt, pyqtSignal, pyqtProperty,
    QPropertyAnimation, QParallelAnimationGroup,
    QEasingCurve, QSize, QRectF, QTimer, QEvent, QPointF
)
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QFontMetrics,
    QMouseEvent, QFocusEvent, QPaintEvent, QResizeEvent, # QResizeEvent not used
    QKeyEvent, QPainterPath, QFont, QPolygonF
)

# Define QWIDGETSIZE_MAX if not available directly (it's an internal C++ define)
QWIDGETSIZE_MAX = (1 << 24) - 1

# ------ Logging helper (GLOBAL) --------------------------------
def get_logger(name: str) -> logging.Logger:
    logger_instance = logging.getLogger(name)
    if not logger_instance.hasHandlers():
        handler = logging.StreamHandler()
        fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
        handler.setFormatter(logging.Formatter(fmt))
        logger_instance.addHandler(handler)
        logger_instance.setLevel(logging.INFO) # DEBUG for more details
    return logger_instance


logger = get_logger("AnimatedButton")


# ----------------------------------------------------------------


# ------ State machine for the widget (GLOBAL) --------------------
class ButtonState(Enum):
    """
    Represents the possible states of the AnimatedButton widget.
    
    States:
        IDLE: Initial state, button is collapsed and not interacted with
        HOVERED: Mouse is over the button but not clicked
        PRESSED_TO_EXPAND: Button is being clicked to expand
        EXPANDING: Button is animating from collapsed to expanded state
        EXPANDED: Button is fully expanded showing the spinbox
        COLLAPSING: Button is animating from expanded to collapsed state
    """
    IDLE = auto()
    HOVERED = auto()
    PRESSED_TO_EXPAND = auto()
    EXPANDING = auto()
    EXPANDED = auto()
    COLLAPSING = auto()


# ----------------------------------------------------------------

# ───────── helpers ──────────────────────────────────────────────
class _ArrowButton(QToolButton):
    def __init__(
            self,
            direction: str,
            theme_settings: "AnimatedButton._ThemeConfig",
            parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._theme_settings = theme_settings
        self._direction = direction

        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._update_size_and_font()
        self.setStyleSheet("background:transparent; border:none;")

    def _update_size_and_font(self):
        # Use theme settings directly
        tri_size = self._theme_settings.ARROW_SIZE
        vert_pad = max(2, self._theme_settings.PADDING_V) # Use theme's vertical padding
        # Adjust height based on theme's MIN_HEIGHT and PADDING_V
        total_height = self._theme_settings.MIN_HEIGHT - 2 * self._theme_settings.PADDING_V
        total_width = self._theme_settings.SPINBOX_ARROW_WIDTH

        max_arrow_v_size = max(1, total_height - 2 * vert_pad)
        self._triangle_size = min(tri_size, max_arrow_v_size)
        self._vertical_padding = vert_pad

        required_height = self._triangle_size + 2 * self._vertical_padding
        final_height = min(total_height, required_height)
        # Adjust padding slightly if calculated height exceeds available space
        if final_height < required_height:
             self._vertical_padding = max(1, (final_height - self._triangle_size) // 2)
             final_height = self._triangle_size + 2 * self._vertical_padding

        self.setFixedSize(total_width, max(10, final_height)) # Ensure min height

        font = self.font()
        # Use theme's calculated font point size for consistency
        font.setPointSize(self._theme_settings.BUTTON_FONT_PT)
        self.setFont(font)

    def update_theme(self, new_theme_settings: "AnimatedButton._ThemeConfig"):
        self._theme_settings = new_theme_settings
        self._update_size_and_font()
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        color = (
            self._theme_settings.COLOR_ARROW_HOVER
            if self.underMouse() and self.isEnabled()
            else self._theme_settings.COLOR_ARROW
        )
        painter.setBrush(color)

        w = self.width()
        h = self.height()
        pad = self._vertical_padding
        tri = self._triangle_size
        center_x = w / 2

        # Adjusted triangle points to use size correctly
        if self._direction == "up":
            pts = [
                QPointF(center_x, pad),
                QPointF(center_x - tri / 2, pad + tri),
                QPointF(center_x + tri / 2, pad + tri),
            ]
        else: # "down"
             pts = [
                QPointF(center_x, h - pad),
                QPointF(center_x - tri / 2, h - pad - tri),
                QPointF(center_x + tri / 2, h - pad - tri),
            ]
        painter.drawPolygon(QPolygonF(pts))


class _ValueSpinBox(QSpinBox):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setKeyboardTracking(True)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.clearFocus()
        else:
            super().keyPressEvent(event)


# ______ AnimatedButton widget _____________________________
class AnimatedButton(QWidget):
    """
    A custom Qt widget that combines a button with an animated spinbox.
    
    This widget starts as a regular button and smoothly expands into a spinbox
    when clicked. It supports keyboard navigation, custom styling, and scaling.
    All transitions are animated with configurable durations and easing curves.
    
    Signals:
        valueChanged(int): Emitted when the spinbox value changes
        clicked(): Emitted when the button is activated (expand or collapse)
    
    Attributes:
        _initial_text (str): The text displayed on the button
        _current_value (int): Current value of the spinbox
        _state (ButtonState): Current state of the widget
        _scale (float): Current scaling factor for the widget
        _theme (_ThemeConfig): Current theme configuration
    """
    valueChanged = pyqtSignal(int)
    clicked = pyqtSignal()

    # Stores the *calculated* theme values based on scale and overrides
    @dataclass(frozen=True)
    class _ThemeConfig:
        """
        Immutable configuration class that stores all theme-related values for the AnimatedButton.
        
        This class is responsible for managing all visual aspects of the button including:
        - Dimensions (padding, spacing, heights, widths)
        - Colors (background, text, borders, accents)
        - Animation settings
        - Font sizes and styles
        
        The values are calculated based on a base scale factor and optional overrides.
        All values are scaled proportionally to maintain visual consistency.
        
        Attributes:
            RADIUS (int): Base radius for rounded corners
            PADDING_V (int): Vertical padding
            PADDING_H (int): Horizontal padding
            MIN_HEIGHT (int): Minimum height of the button
            SPINBOX_ARROW_WIDTH (int): Width of the spinbox arrow buttons
            TEXT_ANIM_OFFSET (int): Offset for text animation
            ANIM_DURATION_MS (int): Duration of animations in milliseconds
            BUTTON_BORDER_RADIUS (int): Border radius of the main button
            BUTTON_PADDING_V (int): Vertical padding of the button
            BUTTON_PADDING_H (int): Horizontal padding of the button
            BUTTON_FONT_PT (int): Font size in points
            SPINBOX_BORDER_RADIUS (int): Border radius of the spinbox
            SPINBOX_PADDING_V (int): Vertical padding of the spinbox
            SPINBOX_PADDING_H (int): Horizontal padding of the spinbox
            ARROW_SIZE (int): Size of the arrow indicators
            SPACING (int): Space between elements
            BORDER_WIDTH (int): Width of borders
            COLOR_BG_IDLE (QColor): Background color in idle state
            COLOR_BG_HOVER (QColor): Background color on hover
            COLOR_BG_PRESSED (QColor): Background color when pressed
            COLOR_BORDER_IDLE (QColor): Border color in idle state
            COLOR_BORDER_HOVER (QColor): Border color on hover
            COLOR_TEXT (QColor): Text color
            COLOR_ACCENT (QColor): Accent color for highlights
            COLOR_ARROW (QColor): Color of arrow indicators
            COLOR_ARROW_HOVER (QColor): Color of arrow indicators on hover
            SHOWBACKGROUND (bool): Whether to show background
            FOCUSON (bool): Whether to show focus indicator
        """
        # Keep all theme slots
        __slots__ = ("RADIUS", "PADDING_V", "PADDING_H", "MIN_HEIGHT", "SPINBOX_ARROW_WIDTH",
                     "TEXT_ANIM_OFFSET", "ANIM_DURATION_MS", "BUTTON_BORDER_RADIUS", "BUTTON_PADDING_V",
                     "BUTTON_PADDING_H", "BUTTON_FONT_PT", "SPINBOX_BORDER_RADIUS", "SPINBOX_PADDING_V",
                     "SPINBOX_PADDING_H", "ARROW_SIZE", "SPACING", "COLOR_BG_IDLE", "COLOR_BG_HOVER",
                     "COLOR_BG_PRESSED",
                     "COLOR_BORDER_IDLE", "COLOR_BORDER_HOVER", "COLOR_TEXT", "COLOR_ACCENT", "COLOR_ARROW",
                     "COLOR_ARROW_HOVER", "SHOWBACKGROUND", "FOCUSON", "BORDER_WIDTH")

        RADIUS: int; PADDING_V: int; PADDING_H: int; MIN_HEIGHT: int; SPINBOX_ARROW_WIDTH: int
        TEXT_ANIM_OFFSET: int; ANIM_DURATION_MS: int; BUTTON_BORDER_RADIUS: int; BUTTON_PADDING_V: int
        BUTTON_PADDING_H: int; BUTTON_FONT_PT: int; SPINBOX_BORDER_RADIUS: int; SPINBOX_PADDING_V: int
        SPINBOX_PADDING_H: int; ARROW_SIZE: int; SPACING: int; BORDER_WIDTH: int
        COLOR_BG_IDLE: QColor; COLOR_BG_HOVER: QColor; COLOR_BG_PRESSED: QColor
        COLOR_BORDER_IDLE: QColor; COLOR_BORDER_HOVER: QColor; COLOR_TEXT: QColor
        COLOR_ACCENT: QColor; COLOR_ARROW: QColor; COLOR_ARROW_HOVER: QColor
        SHOWBACKGROUND: bool; FOCUSON: bool

        # Base values used for scaling (can be class attributes)
        _BASE_FONT_PT = 10
        _BASE_ANIM_MS = 800
        # Inside AnimatedButton._ThemeConfig class
        _BASE_VALUES = {
            "RADIUS": 12, "PADDING_V": 4, "PADDING_H": 12, "SPACING": 12, "MIN_HEIGHT": 36, # PADDING_H acts as base for spacing too
            "SPINBOX_ARROW_WIDTH": 18, "TEXT_ANIM_OFFSET": 0, #"ANIM_DURATION_MS": 800, <- Base defined above
            "BUTTON_BORDER_RADIUS": 14, "BUTTON_PADDING_V": 4, "BUTTON_PADDING_H": 12,
            "BUTTON_FONT_PT": 10, # Added to match _BASE_FONT_PT
            "SPINBOX_BORDER_RADIUS": 8, "SPINBOX_PADDING_V": 2,
            "SPINBOX_PADDING_H": 6, "ARROW_SIZE": 9, "BORDER_WIDTH": 2, # Base border width
            "COLOR_BG_IDLE": "#2A303A", "COLOR_BG_HOVER": "#1A7AF6", "COLOR_BG_PRESSED": "#1A7AF6",
            "COLOR_BORDER_IDLE": "#3C4250", "COLOR_BORDER_HOVER": "#4A5162",
            "COLOR_TEXT": "#E4E8F0", "COLOR_ACCENT": "#1A7AF6",
            "COLOR_ARROW": "#E4E8F0", "COLOR_ARROW_HOVER": "#D0E0FF", # Base Arrow Hover
            "SHOWBACKGROUND": True, "FOCUSON": True,
        }

        @classmethod
        def create(cls, scale: float = 1.0,
                   overrides: Optional[Dict[str, Any]] = None
                  ) -> "AnimatedButton._ThemeConfig":
            """
            Creates a new theme configuration with scaled values and optional overrides.
            
            Args:
                scale (float): Base scaling factor for all dimensions (default: 1.0)
                overrides (Dict[str, Any], optional): Dictionary of value overrides
                    Supported override keys:
                    - 'padding': Override horizontal padding
                    - 'spacing': Override spacing between elements
                    - 'anim_speed': Override animation speed (higher = faster)
                    - 'text_scale': Override text and arrow size scaling
                    - 'active_color': Override active/hover color
                    - 'text_color': Override text and arrow color
                    - Any other theme property can be overridden directly
            
            Returns:
                _ThemeConfig: A new immutable theme configuration instance
            
            Note:
                The scale factor is clamped to a minimum of 0.1 to prevent too small values.
                All dimensions are scaled proportionally to maintain visual consistency.
            """
            scale = max(0.1, scale)
            if overrides is None: overrides = {}
            logger.debug(f"Creating theme: scale={scale}, overrides={list(overrides.keys())}")

            # --- Helper to get scaled value, checking overrides ---
            def px(key: str, clamp: Optional[int] = None) -> int:
                if key in overrides:
                    val = overrides[key]
                    logger.debug(f"  Override found for {key}: {val}")
                    return val
                if key == "BUTTON_FONT_PT":
                    baseline = cls._BASE_FONT_PT  # Use class attribute instead of _BASE_VALUES
                else:
                    baseline = cls._BASE_VALUES[key]
                val = int(round(baseline * scale))
                return max(clamp, val) if clamp is not None else val

            def col(key: str, default: str) -> QColor:
                val = overrides.get(key, default)
                return QColor(val) if isinstance(val, str) else val

            # --- Create final config ---
            arrow_size = px("ARROW_SIZE", clamp=5)
            spinbox_arrow_width = max(arrow_size + 6, int(round(arrow_size * 1.6)))

            return cls(
                RADIUS=max(px("MIN_HEIGHT"), 3 * px("RADIUS")) // 2,
                PADDING_V=px("PADDING_V"),
                PADDING_H=px("PADDING_H"),
                SPACING=px("SPACING"),
                MIN_HEIGHT=max(px("MIN_HEIGHT"), 3 * px("RADIUS")),
                SPINBOX_ARROW_WIDTH=spinbox_arrow_width,
                TEXT_ANIM_OFFSET=cls._BASE_VALUES["TEXT_ANIM_OFFSET"],
                ANIM_DURATION_MS=int(round(cls._BASE_ANIM_MS * (scale ** 0.5))),
                BUTTON_BORDER_RADIUS=px("BUTTON_BORDER_RADIUS"),
                BUTTON_PADDING_V=px("BUTTON_PADDING_V"),
                BUTTON_PADDING_H=px("BUTTON_PADDING_H"),
                BUTTON_FONT_PT=px("BUTTON_FONT_PT", clamp=8),
                SPINBOX_BORDER_RADIUS=px("SPINBOX_BORDER_RADIUS"),
                SPINBOX_PADDING_V=px("SPINBOX_PADDING_V"),
                SPINBOX_PADDING_H=px("SPINBOX_PADDING_H"),
                ARROW_SIZE=arrow_size,
                BORDER_WIDTH=px("BORDER_WIDTH"),
                # colours
                COLOR_BG_IDLE   = col("COLOR_BG_IDLE",   cls._BASE_VALUES["COLOR_BG_IDLE"]),
                COLOR_BG_HOVER  = col("COLOR_BG_HOVER",  cls._BASE_VALUES["COLOR_BG_HOVER"]),
                COLOR_BG_PRESSED= col("COLOR_BG_PRESSED",cls._BASE_VALUES["COLOR_BG_PRESSED"]),
                COLOR_BORDER_IDLE  = col("COLOR_BORDER_IDLE",  cls._BASE_VALUES["COLOR_BORDER_IDLE"]),
                COLOR_BORDER_HOVER = col("COLOR_BORDER_HOVER", cls._BASE_VALUES["COLOR_BORDER_HOVER"]),
                COLOR_TEXT      = col("COLOR_TEXT",      cls._BASE_VALUES["COLOR_TEXT"]),
                COLOR_ACCENT    = col("COLOR_ACCENT",    cls._BASE_VALUES["COLOR_ACCENT"]),
                COLOR_ARROW     = col("COLOR_ARROW",     cls._BASE_VALUES["COLOR_ARROW"]),
                COLOR_ARROW_HOVER = col("COLOR_ARROW_HOVER", cls._BASE_VALUES["COLOR_ARROW_HOVER"]),
                SHOWBACKGROUND  = overrides.get("SHOWBACKGROUND", True),
                FOCUSON         = overrides.get("FOCUSON", False),
            )

    def __init__(
            self,
            initial_text: str = "Value:",
            initial_value: int = 0,
            scale: float = 1.0,
            parent: Optional[QWidget] = None,
            on_update: Optional[Callable[[int], None]] = None,
    ):
        """
        Initialize the AnimatedButton widget.
        
        Args:
            initial_text (str): Text to display on the button (default: "Value:")
            initial_value (int): Initial value for the spinbox (default: 0)
            scale (float): Initial scaling factor (default: 1.0)
            parent (QWidget, optional): Parent widget
            on_update (Callable[[int], None], optional): Callback function for value changes
        """
        super().__init__(parent)

        self._initial_text = initial_text
        self._current_value = initial_value
        self._state = ButtonState.IDLE
        self._is_hovered_visual = False
        self._has_keyboard_focus = False
        self._on_update = on_update

        self._scale = scale # Store the base scale
        self._style_overrides: Dict[str, Any] = {} # Store custom style overrides

        # Initial theme generation using scale
        self._theme: AnimatedButton._ThemeConfig = self._rebuild_theme_with_overrides()

        self._width_anim_value: float = 0.0
        self._spinbox_opacity_anim_value: float = 0.0
        self._border_opacity_anim_value: float = 1.0
        self._spinbox_opacity_effect: Optional[QGraphicsOpacityEffect] = None

        self._setup_widget_flags()
        self._create_widgets()
        self._setup_layout()
        self._calculate_and_set_initial_widths() # First calculation based on initial theme
        self.apply_styles() # Apply styles based on initial theme
        self._build_animations() # Build animations based on initial theme
        self._connect_signals_slots()

        self.setFixedHeight(self._theme.MIN_HEIGHT)
        self.width_anim = self._collapsed_width # Start collapsed

    # --- Scale and Style Application ---

    def set_scale(self, scale: float):
        """
        Sets the base scaling factor for the button.
        
        This will trigger a rebuild of the theme and update all visual elements
        proportionally. The scale factor is clamped to a minimum of 0.1.
        
        Args:
            scale (float): New scaling factor
        """
        scale = max(0.1, scale)
        if abs(self._scale - scale) > 1e-6:
            logger.info(f"Setting scale for '{self._initial_text}' to {scale}")
            self._scale = scale
            self._theme = self._rebuild_theme_with_overrides()
            self._apply_theme_update()
            if self._state in (ButtonState.EXPANDED, ButtonState.EXPANDING, ButtonState.PRESSED_TO_EXPAND):
                self._calculate_and_set_initial_widths()
                self._spinbox_container_widget.setFixedWidth(self._spinbox_container_target_width)
                self.width_anim = self._expanded_width
                self.updateGeometry()
                self.update()
        
        self._update_child_widget_themes_and_fonts()
        self._calculate_and_set_initial_widths()
        self.apply_styles()
        if self._state in (ButtonState.EXPANDED, ButtonState.EXPANDING, ButtonState.PRESSED_TO_EXPAND):
            self.width_anim = self._expanded_width
        else:
            self.width_anim = self._collapsed_width
        # и перерисуем
        self.updateGeometry()
        self.update()

    def apply_custom_style(self, style_overrides: Dict[str, Any]):
        """
        Applies custom style overrides to the button.
        
        This method allows for dynamic styling changes without recreating the widget.
        The overrides are merged with existing ones, with new values taking precedence.
        
        Args:
            style_overrides (Dict[str, Any]): Dictionary of style overrides
                Supported keys:
                - 'padding': Override horizontal padding
                - 'spacing': Override spacing between elements
                - 'anim_speed': Override animation speed (higher = faster)
                - 'text_scale': Override text and arrow size scaling
                - 'active_color': Override active/hover color
                - 'text_color': Override text and arrow color
                - Any other theme property can be overridden directly
        """
        if not isinstance(style_overrides, dict):
            logger.warning("apply_custom_style expects a dictionary.")
            return
        
        style_overrides = self.interpret_styles_keys(style_overrides)
        logger.info(f"Applying custom style to '{self._initial_text}': {list(style_overrides.keys())}")
        self._style_overrides.update(style_overrides)
        self._theme = self._rebuild_theme_with_overrides()
        self._apply_theme_update()

    def interpret_styles_keys(self, style_overrides: Dict[str, Any]) -> Dict[str, Any]:
        """
        Interprets and converts user-friendly style keys to internal theme properties.
        
        This method handles the conversion of simplified style keys to their
        corresponding internal theme properties. It supports both direct theme
        property overrides and simplified style keys.
        
        Args:
            style_overrides (Dict[str, Any]): Dictionary of style overrides
                Supported simplified keys:
                - 'padding': Maps to PADDING_H
                - 'spacing': Maps to SPACING
                - 'anim_speed': Calculates new ANIM_DURATION_MS
                - 'text_scale': Scales BUTTON_FONT_PT and ARROW_SIZE
                - 'active_color': Maps to COLOR_BG_HOVER and COLOR_BG_PRESSED
                - 'text_color': Maps to COLOR_TEXT, COLOR_ARROW, and COLOR_ARROW_HOVER
        
        Returns:
            Dict[str, Any]: Converted style overrides with internal property names
        """
        overrides = {}
        # Direct mappings
        if 'padding' in style_overrides:
            overrides['PADDING_H'] = style_overrides['padding']
        if 'spacing' in style_overrides:
            overrides['SPACING'] = style_overrides['spacing']

        # Animation speed
        if 'anim_speed' in style_overrides:
            speed_factor = style_overrides['anim_speed']
            base_duration = AnimatedButton._ThemeConfig._BASE_ANIM_MS
            new_duration = int(round(base_duration / speed_factor))
            overrides['ANIM_DURATION_MS'] = new_duration

        # Text scale
        if 'text_scale' in style_overrides:
            text_scale_factor = style_overrides['text_scale']
            base_font_pt = AnimatedButton._ThemeConfig._BASE_FONT_PT
            base_arrow_size = AnimatedButton._ThemeConfig._BASE_VALUES['ARROW_SIZE']
            new_font_pt = int(round(base_font_pt * text_scale_factor))
            new_arrow_size = int(round(base_arrow_size * text_scale_factor))
            overrides['BUTTON_FONT_PT'] = new_font_pt
            overrides['ARROW_SIZE'] = new_arrow_size

        # Active color
        if 'active_color' in style_overrides:
            color = style_overrides['active_color']
            overrides['COLOR_BG_HOVER'] = color
            overrides['COLOR_BG_PRESSED'] = color

        # Text color
        if 'text_color' in style_overrides:
            color = style_overrides['text_color']
            overrides['COLOR_TEXT'] = color
            overrides['COLOR_ARROW'] = color
            overrides['COLOR_ARROW_HOVER'] = color

        # Pass through any other keys
        for key in style_overrides:
            if key not in ['padding', 'spacing', 'anim_speed', 'text_scale', 'active_color', 'text_color']:
                overrides[key] = style_overrides[key]

        return overrides

    def _rebuild_theme_with_overrides(self) -> _ThemeConfig:
        """
        Rebuilds the theme configuration using current scale and style overrides.
        
        Returns:
            _ThemeConfig: New theme configuration instance
        """
        return self._ThemeConfig.create(scale=self._scale, overrides=self._style_overrides)

    def _apply_theme_update(self):
        """
        Applies changes after theme is rebuilt.
        
        This method handles all necessary updates when the theme changes:
        1. Updates child widgets (fonts, sizes, internal themes)
        2. Recalculates widths
        3. Updates height
        4. Rebuilds animations
        5. Resets visual state
        6. Applies stylesheets
        7. Updates layout
        """
        logger.debug(f"Applying theme update for '{self._initial_text}' (Scale: {self._scale}, Overrides: {list(self._style_overrides.keys())})")
        self._update_child_widget_themes_and_fonts()
        self._calculate_and_set_initial_widths()
        self.setFixedHeight(self._theme.MIN_HEIGHT)
        self._build_animations()

        # Reset visual state
        target_width = self._collapsed_width
        target_spin_opacity = 0.0
        target_border_opacity = 1.0
        target_spin_container_visible = False
        target_spin_container_width = 0

        if self._state in (ButtonState.EXPANDED, ButtonState.EXPANDING, ButtonState.PRESSED_TO_EXPAND):
            target_width = self._expanded_width
            target_spin_opacity = 1.0
            target_border_opacity = 0.0
            target_spin_container_visible = True
            target_spin_container_width = self._spinbox_container_target_width

        if hasattr(self, '_anim_group') and self._anim_group.state() == QParallelAnimationGroup.Running:
            self._anim_group.stop()

        self.width_anim = target_width
        self.spinbox_opacity_anim = target_spin_opacity
        self.border_opacity_anim = target_border_opacity

        self._spinbox_container_widget.setVisible(target_spin_container_visible)
        self._spinbox_container_widget.setFixedWidth(target_spin_container_width)

        self.apply_styles()
        if self.layout(): self.layout().invalidate()
        self.updateGeometry()
        self.update()

    # --- Properties and Core Methods (use self._theme, mostly unchanged from previous version) ---

    @pyqtProperty(float)
    def width_anim(self) -> float: return self._width_anim_value
    @width_anim.setter
    def width_anim(self, value: float):
        self._width_anim_value = value
        self.setFixedWidth(int(value))

    @pyqtProperty(float)
    def spinbox_opacity_anim(self) -> float: return self._spinbox_opacity_anim_value
    @spinbox_opacity_anim.setter
    def spinbox_opacity_anim(self, value: float):
        self._spinbox_opacity_anim_value = value
        if self._spinbox_opacity_effect:
            self._spinbox_opacity_effect.setOpacity(value)

        opaque = value >= 0.1
        self._spinbox.setEnabled(opaque)
        self._up_arrow.setEnabled(opaque)
        self._down_arrow.setEnabled(opaque)

        if opaque and not self._spinbox_container_widget.isVisible() and self._state == ButtonState.EXPANDING:
             self._spinbox_container_widget.setVisible(True)
             self._spinbox_container_widget.setFixedWidth(self._spinbox_container_target_width)
        elif not opaque and self._spinbox_container_widget.isVisible() and self._state == ButtonState.COLLAPSING:
             if value < 0.01:
                 self._spinbox_container_widget.setVisible(False)
                 self._spinbox_container_widget.setFixedWidth(0)

    @pyqtProperty(float)
    def border_opacity_anim(self) -> float: return self._border_opacity_anim_value
    @border_opacity_anim.setter
    def border_opacity_anim(self, value: float):
        self._border_opacity_anim_value = value; self.update()

    def _update_child_widget_themes_and_fonts(self):
        """
        Updates child widgets with current theme settings.
        
        This method updates fonts, sizes, and other visual properties of all child widgets
        to match the current theme configuration. It handles:
        - Text label font and size
        - Spinbox font and size
        - Arrow buttons theme
        - Layout spacing
        """
        logger.debug(f"Updating child widgets for '{self._initial_text}'...")
        font_label = self._text_label.font()
        font_label.setPointSize(self._theme.BUTTON_FONT_PT)
        self._text_label.setFont(font_label)
        fm_text = QFontMetrics(self._text_label.font())
        self._text_width = fm_text.horizontalAdvance(self._initial_text)
        self._text_label.setFixedWidth(self._text_width)

        font_spin = self._spinbox.font()
        font_spin.setPointSize(self._theme.BUTTON_FONT_PT)
        self._spinbox.setFont(font_spin)
        # ——— динамический расчёт ширины spinbox ———
        # обновляем шрифт
        font_spin = self._spinbox.font()
        font_spin.setPointSize(self._theme.BUTTON_FONT_PT)
        self._spinbox.setFont(font_spin)

        fm_spin = QFontMetrics(self._spinbox.font())
        # сколько цифр в самом большом значении?
        max_val = self._spinbox.maximum()
        num_digits = max(1, len(str(max_val)))
        spin_content = "9" * num_digits
        spin_content_width = fm_spin.horizontalAdvance(spin_content)

        # подхватываем внутренние отступы QLineEdit, если есть
        extra = 0
        if hasattr(self._spinbox, 'lineEdit') and self._spinbox.lineEdit():
            m = self._spinbox.lineEdit().textMargins()
            extra = m.left() + m.right()

        # задаём итоговую ширину
        self._spinbox.setFixedWidth(
            spin_content_width
            + 2 * self._theme.SPINBOX_PADDING_H
            + extra
        )



        max_val = self._spinbox.maximum()
        num_digits = max(1, len(str(max_val)))
        spin_content = "9" * num_digits
        spin_content_width = fm_spin.horizontalAdvance(spin_content)
        self._spinbox.setFixedWidth(spin_content_width + 2 * self._theme.SPINBOX_PADDING_H)

        spin_height = self._theme.MIN_HEIGHT - 2 * self._theme.PADDING_V
        self._spinbox.setFixedHeight(max(10, spin_height))

        self._up_arrow.update_theme(self._theme)
        self._down_arrow.update_theme(self._theme)

        arrows_layout = self._up_arrow.parentWidget().layout()
        if arrows_layout:
            arrows_layout.setSpacing(max(0, self._theme.PADDING_V // 4))


    def _setup_widget_flags(self):
        """
        Sets up initial widget flags and properties.
        
        Configures the widget's size policy, mouse tracking, focus policy,
        and styled background attribute.
        """
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def _create_widgets(self):
        """
        Creates and initializes all child widgets.
        
        This method creates:
        - Text label
        - Spinbox container with opacity effect
        - Spinbox
        - Arrow buttons
        - Layouts for all components
        """
        self._text_label = QLabel(self._initial_text, self)

        self._spinbox_container_widget = QWidget(self)
        self._spinbox_container_widget.setAttribute(Qt.WA_TranslucentBackground, True)
        self._spinbox_opacity_effect = QGraphicsOpacityEffect(self._spinbox_container_widget)
        self._spinbox_container_widget.setGraphicsEffect(self._spinbox_opacity_effect)
        self._spinbox_opacity_effect.setOpacity(0.0)
        self._spinbox_container_widget.setVisible(False)
        self._spinbox_container_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        self._spinbox = _ValueSpinBox(self._spinbox_container_widget)
        self._spinbox.setButtonSymbols(QSpinBox.NoButtons)
        self._spinbox.setRange(0, 9999)
        self._spinbox.setValue(self._current_value)
        self._spinbox.setAlignment(Qt.AlignCenter)
        self._spinbox.setEnabled(False)

        arrows_widget = QWidget(self._spinbox_container_widget)
        arrows_layout = QVBoxLayout(arrows_widget)
        arrows_layout.setContentsMargins(0, 0, 0, 0)
        arrows_layout.setSpacing(max(0, self._theme.PADDING_V // 4))

        self._up_arrow = _ArrowButton("up", self._theme, arrows_widget)
        self._down_arrow = _ArrowButton("down", self._theme, arrows_widget)

        arrows_layout.addWidget(self._up_arrow)
        arrows_layout.addWidget(self._down_arrow)

        spin_container_layout = QHBoxLayout(self._spinbox_container_widget)
        spin_container_layout.setContentsMargins(0, 0, 0, 0)
        spin_container_layout.setSpacing(0)
        spin_container_layout.addWidget(self._spinbox)
        spin_container_layout.addWidget(arrows_widget)

        self._update_child_widget_themes_and_fonts()


    def _setup_layout(self):
        """
        Sets up the main layout structure.
        
        Creates and configures the main horizontal layout with:
        - Left padding spacer
        - Text label
        - Inter-widget spacer
        - Spinbox container
        - Right padding spacer
        """
        self._main_layout = QHBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        self._left_padding_spacer = QSpacerItem(0, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
        self._inter_widget_spacer = QSpacerItem(0, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
        self._right_padding_spacer = QSpacerItem(0, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)

        self._main_layout.addSpacerItem(self._left_padding_spacer)
        self._main_layout.addWidget(self._text_label)
        self._main_layout.addSpacerItem(self._inter_widget_spacer)
        self._main_layout.addWidget(self._spinbox_container_widget)
        self._main_layout.addSpacerItem(self._right_padding_spacer)

        self._update_layout_spacers()
        self._update_spin_container_layout()


    def _update_layout_spacers(self):
        """
        Updates the main layout spacers based on current theme.
        
        Adjusts the size of padding and spacing spacers to match
        the current theme's PADDING_H and SPACING values.
        """
        logger.debug(f"Updating layout spacers for '{self._initial_text}': HPad={self._theme.PADDING_H}, Spacing={self._theme.SPACING}")
        self._left_padding_spacer.changeSize(self._theme.PADDING_H, 0)
        self._inter_widget_spacer.changeSize(self._theme.SPACING, 0)
        self._right_padding_spacer.changeSize(self._theme.PADDING_H, 0)
        if self.layout(): self.layout().invalidate()

    def _update_spin_container_layout(self):
        """
        Updates the spinbox container layout settings.
        
        Configures margins and spacing for the spinbox container layout
        based on current theme settings.
        """
        spin_container_layout = self._spinbox_container_widget.layout()
        if spin_container_layout:
            spin_container_layout.setContentsMargins(0, self._theme.PADDING_V, 0, self._theme.PADDING_V)
            spin_arrow_spacing = max(1, int(round(2 * self._scale)))
            spin_container_layout.setSpacing(spin_arrow_spacing)
            logger.debug(f"Updating spin container layout for '{self._initial_text}': VPad={self._theme.PADDING_V}, Spacing={spin_arrow_spacing}")


    def _calculate_and_set_initial_widths(self):
        """
        Calculates and sets the initial widths for collapsed and expanded states.
        
        This method:
        1. Updates layout spacers and spin container layout
        2. Updates child widgets with current theme
        3. Calculates spinbox container width
        4. Calculates collapsed and expanded widths
        5. Restores original state
        """
        logger.debug(f"Recalculating widths for '{self._initial_text}'...")
        
        self._update_layout_spacers()
        self._update_spin_container_layout()
        self._update_child_widget_themes_and_fonts()
        
        current_spin_visibility = self._spinbox_container_widget.isVisible()
        current_spin_fixed_width = self._spinbox_container_widget.width()
        
        self._spinbox_container_widget.setVisible(True)
        self._spinbox_container_widget.setMinimumWidth(0)
        self._spinbox_container_widget.setMaximumWidth(QWIDGETSIZE_MAX)
        
        spin_container_layout = self._spinbox_container_widget.layout()
        if spin_container_layout:
            spin_container_layout.invalidate()
            spin_container_layout.activate()
        
        spinbox_width = self._spinbox.sizeHint().width()
        arrows_widget = self._up_arrow.parentWidget()
        arrows_width = arrows_widget.sizeHint().width()
        spin_arrow_spacing = spin_container_layout.spacing()
        spin_container_margins = spin_container_layout.contentsMargins()
        margin_width = spin_container_margins.left() + spin_container_margins.right()
        
        self._spinbox_container_target_width = (
            spinbox_width + arrows_width + spin_arrow_spacing + margin_width
        )
        
        logger.debug(f"  Spinbox container target width: {self._spinbox_container_target_width}")
        
        self._spinbox_container_widget.setVisible(current_spin_visibility)
        self._spinbox_container_widget.setFixedWidth(current_spin_fixed_width)
        if not current_spin_visibility:
            self._spinbox_container_widget.setFixedWidth(0)
        
        self._collapsed_width = (
            self._theme.PADDING_H + self._text_width + self._theme.PADDING_H
        )
        self._expanded_width = (
            self._theme.PADDING_H + self._text_width + self._theme.SPACING +
            self._spinbox_container_target_width + self._theme.PADDING_H
        )
        
        logger.debug(f"  Calculated widths: Collapsed={self._collapsed_width}, Expanded={self._expanded_width}")

    def apply_styles(self):
        """
        Applies stylesheets based on the current theme.
        
        Sets up styles for:
        - Text label
        - Spinbox
        - Spinbox container
        Uses colors and dimensions from the current theme configuration.
        """
        logger.debug(f"Applying styles for '{self._initial_text}'...")
        self._text_label.setStyleSheet(f"color:{self._theme.COLOR_TEXT.name()}; background:transparent;")

        spinbox_bg = 'transparent'
        if self._theme.SHOWBACKGROUND:
            pass

        spinbox_qss = f"""
            QSpinBox {{
                background: {spinbox_bg};
                border: none;
                border-radius:{self._theme.SPINBOX_BORDER_RADIUS}px;
                color:{self._theme.COLOR_TEXT.name()};
                selection-background-color:{self._theme.COLOR_ACCENT.name()};
                padding:{self._theme.SPINBOX_PADDING_V}px {self._theme.SPINBOX_PADDING_H}px;
                font-size:{self._theme.BUTTON_FONT_PT}pt;
            }}
            QSpinBox QLineEdit {{
                background:transparent;
                font-size:{self._theme.BUTTON_FONT_PT}pt;
                color:{self._theme.COLOR_TEXT.name()};
                border: none;
            }}
        """
        self._spinbox.setStyleSheet(spinbox_qss)
        self._spinbox_container_widget.setStyleSheet(f"background: transparent; border: none;")

        line_edit = self._spinbox.lineEdit()
        if line_edit:
            fm = QFontMetrics(line_edit.font())
        else:
            fm = QFontMetrics(self._spinbox.font())
        # сколько цифр максимально может быть
        max_val = self._spinbox.maximum()
        num_digits = max(1, len(str(max_val)))
        spin_content = "9" * num_digits
        spin_content_width = fm.horizontalAdvance(spin_content)
        # устанавливаем ширину с учётом horizontal padding из темы
        self._spinbox.setFixedWidth(
            spin_content_width + 2 * self._theme.SPINBOX_PADDING_H
        )

        self._calculate_and_set_initial_widths()
        if self._state in (ButtonState.EXPANDED, ButtonState.EXPANDING, ButtonState.PRESSED_TO_EXPAND):
            self.width_anim = self._expanded_width
        else:
            self.width_anim = self._collapsed_width
        self.updateGeometry()
        self.update()

    def _build_animations(self):
        """
        Builds or rebuilds the animation group based on current theme durations.
        
        Creates three parallel animations:
        1. Width animation for expanding/collapsing
        2. Spinbox opacity animation
        3. Border opacity animation
        
        All animations use the current theme's duration and appropriate easing curves.
        """
        logger.debug(f"Building animations for '{self._initial_text}' with duration: {self._theme.ANIM_DURATION_MS} ms")
        if hasattr(self, '_anim_group') and self._anim_group:
            if self._anim_group.state() == QParallelAnimationGroup.Running:
                self._anim_group.stop()
            try: self._anim_group.finished.disconnect(self._on_animation_finished)
            except TypeError: pass

        self._anim_group = QParallelAnimationGroup(self)

        anim_width = QPropertyAnimation(self, b"width_anim", self)
        anim_width.setDuration(self._theme.ANIM_DURATION_MS)
        anim_width.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_group.addAnimation(anim_width)

        anim_spin_opacity = QPropertyAnimation(self, b"spinbox_opacity_anim", self)
        anim_spin_opacity.setDuration(int(self._theme.ANIM_DURATION_MS * 0.7))
        anim_spin_opacity.setEasingCurve(QEasingCurve.Linear)
        self._anim_group.addAnimation(anim_spin_opacity)

        anim_border_opacity = QPropertyAnimation(self, b"border_opacity_anim", self)
        anim_border_opacity.setDuration(self._theme.ANIM_DURATION_MS)
        anim_border_opacity.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_group.addAnimation(anim_border_opacity)

        self._anim_group.finished.connect(self._on_animation_finished)


    def _set_state(self, new_state: ButtonState):
        """
        Updates the widget's state and triggers necessary updates.
        
        Args:
            new_state (ButtonState): New state to set
        """
        if self._state == new_state: return
        logger.debug(f"State changing for '{self._initial_text}' from {self._state} to {new_state}")
        self._state = new_state
        self.setProperty("expanded", new_state == ButtonState.EXPANDED)
        self.update()

    def _on_spinbox_value_changed(self, value: int):
        """
        Handles value changes from the spinbox.
        
        Args:
            value (int): New value from the spinbox
        """
        self._current_value = value
        logger.debug(f"valueChanged «{self._initial_text}» → {value}")
        self.valueChanged.emit(value)
        if self._on_update: self._on_update(value)

    def _connect_signals_slots(self):
        """
        Connects all necessary signals and slots.
        
        Sets up connections for:
        - Spinbox value changes
        - Arrow button clicks
        """
        self._spinbox.valueChanged.connect(self._on_spinbox_value_changed)
        self._up_arrow.clicked.connect(self._spinbox.stepUp)
        self._down_arrow.clicked.connect(self._spinbox.stepDown)

    def value(self) -> int:
        """
        Gets the current value of the spinbox.
        
        Returns:
            int: Current value
        """
        return self._spinbox.value()

    def setValue(self, val: int):
        """
        Sets the value of the spinbox.
        
        Args:
            val (int): New value to set
        """
        if self._spinbox.value() != val: self._spinbox.setValue(val)

    def expand_button(self):
        """
        Expands the button to show the spinbox.
        
        This method:
        1. Checks if expansion is allowed in current state
        2. Sets up the spinbox container
        3. Starts the expansion animation
        4. Emits the clicked signal
        """
        if self._state not in (ButtonState.IDLE, ButtonState.HOVERED, ButtonState.PRESSED_TO_EXPAND): return
        logger.debug(f"Expanding «{self._initial_text}»")
        self._spinbox_container_widget.setFixedWidth(self._spinbox_container_target_width)
        self._set_state(ButtonState.EXPANDING)

        if self._anim_group.state() == QParallelAnimationGroup.Running: self._anim_group.stop()
        self._anim_group.animationAt(0).setStartValue(self.width_anim)
        self._anim_group.animationAt(0).setEndValue(self._expanded_width)
        self._anim_group.animationAt(1).setStartValue(self.spinbox_opacity_anim)
        self._anim_group.animationAt(1).setEndValue(1.0)
        self._anim_group.animationAt(2).setStartValue(self.border_opacity_anim)
        self._anim_group.animationAt(2).setEndValue(0.0)
        self._anim_group.setDirection(QParallelAnimationGroup.Forward)
        self._anim_group.start()
        self.clicked.emit()

    def collapse_button(self):
        """
        Collapses the button to hide the spinbox.
        
        This method:
        1. Checks if collapse is allowed in current state
        2. Starts the collapse animation
        3. Updates the state
        """
        if self._state not in (ButtonState.EXPANDED, ButtonState.EXPANDING): return
        logger.info(f"Collapsing «{self._initial_text}»")
        self._set_state(ButtonState.COLLAPSING)

        if self._anim_group.state() == QParallelAnimationGroup.Running: self._anim_group.stop()
        self._anim_group.animationAt(0).setStartValue(self.width_anim)
        self._anim_group.animationAt(0).setEndValue(self._collapsed_width)
        self._anim_group.animationAt(1).setStartValue(self.spinbox_opacity_anim)
        self._anim_group.animationAt(1).setEndValue(0.0)
        self._anim_group.animationAt(2).setStartValue(self.border_opacity_anim)
        self._anim_group.animationAt(2).setEndValue(1.0)
        self._anim_group.setDirection(QParallelAnimationGroup.Forward)
        self._anim_group.start()

    def _on_animation_finished(self):
        """
        Handles completion of animations.
        
        This method:
        1. Updates the state based on the completed animation
        2. Sets final values for width, opacity, and visibility
        3. Handles focus and selection for the spinbox
        4. Updates the geometry
        """
        logger.debug(f"Animation finished for '{self._initial_text}'. State: {self._state}, width: {self.width()}, spin_op: {self.spinbox_opacity_anim:.2f}")
        if self._state == ButtonState.EXPANDING:
            self._set_state(ButtonState.EXPANDED)
            self.width_anim = self._expanded_width
            self.spinbox_opacity_anim = 1.0
            self.border_opacity_anim = 0.0
            self._spinbox_container_widget.setVisible(True)
            self._spinbox_container_widget.setFixedWidth(self._spinbox_container_target_width)
            if self._spinbox.isEnabled(): self._spinbox.setFocus(); self._spinbox.selectAll()
        elif self._state == ButtonState.COLLAPSING:
            self._set_state(ButtonState.IDLE)
            self.width_anim = self._collapsed_width
            self.spinbox_opacity_anim = 0.0
            self.border_opacity_anim = 1.0
            if self._spinbox_container_widget.isVisible(): self._spinbox_container_widget.setVisible(False)
            if self._spinbox_container_widget.width() != 0: self._spinbox_container_widget.setFixedWidth(0)
        self.updateGeometry()

    def mousePressEvent(self, event: QMouseEvent):
        """
        Handles mouse press events.
        
        Args:
            event (QMouseEvent): The mouse event
        """
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            if self._state in (ButtonState.IDLE, ButtonState.HOVERED):
                self._set_state(ButtonState.PRESSED_TO_EXPAND)
                self.expand_button()
            elif self._state == ButtonState.EXPANDED:
                if not self._spinbox_container_widget.geometry().contains(event.pos()):
                    self.collapse_button()

    def enterEvent(self, event: QEvent):
        """
        Handles mouse enter events.
        
        Args:
            event (QEvent): The enter event
        """
        super().enterEvent(event)
        self._is_hovered_visual = True
        if self._state == ButtonState.IDLE: self._set_state(ButtonState.HOVERED)
        self.update()

    def leaveEvent(self, event: QEvent):
        """
        Handles mouse leave events.
        
        Args:
            event (QEvent): The leave event
        """
        super().leaveEvent(event)
        self._is_hovered_visual = False
        if self._state == ButtonState.HOVERED: self._set_state(ButtonState.IDLE)
        self.update()

    def focusInEvent(self, event: QFocusEvent):
        """
        Handles focus in events.
        
        Args:
            event (QFocusEvent): The focus event
        """
        super().focusInEvent(event)
        self._has_keyboard_focus = True
        self.update()

    def focusOutEvent(self, event: QFocusEvent):
        """
        Handles focus out events.
        
        Args:
            event (QFocusEvent): The focus event
        """
        super().focusOutEvent(event)
        self._has_keyboard_focus = False
        if self._state == ButtonState.EXPANDED:
            QTimer.singleShot(50, self._check_and_collapse_on_focus_out)
        self.update()

    def _check_and_collapse_on_focus_out(self):
        """
        Checks if the widget should collapse after losing focus.
        
        This method:
        1. Checks if the widget is in expanded state
        2. Verifies if focus has moved outside the widget hierarchy
        3. Collapses the widget if focus has moved outside
        """
        if self._state == ButtonState.EXPANDED:
            focused_widget = QApplication.focusWidget()
            should_collapse = True
            if focused_widget:
                widget_to_check = focused_widget
                while widget_to_check:
                    if widget_to_check == self: should_collapse = False; break
                    widget_to_check = widget_to_check.parentWidget()
            if should_collapse: logger.debug("Focus left, collapsing."); self.collapse_button()

    def keyPressEvent(self, event: QKeyEvent):
        """
        Handles key press events.
        
        Args:
            event (QKeyEvent): The key event
        """
        super().keyPressEvent(event)
        if event.key() in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Space):
            if self.hasFocus() or self._text_label.hasFocus():
                if self._state in (ButtonState.IDLE, ButtonState.HOVERED): self.expand_button()
                elif self._state == ButtonState.EXPANDED: self.collapse_button()

    def paintEvent(self, event: QPaintEvent):
        """
        Handles painting of the widget.
        
        This method:
        1. Draws the background with appropriate color based on state
        2. Draws the border with proper opacity
        3. Draws the focus indicator if needed
        
        Args:
            event (QPaintEvent): The paint event
        """
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

        bw = self._theme.BORDER_WIDTH
        draw_rect = QRectF(self.rect()).adjusted(bw / 2.0, bw / 2.0, -bw / 2.0, -bw / 2.0)
        r_val = min(self._theme.RADIUS, draw_rect.width() / 2.0, draw_rect.height() / 2.0)

        # Background
        if self._theme.SHOWBACKGROUND:
            bg_color = self._theme.COLOR_BG_IDLE
            if self._state in (ButtonState.PRESSED_TO_EXPAND, ButtonState.EXPANDING, ButtonState.EXPANDED, ButtonState.COLLAPSING):
                bg_color = self._theme.COLOR_BG_PRESSED
            elif self._is_hovered_visual:
                bg_color = self._theme.COLOR_BG_HOVER

            path = QPainterPath()
            path.addRoundedRect(draw_rect, r_val, r_val)
            painter.fillPath(path, bg_color)

        # Border
        if self.border_opacity_anim > 0.01 or not self._theme.SHOWBACKGROUND:
            pen = QPen()
            pen.setWidthF(bw)
            pen.setCosmetic(True)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            border_color_base = self._theme.COLOR_BORDER_HOVER if self._is_hovered_visual else self._theme.COLOR_BORDER_IDLE
            final_border_color = QColor(border_color_base)
            border_alpha = self.border_opacity_anim if self._theme.SHOWBACKGROUND else 1.0
            final_border_color.setAlphaF(max(0.0, min(1.0, border_alpha)))

            if final_border_color.alphaF() > 0.01:
                pen.setColor(final_border_color)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                border_path = QPainterPath()
                border_path.addRoundedRect(draw_rect, r_val, r_val)
                painter.drawPath(border_path)

        # Focus Indicator
        if self._has_keyboard_focus and self._theme.FOCUSON:
            focus_pen = QPen(self._theme.COLOR_ACCENT, 1.5, Qt.DashLine)
            focus_pen.setCosmetic(True)
            painter.setPen(focus_pen)
            painter.setBrush(Qt.NoBrush)
            focus_rect = draw_rect.adjusted(bw / 2.0 + 0.5, bw / 2.0 + 0.5, -bw / 2.0 - 0.5, -bw / 2.0 - 0.5)
            focus_r = max(0, r_val - (bw / 2.0 + 0.5))
            painter.drawRoundedRect(focus_rect, focus_r, focus_r)

    def sizeHint(self) -> QSize:
        """
        Returns the recommended size for the widget.
        
        Returns:
            QSize: Recommended size based on current state and animations
        """
        width = self.width_anim
        if not (hasattr(self, '_anim_group') and self._anim_group.state() == QParallelAnimationGroup.Running):
            if self._state in (ButtonState.IDLE, ButtonState.HOVERED, ButtonState.COLLAPSING):
                width = self._collapsed_width
            else:
                width = self._expanded_width
        return QSize(int(round(width)), self._theme.MIN_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        """
        Returns the minimum size for the widget.
        
        Returns:
            QSize: Minimum size based on collapsed width
        """
        return QSize(int(round(self._collapsed_width)), self._theme.MIN_HEIGHT)


# ------ Demo scaffolding -----------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    default_font = QFont("Segoe UI", 10)
    app.setFont(default_font)

    def on_button_value_update(value: int):
        # Optional: Add logging or UI update based on value change
        # print(f"Demo: Button value updated to {value}")
        pass

    # --- 1. Demo Window ---
    demo_window = QWidget()
    demo_window.setWindowTitle("AnimatedButton Combined Demo") # Set Title
    demo_window.setGeometry(150, 150, 500, 600) # Adjusted size
    demo_window.setStyleSheet("background-color:#1E1E1E; color: #D0D0D0;") # Dark background

    main_demo_layout = QVBoxLayout(demo_window)
    main_demo_layout.setSpacing(15) # Distance between widgets
    main_demo_layout.setContentsMargins(20, 20, 20, 20) # Margins
    main_demo_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter) # Align top-center

    # --- 2. Scale Demonstration ---
    scales_to_show = [0.8, 1.0, 1.3, 1.75]
    button_labels = ["Scale: 80%", "Scale: 100% (Default)", "Scale: 130%", "Scale: 175%"]
    demo_buttons = [] # Store buttons for later access

    for idx, current_scale in enumerate(scales_to_show):
        label = button_labels[idx] if idx < len(button_labels) else f"Scale: {current_scale*100:.0f}%"
        animated_btn = AnimatedButton(
            initial_text=label,
            initial_value=idx * 10 + 5, # Different initial values
            scale=current_scale, # Set initial scale
            on_update=on_button_value_update
        )
        # Center each button horizontally within the layout
        h_layout = QHBoxLayout()
        h_layout.addStretch(1)
        h_layout.addWidget(animated_btn)
        h_layout.addStretch(1)
        main_demo_layout.addLayout(h_layout) # Add the horizontal layout containing the button
        demo_buttons.append(animated_btn)

    main_demo_layout.addSpacing(20) # Add some space

    # --- Scale Toggle Button ---
    scale_toggle_button = QPushButton("Toggle First Button Scale (0.8 / 1.5)")
    scale_toggle_button.setStyleSheet("color: #D0D0D0; background-color: #333333; border: 1px solid #555555; padding: 6px;")

    def toggle_first_button_scale():
        if not demo_buttons: return
        first_btn_widget = demo_buttons[0]
        current_scale = first_btn_widget._scale # Access scale directly for toggle logic
        new_scale = 1.5 if abs(current_scale - 0.8) < 0.01 else 0.8
        logger.info(f"Toggling scale of '{first_btn_widget._initial_text}' to {new_scale}")
        first_btn_widget.set_scale(new_scale) # Use the set_scale method

    scale_toggle_button.clicked.connect(toggle_first_button_scale)
    main_demo_layout.addWidget(scale_toggle_button, alignment=Qt.AlignCenter) # Center the toggle button

    main_demo_layout.addSpacing(20) # Add more space

    # --- 3. Custom Styles Demonstration ---
    custom_style_button = QPushButton("Apply Custom Style")
    custom_style_button.setStyleSheet("color: #101010; background-color: #FFA030; border: 1px solid #FFC070; padding: 8px; font-weight: bold;")

    def apply_the_custom_style():
        if not demo_buttons: return

        # Base values needed for calculation (should match _ThemeConfig._BASE_...)
        base_font_pt = AnimatedButton._ThemeConfig._BASE_FONT_PT

        # Define different styles for each button
        custom_styles = [
            {'PADDING_H': 30, 'SPACING': 30},  # Style for first button
            {'active_color': '#FF8800'},  # Style for second button
            {'text_color': '#00FFCC'},  # Style for third button
            {'BUTTON_FONT_PT': int(base_font_pt * 1.5), 'ANIM_DURATION_MS': 0.5}  # Style for fourth button
        ]
        
        logger.info("Applying custom styles to buttons...")
        for i, button in enumerate(demo_buttons):
            if i < len(custom_styles):
                style = custom_styles[i]
                logger.info(f"Applying style {i+1} to button {i+1}: {style}")
                button.apply_custom_style(style)

    custom_style_button.clicked.connect(apply_the_custom_style)
    main_demo_layout.addWidget(custom_style_button, alignment=Qt.AlignCenter) # Center the style button

    # --- Add stretch to push everything up ---
    main_demo_layout.addStretch(1)

    demo_window.show()
    sys.exit(app.exec_())
