"""Unit tests for the pywinauto UIA executor without operating a real desktop application."""

from dataclasses import dataclass

from browser_use.desktop.policy import DesktopApplication
from browser_use.desktop.uia_executor import PywinautoUiaExecutor
from browser_use.desktop.views import (
	DesktopControlType,
	DesktopElementSelector,
	FindDesktopElementAction,
	GetDesktopUiTreeAction,
)


@dataclass
class FakeElementInfo:
	"""Minimal UIA element metadata exposed by a fake pywinauto wrapper."""

	control_type: str
	automation_id: str | None = None
	process_id: int = 1


class FakeUiaWrapper:
	"""Small UIA wrapper double that supports tree traversal and element inspection."""

	def __init__(self, handle: int, name: str, control_type: str, children: list['FakeUiaWrapper'] | None = None):
		self.handle = handle
		self._name = name
		self.element_info = FakeElementInfo(control_type=control_type)
		self._children = children or []

	def children(self) -> list['FakeUiaWrapper']:
		return self._children

	def window_text(self) -> str:
		return self._name

	def is_visible(self) -> bool:
		return True

	def is_enabled(self) -> bool:
		return True


class StubUiaExecutor(PywinautoUiaExecutor):
	"""Executor variant that provides a fixed UIA window and never invokes Windows APIs in these unit tests."""

	def __init__(self, root: FakeUiaWrapper):
		super().__init__()
		self._root = root

	def _focused_window(self, application: DesktopApplication) -> FakeUiaWrapper:
		return self._root


def build_tree() -> FakeUiaWrapper:
	"""Create a visible root with a list item and a nested text node."""
	return FakeUiaWrapper(
		handle=100,
		name='微信',
		control_type='Window',
		children=[
			FakeUiaWrapper(
				handle=101,
				name='张三',
				control_type='ListItem',
				children=[FakeUiaWrapper(handle=102, name='下午三点开会', control_type='Text')],
			),
			FakeUiaWrapper(handle=103, name='布局容器', control_type='Pane'),
		],
	)


def test_ui_tree_is_bounded_and_maps_unknown_uia_controls():
	"""Expose only the requested depth and map provider-specific controls to the safe public enum."""
	executor = StubUiaExecutor(build_tree())

	tree = executor._get_ui_tree_blocking(GetDesktopUiTreeAction(application=DesktopApplication.WECHAT, max_depth=1))

	assert [element.name for element in tree.elements] == ['微信', '张三']
	assert tree.is_truncated is True
	assert tree.elements[1].control_type is DesktopControlType.LIST_ITEM


def test_find_element_uses_exact_selector_fields_and_returns_opaque_reference():
	"""Return the matching list item without relying on coordinates or fuzzy name matching."""
	executor = StubUiaExecutor(build_tree())
	params = FindDesktopElementAction(
		application=DesktopApplication.WECHAT,
		selector=DesktopElementSelector(name='张三', control_type=DesktopControlType.LIST_ITEM),
	)

	result = executor._find_element_blocking(params)

	assert len(result.elements) == 1
	assert result.elements[0].name == '张三'
	assert result.elements[0].element_id
