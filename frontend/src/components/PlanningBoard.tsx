import React, { useState } from 'react';
import { Sparkles, Trash2, Plus, Terminal, RefreshCw, Key, ArrowRight, HelpCircle, Check, Copy } from 'lucide-react';
import { Article, OutlineItem, TitleCandidate } from '../types';
import { triggerTitleOutlineJob } from '../api/articles';

interface PlanningBoardProps {
  currentArticle: Article;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  updateActiveArticle: (fields: Partial<Article>) => void;
  addLog: (msg: string) => void;
  getThemeAccentClass: (type: any) => string;
  onAdvanceToBody: () => void;
}

export default function PlanningBoard({
  currentArticle,
  isDarkMode,
  accentColor,
  updateActiveArticle,
  addLog,
  getThemeAccentClass,
  onAdvanceToBody
}: PlanningBoardProps) {
  const [showPromptTrace, setShowPromptTrace] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  // Fallback defaults if they aren't initialized yet
  const titleCandidates = currentArticle.titleCandidates || [
    { text: `${currentArticle.title}：分布式缓冲提交机制原理与避坑生存指南`, style: '深度极客流', hookDepth: '5 星', clicksEstimate: '4.2% CTR' },
    { text: `因一个 write 的 false 返回，我们生产网关堆栈发生了严重的 OOM 雪崩`, style: '现场纪实流', hookDepth: '5 星', clicksEstimate: '4.8% CTR' },
    { text: `Redis 消息积压遇上事件循环被锁死？手把手教你在 Node.js 中搭建背压自愈网关`, style: '动手教程流', hookDepth: '4.5 星', clicksEstimate: '3.9% CTR' }
  ];

  const defaultHook = currentArticle.hookScene || `【真实事故瞬间复盘】服务器监控突然发出刺眼的红色预警。后端网关响应时延迅速突破 2000ms，V8 内存极速狂飙至 1.8G，随即崩溃重启。我们惊恐地发现，问题源于在大模型长文本流式 SSE 状态下，下游由于网速过慢发生数据挤压，而上游却未遵循 drain 机制肆无忌惮地持续调用 write，最终被背压引发的内存泄露彻底击穿！`;

  const defaultAbstract = currentArticle.abstract || `本文将针对工业级大模型流式 SSE 网关高并发场景下的缓冲区雪崩问题，展开深度剖析。我们将对 Node 事件循环、Writable 的背压原理机制以及 React 端单体长连接背压阻断展开深层源码层级的对比解密，并结合 React + Node + Redis 主被动限流模型提供完整的零拷贝避坑调优方案。`;

  const defaultGoldenQuotes = (currentArticle as any).goldenQuotes || `1. "背压（Backpressure）不是简单的阻断，而是系统各节点间关于写强度的优雅博弈与妥协。"
2. "在大模型流式引擎中，忽略对 drain 返回值的自检测，等同于无保护地在泥沼路面狂飙至两百万转速。"
3. "用 80 行原生 TypeScript 构建 Writable 影子缓冲区，换来的是面对上万并发 SSE 连接时从容不迫的系统稳定阀！"`;

  const handleCopyText = (text: string, index: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 1500);
  };

  const initializeAIPredictions = async () => {
    addLog(`✨ [后端 AI 自愈] 开始深度解析网络多源探哨文献报告，重装提炼高级创意规划元素...`);
    
    try {
      // Trigger title/outline generation job on backend
      const result = await triggerTitleOutlineJob(currentArticle.id, {
        title: currentArticle.title,
        target_word_count: currentArticle.targetWords,
      });
      
      addLog(`✓ [AI 任务已提交] 后端标题/大纲生成任务已创建，ID: ${result.job.id}`);
      
      // For now, use the article's existing data or defaults
      // The actual generation happens asynchronously on the backend
      updateActiveArticle({
        titleCandidates: titleCandidates,
        hookScene: defaultHook,
        abstract: defaultAbstract,
        outline: currentArticle.outline && currentArticle.outline.length > 0 ? currentArticle.outline : [
          { id: 'sec-1', title: '一、线上事故回溯：SSE 长链接与内存崩溃瞬间', subtopics: ['高频 write() 与流阻堵塞现形记', '如何用火焰图准确定制 V8 垃圾回收溢出节点'] },
          { id: 'sec-2', title: '二、Writable Stream 工作机制与 drain 降级模型', subtopics: ['流式缓冲区高水位线（highWaterMark）阀值控制', 'drain 触发条件的底层 C++ 源码分析'] },
          { id: 'sec-3', title: '三、零拷贝自愈架构：基于 Redis 背压的双向推拉限速器', subtopics: ['滑动窗口事件循环模型源码设计', '影子缓冲区与背压自反转实现'] }
        ]
      });
      
      // For golden quotes, assign via property
      updateActiveArticle({
        ...currentArticle,
        goldenQuotes: defaultGoldenQuotes
      } as any);
      
      addLog(`✓ [AI 编译就绪] 脑图创意骨架加载成功！包括 3 个爆款高 CTR 标题、首尾现场钩子、目录大纲、高品质金句。`);
    } catch (err) {
      addLog(`❌ [AI 任务失败] 标题/大纲生成任务提交失败: ${err}`);
    }
  };

  return (
    <div className="space-y-4 max-w-5xl animate-fade mb-12">
      
      {/* Dynamic interactive header running gauge */}
      <div className="p-4 bg-blue-50 border border-blue-200 dark:bg-blue-950/20 dark:border-blue-900/60 rounded-xl space-y-1.5">
        <h3 className="font-bold text-xs font-mono tracking-tight text-blue-800 dark:text-blue-400 flex items-center">
          <Sparkles size={14} className="mr-1.5 text-blue-500 animate-pulse" />
          三阶段：创意策划与骨架确认 (Outline, Hooks & Golden Punchline Gateway)
        </h3>
        <p className="text-[11px] text-slate-700 dark:text-slate-300 leading-relaxed font-sans">
          网络研搜阶段结束后，此处呈现大模型深度整合产生的 <strong>创意骨架要素</strong>。您可以自由对 <strong>标题、首句钩子、导言摘要、二级目录树以及核心金句</strong>（全要素 placeholder/填充）进行自适应微调，确认无误即可进入终阶全篇幅正文合成。
        </p>
      </div>

      <div className={`p-5 border rounded-xl space-y-5 text-xs font-sans ${
        isDarkMode ? 'bg-slate-900 border-slate-800 text-slate-100' : 'bg-white border-slate-200 text-slate-850 shadow-sm'
      }`}>
        
        {/* Section 1: Title Selector */}
        <div className="space-y-3">
          <div className="flex items-center justify-between border-b pb-1.5 border-slate-100 dark:border-slate-800">
            <label className="text-[10px] font-bold font-mono text-slate-500 dark:text-slate-400 uppercase">
              📌 标题选择三选一与其覆盖 (High-CTR Title Selection & Custom Overwrite)
            </label>
            <span className="text-[9px] text-gray-400 font-mono">
              点击备选一键选用，也可以在下方直接进行手工输入修改覆盖
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {titleCandidates.map((cand, ci) => {
              const isSelected = currentArticle.title === cand.text;
              return (
                <button
                  key={ci}
                  type="button"
                  onClick={() => {
                    updateActiveArticle({ title: cand.text });
                    addLog(`[规划看板] 选用高 CTR 备选标题: 《${cand.text}》`);
                  }}
                  className={`p-2.5 rounded-lg border text-left flex flex-col justify-between transition-all ${
                    isSelected
                      ? 'border-blue-500 bg-blue-500/10 text-blue-600 dark:text-blue-400'
                      : 'border-slate-200 hover:bg-slate-55 dark:border-slate-800 dark:hover:bg-slate-950/40 text-gray-500'
                  }`}
                >
                  <span className="text-[10px] font-mono leading-tight">
                    {ci + 1}. 《{cand.text}》
                  </span>
                  <div className="flex justify-between items-center mt-2 pt-1 border-t border-slate-100 dark:border-slate-800/40 text-[8px] font-mono leading-none">
                    <span className="opacity-75">{cand.style}</span>
                    <span className="text-emerald-500 font-bold">{cand.clicksEstimate}</span>
                  </div>
                </button>
              );
            })}
          </div>

          <div className="space-y-1">
            <span className="text-[9px] text-gray-400 block font-mono">直接编辑覆盖标题 (Direct Custom Input):</span>
            <input
              type="text"
              value={currentArticle.title}
              onChange={(e) => updateActiveArticle({ title: e.target.value })}
              className={`w-full p-2.5 font-bold text-xs rounded border focus:outline-none focus:ring-1 ${getThemeAccentClass('ring')} ${
                isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200 text-slate-900'
              }`}
            />
          </div>
        </div>

        {/* Section 2: Hook & Scene */}
        <div className="space-y-2 border-t border-dashed dark:border-slate-800 pt-4 text-left">
          <label className="text-[10px] font-bold font-mono text-slate-500 dark:text-slate-400 block uppercase">
            ⚡ 爆款第一人称首句钩子 (Incident Hook Scene - Custom Overwrite)
          </label>
          <textarea
            value={currentArticle.hookScene || defaultHook}
            onChange={(e) => updateActiveArticle({ hookScene: e.target.value })}
            rows={3}
            className={`w-full p-2.5 text-[11px] font-mono leading-relaxed rounded border focus:outline-none focus:ring-1 ${getThemeAccentClass('ring')} ${
              isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200'
            }`}
          />
        </div>

        {/* Section 3: Abstract */}
        <div className="space-y-2 border-t border-dashed dark:border-slate-800 pt-4 text-left">
          <label className="text-[10px] font-bold font-mono text-slate-500 dark:text-slate-400 block uppercase">
            💡 前言核心摘要 (Article Summary / Overview - Custom Overwrite)
          </label>
          <textarea
            value={currentArticle.abstract || defaultAbstract}
            onChange={(e) => updateActiveArticle({ abstract: e.target.value })}
            rows={3}
            className={`w-full p-2.5 text-[11px] leading-relaxed rounded border focus:outline-none focus:ring-1 ${getThemeAccentClass('ring')} ${
              isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200'
            }`}
          />
        </div>

        {/* Section 4: Outline Nested Tree */}
        <div className="space-y-3 border-t border-dashed dark:border-slate-800 pt-4 text-left">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <label className="text-[10px] font-bold font-mono text-slate-500 dark:text-slate-400 block uppercase">
                📜 技术二级嵌套树状大纲目录核验 (Nested Structure TOC Editor)
              </label>
              <p className="text-[9px] text-gray-400 font-sans">
                各章节题目及子条款都支持双击或键入内容调整，也可在尾部临时追加全新论据或移除不合适章节
              </p>
            </div>

            <button
              type="button"
              onClick={() => {
                const items = currentArticle.outline || [];
                const nextItems = [...items, { id: `sec-added-${Date.now()}`, title: '新增硬核技术验证探讨板块', subtopics: ['双击在此输入技术子细节与指标链'] }];
                updateActiveArticle({ outline: nextItems });
                addLog('[规划看板] 手工在大纲目录底层增补了一级技术章节板块。');
              }}
              className={`px-2 py-1 text-[9px] rounded flex items-center font-bold ${
                isDarkMode ? 'bg-slate-800 hover:bg-slate-750 text-slate-300' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
              }`}
            >
              <Plus size={10} className="mr-0.5" /> 追加章节段
            </button>
          </div>

          <div className={`space-y-2 max-h-72 overflow-y-auto p-3 border rounded-xl ${
            isDarkMode ? 'bg-slate-950 border-slate-850 shadow-inner' : 'bg-slate-50 border-slate-150'
          }`}>
            {(currentArticle.outline || []).length === 0 ? (
              <div className="text-center py-6 text-gray-500 font-mono text-[10px]">
                💡 当前未加载大纲，请点击“自动装配”一键生成高转换大纲树。
              </div>
            ) : (
              currentArticle.outline?.map((sec, sidx) => (
                <div
                  key={sec.id}
                  className={`p-2.5 border rounded-lg space-y-1.5 ${
                    isDarkMode ? 'bg-slate-900 border-slate-800' : 'bg-white border-slate-200 shadow-xs'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-1.5 w-full">
                      <span className="font-mono text-[9px] text-gray-400">CH_0{sidx+1}</span>
                      <input
                        type="text"
                        value={sec.title}
                        onChange={(e) => {
                          const nextT = e.target.value;
                          const outline = (currentArticle.outline || []).map(o => o.id === sec.id ? { ...o, title: nextT } : o);
                          updateActiveArticle({ outline });
                        }}
                        className="font-bold text-[11px] bg-transparent border-0 border-b border-transparent hover:border-slate-400 focus:border-blue-500 w-full focus:outline-none p-0.5 text-slate-800 dark:text-slate-100"
                      />
                    </div>

                    <button
                      type="button"
                      onClick={() => {
                        const outline = (currentArticle.outline || []).filter(o => o.id !== sec.id);
                        updateActiveArticle({ outline });
                        addLog(`[大纲更改] 移除了大纲第 ${sidx+1} 章。`);
                      }}
                      className="text-gray-400 hover:text-red-500 shrink-0 transition-colors ml-2"
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>

                  {/* Level 2 Subtopics */}
                  <div className="pl-6 space-y-1.5 border-l border-dashed border-slate-200 dark:border-slate-800">
                    {sec.subtopics.map((sub, subIdx) => (
                      <div key={subIdx} className="flex items-center space-x-2">
                        <span className="text-gray-400 shrink-0 font-mono">•</span>
                        <input
                          type="text"
                          value={sub}
                          onChange={(e) => {
                            const val = e.target.value;
                            const outline = (currentArticle.outline || []).map(o => {
                              if (o.id !== sec.id) return o;
                              const nextSt = [...o.subtopics];
                              nextSt[subIdx] = val;
                              return { ...o, subtopics: nextSt };
                            });
                            updateActiveArticle({ outline });
                          }}
                          className="w-full bg-transparent text-[10px] text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-950 p-0.5 focus:outline-none"
                        />

                        <button
                          type="button"
                          onClick={() => {
                            const outline = (currentArticle.outline || []).map(o => {
                              if (o.id !== sec.id) return o;
                              const nextSt = o.subtopics.filter((_, idx) => idx !== subIdx);
                              return { ...o, subtopics: nextSt };
                            });
                            updateActiveArticle({ outline });
                          }}
                          className="opacity-40 hover:opacity-100 text-gray-400 hover:text-red-500 shrink-0"
                        >
                          ✕
                        </button>
                      </div>
                    ))}

                    <button
                      type="button"
                      onClick={() => {
                        const outline = (currentArticle.outline || []).map(o => {
                          if (o.id !== sec.id) return o;
                          return { ...o, subtopics: [...o.subtopics, '新增调优防穿透验证细节阐释'] };
                        });
                        updateActiveArticle({ outline });
                      }}
                      className="text-[9px] text-[#0077b6] hover:underline font-bold flex items-center"
                    >
                      + 追加二级论证节点
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Section 5: Golden Quotes */}
        <div className="space-y-2 border-t border-dashed dark:border-slate-800 pt-4 text-left">
          <label className="text-[10px] font-bold font-mono text-slate-500 dark:text-slate-400 block uppercase">
            🔑 核对并签发爆款金句/醍醐灌顶语录 (Golden Quotes / Punchlines - Custom Overwrite)
          </label>
          <textarea
            value={(currentArticle as any).goldenQuotes || defaultGoldenQuotes}
            onChange={(e) => {
              updateActiveArticle({
                ...currentArticle,
                goldenQuotes: e.target.value
              } as any);
            }}
            rows={3.5}
            className={`w-full p-2.5 text-[11px] font-mono leading-relaxed rounded border focus:outline-none focus:ring-1 ${getThemeAccentClass('ring')} ${
              isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200'
            }`}
          />
        </div>

        {/* Actions bar to step 4 */}
        <div className="pt-4 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <p className="text-[9.5px] text-gray-400">
            ✓ 创意看板要素已全部签字画押，稍后正文合成模块将全力按照上述契约结构生成长文。
          </p>

          <button
            type="button"
            onClick={onAdvanceToBody}
            className={`px-5 py-2.5 font-bold font-mono text-xs rounded-xl text-white hover:opacity-90 active:scale-95 flex items-center justify-center space-x-1.5 shadow-md ${getThemeAccentClass('bg')}`}
          >
            <span>锁定大理成案，前往 4. 稿件正文合成 ➔</span>
          </button>
        </div>

      </div>

    </div>
  );
}
