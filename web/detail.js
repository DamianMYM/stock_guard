const detailContent = document.querySelector("#detailContent");
const detailTitle = document.querySelector("#detailTitle");
const symbol = new URLSearchParams(location.search).get("symbol") || "600879.SH";
document.querySelector("#trendLink").href = `trends.html?symbol=${encodeURIComponent(symbol)}`;

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

async function loadDetail() {
  const response = await fetch("/api/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, live: true, required_margin_of_safety: 0.3 }),
  });
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "详情加载失败");
  const row = data.result;
  detailTitle.textContent = `${row.name || row.symbol} · 研究详情`;
  detailContent.className = "";
  detailContent.innerHTML = `
    <div class="detail-grid">
      <section class="box">
        <h2>核心估值</h2>
        <p><span>当前价格</span><strong>${fmt(row.price)}</strong></p>
        <p><span>保守价值</span><strong>${fmt(row.conservative_value)}</strong></p>
        <p><span>买入线</span><strong>${fmt(row.buy_below)}</strong></p>
        <p><span>安全边际</span><strong>${pct(row.margin_of_safety)}</strong></p>
      </section>
      <section class="box">
        <h2>研究摘要</h2>
        <p><span>研究更新</span><strong>${row.research_updated_at || "-"}</strong></p>
        <p><span>营收同比</span><strong>${pct(row.revenue_growth)}</strong></p>
        <p><span>净利同比</span><strong>${pct(row.profit_growth)}</strong></p>
        <p><span>ROE</span><strong>${pct(row.roe)}</strong></p>
        <p><span>估值分位</span><strong>${pct(row.valuation_percentile)}</strong></p>
      </section>
      <section class="box">
        <h2>判断</h2>
        <p><span>价值纪律</span><strong>${row.value_view?.text || "-"}</strong></p>
        <p><span>成长观察</span><strong>${row.growth_view?.text || "-"}</strong></p>
        <p><span>仓位风险</span><strong>${row.position_view?.text || "-"}</strong></p>
      </section>
    </div>
  `;
}

loadDetail().catch((error) => {
  detailContent.innerHTML = `<h2>加载失败</h2><p>${error.message}</p>`;
});
