"""Tests for the initial desktop automation authorization boundary."""

from browser_use.desktop.policy import (
	DEFAULT_DESKTOP_ACCESS_POLICY,
	AccessStatus,
	DesktopApplication,
	DesktopOperation,
	DesktopReadSessionGrant,
)


def approved_wechat_read_session() -> DesktopReadSessionGrant:
	"""Build an explicit session grant for reading WeChat content in a test."""
	return DesktopReadSessionGrant(application=DesktopApplication.WECHAT, allow_model_content_processing=True)


def test_only_wechat_and_notepad_are_allowlisted():
	"""Reject applications outside the initial proof-of-concept scope."""
	decision = DEFAULT_DESKTOP_ACCESS_POLICY.authorize('outlook', DesktopOperation.LAUNCH_OR_FOCUS)

	assert decision.status is AccessStatus.DENIED


def test_allowlisted_application_uses_configured_executable_identity():
	"""Keep application resolution independent from model-provided paths or window titles."""
	specification = DEFAULT_DESKTOP_ACCESS_POLICY.application_spec(DesktopApplication.WECHAT)

	assert specification is not None
	assert specification.executable_names == frozenset({'WeChat.exe'})


def test_allowlisted_application_can_be_focused_without_content_access():
	"""Allow focus so the host can prepare an approved application for a read session."""
	decision = DEFAULT_DESKTOP_ACCESS_POLICY.authorize(DesktopApplication.WECHAT, DesktopOperation.LAUNCH_OR_FOCUS)

	assert decision.status is AccessStatus.ALLOWED


def test_extracting_visible_text_requires_explicit_read_session_consent():
	"""Prevent application content from reaching the model without a grant."""
	decision = DEFAULT_DESKTOP_ACCESS_POLICY.authorize(DesktopApplication.WECHAT, DesktopOperation.EXTRACT_VISIBLE_TEXT)

	assert decision.status is AccessStatus.REQUIRES_READ_SESSION_CONSENT


def test_read_session_allows_only_its_approved_application_and_operations():
	"""Keep a WeChat grant from authorizing content reads in another application."""
	decision = DEFAULT_DESKTOP_ACCESS_POLICY.authorize(
		DesktopApplication.NOTEPAD,
		DesktopOperation.EXTRACT_VISIBLE_TEXT,
		approved_wechat_read_session(),
	)

	assert decision.status is AccessStatus.REQUIRES_READ_SESSION_CONSENT


def test_read_session_requires_model_content_processing_acknowledgement():
	"""Require an explicit acknowledgement before UI text is shared with the model."""
	grant = DesktopReadSessionGrant(application=DesktopApplication.WECHAT)

	decision = DEFAULT_DESKTOP_ACCESS_POLICY.authorize(
		DesktopApplication.WECHAT,
		DesktopOperation.EXTRACT_VISIBLE_TEXT,
		grant,
	)

	assert decision.status is AccessStatus.REQUIRES_READ_SESSION_CONSENT


def test_read_navigation_is_allowed_after_read_session_consent():
	"""Allow scrolling and safe navigation needed to reveal existing content."""
	decision = DEFAULT_DESKTOP_ACCESS_POLICY.authorize(
		DesktopApplication.WECHAT,
		DesktopOperation.SCROLL,
		approved_wechat_read_session(),
	)

	assert decision.status is AccessStatus.ALLOWED


def test_high_risk_actions_still_require_per_action_confirmation():
	"""Do not let a read grant authorize sending a message or deleting content."""
	decision = DEFAULT_DESKTOP_ACCESS_POLICY.authorize(
		DesktopApplication.WECHAT,
		DesktopOperation.SEND_MESSAGE,
		approved_wechat_read_session(),
	)

	assert decision.status is AccessStatus.REQUIRES_ACTION_CONFIRMATION
