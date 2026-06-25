const form = document.querySelector("#stockForm");
const result = document.querySelector("#result");
const statusEl = document.querySelector("#status");
const serverBanner = document.querySelector("#serverBanner");
const llmStatus = document.querySelector("#llmStatus");
const llmModel = document.querySelector("#llmModel");
const chatLog = document.querySelector("#chatLog");
const chatInput = document.querySelector("#chatInput");
const chatSend = document.querySelector("#chatSend");
const saveWatchlistButton = document.querySelector("#saveWatchlistButton");
const recentHistoryEl = document.querySelector("#recentHistory");
const watchlistStatusEl = document.querySelector("#watchlistStatus");
const onlineResearch = document.querySelector("#onlineResearch");
const mascotAsk = document.querySelector("#mascotAsk");
const llmPanel = document.querySelector(".llm-panel");
const assistantToggle = document.querySelector("#assistantToggle");
const llmChips = Array.from(document.querySelectorAll(".llm-chip"));
const modeChips = Array.from(document.querySelectorAll(".mode-chip"));
const advancedPanel = document.querySelector("#advancedPanel");
const workspace = document.querySelector(".workspace");
const API_BASE = location.protocol === "file:" ? "http://127.0.0.1:8787" : "";
let lastEvaluation = null;
let currentMode = "simple";
let cachedRankings = [];
let assistantOpen = false;

const numberFields = new Set([
  "today_close",
  "pe_ttm",
  "eps_ttm",
  "bvps",
  "target_pe",
  "growth_rate",
  "planned_amount",
  "required_margin_of_safety",
]);

function endpoint(path) {
  return `${API_BASE}${path}`;
}

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function readForm() {
  const data = {};
  new FormData(form).forEach((value, key) => {
    if (!numberFields.has(key)) {
      data[key] = value;
      return;
    }
    const cleaned = String(value).trim();
    if (cleaned === "") return;
    const parsed = Number(cleaned);
    if (!Number.isNaN(parsed)) data[key] = parsed;
  });
  if (typeof data.required_margin_of_safety === "number") {
    data.required_margin_of_safety = data.required_margin_of_safety / 100;
  }
  data.symbol = document.querySelector("#symbol").value.trim();
  data.live = document.querySelector("#live").checked;
  return data;
}

function fillForm(stock) {
  clearValueFields();
  Object.entries(stock).forEach(([key, value]) => {
    const input = form.elements.namedItem(key);
    if (input && value !== undefined && value !== null) input.value = value;
  });
  if (stock.symbol) {
    document.querySelector("#symbol").value = stock.symbol;
    setActiveChip(stock.symbol);
  }
}

function clearValueFields() {
  ["today_close", "pe_ttm", "eps_ttm", "bvps"].forEach((name) => {
    const input = form.elements.namedItem(name);
    if (input) input.value = "";
  });
}

function resetForNewStock() {
  form.reset();
  document.querySelector("#symbol").value = "";
  numberFields.forEach((name) => {
    const input = form.elements.namedItem(name);
    if (input && input.type !== "checkbox") input.value = "0";
  });
  document.querySelector("#live").checked = true;
  setActiveChip("");
  statusEl.textContent = "新股票模式";
  result.innerHTML = `
    <div class="empty-state">
      <span class="empty-icon"></span>
      <h2>等待新的股票代码</h2>
      <p>参数已清零。输入代码后，可先拉行情，再手动补财务数据，或点击“带入数据”读取已有预设。</p>
    </div>
  `;
}

function currentStockLabel() {
  return lastEvaluation?.name || document.querySelector("#symbol").value.trim() || "这只股票";
}

function setActiveChip(symbol) {
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.symbol === symbol);
  });
}

function actionClass(action = "") {
  if (action.includes("达到安全边际")) return "good";
  if (action.includes("无安全边际") || action.includes("失效")) return "bad";
  return "";
}

function lensClass(level) {
  if (level === "good") return "good";
  if (level === "bad") return "bad";
  if (level === "watch") return "watch";
  return "neutral";
}

function metricTone(level) {
  return lensClass(level);
}

function barWidth(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 0;
  return Math.max(8, Math.min(100, Math.abs(Number(value)) * 100));
}

function syncAssistantPanel() {
  if (!llmPanel) return;
  const collapsed = currentMode === "simple" && !assistantOpen;
  llmPanel.dataset.collapsed = collapsed ? "true" : "false";
  if (assistantToggle) {
    assistantToggle.textContent = collapsed ? "展开助手" : "收起助手";
    assistantToggle.setAttribute("aria-expanded", String(!collapsed));
  }
}

function openAssistantPanel() {
  assistantOpen = true;
  syncAssistantPanel();
}

function setMode(mode) {
  currentMode = mode === "pro" ? "pro" : "simple";
  document.body.classList.toggle("mode-simple", currentMode === "simple");
  document.body.classList.toggle("mode-pro", currentMode === "pro");
  modeChips.forEach((chip) => chip.classList.toggle("active", chip.dataset.mode === currentMode));
  if (advancedPanel) advancedPanel.open = currentMode === "pro";
  if (currentMode === "pro") assistantOpen = true;
  syncAssistantPanel();
  if (cachedRankings.length) renderQuantRankings(cachedRankings);
}

function ensureRankingPanel() {
  let panel = document.querySelector("#rankingPanel");
  if (panel || !workspace || !workspace.parentElement) return panel;

  panel = document.createElement("section");
  panel.className = "panel ranking-dashboard";
  panel.id = "rankingPanel";
  panel.innerHTML = `
    <div class="ranking-head">
      <div>
        <h2>候选股优先级</h2>
        <p>这不是涨跌预测，而是把当前候选股按“谁更值得先研究”做一个本地排序。</p>
      </div>
      <button type="button" class="secondary pro-only" id="refreshRanking">刷新排序</button>
    </div>
    <div class="ranking-list" id="rankingList">
      <div class="empty-state compact-empty">
        <h2>等待排序</h2>
        <p>鼓手会在这里给出当前观察池里最值得先看的股票。</p>
      </div>
    </div>
  `;
  workspace.insertAdjacentElement("afterend", panel);
  panel.querySelector("#refreshRanking")?.addEventListener("click", () => {
    loadQuantRankings(true).catch((error) => {
      const list = document.querySelector("#rankingList");
      if (list) list.innerHTML = `<p>${error.message}</p>`;
    });
  });
  return panel;
}

function rankingBadge(item) {
  const source = item.quant_source === "trained_model" ? "本地排序模型" : "规则评分";
  return `${item.quant_label || "-"} · ${source}`;
}

function renderQuantRankings(rankings) {
  cachedRankings = rankings || [];
  const panel = ensureRankingPanel();
  const list = panel?.querySelector("#rankingList");
  if (!list) return;
  const compact = currentMode === "simple";
  panel.classList.toggle("compact", compact);
  if (!rankings?.length) {
    list.innerHTML = `
      <div class="empty-state compact-empty">
        <h2>暂无排序</h2>
        <p>等你带入股票后，这里会开始给出优先级。</p>
      </div>
    `;
    return;
  }

  const visibleRankings = compact ? rankings.slice(0, 3) : rankings;
  list.innerHTML = visibleRankings.map((item, index) => `
    <article class="ranking-item ${item.symbol === lastEvaluation?.symbol ? "active" : ""}">
      <div class="ranking-main">
        <div>
          <a class="ranking-name" href="detail.html?symbol=${encodeURIComponent(item.symbol)}">${item.name || item.symbol}</a>
          <p>${item.symbol}</p>
        </div>
        <div class="ranking-score">
          <strong>${fmt(item.quant_score, 1)}</strong>
          <span>第 ${index + 1} 名</span>
        </div>
      </div>
      <div class="ranking-meta">
        <span class="ranking-label">${rankingBadge(item)}</span>
        <span>${item.action || "-"}</span>
      </div>
      <p class="ranking-factors">${(item.factors || []).slice(0, 3).join(" / ") || item.intel_overall || "等待更多研究线索"}</p>
    </article>
  `).join("") + (
    compact && rankings.length > visibleRankings.length
      ? `<div class="ranking-note">分数只表示当前候选池里的相对研究优先级。普通模式只显示前三名，切到专业模式可以看完整列表。</div>`
      : ""
  );
}

async function loadQuantRankings(refresh = false) {
  const panel = ensureRankingPanel();
  const list = panel?.querySelector("#rankingList");
  if (list && refresh) {
    list.innerHTML = `
      <div class="empty-state compact-empty">
        <h2>???</h2>
        <p>??????????</p>
      </div>
    `;
  }
  const suffix = refresh ? "?refresh=1&live=1" : "";
  const data = await requestJson(`/api/quant/rankings${suffix}`);
  if (!data.ok) throw new Error(data.error || "????????");
  renderQuantRankings(data.rankings || []);
}

function render(row) {
  lastEvaluation = row;
  result.innerHTML = `
    <div class="result-head">
      <div>
        <a class="name detail-link" href="detail.html?symbol=${encodeURIComponent(row.symbol)}">${row.name || row.symbol}</a>
        <div class="sub">${row.symbol} · 行情来源 ${row.price_source} · 本地纪律判断</div>
      </div>
      <div class="action ${actionClass(row.action)}">${row.action}</div>
    </div>

    <section class="summary-strip">
      <div class="summary-card">
        <span>现在适合做什么</span>
        <strong>${row.action}</strong>
      </div>
      <div class="summary-card">
        <span>建议仓位</span>
        <strong>${pct(row.planned_weight)}</strong>
      </div>
      <div class="summary-card">
        <span>观察价格</span>
        <strong>${fmt(row.buy_below)}</strong>
      </div>
      <div class="summary-card">
        <span>核心理由</span>
        <strong>${row.value_view?.text || row.research_view?.text || "-"}</strong>
      </div>
    </section>

    <section class="core-brief">
      <article class="core-card emphasis">
        <span>核心模型判断</span>
        <strong>${row.core_model?.headline || row.quant_label || "-"}</strong>
        <p>${row.core_model?.decision_anchor || "先看估值，再看兑现。"}</p>
      </article>
      <article class="core-card">
        <span>产业链路径</span>
        <strong>${row.core_model?.theme || "通用研究框架"}</strong>
        <p>${row.core_model?.industry_chain_view || row.intel_overall || "等待更多产业链线索。"}</p>
      </article>
      <article class="core-card">
        <span>当前最该盯住</span>
        <strong>${(row.core_model?.watch_items || []).slice(0, 1)[0] || "观察兑现质量"}</strong>
        <p>${(row.core_model?.watch_items || []).slice(1).join(" / ") || row.core_model?.event_view || "把公告、财务和估值一起交叉验证。"}</p>
      </article>
    </section>

    <div class="hero-metric">
      <div class="big-number"><span>实际安全边际</span><strong>${pct(row.margin_of_safety)}</strong></div>
      <div class="big-number"><span>${pct(row.required_margin_of_safety)}门槛买入线（每股）</span><strong>${fmt(row.buy_below)}</strong></div>
    </div>

    <div class="metrics">
      <div class="metric"><span>当前价格</span><strong>${fmt(row.price)}</strong></div>
      <div class="metric"><span>保守价值</span><strong>${fmt(row.conservative_value)}</strong></div>
      <div class="metric"><span>PE(TTM)</span><strong>${fmt(row.pe_ttm)}</strong></div>
      <div class="metric"><span>PB</span><strong>${fmt(row.pb)}</strong></div>
      <div class="metric"><span>EPS(TTM)</span><strong>${fmt(row.eps_ttm, 3)}</strong></div>
      <div class="metric"><span>BVPS</span><strong>${fmt(row.bvps, 3)}</strong></div>
      <div class="metric"><span>计划投入</span><strong>${fmt(row.planned_amount, 0)}</strong></div>
      <div class="metric"><span>计划仓位</span><strong>${pct(row.planned_weight)}</strong></div>
    </div>

    <div class="lenses">
      <section class="lens ${lensClass(row.value_view?.level)}">
        <span>估值纪律</span>
        <strong>${row.value_view?.text || "-"}</strong>
      </section>
      <section class="lens ${lensClass(row.growth_view?.level)}">
        <span>成长 / 题材观察</span>
        <strong>${row.growth_view?.text || "-"}</strong>
      </section>
      <section class="lens ${lensClass(row.position_view?.level)}">
        <span>仓位风险</span>
        <strong>${row.position_view?.text || "-"}</strong>
      </section>
      <section class="lens ${lensClass(row.research_view?.level)}">
        <span>基本面研究</span>
        <strong>${row.research_view?.text || "-"}</strong>
      </section>
      <section class="lens ${lensClass(row.long_term_view?.level)}">
        <span>长线筛选</span>
        <strong>${row.long_term_view?.text || "-"}</strong>
      </section>
      <section class="lens ${lensClass(row.entry_timing_view?.level)}">
        <span>进场节奏</span>
        <strong>${row.entry_timing_view?.text || "-"}</strong>
      </section>
    </div>

    <section class="research-board">
      <div class="research-head">
        <h2>研究面板</h2>
        <span>样本更新：${row.research_updated_at || "待补全"}</span>
      </div>
      <div class="research-grid">
        <div class="research-card neutral"><span>最新报告期 EPS</span><strong>${fmt(row.latest_period_eps, 3)}</strong></div>
        <div class="research-card ${metricTone(row.revenue_growth_level)}"><span>营收同比</span><strong>${pct(row.revenue_growth)}</strong></div>
        <div class="research-card ${metricTone(row.profit_growth_level)}"><span>净利同比</span><strong>${pct(row.profit_growth)}</strong></div>
        <div class="research-card ${metricTone(row.roe_level)}"><span>ROE</span><strong>${pct(row.roe)}</strong></div>
        <div class="research-card ${metricTone(row.operating_cash_flow_growth_level)}"><span>经营现金流同比</span><strong>${pct(row.operating_cash_flow_growth)}</strong></div>
        <div class="research-card neutral"><span>经营现金流金额</span><strong>${row.operating_cash_flow_value === null || row.operating_cash_flow_value === undefined ? "-" : `${fmt(row.operating_cash_flow_value, 2)} 亿元`}</strong></div>
        <div class="research-card neutral"><span>估值分位</span><strong>${row.valuation_percentile === null || row.valuation_percentile === undefined ? "待接入" : pct(row.valuation_percentile)}</strong></div>
      </div>
      <div class="bars">
        <div class="bar-row">
          <span>营收同比</span>
          <i><b style="width:${barWidth(row.revenue_growth)}%"></b></i>
          <strong>${pct(row.revenue_growth)}</strong>
        </div>
        <div class="bar-row">
          <span>净利同比</span>
          <i><b style="width:${barWidth(row.profit_growth)}%"></b></i>
          <strong>${pct(row.profit_growth)}</strong>
        </div>
        <div class="bar-row">
          <span>ROE</span>
          <i><b style="width:${barWidth(row.roe)}%"></b></i>
          <strong>${pct(row.roe)}</strong>
        </div>
      </div>
    </section>

    <div class="explain">
      <div class="box">
        <h2>估值拆解</h2>
        <p><span>目标 PE 估值</span><strong>${fmt(row.target_pe_value)}</strong></p>
        <p><span>Graham 增长公式</span><strong>${fmt(row.graham_growth_value)}</strong></p>
        <p><span>Graham Number</span><strong>${fmt(row.graham_number)}</strong></p>
      </div>
      <div class="box">
        <h2>纪律解释</h2>
        <p><span>最低安全边际门槛</span><strong>${pct(row.required_margin_of_safety)}</strong></p>
        <p><span>通过标准</span><strong>实际安全边际 >= 门槛</strong></p>
        <p><span>买入线含义</span><strong>估值反推的每股阈值</strong></p>
        <p><span>当前判断</span><strong>${row.action}</strong></p>
      </div>
      <div class="box notice">
        <h2>数据口径</h2>
        <p><span>EPS 来源</span><strong>${row.eps_source || "未标注"}</strong></p>
        <p><span>财务参数</span><strong>${row.research_source || "本地预设 / 手动输入"}</strong></p>
        <p><span>预期压力</span><strong>${fmt(row.growth_pressure, 1)} x 目标PE</strong></p>
        <p><span>模型适配度</span><strong>${row.model_fit || "-"}</strong></p>
        <p><span>解释</span><strong>${row.model_note || "-"}</strong></p>
      </div>
    </div>
  `;
}

function appendChat(role, text, meta = "", reasoning = "") {
  const item = document.createElement("div");
  item.className = `chat-message ${role}`;
  const title = document.createElement("b");
  title.textContent = role === "user" ? "你" : "鼓手助手";
  const body = document.createElement("p");
  body.textContent = text;
  item.append(title, body);
  if (reasoning) {
    const details = document.createElement("details");
    details.className = "chat-reasoning";
    const summary = document.createElement("summary");
    summary.textContent = "查看思考过程";
    const pre = document.createElement("pre");
    pre.textContent = reasoning;
    details.append(summary, pre);
    item.appendChild(details);
  }
  if (meta) {
    const small = document.createElement("small");
    small.textContent = meta;
    item.appendChild(small);
  }
  chatLog.appendChild(item);
  chatLog.scrollTop = chatLog.scrollHeight;
  return item;
}

function updateChatMessage(item, text, meta = "", reasoning = "") {
  const body = item.querySelector("p");
  const small = item.querySelector("small") || document.createElement("small");
  const existingReasoning = item.querySelector(".chat-reasoning");
  body.textContent = text;
  if (existingReasoning) existingReasoning.remove();
  if (reasoning) {
    const details = document.createElement("details");
    details.className = "chat-reasoning";
    const summary = document.createElement("summary");
    summary.textContent = "查看思考过程";
    const pre = document.createElement("pre");
    pre.textContent = reasoning;
    details.append(summary, pre);
    body.insertAdjacentElement("afterend", details);
  }
  if (meta) {
    small.textContent = meta;
    if (!small.parentElement) item.appendChild(small);
  }
  chatLog.scrollTop = chatLog.scrollHeight;
}

function basisMeta(data) {
  const basis = data.basis?.length ? `依据：${data.basis.join(" / ")}` : "";
  const elapsed = data.elapsed_seconds ? `耗时：${data.elapsed_seconds}s` : "";
  return [basis, elapsed].filter(Boolean).join(" · ");
}

function defaultModel(models) {
  const names = models.map((model) => model.name || model.model).filter(Boolean);
  return (
    names.find((name) => name === "stockguard-ft-v2:q4") ||
    names.find((name) => name === "stockguard-ft:q4") ||
    names.find((name) => name === "stockguard:latest" || name === "stockguard") ||
    names.find((name) => name === "deepseek-r1:8b") ||
    names.find((name) => name === "deepseek-r1:7b") ||
    names.find((name) => name === "deepseek-r1:14b") ||
    names.find((name) => name.includes("deepseek")) ||
    names.find((name) => !name.includes("bge")) ||
    names[0]
  );
}

async function loadLlmModels() {
  if (!llmModel) return;
  try {
    const data = await requestJson("/api/llm/models");
    if (!data.ok) throw new Error(data.error || "本地模型未连接");
    const models = data.models || [];
    llmModel.innerHTML = "";
    models
      .filter((model) => !String(model.name || model.model || "").includes("bge"))
      .forEach((model) => {
        const option = document.createElement("option");
        option.value = model.name || model.model;
        option.textContent = `${model.name || model.model} · ${model.details?.parameter_size || ""}`;
        llmModel.appendChild(option);
      });
    const preferred = defaultModel(models);
    if (preferred) llmModel.value = preferred;
    llmStatus.textContent = preferred ? "已连接 Ollama" : "未发现对话模型";
  } catch (error) {
    llmStatus.textContent = "未连接";
    appendChat("assistant", "未连接到本地 Ollama。请先运行：ollama serve，然后刷新页面。");
  }
}

async function sendChat() {
  const message = chatInput.value.trim();
  if (!message) return;
  openAssistantPanel();
  appendChat("user", message);
  chatInput.value = "";
  chatSend.disabled = true;
  chatSend.textContent = "模型思考中";
  const pending = appendChat(
    "assistant",
    "正在读取当前页面数据，并发送给本地模型，请稍等。",
    "会展示处理进度、依据摘要和可展开的思考过程。"
  );
  try {
    const data = await requestJson("/api/llm/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: llmModel.value,
        message,
        use_online_research: onlineResearch?.checked ?? true,
        context: {
          form: readForm(),
          evaluation: lastEvaluation,
        },
      }),
    });
    if (!data.ok) throw new Error(data.error || "本地模型调用失败");
    updateChatMessage(pending, data.answer, basisMeta(data), data.reasoning || "");
  } catch (error) {
    updateChatMessage(pending, error.message || "本地模型调用失败");
  } finally {
    chatSend.disabled = false;
    chatSend.textContent = "发送给本地模型";
  }
}

function askFromMascot() {
  const label = currentStockLabel();
  openAssistantPanel();
  chatInput.value = `结合当前页面抓取的数据，判断${label}现在是否适合继续买入或加仓，并给出仓位、观察价位和止损纪律。`;
  chatInput.focus();
  chatInput.scrollIntoView({ behavior: "smooth", block: "center" });
}

function watchlistRequestPayload() {
  return {
    stock: {
      ...readForm(),
      ...lastEvaluation,
      symbol: document.querySelector("#symbol").value.trim(),
      today_close: lastEvaluation?.price ?? readForm().today_close,
    },
    result: lastEvaluation || {},
  };
}

function historyMeta(item) {
  const parts = [];
  if (item.action) parts.push(item.action);
  if (item.quant_label) parts.push(item.quant_label);
  if (item.price !== null && item.price !== undefined && !Number.isNaN(Number(item.price))) {
    parts.push(`价格 ${fmt(item.price)}`);
  }
  return parts.join(" / ");
}

function renderHistory(data) {
  if (watchlistStatusEl) {
    watchlistStatusEl.textContent = `观察池 ${data.watchlist_count || 0} 只`;
  }
  if (!recentHistoryEl) return;

  const watchlist = data.watchlist || [];
  const recent = data.recent_symbols || [];
  const currentSymbol = document.querySelector("#symbol").value.trim();
  const alreadyTracked = watchlist.some((item) => item.symbol === currentSymbol);
  if (saveWatchlistButton) {
    saveWatchlistButton.textContent = alreadyTracked ? "更新观察池" : "加入观察池";
  }

  recentHistoryEl.innerHTML = `
    <div class="memory-group">
      <span class="memory-label">观察池</span>
      <div class="memory-chips">
        ${
          watchlist.length
            ? watchlist
                .map(
                  (item) =>
                    `<button type="button" class="memory-chip" data-symbol="${item.symbol}">${item.name || item.symbol}</button>`
                )
                .join("")
            : '<span class="memory-empty inline">还没有保存过股票。</span>'
        }
      </div>
    </div>
    <div class="memory-group">
      <span class="memory-label">最近查看</span>
      <div class="memory-history">
        ${
          recent.length
            ? recent
                .map(
                  (item) => `
                    <button type="button" class="history-item" data-symbol="${item.symbol}">
                      <strong>${item.name || item.symbol}</strong>
                      <span>${item.symbol}</span>
                      <small>${historyMeta(item) || "最近查看"}</small>
                    </button>
                  `
                )
                .join("")
            : '<div class="memory-empty">最近查看和保存的股票会出现在这里。</div>'
        }
      </div>
    </div>
  `;
}

async function loadHistory() {
  const data = await requestJson("/api/history");
  if (!data.ok) throw new Error(data.error || "读取本地记录失败");
  renderHistory(data);
}

async function saveWatchlist() {
  const symbol = document.querySelector("#symbol").value.trim();
  if (!symbol) {
    statusEl.textContent = "请先输入股票代码";
    return;
  }
  saveWatchlistButton.disabled = true;
  saveWatchlistButton.textContent = "保存中";
  try {
    const data = await requestJson("/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(watchlistRequestPayload()),
    });
    if (!data.ok) throw new Error(data.error || "保存失败");
    statusEl.textContent = data.mode === "created" ? "已加入观察池" : "已更新观察池";
    await loadHistory();
    await loadQuantRankings(true);
  } catch (error) {
    statusEl.textContent = error.message || "保存失败";
  } finally {
    saveWatchlistButton.disabled = false;
  }
}

async function requestJson(path, options) {
  const response = await fetch(endpoint(path), options);
  return response.json();
}

async function loadPreset() {
  const symbol = document.querySelector("#symbol").value.trim();
  const data = await requestJson(`/api/preset?symbol=${encodeURIComponent(symbol)}`);
  if (!data.ok) throw new Error(data.error || "读取失败");
  fillForm(data.stock);
  if (document.querySelector("#live").checked) {
    await syncLiveQuoteIntoForm(symbol);
  }
  statusEl.textContent = data.stock.name ? `已带入 ${data.stock.name}` : "未找到预设";
}

async function evaluateStock(event) {
  event?.preventDefault();
  statusEl.textContent = "计算中";
  try {
    const data = await requestJson("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readForm()),
    });
    if (!data.ok) {
      statusEl.textContent = data.error || "计算失败";
      return;
    }
    render(data.result);
    fillDerivedDisplay(data.result);
    renderQuantRankings(cachedRankings);
    statusEl.textContent = "计算完成";
    loadHistory().catch(() => {});
  } catch (error) {
    statusEl.textContent = error.message || "计算失败";
  }
}

async function loadQuote() {
  const symbol = document.querySelector("#symbol").value.trim();
  const quote = await syncLiveQuoteIntoForm(symbol);
  statusEl.textContent = `${quote.name} 实时价 ${fmt(quote.price)}`;
}

async function refreshResearch() {
  const symbol = document.querySelector("#symbol").value.trim();
  statusEl.textContent = "刷新研究指标中";
  const data = await requestJson(`/api/research?symbol=${encodeURIComponent(symbol)}`);
  if (!data.ok) throw new Error(data.error || "研究指标刷新失败");
  fillForm({ ...readForm(), ...data.research, symbol });
  statusEl.textContent = `研究指标已更新至 ${data.research.research_updated_at || "最新可得期"}`;
}

async function syncLiveQuoteIntoForm(symbol) {
  const data = await requestJson(`/api/quote?symbol=${encodeURIComponent(symbol)}`);
  if (!data.ok) throw new Error(data.error || "行情读取失败");
  document.querySelector("#price").value = data.quote.price;
  return data.quote;
}

function hydrateFromQuery() {
  const params = new URLSearchParams(location.search);
  params.forEach((value, key) => {
    const input = form.elements.namedItem(key);
    if (input && input.type !== "checkbox") input.value = value;
  });
  if (params.has("live")) document.querySelector("#live").checked = true;
}

function fillDerivedDisplay(row) {
  const epsInput = form.elements.namedItem("eps_ttm");
  if (epsInput && !String(epsInput.value).trim() && row.eps_ttm) {
    epsInput.value = Number(row.eps_ttm).toFixed(3);
  }
  const marginInput = form.elements.namedItem("required_margin_of_safety");
  if (marginInput && row.required_margin_of_safety !== undefined) {
    marginInput.value = Math.round(Number(row.required_margin_of_safety) * 100);
  }
}

document.querySelector("#loadPreset").addEventListener("click", () => loadPreset().catch((err) => {
  statusEl.textContent = err.message;
}));
document.querySelector("#quoteButton").addEventListener("click", () => loadQuote().catch((err) => {
  statusEl.textContent = err.message;
}));
document.querySelector("#researchButton").addEventListener("click", () => refreshResearch().catch((err) => {
  statusEl.textContent = err.message;
}));
saveWatchlistButton?.addEventListener("click", saveWatchlist);
document.querySelector("#newStockButton").addEventListener("click", resetForNewStock);
mascotAsk?.addEventListener("click", askFromMascot);
chatSend?.addEventListener("click", sendChat);
assistantToggle?.addEventListener("click", () => {
  assistantOpen = !assistantOpen;
  syncAssistantPanel();
});
llmChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    openAssistantPanel();
    chatInput.value = chip.dataset.prompt || "";
    chatInput.focus();
  });
});
chatInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    sendChat();
  }
});
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", async () => {
    document.querySelector("#symbol").value = chip.dataset.symbol;
    setActiveChip(chip.dataset.symbol);
    try {
      await loadPreset();
      await evaluateStock();
    } catch (err) {
      statusEl.textContent = err.message;
    }
  });
});
recentHistoryEl?.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-symbol]");
  if (!target) return;
  document.querySelector("#symbol").value = target.dataset.symbol;
  setActiveChip(target.dataset.symbol);
  try {
    await loadPreset();
    await evaluateStock();
  } catch (err) {
    statusEl.textContent = err.message;
  }
});
form.addEventListener("submit", evaluateStock);
modeChips.forEach((chip) => {
  chip.addEventListener("click", () => setMode(chip.dataset.mode));
});

hydrateFromQuery();
setMode("simple");
if (location.protocol === "file:") {
  serverBanner.hidden = false;
  statusEl.textContent = "文件模式";
}
loadPreset().then(evaluateStock).catch(() => {
  statusEl.textContent = "服务未连接";
});
loadLlmModels();
loadQuantRankings().catch(() => {});
loadHistory().catch(() => {});
