import React from 'react';
import {
  FileText,
  Layers,
  Edit3,
  Bookmark,
  Share2,
  Key,
  Image,
  AlertTriangle,
  Cpu,
  Sun,
  Moon,
  ChevronRight,
  ChevronLeft,
  Flame,
  TrendingUp,
  Home
} from 'lucide-react';
import { ProjectStats } from '../types';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  isDarkMode: boolean;
  setIsDarkMode: (val: boolean) => void;
  accentColor: 'blue' | 'green' | 'brown';
  setAccentColor: (color: 'blue' | 'green' | 'brown') => void;
  stats: ProjectStats;
  onOpenReviewEngine: () => void;
}

export default function Sidebar({
  activeTab,
  setActiveTab,
  isDarkMode,
  setIsDarkMode,
  accentColor,
  setAccentColor,
  stats,
  onOpenReviewEngine
}: SidebarProps) {
  const [isCollapsed, setIsCollapsed] = React.useState(false);
  const [isMobileExpanded, setIsMobileExpanded] = React.useState(false);

  const menuGroups = [
    {
      title: '主干研写流 (Workflow)',
      items: [
        { id: 'dashboard', name: '控制主大盘', icon: Home, desc: '控制中心：综合运营数据、核心指标统计与全景大盘' },
        { id: 'topics', name: '独立选题策划', icon: Flame, desc: '捕获自动热点、系列选题导入与轻量预判' },
        { id: 'workbench', name: 'AI 写作工作台', icon: Edit3, desc: '全生命周期文章研写主跑道' },
        { id: 'overview', name: '历史内容中枢', icon: FileText, desc: '全生命周期文章总库与追踪' },
        { id: 'publish', name: '平台发布控制台', icon: Share2, desc: '核心与扩展矩阵发布分发' }
      ]
    },
    {
      title: '生产要素运维 (Assets Ops)',
      items: [
        { id: 'rules', name: 'Prompt 与风格管理', icon: Bookmark, desc: '提示词控制与精细化创作法则' },
        { id: 'login', name: '平台账号会话', icon: Key, desc: '零故障、Session 会话登录自愈管理' },
        { id: 'assets', name: '素材与封面管理', icon: Image, desc: '自媒体表情包与高阶 LaTeX/封面选配' }
      ]
    },
    {
      title: '审校运营闭环 (Review Loops)',
      items: [
        { id: 'analytics', name: '审校阻断与审计', icon: AlertTriangle, desc: '质量审计与自运维自修护反馈' },
        { id: 'mcp', name: 'MCP 运维控制台', icon: Cpu, desc: 'MCP Tools 注册、健康度与追踪' }
      ]
    }
  ];

  const currentActiveItemName = menuGroups
    .flatMap((group) => group.items)
    .find((item) => item.id === activeTab)?.name || '控制主大盘';

  return (
    <>
      {/* 1. Mobile Top Collapsible Navigation Header */}
      <div
        className={`flex md:hidden flex-col w-full shrink-0 border-b select-none transition-all duration-350 z-50 ${
          isDarkMode
            ? 'bg-slate-900 border-slate-800 text-slate-300'
            : 'bg-slate-50 border-slate-200 text-slate-600'
        }`}
      >
        <div className="flex items-center justify-between h-14 px-4 w-full shrink-0">
          <div className="flex items-center space-x-2.5">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center font-bold bg-gradient-to-tr from-[#0077b6] via-[#2d6a4f] to-[#7f5539] text-white text-base shadow-xs">
              🪄
            </div>
            <div>
              <span className={`font-bold text-xs uppercase ${isDarkMode ? 'text-white' : 'text-slate-850'}`}>
                AImagician
              </span>
              <span className="mx-1.5 text-gray-400 font-mono text-[10px]">/</span>
              <span className="font-bold text-xs text-blue-500 font-sans">
                {currentActiveItemName}
              </span>
            </div>
          </div>

          <div className="flex items-center space-x-1.5">
            {/* Dark theme toggle icon */}
            <button
              type="button"
              onClick={() => setIsDarkMode(!isDarkMode)}
              className={`p-1.5 rounded-md hover:bg-opacity-20 transition-all ${
                isDarkMode ? 'hover:bg-slate-700 text-yellow-500' : 'hover:bg-amber-100 text-slate-600'
              }`}
            >
              {isDarkMode ? <Sun size={13} /> : <Moon size={13} />}
            </button>

            {/* Expander Button */}
            <button
              type="button"
              onClick={() => setIsMobileExpanded(!isMobileExpanded)}
              className={`p-1.5 px-2.5 rounded-lg text-[10.5px] font-semibold flex items-center space-x-1 transition-all ${
                isMobileExpanded 
                  ? 'bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/30' 
                  : 'bg-slate-500/10 text-slate-600 dark:text-slate-300 border border-transparent'
              }`}
            >
              <span>{isMobileExpanded ? '收起 ▴' : '模块导航 ▾'}</span>
            </button>
          </div>
        </div>

        {/* Collapsible dropdown menu items */}
        {isMobileExpanded && (
          <div className="w-full max-h-[80vh] overflow-y-auto border-t border-dashed border-slate-200 dark:border-slate-800 bg-inherit flex flex-col p-4 space-y-4 animate-fade-in divide-y divide-dashed divide-slate-200/50 dark:divide-slate-800/50">
            <div className="space-y-4">
              {menuGroups.map((group) => (
                <div key={group.title} className="space-y-1.5 pt-3 first:pt-0">
                  <h3 className="px-3 text-[9px] uppercase tracking-wider font-bold text-gray-400 dark:text-gray-550 select-none">
                    {group.title}
                  </h3>

                  <div className="grid grid-cols-1 gap-1 pt-1">
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      const isActive = activeTab === item.id;
                      
                      let selectBg = '';
                      let selectText = '';
                      if (isActive) {
                        if (accentColor === 'blue') {
                          selectBg = isDarkMode ? 'bg-slate-800 text-white' : 'bg-blue-50 text-blue-700';
                        } else if (accentColor === 'green') {
                          selectBg = isDarkMode ? 'bg-slate-800 text-white' : 'bg-emerald-50 text-emerald-850';
                        } else {
                          selectBg = isDarkMode ? 'bg-slate-800 text-white' : 'bg-amber-50 text-amber-900';
                        }
                        selectText = 'font-bold text-slate-900 dark:text-white';
                      } else {
                        selectBg = isDarkMode ? 'hover:bg-slate-800/50 hover:text-slate-200' : 'hover:bg-slate-200/50 hover:text-slate-900';
                      }

                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => {
                            setActiveTab(item.id);
                            setIsMobileExpanded(false);
                          }}
                          className={`w-full flex items-center px-3 py-2.5 rounded-lg text-left transition-all ${selectBg} ${selectText}`}
                        >
                          <Icon size={14} className={`mr-3 shrink-0 ${isActive ? (accentColor === 'blue' ? 'text-blue-600 dark:text-blue-400' : accentColor === 'green' ? 'text-emerald-600' : 'text-amber-600') : 'text-slate-400'}`} />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center space-x-1.5">
                              <p className="text-xs truncate font-semibold">{item.name}</p>
                              {isActive && (
                                <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse shrink-0" title="激活" />
                              )}
                            </div>
                            <p className="text-[9px] truncate text-gray-400 font-normal leading-tight">{item.desc}</p>
                          </div>
                          {isActive && <ChevronRight size={11} className="opacity-60" />}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>

            {/* Quick stats and properties view inside mobile expander block too */}
            <div className="pt-4 space-y-4">
              <div className="grid grid-cols-2 gap-2 text-center">
                <div className="p-2.5 rounded-xl bg-slate-100/30 dark:bg-slate-950/35 border border-slate-200/50 dark:border-slate-850/50">
                  <p className="text-[9px] text-gray-500 font-mono">文章总数 / 系列数</p>
                  <p className="font-semibold text-xs mt-0.5">{stats.articleCount} 篇 / {stats.seriesCount} 组</p>
                </div>
                <div className="p-2.5 rounded-xl bg-slate-100/30 dark:bg-slate-950/35 border border-slate-200/50 dark:border-slate-850/50">
                  <p className="text-[9px] text-gray-500 font-mono">效率 / 阻塞详情</p>
                  <p className="font-semibold text-xs mt-0.5 text-amber-550">{stats.promptEfficiency} · {stats.activeBlockers} 阻塞</p>
                </div>
              </div>

              {/* Accent palette toggle on mobile */}
              <div className="flex items-center justify-between text-xs pt-1">
                <span className="text-gray-400 text-[10.5px] font-mono">定制主题视觉基底:</span>
                <div className="flex items-center space-x-3.5">
                  <button
                    type="button"
                    onClick={() => setAccentColor('blue')}
                    className={`w-5.5 h-5.5 rounded-full bg-blue-600 flex items-center justify-center text-white text-[9.5px] border transition-transform ${
                      accentColor === 'blue' ? 'scale-110 ring-2 ring-blue-400' : 'opacity-60 hover:opacity-100'
                    }`}
                  >
                    {accentColor === 'blue' ? '✓' : ''}
                  </button>
                  <button
                    type="button"
                    onClick={() => setAccentColor('green')}
                    className={`w-5.5 h-5.5 rounded-full bg-emerald-600 flex items-center justify-center text-white text-[9.5px] border transition-transform ${
                      accentColor === 'green' ? 'scale-110 ring-2 ring-emerald-400' : 'opacity-60 hover:opacity-100'
                    }`}
                  >
                    {accentColor === 'green' ? '✓' : ''}
                  </button>
                  <button
                    type="button"
                    onClick={() => setAccentColor('brown')}
                    className={`w-5.5 h-5.5 rounded-full bg-amber-800 flex items-center justify-center text-white text-[9.5px] border transition-transform ${
                      accentColor === 'brown' ? 'scale-110 ring-2 ring-amber-500' : 'opacity-60 hover:opacity-100'
                    }`}
                  >
                    {accentColor === 'brown' ? '✓' : ''}
                  </button>
                </div>
              </div>

              {/* Quality Audit engine trigger on mobile */}
              <button
                type="button"
                onClick={() => {
                  onOpenReviewEngine();
                  setIsMobileExpanded(false);
                }}
                className="w-full py-2.5 rounded-xl text-center bg-amber-500/10 hover:bg-amber-500/20 text-amber-550 border border-amber-500/20 active:scale-[0.98] transition-all text-xs font-bold font-mono"
              >
                💡 运行质量阻断及审交复盘引擎 ➔
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 2. Desktop Vertical Collapsible Sidebar */}
      <div
        className={`${
          isCollapsed ? 'md:w-16' : 'md:w-72'
        } border-r hidden md:flex flex-col h-screen select-none transition-all duration-300 shrink-0 ${
          isDarkMode
            ? 'bg-slate-900 border-slate-800 text-slate-300'
            : 'bg-slate-50 border-slate-200 text-slate-600'
        }`}
      >
        {/* Brand Header */}
        <div className={`p-4 pb-3 border-b flex items-center ${
          isCollapsed ? 'flex-col space-y-3 justify-center' : 'justify-between'
        } ${
          isDarkMode ? 'border-slate-800' : 'border-slate-200'
        }`}>
          {isCollapsed ? (
            <div className="flex flex-col items-center space-y-3">
              <div 
                onClick={() => setIsCollapsed(false)}
                className="w-8 h-8 rounded-lg flex items-center justify-center font-bold bg-gradient-to-tr from-[#0077b6] via-[#2d6a4f] to-[#7f5539] text-white text-base shadow-sm cursor-pointer hover:scale-105 transition-transform" 
                title="点击展开导航栏"
              >
                🪄
              </div>
              <button
                onClick={() => setIsCollapsed(false)}
                className="p-1.5 rounded-md hover:bg-slate-500/20 text-gray-400 hover:text-slate-200 transition-all cursor-pointer"
                title="展开导航栏"
              >
                <ChevronRight size={14} className="animate-pulse" />
              </button>
            </div>
          ) : (
            <>
              <div className="flex items-center space-x-2">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center font-bold bg-gradient-to-tr from-[#0077b6] via-[#2d6a4f] to-[#7f5539] text-white text-base shadow-sm">
                  🪄
                </div>
                <div className="min-w-0">
                  <h1 className={`font-semibold text-sm tracking-tight truncate ${isDarkMode ? 'text-white' : 'text-[#1e293b]'}`}>
                    AImagician
                  </h1>
                  <p className="text-[9px] uppercase tracking-widest font-mono text-gray-500 truncate">
                    Content Runtime
                  </p>
                </div>
              </div>

              <div className="flex items-center space-x-1 shrink-0">
                {/* Global Night Mode Switch */}
                <button
                  onClick={() => setIsDarkMode(!isDarkMode)}
                  className={`p-1.5 rounded-md hover:bg-opacity-20 transition-all ${
                    isDarkMode ? 'hover:bg-slate-700 text-yellow-400' : 'hover:bg-amber-100 text-slate-500'
                  }`}
                  title={isDarkMode ? '切换到白昼明亮模式' : '切换到夜间静谧模式'}
                >
                  {isDarkMode ? <Sun size={13} /> : <Moon size={13} />}
                </button>

                {/* Collapse Button */}
                <button
                  onClick={() => setIsCollapsed(true)}
                  className="p-1.5 rounded-md hover:bg-opacity-20 hover:bg-slate-500/20 text-gray-400 hover:text-slate-300 transition-all cursor-pointer"
                  title="收起导航栏"
                >
                  <ChevronLeft size={13} />
                </button>
              </div>
            </>
          )}
        </div>

        {/* Workspace Quick Spec */}
        {!isCollapsed && (
          <div className={`p-4 mx-3 my-3 rounded-lg border flex flex-col space-y-2 text-xs transition-colors ${
            isDarkMode
              ? 'bg-slate-955 border-slate-850 text-slate-400'
              : 'bg-white border-slate-200 text-slate-600 shadow-sm'
          }`}>
            <div className="flex items-center justify-between">
              <span className="font-semibold text-[10px] tracking-widest uppercase font-mono">
                工作空间状态
              </span>
              <span className="flex h-2 w-2 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 pt-1">
              <div>
                <p className="text-[10px] text-gray-500">文章总数 / 系列</p>
                <p className={`font-mono font-semibold text-sm ${isDarkMode ? 'text-white' : 'text-slate-800'}`}>
                  {stats.articleCount} 篇 / {stats.seriesCount} 组
                </p>
              </div>
              <div>
                <p className="text-[10px] text-gray-500">提示词执行效率</p>
                <p className={`font-mono font-semibold text-sm ${isDarkMode ? 'text-[#52b788]' : 'text-[#2d6a4f]'}`}>
                  {stats.promptEfficiency}
                </p>
              </div>
            </div>

            <div className="flex items-center justify-between pt-1 font-mono text-[10px] border-t border-dashed border-gray-400 border-opacity-30">
              <span className="text-amber-500 font-bold">● {stats.activeBlockers} 阻塞</span>
              <span className="text-blue-400 font-bold">● {stats.activeWarnings} 警告</span>
            </div>
          </div>
        )}

        {/* Nav Menu Items Grouped */}
        <div className={`flex-1 ${isCollapsed ? 'px-1' : 'px-2'} pb-4 space-y-4 overflow-y-auto`}>
          {menuGroups.map((group) => (
            <div key={group.title} className="space-y-1">
              {!isCollapsed && (
                <h3 className="px-3 text-[9px] uppercase tracking-wider font-bold text-gray-400 dark:text-gray-550 select-none">
                  {group.title}
                </h3>
              )}

              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive = activeTab === item.id;
                
                let selectBg = '';
                let selectText = '';
                if (isActive) {
                  if (accentColor === 'blue') {
                    selectBg = isDarkMode ? 'bg-slate-800 text-white' : 'bg-blue-50 text-blue-700';
                    selectBg += isCollapsed ? ' border-r-4 border-blue-400' : ' border-l-4 border-blue-600';
                  } else if (accentColor === 'green') {
                    selectBg = isDarkMode ? 'bg-slate-800 text-white' : 'bg-emerald-50 text-emerald-850';
                    selectBg += isCollapsed ? ' border-r-4 border-emerald-400' : ' border-l-4 border-emerald-600';
                  } else {
                    selectBg = isDarkMode ? 'bg-slate-800 text-white' : 'bg-amber-50 text-amber-900';
                    selectBg += isCollapsed ? ' border-r-4 border-amber-500' : ' border-l-4 border-amber-700';
                  }
                  selectText = 'font-semibold text-slate-900 dark:text-white';
                } else {
                  selectBg = isDarkMode ? 'hover:bg-slate-800/50 hover:text-slate-200' : 'hover:bg-slate-200/50 hover:text-slate-900';
                }

                if (isCollapsed) {
                  return (
                    <button
                      key={item.id}
                      onClick={() => setActiveTab(item.id)}
                      className={`w-10 h-10 flex items-center justify-center rounded-lg transition-all mx-auto relative ${selectBg} ${selectText}`}
                      title={`${item.name} — ${item.desc}`}
                    >
                      <Icon size={16} className={`${isActive ? (accentColor === 'blue' ? 'text-blue-500 dark:text-blue-400' : accentColor === 'green' ? 'text-emerald-500 dark:text-emerald-405' : 'text-amber-500 dark:text-amber-400') : 'text-slate-400'}`} />
                    </button>
                  );
                }

                return (
                  <button
                    key={item.id}
                    onClick={() => setActiveTab(item.id)}
                    className={`w-full flex items-center px-3 py-2 rounded-md text-left transition-all ${selectBg} ${selectText}`}
                    title={`${item.name} — ${item.desc}`}
                  >
                    <Icon size={14} className={`mr-3 shrink-0 ${isActive ? (accentColor === 'blue' ? 'text-blue-600 dark:text-blue-400' : accentColor === 'green' ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-750 dark:text-amber-405') : 'text-slate-400'}`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center space-x-1.5">
                        <p className={`text-xs truncate font-semibold ${isActive ? (isDarkMode ? 'text-white' : (accentColor === 'blue' ? 'text-blue-900' : accentColor === 'green' ? 'text-emerald-950' : 'text-amber-955')) : 'text-slate-700 dark:text-slate-300'}`}>{item.name}</p>
                        {isActive && (
                          <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse shrink-0" title="当前激活" />
                        )}
                      </div>
                      <p className={`text-[9px] truncate font-normal leading-tight ${isActive ? (isDarkMode ? 'text-slate-400' : (accentColor === 'blue' ? 'text-blue-600' : accentColor === 'green' ? 'text-emerald-700' : 'text-amber-850')) : 'text-slate-400 dark:text-slate-500'}`}>{item.desc}</p>
                    </div>
                    {isActive && <ChevronRight size={11} className="opacity-60" />}
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        {/* Quality Review Engine Shortcut */}
        <div className={`p-3 border-t text-center shrink-0 ${
          isDarkMode ? 'border-slate-800 bg-slate-950/40' : 'border-slate-200 bg-slate-50'
        }`}>
          {isCollapsed ? (
            <button
              type="button"
              onClick={onOpenReviewEngine}
              className="w-10 h-10 mx-auto flex items-center justify-center p-2 rounded-xl font-bold transition-all bg-amber-500/10 hover:bg-amber-500/20 text-amber-550 border border-amber-500/20 active:scale-95"
              title="💡 随时复盘/质量引擎"
            >
              <TrendingUp size={15} className="animate-pulse" />
            </button>
          ) : (
            <button
              type="button"
              onClick={onOpenReviewEngine}
              className="w-full flex items-center justify-center space-x-1.5 p-2 px-3 rounded-lg font-bold text-[10.5px] transition-all bg-amber-500/10 hover:bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/20 active:scale-95"
              title="随时创建自媒体持续优化与质量复盘任务"
            >
              <TrendingUp size={12} className="animate-pulse" />
              <span>💡 随时复盘/质量引擎</span>
            </button>
          )}
        </div>

        {/* Accent Color Custom Picker */}
        {!isCollapsed ? (
          <div className={`p-4 border-t flex flex-col space-y-2 text-xs ${
            isDarkMode ? 'border-slate-800 bg-slate-950' : 'border-slate-200 bg-slate-100'
          }`}>
            <div className="flex items-center justify-between text-[11px] font-mono">
              <span className="text-gray-500">主视觉基调</span>
              <span className="font-semibold uppercase text-[10px]">
                {accentColor === 'blue' && '海蓝 (Sea Blue)'}
                {accentColor === 'green' && '森林绿 (Forest Green)'}
                {accentColor === 'brown' && '暖棕 (Warm Brown)'}
              </span>
            </div>
            <div className="flex items-center space-x-3 pt-1">
              <button
                onClick={() => setAccentColor('blue')}
                className={`w-5 h-5 rounded-full bg-blue-600 flex items-center justify-center text-white text-[10px] border transition-transform ${
                  accentColor === 'blue' ? 'scale-125 ring-2 ring-blue-400' : 'opacity-70 hover:opacity-100'
                }`}
                title="海蓝"
              >
                {accentColor === 'blue' && '✓'}
              </button>
              <button
                onClick={() => setAccentColor('green')}
                className={`w-5 h-5 rounded-full bg-emerald-600 flex items-center justify-center text-white text-[10px] border transition-transform ${
                  accentColor === 'green' ? 'scale-125 ring-2 ring-emerald-400' : 'opacity-70 hover:opacity-100'
                }`}
                title="森林绿"
              >
                {accentColor === 'green' && '✓'}
              </button>
              <button
                onClick={() => setAccentColor('brown')}
                className={`w-5 h-5 rounded-full bg-amber-800 flex items-center justify-center text-white text-[10px] border transition-transform ${
                  accentColor === 'brown' ? 'scale-125 ring-2 ring-amber-500' : 'opacity-70 hover:opacity-100'
                }`}
                title="暖棕"
              >
                {accentColor === 'brown' && '✓'}
              </button>
            </div>
          </div>
        ) : (
          <div className={`p-2 border-t flex justify-center items-center ${
            isDarkMode ? 'border-slate-800 bg-slate-900/45' : 'border-slate-200 bg-slate-100/50'
          }`}>
            <div className="flex flex-row gap-1 items-center">
              <button
                type="button"
                onClick={() => setAccentColor('blue')}
                className={`w-2 h-2 rounded-full bg-blue-600 cursor-pointer transition-all hover:scale-125 focus:outline-none ${
                  accentColor === 'blue' ? 'ring-1 ring-blue-400 scale-110 opacity-100' : 'opacity-50 hover:opacity-100'
                }`}
                title="海蓝"
              />
              <button
                type="button"
                onClick={() => setAccentColor('green')}
                className={`w-2 h-2 rounded-full bg-emerald-600 cursor-pointer transition-all hover:scale-125 focus:outline-none ${
                  accentColor === 'green' ? 'ring-1 ring-emerald-400 scale-110 opacity-100' : 'opacity-50 hover:opacity-100'
                }`}
                title="森林绿"
              />
              <button
                type="button"
                onClick={() => setAccentColor('brown')}
                className={`w-2 h-2 rounded-full bg-amber-600 cursor-pointer transition-all hover:scale-125 focus:outline-none ${
                  accentColor === 'brown' ? 'ring-1 ring-amber-500 scale-110 opacity-100' : 'opacity-50 hover:opacity-100'
                }`}
                title="暖棕"
              />
            </div>
          </div>
        )}

        {/* Footer Info */}
        <div className={`p-3 text-[9px] text-center border-t select-none truncate ${
          isDarkMode ? 'border-slate-800 text-slate-600' : 'border-slate-200 text-slate-400'
        }`}>
          {isCollapsed ? 'AM' : 'AImagician runtime'}
        </div>
      </div>
    </>
  );
}
