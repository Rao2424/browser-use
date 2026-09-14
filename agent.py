import asyncio
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr

from browser_use import ActionResult, Agent, AgentHistoryList, Browser, ChatOpenAI, Tools

load_dotenv()

LLM_SCREENSHOT_SIZE = (1440, 900)

OPTIONAL_TOOL_NAMES = {
	'evaluate',
	'read_file',
	'replace_file',
	'save_as_pdf',
	'search',
	'upload_file',
	'write_file',
}


class LoginConfig(BaseModel):
	"""Validated login settings loaded from environment variables."""

	username: SecretStr
	password: SecretStr
	totp_secret: SecretStr | None = None
	success_criteria: str = '页面不再显示登录表单，并进入登录后的目标页面'
	max_attempts: int = Field(default=2, ge=1, le=5)
	agent_max_failures: int = Field(default=5, ge=1, le=20)


def require_env(name: str) -> str:
	value = os.getenv(name)
	if not value:
		raise RuntimeError(f'Missing required environment variable: {name}')
	return value


def load_login_config() -> LoginConfig:
	"""Load login settings, accepting legacy SITE_* credential names."""
	username = os.getenv('LOGIN_USERNAME') or os.getenv('SITE_USERNAME')
	password = os.getenv('LOGIN_PASSWORD') or os.getenv('SITE_PASSWORD')
	if not username:
		raise RuntimeError('Missing required environment variable: LOGIN_USERNAME')
	if not password:
		raise RuntimeError('Missing required environment variable: LOGIN_PASSWORD')

	return LoginConfig(
		username=username,
		password=password,
		totp_secret=os.getenv('LOGIN_TOTP_SECRET') or None,
		success_criteria=os.getenv(
			'LOGIN_SUCCESS_CRITERIA',
			'页面不再显示登录表单，并进入登录后的目标页面',
		),
		max_attempts=os.getenv('LOGIN_MAX_ATTEMPTS', '2'),
		agent_max_failures=os.getenv('AGENT_MAX_FAILURES', '5'),
	)


def build_tools() -> Tools:
	"""Build the safe default tool set and enable optional tools explicitly."""
	enabled_optional_tools = {name.strip() for name in os.getenv('ENABLED_OPTIONAL_TOOLS', '').split(',') if name.strip()}
	unknown_tools = enabled_optional_tools - OPTIONAL_TOOL_NAMES
	if unknown_tools:
		raise ValueError('ENABLED_OPTIONAL_TOOLS contains unsupported tools: ' + ', '.join(sorted(unknown_tools)))

	disabled_tools = sorted(OPTIONAL_TOOL_NAMES - enabled_optional_tools)
	tools = Tools(exclude_actions=disabled_tools)
	tools.set_coordinate_clicking(True)

	@tools.action('Pause for a human to complete CAPTCHA, QR-code scanning, or another interactive verification step.')
	async def request_human_verification() -> ActionResult:
		"""Wait until the user confirms that the interactive verification is complete."""
		await asyncio.to_thread(
			input,
			'\n请在浏览器中完成验证码、扫码或其他人工验证，完成后回到终端按 Enter 继续... ',
		)
		return ActionResult(extracted_content='用户已完成人工验证操作；请重新读取当前页面并检查登录状态。')

	return tools


def build_run_summary(result: AgentHistoryList) -> str:
	"""Build a non-empty text summary for a completed agent run."""
	final_result = result.final_result()
	errors = [error for error in result.errors() if error]
	urls = list(dict.fromkeys(url for url in result.urls() if url))

	lines = [
		'任务执行总结',
		f'是否结束: {result.is_done()}',
		f'是否成功: {result.is_successful()}',
		f'执行步骤: {result.number_of_steps()}',
		f'执行耗时: {result.total_duration_seconds():.2f} 秒',
		f'执行动作: {", ".join(result.action_names()) or "无"}',
		f'访问地址: {", ".join(urls) or "无"}',
		'',
		'最终结果:',
		str(final_result) if final_result else '未生成（模型未执行 done，或最后一步未返回内容）',
	]

	if errors:
		lines.extend(['', '错误信息:', *[f'- {error}' for error in errors]])

	return '\n'.join(lines)


async def main():
	openai_api_key = require_env('OPENAI_API_KEY')
	openai_base_url = os.getenv('OPENAI_BASE_URL', 'https://api.duckcoding.ai/v1')
	openai_model = os.getenv('OPENAI_MODEL', 'gpt-5.5')
	target_url = require_env('TARGET_URL').strip()
	after_login_task = require_env('AFTER_LOGIN_TASK')
	login_config = load_login_config()

	parsed_url = urlparse(target_url)
	if parsed_url.scheme not in {'http', 'https'} or not parsed_url.netloc:
		raise ValueError('TARGET_URL must be a complete http:// or https:// URL')

	origin = f'{parsed_url.scheme}://{parsed_url.netloc}'
	browser = Browser(headless=False, allowed_domains=[origin])
	tools = build_tools()
	await browser.start()

	try:
		sensitive_values = {
			'login_username': login_config.username.get_secret_value(),
			'login_password': login_config.password.get_secret_value(),
		}
		totp_instruction = '如出现 TOTP 2FA，调用 request_human_verification。'
		if login_config.totp_secret:
			sensitive_values['login_bu_2fa_code'] = login_config.totp_secret.get_secret_value()
			totp_instruction = '如出现 TOTP 2FA，输入 <secret>login_bu_2fa_code</secret>。'

		login_task = f"""
使用 navigate 动作打开 {target_url}
定位登录表单，输入 <secret>login_username</secret> 和 <secret>login_password</secret>，然后提交。
登录提交最多尝试 {login_config.max_attempts} 次。
{totp_instruction}
如出现图片验证码、扫码或其他人工确认，调用 request_human_verification；不要持续轮询。
登录成功标准：{login_config.success_criteria}
确认登录成功后再执行以下任务：
{after_login_task}
""".strip()

		agent = Agent(
			task=login_task,
			llm=ChatOpenAI(
				model=openai_model,
				api_key=openai_api_key,
				base_url=openai_base_url,
				reasoning_effort='low',
				reasoning_models=[openai_model],
				add_schema_to_system_prompt=True,
			),
			browser=browser,
			tools=tools,
			sensitive_data={origin: sensitive_values},
			initial_actions=[{'navigate': {'url': target_url, 'new_tab': False}}],
			max_failures=login_config.agent_max_failures,
			use_vision='auto',
			llm_screenshot_size=LLM_SCREENSHOT_SIZE,
			extend_system_message="""
OUTPUT FORMAT — STRICT:
Return exactly one valid raw JSON object and nothing else.
Do not use Markdown code fences, DSML, XML, <think>, <action>,
tool-call wrappers, or explanatory text outside the JSON object.
The JSON may contain a "thinking" field, but its value must be a normal
JSON string without <think> tags.
Actions must appear only in the top-level "action" array and must use
the exact action names and parameter names from the supplied JSON Schema.
Before responding, verify that the top-level "action" field exists and
contains at least one schema-valid action.

COORDINATE CLICK SAFETY:
When using click with coordinate_x and coordinate_y, always provide target_hint
with the exact visible text or accessible label of the intended element.
Do not manually scale screenshot coordinates. If validation rejects a click,
take a fresh screenshot and locate the target again before retrying.
""",
		)

		result = await agent.run()
		completed_at = datetime.now()
		run_summary = build_run_summary(result)
		log_directory = Path(__file__).resolve().parent / 'log'
		log_directory.mkdir(parents=True, exist_ok=True)
		log_file = log_directory / f'{completed_at:%Y%m%d_%H%M%S}.txt'
		log_file.write_text(run_summary, encoding='utf-8')

		print(run_summary)
		print(f'\n任务总结已保存至: {log_file}')
	finally:
		await browser.stop()


if __name__ == '__main__':
	asyncio.run(main())
