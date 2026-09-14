import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Badge,
  Button,
  Dropdown,
  Field,
  FluentProvider,
  Input,
  Option,
  Skeleton,
  SkeletonItem,
  Tab,
  TabList,
  Textarea,
  Toast,
  ToastBody,
  Toaster,
  Tooltip,
  webDarkTheme,
  webLightTheme,
  useId,
  useToastController,
} from '@fluentui/react-components'
import {
  Add20Regular,
  ArrowSync20Regular,
  Bot20Regular,
  CheckmarkCircle20Filled,
  ChevronRight20Regular,
  Delete20Regular,
  Dismiss20Regular,
  DocumentText20Regular,
  Eye20Regular,
  EyeOff20Regular,
  Folder20Regular,
  Globe20Regular,
  Key20Regular,
  Navigation20Regular,
  Play20Filled,
  Save20Regular,
  Settings20Regular,
  ShieldKeyhole20Regular,
  Stop20Filled,
  WeatherMoon20Regular,
  WeatherSunny20Regular,
} from '@fluentui/react-icons'

const initialConfigs = [
  {
    id: 'report-center',
    name: '报表中心下载',
    url: 'https://portal.example.com/login',
    username: 'operator@example.com',
    password: 'password-example',
    prompt: '登录后进入月度报表，下载最新一期的销售明细文件。',
    successCriteria: '页面显示工作台，并且不再显示登录表单。',
  },
  {
    id: 'supplier-console',
    name: '供应商后台查询',
    url: 'https://supplier.example.com',
    username: 'purchasing@example.com',
    password: 'password-example',
    prompt: '查询所有待确认订单，将结果下载为 Excel 文件。',
    successCriteria: '页面顶部出现当前账户名称。',
  },
]

const initialModelConfig = {
  apiKey: '',
  baseUrl: 'https://api.openai.com/v1',
  modelName: 'gpt-5.5',
}

const executionSteps = [
  { key: 'open', label: '打开网页', detail: '访问配置中的登录地址' },
  { key: 'login', label: '完成登录', detail: '安全填写账号和密码' },
  { key: 'task', label: '执行任务', detail: '按照提示词操作网页' },
  { key: 'download', label: '保存文件', detail: '写入指定下载目录' },
]

function readStoredValue(key, fallback) {
  try {
    const stored = window.localStorage.getItem(key)
    return stored ? JSON.parse(stored) : fallback
  } catch {
    return fallback
  }
}

function formatTime(date) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date)
}

function getHostname(url) {
  try {
    return new URL(url).hostname || '等待填写网址'
  } catch {
    return '等待填写网址'
  }
}

function StatusBadge({ tone, children }) {
  return (
    <Badge appearance="tint" color={tone} size="small">
      {children}
    </Badge>
  )
}

function AppToaster({ message }) {
  const toasterId = useId('app-toaster')
  const { dispatchToast } = useToastController(toasterId)

  useEffect(() => {
    if (!message) return
    dispatchToast(
      <Toast>
        <ToastBody>{message}</ToastBody>
      </Toast>,
      { intent: 'success', timeout: 2400 },
    )
  }, [dispatchToast, message])

  return <Toaster toasterId={toasterId} position="top-end" />
}

function Sidebar({ currentPage, onNavigate, darkMode, onToggleTheme }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">
          <Navigation20Regular />
        </div>
        <div>
          <strong>Browser Desk</strong>
          <span>网页自动化</span>
        </div>
      </div>

      <nav className="primary-nav" aria-label="主菜单">
        <button
          className={currentPage === 'execution' ? 'nav-item active' : 'nav-item'}
          onClick={() => onNavigate('execution')}
          type="button"
          aria-label="执行中心"
        >
          <Play20Filled />
          <span>执行中心</span>
        </button>
        <button
          className={currentPage === 'configuration' ? 'nav-item active' : 'nav-item'}
          onClick={() => onNavigate('configuration')}
          type="button"
          aria-label="配置中心"
        >
          <Settings20Regular />
          <span>配置中心</span>
        </button>
      </nav>

      <div className="sidebar-footer">
        <div className="service-health">
          <span className="health-dot" aria-hidden="true" />
          <div>
            <strong>本地服务正常</strong>
            <span>数据仅保存在此设备</span>
          </div>
        </div>
        <Tooltip content={darkMode ? '切换到浅色模式' : '切换到深色模式'} relationship="label">
          <Button
            appearance="subtle"
            icon={darkMode ? <WeatherSunny20Regular /> : <WeatherMoon20Regular />}
            onClick={onToggleTheme}
            aria-label={darkMode ? '切换到浅色模式' : '切换到深色模式'}
          />
        </Tooltip>
      </div>
    </aside>
  )
}

function PageHeader({ title, description, action }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </header>
  )
}

function ExecutionCenter({ configs, selectedConfigId, onSelectConfig }) {
  const [downloadPath, setDownloadPath] = useState('C:\\Users\\Public\\Downloads\\BrowserDesk')
  const [runState, setRunState] = useState('idle')
  const [activeStep, setActiveStep] = useState(-1)
  const [logs, setLogs] = useState([])
  const [error, setError] = useState('')
  const timerRef = useRef(null)
  const selectedConfig = configs.find((config) => config.id === selectedConfigId)

  useEffect(() => () => window.clearInterval(timerRef.current), [])

  function stopRun(message = '任务已由用户停止。') {
    window.clearInterval(timerRef.current)
    timerRef.current = null
    setRunState('stopped')
    setLogs((current) => [...current, { time: formatTime(new Date()), text: message, tone: 'muted' }])
  }

  function startRun() {
    if (!selectedConfig) {
      setError('请先选择一个任务配置。')
      return
    }
    if (
      !selectedConfig.url.trim() ||
      !selectedConfig.username.trim() ||
      !selectedConfig.password ||
      !selectedConfig.prompt.trim()
    ) {
      setError('当前任务配置不完整，请在配置中心补充网址、账号、密码和提示词。')
      return
    }
    if (!downloadPath.trim()) {
      setError('请选择文件下载位置。')
      return
    }

    setError('')
    setRunState('running')
    setActiveStep(0)
    setLogs([{ time: formatTime(new Date()), text: `已启动“${selectedConfig.name}”。`, tone: 'default' }])

    let step = 0
    window.clearInterval(timerRef.current)
    timerRef.current = window.setInterval(() => {
      setLogs((current) => [
        ...current,
        {
          time: formatTime(new Date()),
          text: `${executionSteps[step].label}已完成。`,
          tone: 'success',
        },
      ])
      step += 1
      if (step >= executionSteps.length) {
        window.clearInterval(timerRef.current)
        timerRef.current = null
        setRunState('success')
        setActiveStep(executionSteps.length)
        setLogs((current) => [
          ...current,
          { time: formatTime(new Date()), text: '任务执行成功，文件已保存。', tone: 'success' },
        ])
      } else {
        setActiveStep(step)
      }
    }, 1100)
  }

  return (
    <main className="page-content">
      <PageHeader title="执行中心" description="选择已有配置，确认下载位置，然后启动浏览器任务。" />

      <div className="execution-layout">
        <section className="run-setup" aria-labelledby="run-setup-title">
          <div className="section-title-row">
            <div>
              <h2 id="run-setup-title">本次执行</h2>
              <p>运行前确认任务信息。</p>
            </div>
            <StatusBadge tone={runState === 'running' ? 'informative' : runState === 'success' ? 'success' : 'subtle'}>
              {runState === 'running' ? '执行中' : runState === 'success' ? '已完成' : '待启动'}
            </StatusBadge>
          </div>

          <div className="form-stack">
            <Field label="任务配置" required validationMessage={error && !selectedConfig ? error : undefined}>
              <Dropdown
                value={selectedConfig?.name ?? ''}
                selectedOptions={selectedConfigId ? [selectedConfigId] : []}
                onOptionSelect={(_, data) => onSelectConfig(data.optionValue)}
                placeholder="选择任务配置"
              >
                {configs.map((config) => (
                  <Option key={config.id} value={config.id} text={config.name}>
                    {config.name}
                  </Option>
                ))}
              </Dropdown>
            </Field>

            {error && selectedConfig && downloadPath.trim() && (
              <div className="inline-error" role="alert">
                <Dismiss20Regular />
                <span>{error}</span>
              </div>
            )}

            {selectedConfig ? (
              <div className="config-summary">
                <Globe20Regular />
                <div>
                  <strong>{selectedConfig.url}</strong>
                  <span>{selectedConfig.prompt}</span>
                </div>
              </div>
            ) : (
              <div className="empty-inline">还没有可执行的任务配置。</div>
            )}

            <Field label="下载位置" required validationMessage={error && !downloadPath.trim() ? error : undefined}>
              <Input
                value={downloadPath}
                onChange={(_, data) => setDownloadPath(data.value)}
                contentAfter={
                  <Tooltip content="桌面版接入系统目录选择器" relationship="label">
                    <Button appearance="subtle" icon={<Folder20Regular />} aria-label="选择下载目录" />
                  </Tooltip>
                }
              />
            </Field>
          </div>

          <div className="run-actions">
            <Button
              appearance="primary"
              icon={<Play20Filled />}
              size="large"
              onClick={startRun}
              disabled={runState === 'running'}
            >
              开始执行
            </Button>
            <Button
              appearance="secondary"
              icon={<Stop20Filled />}
              size="large"
              onClick={() => stopRun()}
              disabled={runState !== 'running'}
            >
              停止
            </Button>
          </div>
        </section>

        <section className="run-monitor" aria-labelledby="run-monitor-title">
          <div className="section-title-row">
            <div>
              <h2 id="run-monitor-title">实时进度</h2>
              <p>当前浏览器任务的执行轨迹。</p>
            </div>
            {runState === 'running' && <ArrowSync20Regular className="spin-icon" aria-label="正在执行" />}
          </div>

          <ol className="task-rail">
            {executionSteps.map((step, index) => {
              const complete = activeStep > index
              const current = activeStep === index && runState === 'running'
              return (
                <li key={step.key} className={complete ? 'complete' : current ? 'current' : ''}>
                  <div className="rail-marker" aria-hidden="true">
                    {complete ? <CheckmarkCircle20Filled /> : <span>{index + 1}</span>}
                  </div>
                  <div>
                    <strong>{step.label}</strong>
                    <span>{step.detail}</span>
                  </div>
                </li>
              )
            })}
          </ol>

          <div className="log-panel" aria-live="polite">
            <div className="log-header">
              <span>执行日志</span>
              <span>{logs.length} 条</span>
            </div>
            <div className="log-body">
              {logs.length === 0 ? (
                <div className="log-empty">
                  <DocumentText20Regular />
                  <span>启动任务后，执行记录会显示在这里。</span>
                </div>
              ) : (
                logs.map((log, index) => (
                  <div className={`log-line ${log.tone}`} key={`${log.time}-${index}`}>
                    <time>{log.time}</time>
                    <span>{log.text}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}

function ConfigList({ configs, selectedId, onSelect, onAdd }) {
  return (
    <aside className="config-list" aria-label="网站任务列表">
      <div className="config-list-header">
        <div>
          <strong>网站任务</strong>
          <span>{configs.length} 条配置</span>
        </div>
        <Tooltip content="新建配置" relationship="label">
          <Button appearance="subtle" icon={<Add20Regular />} onClick={onAdd} aria-label="新建配置" />
        </Tooltip>
      </div>

      <div className="config-items">
        {configs.length === 0 ? (
          <div className="empty-list">
            <Globe20Regular />
            <strong>暂无配置</strong>
            <span>创建第一条网站任务。</span>
            <Button appearance="primary" icon={<Add20Regular />} onClick={onAdd}>
              新建配置
            </Button>
          </div>
        ) : (
          configs.map((config) => (
            <button
              type="button"
              key={config.id}
              className={selectedId === config.id ? 'config-item active' : 'config-item'}
              onClick={() => onSelect(config.id)}
            >
              <span className="config-icon">
                <Globe20Regular />
              </span>
              <span className="config-copy">
                <strong>{config.name}</strong>
                <small>{getHostname(config.url)}</small>
              </span>
              <ChevronRight20Regular />
            </button>
          ))
        )}
      </div>
    </aside>
  )
}

function WebsiteConfigForm({ config, onChange, onSave, onDelete }) {
  const [showPassword, setShowPassword] = useState(false)
  const [validationError, setValidationError] = useState('')

  if (!config) {
    return (
      <section className="config-editor empty-editor">
        <Globe20Regular />
        <h2>选择一条配置</h2>
        <p>从左侧选择网站任务，或新建一条配置。</p>
      </section>
    )
  }

  function update(field, value) {
    onChange({ ...config, [field]: value })
  }

  function validateAndSave() {
    if (!config.name.trim() || !config.url.trim() || !config.username.trim() || !config.password || !config.prompt.trim()) {
      setValidationError('请填写所有必填内容。')
      return
    }
    try {
      const parsed = new URL(config.url)
      if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('invalid protocol')
    } catch {
      setValidationError('请输入完整的 http 或 https 网址。')
      return
    }
    setValidationError('')
    onSave()
  }

  return (
    <section className="config-editor">
      <div className="editor-header">
        <div>
          <h2>编辑网站任务</h2>
          <p>网址、登录信息和提示词将作为一条配置保存。</p>
        </div>
        <Button appearance="subtle" icon={<Delete20Regular />} onClick={onDelete}>
          删除
        </Button>
      </div>

      {validationError && (
        <div className="inline-error" role="alert">
          <Dismiss20Regular />
          <span>{validationError}</span>
        </div>
      )}

      <div className="editor-form">
        <Field label="配置名称" required hint="用于在执行中心快速识别任务。">
          <Input value={config.name} onChange={(_, data) => update('name', data.value)} />
        </Field>

        <Field label="登录网址" required hint="请输入完整网址，例如 https://example.com/login。">
          <Input contentBefore={<Globe20Regular />} value={config.url} onChange={(_, data) => update('url', data.value)} />
        </Field>

        <div className="form-grid">
          <Field label="登录账号" required>
            <Input value={config.username} onChange={(_, data) => update('username', data.value)} autoComplete="username" />
          </Field>
          <Field label="登录密码" required hint="桌面版将使用 Windows 安全存储。">
            <Input
              type={showPassword ? 'text' : 'password'}
              value={config.password}
              onChange={(_, data) => update('password', data.value)}
              autoComplete="current-password"
              contentAfter={
                <Button
                  appearance="subtle"
                  icon={showPassword ? <EyeOff20Regular /> : <Eye20Regular />}
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                />
              }
            />
          </Field>
        </div>

        <Field label="登录成功条件" hint="帮助浏览器确认已进入登录后的页面。">
          <Input value={config.successCriteria} onChange={(_, data) => update('successCriteria', data.value)} />
        </Field>

        <Field label="执行提示词" required hint="说明登录后需要完成的具体操作和需要下载的文件。">
          <Textarea
            resize="vertical"
            rows={7}
            value={config.prompt}
            onChange={(_, data) => update('prompt', data.value)}
          />
        </Field>
      </div>

      <div className="editor-actions">
        <Button appearance="primary" icon={<Save20Regular />} onClick={validateAndSave}>
          保存更改
        </Button>
      </div>
    </section>
  )
}

function ModelConfigForm({ modelConfig, onChange, onSave }) {
  const [showApiKey, setShowApiKey] = useState(false)
  const [connectionState, setConnectionState] = useState('idle')

  function update(field, value) {
    onChange({ ...modelConfig, [field]: value })
  }

  function testConnection() {
    setConnectionState('testing')
    window.setTimeout(() => setConnectionState(modelConfig.apiKey ? 'success' : 'error'), 900)
  }

  return (
    <div className="model-layout">
      <section className="model-intro">
        <div className="model-intro-icon">
          <ShieldKeyhole20Regular />
        </div>
        <h2>模型服务</h2>
        <p>连接用于驱动浏览器任务的模型。API Key 仅用于本机请求。</p>
        <div className="security-note">
          <Key20Regular />
          <span>正式桌面版将通过 Windows DPAPI 加密保存敏感信息。</span>
        </div>
      </section>

      <section className="model-form">
        <div className="editor-header">
          <div>
            <h2>私人配置</h2>
            <p>设置个人 API 服务和模型名称。</p>
          </div>
          {connectionState === 'success' && <StatusBadge tone="success">连接正常</StatusBadge>}
          {connectionState === 'error' && <StatusBadge tone="danger">缺少 API Key</StatusBadge>}
        </div>

        <div className="editor-form">
          <Field label="API Key" required hint="原型阶段不会发送或验证此密钥。">
            <Input
              type={showApiKey ? 'text' : 'password'}
              value={modelConfig.apiKey}
              placeholder="输入你的 API Key"
              onChange={(_, data) => update('apiKey', data.value)}
              contentBefore={<Key20Regular />}
              contentAfter={
                <Button
                  appearance="subtle"
                  icon={showApiKey ? <EyeOff20Regular /> : <Eye20Regular />}
                  onClick={() => setShowApiKey((value) => !value)}
                  aria-label={showApiKey ? '隐藏 API Key' : '显示 API Key'}
                />
              }
            />
          </Field>

          <Field label="API Base URL" required>
            <Input value={modelConfig.baseUrl} onChange={(_, data) => update('baseUrl', data.value)} />
          </Field>

          <Field label="模型名称" required hint="保留服务商提供的原始模型名称。">
            <Input contentBefore={<Bot20Regular />} value={modelConfig.modelName} onChange={(_, data) => update('modelName', data.value)} />
          </Field>
        </div>

        <div className="editor-actions split-actions">
          <Button appearance="secondary" icon={<ArrowSync20Regular />} onClick={testConnection} disabled={connectionState === 'testing'}>
            {connectionState === 'testing' ? '测试中' : '测试连接'}
          </Button>
          <Button appearance="primary" icon={<Save20Regular />} onClick={onSave}>
            保存配置
          </Button>
        </div>
      </section>
    </div>
  )
}

function ConfigurationCenter({ configs, setConfigs, selectedConfigId, setSelectedConfigId, modelConfig, setModelConfig, notify }) {
  const [tab, setTab] = useState('website')
  const selectedConfig = configs.find((config) => config.id === selectedConfigId)

  function addConfig() {
    const id = `config-${Date.now()}`
    const newConfig = {
      id,
      name: '未命名任务',
      url: 'https://',
      username: '',
      password: '',
      prompt: '',
      successCriteria: '页面不再显示登录表单，并进入登录后的目标页面。',
    }
    setConfigs((current) => [...current, newConfig])
    setSelectedConfigId(id)
  }

  function updateConfig(nextConfig) {
    setConfigs((current) => current.map((config) => (config.id === nextConfig.id ? nextConfig : config)))
  }

  function deleteConfig() {
    if (!selectedConfig) return
    const nextConfigs = configs.filter((config) => config.id !== selectedConfig.id)
    setConfigs(nextConfigs)
    setSelectedConfigId(nextConfigs[0]?.id ?? '')
    notify('配置已删除。')
  }

  return (
    <main className="page-content">
      <PageHeader
        title="配置中心"
        description="管理网站登录任务和个人模型服务。"
        action={
          tab === 'website' ? (
            <Button appearance="primary" icon={<Add20Regular />} onClick={addConfig}>
              新建配置
            </Button>
          ) : null
        }
      />

      <TabList selectedValue={tab} onTabSelect={(_, data) => setTab(data.value)} className="config-tabs">
        <Tab value="website" icon={<Globe20Regular />}>
          网站任务
        </Tab>
        <Tab value="model" icon={<Key20Regular />}>
          模型服务
        </Tab>
      </TabList>

      {tab === 'website' ? (
        <div className="configuration-layout">
          <ConfigList configs={configs} selectedId={selectedConfigId} onSelect={setSelectedConfigId} onAdd={addConfig} />
          <WebsiteConfigForm
            config={selectedConfig}
            onChange={updateConfig}
            onDelete={deleteConfig}
            onSave={() => notify('网站任务已保存。')}
          />
        </div>
      ) : (
        <ModelConfigForm modelConfig={modelConfig} onChange={setModelConfig} onSave={() => notify('模型配置已保存。')} />
      )}
    </main>
  )
}

function LoadingScreen() {
  return (
    <div className="loading-shell" aria-label="正在加载">
      <Skeleton className="loading-sidebar">
        <SkeletonItem shape="rectangle" size={36} />
        <SkeletonItem shape="rectangle" size={32} />
        <SkeletonItem shape="rectangle" size={32} />
      </Skeleton>
      <Skeleton className="loading-content">
        <SkeletonItem shape="rectangle" size={40} />
        <SkeletonItem shape="rectangle" size={20} />
        <SkeletonItem shape="rectangle" className="loading-panel" />
      </Skeleton>
    </div>
  )
}

export function App() {
  const [ready, setReady] = useState(false)
  const [currentPage, setCurrentPage] = useState('execution')
  const [darkMode, setDarkMode] = useState(() => readStoredValue('browser-desk-theme-v2', false))
  const [configs, setConfigs] = useState(() =>
    readStoredValue('browser-desk-configs-v2', initialConfigs).map((config) => ({ ...config, password: config.password ?? '' })),
  )
  const [modelConfig, setModelConfig] = useState(() => ({
    ...readStoredValue('browser-desk-model-v2', initialModelConfig),
    apiKey: '',
  }))
  const [selectedConfigId, setSelectedConfigId] = useState(() => configs[0]?.id ?? '')
  const [toastMessage, setToastMessage] = useState('')

  useEffect(() => {
    const timer = window.setTimeout(() => setReady(true), 420)
    return () => window.clearTimeout(timer)
  }, [])

  useEffect(() => {
    const safeConfigs = configs.map((config) => ({ ...config, password: '' }))
    window.localStorage.setItem('browser-desk-configs-v2', JSON.stringify(safeConfigs))
  }, [configs])

  useEffect(() => {
    window.localStorage.setItem('browser-desk-model-v2', JSON.stringify({ ...modelConfig, apiKey: '' }))
  }, [modelConfig])

  useEffect(() => {
    window.localStorage.setItem('browser-desk-theme-v2', JSON.stringify(darkMode))
  }, [darkMode])

  const theme = useMemo(() => (darkMode ? webDarkTheme : webLightTheme), [darkMode])

  function notify(message) {
    setToastMessage('')
    window.setTimeout(() => setToastMessage(message), 0)
  }

  return (
    <FluentProvider theme={theme} className={darkMode ? 'app-theme dark' : 'app-theme'}>
      {!ready ? (
        <LoadingScreen />
      ) : (
        <div className="app-shell">
          <Sidebar
            currentPage={currentPage}
            onNavigate={setCurrentPage}
            darkMode={darkMode}
            onToggleTheme={() => setDarkMode((value) => !value)}
          />
          {currentPage === 'execution' ? (
            <ExecutionCenter configs={configs} selectedConfigId={selectedConfigId} onSelectConfig={setSelectedConfigId} />
          ) : (
            <ConfigurationCenter
              configs={configs}
              setConfigs={setConfigs}
              selectedConfigId={selectedConfigId}
              setSelectedConfigId={setSelectedConfigId}
              modelConfig={modelConfig}
              setModelConfig={setModelConfig}
              notify={notify}
            />
          )}
          <AppToaster message={toastMessage} />
        </div>
      )}
    </FluentProvider>
  )
}
