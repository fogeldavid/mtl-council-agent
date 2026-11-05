"""Shared test setup."""

from streamlit.testing.v1.element_tree import ButtonGroup

_button_group_value = ButtonGroup.value.fget


def _as_list(self):
    value = _button_group_value(self)
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# Streamlit 1.54's AppTest treats a single-select segmented control's value as a
# list, so the language control's "EN" is read as "E", "N" and the rerun fails.
ButtonGroup.value = property(_as_list)
