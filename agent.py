import asyncio
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from browser_use import Agent, AgentHistoryList, Browser, ChatOpenAI, Tools

load_dotenv()

OPTIONAL_TOOL_NAMES = {
    'evaluate',
    'read_file',
    'replace_file',
    'save_as_pdf',
    'search',
    'upload_file',
    'write_file',
}


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f'Missing required environment variable: {name}')
    return value


def build_tools() -> Tools:
    """Build the safe default tool set and enable optional tools explicitly."""
    enabled_optional_tools = {
        name.strip() for name in os.getenv('ENABLED_OPTIONAL_TOOLS', '').split(',') if name.strip()
    }
    unknown_tools = enabled_optional_tools - OPTIONAL_TOOL_NAMES
    if unknown_tools:
        raise ValueError(
            'ENABLED_OPTIONAL_TOOLS contains unsupported tools: '
            + ', '.join(sorted(unknown_tools))
        )

    disabled_tools = sorted(OPTIONAL_TOOL_NAMES - enabled_optional_tools)
    return Tools(exclude_actions=disabled_tools)


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
    target_url = require_env('TARGET_URL')
    after_login_task = require_env('AFTER_LOGIN_TASK')

    parsed_url = urlparse(target_url)
    if parsed_url.scheme not in {'http', 'https'} or not parsed_url.netloc:
        raise ValueError('TARGET_URL must be a complete http:// or https:// URL')

    origin = f'{parsed_url.scheme}://{parsed_url.netloc}'
    browser = Browser(headless=False, allowed_domains=[origin])
    tools = build_tools()
    await browser.start()

    try:
        await browser.navigate_to(target_url)
        await asyncio.to_thread(
            input,
            '\n请在浏览器中手动完成登录，确认进入系统后，回到终端按 Enter 继续... ',
        )

        agent = Agent(
            task=after_login_task,
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
            use_vision=True,
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

if __name__ == "__main__":
    asyncio.run(main())
