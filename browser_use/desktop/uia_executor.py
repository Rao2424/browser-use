"""Windows UI Automation executor implemented with pywinauto's UIA backend."""

import asyncio
import base64
import io
import sys
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psutil

from browser_use.desktop.policy import DEFAULT_DESKTOP_ACCESS_POLICY, DesktopAccessPolicy, DesktopApplication
from browser_use.desktop.views import (
	CaptureDesktopWindowAction,
	DesktopControlType,
	DesktopElement,
	DesktopElementMatches,
	DesktopNavigationResult,
	DesktopScrollResult,
	DesktopUiTree,
	DesktopVisibleText,
	DesktopWindow,
	DesktopWindowCapture,
	DesktopWindowList,
	ExtractDesktopVisibleTextAction,
	FindDesktopElementAction,
	GetDesktopUiTreeAction,
	ReadNavigateDesktopAction,
	ScrollDesktopWindowAction,
)


class DesktopAutomationError(RuntimeError):
	"""Raised when the UI Automation executor cannot safely complete an operation."""


@dataclass(frozen=True)
class _ElementReference:
	"""An in-memory binding between an opaque element ID and a live UIA wrapper."""

	application: DesktopApplication
	window_handle: int
	wrapper: Any


class PywinautoUiaExecutor:
	"""Perform bounded, read-only Windows interactions using UI Automation rather than coordinates."""

	def __init__(
		self,
		policy: DesktopAccessPolicy = DEFAULT_DESKTOP_ACCESS_POLICY,
		launch_commands: dict[DesktopApplication, str] | None = None,
		operation_timeout_seconds: float = 10.0,
		focus_attempts: int = 2,
	):
		"""Create an executor with trusted application commands and bounded UIA waits."""
		if sys.platform != 'win32':
			raise DesktopAutomationError('Windows UI Automation is only available on Windows hosts.')
		if operation_timeout_seconds <= 0:
			raise ValueError('operation_timeout_seconds must be positive.')
		if focus_attempts < 1:
			raise ValueError('focus_attempts must be at least one.')

		self._policy = policy
		self._launch_commands = launch_commands or {}
		self._operation_timeout_seconds = operation_timeout_seconds
		self._focus_attempts = focus_attempts
		self._element_references: dict[str, _ElementReference] = {}

	async def list_windows(self, applications: frozenset[DesktopApplication]) -> DesktopWindowList:
		"""Return only visible windows whose executable is in the supplied application allowlist."""
		return await self._run_blocking(lambda: DesktopWindowList(windows=self._list_windows_blocking(applications)))

	async def launch_or_focus(self, application: DesktopApplication) -> DesktopWindow:
		"""Focus an existing window or start the application's trusted command and wait for its window."""
		return await self._run_blocking(lambda: self._launch_or_focus_blocking(application))

	async def get_ui_tree(self, params: GetDesktopUiTreeAction) -> DesktopUiTree:
		"""Read a bounded, flattened UIA tree and refresh opaque element references for the application."""
		return await self._run_blocking(lambda: self._get_ui_tree_blocking(params))

	async def find_element(self, params: FindDesktopElementAction) -> DesktopElementMatches:
		"""Find matching UIA elements using exact, coordinate-free selector fields."""
		return await self._run_blocking(lambda: self._find_element_blocking(params))

	async def read_navigate(self, params: ReadNavigateDesktopAction) -> DesktopNavigationResult:
		"""Select only a previously discovered list, tab, or tree item after re-validating its identity."""
		return await self._run_blocking(lambda: self._read_navigate_blocking(params))

	async def scroll(self, params: ScrollDesktopWindowAction) -> DesktopScrollResult:
		"""Scroll the first visible UIA control that exposes a vertical Scroll pattern."""
		return await self._run_blocking(lambda: self._scroll_blocking(params))

	async def extract_visible_text(self, params: ExtractDesktopVisibleTextAction) -> DesktopVisibleText:
		"""Extract de-duplicated visible UIA text with a strict character bound."""
		return await self._run_blocking(lambda: self._extract_visible_text_blocking(params))

	async def capture_window(self, params: CaptureDesktopWindowAction) -> DesktopWindowCapture:
		"""Capture the focused application window into an in-memory PNG payload."""
		return await self._run_blocking(lambda: self._capture_window_blocking(params))

	async def _run_blocking(self, operation):
		"""Run one synchronous pywinauto call off the event loop with a bounded wait."""
		try:
			return await asyncio.wait_for(asyncio.to_thread(operation), timeout=self._operation_timeout_seconds)
		except TimeoutError as error:
			raise DesktopAutomationError(
				f'Windows UI Automation exceeded the {self._operation_timeout_seconds:g}-second operation timeout.'
			) from error

	def _desktop(self):
		"""Create the UIA desktop root lazily so importing this module has no UI side effects."""
		try:
			from pywinauto import Desktop
		except ImportError as error:
			raise DesktopAutomationError('pywinauto is required for Windows UI Automation.') from error
		return Desktop(backend='uia')

	def _list_windows_blocking(self, applications: frozenset[DesktopApplication]) -> list[DesktopWindow]:
		"""Find visible top-level windows and filter them by the configured executable identities."""
		windows: list[DesktopWindow] = []
		for wrapper in self._desktop().windows(visible_only=True):
			application = self._application_for_wrapper(wrapper, applications)
			if application is None:
				continue
			windows.append(self._window_from_wrapper(application, wrapper))
		return windows

	def _launch_or_focus_blocking(self, application: DesktopApplication) -> DesktopWindow:
		"""Focus an existing matching window or start the trusted application command."""
		self._require_application_spec(application)
		windows = self._list_windows_blocking(frozenset({application}))
		if not windows:
			self._start_application(application)
			windows = self._wait_for_windows(application)
		if not windows:
			raise DesktopAutomationError(f'No visible {application.value} window appeared after launch.')

		selected_window = next((window for window in windows if window.is_foreground), windows[0])
		wrapper = self._wrapper_for_window_id(application, selected_window.window_id)
		self._focus_window(wrapper)
		return self._window_from_wrapper(application, wrapper)

	def _get_ui_tree_blocking(self, params: GetDesktopUiTreeAction) -> DesktopUiTree:
		"""Collect the visible UIA subtree with the requested node and depth limits."""
		window = self._focused_window(params.application)
		self._clear_element_references(params.application)
		elements: list[DesktopElement] = []
		truncated = False

		def visit(wrapper: Any, depth: int) -> None:
			nonlocal truncated
			if len(elements) >= params.max_nodes:
				truncated = True
				return
			if not self._is_visible(wrapper):
				return
			elements.append(self._remember_element(params.application, window, wrapper))
			if depth >= params.max_depth:
				if self._children(wrapper):
					truncated = True
				return
			for child in self._children(wrapper):
				visit(child, depth + 1)
				if truncated:
					return

		visit(window, depth=0)
		return DesktopUiTree(application=params.application, elements=elements, is_truncated=truncated)

	def _find_element_blocking(self, params: FindDesktopElementAction) -> DesktopElementMatches:
		"""Match current visible descendants exactly against the provided UIA selector."""
		window = self._focused_window(params.application)
		search_root = window
		if params.selector.parent_element_id is not None:
			search_root = self._resolve_element(params.application, params.selector.parent_element_id).wrapper

		matches: list[DesktopElement] = []
		for wrapper in [search_root, *self._descendants(search_root)]:
			if not self._is_visible(wrapper) or not self._matches_selector(wrapper, params):
				continue
			matches.append(self._remember_element(params.application, window, wrapper))
			if len(matches) >= params.max_results:
				break
		return DesktopElementMatches(application=params.application, elements=matches)

	def _read_navigate_blocking(self, params: ReadNavigateDesktopAction) -> DesktopNavigationResult:
		"""Select a current and verified read-navigation item through the UIA SelectionItem pattern."""
		reference = self._resolve_element(params.application, params.element_id)
		wrapper = reference.wrapper
		if self._control_type(wrapper) is not params.expected_control_type:
			raise DesktopAutomationError('The target control type no longer matches the approved read-navigation request.')
		if self._window_text(wrapper) != params.expected_name:
			raise DesktopAutomationError('The target name changed after discovery; refusing stale navigation.')
		if not self._is_visible(wrapper) or not self._is_enabled(wrapper):
			raise DesktopAutomationError('The approved read-navigation target is no longer visible and enabled.')

		self._focus_window(self._wrapper_for_handle(reference.window_handle))
		try:
			wrapper.select()
		except Exception as error:
			raise DesktopAutomationError('The verified UIA control does not support safe selection.') from error
		return DesktopNavigationResult(application=params.application, focused_element_id=params.element_id)

	def _scroll_blocking(self, params: ScrollDesktopWindowAction) -> DesktopScrollResult:
		"""Use a UIA Scroll pattern and report whether the vertical scroll percent changed."""
		window = self._focused_window(params.application)
		for candidate in [window, *self._descendants(window)]:
			if not self._is_visible(candidate):
				continue
			try:
				scroll_pattern = candidate.iface_scroll
				if not scroll_pattern.CurrentVerticallyScrollable:
					continue
				before = float(scroll_pattern.CurrentVerticalScrollPercent)
				candidate.scroll(params.direction.value, 'page', params.pages)
				after = float(scroll_pattern.CurrentVerticalScrollPercent)
				end_reached = after >= 100.0 if params.direction.value == 'down' else after <= 0.0
				return DesktopScrollResult(
					application=params.application,
					moved=before != after,
					end_reached=end_reached,
				)
			except Exception:
				continue
		raise DesktopAutomationError('No visible vertically scrollable UI Automation control was found.')

	def _extract_visible_text_blocking(self, params: ExtractDesktopVisibleTextAction) -> DesktopVisibleText:
		"""Build a deterministic, de-duplicated visible-text response from one UIA subtree."""
		if params.element_id is None:
			root = self._focused_window(params.application)
		else:
			root = self._resolve_element(params.application, params.element_id).wrapper

		segments: list[str] = []
		seen: set[str] = set()
		for wrapper in [root, *self._descendants(root)]:
			if not self._is_visible(wrapper):
				continue
			text = self._window_text(wrapper)
			if not text or text in seen:
				continue
			seen.add(text)
			segments.append(text)

		text = '\n'.join(segments)
		return DesktopVisibleText(
			application=params.application,
			text=text[: params.max_characters],
			is_truncated=len(text) > params.max_characters,
		)

	def _capture_window_blocking(self, params: CaptureDesktopWindowAction) -> DesktopWindowCapture:
		"""Encode a UIA wrapper screenshot as PNG without writing any file to disk."""
		window = self._focused_window(params.application)
		try:
			image = window.capture_as_image()
			buffer = io.BytesIO()
			image.save(buffer, format='PNG')
		except Exception as error:
			raise DesktopAutomationError('Unable to capture the authorized application window.') from error
		return DesktopWindowCapture(
			application=params.application,
			image_name=f'{params.application.value}-window.png',
			image_base64=base64.b64encode(buffer.getvalue()).decode('ascii'),
		)

	def _start_application(self, application: DesktopApplication) -> None:
		"""Start an application from a trusted configured command, never a model-supplied path."""
		try:
			from pywinauto.application import Application
		except ImportError as error:
			raise DesktopAutomationError('pywinauto is required for Windows UI Automation.') from error
		command = self._launch_commands.get(application) or self._require_application_spec(application).launch_command
		try:
			Application(backend='uia').start(command, timeout=self._operation_timeout_seconds)
		except Exception as error:
			raise DesktopAutomationError(f'Unable to start the trusted {application.value} command.') from error

	def _wait_for_windows(self, application: DesktopApplication) -> list[DesktopWindow]:
		"""Wait for a newly launched application to expose a visible matching window."""
		deadline = time.monotonic() + self._operation_timeout_seconds
		while time.monotonic() < deadline:
			windows = self._list_windows_blocking(frozenset({application}))
			if windows:
				return windows
			time.sleep(0.2)
		return []

	def _focused_window(self, application: DesktopApplication) -> Any:
		"""Resolve and focus the first visible window for one application before reading it."""
		windows = self._list_windows_blocking(frozenset({application}))
		if not windows:
			raise DesktopAutomationError(f'No visible {application.value} window is available.')
		selected_window = next((window for window in windows if window.is_foreground), windows[0])
		wrapper = self._wrapper_for_window_id(application, selected_window.window_id)
		self._focus_window(wrapper)
		return wrapper

	def _focus_window(self, wrapper: Any) -> None:
		"""Recover from focus loss with bounded retries before an operation reads or navigates a window."""
		for attempt in range(self._focus_attempts):
			try:
				wrapper.wait('visible enabled ready', timeout=self._operation_timeout_seconds)
				wrapper.set_focus()
				if self._is_active(wrapper):
					return
			except Exception as error:
				if attempt == self._focus_attempts - 1:
					raise DesktopAutomationError('Unable to focus the approved application window.') from error
			time.sleep(0.2)
		raise DesktopAutomationError('The approved application window repeatedly lost focus.')

	def _application_for_wrapper(
		self,
		wrapper: Any,
		applications: frozenset[DesktopApplication],
	) -> DesktopApplication | None:
		"""Map a window process to an allowlisted application by executable basename."""
		try:
			process_name = psutil.Process(wrapper.element_info.process_id).name().casefold()
		except (psutil.Error, AttributeError):
			return None
		for application in applications:
			specification = self._policy.application_spec(application)
			if specification and process_name in {name.casefold() for name in specification.executable_names}:
				return application
		return None

	def _window_from_wrapper(self, application: DesktopApplication, wrapper: Any) -> DesktopWindow:
		"""Convert a UIA top-level wrapper into a non-content-bearing window reference."""
		handle = self._window_handle(wrapper)
		return DesktopWindow(
			application=application, window_id=self._window_id(application, handle), is_foreground=self._is_active(wrapper)
		)

	def _window_id(self, application: DesktopApplication, handle: int) -> str:
		"""Create an opaque stable-enough window ID scoped to the application process handle."""
		return f'{application.value}:{handle:x}'

	def _wrapper_for_window_id(self, application: DesktopApplication, window_id: str) -> Any:
		"""Resolve a known window ID only after re-checking its executable identity."""
		prefix = f'{application.value}:'
		if not window_id.startswith(prefix):
			raise DesktopAutomationError('The window ID does not belong to the requested application.')
		try:
			handle = int(window_id.removeprefix(prefix), 16)
		except ValueError as error:
			raise DesktopAutomationError('The window ID is malformed.') from error
		wrapper = self._wrapper_for_handle(handle)
		if self._application_for_wrapper(wrapper, frozenset({application})) is not application:
			raise DesktopAutomationError('The window no longer belongs to the requested allowlisted application.')
		return wrapper

	def _wrapper_for_handle(self, handle: int) -> Any:
		"""Resolve a UIA wrapper from a native top-level window handle."""
		try:
			return self._desktop().window(handle=handle).wrapper_object()
		except Exception as error:
			raise DesktopAutomationError('The desktop window is no longer available.') from error

	def _remember_element(self, application: DesktopApplication, window: Any, wrapper: Any) -> DesktopElement:
		"""Store a live UIA wrapper under an opaque element ID and return a safe model representation."""
		element_id = uuid4().hex
		self._element_references[element_id] = _ElementReference(
			application=application,
			window_handle=self._window_handle(window),
			wrapper=wrapper,
		)
		return DesktopElement(
			element_id=element_id,
			name=self._window_text(wrapper)[:500],
			control_type=self._control_type(wrapper),
			automation_id=self._automation_id(wrapper),
			is_enabled=self._is_enabled(wrapper),
			is_visible=self._is_visible(wrapper),
		)

	def _resolve_element(self, application: DesktopApplication, element_id: str) -> _ElementReference:
		"""Load a current in-memory element reference while preventing cross-application reuse."""
		reference = self._element_references.get(element_id)
		if reference is None or reference.application is not application:
			raise DesktopAutomationError('The UI element is unknown, stale, or belongs to a different application.')
		if (
			self._application_for_wrapper(self._wrapper_for_handle(reference.window_handle), frozenset({application}))
			is not application
		):
			raise DesktopAutomationError('The UI element window no longer belongs to the requested application.')
		return reference

	def _clear_element_references(self, application: DesktopApplication) -> None:
		"""Discard stale element references when a new UI tree is captured for an application."""
		self._element_references = {
			element_id: reference
			for element_id, reference in self._element_references.items()
			if reference.application is not application
		}

	@staticmethod
	def _children(wrapper: Any) -> list[Any]:
		"""Return direct UIA children while treating inaccessible providers as empty branches."""
		try:
			return list(wrapper.children())
		except Exception:
			return []

	@classmethod
	def _descendants(cls, wrapper: Any, max_nodes: int = 1_000) -> list[Any]:
		"""Return descendants through the guarded child accessor to isolate provider failures."""
		result: list[Any] = []

		def collect(current: Any) -> None:
			for child in cls._children(current):
				if len(result) >= max_nodes:
					return
				result.append(child)
				collect(child)

		collect(wrapper)
		return result

	@staticmethod
	def _window_handle(wrapper: Any) -> int:
		"""Read the native handle required to re-validate a top-level UIA window."""
		try:
			return int(wrapper.handle)
		except (AttributeError, TypeError, ValueError) as error:
			raise DesktopAutomationError('The UI Automation window does not expose a native handle.') from error

	@staticmethod
	def _window_text(wrapper: Any) -> str:
		"""Read and normalize UIA text without letting provider failures abort a larger extraction."""
		try:
			return str(wrapper.window_text()).strip()
		except Exception:
			return ''

	@staticmethod
	def _automation_id(wrapper: Any) -> str | None:
		"""Read a UIA AutomationId when the provider exposes one."""
		try:
			value = str(wrapper.element_info.automation_id).strip()
		except (AttributeError, TypeError):
			return None
		return value or None

	@staticmethod
	def _is_visible(wrapper: Any) -> bool:
		"""Return whether a UIA wrapper is currently visible."""
		try:
			return bool(wrapper.is_visible())
		except Exception:
			return False

	@staticmethod
	def _is_enabled(wrapper: Any) -> bool:
		"""Return whether a UIA wrapper is currently enabled."""
		try:
			return bool(wrapper.is_enabled())
		except Exception:
			return False

	@staticmethod
	def _is_active(wrapper: Any) -> bool:
		"""Return whether a UIA window currently owns focus, tolerating provider gaps."""
		try:
			import win32gui

			return int(win32gui.GetForegroundWindow()) == int(wrapper.handle)
		except Exception:
			return False

	@staticmethod
	def _control_type(wrapper: Any) -> DesktopControlType:
		"""Map provider-specific UIA control names to the bounded public desktop-tool enum."""
		try:
			return DesktopControlType(wrapper.element_info.control_type)
		except (AttributeError, TypeError, ValueError):
			return DesktopControlType.OTHER

	def _matches_selector(self, wrapper: Any, params: FindDesktopElementAction) -> bool:
		"""Apply every selector criterion as an exact match to avoid fuzzy accidental targeting."""
		selector = params.selector
		if selector.name is not None and self._window_text(wrapper) != selector.name:
			return False
		if selector.automation_id is not None and self._automation_id(wrapper) != selector.automation_id:
			return False
		return selector.control_type is None or self._control_type(wrapper) is selector.control_type

	def _require_application_spec(self, application: DesktopApplication):
		"""Return the application spec or fail before any launch attempt for an unconfigured app."""
		specification = self._policy.application_spec(application)
		if specification is None or application not in self._policy.allowed_applications:
			raise DesktopAutomationError(f'The {application.value} application is not enabled by the desktop access policy.')
		return specification
