"""Policy primitives for controlled Windows desktop automation."""

from browser_use.desktop.policy import (
	DEFAULT_DESKTOP_ACCESS_POLICY,
	AccessDecision,
	AccessStatus,
	DesktopAccessPolicy,
	DesktopApplication,
	DesktopApplicationSpec,
	DesktopOperation,
	DesktopReadSessionGrant,
)

__all__ = [
	'AccessDecision',
	'AccessStatus',
	'DEFAULT_DESKTOP_ACCESS_POLICY',
	'DesktopAccessPolicy',
	'DesktopApplication',
	'DesktopApplicationSpec',
	'DesktopOperation',
	'DesktopReadSessionGrant',
]
