import React, { useState } from 'react';
import { Flame, Plus, Sparkles, AlertCircle, HelpCircle, CheckSquare, RefreshCw, BookOpen } from 'lucide-react';
import { Article, OutlineItem, TitleCandidate } from '../types';

export interface CandidateTopic {
  id: string;
  title: string;
  source: string;
  heatScore: number;
  ctrPrediction: string;
  recommendedWords: number;
  recommendedStyle: string;
  recommendedSeries: string;
  description: string;
  status: '待评估' | '已采用' | '已忽略' | '已合并' | '已过期' | '已写成文章';
  opinions?: string;
  materials?: string;
  referenceLink?: string;
  preResearch?: {
    abstract: string;
    titles: string[];
    outline: string[];
    hook: string;
  };
}

interface TopicSelectionProps {
  articles: Article[];
  setArticles: React.Dispatch<React.SetStateAction<Article[]>>;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  hotspotsList: CandidateTopic[];
  setHotspotsList: React.Dispatch<React.SetStateAction<CandidateTopic[]>>;
  addLog: (msg: string) => void;
  onTransitionToSpecs: (artId: string) => void;
  getThemeAccentClass: (type: any) => string;
}

export default function TopicSelection({
  articles,
  setArticles,
  isDarkMode,
  accentColor,
  hotspotsList,
  setHotspotsList,
  addLog,
  onTransitionToSpecs,
  getThemeAccentClass
}: TopicSelectionProps) {
  const [selectedCandidate, setSelectedCandidate] = useState<CandidateTopic | null>(hotspotsList[0] || null);
  const [isPreResearching, setIsPreResearching] = useState(false);
  const [userTitle, setUserTitle] = useState('');
  const [userOpinions, setUserOpinions] = useState('');
  const [userReferenceLink, setUserReferenceLink] = useState('');
  const [userMaterials, setUserMaterials] = useState('');

  // 1. Trigger pre-research (轻量自动预研)
  const handlePreResearch = (candId: string) => {
    setIsPreResearching(true);
    addLog(`➔ [轻量预研] 对候选选题ID: ${candId} 启动 LLM 快速预跑研判...`);
    
    setTimeout(() => {
      setHotspotsList(prev => prev.map(c => {
        if (c.id !== candId) return c;
        const out = {
          ...c,
          status: '待评估' as const,
          preResearch: {
            abstract: `【轻量预研摘要】针对选题《${c.title}》，初步研判这是一道生产环境下的严重痛点。本文将剖析流控制底层写屏障、V8 新生代内存碎片与背压限流管道方案，为极客开发者提供高集成、无幻觉的代码范例。`,
            titles: [
              c.title,
              `别再直接 += chunk 了！大模型长连接下的内存雪崩与 Node.js 柔性背压控流实录`,
              `万字测评：高并发 Agent 复杂的分布式影子两阶段加锁限时自退回机制`
            ],
            outline: [
              '一、故障回溯：万级并发流长连接 SSE 的溢出报警',
              '二、底层揭秘：V8 新生代垃圾回收（Scavenge）与堆栈字符串拼接漏洞碎片',
              '三、硬核解决：构建 node 标准 `drain` 信号反弹的水波纹回转限速阀代码',
              '四、实效复核：并发写入延迟减少指标及自愈效果比照分析'
            ],
            hook: `【真实事故刺痛】：慢链接客户端与流式大模型在单显卡下的读写不对称性，使得缓冲区在 5 秒内迅速攀至 1.8G。报警尖叫连绵不绝。今天我们用一手源码，看看背压的破局之法...`
          }
        };
        // Update selected view as well
        setSelectedCandidate(out);
        return out;
      }));
      setIsPreResearching(false);
      addLog(`✓ [轻量预研成功] 选题一阶段元参数、大纲结构、痛点钩子已装载，可在右侧视窗预览。`);
    }, 1000);
  };

  // 2. Change Candidate lifecycle status
  const handleUpdateStatus = (candId: string, nextStatus: CandidateTopic['status']) => {
    setHotspotsList(prev => prev.map(c => {
      if (c.id === candId) {
        const updated = { ...c, status: nextStatus };
        if (selectedCandidate?.id === candId) {
          setSelectedCandidate(updated);
        }
        return updated;
      }
      return c;
    }));
    addLog(`[选题状态变更] 选题 ${candId} 状态锁定为：➔ ${nextStatus}`);
  };

  // 3. User manual entry (用户输入主题观点/链接)
  const handleAddCustomTopic = (e: React.FormEvent) => {
    e.preventDefault();
    if (!userTitle.trim()) return;

    const newCand: CandidateTopic = {
      id: `cand-user-${Date.now()}`,
      title: userTitle,
      source: '主编桌面手工录入',
      heatScore: 88,
      ctrPrediction: '2.5% - 3.8% CTR',
      recommendedWords: 4000,
      recommendedStyle: '极客技术分析：无废话、含代码、重火焰图',
      recommendedSeries: 'LLM 与 RAG 工业级调优内幕',
      description: '管理员或用户添加的手动定制主题。' + (userOpinions ? ` 观点聚焦：${userOpinions}` : ''),
      status: '待评估',
      opinions: userOpinions,
      referenceLink: userReferenceLink,
      materials: userMaterials
    };

    setHotspotsList(prev => [newCand, ...prev]);
    setSelectedCandidate(newCand);
    addLog(`✓ [人工立项选题库] 成功录入人工选题候选: 《${userTitle.slice(0, 15)}...》`);
    
    // Auto pre-research manually added topic immediately
    setTimeout(() => {
      handlePreResearch(newCand.id);
    }, 300);

    setUserTitle('');
    setUserOpinions('');
    setUserReferenceLink('');
    setUserMaterials('');
  };

  // 4. Load Next Series Topic (系统读取专栏下一篇待写条目)
  const handleLoadNextSeriesTopic = () => {
    addLog(`➔ [系列规划库] 正在调取“AI Agent 高性能架构原理与研发实战”连载排期专栏数...`);
    
    setTimeout(() => {
      const seriesNextTitle = 'Redis Pub/Sub 订阅泄露遇上 K8s HPA：大模型流式 SSE 网关高并发下的 Event Loop 积额退算机制';
      
      const isExist = hotspotsList.some(c => c.title === seriesNextTitle);
      if (isExist) {
        addLog(`● [系列规划库] 重复机制：专栏下一排期选题已处于候选池中。`);
        return;
      }

      const nextSeriesCand: CandidateTopic = {
        id: `cand-series-${Date.now()}`,
        title: seriesNextTitle,
        source: '专栏分册排期调度器',
        heatScore: 92,
        ctrPrediction: '3.1% - 4.6% CTR',
        recommendedWords: 4500,
        recommendedStyle: '第一人称视角实践复盘，注重一手源码分析与可复现指标',
        recommendedSeries: 'AI Agent 高性能架构原理与研发实战',
        description: '探讨在大模型流式 chunks 突发下，订阅端高并发多路复用的 Event loop 背压控流机制，解决长连接通道拥塞。',
        status: '待评估'
      };

      setHotspotsList(prev => [nextSeriesCand, ...prev]);
      setSelectedCandidate(nextSeriesCand);
      addLog(`✓ [专栏调度就绪] 读取下一排期成功：已向候选选题池追加专栏预置选题并启用推荐参数。`);
      
      // Auto-trigger pre-research
      setTimeout(() => {
        handlePreResearch(nextSeriesCand.id);
      }, 300);
    }, 900);
  };

  // 5. Adopt Theme (确定选题，立项生成 Draft)
  const handleAdoptAndCreateArticleSpec = (cand: CandidateTopic) => {
    addLog(`➔ [立项签署] 采纳选题《${cand.title}》。正在装配一阶段原始 Draft 规约...`);
    
    const newArtId = `art-hot-${Date.now()}`;
    const defaultOutline: OutlineItem[] = cand.preResearch?.outline.map((o, idx) => ({
      id: `sec-${idx}-${Date.now()}`,
      title: o,
      subtopics: ['待二级细化展开观点元素 1', '待二级细化展开观点元素 2']
    })) || [
      { id: 'sec-1', title: '1. 一醒来，看板全红：故障现场回放', subtopics: ['高吞吐下的 V8 新生代内存超温', '网络背压在 Socket 的传导与拥堵'] },
      { id: 'sec-2', title: '2. 深度剖析：为什么传统多阶段方案容易雪崩', subtopics: ['影子锁 (Shadow Locks) 的防挂起机制', '大模型 SSE 缓冲区与滑动限流算法'] },
      { id: 'sec-3', title: '3. 极客硬核代码：基于 ES6+/TS 柔性流控制的源码重构', subtopics: ['事件循环优化的滑动窗口缓冲池', '异常降级与退避退让 graceful shutdown 算法'] }
    ];

    const defaultTitleCandidates: TitleCandidate[] = cand.preResearch?.titles.map((t, idx) => ({
      text: t,
      style: idx === 0 ? '硬核技术专业流' : idx === 1 ? '避坑痛点爽文流' : '极客通俗大揭秘',
      hookDepth: '5级深度标志',
      clicksEstimate: cand.ctrPrediction
    })) || [
      { text: cand.title, style: '极客技术流', hookDepth: '技术 5 星', clicksEstimate: cand.ctrPrediction },
      { text: `别再 += chunk 了：大模型流式对话 SSE 网关的背压限流高可用设计`, style: '通俗痛点解决流', hookDepth: '点击极高', clicksEstimate: '4.2% CTR' }
    ];

    const newArticle: Article = {
      id: newArtId,
      title: cand.title,
      type: '动手实战',
      seriesId: 's-1',
      seriesName: cand.recommendedSeries,
      status: '待写作',
      createdAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
      updatedAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
      abstract: cand.preResearch?.abstract || '一阶段规划摘要暂未编译获得，请点击「自动预研」激活。',
      hookScene: cand.preResearch?.hook || '钩子未签署锁定。首句痛点事故场景缺失。',
      outline: defaultOutline,
      titleCandidates: defaultTitleCandidates,
      targetWords: cand.recommendedWords,
      actualWords: 0,
      writingStyle: cand.recommendedStyle,
      currentContent: '',
      publications: [
        { platformId: 'hexo', platformName: 'Hexo (自建博客)', status: 'Draft', draftId: `${newArtId}-hexo` },
        { platformId: 'wechat', platformName: '微信公众号', status: 'Draft', draftId: `${newArtId}-wechat` },
        { platformId: 'csdn', platformName: 'CSDN 技术社区', status: 'Draft', draftId: `${newArtId}-csdn` }
      ],
      qualityIssues: [
        { id: `qi-lock-${newArtId}`, category: 'Structure', severity: 'Block', description: '新立项：选题一阶段管理员签名锁死未解锁，阻写大正文。', attributedModule: '人工门禁控制阀', fixed: false },
        { id: `qi-res-${newArtId}`, category: 'Research', severity: 'Warning', description: '正文论据不足：未执行深度双重研搜，引文引证缺失。', attributedModule: 'Scholar 研搜审计器', fixed: false }
      ],
      researchReport: {
        summary: `轻量研究选题事实：对《${cand.title}》涉及到的高可用一致性做了检索标记。`,
        sources: [
          { title: 'Reactive Streams Protocol Specifications v1.0', url: 'https://github.com/reactive-streams', reliability: 'High', extract: '非阻塞异步数据流的回压管理物理规范。' }
        ],
        coveragePercent: 88,
        evidenceGaps: ['全系统尚未完成多线程下的极限压测比对，信源引证有拓展余地。']
      },
      agentLogs: [
        { timestamp: new Date().toLocaleTimeString(), action: 'Topics Draft Initialized', agent: 'AImagician System Agent', status: 'Success', detail: `立项契约签署！从候选爆红选题 [${cand.title.slice(0, 15)}...] 促升至全局 Draft 数据库。` }
      ]
    };

    // Promote in hotspots list state
    setHotspotsList(prev => prev.map(c => c.id === cand.id ? { ...c, status: '已写成文章' as const } : c));
    setArticles(prev => [newArticle, ...prev]);
    onTransitionToSpecs(newArtId);
    addLog(`✓ [选题已采用且立项成功] 新稿件 ID: ${newArtId} 已建立，系统已带入下一决策阶段：【2. 深度生文大纲确认】。`);
  };

  return (
    <div className="space-y-4 max-w-5xl animate-fade">
      
      {/* Search and auto scanning board */}
      <div className={`p-4 rounded-xl border flex flex-col md:flex-row md:items-center justify-between gap-4 ${
        isDarkMode ? 'bg-slate-900/40 border-slate-800' : 'bg-blue-50/20 border-blue-200/50 shadow-xs'
      }`}>
        <div className="space-y-1">
          <h3 className="font-bold text-xs font-mono uppercase text-blue-505 dark:text-blue-400">选题搜集与轻量预判 (Mutil-Channel Hotspots Hub)</h3>
          <p className="text-[11px] text-gray-500">
            从各大极客前沿平台收集事实爆款（可写成文章）。采纳选题触发「轻量预研」，系统预先编译大纲、备选标题、摘要钩子。
          </p>
        </div>

        <div className="flex flex-wrap gap-2 shrink-0">
          <button
            type="button"
            onClick={handleLoadNextSeriesTopic}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold flex items-center bg-slate-100 hover:bg-slate-200 text-slate-700 dark:bg-slate-800 dark:hover:bg-slate-750 dark:text-slate-200 border dark:border-slate-700`}
          >
            <BookOpen size={11} className="mr-1" />
            <span>拉取系列连载下一篇</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        
        {/* 1. Left side candidates list */}
        <div className="lg:col-span-7 space-y-4">
          
          {/* Manual insert Form */}
          <div className={`p-4 rounded-xl border space-y-3 ${
            isDarkMode ? 'bg-slate-900 border-slate-800' : 'bg-white border-slate-200 shadow-sm'
          }`}>
            <h4 className="font-bold text-xs text-slate-800 dark:text-slate-100 flex items-center border-b pb-1.5 border-dashed border-slate-200 dark:border-slate-800">
              <Plus size={13} className="mr-1 text-blue-500" />
              手工策划爆款 (意见 / 参考链接素材录入)
            </h4>

            <form onSubmit={handleAddCustomTopic} className="space-y-2.5 text-xs">
              <div>
                <input
                  type="text"
                  required
                  value={userTitle}
                  onChange={(e) => setUserTitle(e.target.value)}
                  placeholder="★ 自拟技术标题：e.g, 极速重构 WebAssembly 底层大文本解析开销"
                  className={`w-full p-2 text-xs rounded border focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                    isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200'
                  }`}
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <input
                  type="text"
                  value={userOpinions}
                  onChange={(e) => setUserOpinions(e.target.value)}
                  placeholder="✍ 主张观点：e.g, 强调在多轮群聊决策中丢弃过时 key"
                  className={`p-2 text-[10px] rounded border focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                    isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200'
                  }`}
                />
                <input
                  type="text"
                  value={userReferenceLink}
                  onChange={(e) => setUserReferenceLink(e.target.value)}
                  placeholder="🔗 论据参考链接：e.g, https://github.or..."
                  className={`p-2 text-[10px] rounded border focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                    isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200'
                  }`}
                />
              </div>

              <div className="flex justify-between items-center">
                <input
                  type="text"
                  value={userMaterials}
                  onChange={(e) => setUserMaterials(e.target.value)}
                  placeholder="📂 附带素材备忘、 DOI 说明..."
                  className={`p-2 text-[10px] rounded border focus:outline-none focus:ring-1 focus:ring-blue-500 flex-1 mr-2 ${
                    isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200'
                  }`}
                />

                <button
                  type="submit"
                  className="py-1.5 px-3 rounded-lg text-xs font-bold font-mono bg-blue-600 text-white hover:bg-blue-700 flex items-center shrink-0"
                >
                  <Plus size={11} className="mr-0.5" />
                  <span>添加并做轻量预研</span>
                </button>
              </div>
            </form>
          </div>

          {/* List panel */}
          <div className="space-y-2">
            <p className="text-[10px] font-bold font-mono text-gray-500 uppercase select-none">精选候选题池 (Selected Tech Hotspots Candidate Pool):</p>
            <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
              {hotspotsList.map((hot) => {
                const isSelected = selectedCandidate?.id === hot.id;
                let statusBadgeColor = 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300';
                if (hot.status === '已写成文章') statusBadgeColor = 'bg-emerald-100/70 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-400';
                else if (hot.status === '已采用') statusBadgeColor = 'bg-blue-105 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400';
                else if (hot.status === '已忽略') statusBadgeColor = 'bg-rose-100/50 text-rose-700/80 dark:bg-rose-950/20';

                return (
                  <div
                    key={hot.id}
                    onClick={() => setSelectedCandidate(hot)}
                    className={`p-3.5 rounded-xl border text-left cursor-pointer transition-all flex flex-col justify-between space-y-2 relative ${
                      isSelected
                        ? isDarkMode
                          ? 'bg-slate-900 border-blue-500/80 shadow-md ring-1 ring-blue-500/10'
                          : 'bg-white border-blue-400 shadow-md ring-1 ring-blue-400/20'
                        : isDarkMode
                        ? 'bg-slate-905 border-slate-850 hover:bg-slate-900/60'
                        : 'bg-white border-slate-205 hover:bg-slate-50/50 shadow-xs'
                    }`}
                  >
                    <div className="flex justify-between items-start">
                      <div className="flex flex-wrap gap-1 items-center">
                        <span className="text-[8px] px-1 py-0.5 rounded font-mono font-bold bg-amber-500 text-slate-950 shrink-0">
                          🔥 HEAT {hot.heatScore}
                        </span>
                        <span className="text-[8px] px-1 py-0.5 rounded font-mono font-semibold opacity-60">
                          来源: {hot.source}
                        </span>
                      </div>

                      <span className={`px-1.5 py-0.5 rounded text-[8px] font-mono uppercase font-bold shrink-0 ${statusBadgeColor}`}>
                        {hot.status}
                      </span>
                    </div>

                    <h4 className="text-[11px] font-bold leading-normal font-sans text-slate-900 dark:text-slate-101">
                      {hot.title}
                    </h4>

                    <p className="text-[10px] text-gray-500 font-normal line-clamp-2 leading-relaxed">
                      {hot.description}
                    </p>

                    <div className="flex justify-between items-center text-[9px] font-mono opacity-80 pt-1.5 border-t border-slate-100 dark:border-slate-850">
                      <span>预计字数: {hot.recommendedWords || 4500} 字</span>
                      <span className="text-emerald-500 font-bold">推荐 CTR: {hot.ctrPrediction}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* 2. Right side info & "Pre-research" visual viewer panel */}
        <div className="lg:col-span-5 h-[calc(100vh-14rem)] sticky top-0 flex flex-col space-y-3">
          {selectedCandidate ? (
            <div className={`p-4 h-full border rounded-xl overflow-y-auto flex flex-col justify-between space-y-4 ${
              isDarkMode ? 'bg-slate-900 border-slate-800' : 'bg-white border-slate-200 shadow-sm'
            }`}>
              
              <div className="space-y-3">
                <div className="flex items-center justify-between border-b pb-2 dark:border-slate-800">
                  <span className="text-[9px] font-bold font-mono text-gray-500 uppercase tracking-widest leading-none">
                    选题预审视窗 (PRE-SPEC EXPLORER)
                  </span>
                  
                  {/* Action states select */}
                  <div className="flex space-x-1">
                    <button
                      type="button"
                      onClick={() => handleUpdateStatus(selectedCandidate.id, '已忽略')}
                      className="px-1.5 py-0.5 text-[8px] rounded border border-rose-500/20 text-rose-500 bg-rose-500/5 font-bold hover:bg-rose-500/15"
                    >
                      忽略
                    </button>
                    <button
                      type="button"
                      onClick={() => handleUpdateStatus(selectedCandidate.id, '已采用')}
                      className="px-1.5 py-0.5 text-[8px] rounded border border-blue-500/20 text-blue-500 bg-blue-500/5 font-bold hover:bg-blue-500/15"
                    >
                      采用
                    </button>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <p className="text-[10px] text-gray-400 font-mono">所选爆款选题：</p>
                  <h3 className="text-xs font-bold leading-normal text-slate-805 dark:text-white">
                    {selectedCandidate.title}
                  </h3>
                  <div className="flex items-center space-x-2 text-[9px] font-mono text-slate-505">
                    <span>专栏: <strong className="text-blue-500">{selectedCandidate.recommendedSeries}</strong></span>
                    <span>·</span>
                    <span>流派: <strong className="text-orange-500">动手实战</strong></span>
                  </div>
                </div>

                {/* Pre-Research summary content */}
                {selectedCandidate.preResearch ? (
                  <div className="space-y-3 pt-2 text-[10px] leading-relaxed">
                    <div className={`p-2.5 rounded-lg border ${
                      isDarkMode ? 'bg-slate-950 border-slate-850 text-slate-300' : 'bg-slate-50 border-slate-150 text-slate-705'
                    }`}>
                      <p className="font-bold text-amber-500 font-sans mb-1 text-[11px] flex items-center">
                        <Sparkles size={11} className="mr-1" />
                        「轻量自动预研」摘要成果：
                      </p>
                      <p className="leading-snug">{selectedCandidate.preResearch.abstract}</p>
                    </div>

                    <div className="space-y-1">
                      <p className="font-bold text-slate-800 dark:text-slate-350">★ 预跑爆款标题备选一览：</p>
                      <ul className="list-decimal pl-4 space-y-0.5 text-gray-500">
                        {selectedCandidate.preResearch.titles.map((t, idx) => (
                          <li key={idx} className="leading-snug transition-colors hover:text-slate-800 dark:hover:text-white pointer-events-none">《{t}》</li>
                        ))}
                      </ul>
                    </div>

                    <div className="space-y-1">
                      <p className="font-bold text-slate-805 dark:text-slate-350">★ 预跑架构大纲一级节点：</p>
                      <div className="space-y-1 p-2 rounded bg-slate-950/30 text-gray-400 font-mono text-[9px]">
                        {selectedCandidate.preResearch.outline.map((o, idx) => (
                          <p key={idx} className="truncate">{o}</p>
                        ))}
                      </div>
                    </div>

                    <div className="space-y-1">
                      <p className="font-bold text-amber-500">★ 预跑生产故事 Hook：</p>
                      <p className="p-2 border border-dashed rounded italic font-mono text-[9px] bg-amber-955/5 text-slate-600 dark:text-amber-200 dark:border-amber-900/30">
                        {selectedCandidate.preResearch.hook}
                      </p>
                    </div>

                    {/* Opinions validation presentation */}
                    {selectedCandidate.opinions && (
                      <div className="p-2 bg-blue-950/20 rounded border border-blue-900/30">
                        <p className="font-bold text-blue-400">■ 录入的特定观点及引用信源链接：</p>
                        <p className="text-[10px] text-slate-300 mt-1">主张：{selectedCandidate.opinions}</p>
                        {selectedCandidate.referenceLink && (
                          <p className="text-[9px] text-[#0077b6] dark:text-blue-400 underline truncate mt-0.5">{selectedCandidate.referenceLink}</p>
                        )}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className={`p-8 rounded-xl border border-dashed text-center space-y-3 ${
                    isDarkMode ? 'border-slate-805 bg-slate-950/20' : 'border-slate-200 bg-slate-50'
                  }`}>
                    <AlertCircle size={22} className="mx-auto text-amber-505 animate-pulse" />
                    <h4 className="text-xs font-bold text-slate-550 dark:text-slate-350">
                      尚未对本选题进行「轻量预研」
                    </h4>
                    <p className="text-[10px] text-gray-500 leading-normal max-w-xs mx-auto">
                      请对该选题发起轻量前置分析，人工智能即可快速预编译出抽象目录、CTR 备选主标题、前置钩子，核对通过即可正式锁定签署。
                    </p>

                    <button
                      type="button"
                      onClick={() => handlePreResearch(selectedCandidate.id)}
                      disabled={isPreResearching}
                      className="px-3 py-1.5 bg-blue-600 text-white hover:bg-blue-700 text-[10px] font-bold rounded-lg font-mono flex items-center space-x-1 justify-center mx-auto disabled:opacity-40"
                    >
                      <RefreshCw size={10} className={isPreResearching ? 'animate-spin' : ''} />
                      <span>{isPreResearching ? '系统正在快速研判中...' : '➔ 采纳并一键轻量预研此选题'}</span>
                    </button>
                  </div>
                )}
              </div>

              {/* Confirm / Prompts creation trigger */}
              <div className="pt-3 border-t dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => handleAdoptAndCreateArticleSpec(selectedCandidate)}
                  disabled={selectedCandidate.status === '已写成文章'}
                  className={`w-full py-2 rounded-xl text-xs font-mono font-bold text-white shadow bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 disabled:opacity-30 flex items-center justify-center space-x-2`}
                >
                  <Sparkles size={12} className="animate-pulse" />
                  <span>{selectedCandidate.status === '已写成文章' ? '✓ 此选题已正式写成连载文章' : '✓ 确定此主题，前往确认生文规格 ➔'}</span>
                </button>
              </div>

            </div>
          ) : (
            <div className="p-12 text-center text-gray-400 font-mono text-xs">
              请点击选题卡片，获取多维要素详细参数。
            </div>
          )}
        </div>

      </div>

    </div>
  );
}
