import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Dashboard from './components/Dashboard';
import HomeDashboard from './components/HomeDashboard';
import LoginScreen from './components/LoginScreen';
import PromptManager from './components/PromptManager';
import PublishingControl from './components/PublishingControl';
import AccountManager from './components/AccountManager';
import AssetLibrary from './components/AssetLibrary';
import AnalyticsPanel from './components/AnalyticsPanel';
import McpConsole from './components/McpConsole';
import TopicManager from './components/TopicManager';
import GlobalSelector from './components/GlobalSelector';
import WritingWorkbench from './components/WritingWorkbench';
import ReviewEngineModal from './components/ReviewEngineModal';

import { Article, Series, PromptRule, PlatformCredential, OptimizerTask } from './types';
import { isAuthenticated, getSession, logout, createPrompt, initAuth, setCsrfToken } from './api';
import { useApiData } from './hooks/useApiData';
import { demoMode } from './demo/fixtures';

export default function App() {
  // Authentication state (must be declared before useApiData)
  const [isLoggedIn, setIsLoggedIn] = useState<boolean>(demoMode || isAuthenticated());
  const [currentUserEmail, setCurrentUserEmail] = useState<string>(demoMode ? '演示访客' : '');
  const [authLoading, setAuthLoading] = useState<boolean>(!demoMode);

  const {
    articles,
    setArticles,
    seriesList,
    promptRules,
    setPromptRules,
    credentials,
    setCredentials,
    optimizerTasks,
    setOptimizerTasks,
    dashboardStats,
  } = useApiData(isLoggedIn);

  // Global selections synced across pages
  const [globalSelectedArticleId, setGlobalSelectedArticleId] = useState<string>(articles[0]?.id || '');
  const [globalSelectedSeriesId, setGlobalSelectedSeriesId] = useState<string>(seriesList[0]?.id || '');
  const [globalSearchQuery, setGlobalSearchQuery] = useState<string>('');

  // App Layout States
  const [activeTab, setActiveTab] = useState<string>('dashboard');
  const [workbenchSubTab, setWorkbenchSubTab] = useState<string>('confirm');
  const [isDarkMode, setIsDarkMode] = useState<boolean>(false);
  const [accentColor, setAccentColor] = useState<'blue' | 'green' | 'brown'>('blue');
  const [isReviewOpen, setIsReviewOpen] = useState<boolean>(false);

  // Check session on mount
  useEffect(() => {
    if (demoMode) return;
    const checkSession = async () => {
      initAuth();
      try {
        const session = await getSession();
        if (session.authenticated && session.user) {
          setCurrentUserEmail(session.user.email);
          setIsLoggedIn(true);
        } else {
          setIsLoggedIn(false);
        }
      } catch {
        setIsLoggedIn(false);
      } finally {
        setAuthLoading(false);
      }
    };
    checkSession();
  }, []);

  // Reset query on tab change
  React.useEffect(() => {
    setGlobalSearchQuery('');
  }, [activeTab]);

  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      setIsLoggedIn(false);
    }
  };

  const handleAddPromptRule = async () => {
    try {
      const newPrompt = await createPrompt({
        label: '新拟开发生成规则 - 草案 (Prompt Draft)',
        domain: 'Outline' as any,
        purpose: '用于引导生文大纲决策层，精确削减25%无用修辞，强化硬核代码比例。',
      });
      
      const newRule: PromptRule = {
        id: newPrompt.id || `p-${Date.now()}`,
        name: newPrompt.label || '新拟开发生成规则',
        category: (newPrompt.domain || 'Outline') as PromptRule['category'],
        content: `# 定位与约束：\n- 本条规则由管理员端动态增添。\n- 用于引导生文大纲决策层，精确削减25%无用修辞，强化硬核代码比例。`,
        status: 'Draft',
        version: '1.0.0',
        lastUpdated: new Date().toISOString().split('T')[0],
        author: 'Admin'
      };
      setPromptRules(prev => [newRule, ...prev]);
      alert(`✅ 新 Prompt 规则已创建！ID: ${newPrompt.id}`);
    } catch (error: any) {
      alert(`❌ 创建失败: ${error?.message || '请检查网络连接'}`);
    }
  };

  const getThemeAccentClass = (type: 'text') => {
    if (accentColor === 'green') return 'text-emerald-600 dark:text-emerald-400';
    if (accentColor === 'brown') return 'text-amber-700 dark:text-amber-400';
    return 'text-blue-600 dark:text-blue-400 font-bold';
  };

  const getTabTitleInfo = () => {
    switch (activeTab) {
      case 'dashboard': return { ch: '控制主大盘', en: 'Control Dashboard Center', status: '看板就绪: 实时系统运营数据已连通' };
      case 'topics': return { ch: '独立选题策划', en: 'Topic Incubation Hub', status: '引擎就绪: 发现高概率技术爆款 4 个' };
      case 'workbench': return { ch: 'AI 写作工作台', en: 'AI Writing Workbench', status: '主干跑道: 大纲签署与流水线生成中' };
      case 'overview': return { ch: '历史内容中枢', en: 'Content Repository', status: '同步中: 本地与全网发布状态对齐' };
      case 'publish': return { ch: '平台发布控制台', en: 'Publishing Syndicate', status: '矩阵就绪: 28 平台就绪对接' };
      case 'planner': return { ch: '长期系列规划', en: 'Series Planner Hub', status: '效能规划: 7 卷目录大纲已锁定' };
      case 'rules': return { ch: 'Prompt 与风格管理', en: 'PromptOps & Custom Styles', status: '流控合规: 规则集编译就绪' };
      case 'login': return { ch: '平台账号会话', en: 'Platform Session & Accounts', status: '会话安全: 零故障自愈网络激活' };
      case 'assets': return { ch: '素材与封面管理', en: 'Asset Library', status: '素材就绪: 选配高精度 LaTeX 支持' };
      case 'analytics': return { ch: '审校阻断与审计', en: 'Analytics & Optimizer', status: '风控扫描: 质量状态正常' };
      case 'mcp': return { ch: 'MCP 运维控制台', en: 'MCP DevOps Console', status: 'Host 守护进程「V3.2」正常挂载' };
      default: return { ch: '系统工作台', en: 'Workspace Selector', status: '运行正常' };
    }
  };

  const titleInfo = getTabTitleInfo();

  // Interactive dynamic stats computing based on active content databases
  const computedStats = {
    articleCount: dashboardStats.articleCount,
    seriesCount: dashboardStats.seriesCount,
    failedPublishes: dashboardStats.failedPublishes,
    activeBlockers: dashboardStats.activeBlockers,
    activeWarnings: dashboardStats.activeWarnings,
    promptEfficiency: dashboardStats.promptEfficiency,
    overallProgress: dashboardStats.overallProgress
  };

  if (authLoading) {
    return (
      <div className="flex items-center justify-center w-screen h-screen bg-white dark:bg-[#090d16]">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-xs text-gray-500 font-mono">检查登录状态...</p>
        </div>
      </div>
    );
  }

  if (!isLoggedIn) {
    return (
      <LoginScreen
        onLoginSuccess={(email) => {
          setCurrentUserEmail(email);
          setIsLoggedIn(true);
          setActiveTab('dashboard');
        }}
        isDarkMode={isDarkMode}
        setIsDarkMode={setIsDarkMode}
        accentColor={accentColor}
      />
    );
  }

  return (
    <div className={`flex flex-col md:flex-row w-screen h-screen overflow-hidden font-sans transition-colors duration-300 ${
      isDarkMode ? 'bg-[#090d16] text-[#e2e8f0]' : 'bg-[#fafdff] text-slate-800'
    }`}>
      {/* Sidebar Navigation */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        isDarkMode={isDarkMode}
        setIsDarkMode={setIsDarkMode}
        accentColor={accentColor}
        setAccentColor={setAccentColor}
        stats={computedStats}
        onOpenReviewEngine={() => setIsReviewOpen(true)}
      />

      {/* Main Panel Viewport */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        {/* Dynamic Synced Top Action Bar matching Active Tab criteria */}
        <div className={`px-6 py-3 border-b flex items-center justify-between select-none shrink-0 ${
          isDarkMode ? 'border-slate-800 bg-[#0c1220] text-slate-100' : 'border-slate-200 bg-white shadow-xs'
        }`}>
          <div className="flex items-center space-x-2 text-xs font-mono">
            <span className="text-gray-400 lowercase">workspace</span>
            <span className="text-gray-500">/</span>
            <span className={`${getThemeAccentClass('text')} font-bold text-slate-805 dark:text-white uppercase`}>{titleInfo.ch}</span>
            {demoMode && <span className="ml-2 rounded-full border border-amber-400/40 bg-amber-400/10 px-2 py-0.5 text-[10px] text-amber-700 dark:text-amber-300">静态演示</span>}
            <span className="text-[10px] text-gray-400 font-normal">({titleInfo.en})</span>
          </div>

          <div className="flex items-center space-x-4">
            <div className="hidden md:flex items-center space-x-2 font-mono text-[10px] text-gray-400 border-r border-[#e2e0db] dark:border-slate-800 pr-4">
              <span className="flex h-1.5 w-1.5 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500"></span>
              </span>
              <span>{titleInfo.status}</span>
            </div>

            {activeTab !== 'assets' && activeTab !== 'overview' && activeTab !== 'mcp' && (
              <div className="flex items-center space-x-2">
                <GlobalSelector
                  articles={articles}
                  seriesList={seriesList}
                  selectedArticleId={globalSelectedArticleId}
                  selectedSeriesId={globalSelectedSeriesId}
                  onSelectArticle={setGlobalSelectedArticleId}
                  onSelectSeries={setGlobalSelectedSeriesId}
                  isDarkMode={isDarkMode}
                  accentColor={accentColor}
                  globalSearchQuery={globalSearchQuery}
                  setGlobalSearchQuery={setGlobalSearchQuery}
                  activeTab={activeTab}
                  promptRules={promptRules}
                />
              </div>
            )}
          </div>
        </div>

        {activeTab === 'dashboard' && (
          <HomeDashboard
            articles={articles}
            seriesList={seriesList}
            stats={computedStats}
            onSetTab={setActiveTab}
            isDarkMode={isDarkMode}
            accentColor={accentColor}
            currentUserEmail={currentUserEmail}
            onLogout={handleLogout}
          />
        )}

        {activeTab === 'topics' && (
          <TopicManager
            articles={articles}
            setArticles={setArticles}
            seriesList={seriesList}
            isDarkMode={isDarkMode}
            accentColor={accentColor}
            onSetTab={setActiveTab}
            selectedArticleId={globalSelectedArticleId}
            selectedSeriesId={globalSelectedSeriesId}
            onSelectArticle={setGlobalSelectedArticleId}
            onSelectSeries={setGlobalSelectedSeriesId}
            globalSearchQuery={globalSearchQuery}
          />
        )}

        {activeTab === 'workbench' && (
          <WritingWorkbench
            articles={articles}
            setArticles={setArticles}
            isDarkMode={isDarkMode}
            accentColor={accentColor}
            onSetTab={setActiveTab}
            credentials={credentials}
            setCredentials={setCredentials}
            selectedArticleId={globalSelectedArticleId}
            onSelectArticle={setGlobalSelectedArticleId}
            selectedSeriesId={globalSelectedSeriesId}
            onSelectSeries={setGlobalSelectedSeriesId}
            seriesList={seriesList}
            initialSubTab={workbenchSubTab}
            onSetSubTab={setWorkbenchSubTab}
          />
        )}

        {activeTab === 'overview' && (
          <Dashboard
            articles={articles}
            setArticles={setArticles}
            isDarkMode={isDarkMode}
            accentColor={accentColor}
            onSetTab={setActiveTab}
            onSetWorkbenchSubTab={setWorkbenchSubTab}
            globalSearchQuery={globalSearchQuery}
            onSelectArticle={setGlobalSelectedArticleId}
          />
        )}

        {activeTab === 'rules' && (
          <PromptManager
            promptRules={promptRules}
            setPromptRules={setPromptRules}
            isDarkMode={isDarkMode}
            accentColor={accentColor}
          />
        )}

        {activeTab === 'publish' && (
          <PublishingControl
            articles={articles}
            setArticles={setArticles}
            isDarkMode={isDarkMode}
            accentColor={accentColor}
          />
        )}

        {activeTab === 'login' && (
          <AccountManager
            credentials={credentials}
            setCredentials={setCredentials}
            isDarkMode={isDarkMode}
            accentColor={accentColor}
          />
        )}

        {activeTab === 'assets' && (
          <AssetLibrary
            isDarkMode={isDarkMode}
            accentColor={accentColor}
            articles={articles}
            setArticles={setArticles}
            globalSearchQuery={globalSearchQuery}
          />
        )}

        {activeTab === 'analytics' && (
          <AnalyticsPanel
            optimizerTasks={optimizerTasks}
            setOptimizerTasks={setOptimizerTasks}
            isDarkMode={isDarkMode}
            accentColor={accentColor}
            articles={articles}
          />
        )}

        {activeTab === 'mcp' && (
          <McpConsole
            isDarkMode={isDarkMode}
            accentColor={accentColor}
          />
        )}
      </div>

      {/* Global Suspended Review and Optimization Task Hub */}
      <ReviewEngineModal
        articles={articles}
        optimizerTasks={optimizerTasks}
        setOptimizerTasks={setOptimizerTasks}
        isDarkMode={isDarkMode}
        accentColor={accentColor}
        isOpen={isReviewOpen}
        setIsOpen={setIsReviewOpen}
      />
    </div>
  );
}
