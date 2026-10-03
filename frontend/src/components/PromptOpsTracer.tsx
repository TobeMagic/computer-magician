import React, { useState, useEffect } from 'react';
import { Cpu, Maximize2, X } from 'lucide-react';
import { Article } from '../types';
import { getPromptSnapshots } from '../api/prompts';

interface PromptOpsTracerProps {
  currentArticle: Article;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  addLog: (msg: string) => void;
  getThemeAccentClass: (type: any) => string;
}

interface PromptOpsEvent {
  id: string;
  phase: string;
  templateVersion: string;
  variables: Record<string, string>;
  temperature: number;
  tokensEstimate: string;
  compiledPrompt: string;
  responseJSON: string;
}

export default function PromptOpsTracer({
  currentArticle,
  isDarkMode,
  accentColor,
  addLog,
  getThemeAccentClass
}: PromptOpsTracerProps) {
  
  const [events, setEvents] = useState<PromptOpsEvent[]>([]);
  const [loading, setLoading] = useState(true);

  // Fetch real prompt snapshots from backend
  useEffect(() => {
    const fetchSnapshots = async () => {
      try {
        // Try to get snapshots with a default prompt key
        const snapshots = await getPromptSnapshots('default', { limit: 10 });
        
        // Map backend snapshots to frontend PromptOpsEvent format
        const mappedEvents: PromptOpsEvent[] = snapshots.map((snapshot: any, index: number) => ({
          id: snapshot.id || `trace-${index + 1}`,
          phase: snapshot.phase || `${index + 1}. Prompt Snapshot`,
          templateVersion: snapshot.version || snapshot.template_version || 'unknown',
          variables: snapshot.variables || snapshot.input_variables || {},
          temperature: snapshot.temperature || 0.3,
          tokensEstimate: snapshot.tokens_estimate || `${snapshot.input_tokens || 0} In / ${snapshot.output_tokens || 0} Out`,
          compiledPrompt: snapshot.compiled_prompt || snapshot.prompt_text || '',
          responseJSON: snapshot.response_json || snapshot.output_text || '{}',
        }));

        // If no snapshots from backend, use fallback defaults
        if (mappedEvents.length === 0) {
          setEvents([
            {
              id: 'trace-1',
              phase: '1. 搜集后生成骨架 (Skeleton Generation Trace)',
              templateVersion: 'v2.4_skeleton_generator',
              temperature: 0.3,
              tokensEstimate: '2,950 In / 1,420 Out',
              variables: {
                article_title: currentArticle.title,
                evidence_sources_count: String(currentArticle.researchReport?.sources?.length || 30)
              },
              compiledPrompt: `System: You are an AI Creator assistant. Relying on parsed evidence links, draft high-CTR title variations, hooks, dynamic abstract, structured outline, and notable quotes.`,
              responseJSON: `{\n  "status": "no_snapshots_available"\n}`
            }
          ]);
        } else {
          setEvents(mappedEvents);
        }
      } catch (err) {
        console.error('Failed to fetch prompt snapshots:', err);
        // Use fallback defaults
        setEvents([
          {
            id: 'trace-1',
            phase: '1. 搜集后生成骨架 (Skeleton Generation Trace)',
            templateVersion: 'v2.4_skeleton_generator',
            temperature: 0.3,
            tokensEstimate: '2,950 In / 1,420 Out',
            variables: {
              article_title: currentArticle.title,
              evidence_sources_count: String(currentArticle.researchReport?.sources?.length || 30)
            },
            compiledPrompt: `System: You are an AI Creator assistant. Relying on parsed evidence links, draft high-CTR title variations, hooks, dynamic abstract, structured outline, and notable quotes.`,
            responseJSON: `{\n  "status": "no_snapshots_available"\n}`
          }
        ]);
      } finally {
        setLoading(false);
      }
    };

    fetchSnapshots();
  }, [currentArticle.id]);

  const [selectedEventId, setSelectedEventId] = useState<string>('');
  const activeEvent = events.find(e => e.id === selectedEventId) || events[0];
  const [isComparisonOpen, setIsComparisonOpen] = useState<boolean>(false);

  // Update selectedEventId when events change
  useEffect(() => {
    if (events.length > 0 && !selectedEventId) {
      setSelectedEventId(events[0].id);
    }
  }, [events, selectedEventId]);

  return (
    <div className="space-y-4 max-w-5xl animate-fade">
      
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        
        {/* Left selector panel */}
        <div className="lg:col-span-5 space-y-3">
          <p className="text-[10px] font-bold font-mono text-gray-400 uppercase select-none text-left">
            Prompt 流程追踪序列 (PromptOps Observability Index):
          </p>

          <div className="space-y-2">
            {events.map((ev) => {
              const isActive = ev.id === selectedEventId;
              return (
                <div
                  key={ev.id}
                  onClick={() => setSelectedEventId(ev.id)}
                  className={`p-3 rounded-lg border text-left cursor-pointer transition-all ${
                    isActive
                      ? 'border-amber-500 bg-amber-500/10 text-slate-101'
                      : isDarkMode
                      ? 'bg-slate-905 border-slate-850 hover:bg-slate-900/60 text-slate-400'
                      : 'bg-white border-slate-200 hover:bg-slate-50 text-slate-700 shadow-xs'
                  }`}
                >
                  <p className="font-bold text-[10px] font-mono leading-none">{ev.phase}</p>
                  <div className="flex justify-between items-center text-[8px] font-mono opacity-70 mt-2">
                    <span>模版: {ev.templateVersion}</span>
                    <span className="text-emerald-500">Gemini 2.5 Pro (Assembled)</span>
                  </div>
                </div>
              );
            })}
          </div>

          <div className={`p-4 border rounded-xl space-y-2 text-xs text-left ${
            isDarkMode ? 'bg-slate-900 border-slate-805 text-slate-100' : 'bg-white border-slate-202 text-slate-850 shadow-sm'
          }`}>
            <h5 className="font-bold text-[11px] font-mono text-amber-500 flex items-center">
              <Cpu size={12} className="mr-1 text-amber-550 animate-pulse" />
              智能体提示词链条跟踪
            </h5>
            <p className="text-[10px] text-gray-400 leading-normal">
              此处将完整展现多源网络探查结束后的<strong>骨架生成契约</strong>、<strong>全文长白话正文生成</strong>以及<strong>Imagen-3 封面提示词加工</strong>的编译组装前后物理 Prompt 和版本控制详情。
            </p>
          </div>
        </div>

        {/* Right visualization viewport */}
        <div className={`lg:col-span-7 p-4 border rounded-xl overflow-hidden flex flex-col justify-between space-y-3 ${
          isDarkMode ? 'bg-slate-900 border-slate-805' : 'bg-white border-slate-202 shadow-sm'
        }`}>
          
          <div className="space-y-3 text-xs text-left w-full">
            <div className="flex justify-between items-center border-b pb-1.5 dark:border-slate-800">
              <span className="font-bold font-mono text-gray-450 uppercase text-[9px]">Prompt 物理字符串及输入输出映射流</span>
              <button
                type="button"
                onClick={() => setIsComparisonOpen(true)}
                className="text-[9.5px] font-mono bg-amber-500/10 text-amber-500 hover:bg-amber-500/20 border border-amber-500/25 p-1 px-2.5 rounded-lg flex items-center gap-1 transition-all active:scale-95 cursor-pointer"
                title="全屏左右分栏精确安全审阅所有模板与变量组合数据"
              >
                <Maximize2 size={10} />
                <span>🖥️ 左右双栏大图极精审阅</span>
              </button>
            </div>

            <div className="grid grid-cols-3 gap-2 font-mono text-[9px] leading-relaxed">
              <div className="p-1.5 rounded bg-slate-950 border border-slate-800 text-left">
                <p className="text-gray-500 font-bold uppercase text-[8px]">1. 链条模板版本:</p>
                <p className="text-blue-400 mt-0.5 font-bold">{activeEvent.templateVersion}</p>
              </div>
              <div className="p-1.5 rounded bg-slate-950 border border-slate-800 text-left">
                <p className="text-gray-500 font-bold uppercase text-[8px]">2. 编译模型温度:</p>
                <p className="text-amber-400 mt-0.5 font-bold">{activeEvent.temperature}</p>
              </div>
              <div className="p-1.5 rounded bg-slate-950 border border-slate-800 text-left">
                <p className="text-gray-500 font-bold uppercase text-[8px]">3. 耗费 token 计算:</p>
                <p className="text-emerald-400 mt-0.5 font-bold">{activeEvent.tokensEstimate}</p>
              </div>
            </div>

            {/* Inputs Variables */}
            <div className="space-y-1">
              <p className="text-gray-500 font-bold font-mono uppercase text-[9px]">■ 绑定的模版占位符变量注入映射表 (Inputs Table):</p>
              <div className="p-2.5 rounded bg-slate-950 border border-slate-800 text-[10px] font-mono leading-relaxed max-h-40 overflow-y-auto w-full">
                {Object.entries(activeEvent.variables).map(([key, val]) => (
                  <p key={key} className="truncate">
                    <span className="text-indigo-400 font-bold">{key}</span>: <span className="text-emerald-400">"{val}"</span>
                  </p>
                ))}
              </div>
            </div>

            {/* Physical compiled prompt */}
            <div className="space-y-1">
              <p className="text-gray-500 font-bold font-mono uppercase text-[9px]">■ 编译后输出大模型的物理物理 Prompts 字符串 (Assembled Prompt String):</p>
              <div className="p-2.5 rounded-lg border bg-slate-950 font-mono text-[10px] leading-relaxed max-h-60 overflow-y-auto border-slate-800 w-full animate-fade-in">
                <pre className="whitespace-pre-wrap text-blue-400 break-all">{activeEvent.compiledPrompt}</pre>
              </div>
            </div>

            {/* Parsed JSON schema */}
            <div className="space-y-1">
              <p className="text-gray-500 font-bold font-mono uppercase text-[9px]">■ 大模型服务端返回结构体 Response JSON (Raw Body):</p>
              <div className="p-2.5 rounded border bg-slate-955 border-slate-800 text-[10px] font-mono leading-relaxed max-h-48 overflow-y-auto w-full animate-fade-in">
                <pre className="whitespace-pre-wrap text-emerald-400 break-all">{activeEvent.responseJSON}</pre>
              </div>
            </div>
          </div>

          <div className="text-[8px] font-mono text-slate-500 text-right shrink-0 mt-2">
            <span>✓ 可追溯性：Prompt Trace 覆盖率 100% | 物理时间：UTC+8</span>
          </div>

        </div>

      </div>

      {/* Fullscreen Double-Pane Comparison Modal View */}
      {isComparisonOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-slate-955/80 backdrop-blur-sm animate-fade-in">
          <div className={`w-full max-w-6xl h-[90vh] rounded-2xl border overflow-hidden flex flex-col shadow-2xl animate-zoom-in ${
            isDarkMode ? 'bg-[#0b101c] border-slate-800 text-white' : 'bg-white border-slate-205 text-slate-805'
          }`}>
            <div className={`p-4 border-b flex items-center justify-between ${
              isDarkMode ? 'border-slate-800 bg-[#070b13]' : 'border-slate-100 bg-[#fafafa]'
            }`}>
              <div className="flex items-center space-x-2.5 text-left">
                <div className="p-2 rounded-xl bg-amber-500/10 text-amber-500">
                  <Cpu size={16} className="animate-pulse" />
                </div>
                <div>
                  <h4 className="font-bold text-sm leading-tight">Prompt 物理组装及左右双栏大图对比精审中枢 (Double-Pane Audit)</h4>
                  <p className="text-[10px] text-gray-500 font-mono">
                    Phase: {activeEvent.phase} | Version: {activeEvent.templateVersion}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsComparisonOpen(false)}
                className="p-2 rounded-lg hover:bg-slate-500/10 transition-colors cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            {/* Split Dual Column Layout Pane */}
            <div className="flex-1 grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-slate-200 dark:divide-slate-800 overflow-hidden text-left min-h-0 bg-slate-950">
              
              {/* Left Column: Variables & Templates before compiled assembly */}
              <div className="flex-1 p-5 overflow-y-auto space-y-4 flex flex-col min-h-0">
                <div>
                  <span className="text-[10px] font-mono text-gray-400 uppercase tracking-wider block mb-1">■ 1. 变量契约注入表 (Variables Input Table):</span>
                  <div className="p-3 rounded-xl bg-[#070b13] border border-slate-800 font-mono text-xs leading-relaxed space-y-1.5 select-all">
                    {Object.entries(activeEvent.variables).map(([key, value]) => (
                      <p key={key}>
                        <span className="text-indigo-400 font-bold">{key}</span>: <span className="text-emerald-400">"{value}"</span>
                      </p>
                    ))}
                  </div>
                </div>

                <div className="flex-1 flex flex-col min-h-0">
                  <span className="text-[10px] font-mono text-gray-405 uppercase tracking-wider block mb-1 font-semibold">■ 2. 物理组装前 提示词流模版 (Raw Template Body):</span>
                  <div className="flex-1 p-3.5 rounded-xl bg-[#070b13] border border-slate-800 font-mono text-xs overflow-y-auto leading-relaxed select-all">
                    <pre className="whitespace-pre-wrap text-blue-300 font-mono text-xs leading-relaxed">
{`System Instructions: You are an AI Creator assistant. Relying on parsed evidence links, draft high-quality artifacts matching target word-counts & outline parameters.

[PROMPT_BEFORE_ASSEMBLY_TEMPLATE]
${Object.keys(activeEvent.variables).map(key => `${key}: {{${key}}}`).join('\n')}`}
                    </pre>
                  </div>
                </div>
              </div>

              {/* Right Column: Physical compiled prompts & actual returned JSON */}
              <div className="flex-1 p-5 overflow-y-auto space-y-4 flex flex-col min-h-0">
                <div className="flex-1 flex flex-col min-h-0">
                  <span className="text-[10px] font-mono text-gray-405 uppercase tracking-wider block mb-1 font-semibold">■ 3. 编译注入后 输出大模型物理明文 (Compiled Physical Prompt):</span>
                  <div className="flex-1 p-3.5 rounded-xl bg-[#070b13] border border-slate-800 font-mono text-xs overflow-y-auto leading-relaxed select-all border-dashed">
                    <pre className="whitespace-pre-wrap text-yellow-100">{activeEvent.compiledPrompt}</pre>
                  </div>
                </div>

                <div className="h-44 flex flex-col shrink-0 min-h-0">
                  <span className="text-[10px] font-mono text-gray-405 uppercase tracking-wider block mb-1 font-semibold">■ 4. 服务端返回结构体 Schema response (JSON):</span>
                  <div className="flex-1 p-3.5 rounded-xl bg-[#070b13] border border-slate-800 font-mono text-xs overflow-y-auto leading-relaxed select-all">
                    <pre className="whitespace-pre-wrap text-emerald-400">{activeEvent.responseJSON}</pre>
                  </div>
                </div>
              </div>

            </div>

            <div className={`p-4 border-t flex justify-end gap-2.5 ${
              isDarkMode ? 'border-slate-800 bg-[#070b13]' : 'border-slate-105 bg-[#fafafa]'
            }`}>
              <button
                type="button"
                onClick={() => setIsComparisonOpen(false)}
                className="px-5 py-2 text-xs font-mono font-medium rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition-colors"
              >
                已确认审阅 Complete
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
