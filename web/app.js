const tabButtons = document.querySelectorAll(".tab-btn")
const panels = {
  chat: document.getElementById("tab-chat"),
  dashboard: document.getElementById("tab-dashboard"),
  knowledge: document.getElementById("tab-knowledge"),
}
const chatMessages = document.getElementById("chatMessages")
const chatInput = document.getElementById("chatInput")
const sendBtn = document.getElementById("sendBtn")
const sessionIdInput = document.getElementById("sessionId")
const userIdInput = document.getElementById("userId")
const useMemory = document.getElementById("useMemory")
const topK = document.getElementById("topK")
const newSessionBtn = document.getElementById("newSessionBtn")
const sessionList = document.getElementById("sessionList")
const refreshDashboard = document.getElementById("refreshDashboard")
const kpiRequests = document.getElementById("kpiRequests")
const kpiErrors = document.getElementById("kpiErrors")
const kpiLatency = document.getElementById("kpiLatency")
const kpiDenied = document.getElementById("kpiDenied")
const dashboardRaw = document.getElementById("dashboardRaw")
const trendCanvas = document.getElementById("trendCanvas")
const docSource = document.getElementById("docSource")
const docFiles = document.getElementById("docFiles")
const uploadDocBtn = document.getElementById("uploadDocBtn")
const uploadResult = document.getElementById("uploadResult")
const refreshDocsBtn = document.getElementById("refreshDocsBtn")
const docsList = document.getElementById("docsList")
const uploadProgressWrap = document.getElementById("uploadProgressWrap")
const uploadProgressBar = document.getElementById("uploadProgressBar")
const uploadPercentText = document.getElementById("uploadPercentText")
const uploadStageText = document.getElementById("uploadStageText")
const uploadStepText = document.getElementById("uploadStepText")
const CHAT_STORAGE_KEY = "meta_agent_chat_sessions_v1"
const CHAT_MAX_SESSIONS = 20
const CHAT_MAX_MESSAGES_PER_SESSION = 120

const chatState = {
  sessions: {},
  current: "",
}

function genSessionId() {
  return `s-${Date.now().toString(36)}`
}

function saveChatState() {
  const payload = {
    current: chatState.current,
    sessions: chatState.sessions,
  }
  try {
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(payload))
  } catch (_) {}
}

function loadChatState() {
  try {
    const raw = localStorage.getItem(CHAT_STORAGE_KEY)
    if (!raw) return false
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== "object") return false
    if (!parsed.sessions || typeof parsed.sessions !== "object") return false
    const entries = Object.entries(parsed.sessions)
    if (!entries.length) return false
    const sliced = entries.slice(-CHAT_MAX_SESSIONS)
    chatState.sessions = Object.fromEntries(sliced)
    const current = String(parsed.current || "")
    chatState.current = current && chatState.sessions[current] ? current : sliced[sliced.length - 1][0]
    return true
  } catch (_) {
    return false
  }
}

function initSession() {
  if (loadChatState()) {
    const sid = chatState.current
    sessionIdInput.value = sid
    userIdInput.value = "web-user"
    renderSessionList()
    renderMessages()
    return
  }
  const sid = genSessionId()
  chatState.sessions[sid] = { title: "新会话", messages: [] }
  chatState.current = sid
  sessionIdInput.value = sid
  userIdInput.value = "web-user"
  renderSessionList()
  renderMessages()
  saveChatState()
}

function renderSessionList() {
  sessionList.innerHTML = ""
  const entries = Object.entries(chatState.sessions)
  for (const [sid, data] of entries) {
    const div = document.createElement("div")
    div.className = `session-item ${sid === chatState.current ? "active" : ""}`
    div.textContent = `${data.title}\n${sid}`
    div.addEventListener("click", () => {
      chatState.current = sid
      sessionIdInput.value = sid
      renderSessionList()
      renderMessages()
    })
    sessionList.appendChild(div)
  }
}

function pushMessage(role, content, meta = "") {
  const sid = chatState.current
  if (!chatState.sessions[sid]) {
    chatState.sessions[sid] = { title: "新会话", messages: [] }
  }
  chatState.sessions[sid].messages.push({ role, content, meta, process: null })
  if (chatState.sessions[sid].messages.length > CHAT_MAX_MESSAGES_PER_SESSION) {
    chatState.sessions[sid].messages = chatState.sessions[sid].messages.slice(-CHAT_MAX_MESSAGES_PER_SESSION)
  }
  if (role === "user" && chatState.sessions[sid].title === "新会话") {
    chatState.sessions[sid].title = content.slice(0, 16) || "新会话"
  }
  const ids = Object.keys(chatState.sessions)
  if (ids.length > CHAT_MAX_SESSIONS) {
    const stale = ids[0]
    if (stale && stale !== chatState.current) delete chatState.sessions[stale]
  }
  saveChatState()
}

function renderMessages() {
  chatMessages.innerHTML = ""
  const sid = chatState.current
  const rows = chatState.sessions[sid]?.messages || []
  for (const row of rows) {
    const block = document.createElement("div")
    block.className = `msg ${row.role}`
    if (row.role === "assistant" && row.process) {
      const details = document.createElement("details")
      details.className = "msg-subpanel"
      const summary = document.createElement("summary")
      summary.textContent = "思考过程与工具调用"
      details.appendChild(summary)
      const processBody = document.createElement("div")
      processBody.className = "msg-subpanel-body"
      const thinking = Array.isArray(row.process.thinking_steps) ? row.process.thinking_steps.join("\n") : "-"
      const tools = Array.isArray(row.process.tool_calls)
        ? row.process.tool_calls.map((x, i) => `${i + 1}. ${x.name || "unknown"}`).join("\n")
        : "-"
      const retrieval = row.process?.route_meta?.retrieval || {}
      const rerankerType = retrieval.reranker_type || "-"
      const docCandidates = retrieval.doc_candidates || 0
      const bgeUsed = Boolean(retrieval?.doc_rerank?.used_bge)
      const bgeLatency = retrieval?.doc_rerank?.bge_latency_ms || 0
      const bgeReason = retrieval?.doc_rerank?.bge_meta?.reason || "-"
      const bgeBackend = retrieval?.doc_rerank?.bge_meta?.backend || "-"
      processBody.textContent =
        `思考过程:\n${thinking}\n\n工具调用:\n${tools}\n\nRAG调试:\n` +
        `reranker=${rerankerType}\n` +
        `doc_candidates=${docCandidates}\n` +
        `bge_used=${bgeUsed}\n` +
        `bge_latency_ms=${bgeLatency}\n` +
        `bge_backend=${bgeBackend}\n` +
        `bge_reason=${bgeReason}`
      details.appendChild(processBody)
      block.appendChild(details)
    }
    const main = document.createElement("div")
    main.className = "msg-main"
    main.textContent = row.content
    block.appendChild(main)
    if (row.meta) {
      const meta = document.createElement("div")
      meta.className = "msg-meta"
      meta.textContent = row.meta
      block.appendChild(meta)
    }
    chatMessages.appendChild(block)
  }
  chatMessages.scrollTop = chatMessages.scrollHeight
}

function tokenizeForRender(text) {
  return String(text || "").match(/[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\s]/g) || []
}

function appendAssistantToken(sessionId, idx, token) {
  const rows = chatState.sessions[sessionId].messages
  const prev = rows[idx].content
  const needsSpace = /[A-Za-z0-9_]$/.test(prev) && /^[A-Za-z0-9_]/.test(token)
  rows[idx].content += `${needsSpace ? " " : ""}${token}`
  const lastBlock = chatMessages.lastElementChild
  if (lastBlock) {
    lastBlock.classList.add("typing")
    const mainNode = lastBlock.querySelector(".msg-main")
    if (mainNode) mainNode.textContent = rows[idx].content
  }
}

function finishAssistantTyping() {
  const lastBlock = chatMessages.lastElementChild
  if (lastBlock) lastBlock.classList.remove("typing")
}

async function streamMessage(text, meta, process = null) {
  const sid = chatState.current
  const row = { role: "assistant", content: "", meta, process }
  chatState.sessions[sid].messages.push(row)
  renderMessages()
  const rows = chatState.sessions[sid].messages
  const idx = rows.length - 1
  const tokens = tokenizeForRender(text)
  const speed = tokens.length > 800 ? 2 : 8
  for (let i = 0; i < tokens.length; i++) {
    appendAssistantToken(sid, idx, tokens[i])
    if (i % speed === 0) {
      await new Promise((resolve) => setTimeout(resolve, 8))
    }
  }
  finishAssistantTyping()
  renderMessages()
}

function formatAssistantMessage(data) {
  let summary = String(data.output ?? "")
  let toolResults = Array.isArray(data.tool_results) ? data.tool_results : []
  try {
    const parsed = JSON.parse(summary)
    if (parsed && typeof parsed === "object") {
      summary = String(parsed.summary ?? summary)
      if (Array.isArray(parsed.tool_results)) {
        toolResults = parsed.tool_results
      }
    }
  } catch (_) {}
  for (let i = 0; i < 2; i++) {
    try {
      const nested = JSON.parse(summary)
      if (nested && typeof nested === "object" && nested.summary) {
        summary = String(nested.summary)
        continue
      }
    } catch (_) {}
    break
  }
  if (!summary.trim()) {
    summary = "当前回答为空，已返回工具结果。"
  }
  const toolLines = toolResults.length
    ? toolResults.map((t, i) => `${i + 1}. ${t.tool}${t.permission ? ` (${t.permission})` : ""}`).join("\n")
    : "无"
  const memory = data.memory_meta || {}
  const main = [summary, "", "工具结果：", toolLines].join("\n")
  const meta = [
    `trace=${data.trace_id || "-"}`,
    `bucket=${data.release_bucket || "-"}`,
    `memory(enabled=${Boolean(memory.enabled)}, short_turns=${memory.short_turns || 0}, rag_hits=${memory.rag_hits || 0}, long_hits=${memory.long_hits || 0})`,
  ].join(" | ")
  return { main, meta }
}

for (const btn of tabButtons) {
  btn.addEventListener("click", () => {
    for (const b of tabButtons) b.classList.remove("active")
    btn.classList.add("active")
    const key = btn.dataset.tab
    for (const name of Object.keys(panels)) panels[name].classList.remove("active")
    panels[key].classList.add("active")
    if (key === "dashboard") {
      loadDashboard()
    }
    if (key === "knowledge") {
      loadKnowledgeDocs()
    }
  })
}

newSessionBtn.addEventListener("click", () => {
  const sid = genSessionId()
  chatState.sessions[sid] = { title: "新会话", messages: [] }
  chatState.current = sid
  sessionIdInput.value = sid
  renderSessionList()
  renderMessages()
  saveChatState()
})

sendBtn.addEventListener("click", async () => {
  const task = chatInput.value.trim()
  if (!task) return
  const sid = sessionIdInput.value.trim() || genSessionId()
  if (!chatState.sessions[sid]) {
    chatState.sessions[sid] = { title: "新会话", messages: [] }
  }
  chatState.current = sid
  sessionIdInput.value = sid
  pushMessage("user", task)
  renderSessionList()
  renderMessages()
  chatInput.value = ""
  const body = {
    domain: "default",
    task,
    session_id: sid,
    user_id: userIdInput.value || "web-user",
    use_memory: useMemory.checked,
    top_k: Number(topK.value || 4),
  }
  try {
    const resp = await fetch("/v1/generate/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    if (!resp.ok || !resp.body) {
      throw new Error(`request_failed:${resp.status}`)
    }
    const sid2 = chatState.current
    const row = { role: "assistant", content: "", meta: "", process: null }
    chatState.sessions[sid2].messages.push(row)
    saveChatState()
    renderMessages()
    const idx = chatState.sessions[sid2].messages.length - 1
    const reader = resp.body.getReader()
    const decoder = new TextDecoder("utf-8")
    let buffer = ""
    let eventName = "message"
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let sep = buffer.indexOf("\n\n")
      while (sep >= 0) {
        const raw = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        const lines = raw.split("\n")
        let dataLine = ""
        for (const line of lines) {
          if (line.startsWith("event:")) eventName = line.slice(6).trim()
          if (line.startsWith("data:")) dataLine += line.slice(5).trim()
        }
        if (dataLine) {
          let payload = {}
          try { payload = JSON.parse(dataLine) } catch (_) {}
          if (eventName === "process") {
            chatState.sessions[sid2].messages[idx].process = payload
            renderMessages()
            saveChatState()
          } else if (eventName === "meta") {
            const m = payload.memory_meta || {}
            const docRerank = m.doc_rerank || {}
            const bgeMeta = docRerank.bge_meta || {}
            chatState.sessions[sid2].messages[idx].meta =
              `trace=${payload.trace_id || "-"} | bucket=${payload.release_bucket || "-"} | ` +
              `memory(enabled=${Boolean(m.enabled)}, short_turns=${m.short_turns || 0}, rag_hits=${m.rag_hits || 0}, long_hits=${m.long_hits || 0}) | ` +
              `reranker=${m.reranker_type || "-"} | bge_used=${Boolean(docRerank.used_bge)} | bge_reason=${bgeMeta.reason || "-"}`
            renderMessages()
            saveChatState()
          } else if (eventName === "token") {
            appendAssistantToken(sid2, idx, String(payload.token || ""))
          } else if (eventName === "error") {
            throw new Error(String(payload.message || "stream_error"))
          }
        }
        sep = buffer.indexOf("\n\n")
      }
    }
    finishAssistantTyping()
    renderMessages()
    saveChatState()
  } catch (err) {
    try {
      const fallbackResp = await fetch("/v1/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      const fallback = await fallbackResp.json()
      if (!fallbackResp.ok) throw new Error(fallback.detail || "fallback_request_failed")
      const rendered = formatAssistantMessage(fallback)
      await streamMessage(rendered.main, `${rendered.meta} | fallback=true`, fallback.process || null)
      saveChatState()
    } catch (err2) {
      pushMessage("assistant", `请求失败: ${String(err2)}`)
      renderMessages()
    }
  }
})

chatInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return
  if (event.shiftKey) return
  event.preventDefault()
  sendBtn.click()
})

function drawTrends(labels, series, color, yMax, yOffset) {
  const ctx = trendCanvas.getContext("2d")
  const width = trendCanvas.width
  const height = trendCanvas.height
  const left = 56
  const right = width - 20
  const top = 20 + yOffset
  const bottom = height - 24
  const xStep = labels.length <= 1 ? 0 : (right - left) / (labels.length - 1)
  ctx.strokeStyle = color
  ctx.lineWidth = 2
  ctx.beginPath()
  for (let i = 0; i < labels.length; i++) {
    const x = left + xStep * i
    const y = bottom - ((series[i] || 0) / Math.max(1, yMax)) * (bottom - top)
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  }
  ctx.stroke()
}

function renderTrendChart(trend) {
  const ctx = trendCanvas.getContext("2d")
  ctx.clearRect(0, 0, trendCanvas.width, trendCanvas.height)
  ctx.fillStyle = "#94a3b8"
  ctx.font = "12px Segoe UI"
  const labels = trend.labels || []
  const req = trend.request_series || []
  const err = trend.error_series || []
  const lat = trend.latency_series || []
  const maxReq = Math.max(1, ...req)
  const maxLat = Math.max(1, ...lat)
  drawTrends(labels, req, "#38bdf8", maxReq, 0)
  drawTrends(labels, err, "#ef4444", maxReq, 0)
  drawTrends(labels, lat, "#22c55e", maxLat, 8)
  ctx.fillText("蓝=请求 红=错误 绿=延迟", 20, 16)
}

async function loadDashboard() {
  try {
    const [summaryResp, trendResp] = await Promise.all([
      fetch("/v1/dashboard/summary"),
      fetch("/v1/dashboard/trends?points=30"),
    ])
    const summary = await summaryResp.json()
    const trend = await trendResp.json()
    kpiRequests.textContent = String(summary.total_requests)
    kpiErrors.textContent = String(summary.error_count)
    kpiLatency.textContent = `${summary.avg_latency_ms}ms`
    kpiDenied.textContent = String(summary.audit_denied_count)
    dashboardRaw.textContent = JSON.stringify({ summary, trend }, null, 2)
    renderTrendChart(trend)
  } catch (err) {
    dashboardRaw.textContent = `加载失败: ${String(err)}`
  }
}

refreshDashboard.addEventListener("click", loadDashboard)

function formatTs(ts) {
  if (!ts) return "-"
  const dt = new Date(Number(ts) * 1000)
  if (Number.isNaN(dt.getTime())) return "-"
  return dt.toLocaleString()
}

function renderKnowledgeDocs(items) {
  docsList.innerHTML = ""
  if (!Array.isArray(items) || items.length === 0) {
    const empty = document.createElement("div")
    empty.className = "doc-row"
    empty.textContent = "当前知识库暂无文档。"
    docsList.appendChild(empty)
    return
  }
  for (const item of items) {
    const row = document.createElement("div")
    row.className = "doc-row"
    const source = String(item.source || "")
    const filename = source.includes(":") ? source.split(":").slice(-1)[0] : source
    row.innerHTML = [
      `<div class="doc-name">${filename || "unknown"}</div>`,
      `<div class="doc-meta">source=${source || "-"} | chunks=${item.chunks || 0} | updated=${formatTs(item.updated_at)}</div>`,
      `<div class="doc-id">${item.doc_id || "-"}</div>`,
    ].join("")
    docsList.appendChild(row)
  }
}

async function loadKnowledgeDocs() {
  try {
    const resp = await fetch("/v1/rag/documents?domain=default")
    const data = await resp.json()
    if (!resp.ok) throw new Error(data.detail || "load_docs_failed")
    renderKnowledgeDocs(data.items || [])
  } catch (err) {
    docsList.innerHTML = ""
    const row = document.createElement("div")
    row.className = "doc-row"
    row.textContent = `加载文档失败: ${String(err)}`
    docsList.appendChild(row)
  }
}

function setUploadProgress(percent, stage, stepText) {
  const safe = Math.max(0, Math.min(100, Number(percent || 0)))
  uploadProgressWrap.classList.remove("hidden")
  uploadProgressBar.style.width = `${safe}%`
  uploadPercentText.textContent = `${Math.round(safe)}%`
  uploadStageText.textContent = stage || "处理中"
  uploadStepText.textContent = stepText || ""
}

async function pollUploadTask(taskId) {
  for (let i = 0; i < 600; i++) {
    const resp = await fetch(`/v1/rag/upload/tasks/${encodeURIComponent(taskId)}`)
    const data = await resp.json()
    if (!resp.ok) {
      throw new Error(data.detail || "query_upload_task_failed")
    }
    const parseMeta = data?.debug?.parse_meta || {}
    const parserInfo = parseMeta.pdf_parser || parseMeta.parser || ""
    const layoutInfo = parseMeta.layout_used === true ? " | layout=true" : ""
    const stepText = parserInfo ? `${data.message} | parser=${parserInfo}${layoutInfo}` : data.message
    setUploadProgress(data.progress, data.stage, stepText)
    if (data.completed) {
      if (data.status !== "completed") {
        throw new Error(data.error || "upload_task_failed")
      }
      return data
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error("upload_task_timeout")
}

uploadDocBtn.addEventListener("click", async () => {
  const files = Array.from(docFiles.files || [])
  if (!files.length) return
  const form = new FormData()
  form.append("domain", "default")
  form.append("source", docSource.value || "manual")
  for (const file of files) {
    form.append("files", file)
  }
  setUploadProgress(0, "正在上传文件", "准备上传")
  try {
    const startResp = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open("POST", "/v1/rag/upload/tasks")
      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return
        const p = Math.min(30, Math.round((event.loaded / event.total) * 30))
        setUploadProgress(p, "正在上传文件", `已上传 ${event.loaded}/${event.total} 字节`)
      }
      xhr.onerror = () => reject(new Error("upload_network_error"))
      xhr.onload = () => {
        try {
          const payload = JSON.parse(xhr.responseText || "{}")
          if (xhr.status >= 400) {
            reject(new Error(payload.detail || "upload_start_failed"))
            return
          }
          resolve(payload)
        } catch (err) {
          reject(new Error(`upload_parse_error:${String(err)}`))
        }
      }
      xhr.send(form)
    })
    setUploadProgress(35, "正在解析文档", "后端已接收文件，开始处理")
    const data = await pollUploadTask(String(startResp.task_id))
    uploadResult.style.display = "block"
    uploadResult.textContent = JSON.stringify(data, null, 2)
    docFiles.value = ""
    await loadKnowledgeDocs()
  } catch (err) {
    uploadResult.style.display = "block"
    uploadResult.textContent = `导入失败: ${String(err)}`
  }
})

refreshDocsBtn.addEventListener("click", loadKnowledgeDocs)

initSession()
loadDashboard()
loadKnowledgeDocs()
if (window.lucide && typeof window.lucide.createIcons === "function") {
  window.lucide.createIcons()
}
