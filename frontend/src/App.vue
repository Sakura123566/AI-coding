<script setup>
import { computed, nextTick, onMounted, reactive, ref } from "vue";
import { API, ApiError, getToken, setToken } from "./api";

const navItems = [
  { id: "explore", label: "探索", icon: "⌕" },
  { id: "history", label: "历史", icon: "◷" },
  { id: "library", label: "资料库", icon: "▤" },
  { id: "profile", label: "画像", icon: "◫" },
  { id: "graph", label: "图谱", icon: "⌘" },
];
const activeView = ref("explore");
const input = ref("");
const loading = ref(false);
const loadingLabel = ref("");
const error = reactive({ message: "", requestId: "" });
const pendingClarification = ref(null);
const auth = reactive({ open: false, mode: "login", loading: false, error: "" });
const user = ref(null);
const health = ref(null);
const sessions = ref([]);
const currentSessionId = ref("");
const messages = ref([]);
const guestPayload = ref(null);
const drawerOpen = ref(false);
const favorites = ref(loadFavorites());
const memories = ref([]);
const memoryLoading = ref(false);
const profileData = ref(null);
const profileLoading = ref(false);
const searches = ref([]);
const graphKeywords = ref([]);
const graphPairs = ref([]);
const graphLoading = ref(false);
const scrollAnchor = ref(null);

const currentPayload = computed(() => {
  const last = [...messages.value].reverse().find((item) => item.role === "assistant" && item.payload);
  return last?.payload || guestPayload.value;
});
const currentPapers = computed(() => currentPayload.value?.papers || []);
const favoriteIds = computed(() => favorites.value.map((item) => item.id));
const isLoggedIn = computed(() => Boolean(user.value));
const showEvidence = computed(() => activeView.value === "explore");

function loadFavorites() {
  try { return JSON.parse(localStorage.getItem("rn-favorites") || "[]"); } catch { return []; }
}
function saveFavorites() {
  localStorage.setItem("rn-favorites", JSON.stringify(favorites.value));
}
function toggleFavorite(paper) {
  const index = favorites.value.findIndex((item) => item.id === paper.id);
  if (index >= 0) favorites.value.splice(index, 1);
  else favorites.value.unshift(paper);
  saveFavorites();
}
function clearError() { error.message = ""; error.requestId = ""; }
function setError(err) {
  error.message = err instanceof Error ? err.message : "操作失败，请稍后重试。";
  error.requestId = err instanceof ApiError ? err.requestId : "";
}
async function run(task, label = "正在处理…") {
  clearError(); loading.value = true; loadingLabel.value = label;
  try { return await task(); }
  catch (err) { setError(err); return null; }
  finally { loading.value = false; loadingLabel.value = ""; }
}
async function scrollBottom() {
  await nextTick();
  scrollAnchor.value?.scrollIntoView({ behavior: "smooth", block: "end" });
}
function addTypewriterMessage(data) {
  const message = {
    id: `local-${Date.now()}`,
    role: "assistant",
    content: "",
    emotion: data.emotion,
    intent: data.intent,
    payload: data,
    typing: true,
  };
  messages.value.push(message);
  const full = data.reply || "已完成处理。";
  let index = 0;
  const timer = window.setInterval(() => {
    index = Math.min(full.length, index + Math.max(1, Math.ceil(full.length / 90)));
    const target = messages.value.find((item) => item.id === message.id);
    if (target) target.content = full.slice(0, index);
    if (index >= full.length) { window.clearInterval(timer); if (target) target.typing = false; }
    scrollBottom();
  }, 18);
}
async function ensureSession() {
  if (currentSessionId.value) return currentSessionId.value;
  const body = await API.createSession(input.value.trim().slice(0, 30) || "新对话");
  currentSessionId.value = body.session.id;
  sessions.value.unshift(body.session);
  messages.value = [];
  return currentSessionId.value;
}
async function login(payload) {
  auth.loading = true; auth.error = "";
  try {
    setToken("");
    const body = auth.mode === "login" ? await API.login(payload) : await API.register(payload);
    setToken(body.token); user.value = body.user; auth.open = false;
    await loadSessions();
    if (!sessions.value.length) await ensureSession();
  } catch (err) { auth.error = err.message; }
  finally { auth.loading = false; }
}
async function logout() {
  await run(async () => {
    try { await API.logout(); } catch { /* token is discarded locally regardless */ }
    setToken(""); user.value = null; sessions.value = []; messages.value = []; guestPayload.value = null;
    currentSessionId.value = ""; activeView.value = "explore";
  }, "正在退出…");
}
async function loadMe() {
  if (!getToken()) return;
  try { const body = await API.me(); user.value = body.user; await loadSessions(); }
  catch { setToken(""); user.value = null; }
}
async function loadSessions() {
  const body = await API.sessions(); sessions.value = body.sessions || [];
}
async function openSession(id) {
  activeView.value = "explore"; currentSessionId.value = id; guestPayload.value = null;
  const body = await run(() => API.messages(id), "正在恢复会话…");
  if (body) { messages.value = body.messages || []; scrollBottom(); }
}
async function newSession() {
  if (!isLoggedIn.value) { openAuth("login"); return; }
  const body = await run(() => API.createSession("新对话"), "正在新建会话…");
  if (body) { currentSessionId.value = body.session.id; messages.value = []; sessions.value.unshift(body.session); activeView.value = "explore"; input.value = ""; }
}
async function deleteSession(id) {
  await run(() => API.deleteSession(id), "正在删除会话…");
  sessions.value = sessions.value.filter((item) => item.id !== id);
  if (currentSessionId.value === id) { currentSessionId.value = ""; messages.value = []; }
}
function parseQuery(query) {
  let value = query.trim();
  const lower = value.toLowerCase();
  if (lower === "rag") return { ambiguous: true, options: [
    { label: "RAG · 检索增强生成", value: "retrieval-augmented generation" },
    { label: "RAG · 免疫基因", value: "RAG gene" },
  ]};
  if (lower === "gnn") value = "graph neural networks";
  return { value };
}
async function submit() {
  const query = input.value.trim();
  if (!query) { setError(new Error("请输入研究主题。")); return; }
  const parsed = parseQuery(query);
  if (parsed.ambiguous) { pendingClarification.value = parsed.options; return; }
  await executeQuery(parsed.value);
}
async function chooseClarification(option) {
  pendingClarification.value = null; input.value = option.value; await executeQuery(option.value);
}
async function executeQuery(query) {
  clearError(); input.value = query;
  if (!isLoggedIn.value) {
    const body = await run(() => API.research(query, 10), "正在检索并组织报告…");
    if (body) { guestPayload.value = body; messages.value = []; drawerOpen.value = true; scrollBottom(); }
    return;
  }
  try {
    const sessionId = await ensureSession();
    messages.value.push({ id: `user-${Date.now()}`, role: "user", content: query });
    await scrollBottom();
    const body = await run(() => API.chat(sessionId, query), "正在检索并组织报告…");
    if (body) { addTypewriterMessage(body); await loadSessions(); }
  } catch (err) { setError(err); }
}
async function loadMemories() {
  memoryLoading.value = true;
  try { const body = await API.memories(); memories.value = body.memories || []; } catch (err) { setError(err); }
  finally { memoryLoading.value = false; }
}
async function addMemory(payload) {
  await run(() => API.addMemory(payload.content, payload.mem_type), "正在保存记忆…"); await loadMemories();
}
async function deleteMemory(id) { await run(() => API.deleteMemory(id), "正在删除记忆…"); await loadMemories(); }
async function clearMemories() { await run(() => API.clearMemories(), "正在清空记忆…"); await loadMemories(); }
async function loadProfile() {
  profileLoading.value = true;
  try {
    const [profile, searchBody] = await Promise.all([API.profile(), API.searches()]);
    profileData.value = profile; searches.value = searchBody.searches || [];
  } catch (err) { setError(err); }
  finally { profileLoading.value = false; }
}
async function loadGraph() {
  graphLoading.value = true;
  try {
    const body = await API.kgKeywords(); graphKeywords.value = body.keywords || [];
    if (user.value?.id) { const pairs = await API.kgCooccurrence(user.value.id); graphPairs.value = pairs.pairs || []; }
    else graphPairs.value = [];
  } catch (err) { setError(err); }
  finally { graphLoading.value = false; }
}
function openAuth(mode = "login") { auth.mode = mode; auth.error = ""; auth.open = true; }
function changeView(id) {
  activeView.value = id; drawerOpen.value = false;
  if (id === "profile") { if (!isLoggedIn.value) openAuth("login"); else Promise.all([loadProfile(), loadMemories()]); }
  if (id === "graph") loadGraph();
}
function selectPaper(paper) { if (paper) { drawerOpen.value = true; document.querySelector(".evidence-panel")?.scrollIntoView({ behavior: "smooth" }); } }
function healthLabel() {
  if (!health.value) return "后端未连接";
  return health.value.environment === "production" ? "公网服务正常" : "本机服务正常";
}
onMounted(async () => {
  try { health.value = await API.health(); } catch { /* health badge is informational */ }
  await loadMe();
  if (!sessions.value.length && isLoggedIn.value) await ensureSession();
});
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" aria-label="主导航">
      <div class="brand-block">
        <div class="brand-mark">RN</div>
        <div><strong>Research Navigator</strong><span>科研对话与导航</span></div>
      </div>
      <button class="new-chat-button" type="button" @click="newSession">＋ 新建研究</button>
      <nav class="main-nav">
        <button v-for="item in navItems" :key="item.id" type="button" :class="{ active: activeView === item.id }"
          :aria-current="activeView === item.id ? 'page' : undefined" @click="changeView(item.id)">
          <span aria-hidden="true">{{ item.icon }}</span>{{ item.label }}
        </button>
      </nav>
      <div class="sidebar-foot">
        <div class="service-indicator" :class="{ online: health }"><i></i>{{ healthLabel() }}</div>
        <button v-if="isLoggedIn" class="account-button" type="button" @click="logout">
          <span>{{ user?.display_name || user?.username }}</span><small>退出</small>
        </button>
        <button v-else class="primary-button wide" type="button" @click="openAuth('login')">登录 / 注册</button>
      </div>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <div><span class="eyebrow">Research workspace</span><h1>{{ navItems.find((item) => item.id === activeView)?.label }}</h1></div>
        <div class="top-actions">
          <button class="secondary-button mobile-only" type="button" @click="drawerOpen = !drawerOpen">证据</button>
          <button v-if="activeView === 'explore' && !isLoggedIn" class="secondary-button" type="button" @click="openAuth('login')">登录以保存会话</button>
        </div>
      </header>

      <div v-if="error.message" class="error-banner" role="alert">
        <span>{{ error.message }}</span><small v-if="error.requestId">请求 ID：{{ error.requestId }}</small>
        <button class="icon-button" type="button" aria-label="关闭错误提示" @click="clearError">×</button>
      </div>

      <section v-if="activeView === 'explore'" class="explore-layout">
        <div class="conversation-column">
          <div v-if="!messages.length && !guestPayload" class="welcome-card">
            <span class="eyebrow">从问题到研究地图</span>
            <h2>告诉 Navi 你想了解什么</h2>
            <p>它会检索真实论文，组织方向概览、主题簇、阅读路线和值得继续查证的问题。</p>
            <div class="example-row">
              <button v-for="example in ['Graph Neural Networks', 'RAG', '多模态学习']" :key="example" type="button" @click="input = example">{{ example }}</button>
            </div>
          </div>
          <div class="message-list">
            <article v-for="message in messages" :key="message.id" class="message" :class="message.role">
              <div class="message-role">{{ message.role === "user" ? "你" : "Navi" }}</div>
              <div class="message-body">
                <p>{{ message.content }}</p>
                <div v-if="message.payload?.degraded" class="degrade-badge">能力降级：{{ message.payload.degrade_reason || "部分服务不可用" }}</div>
                <div v-if="message.payload?.papers?.length" class="message-paper-row">
                  <button v-for="paper in message.payload.papers.slice(0, 6)" :key="paper.id" type="button" @click="selectPaper(paper)">
                    {{ paper.id }} · {{ paper.title }}
                  </button>
                </div>
              </div>
            </article>
          </div>
          <div v-if="loading" class="thinking-indicator" aria-live="polite"><i></i>{{ loadingLabel }}</div>
          <div ref="scrollAnchor"></div>
          <form class="composer" @submit.prevent="submit">
            <label class="sr-only" for="research-input">研究主题或追问</label>
            <textarea id="research-input" v-model="input" rows="3" :disabled="loading"
              placeholder="输入研究主题，或继续追问当前方向…" @keydown.ctrl.enter.prevent="submit" @keydown.meta.enter.prevent="submit"></textarea>
            <div class="composer-foot">
              <span>Ctrl / ⌘ + Enter 发送 · 论文结论请核对原文</span>
              <button class="primary-button" type="submit" :disabled="loading">发送</button>
            </div>
          </form>
        </div>
        <aside class="evidence-panel" :class="{ open: drawerOpen }" aria-label="论文证据与导航报告">
          <div class="panel-heading"><div><span class="eyebrow">Current evidence</span><h2>证据与导航</h2></div><button class="icon-button mobile-only" type="button" aria-label="关闭证据面板" @click="drawerOpen = false">×</button></div>
          <div v-if="!currentPayload" class="empty-panel"><h3>等待研究任务</h3><p>检索完成后，这里会显示论文来源和结构化报告。</p></div>
          <template v-else>
            <div v-if="currentPayload.resolved_keyword || currentPayload.keyword" class="resolved-query"><span>实际检索词</span><strong>{{ currentPayload.resolved_keyword || currentPayload.keyword }}</strong></div>
            <div v-if="currentPayload.warnings?.length" class="notice-list"><p v-for="warning in currentPayload.warnings" :key="warning">{{ warning }}</p></div>
            <div v-if="currentPayload.report_error" class="status-card warning-card"><strong>报告降级</strong><p>{{ currentPayload.report_error }}</p></div>
            <div v-if="currentPayload.report" class="report-view">
              <section class="report-section"><span class="eyebrow">方向概览</span><p>{{ currentPayload.report.overview }}</p></section>
              <section v-if="currentPayload.report.themes?.length" class="report-section"><span class="eyebrow">核心主题</span>
                <article v-for="theme in currentPayload.report.themes" :key="theme.name" class="theme-card"><h4>{{ theme.name }}</h4><p>{{ theme.description }}</p>
                  <div class="citation-row"><button v-for="id in theme.paper_ids" :key="id" type="button" @click="selectPaper(currentPapers.find((p) => p.id === id))">{{ id }}</button></div>
                </article>
              </section>
              <section v-if="currentPayload.report.research_trends?.length" class="report-section"><span class="eyebrow">研究趋势</span><div class="tag-cloud"><span v-for="trend in currentPayload.report.research_trends" :key="trend">{{ trend }}</span></div></section>
              <section v-if="currentPayload.report.reading_path?.length" class="report-section"><span class="eyebrow">推荐阅读路线</span><ol class="reading-path"><li v-for="step in currentPayload.report.reading_path" :key="step.step"><p>{{ step.reason }}</p><div class="citation-row"><button v-for="id in step.paper_ids" :key="id" type="button" @click="selectPaper(currentPapers.find((p) => p.id === id))">{{ id }}</button></div></li></ol></section>
              <section v-if="currentPayload.report.exploration_questions?.length" class="report-section"><span class="eyebrow">值得追问</span><ul class="question-list"><li v-for="question in currentPayload.report.exploration_questions" :key="question">{{ question }}</li></ul></section>
              <section v-if="currentPayload.report.limitations" class="report-section limitation"><span class="eyebrow">检索与归纳局限</span><p>{{ currentPayload.report.limitations }}</p></section>
            </div>
            <h3 class="paper-list-title">论文证据 · {{ currentPapers.length }} 篇</h3>
            <article v-for="paper in currentPapers" :key="paper.id" class="paper-card">
              <div class="paper-heading"><span class="paper-id">{{ paper.id }}</span><button class="icon-button" type="button" :aria-label="favoriteIds.includes(paper.id) ? '取消收藏' : '收藏'" @click="toggleFavorite(paper)">{{ favoriteIds.includes(paper.id) ? "★" : "☆" }}</button></div>
              <h3><a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener noreferrer">{{ paper.title_zh || paper.title }}</a><span v-else>{{ paper.title_zh || paper.title }}</span></h3>
              <small v-if="paper.title_zh" class="paper-original-title">{{ paper.title }}</small>
              <p class="paper-meta">{{ paper.year || "年份未知" }} · {{ paper.source || "来源未知" }}</p>
              <p class="paper-abstract">{{ paper.abstract_summary_zh || paper.abstract_zh || (paper.translation_status === "unavailable" ? "暂无中文摘要，可在原文中查看详细信息。" : "暂无摘要") }}</p>
              <details v-if="paper.abstract_zh || paper.abstract" class="paper-originals">
                <summary>查看完整摘要和英文原文</summary>
                <p v-if="paper.abstract_zh"><strong>中文翻译：</strong>{{ paper.abstract_zh }}</p>
                <p v-if="paper.abstract" lang="en"><strong>Original：</strong>{{ paper.abstract }}</p>
              </details>
            </article>
          </template>
        </aside>
      </section>

      <section v-else-if="activeView === 'history'" class="page-view">
        <div class="page-heading"><div><span class="eyebrow">Persistent sessions</span><h2>会话历史</h2></div><button class="primary-button" type="button" @click="newSession">新建会话</button></div>
        <div v-if="!sessions.length" class="empty-panel"><h3>暂无会话</h3><p>登录后，每次检索和对话都会保存到这里。</p></div>
        <div v-else class="session-list"><article v-for="session in sessions" :key="session.id"><button type="button" @click="openSession(session.id)"><strong>{{ session.title || "新对话" }}</strong><span>{{ session.message_count }} 条消息 · {{ session.updated_at }}</span></button><button class="icon-button" type="button" aria-label="删除会话" @click="deleteSession(session.id)">×</button></article></div>
      </section>

      <section v-else-if="activeView === 'library'" class="page-view">
        <div class="page-heading"><div><span class="eyebrow">Local favorites</span><h2>我的资料库</h2></div><span class="count-badge">{{ favorites.length }} 篇本机收藏</span></div>
        <div v-if="!favorites.length" class="empty-panel"><h3>还没有收藏</h3><p>在论文卡片上点击星标后，会保存在当前浏览器。</p></div>
        <div class="library-grid"><article v-for="paper in favorites" :key="paper.id" class="paper-card"><div class="paper-heading"><span class="paper-id">{{ paper.id }}</span><button class="icon-button" type="button" aria-label="取消收藏" @click="toggleFavorite(paper)">★</button></div><h3><a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener noreferrer">{{ paper.title_zh || paper.title }}</a><span v-else>{{ paper.title_zh || paper.title }}</span></h3><small v-if="paper.title_zh" class="paper-original-title">{{ paper.title }}</small><p class="paper-meta">{{ paper.year || "年份未知" }} · {{ paper.source || "来源未知" }}</p><p class="paper-abstract">{{ paper.abstract_summary_zh || paper.abstract_zh || "暂无中文摘要" }}</p></article></div>
      </section>

      <section v-else-if="activeView === 'profile'" class="page-view">
        <div class="page-heading"><div><span class="eyebrow">Behavior-based profile</span><h2>研究画像与记忆</h2></div></div>
        <div v-if="profileLoading" class="status-card">正在计算画像…</div>
        <div v-else-if="!profileData?.has_enough_data" class="empty-panel"><h3>数据不足</h3><p>至少完成 5 次真实检索或对话后才展示画像，不用空数据制造假图表。</p><span>当前样本：{{ profileData?.sample_size || 0 }}</span></div>
        <template v-else>
          <div class="metric-grid"><article><strong>{{ profileData.profile?.activity?.total_searches || 0 }}</strong><span>累计检索</span></article><article><strong>{{ profileData.profile?.activity?.total_messages || 0 }}</strong><span>对话消息</span></article><article><strong>{{ profileData.profile?.activity?.active_days || 0 }}</strong><span>活跃天数</span></article></div>
          <div class="two-column"><article class="panel-card"><h3>领域分布</h3><div v-for="item in profileData.profile?.domains || []" :key="item.name" class="bar-row"><span>{{ item.name }}</span><div><i :style="{ width: `${Math.round((item.weight || 0) * 100)}%` }"></i></div><b>{{ Math.round((item.weight || 0) * 100) }}%</b></div></article><article class="panel-card"><h3>兴趣趋势</h3><div v-for="item in profileData.profile?.interests || []" :key="item.tag" class="interest-row"><span>{{ item.tag }}</span><b>{{ item.trend === "up" ? "↑" : item.trend === "down" ? "↓" : "→" }}</b></div></article></div>
        </template>
        <article class="panel-card memory-panel"><div class="panel-title-row"><h3>长期记忆</h3><button class="danger-button" type="button" @click="clearMemories">清空</button></div><form class="memory-form" @submit.prevent="addMemory({ content: $event.target.elements.memory.value, mem_type: $event.target.elements.type.value })"><select name="type"><option value="interest">研究兴趣</option><option value="preference">回答偏好</option><option value="goal">研究目标</option><option value="constraint">约束条件</option><option value="profile_fact">身份事实</option></select><input name="memory" maxlength="200" placeholder="例如：我主要研究图神经网络在推荐系统中的应用" /><button class="primary-button" type="submit">记住</button></form><div v-if="memoryLoading" class="status-card">正在读取记忆…</div><div v-else-if="!memories.length" class="muted">还没有长期记忆。</div><div v-else class="memory-list"><article v-for="item in memories" :key="item.id"><span class="memory-type">{{ item.mem_type }}</span><p>{{ item.content }}</p><small>来源：{{ item.source_id || "未知" }}</small><button class="link-button danger" type="button" @click="deleteMemory(item.id)">删除</button></article></div></article>
      </section>

      <section v-else-if="activeView === 'graph'" class="page-view">
        <div class="panel-card graph-view"><div class="page-heading"><div><span class="eyebrow">Real event graph</span><h2>研究关键词图谱</h2></div><span class="count-badge">{{ graphKeywords.length }} 个节点 · {{ graphPairs.length }} 条边</span></div><div v-if="graphLoading" class="status-card">正在读取图谱…</div><div v-else-if="!graphKeywords.length" class="empty-panel"><h3>图谱数据不足</h3><p>完成更多真实检索与对话后，关键词和共现关系会自动出现。</p></div><svg v-else viewBox="0 0 800 560" role="img" aria-label="研究关键词共现图谱"><line v-for="pair in graphPairs.slice(0, 80)" :key="`${pair.source}-${pair.target}`" :x1="40 + (graphKeywords.findIndex((k) => k.term === pair.source) % 8) * 105" :y1="70 + Math.floor(graphKeywords.findIndex((k) => k.term === pair.source) / 8) * 100" :x2="40 + (graphKeywords.findIndex((k) => k.term === pair.target) % 8) * 105" :y2="70 + Math.floor(graphKeywords.findIndex((k) => k.term === pair.target) / 8) * 100" /><g v-for="(item, index) in graphKeywords.slice(0, 40)" :key="item.term"><circle :cx="40 + (index % 8) * 105" :cy="70 + Math.floor(index / 8) * 100" :r="18 + Math.round((item.weight || 0) * 12)" /><text :x="40 + (index % 8) * 105" :y="74 + Math.floor(index / 8) * 100">{{ (item.display || item.term).slice(0, 7) }}</text></g></svg></div>
      </section>
    </main>

    <div v-if="pendingClarification" class="dialog-backdrop">
      <section class="auth-dialog" role="dialog" aria-modal="true" aria-label="确认 RAG 含义"><span class="eyebrow">检索词存在歧义</span><h2>你说的 RAG 是指哪个方向？</h2><p class="muted">选择后会把完整英文检索词发送给论文源。<button class="link-button" type="button" @click="pendingClarification = null">取消</button></p><div class="clarify-options"><button v-for="option in pendingClarification" :key="option.value" class="primary-button" type="button" @click="chooseClarification(option)">{{ option.label }}</button></div></section>
    </div>

    <div v-if="auth.open" class="dialog-backdrop" @click.self="auth.open = false">
      <section class="auth-dialog" role="dialog" aria-modal="true" :aria-label="auth.mode === 'login' ? '登录' : '注册'"><button class="dialog-close icon-button" type="button" aria-label="关闭" @click="auth.open = false">×</button><span class="eyebrow">Research Navigator</span><h2>{{ auth.mode === "login" ? "登录后继续研究" : "创建科研空间" }}</h2><form class="auth-form" @submit.prevent="login({ username: $event.target.elements.username.value, password: $event.target.elements.password.value, display_name: $event.target.elements.display_name?.value || '' })"><label>用户名<input name="username" minlength="2" maxlength="32" autocomplete="username" required /></label><label v-if="auth.mode === 'register'">显示名称<input name="display_name" maxlength="32" autocomplete="name" /></label><label>密码<input name="password" type="password" minlength="6" maxlength="128" :autocomplete="auth.mode === 'login' ? 'current-password' : 'new-password'" required /></label><p v-if="auth.error" class="form-error" role="alert">{{ auth.error }}</p><button class="primary-button wide" type="submit" :disabled="auth.loading">{{ auth.loading ? "正在处理…" : auth.mode === "login" ? "登录" : "注册并进入" }}</button></form><button class="link-button" type="button" @click="auth.mode = auth.mode === 'login' ? 'register' : 'login'">{{ auth.mode === "login" ? "没有账号？注册" : "已有账号？登录" }}</button></section>
    </div>
  </div>
</template>