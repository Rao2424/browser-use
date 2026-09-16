"""Registration layer for read-only desktop tools backed by a future UI Automation executor."""

import json
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from browser_use.agent.views import ActionResult
from browser_use.desktop.policy import (
	DEFAULT_DESKTOP_ACCESS_POLICY,
	AccessDecision,
	AccessStatus,
	DesktopAccessPolicy,
	DesktopApplication,
	DesktopOperation,
	DesktopReadSessionGrant,
)
from browser_use.desktop.views import (
	CaptureDesktopWindowAction,
	DesktopElementMatches,
	DesktopNavigationResult,
	DesktopScrollResult,
	DesktopToolResponse,
	DesktopUiTree,
	DesktopVisibleText,
	DesktopWindow,
	DesktopWindowCapture,
	DesktopWindowList,
	ExtractDesktopVisibleTextAction,
	FindDesktopElementAction,
	GetDesktopUiTreeAction,
	LaunchOrFocusDesktopAppAction,
	ListDesktopWindowsAction,
	ReadNavigateDesktopAction,
	ScrollDesktopWindowAction,
)
from browser_use.tools.service import Tools


class DesktopAutomationExecutor(Protocol):
	"""Executor contract that an eventual pywinauto/UIA adapter must implement."""

	async def list_windows(self, applications: frozenset[DesktopApplication]) -> DesktopWindowList:
		"""Return windows belonging only to allowlisted applications."""
		...

	async def launch_or_focus(self, application: DesktopApplication) -> DesktopWindow:
		"""Launch or focus one application after it has passed policy authorization."""
		...

	async def get_ui_tree(self, params: GetDesktopUiTreeAction) -> DesktopUiTree:
		"""Return a bounded UI Automation tree for an authorized application."""
		...

	async def find_element(self, params: FindDesktopElementAction) -> DesktopElementMatches:
		"""Find UI Automation elements using a validated, coordinate-free selector."""
		...

	async def read_navigate(self, params: ReadNavigateDesktopAction) -> DesktopNavigationResult:
		"""Activate an executor-verified read-navigation control."""
		...

	async def scroll(self, params: ScrollDesktopWindowAction) -> DesktopScrollResult:
		"""Perform one bounded read-only scroll operation."""
		...

	async def extract_visible_text(self, params: ExtractDesktopVisibleTextAction) -> DesktopVisibleText:
		"""Extract bounded visible text from an authorized application."""
		...

	async def capture_window(self, params: CaptureDesktopWindowAction) -> DesktopWindowCapture:
		"""Capture an authorized application window in memory."""
		...


@dataclass(frozen=True)
class DesktopToolsRuntime:
	"""Runtime dependencies captured by registered desktop tool actions."""

	executor: DesktopAutomationExecutor
	policy: DesktopAccessPolicy = DEFAULT_DESKTOP_ACCESS_POLICY
	read_session_grant: DesktopReadSessionGrant | None = None


def _result(response: DesktopToolResponse, capture: DesktopWindowCapture | None = None) -> ActionResult:
	"""Serialize a structured desktop response without persisting application content."""
	payload = response.model_dump(mode='json', exclude_none=True)
	if capture is not None:
		payload['data'] = capture.model_dump(mode='json', exclude={'image_base64'})
	return ActionResult(
		extracted_content=json.dumps(payload, ensure_ascii=False),
		images=[{'name': capture.image_name, 'data': capture.image_base64}] if capture is not None else None,
		metadata={'desktop_operation': response.operation.value, 'desktop_access': response.access.status.value},
	)


def _authorized_response(
	runtime: DesktopToolsRuntime,
	application: DesktopApplication,
	operation: DesktopOperation,
) -> DesktopToolResponse | None:
	"""Return a denial result, or None when an executor may perform the operation."""
	decision = runtime.policy.authorize(application, operation, runtime.read_session_grant)
	if decision.is_allowed:
		return None
	return DesktopToolResponse(application=application, operation=operation, access=decision)


def _completed_response(
	application: DesktopApplication | None,
	operation: DesktopOperation,
	data: BaseModel,
) -> DesktopToolResponse:
	"""Build a successful structured response from an executor payload."""
	return DesktopToolResponse(
		application=application,
		operation=operation,
		access=AccessDecision(status=AccessStatus.ALLOWED, reason='The authorized desktop operation completed.'),
		data=data,
	)


def register_desktop_tools(tools: Tools, runtime: DesktopToolsRuntime) -> None:
	"""Register the first-release, read-only desktop tools on an existing agent tool registry."""

	@tools.action(
		'List only currently open windows belonging to allowlisted desktop applications. Does not return window titles or content.',
		param_model=ListDesktopWindowsAction,
	)
	async def desktop_list_windows(params: ListDesktopWindowsAction) -> ActionResult:
		data = await runtime.executor.list_windows(runtime.policy.allowed_applications)
		response = _completed_response(None, DesktopOperation.LIST_WINDOWS, data)
		return _result(response)

	@tools.action(
		'Launch or focus an allowlisted desktop application. This operation does not reveal application content.',
		param_model=LaunchOrFocusDesktopAppAction,
	)
	async def desktop_launch_or_focus(params: LaunchOrFocusDesktopAppAction) -> ActionResult:
		decision = runtime.policy.authorize(params.application, DesktopOperation.LAUNCH_OR_FOCUS)
		if not decision.is_allowed:
			return _result(
				DesktopToolResponse(application=params.application, operation=DesktopOperation.LAUNCH_OR_FOCUS, access=decision)
			)
		data = await runtime.executor.launch_or_focus(params.application)
		return _result(_completed_response(params.application, DesktopOperation.LAUNCH_OR_FOCUS, data))

	@tools.action(
		'Read a bounded UI Automation tree from an approved application. Requires an explicit read-session grant before content is returned.',
		param_model=GetDesktopUiTreeAction,
	)
	async def desktop_get_ui_tree(params: GetDesktopUiTreeAction) -> ActionResult:
		denied = _authorized_response(runtime, params.application, DesktopOperation.READ_UI_TREE)
		if denied:
			return _result(denied)
		return _result(
			_completed_response(params.application, DesktopOperation.READ_UI_TREE, await runtime.executor.get_ui_tree(params))
		)

	@tools.action(
		'Find a bounded number of UI elements in an approved application using name, AutomationId, control type, or parent element. Requires a read-session grant.',
		param_model=FindDesktopElementAction,
	)
	async def desktop_find_element(params: FindDesktopElementAction) -> ActionResult:
		denied = _authorized_response(runtime, params.application, DesktopOperation.FIND_UI_ELEMENT)
		if denied:
			return _result(denied)
		return _result(
			_completed_response(params.application, DesktopOperation.FIND_UI_ELEMENT, await runtime.executor.find_element(params))
		)

	@tools.action(
		'Select a verified list item, tab item, or tree item only to reveal existing content. Generic clicks are not available. Requires a read-session grant.',
		param_model=ReadNavigateDesktopAction,
	)
	async def desktop_read_navigate(params: ReadNavigateDesktopAction) -> ActionResult:
		denied = _authorized_response(runtime, params.application, DesktopOperation.READ_NAVIGATION)
		if denied:
			return _result(denied)
		return _result(
			_completed_response(
				params.application, DesktopOperation.READ_NAVIGATION, await runtime.executor.read_navigate(params)
			)
		)

	@tools.action(
		'Scroll an approved desktop application only to reveal more existing content. Requires a read-session grant.',
		param_model=ScrollDesktopWindowAction,
	)
	async def desktop_scroll(params: ScrollDesktopWindowAction) -> ActionResult:
		denied = _authorized_response(runtime, params.application, DesktopOperation.SCROLL)
		if denied:
			return _result(denied)
		return _result(_completed_response(params.application, DesktopOperation.SCROLL, await runtime.executor.scroll(params)))

	@tools.action(
		'Extract a bounded amount of currently visible text from an approved desktop application. Requires a read-session grant.',
		param_model=ExtractDesktopVisibleTextAction,
	)
	async def desktop_extract_visible_text(params: ExtractDesktopVisibleTextAction) -> ActionResult:
		denied = _authorized_response(runtime, params.application, DesktopOperation.EXTRACT_VISIBLE_TEXT)
		if denied:
			return _result(denied)
		return _result(
			_completed_response(
				params.application, DesktopOperation.EXTRACT_VISIBLE_TEXT, await runtime.executor.extract_visible_text(params)
			)
		)

	@tools.action(
		'Capture an approved application window only when the UI tree cannot represent needed content. Requires a read-session grant.',
		param_model=CaptureDesktopWindowAction,
	)
	async def desktop_capture_window(params: CaptureDesktopWindowAction) -> ActionResult:
		denied = _authorized_response(runtime, params.application, DesktopOperation.CAPTURE_WINDOW)
		if denied:
			return _result(denied)
		capture = await runtime.executor.capture_window(params)
		return _result(_completed_response(params.application, DesktopOperation.CAPTURE_WINDOW, capture), capture=capture)
