import React, { useState, useRef, useEffect } from 'react';
import { Search, ChevronDown, BookOpen, Layers, X, Flame, Edit3, Clipboard, Share2, Shield, Radio, Terminal } from 'lucide-react';
import { Article, Series, PromptRule } from '../types';

interface GlobalSelectorProps {
  articles: Article[];
  seriesList?: Series[];
  selectedArticleId?: string;
  selectedSeriesId?: string;
  onSelectArticle?: (id: string) => void;
  onSelectSeries?: (id: string) => void;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  globalSearchQuery: string;
  setGlobalSearchQuery: (query: string) => void;
  activeTab?: string;
  promptRules?: PromptRule[];
}

export default function GlobalSelector({
  articles = [],
  seriesList = [],
  selectedArticleId,
  selectedSeriesId,
  onSelectArticle,
  onSelectSeries,
  isDarkMode,
  accentColor,
  globalSearchQuery,
  setGlobalSearchQuery,
  activeTab,
  promptRules = []
}: GlobalSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Global Click Outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Keyboard shortcut supporting Ctrl/Cmd + K
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
        event.preventDefault();
        inputRef.current?.focus();
        setIsOpen(true);
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const getAccentColorClass = () => {
    if (accentColor === 'green') return 'text-emerald-500 hover:bg-emerald-500/10 focus:ring-emerald-500';
    if (accentColor === 'brown') return 'text-amber-600 hover:bg-amber-600/10 focus:ring-amber-700';
    return 'text-[#0077b6] hover:bg-blue-500/10 focus:ring-[#0077b6]';
  };

  const getAccentBorderClass = () => {
    if (accentColor === 'green') return 'focus:border-emerald-500 focus:ring-emerald-550 focus:shadow-emerald-500/10';
    if (accentColor === 'brown') return 'focus:border-amber-700 focus:ring-amber-750 focus:shadow-amber-700/10';
    return 'focus:border-blue-500 focus:ring-blue-500 focus:shadow-blue-500/10';
  };

  // Content-aware placeholders based on active tab
  const getSearchPlaceholder = () => {
    switch (activeTab) {
      case 'topics': return '搜索全网选题热点 (hotspots)...';
      case 'overview': return '搜索历史文章 (标题/状态)...';
      case 'workbench': return '筛选当前草稿文章...';
      case 'planner': return '检索长期大纲或章节...';
      case 'publish': return '检索未发布或可用稿件...';
      case 'assets': return '在资产库中检索媒体资源...';
      case 'analytics': return '检索大盘或审计规则...';
      case 'rules': return '检索编译提示词集...';
      case 'mcp': return '寻找已挂载的 MCP/RPC 主机服务...';
      default: return '全局网关检索 (Search)...';
    }
  };

  // Dynamic selector items matching active tab
  const getDropdownHeader = () => {
    switch (activeTab) {
      case 'topics': return '🔥 自动热点选题检索推荐';
      case 'workbench': return '📝 工作台聚焦草稿/选题切换';
      case 'overview': return '📁 内容中枢历史数据索引';
      case 'publish': return '🚀 投递稿件安全签署网关';
      case 'planner': return '📚 书籍专栏与系列大纲';
      case 'rules': return '🧠 Prompt 风格合规治理准则';
      case 'mcp': return '🔌 MCP 宿主守护组件服务';
      default: return '🔍 全空间高精度检索矩阵';
    }
  };

  return (
    <div className="relative font-sans text-xs select-none" ref={dropdownRef}>
      
      {/* Dynamic Header Searchbar */}
      <div className="flex items-center space-x-1.5">
        <div className="relative group">
          <span className="absolute left-3 top-2 flex items-center text-gray-400 dark:text-gray-550 group-hover:text-amber-500 transition-colors duration-200">
            <Search size={13} className="animate-pulse" />
          </span>
          <input
            ref={inputRef}
            type="text"
            onFocus={() => setIsOpen(true)}
            placeholder={getSearchPlaceholder()}
            value={globalSearchQuery}
            onChange={(e) => {
              setGlobalSearchQuery(e.target.value);
              setIsOpen(true);
            }}
            className={`pl-8 pr-12 py-1.5 w-44 sm:w-60 md:w-72 text-xs font-mono rounded-lg border focus:outline-none focus:ring-1 transition-all ${
              isDarkMode
                ? 'bg-[#151c2e] border-[#1e2a44] text-slate-200 placeholder-slate-500 focus:bg-[#1a233a] focus:shadow-[0_0_12px_rgba(59,130,246,0.15)]'
                : 'bg-[#faf9f6] border-[#dfdbd5] text-slate-800 placeholder-slate-400 focus:bg-white focus:shadow-[0_0_12px_rgba(59,130,246,0.08)]'
            } ${getAccentBorderClass()}`}
          />

          {/* Shortcut indicator inline badge */}
          {!globalSearchQuery && (
            <span className="hidden md:inline-flex items-center absolute right-3 top-2 px-1 py-0.5 text-[8.5px] font-mono leading-none rounded bg-slate-200 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border border-slate-300 dark:border-slate-700/60 select-none pointer-events-none transition-opacity duration-200 opacity-80 group-focus-within:opacity-0">
              ⌘K
            </span>
          )}

          {globalSearchQuery && (
            <button
              onClick={() => {
                setGlobalSearchQuery('');
                setIsOpen(false);
              }}
              className="absolute right-2.5 top-[7px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-0.5 rounded-full hover:bg-slate-200 dark:hover:bg-slate-800 transition-all duration-150"
              title="清除输入内容"
            >
              <X size={11} />
            </button>
          )}
        </div>

        {/* Unified gateway dropdown activator */}
        <button
          onClick={() => setIsOpen(!isOpen)}
          className={`p-1.5 border rounded-lg hover:border-slate-400 dark:hover:border-slate-700 hover:scale-105 active:scale-95 transition-all text-xs ${
            isDarkMode ? 'bg-[#151c2e] border-slate-800 text-gray-400/90' : 'bg-[#faf9f6] border-[#dfdbd5] text-slate-600'
          }`}
          title="切换全局聚焦与控制上下文"
        >
          <ChevronDown size={13} className={`transform transition-transform duration-300 ${isOpen ? 'rotate-180 text-amber-500' : ''}`} />
        </button>
      </div>

      {isOpen && (
        <div
          className={`absolute right-0 mt-2 w-[325px] sm:w-[380px] max-w-[calc(100vw-24px)] max-h-96 overflow-hidden rounded-xl border shadow-xl z-[100] p-3 flex flex-col space-y-2 py-3 ${
            isDarkMode ? 'bg-slate-950 border-slate-800 text-white' : 'bg-white border-slate-200 text-slate-850'
          }`}
        >
          {/* Header Title inside Search Box */}
          <div className="flex items-center justify-between pb-1.5 border-b border-slate-150 dark:border-slate-850 font-mono text-[9px] text-gray-400 leading-none">
            <span className="font-bold tracking-wider">{getDropdownHeader()}</span>
            <span className="bg-slate-200/50 dark:bg-slate-800/60 px-1 py-0.5 rounded text-[8px]">CONTEXT-DECK</span>
          </div>

          {/* Render Contextual Filter Options based on ActiveTab */}
          <div className="flex-1 overflow-y-auto max-h-60 space-y-1 pr-1 font-mono text-[11px]">
            {/* Tab-driven UI content */}
            {activeTab === 'topics' && (
              <div className="space-y-1 bg-slate-50/50 dark:bg-slate-900/50 p-1.5 rounded-lg border">
                <p className="text-[10px] text-gray-400 mb-1.5 flex items-center"><Flame size={10} className="mr-1 text-red-500 animate-pulse" /> 当前推荐热度搜索列表 (匹配中):</p>
                {[
                  'DeepSeek-R1 本地蒸馏小模型：使用 WebAssembly 与 SIMD',
                  '美团大规模 GraphRAG 内存雪崩剖析：HNSW 重排技术',
                  '排查 K8s HPA 下的大模型长连接：Event Loop 控流',
                  '基于 Spanner 2PC 分布式共识协议的 Action 状态双写自愈'
                ]
                  .filter(hot => hot.toLowerCase().includes(globalSearchQuery.toLowerCase()))
                  .map((title, idx) => (
                    <div
                      key={idx}
                      onClick={() => {
                        setGlobalSearchQuery(title);
                        setIsOpen(false);
                      }}
                      className="p-2 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer flex items-start gap-1.5"
                    >
                      <span className="text-red-500 font-bold shrink-0">{idx + 1}.</span>
                      <span className="truncate block font-sans text-xs">{title}</span>
                    </div>
                  ))}
              </div>
            )}

            {activeTab === 'workbench' && (
              <div className="space-y-1">
                <p className="text-[10px] text-gray-400 mb-1 flex items-center"><Edit3 size={10} className="mr-1 text-blue-500" /> 选择聚焦工作台草稿进行规格签署或多段研写 :</p>
                {articles
                  .filter(art => art.status !== '已发布' && art.title.toLowerCase().includes(globalSearchQuery.toLowerCase()))
                  .map((art) => (
                    <button
                      key={art.id}
                      onClick={() => {
                        onSelectArticle?.(art.id);
                        setIsOpen(false);
                      }}
                      className={`w-full text-left p-2 rounded-lg transition-colors flex flex-col space-y-0.5 ${
                        art.id === selectedArticleId
                          ? isDarkMode ? 'bg-slate-800 text-white border-l-2' : 'bg-blue-50 text-blue-900 border-l-2 border-blue-600'
                          : 'hover:bg-slate-100 dark:hover:bg-slate-900'
                      }`}
                    >
                      <div className="flex justify-between items-center text-[8px] opacity-70">
                        <span>{art.status}</span>
                        <span>#{art.id}</span>
                      </div>
                      <p className="truncate w-full font-bold font-sans text-xs pr-1">{art.title}</p>
                    </button>
                  ))}
              </div>
            )}

            {(activeTab === 'overview' || activeTab === 'publish') && (
              <div className="space-y-1">
                <p className="text-[10px] text-gray-400 mb-1 flex items-center"><Clipboard size={10} className="mr-1 text-emerald-500" /> 选择挂载和追踪的生命周期档案 ({activeTab === 'publish' ? '未发布/待投递' : '合集总文章书目'}):</p>
                {articles
                  .filter(art => {
                    const passQuery = art.title.toLowerCase().includes(globalSearchQuery.toLowerCase());
                    if (activeTab === 'publish') {
                      return art.status !== '已发布' && passQuery;
                    }
                    return passQuery;
                  })
                  .map((art) => (
                    <button
                      key={art.id}
                      onClick={() => {
                        onSelectArticle?.(art.id);
                        setIsOpen(false);
                      }}
                      className={`w-full text-left p-2 rounded-lg transition-colors flex flex-col space-y-0.5 ${
                        art.id === selectedArticleId
                          ? isDarkMode ? 'bg-slate-800 text-white border-l-2' : 'bg-blue-50 text-blue-900 border-l-2 border-blue-600'
                          : 'hover:bg-slate-100 dark:hover:bg-slate-900'
                      }`}
                    >
                      <div className="flex justify-between items-center text-[8px] opacity-70">
                        <span>{art.status}</span>
                        <span>ID: {art.id}</span>
                      </div>
                      <p className="truncate w-full text-xs font-sans">{art.title}</p>
                    </button>
                  ))}
              </div>
            )}

            {activeTab === 'planner' && (
              <div className="space-y-1">
                <p className="text-[10px] text-gray-400 mb-1 flex items-center"><Layers size={10} className="mr-1 text-[#2d6a4f]" /> 切换当前的长期书籍专栏大纲 :</p>
                {seriesList
                  .filter(s => s.name.toLowerCase().includes(globalSearchQuery.toLowerCase()))
                  .map((s) => (
                    <button
                      key={s.id}
                      onClick={() => {
                        onSelectSeries?.(s.id);
                        setIsOpen(false);
                      }}
                      className={`w-full text-left p-2 rounded-lg transition-colors flex flex-col space-y-0.5 ${
                        s.id === selectedSeriesId
                          ? isDarkMode ? 'bg-slate-800 text-white border-l-2' : 'bg-emerald-50 text-emerald-950 border-l-2 border-emerald-600'
                          : 'hover:bg-slate-100 dark:hover:bg-slate-900'
                      }`}
                    >
                      <p className="font-bold text-xs truncate font-sans">{s.name}</p>
                      <p className="text-[9px] text-gray-400 truncate mt-0.5">{s.description}</p>
                    </button>
                  ))}
              </div>
            )}

            {activeTab === 'rules' && (
              <div className="space-y-1 p-2 rounded-lg bg-indigo-50/20 dark:bg-indigo-950/20 border border-indigo-100 dark:border-indigo-900/30">
                <p className="text-[10px] text-indigo-400 mb-1 flex items-center font-bold font-sans"><Shield size={10} className="mr-1 text-indigo-500" /> 知识对齐策略与防写幻觉提示词控制规范 :</p>
                {(promptRules && promptRules.length > 0 ? promptRules : [
                  { id: '1', name: '技术文案防幻觉生成约束规范 v2.1', category: 'TitleGeneration', lastUpdated: 'Ready', status: 'Active' },
                  { id: '2', name: '高爆款软文 CTR 指标生成引子 v1.5', category: 'Research', lastUpdated: 'Ready', status: 'Active' }
                ] as PromptRule[])
                  .filter(r => r.name.toLowerCase().includes(globalSearchQuery.toLowerCase()))
                  .map((rule) => (
                    <div
                      key={rule.id}
                      onClick={() => {
                        setGlobalSearchQuery(rule.name);
                        setIsOpen(false);
                      }}
                      className="p-2 rounded hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer text-xs"
                    >
                      <p className="font-bold text-slate-850 dark:text-white truncate font-sans">{rule.name}</p>
                      <p className="text-[8px] text-gray-400 mt-1">种类: {rule.category} | 状态: {rule.status || 'Active'}</p>
                    </div>
                  ))}
              </div>
            )}

            {activeTab === 'assets' && (
              <div className="space-y-1 p-2 rounded-lg border bg-slate-50/20 dark:bg-slate-900/30">
                <span className="text-[10px] text-gray-400 flex items-center mb-1"><Radio size={10} className="mr-1 text-blue-500" /> 在资产库中搜索相关的封面/配图：</span>
                <p className="text-[10px] text-gray-400 p-2 italic">您可以直接在输入框键入“配图”、“微信表情”等，主画板资产会自动与搜索值联想对齐过滤。</p>
              </div>
            )}

            {activeTab === 'mcp' && (
              <div className="space-y-1 p-2 bg-slate-900 text-emerald-400 border border-slate-800 rounded-lg">
                <p className="text-[9px] text-gray-400 mb-1.5 flex items-center font-bold"><Terminal size={10} className="mr-1 text-emerald-500" /> 已安全挂载节点/服务端列表:</p>
                <div className="p-1 px-1.5 rounded bg-slate-950 font-mono text-[9px] text-slate-300">
                  ⚡ 1.[LocalHost 9005] MCP-GoogleCloudPlatform-System
                </div>
                <div className="p-1 px-1.5 rounded bg-slate-950 font-mono text-[9px] text-slate-300 mt-1">
                  ⚡ 2.[SSH Agent] Almagician-Database-Helper-Bridge
                </div>
              </div>
            )}

            {activeTab === 'analytics' && (
              <div className="space-y-1 text-slate-400 p-2">
                <p className="text-[10px] font-sans">大盘指数检索过滤器：您可以在顶部直接模糊输入「高频次」、「OOM」等，系统数据质量模型会自动对匹配分析进行着色筛选分析。</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

