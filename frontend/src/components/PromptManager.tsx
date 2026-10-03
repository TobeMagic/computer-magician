import React, { useState } from 'react';
import {
  Bookmark,
  Plus,
  RefreshCw,
  GitBranch,
  CheckCircle,
  Eye,
  Trash2,
  Lock,
  ChevronRight,
  Clipboard
} from 'lucide-react';
import { PromptRule } from '../types';
import { getPromptVersions, getPromptSnapshots, activatePromptVersion, createPromptVersion } from '../api';

interface PromptManagerProps {
  promptRules: PromptRule[];
  setPromptRules: React.Dispatch<React.SetStateAction<PromptRule[]>>;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
}

export default function PromptManager({
  promptRules,
  setPromptRules,
  isDarkMode,
  accentColor
}: PromptManagerProps) {
  const [selectedPromptId, setSelectedPromptId] = useState('p-1');
  const [editingContent, setEditingContent] = useState('');
  const [activeVersionTab, setActiveVersionTab] = useState<'current' | 'history'>('current');
  const [promptVersions, setPromptVersions] = useState<any[]>([]);
  const [promptSnapshots, setPromptSnapshots] = useState<any[]>([]);

  const activePrompt = promptRules.find((p) => p.id === selectedPromptId) || promptRules[0];

  // Sync edit state
  React.useEffect(() => {
    if (activePrompt) {
      setEditingContent(activePrompt.content);
    }
  }, [selectedPromptId, activePrompt]);

  // Fetch prompt versions from backend
  React.useEffect(() => {
    const fetchVersions = async () => {
      if (!activePrompt?.id) return;
      try {
        const versions = await getPromptVersions(activePrompt.id);
        setPromptVersions(versions || []);
      } catch {
        setPromptVersions([]);
      }
    };
    fetchVersions();
  }, [activePrompt?.id]);

  // Fetch prompt snapshots from backend
  React.useEffect(() => {
    const fetchSnapshots = async () => {
      if (!activePrompt?.id) return;
      try {
        const snapshots = await getPromptSnapshots(activePrompt.id, { limit: 10 });
        setPromptSnapshots(snapshots || []);
      } catch {
        setPromptSnapshots([]);
      }
    };
    fetchSnapshots();
  }, [activePrompt?.id]);

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

  const handleSavePrompt = async () => {
    try {
      // Create new version via backend API
      const newVersion = await createPromptVersion(activePrompt.id, {
        content: editingContent,
      });
      
      // Activate the new version
      if (newVersion?.id) {
        await activatePromptVersion(activePrompt.id, newVersion.id);
      }
      
      // Refresh versions list
      const versions = await getPromptVersions(activePrompt.id);
      setPromptVersions(versions || []);
      
      // Update local state
      setPromptRules((prev) =>
        prev.map((p) => {
          if (p.id === selectedPromptId) {
            const vSegments = p.version.split('.');
            const nextMinor = Number(vSegments[2] || 0) + 1;
            const nextVersion = `${vSegments[0]}.${vSegments[1]}.${nextMinor}`;
            return {
              ...p,
              content: editingContent,
              version: nextVersion,
              lastUpdated: new Date().toISOString().split('T')[0]
            };
          }
          return p;
        })
      );
      alert(`✅ Prompt 规则已保存并激活！新版本 ID: ${newVersion?.id || 'unknown'}`);
    } catch (error: any) {
      alert(`❌ 保存失败: ${error?.message || '请检查网络连接'}`);
    }
  };

  const handleCopyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    alert('已复制 Prompt 首选模板代码至剪贴板！');
  };

  return (
    <div className={`flex-1 flex flex-col h-full min-h-0 overflow-hidden ${
      isDarkMode ? 'bg-[#0f1424] text-white' : 'bg-white text-slate-800'
    }`}>
      <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-hidden">
        {/* Left Side: Prompts List catalog */}
        <div className={`w-full lg:w-80 border-b lg:border-b-0 lg:border-r p-4 space-y-3 overflow-y-auto h-56 lg:h-full shrink-0 ${
          isDarkMode ? 'bg-[#0c101d] border-[#1e2a44]' : 'bg-[#fcfbf9] border-[#e2e0db]'
        }`}>
          <div className="flex items-center justify-between gap-2 pb-1">
            <h4 className="font-bold text-[10px] font-mono text-gray-400 tracking-widest uppercase truncate">
              🧠 全流程规则资产库
            </h4>
            <button
              onClick={() => {
                const freshId = `p-${promptRules.length + 1}`;
                const newPrompt: PromptRule = {
                  id: freshId,
                  name: '新拟技术自媒体 Prompt 风格规则草稿',
                  category: 'TitleGeneration',
                  content: '你的任务是在此补充新的技术文案生成指令...',
                  status: 'Draft',
                  version: '1.0.0',
                  lastUpdated: new Date().toISOString().split('T')[0],
                  author: 'AImagician'
                };
                setPromptRules((prev) => [...prev, newPrompt]);
                setSelectedPromptId(freshId);
              }}
              className={`flex items-center px-2 py-1 rounded text-[9px] font-extrabold tracking-tight transition-all shrink-0 text-white cursor-pointer ${getThemeAccentClass('bg')}`}
            >
              <Plus size={9} className="mr-0.5" />
              <span>拟草规则</span>
            </button>
          </div>

          <div className="space-y-2">
            {promptRules.map((p) => {
              const isSelected = p.id === selectedPromptId;
              let statusColor = 'bg-slate-100 text-slate-600';
              if (p.status === 'Active') statusColor = 'bg-emerald-100 text-emerald-800';
              else if (p.status === 'Testing') statusColor = 'bg-blue-100 text-blue-800';

              return (
                <div
                  key={p.id}
                  onClick={() => setSelectedPromptId(p.id)}
                  className={`p-3 rounded-lg border text-xs cursor-pointer transition-all ${
                    isSelected
                      ? isDarkMode
                        ? 'bg-[#1a233b] border-[#00b4d8]'
                        : 'bg-white border-[#0077b6] shadow-sm'
                      : isDarkMode
                      ? 'bg-[#151c2e] border-[#1e2a44] hover:bg-slate-800'
                      : 'bg-[#faf9f6] border-[#dfdbd5] hover:bg-white'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-mono text-[10px] font-bold text-gray-400">
                      v{p.version}
                    </span>
                    <span className={`px-1.5 py-0.5 rounded text-[8px] font-mono font-semibold ${statusColor}`}>
                      {p.status}
                    </span>
                  </div>

                  <p className={`font-semibold tracking-tight ${isDarkMode ? 'text-white' : 'text-slate-800'}`}>
                    {p.name}
                  </p>
                  
                  <div className="flex items-center justify-between pt-2.5 mt-1 border-t border-dashed border-gray-400 border-opacity-10 text-[9px] text-gray-400 font-mono">
                    <span>分类: {p.category}</span>
                    <span>更新: {p.lastUpdated}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Side: Active Workspace editor */}
        {activePrompt && (
          <div className="flex-1 p-4 md:p-6 flex flex-col h-full overflow-y-auto pb-24">
            <div className="flex flex-col sm:flex-row items-start justify-between border-b pb-4 mb-4 gap-3">
              <div>
                <span className="inline-block px-2 py-0.5 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded font-mono text-[10px] uppercase">
                  📌 ID: {activePrompt.id} · Category: {activePrompt.category}
                </span>
                <h3 className="font-bold text-base mt-1.5 tracking-tight">{activePrompt.name}</h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  作者: {activePrompt.author} · 最后更新于: {activePrompt.lastUpdated} (版本: v{activePrompt.version})
                </p>
              </div>

              <div className="flex space-x-2 shrink-0">
                <button
                  onClick={() => handleCopyToClipboard(activePrompt.content)}
                  className="p-1.5 rounded border border-gray-300 dark:border-slate-850 hover:bg-slate-200 dark:hover:bg-slate-800 cursor-pointer text-slate-650 dark:text-slate-300"
                  title="复制核心 Prompt 模板代码"
                >
                  <Clipboard size={14} />
                </button>

                <button
                  onClick={handleSavePrompt}
                  className={`px-3 py-1.5 rounded text-xs font-semibold font-mono flex items-center space-x-1 ${getThemeAccentClass('bg')}`}
                >
                  <Lock size={12} className="mr-1" />
                  <span>签署发布 v{activePrompt.version} 版规则</span>
                </button>
              </div>
            </div>

            {/* Version control tabs */}
            <div className="flex space-x-2 border-b text-[10px] font-mono mb-4">
              <button
                onClick={() => setActiveVersionTab('current')}
                className={`py-1.5 border-b-2 px-2 ${activeVersionTab === 'current' ? 'border-[#0077b6] dark:border-[#00b4d8] font-bold text-slate-800 dark:text-white' : 'border-transparent text-gray-400'}`}
              >
                当前活动 Prompt 指令 (Code Version)
              </button>
              <button
                onClick={() => setActiveVersionTab('history')}
                className={`py-1.5 border-b-2 px-2 ${activeVersionTab === 'history' ? 'border-[#0077b6] dark:border-[#00b4d8] font-bold text-slate-800 dark:text-white' : 'border-transparent text-gray-400'}`}
              >
                版本回滚树历史 (Git branches Audit)
              </button>
            </div>

            {activeVersionTab === 'current' ? (
              <div className="space-y-4 flex flex-col flex-1">
                {/* Notion Style Instruction Warning Alert box */}
                <div className="p-3 bg-blue-50 dark:bg-slate-900 rounded-lg border border-blue-100 dark:border-slate-850 text-[11px] leading-relaxed text-blue-800 dark:text-blue-300">
                  <strong>提示：</strong> 该规则属于活动状态（ACTIVE），任何在此进行的编辑都会实时应用于与 OpenCV/Hermes AImagician 交互时的所有后台 LLM 管道与 Agent 自动流决策逻辑。
                </div>

                <div className="flex-1 flex flex-col space-y-1">
                  <span className="text-[10px] font-mono text-gray-500 font-semibold block">
                    指令主干文本 (System Instructions):
                  </span>
                  <textarea
                    value={editingContent}
                    onChange={(e) => setEditingContent(e.target.value)}
                    placeholder="（暂无指令文本，请编辑后签署发布）"
                    className={`w-full flex-1 min-h-[350px] p-4 font-mono text-xs leading-relaxed border rounded-lg focus:outline-none focus:ring-1 ${
                      isDarkMode
                        ? 'bg-[#151c2e] border-[#1e2a44] text-slate-100 focus:ring-[#00b4d8]'
                        : 'bg-white border-[#dfdbd5] text-slate-800 focus:ring-[#0077b6]'
                    }`}
                  />
                </div>
              </div>
            ) : (
              <div className="space-y-3 font-mono">
                <div className="border rounded-lg overflow-hidden dark:border-[#1e2a44]">
                  <div className="bg-slate-50 dark:bg-slate-900 border-b p-2 flex items-center justify-between text-[10px]">
                    <span>规则生命树</span>
                    <span className="text-gray-400">可以一键还原至任意历史快照点</span>
                  </div>

                  <div className="divide-y text-[11px] dark:divide-[#1e2a44]">
                    {promptVersions.length === 0 ? (
                      <div className="p-4 text-center text-gray-400 text-[10px]">
                        暂无版本历史数据
                      </div>
                    ) : promptVersions.map((v: any, i: number) => {
                      const isActive = i === 0;
                      return (
                        <div key={v.id || i} className={`p-3 flex justify-between items-center ${isActive ? 'bg-sky-50/40 dark:bg-sky-950/20' : ''}`}>
                          <div>
                            <p className={`${isActive ? 'font-bold' : 'font-semibold'} text-slate-800 dark:text-white`}>
                              {v.label || v.version_id || `v${i + 1}`} {isActive ? '(当前活动版本)' : '(历史基线)'}
                            </p>
                            <p className="text-gray-500 mt-0.5">
                              修改者: {v.created_by || 'System'} · 时间: {v.created_at ? new Date(v.created_at).toLocaleString() : '未知'}
                            </p>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            {isActive && (
                              <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 text-[10px] font-bold">
                                ACTIVE
                              </span>
                            )}
                            {!isActive && v.content && (
                              <button
                                onClick={async () => {
                                  if (!confirm('确认回滚至此版本？当前编辑内容将被覆盖。')) return;
                                  setEditingContent(v.content);
                                  setActiveVersionTab('current');
                                  try {
                                    await activatePromptVersion(activePrompt.id, v.id);
                                    const versions = await getPromptVersions(activePrompt.id);
                                    setPromptVersions(versions || []);
                                    alert(`✅ 已回滚至版本 ${v.label || v.version_id || `v${i + 1}`}`);
                                  } catch (e: any) {
                                    alert(`❌ 回滚失败: ${e?.message || '未知错误'}`);
                                  }
                                }}
                                className="px-2 py-1 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded text-[10px] font-bold dark:bg-slate-800 dark:text-slate-200"
                              >
                                回滚至该版
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
