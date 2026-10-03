import React, { useState, useEffect } from 'react';
import {
  Cpu,
  CheckCircle2,
  AlertCircle,
  Clock,
  Terminal,
  Activity,
  User,
  ExternalLink,
  ChevronRight,
  RefreshCw,
  Search,
  Filter,
  FileCode,
  Layers,
  ArrowUpRight,
  Database,
  SearchIcon,
  Play,
  X
} from 'lucide-react';
import { getMcpToolCalls, getMcpCapabilities, McpToolCall, McpCapabilities } from '../api/mcp';

interface McpTool {
  name: string;
  description: string;
  category: 'Research' | 'Drafting' | 'Format' | 'Publishing' | 'Audit';
  inputParameters: { name: string; type: string; required: boolean; desc: string }[];
  status: 'Ready' | 'Busy' | 'Maintenance';
}

interface ToolCallRecord {
  id: string;
  toolName: string;
  caller: string;
  associatedArticle?: { id: string; title: string };
  associatedRun: string;
  durationMs: number;
  status: 'SUCCESS' | 'WARNING' | 'FAILED' | 'CAPTCHA_BLOCKED';
  timestamp: string;
  inputArgs: string;
  outputSummary: string;
}

interface McpConsoleProps {
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
}

export default function McpConsole({ isDarkMode, accentColor }: McpConsoleProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterCategory, setFilterCategory] = useState<string>('ALL');
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);
  const [selectedDetailTool, setSelectedDetailTool] = useState<McpTool | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [mcpTab, setMcpTab] = useState<'tools' | 'history'>('tools');
  const [showStats, setShowStats] = useState(false);
  const [showTerminal, setShowTerminal] = useState(false);

  // Real API data state
  const [registeredTools, setRegisteredTools] = useState<McpTool[]>([]);
  const [recentCalls, setRecentCalls] = useState<ToolCallRecord[]>([]);
  const [loading, setLoading] = useState(true);

  // Fetch real data from backend
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        // Fetch MCP capabilities
        const caps = await getMcpCapabilities();
        if (caps?.tools) {
          const tools: McpTool[] = caps.tools.map((toolName: string) => ({
            name: toolName,
            description: guessDescription(toolName),
            category: guessCategory(toolName),
            inputParameters: [],
            status: 'Ready' as const,
          }));
          setRegisteredTools(tools);
        }

        // Fetch tool calls
        const calls = await getMcpToolCalls({ limit: 50 });
        if (calls) {
          const mapped: ToolCallRecord[] = calls.map((c: McpToolCall) => ({
            id: c.id,
            toolName: c.tool_name,
            caller: c.actor_label || 'System',
            associatedArticle: c.article_id ? { id: c.article_id, title: c.article_id } : undefined,
            associatedRun: c.run_id || c.job_id || '',
            durationMs: c.duration_ms || 0,
            status: mapStatus(c.status),
            timestamp: c.created_at?.replace('T', ' ').slice(0, 19) || '',
            inputArgs: c.request_json ? JSON.stringify(c.request_json) : '{}',
            outputSummary: c.response_json ? JSON.stringify(c.response_json) : '{}',
          }));
          setRecentCalls(mapped);
          if (mapped.length > 0 && !selectedCallId) {
            setSelectedCallId(mapped[0].id);
          }
        }
      } catch {
        // Fallback to minimal mock data if API fails
        setRegisteredTools([
          { name: 'start_article_flow', description: '初始化文章生产长跑道', category: 'Drafting', status: 'Ready', inputParameters: [] },
          { name: 'fetch_scientific_research', description: '拉取学术研究和文献', category: 'Research', status: 'Ready', inputParameters: [] },
          { name: 'run_quality_audit', description: '核心审校算法', category: 'Audit', status: 'Ready', inputParameters: [] },
        ]);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  function guessCategory(name: string): McpTool['category'] {
    const n = name.toLowerCase();
    if (n.includes('research') || n.includes('fetch') || n.includes('notion') || n.includes('topic')) return 'Research';
    if (n.includes('draft') || n.includes('article') || n.includes('outline') || n.includes('write')) return 'Drafting';
    if (n.includes('format') || n.includes('render') || n.includes('formula') || n.includes('svg')) return 'Format';
    if (n.includes('publish') || n.includes('platform') || n.includes('credential')) return 'Publishing';
    if (n.includes('audit') || n.includes('quality') || n.includes('review')) return 'Audit';
    return 'Drafting';
  }

  function guessDescription(name: string): string {
    const descMap: Record<string, string> = {
      'aimagician_capabilities': '查询系统能力清单与 MCP 协议版本',
      'aimagician_search_articles': '按关键词、状态或标签搜索文章',
      'aimagician_get_article': '获取单篇文章完整元数据',
      'aimagician_create_article': '创建新文章草稿',
      'aimagician_update_article': '更新文章元数据或内容',
      'aimagician_list_series': '获取所有连载专栏列表',
      'aimagician_get_series': '获取单个专栏详情与卷目',
      'aimagician_listPrompts': '获取所有 Prompt 规则',
      'aimagician_listPrompts_versions': '获取 Prompt 版本历史',
      'aimagician_list_platforms': '获取所有平台账号健康状态',
      'aimagician_check_platform': '检查单个平台会话健康',
      'aimagician_dispatch_publication': '向指定平台发布文章',
      'aimagician_list_topic_candidates': '获取待评估选题候选列表',
      'aimagician_adopt_topic': '采纳选题并创建文章草稿',
      'aimagician_collect_hotspots': '从外部源采集最新热点',
      'aimagician_list_assets': '获取文章封面与素材资产',
      'aimagician_trigger_quality_audit': '触发文章质量审计',
      'aimagician_get_quality_findings': '获取文章质量发现列表',
      'aimagician_list_tool_calls': '查询 MCP 工具调用历史',
      'aimagician_get_tool_call': '获取单次工具调用详情',
      'aimagician_get_run': '获取文章生产 Run 状态',
      'aimagician_list_jobs': '获取异步任务列表',
      'aimagician_get_job': '获取单个任务状态与日志',
      'aimagician_list_events': '查询系统事件日志',
      'aimagician_create_topic_candidate': '手动创建选题候选',
      'aimagician_ignore_topic': '忽略选题候选',
      'aimagician_generate_cover': '生成文章封面图片',
      'aimagician_render_markdown': '将 Markdown 渲染为 HTML',
      'aimagician_export_article': '导出文章为指定格式',
      'aimagician_list_versions': '获取文章版本历史',
      'aimagician_get_version': '获取单个版本详情',
      'aimagician_create_version': '创建文章新版本',
      'aimagician_search_notion': '搜索 Notion 数据库',
      'aimagician_sync_notion': '同步 Notion 页面到本地',
      'aimagician_push_notion': '推送本地文章到 Notion',
      'aimagician_list_credentials': '获取平台凭证列表',
      'aimagician_upload_credential': '上传平台凭证文件',
      'aimagician_delete_credential': '删除平台凭证',
      'aimagician_list_runs': '获取生产 Run 列表',
      'aimagician_cancel_run': '取消正在运行的任务',
      'aimagician_retry_job': '重试失败的任务',
      'aimagician_list_optimizer_tasks': '获取优化器任务列表',
      'aimagician_get_optimizer_task': '获取单个优化器任务详情',
      'aimagician_create_optimizer_task': '创建优化器任务',
      'aimagician_update_optimizer_task': '更新优化器任务',
      'aimagician_delete_optimizer_task': '删除优化器任务',
      'aimagician_get_dashboard_stats': '获取仪表盘统计数据',
      'aimagician_get_analytics': '获取分析数据',
      'aimagician_health_check': '系统健康检查',
      'aimagician_get_system_config': '获取系统配置',
      'aimagician_update_config': '更新系统配置',
    };
    return descMap[name] || name.replace(/_/g, ' ').replace(/aimagician /, '');
  }

  function mapStatus(s: string): ToolCallRecord['status'] {
    const m = s?.toUpperCase();
    if (m === 'SUCCESS' || m === 'COMPLETED') return 'SUCCESS';
    if (m === 'WARNING') return 'WARNING';
    if (m === 'BLOCKED' || m === 'CAPTCHA_BLOCKED') return 'CAPTCHA_BLOCKED';
    if (m === 'FAILED' || m === 'ERROR') return 'FAILED';
    return 'SUCCESS';
  }

  // Multi-color accents helper conforming to clean gray slate theme
  const getThemeAccentClass = (type: 'text' | 'bg' | 'border' | 'btn' | 'bg-hover') => {
    if (accentColor === 'blue') {
      if (type === 'text') return 'text-blue-600 dark:text-blue-400';
      if (type === 'bg') return 'bg-blue-600 text-white';
      if (type === 'border') return 'border-blue-500';
      if (type === 'bg-hover') return 'hover:bg-blue-700';
      return 'bg-blue-50 text-blue-800 dark:bg-blue-950/40 dark:text-blue-300';
    } else if (accentColor === 'green') {
      if (type === 'text') return 'text-emerald-600 dark:text-emerald-400';
      if (type === 'bg') return 'bg-emerald-600 text-white';
      if (type === 'border') return 'border-[#2d6a4f]';
      if (type === 'bg-hover') return 'hover:bg-emerald-700';
      return 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300';
    } else {
      if (type === 'text') return 'text-slate-600 dark:text-slate-300';
      if (type === 'bg') return 'bg-slate-700 text-white';
      if (type === 'border') return 'border-slate-500';
      if (type === 'bg-hover') return 'hover:bg-slate-800';
      return 'bg-slate-50 text-slate-800 dark:bg-slate-900/40 dark:text-slate-200';
    }
  };

  const pageSize = 20;
  const totalItems = recentCalls.length;
  const totalPages = Math.ceil(totalItems / pageSize);
  const startIndex = (currentPage - 1) * pageSize;
  const endIndex = startIndex + pageSize;
  const paginatedCalls = recentCalls.slice(startIndex, endIndex);
  const selectedCall = recentCalls.find(c => c.id === selectedCallId);

  const filteredTools = registeredTools.filter(t => {
    const matchesSearch = t.name.toLowerCase().includes(searchTerm.toLowerCase()) || 
                          t.description.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesCat = filterCategory === 'ALL' || t.category === filterCategory;
    return matchesSearch && matchesCat;
  });

  return (
    <div className={`flex-1 flex flex-col h-full min-h-0 overflow-hidden ${
      isDarkMode ? 'bg-slate-950 text-slate-100' : 'bg-slate-50 text-slate-800'
    }`}>

      {/* 仅在手机/移动端适配时展示的折叠控制行 (桌面端 lg-hidden 隐藏) */}
      <div className={`flex lg:hidden items-center justify-between px-4 py-2 border-b text-[10px] md:text-xs font-mono select-none shrink-0 ${
        isDarkMode ? 'bg-slate-900/60 border-slate-800' : 'bg-[#faf9f6] border-slate-200'
      }`}>
        <span className="text-gray-400 font-bold flex items-center space-x-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
          <span>📊 MCP 运行效能数据统计 (Performance Metrics)</span>
        </span>
        <button
          type="button"
          onClick={() => setShowStats(!showStats)}
          className="text-[10px] md:text-xs text-blue-500 hover:text-blue-600 font-bold cursor-pointer transition-all hover:underline"
        >
          {showStats ? '收起统计 ▴ Hide' : '展开统计 (QPS/时延/QoE) ▾ Expand'}
        </button>
      </div>

      <div className={`${showStats ? 'grid' : 'hidden lg:grid'} grid-cols-2 lg:grid-cols-4 gap-2.5 md:gap-4 p-3 md:p-6 border-b shrink-0 ${
        isDarkMode ? 'bg-slate-950/40 border-slate-800' : 'bg-white border-slate-200'
      }`}>
        <div className={`p-2.5 md:p-4 rounded-xl border ${isDarkMode ? 'border-slate-800 bg-slate-900/55' : 'bg-slate-50 border-slate-200'}`}>
          <div className="flex items-center space-x-2 text-slate-400 text-[9px] font-mono uppercase tracking-wider">
            <Cpu size={12} className="text-blue-500" />
            <span>可用 MCP Tools</span>
          </div>
          <p className="text-lg md:text-2xl font-bold font-mono mt-1">{registeredTools.length} 个</p>
          <p className="text-[9px] text-gray-500 mt-0.5">本地及云端规范工具清单</p>
        </div>

        <div className={`p-2.5 md:p-4 rounded-xl border ${isDarkMode ? 'border-slate-800 bg-slate-900/55' : 'bg-slate-50 border-slate-200'}`}>
          <div className="flex items-center space-x-2 text-slate-400 text-[9px] font-mono uppercase tracking-wider">
            <Activity size={12} className="text-emerald-500" />
            <span>最近 24h 调用</span>
          </div>
          <p className="text-lg md:text-2xl font-bold font-mono mt-1">{recentCalls.length} 次</p>
          <p className="text-[9px] text-gray-500 mt-0.5">运行成功率 {recentCalls.length > 0 ? Math.round(recentCalls.filter(c => c.status === 'SUCCESS').length / recentCalls.length * 100) : 0}%</p>
        </div>

        <div className={`p-2.5 md:p-4 rounded-xl border ${isDarkMode ? 'border-slate-800 bg-slate-900/55' : 'bg-slate-50 border-slate-200'}`}>
          <div className="flex items-center space-x-2 text-slate-400 text-[9px] font-mono uppercase tracking-wider">
            <Clock size={12} className="text-purple-500" />
            <span>平均响应耗时</span>
          </div>
          <p className="text-lg md:text-2xl font-bold font-mono mt-1 text-purple-600 dark:text-purple-400">{recentCalls.length > 0 ? Math.round(recentCalls.reduce((acc, c) => acc + (c.durationMs || 0), 0) / recentCalls.length) : 0} ms</p>
          <p className="text-[9px] text-gray-500 mt-0.5">Spanner 及 API 混合耗时</p>
        </div>

        <div className={`p-2.5 md:p-4 rounded-xl border ${isDarkMode ? 'border-slate-800 bg-slate-900/55' : 'bg-slate-50 border-slate-200'}`}>
          <div className="flex items-center space-x-2 text-slate-400 text-[9px] font-mono uppercase tracking-wider">
            <Terminal size={12} className="text-amber-500" />
            <span>健康状态 (Health)</span>
          </div>
          <p className="text-lg md:text-2xl font-bold font-mono mt-1 text-emerald-500 font-extrabold animate-pulse">HEALTHY</p>
          <p className="text-[9px] text-gray-500 mt-0.5">服务就绪 Ready 状态</p>
        </div>
      </div>

      {/* Mobile Tab Navigator (Hidden on Desktop) */}
      <div className={`flex lg:hidden border-b p-3 space-x-2 select-none shrink-0 ${
        isDarkMode ? 'bg-slate-900 border-slate-800' : 'bg-slate-100 border-slate-200'
      }`}>
        <button
          type="button"
          onClick={() => setMcpTab('tools')}
          className={`flex-1 py-2 text-xs font-mono font-bold rounded-lg transition-all flex items-center justify-center space-x-1.5 ${
            mcpTab === 'tools'
              ? isDarkMode
                ? 'bg-blue-600 text-white shadow-md'
                : 'bg-white text-blue-600 border border-blue-100 shadow-sm'
              : isDarkMode
              ? 'bg-slate-950 text-slate-400 hover:text-white'
              : 'bg-transparent text-slate-600 hover:bg-white/50'
          }`}
        >
          <span>🛠️ 可用工具库 ({registeredTools.length})</span>
        </button>
        <button
          type="button"
          onClick={() => setMcpTab('history')}
          className={`flex-1 py-1.5 text-xs font-mono font-bold rounded-lg transition-all flex items-center justify-center space-x-1.5 ${
            mcpTab === 'history'
              ? isDarkMode
                ? 'bg-blue-600 text-white shadow-md'
                : 'bg-white text-blue-600 border border-blue-100 shadow-sm'
              : isDarkMode
              ? 'bg-slate-950 text-slate-400 hover:text-white'
              : 'bg-transparent text-slate-600 hover:bg-white/50'
          }`}
        >
          <span>⏳ 调用追踪历史 ({recentCalls.length})</span>
        </button>
      </div>

      {/* Main Workspace Frame */}
      <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-hidden">
        {/* Left Side: Registered tools list */}
        <div className={`${mcpTab === 'tools' ? 'flex animate-fade-in' : 'hidden'} lg:flex w-full lg:w-96 border-b lg:border-b-0 lg:border-r flex-col h-full lg:h-full shrink-0 overflow-hidden ${
          isDarkMode ? 'bg-slate-950 border-slate-800' : 'bg-white border-slate-200'
        }`}>
          {/* List Toolbar search */}
          <div className="p-4 border-b space-y-3 shrink-0">
            <h3 className="font-bold text-[10px] font-mono text-gray-400 tracking-wider uppercase">
              🛠️ 协议工具清单 (Tool schemas)
            </h3>

            <div className="text-[10px] font-mono text-gray-500 pb-2 border-b border-dashed dark:border-slate-800">
              ⚡ MCP SDK v1.4.1 (Ready)
            </div>

            <div className="relative">
              <Search className="absolute left-2.5 top-2 text-gray-400" size={13} />
              <input
                type="text"
                placeholder="搜索注册工具名或描述..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className={`w-full pl-8 pr-3 py-1.5 text-[11px] rounded border focus:outline-none focus:ring-1 focus:border-blue-500 ${
                  isDarkMode ? 'bg-slate-900 border-slate-800 text-slate-100 font-mono' : 'bg-slate-50 border-slate-200 text-slate-800 font-mono'
                }`}
              />
            </div>

            <div className="flex flex-wrap gap-1.5">
              {['ALL', 'Drafting', 'Research', 'Format', 'Audit'].map((cat) => (
                <button
                  key={cat}
                  onClick={() => setFilterCategory(cat)}
                  className={`px-2 py-0.5 text-[9px] font-mono font-medium rounded transition-all ${
                    filterCategory === cat
                      ? getThemeAccentClass('bg')
                      : isDarkMode
                      ? 'bg-slate-900 text-slate-400 hover:text-white'
                      : 'bg-slate-100 text-slate-600 border border-slate-200 hover:bg-slate-200'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          {/* Registered tools render */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3.5">
            {filteredTools.map((tool) => (
              <div
                key={tool.name}
                className={`p-3.5 rounded-lg border transition-all hover:scale-[1.01] relative hover:z-50 ${
                  isDarkMode ? 'bg-slate-900/40 border-slate-800' : 'bg-slate-50 border-slate-200'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-xs text-blue-500 dark:text-blue-400">
                    {tool.name}
                  </span>
                  <span className={`px-1.5 py-0.2 rounded text-[8px] font-bold font-mono uppercase ${
                    tool.status === 'Ready'
                      ? 'bg-emerald-100 text-emerald-800'
                      : 'bg-amber-100 text-amber-800'
                  }`}>
                    {tool.status}
                  </span>
                </div>

                <p className="text-[10px] text-gray-500 mt-1.5 leading-relaxed font-sans" title={tool.description}>
                  {tool.description.length > 55 ? `${tool.description.slice(0, 55)}...` : tool.description}
                </p>

                {/* Compact review triggers */}
                <div className="mt-3 flex justify-between items-center text-[9.5px] font-mono border-t border-dashed border-slate-250 dark:border-slate-800 pt-2">
                  <span className="text-slate-400">参数: {tool.inputParameters.length} 项</span>
                  
                  <div className="relative group">
                    <button
                      type="button"
                      onClick={() => setSelectedDetailTool(tool)}
                      className="text-amber-500 hover:text-amber-600 font-bold hover:underline flex items-center gap-0.5"
                    >
                      🔍 点击查看参数详情
                    </button>

                    {/* Hover Parameters Preview Tooltip / Popover card */}
                    <div className="hidden md:block absolute right-0 top-full mt-2 w-76 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-xl p-4 z-50 text-left pointer-events-none opacity-0 group-hover:opacity-100 group-hover:pointer-events-auto transition-opacity duration-200 ease-out font-sans">
                      <div className="flex items-center justify-between border-b pb-1.5 mb-2 border-slate-100 dark:border-slate-800">
                        <span className="font-mono font-bold text-xs text-amber-500 flex items-center gap-1">
                          ⚡ {tool.name} 参数表
                        </span>
                        <span className="text-[10px] text-gray-400 font-mono">
                          共 {tool.inputParameters.length} 项
                        </span>
                      </div>

                      {tool.inputParameters.length === 0 ? (
                        <p className="text-[10px] text-gray-400 italic py-1">此工具无入参要求。</p>
                      ) : (
                        <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                          {tool.inputParameters.map((param, pIdx) => (
                            <div key={pIdx} className="text-[10px] leading-relaxed border-b border-slate-100/60 dark:border-slate-800/40 pb-1.5 last:border-0 last:pb-0">
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-mono font-bold text-slate-800 dark:text-slate-200 truncate">
                                  {param.name}
                                </span>
                                <div className="flex items-center space-x-1 font-mono text-[8.5px] shrink-0">
                                  <span className="px-1 bg-slate-100 dark:bg-slate-800 text-gray-550 rounded">
                                    {param.type}
                                  </span>
                                  {param.required && (
                                    <span className="px-1 bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-400 rounded-xs font-bold font-sans">
                                      必填
                                    </span>
                                  )}
                                </div>
                              </div>
                              <p className="text-gray-500 dark:text-gray-400 mt-0.5 text-[9.5px]">
                                {param.desc}
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {/* Triangle accent anchor pointing up */}
                      <div className="absolute bottom-full right-4 w-3 h-3 bg-white dark:bg-slate-900 border-l border-t border-slate-200 dark:border-slate-800 transform rotate-45 translate-y-1.5 shadow-xs" />
                    </div>
                  </div>

                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Middle and Right: Trace log viewer & details details */}
        <div className={`${mcpTab === 'history' ? 'flex animate-fade-in' : 'hidden'} lg:flex flex-1 flex-col min-h-0 h-full lg:h-full bg-stone-50 dark:bg-slate-950/20 overflow-hidden`}>
          {/* Top of right: Tool calls table */}
          <div className="flex-1 p-4 md:p-6 flex flex-col min-h-0 space-y-3 md:space-y-4 overflow-y-auto lg:overflow-hidden custom-scrollbar">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 shrink-0">
              <h3 className="font-bold text-[10px] font-mono text-gray-400 tracking-wider uppercase">
                ⏳ 最近调用追踪记录 (Recent tool call receipts)
              </h3>

              {/* Micro Pagination Controls in Top Right */}
              {totalPages > 1 && (
                <div className="flex items-center space-x-1.5 select-none text-[10px] font-mono shrink-0">
                  <span className="text-gray-400 text-[9.5px] mr-1 hidden md:inline">
                    显示 <span className="text-slate-700 dark:text-slate-300 font-semibold">{startIndex + 1}</span>-{Math.min(endIndex, totalItems)} / <span className="text-blue-500 font-bold">{totalItems}</span> 条记录
                  </span>
                  
                  <button
                    onClick={() => setCurrentPage(1)}
                    disabled={currentPage === 1}
                    className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase transition-colors border ${
                      currentPage === 1
                        ? 'opacity-30 border-transparent text-gray-500 cursor-not-allowed'
                        : isDarkMode
                        ? 'border-slate-800 hover:border-slate-700 text-slate-300 bg-slate-900/40 hover:bg-slate-900'
                        : 'border-slate-200 hover:bg-slate-100 text-slate-700'
                    }`}
                  >
                    首页
                  </button>
                  <button
                    onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                    disabled={currentPage === 1}
                    className={`px-1 py-0.5 rounded text-[9px] font-bold transition-colors border ${
                      currentPage === 1
                        ? 'opacity-30 border-transparent text-gray-550 cursor-not-allowed'
                        : isDarkMode
                        ? 'border-slate-800 hover:border-slate-700 text-slate-300 bg-slate-900/40 hover:bg-slate-900'
                        : 'border-slate-200 hover:bg-slate-100 text-slate-700'
                    }`}
                  >
                    ◀
                  </button>
                  
                  <div className="flex items-center space-x-0.5">
                    {Array.from({ length: totalPages }).map((_, idx) => {
                      const pageNum = idx + 1;
                      const isCurrent = pageNum === currentPage;
                      return (
                        <button
                          key={pageNum}
                          onClick={() => setCurrentPage(pageNum)}
                          className={`w-5 h-5 flex items-center justify-center rounded text-[10px] font-bold transition-all ${
                            isCurrent
                              ? getThemeAccentClass('bg')
                              : isDarkMode
                              ? 'text-slate-450 hover:bg-slate-900 hover:text-white'
                              : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 border border-transparent hover:border-slate-200'
                          }`}
                        >
                          {pageNum}
                        </button>
                      );
                    })}
                  </div>

                  <button
                    onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                    disabled={currentPage === totalPages}
                    className={`px-1 py-0.5 rounded text-[9px] font-bold transition-colors border ${
                      currentPage === totalPages
                        ? 'opacity-30 border-transparent text-gray-555 cursor-not-allowed'
                        : isDarkMode
                        ? 'border-slate-800 hover:border-slate-700 text-slate-300 bg-slate-900/40 hover:bg-slate-900'
                        : 'border-slate-200 hover:bg-slate-100 text-slate-700'
                    }`}
                  >
                    ▶
                  </button>
                  <button
                    onClick={() => setCurrentPage(totalPages)}
                    disabled={currentPage === totalPages}
                    className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase transition-colors border ${
                      currentPage === totalPages
                        ? 'opacity-30 border-transparent text-gray-550 cursor-not-allowed'
                        : isDarkMode
                        ? 'border-slate-800 hover:border-slate-700 text-slate-300 bg-slate-900/40 hover:bg-slate-900'
                        : 'border-slate-200 hover:bg-slate-100 text-slate-700'
                    }`}
                  >
                    尾页
                  </button>
                </div>
              )}
            </div>

            <div className={`border rounded-xl flex-1 overflow-auto custom-scrollbar min-h-[120px] max-h-[220px] lg:max-h-[380px] ${
              isDarkMode ? 'border-slate-800 bg-slate-900/35' : 'bg-white border-slate-200'
            }`}>
              <table className="w-full min-w-[720px] text-left text-xs font-sans table-auto">
                <thead className="sticky top-0 z-10">
                  <tr className={`border-b font-mono text-[10px] text-slate-400 ${
                    isDarkMode ? 'border-slate-850 bg-slate-950' : 'bg-slate-100'
                  }`}>
                    <th className="p-3">事件时间. Timestamp</th>
                    <th className="p-3">接口工具. Tool</th>
                    <th className="p-3">调用调度源. Caller</th>
                    <th className="p-3">关联大作业. Run/Job</th>
                    <th className="p-3 text-right">时间耗时</th>
                    <th className="p-3 text-right">链路状态</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-850">
                  {paginatedCalls.map((call) => {
                    const isSelected = call.id === selectedCallId;
                    let statusLabel = 'bg-stone-100 text-stone-600';
                    if (call.status === 'SUCCESS') statusLabel = 'bg-emerald-100 text-emerald-800';
                    else if (call.status === 'WARNING') statusLabel = 'bg-amber-100 text-amber-800';
                    else if (call.status === 'FAILED') statusLabel = 'bg-rose-100 text-rose-800';
                    else if (call.status === 'CAPTCHA_BLOCKED') statusLabel = 'bg-orange-100 text-orange-850 animate-pulse';

                    return (
                      <tr
                        key={call.id}
                        onClick={() => setSelectedCallId(call.id)}
                        className={`cursor-pointer transition-colors ${
                          isSelected
                            ? isDarkMode
                              ? 'bg-slate-900'
                              : 'bg-blue-50'
                            : isDarkMode
                            ? 'hover:bg-slate-900/40'
                            : 'hover:bg-slate-50'
                        }`}
                      >
                        <td className="p-3 font-mono text-[10px] whitespace-nowrap text-gray-450">{call.timestamp}</td>
                        <td className="p-3 font-mono font-bold text-slate-800 dark:text-silver-300">{call.toolName}</td>
                        <td className="p-3 text-slate-500 font-mono text-[10px]">{call.caller}</td>
                        <td className="p-3 text-slate-500 max-w-40 truncate" title={call.associatedArticle?.title || call.associatedRun}>
                          {call.associatedArticle ? `art: ${call.associatedArticle.id}` : `run: ${call.associatedRun.slice(0, 10)}...`}
                        </td>
                        <td className="p-3 text-right font-mono text-[10px] text-gray-500">{call.durationMs}ms</td>
                        <td className="p-3 text-right whitespace-nowrap">
                          <span className={`px-2 py-0.2 rounded text-[8px] font-mono font-bold whitespace-nowrap ${statusLabel}`}>
                            {call.status}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* JSON argument and output inspector */}
            {selectedCall && (
              <div className="flex flex-col space-y-1.5 shrink-0 bg-stone-100/50 dark:bg-slate-900/10 p-2.5 rounded-xl border border-slate-200/60 dark:border-slate-800/40 max-h-[280px] md:max-h-none overflow-y-auto custom-scrollbar">
                <div className="flex items-center justify-between border-b pb-1.5 mb-1 select-none">
                  <span className="text-[10px] font-mono leading-none font-bold text-blue-500 dark:text-blue-400 flex items-center">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-500 mr-1.5 animate-pulse"></span>
                    🔍 正在查看调用详情: <span className="underline ml-1 font-bold">{selectedCall.toolName}</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => setSelectedCallId(null)}
                    className="text-[10px] font-mono text-rose-500 hover:text-rose-600 font-bold transition-all hover:underline cursor-pointer"
                  >
                    关闭详情 ✕ Close
                  </button>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {/* Inputs card */}
                  <div className={`p-2.5 md:p-3 rounded-lg border flex flex-col min-h-[90px] max-h-[140px] lg:min-h-[130px] lg:max-h-[200px] ${
                    isDarkMode ? 'border-slate-800 bg-slate-900/60' : 'bg-white border-slate-200'
                  }`}>
                    <h4 className="font-bold text-[9px] font-mono text-gray-400 uppercase mb-1.5 tracking-wider">
                      👉 调用入参 (Input arguments)
                    </h4>
                    <pre className={`p-2 font-mono text-[9.5px] rounded flex-1 overflow-y-auto leading-normal whitespace-pre-wrap break-all break-words border custom-scrollbar ${
                      isDarkMode ? 'bg-slate-950 text-cyan-400 border-slate-900' : 'bg-slate-50 text-cyan-855 border-slate-150'
                    }`}>
                      {selectedCall.inputArgs}
                    </pre>
                  </div>

                  {/* Response card */}
                  <div className={`p-2.5 md:p-3 rounded-lg border flex flex-col min-h-[90px] max-h-[140px] lg:min-h-[130px] lg:max-h-[200px] ${
                    isDarkMode ? 'border-slate-800 bg-slate-900/60' : 'bg-white border-slate-200'
                  }`}>
                    <h4 className="font-bold text-[9px] font-mono text-gray-400 uppercase mb-1.5 tracking-wider">
                      👈 调用结果/摘要 (Response result)
                    </h4>
                    <pre className={`p-2 font-mono text-[9.5px] rounded flex-1 overflow-y-auto leading-normal whitespace-pre-wrap break-all break-words border custom-scrollbar ${
                      isDarkMode ? 'bg-slate-950 text-green-400 border-slate-900' : 'bg-slate-50 text-green-800 border-slate-150'
                    }`}>
                      {selectedCall.outputSummary}
                    </pre>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Bottom terminal logs output stream */}
          <div className={`border-t shrink-0 flex flex-col font-mono text-[10px] transition-all duration-200 overflow-hidden ${
            showTerminal ? 'h-40 md:h-52' : 'h-10 md:h-11'
          } ${
            isDarkMode ? 'bg-slate-950 border-slate-900 text-slate-400' : 'bg-slate-50 border-slate-200 text-slate-700'
          }`}>
            <div 
              onClick={() => setShowTerminal(!showTerminal)}
              className={`flex items-center justify-between px-3 md:px-4 py-2 shrink-0 select-none cursor-pointer border-b ${
                isDarkMode ? 'border-slate-900/80 bg-slate-900/20' : 'border-slate-200 bg-[#fbfbfa]'
              }`}
            >
              <span className={`flex items-center text-[9px] font-bold tracking-wider ${
                isDarkMode ? 'text-cyan-400' : 'text-cyan-800'
              }`}>
                <Terminal size={11} className="mr-1.5" />
                STDOUT/STDERR STREAM FROM MCP DEAMON (DAEMON v3.2) {showTerminal ? '▾' : '▸'}
              </span>
              <div className="flex items-center space-x-2">
                <span className="text-[9px] text-slate-500 hidden sm:inline">12 TCP Socket | Buffer 4kb</span>
                <span className="text-blue-500 font-bold hover:underline">
                  {showTerminal ? '收起日志 [-]' : '展开日志 [+]'}
                </span>
              </div>
            </div>
            {showTerminal && (
              <div className="flex-1 overflow-y-auto p-3 md:p-4 pt-2 space-y-1">
                <p>● [2026-05-31 11:42:00] -- [mcp-core] -- Standard Server bootstrapping complete using TypeScript runtime.</p>
                <p className="text-green-400">✔ [2026-05-31 11:42:01] -- [mcp-router] -- Received start_article_flow. Allocated draft article ID: art-wb-02.</p>
                <p>● [2026-05-31 11:42:01] -- [sqlite-state] -- Transaction state persistent commit on primary database context. (14ms)</p>
                <p className="text-cyan-400">➔ [2026-05-31 11:43:08] -- [mcp-proxy] -- Requesting Scholar evidence maps keywords="Spanner consistency 2PC deadlock".</p>
                <p className="text-green-500">✔ [2026-05-31 11:43:10] -- [mcp-router] -- Saved 4 items of high-reliability evidence into evidence db.</p>
                <p className="text-amber-500">⚠ [2026-05-31 11:00:00] -- [platform-juejin] -- Cookie expiration warning: Response 302 landing bypass to check session captcha.</p>
                <p className="text-rose-500">✖ [2026-05-31 11:00:00] -- [mcp-core] -- error code: NOTION_SESSION_EXPIRED. Halting further Notion page scrapes.</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* MCP Tool Detailed Specification Overlay Modal */}
      {selectedDetailTool && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/70 backdrop-blur-sm animate-fade-in">
          <div className={`w-full max-w-xl rounded-2xl border overflow-hidden flex flex-col max-h-[85vh] shadow-2xl animate-zoom-in ${
            isDarkMode ? 'bg-[#0b101d] border-slate-800 text-white' : 'bg-white border-slate-200 text-slate-800'
          }`}>
            <div className={`p-4 border-b flex items-center justify-between ${
              isDarkMode ? 'border-slate-800 bg-[#070b13]' : 'border-slate-100 bg-[#fafafa]'
            }`}>
              <div className="flex items-center space-x-2 text-left">
                <div className="p-1.5 rounded-lg bg-blue-500/10 text-blue-500">
                  <Cpu size={15} className="animate-spin duration-1000" />
                </div>
                <div>
                  <h4 className="font-bold text-sm leading-tight">MCP Protocol Tool Specification Detail</h4>
                  <p className="text-[10px] text-gray-500 font-mono">
                    schema: mcp://{selectedDetailTool.name}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSelectedDetailTool(null)}
                className="p-1.5 rounded-lg hover:bg-slate-500/10 transition-colors"
              >
                <X size={15} />
              </button>
            </div>

            <div className="p-5 overflow-y-auto space-y-4 text-left text-xs custom-scrollbar">
              <div className="space-y-1">
                <span className="text-[10px] font-mono text-gray-405 uppercase tracking-wider block">工具名称 & 运行时状态:</span>
                <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-955 border border-slate-800">
                  <span className="font-mono font-bold text-[12px] text-blue-400">
                    {selectedDetailTool.name}
                  </span>
                  <span className={`px-2 py-0.5 rounded text-[9px] font-bold font-mono uppercase ${
                    selectedDetailTool.status === 'Ready'
                      ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20'
                      : 'bg-amber-500/15 text-amber-400 border border-amber-500/20'
                  }`}>
                    {selectedDetailTool.status}
                  </span>
                </div>
              </div>

              <div className="space-y-1">
                <span className="text-[10px] font-mono text-gray-405 uppercase tracking-wider block">工具协议描述/业务功能:</span>
                <div className={`p-3 rounded-xl border leading-relaxed ${
                  isDarkMode ? 'bg-slate-950 border-slate-800 text-slate-300' : 'bg-slate-50 border-slate-205 text-slate-700'
                }`}>
                  {selectedDetailTool.description}
                </div>
              </div>

              <div className="space-y-2">
                <span className="text-[10px] font-mono text-gray-405 uppercase tracking-wider block">
                  输入规范参数表 (Schema Input Parameters) [{selectedDetailTool.inputParameters.length}项]:
                </span>
                
                {selectedDetailTool.inputParameters.length === 0 ? (
                  <p className="font-mono text-gray-500 italic p-3 text-center border rounded-xl border-dashed">
                    无输入参数约束 (No parameters required).
                  </p>
                ) : (
                  <div className="space-y-2">
                    {selectedDetailTool.inputParameters.map((param) => (
                      <div 
                        key={param.name} 
                        className={`p-3 rounded-xl border flex flex-col gap-1 ${
                          isDarkMode ? 'bg-slate-950 border-slate-800/80' : 'bg-white border-slate-150'
                        }`}
                      >
                        <div className="flex justify-between items-center">
                          <span className="font-mono font-bold text-slate-805 dark:text-slate-200 text-[11px] flex items-center">
                            {param.name}
                            {param.required && <span className="text-red-500 ml-1 font-mono text-xs" title="此项必填">*</span>}
                          </span>
                          <span className="text-[9px] font-mono bg-blue-500/10 text-blue-400 p-0.5 px-2 rounded-full font-semibold">
                            {param.type}
                          </span>
                        </div>
                        <p className="text-[10px] text-gray-400 leading-relaxed font-sans">{param.desc}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className={`p-4 border-t flex justify-end ${
              isDarkMode ? 'border-slate-800 bg-[#070b13]' : 'border-slate-105 bg-[#fafafa]'
            }`}>
              <button
                type="button"
                onClick={() => setSelectedDetailTool(null)}
                className="px-5 py-1.5 text-xs font-mono font-medium rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition-colors"
              >
                确定 Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
