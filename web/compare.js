const compareContent = document.querySelector("#compareContent");

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

async function loadStock(symbol) {
  const response = await fetch("/api/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, live: true, required_margin_of_safety: 0.3 }),
  });
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "对比失败");
  return data.result;
}

function card(row) {
  return `
    <section class="compare-card">
      <h2>${row.name || row.symbol}</h2>
      <p><span>当前价</span><strong>${fmt(row.price)}</strong></p>
      <p><span>PE(TTM)</span><strong>${fmt(row.pe_ttm)}</strong></p>
      <p><span>PB</span><strong>${fmt(row.pb)}</strong></p>
      <p><span>安全边际</span><strong>${pct(row.margin_of_safety)}</strong></p>
      <p><span>营收同比</span><strong>${pct(row.revenue_growth)}</strong></p>
      <p><span>净利同比</span><strong>${pct(row.profit_growth)}</strong></p>
      <p><span>ROE</span><strong>${pct(row.roe)}</strong></p>
      <p><span>判断</span><strong>${row.research_view?.text || "-"}</strong></p>
    </section>
  `;
}

async function compare() {
  const [left, right] = await Promise.all([
    loadStock(document.querySelector("#symbolA").value.trim()),
    loadStock(document.querySelector("#symbolB").value.trim()),
  ]);
  compareContent.className = "";
  compareContent.innerHTML = `<div class="compare-grid">${card(left)}${card(right)}</div>`;
}

document.querySelector("#compareButton").addEventListener("click", () => {
  compare().catch((error) => {
    compareContent.innerHTML = `<h2>对比失败</h2><p>${error.message}</p>`;
  });
});
compare().catch(() => {});
