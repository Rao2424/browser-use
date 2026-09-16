"""Tests for the desktop-tool interface and its policy-aware registration layer."""

import json

import pytest

from browser_use.desktop.policy import AccessStatus, DesktopApplication, DesktopReadSessionGrant
from browser_use.desktop.tools import DesktopToolsRuntime, register_desktop_tools
from browser_use.desktop.views import (
	DesktopControlType,
	DesktopElementSelector,
	DesktopVisibleText,
	DesktopWindow,
	DesktopWindowList,
	ExtractDesktopVisibleTextAction,
)
from browser_use.tools.service import Tools


class FakeDesktopExecutor:
	"""In-memory executor used to verify the interface without desktop UI Automation."""

	def __init__(self):
		self.extract_calls: list[ExtractDesktopVisibleTextAction] = []

	async def list_windows(self, applications: frozenset[DesktopApplication]) -> DesktopWindowList:
		return DesktopWindowList(
			windows=[DesktopWindow(application=DesktopApplication.WECHAT, window_id='wechat-main', is_foreground=True)]
		)

	async def launch_or_focus(self, application: DesktopApplication) -> DesktopWindow:
		return DesktopWindow(application=application, window_id=f'{application}-main', is_foreground=True)

	async def get_ui_tree(self, params):
		raise AssertionError('The fake executor should not receive this call in this test.')

	async def find_element(self, params):
		raise AssertionError('The fake executor should not receive this call in this test.')

	async def read_navigate(self, params):
		raise AssertionError('The fake executor should not receive this call in this test.')

	async def scroll(self, params):
		raise AssertionError('The fake executor should not receive this call in this test.')

	async def extract_visible_text(self, params: ExtractDesktopVisibleTextAction) -> DesktopVisibleText:
		self.extract_calls.append(params)
		return DesktopVisibleText(application=params.application, text='已读取的可见内容', is_truncated=False)

	async def capture_window(self, params):
		raise AssertionError('The fake executor should not receive this call in this test.')


def build_tools(runtime: DesktopToolsRuntime) -> Tools:
	"""Register desktop tools on an isolated registry for one test."""
	tools = Tools()
	register_desktop_tools(tools, runtime)
	return tools


def test_desktop_tool_registration_exposes_only_read_only_actions():
	"""Keep the future text-input contract out of the initial model-visible tool set."""
	tools = build_tools(DesktopToolsRuntime(executor=FakeDesktopExecutor()))
	actions = tools.registry.registry.actions

	assert {
		'desktop_list_windows',
		'desktop_launch_or_focus',
		'desktop_get_ui_tree',
		'desktop_find_element',
		'desktop_read_navigate',
		'desktop_scroll',
		'desktop_extract_visible_text',
		'desktop_capture_window',
	}.issubset(actions)
	assert 'desktop_input_text' not in actions


def test_selector_requires_a_stable_ui_automation_criterion():
	"""Prevent an unbounded element search from reaching an executor."""
	with pytest.raises(ValueError, match='Provide at least one'):
		DesktopElementSelector()

	assert DesktopElementSelector(name='张三', control_type=DesktopControlType.LIST_ITEM).name == '张三'


@pytest.mark.asyncio
async def test_extract_visible_text_returns_consent_request_without_a_grant():
	"""Return a structured consent result before an executor sees application content."""
	executor = FakeDesktopExecutor()
	tools = build_tools(DesktopToolsRuntime(executor=executor))
	registered = tools.registry.registry.actions['desktop_extract_visible_text']
	params = ExtractDesktopVisibleTextAction(application=DesktopApplication.WECHAT)

	result = await registered.function(params=params)
	payload = json.loads(result.extracted_content or '{}')

	assert executor.extract_calls == []
	assert payload['access']['status'] == AccessStatus.REQUIRES_READ_SESSION_CONSENT


@pytest.mark.asyncio
async def test_extract_visible_text_calls_executor_after_matching_read_session_grant():
	"""Pass a typed request to the executor and return its typed response after consent."""
	executor = FakeDesktopExecutor()
	grant = DesktopReadSessionGrant(application=DesktopApplication.WECHAT, allow_model_content_processing=True)
	tools = build_tools(DesktopToolsRuntime(executor=executor, read_session_grant=grant))
	registered = tools.registry.registry.actions['desktop_extract_visible_text']
	params = ExtractDesktopVisibleTextAction(application=DesktopApplication.WECHAT, max_characters=200)

	result = await registered.function(params=params)
	payload = json.loads(result.extracted_content or '{}')

	assert executor.extract_calls == [params]
	assert payload['access']['status'] == AccessStatus.ALLOWED
	assert payload['data'] == {
		'application': 'wechat',
		'text': '已读取的可见内容',
		'is_truncated': False,
	}
