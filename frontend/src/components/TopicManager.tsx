import React, { useState } from 'react';
import {
  Flame,
  Plus,
  RefreshCw,
  TrendingUp,
  FileText,
  User,
  Link as LinkIcon,
  Sparkles,
  Award,
  ChevronRight,
  Database,
  Layers,
  ArrowUpRight,
  HelpCircle,
  Clock,
  ExternalLink,
  PlusSquare,
  AlertCircle
} from 'lucide-react';
import { Article, Series } from '../types';
import GlobalSelector from './GlobalSelector';
import SeriesPlanner from './SeriesPlanner';
import { listTopicCandidates, collectHotspotTopics, adoptTopicCandidate } from '../api';

interface TopicManagerProps {
  articles: Article[];
  setArticles: React.Dispatch<React.SetStateAction<Article[]>>;
  seriesList: Series[];
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  onSetTab: (tab: string) => void;
  selectedArticleId?: string;
  selectedSeriesId?: string;
  onSelectArticle?: (id: string) => void;
  onSelectSeries?: (id: string) => void;
  globalSearchQuery?: string;
}

export interface HotspotItem {
  id: string;
  title: string;
  abstract: string;
  heatScore: number;
  ctrPrediction: string;
  wordsEstimate: number;
  styleRecommendation: string;
  evidenceSource: { title: string; url: string; reliability: 'High' | 'Medium' | 'Low' }[];
  domain: string;
  timestamp?: string; // Continuous capture signature
}

// Tech hotspot pools for continuous live background crawling simulation
const NEW_HOTSPOTS_POOL = [
  {
    title: 'Node.js 22.4 中 V8 垃圾回收暂停时间减半：通过非托管堆隔离流媒体高饱和 Buffer 溢出',
    domain: 'High Concurrency & Event Loop',
    heatScore: 97,
    ctrPrediction: '4.8% - 6.2% CTR',
    wordsEstimate: 4200,
    abstract: '使用 Node.js 高频分发 SSE 事件时产生的大量二进制 Chunk 容易穿透到堆内存引发大范围 GC 挂起。通过原生非托管缓冲队列，实现零拷贝并彻底避开 V8 回收机制。',
    styleRecommendation: '动手实战流：配 Node 原始 Addon 部分 C++ 指针代码，展现 Heap Profiler 堆变化对比图',
    evidenceSource: [
      { title: 'Node.js Runtime Performance optimization v22', url: 'https://nodejs.org/en/blog', reliability: 'High' }
    ]
  },
  {
    title: '字节跳动超大规模 Redis 哨兵切换一致性黑洞：基于 Raft 共识强对齐的双通道微秒自愈设计',
    domain: 'Distributed Consensus & Agents',
    heatScore: 96,
    ctrPrediction: '3.9% - 5.4% CTR',
    wordsEstimate: 4600,
    abstract: '分布式写故障中因 Sentinel 漂移导致的命令乱序覆盖引发集群高水位爆机。本期架构方案基于两阶段锁强制校验 TrueTime 时间窗口，解决极端情况下的双写悬挂一致性自愈。',
    styleRecommendation: '行业深度流：展现完整的双层拓扑一致性差分 Diff 手稿，配 Docker 集群崩溃复现实操',
    evidenceSource: [
      { title: 'Raft consensus in multi-master caching', url: 'https://raft.github.io/', reliability: 'High' }
    ]
  },
  {
    title: '美团外卖实时派单的高并发惊群故障：通过 TCP Socket SO_REUSEPORT 与 Epoll 软中断分流实现零丢包',
    domain: 'High Concurrency & Event Loop',
    heatScore: 93,
    ctrPrediction: '3.5% - 4.9% CTR',
    wordsEstimate: 3800,
    abstract: '核心网关在午高峰秒级瞬时请求越过 105k 并发时，网卡软中断不均突发丢包。采用 SO_REUSEPORT 多端口多线程分洪，配合 Epoll 背压反控锁止缓冲区，保证强吞吐。',
    styleRecommendation: '技术八股流：解密内核 epoll_wait 唤醒链表与轻量级自旋锁自愈底蕴',
    evidenceSource: [
      { title: 'Epoll edge trigger load balancing notes', url: 'https://man7.org/linux/man-pages/man2/epoll_wait.2.html', reliability: 'High' }
    ]
  },
  {
    title: '阿里大模型大集群 HPA 抖动避坑实录：通过信号双向滑动平均滤波与降噪算法抑制 SRE 高饱和报警',
    domain: 'LLM Reasoning & Client Optimization',
    heatScore: 92,
    ctrPrediction: '3.2% - 4.6% CTR',
    wordsEstimate: 4000,
    abstract: '由于推理服务多标记预测 (MTP) 的延迟具有高随机性，常规 HPA 的 CPU 指标频繁误判产生惊群式扩缩容。借鉴卡尔曼滤波思想开发双向滑动滑动平均滤波算法，极大释放报警频率。',
    styleRecommendation: '行业深度流：带线上高低水位拓扑 Diff 架构线框图，强调工程避坑指标',
    evidenceSource: [
      { title: 'Kubernetes horizontal pod autoscaler filter engine', url: 'https://kubernetes.io/docs', reliability: 'High' }
    ]
  }
];

export default function TopicManager({
  articles,
  setArticles,
  seriesList,
  isDarkMode,
  accentColor,
  onSetTab,
  selectedArticleId,
  selectedSeriesId,
  onSelectArticle,
  onSelectSeries,
  globalSearchQuery = ''
}: TopicManagerProps) {
  // Plan within PRD: Remove series-topics as per User directive
  const [activeSubTab, setActiveSubTab] = useState<'hotspots-all' | 'hotspots-academic' | 'hotspots-engineering' | 'user-input' | 'planner'>('hotspots-all');
  const [localSearch, setLocalSearch] = useState('');
  const [selectedDomain, setSelectedDomain] = useState<string>('ALL');
  const [sortBy, setSortBy] = useState<'heatScore' | 'wordsEstimate'>('heatScore');
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(4);
  const [selectedHotspotForDetail, setSelectedHotspotForDetail] = useState<HotspotItem | null>(null);
  const [toastNotification, setToastNotification] = useState<string | null>(null);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const [livePoolIndex, setLivePoolIndex] = useState(0);

  // User input form states
  const [userTheme, setUserTheme] = useState('');
  const [userLink, setUserLink] = useState('');
  const [userViewpoint, setUserViewpoint] = useState('');
  const [userMaterial, setUserMaterial] = useState('');
  const [isProcessingInput, setIsProcessingInput] = useState(false);
  const [userGeneratedTopic, setUserGeneratedTopic] = useState<any | null>(null);

  // Reset page index on filter change
  React.useEffect(() => {
    setCurrentPage(1);
  }, [activeSubTab, selectedDomain, localSearch, sortBy]);

  // Fetch real hotspot candidates from backend
  React.useEffect(() => {
    const fetchHotspots = async () => {
      try {
        const candidates = await listTopicCandidates({ limit: 20 });
        if (candidates && candidates.length > 0) {
          const mappedHotspots: HotspotItem[] = candidates.map((c: any) => ({
            id: c.id || `hot-${Date.now()}`,
            title: c.title || '',
            domain: 'General',
            heatScore: c.metadata_json?.heat_score ?? 50,
            ctrPrediction: '2.5% - 4.0% CTR',
            wordsEstimate: 3500,
            abstract: c.hook || c.summary || '',
            styleRecommendation: '技术深度流',
            evidenceSource: c.evidence_urls?.length 
              ? c.evidence_urls.map((url: string) => ({ title: url.split('/').pop() || url, url, reliability: 'Medium' as const }))
              : c.source_url ? [{ title: c.source_url.split('/').pop() || c.source_url, url: c.source_url, reliability: 'Medium' as const }] : [],
          }));
          setHotspots(prev => [...mappedHotspots, ...prev]);
        }
      } catch {
        // Keep mock data as fallback
      }
    };
    fetchHotspots();
  }, []);

  // Auto-dismiss toast notification
  React.useEffect(() => {
    if (toastNotification) {
      const timer = setTimeout(() => {
        setToastNotification(null);
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [toastNotification]);

  // Simulated auto-hotspots database with timestamps
  const [hotspots, setHotspots] = useState<HotspotItem[]>([
    {
      id: 'hot-1',
      title: 'DeepSeek-R1 本地蒸馏小模型：使用 WebAssembly 与静态 SIMD 削减 75% 边缘客户端流式推理延迟',
      domain: 'LLM Reasoning & Client Optimization',
      heatScore: 98,
      ctrPrediction: '4.2% - 5.8% CTR',
      wordsEstimate: 4500,
      abstract: '深入 Wasm 与 Llama.cpp 底层，将 Llama-3-8B 蒸馏微调后模型压缩。利用端侧算力及 SIMD 指令并行动作，在离线场景下实现极速流式吞吐。',
      styleRecommendation: '动手实战流：提供极致 C++ 与 Rust 胶水适配源码，展示 Chrome DevTools 内存 Profiling 指标',
      evidenceSource: [
        { title: 'WebAssembly SIMD extensions specification v2', url: 'https://github.com/WebAssembly/simd', reliability: 'High' },
        { title: 'Edge Reasoning Optimization via Distillation', url: 'https://arxiv.org/abs/2405.1232', reliability: 'High' }
      ],
      timestamp: '10:00:15'
    },
    {
      id: 'hot-2',
      title: '美团大规模 GraphRAG 内存雪崩剖析：无冲突静态平铺高维 HNSW 索引重排技术规避 SRE 频繁 OOM',
      domain: 'RAG Systems & Vector Indices',
      heatScore: 94,
      ctrPrediction: '3.6% - 4.9% CTR',
      wordsEstimate: 4800,
      abstract: '工业级图检索在实体解析 (Entity Resolution) 和多路召回重排时容易耗尽 GC 内存。利用 C++ 开发的指针池，将高维节点向量强制内存平铺，能够抑制 JVM 堆频繁 Full GC。',
      styleRecommendation: '行业深度流：带线上高低水位拓扑 Diff 架构线框图，强调工程避坑指标',
      evidenceSource: [
        { title: 'Scalable Graph Neural Retrieval in Practice', url: 'https://tech.meituan.com/graphrag-scalability', reliability: 'High' }
      ],
      timestamp: '09:55:00'
    },
    {
      id: 'hot-3',
      title: '排查 K8s HPA 下的大模型长连接：Node 异步 Event Loop 背压控流防止高频 Webhook 写挂',
      domain: 'High Concurrency & Event Loop',
      heatScore: 91,
      ctrPrediction: '3.0% - 4.2% CTR',
      wordsEstimate: 3500,
      abstract: '由于大模型 SSE (Server-Sent Events) 输出速率过重，而下游消费者解析阻塞，最终触发 Node stream 的 Write Buffer 挂起倾斜。本研究针对 WritableStream 的 drain 信号自制了一个背压缓冲区来降低 CPU 损耗。',
      styleRecommendation: '技术八股流：解密 Chrome V8 事件循环底蕴及 Stream Writable _write 背压底层原理',
      evidenceSource: [
        { title: 'Event Loop backpressure mechanics explained', url: 'https://nodejs.org/api/stream.html', reliability: 'High' }
      ],
      timestamp: '09:47:12'
    },
    {
      id: 'hot-4',
      title: '基于 Spanner 2PC 分布式共识协议的大模型 Action 执行状态双写自愈架构设计',
      domain: 'Distributed Consensus & Agents',
      heatScore: 89,
      ctrPrediction: '2.8% - 3.7% CTR',
      wordsEstimate: 4000,
      abstract: '为了对齐三方金融扣款 API 与本地向量索引更新，基于 Paxos 和两阶段加锁进行模型外包装。对 TrueTime 虚拟窗口提供时间边界保障，从而实现柔性最终一致性。',
      styleRecommendation: '动手实战流：配 TypeScript 开发的柔性事务执行器 Spanner-Agent-Lock 完整项目代码',
      evidenceSource: [
        { title: 'Spanner: Google’s Globally-Distributed Database', url: 'https://research.google/pubs/pub39966/', reliability: 'High' }
      ],
      timestamp: '09:30:00'
    }
  ]);

  // Real-time continuous background hotspot collection simulation
  React.useEffect(() => {
    const intervalTime = 12000; // Poll every 12 seconds
    const interval = setInterval(() => {
      const selectedPoolItem = NEW_HOTSPOTS_POOL[livePoolIndex % NEW_HOTSPOTS_POOL.length];
      const formatTime = new Date().toLocaleTimeString('zh-CN', { hour12: false });
      
      const newLiveHotspot: HotspotItem = {
        id: `hot-live-${Date.now()}`,
        title: selectedPoolItem.title,
        domain: selectedPoolItem.domain,
        heatScore: selectedPoolItem.heatScore,
        ctrPrediction: selectedPoolItem.ctrPrediction,
        wordsEstimate: selectedPoolItem.wordsEstimate,
        abstract: selectedPoolItem.abstract,
        styleRecommendation: selectedPoolItem.styleRecommendation,
        evidenceSource: selectedPoolItem.evidenceSource as any,
        timestamp: formatTime
      };

      setHotspots((prev) => {
        // Avoid adding duplicated titles in adjacent intervals
        if (prev.length > 0 && prev[0].title === newLiveHotspot.title) {
          return prev;
        }
        return [newLiveHotspot, ...prev];
      });
      setLivePoolIndex((prev) => prev + 1);
    }, intervalTime);

    return () => clearInterval(interval);
  }, [livePoolIndex]);

  const handleRefreshHotspots = async () => {
    setIsRefreshing(true);
    try {
      // Fetch new hotspot topics from backend
      const collection = await collectHotspotTopics();
      if (collection && collection.candidates && collection.candidates.length > 0) {
        const formatTime = new Date().toLocaleTimeString('zh-CN', { hour12: false });
        const newHotspots: HotspotItem[] = collection.candidates.map((c: any) => ({
          id: c.id || `hot-${Date.now()}`,
          title: c.title || '',
          domain: 'General',
          heatScore: c.metadata_json?.heat_score ?? 50,
          ctrPrediction: '2.5% - 4.0% CTR',
          wordsEstimate: 3500,
          abstract: c.hook || c.summary || '',
          styleRecommendation: '技术深度流',
          evidenceSource: c.evidence_urls?.length 
            ? c.evidence_urls.map((url: string) => ({ title: url.split('/').pop() || url, url, reliability: 'Medium' as const }))
            : c.source_url ? [{ title: c.source_url.split('/').pop() || c.source_url, url: c.source_url, reliability: 'Medium' as const }] : [],
          timestamp: formatTime,
        }));
        setHotspots(prev => [...newHotspots, ...prev]);
        alert(`✓ 已从后端采集 ${newHotspots.length} 个新热点选题！`);
      } else {
        // Fallback to mock data if backend returns empty
        const formatTime = new Date().toLocaleTimeString('zh-CN', { hour12: false });
        const forceItem1 = NEW_HOTSPOTS_POOL[1];
        const forceItem2 = NEW_HOTSPOTS_POOL[2];
        const live1: any = { id: `hot-manual-1-${Date.now()}`, ...forceItem1, timestamp: formatTime };
        const live2: any = { id: `hot-manual-2-${Date.now()}`, ...forceItem2, timestamp: formatTime };
        setHotspots(prev => [live1, live2, ...prev]);
        alert('✓ 选题库已从本地候选池汇入 2 篇热点选题！');
      }
    } catch {
      // Fallback to mock data on error
      const formatTime = new Date().toLocaleTimeString('zh-CN', { hour12: false });
      const forceItem1 = NEW_HOTSPOTS_POOL[1];
      const forceItem2 = NEW_HOTSPOTS_POOL[2];
      const live1: any = { id: `hot-manual-1-${Date.now()}`, ...forceItem1, timestamp: formatTime };
      const live2: any = { id: `hot-manual-2-${Date.now()}`, ...forceItem2, timestamp: formatTime };
      setHotspots(prev => [live1, live2, ...prev]);
      alert('✓ 选题库已从本地候选池汇入 2 篇热点选题！');
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleProcessUserInput = (e: React.FormEvent) => {
    e.preventDefault();
    if (!userTheme.trim()) {
      alert('请输入基本的主题思想或原始观点！');
      return;
    }
    setIsProcessingInput(true);
    setUserGeneratedTopic(null);

    setTimeout(() => {
      setIsProcessingInput(false);
      setUserGeneratedTopic({
        id: `user-topic-${Date.now()}`,
        title: `解密 『${userTheme}』之工业级极限自愈与代码重构全实录`,
        domain: 'Custom User Idea Incubation',
        heatScore: 88,
        ctrPrediction: '3.2% - 4.5% CTR',
        wordsEstimate: 4200,
        abstract: `系统基于用户给出的输入观点【${userViewpoint || '暂无指明'}】及素材引用，自动化提纯出围绕“${userTheme}”的针对性调优。重点攻关高并发故障逃生自愈、高饱和代码重配。`,
        styleRecommendation: '实践剖析流：聚焦真实案例的线上事故 Diff，配合 120 行高纯度 TS 实战代码片段',
        evidenceSource: [
          { title: userTheme, url: userLink || 'Local Scratchpad', reliability: 'Medium' }
        ]
      });
    }, 1500);
  };

  const handleImportAndPlan = async (topic: any) => {
    const existing = articles.find(a => a.title === topic.title);
    if (existing) {
      alert(`此选题大纲已导入！正在直接跳转至写作工作台...`);
      onSetTab('workbench');
      return;
    }

    try {
      // Call real backend adopt API
      const result = await adoptTopicCandidate(topic.id, selectedSeriesId);
      if (result && result.article) {
        const newArt: Article = {
          id: result.article.id,
          title: result.article.confirmed_title || result.article.seed_title || topic.title,
          status: mapArticleStatus(result.article.status),
          type: topic.styleRecommendation?.includes('实战') ? '动手实战' : topic.styleRecommendation?.includes('深度') ? '行业深度' : '技术八股',
          createdAt: result.article.created_at || new Date().toISOString(),
          updatedAt: result.article.updated_at || new Date().toISOString(),
          abstract: result.article.summary || topic.abstract || '',
          targetWords: result.article.target_word_count || topic.wordsEstimate || 2500,
          actualWords: result.article.actual_word_count || 0,
          writingStyle: topic.styleRecommendation || '',
          hookScene: '',
          outline: [],
          titleCandidates: [],
          publications: [],
          researchReport: {
            summary: topic.abstract || '',
            sources: (topic.evidenceSource || []).map((s: any) => ({ ...s, extract: '' })),
            coveragePercent: 0,
            evidenceGaps: []
          },
          qualityIssues: []
        };
        setArticles(prev => [newArt, ...prev]);
        onSelectArticle?.(newArt.id);
        alert(`🎉 选题采纳成功！后端已创建文章 [${result.article.id.slice(0, 8)}]。正在跳转写作工作台...`);
        onSetTab('workbench');
      }
    } catch (error) {
      // Fallback: create local article if backend fails
      const newArtId = `art-${Date.now()}`;
      const newArt: Article = {
        id: newArtId,
        title: topic.title,
        status: '待写作',
        type: topic.styleRecommendation?.includes('实战') ? '动手实战' : topic.styleRecommendation?.includes('深度') ? '行业深度' : '技术八股',
        createdAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
        updatedAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
        abstract: topic.abstract,
        targetWords: topic.wordsEstimate,
        actualWords: 0,
        writingStyle: topic.styleRecommendation,
        hookScene: '',
        outline: [],
        titleCandidates: [],
        publications: [],
        researchReport: {
          summary: topic.abstract,
          sources: (topic.evidenceSource || []).map((s: any) => ({ ...s, extract: '' })),
          coveragePercent: 0,
          evidenceGaps: []
        },
        qualityIssues: []
      };
      setArticles(prev => [newArt, ...prev]);
      onSelectArticle?.(newArtId);
      alert(`⚠️ 后端连接失败，已创建本地草稿。正在跳转写作工作台...`);
      onSetTab('workbench');
    }
  };

  const mapArticleStatus = (status: string): any => {
    const statusMap: Record<string, any> = {
      'draft': '待写作', 'researching': '待研究', 'writing': '写作中',
      'reviewing': '待预览', 'previewed': '已预览', 'ready_to_publish': '待全网发布',
      'published': '已发布', 'archived': '已归档',
    };
    return statusMap[status] || status;
  };

  const getThemeAccentClass = (type: 'text' | 'bg' | 'border' | 'btn' | 'badge') => {
    if (accentColor === 'green') {
      if (type === 'text') return 'text-emerald-600 dark:text-emerald-400';
      if (type === 'bg') return 'bg-emerald-600 hover:bg-emerald-700 text-white';
      if (type === 'border') return 'border-emerald-500/30';
      if (type === 'btn') return 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300';
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50';
    } else if (accentColor === 'brown') {
      if (type === 'text') return 'text-amber-700 dark:text-amber-400';
      if (type === 'bg') return 'bg-amber-700 hover:bg-amber-800 text-white';
      if (type === 'border') return 'border-amber-600/30';
      if (type === 'btn') return 'bg-amber-50 text-amber-900 dark:bg-amber-955/35 dark:text-amber-300';
      return 'bg-amber-100 text-amber-900 dark:bg-amber-955/50';
    } else {
      if (type === 'text') return 'text-blue-600 dark:text-blue-400';
      if (type === 'bg') return 'bg-blue-600 hover:bg-blue-700 text-white';
      if (type === 'border') return 'border-blue-500/30';
      if (type === 'btn') return 'bg-blue-50 text-blue-800 dark:bg-blue-950/35 dark:text-blue-300';
      return 'bg-blue-100 text-blue-700 dark:bg-blue-950/50';
    }
  };

  return (
    <div className={`flex-1 flex flex-col h-full min-h-0 overflow-hidden ${
      isDarkMode ? 'bg-slate-950 text-slate-100' : 'bg-slate-50 text-slate-850'
    }`}>
      {/* Main tab switchers */}
      <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-hidden">
        {/* Left tall or top horizontal rail navigator */}
        <div className={`w-full lg:w-64 border-b lg:border-b-0 lg:border-r flex flex-row lg:flex-col p-2 lg:p-3 items-center lg:items-stretch justify-between shrink-0 overflow-x-auto lg:overflow-x-visible custom-scrollbar ${
          isDarkMode ? 'bg-slate-905 border-slate-855' : 'bg-slate-100/40 border-slate-205 shadow-xs'
        }`}>
          <div className="flex flex-row lg:flex-col items-center lg:items-stretch gap-1.5 w-full lg:space-y-1 shrink-0 lg:shrink">
            <h4 className="hidden lg:block font-bold text-[9px] font-mono text-gray-500 px-3 tracking-widest uppercase mb-2">
              选题数据管理台 (Topic Panel)
            </h4>

            <div className="flex flex-row lg:flex-col gap-1 lg:space-y-1">
              {[
                { id: 'hotspots-all', name: '🔥 自动全域热点池', desc: 'All Scraped Pools', icon: Flame },
                { id: 'planner', name: '📚 长期系列规划', desc: 'Series Planner Hub', icon: Layers },
              ].map((subTab) => {
                const isSelected = activeSubTab === subTab.id;
                const Icon = subTab.icon;

                return (
                  <button
                    key={subTab.id}
                    onClick={() => setActiveSubTab(subTab.id as any)}
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
                    <div className="flex items-center space-x-1.5 lg:space-x-2 truncate">
                      <Icon size={12} className={isSelected ? getThemeAccentClass('text') : 'text-slate-400'} />
                      <div className="truncate text-left leading-tight">
                        <p className="text-[11px] truncate">{subTab.name}</p>
                        <p className="hidden md:block text-[8px] opacity-50 truncate font-mono">{subTab.desc}</p>
                      </div>
                    </div>
                    <ChevronRight size={10} className="hidden lg:block opacity-40 ml-2" />
                  </button>
                );
              })}
            </div>
          </div>

          <div className="hidden lg:block p-3 rounded-lg border bg-amber-500/5 border-amber-500/20 text-[10px] space-y-1 self-stretch shrink-0">
            <div className="flex items-center text-amber-500 font-bold font-mono">
              <AlertCircle size={10} className="mr-1" />
              <span>智能决策建议：</span>
            </div>
            <p className="text-gray-400 font-sans leading-relaxed">
              当前系统运行于**后台纯数据集成管理模式**下。全域热点池数据自动高频抓取上新，支持管理员决策与一键投递规格。
            </p>
          </div>
        </div>

        {/* Content Viewport - Snug/Tight layout with sticky controls and non-scrolling page boundaries */}
        <div className="flex-1 overflow-y-auto lg:overflow-hidden p-3 md:p-4 pb-28 flex flex-col space-y-3.5 bg-slate-50 dark:bg-slate-950">

          {/* SubTab: Series Planner */}
          {activeSubTab === 'planner' && (
            <SeriesPlanner
              seriesList={seriesList}
              setSeriesList={() => {}}
              articles={articles}
              setArticles={setArticles}
              isDarkMode={isDarkMode}
              accentColor={accentColor}
              onSetTab={onSetTab}
              selectedArticleId={selectedArticleId}
              onSelectArticle={onSelectArticle ? (id) => onSelectArticle(id || '') : undefined}
            />
          )}

          {/* SubTab 1: Auto Hotspots */}
          {activeSubTab === 'hotspots-all' && (() => {
            const isAcademic = (hot: HotspotItem) => {
              return hot.evidenceSource.some(ev => 
                ev.title.toLowerCase().includes('arxiv') || 
                ev.title.toLowerCase().includes('scholar')
              );
            };

            const processedHotspots = hotspots.filter(hot => {
              // Left tab filtering
              if (activeSubTab === 'hotspots-academic' && !isAcademic(hot)) return false;
              if (activeSubTab === 'hotspots-engineering' && isAcademic(hot)) return false;
              
              // Domain category filtering
              if (selectedDomain !== 'ALL' && !hot.domain.toLowerCase().includes(selectedDomain.toLowerCase())) return false;
              
              // Local search query filtering
              const searchMatch = !localSearch || 
                hot.title.toLowerCase().includes(localSearch.toLowerCase()) || 
                hot.abstract.toLowerCase().includes(localSearch.toLowerCase()) ||
                hot.domain.toLowerCase().includes(localSearch.toLowerCase());
                
              // Global search query filtering
              const globalMatch = !globalSearchQuery || 
                hot.title.toLowerCase().includes(globalSearchQuery.toLowerCase()) || 
                hot.abstract.toLowerCase().includes(globalSearchQuery.toLowerCase());
                
              return searchMatch && globalMatch;
            });

            // Sorting
            processedHotspots.sort((a, b) => {
              if (sortBy === 'heatScore') {
                return b.heatScore - a.heatScore;
              } else {
                return b.wordsEstimate - a.wordsEstimate;
              }
            });

            // Pagination calculations
            const totalItems = processedHotspots.length;
            const totalPages = Math.max(1, Math.ceil(totalItems / itemsPerPage));
            const startIndex = (currentPage - 1) * itemsPerPage;
            const paginatedHotspots = processedHotspots.slice(startIndex, startIndex + itemsPerPage);

            // Pages dynamic telemetry "页面收集程度不同"
            const pageCollectionDegree = 
              currentPage === 1 ? '100% (完全校对已入池)' : 
              currentPage === 2 ? '91% (高性能就位已缓存)' : 
              currentPage === 3 ? '83% (远端索引惰性就绪)' : '74% (异步深网解压加载)';

            const pageCollectionColor = 
              currentPage === 1 ? 'text-emerald-500 bg-emerald-500/10' : 
              currentPage === 2 ? 'text-blue-500 bg-blue-500/10' : 
              currentPage === 3 ? 'text-amber-500 bg-amber-500/10' : 'text-rose-500 bg-rose-500/10';

            return (
              <div className="flex-1 flex flex-col min-h-0 space-y-3.5 text-left">
                {/* Embedded control deck instead of global search */}
                <div className="flex flex-col gap-4 bg-slate-50 dark:bg-slate-900 p-4 rounded-xl border">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div>
                      <h3 className="font-bold text-sm text-slate-900 dark:text-white flex items-center gap-1.5">
                        <Flame size={14} className="text-red-500 animate-pulse" />
                        <span>网捕技术全域热潮数据源诊断 (
                          {activeSubTab === 'hotspots-all' ? '全部热点池' : 
                           activeSubTab === 'hotspots-academic' ? '顶刊文献雷达' : '开源实践热哨'}
                        )</span>
                      </h3>
                      <p className="text-[10px] text-gray-500 mt-0.5 font-sans">
                        已打通 Scholar、arXiv、GitHub Trends 及中文各大自媒体技术社群，为您实时捕捉前沿爆款
                      </p>
                    </div>
                    
                    <button
                      type="button"
                      onClick={handleRefreshHotspots}
                      disabled={isRefreshing}
                      className={`px-3 py-1.5 rounded-lg border flex items-center space-x-1.5 font-mono text-[10px] font-bold ${getThemeAccentClass('btn')} shrink-0`}
                    >
                      <RefreshCw size={11} className={isRefreshing ? 'animate-spin' : ''} />
                      <span>{isRefreshing ? '正在深网爬取...' : '一键刷新捕获最新'}</span>
                    </button>
                  </div>

                  {/* Local filtering desk */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-3 border-t border-slate-200 dark:border-slate-800">
                    {/* Keyword Input */}
                    <div className="relative flex items-center">
                      <input
                        type="text"
                        placeholder="🔍 关键词局部快滤..."
                        value={localSearch}
                        onChange={(e) => setLocalSearch(e.target.value)}
                        className={`w-full px-3 py-1.5 text-[11px] rounded border focus:outline-none focus:ring-1 focus:ring-blue-500 font-medium transition-all ${
                          isDarkMode 
                            ? 'border-slate-800 text-white bg-slate-955 placeholder-gray-500' 
                            : 'border-slate-200 text-slate-800 bg-white placeholder-gray-400'
                        }`}
                      />
                      {localSearch && (
                        <button onClick={() => setLocalSearch('')} className="absolute right-2 text-[10px] text-gray-400">✕</button>
                      )}
                    </div>

                    {/* Domain filter */}
                    <div>
                      <select
                        value={selectedDomain}
                        onChange={(e) => setSelectedDomain(e.target.value)}
                        className={`w-full px-2 py-1.5 text-[11px] rounded border focus:outline-none focus:ring-1 focus:ring-blue-500 font-sans ${
                          isDarkMode ? 'border-slate-805 text-white bg-slate-955' : 'border-slate-200 text-slate-800 bg-white shadow-xs'
                        }`}
                      >
                        <option value="ALL">全部技术分类 (All Domains)</option>
                        <option value="LLM Reasoning">AI 推理 & 优化 (LLM/Client)</option>
                        <option value="High Concurrency">高并发 & 背压 (Concurrency)</option>
                        <option value="Distributed">分布式共识 (Distributed)</option>
                        <option value="RAG Systems">知识检索图 RAG (RAG/Vector)</option>
                      </select>
                    </div>

                    {/* Sort Order */}
                    <div>
                      <select
                        value={sortBy}
                        onChange={(e) => setSortBy(e.target.value as any)}
                        className={`w-full px-2 py-1.5 text-[11px] rounded border focus:outline-none focus:ring-1 focus:ring-blue-500 font-sans ${
                          isDarkMode ? 'border-slate-805 text-white bg-slate-955' : 'border-slate-200 text-slate-800 bg-white shadow-xs'
                        }`}
                      >
                        <option value="heatScore">按照热点评分排序</option>
                        <option value="wordsEstimate">按照推荐字数排序</option>
                      </select>
                    </div>
                  </div>

                  {/* Summary Bar */}
                  <div className="flex flex-col sm:flex-row gap-2 justify-between items-stretch sm:items-center bg-[#eaeffa] dark:bg-[#11192e] p-2 px-3 rounded-lg text-[10px] font-mono text-slate-500 border border-blue-500/10 dark:border-blue-900/10">
                    <span className="flex items-center gap-1">
                      ℹ️ 共匹配筛选出 <strong className={isDarkMode ? 'text-blue-400' : 'text-blue-750'}>{totalItems}</strong> 篇候选流式热点 · 当前第 {currentPage} 页
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="flex items-center gap-1">
                        📡 页面收集完整度: 
                        <strong className={`px-1.5 py-0.5 rounded font-bold ${pageCollectionColor}`}>
                          {pageCollectionDegree}
                        </strong>
                      </span>
                    </div>
                  </div>
                </div>

                {/* Hotspot table presentation - completely non-scrolling, fixed table layout */}
                <div className="flex-1 min-h-0 overflow-hidden border rounded-xl bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 flex flex-col justify-between">
                  {paginatedHotspots.length === 0 ? (
                    <div className="py-16 text-center text-gray-400 border border-dashed rounded-xl font-mono text-xs">
                      ⚠️ 暂无匹配您筛选条件的技术爆款选题。可以尝试清空搜索词或切换方向分流。
                    </div>
                  ) : (
                    <>
                      {/* Desktop Table View */}
                      <div className="hidden md:block overflow-x-auto">
                        <table className="w-full text-left border-collapse table-fixed select-none text-[11px] leading-relaxed">
                          <thead>
                            <tr className="bg-slate-100/60 dark:bg-slate-950/40 border-b border-slate-200 dark:border-slate-800 font-mono text-slate-500 font-bold">
                              <th className="p-3 w-[150px] truncate text-[9.5px]">分类 / 领域</th>
                              <th className="p-3 text-[9.5px]">热点选题 & 主题摘要 (点击题目查看详情)</th>
                              <th className="p-3 w-[90px] text-center text-[9.5px]">热度指标</th>
                              <th className="p-3 w-[100px] text-center text-[9.5px]">预测 CTR</th>
                              <th className="p-3 w-[160px] text-center text-[9.5px]">快捷控制与处理</th>
                            </tr>
                          </thead>
                          <tbody>
                            {paginatedHotspots.map((hot) => (
                              <tr 
                                key={hot.id}
                                className="border-b border-slate-100 dark:border-slate-850 hover:bg-slate-50/60 dark:hover:bg-slate-950/20 transition-all"
                              >
                                {/* Classification Category Badges */}
                                <td className="p-3 w-[150px]">
                                  <span className="inline-block truncate max-w-[130px] px-1.5 py-0.5 rounded font-bold font-mono text-[8.5px] uppercase bg-blue-50 text-blue-750 dark:bg-blue-950/40 dark:text-blue-300">
                                    {hot.domain}
                                  </span>
                                </td>

                                {/* Hot Topic Title and abstract inline preview */}
                                <td className="p-3">
                                  <div className="space-y-1">
                                    <h4 
                                      onClick={() => {
                                        setSelectedHotspotForDetail(hot);
                                        setToastNotification(`正在加载《${hot.title.slice(0, 15)}...》的深层文献指标...`);
                                      }}
                                      className="font-bold text-[11px] text-slate-900 dark:text-white hover:text-blue-500 cursor-pointer transition-colors truncate"
                                    >
                                      {hot.title}
                                    </h4>
                                    <p className="text-[10px] text-gray-400 dark:text-gray-500 leading-normal truncate">
                                      {hot.abstract}
                                    </p>
                                  </div>
                                </td>

                                {/* Heat Score */}
                                <td className="p-3 w-[90px] text-center font-mono font-bold text-amber-500 text-[10px]">
                                  🔥 {hot.heatScore}
                                </td>

                                {/* CTR Score */}
                                <td className="p-3 w-[100px] text-center font-mono font-bold text-emerald-500 text-[10.5px]">
                                  🎯 {hot.ctrPrediction.split(' ')[0]}
                                </td>

                                {/* Action CTA Buttons */}
                                <td className="p-3 w-[160px] text-center">
                                  <div className="flex items-center justify-center gap-1.5">
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setSelectedHotspotForDetail(hot);
                                        setToastNotification(`已成功解析《${hot.title.slice(0, 15)}...》研究证据链！`);
                                      }}
                                      className="px-2.5 py-1 rounded border border-slate-205 dark:border-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 font-sans font-medium hover:text-blue-500 transition-colors"
                                    >
                                      查看详情
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setToastNotification(`正在深度为您立项：《${hot.title.slice(0, 15)}...》`);
                                        handleImportAndPlan(hot);
                                      }}
                                      className={`px-2.5 py-1 rounded text-white font-sans font-bold flex items-center justify-center transition-colors shadow-xs ${getThemeAccentClass('bg')}`}
                                    >
                                      选用导入
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      {/* Mobile Card View */}
                      <div className="block md:hidden divide-y divide-slate-100 dark:divide-slate-800 max-h-[380px] overflow-y-auto custom-scrollbar p-1">
                        {paginatedHotspots.map((hot) => (
                          <div 
                            key={hot.id}
                            className={`p-3 flex flex-col space-y-2.5 text-left text-xs ${
                              isDarkMode ? 'hover:bg-slate-950/20' : 'hover:bg-slate-50/60'
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <span className="px-1.5 py-0.5 rounded font-bold font-mono text-[8px] uppercase bg-blue-50 text-blue-755 dark:bg-blue-950/40 dark:text-blue-300">
                                {hot.domain}
                              </span>
                              <div className="flex items-center space-x-2 font-mono text-[9px]">
                                <span className="text-amber-500 font-bold">🔥 {hot.heatScore}</span>
                                <span className="text-emerald-500 font-bold">🎯 {hot.ctrPrediction.split(' ')[0]}</span>
                              </div>
                            </div>

                            <div className="space-y-1">
                              <h4 
                                onClick={() => {
                                  setSelectedHotspotForDetail(hot);
                                  setToastNotification(`正在加载《${hot.title.slice(0, 15)}...》的深层文献指标...`);
                                }}
                                className="font-bold text-[11px] leading-snug text-slate-900 dark:text-white hover:text-blue-500 cursor-pointer text-left transition-colors"
                              >
                                {hot.title}
                              </h4>
                              <p className="text-[10px] text-gray-400 dark:text-gray-500 leading-normal text-left">
                                {hot.abstract}
                              </p>
                            </div>

                            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100 dark:border-slate-850">
                              <button
                                type="button"
                                onClick={() => {
                                  setSelectedHotspotForDetail(hot);
                                  setToastNotification(`已成功解析《${hot.title.slice(0, 15)}...》研究证据链！`);
                                }}
                                className="px-3 py-1 rounded border border-slate-205 dark:border-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 font-sans font-medium transition-colors text-[10px]"
                              >
                                查看详情
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setToastNotification(`正在深度为您立项：《${hot.title.slice(0, 15)}...》`);
                                  handleImportAndPlan(hot);
                                }}
                                className={`px-3 py-1 rounded text-white font-sans font-bold flex items-center justify-center transition-colors shadow-xs text-[10px] ${getThemeAccentClass('bg')}`}
                              >
                                选用导入
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </div>

                {/* Pagination Controls */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between border-t border-slate-205 dark:border-slate-800 pt-3 font-mono text-[10px] shrink-0">
                    <div className="text-gray-400 font-sans">
                      第 <strong>{currentPage}</strong> / <strong>{totalPages}</strong> 页
                    </div>
                    <div className="flex items-center space-x-2">
                      <button
                        type="button"
                        disabled={currentPage === 1}
                        onClick={() => setCurrentPage(prev => Math.max(1, prev - 1))}
                        className={`px-3 py-1 rounded-lg border text-[9.5px] font-bold transition-all ${
                          currentPage === 1
                            ? 'opacity-40 cursor-not-allowed'
                            : isDarkMode 
                              ? 'bg-slate-900 border-slate-800 hover:bg-slate-800 text-white' 
                              : 'bg-white border-slate-200 hover:bg-slate-50 text-slate-800'
                        }`}
                      >
                        ◀ 上一页 (Prev)
                      </button>
                      <button
                        type="button"
                        disabled={currentPage === totalPages}
                        onClick={() => setCurrentPage(prev => Math.min(totalPages, prev + 1))}
                        className={`px-3 py-1 rounded-lg border text-[9.5px] font-bold transition-all ${
                          currentPage === totalPages
                            ? 'opacity-40 cursor-not-allowed'
                            : isDarkMode 
                              ? 'bg-slate-900 border-slate-800 hover:bg-slate-800 text-white' 
                              : 'bg-white border-slate-200 hover:bg-slate-50 text-slate-800'
                        }`}
                      >
                        下一页 (Next) ▶
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })()}





        </div>
      </div>

      {/* Floating Detailed Hotspot Overlay (Toast Modal) */}
      {selectedHotspotForDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          {/* Backdrop */}
          <div 
            className="absolute inset-0 bg-slate-900/60 backdrop-blur-xs transition-opacity" 
            onClick={() => setSelectedHotspotForDetail(null)} 
          />
          
          {/* Modal Card */}
          <div className={`relative max-w-lg w-full rounded-2xl p-6 shadow-2xl border transition-all animate-in fade-in zoom-in-95 duration-200 ${
            isDarkMode ? 'bg-slate-900 border-slate-800 text-white' : 'bg-white border-slate-200 text-slate-900'
          }`}>
            {/* Header */}
            <div className="flex items-start justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
              <div className="space-y-1">
                <span className="px-2 py-0.5 rounded text-[9px] font-bold font-mono uppercase bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-350">
                  {selectedHotspotForDetail.domain}
                </span>
                <h3 className="text-xs font-bold font-sans mt-2 leading-relaxed">
                  {selectedHotspotForDetail.title}
                </h3>
              </div>
              <button 
                onClick={() => setSelectedHotspotForDetail(null)}
                className="p-1 rounded-lg hover:bg-slate-150 dark:hover:bg-slate-800 text-gray-400 hover:text-gray-600 transition-colors ml-4"
              >
                ✕
              </button>
            </div>

            {/* Content */}
            <div className="mt-4 space-y-4 text-[11px] leading-relaxed text-left">
              {/* Abstract */}
              <div className="space-y-1 text-left">
                <span className="text-[9px] font-bold font-mono tracking-wider text-slate-400 uppercase block">💡 核心大纲要意 Theme Abstract</span>
                <p className="p-3 rounded-lg border text-slate-600 dark:text-slate-350 bg-slate-50 dark:bg-slate-950 border-slate-105 dark:border-slate-850">
                  {selectedHotspotForDetail.abstract}
                </p>
              </div>

              {/* Stats Grid */}
              <div className="grid grid-cols-2 gap-2.5">
                <div className="p-2 pb-2.5 rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-850">
                  <span className="text-[9px] text-slate-400 font-mono uppercase block">🔥 热点得分</span>
                  <span className="text-xs font-bold font-mono text-amber-500">{selectedHotspotForDetail.heatScore} / 100</span>
                </div>
                <div className="p-2 pb-2.5 rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-850">
                  <span className="text-[9px] text-slate-400 font-mono uppercase block">🎯 预测 CTR 转化</span>
                  <span className="text-xs font-bold font-mono text-emerald-500">{selectedHotspotForDetail.ctrPrediction}</span>
                </div>
                <div className="p-2 pb-2.5 rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-850">
                  <span className="text-[9px] text-slate-400 font-mono uppercase block">✨ 推荐写作规模</span>
                  <span className="text-[11px] font-bold font-mono text-slate-700 dark:text-slate-300">{selectedHotspotForDetail.wordsEstimate} 字左右</span>
                </div>
                <div className="p-2 pb-2.5 rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-850">
                  <span className="text-[9px] text-slate-400 font-mono uppercase block">🧭 最佳风格形态</span>
                  <span className="text-[10px] font-sans font-medium text-slate-700 dark:text-slate-300 line-clamp-1" title={selectedHotspotForDetail.styleRecommendation}>
                    {selectedHotspotForDetail.styleRecommendation}
                  </span>
                </div>
              </div>

              {/* Evidence Sources */}
              <div className="space-y-1.5 text-left">
                <span className="text-[9px] font-bold font-mono tracking-wider text-slate-400 uppercase block">📚 文献与可信数据佐证 (Evidence)</span>
                <div className="space-y-1.5">
                  {selectedHotspotForDetail.evidenceSource.map((ev, i) => (
                    <a
                      key={i}
                      href={ev.url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center justify-between p-2 rounded bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-850 hover:border-blue-500/30 text-blue-600 dark:text-blue-400 transition-colors"
                    >
                      <span className="font-sans font-medium truncate pr-2">[{ev.reliability}] {ev.title}</span>
                      <ArrowUpRight size={11} className="shrink-0" />
                    </a>
                  ))}
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="mt-5 pt-3 border-t border-slate-100 dark:border-slate-850 flex justify-end gap-2">
              <button
                onClick={() => setSelectedHotspotForDetail(null)}
                className={`px-3 py-1.5 rounded-lg text-[11px] font-medium border ${
                  isDarkMode ? 'border-slate-800 text-gray-300 hover:bg-slate-850' : 'border-slate-200 text-gray-600 hover:bg-slate-50'
                }`}
              >
                关闭
              </button>
              <button
                onClick={() => {
                  setSelectedHotspotForDetail(null);
                  setToastNotification(`已选用并导入选题：《${selectedHotspotForDetail.title.slice(0, 15)}...》`);
                  handleImportAndPlan(selectedHotspotForDetail);
                }}
                className={`px-4 py-1.5 rounded-lg text-[11px] font-bold flex items-center gap-1 shadow-xs transition-colors ${getThemeAccentClass('bg')}`}
              >
                <PlusSquare size={12} className="shrink-0" />
                立即选用并导入草稿 ➔
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Floating Sparkles Toast Alert */}
      {toastNotification && (
        <div className="fixed bottom-6 right-6 z-55 max-w-sm bg-slate-900/95 dark:bg-black/95 text-white p-3.5 rounded-xl shadow-2xl border border-blue-500/30 flex items-center space-x-2 text-xs animate-in slide-in-from-bottom-5 fade-in duration-200">
          <Sparkles className="text-amber-400 shrink-0 animate-pulse" size={13} />
          <span className="font-sans font-medium text-[11px]">{toastNotification}</span>
        </div>
      )}

    </div>
  );
}
