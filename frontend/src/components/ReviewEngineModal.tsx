import React, { useState } from 'react';
import {
  TrendingUp,
  AlertTriangle,
  X,
  Plus,
  Cpu,
  Bookmark,
  Sparkles,
  CheckCircle,
  Clock,
  Layers,
  ArrowRight
} from 'lucide-react';
import { Article, OptimizerTask, mapOptimizerTaskFromApi } from '../types';
import { createOptimizerTask } from '../api/optimizerTasks';

interface ReviewEngineModalProps {
  articles: Article[];
  optimizerTasks: OptimizerTask[];
  setOptimizerTasks: React.Dispatch<React.SetStateAction<OptimizerTask[]>>;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
}

export default function ReviewEngineModal({
  articles,
  optimizerTasks,
  setOptimizerTasks,
  isDarkMode,
  accentColor,
  isOpen,
  setIsOpen
}: ReviewEngineModalProps) {
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Form states
  const [taskTitle, setTaskTitle] = useState('');
  const [taskCategory, setTaskCategory] = useState<'Prompt' | 'Formatter' | 'Publisher' | 'Asset' | 'AgentRunbook' | 'SeriesPlan'>('Prompt');
  const [taskDesc, setTaskDesc] = useState('');
  const [taskPriority, setTaskPriority] = useState<'High' | 'Medium' | 'Low'>('Medium');
  const [selectedArticleId, setSelectedArticleId] = useState<string>('');

  const getThemeAccentClass = (type: 'text' | 'bg' | 'border' | 'button-active') => {
    if (accentColor === 'blue') {
      if (type === 'text') return 'text-[#0077b6]';
      if (type === 'bg') return 'bg-[#0077b6] text-white';
      if (type === 'border') return 'border-[#0077b6]';
      return 'bg-blue-600 hover:bg-blue-700 text-white';
    } else if (accentColor === 'green') {
      if (type === 'text') return 'text-[#2d6a4f]';
      if (type === 'bg') return 'bg-[#2d6a4f] text-white';
      if (type === 'border') return 'border-[#2d6a4f]';
      return 'bg-emerald-700 hover:bg-emerald-800 text-white';
    } else {
      if (type === 'text') return 'text-[#7f5539]';
      if (type === 'bg') return 'bg-[#7f5539] text-white';
      if (type === 'border') return 'border-[#7f5539]';
      return 'bg-amber-700 hover:bg-amber-800 text-white';
    }
  };

  // Preset list for premium automation & user-friendly experience
  const PRESETS = [
    {
      title: '微信排版组件 LaTeX 换行对齐调优',
      category: 'Formatter' as const,
      description: '解决微信公众号中段内 LaTeX 公式在高频渲染时发生换行失配的问题，需要注入特定的 CSS display: inline-flex 配置。',
      priority: 'High' as const
    },
    {
      title: '大模型写假话 (SEO AI Slop) 冗余无用词精细过滤 Prompt 升级',
      category: 'Prompt' as const,
      description: '在核心大写模板中，追加「一手实践复盘风格纠偏」，要求禁止出现如"正如我们所知"、"不可否认"等 AI 惯用套话。',
      priority: 'High' as const
    },
    {
      title: '稀土掘金平台安全 Session 校验探哨重试机制',
      category: 'Publisher' as const,
      description: '由于掘金滑块限制，当 Cookie Expired 时，触发自动短信探哨并让 Node 会话层回落至 Pending_Manual 状态。',
      priority: 'Medium' as const
    },
    {
      title: '16:9 封面插图 SVG 矢量极密打包防崩规则',
      category: 'Asset' as const,
      description: '通过建立影子缓冲，把 Imagen-3 生成的巨量超 HD 图片压缩 25% 以防边缘节点 CloudFront 网络背压崩溃。',
      priority: 'Low' as const
    }
  ];

  const applyPreset = (preset: typeof PRESETS[0]) => {
    setTaskTitle(preset.title);
    setTaskCategory(preset.category);
    setTaskDesc(preset.description);
    setTaskPriority(preset.priority);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskTitle.trim() || !taskDesc.trim()) {
      return;
    }

    const linkedArticle = articles.find(a => a.id === selectedArticleId);

    try {
      const newTask = await createOptimizerTask({
        source_type: taskCategory,
        title: taskTitle.trim(),
        description: taskDesc.trim(),
        related_article_id: linkedArticle?.id,
        related_article_title: linkedArticle?.title,
        priority: taskPriority,
        status: 'Pending',
      });

      setOptimizerTasks([mapOptimizerTaskFromApi(newTask), ...optimizerTasks]);
      
      // Success feedback
      setSuccessMsg(`🚀 成功提报优化复盘任务「${taskTitle.substring(0, 16)}...」！任务已在质量中枢与 Prompts 沙箱中实时挂扣生效。`);
      
      // Reset form after submission
      setTaskTitle('');
      setTaskDesc('');
      setSelectedArticleId('');
      
      // Clear success msg after 4s
      setTimeout(() => {
        setSuccessMsg(null);
      }, 4500);
    } catch (err) {
      console.error('Failed to create optimizer task:', err);
    }
  };

  return (
    <>
      {/* Global Review success Toast message */}
      {successMsg && (
        <div 
          id="global-review-toast"
          className="fixed bottom-6 right-6 z-50 pointer-events-auto max-w-sm p-3.5 rounded-xl border border-emerald-500/30 bg-slate-950 text-emerald-400 text-[11px] font-mono shadow-2xl animate-fade-in leading-relaxed text-left flex gap-2 items-start"
        >
          <CheckCircle size={15} className="shrink-0 text-emerald-400 animate-pulse mt-0.5" />
          <div>
            <p className="font-bold text-[9.5px]">【质量引擎成功登记】</p>
            <p className="opacity-90 mt-0.5">{successMsg}</p>
          </div>
        </div>
      )}

      {/* 2. Overlaid Review Engine Dialog */}
      {isOpen && (
        <div 
          id="global-review-engine-modal"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-955/70 backdrop-blur-sm animate-fade-in pointer-events-auto"
        >
          <div 
            className={`w-full max-w-2xl rounded-2xl border overflow-hidden flex flex-col max-h-[88vh] shadow-2xl animate-zoom-in ${
              isDarkMode ? 'bg-[#0b101d] border-slate-800 text-white' : 'bg-white border-slate-200 text-slate-800'
            }`}
          >
            {/* Header */}
            <div className={`p-4 border-b flex items-center justify-between ${
              isDarkMode ? 'border-slate-800 bg-[#070b13]' : 'border-slate-100 bg-[#fafafa]'
            }`}>
              <div className="flex items-center space-x-2 text-left">
                <div className="p-1.5 rounded-lg bg-amber-500/10 text-amber-500">
                  <Cpu size={16} className="animate-pulse" />
                </div>
                <div>
                  <h4 className="font-bold text-sm leading-tight">自媒体持续优化与质量复盘引擎 (Continuous Optimization Center)</h4>
                  <p className="text-[10px] text-gray-500 font-mono">
                    追踪线上排版、生成与分发中的故障反馈，提报并生成规则闭环。
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="p-1.5 rounded-lg hover:bg-slate-500/10 transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            {/* Content body Scrollable */}
            <div className="p-5 overflow-y-auto space-y-4 text-left custom-scrollbar text-xs">
              
              {/* Presets Grid */}
              <div className="space-y-1.5">
                <span className="text-[10px] font-mono text-gray-500 uppercase tracking-wider flex items-center gap-1">
                  <Sparkles size={11} className="text-amber-500" />
                  常见生产复盘故障快速选取 & 预设一键填报:
                </span>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {PRESETS.map((p, idx) => (
                    <div
                      key={idx}
                      onClick={() => applyPreset(p)}
                      className={`p-2 rounded-lg border text-left cursor-pointer transition-all hover:scale-[1.01] ${
                        isDarkMode
                          ? 'bg-slate-900 border-slate-800 hover:border-amber-500/40 hover:bg-slate-900/80'
                          : 'bg-slate-50 border-slate-150 hover:bg-[#fffdfa] hover:border-amber-400'
                      }`}
                    >
                      <div className="flex justify-between items-center text-[9px] font-mono">
                        <span className="text-amber-600 font-bold">[{p.category}]</span>
                        <span className={p.priority === 'High' ? 'text-red-500 font-bold' : 'text-gray-400'}>
                          {p.priority}
                        </span>
                      </div>
                      <p className="font-bold text-[10.5px] mt-1 leading-snug line-clamp-1">{p.title}</p>
                      <p className="text-[9.5px] text-gray-400 mt-0.5 line-clamp-1 leading-normal italic">{p.description}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Form Entry */}
              <form onSubmit={handleSubmit} className="space-y-3.5 pt-1.5 border-t border-slate-200 dark:border-slate-800">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {/* Task Title */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-mono text-gray-400 block font-bold leading-normal">1. 优化/质量复盘任务标题 *</label>
                    <input
                      type="text"
                      required
                      value={taskTitle}
                      onChange={(e) => setTaskTitle(e.target.value)}
                      placeholder="如: 将 Markdown 中 Writable write 返回值加双向检查"
                      className="w-full p-2 border rounded-lg focus:outline-none focus:ring-1 focus:ring-amber-500 dark:bg-slate-950 dark:border-slate-800 text-[11px]"
                    />
                  </div>

                  {/* Related Article link */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-mono text-gray-400 block font-bold leading-normal">
                      2. 关联选题草稿 (Optional Linked Draft)
                    </label>
                    <select
                      value={selectedArticleId}
                      onChange={(e) => setSelectedArticleId(e.target.value)}
                      className="w-full p-2 border rounded-lg focus:outline-none focus:ring-1 focus:ring-amber-500 bg-white dark:bg-slate-955 dark:border-slate-800 text-[11px]"
                    >
                      <option value="">-- 不进行特定选题挂载 --</option>
                      {articles.map((art) => (
                        <option key={art.id} value={art.id}>
                          📜 ({art.status}) {art.title}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {/* Category */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-mono text-gray-400 block font-bold leading-normal">3. 归因技术领域分类 *</label>
                    <select
                      value={taskCategory}
                      onChange={(e: any) => setTaskCategory(e.target.value)}
                      className="w-full p-2 border rounded-lg focus:outline-none focus:ring-1 focus:ring-amber-500 bg-white dark:bg-slate-955 dark:border-slate-800 text-[11px]"
                    >
                      <option value="Prompt">Prompt 核心指令持续对调</option>
                      <option value="Formatter">排版格式渲染适配器调优</option>
                      <option value="Publisher">分发推包与 Session 持久链路</option>
                      <option value="Asset">图床合规/SVG滑动矢量微调</option>
                      <option value="AgentRunbook">Agent工作流智能决策修订</option>
                      <option value="SeriesPlan">长期宏观策划对齐</option>
                    </select>
                  </div>

                  {/* Priority */}
                  <div className="space-y-1">
                    <label className="text-[10px] font-mono text-gray-400 block font-bold leading-normal">4. 优化修复紧急等级 *</label>
                    <div className="flex gap-4 items-center h-9 font-mono px-1">
                      {['High', 'Medium', 'Low'].map((pr) => (
                        <label key={pr} className="flex items-center space-x-1.5 cursor-pointer text-[10.5px]">
                          <input
                            type="radio"
                            name="modal-priority"
                            checked={taskPriority === pr}
                            onChange={() => setTaskPriority(pr as any)}
                            className="text-amber-500 focus:ring-amber-500"
                          />
                          <span className={pr === 'High' ? 'text-red-500 font-bold' : 'text-slate-400'}>{pr}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Description */}
                <div className="space-y-1">
                  <label className="text-[10px] font-mono text-gray-400 block font-bold leading-normal">
                    5. 问题真实成因与优化步骤审计 (Root Cause & Next steps) *
                  </label>
                  <textarea
                    required
                    value={taskDesc}
                    onChange={(e) => setTaskDesc(e.target.value)}
                    placeholder="请输入问题发生时的具体表现，及对此提报的解决方案细节..."
                    rows={4}
                    className="w-full p-2.5 border rounded-lg focus:outline-none focus:ring-1 focus:ring-amber-500 dark:bg-slate-950 dark:border-slate-800 text-[11px]"
                  />
                </div>

                {/* Footer buttons inside Modal */}
                <div className="flex justify-end gap-2 pt-3 border-t border-slate-200 dark:border-slate-800">
                  <button
                    type="button"
                    onClick={() => setIsOpen(false)}
                    className="px-4 py-2 border rounded-lg border-slate-300 dark:border-slate-800 hover:bg-slate-500/5 text-gray-400 font-mono transition-colors"
                  >
                    取消 Close
                  </button>
                  <button
                    type="submit"
                    className={`px-5 py-2 rounded-lg font-bold font-mono tracking-wide flex items-center justify-center space-x-1 transition-all ${getThemeAccentClass('button-active')}`}
                  >
                    <Plus size={12} className="shrink-0" />
                    <span>提交此轮复盘 接入沙箱治理</span>
                  </button>
                </div>
              </form>

            </div>

          </div>
        </div>
      )}
    </>
  );
}
