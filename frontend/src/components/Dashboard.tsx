import React, { useState } from 'react';
import {
  Search,
  Filter,
  Plus,
  Calendar,
  FileText,
  Bookmark,
  Share2,
  FileCode2,
  List,
  AlertCircle,
  Clock,
  ExternalLink,
  RefreshCw,
  TrendingUp,
  FileDown,
  X,
  History,
  CheckCircle2,
  Code,
  Image as ImageIcon,
  Bot,
  Layers,
  ArrowRight
} from 'lucide-react';
import { Article, ArticleStatus, QualityIssue, TitleCandidate } from '../types';

interface DashboardProps {
  articles: Article[];
  setArticles: React.Dispatch<React.SetStateAction<Article[]>>;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  onAddMessageToAgent?: (prompt: string) => void;
  onSetTab?: (tab: string) => void;
  onSetWorkbenchSubTab?: (subTab: string) => void;
  globalSearchQuery?: string;
  onSelectArticle?: (id: string) => void;
}

export default function Dashboard({
  articles,
  setArticles,
  isDarkMode,
  accentColor,
  onAddMessageToAgent,
  onSetTab,
  onSetWorkbenchSubTab,
  globalSearchQuery = '',
  onSelectArticle
}: DashboardProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedStatus, setSelectedStatus] = useState<ArticleStatus | 'ALL'>('ALL');
  const [selectedArticleId, setSelectedArticleId] = useState<string | null>(null);
  const [activeDetailTab, setActiveDetailTab] = useState<'overview' | 'content' | 'research' | 'assets' | 'publish' | 'quality' | 'logs' | 'prompt'>('overview');

  // Multi-color accents helper
  const getThemeAccentClass = (type: 'text' | 'bg' | 'border' | 'btn' | 'bg-hover') => {
    if (accentColor === 'blue') {
      if (type === 'text') return 'text-[#0077b6]';
      if (type === 'bg') return 'bg-[#0077b6] text-white';
      if (type === 'border') return 'border-[#0077b6]';
      if (type === 'bg-hover') return 'hover:bg-[#0096c7]';
      return 'bg-blue-50 text-blue-800';
    } else if (accentColor === 'green') {
      if (type === 'text') return 'text-[#2d6a4f]';
      if (type === 'bg') return 'bg-[#2d6a4f] text-white';
      if (type === 'border') return 'border-[#2d6a4f]';
      if (type === 'bg-hover') return 'hover:bg-[#40916c]';
      return 'bg-emerald-50 text-emerald-800';
    } else {
      if (type === 'text') return 'text-[#7f5539]';
      if (type === 'bg') return 'bg-[#7f5539] text-white';
      if (type === 'border') return 'border-[#7f5539]';
      if (type === 'bg-hover') return 'hover:bg-[#9c6644]';
      return 'bg-amber-50 text-amber-800';
    }
  };

  const getStatusBadge = (status: ArticleStatus) => {
    switch (status) {
      case '已发布':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200">已发布 (Published)</span>;
      case '待全网发布':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-100 text-blue-800 border border-blue-200">待发布 (To Publish)</span>;
      case '已预览':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-purple-100 text-purple-800 border border-purple-200">已预览 (Previewed)</span>;
      case '待预览':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-100 text-amber-800 border border-amber-200">待预览 (To Preview)</span>;
      case '写作中':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-indigo-100 text-indigo-800 border border-indigo-200">写作中 (Writing)</span>;
      case '待写作':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-100 text-slate-800 border border-slate-200">待写作 (To Write)</span>;
      case '已合并覆盖':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-100 text-rose-800 border border-rose-200">已合并 (Merged)</span>;
      default:
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gray-100 text-gray-800 border border-gray-200">{status}</span>;
    }
  };

  // State filtering logic
  const filteredArticles = articles.filter((art) => {
    const query = (searchTerm || globalSearchQuery || '').toLowerCase();
    const matchesSearch =
      art.title.toLowerCase().includes(query) ||
      art.status.toLowerCase().includes(query) ||
      (art.abstract && art.abstract.toLowerCase().includes(query));
    
    if (selectedStatus === 'ALL') return matchesSearch;
    return art.status === selectedStatus && matchesSearch;
  });

  const selectedArticle = articles.find((art) => art.id === selectedArticleId);

  // Quick Action: local modifications save helper
  const handleUpdateContent = (newText: string) => {
    if (!selectedArticleId) return;
    setArticles((prev) =>
      prev.map((art) => (art.id === selectedArticleId ? { ...art, currentContent: newText } : art))
    );
  };

  // Interactive AI rewrite simulations
  const [rewritePrompt, setRewritePrompt] = useState('');
  const [aiWorking, setAiWorking] = useState(false);

  const triggerRewriteAI = (mode: 'expand' | 'compress' | 'style' | 'inline') => {
    if (!selectedArticle) return;
    setAiWorking(true);
    setTimeout(() => {
      let addedText = '';
      if (mode === 'expand') {
        addedText = `\n\n### 🔬 原理扩充：大流量背压下的 Node.js Event Loop 控制指标\n\n大模型流拉取导致网络延迟时，V8 线程会将所有的 SSE 处理挂起进入 Macro-Task 链条。在我们模拟的指标下：\n1. Event Loop Delay 延迟峰值在未经背压调控前攀升到了 \`451ms\`\n2. 引入滑动窗口背压保护之后，Event Loop Delay 稳定收于 \`4.1ms\`，GC 停止时间（Stop the World）降低 \`92%\`。\n\n由此可见，字节数组指针复用机制对长生命周期文本拼接不仅是防泄漏，更是保证主线程轮询的关键。`;
      } else if (mode === 'compress') {
        addedText = `\n\n[精简批注]：已自动精简多余背景讲述，直接亮出 Docker 与 Node 侧 GC 快照剖析点。`;
      } else {
        addedText = `\n\n[风格调整：${rewritePrompt || '极客风纯主干复盘'}]：对段落排版进行了高密度硬核解刨，精简了修饰句。`;
      }

      setArticles((prev) =>
        prev.map((art) =>
          art.id === selectedArticleId
            ? {
                ...art,
                currentContent: (art.currentContent || '') + addedText,
                actualWords: (art.actualWords || 0) + 150
              }
            : art
        )
      );
      setAiWorking(false);
      setRewritePrompt('');
    }, 1200);
  };

  // Re-write formula SVG or MathML symbols
  const handleFixMathFormula = (issueId: string) => {
    if (!selectedArticleId) return;
    // Simulate auto correction attribution
    alert('正在调用 [LaTeX/Formula Renderer] 执行公式转规范 SVG 动作...');
    setArticles((prev) =>
      prev.map((art) => {
        if (art.id !== selectedArticleId) return art;
        const updatedIssues = art.qualityIssues?.map((qi) =>
          qi.id === issueId ? { ...qi, fixed: true } : qi
        );
        return {
          ...art,
          qualityIssues: updatedIssues,
          currentContent: art.currentContent?.replace('$$E = mc^2$$', '<div class="math-svg-wrapper" style="text-align: center;"><svg>Math Preview</svg></div>')
        };
      })
    );
  };

  return (
    <div className={`flex-1 flex flex-col h-screen overflow-hidden ${
      isDarkMode ? 'bg-[#0f1424] text-white' : 'bg-white text-slate-800'
    }`}>
      <div className="flex-1 flex overflow-hidden">
        {/* Main Side List Panel */}
        <div className={`flex-1 flex flex-col p-6 overflow-y-auto ${
          isDarkMode ? 'bg-[#0f1424]' : 'bg-[#fcfbf9]'
        }`}>
          {/* Dashboard Title */}
          <div className="mb-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-bold font-sans tracking-tight mb-2">
                全生命周期文章库 Total Article Base
              </h2>
              <p className="text-xs text-gray-500">
                集中追踪从“选题、研报、草稿、预览、发布”到“审校与运营复盘”的长期自媒体发布记录。
              </p>
            </div>
            <div>
              <button
                onClick={() => {
                  if (onSetTab) onSetTab('topics');
                }}
                className={`flex items-center px-4 py-1.5 rounded-full text-xs font-semibold space-x-1.5 transition-all cursor-pointer ${getThemeAccentClass('bg')} ${getThemeAccentClass('bg-hover')}`}
              >
                <Plus size={13} />
                <span>开启新选题 生产新内容</span>
              </button>
            </div>
          </div>

          {/* Filtration Controls Header */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-4">
            <div className="flex flex-col sm:flex-row sm:items-center gap-4">
              <div className="flex items-center space-x-2 text-[11px] font-mono text-gray-400">
                📊 稿件多维运行水位看板
              </div>
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 text-gray-405 dark:text-gray-500" size={13} />
                <input
                  type="text"
                  placeholder="搜索库内历史文章（支持标题/状态）..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className={`pl-8 pr-7 py-2.5 w-64 md:w-72 text-xs font-mono rounded-lg border focus:outline-none focus:ring-1 transition-all ${
                    isDarkMode
                      ? 'bg-[#151c2e] border-slate-800 text-slate-200 placeholder-slate-500'
                      : 'bg-[#faf9f6] border-[#dfdbd5] text-slate-800 placeholder-slate-400 shadow-sm'
                  } focus:border-blue-500 focus:ring-blue-500`}
                />
                {searchTerm && (
                  <button
                    onClick={() => setSearchTerm('')}
                    className="absolute right-2.5 top-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                  >
                    <X size={11} />
                  </button>
                )}
              </div>
            </div>

            {/* Filter tags panel */}
            <div className="flex flex-wrap items-center gap-1.5">
              {(['ALL', '待研究', '待写作', '写作中', '待预览', '待全网发布', '已发布'] as const).map((stat) => {
                const isActive = selectedStatus === stat;
                return (
                  <button
                    key={stat}
                    onClick={() => setSelectedStatus(stat)}
                    className={`px-2.5 py-1 text-[11px] rounded transition-all font-mono font-medium ${
                      isActive
                        ? getThemeAccentClass('bg')
                        : isDarkMode
                        ? 'bg-[#151c2e] text-gray-400 hover:bg-slate-800'
                        : 'bg-white text-slate-600 border border-[#e2e0db] hover:bg-slate-50'
                    }`}
                  >
                    {stat === 'ALL' ? '全部 (All)' : stat}
                  </button>
                );
              })}
            </div>
          </div>

          {/* List of articles */}
          <div className="space-y-3">
            {filteredArticles.length === 0 ? (
              <div className="text-center py-12 border border-dashed rounded-lg border-gray-300 dark:border-slate-700">
                <FileText size={36} className="mx-auto text-gray-300 dark:text-slate-700 mb-2" />
                <p className="text-xs text-gray-500 font-mono">暂无匹配的文章条目</p>
              </div>
            ) : (
              filteredArticles.map((art) => {
                const isSelected = art.id === selectedArticleId;
                const hasBlock = art.qualityIssues?.some((qi) => qi.severity === 'Block' && !qi.fixed);
                const hasWarning = art.qualityIssues?.some((qi) => qi.severity === 'Critical_Warning' && !qi.fixed);

                return (
                  <div
                    key={art.id}
                    onClick={() => {
                      setSelectedArticleId(art.id);
                      setActiveDetailTab('overview');
                    }}
                    className={`p-4 rounded-lg border transition-all cursor-pointer ${
                      isSelected
                        ? isDarkMode
                          ? 'bg-[#1a233b] border-[#00b4d8] shadow-sm'
                          : 'bg-[#f4f7fb] border-[#0077b6] shadow-sm'
                        : isDarkMode
                        ? 'bg-[#151c2e] border-[#1e2a44] hover:bg-[#1a233b]/60'
                        : 'bg-white border-[#e2e0db] hover:bg-[#fcfbf9]'
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0 pr-4">
                        <div className="flex items-center space-x-2 mb-1.5 flex-wrap gap-y-1">
                          {getStatusBadge(art.status)}

                          {art.seriesName && (
                            <span className="inline-flex items-center text-[10px] bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 px-1.5 py-0.5 rounded font-mono">
                              📚 {art.seriesName}
                            </span>
                          )}

                          {/* Error/Warning indicators info */}
                          {hasBlock && (
                            <span className="inline-flex items-center text-[10px] text-rose-500 font-semibold bg-rose-50 dark:bg-rose-950/40 px-1.5 rounded animate-pulse">
                              🛑 阻塞性发布错误
                            </span>
                          )}
                          {hasWarning && !hasBlock && (
                            <span className="inline-flex items-center text-[10px] text-amber-500 font-semibold bg-amber-50 dark:bg-amber-950/40 px-1.5 rounded">
                              ⚠️ 严重警告
                            </span>
                          )}
                        </div>

                        <h3 className={`font-semibold text-xs md:text-sm tracking-tight mb-2 ${
                          isDarkMode ? 'text-white' : 'text-slate-800'
                        }`}>
                          {art.title}
                        </h3>

                        {art.abstract && (
                          <p className="text-[11px] text-gray-500 line-clamp-2 leading-relaxed">
                            {art.abstract}
                          </p>
                        )}

                        <div className="flex items-center space-x-4 pt-3 mt-1 border-t border-dashed border-gray-400 border-opacity-20 text-[10px] font-mono text-gray-400">
                          <span className="flex items-center">
                            <Clock size={11} className="mr-1" />
                            {art.updatedAt}
                          </span>
                          <span>字数: <strong className={isDarkMode ? 'text-slate-100' : 'text-slate-800'}>{art.actualWords || '待开发'}</strong> / {art.targetWords || 0}</span>
                          <span>分类: <span className="bg-slate-200 dark:bg-slate-700 px-1 rounded text-slate-700 dark:text-slate-200">{art.type}</span></span>

                          {art.publications && (
                            <span className="text-[#0077b6] dark:text-[#38bdf8]">
                              分发渠道: {art.publications.filter((p) => p.status === 'Published').length} / {art.publications.length}已发
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Cover Thumbnail preview inside card list */}
                      {art.chosenCover && (
                        <div className="w-16 h-16 rounded overflow-hidden shrink-0 border border-slate-200 dark:border-slate-800 ml-2 hidden sm:block">
                          <img
                            src={art.chosenCover}
                            alt="封面"
                            className="w-full h-full object-cover"
                            referrerPolicy="no-referrer"
                          />
                        </div>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Sliding Detail Inspector Panel (Split right window) */}
        {selectedArticle && (
          <div className={`w-full md:w-172 border-l flex flex-col h-full transform transition-all duration-300 absolute md:relative inset-y-0 right-0 z-40 md:z-auto shadow-2xl md:shadow-none ${
            isDarkMode ? 'bg-[#0c101d] border-[#1e2a44]' : 'bg-white border-[#e2e0db]'
          }`}>
            {/* Slideover Title Header */}
            <div className={`p-4 border-b flex items-center justify-between ${
              isDarkMode ? 'border-[#1e2a44] bg-[#090d16]' : 'border-[#faf9f6]'
            }`}>
              <div className="flex-1 min-w-0 pr-2">
                <div className="flex items-center mb-1 space-x-1.5 text-[10px] font-mono text-gray-400">
                  <span>编号 ID: {selectedArticle.id}</span>
                  <span>•</span>
                  <span className="truncate">{selectedArticle.type}</span>
                </div>
                <h2 className="text-xs md:text-sm font-bold truncate tracking-tight text-slate-800 dark:text-white" title={selectedArticle.title}>
                  {selectedArticle.title}
                </h2>
              </div>
              <button
                onClick={() => setSelectedArticleId(null)}
                className="p-1.5 hover:bg-slate-200 dark:hover:bg-slate-800 rounded-full cursor-pointer ml-1"
              >
                <X size={15} />
              </button>
            </div>

            {/* Notion Style Inner Module Tabs Navigation */}
            <div className={`flex border-b text-[10px] font-mono overflow-x-auto ${
              isDarkMode ? 'border-[#1e2a44] bg-[#0c101d]' : 'bg-slate-50 border-[#e2e0db]'
            }`}>
              {[
                { id: 'overview', name: '概览 Overview' },
                { id: 'content', name: '正理/Diff Editor' },
                { id: 'research', name: '知识研报 Research' },
                { id: 'assets', name: '封面素材 Assets' },
                { id: 'publish', name: '全矩阵分发 Drafts' },
                { id: 'quality', name: '质量审校 Audit' },
                { id: 'logs', name: '执行日志 Run logs' },
                { id: 'prompt', name: '调用 Prompt' }
              ].map((tab) => {
                const isActive = activeDetailTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveDetailTab(tab.id as any)}
                    className={`px-3 py-2.5 whitespace-nowrap border-b-2 font-medium transition-colors ${
                      isActive
                        ? isDarkMode
                          ? 'border-[#00b4d8] text-white bg-slate-900'
                          : 'border-[#0077b6] text-[#0077b6] bg-white font-semibold'
                        : 'border-transparent text-gray-400 hover:text-slate-900 dark:hover:text-white'
                    }`}
                  >
                    {tab.name}
                  </button>
                );
              })}
            </div>

            {/* Scrollable Tab Container content */}
            <div className="flex-1 overflow-y-auto p-5 text-xs font-sans">
              
              {/* TAB 1: OVERVIEW */}
              {activeDetailTab === 'overview' && (
                <div className="space-y-4">
                  {/* Metric Cards row */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div className={`p-3 rounded border ${isDarkMode ? 'border-[#1e2a44] bg-[#151c2e] text-slate-100' : 'border-[#e2e0db] bg-slate-50 text-slate-800'}`}>
                      <p className="text-[10px] text-gray-400 font-mono">写作状态</p>
                      <p className="font-semibold text-xs mt-1">{selectedArticle.status}</p>
                    </div>
                    <div className={`p-3 rounded border ${isDarkMode ? 'border-[#1e2a44] bg-[#151c2e] text-slate-100' : 'border-[#e2e0db] bg-slate-50 text-slate-800'}`}>
                      <p className="text-[10px] text-gray-400 font-mono">目标 / 实际字数</p>
                      <p className="font-semibold text-xs mt-1">
                        {selectedArticle.targetWords} / <span className={`${isDarkMode ? 'text-sky-400' : 'text-[#0077b6]'} font-bold`}>{selectedArticle.actualWords || '0'}</span>
                      </p>
                    </div>
                    <div className={`p-3 rounded border ${isDarkMode ? 'border-[#1e2a44] bg-[#151c2e] text-slate-100' : 'border-[#e2e0db] bg-slate-50 text-slate-800'}`}>
                      <p className="text-[10px] text-gray-400 font-mono">所属系列</p>
                      <p className="font-semibold text-xs mt-1 truncate" title={selectedArticle.seriesName || '自主命题'}>
                        {selectedArticle.seriesName || '独立选题'}
                      </p>
                    </div>
                  </div>

                  {/* Document Title Candidate list */}
                  {selectedArticle.titleCandidates && (
                    <div className="p-4 rounded-lg bg-sky-50/50 border border-sky-100 dark:bg-slate-900/60 dark:border-slate-800">
                      <h4 className="font-semibold text-[#0284c7] mb-2 font-mono flex items-center">
                        <TrendingUp size={13} className="mr-1" /> 决策树：历史备选标题与 CTR 估能
                      </h4>
                      <div className="space-y-2">
                        {selectedArticle.titleCandidates.map((cand, i) => {
                          const isChosen = cand.text === selectedArticle.title;
                          return (
                            <div
                              key={i}
                              className={`p-2 rounded border text-[11px] ${
                                isChosen
                                  ? 'bg-sky-100/60 border-sky-300 dark:bg-sky-950/40 dark:border-sky-900 font-medium'
                                  : 'bg-white border-transparent dark:bg-slate-800'
                              }`}
                            >
                              <div className="flex items-center justify-between">
                                <span className={isChosen ? 'text-[#0284c7]' : 'text-gray-400'}>
                                  {isChosen ? '✓ 最终决策标题' : `备选 ${i + 1}`}
                                </span>
                                <span className="font-mono text-[10px] font-semibold text-emerald-600 dark:text-[#52b788]">
                                  CTR 预估: {cand.clicksEstimate}
                                </span>
                              </div>
                              <p className="mt-1 font-sans font-medium text-slate-800 dark:text-slate-100">
                                {cand.text}
                              </p>
                              <p className="text-[10px] text-slate-400 mt-1">
                                {cand.style} · <span className="italic">{cand.hookDepth}</span>
                              </p>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Abstract card */}
                  <div>
                    <h4 className="font-semibold mb-1 font-mono text-gray-500">
                      🔍 核心摘要 (Audience Pitch)
                    </h4>
                    <p className={`p-3 rounded border leading-relaxed italic ${isDarkMode ? 'bg-[#151c2e] border-[#1e2a44] text-slate-300' : 'bg-slate-50 border-[#e2e0db] text-slate-600'}`}>
                      {selectedArticle.abstract || '未设置核心摘要。'}
                    </p>
                  </div>

                  {/* Outline List tree */}
                  <div>
                    <h4 className="font-semibold mb-2 font-mono text-gray-500 flex items-center justify-between">
                      <span>📌 被确认的写作大纲 (Structural Blueprint)</span>
                      <span className="text-[10px] text-gray-400 normal-case">人工确认锁住状态</span>
                    </h4>
                    {selectedArticle.outline ? (
                      <div className="border border-[#dfdbd5] dark:border-[#1e2a44] rounded-lg overflow-hidden bg-white dark:bg-slate-900">
                        {selectedArticle.outline.map((out, idx) => (
                          <div
                            key={out.id}
                            className={`p-3 border-b last:border-0 ${
                              isDarkMode ? 'border-[#1e2a44]' : 'border-slate-100'
                            }`}
                          >
                            <p className="font-mono font-medium text-slate-800 dark:text-slate-200">
                              #{idx + 1}. {out.title}
                            </p>
                            {out.subtopics && out.subtopics.length > 0 && (
                              <ul className="list-disc pl-5 mt-1.5 space-y-1 text-gray-400 font-sans">
                                {out.subtopics.map((sub, sidx) => (
                                  <li key={sidx}>{sub}</li>
                                ))}
                              </ul>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-gray-400 italic">暂无确认的大纲</p>
                    )}
                  </div>

                  {/* Hook Scene (爆款首包钩子) */}
                  <div>
                    <h4 className="font-semibold mb-1 font-mono text-gray-500 flex items-center justify-between">
                      <span>🪝 首包真实痛点事故钩子 (Hook Scene)</span>
                      <span className="text-[10px] text-gray-400 normal-case">对应并对齐AI写作工作台</span>
                    </h4>
                    <p className={`p-3 rounded border leading-relaxed text-xs ${isDarkMode ? 'bg-[#151c2e] border-[#1e2a44] text-slate-300' : 'bg-slate-50 border-[#e2e0db] text-slate-600'}`}>
                      {selectedArticle.hookScene || `【真实事故瞬间复盘】服务器监控突然发出刺眼的红色预警。后端网关响应时延迅速突破 2000ms，V8 内存极速狂飙至 1.8G，随即崩溃重启。我们惊恐地发现，问题源于在大模型长文本流式 SSE 状态下，下游由于网速过慢发生数据挤压，而上游却未遵循 drain 机制肆无忌惮地持续调用 write，最终被背压引发的内存泄露彻底击穿！`}
                    </p>
                  </div>

                  {/* Golden Quotes / Punchlines (爆款核心金句) */}
                  <div>
                    <h4 className="font-semibold mb-1 font-mono text-gray-500 flex items-center justify-between">
                      <span>🔑 醍醐灌顶爆款金句/语录 (Golden Quotes / Punchlines)</span>
                      <span className="text-[10px] text-gray-400 normal-case">对应并对齐AI写作工作台</span>
                    </h4>
                    <div className={`p-3 rounded border font-mono space-y-2 text-xs leading-relaxed whitespace-pre-line ${isDarkMode ? 'bg-[#151c2e] border-[#1e2a44] text-slate-300' : 'bg-slate-50 border-[#e2e0db] text-slate-600'}`}>
                      {(selectedArticle as any).goldenQuotes || `1. "背压（Backpressure）不是简单的阻断，而是系统各节点间关于写强度的优雅博弈与妥协。"
2. "在大模型流式引擎中，忽略对 drain 返回值的自检测，等同于无保护地在泥沼路面狂飙至两百万转速。"
3. "用 80 行原生 TypeScript 构建 Writable 影子缓冲区，换来的是面对上万并发 SSE 连接时从容不迫的系统稳定阀！"`}
                    </div>
                  </div>

                </div>
              )}

              {/* TAB 2: EDITOR */}
              {activeDetailTab === 'content' && (
                <div className="space-y-4 flex flex-col h-full min-h-[500px]">
                  {/* Redirect banner */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between p-3.5 rounded-xl bg-violet-50/50 dark:bg-purple-950/25 border border-violet-100 dark:border-purple-900 gap-3">
                    <div className="flex items-start space-x-2 text-xs">
                      <div className="bg-purple-100 dark:bg-purple-900/60 p-2 rounded-lg text-purple-700 dark:text-purple-300">
                        <SparklesIcon className="text-purple-500 animate-pulse" size={15} />
                      </div>
                      <div>
                        <p className="font-bold text-purple-905 dark:text-purple-400 font-mono">
                          🔒 本中心仅作草稿历史记录与核对
                        </p>
                        <p className="text-slate-500 dark:text-slate-400 mt-1 font-sans">
                          此处不支持直接修改正文。如需调动 <strong>AI 局部重写协同器</strong>（扩写、压缩、风格微调）及编辑，请点击前往 AI 写作工作台启动交互。
                        </p>
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => {
                        if (onSelectArticle) {
                          onSelectArticle(selectedArticle.id);
                        }
                        if (onSetWorkbenchSubTab) {
                          onSetWorkbenchSubTab('body');
                        }
                        if (onSetTab) {
                          onSetTab('workbench');
                        }
                      }}
                      className="px-4 py-2 bg-gradient-to-r from-purple-700 to-indigo-600 dark:from-purple-800 dark:to-indigo-700 text-white rounded-xl text-xs font-bold font-mono hover:opacity-95 active:scale-95 shadow-xs transition-all flex items-center justify-center space-x-1 whitespace-nowrap"
                    >
                      <span>跳转至 AI 写作工作台正文 ➔</span>
                    </button>
                  </div>

                  {/* Versions history slider overlay diff helper */}
                  <div className="flex items-center justify-between text-[10px] font-mono text-gray-400">
                    <span>✏️ 交互式编辑器 (Read-Only 阅览模式)</span>
                    <span className="flex items-center">
                      <History size={11} className="mr-1" />
                      已存版本: v2 (最后修改于数分钟前已归档)
                    </span>
                  </div>

                  {/* Main text area */}
                  <textarea
                    readOnly
                    value={selectedArticle.currentContent || ''}
                    placeholder="正文目前为空，请先在 AI 写作工作台起草生成。"
                    className={`w-full h-96 p-4 font-mono text-xs rounded-lg border focus:outline-none focus:ring-1 leading-relaxed ${
                      isDarkMode
                        ? 'bg-[#151c2e] border-[#1e2a44] text-slate-100 focus:ring-[#00b4d8]'
                        : 'bg-white border-[#dfdbd5] text-slate-800 focus:ring-[#0077b6]'
                    }`}
                  />

                  {/* Render Draft Difference with original generation output */}
                  {selectedArticle.originalDraft && (
                    <div className="border border-slate-200 dark:border-slate-800 rounded-lg overflow-hidden mt-2">
                      <div className="bg-slate-100 dark:bg-slate-900 p-2 border-b flex items-center justify-between font-mono text-[10px]">
                        <span>Diff: 原始生成草稿 vs 研改效果版</span>
                        <span className="text-gray-500">双主入口同步结果</span>
                      </div>
                      <div className="p-3 bg-stone-50 dark:bg-[#0c101d] font-mono text-[9px] leading-relaxed max-h-40 overflow-y-auto space-y-1">
                        <p className="text-red-500">- # 引入在大模型技术向硬核业务延伸时，分布式事务是个噩梦...</p>
                        <p className="text-green-500">+ # 模拟谷歌 Spanner 提交协议：解决三方 Agent 与本地数据库双写一致性悬挂</p>
                        <p className="text-green-500">+ 在大模型向生产环境落地中，我们让 Agent 拥有了真实的执行权...</p>
                        <p className="text-gray-400">... [省略 42 处一致性细节修改]</p>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* TAB 3: RESEARCH */}
              {activeDetailTab === 'research' && (
                <div className="space-y-4">
                  {selectedArticle.researchReport ? (
                    <>
                      {/* Summary Card and Evidence indicators */}
                      <div className="p-4 rounded-lg bg-green-50/50 dark:bg-emerald-950/20 border border-green-100 dark:border-emerald-900">
                        <h4 className="font-semibold text-emerald-800 dark:text-[#52b788] mb-1.5 font-mono flex items-center">
                          <CheckCircle2 size={13} className="mr-1" /> Research Summary (研报大纲)
                        </h4>
                        <p className="leading-relaxed text-slate-700 dark:text-slate-300">
                          {selectedArticle.researchReport.summary}
                        </p>
                        <div className="mt-3 flex items-center justify-between font-mono text-[10px] text-gray-500">
                          <span>信源覆盖可靠性: <strong>{selectedArticle.researchReport.coveragePercent}%</strong></span>
                          <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 font-bold">
                            一手信源验证 OK
                          </span>
                        </div>
                      </div>

                      {/* Sources list */}
                      <div>
                        <h4 className="font-semibold mb-2 font-mono text-gray-500">
                          🌐 学术论证与参考信源库 ({selectedArticle.researchReport.sources?.length} 个真实节点)
                        </h4>
                        <div className="space-y-3">
                          {selectedArticle.researchReport.sources?.map((src, sIdx) => (
                            <div
                              key={sIdx}
                              className="p-3 rounded-lg border border-[#dfdbd5] dark:border-[#1e2a44] bg-white dark:bg-slate-900"
                            >
                              <div className="flex items-center justify-between mb-1.5 flex-wrap gap-y-1">
                                <span className={`font-semibold ${getThemeAccentClass('text')}`}>
                                  {src.title}
                                </span>
                                <span className={`px-1.5 py-0.5 rounded text-[9px] font-semibold ${
                                  src.reliability === 'High'
                                    ? 'bg-emerald-100 text-emerald-800'
                                    : 'bg-[#f4f7fb] text-blue-800'
                                }`}>
                                  置信度: {src.reliability} [Core]
                                </span>
                              </div>
                              <p className="text-gray-500 italic mb-2">"{src.extract}"</p>
                              <a
                                href={src.url}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center text-[#0077b6] dark:text-[#38bdf8] font-mono text-[10px] hover:underline"
                              >
                                {src.url} <ExternalLink size={10} className="ml-1" />
                              </a>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Gaps review */}
                      {selectedArticle.researchReport.evidenceGaps && selectedArticle.researchReport.evidenceGaps.length > 0 && (
                        <div className="p-3 rounded bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900 text-[11px]">
                          <p className="font-semibold text-amber-800 dark:text-amber-400 font-mono mb-1">
                            ⚠️ 证据不完美复盘 (Evidence Gaps / 缺陷探究)
                          </p>
                          <ul className="list-disc pl-4 space-y-0.5 font-sans">
                            {selectedArticle.researchReport.evidenceGaps.map((gp, gidx) => (
                              <li key={gidx} className="text-slate-600 dark:text-slate-300">{gp}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="text-center py-10 text-gray-500 italic">
                      该文章尚未挂接 Research 研报。
                    </div>
                  )}
                </div>
              )}

              {/* TAB 4: ASSETS */}
              {activeDetailTab === 'assets' && (
                <div className="space-y-4">
                  {/* Cohesion theme direction */}
                  <div className="p-3 rounded border border-dashed border-[#dfdbd5] dark:border-[#1e2a44]">
                    <p className="font-mono text-gray-400">🎨 Visual Guidelines (视觉概念规范)</p>
                    <p className="mt-1 font-semibold text-slate-800 dark:text-slate-100">
                      方向: {selectedArticle.coverStyleDirection || 'Brutalism Vector Schematic'}
                    </p>
                    <p className="text-[11px] text-gray-500 italic mt-1">
                      Brief: {selectedArticle.coverBrief || 'Minimal blueprint diagram'}
                    </p>
                  </div>

                  {/* Covers candidate gallery */}
                  <div>
                    <h4 className="font-semibold mb-2 font-mono text-gray-500">
                      🌄 Midjourney/DALL-E 最终封面与候选图集
                    </h4>
                    {selectedArticle.chosenCover ? (
                      <div className="grid grid-cols-2 gap-3">
                        <div className="relative border border-slate-300 dark:border-slate-800 roundedoverflow-hidden">
                          <img
                            src={selectedArticle.chosenCover}
                            alt="已锁定封面"
                            className="w-full h-32 object-cover"
                            referrerPolicy="no-referrer"
                          />
                          <span className="absolute bottom-1 right-1 bg-emerald-600 text-white text-[9px] px-1 rounded font-mono">
                            ✓ 已确立发布封面
                          </span>
                        </div>

                        {selectedArticle.coverCandidates?.filter((c) => c !== selectedArticle.chosenCover).map((c, idx) => (
                          <div key={idx} className="relative border border-slate-200 dark:border-slate-800 rounded group overflow-hidden">
                            <img
                              src={c}
                              alt="候选封面"
                              className="w-full h-32 object-cover opacity-70 group-hover:opacity-100 transition-opacity"
                              referrerPolicy="no-referrer"
                            />
                            <button
                              onClick={() => {
                                setArticles((prev) =>
                                  prev.map((art) =>
                                    art.id === selectedArticleId ? { ...art, chosenCover: c } : art
                                  )
                                );
                              }}
                              className="absolute inset-0 bg-black bg-opacity-40 flex items-center justify-center text-white opacity-0 group-hover:opacity-100 transition-opacity text-[10px] font-mono cursor-pointer"
                            >
                              设为最终封面
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-gray-400 italic">未上传或未生成封面候选图。</p>
                    )}
                  </div>

                  {/* Formula and SVG diagrams previews */}
                  <div>
                    <h4 className="font-semibold mb-2 font-mono text-gray-500">
                      📐 页面嵌插媒体与高阶公式 SVG
                    </h4>
                    {selectedArticle.mediaAssets && selectedArticle.mediaAssets.length > 0 ? (
                      <div className="space-y-3">
                        {selectedArticle.mediaAssets.map((asset) => (
                          <div
                            key={asset.id}
                            className="p-3 bg-slate-50 dark:bg-slate-900 border rounded-lg"
                          >
                            <p className="font-mono text-[10px] text-gray-500">
                              类型: {asset.type.toUpperCase()} · 资源 ID: {asset.id}
                            </p>
                            <p className="font-semibold mb-2 mt-0.5 text-slate-800 dark:text-slate-100">
                              {asset.name}
                            </p>

                            {/* Demo SVG placeholder check */}
                            {asset.url.startsWith('#') ? (
                              <div className={`h-60 rounded flex items-center justify-center font-mono overflow-auto border ${
                                isDarkMode ? 'bg-slate-950 border-[#1e2a44]' : 'bg-slate-50 border-[#dfdbd5]'
                              }`}>
                                <div className="p-2 w-full h-full text-[10px] select-all">
                                  {/* Standard XML layout code */}
                                  <pre className={`text-[8px] whitespace-pre-wrap leading-tight ${
                                    isDarkMode ? 'text-[#00b4d8]' : 'text-cyan-800'
                                  }`}>
                                    {`<!-- SVG Blueprint for Spanner Consistent locks -->\n<svg viewBox="0 0 800 400" fill="none"> ... </svg>`}
                                  </pre>
                                </div>
                              </div>
                            ) : (
                              <div className={`h-24 rounded overflow-hidden flex items-center justify-center ${
                                isDarkMode ? 'bg-slate-950' : 'bg-slate-100'
                              }`}>
                                <img
                                  src={asset.url}
                                  alt={asset.name}
                                  className="h-full object-contain"
                                  referrerPolicy="no-referrer"
                                />
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-slate-400 italic">未发现附带公式或反应组件素材。</p>
                    )}
                  </div>
                </div>
              )}

              {/* TAB 5: PUBLISH PREVIEWS */}
              {activeDetailTab === 'publish' && (
                <div className="space-y-4">
                  <div className="p-3 text-[11px] bg-slate-50 dark:bg-slate-950 border rounded-lg leading-relaxed">
                    <p className="font-bold text-slate-800 dark:text-slate-200">
                      🚀 全网矩阵发布真相源 (Publishing Truth Source)
                    </p>
                    AImagician 追踪各平台草稿 ID、公开 URL 以及发布故障，确保同一内容不可二次重复发布（免覆盖安全机制）。
                  </div>

                  {selectedArticle.publications ? (
                    <div className="space-y-3">
                      {selectedArticle.publications.map((pub, pIdx) => {
                        let statusColor = 'text-gray-400';
                        if (pub.status === 'Published') statusColor = 'text-green-500 font-bold';
                        else if (pub.status === 'Draft') statusColor = 'text-purple-500';
                        else if (pub.status === 'Failed') statusColor = 'text-rose-500 font-bold';
                        else if (pub.status === 'Checking') statusColor = 'text-blue-500 animate-pulse';

                        return (
                          <div
                            key={pIdx}
                            className="p-3 border rounded-lg flex items-center justify-between bg-white dark:bg-slate-900"
                          >
                            <div>
                              <p className="font-semibold text-xs text-slate-800 dark:text-white">
                                {pub.platformName}
                              </p>
                              <div className="flex items-center space-x-2 mt-1 text-[10px] font-mono text-gray-500">
                                {pub.draftId && (
                                  <span>草稿 ID: <code className="bg-slate-100 dark:bg-slate-800 px-1 rounded">{pub.draftId}</code></span>
                                )}
                                {pub.publishTime && <span>发布时间: {pub.publishTime}</span>}
                              </div>
                              
                              {pub.errorMessage && (
                                <p className="text-[10px] text-rose-500 mt-1.5 bg-rose-50 dark:bg-rose-950/20 p-1.5 rounded border border-rose-100">
                                  错误: {pub.errorMessage}
                                </p>
                              )}
                            </div>

                            <div className="text-right flex flex-col items-end space-y-1">
                              <span className={`font-mono text-[10px] ${statusColor}`}>
                                {pub.status.toUpperCase()}
                              </span>

                              {pub.url && (
                                <a
                                  href={pub.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center text-[#0077b6] dark:text-[#38bdf8] font-mono text-[10px] hover:underline"
                                >
                                  查看公开链接 <ExternalLink size={9} className="ml-1" />
                                </a>
                              )}

                              {pub.status === 'Failed' && (
                                <button
                                  onClick={() => {
                                    alert(`触发对 ${pub.platformName} 的重新发布动作...`);
                                  }}
                                  className="px-2 py-0.5 bg-[#0077b6] text-white rounded text-[9px] font-mono"
                                >
                                  重试发布
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-gray-400 italic">该文章无任何平台发布链。</p>
                  )}
                </div>
              )}

              {/* TAB 6: QUALITY AUDIT */}
              {activeDetailTab === 'quality' && (
                <div className="space-y-4">
                  {/* Gate checklist header quality indicators */}
                  <div className="flex items-center justify-between border-b pb-2">
                    <span className="font-bold text-xs">AImagician 质量卡防系统</span>
                    <span className="px-2 py-0.5 rounded-full bg-rose-100 dark:bg-rose-950/40 text-[10px] font-mono text-rose-700">
                      强制人工确认闸
                    </span>
                  </div>

                  {selectedArticle.qualityIssues && selectedArticle.qualityIssues.length > 0 ? (
                    <div className="space-y-3">
                      {selectedArticle.qualityIssues.map((issue) => {
                        let sevBadge = '';
                        if (issue.severity === 'Block') {
                          sevBadge = 'bg-rose-100 dark:bg-rose-950/40 text-rose-800 border-rose-300';
                        } else if (issue.severity === 'Critical_Warning') {
                          sevBadge = 'bg-amber-100 dark:bg-amber-950/40 text-amber-800 border-amber-300';
                        } else {
                          sevBadge = 'bg-blue-100 dark:bg-blue-950/40 text-blue-800 border-blue-300';
                        }

                        return (
                          <div
                            key={issue.id}
                            className={`p-3 border rounded-lg flex flex-col space-y-2 bg-[#fdfdfd] dark:bg-slate-900 ${
                              issue.fixed
                                ? 'opacity-50 border-slate-200 line-through'
                                : 'border-slate-300 dark:border-[#1e2a44]'
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <span className={`px-2 py-0.5 border rounded font-mono text-[9px] ${sevBadge}`}>
                                {issue.severity} [{'阻塞性'}]
                              </span>
                              <span className="font-mono text-gray-400 text-[10px]">
                                归因归结: {issue.attributedModule}
                              </span>
                            </div>

                            <p className="text-[11px] leading-relaxed font-sans text-slate-800 dark:text-slate-100">
                              {issue.description}
                            </p>

                            {!issue.fixed && (
                              <div className="flex justify-end pt-1">
                                {issue.category === 'Assets' && (
                                  <button
                                    onClick={() => handleFixMathFormula(issue.id)}
                                    className="px-2 py-1 bg-emerald-700 hover:bg-emerald-800 text-white rounded text-[9px] font-semibold font-mono"
                                  >
                                    🛠️ 触发公式自动渲染修复 (Repair)
                                  </button>
                                )}

                                {issue.category === 'Content' && (
                                  <button
                                    onClick={() => {
                                      setActiveDetailTab('content');
                                      alert('请在编辑器中运行局部重写，扩增正文字数！');
                                    }}
                                    className="px-2 py-1 bg-[#7f5539] text-white rounded text-[9px] font-mono"
                                  >
                                    ✍️ 去编辑器手动扩写
                                  </button>
                                )}
                              </div>
                            )}

                            {issue.fixed && (
                              <span className="text-emerald-500 font-bold self-end text-[10px] font-mono">
                                ✓ 已闭环修复
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="text-center py-10">
                      <p className="text-emerald-500 font-bold font-mono">✓ 100% 审计放行：该草稿无阻塞性错误</p>
                      <p className="text-xs text-gray-400 mt-1">可以通过全分发控制台进行全平台发布。</p>
                    </div>
                  )}
                </div>
              )}

              {/* TAB 7: RUN LOGS */}
              {activeDetailTab === 'logs' && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between border-b pb-2">
                    <span className="font-semibold text-xs font-mono">运行历史与状态回溯 (Audit Logs)</span>
                    <span className="text-[10px] text-gray-500">双主入口同步审计</span>
                  </div>

                  <div className="relative border-l-2 border-slate-200 dark:border-slate-800 pl-4 ml-2 space-y-4 py-1">
                    {selectedArticle.agentLogs?.map((log, lIdx) => (
                      <div key={lIdx} className="relative">
                        <div className="absolute -left-[21px] top-1.5 w-2 h-2 rounded-full bg-emerald-500 ring-4 ring-slate-100 dark:ring-slate-900" />
                        <p className="font-mono text-[10px] text-gray-400">
                          {log.timestamp} · {log.agent}
                        </p>
                        <p className="font-semibold mt-0.5 text-slate-800 dark:text-slate-100">
                          {log.action} ({log.status})
                        </p>
                        <p className="text-[10px] text-slate-500 leading-normal mt-0.5">
                          {log.detail}
                        </p>
                      </div>
                    ))}
                    
                    {/* Add manual initial log block */}
                    <div className="relative">
                      <div className="absolute -left-[21px] top-1.5 w-2 h-2 rounded-full bg-blue-500 ring-4 ring-slate-100 dark:ring-slate-900" />
                      <p className="font-mono text-[10px] text-gray-400">
                        {selectedArticle.createdAt} · 人工创建/系列排程
                      </p>
                      <p className="font-semibold mt-0.5 text-slate-800 dark:text-slate-100">
                        Initial state registered
                      </p>
                      <p className="text-[10px] text-slate-500 leading-normal mt-0.5">
                        选题源通过系列规划系统成功锁闭，进入 “待研究” 运行时初态。
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 8: PROMPT DETAILS */}
              {activeDetailTab === 'prompt' && (
                <div className="space-y-4">
                  {/* Prompt versions references */}
                  <div className="p-3 rounded bg-amber-50 dark:bg-slate-900 border border-amber-200 dark:border-slate-800 text-[11px] font-mono leading-relaxed">
                    <p className="font-bold mb-1">📝 Prompt Track & Rendering (渲染指令记录)</p>
                    锁定文章生命周期使用的精确 Prompt 版本，避免 Prompt 任意变更导致生成质量倒退。
                  </div>

                  <div className="space-y-3">
                    <div className="p-3 bg-slate-50 dark:bg-slate-950 border rounded-lg">
                      <div className="flex items-center justify-between mb-1.5 font-mono text-[10px]">
                        <span className="font-bold">1. 知识 Research 扩展指令</span>
                        <span className="text-gray-400">版本: [Research v2.1]</span>
                      </div>
                      <pre className={`p-2 rounded text-[9px] overflow-auto whitespace-pre-wrap border ${
                        isDarkMode ? 'bg-slate-900 text-cyan-400 border-slate-800' : 'bg-slate-100 text-cyan-800 border-slate-200'
                      }`}>
                        {`"以大语言模型技术专家视角，针对关键词 <${selectedArticle.title}> 拓展生成具有学界真实论文对照点的研究备忘..."`}
                      </pre>
                    </div>

                    <div className="p-3 bg-slate-50 dark:bg-slate-950 border rounded-lg">
                      <div className="flex items-center justify-between mb-1.5 font-mono text-[10px]">
                        <span className="font-bold">2. 正文深度生成 Instruction</span>
                        <span className="text-gray-400">版本: [DeepBody Writer v4.0.2]</span>
                      </div>
                      <pre className={`p-2 rounded text-[9px] overflow-auto whitespace-pre-wrap border ${
                        isDarkMode ? 'bg-slate-900 text-cyan-400 border-slate-800' : 'bg-slate-100 text-cyan-800 border-slate-200'
                      }`}>
                        {`"基于已确认的大纲目录及开头场景钩子，输出排版精细的自媒体深度硬核稿。要求目标字数为: ${selectedArticle.targetWords || 4500}..."`}
                      </pre>
                    </div>
                  </div>
                </div>
              )}

            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Sparkles local SVG icon fallback for UI
function SparklesIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={props.size || "24"}
      height={props.size || "24"}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={props.className}
    >
      <path d="M12 3v16M8 5h8M3 12h18M5 8h14" />
    </svg>
  );
}
