const state = { documents: [], chunks: [], facets: {}, stats: {}, selectedDocId: null };
const dataBasePath = window.location.pathname.includes("/site/") ? "../data" : "./data";

async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Failed to load ${path}`);
  return response.json();
}

function byId(id) { return document.getElementById(id); }

function populateSelect(selectId, values, allLabel) {
  const select = byId(selectId);
  const options = [`<option value="">${allLabel}</option>`].concat((values || []).map(value => `<option value="${value}">${value}</option>`));
  select.innerHTML = options.join("");
}

function renderStats() {
  const items = [
    { label: "文档总数", value: state.stats.document_count || 0 },
    { label: "段落索引", value: state.stats.chunk_count || 0 },
    { label: "覆盖地区", value: state.stats.region_count || 0 },
    { label: "最近更新", value: (state.stats.updated_at || "").slice(0, 10) || "-" }
  ];
  byId("stats").innerHTML = items.map(item => `<div class="stat-card"><span class="stat-label">${item.label}</span><span class="stat-value">${item.value}</span></div>`).join("");
}

function getFilters() {
  return {
    search: byId("searchInput").value.trim().toLowerCase(),
    region: byId("regionFilter").value,
    year: byId("yearFilter").value,
    type: byId("typeFilter").value,
    level: byId("levelFilter").value,
    tag: byId("tagFilter").value
  };
}

function getDocChunks(docId) {
  return state.chunks.filter(chunk => chunk.doc_id === docId);
}

function matchesSearch(doc, filters) {
  if (!filters.search) return true;
  const textPool = [doc.title, doc.summary, ...(doc.keywords || []), ...(doc.tags || []), ...getDocChunks(doc.id).map(chunk => chunk.text)].join(" ").toLowerCase();
  return textPool.includes(filters.search);
}

function filterDocuments() {
  const filters = getFilters();
  return state.documents.filter(doc => {
    if (filters.region && doc.region !== filters.region) return false;
    if (filters.year && String(doc.year) !== String(filters.year)) return false;
    if (filters.type && doc.plan_type !== filters.type) return false;
    if (filters.level && doc.plan_level !== filters.level) return false;
    if (filters.tag && !(doc.tags || []).includes(filters.tag)) return false;
    return matchesSearch(doc, filters);
  });
}

function renderDocumentList() {
  const results = filterDocuments();
  byId("resultCount").textContent = `当前命中 ${results.length} 份文档`;
  if (!results.length) {
    byId("resultList").innerHTML = `<div class="empty">没有符合条件的文档。</div>`;
    byId("detailView").innerHTML = `<div class="empty">请调整筛选条件后重试。</div>`;
    return;
  }
  if (!state.selectedDocId || !results.some(doc => doc.id === state.selectedDocId)) state.selectedDocId = results[0].id;
  byId("resultList").innerHTML = results.map(doc => `
    <article class="doc-card ${doc.id === state.selectedDocId ? "active" : ""}" data-doc-id="${doc.id}">
      <h3>${doc.title}</h3>
      <div class="meta-line">${doc.region || "地区待补充"} · ${doc.year || "年份待补充"} · ${doc.plan_type || "类型待补充"} · ${doc.plan_level || "层级待补充"}</div>
      <p>${doc.summary || "暂无摘要"}</p>
      <div class="tags">${(doc.tags || []).slice(0, 6).map(tag => `<span class="tag">${tag}</span>`).join("")}</div>
    </article>
  `).join("");
  byId("resultList").querySelectorAll(".doc-card").forEach(card => {
    card.addEventListener("click", () => {
      state.selectedDocId = card.dataset.docId;
      renderDocumentList();
      renderDetail();
    });
  });
  renderDetail();
}

function renderDetail() {
  const doc = state.documents.find(item => item.id === state.selectedDocId);
  if (!doc) {
    byId("detailView").innerHTML = `<div class="empty">没有可展示的文档详情。</div>`;
    return;
  }
  const docChunks = getDocChunks(doc.id).slice(0, 6);
  byId("detailView").innerHTML = `
    <div class="detail-section">
      <h3>${doc.title}</h3>
      <div class="detail-meta">
        地区：${doc.region || "-"}<br>
        年份：${doc.year || "-"}<br>
        规划类型：${doc.plan_type || "-"}<br>
        规划层级：${doc.plan_level || "-"}<br>
        页数：${doc.page_count || "-"}<br>
        源文件：${doc.source_filename || "-"}
      </div>
    </div>
    <div class="detail-section"><strong>摘要</strong><div class="chunk">${doc.summary || "暂无摘要"}</div></div>
    <div class="detail-section"><strong>标签</strong><div class="tags">${(doc.tags || []).map(tag => `<span class="tag">${tag}</span>`).join("") || '<span class="empty">暂无标签</span>'}</div></div>
    <div class="detail-section">
      <strong>章节片段</strong>
      ${docChunks.length ? docChunks.map(chunk => `<div class="chunk"><div class="detail-meta">${chunk.heading} · 第 ${chunk.page_start}-${chunk.page_end} 页</div><div>${chunk.text}</div></div>`).join("") : '<div class="empty">暂无章节片段</div>'}
    </div>
  `;
}

function bindFilters() {
  ["searchInput", "regionFilter", "yearFilter", "typeFilter", "levelFilter", "tagFilter"].forEach(id => {
    byId(id).addEventListener("input", renderDocumentList);
    byId(id).addEventListener("change", renderDocumentList);
  });
}

async function init() {
  try {
    const [documents, chunks, facets, stats] = await Promise.all([
      loadJson(`${dataBasePath}/documents.json`),
      loadJson(`${dataBasePath}/chunks.json`),
      loadJson(`${dataBasePath}/facets.json`),
      loadJson(`${dataBasePath}/stats.json`)
    ]);
    state.documents = documents;
    state.chunks = chunks;
    state.facets = facets;
    state.stats = stats;
    populateSelect("regionFilter", facets.region, "全部地区");
    populateSelect("yearFilter", facets.year, "全部年份");
    populateSelect("typeFilter", facets.plan_type, "全部规划类型");
    populateSelect("levelFilter", facets.plan_level, "全部规划层级");
    populateSelect("tagFilter", facets.tags, "全部标签");
    renderStats();
    bindFilters();
    renderDocumentList();
  } catch (error) {
    byId("resultList").innerHTML = `<div class="empty">数据加载失败：${error.message}</div>`;
  }
}

init();
