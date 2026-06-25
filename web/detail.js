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

function renderIntelItems(items) {
  if (!items?.length) return `<p>最近没有抓到可分析的公告。</p>`;
  return `
    <div class="intel-list">
      ${items.map((item) => `
        <article class="intel-item">
          <div class="intel-head">
            <strong>${item.title}</strong>
            <span>${item.date || "-"}</span>
          </div>
          <div class="intel-tags">
            ${(item.tags || []).map((tag) => `<span class="intel-tag">${tag}</span>`).join("") || '<span class="intel-tag neutral">普通公告</span>'}
          </div>
          <p>${item.summary}</p>
        </article>
      `).join("")}
    </div>
  `;
}

async function loadDetail() {
  const [detailResp, intelResp, rankingResp] = await Promise.all([
    fetch("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, live: true, required_margin_of_safety: 0.3 }),
    }),
    fetch(`/api/intel?symbol=${encodeURIComponent(symbol)}`),
    fetch("/api/quant/rankings"),
  ]);

  const detailData = await detailResp.json();
  const intelData = await intelResp.json();
  const rankingData = await rankingResp.json();
  if (!detailData.ok) throw new Error(detailData.error || "详情加载失败");

  const row = intelData.ok ? intelData.snapshot : detailData.result;
  const intel = intelData.ok ? intelData.intel : { items: [], overall: "-", top_tags: [] };
  const ranking = (rankingData.rankings || []).find((item) => item.symbol === row.symbol);

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
        <h2>量化评分</h2>
        <p><span>量化分数</span><strong>${fmt(ranking?.quant_score ?? row.quant_score, 1)}</strong></p>
        <p><span>当前标签</span><strong>${ranking?.quant_label || row.quant_label || "-"}</strong></p>
        <p><span>事件侧判断</span><strong>${row.intel_overall || intel.overall || "-"}</strong></p>
        <p><span>关键因子</span><strong>${(ranking?.factors || row.factors || []).slice(0, 3).join(" / ") || "-"}</strong></p>
      </section>
      <section class="box">
        <h2>核心模型</h2>
        <p><span>模型标题</span><strong>${row.core_model?.headline || "-"}</strong></p>
        <p><span>产业位置</span><strong>${row.core_model?.industry_role || "-"}</strong></p>
        <p><span>当前判断</span><strong>${row.core_model?.decision_anchor || "-"}</strong></p>
        <p><span>事件解释</span><strong>${row.core_model?.event_view || "-"}</strong></p>
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
        <p><span>估值纪律</span><strong>${row.value_view?.text || "-"}</strong></p>
        <p><span>成长观察</span><strong>${row.growth_view?.text || "-"}</strong></p>
        <p><span>仓位风险</span><strong>${row.position_view?.text || "-"}</strong></p>
      </section>
      <section class="box wide-box">
        <h2>公告情报</h2>
        <p class="detail-summary">${intel.overall || "-"}</p>
        <div class="intel-tags">
          ${(intel.top_tags || []).map((tag) => `<span class="intel-tag">${tag}</span>`).join("") || '<span class="intel-tag neutral">暂无重点标签</span>'}
        </div>
        ${renderIntelItems(intel.items)}
      </section>
      <section class="box wide-box">
        <h2>观察池排序参考</h2>
        ${
          ranking
            ? `
              <p><span>排序标签</span><strong>${ranking.quant_label}</strong></p>
              <p><span>分数拆解</span><strong>
                价值 ${fmt(ranking.score_breakdown?.value_score, 1)} /
                质量 ${fmt(ranking.score_breakdown?.quality_score, 1)} /
                事件 ${fmt(ranking.score_breakdown?.event_score, 1)} /
                风险扣分 ${fmt(ranking.score_breakdown?.risk_penalty, 1)}
              </strong></p>
              <p><span>补充说明</span><strong>${ranking.intel_overall || "-"}</strong></p>
            `
            : "<p>这只股票当前不在观察池里，所以没有对应的排序记录。</p>"
        }
      </section>
    </div>
  `;
}

loadDetail().catch((error) => {
  detailContent.innerHTML = `<h2>加载失败</h2><p>${error.message}</p>`;
});
