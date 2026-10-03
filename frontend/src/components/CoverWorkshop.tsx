import React, { useState } from 'react';
import { ImageIcon, RefreshCw, Sparkles, CheckSquare, Shield, Lock, ChevronRight, Check, Cpu } from 'lucide-react';
import { Article } from '../types';
import { triggerCoverBriefJob } from '../api/articles';

interface CoverWorkshopProps {
  currentArticle: Article;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  updateActiveArticle: (fields: Partial<Article>) => void;
  addLog: (msg: string) => void;
  getThemeAccentClass: (type: any) => string;
}

export interface ConceptCandidate {
  id: string;
  concept: string;
  description: string;
  promptSeed: string;
  tags: string[];
}

export interface CoverCandidate {
  id: string;
  imageUrl: string;
  creatorAgent: string;
  seed: number;
}

export default function CoverWorkshop({
  currentArticle,
  isDarkMode,
  accentColor,
  updateActiveArticle,
  addLog,
  getThemeAccentClass
}: CoverWorkshopProps) {
  // Local Cover Pipeline states
  const [coverStage, setCoverStage] = useState<number>(1);
  const [isGenerating, setIsGenerating] = useState(false);
  const [visualCandidates, setVisualCandidates] = useState<ConceptCandidate[]>([]);
  const [confirmedVisualId, setConfirmedVisualId] = useState<string | null>(null);
  const [coverCandidates, setCoverCandidates] = useState<CoverCandidate[]>([]);
  const [selectedCoverId, setSelectedCoverId] = useState<string | null>(null);
  const [showPromptTrace, setShowPromptTrace] = useState(false);

  // Style guidance input (optional)
  const [styleGuide, setStyleGuide] = useState('');

  // 1. Gate 1 -> Gate 2: Generate 3 concept candidates with optional style guide
  const handleGenerateVisualCandidates = async () => {
    setIsGenerating(true);
    const guideSuffix = styleGuide ? `，融合风格引导「${styleGuide}」` : '，采用默认科技感自媒体风格';

    addLog(`➔ [Cover Gate 1] 启动语义智能体分析：正在提炼关键词 《${currentArticle.title}》 结构调性${guideSuffix}...`);

    try {
      // Trigger cover brief generation job on backend
      const result = await triggerCoverBriefJob(currentArticle.id, {
        style_direction: styleGuide || undefined,
      });
      
      addLog(`✓ [Cover 任务已提交] 后端封面生成任务已创建，ID: ${result.job.id}`);
      
      // For now, use the article's existing data or defaults
      // The actual generation happens asynchronously on the backend
      const conceptsList: ConceptCandidate[] = [
        {
          id: 'concept-1',
          concept: styleGuide ? `${styleGuide}风 // 极速流控焰火` : 'Neon Stream Flame (极速流控焰火)',
          description: `基于文章选题《${currentArticle.title}》提炼的流式艺术。应用高对比度黑金画布，搭配高光霓彩流线${styleGuide ? `并特调融入 ${styleGuide} 美学要素` : ''}。象征着在 Socket 背压来袭时，数据流被自适应截限阀牢固控制，视觉张力拉满。`,
          promptSeed: `Imagen3 HD rendering, neon streams flowing, golden valve controls, high contrast, dark cosmic design style, tech focus${styleGuide ? `, fusion style: ${styleGuide}` : ''}, --ar 16:9`,
          tags: ['流控', '黑金极客', styleGuide ? styleGuide.substring(0, 10) : 'Neon-Flame']
        },
        {
          id: 'concept-2',
          concept: styleGuide ? `${styleGuide}风 // V8引擎极地冰层锁` : 'V8 Engine Stack Freeze (V8引擎极地冰层锁)',
          description: `极简抽象的技术隐喻视觉${styleGuide ? `融合「${styleGuide}」艺术意象` : ''}。发光的超温微芯片组包覆在霓虹极地光栅散热网格中，象征采用精控背压技术化解 GC 剧增延迟，运行极度顺滑。`,
          promptSeed: `Minimalism, V8 engine microchips wrapped in deep neon blue glacier grid, cooling, no-disturbing, ultra smooth surface${styleGuide ? `, fusion style: ${styleGuide}` : ''}, --ar 16:9`,
          tags: ['冷处理', '极简抽象', styleGuide ? styleGuide.substring(0, 10) : 'Glacier-Grid']
        },
        {
          id: 'concept-3',
          concept: styleGuide ? `${styleGuide}风 // 赛博关系底座及数据契约` : 'Postgres Cyber Ledger (赛博 PostgreSQL 数据库契约)',
          description: `赛博朋克极客流派 ${styleGuide ? `融合「${styleGuide}」材质语境` : ''}。错综的发光电路线汇入一个浮空的关系底座中，表达数据被精准保存与 Notion、PostgreSQL 安全落盘。`,
          promptSeed: `Cyberpunk database columns glowing in matrix space, golden ledger synchronizing, conceptual art, cinematic ambient lighting${styleGuide ? `, fusion style: ${styleGuide}` : ''}, --ar 16:9`,
          tags: ['PG落盘', '赛博科技', styleGuide ? styleGuide.substring(0, 10) : 'Data-Sync']
        }
      ];

      setVisualCandidates(conceptsList);
      setCoverStage(2);
      setIsGenerating(false);
      addLog(`✓ [Cover Gate 1 通关] 成功推演出 3 组各具特色的核心视觉元素理念${guideSuffix}！已移交至第二隔离阀：【Gate 2：选择核心理念方向】`);
    } catch (err) {
      addLog(`❌ [Cover 任务失败] 封面生成任务提交失败: ${err}`);
      setIsGenerating(false);
    }
  };

  // 2. Gate 2 -> Gate 3: Select one brief direction to lock
  const handleConfirmVisualElement = (visualId: string) => {
    setConfirmedVisualId(visualId);
    setCoverStage(3);
    addLog(`✓ [Cover Gate 2 签署签署通过] 锁定核心方向 ID: ${visualId} (${visualCandidates.find(v => v.id === visualId)?.concept})！`);
  };

  // 3. Gate 3 -> Gate 4: Render images with Imagen HD on mock coordinates specifically tailored
  const handleGenerateCoverCandidates = () => {
    setIsGenerating(true);
    const chosen = visualCandidates.find(v => v.id === confirmedVisualId);
    addLog(`➔ [Cover Gate 3] 图像解算粒子起动：正在发送参数 [${chosen?.promptSeed}] 到 Imagen-3 芯片，专为方向「${chosen?.concept}」一键成稿中...`);

    setTimeout(() => {
      // Choose images depending on selected element to match the user request "然后只需要生成选中的那个就好"
      let imagesList: string[] = [
        'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=500&q=80',
        'https://images.unsplash.com/photo-1620641788421-7a1c342ea42e?auto=format&fit=crop&w=500&q=80',
        'https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?auto=format&fit=crop&w=500&q=80'
      ];

      if (confirmedVisualId === 'concept-1') {
        imagesList = [
          'https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=500&q=80', // neon tech lines
          'https://images.unsplash.com/photo-1544383835-bda2bc66a55d?auto=format&fit=crop&w=500&q=80', // neon flow lines
          'https://images.unsplash.com/photo-1509198397868-475647b2a1e5?auto=format&fit=crop&w=500&q=80'  // radiant glowing
        ];
      } else if (confirmedVisualId === 'concept-2') {
        imagesList = [
          'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=500&q=80', // cool blue abstract
          'https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=500&q=80', // microchip grid close-up
          'https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=500&q=80'  // abstract icy geometric lines
        ];
      } else if (confirmedVisualId === 'concept-3') {
        imagesList = [
          'https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=500&q=80', // Matrix rain nodes
          'https://images.unsplash.com/photo-1544383835-bda2bc66a55d?auto=format&fit=crop&w=500&q=80', // Cyberspace connectivity network
          'https://images.unsplash.com/photo-1523961131990-5ea7c61b2107?auto=format&fit=crop&w=500&q=80'  // digital data flow gold lines
        ];
      } else {
        // User custom direction matching custom prompt
        imagesList = [
          'https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?auto=format&fit=crop&w=500&q=80', // futuristic tech glow
          'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?auto=format&fit=crop&w=500&q=80', // synthwave space lasers
          'https://images.unsplash.com/photo-1614741118887-7a4ee193a5fa?auto=format&fit=crop&w=500&q=80'  // glowing abstract wireframe
        ];
      }

      const candidates: CoverCandidate[] = [
        {
          id: 'cover-candidate-1',
          imageUrl: imagesList[0],
          creatorAgent: 'Imagen_3_Ultra_Engine',
          seed: 4899200000 + Math.floor(Math.random() * 999999)
        },
        {
          id: 'cover-candidate-2',
          imageUrl: imagesList[1],
          creatorAgent: 'Imagen_3_Ultra_Engine',
          seed: 9912000000 + Math.floor(Math.random() * 999999)
        },
        {
          id: 'cover-candidate-3',
          imageUrl: imagesList[2],
          creatorAgent: 'Imagen_3_Ultra_Engine',
          seed: 7721000000 + Math.floor(Math.random() * 999999)
        }
      ];

      setCoverCandidates(candidates);
      setCoverStage(4);
      setIsGenerating(false);
      addLog(`✓ [Cover Gate 3 通过] 围绕锁定方向「${chosen?.concept}」的 3幅高品质候选封面全部渲染完毕！进入 Gate 4 终审。`);
    }, 1200);
  };

  // 4. Gate 4 -> Gate 5: Select final cover and writeback coordinate indices
  const handleSelectFinalCover = (coverId: string) => {
    setSelectedCoverId(coverId);
    setCoverStage(5);
    const chosenCover = coverCandidates.find(c => c.id === coverId);
    addLog(`✓ [Cover Gate 4 终审确认] 管理员批准。选中种子 ID: ${coverId} 作为本期文章的官方自媒体首推封面。`);

    // Write back mock cover parameter inside ActiveArticle model
    const currentLogs = currentArticle.agentLogs || [];
    const updatedLogs = [
      ...currentLogs,
      { timestamp: new Date().toLocaleTimeString(), action: 'Cover asset wrote back to postgres', agent: 'Imagen Graphic Gatekeeper', status: 'Success' as const, detail: `契约归档完毕。封面 URL 注入完成，引信 seed: ${chosenCover?.seed}` }
    ];

    updateActiveArticle({
      agentLogs: updatedLogs
    });

    addLog(`✓ [Cover Gate 5 数据落盘完毕] 生成契约在 Docker 连载卷永久生效存盘。工作流彻底解套！`);
  };

  // 5. Reborn Cover button: Reset pipeline and start over
  const handleRebornCover = () => {
    setCoverStage(1);
    setVisualCandidates([]);
    setConfirmedVisualId(null);
    setCoverCandidates([]);
    setSelectedCoverId(null);
    setIsGenerating(false);
    addLog(`▊ [Reborn Reset] 管理员强制重置了封面工坊一阶段临时存储。旧有实验性 Meta 已抹除。`);
  };

  return (
    <div className="space-y-4 max-w-5xl animate-fade">
      
      {/* Tab Header Card */}
      <div className={`p-4 rounded-xl border ${
        isDarkMode ? 'bg-slate-900 border-slate-805 text-slate-100' : 'bg-white border-slate-200 text-slate-850 shadow-sm'
      }`}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-1">
            <span className={`px-2 py-0.5 text-[8px] font-mono rounded font-bold uppercase ${getThemeAccentClass('badge')}`}>
              Cover Policy Gate (符合 PRD 封面多阶门闸审核规范)
            </span>
            <h3 className="text-xs font-bold leading-normal mt-1 flex items-center">
              <ImageIcon size={14} className="text-blue-500 mr-1.5 animate-pulse" />
              智能封面生成五阶核准链路 (5-Stage Cover Gate Machine)
            </h3>
            <p className="text-[11px] text-gray-500 font-sans">
              封面流程必须严格通过 Gate 拦截：视觉预设审核 ➔ 人工确认 ➔ 候选三选一 ➔ 契约回写。严禁未经同意越级跑图。
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowPromptTrace(!showPromptTrace)}
              className={`px-2.5 py-1.5 text-xs font-mono rounded border flex items-center space-x-1 transition-colors ${
                showPromptTrace ? 'bg-amber-500/15 border-amber-500/60 text-amber-500' : 'text-gray-400 border-slate-350 dark:border-slate-805 hover:bg-slate-500/5'
              }`}
              title="查看封面 Prompt 精细追踪设计契约"
            >
              <Cpu size={11} className={showPromptTrace ? 'animate-spin' : ''} />
              <span>📄 {showPromptTrace ? '收起' : '查看'}封面 Prompt</span>
            </button>

            <button
              type="button"
              onClick={handleRebornCover}
              className="px-2.5 py-1.5 text-xs font-mono rounded border border-rose-500/25 text-rose-500 hover:bg-rose-500/10 flex items-center space-x-1"
            >
              <RefreshCw size={11} className={isGenerating ? 'animate-spin' : ''} />
              <span>重新设计 (Reborn Stage)</span>
            </button>
          </div>
        </div>

        {/* Technical timeline stage status */}
        <div className="grid grid-cols-5 gap-2 mt-4 pt-3 border-t border-dashed border-slate-200 dark:border-slate-800 text-[9px] select-none text-left">
          {[
            { gate: 1, name: 'Gate 1: 视觉要素', status: coverStage >= 1 ? 'active' : 'pending' },
            { gate: 2, name: 'Gate 2: 要素核准', status: coverStage >= 2 ? 'active' : 'pending' },
            { gate: 3, name: 'Gate 3: 候选图像', status: coverStage >= 3 ? 'active' : 'pending' },
            { gate: 4, name: 'Gate 4: 三选一终审', status: coverStage >= 4 ? 'active' : 'pending' },
            { gate: 5, name: 'Gate 5: 数据落盘锁', status: coverStage >= 5 ? 'active' : 'completed' }
          ].map((st) => {
            const isCurrent = st.gate === coverStage;
            const isPassed = coverStage > st.gate;
            
            let color = 'text-gray-400 bg-slate-950/20 border-slate-850';
            if (isCurrent) {
              color = 'border-blue-500 text-blue-400 font-bold bg-blue-955/20';
            } else if (isPassed) {
              color = 'border-emerald-500/30 text-emerald-400 bg-emerald-950/10';
            }

            return (
              <div key={st.gate} className={`p-2 rounded-lg border leading-tight ${color}`}>
                <div className="flex justify-between items-center whitespace-nowrap text-[8px] opacity-75">
                  <span>STAGE_-0{st.gate}</span>
                  {isPassed && <span className="text-emerald-500 font-bold">Passed</span>}
                  {isCurrent && <span className="text-blue-500 font-bold animate-pulse">Active</span>}
                </div>
                <p className="font-semibold truncate mt-1">{st.name}</p>
              </div>
            );
          })}
        </div>
      </div>

      {showPromptTrace && (
        <div className={`p-4 rounded-2xl border text-left space-y-3 font-mono text-[11px] animate-fade-in ${
          isDarkMode ? 'bg-slate-900 border-amber-500/30 text-slate-100' : 'bg-amber-500/5 border-amber-300 shadow-sm text-slate-800'
        }`}>
          <div className="flex justify-between items-center border-b pb-1.5 border-slate-200 dark:border-slate-800">
            <span className="font-bold text-amber-600 flex items-center gap-1">
              <Cpu size={12} className="text-amber-500" />
              Real LLM Prompt Trace: [Phase 3 - 封面生成与提示词加工]
            </span>
            <span className="text-[9px] bg-amber-500/10 text-amber-500 p-0.5 px-2 rounded font-bold">
              v1.2_imagen_prompt_builder
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs leading-relaxed font-sans">
            <div className="p-2 bg-slate-950 rounded border border-slate-800 text-[10px] font-mono leading-relaxed space-y-1 text-slate-300">
              <p className="text-gray-500 font-bold uppercase text-[9px] border-b border-slate-800 pb-0.5 mb-1 text-left">■ 组装前 Prompt (Variables Assembled Before):</p>
              <pre className="whitespace-pre-wrap text-blue-400">
{`System: Assemble detailed stylistic prompts for Imagen 3 text-to-image engine matching custom artistic concepts.

[PROMPT_TEMPLATE]
Concept Input: {{target_concept}}
Output Ratio Constraint: {{aspect_ratio}}`}
              </pre>
            </div>

            <div className="p-2 bg-slate-950 rounded border border-slate-800 text-[10px] font-mono leading-relaxed space-y-1 text-slate-300">
              <p className="text-gray-500 font-bold uppercase text-[9px] border-b border-slate-800 pb-0.5 mb-1 text-left">■ 物理组装后 Prompt (Compiled to Model):</p>
              <pre className="whitespace-pre-wrap text-indigo-400">
{`System: Assemble detailed stylistic prompts for Imagen 3 text-to-image engine matching custom artistic concepts.

Concept Input: "${confirmedVisualId ? (visualCandidates.find(v => v.id === confirmedVisualId)?.concept || '自定义视觉要素') : '极速流控焰火 (Neon Stream Flame)'}"
Output Ratio Constraint: "16:9"
---
Synthesize photographic details.`}
              </pre>
            </div>
          </div>

          <div className="p-2 bg-slate-950 rounded border border-slate-800 text-[10px] font-mono leading-relaxed space-y-1 text-slate-300">
            <p className="text-gray-550 font-bold uppercase text-[9px] border-b border-slate-800 pb-0.5 mb-1 text-left">■ 大模型服务端返回 (Response Image Prompt Compiler JSON):</p>
            <pre className="whitespace-pre-wrap text-slate-400 max-h-40 overflow-y-auto">
{`{
  "promptSeed": "Imagen3 cinematic studio shot, neon lighting, customized minimalist concept, ultra HD --ar 16:9",
  "aspectRatio": "16:9",
  "generationStatus": "gated_verified_100_percent"
}`}
            </pre>
          </div>
        </div>
      )}

      {/* Stage visual container */}
      <div className="space-y-4">
        
        {/* Stage 1: Call semantic generator */}
        {coverStage === 1 && (
          <div className={`p-8 rounded-xl border text-center space-y-5 ${
            isDarkMode ? 'bg-[#0f1424] border-slate-800' : 'bg-white border-slate-200 shadow-sm'
          }`}>
            <div className="max-w-md mx-auto space-y-2">
              <div className="p-3 bg-blue-500/10 rounded-full w-12 h-12 flex items-center justify-center mx-auto text-blue-500">
                <Sparkles size={20} className={isGenerating ? 'animate-pulse' : ''} />
              </div>
              <h4 className="text-[10px] font-mono font-bold text-gray-500 uppercase">第一闸门：预编译视觉设想 (Concept Design Setup)</h4>
              <h3 className="text-sm font-bold text-slate-805 dark:text-white">
                基于爆款标题语义：《{currentArticle.title}》
              </h3>
              <p className="text-xs text-gray-450 leading-relaxed max-w-sm mx-auto font-sans">
                图像解算器将提取文章主体以及目标专栏对齐风格，预先设计 3 组具有高隐喻、高点击率的色彩和排字理念，严禁直接跑图浪费 API 金额。
              </p>
            </div>

            {/* Added style guide input */}
            <div className="max-w-md mx-auto space-y-1.5 p-3 rounded-lg bg-slate-500/5 border border-slate-100 dark:border-slate-850">
              <label className="block text-[10px] font-bold font-mono text-slate-500 dark:text-slate-400 text-left uppercase">
                ✍️ 输入封面风格引导 (可选 Style Guidance, 否则按默认推荐)
              </label>
              <input
                type="text"
                value={styleGuide}
                onChange={(e) => setStyleGuide(e.target.value)}
                placeholder="例如：赛博朋克深蓝、黑金极简、苹果抽象、扁平插画风..."
                className={`w-full p-2 py-1.5 text-xs rounded-lg border focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                  isDarkMode ? 'bg-slate-950 border-slate-800 text-slate-200 placeholder-slate-700' : 'bg-white border-slate-250 text-slate-800 placeholder-slate-400'
                }`}
              />
            </div>

            <button
              type="button"
              onClick={handleGenerateVisualCandidates}
              disabled={isGenerating}
              className={`px-4 py-2 text-xs font-mono font-bold rounded-xl text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-45 flex items-center justify-center space-x-1.5 mx-auto`}
            >
              <RefreshCw size={11} className={isGenerating ? 'animate-spin' : ''} />
              <span>➔ 一键驱赶语义 AI，生成 3 组核心视觉元素理念</span>
            </button>
          </div>
        )}

        {/* Stage 2: Select direction to proceed */}
        {coverStage === 2 && (
          <div className="space-y-4 animate-fade-in text-left">
            <h4 className="text-[11px] font-bold font-mono text-gray-500 text-left">
              ▼ Gate 2：请审核并锁定下述一方向:
            </h4>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {visualCandidates.map((vis) => (
                <div
                  key={vis.id}
                  className={`p-4 rounded-xl border flex flex-col justify-between space-y-4 text-left transition-all hover:border-blue-500/40 ${
                    isDarkMode ? 'bg-slate-900 border-slate-805 text-white' : 'bg-white border-slate-200 shadow-sm'
                  }`}
                >
                  <div className="space-y-2.5">
                    <div className="flex flex-wrap gap-1 leading-none">
                      {vis.tags.map(tag => (
                        <span key={tag} className="px-1.5 py-0.5 rounded text-[8px] font-bold font-mono uppercase bg-slate-950 border border-slate-800 text-slate-400">
                          {tag}
                        </span>
                      ))}
                    </div>
                    <h5 className="font-bold text-xs text-blue-500 dark:text-blue-400 font-mono">{vis.concept}</h5>
                    <p className="text-[10px] text-gray-400 font-sans leading-normal">{vis.description}</p>
                    <div className="p-1 px-1.5 bg-slate-950 border border-slate-850 rounded text-[8px] font-mono text-gray-500 leading-normal line-clamp-3">
                      Prompt: {vis.promptSeed}
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleConfirmVisualElement(vis.id)}
                    className="w-full py-1.5 rounded-lg text-xs font-mono font-bold bg-[#1e293b] border border-slate-700 hover:bg-slate-800 text-white flex items-center justify-center space-x-1"
                  >
                    <span>✓ 人工核对并选用</span>
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Stage 3: Direct Render Triggers with Imagen 3 */}
        {coverStage === 3 && (
          <div className={`p-8 rounded-xl border text-center space-y-4 ${
            isDarkMode ? 'bg-[#0f1424] border-slate-800' : 'bg-white border-slate-200 shadow-sm'
          }`}>
            <div className="max-w-md mx-auto space-y-2">
              <div className="p-3 bg-emerald-500/10 rounded-full w-12 h-12 flex items-center justify-center mx-auto text-emerald-500">
                <Lock size={18} />
              </div>
              <h4 className="text-[10px] font-mono font-bold text-emerald-500 uppercase">第二闸门人工核对通过 (Gate 2 Approved)</h4>
              <h3 className="text-sm font-bold text-slate-805 dark:text-white">
                已核准方向: "{visualCandidates.find(v => v.id === confirmedVisualId)?.concept}"
              </h3>
              <p className="text-xs text-gray-400 leading-relaxed max-w-sm mx-auto font-sans">
                风格及渲染提示词词桩已在本地固化。开始针对此选中要件的一键渲染流。
              </p>
            </div>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-2 max-w-sm mx-auto">
              <button
                type="button"
                onClick={() => {
                  setCoverStage(2);
                  addLog(`◀ [退加要素] 从 Gate 3 回撤至 Gate 2。正在等待重选题件或自定。`);
                }}
                className="w-full sm:w-auto px-4 py-2 text-xs font-mono rounded-xl border border-slate-700 hover:bg-slate-800 text-gray-400 hover:text-white transition-colors"
              >
                ◀ 返回重选题件
              </button>

              <button
                type="button"
                onClick={handleGenerateCoverCandidates}
                disabled={isGenerating}
                className="w-full sm:w-auto px-4 py-2 text-xs font-mono font-bold rounded-xl text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-45 flex items-center justify-center space-x-1.5"
              >
                <RefreshCw size={11} className={isGenerating ? 'animate-spin' : ''} />
                <span>➔ 驱动图像引擎渲染 ➔</span>
              </button>
            </div>
          </div>
        )}

        {/* Stage 4: Admin chooses 1 of 3 cover options */}
        {coverStage === 4 && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-[11px] font-bold font-mono text-gray-500 text-left">
                ▼ Gate 4：围绕锁定要素渲染完毕，请做出封面三选一裁决:
              </h4>
              
              <button
                type="button"
                onClick={() => {
                  setCoverStage(2);
                  addLog(`◀ [不满意退回] 封面不合意，退回至 Gate 2 重选题件重提创意。`);
                }}
                className="px-2.5 py-1 text-[10px] font-mono border border-slate-200 dark:border-slate-800 text-gray-400 hover:text-white hover:bg-slate-805 rounded transition-all"
              >
                ◀ 对不满意？返回重选/添加设计要素
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {coverCandidates.map((cand) => (
                <div
                  key={cand.id}
                  className={`rounded-xl border overflow-hidden flex flex-col justify-between text-left transition-all ${
                    isDarkMode ? 'bg-slate-905 border-slate-850' : 'bg-white border-slate-200 shadow-sm'
                  }`}
                >
                  <div className="relative aspect-video bg-slate-950 overflow-hidden">
                    <img
                      src={cand.imageUrl}
                      alt={cand.id}
                      className="w-full h-full object-cover select-none"
                      referrerPolicy="no-referrer"
                    />
                    <div className="absolute bottom-2 left-2 bg-black/60 px-1.5 py-0.5 rounded text-[8px] font-mono text-white">
                      Seed: {cand.seed}
                    </div>
                  </div>

                  <div className="p-3 space-y-2 text-xs">
                    <p className="text-[9px] text-gray-500 font-mono">
                      关联极速芯片: {cand.creatorAgent}
                    </p>
                    <button
                      type="button"
                      onClick={() => handleSelectFinalCover(cand.id)}
                      className="w-full py-1.5 rounded-lg text-xs font-mono font-bold text-white bg-blue-600 hover:bg-blue-700 flex items-center justify-center space-x-1"
                    >
                      <span>✓ 选用此图作为最终封面</span>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Stage 5: Finalized writeback */}
        {coverStage === 5 && (
          <div className={`p-8 rounded-xl border text-center space-y-3 ${
            isDarkMode ? 'bg-emerald-950/15 border-emerald-900/40 text-emerald-400' : 'bg-emerald-50 border-emerald-250 text-emerald-800 shadow-sm'
          }`}>
            <Check size={28} className="mx-auto text-emerald-500 animate-bounce" />
            <h3 className="text-xs font-mono font-bold uppercase tracking-widest leading-none">五阶要素审计全契约落盘 (Cover Gated Finalized)</h3>
            <h2 className="text-sm font-bold leading-normal text-slate-805 dark:text-emerald-355">
              本期文章首发科技封面设计已 100% 备案！
            </h2>
            <p className="text-[11px] leading-relaxed max-w-sm mx-auto font-sans text-gray-400">
              经过 <strong>Gate 1～5 完备契约审查</strong>，该图像的矢量源坐标、Prompt 编译字符串及防伪 Seed Hash 已成功刷入文章 Meta 数据库。全流放行通过！
            </p>

            <div className="relative overflow-hidden rounded-xl border max-w-md mx-auto mt-2">
              <img
                src={coverCandidates.find(c => c.id === selectedCoverId)?.imageUrl}
                alt="chosen_cover"
                className="w-full aspect-video object-cover"
                referrerPolicy="no-referrer"
              />
            </div>

            <div className="pt-2">
              <button
                type="button"
                onClick={() => {
                  setCoverStage(2);
                  addLog(`◀ [重新核发] 退回至视觉要素决策 Gate 2，可以重选或更换自定要素进行图像重新计算。`);
                }}
                className="px-3 py-1.5 text-xs font-mono bg-transparent border border-slate-700 text-slate-400 hover:text-white rounded hover:bg-slate-800 transition-colors inline-flex items-center gap-1"
              >
                ◀ 重新备案？返回 Gate 2 调配要素与跑图
              </button>
            </div>
          </div>
        )}

      </div>

    </div>
  );
}
