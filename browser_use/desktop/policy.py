"""Authorization boundary for the initial read-only desktop automation release."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DesktopApplication(StrEnum):
	"""Applications approved for the initial desktop automation release."""

	WECHAT = 'wechat'
	NOTEPAD = 'notepad'


class DesktopOperation(StrEnum):
	"""Operations that a desktop automation tool may request."""

	LIST_WINDOWS = 'list_windows'
	LAUNCH_OR_FOCUS = 'launch_or_focus'
	READ_UI_TREE = 'read_ui_tree'
	FIND_UI_ELEMENT = 'find_ui_element'
	EXTRACT_VISIBLE_TEXT = 'extract_visible_text'
	CAPTURE_WINDOW = 'capture_window'
	SCROLL = 'scroll'
	READ_NAVIGATION = 'read_navigation'
	INPUT_TEXT = 'input_text'
	SEND_MESSAGE = 'send_message'
	DELETE_CONTENT = 'delete_content'
	TRANSFER_FILE = 'transfer_file'
	CLOSE_APPLICATION = 'close_application'


class AccessStatus(StrEnum):
	"""The result of an authorization check before desktop UI Automation runs."""

	ALLOWED = 'allowed'
	DENIED = 'denied'
	REQUIRES_READ_SESSION_CONSENT = 'requires_read_session_consent'
	REQUIRES_ACTION_CONFIRMATION = 'requires_action_confirmation'


class DesktopApplicationSpec(BaseModel):
	"""A stable executable identity for an application in the desktop allowlist."""

	model_config = ConfigDict(frozen=True)

	application: DesktopApplication
	display_name: str
	executable_names: frozenset[str]
	launch_command: str


class DesktopReadSessionGrant(BaseModel):
	"""Explicit user consent to expose one application's displayed content to the model."""

	model_config = ConfigDict(frozen=True)

	application: DesktopApplication
	allowed_operations: frozenset[DesktopOperation] = Field(default_factory=lambda: READ_SESSION_OPERATIONS)
	allow_model_content_processing: bool = False


class AccessDecision(BaseModel):
	"""Structured result returned to a desktop tool before it performs an operation."""

	model_config = ConfigDict(frozen=True)

	status: AccessStatus
	reason: str

	@property
	def is_allowed(self) -> bool:
		"""Return whether the caller may execute the requested operation."""
		return self.status is AccessStatus.ALLOWED


READ_SESSION_OPERATIONS = frozenset(
	{
		DesktopOperation.READ_UI_TREE,
		DesktopOperation.FIND_UI_ELEMENT,
		DesktopOperation.EXTRACT_VISIBLE_TEXT,
		DesktopOperation.CAPTURE_WINDOW,
		DesktopOperation.SCROLL,
		DesktopOperation.READ_NAVIGATION,
	}
)

HIGH_RISK_OPERATIONS = frozenset(
	{
		DesktopOperation.INPUT_TEXT,
		DesktopOperation.SEND_MESSAGE,
		DesktopOperation.DELETE_CONTENT,
		DesktopOperation.TRANSFER_FILE,
		DesktopOperation.CLOSE_APPLICATION,
	}
)

DEFAULT_APPLICATION_SPECS = {
	DesktopApplication.WECHAT: DesktopApplicationSpec(
		application=DesktopApplication.WECHAT,
		display_name='WeChat for Windows',
		executable_names=frozenset({'WeChat.exe'}),
		launch_command='WeChat.exe',
	),
	DesktopApplication.NOTEPAD: DesktopApplicationSpec(
		application=DesktopApplication.NOTEPAD,
		display_name='Windows Notepad',
		executable_names=frozenset({'notepad.exe'}),
		launch_command='notepad.exe',
	),
}


class DesktopAccessPolicy(BaseModel):
	"""Enforce the initial application allowlist and read-only consent boundary."""

	model_config = ConfigDict(frozen=True)

	allowed_applications: frozenset[DesktopApplication] = Field(
		default_factory=lambda: frozenset({DesktopApplication.WECHAT, DesktopApplication.NOTEPAD})
	)
	application_specs: dict[DesktopApplication, DesktopApplicationSpec] = Field(
		default_factory=lambda: DEFAULT_APPLICATION_SPECS.copy()
	)

	def application_spec(self, application: DesktopApplication | str) -> DesktopApplicationSpec | None:
		"""Return the configured executable identity for an allowlisted application."""
		try:
			resolved_application = DesktopApplication(application)
		except ValueError:
			return None
		return self.application_specs.get(resolved_application)

	def authorize(
		self,
		application: DesktopApplication | str,
		operation: DesktopOperation,
		read_session_grant: DesktopReadSessionGrant | None = None,
	) -> AccessDecision:
		"""Authorize an operation without performing any desktop interaction."""
		try:
			resolved_application = DesktopApplication(application)
		except ValueError:
			return AccessDecision(
				status=AccessStatus.DENIED,
				reason='The requested desktop application is not in the allowlist.',
			)

		if resolved_application not in self.allowed_applications:
			return AccessDecision(
				status=AccessStatus.DENIED,
				reason='The requested desktop application is not enabled by this policy.',
			)
		if self.application_spec(resolved_application) is None:
			return AccessDecision(
				status=AccessStatus.DENIED,
				reason='The requested desktop application has no configured executable identity.',
			)

		if operation is DesktopOperation.LAUNCH_OR_FOCUS:
			return AccessDecision(
				status=AccessStatus.ALLOWED,
				reason='Launching or focusing an allowlisted application does not reveal its content.',
			)

		if operation in HIGH_RISK_OPERATIONS:
			return AccessDecision(
				status=AccessStatus.REQUIRES_ACTION_CONFIRMATION,
				reason='This high-risk operation needs a one-time human confirmation and is not enabled in the read-only release.',
			)

		if operation in READ_SESSION_OPERATIONS:
			if read_session_grant is None or read_session_grant.application is not resolved_application:
				return AccessDecision(
					status=AccessStatus.REQUIRES_READ_SESSION_CONSENT,
					reason='Reading displayed desktop content requires an explicit read-session grant for this application.',
				)
			if not read_session_grant.allow_model_content_processing:
				return AccessDecision(
					status=AccessStatus.REQUIRES_READ_SESSION_CONSENT,
					reason='The read-session grant must explicitly permit providing displayed content to the configured model.',
				)
			if operation not in read_session_grant.allowed_operations:
				return AccessDecision(
					status=AccessStatus.REQUIRES_READ_SESSION_CONSENT,
					reason='The read-session grant does not include this operation.',
				)
			return AccessDecision(
				status=AccessStatus.ALLOWED, reason='The read-session grant authorizes this read-only operation.'
			)

		return AccessDecision(
			status=AccessStatus.DENIED, reason='The requested desktop operation is not supported by this policy.'
		)


DEFAULT_DESKTOP_ACCESS_POLICY = DesktopAccessPolicy()
