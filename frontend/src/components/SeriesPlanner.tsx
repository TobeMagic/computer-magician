import React, { useState } from 'react';
import {
  Layers,
  ChevronDown,
  ChevronRight,
  Plus,
  HelpCircle,
  Archive,
  CheckCircle,
  Clock,
  Play,
  Bookmark
} from 'lucide-react';
import { Series, Article, ArticleStatus } from '../types';

interface SeriesPlannerProps {
  seriesList: Series[];
  setSeriesList: React.Dispatch<React.SetStateAction<Series[]>>;
  articles: Article[];
  setArticles: React.Dispatch<React.SetStateAction<Article[]>>;
  isDarkMode: boolean;
  accentColor: 'blue' | 'green' | 'brown';
  onAddMessageToAgent?: (prompt: string) => void;
  onSetTab?: (tab: string) => void;
  selectedArticleId?: string | null;
  onSelectArticle?: (id: string | null) => void;
}

export default function SeriesPlanner({
  seriesList,
  setSeriesList,
  articles,
  setArticles,
  isDarkMode,
  accentColor,
  onAddMessageToAgent,
  onSetTab,
  selectedArticleId,
  onSelectArticle
}: SeriesPlannerProps) {
  const [selectedSeriesId, setSelectedSeriesId] = useState<string>('s-1');
  const [localSearchQuery, setLocalSearchQuery] = useState<string>('');
  const [expandedVolumes, setExpandedVolumes] = useState<Record<string, boolean>>({ 'v-1': true, 'v-2': true });

  const activeSeries = seriesList.find((s) => s.id === selectedSeriesId) || seriesList[0] || null;

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

  const getStatusIndicator = (status: ArticleStatus) => {
    switch (status) {
      case '已发布':
        return <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 inline-block" title="已发布" />;
      case '待全网发布':
        return <span className="w-2.5 h-2.5 rounded-full bg-blue-500 inline-block" title="待发布" />;
      case '写作中':
        return <span className="w-2.5 h-2.5 rounded-full bg-indigo-500 inline-block animate-pulse" title="写作中" />;
      case '已合并覆盖':
        return <span className="w-2.5 h-2.5 rounded-full bg-rose-500 inline-block text-center text-[10px] leading-tight" title="已合并覆盖" />;
      default:
        return <span className="w-2.5 h-2.5 rounded-full bg-slate-300 inline-block" title={status} />;
    }
  };

  const toggleVolume = (volId: string) => {
    setExpandedVolumes((prev) => ({
      ...prev,
      [volId]: !prev[volId]
    }));
  };

  return (
    <div className={`flex-1 flex flex-col h-screen overflow-hidden ${
      isDarkMode ? 'bg-[#0f1424] text-white' : 'bg-white text-slate-800'
    }`}>
      <div className="flex-1 flex overflow-hidden">
        {/* Left planner details */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          
          {/* Series Selection Gateway with Filters */}
          <div className="p-4 rounded-xl border border-slate-150 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs space-y-3">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
              <div>
                <h4 className="font-extrabold text-[#0077b6] text-xs font-mono tracking-wide uppercase">
                  📚 长期知识系列大纲检索网关 (Series Selection Deck)
                </h4>
                <p className="text-[10px] text-gray-500">
                  一键秒级检索、筛选系列大纲章节、直观关联核心投递文章
                </p>
              </div>
            </div>

            {/* Grid list of Series options */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2.5 max-h-32 overflow-y-auto pt-0.5 pr-1">
              {seriesList
                .filter(s => s.name.toLowerCase().includes(localSearchQuery.toLowerCase()))
                .map(s => {
                  const isActive = s.id === selectedSeriesId;
                  return (
                    <div
                      key={s.id}
                      onClick={() => setSelectedSeriesId(s.id)}
                      className={`p-2 rounded-xl border text-left cursor-pointer transition-all select-none flex items-center justify-between ${
                        isActive 
                          ? 'border-blue-500 bg-blue-500/10 dark:bg-blue-950/20 shadow-xs scale-[0.99]' 
                          : 'border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/50 hover:bg-slate-100 dark:hover:bg-slate-900'
                      }`}
                    >
                      <div className="min-w-0">
                        <h5 className="font-bold text-[11px] text-slate-850 dark:text-white truncate">
                          {s.name}
                        </h5>
                        <p className="text-[9px] text-gray-400 truncate mt-0.5">{s.description}</p>
                      </div>
                      <span className="text-[9px] font-mono text-gray-500 shrink-0 ml-1">({s.volumes ? s.volumes.length : 0} 卷)</span>
                    </div>
                  );
                })}
            </div>
          </div>
          
          {/* Series Brief Info Card */}
          {activeSeries && (
          <div className="p-5 rounded-xl border border-dashed border-gray-300 dark:border-slate-850 bg-[#fdfdfd] dark:bg-slate-900/40 flex flex-col md:flex-row items-start gap-4">
            {activeSeries.coverUrl && (
              <div className="w-24 h-24 rounded-lg overflow-hidden shrink-0 border border-slate-200 dark:border-slate-800">
                <img
                  src={activeSeries.coverUrl}
                  alt={activeSeries.name}
                  className="w-full h-full object-cover"
                  referrerPolicy="no-referrer"
                />
              </div>
            )}
            <div className="flex-1 min-w-0">
              <span className="px-2 py-0.5 rounded text-[9px] font-mono font-semibold bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200">
                ACTIVE Content Engineering Cluster
              </span>
              <h3 className="font-bold text-base mt-1.5 tracking-tight">{activeSeries.name}</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 leading-relaxed">{activeSeries.description}</p>
              
              <div className="flex flex-wrap items-center gap-4 mt-3 text-[10px] font-mono text-gray-405">
                <span>美学范式: <strong className={isDarkMode ? 'text-slate-100' : 'text-slate-800'}>{activeSeries.visualStyle}</strong></span>
                <span>标题准则: <strong className={isDarkMode ? 'text-slate-100' : 'text-slate-800'}>{activeSeries.defaultTitleStyle}</strong></span>
              </div>
            </div>
          </div>
          )}

          {/* Series Volumes outline hierarchical list */}
          <div className="space-y-4">
            <h4 className="font-bold text-xs font-mono text-gray-500 uppercase tracking-wider flex items-center">
              <span>📖 系列知识拓扑大纲 ({activeSeries?.volumes?.length || 0} 卷目录架)</span>
            </h4>

            {activeSeries?.volumes?.map((vol) => {
              const VolExpanded = expandedVolumes[vol.id];
              return (
                <div
                  key={vol.id}
                  className="border rounded-lg overflow-hidden bg-white dark:bg-slate-950 border-[#e2e0db] dark:border-[#1e2a44]"
                >
                  {/* Volume Bar Header */}
                  <div
                    onClick={() => toggleVolume(vol.id)}
                    className="p-3 bg-slate-50 dark:bg-slate-905 border-b flex items-center justify-between cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-900 transition-colors"
                  >
                    <div className="flex items-center space-x-2">
                      {VolExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      <span className="font-mono text-[11px] font-bold text-indigo-500 dark:text-indigo-400">
                        {vol.id.toUpperCase()}
                      </span>
                      <span className="font-bold text-xs">{vol.name}</span>
                    </div>
                    <span className="text-[10px] text-gray-400 font-mono truncate max-w-xs">{vol.description}</span>
                  </div>

                  {/* Volume content topics */}
                  {VolExpanded && (
                    <div className="p-4 space-y-4">
                      {vol.topics?.map((top) => (
                        <div key={top.id} className="border-l-2 bg-slate-50/40 dark:bg-slate-950/20 px-3 py-2 space-y-2 border-slate-300 dark:border-slate-700">
                          <p className="font-mono text-[11px] font-bold text-gray-400">
                            Topic: {top.name}
                          </p>

                          <div className="space-y-1.5">
                            {top.articles?.map((art) => {
                              // Cross-reference current mockArticles status
                              const realArt = articles.find((ma) => ma.id === art.id);
                              const currentStatus: ArticleStatus = realArt ? realArt.status : art.status;

                              return (
                                <div
                                  key={art.id}
                                  className="flex items-center justify-between p-2 rounded text-xs border bg-white dark:bg-slate-900 border-slate-100 dark:border-slate-800"
                                >
                                  <div className="flex items-center space-x-2 min-w-0 flex-1">
                                    {getStatusIndicator(currentStatus)}
                                    <span className={`font-medium truncate ${
                                      currentStatus === '已合并覆盖' ? 'text-gray-400 line-through' : 'text-slate-800 dark:text-slate-100'
                                    }`}>
                                      {realArt ? realArt.title : art.title}
                                    </span>
                                  </div>

                                  <div className="flex items-center space-x-2 shrink-0 ml-2">
                                    <span className="text-[10px] text-gray-500 font-mono">
                                      {currentStatus}
                                    </span>

                                    <button
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        onSelectArticle?.(art.id);
                                        // Jump tab
                                        if (onSetTab) onSetTab('workbench');
                                      }}
                                      className="px-2 py-0.5 rounded text-[9px] font-semibold font-mono border hover:scale-105 transition-all text-[#0077b6] border-sky-200 hover:bg-sky-50 dark:border-sky-900/30 dark:hover:bg-slate-800"
                                    >
                                      进入写作工作台 ➔
                                    </button>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

      </div>
    </div>
  );
}
