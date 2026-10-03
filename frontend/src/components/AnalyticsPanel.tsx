import React, { useState, useEffect } from 'react';
import {
  TrendingUp,
  AlertTriangle,
  Bookmark,
  Share2,
  Cpu,
  RefreshCw,
  Plus,
  Compass,
  CheckCircle,
  Clock,
  ArrowRight
} from 'lucide-react';
import { OptimizerTask, Article } from '../types';
import { get, listCredentials } from '../api';
import { createOptimizerTask, updateOptimizerTask } from '../api/optimizerTasks';
import { mapOptimizerTaskFromApi } from '../types';

interface AnalyticsPanelProps {
  optimizerTasks: OptimizerTask[];
  setOptimizerTasks: React.Dispatch<React.SetStateAction<OptimizerTask[]>>;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  articles: Article[];
}

export default function AnalyticsPanel({
  optimizerTasks,
  setOptimizerTasks,
  isDarkMode,
  accentColor,
  articles
}: AnalyticsPanelProps) {
  const [taskTitleText, setTaskTitleText] = useState('');
  const [taskCategory, setTaskCategory] = useState<'Prompt' | 'Formatter' | 'Publisher' | 'Asset'>('Prompt');
  const [taskDescText, setTaskDescText] = useState('');
  const [taskPriority, setTaskPriority] = useState<'High' | 'Medium' | 'Low'>('Medium');
  const [platformHealth, setPlatformHealth] = useState<any[]>([]);
  const [recentEvents, setRecentEvents] = useState<any[]>([]);

  // Fetch real data from backend
  useEffect(() => {
    const fetchData = async () => {
      try {
        const [creds, events] = await Promise.allSettled([
          listCredentials(),
          get<any[]>('/api/events', { limit: 20, level: 'warning' }),
        ]);
        if (creds.status === 'fulfilled') setPlatformHealth(creds.value);
        if (events.status === 'fulfilled') setRecentEvents(events.value);
      } catch {}
    };
    fetchData();
  }, []);

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

  // Create new optimization task from review (PRD Section 6.9)
  const handleCreateOptimizeTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskTitleText.trim()) {
      alert('请填写优化任务标题！');
      return;
    }

    try {
      const newTask = await createOptimizerTask({
        source_type: taskCategory,
        title: taskTitleText.trim(),
        description: taskDescText || '人工提报的技术优化规则，用于改进大语言模型及推包适配层质量。',
        priority: taskPriority,
        status: 'Pending',
      });

      setOptimizerTasks([mapOptimizerTaskFromApi(newTask), ...optimizerTasks]);
      setTaskTitleText('');
      setTaskDescText('');
      alert(`成功沉淀并创建优化任务！此任务将在 Prompts 管理及 Agent 运行沙中动态挂接，以治理历史发布质量。`);
    } catch (err) {
      console.error('Failed to create optimizer task:', err);
    }
  };

  // Toggle optimization task done — persist via API
  const handleToggleTaskStatus = async (id: string) => {
    const current = optimizerTasks.find((t) => t.id === id);
    if (!current) return;
    const newStatus = current.status === 'Applied' ? 'Pending' : 'Applied';
    // Optimistic update
    setOptimizerTasks((prev) =>
      prev.map((t) => (t.id === id ? { ...t, status: newStatus } : t))
    );
    try {
      await updateOptimizerTask(id, { status: newStatus });
    } catch (err) {
      console.error('Failed to persist task status:', err);
      // Revert on failure
      setOptimizerTasks((prev) =>
        prev.map((t) => (t.id === id ? { ...t, status: current.status } : t))
      );
    }
  };

  return (
    <div className={`flex-1 flex flex-col h-full min-h-0 overflow-hidden ${
      isDarkMode ? 'bg-[#0f1424] text-white' : 'bg-white text-slate-800'
    }`}>
      <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-hidden">
        {/* Left: Quality status graphs */}
        <div className="flex-1 p-4 md:p-6 overflow-y-auto space-y-6">
          
          {/* Quick Stats overview panel */}
          <div className="mb-4">
            <h3 className="text-base font-bold tracking-tight mb-1">
              自媒体持续优化与质量复盘引擎
            </h3>
            <p className="text-xs text-gray-500">
              通过将发布失败、Cookie 被拒、数学公式失配和 SVG 溢出等问题分类回溯，沉淀提炼为真实的 **Prompt 改进任务** 与 **格式适配器迭代方向**。
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Platform failure distribution from real credentials */}
            <div className="p-4 border dark:border-[#1e2a44] rounded-xl bg-white dark:bg-slate-900 space-y-3">
              <h4 className="font-bold text-xs font-mono text-gray-500 uppercase tracking-widest flex items-center justify-between">
                <span>⚠️ 平台状态与故障分布</span>
                <span className="text-emerald-500 text-[10px]">实时追踪</span>
              </h4>

              <div className="space-y-2 text-xs">
                {platformHealth.length > 0 ? platformHealth.slice(0, 5).map((cred, idx) => (
                  <div key={idx} className="p-2.5 bg-slate-50 dark:bg-slate-950 rounded border border-slate-100 dark:border-slate-800">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-slate-800 dark:text-white">{cred.platform || 'Unknown'}</span>
                      <span className={`font-mono text-[10px] font-bold ${cred.readiness === 'ready' ? 'text-emerald-500' : 'text-rose-500'}`}>
                        {cred.readiness || 'Unknown'}
                      </span>
                    </div>
                    {cred.blockers_json?.items?.[0]?.message && (
                      <p className="text-[10px] text-gray-400 mt-1 leading-normal italic">
                        {cred.blockers_json.items[0].message}
                      </p>
                    )}
                  </div>
                )) : (
                  <div className="p-2.5 bg-slate-50 dark:bg-slate-950 rounded border border-slate-100 dark:border-slate-800 text-center text-gray-400">
                    加载中...
                  </div>
                )}
              </div>
            </div>

            {/* Recent warning events from backend */}
            <div className="p-4 border dark:border-[#1e2a44] rounded-xl bg-white dark:bg-slate-900 space-y-3">
              <h4 className="font-bold text-xs font-mono text-gray-400 tracking-widest uppercase">
                ⚙️ 近期告警事件
              </h4>

              <div className="space-y-3 pt-1">
                {recentEvents.length > 0 ? recentEvents.slice(0, 5).map((evt, idx) => (
                  <div key={idx} className="text-xs">
                    <div className="flex justify-between items-center text-[10px] font-mono mb-1">
                      <span className="text-slate-700 dark:text-slate-350 truncate">{evt.event_type || evt.message || 'Event'}</span>
                      <strong className="font-bold text-slate-500">{evt.platform || ''}</strong>
                    </div>
                    <div className="w-full bg-slate-100 dark:bg-slate-800 h-1.5 rounded-full overflow-hidden">
                      <div className="h-full bg-amber-500 rounded-full" style={{ width: '100%' }}></div>
                    </div>
                  </div>
                )) : (
                  <div className="text-xs text-gray-400 text-center py-4">暂无告警事件</div>
                )}
              </div>
            </div>
          </div>

          {/* Optimizer task log list */}
          <div className="space-y-3">
            <h4 className="font-bold text-xs font-mono text-gray-400 tracking-wider">
              ✅ 自媒体运行时优化整改任务 ({optimizerTasks.length} 个沉淀链条)
            </h4>

            <div className="space-y-2">
              {optimizerTasks.map((task) => {
                const isApplied = task.status === 'Applied';
                let typeBadge = 'bg-stone-100 text-stone-600';
                if (task.sourceType === 'Formatter') typeBadge = 'bg-blue-100 text-blue-800';
                else if (task.sourceType === 'Prompt') typeBadge = 'bg-amber-100 text-amber-800';
                else if (task.sourceType === 'AgentRunbook') typeBadge = 'bg-indigo-100 text-indigo-800';

                return (
                  <div
                    key={task.id}
                    className={`p-3.5 border rounded-lg transition-all flex items-start justify-between bg-white dark:bg-slate-900 ${
                      isApplied ? 'opacity-50 border-slate-200 line-through' : 'border-slate-300 dark:border-slate-800'
                    }`}
                  >
                    <div className="space-y-1.5 min-w-0 pr-4">
                      <div className="flex items-center space-x-2">
                        <span className={`px-2 py-0.2 rounded text-[8px] font-mono font-bold ${typeBadge}`}>
                          {task.sourceType}
                        </span>
                        
                        <span className="font-mono text-[9px] text-gray-400">
                          {task.createdTime}
                        </span>

                        <span className={`text-[9px] font-bold ${task.priority === 'High' ? 'text-rose-500' : 'text-slate-400'}`}>
                          [{task.priority} Priority]
                        </span>
                      </div>

                      <p className={`font-semibold text-xs text-slate-800 dark:text-slate-100`}>
                        {task.title}
                      </p>

                      <p className="text-[10px] text-gray-500 leading-relaxed font-sans">
                        诊断根因: {task.description}
                      </p>
                    </div>

                    <button
                      onClick={() => handleToggleTaskStatus(task.id)}
                      className={`px-2.5 py-1 rounded text-[10px] font-mono shrink-0 cursor-pointer ${
                        isApplied
                          ? 'bg-slate-200 text-slate-700'
                          : 'bg-emerald-700 text-white hover:bg-emerald-800'
                      }`}
                    >
                      {isApplied ? '已归档 Applied' : '标记已优化 Resolved'}
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
