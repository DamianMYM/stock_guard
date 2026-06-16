const form = document.querySelector("#stockForm");
const result = document.querySelector("#result");
const statusEl = document.querySelector("#status");
const serverBanner = document.querySelector("#serverBanner");
const llmStatus = document.querySelector("#llmStatus");
const llmModel = document.querySelector("#llmModel");
const chatLog = document.querySelector("#chatLog");
const chatInput = document.querySelector("#chatInput");
const chatSend = document.querySelector("#chatSend");
const mascotAsk = document.querySelector("#mascotAsk");
const API_BASE = location.protocol === "file:" ? "http://127.0.0.1:8787" : "";
let lastEvaluation = null;

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

function actionClass(action) {
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
        <span>价值纪律</span>
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
        <span>长线精选</span>
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
        <span>样本更新：${row.research_updated_at || "待补充"}</span>
      </div>
      <div class="research-grid">
        <div class="research-card neutral"><span>最新报告期 EPS</span><strong>${fmt(row.latest_period_eps, 3)}</strong></div>
        <div class="research-card ${metricTone(row.revenue_growth_level)}"><span>营收同比</span><strong>${pct(row.revenue_growth)}</strong></div>
        <div class="research-card ${metricTone(row.profit_growth_level)}"><span>净利同比</span><strong>${pct(row.profit_growth)}</strong></div>
        <div class="research-card ${metricTone(row.roe_level)}"><span>ROE</span><strong>${pct(row.roe)}</strong></div>
        <div class="research-card ${metricTone(row.operating_cash_flow_growth_level)}"><span>经营现金流同比</span><strong>${pct(row.operating_cash_flow_growth)}</strong></div>
        <div class="research-card neutral"><span>经营现金流金额</span><strong>${row.operating_cash_flow_value === null || row.operating_cash_flow_value === undefined ? "-" : `${fmt(row.operating_cash_flow_value, 2)} 亿`}</strong></div>
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
        <p><span>目标PE估值</span><strong>${fmt(row.target_pe_value)}</strong></p>
        <p><span>Graham增长公式</span><strong>${fmt(row.graham_growth_value)}</strong></p>
        <p><span>Graham Number</span><strong>${fmt(row.graham_number)}</strong></p>
      </div>
      <div class="box">
        <h2>纪律解释</h2>
        <p><span>最低安全边际门槛</span><strong>${pct(row.required_margin_of_safety)}</strong></p>
        <p><span>通过标准</span><strong>实际安全边际 ≥ 门槛</strong></p>
        <p><span>买入线含义</span><strong>估值反推的每股阈值</strong></p>
        <p><span>当前判断</span><strong>${row.action}</strong></p>
      </div>
      <div class="box notice">
        <h2>数据口径</h2>
        <p><span>EPS 来源</span><strong>${row.eps_source || "未标注"}</strong></p>
        <p><span>财务参数</span><strong>${row.research_source || "本地预设 / 手动输入"}</strong></p>
        <p><span>预期压力</span><strong>${fmt(row.growth_pressure, 1)} × 目标PE</strong></p>
        <p><span>模型适配度</span><strong>${row.model_fit || "-"}</strong></p>
        <p><span>解释</span><strong>${row.model_note || "-"}</strong></p>
      </div>
    </div>
  `;
}

function appendChat(role, text, meta = "") {
  const item = document.createElement("div");
  item.className = `chat-message ${role}`;
  const title = document.createElement("b");
  title.textContent = role === "user" ? "你" : "鼓手助手";
  const body = document.createElement("p");
  body.textContent = text;
  if (meta) {
    const small = document.createElement("small");
    small.textContent = meta;
    item.append(title, body, small);
  } else {
    item.append(title, body);
  }
  chatLog.appendChild(item);
  chatLog.scrollTop = chatLog.scrollHeight;
  return item;
}

function updateChatMessage(item, text, meta = "") {
  const body = item.querySelector("p");
  const small = item.querySelector("small") || document.createElement("small");
  body.textContent = text;
  if (meta) {
    small.textContent = meta;
    if (!small.parentElement) item.appendChild(small);
  }
  chatLog.scrollTop = chatLog.scrollHeight;
}

function basisMeta(data) {
  const basis = data.basis?.length ? `依据：${data.basis.join(" / ")}` : "";
  const elapsed = data.elapsed_seconds ? `耗时：${data.elapsed_seconds}s` : "";
  return [basis, elapsed].filter(Boolean).join(" ｜ ");
}

function defaultModel(models) {
  const names = models.map((model) => model.name || model.model).filter(Boolean);
  return (
    names.find((name) => name === "deepseek-r1:8b") ||
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
  appendChat("user", message);
  chatInput.value = "";
  chatSend.disabled = true;
  chatSend.textContent = "模型思考中";
  const pending = appendChat(
    "assistant",
    "读取当前页面数据 -> 发送给本地模型 -> 等待模型返回。",
    "显示的是处理进度和依据摘要，不展示原始隐藏推理链。"
  );
  try {
    const data = await requestJson("/api/llm/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: llmModel.value,
        message,
        context: {
          form: readForm(),
          evaluation: lastEvaluation,
        },
      }),
    });
    if (!data.ok) throw new Error(data.error || "本地模型调用失败");
    updateChatMessage(pending, data.answer, basisMeta(data));
  } catch (error) {
    updateChatMessage(pending, error.message || "本地模型调用失败");
  } finally {
    chatSend.disabled = false;
    chatSend.textContent = "发送给本地模型";
  }
}

function askFromMascot() {
  const label = currentStockLabel();
  chatInput.value = `结合当前页面抓取的数据，判断${label}现在是否适合继续买入或加仓，并给出仓位、观察价位和止损纪律。`;
  chatInput.focus();
  chatInput.scrollIntoView({ behavior: "smooth", block: "center" });
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
    statusEl.textContent = "计算完成";
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
  statusEl.textContent = `研究指标已更新至 ${data.research.research_updated_at || "最新可得"}`;
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
document.querySelector("#newStockButton").addEventListener("click", resetForNewStock);
mascotAsk?.addEventListener("click", askFromMascot);
chatSend?.addEventListener("click", sendChat);
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
form.addEventListener("submit", evaluateStock);

hydrateFromQuery();
if (location.protocol === "file:") {
  serverBanner.hidden = false;
  statusEl.textContent = "文件模式";
}
loadPreset().then(evaluateStock).catch(() => {
  statusEl.textContent = "服务未连接";
});
loadLlmModels();
