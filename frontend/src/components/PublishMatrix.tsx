import React, { useState, useEffect } from 'react';
import { Send, AlertTriangle, ShieldCheck, Key, HelpCircle, Check, Shield, ExternalLink, Sparkles, RefreshCw } from 'lucide-react';
import { Article, PlatformCredential } from '../types';

interface PublishMatrixProps {
  currentArticle: Article;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  updateActiveArticle: (fields: Partial<Article>) => void;
  addLog: (msg: string) => void;
  getThemeAccentClass: (type: any) => string;
  onPublishAllPlatforms: () => void;
  onSetTab?: (tab: string) => void;
  credentials?: PlatformCredential[];
  setCredentials?: React.Dispatch<React.SetStateAction<PlatformCredential[]>>;
}

export default function PublishMatrix({
  currentArticle,
  isDarkMode,
  accentColor,
  updateActiveArticle,
  addLog,
  getThemeAccentClass,
  onPublishAllPlatforms,
  onSetTab,
  credentials = []
}: PublishMatrixProps) {
  // Published configurations
  const [reprintProtection, setReprintProtection] = useState('开启微信原创保护，设置本渠道为全网独家解密技术案例，严禁机翻引流');
  const [forceRepublish, setForceRepublish] = useState(false);
  
  // Selected platforms state (only healthy ones can be selected)
  const [selectedPlatformIds, setSelectedPlatformIds] = useState<string[]>([]);
  
  // Real-time matrix distribution status and progress
  const [publishingState, setPublishingState] = useState<'idle' | 'running' | 'done'>('idle');
  const [platformProgress, setPlatformProgress] = useState<Record<string, { pct: number; step: string }>>({});

  // Get only healthy credentials
  const healthyCredentials = credentials.filter(c => c.status === 'Healthy');
  const expiredCredentials = credentials.filter(c => c.status !== 'Healthy');

  // Multi-select select-all toggler targeting only HEALHY platforms
  const handleToggleSelectAllHealthy = () => {
    const allHealthyIds = healthyCredentials.map(c => c.id);
    if (selectedPlatformIds.length === allHealthyIds.length && allHealthyIds.length > 0) {
      setSelectedPlatformIds([]); // Clear
      addLog(`[Matrix] 取消勾选所有渠道发布目标`);
    } else {
      setSelectedPlatformIds(allHealthyIds); // Check all healthy
      addLog(`[Matrix] 一键多选成功：勾选了全部 ${allHealthyIds.length} 个 Healthy 健康态渠道`);
    }
  };

  const handleTogglePlatform = (id: string, isHealthy: boolean) => {
    if (!isHealthy) {
      addLog(`[Matrix Blocked] 无法选用此渠道！该平台当前状态不处于 Healthy 态，请前往平台账号会话执行登录自愈。`);
      return;
    }
    if (publishingState === 'running') {
      addLog(`[Matrix Blocked] 正在发布队列运行中，禁止临时修改群组目标！`);
      return;
    }
    if (selectedPlatformIds.includes(id)) {
      setSelectedPlatformIds(prev => prev.filter(item => item !== id));
      addLog(`[Matrix] 取消勾选发布渠道: [ID: ${id}]`);
    } else {
      setSelectedPlatformIds(prev => [...prev, id]);
      addLog(`[Matrix] 成功选用发布目标: [ID: ${id}]`);
    }
  };

  const handlePublishSelected = () => {
    if (selectedPlatformIds.length === 0) {
      alert('请至少选择一个 Healthy (健康) 发布平台交付投推！');
      return;
    }

    setPublishingState('running');
    
    // Check which selected platforms are already published and determine skipped vs active ones
    const alreadyPublishedIds = (currentArticle.publications || [])
      .filter(p => p.status === 'Published')
      .map(p => p.platformId);

    const initialProgress: Record<string, { pct: number; step: string }> = {};
    const skippedPlatforms: string[] = [];
    const activePlatformsToPublish: string[] = [];

    selectedPlatformIds.forEach(id => {
      const isAlreadyPublished = alreadyPublishedIds.includes(id);
      const plat = credentials.find(c => c.id === id);
      const platName = plat?.name || id;

      if (isAlreadyPublished && !forceRepublish) {
        skippedPlatforms.push(id);
        initialProgress[id] = { pct: 100, step: "🛡️ [Skip] 已发布 (过滤防重复投流中)" };
        addLog(`● [Matrix-Skip] 检测到平台 【${platName}】 已处于 Published 状态。已开启自动跳过防御以免重复发布！`);
      } else {
        activePlatformsToPublish.push(id);
        if (isAlreadyPublished && forceRepublish) {
          addLog(`● [Matrix-Force] 平台 【${platName}】 已处于已发布状态，但触发「强硬重发」机制，重新排队覆盖发表。`);
        }
        initialProgress[id] = { pct: 5, step: "🔄 [1/4] 分布式证书安全背签署中..." };
      }
    });

    setPlatformProgress(initialProgress);
    addLog(`● [Matrix Gateway] 启动群组并发投流发布。当前选定渠道: ${selectedPlatformIds.length} 个 (激活推送: ${activePlatformsToPublish.length} 个, 避让跳过: ${skippedPlatforms.length} 个)`);

    // If there are no active platforms to publish because everything got skipped
    if (activePlatformsToPublish.length === 0) {
      setTimeout(() => {
        setPublishingState('done');
        addLog(`✓ [Matrix Completion] 勾选的已发布渠道已全部成功规避。已签署存盘资产幂等性校验。`);
        
        // Wait a small delay before completing globally
        setTimeout(() => {
          onPublishAllPlatforms();
        }, 800);
      }, 1000);
      return;
    }

    let currentPct = 5;
    const interval = setInterval(() => {
      currentPct += 15;
      if (currentPct >= 100) {
        clearInterval(interval);
        
        const finalProgress = { ...platformProgress };
        selectedPlatformIds.forEach(id => {
          if (skippedPlatforms.includes(id)) {
            finalProgress[id] = { pct: 100, step: "🛡️ [Skip] 已发布 (过滤防重复投流中)" };
          } else {
            finalProgress[id] = { pct: 100, step: "✅ 发布成功 (Evidence Locked & Published)" };
          }
        });
        setPlatformProgress(finalProgress);
        setPublishingState('done');
        
        // Update publications status inside article
        const updatedPublications = (currentArticle.publications || []).map(p => {
          if (selectedPlatformIds.includes(p.platformId)) {
            const isSkipped = skippedPlatforms.includes(p.platformId);
            if (!isSkipped) {
              return {
                ...p,
                status: 'Published' as const,
                publishTime: new Date().toISOString().replace('T', ' ').slice(0, 19),
                url: p.url || `https://mp.weixin.qq.com/s/simulated-url-${p.platformId}`
              };
            }
          }
          return p;
        });

        const names = credentials.filter(c => activePlatformsToPublish.includes(c.id)).map(c => c.name).join('、');
        updateActiveArticle({ status: '已发布', publications: updatedPublications });
        addLog(`✓ [Matrix Action] 成功向核心矩阵【${names}】投递流控任务。秒级发布成功！数据库状态更名 ➔ [已发布]`);
        
        // Wait a small delay before completing globally
        setTimeout(() => {
          onPublishAllPlatforms();
        }, 800);
      } else {
        setPlatformProgress(prev => {
          const updated = { ...prev };
          activePlatformsToPublish.forEach(id => {
            let stepText = "🔄 [2/4] CDN 图像及多维静态池级联迁移中...";
            if (currentPct > 35 && currentPct <= 65) stepText = "📝 [3/4] 接口适配及 HTML 自愈渲染...";
            if (currentPct > 65 && currentPct < 95) stepText = "🚀 [4/4] 核心管道秒级推送发布...";
            if (currentPct >= 95) stepText = "⚡ [100%] 正在抓取公开 Evidence URL...";
            
            updated[id] = { pct: currentPct, step: stepText };
          });
          // Ensure skipped remain at 100
          skippedPlatforms.forEach(id => {
            updated[id] = { pct: 100, step: "🛡️ [Skip] 已发布 (过滤防重复投流中)" };
          });
          return updated;
        });
      }
    }, 500);
  };

  return (
    <div className="space-y-4 max-w-5xl animate-fade">
      
      {/* 1. Direct login self-healing redirect banner if dirty platforms exist */}
      {expiredCredentials.length > 0 && (
        <div className="p-4 bg-rose-50 border border-rose-250 dark:bg-rose-950/25 dark:border-rose-900/50 rounded-xl space-y-3 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-start space-x-3 text-left">
            <AlertTriangle className="text-rose-500 shrink-0 mt-0.5 animate-pulse" size={16} />
            <div className="space-y-0.5">
              <h4 className="text-xs font-bold font-mono text-rose-800 dark:text-rose-400">
                ⚠️ [发现失效自媒体账号凭据] 需要登录状态失效自愈 ({expiredCredentials.length} Platforms Session Expired)
              </h4>
              <p className="text-[11px] text-slate-600 dark:text-gray-400 leading-relaxed font-sans">
                检测到有 {expiredCredentials.length} 个平台（如 {expiredCredentials.map(e => e.name).join('、')}）登录会话已断开。
                生文发布前在此<strong>不支持</strong>临时进行验证码自愈。请跳转账号管理页一键自愈。
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => {
              if (onSetTab) {
                onSetTab('login');
                addLog(`➔ [Publish Redirect] 用户点击一键跳转，正在转入「平台账号会话」管理页面执行零故障自愈...`);
              }
            }}
            className="px-3.5 py-2 font-sans font-bold text-xs text-white rounded-lg bg-rose-600 hover:bg-rose-700 shadow-md shrink-0 active:scale-95 transition-transform flex items-center space-x-1.5"
          >
            <Key size={12} />
            <span>一键跳转登录自愈 ➔</span>
          </button>
        </div>
      )}

      {/* 2. Sync platforms selective component */}
      <div className={`p-5 rounded-xl border space-y-4 text-xs ${
        isDarkMode ? 'bg-slate-900 border-slate-805' : 'bg-white border-slate-205 shadow-sm'
      }`}>
        
        <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b pb-2.5 border-dashed border-slate-200 dark:border-slate-850 gap-2">
          <div className="text-left">
            <h4 className="font-bold text-xs text-slate-800 dark:text-slate-101 flex items-center select-none">
              <ShieldCheck size={13} className="mr-1 text-emerald-500" />
              自媒体发布平台多选投流门禁 (Selective Distributions Gateway)
            </h4>
            <p className="text-[10px] text-gray-500 font-sans mt-0.5">只能勾选 Healthy 态平台。过期平台无法勾选，请点上方按钮跳转自愈。</p>
          </div>

          <button
            type="button"
            onClick={handleToggleSelectAllHealthy}
            disabled={healthyCredentials.length === 0}
            className={`px-3 py-1 rounded text-[10px] font-mono font-bold border flex items-center space-x-1 transition-colors ${
              isDarkMode ? 'border-slate-800 hover:bg-slate-800 text-slate-300' : 'border-slate-200 hover:bg-slate-50 text-slate-700 shadow-inner bg-slate-100'
            } disabled:opacity-40`}
          >
            <Check size={11} className="mr-0.5" />
            <span>{selectedPlatformIds.length === healthyCredentials.length && healthyCredentials.length > 0 ? '⛌ 取消全选' : '✓ 一键多选 Healthy 平台'}</span>
          </button>
        </div>

        {/* Horizontal checkbox matrix */}
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-left font-mono text-[10px]">
          {credentials.length === 0 ? (
            <div className="sm:col-span-4 text-center py-6 text-gray-500">
              数据载入中，未找到注册账号...
            </div>
          ) : (
            credentials.map((plat) => {
              const isHealthy = plat.status === 'Healthy';
              const isChecked = selectedPlatformIds.includes(plat.id);
              
              let cardBgBorderClass = '';
              if (!isHealthy) {
                cardBgBorderClass = isDarkMode 
                  ? 'bg-rose-950/10 border-rose-900/30 opacity-50 cursor-not-allowed' 
                  : 'bg-rose-50/40 border-rose-100 opacity-60 cursor-not-allowed';
              } else if (isChecked) {
                cardBgBorderClass = isDarkMode
                  ? 'bg-blue-950/20 border-blue-500 ring-2 ring-blue-500/10'
                  : 'bg-blue-50/25 border-blue-400 ring-2 ring-blue-400/10';
              } else {
                cardBgBorderClass = isDarkMode
                  ? 'bg-slate-950/60 border-slate-850 hover:border-slate-700'
                  : 'bg-slate-50 border-slate-200 hover:border-slate-350';
              }

              return (
                <div
                  key={plat.id}
                  onClick={() => handleTogglePlatform(plat.id, isHealthy)}
                  className={`p-3 rounded-xl border transition-all relative flex flex-col justify-between cursor-pointer ${cardBgBorderClass}`}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="font-bold text-[11px] leading-tight dark:text-white flex items-center">
                        <span className="mr-1.5">{plat.logo}</span>
                        <span>{plat.name}</span>
                      </p>
                      <p className="text-[9px] text-[#0077b6] dark:text-[#38bdf8] mt-1 shrink-0 truncate max-w-[130px]">
                        👤 {plat.username}
                      </p>
                    </div>

                    {/* Small Checkbox element */}
                    <div className="pt-0.5 select-none">
                      <input
                        type="checkbox"
                        checked={isChecked && isHealthy}
                        disabled={!isHealthy}
                        onChange={() => {}} // Controlled by outer div click helper gracefully
                        className="w-3.5 h-3.5 rounded text-blue-600 focus:ring-0 dark:bg-slate-900 dark:border-slate-800"
                      />
                    </div>
                  </div>

                  <div className="flex justify-between items-center mt-3 pt-2 border-t border-slate-100 dark:border-slate-850 select-none">
                    <span className={`text-[8px] font-mono uppercase font-bold shrink-0 ${
                      isHealthy ? 'text-emerald-500' : 'text-rose-500 animate-pulse'
                    }`}>
                      {isHealthy ? '● Healthy' : '🚨 EXPIRED'}
                    </span>
                    <span className="text-[7px] text-gray-500 max-w-[65px] truncate text-right">
                      {plat.type}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Real-time Publication Progress Panel (Visible during publishing or when complete) */}
        {(publishingState === 'running' || publishingState === 'done') && (
          <div className="p-4 rounded-xl border border-blue-200 bg-blue-50/20 dark:border-blue-900/40 dark:bg-slate-950 text-left space-y-3 animate-slideDown">
            <div className="flex items-center justify-between border-b pb-2 dark:border-slate-800">
              <span className="text-xs font-bold font-mono text-indigo-600 dark:text-sky-450 flex items-center">
                <span className="inline-block w-2 h-2 rounded-full bg-blue-500 animate-pulse mr-1.5" />
                📡 平台矩阵分发实时推流监控 (Matrix Sync Progress Telemetry)
              </span>
              <span className="text-[10px] font-mono text-gray-505">
                {publishingState === 'done' ? '✅ 分发任务全部同步成功' : '🔄 并发推送中...'}
              </span>
            </div>

            <div className="space-y-3">
              {selectedPlatformIds.map(id => {
                const plat = credentials.find(c => c.id === id);
                const progressVal = platformProgress[id] || { pct: 0, step: "排队中..." };
                return (
                  <div key={id} className="space-y-1 font-mono text-[10px]">
                    <div className="flex justify-between items-center bg-white/40 dark:bg-slate-900/50 p-2 rounded border dark:border-slate-850">
                      <span className="font-bold flex items-center">
                        <span className="mr-1.5">{plat?.logo}</span>
                        <span>{plat?.name}</span>
                        <span className="text-gray-400 text-[8.5px] font-normal ml-2">({plat?.username})</span>
                      </span>
                      <span className="font-bold text-blue-550 dark:text-sky-450">{progressVal.pct}%</span>
                    </div>
                    <div className="w-full bg-slate-200 dark:bg-slate-850 h-2 rounded overflow-hidden">
                      <div 
                        className={`bg-indigo-600 dark:bg-sky-400 h-full transition-all duration-300`} 
                        style={{ width: `${progressVal.pct}%` }} 
                      />
                    </div>
                    <div className="flex justify-between items-center text-[9px] text-gray-400">
                      <span>{progressVal.step}</span>
                      <span>{progressVal.pct === 100 ? 'SUCCESS' : `${progressVal.pct}%`}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Distribution Details settings */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 border-t pt-4 dark:border-slate-800">
          
          <div className="space-y-2 text-left col-span-1">
            <label className="text-[9px] text-gray-500 font-bold font-mono uppercase block">
              1. 国产平台独家声明文本 *
            </label>
            <input
              type="text"
              value={reprintProtection}
              onChange={(e) => setReprintProtection(e.target.value)}
              className={`w-full p-2 py-1.5 text-[10px] font-sans rounded border focus:outline-none ${
                isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200 text-slate-800'
              }`}
            />
          </div>

          <div className="space-y-2 text-left col-span-1">
            <label className="text-[9px] text-gray-500 font-bold font-mono uppercase block">
              2. 发布参数决策 (Target)
            </label>
            <div className={`p-2 py-1.5 rounded border font-mono text-[10px] text-slate-550 dark:bg-slate-950/40 dark:border-slate-850 bg-slate-50 flex items-center justify-between`}>
              <span>已选: <strong className="text-blue-500">{selectedPlatformIds.length}</strong> / {healthyCredentials.length}</span>
              <span>
                {selectedPlatformIds.length > 0 ? '✓ 就绪' : '✕ 自选'}
              </span>
            </div>
          </div>

          <div className="space-y-2 text-left col-span-1">
            <label className="text-[9px] text-gray-500 font-bold font-mono uppercase block">
              3. 重新发布策略 (Policy)
            </label>
            <button
              type="button"
              onClick={() => setForceRepublish(!forceRepublish)}
              className={`w-full p-2 py-1 flex items-center justify-between rounded border font-mono text-[10px] text-slate-550 transition-colors ${
                forceRepublish 
                  ? 'border-amber-500 bg-amber-500/10 text-amber-500 font-bold' 
                  : 'dark:bg-slate-950/40 dark:border-slate-850 bg-slate-50 hover:bg-slate-100 dark:hover:bg-slate-900'
              }`}
            >
              <span className="flex items-center space-x-1">
                <input
                  type="checkbox"
                  checked={forceRepublish}
                  onChange={() => {}} 
                  className="rounded text-amber-600 focus:ring-0 w-3 h-3"
                />
                <span className="ml-1">允许重发已发布平台</span>
              </span>
              <span>{forceRepublish ? '⚠️ 覆盖' : '🛡️ 跳过'}</span>
            </button>
          </div>

        </div>

        {/* Bottom Submission Action */}
        <div className="pt-4 border-t dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-0.5 text-left select-none">
            <span className="text-[9px] text-emerald-500 font-bold block flex items-center">
              <Shield size={10} className="mr-1" />
              防盗链防篡改防机翻三盾已经融合并注入排版引擎之中
            </span>
            <p className="text-[8px] opacity-60 font-sans">
              发布模式：勾选式多端直连。点击下方即可驱动 Agent 同步生成各平台排版适配，一枪秒出直接公开。
            </p>
          </div>

          <button
            type="button"
            onClick={handlePublishSelected}
            disabled={selectedPlatformIds.length === 0 || currentArticle.status === '待写作' || currentArticle.status === '正在生成' || publishingState === 'running'}
            className={`px-5 py-3 font-bold font-mono text-xs rounded-xl text-white bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-750 disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center space-x-1.5 shadow-md active:scale-95 transition-transform`}
          >
            {publishingState === 'running' ? (
              <>
                <RefreshCw size={11} className="mr-0.5 animate-spin" />
                <span>正在一键秒级推流发表中...</span>
              </>
            ) : publishingState === 'done' ? (
              <>
                <Check size={11} className="mr-0.5" />
                <span>发布成功！签署凭证已锁定</span>
              </>
            ) : (
              <>
                <Send size={11} className="mr-0.5 animate-bounce" />
                <span>➔ 签署发布凭据，一键秒级推流矩阵发表 (Matrix All-Channel Sync)</span>
              </>
            )}
          </button>
        </div>

      </div>

    </div>
  );
}
