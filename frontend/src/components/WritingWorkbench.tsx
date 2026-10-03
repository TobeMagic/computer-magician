import React, { useState, useEffect, useRef } from 'react';
import {
  Sparkles,
  HelpCircle,
  FileText,
  Search,
  CheckCircle,
  AlertCircle,
  Clock,
  Code,
  Image as ImageIcon,
  ArrowRight,
  Cpu,
  Bookmark,
  RefreshCw,
  Lock,
  Unlock,
  ChevronRight,
  Shield,
  Send,
  Plus,
  Trash2,
  BookOpen,
  CheckSquare,
  FileCode,
  AlertTriangle,
  Flame,
  Terminal,
  Database
} from 'lucide-react';
import { Article, Series, PlatformCredential } from '../types';

// Import modular panels
import TopicSelection, { CandidateTopic } from './TopicSelection';
import SpecsConfirmation from './SpecsConfirmation';
import ActivePipeline from './ActivePipeline';
import PlanningBoard from './PlanningBoard';
import VersionConsole from './VersionConsole';
import CoverWorkshop from './CoverWorkshop';
import PublishMatrix from './PublishMatrix';
import PromptOpsTracer from './PromptOpsTracer';

interface WritingWorkbenchProps {
  articles: Article[];
  setArticles: React.Dispatch<React.SetStateAction<Article[]>>;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  onSetTab?: (tab: string) => void;
  credentials?: PlatformCredential[];
  setCredentials?: React.Dispatch<React.SetStateAction<PlatformCredential[]>>;
  selectedArticleId?: string;
  onSelectArticle?: (id: string) => void;
  selectedSeriesId?: string;
  onSelectSeries?: (id: string) => void;
  seriesList?: Series[];
  initialSubTab?: string;
  onSetSubTab?: (subTab: string) => void;
}

const initialCandidates: CandidateTopic[] = [
  {
    id: 'cand-1',
    title: 'DeepSeek-R1 蒸馏小模型在单卡容器边缘侧高并发长连接网关性能雪崩与极限调优',
    source: 'arXiv.org System research',
    heatScore: 98,
    ctrPrediction: '3.8% - 5.2% CTR',
    recommendedWords: 4500,
    recommendedStyle: '第一人称视角实践复盘，注重一手源码分析与指标',
    recommendedSeries: 'AI Agent 高性能架构原理与研发实战',
    description: '深入容器层级及 FP16 分布式并行推理，在极高并发长连接网关中两阶段提交影子锁规避雪崩。',
    status: '待评估',
  },
  {
    id: 'cand-2',
    title: '美团线上大规模 GraphRAG 经验复刻：如何用双路交叉注意力重排器极致剪枝避免内存崩溃',
    source: 'Juejin Tech Blog Radar',
    heatScore: 94,
    ctrPrediction: '2.8% - 3.9% CTR',
    recommendedWords: 4800,
    recommendedStyle: '学术论文质感硬核提炼，辅以工程代码',
    recommendedSeries: 'LLM 与 RAG 工业级调优内幕',
    description: '阐述图形拓扑在长召回文本中的内存分配优化，使用静态平铺底层缓冲并将超长重排进行折叠。',
    status: '已采用',
  },
  {
    id: 'cand-3',
    title: 'Redis Pub/Sub 订阅泄露遇上 K8s HPA：大模型流式 SSE 网关高并发下的 Event Loop 背压控流模型',
    source: 'Production SRE Alert Logs',
    heatScore: 91,
    ctrPrediction: '3.1% - 4.5% CTR',
    recommendedWords: 3500,
    recommendedStyle: '第一人称视角实践复盘，拒绝废话',
    recommendedSeries: 'AI Agent 高性能架构原理与研发实战',
    description: '下级通道网速太慢引发 SSE 连接挂载，字符串拼接造成 V8 堆内存严重碎片化与 Event Loop 积压。',
    status: '待评估',
  }
];

export default function WritingWorkbench({
  articles,
  setArticles,
  isDarkMode,
  accentColor,
  onSetTab,
  credentials = [],
  setCredentials,
  selectedArticleId,
  onSelectArticle,
  selectedSeriesId,
  onSelectSeries,
  seriesList = [],
  initialSubTab,
  onSetSubTab
}: WritingWorkbenchProps) {
  // Candidate pool local states
  const [hotspotsList, setHotspotsList] = useState<CandidateTopic[]>(initialCandidates);

  // Selector controls
  const [selectedArtId, setSelectedArtId] = useState<string>(selectedArticleId || articles[0]?.id || '');
  const [activeTab, setActiveTabInternal] = useState<'confirm' | 'research' | 'prewrite' | 'body' | 'assets' | 'quality' | 'publish' | 'prompts'>((initialSubTab as any) || 'confirm');

  const setActiveTab = (tab: 'confirm' | 'research' | 'prewrite' | 'body' | 'assets' | 'quality' | 'publish' | 'prompts') => {
    setActiveTabInternal(tab);
    onSetSubTab?.(tab);
  };

  useEffect(() => {
    if (initialSubTab && initialSubTab !== activeTab) {
      setActiveTabInternal(initialSubTab as any);
    }
  }, [initialSubTab]);

  // Search filter options
  const [searchQuery, setSearchQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const searchDropdownRef = useRef<HTMLDivElement>(null);

  // Dropdown outside click resolver
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (searchDropdownRef.current && !searchDropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const filteredOptions = articles.filter(art => 
    art.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    art.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
    art.status.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Creation placeholder states
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newType, setNewType] = useState('技术八股');
  const [newSeries, setNewSeries] = useState('AI Agent 高性能架构原理与研发实战');

  // Console active trace logs simulation
  const [logs, setLogs] = useState<string[]>([
    '● [12:00:15] [AImagician Workspace Core] 启动运行环境. 连接节点 OK.',
    '● [12:00:18] [Loader] 挂载真相数据底层模型共计 4 篇技术连载大底稿.',
    '● [12:01:02] [Audit] 大纲一致性校验校验器分析就绪... [Active].'
  ]);

  const addLog = (msg: string) => {
    const time = new Date().toTimeString().split(' ')[0];
    setLogs(prev => [`● [${time}] ${msg}`, ...prev]);
  };

  const currentArticle = articles.find(a => a.id === selectedArtId) || articles[0];

  // Sync prop changes
  useEffect(() => {
    if (selectedArticleId && selectedArticleId !== selectedArtId) {
      setSelectedArtId(selectedArticleId);
    }
  }, [selectedArticleId]);

  // Auto fallback sync
  useEffect(() => {
    if (articles.length > 0 && !selectedArtId) {
      setSelectedArtId(articles[0].id);
      onSelectArticle?.(articles[0].id);
    }
  }, [articles, selectedArtId]);

  const getThemeAccentClass = (type: 'bg' | 'text' | 'border' | 'badge' | 'ring' | 'card') => {
    if (accentColor === 'green') {
      if (type === 'bg') return 'bg-emerald-600 hover:bg-emerald-700 text-white';
      if (type === 'text') return 'text-emerald-600 dark:text-emerald-400';
      if (type === 'border') return 'border-emerald-500/30';
      if (type === 'badge') return 'bg-emerald-100/80 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300';
      if (type === 'ring') return 'focus:ring-emerald-500';
      return 'bg-emerald-500/5 border-emerald-500/20 text-emerald-600';
    }
    if (accentColor === 'brown') {
      if (type === 'bg') return 'bg-amber-700 hover:bg-amber-800 text-white';
      if (type === 'text') return 'text-amber-700 dark:text-amber-400';
      if (type === 'border') return 'border-amber-600/30';
      if (type === 'badge') return 'bg-amber-100/80 text-amber-905 dark:bg-amber-955/50 dark:text-amber-300';
      if (type === 'ring') return 'focus:ring-amber-500';
      return 'bg-amber-500/5 border-amber-500/20 text-amber-600';
    }
    // Blue default
    if (type === 'bg') return 'bg-blue-600 hover:bg-blue-700 text-white';
    if (type === 'text') return 'text-blue-500 dark:text-blue-400';
    if (type === 'border') return 'border-blue-500/30';
    if (type === 'badge') return 'bg-blue-100 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300';
    if (type === 'ring') return 'focus:ring-blue-500';
    return 'bg-blue-500/5 border-blue-500/20 text-blue-555';
  };

  const updateActiveArticle = (fields: Partial<Article>) => {
    setArticles(prev => prev.map(art => art.id === selectedArtId ? { ...art, ...fields } : art));
  };

  // 2. Direct creation action
  const handleCreateArticle = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;

    const newId = `art-${Date.now()}`;
    const draftArt: Article = {
      id: newId,
      title: newTitle,
      seriesName: newSeries,
      status: '待写作',
      type: newType,
      createdAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
      updatedAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
      abstract: '待放行。',
      targetWords: 4000,
      actualWords: 0,
      writingStyle: '一手前沿代码解析加故障火焰剖析风格。排拒废话、AI套话！',
      hookScene: '暂无钩子。',
      outline: [
        { id: 'sec-1', title: '一、故障回溯现场', subtopics: ['事件循环阻塞与写溢出'] },
        { id: 'sec-2', title: '二、多路复用背控源码实现', subtopics: ['流式 drain 回落控制'] }
      ],
      titleCandidates: [
        { text: `${newTitle}：底层理论与高可用生存指南`, style: '专业流', hookDepth: '5星', clicksEstimate: '2.5% CTR' }
      ],
      publications: [
        { platformId: 'hexo', platformName: 'Hexo (自建博客)', status: 'Draft', draftId: `${newId}-hexo` },
        { platformId: 'wechat', platformName: '微信公众号', status: 'Draft', draftId: `${newId}-wechat` }
      ],
      qualityIssues: [
        { id: `qi-added-${newId}`, category: 'Structure', severity: 'Block', description: '新立项：目录树尚未在管理员端签署放行。', attributedModule: '人工门卡门禁', fixed: false }
      ]
    };

    setArticles(prev => [draftArt, ...prev]);
    setSelectedArtId(newId);
    setNewTitle('');
    setIsCreatingNew(false);
    setActiveTab('confirm');
    addLog(`✓ [自拟选题] 成功向全局 Draft 库投递新选题，并触发一阶段规格规格设定。`);
  };

  const handleDeleteArticle = (artId: string) => {
    if (articles.length <= 1) {
      alert('系统库至少需要保留一篇草案大纲备份！');
      return;
    }
    const rem = articles.filter(a => a.id !== artId);
    setArticles(rem);
    setSelectedArtId(rem[0].id);
    addLog(`✕ 移除了连载稿件 ID: ${artId}`);
  };

  const blockersCount = (currentArticle?.qualityIssues || []).filter(qi => qi.severity === 'Block' && !qi.fixed).length;

  if (!currentArticle) {
    return (
      <div className="p-12 text-center text-gray-400 font-mono">
        <RefreshCw className="animate-spin text-blue-500 mx-auto mb-4" />
        正在连接并重建 Workstation 真相数据引擎...
      </div>
    );
  }

  return (
    <div className={`flex-1 flex flex-col h-full min-h-0 overflow-hidden ${
      isDarkMode ? 'bg-slate-950 text-slate-100' : 'bg-slate-50 text-slate-800'
    }`}>
      
      {/* Manual Creation Modal Form Overlay */}
      {isCreatingNew && (
        <div className="fixed inset-0 z-55 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
          <form
            onSubmit={handleCreateArticle}
            className={`w-full max-w-md p-6 rounded-2xl border shadow-xl animate-fade ${
              isDarkMode ? 'bg-slate-900 border-slate-800 text-white' : 'bg-white border-slate-200 text-slate-800'
            }`}
          >
            <div className="flex items-center justify-between pb-3 border-b dark:border-slate-800 mb-4 font-mono text-xs">
              <h3 className="font-bold">🧙‍♂️ 自拟硬核爆款技术大纲选题 SKELETON</h3>
              <button type="button" onClick={() => setIsCreatingNew(false)} className="text-gray-500 hover:text-red-500">✕</button>
            </div>

            <div className="space-y-4 text-xs text-left">
              <div>
                <label className="text-[10px] text-gray-500 font-mono block mb-1">自拟技术大纲标题 *</label>
                <input
                  type="text"
                  required
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="e.g. Node stream.Writable 高敏背压 drain 控制代码实效性评测"
                  className={`w-full p-2 rounded border focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                    isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-white border-slate-200'
                  }`}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[10px] text-gray-550 block mb-1">流派属性分类 *</label>
                  <select
                    value={newType}
                    onChange={(e) => setNewType(e.target.value)}
                    className="w-full p-2 rounded border bg-transparent text-slate-800 dark:text-white dark:bg-slate-950"
                  >
                    <option value="动手实战">动手实战 (调优避坑)</option>
                    <option value="技术八股">技术八股 (原理解密)</option>
                    <option value="行业深度">行业深度 (前瞻架构)</option>
                  </select>
                </div>

                <div>
                  <label className="text-[10px] text-gray-555 block mb-1">连载专栏匹配</label>
                  <input
                    type="text"
                    value={newSeries}
                    onChange={(e) => setNewSeries(e.target.value)}
                    className={`w-full p-2 rounded border focus:outline-none ${isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-white border-slate-200'}`}
                  />
                </div>
              </div>
            </div>

            <div className="pt-4 mt-4 border-t dark:border-slate-800 flex justify-end space-x-2">
              <button
                type="button"
                onClick={() => setIsCreatingNew(false)}
                className="px-3 py-1.5 bg-slate-200 hover:bg-slate-300 dark:bg-slate-800 dark:hover:bg-slate-750 rounded text-xs text-slate-400"
              >
                取消
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 text-xs font-bold rounded text-white bg-blue-600 hover:bg-blue-700"
              >
                ✓ 人工立项存备
              </button>
            </div>
          </form>
        </div>
      )}



      {/* 3. Core dynamic tabs render split view workspace */}
      <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-hidden">
        
        {/* Left tall tall vertical navigation menus / top horizontal scrolling panel */}
        <div className={`w-full lg:w-64 border-b lg:border-b-0 lg:border-r flex flex-row lg:flex-col p-2 lg:p-3 items-center lg:items-stretch justify-between shrink-0 overflow-x-auto lg:overflow-x-visible custom-scrollbar ${
          isDarkMode ? 'bg-[#0c1220] border-slate-850' : 'bg-slate-50 border-slate-205 shadow-xs'
        }`}>
          <div className="flex flex-row lg:flex-col items-center lg:items-stretch gap-1.5 w-full lg:space-y-2 shrink-0 lg:shrink">
            <div className="hidden lg:flex items-center justify-between px-3 select-none shrink-0">
              <h4 className="font-bold text-[9px] font-mono text-gray-500 tracking-widest uppercase">
                🔬 爆款生文 6 阶盘
              </h4>
            </div>

            <div className="flex flex-row lg:flex-col gap-1 lg:space-y-1">
              {[
                { id: 'confirm', name: '1. 深度生文规格签署', desc: '1st-Stage Specs Gate', icon: Lock },
                { id: 'research', name: '2. 网络多源研搜流水线', desc: 'Web Crawler Evidence', icon: Cpu },
                { id: 'prewrite', name: '3. 创意策划与骨架确认', desc: 'Outline & Punchline Planner', icon: Sparkles },
                { id: 'body', name: '4. 正文编辑及多端格式', desc: 'Editor & Copilot Appender', icon: FileCode },
                { id: 'assets', name: '5. 素材与封面管理车间', desc: 'Emoticon & Cover Machine', icon: ImageIcon },
                { id: 'publish', name: '6. 矩阵分发与账号会话', desc: 'Matrix Syndication', icon: Send },
                { id: 'prompts', name: '7. 提示词流控 Trace 控制', desc: 'Observability Console', icon: Terminal }
              ].map((tab) => {
                const isSelected = activeTab === tab.id || (tab.id === 'research' && activeTab === 'quality');
                const Icon = tab.icon;

                let badgeNode = null;
                if (tab.id === 'confirm' && blockersCount > 0) {
                  badgeNode = <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-ping shrink-0" />;
                }

                return (
                  <button
                    key={tab.id}
                    onClick={() => {
                      setActiveTab(tab.id as any);
                      addLog(`切换控制台面板 ➔ 【${tab.name}】`);
                    }}
                    className={`flex items-center justify-between px-2.5 py-1.5 lg:px-3 lg:py-2 rounded-lg border text-left transition-all shrink-0 whitespace-nowrap lg:whitespace-normal lg:w-full ${
                      isSelected
                        ? isDarkMode 
                          ? 'bg-slate-800 border-slate-700 text-white font-bold'
                          : 'bg-white border-slate-250 text-slate-900 font-bold shadow-xs'
                        : isDarkMode
                        ? 'bg-transparent border-transparent text-slate-400 hover:bg-slate-900/60'
                        : 'bg-transparent border-transparent text-slate-600 hover:bg-white/80'
                    }`}
                  >
                    <div className="flex items-center space-x-1.5 lg:space-x-2 max-w-[95%] lg:max-w-[85%]">
                      <Icon size={12} className={`shrink-0 ${isSelected ? getThemeAccentClass('text') : 'text-slate-450'}`} />
                      <div className="truncate text-left leading-tight">
                        <p className="text-[11px] truncate font-sans lg:max-w-none">{tab.name}</p>
                        <p className="hidden md:block text-[8px] opacity-50 truncate font-mono">{tab.desc}</p>
                      </div>
                    </div>
                    {badgeNode ? badgeNode : <ChevronRight size={10} className="hidden lg:block opacity-40 shrink-0" />}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Quick deletion and cleanup controls */}
          <div className="hidden lg:block pt-3 border-t border-dashed border-slate-205 dark:border-slate-800 text-center select-none shrink-0">
            <button
              onClick={() => {
                if (window.confirm('此操作会在本地 PostgreSQL 历史版本序列强制擦除此稿。确定注销？')) {
                  handleDeleteArticle(currentArticle.id);
                }
              }}
              className="text-[9px] text-gray-550 hover:text-red-500 font-mono flex items-center justify-center space-x-1 mx-auto"
            >
              <Trash2 size={11} />
              <span>整篇备档物理注销</span>
            </button>
          </div>
        </div>

        {/* Right workspace viewports container */}
        <div className="flex-1 overflow-y-auto p-4 pb-28 space-y-4">
          
          {/* Real-time small telemetry notification alert */}
          <div className={`p-1.5 rounded font-mono text-[8px] border flex justify-between select-none ${
            isDarkMode ? 'bg-[#0a0f1d] text-cyan-400 border-slate-850' : 'bg-slate-50 text-slate-900 border-slate-200 shadow-inner'
          }`}>
            <div className="flex items-center space-x-1.5 max-w-[80%]">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-gray-400 uppercase text-[9px] font-bold">[CONSOLE MONITOR]:</span>
              <span className="truncate">{logs[0] || '● Listening trace stream...'}</span>
            </div>
            <span className="opacity-50 text-[7px] tracking-wider uppercase shrink-0">High-Availability Guarded</span>
          </div>

          {/* 4. Tab contents render router */}
          {activeTab === 'confirm' && (
            <SpecsConfirmation
              currentArticle={currentArticle}
              isDarkMode={isDarkMode}
              accentColor={accentColor}
              updateActiveArticle={updateActiveArticle}
              addLog={addLog}
              getThemeAccentClass={getThemeAccentClass}
              onLockSpecsAndGenerate={() => {
                // Instantly heal outline sign, start streaming active pipeline
                const issues = currentArticle.qualityIssues || [];
                const healed = issues.map(q => q.category === 'Structure' ? { ...q, fixed: true } : q);
                updateActiveArticle({ qualityIssues: healed });
                setActiveTab('research');
                addLog(`⚙ [决断放行] 人工签署大目录锁已彻底解除！正在智能调度流水重试...`);
              }}
            />
          )}

          {(activeTab === 'research' || activeTab === 'quality') && (
            <ActivePipeline
              currentArticle={currentArticle}
              isDarkMode={isDarkMode}
              accentColor={accentColor}
              updateActiveArticle={updateActiveArticle}
              addLog={addLog}
              getThemeAccentClass={getThemeAccentClass}
              onAdvanceToPlanning={() => {
                setActiveTab('prewrite');
                addLog(`⚙ [流转创意] 探哨报告就绪，自动转进“3. 创意策划与骨架确认”...`);

                const topicTitle = currentArticle.title || "学术流控";
                const titleCandidates = currentArticle.titleCandidates || [
                  { text: `${topicTitle}：分布式缓冲提交机制原理与避坑生存指南`, style: '深度极客流', hookDepth: '5 星', clicksEstimate: '4.2% CTR' },
                  { text: `因一个 write 的 false 返回，我们生产网关堆栈发生了严重的 OOM 雪崩`, style: '现场纪实流', hookDepth: '5 星', clicksEstimate: '4.8% CTR' },
                  { text: `Redis 消息积压遇上事件循环被锁死？手把手教你在 Node.js 中搭建背压自愈网关`, style: '动手教程流', hookDepth: '4.5 星', clicksEstimate: '3.9% CTR' }
                ];
                const defaultHook = currentArticle.hookScene || `【真实事故瞬间复盘】服务器监控突然发出刺眼的红色预警。后端网关响应时延迅速突破 2000ms，V8 内存极速狂飙至 1.8G，随即崩溃重启。我们惊恐地发现，问题源于在大模型长文本流式 SSE 状态下，下游由于网速过慢发生数据挤压，而上游却未遵循 drain 机制肆无忌惮地持续调用 write，最终被背压引发的内存泄露彻底击穿！`;
                const defaultAbstract = currentArticle.abstract || `本文将针对工业级大模型流式 SSE 网关高并发场景下的缓冲区雪崩问题，展开深度剖析。我们将对 Node 事件循环、Writable 的背压原理机制以及 React 端单体长连接背压阻断展开深层源码层级的对比解密，并结合 React + Node + Redis 主被动限流模型提供完整的零拷贝避坑调优方案。`;
                const defaultGoldenQuotes = (currentArticle as any).goldenQuotes || `1. "背压（Backpressure）不是简单的阻断，而是系统各节点间关于写强度的优雅博弈与妥协。"
2. "在大模型流式引擎中，忽略对 drain 返回值的自检测，等同于无保护地在泥沼路面狂飙至两百万转速。"
3. "用 80 行原生 TypeScript 构建 Writable 影子缓冲区，换来的是面对上万并发 SSE 连接时从容不迫的系统稳定阀！"`;
                const defaultOutline = currentArticle.outline && currentArticle.outline.length > 0 ? currentArticle.outline : [
                  { id: 'sec-1', title: '一、线上事故回溯：SSE 长链接与内存崩溃瞬间', subtopics: ['高频 write() 与流阻堵塞现形记', '如何用火焰图准确定制 V8 垃圾回收溢出节点'] },
                  { id: 'sec-2', title: '二、Writable Stream 工作机制与 drain 降级模型', subtopics: ['流式缓冲区高水位线（highWaterMark）阀值控制', 'drain 触发条件的底层 C++ 源码分析'] },
                  { id: 'sec-3', title: '三、零拷贝自愈架构：基于 Redis 背压的双向推拉限速器', subtopics: ['滑动窗口事件循环模型源码设计', '影子缓冲区与背压自反转实现'] }
                ];

                updateActiveArticle({
                  titleCandidates,
                  hookScene: defaultHook,
                  abstract: defaultAbstract,
                  outline: defaultOutline,
                  goldenQuotes: defaultGoldenQuotes
                } as any);
                addLog(`✓ [AI 自动装配] 已完美自动装配创意骨架要素（3个高CTR候选标题、首句现场钩子、目录大纲、高品质金句）！`);
              }}
            />
          )}

          {activeTab === 'prewrite' && (
            <PlanningBoard
              currentArticle={currentArticle}
              isDarkMode={isDarkMode}
              accentColor={accentColor}
              updateActiveArticle={updateActiveArticle}
              addLog={addLog}
              getThemeAccentClass={getThemeAccentClass}
              onAdvanceToBody={() => {
                setActiveTab('body');
                updateActiveArticle({ status: '正在生成', currentContent: '' });
                addLog(`⚙ [开始生成] 大纲骨架正式锁定！提交正文生成 Job 到“4. 正文编辑及多端格式”通道...`);
              }}
            />
          )}

          {activeTab === 'body' && (
            <VersionConsole
              currentArticle={currentArticle}
              isDarkMode={isDarkMode}
              accentColor={accentColor}
              updateActiveArticle={updateActiveArticle}
              addLog={addLog}
              getThemeAccentClass={getThemeAccentClass}
            />
          )}

          {activeTab === 'assets' && (
            <CoverWorkshop
              currentArticle={currentArticle}
              isDarkMode={isDarkMode}
              accentColor={accentColor}
              updateActiveArticle={updateActiveArticle}
              addLog={addLog}
              getThemeAccentClass={getThemeAccentClass}
            />
          )}

          {activeTab === 'publish' && (
            <PublishMatrix
              currentArticle={currentArticle}
              isDarkMode={isDarkMode}
              accentColor={accentColor}
              updateActiveArticle={updateActiveArticle}
              addLog={addLog}
              getThemeAccentClass={getThemeAccentClass}
              onPublishAllPlatforms={() => {
                updateActiveArticle({ status: '已发布' });
                addLog(`✓ [Matrix SYNC_OK] 微信公众号、Hexo、掘金、CSDN大功发布告成！全渠道状态变位 -> [已发布]！`);
              }}
              onSetTab={onSetTab}
              credentials={credentials}
              setCredentials={setCredentials}
            />
          )}

          {activeTab === 'prompts' && (
            <PromptOpsTracer
              currentArticle={currentArticle}
              isDarkMode={isDarkMode}
              accentColor={accentColor}
              addLog={addLog}
              getThemeAccentClass={getThemeAccentClass}
            />
          )}

        </div>


      </div>

    </div>
  );
}
