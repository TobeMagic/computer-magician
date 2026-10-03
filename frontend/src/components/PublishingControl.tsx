import React, { useState, useEffect } from 'react';
import {
  Share2,
  CheckCircle,
  AlertTriangle,
  Play,
  RefreshCw,
  GitBranch,
  XCircle,
  Link,
  History,
  Lock,
  Compass,
  ArrowRight
} from 'lucide-react';
import { Article, PublisherProof } from '../types';
import { publishArticle, getPublicationMatrix, getPlatformHealth, listCredentials } from '../api';

interface PublishingControlProps {
  articles: Article[];
  setArticles: React.Dispatch<React.SetStateAction<Article[]>>;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
}

export default function PublishingControl({
  articles,
  setArticles,
  isDarkMode,
  accentColor
}: PublishingControlProps) {
  // Select active article to publish
  const [selectedArticleId, setSelectedArticleId] = useState<string>('art-102');
  const [localFilterStatus, setLocalFilterStatus] = useState<string>('ALL');
  const [localSearchQuery, setLocalSearchQuery] = useState<string>('');
  const activeArticle = articles.find((art) => art.id === selectedArticleId) || articles[0];

  if (!activeArticle) {
    return (
      <div className="flex-1 flex items-center justify-center h-64 text-gray-400 text-xs font-mono">
        加载文章数据中...
      </div>
    );
  }

  const getThemeAccentClass = (type: 'text' | 'bg' | 'border' | 'btn') => {
    if (accentColor === 'blue') {
      if (type === 'text') return 'text-[#0077b6]';
      if (type === 'bg') return 'bg-[#0077b6] text-white';
      if (type === 'border') return 'border-[#0077b6]';
      return 'bg-blue-50 text-blue-800';
    } else if (accentColor === 'green') {
      if (type === 'text') return 'text-[#2d6a4f]';
      if (type === 'bg') return 'bg-[#2d6a4f] text-white';
      if (type === 'border') return 'border-[#2d6a4f]';
      return 'bg-emerald-50 text-emerald-800';
    } else {
      if (type === 'text') return 'text-[#7f5539]';
      if (type === 'bg') return 'bg-[#7f5539] text-white';
      if (type === 'border') return 'border-[#7f5539]';
      return 'bg-amber-50 text-amber-800';
    }
  };

  // Simulated live publish actions per node
  const [runningPlatforms, setRunningPlatforms] = useState<Record<string, boolean>>({});
  const [platformHealth, setPlatformHealth] = useState<Record<string, any>>({});

  // Fetch platform health data on mount
  useEffect(() => {
    const fetchPlatformHealth = async () => {
      try {
        const credentials = await listCredentials();
        const healthData: Record<string, any> = {};
        
        for (const cred of credentials) {
          try {
            const health = await getPlatformHealth(cred.platform);
            healthData[cred.platform] = health;
          } catch (err) {
            console.error(`Failed to fetch health for ${cred.platform}:`, err);
          }
        }
        
        setPlatformHealth(healthData);
      } catch (err) {
        console.error('Failed to fetch platform credentials:', err);
      }
    };

    fetchPlatformHealth();
  }, []);

  const executePublishFlow = async (platformId: string, actionType: 'publish' | 'reissue' | 'force' | 'retry') => {
    const existingProof = activeArticle.publications?.find((p) => p.platformId === platformId);
    if (existingProof?.status === 'Published' && actionType === 'publish') {
      const confirmForce = window.confirm(`[AImagician 安全拦截警告]：当前文章在平台 "${platformId}" 已存在明确发布证据。是否要进行【强制二次补发】？`);
      if (!confirmForce) return;
    }

    setRunningPlatforms((prev) => ({ ...prev, [platformId]: true }));

    try {
      const result = await publishArticle({
        article_id: activeArticle.id,
        mode: actionType === 'force' ? 'force_republish' : 'selected_platforms',
        platforms: [platformId],
        force_reason: actionType === 'force' ? 'Manual force publish' : undefined,
      });

      setArticles((prevArticles) =>
        prevArticles.map((art) => {
          if (art.id !== activeArticle.id) return art;
          const updatedPubs = art.publications ? [...art.publications] : [];
          const idx = updatedPubs.findIndex((p) => p.platformId === platformId);
          const customProof: PublisherProof = {
            platformId,
            platformName: existingProof?.platformName || platformId,
            status: result.queued_platforms?.includes(platformId) ? 'Published' : 'Failed',
            url: result.queued_platforms?.includes(platformId) ? `https://${platformId}.tech/aimagician/p/${result.job?.id?.slice(0, 8) || 'unknown'}` : undefined,
            draftId: result.job?.id,
            publishTime: new Date().toISOString().replace('T', ' ').slice(0, 16),
            retryCount: (existingProof?.retryCount || 0) + (actionType === 'retry' ? 1 : 0)
          };
          if (idx !== -1) updatedPubs[idx] = customProof;
          else updatedPubs.push(customProof);
          let nextStatus = art.status;
          if (art.status === '待全网发布' || art.status === '已预览') nextStatus = '已发布';
          return { ...art, publications: updatedPubs, status: nextStatus };
        })
      );
      alert(`✅ ${platformId} 发布任务已提交！Job ID: ${result.job?.id || 'pending'}`);
    } catch (error: any) {
      const msg = error?.message || error?.detail || 'Unknown error';
      alert(`❌ ${platformId} 发布失败: ${msg}`);
    } finally {
      setRunningPlatforms((prev) => ({ ...prev, [platformId]: false }));
    }
  };

  // Quick Action: publish to all active platforms at once (Preview or Core)
  const [broadcasting, setBroadcasting] = useState(false);
  const handleBroadCastToMatrix = () => {
    setBroadcasting(true);
    let delay = 0;
    const targetPlatforms = ['hexo', 'wechat', 'csdn', 'zhihu'];

    targetPlatforms.forEach((pId) => {
      setTimeout(() => {
        executePublishFlow(pId, 'publish');
      }, delay);
      delay += 800;
    });

    setTimeout(() => {
      setBroadcasting(false);
    }, delay + 1000);
  };

  return (
    <div className={`flex-1 flex flex-col h-screen overflow-hidden ${
      isDarkMode ? 'bg-[#0f1424] text-white' : 'bg-white text-slate-800'
    }`}>
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        
        {/* Supported Filter / Search Deck for Selection */}
        <div className="p-4 rounded-xl border border-slate-150 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs space-y-3">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div>
              <h4 className="font-extrabold text-[#0077b6] text-xs font-mono tracking-wide uppercase">
                🎯 投递稿件选择网关 (Select Dispatch Article With Filters)
              </h4>
              <p className="text-[10px] text-gray-500">
                支持快速切片过滤，选中卡片直接挂载发布流矩阵
              </p>
            </div>
            
            {/* Local fast filter state */}
            <div className="flex items-center space-x-1">
              {['ALL', '待写作', '已发布'].map(st => (
                <button
                  type="button"
                  key={st}
                  onClick={() => setLocalFilterStatus(st)}
                  className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border transition-colors ${
                    localFilterStatus === st 
                      ? 'bg-blue-600 border-blue-600 text-white' 
                      : 'bg-slate-50 dark:bg-slate-950 text-slate-500 border-slate-250 dark:border-slate-800 hover:bg-slate-100 dark:hover:bg-slate-900'
                  }`}
                >
                  {st === 'ALL' ? '全部状态' : st}
                </button>
              ))}
            </div>
          </div>

          {/* Grid list of articles */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2.5 max-h-36 overflow-y-auto pt-1 pr-1">
            {articles
              .filter(art => {
                const matchesStatus = localFilterStatus === 'ALL' || art.status === localFilterStatus;
                const matchesSearch = art.title.toLowerCase().includes(localSearchQuery.toLowerCase());
                return matchesStatus && matchesSearch;
              })
              .map(art => {
                const isActive = art.id === selectedArticleId;
                return (
                  <div
                    key={art.id}
                    onClick={() => setSelectedArticleId(art.id)}
                    className={`p-2 rounded-xl border text-left cursor-pointer transition-all select-none flex flex-col justify-between ${
                      isActive 
                        ? 'border-blue-500 bg-blue-500/10 dark:bg-blue-950/20 shadow-xs' 
                        : 'border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/50 hover:bg-slate-100 dark:hover:bg-slate-900'
                    }`}
                  >
                    <div className="space-y-1">
                      <div className="flex items-center justify-between">
                        <span className={`px-1.5 py-0.5 rounded text-[8px] font-mono font-extrabold ${
                          art.status === '已发布' 
                            ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/20 dark:text-emerald-400 border border-emerald-100 dark:border-emerald-900' 
                            : 'bg-amber-50 text-amber-700 dark:bg-amber-950/20 dark:text-amber-400 border border-amber-100 dark:border-amber-900'
                        }`}>
                          {art.status}
                        </span>
                        <span className="text-[8px] text-gray-400 font-mono">ID: {art.id}</span>
                      </div>
                      <h5 className="font-bold text-[11px] text-slate-850 dark:text-white line-clamp-1">
                        {art.title}
                      </h5>
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
        
        {/* Anti-double posting guidelines top box */}
        <div className="p-4 rounded-xl border border-dashed border-red-300 bg-red-50/10 flex items-start gap-3">
          <AlertTriangle className="text-rose-500 shrink-0 mt-0.5" size={16} />
          <div>
            <h4 className="font-bold text-xs text-rose-500 font-mono">
              [AImagician 投锁防覆盖协议：双重投递锁定组件已开启]
            </h4>
            <p className="text-[11px] text-gray-500 dark:text-slate-350 leading-relaxed mt-1">
              控制台自动截断对已发布 URL 的任何静默推包行为。若账号 Cookie 判定过期、或处于平台重机校验阶段，系统进入“待人工补发”挂线区。禁止无确认静默发布。
            </p>
          </div>
        </div>

        {/* Selected target metadata summary */}
        <div className="p-4 rounded-xl border bg-slate-50 dark:bg-[#151c2e] border-slate-200 dark:border-slate-800 flex items-center justify-between flex-wrap gap-4">
          <div>
            <span className="px-2 py-0.5 rounded text-[9px] font-mono font-bold bg-blue-100 text-blue-800 uppercase">
              Selected Target (核心拟分发稿)
            </span>
            <h3 className="font-bold text-xs md:text-sm mt-1.5 text-slate-800 dark:text-white">{activeArticle.title}</h3>
            <p className="text-[11px] text-gray-500 mt-0.5 font-mono">
              总字数: {activeArticle.actualWords || '0'} | 状态: {activeArticle.status}
            </p>
          </div>

          <button
            onClick={handleBroadCastToMatrix}
            disabled={broadcasting}
            className={`px-4 py-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white rounded-lg text-xs font-bold font-mono tracking-wide shadow flex items-center space-x-1.5`}
          >
            {broadcasting ? <RefreshCw size={12} className="animate-spin" /> : <Share2 size={13} />}
            <span>全渠道一键矩阵分发预览</span>
          </button>
        </div>

        {/* The Matrix tiers grids */}
        <div className="space-y-6">
          
          {/* TIER 1: PREVIEW TABS */}
          <div className="space-y-3">
            <h4 className="font-bold text-xs font-mono text-gray-400 tracking-wider">
              1. 预览先行与公众号草箱 (Preview Matrix)
            </h4>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {[
                { id: 'hexo', name: 'Hexo CLI Blog (公开前/预览首站)', action: 'SSH Push' },
                { id: 'wechat', name: '微信公众号 (官方草稿预览通道)', action: 'Draft Upload' }
              ].map((plat) => {
                const proof = activeArticle.publications?.find((p) => p.platformId === plat.id);
                const isWorking = runningPlatforms[plat.id];

                return (
                  <div
                    key={plat.id}
                    className="p-4 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-850 flex flex-col justify-between"
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <span className="text-[10px] uppercase font-mono text-gray-400">
                          {plat.action} Unit
                        </span>
                        <h5 className="font-bold text-xs text-slate-800 dark:text-white mt-0.5">
                          {plat.name}
                        </h5>
                      </div>

                      <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded ${
                        proof?.status === 'Published'
                          ? 'bg-emerald-100 text-emerald-800 font-bold'
                          : 'bg-stone-100 text-stone-500 dark:bg-slate-800 dark:text-slate-400'
                      }`}>
                        {proof?.status || 'UNPUBLISHED'}
                      </span>
                    </div>

                    {proof?.url && (
                      <div className="mt-3 p-2 bg-slate-50 dark:bg-slate-950 rounded border text-[10px] font-mono leading-relaxed space-y-1">
                        <p className="text-gray-400">证据 URL:</p>
                        <a href={proof.url} target="_blank" rel="noreferrer" className="text-blue-500 hover:underline break-all block">
                          {proof.url}
                        </a>
                        <p className="text-[9px] text-slate-500">
                          {proof.draftId && `草稿 token: ${proof.draftId}`} | 投送: {proof.publishTime}
                        </p>
                      </div>
                    )}

                    <div className="mt-4 flex justify-end space-x-1.5 text-[10px] font-mono select-none">
                      <button
                        onClick={() => executePublishFlow(plat.id, 'publish')}
                        disabled={isWorking}
                        className="px-2 py-1 bg-[#0077b6] text-white rounded hover:bg-sky-700 font-medium"
                      >
                        {isWorking ? '投包中...' : '普通发布'}
                      </button>
                      <button
                        onClick={() => executePublishFlow(plat.id, 'force')}
                        disabled={isWorking}
                        className="px-2 py-1 bg-rose-50 hover:bg-rose-100 text-rose-700 rounded border border-rose-200 dark:bg-rose-950/20"
                      >
                        强刷补发
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* TIER 2: CORE MATRIX */}
          <div className="space-y-3">
            <h4 className="font-bold text-xs font-mono text-gray-400 tracking-wider">
              2. 核心大自媒体矩阵 (Core Publisher Matrix / 自动推流)
            </h4>

            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
              {[
                { id: 'juejin', name: '稀土掘金开发者社区' },
                { id: 'csdn', name: 'CSDN 技术大本营' },
                { id: 'zhihu', name: '知乎技术专栏 & 回答' },
                { id: 'cnblogs', name: '博客园' },
                { id: 'bilibili', name: 'B 站图文专栏' },
                { id: 'infoq', name: 'InfoQ 极客写作池' }
              ].map((plat) => {
                const proof = activeArticle.publications?.find((p) => p.platformId === plat.id);
                const isWorking = runningPlatforms[plat.id];

                return (
                  <div
                    key={plat.id}
                    className="p-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-850 rounded-lg flex flex-col justify-between space-y-3"
                  >
                    <div>
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-xs text-slate-800 dark:text-white truncate">
                          {plat.name}
                        </span>
                        
                        <span className={`font-mono text-[9px] px-1.5 py-0.2 rounded font-bold ${
                          proof?.status === 'Published'
                            ? 'bg-emerald-100 text-emerald-800'
                            : proof?.status === 'Pending_Manual'
                            ? 'bg-amber-100 text-amber-800 animate-pulse'
                            : 'bg-slate-100 text-slate-400 dark:bg-slate-800'
                        }`}>
                          {proof?.status || '未开始'}
                        </span>
                      </div>

                      {proof?.errorMessage && (
                        <p className="text-[9px] text-rose-500 bg-rose-50 dark:bg-rose-950/20 leading-relaxed mt-1 p-1 rounded">
                          拦截故障: {proof.errorMessage}
                        </p>
                      )}

                      {proof?.url && (
                        <a
                          href={proof.url}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-2 text-[#0077b6] dark:text-[#38bdf8] hover:underline font-mono text-[10px] block truncate"
                        >
                          🔗 查看推包公开连接
                        </a>
                      )}
                    </div>

                    <div className="flex justify-between items-center text-[9px] font-mono border-t pt-2 dark:border-slate-800 select-none">
                      <button
                        onClick={() => executePublishFlow(plat.id, 'retry')}
                        className="text-gray-400 hover:text-slate-800"
                        title="触发手动补偿"
                      >
                        🔄 重试/补发
                      </button>

                      <button
                        onClick={() => executePublishFlow(plat.id, 'publish')}
                        disabled={isWorking}
                        className="px-2 py-0.5 bg-slate-900 border text-white dark:bg-slate-850 rounded hover:opacity-80"
                      >
                        {isWorking ? '正在投包...' : '开始投包'}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* TIER 3: EXPANSION DEVELOPERS */}
          <div className="space-y-3">
            <h4 className="font-bold text-xs font-mono text-gray-400 tracking-wider">
              3. 厂商开发者社区扩展矩阵 (Expansion Cloud Developers)
            </h4>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              {[
                { id: 'tencent_cloud', name: '腾讯云腾讯社区' },
                { id: 'alibaba_cloud', name: '阿里云栖开发者社' },
                { id: 'huawei_cloud', name: '华为云社区专家' },
                { id: 'volc_cloud', name: '火山引擎云技术社' }
              ].map((cloud) => {
                return (
                  <div
                    key={cloud.id}
                    className="p-3 rounded border bg-slate-100/50 dark:bg-slate-900/60 dark:border-slate-850 font-mono text-[10px] flex items-center justify-between"
                  >
                    <div>
                      <span className="text-gray-400 block text-[9px]">EXPANSION</span>
                      <span className="font-semibold">{cloud.name}</span>
                    </div>

                    <button
                      onClick={() => executePublishFlow(cloud.id, 'publish')}
                      className="px-1.5 py-0.5 bg-slate-900 text-white rounded text-[9px] hover:opacity-80"
                    >
                      投包
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
