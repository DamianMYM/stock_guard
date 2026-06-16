const trendContent = document.querySelector("#trendContent");
const trendTitle = document.querySelector("#trendTitle");
const symbol = new URLSearchParams(location.search).get("symbol") || "600879.SH";
document.querySelector("#snapshotDate").value = new Date().toISOString().slice(0, 10);

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function chart(title, dates, values, tone) {
  const clean = values.map((value) => value ?? 0);
  const max = Math.max(...clean.map((value) => Math.abs(value)), 0.01);
  return `
    <section class="trend-card">
      <h2>${title}</h2>
      <div class="trend-bars">
        ${dates.map((date, index) => {
          const value = values[index];
          const height = value === null || value === undefined ? 8 : Math.max(8, Math.abs(value) / max * 140);
          return `
            <div class="trend-col">
              <strong>${pct(value)}</strong>
              <i class="${tone}" style="height:${height}px"></i>
              <span>${date.slice(2)}</span>
            </div>
          `;
        }).join("")}
      </div>
    </section>
  `;
}

async function loadTrends() {
  const response = await fetch(`/api/trends?symbol=${encodeURIComponent(symbol)}`);
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "趋势加载失败");
  trendTitle.textContent = `${symbol} · 历史趋势`;
  const trends = data.trends;
  const valuationDates = (trends.valuation_percentile || []).map((item) => item.date);
  const valuationValues = (trends.valuation_percentile || []).map((item) => item.value);
  trendContent.className = "";
  trendContent.innerHTML = `
    <div class="trend-grid">
      ${chart("营收增速", trends.dates, trends.metrics.revenue_growth, "blue")}
      ${chart("净利增速", trends.dates, trends.metrics.profit_growth, "green")}
      ${chart("ROE", trends.dates, trends.metrics.roe, "amber")}
      ${
        valuationValues.length
          ? chart(`估值分位 · ${trends.valuation_percentile_source || "快照"}`, valuationDates, valuationValues, "blue")
          : `<section class="trend-card placeholder"><h2>估值分位</h2><p>当前股票暂无可展示的估值分位快照。</p></section>`
      }
    </div>
  `;
}

loadTrends().catch((error) => {
  trendContent.innerHTML = `<h2>加载失败</h2><p>${error.message}</p>`;
});

document.querySelector("#snapshotForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await fetch("/api/valuation-snapshot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol,
      value: Number(document.querySelector("#snapshotValue").value),
      date: document.querySelector("#snapshotDate").value,
      source: "手动录入",
    }),
  });
  const data = await response.json();
  if (!data.ok) {
    alert(data.error || "保存失败");
    return;
  }
  await loadTrends();
});
