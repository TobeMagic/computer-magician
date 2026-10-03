import React from 'react';
import { Lock, FileText, Sparkles, Sliders, CheckSquare, Plus, Check } from 'lucide-react';
import { Article } from '../types';

interface SpecsConfirmationProps {
  currentArticle: Article;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  updateActiveArticle: (fields: Partial<Article>) => void;
  addLog: (msg: string) => void;
  getThemeAccentClass: (type: any) => string;
  onLockSpecsAndGenerate: () => void;
}

export default function SpecsConfirmation({
  currentArticle,
  isDarkMode,
  accentColor,
  updateActiveArticle,
  addLog,
  getThemeAccentClass,
  onLockSpecsAndGenerate
}: SpecsConfirmationProps) {

  const handleSignSpecifications = (e: React.FormEvent) => {
    e.preventDefault();
    addLog(`✓ [签署放行] 规格合约签署完成！已有选题:《${currentArticle.title}》, 目标字数: ${currentArticle.targetWords || 4000}字, 风格: ${currentArticle.writingStyle || '硬核流'}`);
    onLockSpecsAndGenerate();
  };

  return (
    <div className="space-y-4 max-w-5xl animate-fade">
      
      {/* Specs Overview Header Banner */}
      <div className="p-4 bg-amber-50 border border-amber-200 dark:bg-amber-955/20 dark:border-amber-900/60 rounded-xl space-y-1.5 text-left">
        <h3 className="font-bold text-xs font-mono tracking-tight text-amber-850 dark:text-amber-400 flex items-center">
          <Lock size={14} className="mr-1.5 text-amber-500 animate-pulse" />
          一阶段：深度生文规格签署 (Stage-1 Project Intent & Specs Signing Gate)
        </h3>
        <p className="text-[11px] text-slate-705 dark:text-slate-300 leading-relaxed font-sans">
          在文章正式开始研搜和起草之前，请锁定该稿件的 <strong>核心元属性契约</strong>。签署放行后，任务将投入 <strong>网络探哨流水线</strong> 中同步检索权威技术文献、沉淀学术报告。
        </p>
      </div>

      <form 
        onSubmit={handleSignSpecifications}
        className={`p-6 border rounded-2xl space-y-5 text-xs font-sans text-left ${
          isDarkMode ? 'bg-slate-900 border-slate-800 text-slate-100' : 'bg-white border-slate-200 text-slate-850 shadow-sm'
        }`}
      >
        <div className="flex items-center space-x-2 border-b pb-2.5 dark:border-slate-800">
          <Sliders size={13} className={getThemeAccentClass('text')} />
          <span className="font-bold font-mono text-[11px] uppercase tracking-wider text-slate-400">核定生成契约参数 (Draft Parameters Validation)</span>
        </div>

        {/* 1. 已有选题 */}
        <div className="space-y-1.5">
          <label className="text-[10px] font-bold font-mono text-slate-500 dark:text-slate-400 block uppercase">
            📌 当前已有选题 (Active Topic Title) *
          </label>
          <div className="relative">
            <input
              type="text"
              required
              value={currentArticle.title}
              onChange={(e) => updateActiveArticle({ title: e.target.value })}
              placeholder="请输入或修订当前草签选题..."
              className={`w-full p-3 font-bold text-xs rounded-xl border focus:outline-none focus:ring-1 ${getThemeAccentClass('ring')} ${
                isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200'
              }`}
            />
            <div className="absolute right-3 top-3 text-[9px] font-mono text-gray-500">
              ID: {currentArticle.id}
            </div>
          </div>
          <p className="text-[9.5px] text-gray-400 leading-normal">
            💡 已有选题已结合全域热点算法库为您做前置锁定（选题不可为空），您也可以在此直接细节修正微调。
          </p>
        </div>

        {/* 2. 目标字数 and 文章类型 and 专栏名称 */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 border-t border-dashed dark:border-slate-800 pt-4">
          <div className="space-y-1.5">
            <label className="text-[10px] font-bold font-mono text-slate-500 dark:text-slate-400 block uppercase">
              📊 目标生成字数规限 (Target Words) *
            </label>
            <input
              type="number"
              required
              min={100}
              max={50000}
              value={currentArticle.targetWords || 4000}
              onChange={(e) => updateActiveArticle({ targetWords: Number(e.target.value) })}
              className={`w-full p-2.5 rounded-lg border focus:outline-none ${
                isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200'
              }`}
            />
            <span className="text-[9px] text-gray-400 block leading-tight">首选推荐: 3000 ~ 5000 字</span>
          </div>

          <div className="space-y-1.5">
            <label className="text-[10px] font-bold font-mono text-slate-500 dark:text-slate-400 block uppercase">
              🧭 题材与流派 (Article Type)
            </label>
            <input
              type="text"
              required
              value={currentArticle.type || ''}
              onChange={(e) => updateActiveArticle({ type: e.target.value })}
              placeholder="请输入自定义题材/流派 (建议流派在下方)"
              className={`w-full p-2.5 rounded-lg border focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs ${
                isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200'
              }`}
            />
            <div className="flex flex-wrap gap-1 mt-1.5 pt-0.5">
              <span className="text-[9px] text-gray-400 mr-1 self-center">💡 建议题材:</span>
              {['动手实战', '技术八股', '行业深度', '新闻快讯'].map((suggested) => (
                <button
                  key={suggested}
                  type="button"
                  onClick={() => updateActiveArticle({ type: suggested })}
                  className={`px-1.5 py-0.5 rounded text-[9px] font-mono border transition-all ${
                    currentArticle.type === suggested
                      ? 'bg-blue-500/10 border-blue-500 text-blue-500 font-semibold'
                      : 'border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-gray-400 hover:text-blue-500 hover:border-blue-500/50'
                  }`}
                >
                  {suggested}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-[10px] font-bold font-mono text-slate-500 dark:text-slate-400 block uppercase flex items-center justify-between">
              <span>📚 连载专栏匹配 (Series)</span>
              {currentArticle.seriesName && (
                <span className="text-[8.5px] text-amber-500 font-mono font-bold flex items-center gap-0.5 bg-amber-500/5 px-1 py-0.2 rounded border border-amber-500/10">
                  <Lock size={10} /> 专栏匹配不可修改
                </span>
              )}
            </label>
            <input
              type="text"
              disabled={!!currentArticle.seriesName}
              readOnly={!!currentArticle.seriesName}
              value={currentArticle.seriesName || '自营文章工作流'}
              onChange={(e) => updateActiveArticle({ seriesName: e.target.value })}
              className={`w-full p-2.5 rounded-lg border focus:outline-none text-xs ${
                currentArticle.seriesName
                  ? 'bg-slate-100 dark:bg-slate-950 text-gray-400 dark:text-gray-500 border-slate-200 dark:border-slate-850 cursor-not-allowed select-none'
                  : isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200'
              }`}
            />
          </div>
        </div>

        {/* 3. 文章风格确认 */}
        <div className="space-y-1.5 border-t border-dashed dark:border-slate-800 pt-4">
          <label className="text-[10px] font-bold font-mono text-slate-500 dark:text-slate-400 block uppercase">
            🎨 文章起草风格控制 (Writing Style Recommendation) *
          </label>
          <textarea
            required
            rows={3.5}
            value={currentArticle.writingStyle || '一手故障现身说法复盘，直入重灾代码高频调用。全篇注重代码实践，拒绝无用AI行话、修饰废话，力求学术级精确度与开发者极致共鸣感。'}
            onChange={(e) => updateActiveArticle({ writingStyle: e.target.value })}
            placeholder="请输入期望文章写作的风格约束条件、特定排字语气..."
            className={`w-full p-3 text-[11px] leading-relaxed font-sans rounded-xl border focus:outline-none focus:ring-1 ${getThemeAccentClass('ring')} ${
              isDarkMode ? 'bg-slate-950 border-slate-850 text-white' : 'bg-slate-50 border-slate-200'
            }`}
          />
          <p className="text-[9.5px] text-gray-400 leading-normal">
            💡 支持精细定制词、语言范式约束（如“禁止套话”、“多增加案例对照跑分”），生文引擎将动态融合至流控提示词核心层中。
          </p>
        </div>

        {/* Lock Spec Actions and Advance Gate */}
        <div className="pt-4 border-t border-slate-100 dark:border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="text-left space-y-0.5">
            <div className="flex items-center space-x-1 font-mono text-[9px] text-emerald-500 font-bold">
              <Check size={11} className="animate-bounce" />
              <span>✓ 签署门卡准备完毕 · 原信息无断代</span>
            </div>
            <p className="text-[9px] text-gray-400">
              点击签署确认，将直接流转至 <strong>“2. 网络多源研搜流水线”</strong> 执行分布式权威探哨。
            </p>
          </div>

          <button
            type="submit"
            className="w-full sm:w-auto px-6 py-2.5 font-bold font-mono text-xs text-white rounded-xl bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-700 hover:to-orange-700 transition-all shadow-md active:scale-95 flex items-center justify-center space-x-1"
          >
            <span>🚀 签署放行，开始全网探哨搜探 ➔</span>
          </button>
        </div>

      </form>

    </div>
  );
}
