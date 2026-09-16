"""Pydantic contracts shared by desktop tools and a future UI Automation executor."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, model_validator

from browser_use.desktop.policy import AccessDecision, DesktopApplication, DesktopOperation


class DesktopToolInput(BaseModel):
	"""Base class that rejects unknown model-generated desktop-tool parameters."""

	model_config = ConfigDict(extra='forbid')


class DesktopControlType(StrEnum):
	"""UI Automation control types supported by the first desktop-tool interface."""

	BUTTON = 'Button'
	EDIT = 'Edit'
	LIST_ITEM = 'ListItem'
	TAB_ITEM = 'TabItem'
	TREE_ITEM = 'TreeItem'
	TEXT = 'Text'
	WINDOW = 'Window'
	OTHER = 'Other'


class DesktopScrollDirection(StrEnum):
	"""Directions accepted by the read-only scrolling tool."""

	UP = 'up'
	DOWN = 'down'


class DesktopElementSelector(DesktopToolInput):
	"""Stable UI Automation properties used to locate an element without coordinates."""

	name: str | None = Field(default=None, min_length=1, max_length=200)
	automation_id: str | None = Field(default=None, min_length=1, max_length=200)
	control_type: DesktopControlType | None = None
	parent_element_id: str | None = Field(default=None, min_length=1, max_length=200)

	@model_validator(mode='after')
	def require_selector_criterion(self) -> 'DesktopElementSelector':
		"""Reject selectors that would search every element in a window."""
		if not any((self.name, self.automation_id, self.control_type, self.parent_element_id)):
			raise ValueError('Provide at least one of name, automation_id, control_type, or parent_element_id.')
		return self


class ListDesktopWindowsAction(DesktopToolInput):
	"""Request running windows for allowlisted applications only."""


class LaunchOrFocusDesktopAppAction(DesktopToolInput):
	"""Start an allowlisted application or focus its existing window."""

	application: DesktopApplication


class GetDesktopUiTreeAction(DesktopToolInput):
	"""Request a bounded UI Automation tree from one approved application."""

	application: DesktopApplication
	max_depth: int = Field(default=5, ge=1, le=12)
	max_nodes: int = Field(default=200, ge=1, le=500)


class FindDesktopElementAction(DesktopToolInput):
	"""Locate a bounded number of UI Automation elements in one approved application."""

	application: DesktopApplication
	selector: DesktopElementSelector
	max_results: int = Field(default=10, ge=1, le=25)


class ReadNavigateDesktopAction(DesktopToolInput):
	"""Select a proven read-navigation control without allowing a generic click."""

	application: DesktopApplication
	element_id: str = Field(min_length=1, max_length=200)
	expected_name: str = Field(min_length=1, max_length=200)
	expected_control_type: DesktopControlType = Field(
		description='Must be a list item, tab item, or tree item that only reveals existing content.'
	)

	@model_validator(mode='after')
	def require_read_navigation_control(self) -> 'ReadNavigateDesktopAction':
		"""Prevent the schema from expressing a click on a destructive control."""
		if self.expected_control_type not in {
			DesktopControlType.LIST_ITEM,
			DesktopControlType.TAB_ITEM,
			DesktopControlType.TREE_ITEM,
		}:
			raise ValueError('Read navigation only supports ListItem, TabItem, or TreeItem controls.')
		return self


class ScrollDesktopWindowAction(DesktopToolInput):
	"""Scroll a window only to reveal additional existing content."""

	application: DesktopApplication
	direction: DesktopScrollDirection = DesktopScrollDirection.DOWN
	pages: int = Field(default=1, ge=1, le=5)


class ExtractDesktopVisibleTextAction(DesktopToolInput):
	"""Extract a bounded amount of text that is currently visible in an approved application."""

	application: DesktopApplication
	element_id: str | None = Field(default=None, min_length=1, max_length=200)
	max_characters: int = Field(default=4_000, ge=1, le=8_000)


class CaptureDesktopWindowAction(DesktopToolInput):
	"""Capture the current application window when the UI tree cannot represent the needed content."""

	application: DesktopApplication


class InputDesktopTextAction(DesktopToolInput):
	"""Future-only high-risk text input contract; it is intentionally not registered in the read-only release."""

	application: DesktopApplication
	element_id: str = Field(min_length=1, max_length=200)
	text: str = Field(min_length=1, max_length=4_000)


class DesktopWindow(BaseModel):
	"""A non-content-bearing reference to an allowlisted application window."""

	model_config = ConfigDict(frozen=True)

	application: DesktopApplication
	window_id: str = Field(min_length=1, max_length=200)
	is_foreground: bool


class DesktopWindowList(BaseModel):
	"""The currently available allowlisted application windows."""

	windows: list[DesktopWindow]


class DesktopElement(BaseModel):
	"""A bounded UI Automation element representation returned to the model."""

	model_config = ConfigDict(frozen=True)

	element_id: str = Field(min_length=1, max_length=200)
	name: str = Field(default='', max_length=500)
	control_type: DesktopControlType
	automation_id: str | None = Field(default=None, max_length=200)
	is_enabled: bool
	is_visible: bool


class DesktopUiTree(BaseModel):
	"""A truncated UI Automation tree for one application window."""

	application: DesktopApplication
	elements: list[DesktopElement]
	is_truncated: bool


class DesktopElementMatches(BaseModel):
	"""The matching UI Automation elements for one selector."""

	application: DesktopApplication
	elements: list[DesktopElement]


class DesktopNavigationResult(BaseModel):
	"""The element selected by a verified read-navigation operation."""

	application: DesktopApplication
	focused_element_id: str


class DesktopScrollResult(BaseModel):
	"""The outcome of one bounded scroll operation."""

	application: DesktopApplication
	moved: bool
	end_reached: bool


class DesktopVisibleText(BaseModel):
	"""A bounded visible-text extraction from the approved application."""

	application: DesktopApplication
	text: str = Field(max_length=8_000)
	is_truncated: bool


class DesktopWindowCapture(BaseModel):
	"""An in-memory image payload for a window capture, never persisted by the interface itself."""

	application: DesktopApplication
	image_name: str = Field(min_length=1, max_length=200)
	image_base64: str = Field(min_length=1)


class DesktopToolResponse(BaseModel):
	"""Structured tool result supplied to the agent after authorization and execution."""

	application: DesktopApplication | None
	operation: DesktopOperation
	access: AccessDecision
	data: SerializeAsAny[BaseModel] | None = None
